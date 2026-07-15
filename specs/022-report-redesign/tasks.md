# Report Redesign ("Analysis Workspace") — Implementation Tasks

Reference documents:
- Spec: `specs/022-report-redesign/spec.md`
- Plan: `specs/022-report-redesign/plan.md`
- Constitution: `specs/000-constitution.md` (**no amendment**, **no backend change**)
- Consumed: 017 (`/jobs/[id]/report`, `ReportView`, `ReportHeader`, `SummaryStrip`, `RiskOverview`,
  `FindingCard`, `FindingRiskBadge`, `useReport`, `getApiClient` seam), 009 `ContractReport` DTO
  (`frontend/src/lib/api/types.ts`), test helpers (`_fakeClient.ts` `makeFakeClient` / `reportWith`,
  `fixtures.ts` `reportFixture` / `emptyReportFixture` / `ingestErrorReportFixture`)

Frontend paths relative to `frontend/`.

**Workflow reminders:**
- TDD (§7): tests written + confirmed FAILING before implementation.
- **Frontend-only** — no `backend/**`, no migration, no endpoint, no `types.ts`, no `app/graph/`
  change; `app/jobs/[jobId]/report/page.tsx` is UNCHANGED.
- Reach the backend only via `getApiClient()` (through `useReport`; `ReportHeader` for the download
  URLs) — no provider import anywhere in `components/report` (seam, AC-10).
- **Restyle only**: every 017 state branch (loading/redirecting/not_found/artifact_unavailable/
  error/ingest_error) is preserved unchanged; no 78/100 score, no Business Impact, no chat panel.
- The one sanctioned pre-existing-test change is **query scoping** in `report.test.tsx` (the rail now
  also shows clause titles) — assertions are re-targeted, never weakened.
- NEVER `next build` while `next dev` runs. Stop dev first.

---

## Task 0: Branch
- [ ] From up-to-date `main`, create `feature/022-report-redesign` (`git-start`). Commit the 022
  `spec.md`/`plan.md`/`tasks.md` on the branch. (No constitution amendment.)

**Verify:** `git branch --show-current` → `feature/022-report-redesign`.

---

## Task 1: Workspace test (red)
- [ ] **[NEW] `src/__tests__/report-workspace.test.tsx`** — confirm FAILING. Mock like
  `report.test.tsx`: `vi.mock("@/lib/api/provider", () => ({ getApiClient: vi.fn() }))`,
  `vi.mock("next/navigation", …)`, and in `beforeEach` reset mocks. Stub the missing jsdom API:
  `Element.prototype.scrollIntoView = vi.fn()`. Render `<AnalysisWorkspace jobId="job-1"
  report={reportFixture} />` directly (it takes the already-fetched report as a prop — no
  `useReport`), or render `<ReportView jobId="job-1"/>` with `makeFakeClient({})`. Cover:
  - **AC-1 two-pane:** exactly one `nav-clause` entry per finding **and** one `finding-card` per
    finding (`reportFixture` has 4). Assert an "AI Analysis Panel" region (`getByTestId(
    "analysis-panel")`) and a navigator (`getByTestId("clause-navigator")`) both render.
  - **AC-3 nav entries:** `getAllByTestId("nav-clause")` are in `findings` order and each shows the
    finding title (`Limitation Of Liability`, `Indemnification`, `Governing Law`, `Clause 4`) and,
    when present, the `§` locator. The risk indicator exposes its level via `aria-label`/`title`
    (NOT visible "High risk"/"Severity unavailable" text — see Task 5 collision note).
  - **AC-4 nav→focus:** clicking the 2nd `nav-clause` sets it `data-active` (or `aria-current`) and
    expands the matching card (`aria-expanded="true"` on the card whose title is "Indemnification",
    scoped `within(panel)`); clicking the 3rd moves the active state off the 2nd.
  - **AC-6 compare:** the 1st finding (`rewritten`) shows a **Compare** control; clicking it renders
    `getByTestId("clause-compare")` containing BOTH the original clause text and the suggested
    rewrite text.
  - **AC-7 no-compare:** the 2nd (`unavailable`) and 3rd (`not_eligible`) findings show **no**
    Compare control (query within each card).
  - **AC-8 empty:** with `makeFakeClient({ report: emptyReportFixture })` (0 findings) → the panel
    shows "No risky clauses found" and the navigator shows an empty hint; `queryAllByTestId(
    "nav-clause")` is empty.
  - **AC-11 no chat:** `queryByText(/legal ai assistant/i)` is null and there is no chat message
    `textbox`/input.

**Verify:** the test imports the intended `AnalysisWorkspace` / `ClauseNavigator` and fails
(components not yet built).

---

## Task 2: `ClauseNavigator` (green)
- [ ] **[NEW] `src/components/report/ClauseNavigator.tsx`** (`"use client"`):
  - Props: `{ findings: ReportFinding[]; activeId: string | null; onSelect: (clauseId: string) =>
    void }`.
  - Root `data-testid="clause-navigator"` with a small "Flagged clauses" label + `{findings.length}
    findings` count.
  - `findings.length === 0` → a muted "No flagged clauses" hint (AC-8); no entries.
  - Else map each finding to a `<button data-testid="nav-clause" onClick={()=>onSelect(f.clause_id)}`
    showing the `position`/index, `findingTitle(f)` (reuse `@/lib/reportFormat`), `§ {section_number}`
    when present, and a **risk dot** colored by `f.risk_level` (high/medium/low; neutral when null).
    The dot's level is conveyed with `aria-label`/`title` (e.g. `"High risk"`), NOT visible band
    text. `aria-current="true"` + `data-active` when `activeId === f.clause_id`.
  - Independently scrollable container (`overflow-y-auto`, sticky top on `lg`).
  - No provider import (AC-10).

**Verify:** `tsc --noEmit` clean for this file; used by Task 3.

---

## Task 3: `AnalysisWorkspace` (green)
- [ ] **[NEW] `src/components/report/AnalysisWorkspace.tsx`** (`"use client"`) — build until the
  Task 1 test passes:
  - Props: `{ jobId: string; report: ContractReport }`.
  - **State:** `openIds: Set<string>` seeded with `report.findings[0]?.clause_id` (mirrors today's
    `defaultOpen={i===0}`); `activeId: string | null`. Keep a `refs` map
    (`Record<string, RefObject<HTMLDivElement>>`) keyed by `clause_id`.
  - **Top zone (full width):** an "Analysis Workspace" eyebrow, then `<ReportHeader jobId={jobId}
    report={report} />` (unchanged — filename, derived band, downloads, meta) and
    `<SummaryStrip summary={report.summary} />`.
  - **No findings** (`report.findings.length === 0`): render the "No risky clauses found" panel
    (move the exact block from `ReportView`) full width, plus `<ClauseNavigator findings={[]}
    activeId={null} onSelect={()=>{}} />` (shows its empty hint). Do NOT render the two-pane grid.
  - **Has findings:** a responsive grid `grid gap-6 lg:grid-cols-[minmax(0,18rem)_1fr]` (single
    column below `lg`, D7): left `<ClauseNavigator findings activeId onSelect={handleSelect} />`;
    right a `<section data-testid="analysis-panel" aria-label="AI Analysis Panel">` containing
    `<RiskOverview summary={report.summary} />` then `report.findings.map` of a wrapper
    `<div id={anchorId(f.clause_id)} ref={refs[f.clause_id]}>` around
    `<FindingCard finding={f} open={openIds.has(f.clause_id)} onToggle={()=>toggle(f.clause_id)}
    active={activeId === f.clause_id} />`.
  - **`handleSelect(id)`:** `setActiveId(id)`; add `id` to `openIds`;
    `refs[id]?.current?.scrollIntoView?.({ behavior:"smooth", block:"start" })` (optional-chained).
  - **`toggle(id)`:** flip membership in `openIds` (and it may set `activeId=id` on open).
  - No provider import; `ReportHeader` already owns the `getApiClient()` download URLs (AC-10).

**Verify:** `vitest run src/__tests__/report-workspace.test.tsx` → the two-pane / nav / empty / chat
assertions PASS (compare comes with Task 4).

---

## Task 4: `FindingCard` — controlled open + `active` + Compare (green)
- [ ] **[MODIFY] `src/components/report/FindingCard.tsx`** — additive, backward-compatible:
  - Add optional props `open?: boolean`, `onToggle?: () => void`, `active?: boolean`. When `open` is
    provided, the card is **controlled**: use `open` for expansion and call `onToggle` from the
    header button; when omitted, fall back to the existing `useState(defaultOpen)` (existing
    standalone behavior preserved). `active` adds a highlight (`ring-1 ring-accent/40`).
  - **Compare toggle (AC-6):** inside the existing rewrite section — only when `rewrite_state ===
    "rewritten" && suggested_rewrite` — keep the current stacked "Suggested rewrite" block
    (`data-testid="rewrite-block"`, so 017 assertions still pass) and add a **"Compare"** toggle
    button (local `useState(false)`). When on, render a side-by-side block
    `data-testid="clause-compare"` (`grid gap-3 sm:grid-cols-2`): left "Original" = `clause_text`,
    right "Suggested" = `suggested_rewrite`; each column wraps/scrolls independently (EC-5).
  - Findings with `rewrite_state` of `unavailable` (keep the "couldn't be generated" note) or
    `not_eligible` (no rewrite block) show **no** Compare control (AC-7 / EC-2).
  - Everything else (AI Explanation, Text + "show full clause", evidence, confidence, risk badge,
    accent stripe) is UNCHANGED — same markup/testids; no "Business Impact" (AC-2/D5).

**Verify:** `vitest run src/__tests__/report-workspace.test.tsx` → compare assertions (AC-6/7) PASS.

---

## Task 5: Wire `ReportView` + fix `report.test.tsx` scoping
- [ ] **[MODIFY] `src/components/report/ReportView.tsx`** — replace ONLY the loaded happy-path block
  (the `<div className="mx-auto max-w-5xl …">` with `ReportHeader`/`SummaryStrip`/`RiskOverview`/
  findings/empty-state) with `return <AnalysisWorkspace jobId={jobId} report={report} />;`. Leave
  the `IngestErrorPanel` branch and every state branch (`loading`, `redirecting` →
  `router.replace('/jobs/{jobId}')`, `not_found`, `artifact_unavailable`, `error` + `retry`)
  byte-for-byte unchanged (AC-9).
- [ ] **[MODIFY] `src/__tests__/report.test.tsx`** — the rail now also shows clause titles/risk;
  re-target (do NOT weaken) the colliding queries:
  - Add `Element.prototype.scrollIntoView = vi.fn()` (jsdom lacks it) in setup.
  - Introduce `const panel = () => screen.getByTestId("analysis-panel")` and change the `expandCard`
    helper to scope: `within(panel()).findByRole("button", { name: title })` (the rail entry is also
    a button carrying the title).
  - Scope card-level `getByText` to the panel: e.g. line ~103
    `within(panel()).getByText("Governing Law").closest("[data-testid='finding-card']")`.
  - Leave header-level assertions as-is: `getByText("High risk")`, `getByText(/1 high · 1 medium · 1
    low across 12 clauses/)`, `queryByText(/\/100/)`, `getByText(/severity unavailable/i)`,
    `queryByText(/business impact/i)` — these must still resolve **uniquely**, which holds because
    the rail uses `aria-label`/`title` (not visible band text) for risk (Task 2). If any becomes
    ambiguous, fix the RAIL to not emit that visible text — do not loosen the assertion.
  - `findAllByTestId("finding-title")` stays = 4 (rail uses `nav-clause`).

**Verify:** `vitest run src/__tests__/report.test.tsx src/__tests__/report-workspace.test.tsx` →
both PASS.

---

## Task 6: Full verification
- [ ] `vitest run` (whole frontend) GREEN; `tsc --noEmit` clean; `npm run lint` clean.
- [ ] `report-boundary.test.ts` (unchanged) still GREEN — the two new `components/report` files have
  no `realProvider`/`mockProvider` import (AC-10).
- [ ] Stop dev; `next build` succeeds.
- [ ] `pytest` (whole backend) still GREEN (no backend changes expected).
- [ ] `git diff --name-only main` — no `backend/**`, no `types.ts`, no `app/graph/**`, no
  `app/jobs/[jobId]/report/page.tsx` change.

---

## Task 7: Live smoke (AC-12)
- [ ] Start `uvicorn` + `npm run dev` (provider `real`, per `.env.local`).
- [ ] Smoke: open a real completed report → **two-pane Analysis Workspace** renders with the real
  filename, real flagged clauses in the navigator, real AI explanations + clause text; clicking a
  navigator entry focuses/expands its card; **Compare** on a rewritten clause shows the before/after;
  Markdown + JSON downloads work; a non-terminal job still redirects to `/jobs/{id}`. Report the
  outcome.

---

## Task 8: Merge
- [ ] All frontend suites + `tsc` + `build` green; backend green; smoke noted.
- [ ] Rebase `main`, merge `feature/022-report-redesign`, delete branch (`git-finish`).

---

*Per §1/§11, implementation happens only on `feature/022-report-redesign`, opened after spec +
plan + tasks are approved. No backend deps, no migration.*
