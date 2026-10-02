# Feature 058 — Technical plan: evidence-source badge on report findings

Branch: `feature/058-evidence-source-badge` (per constitution §11).

Derived from the approved `spec.md`. **Frontend-only, presentation layer:** render the already-present
`ReportFinding.path_taken` as an evidence-source badge in each finding card's header **and** as a
secondary label on the expanded "Supporting sources" section. **No backend / graph / `ContractState` /
API / migration change; no `specs/001` amendment** — `path_taken` (`RetrievalPath`) already exists on the
clause record (001) and on the 009 `ReportFinding` model + `types.ts`.

## 0. Scope of change (files touched)

Per **AC-9** the `git diff --name-only main` must show **exactly**:
```
frontend/src/components/report/EvidenceSourceBadge.tsx     (NEW — component + evidenceSourceLabel helper)
frontend/src/components/report/FindingCard.tsx             (header badge + evidence-section label)
frontend/src/lib/api/fixtures.ts                           (correct the invalid path_taken values, D5)
frontend/src/__tests__/evidenceSource.test.tsx            (NEW — AC-1..AC-7, AC-10 + AC-6 regression)
specs/058-evidence-source-badge/spec.md
specs/058-evidence-source-badge/plan.md
specs/058-evidence-source-badge/tasks.md
```
No other file. In particular **`StatusBadge.tsx` is NOT modified** (the icon is composed adjacent to it,
not inside it — §1), **`report-fields.test.ts` is NOT modified** (its drift-lock stays green unchanged,
AC-8 — no field added/removed on `ReportFinding`), and no backend file is touched.

## 1. `EvidenceSourceBadge.tsx` — new component (D3/D7/D8/D2)

A self-contained sibling of `FindingRiskBadge.tsx`, in the same folder. Holds the single source-of-truth
map + the shared label helper so both the header badge and the evidence-section label (AC-10) read one
place.

```tsx
import { Database, Globe } from "lucide-react";
import { StatusBadge, type BadgeTone } from "@/components/ui/StatusBadge";

// Closed map: ONLY the two real RetrievalPath values (state.py). Anything else → unknown → null.
const SOURCE_META: Record<string, { label: string; tone: BadgeTone; Icon: typeof Database }> = {
  local_kb:     { label: "Local knowledge base", tone: "success", Icon: Database }, // D7/D8, trusted tone
  web_fallback: { label: "Live web search",      tone: "warning", Icon: Globe },    // D7/D8, lower-trust tone
};

/** Pure helper — the user-facing source label, or null for null/unknown path (D2). Reused by AC-10. */
export function evidenceSourceLabel(path?: string | null): string | null {
  return (path && SOURCE_META[path]?.label) || null;
}

/** Header badge. Wraps StatusBadge (D3) with a lucide icon adjacent; renders nothing when the source
 *  is null/unknown (D2) — mirrors FindingRiskBadge's safe-fallback pattern. */
export function EvidenceSourceBadge({ path }: { path?: string | null }) {
  const meta = path ? SOURCE_META[path] : undefined;
  if (!meta) return null;
  const { label, tone, Icon } = meta;
  return (
    <span data-testid="evidence-source-badge" className="inline-flex items-center gap-1.5 shrink-0">
      <Icon size={13} aria-hidden className="text-text-tertiary" />
      <StatusBadge label={label} tone={tone} />
    </span>
  );
}
```

- **D3 (reuse StatusBadge):** the pill is a real `StatusBadge`; the icon is composed in the wrapper span
  (StatusBadge has no icon slot and is a shared primitive — composing adjacent avoids modifying it,
  keeping the §0 file list and AC-9 intact).
- **AC-7 (distinct tones, no hex):** `success` (risk-low token) vs `warning` (risk-medium token) are two
  different `TONE[...]` class strings sourced from theme tokens in `StatusBadge`; no raw hex in this file.
- **D2 / AC-3 / AC-4:** `null`, `""`, or any non-enum string (e.g. the stale `"corrective"`/`"direct"`)
  → `meta` undefined → `return null` (no DOM node).

## 2. `FindingCard.tsx` — wire the badge + section label (D4)

Two insertions; nothing else in the card changes.

- **Import:** `import { EvidenceSourceBadge, evidenceSourceLabel } from "./EvidenceSourceBadge";`
- **(a) Header badge (D4a / AC-5):** inside the always-visible header `<button>` flex row, render
  `<EvidenceSourceBadge path={finding.path_taken} />` immediately **before** the existing confidence
  `<span>` (current FindingCard.tsx:86-90), so provenance sits with confidence and is present when the
  card is collapsed. The confidence span, `is_failsafe` "auto" tag, and `FindingRiskBadge` are left
  exactly as they are (AC-6, EC-6).
- **(b) Evidence-section label (D4b / AC-10):** the "Supporting sources" section only renders when
  `finding.evidence.length > 0` (current FindingCard.tsx:183). Change its `SectionLabel` children from
  the literal `Supporting sources` to append the source when known:
  ```tsx
  const srcLabel = evidenceSourceLabel(finding.path_taken);
  // ...
  <SectionLabel icon={<BookOpen size={13} />}>
    {srcLabel ? `Supporting sources · ${srcLabel}` : "Supporting sources"}
  </SectionLabel>
  ```
  When `path_taken` is null/unknown → plain `Supporting sources` (AC-10). When there is no evidence the
  whole section does not render, so no label appears (AC-10 "only labels an already-shown section").

## 3. `fixtures.ts` — correct the invalid `path_taken` values (D5 / AC-8)

The mock `reportFixture` carries values that are **not** `RetrievalPath` members (fixtures.ts:89,108,127).
Correct them to real values chosen to exercise every branch:

| finding | today | → fix | why (test coverage) |
|---|---|---|---|
| `c-001` (high, conf 0.82, has evidence) | `"corrective"` | `"local_kb"` | AC-1 header local badge + AC-10 local-KB section label |
| `c-002` (medium, conf 0.6, has evidence) | `"corrective"` | `"web_fallback"` | AC-2 header web badge + AC-10 web section label |
| `c-003` (low, conf **null**, evidence `[]`) | `"direct"` | `"web_fallback"` | EC-5 badge present with no confidence; section absent → no label |
| `c-004` (null severity, evidence `[]`) | `null` | `null` (unchanged) | AC-3 no badge |

This is dev/mock-data only; it does not touch real backend output. `degradedReportFixture` spreads
`reportFixture.findings[0/1]`, so it inherits `local_kb`/`web_fallback` automatically (EC-3/EC-6 — no
separate edit). The `report-fields.test.ts` drift-lock is unaffected (no field added/removed, AC-8).

## 4. Tests — `__tests__/evidenceSource.test.tsx` (NEW)

TDD: write these first and confirm failing (the component does not exist yet and FindingCard does not
render the source), then implement §1/§2/§3 to green. Uses `@testing-library/react` + `vitest` (the
existing FE test stack) and the corrected `reportFixture`.

**Unit — `EvidenceSourceBadge` / `evidenceSourceLabel`:**
- **AC-1:** `<EvidenceSourceBadge path="local_kb" />` renders text "Local knowledge base".
- **AC-2:** `path="web_fallback"` renders "Live web search".
- **AC-3:** `path={null}` renders nothing (`queryByTestId("evidence-source-badge")` is null).
- **AC-4:** `path="corrective"` (and `"direct"`, `""`) render nothing (unknown → safe).
- **AC-7:** the local-KB and web-fallback pills carry **different** tone classes (assert the rendered
  `StatusBadge` span className differs between the two — `success` vs `warning` token classes); assert no
  raw hex (`/#[0-9a-f]{3,6}/i`) in either rendered class string.
- `evidenceSourceLabel`: `"local_kb"→"Local knowledge base"`, `"web_fallback"→"Live web search"`,
  `null`/`"corrective"`→`null`.

**Integration — `FindingCard` with the corrected fixture:**
- **AC-5 (visible collapsed):** render a `FindingCard` for the `local_kb` finding **collapsed**
  (default); the source badge is in the DOM without expanding.
- **AC-6 (confidence untouched):** the `"<n>% confidence"` text still renders for a finding with a
  non-null `confidence_score` and is **absent** for the `confidence_score: null` finding — unchanged from
  today.
- **AC-10 (section label):** expand the `local_kb` finding (has evidence) → the Supporting-sources
  heading text includes "Local knowledge base"; expand the `web_fallback` finding with evidence → heading
  includes "Live web search"; a finding with `path_taken` known but **no** evidence renders no
  Supporting-sources section at all (so no label).

## 5. Correctness / AC mapping
- **No data/schema change (AC-8/AC-9):** only presentation files + fixtures + the new test change;
  `ReportFinding` shape is untouched so the drift-lock passes unchanged; `path_taken` is read, never
  written or re-derived (D1 — the KB-vs-web decision stays CRAG's, constitution §2/§3).
- **Single source of truth:** `SOURCE_META` + `evidenceSourceLabel` live in one file; the header badge
  and the section label cannot drift (AC-1/AC-2 ↔ AC-10 consistent).
- **Graceful degradation (D2):** every null/unknown path — including legacy JSON missing the field
  (EC-3) and the pre-fix stale values (EC-2) — renders nothing, never a wrong/placeholder source.
- **Orthogonality (EC-5/EC-6):** badge vs confidence vs `is_failsafe`/degraded each decide independently;
  no coupling introduced.

## 6. Verification gate (all offline)
- `npm test` (vitest) — the new `evidenceSource.test.tsx` (AC-1..AC-7, AC-10, AC-6) + the full existing
  suite (incl. `report-fields.test.ts` drift-lock, AC-8) green.
- `npx tsc --noEmit` — clean (the new component + helper typed; `BadgeTone` imported).
- eslint (project lint script) — clean (no unused imports; `aria-hidden` icon).
- `npm run build` (`next build`) — compiles.

## 7. Risks / limitations
- **Presentation only** — no data/route/API risk; CRAG routing and the confidence threshold are
  untouched (constitution §2/§3).
- **Icon adjacent, not inside the pill** — a deliberate choice to avoid modifying the shared
  `StatusBadge` primitive (keeps the §0 allow-list tight); visually it reads as one unit. If an
  icon-inside-pill look is later wanted, it is a separate additive `StatusBadge` enhancement.
- **Report workspace only** — the PDF/md/email renderers do not get the badge (out of scope, §5); a
  backend follow-up if wanted.
- **Live per-clause SSE narration** is feature 059, not here (spec §5).

## 8. Merge
- Full FE gate green (test + tsc + eslint + build); `git diff --name-only main` matches the §0 allow-list
  exactly (no backend / `StatusBadge` / `report-fields.test.ts` change). Rebase `main`, merge
  `feature/058-evidence-source-badge`, delete branch (`git-finish`).
