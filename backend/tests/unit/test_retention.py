"""
Unit tests for JobRegistry retention (prune + checkpoint thread deletion).

Written red (Task 6) — green after registry.py is updated.
"""

import asyncio
from datetime import datetime, timezone, timedelta

import pytest

from app.runner.migrations import upgrade_to_head
from app.runner.models import JobState


@pytest.fixture()
def db(tmp_path):
    path = str(tmp_path / "ret.db")
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


class SpySaver:
    """Minimal saver stub that records delete_thread calls."""

    def __init__(self):
        self.deleted = []

    def delete_thread(self, thread_id: str) -> None:
        self.deleted.append(thread_id)


def _make_record(job_id: str, submitted_at: str, loop):
    from app.runner.events import JobEventBuffer
    from app.runner.registry import JobRecord

    buf = JobEventBuffer.__new__(JobEventBuffer)
    buf._subscribers = []
    buf._history = []
    buf._loop = loop

    return JobRecord(
        job_id=job_id,
        document_path="/f",
        submitted_at=submitted_at,
        buffer=buf,
    )


def _ts(offset_seconds: int) -> str:
    base = datetime(2026, 1, 1, tzinfo=timezone.utc)
    return (base + timedelta(seconds=offset_seconds)).isoformat()


def test_add_prunes_oldest_and_deletes_threads(db, store, loop):
    from app.runner.registry import JobRegistry

    spy = SpySaver()
    registry = JobRegistry(store=store, saver=spy, loop=loop, max_jobs=3)

    for i in range(5):
        rec = _make_record(f"j{i}", _ts(i), loop)
        registry.add(rec)

    # j0 and j1 should have been pruned (oldest 2)
    assert registry.get("j0") is None
    assert registry.get("j1") is None
    assert registry.get("j2") is not None
    assert registry.get("j3") is not None
    assert registry.get("j4") is not None

    # delete_thread called for the pruned ids
    assert "j0" in spy.deleted
    assert "j1" in spy.deleted
