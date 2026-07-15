# Feature 022 — Report Redesign ("Analysis Workspace")

## 1. Problem statement

The report destination screen (017, `/jobs/[jobId]/report`) today is a single centered column:
a gradient hero header, a risk overview, and a vertical stack of expandable `FindingCard`s. It is
correct and honest, but it does not match the reference design **screen 6 "Analysis Workspace"**
(`…31 PM (6).jpeg`) — a **two-pane legal workspace** with a document/clause rail on the left and an
**AI Analysis Panel** on the right that lists each flagged clause by risk with its text, an AI
explanation, and a **before/after compare** of the original clause vs. the suggested rewrite.

This feature **restyles the existing report** into that workspace look. It is **phase 3** of the
post-019 set (020 profile ✓ → 021 report history ✓ → **022 report redesign**).

### Position relative to the constitution

**No amendment, no backend change, no graph/state change.** The report data already exists and is
served by `GET /api/jobs/{id}/report?format=json` as the 009 `ContractReport` **boundary model**
(constitution §4 — the internal `ContractState` TypedDict never crosses the HTTP boundary; this
feature consumes only the already-defined report DTO, inventing no new field names). This feature is
**frontend-only** — it re-lays-out and restyles the components under
`frontend/src/components/report/**` that already render that DTO. No LangGraph node/edge, no
`ContractState` field, no new endpoint, no migration, no new data hook. Per §11 it is developed on
`feature/022-report-redesign`.

The mockup's third column — the **"Legal AI Assistant" chat panel** — is **not** built (there is no
chat backend and none is in scope; see D3). This is consistent with the PERMANENTLY-CUT posture in
§2 against unspecced surfaces; the workspace here is **two-pane, not three**.

## 2. Inputs and outputs

### 2.1 Data source (unchanged backend, unchanged DTO)

The single input is the serialized 009 `ContractReport` already fetched by the existing `useReport`
hook via `getApiClient()` (seam). No fields are added or renamed. The fields this redesign consumes
(all already present — see `frontend/src/lib/api/types.ts`):

| Field | Use in the workspace |
| --- | --- |
| `original_filename` | Workspace header title |
| `summary { total_clauses, validated_findings, clean_clauses, high, medium, low }` | Derived **risk band** pill + counts (via existing `deriveRiskBand` / `countsLine`) |
| `generated_at`, `ocr_used`, `ocr_confidence` | Header meta row (unchanged from 017) |
| `ingest_error` | "could not process" panel (unchanged from 017 D6 / EC-4) |
| `findings[]` — `clause_id, position, section_number, clause_type, risk_level, risk_rationale, clause_text, rewrite_state, suggested_rewrite, confidence_score, evidence[]` | **Left rail** entries + **AI Analysis Panel** cards + **before/after compare** |

There is **no full-document text field** in the report — the 009 report stores only *flagged*
clauses (`clause_text`) plus their `suggested_rewrite`. This directly shapes D1 below.

### 2.2 The Analysis Workspace (`/jobs/[jobId]/report`, restyled)

A **two-pane** layout replaces the current single centered column:

- **Workspace header** (full width): an "Analysis Workspace" eyebrow, the `original_filename`, the
  **derived risk band** pill + literal findings counts (high/medium/low), the generated-at / OCR
  meta, and the existing **two honest downloads** (Markdown + JSON). **No `NN/100` score** (D4), no
  "Business Impact" (D5).
- **Left rail — "Flagged clauses" navigator** (D1): an ordered list of the report's `findings`
  (title from `clause_type`/`position`, `section_number`, a risk dot/pill). It is a **table of
  contents over the analyzed clauses**, not a rendering of the full contract (which the data does
  not contain). Selecting an entry **focuses/scrolls to** that finding's card in the main panel and
  expands it; the active entry is highlighted. On narrow screens the rail collapses (D7).
- **Main pane — "AI Analysis Panel"**: the `findings`, each an expandable card (reusing the existing
  `FindingCard` content — risk badge, **AI Explanation** from `risk_rationale`, **Text** =
  `clause_text`, supporting evidence), restyled to the workspace look. Each card with a rewrite
  (`rewrite_state === "rewritten"` and a `suggested_rewrite`) gains a **Compare toggle** that
  switches its rewrite section between the current stacked view and a **side-by-side before/after**
  (Original clause ↔ Suggested rewrite) — the mockup's `[Compare]`, reinterpreted per D2.

### 2.3 States (all preserved from 017)

Every non-happy state that 017 already handles is preserved, restyled to fit: `loading`,
`redirecting` (non-terminal job → `/jobs/{id}`), `not_found`, `artifact_unavailable`, `error` (with
retry), `ingest_error` panel, and the **no-findings** "No risky clauses found" state (in which the
left rail shows an empty hint rather than a dead navigator).

## 3. Resolved decisions (inline)

- **D1 — Left "Document View" → a "Flagged clauses" navigator rail (no fabricated full text).** The
  009 report contains only flagged clauses, not the whole contract, and there is no backend that
  serves full document text. Rather than fabricate a document, the left column is an honest
  **clause-navigation rail** (a table of contents over `findings`) that drives the main panel. This
  keeps the two-pane workspace *shape* of screen 6 while staying truthful to the data — and stays
  **frontend-only** (no new endpoint). The column is labeled for what it is ("Flagged clauses" /
  "Contents"), not "Document".
- **D2 — `[Compare]` = per-clause before/after (original ↔ suggested rewrite).** The mockup's
  `[Compare]` is reinterpreted as a **within-a-single-clause** comparison of `clause_text` vs.
  `suggested_rewrite`, matching [[phase-020-022-plan]]. It is **not** contract-to-contract
  comparison (a separate future feature / screen 7, out of scope). Offered only when the clause has a
  rewrite; clauses without one show the existing "no safe rewrite" note and no Compare toggle. The
  mockup's `[Rewrite]` action maps to the `suggested_rewrite` the report already provides — no new
  generate-on-demand action is added.
- **D3 — "Legal AI Assistant" chat panel is CUT.** There is no chat backend and none is in scope;
  the third column is dropped and the workspace is two-pane. (Consistent with the resolved-cut list
  in [[phase-020-022-plan]].)
- **D4 — No `78/100` numeric risk score.** 017/018 deliberately show a **derived risk band** (from
  the real summary counts), never a fabricated 0–100 number; the header keeps the band pill + counts.
- **D5 — No "Business Impact" section.** That field does not exist in the 009 report (noted in the
  existing `FindingCard`); nothing is fabricated.
- **D6 — Restyle only; reuse the data path, seam, and all states.** The view continues to reach the
  backend **only** via `getApiClient()` through the existing `useReport` hook; every 017 state
  (§2.3) is preserved. No backend, graph, `ContractState`, endpoint, or migration change. Existing
  helpers (`deriveRiskBand`, `countsLine`, `findingTitle`, `formatGeneratedAt`, `FindingRiskBadge`)
  are reused, not reimplemented.
- **D7 — Responsive.** Two-pane on desktop (rail + panel); on narrow screens it collapses to a
  single column with the navigator rendered above the panel (or as a collapsible strip) — no
  horizontal scroll, no content hidden without an affordance.
- **D8 — Honest downloads retained.** The header keeps exactly the two real downloads from 017
  (Markdown report + JSON data); no new export formats are introduced.

## 4. Acceptance criteria

Frontend → Vitest + RTL (mock/fake provider). No backend criteria (unchanged).

- **AC-1:** `/jobs/{jobId}/report` for a completed report with findings renders a **two-pane
  workspace**: a left **Flagged-clauses navigator** listing one entry per `finding`, and a main **AI
  Analysis Panel** listing one card per `finding`. (Was a single centered column.)
- **AC-2:** The workspace **header** shows the `original_filename`, the **derived risk band** pill,
  the literal high/medium/low counts, and the two downloads (Markdown + JSON). It shows **no
  `NN/100` score** and **no "Business Impact"** text anywhere.
- **AC-3:** Each navigator entry shows the finding's title (`clause_type`/`position`), its
  `section_number` when present, and a **risk indicator**; entries appear in `findings` order.
- **AC-4:** **Selecting a navigator entry** focuses its card in the main panel — the card is
  expanded and marked active (e.g. scrolled into view / highlighted). Selecting a different entry
  moves the active state.
- **AC-5:** Each analysis card shows the **AI Explanation** (`risk_rationale`), the **Text**
  (`clause_text`), the risk badge, and evidence — reusing the existing finding content.
- **AC-6:** A finding with `rewrite_state === "rewritten"` and a `suggested_rewrite` renders a
  **Compare** control; toggling it switches the rewrite section between the stacked view and a
  **side-by-side original ↔ suggested** view, both showing the real `clause_text` and
  `suggested_rewrite`.
- **AC-7:** A finding with `rewrite_state !== "rewritten"` (or no `suggested_rewrite`) shows **no
  Compare control** and keeps the existing "no safe rewrite" note where applicable.
- **AC-8:** **No-findings** report → the "No risky clauses found" state renders in the main pane and
  the navigator shows an **empty hint** (not a dead/blank navigator, not a header-only table).
- **AC-9:** Every 017 non-happy state still renders (restyled): `loading`, `redirecting` →
  `router.replace('/jobs/{id}')`, `not_found`, `artifact_unavailable`, `error` with a working
  **retry** that re-calls the report fetch, and the `ingest_error` "could not process" panel with its
  Markdown download.
- **AC-10:** **Seam + boundary:** no `components/report/**` file imports a provider module directly
  (only `getApiClient()` / the `useReport` hook); **no `backend/**` file changes**; no new field
  names beyond the 009 `ContractReport` DTO.
- **AC-11:** The mockup's **chat panel is absent** — no "Legal AI Assistant" / chat / message-input
  UI is rendered (D3).

**Live (real backend)**

- **AC-12 (smoke, manual):** With `provider=real`, open a real completed report: the two-pane
  workspace renders with the real filename, real flagged clauses in the navigator, real AI
  explanations and clause text, and a working before/after compare on a clause that has a rewrite;
  the Markdown/JSON downloads still work; a non-terminal job still redirects to `/jobs/{id}`.

## 5. Edge cases

- **EC-1 — No findings** → main-pane empty state + navigator empty hint (AC-8); Compare never
  appears.
- **EC-2 — Finding without a rewrite** (`rewrite_state` of `unavailable` or `not_eligible`, or a
  null `suggested_rewrite`) → no Compare toggle; existing "no safe rewrite" note shown for
  `unavailable`, nothing extra for `not_eligible` (AC-7).
- **EC-3 — Missing `clause_type`** → navigator + card fall back to `Clause {position}` (existing
  `findingTitle`); missing `section_number` → locator omitted.
- **EC-4 — Missing/near-empty `risk_rationale`** → existing "No explanation provided." fallback.
- **EC-5 — Long clause / long rewrite** → in side-by-side compare both columns wrap/scroll
  independently without breaking the layout; the existing "show full clause" affordance is preserved.
- **EC-6 — Many findings (long report)** → navigator is independently scrollable; the panel scrolls;
  neither pane pushes the other off-screen.
- **EC-7 — Narrow viewport** → single-column fallback (D7); navigator remains reachable, no
  horizontal overflow.
- **EC-8 — `ingest_error` report** (no findings, could-not-process) → the 017 error panel renders;
  no two-pane workspace is forced onto an empty report.
- **EC-9 — `redirecting`/`loading`** → the workspace chrome is not rendered around a missing report;
  the existing centered state shows instead (AC-9).

## 6. Out of scope

- **Contract comparison** (side-by-side of two *different* contracts, screen 7) — a separate future
  feature; D2's "compare" is strictly within one clause.
- **The "Legal AI Assistant" chat** / any conversational Q&A over the contract — no chat backend
  exists; cut (D3).
- **Serving or reconstructing the full contract document text** — not stored in the 009 report; the
  left rail is a clause navigator, not a document viewer (D1). Any future full-text viewer would need
  a *separate* backend spec.
- **A numeric `0–100` risk score** and **"Business Impact"** copy — deliberately not shown (D4/D5).
- **New export formats, "Draft Amendment", editing/accepting rewrites, or generate-on-demand
  rewrites** — the report is read-only; downloads stay Markdown + JSON (D8).
- **Any backend / graph / `ContractState` / endpoint / migration change** — none (D6).

## 7. Open questions

_None blocking — all significant design decisions are resolved inline in §3 per the user's standing
preference for inline spec decisions ([[feedback-spec-decisions-inline]]). Two points are flagged
for visibility, each already given a default so the spec is buildable as written:_

- **Q1 (resolved as D1):** The reference "Document View" cannot show the real full contract (the
  report has only flagged clauses). Resolved: render a **Flagged-clauses navigator** rail instead of
  fabricating document text or adding a backend. If a true full-document viewer is later wanted, it
  is a separate backend feature.
- **Q2 (resolved as D3):** The reference third column (chat) has no backend. Resolved: **cut**; the
  workspace is two-pane. Reversible later only via a separate chat feature (its own spec).
