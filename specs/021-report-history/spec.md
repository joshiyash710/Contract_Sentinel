# Feature 021 — Report History (Contracts List)

## 1. Problem statement

There is no way to browse past work. The dashboard shows only the **6 most-recent** jobs in its
Activity Feed (018), and the "Contracts" sidebar item currently just **redirects to `/upload`**
(015 D5) — so once a contract scrolls off the feed, its report is effectively unreachable
except by a saved URL. Users need a **Report History**: a browsable list of every contract they
have analyzed, each linking to its report.

This is **phase 2** of the post-019 set (020 profile ✓ → **021 report history** → 022 report
redesign).

### Position relative to the constitution

**No amendment, no backend change.** The data already exists: `GET /api/jobs` returns the
caller's jobs (user-scoped since 019), newest-first, paginated (`limit`/`offset`, with `total`).
This feature is **frontend-only** — a new list view + a nav/route change. No LangGraph
node/edge, no `ContractState`, no new endpoint, no migration. Per §11 it is developed on
`feature/021-report-history`.

## 2. Inputs and outputs

### 2.1 Data source (unchanged backend)
`GET /api/jobs?limit&offset` → `JobList { total, items: JobListItem[] }`, where each
`JobListItem` already carries everything the history needs:
`job_id, original_filename, status, submitted_at, finished_at, report_available, risk_band,
high, medium, low`. Scoped to the logged-in user (019). No new fields.

### 2.2 The Report History page (`/contracts`)
Replaces the current `redirect("/upload")`. Renders a **table of all the user's analyzed
contracts**, newest-first:

| Column | Source |
| --- | --- |
| **Contract** | `original_filename` |
| **Submitted** | `submitted_at` (formatted) |
| **Status** | `status` (queued / running / completed / failed) as a badge |
| **Risk** | `risk_band` (high/medium/low/none) as a risk badge — only for completed |
| **Findings** | `high`/`medium`/`low` counts (completed only) |
| **Action** | **View Report** → `/jobs/{job_id}/report` when `report_available`; otherwise a state hint (e.g. "Processing…", "Failed", "No report") |

- A header with the page title + an **"Upload New Contract"** button → `/upload` (the upload
  flow is no longer reached via the nav item; it moves to this button — D1).
- **Client-side sort** (by the table's sortable columns) and a **filename search** box.
- **Pagination** so long histories are navigable.
- Polished **empty / loading / error** states consistent with the dashboard (018).

### 2.3 Navigation change
The sidebar **"Contracts"** item points to **`/contracts`** (the history list) instead of
`/upload` (D1). All five nav items remain; no new item is added.

## 3. Resolved decisions (inline)

- **D1 — "Contracts" = the history list; upload becomes a button.** Reverses 015 D5 ("Contracts
  nav = the upload flow"). Rationale: a top-level "Contracts" item is expected to show the
  user's contracts, not jump straight into an uploader; the upload action lives as a prominent
  **"Upload New Contract"** button on the list page (and `/upload` stays directly reachable).
  This matches the reference mockups, where "Contracts" is a persistent nav destination.
- **D2 — Load the full (bounded) history, then filter/sort/paginate client-side.** A user's job
  count is bounded by the retention cap (`JOB_STORE_RETENTION_MAX`), so the page fetches up to
  the list endpoint's max (`JOBS_LIST_MAX_LIMIT`) in one call and does search / sort /
  pagination **in the browser** — making filename search and column sort accurate across the
  whole history (not just one server page). If `total` ever exceeds what was fetched, a clear
  "showing the most recent N of M" note is shown (honest, no silent truncation). No new backend
  paging semantics.
- **D3 — Row action keyed on `report_available`.** "View Report" links to
  `/jobs/{job_id}/report` **only** when the report is available; otherwise the row shows a
  non-link status hint. A whole completed row is also click-through to its report (convenience).
- **D4 — Reuse existing pieces.** Built on the `useJobs` hook (already paginated), the
  `DataTable` primitive (sortable, per-row actions — built for "screen 12 history"), and the
  existing `StatusBadge` / risk badge + `deriveRiskBand` helpers. No new data hook or endpoint.
- **D5 — Status/risk semantics reuse 017/018.** `risk_band` and the findings counts come
  straight from `JobListItem` (already derived server-side from the 009 report). Running/queued
  rows show no risk (dashes); failed rows show a Failed badge and no report link.
- **D6 — No selection/bulk/compare/download here.** The `DataTable` supports select-all and a
  Compare/Download action slot (screen 12), but contract **comparison** and bulk actions are
  **out of scope** (comparison is a separate future feature). v1 is: browse, search, sort, open.
- **D7 — Seam preserved.** The view reaches the backend only via `getApiClient()` (no direct
  provider import); mock provider returns `jobListFixture` so the page renders in mock dev/tests.

## 4. Acceptance criteria

Frontend → Vitest + RTL (mock/fake provider). No backend criteria (unchanged).

- **AC-1:** `/contracts` renders a row for each contract from `getJobs()` showing the filename,
  submitted date, status, and — for completed rows — risk band + findings counts. (Was a
  redirect to `/upload`.)
- **AC-2:** A completed row with `report_available` renders a **View Report** link to
  `/jobs/{job_id}/report`; a running/queued/failed row shows a status hint and **no** report
  link.
- **AC-3:** The **"Upload New Contract"** button links to `/upload`.
- **AC-4:** The **filename search** filters the list to matching contracts (case-insensitive,
  substring); clearing it restores the full list.
- **AC-5:** **Sorting** a sortable column (e.g. Submitted, Contract) reorders the rows
  (DataTable). Default order is newest-first.
- **AC-6:** **Pagination** — with more than one page of contracts, page controls navigate
  between pages and show the range/total ("1–20 of N"); a single page shows no pager.
- **AC-7:** **Empty state** — when the user has zero contracts, a polished "No contracts yet /
  Upload your first contract" state with a CTA to `/upload` (not an empty table).
- **AC-8:** **Loading** shows a loading state; a `getJobs` failure shows an error state with a
  retry that re-calls `getJobs` (reuse the 018 pattern).
- **AC-9:** The sidebar **"Contracts"** item navigates to `/contracts` and is marked active
  there; no new nav item is added (still five).
- **AC-10:** No `components/**` history file imports a provider directly (seam); no
  `backend/**` file changes.

**Live (real backend)**
- **AC-11 (smoke, manual):** With `provider=real`, upload a couple of contracts, then open
  Contracts → both appear newest-first with correct status/risk; completed ones open their real
  report; a second account sees only **its own** history (019 isolation still holds).

## 5. Edge cases
- **EC-1 — Zero contracts** → empty state (AC-7), never a header-only empty table.
- **EC-2 — Running/queued row** → status badge, dash for risk/findings, no report link (AC-2).
- **EC-3 — Failed row** → Failed badge, no report link; filename still shown so the user knows
  what failed.
- **EC-4 — Completed but `report_available=false`** (artifact evicted/missing, 017/018) → shows
  "No report" hint, not a dead link.
- **EC-5 — Search with no matches** → a "no results" row/message (distinct from the zero-contracts
  empty state), with the search still editable.
- **EC-6 — History larger than the fetch cap** → "showing the most recent N of M" note (D2); no
  silent drop.
- **EC-7 — Long filenames** → truncate with ellipsis; full name available on hover/title.

## 6. Out of scope
- **Contract comparison** (side-by-side diff, screen 7) and **bulk actions / multi-select
  download** — separate future features (D6).
- **Server-side search/filtering or new paging params** — client-side over the fetched
  (retention-bounded) set (D2); no backend change.
- **Deleting / renaming / re-running** a contract from the list — not built here.
- **The report page redesign** — feature 022.
- **Any backend/graph/state change** — none.

## 7. Notes for plan.md / tasks.md (pointers)
- Frontend touch: `src/app/contracts/page.tsx` (replace the redirect with the new view), a new
  `src/components/history/ReportHistoryView.tsx` (table + search + pager + states), possibly a
  small `src/lib/history.ts` for row formatting, and `src/components/shell/Sidebar.tsx`
  (`NAV_ITEMS` "Contracts" `href` → `/contracts`). Reuse `useJobs`, `DataTable`, `StatusBadge`,
  risk-band helpers, and the 018 empty/error patterns.
- Tests: a new `ReportHistoryView`/contracts-page test (rows, view-report link, upload button,
  search, empty/error), a sidebar-nav test update (Contracts → `/contracts`), and a boundary
  grep (no provider import). Any existing test asserting Contracts → `/upload` is updated (the
  nav contract legitimately changed — D1).
- TDD (§7): failing tests first; 015/017/018 behavior preserved except the intentional D1 nav
  change.
