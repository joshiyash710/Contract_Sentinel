"""
LangGraph StateGraph builder for the ContractSentinel pipeline.

Current scope (feature-004):
    - Node 1 (ingest_agent) with a conditional error-short-circuit edge.
    - Node 2 (clause_splitter) wired on the success path; routes to END
      temporarily until feature-005 adds Node 3 (CRAG retrieval).

Future nodes will call graph.add_node() and graph.add_edge() here as their
respective feature plans are implemented.

Note on return type annotation:
    The compiled graph type is CompiledStateGraph from langgraph.graph.state.
    Its exact import path has changed across LangGraph versions. To avoid
    ImportError on version drift, we intentionally do NOT annotate the return
    type of build_graph() and instead document it here.
"""

from langgraph.graph import StateGraph, END

from app.graph.state import ContractState
from app.graph.nodes.ingest_agent import ingest_agent
from app.graph.nodes.clause_splitter_agent import clause_splitter_agent


def build_graph():
    """Build and compile the ContractSentinel pipeline graph.

    Returns:
        CompiledStateGraph: the compiled LangGraph graph object.
        (Not annotated to avoid langgraph version drift on the import path.)
    """
    graph = StateGraph(ContractState)

    # ── Node 1: IngestAgent ────────────────────────────────────────────────────
    graph.add_node("ingest_agent", ingest_agent)

    def route_after_ingest(state: ContractState) -> str:
        """Short-circuit to END when ingest_error is set.

        This is an error-guard edge, NOT one of the two domain-logic
        conditional edges defined in constitution §2 (CRAG confidence
        routing and route_on_risk). This edge exists purely to prevent
        empty extracted_text from reaching ClauseSplitterAgent.
        """
        if state.get("ingest_error"):
            return "end"
        return "clause_splitter"

    graph.add_conditional_edges(
        "ingest_agent",
        route_after_ingest,
        {
            "end": END,
            "clause_splitter": "clause_splitter",
        },
    )

    # ── Node 2: ClauseSplitterAgent ────────────────────────────────────────────
    graph.add_node("clause_splitter", clause_splitter_agent)
    # Routes to END temporarily until feature-005 adds Node 3 (CRAG retrieval)
    graph.add_edge("clause_splitter", END)

    graph.set_entry_point("ingest_agent")
    return graph.compile()
