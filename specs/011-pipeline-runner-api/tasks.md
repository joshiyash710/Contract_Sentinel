# Pipeline Runner + API Implementation Tasks

Reference documents:
- Spec: `specs/011-pipeline-runner-api/spec.md`
- Plan: `specs/011-pipeline-runner-api/plan.md`
- State schema: `specs/001-contract-state-schema.md`
- Tech stack: `specs/002-tech-stack.md`
- Constitution: `specs/000-constitution.md`

All file paths below are relative to `backend/` unless stated otherwise.

**Workflow reminders:**
- Follow TDD per constitution §7 — write tests, confirm they FAIL, then implement to make them PASS.
- This feature is the **pipeline runner + FastAPI API + SSE progress streaming** — the pipeline's **outer orchestration boundary**. It accepts an uploaded contract, drives the compiled graph (`build_graph()`, feature 009) to `END`, then invokes the post-terminal delivery step (`deliver_report_sync()`, feature 010). Today both are called **only from tests**; this feature is the ignition.
- **It is NOT a graph node.** Constitution §2 fixes the graph at exactly 7 nodes / 2 conditional edges ending at `report → END`. This feature makes **ZERO** changes to `builder.py` — no `add_node`, no `add_edge`, no `add_conditional_edges`, no comment either. All new code lives under **two new top-level packages**: `app/runner/` (entry-agnostic core, worker, registry, event bus, CLI) and `app/api/` (FastAPI wiring) — deliberately **outside** `app/graph/nodes/`.
- **No existing test should change.** Because the graph is untouched, the current **418** tests (features 003–010) must remain **byte-for-byte unmodified** and still pass. If an existing test breaks, something leaked into the graph/config — do NOT "fix" it by editing the graph or an existing test.
- **The runner touches state minimally.** `run_pipeline` seeds ONLY `document_path` + `processing_started_at` in the initial state (spec AC-3/6) and stamps `processing_completed_at` after the graph — filling the pipeline-level gap features 007/009 deliberately left to the runner. It seeds **no** node-owned key.
- **Zero LLM / embedding calls** — the runner makes none. No `ollama`, no model/timeout/circuit-breaker constant (per-node timeouts live in the nodes' own config; spec D6).
- All knobs (upload dir/size/extensions, worker concurrency, eviction cap, CORS allowlist, bind host/port) live in `app/config.py` per constitution §3 — never hardcode inline.
- **Boundary Pydantic (constitution §4):** every HTTP/SSE request/response body is a Pydantic type in `app/runner/models.py`, validated at the boundary, never stored in graph state. The internal mutable `JobRecord` is a `@dataclass` (not a boundary type), projected to the Pydantic `JobStatus`. Graph state stays the `001` `ContractState` TypedDict.
- **Threading discipline (review R1):** the graph runs on a background worker THREAD while GET handlers read job state on the event LOOP. Every `JobRecord` field mutation and its `to_status()` projection go through the record's **own lock** — never direct attribute writes from the worker. The registry lock guards the dict of records; the record lock guards fields inside one record.
- **`asyncio_mode = "auto"` is already enabled** (feature 010, `pyproject.toml`), so bare `async def test_*` (event-buffer / SSE tests) run without `@pytest.mark.asyncio`. No gating change needed for async.
- **One core, two entry points (spec D2):** the API worker and the CLI (`python -m app.runner <file>`) BOTH call the single `run_pipeline` — no forked orchestration logic. The CLI is what lets the feature-010 Drive/Gmail OAuth delivery smoke run without a server.

**The seven locked design decisions (spec §6 D1–D7):**
- **D1** — Uvicorn binds `127.0.0.1` only; **no auth** (auth/RBAC PERMANENTLY CUT). Host/port configurable.
- **D2** — CLI runner in scope, sharing the exact `run_pipeline` core with the API (no forked logic).
- **D3** — async-only; no synchronous analyze-and-wait endpoint.
- **D4** — single shared background worker, default concurrency 1; excess submissions **queue** (never `429`), hence the `queued` `JobState`.
- **D5** — in-memory registry evicts by **insertion order**, keep last `N`; evicted id → `404` (≡ never-existed).
- **D6** — **no** runner-level wall-clock cap.
- **D7** — permissive **CORS** for a configurable localhost allowlist (default the Vite dev-server origin).
- Branch: `feature/011-pipeline-runner-api` per constitution §11.

---

## Task 0: Create feature branch

- [ ] Confirm `specs/011-pipeline-runner-api/spec.md`, `plan.md`, and `tasks.md` all exist and are approved (constitution §1 / §11 gate).
- [ ] From an up-to-date `main`, create and check out `feature/011-pipeline-runner-api` (the `git-start` skill does this mechanically).

**Why**: Per constitution §11, every feature is developed on its own branch. MCP delivery (010) is already merged to `main`.

**Verify**: `git branch --show-current` prints `feature/011-pipeline-runner-api`.

**Note**: The working tree has an untracked `specs/011-pipeline-runner-api/`. Confirm with the user whether the spec docs should be committed before branching, so 011 starts from a clean tree (same as prior features).

---

## Task 1: Add `python-multipart`, record it in the tech stack, git-ignore uploads (GATING — do first)

- [ ] Open `pyproject.toml` (in `backend/`). In `[project].dependencies`, add:
```toml
    "python-multipart>=0.0.9",
```
- [ ] Install it into the venv (`uv sync` / `pip install -e .` per the repo's workflow) so the import resolves.
- [ ] Open `specs/002-tech-stack.md` §3e ("Backend API Layer") and §4 (the `[project].dependencies` block) and add a one-line entry recording `python-multipart` as the multipart transport dependency for the upload endpoint (spec-first sync — plan review M3). Pure addition; no architectural change.
- [ ] Open the repo-root `.gitignore` and add `backend/data/uploads/` beside the existing `backend/data/reports/` (`.gitignore:33`) and `backend/data/secrets/` (`.gitignore:36`) lines so uploaded contracts are never committed.

**Why**: FastAPI's `multipart/form-data` parsing (`UploadFile` + `Form`, used by `POST /api/analyze`) requires `python-multipart`, which is NOT in `002` §4. Without it FastAPI raises at request time and the entire upload/API suite fails. This gates every API integration test (Task 18+).

**Verify**: `python -c "import multipart"` succeeds. `git status --porcelain` shows nothing under `data/uploads/` would be tracked. The existing 418 tests still pass.

---

## Task 2: Write config tests for the Runner/API constants (confirm FAILING)

- [ ] Open `tests/unit/test_config.py`
- [ ] Add 4 new test functions:

```python
def test_runner_api_constants_match_spec():
    """Verify Runner/API constants match specs/011 §6.1."""
    from app import config
    assert config.UPLOAD_DIR == "data/uploads"
    assert config.MAX_UPLOAD_SIZE_BYTES == 25 * 1024 * 1024
    assert config.ALLOWED_UPLOAD_EXTENSIONS == frozenset({".pdf", ".docx"})
    assert config.RUNNER_WORKER_CONCURRENCY == 1
    assert config.JOB_REGISTRY_MAX == 100
    assert tuple(config.CORS_ALLOWED_ORIGINS) == (
        "http://localhost:5173", "http://127.0.0.1:5173")
    assert config.API_BIND_HOST == "127.0.0.1"
    assert config.API_BIND_PORT == 8000


def test_upload_extensions_match_ingest():
    """The API's accepted extensions must mirror IngestAgent's, so the boundary and the
    node agree on what is a valid contract (drift lock — spec AC-15)."""
    from app import config
    from app.graph.nodes.ingest_agent import ALLOWED_EXTENSIONS
    assert set(config.ALLOWED_UPLOAD_EXTENSIONS) == set(ALLOWED_EXTENSIONS)


def test_bind_host_is_localhost():
    """D1: never an accidental public bind."""
    from app import config
    assert config.API_BIND_HOST == "127.0.0.1"


def test_runner_no_llm_constant():
    """The runner makes no LLM call — no model/timeout-LLM/circuit-breaker constant (D6)."""
    from app import config
    assert not hasattr(config, "RUNNER_MODEL_NAME")
    assert not hasattr(config, "RUNNER_TIMEOUT_SECONDS")
    assert not hasattr(config, "RUNNER_LLM_CIRCUIT_BREAKER_THRESHOLD")
```

**Verify**: Run `python -m pytest tests/unit/test_config.py -v` — the constant/extension/host tests must FAIL (`AttributeError`); the no-LLM test may already PASS. All existing config tests (Ingest → MCP delivery) must still PASS.

---

## Task 3: Add the Runner/API constants to config

- [ ] Open `app/config.py`. It already imports `os` and `Optional` at the top — **no new import** needed.
- [ ] Append a new `# ── Runner / API layer` block at the end (pure addition — no rename), exactly per plan §2:

```python
# ── Runner / API layer ─────────────────────────────────────────────────────────
# Source: specs/011-pipeline-runner-api/spec.md §6.1

UPLOAD_DIR: str = "data/uploads"
# Directory (backend/-relative, mirroring REPORT_OUTPUT_DIR) where submitted contract
# files are persisted as document_path before the graph runs (constitution §6 — state
# minimality: the file is a reference, not embedded in state). Created if absent.

MAX_UPLOAD_SIZE_BYTES: int = 25 * 1024 * 1024   # 25 MB
# Boundary reject → 413 (spec AC-16). Enforced while streaming the upload.

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

- [ ] Do NOT add any LLM/model/timeout/circuit-breaker constant.

**Verify**: Run `python -m pytest tests/unit/test_config.py -v` — all config tests (through Runner/API) must PASS.

---

## Task 4: Write unit tests for the boundary Pydantic models (confirm FAILING)

- [ ] Create file `tests/unit/test_runner_models.py`
- [ ] The import `from app.runner.models import JobState, ErrorInfo, AnalyzeAccepted, JobStatus, ProgressEvent` will fail until Task 5.
- [ ] Write these 4 test functions (plan §2 model matrix):

| Test function | Verifies |
|---------------|----------|
| `test_jobstate_values` | `JobState` values are exactly `queued/running/completed/failed` (spec §2.3) |
| `test_jobstatus_defaults` | `JobStatus(...)` minimal build → `completed_nodes == []`, `mcp_delivery_status == {}`, `report_available is False`, optionals `None` |
| `test_progressevent_roundtrips` | `ProgressEvent(event="completed", job_id="x", final=JobStatus(...))` round-trips via `model_dump_json()`/parse; `final` embeds a `JobStatus` |
| `test_analyze_accepted_shape` | `AnalyzeAccepted` requires `job_id`, `status`, `submitted_at`; a valid one constructs |

**Verify**: Run `python -m pytest tests/unit/test_runner_models.py -v` — all 4 must FAIL (ImportError).

---

## Task 5: Implement the boundary Pydantic models

- [ ] Create the package: `app/runner/__init__.py` (docstring only for now; the `run_pipeline`/`RunResult`/`NodeProgress` re-exports are added in Task 9 — a bare docstring keeps imports clean meanwhile).
- [ ] Create file `app/runner/models.py` exactly per plan §2 ("Boundary Pydantic Models"): `JobState(str, Enum)`, `ErrorInfo`, `AnalyzeAccepted`, `JobStatus`, `ProgressEvent`.
- [ ] **Imports**: `from enum import Enum`; `from typing import Dict, List, Optional`; `from pydantic import BaseModel, Field`. No graph/state import.
- [ ] Module docstring: these are **boundary types** (constitution §4), validated at the HTTP/SSE boundary, never stored in graph state; `JobState` is a runner concept distinct from `001`'s `ValidationStatus`/`MCPDeliveryStatus`.

**Verify**: Run `python -m pytest tests/unit/test_runner_models.py -v` — all 4 must PASS.

---

## Task 6: Write unit tests for the progress map (confirm FAILING)

- [ ] Create file `tests/unit/test_progress_map.py`
- [ ] The import `from app.runner.progress import NODE_INDEX, TOTAL_STAGES, node_index` will fail until Task 7.
- [ ] Write these 4 test functions (plan §2 progress matrix — Gap B):

| Test function | Verifies |
|---------------|----------|
| `test_redline_and_skip_share_index_6` | `NODE_INDEX["redline"] == NODE_INDEX["skip_redline"] == 6` (branching graph maps 1:1 to names) |
| `test_indices_cover_seven_stages` | The distinct index values are exactly `{1,2,3,4,5,6,7}`; `TOTAL_STAGES == 7` |
| `test_node_names_match_builder` | Every `NODE_INDEX` key is a node name `build_graph()` actually registers (inspect `build_graph().get_graph()` nodes) — guards against a graph-node rename silently breaking progress |
| `test_unknown_node_returns_none` | `node_index("nope") is None` (defensive — no raise) |

**Verify**: Run `python -m pytest tests/unit/test_progress_map.py -v` — all 4 must FAIL (ImportError).

---

## Task 7: Implement `progress.py`

- [ ] Create file `app/runner/progress.py` exactly per plan §2 ("Progress Map"): the `NODE_INDEX` dict (`redline` and `skip_redline` both → 6), `TOTAL_STAGES = 7`, and `node_index(node_name) -> int | None` (`.get`, no raise).
- [ ] Stdlib only — no graph import.

**Verify**: Run `python -m pytest tests/unit/test_progress_map.py -v` — all 4 must PASS.

---

## Task 8: Write unit tests for the runner core (confirm FAILING)

- [ ] Create file `tests/unit/test_runner_core.py`
- [ ] The import `from app.runner.core import run_pipeline, RunResult, NodeProgress` will fail until Task 9.
- [ ] Patch `app.runner.core.build_graph` to return a **fake compiled graph** whose `.stream(initial, stream_mode="values")` yields a scripted list of full-state dicts (each carrying a `current_node`, the last one terminal with `report_path`/`document_id`), and patch `app.runner.core.deliver_report_sync` with a stub returning `{"mcp_delivery_status": {...}}`. Capture the `initial` dict the fake `.stream` was called with.
- [ ] Write these 10 test functions (plan §2 core matrix):

| Test function | Verifies |
|---------------|----------|
| `test_seeds_only_document_path_and_started_at` | The `initial` state passed to `.stream` has keys ⊆ `{document_path, processing_started_at}` (spec AC-3/6) |
| `test_build_graph_called_once` | `build_graph` invoked exactly once per `run_pipeline` (AC-6) |
| `test_progress_callback_per_node` | `on_progress` fires once per DISTINCT `current_node`, in order, with the mapped `index` and `total == 7` (AC-9 basis) |
| `test_redline_branch_indices` | A scripted `redline` path emits index 6 for `redline`; a `skip_redline` script emits 6 for `skip_redline` |
| `test_delivery_called_with_recipient` | `deliver_report_sync` called with the passed `recipient`; omitted → `None` (AC-5) |
| `test_final_state_has_completed_timestamp` | `RunResult.final_state["processing_completed_at"]` is set by the runner (§ closes the D2 gap) |
| `test_result_carries_report_path_and_delivery` | `RunResult.report_path` / `.mcp_delivery_status` come from the terminal state / delivery return |
| `test_ingest_error_surfaced_not_raised` | Scripted terminal state with `ingest_error` → `RunResult.ingest_error` set, NO exception (EC-1) |
| `test_graph_exception_propagates` | Fake `.stream` raising propagates out of `run_pipeline` (caller converts to FAILED — EC-2) |
| `test_only_public_entrypoints_imported` | `inspect.getsource(app.runner.core)` references `build_graph` + `deliver_report_sync` only — NO `app.graph.nodes.` substring (AC-7) |

**Verify**: Run `python -m pytest tests/unit/test_runner_core.py -v` — all 10 must FAIL (ImportError).

---

## Task 9: Implement `core.py` (spike the stream mode first)

- [ ] **Spike (review R2) — do BEFORE writing the loop.** In a throwaway script/REPL, run the REAL `build_graph().stream({"document_path": <a tiny fixture>, "processing_started_at": ...}, stream_mode="values")` (or against a mocked-node graph) and confirm it yields **once per node with a changing `current_node`**. If `values`-mode granularity disappoints, adopt the documented fallback: `stream_mode="updates"` (each yield `{node_name: delta}` — node name is the dict key) and shallow-accumulate deltas into `final_state` (sufficient because delivery reads only top-level keys). Record which mode you chose in a code comment. Delete the spike.
- [ ] Create file `app/runner/core.py` exactly per plan §2 ("Runner Core"): `_now_iso`, `NodeProgress` (dataclass), `RunResult` (dataclass — **no `completed_nodes` field**, review M1), and `run_pipeline(document_path, *, recipient=None, on_progress=None) -> RunResult`.
- [ ] **Imports**: `logging`, `from dataclasses import dataclass`, `from datetime import datetime, timezone`, `from typing import Callable, Optional`; `from app.graph.builder import build_graph`; `from app.delivery import deliver_report_sync`; `from app.runner.progress import node_index, TOTAL_STAGES`. **No `app.graph.nodes.*` import** (AC-7).
- [ ] Flow: seed `initial = {"document_path": ..., "processing_started_at": _now_iso()}`; iterate the chosen stream mode keeping the last full state as `final_state` and emitting one `on_progress(NodeProgress(node, node_index(node), TOTAL_STAGES, timing))` per distinct node (dedup on `last_node`); call `deliver_report_sync(final_state, recipient=recipient)`; merge its `mcp_delivery_status`; stamp `processing_completed_at`; return `RunResult`.
- [ ] Update `app/runner/__init__.py` to re-export `run_pipeline`, `RunResult`, `NodeProgress`.

**Verify**: Run `python -m pytest tests/unit/test_runner_core.py -v` — all 10 must PASS.

---

## Task 10: Write unit tests for the per-job event buffer (confirm FAILING)

- [ ] Create file `tests/unit/test_event_buffer.py`
- [ ] The import `from app.runner.events import JobEventBuffer` will fail until Task 11.
- [ ] Construct a buffer with a real running loop (`asyncio.get_running_loop()` inside an `async def` test; `asyncio_mode="auto"` collects it). Publish `ProgressEvent`s from the test (simulating the worker) and consume via `subscribe()`.
- [ ] Write these 6 test functions (plan §2 event-buffer matrix):

| Test function | Verifies |
|---------------|----------|
| `test_live_subscriber_receives_events` | `subscribe()` then `publish(ev)` → the returned queue yields `ev` |
| `test_late_subscriber_replays_backlog` | `publish` 3 events, THEN `subscribe()` → the backlog contains all 3 (EC-7) |
| `test_finished_job_replays_terminal_and_closes` | `publish` a terminal (`completed`) event, then `subscribe()` → backlog includes the terminal, `closed is True`, queue is `None` (AC-11) |
| `test_no_lost_wakeup` | Interleave `publish` + `subscribe` under contention → every event reaches the subscriber exactly once, terminal never dropped (EC-7) |
| `test_unsubscribe_removes_queue` | After `unsubscribe(q)`, a later `publish` does not target `q` (EC-6 — client disconnect) |
| `test_publish_is_thread_safe` | Concurrent `publish` from multiple threads → backlog length == total published, no corruption |

**Verify**: Run `python -m pytest tests/unit/test_event_buffer.py -v` — all 6 must FAIL (ImportError).

---

## Task 11: Implement `events.py`

- [ ] Create file `app/runner/events.py` exactly per plan §2 ("Per-Job Event Buffer"): `JobEventBuffer(loop)` with `publish` (worker thread; appends under a `threading.Lock`, sets `_closed` on terminal, hands each event to every subscriber via `loop.call_soon_threadsafe(q.put_nowait, event)`), `subscribe` (snapshots backlog AND registers the new `asyncio.Queue` under ONE lock — the no-lost-wakeup guarantee; returns `(backlog, queue|None, closed)`), and `unsubscribe`.
- [ ] **Imports**: `asyncio`, `threading`, `from typing import Optional`; `from app.runner.models import ProgressEvent`.

**Verify**: Run `python -m pytest tests/unit/test_event_buffer.py -v` — all 6 must PASS.

---

## Task 12: Write unit tests for the job registry + record locking (confirm FAILING)

- [ ] Create file `tests/unit/test_registry.py`
- [ ] The import `from app.runner.registry import JobRegistry, JobRecord` will fail until Task 13. Build a `JobRecord` with a dummy `JobEventBuffer` (a running loop, or a `MagicMock` where the buffer isn't exercised).
- [ ] Write these 7 test functions (plan §2 registry matrix, incl. the review-R1 race test):

| Test function | Verifies |
|---------------|----------|
| `test_add_and_get` | An added record is retrievable by id; an unknown id → `None` (AC-17 basis) |
| `test_eviction_keeps_last_n` | `JobRegistry(max_jobs=N)`; adding `N+1` evicts the oldest by insertion order; `get(oldest)` → `None` (AC-22, D5) |
| `test_record_lock_methods_mutate` | `mark_running`/`record_progress`/`mark_terminal` update fields; `to_status()` reflects them |
| `test_concurrent_progress_and_to_status_no_race` | One thread calls `record_progress` in a tight loop while another repeatedly calls `to_status()` → **no `RuntimeError`**, every `completed_nodes` snapshot is internally consistent (review R1) |
| `test_to_status_report_available_reflects_disk` | `report_available` is True only when the file at `report_path` exists, not merely when `report_path` is set (EC-8) |
| `test_delivery_status_enum_coerced` | An `MCPDeliveryStatus` enum in `mcp_delivery_status` → its `.value` string in the projected `JobStatus` |
| `test_registry_is_single_seam` | A fake registry object (same `add`/`get` surface) substitutes into a handler/worker with no other patching — the 012-swap property (AC-21) |

**Verify**: Run `python -m pytest tests/unit/test_registry.py -v` — all 7 must FAIL (ImportError). (`test_concurrent_progress_and_to_status_no_race` is the one that would flakily FAIL against a naive lock-free implementation — it must pass deterministically after Task 13.)

---

## Task 13: Implement `registry.py`

- [ ] Create file `app/runner/registry.py` exactly per plan §2 ("In-Memory Job Registry"):
  - `JobRecord` (`@dataclass`) with a per-record `_lock: threading.Lock = field(default_factory=threading.Lock, repr=False, compare=False)` and the mutation methods `mark_running`, `record_progress`, `mark_terminal`, plus `to_status()` — **all taking `self._lock`**; `to_status()` copies `completed_nodes` **under the lock** and computes `report_available` from disk (EC-8). NO direct external field writes (review R1).
  - `JobRegistry(max_jobs)` with a dict-guarding `threading.Lock`, `add` (insertion-order cap → `OrderedDict.popitem(last=False)` eviction), `get`. **No `update` method** — all field mutation flows through the record's lock methods.
  - `_coerce_status(...)` helper normalizing each `MCPDeliveryInfo`'s `status` enum to `.value`.
- [ ] **Imports**: `threading`, `from collections import OrderedDict`, `from dataclasses import dataclass, field`, `from pathlib import Path`, `from typing import Optional`; `from app.runner.events import JobEventBuffer`; `from app.runner.models import JobState, JobStatus, ErrorInfo`.

**Verify**: Run `python -m pytest tests/unit/test_registry.py -v` — all 7 must PASS (including the concurrency race test, run it a few times to confirm it is not flaky).

---

## Task 14: Write unit tests for the background worker (confirm FAILING)

- [ ] Create file `tests/unit/test_worker.py`
- [ ] The import `from app.runner.worker import PipelineWorker` will fail until Task 15.
- [ ] Patch `app.runner.worker.run_pipeline` with a controllable stub (use a `threading.Event` to hold a job "running" so concurrency is observable; another stub returns an `ingest_error` `RunResult`; another raises). Build a real `JobRegistry` + `JobRecord`s (with a real `JobEventBuffer` on a running loop). Start the worker, `submit(job_id)`, and `_wait_for` the record status.
- [ ] Write these 6 test functions (plan §2 worker matrix):

| Test function | Verifies |
|---------------|----------|
| `test_single_shared_worker_serializes` | concurrency=1: submit two; while the first is held "running", the second stays `queued`; it runs only after the first finishes (AC-20, D4) |
| `test_completed_status_and_terminal_event` | On success → record `COMPLETED`, `report_path`/`mcp_delivery_status`/`finished_at` set, a terminal `completed` `ProgressEvent` published to the buffer (AC-4/9/10) |
| `test_ingest_error_marks_completed_with_error` | Stub returns `ingest_error` → record `COMPLETED` + `error.kind == "ingest_error"` with the extracted `message` (EC-1, review M2) |
| `test_exception_marks_failed_isolated` | Stub raises for job A → A `FAILED` with `error`; a separately-submitted job B still `COMPLETED` (EC-2) |
| `test_worker_uses_run_pipeline` | The worker calls `run_pipeline` (shared core — D2), with the record's `document_path` + `recipient` |
| `test_evicted_job_skipped` | A job id whose record was evicted before it ran is a no-op (no crash) when dequeued (D5) |

**Verify**: Run `python -m pytest tests/unit/test_worker.py -v` — all 6 must FAIL (ImportError).

---

## Task 15: Implement `worker.py`

- [ ] Create file `app/runner/worker.py` exactly per plan §2 ("Background Worker"): `PipelineWorker(registry, concurrency=1)` with a `queue.Queue`, `start()` (spawns `concurrency` daemon threads), `submit(job_id)`, `stop(join_timeout=5.0)`, `_loop`, and `_run_one`.
- [ ] **Deterministic shutdown (review T1):** `stop()` sets the stop event, enqueues one sentinel per thread, **then `t.join(timeout=join_timeout)` for each thread** — so no worker is still mid-run after `lifespan` shutdown returns. This matters because the SSE path publishes via `loop.call_soon_threadsafe` onto the loop captured at startup; a worker that publishes after that loop closes raises `RuntimeError: Event loop is closed` (intermittent, cross-test). Daemon threads still prevent a hard hang if a run genuinely wedges past the timeout.
- [ ] `_run_one`: `registry.get(job_id)` (skip if `None` — evicted); `rec.mark_running(_now_iso())`; define `_on_progress` calling `rec.record_progress(p.node)` then `rec.buffer.publish(ProgressEvent(event="progress", ...))`; `try:` call `run_pipeline(rec.document_path, recipient=rec.recipient, on_progress=_on_progress)`, build `error` from `result.ingest_error.get("message")` (review M2) when present, `rec.mark_terminal(status=COMPLETED, ...)`, publish a `completed` terminal event; `except Exception as exc:` log, `rec.mark_terminal(status=FAILED, ..., error=ErrorInfo(kind="runner_exception", message=str(exc)))`, publish a `failed` terminal event. **Only `mark_*`/`record_progress` — never direct `rec.field =` writes (review R1).**
- [ ] **Imports**: `logging`, `queue`, `threading`, `from datetime import datetime, timezone`; `from app.runner.core import run_pipeline, NodeProgress`; `from app.runner.models import JobState, ProgressEvent, ErrorInfo`; `from app.runner.registry import JobRegistry, JobRecord`. Define `_SENTINEL = object()` and a local `_now_iso`.

**Verify**: Run `python -m pytest tests/unit/test_worker.py -v` — all 6 must PASS.

---

## Task 16: Write unit tests for the CLI (confirm FAILING)

- [ ] Create file `tests/unit/test_cli.py`
- [ ] The import `from app.runner.__main__ import main` will fail until Task 17. Patch `app.runner.__main__.run_pipeline`.
- [ ] Write these 5 test functions (plan §2 CLI matrix):

| Test function | Verifies |
|---------------|----------|
| `test_cli_uses_run_pipeline` | `main(["c.pdf"])` calls `run_pipeline("c.pdf", recipient=None, on_progress=<callable>)` — shared core (D2) |
| `test_cli_passes_recipient` | `main(["c.pdf", "--recipient", "x@y.z"])` → `run_pipeline(..., recipient="x@y.z")` |
| `test_cli_prints_report_path` | On a success `RunResult`, stdout contains `report_path`; return code 0 |
| `test_cli_ingest_error_exit_2` | `RunResult.ingest_error` set → return code 2, ingest error printed to stderr (EC-1) |
| `test_cli_exception_exit_1` | `run_pipeline` raising → stderr error, return code 1 (EC-2) |

**Verify**: Run `python -m pytest tests/unit/test_cli.py -v` — all 5 must FAIL (ImportError).

---

## Task 17: Implement the CLI (`app/runner/__main__.py`)

- [ ] Create file `app/runner/__main__.py` exactly per plan §2 ("CLI Entry Point"): `main(argv=None) -> int` using `argparse` (`file` positional, `--recipient` optional), an `_on_progress` printing `[index/total] node` to **stderr**, `try: run_pipeline(...)` → print `report_path` + `delivery` to **stdout**, return 0 (or 2 on `ingest_error`); `except Exception` → stderr + return 1. `if __name__ == "__main__": raise SystemExit(main())`.
- [ ] **Imports**: `argparse`, `sys`; `from app.runner.core import run_pipeline, NodeProgress`. Shares the exact core with the API — **no forked logic** (D2).

**Verify**: Run `python -m pytest tests/unit/test_cli.py -v` — all 5 must PASS.

---

## Task 18: Write the API integration tests + fixture (confirm FAILING)

- [ ] Add a `client` fixture to `tests/integration/conftest.py` (it already has an autouse `_isolate_report_output`). The fixture MUST use the **context-manager form so lifespan runs** (review R3):

```python
@pytest.fixture
def client(monkeypatch, tmp_path):
    import app.config as _config
    from app.api.main import create_app
    from starlette.testclient import TestClient
    monkeypatch.setattr("app.runner.core.build_graph", _fake_build_graph)      # fast, scripted
    monkeypatch.setattr("app.runner.core.deliver_report_sync", _stub_delivery)
    monkeypatch.setattr(_config, "UPLOAD_DIR", str(tmp_path / "uploads"))
    # NOTE (review T2): do NOT re-patch report_agent.REPORT_OUTPUT_DIR here — the autouse
    # _isolate_report_output (conftest:14) already redirects it to tmp_path/reports. And since
    # build_graph is FAKED, the real report_agent never runs, so REPORT_OUTPUT_DIR is moot for
    # these tests: what matters is that _fake_build_graph writes its own report files under
    # tmp_path and puts that .md path in the terminal state it yields.
    with TestClient(create_app()) as c:      # <-- runs lifespan → worker starts, loop captured
        yield c
```

  - Provide `_fake_build_graph()` → an object whose `.stream(initial, stream_mode=...)` yields scripted full states. Default = the 7-node happy path; on the terminal state it **writes BOTH report siblings** to a `tmp_path` dir — `{stem}.md` **and** `{stem}.json` (review T3) — and sets `report_path` to the `.md`, so `/report?format=json` (AC-12) and the `md_path.with_suffix(".json")` resolution (EC-8) both work. Parametrizable to an `ingest_error` short-circuit (yields one state with `ingest_error` set, no report file) and to a `.stream` that raises. `_stub_delivery(state, *, recipient=None)` → `{"mcp_delivery_status": {...}}` (parametrizable to a FAILED channel and to `{}` for disabled). A `_wait_for(client, job_id, state, timeout=5)` polling helper.
  - **Patch `build_graph`/`deliver_report_sync` on `app.runner.core`** (where they are imported and called), not on their defining modules.
  - Consume SSE with the streaming form: `with client.stream("GET", f"/api/jobs/{job_id}/events") as r:` then iterate `r.iter_lines()`.
  - **Held-job cleanup (review T1):** the two AC-20 tests that hold a job "running" via a `threading.Event` (`test_response_not_blocked_by_run`, `test_single_shared_worker_serializes`) MUST `event.set()` to release the job **before** the `with TestClient` block exits — otherwise the worker is mid-run at teardown when `stop()`/loop-close happen. With Task 15's joining `stop()` this is deterministic, but the held job must be released so `stop()`'s join doesn't wait out its full timeout.
- [ ] Create the 6 integration test files; the imports of `app.api.main.create_app` will fail until Task 19. Write these functions (plan §2 integration matrix):

`tests/integration/test_api_analyze.py` (8):
| Test | Verifies |
|------|----------|
| `test_analyze_pdf_returns_202` | valid `.pdf` → 202 + `job_id`; immediate status `queued`/`running`, never `completed` (AC-1) |
| `test_analyze_docx_accepted` | `.docx` accepted identically (AC-2) |
| `test_upload_saved_and_path_passed` | bytes land under `UPLOAD_DIR`; the path handed to the fake graph == `state["document_path"]` (AC-3) |
| `test_recipient_forwarded` | `recipient` form field reaches `deliver_report_sync(recipient=...)` (AC-5) |
| `test_unsupported_extension_400_no_job` | `.txt` → 400, no job created (AC-15) |
| `test_oversized_413` | file > `MAX_UPLOAD_SIZE_BYTES` → 413 (AC-16) |
| `test_empty_upload_400` | zero-byte file → 400, no job (EC-5) |
| `test_response_not_blocked_by_run` | with a slow fake graph, the 202 returns while the job is still `running` (AC-20) |

`tests/integration/test_api_jobs.py` (8):
| Test | Verifies |
|------|----------|
| `test_job_lifecycle_to_completed` | after the fake run, status → `completed`, `report_available True`, `finished_at` set (AC-4) |
| `test_unknown_job_404` | `GET /api/jobs/{random}` → 404 (AC-17) |
| `test_health_ok` | `GET /api/health` → 200 `{"status":"ok"}` (AC-18) |
| `test_two_jobs_independent` | two submissions → two ids tracked independently (AC-19) |
| `test_ingest_error_completes_with_error` | fake graph sets `ingest_error` → job `completed`, `error.kind=="ingest_error"` (EC-1) |
| `test_graph_exception_marks_failed` | fake graph raises → job `failed` with `error`; a second job still completes (EC-2) |
| `test_delivery_status_surfaced` | asserts BOTH branches (review T4): a stub returning a FAILED channel → it surfaces in `mcp_delivery_status`, job still `completed` (EC-3); a stub returning `{}` → empty map, job still `completed` (EC-4) |
| `test_eviction_returns_404` | small `JOB_REGISTRY_MAX`; exceed it → oldest job `GET` → 404 (AC-22) |

`tests/integration/test_api_sse.py` (6):
| Test | Verifies |
|------|----------|
| `test_event_stream_content_type` | `/events` → `text/event-stream` (AC-9) |
| `test_progress_then_terminal_then_close` | one `progress` per node entered, in order, then exactly one terminal event, then the stream closes (AC-9) |
| `test_terminal_final_equals_status` | terminal event's `final` equals `GET /api/jobs/{id}` at that moment (AC-10) |
| `test_finished_job_stream_immediate_terminal` | opening `/events` after completion → terminal event immediately, no hang (AC-11) |
| `test_late_subscriber_gets_full_sequence` | subscribing mid-run replays earlier events then live ones (EC-7) |
| `test_unknown_job_events_404` | `/events` on unknown id → 404 (AC-17) |

`tests/integration/test_api_report.py` (6):
| Test | Verifies |
|------|----------|
| `test_download_markdown` | completed job `/report?format=md` → `text/markdown` body (AC-12) |
| `test_download_json` | `/report?format=json` → `application/json` sibling (AC-12) |
| `test_report_before_ready_409` | `/report` on a still-running job → 409 (AC-14) |
| `test_report_path_only_from_record` | served file is the record's `report_path` (+`.json`); no client path honored (AC-13) |
| `test_missing_file_on_disk_404` | `report_path` set but file deleted → 404; `report_available` False (EC-8) |
| `test_report_unknown_job_404` | `/report` on unknown id → 404 (AC-17) |

`tests/integration/test_api_cors.py` (2):
| Test | Verifies |
|------|----------|
| `test_preflight_allowed_origin_gets_header` | `OPTIONS` from `http://localhost:5173` → `Access-Control-Allow-Origin` present (AC-23) |
| `test_disallowed_origin_no_header` | an origin absent from the allowlist → no ACAO header (AC-23) |

`tests/integration/test_runner_graph_untouched.py` (2):
| Test | Verifies |
|------|----------|
| `test_builder_not_modified_by_runner` | `build_graph().get_graph()` still ends `report → END`; the runner packages import `build_graph`/`deliver_report_sync` only (spec §1, AC-7) |
| `test_conditional_edge_count_unchanged` | conditional sources remain the ingest guard + `route_on_risk` (constitution §2 invariant holds) |

**Verify**: Run `python -m pytest tests/integration/test_api_*.py tests/integration/test_runner_graph_untouched.py -v` — all 32 must FAIL (ImportError on `create_app`).

---

## Task 19: Implement the FastAPI application (`app/api/`)

- [ ] Create `app/api/__init__.py` (package marker; docstring: FastAPI app for the runner).
- [ ] Create `app/api/main.py` exactly per plan §2 ("FastAPI Application"): the `lifespan` async context manager (captures `asyncio.get_running_loop()`, builds `JobRegistry(max_jobs=JOB_REGISTRY_MAX)` + `PipelineWorker(registry, concurrency=RUNNER_WORKER_CONCURRENCY)`, `worker.start()`, stores `RunnerContext(registry, worker, loop)` on `app.state.ctx`, `worker.stop()` on shutdown); `create_app()` (adds `CORSMiddleware` with `allow_origins=list(CORS_ALLOWED_ORIGINS)`, includes the router); module-level `app = create_app()`; `run()` → `uvicorn.run(app, host=API_BIND_HOST, port=API_BIND_PORT)`.
- [ ] Create `app/api/__main__.py` → `from app.api.main import run` then `run()` (enables `python -m app.api`).
- [ ] Create `app/api/routes.py` exactly per plan §2 ("routes.py"): `RunnerContext` dataclass; `router = APIRouter(prefix="/api")`; the 5 endpoints:
  - `GET /health` → `{"status":"ok"}`.
  - `POST /analyze` (status 202) — validate `ext in ALLOWED_UPLOAD_EXTENSIONS` else 400; stream-write to `UPLOAD_DIR/{uuid}{ext}` enforcing `MAX_UPLOAD_SIZE_BYTES` (→ 413, unlink partial) and rejecting empty (→ 400); build a `JobRecord` (with `JobEventBuffer(ctx.loop)`), `ctx.registry.add(rec)`, `ctx.worker.submit(job_id)`; return `AnalyzeAccepted`.
  - `GET /jobs/{job_id}` → 404 or `rec.to_status()`.
  - `GET /jobs/{job_id}/events` → 404, else `EventSourceResponse` over an async generator that replays `buffer.subscribe()` backlog, stops if `closed`, else `await q.get()` until a terminal event, `unsubscribe` in `finally` (EC-6).
  - `GET /jobs/{job_id}/report?format=md|json` → 404 (no job); 409 (not `COMPLETED`/no `report_path`); resolve `md_path = Path(rec.report_path)` (+`.json` sibling for json — **only from the record**, AC-13); 404 if the file is missing on disk (EC-8); `FileResponse` with the right media type.
- [ ] **Imports** per plan §3 (fastapi, `fastapi.responses.FileResponse`, `sse_starlette.sse.EventSourceResponse`, config, runner packages). **No `builder.py` import; the runner never touches the graph module** beyond `run_pipeline`.

**Verify**: Run `python -m pytest tests/integration/test_api_*.py tests/integration/test_runner_graph_untouched.py -v` — all 32 must PASS.

---

## Task 20: Full test suite pass (NO regressions expected)

- [ ] Run the complete suite:
```
python -m pytest tests/ -v --tb=short
```
- [ ] **All existing 418 tests (features 003–010) must still pass, UNMODIFIED.** This feature adds an outer caller and changes **nothing** in the graph, so there are no regression fix-ups. If any existing test changes behavior, STOP: the runner has leaked into the graph/config. Do not edit existing tests to make them pass.
- [ ] Expected NEW test count for feature 011: 4 (config) + 4 (models) + 4 (progress) + 10 (core) + 6 (events) + 7 (registry) + 6 (worker) + 5 (cli) + 8 (analyze) + 8 (jobs) + 6 (sse) + 6 (report) + 2 (cors) + 2 (graph-untouched) = **78 new tests**. Total suite: 418 + 78 = **496**.
- [ ] OCR-gated IngestAgent tests may skip if Tesseract is absent — acceptable. **No runner/API test requires a live Ollama, real Google, or the network** — `build_graph`/`deliver_report_sync` are mocked/stubbed in every automated test (spec AC-8). Re-run the suite a couple of times to confirm the threading test (`test_concurrent_progress_and_to_status_no_race`) and SSE tests are not flaky.

---

## Task 21: Linting and type checking

- [ ] Run `black app/ tests/` — auto-format.
- [ ] Run `ruff check app/ tests/` — no lint errors (new `app/runner/` + `app/api/` trees; the async event-buffer/SSE code).
- [ ] Run `mypy app/` — no type errors (if installed). The Pydantic boundary models and dataclasses are fully typed; add narrow `# type: ignore[...]` only if genuinely needed for untyped `sse_starlette`/`uvicorn` surfaces — do NOT broaden.
- [ ] Do NOT weaken tests to satisfy lint/type checks — fix the implementation instead (constitution §7).

---

## Task 22: Manual run smoke (optional, not in the automated suite)

- [ ] **CLI smoke (also unblocks the feature-010 OAuth delivery smoke).** With a provisioned Google OAuth token at `GOOGLE_OAUTH_TOKEN_PATH` (feature 010, one-time setup) and `CONTRACTSENTINEL_DELIVERY_RECIPIENT` set, run `python -m app.runner <a real .pdf/.docx>` and confirm: progress prints per node to stderr; a report appears under `REPORT_OUTPUT_DIR`; the report is delivered to Drive/Gmail; the printed `delivery` map shows `drive`/`gmail` `SUCCESS`. (This is the real graph + real Ollama — expect it to be slow, and note `qwen3:14b` may OOM on constrained boxes; it is out of the automated suite by design.)
- [ ] **HTTP smoke.** Start the server (`python -m app.api`, binds `127.0.0.1:8000`), `POST /api/analyze` a contract (`curl -F file=@contract.pdf http://127.0.0.1:8000/api/analyze`), poll `GET /api/jobs/{id}`, open `GET /api/jobs/{id}/events` (SSE), and download `GET /api/jobs/{id}/report?format=md`. Confirm the localhost bind (a request to the machine's LAN IP is refused — D1).

**Why**: The automated suite exercises the mechanics against mocks; this is the only step that runs the real pipeline end-to-end and eyeballs the artifacts.

---

## Summary of all files created/modified

| # | File | Action |
|---|------|--------|
| 1 | `pyproject.toml` | MODIFIED (add `python-multipart>=0.0.9`) |
| 2 | `specs/002-tech-stack.md` | MODIFIED (record `python-multipart` in §3e/§4) |
| 3 | `.gitignore` (repo root) | MODIFIED (add `backend/data/uploads/`) |
| 4 | `app/config.py` | MODIFIED (add Runner/API constants block) |
| 5 | `app/runner/__init__.py` | NEW (package marker; re-exports `run_pipeline`, `RunResult`, `NodeProgress`) |
| 6 | `app/runner/models.py` | NEW (Pydantic: `JobState`, `ErrorInfo`, `AnalyzeAccepted`, `JobStatus`, `ProgressEvent`) |
| 7 | `app/runner/progress.py` | NEW (`NODE_INDEX`, `TOTAL_STAGES`, `node_index`) |
| 8 | `app/runner/core.py` | NEW (`run_pipeline`, `RunResult`, `NodeProgress`) |
| 9 | `app/runner/events.py` | NEW (`JobEventBuffer`) |
| 10 | `app/runner/registry.py` | NEW (`JobRecord` + per-record lock, `JobRegistry`) |
| 11 | `app/runner/worker.py` | NEW (`PipelineWorker`) |
| 12 | `app/runner/__main__.py` | NEW (CLI) |
| 13 | `app/api/__init__.py` | NEW (package marker) |
| 14 | `app/api/main.py` | NEW (`create_app`, `lifespan`, `app`, `run`) |
| 15 | `app/api/routes.py` | NEW (`RunnerContext`, the 5 endpoints) |
| 16 | `app/api/__main__.py` | NEW (`python -m app.api`) |
| 17 | `tests/unit/test_config.py` | MODIFIED (+4 tests) |
| 18 | `tests/unit/test_runner_models.py` | NEW (4 tests) |
| 19 | `tests/unit/test_progress_map.py` | NEW (4 tests) |
| 20 | `tests/unit/test_runner_core.py` | NEW (10 tests) |
| 21 | `tests/unit/test_event_buffer.py` | NEW (6 tests) |
| 22 | `tests/unit/test_registry.py` | NEW (7 tests) |
| 23 | `tests/unit/test_worker.py` | NEW (6 tests) |
| 24 | `tests/unit/test_cli.py` | NEW (5 tests) |
| 25 | `tests/integration/conftest.py` | MODIFIED (add `client` fixture + fakes + `_wait_for`) |
| 26 | `tests/integration/test_api_analyze.py` | NEW (8 tests) |
| 27 | `tests/integration/test_api_jobs.py` | NEW (8 tests) |
| 28 | `tests/integration/test_api_sse.py` | NEW (6 tests) |
| 29 | `tests/integration/test_api_report.py` | NEW (6 tests) |
| 30 | `tests/integration/test_api_cors.py` | NEW (2 tests) |
| 31 | `tests/integration/test_runner_graph_untouched.py` | NEW (2 tests) |

> **`app/graph/builder.py` is NOT in this list — by design.** The graph is untouched; no existing test file is modified.

---

## Acceptance-criteria traceability (spec §3 → tasks)

| Spec §3 criterion | Covered by |
|-------------------|-----------|
| **Submission & lifecycle** | |
| AC-1 pdf → 202, not sync-completed | Task 18 (`test_analyze_pdf_returns_202`) |
| AC-2 docx accepted | Task 18 (`test_analyze_docx_accepted`) |
| AC-3 upload saved; seeds only document_path (+started_at) | Task 8/9 (`test_seeds_only_document_path_and_started_at`), Task 18 (`test_upload_saved_and_path_passed`) |
| AC-4 completed status + report_available + finished_at | Task 18 (`test_job_lifecycle_to_completed`) |
| AC-5 recipient forwarded to delivery | Task 8/9 (`test_delivery_called_with_recipient`), Task 18 (`test_recipient_forwarded`) |
| **Graph invocation isolation** | |
| AC-6 build_graph once; no node-owned key seeded | Task 8/9 (`test_build_graph_called_once`, `test_seeds_only_document_path_and_started_at`) |
| AC-7 imports only build_graph/deliver; builder unchanged | Task 8/9 (`test_only_public_entrypoints_imported`), Task 18 (`test_builder_not_modified_by_runner`) |
| AC-8 fully-mocked graph → correct completed status | Task 18 (whole suite runs on the fake graph) |
| **Progress streaming (SSE)** | |
| AC-9 event/node in order + one terminal + close | Task 18 (`test_progress_then_terminal_then_close`, `test_event_stream_content_type`) |
| AC-10 terminal `final` == GET status | Task 18 (`test_terminal_final_equals_status`) |
| AC-11 finished job → immediate terminal, no hang | Task 10/11 (`test_finished_job_replays_terminal_and_closes`), Task 18 (`test_finished_job_stream_immediate_terminal`) |
| **Report retrieval** | |
| AC-12 md/json download, correct media type | Task 18 (`test_download_markdown`, `test_download_json`) |
| AC-13 path only from record (no traversal) | Task 18 (`test_report_path_only_from_record`) |
| AC-14 not-completed → 409 | Task 18 (`test_report_before_ready_409`) |
| **Validation & not-found** | |
| AC-15 unsupported ext → 400, no job | Task 2/3 (`test_upload_extensions_match_ingest`), Task 18 (`test_unsupported_extension_400_no_job`) |
| AC-16 oversized → 413 | Task 18 (`test_oversized_413`) |
| AC-17 unknown id (jobs/events/report) → 404 | Task 18 (`test_unknown_job_404`, `test_unknown_job_events_404`, `test_report_unknown_job_404`) |
| AC-18 health → 200 | Task 18 (`test_health_ok`) |
| **Registry & concurrency** | |
| AC-19 two ids tracked independently | Task 18 (`test_two_jobs_independent`) |
| AC-20 run off the event loop; single shared worker | Task 14 (`test_single_shared_worker_serializes`), Task 18 (`test_response_not_blocked_by_run`) |
| AC-21 single registry seam | Task 12 (`test_registry_is_single_seam`) |
| AC-22 eviction → 404 | Task 12 (`test_eviction_keeps_last_n`), Task 18 (`test_eviction_returns_404`) |
| AC-23 CORS preflight allowed/denied | Task 18 (`test_preflight_allowed_origin_gets_header`, `test_disallowed_origin_no_header`) |
| **Edge cases** | |
| EC-1 ingest-error → completed-with-error | Task 8/9 (`test_ingest_error_surfaced_not_raised`), Task 14 (`test_ingest_error_marks_completed_with_error`), Task 18 (`test_ingest_error_completes_with_error`) |
| EC-2 crash → failed, isolated | Task 8/9 (`test_graph_exception_propagates`), Task 14 (`test_exception_marks_failed_isolated`), Task 18 (`test_graph_exception_marks_failed`) |
| EC-3/4 delivery fails/disabled but job completed | Task 18 (`test_delivery_status_surfaced` — asserts both branches) |
| EC-5 empty upload → 400 | Task 18 (`test_empty_upload_400`) |
| EC-6 client disconnect mid-SSE | Task 10/11 (`test_unsubscribe_removes_queue`) |
| EC-7 late/no-lost-wakeup subscribe | Task 10/11 (`test_late_subscriber_replays_backlog`, `test_no_lost_wakeup`), Task 18 (`test_late_subscriber_gets_full_sequence`) |
| EC-8 report_path set but file missing → 404 | Task 12 (`test_to_status_report_available_reflects_disk`), Task 18 (`test_missing_file_on_disk_404`) |
| EC-9 restart loses jobs → 404 | Task 12 (`test_eviction_keeps_last_n` — same 404 semantics) |
| **Design invariants (review + plan)** | |
| R1 — record-level thread safety (no torn read) | Task 12 (`test_concurrent_progress_and_to_status_no_race`) |
| M1 — single source of truth for completed_nodes | Task 8/9 (`RunResult` has no `completed_nodes`; callback path only) |
| M2 — clean ingest-error message | Task 14 (`test_ingest_error_marks_completed_with_error`) |
| D2 — one core, two entry points | Task 14 (`test_worker_uses_run_pipeline`), Task 16 (`test_cli_uses_run_pipeline`) |
| D6 — no runner-level LLM/timeout constant | Task 2/3 (`test_runner_no_llm_constant`) |
