"""
Unit tests for app.runner.store — pure SQLite job store.

Written red (Task 4) — green after store.py is created.
"""

import pytest

from app.graph.state import MCPDeliveryStatus
from app.runner.migrations import upgrade_to_head
from app.runner.models import ErrorInfo, JobState


@pytest.fixture()
def store(tmp_path):
    from app.runner.store import JobStore

    db = str(tmp_path / "test.db")
    upgrade_to_head(db)
    s = JobStore(db)
    yield s
    s.close()


def _make_row(job_id="j1"):
    from app.runner.store import JobRow

    return JobRow(
        job_id=job_id,
        document_path="/tmp/contract.pdf",
        recipient="user@example.com",
        status=JobState.completed,
        submitted_at="2026-01-01T00:00:00+00:00",
        started_at="2026-01-01T00:01:00+00:00",
        finished_at="2026-01-01T00:02:00+00:00",
        current_node="report",
        completed_nodes=["ingest_agent", "clause_splitter"],
        report_path="/data/reports/abc.md",
        mcp_delivery_status={
            "drive": {
                "status": MCPDeliveryStatus.SUCCESS,
                "error_message": None,
                "delivered_at": "2026-01-01T00:02:05+00:00",
            }
        },
        error=ErrorInfo(kind="x", message="y"),
    )


def test_upsert_get_roundtrip(store):
    row = _make_row()
    store.upsert(row)
    got = store.get("j1")

    assert got is not None
    assert got.job_id == "j1"
    assert got.document_path == "/tmp/contract.pdf"
    assert got.recipient == "user@example.com"
    assert got.status == JobState.completed
    assert got.completed_nodes == ["ingest_agent", "clause_splitter"]
    assert got.report_path == "/data/reports/abc.md"
    # MCPDeliveryStatus is a str-enum, serializes as "success" then decoded as plain str
    assert got.mcp_delivery_status["drive"]["status"] == "success"
    assert got.error is not None
    assert got.error.kind == "x"
    assert got.error.message == "y"


def test_upsert_is_update(store):
    row = _make_row()
    store.upsert(row)

    from app.runner.store import JobRow

    updated = JobRow(
        job_id="j1",
        document_path="/tmp/contract.pdf",
        recipient=None,
        status=JobState.running,
        submitted_at="2026-01-01T00:00:00+00:00",
        started_at="2026-01-01T00:01:00+00:00",
        finished_at=None,
        current_node="crag_retrieval",
        completed_nodes=["ingest_agent"],
        report_path=None,
        mcp_delivery_status={},
        error=None,
    )
    store.upsert(updated)

    got = store.get("j1")
    assert got is not None
    assert got.status == JobState.running
    assert got.current_node == "crag_retrieval"
    assert got.error is None


def test_nonterminal_filters(store):
    from app.runner.store import JobRow

    def _row(job_id, status, submitted_at):
        return JobRow(
            job_id=job_id,
            document_path="/f",
            recipient=None,
            status=status,
            submitted_at=submitted_at,
            started_at=None,
            finished_at=None,
            current_node=None,
            completed_nodes=[],
            report_path=None,
            mcp_delivery_status={},
            error=None,
        )

    store.upsert(_row("queued1", JobState.queued, "2026-01-01T00:00:00"))
    store.upsert(_row("running1", JobState.running, "2026-01-01T00:01:00"))
    store.upsert(_row("done1", JobState.completed, "2026-01-01T00:02:00"))
    store.upsert(_row("fail1", JobState.failed, "2026-01-01T00:03:00"))

    rows = store.nonterminal()
    ids = [r.job_id for r in rows]
    assert "queued1" in ids
    assert "running1" in ids
    assert "done1" not in ids
    assert "fail1" not in ids
    # ordered by submitted_at
    assert ids == ["queued1", "running1"]


def test_prune_returns_oldest(store, tmp_path):
    from app.runner.store import JobRow

    N = 3
    for i in range(N + 2):
        store.upsert(
            JobRow(
                job_id=f"j{i}",
                document_path="/f",
                recipient=None,
                status=JobState.completed,
                submitted_at=f"2026-01-0{i + 1}T00:00:00",
                started_at=None,
                finished_at=None,
                current_node=None,
                completed_nodes=[],
                report_path=None,
                mcp_delivery_status={},
                error=None,
            )
        )

    victims = store.prune(N)
    assert len(victims) == 2
    # oldest two are j0 and j1
    assert set(victims) == {"j0", "j1"}
    assert store.get("j0") is None
    assert store.get("j1") is None
    assert store.get("j2") is not None


def test_get_missing_none(store):
    assert store.get("nope") is None


def test_user_id_roundtrip(store):
    # Feature 019 (AC-A1): the owning account's id is persisted and read back.
    from app.runner.store import JobRow

    row = JobRow(
        job_id="owned",
        document_path="/tmp/c.pdf",
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
        user_id="user-123",
    )
    store.upsert(row)
    got = store.get("owned")
    assert got is not None
    assert got.user_id == "user-123"
    # A row persisted without an owner decodes as None (legacy).
    assert store.get("j-none") is None
