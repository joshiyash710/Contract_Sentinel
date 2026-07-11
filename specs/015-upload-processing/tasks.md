# Upload + Live Processing — Implementation Tasks

Reference documents:
- Spec: `specs/015-upload-processing/spec.md`
- Plan: `specs/015-upload-processing/plan.md`
- API contract consumed: `specs/011-pipeline-runner-api/spec.md` §2
- Foundation reused: feature 013 (`frontend/src/lib/api/*`, `frontend/src/components/ui/*`)
- Constitution: `specs/000-constitution.md`
- Design references: `specs/013-frontend-design-system/design-refs/` screen 9 (`…31 PM (8).jpeg`, upload) + screen 6 (`…31 PM (5).jpeg`, processing)

All paths below are relative to `frontend/` unless stated. **No file under `backend/` is created or modified** (spec AC-18).

**Workflow reminders:**
- TDD per constitution §7 — write tests, confirm FAILING, then implement to PASS. Never weaken a test to force a pass.
- Reach the backend **only** through `getApiClient()` (013 seam). No component imports `realProvider`/`mockProvider` directly (spec AC-16).
- Consume the 011 contract via `@/lib/api/types.ts` unchanged — invent no field names (spec AC-17).
- Client file validation mirrors 011 (`.pdf`/`.docx`, 25 MB) but the **server stays authoritative** (spec D1/EC-4).
- **`"use client"` directive** is required on `DropZone`, `UploadForm`, `ProcessingView`, `useJobEvents` (they use hooks/browser APIs). `ProcessingArt` and the two `page.tsx` files stay server components (review B4).
- **NEVER run `next build` while `next dev` is running** — it corrupts `.next` (learned in 013). Stop the dev server before any build.
- Locked defaults (spec §6): **OQ1=(a)** stay on `/jobs/[id]` with an "Analysis complete" panel; **OQ2=(a)** report link opens `?format=md` in a new tab; **OQ3=minimal** SSE-drop recovery (manual refresh re-subscribes; 011 buffer replays).

---

## Task 0: Start the feature branch

- [ ] Confirm `spec.md`, `plan.md`, `tasks.md` exist and are approved (constitution §1/§11 gate).
- [ ] From an up-to-date `main`, create/checkout `feature/015-upload-processing` (the `git-start` skill does this).

**Verify:** `git branch --show-current` → `feature/015-upload-processing`. The 013 work is already on `main`.

---

## Task 1: `lib/upload.ts` — client validation (tests first)

- [ ] **[NEW] `src/__tests__/upload-validation.test.ts`** — confirm FAILING:
  - `accepts_pdf_and_docx`: `validateFile` returns `{ok:true}` for a `.pdf` and a `.docx` (use `new File(["x"], "c.pdf")`).
  - `rejects_other_extension`: `.txt` / `.png` → `{ok:false, error:"type"}` (spec AC-4).
  - `rejects_empty`: a 0-byte file → `{ok:false, error:"empty"}` (spec AC-6).
  - `rejects_oversize`: a file with `size > 25*1024*1024` → `{ok:false, error:"size"}` (spec AC-5). (Build one via `Object.defineProperty(file, "size", { value: 26*1024*1024 })`.)
- [ ] **[NEW] `src/lib/upload.ts`** — implement exactly per plan §3.1: export `ACCEPTED_EXTENSIONS`, `MAX_UPLOAD_BYTES` (25 MB), `ACCEPT_ATTR = ".pdf,.docx"`, `type FileError`, and `validateFile(file)`.

**Verify:** `npx vitest run src/__tests__/upload-validation.test.ts` → PASS.

---

## Task 2: `lib/jobLabels.ts` — node → friendly label (tests first)

- [ ] **[NEW] `src/__tests__/job-labels.test.ts`** — confirm FAILING:
  - `maps_all_seven`: each of `ingest_agent, clause_splitter, crag_retrieval, self_rag_validation, risk_score, redline, skip_redline, report` maps to its label; `nodeLabel("redline") === nodeLabel("skip_redline")` (011 §2.4).
  - `unknown_falls_back`: `nodeLabel("nope") === "Analyzing…"` and `nodeLabel(null) === "Analyzing…"` (spec AC-11).
- [ ] **[NEW] `src/lib/jobLabels.ts`** — implement `NODE_LABELS` + `nodeLabel(node?)` exactly per plan §3.2.

**Verify:** `npx vitest run src/__tests__/job-labels.test.ts` → PASS.

---

## Task 3: shared test util `_fakeClient.ts` (no test of its own; used by later tasks)

- [ ] **[NEW] `src/__tests__/_fakeClient.ts`** — a helper for processing/upload tests that need scripted backend behavior the 013 mock can't produce (review B2). Export:
  - `makeFakeClient(opts)` returning an `ApiClient` (import the interface from `@/lib/api/client`) where:
    - `openJobEvents(jobId, handlers)` replays `opts.events: ProgressEvent[]` via `setTimeout(…, i*1)`, calling `onProgress` for `event==="progress"` and `onTerminal` otherwise; if `opts.emitError` is set, calls `handlers.onError(new Error("boom"))` instead; returns an unsubscribe that cancels pending timers. Emitting `[]` leaves the view in `connecting` (EC-8).
    - `submitAnalysis` resolves `opts.accepted ?? { job_id: "job-1", status: "queued", submitted_at: "t" }`, or rejects `opts.submitError` if provided (used for EC-3/EC-4).
    - `getJob`, `getReportUrl`, `health` — minimal sane stubs (`getReportUrl` returns `/api/jobs/${id}/report?format=${fmt}`).
  - Helper builders: `progress(node, index, total)` and `terminal(event, final)` returning `ProgressEvent`s; a `completedFinal(overrides?)` returning a valid `JobStatus`.

**Verify:** `npx tsc --noEmit` compiles (no test yet; it's a util).

---

## Task 4: `lib/useJobEvents.ts` — SSE state hook (tests first)

- [ ] **[NEW] `src/__tests__/useJobEvents.test.tsx`** — confirm FAILING. Use `@testing-library/react`'s `renderHook`; mock the seam per test: `vi.mock("@/lib/api/provider", () => ({ getApiClient: () => fake }))` with `makeFakeClient` (Task 3):
  - `subscribes_and_unsubscribes`: on mount `openJobEvents` is called once; unmount calls the returned unsubscribe (spec AC-9). (Track via spies on the fake.)
  - `progress_updates_state`: after emitting `progress("clause_splitter",2,4)`, state `phase==="running"`, `node`, `index===2`, `total===4`, `completedNodes` includes the node.
  - `terminal_completed_sets_final`: emitting `terminal("completed", completedFinal())` → `phase==="completed"`, `final` populated.
  - `error_sets_recoverable_state`: `emitError` → `phase==="error"` with `errorMessage`, UNLESS already terminal.
- [ ] **[NEW] `src/lib/useJobEvents.ts`** — `"use client"`; implement exactly per plan §3.3 (state shape `JobEventsState`, `phase` union, subscribe in `useEffect` keyed on `[jobId, reconnectKey]`, `closed` guard + cleanup, `reconnect()` bumps `reconnectKey`). Per review B1, do NOT copy `final.error.message` into `errorMessage` on completion — leave `errorMessage` for the `error` phase only.

**Verify:** `npx vitest run src/__tests__/useJobEvents.test.tsx` → PASS.

---

## Task 5: Upload screen (tests first)

- [ ] **[NEW] `src/__tests__/upload.test.tsx`** — confirm FAILING. Mock router: `vi.mock("next/navigation", () => ({ useRouter: () => ({ push }) }))` with a `push = vi.fn()`. Use the real 013 mock provider for the happy path; use `makeFakeClient` (via `vi.mock` provider) for the error-mapping test. Tests (spec AC-1…AC-8, EC-3/EC-4):
  - `renders_stepper_and_zone`: Stepper with step 1 ("Upload") current; "Upload New Contract" heading; PDF + DOCX icon chips present, **no "TXT"** text; "Browse Files" button (AC-1).
  - `valid_file_submits_and_navigates`: firing `change` on the hidden input with a `.pdf` calls `submitAnalysis` once and `push` with `/jobs/<job_id>` (AC-2).
  - `drop_behaves_like_browse`: `fireEvent.drop` on the zone with a valid file → same submit + navigate (AC-3).
  - `invalid_type_blocks_submit`: a `.txt` file → inline error text naming PDF/DOCX; `submitAnalysis` NOT called (AC-4).
  - `oversize_blocks_submit`: a >25 MB file → error; no submit (AC-5).
  - `empty_blocks_submit`: 0-byte file → error; no submit (AC-6).
  - `busy_state_prevents_double_submit`: with a slow `submitAnalysis`, the button is disabled during flight and a second file is ignored (AC-7).
  - `no_external_or_recipient_ui`: no "Google Drive"/"Dropbox"/"connect" text, no email/recipient field (AC-8).
  - `submit_network_error_inline`: fake client `submitError = new ApiError("net")` (no status) → "couldn't reach the server" inline error, `push` NOT called (EC-3/AC-19).
  - `submit_400_and_413_mapped`: `submitError = new ApiError("bad",400)` → "unsupported or empty file"; `new ApiError("big",413)` → "file too large" (EC-4).
- [ ] **[NEW] `src/components/upload/DropZone.tsx`** — `"use client"`; per plan §3.4 (dashed zone, PDF+DOCX chips, hidden `<input type="file" accept=".pdf,.docx">`, Browse button, drag handlers; single `onFile(file)` prop for both browse + drop).
- [ ] **[NEW] `src/components/upload/UploadForm.tsx`** — `"use client"`; per plan §3.5 (Stepper + heading + DropZone + inline error slot; `onFile` runs `validateFile` then `getApiClient().submitAnalysis` → `router.push('/jobs/'+job_id)`; busy state; catch `ApiError` and map 400/413/other; no external/recipient UI).
- [ ] **[NEW] `src/app/upload/page.tsx`** — server component: `<TopBar title="Contract Upload" userName="Sarah Jenkins" />` + centered `<UploadForm/>` in a padded container.

**Verify:** `npx vitest run src/__tests__/upload.test.tsx` → PASS.

---

## Task 6: Processing screen (tests first)

- [ ] **[NEW] `src/__tests__/processing.test.tsx`** — confirm FAILING. Mock router (`push`) and inject `makeFakeClient` via `vi.mock("@/lib/api/provider")` per test. Tests (spec AC-9…AC-15, EC-1/2/6/8):
  - `renders_connecting_before_first_event`: fake emits `[]` → "starting"/"queued" state shown, no 0-width bar / no crash (EC-8).
  - `renders_progress`: emit `progress("clause_splitter",2,4)` → friendly label "Breaking the document into clauses" + "Step 2 of 4" + a `ProgressBar` at 50% (`aria-valuenow≈50`) — assert against the fixture's real `total=4` (AC-10, review N5).
  - `unknown_node_generic_label`: `progress("nope",1,4)` → "Analyzing…" (AC-11).
  - `completed_shows_report_link`: emit `terminal("completed", completedFinal({report_available:true}))` → "Analysis complete" + a link whose href is `/api/jobs/<id>/report?format=md`; a "View JSON" link → `?format=json` (AC-12).
  - `ingest_error_soft_state`: `terminal("completed", completedFinal({error:{kind:"ingest_error",message:"bad pdf"}, report_available:false}))` → completed-with-issue variant showing "bad pdf", no report link (AC-13/EC-1).
  - `failed_shows_retry`: `terminal("failed", completedFinal({status:"failed"}))` → error state + "Retry" that calls `push('/upload')` (AC-14/EC-2).
  - `already_finished_lands_terminal`: fake emits ONLY a terminal event immediately → terminal state, no hang (AC-15).
  - `error_phase_refresh_reconnects`: `emitError` → "connection lost" state; clicking "Refresh" re-invokes `openJobEvents` (spy call count increases) (EC-5/EC-6).
- [ ] **[NEW] `src/components/processing/ProcessingArt.tsx`** — decorative glowing shield/document (CSS/SVG using accent-gradient + glow tokens). No data/API. (Server component OK.)
- [ ] **[NEW] `src/components/processing/ProcessingView.tsx`** — `"use client"`; per plan §3.6: calls `useJobEvents(jobId)` and renders by `phase` (`connecting`/`running`/`completed`/`failed`/`error`). `running` uses `nodeLabel` + "Step {index} of {total}" + `ProgressBar` (guard `total>0`) + a step trace from `completedNodes`. `completed` panel: report link (`getReportUrl(jobId,'md')`, new tab) + "View JSON"; EC-1 branch on `state.final?.error`; report link only when `final.report_available`. `failed` → Retry → `/upload`. `error` → "connection lost" + Refresh → `reconnect()`.
- [ ] **[NEW] `src/app/jobs/[jobId]/page.tsx`** — server component: read `params.jobId`, render a full-bleed dark container with `<ProcessingView jobId={params.jobId} />` (no TopBar title — immersive look).

**Verify:** `npx vitest run src/__tests__/processing.test.tsx` → PASS.

---

## Task 7: Shell wiring + boundary tests

- [ ] **[MODIFY] `src/components/shell/Sidebar.tsx`** — change the `Contracts` `NAV_ITEMS` entry `href` from `/contracts` to `/upload` (spec D5).
- [ ] **[MODIFY] `src/app/contracts/page.tsx`** — replace the placeholder body with `import { redirect } from "next/navigation"; export default function () { redirect("/upload"); }` (call at top level, no try/catch — review N1).
- [ ] **[NEW] `src/__tests__/upload-boundary.test.ts`** — boundary checks (spec AC-16/AC-17/AC-18):
  - `screens_use_getApiClient_only`: read the files under `src/components/upload` and `src/components/processing`; assert none contains `realProvider` or `mockProvider` import (AC-16).
  - (AC-18 no-backend-edits is verified in Task 8 via `git diff`; AC-17 via `tsc`.)
- [ ] Confirm the existing 013 `shell.test.tsx` still passes (Sidebar still renders five items; the href change doesn't break `sidebar_five_items`/active tests — active is by `startsWith(href)`, and `/upload` is a valid href).

**Verify:** `npx vitest run` (whole suite) → all PASS, including the untouched 013 tests.

---

## Task 8: Full verification pass

- [ ] `npx vitest run` — entire suite GREEN (013 + 015).
- [ ] `npx tsc --noEmit` — no type errors (AC-17 drift-lock holds).
- [ ] `npm run lint` — clean.
- [ ] **Stop the dev server if running**, then `npx next build` — succeeds (routes `/upload`, `/jobs/[jobId]` appear; `/jobs/[jobId]` is dynamic).
- [ ] `git diff --name-only` — confirm **no** path under `backend/` changed (spec AC-18).

**Verify:** all green; build lists the two new routes.

---

## Task 9: Live end-to-end smoke against the real backend (spec AC-20)

- [ ] Stop the dev server. Ensure the backend is running: `uvicorn app.api.main:app --host 127.0.0.1 --port 8000` (and Ollama up). 
- [ ] Create `frontend/.env.local` with `NEXT_PUBLIC_API_PROVIDER=real` and `NEXT_PUBLIC_API_BASE_URL=` (empty → same-origin via the dev proxy; do NOT set a direct `:8000` URL — CORS footgun, review N4).
- [ ] `npm run dev`; open `http://localhost:3000/upload`; upload a real `.pdf`.
- [ ] Confirm: navigates to `/jobs/{id}`; the SSE stream shows ≥1 `progress` step per node in order (slow — minutes, per constitution §9); ends on "Analysis complete"; the report link opens the markdown. Note the result.
- [ ] Reset `.env.local` provider back to `mock` (or delete it) so the default dev/test posture is mock again.

**Verify:** a real upload runs end-to-end through the browser → live SSE → report link. Report the outcome to the user (this is the "run the real smoke before continuation" practice).

---

## Task 10: Finish the feature branch

- [ ] Full suite + `tsc` + `next build` green (Task 8); live smoke noted (Task 9).
- [ ] Rebase latest `main` into the branch, resolve conflicts on the branch (constitution §11), merge to `main`, delete the branch (the `git-finish` skill).

**Verify:** on `main`; `feature/015-upload-processing` gone; suite + build green on `main`.

---

*Per constitution §1/§11, implementation happens only on `feature/015-upload-processing`, opened after spec + plan + tasks are approved. Later specs (016 workspace/chat/comparison, 017 reports+history, 018 dashboards/settings) build the remaining screens.*
