# Report View + Auto-redirect — Technical Plan

## Git Branch

`feature/017-report-view` — branching workflow per `specs/000-constitution.md` §11.

---

## 1. Overview

This plan implements the **report page** and the **auto-redirect** specified in
`specs/017-report-view/spec.md` — the destination the user lands on after watching
the pipeline run. It builds on 013 (tokens, shell, primitives, the mock/real
API-client seam) and 015 (the upload + live processing screens). It adds **no
backend change**: the report JSON is already served by `GET
/api/jobs/{id}/report?format=json` (011), and it reaches the backend **only**
through `getApiClient()` (013 seam).

**One new route (spec D1):**
- `/jobs/[jobId]/report` — fetches the real `ContractReport` (009) via
  `getApiClient().getReport(jobId)` and renders the header (filename + derived risk
  band + counts + downloads), the summary strip, and the per-clause findings list.
  On load it applies the D7 guard (409 → redirect to processing; 404 →
  disambiguate via `getJob`).

**One behavioral change to 015 (spec D1):** `ProcessingView`'s terminal
`completed` branch — when `report_available === true` **and** there is no
job-level `final.error` (INV-1/INV-3) — holds the "Analysis complete ✓" flourish
for `REPORT_REDIRECT_DELAY_MS` (~1.2 s, D10) then `router.replace('/jobs/' + jobId
+ '/report')`. The **completed-with-issue** branch (`final.error` set) stays inline
(no auto-redirect, per INV-3); `failed` and all running/connecting states are
unchanged.

**The three seam invariants the guard logic leans on (spec §2.2a, verified against
the runner):** INV-1 `report_available ⟹ non-409`; INV-2 both report formats
co-exist on the success path (a completed-job 404 = out-of-band artifact loss, not
"unknown job"); INV-3 `report.ingest_error` set ⟺ `JobStatus.error.kind ===
"ingest_error"`. The plan relies on these rather than re-deriving them.

**Consumes 009's `ContractReport` unchanged.** The only new typed surface is a TS
mirror of `ContractReport`/`ReportSummary`/`ReportFinding`/`ReportEvidence` in
`types.ts` and a `getReport()` method on `ApiClient`. No new/divergent field names;
the internal `ContractState` TypedDict never crosses the wire (constitution §4).

**Reality-grounded (spec D2/D4/D5), not the mockups' fiction:** no fabricated
0–100 score (derive a band from real counts), no fabricated "Business Impact" field,
two honest downloads (Markdown + JSON) — no Notion/JPG/PDF-split/email UI.

---

## 2. Files to Create / Modify (all under `frontend/`)

```
src/
  lib/
    riskBand.ts                     [NEW] deriveRiskBand(summary) → {band,label} (D2) — pure
    reportFormat.ts                 [NEW] titleCase(clauseType), findingTitle(f), formatGeneratedAt() — pure display helpers
    useReport.ts                    [NEW] hook: getReport(jobId) + D7 409/404 guard → typed state
    reportConstants.ts              [NEW] REPORT_REDIRECT_DELAY_MS (D10 tunable constant)
    api/
      types.ts                      [MODIFY] + ContractReport / ReportSummary / ReportFinding / ReportEvidence mirrors
      client.ts                     [MODIFY] + getReport(jobId): Promise<ContractReport> on ApiClient
      realProvider.ts               [MODIFY] + getReport (fetch ?format=json → parse → ApiError wrap, status preserved)
      mockProvider.ts               [MODIFY] + getReport (returns the report fixture)
      fixtures.ts                   [MODIFY] + reportFixture (rich), ingestErrorReportFixture, emptyReportFixture
  components/
    report/
      ReportView.tsx                [NEW] client; useReport(jobId) → loading / redirecting / not-found / artifact-unavailable / error / ingest-error / empty / loaded
      ReportHeader.tsx              [NEW] filename, risk-band badge (riskBand), counts, generated_at, OCR note, 2 Download actions (D5)
      SummaryStrip.tsx              [NEW] stat chips: total / validated / clean / high / medium / low
      FindingCard.tsx               [NEW] one expandable finding (D3): title, risk badge, explanation, clause text (collapsible), rewrite (three-way), evidence, confidence
      RiskBadge.tsx                 [NEW] risk_level → colored badge; null → "Severity unavailable" (AC-5)
    processing/
      ProcessingView.tsx            [MODIFY] completed branch → auto-redirect (D1/D10); keep completed-with-issue inline
  app/
    jobs/[jobId]/report/page.tsx    [NEW] server component: reads params.jobId → <ReportView jobId=… />
  __tests__/
    riskBand.test.ts                [NEW] AC-2 band derivation (D2)
    reportFormat.test.ts            [NEW] title-case / findingTitle / formatGeneratedAt helpers
    useReport.test.tsx              [NEW] AC-14 / EC-1/2/3 (409 redirect, 404 disambiguation, load/error)
    report.test.tsx                 [NEW] AC-1,3,4,5,6,7,8,9,10,11 (render, badges, rewrite three-way, evidence, ingest-error, empty)
    report-fields.test.ts           [NEW] AC-15a field-list drift lock vs 009
    report-boundary.test.ts         [NEW] AC-15 getApiClient-only / no direct-provider-import
    processing-redirect.test.tsx    [NEW] AC-12 / AC-13 (completed → replace; completed-with-issue → no replace)
    _fakeClient.ts                  [MODIFY] + getReport / getReportError / job-for-disambiguation scripting
```

Nothing else in 013/015 is touched except the one `ProcessingView` `[MODIFY]` and
the four seam files. No `backend/` file (AC-15).

---

## 3. Design details

> **Client vs. server components (Next.js App Router — constitution §8).**
> `ReportView`, `FindingCard`, and the modified `ProcessingView` MUST begin with
> `"use client"` (hooks, `useRouter`, `useState`, timers). `ReportHeader`,
> `SummaryStrip`, `RiskBadge` are presentational and may stay server-renderable, but
> since they're only ever rendered inside the client `ReportView` tree they need no
> directive. `app/jobs/[jobId]/report/page.tsx` stays a **server** component that
> reads `params.jobId` and renders the client `<ReportView/>`. `useReport.ts` is a
> hook (`"use client"`).

### 3.1 `[MODIFY] src/lib/api/types.ts` — the `ContractReport` mirror (constitution §4)

Field-for-field mirror of 009 `app/models/report.py` (verified against that file).
Reuses the existing `RiskLevel` tuple where applicable, but note `risk_level` on the
wire is an **optional string** (009 `Optional[str]`), so the mirror types it as
`RiskLevel | null` widened to `string | null` defensively (an unknown value must not
crash — AC-5).

```ts
// ── 009 report boundary model (Node 7 output; never ContractState, constitution §4) ──
export interface ReportEvidence {
  source_reference: string;
  snippet_text: string;
}
export type RewriteState = "rewritten" | "unavailable" | "not_eligible"; // 009 three-way (AC-8)
export interface ReportFinding {
  clause_id: string;
  position: number;
  section_number?: string | null;
  clause_type?: string | null;
  risk_level?: string | null;          // RiskLevel value, or null → "Severity unavailable"
  risk_rationale?: string | null;
  clause_text: string;
  rewrite_state: RewriteState;
  suggested_rewrite?: string | null;   // present only when rewrite_state === "rewritten"
  path_taken?: string | null;
  confidence_score?: number | null;
  evidence: ReportEvidence[];
}
export interface ReportSummary {
  total_clauses: number;
  validated_findings: number;
  clean_clauses: number;
  high: number;
  medium: number;
  low: number;
}
export interface ContractReport {
  document_id: string;
  original_filename: string;
  uploaded_at: string;
  processing_started_at?: string | null;
  generated_at: string;
  ocr_used: boolean;
  ocr_confidence?: number | null;
  ingest_error?: Record<string, unknown> | null; // set → minimal report (D6 / 009 Edge Case 1)
  summary: ReportSummary;
  findings: ReportFinding[];
  node_timings: Record<string, unknown>;
  error_count: number;
}
```

`document_id`, `processing_started_at`, `node_timings`, `error_count`, `clause_id`,
`path_taken` are in the mirror for faithfulness but **not rendered** (spec §2.1
"Intentionally not rendered").

### 3.2 `[MODIFY] client.ts / realProvider.ts / mockProvider.ts` — `getReport`

`ApiClient` gains one method:

```ts
getReport(jobId: string): Promise<ContractReport>;
```

- **realProvider:** `fetch(getReportUrl(jobId,"json"))` → on `!res.ok` throw
  `new ApiError('HTTP ' + res.status, res.status)` (status **preserved** so
  `useReport` can branch on 409/404, D7); parse errors wrapped as `ApiError` too
  (EC-3). Mirrors the existing `asJson` pattern in `realProvider.ts`.
- **mockProvider:** `async getReport(jobId) { return { ...reportFixture, document_id: jobId }; }`
  — zero network, so the report page and its unit tests need no backend (D8).

### 3.3 `[NEW] src/lib/riskBand.ts` — derived risk band (spec D2)

Pure; the **only** overall-severity logic (no fabricated 0–100 score).

```ts
import type { ReportSummary } from "@/lib/api/types";
export type RiskBand = "high" | "medium" | "low" | "none";

export function deriveRiskBand(s: ReportSummary): { band: RiskBand; label: string } {
  if (s.high > 0) return { band: "high", label: "High risk" };
  if (s.medium > 0) return { band: "medium", label: "Medium risk" };
  if (s.validated_findings > 0) return { band: "low", label: "Low risk" };
  return { band: "none", label: "No issues found" };
}

export function countsLine(s: ReportSummary): string {
  return `${s.high} high · ${s.medium} medium · ${s.low} low across ${s.total_clauses} clauses`;
}
```

The `band` maps to the 013 risk tokens (`--risk-high|medium|low`; `none` → a neutral
success token) in `RiskBadge`/`ReportHeader`. No "/100" string is ever rendered
(AC-2).

### 3.4 `[NEW] src/lib/useReport.ts` — fetch + D7 guard hook

Discriminated UI state; applies INV-1/INV-2 branching. Subscribes once per `jobId`.

```ts
export type ReportPhase =
  | "loading"
  | "loaded"              // has a ContractReport
  | "redirecting"         // 409 or non-terminal job → go watch it (D7)
  | "not_found"           // 404 + getJob unknown (INV-2 unknown-job case)
  | "artifact_unavailable"// 404 + getJob completed (INV-2 out-of-band loss)
  | "error";              // network / parse (EC-3)

export interface ReportState {
  phase: ReportPhase;
  report?: ContractReport | null;
  message?: string;
}

export function useReport(jobId: string): { state: ReportState; retry: () => void } { … }
```

Load flow (in the effect):
1. `getApiClient().getReport(jobId)` → success ⇒ `phase:"loaded"`.
2. `ApiError` with `status === 409` ⇒ `phase:"redirecting"`; the component
   `router.replace('/jobs/' + jobId)` (watch it finish; D1 brings the user back).
3. `ApiError` with `status === 404` ⇒ **disambiguate** with
   `getApiClient().getJob(jobId)`:
   - `getJob` rejects (404/unknown) ⇒ `phase:"not_found"` (link to `/upload`).
   - `getJob` resolves with `status === "completed"` ⇒ `phase:"artifact_unavailable"`
     (INV-2 out-of-band loss; offer `/upload` re-run + the other format link).
   - `getJob` resolves non-terminal (`queued`/`running`) ⇒ `phase:"redirecting"`
     (treat like 409).
4. Any other error ⇒ `phase:"error"` with a retry (`retry()` bumps a key that
   re-runs the effect).

`redirecting` is a phase (not an inline `router.replace` inside the hook) so the
navigation lives in the component and stays test-observable (assert the phase, or
assert the mocked `router.replace`).

### 3.5 `[NEW] src/components/report/ReportView.tsx`

Client component: `const { state, retry } = useReport(jobId)`. Renders by phase:
- `loading` → a skeleton/"Loading your report…".
- `redirecting` → `useEffect(() => router.replace('/jobs/' + jobId), [])` + a brief
  "Finishing analysis…" (D7 409 path).
- `not_found` → "We couldn't find that report." + link to `/upload` (EC-2 unknown).
- `artifact_unavailable` → "This report's files are no longer available." + a
  "Start a new analysis" link (EC-2 INV-2 case) — distinct copy from `not_found`.
- `error` → "We couldn't load the report." + a Retry calling `retry()` (EC-3).
- `loaded` → branch on the report contents:
  - `report.ingest_error` set ⇒ the **ingest-error panel** (D6/AC-10): a clear
    "We couldn't fully process this contract" with the message pulled from the
    `ingest_error` dict, plus the Download actions when the files exist. **Not** an
    empty findings list. Because the mirror types `ingest_error` as
    `Record<string, unknown> | null` (a `dict` on the wire, not a string), the
    message read must narrow/cast for `tsc --noEmit` (Task 8): use
    `String((report.ingest_error as { message?: unknown })?.message ??
    JSON.stringify(report.ingest_error))` — never assume a bare string.
  - else `report.findings.length === 0` ⇒ the **positive empty state** (D6/AC-11):
    "No risky clauses found" + `SummaryStrip` + Downloads.
  - else the **full report**: `<ReportHeader/>`, `<SummaryStrip/>`, then
    `report.findings` (already `position`-ordered by the backend) mapped to
    `<FindingCard/>`, **first expanded, rest collapsed** (D9).

### 3.6 `[NEW] ReportHeader.tsx` / `SummaryStrip.tsx` / `RiskBadge.tsx`

- **ReportHeader** (screen-11 header, grounded): `original_filename`, the
  `deriveRiskBand(summary)` badge + `countsLine(summary)`, `formatGeneratedAt`, an
  OCR note when `ocr_used` (append `ocr_confidence` as a % when present, AC-3), and
  the two Download actions — `<a href={getReportUrl(jobId,'md')}>Download report
  (Markdown)</a>` and `…'json'` "Download data (JSON)" (D5, AC-1). No Notion/JPG/
  PDF-split/email controls.
- **SummaryStrip**: stat chips for `total_clauses`, `validated_findings`,
  `clean_clauses`, `high`, `medium`, `low` reusing the dashboard stat styling.
- **RiskBadge**: `risk_level` → High/Medium/Low colored badge (013 risk tokens);
  `null` → neutral "Severity unavailable" (AC-5). Shared by header/cards.

### 3.7 `[NEW] src/components/report/FindingCard.tsx` (screen 7's AI Analysis card)

One `ReportFinding` → an expandable card (own `useState(open)`; D9 sets initial):
- **Title** (`reportFormat.findingTitle`): `titleCase(clause_type)` or "Clause
  {position}" (`position` **verbatim** to match the backend's `## Finding
  {position}` Markdown, D3); `section_number` as a subtle locator prefix when set.
- **`RiskBadge`** for `risk_level`; `confidence_score` shown as "N% confidence"
  when present, omitted when null (AC-9).
- **Explanation** ("AI Explanation" heading): `risk_rationale`, or a muted "No
  explanation provided" when null (AC-7). **No "Business Impact" heading** — that
  field doesn't exist in 009 (D4); nothing fabricated.
- **Clause text** ("Text"): `clause_text` in a quoted/monospace block, collapsed by
  default when long with an expand control (AC-9, EC-7) — collapse only, no
  virtualization.
- **Suggested rewrite** (three-way on `rewrite_state`, AC-6): `"rewritten"` →
  highlighted `suggested_rewrite` block; `"unavailable"` → muted "A safer rewrite
  couldn't be generated for this clause."; `"not_eligible"` → **no** rewrite block.
- **Evidence** ("Supporting sources"): map `evidence[]`
  (`source_reference`+`snippet_text`); render nothing (no header) when empty (AC-8).

### 3.8 `[MODIFY] src/components/processing/ProcessingView.tsx` — auto-redirect (D1/D10)

Only the `state.phase === "completed"` branch changes (currently
`ProcessingView.tsx:54-90`, the inline "Analysis complete" + View report/JSON
links). New behavior:

```ts
// inside ProcessingView — MUST be placed ABOVE the phase early-returns (Rules of
// Hooks: the component currently early-returns for failed/error/completed before any
// hook other than useJobStatus + useRouter, so the new useEffect goes right after
// those two calls, before the first `if`).
useEffect(() => {
  if (state.phase !== "completed") return;
  if (state.final?.error) return;               // completed-with-issue → stay inline (INV-3, AC-13)
  if (!state.final?.report_available) return;   // no report → stay inline (INV-1)
  const t = setTimeout(
    () => router.replace(`/jobs/${jobId}/report`),
    REPORT_REDIRECT_DELAY_MS,
  );
  return () => clearTimeout(t);
}, [state.phase, state.final?.error, state.final?.report_available, jobId, router]);
```

The render for a clean completion becomes the brief "Analysis complete ✓" flourish
(the redirect fires after the delay). The **completed-with-issue** render (the
`issue = state.final?.error` branch) is **unchanged** — it keeps the inline "finished
with an issue" panel and may still link to the report (which will render the D6
panel), but does not auto-`replace`. `failed`/`error`/`running`/`connecting` are
untouched. `REPORT_REDIRECT_DELAY_MS` lives in `reportConstants.ts` so a test can
import and (via fake timers) advance it without a real 1.2 s wait.

### 3.9 `[NEW] src/lib/reportConstants.ts`

```ts
export const REPORT_REDIRECT_DELAY_MS = 1200; // D10 — "Analysis complete ✓" hold before auto-redirect
```

---

## 4. Tests (Vitest + RTL, mock provider) mapped to acceptance criteria

**Router mock — MUST expose both `push` and `replace` (review B1).** 015's existing
mock is `useRouter: () => ({ push })` (only `push`). 017 adds `router.replace`, so the
mock in every 017 test that renders a redirecting component becomes
`vi.mock("next/navigation", () => ({ useRouter: () => ({ push, replace }) }))` with
`const replace = vi.fn()` alongside `push`. Copying 015's `{ push }`-only mock would
make `router.replace(...)` throw at runtime. (The `failed` Retry path still asserts
`push('/upload')`, so both spies are needed in `processing-redirect.test.tsx`.)

Reuse 015's fake-client injection pattern (`vi.mocked(getApiClient).mockReturnValue(
makeFakeClient({...}))`); extend `_fakeClient.ts` with `getReport`, a `getReportError`
(a thrown `ApiError` with a chosen `status`), and a scripted `getJob` for the
404-disambiguation cases.

**Fake timers vs. the polling hook — the redirect-test harness (review B3).**
`useJobStatus` calls `tick()` **immediately** on mount and `getJob()` resolves via a
**microtask** (promise), not a timer — so the `completed` state, and therefore the
`REPORT_REDIRECT_DELAY_MS` timer that the redirect effect schedules, only exist *after*
the poll promise flushes. A naive `render() → vi.advanceTimersByTime(1200) →
expect(replace)` fires nothing (the timer isn't scheduled yet) and mixing
`vi.useFakeTimers()` with RTL `waitFor`/`findBy` can deadlock (RTL's polling uses
timers). **So `processing-redirect.test.tsx` uses real timers and neutralizes the
delay by mocking the constant to 0:** `vi.mock("@/lib/reportConstants", () => ({
REPORT_REDIRECT_DELAY_MS: 0 }))`, then `await waitFor(() =>
expect(replace).toHaveBeenCalledWith("/jobs/job-1/report"))`. With the delay at 0 the
redirect fires on the next macrotask after the completed state renders, and `waitFor`
(real timers) observes it — no fake-timer/RTL conflict. (The ~1.2 s hold is a UX
constant, not logic; asserting the redirect eventually fires with `replace` is the
behavior under test. If a future test wants to assert the *hold itself*, use
`vi.useFakeTimers({ shouldAdvanceTime: true })` + `await vi.runAllTimersAsync()`, which
drains microtasks then timers — but that's not needed for AC-12/13.)

#### `riskBand.test.ts` (D2 / AC-2)
| Test | Verifies |
|---|---|
| `high_dominates` | `{high:1,medium:5,low:9}` → band `high`, "High risk" |
| `medium_when_no_high` | `{high:0,medium:2,…}` → "Medium risk" |
| `low_when_only_lows` | `{high:0,medium:0,validated_findings:3}` → "Low risk" |
| `none_when_no_findings` | `{validated_findings:0}` → "No issues found" |
| `no_score_string` | header render contains no "/100" (AC-2) |

#### `useReport.test.tsx` (D7 / AC-14 / EC-1/2/3)
| Test | Verifies |
|---|---|
| `loads_report` | `getReport` resolves → phase `loaded`, report set |
| `409_redirects` | `getReport` throws `ApiError(status=409)` → phase `redirecting` (→ `router.replace('/jobs/{id}')`) |
| `404_unknown_job` | `getReport` 404 + `getJob` rejects → phase `not_found` |
| `404_completed_job` | `getReport` 404 + `getJob` returns completed → phase `artifact_unavailable` (INV-2) |
| `404_running_job` | `getReport` 404 + `getJob` returns running → phase `redirecting` |
| `network_error_retry` | `getReport` rejects (no status) → phase `error`; `retry()` re-fetches |

#### `report.test.tsx` (AC-1,3,4,5,6,7,8,9,10,11)
| Test | Verifies |
|---|---|
| `header_and_downloads` | filename, MD+JSON hrefs = `getReportUrl(id,'md'/'json')`, summary chips (AC-1) |
| `ocr_note` | `ocr_used:true` shows OCR note (+confidence); false hides it (AC-3) |
| `findings_render_in_order` | cards in `position` order, titled by `clause_type` or "Clause {position}" (AC-4) |
| `null_severity_badge` | finding `risk_level:null` → "Severity unavailable", no crash (AC-5) |
| `rewrite_three_way` | `rewritten` shows rewrite; `unavailable` shows muted note; `not_eligible` shows no rewrite block (AC-6) |
| `rationale_and_no_business_impact` | `risk_rationale` shown; null → placeholder; no fabricated "Business Impact" text (AC-7) |
| `evidence_list` | evidence rows render; empty evidence → no evidence section (AC-8) |
| `long_clause_collapses` | long `clause_text` collapsed + expand reveals; confidence shown/omitted (AC-9) |
| `ingest_error_panel` | `ingest_error` set + empty findings → "couldn't fully process" + message, not empty list; downloads present (AC-10) |
| `zero_findings_empty_state` | empty findings, no `ingest_error` → "No risky clauses found" + counts (AC-11) |

#### `report-fields.test.ts` (AC-15a — drift lock)
| Test | Verifies |
|---|---|
| `fixture_has_all_009_fields` | the report fixture carries every field name in 009's four models (explicit written list) — a backend add/remove surfaces as a failing assert |

#### `processing-redirect.test.tsx` (AC-12 / AC-13)
| Test | Verifies |
|---|---|
| `completed_auto_redirects` | fake client → terminal `completed`, `final.report_available:true`, `final.error:null`; after advancing `REPORT_REDIRECT_DELAY_MS` (fake timers) `router.replace('/jobs/{id}/report')` fires; the old inline "View report" panel is not the resting state (AC-12) |
| `completed_no_report_stays_inline` | `report_available:false` → no `replace` (INV-1) |
| `completed_with_issue_no_redirect` | `final.error` set → no `replace`; inline "finished with an issue" preserved (AC-13/INV-3) |
| `failed_unchanged` | `failed` → Retry → `push('/upload')` (015 behavior intact) |

#### Boundary (AC-15)
| Test | Verifies |
|---|---|
| `report_uses_getApiClient_only` | grep: no `realProvider`/`mockProvider` import in `components/report` or the modified `ProcessingView` (AC-15) |
| `types_unchanged` | `tsc --noEmit` passes; report components import only from `@/lib/api/types` |
| `no_backend_edits` | `git diff --name-only` touches nothing under `backend/` (AC-15) |

Plus the existing 013/015 suites must stay green. The **015 `processing.test.tsx`
`completed_shows_report_link`** test asserts the old inline behavior — it is
**updated** here (the completed clean path now redirects, so that assertion moves to
`processing-redirect.test.tsx`); the completed-with-issue and failed tests remain
valid. Note this as a deliberate test change (constitution §7: the behavior changed
per D1, so the test changes with it — not a test bent to green code).

---

## 5. Implementation order (TDD — constitution §7)

1. **Types + seam:** add the `ContractReport` mirrors to `types.ts`; add `getReport`
   to `client.ts` + both providers; add the fixtures. Then `report-fields.test.ts`
   (red → green) locks the mirror to 009.
2. **Pure logic:** `riskBand.ts` + `riskBand.test.ts`; `reportFormat.ts`
   (title/format helpers) with small unit tests. No React.
3. **Hook:** `useReport.ts` + `useReport.test.tsx` (409/404 disambiguation via the
   fake client) (red → green).
4. **Report UI:** `RiskBadge` → `SummaryStrip` → `ReportHeader` → `FindingCard` →
   `ReportView` → `app/jobs/[jobId]/report/page.tsx`; `report.test.tsx`.
5. **Auto-redirect:** modify `ProcessingView` (the completed branch + effect);
   `processing-redirect.test.tsx`; update the 015 `processing.test.tsx` completed
   assertion.
6. **Verify:** full `vitest run`, `tsc --noEmit`, `next lint`, `next build` (dev
   server STOPPED — never build while `next dev` runs), confirm no `backend/` diff.
7. **Live smoke (AC-16):** stop tests; start `uvicorn app.api.main:app` on `:8000`
   + Ollama; `NEXT_PUBLIC_API_PROVIDER=real` in `.env.local`; `next dev`; upload a
   real contract; watch 015's processing view finish and **auto-redirect** to
   `/jobs/{id}/report`; confirm the real filename, risk band, and per-clause
   findings render and both Download links open the real `.md`/`.json`.

Each step's tests are written and confirmed failing before its implementation
(constitution §7); a post-impl failure fixes the code, not the test (except the one
deliberate 015 assertion change in step 5, which tracks the D1 behavior change).

---

## 6. Notes / risks

- **The single 015 behavior change is intentional and spec'd (D1).** 015 Open-Q1
  explicitly deferred the auto-redirect to "a `/jobs/[jobId]/report` route 017 will
  own." This plan realizes exactly that; the completed-with-issue and failed paths
  are preserved, so 015's recovery UX is intact.
- **Redirect timer lives in `ProcessingView`, not `useJobStatus`.** The hook stops
  polling on the terminal status (`useJobStatus` returns before rescheduling the next
  `setTimeout`); the `REPORT_REDIRECT_DELAY_MS` timer runs in the component effect
  after the last poll returns `completed`, so it doesn't interact with poll
  *teardown*. It **does** interact with poll *resolution ordering* (the completed
  state arrives via a promise before the timer is scheduled) — see the §4 harness
  note (review B3): tests mock the delay to 0 and `waitFor` the `replace` rather than
  advancing fake timers blindly.
- **`replace`, not `push`, for the redirect (D1/EC-9).** The auto-redirect uses
  `router.replace` so Back doesn't land on the finished processing screen (which would
  re-redirect). `processing-redirect.test.tsx` asserts both that `replace` is called
  with the report URL **and** that `push` was not used for the redirect (locks EC-9).
- **`completed_no_report_stays_inline` is a synthetic guard (review B2).** A clean
  `completed` job always has `report_available === true` (INV-1), so a completed job
  with `report_available: false` is not a state the backend emits; the test builds it
  via `completedFinal({ report_available: false })` purely to prove the redirect gate
  is defensive. Noted so it isn't mistaken for a real backend path.
- **404 is genuinely ambiguous in the backend (INV-2).** The extra `getJob`
  round-trip on 404 (D7) is the honest disambiguation; it only fires on the rare
  404, never on the happy path. Without it, a completed-but-file-missing job would
  be mislabeled "not found."
- **`ingest_error` is a `dict`, not a string (009 `Optional[dict]`).** The
  ingest-error panel reads `report.ingest_error?.message ?? JSON.stringify(report.
  ingest_error)` — never assumes a bare string.
- **`getReport` is a plain `fetch`, not SSE (D8).** The Next dev proxy buffering that
  forced 015's SSE→polling switch (015 D7) does **not** affect a one-shot JSON GET,
  so the report loads cleanly through the same proxy. Keep `NEXT_PUBLIC_API_BASE_URL`
  empty so the call is same-origin `/api/*` through the proxy (011 CORS allowlists
  `:5173`, not `:3000` — a direct base URL would be rejected; same lesson as 015).
- **`next build` vs `next dev`.** Learned in 013/015: never run a production build
  while the dev server is live (it corrupts `.next`). Step 6 builds with dev stopped.
- **No document-level score, business-impact field, PDF/JPG export, or delivery
  re-trigger** is added — each is a backend feature (spec §5), explicitly out of
  scope; the page renders only what 009 actually emits.

---

*Per constitution §1/§11, a `feature/017-report-view` branch opens only after this
plan.md and its spec.md are approved and `tasks.md` exists. No `tasks.md` or
implementation was written in this pass — plan only.*
