"""Feature 061 — CRAG read-side augmentation with the per-user KB. AC-1/AC-4/AC-5/AC-6.

No Ollama/FAISS: load_kb/load_user_kb/search_kb/embed_query are mocked. The base KB and the user KB are
distinct sentinel handles; the fake search_kb returns a controlled RetrievalResult per handle.
"""

import numpy as np
import pytest

import app.graph.nodes.crag_retrieval_agent as crag_mod
from app.graph.nodes.retrievers import RetrievalResult, make_snippet
from app.graph.state import RetrievalPath

_BASE = object()
_USER = object()


def _state():
    return {
        "document_id": "d1",
        "clauses": {"c1": {"text": "a termination clause", "position": 0, "clause_type": None}},
    }


@pytest.fixture
def mocked(monkeypatch):
    monkeypatch.setattr(crag_mod, "CRAG_USER_KB_ENABLED", True)
    monkeypatch.setattr(crag_mod, "embed_query", lambda *a, **k: np.ones(8, dtype=np.float32))
    monkeypatch.setattr(crag_mod, "load_kb", lambda: _BASE)
    monkeypatch.setattr(crag_mod, "web_search", lambda *a, **k: RetrievalResult(snippets=[], top_score=None))
    return monkeypatch


def _set_scores(monkeypatch, base_score, user_score):
    base_res = RetrievalResult(snippets=[make_snippet("base evidence", "base ref")], top_score=base_score)
    user_res = RetrievalResult(snippets=[make_snippet("user evidence", "user ref")], top_score=user_score)

    def fake_search(handle, vec, k):
        return base_res if handle is _BASE else user_res

    monkeypatch.setattr(crag_mod, "search_kb", fake_search)


def test_user_kb_raises_local_hit_above_base(mocked):
    # AC-5: base < 0.73 but the user KB ≥ 0.73 → max score routes LOCAL_KB and includes the user snippet.
    mocked.setattr(crag_mod, "_run_user_id", lambda: "u1")
    mocked.setattr(crag_mod, "load_user_kb", lambda uid: _USER if uid == "u1" else None)
    _set_scores(mocked, base_score=0.50, user_score=0.80)

    out = crag_mod.crag_retrieval_agent(_state())["clauses"]["c1"]
    assert out["confidence_score"] == pytest.approx(0.80)
    assert out["path_taken"] == RetrievalPath.LOCAL_KB
    texts = [s["snippet_text"] for s in out["evidence_snippets"]]
    assert "user evidence" in texts


def test_negative_control_unrelated_stays_web(mocked):
    # Evaluation guardrail: an unrelated clause that scores low against BOTH KBs still routes WEB_FALLBACK.
    mocked.setattr(crag_mod, "_run_user_id", lambda: "u1")
    mocked.setattr(crag_mod, "load_user_kb", lambda uid: _USER)
    _set_scores(mocked, base_score=0.50, user_score=0.40)

    out = crag_mod.crag_retrieval_agent(_state())["clauses"]["c1"]
    assert out["path_taken"] == RetrievalPath.WEB_FALLBACK


def test_flag_off_searches_base_only(mocked):
    # AC-1: flag off → the user KB is never consulted (load_user_kb must not be called).
    mocked.setattr(crag_mod, "CRAG_USER_KB_ENABLED", False)
    _set_scores(mocked, base_score=0.90, user_score=0.95)

    def _boom(uid):
        raise AssertionError("load_user_kb must not be called when the flag is off")

    mocked.setattr(crag_mod, "load_user_kb", _boom)
    out = crag_mod.crag_retrieval_agent(_state())["clauses"]["c1"]
    assert out["confidence_score"] == pytest.approx(0.90)  # base only
    assert out["path_taken"] == RetrievalPath.LOCAL_KB


def test_no_runnable_context_guarded(mocked):
    # AC-6: a direct node call (no runnable context) → _run_user_id resolves None (get_config RuntimeError),
    # so the user KB is never consulted and the node behaves base-only, no throw.
    _set_scores(mocked, base_score=0.90, user_score=0.95)

    def _boom(uid):
        raise AssertionError("load_user_kb must not be called without a user_id")

    mocked.setattr(crag_mod, "load_user_kb", _boom)
    out = crag_mod.crag_retrieval_agent(_state())["clauses"]["c1"]
    assert out["path_taken"] == RetrievalPath.LOCAL_KB
    assert out["confidence_score"] == pytest.approx(0.90)
