# Legal-Grounding Upgrade (Corpus + Evaluation) — Technical Plan

## Git Branch

`feature/041-legal-corpus-evaluation` — branching workflow per `specs/000-constitution.md` §11.

---

## 1. Overview

Implements `specs/041-legal-corpus-evaluation/spec.md` — an **offline data + tooling** upgrade in two
coupled parts on one branch:

- **Part A (corpus):** grow the CRAG reference KB from ~109 Bonterms-only chunks to a diverse,
  provenance-clean **800–1,500 chunk** corpus (anchor **CUAD**, CC BY 4.0; optional EDGAR public-domain;
  retain Bonterms), with **additive** metadata (`clause_type`/`source_license`/`jurisdiction`), then
  rebuild the FAISS index.
- **Part B (evaluation):** enlarge the 026 gold set to **≥25 contracts / ≥250 labeled clauses** and extend
  the **existing** 026 scorer with a **per-clause-type breakdown** and **bootstrap confidence intervals**,
  then re-run 026's `run`→`score` and commit a real `metrics.json`.

**No constitution amendment. NOT a graph node/edge. No `ContractState` change. No migration. No frontend.
No runtime CRAG behavior change** (§2/§10). The only runtime-adjacent edit is a **small `scripts/`
change** to `build_kb.py::_load_corpus()` so additive metadata reaches `clauses_meta.jsonl` (spec A6) — the
runtime retriever still reads only `snippet_text`+`source_reference`. The pure scorer additions
(per-type, bootstrap CI) are TDD-unit-tested in the pytest suite; the corpus build and the live
`run`→`score` are exercised by the manual smoke (AC-10), mirroring the existing evals.

---

## 2. Files to Create / Modify

### Backend (`backend/`)
```
scripts/fetch_cuad.py               [NEW]    download CUAD (CC BY 4.0) → gitignored data/kb/sources/cuad_raw/ (D8); no-op-safe if offline (EC-1)
scripts/build_corpus.py             [MODIFY] read Bonterms app/db/*.md AND data/kb/sources/* ; curate/dedup/cap per clause_type ; emit additive metadata (A4/A6)
scripts/build_kb.py                 [MODIFY] _load_corpus(): preserve additive keys into clauses_meta.jsonl (still require the 2 mandatory) — spec A6
data/kb/sources/                    [NEW]    curated source inputs (committed slice); raw fetch dir gitignored
data/kb/SOURCES.md                  [NEW]    per-source provenance + license + CUAD CC BY attribution (A5/AC-3)
data/kb/clauses_corpus.jsonl        [REGEN]  rebuilt (≥800 chunks, ≥12 clause_types) — committed
data/kb/clauses_meta.jsonl          [REGEN]  rebuilt sidecar (now carries additive keys)
data/kb/clauses.faiss               [REGEN]  rebuilt index (ntotal == corpus lines, L2-normalized IP)

eval/harness/config.py              [MODIFY] add EVAL_BOOTSTRAP_ITERATIONS, EVAL_BOOTSTRAP_SEED, EVAL_CI_LEVEL (§3 named consts)
eval/harness/scorer.py              [MODIFY] add detection_by_type (per clause_type) + detection_ci (bootstrap) to score()'s output dict
eval/harness/score.py               [MODIFY] print per-type table + render rates as "est (95% CI lo–hi, n=…)"
eval/gold/*.json                    [NEW]    ≥25 gold files / ≥250 labeled clauses (026 schema; human-confirmed labels, D4)
eval/corpus/*                       [NEW]    the ≥25 source contracts the gold files reference (curated CUAD subset)
.gitignore                          [MODIFY] ignore backend/data/kb/sources/cuad_raw/ (raw fetch); keep committed curated slice tracked

tests/unit/test_corpus_shape.py     [NEW]    corpus/sidecar shape: 2 required keys present, no empty snippets, additive keys well-formed & absent-not-null, meta carries additive keys (AC-2)
tests/unit/test_eval_per_type_breakdown.py [NEW]  per-type recall/miss/false-flag/severity + aggregate-consistency (AC-7)
tests/unit/test_eval_bootstrap_ci.py       [NEW]  seeded reproducibility, point-estimate-in-CI, degenerate sample (AC-8)
```
**No `app/**` change.** `kb_retriever.py` is untouched — it keeps reading `row["snippet_text"]` /
`row["source_reference"]` (extra sidecar keys are loaded but never accessed). No `app/graph/**`, no
`ContractState`, no boundary model, no endpoint, no migration. The `eval/harness/` matcher/schema/run
mechanics are reused verbatim (026 owns them).

---

## 3. Design

### 3.1 Part A — corpus expansion

#### 3.1.1 `scripts/fetch_cuad.py` (D8, EC-1)
- Downloads the CUAD release (clause spans + category labels) into **gitignored**
  `data/kb/sources/cuad_raw/`. Prints a clear notice and exits 0 if already present. Network-only; never
  run in pytest.
- CUAD ships clause **spans** annotated by one of 41 legal **categories**. We take each annotated span's
  text as a candidate corpus chunk and its category as the `clause_type` metadata (mapped to a
  `ClauseType` enum value where one exists, else kept as the raw CUAD label string — EC-3).

#### 3.1.2 `scripts/build_corpus.py` (extend, D7/A4/A6)
- Keep the existing Bonterms path unchanged (still reads `app/db/Cloud-Terms.md` +
  `Data-Protection-Addendum.md` via the `SOURCES` dict; existing `_parse_document` and
  `_MIN_SNIPPET_CHARS = 40` reused).
- Add a second ingestion path over `data/kb/sources/` (CUAD curated + optional EDGAR):
  - **Curate, not dump (A4):** drop spans `< _MIN_SNIPPET_CHARS`; **dedup** near-identical spans (exact
    after `_strip_markdown`-style normalization, plus a cheap normalized-prefix key); **cap per
    `clause_type`** at `MAX_PER_TYPE` (a new named constant in this script, e.g. 120) so the corpus is
    balanced and small; target 800–1,500 total (AC-1 floor/ceiling).
  - **Additive metadata (A6):** each new record is
    `{"snippet_text", "source_reference", "clause_type", "source_license"}` (+ `"jurisdiction"` only when
    the source states it). Bonterms records stay **exactly** `{"snippet_text","source_reference"}` — no
    `null` keys injected (AC-2 converse invariant).
- Deterministic + re-runnable (fully rewrites `clauses_corpus.jsonl`), same as today.
- Writes/updates `data/kb/SOURCES.md` is a **separate committed doc** (authored, not generated) —
  build_corpus does not need to emit it; it references it in its module docstring.

#### 3.1.3 `scripts/build_kb.py::_load_corpus()` (small change, spec A6 — the reviewer-caught fix)
- **Today** `_load_corpus()` rebuilds each record as only
  `records.append({"snippet_text": rec["snippet_text"], "source_reference": rec["source_reference"]})`
  and `main()` writes exactly those to `META_PATH` — stripping any additive key.
- **Change:** still require the two mandatory keys, but **carry the whole record through** (preserve any
  additional keys) so `clauses_meta.jsonl` contains `clause_type`/`source_license`/`jurisdiction` where
  present. Embedding uses `rec["snippet_text"]` (unchanged); `IndexFlatIP` + L2-normalization + 1:1
  vector↔row order are **unchanged** (AC-4). This is a `scripts/` edit → §1 unaffected.

#### 3.1.4 `data/kb/SOURCES.md` (A5/AC-3)
- One entry per source: **name, URL, license, retrieval date, attribution.** Explicit **CUAD CC BY 4.0**
  attribution line; EDGAR noted public-domain. States that only license-permitted text is committed and
  the full corpus is reproducible via `fetch_cuad.py` (no over-redistribution).

#### 3.1.5 Threshold re-check (D6, no runtime change)
- After rebuild, re-run the existing `backend/eval/eval_crag_confidence.py` over the new index and record
  the confidence distribution + a **recommendation** on the §3 `CRAG_CONFIDENCE_THRESHOLD` (0.73). The
  constant is **not** changed in this feature; any change is a separate justified edit (spec §6, AC-11).

### 3.2 Part B — defensible evaluation

#### 3.2.1 `eval/harness/config.py` (new §3 constants)
- `EVAL_BOOTSTRAP_ITERATIONS: int = 2000` — resamples for the CI.
- `EVAL_BOOTSTRAP_SEED: int = 12345` — fixes `random.Random(seed)` so CIs are reproducible (AC-8).
- `EVAL_CI_LEVEL: float = 0.95` — two-sided percentile interval (2.5/97.5).
All named/centralized (mirrors 026 D7); nothing hardcoded in the scorer.

#### 3.2.2 `eval/harness/scorer.py` — per-type breakdown (B2, AC-7)
- `GoldClause.clause_type` already exists (schema.py). In the detection loop (`scorer.py:69`), additionally
  tally `tp/fn/fp_clean/tn` **keyed by `g.clause_type or "unspecified"`**, and severity `exact/within/n`
  per type.
- Emit `detection_by_type: { <clause_type>: {recall, miss_rate, false_flag_rate, severity_exact,
  severity_within, n} }`. **Only gold-clause-anchored rates are reported per type** (recall, miss,
  false-flag, severity) — these are well-defined because every gold clause has a type. **Global**
  precision/F1 stay aggregate-only because *unmatched* findings (`unlabeled_flags`) carry no gold
  `clause_type` and would make per-type precision ill-defined; a code comment + the summary state this.
- **Aggregate-consistency invariant (AC-7):** summing each type's per-type tallies reproduces the global
  `tp/fn/fp_clean/tn`, so aggregate recall/miss/false-flag equal the pooled per-type tallies — the unit
  test hand-verifies this.

#### 3.2.3 `eval/harness/scorer.py` — bootstrap CIs (B3, AC-8)
- New pure helper `bootstrap_detection_ci(docs, iterations, seed, ci_level) -> dict`:
  - **Resample at the document level** (docs with replacement) — clauses within one contract are
    correlated, so the document is the independent unit; this gives an honest interval (documented choice).
  - For each resample, recompute the aggregate detection tallies and derive precision/recall/f1/miss/
    false-flag; collect each metric's distribution; report the `[2.5th, 97.5th]` percentile as `[lo, hi]`.
  - Deterministic under `EVAL_BOOTSTRAP_SEED` (`random.Random`, **stdlib only** — no new dep, stays
    offline/pure). Degenerate cases (single doc, all-correct, undefined metric) → interval `[x, x]` or
    `None` with no error (EC-6).
- `score()`'s returned dict gains `detection_ci: {precision:[lo,hi]|None, recall:…, f1:…, miss_rate:…,
  false_flag_rate:…}` and each detection rate is reported alongside its **`n`** (denominator):
  `recall_n = tp+fn`, `false_flag_n = fp_clean+tn`, etc. `score(docs)` keeps its **single-arg signature**
  (reads the config constants internally) so `score.py`'s call site (`metrics = score(docs)`) is unchanged.

#### 3.2.4 `eval/harness/score.py` — summary (AC-9)
- Extend `print_summary` to render each detection rate as **`est (95% CI lo–hi, n=…)`** using a new
  `_ci_str(est, ci, n)` helper (alongside the existing `_pct`), and to print a compact **per-type table**
  (clause_type · recall · miss · false-flag · severity-exact · n). `metrics.json` already round-trips the
  full dict via the unchanged `score_run` writer, so the new keys persist automatically.

#### 3.2.5 Gold data (B1, D4)
- ≥25 `eval/gold/*.json` files (one contract each, 026 schema; `load_gold`/`GoldError` reused), each with
  both `should_flag:true` and `:false` clauses, totaling ≥250 labeled clauses. CUAD categories only
  **select candidates**; a human confirms `should_flag`/`expected_severity` (no auto-derived/circular
  labels). Source contracts committed under `eval/corpus/` (curated CUAD subset) so gold `document` paths
  are self-contained (026 pattern). The eval summary keeps the "best-effort, not lawyer-reviewed" caveat.

---

## 4. Tests mapped to acceptance criteria

**Backend (pytest — pure, deterministic, fixture-driven; these DO run in the suite).**
- `test_corpus_shape.py` (AC-2): a fixture corpus/meta pair — every record has the two required keys, no
  empty snippet; additive-keyed records are well-formed; Bonterms-style records round-trip with **exactly**
  two keys (no `null` clause_type); the meta sidecar **carries** additive keys (guards the build_kb fix).
- `test_eval_per_type_breakdown.py` (AC-7): hand-worked multi-type gold+report fixture → correct per-type
  recall/miss/false-flag/severity; **aggregate == pooled per-type** tallies; `"unspecified"` bucket for
  untyped gold.
- `test_eval_bootstrap_ci.py` (AC-8): same input + `EVAL_BOOTSTRAP_SEED` ⇒ **identical** interval; the
  point estimate lies within its CI; an all-correct sample yields a valid `[1.0, 1.0]`; a single-doc /
  undefined-rate sample returns `[x,x]`/`None` without raising.
- **Boundary (AC-11):** nothing under `app/` imports `eval/`; `git diff --name-only main` shows no
  `app/**` change and the §3 `CRAG_CONFIDENCE_THRESHOLD` constant unchanged.

**Not unit-tested (data/build/live, per §7 — matches 026):** `fetch_cuad.py`, `build_corpus.py`,
`build_kb.py` rebuild, and the live `run`→`score` are covered by the manual smoke (AC-1, AC-3, AC-4,
AC-5, AC-6, AC-10, AC-12).

**Live smoke (AC-10):** `python scripts/build_corpus.py` → `python scripts/build_kb.py` (Ollama + bge-m3)
→ `python -m eval.harness.run --gold eval/gold` (delivery off per 026 D8) → `python -m eval.harness.score
eval/runs/<ts>` → coherent CI-bounded summary; commit `metrics.json` + a short before/after results note.

---

## 5. Implementation order (TDD — §7)

1. **Config:** add the three `EVAL_BOOTSTRAP_*`/`EVAL_CI_LEVEL` constants (trivial).
2. **Per-type test (red) → scorer per-type (green):** write `test_eval_per_type_breakdown.py`; add
   `detection_by_type` to `score()` until green (aggregate-consistency asserted).
3. **Bootstrap test (red) → bootstrap (green):** write `test_eval_bootstrap_ci.py`; implement
   `bootstrap_detection_ci` + wire `detection_ci`/`n` into `score()` until green.
4. **Summary:** extend `score.py` (`_ci_str`, per-type table) — verified via the live smoke.
5. **build_kb fix + corpus-shape test:** write `test_corpus_shape.py` (red against a fixture that includes
   additive keys), apply the `_load_corpus()` preserve-keys change, green.
6. **Corpus build tooling:** `fetch_cuad.py`, extend `build_corpus.py` (dedup/cap/metadata), author
   `SOURCES.md`, `.gitignore` the raw dir.
7. **Rebuild + gold:** run build_corpus→build_kb; curate `eval/corpus/` + hand-confirm `eval/gold/*.json`.
8. **Verify:** whole-backend `pytest` GREEN; `git diff --name-only main` shows only
   `scripts/**`, `data/kb/**`, `eval/**`, `tests/unit/test_{corpus_shape,eval_per_type_breakdown,eval_bootstrap_ci}.py`,
   `.gitignore` — **no `app/**`**.
9. **Threshold re-check (D6):** re-run `eval/eval_crag_confidence.py`; record recommendation (no constant
   change).
10. **Live smoke (AC-10) + README (AC-12):** run→score; commit `metrics.json` + results note; update
    README KB-size/accuracy claims to the measured, CI-bounded, n-stated numbers.

Each step's unit tests are written failing first (§7). The build/live steps are not in the pytest suite
(need CUAD data / Ollama), consistent with the existing evals.

---

## 6. Notes / risks

- **The build_kb fix is load-bearing (spec A6):** if `_load_corpus()` isn't changed, additive metadata is
  silently dropped and the per-type breakdown has no `clause_type` in the sidecar. `test_corpus_shape.py`
  guards this; keep the change to preserving keys (do **not** alter embedding/index invariants — AC-4).
- **Per-type precision is deliberately NOT reported** (untyped unmatched findings make it ill-defined);
  only gold-anchored per-type rates are, with a stated reason. Don't "fix" this by inventing types for
  unmatched findings — that would fabricate a number.
- **Bootstrap resamples DOCUMENTS, not clauses** — clauses within a contract are correlated; doc-level is
  the honest independent unit. With ~25 docs the CIs will be wide; that width is the truthful message, not
  a bug. Report `n` alongside every rate so the reader sees the sample size.
- **Determinism:** the CI must be reproducible — always seed `random.Random(EVAL_BOOTSTRAP_SEED)`; never
  use the global `random` state (AC-8).
- **Labels are human-confirmed, not lawyer-reviewed (D4/D9):** CUAD categories only *select* candidates; a
  category is not a risk verdict, and the system's own output is never a label (no circular "silver"). The
  summary + `SOURCES.md` + README carry the honesty caveat; no number ships without its `n` + CI.
- **Data provenance/license (A5):** commit only license-permitted text; CUAD CC BY 4.0 attribution is
  mandatory in `SOURCES.md`; raw fetch stays gitignored. A "serious legal AI" must have auditable data
  provenance.
- **Delivery off for the run** (026 carry-over): set
  `app.delivery.delivery_step.MCP_DELIVERY_ENABLED = False` (NOT `app.config.…`, which has no effect) —
  the 026 `run.py` already does this; the enlarged gold set doesn't change that.
- **Repo size:** the per-`clause_type` cap (`MAX_PER_TYPE`) + committing only a curated CUAD subset bound
  both the corpus and `eval/corpus/`; raw CUAD stays gitignored (EC-7).
- **Slow live run:** ~minutes/doc on the local 8B/6GB box; the ≥25-doc run is long — it is a one-off
  measurement (cached), and `run` is resumable (026), so a killed run continues.

---

*Per §1/§11, a `feature/041-legal-corpus-evaluation` branch opens only after this plan.md + spec.md are
approved and `tasks.md` exists. Offline data + tooling only; no runtime/app/graph change, no
`ContractState` change, no migration. No `tasks.md`/implementation in this pass — plan only.*
