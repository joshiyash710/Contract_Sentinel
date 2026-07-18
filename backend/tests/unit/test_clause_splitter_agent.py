"""
Unit tests for app.graph.nodes.clause_splitter_agent.clause_splitter_agent().

Mocks split_by_regex and refine_with_llm at the node module level.
Written BEFORE the implementation (TDD red phase).

Run: python -m pytest tests/unit/test_clause_splitter_agent.py -v
Expected before Task 9: FAIL (ImportError)
Expected after Task 9:  all 13 PASS
"""

from unittest.mock import MagicMock

import app.graph.nodes.clause_splitter_agent as clause_splitter_agent_module
from app.graph.nodes.clause_splitter_agent import clause_splitter_agent
from app.graph.nodes.splitters import ClauseBoundary
from app.graph.state import ClauseType

# ── Helpers ────────────────────────────────────────────────────────────────────


def make_state(extracted_text="", ingest_error=None, document_id="doc-test-1"):
    return {
        "document_id": document_id,
        "extracted_text": extracted_text,
        "ingest_error": ingest_error,
    }


def make_boundary(n, text="Clause text.", section_number="1", clause_type=None):
    return ClauseBoundary(
        clause_id=f"clause_{n:03d}",
        text=text,
        position=n,
        section_number=section_number,
        clause_type=clause_type,
    )


LONG_TEXT = (
    "1. Definitions\nAll terms are defined here in detail.\n" * 10
)  # > 100 chars


# ── Tests ──────────────────────────────────────────────────────────────────────


def test_splitter_success_basic(monkeypatch):
    """Full success path: correct clauses dict with all required fields."""
    fake_clauses = [make_boundary(1, "Definitions.", "1", "definitions")]
    monkeypatch.setattr(
        clause_splitter_agent_module, "split_by_regex", lambda t: fake_clauses
    )
    monkeypatch.setattr(
        clause_splitter_agent_module, "refine_with_llm", lambda c, t, m: c
    )

    result = clause_splitter_agent(make_state(LONG_TEXT))

    assert "clauses" in result
    assert len(result["clauses"]) == 1
    assert "clause_001" in result["clauses"]
    clause = result["clauses"]["clause_001"]
    assert clause["text"] == "Definitions."
    assert clause["position"] == 1


def test_splitter_ingest_error_returns_empty(monkeypatch):
    """ingest_error set → empty clauses dict; regex/LLM NOT called."""
    regex_mock = MagicMock()
    llm_mock = MagicMock()
    monkeypatch.setattr(clause_splitter_agent_module, "split_by_regex", regex_mock)
    monkeypatch.setattr(clause_splitter_agent_module, "refine_with_llm", llm_mock)

    state = make_state(
        "Some text.", ingest_error={"error_type": "corrupted_file", "message": "bad"}
    )
    result = clause_splitter_agent(state)

    assert result["clauses"] == {}
    regex_mock.assert_not_called()
    llm_mock.assert_not_called()


def test_splitter_empty_text_returns_empty(monkeypatch, caplog):
    """Empty extracted_text → empty clauses dict, warning logged."""
    monkeypatch.setattr(clause_splitter_agent_module, "split_by_regex", lambda t: [])
    monkeypatch.setattr(
        clause_splitter_agent_module, "refine_with_llm", lambda c, t, m: c
    )

    with caplog.at_level("WARNING"):
        result = clause_splitter_agent(make_state(""))

    assert result["clauses"] == {}
    assert any(
        "warning" in r.levelname.lower() or "empty" in r.message.lower()
        for r in caplog.records
    )


def test_splitter_short_text_single_clause(monkeypatch):
    """Text shorter than MIN_CLAUSE_LENGTH → single clause without regex pre-pass."""
    monkeypatch.setattr(clause_splitter_agent_module, "MIN_CLAUSE_LENGTH", 100)

    regex_spy = MagicMock()
    monkeypatch.setattr(clause_splitter_agent_module, "split_by_regex", regex_spy)
    monkeypatch.setattr(
        clause_splitter_agent_module, "refine_with_llm", lambda c, t, m: c
    )

    result = clause_splitter_agent(make_state("Short text."))

    # regex should NOT be called for short text
    regex_spy.assert_not_called()
    assert "clause_001" in result["clauses"]
    assert result["clauses"]["clause_001"]["position"] == 1


def test_splitter_max_clauses_truncated(monkeypatch, caplog):
    """When regex output exceeds MAX_CLAUSES_LIMIT, final clauses dict is truncated."""
    monkeypatch.setattr(clause_splitter_agent_module, "MAX_CLAUSES_LIMIT", 2)

    many_clauses = [make_boundary(i, f"Clause {i}.", str(i)) for i in range(1, 6)]
    monkeypatch.setattr(
        clause_splitter_agent_module, "split_by_regex", lambda t: many_clauses
    )
    monkeypatch.setattr(
        clause_splitter_agent_module, "refine_with_llm", lambda c, t, m: c
    )

    with caplog.at_level("WARNING"):
        result = clause_splitter_agent(make_state(LONG_TEXT))

    assert len(result["clauses"]) == 2


def test_splitter_partial_update_only(monkeypatch):
    """Return dict contains ONLY clauses, current_node, node_timings."""
    fake_clauses = [make_boundary(1, "Text.", "1", "general")]
    monkeypatch.setattr(
        clause_splitter_agent_module, "split_by_regex", lambda t: fake_clauses
    )
    monkeypatch.setattr(
        clause_splitter_agent_module, "refine_with_llm", lambda c, t, m: c
    )

    result = clause_splitter_agent(make_state(LONG_TEXT))

    allowed_keys = {"clauses", "current_node", "node_timings"}
    forbidden = set(result.keys()) - allowed_keys
    assert not forbidden, f"Return dict contains forbidden keys: {forbidden}"

    # Explicitly verify none of the IngestAgent or downstream keys are present
    for key in (
        "document_id",
        "extracted_text",
        "ocr_used",
        "report_path",
        "evidence_trail",
        "mcp_delivery_status",
        "error_count",
    ):
        assert key not in result, f"Forbidden key '{key}' present in return dict"


def test_splitter_clause_type_enum_conversion(monkeypatch):
    """Raw clause_type strings are converted to ClauseType enum values in output."""
    fake_clauses = [
        make_boundary(1, "Payment text.", "1", "payment"),
        make_boundary(2, "Confidential info.", "2", "confidentiality"),
    ]
    monkeypatch.setattr(
        clause_splitter_agent_module, "split_by_regex", lambda t: fake_clauses
    )
    monkeypatch.setattr(
        clause_splitter_agent_module, "refine_with_llm", lambda c, t, m: c
    )

    result = clause_splitter_agent(make_state(LONG_TEXT))

    assert result["clauses"]["clause_001"]["clause_type"] == ClauseType.PAYMENT
    assert result["clauses"]["clause_002"]["clause_type"] == ClauseType.CONFIDENTIALITY


def test_splitter_clause_type_none_preserved(monkeypatch):
    """None clause_type is preserved (not forced to a value)."""
    fake_clauses = [make_boundary(1, "Some text.", "1", None)]
    monkeypatch.setattr(
        clause_splitter_agent_module, "split_by_regex", lambda t: fake_clauses
    )
    monkeypatch.setattr(
        clause_splitter_agent_module, "refine_with_llm", lambda c, t, m: c
    )

    result = clause_splitter_agent(make_state(LONG_TEXT))

    assert result["clauses"]["clause_001"]["clause_type"] is None


def test_splitter_position_sequential(monkeypatch):
    """Positions are 1-indexed, sequential, and contiguous."""
    fake_clauses = [make_boundary(i, f"Clause {i}.", str(i)) for i in range(1, 5)]
    monkeypatch.setattr(
        clause_splitter_agent_module, "split_by_regex", lambda t: fake_clauses
    )
    monkeypatch.setattr(
        clause_splitter_agent_module, "refine_with_llm", lambda c, t, m: c
    )

    result = clause_splitter_agent(make_state(LONG_TEXT))

    positions = sorted(c["position"] for c in result["clauses"].values())
    assert positions == list(range(1, len(fake_clauses) + 1))


def test_splitter_required_fields_present(monkeypatch):
    """Every clause has text, position, section_number, clause_type fields."""
    fake_clauses = [make_boundary(1, "Complete clause.", "1.1", None)]
    monkeypatch.setattr(
        clause_splitter_agent_module, "split_by_regex", lambda t: fake_clauses
    )
    monkeypatch.setattr(
        clause_splitter_agent_module, "refine_with_llm", lambda c, t, m: c
    )

    result = clause_splitter_agent(make_state(LONG_TEXT))

    for clause_id, clause in result["clauses"].items():
        assert "text" in clause, f"{clause_id} missing 'text'"
        assert "position" in clause, f"{clause_id} missing 'position'"
        assert "section_number" in clause, f"{clause_id} missing 'section_number'"
        assert "clause_type" in clause, f"{clause_id} missing 'clause_type'"


def test_splitter_node_timing_recorded(monkeypatch):
    """node_timings['clause_splitter'] is a positive float."""
    fake_clauses = [make_boundary(1, "Text.", "1")]
    monkeypatch.setattr(
        clause_splitter_agent_module, "split_by_regex", lambda t: fake_clauses
    )
    monkeypatch.setattr(
        clause_splitter_agent_module, "refine_with_llm", lambda c, t, m: c
    )

    result = clause_splitter_agent(make_state(LONG_TEXT))

    assert "node_timings" in result
    assert "clause_splitter" in result["node_timings"]
    assert result["node_timings"]["clause_splitter"] >= 0.0


def test_splitter_current_node_set(monkeypatch):
    """current_node is 'clause_splitter'."""
    fake_clauses = [make_boundary(1, "Text.", "1")]
    monkeypatch.setattr(
        clause_splitter_agent_module, "split_by_regex", lambda t: fake_clauses
    )
    monkeypatch.setattr(
        clause_splitter_agent_module, "refine_with_llm", lambda c, t, m: c
    )

    result = clause_splitter_agent(make_state(LONG_TEXT))

    assert result["current_node"] == "clause_splitter"


def test_splitter_no_error_count_on_fallback(monkeypatch):
    """LLM-fallback path does NOT set error_count in return dict."""
    # Simulate LLM fallback (refine_with_llm returns input unchanged = regex-only)
    fake_clauses = [make_boundary(1, "Text.", "1")]
    monkeypatch.setattr(
        clause_splitter_agent_module, "split_by_regex", lambda t: fake_clauses
    )
    monkeypatch.setattr(
        clause_splitter_agent_module, "refine_with_llm", lambda c, t, m: c
    )

    result = clause_splitter_agent(make_state(LONG_TEXT))

    assert "error_count" not in result


def test_splitter_gated_skips_llm(monkeypatch):
    """Feature 025 lever A: when split_by_regex yields > CLAUSE_SPLITTER_LLM_MAX_CLAUSES clauses,
    the LLM refinement is SKIPPED and the regex boundaries are returned verbatim.

    make_state(LONG_TEXT) (> MIN_CLAUSE_LENGTH) selects the NORMAL path so split_by_regex runs;
    the boundaries' own text length is irrelevant to the gate.
    """
    monkeypatch.setattr(clause_splitter_agent_module, "CLAUSE_SPLITTER_LLM_MAX_CLAUSES", 2)
    regex_boundaries = [make_boundary(1), make_boundary(2), make_boundary(3)]  # 3 > 2 → gate fires
    monkeypatch.setattr(
        clause_splitter_agent_module, "split_by_regex", lambda t: regex_boundaries
    )
    refine_spy = MagicMock()
    monkeypatch.setattr(clause_splitter_agent_module, "refine_with_llm", refine_spy)

    result = clause_splitter_agent(make_state(LONG_TEXT))

    refine_spy.assert_not_called()
    clauses = result["clauses"]
    assert list(clauses.keys()) == ["clause_001", "clause_002", "clause_003"]
    for cid, b in zip(["clause_001", "clause_002", "clause_003"], regex_boundaries):
        assert clauses[cid]["text"] == b.text
        assert clauses[cid]["position"] == b.position
        assert clauses[cid]["clause_type"] is None  # regex infers no type
