"""
Integration tests for GET /api/jobs/{job_id} and GET /api/health.

TDD red phase: all tests FAIL (ImportError) until Task 19 implements create_app.
Run: python -m pytest tests/integration/test_api_jobs.py -v
"""

import time
from dataclasses import dataclass
from typing import Optional

from tests.integration.conftest import _wait_for


@dataclass
class _FakeRunResult:
    final_state: dict
    report_path: Optional[str]
    mcp_delivery_status: dict
    ingest_error: Optional[dict]


def _happy_result(doc="c.pdf"):
    return _FakeRunResult(
        final_state={},
        report_path="r.md",
        mcp_delivery_status={},
        ingest_error=None,
    )


def _submit(client, filename="c.pdf"):
    r = client.post(
        "/api/analyze",
        files={"file": (filename, b"%PDF-1.4", "application/pdf")},
    )
    assert r.status_code == 202
    return r.json()["job_id"]


def test_job_lifecycle_to_completed(client):
    """After the fake run, status → completed, report_available True, finished_at set."""
    job_id = _submit(client)
    status = _wait_for(client, job_id, "completed")

    assert status["status"] == "completed"
    assert status["report_available"] is True
    assert status["finished_at"] is not None


def test_unknown_job_404(client):
    """GET /api/jobs/{random} → 404."""
    r = client.get("/api/jobs/does-not-exist-xyz")
    assert r.status_code == 404


def test_health_ok(client):
    """GET /api/health → 200 {'status': 'ok'}."""
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_two_jobs_independent(client):
    """Two submissions → two ids tracked independently."""
    job_id1 = _submit(client, "a.pdf")
    job_id2 = _submit(client, "b.pdf")

    assert job_id1 != job_id2

    _wait_for(client, job_id1, "completed")
    _wait_for(client, job_id2, "completed")

    r1 = client.get(f"/api/jobs/{job_id1}").json()
    r2 = client.get(f"/api/jobs/{job_id2}").json()

    assert r1["job_id"] == job_id1
    assert r2["job_id"] == job_id2
    assert r1["status"] == "completed"
    assert r2["status"] == "completed"


def test_ingest_error_completes_with_error(client, monkeypatch):
    """Fake graph sets ingest_error → job 'completed' with error.kind='ingest_error'."""
    import app.runner.core as core_mod

    def ingest_error_graph(checkpointer=None):
        class _FG:
            def stream(self, initial, stream_mode=None, config=None):
                yield {
                    "current_node": "ingest_agent",
                    "document_path": (initial or {}).get("document_path", ""),
                    "ingest_error": {"message": "bad pdf", "error_type": "ParseError"},
                }

        return _FG()

    def delivery_no_report(state, *, recipient=None):
        return {"mcp_delivery_status": {}}

    monkeypatch.setattr(core_mod, "build_graph", ingest_error_graph)
    monkeypatch.setattr(core_mod, "deliver_report_sync", delivery_no_report)

    job_id = _submit(client)
    status = _wait_for(client, job_id, "completed")

    assert status["status"] == "completed"
    assert status["error"] is not None
    assert status["error"]["kind"] == "ingest_error"


def test_graph_exception_marks_failed(client, monkeypatch):
    """Fake graph raises → job 'failed' with error; a second job still completes."""
    import app.runner.core as core_mod

    call_count = {"n": 0}

    def sometimes_raise(checkpointer=None):
        class _FG:
            def stream(self, initial, stream_mode=None, config=None):
                call_count["n"] += 1
                if call_count["n"] == 1:
                    raise RuntimeError("graph exploded")
                # Second call: happy path (minimal)
                yield {
                    "current_node": "report",
                    "document_path": (initial or {}).get("document_path", ""),
                    "report_path": "r.md",
                    "document_id": "d",
                }

        return _FG()

    monkeypatch.setattr(core_mod, "build_graph", sometimes_raise)

    job_id1 = _submit(client, "a.pdf")
    _wait_for(client, job_id1, "failed")
    s1 = client.get(f"/api/jobs/{job_id1}").json()
    assert s1["status"] == "failed"
    assert s1["error"] is not None

    job_id2 = _submit(client, "b.pdf")
    _wait_for(client, job_id2, "completed")
    s2 = client.get(f"/api/jobs/{job_id2}").json()
    assert s2["status"] == "completed"


def test_delivery_status_surfaced(client, monkeypatch):
    """Branch 1: failed channel → surfaces in mcp_delivery_status, job completed.
    Branch 2: empty {} → empty map, job still completed. (review T4)"""
    import app.runner.core as core_mod

    # Branch 1: FAILED channel
    def failed_delivery(state, *, recipient=None):
        return {
            "mcp_delivery_status": {
                "drive": {
                    "status": "FAILED",
                    "error_message": "auth",
                    "delivered_at": None,
                },
            }
        }

    monkeypatch.setattr(core_mod, "deliver_report_sync", failed_delivery)

    job_id1 = _submit(client, "a.pdf")
    s1 = _wait_for(client, job_id1, "completed")
    assert s1["status"] == "completed"
    assert s1["mcp_delivery_status"]["drive"]["status"] == "FAILED"

    # Branch 2: empty delivery
    def empty_delivery(state, *, recipient=None):
        return {"mcp_delivery_status": {}}

    monkeypatch.setattr(core_mod, "deliver_report_sync", empty_delivery)

    job_id2 = _submit(client, "b.pdf")
    s2 = _wait_for(client, job_id2, "completed")
    assert s2["status"] == "completed"
    assert s2["mcp_delivery_status"] == {}


def test_eviction_returns_404(monkeypatch, tmp_path):
    """Small JOB_REGISTRY_MAX; exceed it → oldest job GET → 404 (AC-22)."""
    import app.config as _config
    from app.api.main import create_app
    from starlette.testclient import TestClient

    report_dir = tmp_path / "reports"
    report_dir.mkdir(parents=True)
    stem = "evict_test"
    (report_dir / f"{stem}.md").write_text("# R")
    (report_dir / f"{stem}.json").write_text("{}")

    def _small_fake(checkpointer=None):
        class _FG:
            def stream(self, initial, stream_mode=None, config=None):
                yield {
                    "current_node": "ingest_agent",
                    "document_path": (initial or {}).get("document_path", ""),
                }
                yield {
                    "current_node": "report",
                    "document_path": (initial or {}).get("document_path", ""),
                    "report_path": str(report_dir / f"{stem}.md"),
                    "document_id": stem,
                }

        return _FG()

    def _delivery(state, *, recipient=None):
        return {"mcp_delivery_status": {}}

    monkeypatch.setattr("app.runner.core.build_graph", _small_fake)
    monkeypatch.setattr("app.runner.core.deliver_report_sync", _delivery)
    monkeypatch.setattr(_config, "UPLOAD_DIR", str(tmp_path / "uploads"))
    monkeypatch.setattr(_config, "JOB_REGISTRY_MAX", 2)
    monkeypatch.setattr(_config, "JOB_STORE_RETENTION_MAX", 2)
    monkeypatch.setattr(_config, "JOB_STORE_DB_PATH", str(tmp_path / "evict_job_store.db"))
    monkeypatch.setattr(_config, "CHECKPOINTER_DB_PATH", str(tmp_path / "evict_checkpoints.db"))
    monkeypatch.setattr(_config, "STARTUP_RECOVERY_ENABLED", False)

    import app.graph.nodes.report_agent as ra_mod

    monkeypatch.setattr(ra_mod, "REPORT_OUTPUT_DIR", str(report_dir))

    with TestClient(create_app()) as c:
        job_ids = []
        for i in range(3):
            r = c.post(
                "/api/analyze",
                files={"file": (f"c{i}.pdf", b"%PDF", "application/pdf")},
            )
            assert r.status_code == 202
            job_ids.append(r.json()["job_id"])

        # Wait for all jobs to complete/process
        time.sleep(0.5)

        # Oldest job should be 404 (evicted with max_jobs=2)
        r = c.get(f"/api/jobs/{job_ids[0]}")
        assert r.status_code == 404
