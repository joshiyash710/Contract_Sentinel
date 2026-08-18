"""Offline miss-triage for a cached evaluation run (feature 041 follow-up).

The full 32-contract run (`81411c0f`) reported recall 31.7% — but that number is CONFOUNDED: the
CANDIDATE gold labels flag 463/695 clauses as should-flag, and a CUAD category is not a risk verdict
(spec D4). So many of the 316 "misses" (fn) are the pipeline CORRECTLY declining a routine clause,
not a real detection failure. This script disambiguates the two BEFORE any Self-RAG / threshold tuning.

It is PURE ANALYSIS of cached artifacts — NO Ollama, NO network, NO new pipeline run. It reuses the
same matcher / gold reader / best-sidecar logic the scorer uses (so its miss count reconciles with
`metrics.json`), and for every missed gold clause emits a review row recording what the pipeline
actually did with the best-overlapping segmented clause, plus a blank `verdict` column for a human to
mark **real_miss** vs **label_overflag**.

It also mines the run's CRAG retrieval-confidence distribution (finding `confidence_score` vs the
0.73 `CRAG_CONFIDENCE_THRESHOLD`, split by `path_taken`) — an independent free win to gauge whether
0.73 is too high for real-query clauses (the run went 85% web-fallback).

Each miss also gets a `signature` (how far the clause got through Self-RAG before being dropped —
A_discarded_after_isrel / A_discarded_after_relevance / B_never_scored / validated_unmatched /
no_overlapping_clause); `--only A` writes just the A_* real-recall-bug candidates (the summary is
always computed over ALL misses).

Run from backend/ (offline):
    python -X utf8 scripts/build_miss_triage.py eval/runs/20260817-190549
    python -X utf8 scripts/build_miss_triage.py eval/runs/20260817-190549 --sample 40
    python -X utf8 scripts/build_miss_triage.py eval/runs/20260817-190549 --only A
"""

from __future__ import annotations

import argparse
import csv
import json
import random
import sys
from collections import Counter, defaultdict
from pathlib import Path
from statistics import mean, median
from typing import List, Optional, Tuple

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from eval.harness.matcher import match, overlap  # noqa: E402
from eval.harness.schema import load_gold, read_manifest  # noqa: E402

# Mirrors app.config.CRAG_CONFIDENCE_THRESHOLD (retrieval confidence split, constitution §2). Copied
# rather than imported to keep this analysis fully offline (no app.* side effects, cf. harness AC-6).
CRAG_CONFIDENCE_THRESHOLD = 0.73

_VALIDATED = "validated"       # ValidationStatus.VALIDATED.value
_LOCAL_KB = "local_kb"         # RetrievalPath.LOCAL_KB.value
_WEB_FALLBACK = "web_fallback"  # RetrievalPath.WEB_FALLBACK.value
_MIN_OVERLAP = 0.6             # EVAL_MATCH_MIN_OVERLAP (kept local to _best_sidecar semantics)

# Columns emitted for each missed gold clause (blank `verdict` last, for the reviewer).
_CSV_FIELDS = [
    "contract", "clause_type", "expected_severity", "gold_section", "disposition", "signature",
    "final_status", "relevance_verdict", "isrel_verdict", "issup_verdict", "retry_count",
    "path_taken", "best_overlap", "gold_snippet", "best_sidecar_text", "gold_note",
    "verdict",  # blank: reviewer marks real_miss | label_overflag
]

# Reviewer-facing disposition of a missed gold clause vs the best-overlapping segmented clause.
#   discarded_self_rag  — a clause overlapped, but the pipeline did NOT validate it (Self-RAG/pipeline
#                         declined). These are the candidate REAL misses (or correct declines).
#   validated_unmatched — a clause overlapped AND was validated, but the matcher didn't link the
#                         surfaced finding to this gold clause (text-reassembly divergence, or the
#                         finding matched a different gold clause). NOT a Self-RAG discard.
#   no_overlapping_clause — no segmented clause overlapped the gold snippet >= 0.6: either a
#                         segmentation gap or the gold snippet is mislocated / too short.
_DISCARDED = "discarded_self_rag"
_VALIDATED_UNMATCHED = "validated_unmatched"
_NO_CLAUSE = "no_overlapping_clause"

# Finer "signature" of a miss, read off how far the clause got through Self-RAG before being dropped
# (the actionable axis — see the eyeball cross-section). Deepest discard first:
#   A_discarded_after_isrel     — relevance=True AND isrel=True, but not validated: the pipeline judged
#                                 both the clause AND its evidence relevant, then dropped it at/before
#                                 the support check (Branch-B). STRONGEST real-recall-bug candidate.
#   A_discarded_after_relevance — relevance=True but isrel not True (isrel=False: evidence judged NOT
#                                 relevant; or isrel never reached): passed the relevance gate, dropped
#                                 at/after the isrel evidence-check.
#   B_never_scored              — relevance not True (relevance=None: grader never ran; or the rare
#                                 relevance=False): dropped at/before the relevance gate. Mixed: real
#                                 clauses never given a chance OR mislocated fragment gold snippets.
#   validated_unmatched / no_overlapping_clause — NOT real misses (flagged-but-unmatched / segmentation gap).
_SIG_AFTER_ISREL = "A_discarded_after_isrel"
_SIG_AFTER_REL = "A_discarded_after_relevance"
_SIG_NEVER = "B_never_scored"
_SIG_VALIDATED = "validated_unmatched"
_SIG_NO_CLAUSE = "no_overlapping_clause"
# Fixed display order (deepest discard → not-a-miss) and the real-recall-bug candidate set.
_SIG_ORDER = [_SIG_AFTER_ISREL, _SIG_AFTER_REL, _SIG_NEVER, _SIG_VALIDATED, _SIG_NO_CLAUSE]
_SIG_REALBUG = (_SIG_AFTER_ISREL, _SIG_AFTER_REL)


def _truthy(v) -> bool:
    """Sidecar verdicts are JSON booleans/None (both this and _fmt_verdict assume that); tolerate a
    stringified 'true' too, consistent with _fmt_verdict rendering a stringified 'false' as falsy."""
    return v is True or (isinstance(v, str) and v.strip().lower() == "true")


def _signature(disposition: str, best: Optional[dict]) -> str:
    if disposition == _VALIDATED_UNMATCHED:
        return _SIG_VALIDATED
    if disposition == _NO_CLAUSE:
        return _SIG_NO_CLAUSE
    rel = _truthy((best or {}).get("relevance_verdict"))
    isr = _truthy((best or {}).get("isrel_verdict"))
    if rel and isr:
        return _SIG_AFTER_ISREL
    if rel:
        return _SIG_AFTER_REL
    return _SIG_NEVER


def _best_sidecar(snippet: str, sidecar: List[dict]) -> Tuple[Optional[dict], float]:
    """Best-overlapping raw clause record + its overlap — identical SELECTION to
    scorer._best_sidecar (which returns only the record)."""
    best, best_ov = None, 0.0
    for rec in sidecar:
        ov = overlap(rec.get("text"), snippet)
        if ov >= _MIN_OVERLAP and ov > best_ov:
            best, best_ov = rec, ov
    return best, best_ov


def _snip(text: Optional[str], n: int = 240) -> str:
    """One-line, whitespace-collapsed, truncated snippet for CSV/JSON readability."""
    s = " ".join((text or "").split())
    return s if len(s) <= n else s[: n - 1] + "…"


def _fmt_verdict(v) -> str:
    """Render a Self-RAG verdict for the CSV, keeping the three states DISTINCT: an explicit
    `False` (scored → judged NOT relevant/supported) must not collapse to the same blank as
    `None`/absent (that step never ran). `True`→"true", `False`→"false", `None`/absent→"" (blank)."""
    if v is True:
        return "true"
    if v is False:
        return "false"
    return "" if v is None else str(v)


def _disposition(best: Optional[dict]) -> str:
    if best is None:
        return _NO_CLAUSE
    return _VALIDATED_UNMATCHED if best.get("final_status") == _VALIDATED else _DISCARDED


def build_rows(run_dir: Path) -> tuple:
    """Return (rows, crag) where rows is one dict per missed gold clause and crag is the
    finding-level confidence mining. Mirrors score_run's artifact loading."""
    manifest = read_manifest(run_dir)
    rows: List[dict] = []
    # CRAG mining: finding-level (surfaced clauses) confidence by path + sidecar path population.
    conf_by_path: dict = {_LOCAL_KB: [], _WEB_FALLBACK: [], "other": []}
    sidecar_path = Counter()

    for gid, entry in manifest.items():
        if "report" not in entry:
            continue  # pipeline crashed before a report (score_run skips these too)
        report = json.loads((run_dir / entry["report"]).read_text(encoding="utf-8"))
        sidecar = json.loads((run_dir / entry["sidecar"]).read_text(encoding="utf-8"))
        gold = load_gold(entry["gold"])

        findings = report.get("findings", [])
        res = match(findings, gold.clauses)

        # Missed gold clauses = unmatched gold that SHOULD have been flagged (the fn population).
        for g in res.unmatched_gold:
            if not g.should_flag:
                continue
            best, best_ov = _best_sidecar(g.text_snippet, sidecar)
            disposition = _disposition(best)
            rows.append({
                "contract": gold.gold_id,
                "clause_type": g.clause_type or "unspecified",
                "expected_severity": g.expected_severity or "",
                "gold_section": g.section_number or "",
                "disposition": disposition,
                "signature": _signature(disposition, best),
                "final_status": (best or {}).get("final_status") or "",
                "relevance_verdict": _fmt_verdict((best or {}).get("relevance_verdict")),
                "isrel_verdict": _fmt_verdict((best or {}).get("isrel_verdict")),
                "issup_verdict": _fmt_verdict((best or {}).get("issup_verdict")),
                "retry_count": (best or {}).get("retry_count") if best else "",
                "path_taken": (best or {}).get("path_taken") or "",
                "best_overlap": round(best_ov, 3),
                "gold_snippet": _snip(g.text_snippet),
                "best_sidecar_text": _snip((best or {}).get("text")) if best else "",
                "gold_note": _snip(g.note, 160) or "",
                "verdict": "",
            })

        # CRAG free-win: finding-level confidence by path, + full sidecar path population.
        for f in findings:
            c = f.get("confidence_score")
            if c is None:
                continue
            p = f.get("path_taken")
            conf_by_path.setdefault(p if p in (_LOCAL_KB, _WEB_FALLBACK) else "other", []).append(c)
        for rec in sidecar:
            p = rec.get("path_taken")
            if p in (_LOCAL_KB, _WEB_FALLBACK):
                sidecar_path[p] += 1

    crag = {"conf_by_path": conf_by_path, "sidecar_path": dict(sidecar_path)}
    return rows, crag


def _stratified_sample(rows: List[dict], n: int, seed: int) -> List[dict]:
    """Deterministic sample of ~n rows spread proportionally across clause_type (largest remainder),
    so a reviewer sees the diversity of miss types rather than one dominant category."""
    if n >= len(rows):
        return list(rows)
    by_type: dict = defaultdict(list)
    for r in rows:
        by_type[r["clause_type"]].append(r)
    rng = random.Random(seed)
    total = len(rows)
    # Proportional quota per type, then distribute the rounding remainder to the largest fractions.
    quotas = {}
    fracs = {}
    for t, group in by_type.items():
        exact = n * len(group) / total
        quotas[t] = min(len(group), int(exact))
        fracs[t] = exact - int(exact)
    shortfall = n - sum(quotas.values())
    for t in sorted(fracs, key=lambda k: fracs[k], reverse=True):
        if shortfall <= 0:
            break
        if quotas[t] < len(by_type[t]):
            quotas[t] += 1
            shortfall -= 1
    out: List[dict] = []
    for t, group in by_type.items():
        out.extend(rng.sample(group, quotas[t]))
    out.sort(key=lambda r: (r["clause_type"], r["contract"]))
    return out


def _write_csv(path: Path, rows: List[dict]) -> None:
    with path.open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=_CSV_FIELDS)
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in _CSV_FIELDS})


def _pct(n: int, d: int) -> str:
    return "N/A" if not d else f"{100 * n / d:.1f}%"


def _conf_stats(xs: List[float]) -> dict:
    if not xs:
        return {"n": 0}
    ys = sorted(xs)
    return {
        "n": len(ys),
        "min": round(ys[0], 3),
        "p25": round(ys[len(ys) // 4], 3),
        "median": round(median(ys), 3),
        "mean": round(mean(ys), 3),
        "p75": round(ys[(3 * len(ys)) // 4], 3),
        "max": round(ys[-1], 3),
        "below_0.73": sum(1 for c in ys if c < CRAG_CONFIDENCE_THRESHOLD),
    }


def summarize(rows: List[dict], crag: dict) -> dict:
    disp = Counter(r["disposition"] for r in rows)
    by_type = Counter(r["clause_type"] for r in rows)
    by_contract = Counter(r["contract"] for r in rows)
    # Among Self-RAG discards, which verdict drove the discard.
    disc = [r for r in rows if r["disposition"] == _DISCARDED]
    issup = Counter(r["issup_verdict"] or "∅" for r in disc)
    isrel = Counter(r["isrel_verdict"] or "∅" for r in disc)
    relv = Counter(r["relevance_verdict"] or "∅" for r in disc)
    status = Counter(r["final_status"] or "∅" for r in disc)
    sig = Counter(r["signature"] for r in rows)
    return {
        "total_misses": len(rows),
        "by_disposition": dict(disp),
        "by_signature": [(s, sig.get(s, 0)) for s in _SIG_ORDER if sig.get(s, 0)],
        "realbug_candidates": sum(sig.get(s, 0) for s in _SIG_REALBUG),
        "by_clause_type": by_type.most_common(),
        "by_contract": by_contract.most_common(),
        "discard_final_status": status.most_common(),
        "discard_issup_verdict": issup.most_common(),
        "discard_isrel_verdict": isrel.most_common(),
        "discard_relevance_verdict": relv.most_common(),
        "crag_confidence": {
            "threshold": CRAG_CONFIDENCE_THRESHOLD,
            "sidecar_path_population": crag["sidecar_path"],
            "finding_confidence_local_kb": _conf_stats(crag["conf_by_path"][_LOCAL_KB]),
            "finding_confidence_web_fallback": _conf_stats(crag["conf_by_path"][_WEB_FALLBACK]),
        },
    }


def print_report(summary: dict, out_all: Path, out_sample: Path, sample_n: int,
                 emitted_n: int, only: Optional[str]) -> None:
    print("\n" + "=" * 72)
    print("Feature 041 — MISS TRIAGE (offline analysis of a cached run)")
    print("Splits the 'misses' into pipeline dispositions so a reviewer can mark each")
    print("real_miss vs label_overflag BEFORE any Self-RAG / 0.73-threshold tuning.")
    print("=" * 72)
    tot = summary["total_misses"]
    print(f"\nTotal missed gold clauses (should_flag & unmatched): {tot}")
    print("\nBy pipeline disposition vs the best-overlapping segmented clause:")
    for d, c in sorted(summary["by_disposition"].items(), key=lambda kv: -kv[1]):
        print(f"  {d:22s} {c:4d}  ({_pct(c, tot)})")
    print("\n  discarded_self_rag = candidate REAL misses OR correct declines (the triage target).")
    print("  validated_unmatched = clause WAS validated; matcher/text divergence, NOT a miss of judgment.")
    print("  no_overlapping_clause = segmentation gap or mislocated gold snippet.")

    rb = summary["realbug_candidates"]
    print("\nBy signature (how far the clause got before being dropped — deepest first):")
    for s, c in summary["by_signature"]:
        tag = "  <- real-recall-bug candidate" if s in _SIG_REALBUG else ""
        print(f"  {s:28s} {c:4d}  ({_pct(c, tot)}){tag}")
    print(f"  → {rb} real-recall-bug candidates (relevance judged True, then discarded pre-validate).")
    print("    Filter to just these with:  --only A   (or --only B / a full signature name).")

    print("\nMisses by clause_type (raw CUAD label — top 15):")
    for t, c in summary["by_clause_type"][:15]:
        print(f"  {t:34s} {c:4d}")

    print("\nAmong Self-RAG discards — final_status:")
    for s, c in summary["discard_final_status"]:
        print(f"  {s:22s} {c:4d}")
    print("Among Self-RAG discards — issup_verdict / isrel_verdict / relevance_verdict:")
    print(f"  issup:     {summary['discard_issup_verdict']}")
    print(f"  isrel:     {summary['discard_isrel_verdict']}")
    print(f"  relevance: {summary['discard_relevance_verdict']}")

    cc = summary["crag_confidence"]
    print("\n" + "-" * 72)
    print(f"CRAG free-win — retrieval confidence vs threshold {cc['threshold']} (higher ⇒ local KB):")
    print(f"  sidecar path population (ALL clauses): {cc['sidecar_path_population']}")
    lk, wf = cc["finding_confidence_local_kb"], cc["finding_confidence_web_fallback"]
    print(f"  surfaced-finding confidence  local_kb (>=0.73): {lk}")
    print(f"  surfaced-finding confidence  web_fallback(<0.73): {wf}")
    print("  NOTE: confidence is the CRAG retrieval-grader score; only SURFACED findings persist it")
    print("  (per-clause pre-validation scores are not in the sidecar), so the distribution is a")
    print("  sample. A threshold re-tune is a runtime change → needs its own spec.")

    print("\n" + "-" * 72)
    scope = f"{emitted_n} rows matching --only {only!r}" if only else f"ALL {tot} miss rows"
    print(f"Wrote {scope} → {out_all}")
    print(f"Wrote stratified sample (~{sample_n}) → {out_sample}")
    print("Fill the blank `verdict` column with: real_miss | label_overflag")
    print("=" * 72)


def main() -> None:
    ap = argparse.ArgumentParser(description="Offline miss-triage of a cached eval run.")
    ap.add_argument("run_dir", help="a runs/<timestamp> directory produced by run.py")
    ap.add_argument("--out", default=None, help="output dir (default: <run_dir>/miss_triage)")
    ap.add_argument("--sample", type=int, default=40, help="stratified reviewer-sample size (default 40)")
    ap.add_argument("--seed", type=int, default=12345, help="deterministic sample seed")
    ap.add_argument("--only", default=None, metavar="SIGNATURE",
                    help="write only rows whose `signature` starts with this (e.g. A, B, "
                         "A_discarded_after_isrel). Summary still reflects ALL misses.")
    args = ap.parse_args()

    run_dir = Path(args.run_dir)
    out_dir = Path(args.out) if args.out else run_dir / "miss_triage"
    out_dir.mkdir(parents=True, exist_ok=True)

    rows, crag = build_rows(run_dir)
    summary = summarize(rows, crag)  # computed over ALL misses, before any --only filter
    emitted = rows
    if args.only:
        emitted = [r for r in rows if r["signature"].startswith(args.only)]
        if not emitted:
            raise SystemExit(f"--only {args.only!r} matched 0 of {len(rows)} rows; "
                             f"signatures present: {sorted({r['signature'] for r in rows})}")
    # Group the review sheet by clause_type so a reviewer works one type at a time (then contract,
    # then signature). Deterministic; the summary is unaffected (computed over `rows` above). The
    # stratified sample keeps identical PER-TYPE quotas, but because it draws by index into each
    # (now-reordered) group its specific rows are re-drawn — still deterministic under the seed.
    emitted = sorted(emitted, key=lambda r: (r["clause_type"], r["contract"], r["signature"]))
    sample = _stratified_sample(emitted, args.sample, args.seed)

    suffix = f"_{args.only}" if args.only else ""
    out_all = out_dir / f"misses_all{suffix}.csv"
    out_sample = out_dir / f"misses_sample{suffix}.csv"
    _write_csv(out_all, emitted)
    _write_csv(out_sample, sample)
    (out_dir / "summary.json").write_text(
        json.dumps({"run_dir": str(run_dir), **summary}, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    print_report(summary, out_all, out_sample, len(sample), len(emitted), args.only)


if __name__ == "__main__":
    main()
