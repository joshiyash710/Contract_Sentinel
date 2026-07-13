# Feature 017 — Report View + Auto-redirect (the destination screen)

## 1. Problem statement

Feature 015 closed the *upload → watch* loop: a user submits a contract and
watches the 7-node pipeline run live on `/jobs/[jobId]` (polling `GET
/api/jobs/{id}`). But on completion it currently shows only an **inline "Analysis
complete" panel with a raw report link** — 015 explicitly deferred the real
destination (015 §5: "the report content … are **spec 017**"; 015 Open-Q1 named a
future `/jobs/[jobId]/report` route and recommended deferring the auto-redirect to
it). The product intent the user stated is concrete: **stay on the site → watch
the live steps → get auto-redirected to a real report page when it finishes** (no
email hand-off, no leaving the page).

This feature builds that destination. It:

1. Adds a **report page** that renders the backend's *actual* report — the file +
   an overall risk roll-up, then each analyzed clause as a card (risk badge →
   plain-English explanation → suggested safer wording → supporting evidence),
   plus real **Download** actions (Markdown + JSON).
2. Changes 015's processing screen so that on the terminal `completed` state it
   **auto-redirects** to that page instead of showing the inline panel.

It realizes **two reference screens** (from
`specs/013-frontend-design-system/design-refs/`):

- **AI Analysis Panel** (screen 7, `…31 PM (6).jpeg`) — the per-clause findings
  list with expandable risk cards (Text / AI Explanation / Business Impact /
  Rewrite). *We take the findings-card layout; the live Document View pane and the
  Legal AI Assistant chat rail are **spec 016**, not here.*
- **Generate & Download Reports** (screen 11, `…32 PM (1).jpeg`) — the header
  ("filename / risk score") and the downloadable-artifact cards. *We take the
  header + download affordance, grounded to what the backend actually emits (§2.3
  D5).*

### Position relative to the fixed architecture (constitution §2)

Like 015, this feature sits **entirely outside** the LangGraph StateGraph: no
node, no edge, and **no file under `backend/app/graph/` or the pipeline is
modified**. It is a pure HTTP *client* of the boundary feature 011/009 already
defined. It consumes the **009 `ContractReport` Pydantic boundary model** (Node 7
output, `app/models/report.py`) — never the internal `ContractState` `TypedDict`
(constitution §4). Per constitution §11 it is developed on
`feature/017-report-view`.

The one non-`backend/` seam addition is a TypeScript mirror of `ContractReport`
in `frontend/src/lib/api/types.ts` and a `getReport()` method on the frontend
`ApiClient` (see §2.2). **No new backend endpoint is added** — the report JSON is
already served by `GET /api/jobs/{id}/report?format=json` (011 routes.py).

### Phasing note (numbering)

013 §5 mapped the rollout 014 (auth, deferred) → 015 (upload+processing) → 016
(workspace/chat/comparison) → 017 (reports+history) → 018 (dashboards/settings).
This spec is **017**, but scoped to the **report *view* + auto-redirect only**.
The **contract-history table** that 015 §5 also filed under 017 is split out to a
later slice (see §5) so this feature stays shippable and focused on the user's
stated goal. No auth is added (PERMANENTLY CUT).

## 2. Inputs and outputs

### 2.1 Relationship to the 009 report model and the 011 contract

This feature **introduces no backend field**. It reads exactly the 009
`ContractReport` shape, serialized by `ContractReport.model_dump_json()` and
served verbatim by 011's report endpoint. The relevant fields (from
`app/models/report.py`, authoritative):

| Model | Fields this feature reads |
| --- | --- |
| `ContractReport` | `original_filename`, `uploaded_at`, `generated_at`, `ocr_used`, `ocr_confidence`, `ingest_error`, `summary`, `findings[]`, `error_count` |
| `ReportSummary` | `total_clauses`, `validated_findings`, `clean_clauses`, `high`, `medium`, `low` |
| `ReportFinding` | `clause_id`, `position`, `section_number`, `clause_type`, `risk_level`, `risk_rationale`, `clause_text`, `rewrite_state`, `suggested_rewrite`, `path_taken`, `confidence_score`, `evidence[]` |
| `ReportEvidence` | `source_reference`, `snippet_text` |

**Intentionally not rendered** (present in the model, deliberately unused by this
view — the TS mirror still includes them so the types stay faithful to 009):
`ContractReport.document_id`, `processing_started_at`, `node_timings`,
`error_count`; `ReportFinding.clause_id`, `path_taken`. `error_count` is a
pipeline-internal write-failure counter, not a user-facing warning; if we later
decide to surface "N pipeline warnings" it becomes its own small decision. Listing
these here so their omission is a choice, not an oversight.

| UI action | Endpoint (011 / unchanged) | Shape |
| --- | --- | --- |
| Load report data | `GET /api/jobs/{job_id}/report?format=json` | `ContractReport` JSON (or `409` if not ready, `404` if unknown) |
| Download Markdown | `GET /api/jobs/{job_id}/report?format=md` | report `.md` file |
| Download JSON | `GET /api/jobs/{job_id}/report?format=json` | report `.json` file |
| Guard direct nav | `GET /api/jobs/{job_id}` | `JobStatus` (to detect not-yet-complete / not-found before fetching the report) |

### 2.2 Seam additions (the only new frontend surface)

- **`ContractReport` mirror types** added to `frontend/src/lib/api/types.ts`
  (mirroring 009's `ContractReport` / `ReportSummary` / `ReportFinding` /
  `ReportEvidence`), in the same TS-mirror style 015 used for `JobStatus` etc.
  (constitution §4 — the internal `ContractState` never crosses the wire).
- **`getReport(jobId): Promise<ContractReport>`** added to the `ApiClient`
  interface (`client.ts`) and both providers:
  - `realProvider`: `fetch(getReportUrl(jobId, "json"))` → parse JSON →
    `ContractReport`; HTTP/network failures wrapped in the existing `ApiError`
    (409/404 preserved on `.status`), never thrown raw (mirrors 015 EC-3).
  - `mockProvider`: returns a static `ContractReport` fixture (added to
    `fixtures.ts`) so the report page and its unit tests need **no backend**
    (mirrors 015 D6).
  - `getReportUrl` (already present) is reused unchanged for the download links.
- No component imports a provider directly; both the report page and the modified
  processing screen reach the backend **only** through `getApiClient()` (013 seam;
  015 AC-16).

### 2.2a Seam invariants (verified against the real runner — the plumbing D1/D6/D7 rely on)

The redirect/guard logic below depends on three invariants that are **guaranteed by
the existing backend code**, not assumed. They are stated here so the plan can
lean on them:

- **INV-1 (`report_available ⟹ non-409`).** `JobStatus.report_available` is
  `true` **only** when `status == completed`, `report_path` is set, **and** the
  `.md` file exists on disk (`registry.py` `to_status()`:
  `bool(report_path and Path(report_path).exists())`). The report endpoint returns
  **409** exactly when `status != completed OR not report_path` (`routes.py`).
  Therefore `report_available === true` ⟹ the report endpoint is **not** 409.
  **D1 gates the auto-redirect on `report_available === true`** (the field 015
  already polls), so the redirect target can never bounce back with a 409.
- **INV-2 (both formats co-exist on success).** `report_agent.py` writes the
  **JSON first, then the Markdown**, and sets `report_path` (the `.md` path) **only
  after both writes succeed** (a failed MD write unlinks the orphan JSON and leaves
  `report_path = None` → the job stays 409, never 404). So on the normal success
  path **both `.json` and `.md` exist together**. A **404 on a *completed* job** is
  therefore only reachable by out-of-band artifact loss (a file deleted off disk
  after completion), and is handled as "**report artifact unavailable**", *not* as
  "unknown job" (D7 / EC-2). A 404 on a job that is *not* completed / not found is
  the genuine unknown-job case.
- **INV-3 (ingest-error is coupled across both layers).** On a **completed** run,
  if the report has a report-level `ContractReport.ingest_error`, the worker
  **always** also sets the job-level `JobStatus.error = ErrorInfo(kind:
  "ingest_error", …)` (`worker.py`: `if result.ingest_error: error =
  ErrorInfo(kind="ingest_error", …)`). So the two signals **cannot disagree**:
  `report.ingest_error` set ⟺ `JobStatus.error.kind === "ingest_error"`. **D1/AC-13
  gate the no-auto-redirect on the job-level `JobStatus.error`** (the signal the
  processing screen already has from polling — `ProcessingView` reads
  `state.final?.error`); **D6/AC-10 gate the report page's minimal-panel rendering
  on the report-level `ContractReport.ingest_error`.** These are two views of the
  *same* condition; INV-3 guarantees they stay consistent.

### 2.3 Resolved decisions (inline, per project preference — not open questions)

- **D1 — Route + auto-redirect.** The report lives at **`/jobs/[jobId]/report`**
  (the route 015 Open-Q1 named). When 015's processing screen reaches the terminal
  **`completed`** state **with `report_available === true` and no job-level
  `final.error`**, it calls `router.replace('/jobs/' + jobId + '/report')`
  (`replace`, not `push`, so the browser Back button returns to wherever the user
  started — not back into the finished processing view, which would just
  re-redirect). Gating on `report_available === true` (per **INV-1**) guarantees the
  report page won't bounce back with a 409. A **completed-with-ingest-error**
  terminal — detected by `final.error` being set, which per **INV-3** is exactly
  when the report carries `ingest_error` — does **not** auto-redirect; 015's
  completed-with-issue state is preserved (it may still *link* to the report, which
  will render the D6 minimal panel, but the transition is user-initiated, not an
  auto-`replace`). A **`failed`** terminal keeps 015's error+Retry state
  (unchanged). This is the only behavioral change to 015's `ProcessingView`.
- **D2 — Overall risk roll-up is derived from real counts, never fabricated.** The
  mockups show "78/100 Risk Score", but `ContractReport` carries **no** aggregate
  0–100 score (only per-clause `risk_level` and `summary` counts). We do **not**
  invent a number. The header shows a **risk band** derived from `summary`:
  `high > 0` → **"High risk"**; else `medium > 0` → **"Medium risk"**; else
  `validated_findings > 0` → **"Low risk"**; else **"No issues found"** — plus the
  literal counts ("3 high · 5 medium · 2 low across 42 clauses"). The band drives
  the badge color using the existing 013 risk tokens. (Consistent with 015 D4:
  numbers that the backend doesn't emit are not fabricated. Adding a real
  document-level score is a *backend* change — noted as a follow-up in §5, not
  attempted here.)
- **D3 — Finding card fields map to the real `ReportFinding`.** Each of
  `findings[]` (already ordered by `position`) renders one card:
  - **Title:** `clause_type` (title-cased) or fallback **"Clause {position}"**.
    `position` is rendered **verbatim** from the model (not re-indexed) so the card
    numbering matches the backend's own Markdown, which titles findings
    `## Finding {position}` (`markdown_renderer.py`) — the on-screen card and the
    downloaded `.md` stay consistent. `section_number`, when present, is shown as a
    subtle locator prefix (it is the human-facing clause reference; `position` is
    the ordering key).
  - **Risk badge:** `risk_level` → High/Medium/Low badge (013 tokens); `null` →
    a neutral **"Severity unavailable"** badge (009 Edge Case 4, `risk_level`
    optional).
  - **Explanation ("AI Explanation"):** `risk_rationale` (or a muted "No
    explanation provided" when `null`).
  - **Clause text ("Text"):** `clause_text`, in a monospace/quoted block,
    collapsed by default on long clauses (expand/collapse), since clauses can be
    long.
  - **Suggested rewrite:** driven by the 009 three-way `rewrite_state`:
    `"rewritten"` → show `suggested_rewrite` in a highlighted block;
    `"unavailable"` → muted "A safer rewrite couldn't be generated for this
    clause."; `"not_eligible"` → no rewrite block (clause wasn't routed to
    Redline). (009 AC-8 flattened this so the UI never re-derives it.)
  - **Evidence:** `evidence[]` rendered as a small "Supporting sources" list
    (`source_reference` + `snippet_text`); hidden when empty.
  - **Confidence:** `confidence_score` shown subtly when present (e.g. "82%
    confidence"); omitted when `null`.
- **D4 — "Business Impact" is not a backend field → not fabricated.** Screen 7's
  card has a distinct "Business Impact" section, but `ReportFinding` has no such
  field (it has `risk_rationale` + `suggested_rewrite` + `evidence`). We do **not**
  invent per-clause business-impact prose. The card's explanatory content is
  `risk_rationale`; the "Business Impact" heading is dropped rather than filled
  with fabricated text. (If a real field is added to Node 7 later, the card gains a
  section — a backend change, §5.)
- **D5 — Downloads reflect what the backend actually emits: one report, two
  formats.** Screen 11 shows four separate PDFs, a Risk Scorecard **JPG**, a
  **Notion** integration, and an **email** box. None of these are backed: the
  backend produces exactly **one** report as `.md` + `.json` (011 report
  endpoint); Notion is **PERMANENTLY CUT** (constitution §2); per-file PDF/JPG
  generation does not exist; email/Drive is *delivery* (feature 010), not a
  button on this page. So the page offers exactly two honest actions —
  **"Download report (Markdown)"** → `getReportUrl(jobId,'md')` and **"Download
  data (JSON)"** → `getReportUrl(jobId,'json')` (both open the 011 endpoint) — and
  no Notion/JPG/PDF-split/email UI. (A real single-file PDF export and re-triggered
  Drive/Gmail delivery are possible later features, §5.)
- **D6 — Ingest-error & empty reports render a real minimal state, never a
  crash.** 009 Edge Case 1: an ingest failure yields a **minimal** report
  (`ingest_error` set, `findings` empty). The report page detects `ingest_error`
  and shows a clear **"We couldn't fully process this contract"** panel with the
  error message and the raw downloads (if `report_available`), *not* an empty
  findings list. A **successful but issue-free** report (`findings` empty,
  `ingest_error` null, e.g. `validated_findings === 0`) shows a positive **"No
  risky clauses found"** empty state with the summary counts and downloads —
  distinct from the ingest-error panel.
- **D7 — Direct-navigation / race guard (with 404 disambiguation).** The page is
  self-sufficient from the URL `jobId` (015 EC-7 style). On load it fetches
  `getReport(jobId)` and branches on the `ApiError.status`:
  - **409** (job exists but not finished — the endpoint returns `409` until
    `completed`, per INV-1): redirect to the **processing** screen `/jobs/[jobId]`
    (the user watches it finish, then auto-redirects back here per D1) — not an
    error.
  - **404** — this status is **ambiguous** in the backend (`routes.py` returns 404
    both for an unknown job *and* for a completed job whose file is missing on
    disk). The page **disambiguates by calling `getJob(jobId)`**: if `getJob` also
    404s (or the job is unknown) → the genuine unknown/evicted case (011 EC-9) →
    show **"report not found"** with a link to `/upload`; if `getJob` returns a
    `completed` job (the INV-2 out-of-band-artifact-loss case) → show **"report
    artifact unavailable"** (offer the other format / a link back to `/upload` to
    re-run), *not* a misleading "job not found". A `getJob` returning a
    non-terminal status is treated as the 409 case (redirect to processing).
  - **Any other error / network failure:** a "couldn't load the report" retry
    affordance (EC-3).
  This makes a bookmarked/refreshed report URL behave correctly whether the job is
  done, still running, gone, or completed-but-missing-its-file.
- **D8 — Provider seam / default mock.** Both the report page and the modified
  processing screen reach the backend only through `getApiClient()`; default
  provider stays **mock** (unit tests need no backend). The real path is covered by
  the live end-to-end smoke (AC-16), reusing 015's `provider=real` + Next dev proxy
  setup. The report JSON is a plain `fetch` (not SSE), so the proxy-buffering issue
  that forced 015's polling switch (015 D7) does **not** apply here.
- **D9 — Findings expanded state.** The findings list renders with the **first
  card expanded and the rest collapsed** (matches screen 7 and keeps a long report
  scannable). Each card toggles independently; the choice lives in one component so
  it is trivially switchable.
- **D10 — Auto-redirect timing.** On terminal `completed` (report-available), the
  processing screen shows the "Analysis complete ✓" flourish for a **brief ~1.2 s
  hold** (`REPORT_REDIRECT_DELAY_MS`, a §3-style tunable constant) and then
  `router.replace`s to the report page (D1) — hands-free, but the user sees the run
  finish before the page changes. The delay is a named constant, not a magic
  number, so it is tunable/zeroable in tests (a test can assert the `replace`
  fires after the timer without a real 1.2 s wait).

### 2.4 Outputs (what this feature renders)

- **Report page** (`/jobs/[jobId]/report`):
  1. **Header** — `original_filename`, the derived **risk band badge** + literal
     counts (D2), `generated_at` (formatted), an OCR note when `ocr_used`
     (with `ocr_confidence` if present), and the two **Download** actions (D5).
  2. **Summary strip** — `total_clauses`, `validated_findings`, `clean_clauses`,
     and the high/medium/low counts as small stat chips (reusing 013 primitives /
     the dashboard's stat styling).
  3. **Findings list** — `findings[]` as expandable risk cards (D3), ordered by
     `position`, styled after screen 7's AI Analysis Panel; the first (or all)
     expanded per design.
  4. **Terminal/empty states** — ingest-error panel and "no issues found" empty
     state (D6).
- **Modified processing screen** (`/jobs/[jobId]`, 015): the terminal `completed`
  (report-available) path auto-redirects here (D1) instead of showing the inline
  "Analysis complete" panel. All other 015 states (queued/running/failed/
  completed-with-ingest-error/not-found) are unchanged.

## 3. Acceptance criteria

Each becomes a test (Vitest + React Testing Library, driving the **mock** provider
unless noted; the real path is the live smoke, AC-16).

**Report page — header & summary**
- AC-1: Given a completed job whose report has findings, the report page renders
  the `original_filename`, the two Download actions with hrefs equal to
  `getReportUrl(jobId,'md')` and `getReportUrl(jobId,'json')`, and a summary strip
  showing `total_clauses` / high / medium / low from `summary`.
- AC-2: The header risk-band badge is **derived** (D2): a report with `high>0`
  shows "High risk"; a report with `high=0, medium>0` shows "Medium risk"; with
  only lows shows "Low risk"; with `validated_findings=0` shows "No issues found".
  No 0–100 score string is rendered (assert the mockup's "/100" is absent).
- AC-3: When `ocr_used` is true the header shows an OCR note (with
  `ocr_confidence` when present); when false, no OCR note.

**Report page — findings**
- AC-4: Each `findings[]` item renders a card in `position` order, titled by
  `clause_type` (title-cased) or "Clause {position}" when `clause_type` is null,
  with a risk badge matching `risk_level`.
- AC-5: A finding with `risk_level: null` renders a "Severity unavailable" badge,
  not a crash/blank (009 Edge Case 4).
- AC-6: A finding with `rewrite_state: "rewritten"` shows its `suggested_rewrite`
  text; `"unavailable"` shows the muted "couldn't be generated" note; and
  `"not_eligible"` shows **no** rewrite block (three-way, 009 AC-8).
- AC-7: A finding's `risk_rationale` is shown as the explanation; when `null`, a
  muted placeholder is shown, not a blank. There is **no** fabricated "Business
  Impact" text (D4 — assert only backend-provided fields appear).
- AC-8: A finding's `evidence[]` renders each `source_reference`+`snippet_text`;
  an empty `evidence` array renders no evidence section (no empty header).
- AC-9: Long `clause_text` is collapsed with an expand control that reveals the
  full text (no layout overflow); `confidence_score` shows when present, is
  omitted when null.

**Report page — empty / error states**
- AC-10: A report with `ingest_error` set and empty `findings` renders the
  "couldn't fully process" panel carrying the error message (D6), **not** an empty
  findings list, and still offers downloads when `report_available`.
- AC-11: A successful report with empty `findings` and no `ingest_error` renders
  the positive "no risky clauses found" empty state with the summary counts (D6),
  distinct from AC-10.

**Auto-redirect & navigation guard**
- AC-12: When 015's processing screen reaches terminal `completed` with
  `report_available === true`, it calls `router.replace('/jobs/{jobId}/report')`
  (assert the replace) and does **not** render the old inline "Analysis complete"
  panel.
- AC-13: A terminal `completed` with job-level `final.error` set (ingest-error
  completion — INV-3 guarantees this is exactly when the report has `ingest_error`;
  015 EC-1) does **not** auto-redirect to the full report; 015's completed-with-
  issue state is preserved (it may link to the report, but no auto-`replace`).
- AC-14: Loading `/jobs/[jobId]/report` when `getReport` rejects with `ApiError`
  status **409** redirects to `/jobs/[jobId]` (the processing screen, D7). On
  status **404**, the page disambiguates via `getJob(jobId)`: `getJob` 404/unknown
  → "report not found" + link to `/upload`; `getJob` returning a `completed` job →
  "report artifact unavailable" (INV-2), distinct from "not found". Other errors
  show a retry affordance — no unhandled throw. (Testable against the mock by
  scripting `getReport` to reject with a status and `getJob` to return the two
  cases.)

**Seam / boundary**
- AC-15: The report page and modified processing screen reach the backend **only**
  via `getApiClient()`; swapping provider mock↔real needs no component edit (013
  seam). `getReport` is defined on the `ApiClient` interface and both providers. No
  file under `backend/` is modified (structural check).
- AC-15a: The `ContractReport` TS mirror does not silently drop a 009 field. Since
  a plain `tsc` check compares object *shapes* but nothing automatically compares
  the TS interface to the Python model, this is enforced by an explicit
  **field-list fixture test**: a test asserts the TS mock fixture carries every
  field name in 009's `ContractReport`/`ReportSummary`/`ReportFinding`/
  `ReportEvidence` (the list is written down in the test), so adding/removing a
  backend field surfaces as a failing assertion — the same spirit as 015's
  `as const` drift-lock, extended to object fields.

**Live end-to-end (real backend)**
- AC-16 (smoke, manual/gated): With `NEXT_PUBLIC_API_PROVIDER=real` and `uvicorn`
  on `:8000`, uploading a real contract runs 015's watch view to completion, then
  **auto-redirects** to `/jobs/{id}/report`, which fetches the real report JSON
  through the Next dev proxy and renders the actual filename, risk band, and
  per-clause findings; both Download links open the real `.md`/`.json`.

## 4. Edge cases

- **EC-1 — Report not yet ready (409):** covered by D7/AC-14 — redirect to the
  processing screen; the run continues server-side and the user is auto-returned on
  completion.
- **EC-2 — 404 is two cases (INV-2):** a 404 from the report endpoint means either
  an unknown/evicted job **or** a completed job whose file was lost off disk. D7/
  AC-14 disambiguates via `getJob`: unknown → "report not found" + link to
  `/upload` (mirrors 011 EC-9 / 015 EC-6); completed-but-missing → "report artifact
  unavailable". No hang, no misleading message.
- **EC-3 — Backend unreachable / malformed JSON:** `getReport` rejects with
  `ApiError` (or a parse error wrapped as one); the page shows a "couldn't load the
  report" retry state, not an unhandled throw (mirrors 015 EC-3).
- **EC-4 — Ingest-error minimal report:** D6/AC-10 (009 Edge Case 1).
- **EC-5 — Zero-findings success:** D6/AC-11.
- **EC-6 — Missing optional fields:** `clause_type`, `risk_level`, `risk_rationale`,
  `suggested_rewrite`, `section_number`, `confidence_score`, `ocr_confidence` are
  all optional in 009; each has a defined fallback (§2.3 D2/D3, AC-5/7/9) so a
  sparse report never blanks or crashes.
- **EC-7 — Very large report (many findings / long clauses):** long `clause_text`
  is collapsed by default with an expand control (AC-9), and each finding card
  toggles independently (D9), so a 100-clause contract stays usable without
  fabricating a hard cap. Virtualization/pagination is **not** built in this
  feature (no AC, no "only if needed" hand-wave); collapse-by-default is the
  committed mechanism.
- **EC-8 — Direct navigation to a *running* job's report URL:** D7 — the 409
  redirect sends the user to the live processing view, then auto-redirects back
  when done (round-trips cleanly on refresh).
- **EC-9 — Back button after auto-redirect:** because D1 uses `router.replace`
  (not `push`), Back does not land on the finished processing screen (which would
  re-redirect); it returns to the pre-processing origin.

## 5. Out of scope

- **The contract-history table** (015 §5 filed it under 017) — split to a later
  slice so this feature stays focused on the report view + auto-redirect. Not built
  here.
- **The analysis workspace / clause chat / comparison / live Document View pane**
  (screen 7's left pane + Legal AI Assistant rail) — **spec 016**. This feature
  renders findings as a standalone report, not the interactive workspace.
- **Any backend change** — no new endpoint, no new field. Specifically **not**
  attempted here (each would be its own backend feature): a real document-level
  **0–100 risk score** in `ReportSummary` (D2), a per-clause **business-impact**
  field (D4), server-side **single-file PDF** export or a **Risk Scorecard image**
  (D5), and re-triggering **Drive/Gmail delivery** from this page (feature 010
  owns delivery; D5).
- **Notion / Slack / Dropbox / email-from-this-page UI** — Notion/Slack/Dropbox
  are PERMANENTLY CUT (constitution §2); email is delivery (010), not a report-page
  control (D5).
- **Dashboards / analytics / settings / auth / marketing** — specs 018 / 014.
- **Editing / accepting rewrites, exporting redlines to Word** — not offered; the
  report is read-only. (Redline *content* is shown per D3; applying it is not.)

## 6. Resolved decisions (no open questions)

Per the project's inline-decision preference, every significant choice is resolved
in §2.3 (D1–D10). The three previously-open items are now decided:

1. **Findings expanded state** → resolved in **D9** (first card expanded, rest
   collapsed, per-card toggle).
2. **Auto-redirect timing** → resolved in **D10** (brief ~1.2 s "complete ✓" hold
   via a named `REPORT_REDIRECT_DELAY_MS` constant, then `router.replace`).
3. **Deferred history table** → filed as its own **017b** slice (kept near the
   report work rather than folded into 018); see §5. Non-blocking for this feature.
