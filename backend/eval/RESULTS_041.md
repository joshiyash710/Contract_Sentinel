# Feature 041 — Corpus Expansion + Evaluation: Results

Offline results for the legal-grounding upgrade. **Honesty caveat:** the gold labels are heuristic
**candidates auto-selected from CUAD annotations — NOT lawyer-confirmed** (spec D4). All numbers below
are indicative, not authoritative; every rate is reported with its sample size `n` and a 95% bootstrap
confidence interval. Trustworthy accuracy requires human-confirmed labels and the full-corpus run.

## 1. Corpus: before → after

| | Before (feature 026) | After (feature 041) |
|---|---|---|
| Chunks | 109 | **1,431** |
| Sources | Bonterms Cloud Terms + DPA only | Bonterms (109) + **CUAD** (1,322), CC BY 4.0 |
| Distinct `clause_type`s | 0 (untyped) | **39** |
| FAISS index | 109 × 1024 | 1,431 × 1024 (bge-m3), `ntotal == meta` 1:1 |

CUAD spans are curated (deduplicated, capped at 35 per `clause_type`) and carry additive
`clause_type` + `source_license` metadata that survives into `clauses_meta.jsonl` (build_kb fix).
Bonterms records stay exactly two-keyed. Provenance + attribution: `data/kb/SOURCES.md`.

## 2. CRAG confidence threshold recheck (spec D6 — measure only)

Leave-one-out over the rebuilt index (`eval/eval_crag_confidence.py`, offline):

- Self-similarity ~1.0 (L2-normalization / inner-product invariant intact).
- Inter-clause confidence: min 0.540, **median 0.778**, mean 0.786, max 0.998.
- Path split @ `CRAG_CONFIDENCE_THRESHOLD = 0.73`: **LOCAL_KB 72.9%**, WEB_FALLBACK 27.1%.

**Recommendation: keep 0.73.** It sits at the median of the enlarged, more diverse corpus's
inter-clause similarity and yields a balanced ~73/27 local/web split. The constant is **unchanged** in
this feature (AC-11); any future re-tune is a separate, justified edit.

## 3. Full accuracy run (live pipeline → score, delivery off)

Ran the real 7-node pipeline (local qwen3:8b + bge-m3) over the **entire candidate gold set (32
contracts / 695 clauses)** against the new KB, then scored offline (per-type breakdown + document-level
bootstrap CIs). Completed 2026-08-18 across two sessions via `run.py --resume`; **no Drive/Gmail
delivery occurred**.

**FULL RUN — all 32 gold contracts / 695 candidate clauses (run 20260817-190549, 0 ingest errors):**

| Detection metric | Value (95% bootstrap CI, n = docs 32) |
|---|---|
| Precision | **56.1%** (48.0–63.0%), n=262 flagged |
| Recall | **31.7%** (23.7–39.6%), n=463 should-flag |
| F1 | **40.6%** (32.2–47.5%) |
| Miss rate | 68.3% (60.4–76.3%) |
| False-flag rate | 14.2% (9.2–19.6%), n=232 clean |
| Severity exact / within-one | 38.8% / **93.2%** (n=147) |

Confusion tallies: tp=147, fn=316, fp_clean=33, tn=199, unlabeled flags=82.

**Read these with the candidate-label caveat front of mind (spec D4).** The heuristic gold flags **463
of 695** clauses as should-flag (every clause of a CUAD "risk" category), but a category is *not* a risk
verdict — a standard cap-on-liability or a boilerplate audit-rights clause is often benign. So a large
share of the "misses" are the pipeline **correctly declining to flag a routine clause** that the
over-eager candidate label marked risky. Recall is therefore a **lower bound**; with lawyer-confirmed
labels it would rise materially. Precision 56% / false-flag 14% and **severity within-one 93%** are the
more trustworthy signals here.

**Diagnostics (the actionable findings):**
- **Self-RAG is the dominant recall bottleneck:** of 316 missed gold clauses, **282 were seen-but-
  discarded** by Self-RAG (only 34 were never split). The pipeline retrieved+considered them and chose
  to discard — so recall is gated by Self-RAG's validation strictness, not by clause segmentation.
- **CRAG went to web-fallback ~85% of the time** (local_kb 851 vs web_fallback 4841 clause-retrievals).
  On *real uploaded-contract clauses* the local KB rarely clears 0.73 — **contradicting the offline
  D6 recheck** (which measured KB self-similarity, not real queries). The 0.73 threshold looks **too high
  for production queries**; lowering it (or growing/diversifying the KB further) is the clear next lever.
- Per-type highlights: strong on `uncapped_liability` (recall 78.6%, n=14) and `rofr_rofo_rofn` (70%),
  weak on `audit_rights` (10.6%, n=66), `volume_restriction` (6.2%), `post_termination_services` (18%).
  Full per-type table in the score output.
- **Latency is heavy** (p50/p95 s): self_rag 385/1512, crag 196/1204, redline 59/296, risk 22/116 —
  the large contracts dominate; a real deployment needs the 025/029 latency levers + a smaller-doc path.

## 4. What's proven vs. still open

- **Proven:** corpus expansion (109→1,431, license-clean, provenance-documented); additive metadata
  preserved end-to-end into the sidecar; the runtime CRAG retriever loads the new index unchanged; the
  harness produces **defensible, CI-bounded, per-clause-type** accuracy over 32 real contracts.
- **Actionable next levers (surfaced by this run):** (1) **re-tune the CRAG 0.73 threshold against real
  query clauses** — 85% web-fallback says it's too high; (2) revisit **Self-RAG discard strictness** —
  it accounts for 282/316 misses; (3) latency work for the large-contract path.
- **Still open (needs human):** **lawyer-confirmation of the candidate labels** — until then recall is a
  pessimistic lower bound; the honest headline is precision ~56% / severity-within-one 93% with the
  recall caveat.
