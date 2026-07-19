"""Feature 028 Part B — variance driver: run the 026 harness N times and report metric variance.

Needs live Ollama (reuses 026 run+score; delivery is disabled because importing `run` sets
`_dstep.MCP_DELIVERY_ENABLED=False`). Smoke-only — NOT part of the pytest runtime suite; the pure
aggregation it calls (`variance_stats`) is what's unit-tested.

Run from `backend/` (UTF-8 mode — run.py's ✓ progress print crashes on Windows cp1252):
    python -X utf8 -m eval.harness.variance                 # mode (a): residual at temp 0 + seed 42
    python -X utf8 -m eval.harness.variance --vary-seed     # mode (b): true model wobble (samples)

Mode (a) measures how reproducible the SHIPPED pipeline is (temperature 0 + fixed seed → residual is
GPU-float / web-fallback). Mode (b) sets seed=None AND raises temperature so the model actually
samples — a seed=None sweep left at temperature 0 measures near-nothing (greedy stays greedy).
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Dict, List, Tuple

from eval.harness import (
    run,
    score,
    schema,
    matcher,
)  # `run` import also disables delivery
from eval.harness.config import EVAL_VARIANCE_RUNS
from eval.harness.variance_stats import build_report, format_summary


def _enable_sampling(temp: float) -> None:
    """Mode (b): flip the four generative node modules to sampling (seed=None, raised temperature).

    Patches the import-bound aliases directly (same technique run.py uses for _dstep), because the
    nodes read OLLAMA_TEMPERATURE/OLLAMA_SEED by bare module-level name bound at import.
    """
    import app.graph.nodes.splitters.llm_refiner as m1
    import app.graph.nodes.validators.reflectors as m2
    import app.graph.nodes.scorers.risk_scorer as m3
    import app.graph.nodes.drafters.redline_drafter as m4

    for m in (m1, m2, m3, m4):
        m.OLLAMA_SEED = None
        m.OLLAMA_TEMPERATURE = temp
    print(
        f"[variance] --vary-seed: sampling ON (temperature={temp}, seed=None) on 4 generative nodes"
    )


def _per_clause_maps(run_dir: str) -> Tuple[Dict[str, bool], Dict[str, Tuple]]:
    """From one cached run, derive the flip map (should_flag gold → caught?) and the verdict map
    (matched gold clause → (final_status, risk_level)), joining risk_level from the report finding to
    final_status from the sidecar by clause_id (spec 028 §3c — sidecar has no risk_level).
    """
    manifest = schema.read_manifest(run_dir)
    caught: Dict[str, bool] = {}
    verdicts: Dict[str, Tuple] = {}
    run_path = Path(run_dir)
    for gid, entry in manifest.items():
        if "report" not in entry:  # pipeline error for this doc — skip
            continue
        report = schema.read_report(run_path / entry["report"])
        sidecar = schema.read_sidecar(run_path / entry["sidecar"])
        gold = schema.load_gold(entry["gold"])
        findings = report.get("findings", [])
        res = matcher.match(findings, gold.clauses)
        matched_by_gold = {id(g): f for (f, g) in res.matches}
        final_status_by_cid = {
            row["clause_id"]: row.get("final_status") for row in sidecar
        }
        for gi, g in enumerate(gold.clauses):
            key = f"{gid}#{gi}"
            finding = matched_by_gold.get(id(g))
            if g.should_flag:
                caught[key] = finding is not None
            if finding is not None:
                verdicts[key] = (
                    final_status_by_cid.get(finding.get("clause_id")),
                    finding.get("risk_level"),
                )
    return caught, verdicts


def run_variance(
    gold_dir: str, out_root: str, n: int, vary_seed: bool = False, temp: float = 0.8
) -> dict:
    if vary_seed:
        _enable_sampling(temp)

    var_root = Path(out_root) / time.strftime("%Y%m%d-%H%M%S")
    var_root.mkdir(parents=True, exist_ok=True)

    metrics_list: List[dict] = []
    per_run_caught: List[Dict[str, bool]] = []
    per_run_verdicts: List[Dict[str, Tuple]] = []

    for i in range(n):
        print(f"\n===== variance run {i + 1}/{n} =====", flush=True)
        run_dir = run.run(gold_dir, str(var_root / f"run{i}"))
        if not run_dir:
            print(f"[variance] run {i} produced no data (empty gold?) — stopping.")
            break
        metrics_list.append(score.score_run(run_dir))
        caught, verdicts = _per_clause_maps(run_dir)
        per_run_caught.append(caught)
        per_run_verdicts.append(verdicts)

    report = build_report(metrics_list, per_run_caught, per_run_verdicts)
    (var_root / "variance.json").write_text(
        json.dumps(report, indent=2), encoding="utf-8"
    )
    print("\n" + format_summary(report))
    print(f"\nVariance report written to {var_root / 'variance.json'}")
    return report


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Run the 026 harness N times and report metric variance."
    )
    ap.add_argument(
        "--gold", default="eval/gold", help="gold label dir (default: eval/gold)"
    )
    ap.add_argument("--out", default="eval/runs/variance", help="variance runs root")
    ap.add_argument(
        "--runs",
        type=int,
        default=EVAL_VARIANCE_RUNS,
        help="N cycles (default: config)",
    )
    ap.add_argument(
        "--vary-seed",
        action="store_true",
        help="mode (b): sample (seed=None + raised temp)",
    )
    ap.add_argument(
        "--temp", type=float, default=0.8, help="sampling temperature for --vary-seed"
    )
    args = ap.parse_args()
    run_variance(
        args.gold, args.out, args.runs, vary_seed=args.vary_seed, temp=args.temp
    )


if __name__ == "__main__":
    main()
