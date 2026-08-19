# Feature 042 — AC-7 measurement results & merge decision

**Date:** 2026-08-19 · **Branch:** `feature/042-deterministic-clause-typing`

## What was measured
The deterministic clause-type fallback (fill `clause_type` from a conservative keyword tagger when
the ClauseSplitter LLM refinement left it `None`) was measured on the **large-doc regime** the fix
targets — the 6-doc subset where regex clause count > `CLAUSE_SPLITTER_LLM_MAX_CLAUSES` (40) and
baseline typing is ~0:

- Arconic (Trademark License), ArmstrongFlooring (IP), BellringBrands (Manufacturing),
  Cerence (IP), CybergyHoldings (Affiliate), FuseMedical (Distributor).

Cached artifacts (local only — `eval/runs/**` is gitignored, not committed):
- **BEFORE** (flag-off): `eval/runs/BEFORE_042subset` — the 6 docs sliced from cached run
  `eval/runs/20260817-190549`.
- **AFTER** (flag-ON): `eval/runs/20260818-230210` — fresh live run, `DETERMINISTIC_CLAUSE_TYPING_ENABLED=True`.
- Reproduce: copy the 6 gold files (Arconic/Armstrong/Bellring/Cerence/Cybergy/FuseMedical) from
  `eval/gold/` into a subset dir, then `python -X utf8 -m eval.harness.run --gold <subset>` (flag on)
  and `python -X utf8 -m eval.harness.score <run_dir>`.

## Results (6-doc large subset, before → after)

| Metric | BEFORE (flag-off) | AFTER (flag-ON) | Δ |
|---|---|---|---|
| **Recall** | 15.2% (7/46) | 32.6% (15/46) | **+17.4pp** |
| **False-flag rate** | 15.0% (6/40) | 32.5% (13/40) | **+17.5pp** |
| Precision | 25.9% (n=27) | 19.0% (n=79) | −6.9pp |
| F1 | 19.2% | 24.0% | +4.8pp |
| Severity exact / within-one | 14.3% / 100% | 26.7% / 93.3% | — |
| Self-RAG seen-but-discarded | 38 | 25 | −13 |
| **027 floor-rescue validations** | **0** | **66** | **+66** |
| Unlabeled flags | 14 | 51 | +37 |

95% bootstrap CIs (6 resampled docs): recall AFTER 32.6% (23.8–41.2%); false-flag AFTER 32.5%
(8.6–54.8%, wide at this n). Candidate-labeled corpus — indicative, not lawyer-confirmed (026/041 framing).

## Mechanism — PROVEN (the positive-half control the 041 experiment lacked)
- **027 floor-rescue signature** (`final_status=validated, relevance_verdict=True, isrel=None,
  issup=None`) went **0 → 66**, present in **all six** docs — the recall floor, inert on large docs
  before (the 041 root cause), now fires. Floor-type material is rescued: `cap_on_liability` recall
  16.7%→50%, `ip_ownership_assignment` 50%→100%, `anti_assignment` 36.4%→54.5%; seen-but-discarded 38→25.
- Note: the run **sidecar carries no `clause_type` field** (`SIDECAR_KEYS` omits it), so coverage was
  confirmed via the floor-rescue signature, not a sidecar coverage count.

## Merge gate (plan §6, D3) — **FAILS**
1. Recall RISES → ✓ (+17.4pp)
2. False-flag rises ≤ +5pp → **✗ (+17.5pp)**
3. Recall-gain (pp) ≥ false-flag-gain (pp) → **✗ (17.4 < 17.5)**

A ~1:1 true-vs-false trade (+8 tp, +7 fp_clean), not the favorable net win the gate requires.

## Decision: ship flag-OFF (default `False`)
`DETERMINISTIC_CLAUSE_TYPING_ENABLED` default flipped to `False`. The feature is present and fully
reversible; the mechanism is validated. **Follow-up (future):** tighten the phrase map — the main
false-flag culprits are the IP phrases `"intellectual property rights"` / `"proprietary rights"`
(match clean license-grant clauses) and the termination phrases `"expiration or termination"` /
`"termination of this agreement"` (match clean renewal/expiration boilerplate) — then re-measure the
6-doc subset and re-apply the gate before enabling by default.
