"""
Unit tests for app.runner.models — boundary Pydantic types.

TDD red phase: all tests must FAIL (ImportError) until Task 5 implements the module.
Run: python -m pytest tests/unit/test_runner_models.py -v
"""


def test_jobstate_values():
    """JobState values are exactly queued/running/completed/failed (spec §2.3)."""
    from app.runner.models import JobState

    values = {s.value for s in JobState}
    assert values == {"queued", "running", "completed", "failed"}


def test_jobstatus_defaults():
    """JobStatus minimal build → completed_nodes == [], mcp_delivery_status == {},
    report_available is False, optionals None."""
    from app.runner.models import JobState, JobStatus

    status = JobStatus(
        job_id="test-id",
        status=JobState.queued,
        submitted_at="2026-07-08T00:00:00Z",
    )
    assert status.completed_nodes == []
    assert status.mcp_delivery_status == {}
    assert status.report_available is False
    assert status.started_at is None
    assert status.finished_at is None
    assert status.error is None
    assert status.current_node is None
    # report_path is intentionally NOT a boundary field (spec §2.3) — clients get
    # report_available + the /report download endpoint, never the server FS path.
    assert not hasattr(status, "report_path")


def test_progressevent_roundtrips():
    """ProgressEvent(event='completed', ...) round-trips via model_dump_json()/parse;
    final embeds a JobStatus."""
    from app.runner.models import JobState, JobStatus, ProgressEvent

    status = JobStatus(
        job_id="x",
        status=JobState.completed,
        submitted_at="2026-07-08T00:00:00Z",
        report_available=True,
    )
    ev = ProgressEvent(event="completed", job_id="x", final=status)
    serialized = ev.model_dump_json()
    parsed = ProgressEvent.model_validate_json(serialized)
    assert parsed.event == "completed"
    assert parsed.job_id == "x"
    assert parsed.final is not None
    assert parsed.final.status == JobState.completed
    assert parsed.final.report_available is True


def test_progressevent_carries_elapsed_seconds():
    """ProgressEvent surfaces per-node elapsed_seconds (spec §2.4)."""
    from app.runner.models import ProgressEvent

    ev = ProgressEvent(
        event="progress",
        job_id="x",
        node="ingest_agent",
        index=1,
        total=7,
        elapsed_seconds=1.5,
    )
    parsed = ProgressEvent.model_validate_json(ev.model_dump_json())
    assert parsed.elapsed_seconds == 1.5
    # Optional — absent when a node recorded no timing
    assert ProgressEvent(event="progress", job_id="x").elapsed_seconds is None


def test_analyze_accepted_shape():
    """AnalyzeAccepted requires job_id, status, submitted_at; a valid one constructs."""
    from app.runner.models import AnalyzeAccepted, JobState

    accepted = AnalyzeAccepted(
        job_id="abc-123",
        status=JobState.queued,
        submitted_at="2026-07-08T00:00:00Z",
    )
    assert accepted.job_id == "abc-123"
    assert accepted.status == JobState.queued
    assert accepted.submitted_at == "2026-07-08T00:00:00Z"
