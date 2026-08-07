# Feature 038 — Honest LLM-Failure Surfacing

## Problem statement

When the local generative LLM (Qwen3 via Ollama) is unavailable, out of memory,
timing out, or returning unparseable output, `RiskScoreAgent` (Node 5 in the
fixed architecture, constitution §2) does **not** crash. By design it applies a
**fail-safe default** per clause and, after
`RISK_SCORE_LLM_CIRCUIT_BREAKER_THRESHOLD` consecutive failures, opens a circuit
breaker that fail-safes every remaining validated finding for the run
(`app/graph/nodes/risk_score_agent.py`). Each fail-safe clause is assigned the
default severity (currently **High**) with an `[auto]` rationale, and the run
sets pipeline `error_count` to 1 when the breaker trips.

This is the correct *pipeline* behavior — the run completes and a report is
produced. The problem is **honesty of presentation**: the fail-safe signal never
leaves the internals. Today it is only written to logs (the `is_failsafe` field
in `risk_score_agent`'s per-clause log line). It is **not** persisted into the
clause record, **not** carried into the `ContractReport` boundary model
(`app/models/report.py`), and therefore **not** shown in the Markdown report,
the PDF (`app/delivery/report_pdf.py`), the HTML email
(`app/delivery/email_html.py`), or the frontend report/dashboard.

The consequence is a **trust bug**: a fully degraded run — every clause defaulted
to High because the model was down — renders as a normal-looking report with a
row of confident-looking High findings. A user cannot tell a genuine legal
judgment from an auto-defaulted placeholder. For a product positioned as a
trustworthy legal-AI assistant, silently presenting machine-fabricated fail-safe
severities as analysis is the single most damaging integrity gap.

This feature makes the existing internal fail-safe/circuit-breaker signal
**visible and unmistakable** to the user, end-to-end, without changing the fixed
7-node architecture. It adds **no LangGraph node and no edge** (constitution §2).
It is a surfacing/plumbing feature: persist the signal the pipeline already
computes, carry it through the report boundary model, and render an honest
"degraded analysis" notice in every output channel. It is fully reversible via a
config flag (constitution §3).

Position in the pipeline: the signal originates at **Node 5 (RiskScoreAgent)**;
it is assembled for presentation at **Node 7 (ReportAgent)** via the pure
`assemble_report` transform; and it is rendered by the post-terminal delivery
layer and the frontend. No earlier node's contract changes.

## Inputs and outputs

### Inputs (read)

From `ContractState` (defined in `001-contract-state-schema.md`):

- `clauses: Dict[str, Dict[str, Any]]` — per-clause records. Node 5 already writes
  `risk_level` and `risk_rationale` for every scored clause. This feature reads a
  **new, documented per-clause sub-field** that Node 5 will additionally write:
  - `is_failsafe: Optional[bool]` — `True` when this clause's `risk_level` was
    assigned by the fail-safe path (LLM failure / unparseable output / circuit
    open / empty-or-oversize clause text) rather than a genuine model judgment;
    `False`/absent when the severity is a real judgment. **This is a change to
    `001-contract-state-schema.md` and, per constitution §10 (Spec-First Change
    Rule), that schema file MUST be amended first, with written rationale, before
    any code writes the field.** This is a **resolved design decision** (see
    Design decisions below): the fragile alternative — deriving failsafe-ness from
    the `[auto]` rationale substring — is explicitly rejected, because a genuine
    rationale could contain that substring and the marker is a presentation
    detail, not a reliable provenance signal. The clause record already documents
    `risk_level`/`risk_rationale` sub-fields, so this is a purely additive
    documented sub-field, not a breaking change to any existing field.
- `error_count: int` — already incremented to 1 by Node 5 when the circuit
  breaker trips (existing behavior; no change).

Node 5 additionally must be able to distinguish, for aggregation, how many
clauses were fail-safed and whether the circuit breaker opened. The per-clause
`is_failsafe` field plus `error_count` are sufficient; no other new state field
is required. (The existing `_failsafe()` rationale `[auto]` marker is retained
as-is for backward compatibility but is no longer the source of truth.)

### Outputs (write)

1. **Node 5 (`risk_score_agent`)** — in addition to today's `risk_level` /
   `risk_rationale`, writes `is_failsafe: bool` into each clause update it
   produces (`True` for every `_failsafe(...)` update including empty/oversize
   text and circuit-open updates; `False` for genuinely-scored clauses). This is
   a partial-update dict per constitution §5; no other clause sub-field changes.

2. **`ContractReport` boundary model (`app/models/report.py`)** — Pydantic model
   built FROM state at Node 7, never stored in state (constitution §4). Gains:
   - `ReportFinding.is_failsafe: bool = False` — per-finding flag, copied from the
     clause record by `assemble_report`. Lets each rendered finding be marked
     "auto-assigned severity".
   - `ReportSummary.failsafe_count: int = 0` — number of validated findings whose
     severity was fail-safe (derived by `assemble_report`).
   - `ContractReport.analysis_degraded: bool = False` — the single top-level
     honesty flag the renderers key off. `True` when the run's analysis is
     materially unreliable (see Acceptance Criteria for the exact rule).
   These are additions to a boundary model, **not** to `ContractState`, so they
   do **not** require a `001` amendment (only the per-clause `is_failsafe` state
   field does).

3. **Markdown renderer (`markdown_renderer.py`)**, **PDF
   (`report_pdf.py`)**, **HTML email (`email_html.py`)** — when
   `analysis_degraded` is `True`, each renders a prominent, plain-language
   **degraded-analysis banner** at the top of the report/email body, e.g.
   *"⚠ Degraded analysis — the AI model was unavailable for part or all of this
   run. Severities marked "auto" were assigned by a fail-safe default, not by
   model judgment. Do not rely on them; re-run this analysis when the model is
   available."* Each fail-safe finding is additionally marked inline (e.g. an
   "(auto-assigned)" tag next to its severity).

4. **Frontend report view + dashboard/history** (`frontend/src/...`) — when the
   report JSON has `analysis_degraded: true`, the report page shows a degraded
   banner and per-finding "auto" tags; the contracts/history list and dashboard
   mark such a report with a "Degraded" badge instead of presenting its risk
   counts as trustworthy. No file under `frontend/src/` is written until this
   spec **and** plan.md are approved (constitution §1).

5. **Config (`app/config.py`)** — one named, reversible master flag
   `HONEST_FAILURE_SURFACING_ENABLED: bool = True` (constitution §3). When
   `False`, behavior is **byte-identical** to today: Node 5 does not write
   `is_failsafe`, `assemble_report` sets `analysis_degraded=False` and
   `failsafe_count=0`, and no banner/tag renders anywhere. A second named
   threshold constant governs the degraded rule (see AC-3 / D2; its numeric
   default is the sole remaining Open Question).

### Data flow

`risk_score_agent` (writes `is_failsafe` per clause, `error_count` on trip) →
[state] → `report_agent` / `assemble_report` (derives
`ReportFinding.is_failsafe`, `ReportSummary.failsafe_count`,
`ContractReport.analysis_degraded`) → JSON + Markdown + PDF + HTML email + API →
frontend.

## Acceptance criteria

Each criterion is written to be directly testable.

- **AC-1** — Given a clause whose severity is assigned by any fail-safe path in
  `risk_score_agent` (LLM returned `None`, unparseable output, circuit open, or
  empty/oversize text), the clause update returned by Node 5 contains
  `is_failsafe: True`.
- **AC-2** — Given a clause scored by a genuine model judgment, the clause update
  contains `is_failsafe: False` (never absent when the flag feature is on).
- **AC-3** — `assemble_report` sets `ContractReport.analysis_degraded = True`
  **only when the report actually contains at least one fail-safe severity**
  (`failsafe_count >= 1`) **and** in addition **either** (a) the run's
  `error_count >= 1` (a circuit breaker tripped this run) **or** (b) the fraction
  of validated findings that are fail-safe is `>=` the configurable threshold
  `ANALYSIS_DEGRADED_FAILSAFE_FRACTION`; otherwise `analysis_degraded = False`.
  The `failsafe_count >= 1` precondition is essential: `error_count` is a **shared**
  accumulating counter incremented by *any* node's circuit breaker (ingest /
  self_rag / redline / risk_score), so without it an unrelated node's failure
  would falsely flag a fully-genuine risk analysis as degraded (the banner claims
  severities are auto-assigned — false if none are). Because a risk-score circuit
  trip always produces fail-safe findings, gating on `failsafe_count` loses none
  of the intended systemic-outage detection. This logical rule is **fixed** (the
  acceptance test is deterministic); only the **numeric default** of
  `ANALYSIS_DEGRADED_FAILSAFE_FRACTION` (proposed `0.5`) remains a §3-tunable
  constant. When `validated_findings == 0` the fraction is defined as `0` (no
  division by zero) and `failsafe_count == 0`, so the run is not degraded.
- **AC-4** — `ReportSummary.failsafe_count` equals the number of validated
  findings with `is_failsafe == True`, and `<= validated_findings`.
- **AC-5** — Each `ReportFinding` carries `is_failsafe` copied faithfully from its
  clause record (`True`/`False`), independent of `analysis_degraded`.
- **AC-6** — When `analysis_degraded == True`, the Markdown report body contains a
  degraded-analysis banner (distinct, matchable marker text) positioned before
  the findings section; when `False`, the banner is absent.
- **AC-7** — When `analysis_degraded == True`, the generated PDF and the HTML
  email body each contain the degraded-analysis banner; when `False`, neither
  does.
- **AC-8** — Each rendered finding with `is_failsafe == True` shows an inline
  "auto-assigned" marker next to its severity in Markdown, PDF, HTML email, and
  the frontend; findings with `is_failsafe == False` show no such marker.
- **AC-9** — The frontend report view renders the degraded banner and per-finding
  auto tags iff `analysis_degraded`/`is_failsafe` are set in the report JSON; the
  dashboard/history entry for a degraded report shows a "Degraded" badge and does
  not present its High/Medium/Low counts as trustworthy analysis.
- **AC-10 (reversibility)** — With `HONEST_FAILURE_SURFACING_ENABLED = False`,
  the full pipeline output (state, report JSON, Markdown bytes, PDF, email HTML)
  is byte-identical to pre-feature behavior: no `is_failsafe` key is written to
  state, `analysis_degraded` is always `False`, `failsafe_count` is `0`, and no
  banner or tag appears in any channel.
- **AC-11 (no architecture change)** — No LangGraph node or edge is added,
  removed, or reordered; the graph builder and the 7-node/2-edge topology are
  unchanged (constitution §2). No new node timing key appears.
- **AC-12 (honesty, not suppression)** — A degraded report is still generated,
  still persisted, and still delivered (email/Drive) — it is flagged, never
  silently withheld and never silently "cleaned up" to look genuine. (Suppressing
  delivery would be its own trust failure; see Out of Scope.)
- **AC-13 (schema consistency)** — `001-contract-state-schema.md` is amended
  (documented `is_failsafe` sub-field on the clause record) **before** any code
  writes the field, with a rationale note per constitution §10; the amended
  sub-field name matches exactly what Node 5 writes and `assemble_report` reads.
  (This is a committed decision, not conditional — see Design decisions.)

## Edge cases

- **All clauses fail-safe (full outage).** Circuit breaker opens; every validated
  finding is `is_failsafe: True`; `analysis_degraded: True`; banner shown; every
  finding tagged auto. This is the headline scenario the feature exists for.
- **Zero validated findings, but `error_count >= 1`.** No findings, so
  `failsafe_count = 0`; per AC-3's `failsafe_count >= 1` precondition,
  `analysis_degraded = False` — there are no auto-defaulted severities in the
  report to warn about, and the `error_count` may be from an unrelated node. (A
  risk-score circuit trip cannot reach this state: tripping requires scoring
  VALIDATED clauses, each of which becomes a fail-safe finding, so
  `failsafe_count >= 1` whenever the risk-score breaker tripped.) The
  `failsafe_count / validated_findings` division must not divide by zero (guard:
  fraction is 0 when `validated_findings == 0`).
- **Single isolated fail-safe clause (empty/oversize text), model otherwise
  healthy.** Circuit breaker did **not** trip (`error_count == 0`); one finding is
  `is_failsafe: True`. Whether this alone flips `analysis_degraded` depends on the
  fraction threshold (fixed rule D2/AC-3; the numeric default is the sole Open
  Question). Intended default: one isolated fail-safe
  in a large healthy run should **not** scream "degraded report," but the single
  finding is still tagged auto (AC-8). The banner should not cry wolf.
- **`ingest_error` set (Edge Case 1 of Report spec 009).** A minimal "could not
  process" report is produced with empty findings. `analysis_degraded` is
  independent of ingest failure and should be `False` here (there was no risk-score
  degradation; the failure is already surfaced as `ingest_error`). No banner from
  this feature (the ingest-error message is the existing, separate surface).
- **Redline failure vs risk-score failure.** A clause whose `suggested_rewrite`
  is `None` because Redline failed is already surfaced today as
  `rewrite_state == "unavailable"`. This feature does **not** re-flag that as
  `is_failsafe`; `is_failsafe` is strictly about **severity** provenance from
  Node 5. Redline honesty is out of scope (see Out of Scope).
- **Feature flag off mid-existing-data.** Old persisted reports (JSON without the
  new fields) must still deserialize: the new `ContractReport` fields have
  defaults (`analysis_degraded=False`, `failsafe_count=0`, `is_failsafe=False`)
  so historical report JSONs render exactly as before (no banner). Frontend must
  treat missing `analysis_degraded` as `false`.
- **Checkpoint round-trip.** `is_failsafe` is a plain `bool` in the clause dict;
  it survives LangGraph SQLite checkpoint serialization like the existing
  `risk_level` field. No enum/serialization concern.
- **Retry exhaustion / timeout at Node 5.** These already funnel into the
  fail-safe path (`_run_scoring` returns `None` on timeout/exception per
  `risk_score_agent`), so they are covered by AC-1 without new timeout logic. The
  circuit-breaker threshold and per-call timeout are existing configurable
  constants (constitution §3, §9) — unchanged by this feature.

## Out of scope

- **Changing the fail-safe default severity or the circuit-breaker mechanics.**
  Node 5's fail-safe logic (default level, threshold, timeout) is owned by
  `specs/007-risk-score`. This feature only *surfaces* its existing signal; it
  does not retune it. **Resolved for 038: the fail-safe default severity stays
  `High` (`RISK_SCORE_DEFAULT_LEVEL_ON_FAILURE`) unchanged** — once each fail-safe
  finding is clearly tagged "auto-assigned," honest labeling (not a quieter
  default) is what closes the trust gap. Whether the default should become an
  explicit "Unknown/Unscored" is a separate `specs/007` follow-up, not this
  feature.
- **Honest surfacing of non-severity LLM failures** — Self-RAG mass-discard when
  the validator LLM is down (`specs/006`), Redline rewrite failures
  (`rewrite_state == "unavailable"`, already surfaced by `specs/009`), and CRAG
  retrieval/embedding failures (`specs/005`). v1 scopes strictly to the
  risk-score severity fail-safe + circuit breaker, which is the concrete all-High
  trust bug. A future feature may generalize a "run health" surface (deferred per
  decision D4).
- **Suppressing or auto-retrying degraded runs.** This feature does not block
  delivery, auto-re-run the pipeline, or queue a retry when degraded. It flags;
  it does not remediate. Auto-retry/queueing would be a separate feature.
- **A run-health dashboard, audit log, or admin surface.** Any audit-log UI is
  PERMANENTLY CUT (constitution §2). The degraded badge on the existing
  contracts/dashboard is a per-report honesty marker, not an ops dashboard.
- **Detecting model unavailability proactively** (health-checking Ollama before a
  run). Out of scope; the signal is derived from the run's own fail-safe outcome.
- **Encryption / storage concerns.** Unrelated; owned by the 032/036 security
  amendments.

## Evaluation

This feature is about failure-mode honesty, so the following should be logged
(structured logs, consistent with Node 5's existing aggregate log line) for later
analysis — no new user-facing metric UI (that would collide with the CUT audit
UI):

- **Fail-safe rate per run** — `failsafe_count / validated_findings` (already
  derivable; log it explicitly at report assembly).
- **Circuit-open rate** — fraction of runs where the risk-score breaker tripped
  (`error_count` attributable to Node 5). Signals how often the local model is
  effectively unavailable, informing the constitution §9 latency/capacity notes.
- **Degraded-report rate** — fraction of runs where `analysis_degraded == True`.
- **Degraded-trigger reason** — for each degraded run, whether it was triggered by
  AC-3(a) (circuit tripped) or AC-3(b) (fraction threshold), to tune the
  threshold against real runs (constitution §3 — thresholds are tuned after
  implementation).

These are diagnostic logs, not blocking tests; they mirror the measure-first
approach used by features 026/028/029. No confidence-score or retrieval-path
metrics are added here (this feature does not touch CRAG/Self-RAG).

## Design decisions (resolved inline)

These were previously open; they are architecturally significant and the spec
body (Inputs/Outputs/ACs/Edge cases) depends on them, so they are resolved here
with rationale rather than left to the plan to guess (constitution §10; the
project's inline-decision preference):

- **D1 — Persist `is_failsafe` in state (amend 001), do not derive from the
  `[auto]` marker.** An explicit `is_failsafe: Optional[bool]` documented
  sub-field is added to the clause record; `001-contract-state-schema.md` is
  amended first (§10, AC-13). Rationale: a rationale-substring derivation is
  fragile and conflates presentation with provenance. Drives Inputs, Outputs,
  AC-1, AC-2, AC-13, and the checkpoint edge case.
- **D2 — `analysis_degraded` rule = "`failsafe_count ≥ 1` AND (circuit trip OR
  failsafe-fraction ≥ threshold)."** Committed as the fixed logical rule (AC-3);
  only the numeric `ANALYSIS_DEGRADED_FAILSAFE_FRACTION` default (proposed `0.5`)
  is a §3-tunable constant. Rationale: the `failsafe_count ≥ 1` gate ensures a
  report is only flagged when it truly contains auto-defaulted severities (the
  shared `error_count` alone would false-positive on an unrelated node's circuit
  trip); the circuit-trip arm then catches systemic outages even when genuine
  findings dilute the fraction; the fraction arm catches partial outages; the
  threshold prevents a single isolated empty-text clause from crying wolf.
- **D3 — Fail-safe default severity stays `High` for 038.** See Out of scope;
  honest tagging, not a quieter default, closes the trust gap. Any default-value
  change is a `specs/007` follow-up.
- **D4 — Scope is risk-score severity fail-safe + circuit breaker only.**
  Self-RAG-down / CRAG-down honesty and a generalized "run health" surface are
  deferred (Out of scope); Redline "unavailable" is already surfaced today.
- **D5 — Frontend surfaces = report page (banner + per-finding auto tags) AND a
  "Degraded" badge on the contracts/history list + dashboard cards** (AC-9).
- **D6 — `HONEST_FAILURE_SURFACING_ENABLED` default `True`** (ship on; honesty is
  the point), fully reversible to byte-identical prior behavior when `False`
  (AC-10).

## Open questions

1. **Numeric value of `ANALYSIS_DEGRADED_FAILSAFE_FRACTION`.** Proposed default
   `0.5`. This is a constitution §3 *tunable* threshold — it can ship at `0.5`
   and be re-tuned against real degraded runs (Evaluation section) without any
   code-structure change. Flagged only so you can veto the starting value; it is
   **not** a blocker for plan.md (the logical rule in AC-3/D2 is fixed regardless).
   No other questions remain open; all architecturally-significant decisions are
   resolved in Design decisions above.
