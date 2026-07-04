"""
Integration tests: IngestAgent → ClauseSplitterAgent → CRAGRetrievalAgent →
SelfRAGValidationAgent wired in the LangGraph graph.

The three Self-RAG reflective judgments are mocked on the node module (because
the node did `from ...reflectors import ...`, binding those names locally).
Patching app.graph.nodes.validators.reflectors.* would NOT intercept the
already-bound names and could silently hit real Ollama.

Upstream LLM/embed/web calls are also mocked so no live Ollama or network is
needed.

Run: python -m pytest tests/integration/test_self_rag_validation_graph.py -v
"""

import json
from unittest.mock import MagicMock, patch

import pytest

import app.graph.nodes.crag_retrieval_agent as crag_mod
import app.graph.nodes.self_rag_validation_agent as self_rag_mod
import app.graph.nodes.retrievers.kb_retriever as kb_mod
from app.graph.builder import build_graph
from app.graph.nodes.retrievers import RetrievalResult
from app.graph.state import ValidationStatus, ClauseType

# ── Fixtures / helpers ─────────────────────────────────────────────────────────


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
            "text": "The vendor shall indemnify and hold harmless the client "
            "from all claims arising from the vendor's negligence. " * 5,
            "section_number": "4.1",
            "clause_type": "liability",
        }
    ]


def _mock_web_result(n: int = 2) -> RetrievalResult:
    return RetrievalResult(
        snippets=[
            {
                "snippet_text": f"Web evidence snippet {i}",
                "source_reference": f"https://web.example/{i}",
            }
            for i in range(n)
        ],
        top_score=None,
    )


def _all_true(*args, **kwargs):
    return True


def _all_false(*args, **kwargs):
    return False


# ── Tests ──────────────────────────────────────────────────────────────────────


def test_graph_reaches_self_rag_and_ends(sample_pdf_path):
    """Node1→Node2→Node3→Node4 reaches END; every clause carries a non-None final_status."""
    mock_client = _make_mock_ollama_client(_sample_clause_list())
    graph = build_graph()

    with patch("ollama.Client", return_value=mock_client), patch.object(
        crag_mod, "embed_query", return_value=None
    ), patch.object(
        crag_mod, "web_search", return_value=_mock_web_result()
    ), patch.object(
        self_rag_mod, "check_relevance", side_effect=_all_true
    ), patch.object(
        self_rag_mod, "check_isrel", side_effect=_all_true
    ), patch.object(
        self_rag_mod, "check_issup", side_effect=_all_true
    ):
        final_state = graph.invoke({"document_path": sample_pdf_path})

    assert final_state.get("ingest_error") is None
    assert final_state.get("current_node") == "self_rag_validation"
    clauses = final_state.get("clauses", {})
    assert len(clauses) >= 1
    for clause_id, clause in clauses.items():
        assert (
            clause.get("final_status") is not None
        ), f"Clause {clause_id} missing final_status"


def test_graph_ingest_error_skips_self_rag(unsupported_txt_path):
    """Ingest error short-circuits to END without reaching Self-RAG."""
    mock_rel = MagicMock()
    graph = build_graph()

    with patch.object(crag_mod, "embed_query"), patch.object(
        crag_mod, "web_search"
    ), patch.object(self_rag_mod, "check_relevance", mock_rel):
        final_state = graph.invoke({"document_path": unsupported_txt_path})

    assert final_state.get("ingest_error") is not None
    # KeyError caution: clauses channel has no default; use .get() not direct access
    assert not final_state.get("clauses")
    mock_rel.assert_not_called()


def test_graph_validated_and_discarded_coexist(sample_pdf_path):
    """A mixed fixture yields both VALIDATED and DISCARDED clauses, all still present (AC-19)."""
    # Two clauses: one where Relevance passes → VALIDATED; one where Relevance fails → DISCARDED
    two_clauses = [
        {
            "text": "The vendor shall pay all applicable taxes. " * 5,
            "section_number": "2.1",
            "clause_type": "payment",
        },
        {
            "text": "This agreement is subject to the laws of the jurisdiction. " * 5,
            "section_number": "2.2",
            "clause_type": "general",
        },
    ]
    mock_client = _make_mock_ollama_client(two_clauses)
    graph = build_graph()

    call_count = [0]

    def alternating_relevance(*args, **kwargs):
        call_count[0] += 1
        return call_count[0] % 2 == 1  # True for odd clauses, False for even

    with patch("ollama.Client", return_value=mock_client), patch.object(
        crag_mod, "embed_query", return_value=None
    ), patch.object(
        crag_mod, "web_search", return_value=_mock_web_result()
    ), patch.object(
        self_rag_mod, "check_relevance", side_effect=alternating_relevance
    ), patch.object(
        self_rag_mod, "check_isrel", side_effect=_all_true
    ), patch.object(
        self_rag_mod, "check_issup", side_effect=_all_true
    ):
        final_state = graph.invoke({"document_path": sample_pdf_path})

    clauses = final_state.get("clauses", {})
    statuses = {c.get("final_status") for c in clauses.values()}
    # Both VALIDATED and DISCARDED should appear
    assert ValidationStatus.VALIDATED in statuses
    assert ValidationStatus.DISCARDED in statuses
    # All clause IDs still present (discarded clauses not removed)
    assert len(clauses) == 2


def test_graph_empty_evidence_gate_end_to_end(sample_pdf_path):
    """High-risk empty-evidence clause validates on text; non-high-risk is discarded."""
    # Use two clauses: one liability (high-risk), one general (non-high-risk)
    two_clauses = [
        {
            "text": "Vendor's total liability shall be unlimited and uncapped. " * 5,
            "section_number": "5.1",
            "clause_type": "liability",
        },
        {
            "text": "This clause establishes general operational guidelines. " * 5,
            "section_number": "5.2",
            "clause_type": "general",
        },
    ]
    mock_client = _make_mock_ollama_client(two_clauses)
    graph = build_graph()

    with patch("ollama.Client", return_value=mock_client), patch.object(
        crag_mod, "embed_query", return_value=None
    ), patch.object(
        crag_mod,
        "web_search",
        return_value=RetrievalResult(snippets=[], top_score=None),
    ), patch.object(
        self_rag_mod, "check_relevance", side_effect=_all_true
    ), patch.object(
        self_rag_mod, "check_isrel", side_effect=_all_true
    ), patch.object(
        self_rag_mod, "check_issup", side_effect=_all_true
    ):
        final_state = graph.invoke({"document_path": sample_pdf_path})

    clauses = final_state.get("clauses", {})
    assert len(clauses) == 2
    statuses = {c.get("final_status") for c in clauses.values()}
    # High-risk liability clause with empty evidence → rescue path → VALIDATED (Relevance+ISSUP both True)
    # Non-high-risk general clause with empty evidence → zero-LLM discard → DISCARDED
    assert ValidationStatus.VALIDATED in statuses
    assert ValidationStatus.DISCARDED in statuses


def test_graph_circuit_open_sets_error_count(sample_pdf_path, monkeypatch):
    """Forcing all judgments to None opens the breaker → final state error_count==1
    and remaining LLM-path clauses are fail-open VALIDATED (AC-15, AC-20)."""
    monkeypatch.setattr(self_rag_mod, "SELF_RAG_LLM_CIRCUIT_BREAKER_THRESHOLD", 1)
    mock_client = _make_mock_ollama_client(_sample_clause_list())
    graph = build_graph()

    with patch("ollama.Client", return_value=mock_client), patch.object(
        crag_mod, "embed_query", return_value=None
    ), patch.object(
        crag_mod, "web_search", return_value=_mock_web_result()
    ), patch.object(
        self_rag_mod, "check_relevance", return_value=None
    ), patch.object(
        self_rag_mod, "check_isrel", return_value=None
    ), patch.object(
        self_rag_mod, "check_issup", return_value=None
    ):
        final_state = graph.invoke({"document_path": sample_pdf_path})

    # error_count should be 1 (circuit opened)
    assert final_state.get("error_count") == 1
    # All LLM-path clauses should be fail-open VALIDATED
    for clause in final_state.get("clauses", {}).values():
        assert clause.get("final_status") == ValidationStatus.VALIDATED


def test_graph_checkpointing_after_self_rag(sample_pdf_path):
    """State is checkpointed after Self-RAG completes (SqliteSaver)."""
    try:
        from langgraph.checkpoint.sqlite import SqliteSaver
    except ImportError:
        pytest.skip("SqliteSaver import path unavailable — acceptable")

    mock_client = _make_mock_ollama_client(_sample_clause_list())

    with SqliteSaver.from_conn_string(":memory:") as checkpointer:
        graph = build_graph()
        # Re-build with checkpointer attached
        from langgraph.graph import StateGraph, END
        from app.graph.state import ContractState
        from app.graph.nodes.ingest_agent import ingest_agent
        from app.graph.nodes.clause_splitter_agent import clause_splitter_agent
        from app.graph.nodes.crag_retrieval_agent import crag_retrieval_agent

        g = StateGraph(ContractState)
        g.add_node("ingest_agent", ingest_agent)

        def route_after_ingest(state):
            if state.get("ingest_error"):
                return "end"
            return "clause_splitter"

        g.add_conditional_edges(
            "ingest_agent",
            route_after_ingest,
            {"end": END, "clause_splitter": "clause_splitter"},
        )
        g.add_node("clause_splitter", clause_splitter_agent)
        g.add_edge("clause_splitter", "crag_retrieval")
        g.add_node("crag_retrieval", crag_retrieval_agent)
        g.add_edge("crag_retrieval", "self_rag_validation")
        g.add_node("self_rag_validation", self_rag_mod.self_rag_validation_agent)
        g.add_edge("self_rag_validation", END)
        g.set_entry_point("ingest_agent")
        compiled = g.compile(checkpointer=checkpointer)

        thread_cfg = {"configurable": {"thread_id": "test-ckpt-006"}}
        with patch("ollama.Client", return_value=mock_client), patch.object(
            crag_mod, "embed_query", return_value=None
        ), patch.object(
            crag_mod, "web_search", return_value=_mock_web_result()
        ), patch.object(
            self_rag_mod, "check_relevance", side_effect=_all_true
        ), patch.object(
            self_rag_mod, "check_isrel", side_effect=_all_true
        ), patch.object(
            self_rag_mod, "check_issup", side_effect=_all_true
        ):
            final = compiled.invoke(
                {"document_path": sample_pdf_path}, config=thread_cfg
            )

        assert final.get("current_node") == "self_rag_validation"
        # Verify checkpointed state is retrievable
        saved = compiled.get_state(thread_cfg)
        assert saved is not None
