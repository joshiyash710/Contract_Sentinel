# Feature 043 — Glass filter dropdown — Implementation Tasks

Reference documents:
- Spec: `specs/043-glass-filter-dropdown/spec.md`
- Plan: `specs/043-glass-filter-dropdown/plan.md`
- Constitution: `specs/000-constitution.md` (**§1/§11** branch-gated frontend change; **§7** TDD /
  never weaken a test)

Frontend paths relative to `frontend/`.

**Workflow reminders:**
- **Frontend-only, presentation layer.** No backend, graph, `ContractState`, API, or migration change.
- **Scope is exactly 6 paths (AC-6).** `git diff --name-only main` must show only
  `src/components/ui/Dropdown.tsx`, `src/components/history/ReportHistoryView.tsx`,
  `src/__tests__/reportHistory.test.tsx`, and the three `specs/043-**` docs.
- **The implementation is in `git stash@{0}`** (a mixed stash whose backend half is already merged as
  feature 040). Take **ONLY** the three frontend files above; the backend files and any other stash
  content must NOT be applied.
- **`primitives.test.tsx` stays UNCHANGED and green** — its `dropdown_select` test is the AC-3
  additive-back-compat guard. Do not modify it.
- `ChevronLeft`/`ChevronRight` (the pager icons in `ReportHistoryView`) stay; only `ChevronDown`
  becomes unused in `FilterSelect` and is removed from that file's imports.

---

## Task 0: Branch
- [x] From up-to-date `main`, create `feature/043-glass-filter-dropdown`. Commit the
  `spec.md`/`plan.md`/`tasks.md` on the branch (each spec-reviewer-APPROVED before proceeding).

**Verify:** `git branch --show-current` → `feature/043-glass-filter-dropdown`.

---

## Task 1: Apply the 3 frontend files from the stash  [AC-1, AC-2, AC-4]
- [ ] From the branch, extract ONLY these three files from `stash@{0}`
  (`git checkout stash@{0} -- <path>` per file):
  - `src/components/ui/Dropdown.tsx` — additive `ariaLabel?` prop → trigger `aria-label`;
    close-on-outside-click/Escape `useEffect` (attached only while open, cleaned up on close/unmount);
    opaque open panel (`bg-card-raised`, themed border/shadow, `z-30`), selected `Check`, rotating
    chevron. Existing props + `role="button"`/`listbox`/`option` structure preserved.
  - `src/components/history/ReportHistoryView.tsx` — `FilterSelect` renders `<Dropdown ariaLabel={label} … />` instead of the native `<select>`; drop the now-unused `ChevronDown` import (keep
    `ChevronLeft`/`ChevronRight`), add the `Dropdown` import.
  - `src/__tests__/reportHistory.test.tsx` — the Risk/Status filter tests drive the custom dropdown
    (click trigger via `getByLabelText(/filter by risk/i)` / `/filter by status/i` → click
    `getByRole("option", { name: "High" | "Failed" })`), asserting the same row visibility as before.
- [ ] Confirm `primitives.test.tsx` is **not** among the changed files.

**Verify:** `git status --short` shows exactly the 3 frontend files modified; `git diff --name-only`
contains no backend path and no `primitives.test.tsx`.

---

## Task 2: Add the close-behavior test  [AC-5]
- [ ] **[MODIFY] `src/__tests__/reportHistory.test.tsx`** — add ONE test: open a filter (assert its
  `role="listbox"` is present), then press `Escape` (`fireEvent.keyDown(document, { key: "Escape" })`)
  and assert the `listbox` is gone; optionally also assert an outside `pointerDown` closes it. Reuse
  the existing render/query setup; no new dependency. This makes AC-5 a real assertion.

**Verify:** the new test is present and passes in Task 3's run.

---

## Task 3: Full frontend gate  [AC-1…AC-6]
- [ ] `npm test` (vitest) → the full suite green, including the rewritten `reportHistory.test.tsx`
  filter + close tests (AC-1/2/5) and the **unchanged** `primitives.test.tsx` `dropdown_select`
  (AC-3). If any pre-existing test is surprised, pin it with justification — never weaken (§7).
- [ ] `npx tsc --noEmit` → no type error (new `ariaLabel` prop, `useRef`/`useEffect` typed).
- [ ] the project lint script (`npm run lint` / eslint) → clean (no unused `ChevronDown`,
  exhaustive-deps satisfied).
- [ ] `npm run build` (`next build`) → compiles.
- [ ] `git diff --name-only main` shows **exactly** the 6 allow-listed paths (3 frontend + 3 specs) —
  AC-6.

**Verify:** all four gate commands pass; diff scope matches the plan §0 allow-list.

---

## Task 4: Merge
- [ ] FE gate green; diff scope confirmed. Rebase `main`, merge
  `feature/043-glass-filter-dropdown`, delete branch (`git-finish`).

---

*Per §1/§11, implementation happens only on `feature/043-glass-filter-dropdown`, opened after spec +
plan + tasks are approved. Frontend-visual-only — no backend, no `ContractState`, no API, no
migration. Only the three frontend files are taken from the mixed `stash@{0}`; `primitives.test.tsx`
stays unchanged as the back-compat guard.*
