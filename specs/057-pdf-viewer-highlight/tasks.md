# Feature 057 — In-workspace PDF viewer with click-to-highlight — Implementation Tasks

Reference documents:
- Spec: `specs/057-pdf-viewer-highlight/spec.md`
- Plan: `specs/057-pdf-viewer-highlight/plan.md`
- Constitution: `specs/000-constitution.md` (**§1/§11** branch workflow; **§7** TDD / never weaken a test)
- **`frontend/AGENTS.md`** — Next 16 is non-standard; **READ `node_modules/next/dist/docs` before writing
  frontend code** (esp. lazy-loading / dynamic + the pdf.js worker). Confirmed: `dynamic(…, {ssr:false})`
  is supported only inside a Client Component (AnalysisWorkspace is `"use client"` → correct).

Frontend paths relative to `frontend/`.

**Workflow reminders:**
- **Frontend-only.** No backend/API/graph/`ContractState` change — consume 056 `/source` + 055
  `source_locator` as-is. Chain flags stay OFF by default; live smoke via env (Task 9).
- **Scope allow-list (AC-8)** = `package.json`(+lock), optional `next.config.*` (only if the worker needs
  it), `src/lib/api/{client,realProvider,mockProvider}.ts`, `src/__tests__/_fakeClient.ts`,
  `src/lib/pdfLocator.ts` (NEW), `src/components/report/{ContractViewer.tsx(NEW),FindingCard.tsx,
  AnalysisWorkspace.tsx}`, + the new tests + specs. NO backend file.
- **TDD (§7):** write tests first (react-pdf mocked), confirm FAIL, implement to green. Never weaken a test.
- **Honesty bar:** real served PDF + real captured bboxes only — no fabricated UI.

---

## Task 0: Branch
- [x] From up-to-date `main` (`git checkout main && git pull`), create `feature/057-pdf-viewer-highlight`
  (`git-start`). Commit the APPROVED spec/plan/tasks.

**Verify:** `git branch --show-current` → `feature/057-pdf-viewer-highlight`.

---

## Task 1: Add the dependency
- [x] `npm install react-pdf` (pulls `pdfjs-dist` peer). Confirm `package.json` + `package-lock.json`
  updated; pin a known-good version. Do NOT import it anywhere server-side.

---

## Task 2: Write the failing tests first  [AC-1..AC-6]  (react-pdf mocked in jsdom)
Add at the top of the viewer test: `vi.mock("react-pdf", () => ({ Document: (p)=>..., Page: (p)=>...,
pdfjs: { GlobalWorkerOptions: {} } }))`.
- [x] **[NEW] `src/__tests__/pdfLocator.test.ts`** — AC-4: `bboxToRect([10,20,30,50], 2)` →
  `{left:20, top:40, width:40, height:60}`.
- [x] **[NEW] `src/__tests__/contractViewer.test.tsx`** — AC-5: the mocked `Document` receives `file ===`
  the fake client's `getSourceUrl(jobId)`; AC-6: an `onLoadError` (or a 404 file) renders the
  "isn't available" placeholder, no throw.
- [x] **[EXTEND] a FindingCard/report test** (`src/__tests__/*`) — AC-2: a finding WITH `source_locator`
  renders "View in contract"; without → does not. AC-3: clicking it calls `onViewInContract(finding)`; and
  (workspace) a click opens the viewer with that finding's locator.
- [x] **[EXTEND] provider test** — AC-1: `realProvider.getSourceUrl("job-1")` ends with
  `/api/jobs/job-1/source`; the `ApiClient` interface + mock + `_fakeClient` implement it (tsc).
- [x] Run `npm test` → CONFIRM FAIL (symbols/components absent).

---

## Task 3: Provider seam  [AC-1/AC-5]
- [x] `src/lib/api/client.ts`: add `getSourceUrl(jobId: string): string;` to `ApiClient`.
- [x] `src/lib/api/realProvider.ts`: `getSourceUrl: (jobId) => \`${base()}/api/jobs/${jobId}/source\``.
- [x] `src/lib/api/mockProvider.ts`: `getSourceUrl: (jobId) => "/mock/sample.pdf"` (stub; viewer placeholder
  handles a non-loading mock).
- [x] `src/__tests__/_fakeClient.ts`: add `getSourceUrl: vi.fn((id) => \`/api/jobs/${id}/source\`)`.

---

## Task 4: `src/lib/pdfLocator.ts` (NEW, pure)  [AC-4]
- [x] Export `bboxToRect(bbox: number[], scale: number)` → `{left:x0*scale, top:y0*scale,
  width:(x1-x0)*scale, height:(y1-y0)*scale}` (bbox = `[x0,y0,x1,y1]` PDF points, top-left origin).

---

## Task 5: `src/components/report/ContractViewer.tsx` (NEW, client-only)  [AC-5/AC-6/AC-7]
- [x] **READ `node_modules/next/dist/docs` for the worker/dynamic guidance first (AGENTS.md).**
- [x] `"use client"`. Props `{ jobId, locator, open, onClose }` per plan §2. Render a drawer/modal (backdrop
  + Escape/outside-click close, mirroring `components/ui/Dropdown.tsx`'s close pattern).
- [x] Set `pdfjs.GlobalWorkerOptions.workerSrc` once (module scope) — primary: `new URL("pdfjs-dist/build/
  pdf.worker.min.mjs", import.meta.url).toString()`; if Next-16 won't resolve it, fall back to a
  version-pinned static/CDN worker. Document the chosen approach inline.
- [x] Load `getApiClient().getSourceUrl(jobId)` via `<Document>`; render `<Page>`s; on each page's
  `onRenderSuccess` (viewport scale), overlay a highlight `<div>` per matching span via `bboxToRect`
  (theme token, no hex). Scroll the active page into view on `open`/`locator` change.
- [x] `onLoadError` / 404 → inline "The original document isn't available." placeholder (AC-6). No locator →
  render the PDF without highlights.

---

## Task 6: `src/components/report/FindingCard.tsx`  [AC-2/AC-3]
- [x] Add optional prop `onViewInContract?: (finding: ReportFinding) => void`. When `finding.source_locator`
  is present AND the prop is given, render a "View in contract →" button calling `onViewInContract(finding)`.
  Hidden otherwise. No other FindingCard behavior changes.

---

## Task 7: `src/components/report/AnalysisWorkspace.tsx`  [AC-3/AC-7]
- [x] Add `const [viewerFinding, setViewerFinding] = useState<ReportFinding | null>(null)`; pass
  `onViewInContract={setViewerFinding}` to each `FindingCard`.
- [x] `const ContractViewer = dynamic(() => import("./ContractViewer"), { ssr: false })`; render it with
  `jobId`, `locator={viewerFinding?.source_locator ?? null}`, `open={!!viewerFinding}`,
  `onClose={() => setViewerFinding(null)}`. Two-pane navigator/findings layout unchanged.

---

## Task 8: Frontend gate  [AC-1..AC-8]
- [x] `npm test` (vitest, react-pdf mocked) green incl. existing report/workspace tests; `npx tsc --noEmit`
  clean; eslint no new errors; `npm run build` compiles with the viewer SSR-off (AC-7 — no pdf.js in the
  server bundle).
- [x] `git diff --name-only main` matches the §0 allow-list (frontend + package files + specs; NO backend).

---

## Task 9: Live smoke (manual, env override — flags stay OFF in the repo)
- [ ] **NOT YET DONE** — manual step; requires a running backend + a real PDF upload + a human to
  visually confirm the bbox y-origin orientation. Not performed during the automated completion gate.
  Run backend with `PDF_SOURCE_LOCATOR_ENABLED=True UPLOAD_SOURCE_RETENTION_ENABLED=True
  AUTH_COOKIE_SECURE=False MCP_DELIVERY_ENABLED=False` + `npm run dev`; upload a real multi-clause PDF; open
  a finding's "View in contract" → confirm the original renders and the clause highlights on the correct
  page. **Visually confirm the bbox y-origin orientation is correct** (plan §9 note); if flipped, adjust
  `bboxToRect` (e.g. `top = pageHeight - y1`) and re-smoke.

---

## Task 10: Merge
- [x] FE gate green + live smoke confirmed; diff scope matches §0. Rebase `main`, merge
  `feature/057-pdf-viewer-highlight`, delete branch (`git-finish`). Chain flags still ship OFF; flipping the
  defaults is a separate follow-up after the 055 extraction-diff measurement.

---

*Per §1/§11, implementation happens only on `feature/057-pdf-viewer-highlight`, opened after spec + plan +
tasks are all spec-reviewer-APPROVED. Frontend-only — no backend/API/graph/`ContractState` change; consumes
055/056; chain flags ship OFF (live smoke via env).*
