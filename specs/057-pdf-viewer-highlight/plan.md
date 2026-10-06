# Feature 057 — Technical plan: in-workspace PDF viewer with click-to-highlight

Branch: `feature/057-pdf-viewer-highlight` (per constitution §11).

Derived from the approved `spec.md`. **Frontend-only.** Add a `react-pdf` viewer opened on demand
(modal/drawer) from a per-finding "View in contract →" button, rendering the 056 `/source` PDF and drawing
the 055 `source_locator` bbox highlights. No backend/API/graph/`ContractState` change. Chain flags stay OFF
by default (live smoke via env). Owner decisions: modal/drawer, react-pdf, flags-off.

## 0. Scope of change (files touched)
```
frontend/package.json  (+ package-lock.json)          (add react-pdf; pdfjs-dist is its peer)
frontend/next.config.* (only if the worker needs a bundler tweak — see §2)
frontend/src/lib/api/client.ts                        (ApiClient: + getSourceUrl)
frontend/src/lib/api/realProvider.ts                  (getSourceUrl impl)
frontend/src/lib/api/mockProvider.ts                  (getSourceUrl stub)
frontend/src/__tests__/_fakeClient.ts                 (fake getSourceUrl)
frontend/src/lib/pdfLocator.ts                        (NEW — pure bbox→pixel-rect helper)
frontend/src/components/report/ContractViewer.tsx     (NEW — client-only react-pdf viewer + overlay)
frontend/src/components/report/FindingCard.tsx        ("View in contract" button when source_locator)
frontend/src/components/report/AnalysisWorkspace.tsx  (drawer state + dynamic(ssr:false) viewer wiring)
frontend/src/__tests__/*                               (NEW/updated tests)
specs/057-pdf-viewer-highlight/{spec,plan,tasks}.md
```
**NOT touched:** any backend file; the report route page already renders `<ReportView>` → `AnalysisWorkspace`.

## 1. Provider seam — `getSourceUrl` (AC-1/AC-5)
- `client.ts`: add `getSourceUrl(jobId: string): string;` to the `ApiClient` interface.
- `realProvider.ts`: `getSourceUrl: (jobId) => \`${base()}/api/jobs/${jobId}/source\`` (mirrors
  `getReportUrl`; goes through the Next proxy to the backend).
- `mockProvider.ts`: return a small bundled sample (e.g. `"/mock/sample.pdf"`) or an empty-string stub so
  dev/mock doesn't 500; the viewer's placeholder handles a non-loading mock.
- `_fakeClient.ts`: add `getSourceUrl: vi.fn((id) => \`/api/jobs/${id}/source\`)` so component tests can
  assert the viewer uses it.

## 2. `ContractViewer.tsx` (NEW, client-only) (AC-5/AC-6/AC-7)
- `"use client"`. Props: `{ jobId: string; locator: { page: number; spans: {page:number; bbox:number[]}[] } | null; open: boolean; onClose: () => void }` (the workspace passes the active finding's locator).
- Imports `Document`, `Page` from `react-pdf`; file = `getApiClient().getSourceUrl(jobId)`. Rendered inside a
  **drawer/modal** (reuse an existing overlay primitive if present, else a simple fixed-position panel with a
  backdrop + Escape/outside-click close, like the 043 Dropdown pattern).
- **Worker config (the key integration risk — AGENTS.md: read `node_modules/next/dist/docs` first):** set
  `pdfjs.GlobalWorkerOptions.workerSrc` once (module scope). Primary approach:
  `import { pdfjs } from "react-pdf"; pdfjs.GlobalWorkerOptions.workerSrc = new URL("pdfjs-dist/build/pdf.worker.min.mjs", import.meta.url).toString();`
  If the Next-16 bundler won't resolve the worker URL, fall back to a version-pinned static/CDN worker
  (`pdf.worker.min.mjs` matching the installed pdfjs-dist version). The implementer verifies which works in
  `next build` + runtime; document the choice inline.
- **Highlight overlay:** on each `Page`'s `onRenderSuccess` (gives the rendered viewport/scale), for every
  span whose `page === pageNumber`, compute a rect via `bboxToRect` (§3) and absolutely-position a
  semi-transparent highlight `<div>` over the page canvas (theme token, no hex). Scroll the active page into
  view when `open` + `locator` change.
- **Graceful states (AC-6):** `Document` `onLoadError` / a fetch 404 → render an inline
  "The original document isn't available." placeholder; never throw. No `locator` → render the PDF with no
  highlights (still useful).

## 3. `pdfLocator.ts` (NEW, pure) (AC-4)
- `bboxToRect(bbox: number[], scale: number): { left: number; top: number; width: number; height: number }`
  — `bbox = [x0, y0, x1, y1]` in PDF points (pdf.js `get_text("dict")` origin = top-left, matching
  react-pdf's default viewport). Returns `{ left: x0*scale, top: y0*scale, width: (x1-x0)*scale,
  height: (y1-y0)*scale }`. Pure, unit-tested with a known bbox+scale (no pdf.js).

## 4. `FindingCard.tsx` (AC-2/AC-3)
- Add an optional prop `onViewInContract?: (finding: ReportFinding) => void`. When `finding.source_locator`
  is present AND `onViewInContract` is provided, render a small **"View in contract →"** button (in the
  header or the expanded body) that calls `onViewInContract(finding)`. Hidden when `source_locator` is
  null/absent (old reports / DOCX / flags-off) — AC-2. No change to any existing FindingCard behavior.

## 5. `AnalysisWorkspace.tsx` (AC-3/AC-7)
- Add state: `const [viewerFinding, setViewerFinding] = useState<ReportFinding | null>(null)`.
- Pass `onViewInContract={setViewerFinding}` to each `FindingCard`.
- Dynamically import the viewer SSR-off: `const ContractViewer = dynamic(() => import("./ContractViewer"),
  { ssr: false })` (keeps pdf.js out of the server bundle — AC-7). Render
  `<ContractViewer jobId={jobId} locator={viewerFinding?.source_locator ?? null} open={!!viewerFinding}
  onClose={() => setViewerFinding(null)} />`. The drawer jumps to the locator's first page + highlights.
- The existing navigator/findings two-pane layout is unchanged (D1 — viewer is on-demand overlay).

## 6. Tests (TDD — write first, confirm failing, then implement). Mock `react-pdf` in jsdom.
- **provider** (`__tests__/provider*`/new): AC-1 — `realProvider.getSourceUrl("job-1") === "/api/jobs/job-1/source"` (base-relative); interface + mock implement it (tsc).
- **pdfLocator** (new): AC-4 — `bboxToRect([10,20,30,50], 2)` → `{left:20, top:40, width:40, height:60}`.
- **FindingCard** (extend `__tests__`): AC-2 — a finding with `source_locator` renders "View in contract";
  one without does not. AC-3 — clicking it calls `onViewInContract` with the finding.
- **AnalysisWorkspace/viewer** (new): mock `react-pdf` (`vi.mock("react-pdf", () => ({ Document: stub, Page:
  stub, pdfjs: { GlobalWorkerOptions: {} } }))`); AC-3 — clicking a finding's button opens the viewer with
  that finding's locator; AC-5 — the viewer's `Document` file prop === `getSourceUrl(jobId)` (via fake
  client); AC-6 — an `onLoadError`/404 path renders the placeholder.
- **Build/SSR** (AC-7): `next build` passes with the viewer dynamically imported `ssr:false` (verified in the
  gate, not a unit test).

## 7. Correctness / constitution
- **§1/§11 frontend-only:** no backend/API/graph/`ContractState` change; consumes 055/056 as-is.
- **Honesty bar:** shows the REAL served PDF + REAL captured bboxes; no fabricated score/chat/impact.
- **Graceful degradation (D2):** no locator → no button; `/source` down → placeholder; pre-chain reports
  look exactly like today.
- **Flags OFF (D4):** nothing flips the backend defaults; the live smoke uses env overrides.

## 8. Verification gate (all offline + one live smoke)
- `npm install` adds react-pdf (lockfile updated). `npm test` (vitest, react-pdf mocked) green incl. existing
  report/workspace tests; `npx tsc --noEmit` clean; eslint no new errors; `npm run build` compiles with the
  viewer SSR-off (AC-7).
- `git diff --name-only main` == §0 allow-list (frontend + package files + specs only).
- **Live smoke (manual, env override, like 059):** run the backend with `PDF_SOURCE_LOCATOR_ENABLED=True
  UPLOAD_SOURCE_RETENTION_ENABLED=True AUTH_COOKIE_SECURE=False` + frontend, upload a real PDF, open a
  finding's "View in contract", confirm the original renders and the clause is highlighted on the right page.

## 9. Risks / limitations
- **pdf.js worker + Next 16 (primary risk):** worker resolution is the fiddly part; §2 gives a primary +
  CDN-fallback approach; verify in `next build` + runtime. READ `node_modules/next/dist/docs` before writing
  the component (AGENTS.md).
- **bbox precision:** best-effort (055 OQ-2 dict-vs-plain diff); a few-pixel drift is acceptable (EC-7).
- **Old reports / DOCX:** no locators → no highlights (graceful, EC-1/EC-2).
- **New dependency weight:** react-pdf/pdfjs-dist is sizable but lazy-loaded (dynamic, drawer-only) so it
  doesn't bloat the initial bundle.

## 10. Merge
Full FE gate green + live smoke confirmed; diff scope matches §0. Rebase `main`, merge
`feature/057-pdf-viewer-highlight`, delete branch (`git-finish`). Chain flags still ship OFF; flipping the
defaults is a separate follow-up after the 055 extraction-diff measurement.
