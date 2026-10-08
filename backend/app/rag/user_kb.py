"""Feature 061 — per-user learned clause KB.

A private FAISS index per account that accumulates the VALIDATED-finding clauses of the contracts that user
analyzes. CRAG (node 3) searches it in addition to the shared base KB (see crag_retrieval_agent), so the
local-hit rate rises run-over-run. Mirrors kb_retriever conventions (IndexFlatIP on L2-normalized vectors ==
cosine; a {snippet_text, source_reference} JSONL sidecar 1:1 with vector rows; a .provider marker).

Isolation (§019): a user's index lives under {CRAG_USER_KB_DIR}/{user_id}/ and is only ever read/written for
that user_id. The user_id is validated as a safe single path segment — it can never escape the base dir.
"""

import json
import logging
import os
import threading
from pathlib import Path
from typing import List, Optional

import faiss
import numpy as np

import app.config as _config
from app.graph.nodes.retrievers.embeddings import embed_query
from app.graph.nodes.retrievers.kb_retriever import (
    _LoadedKB,
    _resolve_backend_path,
    _warn_on_provider_mismatch,
)

logger = logging.getLogger("contractsentinel.crag_retrieval.user_kb")

# Per-user caches, mirroring kb_retriever's single-index module cache. Keyed by the validated user slug.
_USER_KB_CACHE: dict = {}
_USER_KB_LOCKS: dict = {}
_LOCKS_GUARD = threading.Lock()


def _slug(user_id: str) -> str:
    """Validate user_id as a single safe path segment (§019 isolation / path-traversal guard).

    Rejects empty, path separators, and dot-segments so the index can never escape CRAG_USER_KB_DIR.
    """
    if not user_id or not isinstance(user_id, str):
        raise ValueError("user_id must be a non-empty string")
    if user_id in (".", "..") or ".." in user_id or "/" in user_id or "\\" in user_id or os.sep in user_id:
        raise ValueError(f"unsafe user_id for a KB path segment: {user_id!r}")
    return user_id


def _user_paths(user_id: str):
    """(index_path, meta_path, marker_path) for a user, resolved backend-relative like the base KB."""
    slug = _slug(user_id)
    base = _resolve_backend_path(_config.CRAG_USER_KB_DIR) / slug
    index_path = base / "clauses.faiss"
    meta_path = base / "clauses_meta.jsonl"
    marker_path = Path(str(index_path) + ".provider")
    return index_path, meta_path, marker_path


def _lock_for(slug: str) -> threading.Lock:
    with _LOCKS_GUARD:
        lock = _USER_KB_LOCKS.get(slug)
        if lock is None:
            lock = threading.Lock()
            _USER_KB_LOCKS[slug] = lock
        return lock


def _provider_marker() -> str:
    """JSON provenance stamp of the active embedding provider/model (feature 050 D3), matching build_kb."""
    model = _config.HF_EMBED_MODEL if _config.EMBED_PROVIDER == "hf" else _config.OLLAMA_EMBED_MODEL_NAME
    return json.dumps({"provider": _config.EMBED_PROVIDER, "model": model})


def _read_meta(meta_path: Path) -> List[dict]:
    rows: List[dict] = []
    with open(meta_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def load_user_kb(user_id: str) -> Optional[_LoadedKB]:
    """Load + cache a user's index, or None if unavailable/corrupt (same guards as kb_retriever.load_kb)."""
    slug = _slug(user_id)
    cached = _USER_KB_CACHE.get(slug)
    if cached is not None:
        return cached

    index_path, meta_path, _marker = _user_paths(user_id)
    if not index_path.exists() or not meta_path.exists():
        return None
    try:
        index = faiss.read_index(str(index_path))
    except Exception as exc:  # noqa: BLE001
        logger.warning("user KB: failed to load index for %r: %s", slug, exc)
        return None

    _warn_on_provider_mismatch(index_path)

    try:
        meta = _read_meta(meta_path)
    except Exception as exc:  # noqa: BLE001
        logger.warning("user KB: failed to read metadata for %r: %s", slug, exc)
        return None

    if len(meta) != index.ntotal:
        logger.warning(
            "user KB %r: metadata rows (%d) != index vectors (%d) — treating as corrupt",
            slug, len(meta), index.ntotal,
        )
        return None

    loaded = _LoadedKB(index=index, meta=meta)
    _USER_KB_CACHE[slug] = loaded
    return loaded


def append_clauses(user_id: str, items: List[dict]) -> int:
    """Append items ([{"text","source_reference"}]) to the user's index. Returns the count actually added.

    Embeds each text with BGE-M3 (skipping un-embeddable items so vectors and rows stay 1:1), adds to the
    IndexFlatIP, appends the sidecar rows, writes both atomically under a per-user lock, refreshes the
    provider marker on create, and invalidates the per-user cache.
    """
    slug = _slug(user_id)
    with _lock_for(slug):
        index_path, meta_path, marker_path = _user_paths(user_id)

        vectors = []
        rows = []
        for item in items:
            vec = embed_query(item["text"], _config.CRAG_EMBED_TIMEOUT_SECONDS, _config.OLLAMA_EMBED_MODEL_NAME)
            if vec is None:
                logger.warning("user KB %r: skipping un-embeddable clause", slug)
                continue
            vectors.append(np.asarray(vec, dtype=np.float32))
            rows.append({"snippet_text": item["text"], "source_reference": item["source_reference"]})
        if not vectors:
            return 0

        matrix = np.vstack(vectors).astype(np.float32)
        dim = matrix.shape[1]

        if index_path.exists():
            index = faiss.read_index(str(index_path))
            if index.d != dim:
                logger.warning(
                    "user KB %r: embedding dim %d != existing index dim %d — skipping append to avoid "
                    "corruption (rebuild needed)", slug, dim, index.d,
                )
                return 0
            existing_meta = _read_meta(meta_path) if meta_path.exists() else []
        else:
            index_path.parent.mkdir(parents=True, exist_ok=True)
            index = faiss.IndexFlatIP(dim)
            existing_meta = []

        index.add(matrix)
        new_meta = existing_meta + rows

        # Atomic persist: temp + os.replace so ntotal and the sidecar never desync on a crash mid-write.
        tmp_index = str(index_path) + ".tmp"
        faiss.write_index(index, tmp_index)
        os.replace(tmp_index, str(index_path))

        tmp_meta = str(meta_path) + ".tmp"
        with open(tmp_meta, "w", encoding="utf-8") as f:
            for row in new_meta:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
        os.replace(tmp_meta, str(meta_path))

        if not marker_path.exists():
            marker_path.write_text(_provider_marker(), encoding="utf-8")

        _USER_KB_CACHE.pop(slug, None)  # invalidate so the next load/search sees the new vectors
        return len(rows)
