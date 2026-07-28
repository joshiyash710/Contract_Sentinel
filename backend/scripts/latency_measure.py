"""One-off latency re-measurement (post-025/027/028).

Runs the REAL pipeline over the eval corpus and prints per-node node_timings + total wall
time. Needs live Ollama. Delivery is DISABLED (import-bound). Run from backend/:

    python -X utf8 scripts/latency_measure.py
"""

from __future__ import annotations

import time
from pathlib import Path

import app.delivery.delivery_step as _dstep  # noqa: E402

_dstep.MCP_DELIVERY_ENABLED = False

from app.config import OLLAMA_MODEL_NAME  # noqa: E402
from app.runner.core import run_pipeline  # noqa: E402

_BACKEND = Path(__file__).resolve().parents[1]
_DOCS = [
    ("sample_balanced (normal)", _BACKEND / "eval/corpus/sample_balanced.docx"),
    ("heavy_contract (large)", _BACKEND / "eval/corpus/heavy_contract.docx"),
]


def _measure(label: str, doc: Path) -> None:
    print(f"\n=== {label}: {doc.name} ===", flush=True)
    if not doc.exists():
        print(f"  ! missing: {doc}")
        return
    t0 = time.monotonic()
    result = run_pipeline(document_path=str(doc), original_filename=doc.name)
    wall = time.monotonic() - t0

    timings = result.final_state.get("node_timings") or {}
    n_clauses = len(result.final_state.get("clauses", {}) or {})
    print(f"  clauses: {n_clauses}   wall: {wall:6.2f}s")
    for node, secs in sorted(timings.items(), key=lambda kv: -kv[1]):
        print(f"    {node:28s} {secs:7.2f}s")
    summed = sum(timings.values())
    print(f"    {'(sum of node_timings)':28s} {summed:7.2f}s")


def main() -> None:
    print(f"model: {OLLAMA_MODEL_NAME}")
    for label, doc in _DOCS:
        _measure(label, doc)


if __name__ == "__main__":
    main()
