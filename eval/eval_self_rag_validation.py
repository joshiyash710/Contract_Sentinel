"""
Task 12 live smoke / eval harness for Self-RAG validation (Node 4, feature 006).

Drives `self_rag_validation_agent` with a LIVE Ollama (qwen3:14b) against a small,
hand-built set of CRAG-shaped clauses that deliberately exercise every real branch:

  - Branch C (evidence present) → full Relevance → ISREL → ISSUP gate
      * a plainly risky clause (expect VALIDATED)
      * a balanced/standard clause (expect DISCARDED via ISSUP-false or ISREL-false)
      * boilerplate filler (expect DISCARDED via Relevance-false short-circuit)
  - Branch A (empty evidence + high-risk clause_type) → rescue: Relevance → ISSUP-on-text
  - Branch B (empty evidence + non-high-risk clause_type) → zero-LLM DISCARD (no LLM call)

We invoke Node 4 directly on synthetic CRAG output (rather than the full Node 1→4
graph) so the smoke does not depend on CRAG's live web search / KB — Task 12 explicitly
permits mocking embedding + web. The purpose of this step (tasks.md Task 12 "Why") is to
validate real Qwen3 judgment quality, prompt wording, and the true latency envelope of
Node 4 — all of which this exercises with live LLM calls.

Run from the repo root:  python eval/eval_self_rag_validation.py
Requires: Ollama running with qwen3:14b pulled.
"""

import os
import sys
import time

# Make `app` importable (it lives under backend/).
_REPO_ROOT = os.path.dirname(os.path.abspath(__file__))
_BACKEND = os.path.join(os.path.dirname(_REPO_ROOT), "ContractSentinel", "backend")
if not os.path.isdir(_BACKEND):
    _BACKEND = os.path.join(os.path.dirname(_REPO_ROOT), "backend")
sys.path.insert(0, _BACKEND)

from app.graph.nodes.self_rag_validation_agent import self_rag_validation_agent  # noqa: E402
from app.graph.state import ValidationStatus  # noqa: E402
import app.config as config  # noqa: E402


def _ev(text, src):
    return {"snippet_text": text, "source_reference": src}


# ── Hand-built CRAG-shaped clauses (one per intended branch) ─────────────────
CLAUSES = {
    "clause_001": {
        "position": 1,
        "clause_type": "liability",
        "text": (
            "The Supplier's total aggregate liability under this Agreement shall be "
            "UNLIMITED, and the Customer waives any and all statutory caps on damages, "
            "including for consequential, indirect, and punitive losses of any kind."
        ),
        "evidence_snippets": [
            _ev(
                "Market-standard commercial contracts cap aggregate liability at 12 "
                "months of fees; uncapped liability is a material red flag for the "
                "party bearing it.",
                "practical-law/liability-caps",
            ),
        ],
        "expect": "VALIDATED (branch C: risky, uncapped liability)",
    },
    "clause_002": {
        "position": 2,
        "clause_type": "payment",
        "text": (
            "Payment shall be made within thirty (30) days of receipt of a valid "
            "invoice. Undisputed amounts not paid when due may accrue interest at a "
            "commercially reasonable rate."
        ),
        "evidence_snippets": [
            _ev(
                "Net-30 payment terms with reasonable late-payment interest are a "
                "standard, balanced commercial arrangement.",
                "practical-law/payment-terms",
            ),
        ],
        "expect": "DISCARDED (branch C: standard/balanced clause)",
    },
    "clause_003": {
        "position": 3,
        "clause_type": "general",
        "text": "ARTICLE 4",
        "evidence_snippets": [
            _ev("Section headers carry no substantive obligation.", "n/a"),
        ],
        "expect": "DISCARDED (branch C: Relevance-false short-circuit on filler)",
    },
    "clause_004": {
        "position": 4,
        "clause_type": "intellectual_property",
        "text": (
            "All intellectual property created by the Contractor during the term, "
            "whether or not related to the Services, is hereby irrevocably assigned "
            "to the Company with no additional compensation."
        ),
        "evidence_snippets": [],  # empty → high-risk rescue (Branch A)
        "expect": "VALIDATED (branch A rescue: high-risk empty-evidence, ISSUP-on-text)",
    },
    "clause_005": {
        "position": 5,
        "clause_type": "general",
        "text": (
            "Section headings in this Agreement are for convenience of reference only "
            "and shall not affect the interpretation of any provision."
        ),
        "evidence_snippets": [],  # empty → non-high-risk zero-LLM discard (Branch B)
        "expect": "DISCARDED (branch B: non-high-risk empty-evidence, zero-LLM)",
    },
    "clause_006": {
        "position": 6,
        "clause_type": "termination",
        "text": (
            "The Company may terminate this Agreement at any time, for any reason or "
            "no reason, effective immediately upon notice, with no cure period and no "
            "liability for termination, while the Contractor may not terminate for "
            "any reason."
        ),
        "evidence_snippets": [
            _ev(
                "Unilateral, immediate, no-cure termination rights granted to only "
                "one party are a well-recognized one-sided risk.",
                "practical-law/termination-rights",
            ),
        ],
        "expect": "VALIDATED (branch C: one-sided termination right)",
    },
}


def main():
    state = {
        "document_id": "smoke-006",
        "clauses": {cid: {k: v for k, v in rec.items() if k != "expect"}
                    for cid, rec in CLAUSES.items()},
    }

    print("=" * 78)
    print("Task 12 live smoke — Self-RAG validation (Node 4) — model:", config.OLLAMA_MODEL_NAME)
    print("Config: MAX_ATTEMPTS=%d  TIMEOUT=%ds  CB_THRESHOLD=%d  HIGH_RISK=%s"
          % (config.SELF_RAG_MAX_ATTEMPTS, config.SELF_RAG_TIMEOUT_SECONDS,
             config.SELF_RAG_LLM_CIRCUIT_BREAKER_THRESHOLD,
             sorted(config.SELF_RAG_HIGH_RISK_CLAUSE_TYPES)))
    print("=" * 78)

    t0 = time.monotonic()
    out = self_rag_validation_agent(state)
    wall = time.monotonic() - t0

    updates = out["clauses"]
    n = len(updates)
    validated = discarded = 0
    retry_dist = {}
    discard_reasons = {"relevance_false": 0, "isrel_false": 0, "issup_exhausted": 0,
                       "zero_llm": 0, "other": 0}

    for cid in sorted(updates, key=lambda c: CLAUSES[c]["position"]):
        v = updates[cid]
        fs = v["final_status"]
        status = fs.value if isinstance(fs, ValidationStatus) else fs
        if fs == ValidationStatus.VALIDATED:
            validated += 1
        else:
            discarded += 1
            if v["relevance_verdict"] is False:
                discard_reasons["relevance_false"] += 1
            elif v["isrel_verdict"] is False:
                discard_reasons["isrel_false"] += 1
            elif v["issup_verdict"] is False and v["retry_count"] is not None:
                discard_reasons["issup_exhausted"] += 1
            elif all(v[k] is None for k in ("relevance_verdict", "isrel_verdict",
                                            "issup_verdict", "retry_count")):
                discard_reasons["zero_llm"] += 1
            else:
                discard_reasons["other"] += 1
        rc = v["retry_count"]
        retry_dist[rc] = retry_dist.get(rc, 0) + 1

        print(f"\n{cid} (pos {CLAUSES[cid]['position']}, type={CLAUSES[cid]['clause_type']})")
        print(f"  expect : {CLAUSES[cid]['expect']}")
        print(f"  actual : status={status}  relevance={v['relevance_verdict']}  "
              f"isrel={v['isrel_verdict']}  issup={v['issup_verdict']}  "
              f"retry_count={v['retry_count']}")

    print("\n" + "=" * 78)
    print("AGGREGATE (spec §9)")
    print(f"  total clauses      : {n}")
    print(f"  validated          : {validated}  ({validated/n:.0%} validation rate)")
    print(f"  discarded          : {discarded}")
    print(f"  discard reasons    : {discard_reasons}")
    print(f"  retry distribution : {retry_dist}")
    print(f"  node_timings       : {out['node_timings']}")
    print(f"  current_node       : {out['current_node']}")
    print(f"  error_count present: {'error_count' in out}  "
          f"(expected False — breaker should not open on healthy Ollama)")
    print(f"  wall clock         : {wall:.2f}s  "
          f"(avg {wall/n:.2f}s/clause vs timeout {config.SELF_RAG_TIMEOUT_SECONDS}s)")
    print("=" * 78)

    # Task 12 sanity assertions
    problems = []
    if not all("final_status" in v for v in updates.values()):
        problems.append("some clause missing final_status")
    if validated == 0 or discarded == 0:
        problems.append("expected a MIX of VALIDATED and DISCARDED")
    if wall / n >= config.SELF_RAG_TIMEOUT_SECONDS:
        problems.append("avg per-clause latency not well under timeout")
    if "error_count" in out:
        problems.append("error_count present — breaker opened unexpectedly")

    if problems:
        print("SMOKE RESULT: ATTENTION —", "; ".join(problems))
        sys.exit(1)
    print("SMOKE RESULT: SANE — every clause has final_status, mix of outcomes, "
          "latency well under timeout, no spurious error_count.")


if __name__ == "__main__":
    main()
