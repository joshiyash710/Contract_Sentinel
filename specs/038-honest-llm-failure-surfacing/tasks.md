# Feature 038 — Honest LLM-Failure Surfacing — Tasks

TDD-ordered (constitution §7): each implementation task is preceded by the test
that must first be written and confirmed failing. Tests are never weakened to
force a pass. Every task traces to a spec acceptance criterion (AC-1..AC-13) or a
plan section (§n). Branch: `feature/038-honest-llm-failure-surfacing`.

Run backend tests from `backend/`: `python -X utf8 -m pytest`. Run frontend tests
from `frontend/`: `npm test`.

---

## Phase A — Schema amendment + config (prerequisite, §10)

### T1 — Amend 001 state schema FIRST (plan §1.1, AC-13, §10)
Edit `specs/001-contract-state-schema.md`:
- In §3, under the `clauses` clause-record sub-field comment block (near
  `risk_level` / `risk_rationale`), add:
  `#   is_failsafe: Optional[bool]  # True if risk_level was assigned by the Node 5 fail-safe path (LLM failure/unparseable/circuit-open/empty-or-oversize text) rather than a genuine model judgment. Written by RiskScoreAgent only.`
- Add a brief revision-note paragraph (mirror §6 decision style) recording:
  feature 038, §10 spec-first rationale; purely additive simple per-clause field;
  rides the existing `merge_nested_clause_dicts` reducer; no top-level field, no
  reducer change. No code writes `is_failsafe` before this task is committed.

### T2 — Config constants (plan §1.2, §3)
Edit `app/config.py`:
- Add `HONEST_FAILURE_SURFACING_ENABLED: bool = _env_bool("HONEST_FAILURE_SURFACING_ENABLED", True)`
  (reuse the existing `_env_bool` helper verbatim).
- Add `ANALYSIS_DEGRADED_FAILSAFE_FRACTION: float = 0.5` as a plain float literal
  (no `_env_float` exists; match `OCR_LOW_CONFIDENCE_THRESHOLD` style).

---

## Phase B — Node 5 writes the signal (AC-1, AC-2, AC-10)

### T3 (test) — risk_score_agent is_failsafe writes
In the existing risk-score agent test module (grep
`tests/**/*risk_score*` for the file), add tests:
- Flag ON: an empty-text validated clause → clause update has `is_failsafe: True`.
- Flag ON: circuit-open bulk path → `is_failsafe: True` (drive ≥ threshold
  consecutive LLM failures so `cb["open"]`, then assert remaining clauses True).
- Flag ON: LLM-None path (mock `score_risk`→None) → `is_failsafe: True`.
- Flag ON: genuine score (mock `score_risk`→(RiskLevel.LOW, "ok")) →
  `is_failsafe: False`.
- Flag OFF (monkeypatch `HONEST_FAILURE_SURFACING_ENABLED=False`): none of the
  above clause updates contain the `is_failsafe` key at all (AC-10).
Confirm failing.

### T4 (impl) — write is_failsafe in risk_score_agent (plan §1.3)
Edit `app/graph/nodes/risk_score_agent.py`:
- Import `HONEST_FAILURE_SURFACING_ENABLED` from `app.config`; read once into a
  local `honest = HONEST_FAILURE_SURFACING_ENABLED` at the top of the node fn.
- Add kw param to helper: `def _failsafe(reason: str, *, mark_failsafe: bool = False)`;
  when `mark_failsafe`, include `"is_failsafe": True` in the returned dict; else
  return exactly today's dict. Update all **3** call sites (empty-text ~L115,
  circuit-open ~L123, LLM-None ~L146) to pass `mark_failsafe=honest`.
- In the genuine-scoring branch (the `else` with a real `(level, rationale)`):
  when `honest`, add `"is_failsafe": False` to that clause update; else leave the
  update exactly as today.
- Do not change `error_count` / circuit-breaker logic; retain the `[auto]`
  rationale marker.
Run T3 → green.

---

## Phase C — Report boundary model + assembler (AC-3, AC-4, AC-5, AC-10)

### T5 (test) — report model defaults
In `tests/**/*report*` model tests, assert: a `ContractReport` built from a JSON
dict lacking `analysis_degraded`/`failsafe_count`/finding `is_failsafe`
deserializes with defaults `False`/`0`/`False` (legacy-safe). Confirm failing.

### T6 (impl) — extend report models (plan §1.4)
Edit `app/models/report.py`:
- `ReportFinding`: add `is_failsafe: bool = False`.
- `ReportSummary`: add `failsafe_count: int = 0`.
- `ContractReport`: add `analysis_degraded: bool = False`.
Run T5 → green.

### T7 (test) — assemble_report degraded logic
In `tests/**/*assembl*`/report-assembler tests, add:
- Per-finding `is_failsafe` copied from clause record (True/False/absent→False) (AC-5).
- `failsafe_count` == count of failsafe validated findings; `<= validated_findings` (AC-4).
- `analysis_degraded` truth table (AC-3/D2), passing `honest_enabled=True`,
  `degraded_fraction=0.5`:
  - `error_count>=1`, 0 findings → True (circuit arm, div-by-zero guard).
  - `error_count=0`, failsafe fraction 0.6 → True (fraction arm).
  - `error_count=0`, failsafe fraction 0.4 → False.
  - `error_count=0`, 0 findings → False.
  - `ingest_error` branch → `analysis_degraded=False`.
  - `honest_enabled=False` → `analysis_degraded=False`, `failsafe_count=0`, all
    finding `is_failsafe=False` regardless of clause data (AC-10).
Confirm failing.

### T8 (impl) — assemble_report (plan §1.5)
Edit `app/graph/nodes/renderers/report_assembler.py`:
- Add params `honest_enabled: bool` and `degraded_fraction: float` to
  `assemble_report(...)`.
- Copy `is_failsafe = bool(record.get("is_failsafe"))` onto each `ReportFinding`
  (force `False` when `not honest_enabled`).
- Compute `failsafe_count` (0 when `not honest_enabled`).
- Compute `analysis_degraded` per plan §1.5 snippet (circuit arm OR fraction arm;
  div-by-zero guard; `False` for ingest_error branch and when `not honest_enabled`).
- Emit the Evaluation structured log line (failsafe_count, validated_findings,
  frac, circuit_tripped, analysis_degraded, trigger reason).
Run T7 → green.

### T9 (impl) — report_agent passes config (plan §1.6)
Edit `app/graph/nodes/report_agent.py`: at the `assemble_report(...)` call, pass
`honest_enabled=HONEST_FAILURE_SURFACING_ENABLED`,
`degraded_fraction=ANALYSIS_DEGRADED_FAILSAFE_FRACTION` (import both from
`app.config`). Fix any other `assemble_report` call sites (grep) to pass the new
params (tests may call it directly — update them to the new signature).

---

## Phase D — Renderers: banner + inline tag (AC-6, AC-7, AC-8)

### T10 (test) — markdown banner + tag
In markdown-renderer tests: `analysis_degraded=True` → body contains the banner
marker before the findings section; `False` → no marker. A finding with
`is_failsafe=True` → its severity line carries an "(auto-assigned)" marker;
`False` → none. Confirm failing.

### T11 (impl) — markdown_renderer (plan §1.7)
Edit `app/graph/nodes/renderers/markdown_renderer.py`: prepend the degraded
banner block before the findings section when `report.analysis_degraded`; add the
inline "(auto-assigned)" marker on each `is_failsafe` finding's severity. Leave
the `**Upstream errors:**` footer unchanged. Run T10 → green.

### T12 (test+impl) — PDF (plan §1.8, AC-7/AC-8)
Test (`tests/**/*report_pdf*`): with `analysis_degraded=True` the generated PDF
bytes/story contains the banner text and, for a failsafe finding, the auto tag;
`False` → neither. Then implement in `app/delivery/report_pdf.py` (banner flowable
at top of story; auto tag on failsafe finding severity). Green.

### T13 (test+impl) — HTML email (plan §1.9, AC-7/AC-8)
Test (`tests/**/*email_html*`): degraded → banner `<div>` + per-finding auto tag
present in HTML; not degraded → absent. Implement in `app/delivery/email_html.py`.
Green.

---

## Phase E — History/dashboard badge (AC-9 backend half)

### T14 (test) — aggregate surfaces analysis_degraded
In `tests/**/*aggregate*`: `read_report_data` on a report JSON with
`analysis_degraded=True` → `ReportData.analysis_degraded is True` (and `False`/
missing → False); `build_job_list` copies it onto `JobListItem.analysis_degraded`.
Confirm failing.

### T15 (impl) — aggregate + JobListItem (plan §1.10)
- Edit `app/runner/models.py`: add `analysis_degraded: bool = False` to
  `JobListItem`.
- Edit `app/api/aggregate.py`: add `analysis_degraded: bool = False` to the
  `ReportData` dataclass, read `data.get("analysis_degraded", False)` in
  `read_report_data`, and set it on the item in `build_job_list`.
Run T14 → green. `build_dashboard_metrics` risk math unchanged (out of scope).

---

## Phase F — Frontend (AC-9) — only after Phases A–E green

### T16 (test) — frontend types + report/badge rendering
Add/extend Vitest+RTL tests (`frontend/src/__tests__/`):
- Report renders a degraded banner iff `report.analysis_degraded`; a finding shows
  an "(auto)" tag iff `finding.is_failsafe`; missing fields → no banner/tag.
- History/dashboard row shows a "Degraded" badge iff `JobListItem.analysis_degraded`.
Add a degraded fixture in `lib/api/fixtures.ts`. Confirm failing.

### T17 (impl) — frontend (plan §2)
- `lib/api/types.ts`: add `is_failsafe?: boolean` (ReportFinding),
  `failsafe_count?: number` (ReportSummary), `analysis_degraded?: boolean`
  (ContractReport), `analysis_degraded?: boolean | null` (JobListItem).
- New `components/report/DegradedBanner.tsx`; render it in `ReportView.tsx`/
  `AnalysisWorkspace.tsx` when `analysis_degraded` truthy.
- `FindingCard.tsx` / `FindingRiskBadge.tsx`: "(auto)" tag when `is_failsafe`.
- `history/ReportHistoryView.tsx`, `dashboard/DashboardView.tsx`, `ReportsView.tsx`:
  "Degraded" badge when the row's `analysis_degraded` is truthy (reuse an existing
  badge component — confirm the exact one, e.g. `ui/StatusBadge.tsx`).
- Thread fields through `realProvider.ts` / `mockProvider.ts` / `fixtures.ts`.
Run T16 + `npm test` + `tsc` → green.

---

## Phase G — Reversibility + full suite (AC-10, AC-11)

### T18 (test) — reversibility integration
Backend test: with `HONEST_FAILURE_SURFACING_ENABLED=False`, assemble a report
from a state that WOULD degrade (failsafe clauses + error_count) and assert the
report JSON has `analysis_degraded=False`, `failsafe_count=0`, every finding
`is_failsafe=False`, and the markdown output contains no banner marker (proxy for
byte-identical prior behavior). Green.

### T19 — full suites + graph-unchanged check (AC-11)
Run the full backend suite (`python -X utf8 -m pytest`) and frontend
(`npm test` + `tsc --noEmit`) — all green. Confirm no change to
`app/graph/builder.py` (no node/edge added) and no new `node_timings` key.

---

## Phase H — Handoff
Live smoke (owner-run, [[feedback_run_real_smoke_before_continuation]]): run the
app on live Ollama, start an analysis, stop Ollama mid-run to force the risk-score
circuit breaker, and confirm the degraded banner appears in the report page + PDF
+ email and the "Degraded" badge on the history/dashboard. Then `/code-review` and
git-finish.
