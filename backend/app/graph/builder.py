"""
LangGraph StateGraph builder for the ContractSentinel pipeline.

Current scope (feature-009):
    - Node 1 (ingest_agent) with a conditional error-short-circuit edge.
    - Node 2 (clause_splitter) wired on the success path.
    - Node 3 (crag_retrieval) wired after clause_splitter.
    - Node 4 (self_rag_validation) wired after crag_retrieval.
    - Node 5 (risk_score) wired after self_rag_validation.
    - Node 6 (route_on_risk conditional edge → redline / skip_redline).
    - Node 7 (report) fan-in from redline + skip_redline → END (terminal node).

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
from app.graph.nodes.crag_retrieval_agent import crag_retrieval_agent
from app.graph.nodes.self_rag_validation_agent import self_rag_validation_agent
from app.graph.nodes.risk_score_agent import risk_score_agent
from app.graph.nodes.redline_agent import route_on_risk, redline_agent, skip_redline
from app.graph.nodes.report_agent import report_agent


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
    graph.add_edge("clause_splitter", "crag_retrieval")  # was END temporarily

    # ── Node 3: CRAGRetrievalAgent ─────────────────────────────────────────────
    # Constitution §2 interpretation (spec §7.2): CRAG's confidence-based routing
    # is one of the two permitted conditional edges, but it is realized as INTERNAL
    # Python branching inside crag_retrieval_agent (a per-clause if/else loop),
    # NOT as a graph-level add_conditional_edges. A graph-level conditional edge
    # routes the whole ContractState to one successor, but CRAG routes per clause,
    # and all clauses live in one state object. A Send-API map-reduce subgraph was
    # rejected for Phase 1 as unnecessary complexity (spec §7.2). The node name
    # "crag_retrieval" matches the pinned current_node value in the node itself so
    # state-key identity never drifts from the graph node name.
    graph.add_node("crag_retrieval", crag_retrieval_agent)
    graph.add_edge("crag_retrieval", "self_rag_validation")  # was END temporarily

    # ── Node 4: SelfRAGValidationAgent ────────────────────────────────────────
    # Constitution §2 note: Self-RAG's outgoing edge is a PLAIN LINEAR add_edge,
    # deliberately NOT an add_conditional_edges. The two permitted conditional
    # edges are CRAG's confidence routing (Node 3, implemented as internal
    # per-clause branching) and route_on_risk (Node 6, future). Discarded findings
    # stay in ContractState marked DISCARDED and flow along this linear edge;
    # downstream nodes filter on final_status. The node name "self_rag_validation"
    # matches the pinned current_node value (spec §2) so state-key identity never
    # drifts from the graph node name (constitution §8).
    graph.add_node("self_rag_validation", self_rag_validation_agent)
    graph.add_edge("self_rag_validation", "risk_score")  # was END until feature-007

    # ── Node 5: RiskScoreAgent ─────────────────────────────────────────────────
    # Constitution §2 note: RiskScore's outgoing edge feeds the route_on_risk
    # conditional edge (Node 6) below. RiskScore assigns severity; routing is
    # Node 6's job. The node name "risk_score" matches the pinned current_node
    # value (spec §2) so state-key identity never drifts from the graph node
    # name (constitution §8).
    graph.add_node("risk_score", risk_score_agent)

    # ── Node 6: route_on_risk (conditional edge) → RedlineAgent / SkipRedline ──
    # Constitution §2: this is the SECOND of the two permitted domain conditional
    # edges (the first is CRAG's confidence routing, Node 3, realized as internal
    # per-clause branching). Unlike CRAG, route_on_risk is a DOCUMENT-LEVEL decision
    # that routes the whole ContractState to one successor, so it IS a genuine
    # graph-level add_conditional_edges (spec §7.1). RedlineAgent does per-clause
    # filtering internally via the same is_redline_eligible predicate route_on_risk
    # uses (spec §7.2). The node names "redline" / "skip_redline" match the pinned
    # current_node values (spec §2) so state-key identity never drifts from the
    # graph node name (constitution §8).
    graph.add_node("redline", redline_agent)
    graph.add_node("skip_redline", skip_redline)
    graph.add_conditional_edges(
        "risk_score",
        route_on_risk,
        {"redline": "redline", "skip_redline": "skip_redline"},
    )
    # ── Node 7: ReportAgent (terminal assembly node) ──────────────────────────
    # Constitution §2 item 7. Both Node-6 branches converge here via plain LINEAR
    # add_edge (fan-in) — NOT a conditional edge — so the graph still has exactly the
    # two permitted domain conditional edges (CRAG internal, route_on_risk). ReportAgent
    # reads the fully-populated ContractState, writes the report file(s), and returns
    # report_path + evidence_trail (spec §7.1). The node name "report" matches the pinned
    # current_node value (spec §7.5) so state-key identity never drifts from the graph
    # node name (constitution §8).
    graph.add_node("report", report_agent)
    graph.add_edge("redline", "report")  # was END (feature-008 placeholder)
    graph.add_edge("skip_redline", "report")  # was END (feature-008 placeholder)
    graph.add_edge("report", END)

    graph.set_entry_point("ingest_agent")
    return graph.compile()
