"""Pure metric computation for the evaluation harness (feature 026, §3.4).

Consumes (report dict, verdict sidecar, GoldDoc) per document; computes detection / severity /
calibration / per-node diagnostics / latency across the corpus. No app.* imports (offline, AC-6).
Sidecar `final_status`/`path_taken` are compared against the enum VALUE strings.
"""

from __future__ import annotations

from dataclasses import dataclass
from statistics import median
from typing import List, Optional

from eval.harness.config import CONFIDENCE_BUCKETS, EVAL_MATCH_MIN_OVERLAP, SEVERITY_RANK
from eval.harness.matcher import match, overlap
from eval.harness.schema import GoldDoc

_VALIDATED = "validated"          # ValidationStatus.VALIDATED.value
_LOCAL_KB = "local_kb"            # RetrievalPath.LOCAL_KB.value
_WEB_FALLBACK = "web_fallback"    # RetrievalPath.WEB_FALLBACK.value


@dataclass
class DocInput:
    report: dict
    sidecar: List[dict]
    gold: GoldDoc


def _safe_div(n: float, d: float) -> Optional[float]:
    return (n / d) if d else None


def _percentile(values: List[float], q: float) -> float:
    if not values:
        return 0.0
    xs = sorted(values)
    if len(xs) == 1:
        return xs[0]
    idx = q * (len(xs) - 1)
    lo = int(idx)
    frac = idx - lo
    hi = min(lo + 1, len(xs) - 1)
    return xs[lo] + (xs[hi] - xs[lo]) * frac


def score(docs: List[DocInput]) -> dict:
    tp = fn = fp_clean = tn = unlabeled = 0
    sev_exact = sev_within = sev_n = 0
    confusion: dict = {}
    cal_findings: List[tuple] = []  # (confidence, correct)
    seen_discarded = never_split = 0
    path_counts = {_LOCAL_KB: 0, _WEB_FALLBACK: 0}
    rewrite_total = rewrite_yes = 0
    node_times: dict = {}
    errors: List[str] = []

    for d in docs:
        if d.report.get("ingest_error"):
            errors.append(d.gold.gold_id)
            continue

        findings = d.report.get("findings", [])
        gold = d.gold.clauses
        res = match(findings, gold)

        matched_gold = {id(g) for _f, g in res.matches}
        # Detection tallies over gold clauses.
        for g in gold:
            flagged = id(g) in matched_gold
            if g.should_flag and flagged:
                tp += 1
            elif g.should_flag and not flagged:
                fn += 1
            elif (not g.should_flag) and flagged:
                fp_clean += 1
            else:
                tn += 1
        unlabeled += len(res.unmatched_findings)

        # Severity + calibration over matched findings.
        for f, g in res.matches:
            correct = g.should_flag
            cal_findings.append((f.get("confidence_score"), correct))
            if g.should_flag and g.expected_severity and f.get("risk_level") is not None:
                pr = SEVERITY_RANK.get(str(f["risk_level"]).lower())
                gr = SEVERITY_RANK.get(g.expected_severity)
                if pr is not None and gr is not None:
                    sev_n += 1
                    if pr == gr:
                        sev_exact += 1
                    if abs(pr - gr) <= 1:
                        sev_within += 1
                    confusion.setdefault(g.expected_severity, {}).setdefault(str(f["risk_level"]).lower(), 0)
                    confusion[g.expected_severity][str(f["risk_level"]).lower()] += 1
        # Unmatched findings count toward calibration as incorrect flags.
        for f in res.unmatched_findings:
            cal_findings.append((f.get("confidence_score"), False))

        # Rewrite availability.
        for f in findings:
            rewrite_total += 1
            if f.get("rewrite_state") == "rewritten":
                rewrite_yes += 1

        # Self-RAG discard contribution to misses (from sidecar).
        for g in res.unmatched_gold:
            if not g.should_flag:
                continue
            best = _best_sidecar(g.text_snippet, d.sidecar)
            if best is not None and best.get("final_status") != _VALIDATED:
                seen_discarded += 1
            else:
                never_split += 1

        # CRAG path split (from sidecar).
        for rec in d.sidecar:
            p = rec.get("path_taken")
            if p in path_counts:
                path_counts[p] += 1

        # Latency (document-level node_timings).
        for node, secs in (d.report.get("node_timings") or {}).items():
            node_times.setdefault(node, []).append(secs)

    precision = _safe_div(tp, tp + fp_clean + unlabeled)
    recall = _safe_div(tp, tp + fn)
    f1 = _safe_div(2 * precision * recall, precision + recall) if (precision and recall) else (
        None if precision is None or recall is None else 0.0
    )

    return {
        "corpus": {"docs": len(docs) - len(errors), "errors": errors},
        "detection": {
            "tp": tp, "fn": fn, "fp_clean": fp_clean, "tn": tn, "unlabeled_flags": unlabeled,
            "precision": precision, "recall": recall, "f1": f1,
            "miss_rate": _safe_div(fn, tp + fn),
            "false_flag_rate": _safe_div(fp_clean, fp_clean + tn),
        },
        "severity": {
            "n": sev_n,
            "exact_accuracy": _safe_div(sev_exact, sev_n),
            "within_one_accuracy": _safe_div(sev_within, sev_n),
            "confusion": confusion,
        },
        "calibration": _calibrate(cal_findings),
        "diagnostics": {
            "self_rag_miss": {"seen_but_discarded": seen_discarded, "never_split": never_split},
            "crag_path": path_counts,
            "rewrite_availability": _safe_div(rewrite_yes, rewrite_total),
        },
        "latency": {
            node: {"p50": _percentile(v, 0.5), "p95": _percentile(v, 0.95)}
            for node, v in sorted(node_times.items())
        },
    }


def _best_sidecar(snippet: str, sidecar: List[dict]) -> Optional[dict]:
    best, best_ov = None, 0.0
    for rec in sidecar:
        ov = overlap(rec.get("text"), snippet)
        if ov >= EVAL_MATCH_MIN_OVERLAP and ov > best_ov:
            best, best_ov = rec, ov
    return best


def _calibrate(findings: List[tuple]) -> List[dict]:
    edges = CONFIDENCE_BUCKETS
    out = []
    for i in range(len(edges) - 1):
        lo, hi = edges[i], edges[i + 1]
        in_bucket = [c for (conf, c) in findings if conf is not None and lo <= conf < hi]
        out.append({
            "bucket": f"[{lo}, {hi})",
            "count": len(in_bucket),
            "correct_fraction": _safe_div(sum(1 for c in in_bucket if c), len(in_bucket)),
        })
    return out
