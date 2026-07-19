"""Feature 028 Part B — pure cross-run variance aggregation.

Deterministic, offline: no Ollama, no network, no filesystem. Consumes the N per-run 026 metrics
dicts (from score.score_run) plus per-run per-clause maps built by the driver, and reports the
distribution (mean/std/min/max/CV) of each headline metric, the per-gold-clause caught↔missed flip
rate, and the Self-RAG verdict-stability rate. This is the §7 TDD-unit-tested core (spec 028 §2.3).
"""

from __future__ import annotations

import math
from typing import Dict, List, Optional, Tuple

# Headline 026 metric leaves whose distribution we summarize across runs.
_DETECTION_LEAVES = ("precision", "recall", "f1", "miss_rate", "false_flag_rate")
_SEVERITY_LEAVES = ("exact_accuracy", "within_one_accuracy")


def summarize(values: List[Optional[float]]) -> Dict:
    """mean/std/min/max/CV over the non-None values. Population std; CV=None when mean==0 or n<2."""
    xs = [v for v in values if v is not None]
    n = len(xs)
    if n == 0:
        return {"n": 0, "mean": None, "std": None, "min": None, "max": None, "cv": None}
    mean = sum(xs) / n
    std = math.sqrt(sum((x - mean) ** 2 for x in xs) / n) if n >= 2 else 0.0
    cv = (std / mean) if (n >= 2 and mean != 0) else None
    return {"n": n, "mean": mean, "std": std, "min": min(xs), "max": max(xs), "cv": cv}


def aggregate_metrics(metrics_list: List[Dict]) -> Dict:
    """For each headline detection/severity leaf, summarize its value across the N runs."""
    detection = {
        leaf: summarize([m.get("detection", {}).get(leaf) for m in metrics_list])
        for leaf in _DETECTION_LEAVES
    }
    severity = {
        leaf: summarize([m.get("severity", {}).get(leaf) for m in metrics_list])
        for leaf in _SEVERITY_LEAVES
    }
    return {"runs": len(metrics_list), "detection": detection, "severity": severity}


def flip_stats(per_run_caught: List[Dict[str, bool]]) -> Dict:
    """Per-gold-clause caught fraction + stable-caught / stable-missed / unstable counts.

    per_run_caught: one map per run of {gold_clause_key -> caught?} over should_flag:true clauses.
    A key missing from a run's map counts as not caught that run.
    """
    n = len(per_run_caught)
    keys = sorted({k for run in per_run_caught for k in run})
    per_clause: Dict[str, float] = {}
    stable_caught = stable_missed = unstable = 0
    for k in keys:
        caught = sum(1 for run in per_run_caught if run.get(k, False))
        frac = caught / n if n else 0.0
        per_clause[k] = frac
        if caught == n:
            stable_caught += 1
        elif caught == 0:
            stable_missed += 1
        else:
            unstable += 1
    return {
        "runs": n,
        "total": len(keys),
        "stable_caught": stable_caught,
        "stable_missed": stable_missed,
        "unstable": unstable,
        "per_clause": per_clause,
    }


def verdict_stability(per_run_verdicts: List[Dict[str, Tuple]]) -> Dict:
    """Fraction of clauses whose (final_status, risk_level) tuple is identical across ALL N runs.

    A clause counts as stable only if it is present in every run with the same tuple. fraction is
    None when there are no runs or no clauses (insufficient data).
    """
    n = len(per_run_verdicts)
    keys = sorted({k for run in per_run_verdicts for k in run})
    total = len(keys)
    if n == 0 or total == 0:
        return {"runs": n, "total": total, "stable": 0, "fraction": None}
    stable = 0
    for k in keys:
        present = [run[k] for run in per_run_verdicts if k in run]
        if len(present) == n and all(v == present[0] for v in present):
            stable += 1
    return {"runs": n, "total": total, "stable": stable, "fraction": stable / total}


def build_report(
    metrics_list: List[Dict],
    per_run_caught: List[Dict[str, bool]],
    per_run_verdicts: List[Dict[str, Tuple]],
) -> Dict:
    """Assemble the full variance report (the shape written to variance.json)."""
    return {
        "runs": len(metrics_list),
        "metrics": aggregate_metrics(metrics_list),
        "flip": flip_stats(per_run_caught),
        "verdict_stability": verdict_stability(per_run_verdicts),
    }


def _fmt_stat(s: Dict) -> str:
    if s["n"] == 0 or s["mean"] is None:
        return "N/A (insufficient runs)"
    cv = "N/A" if s["cv"] is None else f"{s['cv'] * 100:.1f}%"
    return (
        f"{s['mean'] * 100:.1f}% ± {s['std'] * 100:.1f}% "
        f"({s['min'] * 100:.1f}–{s['max'] * 100:.1f}%, CV={cv})"
    )


def format_summary(report: Dict) -> str:
    """Human-readable summary: each headline metric as `mean ± std (min–max, CV=…)`."""
    n = report["runs"]
    m = report["metrics"]
    flip = report["flip"]
    vs = report["verdict_stability"]
    lines = [
        "=" * 64,
        f"ContractSentinel — variance across {n} run(s) (feature 028)",
        "NOTE: only as meaningful as the gold corpus; N>=3 needed to characterize variance.",
        "=" * 64,
        "Detection:",
        f"  precision  {_fmt_stat(m['detection']['precision'])}",
        f"  recall     {_fmt_stat(m['detection']['recall'])}",
        f"  F1         {_fmt_stat(m['detection']['f1'])}",
        f"  miss       {_fmt_stat(m['detection']['miss_rate'])}",
        f"  false-flag {_fmt_stat(m['detection']['false_flag_rate'])}",
        "Severity:",
        f"  exact      {_fmt_stat(m['severity']['exact_accuracy'])}",
        f"  within-one {_fmt_stat(m['severity']['within_one_accuracy'])}",
        "Stability:",
        f"  gold clauses: stable-caught={flip['stable_caught']} "
        f"stable-missed={flip['stable_missed']} unstable={flip['unstable']} (of {flip['total']})",
        f"  verdict-stability: "
        + ("N/A" if vs["fraction"] is None else f"{vs['fraction'] * 100:.1f}%")
        + f" ({vs['stable']}/{vs['total']})",
        "=" * 64,
    ]
    return "\n".join(lines)
