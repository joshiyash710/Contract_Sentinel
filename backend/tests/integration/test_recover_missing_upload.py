"""
Integration test: a recoverable job whose document_path doesn't exist terminates
gracefully — never stays perpetually running (spec EC-3).
"""

import time

import app.config as _cfg
from app.runner.migrations import upgrade_to_head
from app.runner.models import JobState
from app.runner.store import JobRow, JobStore


def _seed_queued_missing_file(job_store_path, job_id):
    upgrade_to_head(job_store_path)
    store = JobStore(job_store_path)
    store.upsert(
        JobRow(
            job_id=job_id,
            document_path="/definitely/does/not/exist.pdf",
            recipient=None,
            status=JobState.queued,
            submitted_at="2026-01-01T00:00:00+00:00",
            started_at=None,
            finished_at=None,
            current_node=None,
            completed_nodes=[],
            report_path=None,
            mcp_delivery_status={},
            error=None,
        )
    )
    store.close()


def _make_client(monkeypatch, tmp_path, job_store_path, checkpoints_path):
    from app.api.main import create_app
    from starlette.testclient import TestClient

    def _fake_build_graph(checkpointer=None):
        class _FG:
            def stream(self, initial, stream_mode=None, config=None):
                doc = (initial or {}).get("document_path", "")
                # Simulate ingest_error for missing file
                yield {
                    "current_node": "ingest_agent",
                    "document_path": doc,
                    "ingest_error": {"message": "File not found", "error_type": "FileNotFoundError"},
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
    monkeypatch.setattr(_cfg, "STARTUP_RECOVERY_ENABLED", True)

    return TestClient(create_app())


def test_missing_upload_terminates(monkeypatch, tmp_path):
    """Recovered job with missing document_path reaches a terminal state (spec EC-3)."""
    job_id = "missing-upload-job"
    job_store = str(tmp_path / "job_store.db")
    checkpoints = str(tmp_path / "checkpoints.db")
    _seed_queued_missing_file(job_store, job_id)

    with _make_client(monkeypatch, tmp_path, job_store, checkpoints) as c:
        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline:
            r = c.get(f"/api/jobs/{job_id}")
            if r.status_code == 200:
                status = r.json()["status"]
                if status in ("completed", "failed"):
                    break
            time.sleep(0.05)
        else:
            raise TimeoutError(f"Job {job_id!r} never reached a terminal state")

        final = c.get(f"/api/jobs/{job_id}").json()
        assert final["status"] in ("completed", "failed"), (
            f"Expected terminal status, got {final['status']}"
        )
