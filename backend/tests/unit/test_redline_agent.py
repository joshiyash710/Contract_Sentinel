"""
Unit tests for app.graph.nodes.redline_agent:
  - route_on_risk (7 tests)
  - redline_agent  (22 tests)
  - skip_redline   (2 tests)

draft_rewrite is mocked at the node module level.
Run: python -m pytest tests/unit/test_redline_agent.py -v
"""

import copy
from unittest.mock import MagicMock, patch, call

import pytest

import app.graph.nodes.redline_agent as redline_mod
from app.graph.nodes.redline_agent import (
    route_on_risk,
    redline_agent,
    skip_redline,
    is_redline_eligible,
)
from app.graph.state import RiskLevel, ValidationStatus
from app.config import OLLAMA_MODEL_NAME, OLLAMA_EMBED_MODEL_NAME

DRAFT_TARGET = "app.graph.nodes.redline_agent.draft_rewrite"


# ── Fixtures / helpers ─────────────────────────────────────────────────────────

def _eligible_record(
    clause_id="c1",
    text="The vendor bears unlimited liability.",
    risk_level=RiskLevel.HIGH,
    rationale="Uncapped exposure.",
    evidence=None,
    clause_type="liability",
    position=1,
) -> dict:
    return {
        "text": text,
        "position": position,
        "final_status": ValidationStatus.VALIDATED,
        "risk_level": risk_level,
        "risk_rationale": rationale,
        "evidence_snippets": evidence,
        "clause_type": clause_type,
        "section_number": "1.1",
    }


def _discarded_record(position=1) -> dict:
    return {
        "text": "This clause is standard.",
        "position": position,
        "final_status": ValidationStatus.DISCARDED,
        "risk_level": None,
        "risk_rationale": None,
        "evidence_snippets": None,
        "clause_type": "general",
        "section_number": "1.2",
    }


def _none_status_record(position=1) -> dict:
    return {
        "text": "Placeholder clause.",
        "position": position,
        "final_status": None,
        "risk_level": None,
        "risk_rationale": None,
        "evidence_snippets": None,
        "clause_type": None,
        "section_number": "0.0",
    }


def _make_state(clauses: dict, ingest_error=None, document_id="doc-1") -> dict:
    state = {"clauses": clauses, "document_id": document_id}
    if ingest_error is not None:
        state["ingest_error"] = ingest_error
    return state


# ── route_on_risk tests ────────────────────────────────────────────────────────


def test_route_redline_when_eligible_exists():
    """≥1 VALIDATED clause with in-threshold risk_level → 'redline' (AC-1)."""
    state = _make_state({"c1": _eligible_record()})
    assert route_on_risk(state) == "redline"


def test_route_skip_when_none_eligible():
    """All discarded → 'skip_redline' (AC-2)."""
    state = _make_state({"c1": _discarded_record()})
    assert route_on_risk(state) == "skip_redline"


def test_route_skip_empty_clauses():
    """clauses == {} → 'skip_redline' (AC-3)."""
    assert route_on_risk(_make_state({})) == "skip_redline"


def test_route_skip_on_ingest_error():
    """ingest_error set → 'skip_redline' regardless of clauses (AC-4)."""
    state = _make_state(
        {"c1": _eligible_record()},
        ingest_error={"error_type": "parse_failed", "message": "boom"},
    )
    assert route_on_risk(state) == "skip_redline"


def test_route_ignores_discarded_with_risk_level():
    """DISCARDED clause carrying a risk_level is not counted (AC-5)."""
    rec = _discarded_record()
    rec["risk_level"] = RiskLevel.HIGH  # defensive — should never happen in practice
    state = _make_state({"c1": rec})
    assert route_on_risk(state) == "skip_redline"


def test_route_threshold_from_config():
    """Monkeypatch threshold to exclude LOW → all-LOW doc routes 'skip_redline' (AC-6)."""
    rec = _eligible_record(risk_level=RiskLevel.LOW)
    state = _make_state({"c1": rec})
    with patch.object(redline_mod, "REDLINE_RISK_THRESHOLD", frozenset({RiskLevel.HIGH})):
        result = route_on_risk(state)
    assert result == "skip_redline"


def test_route_does_not_mutate_state():
    """route_on_risk is a pure function — state is unchanged after the call (AC-7)."""
    state = _make_state({"c1": _eligible_record()})
    state_copy = copy.deepcopy(state)
    route_on_risk(state)
    assert state == state_copy


# ── redline_agent tests ────────────────────────────────────────────────────────


def test_eligible_clauses_get_rewrite():
    """Every eligible clause gets a non-None, non-empty suggested_rewrite (AC-8)."""
    clauses = {
        "c1": _eligible_record(position=1),
        "c2": _eligible_record(clause_id="c2", position=2, risk_level=RiskLevel.MEDIUM),
    }
    with patch(DRAFT_TARGET, return_value="safer text") as mock_draft:
        result = redline_agent(_make_state(clauses))
    assert mock_draft.call_count == 2
    for cid in ("c1", "c2"):
        assert result["clauses"][cid]["suggested_rewrite"] == "safer text"


def test_below_threshold_untouched_no_llm():
    """VALIDATED-but-below-threshold clause: key absent, no draft_rewrite call (AC-9)."""
    rec = _eligible_record(risk_level=RiskLevel.LOW)
    with patch.object(
        redline_mod, "REDLINE_RISK_THRESHOLD", frozenset({RiskLevel.HIGH})
    ), patch(DRAFT_TARGET) as mock_draft:
        result = redline_agent(_make_state({"c1": rec}))
    mock_draft.assert_not_called()
    assert "c1" not in result["clauses"]


def test_discarded_and_none_untouched_no_llm():
    """DISCARDED / final_status=None clauses: key absent, no call (AC-10)."""
    clauses = {
        "d1": _discarded_record(position=1),
        "n1": _none_status_record(position=2),
    }
    with patch(DRAFT_TARGET) as mock_draft:
        result = redline_agent(_make_state(clauses))
    mock_draft.assert_not_called()
    assert "d1" not in result["clauses"]
    assert "n1" not in result["clauses"]


def test_one_llm_call_per_eligible_clause():
    """draft_rewrite call count == number of eligible clauses (AC-11)."""
    clauses = {
        "e1": _eligible_record(position=1),
        "e2": _eligible_record(clause_id="e2", position=2),
        "d1": _discarded_record(position=3),
    }
    with patch(DRAFT_TARGET, return_value="safer") as mock_draft:
        redline_agent(_make_state(clauses))
    assert mock_draft.call_count == 2


def test_uses_generative_not_embedding_model():
    """draft_rewrite invoked with OLLAMA_MODEL_NAME; never OLLAMA_EMBED_MODEL_NAME (AC-12)."""
    with patch(DRAFT_TARGET, return_value="safer") as mock_draft:
        redline_agent(_make_state({"c1": _eligible_record()}))
    assert mock_draft.called
    call_kwargs = mock_draft.call_args[1]
    assert call_kwargs["model_name"] == OLLAMA_MODEL_NAME
    assert call_kwargs["model_name"] != OLLAMA_EMBED_MODEL_NAME


def test_ingest_error_returns_empty():
    """ingest_error set → empty update; no draft_rewrite calls (AC-14)."""
    state = _make_state(
        {"c1": _eligible_record()},
        ingest_error={"error_type": "parse_failed", "message": "boom"},
    )
    with patch(DRAFT_TARGET) as mock_draft:
        result = redline_agent(state)
    mock_draft.assert_not_called()
    assert result["clauses"] == {}
    assert result["current_node"] == "redline"


def test_empty_clauses_returns_empty(caplog):
    """clauses == {} → empty update, warning, no calls (AC-15)."""
    with patch(DRAFT_TARGET) as mock_draft, caplog.at_level(
        "WARNING", logger="contractsentinel.redline"
    ):
        result = redline_agent(_make_state({}))
    mock_draft.assert_not_called()
    assert result["clauses"] == {}
    assert any("no clauses" in r.message.lower() for r in caplog.records)


def test_no_eligible_findings_zero_llm(caplog):
    """Non-empty but zero-eligible → empty clauses update, zero calls (AC-16)."""
    clauses = {"d1": _discarded_record()}
    with patch(DRAFT_TARGET) as mock_draft, caplog.at_level(
        "INFO", logger="contractsentinel.redline"
    ):
        result = redline_agent(_make_state(clauses))
    mock_draft.assert_not_called()
    assert result["clauses"] == {}
    # Aggregate log must still fire (spec §9)
    assert any("RedlineAgent completed" in r.message for r in caplog.records)


def test_partial_update_only_no_error_count():
    """Non-outage run → exactly {clauses, current_node, node_timings}; no error_count (AC-17)."""
    forbidden_keys = {
        "document_id", "extracted_text", "ingest_error",
        "report_path", "evidence_trail", "mcp_delivery_status",
        "retry_budgets", "error_count",
    }
    with patch(DRAFT_TARGET, return_value="safer"):
        result = redline_agent(_make_state({"c1": _eligible_record()}))
    assert set(result.keys()) == {"clauses", "current_node", "node_timings"}
    assert not (forbidden_keys & set(result.keys()))


def test_graceful_failure_emits_none(caplog):
    """draft_rewrite → None → clause gets explicit suggested_rewrite: None; no crash;
    others still processed; error_count NOT incremented for a single failure (AC-18)."""
    clauses = {
        "fail": _eligible_record(clause_id="fail", position=1),
        "ok": _eligible_record(clause_id="ok", position=2),
    }
    with patch(DRAFT_TARGET, side_effect=[None, "safer text"]) as mock_draft, \
         caplog.at_level("WARNING", logger="contractsentinel.redline"):
        result = redline_agent(_make_state(clauses))

    assert result["clauses"]["fail"]["suggested_rewrite"] is None
    assert result["clauses"]["ok"]["suggested_rewrite"] == "safer text"
    assert "error_count" not in result


def test_empty_output_emits_none():
    """draft_rewrite returning None (empty output path) → same fail-safe (AC-19)."""
    with patch(DRAFT_TARGET, return_value=None):
        result = redline_agent(_make_state({"c1": _eligible_record()}))
    assert result["clauses"]["c1"]["suggested_rewrite"] is None


def test_circuit_breaker_opens(caplog):
    """After THRESHOLD consecutive None results, remaining get None with no further calls (AC-20)."""
    threshold = 3
    n_clauses = 6
    clauses = {
        f"c{i}": _eligible_record(clause_id=f"c{i}", position=i)
        for i in range(1, n_clauses + 1)
    }
    with patch.object(
        redline_mod, "REDLINE_LLM_CIRCUIT_BREAKER_THRESHOLD", threshold
    ), patch(DRAFT_TARGET, return_value=None) as mock_draft, caplog.at_level(
        "WARNING", logger="contractsentinel.redline"
    ):
        result = redline_agent(_make_state(clauses))

    # draft_rewrite must be called at most threshold times (circuit opens, then bulk skip)
    assert mock_draft.call_count == threshold
    # Every eligible clause must have suggested_rewrite: None
    for cid in clauses:
        assert result["clauses"][cid]["suggested_rewrite"] is None
    # One "circuit opened" warning
    circuit_warnings = [r for r in caplog.records if "circuit opened" in r.message.lower()]
    assert len(circuit_warnings) == 1


def test_empty_text_findings_are_circuit_neutral():
    """Run with only empty-text eligible findings: None emitted for each but circuit
    never opens and return has no error_count (AC-20a)."""
    n = 10  # more than the default threshold of 5
    clauses = {
        f"c{i}": {**_eligible_record(clause_id=f"c{i}", position=i), "text": "   "}
        for i in range(1, n + 1)
    }
    with patch(DRAFT_TARGET) as mock_draft:
        result = redline_agent(_make_state(clauses))

    mock_draft.assert_not_called()
    for cid in clauses:
        assert result["clauses"][cid]["suggested_rewrite"] is None
    assert "error_count" not in result


def test_circuit_resets_on_success():
    """An interleaved real rewrite resets the counter; intermittent failures don't trip it."""
    threshold = 3
    # Pattern: fail, fail, success, fail, fail → counter resets at success, never reaches 3 in a row
    side_effects = [None, None, "safer", None, None]
    clauses = {
        f"c{i}": _eligible_record(clause_id=f"c{i}", position=i)
        for i in range(1, 6)
    }
    with patch.object(
        redline_mod, "REDLINE_LLM_CIRCUIT_BREAKER_THRESHOLD", threshold
    ), patch(DRAFT_TARGET, side_effect=side_effects):
        result = redline_agent(_make_state(clauses))

    assert "error_count" not in result
    assert result["clauses"]["c3"]["suggested_rewrite"] == "safer"


def test_circuit_open_emits_error_count_once():
    """Breaker opens → error_count: 1 exactly once; never-open run has no error_count (AC-23)."""
    threshold = 2
    clauses = {f"c{i}": _eligible_record(clause_id=f"c{i}", position=i) for i in range(1, 5)}

    # Run that opens the breaker
    with patch.object(
        redline_mod, "REDLINE_LLM_CIRCUIT_BREAKER_THRESHOLD", threshold
    ), patch(DRAFT_TARGET, return_value=None):
        open_result = redline_agent(_make_state(clauses))

    assert open_result.get("error_count") == 1

    # Run that never opens the breaker
    with patch(DRAFT_TARGET, return_value="safer"):
        clean_result = redline_agent(_make_state(clauses))

    assert "error_count" not in clean_result


def test_rewrite_truncated():
    """Rewrite longer than REDLINE_REWRITE_MAX_CHARS is truncated before write (AC-21)."""
    long_rewrite = "Z" * 5000
    with patch.object(redline_mod, "REDLINE_REWRITE_MAX_CHARS", 100), \
         patch(DRAFT_TARGET, return_value=long_rewrite):
        result = redline_agent(_make_state({"c1": _eligible_record()}))
    assert result["clauses"]["c1"]["suggested_rewrite"] == "Z" * 100


def test_current_node_pinned():
    """current_node == 'redline' and same key in node_timings (AC-24)."""
    with patch(DRAFT_TARGET, return_value="safer"):
        result = redline_agent(_make_state({"c1": _eligible_record()}))
    assert result["current_node"] == "redline"
    assert "redline" in result["node_timings"]


def test_rerun_overwrites_rewrite():
    """Pre-existing suggested_rewrite overwritten on success; a now-failing re-run emits None;
    reducer preserves non-rewrite fields (AC-25 / R3)."""
    rec = _eligible_record()
    rec["suggested_rewrite"] = "old rewrite"

    # Successful re-run: overwrites
    with patch(DRAFT_TARGET, return_value="new safer text"):
        result = redline_agent(_make_state({"c1": rec}))
    assert result["clauses"]["c1"]["suggested_rewrite"] == "new safer text"

    # Failing re-run: emits explicit None (clears stale value)
    with patch(DRAFT_TARGET, return_value=None):
        result2 = redline_agent(_make_state({"c1": rec}))
    assert result2["clauses"]["c1"]["suggested_rewrite"] is None
    # Only suggested_rewrite in the per-clause update
    assert set(result2["clauses"]["c1"].keys()) == {"suggested_rewrite"}


def test_empty_evidence_eligible_still_drafts():
    """Eligible clause with evidence_snippets=[]/None still drafts (one call) (AC-26)."""
    for evidence in [None, []]:
        rec = _eligible_record()
        rec["evidence_snippets"] = evidence
        with patch(DRAFT_TARGET, return_value="safer text") as mock_draft:
            result = redline_agent(_make_state({"c1": rec}))
        assert mock_draft.call_count == 1
        assert result["clauses"]["c1"]["suggested_rewrite"] == "safer text"


def test_empty_text_eligible_emits_none(caplog):
    """Whitespace-only text on an eligible finding → suggested_rewrite: None,
    no draft_rewrite call, circuit-neutral (Edge Case 6 + AC-20a)."""
    rec = _eligible_record()
    rec["text"] = "   "
    with patch(DRAFT_TARGET) as mock_draft, caplog.at_level(
        "WARNING", logger="contractsentinel.redline"
    ):
        result = redline_agent(_make_state({"c1": rec}))
    mock_draft.assert_not_called()
    assert result["clauses"]["c1"]["suggested_rewrite"] is None
    assert "error_count" not in result
    assert any("empty" in r.message.lower() for r in caplog.records)


def test_upstream_fields_untouched():
    """Node never sets/modifies risk_level, risk_rationale, or any upstream field (AC-27)."""
    rec = _eligible_record()
    rec["confidence_score"] = 0.9
    rec["path_taken"] = "kb"
    rec["validation_rationale"] = "well supported"

    with patch(DRAFT_TARGET, return_value="safer text"):
        result = redline_agent(_make_state({"c1": rec}))

    # The per-clause update must contain ONLY suggested_rewrite
    update_keys = set(result["clauses"]["c1"].keys())
    assert update_keys == {"suggested_rewrite"}


def test_noop_rewrite_counted(caplog):
    """Mock draft_rewrite to return the clause text verbatim → noop==1, rewritten==1 in
    the aggregate log (locks spec §9 metric 6 / §8a R5)."""
    clause_text = "The vendor bears unlimited liability."
    rec = _eligible_record(text=clause_text)

    with patch(DRAFT_TARGET, return_value=clause_text), caplog.at_level(
        "INFO", logger="contractsentinel.redline"
    ):
        redline_agent(_make_state({"c1": rec}))

    aggregate_records = [
        r for r in caplog.records if "RedlineAgent completed" in r.message
    ]
    assert len(aggregate_records) == 1
    rec_log = aggregate_records[0]
    assert rec_log.noop == 1
    assert rec_log.rewritten == 1


# ── skip_redline tests ─────────────────────────────────────────────────────────


def test_skip_passthrough_only():
    """Returns exactly {current_node, node_timings}; no clauses, no error_count (AC-28)."""
    state = _make_state({"c1": _eligible_record()})
    result = skip_redline(state)
    assert set(result.keys()) == {"current_node", "node_timings"}
    assert result["current_node"] == "skip_redline"
    assert "skip_redline" in result["node_timings"]
    assert isinstance(result["node_timings"]["skip_redline"], float)


def test_skip_no_clause_mutation():
    """After skip_redline, clauses dict is unchanged; return has no 'clauses' key (AC-29)."""
    state = _make_state({"c1": _eligible_record()})
    clauses_before = copy.deepcopy(state["clauses"])
    result = skip_redline(state)
    assert "clauses" not in result
    assert state["clauses"] == clauses_before
