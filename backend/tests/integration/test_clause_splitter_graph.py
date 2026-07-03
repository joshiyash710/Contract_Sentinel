"""
Integration tests: IngestAgent → ClauseSplitterAgent → CRAGRetrievalAgent
wired in the LangGraph graph (feature-005 updated).

These tests invoke the compiled graph end-to-end and verify:
  - Graph runs all three nodes successfully on a valid PDF.
  - Error short-circuit still works (ingest_error bypasses both ClauseSplitter
    and CRAG).
  - LLM timeout/failure causes regex-only fallback; CRAG still runs after.
  - State is checkpointed after ClauseSplitterAgent completes.

ollama.Client is mocked — no running Ollama instance required.
CRAG embed_query and web_search are also mocked — no Ollama embedding / network.

Run: python -m pytest tests/integration/test_clause_splitter_graph.py -v
"""

import json
from unittest.mock import MagicMock, patch

import httpx
import pytest
from app.graph.builder import build_graph
import app.graph.nodes.crag_retrieval_agent as crag_mod
from app.graph.nodes.retrievers import RetrievalResult


def _empty_web():
    return RetrievalResult(snippets=[], top_score=None)


def _make_llm_response(clauses: list) -> dict:
    """Build a minimal valid Ollama chat response."""
    return {"message": {"content": json.dumps({"clauses": clauses})}}


def _make_mock_client(clauses: list) -> MagicMock:
    """Return a mock ollama.Client whose .chat() returns the given clauses response."""
    client = MagicMock()
    client.chat.return_value = _make_llm_response(clauses)
    return client


def test_graph_ingest_then_clause_splitter_success(sample_pdf_path):
    """Graph runs IngestAgent → ClauseSplitterAgent on valid PDF; clauses dict populated."""
    # Use enough text so the preservation guard doesn't force a regex fallback
    mock_client = _make_mock_client(
        [
            {
                "text": "Sample clause text from the PDF document. " * 15,
                "section_number": None,
                "clause_type": "general",
            },
        ]
    )
    graph = build_graph()

    with patch("ollama.Client", return_value=mock_client), \
         patch.object(crag_mod, "embed_query", return_value=None), \
         patch.object(crag_mod, "web_search", return_value=_empty_web()):
        final_state = graph.invoke({"document_path": sample_pdf_path})

    assert final_state["ingest_error"] is None
    # current_node is now "crag_retrieval" — CRAG is the terminal node (feature-005)
    assert final_state["current_node"] == "crag_retrieval"
    assert "clauses" in final_state
    assert len(final_state["clauses"]) >= 1

    # Verify required fields on every clause (ClauseSplitter fields still present)
    for clause_id, clause in final_state["clauses"].items():
        assert "text" in clause, f"{clause_id} missing 'text'"
        assert "position" in clause, f"{clause_id} missing 'position'"
        assert "section_number" in clause, f"{clause_id} missing 'section_number'"
        assert "clause_type" in clause, f"{clause_id} missing 'clause_type'"


def test_graph_ingest_error_skips_clause_splitter(unsupported_txt_path):
    """IngestAgent error short-circuits to END; ClauseSplitterAgent not reached."""
    graph = build_graph()

    # Patch the node itself: if the router misfires and the node is called, fail loudly.
    # Patching ollama.Client is insufficient because the node bails early on ingest_error
    # before ever reaching refine_with_llm.
    with patch(
        "app.graph.nodes.clause_splitter_agent.clause_splitter_agent",
        side_effect=AssertionError("ClauseSplitterAgent reached despite ingest error"),
    ):
        final_state = graph.invoke({"document_path": unsupported_txt_path})

    assert final_state["ingest_error"] is not None
    assert final_state["ingest_error"]["error_type"] == "unsupported_format"
    # ClauseSplitter was never reached, so clauses channel is absent or empty
    assert not final_state.get("clauses")


def test_graph_clause_splitter_llm_fallback(sample_pdf_path):
    """LLM call failing (httpx timeout) → regex-only fallback; graph completes."""
    mock_client = MagicMock()
    mock_client.chat.side_effect = httpx.ReadTimeout("Connection timed out")
    graph = build_graph()

    with patch("ollama.Client", return_value=mock_client), \
         patch.object(crag_mod, "embed_query", return_value=None), \
         patch.object(crag_mod, "web_search", return_value=_empty_web()):
        final_state = graph.invoke({"document_path": sample_pdf_path})

    # Graph must complete without crashing; CRAG is now the terminal node
    assert final_state["current_node"] == "crag_retrieval"
    # Regex-only fallback still produces clauses (PDF has extractable text)
    assert "clauses" in final_state
    assert len(final_state["clauses"]) >= 1


def test_graph_checkpointing_after_clause_splitter(sample_pdf_path, tmp_path):
    """State is checkpointed after ClauseSplitterAgent completes."""
    try:
        from langgraph.checkpoint.sqlite import SqliteSaver
    except ImportError:
        pytest.skip(
            "langgraph-checkpoint-sqlite not available or API changed "
            "— verify import path"
        )
    from langgraph.graph import StateGraph, END
    from app.graph.state import ContractState
    from app.graph.nodes.ingest_agent import ingest_agent
    from app.graph.nodes.clause_splitter_agent import clause_splitter_agent

    db_path = str(tmp_path / "checkpoints_004.db")
    mock_client = _make_mock_client(
        [
            {
                "text": "Clause from checkpointing test. " * 20,
                "section_number": None,
                "clause_type": None,
            },
        ]
    )

    with SqliteSaver.from_conn_string(db_path) as checkpointer:
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
        g.add_edge("clause_splitter", END)
        g.set_entry_point("ingest_agent")
        compiled = g.compile(checkpointer=checkpointer)

        config = {"configurable": {"thread_id": "integration-004-thread-1"}}

        with patch("ollama.Client", return_value=mock_client):
            final_state = compiled.invoke(
                {"document_path": sample_pdf_path}, config=config
            )

        assert final_state["ingest_error"] is None
        assert final_state["current_node"] == "clause_splitter"
        assert "clauses" in final_state

        checkpoint = checkpointer.get(config)
        assert checkpoint is not None
