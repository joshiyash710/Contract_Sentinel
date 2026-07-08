"""
Unit tests for app.runner.events.JobEventBuffer.

asyncio_mode="auto" (pyproject.toml) means bare async def tests run without
@pytest.mark.asyncio. The event loop is a real running loop inside async tests.
TDD red phase: all tests FAIL (ImportError) until Task 11 implements the module.
Run: python -m pytest tests/unit/test_event_buffer.py -v
"""

import asyncio
import threading

from app.runner.models import JobState, JobStatus, ProgressEvent


def _make_terminal_event(job_id: str = "job1") -> ProgressEvent:
    status = JobStatus(
        job_id=job_id,
        status=JobState.completed,
        submitted_at="2026-07-08T00:00:00Z",
        report_available=True,
    )
    return ProgressEvent(event="completed", job_id=job_id, final=status)


def _make_progress_event(
    job_id: str = "job1", node: str = "ingest_agent"
) -> ProgressEvent:
    return ProgressEvent(event="progress", job_id=job_id, node=node, index=1, total=7)


async def test_live_subscriber_receives_events():
    """subscribe() then publish(ev) → the returned queue yields ev."""
    from app.runner.events import JobEventBuffer

    loop = asyncio.get_running_loop()
    buf = JobEventBuffer(loop)
    ev = _make_progress_event()

    backlog, queue, closed = buf.subscribe()
    assert not closed
    assert queue is not None

    buf.publish(ev)
    received = await asyncio.wait_for(queue.get(), timeout=1.0)
    assert received == ev


async def test_late_subscriber_replays_backlog():
    """publish 3 events, THEN subscribe → backlog contains all 3."""
    from app.runner.events import JobEventBuffer

    loop = asyncio.get_running_loop()
    buf = JobEventBuffer(loop)

    evs = [_make_progress_event(node=f"node{i}") for i in range(3)]
    for ev in evs:
        buf.publish(ev)

    # Small sleep so call_soon_threadsafe callbacks can run (single-thread test)
    await asyncio.sleep(0)

    backlog, queue, closed = buf.subscribe()
    assert len(backlog) == 3
    assert backlog == evs
    assert not closed


async def test_finished_job_replays_terminal_and_closes():
    """publish a terminal event, then subscribe → backlog has terminal, closed is True,
    queue is None."""
    from app.runner.events import JobEventBuffer

    loop = asyncio.get_running_loop()
    buf = JobEventBuffer(loop)

    terminal = _make_terminal_event()
    buf.publish(terminal)

    await asyncio.sleep(0)

    backlog, queue, closed = buf.subscribe()
    assert terminal in backlog
    assert closed is True
    assert queue is None


async def test_no_lost_wakeup():
    """Interleave publish + subscribe under contention → every event reaches the
    subscriber exactly once, terminal never dropped."""
    from app.runner.events import JobEventBuffer

    loop = asyncio.get_running_loop()
    buf = JobEventBuffer(loop)

    events_to_publish = [_make_progress_event(node=f"n{i}") for i in range(5)]
    terminal = _make_terminal_event()
    all_events = events_to_publish + [terminal]

    # Subscribe before publishing
    backlog, queue, closed = buf.subscribe()
    assert queue is not None

    # Publish all events (simulating worker thread — but we're in the event loop here)
    for ev in all_events:
        buf.publish(ev)
        await asyncio.sleep(0)  # allow callbacks to fire

    # Collect from backlog + queue until terminal
    received = list(backlog)
    while True:
        item = await asyncio.wait_for(queue.get(), timeout=2.0)
        received.append(item)
        if item.event in ("completed", "failed"):
            break

    # Every event received exactly once
    assert len(received) == len(all_events)
    # Terminal present
    assert any(e.event == "completed" for e in received)


async def test_unsubscribe_removes_queue():
    """After unsubscribe(q), a later publish does not target q."""
    from app.runner.events import JobEventBuffer

    loop = asyncio.get_running_loop()
    buf = JobEventBuffer(loop)

    _, queue, _ = buf.subscribe()
    buf.unsubscribe(queue)

    ev = _make_progress_event()
    buf.publish(ev)
    await asyncio.sleep(0)

    # The queue should be empty (nothing delivered after unsubscribe)
    assert queue.empty()


def test_publish_is_thread_safe():
    """Concurrent publish from multiple threads → backlog length == total published."""
    from app.runner.events import JobEventBuffer

    # Use a new event loop since we're in a sync test
    loop = asyncio.new_event_loop()
    try:
        buf = JobEventBuffer(loop)
        n_threads = 5
        n_per_thread = 10

        def publish_batch():
            for i in range(n_per_thread):
                buf.publish(_make_progress_event(node=f"t{i}"))

        threads = [threading.Thread(target=publish_batch) for _ in range(n_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(buf._backlog) == n_threads * n_per_thread
    finally:
        loop.close()
