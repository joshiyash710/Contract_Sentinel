"""
Unit tests for app.graph.nodes.retrievers.kb_retriever.

Uses a tiny in-memory FAISS index built from known unit vectors so cosines are
exact and routing is deterministic. Monkeypatches _resolve_backend_path so the
retriever hits temp files instead of the real KB.

Run: python -m pytest tests/unit/test_kb_retriever.py -v
"""

import json
import math
from pathlib import Path
from unittest.mock import patch

import faiss
import numpy as np
import pytest

import app.graph.nodes.retrievers.kb_retriever as kb_retriever_mod
from app.graph.nodes.retrievers.kb_retriever import load_kb, search_kb
from app.config import CRAG_TOP_K

# ── Fixture helpers ────────────────────────────────────────────────────────────


def _make_unit_vec(*components) -> np.ndarray:
    """Return a float32 L2-normalized vector from given components."""
    v = np.array(components, dtype=np.float32)
    return v / np.linalg.norm(v)


def _write_kb(tmp_path: Path, vectors: list, meta: list) -> tuple:
    """Write a tiny IndexFlatIP + JSONL sidecar to tmp_path. Returns (index_path, meta_path)."""
    assert len(vectors) == len(meta)
    dim = len(vectors[0]) if vectors else 1
    index = faiss.IndexFlatIP(dim)
    if vectors:
        matrix = np.stack(vectors).astype(np.float32)
        index.add(matrix)
    index_path = tmp_path / "clauses.faiss"
    meta_path = tmp_path / "clauses_meta.jsonl"
    faiss.write_index(index, str(index_path))
    with open(meta_path, "w") as f:
        for row in meta:
            f.write(json.dumps(row) + "\n")
    return index_path, meta_path


def _redirect_kb(monkeypatch, index_path: Path, meta_path: Path):
    """Monkeypatch _resolve_backend_path to point at tmp paths."""
    import app.config as cfg

    def fake_resolve(rel: str) -> Path:
        if rel == cfg.CRAG_KB_INDEX_PATH:
            return index_path
        if rel == cfg.CRAG_KB_METADATA_PATH:
            return meta_path
        raise ValueError(f"Unexpected path: {rel}")

    monkeypatch.setattr(kb_retriever_mod, "_resolve_backend_path", fake_resolve)


@pytest.fixture(autouse=True)
def reset_kb_cache():
    """Clear module-level KB cache before/after each test to prevent leakage."""
    kb_retriever_mod._KB_CACHE = None
    yield
    kb_retriever_mod._KB_CACHE = None


# ── Tests ──────────────────────────────────────────────────────────────────────


def test_search_returns_top1_cosine(tmp_path, monkeypatch):
    """top_score == max cosine among returned neighbors, clamped at 0."""
    q = _make_unit_vec(1.0, 0.0)
    k1 = _make_unit_vec(0.8, 0.6)  # cosine with q = 0.8
    k2 = _make_unit_vec(0.6, 0.8)  # cosine with q = 0.6
    meta = [
        {"snippet_text": "text A", "source_reference": "src A"},
        {"snippet_text": "text B", "source_reference": "src B"},
    ]
    idx_p, meta_p = _write_kb(tmp_path, [k1, k2], meta)
    _redirect_kb(monkeypatch, idx_p, meta_p)

    kb = load_kb()
    result = search_kb(kb, q, top_k=2)

    assert result.top_score == pytest.approx(0.8, abs=1e-5)


def test_search_snippet_shape(tmp_path, monkeypatch):
    """Each snippet has exactly snippet_text + source_reference (AC-6)."""
    v = _make_unit_vec(1.0, 0.0)
    meta = [{"snippet_text": "clause text", "source_reference": "ref://1"}]
    idx_p, meta_p = _write_kb(tmp_path, [v], meta)
    _redirect_kb(monkeypatch, idx_p, meta_p)

    kb = load_kb()
    result = search_kb(kb, v, top_k=1)

    assert len(result.snippets) == 1
    s = result.snippets[0]
    assert set(s.keys()) == {"snippet_text", "source_reference"}
    assert s["snippet_text"] == "clause text"
    assert s["source_reference"] == "ref://1"


def test_search_cosine_exactly_threshold_routes_local(tmp_path, monkeypatch):
    """A neighbor at cosine == 0.73 yields top_score == 0.73 (feeds AC-4)."""
    threshold = 0.73
    # Build kb_vec whose cosine with [1,0] is exactly 0.73
    # kb = [0.73, sqrt(1 - 0.73^2)]; query = [1, 0]
    sin_val = math.sqrt(1 - threshold**2)
    kb_vec = np.array([threshold, sin_val], dtype=np.float32)
    query_vec = np.array([1.0, 0.0], dtype=np.float32)

    meta = [{"snippet_text": "threshold clause", "source_reference": "ref://threshold"}]
    idx_p, meta_p = _write_kb(tmp_path, [kb_vec], meta)
    _redirect_kb(monkeypatch, idx_p, meta_p)

    kb = load_kb()
    result = search_kb(kb, query_vec, top_k=1)

    assert result.top_score == pytest.approx(threshold, abs=1e-5)


def test_search_fewer_than_topk(tmp_path, monkeypatch):
    """Index with fewer vectors than top_k → returns all available, no crash."""
    v = _make_unit_vec(1.0, 0.0)
    meta = [{"snippet_text": "only one", "source_reference": "ref://1"}]
    idx_p, meta_p = _write_kb(tmp_path, [v], meta)
    _redirect_kb(monkeypatch, idx_p, meta_p)

    kb = load_kb()
    result = search_kb(kb, v, top_k=CRAG_TOP_K)  # CRAG_TOP_K=5 but only 1 vector

    assert len(result.snippets) == 1
    assert result.top_score is not None


def test_search_zero_vectors_score_zero(tmp_path, monkeypatch):
    """Empty index → top_score == 0.0, snippets == [] (spec §4.6)."""
    dim = 2
    index = faiss.IndexFlatIP(dim)
    idx_p = tmp_path / "empty.faiss"
    meta_p = tmp_path / "empty_meta.jsonl"
    faiss.write_index(index, str(idx_p))
    meta_p.write_text("")

    _redirect_kb(monkeypatch, idx_p, meta_p)

    kb = load_kb()
    q = _make_unit_vec(1.0, 0.0)
    result = search_kb(kb, q, top_k=3)

    assert result.top_score == 0.0
    assert result.snippets == []


def test_load_kb_missing_index_returns_none(tmp_path, monkeypatch, caplog):
    """Missing index file → None, single warning (AC-14)."""
    idx_p = tmp_path / "nonexistent.faiss"
    meta_p = tmp_path / "nonexistent_meta.jsonl"
    _redirect_kb(monkeypatch, idx_p, meta_p)

    with caplog.at_level("WARNING"):
        kb = load_kb()

    assert kb is None
    warning_count = sum(1 for r in caplog.records if r.levelno >= 30)
    assert warning_count >= 1


def test_load_kb_row_count_mismatch_returns_none(tmp_path, monkeypatch, caplog):
    """len(meta) != index.ntotal → treated as corrupt → None."""
    v = _make_unit_vec(1.0, 0.0)
    meta = [
        {"snippet_text": "row 0", "source_reference": "ref://0"},
        {"snippet_text": "row 1", "source_reference": "ref://1"},  # one extra
    ]
    # Write index with 1 vector but sidecar with 2 rows
    dim = 2
    index = faiss.IndexFlatIP(dim)
    index.add(v.reshape(1, -1))
    idx_p = tmp_path / "mismatch.faiss"
    meta_p = tmp_path / "mismatch_meta.jsonl"
    faiss.write_index(index, str(idx_p))
    with open(meta_p, "w") as f:
        for row in meta:
            f.write(json.dumps(row) + "\n")
    _redirect_kb(monkeypatch, idx_p, meta_p)

    with caplog.at_level("WARNING"):
        kb = load_kb()

    assert kb is None


def test_load_kb_cached(tmp_path, monkeypatch):
    """Second load_kb() call does not re-read the index file (caching)."""
    v = _make_unit_vec(1.0, 0.0)
    meta = [{"snippet_text": "cached", "source_reference": "ref://c"}]
    idx_p, meta_p = _write_kb(tmp_path, [v], meta)
    _redirect_kb(monkeypatch, idx_p, meta_p)

    with patch(
        "app.graph.nodes.retrievers.kb_retriever.faiss.read_index",
        wraps=faiss.read_index,
    ) as mock_read:
        kb1 = load_kb()
        kb2 = load_kb()

    assert kb1 is kb2
    assert mock_read.call_count == 1


def test_path_resolved_relative_to_backend(monkeypatch):
    """Configured relative paths resolve against backend/ dir, not raw CWD."""
    import app.config as cfg
    from pathlib import Path

    resolved = kb_retriever_mod._resolve_backend_path(cfg.CRAG_KB_INDEX_PATH)
    backend_dir = Path(cfg.__file__).resolve().parent.parent
    expected = backend_dir / cfg.CRAG_KB_INDEX_PATH
    assert resolved == expected
