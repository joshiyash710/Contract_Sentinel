"""
Local FAISS clause knowledge-base retriever for CRAG (Node 3).

load_kb() loads and caches the index + metadata sidecar once per process.
search_kb() searches the cached KB with an L2-normalized query vector.

Path resolution (spec §6 anchor): config paths are resolved relative to
backend/ (computed as Path(config.__file__).parent.parent), not the raw CWD,
so the KB is found consistently whether launched from backend/ or elsewhere.
"""

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

import faiss
import numpy as np

import app.config as _config
from app.graph.nodes.retrievers import RetrievalResult, make_snippet

logger = logging.getLogger("contractsentinel.crag_retrieval.kb")

# Module-level cache: populated on first successful load_kb() call.
_KB_CACHE = None


@dataclass
class _LoadedKB:
    index: faiss.Index
    meta: List[dict]


def _resolve_backend_path(rel: str) -> Path:
    """Resolve a config-relative path against the backend/ directory."""
    backend_dir = Path(_config.__file__).resolve().parent.parent
    return backend_dir / rel


def load_kb() -> Optional[_LoadedKB]:
    """Load and cache the FAISS index + metadata sidecar.

    Returns a _LoadedKB handle or None if the KB is unavailable
    (missing/corrupt index, missing sidecar, or row/vector count mismatch).
    Logs a single warning on first unavailability (AC-14). Cached module-level.
    """
    global _KB_CACHE
    if _KB_CACHE is not None:
        return _KB_CACHE

    index_path = _resolve_backend_path(_config.CRAG_KB_INDEX_PATH)
    meta_path = _resolve_backend_path(_config.CRAG_KB_METADATA_PATH)

    if not index_path.exists():
        logger.warning(
            "CRAG KB index not found at %s — every clause will use web fallback",
            index_path,
        )
        return None
    if not meta_path.exists():
        logger.warning(
            "CRAG KB metadata not found at %s — every clause will use web fallback",
            meta_path,
        )
        return None

    try:
        index = faiss.read_index(str(index_path))
    except Exception as exc:
        logger.warning(
            "CRAG KB: failed to load FAISS index from %s: %s", index_path, exc
        )
        return None

    try:
        meta: List[dict] = []
        with open(meta_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    meta.append(json.loads(line))
    except Exception as exc:
        logger.warning("CRAG KB: failed to read metadata from %s: %s", meta_path, exc)
        return None

    if len(meta) != index.ntotal:
        logger.warning(
            "CRAG KB: metadata row count (%d) != index vector count (%d) — treating as corrupt",
            len(meta),
            index.ntotal,
        )
        return None

    _KB_CACHE = _LoadedKB(index=index, meta=meta)
    return _KB_CACHE


def search_kb(kb: _LoadedKB, query_vec: np.ndarray, top_k: int) -> RetrievalResult:
    """Search the loaded KB with an L2-normalized query vector.

    Returns RetrievalResult(snippets=top-k KB snippets in 001 shape,
    top_score=max(0.0, best cosine)). Fewer than top_k vectors → returns
    whatever exists; zero vectors → top_score=0.0, snippets=[].
    """
    # Guard empty index before calling faiss.search (k=0 is version-dependent)
    if kb.index.ntotal == 0:
        return RetrievalResult(snippets=[], top_score=0.0)

    actual_k = min(top_k, kb.index.ntotal)
    D, indices = kb.index.search(query_vec.reshape(1, -1), actual_k)

    top_score = max(0.0, float(D[0][0]))  # top-1 clamp per spec §7.1

    snippets = []
    for idx in indices[0]:
        if 0 <= idx < len(kb.meta):
            row = kb.meta[idx]
            snippets.append(make_snippet(row["snippet_text"], row["source_reference"]))

    return RetrievalResult(snippets=snippets, top_score=top_score)
