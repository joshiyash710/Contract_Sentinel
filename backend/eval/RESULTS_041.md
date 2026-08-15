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

## 3. Evaluation smoke (live pipeline → score, delivery off)

Ran the real 7-node pipeline (local qwen3:8b + bge-m3) over a small subset of the candidate gold set
against the new KB, then scored offline. Demonstrates the full run → match → score path (per-type
breakdown + bootstrap CIs) on genuine pipeline output. **No Drive/Gmail delivery occurred.**

_Initial 1-document smoke (ADUROBIOTECH consulting agreement, candidate labels):_

| Metric | Value |
|---|---|
| Detection precision | 100.0% (n=3) |
| Detection recall | 42.9% (n=7) |
| F1 | 60.0% |
| Miss rate | 57.1% |
| False-flag rate | 0.0% (n=2) |
| Severity within-one | 100.0% (exact 0.0%, n=3) |

Per-type breakdown spanned 7 clause types (e.g. `ip_ownership_assignment` recall 33%,
`termination_for_convenience` 100%, `governing_law`/`expiration_date` clean → false-flag 0%). Per-node
latency (this doc): redline ~83s, self_rag ~57s, clause_splitter ~38s, crag ~18s, risk ~16s.

CIs are degenerate `[x, x]` at n=1 document (the bootstrap resamples documents — the independent
unit); a multi-document run yields non-degenerate intervals. **The full ≥25-document measurement is a
longer offline job (~1–2 h on the local 8B box) and remains deferred**, as do lawyer-confirmed labels.

## 4. What's proven vs. deferred

- **Proven:** corpus expansion (109→1,431, license-clean, provenance-documented); additive metadata
  preserved end-to-end into the sidecar; the runtime CRAG retriever loads the new index unchanged;
  the eval harness produces per-clause-type metrics + document-level bootstrap CIs on real pipeline
  output; 0.73 threshold validated on the new distribution.
- **Deferred (needs human / long run):** lawyer-confirmation of the candidate gold labels; the full
  ≥25-document accuracy run to replace these indicative numbers with authoritative, CI-bounded ones.
