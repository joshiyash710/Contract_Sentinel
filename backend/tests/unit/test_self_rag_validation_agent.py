"""
Unit tests for app.graph.nodes.self_rag_validation_agent (Node 4).

All LLM calls are mocked at the node module level (i.e. on the bound names
check_relevance / check_isrel / check_issup that the node imported with
`from ...reflectors import ...`). Patching at reflectors.py would NOT affect
the node. No live Ollama required.
"""

import pytest
from unittest.mock import MagicMock, patch, call

import app.graph.nodes.self_rag_validation_agent as node_mod
from app.graph.state import ClauseType, ValidationStatus

# ── Helpers ────────────────────────────────────────────────────────────────────


def make_state(clauses, ingest_error=None, document_id="doc-1"):
    return {
        "document_id": document_id,
        "ingest_error": ingest_error,
        "clauses": clauses,
    }


def clause_record(
    text="This is a substantive contract clause with obligations.",
    position=1,
    evidence_snippets=None,
    clause_type=ClauseType.GENERAL,
    section_number=None,
):
    return {
        "text": text,
        "position": position,
        "evidence_snippets": evidence_snippets,
        "clause_type": clause_type,
        "section_number": section_number,
    }


def with_evidence(snippets=None):
    if snippets is None:
        snippets = [{"snippet_text": "Some evidence.", "source_reference": "kb/1"}]
    return snippets


def _call_node(clauses, ingest_error=None):
    state = make_state(clauses, ingest_error=ingest_error)
    return node_mod.self_rag_validation_agent(state)


# ── AC-1: per-clause coverage ─────────────────────────────────────────────────


def test_all_clauses_get_final_status():
    """Every clause ends with a non-None final_status."""
    clauses = {
        "c1": clause_record(position=1, evidence_snippets=with_evidence()),
        "c2": clause_record(position=2, evidence_snippets=with_evidence()),
        "c3": clause_record(position=3, evidence_snippets=with_evidence()),
    }
    with patch.object(node_mod, "check_relevance", return_value=True), patch.object(
        node_mod, "check_isrel", return_value=True
    ), patch.object(node_mod, "check_issup", return_value=True):
        result = _call_node(clauses)
    for cid in clauses:
        assert result["clauses"][cid]["final_status"] is not None


# ── AC-2: Relevance fail → discard (short-circuit) ───────────────────────────


def test_relevance_fail_discards_short_circuit():
    """Relevance False → relevance=False, isrel=None, issup=None, retry=None, DISCARDED.
    No ISREL or ISSUP call is made."""
    clauses = {"c1": clause_record(position=1, evidence_snippets=with_evidence())}
    mock_isrel = MagicMock()
    mock_issup = MagicMock()
    with patch.object(node_mod, "check_relevance", return_value=False), patch.object(
        node_mod, "check_isrel", mock_isrel
    ), patch.object(node_mod, "check_issup", mock_issup):
        result = _call_node(clauses)
    r = result["clauses"]["c1"]
    assert r["relevance_verdict"] is False
    assert r["isrel_verdict"] is None
    assert r["issup_verdict"] is None
    assert r["retry_count"] is None
    assert r["final_status"] == ValidationStatus.DISCARDED
    mock_isrel.assert_not_called()
    mock_issup.assert_not_called()


# ── AC-3: ISREL fail → discard (short-circuit) ───────────────────────────────


def test_isrel_fail_discards_short_circuit():
    """Relevance True, ISREL False → isrel=False, issup=None, retry=None, DISCARDED.
    No ISSUP call is made."""
    clauses = {"c1": clause_record(position=1, evidence_snippets=with_evidence())}
    mock_issup = MagicMock()
    with patch.object(node_mod, "check_relevance", return_value=True), patch.object(
        node_mod, "check_isrel", return_value=False
    ), patch.object(node_mod, "check_issup", mock_issup):
        result = _call_node(clauses)
    r = result["clauses"]["c1"]
    assert r["relevance_verdict"] is True
    assert r["isrel_verdict"] is False
    assert r["issup_verdict"] is None
    assert r["retry_count"] is None
    assert r["final_status"] == ValidationStatus.DISCARDED
    mock_issup.assert_not_called()


# ── AC-4: ISSUP pass first attempt → validated ───────────────────────────────


def test_issup_pass_first_attempt_validated():
    """ISSUP True first try → issup=True, retry_count=0, VALIDATED."""
    clauses = {"c1": clause_record(position=1, evidence_snippets=with_evidence())}
    with patch.object(node_mod, "check_relevance", return_value=True), patch.object(
        node_mod, "check_isrel", return_value=True
    ), patch.object(node_mod, "check_issup", return_value=True):
        result = _call_node(clauses)
    r = result["clauses"]["c1"]
    assert r["issup_verdict"] is True
    assert r["retry_count"] == 0
    assert r["final_status"] == ValidationStatus.VALIDATED


# ── AC-5: ISSUP retry then pass → validated ──────────────────────────────────


def test_issup_retry_then_pass_validated(monkeypatch):
    """ISSUP [False, True] → issup=True, retry_count=1, VALIDATED.

    Exercises the multi-attempt retry path, so it pins SELF_RAG_MAX_ATTEMPTS=3 independent of the
    feature-025 latency default (1). Assertions unchanged.
    """
    monkeypatch.setattr(node_mod, "SELF_RAG_MAX_ATTEMPTS", 3)
    clauses = {"c1": clause_record(position=1, evidence_snippets=with_evidence())}
    mock_issup = MagicMock(side_effect=[False, True])
    with patch.object(node_mod, "check_relevance", return_value=True), patch.object(
        node_mod, "check_isrel", return_value=True
    ), patch.object(node_mod, "check_issup", mock_issup):
        result = _call_node(clauses)
    r = result["clauses"]["c1"]
    assert r["issup_verdict"] is True
    assert r["retry_count"] == 1
    assert r["final_status"] == ValidationStatus.VALIDATED


# ── AC-6: ISSUP exhaustion → discard ─────────────────────────────────────────


def test_issup_exhaustion_discarded(monkeypatch):
    """ISSUP False every attempt → issup=False, retry_count=MAX-1, DISCARDED.

    Pins SELF_RAG_MAX_ATTEMPTS=3 so it keeps exercising MULTI-attempt exhaustion (retry_count=2)
    independent of the feature-025 latency default (1); the single-attempt case is covered by
    test_issup_single_attempt_no_retry below.
    """
    monkeypatch.setattr(node_mod, "SELF_RAG_MAX_ATTEMPTS", 3)
    clauses = {"c1": clause_record(position=1, evidence_snippets=with_evidence())}
    max_attempts = node_mod.SELF_RAG_MAX_ATTEMPTS
    with patch.object(node_mod, "check_relevance", return_value=True), patch.object(
        node_mod, "check_isrel", return_value=True
    ), patch.object(node_mod, "check_issup", return_value=False):
        result = _call_node(clauses)
    r = result["clauses"]["c1"]
    assert r["issup_verdict"] is False
    assert r["retry_count"] == max_attempts - 1
    assert r["final_status"] == ValidationStatus.DISCARDED


def test_issup_single_attempt_no_retry(monkeypatch):
    """Feature 025 lever B: SELF_RAG_MAX_ATTEMPTS=1 → ISSUP judged ONCE, no retries.

    A single False verdict discards immediately (retry_count=0), with check_issup called exactly once.
    """
    monkeypatch.setattr(node_mod, "SELF_RAG_MAX_ATTEMPTS", 1)
    clauses = {"c1": clause_record(position=1, evidence_snippets=with_evidence())}
    mock_issup = MagicMock(return_value=False)
    with patch.object(node_mod, "check_relevance", return_value=True), patch.object(
        node_mod, "check_isrel", return_value=True
    ), patch.object(node_mod, "check_issup", mock_issup):
        result = _call_node(clauses)
    r = result["clauses"]["c1"]
    assert mock_issup.call_count == 1
    assert r["issup_verdict"] is False
    assert r["retry_count"] == 0
    assert r["final_status"] == ValidationStatus.DISCARDED


# ── AC-7: attempt cap enforced ────────────────────────────────────────────────


def test_attempt_cap_enforced(monkeypatch):
    """No more than SELF_RAG_MAX_ATTEMPTS ISSUP calls per clause."""
    monkeypatch.setattr(node_mod, "SELF_RAG_MAX_ATTEMPTS", 2)
    clauses = {"c1": clause_record(position=1, evidence_snippets=with_evidence())}
    mock_issup = MagicMock(return_value=False)
    with patch.object(node_mod, "check_relevance", return_value=True), patch.object(
        node_mod, "check_isrel", return_value=True
    ), patch.object(node_mod, "check_issup", mock_issup):
        _call_node(clauses)
    assert mock_issup.call_count == 2


# ── AC-8: only ISSUP retries ─────────────────────────────────────────────────


def test_only_issup_retries():
    """Exactly one Relevance call and one ISREL call — never retried."""
    clauses = {"c1": clause_record(position=1, evidence_snippets=with_evidence())}
    mock_rel = MagicMock(return_value=True)
    mock_isrel = MagicMock(return_value=True)
    mock_issup = MagicMock(return_value=True)
    with patch.object(node_mod, "check_relevance", mock_rel), patch.object(
        node_mod, "check_isrel", mock_isrel
    ), patch.object(node_mod, "check_issup", mock_issup):
        _call_node(clauses)
    assert mock_rel.call_count == 1
    assert mock_isrel.call_count == 1


# ── AC-9: generative model, not embedding model ───────────────────────────────


def test_uses_generative_not_embedding_model():
    """Node passes OLLAMA_MODEL_NAME to reflectors; OLLAMA_EMBED_MODEL_NAME never used."""
    from app.config import OLLAMA_MODEL_NAME, OLLAMA_EMBED_MODEL_NAME

    assert OLLAMA_MODEL_NAME != OLLAMA_EMBED_MODEL_NAME
    clauses = {"c1": clause_record(position=1, evidence_snippets=with_evidence())}
    all_args = []

    def capture_call(*args, **kwargs):
        all_args.append(args)
        return True

    with patch.object(
        node_mod, "check_relevance", side_effect=capture_call
    ), patch.object(node_mod, "check_isrel", side_effect=capture_call), patch.object(
        node_mod, "check_issup", side_effect=capture_call
    ):
        _call_node(clauses)
    # Each call must include OLLAMA_MODEL_NAME somewhere in positional args
    # and must never include OLLAMA_EMBED_MODEL_NAME
    for args in all_args:
        assert (
            OLLAMA_MODEL_NAME in args
        ), f"OLLAMA_MODEL_NAME not in call args: {args!r}"
        assert (
            OLLAMA_EMBED_MODEL_NAME not in args
        ), f"OLLAMA_EMBED_MODEL_NAME found in call: {args!r}"


# ── AC-11: ingest_error → empty return ───────────────────────────────────────


def test_ingest_error_returns_empty():
    """ingest_error set → empty clauses update, no reflector calls."""
    mock_rel = MagicMock()
    mock_isrel = MagicMock()
    mock_issup = MagicMock()
    with patch.object(node_mod, "check_relevance", mock_rel), patch.object(
        node_mod, "check_isrel", mock_isrel
    ), patch.object(node_mod, "check_issup", mock_issup):
        result = _call_node(
            {"c1": clause_record(position=1, evidence_snippets=with_evidence())},
            ingest_error={"error": "parse failed"},
        )
    assert result["clauses"] == {}
    mock_rel.assert_not_called()
    mock_isrel.assert_not_called()
    mock_issup.assert_not_called()


# ── AC-12: empty clauses input ───────────────────────────────────────────────


def test_empty_clauses_returns_empty(caplog):
    """clauses == {} → empty update, warning logged, no reflector calls."""
    mock_rel = MagicMock()
    with caplog.at_level("WARNING"):
        with patch.object(node_mod, "check_relevance", mock_rel):
            result = _call_node({})
    assert result["clauses"] == {}
    mock_rel.assert_not_called()
    assert any(
        "empty" in r.message.lower() or "no clauses" in r.message.lower()
        for r in caplog.records
    )


# ── AC-13: partial update only (no error_count on clean run) ─────────────────


def test_partial_update_only_no_error_count():
    """Non-outage run → keys exactly {clauses, current_node, node_timings}; no error_count."""
    clauses = {"c1": clause_record(position=1, evidence_snippets=with_evidence())}
    with patch.object(node_mod, "check_relevance", return_value=True), patch.object(
        node_mod, "check_isrel", return_value=True
    ), patch.object(node_mod, "check_issup", return_value=True):
        result = _call_node(clauses)
    allowed = {"clauses", "current_node", "node_timings"}
    forbidden = {
        "document_id",
        "extracted_text",
        "ingest_error",
        "report_path",
        "evidence_trail",
        "mcp_delivery_status",
        "retry_budgets",
        "error_count",
    }
    assert set(result.keys()) == allowed
    for k in forbidden:
        assert k not in result, f"Forbidden key {k!r} present in result"


# ── AC-14: graceful LLM failure (fail-open) ───────────────────────────────────


def test_graceful_llm_failure_fail_open():
    """Reflector returns None → clause VALIDATED (fail-open), affected verdict None,
    no crash, other clauses still process. Single failure does NOT increment error_count.
    """
    clauses = {
        "c1": clause_record(position=1, evidence_snippets=with_evidence()),
        "c2": clause_record(position=2, evidence_snippets=with_evidence()),
    }
    # c1: Relevance returns None (LLM failure) → fail-open
    # c2: all pass normally
    call_count = [0]

    def mock_rel(*args, **kwargs):
        call_count[0] += 1
        if call_count[0] == 1:
            return None  # fail for c1
        return True  # pass for c2

    with patch.object(node_mod, "check_relevance", side_effect=mock_rel), patch.object(
        node_mod, "check_isrel", return_value=True
    ), patch.object(node_mod, "check_issup", return_value=True):
        result = _call_node(clauses)

    r1 = result["clauses"]["c1"]
    assert r1["final_status"] == ValidationStatus.VALIDATED  # fail-open
    assert r1["relevance_verdict"] is None
    r2 = result["clauses"]["c2"]
    assert r2["final_status"] == ValidationStatus.VALIDATED
    assert "error_count" not in result  # single failure does NOT increment


# ── AC-15: circuit breaker opens ─────────────────────────────────────────────


def test_circuit_breaker_opens(monkeypatch, caplog):
    """After THRESHOLD consecutive failures, remaining clauses take fail-open;
    no further reflector calls; one 'circuit opened' warning logged."""
    monkeypatch.setattr(node_mod, "SELF_RAG_LLM_CIRCUIT_BREAKER_THRESHOLD", 3)
    # 5 clauses: first 3 will trigger the breaker; remaining 2 should be fail-opened
    clauses = {
        f"c{i}": clause_record(position=i, evidence_snippets=with_evidence())
        for i in range(1, 6)
    }
    mock_rel = MagicMock(return_value=None)  # all return None → consecutive failures
    with caplog.at_level("WARNING"):
        with patch.object(node_mod, "check_relevance", mock_rel), patch.object(
            node_mod, "check_isrel", return_value=True
        ), patch.object(node_mod, "check_issup", return_value=True):
            result = _call_node(clauses)

    # After 3 consecutive failures the breaker opens; reflector call count stops at 3
    assert mock_rel.call_count == 3
    # All 5 clauses should be fail-open VALIDATED
    for cid in clauses:
        assert result["clauses"][cid]["final_status"] == ValidationStatus.VALIDATED
    # Exactly one "circuit opened" warning
    circuit_warnings = [r for r in caplog.records if "circuit" in r.message.lower()]
    assert len(circuit_warnings) >= 1


def test_circuit_resets_on_success(monkeypatch):
    """An interleaved real verdict resets the consecutive counter (not tripped by intermittent failures)."""
    monkeypatch.setattr(node_mod, "SELF_RAG_LLM_CIRCUIT_BREAKER_THRESHOLD", 3)
    # None, True, None, True — never 3 consecutive
    clauses = {
        f"c{i}": clause_record(position=i, evidence_snippets=with_evidence())
        for i in range(1, 5)
    }
    # relevance alternates None/True
    side_effects = [None, True, None, True]
    with patch.object(
        node_mod, "check_relevance", side_effect=side_effects
    ), patch.object(node_mod, "check_isrel", return_value=True), patch.object(
        node_mod, "check_issup", return_value=True
    ):
        result = _call_node(clauses)
    # Breaker should NOT have opened (never 3 consecutive)
    assert "error_count" not in result


# ── AC-16: empty evidence, high-risk type ─────────────────────────────────────


def test_empty_evidence_high_risk_validates_on_text():
    """Empty evidence + recall-floor type (LIABILITY) + Relevance True → VALIDATED.

    SUPERSEDED BY 027: pre-027 this ran a text-only ISSUP loop in Branch A. The recall
    floor (spec 027 §2.2) now short-circuits an on-topic floor type to VALIDATED without
    ISSUP — so issup_verdict is None (not True) and check_issup is not called. The clause
    is still VALIDATED (the safety-relevant outcome); isrel_verdict stays None (AC-16a)."""
    mock_issup = MagicMock(return_value=True)
    clauses = {
        "c1": clause_record(
            position=1, evidence_snippets=[], clause_type=ClauseType.LIABILITY
        )
    }
    with patch.object(node_mod, "check_relevance", return_value=True), patch.object(
        node_mod, "check_isrel", MagicMock()
    ), patch.object(node_mod, "check_issup", mock_issup):
        result = _call_node(clauses)
    r = result["clauses"]["c1"]
    assert r["relevance_verdict"] is True
    assert r["isrel_verdict"] is None  # not-assessable (absent evidence ≠ off-topic)
    assert r["issup_verdict"] is None  # recall floor skips ISSUP
    assert r["final_status"] == ValidationStatus.VALIDATED
    mock_issup.assert_not_called()


def test_empty_evidence_high_risk_relevance_false_discards():
    """Empty evidence + high-risk type + Relevance False → DISCARDED; no ISSUP call."""
    clauses = {
        "c1": clause_record(
            position=1, evidence_snippets=None, clause_type=ClauseType.TERMINATION
        )
    }
    mock_issup = MagicMock()
    with patch.object(node_mod, "check_relevance", return_value=False), patch.object(
        node_mod, "check_isrel", MagicMock()
    ), patch.object(node_mod, "check_issup", mock_issup):
        result = _call_node(clauses)
    r = result["clauses"]["c1"]
    assert r["relevance_verdict"] is False
    assert r["isrel_verdict"] is None
    assert r["issup_verdict"] is None
    assert r["retry_count"] is None
    assert r["final_status"] == ValidationStatus.DISCARDED
    mock_issup.assert_not_called()


def test_empty_evidence_high_risk_issup_false_validates_under_floor():
    """Empty evidence + recall-floor type (INTELLECTUAL_PROPERTY) + Relevance True → VALIDATED.

    SUPERSEDED BY 027 (renamed from ..._issup_false_discards): pre-027 an empty-evidence
    high-risk clause with an ISSUP-False text judgment was DISCARDED. The recall floor
    (spec 027 §2.2, AC-5) now rescues it — the clause VALIDATEs without ISSUP being relied
    on, exactly the miss the feature targets. Reversibility of the pre-027 discard is
    covered by test_recall_floor_empty_set_restores_old_behavior (empty floor)."""
    mock_issup = MagicMock(return_value=False)
    clauses = {
        "c1": clause_record(
            position=1,
            evidence_snippets=[],
            clause_type=ClauseType.INTELLECTUAL_PROPERTY,
        )
    }
    with patch.object(node_mod, "check_relevance", return_value=True), patch.object(
        node_mod, "check_isrel", MagicMock()
    ), patch.object(node_mod, "check_issup", mock_issup):
        result = _call_node(clauses)
    r = result["clauses"]["c1"]
    assert r["isrel_verdict"] is None
    assert r["issup_verdict"] is None  # recall floor: ISSUP not relied on
    assert r["final_status"] == ValidationStatus.VALIDATED
    mock_issup.assert_not_called()


def test_empty_evidence_non_high_risk_zero_llm_discard():
    """Empty evidence + non-high-risk type → all verdicts None, DISCARDED, zero reflector calls."""
    clauses = {
        "c1": clause_record(
            position=1, evidence_snippets=[], clause_type=ClauseType.GENERAL
        )
    }
    mock_rel = MagicMock()
    mock_isrel = MagicMock()
    mock_issup = MagicMock()
    with patch.object(node_mod, "check_relevance", mock_rel), patch.object(
        node_mod, "check_isrel", mock_isrel
    ), patch.object(node_mod, "check_issup", mock_issup):
        result = _call_node(clauses)
    r = result["clauses"]["c1"]
    assert r["relevance_verdict"] is None
    assert r["isrel_verdict"] is None
    assert r["issup_verdict"] is None
    assert r["retry_count"] is None
    assert r["final_status"] == ValidationStatus.DISCARDED
    mock_rel.assert_not_called()
    mock_isrel.assert_not_called()
    mock_issup.assert_not_called()


def test_empty_evidence_clause_type_none_discards():
    """Empty evidence + clause_type=None → zero-LLM DISCARD."""
    clauses = {
        "c1": clause_record(position=1, evidence_snippets=None, clause_type=None)
    }
    mock_rel = MagicMock()
    with patch.object(node_mod, "check_relevance", mock_rel), patch.object(
        node_mod, "check_isrel", MagicMock()
    ), patch.object(node_mod, "check_issup", MagicMock()):
        result = _call_node(clauses)
    r = result["clauses"]["c1"]
    assert r["final_status"] == ValidationStatus.DISCARDED
    mock_rel.assert_not_called()


# ── AC-16a: no isrel_verdict=False with VALIDATED ────────────────────────────


def test_no_isrel_false_with_validated():
    """Invariant: no clause ends isrel_verdict=False + VALIDATED."""
    # Branch A (high-risk empty evidence) → isrel=None + VALIDATED
    # Branch C (evidence present, ISREL passes) → isrel=True + VALIDATED
    clauses = {
        "c1": clause_record(
            position=1, evidence_snippets=[], clause_type=ClauseType.LIABILITY
        ),
        "c2": clause_record(
            position=2,
            evidence_snippets=with_evidence(),
            clause_type=ClauseType.GENERAL,
        ),
    }
    with patch.object(node_mod, "check_relevance", return_value=True), patch.object(
        node_mod, "check_isrel", return_value=True
    ), patch.object(node_mod, "check_issup", return_value=True):
        result = _call_node(clauses)
    for cid, r in result["clauses"].items():
        if r["final_status"] == ValidationStatus.VALIDATED:
            assert (
                r["isrel_verdict"] is not False
            ), f"Clause {cid} is VALIDATED but isrel_verdict=False (contradictory)"


# ── AC-17: current_node pinned ────────────────────────────────────────────────


def test_current_node_pinned():
    """current_node == 'self_rag_validation' and same key in node_timings."""
    with patch.object(node_mod, "check_relevance", return_value=True), patch.object(
        node_mod, "check_isrel", return_value=True
    ), patch.object(node_mod, "check_issup", return_value=True):
        result = _call_node(
            {"c1": clause_record(position=1, evidence_snippets=with_evidence())}
        )
    assert result["current_node"] == "self_rag_validation"
    assert "self_rag_validation" in result["node_timings"]


# ── AC-18: re-run overwrites verdicts ────────────────────────────────────────


def test_rerun_overwrites_verdicts():
    """Pre-existing verdict fields are overwritten; non-verdict fields preserved."""
    clauses = {
        "c1": {
            "text": "Some clause.",
            "position": 1,
            "evidence_snippets": with_evidence(),
            "clause_type": ClauseType.GENERAL,
            "section_number": "1.1",
            # Pre-existing stale verdicts:
            "relevance_verdict": False,
            "isrel_verdict": False,
            "issup_verdict": False,
            "retry_count": 2,
            "final_status": ValidationStatus.DISCARDED,
        }
    }
    with patch.object(node_mod, "check_relevance", return_value=True), patch.object(
        node_mod, "check_isrel", return_value=True
    ), patch.object(node_mod, "check_issup", return_value=True):
        result = _call_node(clauses)
    r = result["clauses"]["c1"]
    # Verdict fields should be updated
    assert r["relevance_verdict"] is True
    assert r["issup_verdict"] is True
    assert r["final_status"] == ValidationStatus.VALIDATED


# ── AC-19: discarded clause still present ─────────────────────────────────────


def test_discarded_clause_still_present():
    """DISCARDED clause remains in the update; no clause IDs removed."""
    clauses = {
        "c1": clause_record(position=1, evidence_snippets=with_evidence()),
        "c2": clause_record(position=2, evidence_snippets=with_evidence()),
    }
    call_n = [0]

    def rel_side(*args, **kwargs):
        call_n[0] += 1
        return True if call_n[0] == 1 else False  # c1 passes, c2 discarded at relevance

    with patch.object(node_mod, "check_relevance", side_effect=rel_side), patch.object(
        node_mod, "check_isrel", return_value=True
    ), patch.object(node_mod, "check_issup", return_value=True):
        result = _call_node(clauses)
    assert "c1" in result["clauses"]
    assert "c2" in result["clauses"]
    assert result["clauses"]["c2"]["final_status"] == ValidationStatus.DISCARDED


# ── AC-20: circuit-open health signal ────────────────────────────────────────


def test_circuit_open_emits_error_count_once(monkeypatch):
    """Breaker opens → error_count=1 in result; never-open run has no error_count key."""
    monkeypatch.setattr(node_mod, "SELF_RAG_LLM_CIRCUIT_BREAKER_THRESHOLD", 2)
    # Run 1: force enough consecutive failures to open the breaker
    clauses_trip = {
        f"c{i}": clause_record(position=i, evidence_snippets=with_evidence())
        for i in range(1, 4)
    }
    with patch.object(node_mod, "check_relevance", return_value=None), patch.object(
        node_mod, "check_isrel", return_value=True
    ), patch.object(node_mod, "check_issup", return_value=True):
        result_tripped = _call_node(clauses_trip)
    assert result_tripped.get("error_count") == 1

    # Run 2: clean run — breaker never opens
    clauses_clean = {"c1": clause_record(position=1, evidence_snippets=with_evidence())}
    with patch.object(node_mod, "check_relevance", return_value=True), patch.object(
        node_mod, "check_isrel", return_value=True
    ), patch.object(node_mod, "check_issup", return_value=True):
        result_clean = _call_node(clauses_clean)
    assert "error_count" not in result_clean


# ── Edge Case 6: empty/whitespace clause text ─────────────────────────────────


def test_empty_clause_text_skipped():
    """Whitespace-only text → all verdicts None, DISCARDED, no reflector call."""
    clauses = {
        "c1": clause_record(text="   ", position=1, evidence_snippets=with_evidence())
    }
    mock_rel = MagicMock()
    with patch.object(node_mod, "check_relevance", mock_rel), patch.object(
        node_mod, "check_isrel", MagicMock()
    ), patch.object(node_mod, "check_issup", MagicMock()):
        result = _call_node(clauses)
    r = result["clauses"]["c1"]
    assert r["relevance_verdict"] is None
    assert r["isrel_verdict"] is None
    assert r["issup_verdict"] is None
    assert r["retry_count"] is None
    assert r["final_status"] == ValidationStatus.DISCARDED
    mock_rel.assert_not_called()


# ── clause_type enum or str gate ────────────────────────────────────────────


def test_clause_type_enum_or_str_gate():
    """High-risk gate matches both ClauseType enum and its .value string."""
    mock_rel = MagicMock(return_value=False)
    # As enum
    clauses_enum = {
        "c1": clause_record(
            position=1, evidence_snippets=[], clause_type=ClauseType.LIABILITY
        )
    }
    with patch.object(node_mod, "check_relevance", mock_rel), patch.object(
        node_mod, "check_isrel", MagicMock()
    ), patch.object(node_mod, "check_issup", MagicMock()):
        _call_node(clauses_enum)
    enum_call_count = mock_rel.call_count
    assert enum_call_count == 1  # rescue path entered for enum type

    mock_rel.reset_mock()
    # As string
    clauses_str = {
        "c1": clause_record(position=1, evidence_snippets=[], clause_type="liability")
    }
    with patch.object(node_mod, "check_relevance", mock_rel), patch.object(
        node_mod, "check_isrel", MagicMock()
    ), patch.object(node_mod, "check_issup", MagicMock()):
        _call_node(clauses_str)
    assert mock_rel.call_count == 1  # rescue path entered for string type too


# ── Zero-LLM branches exempt from fail-open after circuit trips ──────────────


def test_zero_llm_branches_exempt_from_fail_open_after_trip(monkeypatch):
    """After circuit opens, Branch-B (non-high-risk empty-evidence) and empty-text
    clauses still reach DISCARDED, not fail-open VALIDATED."""
    monkeypatch.setattr(node_mod, "SELF_RAG_LLM_CIRCUIT_BREAKER_THRESHOLD", 1)
    # c1: evidence present, returns None → opens circuit (1 consecutive failure)
    # c2: Branch B (non-high-risk, empty evidence) → must stay DISCARDED even after trip
    # c3: empty text → must stay DISCARDED even after trip
    clauses = {
        "c1": clause_record(
            position=1,
            evidence_snippets=with_evidence(),
            clause_type=ClauseType.GENERAL,
        ),
        "c2": clause_record(
            position=2, evidence_snippets=[], clause_type=ClauseType.GENERAL
        ),
        "c3": clause_record(
            text="  ",
            position=3,
            evidence_snippets=with_evidence(),
            clause_type=ClauseType.GENERAL,
        ),
    }
    with patch.object(node_mod, "check_relevance", return_value=None), patch.object(
        node_mod, "check_isrel", return_value=True
    ), patch.object(node_mod, "check_issup", return_value=True):
        result = _call_node(clauses)

    # c1 trips the breaker → fail-open VALIDATED
    assert result["clauses"]["c1"]["final_status"] == ValidationStatus.VALIDATED
    # c2 (Branch B, zero-LLM) → still DISCARDED
    assert result["clauses"]["c2"]["final_status"] == ValidationStatus.DISCARDED
    # c3 (empty text, zero-LLM) → still DISCARDED
    assert result["clauses"]["c3"]["final_status"] == ValidationStatus.DISCARDED


# ══════════════════════════════════════════════════════════════════════════════
# Feature 027 — Self-RAG recall floor for high-risk clause types
#   Once a recall-floor clause_type passes the light relevance gate, it is
#   VALIDATED even if ISSUP/ISREL would discard it, or if it had no evidence.
# ══════════════════════════════════════════════════════════════════════════════


def _floor_verdict(shape):
    """Assert the record shape of a recall-floor VALIDATE (spec §2.3):
    relevance True, isrel/issup/retry all None, final_status VALIDATED."""
    assert shape["relevance_verdict"] is True
    assert shape["isrel_verdict"] is None  # AC-16a: never False + VALIDATED
    assert shape["issup_verdict"] is None
    assert shape["retry_count"] is None
    assert shape["final_status"] == ValidationStatus.VALIDATED


def test_recall_floor_evidence_issup_false_validates():
    """AC-1: floor type + evidence + relevance True + ISSUP-would-be-False → VALIDATED.
    A non-floor type in the same scenario → DISCARDED (today's behavior)."""
    clauses = {
        "floor": clause_record(
            position=1,
            evidence_snippets=with_evidence(),
            clause_type=ClauseType.LIABILITY,
        ),
        "nonfloor": clause_record(
            position=2,
            evidence_snippets=with_evidence(),
            clause_type=ClauseType.GENERAL,
        ),
    }
    with patch.object(node_mod, "check_relevance", return_value=True), patch.object(
        node_mod, "check_isrel", return_value=True
    ), patch.object(node_mod, "check_issup", return_value=False):
        result = _call_node(clauses)
    _floor_verdict(result["clauses"]["floor"])
    # non-floor: ISSUP False → DISCARDED, unchanged
    assert result["clauses"]["nonfloor"]["final_status"] == ValidationStatus.DISCARDED
    assert result["clauses"]["nonfloor"]["issup_verdict"] is False


def test_recall_floor_evidence_isrel_false_validates():
    """AC-2: floor type + evidence + relevance True + ISREL-would-be-False → VALIDATED.
    Non-floor type → DISCARDED."""
    clauses = {
        "floor": clause_record(
            position=1,
            evidence_snippets=with_evidence(),
            clause_type=ClauseType.TERMINATION,
        ),
        "nonfloor": clause_record(
            position=2,
            evidence_snippets=with_evidence(),
            clause_type=ClauseType.GENERAL,
        ),
    }
    with patch.object(node_mod, "check_relevance", return_value=True), patch.object(
        node_mod, "check_isrel", return_value=False
    ), patch.object(node_mod, "check_issup", return_value=True):
        result = _call_node(clauses)
    _floor_verdict(result["clauses"]["floor"])
    r = result["clauses"]["nonfloor"]
    assert r["isrel_verdict"] is False
    assert r["final_status"] == ValidationStatus.DISCARDED


def test_recall_floor_branch_c_skips_isrel_and_issup():
    """AC-4c: for a floor Branch-C clause, once relevance passes, neither ISREL nor
    ISSUP is called (side benefit: skips 1-2 LLM calls)."""
    mock_isrel = MagicMock(return_value=False)
    mock_issup = MagicMock(return_value=False)
    clauses = {
        "c1": clause_record(
            position=1,
            evidence_snippets=with_evidence(),
            clause_type=ClauseType.LIABILITY,
        )
    }
    with patch.object(node_mod, "check_relevance", return_value=True), patch.object(
        node_mod, "check_isrel", mock_isrel
    ), patch.object(node_mod, "check_issup", mock_issup):
        result = _call_node(clauses)
    _floor_verdict(result["clauses"]["c1"])
    mock_isrel.assert_not_called()
    mock_issup.assert_not_called()


def test_recall_floor_empty_evidence_validates():
    """AC-3: floor type + empty evidence + relevance True → VALIDATED via Branch A
    rescue WITHOUT entering the ISSUP loop (issup not called)."""
    mock_issup = MagicMock(return_value=False)
    clauses = {
        "c1": clause_record(
            position=1, evidence_snippets=[], clause_type=ClauseType.LIABILITY
        )
    }
    with patch.object(node_mod, "check_relevance", return_value=True), patch.object(
        node_mod, "check_isrel", MagicMock()
    ), patch.object(node_mod, "check_issup", mock_issup):
        result = _call_node(clauses)
    _floor_verdict(result["clauses"]["c1"])
    mock_issup.assert_not_called()


def test_recall_floor_confidentiality_empty_evidence_validates():
    """AC-3b: CONFIDENTIALITY (NOT in the old high-risk set) + empty evidence +
    relevance True → VALIDATED. Proves the empty-evidence routing fix (spec §2.2)."""
    clauses = {
        "c1": clause_record(
            position=1, evidence_snippets=None, clause_type=ClauseType.CONFIDENTIALITY
        )
    }
    with patch.object(node_mod, "check_relevance", return_value=True), patch.object(
        node_mod, "check_isrel", MagicMock()
    ), patch.object(node_mod, "check_issup", return_value=False):
        result = _call_node(clauses)
    _floor_verdict(result["clauses"]["c1"])


def test_recall_floor_non_floor_empty_evidence_still_zero_llm_discard():
    """AC-3 (control): a non-floor type with empty evidence still hits the Branch-B
    zero-LLM discard — no reflector calls."""
    mock_rel = MagicMock()
    clauses = {
        "c1": clause_record(
            position=1, evidence_snippets=[], clause_type=ClauseType.GENERAL
        )
    }
    with patch.object(node_mod, "check_relevance", mock_rel), patch.object(
        node_mod, "check_isrel", MagicMock()
    ), patch.object(node_mod, "check_issup", MagicMock()):
        result = _call_node(clauses)
    assert result["clauses"]["c1"]["final_status"] == ValidationStatus.DISCARDED
    mock_rel.assert_not_called()


def test_recall_floor_relevance_false_discards():
    """AC-4 / EC-2: floor type + relevance False → still DISCARDED (off-topic wins)."""
    clauses = {
        "c1": clause_record(
            position=1,
            evidence_snippets=with_evidence(),
            clause_type=ClauseType.LIABILITY,
        )
    }
    with patch.object(node_mod, "check_relevance", return_value=False), patch.object(
        node_mod, "check_isrel", MagicMock()
    ), patch.object(node_mod, "check_issup", MagicMock()):
        result = _call_node(clauses)
    r = result["clauses"]["c1"]
    assert r["relevance_verdict"] is False
    assert r["final_status"] == ValidationStatus.DISCARDED


def test_recall_floor_relevance_none_validates():
    """AC-4 / EC-1: floor type + relevance None (LLM failure) → VALIDATED (fail-open)."""
    clauses = {
        "c1": clause_record(
            position=1,
            evidence_snippets=with_evidence(),
            clause_type=ClauseType.LIABILITY,
        )
    }
    with patch.object(node_mod, "check_relevance", return_value=None), patch.object(
        node_mod, "check_isrel", MagicMock()
    ), patch.object(node_mod, "check_issup", MagicMock()):
        result = _call_node(clauses)
    r = result["clauses"]["c1"]
    assert r["relevance_verdict"] is None
    assert r["final_status"] == ValidationStatus.VALIDATED


def test_recall_floor_empty_set_restores_old_behavior(monkeypatch):
    """AC-5 (reversibility): with the node's recall-floor set empty, a floor-type
    clause with evidence + ISSUP-False → DISCARDED, exactly as before 027."""
    monkeypatch.setattr(node_mod, "SELF_RAG_RECALL_FLOOR_TYPES", frozenset())
    clauses = {
        "c1": clause_record(
            position=1,
            evidence_snippets=with_evidence(),
            clause_type=ClauseType.LIABILITY,
        )
    }
    with patch.object(node_mod, "check_relevance", return_value=True), patch.object(
        node_mod, "check_isrel", return_value=True
    ), patch.object(node_mod, "check_issup", return_value=False):
        result = _call_node(clauses)
    assert result["clauses"]["c1"]["final_status"] == ValidationStatus.DISCARDED
    assert result["clauses"]["c1"]["issup_verdict"] is False
