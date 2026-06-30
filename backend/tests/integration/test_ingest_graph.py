"""
Integration tests: IngestAgent wired into the full LangGraph graph.

These tests invoke the compiled graph end-to-end and verify:
  - That the graph runs IngestAgent and reaches END with correct state.
  - That ingest_error short-circuits the pipeline correctly.
  - That LangGraph checkpointing with SqliteSaver works with our state schema.

Run: python -m pytest tests/integration/test_ingest_graph.py -v
"""

from app.graph.builder import build_graph


def test_graph_ingest_success_to_end(sample_pdf_path):
    """Graph runs IngestAgent on valid PDF and reaches END with populated state."""
    graph = build_graph()
    initial_state = {"document_path": sample_pdf_path}

    final_state = graph.invoke(initial_state)

    assert final_state["ingest_error"] is None
    assert len(final_state["extracted_text"]) >= 200
    assert final_state["current_node"] == "ingest_agent"
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
    from langgraph.checkpoint.sqlite import SqliteSaver
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
