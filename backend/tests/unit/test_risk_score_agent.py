"""
Unit tests for app.graph.nodes.risk_score_agent.

score_risk is patched at the node module level (app.graph.nodes.risk_score_agent.score_risk)
because the node does `from ...risk_scorer import score_risk`, binding the name locally.

Run: python -m pytest tests/unit/test_risk_score_agent.py -v
"""

from unittest.mock import patch

import pytest

from app.graph.state import RiskLevel, ValidationStatus, ClauseType

# ── Helpers ────────────────────────────────────────────────────────────────────


def _validated_clause(
    text="This clause assigns all IP rights to the vendor unconditionally.",
    position=1,
    evidence=None,
    clause_type=None,
):
    return {
        "text": text,
        "position": position,
        "final_status": ValidationStatus.VALIDATED,
        "evidence_snippets": evidence or [],
        "clause_type": clause_type,
    }


def _discarded_clause(text="Standard boilerplate.", position=2):
    return {
        "text": text,
        "position": position,
        "final_status": ValidationStatus.DISCARDED,
        "evidence_snippets": [],
        "clause_type": None,
    }


def _none_status_clause(text="Some clause.", position=3):
    return {
        "text": text,
        "position": position,
        "final_status": None,
        "evidence_snippets": [],
        "clause_type": None,
    }


def _make_state(clauses, ingest_error=None, document_id="doc-1"):
    return {
        "clauses": clauses,
        "ingest_error": ingest_error,
        "document_id": document_id,
    }


MOCK_TARGET = "app.graph.nodes.risk_score_agent.score_risk"


# ── Scoring correctness ────────────────────────────────────────────────────────


def test_validated_findings_scored():
    """Every VALIDATED clause ends with risk_level ∈ {LOW,MEDIUM,HIGH} and non-empty risk_rationale (AC-1)."""
    from app.graph.nodes.risk_score_agent import risk_score_agent

    clauses = {
        "c1": _validated_clause(position=1),
        "c2": _validated_clause(position=2),
    }
    state = _make_state(clauses)

    with patch(MOCK_TARGET, return_value=(RiskLevel.HIGH, "high risk reason")):
        result = risk_score_agent(state)

    for clause_id in ["c1", "c2"]:
        assert clause_id in result["clauses"]
        rec = result["clauses"][clause_id]
        assert rec["risk_level"] in {RiskLevel.LOW, RiskLevel.MEDIUM, RiskLevel.HIGH}
        assert rec["risk_rationale"]


def test_discarded_untouched_no_llm():
    """DISCARDED clause: risk_level/risk_rationale stay absent; no score_risk call (AC-2)."""
    from app.graph.nodes.risk_score_agent import risk_score_agent

    clauses = {"c1": _discarded_clause(position=1)}
    state = _make_state(clauses)

    with patch(MOCK_TARGET) as mock_score:
        result = risk_score_agent(state)

    mock_score.assert_not_called()
    assert "c1" not in result["clauses"]


def test_final_status_none_skipped():
    """final_status is None clause skipped, no call (AC-3)."""
    from app.graph.nodes.risk_score_agent import risk_score_agent

    clauses = {"c1": _none_status_clause(position=1)}
    state = _make_state(clauses)

    with patch(MOCK_TARGET) as mock_score:
        result = risk_score_agent(state)

    mock_score.assert_not_called()
    assert "c1" not in result["clauses"]


@pytest.mark.parametrize("level", [RiskLevel.HIGH, RiskLevel.MEDIUM, RiskLevel.LOW])
def test_level_echoes_judgment(level):
    """Mock returns HIGH/MEDIUM/LOW → clause gets that level (AC-4)."""
    from app.graph.nodes.risk_score_agent import risk_score_agent

    clauses = {"c1": _validated_clause(position=1)}
    state = _make_state(clauses)

    with patch(MOCK_TARGET, return_value=(level, "rationale")):
        result = risk_score_agent(state)

    assert result["clauses"]["c1"]["risk_level"] == level


def test_only_validated_incur_llm_calls():
    """score_risk call count == number of VALIDATED clauses (AC-5)."""
    from app.graph.nodes.risk_score_agent import risk_score_agent

    clauses = {
        "v1": _validated_clause(position=1),
        "d1": _discarded_clause(position=2),
        "v2": _validated_clause(position=3),
        "n1": _none_status_clause(position=4),
    }
    state = _make_state(clauses)

    with patch(MOCK_TARGET, return_value=(RiskLevel.MEDIUM, "r")) as mock_score:
        risk_score_agent(state)

    assert mock_score.call_count == 2


def test_uses_generative_not_embedding_model():
    """score_risk invoked with OLLAMA_MODEL_NAME; OLLAMA_EMBED_MODEL_NAME never referenced (AC-6)."""
    from app.graph.nodes.risk_score_agent import risk_score_agent, OLLAMA_MODEL_NAME
    from app.config import OLLAMA_EMBED_MODEL_NAME

    clauses = {"c1": _validated_clause(position=1)}
    state = _make_state(clauses)

    with patch(MOCK_TARGET, return_value=(RiskLevel.HIGH, "r")) as mock_score:
        risk_score_agent(state)

    call_kwargs = mock_score.call_args
    # model_name is the 5th positional argument (index 4) to score_risk
    model_used = call_kwargs[0][4]
    assert model_used == OLLAMA_MODEL_NAME
    assert model_used != OLLAMA_EMBED_MODEL_NAME


# ── Defensive guards ───────────────────────────────────────────────────────────


def test_ingest_error_returns_empty():
    """ingest_error set → empty update; no score_risk calls (AC-8)."""
    from app.graph.nodes.risk_score_agent import risk_score_agent

    clauses = {"c1": _validated_clause(position=1)}
    state = _make_state(
        clauses, ingest_error={"error_type": "parse_error", "detail": "failed"}
    )

    with patch(MOCK_TARGET) as mock_score:
        result = risk_score_agent(state)

    mock_score.assert_not_called()
    assert result["clauses"] == {}
    assert result["current_node"] == "risk_score"


def test_empty_clauses_returns_empty(caplog):
    """clauses == {} → empty update, warning, no calls (AC-9)."""
    from app.graph.nodes.risk_score_agent import risk_score_agent

    state = _make_state({})

    with patch(MOCK_TARGET) as mock_score:
        with caplog.at_level("WARNING"):
            result = risk_score_agent(state)

    mock_score.assert_not_called()
    assert result["clauses"] == {}


def test_no_validated_findings_zero_llm(caplog):
    """All-DISCARDED doc → empty clauses update, zero calls (AC-10)."""
    from app.graph.nodes.risk_score_agent import risk_score_agent

    clauses = {
        "d1": _discarded_clause(position=1),
        "d2": _discarded_clause(position=2),
    }
    state = _make_state(clauses)

    with patch(MOCK_TARGET) as mock_score:
        result = risk_score_agent(state)

    mock_score.assert_not_called()
    assert result["clauses"] == {}


# ── Partial update / return shape ──────────────────────────────────────────────


def test_partial_update_only_no_error_count():
    """Non-outage run → keys exactly {clauses, current_node, node_timings}; NO error_count (AC-11)."""
    from app.graph.nodes.risk_score_agent import risk_score_agent

    clauses = {"c1": _validated_clause(position=1)}
    state = _make_state(clauses)

    with patch(MOCK_TARGET, return_value=(RiskLevel.MEDIUM, "r")):
        result = risk_score_agent(state)

    assert set(result.keys()) == {"clauses", "current_node", "node_timings"}
    # Explicitly check forbidden keys
    for forbidden in [
        "error_count",
        "document_id",
        "extracted_text",
        "ingest_error",
        "report_path",
        "evidence_trail",
        "mcp_delivery_status",
        "retry_budgets",
    ]:
        assert forbidden not in result, f"Unexpected key {forbidden!r} in result"


# ── Fail-safe / graceful failure ──────────────────────────────────────────────


def test_graceful_llm_failure_failsafe_high():
    """score_risk → None → clause gets default HIGH, [auto] rationale, no crash (AC-12)."""
    from app.graph.nodes.risk_score_agent import risk_score_agent

    clauses = {
        "c1": _validated_clause(position=1),
        "c2": _validated_clause(position=2),
    }
    state = _make_state(clauses)

    # First call fails, second succeeds
    with patch(MOCK_TARGET, side_effect=[None, (RiskLevel.LOW, "low rationale")]):
        result = risk_score_agent(state)

    assert result["clauses"]["c1"]["risk_level"] == RiskLevel.HIGH
    assert "[auto]" in result["clauses"]["c1"]["risk_rationale"]
    assert result["clauses"]["c2"]["risk_level"] == RiskLevel.LOW
    # Single failure should NOT increment error_count
    assert "error_count" not in result


def test_malformed_output_failsafe():
    """score_risk returns None on unparseable output → same fail-safe path (AC-13)."""
    from app.graph.nodes.risk_score_agent import risk_score_agent

    clauses = {"c1": _validated_clause(position=1)}
    state = _make_state(clauses)

    with patch(MOCK_TARGET, return_value=None):
        result = risk_score_agent(state)

    assert result["clauses"]["c1"]["risk_level"] == RiskLevel.HIGH
    assert "[auto]" in result["clauses"]["c1"]["risk_rationale"]


# ── Circuit breaker ────────────────────────────────────────────────────────────


def test_circuit_breaker_opens():
    """After THRESHOLD consecutive None-returns, remaining findings get default HIGH
    with NO further score_risk calls; one 'circuit opened' warning (AC-14)."""
    import app.graph.nodes.risk_score_agent as mod
    from app.graph.nodes.risk_score_agent import risk_score_agent

    threshold = 3
    total_validated = threshold + 2  # 2 more after breaker opens

    clauses = {f"c{i}": _validated_clause(position=i) for i in range(total_validated)}
    state = _make_state(clauses)

    with patch.object(mod, "RISK_SCORE_LLM_CIRCUIT_BREAKER_THRESHOLD", threshold):
        with patch(MOCK_TARGET, return_value=None) as mock_score:
            result = risk_score_agent(state)

    # score_risk called exactly 'threshold' times (the ones that tripped the breaker)
    assert mock_score.call_count == threshold

    # All findings get HIGH (either from failure or from bulk default)
    for clause_id, rec in result["clauses"].items():
        assert rec["risk_level"] == RiskLevel.HIGH


def test_empty_text_findings_are_circuit_neutral():
    """A run of only empty-text validated findings: default applied to each, circuit
    never opens, no error_count (AC-14a)."""
    import app.graph.nodes.risk_score_agent as mod
    from app.graph.nodes.risk_score_agent import risk_score_agent

    threshold = 3
    count = threshold + 2  # more than threshold empty-text findings

    clauses = {
        f"c{i}": _validated_clause(text="   ", position=i)  # whitespace-only
        for i in range(count)
    }
    state = _make_state(clauses)

    with patch.object(mod, "RISK_SCORE_LLM_CIRCUIT_BREAKER_THRESHOLD", threshold):
        with patch(MOCK_TARGET) as mock_score:
            result = risk_score_agent(state)

    # score_risk never called (empty-text is circuit-neutral, no LLM call)
    mock_score.assert_not_called()
    # Every finding still gets the default level
    for clause_id, rec in result["clauses"].items():
        assert rec["risk_level"] == RiskLevel.HIGH
    # Circuit never opened → no error_count
    assert "error_count" not in result


def test_circuit_resets_on_success():
    """An interleaved real score resets the consecutive counter (intermittent single
    failures never trip the breaker)."""
    import app.graph.nodes.risk_score_agent as mod
    from app.graph.nodes.risk_score_agent import risk_score_agent

    threshold = 3
    # Pattern: fail, fail, succeed, fail, fail — counter resets on succeed, never trips
    clauses = {f"c{i}": _validated_clause(position=i) for i in range(5)}
    state = _make_state(clauses)

    side_effects = [None, None, (RiskLevel.LOW, "ok"), None, None]

    with patch.object(mod, "RISK_SCORE_LLM_CIRCUIT_BREAKER_THRESHOLD", threshold):
        with patch(MOCK_TARGET, side_effect=side_effects) as mock_score:
            result = risk_score_agent(state)

    # All 5 LLM calls were made (no early circuit trip)
    assert mock_score.call_count == 5
    # Circuit never tripped → no error_count
    assert "error_count" not in result


def test_circuit_open_emits_error_count_once():
    """Breaker opens → return includes error_count: 1 exactly once; never-open run has no error_count (AC-15)."""
    import app.graph.nodes.risk_score_agent as mod
    from app.graph.nodes.risk_score_agent import risk_score_agent

    threshold = 2

    # Run that trips the circuit
    clauses_trip = {
        f"c{i}": _validated_clause(position=i) for i in range(threshold + 1)
    }
    state_trip = _make_state(clauses_trip)

    with patch.object(mod, "RISK_SCORE_LLM_CIRCUIT_BREAKER_THRESHOLD", threshold):
        with patch(MOCK_TARGET, return_value=None):
            result_trip = risk_score_agent(state_trip)

    assert result_trip.get("error_count") == 1

    # Run that does NOT trip the circuit
    clauses_ok = {"c1": _validated_clause(position=1)}
    state_ok = _make_state(clauses_ok)

    with patch(MOCK_TARGET, return_value=(RiskLevel.MEDIUM, "r")):
        result_ok = risk_score_agent(state_ok)

    assert "error_count" not in result_ok


# ── State correctness ──────────────────────────────────────────────────────────


def test_current_node_pinned():
    """current_node == 'risk_score' and same key in node_timings (AC-16)."""
    from app.graph.nodes.risk_score_agent import risk_score_agent

    clauses = {"c1": _validated_clause(position=1)}
    state = _make_state(clauses)

    with patch(MOCK_TARGET, return_value=(RiskLevel.LOW, "r")):
        result = risk_score_agent(state)

    assert result["current_node"] == "risk_score"
    assert "risk_score" in result["node_timings"]


def test_rerun_overwrites_risk_fields():
    """Pre-existing risk_level/risk_rationale overwritten; reducer preserves text/verdicts (AC-17)."""
    from app.graph.nodes.risk_score_agent import risk_score_agent

    # Clause already has old risk fields from a previous run
    clause = _validated_clause(position=1)
    clause["risk_level"] = RiskLevel.LOW
    clause["risk_rationale"] = "old rationale"
    clause["final_status"] = ValidationStatus.VALIDATED
    clauses = {"c1": clause}
    state = _make_state(clauses)

    with patch(MOCK_TARGET, return_value=(RiskLevel.HIGH, "new rationale")):
        result = risk_score_agent(state)

    # Overwritten
    assert result["clauses"]["c1"]["risk_level"] == RiskLevel.HIGH
    assert result["clauses"]["c1"]["risk_rationale"] == "new rationale"
    # Node only writes risk fields; text is not in the partial update
    assert "text" not in result["clauses"]["c1"]


def test_rationale_truncated():
    """Rationale longer than RISK_RATIONALE_MAX_CHARS truncated before write (AC-18)."""
    import app.graph.nodes.risk_score_agent as mod
    from app.graph.nodes.risk_score_agent import risk_score_agent

    max_chars = 50
    long_rationale = "R" * 200

    clauses = {"c1": _validated_clause(position=1)}
    state = _make_state(clauses)

    with patch.object(mod, "RISK_RATIONALE_MAX_CHARS", max_chars):
        with patch(MOCK_TARGET, return_value=(RiskLevel.MEDIUM, long_rationale)):
            result = risk_score_agent(state)

    written_rationale = result["clauses"]["c1"]["risk_rationale"]
    assert len(written_rationale) <= max_chars


def test_empty_evidence_validated_still_scored():
    """VALIDATED finding with evidence_snippets [] / None still scored, no crash (AC-20)."""
    from app.graph.nodes.risk_score_agent import risk_score_agent

    for evidence in [[], None]:
        clause = _validated_clause(position=1, evidence=evidence)
        clauses = {"c1": clause}
        state = _make_state(clauses)

        with patch(MOCK_TARGET, return_value=(RiskLevel.MEDIUM, "r")) as mock_score:
            result = risk_score_agent(state)

        assert mock_score.call_count == 1
        assert result["clauses"]["c1"]["risk_level"] == RiskLevel.MEDIUM


def test_empty_text_validated_failsafe():
    """Whitespace-only text on a VALIDATED finding → default level, [auto] rationale,
    no score_risk call, circuit-neutral (Edge Case 6 + AC-14a)."""
    from app.graph.nodes.risk_score_agent import risk_score_agent

    clause = _validated_clause(text="   ", position=1)  # whitespace only
    clauses = {"c1": clause}
    state = _make_state(clauses)

    with patch(MOCK_TARGET) as mock_score:
        result = risk_score_agent(state)

    mock_score.assert_not_called()
    assert result["clauses"]["c1"]["risk_level"] == RiskLevel.HIGH
    assert "[auto]" in result["clauses"]["c1"]["risk_rationale"]
    assert "error_count" not in result


def test_suggested_rewrite_untouched():
    """Node never sets/modifies suggested_rewrite on any clause (AC-21)."""
    from app.graph.nodes.risk_score_agent import risk_score_agent

    clause = _validated_clause(position=1)
    clause["suggested_rewrite"] = "existing rewrite from somewhere"
    clauses = {"c1": clause}
    state = _make_state(clauses)

    with patch(MOCK_TARGET, return_value=(RiskLevel.HIGH, "r")):
        result = risk_score_agent(state)

    # The node's partial update must NOT contain suggested_rewrite
    assert "suggested_rewrite" not in result["clauses"]["c1"]


def test_risk_level_is_valid_enum():
    """Every assigned risk_level is a RiskLevel member (serializes to 'low'/'medium'/'high') (AC-22)."""
    from app.graph.nodes.risk_score_agent import risk_score_agent

    clauses = {f"c{i}": _validated_clause(position=i) for i in range(3)}
    state = _make_state(clauses)

    levels = [RiskLevel.LOW, RiskLevel.MEDIUM, RiskLevel.HIGH]
    with patch(MOCK_TARGET, side_effect=[(lvl, "r") for lvl in levels]):
        result = risk_score_agent(state)

    for rec in result["clauses"].values():
        assert isinstance(rec["risk_level"], RiskLevel)
        assert rec["risk_level"].value in {"low", "medium", "high"}


def test_clause_type_enum_or_str_context():
    """_clause_type_value normalizes ClauseType enum, str, and None to the string label passed to score_risk."""
    from app.graph.nodes.risk_score_agent import risk_score_agent

    # Test ClauseType enum → string
    clause_enum = _validated_clause(position=1, clause_type=ClauseType.LIABILITY)
    state1 = _make_state({"c1": clause_enum})

    with patch(MOCK_TARGET, return_value=(RiskLevel.HIGH, "r")) as mock_score:
        risk_score_agent(state1)

    call_args = mock_score.call_args[0]
    # 3rd positional arg to score_risk is clause_type (index 2)
    assert call_args[2] == "liability"

    # Test plain string → same string
    clause_str = _validated_clause(position=1, clause_type="liability")
    state2 = _make_state({"c1": clause_str})

    with patch(MOCK_TARGET, return_value=(RiskLevel.HIGH, "r")) as mock_score2:
        risk_score_agent(state2)

    call_args2 = mock_score2.call_args[0]
    assert call_args2[2] == "liability"

    # Test None → None
    clause_none = _validated_clause(position=1, clause_type=None)
    state3 = _make_state({"c1": clause_none})

    with patch(MOCK_TARGET, return_value=(RiskLevel.HIGH, "r")) as mock_score3:
        risk_score_agent(state3)

    call_args3 = mock_score3.call_args[0]
    assert call_args3[2] is None
