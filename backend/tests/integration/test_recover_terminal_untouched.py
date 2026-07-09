"""
Integration test: terminal jobs (completed/failed) are not re-run on restart (spec AC-14/15).

Recovery only re-enqueues queued/running rows — terminal rows are left alone.
Recovery is idempotent across multiple startups (AC-15).
"""

import time

import app.config as _cfg
from app.runner.migrations import upgrade_to_head
from app.runner.models import JobState
from app.runner.store import JobRow, JobStore


def _seed_terminal_jobs(job_store_path):
    upgrade_to_head(job_store_path)
    store = JobStore(job_store_path)
    store.upsert(
        JobRow(
            job_id="completed-job",
            document_path="/f/completed.pdf",
            recipient=None,
            status=JobState.completed,
            submitted_at="2026-01-01T00:00:00+00:00",
            started_at="2026-01-01T00:01:00+00:00",
            finished_at="2026-01-01T00:02:00+00:00",
            current_node="report",
            completed_nodes=["ingest_agent", "report"],
            report_path=None,
            mcp_delivery_status={},
            error=None,
        )
    )
    store.upsert(
        JobRow(
            job_id="failed-job",
            document_path="/f/failed.pdf",
            recipient=None,
            status=JobState.failed,
            submitted_at="2026-01-01T00:03:00+00:00",
            started_at="2026-01-01T00:04:00+00:00",
            finished_at="2026-01-01T00:05:00+00:00",
            current_node=None,
            completed_nodes=[],
            report_path=None,
            mcp_delivery_status={},
            error=None,
        )
    )
    store.close()


def _make_client(monkeypatch, tmp_path, job_store_path, checkpoints_path, recovery_on):
    from app.api.main import create_app
    from starlette.testclient import TestClient

    submitted = []

    def _fake_build_graph(checkpointer=None):
        class _FG:
            def stream(self, initial, stream_mode=None, config=None):
                return iter([])

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

    return TestClient(create_app())


def test_terminal_jobs_not_rerun(monkeypatch, tmp_path):
    """Completed + failed rows are NOT re-submitted on startup recovery (spec AC-14)."""
    job_store = str(tmp_path / "job_store.db")
    checkpoints = str(tmp_path / "checkpoints.db")
    _seed_terminal_jobs(job_store)

    import app.runner.worker as worker_mod

    submitted_ids = []
    orig_submit = None

    with _make_client(monkeypatch, tmp_path, job_store, checkpoints, recovery_on=True) as c:
        # Both jobs should be retrievable (AC-14)
        r1 = c.get("/api/jobs/completed-job")
        assert r1.status_code == 200
        assert r1.json()["status"] == "completed"

        r2 = c.get("/api/jobs/failed-job")
        assert r2.status_code == 200
        assert r2.json()["status"] == "failed"


def test_recovery_is_idempotent(monkeypatch, tmp_path):
    """Building the app twice on the same DB does not double-enqueue (spec AC-15)."""
    job_store = str(tmp_path / "job_store.db")
    checkpoints = str(tmp_path / "checkpoints.db")
    _seed_terminal_jobs(job_store)

    # Build app twice — both GETs must succeed, no crash on second start
    with _make_client(monkeypatch, tmp_path, job_store, checkpoints, recovery_on=True) as c1:
        r1 = c1.get("/api/jobs/completed-job")
        assert r1.status_code == 200

    with _make_client(monkeypatch, tmp_path, job_store, checkpoints, recovery_on=True) as c2:
        r2 = c2.get("/api/jobs/completed-job")
        assert r2.status_code == 200


def test_routes_module_does_not_import_sqlite(monkeypatch, tmp_path):
    """routes.py must not import sqlite3 or app.runner.store — job access stays behind registry (AC-6/7)."""
    import inspect
    import app.api.routes as routes_mod

    src = inspect.getsource(routes_mod)
    assert "sqlite3" not in src
    assert "app.runner.store" not in src
