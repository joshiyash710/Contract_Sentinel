# Evaluation Harness — Implementation Tasks

Reference documents:
- Spec: `specs/026-evaluation-harness/spec.md`
- Plan: `specs/026-evaluation-harness/plan.md`
- Constitution: `specs/000-constitution.md` (**§2** offline tooling — NOT a graph node/edge; **§3**
  config constants; **§7** TDD; **§10** no `ContractState` change)

Backend paths relative to `backend/`.

**Workflow reminders:**
- TDD (§7): the matcher/scorer tests are written FAILING before their implementation.
- **Offline tooling only** — nothing under `app/**` changes; the harness only IMPORTS
  `app.runner.core.run_pipeline` + `app.config` at run time. No `app/graph/**`, no `ContractState`,
  no boundary model, no endpoint, no migration, no frontend.
- **Delivery-disable is safety-critical (plan §3.5/§6):** in `run.py`, set
  `app.delivery.delivery_step.MCP_DELIVERY_ENABLED = False` (the import-bound name — patching
  `app.config.…` is a NO-OP) **or** monkeypatch `app.runner.core.deliver_report_sync` → no-op, BEFORE
  any pipeline call. Getting the wrong target fires real Drive/Gmail.
- **Sidecar keys are raw-state keys** (`text` not `clause_text`; `final_status`, `relevance_verdict`,
  `isrel_verdict`, `issup_verdict`, `retry_count`, `path_taken`, `position`). `final_status`/
  `path_taken` are `str`-subclass enums → `json.dump` emits their value strings automatically; the
  scorer compares against `.value` strings.
- The matcher/scorer unit tests DO run in pytest; `run.py`/`score.py` (live Ollama) are exercised by
  the manual smoke (AC-9), not the runtime suite — like the existing per-node evals.

---

## Task 0: Branch
- [ ] From up-to-date `main`, create `feature/026-evaluation-harness` (`git-start`). Commit the 026
  `spec.md`/`plan.md`/`tasks.md` on the branch.

**Verify:** `git branch --show-current` → `feature/026-evaluation-harness`.

---

## Task 1: Config + schema
- [ ] **[NEW] `eval/harness/__init__.py`** (empty package marker).
- [ ] **[NEW] `eval/harness/config.py`** (§3, D7): `EVAL_MATCH_MIN_OVERLAP: float = 0.6`;
  `SEVERITY_RANK = {"low": 0, "medium": 1, "high": 2}`; `CONFIDENCE_BUCKETS = [0.0, 0.5, 0.7, 0.85,
  1.01]`. Named constants only; nothing hardcoded elsewhere.
- [ ] **[NEW] `eval/harness/schema.py`**: `load_gold(path) -> GoldDoc` validating the §2.1 shape
  (`document`, `clauses[{locator{section_number?, text_snippet}, should_flag, expected_severity∈
  {low,medium,high,None}, clause_type?, note?}]`), normalizing severity casing, raising a clear error
  on malformed input; `read_report(json_path)`, `read_sidecar(path)`, `read_manifest(run_dir)`;
  `build_sidecar(final_state_clauses) -> list[dict]` keeping the raw-state keys above (enum members
  dumped as-is → value strings).

**Verify:** `python -c "import eval.harness.config, eval.harness.schema"` from `backend/`; a trivial
shape test passes.

---

## Task 2: Matcher test (red) → matcher (green)
- [ ] **[NEW] `tests/unit/test_eval_matcher.py`** (confirm FAILING): synthetic findings + gold
  clauses. Cover: containment overlap scoring; a finding matches a gold clause by snippet overlap
  despite different `clause_id`/`position` (AC-2/AC-4); tie-break by `section_number` then nearer
  `position` (EC-2); one-to-one (no double-count); a surplus finding overlapping an already-matched
  `should_flag:true` clause is **dropped, not a false-flag** (EC-3); a finding overlapping no
  `should_flag:true` clause is a false-flag.
- [ ] **[NEW] `eval/harness/matcher.py`**: `normalize(s)` (lowercase, strip punctuation, collapse
  whitespace → tokens); `overlap(finding_text, snippet) = |tokens(snippet)∩tokens(finding)| /
  max(1,|tokens(snippet)|)`; `match(findings, gold) -> (matches, unmatched_findings, unmatched_gold)`
  greedy best-first (≥ `EVAL_MATCH_MIN_OVERLAP`, tie-break section then position, one-to-one) with the
  surplus-drop rule.

**Verify:** `pytest tests/unit/test_eval_matcher.py` → PASS.

---

## Task 3: Scorer test (red) → scorer (green)
- [ ] **[NEW] `tests/unit/test_eval_scorer.py`** (confirm FAILING): a hand-worked corpus of
  (report-dict, sidecar-list, gold) fixtures — sidecar fixtures use **plain strings** (`"validated"`,
  `"local_kb"`) matching the round-tripped live form. Cover: exact precision/recall/F1 (AC-1);
  miss-rate & false-flag-rate incl. the overlap-matched boundary case (AC-2); severity exact +
  within-one, `expected_severity None` excluded from severity but counted in detection (AC-3);
  `risk_level None` detected-but-severity-excluded (EC-4); confidence buckets; Self-RAG
  discard-contribution + CRAG path split from the **sidecar** (AC-5); `metrics.json` shape + non-empty
  summary with no network (AC-6); empty/all-miss/all-false-flag/empty-gold → N/A not div-by-zero
  (AC-7, EC-1/EC-7); an `ingest_error` report excluded from denominators (AC-8, EC-5).
- [ ] **[NEW] `eval/harness/scorer.py`**: pure functions computing the plan §3.4 metrics from
  (matches, unmatched_*, sidecar, report `node_timings`); undefined denominators → `None`; compares
  sidecar `final_status` against `ValidationStatus.VALIDATED.value` and `path_taken` against
  `RetrievalPath.LOCAL_KB.value`/`.WEB_FALLBACK.value`; returns a metrics dict.

**Verify:** `pytest tests/unit/test_eval_scorer.py` → PASS.

---

## Task 4: CLIs + gitignore
- [ ] **[NEW] `eval/harness/run.py`** (live): for each gold file — resolve `document` relative to
  `backend/`; **`app.delivery.delivery_step.MCP_DELIVERY_ENABLED = False`** before any call; invoke
  `run_pipeline(document_path=..., original_filename=<basename>)`; read report JSON at
  `Path(result.report_path).with_suffix(".json")`; build the sidecar from
  `result.final_state["clauses"]`; capture `result.final_state["document_id"]`; write
  `runs/<ts>/<gold-id>/report.json` + `sidecar.json` + append `runs/<ts>/manifest.json`
  (gold-id → {document_id, report path, sidecar path, ingest_error}). Idempotent (skip gold ids in the
  manifest); on pipeline exception/ingest_error, record it in the manifest and continue (EC-5).
- [ ] **[NEW] `eval/harness/score.py`** (offline): load a run dir's manifest; per entry load report +
  sidecar + matching gold; run matcher + scorer; write `runs/<ts>/metrics.json` and print a summary
  that **leads with the honesty caveat** (numbers only as good as the corpus). No Ollama, no network.
  **`score.py` must import ONLY `schema`/`matcher`/`scorer`/`config` — NOT `run.py` or any `app.*`
  module** (importing `run`/`app.runner.core` pulls the graph/FAISS chain and breaks the offline
  guarantee, AC-6).
- [ ] **[MODIFY] `.gitignore`**: ignore `backend/eval/runs/`.

**Verify:** `python -m eval.harness.score` help/arg parsing works offline; `tsc`-equivalent not
needed (Python).

---

## Task 5: Seed corpus + gold labels
- [ ] **[NEW] `eval/corpus/`**: copy 1–2 existing sample contracts (from `data/uploads/`) into the
  repo so gold `document` paths are self-contained.
- [ ] **[NEW] `eval/gold/*.json`**: hand-label the seed contracts per the §2.1 schema — label BOTH
  risky (`should_flag:true` + severity) AND explicitly-clean (`should_flag:false`) clauses so
  precision/false-flags are measurable. Include a `notes` field (who/when; "seed, indicative").

**Verify:** `load_gold` accepts each seed file without error.

---

## Task 6: Full verification
- [ ] **[NEW] `tests/unit/test_eval_boundary.py`** (AC-10): assert no file under `app/` imports
  `eval` (grep-style, mirroring the existing boundary tests).
- [ ] `pytest` (whole backend) GREEN.
- [ ] `git diff --name-only main` shows ONLY `eval/**`, `tests/unit/test_eval_*`, `.gitignore` — **no
  `app/**` change**, no `ContractState`, no migration, no frontend.

---

## Task 7: Live smoke (AC-9)
- [ ] Kill any stale uvicorn/python on :8000 from a prior session (see [[feature-023-complete]]
  gotcha) — not strictly needed (no server), but ensure Ollama (`qwen3:8b`) is up.
- [ ] `python -m eval.harness.run --gold eval/gold` (live Ollama, delivery OFF) → caches reports +
  sidecars + manifest; confirm **no Drive/Gmail delivery** occurred. Then `python -m eval.harness.score
  runs/<ts>` → a coherent metrics summary (precision/recall/severity/miss/false-flag + latency) on the
  seed set, led by the honesty caveat. Report the numbers.

---

## Task 8: Merge
- [ ] Whole `pytest` green; `git diff` scope confirmed (no `app/**`); smoke numbers noted.
- [ ] Rebase `main`, merge `feature/026-evaluation-harness`, delete branch (`git-finish`).

---

*Per §1/§11, implementation happens only on `feature/026-evaluation-harness`, opened after spec +
plan + tasks are approved. Offline tooling only; no runtime/app change, no migration.*
