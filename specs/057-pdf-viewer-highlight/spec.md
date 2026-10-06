# Feature 057 — Spec: In-workspace PDF viewer with click-to-highlight

Status: DRAFT (pre spec-reviewer gate)
Branch: `feature/057-pdf-viewer-highlight` (constitution §11).

> Final piece of the "Suggestion 1 — clause traceability" chain (**055 locator capture ✅ → 056 serve-
> original ✅ → 057 viewer**). 057 renders the original uploaded PDF in the report workspace and, for each
> finding, lets the user jump to the exact page and see the clause highlighted — making the 055
> `source_locator` + 056 `/source` endpoint visible. **Frontend-only.**

## 1. Problem statement

Clause traceability is now captured (055: each finding carries a `source_locator` = pages + per-line
bboxes) and the original PDF is retrievable (056: `GET /api/jobs/{id}/source`). But the report workspace
still has no way to *see* it: `AnalysisWorkspace` is deliberately a clause **navigator + findings panel**,
"NOT a document viewer" (022 D1). So a reader can read a finding's risk but cannot see where that clause
physically lives in the contract.

This feature adds an **in-workspace PDF viewer** that renders the original (from `/source`) and a
**"view in contract →"** affordance on each finding: clicking it jumps the viewer to the finding's page
and draws a highlight overlay at its `source_locator` bbox(es). It degrades gracefully when the source or
locator is unavailable (old reports, DOCX, flags-off).

### Position relative to the constitution
- **Frontend-only, presentation layer.** No backend/graph/node/edge/`ContractState`/API change (it consumes
  the existing 056 `/source` endpoint and the 055 `source_locator` already on `ReportFinding`). Per §1/§11 on
  `feature/057-pdf-viewer-highlight`.
- **New frontend dependency** (`react-pdf` / `pdfjs-dist`) added to `frontend/package.json`. 002-tech-stack
  is backend-only (Python); frontend deps are governed by the 013-established Next.js stack, so this is a
  normal frontend-stack addition, not a 002 amendment.
- **022 evolution (not a conflict):** 022 D1 scoped the workspace as a navigator "not a document viewer";
  057 deliberately supersedes that by adding the viewer now that the locator data exists. No honesty-bar
  regression — the viewer shows the *real* uploaded PDF and *real* captured bboxes (nothing fabricated).
- **Reversible / graceful:** the "view in contract" affordance only appears when a finding has a
  `source_locator`; the viewer only loads when `/source` succeeds. Old reports (analyzed with the chain
  flags off) simply have no locators / no served source and show the workspace exactly as today.

## 2. Inputs and outputs

### Provider seam
- Add **`getSourceUrl(jobId: string): string`** to the `ApiClient` interface + `realProvider`
  (`${base}/api/jobs/${jobId}/source`) + `mockProvider` (a fixture PDF URL or a data-URL stub for offline
  dev/tests). Mirrors the existing `getReportUrl(jobId, format)`.

### Inputs (already present, no new backend)
- `ReportFinding.source_locator?: { pages: number[]; spans: { page: number; bbox: number[] }[] } | null`
  (055, already in `types.ts`).
- `GET /api/jobs/{id}/source` → `application/pdf` (056): 200 with bytes, 404 if unavailable, 415 for DOCX.

### Frontend components
- **`ContractViewer`** (new, client-only): given `jobId`, loads the PDF from `getSourceUrl(jobId)` via
  `react-pdf` (pdf.js). Renders pages; exposes an imperative/prop API to **scroll to a page** and draw a
  **highlight overlay** at a given list of bboxes (converting PDF-point bboxes → rendered-pixel rects using
  the page's render scale/viewport). pdf.js is **client-only** — the component is dynamically imported with
  SSR disabled and the worker configured for the Next bundler (see §4 risks). On `/source` 404/415/error it
  renders an inline "Original document isn't available" placeholder (no crash).
- **`FindingCard`**: when `finding.source_locator` is present, show a **"View in contract →"** button; on
  click it calls a workspace callback with the finding's `clause_id` (+ its first page / bboxes). Hidden
  when `source_locator` is null (old reports / DOCX / flags-off) — AC.
- **`AnalysisWorkspace`**: wire the viewer in (layout per OQ-1) and own the "active locator" state so a
  "view in contract" click drives the `ContractViewer` to the right page + highlight, reusing the existing
  `activeId`/selection plumbing.

### Resolved decisions (inline)
- **D1 — Frontend-only; consume existing 056/055.** No backend change.
- **D2 — Graceful degradation is first-class.** No `source_locator` → no "view in contract" button; `/source`
  unavailable → viewer placeholder. The workspace is unchanged for pre-chain reports.
- **D3 — bbox→pixel mapping via the page viewport.** 055 bboxes are in PDF points (top-left origin from
  `get_text("dict")`); the overlay converts them with the rendered page's scale, matching pdf.js's
  coordinate space. Multiple spans → multiple highlight rects (precise, per 055 OQ-1).
- **D4 — Chain flags stay OFF by default; live smoke via env override.** 057 does NOT flip the backend
  defaults (`PDF_SOURCE_LOCATOR_ENABLED` / `UPLOAD_SOURCE_RETENTION_ENABLED`) — the 055 extraction-diff
  measurement (055 Task 12) has not been run, so a blind default-flip is deferred. The end-to-end live smoke
  runs the stack with those two env vars set True (like 059's smoke); the default-flip is a separate
  follow-up once the measurement is clean.

## 3. Acceptance criteria

Frontend, offline (vitest + tsc + eslint + build). pdf.js is mocked in component tests (it needs a real
browser canvas/worker); the viewer's data flow + the FindingCard affordance + the bbox→rect mapping are
unit-tested with the pdf.js render layer stubbed.

- **AC-1 (provider seam):** `getSourceUrl("job-1")` returns `/api/jobs/job-1/source` (realProvider); the
  `ApiClient` interface + mockProvider implement it; tsc + any provider-contract test pass.
- **AC-2 ("view in contract" shown only with a locator):** a `FindingCard` for a finding WITH
  `source_locator` renders a "View in contract" control; a finding with `source_locator: null` does NOT.
- **AC-3 (click drives the viewer):** clicking "View in contract" on a finding invokes the workspace
  callback with that finding's `clause_id` and target page/bboxes; the workspace sets the viewer's active
  page + highlight to that finding.
- **AC-4 (bbox→rect mapping):** the pure mapping helper converts a PDF-point bbox + page scale into the
  correct pixel rect (left/top/width/height), verified on a known bbox + scale (no pdf.js needed).
- **AC-5 (source loaded from the endpoint):** `ContractViewer` requests the PDF from `getSourceUrl(jobId)`
  (asserted via the mocked provider/react-pdf file prop) — never a client-supplied path.
- **AC-6 (graceful unavailable):** when `/source` yields an error/404 (mocked), the viewer shows an
  "original not available" placeholder and does not throw; the rest of the workspace still renders.
- **AC-7 (SSR-safe):** the viewer is a client-only dynamic import (no pdf.js evaluated during SSR);
  `next build` succeeds and the report page prerenders without pulling pdf.js into the server bundle.
- **AC-8 (no backend / honesty-bar regression):** `git diff main` touches only frontend files +
  `package.json`/lockfile + the specs; no backend/API change. No fabricated data (the viewer shows the real
  served PDF + real captured bboxes). `npm test`, `tsc`, eslint, `next build` all pass; the existing
  report/workspace tests stay green.

## 4. Edge cases
- **EC-1 — Report analyzed with the chain OFF (most existing reports):** findings have
  `source_locator: null` → no "view in contract" anywhere; the workspace is byte-identical to today. The
  viewer either isn't shown or shows the placeholder (OQ-1 decides whether it renders at all when no
  finding has a locator).
- **EC-2 — DOCX contract:** `/source` → 415; no `source_locator` on findings (055 is PDF-only) → no "view
  in contract"; viewer placeholder if shown.
- **EC-3 — `/source` 404 (retention off + terminal-deleted on Turso, or source vanished):** viewer
  placeholder (AC-6); findings may still have locators but the document can't be shown — the button can
  surface a "original no longer available" toast rather than a broken view.
- **EC-4 — Cross-page clause (`pages.length > 1`):** "view in contract" jumps to the first page; the
  highlight draws each span on its own page (visible as the user scrolls). 
- **EC-5 — pdf.js worker/canvas unavailable (jsdom tests):** pdf.js is mocked in tests; the real worker is
  only needed in the browser (AC-7 keeps it client-only).
- **EC-6 — Very large PDF:** react-pdf renders lazily/per-page; bounded by the 25 MB upload cap. Acceptable.
- **EC-7 — bbox slightly off (dict-vs-plain extraction diff, 055 OQ-2):** highlights are best-effort; a
  few-pixel drift is acceptable and does not break the view.

## 5. Out of scope
- **Flipping the backend chain-flag defaults to True** (D4) — deferred to a separate change after the 055
  extraction-diff measurement; 057 smokes via env override.
- **Any backend/API/graph/`ContractState` change** — consumes 055/056 as-is.
- **Editing/annotating/downloading-with-highlights the PDF** — view + highlight only.
- **DOCX rendering** (415) and DOCX→PDF conversion — out of the PDF-only chain.
- **Highlighting in the exported PDF/Markdown report** (a static report can't interactively highlight;
  055 already carries the data if a future static-render wants it).
- **Re-analyzing old reports to backfill locators** — only new runs (chain on) get them.

## 6. Evaluation (metrics to log)
No accuracy/retrieval change (pure presentation of existing data). No eval-harness change. Optional
client-side debug log: viewer load success/placeholder, and the count of findings with a `source_locator`
(locator coverage visible in the UI). The 055 extraction-diff measurement (gating the default-flip) is
tracked under 055 Task 12, not here.

## 7. Open questions

All resolved by the owner (2026-10-05); they confirm the spec's primary design (already in §2 / the
decisions) — no scope change:
- **OQ-1 — Viewer layout → RESOLVED: modal/drawer on demand.** "View in contract" opens the viewer as an
  overlay/drawer (jumps to the page + highlight); today's two-pane navigator+findings layout is kept and the
  viewer renders only when opened (lowest-risk; pdf.js not loaded until needed).
- **OQ-2 — PDF library → RESOLVED: `react-pdf`** (pdf.js wrapper), with the Next-16 worker config.
- **OQ-3 — Default-flag flip → RESOLVED: keep defaults OFF (D4).** Ship 057 with the chain flags off; run
  the live smoke with `PDF_SOURCE_LOCATOR_ENABLED` + `UPLOAD_SOURCE_RETENTION_ENABLED` set via env; defer the
  default-flip until the 055 extraction-diff measurement (055 Task 12) is run.

No open questions remain.
