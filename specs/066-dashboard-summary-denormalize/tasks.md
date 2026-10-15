# Feature 066 — Denormalize risk summary onto the job row — Implementation Tasks

Reference documents:
- Spec: `specs/066-dashboard-summary-denormalize/spec.md`
- Plan: `specs/066-dashboard-summary-denormalize/plan.md`
- Constitution: `specs/000-constitution.md` (**§2/§10** no node/edge/state; **§7** TDD / never weaken a test;
  **§11** branch workflow; **§019** per-user isolation)

Backend paths relative to `backend/`.

**Workflow reminders:**
- **Store DB + aggregation only.** No LangGraph node/edge/`ContractState`/`specs/001` change; response models
  (`DashboardMetrics`/`JobList*`) + frontend unchanged (identical JSON). No new dependency.
- **Parity is structural (locked):** ONE shared `summarize_report(report_dict) -> RiskSummary` feeds BOTH the
  write path and the read-path legacy fallback (both call `load_report_summary`), so the stored summary and a
  live report read cannot diverge (D4/AC-7).
- **Serialization path (locked):** `registry._to_row()` maps the summary via
  `risk_summary.to_row_fields(summary)` (not ad-hoc) — one path.
- **Scope allow-list (AC-8)** = the migration, `app/runner/risk_summary.py` (NEW), `store.py`, `registry.py`,
  `worker.py`, `app/api/aggregate.py` (+ the routes call-site update), the tests, and the 066 specs. Nothing
  else (NOT the response models, NOT the frontend, NOT blob_store/renderers).
- **TDD (§7):** write tests first, confirm FAIL, implement to green. Best-effort write (a summary exception
  must NOT alter the job's terminal status). Never log secrets. Never weaken a test.

---

## Task 0: Branch
- [ ] From up-to-date `main` (`git checkout main && git pull`), create
  `feature/066-dashboard-summary-denormalize` (`git-start`). Commit the APPROVED spec/plan/tasks.

**Verify:** `git branch --show-current` → `feature/066-dashboard-summary-denormalize`.

---

## Task 1: Write the failing tests first  [AC-1..AC-7]
Create/extend tests; confirm they FAIL. Stores run against local SQLite; aggregation is pure.
- [ ] **[NEW] `tests/integration/test_migration_0011.py`** (AC-1): `upgrade` adds the 7 nullable `jobs` columns
  (`risk_high/risk_medium/risk_low/validated_findings/total_clauses/analysis_degraded/risk_by_type`);
  pre-existing rows survive with the new cols NULL; `downgrade` drops them. (Mirror an existing migration test.)
- [ ] **[EXTEND] store test** (AC-2): a `JobRow` WITH a summary upserts + reads back intact (ints + decoded
  `risk_by_type` dict + bool `analysis_degraded`); a `JobRow` WITHOUT a summary stores NULLs and reads back as
  None (`from_row` → None).
- [ ] **[EXTEND] registry/worker test** (AC-3 — TWO cases + best-effort EC-3): (a) completed + report →
  `mark_terminal` stamps the summary from the report; (b) failed / report-less terminal → no summary (NULLs);
  (c) `load_report_summary` raising → the job is still `completed`, summary NULL (status unaltered).
- [ ] **[EXTEND] aggregate test** (AC-4/AC-5): `build_dashboard_metrics` and `build_job_list` over
  all-summarized rows produce the SAME output as the BLOB path, with the injected summary-reader asserted
  called **0** times.
- [ ] **[EXTEND] aggregate test** (AC-6): a mixed batch (one summarized row + one legacy NULL-summary row) →
  correct output; the reader is called **only** for the legacy row.
- [ ] **[NEW] `tests/unit/test_risk_summary.py`** (AC-7): `summarize_report(report_dict)` yields the correct
  `RiskSummary` (high/medium/low/validated/total/degraded + per-clause-type map matching the dashboard's
  labels) and equals the dashboard-relevant fields of the legacy `read_report_data(path)` for the same report.
- [ ] Run `python -X utf8 -m pytest -q` → CONFIRM the new assertions FAIL.

---

## Task 2: Migration `alembic/versions/0011_job_risk_summary.py`  [AC-1]
- [ ] `revision="0011"`, `down_revision="0010"` (mirror 0010's additive/reversible style).
- [ ] `upgrade()`: `op.add_column("jobs", sa.Column(<n>, <t>, nullable=True))` for `risk_high`/`risk_medium`/
  `risk_low`/`validated_findings`/`total_clauses` (sa.Integer), `analysis_degraded` (sa.Integer, 0/1),
  `risk_by_type` (sa.Text).
- [ ] `downgrade()`: `op.drop_column("jobs", <n>)` for each.

---

## Task 3: `app/runner/risk_summary.py` (NEW — neutral)  [AC-3, AC-7]
- [ ] `@dataclass RiskSummary`: `high/medium/low/validated_findings/total_clauses: int`,
  `analysis_degraded: bool`, `risk_by_type: dict` (per-clause-type `{type:{"high","medium","low"}}` for ONE
  report).
- [ ] `summarize_report(report: dict) -> RiskSummary` — **pure**, from a parsed report `.json`
  (`summary` + `findings` + `analysis_degraded`); build `risk_by_type` using the SAME clause-type labels +
  severity keys `build_dashboard_metrics` uses today (incl. the uncategorized bucket).
- [ ] `load_report_summary(report_path) -> Optional[RiskSummary]` — best-effort: resolve
  `Path(report_path).with_suffix(".json")`, `blob_store.exists` + `blob_store.read`, `json.loads`,
  `summarize_report`; `None` on unset/missing/malformed (logged, never raised). **This is the single seam the
  write path AND the read-path fallback both call** (structural parity). Imports only `blob_store`, `json`,
  `logging`, `pathlib` (runner-safe — no `app.api.*`, no graph-node import).
- [ ] `to_row_fields(summary) -> dict` (summary → the 7 column values, `risk_by_type` as a JSON string;
  `analysis_degraded` as 0/1) and `from_row(row) -> Optional[RiskSummary]` (the 7 JobRow fields → RiskSummary;
  None when `risk_high` is None / `risk_by_type` unparseable → EC-7).

---

## Task 4: `store.py` — JobRow + upsert + read  [AC-2]
- [ ] `JobRow` gains `risk_high/risk_medium/risk_low/validated_findings/total_clauses: Optional[int] = None`,
  `analysis_degraded: Optional[bool] = None`, `risk_by_type: Optional[dict] = None`.
- [ ] `upsert`: add the 7 columns to `INSERT INTO jobs (…)` + `VALUES (…)` + `ON CONFLICT … DO UPDATE SET …`
  (`json.dumps(risk_by_type)` when present; `analysis_degraded` 0/1; NULLs when absent).
- [ ] Row→JobRow read (store.py ~180): populate the new fields with the backward-compat guard
  `r["risk_high"] if "risk_high" in r.keys() else None` (mirror the `original_filename`/`user_id` pattern);
  `json.loads(r["risk_by_type"])` when present/non-null (defensive → None on malformed).

---

## Task 5: `registry.py` — thread the summary through mark_terminal  [AC-3]
- [ ] `mark_terminal(…, risk_summary: Optional["RiskSummary"] = None)`: set `self._risk_summary = risk_summary`
  before `_persist()`. Default None ⇒ unchanged callers store no summary.
- [ ] `_to_row()`: when `self._risk_summary` is not None, spread `risk_summary.to_row_fields(self._risk_summary)`
  into the `JobRow(...)` construction; else the new fields default to None. (No graph-node/api import — 061
  guard intact; `RiskSummary` is runner-level.)

---

## Task 6: `worker.py` — compute at completion, best-effort  [AC-3, EC-3]
- [ ] In the **completed** branch, before `rec.mark_terminal(...)`, compute the summary guarded so it can NEVER
  alter the terminal outcome (mirrors 061):
  ```python
  summary = None
  try:
      if result.report_path:
          summary = load_report_summary(result.report_path)
  except Exception:
      logger.warning("risk-summary computation failed (best-effort)", exc_info=True)
  ```
  then pass `risk_summary=summary` to the existing `mark_terminal(status=JobState.completed, …)` call.
- [ ] The `failed`/error terminal branch passes no `risk_summary` (stays NULL).

---

## Task 7: `aggregate.py` (+ routes call-site) — read from row, fall back for legacy  [AC-4, AC-5, AC-6]
- [ ] Change the injected reader seam to return a `RiskSummary`: the builders take
  `read_summary: Callable[[str], Optional[RiskSummary]]` (prod = `risk_summary.load_report_summary`). routes.py
  dashboard/jobs call-sites pass `load_report_summary` instead of `read_report_data`.
- [ ] Per completed row: `rs = risk_summary.from_row(row)` → if not None use it (NO read); else
  `rs = read_summary(row.report_path)` (legacy fallback — the ONLY place the reader is called).
- [ ] `build_dashboard_metrics`: fold `high/medium/low`, `validated`, `total` and MERGE each row's
  `risk_by_type` into the aggregate heatmap/top-risky — identical numbers, sourced per-row. (The dashboard no
  longer needs raw `findings`.)
- [ ] `build_job_list`: for a completed row set `report_available`, `high/medium/low`, `risk_band`
  (`derive_band`), `analysis_degraded` from `rs`.
- [ ] Response models unchanged → identical JSON (AC-8). (`read_report_data` may remain for any other caller;
  do not delete unless unused.)

---

## Task 8: Backend gate  [AC-1..AC-8]
- [ ] `python -X utf8 -m pytest -q` → new tests pass AND the full suite stays green (store / registry / worker
  / dashboard / migration tests unchanged except where they assert the new behavior). Fix code, not tests (§7).
- [ ] `git diff --name-only main` matches the §0 allow-list (no node/edge/`ContractState`/`specs/001`/response-
  model/frontend/dependency change).

---

## Task 9: Merge
- [ ] Gate green; diff scope matches §0. Rebase `main`, merge `feature/066-dashboard-summary-denormalize`,
  delete branch (`git-finish`). Auto-deploys; the entrypoint `alembic upgrade head` adds the columns on Turso;
  new analyses store the summary; `/api/dashboard` + `/api/jobs` load sub-second (one SELECT, no per-report
  round-trips), legacy rows correct via fallback. No flag, no frontend change. (AC-9 live smoke: confirm the
  fast loads on the deploy.)

---

*Per §1/§11, implementation happens only on `feature/066-dashboard-summary-denormalize`, opened after spec +
plan + tasks are all spec-reviewer-APPROVED. Store-DB denormalization only; one shared `summarize_report`
feeds the stored + fallback paths; best-effort write; §019 isolation + response JSON unchanged.*
