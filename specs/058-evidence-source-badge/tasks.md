# Feature 058 — Evidence-source badge — Implementation Tasks

Reference documents:
- Spec: `specs/058-evidence-source-badge/spec.md`
- Plan: `specs/058-evidence-source-badge/plan.md`
- Constitution: `specs/000-constitution.md` (**§1/§11** branch-gated frontend change; **§7** TDD / never
  weaken a test)

Frontend paths below are relative to `frontend/`.

**Workflow reminders:**
- **Frontend-only, presentation layer.** No backend, graph, `ContractState`, API, or migration change.
  `path_taken` is only **read** (it already exists on `ReportFinding`); it is never written or
  re-derived (the KB-vs-web decision stays CRAG's — constitution §2/§3).
- **Scope is exactly these paths (AC-9).** `git diff --name-only main` must show only:
  - `src/components/report/EvidenceSourceBadge.tsx` (NEW)
  - `src/components/report/FindingCard.tsx`
  - `src/lib/api/fixtures.ts`
  - `src/__tests__/evidenceSource.test.tsx` (NEW)
  - the three `specs/058-evidence-source-badge/**` docs.
- **Do NOT modify** `src/components/ui/StatusBadge.tsx` (icon is composed adjacent, not inside — plan §1),
  `src/lib/reportFormat.ts` (the label helper lives in the new component file), or
  `src/__tests__/report-fields.test.ts` (its drift-lock must stay green **unchanged** — AC-8; this
  feature adds/removes NO field on `ReportFinding`).
- **TDD (§7):** write the test file first and confirm it FAILS, then implement to green. If a pre-existing
  test is surprised, fix the code — never weaken the test.
- **Exact badge copy (D7):** `local_kb` → `"Local knowledge base"`; `web_fallback` → `"Live web search"`.
  **Icons (D8):** lucide `Database` (local KB), `Globe` (web fallback). **Tones (AC-7):** `success`
  (local KB), `warning` (web fallback) — both from `StatusBadge`'s theme tokens, no raw hex.

---

## Task 0: Branch
- [ ] From an up-to-date `main` (`git checkout main && git pull`), create
  `feature/058-evidence-source-badge` (use `git-start`). Commit the APPROVED
  `spec.md`/`plan.md`/`tasks.md` on the branch.

**Verify:** `git branch --show-current` → `feature/058-evidence-source-badge`.

---

## Task 1: Write the failing tests first  [AC-1, AC-2, AC-3, AC-4, AC-5, AC-6, AC-7, AC-10]
- [ ] **[NEW] `src/__tests__/evidenceSource.test.tsx`** — using `vitest` + `@testing-library/react`
  (the existing FE stack) and the `reportFixture` from `src/lib/api/fixtures.ts`. Write these cases; they
  will FAIL to compile/run until Tasks 2–4 exist:

  **Unit — `EvidenceSourceBadge` + `evidenceSourceLabel`** (import from
  `@/components/report/EvidenceSourceBadge`):
  - **AC-1:** render `<EvidenceSourceBadge path="local_kb" />` → `getByText("Local knowledge base")`.
  - **AC-2:** render `path="web_fallback"` → `getByText("Live web search")`.
  - **AC-3:** render `path={null}` → `queryByTestId("evidence-source-badge")` is `null`.
  - **AC-4:** render `path="corrective"`, then `"direct"`, then `""` → each `queryByTestId(...)` is
    `null` (unknown → render nothing).
  - **AC-7:** render both `local_kb` and `web_fallback`; assert the two rendered badges' class strings
    **differ** (distinct tones) and that neither class string matches `/#[0-9a-f]{3,6}/i` (no raw hex).
  - `evidenceSourceLabel("local_kb") === "Local knowledge base"`,
    `evidenceSourceLabel("web_fallback") === "Live web search"`,
    `evidenceSourceLabel(null) === null`, `evidenceSourceLabel("corrective") === null`.

  **Integration — `FindingCard`** (import `FindingCard` from `@/components/report/FindingCard`; render
  individual findings from the corrected `reportFixture`):
  - **AC-5 (visible when collapsed):** render the `c-001` (`local_kb`) finding with the card **collapsed**
    (default, do not expand) → the source badge text "Local knowledge base" is in the DOM.
  - **AC-6 (confidence untouched):** the `c-001` finding (confidence_score 0.82) still shows
    `"82% confidence"`; the `c-003` finding (confidence_score `null`) shows **no** `"% confidence"` text.
  - **AC-10 (section label):** expand the `c-001` (`local_kb`, has evidence) finding → the
    "Supporting sources" heading text contains "Local knowledge base"; expand the `c-002`
    (`web_fallback`, has evidence) finding → heading contains "Live web search"; the `c-003`
    (`web_fallback`, **evidence `[]`**) finding renders **no** "Supporting sources" section at all.

- [ ] Run `npm test` and CONFIRM these new tests FAIL (component missing / FindingCard not yet rendering
  the source). Do not proceed until failure is confirmed (§7).

**Verify:** `npm test` shows `evidenceSource.test.tsx` failing for the expected reasons.

---

## Task 2: Create the badge component  [AC-1, AC-2, AC-3, AC-4, AC-7]
- [ ] **[NEW] `src/components/report/EvidenceSourceBadge.tsx`** exactly per plan §1:
  - Import `{ Database, Globe }` from `lucide-react` and `{ StatusBadge, type BadgeTone }` from
    `@/components/ui/StatusBadge`.
  - Define the closed map `SOURCE_META: Record<string, { label: string; tone: BadgeTone; Icon: typeof Database }>`
    with ONLY `local_kb` (`"Local knowledge base"`, tone `"success"`, `Database`) and `web_fallback`
    (`"Live web search"`, tone `"warning"`, `Globe`).
  - Export `function evidenceSourceLabel(path?: string | null): string | null` →
    `(path && SOURCE_META[path]?.label) || null`.
  - Export `function EvidenceSourceBadge({ path }: { path?: string | null })`:
    look up `meta = path ? SOURCE_META[path] : undefined`; if falsy, `return null` (AC-3/AC-4); else
    return a `<span data-testid="evidence-source-badge" className="inline-flex items-center gap-1.5 shrink-0">`
    containing `<Icon size={13} aria-hidden className="text-text-tertiary" />` then
    `<StatusBadge label={meta.label} tone={meta.tone} />`.
- [ ] Re-run `npm test` → the Task-1 **unit** cases (AC-1/2/3/4/7 + `evidenceSourceLabel`) now pass.

**Verify:** the unit portion of `evidenceSource.test.tsx` is green; no raw hex in the component.

---

## Task 3: Correct the mock fixtures  [AC-8, EC-5]
- [ ] **[MODIFY] `src/lib/api/fixtures.ts`** — change only the three invalid `path_taken` values in
  `reportFixture.findings` (do NOT touch any other field or any other fixture):
  - `c-001` (line ~89): `"corrective"` → `"local_kb"`.
  - `c-002` (line ~108): `"corrective"` → `"web_fallback"`.
  - `c-003` (line ~127): `"direct"` → `"web_fallback"` (its `confidence_score` stays `null`, evidence
    stays `[]` — EC-5 / the AC-10 "no section → no label" case).
  - `c-004` (line ~141): leave `path_taken: null` unchanged (AC-3).
- [ ] Do not edit `degradedReportFixture` — it spreads `reportFixture.findings[0]/[1]` and inherits the
  corrected values (EC-3/EC-6).

**Verify:** every `reportFixture.findings[*].path_taken` is one of `local_kb` / `web_fallback` / `null`;
`report-fields.test.ts` is untouched and still green (AC-8).

---

## Task 4: Wire the badge + section label into FindingCard  [AC-5, AC-6, AC-10, EC-6]
- [ ] **[MODIFY] `src/components/report/FindingCard.tsx`** per plan §2:
  - Add import: `import { EvidenceSourceBadge, evidenceSourceLabel } from "./EvidenceSourceBadge";`
  - **(a)** Inside the header `<button>` flex row, render `<EvidenceSourceBadge path={finding.path_taken} />`
    immediately **before** the existing confidence `<span>` (currently around lines 86-90). Leave the
    confidence span, the `is_failsafe` "auto" tag, and `<FindingRiskBadge />` exactly as they are (AC-6,
    EC-6).
  - **(b)** In the expanded body, before the evidence `<section>` (gated by `finding.evidence.length > 0`,
    ~line 183), compute `const srcLabel = evidenceSourceLabel(finding.path_taken);` and change that
    section's `SectionLabel` children from the literal `Supporting sources` to
    `{srcLabel ? \`Supporting sources · ${srcLabel}\` : "Supporting sources"}` (keep the `BookOpen` icon —
    already imported). Do not otherwise change the section.
- [ ] Re-run `npm test` → the Task-1 **integration** cases (AC-5/6/10) now pass.

**Verify:** the integration portion of `evidenceSource.test.tsx` is green.

---

## Task 5: Full frontend gate  [AC-1…AC-10]
- [ ] `npm test` (vitest) → the **full** suite green, including:
  - the new `evidenceSource.test.tsx` (AC-1…AC-7, AC-10, AC-6),
  - the **unchanged** `report-fields.test.ts` drift-lock (AC-8),
  - the existing **`report.test.tsx`** view test (it asserts `"82% confidence"` on `c-001` and that the
    empty-evidence `c-003` has no "Supporting sources" section — both stay green because `c-001`'s
    confidence is untouched and `c-003`'s evidence stays `[]`).
  - If any pre-existing test is surprised, fix the code — never weaken the test (§7).
- [ ] `npx tsc --noEmit` → no type error (new component/helper typed; `BadgeTone` imported).
- [ ] project lint script (`npm run lint` / eslint) → clean (no unused imports; `aria-hidden` icon).
- [ ] `npm run build` (`next build`) → compiles.
- [ ] `git diff --name-only main` shows **exactly** the allow-listed paths (4 frontend + 3 specs) — AC-9.

**Verify:** all four gate commands pass; diff scope matches the plan §0 / Task-0 allow-list.

---

## Task 6: Merge
- [ ] FE gate green; diff scope confirmed. Rebase `main`, merge `feature/058-evidence-source-badge`,
  delete the branch (`git-finish`).

---

*Per §1/§11, implementation happens only on `feature/058-evidence-source-badge`, opened after spec +
plan + tasks are all spec-reviewer-APPROVED. Frontend-visual-only — no backend, no `ContractState`, no
API, no migration. `StatusBadge.tsx`, `reportFormat.ts`, and `report-fields.test.ts` are NOT modified.*
