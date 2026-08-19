# Feature 043 — Glass filter dropdown on the report-history page

Branch: `feature/043-glass-filter-dropdown` (per constitution §11).

## 1. Problem statement

The report-history / contracts page (`ReportHistoryView`, spec 021) filters by **Risk** and **Status**
using native HTML `<select>` elements. A native `<select>`'s open option list is rendered by the
**operating system**, so it appears as the browser's opaque white/blue popup — visually inconsistent
with the app's frosted-glass dark theme (the visual-consistency bar: one premium look across every
surface). The app already ships a themed `Dropdown` primitive (`components/ui/Dropdown.tsx`), but it is
not wired into these filters and is currently missing the small behaviors a native `<select>` gave for
free (accessible name when there is no visible `<label>`, close-on-outside-click / Escape), and its
open panel is translucent enough that the table behind it can bleed through.

This feature (a) hardens the shared `Dropdown` primitive and (b) uses it for the two report-history
filters, so the filter menus match the app theme instead of the OS popup.

### Position relative to the constitution
**Frontend-only, presentation layer.** No backend, no graph/node/edge, no `ContractState`, no API/
schema, no migration. It refines an existing spec-021 UI surface and an existing shared primitive; per
§1/§11 it is developed on `feature/043-glass-filter-dropdown`. Behavior of the data (which rows show
for a given filter value) is **unchanged** — only the control's rendering and its open/close
interaction change.

## 2. Inputs and outputs

- **`Dropdown` primitive (`components/ui/Dropdown.tsx`)** gains:
  - an optional **`ariaLabel`** prop applied to the trigger button (accessible name when the caller
    has no visible `<label>` — the filters label via `aria-label`, not a `<label for>`);
  - **close-on-outside-click and close-on-Escape** (a native `<select>` closed automatically; the
    custom menu must too);
  - a **fully opaque** open panel (raised surface, not the translucent glass fill) so the table behind
    it does not show through, plus a selected-option affordance (a check mark) and a chevron that
    rotates when open.
  - Its public contract is **additive**: existing props (`options`, `value`, `onSelect`,
    `placeholder`, `className`) and the `role="button"` trigger / `role="listbox"` +
    `role="option"` structure are unchanged; `ariaLabel` is optional.
- **`ReportHistoryView` (`components/history/ReportHistoryView.tsx`)**: the internal `FilterSelect`
  helper renders the themed `Dropdown` (passing `ariaLabel={label}`) instead of a native `<select>`;
  same `value` / `options` / `onChange` wiring, same filter semantics.
- **No output/data change:** the filtering logic, `useJobs` seam, table, and results are identical.

## 3. Resolved decisions (inline)

- **D1 — Reuse the existing `Dropdown` primitive**, do not fork a page-local one. The filters and the
  existing primitive should be the same component so the whole app has one dropdown look/behavior.
- **D2 — Opaque panel, not translucent glass.** The menu overlays a data table; a see-through panel is
  unreadable. Use the raised solid surface with a themed border + shadow to keep the glass feel while
  staying opaque.
- **D3 — `ariaLabel` is opt-in and additive.** Existing callers (and `primitives.test.tsx`) pass no
  `ariaLabel` and must keep working; the filters pass it because they have no visible `<label>`.
- **D4 — Accessibility parity with the native `<select>` it replaces:** keyboard Escape + outside-click
  close, `aria-haspopup="listbox"`, `aria-expanded`, `role="option"` + `aria-selected`. No regression
  in the a11y the native control provided.
- **D5 — Frontend-visual-only.** No new dependency, no data/route/API change; purely the control's
  presentation + open/close behavior.

## 4. Acceptance criteria

### Frontend (vitest + tsc + lint + build — all offline)
- **AC-1 (filters use the themed dropdown):** on the report-history page, the Risk and Status filters
  render the custom `Dropdown` (a `role="button"` trigger opening a `role="listbox"`), **not** a native
  `<select>`.
- **AC-2 (filter semantics unchanged):** opening the Risk filter and choosing **High** shows only
  high-risk rows and hides the others; opening the Status filter and choosing **Failed** shows only
  failed rows — i.e. `reportHistory.test.tsx`'s filter tests pass against the new interaction
  (click trigger → click option).
- **AC-3 (primitive back-compat):** `primitives.test.tsx`'s `dropdown_select` (no `ariaLabel`, click
  trigger → click "Low" → `onSelect("lo")`) still passes unchanged — the `Dropdown` contract is
  additive.
- **AC-4 (accessible name):** each filter's trigger button exposes an accessible name (the `label`
  prop passed through as `aria-label` — "Filter by risk" / "Filter by status", matched
  case-insensitively) so it is reachable by `getByLabelText` / assistive tech.
- **AC-5 (close behavior):** the open menu closes on outside pointer-down and on Escape.
- **AC-6 (no architecture change):** `git diff main` touches only the three frontend files
  (`Dropdown.tsx`, `ReportHistoryView.tsx`, `reportHistory.test.tsx`) + the `specs/043-**` docs — no
  backend, graph, state, API, migration change. `npm test`, `tsc --noEmit`, `eslint`, and
  `next build` all pass.

## 5. Edge cases
- **EC-1 — No visible `<label>`:** the filters rely on `ariaLabel`; without it the trigger would be an
  unnamed button (AC-4 guards this).
- **EC-2 — Menu over the table:** opaque panel (D2) prevents bleed-through (visual; not unit-asserted
  beyond the class, but covered by the opaque-surface class in the component).
- **EC-3 — Other `Dropdown` consumers:** on `main` the only other consumer is `primitives.test.tsx`;
  the additive change keeps it green (AC-3). Any future consumer inherits the improved behavior.
- **EC-4 — Rapid open/close / unmount:** the outside-click/Escape listeners are attached only while
  open and removed on close/unmount (no leaked listeners).

## 6. Out of scope
- Restyling dropdowns/selects elsewhere in the app (only the report-history filters are wired here;
  other surfaces can adopt the primitive later).
- Full keyboard **arrow-key navigation** within the menu (Escape + click + outside-click only) — a
  possible later a11y enhancement, not required to reach parity with the native `<select>` for this use.
- Any change to filter logic, columns, pagination, or the `useJobs` data seam.

## 7. Evaluation (metrics to log)
Deterministic frontend tests only (no harness/eval): the updated `reportHistory.test.tsx` filter tests
(AC-1/AC-2) and the unchanged `primitives.test.tsx` `dropdown_select` (AC-3), plus the standard gate
(`tsc --noEmit`, `eslint`, `next build`). No probabilistic measurement.

## 8. Notes for plan.md / tasks.md (pointers)
- **Files:** `components/ui/Dropdown.tsx` (additive `ariaLabel` + outside-click/Escape `useEffect` +
  opaque panel/Check/rotate), `components/history/ReportHistoryView.tsx` (`FilterSelect` → `Dropdown`),
  `__tests__/reportHistory.test.tsx` (drive the custom dropdown: click trigger → click option).
- The implementation exists in `git stash@{0}` (a mixed stash whose backend half is already merged as
  feature 040); take **only** these three frontend files from it.
- **Tests:** keep `primitives.test.tsx` unchanged and green (back-compat guard, AC-3).
