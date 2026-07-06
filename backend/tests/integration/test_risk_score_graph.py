"""
Integration tests: RiskScore (Node 5) wired into the full LangGraph graph.

score_risk is patched at the node module level (app.graph.nodes.risk_score_agent.score_risk)
because the node did `from ...risk_scorer import score_risk`, binding the name locally.
Patching scorers.risk_scorer.score_risk would NOT affect the already-bound name
and could silently hit real Ollama.

Upstream LLM/embed/web calls are also mocked — no live Ollama or network required.

Run: python -m pytest tests/integration/test_risk_score_graph.py -v
"""

import json
from unittest.mock import MagicMock, patch

import pytest

import app.graph.nodes.crag_retrieval_agent as crag_mod
import app.graph.nodes.self_rag_validation_agent as self_rag_mod
import app.graph.nodes.risk_score_agent as risk_score_mod
import app.graph.nodes.retrievers.kb_retriever as kb_mod
from app.graph.builder import build_graph
from app.graph.nodes.retrievers import RetrievalResult
from app.graph.state import RiskLevel, ValidationStatus

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


def test_graph_reaches_risk_score_and_ends(sample_pdf_path):
    """Full path Node1→…→5 reaches END; every VALIDATED clause carries a risk_level."""
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
    ):
        final_state = graph.invoke({"document_path": sample_pdf_path})

    assert final_state.get("ingest_error") is None
    # current_node is now "report" — Node 7 is the terminal node after feature-009
    assert final_state.get("current_node") == "report"
    clauses = final_state.get("clauses", {})
    assert len(clauses) >= 1
    for clause_id, clause in clauses.items():
        if clause.get("final_status") == ValidationStatus.VALIDATED:
            assert (
                clause.get("risk_level") is not None
            ), f"VALIDATED clause {clause_id} missing risk_level"


def test_graph_ingest_error_skips_risk_score(unsupported_txt_path):
    """Ingest error short-circuits to END; RiskScore not reached."""
    graph = build_graph()

    with patch(SCORE_TARGET) as mock_score:
        final_state = graph.invoke({"document_path": unsupported_txt_path})

    assert final_state.get("ingest_error") is not None
    # KeyError caution: clauses channel has no default; use .get() not direct access
    assert not final_state.get("clauses")
    mock_score.assert_not_called()


def test_graph_only_validated_scored(sample_pdf_path):
    """Mixed fixture: VALIDATED clauses get a risk_level; DISCARDED clauses keep
    risk_level absent/None; all IDs remain present in state (AC-2)."""
    two_clauses = [
        {
            "text": ("The vendor shall indemnify the client for all liability. " * 5),
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
        SCORE_TARGET, return_value=(RiskLevel.MEDIUM, "medium risk")
    ):
        final_state = graph.invoke({"document_path": sample_pdf_path})

    clauses = final_state.get("clauses", {})
    assert len(clauses) == 2

    validated = [
        c
        for c in clauses.values()
        if c.get("final_status") == ValidationStatus.VALIDATED
    ]
    discarded = [
        c
        for c in clauses.values()
        if c.get("final_status") == ValidationStatus.DISCARDED
    ]

    for c in validated:
        assert c.get("risk_level") is not None

    for c in discarded:
        assert c.get("risk_level") is None


def test_graph_no_validated_findings(sample_pdf_path):
    """All-DISCARDED document → no clause has a risk_level; graph ends cleanly
    with no error_count (AC-10)."""
    mock_client = _make_mock_ollama_client(_sample_clause_list())
    graph = build_graph()

    # All relevance checks return False → all clauses DISCARDED
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
        SCORE_TARGET
    ) as mock_score:
        final_state = graph.invoke({"document_path": sample_pdf_path})

    mock_score.assert_not_called()
    clauses = final_state.get("clauses", {})
    for clause in clauses.values():
        assert clause.get("risk_level") is None
    assert (
        final_state.get("error_count") is None or final_state.get("error_count", 0) == 0
    )


def test_graph_circuit_open_sets_error_count(sample_pdf_path):
    """Forcing all score_risk calls to return None opens the breaker → final
    state error_count == 1 and remaining validated findings default to HIGH (AC-14, AC-15).
    """
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
    ), patch.object(
        risk_score_mod, "RISK_SCORE_LLM_CIRCUIT_BREAKER_THRESHOLD", 1
    ), patch(
        SCORE_TARGET, return_value=None
    ):
        final_state = graph.invoke({"document_path": sample_pdf_path})

    assert final_state.get("error_count") == 1
    clauses = final_state.get("clauses", {})
    validated = [
        c
        for c in clauses.values()
        if c.get("final_status") == ValidationStatus.VALIDATED
    ]
    for c in validated:
        assert c.get("risk_level") == RiskLevel.HIGH


def test_graph_checkpointing_after_risk_score(sample_pdf_path):
    """State is checkpointed after RiskScore completes (SqliteSaver)."""
    try:
        from langgraph.checkpoint.sqlite import SqliteSaver
    except ImportError:
        pytest.skip("SqliteSaver import path unavailable — acceptable")

    mock_client = _make_mock_ollama_client(_sample_clause_list())

    with SqliteSaver.from_conn_string(":memory:") as checkpointer:
        from langgraph.graph import StateGraph, END
        from app.graph.state import ContractState
        from app.graph.nodes.ingest_agent import ingest_agent
        from app.graph.nodes.clause_splitter_agent import clause_splitter_agent
        from app.graph.nodes.crag_retrieval_agent import crag_retrieval_agent
        from app.graph.nodes.self_rag_validation_agent import (
            self_rag_validation_agent as srv,
        )
        from app.graph.nodes.risk_score_agent import risk_score_agent as rsa

        g = StateGraph(ContractState)

        def route_after_ingest(state):
            if state.get("ingest_error"):
                return "end"
            return "clause_splitter"

        g.add_node("ingest_agent", ingest_agent)
        g.add_conditional_edges(
            "ingest_agent",
            route_after_ingest,
            {"end": END, "clause_splitter": "clause_splitter"},
        )
        g.add_node("clause_splitter", clause_splitter_agent)
        g.add_edge("clause_splitter", "crag_retrieval")
        g.add_node("crag_retrieval", crag_retrieval_agent)
        g.add_edge("crag_retrieval", "self_rag_validation")
        g.add_node("self_rag_validation", srv)
        g.add_edge("self_rag_validation", "risk_score")
        g.add_node("risk_score", rsa)
        g.add_edge("risk_score", END)
        g.set_entry_point("ingest_agent")
        compiled = g.compile(checkpointer=checkpointer)

        thread_cfg = {"configurable": {"thread_id": "test-ckpt-007"}}
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
        ):
            final = compiled.invoke(
                {"document_path": sample_pdf_path}, config=thread_cfg
            )

        assert final.get("current_node") == "risk_score"
        # Verify checkpointed state is retrievable
        saved = compiled.get_state(thread_cfg)
        assert saved is not None
