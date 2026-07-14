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


def _row(job_id, submitted_at, *, original_filename=None, status=JobState.completed):
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
    page = store.list(limit=2, offset=0)
    assert [r.job_id for r in page] == ["j3", "j2"]
    page2 = store.list(limit=2, offset=2)
    assert [r.job_id for r in page2] == ["j1", "j0"]


def test_count_and_all(store):
    assert store.count() == 0
    assert store.all() == []
    for i in range(3):
        store.upsert(_row(f"j{i}", f"2026-01-0{i + 1}T00:00:00+00:00"))
    assert store.count() == 3
    assert [r.job_id for r in store.all()] == ["j2", "j1", "j0"]  # newest-first


def test_list_offset_out_of_range_empty(store):
    store.upsert(_row("j0", "2026-01-01T00:00:00+00:00"))
    assert store.list(limit=10, offset=5) == []  # EC-6
