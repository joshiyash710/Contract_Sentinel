# Feature 015 — Upload + Live Processing (first backend-connected UI)

## 1. Problem statement

Feature 013 delivered the frontend foundation (design tokens, app shell, UI
primitives, and the mock/real API-client seam) but **ships no feature screen and
renders no live data**. Feature 011 exposes the real HTTP+SSE contract (upload →
run the 7-node pipeline → stream progress → serve the report) and 012 made job
state durable, but **nothing in the UI drives it**. This feature is the first
that closes that loop: it lets a user actually submit a contract and watch the
pipeline run against the real backend.

It realizes **two reference screens** (from
`specs/013-frontend-design-system/design-refs/`):

- **Upload** (screen 9, `…31 PM (8).jpeg`) — pick/drop a contract file and start
  a run.
- **Processing** (screen 6, `…31 PM (5).jpeg`) — a live view of the running
  pipeline, driven by the SSE progress stream.

### Position relative to the fixed architecture (constitution §2)

This feature sits **entirely outside** the LangGraph StateGraph. It adds no
node, no edge, and **modifies no file under `backend/`**. It is a pure HTTP/SSE
*client* of the boundary feature 011 already defined, consuming 011's **Pydantic**
boundary models via the TypeScript mirror types already in
`frontend/src/lib/api/types.ts` (constitution §4 — the internal `ContractState`
`TypedDict` never crosses the wire). Per constitution §11 it is developed on
`feature/015-upload-processing`.

### Phasing note (numbering)

013 §5 mapped the frontend rollout as 014 (auth/marketing) → 015 (upload +
processing) → 016 → 017 → 018. The user chose to build **upload + processing
first**; **014 (auth) is intentionally deferred**, not renumbered. This spec keeps
the documented map and is numbered **015**. There is no auth in this feature
(auth is PERMANENTLY CUT; 011 D1 fixed the backend as no-auth, localhost-only).

## 2. Inputs and outputs

### 2.1 Relationship to `ContractState` (001) and the 011 contract

This feature **introduces no backend field** and does not conflict with any name
in `001-contract-state-schema.md`. It consumes exactly the 011 §2 boundary models
(already mirrored in 013 `types.ts`) and never the internal `ContractState`
directly. Mapping of what the two screens read/produce onto the shared shapes:

| UI action | 011 endpoint | Shapes (011 §2 / 001) |
| --- | --- | --- |
| Submit a file | `POST /api/analyze` (multipart: `file`, optional `recipient`) | → `202 AnalyzeAccepted { job_id, status, submitted_at }` |
| Watch progress | `GET /api/jobs/{job_id}/events` (SSE) | stream of `ProgressEvent { event, job_id, node?, index?, total?, elapsed_seconds?, final? }` |
| Fallback poll | `GET /api/jobs/{job_id}` | `JobStatus` (all 9 fields; `status: JobState`) |
| Open the report | `GET /api/jobs/{job_id}/report?format=md\|json` | report file, or `409` if not ready |

The **upload** produces, server-side, the graph's sole required input
`document_path` (001 line 83) — the runner saves the uploaded bytes and seeds it
(011 §2.1); the frontend never sets it. The **processing** view reads progress
derived from `current_node` / `node_timings` (001 lines 124/127) as surfaced by
011's `ProgressEvent`/`JobStatus`, and the terminal state's `report_available`
(from `report_path`, 001 line 113), `error` (from `ingest_error`, 001 line 89),
and `mcp_delivery_status` (001 line 121).

### 2.2 Node → friendly-label map (display only)

The SSE `ProgressEvent.node` carries the graph's internal node name. The
processing screen maps each to a human label (display-only; the canonical names
are 011's, unchanged):

| `node` (011 / builder) | Friendly label | `index` (011 §2.4) |
| --- | --- | --- |
| `ingest_agent` | "Reading & extracting the document" | 1 |
| `clause_splitter` | "Breaking the document into clauses" | 2 |
| `crag_retrieval` | "Retrieving legal evidence" | 3 |
| `self_rag_validation` | "Validating findings" | 4 |
| `risk_score` | "Scoring risk" | 5 |
| `redline` / `skip_redline` | "Drafting safer language" | 6 |
| `report` | "Compiling your report" | 7 |

An **unknown** node name (defensive — a future graph rename) falls back to a
generic "Analyzing…" label rather than crashing. The map lives in one module so a
rename is a one-line change.

### 2.3 Resolved decisions (inline, per project preference — not open questions)

- **D1 — Accept only `.pdf` and `.docx`.** The client validates the chosen file's
  extension against `{.pdf, .docx}` (mirrors IngestAgent `ALLOWED_EXTENSIONS` /
  011 AC-15) and its size against **25 MB** (011 `MAX_UPLOAD_SIZE_BYTES` / AC-16)
  **before** upload, showing a clear inline error on violation. The mockup's TXT
  icon is dropped (the backend rejects `.txt` with `400`); only PDF + DOCX icons
  are shown. Client validation is a UX nicety; the server remains authoritative
  (a slipped-through bad file still yields the 011 `400`/`413`, handled per §4).
- **D2 — No "connect external accounts" row.** Google Drive / Dropbox upload
  sources are omitted: there is no backend upload-source endpoint, and Dropbox is
  PERMANENTLY CUT (constitution §2). Direct file upload only. (Drive/Gmail exist
  only as report *delivery*, feature 010 — not upload.)
- **D3 — No recipient field.** `POST /api/analyze` is called without `recipient`;
  the backend uses its configured default delivery recipient (011 §6.1). A
  per-upload recipient override is deferred to a later spec.
- **D4 — Node-based progress, not a clause count.** 011 §2.4 emits only
  `node`/`index`/`total`; it does **not** emit the mockup's "35/150 clauses
  analyzed". That count is **not fabricated**. The screen shows the friendly node
  label + "Step {index} of {total}" + a determinate `ProgressBar` at
  `index/total`. (Per constitution §9, runs are minutes-long on local Ollama, so
  a live SSE view — not a spinner guess — is the right transport.)
- **D5 — Routes.** `/upload` (upload screen) and `/jobs/[jobId]` (live processing
  screen). A successful submit does `router.push('/jobs/' + job_id)`. The sidebar
  **Contracts** item links to `/upload` as the entry point.
- **D6 — Provider seam.** Both screens reach the backend only through
  `getApiClient()` (013 seam), which honors `NEXT_PUBLIC_API_PROVIDER`. Default
  stays **mock** so unit tests need no backend; the live end-to-end smoke runs
  with `provider=real` against `uvicorn` on `:8000` via the Next dev proxy
  (013 Q4). No component imports `realProvider`/`mockProvider` directly.

### 2.4 Outputs (what this feature renders)

- **Upload screen** (`/upload`): the stepper (step 1 active), heading, drag-&-drop
  zone + Browse button, inline validation errors, and a submitting state.
- **Processing screen** (`/jobs/[jobId]`): the glowing artwork, the current
  friendly label + "Step {index}/{total}" + `ProgressBar`, a list/trace of
  completed steps, and terminal states: **completed** (→ "Analysis complete" with
  a "View / Download report" action hitting the report endpoint), **failed** (→
  error state with a Retry that returns to `/upload`), and **completed-with-
  ingest-error** (EC-1 — treated as a soft failure with the ingest message).

## 3. Acceptance criteria

Each is written to become a test (Vitest + React Testing Library, driving the
**mock** provider unless noted; the real path is covered by the live smoke, AC-20).

**Upload — validation & submit**
- AC-1: The upload screen renders the 3-step Stepper with step 1 ("Upload")
  current, the "Upload New Contract" heading, the drag-&-drop zone showing PDF and
  DOCX file-type icons (no TXT), and a primary "Browse Files" button.
- AC-2: Choosing a `.pdf` (or `.docx`) via the file input calls
  `apiClient.submitAnalysis(file)` exactly once and, on the returned `job_id`,
  navigates to `/jobs/{job_id}` (assert the router push).
- AC-3: Dropping a valid file onto the drop zone behaves identically to choosing
  it (same submit + navigate path).
- AC-4: Choosing a `.txt` (or any non-pdf/docx) file shows an inline error naming
  the accepted types and does **not** call `submitAnalysis` (D1).
- AC-5: Choosing a file larger than 25 MB shows an inline "file too large" error
  and does **not** call `submitAnalysis` (D1).
- AC-6: Choosing a 0-byte file shows an inline "empty file" error and does not
  submit (mirrors 011 EC-5).
- AC-7: While `submitAnalysis` is in flight the submit control shows a busy/
  disabled state and cannot be double-submitted (one job per submit).
- AC-8: There is **no** "connect external accounts"/Drive/Dropbox UI on the
  screen (D2), and no recipient field (D3).

**Processing — live progress**
- AC-9: The processing screen for a `jobId` calls `apiClient.openJobEvents(jobId,
  …)` on mount and calls its returned unsubscribe function on unmount (no leaked
  stream).
- AC-10: For each `progress` event, the screen shows the friendly label for
  `event.node` (per §2.2), the text "Step {index} of {total}", and a `ProgressBar`
  whose value equals `round(index/total*100)`.
- AC-11: An unknown `node` value renders the generic "Analyzing…" label, not a
  crash/blank (defensive map).
- AC-12: On the terminal `completed` event, the screen shows an "Analysis
  complete" state with a "View / Download report" action whose href/handler
  targets `apiClient.getReportUrl(jobId, 'md')` (and a JSON option) — no crash if
  `final` is present.
- AC-13: On a `completed` event whose `final.error` is set (ingest-error
  completion, 011 EC-1), the screen shows the completed-with-issue state carrying
  the error message, distinct from a hard failure.
- AC-14: On the terminal `failed` event, the screen shows an error state with a
  "Retry" action that navigates back to `/upload`.
- AC-15: Opening the processing screen for an **already-finished** job (the seam
  emits the terminal event immediately) lands directly on the terminal state
  without hanging (mirrors 011 AC-11 / 013 EC-2).

**Seam / boundary**
- AC-16: Both screens reach the backend **only** via `getApiClient()` — a test
  swapping the provider (mock↔real) needs no change to either component (013 seam;
  no direct `realProvider`/`mockProvider` import).
- AC-17: The screens use the 011 mirror types from `types.ts` unchanged (no new/
  divergent field names; a type check catches drift).
- AC-18: No file under `backend/` is modified by this feature (structural check).
- AC-19: Submit failures surface a typed error in the UI, not an unhandled throw
  (see §4 EC-2/EC-3).

**Live end-to-end (real backend)**
- AC-20 (smoke, manual/gated): With `NEXT_PUBLIC_API_PROVIDER=real` and `uvicorn`
  on `:8000`, uploading a real `.pdf` navigates to `/jobs/{id}`, streams ≥1
  `progress` event per node entered in order, and ends on the completed state with
  a working report link — exercising the real POST + SSE through the Next dev
  proxy. (Not a CI unit test; the automated suite uses the mock provider.)

## 4. Edge cases

- **EC-1 — Ingest-error completion (soft failure):** 011 EC-1 — the run reaches
  `END` with `final.error` set (unsupported/corrupt file that passed the client
  check, parse timeout). The processing screen shows a *completed-with-issue*
  state with the message, and offers the report link only if
  `final.report_available` is true (AC-13). Distinct from EC-2.
- **EC-2 — Pipeline crash (`failed`):** the terminal event is `failed`; show the
  error state + Retry (AC-14). One failed run never wedges the UI.
- **EC-3 — Backend unreachable / network error on submit:** `submitAnalysis`
  rejects (013 `ApiError`); the upload screen shows an inline "couldn't reach the
  server" error and stays on `/upload` with the file re-selectable — no navigation,
  no unhandled throw (AC-19).
- **EC-4 — Submit rejected by server despite client checks (`400`/`413`):** a
  file that slipped the client validation still gets the 011 boundary rejection;
  the `ApiError` (with status) is surfaced as an inline error mapping 400→"unsupported
  or empty file", 413→"file too large". Server is authoritative (D1).
- **EC-5 — SSE connection drops mid-run:** the stream errors before a terminal
  event; the screen shows a "reconnecting…/lost connection" affordance and offers
  a manual refresh that re-opens the stream (or polls `GET /api/jobs/{id}` once)
  — the underlying run continues server-side (011 EC-6), so re-subscribing
  recovers current state. No fabricated completion.
- **EC-6 — Unknown / evicted / 404 job id in the URL:** navigating to
  `/jobs/{unknown}` (e.g. after a server restart evicted an in-memory job, 011
  EC-9) surfaces a "job not found" state with a link back to `/upload`, not a hang.
- **EC-7 — Direct navigation / refresh of `/jobs/[jobId]`:** the screen is
  self-sufficient from the URL `jobId` (it re-opens the SSE stream, replaying
  buffered events per 011 §2.4), so a page refresh mid-run resumes the live view
  rather than losing it.
- **EC-8 — Slow first event (local-Ollama latency, constitution §9):** before any
  `progress` event arrives the screen shows a "queued / starting" state (not a
  blank), consistent with `JobState` `queued`→`running`.
- **EC-9 — Double file selection / re-drop while submitting:** ignored while a
  submit is in flight (AC-7); no second job is created.

## 5. Out of scope

- **The report content & history views** — viewing the rendered report inline,
  the downloads/share cards, and the contract-history table are **spec 017**. This
  feature only *links* to the report endpoint on completion; it does not render
  report contents.
- **The analysis workspace / clause chat / comparison** — **spec 016**.
- **Dashboards / analytics / settings / auth / marketing** — specs 018 / 014. No
  auth is added (PERMANENTLY CUT).
- **Any backend change** — no new endpoint, no field, no `backend/` edit
  (AC-18). Upload-from-Drive/Dropbox is not built (D2); recipient override (D3)
  and clause-count streaming (D4) would each require backend work owned elsewhere,
  explicitly not attempted here.
- **Resumable uploads / chunked upload / multiple-file batch** — single file,
  single request (mirrors 011's single-file `POST /api/analyze`; multi-submit is
  011 EC-10 territory, one job per file, not batched here).
- **Cancelling a running job** — 011 exposes no cancel endpoint; not offered.

## 6. Open questions

Per the project's inline-decision preference, the significant choices are resolved
in §2.3 (D1–D6). The remaining genuinely-uncertain items, none blocking the plan:

1. **Completion redirect vs. inline.** On `completed`, should the screen (a) stay
   on `/jobs/[jobId]` showing an "Analysis complete" panel with the report link
   (my recommendation — keeps the smoke simple and works before spec 017 exists),
   or (b) auto-redirect to a `/jobs/[jobId]/report` route that 017 will own? I
   recommend **(a)** now; 017 can add the richer report route later. Confirm.
2. **Report link target before 017 exists.** The "View report" action can either
   (a) open `GET /api/jobs/{id}/report?format=md` directly (raw markdown in a new
   tab — trivial, works today) or (b) be a disabled "coming in 017" affordance. I
   recommend **(a)** so the end-to-end smoke is genuinely complete. Confirm.
3. **SSE-drop recovery depth (EC-5).** Minimal (show "connection lost" + a manual
   refresh that re-opens the stream) vs. automatic retry with backoff. I recommend
   **minimal** for this feature (the 011 buffer replays on re-subscribe, so a
   manual refresh fully recovers); auto-retry can be added if the live smoke shows
   it's needed. Confirm.
