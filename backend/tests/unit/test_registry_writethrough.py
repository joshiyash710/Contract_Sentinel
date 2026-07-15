"""
Unit tests for JobRecord write-through and JobRegistry rehydration.

Written red (Task 6) — green after registry.py is updated.
"""

import asyncio

import pytest

from app.runner.migrations import upgrade_to_head
from app.runner.models import ErrorInfo, JobState


@pytest.fixture()
def db(tmp_path):
    path = str(tmp_path / "test.db")
    upgrade_to_head(path)
    return path


@pytest.fixture()
def store(db):
    from app.runner.store import JobStore

    s = JobStore(db)
    yield s
    s.close()


@pytest.fixture()
def loop():
    lp = asyncio.new_event_loop()
    yield lp
    lp.close()


def _make_record(job_id="j1"):
    from app.runner.events import JobEventBuffer
    from app.runner.registry import JobRecord

    buf = JobEventBuffer.__new__(JobEventBuffer)
    buf._subscribers = []
    buf._history = []
    buf._loop = None

    return JobRecord(
        job_id=job_id,
        document_path="/tmp/contract.pdf",
        submitted_at="2026-01-01T00:00:00+00:00",
        buffer=buf,
        recipient="u@example.com",
    )


def test_add_persists_queued(db, store, loop):
    from app.runner.store import JobStore
    from app.runner.registry import JobRegistry

    registry = JobRegistry(store=store, saver=None, loop=loop, max_jobs=100)
    rec = _make_record("j1")
    registry.add(rec)

    fresh = JobStore(db)
    row = fresh.get("j1")
    fresh.close()
    assert row is not None
    assert row.status == JobState.queued


def test_mutations_writethrough(db, store, loop):
    from app.runner.store import JobStore
    from app.runner.registry import JobRegistry

    registry = JobRegistry(store=store, saver=None, loop=loop, max_jobs=100)
    rec = _make_record("j2")
    registry.add(rec)

    rec.mark_running("2026-01-01T00:01:00+00:00")
    fresh = JobStore(db)
    assert fresh.get("j2").status == JobState.running
    fresh.close()

    rec.record_progress("ingest_agent")
    fresh2 = JobStore(db)
    row = fresh2.get("j2")
    fresh2.close()
    assert "ingest_agent" in row.completed_nodes

    rec.mark_terminal(
        status=JobState.completed,
        finished_at="2026-01-01T00:02:00+00:00",
        report_path="/data/reports/j2.md",
        mcp_delivery_status={},
        error=None,
    )
    fresh3 = JobStore(db)
    row3 = fresh3.get("j2")
    fresh3.close()
    assert row3.status == JobState.completed
    assert row3.report_path == "/data/reports/j2.md"


def test_rehydrate_after_restart(db, store, loop):
    from app.runner.registry import JobRegistry

    registry = JobRegistry(store=store, saver=None, loop=loop, max_jobs=100)
    rec = _make_record("j3")
    registry.add(rec)
    rec.mark_running("2026-01-01T00:01:00+00:00")
    rec.mark_terminal(
        status=JobState.completed,
        finished_at="2026-01-01T00:02:00+00:00",
        report_path=None,
        mcp_delivery_status={},
        error=None,
    )

    # Simulate restart: clear the live dict
    registry._live.clear()

    got = registry.get("j3")
    assert got is not None
    assert got.to_status().status == JobState.completed


def test_user_id_persists_and_rehydrates(db, store, loop):
    """Feature 019 (AC-A8): a JobRecord's owner persists on insert and survives rehydration."""
    from app.runner.events import JobEventBuffer
    from app.runner.registry import JobRecord, JobRegistry

    registry = JobRegistry(store=store, saver=None, loop=loop, max_jobs=100)
    buf = JobEventBuffer.__new__(JobEventBuffer)
    buf._subscribers = []
    buf._history = []
    buf._loop = None
    rec = JobRecord(
        job_id="owned1",
        document_path="/tmp/c.pdf",
        submitted_at="2026-01-01T00:00:00+00:00",
        buffer=buf,
        user_id="user-abc",
    )
    registry.add(rec)

    # Owner is persisted on the initial durable insert.
    row = store.get("owned1")
    assert row is not None and row.user_id == "user-abc"

    # Rehydrate after a simulated restart — the owner is carried through.
    registry._live.clear()
    got = registry.get("owned1")
    assert got is not None
    assert got.user_id == "user-abc"


def test_store_none_record_still_works():
    """_store=None record mutates in memory without error (spec AC-7a)."""
    from app.runner.events import JobEventBuffer
    from app.runner.registry import JobRecord

    buf = JobEventBuffer.__new__(JobEventBuffer)
    buf._subscribers = []
    buf._history = []
    buf._loop = None

    rec = JobRecord(
        job_id="j-nosave",
        document_path="/f",
        submitted_at="2026-01-01T00:00:00+00:00",
        buffer=buf,
    )
    # _store is None by default — mutations must not raise
    rec.mark_running("2026-01-01T00:01:00+00:00")
    rec.record_progress("ingest_agent")
    rec.mark_terminal(
        status=JobState.completed,
        finished_at="2026-01-01T00:02:00+00:00",
        report_path=None,
    )
    assert rec.to_status().status == JobState.completed
