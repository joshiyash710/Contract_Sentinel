"""
Offline CRAG confidence-scoring eval for Node 3 (specs/005-crag-retrieval §8).

Purpose: sanity-check the confidence-scoring + routing behaviour against the
REAL built FAISS KB, deterministically and OFFLINE (no live Ollama, no network).

Method — leave-one-out over the KB itself:
  For each of the N reference vectors, reconstruct it from the index (it is
  already L2-normalized), use it as a query, search top-(K+1), then DROP the
  self-match (the row's cosine with itself is ~1.0 at its own index) and take
  the best remaining neighbour as that clause's confidence. This measures how
  strongly each reference clause matches the REST of the corpus — a realistic
  proxy for the per-clause confidence distribution the spec §8 asks us to log,
  without needing bge-m3 running (reconstruct returns the stored vector).

Reported (spec §8 metrics 1, 2, 7-adjacent):
  * self-similarity sanity (must be ~1.0 for every row — validates the
    normalization + inner-product invariant that the 0.73 threshold relies on);
  * confidence distribution (min / mean / median / max + coarse histogram);
  * retrieval-path hit-rate at CRAG_CONFIDENCE_THRESHOLD (LOCAL_KB vs WEB_FALLBACK).

This is an OFFLINE eval utility, not part of the runtime pipeline and not part
of the pytest suite. Run from the backend/ directory:

    python eval/eval_crag_confidence.py
"""

from __future__ import annotations

import statistics
import sys
from pathlib import Path

import numpy as np

# Make ``app`` importable when run as a plain script from backend/.
BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from app import config  # noqa: E402
from app.graph.nodes.retrievers.kb_retriever import load_kb  # noqa: E402


def main() -> int:
    kb = load_kb()
    if kb is None:
        print("FAIL: KB unavailable — run scripts/build_kb.py first.")
        return 1

    n = kb.index.ntotal
    dim = kb.index.d
    threshold = config.CRAG_CONFIDENCE_THRESHOLD
    top_k = config.CRAG_TOP_K
    print(f"Loaded KB: {n} vectors, dim {dim}, threshold {threshold}, top_k {top_k}\n")

    self_sims: list[float] = []
    confidences: list[float] = []  # best cosine to a DIFFERENT clause
    local_hits = 0

    for i in range(n):
        q = kb.index.reconstruct(i).reshape(1, -1).astype("float32")
        # search one extra so we can drop the guaranteed self-match
        D, indices = kb.index.search(q, min(top_k + 1, n))
        scores = D[0]
        ids = indices[0]

        # self-similarity: the score at the row's own id
        self_pos = np.where(ids == i)[0]
        if len(self_pos):
            self_sims.append(float(scores[self_pos[0]]))

        # best cosine to any OTHER clause = confidence proxy
        best_other = 0.0
        for score, idx in zip(scores, ids):
            if idx != i:
                best_other = max(0.0, float(score))
                break
        confidences.append(best_other)
        if best_other >= threshold:
            local_hits += 1

    # ── self-similarity sanity ────────────────────────────────────────────────
    min_self = min(self_sims)
    print("Self-similarity sanity (must be ~1.0 - validates L2-norm invariant):")
    print(f"  min {min_self:.4f}  mean {statistics.mean(self_sims):.4f}")
    if min_self < 0.99:
        print(
            "  WARNING: a self-similarity < 0.99 suggests a normalization/index issue."
        )
    print()

    # ── confidence distribution ───────────────────────────────────────────────
    print("Confidence distribution (best cosine to a DIFFERENT clause):")
    print(
        f"  min {min(confidences):.4f}  mean {statistics.mean(confidences):.4f}"
        f"  median {statistics.median(confidences):.4f}  max {max(confidences):.4f}"
    )
    buckets = [0.0, 0.5, 0.6, 0.7, 0.73, 0.8, 0.9, 1.01]
    print("  histogram:")
    for lo, hi in zip(buckets, buckets[1:]):
        c = sum(1 for x in confidences if lo <= x < hi)
        bar = "#" * c
        print(f"    [{lo:.2f}, {hi:.2f}): {c:3d} {bar}")
    print()

    # ── path hit-rate ─────────────────────────────────────────────────────────
    local_pct = 100.0 * local_hits / n
    print(f"Path hit-rate @ threshold {threshold}:")
    print(f"  LOCAL_KB    : {local_hits:3d} / {n}  ({local_pct:5.1f}%)")
    print(f"  WEB_FALLBACK: {n - local_hits:3d} / {n}  ({100 - local_pct:5.1f}%)")

    print("\nOK: eval completed with sane output.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
