"""
Integration test: ingest_error path persists durably; a failed job is not resumed (spec AC-16/17).
"""

import time

import app.config as _cfg
from app.runner.migrations import upgrade_to_head


def _make_client(monkeypatch, tmp_path, job_store_path, checkpoints_path, recovery_on=False):
    from app.api.main import create_app
    from starlette.testclient import TestClient

    def _fake_build_graph(checkpointer=None):
        class _FG:
            def stream(self, initial, stream_mode=None, config=None):
                doc = (initial or {}).get("document_path", "c.pdf")
                yield {
                    "current_node": "ingest_agent",
                    "document_path": doc,
                    "ingest_error": {"message": "bad pdf", "error_type": "ParseError"},
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
    monkeypatch.setattr(_cfg, "STARTUP_RECOVERY_ENABLED", recovery_on)
    monkeypatch.setenv("AUTH_SECRET", "ingest_error_test_secret_" + "x" * 16)
    monkeypatch.setattr(_cfg, "AUTH_SECRET_FILE", str(tmp_path / "auth_secret"))

    return TestClient(create_app())


def _wait_for(client, job_id, target, timeout=5.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        r = client.get(f"/api/jobs/{job_id}")
        if r.status_code == 200 and r.json().get("status") == target:
            return r.json()
        time.sleep(0.05)
    raise TimeoutError(f"Job {job_id!r} did not reach {target!r}")


def test_ingest_error_survives_restart(monkeypatch, tmp_path):
    """Job completed with ingest_error is visible after a rebuild on same DB (spec AC-16)."""
    job_store = str(tmp_path / "job_store.db")
    checkpoints = str(tmp_path / "checkpoints.db")

    # First instance: submit + get completed with error
    with _make_client(monkeypatch, tmp_path, job_store, checkpoints, recovery_on=False) as c1:
        from tests.integration.conftest import authenticate
        authenticate(c1)
        r = c1.post(
            "/api/analyze",
            files={"file": ("c.pdf", b"%PDF", "application/pdf")},
        )
        assert r.status_code == 202
        job_id = r.json()["job_id"]
        status = _wait_for(c1, job_id, "completed")
        assert status["error"] is not None
        assert status["error"]["kind"] == "ingest_error"

    # Second instance on same DB (recovery disabled): GET still returns completed+error
    with _make_client(monkeypatch, tmp_path, job_store, checkpoints, recovery_on=False) as c2:
        from tests.integration.conftest import authenticate
        authenticate(c2)
        r2 = c2.get(f"/api/jobs/{job_id}")
        assert r2.status_code == 200
        s2 = r2.json()
        assert s2["status"] == "completed"
        assert s2["error"]["kind"] == "ingest_error"


def test_failed_job_not_resumed_on_restart(monkeypatch, tmp_path):
    """A failed job is NOT re-run on startup (spec AC-17 — terminal, per AC-14)."""
    from app.runner.models import JobState
    from app.runner.store import JobRow, JobStore

    job_store = str(tmp_path / "job_store.db")
    checkpoints = str(tmp_path / "checkpoints.db")
    upgrade_to_head(job_store)

    store = JobStore(job_store)
    store.upsert(
        JobRow(
            job_id="pre-failed",
            document_path="/f.pdf",
            recipient=None,
            status=JobState.failed,
            submitted_at="2026-01-01T00:00:00+00:00",
            started_at="2026-01-01T00:01:00+00:00",
            finished_at="2026-01-01T00:02:00+00:00",
            current_node=None,
            completed_nodes=[],
            report_path=None,
            mcp_delivery_status={},
            error=None,
        )
    )
    store.close()

    # Build app with recovery ON — failed job must remain failed, not re-run
    with _make_client(monkeypatch, tmp_path, job_store, checkpoints, recovery_on=True) as c:
        from tests.integration.conftest import authenticate
        authenticate(c)
        import time
        time.sleep(0.2)  # give recovery time to run

        r = c.get("/api/jobs/pre-failed")
        assert r.status_code == 200
        assert r.json()["status"] == "failed"
