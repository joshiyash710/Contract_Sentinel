"""
Feature 018: original_filename must survive the JobRecord → _to_row → upsert → get →
from_row round-trip through the registry/store (review B2 — a dropped _to_row field would
silently persist None).
"""

import pytest

from app.runner.events import JobEventBuffer
from app.runner.migrations import upgrade_to_head
from app.runner.store import JobStore


@pytest.fixture()
def registry(tmp_path):
    from app.runner.registry import JobRegistry

    db = str(tmp_path / "reg.db")
    upgrade_to_head(db)
    store = JobStore(db)
    reg = JobRegistry(store=store, saver=None, loop=None, max_jobs=100)
    yield reg
    store.close()


def test_original_filename_roundtrips_through_registry(registry):
    from app.runner.registry import JobRecord

    rec = JobRecord(
        job_id="j1",
        document_path="/data/uploads/j1.docx",
        submitted_at="2026-01-01T00:00:00+00:00",
        buffer=JobEventBuffer(loop=None),
        recipient=None,
        original_filename="Real Contract.docx",
    )
    registry.add(rec)  # persists via _persist_initial → _to_row → upsert

    # Force a rehydrate-from-store path by clearing the live dict.
    registry._live.clear()
    got = registry.get("j1")
    assert got is not None
    assert got.original_filename == "Real Contract.docx"


def test_list_count_all_rows_passthrough(registry):
    from app.runner.registry import JobRecord

    for i in range(3):
        registry.add(
            JobRecord(
                job_id=f"j{i}",
                document_path=f"/u/j{i}.pdf",
                submitted_at=f"2026-01-0{i + 1}T00:00:00+00:00",
                buffer=JobEventBuffer(loop=None),
                original_filename=f"c{i}.pdf",
            )
        )
    assert registry.count() == 3
    assert [r.job_id for r in registry.list_jobs(limit=2, offset=0)] == ["j2", "j1"]
    assert [r.job_id for r in registry.all_rows()] == ["j2", "j1", "j0"]
