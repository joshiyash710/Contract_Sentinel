# Report View + Auto-redirect — Implementation Tasks

Reference documents:
- Spec: `specs/017-report-view/spec.md`
- Plan: `specs/017-report-view/plan.md`
- Report model consumed: `specs/009-report-agent/spec.md` + `backend/app/models/report.py` (`ContractReport`)
- API contract consumed: `specs/011-pipeline-runner-api/spec.md` §2 (`GET /api/jobs/{id}/report`, `GET /api/jobs/{id}`)
- Foundation reused: features 013 (`frontend/src/lib/api/*`, `frontend/src/components/ui/*`) + 015 (`ProcessingView`, `useJobStatus`, `_fakeClient.ts`)
- Constitution: `specs/000-constitution.md`
- Design references: `specs/013-frontend-design-system/design-refs/` screen 7 (`…31 PM (6).jpeg`, AI Analysis Panel) + screen 11 (`…32 PM (1).jpeg`, Generate & Download Reports)

All paths below are relative to `frontend/` unless stated. **No file under `backend/` is created or modified** (spec AC-15).

**Workflow reminders:**
- TDD per constitution §7 — write tests, confirm FAILING, then implement to PASS. Never weaken a test to force a pass. The one exception is the deliberate update to 015's `completed_shows_report_link` assertion (Task 7), which tracks the D1 behavior change.
- Reach the backend **only** through `getApiClient()` (013 seam). No component imports `realProvider`/`mockProvider` directly (spec AC-15).
- Consume the 009 report model via the new `@/lib/api/types.ts` mirrors unchanged — invent no field names (constitution §4). The internal `ContractState` never crosses the wire.
- **Reality-grounded (spec D2/D4/D5):** NO fabricated 0–100 score (derive a band from counts), NO fabricated "Business Impact" field, exactly two downloads (Markdown + JSON) — no Notion/JPG/PDF-split/email UI.
- **`"use client"` directive** is required on `ReportView`, `FindingCard`, `useReport`, and the modified `ProcessingView` (hooks/`useRouter`/`useState`/timers). The `report/page.tsx` stays a server component (review §3 header).
- **Three verified seam invariants** the guard logic leans on (spec §2.2a): **INV-1** `report_available===true ⟹ non-409`; **INV-2** both report formats co-exist on success, so a completed-job 404 = out-of-band loss (disambiguate via `getJob`); **INV-3** `report.ingest_error` set ⟺ `JobStatus.error.kind==="ingest_error"`.
- **NEVER run `next build` while `next dev` is running** — it corrupts `.next` (learned 013/015). Stop the dev server before any build.
- Locked defaults (spec §6): **D9** first card expanded, rest collapsed; **D10** ~1.2 s "Analysis complete ✓" hold (`REPORT_REDIRECT_DELAY_MS`) before `router.replace`; deferred history table → separate 017b (not this feature).

---

## Task 0: Start the feature branch

- [ ] Confirm `spec.md`, `plan.md`, `tasks.md` exist and are approved (constitution §1/§11 gate).
- [ ] From an up-to-date `main`, create/checkout `feature/017-report-view` (the `git-start` skill does this).

**Verify:** `git branch --show-current` → `feature/017-report-view`. The 013 + 015 work is already on `main`.

---

## Task 1: `types.ts` mirror + `getReport` seam + fixtures (tests first)

- [ ] **[MODIFY] `src/lib/api/types.ts`** — add the 009 report mirrors exactly per plan §3.1: `ReportEvidence`, `RewriteState` (`"rewritten"|"unavailable"|"not_eligible"`), `ReportFinding` (all fields; `risk_level?: string | null` widened defensively), `ReportSummary`, `ContractReport`. Every field name must match `backend/app/models/report.py` verbatim.
- [ ] **[MODIFY] `src/lib/api/client.ts`** — add `getReport(jobId: string): Promise<ContractReport>` to the `ApiClient` interface.
- [ ] **[MODIFY] `src/lib/api/realProvider.ts`** — implement `getReport`: `fetch(getReportUrl(jobId,"json"))`; on `!res.ok` throw `new ApiError('HTTP ' + res.status, res.status)` (**status preserved** for the D7 409/404 branch); wrap network/parse failures in `ApiError` too (EC-3). Follow the existing `asJson`/try-catch pattern.
- [ ] **[MODIFY] `src/lib/api/fixtures.ts`** — add three fixtures:
  - `reportFixture: ContractReport` — **rich**: several `findings` covering all card branches — one High with `risk_level:"high"` + `rewrite_state:"rewritten"` + `suggested_rewrite` + `evidence[≥1]`; one Medium `rewrite_state:"unavailable"`; one Low `rewrite_state:"not_eligible"` + empty `evidence`; one with `risk_level:null` (severity unavailable) + `risk_rationale:null`; a long `clause_text` on at least one. `summary` counts consistent with the findings. `ocr_used:false`, `ingest_error:null`.
  - `ingestErrorReportFixture: ContractReport` — `ingest_error:{message:"Could not parse the uploaded file"}`, `findings:[]`, summary zeros.
  - `emptyReportFixture: ContractReport` — `ingest_error:null`, `findings:[]`, `summary.validated_findings:0`, `ocr_used:true`, `ocr_confidence:0.87`.
- [ ] **[MODIFY] `src/lib/api/mockProvider.ts`** — implement `getReport(jobId)` returning `{ ...reportFixture, document_id: jobId }`.
- [ ] **[NEW] `src/__tests__/report-fields.test.ts`** — confirm FAILING, then GREEN: assert `reportFixture` (and the finding/summary/evidence shapes) carry **every** field name listed for 009's `ContractReport`/`ReportSummary`/`ReportFinding`/`ReportEvidence` (write the expected key list literally in the test). A backend add/remove then surfaces as a failing assert (spec AC-15a, the drift lock).

**Verify:** `npx vitest run src/__tests__/report-fields.test.ts` → PASS; `npx tsc --noEmit` compiles.

---

## Task 2: `lib/riskBand.ts` + `lib/reportFormat.ts` — pure logic (tests first)

- [ ] **[NEW] `src/__tests__/riskBand.test.ts`** — confirm FAILING (spec D2/AC-2):
  - `high_dominates`: `{high:1,medium:5,low:9,validated_findings:15,…}` → `{band:"high",label:"High risk"}`.
  - `medium_when_no_high`: `{high:0,medium:2,…}` → "Medium risk".
  - `low_when_only_lows`: `{high:0,medium:0,low:3,validated_findings:3}` → "Low risk".
  - `none_when_no_findings`: `{high:0,medium:0,low:0,validated_findings:0}` → "No issues found".
  - `counts_line`: `countsLine` renders "H high · M medium · L low across T clauses".
- [ ] **[NEW] `src/lib/riskBand.ts`** — implement `deriveRiskBand(summary)` + `countsLine(summary)` exactly per plan §3.3. No "/100" anywhere.
- [ ] **[NEW] `src/__tests__/reportFormat.test.ts`** — confirm FAILING:
  - `title_cases_clause_type`: `findingTitle({clause_type:"limitation_of_liability", position:1})` → "Limitation Of Liability".
  - `falls_back_to_position`: `findingTitle({clause_type:null, position:3})` → "Clause 3" (position **verbatim**, D3).
  - `formats_generated_at`: `formatGeneratedAt(iso)` returns a human string (non-empty, no throw on a valid ISO).
- [ ] **[NEW] `src/lib/reportFormat.ts`** — implement `titleCase`, `findingTitle(f)`, `formatGeneratedAt(iso)` per plan §3.7.

**Verify:** `npx vitest run src/__tests__/riskBand.test.ts src/__tests__/reportFormat.test.ts` → PASS.

---

## Task 3: extend `_fakeClient.ts` (no test of its own; used by later tasks)

- [ ] **[MODIFY] `src/__tests__/_fakeClient.ts`** — extend `makeFakeClient(opts)` (015's helper) with:
  - `getReport`: resolves `opts.report ?? reportFixture`, OR rejects `opts.getReportError` (an `ApiError` with a chosen `status`) when provided — for the 409/404/error branches.
  - `getJob`: resolves `opts.job ?? completedFinal()`, OR rejects `opts.getJobError` when provided — for the 404 disambiguation (unknown vs completed vs running).
  - Add builders: `reportWith(findings, overrides?)` and reuse `completedFinal({status})` from 015.

**Verify:** `npx tsc --noEmit` compiles (util only).

---

## Task 4: `lib/useReport.ts` — fetch + D7 guard hook (tests first)

- [ ] **[NEW] `src/__tests__/useReport.test.tsx`** — confirm FAILING. `renderHook` + `vi.mocked(getApiClient).mockReturnValue(fake)`. **Router mock must expose `replace`** (the `redirecting` phase drives `router.replace` in the component; if a test renders one, use `vi.mock("next/navigation", () => ({ useRouter: () => ({ push, replace }) }))` with both spies — review B1). (spec D7/AC-14, EC-1/2/3):
  - `loads_report`: `getReport` resolves → `phase==="loaded"`, `report` set.
  - `409_redirects`: `getReportError = new ApiError("x",409)` → `phase==="redirecting"`.
  - `404_unknown_job`: `getReportError=404` + `getJobError` set → `phase==="not_found"`.
  - `404_completed_job`: `getReportError=404` + `getJob` resolves `completedFinal({status:"completed"})` → `phase==="artifact_unavailable"` (INV-2).
  - `404_running_job`: `getReportError=404` + `getJob` resolves `{status:"running"}` → `phase==="redirecting"`.
  - `network_error_retry`: `getReportError = new ApiError("net")` (no status) → `phase==="error"`; calling `retry()` re-runs the fetch (spy count increases).
- [ ] **[NEW] `src/lib/useReport.ts`** — `"use client"`; implement `ReportPhase`/`ReportState`/`useReport(jobId)` exactly per plan §3.4 (fetch in `useEffect`; branch on `ApiError.status` 409 → `redirecting`, 404 → `getJob` disambiguation, else `error`; `retry()` bumps a key). Navigation stays in the component, not the hook (`redirecting` is a phase).

**Verify:** `npx vitest run src/__tests__/useReport.test.tsx` → PASS.

---

## Task 5: Report UI components (tests first)

- [ ] **[NEW] `src/__tests__/report.test.tsx`** — confirm FAILING. **Router mock must expose BOTH `push` and `replace`** (`vi.mock("next/navigation", () => ({ useRouter: () => ({ push, replace }) }))` — the `redirecting`/`not_found` paths use `replace`; review B1) + inject `makeFakeClient` via `vi.mocked(getApiClient).mockReturnValue(...)` per test. Render `<ReportView jobId="job-1" />`. Tests (spec AC-1,3,4,5,6,7,8,9,10,11):
  - `header_and_downloads`: `reportFixture` → filename shown; two links with hrefs `/api/jobs/job-1/report?format=md` and `?format=json`; summary chips for total/high/medium/low (AC-1).
  - `derived_band_no_score`: header shows the `deriveRiskBand` label; assert the text has **no** "/100" (AC-2).
  - `ocr_note`: `emptyReportFixture` (`ocr_used:true`, conf 0.87) → OCR note with the % present; the rich fixture (`ocr_used:false`) → no OCR note (AC-3).
  - `findings_in_order`: cards render in `position` order, titled by `clause_type`/"Clause {position}" (AC-4).
  - `null_severity_badge`: the null-`risk_level` finding → "Severity unavailable" badge, no crash (AC-5).
  - `rewrite_three_way`: the `rewritten` finding shows its `suggested_rewrite`; `unavailable` shows the muted "couldn't be generated" note; `not_eligible` shows **no** rewrite block (AC-6).
  - `rationale_and_no_business_impact`: `risk_rationale` shown; the null-rationale finding shows the muted placeholder; assert **no** "Business Impact" heading/text anywhere (AC-7/D4).
  - `evidence_list`: the finding with evidence renders each `source_reference`+`snippet_text`; the empty-evidence finding renders no "Supporting sources" header (AC-8).
  - `long_clause_collapses`: the long `clause_text` is truncated with an expand control; activating it reveals full text; `confidence_score` renders when present, omitted when null (AC-9).
  - `ingest_error_panel`: inject `report = ingestErrorReportFixture` → "couldn't fully process" panel with the message, **not** an empty findings list (AC-10).
  - `zero_findings_empty_state`: inject `report = emptyReportFixture` → "No risky clauses found" positive empty state + summary counts, distinct from AC-10 (AC-11).
  - `not_found_and_artifact_states`: `getReportError=404`+`getJobError` → "report not found" + a link to `/upload`; `getReportError=404`+`getJob` completed → "artifact unavailable" copy (EC-2).
- [ ] **[NEW] `src/components/report/RiskBadge.tsx`** — `risk_level` → High/Medium/Low colored badge (013 risk tokens); `null` → neutral "Severity unavailable" (AC-5). Shared.
- [ ] **[NEW] `src/components/report/SummaryStrip.tsx`** — stat chips: total_clauses / validated_findings / clean_clauses / high / medium / low (reuse dashboard stat styling).
- [ ] **[NEW] `src/components/report/ReportHeader.tsx`** — filename, `deriveRiskBand` badge + `countsLine`, `formatGeneratedAt`, OCR note (with `ocr_confidence` %) when `ocr_used`, and the two Download `<a>` actions via `getReportUrl` (D5). No Notion/JPG/PDF-split/email controls.
- [ ] **[NEW] `src/components/report/FindingCard.tsx`** — `"use client"`; one `ReportFinding` per plan §3.7: title (`findingTitle`, `section_number` prefix), `RiskBadge` + confidence, explanation (`risk_rationale` / muted placeholder, **no Business Impact**), collapsible `clause_text`, three-way rewrite block, evidence list. `useState(open)` with initial from a prop (D9).
- [ ] **[NEW] `src/components/report/ReportView.tsx`** — `"use client"`; `useReport(jobId)` → render by phase per plan §3.5: `loading`; `redirecting` (`useEffect` → `router.replace('/jobs/'+jobId)`); `not_found` (link `/upload`); `artifact_unavailable` (distinct copy + "start new analysis"); `error` (Retry → `retry()`); `loaded` → branch `ingest_error` panel (D6) / zero-findings empty state (D6) / full report (`ReportHeader`+`SummaryStrip`+`FindingCard`s, first expanded). **`ingest_error` is a `dict`, not a string** — read the message as `String((report.ingest_error as { message?: unknown })?.message ?? JSON.stringify(report.ingest_error))` so `tsc --noEmit` (Task 8) stays clean (review B4).
- [ ] **[NEW] `src/app/jobs/[jobId]/report/page.tsx`** — server component: read `params.jobId`, render `<ReportView jobId={params.jobId} />` inside the app shell.

**Verify:** `npx vitest run src/__tests__/report.test.tsx` → PASS.

---

## Task 6: Auto-redirect from the processing screen (tests first)

- [ ] **[NEW] `src/__tests__/processing-redirect.test.tsx`** — confirm FAILING. Harness (review B1/B3):
  - **Router mock exposes BOTH spies:** `const push = vi.fn(); const replace = vi.fn(); vi.mock("next/navigation", () => ({ useRouter: () => ({ push, replace }) }))`. (Copying 015's `{ push }`-only mock would make `router.replace` throw.)
  - **Real timers + delay mocked to 0 (NOT `vi.useFakeTimers()`):** `vi.mock("@/lib/reportConstants", () => ({ REPORT_REDIRECT_DELAY_MS: 0 }))`. `useJobStatus` polls immediately and resolves the completed status via a **microtask**, so the redirect timer is only scheduled *after* the completed state renders; fake timers won't advance that promise and can deadlock RTL `waitFor`. With the delay at 0, `await waitFor(() => expect(replace).toHaveBeenCalledWith("/jobs/job-1/report"))` cleanly observes the redirect. Inject terminal states via `makeFakeClient({ statuses: [...] })`.
  - Tests (spec AC-12/AC-13, EC-9, INV-1/INV-3):
    - `completed_auto_redirects`: `completedFinal({report_available:true})` (no error) → `await waitFor` that `replace` was called with `/jobs/job-1/report`; assert the inline "View report" link is **not** the resting state (AC-12).
    - `completed_redirect_uses_replace_not_push`: same setup → `push` was NOT called with the report URL (locks EC-9 — Back must not re-hit the finished processing screen).
    - `completed_no_report_stays_inline`: `completedFinal({report_available:false})` → after the completed state renders, `replace` NOT called (INV-1 defensive guard; note this is a synthetic state the backend never emits — review B2).
    - `completed_with_issue_no_redirect`: `completedFinal({error:{kind:"ingest_error",message:"bad pdf"}, report_available:true})` → `replace` NOT called; inline "finished with an issue" + "bad pdf" preserved (AC-13/INV-3).
    - `failed_unchanged`: `completedFinal({status:"failed"})` → "Retry" → `push('/upload')` (015 behavior intact; `replace` not called).
- [ ] **[NEW] `src/lib/reportConstants.ts`** — `export const REPORT_REDIRECT_DELAY_MS = 1200;` (D10). Created before the redirect test imports/mocks it.
- [ ] **[MODIFY] `src/components/processing/ProcessingView.tsx`** — add the top-level redirect `useEffect` per plan §3.8. **Placement: insert it immediately after the `useJobStatus`/`useRouter` calls and BEFORE the first `if (state.phase === "failed")` early-return** (Rules of Hooks — the component early-returns per phase, so no hook may sit below those returns). The effect fires `router.replace('/jobs/'+jobId+'/report')` after `REPORT_REDIRECT_DELAY_MS` **only** when `phase==="completed"` && `!state.final?.error` && `state.final?.report_available`; cleanup clears the timer. Change the clean-completion render to a brief "Analysis complete ✓" flourish (the redirect follows). **Leave** the completed-with-issue branch (`issue = state.final?.error`) and the `failed`/`error`/running/connecting renders unchanged.

**Verify:** `npx vitest run src/__tests__/processing-redirect.test.tsx` → PASS.

---

## Task 7: Reconcile 015's processing test + boundary tests

- [ ] **[MODIFY] `src/__tests__/processing.test.tsx`** (015) — the `completed_shows_report_link` test asserted the old inline "View report" resting state, which D1 replaces with the auto-redirect. **Update** it: for a clean completion it now asserts the brief "Analysis complete ✓" state (the redirect assertion lives in `processing-redirect.test.tsx`). Keep `ingest_error_soft_state` and `failed_shows_retry` as-is (those paths are unchanged). This is the one sanctioned test change (constitution §7 — the behavior changed per D1, so the test tracks it).
- [ ] **[NEW] `src/__tests__/report-boundary.test.ts`** — boundary checks (spec AC-15):
  - `report_uses_getApiClient_only`: read files under `src/components/report` and the modified `ProcessingView`; assert none imports `realProvider`/`mockProvider` (AC-15).
  - (AC-15 no-backend-edits is verified in Task 8 via `git diff`; type drift via `tsc`.)
- [ ] Confirm the existing 013/015 suites still pass (shell, upload, useJobStatus, etc.).

**Verify:** `npx vitest run` (whole suite) → all PASS, including the untouched 013/015 tests.

---

## Task 8: Full verification pass

- [ ] `npx vitest run` — entire suite GREEN (013 + 015 + 017).
- [ ] `npx tsc --noEmit` — no type errors (the `ContractReport` mirror + drift lock hold).
- [ ] `npm run lint` — clean.
- [ ] **Stop the dev server if running**, then `npx next build` — succeeds; the new route `/jobs/[jobId]/report` appears (dynamic).
- [ ] `git diff --name-only` — confirm **no** path under `backend/` changed (spec AC-15).

**Verify:** all green; build lists the new report route.

---

## Task 9: Live end-to-end smoke against the real backend (spec AC-16)

- [ ] Stop the dev server. Ensure the backend is running: `uvicorn app.api.main:app --host 127.0.0.1 --port 8000` (and Ollama up, `qwen3:8b` per config).
- [ ] `frontend/.env.local`: `NEXT_PUBLIC_API_PROVIDER=real` and `NEXT_PUBLIC_API_BASE_URL=` (empty → same-origin via the dev proxy; do NOT set a direct `:8000` URL — CORS footgun).
- [ ] `npm run dev`; open `http://localhost:3000/upload`; upload a real contract (e.g. `backend/data/heavy_contract.docx`).
- [ ] Confirm: 015's processing view runs to completion (slow — minutes, per constitution §9), then **auto-redirects** to `/jobs/{id}/report` after the ~1.2 s hold; the page shows the real filename, derived risk band + counts, and per-clause findings (risk badge → rationale → clause text → rewrite → evidence); both Download links open the real `.md`/`.json`. Also spot-check a **direct** navigation/refresh of `/jobs/{id}/report` (INV-2 / D7 guard). Note the result.
- [ ] Reset `.env.local` provider back to `mock` (or delete it) so the default dev/test posture is mock again.

**Verify:** a real upload runs end-to-end → live watch → auto-redirect → real report renders with working downloads. Report the outcome to the user (the "run the real smoke before continuation" practice).

---

## Task 10: Finish the feature branch

- [ ] Full suite + `tsc` + `next build` green (Task 8); live smoke noted (Task 9).
- [ ] Rebase latest `main` into the branch, resolve conflicts on the branch (constitution §11), merge to `main`, delete the branch (the `git-finish` skill).

**Verify:** on `main`; `feature/017-report-view` gone; suite + build green on `main`.

---

*Per constitution §1/§11, implementation happens only on `feature/017-report-view`, opened after spec + plan + tasks are approved. The deferred contract-history table is a later 017b slice (spec §5); remaining screens are 016 (workspace/chat/comparison) and 018 (dashboards/settings).*
