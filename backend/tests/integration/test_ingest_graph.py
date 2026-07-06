"""
Integration tests: IngestAgent wired into the full LangGraph graph.

These tests invoke the compiled graph end-to-end and verify:
  - That the graph runs IngestAgent and reaches END with populated state.
  - That ingest_error short-circuits the pipeline correctly.
  - That LangGraph checkpointing with SqliteSaver works with our state schema.

Note: ollama.Client is mocked so no running Ollama instance is needed and
the LLM timeout fallback (120s) is not hit in CI.

Run: python -m pytest tests/integration/test_ingest_graph.py -v
"""

import json
from unittest.mock import MagicMock, patch

import pytest
from app.graph.builder import build_graph


def _llm_response(text="Test clause."):
    return {
        "message": {
            "content": json.dumps(
                {
                    "clauses": [
                        {"text": text, "section_number": None, "clause_type": None}
                    ]
                }
            )
        }
    }


def test_graph_ingest_success_to_end(sample_pdf_path):
    """Graph runs IngestAgent → ClauseSplitterAgent on valid PDF; reaches END."""
    graph = build_graph()
    initial_state = {"document_path": sample_pdf_path}

    import app.graph.nodes.crag_retrieval_agent as crag_mod
    import app.graph.nodes.self_rag_validation_agent as self_rag_mod
    from app.graph.nodes.retrievers import RetrievalResult

    mock_client = MagicMock()
    mock_client.chat.return_value = _llm_response(text="Test clause. " * 50)
    with patch("ollama.Client", return_value=mock_client), \
         patch.object(crag_mod, "embed_query", return_value=None), \
         patch.object(crag_mod, "web_search",
                      return_value=RetrievalResult(snippets=[], top_score=None)), \
         patch.object(self_rag_mod, "check_relevance", return_value=True), \
         patch.object(self_rag_mod, "check_isrel", return_value=True), \
         patch.object(self_rag_mod, "check_issup", return_value=True):
        final_state = graph.invoke(initial_state)

    assert final_state["ingest_error"] is None
    assert len(final_state["extracted_text"]) >= 200
    # current_node is "redline" or "skip_redline" — Node 6 is the terminal after feature-008
    assert final_state["current_node"] in ("redline", "skip_redline")
    assert final_state["document_path"] == sample_pdf_path
    assert final_state["original_filename"] == "sample.pdf"


def test_graph_ingest_error_short_circuits(unsupported_txt_path):
    """Graph runs IngestAgent on unsupported format and short-circuits to END.

    The graph must not crash; final state contains the error and empty text.
    """
    graph = build_graph()
    initial_state = {"document_path": unsupported_txt_path}

    final_state = graph.invoke(initial_state)

    assert final_state["ingest_error"] is not None
    assert final_state["ingest_error"]["error_type"] == "unsupported_format"
    assert final_state["extracted_text"] == ""


def test_graph_checkpointing(sample_pdf_path, tmp_path):
    """State is checkpointed after IngestAgent completes using SqliteSaver."""
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

    db_path = str(tmp_path / "checkpoints.db")

    with SqliteSaver.from_conn_string(db_path) as checkpointer:
        # Recompile graph with checkpointer attached
        g = StateGraph(ContractState)
        g.add_node("ingest_agent", ingest_agent)

        def route_after_ingest(state):
            if state.get("ingest_error"):
                return "end"
            return "clause_splitter"

        g.add_conditional_edges(
            "ingest_agent",
            route_after_ingest,
            {"end": END, "clause_splitter": END},
        )
        g.set_entry_point("ingest_agent")
        compiled = g.compile(checkpointer=checkpointer)

        config = {"configurable": {"thread_id": "integration-test-thread-1"}}
        initial_state = {"document_path": sample_pdf_path}

        final_state = compiled.invoke(initial_state, config=config)

        # Verify the pipeline ran successfully
        assert final_state["ingest_error"] is None
        assert len(final_state["extracted_text"]) >= 200

        # Verify a checkpoint was persisted
        checkpoint = checkpointer.get(config)
        assert checkpoint is not None
