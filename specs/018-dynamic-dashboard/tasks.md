# Dynamic Dashboard — Implementation Tasks

Reference documents:
- Spec: `specs/018-dynamic-dashboard/spec.md`
- Plan: `specs/018-dynamic-dashboard/plan.md`
- Consumed contracts: 011 (`app/api/routes.py`), 012 (`app/runner/store.py`,
  `registry.py`), 009 (`app/models/report.py`), 001 (`original_filename`, `ClauseType`)
- Frontend foundation: 013 (`lib/api/*`, `components/charts/*`, `components/ui/*`), 017
  (`getReport`/`useReport` templates, `riskBand.ts`)
- Constitution: `specs/000-constitution.md`

Backend paths are relative to `backend/`, frontend to `frontend/`.

**Workflow reminders:**
- TDD per constitution §7 — write tests, confirm FAILING, then implement to PASS. Never
  weaken a test to force a pass.
- Reach the backend from the UI **only** through `getApiClient()` (013 seam); no page
  imports `realProvider`/`mockProvider` (AC-18).
- **No graph node/edge added.** The ONLY `backend/app/graph/` edit permitted is the one
  `ingest_agent.py` read-with-fallback line (Task 5); every other backend change is API /
  persistence / migration (AC-19).
- Boundary data is **Pydantic** (backend) mirrored **field-for-field** in `types.ts`
  (constitution §4). Never cross `ContractState` over the wire.
- Reality-grounded (spec D2–D14): NO fabricated score (derived health, D3); clause-type
  not contract-type (D4); real `clause_type × severity` heatmap (D5); real empty states
  (D11). No `"/100"`, `"78"`, `"339"`, `"80%"` literals survive.
- **NEVER run `next build` while `next dev` is running** (013/015 lesson). Stop dev first.
- Before any real run / smoke: `alembic upgrade head` (the new column, Task 3).

---

## Task 0: Start the feature branch

- [ ] Confirm `spec.md`, `plan.md`, `tasks.md` exist and are approved (§1/§11 gate).
- [ ] From an up-to-date `main`, create `feature/018-dynamic-dashboard` (`git-start`).

**Verify:** `git branch --show-current` → `feature/018-dynamic-dashboard`.

---

## Task 1: Config constants + boundary models (no tests of their own)

- [ ] **[MODIFY] `app/config.py`** — add (plan §3.1): `PORTFOLIO_HEALTH_MEDIUM_WEIGHT =
  0.5`, `PORTFOLIO_HEALTH_BAND_HEALTHY = 80`, `PORTFOLIO_HEALTH_BAND_ELEVATED = 50`,
  `USAGE_TIMELINE_DAYS = 30`, `JOBS_LIST_DEFAULT_LIMIT = 20`, `JOBS_LIST_MAX_LIMIT = 100`.
- [ ] **[MODIFY] `app/runner/models.py`** — add the Pydantic boundary models exactly per
  plan §3.2: `JobListItem`, `JobList`, `RiskDistribution`, `UsageBucket`,
  `ClauseTypeRisk`, `ClauseRiskHeatmap`, `TopClause`, `DashboardMetrics`. `JobListItem.status`
  is `JobState`. Do not disturb the existing `JobStatus`/`JobState`/`ErrorInfo`.

**Verify:** `python -c "import app.runner.models"` imports clean; `pytest tests/unit/test_config.py` still green.

---

## Task 2: Pure aggregation `app/api/aggregate.py` (tests first)

- [ ] **[NEW] `tests/unit/test_aggregate.py`** — confirm FAILING. All pure (inject a
  `read` stub returning `ReportData | None`; build `JobRow` lists directly — no disk):
  - `derive_band_four_cases`: `(high>0)→"high"`, `(0,med>0)→"medium"`,
    `(0,0,validated>0)→"low"`, `(0,0,0,0)→"none"` — **must match 017 TS `deriveRiskBand`**
    (review N2, guards Python/TS drift).
  - `health_formula`: `portfolio_health(high,medium,low)` = `round(100·(1 −
    (high+0.5·medium)/max(1,graded)))` + band via 80/50 cutoffs; all-low → high pct
    "healthy"; high-dominated → low pct "at_risk" (AC-5).
  - `health_zero_graded`: `(0,0,0)` → `pct=100` (max(1,·) guard, AC-9, no div-by-zero).
  - `risk_distribution_sum`: sums high/med/low across completed reports (AC-4/D8).
  - `by_clause_type_and_heatmap`: groups by `clause_type`; `null` → "Uncategorized"
    (D14); heatmap `rows` = types present, `cols=[low,medium,high]`, `cells[r][c]`
    counts (AC-6).
  - `top_risky`: ≤5 clause types by high count, descending (AC-7).
  - `usage_dense_30`: day-buckets, **all `USAGE_TIMELINE_DAYS` days zero-filled**, counts
    match seeded `submitted_at` days (AC-8/N5); empty rows → 30 zero buckets.
  - `missing_report_skipped`: a completed row whose `read` returns `None` is counted in
    `total_contracts` but contributes no risk (AC-10/EC-3); `report_available=False`.
  - `failed_job_in_totals_not_risk`: failed/no-report rows count in totals, not risk
    (EC-2).
- [ ] **[NEW] `app/api/aggregate.py`** — implement per plan §3.4: `ReportData` dataclass,
  `read_report_data(report_path)` (resolve `.json` sibling of `report_path` like
  `routes.py` report handler; return `None` on missing/absent/malformed, logged —
  EC-3/EC-10), `derive_band`, `portfolio_health`, `build_job_list(rows, read, limit,
  offset, total)`, `build_dashboard_metrics(rows, read, *, today)`. `build_*` are pure
  (take `rows` + injected `read`).

**Verify:** `pytest tests/unit/test_aggregate.py` → PASS.

---

## Task 3: Migration + `store.py` (tests first)

- [ ] **[NEW] `alembic/versions/0002_add_original_filename.py`** — `revision="0002"`,
  `down_revision="0001"`; `upgrade` = `op.add_column("jobs", sa.Column(
  "original_filename", sa.Text, nullable=True))`; `downgrade` = `op.drop_column(...)`.
- [ ] **[NEW] `tests/unit/test_store_list.py`** — confirm FAILING (use a temp DB with
  `alembic upgrade head`, or the test harness's store fixture):
  - `original_filename_roundtrip`: upsert a `JobRow(original_filename="heavy.docx")`,
    `get` → equals `"heavy.docx"` (AC-11).
  - `legacy_null_filename`: a row inserted without the column set decodes with
    `original_filename=None` (AC-12/EC-7).
  - `list_pagination`: `list(limit=2, offset=2)` returns the 3rd–4th newest by
    `submitted_at DESC`; `count()` = total; `all()` returns every row (AC-1).
- [ ] **[MODIFY] `app/runner/store.py`** — add `original_filename: Optional[str]` to
  `JobRow` **LAST (after `error`)**. **Alignment rule (plan §3.3 / review B1):** append it
  LAST and identically in ALL of — (1) `JobRow` fields, (2) the `_encode` return tuple,
  (3) the INSERT column list + `VALUES` placeholders + the `ON CONFLICT DO UPDATE SET`,
  (4) `_decode`'s `JobRow(...)` kwargs. The INSERT column count MUST equal the `_encode`
  tuple length (a mismatch is a silent runtime `sqlite3` error). Add `list(limit, offset)`
  (`SELECT * FROM jobs ORDER BY submitted_at DESC LIMIT ? OFFSET ?`), `count()`
  (`SELECT COUNT(*)`), `all()` (`SELECT * ORDER BY submitted_at DESC`), each lock-guarded.

**Verify:** `pytest tests/unit/test_store_list.py` → PASS; existing `test_job_store.py` still green.

---

## Task 4: `registry.py` (JobRecord field + row round-trip + list/count/all)

- [ ] **[NEW] test in `tests/unit/test_store_list.py` (or `test_registry_*.py`)** — confirm
  FAILING: `record_row_roundtrip`: a `JobRecord(..., original_filename="x")` →
  `_to_row()` → `store.upsert` → `store.get` → `JobRecord.from_row` has
  `original_filename == "x"` (review B2 — proves `_to_row` doesn't drop it).
- [ ] **[MODIFY] `app/runner/registry.py`** —
  - `JobRecord`: add `original_filename: Optional[str] = None` **immediately after
    `recipient`** (last defaulted init field) and **before** the `field(init=False)` block,
    with default `None` (review B3 — avoids "non-default follows default").
  - `_to_row()`: pass `original_filename=self.original_filename`.
  - `from_row()`: set `original_filename=row.original_filename`.
  - Add `JobRegistry.list_jobs(limit, offset)`, `count()`, `all_rows()` delegating to the
    store (durable reads).

**Verify:** `pytest tests/unit/test_store_list.py tests/unit/test_registry*.py` → PASS.

---

## Task 5: `original_filename` seeding (core → worker → ingest → analyze)

- [ ] **[NEW] test** (extend an ingest unit test): with `state={"document_path": ".../abc.docx",
  "original_filename": "Real Contract.docx"}`, `ingest_agent` sets
  `original_filename == "Real Contract.docx"`; with the key absent it falls back to
  `Path(document_path).name`. Confirm FAILING.
- [ ] **[MODIFY] `app/graph/nodes/ingest_agent.py`** (line ~60, the ONE permitted graph
  edit): `original_filename = state.get("original_filename") or Path(document_path).name`.
- [ ] **[MODIFY] `app/runner/core.py`** — `run_pipeline(..., original_filename:
  Optional[str] = None)`; in the non-resume branch add
  `stream_input["original_filename"] = original_filename` **only when not None** (keeps the
  012 resume path and the default byte-identical).
- [ ] **[MODIFY] `app/runner/worker.py`** — `_run_one` passes
  `original_filename=rec.original_filename` into `run_pipeline`.
- [ ] **[MODIFY] `app/api/routes.py` `analyze`** — compute `original_filename =
  file.filename or f"{job_id}{ext}"`; pass `original_filename=original_filename` into
  `JobRecord(...)`.

**Verify:** the ingest test PASS; `pytest tests/` for the runner/graph packages still green.

---

## Task 6: Endpoints + integration tests

- [ ] **[NEW] `tests/integration/test_dashboard_endpoints.py`** — confirm FAILING
  (FastAPI `TestClient`; seed the store + write matching report `.json` fixtures under a
  temp `REPORT_OUTPUT_DIR`):
  - `list_jobs_shape_and_pagination`: `GET /api/jobs` → `{items,total}` newest-first;
    `limit`/`offset` page; completed items carry `risk_band`+counts, non-completed have
    them `null` (AC-1/AC-2).
  - `list_empty`: empty store → `{items:[], total:0}` (AC-3).
  - `list_limit_clamped`: `limit=9999` clamped to `JOBS_LIST_MAX_LIMIT`; negative offset
    → 0 (EC-6).
  - `dashboard_aggregates`: `GET /api/dashboard` totals, `risk_distribution`, health
    pct/band, `risk_by_clause_type`, heatmap, top clauses, dense usage (AC-4..8).
  - `dashboard_empty`: empty store → zeros, `pct=100`, empty lists, 30 zero usage buckets
    (AC-9).
  - `dashboard_missing_report`: completed job with no `.json` on disk → skipped in risk,
    counted in totals (AC-10).
  - `analyze_persists_real_filename`: `POST /api/analyze` with a file named
    `heavy_contract.docx` → that name appears in `GET /api/jobs` (AC-11).
  - `jobs_routes_coexist`: `GET /api/jobs` and `GET /api/jobs/{id}` both resolve (no
    shadowing).
- [ ] **[MODIFY] `app/api/routes.py`** — add `GET /api/jobs` (limit/offset, clamped per
  plan §3.5) → `build_job_list(reg.list_jobs(...), read_report_data, limit, offset,
  reg.count())`; add `GET /api/dashboard` → `build_dashboard_metrics(reg.all_rows(),
  read_report_data, today=_utc_today())`. Add a small `_utc_today()` helper.

**Verify:** `pytest tests/integration/test_dashboard_endpoints.py` → PASS. Then run the
**whole backend suite** (`pytest`) — confirm 011/012 tests still green (JobRecord/JobRow
gained a defaulted field; `run_pipeline` gained a defaulted kwarg — all additive).

---

## Task 7: Frontend seam (types + client + providers + fixtures + drift lock)

- [ ] **[MODIFY] `src/lib/api/types.ts`** — mirror field-for-field: `JobListItem`,
  `JobList`, `RiskDistribution`, `UsageBucket`, `ClauseTypeRisk`, `ClauseRiskHeatmap`,
  `TopClause`, `DashboardMetrics` (plan §3.2 shapes).
- [ ] **[MODIFY] `src/lib/api/client.ts`** — add `getJobs(params?: { limit?: number;
  offset?: number }): Promise<JobList>` and `getDashboardMetrics(): Promise<DashboardMetrics>`
  to `ApiClient`.
- [ ] **[MODIFY] `src/lib/api/realProvider.ts`** — implement both via `fetch` +
  `asJson`/`ApiError` (getReport is the template): `getJobs` → `/api/jobs?limit&offset`,
  `getDashboardMetrics` → `/api/dashboard`.
- [ ] **[MODIFY] `src/lib/api/fixtures.ts`** — add `dashboardMetricsFixture` (mixed
  severities, ≥2 clause types incl. an "Uncategorized" bucket, non-empty heatmap, several
  usage buckets), `jobListFixture` (completed + running + failed items),
  `emptyDashboardFixture` (all-zero, 30 zero usage buckets), `emptyJobListFixture`
  (`items:[], total:0`).
- [ ] **[MODIFY] `src/lib/api/mockProvider.ts`** — `getJobs` → `jobListFixture`,
  `getDashboardMetrics` → `dashboardMetricsFixture`.
- [ ] **[NEW] `src/__tests__/dashboardMetrics-fields.test.ts`** — confirm FAILING then
  GREEN: assert the fixtures carry every field of the boundary models (explicit field
  lists, 017 AC-15a style) so a backend add/remove fails the test (AC-18).
- [ ] **[MODIFY] `src/__tests__/_fakeClient.ts`** — add `getJobs`/`getDashboardMetrics`
  (return fixtures or scripted `getDashboardError`/`getJobsError` for hook error tests),
  so the client stays a complete `ApiClient`.

**Verify:** `npx vitest run src/__tests__/dashboardMetrics-fields.test.ts` → PASS; `npx tsc --noEmit` clean.

---

## Task 8: `BarChart` stacked mode (tests first)

- [ ] **[NEW] `src/__tests__/barchart-stacked.test.tsx`** — confirm FAILING:
  - `stacked_renders_series`: with `stack=[{key:"low"…},{medium},{high}]` and data rows,
    renders one bar series per stack entry (assert 3 `<Bar>`/rects present, not the default
    `value` bar).
  - `empty_data_no_data`: `data=[]` → the existing "No data" node.
  - `legacy_value_series_unchanged`: `data=[{name,value}]` with no `stack` still renders
    the single value bar (backward compat).
- [ ] **[MODIFY] `src/components/charts/BarChart.tsx`** — add optional `stack?:
  StackSeries[]` (plan §4.3): when set, render one `<Bar stackId="a" dataKey={s.key}
  fill={riskColor(s.level)}>` per entry and **skip** the default `value`/`secondary` bars;
  when unset, behavior is unchanged.

**Verify:** `npx vitest run src/__tests__/barchart-stacked.test.tsx` → PASS; existing dashboard/reports still compile.

---

## Task 9: Hooks + views + page wiring (tests first)

- [ ] **[NEW] `src/lib/useDashboard.ts`, `src/lib/useJobs.ts`** — `"use client"`;
  discriminated-state hooks returning `{ state: { phase, data, message }, retry }` with
  `phase: "loading"|"loaded"|"empty"|"error"`; `empty` when `total_contracts === 0` /
  `total === 0` (plan §4.2). Backend only via `getApiClient()`.
- [ ] **[NEW] `src/__tests__/useDashboard.test.tsx`** — confirm FAILING: loading→loaded;
  `empty` on `emptyDashboardFixture`; `error`+`retry` on a thrown `ApiError`.
- [ ] **[NEW] `src/components/dashboard/DashboardView.tsx`** — `"use client"` per plan
  §4.4: `useDashboard()`+`useJobs()`; loading/empty("No contracts analyzed yet" + link
  `/upload`)/error(retry); Risk Summary donut from `risk_distribution` + derived
  `portfolio_health_pct` (NO `ScorePill value={78}`/`"78"`/`"/100"`); Activity Feed from
  jobs (filename, status/risk badge, `finished_at ?? submitted_at`, completed row →
  `/jobs/{id}/report`); Usage bar from `usage_timeline`. Notifications/greeting static.
- [ ] **[NEW] `src/components/dashboard/ReportsView.tsx`** — `"use client"` per plan §4.5:
  `useDashboard()`; stacked BarChart (risk_by_clause_type), Heatmap (+ left-column labels
  from `rows`), usage area, distribution donut, top clauses, `completed_contracts` stat,
  `GaugeChart value={portfolio_health_pct}` — NO `"/100"`/`"80%"`/`"339"` literals.
- [ ] **[MODIFY] `src/app/dashboard/page.tsx`** — server shell: `TopBar` + `<DashboardView/>`;
  delete `RISK_SLICES`/`ACTIVITY`/`USAGE` consts.
- [ ] **[MODIFY] `src/app/reports/page.tsx`** — server shell: `TopBar` + `<ReportsView/>`;
  delete `RISK_BY_TYPE`/`USAGE`/`DISTRIBUTION`/`HEATMAP`/`HEAT_*`/`TOP_CLAUSES` consts.
- [ ] **[NEW] `src/__tests__/dashboard.test.tsx`** (AC-13/15/16/17): renders donut/feed/usage
  from fixtures; no hardcoded consts / no `ScorePill`/`"78"`/`"/100"`; empty state; error
  state; completed feed row links `/jobs/{id}/report`; uses `getApiClient()` only.
- [ ] **[NEW] `src/__tests__/reports.test.tsx`** (AC-14/15/16): stacked bar + heatmap +
  gauge from metrics; headline = `completed_contracts`; no
  `RISK_BY_TYPE`/`HEATMAP`/`"339"`/`"80%"`/`"/100"`; empty + error states.
- [ ] **[NEW] `src/__tests__/dashboard-boundary.test.ts`**: no `realProvider`/`mockProvider`
  import under `components/dashboard` (AC-18).

**Verify:** `npx vitest run src/__tests__/useDashboard.test.tsx src/__tests__/dashboard.test.tsx src/__tests__/reports.test.tsx` → PASS.

---

## Task 10: Full verification pass

- [ ] Backend: `pytest` (entire suite) GREEN — 011/012/017 + new 018 tests.
- [ ] Frontend: `npx vitest run` GREEN; `npx tsc --noEmit` clean; `npm run lint` clean.
- [ ] **Stop the dev server**, then `npx next build` — succeeds; `/dashboard` + `/reports`
  build.
- [ ] `git diff --name-only` — confirm **no** `backend/app/graph/` file other than
  `ingest_agent.py` changed (AC-19); no `ContractState` field added.

**Verify:** all green; only `ingest_agent.py` touched under `graph/`.

---

## Task 11: Live end-to-end smoke (AC-20)

- [ ] Stop dev. `alembic upgrade head` (applies `0002`). Start `uvicorn app.api.main:app
  --host 127.0.0.1 --port 8000` + Ollama.
- [ ] `frontend/.env.local`: `NEXT_PUBLIC_API_PROVIDER=real`, empty `NEXT_PUBLIC_API_BASE_URL`.
- [ ] `npm run dev`. On a **fresh store**, confirm `/dashboard` + `/reports` show the empty
  state (not demo numbers). Then analyze **≥2 real contracts** via `/upload`; confirm both
  pages show real totals, a risk distribution matching the reports, real **filenames** in
  the Activity Feed, and a completed row links to its `/jobs/{id}/report`.
- [ ] Reset `.env.local` provider to `mock`. Report the outcome (real-smoke-before-continuation).

**Verify:** real aggregates + real names render; fresh store shows the empty state.

---

## Task 12: Finish the feature branch

- [ ] Full backend + frontend suites, `tsc`, `next build` green (Task 10); smoke noted
  (Task 11).
- [ ] Rebase latest `main` into the branch, resolve conflicts on the branch (§11), merge to
  `main`, delete the branch (`git-finish`).

**Verify:** on `main`; `feature/018-dynamic-dashboard` gone; suites + build green on `main`.

---

*Per constitution §1/§11, implementation happens only on `feature/018-dynamic-dashboard`,
opened after spec + plan + tasks are approved. Deferred elsewhere: 017b contracts-history
table, settings page, the persisted risk-summary optimization (spec §5), backend pipeline
speedup.*
