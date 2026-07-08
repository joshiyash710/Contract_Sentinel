"""
Unit tests for app.runner.registry — JobRegistry and JobRecord.

TDD red phase: all tests FAIL (ImportError) until Task 13 implements the module.
Run: python -m pytest tests/unit/test_registry.py -v
"""

import asyncio
import threading
import time
from unittest.mock import MagicMock


def _make_buffer():
    """Return a real JobEventBuffer on a fresh loop (tests that need one)."""
    from app.runner.events import JobEventBuffer

    loop = asyncio.new_event_loop()
    return JobEventBuffer(loop), loop


def _make_mock_buffer():
    """Return a MagicMock buffer for tests that don't exercise event publishing."""
    return MagicMock()


def test_add_and_get():
    """An added record is retrievable by id; an unknown id returns None."""
    from app.runner.registry import JobRegistry, JobRecord

    reg = JobRegistry(max_jobs=10)
    buf = _make_mock_buffer()
    rec = JobRecord(job_id="j1", document_path="c.pdf", submitted_at="t", buffer=buf)
    reg.add(rec)

    assert reg.get("j1") is rec
    assert reg.get("unknown") is None


def test_eviction_keeps_last_n():
    """JobRegistry(max_jobs=N): adding N+1 records evicts the oldest; get(oldest) → None."""
    from app.runner.registry import JobRegistry, JobRecord

    N = 3
    reg = JobRegistry(max_jobs=N)
    ids = []
    for i in range(N + 1):
        jid = f"j{i}"
        ids.append(jid)
        rec = JobRecord(
            job_id=jid,
            document_path="c.pdf",
            submitted_at="t",
            buffer=_make_mock_buffer(),
        )
        reg.add(rec)

    # Oldest is ids[0]
    assert reg.get(ids[0]) is None
    # The remaining N are still present
    for jid in ids[1:]:
        assert reg.get(jid) is not None


def test_record_lock_methods_mutate():
    """mark_running/record_progress/mark_terminal update fields; to_status() reflects them."""
    from app.runner.registry import JobRecord
    from app.runner.models import JobState

    buf = _make_mock_buffer()
    rec = JobRecord(job_id="j1", document_path="c.pdf", submitted_at="t0", buffer=buf)

    assert rec.to_status().status == JobState.queued

    rec.mark_running("t1")
    assert rec.to_status().status == JobState.running
    assert rec.to_status().started_at == "t1"

    rec.record_progress("ingest_agent")
    status = rec.to_status()
    assert "ingest_agent" in status.completed_nodes

    rec.mark_terminal(status=JobState.completed, finished_at="t2", report_path=None)
    assert rec.to_status().status == JobState.completed
    assert rec.to_status().finished_at == "t2"


def test_concurrent_progress_and_to_status_no_race():
    """One thread writes record_progress in a loop; another reads to_status — no RuntimeError."""
    from app.runner.registry import JobRecord

    buf = _make_mock_buffer()
    rec = JobRecord(job_id="j1", document_path="c.pdf", submitted_at="t0", buffer=buf)
    rec.mark_running("t1")

    errors = []
    stop = threading.Event()

    def writer():
        nodes = ["ingest_agent", "clause_splitter", "crag_retrieval"]
        i = 0
        while not stop.is_set():
            rec.record_progress(nodes[i % len(nodes)])
            i += 1

    def reader():
        while not stop.is_set():
            try:
                status = rec.to_status()
                # Snapshot must be a consistent list (never a partially-mutated object)
                _ = list(status.completed_nodes)
            except Exception as exc:
                errors.append(exc)

    t_w = threading.Thread(target=writer)
    t_r = threading.Thread(target=reader)
    t_w.start()
    t_r.start()
    time.sleep(0.3)
    stop.set()
    t_w.join()
    t_r.join()

    assert not errors, f"Race condition errors: {errors}"


def test_to_status_report_available_reflects_disk(tmp_path):
    """report_available is True only when the file at report_path exists on disk."""
    from app.runner.registry import JobRecord
    from app.runner.models import JobState

    report_file = tmp_path / "doc.md"
    buf = _make_mock_buffer()
    rec = JobRecord(job_id="j1", document_path="c.pdf", submitted_at="t0", buffer=buf)
    rec.mark_running("t1")
    rec.mark_terminal(
        status=JobState.completed,
        finished_at="t2",
        report_path=str(report_file),
    )

    # File doesn't exist yet
    assert rec.to_status().report_available is False

    # Create the file
    report_file.write_text("# Report")
    assert rec.to_status().report_available is True


def test_delivery_status_enum_coerced():
    """An MCPDeliveryStatus enum in mcp_delivery_status → .value string in JobStatus."""
    from app.runner.registry import JobRecord
    from app.runner.models import JobState
    from app.graph.state import MCPDeliveryStatus

    buf = _make_mock_buffer()
    rec = JobRecord(job_id="j1", document_path="c.pdf", submitted_at="t0", buffer=buf)
    rec.mark_running("t1")
    rec.mark_terminal(
        status=JobState.completed,
        finished_at="t2",
        report_path=None,
        mcp_delivery_status={
            "drive": {
                "status": MCPDeliveryStatus.SUCCESS,
                "error_message": None,
                "delivered_at": "t2",
            },
        },
    )

    projected = rec.to_status().mcp_delivery_status
    assert projected["drive"]["status"] == "success"


def test_registry_is_single_seam():
    """A fake registry with the same add/get surface substitutes without other patching."""

    class FakeRegistry:
        def __init__(self):
            self._store = {}

        def add(self, rec):
            self._store[rec.job_id] = rec

        def get(self, job_id):
            return self._store.get(job_id)


    fake_reg = FakeRegistry()

    buf = _make_mock_buffer()

    # Import the real dataclass just to construct a record
    from app.runner.registry import JobRecord

    rec = JobRecord(job_id="j1", document_path="c.pdf", submitted_at="t0", buffer=buf)
    fake_reg.add(rec)

    retrieved = fake_reg.get("j1")
    assert retrieved is rec
    assert fake_reg.get("nope") is None
