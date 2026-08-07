# Feature 038 — Honest LLM-Failure Surfacing — Technical Plan

Branch: `feature/038-honest-llm-failure-surfacing` (git workflow per constitution §11).

This plan implements the approved `spec.md` without scope drift. It adds **no
LangGraph node or edge** (constitution §2). It is a surfacing/plumbing feature:
persist the per-clause fail-safe signal Node 5 already computes, carry it through
the `ContractReport` boundary model at Node 7, derive a single top-level
`analysis_degraded` flag, and render an honest degraded-analysis banner + inline
"auto-assigned" tags in Markdown, PDF, HTML email, and the frontend — plus a
"Degraded" badge on the history/dashboard lists. Fully reversible via
`HONEST_FAILURE_SURFACING_ENABLED`.

## 0. Constitution touchpoints

- **§10 Spec-First Change (blocking prerequisite).** The only `ContractState`
  change is a new documented per-clause sub-field `is_failsafe: Optional[bool]`.
  Per §10 and spec D1/AC-13, `specs/001-contract-state-schema.md` is amended
  **first**, with a written rationale, before any code writes the field. This is
  Task 1 and gates all code tasks.
- **§2 Fixed Architecture.** No node/edge added; the 7-node/2-edge graph builder
  is untouched (AC-11). Nothing from PHASE 2 DEFERRED / PERMANENTLY CUT is touched
  (the degraded badge is a per-report honesty marker, not an audit-log UI).
- **§3 Configurable Thresholds.** Two named constants in `app/config.py`:
  `HONEST_FAILURE_SURFACING_ENABLED` (master reversible lever) and
  `ANALYSIS_DEGRADED_FAILSAFE_FRACTION` (tunable, default `0.5`). No inline magic
  numbers.
- **§4 State Typing.** `is_failsafe` is a plain `bool` in the TypedDict `clauses`
  dict (internal). `analysis_degraded` / `failsafe_count` / per-finding
  `is_failsafe` live on the Pydantic boundary model `ContractReport` (never stored
  in state). The two are not mixed.
- **§5 Partial-Update.** `risk_score_agent` already returns a partial `clauses`
  dict; we only add one key to the per-clause updates it already emits.
- **§9 Local-model latency.** No new LLM call, retry, or timeout is introduced;
  we only read an already-computed outcome, so latency characteristics are
  unchanged.

## 1. Backend changes (file by file)

### 1.1 `specs/001-contract-state-schema.md` (amend FIRST — Task 1)
Add to the documented clause-record sub-fields (the comment block under
`clauses` in §3, near `risk_level` / `risk_rationale`):
```
#   is_failsafe: Optional[bool]  # True if risk_level was assigned by the Node 5
#                                # fail-safe path (LLM failure/unparseable/circuit
#                                # open/empty-or-oversize text) rather than a genuine
#                                # model judgment. Written by RiskScoreAgent only.
```
Add a short revision-note paragraph (mirroring the existing §6 decision style)
recording the rationale (feature 038; §10) and that it is a purely additive,
simple per-clause field requiring no reducer change (it rides the existing
`merge_nested_clause_dicts` reducer on `clauses`). No top-level field is added.

### 1.2 `app/config.py`
Add two module-level constants (env-overridable, matching the existing
`_env_bool` / config style used by `PROMPT_INJECTION_DEFENSE_ENABLED`,
`CONTRACT_ENCRYPTION_AT_REST_ENABLED`, etc.):
- `HONEST_FAILURE_SURFACING_ENABLED: bool = True` — use the existing `_env_bool`
  helper in `config.py` (reuse verbatim; do not invent a new parsing pattern).
- `ANALYSIS_DEGRADED_FAILSAFE_FRACTION: float = 0.5` — there is **no** `_env_float`
  helper; define it as a plain float literal, matching existing float constants
  (e.g. `OCR_LOW_CONFIDENCE_THRESHOLD: float = 0.6`). Do not wrap it in `_env_bool`.

### 1.3 `app/graph/nodes/risk_score_agent.py`
Two write sites, gated on `HONEST_FAILURE_SURFACING_ENABLED` (imported from
`app.config`, read once into a local at function top like the other reversible
flags):
- **`_failsafe(reason)`** (currently returns `{"risk_level": default, "risk_rationale": "[auto] …"}`):
  when the flag is ON, also set `"is_failsafe": True`. When OFF, return exactly
  today's dict (no new key → byte-identical, AC-10). Since `_failsafe` is a
  module-level helper with no access to the flag, pass the flag in as a parameter
  (`_failsafe(reason, honest_enabled)`) OR read the config constant at module
  scope; **chosen approach: add a keyword param `mark_failsafe: bool = False`** so
  the helper stays pure and testable, and each of its call sites passes the
  flag-derived local. There are exactly **3** `_failsafe(...)` call sites in
  `risk_score_agent.py`: empty-text (~line 115), circuit-open bulk (~line 123),
  and LLM-None (~line 146). No fourth site exists.
- **Genuine-scoring branch** (the `else` where `result` is a real `(level, rationale)`):
  when the flag is ON, add `"is_failsafe": False` to that clause update. When OFF,
  do not add the key.
No change to `error_count` / circuit-breaker logic (AC-11: `error_count` still set
once on trip). The existing `[auto]` rationale marker is retained unchanged for
backward compatibility (spec D1 — it is no longer the source of truth but is not
removed).

### 1.4 `app/models/report.py`
- `ReportFinding`: add `is_failsafe: bool = False`.
- `ReportSummary`: add `failsafe_count: int = 0`.
- `ContractReport`: add `analysis_degraded: bool = False`.
All defaulted, so historical report JSONs (without these keys) still deserialize
unchanged (spec "feature flag off mid-existing-data" edge case).

### 1.5 `app/graph/nodes/renderers/report_assembler.py` (pure transform)
`assemble_report(state, generated_at, evidence_text_max_chars)` gains two params:
`honest_enabled: bool` and `degraded_fraction: float` (passed by the node; keeps
the function pure and config-free per its existing contract). Logic:
- Per finding: `is_failsafe = bool(record.get("is_failsafe"))` copied onto the
  `ReportFinding` (AC-5). Only meaningful when the flag was on at scoring time;
  absent key → `False`.
- `failsafe_count = sum(1 for f in findings if f.is_failsafe)` on `ReportSummary`
  (AC-4).
- `analysis_degraded` (AC-3 / D2), computed only when `honest_enabled` is True,
  else always `False` (AC-10):
  ```
  circuit_tripped = state.get("error_count", 0) >= 1
  frac = (failsafe_count / validated_findings) if validated_findings else 0.0
  analysis_degraded = (
      honest_enabled
      and failsafe_count >= 1
      and (circuit_tripped or frac >= degraded_fraction)
  )
  ```
  The `failsafe_count >= 1` gate is required: `error_count` is a **shared**
  accumulating counter incremented by any node's circuit breaker (ingest /
  self_rag / redline / risk_score), so without this gate an unrelated node's trip
  would falsely flag a genuine risk analysis (the banner would claim severities
  are auto-assigned when none are). A risk-score trip always yields fail-safe
  findings, so the gate loses no intended detection. Note the div-by-zero guard
  (validated_findings == 0 → frac 0.0). For the `ingest_error` minimal-report
  branch, leave `analysis_degraded=False` (spec edge case — ingest failure is
  surfaced separately).
- Log a structured line at assembly time with `failsafe_count`,
  `validated_findings`, `frac`, `circuit_tripped`, `analysis_degraded`, and the
  trigger reason (Evaluation section).

### 1.6 `app/graph/nodes/report_agent.py`
At the `assemble_report(...)` call site, pass
`honest_enabled=HONEST_FAILURE_SURFACING_ENABLED` and
`degraded_fraction=ANALYSIS_DEGRADED_FAILSAFE_FRACTION` (imported from
`app.config`). No other change.

### 1.7 `app/graph/nodes/renderers/markdown_renderer.py`
- When `report.analysis_degraded`, prepend a banner block **before the findings
  section** (a matchable marker line, e.g. starting `> ⚠ **Degraded analysis**`),
  with the plain-language text from spec Output 3 (AC-6). When False, no banner.
- For each finding with `is_failsafe`, append an inline "(auto-assigned)" marker
  next to its severity where the finding renders its risk level (AC-8). Keep the
  existing `**Upstream errors:**` footer as-is (it is orthogonal).

### 1.8 `app/delivery/report_pdf.py`
Same two surfaces in the reportlab renderer: a banner flowable at the top of the
story when `analysis_degraded`, and an "(auto-assigned)" tag on each fail-safe
finding's severity cell/paragraph (AC-7, AC-8). Match the existing styling
helpers already in the module.

### 1.9 `app/delivery/email_html.py`
Same two surfaces in the branded HTML email: a banner `<div>` at the top of the
body when `analysis_degraded`, and an inline tag per fail-safe finding (AC-7,
AC-8). Reuse existing inline-style constants in the module.

### 1.10 `app/api/aggregate.py` (history/dashboard badge integration point)
`read_report_data(report_path)` already parses the report JSON's `summary`. Extend
its `ReportData` dataclass with `analysis_degraded: bool` read from the top-level
report JSON (`data.get("analysis_degraded", False)`), and in `build_job_list`
copy it onto `JobListItem` (new field). This makes the degraded flag available to
the history list and dashboard without a second report read (D5/AC-9). The
dashboard aggregate (`build_dashboard_metrics`) does **not** change its risk math
in v1 — the badge is the honesty surface; excluding degraded reports from
portfolio math is out of scope (noted for a possible follow-up).
- Add `analysis_degraded: bool = False` to the `JobListItem` Pydantic model,
  which is defined in **`app/runner/models.py`** (imported into `aggregate.py`
  from `app.runner.models`) — NOT in `aggregate.py`. `build_job_list` (in
  `aggregate.py`) populates the field from `ReportData.analysis_degraded`.

## 2. Frontend changes (only after this plan is approved — constitution §1)

### 2.1 `frontend/src/lib/api/types.ts`
- `ReportFinding`: add `is_failsafe?: boolean` (default-absent → falsy).
- `ReportSummary`: add `failsafe_count?: number`.
- `ContractReport`: add `analysis_degraded?: boolean` (treat missing as `false`).
- `JobListItem`: add `analysis_degraded?: boolean | null`.

### 2.2 Report page
- `components/report/ReportView.tsx` (or `AnalysisWorkspace.tsx` — whichever owns
  the top of the report body): render a **degraded banner** component when
  `report.analysis_degraded` is truthy (AC-9). Add a small presentational
  component `components/report/DegradedBanner.tsx`.
- `components/report/FindingCard.tsx` / `FindingRiskBadge.tsx`: render an
  "(auto)" tag next to the severity when `finding.is_failsafe` (AC-8/AC-9).

### 2.3 History + dashboard badge
- `components/history/ReportHistoryView.tsx`: when a row's
  `analysis_degraded` is truthy, show a "Degraded" badge (reuse
  `components/ui/StatusBadge.tsx` or `RiskBadge.tsx` styling) and do not present
  its High/Medium/Low counts as trustworthy (e.g. mute them / append the badge).
- `components/dashboard/DashboardView.tsx` + `ReportsView.tsx`: show the same
  "Degraded" badge on cards/rows sourced from `JobListItem.analysis_degraded`.

### 2.4 Provider seam + fixtures
- `lib/api/realProvider.ts` / `mockProvider.ts` / `fixtures.ts` / `_fakeClient.ts`:
  ensure the new fields pass through; add a degraded fixture for tests. No API
  URL change (fields ride existing `getReport` / `getJobs` responses).

## 3. Tests (TDD — written and confirmed failing first, §7)

Backend (pytest):
- `risk_score_agent`: fail-safe update carries `is_failsafe: True` (empty-text,
  circuit-open, LLM-None paths) and genuine path carries `is_failsafe: False`
  when flag ON; neither key present when flag OFF (AC-1, AC-2, AC-10).
- `report_assembler`: `failsafe_count` correctness (AC-4); per-finding
  `is_failsafe` copy (AC-5); `analysis_degraded` truth table — circuit-tripped
  arm, fraction arm at/below/above threshold, zero-findings guard,
  `ingest_error` branch False (AC-3); flag-OFF forces all three defaults (AC-10).
- `report.py` model: defaults deserialize legacy JSON without new keys.
- `markdown_renderer`: banner present iff `analysis_degraded`; per-finding tag iff
  `is_failsafe` (AC-6, AC-8).
- `report_pdf` / `email_html`: banner + tag markers present iff degraded (AC-7,
  AC-8) — assert on generated text/markup.
- `aggregate`: `read_report_data` surfaces `analysis_degraded`; `build_job_list`
  puts it on `JobListItem` (AC-9 backend half).
- Reversibility integration: with `HONEST_FAILURE_SURFACING_ENABLED=False`, a run
  that would degrade produces state/report JSON byte-identical to pre-feature
  (AC-10) — assert no `is_failsafe` key, `analysis_degraded False`,
  `failsafe_count 0`, no banner marker.

Frontend (Vitest + RTL):
- Report renders `DegradedBanner` iff `analysis_degraded`; finding shows "(auto)"
  tag iff `is_failsafe`; missing fields → no banner/tag (AC-9, legacy-safe).
- History/dashboard rows show "Degraded" badge iff `JobListItem.analysis_degraded`.

## 4. Evaluation (measure-first, non-blocking)
Structured logs only (no CUT audit UI): per-run `failsafe_count/validated`,
circuit-open occurrence, `analysis_degraded` + trigger reason. After merge, on a
live Ollama run, deliberately induce degradation (stop Ollama mid-run) and
confirm the banner + badge appear end-to-end (real smoke, per project practice).
The `ANALYSIS_DEGRADED_FAILSAFE_FRACTION=0.5` default is tunable against these
logs without code-structure change (§3).

## 5. Risks / notes
- **Frozen-flag consistency:** `is_failsafe` is written at scoring time under the
  flag; `analysis_degraded` is derived at report time under the flag. If the flag
  is toggled between scoring and reporting of the *same* run (only possible via a
  mid-run restart with a config change — pathological), a run could have
  `is_failsafe` keys but `analysis_degraded=False`, or vice-versa. Acceptable:
  documented, and the OFF path never *fabricates* a degraded banner. No guard
  needed for v1.
- **PDF/email are post-terminal (delivery layer), not graph nodes** — editing
  them does not touch the graph (AC-11 safe).
- **Order:** Task 1 (001 amendment) must land before any code writes
  `is_failsafe` (§10).
