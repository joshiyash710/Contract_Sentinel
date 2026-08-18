"""EXPERIMENT (feature 041 → 042 measure-first): does restoring clause-typing on large docs revive
the inert Self-RAG recall floor and rescue material misses?

Root cause established offline (review-agent APPROVED): the pipeline assigns clause_type=None to ~95%
of clauses because feature 025 Lever A skips the ClauseSplitter LLM refinement when regex yields
>CLAUSE_SPLITTER_LLM_MAX_CLAUSES (=40) clauses — which is every large CUAD contract. With clause_type
None, the feature-027 recall floor (which gates on clause_type) never fires, so material clauses
(e.g. cap_on_liability → ClauseType.liability, already in the floor) are discarded.

This script A/B-tests, on a FEW docs, ONE half of the chain — whether simply raising the Lever-A gate
restores typing and rescues misses (it does NOT propose a config; raising the gate reintroduces 025's
latency). It does NOT prove the positive half ("typing, WHEN it succeeds, revives the floor") — that
needs a successful-typing run and is left to the feature-042 spec's validation step.
  TREATMENT = re-run the real pipeline with the Lever-A gate raised (LLM typing forced on).
  BASELINE  = the cached run (gate at 40); only the gate differs, so the cached artifacts are a valid A.
Per doc it reports: clause_type non-None coverage (treatment), detection tp/fn vs baseline (harness
matcher + gold), and — crucially — which specific gold clauses flip fn→tp.

RESULT (2026-08-18, n=2): raising the gate did NOT restore typing — the LLM grouping call went
OFF-SCHEMA on both docs (Cybergy 117cl: emitted a document-summary tree re-emitting full text →
truncated at num_predict=1024; Arconic 45cl: valid but wrong shape, "missing 'clauses' list"). Both
fell back to regex → clause_type=None → 0 rescued. So the naive gate-raise is falsified; the real
issue is schema-adherence of the grouping call on large inputs, not merely token budget.

Needs live Ollama (qwen3:8b + bge-m3). Delivery is DISABLED (import-bound). Slow on large docs by
design. Run from backend/:
    python -X utf8 scripts/exp_clausetype_floor.py
    python -X utf8 scripts/exp_clausetype_floor.py --docs CybergyHoldingsInc_20140520_10-Q_EX-10.27_8605784_EX-10.27_Affiliate_Agreement
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

# Disable delivery BEFORE importing the runner (import-bound; app.config toggle would be a no-op).
import app.delivery.delivery_step as _dstep  # noqa: E402

_dstep.MCP_DELIVERY_ENABLED = False

import app.graph.nodes.clause_splitter_agent as _splitter  # noqa: E402
from app.runner.core import run_pipeline  # noqa: E402
from eval.harness.matcher import match, overlap  # noqa: E402
from eval.harness.schema import load_gold, read_manifest  # noqa: E402

# Default demonstrator docs (moderate size, gate-triggering, with material misses). CybergyHoldings is
# the flagship: 5 cap_on_liability misses → ClauseType.liability, which is ALREADY in the recall floor,
# so restoring typing should rescue them via the existing mechanism (cleanest possible proof).
DEFAULT_DOCS = [
    "CybergyHoldingsInc_20140520_10-Q_EX-10.27_8605784_EX-10.27_Affiliate_Agreement",
    "ArconicRolledProductsCorp_20191217_10-12B_EX-2.7_11923804_EX-2.7_Trademark_Licen",
]
BASELINE_RUN = "eval/runs/20260817-190549"


def _detect(findings: list, gold_clauses: list) -> tuple:
    """tp/fn over should_flag gold clauses + the set of matched gold text_snippets (for fn→tp diff)."""
    res = match(findings, gold_clauses)
    matched = {id(g) for _f, g in res.matches}
    tp = fn = 0
    flagged_snippets = set()
    for g in gold_clauses:
        if not g.should_flag:
            continue
        if id(g) in matched:
            tp += 1
            flagged_snippets.add(g.text_snippet)
        else:
            fn += 1
    return tp, fn, flagged_snippets


def _clause_views(clauses: dict) -> list:
    """Flatten final_state['clauses'] into per-clause verdict views (incl. clause_type, which
    build_sidecar drops) so a rescued gold clause can be traced to its recall-floor signature."""
    out = []
    for rec in clauses.values():
        ct = rec.get("clause_type")
        out.append({
            "text": rec.get("text"),
            "clause_type": getattr(ct, "value", ct),
            "relevance_verdict": rec.get("relevance_verdict"),
            "isrel_verdict": rec.get("isrel_verdict"),
            "issup_verdict": rec.get("issup_verdict"),
            "final_status": getattr(rec.get("final_status"), "value", rec.get("final_status")),
        })
    return out


def _trace_rescue(snippet: str, views: list) -> dict:
    """Best-overlap treatment clause for a rescued gold snippet + whether it validated via the recall
    floor. The 027 floor path is the signature relevance=True, isrel=None, issup=None, validated —
    distinguishing a floor rescue from a plain ISSUP/ISREL pass or a better-boundary match."""
    best, best_ov = None, 0.0
    for v in views:
        ov = overlap(v["text"], snippet)
        if ov >= 0.6 and ov > best_ov:
            best, best_ov = v, ov
    if best is None:
        return {"clause_type": None, "via_floor": None}
    via_floor = (best["relevance_verdict"] is True and best["isrel_verdict"] is None
                 and best["issup_verdict"] is None
                 and str(best["final_status"]).endswith("validated"))
    return {"clause_type": best["clause_type"], "final_status": best["final_status"],
            "isrel": best["isrel_verdict"], "issup": best["issup_verdict"], "via_floor": via_floor}


def run_doc(gid: str, manifest: dict, baseline_run: Path, out_root: Path, llm_max: int) -> dict:
    entry = manifest.get(gid)
    if not entry:
        return {"gid": gid, "error": "not in baseline manifest"}
    gold = load_gold(entry["gold"])
    doc_path = BACKEND_DIR / gold.document

    # Baseline (cached). clause_type per-clause isn't persisted in the sidecar, so baseline typing is
    # measured on the surfaced findings (a proxy — the ~0 whole-corpus rate is established separately).
    base_report = json.loads((baseline_run / entry["report"]).read_text(encoding="utf-8"))
    b_findings = base_report.get("findings", [])
    b_tp, b_fn, b_snips = _detect(b_findings, gold.clauses)
    b_typed_findings = sum(1 for f in b_findings if f.get("clause_type") is not None)

    # Treatment: force LLM typing by raising the Lever-A gate for this run.
    prev = _splitter.CLAUSE_SPLITTER_LLM_MAX_CLAUSES
    _splitter.CLAUSE_SPLITTER_LLM_MAX_CLAUSES = llm_max
    t0 = time.monotonic()
    try:
        result = run_pipeline(document_path=str(doc_path), original_filename=doc_path.name)
    finally:
        _splitter.CLAUSE_SPLITTER_LLM_MAX_CLAUSES = prev
    elapsed = time.monotonic() - t0

    report_json = Path(result.report_path).with_suffix(".json") if result.report_path else None
    if report_json and not report_json.is_absolute():
        report_json = BACKEND_DIR / report_json
    t_report = json.loads(report_json.read_text(encoding="utf-8")) if report_json and report_json.exists() else {}
    t_findings = t_report.get("findings", [])
    t_tp, t_fn, t_snips = _detect(t_findings, gold.clauses)

    # clause_type coverage across ALL clauses in the treatment run (the direct root-cause metric).
    clauses = result.final_state.get("clauses", {})
    views = _clause_views(clauses)
    typed = sum(1 for v in views if v["clause_type"] is not None)
    n_clauses = len(clauses)

    # Trace each rescued clause: did it validate via the recall floor (floor-attribution, not just a
    # better-matching boundary)?
    rescued = sorted(t_snips - b_snips)
    rescued_trace = [{"snippet": s[:100], **_trace_rescue(s, views)} for s in rescued]

    # Persist treatment artifacts for inspection.
    out_dir = out_root / gid
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "report.json").write_text(json.dumps(t_report, indent=2), encoding="utf-8")

    return {
        "gid": gid,
        "n_clauses": n_clauses,
        "typed": typed,
        "baseline_typed_findings": b_typed_findings,
        "baseline_n_findings": len(b_findings),
        "elapsed_s": round(elapsed, 1),
        "baseline": {"tp": b_tp, "fn": b_fn},
        "treatment": {"tp": t_tp, "fn": t_fn},
        "rescued": rescued,                     # gold clauses that flipped fn→tp
        "rescued_trace": rescued_trace,         # floor-attribution per rescued clause
        "lost": sorted(b_snips - t_snips),      # any regressions (tp→fn)
    }


def _pct(n, d):
    return "N/A" if not d else f"{100 * n / d:.0f}%"


def main() -> None:
    ap = argparse.ArgumentParser(description="Measure clause-type restoration → recall-floor effect.")
    ap.add_argument("--docs", nargs="*", default=DEFAULT_DOCS, help="gold_ids to test (default: 2 demonstrators)")
    ap.add_argument("--baseline", default=BASELINE_RUN, help="cached baseline run dir")
    ap.add_argument("--llm-max", type=int, default=500, help="raised Lever-A gate for treatment (default 500)")
    ap.add_argument("--out", default=None, help="treatment output dir (default: <baseline>/exp_clausetype)")
    args = ap.parse_args()

    baseline_run = Path(args.baseline)
    manifest = read_manifest(baseline_run)
    out_root = Path(args.out) if args.out else baseline_run / "exp_clausetype"
    out_root.mkdir(parents=True, exist_ok=True)

    print(f"Baseline: {baseline_run}   treatment gate CLAUSE_SPLITTER_LLM_MAX_CLAUSES={args.llm_max}")
    print(f"Docs: {len(args.docs)}   (delivery OFF; live Ollama)\n")

    results = []
    for gid in args.docs:
        print(f"[run] {gid} …", flush=True)
        try:
            r = run_doc(gid, manifest, baseline_run, out_root, args.llm_max)
        except Exception as exc:  # noqa: BLE001 — isolate per-doc so one failure doesn't lose the run
            r = {"gid": gid, "error": f"{type(exc).__name__}: {exc}"}
            print(f"  ! pipeline error: {exc}")
        results.append(r)
        (out_root / "summary.json").write_text(  # persist after each doc (long run resilience)
            json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")
        if "error" in r:
            continue
        print(f"  clause_type coverage: treatment {r['typed']}/{r['n_clauses']} "
              f"({_pct(r['typed'], r['n_clauses'])})  |  baseline typed findings "
              f"{r['baseline_typed_findings']}/{r['baseline_n_findings']}   ({r['elapsed_s']}s)")
        print(f"  detection tp/fn:  baseline {r['baseline']['tp']}/{r['baseline']['fn']}  "
              f"->  treatment {r['treatment']['tp']}/{r['treatment']['fn']}")
        print(f"  rescued (fn->tp): {len(r['rescued'])}   regressions (tp->fn): {len(r['lost'])}")
        for t in r["rescued_trace"]:
            fl = "via FLOOR" if t["via_floor"] else f"via {t.get('final_status')}(isrel={t.get('isrel')},issup={t.get('issup')})"
            print(f"     + [{t['clause_type']}] {fl}: {t['snippet']}")
        for s in r["lost"]:
            print(f"     - REGRESSION: {s[:100]}")

    (out_root / "summary.json").write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")
    ok = [r for r in results if "error" not in r]
    tot_rescued = sum(len(r["rescued"]) for r in ok)
    tot_lost = sum(len(r["lost"]) for r in ok)
    print("\n" + "=" * 64)
    print(f"TOTAL rescued (fn->tp): {tot_rescued}   regressions (tp->fn): {tot_lost}   over {len(ok)} docs")
    print(f"clause_type coverage (treatment): {sum(r['typed'] for r in ok)}/{sum(r['n_clauses'] for r in ok)}")
    print("Coverage still ~0 + 0 rescued ⇒ raising the gate does NOT restore typing (naive fix falsified);")
    print("the LLM grouping call went off-schema. NOTE: this shows the NEGATIVE half only — the positive")
    print("'typing→floor rescue' half needs a successful-typing run (feature-042 validation).")
    print(f"Artifacts + summary.json under {out_root}")
    print("=" * 64)


if __name__ == "__main__":
    main()
