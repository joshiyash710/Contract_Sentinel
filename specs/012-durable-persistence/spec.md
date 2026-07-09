# Feature 012 — Durable Persistence (SQLite Job Store + LangGraph Checkpointer)

## 1. Problem statement

Feature 011 (pipeline runner + FastAPI + SSE) ships an **in-memory** job
registry: `JobRegistry` holds an `OrderedDict` of `JobRecord`s, and the graph
runs with a **checkpointer-less** compiled graph (`graph.compile()` with no
`checkpointer=`). Two consequences were accepted for Phase 1 and explicitly
deferred to *this* feature:

1. **EC-9 (011): a process restart loses all jobs.** Every `JobRecord` lives
   only in RAM, so after a restart `GET /api/jobs/{id}` returns `404` for a job
   that was accepted seconds earlier — indistinguishable from a never-existed
   id. A local-Ollama run takes minutes (constitution §9); a laptop sleep, an
   `uvicorn --reload`, or a crash mid-run silently discards accepted work.
2. **No mid-pipeline recovery.** Because the graph is compiled without a
   checkpointer, an interrupted run cannot resume from its last completed node;
   the ~7 minutes of already-computed nodes are thrown away.

This feature removes both. It:

1. Swaps the in-memory `JobRegistry` seam for a **durable SQLite job store**, so
   job status (queued/running/completed/failed, progress, report path, delivery
   status, error) survives a process restart.
2. Compiles the graph **with a LangGraph SQLite checkpointer** (tech-stack §3a,
   `langgraph-checkpoint-sqlite`), so `ContractState` is durably persisted after
   every node — the exact mechanism constitution §6 and 001 §1 were written for.
3. On startup, **recovers interrupted runs**: a job left `running` is resumed
   from its last checkpoint; a job left `queued` is re-enqueued fresh.

### Position in the fixed architecture (constitution §2)

This feature adds **no graph node and no conditional edge**. The graph remains
exactly 7 nodes + 2 conditional edges. The only change to `app/graph/builder.py`
is that `build_graph()` gains an **optional `checkpointer` parameter** threaded
into `graph.compile(checkpointer=...)`; with the default `checkpointer=None` the
compiled graph is byte-for-byte the current behavior, so every existing
graph-structure test (node count, edge count, node names) is unaffected. This is
explicitly sanctioned architecture, not an extension of it: constitution §6
justifies State Minimality *"since LangGraph checkpoints state after every
step,"* and 001 §1 says the progressive state shape *"enables checkpointing and
recovery at any pipeline stage."* Checkpointing was designed in from the start;
011 merely postponed wiring it.

Per constitution §4, everything the store persists that crosses a system
boundary (the SQLite rows, the API responses) is projected through the existing
**Pydantic** `JobStatus`/`AnalyzeAccepted` models from 011; the internal graph
state the checkpointer serializes remains the `TypedDict` `ContractState` from
001, untouched. The two are never mixed — the checkpointer stores
`ContractState`; the job store stores the runner's `JobRecord` projection.

### Relationship to feature 011 (the seam this fills)

011 was written to make this swap **local**: AC-21 requires all registry access
to go through a single interface/object *"so a test can substitute a fake
registry without patching handler internals — the property that makes the
feature-012 persistence swap local."* This feature honors that: no route handler
in `app/api/routes.py` changes its registry-access shape; the durable store is a
drop-in behind the same `add`/`get`/record-mutation surface `JobRecord` /
`JobRegistry` expose today.

## 2. Inputs and outputs

### 2.1 What is persisted, and where (two distinct SQLite stores)

There are two separable persistence concerns; this feature keeps them in **two
separate SQLite database files** (D1) so their schema ownership never collides:

| Store | File (config) | Owns | Schema managed by |
| --- | --- | --- | --- |
| **Job store** | `JOB_STORE_DB_PATH` (default `data/job_store.db`) | The runner's durable `JobRecord` fields (the projection behind `JobStatus`) | This feature, via **Alembic** migrations (tech-stack §3f) |
| **Checkpointer** | `CHECKPOINTER_DB_PATH` (default `data/checkpoints.db`) | LangGraph's serialized `ContractState` per super-step, keyed by `thread_id` | **LangGraph's `SqliteSaver`** (its own `.setup()`; Alembic never touches it) |

The two are correlated by one key: **`thread_id == job_id`**. The job store row
for `job_id` and the checkpoint thread for `thread_id` describe the same run.

### 2.2 Job-store row schema (durable projection of `JobRecord`)

The job store persists exactly the fields `JobRecord` mutates today (011
`registry.py`) — the columns that `to_status()` projects into the boundary
`JobStatus`, plus the inputs needed to *resume* a run. It does **not** invent new
`ContractState` fields (constitution §4; 001 owns `ContractState`).

| Column | Source in 011 `JobRecord` | Purpose |
| --- | --- | --- |
| `job_id` (PK) | `job_id` | Identity; also the checkpointer `thread_id`. |
| `document_path` | `document_path` | Graph input; needed to **resume/re-run** after restart. |
| `recipient` | `recipient` | Delivery override; needed to re-run `deliver_report_sync`. |
| `status` | `_status` (`JobState`) | queued / running / completed / failed. |
| `submitted_at` | `submitted_at` | ISO-8601 UTC. |
| `started_at` | `_started_at` | ISO-8601 UTC, nullable. |
| `finished_at` | `_finished_at` | ISO-8601 UTC, nullable. |
| `current_node` | `_current_node` | Last node entered (progress). |
| `completed_nodes` | `_completed_nodes` | Ordered node names finished (JSON-encoded list). |
| `report_path` | `_report_path` | Resolved by `/report` (AC-13, never client-supplied). |
| `mcp_delivery_status` | `_mcp_delivery_status` | Delivery outcome map (JSON-encoded). |
| `error` | `_error` (`ErrorInfo`) | ingest-error or crash (JSON-encoded `{kind,message}`), nullable. |

The **`JobEventBuffer`** (011 `events.py`) is **not** persisted: it is a live
asyncio SSE fan-out bound to the running event loop and is inherently ephemeral
(D4). On load/restart a `JobRecord` is rehydrated with a **fresh empty buffer**.

### 2.3 Checkpointer input/output (LangGraph `ContractState` from 001)

The checkpointer serializes the whole `ContractState` `TypedDict` (001 §3) after
each super-step. This feature introduces **no new state field** and changes no
reducer (001 §4). It only changes *where the compiled graph writes its
checkpoints* — from nowhere (011) to `CHECKPOINTER_DB_PATH`. Row size is bounded
by `ContractState` size, which 001/003 govern (e.g. `extracted_text` is already
in-state there); bounding state size is **not** in this feature's scope.

Invocation contract: the runner invokes the graph with
`config={"configurable": {"thread_id": job_id}}` for both the initial run
(`graph.stream(initial, config=...)`) and the resume
(`graph.stream(None, config=...)` — LangGraph's resume-from-checkpoint form).

### 2.4 No change to the HTTP surface

The five endpoints from 011 (`/api/health`, `/api/analyze`,
`/api/jobs/{id}`, `/api/jobs/{id}/events`, `/api/jobs/{id}/report`) keep their
paths, methods, request bodies, and response models **unchanged**. The only
observable difference to a client is behavioral: after a restart, a `GET` for a
previously-accepted job returns its real status instead of `404`. `JobStatus`
and `ProgressEvent` (011 §2.3/§2.4) are unchanged.

## 3. Acceptance criteria

Each is written to become a test case directly. Tests use temp SQLite paths
(config-overridden) and a **fast mocked graph** where a real run is not the point
(mirrors 011 AC-8), so no test depends on real Ollama.

**Durable job store — survives restart**

- AC-1: After `POST /api/analyze` returns `202`, the job store file contains a
  row for that `job_id` with `status ∈ {queued, running}` — i.e. the record is
  written durably *before* (or atomically with) the `202`, not only in RAM.
- AC-2: Simulating a restart (tear down the app/worker, build a fresh app on the
  **same** `JOB_STORE_DB_PATH`) and then `GET /api/jobs/{job_id}` returns the
  persisted `JobStatus` (not `404`) — the direct removal of 011 EC-9.
- AC-3: A job driven to `completed` (mocked graph) has its terminal fields
  (`status=completed`, `finished_at`, `report_path`, `completed_nodes`,
  `mcp_delivery_status`, `error`) all present in the store row, and a
  post-restart `GET` returns a `JobStatus` byte-identical to the pre-restart one.
- AC-4: Every `JobRecord` mutation that 011 performs (`mark_running`,
  `record_progress`, `mark_terminal`) **write-through** persists to the store:
  after each, reading the row back (fresh connection) reflects the new value.
- AC-5: `GET /api/jobs/{unknown_id}` still returns `404`; a store miss is
  indistinguishable from a never-existed id (unchanged from 011 AC-17).

**Registry seam preserved (011 AC-21 honored)**

- AC-6: The route handlers in `app/api/routes.py` access jobs through the **same
  interface** as 011 (the registry/store object on `app.state.ctx`); a test can
  inject a fake store without patching handler internals. No handler constructs
  a SQLite connection directly.
- AC-7: The in-memory registry from 011 either (a) still satisfies the same
  interface for use in unit tests, or (b) is fully replaced by the durable store
  used with a temp file — either way there is exactly **one** store seam, and a
  structural test asserts handlers import only that seam.

**LangGraph checkpointer**

- AC-8: `build_graph()` called with `checkpointer=None` (its default) compiles a
  graph whose node set, edge set, and node names are **identical** to 011's — a
  regression test locks the 7-node/2-conditional-edge structure against this
  change.
- AC-9: `build_graph(checkpointer=<saver>)` compiles a graph that, when run with
  `config={"configurable":{"thread_id": t}}`, writes at least one checkpoint row
  for thread `t` to `CHECKPOINTER_DB_PATH`; after the run reaches `END`, the
  latest checkpoint's `current_node` reflects the final node (`report`).
- AC-10: The runner invokes the graph with `thread_id == job_id` (assert via a
  spy/mock on `stream`), so each job's checkpoints are isolated per thread; two
  concurrent-in-store jobs never share a checkpoint thread.

**Startup recovery of interrupted runs**

- AC-11: A job persisted as `running` with an existing checkpoint at node *k*
  (< 7) is, on startup, **re-enqueued and resumed** — the runner calls
  `graph.stream(None, config={thread_id})` (resume form, not a fresh
  `stream(initial, ...)`), and the job proceeds to `completed` without re-running
  the nodes already checkpointed (verified by a spy: node functions ≤ *k* are not
  re-invoked; the resumed stream continues from *k+1*).
- AC-12: A job persisted as `queued` (never started, no checkpoint) is, on
  startup, re-enqueued as a **fresh** run (`stream(initial, ...)` seeded from the
  persisted `document_path` + a new `processing_started_at`) and reaches
  `completed`.
- AC-13: A job persisted as `running` but with **no** checkpoint (crashed before
  the first checkpoint was written) is recovered as a **fresh** re-run from
  `document_path` (falls back to AC-12 behavior), not left stuck in `running`.
- AC-14: Jobs persisted as `completed` or `failed` are **not** re-run on startup;
  their rows and status are untouched and remain retrievable via `GET`.
- AC-15: Startup recovery is **idempotent**: building the app twice in a row over
  the same store does not double-enqueue or duplicate any job.

**Delivery + error semantics unchanged (011 EC-1/2/3 still hold, now durable)**

- AC-16: An ingest-error run (011 EC-1) persists `status=completed` with `error`
  populated from `ingest_error`; a post-restart `GET` still shows that.
- AC-17: A crashed run (011 EC-2) persists `status=failed` with an `ErrorInfo`;
  it is **not** resumed on a later startup (it is terminal, AC-14), and one
  failed job never corrupts the store for other jobs.

**Config & isolation**

- AC-18: With no persistence configured to a real path (tests), the store and
  checkpointer both target temp files under the test's tmp dir; nothing is
  written to the repo's `data/` during tests.
- AC-19: The job-store schema is created/upgraded via **Alembic** (a migration
  exists and `alembic upgrade head` on an empty file yields the expected table);
  the checkpointer schema is created via LangGraph's `SqliteSaver.setup()`, never
  by Alembic.

## 4. Edge cases

- **EC-1 — Restart with an in-flight `running` job, checkpoint present:**
  Resume from last checkpoint (AC-11). Already-completed node **functions are
  not re-executed** (verified against LangGraph 1.2.8: replay resumes forward
  from the last checkpoint). However, with `stream_mode="values"` the resumed
  `stream(None, ...)` **re-emits the last checkpointed node's state as its first
  yield**, then continues with the genuinely new nodes. The runner therefore
  MUST dedup progress against the already-recorded `completed_nodes` (seed a
  seen-set from the rehydrated record) so that first re-emitted node is neither
  double-appended to `completed_nodes` nor re-published as an SSE event. Because
  a node is checkpointed *before* the runner records its progress, the checkpoint
  is always at or ahead of the persisted `completed_nodes`; this same re-emit +
  dedup therefore also **reconciles** a node that was checkpointed but whose
  progress-write did not land before the kill — the final `completed_nodes` is
  the correct full ordered list, with no duplicates and no gaps.
- **EC-2 — Restart with `running` job but no/partial checkpoint:** LangGraph
  wrote nothing for that thread (killed inside the first node). Treat as a fresh
  re-run from `document_path` (AC-13). A partially-written checkpoint that
  LangGraph itself rejects on load is treated the same as "no checkpoint."
- **EC-3 — Upload file gone at recovery:** A `running`/`queued` job is recovered,
  but its `document_path` no longer exists on disk (e.g. `data/uploads` was
  cleaned — Phase-1 disk hygiene is manual per 011 §5). Ingest then fails; the
  job resolves to `completed`-with-ingest-error (011 EC-1) or `failed`, never a
  perpetual `running`. No crash on startup.
- **EC-4 — SSE backlog is not durable:** After a restart, a client reconnecting
  to `/events` for a resumed job sees only progress events emitted **after** the
  resume (fresh buffer, D4). Pre-restart progress frames are gone, but the job
  **status** (`completed_nodes`, `current_node`) is fully durable via `GET`. The
  terminal `completed`/`failed` event still fires once on the resumed run
  (011 AC-9/10/11 semantics hold for the resumed segment).
- **EC-5 — Concurrent write-through under the single worker (D2 of 011,
  concurrency = 1):** The worker thread persists `record_progress` after each
  node while a request-loop `GET` reads the same row. The store's access must be
  thread-safe (a single-writer sqlite connection guarded by a lock, or an
  equivalent) so a concurrent read never sees a torn row and a write from the
  worker thread never raises `SQLite objects created in a thread…`.
- **EC-6 — Checkpoint DB present, job-store row absent (or vice versa):** The two
  files can drift if one is deleted out-of-band. Recovery keys off the **job
  store** as the source of truth: an orphan checkpoint thread with no job row is
  ignored (never auto-run — there is no job to attach it to); a job row whose
  checkpoint is missing falls back to fresh re-run (EC-2). Neither state crashes
  startup.
- **EC-7 — Store growth / retention:** The durable store no longer evicts on an
  in-memory cap the way 011 D5 did. Retention is governed by
  `JOB_STORE_RETENTION_MAX` (D5): on insert, rows beyond the cap are pruned
  oldest-first by `submitted_at`, and the pruned job's checkpoint thread is
  deleted too so the two stores do not drift. A `GET` on a pruned id returns
  `404` (consistent with 011 AC-22 / EC-9). Set the cap high (default 500) so a
  single local session never prunes an in-session job.
- **EC-8 — Corrupt / unreadable store file at startup:** If `JOB_STORE_DB_PATH`
  exists but is not a valid SQLite DB (or Alembic cannot bring it to head), the
  app fails fast at startup with a clear error rather than silently starting with
  a half-initialized store. (A missing file is normal — it is created and
  migrated to head.)
- **EC-9 — Resume re-runs the terminal node / delivery:** The checkpointer covers
  only the graph (through `END`); `deliver_report_sync` runs **after** `END`,
  outside the checkpointer. A job that crashed *after* `END` but *before* being
  marked `completed` would be `running` with a checkpoint at `END`; resuming
  `stream(None, ...)` yields no further node updates, and the runner proceeds to
  delivery again. Re-delivery is at worst a duplicate Drive upload / email
  (feature 010's concern, idempotency not guaranteed there); this is an accepted,
  documented consequence, not a job failure. Report-file writes are idempotent
  (009 D6, deterministic overwrite by `document_id`), so re-reaching `report`
  overwrites in place.
- **EC-10 — `alembic`/`SqliteSaver` on a read-only or full disk:** A write
  failure in either store surfaces as a `500`/logged error for that operation;
  it does not corrupt the other store. (Not specially recovered in Phase 1.)

## 5. Out of scope

- **The 7 graph nodes and their edges** — unchanged (constitution §2). The only
  `builder.py` change is the optional `checkpointer` param on `build_graph()`.
- **Bounding `ContractState` size for checkpoint rows** — owned by 001/003
  (e.g. `extracted_text` living in state). This feature persists whatever state
  001 defines; it does not slim it.
- **MCP delivery idempotency / dedup on resume** — owned by feature 010. EC-9's
  possible duplicate delivery is documented, not solved here.
- **Postgres / multi-worker / horizontal scaling** — tech-stack §3f fixes SQLite
  for Phase 1; the store still assumes a **single Uvicorn worker** (a second
  worker process would contend on the SQLite files and on run ownership).
  Multi-worker correctness is out of scope, consistent with 011 §5.
- **Live SSE recovery across a restart** — only job *status* is durable, not the
  in-memory SSE backlog (EC-4, D4). A reconnecting client resyncs via `GET` +
  the resumed stream.
- **A "resume this job" HTTP endpoint / manual re-run API** — recovery is
  automatic at startup only. No new endpoint is added (§2.4).
- **Authentication / authorization / RBAC / multi-tenancy** — PERMANENTLY CUT
  (constitution §2); unchanged by adding a database.
- **Phase 2 concerns** — PrivacyAgent, encryption at rest (the store is
  **plaintext** SQLite; encryption at rest is Phase 2), Zero-Storage mode, audit
  log, retention *policy* as a scheduled cleanup job. `JOB_STORE_RETENTION_MAX`
  here is a simple insert-time cap, **not** the Phase-2 scheduled retention job.
- **Encrypting or access-controlling `data/checkpoints.db` / `data/job_store.db`**
  — both are git-ignored local files; at-rest protection is Phase 2.

## 6. Resolved decisions

Per the project's preference for inline decisions with rationale over deferred
open questions, the design choices are recorded here. Nothing below is left for
`plan.md` to re-litigate.

- **D1 — Two separate SQLite files, not one.** The job store
  (`data/job_store.db`, Alembic-managed) and the LangGraph checkpointer
  (`data/checkpoints.db`, `SqliteSaver.setup()`-managed) use **separate files**.
  Rationale: LangGraph's saver auto-creates and owns its `checkpoints`/`writes`
  tables; letting Alembic and `SqliteSaver` share one file invites migration vs.
  auto-DDL collisions. Two files keep each library the sole owner of its schema.
  Both paths are configurable (§6.1).

- **D2 — Synchronous SQLite access (`sqlite3` + `SqliteSaver`), not async.** The
  heavy writers are the **background worker thread** (011 D4): `record_progress`
  fires once per node and `graph.stream` is synchronous inside that thread. A
  synchronous store (a single `sqlite3` connection with
  `check_same_thread=False`, guarded by a lock) and LangGraph's **sync**
  `SqliteSaver` (matching the sync `graph.stream`) are the natural fit;
  `AsyncSqliteSaver`/`aiosqlite` would force the graph to run async and fight the
  proven 011 thread model for no benefit at concurrency = 1. Tech-stack §3f lists
  `aiosqlite`; it is not required for correctness here and is not adopted for the
  hot path (noted as a deliberate divergence with rationale — spec-first,
  constitution §10 spirit). Alembic (also §3f) **is** used, for schema migration.

- **D3 — `thread_id == job_id`.** One key correlates a job-store row with its
  checkpoint thread, so recovery can find the checkpoint for a `running` job and
  resume it. No separate mapping table.

- **D4 — SSE buffer stays in-memory (ephemeral).** Only durable job *status* is
  persisted; the `JobEventBuffer` is rebuilt empty on load. Rationale: it is
  bound to the running asyncio loop and cannot be meaningfully serialized;
  post-restart clients resync via `GET` + the resumed stream (EC-4).

- **D5 — Retention: insert-time cap, prune oldest, prune its checkpoint too.**
  Replaces 011 D5's in-memory OrderedDict eviction with a durable equivalent:
  keep at most `JOB_STORE_RETENTION_MAX` rows (default 500), prune oldest by
  `submitted_at` on insert, and delete the pruned job's checkpoint thread so the
  two files never drift. A `GET` on a pruned id → `404` (011 AC-22 preserved).
  This is a simple cap, **not** the Phase-2 scheduled retention job (§5).

- **D6 — Job store is the source of truth for recovery.** Startup enumerates
  **job-store** rows, not checkpoint threads: `running` → resume (or fresh re-run
  if no checkpoint), `queued` → fresh, `completed`/`failed` → leave. Orphan
  checkpoint threads with no job row are ignored (EC-6). This keeps recovery
  deterministic and driven by the store this feature owns.

- **D7 — `build_graph(checkpointer=None)` default preserves 011 behavior.** The
  checkpointer is an **optional injected** parameter, not built inside the graph
  module, so: (a) existing graph tests and the CLI keep compiling a
  checkpointer-less graph unchanged; (b) the runner/lifespan owns the saver's
  lifecycle (one saver, `.setup()` once at startup); (c) the CLI
  (`python -m app.runner`, 011 D2) may opt into a checkpointer for local resume
  testing but defaults to none. This is the entire, minimal change to
  `builder.py`.

- **D8 — Startup recovery runs inside the FastAPI lifespan, before serving.** The
  same lifespan that builds the store + saver + worker (011 `app/api/main.py`)
  performs recovery enumeration and re-enqueues recoverable jobs onto the
  existing worker, then yields. Rationale: reuses 011's worker/lifespan wiring;
  recovery is just "enumerate the store and submit," not a new subsystem.
  Idempotent per AC-15.

### 6.1 Configuration

New named constants in `app/config.py`, matching the existing pattern (§6.1 of
011; module-level constants, `os.getenv` where a runtime override is wanted).

| Knob | Purpose | Default |
| --- | --- | --- |
| `JOB_STORE_DB_PATH` | Alembic-managed durable job store (D1) | `data/job_store.db` (backend-relative, mirroring `REPORT_OUTPUT_DIR`) |
| `CHECKPOINTER_DB_PATH` | LangGraph `SqliteSaver` file (D1) | `data/checkpoints.db` |
| `CHECKPOINTER_ENABLED` | Compile the graph with the checkpointer (D7); tests may disable | `True` |
| `JOB_STORE_RETENTION_MAX` | Insert-time row cap; prune oldest + its checkpoint (D5) | `500` |
| `STARTUP_RECOVERY_ENABLED` | Run interrupted-job recovery in lifespan (D8); tests may disable | `True` |

The 011 knob `JOB_REGISTRY_MAX` is superseded by `JOB_STORE_RETENTION_MAX`
(D5); the plan decides whether to keep the old name as an alias or migrate call
sites. `data/job_store.db` and `data/checkpoints.db` are added to `.gitignore`.

## 7. Open questions

None. Every design choice above is resolved inline (§6) with rationale, per the
project's spec convention. This spec is considered final and ready for `plan.md`.
