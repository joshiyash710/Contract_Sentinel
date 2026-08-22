# Feature 046 — AC-9 live measurement results

**Date:** 2026-08-22 · **Feature:** MERGED (`26a17582..6ab3dd49`) · Measurement is post-merge (Task 8).

## What was measured
The provider adapter routes the 5 generative call sites to **Groq `openai/gpt-oss-120b`** (embeddings
stay local on `bge-m3`, §8). AC-9 compares this against the **local qwen3:8b** baseline on the 6-doc
large subset, to test whether the strongest available model moves accuracy — in particular whether the
`cap_on_liability` misses flip fn→tp.

Cached artifacts (local only — `eval/runs/**` is gitignored):
- **AFTER** (Groq gpt-oss-120b): `eval/runs/20260822-005604` — `LLM_PROVIDER=groq`, gold `eval/gold_046subset`.
- **BEFORE** (qwen3:8b): `eval/runs/BEFORE_042subset`.
- Reproduce: `LLM_PROVIDER=groq python -X utf8 -m eval.harness.run --gold eval/gold_046subset` then
  `python -X utf8 -m eval.harness.score <run_dir>` (Ollama up with `bge-m3`).

## ⚠ Only 4 of 6 docs are valid — Groq free-tier daily token cap
The Groq free tier enforces a **200,000 tokens/day (TPD)** limit. A single 6-doc run exhausts it: the
last two docs hit repeated `groq.RateLimitError: 429 … tokens per day (TPD): Limit 200000` that a
per-day cap cannot clear inside SDK retries, so they fell back to failsafe/degraded output:
- **CybergyHoldings** — 429-starved: clauses dropped before scoring → `0 findings` (not degraded-flagged,
  but empty).
- **FuseMedical** — `analysis_degraded=True`, `failsafe_count=22` (all-High failsafe).

Both are **excluded** from the comparison (including them would inflate recall + destroy precision via
the all-High failsafe, and zero recall via the empty doc). The comparison below is the **same 4 clean
docs on both sides**: Arconic, Armstrong, Bellring, Cerence.

## Results (4 clean docs, before → after)

| Metric | BEFORE (qwen3:8b) | AFTER (gpt-oss-120b) | Δ |
|---|---|---|---|
| Precision | 26.3% | 26.3% | tie |
| Recall | 17.9% | 17.9% | tie |
| F1 | 21.3% | 21.3% | tie |
| False-flag rate | 21.4% | 25.0% | +3.6pp (within noise) |
| tp / fn / fp_clean | 5 / 23 / 6 | 5 / 23 / 7 | tie |
| **Severity exact** | **20.0%** | **80.0%** | **+60pp** |
| Severity within-one | 100% | 100% | tie |

95% bootstrap CIs are very wide at n=4 (e.g. false-flag BEFORE 0.0–51.6%). Candidate-labeled corpus —
indicative, not lawyer-confirmed (026/041 framing).

## Findings — honest read
1. **The strongest model did NOT move recall or precision** — statistically identical (tp=5, fn=23 on
   both). This is *expected* from the 041/042 root-cause: **recall is bottlenecked upstream** of
   generation — the Self-RAG relevance filter (`seen-but-discarded=22`) and `clause_type=None`
   (deterministic typing shipped OFF ⇒ 027 recall floor inert). A better generator can only judge
   clauses that survive those stages; it cannot recover clauses already dropped before it runs.
2. **The one real win is severity grading: 80% vs 20% exact.** When gpt-oss flags a clause it grades
   the risk level far more accurately.
3. **The `cap_on_liability` hypothesis did NOT reproduce here:** on the single cap_on_liability clause
   in this subset qwen3:8b caught it (100%) and gpt-oss missed it — but n=1, noise not signal. gpt-oss
   did gain `covenant_not_to_sue` (0%→40%, n=5).
4. **Confounds:** gpt-oss's clause-*grouping* JSON is malformed (concatenated indices) → it falls back
   to regex splitting (same clause set as baseline), so its segmentation was never exercised; and n=4
   makes every aggregate CI very wide.

## Decision
- **Keep `LLM_PROVIDER` default `ollama`** (already shipped that way). Given the recall/precision tie,
  routing contract text to a third party (privacy cost, spec §1) plus the free-tier daily token cap
  buys nothing on the headline metrics. Groq stays a reversible opt-in; its genuine value is severity
  grading.
- **Next real lever is upstream, not the model.** The accuracy ceiling on this corpus is set by
  segmentation + the Self-RAG relevance drop, not generative quality — the correct target for the next
  feature (see the seen-but-discarded diagnostic).
- **Deployment note:** the 200K tokens/day free-tier cap is a hard product constraint — a single 6-doc
  eval nearly exhausts a day's budget. Documented for `docs/DEPLOYMENT.md`.
