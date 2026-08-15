# Legal-Grounding Upgrade (Corpus + Evaluation) — Implementation Tasks

Reference documents:
- Spec: `specs/041-legal-corpus-evaluation/spec.md`
- Plan: `specs/041-legal-corpus-evaluation/plan.md`
- Constitution: `specs/000-constitution.md` (**§2** offline data/tooling — NOT a graph node/edge, no
  amendment; **§3** config constants; **§7** TDD; **§8** embedding model (bge-m3) for the KB build, never
  the generative model; **§10** no `ContractState` change)

Backend paths relative to `backend/`.

**Workflow reminders:**
- TDD (§7): the per-type, bootstrap, and corpus-shape unit tests are written FAILING before their
  implementation.
- **No `app/**` change.** All edits are under `scripts/`, `data/kb/`, `eval/`, `tests/unit/`. `kb_retriever.py`
  stays untouched (it reads only `snippet_text`+`source_reference`; extra sidecar keys are ignored). No
  `app/graph/**`, no `ContractState`, no boundary model, no endpoint, no migration, no frontend.
- **Do NOT change the §3 `CRAG_CONFIDENCE_THRESHOLD` (0.73) constant** in this feature — Task 9 only
  *measures* and *recommends* (spec D6/AC-11). Any change is a separate, separately-justified edit.
- **build_kb.py fix is minimal:** preserve additive keys into the sidecar; do NOT alter the `IndexFlatIP`
  + L2-normalize + 1:1 vector↔row-order invariants (AC-4).
- **Metadata is additive, not mandatory:** Bonterms records stay EXACTLY `{snippet_text, source_reference}`
  — never inject a `null` `clause_type` (AC-2 converse invariant).
- **clause_type is FREE-TEXT, not enum-validated** (reviewer suggestion 1): the per-type breakdown groups
  on the raw recorded `clause_type` string (enum values like `liability` AND CUAD/gold labels like
  `limitation_of_liability`/`governing_law`). Do NOT coerce to the 12-member `ClauseType` enum — that would
  collapse or drop CUAD labels (spec EC-3).
- **Two distinct notions of `n`** (reviewer suggestion 3): the **bootstrap resamples DOCUMENTS**, so its
  reported `n` is the document count; the per-rate `n` printed next to recall/miss/etc. is the
  **clause-level denominator** (`recall_n = tp+fn`, `false_flag_n = fp_clean+tn`). Keep them separate and
  label them in the summary.
- The new unit tests DO run in pytest; the corpus **build** (`fetch_cuad`/`build_corpus`/`build_kb`) and the
  live `run`→`score` are exercised by the manual smoke (AC-10), not the runtime suite — like the existing
  evals.

---

## Task 0: Branch
- [ ] From up-to-date `main`, create `feature/041-legal-corpus-evaluation` (`git-start`). Commit the 041
  `spec.md`/`plan.md`/`tasks.md` on the branch.

**Verify:** `git branch --show-current` → `feature/041-legal-corpus-evaluation`.

---

## Task 1: Eval config constants (§3)
- [ ] **[MODIFY] `eval/harness/config.py`** — add three named constants (mirroring the existing pattern):
  - `EVAL_BOOTSTRAP_ITERATIONS: int = 2000`
  - `EVAL_BOOTSTRAP_SEED: int = 12345`
  - `EVAL_CI_LEVEL: float = 0.95`
  Named/centralized only; nothing hardcoded in `scorer.py`.

**Verify:** `python -c "import eval.harness.config as c; print(c.EVAL_BOOTSTRAP_ITERATIONS, c.EVAL_BOOTSTRAP_SEED, c.EVAL_CI_LEVEL)"` from `backend/`.

---

## Task 2: Per-type breakdown — test (red) → scorer (green)  [AC-7]
- [ ] **[NEW] `tests/unit/test_eval_per_type_breakdown.py`** (confirm FAILING): a hand-worked
  multi-`clause_type` fixture of (report-dict, sidecar-list, `GoldDoc`) inputs where gold clauses carry
  mixed `clause_type` values, including a raw CUAD-style label (e.g. `"limitation_of_liability"`) and an
  untyped clause (`clause_type=None` → `"unspecified"` bucket). Assert:
  - `detection_by_type[<type>]` reports correct `recall`, `miss_rate`, `false_flag_rate`,
    `severity_exact`, `severity_within`, and `n` per type (all gold-clause-anchored).
  - **Aggregate-consistency invariant:** summing per-type `tp/fn/fp_clean/tn` equals the global
    `detection` tallies, so the pooled per-type rates reproduce the aggregate recall/miss/false-flag (this
    is AC-7's "aggregate equals the weighted combination").
  - Grouping is on the **raw** `clause_type` string (no enum coercion); `None` → `"unspecified"`.
- [ ] **[MODIFY] `eval/harness/scorer.py`** — inside the existing detection loop (the `for g in gold:`
  block ~line 69), additionally accumulate `tp/fn/fp_clean/tn` and severity `exact/within/n` into a
  `by_type` dict keyed by `g.clause_type or "unspecified"`. Emit a new top-level key:
  `"detection_by_type": { <clause_type>: {"recall", "miss_rate", "false_flag_rate", "severity_exact",
  "severity_within", "n"} }` using the existing `_safe_div` (undefined → `None`).
  - **Per-type PRECISION is deliberately NOT reported** — global precision's denominator is
    `tp+fp_clean+unlabeled` (`scorer.py:126`) and `unlabeled` (unmatched findings) carry no gold
    `clause_type`; typing them would fabricate a number. Leave a code comment stating this; global
    precision/F1 stay aggregate-only.

**Verify:** `pytest tests/unit/test_eval_per_type_breakdown.py` → PASS.

---

## Task 3: Bootstrap CIs — test (red) → scorer (green)  [AC-8]
- [ ] **[NEW] `tests/unit/test_eval_bootstrap_ci.py`** (confirm FAILING): fixtures of `List[DocInput]`.
  Assert:
  - **Reproducibility:** same input + `EVAL_BOOTSTRAP_SEED` ⇒ byte-identical intervals across two calls.
  - **Point-estimate-in-CI:** each metric's aggregate point estimate lies within its `[lo, hi]`.
  - **Degenerate cases:** an all-correct sample yields a valid `[1.0, 1.0]`; a single-doc corpus and an
    undefined-rate case return `[x, x]` / `None` without raising (EC-6).
  - The returned interval object also reports the resample **document count** `n_docs`.
- [ ] **[MODIFY] `eval/harness/scorer.py`** — add a pure helper
  `bootstrap_detection_ci(docs, iterations, seed, ci_level) -> dict`:
  - Use `random.Random(seed)` (**stdlib only — no new dependency**, tech-stack 002 unchanged). **Never**
    touch the global `random` state.
  - **Resample DOCUMENTS with replacement** (`docs` is the independent unit — clauses within a contract are
    correlated). For each of `iterations` resamples, recompute the aggregate detection tallies (reuse the
    per-doc tally logic — factor it into a helper if needed) → precision/recall/f1/miss_rate/
    false_flag_rate; collect each metric's distribution; report `[lo, hi]` at the
    `(1-ci_level)/2` and `1-(1-ci_level)/2` percentiles (2.5/97.5 for 0.95). Undefined metric in a
    resample → skip that draw; if a metric is undefined on the full corpus → interval `None`.
  - Return `{"n_docs": <count>, "precision":[lo,hi]|None, "recall":…, "f1":…, "miss_rate":…,
    "false_flag_rate":…}`.
- [ ] In `score()` (single-arg signature UNCHANGED so `score.py`'s `metrics = score(docs)` call site is
  untouched), read the config constants internally and add to the returned dict:
  - `"detection_ci"`: the `bootstrap_detection_ci(...)` result;
  - the clause-level denominators next to detection: `detection["recall_n"] = tp+fn`,
    `detection["precision_n"] = tp+fp_clean+unlabeled`, `detection["false_flag_n"] = fp_clean+tn`,
    `detection["miss_n"] = tp+fn`.

**Verify:** `pytest tests/unit/test_eval_bootstrap_ci.py` → PASS.

---

## Task 4: Summary rendering  [AC-9]
- [ ] **[MODIFY] `eval/harness/score.py`** — extend `print_summary`:
  - Add a `_ci_str(est, ci, n)` helper rendering `est (95% CI lo–hi, n=…)` (reuse `_pct` for the percent
    formatting; `"N/A"` when `est`/`ci` is `None`). Print each detection rate with its CI and its
    **clause-level** `n` (`recall_n` etc.). Print the bootstrap's `n_docs` once, labeled as the document
    resample count (so the two `n` notions are unambiguous — reviewer suggestion 3).
  - Print a compact **per-type table** from `detection_by_type`: columns
    `clause_type · recall · miss · false-flag · severity-exact · n`.
  - Keep the leading honesty caveat (`_CAVEAT`) and add: labels are best-effort, not lawyer-reviewed.
  `metrics.json` persists the new keys automatically via the unchanged `score_run` writer.

**Verify:** exercised by the Task 10 smoke (needs a scored run); `python -c "import eval.harness.score"`
imports clean offline.

---

## Task 5: build_kb.py additive-metadata fix + corpus-shape test  [AC-2, AC-4]
- [ ] **[NEW] `tests/unit/test_corpus_shape.py`** (confirm FAILING): given a small fixture
  `clauses_corpus.jsonl`-shaped list mixing (a) Bonterms-style records `{snippet_text, source_reference}`
  and (b) CUAD-style records with additive `clause_type`+`source_license`, assert a `validate_corpus`
  helper enforces: both required keys present + non-empty snippet on every record; additive keys
  well-formed where present; Bonterms records round-trip with **exactly** two keys (**no `null`
  clause_type injected**); and — simulating the build — additive keys **survive into the meta sidecar**
  (guards the `_load_corpus` fix). Put the pure `validate_corpus(records) -> None (raises)` helper where
  the test can import it offline (e.g. a small `eval/harness/corpus_check.py`, no `app.*` import) so this
  test needs no Ollama/FAISS.
- [ ] **[MODIFY] `scripts/build_kb.py`** — in `_load_corpus()`, still **require** `snippet_text` +
  `source_reference`, but **preserve the whole record** (carry any additional keys through) instead of
  reconstructing `{snippet_text, source_reference}` only. `main()` then writes those full records to
  `clauses_meta.jsonl`. Embedding still uses `rec["snippet_text"]`; `IndexFlatIP`, L2-normalization, and
  1:1 vector↔row order are UNCHANGED (AC-4).

**Verify:** `pytest tests/unit/test_corpus_shape.py` → PASS.

---

## Task 6: Corpus fetch + curation tooling  [AC-1, AC-3]
- [ ] **[NEW] `scripts/fetch_cuad.py`** — download the CUAD release (clause spans + 41 category labels)
  into **gitignored** `data/kb/sources/cuad_raw/`. Print a notice + exit 0 if already present or if offline
  (EC-1 — never hard-fail the pipeline on a missing fetch). Network-only; not run in pytest.
- [ ] **[MODIFY] `scripts/build_corpus.py`** — keep the existing Bonterms path (the `SOURCES` dict +
  `_parse_document` + `_MIN_SNIPPET_CHARS=40`) UNCHANGED, and add a second ingestion path over
  `data/kb/sources/`:
  - map each CUAD span → a record `{snippet_text, source_reference, clause_type, source_license}` (+
    `jurisdiction` only when the source states it); `clause_type` = the CUAD category **string** (map to a
    `ClauseType` value — `from app.graph.state import ClauseType`, a read-only import, harmless in a
    script — where one exists, else keep the raw label as free-text, EC-3);
  - **curate:** drop spans `< _MIN_SNIPPET_CHARS`; **dedup** near-identical spans (normalized exact +
    normalized-prefix key); **cap per `clause_type`** at a new named constant `MAX_PER_TYPE` (e.g. 120) so
    the corpus is balanced (`MAX_PER_TYPE` lives in `build_corpus.py`, NOT `eval/harness/config.py`: it is
    a build-script knob co-located with `_MIN_SNIPPET_CHARS`, not an eval-harness constant); target
    **800–1,500 total** chunks (AC-1) spanning **≥12 distinct recorded
    `clause_type` labels** (count is over recorded labels = enum values + CUAD labels, NOT strictly the 12
    enum members — reviewer suggestion 2).
  - Deterministic + fully-rewrites the corpus (as today). Bonterms records stay exactly two-keyed.
- [ ] **[NEW] `data/kb/SOURCES.md`** (authored, committed): one entry per source — name, URL, license,
  retrieval date, attribution; explicit **CUAD CC BY 4.0** attribution line; EDGAR noted public-domain;
  state that only license-permitted text is committed and the full corpus is reproducible via
  `fetch_cuad.py`.
- [ ] **[MODIFY] `.gitignore`** — ignore `backend/data/kb/sources/cuad_raw/` (raw fetch); keep the
  committed curated slice + `SOURCES.md` tracked.

**Verify:** `python scripts/build_corpus.py` prints per-source counts and writes
`data/kb/clauses_corpus.jsonl` with 800–1,500 records / ≥12 clause_type labels; Bonterms chunks still
present. (No Ollama needed for this step.)

---

## Task 7: Rebuild the FAISS index  [AC-4, AC-5]
- [ ] Ensure Ollama is up with the **embedding** model `bge-m3` (constitution §8 — NEVER the generative
  model). Run `python scripts/build_kb.py`.
- [ ] Confirm output: `index ntotal == corpus line count`; `clauses_meta.jsonl` now carries the additive
  keys (spot-check a CUAD row has `clause_type`/`source_license`; a Bonterms row has exactly two keys).

**Verify:** a retrieval smoke — load the new index via the unchanged `kb_retriever` and confirm it returns
snippets for a sample clause using only `snippet_text`+`source_reference` (AC-5); `git diff --name-only`
shows **no `app/**`** change.

---

## Task 8: Gold data (enlarged eval set)  [AC-6]
- [ ] **[NEW] `eval/corpus/*`** — commit the ≥25 source contracts the gold files reference (a curated CUAD
  subset), so gold `document` paths are self-contained (026 pattern; the per-`clause_type` cap + subset
  keep repo size bounded, EC-7).
- [ ] **[NEW] `eval/gold/*.json`** — ≥25 files (one contract each, existing 026 `load_gold` schema),
  totaling ≥250 labeled clauses, each with BOTH `should_flag:true` (+ `expected_severity`) AND
  `should_flag:false` clauses. **CUAD categories only SELECT candidate clauses; a human confirms
  `should_flag`/`expected_severity`** — never auto-derive from a CUAD category (a category is not a risk
  verdict) and never from the system's own output (no circular labels, spec D4). Each file's `notes`
  records who/when + "best-effort, not lawyer-reviewed".

**Verify:** `load_gold` accepts every file without a `GoldError`; confirm the ≥250-clause / ≥25-file floor
**mechanically** (e.g. `python -c "from eval.harness.schema import load_gold_dir; ds=load_gold_dir('eval/gold'); print(len(ds), sum(len(d.clauses) for d in ds))"` from `backend/`), not by eye.

---

## Task 9: CRAG threshold re-check (measure only, D6)  [AC-11]
- [ ] Re-run the existing `python eval/eval_crag_confidence.py` (or its documented entrypoint) over the new
  index; record the confidence distribution and a **recommendation** on the 0.73
  `CRAG_CONFIDENCE_THRESHOLD`. **Do NOT change the constant** in this feature.

**Verify:** a short recommendation note is captured (committed alongside the results note in Task 10);
`git diff` shows the §3 threshold constant unchanged (AC-11).

---

## Task 10: Full verification + live smoke + README  [AC-10, AC-12]
- [ ] **[NEW] boundary check** — assert no file under `app/` imports `eval` (reuse/extend the existing
  boundary-test style). `pytest` (whole backend) GREEN.
- [ ] `git diff --name-only main` shows ONLY `scripts/**`, `data/kb/**`, `eval/**`,
  `tests/unit/test_{corpus_shape,eval_per_type_breakdown,eval_bootstrap_ci}.py`, `.gitignore`,
  `specs/041-**` — **no `app/**` change**, no `ContractState`, no migration, no frontend.
- [ ] **Live smoke (AC-10):** with Ollama (`qwen3:8b` generative + `bge-m3` embedding) up and delivery OFF
  (`app.delivery.delivery_step.MCP_DELIVERY_ENABLED = False`, the import-bound name — patching
  `app.config.…` is a NO-OP), run `python -m eval.harness.run --gold eval/gold` over the enlarged gold set
  against the new KB; confirm **no Drive/Gmail delivery** occurred. Then `python -m eval.harness.score
  eval/runs/<ts>` → a coherent, CI-bounded, per-type summary. Commit `metrics.json` + a short **before
  (109-chunk KB) vs after (enlarged KB)** results note.
- [ ] **[MODIFY] `README.md`** (AC-12): replace the KB-size and "recall 64% → 100%" claims with the
  measured, **CI-bounded, n-stated** numbers; no headline number without its sample size + caveat.

**Verify:** smoke summary is coherent; `metrics.json` carries `detection_ci` + `detection_by_type`; README
numbers match the committed `metrics.json`.

---

## Task 11: Merge
- [ ] Whole `pytest` green; `git diff` scope confirmed (no `app/**`); smoke numbers + threshold
  recommendation noted; README updated.
- [ ] Rebase `main`, merge `feature/041-legal-corpus-evaluation`, delete branch (`git-finish`).

---

*Per §1/§11, implementation happens only on `feature/041-legal-corpus-evaluation`, opened after spec +
plan + tasks are approved. Offline data + tooling only; no runtime/app/graph change, no `ContractState`
change, no migration, no frontend. The §3 CRAG threshold is measured/recommended, never changed here.*
