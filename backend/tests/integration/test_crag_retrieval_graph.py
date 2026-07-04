"""
Integration tests: IngestAgent → ClauseSplitterAgent → CRAGRetrievalAgent
wired in the LangGraph graph.

Embedding and web calls are mocked (no live Ollama / no network).
The real built FAISS KB is used so the local path is exercised end-to-end.

Patch targets are on the NODE MODULE (app.graph.nodes.crag_retrieval_agent)
because crag_retrieval_agent.py does `from ...embeddings import embed_query`
and `from ...web_retriever import web_search`, binding those names into the
node module. Patching the retriever sub-modules directly would NOT intercept
the already-bound names and would silently hit real Ollama/DDG.

Run: python -m pytest tests/integration/test_crag_retrieval_graph.py -v
"""

import json
from unittest.mock import MagicMock, patch

import faiss
import pytest

import app.config as config
import app.graph.nodes.crag_retrieval_agent as crag_mod
import app.graph.nodes.self_rag_validation_agent as self_rag_mod
import app.graph.nodes.retrievers.kb_retriever as kb_mod
from app.graph.builder import build_graph
from app.graph.nodes.retrievers import RetrievalResult
from app.graph.nodes.retrievers.kb_retriever import _resolve_backend_path
from app.graph.state import RetrievalPath

# ── Shared fixtures / helpers ──────────────────────────────────────────────────


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
            "text": "The vendor shall provide services as described herein. " * 10,
            "section_number": "1.1",
            "clause_type": "general",
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


def test_graph_ingest_clause_crag_success(sample_pdf_path):
    """Node1→Node2→Node3 reaches END; every clause carries the three evidence fields."""
    mock_client = _make_mock_ollama_client(_sample_clause_list())
    graph = build_graph()

    with patch("ollama.Client", return_value=mock_client), \
         patch.object(crag_mod, "embed_query", return_value=None), \
         patch.object(crag_mod, "web_search", return_value=_mock_web_result()), \
         patch.object(self_rag_mod, "check_relevance", return_value=True), \
         patch.object(self_rag_mod, "check_isrel", return_value=True), \
         patch.object(self_rag_mod, "check_issup", return_value=True):
        final_state = graph.invoke({"document_path": sample_pdf_path})

    assert final_state["ingest_error"] is None
    assert final_state["current_node"] == "self_rag_validation"
    assert "clauses" in final_state
    assert len(final_state["clauses"]) >= 1

    for clause_id, clause in final_state["clauses"].items():
        assert "confidence_score" in clause, f"{clause_id} missing confidence_score"
        assert "path_taken" in clause, f"{clause_id} missing path_taken"
        assert "evidence_snippets" in clause, f"{clause_id} missing evidence_snippets"


def test_graph_ingest_error_skips_crag(unsupported_txt_path):
    """Ingest error short-circuits to END; CRAG not reached."""
    graph = build_graph()

    with patch.object(crag_mod, "embed_query") as mk_embed, patch.object(
        crag_mod, "web_search"
    ) as mk_web:
        final_state = graph.invoke({"document_path": unsupported_txt_path})

    assert final_state["ingest_error"] is not None
    # CRAG was never reached (ingest error short-circuits before clause_splitter)
    assert not final_state.get("clauses")
    mk_embed.assert_not_called()
    mk_web.assert_not_called()


def test_graph_crag_local_path_real_kb(sample_pdf_path):
    """A clause routes LOCAL_KB using the real 109-vector FAISS index.

    Deterministic fixture: we read row 0 back out of the real index via
    faiss.reconstruct(0). Its self-similarity is 1.0, guaranteed >= 0.73.
    """
    index_path = _resolve_backend_path(config.CRAG_KB_INDEX_PATH)
    meta_path = _resolve_backend_path(config.CRAG_KB_METADATA_PATH)

    if not index_path.exists() or not meta_path.exists():
        pytest.skip("Real FAISS KB not found — build it with scripts/build_kb.py first")

    # Read the real index and extract row 0 as the query vector (self-sim == 1.0)
    real_index = faiss.read_index(str(index_path))
    kb_vec0 = real_index.reconstruct(0)  # already L2-normalized

    # Read the expected source_reference for row 0
    with open(meta_path, "r", encoding="utf-8") as f:
        meta_row0 = json.loads(f.readline())

    mock_client = _make_mock_ollama_client(_sample_clause_list())
    graph = build_graph()

    with patch("ollama.Client", return_value=mock_client), patch.object(
        crag_mod, "embed_query", return_value=kb_vec0
    ), patch.object(crag_mod, "web_search", return_value=_mock_web_result()):
        final_state = graph.invoke({"document_path": sample_pdf_path})

    for clause_id, clause in final_state["clauses"].items():
        assert (
            clause["path_taken"] == RetrievalPath.LOCAL_KB
        ), f"{clause_id}: expected LOCAL_KB, got {clause['path_taken']}"
        sources = [s["source_reference"] for s in clause["evidence_snippets"]]
        assert (
            meta_row0["source_reference"] in sources
        ), f"Expected row-0 source_reference in snippets; got {sources}"


def test_graph_crag_web_fallback_on_low_confidence(sample_pdf_path):
    """A clause routes WEB_FALLBACK when embed_query returns a vector orthogonal
    to the KB (cosine clamps to 0.0, well below 0.73)."""
    index_path = _resolve_backend_path(config.CRAG_KB_INDEX_PATH)
    if not index_path.exists():
        pytest.skip("Real FAISS KB not found — build it with scripts/build_kb.py first")

    real_index = faiss.read_index(str(index_path))
    kb_vec0 = real_index.reconstruct(0)
    # -kb_vec0 has cosine ≤ 0 with every mostly-non-negative KB vector → max(0, .) = 0.0
    low_vec = -kb_vec0

    mock_client = _make_mock_ollama_client(_sample_clause_list())
    web_snippets = _mock_web_result(2)
    graph = build_graph()

    with patch("ollama.Client", return_value=mock_client), patch.object(
        crag_mod, "embed_query", return_value=low_vec
    ), patch.object(crag_mod, "web_search", return_value=web_snippets):
        final_state = graph.invoke({"document_path": sample_pdf_path})

    for clause_id, clause in final_state["clauses"].items():
        assert (
            clause["path_taken"] == RetrievalPath.WEB_FALLBACK
        ), f"{clause_id}: expected WEB_FALLBACK, got {clause['path_taken']}"
        assert clause["confidence_score"] == pytest.approx(0.0, abs=1e-5)


def test_graph_checkpointing_after_crag(sample_pdf_path, tmp_path):
    """State is checkpointed after CRAGRetrievalAgent completes."""
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

    db_path = str(tmp_path / "checkpoints_005.db")
    mock_client = _make_mock_ollama_client(_sample_clause_list())

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
        g.add_edge("clause_splitter", "crag_retrieval")
        g.add_node("crag_retrieval", crag_mod.crag_retrieval_agent)
        g.add_edge("crag_retrieval", END)
        g.set_entry_point("ingest_agent")
        compiled = g.compile(checkpointer=checkpointer)

        thread_cfg = {"configurable": {"thread_id": "integration-005-thread-1"}}

        with patch("ollama.Client", return_value=mock_client), patch.object(
            crag_mod, "embed_query", return_value=None
        ), patch.object(crag_mod, "web_search", return_value=_mock_web_result()):
            final_state = compiled.invoke(
                {"document_path": sample_pdf_path}, thread_cfg
            )

        assert final_state["current_node"] == "crag_retrieval"
        assert "clauses" in final_state

        checkpoint = checkpointer.get(thread_cfg)
        assert checkpoint is not None
