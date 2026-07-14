"""
Integration test: GET /api/jobs/{id} survives a process restart (spec AC-2/AC-3).

A job that completed in one app instance is retrievable in a new instance on the
same DB, with the same status fields (byte-identical for completed jobs, AC-3).
"""

import app.config as _cfg
from app.runner.migrations import upgrade_to_head


def _make_client(monkeypatch, tmp_path, job_store_path, checkpoints_path, report_dir):
    from app.api.main import create_app
    from starlette.testclient import TestClient

    stem = "restart_contract"
    md_path = report_dir / f"{stem}.md"
    json_path = report_dir / f"{stem}.json"
    md_path.write_text("# Risk Report")
    json_path.write_text("{}")

    def _fake_build_graph(checkpointer=None):
        class _FG:
            def stream(self, initial, stream_mode=None, config=None):
                doc = (initial or {}).get("document_path", "c.pdf")
                for node in ["ingest_agent", "clause_splitter", "risk_score"]:
                    yield {"current_node": node, "document_path": doc}
                yield {
                    "current_node": "report",
                    "document_path": doc,
                    "report_path": str(md_path),
                    "document_id": stem,
                }

        return _FG()

    monkeypatch.setattr("app.runner.core.build_graph", _fake_build_graph)
    monkeypatch.setattr(
        "app.runner.core.deliver_report_sync",
        lambda state, *, recipient=None: {"mcp_delivery_status": {}},
    )
    monkeypatch.setattr(_cfg, "UPLOAD_DIR", str(tmp_path / "uploads"))
    monkeypatch.setattr(_cfg, "JOB_STORE_DB_PATH", job_store_path)
    monkeypatch.setattr(_cfg, "CHECKPOINTER_DB_PATH", checkpoints_path)
    monkeypatch.setattr(_cfg, "STARTUP_RECOVERY_ENABLED", False)
    monkeypatch.setenv("AUTH_SECRET", "restart_test_secret_" + "x" * 20)
    monkeypatch.setattr(_cfg, "AUTH_SECRET_FILE", str(tmp_path / "auth_secret"))

    return TestClient(create_app())


def test_restart_get_survives(monkeypatch, tmp_path):
    """Completed job is retrievable after a full app restart on the same DBs (spec AC-2)."""
    report_dir = tmp_path / "reports"
    report_dir.mkdir()
    job_store = str(tmp_path / "job_store.db")
    checkpoints = str(tmp_path / "checkpoints.db")

    # First app instance: submit and complete a job
    with _make_client(monkeypatch, tmp_path, job_store, checkpoints, report_dir) as c1:
        from tests.integration.conftest import authenticate
        authenticate(c1)
        r = c1.post(
            "/api/analyze",
            files={"file": ("c.pdf", b"%PDF", "application/pdf")},
        )
        assert r.status_code == 202
        job_id = r.json()["job_id"]

        import time
        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline:
            resp = c1.get(f"/api/jobs/{job_id}")
            if resp.status_code == 200 and resp.json().get("status") == "completed":
                first_status = resp.json()
                break
            time.sleep(0.05)
        else:
            raise TimeoutError("Job did not complete in first app instance")

    # Second app instance on the SAME DBs (recovery disabled)
    with _make_client(monkeypatch, tmp_path, job_store, checkpoints, report_dir) as c2:
        from tests.integration.conftest import authenticate
        authenticate(c2)  # idempotent: 409 signup → login (user row persists in same DB)
        r2 = c2.get(f"/api/jobs/{job_id}")
        assert r2.status_code == 200, f"Expected 200, got {r2.status_code}: {r2.text}"
        second_status = r2.json()

    # Status fields are identical (AC-3)
    assert second_status["status"] == "completed"
    assert second_status["job_id"] == job_id
    assert second_status["submitted_at"] == first_status["submitted_at"]
    assert second_status["finished_at"] == first_status["finished_at"]
