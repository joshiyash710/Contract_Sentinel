# Feature 041 — Legal-Grounding Upgrade: Corpus Expansion + Defensible Evaluation

## 1. Problem statement

ContractSentinel's two most-cited capabilities — "**Corrective RAG over a local legal knowledge base**"
and "**measured accuracy** (recall ~64% → 100%)" — are today both resting on a demo-sized substrate:

1. **The retrieval KB is one vendor's template.** `data/kb/clauses_corpus.jsonl` is **109 chunks, curated
   entirely from `app/db/Cloud-Terms.md` + `app/db/Data-Protection-Addendum.md`** (Bonterms standardized
   SaaS terms). For any contract that is not cloud-SaaS-shaped, CRAG retrieval contributes little real
   grounding and the risk judgment falls back to the 8B model's parametric knowledge. A tool that claims
   to ground contract-risk findings in a "legal knowledge base" must retrieve against a **broad, diverse,
   provenance-clean body of real clause language**, not a single template family.
2. **The accuracy numbers are computed on n=14.** The 026 evaluation harness is well-built, but the gold
   corpus is **2 contracts / 14 clauses total** (`eval/gold/heavy_contract.json` = 8, `sample_balanced.json`
   = 6). Every published rate (precision/recall/F1/miss/false-flag) is therefore statistically
   meaningless and, by the project's own notes, "±2-clause LLM-noisy." No accuracy claim can be defended
   from this sample size.

These are the **single biggest gap between "excellent engineering demo" and "serious legal AI"** (senior
review, 2026-08-15). This feature closes both at once, because they are one deliverable: **expanding the
corpus is only trustworthy if it is re-measured**, and the 026 harness already exists to do the measuring.

### Position relative to the constitution

**No amendment. NOT a graph node/edge. No `ContractState` change. No migration. No frontend. No runtime
retrieval-code behavior change.** This feature is **offline data + tooling**, exactly like features 005's
`build_corpus.py`/`build_kb.py` and 026's `eval/harness/`:

- The **runtime 7-node pipeline (§2) is untouched.** CRAG's `kb_retriever` keeps reading the same two
  required sidecar keys (`snippet_text`, `source_reference`); any new metadata keys are **additive** and
  ignored by the runtime retriever (§4, D3). Retrieval quality improves purely because the indexed corpus
  is larger and more diverse — **not** because node/edge/state code changed.
- The **§3 CRAG 0.73 confidence threshold stays a named config constant.** This feature *measures* whether
  the enlarged KB warrants re-tuning it and **reports a recommendation**, but does not silently change it;
  any change is a separate, justified config edit (D6).
- Files touched live under `backend/scripts/` (build tooling), `backend/data/kb/` (corpus data),
  `backend/eval/` (gold labels + harness scoring). Per §1 those are **not** `backend/app/` or
  `frontend/src/`, so §1's "no app code before approved spec+plan" gate is respected. Per §11 it is
  developed on `feature/041-legal-corpus-evaluation`. Per §7, the new pure scoring additions
  (per-type breakdown, bootstrap CIs) are TDD-unit-tested; the live pipeline run is the
  un-unit-testable part, as with 026.

## 2. Scope — two coupled parts on one branch

### Part A — Corpus expansion (retrieval grounding)

Grow `clauses_corpus.jsonl` from ~109 single-template chunks to a **diverse, provenance-clean reference
corpus of real contract clause language**, then rebuild the FAISS index.

- **A1 — Anchor source: CUAD** ([Contract Understanding Atticus Dataset](https://www.atticusprojectai.org/cuad),
  **CC BY 4.0**). 510 real commercial contracts with expert clause-span annotations across 41 legal
  categories. Its clause spans are ideal **retrieval reference material**, and each span carries a
  category label that becomes clean additive metadata (`clause_type`).
- **A2 — Optional secondary source: EDGAR material-contract exhibits** (SEC filings, **public domain**),
  used only if it adds category coverage CUAD lacks. Retained as a documented, reproducible fetch.
- **A3 — Retain the Bonterms corpus** (the current 109 chunks) so nothing regresses; the existing SaaS
  coverage stays.
- **A4 — Curation, not a dump.** Deduplicate near-identical spans, drop boilerplate/too-short spans
  (reuse `_MIN_SNIPPET_CHARS`), and **cap per-category counts** to keep the corpus balanced and the repo
  small — target **~800–1,500 committed chunks** spanning the 12 `ClauseType` enum categories plus CUAD's
  high-value risk categories (liability caps, indemnification, termination, IP assignment, non-compete,
  exclusivity, most-favored-nation, uncapped/uncapped-liability). Full-download reproducibility via a
  script; only the curated slice is committed.
- **A5 — Provenance + license manifest.** A committed `data/kb/SOURCES.md` (or `sources_manifest.json`)
  records, per source: name, URL, license, retrieval date, and the CC BY 4.0 attribution CUAD requires.
  A "serious legal AI" must have clean, auditable data provenance. **No copyrighted contract text is
  redistributed beyond what each source's license permits** (CUAD CC BY, EDGAR public domain).
- **A6 — Additive metadata.** Each corpus record MAY gain `clause_type`, `source_license`, and (where the
  source states it) `governing_law`/`jurisdiction`, **in addition to** the two required keys. This requires
  a **small `build_kb.py` change**: today its `_load_corpus()` reconstructs each record (the
  `records.append({...})` line) as only `{snippet_text, source_reference}` and writes exactly those to
  `clauses_meta.jsonl` — so any additive key
  would be silently dropped. `_load_corpus()` is extended to **preserve** the additive keys (still requiring
  the two mandatory ones) so they flow into `clauses_meta.jsonl` for the eval's per-type analysis (B2). This
  is a `backend/scripts/` change (not `backend/app/`), so §1 is unaffected. The runtime retriever still
  reads only the two required keys and ignores the extras (D3, AC-5).

### Part B — Defensible evaluation (measurement)

Make the accuracy numbers real by enlarging the gold set and hardening the 026 scorer's reporting.

- **B1 — Enlarge the gold corpus** from 2 → a **materially larger labeled set** (target **≥ 25 contracts /
  ≥ 250 labeled clauses**, both `should_flag:true` and `:false`), using the existing 026 gold schema
  (`eval/gold/*.json`). CUAD's category annotations are used to **select and pre-populate candidate**
  clauses for labeling; a **human confirms `should_flag`/`expected_severity`** — labels are **not**
  auto-derived from CUAD categories (a category is not a risk verdict) and **never** from the system's own
  output (026 D5, no circular "silver" labels). The honesty caveat: absent lawyer review, these are
  best-effort labels and the summary says so.
- **B2 — Per-clause-type metric breakdown.** Extend the 026 scorer to report detection precision/recall/F1
  and severity accuracy **broken down by `clause_type`**, so weaknesses are localized (e.g. "recall is
  fine on liability, poor on IP assignment") instead of hidden in one aggregate.
- **B3 — Confidence intervals.** Add **bootstrap (resampling) confidence intervals** to the headline
  detection rates so a number is reported as, e.g., "recall 0.78 (95% CI 0.69–0.86, n=250)" — turning
  "we think it works" into a defensible interval. Pure, deterministic given a fixed RNG seed; unit-tested.
- **B4 — Re-run + record.** Execute the 026 `run` → `score` flow over the enlarged gold set against the
  **new KB** (live Ollama) and commit the resulting `metrics.json` + a short written results note. This is
  the real, headline-worthy accuracy measurement the README currently overstates.
- **B5 — This feature builds NO new harness.** 026 owns the harness. 041 supplies **data** (gold labels)
  and **additive scoring reporting** (B2/B3). The `run`/`match`/two-phase mechanics are reused verbatim.

## 3. Resolved decisions (inline)

- **D1 — One feature, two coupled parts, one branch.** Corpus expansion (A) and evaluation (B) ship
  together because a bigger KB is only trustworthy once re-measured, and B's whole purpose is to validate
  A. plan.md MAY sequence them as Phase A then Phase B, but they are one reviewable deliverable.
- **D2 — Runtime pipeline is byte-behavior-unchanged.** No node/edge/state/migration/frontend/API change.
  Improvement comes from *data* (bigger, more diverse index) — not from changing how CRAG/Self-RAG/scoring
  run. This keeps the change low-risk and the 026 harness a valid before/after comparison.
- **D3 — Metadata is additive; the runtime retriever is not changed.** `kb_retriever` continues to require
  only `snippet_text` + `source_reference` and ignores any extra sidecar keys. New keys (`clause_type`,
  `source_license`, `jurisdiction`) are carried into `clauses_meta.jsonl` (via the small `build_kb.py`
  `_load_corpus()` extension, A6) for provenance and for the eval's per-type analysis (B2), but the
  **runtime** retriever does not read them in this feature. The change is confined to the offline
  `scripts/` build step, not the `app/` runtime. (Surfacing metadata into findings is a **future**
  feature, §6.)
- **D4 — CUAD for retrieval text is automatic; CUAD for risk labels is NOT.** CUAD spans → corpus chunks +
  `clause_type` metadata is a clean, automatic, license-clear win. But CUAD annotates clause *categories*,
  not risk severity — so gold `should_flag`/`expected_severity` are **human-confirmed**, using CUAD only to
  surface candidates. No circular labels (026 D5).
- **D5 — Provenance/license is a first-class deliverable (A5).** Committed source manifest with per-source
  license + CUAD CC BY attribution. Only license-permitted text is committed; the full corpus is
  reproducible from a fetch script, not bulk-committed.
- **D6 — Re-tuning the 0.73 CRAG threshold is measured and recommended, not silently applied.** The
  enlarged, more diverse KB changes the retrieval-confidence distribution. `eval/eval_crag_confidence.py`
  (existing) is re-run over the new index; the feature **reports** whether 0.73 still separates
  local-KB-confident from web-fallback clauses well, and recommends a value. The existing re-run driver is
  `backend/eval/eval_crag_confidence.py`. Any actual change to the §3 constant is a small,
  separately-justified config edit, not smuggled into the corpus rebuild.
- **D7 — Corpus source data lives under `data/`, not `app/`.** New raw/curated source inputs go under
  `backend/data/kb/sources/` (raw fetch gitignored; curated slice committed) so no file under
  `backend/app/` is written (§1). `build_corpus.py` (a script, not app code) is extended to read the
  Bonterms `app/db/*.md` **and** the new `data/kb/sources/*` inputs.
- **D8 — Committed corpus stays small; full is reproducible.** A `fetch_cuad.py` (or documented manual
  step) downloads CUAD to the gitignored raw dir; `build_corpus.py` curates + caps to the committed slice.
  This keeps repo size sane while making the corpus fully rebuildable (A4/A8).
- **D9 — Honesty carries into README + summaries.** README's "recall 64% → 100%" and KB claims are updated
  to the new, CI-bounded numbers with the sample size stated; the eval summary keeps the 026 "only as good
  as the corpus / not lawyer-reviewed" caveat. No number is published without its n and CI.

## 4. Acceptance criteria

### Corpus (Part A)
- **AC-1:** After running `build_corpus.py` → `build_kb.py`, `clauses_corpus.jsonl` contains **between 800
  and 1,500** curated chunks (floor for diversity, ceiling from the per-category cap / repo-size bound of
  A4/EC-7) spanning **≥ 12 distinct `clause_type` values** (verified by a committed count assertion / script
  output), and the Bonterms chunks are still present (no regression of existing coverage).
- **AC-2:** Every committed corpus record still has the two required keys (`snippet_text`,
  `source_reference`); records sourced from CUAD/EDGAR additionally carry `clause_type` + `source_license`,
  and after `build_kb.py` those additive keys are **present in `clauses_meta.jsonl`** (the sidecar), not
  stripped (A6). Conversely, Bonterms records that lack additive keys still round-trip with **exactly** the
  two required keys (no `null` `clause_type` injected) — the additive keys are optional, not mandatory. A
  pure unit test validates the corpus file's shape (required keys present, no empty snippets, additive
  keys well-formed where present, and absent-rather-than-null where a source omits them).
- **AC-3:** `data/kb/SOURCES.md` (or `sources_manifest.json`) exists and lists, per source: name, URL,
  license, retrieval date, and the CUAD CC BY 4.0 attribution. No source text is committed that its license
  disallows.
- **AC-4:** `build_kb.py` rebuilds the FAISS index from the enlarged corpus with **1:1 vector↔sidecar-row
  correspondence** preserved (existing invariant) and L2-normalized vectors (existing guard); index
  `ntotal` == corpus line count.
- **AC-5:** The runtime CRAG retriever is **unchanged** (`git diff` shows no change under
  `app/graph/nodes/retrievers/**` or any `app/**`); it loads the new index and returns evidence using only
  the two required keys (a retrieval smoke over the new index returns snippets for a sample clause).

### Evaluation (Part B)
- **AC-6:** The gold corpus under `eval/gold/` contains **≥ 25 gold files (one file per contract, per the
  026 schema — `load_gold` operates per-file and the manifest is one entry per file) totaling ≥ 250 labeled
  clauses**, each valid against the existing 026 `load_gold` schema (both `should_flag:true` and `:false`
  present), and loads without a `GoldError`.
- **AC-7 (pytest, deterministic, no Ollama):** The scorer's new **per-clause-type breakdown** (B2) is
  computed correctly on a hand-worked fixture (aggregate rates equal the weighted combination of the
  per-type rates).
- **AC-8 (pytest, deterministic):** **Bootstrap CIs** (B3) are correct and reproducible under a fixed seed:
  same input + seed ⇒ identical interval; the point estimate lies within its reported CI; a degenerate
  all-correct sample yields a valid (possibly [1.0,1.0]) interval without error.
- **AC-9:** `score` emits an extended `metrics.json` carrying the aggregate metrics **plus** per-type
  breakdown **plus** CI bounds and each rate's `n`; the human-readable summary prints numbers as
  "estimate (95% CI lo–hi, n=…)". Runs with no Ollama/network against cached fixtures (026 AC-6 preserved).
- **AC-10 (live smoke, manual):** `run` executes the real pipeline over the enlarged gold set against the
  **new KB** (live Ollama, delivery stubbed per 026 D8) and `score` prints a coherent, CI-bounded metrics
  summary; the committed `metrics.json` + results note reflect that run.

### Boundary / honesty
- **AC-11:** Nothing under `app/` imports `eval/`; the graph, `ContractState`, migrations, and frontend are
  unchanged (`git diff` boundary check — same guard as 026 AC-10). The §3 CRAG threshold constant is
  unchanged **unless** a separate, in-diff justification (D6) accompanies a deliberate edit.
- **AC-12:** README's KB-size and accuracy claims are updated to the measured, CI-bounded, n-stated numbers
  (D9); no headline number appears without its sample size.

## 5. Edge cases
- **EC-1 — CUAD download unavailable / offline.** `build_corpus.py` degrades to the committed curated slice
  + Bonterms and prints a clear notice; it never fails the build just because the raw fetch dir is absent
  (the committed corpus is self-contained). The full fetch is reproducible when back online.
- **EC-2 — A CUAD span is too short / boilerplate / duplicate.** Dropped by the `_MIN_SNIPPET_CHARS` +
  dedup curation (A4); it does not enter the corpus.
- **EC-3 — A CUAD category has no `ClauseType` enum equivalent.** Its `clause_type` metadata is recorded
  as the CUAD label string (additive, free-text) — the runtime ignores it (D3); the eval per-type
  breakdown groups by the recorded label.
- **EC-4 — Enlarged KB shifts the confidence distribution so 0.73 mis-separates.** Surfaced by the re-run
  `eval_crag_confidence.py` (D6) as a recommendation; the corpus rebuild itself does not change the
  constant.
- **EC-5 — A gold clause's `text_snippet` doesn't match any pipeline finding/clause** → handled by the
  existing 026 matcher as a miss/ignored (026 EC-6); no new behavior.
- **EC-6 — Bootstrap on an empty or single-sample rate** → CI reported as "N/A" (or [x,x] for n=1) with no
  div-by-zero (mirrors 026 AC-7 undefined-rate handling).
- **EC-7 — Committed corpus would exceed a sane repo size.** The per-category cap (A4/D8) bounds it; raw
  full data stays gitignored under `data/kb/sources/`.

## 6. Out of scope
- **Surfacing KB metadata (`clause_type`/`jurisdiction`) into runtime findings or the report** — additive
  in the sidecar now (D3); *using* it in CRAG/report is a **future** feature (would be an `app/` change with
  its own spec).
- **Changing the §3 CRAG threshold, or any CRAG/Self-RAG/scoring runtime logic** — this feature measures
  and *recommends* (D6); it does not re-tune runtime behavior.
- **Auto-grading redline/rewrite quality** — still 026 D6 / future (human or LLM-judge rubric).
- **Lawyer-reviewed gold labels** — target is best-effort human labels with an honesty caveat; formal
  legal review is a data-collection effort, not this code deliverable.
- **A stronger/larger generative model, jurisdiction-conditioned scoring, playbook comparison, CI
  accuracy-gating** — these are the Tier-2/Tier-3 follow-ups (senior review) and each is its own feature.
- **Any runtime pipeline / `ContractState` / API / frontend / migration change** — none.

## 7. Evaluation (metrics this feature exists to produce)
The whole point is to replace indicative numbers with defensible ones. After B4, the committed
`metrics.json` reports, **each with its sample size `n` and a 95% bootstrap CI**: detection
**precision / recall / F1**, **miss rate**, **false-flag rate**, **severity exact + within-one accuracy**,
all **broken down by `clause_type`** (B2) as well as aggregate; plus the retained 026 diagnostics
(Self-RAG discard-vs-validate contribution to misses, CRAG LOCAL_KB vs WEB_FALLBACK path split, per-node
p50/p95 latency). A short results note compares **before (109-chunk KB) vs after (enlarged KB)** on the
same enlarged gold set, so the corpus expansion's effect on retrieval-path split and recall is visible.
**Honesty caveat (carried in the summary + README):** numbers are best-effort-labeled, not lawyer-reviewed;
every rate is reported with its `n` and CI.

## 8. Notes for plan.md / tasks.md (pointers)
- **Layout:**
  - `backend/data/kb/sources/` — new source inputs: raw CUAD/EDGAR fetch **gitignored**; curated slice
    committed. `backend/data/kb/SOURCES.md` (or `sources_manifest.json`) — provenance/license (A5/AC-3).
  - `backend/scripts/fetch_cuad.py` (or documented manual step, D8) → downloads CUAD to the gitignored raw
    dir. `backend/scripts/build_corpus.py` — extended (D7) to read Bonterms `app/db/*.md` **and**
    `data/kb/sources/*`, curate/dedup/cap (A4), and write additive metadata (A6). `build_kb.py` gets a
    **small** change: its `_load_corpus()` currently rebuilds each record (the `records.append({...})` line)
    as only `{snippet_text, source_reference}` and writes just those to `clauses_meta.jsonl`; extend it to preserve
    the additive keys into the sidecar (A6) while still requiring the two mandatory keys. Embedding/index
    build (IndexFlatIP + L2-normalize) is otherwise unchanged.
  - `backend/eval/gold/*.json` — the enlarged gold set (B1), same 026 schema.
  - `backend/eval/harness/scorer.py` (+`score.py` summary) — add per-type breakdown (B2) and bootstrap CIs
    (B3). `backend/eval/harness/config.py` — new named constants: `EVAL_BOOTSTRAP_ITERATIONS`,
    `EVAL_BOOTSTRAP_SEED`, `EVAL_CI_LEVEL` (0.95) — §3 centralization (mirrors 026 D7).
- **Tests (pytest, pure, deterministic — these DO run in the runtime suite):**
  `test_eval_per_type_breakdown.py` (AC-7), `test_eval_bootstrap_ci.py` (AC-8, fixed-seed reproducibility),
  and a corpus-shape test `test_corpus_shape.py` (AC-2). The corpus **build** and the live **run/score**
  are exercised by the manual smoke (AC-10), not the runtime suite.
- **Gitignore:** add `backend/data/kb/sources/` raw-fetch dir (keep the committed curated files tracked via
  a `!`-negation or by committing them to a tracked subpath); `eval/runs/` already ignored.
- **Rebuild order (documented for the smoke):** `python scripts/fetch_cuad.py` (once, online) →
  `python scripts/build_corpus.py` → `python scripts/build_kb.py` (needs Ollama + bge-m3) → 026
  `run` → `score`. Requires the embedding model per constitution §8 (never the generative model).
- **Honest framing** must appear in the eval summary, `SOURCES.md`, and the README edit (D9): the corpus is
  license-clean and diverse but finite; the numbers are best-effort-labeled with stated `n` + CI.
