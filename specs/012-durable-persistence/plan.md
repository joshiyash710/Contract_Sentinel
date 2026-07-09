# Durable Persistence Technical Plan

## Git Branch

Per constitution §11 (Git Branching Workflow), this feature is developed on
branch **`feature/012-durable-persistence`**. Use the `git-start` /
`git-finish` slash commands for the mechanical branch/rebase/merge steps.

## 1. Overview

Feature 011 left two seams deliberately open for this feature (011 spec §5, D5,
EC-9; AC-21):

1. The **single registry seam** — all job access goes through one object
   (`JobRegistry` on `app.state.ctx`), so its in-memory store can be swapped for
   a durable one without touching route handlers.
2. The **checkpointer-less compile** — `build_graph()` calls `graph.compile()`
   with no `checkpointer=`, so nothing durably records `ContractState` between
   nodes.

This plan fills both, exactly as scoped in `spec.md` (decisions D1–D8):

- A **synchronous SQLite job store** (`app/runner/store.py`) behind the existing
  registry seam, with **write-through** on every `JobRecord` mutation, so job
  status survives a restart (spec AC-1..AC-5; kills 011 EC-9).
- A **LangGraph `SqliteSaver` checkpointer**, injected via a new optional
  `build_graph(checkpointer=...)` parameter and driven with
  `thread_id == job_id`, so `ContractState` is durably checkpointed after every
  node (spec AC-8..AC-10).
- **Startup recovery** in the FastAPI lifespan: `running` jobs resume from their
  last checkpoint, `queued` jobs re-run fresh, terminal jobs are left alone
  (spec AC-11..AC-15).
- **Alembic** owns the job-store schema; **`SqliteSaver.setup()`** owns the
  checkpointer schema; the two live in **separate files** (spec D1).

**Non-goals restated from the spec:** no graph node/edge change beyond the
optional `checkpointer` param on `build_graph()` (D7); no HTTP surface change
(spec §2.4); sync driver, not `aiosqlite`/`AsyncSqliteSaver` (D2, endorsed);
SSE backlog stays ephemeral (D4).

**Verified against the installed stack** (`langgraph` 1.2.8,
`langgraph-checkpoint-sqlite` 3.1.0, `aiosqlite` 0.22.1, `alembic` 1.18.5):
`from langgraph.checkpoint.sqlite import SqliteSaver`; `SqliteSaver(conn)` +
`.setup()`; `.get_tuple(config) -> None` when a thread has no checkpoint;
`.delete_thread(thread_id)`; `StateGraph.compile(checkpointer=...)`.

## 2. Files to Create / Modify

### 2.1 Shared Config — `backend/app/config.py` [MODIFY]

Append a new section (mirroring the existing "Runner / API layer" block), per
spec §6.1:

```python
# ── Durable persistence (feature 012) ──────────────────────────────────────────
# Source: specs/012-durable-persistence/spec.md §6.1

JOB_STORE_DB_PATH: str = "data/job_store.db"
# Alembic-managed durable job store (spec D1). backend/-relative, mirroring
# REPORT_OUTPUT_DIR / UPLOAD_DIR. Holds the durable projection of JobRecord so a
# GET survives a process restart (spec AC-2; kills 011 EC-9). git-ignored.

CHECKPOINTER_DB_PATH: str = "data/checkpoints.db"
# LangGraph SqliteSaver file (spec D1). Owned by SqliteSaver.setup(), NEVER by
# Alembic. Holds serialized ContractState per super-step, keyed by thread_id
# (== job_id, spec D3). git-ignored.

CHECKPOINTER_ENABLED: bool = True
# When True the runner compiles the graph with the SqliteSaver (spec D7). Tests
# and the CLI may disable it to compile a checkpointer-less graph (011 behavior).

JOB_STORE_RETENTION_MAX: int = 500
# Insert-time row cap (spec D5). On insert, rows beyond this are pruned oldest-
# first by submitted_at and their checkpoint threads deleted, so the two stores
# never drift. Supersedes 011's JOB_REGISTRY_MAX (kept as an alias, see §2.3).
# High enough that a single local session never prunes an in-session job.

STARTUP_RECOVERY_ENABLED: bool = True
# When True the lifespan enumerates the store and re-enqueues recoverable jobs
# (spec D8). Tests disable it to assert store state without auto-running jobs.
```

`JOB_REGISTRY_MAX` (011) is retained as `JOB_REGISTRY_MAX = JOB_STORE_RETENTION_MAX`
so no 011 call site breaks; new code reads `JOB_STORE_RETENTION_MAX`.

`.gitignore` gains `backend/data/job_store.db` and `backend/data/checkpoints.db`
(and their `-wal`/`-shm` siblings) — add `backend/data/*.db*`.

### 2.2 Job Store — `backend/app/runner/store.py` [NEW]

A pure-persistence class. Knows nothing about `JobRecord`, buffers, or graphs —
it moves plain rows in/out of SQLite so it is trivially unit-testable (AC-4). A
`JobRow` dataclass is the serialized shape.

```python
import json, sqlite3, threading
from dataclasses import dataclass
from typing import Optional

from app.runner.models import ErrorInfo, JobState

_TERMINAL = (JobState.completed, JobState.failed)

@dataclass
class JobRow:
    """Durable projection of JobRecord (spec §2.2). List/dict/ErrorInfo fields are
    JSON-encoded in SQLite; decoded here."""
    job_id: str
    document_path: str
    recipient: Optional[str]
    status: JobState
    submitted_at: str
    started_at: Optional[str]
    finished_at: Optional[str]
    current_node: Optional[str]
    completed_nodes: list          # JSON TEXT column
    report_path: Optional[str]
    mcp_delivery_status: dict       # JSON TEXT column
    error: Optional[ErrorInfo]      # JSON TEXT column {kind,message}

class JobStore:
    """Thread-safe synchronous SQLite job store (spec D2). ONE shared sqlite3
    connection with check_same_thread=False, guarded by a lock, because the
    background WORKER THREAD write-through-persists while a request-loop GET reads
    (spec EC-5). Schema is created/upgraded by Alembic (§2.7), NOT here — this
    class only reads/writes rows and assumes `alembic upgrade head` already ran."""

    def __init__(self, db_path: str) -> None:
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row

    def upsert(self, row: JobRow) -> None:
        with self._lock:
            self._conn.execute(
                """INSERT INTO jobs (job_id, document_path, recipient, status,
                       submitted_at, started_at, finished_at, current_node,
                       completed_nodes, report_path, mcp_delivery_status, error)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(job_id) DO UPDATE SET
                       status=excluded.status, started_at=excluded.started_at,
                       finished_at=excluded.finished_at, current_node=excluded.current_node,
                       completed_nodes=excluded.completed_nodes, report_path=excluded.report_path,
                       mcp_delivery_status=excluded.mcp_delivery_status, error=excluded.error""",
                self._encode(row),
            )
            self._conn.commit()

    def get(self, job_id: str) -> Optional[JobRow]:
        with self._lock:
            cur = self._conn.execute("SELECT * FROM jobs WHERE job_id=?", (job_id,))
            r = cur.fetchone()
        return self._decode(r) if r else None

    def nonterminal(self) -> list[JobRow]:
        """Rows in queued/running — the recovery candidates (spec D6, AC-11/12)."""
        with self._lock:
            cur = self._conn.execute(
                "SELECT * FROM jobs WHERE status IN (?,?) ORDER BY submitted_at",
                (JobState.queued.value, JobState.running.value),
            )
            rows = cur.fetchall()
        return [self._decode(r) for r in rows]

    def prune(self, keep_max: int) -> list[str]:
        """Delete rows beyond keep_max oldest-first by submitted_at. Returns the
        pruned job_ids so the caller can delete their checkpoint threads (spec D5)."""
        with self._lock:
            cur = self._conn.execute(
                "SELECT job_id FROM jobs ORDER BY submitted_at DESC LIMIT -1 OFFSET ?",
                (keep_max,),
            )
            victims = [r["job_id"] for r in cur.fetchall()]
            if victims:
                self._conn.executemany("DELETE FROM jobs WHERE job_id=?",
                                       [(v,) for v in victims])
                self._conn.commit()
        return victims

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    # _encode(row)->tuple / _decode(sqlite3.Row)->JobRow handle the JSON columns
    # (completed_nodes, mcp_delivery_status, error) and the JobState<->str value.
```

`_encode`/`_decode` are the only place JSON (de)serialization of the three
composite columns and the `JobState`/`ErrorInfo` round-trip lives, so the row
shape has one source of truth.

### 2.3 Registry seam becomes durable — `backend/app/runner/registry.py` [MODIFY]

Keep the class names `JobRecord` / `JobRegistry` (the 011 seam name is stable) and
the exact `add`/`get` surface (spec AC-6, AC-7). Two changes:

**(a) `JobRecord` gains an optional `_store` handle and write-through.** Every
existing lock method (`mark_running`, `record_progress`, `mark_terminal`) calls a
new private `_persist()` **inside the same critical section**, so the SQLite row
and the in-memory fields never diverge (spec AC-4). `_store=None` keeps the record
a pure in-memory object for unit tests (spec AC-7a), so 011's registry tests still
pass unchanged.

```python
# JobRecord: add field
_store: Optional["JobStore"] = field(default=None, init=False, repr=False, compare=False)

def _persist(self) -> None:              # caller already holds self._lock
    if self._store is not None:
        self._store.upsert(self._to_row())   # builds a JobRow from current fields

def mark_running(self, started_at: str) -> None:
    with self._lock:
        self._status = JobState.running
        self._started_at = started_at
        self._persist()                  # ← added
# ...same one-line _persist() added to record_progress() and mark_terminal()

def reset_for_rerun(self) -> None:
    """Fresh re-run after restart with NO usable checkpoint (spec AC-12/13, EC-2):
    clear progress so completed_nodes re-accumulates from zero."""
    with self._lock:
        self._status = JobState.queued
        self._started_at = None
        self._finished_at = None
        self._current_node = None
        self._completed_nodes = []
        self._error = None
        self._persist()

def snapshot_completed_nodes(self) -> list[str]:
    """Lock-guarded copy for the resume dedup seed (spec EC-1). Copying under the
    lock avoids a torn read against the worker's record_progress append (011 R1)."""
    with self._lock:
        return list(self._completed_nodes)
```

`_to_row()` maps the private fields to a `JobRow` (JSON-encoding handled in the
store). The `report_path` property and `to_status()` are unchanged.

**(b) `JobRegistry` wraps a `JobStore` + a live in-memory dict.** The in-memory
dict holds the *live* `JobRecord` (with its ephemeral `JobEventBuffer`, spec D4)
for the process lifetime; the store is the durable mirror. `get()` returns the
live record if present, else **rehydrates** one from the store (fresh empty
buffer). `add()` writes through and prunes (spec D5).

```python
class JobRegistry:
    def __init__(self, store: "JobStore", saver, loop, max_jobs: int) -> None:
        self._store = store
        self._saver = saver            # for checkpoint-thread deletion on prune
        self._loop = loop              # to build fresh buffers on rehydrate
        self._max = max_jobs
        self._lock = threading.Lock()
        self._live: dict[str, JobRecord] = {}

    def add(self, rec: JobRecord) -> None:
        rec._store = self._store       # wire write-through before first persist
        with self._lock:
            self._live[rec.job_id] = rec
        rec._persist_initial()         # INSERT the queued row durably (spec AC-1)
        victims = self._store.prune(self._max)         # spec D5
        with self._lock:
            for v in victims:
                self._live.pop(v, None)                # evict live record under the lock
        for v in victims:
            if self._saver is not None:
                self._saver.delete_thread(v)           # keep files from drifting (SqliteSaver
                                                       # is internally thread-safe — has its own lock)

    def get(self, job_id: str) -> Optional[JobRecord]:
        with self._lock:
            rec = self._live.get(job_id)
        if rec is not None:
            return rec
        row = self._store.get(job_id)                  # rehydrate across restart (AC-2)
        if row is None:
            return None                                # → 404 (AC-5, 011 AC-17)
        rec = JobRecord.from_row(row, buffer=JobEventBuffer(self._loop), store=self._store)
        with self._lock:
            self._live.setdefault(job_id, rec)
        return rec
```

`_persist_initial()` is `mark`-style: under the lock it sets `submitted_at`/status
and INSERTs. `JobRecord.from_row(...)` is a classmethod rebuilding a record from a
`JobRow` with a fresh buffer and a store handle (buffer is ephemeral, spec D4).
The registry constructor signature changes (now takes `store`, `saver`, `loop`) —
only the lifespan (§2.6) constructs it, so this is a localized change (spec AC-6).

### 2.4 Graph builder — optional checkpointer — `backend/app/graph/builder.py` [MODIFY]

The **only** change to the graph module (spec D7, constitution §2). Add one
parameter and thread it into `compile`:

```python
def build_graph(checkpointer=None):
    """... (unchanged docstring) ...
    checkpointer: optional LangGraph checkpointer (feature 012). Default None →
    compiles a checkpointer-less graph byte-identical to feature 011, so every
    existing graph-structure test is unaffected (spec AC-8)."""
    graph = StateGraph(ContractState)
    # ... all 7 add_node / add_edge / add_conditional_edges UNCHANGED ...
    return graph.compile(checkpointer=checkpointer)
```

No node, edge, name, or ordering changes. The 7-node / 2-conditional-edge
structure test locks this (spec AC-8).

### 2.5 Saver factory + Runner core resume — `backend/app/runner/` [NEW + MODIFY]

**[NEW] `backend/app/runner/persistence.py`** — one place that builds the shared
`SqliteSaver` (long-lived, thread-shared, sync — spec D2), so lifespan and CLI
don't duplicate the construction:

```python
import sqlite3
from langgraph.checkpoint.sqlite import SqliteSaver

def build_saver(db_path: str) -> SqliteSaver:
    conn = sqlite3.connect(db_path, check_same_thread=False)   # worker thread + loop share it
    saver = SqliteSaver(conn)
    saver.setup()                    # idempotent DDL; owns its own schema (spec D1)
    return saver

def has_checkpoint(saver: SqliteSaver, thread_id: str) -> bool:
    return saver.get_tuple({"configurable": {"thread_id": thread_id}}) is not None
```

**[MODIFY] `backend/app/runner/core.py`** — `run_pipeline` accepts an optional
`checkpointer` + `thread_id`, and a `resume` flag. When a checkpointer is present
it passes `config={"configurable": {"thread_id": thread_id}}`; `resume=True`
streams `None` (LangGraph resume-from-checkpoint) instead of the seeded initial:

```python
def run_pipeline(document_path, *, recipient=None, on_progress=None,
                 checkpointer=None, thread_id=None, resume=False,
                 already_completed=None):
    config = {"configurable": {"thread_id": thread_id}} if checkpointer else None
    graph = build_graph(checkpointer=checkpointer)
    if resume:
        stream_input = None            # resume from last checkpoint (spec AC-11)
    else:
        stream_input = {"document_path": document_path,
                        "processing_started_at": _now_iso()}
    # Dedup seen-set (spec EC-1). VERIFIED: stream(None, "values") RE-EMITS the last
    # checkpointed node as its first yield, so a naive last_node=None would double-count
    # it. Seed `seen` from the rehydrated record's completed_nodes; fire on_progress ONLY
    # for nodes not yet seen. This also reconciles a node checkpointed-but-not-yet-persisted
    # before the kill (checkpoint is always >= persisted completed_nodes).
    seen = set(already_completed or ())
    final_state, last_node = {}, None
    for state in graph.stream(stream_input, stream_mode="values", config=config):
        final_state = state
        node = state.get("current_node")
        if node and node != last_node and node not in seen:   # ← added `node not in seen`
            last_node, _ = node, seen.add(node)
            if on_progress is not None:
                timing = (state.get("node_timings") or {}).get(node)
                on_progress(NodeProgress(node=node, index=node_index(node),
                                         total=TOTAL_STAGES, elapsed_seconds=timing))
        else:
            last_node = node
    # deliver_report_sync + processing_completed_at stamping: UNCHANGED
```

`build_graph()` is still called once per run (011 AC-6 preserved); passing
`checkpointer=None` yields today's behavior, so the CLI and mocked-graph tests are
unaffected. The initial-state keys remain the subset `{document_path,
processing_started_at}` (011 AC-6) on a fresh run. On a **fresh** run
`already_completed` is `None` → `seen` is empty → behavior is byte-identical to
011's progress loop (the extra `node not in seen` clause is always true for the
first entry into each node).

### 2.6 Worker resume flag — `backend/app/runner/worker.py` [MODIFY]

`submit()` gains a `resume` flag; `_run_one` threads `checkpointer`, `thread_id`,
and `resume` into `run_pipeline`. The worker is constructed with the shared saver:

```python
class PipelineWorker:
    def __init__(self, registry, saver=None, concurrency=1):
        self._saver = saver           # None when CHECKPOINTER_ENABLED is False
        # ... rest unchanged ...

    def submit(self, job_id: str, resume: bool = False) -> None:
        self._queue.put((job_id, resume))     # queue item is now a tuple

    def _run_one(self, item) -> None:
        job_id, resume = item
        rec = self._registry.get(job_id)
        if rec is None:
            return
        if not resume:
            rec.mark_running(_now_iso())       # fresh/queued run
            already = None
        else:
            rec.mark_running(rec._started_at or _now_iso())  # keep original start
            already = rec.snapshot_completed_nodes()  # under the record lock (spec EC-1 dedup)
        # ... _on_progress unchanged ...
        result = run_pipeline(rec.document_path, recipient=rec.recipient,
                              on_progress=_on_progress, checkpointer=self._saver,
                              thread_id=job_id, resume=resume, already_completed=already)
        # ... mark_terminal + publish: UNCHANGED (write-through now persists it)
```

The `_SENTINEL` sentinel handling adapts to the tuple queue (a sentinel item is
still detected by identity before unpacking).

### 2.7 Alembic scaffold + migration — `backend/alembic/` + `backend/alembic.ini` [NEW]

Introduce Alembic (tech-stack §3f) scoped to the **job store only** (spec D1,
AC-19). `alembic.ini` `sqlalchemy.url` is a placeholder; `env.py` overrides it
from `app.config.JOB_STORE_DB_PATH` (`sqlite:///<path>`) so config stays the one
source of truth. One initial migration creates the `jobs` table:

```
jobs(
  job_id TEXT PRIMARY KEY,
  document_path TEXT NOT NULL,
  recipient TEXT,
  status TEXT NOT NULL,
  submitted_at TEXT NOT NULL,
  started_at TEXT, finished_at TEXT, current_node TEXT,
  completed_nodes TEXT NOT NULL DEFAULT '[]',      -- JSON
  report_path TEXT,
  mcp_delivery_status TEXT NOT NULL DEFAULT '{}',  -- JSON
  error TEXT                                        -- JSON {kind,message} or NULL
)
-- index on submitted_at for prune()/nonterminal() ordering
CREATE INDEX ix_jobs_submitted_at ON jobs(submitted_at);
```

A small helper `app/runner/migrations.py::upgrade_to_head(db_path)` runs
`alembic upgrade head` programmatically (via Alembic's `command.upgrade` with a
`Config`) so the lifespan and tests migrate a fresh/temp DB without a shell step
(spec AC-18/19). On failure it raises (spec EC-8 — fail fast).

### 2.8 Lifespan wiring + startup recovery — `backend/app/api/main.py` [MODIFY]

The lifespan builds the durable stack and runs recovery before `yield` (spec D8):

```python
async def lifespan(application):
    loop = asyncio.get_running_loop()
    upgrade_to_head(_cfg.JOB_STORE_DB_PATH)                 # Alembic → head (AC-19, EC-8)
    store = JobStore(_cfg.JOB_STORE_DB_PATH)
    saver = build_saver(_cfg.CHECKPOINTER_DB_PATH) if _cfg.CHECKPOINTER_ENABLED else None
    registry = JobRegistry(store, saver, loop, max_jobs=_cfg.JOB_STORE_RETENTION_MAX)
    worker = PipelineWorker(registry, saver=saver, concurrency=_cfg.RUNNER_WORKER_CONCURRENCY)
    worker.start()
    if _cfg.STARTUP_RECOVERY_ENABLED:
        _recover(registry, store, saver, worker)            # spec AC-11..AC-15
    application.state.ctx = RunnerContext(registry=registry, worker=worker, loop=loop)
    try:
        yield
    finally:
        worker.stop()
        store.close()
        if saver is not None:
            saver.conn.close()       # release the checkpointer connection

def _recover(registry, store, saver, worker) -> None:
    """Idempotent (spec AC-15): enumerate store rows once and submit recoverable
    ones. Terminal jobs (completed/failed) are never touched (spec AC-14, D6)."""
    for row in store.nonterminal():                          # queued + running only
        rec = registry.get(row.job_id)                       # rehydrates a live record
        resumable = (row.status == JobState.running
                     and saver is not None
                     and has_checkpoint(saver, row.job_id))  # spec AC-11 vs AC-13
        if not resumable:
            rec.reset_for_rerun()                            # queued OR running-no-ckpt (AC-12/13)
        worker.submit(row.job_id, resume=resumable)
```

Idempotency (AC-15): recovery only submits rows found `queued`/`running`; once a
resumed/re-run job is picked up it is marked `running` then terminal, so a second
lifespan pass over the same store re-submits only what is still non-terminal (and
in the single-process model the worker has already advanced them). Recovery reads
the **store**, never checkpoint threads (spec D6); an orphan checkpoint thread
with no job row is thus never auto-run (spec EC-6).

### 2.9 CLI checkpointer opt-in — `backend/app/runner/__main__.py` [MODIFY]

Add an opt-in `--checkpoint` flag so local resume testing works without the
server (011 D2). Default off → today's checkpointer-less behavior:

```python
parser.add_argument("--checkpoint", action="store_true",
                    help="Enable the SQLite checkpointer for resume testing (feature 012)")
# ...
saver = build_saver(_cfg.CHECKPOINTER_DB_PATH) if args.checkpoint else None
result = run_pipeline(args.file, recipient=args.recipient, on_progress=_on_progress,
                      checkpointer=saver, thread_id=(str(uuid4()) if saver else None))
```

### 2.10 Tests — `backend/tests/` [NEW]

**Unit — job store & registry (`tests/unit/`):**
- `test_job_store.py`: upsert/get round-trip incl. JSON columns; `nonterminal()`
  filters terminal rows; `prune()` returns oldest victims and deletes them; JSON
  encode/decode of `completed_nodes`/`mcp_delivery_status`/`error` (spec AC-4).
- `test_registry_writethrough.py`: each `JobRecord` lock method write-throughs —
  read the row back on a fresh `JobStore` and see the mutation (AC-4); `_store=None`
  record still works (AC-7a); `get()` rehydrates a record from the store with a
  fresh buffer after the live dict is cleared (simulated restart, AC-2/3).
- `test_retention.py`: `add()` beyond `JOB_STORE_RETENTION_MAX` prunes oldest +
  calls `saver.delete_thread` for the victim; `GET` of a pruned id → `None`/404
  (spec D5, EC-7, 011 AC-22).

**Unit — checkpointer & core (`tests/unit/`):**
- `test_build_graph_checkpointer.py`: `build_graph()` (default) node/edge/name set
  is identical to a pinned expected structure (spec AC-8); `build_graph(saver)`
  runs a **fake/mocked** node set and writes a checkpoint row for the thread; latest
  checkpoint after END has `current_node == "report"` (spec AC-9).
- `test_run_pipeline_resume.py`: with a mocked graph, `resume=True` streams `None`
  and `resume=False` streams the seeded initial; `thread_id` is passed in `config`
  (spec AC-10, AC-11 stream form).

**Integration — recovery (`tests/integration/`):** all with a **mocked graph**
(spec AC-8 / §3 no real Ollama), temp DB paths (spec AC-18):
- `test_restart_get_survives.py`: submit → tear down app → rebuild app on same DB
  → `GET` returns persisted `JobStatus` (spec AC-2), byte-identical for a completed
  job (AC-3).
- `test_recover_running_resumes.py`: seed a `running` row + a checkpoint at node k;
  build app with recovery on; assert (a) node functions ≤ k are **not** re-invoked,
  (b) the resume re-emits node k but `completed_nodes` has **no duplicate** and ends as
  the full ordered `[1..7]` list, (c) job → completed (spec AC-11, EC-1 dedup).
- `test_recover_queued_fresh.py`: seed a `queued` row (no checkpoint) → fresh run to
  completed (spec AC-12); seed `running` with **no** checkpoint → fresh re-run
  (spec AC-13, EC-2).
- `test_recover_terminal_untouched.py`: `completed`/`failed` rows are not re-run;
  `GET` still returns them (spec AC-14, AC-17); recovery is idempotent across two
  builds (spec AC-15).
- `test_recover_missing_upload.py`: recovered job whose `document_path` is gone
  resolves to ingest-error/failed, not perpetual running (spec EC-3).
- `test_alembic_head.py`: `upgrade_to_head` on an empty temp file creates the
  `jobs` table with the expected columns (spec AC-19).

## 3. Dependency & Import Map

```
app/config.py                 [MODIFY] + JOB_STORE_DB_PATH, CHECKPOINTER_DB_PATH,
                                        CHECKPOINTER_ENABLED, JOB_STORE_RETENTION_MAX,
                                        STARTUP_RECOVERY_ENABLED (alias JOB_REGISTRY_MAX)
app/runner/store.py           [NEW]    JobRow, JobStore   (imports: sqlite3, json, models)
app/runner/persistence.py     [NEW]    build_saver, has_checkpoint  (imports: SqliteSaver)
app/runner/migrations.py      [NEW]    upgrade_to_head(db_path)      (imports: alembic.command)
app/runner/registry.py        [MODIFY] JobRecord write-through + from_row/reset_for_rerun;
                                        JobRegistry(store, saver, loop, max_jobs)
app/runner/core.py            [MODIFY] run_pipeline(..., checkpointer, thread_id, resume)
app/runner/worker.py          [MODIFY] PipelineWorker(registry, saver); submit(job_id, resume)
app/graph/builder.py          [MODIFY] build_graph(checkpointer=None)
app/api/main.py               [MODIFY] lifespan builds store/saver/registry + _recover()
app/runner/__main__.py        [MODIFY] --checkpoint opt-in
app/api/routes.py             [UNCHANGED] — still ctx.registry.get/add, ctx.worker.submit
app/runner/models.py          [UNCHANGED] — JobState/JobStatus/ProgressEvent reused
app/runner/events.py          [UNCHANGED] — JobEventBuffer stays ephemeral (D4)
alembic.ini, alembic/env.py, alembic/versions/0001_*.py   [NEW]
```

**Import-direction rule (unchanged from 011):** `store.py` and `persistence.py`
depend only on stdlib + `models` + the LangGraph saver; `registry.py` depends on
`store`; `worker.py`/`core.py` depend on `registry`/`persistence`/`builder`;
`api/main.py` is the only assembler. No route handler imports `store`/`sqlite3`
(spec AC-6); no `app/graph/nodes/*` import is added (011 AC-7 preserved).

## 4. Implementation Order (TDD — constitution §7)

1. **Config + `.gitignore`** (§2.1) — constants first; nothing depends on missing names.
2. **Alembic scaffold + migration + `migrations.py`** (§2.7); write `test_alembic_head.py`
   red → green. Foundation for the store.
3. **`store.py` + `test_job_store.py`** (§2.2) red → green — pure persistence, no app wiring.
4. **`persistence.py` + `test_build_graph_checkpointer.py`** (§2.5, §2.4) — saver factory
   and the one-line `builder.py` param; lock the AC-8 structure test first.
5. **`registry.py` write-through + rehydrate** (§2.3) with `test_registry_writethrough.py`,
   `test_retention.py` red → green.
6. **`core.py` + `worker.py` resume plumbing** (§2.5, §2.6) with `test_run_pipeline_resume.py`.
7. **Lifespan + `_recover()`** (§2.8) with the integration recovery suite (§2.10) red → green.
8. **CLI `--checkpoint`** (§2.9) — smallest, last.
9. Full `pytest` green (498 existing + new); then the **real end-to-end restart smoke**
   (per the project's run-real-smoke-before-continuation rule): start server, submit
   `tests/fixtures/sample.pdf`, kill mid-run, restart, confirm the job resumes from its
   last checkpoint and completes — the live proof AC-11 exists for.

## 5. Design Decisions & Rationale (traceable to spec §6)

- **Sync `sqlite3` + sync `SqliteSaver`, one shared locked connection each (spec D2,
  user-endorsed).** The hot writers are the 011 worker **thread** running a sync
  `graph.stream`; a sync store with `check_same_thread=False` + a lock and the sync
  saver match that model exactly. `aiosqlite`/`AsyncSqliteSaver` would force an async
  graph and refight the proven 011 thread design for zero benefit at concurrency = 1
  (spec EC-5). Alembic (also tech-stack §3f) **is** used, for migrations only.
- **Two files, two schema owners (spec D1).** Alembic owns `job_store.db`; LangGraph's
  `.setup()` owns `checkpoints.db`. Never one file — that invites migration-vs-auto-DDL
  collisions.
- **Write-through inside the `JobRecord` lock (spec AC-4).** Persisting in the same
  critical section that mutates the in-memory fields means a restart can never lose a
  mutation that a `GET` already observed; store and memory are always consistent.
- **Registry keeps live records in memory + mirrors to the store.** The live dict
  preserves each job's ephemeral `JobEventBuffer` (spec D4) for the process lifetime;
  the store is the durable mirror consulted only on a miss (rehydrate) — so the common
  path is as fast as 011 and only a cross-restart `GET` touches SQLite to rebuild a record.
- **`thread_id == job_id` (spec D3)** — one key ties a job row to its checkpoint thread,
  so recovery finds the checkpoint for a `running` job with `has_checkpoint(saver, job_id)`.
- **`build_graph(checkpointer=None)` default (spec D7)** — the entire, minimal `builder.py`
  change; the graph structure and all its tests are untouched (spec AC-8).
- **Recovery is store-driven and idempotent (spec D6, D8, AC-15)** — enumerate store rows
  in the lifespan, resume `running`+checkpoint, fresh-run `queued`/`running`-no-checkpoint,
  leave terminal; orphan checkpoint threads are ignored (spec EC-6).
- **Retention prunes both stores (spec D5)** — on insert, prune oldest job rows and delete
  their checkpoint threads so the two files never drift; a pruned id → 404 (011 AC-22).

## 6. Risks & Mitigations

- **R1 — LangGraph resume semantics differ from the mental model.** `stream(None, config)`
  resumes from the last *completed* super-step; a node interrupted mid-execution did not
  checkpoint and is re-run. *Mitigation:* all graph nodes are side-effect-free through
  `END` except `report`, whose writes are idempotent (009 D6, deterministic overwrite by
  `document_id`); delivery is post-`END` and outside the checkpointer (spec EC-9). The
  resume integration test (§2.10) asserts already-checkpointed nodes are not re-invoked.
- **R2 — SQLite cross-thread access.** A connection used from a thread it wasn't created on
  raises by default. *Mitigation:* `check_same_thread=False` + a per-store lock (`JobStore`).
  The **`SqliteSaver` is internally thread-safe** — verified it holds its own `lock`, so the
  recovery `get_tuple` (loop thread) and worker `put` (worker thread) over the one shared
  saver connection are already serialized; no extra wrapping needed (concurrency = 1 also
  serializes graph runs). Covered by `test_registry_writethrough.py` exercising the
  worker-thread + loop-read path.
- **R3 — `SqliteSaver.setup()` / Alembic on a locked or read-only file.** *Mitigation:*
  fail fast at startup with a clear error (spec EC-8); missing file is normal (created +
  migrated). WAL siblings (`-wal`/`-shm`) are git-ignored.
- **R4 — Recovery storm re-runs many jobs on a busy store at startup.** *Mitigation:*
  concurrency = 1 means recovered jobs queue and run one at a time; the retention cap bounds
  how many rows exist; terminal jobs are skipped (the vast majority after normal shutdown).
- **R5 — Double delivery on post-`END` crash (spec EC-9).** Accepted and documented; a
  duplicate Drive upload/email is a feature-010 concern, not a job failure. Not solved here.

## 7. Out of Scope for This Plan

Everything in `spec.md §5`: no `ContractState` slimming (001/003 own it); no MCP delivery
idempotency (010); no Postgres/multi-worker/horizontal scaling; no live-SSE recovery across
a restart (only status is durable); no "resume this job" HTTP endpoint (recovery is
startup-only); no auth/RBAC (PERMANENTLY CUT); no at-rest encryption of the DB files
(Phase 2); no scheduled retention job (Phase 2 — the cap here is insert-time only).

## 8. Constitution & Spec Traceability

- **§2 Fixed Architecture** — no node/edge added; the sole graph change is the optional
  `checkpointer` param on `build_graph()` (spec D7), and checkpointing is architecture the
  constitution (§6) and 001 (§1) explicitly anticipate. AC-8 locks the structure.
- **§4 State Typing** — the checkpointer serializes the `ContractState` `TypedDict` (001);
  the store persists the Pydantic-projected `JobStatus` shape at the boundary. Never mixed.
- **§6 State Minimality** — this is the feature that realizes "LangGraph checkpoints state
  after every step"; row size is bounded by 001's state, not widened here.
- **§7 Testing** — TDD order in §4: every store/registry/recovery test is written red first;
  the real restart smoke is run before the feature is called done (project rule).
- **§10 Spec-First Change** — no change to 001 is required; if implementation reveals one,
  001 is edited first with rationale before code.
- **§11 Git** — branch `feature/012-durable-persistence`; open only after spec + plan are
  approved and `tasks.md` exists; merge only when this plan's tests pass.
```
