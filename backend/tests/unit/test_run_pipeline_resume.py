"""
Unit tests for run_pipeline resume/checkpointer plumbing (spec AC-6/10/11, EC-1).

Written red (Task 7) — green after core.py and worker.py are updated.
"""

from unittest.mock import MagicMock, patch

import pytest


def _make_fake_graph(scripted_states):
    """Return a mock compiled graph whose stream() records calls and yields states."""
    calls = []

    class _FakeGraph:
        def stream(self, inp, stream_mode=None, config=None):
            calls.append({"inp": inp, "config": config})
            yield from scripted_states

        def get_graph(self):
            return MagicMock()

    return _FakeGraph(), calls


@pytest.fixture(autouse=True)
def _patch_delivery(monkeypatch):
    monkeypatch.setattr(
        "app.runner.core.deliver_report_sync",
        lambda state, *, recipient=None: {"mcp_delivery_status": {}},
    )


def test_fresh_seeds_initial(monkeypatch):
    """Fresh run streams the seeded initial dict with document_path (spec AC-6/10)."""
    states = [{"current_node": "ingest_agent"}, {"current_node": "report"}]
    fake, calls = _make_fake_graph(states)
    saver = MagicMock()
    monkeypatch.setattr("app.runner.core.build_graph", lambda checkpointer=None: fake)

    from app.runner.core import run_pipeline

    run_pipeline("/tmp/c.pdf", checkpointer=saver, thread_id="t1", resume=False)

    assert len(calls) == 1
    assert "document_path" in calls[0]["inp"]
    assert "processing_started_at" in calls[0]["inp"]
    assert calls[0]["config"] == {"configurable": {"thread_id": "t1"}}


def test_resume_streams_none(monkeypatch):
    """Resume run streams None (spec AC-11)."""
    fake, calls = _make_fake_graph([{"current_node": "report"}])
    saver = MagicMock()
    monkeypatch.setattr("app.runner.core.build_graph", lambda checkpointer=None: fake)

    from app.runner.core import run_pipeline

    run_pipeline("/tmp/c.pdf", checkpointer=saver, thread_id="t1", resume=True)

    assert calls[0]["inp"] is None


def test_resume_dedup(monkeypatch):
    """Re-emitted already_completed nodes are not fired to on_progress (spec EC-1)."""
    states = [
        {"current_node": "ingest_agent"},  # re-emitted by stream(None) — must be deduped
        {"current_node": "clause_splitter"},  # new — must fire
    ]
    fake, _ = _make_fake_graph(states)
    saver = MagicMock()
    monkeypatch.setattr("app.runner.core.build_graph", lambda checkpointer=None: fake)

    fired = []

    from app.runner.core import run_pipeline

    run_pipeline(
        "/tmp/c.pdf",
        checkpointer=saver,
        thread_id="t1",
        resume=True,
        already_completed=["ingest_agent"],
        on_progress=lambda p: fired.append(p.node),
    )

    assert fired == ["clause_splitter"]
    assert "ingest_agent" not in fired


def test_no_checkpointer_unchanged(monkeypatch):
    """checkpointer=None → config=None and fresh initial dict (011 behaviour, spec D7)."""
    states = [{"current_node": "report"}]
    fake, calls = _make_fake_graph(states)
    monkeypatch.setattr("app.runner.core.build_graph", lambda checkpointer=None: fake)

    from app.runner.core import run_pipeline

    run_pipeline("/tmp/c.pdf")

    assert calls[0]["config"] is None
    assert "document_path" in calls[0]["inp"]
