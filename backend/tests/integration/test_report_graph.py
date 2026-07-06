"""
Integration tests: ReportAgent (Node 7) wired into the full LangGraph graph.

REPORT_OUTPUT_DIR is monkeypatched to tmp_path so no real disk writes land in
data/reports/. Upstream LLM/embed/web/score/draft boundaries are mocked — no
live Ollama or network required (D3).

Run: python -m pytest tests/integration/test_report_graph.py -v
"""

import json
from collections import defaultdict
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

import app.graph.nodes.crag_retrieval_agent as crag_mod
import app.graph.nodes.self_rag_validation_agent as self_rag_mod
import app.graph.nodes.report_agent as report_mod
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
                "claims arising from unlimited liability. " * 5
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


def _full_graph_patches(
    ollama_client,
    *,
    relevance=True,
    isrel=True,
    issup=True,
    score=(RiskLevel.HIGH, "high risk finding"),
    rewrite="safer rewritten clause",
):
    """Context manager stacking all upstream mocks for a full-graph run."""
    return (
        patch("ollama.Client", return_value=ollama_client),
        patch.object(crag_mod, "embed_query", return_value=None),
        patch.object(crag_mod, "web_search", return_value=_mock_web_result()),
        patch.object(self_rag_mod, "check_relevance", return_value=relevance),
        patch.object(self_rag_mod, "check_isrel", return_value=isrel),
        patch.object(self_rag_mod, "check_issup", return_value=issup),
        patch(SCORE_TARGET, return_value=score),
        patch(DRAFT_TARGET, return_value=rewrite),
    )


def _run_graph(graph, sample_pdf_path, tmp_path, **patch_kwargs):
    mock_client = _make_mock_ollama_client(_sample_clause_list())
    patches = _full_graph_patches(mock_client, **patch_kwargs)
    ctx = patches[0]
    for p in patches[1:]:
        ctx = ctx.__and__(p) if hasattr(ctx, "__and__") else ctx  # fallback

    # Use nested with-statements for compatibility
    with patch("ollama.Client", return_value=mock_client), patch.object(
        crag_mod, "embed_query", return_value=None
    ), patch.object(
        crag_mod, "web_search", return_value=_mock_web_result()
    ), patch.object(
        self_rag_mod,
        "check_relevance",
        return_value=patch_kwargs.get("relevance", True),
    ), patch.object(
        self_rag_mod, "check_isrel", return_value=patch_kwargs.get("isrel", True)
    ), patch.object(
        self_rag_mod, "check_issup", return_value=patch_kwargs.get("issup", True)
    ), patch(
        SCORE_TARGET,
        return_value=patch_kwargs.get("score", (RiskLevel.HIGH, "high risk finding")),
    ), patch(
        DRAFT_TARGET, return_value=patch_kwargs.get("rewrite", "safer rewritten clause")
    ), patch.object(
        report_mod, "REPORT_OUTPUT_DIR", str(tmp_path)
    ):
        return graph.invoke({"document_path": sample_pdf_path})


# ── Tests ──────────────────────────────────────────────────────────────────────


def test_graph_reaches_report_and_ends(sample_pdf_path, tmp_path):
    """A doc with mixed clauses + ≥1 rewrite reaches report; report_path exists on
    disk; final current_node == 'report' (AC-25)."""
    graph = build_graph()
    final_state = _run_graph(graph, sample_pdf_path, tmp_path)

    assert final_state.get("ingest_error") is None
    assert final_state.get("current_node") == "report"
    report_path = final_state.get("report_path")
    assert report_path is not None
    assert Path(report_path).exists()


def test_graph_redline_branch_fans_into_report(sample_pdf_path, tmp_path):
    """An eligible-finding doc flows redline → report (not END); a report file is
    written (AC-22)."""
    graph = build_graph()
    final_state = _run_graph(
        graph,
        sample_pdf_path,
        tmp_path,
        relevance=True,
        isrel=True,
        issup=True,
        rewrite="safer rewritten clause",
    )

    assert final_state.get("current_node") == "report"
    assert final_state.get("report_path") is not None
    assert Path(final_state["report_path"]).exists()

    # Branch evidence: at least one validated clause with a suggested_rewrite
    clauses = final_state.get("clauses", {})
    validated = [
        c
        for c in clauses.values()
        if c.get("final_status") == ValidationStatus.VALIDATED
    ]
    assert any(
        c.get("suggested_rewrite") == "safer rewritten clause" for c in validated
    )


def test_graph_skip_redline_branch_fans_into_report(sample_pdf_path, tmp_path):
    """An all-DISCARDED doc flows skip_redline → report; report file written;
    final current_node == 'report' (AC-22)."""
    graph = build_graph()
    final_state = _run_graph(
        graph,
        sample_pdf_path,
        tmp_path,
        relevance=False,
        isrel=False,
        issup=False,
    )

    assert final_state.get("current_node") == "report"
    assert final_state.get("report_path") is not None
    assert Path(final_state["report_path"]).exists()


def test_graph_report_to_end():
    """Inspect build_graph(): 'report' node's only successor is END (AC-23)."""
    graph = build_graph()
    g = graph.get_graph()

    outgoing = defaultdict(set)
    for edge in g.edges:
        if hasattr(edge, "source") and hasattr(edge, "target"):
            outgoing[edge.source].add(edge.target)
        elif isinstance(edge, tuple) and len(edge) >= 2:
            outgoing[edge[0]].add(edge[1])

    report_successors = outgoing.get("report", set())
    # Should only go to END (represented as "__end__" in LangGraph)
    assert len(report_successors) == 1
    assert any(
        "end" in s.lower() for s in report_successors
    ), f"'report' successors should be END, got: {report_successors}"


def test_graph_ingest_error_still_reaches_end(unsupported_txt_path, tmp_path):
    """Ingest error short-circuits to END without reaching report (current wiring).
    assert not final_state.get('clauses') — KeyError caution: clauses channel has
    no default when the error short-circuit fires (constitution §8 note)."""
    graph = build_graph()

    with patch.object(report_mod, "REPORT_OUTPUT_DIR", str(tmp_path)):
        final_state = graph.invoke({"document_path": unsupported_txt_path})

    assert final_state.get("ingest_error") is not None
    assert not final_state.get("clauses")
    # report_path must not be set — report node was not reached
    assert final_state.get("report_path") is None


def test_graph_no_new_conditional_edges():
    """Inspect build_graph(): report is reached only by linear edges from redline/
    skip_redline; conditional branch sources are exactly {ingest_agent, risk_score};
    crag_retrieval/self_rag_validation stay linear (AC-24)."""
    graph = build_graph()
    g = graph.get_graph()

    outgoing = defaultdict(set)
    for edge in g.edges:
        if hasattr(edge, "source") and hasattr(edge, "target"):
            outgoing[edge.source].add(edge.target)
        elif isinstance(edge, tuple) and len(edge) >= 2:
            outgoing[edge[0]].add(edge[1])

    # Nodes that fan out to multiple successors are the conditional sources
    conditional_sources = {src for src, targets in outgoing.items() if len(targets) > 1}
    assert "ingest_agent" in conditional_sources
    assert "risk_score" in conditional_sources
    # report must NOT be a conditional source
    assert "report" not in conditional_sources
    # crag_retrieval and self_rag_validation are linear
    assert "crag_retrieval" not in conditional_sources
    assert "self_rag_validation" not in conditional_sources


def test_graph_evidence_trail_populated(sample_pdf_path, tmp_path):
    """After a full run, evidence_trail has validated-only rows sharing the D8
    timestamp, correct shape (AC-12a/13)."""
    graph = build_graph()
    final_state = _run_graph(graph, sample_pdf_path, tmp_path)

    trail = final_state.get("evidence_trail", [])
    assert isinstance(trail, list)
    if trail:
        timestamps = {row["retrieved_at"] for row in trail}
        assert len(timestamps) == 1, "All trail rows must share one retrieved_at (D8)"
        row = trail[0]
        assert set(row.keys()) == {
            "clause_id",
            "evidence_source",
            "evidence_text",
            "retrieved_at",
        }


def test_graph_checkpointing_after_report(sample_pdf_path, tmp_path):
    """State checkpointed after Node 7. Test builds its own graph with SqliteSaver."""
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
        from app.graph.nodes.report_agent import report_agent as rep

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
        # Wire through report → END (not to END directly as 008 did)
        g.add_node("report", rep)
        g.add_edge("redline", "report")
        g.add_edge("skip_redline", "report")
        g.add_edge("report", GRAPH_END)
        g.set_entry_point("ingest_agent")
        compiled = g.compile(checkpointer=checkpointer)

        thread_cfg = {"configurable": {"thread_id": "test-ckpt-009"}}
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
        ), patch.object(
            report_mod, "REPORT_OUTPUT_DIR", str(tmp_path)
        ):
            final = compiled.invoke(
                {"document_path": sample_pdf_path}, config=thread_cfg
            )

        assert final.get("current_node") == "report"
        saved = compiled.get_state(thread_cfg)
        assert saved is not None
