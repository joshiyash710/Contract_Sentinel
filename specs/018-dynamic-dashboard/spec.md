# Feature 018 — Dynamic Dashboard (Command Center + Risk Dashboard)

## 1. Problem statement

Feature 013 delivered two portfolio-level screens — the **Command Center**
(`/dashboard`) and the **Risk Dashboard** (`/reports`) — but they render **100%
hardcoded demo data** (`RISK_SLICES`, `ACTIVITY`, `USAGE`, `RISK_BY_TYPE`,
`DISTRIBUTION`, `HEATMAP`, `TOP_CLAUSES`, "339 contracts", "78/100", "80% health",
fake heatmap labels like "Pox Nick"). Feature 017 made the **single-contract**
report page real; this feature makes the **portfolio** pages real — showing
aggregates over the contracts the user has actually analyzed.

Unlike 017, the backend today exposes **no way to list or aggregate jobs** — the
011 API has only per-job endpoints (`analyze`, `jobs/{id}`, `events`,
`jobs/{id}/report`), and the 012 `JobStore` has only `get(id)` / `nonterminal()` /
`prune()`. So this feature **adds new read-only backend endpoints** plus one small
persistence correctness fix, then wires the two pages to them.

### Position relative to the fixed architecture (constitution §2)

This feature adds **no LangGraph node, no edge, and does not change the 7-node graph
or its state transitions** (constitution §2 is untouched). It lives entirely in the
**API/runner/persistence layer** (features 011/012, which are outside the graph) plus
the frontend. The internal `ContractState` `TypedDict` never crosses the wire; all new
surfaces are **Pydantic** boundary models (constitution §4).

**Constitution §2 CUT-list note (resolved).** §2 PERMANENTLY CUT lists "Any audit log
UI, dashboard, or viewer." Per the project owner's explicit confirmation, that item
refers to a viewer **for the Phase-2 audit log** (grouped with the security/compliance
cuts: KMS, ISO 27001, RBAC), **not** the product analytics dashboard. The Command
Center / Risk Dashboard are established product features (013 shipped them; the 013
phasing maps 018 = dashboards). This feature is therefore in scope. No audit-log
surface is built.

Per constitution §11 it is developed on `feature/018-dynamic-dashboard`.

### Reference screens

- **Command Center** (`/dashboard`, screens 1–2, `…31 PM.jpeg` / `…(1).jpeg`) — Risk
  Summary donut, Activity Feed, Usage Analytics.
- **Risk Dashboard** (`/reports`, screen 3, `…(2).jpeg`) — risk-by-type bar, heatmap,
  usage area, risk-distribution donut, top risky clauses, total-contracts + portfolio-
  health stats + gauge.

## 2. Inputs and outputs

### 2.1 Relationship to 001 / 012 / 009 / 011

This feature reads data that **already exists**, plus one field it makes correct:

- **012 `JobStore` (`jobs` table)** — per-job: `job_id`, `status`, `submitted_at`,
  `started_at`, `finished_at`, `report_path`, `error`, etc. Source for the **list**,
  the **usage timeline**, **total contracts**, and per-job status/timestamps.
- **009 `ContractReport` JSON** (at `report_path`'s `.json` sibling) — per completed
  contract: `summary` {`total_clauses`, `validated_findings`, `clean_clauses`,
  `high`, `medium`, `low`} and `findings[]` (each with `clause_type`, `risk_level`).
  Source for all **risk aggregates** (distribution, by-clause-type, heatmap, top
  clauses, portfolio health).
- **001 `original_filename`** (001 §3 line 84 — "Original filename of the uploaded
  document") is **already part of the schema**, but the runner currently **loses the
  real name**: `POST /api/analyze` saves the upload as `{job_id}{ext}` and the report
  ends up showing the job-id filename (observed in the 017 smoke:
  `c48ef4c7…docx`). This feature makes `original_filename` **correct** by capturing
  the real upload filename and persisting it (see D2) — a **001-alignment fix**, not a
  new field, so it introduces no name conflict with 001.

No `ContractState` field is added; no graph node reads or writes anything new.

### 2.2 New backend surface (011 API layer — read-only, outside the graph)

Two new endpoints and one changed endpoint:

| Endpoint | Purpose | Response (new Pydantic boundary models) |
| --- | --- | --- |
| `GET /api/jobs?limit=&offset=` | List jobs newest-first (Activity Feed / contracts list) | `JobList { items: JobListItem[], total: int }` |
| `GET /api/dashboard` | Portfolio aggregates (all charts) | `DashboardMetrics { … }` (see §2.3) |
| `POST /api/analyze` (**changed**) | Now captures `file.filename` and persists it (D2) | unchanged response (`AnalyzeAccepted`) |

`JobListItem` = `{ job_id, original_filename, status, submitted_at, finished_at,
report_available, risk_band: str|null, high: int|null, medium: int|null, low: int|null
}`. Risk fields are `null` for non-completed jobs (no report yet). `risk_band` is the
017-style derived band ("high"/"medium"/"low"/"none") from that report's counts.
**`report_available` (review B-2)** uses the **same disk-existence check** as 012's
`to_status()` — `report_path` is set **and** the file exists on disk — so a completed
job whose report file is gone (017 INV-2) reports `report_available: false` and `null`
risk counts, consistent with AC-10/EC-3.

These are **boundary Pydantic models**, mirrored field-for-field into the frontend
`types.ts` (constitution §4), consumed only through the 013 `getApiClient()` seam.

### 2.3 `DashboardMetrics` shape (every field grounded in real data)

```
DashboardMetrics {
  total_contracts: int              # count of jobs in the store (D10)
  completed_contracts: int          # jobs with status == completed
  risk_distribution: { high: int, medium: int, low: int }   # summed across all reports (D8)
  portfolio_health_pct: int         # DERIVED from counts, not fabricated (D3)
  portfolio_health_band: str        # "healthy" | "elevated" | "at_risk" (D3)
  usage_timeline: [{ period: str, count: int }]             # jobs per day/week (D7)
  risk_by_clause_type: [{ clause_type: str, high: int, medium: int, low: int }]  # (D4)
  clause_risk_heatmap: {            # clause_type × severity (D5)
    rows: string[],                 # clause_type labels
    cols: ["low","medium","high"],
    cells: int[][]                  # cells[r][c] = finding count
  }
  top_risky_clause_types: [{ clause_type: str, high_count: int }]   # top 5 (D6)
}
```

### 2.4 Resolved decisions (inline, per project preference — not open questions)

- **D1 — Aggregation reads 009 report JSONs on demand; the jobs table drives list &
  timeline.** The `/api/dashboard` and `/api/jobs` handlers iterate the store's jobs;
  for each **completed** job with a report file, they read the `.json` report and fold
  its `summary`/`findings` into the aggregates. No new *risk* columns are persisted.
  This is acceptable because the store is bounded (012 prunes to `MAX_JOBS`) and no LLM
  is involved (constitution §9 latency note does not apply — these are fast local file
  reads). Persisting a compact risk-summary column for O(1) aggregation is a noted
  **future optimization**, explicitly not done here (§5). **Join key (review N-3):** a
  job is joined to its report by the store's `report_path` (the `.md` path; the
  aggregator reads its `.json` sibling, the same resolution the 011 report handler
  uses), **not** by `document_id` (a separate uuid the ingest node mints, unrelated to
  `job_id`).
- **D2 — Persist the real `original_filename` (001-alignment fix).** `POST
  /api/analyze` captures the multipart `file.filename`, stores it in a new
  `original_filename` column on the `jobs` table (one Alembic migration, revision
  `0002`, `down_revision="0001"`; nullable for pre-existing rows), and threads it into
  the runner's initial state so `ContractState.original_filename` — and therefore
  `ContractReport.original_filename` — is the **real** name (this also fixes the 017
  report page showing the job-id filename). The `jobs`-table column is required because
  the **list** endpoint must show names for jobs that have **no report yet**
  (queued/running/failed). **Plumbing (review N-2):** `run_pipeline`/`build_graph` accept
  an `original_filename` and seed it into the initial state dict; `ingest_agent` then
  **reads `state.get("original_filename")`** (falling back to deriving it from the path
  when absent, e.g. tests/legacy) instead of always deriving `Path(document_path).name`.
  This edits `ingest_agent.py` to *prefer a seeded value* — it adds **no node and no
  edge**, so the fixed 7-node graph structure (constitution §2) is unchanged; it is the
  one permitted `graph/nodes/` edit (see AC-19). It adds no `ContractState` field (001
  already declares `original_filename`).
- **D3 — Portfolio health is DERIVED, never a fabricated score.** The mockups show
  "78/100" and "80%"; the backend has **no** document- or portfolio-level 0–100 score
  (same gap as 017 D2). We compute an honest metric from the real aggregate risk
  counts over all graded clauses:
  `portfolio_health_pct = round(100 * (1 − (high + 0.5·medium) / max(1, high+medium+low)))`
  (a healthy portfolio ≈ few high/medium findings). Band: `≥80 → "healthy"`,
  `50–79 → "elevated"`, `<50 → "at_risk"`. The weights (`0.5` for medium, band cutoffs)
  are **named configurable constants** (constitution §3 spirit) so they can be tuned.
  When there are **zero** graded clauses, `portfolio_health_pct = 100` and band
  `"healthy"` is **not** shown as a score — the page renders the empty state (D11).
- **D4 — "Risk by contract type" → "risk by clause type".** The mockup's grouped bar is
  labeled by *contract* type (MSA/NDA/SOW), but the system has **no document-level
  contract type** — classifying a whole document as a type would be the CUT "Legal
  Classification Agent" (constitution §2), and no node produces it. It **does** have
  per-clause `clause_type` (001 `ClauseType`). So the bar is remapped to **risk counts
  grouped by `clause_type`** (high/medium/low per type). Honest, real, and derivable.
  **Component note (review B-1):** rendering three severities per type needs the shared
  `BarChart` (today 2-series: `value`/`secondary`) to gain a **stacked multi-series
  (low/medium/high) mode** — a small, self-contained frontend enhancement scheduled in
  plan.md. The *data* (`risk_by_clause_type[]` with high/medium/low, §2.3) is fully real;
  only the chart renderer is extended, backward-compatibly.
- **D5 — Heatmap → `clause_type` × severity.** The mockup heatmap has fabricated axes
  ("Pox Nick" × "Sol/Ref/Pen"). It is remapped to a real 2-D matrix: **rows =
  `clause_type`**, **cols = low/medium/high**, **cell = count of findings**. Intensity
  scales to the max cell. Meaningful and fully backed.
- **D6 — Top risky clauses → top `clause_type` by high-risk count.** Aggregate `high`
  findings by `clause_type` across all reports; take the top 5. (Not individual clause
  instances — the portfolio view is by type.)
- **D7 — Usage timeline = jobs bucketed by day.** Count jobs by the **date** of
  `submitted_at` (UTC day), returned as an ordered `[{period, count}]` covering the
  active range (default: the last 30 days, a named constant). Real; sourced from the
  jobs table alone (works even for failed jobs).
- **D8 — Risk distribution = summed `summary` counts.** `risk_distribution` sums
  `high`/`medium`/`low` from every completed report's `summary`. Shared by the
  dashboard "Risk Summary" donut and the reports "Total Risk Distribution" donut.
- **D9 — Activity Feed = recent jobs.** The dashboard feed and the list endpoint both
  read the newest jobs: `original_filename`, `status`, derived `risk_band` (when
  completed), and a timestamp (`finished_at ?? submitted_at`). No fabricated activity.
- **D10 — "Total contracts" counts jobs in the store.** `total_contracts` = number of
  job rows (bounded by `MAX_JOBS`); `completed_contracts` is surfaced separately so the
  UI can say "N analyzed" honestly. (A job pruned out of the store is no longer
  counted — the store is the source of truth, consistent with 012.)
- **D11 — Real empty states (no fabricated numbers on a fresh install).** With **zero**
  jobs, `/api/dashboard` returns all-zero aggregates and `/api/jobs` returns
  `{items:[], total:0}`; **both pages render explicit empty states** ("No contracts
  analyzed yet" + a link to `/upload`), never the old demo numbers. Charts with no data
  render their own "No data" state (the existing chart components already support this).
- **D12 — Non-data chrome stays static / is trimmed, not faked.** The mockups include
  a **Notifications** panel, "Integration connected — Google Drive connected", "Welcome
  back, Sarah Jenkins", and a "78/100" ScorePill. There is **no** notifications system,
  no auth/user identity (auth PERMANENTLY CUT), and no live integration status. These
  are **not** wired to fake data: the Notifications/greeting are removed or shown as
  clearly static placeholders, the ScorePill is replaced by the derived health metric
  (D3), and the "Upload New Contract" actions link to `/upload`. Making notifications or
  integration-status real is out of scope (§5).
- **D13 — Provider seam.** Two new methods — `getJobs(params)` and
  `getDashboardMetrics()` — are added to the `ApiClient` interface and both providers
  (real: `fetch` the new endpoints, wrapping failures in `ApiError`; mock: static
  fixtures). Default provider stays **mock** so unit tests need no backend. No page
  imports a provider directly (013 seam). The pages fetch via a small hook
  (`useDashboard` / `useJobs`) with loading / empty / error states.
- **D14 — Missing/optional fields bucket safely.** A finding with `clause_type = null`
  is bucketed under **"Uncategorized"** in by-type/heatmap/top aggregations (never
  dropped silently from totals). A finding with `risk_level = null` is counted in
  `total`/`validated` but excluded from the high/medium/low severity aggregates (it has
  no severity to place — mirrors 017 "severity unavailable"). Failed jobs (no report)
  contribute to the list and `total_contracts` but not to risk aggregates.

### 2.5 Outputs (what this feature renders)

- **`/dashboard` (Command Center):** Risk Summary donut (real `risk_distribution` +
  derived health, D3/D8), Activity Feed (real recent jobs, D9), Usage Analytics bar
  (real timeline, D7). Static chrome per D12.
- **`/reports` (Risk Dashboard):** risk-by-clause-type grouped bar (D4), clause-type ×
  severity heatmap (D5), usage area (D7), risk-distribution donut (D8), top risky
  clause types (D6), total-contracts stat (D10), portfolio-health % + gauge (D3).
- Both pages: **loading**, **empty** (D11), and **error** states.

## 3. Acceptance criteria

Backend criteria become pytest cases against the new endpoints (seeded store +
report fixtures); frontend criteria become Vitest + RTL cases driving the **mock**
provider. The real path is covered by the live smoke (AC-20).

**Backend — list endpoint**
- AC-1: `GET /api/jobs` returns `{items, total}` with items newest-first by
  `submitted_at`; `total` equals the number of jobs in the store; `limit`/`offset`
  paginate (e.g. `limit=2&offset=2` returns the 3rd–4th newest).
- AC-2: Each `JobListItem` carries `original_filename` (the **real** name, D2),
  `status`, `submitted_at`, `finished_at`, `report_available`, and — for a completed
  job — a derived `risk_band` and `high/medium/low` from its report; a non-completed
  job has those risk fields `null`.
- AC-3: With an empty store, `GET /api/jobs` returns `{items:[], total:0}` (no error).

**Backend — dashboard aggregate**
- AC-4: `GET /api/dashboard` returns `total_contracts` and `completed_contracts`
  matching the seeded store, and `risk_distribution` equal to the summed `high/medium/
  low` across the seeded completed reports (D8).
- AC-5: `portfolio_health_pct` equals the D3 formula applied to the summed counts, and
  `portfolio_health_band` matches the D3 cutoffs; a store with only low-risk findings
  yields a high `pct`, a store dominated by high-risk yields a low one.
- AC-6: `risk_by_clause_type` groups finding counts by `clause_type` (with `null` →
  "Uncategorized", D14); `clause_risk_heatmap` has `rows` = the clause types present,
  `cols = [low,medium,high]`, and `cells[r][c]` = the matching finding count.
- AC-7: `top_risky_clause_types` lists the ≤5 clause types with the most **high** risk
  findings, descending.
- AC-8: `usage_timeline` buckets jobs by UTC day over the configured window, counts
  matching the seeded `submitted_at` dates (D7).
- AC-9: With an empty store, `/api/dashboard` returns all-zero aggregates,
  `portfolio_health_pct = 100`, empty lists/heatmap — no error, no division-by-zero.
- AC-10: A completed job whose report `.json` is **missing on disk** (017 INV-2 case)
  is skipped in risk aggregation without error; it still counts in `total_contracts`.

**Backend — filename persistence (D2)**
- AC-11: `POST /api/analyze` with an upload named `heavy_contract.docx` results in a
  job whose `original_filename` is `heavy_contract.docx` (not `{job_id}.docx`), visible
  via `GET /api/jobs` and in the generated report's `original_filename`.
- AC-12: A job row created before the migration (no stored filename) surfaces a safe
  fallback (the job-id-based name) rather than null/crash (D2, EC-7).

**Frontend — dashboard & reports**
- AC-13: `/dashboard` fetches via `getApiClient().getDashboardMetrics()` +
  `getJobs()` (no direct provider import), and renders the Risk Summary donut from
  `risk_distribution`, the Activity Feed from the job list, and the Usage bar from
  `usage_timeline` — **no** hardcoded `RISK_SLICES`/`ACTIVITY`/`USAGE` remain, and the
  fabricated `ScorePill value={78}` / donut-center `"78"` / `"/100"` are removed (the
  donut center shows a real count and the derived health per D3/D12).
- AC-14: `/reports` renders risk-by-clause-type, the clause×severity heatmap, usage,
  the distribution donut, top clauses, total contracts, and the derived portfolio-
  health % + gauge — all from `DashboardMetrics`; **no** hardcoded `RISK_BY_TYPE`/
  `HEATMAP`/`DISTRIBUTION`/`TOP_CLAUSES`/"339"/"80%" remain, and no "/100" or fabricated
  score string is rendered (D3).
- AC-15: With empty metrics (fresh install), both pages render the D11 empty state
  ("No contracts analyzed yet" + link to `/upload`), not zeros-as-charts-that-look-
  broken and not demo numbers.
- AC-16: While the fetch is in flight both pages show a loading state; on fetch error
  they show an error state with a retry — no unhandled throw, no infinite spinner.
- AC-17: The Activity Feed rows show the real `original_filename`, a status/risk badge,
  and a real timestamp; clicking a **completed** row links to that contract's report
  (`/jobs/{id}/report`, 017).

**Seam / boundary**
- AC-18: `getJobs` and `getDashboardMetrics` exist on the `ApiClient` interface and
  both providers; the `JobList`/`DashboardMetrics` TS mirrors match the Pydantic models
  (a field-list drift test, mirroring 017 AC-15a). Swapping mock↔real needs no page
  edit (013 seam).
- AC-19: The fixed 7-node graph **structure** is unchanged — **no node or edge is
  added, removed, or reordered** (constitution §2), and no `ContractState` field is
  added. The **only** permitted `backend/app/graph/` edit is `ingest_agent.py` preferring
  a runner-seeded `original_filename` over deriving it from the path (D2); every other
  backend change is confined to the API layer, `JobStore`/runner persistence, and one
  Alembic migration (structural check asserts no other `graph/` file changed).

**Live end-to-end (real backend)**
- AC-20 (smoke, manual/gated): With `NEXT_PUBLIC_API_PROVIDER=real` and the backend
  running, after analyzing ≥2 real contracts, `/dashboard` and `/reports` show real
  aggregates (correct totals, risk distribution matching the reports, real filenames in
  the feed), and a fresh store shows the empty state.

## 4. Edge cases

- **EC-1 — Empty store (fresh install):** AC-3/AC-9/AC-15 — zero aggregates, empty
  lists, `pct=100`, explicit empty-state UI; no division-by-zero, no demo data.
- **EC-2 — Only failed/queued jobs (no reports):** they appear in the list and
  `total_contracts`, but contribute nothing to risk aggregates (`risk_distribution` all
  zero); `completed_contracts = 0`; pages show the list but an empty risk section.
- **EC-3 — Completed job with report file missing on disk (017 INV-2):** skipped in
  aggregation, still counted in totals (AC-10); no crash.
- **EC-4 — `clause_type` null / `risk_level` null (009 optionals):** bucket as
  "Uncategorized" / exclude from severity (D14); totals stay consistent.
- **EC-5 — Large / pruned store:** aggregation is bounded by `MAX_JOBS` (012). Reading
  N small JSONs per request is acceptable (D1); if a future store grows large, the
  persisted-summary optimization (§5) is the escape hatch.
- **EC-6 — Pagination out of range:** `offset` beyond `total` returns `{items:[]}` with
  the true `total`; negative/oversized `limit` is clamped to a sane range.
- **EC-7 — Legacy job rows without a stored filename (pre-D2 migration):** the list
  falls back to the job-id-based name (AC-12); no null/crash. (Existing local stores
  predate the new column.)
- **EC-8 — Backend unreachable / 5xx on a dashboard fetch:** the page shows an error
  state with retry (AC-16); the mock provider path is unaffected.
- **EC-9 — Concurrent write during aggregation:** the `JobStore` is lock-guarded (012
  EC-5); a job completing mid-aggregation either is or isn't included — both are
  consistent snapshots, never a partial/corrupt read.
- **EC-10 — Report JSON present but malformed:** treated like a missing report (EC-3) —
  skipped with a logged warning, not a 500.

## 5. Out of scope

- **Persisting a risk-summary column for O(1) aggregation** — D1 reads report JSONs on
  demand; a `report_summary`/risk-count column (write-through at completion) is a future
  performance optimization, not built here.
- **Notifications system, live integration status, user identity/greeting** — no
  notifications backend, no auth (PERMANENTLY CUT); these stay static chrome (D12).
- **Document-level "contract type" classification** (MSA/NDA/SOW) — would be the CUT
  "Legal Classification Agent" (constitution §2); the by-type views use `clause_type`
  instead (D4/D5).
- **A true 0–100 risk/health score model** — only the derived metric (D3); a real
  scoring model is not introduced.
- **The contracts-history table with search/filter/sort** (the richer `/contracts`
  management view) — that is the deferred **017b** slice; this feature adds only the
  dashboard **Activity Feed** and the list endpoint it needs.
- **Settings page, workspace/chat/comparison** — specs 018-settings (later) / 016. No
  auth, no RBAC (CUT).
- **Real-time push / websockets for live dashboard updates** — the pages fetch on load
  (and on manual refresh); no streaming. (SSE through the dev proxy is also unreliable,
  015 D7.)
- **Any graph/node/state change** — the 7-node graph and `ContractState` fields are
  untouched (AC-19); `original_filename` already exists in 001 (D2 is an alignment fix,
  not a schema addition).

## 6. Resolved decisions (no open questions)

Per the project's inline-decision preference, every significant choice is resolved in
§2.4 (D1–D14). The four previously-open items are now decided with the recommended
defaults:

1. **Portfolio-health formula** → resolved in **D3**: `portfolio_health_pct =
   round(100·(1 − (high + 0.5·medium)/max(1, graded)))`, bands `≥80 healthy / 50–79
   elevated / <50 at_risk`. The `0.5` medium weight and the `80/50` cutoffs are **named
   configurable constants** (constitution §3), tunable against real contracts without a
   spec change.
2. **Usage-timeline bucket & window** → **day-buckets over the last 30 days** (D7), the
   window a named constant (`USAGE_TIMELINE_DAYS = 30`).
3. **"Total contracts" counting** → the API returns **both** (D10): `total_contracts` =
   all job rows, `completed_contracts` = completed. The `/reports` big "Total Contracts
   Analyzed" stat headlines **`completed_contracts`** ("N analyzed"), with the all-jobs
   total available for secondary display.
4. **Filename-fix scope** → **included** (D2): persist the real `original_filename` (one
   Alembic migration + analyze route + runner state-seeding), since real contract names
   are the point of the dashboard, and it also corrects the 017 report filename.
