# Durable Persistence Implementation Tasks

These tasks implement `specs/012-durable-persistence/spec.md` per
`specs/012-durable-persistence/plan.md`. Follow them **in order** — the order is
the plan's §4 TDD sequence (test written and confirmed failing before the code
that satisfies it, constitution §7). Each task is written to be implementable
without inferring anything not stated (constitution §8).

Conventions (unchanged from 011):
- All paths are relative to `backend/` unless noted (e.g. `.gitignore` is repo-root).
- "confirm FAILING" = run the named test and see it fail on the missing symbol
  *before* writing the implementation task that follows.
- Do **not** modify `app/api/routes.py`, `app/runner/models.py`, or
  `app/runner/events.py` — the 011 seam and boundary types are reused as-is
  (spec §2.4, AC-6). If you feel you must, stop: something has drifted from the plan.

---

## Task 0: Create feature branch (constitution §1/§11 gate)

- [ ] Confirm `spec.md`, `plan.md`, and this `tasks.md` all exist under
      `specs/012-durable-persistence/` and are approved.
- [ ] From an up-to-date `main`, create and check out `feature/012-durable-persistence`
      (the `git-start` skill does this mechanically).
- [ ] Confirm the required deps are already installed (they are in `pyproject.toml`
      and the venv): `langgraph-checkpoint-sqlite`, `aiosqlite`, `alembic`. **No new
      dependency is added by this feature.** (If any import fails, `pip install -e .`.)

---

## Task 1: Config constants + `.gitignore` (GATING — do first)

- [ ] Open `app/config.py`. It already imports `os`. Append a new section at the
      **end** (pure addition; do not touch existing constants), exactly:

```python
# ── Durable persistence (feature 012) ──────────────────────────────────────────
# Source: specs/012-durable-persistence/spec.md §6.1

JOB_STORE_DB_PATH: str = "data/job_store.db"
# Alembic-managed durable job store (spec D1). backend/-relative, mirroring
# REPORT_OUTPUT_DIR / UPLOAD_DIR. Holds the durable projection of JobRecord so a
# GET survives a process restart (spec AC-2; kills 011 EC-9). git-ignored.

CHECKPOINTER_DB_PATH: str = "data/checkpoints.db"
# LangGraph SqliteSaver file (spec D1). Owned by SqliteSaver.setup(), NEVER by
# Alembic. Serialized ContractState per super-step, keyed by thread_id
# (== job_id, spec D3). git-ignored.

CHECKPOINTER_ENABLED: bool = True
# When True the runner compiles the graph with the SqliteSaver (spec D7). Tests
# and the CLI may disable it to compile a checkpointer-less graph (011 behavior).

JOB_STORE_RETENTION_MAX: int = 500
# Insert-time row cap (spec D5). On insert, rows beyond this are pruned oldest-
# first by submitted_at and their checkpoint threads deleted, so the two stores
# never drift. Supersedes 011's JOB_REGISTRY_MAX (kept as an alias below).

STARTUP_RECOVERY_ENABLED: bool = True
# When True the lifespan enumerates the store and re-enqueues recoverable jobs
# (spec D8). Tests disable it to assert store state without auto-running jobs.

JOB_REGISTRY_MAX: int = JOB_STORE_RETENTION_MAX
# 011 alias — keep so no existing call site breaks; new code reads JOB_STORE_RETENTION_MAX.
```

- [ ] The existing 011 `JOB_REGISTRY_MAX: int = 100` line must be **removed**
      (it is replaced by the alias above). Grep for `JOB_REGISTRY_MAX` and confirm
      the only definition left is the alias.
- [ ] Open the repo-root `.gitignore`. Beside the existing `backend/data/reports/`
      / `backend/data/uploads/` / `backend/data/secrets/` lines, add:
      `backend/data/*.db` and `backend/data/*.db-wal` and `backend/data/*.db-shm`
      (SQLite WAL siblings) so neither store nor its journals are ever committed.
- [ ] Update `tests/unit/test_config.py`: add a test asserting the five new
      constants exist with the documented types/defaults, and that
      `JOB_REGISTRY_MAX == JOB_STORE_RETENTION_MAX`. Run it — green.

---

## Task 2: Alembic scaffold + `jobs` migration (test-first)

- [ ] Create `tests/integration/test_alembic_head.py` (confirm FAILING):
  - [ ] `from app.runner.migrations import upgrade_to_head` (fails until Task 3).
  - [ ] Test: call `upgrade_to_head(str(tmp_path / "j.db"))`, then open that file
        with `sqlite3` and assert a `jobs` table exists with columns exactly:
        `job_id, document_path, recipient, status, submitted_at, started_at,
        finished_at, current_node, completed_nodes, report_path,
        mcp_delivery_status, error` and that `job_id` is the primary key
        (`PRAGMA table_info(jobs)`), and index `ix_jobs_submitted_at` exists
        (`PRAGMA index_list(jobs)`) — spec AC-19.
- [ ] Create the Alembic scaffold under `backend/` (do NOT use the interactive
      `alembic init`; create the files directly to keep it scoped to the job store):
  - [ ] `backend/alembic.ini` — minimal: `[alembic] script_location = alembic`,
        a placeholder `sqlalchemy.url = sqlite:///data/job_store.db` (env.py
        overrides it), and the standard `[loggers]/[handlers]/[formatters]` block.
  - [ ] `backend/alembic/script.py.mako` — the standard Alembic template.
  - [ ] `backend/alembic/env.py` — offline+online run functions that read the URL
        from `config.get_main_option("sqlalchemy.url")` (the single source — Task 3's
        `upgrade_to_head` always injects it via `set_main_option`, and the ini's
        placeholder is the real default for a raw `alembic` CLI call). Do NOT import
        `app.config` here — keeping env.py config-free avoids an import cycle and lets
        tests point at a temp DB purely through the injected URL. `target_metadata =
        None` (migrations are hand-written, not autogenerate).
  - [ ] `backend/alembic/versions/0001_create_jobs_table.py` — `revision = "0001"`,
        `down_revision = None`. `upgrade()` runs:

```python
op.create_table(
    "jobs",
    sa.Column("job_id", sa.Text, primary_key=True),
    sa.Column("document_path", sa.Text, nullable=False),
    sa.Column("recipient", sa.Text, nullable=True),
    sa.Column("status", sa.Text, nullable=False),
    sa.Column("submitted_at", sa.Text, nullable=False),
    sa.Column("started_at", sa.Text, nullable=True),
    sa.Column("finished_at", sa.Text, nullable=True),
    sa.Column("current_node", sa.Text, nullable=True),
    sa.Column("completed_nodes", sa.Text, nullable=False, server_default="[]"),
    sa.Column("report_path", sa.Text, nullable=True),
    sa.Column("mcp_delivery_status", sa.Text, nullable=False, server_default="{}"),
    sa.Column("error", sa.Text, nullable=True),
)
op.create_index("ix_jobs_submitted_at", "jobs", ["submitted_at"])
```
        `downgrade()` drops the index then the table.

---

## Task 3: `migrations.py` helper (make Task 2 green)

- [ ] Create `app/runner/migrations.py` with `upgrade_to_head(db_path: str) -> None`:
  - [ ] Build an Alembic `Config` pointing `script_location` at the `backend/alembic`
        directory (resolve it relative to this file: `Path(__file__).parents[2] /
        "alembic"` → i.e. `backend/alembic`), set
        `config.set_main_option("sqlalchemy.url", f"sqlite:///{db_path}")`, then
        `from alembic import command; command.upgrade(config, "head")`.
  - [ ] On any exception, let it propagate (spec EC-8 — fail fast; do NOT swallow).
- [ ] Run `tests/integration/test_alembic_head.py` — green.

---

## Task 4: `store.py` — pure SQLite job store (test-first)

- [ ] Create `tests/unit/test_job_store.py` (confirm FAILING):
  - [ ] `from app.runner.store import JobStore, JobRow` (fails until this task's impl).
  - [ ] Fixture: `upgrade_to_head(db)` on a temp path, then `JobStore(db)`.
  - [ ] `test_upsert_get_roundtrip`: build a `JobRow` with non-empty
        `completed_nodes=["ingest_agent","clause_splitter"]`,
        `error=ErrorInfo(kind="x", message="y")`, and — importantly —
        `mcp_delivery_status={"drive":{"status": MCPDeliveryStatus.SUCCESS,
        "error_message": None, "delivered_at": "..."}}` using the **real
        `MCPDeliveryStatus` enum member** (from `app.graph.state`), NOT a plain
        string. This proves `_encode`'s `json.dumps` survives the enum (it does
        because `MCPDeliveryStatus` is a `str`-enum → serializes as `"success"`);
        a plain-string test would hide a regression if that ever changed. `upsert`
        then `get` returns an equal `JobRow` with the status decoded back to the
        plain string `"success"` (json has no enum on the way back) — spec AC-4.
        Note in `_encode`: `error` is a Pydantic model, so encode it as
        `json.dumps({"kind": e.kind, "message": e.message})`, not `json.dumps(e)`.
  - [ ] `test_upsert_is_update`: upsert same `job_id` twice with a changed `status`;
        `get` reflects the second write (ON CONFLICT update path).
  - [ ] `test_nonterminal_filters`: insert rows with statuses queued/running/
        completed/failed; `nonterminal()` returns only queued+running, ordered by
        `submitted_at` (spec D6).
  - [ ] `test_prune_returns_oldest`: insert N+2 rows with increasing `submitted_at`;
        `prune(N)` returns the 2 oldest `job_id`s and they are gone from `get` (spec D5).
  - [ ] `test_get_missing_none`: `get("nope")` → `None` (spec AC-5).
- [ ] Create `app/runner/store.py` exactly per plan §2.2:
  - [ ] Imports: `json, sqlite3, threading`; `from dataclasses import dataclass`;
        `from typing import Optional`; `from app.runner.models import ErrorInfo, JobState`.
  - [ ] `JobRow` dataclass with the 12 fields from plan §2.2 (types as listed;
        `completed_nodes: list`, `mcp_delivery_status: dict`, `error: Optional[ErrorInfo]`).
  - [ ] `JobStore.__init__(db_path)`: `threading.Lock()`, one
        `sqlite3.connect(db_path, check_same_thread=False)`, `row_factory = sqlite3.Row`.
        Do **not** create the schema here — assume Alembic already ran (docstring says so).
  - [ ] `upsert(row)`, `get(job_id)`, `nonterminal()`, `prune(keep_max)`, `close()`
        exactly per the plan §2.2 SQL. Every method that touches the connection does so
        **under `self._lock`** (spec EC-5).
  - [ ] Private `_encode(row) -> tuple` and `_decode(sqlite3.Row) -> JobRow`: the only
        place JSON (de)serialization of `completed_nodes`/`mcp_delivery_status`/`error`
        and the `JobState.value` ↔ `JobState(...)` / `ErrorInfo` round-trip lives.
        `error` encodes to `json.dumps({"kind":..., "message":...})` or `None`.
- [ ] Run `tests/unit/test_job_store.py` — green.

---

## Task 5: `persistence.py` — saver factory + `builder.py` param (test-first)

- [ ] Create `tests/unit/test_build_graph_checkpointer.py` (confirm FAILING):
  - [ ] `test_default_structure_unchanged`: `g = build_graph()`; assert its node set
        and edges match a **pinned** expected structure — the 7 node names
        (`ingest_agent, clause_splitter, crag_retrieval, self_rag_validation,
        risk_score, redline, skip_redline, report`) and that compiling succeeds. This
        locks spec AC-8 (checkpointer param must NOT change the default graph).
        (Reuse whatever structure assertion 011/009 tests already use for the graph;
        if none, assert `set(g.get_graph().nodes) ⊇` the 7 logical node names.)
  - [ ] `test_checkpointer_writes_thread`: `from app.runner.persistence import
        build_saver, has_checkpoint` (fails until impl); build a saver on a temp DB;
        build a **tiny local StateGraph** (2 fake nodes, not the real pipeline)
        compiled with that saver; stream it once with
        `config={"configurable":{"thread_id":"t1"}}`; assert `has_checkpoint(saver,"t1")`
        is True and `has_checkpoint(saver,"absent")` is False (spec AC-9).
- [ ] Modify `app/graph/builder.py`: change the signature to
      `def build_graph(checkpointer=None):` and the final line to
      `return graph.compile(checkpointer=checkpointer)`. Add one line to the docstring
      noting the default `None` compiles a checkpointer-less graph byte-identical to
      011 (spec D7). **Change nothing else** — no node/edge/name/order edits.
- [ ] Create `app/runner/persistence.py` exactly per plan §2.5:
  - [ ] `build_saver(db_path) -> SqliteSaver`: `conn = sqlite3.connect(db_path,
        check_same_thread=False)`; `saver = SqliteSaver(conn)`; `saver.setup()`; return.
        Import `from langgraph.checkpoint.sqlite import SqliteSaver`.
  - [ ] `has_checkpoint(saver, thread_id) -> bool`:
        `return saver.get_tuple({"configurable":{"thread_id":thread_id}}) is not None`.
- [ ] Run `tests/unit/test_build_graph_checkpointer.py` — green. Also re-run the
      existing graph-structure tests (009/011) — still green (AC-8).

---

## Task 6: `registry.py` — write-through + rehydrate + retention (test-first)

- [ ] Create `tests/unit/test_registry_writethrough.py` (confirm FAILING):
  - [ ] Helper: `upgrade_to_head(db)`, `store = JobStore(db)`, a dummy asyncio loop
        (`asyncio.new_event_loop()`), and `registry = JobRegistry(store, saver=None,
        loop=loop, max_jobs=100)`.
  - [ ] `test_add_persists_queued`: build a `JobRecord`, `registry.add(rec)`; open a
        **fresh** `JobStore` on the same file and `get(job_id)` → row with
        `status=queued` (spec AC-1).
  - [ ] `test_mutations_writethrough`: `rec.mark_running(...)`, `rec.record_progress(
        "ingest_agent")`, `rec.mark_terminal(status=completed, ...)`; after each, a
        fresh `JobStore.get` reflects the new value (spec AC-4).
  - [ ] `test_rehydrate_after_restart`: `registry.add(rec)`, mutate to completed;
        drop the live dict (`registry._live.clear()`); `registry.get(job_id)` returns a
        rebuilt `JobRecord` whose `to_status()` equals the pre-clear status, with a
        **fresh** buffer (spec AC-2/AC-3, D4).
  - [ ] `test_store_none_record_still_works`: a `JobRecord` with `_store=None`
        (no registry) mutates in memory without error (spec AC-7a — 011 unit tests
        keep working).
- [ ] Create `tests/unit/test_retention.py` (confirm FAILING):
  - [ ] Use a **spy saver** exposing `delete_thread(tid)` recording calls.
        `registry = JobRegistry(store, saver=spy, loop=loop, max_jobs=3)`.
  - [ ] Add 5 records with increasing `submitted_at`; assert the 2 oldest are gone
        from `registry.get` (→ None) and `spy.delete_thread` was called with those 2
        `job_id`s (spec D5, EC-7, 011 AC-22).
- [ ] Modify `app/runner/registry.py` per plan §2.3:
  - [ ] `JobRecord`: add field `_store: Optional["JobStore"] = field(default=None,
        init=False, repr=False, compare=False)`.
  - [ ] Add `_to_row(self) -> "JobRow"` building a `JobRow` from the private fields
        (status→`self._status`, etc.).
  - [ ] Add `_persist(self)` (caller holds `self._lock`): `if self._store: self._store.upsert(self._to_row())`.
  - [ ] Add `_persist_initial(self)` (caller does NOT hold the lock): `with self._lock:
        self._persist()` — used by `JobRegistry.add` to INSERT the queued row.
  - [ ] Add the one-line `self._persist()` call at the **end** of the existing
        `mark_running`, `record_progress`, `mark_terminal` critical sections (inside
        their `with self._lock`).
  - [ ] Add `reset_for_rerun(self)` and `snapshot_completed_nodes(self)` exactly per
        plan §2.3.
  - [ ] Add classmethod `from_row(cls, row, *, buffer, store) -> "JobRecord"` rebuilding
        a record from a `JobRow`: set the public init fields (`job_id, document_path,
        submitted_at, buffer, recipient`) and the private mutable fields
        (`_status, _started_at, _finished_at, _current_node, _completed_nodes,
        _report_path, _mcp_delivery_status, _error`) from the row; set `_store = store`.
  - [ ] `JobRegistry.__init__(self, store, saver, loop, max_jobs)`: keep `_lock`, add
        `_store`, `_saver`, `_loop`, `_max`, and `_live: dict[str, JobRecord] = {}`.
  - [ ] `add(self, rec)` and `get(self, job_id)` exactly per plan §2.3 (including the
        prune-then-evict-under-lock then delete_thread pattern, and rehydrate-on-miss
        building a fresh `JobEventBuffer(self._loop)`).
  - [ ] Import `from app.runner.store import JobStore, JobRow`.
- [ ] Run both new test files — green.

---

## Task 7: `core.py` + `worker.py` — checkpointer + resume plumbing (test-first)

- [ ] Create `tests/unit/test_run_pipeline_resume.py` (confirm FAILING):
  - [ ] Patch `app.runner.core.build_graph` with a fake returning a graph whose
        `.stream(inp, stream_mode, config)` records `inp` and `config` and yields a
        scripted list of `{"current_node": n, ...}` states; patch
        `app.runner.core.deliver_report_sync` to a stub.
  - [ ] `test_fresh_seeds_initial`: `run_pipeline(path, checkpointer=saver,
        thread_id="t", resume=False)` calls `.stream` with a dict input containing
        exactly `{document_path, processing_started_at}` and
        `config={"configurable":{"thread_id":"t"}}` (spec AC-6, AC-10).
  - [ ] `test_resume_streams_none`: `resume=True` calls `.stream(None, ...)` (spec AC-11).
  - [ ] `test_resume_dedup`: with `already_completed=["ingest_agent"]` and a scripted
        stream whose FIRST yield re-emits `current_node="ingest_agent"` then
        `"clause_splitter"`, assert `on_progress` fires **only** for
        `clause_splitter` (the re-emitted `ingest_agent` is deduped) — spec EC-1.
  - [ ] `test_no_checkpointer_unchanged`: `checkpointer=None` → `.stream` called with
        `config=None` and the fresh initial dict (011 behavior preserved).
- [ ] Modify `app/runner/core.py` per plan §2.5: extend `run_pipeline` signature with
      `checkpointer=None, thread_id=None, resume=False, already_completed=None`; build
      `config` only when `checkpointer` is set; choose `stream_input` (None on resume,
      else the seeded initial); seed `seen = set(already_completed or ())`; in the loop
      fire `on_progress` only when `node and node != last_node and node not in seen`,
      adding each fired node to `seen`; pass `config=config` to `graph.stream`. Delivery
      and `processing_completed_at` stamping stay exactly as they are.
- [ ] Modify `app/runner/worker.py` per plan §2.6:
  - [ ] `PipelineWorker.__init__(self, registry, saver=None, concurrency=1)` — store `self._saver`.
  - [ ] `submit(self, job_id, resume=False)` → `self._queue.put((job_id, resume))`.
        (The existing `ctx.worker.submit(job_id)` call in routes.py still works via
        the `resume=False` default — do not change routes.py.)
  - [ ] `_loop`: `item = self._queue.get(); if item is _SENTINEL: return; self._run_one(item)`
        (sentinel is still the bare object; tuples are unpacked in `_run_one`).
  - [ ] `_run_one(self, item)`: unpack `job_id, resume = item`; keep the `rec is None`
        guard; `mark_running` as per plan §2.6 (fresh vs keep-original-start);
        `already = None` on fresh, `rec.snapshot_completed_nodes()` on resume; pass
        `checkpointer=self._saver, thread_id=job_id, resume=resume,
        already_completed=already` into `run_pipeline`. `mark_terminal`/publish blocks
        are unchanged (write-through now persists them automatically).
- [ ] Run `tests/unit/test_run_pipeline_resume.py` — green. Re-run 011's
      `test_runner_core.py` / worker tests — adapt only the constructor/`submit`
      call-sites the signature change forces (registry now needs store/saver/loop;
      worker now takes `saver=`), nothing behavioral.

---

## Task 8: Lifespan wiring + startup recovery (test-first, integration)

- [ ] Create the recovery integration suite under `tests/integration/` (confirm FAILING),
      all with a **mocked graph** (patch `build_graph`/node functions so no real Ollama;
      spec §3) and temp `JOB_STORE_DB_PATH`/`CHECKPOINTER_DB_PATH` (monkeypatch config;
      spec AC-18):
  - [ ] `test_restart_get_survives.py`: build app (TestClient), `POST /api/analyze`,
        let the mocked run finish, tear the app down, rebuild on the SAME temp DBs with
        `STARTUP_RECOVERY_ENABLED=False`; `GET /api/jobs/{id}` returns the persisted
        `JobStatus` (spec AC-2) byte-identical for the completed job (AC-3).
  - [ ] `test_recover_running_resumes.py`: pre-seed a `running` row (via `JobStore`)
        AND a checkpoint at node k (via a saver + a partial mocked stream); build app
        with recovery ON; assert (a) node fns ≤ k not re-invoked, (b) `completed_nodes`
        has no duplicate and ends `[1..7]`, (c) job → completed (spec AC-11, EC-1).
  - [ ] `test_recover_queued_fresh.py`: seed a `queued` row (no checkpoint) → fresh run
        to completed (AC-12); seed `running` with NO checkpoint → fresh re-run (AC-13, EC-2).
  - [ ] `test_recover_terminal_untouched.py`: seed `completed` + `failed` rows; build
        app with recovery ON; neither is re-run (spy on the worker), both retrievable via
        `GET` (AC-14); building the app twice does not double-enqueue (AC-15).
  - [ ] `test_recover_missing_upload.py`: seed a recoverable job whose `document_path`
        does not exist; recovery does not crash startup and the job ends terminal
        (completed-with-ingest-error or failed), never perpetual running (spec EC-3).
  - [ ] `test_ingest_error_durable.py`: mock the graph to reach `END` with
        `ingest_error` set (011 EC-1 path); the job persists `status=completed` with
        `error` populated; after a rebuild-on-same-DB the `GET` still shows
        completed+error (spec AC-16). Also assert a `failed` (crashed) job is NOT
        resumed on a later startup (spec AC-17 — terminal, per AC-14).
  - [ ] Add a light **structural** assertion (spec AC-6/AC-7): a test that imports
        `app.api.routes` and asserts its module source does not import `sqlite3` or
        `app.runner.store` — job access stays behind the registry seam. (Cheap; mirrors
        011's import-guard test.)
- [ ] Modify `app/api/main.py` per plan §2.8:
  - [ ] Import `upgrade_to_head`, `JobStore`, `build_saver`, `has_checkpoint`,
        `JobState`.
  - [ ] In `lifespan`, before building the registry: `upgrade_to_head(_cfg.JOB_STORE_DB_PATH)`;
        `store = JobStore(_cfg.JOB_STORE_DB_PATH)`;
        `saver = build_saver(_cfg.CHECKPOINTER_DB_PATH) if _cfg.CHECKPOINTER_ENABLED else None`;
        `registry = JobRegistry(store, saver, loop, max_jobs=_cfg.JOB_STORE_RETENTION_MAX)`;
        `worker = PipelineWorker(registry, saver=saver, concurrency=_cfg.RUNNER_WORKER_CONCURRENCY)`.
  - [ ] `worker.start()`; then `if _cfg.STARTUP_RECOVERY_ENABLED: _recover(registry, store, saver, worker)`.
  - [ ] In the `finally`: `worker.stop()`, `store.close()`, and
        `if saver is not None: saver.conn.close()`.
  - [ ] Add the module-level `_recover(registry, store, saver, worker)` exactly per plan
        §2.8 (enumerate `store.nonterminal()`; `rec = registry.get(row.job_id)`;
        `resumable = row.status == JobState.running and saver is not None and
        has_checkpoint(saver, row.job_id)`; if not resumable `rec.reset_for_rerun()`;
        `worker.submit(row.job_id, resume=resumable)`).
- [ ] Run the recovery suite — green.

---

## Task 9: CLI `--checkpoint` opt-in

- [ ] Modify `app/runner/__main__.py` per plan §2.9: add `--checkpoint`
      (`action="store_true"`); when set, `saver = build_saver(_cfg.CHECKPOINTER_DB_PATH)`
      and pass `checkpointer=saver, thread_id=str(uuid4())` into `run_pipeline`;
      default (flag absent) → `checkpointer=None, thread_id=None` (011 behavior).
      Import `uuid4`, `app.config as _cfg`, `build_saver`.
- [ ] Manually run `python -m app.runner tests/fixtures/<a small fixture> --checkpoint`
      is optional here (real-LLM); a fast check is that `python -m app.runner --help`
      shows the new flag and that argument wiring imports cleanly.

---

## Task 10: Full suite + real restart smoke (constitution §7; project rule)

- [ ] Run the **entire** test suite (`pytest`): the 498 existing + all new tests green.
      No existing test is weakened to pass (constitution §7); if a 011 test broke, fix
      the code, not the test.
- [ ] `black` + `ruff` + `mypy` clean on the changed files.
- [ ] **Real end-to-end restart smoke** (the live proof AC-11 exists for — run before
      calling the feature done, per the project's run-real-smoke-before-continuation rule):
  1. Start the server (`python -m app.api`), `POST /api/analyze` with
     `tests/fixtures/sample.pdf`.
  2. Watch SSE / `GET` until a mid-pipeline node (e.g. `crag_retrieval`) is reached,
     then **hard-kill** the process (so no terminal write happens — the job row stays
     `running` with a checkpoint).
  3. Restart the server on the same `data/` dir. Confirm: startup does not crash;
     `GET /api/jobs/{id}` shows the job (not 404); the job **resumes** from its last
     checkpoint (earlier nodes not re-run — visible as the run finishing materially
     faster than a cold run) and reaches `completed` with `report_available: true`.
  4. Record the outcome (timings, which node it resumed from) in the merge notes.
- [ ] Finish the branch with the `git-finish` skill (rebase on main, merge, delete
      branch) once all of the above pass.

---

## Out of scope for these tasks (do NOT implement here)

Per `spec.md §5` / `plan.md §7`: no `ContractState` slimming; no MCP delivery
idempotency; no Postgres/multi-worker; no live-SSE recovery across restart; no
"resume this job" HTTP endpoint; no auth/RBAC; no at-rest DB encryption; no
scheduled retention job. The only `builder.py` change is the optional
`checkpointer` param (Task 5). `routes.py`, `models.py`, `events.py` are untouched.
