"""
Integration tests for GET /api/jobs/{job_id}/events — SSE progress streaming.

TDD red phase: all tests FAIL (ImportError) until Task 19 implements create_app.
Run: python -m pytest tests/integration/test_api_sse.py -v
"""

import json

from tests.integration.conftest import _wait_for


def _submit(client, filename="c.pdf"):
    r = client.post(
        "/api/analyze",
        files={"file": (filename, b"%PDF-1.4", "application/pdf")},
    )
    assert r.status_code == 202
    return r.json()["job_id"]


def _collect_sse_events(client, job_id):
    """Subscribe to SSE and collect all ProgressEvent dicts until stream closes."""
    events = []
    with client.stream("GET", f"/api/jobs/{job_id}/events") as r:
        assert r.status_code == 200
        for line in r.iter_lines():
            if line.startswith("data:"):
                payload = line[len("data:") :].strip()
                if payload:
                    events.append(json.loads(payload))
    return events


def test_event_stream_content_type(client):
    """GET /api/jobs/{id}/events → text/event-stream content type (AC-9)."""
    job_id = _submit(client)
    _wait_for(client, job_id, "completed")

    with client.stream("GET", f"/api/jobs/{job_id}/events") as r:
        assert "text/event-stream" in r.headers.get("content-type", "")


def test_progress_then_terminal_then_close(client):
    """One 'progress' event per node entered, in order, then exactly one terminal event,
    then stream closes (AC-9)."""
    job_id = _submit(client)
    # Let the job complete so backlog has all events
    _wait_for(client, job_id, "completed")

    events = _collect_sse_events(client, job_id)

    # All events have correct job_id
    for ev in events:
        assert ev["job_id"] == job_id

    # Progress events are all before the terminal
    progress_events = [e for e in events if e["event"] == "progress"]
    terminal_events = [e for e in events if e["event"] in ("completed", "failed")]

    assert len(progress_events) == 7  # 7 nodes
    assert len(terminal_events) == 1
    assert terminal_events[0]["event"] == "completed"

    # Terminal is last
    assert events[-1] == terminal_events[0]


def test_terminal_final_equals_status(client):
    """Terminal event's 'final' equals GET /api/jobs/{id} at that moment (AC-10)."""
    job_id = _submit(client)
    _wait_for(client, job_id, "completed")

    events = _collect_sse_events(client, job_id)
    terminal = next(e for e in events if e["event"] in ("completed", "failed"))

    status = client.get(f"/api/jobs/{job_id}").json()

    assert terminal["final"]["status"] == status["status"]
    assert terminal["final"]["job_id"] == status["job_id"]
    assert terminal["final"]["report_available"] == status["report_available"]


def test_finished_job_stream_immediate_terminal(client):
    """Opening /events after completion → terminal event immediately, no hang (AC-11)."""
    job_id = _submit(client)
    _wait_for(client, job_id, "completed")

    events = _collect_sse_events(client, job_id)

    # Stream should have ended (we received it fully)
    terminal_events = [e for e in events if e["event"] in ("completed", "failed")]
    assert len(terminal_events) == 1


def test_late_subscriber_gets_full_sequence(client):
    """Subscribing after some events have been published → backlog replay gives all
    events (EC-7). With a fast fake, subscribing after completion tests the same
    backlog-replay guarantee."""
    job_id = _submit(client)
    _wait_for(client, job_id, "completed")

    # At this point all 7 progress events + 1 terminal are in the backlog
    events = _collect_sse_events(client, job_id)

    node_names = [e.get("node") for e in events if e["event"] == "progress"]
    assert "ingest_agent" in node_names
    assert "report" in node_names
    assert len(node_names) == 7

    terminal = next((e for e in events if e["event"] in ("completed", "failed")), None)
    assert terminal is not None


def test_sse_named_event_field(client):
    """Each SSE frame carries a named `event:` line matching its payload (spec §2.4, F1),
    so a browser EventSource.addEventListener('completed'|'progress', ...) works."""
    job_id = _submit(client)
    _wait_for(client, job_id, "completed")

    event_lines = []
    with client.stream("GET", f"/api/jobs/{job_id}/events") as r:
        for line in r.iter_lines():
            if line.startswith("event:"):
                event_lines.append(line[len("event:") :].strip())

    assert "progress" in event_lines
    assert event_lines[-1] == "completed"


def test_unknown_job_events_404(client):
    """GET /api/jobs/{unknown}/events → 404 (AC-17)."""
    r = client.get("/api/jobs/does-not-exist/events")
    assert r.status_code == 404
