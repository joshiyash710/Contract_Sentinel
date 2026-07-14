"""
Integration test: queued/running-no-checkpoint rows get a fresh re-run on recovery (spec AC-12/13, EC-2).
"""

import time

import app.config as _cfg
from app.runner.migrations import upgrade_to_head
from app.runner.models import JobState
from app.runner.store import JobRow, JobStore


def _seed_row(job_store_path, job_id, status):
    upgrade_to_head(job_store_path)
    store = JobStore(job_store_path)
    store.upsert(
        JobRow(
            job_id=job_id,
            document_path="nonexistent_dummy.pdf",
            recipient=None,
            status=status,
            submitted_at="2026-01-01T00:00:00+00:00",
            started_at="2026-01-01T00:01:00+00:00" if status == JobState.running else None,
            finished_at=None,
            current_node="ingest_agent" if status == JobState.running else None,
            completed_nodes=["ingest_agent"] if status == JobState.running else [],
            report_path=None,
            mcp_delivery_status={},
            error=None,
        )
    )
    store.close()


def _make_recovery_client(monkeypatch, tmp_path, job_store_path, checkpoints_path):
    from app.api.main import create_app
    from starlette.testclient import TestClient

    def _fake_build_graph(checkpointer=None):
        class _FG:
            def stream(self, initial, stream_mode=None, config=None):
                doc = (initial or {}).get("document_path", "c.pdf")
                yield {"current_node": "ingest_agent", "document_path": doc}
                yield {
                    "current_node": "report",
                    "document_path": doc,
                    "report_path": None,
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
    monkeypatch.setenv("AUTH_SECRET", "recover_queued_test_secret_" + "x" * 13)
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


def test_queued_row_fresh_run(monkeypatch, tmp_path):
    """Seeded queued row → fresh run → completed (spec AC-12)."""
    job_store = str(tmp_path / "job_store.db")
    checkpoints = str(tmp_path / "checkpoints.db")
    _seed_row(job_store, "queued-job", JobState.queued)

    with _make_recovery_client(monkeypatch, tmp_path, job_store, checkpoints) as c:
        from tests.integration.conftest import authenticate
        authenticate(c)
        status = _wait_for(c, "queued-job", "completed")
        assert status["status"] == "completed"


def test_running_no_checkpoint_fresh_run(monkeypatch, tmp_path):
    """Seeded running row with no checkpoint → fresh re-run → completed (spec AC-13, EC-2)."""
    job_store = str(tmp_path / "job_store.db")
    checkpoints = str(tmp_path / "checkpoints.db")
    _seed_row(job_store, "running-job", JobState.running)
    # No checkpoint in checkpoints.db → has_checkpoint returns False → fresh run

    with _make_recovery_client(monkeypatch, tmp_path, job_store, checkpoints) as c:
        from tests.integration.conftest import authenticate
        authenticate(c)
        status = _wait_for(c, "running-job", "completed")
        assert status["status"] == "completed"
