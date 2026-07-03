"""
Unit tests for app.graph.nodes.crag_retrieval_agent.crag_retrieval_agent.

All external calls (embed_query, load_kb, search_kb, web_search) are mocked
at the node module level per the Node 2 monkeypatch precedent.

Run: python -m pytest tests/unit/test_crag_retrieval_agent.py -v
"""

from unittest.mock import MagicMock, patch

import pytest

import app.graph.nodes.crag_retrieval_agent as crag_mod
from app.graph.nodes.crag_retrieval_agent import crag_retrieval_agent
from app.graph.nodes.retrievers import RetrievalResult
from app.graph.state import RetrievalPath

# ── Helpers ────────────────────────────────────────────────────────────────────


def make_crag_state(clauses: dict, ingest_error=None, document_id="doc-1"):
    """Build a minimal state dict with the keys CRAG reads."""
    return {
        "document_id": document_id,
        "clauses": clauses,
        "ingest_error": ingest_error,
    }


def _clause(text="Some contract clause text.", position=1):
    return {
        "text": text,
        "position": position,
        "section_number": None,
        "clause_type": None,
    }


def _kb_result(top_score: float, n_snippets: int = 2) -> RetrievalResult:
    snippets = [
        {"snippet_text": f"KB snippet {i}", "source_reference": f"kb://ref/{i}"}
        for i in range(n_snippets)
    ]
    return RetrievalResult(snippets=snippets, top_score=top_score)


def _web_result(n_snippets: int = 2) -> RetrievalResult:
    snippets = [
        {
            "snippet_text": f"Web snippet {i}",
            "source_reference": f"https://web.example/{i}",
        }
        for i in range(n_snippets)
    ]
    return RetrievalResult(snippets=snippets, top_score=None)


THRESHOLD = 0.73
EMBED_VEC = [0.1] * 10  # dummy non-zero vector (shape doesn't matter for mocked search)


@pytest.fixture(autouse=True)
def reset_kb_cache():
    """Clear kb_retriever module cache between tests."""
    import app.graph.nodes.retrievers.kb_retriever as kb_mod

    kb_mod._KB_CACHE = None
    yield
    kb_mod._KB_CACHE = None


# ── Tests ──────────────────────────────────────────────────────────────────────


def test_all_clauses_get_three_fields():
    """Every clause gets confidence_score, path_taken, evidence_snippets (AC-1)."""
    clauses = {
        "clause_001": _clause("Clause A.", 1),
        "clause_002": _clause("Clause B.", 2),
    }
    state = make_crag_state(clauses)

    with patch.object(crag_mod, "load_kb", return_value=MagicMock()), patch.object(
        crag_mod, "embed_query", return_value=EMBED_VEC
    ), patch.object(crag_mod, "search_kb", return_value=_kb_result(0.9)), patch.object(
        crag_mod, "web_search", return_value=_web_result()
    ):
        result = crag_retrieval_agent(state)

    for cid in clauses:
        rec = result["clauses"][cid]
        assert "confidence_score" in rec
        assert "path_taken" in rec
        assert "evidence_snippets" in rec


def test_high_confidence_routes_local():
    """top-1 cosine ≥ threshold → LOCAL_KB, KB-sourced snippets (AC-2)."""
    state = make_crag_state({"clause_001": _clause()})

    with patch.object(crag_mod, "load_kb", return_value=MagicMock()), patch.object(
        crag_mod, "embed_query", return_value=EMBED_VEC
    ), patch.object(crag_mod, "search_kb", return_value=_kb_result(0.9)), patch.object(
        crag_mod, "web_search", return_value=_web_result()
    ) as mock_web:
        result = crag_retrieval_agent(state)

    rec = result["clauses"]["clause_001"]
    assert rec["path_taken"] == RetrievalPath.LOCAL_KB
    mock_web.assert_not_called()
    assert rec["evidence_snippets"][0]["source_reference"].startswith("kb://")


def test_low_confidence_routes_web():
    """top-1 cosine < threshold → WEB_FALLBACK, web snippets (AC-3)."""
    state = make_crag_state({"clause_001": _clause()})

    with patch.object(crag_mod, "load_kb", return_value=MagicMock()), patch.object(
        crag_mod, "embed_query", return_value=EMBED_VEC
    ), patch.object(crag_mod, "search_kb", return_value=_kb_result(0.5)), patch.object(
        crag_mod, "web_search", return_value=_web_result()
    ) as mock_web:
        result = crag_retrieval_agent(state)

    rec = result["clauses"]["clause_001"]
    assert rec["path_taken"] == RetrievalPath.WEB_FALLBACK
    mock_web.assert_called_once()
    assert rec["evidence_snippets"][0]["source_reference"].startswith("https://")


def test_threshold_boundary_inclusive_local():
    """cosine == 0.73 → LOCAL_KB (comparison is >=) (AC-4)."""
    state = make_crag_state({"clause_001": _clause()})

    with patch.object(crag_mod, "load_kb", return_value=MagicMock()), patch.object(
        crag_mod, "embed_query", return_value=EMBED_VEC
    ), patch.object(
        crag_mod, "search_kb", return_value=_kb_result(THRESHOLD)
    ), patch.object(
        crag_mod, "web_search", return_value=_web_result()
    ) as mock_web:
        result = crag_retrieval_agent(state)

    assert result["clauses"]["clause_001"]["path_taken"] == RetrievalPath.LOCAL_KB
    mock_web.assert_not_called()


def test_confidence_in_range_or_none():
    """Every confidence_score is None or a float in [0, 1] (AC-5)."""
    clauses = {
        "clause_001": _clause("Normal clause.", 1),
        "clause_002": {"text": "", "position": 2},  # empty → None
    }
    state = make_crag_state(clauses)

    with patch.object(crag_mod, "load_kb", return_value=MagicMock()), patch.object(
        crag_mod, "embed_query", return_value=EMBED_VEC
    ), patch.object(crag_mod, "search_kb", return_value=_kb_result(0.8)), patch.object(
        crag_mod, "web_search", return_value=_web_result()
    ):
        result = crag_retrieval_agent(state)

    for cid, rec in result["clauses"].items():
        score = rec["confidence_score"]
        assert score is None or (0.0 <= score <= 1.0), f"{cid}: score={score}"


def test_snippet_cap_enforced(monkeypatch):
    """With CRAG_MAX_EVIDENCE_SNIPPETS below source count, no clause exceeds the cap (AC-7)."""
    monkeypatch.setattr(crag_mod, "CRAG_MAX_EVIDENCE_SNIPPETS", 2)
    state = make_crag_state({"clause_001": _clause()})

    with patch.object(crag_mod, "load_kb", return_value=MagicMock()), patch.object(
        crag_mod, "embed_query", return_value=EMBED_VEC
    ), patch.object(
        crag_mod, "search_kb", return_value=_kb_result(0.9, n_snippets=5)
    ), patch.object(
        crag_mod, "web_search", return_value=_web_result()
    ):
        result = crag_retrieval_agent(state)

    assert len(result["clauses"]["clause_001"]["evidence_snippets"]) == 2


def test_embed_model_separation():
    """embed_query invoked with OLLAMA_EMBED_MODEL_NAME, never OLLAMA_MODEL_NAME (AC-8)."""
    state = make_crag_state({"clause_001": _clause()})

    with patch.object(crag_mod, "load_kb", return_value=MagicMock()), patch.object(
        crag_mod, "embed_query", return_value=EMBED_VEC
    ) as mock_embed, patch.object(
        crag_mod, "search_kb", return_value=_kb_result(0.9)
    ), patch.object(
        crag_mod, "web_search", return_value=_web_result()
    ):
        crag_retrieval_agent(state)

    args = mock_embed.call_args
    used_model = args.args[2] if len(args.args) > 2 else args.kwargs.get("model_name")
    assert used_model == crag_mod.OLLAMA_EMBED_MODEL_NAME
    assert used_model != crag_mod.OLLAMA_MODEL_NAME


def test_ingest_error_returns_empty():
    """ingest_error set → empty clauses update; no embed/KB/web calls (AC-10)."""
    state = make_crag_state(
        {"clause_001": _clause()},
        ingest_error={"error_type": "unsupported_format", "message": "bad file"},
    )

    with patch.object(crag_mod, "load_kb") as mk_kb, patch.object(
        crag_mod, "embed_query"
    ) as mk_embed, patch.object(crag_mod, "search_kb") as mk_search, patch.object(
        crag_mod, "web_search"
    ) as mk_web:
        result = crag_retrieval_agent(state)

    assert result["clauses"] == {}
    mk_kb.assert_not_called()
    mk_embed.assert_not_called()
    mk_search.assert_not_called()
    mk_web.assert_not_called()


def test_empty_clauses_returns_empty(caplog):
    """clauses == {} → empty update, warning logged, no external calls (AC-11)."""
    state = make_crag_state({})

    with patch.object(crag_mod, "load_kb") as mk_kb, patch.object(
        crag_mod, "embed_query"
    ) as mk_embed, patch.object(crag_mod, "search_kb") as mk_search, patch.object(
        crag_mod, "web_search"
    ) as mk_web, caplog.at_level(
        "WARNING"
    ):
        result = crag_retrieval_agent(state)

    assert result["clauses"] == {}
    mk_kb.assert_not_called()
    mk_embed.assert_not_called()
    mk_search.assert_not_called()
    mk_web.assert_not_called()
    assert any(r.levelno >= 30 for r in caplog.records)


def test_partial_update_only():
    """Return dict has ONLY {clauses, current_node, node_timings}; no error_count (AC-12)."""
    state = make_crag_state({"clause_001": _clause()})
    forbidden = {
        "document_id",
        "extracted_text",
        "ocr_used",
        "ingest_error",
        "report_path",
        "evidence_trail",
        "mcp_delivery_status",
        "error_count",
    }

    with patch.object(crag_mod, "load_kb", return_value=MagicMock()), patch.object(
        crag_mod, "embed_query", return_value=EMBED_VEC
    ), patch.object(crag_mod, "search_kb", return_value=_kb_result(0.9)), patch.object(
        crag_mod, "web_search", return_value=_web_result()
    ):
        result = crag_retrieval_agent(state)

    assert set(result.keys()) == {"clauses", "current_node", "node_timings"}
    for key in forbidden:
        assert key not in result


def test_web_failure_graceful():
    """web_search returning ([], None) → WEB_FALLBACK, [], recorded score, no crash (AC-13).
    Other clauses still process normally."""
    clauses = {
        "clause_001": _clause("Clause A.", 1),
        "clause_002": _clause("Clause B.", 2),
    }
    state = make_crag_state(clauses)

    def web_side_effect(*args, **kwargs):
        return RetrievalResult(snippets=[], top_score=None)

    with patch.object(crag_mod, "load_kb", return_value=MagicMock()), patch.object(
        crag_mod, "embed_query", return_value=EMBED_VEC
    ), patch.object(crag_mod, "search_kb", return_value=_kb_result(0.5)), patch.object(
        crag_mod, "web_search", side_effect=web_side_effect
    ):
        result = crag_retrieval_agent(state)

    for cid in clauses:
        rec = result["clauses"][cid]
        assert rec["path_taken"] == RetrievalPath.WEB_FALLBACK
        assert rec["evidence_snippets"] == []
        assert rec["confidence_score"] is not None


def test_kb_unavailable_all_web(caplog):
    """load_kb() → None → every clause WEB_FALLBACK, one warning (AC-14)."""
    clauses = {
        "clause_001": _clause("Clause A.", 1),
        "clause_002": _clause("Clause B.", 2),
    }
    state = make_crag_state(clauses)

    with patch.object(crag_mod, "load_kb", return_value=None), patch.object(
        crag_mod, "embed_query", return_value=EMBED_VEC
    ), patch.object(crag_mod, "search_kb") as mk_search, patch.object(
        crag_mod, "web_search", return_value=_web_result()
    ), caplog.at_level(
        "WARNING"
    ):
        result = crag_retrieval_agent(state)

    mk_search.assert_not_called()
    for cid in clauses:
        assert result["clauses"][cid]["path_taken"] == RetrievalPath.WEB_FALLBACK


def test_local_path_deterministic():
    """Same text + same mocked KB + same embed → identical snippets + score across two runs (AC-15)."""
    state = make_crag_state({"clause_001": _clause()})
    mock_kb = MagicMock()
    fixed_snippets = _kb_result(0.85)

    with patch.object(crag_mod, "load_kb", return_value=mock_kb), patch.object(
        crag_mod, "embed_query", return_value=EMBED_VEC
    ), patch.object(crag_mod, "search_kb", return_value=fixed_snippets), patch.object(
        crag_mod, "web_search", return_value=_web_result()
    ):
        r1 = crag_retrieval_agent(state)
        r2 = crag_retrieval_agent(state)

    assert (
        r1["clauses"]["clause_001"]["confidence_score"]
        == r2["clauses"]["clause_001"]["confidence_score"]
    )
    assert (
        r1["clauses"]["clause_001"]["evidence_snippets"]
        == r2["clauses"]["clause_001"]["evidence_snippets"]
    )


def test_circuit_breaker_opens(monkeypatch, caplog):
    """After CRAG_EMBED_CIRCUIT_BREAKER_THRESHOLD consecutive failures, embed stops (AC-16)."""
    monkeypatch.setattr(crag_mod, "CRAG_EMBED_CIRCUIT_BREAKER_THRESHOLD", 3)
    # 6 clauses: embed fails for all → breaker should open after 3, skip remaining 3
    clauses = {f"clause_{i:03d}": _clause(f"Clause {i}.", i) for i in range(1, 7)}
    state = make_crag_state(clauses)

    with patch.object(crag_mod, "load_kb", return_value=MagicMock()), patch.object(
        crag_mod, "embed_query", return_value=None
    ) as mk_embed, patch.object(crag_mod, "search_kb") as mk_search, patch.object(
        crag_mod, "web_search", return_value=_web_result()
    ), caplog.at_level(
        "WARNING"
    ):
        result = crag_retrieval_agent(state)

    # embed_query called only for first 3 (threshold) clauses, then circuit opens
    assert mk_embed.call_count == 3
    mk_search.assert_not_called()
    # All clauses still got WEB_FALLBACK
    for cid in clauses:
        assert result["clauses"][cid]["path_taken"] == RetrievalPath.WEB_FALLBACK
    # "circuit opened" warning emitted once
    circuit_warnings = [
        r for r in caplog.records if "circuit" in r.message.lower() and r.levelno >= 30
    ]
    assert len(circuit_warnings) >= 1


def test_circuit_resets_on_success(monkeypatch):
    """A success between failures resets the counter — circuit does NOT trip on intermittent failures."""
    monkeypatch.setattr(crag_mod, "CRAG_EMBED_CIRCUIT_BREAKER_THRESHOLD", 3)
    # Pattern: fail, fail, success, fail, fail → counter resets after success → 2 consecutive, no trip
    # 5 clauses + 1 extra so we know no circuit opened
    clauses = {f"clause_{i:03d}": _clause(f"Clause {i}.", i) for i in range(1, 6)}
    state = make_crag_state(clauses)

    embed_return_values = [None, None, EMBED_VEC, None, None]
    embed_call_count = [0]

    def embed_side_effect(*args, **kwargs):
        idx = embed_call_count[0]
        embed_call_count[0] += 1
        if idx < len(embed_return_values):
            return embed_return_values[idx]
        return EMBED_VEC

    with patch.object(crag_mod, "load_kb", return_value=MagicMock()), patch.object(
        crag_mod, "embed_query", side_effect=embed_side_effect
    ) as mk_embed, patch.object(
        crag_mod, "search_kb", return_value=_kb_result(0.9)
    ), patch.object(
        crag_mod, "web_search", return_value=_web_result()
    ):
        crag_retrieval_agent(state)

    # All 5 clauses should have been attempted (no circuit trip)
    assert mk_embed.call_count == 5


def test_empty_clause_text_skipped():
    """Whitespace-only clause → all three fields None; embed_query NOT called for it (spec §4.3)."""
    state = make_crag_state(
        {
            "clause_001": {"text": "   ", "position": 1},
        }
    )

    with patch.object(crag_mod, "load_kb", return_value=MagicMock()), patch.object(
        crag_mod, "embed_query"
    ) as mk_embed, patch.object(crag_mod, "search_kb") as mk_search, patch.object(
        crag_mod, "web_search"
    ) as mk_web:
        result = crag_retrieval_agent(state)

    rec = result["clauses"]["clause_001"]
    assert rec["confidence_score"] is None
    assert rec["path_taken"] is None
    assert rec["evidence_snippets"] is None
    mk_embed.assert_not_called()
    mk_search.assert_not_called()
    mk_web.assert_not_called()


def test_current_node_pinned():
    """current_node == 'crag_retrieval' and that string keys node_timings."""
    state = make_crag_state({"clause_001": _clause()})

    with patch.object(crag_mod, "load_kb", return_value=MagicMock()), patch.object(
        crag_mod, "embed_query", return_value=EMBED_VEC
    ), patch.object(crag_mod, "search_kb", return_value=_kb_result(0.9)), patch.object(
        crag_mod, "web_search", return_value=_web_result()
    ):
        result = crag_retrieval_agent(state)

    assert result["current_node"] == "crag_retrieval"
    assert "crag_retrieval" in result["node_timings"]


def test_confidence_none_vs_zero():
    """Embed failure → confidence_score is None; KB-unavailable-with-successful-embed → 0.0."""
    # Case 1: embed fails → None
    state1 = make_crag_state({"clause_001": _clause()})
    with patch.object(crag_mod, "load_kb", return_value=MagicMock()), patch.object(
        crag_mod, "embed_query", return_value=None
    ), patch.object(crag_mod, "search_kb", return_value=_kb_result(0.5)), patch.object(
        crag_mod, "web_search", return_value=_web_result()
    ):
        r1 = crag_retrieval_agent(state1)
    assert r1["clauses"]["clause_001"]["confidence_score"] is None

    # Case 2: embed succeeds but KB is None → 0.0
    state2 = make_crag_state({"clause_001": _clause()})
    with patch.object(crag_mod, "load_kb", return_value=None), patch.object(
        crag_mod, "embed_query", return_value=EMBED_VEC
    ), patch.object(crag_mod, "search_kb") as mk_s, patch.object(
        crag_mod, "web_search", return_value=_web_result()
    ):
        r2 = crag_retrieval_agent(state2)
    assert r2["clauses"]["clause_001"]["confidence_score"] == 0.0
    mk_s.assert_not_called()


def test_query_truncated_before_embed(monkeypatch):
    """Clause text longer than CRAG_QUERY_MAX_CHARS → truncated text passed to embed_query (spec §4.11)."""
    monkeypatch.setattr(crag_mod, "CRAG_QUERY_MAX_CHARS", 10)
    long_text = "A" * 100
    state = make_crag_state({"clause_001": {"text": long_text, "position": 1}})

    with patch.object(crag_mod, "load_kb", return_value=MagicMock()), patch.object(
        crag_mod, "embed_query", return_value=EMBED_VEC
    ) as mk_embed, patch.object(
        crag_mod, "search_kb", return_value=_kb_result(0.9)
    ), patch.object(
        crag_mod, "web_search", return_value=_web_result()
    ):
        crag_retrieval_agent(state)

    called_text = mk_embed.call_args.args[0]
    assert len(called_text) == 10
    assert called_text == "A" * 10
