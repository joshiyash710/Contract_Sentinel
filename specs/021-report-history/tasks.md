# Report History (Contracts List) — Implementation Tasks

Reference documents:
- Spec: `specs/021-report-history/spec.md`
- Plan: `specs/021-report-history/plan.md`
- Constitution: `specs/000-constitution.md` (**no amendment**, **no backend change**)
- Consumed: 018 (`useJobs`, `JobListItem`, `StatusBadge`, empty/error patterns), 013
  (`DataTable`, `Sidebar`/`SidebarNavItem`, `TopBar`), 017 (`/jobs/[id]/report` destination),
  019 (`GET /api/jobs` user-scoped)

Frontend paths relative to `frontend/`.

**Workflow reminders:**
- TDD (§7): tests written + confirmed FAILING before implementation.
- **Frontend-only** — no `backend/**`, no migration, no endpoint, no `types.ts`, no
  `app/graph/` change.
- Reach the backend only via `getApiClient()` (through `useJobs`) — no provider import in
  `components/history` (seam).
- The one intentional behavior change is **D1**: the "Contracts" nav goes to `/contracts` (the
  history list) instead of `/upload`; the `shell` nav test is updated, not weakened.
- NEVER `next build` while `next dev` runs. Stop dev first.

---

## Task 0: Branch
- [ ] From up-to-date `main`, create `feature/021-report-history` (`git-start`). Commit the 021
  `spec.md`/`plan.md`/`tasks.md` on the branch. (No constitution amendment.)

**Verify:** `git branch --show-current` → `feature/021-report-history`.

---

## Task 1: History helpers + view test (red)
- [ ] **[NEW] `src/lib/history.ts`** — pure helpers: `formatSubmitted(iso: string): string`
  (short local date/time), `riskTone(band?: string | null): BadgeTone`, and
  `overflowNote(fetched: number, total: number): string | null` (returns
  "Showing the most recent {fetched} of {total}." when `total > fetched`, else null).
- [ ] **[NEW] `src/__tests__/reportHistory.test.tsx`** — confirm FAILING (mock
  `@/lib/api/provider` with `makeFakeClient`; mock `next/navigation`; mock `next/link` to a
  plain `<a>` as other view tests do). Cover AC-1..8 + EC-5/6 (see Task 2 for the exact
  assertions). Build a **>20-item** `jobList` inline for the pagination case (the shared
  `jobListFixture` has only 3).

**Verify:** the test file imports the intended `ReportHistoryView` and fails (not yet built).

---

## Task 2: `ReportHistoryView` (green)
- [ ] **[NEW] `src/components/history/ReportHistoryView.tsx`** (`"use client"`) — build until the
  Task 1 test passes:
  - `const { state, retry } = useJobs({ limit: 100 })` — literal **100** (matches the backend
    `JOBS_LIST_MAX_LIMIT` clamp; do NOT import backend config).
  - **States:** `loading` → loading text/skeleton; `error` → message + **Try again** (`retry`,
    AC-8); `empty` (`total===0`) → an empty state with **Upload your first contract** CTA →
    `/upload` (AC-7); `loaded` → header + controls + table + pager.
  - **Header:** heading + **"Upload New Contract"** `Link href="/upload"` (primary button, AC-3).
  - **Search:** controlled input; filter `items` by `original_filename` (case-insensitive
    substring, AC-4); reset page to 0 on change; `filtered.length===0 && items.length>0` →
    "No contracts match" message (EC-5).
  - **Table:** `DataTable<JobListItem>` with columns — `Contract` (sortable; filename as a
    `Link` to `/jobs/{job_id}/report` when `report_available`, else text, truncated w/ `title`),
    `Submitted` (sortable via key `submitted_at`, rendered `formatSubmitted`), `Status`
    (`StatusBadge` tone map), `Risk` (completed → risk badge via `riskTone`; else `—`),
    `Findings` (completed → `H {high} · M {medium} · L {low}`; else `—`). `rowKey = r => r.job_id`.
  - **Row action** (`actions` slot): `report_available` → **View Report** `Link` →
    `/jobs/{job_id}/report` (AC-2); else muted hint ("Processing…"/"Failed"/"No report",
    EC-2/3/4).
  - **Pagination:** `pageSize=20`; slice `filtered` for the current page; Prev/Next + "A–B of
    {filtered.length}" shown only when `filtered.length > pageSize` (AC-6); clamp page.
  - **Overflow note:** `overflowNote(items.length, state.data.total)` when non-null (EC-6).
  - **Seam:** no provider import (AC-10).

**Verify:** `vitest run src/__tests__/reportHistory.test.tsx` → PASS.

---

## Task 3: Route
- [ ] **[MODIFY] `src/app/contracts/page.tsx`** — replace `redirect("/upload")` with
  `<><TopBar title="Contracts" /><ReportHistoryView /></>` (mirror `dashboard/page.tsx`).

**Verify:** `tsc --noEmit` clean; the page renders the view (covered by the view test + build).

---

## Task 4: Sidebar nav (D1)
- [ ] **[MODIFY] `src/components/shell/Sidebar.tsx`** — `NAV_ITEMS` "Contracts" `href`:
  `"/upload"` → `"/contracts"` (label/icon unchanged; still five items).
- [ ] **[MODIFY] `src/__tests__/shell.test.tsx`** — assert the Contracts nav item links to
  `/contracts` (`screen.getByText("Contracts").closest("a")` has `href="/contracts"`) and is
  `data-active` when `usePathname()==="/contracts"` (AC-9). Keep the five-items assertion.

**Verify:** `vitest run src/__tests__/shell.test.tsx` → PASS.

---

## Task 5: Boundary test
- [ ] **[NEW] `src/__tests__/history-boundary.test.ts`** — assert no `realProvider`/
  `mockProvider` import under `src/components/history` (model on `auth-boundary.test.ts`, AC-10).

**Verify:** `vitest run src/__tests__/history-boundary.test.ts` → PASS.

---

## Task 6: Full verification
- [ ] `vitest run` (whole frontend) GREEN; `tsc --noEmit` clean; `npm run lint` clean.
- [ ] Stop dev; `next build` succeeds.
- [ ] `pytest` (whole backend) still GREEN (no backend changes expected).
- [ ] `git diff --name-only main` — no `backend/**` file changed; no new endpoint/migration.

---

## Task 7: Live smoke (AC-11)
- [ ] Start `uvicorn` + `npm run dev` (provider `real`, per `.env.local`).
- [ ] Smoke: upload two contracts → open **Contracts** → both listed newest-first with correct
  status/risk; a completed one opens its **real** report; search filters by filename; a second
  account sees only **its own** history (019 isolation). Report the outcome.

---

## Task 8: Merge
- [ ] All frontend suites + `tsc` + `build` green; backend green; smoke noted.
- [ ] Rebase `main`, merge `feature/021-report-history`, delete branch (`git-finish`).

---

*Per §1/§11, implementation happens only on `feature/021-report-history`, opened after spec +
plan + tasks are approved. No backend deps, no migration.*
