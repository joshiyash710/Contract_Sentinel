"""
Offline FAISS knowledge-base build utility for CRAG retrieval (Node 3).

Reads the curated reference-clause corpus produced by ``build_corpus.py``
(``data/kb/clauses_corpus.jsonl``), embeds each clause with the BGE-M3 embedding
model via Ollama, **L2-normalizes every vector**, and writes:

  * a FAISS **inner-product** index  -> ``config.CRAG_KB_INDEX_PATH``
  * a JSONL metadata sidecar         -> ``config.CRAG_KB_METADATA_PATH``

Row order in the sidecar corresponds 1:1 to vector IDs in the index. Because
vectors are L2-normalized on both build and query sides, inner product equals
cosine similarity — the exact scoring invariant CRAG's 0.73 threshold relies on
(specs/005-crag-retrieval §7.1, §7.3).

This is an OFFLINE utility, not part of the runtime pipeline. It uses the
EMBEDDING model (``OLLAMA_EMBED_MODEL_NAME`` = bge-m3) and MUST NEVER use the
generative ``OLLAMA_MODEL_NAME`` (constitution §8, model-separation rule).

Usage (from the backend/ directory, with Ollama running and bge-m3 pulled):

    python scripts/build_kb.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import List

import faiss
import numpy as np
import ollama

# Make ``app`` importable when run as a plain script from backend/.
BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from app import config  # noqa: E402

CORPUS_PATH = BACKEND_DIR / "data" / "kb" / "clauses_corpus.jsonl"
INDEX_PATH = BACKEND_DIR / config.CRAG_KB_INDEX_PATH
META_PATH = BACKEND_DIR / config.CRAG_KB_METADATA_PATH

# L2-normalization guard: reject any vector whose norm is ~0 (cannot normalize).
_MIN_NORM = 1e-12


def _model_separation_guard() -> None:
    """Fail loudly if the embedding model is misconfigured as the generative one."""
    if config.OLLAMA_EMBED_MODEL_NAME == config.OLLAMA_MODEL_NAME:
        raise SystemExit(
            "Model-separation violation (constitution §8): "
            "OLLAMA_EMBED_MODEL_NAME must differ from OLLAMA_MODEL_NAME."
        )


def _load_corpus() -> List[dict]:
    if not CORPUS_PATH.exists():
        raise SystemExit(
            f"Corpus not found: {CORPUS_PATH}\n"
            "Run `python scripts/build_corpus.py` first."
        )
    records: List[dict] = []
    for line_no, line in enumerate(CORPUS_PATH.read_text(encoding="utf-8").splitlines(), 1):
        line = line.strip()
        if not line:
            continue
        rec = json.loads(line)
        if not rec.get("snippet_text") or not rec.get("source_reference"):
            raise SystemExit(f"Corpus line {line_no} missing required keys: {rec!r}")
        records.append({"snippet_text": rec["snippet_text"], "source_reference": rec["source_reference"]})
    if not records:
        raise SystemExit("Corpus is empty — nothing to index.")
    return records


def _embed(text: str) -> np.ndarray:
    resp = ollama.embeddings(model=config.OLLAMA_EMBED_MODEL_NAME, prompt=text)
    vec = np.asarray(resp["embedding"], dtype=np.float32)
    norm = float(np.linalg.norm(vec))
    if norm < _MIN_NORM:
        raise SystemExit("Embedding returned a zero-norm vector; cannot L2-normalize.")
    return vec / norm  # L2-normalize so inner product == cosine (§7.1)


def main() -> None:
    _model_separation_guard()
    records = _load_corpus()
    print(f"Embedding {len(records)} clauses with '{config.OLLAMA_EMBED_MODEL_NAME}'...")

    vectors: List[np.ndarray] = []
    for i, rec in enumerate(records, 1):
        vectors.append(_embed(rec["snippet_text"]))
        if i % 20 == 0 or i == len(records):
            print(f"  embedded {i}/{len(records)}")

    matrix = np.vstack(vectors).astype(np.float32)
    dim = matrix.shape[1]

    # Inner-product index; with L2-normalized vectors this yields cosine similarity.
    index = faiss.IndexFlatIP(dim)
    index.add(matrix)

    INDEX_PATH.parent.mkdir(parents=True, exist_ok=True)
    faiss.write_index(index, str(INDEX_PATH))

    with META_PATH.open("w", encoding="utf-8") as fh:
        for rec in records:
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")

    print(
        f"Built FAISS index: {index.ntotal} vectors, dim={dim}\n"
        f"  index -> {INDEX_PATH.relative_to(BACKEND_DIR)}\n"
        f"  meta  -> {META_PATH.relative_to(BACKEND_DIR)}"
    )


if __name__ == "__main__":
    main()
