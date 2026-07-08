"""
Unit tests for app.runner.worker.PipelineWorker.

Tests use real JobRegistry + JobRecord with a real JobEventBuffer on a running
asyncio loop. run_pipeline is patched with controllable stubs.

TDD red phase: all tests FAIL (ImportError) until Task 15 implements the module.
Run: python -m pytest tests/unit/test_worker.py -v
"""

import asyncio
import threading
import time
from dataclasses import dataclass
from typing import Optional
from unittest.mock import patch

# ── helpers ──────────────────────────────────────────────────────────────────


def _make_registry_and_record(
    job_id: str = "j1", document_path: str = "c.pdf", recipient=None
):
    """Build a real registry and one queued JobRecord."""
    from app.runner.registry import JobRegistry, JobRecord
    from app.runner.events import JobEventBuffer

    loop = asyncio.new_event_loop()
    buf = JobEventBuffer(loop)
    reg = JobRegistry(max_jobs=50)
    rec = JobRecord(
        job_id=job_id,
        document_path=document_path,
        submitted_at="2026-07-08T00:00:00Z",
        buffer=buf,
        recipient=recipient,
    )
    reg.add(rec)
    return reg, rec, loop


def _wait_for_status(rec, target_state, timeout: float = 5.0):
    """Poll rec.to_status() until status matches target_state."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if rec.to_status().status.value == target_state:
            return True
        time.sleep(0.05)
    return False


@dataclass
class FakeRunResult:
    final_state: dict
    report_path: Optional[str]
    mcp_delivery_status: dict
    ingest_error: Optional[dict]


def _happy_run_result(document_path="c.pdf"):
    return FakeRunResult(
        final_state={
            "document_path": document_path,
            "report_path": "data/reports/doc.md",
        },
        report_path="data/reports/doc.md",
        mcp_delivery_status={"drive": "SUCCESS", "gmail": "SUCCESS"},
        ingest_error=None,
    )


def _ingest_error_result():
    return FakeRunResult(
        final_state={"ingest_error": {"message": "bad pdf"}},
        report_path=None,
        mcp_delivery_status={},
        ingest_error={"message": "bad pdf"},
    )


# ── tests ─────────────────────────────────────────────────────────────────────


def test_single_shared_worker_serializes():
    """concurrency=1: while first job is held running, second stays queued."""
    from app.runner.worker import PipelineWorker
    import app.runner.worker as worker_mod

    hold = threading.Event()
    release = threading.Event()

    def slow_run(document_path, *, recipient=None, on_progress=None):
        hold.set()
        release.wait(timeout=5.0)
        return _happy_run_result(document_path)

    reg1, rec1, loop1 = _make_registry_and_record("j1")
    reg2, rec2, loop2 = _make_registry_and_record("j2")

    # Use a single registry for both
    from app.runner.registry import JobRegistry, JobRecord
    from app.runner.events import JobEventBuffer

    loop = asyncio.new_event_loop()
    buf1 = JobEventBuffer(loop)
    buf2 = JobEventBuffer(loop)
    reg = JobRegistry(max_jobs=50)
    rec1 = JobRecord(job_id="j1", document_path="c.pdf", submitted_at="t", buffer=buf1)
    rec2 = JobRecord(job_id="j2", document_path="c2.pdf", submitted_at="t", buffer=buf2)
    reg.add(rec1)
    reg.add(rec2)

    with patch.object(worker_mod, "run_pipeline", side_effect=slow_run):
        worker = PipelineWorker(reg, concurrency=1)
        worker.start()
        try:
            worker.submit("j1")
            hold.wait(timeout=5.0)  # j1 is now running

            worker.submit("j2")
            time.sleep(0.1)  # give j2 a moment to be dequeued
            assert rec2.to_status().status.value == "queued"

            release.set()
            assert _wait_for_status(rec1, "completed")
            assert _wait_for_status(rec2, "completed")
        finally:
            release.set()
            worker.stop()
        loop.close()


def test_completed_status_and_terminal_event():
    """On success → record COMPLETED, report_path/mcp_delivery_status/finished_at set."""
    from app.runner.worker import PipelineWorker
    import app.runner.worker as worker_mod

    loop = asyncio.new_event_loop()
    from app.runner.registry import JobRegistry, JobRecord
    from app.runner.events import JobEventBuffer

    buf = JobEventBuffer(loop)
    reg = JobRegistry(max_jobs=50)
    rec = JobRecord(job_id="j1", document_path="c.pdf", submitted_at="t", buffer=buf)
    reg.add(rec)

    with patch.object(worker_mod, "run_pipeline", return_value=_happy_run_result()):
        worker = PipelineWorker(reg, concurrency=1)
        worker.start()
        try:
            worker.submit("j1")
            assert _wait_for_status(rec, "completed")
        finally:
            worker.stop()

    status = rec.to_status()
    assert status.status.value == "completed"
    assert status.report_path == "data/reports/doc.md"
    assert status.mcp_delivery_status != {}
    assert status.finished_at is not None

    loop.close()


def test_ingest_error_marks_completed_with_error():
    """Ingest error → record COMPLETED with error.kind == 'ingest_error'."""
    from app.runner.worker import PipelineWorker
    import app.runner.worker as worker_mod

    loop = asyncio.new_event_loop()
    from app.runner.registry import JobRegistry, JobRecord
    from app.runner.events import JobEventBuffer

    buf = JobEventBuffer(loop)
    reg = JobRegistry(max_jobs=50)
    rec = JobRecord(job_id="j1", document_path="c.pdf", submitted_at="t", buffer=buf)
    reg.add(rec)

    with patch.object(worker_mod, "run_pipeline", return_value=_ingest_error_result()):
        worker = PipelineWorker(reg, concurrency=1)
        worker.start()
        try:
            worker.submit("j1")
            assert _wait_for_status(rec, "completed")
        finally:
            worker.stop()

    status = rec.to_status()
    assert status.status.value == "completed"
    assert status.error is not None
    assert status.error.kind == "ingest_error"
    assert "bad pdf" in status.error.message

    loop.close()


def test_exception_marks_failed_isolated():
    """Exception for job A → A FAILED; separately submitted job B still COMPLETED."""
    from app.runner.worker import PipelineWorker
    import app.runner.worker as worker_mod

    loop = asyncio.new_event_loop()
    from app.runner.registry import JobRegistry, JobRecord
    from app.runner.events import JobEventBuffer

    buf_a = JobEventBuffer(loop)
    buf_b = JobEventBuffer(loop)
    reg = JobRegistry(max_jobs=50)
    rec_a = JobRecord(
        job_id="jA", document_path="a.pdf", submitted_at="t", buffer=buf_a
    )
    rec_b = JobRecord(
        job_id="jB", document_path="b.pdf", submitted_at="t", buffer=buf_b
    )
    reg.add(rec_a)
    reg.add(rec_b)

    call_count = {"n": 0}

    def side_effect(document_path, *, recipient=None, on_progress=None):
        call_count["n"] += 1
        if document_path == "a.pdf":
            raise RuntimeError("boom")
        return _happy_run_result(document_path)

    with patch.object(worker_mod, "run_pipeline", side_effect=side_effect):
        worker = PipelineWorker(reg, concurrency=1)
        worker.start()
        try:
            worker.submit("jA")
            assert _wait_for_status(rec_a, "failed")
            worker.submit("jB")
            assert _wait_for_status(rec_b, "completed")
        finally:
            worker.stop()

    assert rec_a.to_status().status.value == "failed"
    assert rec_a.to_status().error is not None
    assert rec_b.to_status().status.value == "completed"

    loop.close()


def test_worker_uses_run_pipeline():
    """Worker calls run_pipeline (shared core — D2) with document_path and recipient."""
    from app.runner.worker import PipelineWorker
    import app.runner.worker as worker_mod

    loop = asyncio.new_event_loop()
    from app.runner.registry import JobRegistry, JobRecord
    from app.runner.events import JobEventBuffer

    buf = JobEventBuffer(loop)
    reg = JobRegistry(max_jobs=50)
    rec = JobRecord(
        job_id="j1",
        document_path="c.pdf",
        submitted_at="t",
        buffer=buf,
        recipient="r@x.com",
    )
    reg.add(rec)

    calls = []

    def capture(document_path, *, recipient=None, on_progress=None):
        calls.append({"document_path": document_path, "recipient": recipient})
        return _happy_run_result(document_path)

    with patch.object(worker_mod, "run_pipeline", side_effect=capture):
        worker = PipelineWorker(reg, concurrency=1)
        worker.start()
        try:
            worker.submit("j1")
            assert _wait_for_status(rec, "completed")
        finally:
            worker.stop()

    assert len(calls) == 1
    assert calls[0]["document_path"] == "c.pdf"
    assert calls[0]["recipient"] == "r@x.com"

    loop.close()


def test_evicted_job_skipped():
    """A job id whose record was evicted before it ran is a no-op (no crash)."""
    from app.runner.worker import PipelineWorker
    import app.runner.worker as worker_mod

    loop = asyncio.new_event_loop()
    from app.runner.registry import JobRegistry, JobRecord
    from app.runner.events import JobEventBuffer

    reg = JobRegistry(max_jobs=1)
    buf_a = JobEventBuffer(loop)
    buf_b = JobEventBuffer(loop)
    rec_a = JobRecord(
        job_id="jA", document_path="a.pdf", submitted_at="t", buffer=buf_a
    )
    rec_b = JobRecord(
        job_id="jB", document_path="b.pdf", submitted_at="t", buffer=buf_b
    )
    reg.add(rec_a)
    reg.add(rec_b)  # evicts jA (max_jobs=1)

    assert reg.get("jA") is None  # confirm evicted

    called_with = []

    def capture(document_path, *, recipient=None, on_progress=None):
        called_with.append(document_path)
        return _happy_run_result(document_path)

    with patch.object(worker_mod, "run_pipeline", side_effect=capture):
        worker = PipelineWorker(reg, concurrency=1)
        worker.start()
        try:
            worker.submit("jA")  # evicted — should be a no-op
            time.sleep(0.2)  # give the worker time to process
        finally:
            worker.stop()

    # run_pipeline should NOT have been called for the evicted job
    assert "a.pdf" not in called_with

    loop.close()
