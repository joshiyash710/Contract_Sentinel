# Feature 066 — Technical plan: denormalize the risk summary onto the job row

Branch: `feature/066-dashboard-summary-denormalize` (per constitution §11).

Derived from the approved `spec.md`. Kill the `/api/dashboard` + `/api/jobs` N+1 (one report-BLOB read per
completed job) by persisting a **compact risk summary on the `jobs` row at completion**; both endpoints then
build from the single `SELECT * FROM jobs` they already run, with legacy rows falling back to today's
BLOB-read path. **Store DB + aggregation only. No LangGraph node/edge/`ContractState` change.** Response JSON
unchanged (no frontend change). No new dependency.

## 0. Scope of change (files touched)
```
backend/alembic/versions/0011_job_risk_summary.py   (NEW — add nullable risk-summary columns to `jobs`)
backend/app/runner/risk_summary.py                  (NEW — RiskSummary + summarize_report + load_report_summary; neutral, runner-level)
backend/app/runner/store.py                         (JobRow fields + upsert INSERT/ON CONFLICT + row→JobRow read)
backend/app/runner/registry.py                      (mark_terminal gains risk_summary; _to_row serializes it)
backend/app/runner/worker.py                         (compute load_report_summary at completion, best-effort; pass to mark_terminal)
backend/app/api/aggregate.py                         (dashboard/job-list build from the row summary; fall back for legacy)
backend/tests/...                                    (migration, store round-trip, write-at-completion, read-from-row, legacy fallback, parity)
specs/066-dashboard-summary-denormalize/{spec,plan,tasks}.md
```
**NOT touched:** any LangGraph node/graph/`builder.py`/`ContractState`/`specs/001`; the response models
(`DashboardMetrics`/`JobList*` shapes unchanged); the frontend; `blob_store.py`; the report renderers;
`pyproject.toml`.

## 1. Migration — `alembic/versions/0011_job_risk_summary.py` (AC-1)
- `revision="0011"`, `down_revision="0010"`. Mirror 0010's additive/reversible style.
- `upgrade()`: `op.add_column("jobs", sa.Column(<name>, <type>, nullable=True))` for:
  `risk_high` INTEGER, `risk_medium` INTEGER, `risk_low` INTEGER, `validated_findings` INTEGER,
  `total_clauses` INTEGER, `analysis_degraded` INTEGER (0/1), `risk_by_type` TEXT (JSON). All **nullable**
  (legacy rows NULL ⇒ fallback).
- `downgrade()`: `op.drop_column("jobs", <name>)` for each.

## 2. `app/runner/risk_summary.py` (NEW — neutral, importable by runner AND api; AC-3, AC-7)
- `@dataclass RiskSummary`: `high:int, medium:int, low:int, validated_findings:int, total_clauses:int,
  analysis_degraded:bool, risk_by_type:dict` (per-clause-type `{type: {"high","medium","low"}}` for THIS one
  report).
- `summarize_report(report: dict) -> RiskSummary` — **pure**, from an already-parsed report `.json`
  (`summary` + `findings` + `analysis_degraded`), building `risk_by_type` the SAME way
  `build_dashboard_metrics` does today (same clause-type labels incl. the uncategorized bucket, same severity
  keys). This is the single source feeding BOTH the stored summary and (for parity) the fallback path (D4/AC-7).
- `load_report_summary(report_path) -> Optional[RiskSummary]` — **best-effort**: resolve the `.json` key
  (`Path(report_path).with_suffix(".json")`), `blob_store.exists` + `blob_store.read`, `json.loads`,
  `summarize_report`. Returns `None` on unset/missing/malformed (logged, never raised) — used by the WRITE
  path (one read per analysis, at completion). (Mirrors `read_report_data`'s tolerance; neutral module so the
  runner does not import `app.api.*` and the api does not duplicate extraction — no layering violation, no
  graph-node import so the 061 runner-isolation guard holds.)
- JSON helpers: `to_row_fields(summary) -> dict` (summary → the 7 column values, `risk_by_type` as a JSON
  string) and `from_row(row) -> Optional[RiskSummary]` (the 7 columns → RiskSummary, or None when `risk_high`
  is NULL / `risk_by_type` unparseable → EC-7 fallback).

## 3. `store.py` — JobRow + upsert + read (AC-2)
- `JobRow` gains optional fields: `risk_high/risk_medium/risk_low/validated_findings/total_clauses:
  Optional[int] = None`, `analysis_degraded: Optional[bool] = None`, `risk_by_type: Optional[dict] = None`.
- `upsert`: add the 7 columns to the `INSERT INTO jobs (…)` list + `VALUES` + the `ON CONFLICT … DO UPDATE SET`
  clause (serialize `risk_by_type` via `json.dumps`, store `analysis_degraded` as 0/1; NULLs when the summary
  is absent).
- Row→JobRow read (store.py:180): populate the new fields using the **backward-compat guard**
  `r["risk_high"] if "risk_high" in r.keys() else None` (mirrors the existing `original_filename`/`user_id`
  pattern), and `json.loads(r["risk_by_type"])` when present/non-null (defensive — malformed → None).

## 4. `registry.py` — thread the summary through mark_terminal (AC-3)
- `mark_terminal(…, risk_summary: Optional[RiskSummary] = None)`: store it on the record
  (`self._risk_summary = risk_summary`) before `_persist()`. Default `None` ⇒ unchanged callers (the failure
  path, 063/054 logic) store no summary.
- `_to_row()`: map `self._risk_summary` → the new JobRow fields (via `risk_summary.to_row_fields` or directly);
  `None` ⇒ all NULL.
- No new import of graph-node modules (guard preserved); `risk_summary` is a runner-level dataclass.

## 5. `worker.py` — compute at completion, best-effort (AC-3, EC-3)
- In the **completed** branch (where `rec.mark_terminal(status=completed, report_path=result.report_path, …)`
  is called), compute the summary first, guarded so it can NEVER alter the terminal outcome (mirrors 061's
  best-effort KB write):
  ```python
  summary = None
  try:
      if result.report_path:
          summary = load_report_summary(result.report_path)
  except Exception:
      logger.warning("risk-summary computation failed (best-effort)", exc_info=True)
  rec.mark_terminal(status=JobState.completed, finished_at=_now_iso(), report_path=result.report_path,
                    mcp_delivery_status=result.mcp_delivery_status, error=error, risk_summary=summary)
  ```
- The `failed`/error terminal branch passes no `risk_summary` (stays NULL) — AC-3 second case.

## 6. `aggregate.py` — read from the row, fall back for legacy (AC-4, AC-5, AC-6)
- Refactor the two builders to obtain a `RiskSummary` **per completed row** and fold uniformly:
  - `row_summary = risk_summary.from_row(row)` → if not None, use it (NO BLOB read).
  - else (legacy) → `rd = read(row.report_path)`; if not None, `summarize` its fields into a `RiskSummary`
    (reuse `summarize_report` on the raw report dict, or adapt `read_report_data`'s `ReportData` → RiskSummary)
    so the fold is uniform.
- `build_dashboard_metrics`: fold `high/medium/low`, `validated`, `total`, and merge each row's
  `risk_by_type` into the aggregate heatmap/top-risky — identical numbers to today, just sourced per-row.
  The injected `read` is invoked **only** for legacy rows (AC-4 asserts zero calls when all rows are
  summarized).
- `build_job_list`: for a completed row, set `report_available`, `high/medium/low`, `risk_band`
  (`derive_band`), `analysis_degraded` from `from_row(row)` when present, else the legacy `read()` path.
- Response models unchanged → identical JSON (AC-8).

## 7. Tests (TDD — write first, confirm failing, then implement)
- **Migration (AC-1):** `test_migration_0011` — upgrade adds the 7 nullable columns (pre-existing rows survive,
  new cols NULL); downgrade drops them. (Mirror an existing migration test; run against local SQLite.)
- **Store round-trip (AC-2):** a `JobRow` with a summary upserts + reads back intact (ints + decoded
  `risk_by_type`); a `JobRow` without a summary stores NULLs and reads back as None.
- **Write-at-completion — TWO cases (AC-3, reviewer note 1):** (a) completed + report → `mark_terminal` stamps
  the summary derived from the report; (b) failed / report-less terminal → no summary (NULLs). **Best-effort
  (EC-3):** a `load_report_summary` that raises does NOT change the terminal status (the job is still
  `completed`, summary NULL).
- **Dashboard reads from row (AC-4):** `build_dashboard_metrics` over all-summarized rows == the BLOB-path
  result, with the injected reader asserted called **0** times.
- **Job list reads from row (AC-5):** same for `build_job_list`.
- **Legacy fallback + mixed batch (AC-6):** a summarized row + a legacy (NULL-summary) row → correct output;
  reader called **only** for the legacy row.
- **Parity (AC-7):** `summarize_report(report_json)` == the dashboard-relevant fields of
  `read_report_data(report_path)` for the same report.
- Run `python -X utf8 -m pytest -q` → confirm the new tests FAIL first, then implement to green.

## 8. Correctness / constitution
- **§2/§10:** no node/edge/`ContractState`/`specs/001` change; store-DB migration only (Alembic-managed per
  051, like 0009/0010). `builder.py` untouched.
- **§019:** per-job summary, owner-scoped reads unchanged; no cross-account exposure.
- **Honesty (D4/AC-7):** stored summary == what reading the report yields (one shared `summarize_report`); the
  dashboard numbers are identical, just sourced from the row.
- **Best-effort write (EC-3):** summary computation never alters the job's terminal status (mirrors 061).
- **No new dependency; no frontend change; response JSON unchanged** (AC-8).

## 9. Verification gate (offline) + rollout
- `python -X utf8 -m pytest -q` → new tests pass AND the full suite stays green (store / registry / worker /
  dashboard / migration tests unchanged except where they assert the new behavior).
- `git diff --name-only main` == the §0 allow-list.
- **Live effect (AC-9, post-deploy):** the entrypoint runs `alembic upgrade head` (adds the columns on Turso);
  new analyses store the summary; `/api/dashboard` + `/api/jobs` load sub-second (one `SELECT`, no per-report
  round-trips). Legacy rows stay correct via fallback and speed up as users re-run. No flag needed.

## 10. Risks / limitations
- **Legacy rows stay slow until re-run** (D3 fallback) — acceptable; no mandatory backfill. An optional
  backfill chore is out of scope.
- **`risk_by_type` must match the live heatmap labels** — guaranteed by using the SAME `summarize_report`
  logic the dashboard folding uses (AC-7 parity test guards drift).
- **Embedded replica (064/065) is abandoned** (spec §5): its flag stays OFF; this feature is the correct
  latency fix. 064/065 code remains default-off (marked experimental in docs/memory).

## 11. Merge
Full backend gate green; diff scope matches §0. Rebase `main`, merge
`feature/066-dashboard-summary-denormalize`, delete branch (`git-finish`). Auto-deploys; the migration runs on
boot; dashboard/jobs become fast with no flag + no frontend change.
