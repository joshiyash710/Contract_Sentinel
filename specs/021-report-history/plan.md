# Report History (Contracts List) — Technical Plan

## Git Branch

`feature/021-report-history` — branching workflow per `specs/000-constitution.md` §11.

---

## 1. Overview

Implements `specs/021-report-history/spec.md` (phase 2 of 3) — **frontend-only**. Turns the
`/contracts` route (currently `redirect("/upload")`) into a **Report History**: a searchable,
sortable, paginated table of the logged-in user's analyzed contracts, each linking to its
report. Repoints the sidebar **"Contracts"** item to `/contracts` and moves the upload entry to
an **"Upload New Contract"** button on the page (D1).

Built on existing pieces — `useJobs` (paginated `GET /api/jobs`, user-scoped since 019), the
`DataTable` primitive (sortable, per-row actions slot — built "for screen 12 history"),
`StatusBadge`, and the 018 empty/error patterns. **No backend, migration, endpoint, or graph
change.**

**Data ceiling (from config):** `JOBS_LIST_MAX_LIMIT = 100`, `JOB_STORE_RETENTION_MAX = 500`.
The view fetches the most-recent **100** in one call and does search / sort / pagination
client-side; if `total > 100`, a "showing the most recent 100 of N" note is shown (D2 / EC-6).
Raising the fetch beyond 100 (or true server-side paging) is a documented future option, out of
scope here.

---

## 2. Files to Create / Modify

### Frontend (`frontend/`)
```
src/app/contracts/page.tsx                 [MODIFY] replace redirect("/upload") with <TopBar title="Contracts"/> + <ReportHistoryView/>
src/components/history/ReportHistoryView.tsx [NEW]  table + search + pager + empty/loading/error + Upload button
src/lib/history.ts                          [NEW]  small pure helpers: formatSubmitted(date), row→risk tone, "N of M" note text
src/components/shell/Sidebar.tsx            [MODIFY] NAV_ITEMS "Contracts" href: "/upload" → "/contracts"

src/__tests__/reportHistory.test.tsx        [NEW]  rows/link/upload/search/sort/pager/empty/error (AC-1..8)
src/__tests__/history-boundary.test.ts      [NEW]  no provider import in components/history (AC-10)
src/__tests__/shell.test.tsx                [MODIFY] Contracts nav item points to /contracts + active there (AC-9)
```

No `backend/**` change; no new endpoint; no `types.ts` change (JobListItem already has every
field). No `app/graph/` change.

---

## 3. Frontend design

> **Client/server (§8).** `ReportHistoryView` is a client component (`useJobs`, `useState`).
> `app/contracts/page.tsx` is a thin server shell rendering `<TopBar/>` + the view (mirrors
> `dashboard/page.tsx`). `TopBar` is already client (020).

### 3.1 `ReportHistoryView.tsx`
- **Data:** `const { state, retry } = useJobs({ limit: JOBS_LIST_MAX_LIMIT })` (100). Phases:
  `loading` → spinner/skeleton; `error` → message + **Try again** (`retry`) (AC-8); `empty`
  (`total === 0`) → `<EmptyHistory/>` with an Upload CTA → `/upload` (AC-7); `loaded` → the table.
- **Header:** page-level heading + an **"Upload New Contract"** `Link href="/upload"` styled as a
  primary button (AC-3). (The `<TopBar title="Contracts"/>` comes from the page.)
- **Search:** a controlled `search` input; `filtered = items.filter(i =>
  i.original_filename.toLowerCase().includes(search.trim().toLowerCase()))` (AC-4). Reset the
  page to 0 whenever `search` changes. If `filtered.length === 0 && items.length > 0` → a
  "No contracts match" row/message (EC-5), distinct from the zero-contracts empty state.
- **Sort:** delegated to `DataTable` (sortable `Contract` + `Submitted` columns). Rows arrive
  newest-first from the API (AC-5 default).
- **Pagination (client-side):** `pageSize = 20`; `pageRows = filtered.slice(page*pageSize,
  +pageSize)`; a pager below the table with Prev/Next + "showing A–B of {filtered.length}"
  renders only when `filtered.length > pageSize` (AC-6). Clamp `page` to valid range.
- **Overflow note:** if `state.data.total > items.length` (i.e. > 100 exist), render
  "Showing the most recent 100 of {total}." (EC-6).
- **Columns** (`Column<JobListItem>[]`):
  - `Contract` — `original_filename`, sortable, truncated w/ `title` (EC-7); rendered as a
    `Link` to `/jobs/{job_id}/report` when `report_available`, else plain text.
  - `Submitted` — `formatSubmitted(row.submitted_at)`, sortable (sort by the raw ISO via the
    column key `submitted_at`).
  - `Status` — `<StatusBadge>` with a tone map (completed→success, running/queued→neutral/accent,
    failed→danger).
  - `Risk` — completed → a risk badge from `risk_band` (high/medium/low/none); non-completed →
    `—` (EC-2/EC-3).
  - `Findings` — completed with counts → `H {high} · M {medium} · L {low}`; else `—`.
- **Row action** (`actions` slot): `report_available` → **View Report** `Link` →
  `/jobs/{job_id}/report` (AC-2); else a muted status hint ("Processing…" / "Failed" /
  "No report", EC-2/3/4) — never a dead link.
- **Seam:** only `getApiClient()` via `useJobs`; no provider import (AC-10).

### 3.2 `history.ts` (pure helpers)
`formatSubmitted(iso)` → short local date/time; `riskTone(band)` → BadgeTone; `overflowNote(
fetched, total)`. Pure + unit-friendly; keeps the view lean.

### 3.3 Sidebar nav
`NAV_ITEMS`: change the `Contracts` entry `href` from `"/upload"` to `"/contracts"` (D1). Label
and icon unchanged; still five items. `SidebarNavItem` active-state logic already keys on
`usePathname()` so `/contracts` highlights correctly (AC-9).

### 3.4 `app/contracts/page.tsx`
Replace the `redirect("/upload")` with:
```tsx
return (<><TopBar title="Contracts" /><ReportHistoryView /></>);
```

---

## 4. Tests mapped to acceptance criteria

**Frontend (Vitest + RTL; mock/fake provider).**
- `reportHistory.test.tsx` (mock `getApiClient` with `makeFakeClient`):
  - `jobListFixture` → a row per contract with filename/status; completed row shows risk +
    findings (AC-1); the completed row's **View Report** links to `/jobs/{id}/report`; a
    running/failed row has no report link (AC-2).
  - "Upload New Contract" → `/upload` (AC-3).
  - typing in search filters rows (AC-4); no-match → "no contracts match" (EC-5).
  - clicking a sortable header reorders (AC-5).
  - a `jobList` with > pageSize items shows the pager + range; Next advances the page (AC-6);
    ≤ pageSize → no pager.
  - `emptyJobListFixture` → empty state with Upload CTA → `/upload` (AC-7).
  - `jobsError` → error + Try again re-calls `getJobs` (AC-8).
  - overflow: `total` > items → the "most recent 100 of N" note (EC-6).
- `history-boundary.test.ts`: no `realProvider`/`mockProvider` import under
  `components/history` (AC-10).
- `shell.test.tsx`: the Contracts nav item's `href` is `/contracts`, and it is `data-active`
  when `usePathname()==="/contracts"` (AC-9). Still five items.

**Live smoke (AC-11):** `provider=real`; upload two contracts → Contracts lists them
newest-first with correct status/risk; completed opens its real report; a second account sees
only its own history (019).

---

## 5. Implementation order (TDD — §7)

1. **Helpers + view test (red):** write `reportHistory.test.tsx` against the intended
   `ReportHistoryView` API; add `history.ts` pure helpers (+ trivial asserts inline).
2. **View (green):** build `ReportHistoryView` (states → table → search → pager) until the test
   passes; reuse `DataTable`, `StatusBadge`, risk badge, `useJobs`.
3. **Route:** swap `app/contracts/page.tsx` to render `TopBar` + the view.
4. **Nav:** repoint `NAV_ITEMS` Contracts → `/contracts`; update `shell.test.tsx` (AC-9).
5. **Boundary:** `history-boundary.test.ts`.
6. **Verify:** `vitest run` (whole) GREEN; `tsc --noEmit`, `npm run lint`, `next build` (dev
   STOPPED). Backend untouched — run `pytest` once to confirm still green (no changes expected).
   `git diff --name-only main` shows no `backend/**`.
7. **Live smoke** (AC-11). `.env.local` stays as the user set it.

Each step's tests are written failing first (§7). The one sanctioned behavior change is D1 (the
Contracts nav destination) — the `shell` nav assertion is updated intentionally, not weakened.

---

## 6. Notes / risks

- **`DataTable` has no pagination or row-click** — both handled by the view: slice `filtered`
  for the page + a separate pager; navigation via the Contract-cell `Link` and the View-Report
  action. Do **not** modify `DataTable` (keeps the primitive stable for other screens).
- **Fetch ceiling is 100, retention is 500** — a user with >100 contracts sees the most-recent
  100 with an honest note (D2/EC-6). Raising `JOBS_LIST_MAX_LIMIT` or adding true server paging
  is a future, backend-touching option; explicitly out of scope.
- **Nav change is low-risk** — only `Sidebar.tsx` line 19 + the `shell` test; the `/upload` CTAs
  in the dashboard/report empty states are unrelated and unchanged; `/upload` stays a real route.
- **`findings`/`risk` are synthetic columns** (no single `JobListItem` field) — provided via
  `Column.render`; leave them non-sortable (sort on `Contract`/`Submitted` only).
- **`next build` vs `next dev`** — never build while dev runs; step 6 builds with dev stopped.
- **Out of scope discipline** — no compare, no multi-select/bulk, no delete/rerun, no report
  redesign (022).

---

*Per §1/§11, a `feature/021-report-history` branch opens only after this plan.md + spec.md are
approved and `tasks.md` exists. No backend deps, no migration. No `tasks.md`/implementation in
this pass — plan only.*
