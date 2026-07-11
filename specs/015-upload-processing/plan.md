
# Upload + Live Processing — Technical Plan

## Git Branch

`feature/015-upload-processing` — branching workflow per `specs/000-constitution.md` §11.

---

## 1. Overview

This plan implements the **upload** and **live processing** screens specified in
`specs/015-upload-processing/spec.md` — the first UI that drives the real feature-011
FastAPI+SSE backend. It builds on the 013 foundation (design tokens, app shell, UI
primitives, and the mock/real API-client seam); it adds **no backend change** (spec AC-18)
and reaches the backend **only** through `getApiClient()` (013 seam), which honors
`NEXT_PUBLIC_API_PROVIDER` (default `mock` for tests, `real` for the live smoke via the
013 Next dev proxy).

**Two routes (spec D5):**
- `/upload` — the upload screen (`UploadForm` + drop zone). On a valid file it calls
  `apiClient.submitAnalysis(file)` → `202 { job_id }` and `router.push('/jobs/' + job_id)`.
- `/jobs/[jobId]` — the live processing screen, driven by `apiClient.openJobEvents(jobId, …)`
  (SSE), rendering the friendly node label + "Step {index}/{total}" + `ProgressBar`, and the
  terminal completed / failed / completed-with-ingest-error states.

**Locked open-question defaults (spec §6):**
- **OQ1 = (a)** — on `completed`, stay on `/jobs/[jobId]` and show an "Analysis complete"
  panel with a report link (no auto-redirect; the richer report route is spec 017).
- **OQ2 = (a)** — the report action opens `GET /api/jobs/{id}/report?format=md` directly in a
  new tab (plus a JSON option), so the end-to-end smoke is genuinely complete today.
- **OQ3 = minimal** — on an SSE drop, show a "connection lost" state with a manual refresh
  that re-opens the stream (011's per-job buffer replays on re-subscribe, so this fully
  recovers); no auto-retry/backoff in this feature.

**Consumes the 011 contract unchanged.** All shapes come from `frontend/src/lib/api/types.ts`
(the 013 mirror of 011 §2). No new/divergent field names (spec AC-17). Client-side file
validation mirrors 011's `ALLOWED_UPLOAD_EXTENSIONS` / `MAX_UPLOAD_SIZE_BYTES` but the server
stays authoritative (spec D1, EC-4).

---

## 2. Files to Create / Modify (all under `frontend/`)

```
src/
  lib/
    upload.ts                 [NEW] accepted extensions + max size (mirror 011) + validateFile()
    jobLabels.ts              [NEW] node-name → friendly label map (spec §2.2)
    useJobEvents.ts           [NEW] React hook wrapping apiClient.openJobEvents → typed state
  components/
    upload/
      DropZone.tsx            [NEW] dashed drag-&-drop + hidden file input + Browse button
      UploadForm.tsx          [NEW] stepper + heading + DropZone + inline errors + submit/navigate
    processing/
      ProcessingArt.tsx       [NEW] the glowing shield/document artwork (decorative, CSS/SVG)
      ProcessingView.tsx      [NEW] consumes useJobEvents → live progress + terminal states
  app/
    upload/page.tsx           [NEW] renders <TopBar title="Contract Upload"> + <UploadForm/>
    jobs/[jobId]/page.tsx     [NEW] full-bleed processing screen → <ProcessingView jobId=…/>
    contracts/page.tsx        [MODIFY] redirect('/upload') (Contracts nav is the upload entry, D5)
  components/shell/Sidebar.tsx [MODIFY] NAV_ITEMS "Contracts" href '/contracts' → '/upload'
  __tests__/
    upload.test.tsx           [NEW] AC-1..AC-8
    processing.test.tsx       [NEW] AC-9..AC-15, EC-1/2/6
    useJobEvents.test.tsx     [NEW] hook lifecycle (subscribe/unsubscribe, state transitions)
    upload-validation.test.ts [NEW] validateFile() unit (D1: ext/size/empty)
    job-labels.test.ts        [NEW] label map incl. redline/skip → same label, unknown fallback
```

Nothing else in 013 is touched except the two `[MODIFY]`s above. No `backend/` file (AC-18).

---

## 3. Design details

> **Client vs. server components (Next.js App Router — constitution §8, review B4).** These four
> components MUST begin with the `"use client"` directive because they use hooks / browser APIs:
> `DropZone` (drag handlers, `useRef` file input), `UploadForm` (`useState`, `useRouter`),
> `ProcessingView` (calls `useJobEvents`), and `useJobEvents.ts` (hook). `ProcessingArt` is
> static markup and may stay server (no directive needed). The two `page.tsx` files
> (`app/upload/`, `app/jobs/[jobId]/`) stay **server** components that render these client
> children — which is correct only because the children carry their own `"use client"`.

### 3.1 `[NEW] src/lib/upload.ts` — client validation (spec D1)

Mirrors the 011 boundary constants so the UX rejects early; the server remains authoritative.

```ts
export const ACCEPTED_EXTENSIONS = [".pdf", ".docx"] as const;   // mirrors 011 ALLOWED_UPLOAD_EXTENSIONS
export const MAX_UPLOAD_BYTES = 25 * 1024 * 1024;                // mirrors 011 MAX_UPLOAD_SIZE_BYTES (25 MB)
export const ACCEPT_ATTR = ".pdf,.docx";                         // <input accept="…">

export type FileError = "type" | "size" | "empty";

export function validateFile(file: File): { ok: true } | { ok: false; error: FileError; message: string } {
  const lower = file.name.toLowerCase();
  const okExt = ACCEPTED_EXTENSIONS.some((e) => lower.endsWith(e));
  if (!okExt) return { ok: false, error: "type", message: "Only PDF and DOCX files are supported." };
  if (file.size === 0) return { ok: false, error: "empty", message: "That file is empty." };
  if (file.size > MAX_UPLOAD_BYTES) return { ok: false, error: "size", message: "File exceeds the 25 MB limit." };
  return { ok: true };
}
```

### 3.2 `[NEW] src/lib/jobLabels.ts` — node → friendly label (spec §2.2)

```ts
export const NODE_LABELS: Record<string, string> = {
  ingest_agent: "Reading & extracting the document",
  clause_splitter: "Breaking the document into clauses",
  crag_retrieval: "Retrieving legal evidence",
  self_rag_validation: "Validating findings",
  risk_score: "Scoring risk",
  redline: "Drafting safer language",
  skip_redline: "Drafting safer language",   // both logical Node 6 → same label (011 §2.4)
  report: "Compiling your report",
};
export function nodeLabel(node?: string | null): string {
  return (node && NODE_LABELS[node]) || "Analyzing…";   // defensive fallback (spec AC-11)
}
```

### 3.3 `[NEW] src/lib/useJobEvents.ts` — SSE-driven state hook

Wraps `apiClient.openJobEvents` into a typed, discriminated UI state. Subscribes on mount,
**unsubscribes on unmount** (spec AC-9), and exposes everything the processing view needs.

```ts
"use client";
import { useEffect, useState } from "react";
import { getApiClient } from "@/lib/api/provider";
import type { JobStatus, ProgressEvent } from "@/lib/api/types";

export type JobPhase = "connecting" | "running" | "completed" | "failed" | "error";

export interface JobEventsState {
  phase: JobPhase;
  node?: string | null;      // last progress node
  index?: number | null;
  total?: number | null;
  completedNodes: string[];  // ordered, for the step trace
  final?: JobStatus | null;  // set on completed/failed
  errorMessage?: string;     // EC-3/EC-5/EC-6 surface text
}

export function useJobEvents(jobId: string): { state: JobEventsState; reconnectKey: number; reconnect: () => void } {
  const [state, setState] = useState<JobEventsState>({ phase: "connecting", completedNodes: [] });
  const [reconnectKey, setReconnectKey] = useState(0);

  useEffect(() => {
    const client = getApiClient();
    let closed = false;
    const stop = client.openJobEvents(jobId, {
      onProgress: (e: ProgressEvent) => {
        if (closed) return;
        setState((s) => ({
          ...s, phase: "running", node: e.node, index: e.index, total: e.total,
          completedNodes: e.node ? [...s.completedNodes, e.node] : s.completedNodes,
        }));
      },
      onTerminal: (e: ProgressEvent) => {
        if (closed) return;
        setState((s) => ({
          ...s,
          phase: e.event === "completed" ? "completed" : "failed",
          final: e.final ?? null,
          // `errorMessage` carries ONLY connection-phase text (EC-3/5/6). Do NOT stuff the
          // ingest-error message here (review B1) — the completed-with-issue branch (EC-1) reads
          // `state.final?.error` directly, and a normal completion has final.error == null.
        }));
      },
      onError: () => {
        if (closed) return;
        // 404 (unknown/evicted, EC-6) or a dropped connection (EC-5) both land here; the view
        // shows a recoverable "connection lost / job not found" state with a manual refresh.
        setState((s) => (s.phase === "completed" || s.phase === "failed" ? s
          : { ...s, phase: "error", errorMessage: "Lost connection to the analysis stream." }));
      },
    });
    return () => { closed = true; stop(); };
  }, [jobId, reconnectKey]);   // reconnectKey bump re-runs the effect → re-subscribe (OQ3, replays buffer)

  return { state, reconnectKey, reconnect: () => setReconnectKey((k) => k + 1) };
}
```

> **Note on `total` (spec AC-10, review N3).** `ProgressBar` value = `round((index/total)*100)`
> guarded by `index != null && total && total > 0` (never divide by zero). If `total`/`index` are
> null (before the first event) the view shows the "connecting/queued" state (EC-8) rather than a
> 0-width bar. The step trace uses `completedNodes` for the authoritative list of what ran
> (011 §2.4).

### 3.4 `[NEW] src/components/upload/DropZone.tsx`

Dashed zone (matches screen 9): PDF + DOCX file-type icon chips (no TXT — D1), "Drag & Drop
files here, or browse", a hidden `<input type="file" accept=".pdf,.docx">`, and the primary
"Browse Files" button. Handles `onDragOver`/`onDragLeave`/`onDrop` (drag-active styling) and
`onChange`; both paths call a single `onFile(file: File)` prop. Purely presentational + file
capture — validation and submit live in `UploadForm` so the drop and browse paths are
identical (spec AC-3).

### 3.5 `[NEW] src/components/upload/UploadForm.tsx`

Owns the flow (client component):
- Renders the 013 `Stepper` (`["Upload","AI Analysis","Review"]`, `current={0}`), the "Upload
  New Contract" heading, `DropZone`, and an inline error slot.
- `onFile(file)`: run `validateFile` (D1); on failure set the inline error and **stop** (no
  submit — AC-4/5/6). On success set `submitting`, call `getApiClient().submitAnalysis(file)`,
  and `router.push('/jobs/' + res.job_id)` (AC-2). While `submitting`, disable the zone/button
  and ignore further files (AC-7, EC-9).
- Catch `submitAnalysis` rejections: map `ApiError.status` 400→"unsupported or empty file",
  413→"file too large", otherwise "couldn't reach the server" (EC-3/EC-4, AC-19); stay on
  `/upload`, clear `submitting`, keep the file re-selectable. No navigation on error.
- No external-account row, no recipient field (D2/D3, AC-8).

Uses `useRouter` from `next/navigation`.

### 3.6 `[NEW] src/components/processing/ProcessingView.tsx` + `ProcessingArt.tsx`

`ProcessingView` (client) calls `useJobEvents(jobId)` and renders by `phase`:
- `connecting` → `ProcessingArt` + "Starting analysis…" + indeterminate bar (EC-8).
- `running` → `ProcessingArt` + `nodeLabel(node)` + "Step {index} of {total}" + determinate
  `ProgressBar` (AC-10) + a step trace from `completedNodes` (each mapped via `nodeLabel`).
- `completed` → "Analysis complete" panel: a "View report" link →
  `getApiClient().getReportUrl(jobId,'md')` (OQ2, opens in a new tab) + a "View JSON" → `…'json'`
  (the backend serves `application/json` **inline**, no `Content-Disposition` — so it opens, not
  downloads; label "View", not "Download" — review B3). The EC-1 completed-with-issue variant is
  chosen by **`state.final?.error`** (review B1), carrying `final.error.message`; the report link
  shows only when `final.report_available` (AC-12/AC-13).
- `failed` → error state + "Retry" → `router.push('/upload')` (AC-14).
- `error` → recoverable "connection lost / job not found" state + a "Refresh" button calling
  the hook's `reconnect()` (OQ3/EC-5/EC-6).

`ProcessingArt` is the decorative glowing shield/document (screen 6): a CSS/SVG composition
using the accent-gradient + glow tokens; no data, no API. Kept in its own file so it doesn't
clutter the view logic.

### 3.7 Route pages + shell wiring

- `[NEW] src/app/upload/page.tsx` — server component: `<TopBar title="Contract Upload"
  userName="Sarah Jenkins" />` then a centered `<UploadForm/>` in a padded container (matches
  screen 9's centered card).
- `[NEW] src/app/jobs/[jobId]/page.tsx` — reads `params.jobId`; renders a **full-bleed** dark
  container (screen 6 has no card chrome) with `<ProcessingView jobId={params.jobId} />`. It is
  inside the app shell (sidebar persists) but omits a TopBar title to match the immersive
  processing look.
- `[MODIFY] src/components/shell/Sidebar.tsx` — change the `Contracts` `NAV_ITEMS` href from
  `/contracts` to `/upload` (D5) so the sidebar entry opens the upload flow; active-highlight
  then lights on `/upload`.
- `[MODIFY] src/app/contracts/page.tsx` — replace the placeholder with `redirect('/upload')`
  (`next/navigation`) so the old route isn't a dead end. `redirect()` throws a control-flow
  signal by design — call it at the top level, never inside a try/catch (review N1).

---

## 4. Tests (Vitest + RTL, mock provider) mapped to acceptance criteria

Mock the router: `vi.mock("next/navigation", () => ({ useRouter: () => ({ push }), redirect: vi.fn() }))`.

**Test client injection (review B2 — critical).** The 013 mock provider emits only ONE happy
sequence (`progress×4 → completed` with `final.error == null`, and a **4-node** fixture:
`ingest_agent, clause_splitter, risk_score, report`). It has **no** `failed`, no ingest-error,
and no configurable variant. So:
- **Upload tests** may use the real 013 mock (happy submit → fixed `job_id`).
- **Processing tests** that need `failed` / ingest-error / already-finished / connecting variants
  MUST inject a scripted fake client by mocking the provider seam:
  `vi.mock("@/lib/api/provider", () => ({ getApiClient: () => fakeClient }))`, where a helper
  `makeFakeClient(events: ProgressEvent[], opts?)` implements `openJobEvents` by replaying the
  given events via `setTimeout` (and, for AC-15, replaying a terminal immediately; for EC-8,
  emitting nothing so the view stays `connecting`; for the `error` phase, invoking `onError`).
  This keeps components calling `getApiClient()` unchanged (spec AC-16) while giving tests full
  control. `makeFakeClient` lives in a shared test util (`src/__tests__/_fakeClient.ts`).
- **N5:** the `renders_progress` happy test asserts against the fixture's real numbers
  (`total = 4`), not the 7-node map.

#### `upload-validation.test.ts` (D1)
| Test | Verifies |
|---|---|
| `accepts_pdf_and_docx` | `validateFile` ok for `.pdf`/`.docx` |
| `rejects_other_extension` | `.txt`/`.png` → `{error:"type"}` (AC-4) |
| `rejects_empty` | 0-byte → `{error:"empty"}` (AC-6) |
| `rejects_oversize` | > 25 MB → `{error:"size"}` (AC-5) |

#### `job-labels.test.ts` (§2.2)
| Test | Verifies |
|---|---|
| `maps_all_seven` | each node name → its label; `redline`/`skip_redline` share the label |
| `unknown_falls_back` | `nodeLabel("nope")==="Analyzing…"` (AC-11) |

#### `upload.test.tsx` (AC-1..AC-8)
| Test | Verifies |
|---|---|
| `renders_stepper_and_zone` | Stepper step 1 current, heading, PDF+DOCX chips (no TXT), Browse button (AC-1) |
| `valid_file_submits_and_navigates` | choosing `.pdf` → `submitAnalysis` once → `push('/jobs/<id>')` (AC-2) |
| `drop_behaves_like_browse` | dropping a valid file → same submit+navigate (AC-3) |
| `invalid_type_blocks_submit` | `.txt` → inline error, `submitAnalysis` not called (AC-4) |
| `oversize_blocks_submit` | >25 MB → error, no submit (AC-5) |
| `empty_blocks_submit` | 0-byte → error, no submit (AC-6) |
| `busy_state_prevents_double_submit` | during in-flight submit the control is disabled; a 2nd file is ignored (AC-7) |
| `no_external_or_recipient_ui` | no Drive/Dropbox row, no recipient field (AC-8) |
| `submit_network_error_inline` | `submitAnalysis` rejects (no status) → "couldn't reach the server" inline error, no navigation (EC-3/AC-19) |
| `submit_400_and_413_mapped` | `submitAnalysis` rejects with `ApiError(status=400)` → "unsupported or empty file"; `status=413` → "file too large" (EC-4; review) — inject via a fake client whose `submitAnalysis` throws the typed `ApiError` |

#### `useJobEvents.test.tsx`
| Test | Verifies |
|---|---|
| `subscribes_and_unsubscribes` | opens stream on mount; unsubscribe called on unmount (AC-9) |
| `progress_updates_state` | progress events set node/index/total + append completedNodes |
| `terminal_completed_sets_final` | completed → phase `completed`, `final` populated |
| `error_sets_recoverable_state` | `onError` → phase `error` unless already terminal (EC-5/6) |

#### `processing.test.tsx` (AC-9..AC-15, EC-1/2/6)
| Test | Verifies |
|---|---|
| `renders_connecting_before_first_event` | with a fake client that emits nothing yet, the view shows the "starting/queued" state (not blank, no 0-width bar) (EC-8) |
| `renders_progress` | a progress event shows friendly label + "Step {index} of {total}" + bar at `round(index/total*100)`; assert against the fixture's real `total=4` (AC-10, review N5) |
| `unknown_node_generic_label` | node "nope" → "Analyzing…" (AC-11) |
| `completed_shows_report_link` | terminal completed → "Analysis complete" + report link → `getReportUrl(id,'md')` (AC-12) |
| `ingest_error_soft_state` | completed with `final.error` → completed-with-issue + message (AC-13/EC-1) |
| `failed_shows_retry` | failed → error state + Retry → `push('/upload')` (AC-14/EC-2) |
| `already_finished_lands_terminal` | immediate terminal → terminal state, no hang (AC-15) |
| `error_phase_refresh_reconnects` | error phase → Refresh calls reconnect (re-subscribes) (EC-5/6) |

#### Boundary (AC-16..AC-18)
| Test | Verifies |
|---|---|
| `screens_use_getApiClient_only` | grep: no `realProvider`/`mockProvider` import in `components/upload`,`components/processing` (AC-16) |
| `types_unchanged` | `tsc --noEmit` passes; screens import only from `@/lib/api/types` (AC-17) |
| `no_backend_edits` | `git diff --name-only` touches nothing under `backend/` (AC-18) |

Plus the existing 013 suite must stay green (the two `[MODIFY]`s don't break shell/boundary
tests — Sidebar still renders five items; `/contracts` redirect is covered by its own trivial
render check).

---

## 5. Implementation order (TDD — constitution §7)

1. **Pure utils first:** `upload.ts` + `upload-validation.test.ts`; `jobLabels.ts` +
   `job-labels.test.ts` (red → green). No React.
2. **Hook:** `useJobEvents.ts` + `useJobEvents.test.tsx` (drive with the mock provider).
3. **Upload screen:** `DropZone` → `UploadForm` → `app/upload/page.tsx`; `upload.test.tsx`
   (red → green). Wire the router mock.
4. **Processing screen:** `ProcessingArt` → `ProcessingView` → `app/jobs/[jobId]/page.tsx`;
   `processing.test.tsx`.
5. **Shell wiring:** Sidebar `Contracts` href → `/upload`; `contracts/page.tsx` → redirect.
   Re-run the 013 shell/boundary suite.
6. **Verify:** full `vitest run`, `tsc --noEmit`, `next lint`, `next build` (with the dev
   server STOPPED — never build while `next dev` runs), confirm no `backend/` diff.
7. **Live smoke (AC-20):** stop tests, start `uvicorn app.api.main:app` on `:8000` + Ollama,
   set `NEXT_PUBLIC_API_PROVIDER=real` in `.env.local`, `next dev`, upload a real `.pdf`, watch
   the SSE progress to completion, open the report link.

Each step's tests are written and confirmed failing before its implementation (constitution
§7); a post-impl failure fixes the code, not the test.

---

## 6. Notes / risks

- **SSE through the Next dev proxy (real path).** 013's `next.config.mjs` rewrites `/api/*` →
  `:8000`; `EventSource` uses the same-origin `/api/jobs/{id}/events`, so the browser sees no
  cross-origin request (013 Q4). If a future prod build needs it, that's a deploy-time reverse
  proxy concern, not this feature's.
- **Local-Ollama latency (constitution §9).** Real runs take minutes; the processing view is
  built around the live SSE stream (not a fixed timer), and EC-8 covers the pre-first-event
  window. The live smoke will be slow — expected, not a bug.
- **React StrictMode double-subscribe (review N2).** `next.config.mjs` sets
  `reactStrictMode: true`, so in dev the `useJobEvents` effect mounts→unmounts→remounts and
  `openJobEvents` fires twice — expected. The `closed` guard + `stop()` cleanup makes this safe
  (each effect run owns its own EventSource + unsubscribe); seeing two EventSource opens in the
  dev smoke is StrictMode, not a leak.
- **AC-20 smoke — use the proxy, not a direct base URL (review N4).** Keep
  `NEXT_PUBLIC_API_BASE_URL` **empty** so calls go same-origin `/api/*` through the Next dev
  proxy. Setting it to `http://127.0.0.1:8000` directly would make the browser call `:8000`
  cross-origin, which 011's CORS allowlist (`:5173`, not `:3000`) rejects. The proxy is the
  supported path.
- **`next build` vs `next dev`.** Learned in 013: never run a production build while the dev
  server is live (it corrupts `.next`). Step 6 builds with dev stopped.
- **`params` in `app/jobs/[jobId]/page.tsx`.** Next 14 App Router passes `params` synchronously
  to the page; `jobId` is read directly and passed to the client `ProcessingView`.

---

*Per constitution §1/§11, a `feature/015-upload-processing` branch opens only after this
plan.md and its spec.md are approved and `tasks.md` exists. No `tasks.md` or implementation was
written in this pass — plan only.*
