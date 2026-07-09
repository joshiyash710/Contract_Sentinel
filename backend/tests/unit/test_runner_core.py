"""
Unit tests for app.runner.core — run_pipeline, RunResult, NodeProgress.

The graph and delivery are patched so no Ollama / Google calls are made.
TDD red phase: all tests must FAIL (ImportError) until Task 9 implements the module.
Run: python -m pytest tests/unit/test_runner_core.py -v
"""

import inspect
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Scripted fake compiled graph helpers
# ---------------------------------------------------------------------------


def _make_fake_graph(states: list, *, raise_exc: Exception = None):
    """Return a fake compiled graph object.

    states: list of full-state dicts to yield from .stream()
    raise_exc: if set, .stream() raises this exception instead of yielding
    """
    fake = MagicMock()

    def fake_stream(initial, stream_mode=None, config=None):
        if raise_exc is not None:
            raise raise_exc
        yield from states

    fake.stream = fake_stream
    return fake


# Happy-path scripted states (7 nodes, values mode — each dict is the full state).
# node_timings mirrors what real nodes write ({current_node: elapsed}).
_HAPPY_STATES = [
    {
        "current_node": "ingest_agent",
        "document_path": "c.pdf",
        "node_timings": {"ingest_agent": 0.5},
    },
    {
        "current_node": "clause_splitter",
        "document_path": "c.pdf",
        "node_timings": {"clause_splitter": 0.5},
    },
    {
        "current_node": "crag_retrieval",
        "document_path": "c.pdf",
        "node_timings": {"crag_retrieval": 0.5},
    },
    {
        "current_node": "self_rag_validation",
        "document_path": "c.pdf",
        "node_timings": {"self_rag_validation": 0.5},
    },
    {
        "current_node": "risk_score",
        "document_path": "c.pdf",
        "node_timings": {"risk_score": 0.5},
    },
    {
        "current_node": "redline",
        "document_path": "c.pdf",
        "node_timings": {"redline": 0.5},
    },
    {
        "current_node": "report",
        "document_path": "c.pdf",
        "node_timings": {"report": 0.5},
        "report_path": "data/reports/doc.md",
        "document_id": "doc",
    },
]

_SKIP_REDLINE_STATES = [
    {"current_node": "ingest_agent", "document_path": "c.pdf"},
    {"current_node": "clause_splitter", "document_path": "c.pdf"},
    {"current_node": "crag_retrieval", "document_path": "c.pdf"},
    {"current_node": "self_rag_validation", "document_path": "c.pdf"},
    {"current_node": "risk_score", "document_path": "c.pdf"},
    {"current_node": "skip_redline", "document_path": "c.pdf"},
    {
        "current_node": "report",
        "document_path": "c.pdf",
        "report_path": "data/reports/doc.md",
        "document_id": "doc",
    },
]

_INGEST_ERROR_STATES = [
    {
        "current_node": "ingest_agent",
        "document_path": "c.pdf",
        "ingest_error": {"message": "bad pdf", "error_type": "ParseError"},
    }
]


def _stub_delivery(state, *, recipient=None):
    return {"mcp_delivery_status": {"drive": "SUCCESS", "gmail": "SUCCESS"}}


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_seeds_only_document_path_and_started_at():
    """Initial state passed to .stream has keys ⊆ {document_path, processing_started_at}."""
    import app.runner.core as core

    captured = {}

    def fake_stream(initial, stream_mode=None, config=None):
        captured["initial"] = initial
        yield from _HAPPY_STATES

    fake_graph = MagicMock()
    fake_graph.stream = fake_stream

    with patch.object(core, "build_graph", return_value=fake_graph), patch.object(
        core, "deliver_report_sync", side_effect=_stub_delivery
    ):
        core.run_pipeline("c.pdf")

    allowed = {"document_path", "processing_started_at"}
    assert set(captured["initial"].keys()) <= allowed


def test_build_graph_called_once():
    """build_graph is invoked exactly once per run_pipeline call."""
    import app.runner.core as core

    with patch.object(
        core, "build_graph", return_value=_make_fake_graph(_HAPPY_STATES)
    ) as mock_bg, patch.object(core, "deliver_report_sync", side_effect=_stub_delivery):
        core.run_pipeline("c.pdf")

    mock_bg.assert_called_once()


def test_progress_callback_per_node():
    """on_progress fires once per distinct current_node, in order, with mapped index/total."""
    import app.runner.core as core

    calls = []

    def on_progress(p):
        calls.append(p)

    with patch.object(
        core, "build_graph", return_value=_make_fake_graph(_HAPPY_STATES)
    ), patch.object(core, "deliver_report_sync", side_effect=_stub_delivery):
        core.run_pipeline("c.pdf", on_progress=on_progress)

    node_names = [c.node for c in calls]
    assert node_names == [
        "ingest_agent",
        "clause_splitter",
        "crag_retrieval",
        "self_rag_validation",
        "risk_score",
        "redline",
        "report",
    ]
    for c in calls:
        assert c.total == 7
        assert isinstance(c.index, int)
        # elapsed_seconds is read from state["node_timings"][node] (spec §2.4)
        assert c.elapsed_seconds == 0.5


def test_redline_branch_indices():
    """redline path emits index 6; skip_redline path also emits index 6."""
    import app.runner.core as core

    redline_calls = []
    skip_calls = []

    def on_progress_redline(p):
        if p.node == "redline":
            redline_calls.append(p)

    def on_progress_skip(p):
        if p.node == "skip_redline":
            skip_calls.append(p)

    with patch.object(
        core, "build_graph", return_value=_make_fake_graph(_HAPPY_STATES)
    ), patch.object(core, "deliver_report_sync", side_effect=_stub_delivery):
        core.run_pipeline("c.pdf", on_progress=on_progress_redline)

    with patch.object(
        core, "build_graph", return_value=_make_fake_graph(_SKIP_REDLINE_STATES)
    ), patch.object(core, "deliver_report_sync", side_effect=_stub_delivery):
        core.run_pipeline("c.pdf", on_progress=on_progress_skip)

    assert redline_calls[0].index == 6
    assert skip_calls[0].index == 6


def test_delivery_called_with_recipient():
    """deliver_report_sync is called with the passed recipient; None when omitted."""
    import app.runner.core as core

    delivery_calls = []

    def capture_delivery(state, *, recipient=None):
        delivery_calls.append(recipient)
        return {"mcp_delivery_status": {}}

    with patch.object(
        core, "build_graph", return_value=_make_fake_graph(_HAPPY_STATES)
    ), patch.object(core, "deliver_report_sync", side_effect=capture_delivery):
        core.run_pipeline("c.pdf", recipient="user@example.com")

    with patch.object(
        core, "build_graph", return_value=_make_fake_graph(_HAPPY_STATES)
    ), patch.object(core, "deliver_report_sync", side_effect=capture_delivery):
        core.run_pipeline("c.pdf")

    assert delivery_calls[0] == "user@example.com"
    assert delivery_calls[1] is None


def test_final_state_has_completed_timestamp():
    """RunResult.final_state['processing_completed_at'] is set by the runner."""
    import app.runner.core as core

    with patch.object(
        core, "build_graph", return_value=_make_fake_graph(_HAPPY_STATES)
    ), patch.object(core, "deliver_report_sync", side_effect=_stub_delivery):
        result = core.run_pipeline("c.pdf")

    assert "processing_completed_at" in result.final_state
    assert result.final_state["processing_completed_at"]


def test_result_carries_report_path_and_delivery():
    """RunResult.report_path / .mcp_delivery_status come from the terminal state / delivery."""
    import app.runner.core as core

    with patch.object(
        core, "build_graph", return_value=_make_fake_graph(_HAPPY_STATES)
    ), patch.object(core, "deliver_report_sync", side_effect=_stub_delivery):
        result = core.run_pipeline("c.pdf")

    assert result.report_path == "data/reports/doc.md"
    assert result.mcp_delivery_status == {"drive": "SUCCESS", "gmail": "SUCCESS"}


def test_ingest_error_surfaced_not_raised():
    """Scripted ingest_error in terminal state → RunResult.ingest_error set, NO exception."""
    import app.runner.core as core

    def delivery_no_report(state, *, recipient=None):
        return {"mcp_delivery_status": {}}

    with patch.object(
        core, "build_graph", return_value=_make_fake_graph(_INGEST_ERROR_STATES)
    ), patch.object(core, "deliver_report_sync", side_effect=delivery_no_report):
        result = core.run_pipeline("c.pdf")

    assert result.ingest_error is not None
    assert "message" in result.ingest_error or isinstance(result.ingest_error, dict)


def test_graph_exception_propagates():
    """If .stream raises, the exception propagates out of run_pipeline."""
    import app.runner.core as core

    boom = RuntimeError("graph exploded")
    with patch.object(
        core, "build_graph", return_value=_make_fake_graph([], raise_exc=boom)
    ), patch.object(core, "deliver_report_sync", side_effect=_stub_delivery):
        with pytest.raises(RuntimeError, match="graph exploded"):
            core.run_pipeline("c.pdf")


def test_only_public_entrypoints_imported():
    """core.py references build_graph + deliver_report_sync only — no app.graph.nodes. import."""
    import app.runner.core as core

    src = inspect.getsource(core)
    assert "build_graph" in src
    assert "deliver_report_sync" in src
    assert "app.graph.nodes." not in src
