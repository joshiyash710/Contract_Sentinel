"""
Unit tests for feature-018 additions to app.runner.store — the original_filename column
and the list/count/all read methods for the dashboard endpoints.
"""

import pytest

from app.runner.migrations import upgrade_to_head
from app.runner.models import JobState


@pytest.fixture()
def store(tmp_path):
    from app.runner.store import JobStore

    db = str(tmp_path / "test.db")
    upgrade_to_head(db)
    s = JobStore(db)
    yield s
    s.close()


def _row(job_id, submitted_at, *, original_filename=None, status=JobState.completed, user_id="u1"):
    from app.runner.store import JobRow

    return JobRow(
        job_id=job_id,
        document_path=f"/tmp/{job_id}.pdf",
        recipient=None,
        status=status,
        submitted_at=submitted_at,
        started_at=None,
        finished_at=None,
        current_node="report",
        completed_nodes=[],
        report_path=f"/data/reports/{job_id}.md",
        mcp_delivery_status={},
        error=None,
        original_filename=original_filename,
        user_id=user_id,
    )


def test_original_filename_roundtrip(store):
    store.upsert(_row("j1", "2026-01-01T00:00:00+00:00", original_filename="heavy_contract.docx"))
    got = store.get("j1")
    assert got is not None
    assert got.original_filename == "heavy_contract.docx"  # AC-11


def test_legacy_null_filename(store):
    # A row persisted without a filename decodes as None (AC-12 / EC-7 — legacy rows).
    store.upsert(_row("j1", "2026-01-01T00:00:00+00:00", original_filename=None))
    assert store.get("j1").original_filename is None


def test_list_pagination_newest_first(store):
    # Insert oldest→newest; list must return newest-first.
    for i in range(4):
        store.upsert(_row(f"j{i}", f"2026-01-0{i + 1}T00:00:00+00:00"))
    page = store.list("u1", limit=2, offset=0)
    assert [r.job_id for r in page] == ["j3", "j2"]
    page2 = store.list("u1", limit=2, offset=2)
    assert [r.job_id for r in page2] == ["j1", "j0"]


def test_count_and_all(store):
    assert store.count("u1") == 0
    assert store.all("u1") == []
    for i in range(3):
        store.upsert(_row(f"j{i}", f"2026-01-0{i + 1}T00:00:00+00:00"))
    assert store.count("u1") == 3
    assert [r.job_id for r in store.all("u1")] == ["j2", "j1", "j0"]  # newest-first


def test_list_offset_out_of_range_empty(store):
    store.upsert(_row("j0", "2026-01-01T00:00:00+00:00"))
    assert store.list("u1", limit=10, offset=5) == []  # EC-6


def test_reads_scoped_by_user_id(store):
    # Feature 019 (AC-A2/A6): list/all/count return only the caller's rows;
    # a second user's rows and legacy NULL-owner rows are excluded.
    store.upsert(_row("a1", "2026-01-01T00:00:00+00:00", user_id="u1"))
    store.upsert(_row("a2", "2026-01-02T00:00:00+00:00", user_id="u1"))
    store.upsert(_row("b1", "2026-01-03T00:00:00+00:00", user_id="u2"))
    store.upsert(_row("legacy", "2026-01-04T00:00:00+00:00", user_id=None))

    assert store.count("u1") == 2
    assert store.count("u2") == 1
    assert [r.job_id for r in store.all("u1")] == ["a2", "a1"]  # newest-first, u1 only
    assert [r.job_id for r in store.all("u2")] == ["b1"]
    assert [r.job_id for r in store.list("u1", limit=10, offset=0)] == ["a2", "a1"]
    # The legacy NULL-owner row is returned to no scoped caller.
    all_ids = {r.job_id for r in store.all("u1")} | {r.job_id for r in store.all("u2")}
    assert "legacy" not in all_ids
    # get() still fetches by id regardless of owner (ownership is enforced in the route).
    assert store.get("legacy") is not None
    assert store.get("legacy").user_id is None
