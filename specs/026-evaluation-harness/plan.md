# Evaluation Harness — Technical Plan

## Git Branch

`feature/026-evaluation-harness` — branching workflow per `specs/000-constitution.md` §11.

---

## 1. Overview

Implements `specs/026-evaluation-harness/spec.md` — an **offline** system-level accuracy harness under
`backend/eval/harness/`. It runs the **real** pipeline (`run_pipeline`, delivery disabled) over a
gold-labeled corpus, caches each report JSON + a per-clause **verdict sidecar** + a `manifest.json`,
then a pure **offline scorer** matches findings ↔ gold clauses and computes detection
(precision/recall/F1, miss & false-flag rates), severity accuracy, confidence calibration, per-node
diagnostics, and latency. **Not a graph node/edge, no `ContractState` change, no migration, no
frontend** (§2/§10). The scoring/matching core is TDD-unit-tested in the pytest suite; the
live-Ollama `run` and the CLIs are exercised by the manual smoke (AC-9), mirroring the existing
per-node evals.

---

## 2. Files to Create / Modify

### Backend (`backend/`)
```
eval/harness/__init__.py            [NEW]  package marker
eval/harness/config.py              [NEW]  §3 eval constants (EVAL_MATCH_MIN_OVERLAP, severity ranks, confidence buckets)
eval/harness/schema.py              [NEW]  load/validate gold JSON (dataclasses/TypedDicts) + run-artifact readers (report json, verdict sidecar, manifest)
eval/harness/matcher.py             [NEW]  deterministic finding↔gold overlap matching (one-to-one + tie-breakers + surplus-drop)
eval/harness/scorer.py              [NEW]  pure metric computation from (report, sidecar, gold) → metrics dict
eval/harness/run.py                 [NEW]  CLI: run pipeline over gold corpus (live Ollama, delivery off), cache report+sidecar+manifest
eval/harness/score.py               [NEW]  CLI: load a run dir via manifest, score, emit metrics.json + printed summary
eval/gold/*.json                    [NEW]  small seed gold label files (§2.1 schema)
eval/corpus/*                       [NEW]  seed source contracts copied into the repo (a couple of existing data/uploads samples)
.gitignore                          [MODIFY] ignore backend/eval/runs/ (cache)

tests/unit/test_eval_matcher.py     [NEW]  matcher: overlap, tie-breakers, one-to-one, surplus-drop (AC-4, EC-2/3)
tests/unit/test_eval_scorer.py      [NEW]  precision/recall/F1, miss/false-flag, severity exact+within-one, calibration, diagnostics, edge cases (AC-1..8)
```
No `app/**` change (the harness only IMPORTS `app.runner.core.run_pipeline` + `app.config` at run
time). No `app/graph/**`, no `ContractState`, no boundary model, no endpoint, no migration.

---

## 3. Design

### 3.1 `config.py` (§3 constants — D7)
- `EVAL_MATCH_MIN_OVERLAP: float = 0.6` — min gold-snippet containment to count a finding↔gold match.
- `SEVERITY_RANK = {"low": 0, "medium": 1, "high": 2}` — for exact + within-one severity scoring.
- `CONFIDENCE_BUCKETS = [0.0, 0.5, 0.7, 0.85, 1.01]` — reliability-table bin edges.
All named/centralized here; nothing hardcoded in matcher/scorer.

### 3.2 `schema.py`
- `GoldClause { locator: {section_number?, text_snippet}, should_flag: bool, expected_severity:
  "low"|"medium"|"high"|None, clause_type?: str, note?: str }`; `GoldDoc { document: str, notes?,
  clauses: [GoldClause] }`. `load_gold(path)` validates shape, normalizes severity casing, raises a
  clear error on malformed files.
- Run-artifact readers: `read_report(json_path) -> dict` (the 009 report dict), `read_sidecar(path)
  -> list[clause verdict dict]`, `read_manifest(run_dir)`.
- **Verdict sidecar record** (sliced from raw `final_state["clauses"]` — raw-state keys, NOT report
  names): `text` (clause body — NOT `clause_text`), `position`, `final_status`, `relevance_verdict`,
  `isrel_verdict`, `issup_verdict`, `retry_count`, `path_taken`.
- **Serialization note:** `final_status` (`ValidationStatus`) and `path_taken` (`RetrievalPath`) are
  **`str`-subclass enums**, so `json.dump` serializes them to their value strings automatically
  (`"validated"`, `"local_kb"`, `"web_fallback"`) — no `TypeError`, no manual conversion needed. Do
  **not** use `str(member)` (that yields the qualified name `"ValidationStatus.VALIDATED"`); dump the
  member directly or use `.value`. After the JSON round-trip the sidecar holds **plain strings**, so
  the scorer compares against the string values (`ValidationStatus.VALIDATED.value` /
  `RetrievalPath.LOCAL_KB.value` / `.WEB_FALLBACK.value`), and the unit fixtures use those same plain
  strings — keeping the test and live paths in agreement (§3.4).

### 3.3 `matcher.py`
- `normalize(s)`: lowercase, strip punctuation, collapse whitespace → token list.
- `overlap(finding_text, gold_snippet)`: **containment** = `|tokens(snippet) ∩ tokens(finding)| /
  max(1, |tokens(snippet)|)` (snippet is a fragment of the clause, so measure how much of it appears
  in the finding). Range 0..1.
- `match(findings, gold_clauses)`: greedy best-first — compute all (finding, gold) overlaps ≥
  `EVAL_MATCH_MIN_OVERLAP`, sort desc (tie-break: `section_number` exact-equal first, then nearer
  `position`), assign one-to-one (each finding and each gold clause used at most once). Returns
  `matches: [(finding, gold)]`, `unmatched_findings`, `unmatched_gold`.
- **Surplus rule (EC-3):** a still-unmatched finding that overlaps (≥ threshold) an already-matched
  `should_flag:true` gold clause is classified **surplus → dropped** (not a false-flag). Remaining
  unmatched findings that overlap no `should_flag:true` clause → false-flags.

### 3.4 `scorer.py` (pure; the TDD core)
Given matched/unmatched sets across the whole corpus:
- **Detection:** TP = matched to `should_flag:true`; FP = false-flags (per surplus rule); FN =
  unmatched `should_flag:true`. `precision = TP/(TP+FP)`, `recall = TP/(TP+FN)`, `F1`; **miss rate =
  FN/(TP+FN)**, **false-flag rate = FP/(FP + TN)** where TN = matched-or-unflagged `should_flag:false`
  clauses. Undefined denominators → `None` (rendered "N/A").
- **Severity** (over TP with `expected_severity != None` and finding `risk_level != None`): exact =
  ranks equal; within-one = `|rank diff| <= 1`; also a 3×3 confusion matrix. `risk_level None` or
  `expected_severity None` → excluded from severity, still counted in detection (EC-4).
- **Confidence calibration:** bin TP∪FP findings by `confidence_score` into `CONFIDENCE_BUCKETS`;
  per bucket report count + empirical "correct" fraction (correct = matched to `should_flag:true`).
- **Per-node diagnostics (from the sidecar; string comparisons, §3.2):** Self-RAG
  **discard-contribution-to-misses** = of the FN gold clauses, how many map (by overlap) to a sidecar
  clause with `final_status != ValidationStatus.VALIDATED.value` (seen-but-discarded) vs none
  (never-split); CRAG **path split** = `RetrievalPath.LOCAL_KB.value` vs `.WEB_FALLBACK.value` counts
  over sidecar `path_taken`; rewrite-availability = `rewrite_state == "rewritten"` fraction of findings.
- **Latency:** per-node p50/p95 over each doc's report `node_timings` dict; with an empty/zero-doc
  corpus, latency (like the rates) is reported as N/A rather than raising.
- **Per-doc errors (AC-8):** a doc whose report has `ingest_error` set → recorded in
  `metrics["errors"]`, excluded from all rate denominators.

### 3.5 `run.py` (live)
- For each gold file: resolve the `document` path **relative to `backend/`** (the pipeline cwd, same
  anchor as `REPORT_OUTPUT_DIR`; gold `document` values are `eval/corpus/…` backend-relative). Call
  `run_pipeline(document_path=..., original_filename=<basename>)`.
- **Disable delivery correctly (safety-critical):** `deliver_report_sync` reads the flag as a
  **module-level name bound at import** in `app.delivery.delivery_step` (`MCP_DELIVERY_ENABLED =
  _config.MCP_DELIVERY_ENABLED`, delivery_step.py:31) — so setting `app.config.MCP_DELIVERY_ENABLED`
  has **no effect**. Set **`app.delivery.delivery_step.MCP_DELIVERY_ENABLED = False`** before any
  pipeline call (or, equivalently, monkeypatch **`app.runner.core.deliver_report_sync`** → no-op,
  since `core.py:25` does `from app.delivery import deliver_report_sync`, binding it in the `core`
  namespace — patching `app.delivery.deliver_report_sync` would NOT affect that bound reference).
- From the returned `RunResult`: read the report JSON at `Path(result.report_path).with_suffix(".json")`;
  build the verdict sidecar from `result.final_state["clauses"]`; capture
  `result.final_state["document_id"]`.
- Write `runs/<timestamp>/<gold-id>/report.json` + `.../sidecar.json`; append to
  `runs/<timestamp>/manifest.json` (gold-id → {document_id, report path, sidecar path, ingest_error}).
- Idempotent: skip gold ids already in the manifest. On a pipeline exception/ingest_error, record it
  in the manifest and continue (EC-5).

### 3.6 `score.py` (offline)
- Load a run dir's manifest; for each entry load report + sidecar + the matching gold file; run
  `matcher` + `scorer`; write `runs/<timestamp>/metrics.json` and print a summary that **leads with the
  honesty caveat** (numbers only as good as the corpus, seed = indicative). No Ollama, no network.

---

## 4. Tests mapped to acceptance criteria

**Backend (pytest — pure, deterministic, fixture-driven; synthetic report/sidecar/gold dicts).**
- `test_eval_matcher.py`: overlap containment scoring; a finding matches a gold clause by snippet
  overlap despite different ids/positions (AC-2/AC-4); tie-break by section then position (EC-2);
  one-to-one (no double-count); surplus finding on an already-matched risky clause is dropped, not a
  false-flag (EC-3).
- `test_eval_scorer.py`: hand-worked corpus → exact precision/recall/F1 (AC-1); miss & false-flag
  rates incl. the overlap-matched boundary case (AC-2); severity exact + within-one, with
  `expected_severity None` excluded from severity but counted in detection (AC-3); `risk_level None`
  finding detected-but-severity-excluded (EC-4); confidence buckets; Self-RAG discard-contribution +
  CRAG path split computed from a synthetic **sidecar** (AC-5); `metrics.json` shape + non-empty
  summary, runs with no network (AC-6); empty/all-miss/all-false-flag/empty-gold → N/A not div-by-zero
  (AC-7, EC-1/EC-7); ingest_error doc excluded from denominators (AC-8, EC-5).
- **AC-10 boundary:** a test (or the existing import-boundary style) asserting nothing under `app/`
  imports `eval/`; `git diff` shows no `app/graph/**` / `ContractState` change.

**Live smoke (AC-9):** `python -m eval.harness.run --gold eval/gold` (live Ollama, delivery off) then
`python -m eval.harness.score runs/<ts>` → coherent metrics summary on the seed set.

---

## 5. Implementation order (TDD — §7)

1. **config + schema:** constants + gold/artifact loaders (+ trivial shape tests).
2. **Matcher test (red) → matcher (green):** `test_eval_matcher.py` first; implement `matcher.py`.
3. **Scorer test (red) → scorer (green):** `test_eval_scorer.py` first (all metrics + edges);
   implement `scorer.py` until green.
4. **CLIs:** `run.py` (live) + `score.py` (offline) wiring; `.gitignore` runs/.
5. **Seed data:** copy 1–2 sample contracts into `eval/corpus/`; hand-label matching `eval/gold/*.json`.
6. **Verify:** `pytest` (whole backend) GREEN — the new unit tests pass and nothing else regresses;
   `git diff --name-only main` shows only `eval/**`, `tests/unit/test_eval_*`, `.gitignore` — no
   `app/**` change.
7. **Live smoke (AC-9):** run + score on the seed set; capture metrics.json; report numbers with the
   honesty caveat.

Each step's tests are written failing first (§7). The live `run` is not in the pytest suite (needs
Ollama), consistent with the existing evals.

---

## 6. Notes / risks

- **Delivery MUST be disabled for the run, at the RIGHT target** — `run_pipeline` calls
  `deliver_report_sync` unconditionally. The gate is a module-level name in
  `app.delivery.delivery_step` bound at import, so patch
  **`app.delivery.delivery_step.MCP_DELIVERY_ENABLED = False`** (NOT `app.config.…`, which has no
  effect) or monkeypatch **`app.runner.core.deliver_report_sync`** → no-op. Getting the wrong target
  silently fires real Drive/Gmail. The run CLI sets this before any pipeline call. (§3.5)
- **document_id is a random UUID at ingest** — never predict the report filename; always take it from
  `RunResult.report_path` / `final_state["document_id"]` and persist the manifest (else run↔score
  can't re-associate).
- **Sidecar uses raw-state keys** (`text`, not `clause_text`; the verdicts + `final_status` +
  `path_taken` + `retry_count` + `position`) — do not use report field names when slicing
  `final_state["clauses"]`.
- **Findings are VALIDATED-only** — discard/CRAG-path facts come from the sidecar, not the report.
- **Matching is heuristic** — overlap containment can mis-associate near-duplicate clauses; the
  threshold is a tunable §3 constant and the summary logs unmatched gold/findings for reviewer QA.
- **Honesty** — the seed corpus yields indicative, not authoritative, numbers; the summary and module
  docstring say so. A larger expert-labeled corpus is the real prerequisite (spec D5).
- **Slow live run** — the pipeline is minutes/doc; keep the seed corpus small and the run resumable.

---

*Per §1/§11, a `feature/026-evaluation-harness` branch opens only after this plan.md + spec.md are
approved and `tasks.md` exists. Offline tooling only; no runtime/app change, no migration. No
`tasks.md`/implementation in this pass — plan only.*
