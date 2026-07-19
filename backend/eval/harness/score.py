"""Score phase (feature 026): offline metrics from a cached run. NO Ollama, NO network.

Imports ONLY schema/matcher/scorer/config — never run.py or app.* (keeps it offline, AC-6).
Run from `backend/`:  python -m eval.harness.score eval/runs/<timestamp>
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from eval.harness.schema import load_gold, read_manifest
from eval.harness.scorer import DocInput, score

_CAVEAT = (
    "NOTE: these numbers are only as meaningful as the gold corpus. The seed set is INDICATIVE, "
    "not authoritative — trustworthy accuracy needs a larger, expert-labeled corpus."
)


def score_run(run_dir: str) -> dict:
    run_path = Path(run_dir)
    manifest = read_manifest(run_path)

    docs = []
    for gid, entry in manifest.items():
        if "error" in entry and "report" not in entry:
            continue  # pipeline crashed before producing a report; scorer marks it via ingest_error too
        report = json.loads((run_path / entry["report"]).read_text(encoding="utf-8"))
        sidecar = json.loads((run_path / entry["sidecar"]).read_text(encoding="utf-8"))
        gold = load_gold(entry["gold"])
        docs.append(DocInput(report=report, sidecar=sidecar, gold=gold))

    metrics = score(docs)
    (run_path / "metrics.json").write_text(json.dumps(metrics, indent=2), encoding="utf-8")
    return metrics


def _pct(x):
    return "N/A" if x is None else f"{x * 100:.1f}%"


def print_summary(m: dict) -> None:
    print("\n" + "=" * 64)
    print("ContractSentinel — evaluation metrics")
    print(_CAVEAT)
    print("=" * 64)
    c, det, sev, dia = m["corpus"], m["detection"], m["severity"], m["diagnostics"]
    print(f"docs scored: {c['docs']}   errors: {c['errors'] or 'none'}")
    print("\nDetection (risk flagging):")
    print(f"  precision {_pct(det['precision'])}  recall {_pct(det['recall'])}  F1 {_pct(det['f1'])}")
    print(f"  MISS rate {_pct(det['miss_rate'])}   FALSE-FLAG rate {_pct(det['false_flag_rate'])}")
    print(f"  tp={det['tp']} fn={det['fn']} fp_clean={det['fp_clean']} tn={det['tn']} "
          f"unlabeled_flags={det['unlabeled_flags']}")
    print(f"\nSeverity (n={sev['n']}): exact {_pct(sev['exact_accuracy'])}  "
          f"within-one {_pct(sev['within_one_accuracy'])}")
    print(f"\nSelf-RAG misses: seen-but-discarded={dia['self_rag_miss']['seen_but_discarded']}  "
          f"never-split={dia['self_rag_miss']['never_split']}")
    print(f"CRAG path: {dia['crag_path']}   rewrite-availability {_pct(dia['rewrite_availability'])}")
    print("\nLatency (p50/p95 s):")
    for node, v in m["latency"].items():
        print(f"  {node:24s} p50={v['p50']:.2f}  p95={v['p95']:.2f}")
    print("=" * 64)


def main() -> None:
    ap = argparse.ArgumentParser(description="Score a cached eval run (offline).")
    ap.add_argument("run_dir", help="a runs/<timestamp> directory produced by run.py")
    args = ap.parse_args()
    print_summary(score_run(args.run_dir))


if __name__ == "__main__":
    main()
