# Feature 058 — Evidence-source badge on report findings

Branch: `feature/058-evidence-source-badge` (per constitution §11).

> Numbering note: 055–057 are reserved for the "Suggestion 1 — clause traceability" chain (PDF
> source-locator capture → serve-original endpoint → in-workspace viewer), which is planned but not yet
> spec'd. This feature is the quick-win first half of "Suggestion 2 — retrieval transparency"; the live
> per-clause SSE narration is a separate later feature (059). The gap in folder numbers is intentional.

## 1. Problem statement

Node 3 of the fixed pipeline (CRAG retrieval, constitution §2) makes a per-clause confidence decision:
when the local FAISS KB top-score is `>= CRAG_CONFIDENCE_THRESHOLD` (0.73) the clause is judged against
the **curated local legal knowledge base**; below it, the clause falls back to a **live web search**.
This is one of the two permitted conditional branches, and it already records its outcome per clause as
`path_taken` (a `RetrievalPath`) plus the `confidence_score` that drove it (`crag_retrieval_agent.py`).

Those two fields already flow all the way to the UI boundary — CRAG writes them into the clause record
(001), `assemble_report` copies them into `ReportFinding` (`path_taken`, `confidence_score`), they are
mirrored in `frontend/src/lib/api/types.ts`, and `FindingCard` already **renders the confidence
percentage**. But `path_taken` reaches the card and is **never displayed**. The user therefore cannot
tell whether a given finding was supported by the trustworthy curated KB or by an open-web search — two
evidence sources of very different reliability. For a legal tool, that provenance is a trust signal the
user is currently blind to.

This feature surfaces the already-present `path_taken` as a small **evidence-source badge** on each
finding card ("Local knowledge base" vs "Live web search"), so the retrieval provenance becomes a
visible, permanent part of the report.

### Position relative to the constitution
**Frontend-only, presentation layer.** No backend, no graph/node/edge, no `ContractState` change, no
API/schema change, no Alembic migration, **no amendment to `specs/001-contract-state-schema.md`** — the
`path_taken` field it reads is already defined there (clause record: `path_taken: Optional[RetrievalPath]`)
and already present on the 009 `ReportFinding` boundary model. Per §1/§11 it is developed on
`feature/058-evidence-source-badge`. Pipeline behavior, retrieval routing, and the data on the wire are
**unchanged** — only the finding card's rendering changes. It does not touch CRAG, the confidence
threshold, or any node logic (constitution §2/§3 untouched).

## 2. Inputs and outputs

### Input — the existing data contract (no new fields)
- **`ReportFinding.path_taken` (`009` model / `types.ts`)** — the `RetrievalPath` value as a string on
  the wire. Per `specs/001-contract-state-schema.md` (`RetrievalPath` enum) the only two valid values are:
  - `"local_kb"` → the local curated FAISS KB path
  - `"web_fallback"` → the live web-search fallback path
  - It may also be **`null`/absent** (e.g. an empty-text clause, or legacy report JSON) — CRAG sets
    `path_taken: None` for a clause it could not process (`crag_retrieval_agent.py` empty-text guard).
- **`ReportFinding.confidence_score`** — already rendered in the header today; unchanged by this feature
  (it may be shown adjacent to the new badge for context, see D4).

### Output — UI only
- Each `FindingCard` renders an **evidence-source badge** with user-facing copy:
  - `"local_kb"` → **"Local knowledge base"**
  - `"web_fallback"` → **"Live web search"**
  - `null` / unrecognized → **no badge** (render nothing; never fabricate a source).
- No change to any serialized data, file, API response, or `ContractState`.

### Resolved decisions (inline)
- **D1 — Read `path_taken`, do not recompute.** The badge is a pure render of the existing field. It
  never re-derives the source from `confidence_score` or the KB threshold (that logic is CRAG's, §2/§3).
- **D2 — Two known values + graceful unknown.** Map exactly `local_kb`/`web_fallback`; any other value
  (including `null`, `""`, or a future enum member not yet handled) renders **no badge** rather than a
  wrong or placeholder one. This mirrors `FindingRiskBadge`'s "unknown → safe fallback" pattern.
- **D3 — Reuse the design-system badge primitive.** Implement a small `EvidenceSourceBadge` component
  (sibling of `FindingRiskBadge`) that wraps the existing `StatusBadge` primitive with a tone + a
  lucide icon. **No raw hex** in `src/components/**` (honors the visual-consistency bar); tones come from
  theme tokens. The web-fallback badge uses a visually distinct (lower-trust) tone from the local-KB one
  so the two are tellable at a glance.
- **D4 — Placement: both the always-visible card header and the expanded evidence section** (resolves
  OQ-2). (a) A badge in the always-visible header, grouped with the existing confidence indicator, so
  provenance is visible **without expanding** the card (at-a-glance transparency). (b) The expanded
  "Supporting sources" section header also carries the source as a secondary label (e.g. "Supporting
  sources · Live web search"), reinforcing provenance where the snippets are shown. Both read the same
  `path_taken`; both degrade to nothing when it is null/unknown (D2).
- **D7 — Badge copy (resolves OQ-1):** exactly **"Local knowledge base"** (for `local_kb`) and **"Live
  web search"** (for `web_fallback`). These are the user-facing strings asserted by AC-1/AC-2.
- **D8 — Icons (resolves OQ-4):** lucide **`Database`** for the local-KB badge and **`Globe`** for the
  web-fallback badge (lucide-react is already a dependency; purely cosmetic).
- **D9 — Confidence indicator unchanged (resolves OQ-3):** the existing `"<n>% confidence"` display is
  left exactly as-is; this feature does not emphasize or relocate it (AC-6 guards this).
- **D5 — Correct the stale mock fixtures.** `frontend/src/lib/api/fixtures.ts` currently sets
  `path_taken` to `"corrective"` / `"direct"` (fixtures.ts:89,108,127) — values that are **not** members
  of the backend `RetrievalPath` enum and never occur in real data. This feature updates the fixture to
  the real values (`"local_kb"` / `"web_fallback"`, plus the existing `null` on the 4th finding) so the
  mock provider and the badge tests reflect reality. This is a dev/test-data-only correction — it does
  not touch real backend output.
- **D6 — Frontend-visual-only.** No new runtime dependency; lucide-react (already a dependency) supplies
  the icons. No data/route/API change.

## 3. Acceptance criteria

All testable with the standard offline frontend gate (vitest + `tsc --noEmit` + eslint + `next build`).

- **AC-1 (local-KB badge):** a `FindingCard` for a finding with `path_taken: "local_kb"` renders a
  visible badge whose accessible text is **"Local knowledge base"**.
- **AC-2 (web-fallback badge):** a `FindingCard` for a finding with `path_taken: "web_fallback"` renders
  a visible badge whose accessible text is **"Live web search"**.
- **AC-3 (null → no badge):** a `FindingCard` for a finding with `path_taken: null` (or absent) renders
  **no** evidence-source badge (the badge element is not in the DOM).
- **AC-4 (unknown → no badge):** a `FindingCard` for a finding with an unrecognized `path_taken` (e.g.
  `"corrective"`, `"direct"`, or any non-enum string) renders **no** evidence-source badge — the
  component degrades safely instead of showing a wrong/placeholder source (guards against the stale
  values D5 corrects, and any future enum drift).
- **AC-5 (visible when collapsed):** the badge appears in the card's always-visible header region, i.e.
  it is present in the DOM when the card is collapsed (not gated behind expanding the card).
- **AC-6 (confidence untouched):** the existing `"<n>% confidence"` indicator still renders exactly as
  today for findings with a non-null `confidence_score`, and is still absent when `confidence_score` is
  null — this feature does not regress the confidence display (regression guard on FindingCard).
- **AC-7 (distinct tones):** the local-KB badge and the web-fallback badge render with **different**
  tone/visual-treatment classes (so they are distinguishable), both sourced from theme tokens with no
  raw hex in the component.
- **AC-8 (fixtures corrected + drift-lock green):** `fixtures.ts` `path_taken` values are valid
  `RetrievalPath` members (`local_kb`/`web_fallback`/`null`); the existing
  `frontend/src/__tests__/report-fields.test.ts` drift-lock (which already lists `path_taken` in
  `REPORT_FINDING_FIELDS`) stays green — i.e. no field is added/removed on `ReportFinding`.
- **AC-9 (no architecture change):** `git diff main` touches only frontend presentation files
  (the new `EvidenceSourceBadge` component, `FindingCard.tsx`, `fixtures.ts`, and the relevant
  `__tests__`/component test) plus the `specs/058-**` docs — **no** backend, graph, state, API, or
  migration change. `npm test`, `tsc --noEmit`, `eslint`, and `next build` all pass.
- **AC-10 (evidence-section secondary label, D4b):** when a finding has non-empty evidence AND a known
  `path_taken`, the expanded "Supporting sources" section header also shows the source as a secondary
  label (local-KB finding → text includes "Local knowledge base"; web-fallback finding → "Live web
  search"). When `path_taken` is null/unknown, the section header shows no source label (and is the
  plain "Supporting sources" as today). The evidence section is unchanged when there is no evidence
  (the section itself does not render at all — this AC only labels an already-shown section).

## 4. Edge cases

- **EC-1 — `path_taken: null` (empty-text / unprocessed clause):** CRAG writes `None` for a clause it
  could not embed/route; the card shows no source badge (AC-3). The finding still renders fully (risk,
  rationale, etc.) — the badge's absence must not break layout or other fields.
- **EC-2 — Stale/unknown value:** pre-058 mock data and any future `RetrievalPath` member not yet mapped
  → no badge (AC-4). The map is closed (two known keys); everything else is "unknown → render nothing".
- **EC-3 — Legacy report JSON (field absent entirely):** `path_taken` optional/undefined → treated as
  null → no badge (same as EC-1). The 038 degraded fixture, built by spreading `reportFixture`, inherits
  corrected values and must still render without error.
- **EC-4 — `web_fallback` with evidence snippets:** a web-fallback finding often still has evidence; the
  badge labels the *source path*, independent of whether the "Supporting sources" list is non-empty. The
  two are not coupled.
- **EC-5 — Confidence present/absent is independent of `path_taken`:** a finding can have
  `path_taken: "web_fallback"` with `confidence_score: null` (KB unavailable / embed failure) — the
  badge renders, the confidence indicator does not. Both the badge and the confidence indicator decide
  independently (AC-5/AC-6).
- **EC-6 — Degraded / fail-safe findings (038):** `is_failsafe` and `analysis_degraded` are orthogonal to
  retrieval source; the new badge coexists with the existing "auto" tag and degraded banner without
  interaction.

## 5. Out of scope

- **Live per-clause SSE narration during the CRAG step** ("Clause 7 → confidence 0.61 → searching live
  web") — owned by **future feature 059**. This feature is the persisted-report half only; it adds no
  SSE/`ProgressEvent` change and no processing-view change.
- **Any backend/CRAG change** — the confidence threshold, routing logic, and `path_taken`/
  `confidence_score` computation are unchanged (owned by `specs/005-crag-retrieval`).
- **Aggregating retrieval-source rates** into the dashboard (e.g. "% of findings judged on the local KB")
  — a possible later analytics surface; not built here (would belong to an 018-style dashboard feature).
- **Per-snippet provenance** inside the "Supporting sources" list — the badge and the section-header
  label (D4b/AC-10) label the clause's single chosen retrieval path, NOT each individual snippet. Labeling
  snippets one-by-one is out of scope (CRAG already stores one `path_taken` per clause, not per snippet).
- **PDF/Markdown/email report rendering of the source** — this feature targets the interactive report
  workspace card only. Carrying the badge into the exported PDF (reportlab) / md renderer is a possible
  follow-up but is **not** in scope here (those renderers live in `backend/app/graph/nodes/renderers`
  and would be a backend change, violating this feature's frontend-only boundary).
- **The clause-traceability / jump-to-original feature** (Suggestion 1, folders 055–057) — unrelated.

## 6. Evaluation (metrics to log)

This feature does CRAG-adjacent work (it surfaces the retrieval-path decision) but performs **no
scoring, retrieval, or validation itself**, so it introduces **no new probabilistic measurement** and
needs no eval-harness change. Verification is deterministic frontend tests only (AC-1…AC-9) plus the
standard gate (`tsc --noEmit`, eslint, `next build`).

For context (not produced by this feature): the retrieval-path hit rate — the fraction of findings with
`path_taken == "local_kb"` vs `"web_fallback"` — is the metric this badge makes *visible to the user*
per report. It is already observable in CRAG's per-clause structured logs
(`crag_retrieval_agent.py` logs `path_taken` + `confidence_score`), and the offline eval harness already
reports per-clause-type retrieval behavior. Aggregating it across reports into a UI metric is explicitly
out of scope (§5). No false-flag / recall / retry metrics are relevant here (this feature cannot change
them).

## 7. Open questions

All open questions have been **resolved** by the owner (2026-10-02) and folded into §2 resolved decisions
and §3 acceptance criteria. Recorded here for traceability:

- **OQ-1 — Badge copy wording → RESOLVED (D7):** **"Local knowledge base"** / **"Live web search"**
  (full wording). AC-1/AC-2 assert these exact strings.
- **OQ-2 — Also label the expanded "Supporting sources" section? → RESOLVED YES (D4b / AC-10):** header
  badge **and** an evidence-section secondary label.
- **OQ-3 — Emphasize confidence next to the web-fallback badge? → RESOLVED NO (D9):** the existing
  confidence indicator is left exactly as-is (AC-6).
- **OQ-4 — Icons → RESOLVED (D8):** lucide `Database` (local KB) + `Globe` (web fallback).

No open questions remain.
