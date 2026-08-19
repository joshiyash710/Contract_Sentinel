# Feature 043 — Technical plan: glass filter dropdown on the report-history page

Branch: `feature/043-glass-filter-dropdown` (per constitution §11).

Derived from `spec.md`. Frontend-only, presentation layer: harden the shared `Dropdown` primitive
(additive) and wire it into the two report-history filters, replacing native `<select>` elements. **No
backend / graph / `ContractState` / API / migration change.**

> The implementation already exists in `git stash@{0}` (a mixed stash whose backend half is already
> merged as feature 040). Take **only** the three frontend files; a small close-behavior test is added
> on top (see Task 3 / spec suggestion 2). All three files are byte-clean against the stash base
> (verified — the apply is conflict-free).

## 0. Scope of change (files touched)

Per **AC-6** the `git diff --name-only main` must show **exactly**:
```
frontend/src/components/ui/Dropdown.tsx
frontend/src/components/history/ReportHistoryView.tsx
frontend/src/__tests__/reportHistory.test.tsx
specs/043-glass-filter-dropdown/spec.md
specs/043-glass-filter-dropdown/plan.md
specs/043-glass-filter-dropdown/tasks.md
```
No other file — in particular **none of the mixed stash's backend files** (already merged) and no
change to `primitives.test.tsx` (its unchanged pass is the AC-3 back-compat guard).

## 1. `Dropdown.tsx` — additive hardening (from stash)

- Add optional prop **`ariaLabel?: string`** to `DropdownProps`; apply it to the trigger button as
  `aria-label={ariaLabel}`. All existing props/behaviors unchanged (D3 additive).
- Add a **close-on-outside-click / Escape** effect, attached only while `open`:
  ```tsx
  const rootRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const onPointer = (e: PointerEvent) => {
      if (rootRef.current && !rootRef.current.contains(e.target as Node)) setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") setOpen(false); };
    document.addEventListener("pointerdown", onPointer);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("pointerdown", onPointer);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);
  ```
  The root `<div>` gets `ref={rootRef}` (EC-4: listeners added only while open, removed on close/
  unmount by the cleanup).
- **Opaque open panel (D2):** the `<ul role="listbox">` uses the raised solid surface
  (`bg-card-raised`, themed `border-white/10`, `shadow-[var(--glass-shadow)]`, `z-30`) instead of the
  translucent `bg-card` fill, so the table behind does not bleed through. Selected option shows a
  `Check` icon and highlighted style; the chevron rotates when `open`.
- The `role="button"` trigger, `aria-haspopup="listbox"`, `aria-expanded`, and per-item
  `role="option"` + `aria-selected` are all preserved (D4) — this is exactly what keeps
  `primitives.test.tsx` green (AC-3) and satisfies AC-1/AC-5.

## 2. `ReportHistoryView.tsx` — use the primitive (from stash)

- `FilterSelect` renders `<Dropdown ariaLabel={label} value={value} options={options} onSelect={onChange} className="w-full sm:w-40" />` instead of the native `<select>` + `ChevronDown`.
- Remove the now-unused `ChevronDown` import; add the `Dropdown` import. `value`/`options`/`onChange`
  wiring and the filter semantics are unchanged (spec §2 — data behavior identical).

## 3. Tests

- **`reportHistory.test.tsx` (from stash):** the two filter tests drive the custom dropdown — open the
  trigger (`fireEvent.click(getByLabelText(/filter by risk|status/i))`) then pick the option
  (`fireEvent.click(getByRole("option", { name: "High"|"Failed" }))`) — replacing the old
  `fireEvent.change` on a native `<select>`. Asserts the same row visibility as before (AC-2).
- **New close-behavior test (spec suggestion 2, AC-5):** add ONE small test to `reportHistory.test.tsx`
  (or the same describe block) that opens a filter, asserts the `listbox` is present, then presses
  `Escape` (and/or a `pointerdown` outside the root) and asserts the `listbox` is gone. This makes AC-5
  an actual assertion rather than a purely visual claim. Reuse the existing render + queries; no new
  dependency.
- **`primitives.test.tsx`:** left UNCHANGED and must stay green (AC-3 back-compat).

## 4. Control-flow / correctness
- **Additive contract (D3):** `ariaLabel` optional ⇒ `primitives.test.tsx` (no `ariaLabel`) unaffected;
  the trigger/listbox/option roles are unchanged so both its and the report-history queries resolve.
- **No data change:** `useJobs`, columns, pagination, and the filter predicate are untouched; only the
  control's rendering + open/close behavior change.
- **Listener hygiene (EC-4):** effect guarded by `if (!open) return;` and cleaned up on close/unmount.
- **Blast radius:** on `main` the only other `Dropdown` consumer is `primitives.test.tsx`; the change
  is additive so no other surface regresses (EC-3).

## 5. Verification gate (all offline)
- `npm test` (vitest) — `reportHistory.test.tsx` (AC-1/2/5) + `primitives.test.tsx` (AC-3) + the full
  242+ suite green.
- `npx tsc --noEmit` — no type error (the new `ariaLabel` prop + `useEffect`/`useRef` typed).
- `npx eslint` (the project's lint script) — clean (no unused `ChevronDown`, exhaustive-deps ok).
- `npm run build` (`next build`) — compiles.

## 6. Risks / limitations
- **No arrow-key menu navigation** (Escape + click + outside-click only) — parity with the native
  `<select>` for this use; full keyboard nav is a later a11y enhancement (spec §6).
- **Only the report-history filters** are migrated; other native selects elsewhere are out of scope.
- Purely presentational — no data/route/API risk.

## 7. Merge
- Full FE gate green (test + tsc + eslint + build); `git diff --name-only main` matches the §0 six-path
  allow-list exactly (no stray backend/`primitives.test.tsx` change). Rebase `main`, merge
  `feature/043-glass-filter-dropdown`, delete branch (`git-finish`).
