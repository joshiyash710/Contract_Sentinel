
# Pipeline Runner + API Technical Plan

## Git Branch

`feature/011-pipeline-runner-api` — branching workflow per `specs/000-constitution.md` §11.

---

## 1. Overview

This plan details how to implement the **pipeline runner + FastAPI API layer + SSE
progress streaming** specified in `specs/011-pipeline-runner-api/spec.md`. It is the
pipeline's **outer orchestration boundary** — the ignition the project has lacked:
`build_graph()` (feature 009, `builder.py:136`) and `deliver_report_sync()` (feature 010,
`delivery_step.py:220`) are today invoked *only from tests*. This feature builds the
callable + HTTP surface that accepts a contract, drives the compiled graph to `END`, then
invokes the existing delivery step.

**It adds no graph node and no conditional edge (spec §1).** Constitution §2 fixes the
StateGraph at exactly 7 sequential nodes + 2 conditional edges, terminating at
`report → END` (`builder.py:133`). This feature makes **zero** changes to `builder.py` —
no `add_node`, no `add_edge`, no `add_conditional_edges`. Exactly like feature 010's
delivery step, the runner is the graph's *caller*, not a member. To make the "not a node"
boundary **structural and obvious**, all new application code lives under two new
top-level packages — `backend/app/runner/` (the entry-agnostic core, worker, registry,
event bus, CLI) and `backend/app/api/` (FastAPI wiring) — deliberately **outside**
`app/graph/nodes/` (reserved for the 7 nodes). The pre-existing empty scaffolds
`app/api/.gitkeep`, `app/llm/.gitkeep`, `app/rag/.gitkeep`, `app/mcp_servers/.gitkeep` are
untouched by this feature except that `app/api/` gains real modules.

**Two entry points, one core (spec D2).** A single `run_pipeline(...)` function in
`app/runner/core.py` is the *only* place the graph and delivery are invoked. **Both** the
HTTP worker and the headless CLI (`python -m app.runner <file>`) call it — no forked
orchestration logic, so the two entry points cannot drift (spec D2 constraint;
`test_cli_uses_run_pipeline` + `test_worker_uses_run_pipeline` lock it). The CLI finally
lets the feature-010 Drive/Gmail OAuth delivery smoke be exercised end-to-end without
standing up a server (noted still-pending; `qwen3:14b` OOMs on this box, so real-LLM runs
stay a manual smoke and every automated test mocks the graph — spec AC-8).

**Async/sync bridge.** The compiled graph is **synchronous** (`graph.stream(...)` blocks),
and `deliver_report_sync` is synchronous; FastAPI is async (`002` §e). The graph therefore
runs on a **single shared background worker thread** (spec D4, concurrency = 1), never on
the request event loop (spec AC-20). A **per-job, thread-safe, replay-capable event
buffer** bridges the worker thread's progress callbacks to async SSE consumers, including
**late** subscribers that must replay already-emitted events (incl. a terminal event that
already fired) with no lost-wakeup gap (spec §2.4, EC-7, AC-11).

**In-memory only; feature 012 adds durability.** Job state lives in an in-memory
`JobRegistry` behind a single interface (spec AC-21) so feature 012 can swap it for
SQLite (`002` §f) + a LangGraph checkpointer (`002` §a) as a localized change. Records do
not survive a restart (spec EC-9) and the API assumes a single Uvicorn worker (spec §5).

**Boundary Pydantic (constitution §4).** Every request/response body — `AnalyzeAccepted`,
`JobStatus`, `ProgressEvent`, `ErrorInfo`, and the `JobState` enum — is a **Pydantic**
model in `app/runner/models.py` (co-located, mirroring feature 010's
`app/delivery/models.py`). The internal graph state stays the `001` `TypedDict`
`ContractState`, and the internal mutable `JobRecord` is a plain `@dataclass` (not a
boundary type) projected to the Pydantic `JobStatus` for responses — the §4
TypedDict/Pydantic separation is preserved.

**This feature closes the long-standing `processing_*` gap.** Features 007/009 flagged
that `processing_started_at` / `processing_completed_at` are pipeline-level, node-agnostic
fields that *no node* writes (report plan D2 caveat; confirmed:
`markdown_renderer.py` reads `processing_started_at`, nothing writes it). `run_pipeline`
now **seeds `processing_started_at`** in the initial state (spec §2.1, AC-3) and **stamps
`processing_completed_at`** into the returned state/job record after the graph — filling
the gap the report node deliberately left to the runner (see §5).

**Resolved spec decisions carried into this plan (§6 D1–D7):**
- **D1** — Uvicorn binds `127.0.0.1` only; **no auth** (auth/RBAC PERMANENTLY CUT). Host/
  port configurable.
- **D2** — CLI runner in scope, sharing the exact `run_pipeline` core with the API (no
  forked logic).
- **D3** — async-only; no synchronous analyze-and-wait endpoint.
- **D4** — single shared background worker, default concurrency 1; excess submissions
  **queue** (never `429`), hence the `queued` `JobState`.
- **D5** — in-memory registry evicts by **insertion order**, keep last `N`; evicted id →
  `404` (≡ never-existed, EC-9).
- **D6** — **no** runner-level wall-clock cap (nodes own their timeouts/circuit breakers).
- **D7** — permissive **CORS** for a configurable localhost allowlist (default the Vite
  dev-server origin), so the future browser frontend's `EventSource`/`fetch` is not
  blocked cross-origin.

---

## 2. Files to Create / Modify

### Shared Config Module

#### [MODIFY] `backend/app/config.py`

Add a new `# ── Runner / API` block (pure addition, no rename). `config.py` already
imports `os` and `Optional` (top of file), so **no new import** is required.

```python
# ── Runner / API layer ─────────────────────────────────────────────────────────
# Source: specs/011-pipeline-runner-api/spec.md §6.1

UPLOAD_DIR: str = "data/uploads"
# Directory (backend/-relative, mirroring REPORT_OUTPUT_DIR) where submitted contract
# files are persisted as document_path before the graph runs (constitution §6 — state
# minimality: the file is a reference, not embedded in state). Created if absent.

MAX_UPLOAD_SIZE_BYTES: int = 25 * 1024 * 1024   # 25 MB
# Boundary reject → 413 (spec AC-16). Enforced while streaming the upload so an oversized
# file is never fully buffered.

ALLOWED_UPLOAD_EXTENSIONS: frozenset = frozenset({".pdf", ".docx"})
# Boundary reject → 400 (spec AC-15). MIRRORS IngestAgent's ALLOWED_EXTENSIONS
# (ingest_agent.py:40); test_upload_extensions_match_ingest locks the two against drift.

RUNNER_WORKER_CONCURRENCY: int = 1
# Size of the shared background worker pool (spec D4). 1 because local Ollama serves one
# generation at a time; >1 would contend, not speed up. Excess submissions queue.

JOB_REGISTRY_MAX: int = 100
# Max retained JobRecords in the in-memory registry (spec D5). On overflow the oldest by
# insertion order is evicted; a GET on an evicted job_id → 404 (spec AC-22, EC-9).

CORS_ALLOWED_ORIGINS: tuple = (
    "http://localhost:5173", "http://127.0.0.1:5173",
)
# Browser origins granted CORS (spec D7). Default = the Vite dev-server origins the future
# frontend/ runs on; a cross-origin EventSource/fetch fails without this even on localhost.

API_BIND_HOST: str = "127.0.0.1"
API_BIND_PORT: int = 8000
# Uvicorn bind target (spec D1). Localhost-only; no auth. Overridable for local use.
```

There is intentionally **no** LLM / model / timeout constant — the runner makes zero LLM
calls (per-node timeouts and circuit breakers live in the nodes' own config; spec D6).

#### [MODIFY] `backend/pyproject.toml` — add `python-multipart` (**gating**)

FastAPI's `multipart/form-data` parsing (`UploadFile` + `Form`, used by `POST /api/analyze`
— spec §2.2) requires **`python-multipart`**, which is **not** in `002` §4's dependency
block. Without it, FastAPI raises at request time and the entire upload suite fails to run.
Add to `[project].dependencies`:

```toml
    "python-multipart>=0.0.9",
```

`fastapi`, `uvicorn`, `sse-starlette`, `httpx` (used by Starlette's `TestClient`) are
**already** in `002` §4 (lines 139–141, 132). **Recommended companion change:** append one
line to `002-tech-stack.md` §3e / §4 recording `python-multipart` as the multipart transport
dep for the upload endpoint — a pure addition to the already-chosen FastAPI upload capability
(no architectural change), keeping `002` and `pyproject.toml` in sync per the project's
spec-first discipline. This is **Step 0** of the TDD order (§4) — the API tests depend on it.

**[MODIFY] `.gitignore`** (repo root) — add `backend/data/uploads/` next to the existing
`backend/data/reports/` / `backend/data/secrets/` lines so uploaded contracts are never
committed.

---

### Boundary Pydantic Models

#### [NEW] `backend/app/runner/models.py`

Boundary types (constitution §4). Never stored in graph state; they *project from* the
internal `JobRecord` dataclass / from `ContractState`.

```python
from enum import Enum
from typing import Dict, List, Optional
from pydantic import BaseModel, Field

class JobState(str, Enum):
    """Job lifecycle — a runner concept, DISTINCT from 001's ValidationStatus /
    MCPDeliveryStatus (spec §2.3). str-Enum for JSON-friendly values."""
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"     # graph reached END (incl. ingest-error short-circuit)
    FAILED = "failed"           # unexpected exception during the run (EC-2)

class ErrorInfo(BaseModel):
    """Populated on an ingest-error completion (EC-1) OR a crashed run (EC-2)."""
    kind: str                   # e.g. "ingest_error" | "runner_exception"
    message: str

class AnalyzeAccepted(BaseModel):
    """202 body for POST /api/analyze."""
    job_id: str
    status: JobState
    submitted_at: str           # ISO-8601 UTC

class JobStatus(BaseModel):
    """GET /api/jobs/{job_id} body; also the terminal SSE event's `final`."""
    job_id: str
    status: JobState
    current_node: Optional[str] = None
    completed_nodes: List[str] = Field(default_factory=list)
    submitted_at: str
    started_at: Optional[str] = None
    finished_at: Optional[str] = None
    report_available: bool = False                      # on-disk truth (EC-8)
    mcp_delivery_status: Dict[str, dict] = Field(default_factory=dict)  # 001 MCPDeliveryInfo shape
    error: Optional[ErrorInfo] = None

class ProgressEvent(BaseModel):
    """One SSE payload (spec §2.4)."""
    event: str                  # "progress" | "completed" | "failed"
    job_id: str
    node: Optional[str] = None
    node_index: Optional[int] = None      # canonical map (§ progress.py); redline/skip → 6
    node_total: Optional[int] = None      # canonical pipeline length (7); see progress.py
    elapsed_seconds: Optional[float] = None
    final: Optional[JobStatus] = None     # present only on completed/failed
```

`mcp_delivery_status` is typed `Dict[str, dict]` (the `001` `MCPDeliveryInfo` TypedDict is
not a Pydantic model); values carry `{status, error_message, delivered_at}` exactly as the
delivery step returns them, with the `MCPDeliveryStatus` enum coerced to its `.value` at
projection time so the JSON is clean.

---

### Progress Map (canonical node → index)

#### [NEW] `backend/app/runner/progress.py`

The single source of truth for the branching-graph progress indexing (spec §2.4, Gap B):

```python
# graph node name (as build_graph registers it) → progress-bar index.
# redline and skip_redline are BOTH logical Node 6, so they share index 6 — the graph
# physically emits an update for exactly one of them per run (spec §2.4).
NODE_INDEX: dict[str, int] = {
    "ingest_agent": 1,
    "clause_splitter": 2,
    "crag_retrieval": 3,
    "self_rag_validation": 4,
    "risk_score": 5,
    "redline": 6,
    "skip_redline": 6,
    "report": 7,
}
TOTAL_STAGES: int = 7   # canonical pipeline length with redline/skip collapsed to one slot

def node_index(node_name: str) -> int | None:
    """Return the progress index for a graph node name, or None for an unknown name
    (defensive — an unknown name yields a progress event with node_index=None rather
    than raising, so a future graph-node rename can't crash the runner)."""
    return NODE_INDEX.get(node_name)
```

`node_index` drives the progress bar **only**; the authoritative record of what ran is the
job's `completed_nodes` list and the terminal event (spec §2.4, AC-9). A run that
short-circuits at `ingest_agent` (ingest error → `END`) simply emits one `progress` event
then the terminal event — the bar not reaching 7 correctly reflects an incomplete run.

---

### Runner Core (the shared, entry-agnostic engine)

#### [NEW] `backend/app/runner/core.py`

The **only** module that invokes `build_graph()` and `deliver_report_sync()`. Pure of HTTP
and of the registry — it takes a file path + an optional progress callback and returns a
`RunResult`. Both the API worker and the CLI call `run_pipeline`.

```python
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, Optional

from app.graph.builder import build_graph
from app.delivery import deliver_report_sync
from app.runner.progress import node_index, TOTAL_STAGES

logger = logging.getLogger("contractsentinel.runner")

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()

@dataclass
class NodeProgress:
    node: str
    index: Optional[int]
    total: int
    elapsed_seconds: Optional[float]

@dataclass
class RunResult:
    # NOTE: the completed-node SEQUENCE is NOT carried here — it is emitted live via
    # on_progress and recorded on the JobRecord (single source of truth, review M1). A
    # duplicate list on RunResult that nobody reads could silently diverge from the live
    # one, so it is deliberately absent.
    final_state: dict
    report_path: Optional[str]
    mcp_delivery_status: dict
    ingest_error: Optional[dict] = None      # the 001 {"error_type","message"} dict, or None
    started_at: str = ""
    completed_at: str = ""

def run_pipeline(document_path: str, *, recipient: Optional[str] = None,
                 on_progress: Optional[Callable[[NodeProgress], None]] = None) -> RunResult:
    """Drive the compiled graph over `document_path`, then deliver the report.
    The ONLY orchestration entry point — API worker and CLI both call this (spec D2).
    Seeds the two runner-owned initial-state keys and stamps completion. Never seeds a
    node-owned key (spec AC-3/6). May raise — callers convert an exception into a FAILED
    job (EC-2); the CLI prints it and exits non-zero."""
    started_at = _now_iso()
    graph = build_graph()                              # exactly once per run (spec AC-6)
    initial = {"document_path": document_path,
               "processing_started_at": started_at}    # ONLY runner-seeded keys (spec §2.1)

    final_state: dict = {}
    last_node: Optional[str] = None
    # PRIMARY: stream_mode="values" — each yield is the FULL cumulative ContractState after
    # a super-step, so the last yield IS the terminal state (delivery needs the whole state,
    # not per-node deltas). The just-run node is read from state["current_node"], deduped so
    # each node emits exactly one progress event.
    for state in graph.stream(initial, stream_mode="values"):
        final_state = state
        node = state.get("current_node")
        if node and node != last_node:
            last_node = node
            if on_progress is not None:
                timing = (state.get("node_timings") or {}).get(node)
                on_progress(NodeProgress(node, node_index(node), TOTAL_STAGES, timing))

    # ── post-terminal delivery (feature 010) — same call the tests use ──
    delivery = deliver_report_sync(final_state, recipient=recipient)   # never raises
    mcp_status = delivery.get("mcp_delivery_status", {})
    final_state = {**final_state, **delivery}

    completed_at = _now_iso()
    final_state["processing_completed_at"] = completed_at   # runner fills the D2 gap (§5)

    return RunResult(
        final_state=final_state,
        report_path=final_state.get("report_path"),
        mcp_delivery_status=mcp_status,
        ingest_error=final_state.get("ingest_error"),
        started_at=started_at,
        completed_at=completed_at,
    )
```

> **LangGraph streaming altitude + fallback (review R2).** No existing code streams the
> graph — every current test uses `graph.invoke()` — so `stream_mode="values"` yielding
> once per node with a changing `current_node` is an **assumption to verify with a one-line
> spike at Step 8/9** (§4) before the core is committed. It almost certainly holds for this
> linear graph. **Documented fallback if per-node granularity disappoints:** switch to
> `stream_mode="updates"`, which yields `{node_name: delta}` per node — the node name is the
> dict key directly (no reliance on `current_node`) — and shallow-accumulate the deltas into
> `final_state` (`final_state.update(delta)`). Shallow accumulation is sufficient here
> because delivery reads only top-level simple-overwrite keys (`report_path`, `document_id`,
> `original_filename`) and loads the summary from the on-disk JSON sibling — it never reads
> the reducer-merged `clauses`/`evidence_trail`, so no reducer replay is needed. Either mode
> makes **zero** `builder.py` change and uses no checkpointer (that is feature 012).

#### [NEW] `backend/app/runner/__init__.py`
Re-exports `run_pipeline`, `RunResult`, `NodeProgress`.

---

### Per-Job Event Buffer (thread → async bridge)

#### [NEW] `backend/app/runner/events.py`

Bridges the synchronous worker thread's `publish(...)` to async SSE consumers, with replay
for late subscribers and no lost-wakeup race (spec §2.4, EC-7, AC-11).

```python
import asyncio, threading
from typing import Optional
from app.runner.models import ProgressEvent

class JobEventBuffer:
    """Per-job, thread-safe, replay-capable SSE event bus.
    publish() is called from the worker THREAD; subscribe()/iteration run on the API
    event LOOP. The loop is captured once at app startup so the thread can hand events
    across via loop.call_soon_threadsafe (asyncio.Queue is not thread-safe to poke
    directly from another thread)."""
    def __init__(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop
        self._lock = threading.Lock()
        self._events: list[ProgressEvent] = []
        self._subscribers: set[asyncio.Queue] = set()
        self._closed = False

    def publish(self, event: ProgressEvent) -> None:           # worker thread
        with self._lock:
            self._events.append(event)
            if event.event in ("completed", "failed"):
                self._closed = True
            subs = list(self._subscribers)
        for q in subs:
            self._loop.call_soon_threadsafe(q.put_nowait, event)

    def subscribe(self) -> tuple[list[ProgressEvent], Optional[asyncio.Queue], bool]:
        """Atomically snapshot the replayable backlog AND register for live events under
        ONE lock — so nothing published between snapshot and registration is lost."""
        with self._lock:
            backlog = list(self._events)
            if self._closed:
                return backlog, None, True          # finished: replay + stop (AC-11)
            q: asyncio.Queue = asyncio.Queue()
            self._subscribers.add(q)
            return backlog, q, False

    def unsubscribe(self, q: asyncio.Queue) -> None:
        with self._lock:
            self._subscribers.discard(q)
```

The SSE route's async generator (see `routes.py`) yields the `backlog` first, then — if
not `closed` — `await q.get()` in a loop, yielding each event until it sees a terminal
(`completed`/`failed`) event, then `unsubscribe`s. A client disconnect (EC-6) is caught by
the route and also `unsubscribe`s; the underlying run continues (the worker never checks
subscriber presence).

---

### In-Memory Job Registry (the single 012-swap seam)

#### [NEW] `backend/app/runner/registry.py`

```python
import threading
from collections import OrderedDict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional
from app.runner.events import JobEventBuffer
from app.runner.models import JobState, JobStatus, ErrorInfo

@dataclass
class JobRecord:
    """Internal MUTABLE job state (NOT a boundary type — projected to JobStatus).
    Mutated by the WORKER THREAD while GET handlers on the event loop read it, so EVERY
    field mutation AND the to_status() projection go through the record's OWN lock
    (review R1). The registry lock protects the DICT of records; this lock protects the
    FIELDS inside one record — distinct critical sections. In particular, copying
    completed_nodes must happen under the lock: iterating a list while the worker appends
    to it is a real CPython race (RuntimeError / torn read)."""
    job_id: str
    document_path: str
    recipient: Optional[str]
    buffer: JobEventBuffer
    submitted_at: str = ""
    status: JobState = JobState.QUEUED
    current_node: Optional[str] = None
    completed_nodes: list[str] = field(default_factory=list)
    started_at: Optional[str] = None
    finished_at: Optional[str] = None
    report_path: Optional[str] = None
    mcp_delivery_status: dict = field(default_factory=dict)
    error: Optional[ErrorInfo] = None
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False, compare=False)

    def mark_running(self, started_at: str) -> None:          # worker thread
        with self._lock:
            self.status = JobState.RUNNING
            self.started_at = started_at

    def record_progress(self, node: str) -> None:             # worker thread (per node)
        with self._lock:
            self.current_node = node
            self.completed_nodes.append(node)

    def mark_terminal(self, *, status: JobState, finished_at: str,
                      report_path: Optional[str] = None,
                      mcp_delivery_status: Optional[dict] = None,
                      error: Optional[ErrorInfo] = None) -> None:   # worker thread
        with self._lock:
            self.status = status
            self.finished_at = finished_at
            if report_path is not None:
                self.report_path = report_path
            if mcp_delivery_status is not None:
                self.mcp_delivery_status = mcp_delivery_status
            self.error = error

    def to_status(self) -> JobStatus:                         # event loop (GET handlers)
        with self._lock:                                      # atomic snapshot of ALL fields
            report_available = bool(self.report_path and Path(self.report_path).exists())  # EC-8
            return JobStatus(
                job_id=self.job_id, status=self.status, current_node=self.current_node,
                completed_nodes=list(self.completed_nodes),   # copy UNDER lock — no torn read (R1)
                submitted_at=self.submitted_at, started_at=self.started_at,
                finished_at=self.finished_at, report_available=report_available,
                mcp_delivery_status=_coerce_status(self.mcp_delivery_status), error=self.error,
            )

class JobRegistry:
    """Thread-safe, insertion-order-capped store of records. The ONE seam feature 012
    replaces with a persistent store — handlers/worker touch jobs ONLY through this object
    (spec AC-21). This lock guards the DICT (add/get/evict); per-record FIELD mutation is
    guarded by each JobRecord's own lock (review R1), so a long-running progress update
    never blocks a lookup of a DIFFERENT job."""
    def __init__(self, max_jobs: int) -> None:
        self._lock = threading.Lock()
        self._jobs: "OrderedDict[str, JobRecord]" = OrderedDict()
        self._max = max_jobs

    def add(self, record: JobRecord) -> None:
        with self._lock:
            self._jobs[record.job_id] = record
            while len(self._jobs) > self._max:
                self._jobs.popitem(last=False)          # evict oldest by insertion (D5, AC-22)

    def get(self, job_id: str) -> Optional[JobRecord]:
        with self._lock:
            return self._jobs.get(job_id)               # None → 404 (AC-17, EC-9)
```

`_coerce_status(...)` normalizes each `MCPDeliveryInfo`'s `status` enum to its `.value` for
JSON. `OrderedDict` makes eviction and "oldest" deterministic and trivially testable (D5
chose insertion-order over TTL for exactly this). There is **no** `JobRegistry.update(...)`:
all field mutation flows through the `JobRecord` lock methods above (single mutation path),
so the registry lock and the record lock never overlap responsibilities.

---

### Background Worker (single shared consumer)

#### [NEW] `backend/app/runner/worker.py`

```python
import logging, queue, threading
from datetime import datetime, timezone
from app.runner.core import run_pipeline, NodeProgress
from app.runner.models import JobState, ProgressEvent, ErrorInfo
from app.runner.registry import JobRegistry, JobRecord

logger = logging.getLogger("contractsentinel.runner.worker")

class PipelineWorker:
    """A SINGLE shared background consumer (spec D4/AC-20). Jobs are enqueued by the API
    handler and processed one at a time (concurrency=1) off the request event loop. Not
    per-request threads — that would make AC-20's off-loop guarantee and completion racy."""
    def __init__(self, registry: JobRegistry, concurrency: int = 1) -> None:
        self._registry = registry
        self._queue: "queue.Queue[str]" = queue.Queue()
        self._threads: list[threading.Thread] = []
        self._concurrency = concurrency
        self._stop = threading.Event()

    def start(self) -> None:
        for i in range(self._concurrency):
            t = threading.Thread(target=self._loop, name=f"pipeline-worker-{i}", daemon=True)
            t.start(); self._threads.append(t)

    def submit(self, job_id: str) -> None:
        self._queue.put(job_id)                        # extra jobs queue, never 429 (D4)

    def stop(self, join_timeout: float = 5.0) -> None:
        self._stop.set()
        for _ in self._threads:
            self._queue.put(_SENTINEL)
        for t in self._threads:               # DETERMINISTIC shutdown (review T1): join so no
            t.join(timeout=join_timeout)       # worker is mid-run after lifespan exits — a lingering
                                               # publish via call_soon_threadsafe onto a closed loop
                                               # would raise "Event loop is closed". Daemon threads
                                               # prevent a hard hang if a run genuinely wedges.

    def _loop(self) -> None:
        while not self._stop.is_set():
            job_id = self._queue.get()
            if job_id is _SENTINEL:
                return
            self._run_one(job_id)

    def _run_one(self, job_id: str) -> None:
        rec = self._registry.get(job_id)
        if rec is None:                                # evicted before it ran (D5)
            return
        rec.mark_running(_now_iso())                   # field writes under the record lock (R1)

        def _on_progress(p: NodeProgress) -> None:
            rec.record_progress(p.node)                # append under the record lock (R1)
            rec.buffer.publish(ProgressEvent(
                event="progress", job_id=job_id, node=p.node,
                node_index=p.index, node_total=p.total, elapsed_seconds=p.elapsed_seconds))

        try:
            result = run_pipeline(rec.document_path, recipient=rec.recipient,
                                  on_progress=_on_progress)
            error = None
            if result.ingest_error:                    # EC-1: reached END, but ingest failed
                # extract the human message from {"error_type","message"}, not the raw dict (M2)
                msg = result.ingest_error.get("message") or str(result.ingest_error)
                error = ErrorInfo(kind="ingest_error", message=msg)
            rec.mark_terminal(status=JobState.COMPLETED, finished_at=result.completed_at,
                              report_path=result.report_path,
                              mcp_delivery_status=result.mcp_delivery_status, error=error)
            terminal = ProgressEvent(event="completed", job_id=job_id, final=rec.to_status())
        except Exception as exc:                       # EC-2: crash → FAILED, isolated
            logger.exception("pipeline run failed for job %s", job_id)
            rec.mark_terminal(status=JobState.FAILED, finished_at=_now_iso(),
                              error=ErrorInfo(kind="runner_exception", message=str(exc)))
            terminal = ProgressEvent(event="failed", job_id=job_id, final=rec.to_status())
        rec.buffer.publish(terminal)                   # closes the buffer (AC-9/10)
```

`_SENTINEL = object()`; `_now_iso()` as in core. All record-field mutation goes through the
`JobRecord` lock methods (`mark_running` / `record_progress` / `mark_terminal`), never direct
attribute writes, so a concurrent `to_status()` on the event loop can't observe a torn field
or race the `completed_nodes` append (review R1). One job's exception never touches another
record (EC-2) — each `_run_one` is independent and the `try` contains the whole run.

---

### FastAPI Application

#### [NEW] `backend/app/api/main.py`

App factory + lifespan (captures the loop, starts/stops the worker) + module-level `app`
for `uvicorn app.api.main:app`, and a `run()` for `python -m app.api`.

```python
import asyncio, logging
from contextlib import asynccontextmanager
import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

import app.config as _config
from app.api.routes import router, RunnerContext
from app.runner.registry import JobRegistry
from app.runner.worker import PipelineWorker

logger = logging.getLogger("contractsentinel.api")

@asynccontextmanager
async def lifespan(app: FastAPI):
    loop = asyncio.get_running_loop()                  # the loop the event buffer bridges to
    registry = JobRegistry(max_jobs=_config.JOB_REGISTRY_MAX)
    worker = PipelineWorker(registry, concurrency=_config.RUNNER_WORKER_CONCURRENCY)
    worker.start()
    app.state.ctx = RunnerContext(registry=registry, worker=worker, loop=loop)
    try:
        yield
    finally:
        worker.stop()

def create_app() -> FastAPI:
    app = FastAPI(title="ContractSentinel", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(_config.CORS_ALLOWED_ORIGINS),  # spec D7 / AC-23
        allow_methods=["*"], allow_headers=["*"],
    )
    app.include_router(router)
    return app

app = create_app()

def run() -> None:
    uvicorn.run(app, host=_config.API_BIND_HOST, port=_config.API_BIND_PORT)  # D1
```

`RunnerContext` is a small dataclass bundling `registry`, `worker`, `loop` (so handlers get
them from `request.app.state.ctx`, no module globals — testable, and the loop reference the
`JobEventBuffer` needs is created here).

#### [NEW] `backend/app/api/__main__.py`
`from app.api.main import run` then `run()` — enables `python -m app.api`.

#### [NEW] `backend/app/api/routes.py`

All endpoints. Uses `request.app.state.ctx`.

```python
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from sse_starlette.sse import EventSourceResponse

import app.config as _config
from app.runner.events import JobEventBuffer
from app.runner.models import AnalyzeAccepted, JobState
from app.runner.registry import JobRecord

router = APIRouter(prefix="/api")

@dataclass
class RunnerContext:
    registry: ...
    worker: ...
    loop: ...

@router.get("/health")
async def health():
    return {"status": "ok"}                            # AC-18

@router.post("/analyze", status_code=202)
async def analyze(request: Request, file: UploadFile = File(...),
                  recipient: str | None = Form(None)) -> AnalyzeAccepted:
    ext = Path(file.filename or "").suffix.lower()
    if ext not in _config.ALLOWED_UPLOAD_EXTENSIONS:
        raise HTTPException(400, f"Unsupported file type '{ext}'")     # AC-15
    # stream to disk, enforcing the size cap without buffering the whole file (AC-16)
    dest_dir = Path(_config.UPLOAD_DIR); dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / f"{uuid.uuid4().hex}{ext}"
    size = 0
    with dest.open("wb") as fh:
        while chunk := await file.read(1024 * 1024):
            size += len(chunk)
            if size > _config.MAX_UPLOAD_SIZE_BYTES:
                fh.close(); dest.unlink(missing_ok=True)
                raise HTTPException(413, "File too large")             # AC-16
            fh.write(chunk)
    if size == 0:
        dest.unlink(missing_ok=True)
        raise HTTPException(400, "Empty upload")                       # EC-5
    ctx = request.app.state.ctx
    job_id = uuid.uuid4().hex
    rec = JobRecord(job_id=job_id, document_path=str(dest), recipient=recipient,
                    buffer=JobEventBuffer(ctx.loop), submitted_at=_now_iso())
    ctx.registry.add(rec)
    ctx.worker.submit(job_id)                          # queues if worker busy (D4)
    return AnalyzeAccepted(job_id=job_id, status=JobState.QUEUED, submitted_at=rec.submitted_at)

@router.get("/jobs/{job_id}")
async def get_job(request: Request, job_id: str):
    rec = request.app.state.ctx.registry.get(job_id)
    if rec is None:
        raise HTTPException(404, "No such job")         # AC-17, EC-9
    return rec.to_status()

@router.get("/jobs/{job_id}/events")
async def job_events(request: Request, job_id: str):
    rec = request.app.state.ctx.registry.get(job_id)
    if rec is None:
        raise HTTPException(404, "No such job")
    backlog, q, closed = rec.buffer.subscribe()

    async def _stream():
        for ev in backlog:                              # replay (late subscriber / AC-11)
            yield {"event": ev.event, "data": ev.model_dump_json()}
        if closed:
            return
        try:
            while True:
                ev = await q.get()
                yield {"event": ev.event, "data": ev.model_dump_json()}
                if ev.event in ("completed", "failed"):
                    return
        finally:
            rec.buffer.unsubscribe(q)                   # client disconnect (EC-6)
    return EventSourceResponse(_stream())

@router.get("/jobs/{job_id}/report")
async def get_report(request: Request, job_id: str, format: str = "md"):
    rec = request.app.state.ctx.registry.get(job_id)
    if rec is None:
        raise HTTPException(404, "No such job")
    if rec.status is not JobState.COMPLETED or not rec.report_path:
        raise HTTPException(409, "Report not ready")    # AC-14
    md_path = Path(rec.report_path)                     # ONLY from the record (AC-13)
    path = md_path if format == "md" else md_path.with_suffix(".json")
    if not path.exists():
        raise HTTPException(404, "Report file missing") # EC-8
    media = "text/markdown" if format == "md" else "application/json"
    return FileResponse(str(path), media_type=media, filename=path.name)
```

**Report-path safety (AC-13).** The path is derived solely from `rec.report_path` (set by
the runner from Node 7's `report_path`) and its `.json` sibling — **no** client-supplied
path component is ever joined, so traversal is structurally impossible. `format` is a
whitelist (`md` → the recorded path, anything else → its `.json` sibling); an unknown
`format` never touches arbitrary files.

---

### CLI Entry Point

#### [NEW] `backend/app/runner/__main__.py`

The headless runner (spec D2). Shares `run_pipeline` with the API — **no forked logic**.

```python
import argparse, sys
from app.runner.core import run_pipeline, NodeProgress

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.runner",
                                     description="Run the ContractSentinel pipeline on one file.")
    parser.add_argument("file", help="Path to a .pdf or .docx contract")
    parser.add_argument("--recipient", default=None, help="Override the Gmail delivery recipient")
    args = parser.parse_args(argv)

    def _on_progress(p: NodeProgress) -> None:
        print(f"[{p.index}/{p.total}] {p.node}", file=sys.stderr)   # progress → stderr

    try:
        result = run_pipeline(args.file, recipient=args.recipient, on_progress=_on_progress)
    except Exception as exc:                            # EC-2 at the CLI boundary
        print(f"ERROR: pipeline failed: {exc}", file=sys.stderr)
        return 1
    print(f"report_path: {result.report_path}")
    print(f"delivery: {result.mcp_delivery_status}")
    if result.ingest_error:
        print(f"ingest_error: {result.ingest_error}", file=sys.stderr)
        return 2                                        # completed-with-ingest-error (EC-1)
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
```

This is the entry the feature-010 Drive/Gmail OAuth delivery smoke uses (real graph + real
`deliver_report_sync`) once a provisioned token exists — no HTTP server required.

#### [NEW] `backend/app/api/__init__.py`
Package marker (docstring: FastAPI app for the runner). The `app/api/.gitkeep` may remain.

---

### Unit Tests

All graph/delivery invocation is **mocked** — no live Ollama (`qwen3:14b` OOMs here) and no
live Google. Async pieces use the repo's existing `asyncio_mode = "auto"` (feature 010).

#### [NEW] `backend/tests/unit/test_runner_models.py`
| Test | Verifies |
|------|----------|
| `test_jobstate_values` | `JobState` values are `queued/running/completed/failed` (spec §2.3) |
| `test_jobstatus_defaults` | `completed_nodes`/`mcp_delivery_status` default empty; `report_available` False; optionals None |
| `test_progressevent_roundtrips` | `ProgressEvent.model_dump_json` re-parses; `final` embeds a `JobStatus` on terminal events |
| `test_analyze_accepted_shape` | `AnalyzeAccepted` requires `job_id/status/submitted_at` |

#### [NEW] `backend/tests/unit/test_progress_map.py`
| Test | Verifies |
|------|----------|
| `test_redline_and_skip_share_index_6` | `NODE_INDEX["redline"] == NODE_INDEX["skip_redline"] == 6` (Gap B) |
| `test_indices_cover_seven_stages` | Distinct indices are exactly `{1..7}`; `TOTAL_STAGES == 7` |
| `test_node_names_match_builder` | Every key equals a node name `build_graph()` registers (guards rename drift) |
| `test_unknown_node_returns_none` | `node_index("nope") is None` (defensive, no raise) |

#### [NEW] `backend/tests/unit/test_runner_core.py`
`build_graph` patched to a fake compiled graph whose `.stream(...)` yields scripted full
states (each with a `current_node`); `deliver_report_sync` patched to a stub.
| Test | Verifies |
|------|----------|
| `test_seeds_only_document_path_and_started_at` | The initial state passed to `.stream` has keys ⊆ `{document_path, processing_started_at}` (spec AC-3/6) |
| `test_build_graph_called_once` | `build_graph` invoked exactly once per run (AC-6) |
| `test_progress_callback_per_node` | `on_progress` fires once per distinct `current_node`, in order, with the mapped index (AC-9 basis) |
| `test_redline_branch_indices` | A scripted redline path emits index 6 for `redline`; a skip path emits 6 for `skip_redline` |
| `test_delivery_called_with_recipient` | `deliver_report_sync` called with the passed `recipient`; omitted → `None` (AC-5) |
| `test_final_state_has_completed_timestamp` | `RunResult.final_state["processing_completed_at"]` is set by the runner (§5, D2 gap closed) |
| `test_result_carries_report_path_and_delivery` | `report_path` + `mcp_delivery_status` taken from terminal state / delivery return |
| `test_ingest_error_surfaced_not_raised` | Scripted `ingest_error` terminal state → `RunResult.ingest_error` set, no exception (EC-1) |
| `test_graph_exception_propagates` | `.stream` raising propagates out of `run_pipeline` (caller converts to FAILED — EC-2) |
| `test_only_public_entrypoints_imported` | `core.py` imports only `build_graph` + `deliver_report_sync` from graph/delivery — no `app.graph.nodes.*` (AC-7) |

#### [NEW] `backend/tests/unit/test_event_buffer.py`
| Test | Verifies |
|------|----------|
| `test_live_subscriber_receives_events` | Subscribe, publish → subscriber queue gets the event |
| `test_late_subscriber_replays_backlog` | Publish 3, then subscribe → backlog has all 3 (EC-7) |
| `test_finished_job_replays_terminal_and_closes` | Publish terminal, then subscribe → backlog includes terminal, `closed is True`, no queue (AC-11) |
| `test_no_lost_wakeup` | Interleave publish + subscribe under contention → every event reaches the subscriber exactly once (EC-7) |
| `test_unsubscribe_removes_queue` | After `unsubscribe`, further publishes don't target the queue (EC-6) |
| `test_publish_is_thread_safe` | Concurrent publishes from threads don't corrupt the backlog (lock) |

#### [NEW] `backend/tests/unit/test_registry.py`
| Test | Verifies |
|------|----------|
| `test_add_and_get` | Added record retrievable; unknown id → `None` (AC-17 basis) |
| `test_eviction_keeps_last_n` | With `max=N`, adding `N+1` evicts the oldest by insertion; evicted `get` → `None` (AC-22, D5) |
| `test_record_lock_methods_mutate` | `mark_running`/`record_progress`/`mark_terminal` update the record; `to_status()` reflects them |
| `test_concurrent_progress_and_to_status_no_race` | One thread calls `record_progress` in a tight loop while another repeatedly calls `to_status()` → no `RuntimeError`, `completed_nodes` snapshots are always internally consistent (review R1) |
| `test_to_status_report_available_reflects_disk` | `report_available` True only when the file exists, not merely `report_path` set (EC-8) |
| `test_delivery_status_enum_coerced` | `MCPDeliveryStatus` enum in a record → `.value` string in `JobStatus` JSON |
| `test_registry_is_single_seam` | Handlers/worker reach jobs only via the registry object (a fake registry substitutes with no other patching — AC-21) |

#### [NEW] `backend/tests/unit/test_worker.py`
`run_pipeline` patched with a controllable stub (an `Event` to hold it "running").
| Test | Verifies |
|------|----------|
| `test_single_shared_worker_serializes` | Two submits with concurrency=1 → second stays `queued` until the first finishes (AC-20, D4) |
| `test_completed_status_and_terminal_event` | On success → record `COMPLETED`, terminal `completed` event published (AC-4/9/10) |
| `test_ingest_error_marks_completed_with_error` | Stub returns `ingest_error` → `COMPLETED` + `error.kind == "ingest_error"` (EC-1) |
| `test_exception_marks_failed_isolated` | Stub raises for job A → A `FAILED`; job B still completes (EC-2) |
| `test_worker_uses_run_pipeline` | The worker calls `run_pipeline` (shared core — D2) |
| `test_evicted_job_skipped` | A job evicted before it runs is a no-op, no crash (D5) |

#### [NEW] `backend/tests/unit/test_cli.py`
`run_pipeline` patched.
| Test | Verifies |
|------|----------|
| `test_cli_uses_run_pipeline` | `main([file])` calls `run_pipeline(file, recipient=None, ...)` — shared core (D2) |
| `test_cli_passes_recipient` | `--recipient x` → `run_pipeline(..., recipient="x")` |
| `test_cli_prints_report_path` | stdout carries `report_path` on success; exit 0 |
| `test_cli_ingest_error_exit_2` | `RunResult.ingest_error` → exit code 2 (EC-1) |
| `test_cli_exception_exit_1` | `run_pipeline` raising → stderr error, exit 1 (EC-2) |

#### [MODIFY] `backend/tests/unit/test_config.py`
| Test | Verifies |
|------|----------|
| `test_runner_api_constants_match_spec` | `UPLOAD_DIR`, `MAX_UPLOAD_SIZE_BYTES`, `RUNNER_WORKER_CONCURRENCY`, `JOB_REGISTRY_MAX`, `CORS_ALLOWED_ORIGINS`, `API_BIND_HOST/PORT` match spec §6.1 values/types |
| `test_upload_extensions_match_ingest` | `ALLOWED_UPLOAD_EXTENSIONS == ingest_agent.ALLOWED_EXTENSIONS` (drift lock, AC-15) |
| `test_bind_host_is_localhost` | `API_BIND_HOST == "127.0.0.1"` (D1 — no accidental `0.0.0.0`) |
| `test_runner_no_llm_constant` | No `RUNNER_*_TIMEOUT` / model / circuit-breaker constant (D6) |

---

### Integration Tests

Use Starlette's `TestClient`. `build_graph` is monkeypatched to a **fast fake** that streams
a scripted 7-node (or short-circuit) sequence, and `deliver_report_sync` is stubbed — so
tests are deterministic and never touch Ollama/Google (spec AC-8). A helper
`_wait_for(client, job_id, state, timeout=5)` polls `GET /api/jobs/{id}` until the state is
reached (the fake graph finishes in milliseconds).

> **Lifespan MUST run — use the context-manager form (review R3).** The worker thread and
> the event-loop capture happen in the FastAPI `lifespan` startup. A bare
> `TestClient(create_app())` **skips** lifespan → the worker never starts → every
> lifecycle/SSE test hangs or times out. The fixture therefore yields the client from the
> `with` form so startup/shutdown fire:
>
> ```python
> @pytest.fixture
> def client(monkeypatch, tmp_path):
>     monkeypatch.setattr("app.runner.core.build_graph", _fake_build_graph)
>     monkeypatch.setattr("app.runner.core.deliver_report_sync", _stub_delivery)
>     monkeypatch.setattr(_config, "UPLOAD_DIR", str(tmp_path / "uploads"))
>     monkeypatch.setattr(report_agent_mod, "REPORT_OUTPUT_DIR", str(tmp_path / "reports"))
>     with TestClient(create_app()) as c:      # <-- context manager RUNS lifespan (worker start)
>         yield c
> ```
>
> SSE responses are consumed with the streaming form, e.g.
> `with client.stream("GET", f"/api/jobs/{job_id}/events") as r:` then iterate
> `r.iter_lines()` — a plain `client.get` on an `EventSourceResponse` would block. (Patch
> `build_graph`/`deliver_report_sync` on `app.runner.core`, where they are imported and
> called — see §3 import map — not on their defining modules.)

#### [NEW] `backend/tests/integration/conftest.py` additions (or a new `test_api_*` fixture module)
The `client` fixture above, plus the `_fake_build_graph` (returns an object whose
`.stream(initial, stream_mode="values")` yields scripted full states) and `_stub_delivery`
helpers, plus `_wait_for`.

#### [NEW] `backend/tests/integration/test_api_analyze.py`
| Test | Verifies |
|------|----------|
| `test_analyze_pdf_returns_202` | Valid `.pdf` → 202 + `job_id`; immediate status `queued`/`running`, never `completed` (AC-1) |
| `test_analyze_docx_accepted` | `.docx` accepted identically (AC-2) |
| `test_upload_saved_and_path_passed` | Uploaded bytes land under `UPLOAD_DIR`; the path handed to the (fake) graph equals `state["document_path"]` (AC-3) |
| `test_recipient_forwarded` | `recipient` form field reaches `deliver_report_sync(recipient=...)` (AC-5) |
| `test_unsupported_extension_400_no_job` | `.txt` → 400, and no job is created (AC-15) |
| `test_oversized_413` | File > `MAX_UPLOAD_SIZE_BYTES` → 413 (AC-16) |
| `test_empty_upload_400` | Zero-byte file → 400, no job (EC-5) |
| `test_response_not_blocked_by_run` | With a deliberately slow fake graph, the 202 returns while the job is still `running` (AC-20) |

#### [NEW] `backend/tests/integration/test_api_jobs.py`
| Test | Verifies |
|------|----------|
| `test_job_lifecycle_to_completed` | After the fake run, status → `completed`, `report_available True`, `finished_at` set (AC-4) |
| `test_unknown_job_404` | `GET /api/jobs/{random}` → 404 (AC-17) |
| `test_health_ok` | `GET /api/health` → 200 `{"status":"ok"}` (AC-18) |
| `test_two_jobs_independent` | Two submissions → two ids tracked independently (AC-19) |
| `test_ingest_error_completes_with_error` | Fake graph sets `ingest_error` → job `completed` with `error.kind=="ingest_error"` (EC-1) |
| `test_graph_exception_marks_failed` | Fake graph raises → job `failed` with `error` populated; a second job still completes (EC-2) |
| `test_delivery_status_surfaced` | Stubbed delivery status appears in `mcp_delivery_status`; disabled → empty map, still `completed` (EC-3/4) |
| `test_eviction_returns_404` | Set `JOB_REGISTRY_MAX` small; exceed it → oldest job `GET` → 404 (AC-22) |

#### [NEW] `backend/tests/integration/test_api_sse.py`
| Test | Verifies |
|------|----------|
| `test_event_stream_content_type` | `/events` returns `text/event-stream` (AC-9) |
| `test_progress_then_terminal_then_close` | One `progress` event per node the fake graph entered, in order, then exactly one terminal event, then the stream closes (AC-9) |
| `test_terminal_final_equals_status` | The terminal event's `final` equals `GET /api/jobs/{id}` at that moment (AC-10) |
| `test_finished_job_stream_immediate_terminal` | Opening `/events` after completion → terminal event immediately, then close (no hang) (AC-11) |
| `test_late_subscriber_gets_full_sequence` | Subscribing mid-run replays earlier events then live ones (EC-7) |
| `test_unknown_job_events_404` | `/events` on unknown id → 404 (AC-17) |

#### [NEW] `backend/tests/integration/test_api_report.py`
| Test | Verifies |
|------|----------|
| `test_download_markdown` | Completed job `/report?format=md` → `text/markdown` body (AC-12) |
| `test_download_json` | `/report?format=json` → `application/json` sibling (AC-12) |
| `test_report_before_ready_409` | `/report` on a still-running job → 409 (AC-14) |
| `test_report_path_only_from_record` | The served file is the record's `report_path` (+`.json`); no client path is honored (AC-13) |
| `test_missing_file_on_disk_404` | `report_path` set but file deleted → 404, and `report_available` in status is False (EC-8) |
| `test_report_unknown_job_404` | `/report` on unknown id → 404 (AC-17) |

#### [NEW] `backend/tests/integration/test_api_cors.py`
| Test | Verifies |
|------|----------|
| `test_preflight_allowed_origin_gets_header` | `OPTIONS` from `http://localhost:5173` → `Access-Control-Allow-Origin` present (AC-23) |
| `test_disallowed_origin_no_header` | An origin absent from the allowlist → no ACAO header (AC-23) |

#### [NEW] `backend/tests/integration/test_runner_graph_untouched.py`
| Test | Verifies |
|------|----------|
| `test_builder_not_modified_by_runner` | `build_graph().get_graph()` still ends `report → END`; the runner packages import `build_graph`/`deliver_report_sync` only (spec §1, AC-7) |
| `test_conditional_edge_count_unchanged` | Conditional sources remain the ingest guard + `route_on_risk` (constitution §2 invariant holds — the runner added none) |

---

## 3. Dependency & Import Map

```
app/config.py
    └── os, typing.Optional          # ALREADY imported — runner block adds no new import

app/runner/models.py
    └── enum, typing, pydantic (BaseModel, Field)      # boundary types (constitution §4)

app/runner/progress.py
    └── (stdlib only)                # canonical node→index map; no graph import

app/runner/core.py
    ├── logging, dataclasses, datetime, typing (stdlib)
    ├── app.graph.builder (build_graph)        # PUBLIC entrypoint — the only graph import
    ├── app.delivery (deliver_report_sync)     # PUBLIC entrypoint — feature 010
    └── app.runner.progress (node_index, TOTAL_STAGES)
        # NO app.graph.nodes.* import (AC-7)

app/runner/events.py
    ├── asyncio, threading (stdlib)
    └── app.runner.models (ProgressEvent)

app/runner/registry.py
    ├── threading, dataclasses, collections.OrderedDict, pathlib (stdlib)
    ├── app.runner.events (JobEventBuffer)
    └── app.runner.models (JobState, JobStatus, ErrorInfo)

app/runner/worker.py
    ├── logging, queue, threading, datetime (stdlib)
    ├── app.runner.core (run_pipeline, NodeProgress)
    ├── app.runner.models (JobState, ProgressEvent, ErrorInfo)
    └── app.runner.registry (JobRegistry, JobRecord)

app/runner/__main__.py   (CLI)
    ├── argparse, sys (stdlib)
    └── app.runner.core (run_pipeline, NodeProgress)      # SAME core as the API (D2)

app/api/main.py
    ├── asyncio, contextlib, logging (stdlib)
    ├── fastapi (FastAPI), fastapi.middleware.cors (CORSMiddleware), uvicorn
    ├── app.config (JOB_REGISTRY_MAX, RUNNER_WORKER_CONCURRENCY, CORS_ALLOWED_ORIGINS,
    │               API_BIND_HOST, API_BIND_PORT)
    ├── app.api.routes (router, RunnerContext)
    ├── app.runner.registry (JobRegistry)
    └── app.runner.worker (PipelineWorker)

app/api/routes.py
    ├── uuid, dataclasses, datetime, pathlib (stdlib)
    ├── fastapi (APIRouter, File, Form, HTTPException, Request, UploadFile)
    ├── fastapi.responses (FileResponse), sse_starlette.sse (EventSourceResponse)
    ├── app.config (UPLOAD_DIR, MAX_UPLOAD_SIZE_BYTES, ALLOWED_UPLOAD_EXTENSIONS)
    ├── app.runner.events (JobEventBuffer)
    ├── app.runner.models (AnalyzeAccepted, JobState)
    └── app.runner.registry (JobRecord)

app/api/__main__.py
    └── app.api.main (run)

app/graph/builder.py
    └── UNCHANGED (no runner import; the runner is the caller — spec §1)
```

**New runtime dependency:** `python-multipart` (multipart upload parsing) — **not** in
`002` §4; added to `pyproject.toml` (§2). `fastapi`, `uvicorn`, `sse-starlette`, `httpx`
(TestClient) are already in `002` §4. No other new dependency.

---

## 4. Implementation Order

TDD per constitution §7 — tests written and confirmed failing before implementation.

| Step | Action | Files |
|------|--------|-------|
| 0 | **Add `python-multipart` to `pyproject.toml` + record it in `002-tech-stack.md` §3e/§4 (M3); `.gitignore` `data/uploads/`** (gates the upload suite) | `pyproject.toml`, `specs/002-tech-stack.md`, `.gitignore` |
| 1 | Config tests for Runner/API constants (confirm failing) | `tests/unit/test_config.py` |
| 2 | Add the `# ── Runner / API layer` block | `app/config.py` |
| 3 | Run config tests (pass) | — |
| 4 | Boundary-model tests (failing) | `tests/unit/test_runner_models.py` |
| 5 | Implement `app/runner/models.py` (+ `runner/__init__.py`) | `app/runner/models.py` |
| 6 | Progress-map tests (failing) | `tests/unit/test_progress_map.py` |
| 7 | Implement `progress.py` | `app/runner/progress.py` |
| 8 | Runner-core tests (fake graph + stub delivery, failing) | `tests/unit/test_runner_core.py` |
| 8a | **Spike (review R2):** confirm the real `build_graph().stream(initial, stream_mode="values")` yields once per node with a changing `current_node`; if not, adopt the documented `stream_mode="updates"` fallback in `core.py` BEFORE Step 9 | — (throwaway spike) |
| 9 | Implement `core.py` (mode chosen by the spike) | `app/runner/core.py` |
| 10 | Event-buffer tests (failing) | `tests/unit/test_event_buffer.py` |
| 11 | Implement `events.py` | `app/runner/events.py` |
| 12 | Registry tests (failing) | `tests/unit/test_registry.py` |
| 13 | Implement `registry.py` | `app/runner/registry.py` |
| 14 | Worker tests (failing) | `tests/unit/test_worker.py` |
| 15 | Implement `worker.py` | `app/runner/worker.py` |
| 16 | CLI tests (failing) | `tests/unit/test_cli.py` |
| 17 | Implement `app/runner/__main__.py` | `app/runner/__main__.py` |
| 18 | API integration tests: analyze/jobs/sse/report/cors/graph-untouched (failing) | `tests/integration/test_api_*.py` |
| 19 | Implement `app/api/` (`__init__`, `main.py`, `routes.py`, `__main__.py`) | `app/api/*.py` |
| 20 | Run API integration tests (pass) | — |
| 21 | Full suite pass (all existing 418 + new) + `ruff`/`black` | all tests |

---

## 5. Design Decisions & Rationale

### Outer orchestration under `app/runner/` + `app/api/`, not a node (spec §1)
Placing the code in new top-level packages — not `app/graph/nodes/` — makes the "not the
8th node" boundary *structural*, exactly as feature 010 did with `app/delivery/`. Nothing
here is registered with `StateGraph`, `builder.py` is untouched, and
`test_runner_graph_untouched.py` locks it, so constitution §2's "exactly 7 nodes / 2
conditional edges" invariant is preserved by construction.

### One `run_pipeline` core, two entry points (spec D2)
The graph + delivery are invoked in exactly one function; the HTTP worker and the CLI both
call it with different `on_progress` sinks (event buffer vs. stderr). This guarantees the
CLI and API can't diverge in *what the pipeline does* — only in *how progress is surfaced*
— and it gives the feature-010 OAuth delivery smoke a real, serverless run path. Locked by
`test_worker_uses_run_pipeline` + `test_cli_uses_run_pipeline`.

### `stream_mode="values"` to get both progress and the terminal state (core)
Delivery needs the *whole* final `ContractState` (report_path, document_id,
original_filename, …). `stream_mode="values"` yields the full cumulative state per
super-step, so the last yield is the terminal state (no manual reducer merging) and the
just-run node is read from `state["current_node"]` for progress. This reuses the pinned
`current_node` convention (constitution §8) the nodes already maintain.

### Runner seeds `processing_started_at`, stamps `processing_completed_at` (spec §2.1; §1)
These pipeline-level, node-agnostic fields are written by no node (features 007/009 flagged
the gap and deliberately left it to the runner — report plan D2). `run_pipeline` seeds
`processing_started_at` in the initial state and stamps `processing_completed_at` after the
graph, filling the gap. Accepted limitation carried forward: because Node 7 renders the
report *before* the runner stamps completion, `processing_completed_at` is not in the
already-written report file — it lives in the returned state and the job record (this is
the same "a node can't render its own post-hoc timing" limitation the report plan §6
documented, not a defect).

### Single shared background worker, concurrency 1, queue excess (spec D4)
Local Ollama serializes generation, so parallel graph runs contend rather than speed up. A
single shared consumer (not per-request threads) keeps AC-20's off-loop guarantee and AC-4's
completion deterministic, and makes queueing (the `queued` `JobState`) the natural
backpressure — never `429`. Concurrency is configurable if a future non-local model changes
the calculus.

### Thread → async via a per-job replay buffer (spec §2.4, EC-7, AC-11)
The graph is synchronous in a worker thread; SSE consumers are async and may subscribe
late. `JobEventBuffer` snapshots the backlog **and** registers the live subscriber under one
lock (no lost-wakeup), and hands events across threads via `loop.call_soon_threadsafe`
(`asyncio.Queue` is not thread-safe to poke from another thread). A finished job's buffer is
`closed`, so a late `/events` open replays the terminal event and stops immediately (AC-11)
rather than hanging. This is the one genuinely subtle mechanism in the feature; it is spelled
out here so the implementation doesn't substitute a lossy broadcast.

### In-memory registry behind one interface (spec D5, AC-21; feature 012)
All job access goes through `JobRegistry`; handlers and the worker never touch a global dict.
Insertion-order eviction (not TTL) makes "oldest" deterministic and `test_eviction_keeps_last_n`
trivial. Because the seam is one object, feature 012 swaps it for a SQLite-backed store (and
adds the LangGraph checkpointer in `run_pipeline`) without touching handlers.

### CORS for a localhost allowlist (spec D7, AC-23)
D1's localhost binding does not make a browser `EventSource` from the Vite dev server
(`:5173`) to the API (`:8000`) same-origin — it's cross-origin and blocked without CORS even
on localhost. `CORSMiddleware` with the configurable allowlist unblocks exactly the frontend
origin(s) and nothing else.

### No auth, localhost bind (spec D1)
Phase-1 single-user local scope; auth/RBAC is PERMANENTLY CUT (constitution §2). Binding to
`127.0.0.1` (never `0.0.0.0`) is the security boundary; `test_bind_host_is_localhost` guards
against an accidental public bind.

### Logging strategy
Named loggers `contractsentinel.runner` / `.runner.worker` / `.api`. Per-run start/finish and
per-job failures are logged; all progress/telemetry that a client needs is in `JobStatus` /
SSE, never added to `ContractState` (the runner writes only `processing_*` to state, and only
in memory).

---

## 6. Risks & Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| A graph run blocks the request event loop | API unresponsive during minutes-long runs | Runs execute on a dedicated worker thread; handlers only enqueue; `test_response_not_blocked_by_run` locks AC-20 |
| Lost-wakeup: event fires between a late subscriber's status read and its stream subscribe | SSE misses the terminal event → client hangs | `JobEventBuffer.subscribe()` snapshots backlog + registers under one lock; `closed` short-circuits; `test_no_lost_wakeup` / `test_finished_job_stream_immediate_terminal` lock EC-7/AC-11 |
| Poking `asyncio.Queue` from the worker thread | Race / corruption | Cross-thread handoff via `loop.call_soon_threadsafe`; loop captured once at lifespan startup |
| Worker mutates `JobRecord` fields while a GET handler reads them (esp. `completed_nodes.append` vs `list(...)`) | Intermittent `RuntimeError`/torn read → 500s no single-threaded test catches | Per-record lock; ALL mutation via `mark_running`/`record_progress`/`mark_terminal`, `to_status()` snapshots under it; `test_concurrent_progress_and_to_status_no_race` locks it (review R1) |
| `stream_mode="values"` per-node granularity unproven (no code streams the graph today) | Progress/completed-node sequence wrong | Step-8a spike verifies it before committing `core.py`; documented `stream_mode="updates"` fallback (node name = dict key) needs no reducer replay since delivery reads only top-level keys (review R2) |
| `TestClient` created without the `with` form | Lifespan skipped → worker never starts → SSE/lifecycle tests hang | Fixture uses `with TestClient(create_app()) as c:`; SSE via `client.stream(...)`; called out in the integration fixture (review R3) |
| Worker still mid-run at test teardown (monkeypatch/`tmp_path` gone, captured loop closed) | Lingering `call_soon_threadsafe` publish → intermittent `RuntimeError: Event loop is closed`, cross-test flakiness | `stop()` **joins** each thread with a timeout (deterministic shutdown); the two AC-20 "held-job" tests `Event.set()` to release the job before the `with` block exits (review T1) |
| `python-multipart` missing | Upload endpoint 500s at request time | Added to `pyproject.toml` as Step 0; `002` update recommended to keep stack docs in sync |
| Path traversal via the report endpoint | Arbitrary file read | Path derived solely from `rec.report_path` + `.json`; `format` is a whitelist; no client path joined — `test_report_path_only_from_record` locks AC-13 |
| Oversized upload buffered fully before rejection | Memory blowup | Size enforced while streaming chunks to disk; abort + unlink at the cap (AC-16) |
| Unbounded registry growth over a long-lived process | Memory creep | Insertion-order cap `JOB_REGISTRY_MAX`; oldest evicted; `test_eviction_keeps_last_n` (D5) |
| One job's exception corrupts others | Cross-job failure | Each `_run_one` is independent and fully wrapped; failure sets only that record → FAILED; `test_exception_marks_failed_isolated` locks EC-2 |
| Ingest-error mistaken for a crash | Wrong status semantics | `ingest_error` in terminal state → `COMPLETED` + `ErrorInfo(kind="ingest_error")`; a raised exception → `FAILED`; distinct tests (EC-1 vs EC-2) |
| Records lost on restart surprise a client | Confusing 404s | Documented behavior (spec EC-9); feature 012 adds persistence; status semantics unchanged |
| Runner accidentally wired as a graph node | Violates constitution §2 | Code outside `app/graph/nodes/`; `builder.py` untouched; `test_runner_graph_untouched.py` locks it |
| Accidental public bind (`0.0.0.0`) | Exposure beyond localhost | `API_BIND_HOST` defaults `127.0.0.1`; `test_bind_host_is_localhost` guards D1 |
| Graph node renamed, progress map stale | Wrong/None progress index | `test_node_names_match_builder` cross-checks the map against `build_graph`; `node_index` returns `None` (no crash) for unknowns |

---

## 7. Out of Scope for This Plan

- **Durable persistence & mid-pipeline resume** — the SQLite job store (`aiosqlite`/
  `alembic`, `002` §f) and the LangGraph SQLite checkpointer (`002` §a). Owned by the
  future **feature 012**; this feature is in-memory and non-resumable (spec §5).
- **The 7 graph nodes and their edges** — features 003–009; the runner only *calls*
  `build_graph()` (spec §5). No node/edge added or modified.
- **MCP delivery mechanics** — Drive/Gmail transport, OAuth, retries — feature 010; the
  runner only invokes `deliver_report_sync()` and reports its result (spec §5).
- **Report content/formatting** — feature 009; the runner serves the already-written bytes
  (spec §5).
- **Authentication / authorization / multi-tenancy / RBAC** — PERMANENTLY CUT (constitution
  §2); localhost-only, no auth (spec §5, D1).
- **A frontend / UI** — this feature ships the HTTP + SSE contract the future `frontend/`
  consumes, no UI (spec §5).
- **Phase-2 concerns** — PrivacyAgent, encryption at rest, Zero-Storage, audit log,
  retention/scheduled cleanup of uploads/reports — DEFERRED (constitution §2); Phase-1 disk
  hygiene is manual (spec §5).
- **Horizontal scaling / multi-worker Uvicorn** — the in-memory registry assumes one worker;
  multi-worker correctness depends on 012's shared store (spec §5).
- **A runner-level wall-clock timeout** — none in Phase 1 (spec D6); nodes own their
  timeouts/circuit breakers.
- **Any `002-tech-stack.md` change beyond recording `python-multipart`** — the FastAPI/
  Uvicorn/SSE/SQLite stack is already listed (§2).

---

## 8. Reference: Constitution & Spec Traceability

- **Constitution §2** — the runner is an outer caller, not an 8th node; `builder.py`
  untouched, code under `app/runner/` + `app/api/` (this plan §1, §2, §5; spec §1). Auth/RBAC
  and MCP-beyond-Drive/Gmail stay CUT (spec §5).
- **Constitution §3** — all runner knobs (upload dir/size/extensions, concurrency, eviction
  cap, CORS allowlist, bind host/port) in `app/config.py` (§2 config block; AC-15/16/22/23).
- **Constitution §4** — Pydantic at the HTTP/SSE boundary (`app/runner/models.py`); internal
  `JobRecord` is a dataclass; graph state stays the `001` TypedDict (§2, §5).
- **Constitution §5** — partial-update discipline preserved: the runner writes only
  `processing_started_at`/`processing_completed_at` to state and does not fabricate node
  outputs (§5).
- **Constitution §6** — state minimality: the uploaded contract and the report stay on disk
  (file references); only paths/status live in the job record (§2, §5).
- **Constitution §7** — TDD order (§4).
- **Constitution §8** — model-separation: N/A (the runner makes zero LLM/embedding calls);
  progress reads the pinned `current_node` node-name convention (§5).
- **Constitution §9** — local-model latency: async job model + SSE progress + single-slot
  worker; **no** runner wall-clock cap that would pre-empt a slow local run (spec D3/D4/D6).
- **Constitution §10** — **no** `001` schema change: `processing_started_at` /
  `processing_completed_at` / `report_path` / `mcp_delivery_status` are pre-reserved `001`
  fields, now populated by the runner (§1, §5).
- **Constitution §11** — branch `feature/011-pipeline-runner-api` (top of this file).
- **Spec §6 D1–D7 + §6.1** — resolved decisions and the configuration surface carried into
  this plan §1, §2, §5.
```
