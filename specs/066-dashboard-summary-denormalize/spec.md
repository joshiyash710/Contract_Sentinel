# Feature 066 — Spec: denormalize the risk summary onto the job row (kill the dashboard N+1)

Status: DRAFT (pre spec-reviewer gate)
Branch: `feature/066-dashboard-summary-denormalize` (constitution §11).

> Latency fix that attacks the real cause (not the DB engine). `/api/dashboard` and `/api/jobs` build their
> response by reading **one report BLOB per completed job** (`aggregate.build_dashboard_metrics` /
> `build_job_list` call `read(row.report_path)` in a loop; each `read_report_data` is a `blob_store.exists`
> **plus** a `blob_store.read` — two round-trips). On the Turso deploy (Oregon backend ↔ Mumbai primary) that
> is O(N completed reports) × 2 cross-region calls → multi-second loads + 500s. This feature **persists a
> compact risk summary on the job row at completion**, so both endpoints read everything they need from the
> single `jobs` query they already run — **zero per-report BLOB fetches**. Store/registry/aggregate +
> one Alembic migration; **no LangGraph node/edge/`ContractState` change**.

## 1. Problem statement

Grounded in the code:
- `app/api/aggregate.py::build_dashboard_metrics` (line ~159): `for r in completed_rows: rd =
  read(r.report_path)` — one report read per completed job. It uses the folded risk counts (high/medium/low,
  validated, total_clauses, `analysis_degraded`) and the per-finding list to build the clause-type heatmap +
  top-risky-types.
- `app/api/aggregate.py::build_job_list`: same `read(row.report_path)` per completed row — to set
  `report_available`, `high/medium/low`, `risk_band`, `analysis_degraded`.
- `read_report_data` (aggregate.py): `blob_store.exists(json_key)` **then** `blob_store.read(json_key)` — two
  blob ops per report. On Turso each is a network round-trip.
- The `jobs` table (`app/runner/store.py`, `JobRow`) already stores job metadata but **no risk summary**; the
  stores run a single `SELECT * FROM jobs WHERE user_id=? ORDER BY submitted_at DESC …`.

So a user with N completed contracts pays ~2N cross-region round-trips **on every dashboard/jobs load**. The
database engine is not the problem (Postgres/embedded-replica would still make N calls); the **N+1 read
pattern** is. (This is why features 064/065's embedded replica — which only makes each round-trip faster/local
— was the wrong tool and proved fragile; see §5.)

Fix: when a job completes, compute a **compact risk summary** from its report and store it on the job row. The
dashboard and jobs-list then read from the row (already loaded by the one `SELECT`) and **never** fetch a
report BLOB. Legacy rows (completed before this feature, no stored summary) **fall back** to today's
`read(report_path)` path — graceful, no backfill required.

### Position relative to the constitution
- **No LangGraph node/edge/`ContractState` change (§2).** The change is in the **runner store DB** (the `jobs`
  table + its `JobRow`/registry persistence) and the **aggregation/API read path**. The graph state
  (`specs/001`) is untouched — this is report-derived metadata on the *job record*, not pipeline state.
- **Alembic migration is normal here.** The store DB is Alembic-managed (feature 051); adding columns to
  `jobs` mirrors 0009 (`report_blobs`) / 0010 (`upload_blobs`). Not a §2 fixed-architecture issue.
- **§019 isolation preserved.** The summary is per-job (owned by the job's `user_id`); reads stay owner-scoped
  exactly as today. No cross-account exposure.
- **No new dependency; no frontend change.** The API response shapes (`DashboardMetrics`, `JobList` items) are
  unchanged — only *how* they're populated changes. The frontend sees identical JSON.
- **Reversible / graceful.** Legacy rows without the summary fall back to the current BLOB-read path, so
  correctness holds during/after rollout with or without a backfill.

## 2. Inputs and outputs

### Schema — `jobs` table + `JobRow` (store.py) + Alembic migration
- Add nullable columns to `jobs` (migration 0011): `risk_high INTEGER`, `risk_medium INTEGER`,
  `risk_low INTEGER`, `validated_findings INTEGER`, `total_clauses INTEGER`, `analysis_degraded INTEGER`
  (0/1), and `risk_by_type TEXT` (a compact JSON of per-clause-type severity counts, e.g.
  `{"liability":{"high":2,"medium":1,"low":0}, …}`). All **nullable** → legacy rows are `NULL` ⇒ "no stored
  summary" ⇒ fall back.
- `JobRow` gains the matching optional fields; `JobStore` `INSERT … ON CONFLICT` upsert persists them (store
  the summary when present, leave NULL otherwise).

### Write path — persist the summary at completion
- When a job reaches a **completed** terminal state **with a report**, compute a compact
  `RiskSummary` (high/medium/low, validated_findings, total_clauses, analysis_degraded, risk_by_type map) from
  the report data and stamp it on the job record so the next `_persist()` writes it. The summary is computed
  **once per analysis** (at completion) instead of on every dashboard load. (Exact write point — registry
  `mark_terminal` vs the worker over `final_state` — is a plan detail; it must not read N BLOBs and must not
  make the runner import graph-node modules, per the 061 runner-isolation guard.)
- A pure helper builds `RiskSummary` from the report's `summary` + `findings` (the same fields
  `read_report_data` already extracts), so the stored summary and the live-read path cannot diverge.

### Read path — aggregate from the row, fall back for legacy
- `build_dashboard_metrics` / `build_job_list`: when a completed row **has a stored summary**
  (`risk_high` is not NULL), build the metrics/list item **from the row's columns** (`risk_high/medium/low`,
  `validated_findings`, `total_clauses`, `analysis_degraded`, and the decoded `risk_by_type` for the heatmap +
  top-risky). When the row has **no** stored summary (legacy), fall back to `read(report_path)` exactly as
  today. No per-report BLOB fetch in the fast path.
- The response models (`DashboardMetrics`, `JobList`) are unchanged — identical JSON out.

### Resolved decisions (inline)
- **D1 — Denormalize onto the job row** (not a cache): the real cure for the N+1; one write per analysis, O(1)
  reads thereafter.
- **D2 — Store a compact per-clause-type map**, not full findings: the dashboard heatmap/top-risky need
  per-type severity counts, not the raw findings — a small bounded JSON (≤ ~dozen clause types × 3 severities)
  keeps the row lean and avoids reading findings at dashboard time.
- **D3 — Legacy rows fall back to the BLOB read** (no mandatory backfill): correctness preserved immediately;
  the deploy gets faster as users run new analyses. (An optional one-off backfill is out of scope, §5.)
- **D4 — Summaries derived from the report, via one shared helper** so the stored and live paths agree (D1
  honesty: the row summary equals what reading the report would yield).

## 3. Acceptance criteria

Backend, offline (pytest). The stores run against local SQLite in tests; the aggregation is pure.

- **AC-1 (migration adds the columns):** `alembic upgrade head` creates the new nullable `jobs` columns
  (`risk_high`/`risk_medium`/`risk_low`/`validated_findings`/`total_clauses`/`analysis_degraded`/`risk_by_type`);
  `downgrade` drops them; existing rows survive upgrade with the new columns NULL.
- **AC-2 (JobRow + upsert round-trip):** a `JobRow` carrying a risk summary is persisted and read back by
  `JobStore` with the summary intact (ints + the decoded `risk_by_type` map); a `JobRow` without a summary
  stores NULLs and reads back as "no summary".
- **AC-3 (summary written at completion):** when a job completes with a report, the job record is stamped with
  the risk summary derived from that report (high/medium/low/validated/total/degraded + per-type map match the
  report's `summary`/`findings`); a non-completed or report-less terminal (e.g. ingest error) stores no
  summary (NULLs).
- **AC-4 (dashboard reads from the row — no BLOB fetch):** `build_dashboard_metrics` over rows that all carry
  stored summaries produces the **same** `DashboardMetrics` as the current read-the-BLOB path, while calling
  the injected report-reader **zero** times (assert the reader is not invoked for summarized rows).
- **AC-5 (job list reads from the row — no BLOB fetch):** `build_job_list` over summarized rows yields the same
  `JobList` items (`report_available`, high/medium/low, `risk_band`, `analysis_degraded`) as the BLOB path,
  with the reader called **zero** times.
- **AC-6 (legacy fallback):** a completed row with **no** stored summary still produces correct
  dashboard/list output by falling back to `read(report_path)` (today's behavior) — mixed batches (some
  summarized, some legacy) are correct, and the reader is called only for the legacy rows.
- **AC-7 (parity — stored == read):** for a given report, the shared helper's `RiskSummary` equals what
  `read_report_data` yields for the dashboard-relevant fields (no divergence between the fast and fallback
  paths).
- **AC-8 (no architecture/contract change):** `git diff main` touches only the store/registry (+ its models),
  `app/api/aggregate.py`, the new migration + helper, tests, and the 066 specs. No node/edge/`ContractState`/
  `specs/001` change; no new dependency; no frontend change; response JSON shapes unchanged. Full backend suite
  green.
- **AC-9 (live effect — operational):** on the Turso deploy, `/api/dashboard` and `/api/jobs` for a user with
  many completed reports load in well under a second (one `SELECT`, no per-report round-trips) vs multi-second
  before. Verified on the deploy.

## 4. Edge cases
- **EC-1 — Legacy completed jobs (pre-066):** `risk_*` NULL → fall back to `read(report_path)` (AC-6). Correct,
  just not yet fast for those rows.
- **EC-2 — Degraded analysis:** `analysis_degraded=True` is stored and surfaced identically (the dashboard/list
  already de-emphasize degraded counts); the stored flag mirrors the report.
- **EC-3 — Report BLOB unreadable at completion (write path):** if the summary can't be computed at completion
  (missing/malformed report), store NO summary (NULLs) → the read path falls back to `read()` (which will also
  return None/skip, exactly as today). Never fail the run over summary computation (best-effort, like 061).
- **EC-4 — Clause types / severities:** `risk_by_type` keys are the same clause-type labels the live heatmap
  uses (incl. the uncategorized bucket); a report with no findings → empty map + zero counts.
- **EC-5 — Non-completed rows:** queued/running/errored rows have no report → no summary; the dashboard already
  only folds completed rows.
- **EC-6 — Migration idempotency / existing data:** adding nullable columns is non-destructive; `alembic
  upgrade head` on the live Turso DB (entrypoint) adds them with existing rows NULL (→ fallback). Downgrade
  drops them.
- **EC-7 — `risk_by_type` JSON malformed on read (shouldn't happen):** decode defensively → treat as "no
  stored summary" and fall back (EC-1), logged, never 500.

## 5. Out of scope
- **A one-off backfill of legacy rows** — not required (D3 fallback); could be a later chore. New analyses are
  fast immediately; old rows stay correct via fallback.
- **Server-side response caching** (the earlier "3b") — a separate, optional optimization; the denormalization
  (this feature) is the real N+1 cure and is sufficient. Not built here.
- **The Turso embedded replica (features 064/065)** — abandoned: it only makes each round-trip faster/local and
  proved incompatible with FastAPI's threadpool model (a native libSQL panic across worker threads). Its flag
  stays **off**; this feature supersedes the latency goal correctly. (064/065 code remains, default-off,
  marked experimental.)
- **Any LangGraph node/edge/`ContractState` change, or a frontend change.**
- **Co-location / Postgres / Turso paid tier** — unneeded once the N+1 is gone.

## 6. Evaluation (metrics to log)
No accuracy/retrieval change (the numbers are identical — just sourced from the row). Operability: the
dashboard/jobs endpoints should issue **one** store query and **zero** report-BLOB reads for summarized rows
(AC-4/AC-5); optionally debug-log the count of rows served from the stored summary vs the legacy fallback, so
the rollout's speed-up is observable. The live effect (AC-9) is the real measure. No eval-harness change.

## 7. Open questions
Resolved inline (2026-10-15); none architecturally significant:
- **OQ-1 — Denormalize vs cache? → RESOLVED: denormalize onto the job row** (D1) — removes the N round-trips
  entirely rather than hiding them; one write per analysis.
- **OQ-2 — Store full findings or a compact per-type map? → RESOLVED: compact per-clause-type severity map**
  (D2) — all the dashboard needs, keeps the row small.
- **OQ-3 — Backfill legacy rows? → RESOLVED: no — fall back to the BLOB read for rows without a summary** (D3);
  an optional backfill is out of scope.
- **OQ-4 — Write point (registry vs worker)? → deferred to the plan** (a localized implementation choice, not
  architecturally significant): compute the compact summary once at completion from the report data, without
  N BLOB reads and without the runner importing graph-node modules (061 guard).

No open questions remain.
