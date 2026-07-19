# Feature 026 — Evaluation Harness (end-to-end accuracy measurement)

## 1. Problem statement

ContractSentinel emits risk findings, severities, and redlines from a **local 8B model** with **no
measured accuracy**. There are per-node offline evals (`backend/eval/eval_crag_confidence.py`,
`eval/eval_self_rag_validation.py`) that sanity-check distributions and branch behaviour, but there
is **no system-level evaluation against ground truth** — nobody can answer "on a labeled contract,
what fraction of the genuinely risky clauses does the pipeline catch, and how many does it flag
wrongly?" For a legal-risk tool that is the single most important missing capability: **you cannot
trust or safely tune the pipeline (including the 025 latency levers we just merged) without measuring
its precision/recall against expert labels.**

This feature builds an **offline evaluation harness** that runs the full pipeline over a
**gold-labeled corpus** and computes end-to-end detection/severity metrics + per-node diagnostics.

### Position relative to the constitution

**No amendment. NOT a graph node/edge. No `ContractState` change. No migration. No frontend.** This is
**offline tooling** under `backend/eval/`, exactly like the existing per-node eval scripts — it is
explicitly not part of the runtime 7-node pipeline (§2 fixed architecture is untouched) and not part
of the pytest runtime suite. It **consumes** the already-defined 009 `ContractReport` output — per-finding
`risk_level`/`path_taken`/`confidence_score`/`clause_text`/`section_number`/`position`, and the
**document-level** `node_timings` dict (per-node, not per-finding) — plus, for the miss-diagnosis
metric, a cached slice of the internal `final_state["clauses"]` verdicts (see §2.2). No boundary
model changes (§4). Any thresholds it introduces are named config constants (§3). Per §1/§11 it is developed on
`feature/026-evaluation-harness`; per §7 the pure scoring/matching logic is TDD-unit-tested (the live
pipeline run is the un-unit-testable part, as with the other evals).

## 2. Inputs and outputs

### 2.1 Gold-label dataset (the input contract for evaluation)
A directory `backend/eval/gold/` of one JSON file per labeled contract:
```jsonc
{
  "document": "eval/corpus/msa_acme.pdf",         // path to the source contract
  "notes": "hand-labeled 2026-07-…, reviewer: <who>",
  "clauses": [
    {
      "locator": { "section_number": "3.1", "text_snippet": "In no event shall…" },
      "should_flag": true,                          // is this clause genuinely risk-worthy?
      "expected_severity": "high",                  // "low"|"medium"|"high" | null (flag-only)
      "clause_type": "limitation_of_liability",     // optional
      "note": "uncapped-ish liability floor"
    }
    // … one entry per clause the reviewer assessed (both risky AND explicitly-clean clauses)
  ]
}
```
Labels are **clause-level**. Both `should_flag:true` (risky) and `should_flag:false` (explicitly
clean) clauses must be labeled so false-flag rate is measurable. `expected_severity` may be `null`
when the reviewer asserts "flag-worthy" without committing to a grade.

### 2.2 Harness — two phases (run once, score many)
Under `backend/eval/harness/`:
- **`run`** (needs live Ollama): for each gold file, invoke the real pipeline via the existing
  `run_pipeline(document_path, …)` (011/012 runner). `run_pipeline` returns a
  `RunResult(final_state, report_path, mcp_delivery_status, ingest_error)` — it does **not** hand back
  a `ContractReport`; the report JSON is written by `report_agent` to
  `Path(report_path).with_suffix(".json")` (i.e. `REPORT_OUTPUT_DIR/{document_id}.json`). The run
  phase therefore:
  - **Disables delivery** (there is no `deliver=` runner param): set `MCP_DELIVERY_ENABLED = False`
    (or monkeypatch `app.runner.core.deliver_report_sync` to a no-op) so no Drive/Gmail call is made.
  - **Copies two artifacts** into `backend/eval/runs/<timestamp>/<gold-id>/`: (a) the report JSON read
    from `RunResult.report_path`→`.json`; (b) a **verdict sidecar** — a slice of
    `RunResult.final_state["clauses"]` keeping each clause's `final_status`, `relevance/isrel/issup`
    verdicts, `retry_count`, `path_taken`, `text` (the raw-state clause-body key — the report model
    renames it to `clause_text`), `position` (needed for the miss-diagnosis/CRAG-path metrics that
    are NOT in the report — see §2.3).
  - **Writes a `manifest.json`** mapping each gold file → the pipeline's `document_id`
    (from `RunResult.final_state["document_id"]`, a **random UUID minted at ingest** so it can't be
    predicted before the run) and the cached artifact paths, so `score` can re-associate them offline.
  - Idempotent/resumable (skip gold docs already in the manifest).
- **`score`** (pure, offline, deterministic — **no Ollama**): using the run directory's
  `manifest.json`, load each gold file's cached report JSON + verdict sidecar, **match** findings ↔
  gold clauses, compute the metrics (§2.3), and emit `metrics.json` + a printed human-readable
  summary. This is the unit-tested core.

### 2.3 Metrics (output)
- **Detection** (each gold clause is a binary "should_flag"): **precision, recall, F1** for the
  pipeline flagging a clause; and the two legal-critical rates — **miss rate** (`should_flag:true`
  clauses with no finding) and **false-flag rate** (findings on `should_flag:false` clauses).
- **Severity accuracy** (over matched flagged clauses): exact-match accuracy + **within-one**
  accuracy (Low/Med/High adjacency), and a confusion matrix.
- **Confidence calibration:** findings bucketed by `confidence_score`, each bucket's empirical
  correctness (a reliability table) — surfaces whether the score means anything.
- **Per-node diagnostics** (these use the **verdict sidecar**, since discarded clauses are absent
  from `ContractReport.findings` — the report only carries VALIDATED clauses): Self-RAG **discard vs
  validate** contribution to misses (how many `should_flag:true` gold clauses map to a sidecar clause
  that was split/retrieved but `final_status != VALIDATED`, i.e. discarded — distinguishing a "we saw
  it but discarded it" miss from a "never split it" miss); CRAG **path split** (LOCAL_KB vs
  WEB_FALLBACK from `path_taken`) computed over the sidecar clauses (report `path_taken` alone would
  only cover surviving findings); rewrite-availability rate (from `rewrite_state` on findings).
- **Latency:** aggregate the document-level `node_timings` dicts (per-node p50/p95) across the corpus
  — ties the 025 levers to a measurable number.

### 2.4 Finding ↔ gold matching (the crux)
Pipeline clause boundaries do not align 1:1 with gold clauses (especially regex-only large docs after
025). Match each finding to at most one gold clause by **normalized text overlap** ≥
`EVAL_MATCH_MIN_OVERLAP` (§3 config), with `section_number`/`position` as tie-breakers; each gold
clause is matched at most once. Resolution of leftovers:
- a finding that matches **no** gold clause (or only a gold clause below the overlap threshold) →
  **false-flag** if it doesn't overlap any `should_flag:true` clause;
- a **surplus** finding that overlaps a `should_flag:true` gold clause already matched by another
  finding (pipeline over-split) → **dropped**, NOT counted as a false-flag (the clause is already
  credited as detected — EC-3);
- a `should_flag:true` gold clause with no matching finding → **miss**.
Matching is deterministic and unit-tested.

## 3. Resolved decisions (inline)

- **D1 — Offline harness under `backend/eval/harness/`; not a node, not in pytest runtime.** Mirrors
  the existing per-node evals. The runtime graph, `ContractState`, and API are untouched.
- **D2 — Gold labels are clause-level and hand-authored** (§2.1 schema). Both risky and clean clauses
  are labeled so precision/false-flags are real. Stored as JSON under `backend/eval/gold/`, source
  contracts under `backend/eval/corpus/`.
- **D3 — Two-phase run/score split** (§2.2). The slow, Ollama-dependent run is cached once; scoring is
  pure and fast so metrics can be recomputed/iterated without re-running the pipeline. Scoring is the
  §7 TDD core.
- **D4 — Overlap-based matching** (§2.4), not exact clause-id equality — because the splitter's
  boundaries won't match the reviewer's, and 025's regex-only path widens that gap. Threshold is a
  tunable §3 constant.
- **D5 — Ship a SMALL seed gold set + be honest about its limits.** A handful of hand-labeled
  contracts are committed as a working example + template. **Trustworthy numbers require a larger,
  expert-labeled corpus** — the harness provides the *measurement machinery and schema*, not the
  labels. No "silver" labels derived from the system's own output (circular).
- **D6 — Redline quality is NOT auto-graded in v1.** Judging rewrite quality with the same weak local
  model is circular; primary metrics are detection + severity. A human/LLM-judge redline rubric is a
  future extension (§6). The harness does report rewrite-availability (did a rewrite get produced).
- **D7 — Config §3 in one place: `backend/eval/harness/config.py`.** `EVAL_MATCH_MIN_OVERLAP`, the
  severity-adjacency definition, and the confidence buckets are named constants in that single eval
  config module (kept out of the runtime `app/config.py` hot path but still centralized, not
  scattered inline).
- **D8 — Reuse `run_pipeline` verbatim** (011/012), with **delivery disabled via
  `MCP_DELIVERY_ENABLED=False`** (there is no `deliver=` param — delivery is config-gated); the
  harness must measure the REAL pipeline, not a reimplementation, so results reflect production
  behaviour (incl. the 025 levers). It reads the report from `RunResult.report_path`→`.json`, not a
  returned model.

## 4. Acceptance criteria

### Scoring core (pytest — deterministic, no Ollama)
- **AC-1:** Given synthetic (report findings, gold clauses) fixtures, the scorer computes correct
  **precision / recall / F1** for detection (verified on a hand-worked example incl. true/false
  positives and misses).
- **AC-2:** **Miss rate** and **false-flag rate** are computed correctly, including the boundary case
  where a finding matches a gold clause by overlap despite differing clause ids/positions.
- **AC-3:** **Severity accuracy** (exact + within-one) is correct over matched flagged clauses, and
  `expected_severity: null` gold clauses are excluded from severity scoring but still count for
  detection.
- **AC-4:** The **matcher** maps a finding to the best-overlap gold clause ≥ `EVAL_MATCH_MIN_OVERLAP`,
  respects the tie-breakers, and matches each finding/gold clause at most once (no double-counting).
- **AC-5:** Per-node diagnostics are computed from the cached run artifacts: Self-RAG
  discard-contribution-to-misses and the CRAG path split from the **verdict sidecar**
  (`final_status`, `path_taken` per clause — since discarded clauses are absent from the report), and
  latency aggregates from the report's document-level `node_timings`.
- **AC-6:** `score` emits a `metrics.json` with all metrics and a non-empty human-readable summary; it
  runs with **no Ollama and no network** against cached report fixtures.

### Edge & robustness (pytest)
- **AC-7:** Empty findings, all-miss, all-false-flag, and empty-gold corpora produce well-defined
  metrics (no div-by-zero; rates reported as N/A where undefined) — see §5.
- **AC-8:** A gold doc whose cached report has an `ingest_error` is reported as an evaluation error
  for that doc and excluded from rate denominators (not silently counted as all-miss).

### Live (real backend)
- **AC-9 (smoke, manual):** `run` executes the real pipeline over the seed gold set (live Ollama,
  delivery stubbed) and caches reports; `score` on that run prints a coherent metrics summary
  (precision/recall/severity/miss/false-flag + latency) with plausible numbers on the seed set.
- **AC-10:** The harness is **not** imported by the runtime app or the pytest runtime suite (grep
  boundary): nothing under `app/` imports `eval/`; the graph/`ContractState` are unchanged
  (`git diff` shows no `app/graph/**` / state change).

## 5. Edge cases
- **EC-1 — No `should_flag:true` gold clauses** → recall undefined → reported "N/A", detection still
  reports precision/false-flags.
- **EC-2 — A finding overlaps two gold clauses equally** → tie-break by `section_number` then
  `position`; still one-to-one (AC-4).
- **EC-3 — Multiple findings overlap one gold clause** (over-split) → count the gold clause as
  detected once; extra findings are not double-counted as false-flags if they overlap a
  `should_flag:true` clause (documented matching rule).
- **EC-4 — `risk_level: None` finding** (severity unavailable) matched to a `should_flag:true` clause
  → counts as detected for recall, excluded from severity accuracy.
- **EC-5 — Pipeline ingest_error / crash on a gold doc** → recorded as a per-doc eval error, excluded
  from denominators (AC-8); the run continues to the next doc.
- **EC-6 — Gold `text_snippet` not found / low overlap with any finding or clause** → that gold clause
  is a miss (if `should_flag:true`) or ignored (if clean and unflagged); logged for reviewer QA.
- **EC-7 — Empty gold corpus** → the harness reports "no gold data" and exits cleanly (D5 honesty:
  metrics are only as good as the corpus).

## 6. Out of scope
- **Authoring the expert-labeled corpus** beyond a small committed seed (D5) — that is a data-collection
  effort (ideally lawyer-reviewed), not a code deliverable.
- **Auto-grading redline/rewrite quality** (D6) — a future human/LLM-judge rubric.
- **Model/config A-B comparison automation, CI gating, statistical-significance testing** — future;
  v1 produces the metrics, not a regression gate.
- **Any runtime pipeline / `ContractState` / API / frontend / migration change** — none.

## 7. Evaluation (metrics this feature exists to log)
Since this harness measures CRAG/Self-RAG/risk-scoring outputs, the metrics it logs (per §2.3) are
exactly the constitution-relevant ones: **detection precision/recall/F1, miss rate, false-flag rate,
severity exact + within-one accuracy, confidence-score reliability buckets, Self-RAG discard-vs-validate
rate, CRAG retrieval-path (LOCAL_KB vs WEB_FALLBACK) hit split, and per-node latency (p50/p95)**. These
are written to `metrics.json` per run so successive runs (e.g. before/after a tuning change or a model
swap) can be compared. **Honesty caveat carried in the summary output:** all rates are only as
meaningful as the size/quality of the gold corpus (seed set = indicative, not authoritative).

## 8. Notes for plan.md / tasks.md (pointers)
- **Layout:** `backend/eval/harness/{config.py, schema.py, matcher.py, scorer.py, run.py, score.py}`
  (config.py = the §3 eval constants, D7); `backend/eval/gold/*.json` (seed labels);
  `backend/eval/corpus/*` — seed **source contracts copied into the repo** (a couple of the existing
  `data/uploads` PDFs/DOCX, so the gold `document` path is self-contained and not dependent on
  gitignored runtime `data/`); `backend/eval/runs/` (gitignored cache: report JSON + verdict sidecar +
  `manifest.json` per run).
- **Run mechanics:** invoke `run_pipeline(document_path=..., original_filename=...)`; set
  `MCP_DELIVERY_ENABLED=False` (monkeypatch/config) for the run; read the report at
  `Path(RunResult.report_path).with_suffix(".json")`; capture `RunResult.final_state["document_id"]`
  and the `final_state["clauses"]` verdict slice; write the manifest.
- **Tests:** `backend/tests/unit/test_eval_scorer.py`, `test_eval_matcher.py` (pure, deterministic,
  fixture-driven — synthetic report+gold dicts) — these DO run in pytest; `run.py`/`score.py` CLIs are
  exercised by the live smoke (AC-9), not the runtime suite.
- **Honest framing** must appear in the summary output and README-ish module docstring: the harness is
  the measurement tool; the numbers depend on the corpus.
