# Feature 047 — AC-10 measurement results & default decision

**Date:** 2026-08-23 · Feature MERGED (`bbc81ae0`); this measurement follows (Task 8-style).

## What was measured
Whether the tolerant grouping parser lets the model's `clause_type` flow through and re-arms the 027
recall floor end-to-end, lifting recall on floor-type clauses (`liability`/`termination`/
`intellectual_property`/`confidentiality`). Two A/Bs (tolerant ON vs OFF; ON = new default at build time):

1. **Arconic — Groq gpt-oss-120b** (`eval/runs/20260823-114719` ON vs cached `20260822-005604` OFF, same
   model). Both clean.
2. **Cerence — local qwen3:4b** (`eval/runs/20260823-123102` ON vs `20260823-124055` OFF, same model),
   run locally to dodge the Groq token cap.

(Cerence via Groq was attempted for the ON side but **degraded** — the raised `num_predict=4096` + gpt-oss
reasoning tokens pushed 2 docs past Groq's **200K-tokens/day** cap; the informative doc was starved.)

## Results

**Arconic (gpt-oss-120b), ON vs OFF:**
| Metric | OFF (strict) | ON (tolerant) |
|---|---|---|
| Recall | 20.0% (tp=1/fn=4) | 20.0% (tp=1/fn=4) |
| Precision | 16.7% | 14.3% |
| fp_clean | 1 | 1 |

**Cerence (qwen3:4b), ON vs OFF:**
| Metric | OFF (strict) | ON (tolerant) |
|---|---|---|
| Recall | 87.5% (tp=7/fn=1) | 87.5% (tp=7/fn=1) |
| Precision | 26.9% | 28.0% |
| False-flag | 62.5% | 62.5% |
| cap_on_liability | 100% | 100% |
| ip_ownership_assignment | 100% | 100% |
| seen-but-discarded | 0 | 0 |

**No recall gain on either measurable doc; no gold-clean precision harm (fp_clean flat).**

## Why no delta (the crux)
Tolerant grouping only changes output when the model returns a **non-exact partition** (the case the
strict parser discards to regex). Neither measurable doc hit that case:
- **Arconic** has **zero floor-type gold clauses** (all `license_grant`/`governing_law`/`anti_assignment`/
  `audit_rights`/`covenant_not_to_sue`), so reviving the floor cannot affect it by construction.
- **Cerence + qwen3:4b** produced (near-)**exact partitions**, so strict already succeeded → `clause_type`
  already flowed → floor-types already caught in strict mode; tolerant = strict here (AC-2).
- The case 047 actually fixes — **gpt-oss returning partial partitions on large docs** — is exactly the
  token-capped scenario. Telling cross-model clue: in the cached Groq run, **gpt-oss *strict* MISSED
  `cap_on_liability` on Cerence (0%)** while **qwen3:4b strict caught it (100%)** — consistent with
  gpt-oss's partial grouping falling back to regex there (what 047 would recover), but unproven end-to-end.

## Decision — ship default `False`
The **042 merge gate** requires recall to rise; it did **not** on measurable evidence, so
`CLAUSE_SPLITTER_LLM_TOLERANT_GROUPING` default is flipped to **`False`** (feature present, fully
reversible, zero behavior change; mirrors how 042 shipped). The mechanism is proven at the probe/unit
level (gpt-oss returns valid partial groupings with correct floor-types; the tolerant parser applies
them) but its practical recall benefit for the target case is unmeasured.

**Follow-up (after quota/paid tier):** run a gpt-oss **single-doc** large-doc A/B (Cerence tolerant ON
vs cached strict OFF) — 1 doc fits the 200K/day budget — and if recall rises with false-flag rise ≤ +5pp,
flip the default to `True`. Cached OFF baseline: `eval/runs/20260822-005604` (Cerence).
