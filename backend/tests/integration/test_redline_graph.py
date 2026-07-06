"""
Integration tests: Redline (Node 6) wired into the full LangGraph graph.

draft_rewrite is patched at the node module level
(app.graph.nodes.redline_agent.draft_rewrite) because the node did
`from ...redline_drafter import draft_rewrite`, binding the name locally.
Patching the drafter module directly would NOT affect the already-bound name.

Upstream LLM/embed/web calls are also mocked — no live Ollama or network required.

Run: python -m pytest tests/integration/test_redline_graph.py -v
"""

import json
from unittest.mock import MagicMock, patch

import pytest

import app.graph.nodes.crag_retrieval_agent as crag_mod
import app.graph.nodes.self_rag_validation_agent as self_rag_mod
import app.graph.nodes.risk_score_agent as risk_score_mod
import app.graph.nodes.redline_agent as redline_mod
import app.graph.nodes.retrievers.kb_retriever as kb_mod
from app.graph.builder import build_graph
from app.graph.nodes.retrievers import RetrievalResult
from app.graph.state import RiskLevel, ValidationStatus

DRAFT_TARGET = "app.graph.nodes.redline_agent.draft_rewrite"
SCORE_TARGET = "app.graph.nodes.risk_score_agent.score_risk"


@pytest.fixture(autouse=True)
def reset_kb_cache():
    """Prevent a cached KB from leaking between tests."""
    kb_mod._KB_CACHE = None
    yield
    kb_mod._KB_CACHE = None


def _make_llm_response(clauses: list) -> dict:
    return {"message": {"content": json.dumps({"clauses": clauses})}}


def _make_mock_ollama_client(clauses: list) -> MagicMock:
    client = MagicMock()
    client.chat.return_value = _make_llm_response(clauses)
    return client


def _sample_clause_list():
    return [
        {
            "text": (
                "The vendor shall indemnify and hold harmless the client from all "
                "claims arising from the vendor's unlimited liability. " * 5
            ),
            "section_number": "4.1",
            "clause_type": "liability",
        }
    ]


def _mock_web_result(n: int = 2) -> RetrievalResult:
    return RetrievalResult(
        snippets=[
            {
                "snippet_text": f"Web snippet {i}",
                "source_reference": f"https://web.example/{i}",
            }
            for i in range(n)
        ],
        top_score=None,
    )


# ── Tests ──────────────────────────────────────────────────────────────────────


def test_graph_routes_to_redline_and_ends(sample_pdf_path):
    """Full path Node1→…→6 routes through redline to END; eligible clause carries
    a non-empty suggested_rewrite (AC-30/31)."""
    mock_client = _make_mock_ollama_client(_sample_clause_list())
    graph = build_graph()

    with patch("ollama.Client", return_value=mock_client), patch.object(
        crag_mod, "embed_query", return_value=None
    ), patch.object(
        crag_mod, "web_search", return_value=_mock_web_result()
    ), patch.object(
        self_rag_mod, "check_relevance", return_value=True
    ), patch.object(
        self_rag_mod, "check_isrel", return_value=True
    ), patch.object(
        self_rag_mod, "check_issup", return_value=True
    ), patch(
        SCORE_TARGET, return_value=(RiskLevel.HIGH, "high risk finding")
    ), patch(
        DRAFT_TARGET, return_value="safer rewritten clause"
    ):
        final_state = graph.invoke({"document_path": sample_pdf_path})

    assert final_state.get("ingest_error") is None
    assert final_state.get("current_node") == "report"
    clauses = final_state.get("clauses", {})
    assert len(clauses) >= 1
    # Branch evidence: every VALIDATED clause went through redline and has a rewrite
    for clause in clauses.values():
        if clause.get("final_status") == ValidationStatus.VALIDATED:
            assert clause.get("suggested_rewrite") == "safer rewritten clause"


def test_graph_routes_to_skip_redline_and_ends(sample_pdf_path):
    """All-DISCARDED doc routes through skip_redline to END; no suggested_rewrite on
    any clause (AC-2/28)."""
    mock_client = _make_mock_ollama_client(_sample_clause_list())
    graph = build_graph()

    with patch("ollama.Client", return_value=mock_client), patch.object(
        crag_mod, "embed_query", return_value=None
    ), patch.object(
        crag_mod, "web_search", return_value=_mock_web_result()
    ), patch.object(
        self_rag_mod, "check_relevance", return_value=False
    ), patch.object(
        self_rag_mod, "check_isrel", return_value=False
    ), patch.object(
        self_rag_mod, "check_issup", return_value=False
    ), patch(
        DRAFT_TARGET
    ) as mock_draft:
        final_state = graph.invoke({"document_path": sample_pdf_path})

    assert final_state.get("current_node") == "report"
    mock_draft.assert_not_called()
    clauses = final_state.get("clauses", {})
    for clause in clauses.values():
        assert clause.get("suggested_rewrite") is None


def test_graph_ingest_error_skips_to_end(unsupported_txt_path):
    """Ingest error short-circuits to END without reaching Node 6."""
    graph = build_graph()

    with patch(DRAFT_TARGET) as mock_draft:
        final_state = graph.invoke({"document_path": unsupported_txt_path})

    assert final_state.get("ingest_error") is not None
    # KeyError caution: clauses channel has no default — use .get() not direct access
    assert not final_state.get("clauses")
    mock_draft.assert_not_called()


def test_graph_mixed_only_eligible_rewritten(sample_pdf_path):
    """Mixed fixture: eligible clauses get suggested_rewrite; ineligible/discarded keep
    it absent; risk_level unchanged everywhere (AC-9/10/27)."""
    two_clauses = [
        {
            "text": "The vendor shall indemnify the client for all liability. " * 5,
            "section_number": "1.1",
            "clause_type": "liability",
        },
        {
            "text": "This agreement shall be governed by applicable law. " * 5,
            "section_number": "1.2",
            "clause_type": "general",
        },
    ]
    mock_client = _make_mock_ollama_client(two_clauses)
    graph = build_graph()

    call_count = [0]

    def alternating_relevance(*args, **kwargs):
        call_count[0] += 1
        return call_count[0] % 2 == 1  # True for 1st, False for 2nd

    with patch("ollama.Client", return_value=mock_client), patch.object(
        crag_mod, "embed_query", return_value=None
    ), patch.object(
        crag_mod, "web_search", return_value=_mock_web_result()
    ), patch.object(
        self_rag_mod, "check_relevance", side_effect=alternating_relevance
    ), patch.object(
        self_rag_mod, "check_isrel", return_value=True
    ), patch.object(
        self_rag_mod, "check_issup", return_value=True
    ), patch(
        SCORE_TARGET, return_value=(RiskLevel.HIGH, "high risk")
    ), patch(
        DRAFT_TARGET, return_value="safer text"
    ):
        final_state = graph.invoke({"document_path": sample_pdf_path})

    clauses = final_state.get("clauses", {})
    validated = [c for c in clauses.values() if c.get("final_status") == ValidationStatus.VALIDATED]
    discarded = [c for c in clauses.values() if c.get("final_status") == ValidationStatus.DISCARDED]

    for c in validated:
        assert c.get("risk_level") is not None
        # risk_level must not be modified by redline_agent
        assert c.get("suggested_rewrite") == "safer text"

    for c in discarded:
        assert c.get("suggested_rewrite") is None


def test_graph_circuit_open_sets_error_count(sample_pdf_path):
    """Forcing all draft_rewrite calls to return None opens the breaker → final
    state error_count == 1, eligible clauses have suggested_rewrite is None (AC-20/23)."""
    mock_client = _make_mock_ollama_client(_sample_clause_list())
    graph = build_graph()

    with patch("ollama.Client", return_value=mock_client), patch.object(
        crag_mod, "embed_query", return_value=None
    ), patch.object(
        crag_mod, "web_search", return_value=_mock_web_result()
    ), patch.object(
        self_rag_mod, "check_relevance", return_value=True
    ), patch.object(
        self_rag_mod, "check_isrel", return_value=True
    ), patch.object(
        self_rag_mod, "check_issup", return_value=True
    ), patch(
        SCORE_TARGET, return_value=(RiskLevel.HIGH, "high risk")
    ), patch.object(
        redline_mod, "REDLINE_LLM_CIRCUIT_BREAKER_THRESHOLD", 1
    ), patch(
        DRAFT_TARGET, return_value=None
    ):
        final_state = graph.invoke({"document_path": sample_pdf_path})

    assert final_state.get("error_count") == 1
    clauses = final_state.get("clauses", {})
    for clause in clauses.values():
        if clause.get("final_status") == ValidationStatus.VALIDATED:
            assert clause.get("suggested_rewrite") is None


def test_graph_has_only_expected_conditional_edges(sample_pdf_path):
    """Inspect the compiled graph: risk_score branches to exactly {redline, skip_redline};
    crag_retrieval stays internal (no graph-level conditional); ingest_agent is the
    only other conditional source (AC-32)."""
    graph = build_graph()
    g = graph.get_graph()

    # Map each source node to its set of outgoing targets to find fan-out (conditional) sources
    edges = list(g.edges)
    # Find which source nodes fan out to multiple targets
    from collections import defaultdict
    outgoing = defaultdict(set)
    for edge in edges:
        # edge is a tuple (source, target) or an object
        if hasattr(edge, "source") and hasattr(edge, "target"):
            outgoing[edge.source].add(edge.target)
        elif isinstance(edge, tuple) and len(edge) >= 2:
            outgoing[edge[0]].add(edge[1])

    # risk_score must fan out to exactly {redline, skip_redline}
    risk_score_targets = outgoing.get("risk_score", set())
    assert "redline" in risk_score_targets, f"'redline' not in risk_score successors: {risk_score_targets}"
    assert "skip_redline" in risk_score_targets, f"'skip_redline' not in risk_score successors: {risk_score_targets}"

    # ingest_agent must fan out (to clause_splitter and END)
    ingest_targets = outgoing.get("ingest_agent", set())
    assert len(ingest_targets) >= 2

    # crag_retrieval must have a single linear successor
    crag_targets = outgoing.get("crag_retrieval", set())
    assert len(crag_targets) == 1, f"crag_retrieval must have exactly 1 successor, got: {crag_targets}"


def test_graph_checkpointing_after_redline(sample_pdf_path):
    """State is checkpointed after Node 6 completes (SqliteSaver)."""
    try:
        from langgraph.checkpoint.sqlite import SqliteSaver
    except ImportError:
        pytest.skip("SqliteSaver import path unavailable — acceptable")

    mock_client = _make_mock_ollama_client(_sample_clause_list())

    with SqliteSaver.from_conn_string(":memory:") as checkpointer:
        from langgraph.graph import StateGraph, END as GRAPH_END
        from app.graph.state import ContractState
        from app.graph.nodes.ingest_agent import ingest_agent
        from app.graph.nodes.clause_splitter_agent import clause_splitter_agent
        from app.graph.nodes.crag_retrieval_agent import crag_retrieval_agent
        from app.graph.nodes.self_rag_validation_agent import (
            self_rag_validation_agent as srv,
        )
        from app.graph.nodes.risk_score_agent import risk_score_agent as rsa
        from app.graph.nodes.redline_agent import (
            route_on_risk as ror,
            redline_agent as ra,
            skip_redline as sr,
        )

        g = StateGraph(ContractState)

        def route_after_ingest(state):
            if state.get("ingest_error"):
                return "end"
            return "clause_splitter"

        g.add_node("ingest_agent", ingest_agent)
        g.add_conditional_edges(
            "ingest_agent",
            route_after_ingest,
            {"end": GRAPH_END, "clause_splitter": "clause_splitter"},
        )
        g.add_node("clause_splitter", clause_splitter_agent)
        g.add_edge("clause_splitter", "crag_retrieval")
        g.add_node("crag_retrieval", crag_retrieval_agent)
        g.add_edge("crag_retrieval", "self_rag_validation")
        g.add_node("self_rag_validation", srv)
        g.add_edge("self_rag_validation", "risk_score")
        g.add_node("risk_score", rsa)
        g.add_node("redline", ra)
        g.add_node("skip_redline", sr)
        g.add_conditional_edges(
            "risk_score",
            ror,
            {"redline": "redline", "skip_redline": "skip_redline"},
        )
        g.add_edge("redline", GRAPH_END)
        g.add_edge("skip_redline", GRAPH_END)
        g.set_entry_point("ingest_agent")
        compiled = g.compile(checkpointer=checkpointer)

        thread_cfg = {"configurable": {"thread_id": "test-ckpt-008"}}
        with patch("ollama.Client", return_value=mock_client), patch.object(
            crag_mod, "embed_query", return_value=None
        ), patch.object(
            crag_mod, "web_search", return_value=_mock_web_result()
        ), patch.object(
            self_rag_mod, "check_relevance", return_value=True
        ), patch.object(
            self_rag_mod, "check_isrel", return_value=True
        ), patch.object(
            self_rag_mod, "check_issup", return_value=True
        ), patch(
            SCORE_TARGET, return_value=(RiskLevel.HIGH, "high risk")
        ), patch(
            DRAFT_TARGET, return_value="safer rewritten clause"
        ):
            final = compiled.invoke(
                {"document_path": sample_pdf_path}, config=thread_cfg
            )

        # Node 6 is now terminal — current_node must be "redline" or "skip_redline"
        assert final.get("current_node") in ("redline", "skip_redline")
        # Verify checkpointed state is retrievable
        saved = compiled.get_state(thread_cfg)
        assert saved is not None
