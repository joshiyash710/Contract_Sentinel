# Report Redesign ("Analysis Workspace") — Technical Plan

## Git Branch

`feature/022-report-redesign` — branching workflow per `specs/000-constitution.md` §11.

---

## 1. Overview

Implements `specs/022-report-redesign/spec.md` (phase 3 of 3) — **frontend-only**. Restyles the
existing report screen (`/jobs/[jobId]/report`, feature 017) into the **"Analysis Workspace"** of
design ref screen 6: a full-width header, an honest risk snapshot, and a **two-pane clause zone** —
a left **Flagged-clauses navigator** rail that drives a main **AI Analysis Panel** of expandable
finding cards, each with an AI explanation, the clause text, and a **before/after Compare** of the
original clause vs. its suggested rewrite.

Built entirely on the pieces 017 already ships (`useReport`, `getApiClient()` seam, `ReportHeader`,
`SummaryStrip`, `RiskOverview`, `FindingCard`, `FindingRiskBadge`, and the `deriveRiskBand` /
`countsLine` / `findingTitle` helpers). **No backend, endpoint, graph, `ContractState`, `types.ts`,
or migration change.** It consumes the same serialized 009 `ContractReport` DTO; no new field names
(spec §2.1, constitution §4).

**Cut from the mockup (spec D3/D4/D5):** the "Legal AI Assistant" chat column, the `78/100` numeric
score, and "Business Impact" — none are built. The workspace is **two-pane, not three**.

---

## 2. Files to Create / Modify

### Frontend (`frontend/`)
```
src/components/report/AnalysisWorkspace.tsx  [NEW]    two-pane layout: header zone + <ClauseNavigator> | analysis panel of <FindingCard>s; owns openIds/activeId + scroll-to-card
src/components/report/ClauseNavigator.tsx    [NEW]    left rail: one entry per finding (title, §, risk dot); click → focus card; empty hint when no findings
src/components/report/FindingCard.tsx        [MODIFY] optional controlled open/onToggle + `active` highlight; add Compare toggle (stacked ↔ side-by-side before/after). All existing content/testids preserved
src/components/report/ReportView.tsx         [MODIFY] swap the loaded-happy-path block to render <AnalysisWorkspace/>; ALL state branches (loading/redirecting/not_found/artifact_unavailable/error/ingest_error) unchanged

src/__tests__/report.test.tsx                [MODIFY] scope finding-card queries to the analysis panel (nav rail now also shows titles); add nav-focus (AC-4) + compare (AC-6) + no-chat (AC-11) cases
src/__tests__/report-workspace.test.tsx      [NEW]    two-pane render (AC-1), navigator entries (AC-3), nav→card focus (AC-4), compare toggle (AC-6/7), empty-state rail hint (AC-8), no-chat (AC-11)
src/__tests__/report-boundary.test.ts        [—]      UNCHANGED — already greps all of components/report/** for provider imports; the two new files are covered automatically (AC-10)
```

No `backend/**` change; no new endpoint; no `types.ts` change (the 009 DTO already has every field);
no `app/graph/**` change. `app/jobs/[jobId]/report/page.tsx` is **unchanged** (still renders
`<ReportView/>`).

---

## 3. Frontend design

> **Client/server (§8).** All report components are already client components; `AnalysisWorkspace`
> and `ClauseNavigator` are client (`useState`, refs). No server-component or data-fetching change —
> `ReportView` still owns the single `useReport(jobId)` call.

### 3.1 `ReportView.tsx` (MODIFY — minimal)
Only the **loaded, non-error, has-report** branch changes. Every other branch is byte-for-byte the
same (spec AC-9): `loading`, `redirecting` (→ `router.replace('/jobs/{jobId}')`), `not_found`,
`artifact_unavailable`, `error` + `retry`, and `IngestErrorPanel`. The current happy path
(`ReportHeader` + `SummaryStrip` + `RiskOverview` + the `findings.map(FindingCard)` / empty state)
is replaced by a single:
```tsx
return <AnalysisWorkspace jobId={jobId} report={report} />;
```
The no-findings empty state moves **into** `AnalysisWorkspace` (so the workspace owns both the
populated and empty happy-path layouts).

### 3.2 `AnalysisWorkspace.tsx` (NEW)
- **Props:** `{ jobId: string; report: ContractReport }`.
- **Top zone (full width):** reuses `<ReportHeader jobId report/>` (filename, derived band pill +
  counts, generated-at/OCR meta, Markdown+JSON downloads — spec AC-2/D8, no score) then
  `<SummaryStrip summary/>`. An `eyebrow` "Analysis Workspace" label is added above the header title
  (small change to `ReportHeader` copy, or rendered by the workspace above it — keep in the
  workspace to leave `ReportHeader` API stable).
- **Clause zone:**
  - **No findings** → render the existing "No risky clauses found" panel (moved from `ReportView`)
    across the full width, and render `<ClauseNavigator findings={[]} …/>` collapsed to its empty
    hint (spec AC-8 / EC-1). `RiskOverview` is omitted here (it already self-hides with no graded
    findings).
  - **Has findings** → a responsive **two-pane grid** (`grid lg:grid-cols-[minmax(0,18rem)_1fr]`,
    single column below `lg` — spec D7/EC-7): left `<ClauseNavigator/>` (sticky, own scroll), right
    the **AI Analysis Panel**: `<RiskOverview summary/>` (reused, honest donut) followed by the
    `findings.map` of `<FindingCard/>`. Each card is wrapped in
    `<div id={anchorId(clause_id)} ref=…>` for scroll targeting.
- **Focus state (spec AC-4):** owns `openIds: Set<string>` (seeded with the first finding's
  `clause_id`, mirroring today's `defaultOpen={i===0}`) and `activeId: string | null`. A navigator
  click → `setActiveId(id)`, add `id` to `openIds`, and
  `refs[id].current?.scrollIntoView?.({ behavior:"smooth", block:"start" })` (optional-chained so
  jsdom's missing `scrollIntoView` is a no-op — see §6). The card for `activeId` gets `active` (ring
  highlight); its nav entry gets `data-active`.
- **Card open state:** each `<FindingCard open={openIds.has(id)} onToggle={…}/>` is **controlled** by
  the workspace, so both the card's own chevron and the navigator toggle the same state.
- **Seam:** no provider import; `ReportHeader` already calls `getApiClient()` for the download URLs
  (unchanged). `AnalysisWorkspace`/`ClauseNavigator` touch no client at all (AC-10).

### 3.3 `ClauseNavigator.tsx` (NEW)
- **Props:** `{ findings: ReportFinding[]; activeId: string | null; onSelect: (clauseId:string)=>void }`.
- **Header:** a small "Flagged clauses" / "Contents" label + count (`{n} findings`).
- **Entries:** `findings.map` → a `<button>` per finding showing an index/`position`, the
  `findingTitle(f)` (reused helper — `clause_type` title-cased or `Clause {position}` fallback,
  EC-3), the `§ section_number` when present, and a **risk dot** colored by `risk_level`
  (high/medium/low; neutral when null — EC-3). `onClick={() => onSelect(f.clause_id)}`;
  `aria-current`/`data-active` when `activeId === f.clause_id`. **testid `nav-clause`** — deliberately
  NOT `finding-title` so the panel's `finding-title` count stays = number of cards (§5 test note).
- **Empty:** `findings.length === 0` → a muted "No flagged clauses" hint (spec AC-8), never a blank
  rail.
- Independently scrollable (`overflow-y-auto`, sticky top) so a long report doesn't push the panel
  (EC-6).

### 3.4 `FindingCard.tsx` (MODIFY — additive, backward-compatible)
1. **Controllable open:** add optional `open?: boolean` + `onToggle?: () => void` and `active?:
   boolean`. When `open` is passed, the card is controlled (header button calls `onToggle`); when
   omitted it falls back to today's internal `useState(defaultOpen)` — so the component stays usable
   standalone. `active` adds a ring/border highlight (`ring-1 ring-accent/40`).
2. **Compare toggle (spec AC-6):** in the rewrite section (only when `rewrite_state === "rewritten"
   && suggested_rewrite`), keep the existing stacked "Suggested rewrite" block as the default, and
   add a **"Compare"** toggle button. When on, render a **side-by-side** two-column block
   (`grid sm:grid-cols-2`): **Original** = `clause_text`, **Suggested** = `suggested_rewrite`
   (`data-testid="clause-compare"`); each column wraps/scrolls independently (EC-5). Default (off)
   keeps `data-testid="rewrite-block"` visible, so existing 017 rewrite assertions still pass. A
   finding with no rewrite (`unavailable` / `not_eligible`) shows **no** Compare button (spec AC-7 /
   EC-2) — `unavailable` keeps its "couldn't be generated" note.
3. Everything else (AI Explanation from `risk_rationale`, `Text` = `clause_text` with "show full
   clause", evidence list, confidence, risk badge, accent stripe) is **unchanged** — same markup and
   testids, so no fabricated "Business Impact" appears (spec AC-2/D5).

### 3.5 What is explicitly NOT added
No chat/assistant UI, no message input, no `78/100` score element, no "Business Impact" copy, no new
download formats, no full-document text pane, no generate-on-demand rewrite (spec §6, AC-11).

---

## 4. Tests mapped to acceptance criteria

**Frontend (Vitest + RTL; mock/fake provider via `makeFakeClient` + `getReport` fixture).** The mock
`reportFixture` already contains a `rewritten` finding (Compare), an `unavailable`, and two
`not_eligible` — covering AC-6/AC-7 without new fixtures.

- **`report-workspace.test.tsx` (NEW):**
  - two-pane render: a `ClauseNavigator` (`nav-clause` entries) **and** an analysis panel
    (`finding-card`s), one of each per finding (AC-1); nav entries in `findings` order with title/§/
    risk indicator (AC-3).
  - **nav→focus:** clicking a `nav-clause` marks it `data-active` and expands the matching card
    (`aria-expanded=true`); selecting another moves the active state (AC-4). (`Element.prototype.
    scrollIntoView` stubbed to a no-op in the test — jsdom lacks it.)
  - **compare:** the `rewritten` finding shows a **Compare** button; clicking renders
    `clause-compare` with both the original clause text and the suggested rewrite (AC-6). The
    `unavailable` / `not_eligible` findings show **no** Compare button (AC-7).
  - **empty:** `emptyReportFixture` (0 findings) → "No risky clauses found" in the panel + navigator
    empty hint, no `nav-clause` entries (AC-8 / EC-1).
  - **no chat:** no element matching `/legal ai assistant/i` or a chat message input is rendered
    (AC-11).
- **`report.test.tsx` (MODIFY):** existing 017 assertions preserved but **scoped** — card-level
  `getByText` (e.g. "Governing Law", clause text) resolved `within(analysisPanel)` (or by
  `finding-card`) since the nav rail now also shows titles; add nothing that weakens an assertion.
  The header/band/OCR/ingest-error/not-found/artifact/redirect tests are unchanged (those branches
  didn't move).
- **`report-boundary.test.ts` (UNCHANGED):** already walks `components/report/**`; the two new
  components are covered — no direct `realProvider`/`mockProvider` import (AC-10).
- **No-backend-change** half of AC-10 verified in §5 via `git diff --name-only main` showing no
  `backend/**`.

**Live smoke (AC-12):** `provider=real`; open a real completed report → two-pane workspace with real
filename, real flagged clauses in the navigator, real explanations/clause text, a working
before/after Compare on a rewritten clause; Markdown/JSON downloads work; a non-terminal job still
redirects to `/jobs/{id}`.

---

## 5. Implementation order (TDD — §7)

1. **Workspace test (red):** write `report-workspace.test.tsx` against the intended
   `AnalysisWorkspace` / `ClauseNavigator` API (two-pane, nav-focus, compare, empty, no-chat).
2. **Navigator + workspace (green):** build `ClauseNavigator`, then `AnalysisWorkspace`
   (header zone + two-pane + openIds/activeId + scroll) until the new test passes; reuse
   `ReportHeader`/`SummaryStrip`/`RiskOverview`/`FindingCard`.
3. **FindingCard (green):** add controlled `open`/`onToggle` + `active` + the Compare toggle; keep
   all existing testids/markup so unmodified assertions still pass.
4. **Wire ReportView:** replace the happy-path block with `<AnalysisWorkspace/>`; confirm every
   other state branch is untouched.
5. **Fix `report.test.tsx`:** scope the card-level queries (nav duplication); confirm the whole 017
   suite is green again — no assertion weakened (the query scoping is a layout-driven update, §7).
6. **Verify:** `vitest run` (whole FE suite) GREEN; `tsc --noEmit`, `npm run lint`, `next build`
   (with `next dev` STOPPED). Backend untouched — run `pytest` once to confirm still green (no
   changes expected). `git diff --name-only main` shows no `backend/**` and no `types.ts`.
7. **Live smoke (AC-12).** `.env.local` stays as the user set it.

Each step's tests are written failing first (§7). The one sanctioned pre-existing-test change is the
**query scoping in `report.test.tsx`** (the layout legitimately gained a second place that shows
clause titles) — assertions are re-targeted, never removed or loosened.

---

## 6. Notes / risks

- **`scrollIntoView` in jsdom:** not implemented — call it optional-chained
  (`ref.current?.scrollIntoView?.(…)`) and stub `Element.prototype.scrollIntoView` in the
  nav-focus test. The focus behavior's *observable* assertions are `data-active` + `aria-expanded`,
  not the scroll itself.
- **Nav/card title duplication (concrete breakages in `report.test.tsx`):** the rail adds a second
  place that shows clause titles + risk, colliding with three existing query styles unless handled:
  (a) `getAllByTestId("finding-title")` — rail uses `data-testid="nav-clause"` (not `finding-title`),
  so the count stays = number of cards; (b) `getByText("Governing Law").closest(...)` and the
  `expandCard` helper's `findByRole("button", { name: title })` — **scope to the analysis panel**
  (`within(panel)` where `panel = getByTestId("analysis-panel")`), since the rail entry is also a
  button carrying the title; (c) `getByText("High risk")` / `getByText(/severity unavailable/i)` on
  the header band — the rail's risk indicator must expose its level via **`aria-label`/`title`
  (a colored dot), not visible band text**, so no second text match is created. This is the single
  most likely source of test breakage — handled explicitly in step 5.
- **Controlled vs. uncontrolled `FindingCard`:** the `open`/`onToggle` props are optional; existing
  standalone/`defaultOpen` usage is preserved, so only `AnalysisWorkspace` opts into control. Keep
  the fallback so the component never becomes render-broken when `open` is absent.
- **`RiskOverview` placement:** it self-hides when there are no graded findings, so putting it atop
  the analysis panel is safe for all-null-severity reports (no fake donut). No change to its code.
- **Responsive:** two-pane only at `lg+`; below that it is a single column (rail above panel) — no
  horizontal scroll (D7/EC-7). Long rail/panel scroll independently (EC-6).
- **`next build` vs `next dev`:** never build while dev runs; step 6 builds with dev stopped.
- **Out-of-scope discipline:** no chat, no numeric score, no Business Impact, no full-document pane,
  no contract-to-contract compare, no new endpoint/field — all per spec §6.

---

*Per §1/§11, a `feature/022-report-redesign` branch opens only after this plan.md + spec.md are
approved and `tasks.md` exists. No backend deps, no migration. No `tasks.md`/implementation in this
pass — plan only.*
