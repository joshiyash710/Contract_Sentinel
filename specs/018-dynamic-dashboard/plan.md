# Dynamic Dashboard — Technical Plan

## Git Branch

`feature/018-dynamic-dashboard` — branching workflow per `specs/000-constitution.md` §11.

---

## 1. Overview

This plan implements `specs/018-dynamic-dashboard/spec.md`: make `/dashboard`
(Command Center) and `/reports` (Risk Dashboard) render **real** portfolio data
instead of feature-013 hardcoded demo constants. It has three parts:

1. **Backend read-only aggregation** — two new endpoints (`GET /api/jobs`,
   `GET /api/dashboard`) that read the 012 `JobStore` (list/timeline/totals) and the
   009 report JSONs on demand (risk aggregates, D1). No graph node/edge added.
2. **`original_filename` correctness fix (D2)** — capture the real upload filename,
   persist it (Alembic `0002`), seed it into the runner's initial state, and have
   `ingest_agent` prefer the seeded value. This is the **only** `graph/nodes/` edit
   (no node/edge added — constitution §2 structure intact, AC-19).
3. **Frontend wiring** — a `getJobs()` / `getDashboardMetrics()` seam, two client
   view components fed by hooks (loading/empty/error), and a backward-compatible
   **stacked multi-series** mode on the shared `BarChart` (D4, review B-1).

All aggregation is **grounded** (spec D3–D14): no fabricated score (derived health,
D3), clause-type not contract-type (D4), real `clause_type × severity` heatmap (D5),
real empty states (D11). Reaches the backend only through `getApiClient()` (013 seam).

---

## 2. Files to Create / Modify

### Backend (`backend/`)

```
alembic/versions/0002_add_original_filename.py   [NEW] add nullable jobs.original_filename (down_revision "0001")
app/config.py                                    [MODIFY] + tunable constants (D3/D7 §3-style)
app/runner/models.py                             [MODIFY] + JobListItem, JobList, DashboardMetrics (+ sub-models)
app/runner/store.py                              [MODIFY] JobRow +original_filename; encode/decode; + list(limit,offset), count(), all()
app/runner/registry.py                           [MODIFY] JobRecord +original_filename; _to_row/from_row; + list_jobs/count/all_rows pass-throughs
app/runner/core.py                               [MODIFY] run_pipeline(original_filename=…) → seed stream_input
app/runner/worker.py                             [MODIFY] pass rec.original_filename into run_pipeline
app/graph/nodes/ingest_agent.py                  [MODIFY — the one permitted graph edit] prefer state.get("original_filename")
app/api/aggregate.py                             [NEW] PURE aggregation (build_job_list, build_dashboard_metrics, health/band helpers)
app/api/routes.py                                [MODIFY] analyze captures file.filename; + GET /api/jobs, GET /api/dashboard
tests/unit/test_aggregate.py                     [NEW] pure-function tests (health, band, buckets, empty, nulls)
tests/unit/test_store_list.py                    [NEW] list/count/all + original_filename round-trip + migration
tests/integration/test_dashboard_endpoints.py    [NEW] GET /api/jobs, GET /api/dashboard, analyze filename (TestClient)
```

### Frontend (`frontend/`)

```
src/lib/api/types.ts                 [MODIFY] + JobListItem/JobList/DashboardMetrics mirrors (+ sub-shapes)
src/lib/api/client.ts                [MODIFY] + getJobs(params)/getDashboardMetrics() on ApiClient
src/lib/api/realProvider.ts          [MODIFY] + both methods (fetch + ApiError wrap)
src/lib/api/mockProvider.ts          [MODIFY] + both methods (from fixtures)
src/lib/api/fixtures.ts              [MODIFY] + dashboardMetricsFixture, jobListFixture, emptyDashboardFixture, emptyJobListFixture
src/lib/useDashboard.ts              [NEW] hook: getDashboardMetrics → {phase,data,retry}
src/lib/useJobs.ts                   [NEW] hook: getJobs → {phase,data,retry}
src/components/charts/BarChart.tsx   [MODIFY] + optional stacked multi-series (low/medium/high) mode — backward compatible
src/components/dashboard/DashboardView.tsx  [NEW] "use client" — Command Center body (hooks + states)
src/components/dashboard/ReportsView.tsx    [NEW] "use client" — Risk Dashboard body (hooks + states)
src/app/dashboard/page.tsx           [MODIFY] server shell → <DashboardView/> (drop hardcoded consts)
src/app/reports/page.tsx             [MODIFY] server shell → <ReportsView/> (drop hardcoded consts)
src/__tests__/dashboardMetrics-fields.test.ts [NEW] TS↔Pydantic drift lock (mirrors 017 AC-15a)
src/__tests__/barchart-stacked.test.tsx        [NEW] stacked mode renders N series + empty state
src/__tests__/useDashboard.test.tsx            [NEW] loading/loaded/empty/error/retry
src/__tests__/dashboard.test.tsx               [NEW] DashboardView AC-13/15/16/17
src/__tests__/reports.test.tsx                 [NEW] ReportsView AC-14/15/16 (+ no "/100")
```

No file under `backend/app/graph/` other than `ingest_agent.py` is touched (AC-19).

---

## 3. Backend design

### 3.1 Config constants (`app/config.py`, D3/D7 — constitution §3)

```python
# 018 dashboard (tunable — never hardcode in aggregation logic, §3)
PORTFOLIO_HEALTH_MEDIUM_WEIGHT: float = 0.5     # D3
PORTFOLIO_HEALTH_BAND_HEALTHY: int = 80         # >=  → "healthy"
PORTFOLIO_HEALTH_BAND_ELEVATED: int = 50        # >=  → "elevated"; else "at_risk"
USAGE_TIMELINE_DAYS: int = 30                   # D7 window
JOBS_LIST_DEFAULT_LIMIT: int = 20
JOBS_LIST_MAX_LIMIT: int = 100
```

### 3.2 Boundary models (`app/runner/models.py`, Pydantic — §4)

```python
class JobListItem(BaseModel):
    job_id: str
    original_filename: str
    status: JobState
    submitted_at: str
    finished_at: Optional[str] = None
    report_available: bool = False
    risk_band: Optional[str] = None            # "high"|"medium"|"low"|"none" (completed only)
    high: Optional[int] = None
    medium: Optional[int] = None
    low: Optional[int] = None

class JobList(BaseModel):
    items: List[JobListItem]
    total: int

class RiskDistribution(BaseModel):
    high: int = 0; medium: int = 0; low: int = 0

class UsageBucket(BaseModel):
    period: str        # "YYYY-MM-DD"
    count: int

class ClauseTypeRisk(BaseModel):
    clause_type: str   # ClauseType.value or "Uncategorized" (D14)
    high: int = 0; medium: int = 0; low: int = 0

class ClauseRiskHeatmap(BaseModel):
    rows: List[str]                 # clause_type labels
    cols: List[str] = ["low", "medium", "high"]
    cells: List[List[int]]          # cells[r][c]

class TopClause(BaseModel):
    clause_type: str
    high_count: int

class DashboardMetrics(BaseModel):
    total_contracts: int
    completed_contracts: int
    risk_distribution: RiskDistribution
    portfolio_health_pct: int
    portfolio_health_band: str      # "healthy"|"elevated"|"at_risk"
    usage_timeline: List[UsageBucket]
    risk_by_clause_type: List[ClauseTypeRisk]
    clause_risk_heatmap: ClauseRiskHeatmap
    top_risky_clause_types: List[TopClause]
```

### 3.3 `original_filename` persistence (D2)

- **Migration `0002_add_original_filename.py`**: `op.add_column("jobs",
  sa.Column("original_filename", sa.Text, nullable=True))`; `downgrade` drops it.
  `down_revision = "0001"`.
- **`store.py`**: add `original_filename: Optional[str]` to `JobRow`. **Field-alignment
  rule (review B1 — the top runtime-bug risk).** `JobRow` is a `@dataclass` with no
  defaults and `_encode()` returns a *positional* tuple that must match the INSERT
  placeholders exactly. Append `original_filename` **LAST** in all four places, in the
  same order: (1) the `JobRow` field list (after `error`), (2) the `_encode` return tuple
  (after `error_json`), (3) the `INSERT … (…)` column list **and** its `VALUES (?,…?)`
  placeholders **and** the `ON CONFLICT DO UPDATE SET` clause, (4) the `_decode`
  `JobRow(...)` kwargs (kwarg, order-independent, but include it). A mismatch between the
  INSERT column count and the `_encode` tuple length is a silent `sqlite3` runtime error,
  not a type error — so tasks.md pins this exactly. Add `list(limit, offset) ->
  List[JobRow]` (`SELECT … ORDER BY submitted_at DESC LIMIT ? OFFSET ?`, using
  `ix_jobs_submitted_at`), `count() -> int`, and `all() -> List[JobRow]` (bounded read
  for aggregation), all lock-guarded like the existing methods.
- **`registry.py`**: `JobRecord` (a `@dataclass`) gains `original_filename:
  Optional[str] = None` — **positioned immediately after `recipient`** (the last init
  field with a default) and **before** the `field(init=False)` block, with a default of
  `None`, so Python's "no non-default after default" rule is satisfied (review B3).
  Update **both** `_to_row()` (pass `original_filename=self.original_filename`) **and**
  `from_row()` (read `row.original_filename`) — omitting `_to_row` would silently persist
  `None` even though the analyze route set it (review B2); tasks.md asserts a
  `JobRecord(original_filename="x") → _to_row → upsert → get → from_row` round-trip. Add
  `JobRegistry.list_jobs(limit, offset)`, `count()`, `all_rows()` delegating to the store
  (rehydration-safe — reads durable rows, not just the live dict).
- **`core.py`**: `run_pipeline(..., original_filename: Optional[str] = None)`; when not
  resuming, seed `stream_input["original_filename"] = original_filename` (only if not
  None — keeps 011/012 byte-identical default when omitted).
- **`worker.py`**: pass `original_filename=rec.original_filename` into `run_pipeline`.
- **`ingest_agent.py`** (the one permitted graph edit): change line 60 to
  `original_filename = state.get("original_filename") or Path(document_path).name`.
  Prefers the seeded real name; falls back to path-derivation for tests/legacy. Adds no
  node/edge, reads an already-declared 001 field (no state-schema change).
- **`routes.py` `analyze`**: compute `original_filename = file.filename or f"{job_id}{ext}"`
  and pass it to `JobRecord(..., original_filename=original_filename)`.

### 3.4 Pure aggregation (`app/api/aggregate.py`) — the testable core

Kept out of the route handlers so it unit-tests with plain data (no HTTP, no disk):

```python
@dataclass
class ReportData:                         # the slice we read from a report .json
    high: int; medium: int; low: int
    total_clauses: int; validated_findings: int
    findings: list                        # [{clause_type, risk_level}]

def read_report_data(report_path: str | None) -> ReportData | None:
    # resolve .json sibling of report_path (same as routes.py report handler);
    # return None if path missing / file absent / malformed (EC-3/EC-10, logged).

def derive_band(high, medium, low, validated) -> str:        # 017-style (D9)
def portfolio_health(high, medium, low) -> tuple[int, str]:  # D3 formula + band, max(1,graded) guard

def build_job_list(rows, read: Callable[[str|None], ReportData|None],
                   limit, offset, total) -> JobList          # D9/D14/B-2 report_available via read result
def build_dashboard_metrics(rows, read, *, today) -> DashboardMetrics
    # totals (D10), risk_distribution (D8), health (D3), usage_timeline (D7 day-bucket,
    # USAGE_TIMELINE_DAYS), risk_by_clause_type + heatmap (D4/D5, null→"Uncategorized"),
    # top_risky_clause_types (D6). Failed/no-report rows: counted in totals, skipped in risk.
```

- `build_*` take `rows: List[JobRow]` and an injected `read` callable → **pure**, fully
  unit-testable with a stub `read` (no filesystem). The route wires
  `read = read_report_data` and `rows = registry.all_rows()` / `list_jobs(...)`.
- `report_available` per item = `read(report_path) is not None` (review N4): the reader
  resolves and parses the **`.json` sibling** of `report_path`, so `report_available` is
  keyed on the **`.json`** existing — which is exactly what aggregation needs (a report
  whose `.json` is gone/malformed can't be folded, EC-3/EC-10). This is intentionally
  the `.json` check, a hair stricter than `to_status()`'s `.md` check; AC-10/EC-3 tests
  seed a missing/broken `.json` accordingly.
- **`usage_timeline` is DENSE (review N5):** return **all `USAGE_TIMELINE_DAYS` day
  buckets** (UTC, oldest→newest ending today), zero-filled for days with no jobs, so the
  bar/area chart shows a continuous series. An empty store still returns 30 zero buckets
  (the page's empty-state gate, not the chart, handles "no contracts" — D11).
- `derive_band(high, medium, low, validated)` reproduces 017's TS `deriveRiskBand`
  (`high>0→"high"`, else `medium>0→"medium"`, else `validated>0→"low"`, else `"none"`);
  because this is a **second implementation** of that logic (review N2), `test_aggregate`
  asserts all four cases so the Python and TS bands can't silently drift.

### 3.5 Routes (`app/api/routes.py`)

```python
@router.get("/jobs", response_model=JobList)         # NOTE: registered alongside /jobs/{job_id}
async def list_jobs(request, limit: int = cfg.JOBS_LIST_DEFAULT_LIMIT, offset: int = 0):
    limit = max(1, min(limit, cfg.JOBS_LIST_MAX_LIMIT)); offset = max(0, offset)   # EC-6 clamp
    reg = _get_ctx(request).registry
    return build_job_list(reg.list_jobs(limit, offset), read_report_data,
                          limit, offset, reg.count())

@router.get("/dashboard", response_model=DashboardMetrics)
async def dashboard(request):
    reg = _get_ctx(request).registry
    return build_dashboard_metrics(reg.all_rows(), read_report_data, today=_utc_today())
```

`GET /api/jobs` (one segment) and `GET /api/jobs/{job_id}` (two segments) can never
match the same concrete path, so they coexist regardless of **declaration order** (order
only matters when two routes *can* match the same path, e.g. `/jobs/active` vs
`/jobs/{id}` — not the case here). `analyze` adds the filename capture from §3.3.

---

## 4. Frontend design

> **Client/server split (constitution §8).** `dashboard/page.tsx` and
> `reports/page.tsx` stay **server** components rendering the existing `TopBar` + a new
> **client** `DashboardView` / `ReportsView` (which call the hooks). `useDashboard`,
> `useJobs`, `DashboardView`, `ReportsView`, and the modified `BarChart` carry
> `"use client"`.

### 4.1 Seam (`types.ts` / `client.ts` / providers / fixtures)

- **`types.ts`**: mirror `JobListItem`, `JobList`, `RiskDistribution`, `UsageBucket`,
  `ClauseTypeRisk`, `ClauseRiskHeatmap`, `TopClause`, `DashboardMetrics` field-for-field
  (constitution §4). `dashboardMetrics-fields.test.ts` locks the shape (017 AC-15a style).
- **`client.ts`**: `getJobs(params?: { limit?: number; offset?: number }): Promise<JobList>`
  and `getDashboardMetrics(): Promise<DashboardMetrics>` on `ApiClient`.
- **`realProvider.ts`**: `fetch` `/api/jobs?limit&offset` and `/api/dashboard`, `asJson`
  with `ApiError` wrap (status preserved), same pattern as `getReport`.
- **`mockProvider.ts`**: return `jobListFixture` / `dashboardMetricsFixture`.
- **`fixtures.ts`**: a rich `dashboardMetricsFixture` (mixed severities, ≥2 clause types,
  a "Uncategorized" bucket, a non-empty heatmap, a few usage buckets), a `jobListFixture`
  (completed + running + failed items), and **empty** variants (all-zero / `items:[]`).

### 4.2 Hooks (`useDashboard.ts`, `useJobs.ts`)

Same *pattern* as `useReport` (017) — a discriminated-state hook — but note the exact
shape differs: these return `{ state: { phase, data, message }, retry }` (phase nested
under `state`, payload keyed `data`), consistent with `useReport`'s
`{ state:{ phase, report, message }, retry }` (do **not** claim identical field names).
`phase: "loading"|"loaded"|"empty"|"error"`; `empty` when `total_contracts === 0`
(dashboard) / `total === 0` (jobs) so the views branch cleanly (D11). Reach the backend
only via `getApiClient()`.

### 4.3 `BarChart` stacked mode (D4 / review B-1)

Backward-compatible addition — existing `value`/`secondary` calls unchanged:

```ts
export interface StackSeries { key: string; label: string; level: "low"|"medium"|"high"; }
export function BarChart({ data, grouped, height, stack }: {
  data: Array<Record<string, number | string>>; grouped?: boolean; height?: number;
  stack?: StackSeries[];   // NEW: when set, render one <Bar stackId="a" dataKey={s.key} fill={riskColor(s.level)}/> per series
}) { … }
```

`ReportsView` passes `data = risk_by_clause_type.map(t => ({name:t.clause_type, low:t.low, medium:t.medium, high:t.high}))` and `stack = [{key:"low",level:"low",…},{medium},{high}]`.
**Caveat (review):** in `stack` mode the component must render **only** the per-series
`<Bar>`s (skip the default `dataKey="value"` bar and the `secondary` bar), else an empty
`value` series draws alongside. Existing `value`/`secondary` callers (dashboard `USAGE`,
reports has none now) are unchanged because `stack` is undefined for them.

### 4.4 `DashboardView` (Command Center) — AC-13/15/16/17

`useDashboard()` + `useJobs()`. Branch: `loading` → skeleton; `error` → retry; `empty`
→ "No contracts analyzed yet" + link `/upload` (D11). Loaded:
- **Risk Summary** donut from `risk_distribution` (map to `DonutSlice[]`), center shows a
  real count; the derived `portfolio_health_pct` replaces the fake `ScorePill value={78}`
  and `"78"/"/100"` (D3/D12, AC-13).
- **Activity Feed** from `getJobs()` items: `original_filename`, status/risk badge,
  `finished_at ?? submitted_at`; a completed row links to `/jobs/{id}/report` (AC-17).
- **Usage** bar from `usage_timeline`.
- Notifications/greeting/quick-actions kept as **static chrome** (D12); "Upload"
  actions link `/upload`.

### 4.5 `ReportsView` (Risk Dashboard) — AC-14/15/16

`useDashboard()`. Empty/loading/error as above. Loaded:
- **Risk by clause type** → stacked `BarChart` (§4.3).
- **Heatmap** → `<Heatmap data={cells} rowLabels={rows} colLabels={cols}/>` from
  `clause_risk_heatmap` (D5). Note (review): `Heatmap`'s own `rowLabels` render only in
  SVG `<title>` tooltips, so `ReportsView` reproduces the reference's **left-column
  label stack** (`reports/page.tsx:104-109`) next to the grid, fed from
  `clause_risk_heatmap.rows`, so the clause-type labels are visible.
- **Usage** area from `usage_timeline`; **distribution** donut from `risk_distribution`.
- **Top risky clauses** from `top_risky_clause_types`.
- **Total Contracts Analyzed** = `completed_contracts` (D10); **Portfolio Health** % +
  `GaugeChart value={portfolio_health_pct}` (D3) — no `"/100"`, no `"80%"` literal.

---

## 5. Tests mapped to acceptance criteria

**Backend (pytest).**
- `test_aggregate.py` (pure, no disk — inject `read` stub + `JobRow` lists):
  health formula & bands (AC-5), `derive_band`, empty store → zeros + `pct=100` (AC-9),
  risk_distribution sum (AC-4), by-clause-type + heatmap incl. `null`→"Uncategorized"
  (AC-6/D14), top clauses (AC-7), usage day-buckets (AC-8), missing-report skip (AC-10),
  failed-job-in-totals-not-risk (EC-2).
- `test_store_list.py`: `original_filename` upsert/round-trip after migration (AC-11),
  `list`/`count`/`all` ordering + pagination (AC-1), legacy null filename fallback (AC-12/EC-7).
- `test_dashboard_endpoints.py` (TestClient, seeded store + report fixtures):
  `GET /api/jobs` shape/pagination/empty (AC-1/2/3), `GET /api/dashboard` (AC-4..9),
  `analyze` persists real filename end-to-end (AC-11), pagination clamp (EC-6),
  `/api/jobs` vs `/api/jobs/{id}` no collision.

**Frontend (Vitest + RTL, mock provider).**
- `dashboardMetrics-fields.test.ts`: TS mirror carries every Pydantic field (AC-18).
- `barchart-stacked.test.tsx`: `stack` renders N `<Bar>`s; empty data → "No data".
- `useDashboard.test.tsx`: loading→loaded, empty (total 0), error+retry.
- `dashboard.test.tsx`: renders donut/feed/usage from fixtures, no hardcoded consts, no
  `ScorePill`/"78"/"/100" (AC-13); empty state (AC-15); error state (AC-16); completed
  feed row links to `/jobs/{id}/report` (AC-17); uses `getApiClient()` only (AC-18).
- `reports.test.tsx`: stacked bar + heatmap + gauge from metrics, headline =
  `completed_contracts`, no `RISK_BY_TYPE`/`HEATMAP`/"339"/"80%"/"/100" (AC-14); empty
  (AC-15); error (AC-16).
- Boundary grep: no `realProvider`/`mockProvider` import in `components/dashboard`.

**Live smoke (AC-20):** analyze ≥2 real contracts; `/dashboard` + `/reports` show real
totals/distribution/filenames; fresh store shows empty state.

---

## 6. Implementation order (TDD — constitution §7)

1. **Backend pure core:** `config` constants → `models.py` boundary models →
   `aggregate.py` + `test_aggregate.py` (red→green). No HTTP, no disk.
2. **Persistence:** migration `0002` → `store.py`/`registry.py` (`original_filename` +
   `list`/`count`/`all`) + `test_store_list.py`.
3. **Filename seed:** `core.py` param → `worker.py` → `ingest_agent.py` read-seeded →
   `routes.analyze` capture. (Unit: ingest prefers seeded name.)
4. **Endpoints:** `routes.py` `GET /api/jobs` + `GET /api/dashboard` +
   `test_dashboard_endpoints.py`. Run the **full backend suite** — confirm 012/011
   tests still green (JobRecord/JobRow gained a field; `run_pipeline` gained a kwarg —
   both default-compatible).
5. **Frontend seam:** `types.ts` + `client.ts` + providers + fixtures +
   `dashboardMetrics-fields.test.ts`.
6. **BarChart stacked:** `BarChart.tsx` + `barchart-stacked.test.tsx` (keep existing
   BarChart usages green).
7. **Hooks + views:** `useDashboard`/`useJobs` → `DashboardView`/`ReportsView` → wire
   `page.tsx` shells; `useDashboard.test.tsx`, `dashboard.test.tsx`, `reports.test.tsx`.
8. **Verify:** `pytest` (whole backend), `vitest run` (whole frontend), `tsc --noEmit`,
   `npm run lint`, `next build` (dev server STOPPED). Confirm no `backend/app/graph/`
   file other than `ingest_agent.py` changed (AC-19).
9. **Live smoke (AC-20):** `uvicorn` + Ollama, `provider=real`, analyze ≥2 contracts,
   eyeball both pages + empty state; reset `.env.local` to `mock`.

Each step's tests are written failing first (constitution §7). Note the migration means
the live smoke (and any real run) needs `alembic upgrade head` before starting the API.

---

## 7. Notes / risks

- **Existing durable stores need the migration.** A dev machine with a pre-018 SQLite DB
  must run `alembic upgrade head`; the new column is nullable so old rows load with
  `original_filename = None` → list fallback to the job-id name (EC-7/AC-12).
- **JobRecord/JobRow/run_pipeline signature changes are additive & default-compatible** —
  012/011 tests construct these; the new field/kwarg default to `None`, so existing
  callers and tests keep working (verify in step 4). The `ingest_agent` change is a
  read-with-fallback, so its existing tests (which set only `document_path`) still pass.
- **Aggregation cost (D1):** O(#jobs) small JSON reads per dashboard GET, bounded by
  `MAX_JOBS`; fine for local. The persisted-summary column is the escape hatch if a
  deployment ever grows the store (spec §5).
- **`next build` vs `next dev`:** never build while dev runs (013/015 lesson) — step 8
  builds with dev stopped.
- **Charts in jsdom:** the `ResizeObserver` stub in `vitest.setup.ts` already lets
  Recharts render in tests (used by 017's donut); the stacked BarChart + Heatmap tests
  rely on the same stub.

---

*Per constitution §1/§11, a `feature/018-dynamic-dashboard` branch opens only after this
plan.md and its spec.md are approved and `tasks.md` exists. No `tasks.md` or
implementation was written in this pass — plan only.*
