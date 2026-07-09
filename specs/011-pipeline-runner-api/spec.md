# Feature 011 — Pipeline Runner + FastAPI API Layer + SSE Progress Streaming

## 1. Problem statement

The fixed 7-node LangGraph pipeline (features 003–009) and the post-terminal
MCP delivery step (feature 010) are complete, but **nothing invokes them**.
`build_graph()` and `deliver_report_sync()` are only ever called from tests —
there is no application entry point that accepts a contract, drives it through
the graph to `END`, and then delivers the report.

This feature builds that ignition layer. It is the **outer orchestration
boundary** described by tech-stack §3e ("Backend API Layer": `fastapi`,
`uvicorn`, `sse-starlette`). Its job is:

1. Accept an uploaded contract (PDF/DOCX) over HTTP.
2. Persist it to disk as a file reference (constitution §6 — state minimality).
3. Seed the minimal initial `ContractState` and invoke the compiled graph.
4. Stream per-node progress to the client while the (slow, local-Ollama)
   pipeline runs (constitution §9 — local-model latency).
5. On terminal state, invoke the existing `deliver_report_sync()` step.
6. Expose the resulting report and delivery status for retrieval.

### Position in the fixed architecture (constitution §2)

This feature adds **no graph node and no conditional edge**. It does not touch
`app/graph/builder.py` or any file under `app/graph/nodes/`. It mirrors the
architectural pattern established by feature 010 (MCP delivery): an outer
step that *calls* the compiled graph rather than living inside it. The graph
remains exactly 7 nodes + 2 conditional edges. The runner is to the graph what
`main()` is to a library — the caller, not a member.

Per constitution §4, everything crossing the HTTP boundary uses **Pydantic**
models for runtime validation; the internal graph state remains the `TypedDict`
`ContractState` from 001 and is never replaced or wrapped by Pydantic.

### Scope boundary with feature 012 (deferred)

Job state lives in an **in-memory registry** for this feature. Durable
persistence — SQLite via `aiosqlite`/`alembic` (tech-stack §3f) **and** the
LangGraph SQLite checkpointer (tech-stack §3a) — is explicitly deferred to a
future **feature 012**. Consequence, accepted for Phase 1's single-user local
scope: job records and in-flight runs do not survive a process restart, and the
API is single-process. This feature must be written so that swapping the
in-memory registry for a persistent store in 012 is a localized change (the
registry is accessed through one interface, not sprinkled across handlers).

## 2. Inputs and outputs

### 2.1 Relationship to `ContractState` (001)

The runner is the sole producer of the graph's **initial** state and the sole
consumer of its **terminal** state. It does not introduce any new field into
`ContractState` and does not conflict with any field 001 already defines.

**Initial state the runner seeds** (only keys no node owns as its input):

| Key (from 001) | Value the runner sets | Why the runner, not a node |
| --- | --- | --- |
| `document_path` | Absolute path to the saved upload | IngestAgent reads `state["document_path"]`; it is the graph's sole required input (matches `graph.invoke({"document_path": ...})` in the integration tests). |
| `processing_started_at` | ISO-8601 UTC timestamp at run start | 001 §4 lists this as pipeline-level metadata; it is **read** by the report renderer but **written by no node** (confirmed in `markdown_renderer.py` / `ingest_agent.py`). If the runner does not seed it, the report's elapsed-time line renders "unknown". |

All other `ContractState` keys are produced by the nodes themselves
(IngestAgent generates `document_id`, `original_filename`, `uploaded_at`, etc.)
and MUST NOT be pre-seeded by the runner.

**Terminal state the runner reads** (after `END`):

- `report_path: Optional[str]` — path to the Markdown report (JSON sibling at
  the same stem). Used for report retrieval and passed implicitly to delivery.
- `ingest_error: Optional[Dict[str, str]]` — if set, the run short-circuited at
  Node 1; the job is *completed-with-ingest-error*, not *crashed* (see §4).
- `mcp_delivery_status: Dict[str, MCPDeliveryInfo]` — populated by
  `deliver_report_sync()` after the graph, surfaced in job status.
- `current_node`, `node_timings`, `error_count`, `processing_completed_at` —
  surfaced as progress/telemetry in job status where useful.

### 2.2 HTTP surface (all request/response bodies are Pydantic — constitution §4)

| Method & path | Purpose | Request | Response |
| --- | --- | --- | --- |
| `POST /api/analyze` | Submit a contract; start a run | `multipart/form-data`: the file, plus optional `recipient` (Gmail override, passed to `deliver_report_sync(recipient=...)`) | `202 Accepted` + `AnalyzeAccepted { job_id, status, submitted_at }` |
| `GET /api/jobs/{job_id}` | Poll job status | — | `JobStatus` (see §2.3) |
| `GET /api/jobs/{job_id}/events` | SSE progress stream | — | `text/event-stream` of `ProgressEvent`s (see §2.4) |
| `GET /api/jobs/{job_id}/report?format=md\|json` | Download the finished report | — | The report file (`text/markdown` or `application/json`), or `409` if not ready |
| `GET /api/health` | Liveness | — | `{ status: "ok" }` |

### 2.3 `JobStatus` (Pydantic response model)

```
job_id: str
status: JobState                      # queued | running | completed | failed
current_node: Optional[str]           # last node the graph entered (progress)
completed_nodes: List[str]            # ordered node names already finished
submitted_at: str                     # ISO-8601 UTC
started_at: Optional[str]
finished_at: Optional[str]
report_available: bool                # True iff report_path exists on disk
mcp_delivery_status: Dict[str, MCPDeliveryInfo]   # empty until delivery runs
error: Optional[ErrorInfo]            # set on ingest-error OR crash (see §4)
```

`JobState` is a Pydantic/`Enum` boundary type owned by this feature (it is a
job-lifecycle concept, distinct from the graph's `ValidationStatus` /
`MCPDeliveryStatus` in 001 — do not reuse those). `MCPDeliveryInfo` is imported
from 001 unchanged.

### 2.4 `ProgressEvent` (SSE payload)

```
event: "progress" | "completed" | "failed"
job_id: str
node: Optional[str]                   # node just finished (progress events)
index: Optional[int]                  # this node's position (see mapping below)
total: Optional[int]                  # total nodes THIS run will traverse
elapsed_seconds: Optional[float]      # from node_timings for that node
final: Optional[JobStatus]            # present only on completed/failed
```

Progress events are derived from `graph.stream(...)`: each yielded node update
becomes one `progress` SSE event. When the graph reaches `END` and delivery
finishes, a single terminal `completed` (or `failed`) event carries the full
`JobStatus`, then the stream closes. Each SSE frame sets the named `event:` field
(`progress`/`completed`/`failed`) in addition to the JSON `data:` payload, so a
browser `EventSource.addEventListener(...)` can dispatch by event name.

**Progress indexing over a branching graph.** The graph does not always emit 7
updates: `route_on_risk` yields an update for **either** `redline` **or**
`skip_redline` (both are logical Node 6), and an ingest-error short-circuits to
`END` after `ingest_agent` (one update). The runner therefore holds a canonical
`node_name → index` map where `redline` and `skip_redline` **both resolve to
index 6**, and reports `total` per run (≤ 7) to reflect the branch/
short-circuit actually taken. `index` is for driving a progress bar only;
AC-9's "one event per node actually entered" remains the authoritative event
count. The map lives in one place so the plan does not re-derive it per handler.

**Event delivery mechanism.** The graph runs synchronously (`graph.stream`) in a
worker thread, while SSE consumers are async and may subscribe **late** (after
the run started, or after it finished — EC-7, AC-11). The runner therefore
requires a **per-job, thread-safe, replay-capable event buffer**: the worker
appends events to it; each SSE subscriber replays already-buffered events (incl.
a terminal event that already fired) and then follows live ones, with no
lost-wakeup gap between the registry read and the subscription. The plan must
not substitute a lossy fire-and-forget broadcast.

## 3. Acceptance criteria

Each is written to become a test case directly.

**Submission & lifecycle**

- AC-1: `POST /api/analyze` with a valid `.pdf` returns `202` and a
  `job_id`; an immediate `GET /api/jobs/{job_id}` returns status `queued` or
  `running` (never `completed` synchronously).
- AC-2: `POST /api/analyze` with a valid `.docx` is accepted identically.
- AC-3: The uploaded bytes are written to disk under the configured upload
  directory, and the path passed to the graph equals `state["document_path"]`
  (i.e. the runner seeds exactly `document_path` + `processing_started_at` and
  nothing else in the initial state).
- AC-4: After the run completes, `GET /api/jobs/{job_id}` returns status
  `completed` with `report_available == true` and `finished_at` set.
- AC-5: `POST /api/analyze` with a `recipient` form field results in
  `deliver_report_sync` being called with that `recipient` (assert via mock);
  omitting it falls back to the configured default recipient.

**Graph invocation isolation**

- AC-6: The runner calls `build_graph()` exactly once per run and invokes it
  with an initial state whose keys are a subset of `{document_path,
  processing_started_at}` — proving no node-owned key is pre-seeded.
- AC-7: The runner never imports from `app/graph/nodes/*` except via the public
  `build_graph()` / `deliver_report_sync()` entry points; `builder.py` is
  unchanged by this feature (structural/import test).
- AC-8: A run whose graph invocation is fully mocked still produces a correct
  `completed` `JobStatus`, proving the runner does not depend on real Ollama.

**Progress streaming (SSE)**

- AC-9: `GET /api/jobs/{job_id}/events` returns `Content-Type:
  text/event-stream` and emits at least one `progress` event per node the graph
  actually entered, in pipeline order, followed by exactly one terminal
  (`completed`/`failed`) event, after which the connection closes.
- AC-10: The terminal SSE event's `final` field is a complete `JobStatus`
  equal to what `GET /api/jobs/{job_id}` returns at that moment.
- AC-11: Opening the SSE stream for an already-finished job immediately emits
  the terminal event and closes (no hang), rather than waiting forever.

**Report retrieval**

- AC-12: `GET /api/jobs/{job_id}/report?format=md` on a completed job returns
  the Markdown file with `text/markdown`; `?format=json` returns the JSON
  sibling with `application/json`.
- AC-13: The report endpoint resolves the file **only** from the job's recorded
  `report_path` (and its `.json` sibling) — it never accepts or joins a
  client-supplied path (path-traversal is structurally impossible).
- AC-14: Requesting the report of a job that is not yet `completed` returns
  `409 Conflict`, not a partial/empty file.

**Validation & not-found**

- AC-15: `POST /api/analyze` with an unsupported extension (e.g. `.txt`) is
  rejected at the boundary with `400` and no job is created. (This mirrors
  IngestAgent's `ALLOWED_EXTENSIONS = {.pdf, .docx}`; the boundary rejects
  early so an obviously-wrong upload never spawns a run.)
- AC-16: `POST /api/analyze` with a file exceeding the configured max upload
  size returns `413`.
- AC-17: `GET /api/jobs/{unknown_id}` (and its `/events`, `/report`) returns
  `404`.
- AC-18: `GET /api/health` returns `200 {"status": "ok"}`.

**In-memory registry & concurrency**

- AC-19: Two submissions receive two distinct `job_id`s whose statuses are
  tracked independently.
- AC-20: The graph run executes off the request-handling event loop, on a
  **single shared background worker** (not a per-request thread), so
  `POST /api/analyze` returns its `202` without blocking on the pipeline —
  verified by the response arriving while a deliberately-slowed mock graph is
  still "running". A second submission while the worker is busy is recorded as
  `queued` and runs after the first (concurrency = 1, §6 decision D4).
- AC-21: Registry access goes through a single registry interface/object (one
  seam), so a test can substitute a fake registry without patching handler
  internals — the property that makes the feature-012 persistence swap local.
- AC-22: With the eviction cap set to `N`, submitting more than `N` jobs evicts
  the oldest by insertion order; a `GET /api/jobs/{evicted_id}` then returns
  `404`, indistinguishable from a never-existed id (consistent with EC-9).
- AC-23: A CORS preflight (`OPTIONS`) from an allowed localhost origin (e.g.
  `http://localhost:5173`) receives the `Access-Control-Allow-Origin` header, so
  a browser `EventSource`/`fetch` from the frontend dev server is not blocked; an
  origin absent from the configured allowlist does not receive it.

## 4. Edge cases

- **EC-1 — IngestAgent short-circuit (not a crash):** When the graph sets
  `ingest_error` and routes straight to `END` (unsupported format that slipped
  past the boundary, corrupted file, parse timeout), the run reaches `END`
  normally. The job is marked `completed` with `report_available` per whether
  Node 7 still wrote a report, and `error` populated from `ingest_error`. This
  is distinct from a crashed run (EC-2).
- **EC-2 — Unexpected exception during `graph.invoke`/`stream`:** Any exception
  the graph does not handle internally marks the job `failed` with an
  `ErrorInfo`, is logged, and closes the SSE stream with a `failed` terminal
  event. One failed job never affects other jobs in the registry.
- **EC-3 — Delivery fails but pipeline succeeded:** `deliver_report_sync` never
  raises (feature 010 guarantee); a FAILED channel surfaces in
  `mcp_delivery_status`. The job is still `completed` (analysis succeeded); the
  delivery outcome is reported, not treated as a job failure.
- **EC-4 — Delivery disabled by config:** `deliver_report_sync` returns
  `{"mcp_delivery_status": {}}`; the job completes with an empty delivery map.
  No error.
- **EC-5 — Empty / zero-byte upload:** Rejected at the boundary with `400`
  before a job is created (an empty file cannot be a valid PDF/DOCX and would
  only produce an ingest error downstream).
- **EC-6 — Client disconnects mid-SSE:** The server stops writing to that
  stream but the underlying run continues to completion; its final status
  remains retrievable via `GET /api/jobs/{job_id}`. The run is not cancelled by
  a dropped event connection.
- **EC-7 — SSE opened before the run starts producing events:** The stream must
  emit already-known state (e.g. `queued`) and then live events, without
  dropping the terminal event if the run finishes between registry read and
  stream subscription (no lost-wakeup race).
- **EC-8 — Report file missing at retrieval despite `report_path` set:** If
  Node 7 recorded a path but the file is absent on disk, `/report` returns
  `404` (not `200` with empty body); `report_available` in status reflects the
  on-disk truth, not merely that `report_path` is non-None.
- **EC-9 — Process restart with in-flight/finished jobs:** All job records are
  lost (in-memory only). Subsequent `GET /api/jobs/{id}` returns `404`. This is
  the accepted Phase-1 limitation that feature 012 removes; it must be noted in
  the API docs/response semantics, not silently surprising.
- **EC-10 — Duplicate/concurrent submissions of the same file:** Each
  submission is an independent job with its own `job_id` and its own saved copy
  on disk (IngestAgent generates a fresh `document_id` per run, so report files
  do not collide across jobs). No dedup is attempted.
- **EC-11 — Long run vs. Ollama latency (constitution §9):** The runner must
  not impose its own short wall-clock timeout that pre-empts a legitimately slow
  local model; per-node timeouts already live in the nodes' own config. Per
  decision **D6**, no runner-level wall-clock cap is added for Phase 1.

## 5. Out of scope

- **Durable persistence & recovery** — SQLite job store (`aiosqlite`/`alembic`)
  and the LangGraph SQLite checkpointer for mid-pipeline resume. Owned by the
  future **feature 012**. This feature is in-memory and non-resumable by design.
- **The 7 graph nodes and their edges** — owned by features 003–009; this
  feature only *calls* `build_graph()`. No node/edge is added or modified
  (constitution §2).
- **MCP delivery mechanics** — Drive/Gmail transport, OAuth, retries — owned by
  feature 010. This feature only invokes `deliver_report_sync()` and reports its
  result.
- **Report content/formatting** — owned by feature 009. This feature serves the
  already-written report bytes; it does not render or alter them.
- **Authentication / authorization / multi-tenancy / RBAC** — PERMANENTLY CUT
  (constitution §2). No login, API-key framework, or per-user isolation is in
  scope. (Binding posture is fixed by decision D1; auth *features* remain cut.)
- **A frontend / UI** — this feature exposes the HTTP + SSE contract the future
  `frontend/` will consume; it ships no UI.
- **Phase 2 concerns** — PrivacyAgent, encryption at rest, Zero-Storage mode,
  audit log, retention policy — all DEFERRED (constitution §2). In particular,
  no scheduled cleanup of saved uploads/reports is built here (that is the Phase
  2 retention policy); disk hygiene for Phase 1 is manual.
- **Horizontal scaling / multi-worker deployment** — the in-memory registry
  assumes a single Uvicorn worker for Phase 1; multi-worker correctness depends
  on 012's shared store.

## 6. Resolved decisions

The six open questions from the review are resolved here as recorded decisions,
per the project's preference for inline decisions with rationale over deferred
questions. Nothing in this section is left for the plan to re-litigate.

- **D1 — Binding & auth: localhost-only, no auth.** Uvicorn binds to
  `127.0.0.1` only; no login, API key, or token. Rationale: Phase-1
  single-user local scope; auth/RBAC is PERMANENTLY CUT (constitution §2). Host
  and port are configurable (§6.1) so the value is not hardcoded.

- **D2 — CLI runner is in scope.** Feature 011 ships a thin headless CLI
  (`python -m app.runner <file>`, exact entry name is a plan detail) that runs
  the graph + `deliver_report_sync` and prints the result, with **no HTTP**.
  Rationale: it makes the pipeline runnable for local testing and finally lets
  the feature-010 OAuth delivery smoke be exercised end-to-end without a server
  (noted still-pending on this box, where `qwen3:14b` OOMs). **Constraint:** the
  CLI and the API handlers MUST call the *same* runner core function — no forked
  orchestration logic — so the two entry points cannot drift. (Enforceable via
  the AC-8 runner-core test being invoked from both paths.)

- **D3 — Async-only; no synchronous analyze endpoint.** Submission returns a
  `job_id`; results are obtained via poll (`GET /api/jobs/{id}`) or SSE.
  Rationale: local-Ollama runs take minutes (constitution §9), so a blocking
  request is a footgun. Tests wait via a fast mocked graph (AC-8), so no test
  needs a synchronous path.

- **D4 — Concurrency = 1, excess queues.** Graph runs execute on a single
  shared background worker (default concurrency `1`, configurable); further
  submissions are recorded `queued` and run in order — never rejected with
  `429`. Rationale: local Ollama serializes generation anyway, so parallel runs
  contend rather than speed up; `queued` already exists in `JobState` for this.
  A single shared consumer (not per-request threads) is required so AC-20's
  off-loop guarantee and AC-4's completion are not racy.

- **D5 — Eviction: insertion-order cap, keep last N.** The in-memory registry
  keeps at most `N` jobs (configurable, §6.1) and evicts the oldest by insertion
  order (LRU/insertion-order, **not** TTL — deterministic and trivially
  testable, AC-22). An evicted `job_id` returns `404`, identical to a
  never-existed id and consistent with EC-9. Feature 012's persistent store
  supersedes this.

- **D6 — No runner-level wall-clock cap.** No overall per-run timeout above the
  nodes' own per-call timeouts and circuit breakers (constitution §9; EC-11).
  Rationale: nodes already fail-open/fail-safe on timeout, and a runner cap
  would risk pre-empting a legitimately slow local run. Revisit only if a wedged
  run is ever observed.

- **D7 — CORS: permissive for a configurable localhost allowlist.** The API
  enables CORS for an allowlist of local origins (default includes the frontend
  dev-server origin, e.g. `http://localhost:5173` / `http://127.0.0.1:5173`),
  configurable via §6.1. Rationale (Gap A from review): §5 states this feature
  exposes the HTTP+SSE contract the future `frontend/` consumes; a browser
  `EventSource`/`fetch` from a Vite dev server (`:5173`) to the API (`:8000`) is
  cross-origin and fails without CORS *even on localhost*. D1's binding posture
  does not cover this. Non-allowlisted origins are not granted CORS (AC-23).

### 6.1 Configuration

All knobs introduced by the decisions above are defined as named constants in
`app/config.py`, matching the existing pattern there (module-level constants
seeded from `os.getenv(...)` where a runtime override is wanted). The plan
enumerates exact names/types; the set is:

| Knob | Purpose | Default |
| --- | --- | --- |
| Upload directory | Where submitted files are persisted as `document_path` (constitution §6) | `data/uploads` (backend-relative, mirroring `REPORT_OUTPUT_DIR`) |
| Max upload size (bytes) | Boundary reject → `413` (AC-16) | e.g. 25 MB |
| Allowed upload extensions | Boundary reject → `400` (AC-15) | `{.pdf, .docx}` (mirrors IngestAgent `ALLOWED_EXTENSIONS`) |
| Worker concurrency | Shared background worker size (D4) | `1` |
| Registry eviction cap `N` | Max retained job records (D5) | e.g. 100 |
| CORS allowlist | Permitted browser origins (D7) | frontend dev-server origins |
| Bind host / port | Uvicorn bind (D1) | `127.0.0.1` / `8000` |

No open questions remain. This spec is considered final and ready for `plan.md`.
