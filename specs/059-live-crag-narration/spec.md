# Feature 059 — Spec: Live per-clause CRAG retrieval progress (polled)

Status: DRAFT (pre spec-reviewer gate) — REVISED delivery mechanism (polling, not SSE) after a
plan-stage grounding finding (see §1).
Branch: `feature/059-live-crag-narration` (constitution §11).

> Second half of "Suggestion 2 — retrieval transparency". **058** (merged + pushed) surfaces each
> finding's `path_taken` as a persisted badge in the report; **059** surfaces CRAG's per-clause decisions
> *while processing*. The clause-traceability chain (Suggestion 1) is the separate reserved 055→056→057.

## 1. Problem statement

Node 3 (CRAG retrieval, constitution §2) decides **per clause** whether to trust the curated local FAISS
KB (confidence `>= CRAG_CONFIDENCE_THRESHOLD`, 0.73) or fall back to a **live web search**. Today that
decision is invisible while it happens: the processing screen (`ProcessingView` ← `useJobStatus`) shows
only coarse **node-level** progress ("Evidence…" stage 3 of 7). CRAG can be the slowest node — an
embedding call plus possibly a web search *per clause* (constitution §9) — so on a multi-clause contract
the user watches one static "Evidence" step with no insight into which clauses are judged against the
trustworthy KB versus an open-web search.

This feature surfaces CRAG's per-clause decision **live during processing** — a running counter and a feed
of recent clauses with their source (e.g. *"Clause 7/12 · indemnification — Live web search (61%)"*). It
is the live counterpart to feature 058's persisted badge.

### Delivery mechanism — grounding finding (why polling, not SSE)
The processing screen is driven by `useJobStatus`, which **polls `GET /api/jobs/{job_id}` every 2.5s**
(`POLL_INTERVAL_MS`) and renders from the returned `JobStatus` (`current_node`/`completed_nodes`/
`status`). It does **not** subscribe to the SSE stream — the `openJobEvents`/`/events` SSE path exists in
the provider layer but **no screen consumes it** (015 chose polling because "SSE buffers through the Next
dev proxy"). Therefore this feature delivers the per-clause progress **through the polled `JobStatus`**, not
through SSE events. The backend still collects per-clause progress *live* during the CRAG node (so a poll
mid-CRAG reflects current progress); the UI reads it on its next 2.5s poll.

**Accepted trade-off (owner decision 2026-10-02):** polling is 2.5s-granular, so the *cumulative counters*
are always accurate but the line-by-line feed shows the **most recent K clauses** at each poll and may skip
individual lines between polls. This was chosen over SSE for reliability (identical behavior in local
`npm run dev` and on the deploy).

### Position relative to the constitution
**No new node or edge (§2 intact).** CRAG stays a single node; it only emits per-clause *observability*
payloads through LangGraph's official `get_stream_writer()` custom-stream channel while it already loops
over clauses. This:
- does **not** change CRAG's return value (still only `clauses`/`current_node`/`node_timings`) — §5 intact;
- stores **nothing** new in `ContractState` (the per-clause progress lives on the runner's `JobRecord`, a
  boundary/runtime object, never in graph state / never checkpointed) — §6 intact; the data it carries
  (`path_taken`, `confidence_score`) already exists on the clause record per `specs/001`;
- is exactly the progress-reporting §9 (local-model latency) calls for;
- requires **no `specs/001` amendment** (no new `ContractState` field), **no Alembic migration** (job
  progress is in-memory on `JobRecord`, not persisted), and **no new/changed API endpoint** (the existing
  `GET /jobs/{job_id}` already returns `rec.to_status()`; `JobStatus` gains optional fields only).

Fully reversible via a config flag (§3, default off) ⇒ byte-identical to today.

## 2. Inputs and outputs

### Backend flow (existing paths, extended)
1. **CRAG node** (`crag_retrieval_agent.py`): inside its existing per-clause loop (`enumerate(ordered,
   start=1)`), after computing `confidence`+`path` for a clause (values it already logs and writes to the
   clause record), it emits one **custom-stream payload per clause** via
   `langgraph.config.get_stream_writer()`. The payload: `{"kind": "clause", "clause_index": i,
   "clause_total": N, "clause_type": <ClauseType.value|None>, "retrieval_path": <RetrievalPath.value|None>,
   "confidence": <float|None>}`. The empty-text/unscorable guard path also emits (with
   `retrieval_path`/`confidence` = `None`) before `continue`, so no index is skipped.
   - **Writer acquisition is guarded** (see D3): a direct node call with no runnable context (unit
     test / CLI) makes `get_stream_writer()` raise `RuntimeError` at acquisition, so the node wraps the
     `get_stream_writer()` call itself in `try/except RuntimeError` and skips emitting when unavailable.
2. **Runner** (`core.run_pipeline`): when an `on_clause` callback is provided it streams
   `graph.stream(stream_mode=["values","custom"])` (each yield is a `(mode, chunk)` tuple): `values`
   chunks drive the existing node-level progress unchanged; `custom` chunks are passed to `on_clause`.
   When `on_clause is None` it streams the current `stream_mode="values"` (plain-state yields) —
   byte-identical to today.
3. **Worker** (`worker.py`): when the flag is on, `_run_one` passes `on_clause=_on_clause`;
   `_on_clause(payload)` updates the job's `JobRecord` clause-progress **under the record's lock**
   (thread-safe, like `record_progress`). When the flag is off it passes no `on_clause`.
4. **Registry** (`registry.py`): `JobRecord` gains in-memory clause-progress state —
   `clauses_done`, `clauses_total`, `web_fallbacks`, and a bounded `recent` ring buffer
   (cap `CRAG_PROGRESS_RECENT_MAX`) of the last K clause payloads — mutated only via a locked
   `update_clause_progress(payload)` method, and surfaced by `to_status()`.
5. **Status endpoint**: **unchanged** — `GET /jobs/{job_id}` already returns `rec.to_status()`; the new
   fields ride along. **No SSE/`/events`/buffer change; no `routes.py` change.**

### `JobStatus` (Pydantic boundary model, `runner/models.py`) — additive fields
All **optional, default empty/None** (so legacy consumers and pre-059 serialization are unchanged — §4):
- `clause_progress: Optional[ClauseProgress]` — a small sub-model, `None` until CRAG starts emitting:
  - `clauses_done: int`, `clauses_total: int`, `web_fallbacks: int`
  - `recent: List[ClauseProgressLine]` — the last ≤K clauses, each
    `{clause_index, clause_total, clause_type, retrieval_path, confidence}` (all optional except indices).

### Frontend
- `frontend/src/lib/api/types.ts` — mirror the new optional `JobStatus.clause_progress` shape
  field-for-field.
- `useJobStatus` (`mapStatus`) — carry `clause_progress` from the polled `JobStatus` into
  `JobEventsState` (additive; node-progress mapping unchanged).
- `ProcessingView` — during the CRAG stage, render a **rolling window of the most recent ~K clause lines**
  plus a **running counter** `{clauses_done}/{clauses_total} clauses · {web_fallbacks} web-fallbacks`.
  Each line uses the format: `Clause {i}/{N} · {clause_type?} — {Local knowledge base | Live web search}
  ({conf}%)` (clause type and confidence shown only when present; source wording reused from 058).
  Web-fallback lines are visually emphasized (lower-trust path). Node-level stage progress is unchanged.
- The mock provider's scripted `getJob` sequence (`fixtures.ts`/`mockProvider.ts`) returns increasing
  `clause_progress` across successive polls during the CRAG stage, so the feed is exercisable offline.

### Resolved decisions (inline)
- **D1 — Deliver via the polled `JobStatus`, not SSE.** The UI polls `GET /jobs/{id}`; put clause-progress
  there. No `routes.py`/SSE/buffer change; reliable in dev and on deploy (owner decision; §1 trade-off).
- **D2 — Emit one payload per clause (every decision), not only web-fallbacks.** Full transparency (KB and
  fallback) matches 058; the counter tracks `web_fallbacks` separately for emphasis.
- **D3 — CRAG emits via `get_stream_writer()` (custom stream); guard the acquisition.** Verified available
  (`from langgraph.config import get_stream_writer`; `stream_mode="custom"` supported). **Two out-of-scope
  contexts differ** (verified in `langgraph/config.py`+`runtime.py`): (a) *inside* a graph run not
  streaming `custom` → `get_stream_writer()` returns the built-in `_no_op_stream_writer` (genuine no-op);
  (b) a **direct node call with no runnable context** (unit test / CLI) → `get_stream_writer()` calls
  `get_config()` which **raises `RuntimeError("Called get_config outside of a runnable context")`** at
  *acquisition*, before any emit. CRAG MUST therefore wrap the **`get_stream_writer()` acquisition itself**
  (not merely the emit) in `try/except RuntimeError`, skipping emission when unavailable.
- **D4 — Reversible flag `CRAG_LIVE_CLAUSE_PROGRESS_ENABLED` (§3), default `False`.** Off ⇒ CRAG emits no
  payloads, the worker passes no `on_clause`, and `run_pipeline` streams `"values"` only ⇒ byte-identical
  to today. Shipped OFF per the project pattern (042/044/045/047); flip on after a live smoke. Tests
  exercise the on-behavior by explicitly enabling the flag.
- **D5 — `CRAG_PROGRESS_RECENT_MAX` (§3, default 8)** bounds the `recent` ring buffer so a 185-clause doc
  does not bloat the polled status payload.
- **D6 — No `ContractState`/graph change, no migration, no `routes.py`/SSE change.** Per §1. The only
  boundary change is additive optional fields on `JobStatus` + in-memory `JobRecord` state.

## 3. Acceptance criteria

### Backend (pytest, offline — CRAG LLM/embeddings mocked as in existing tests)
- **AC-1 (node emits per-clause payloads):** with the flag on, running the graph with
  `stream_mode=["values","custom"]` over N clauses yields **N** custom payloads. Note the list stream mode
  makes each `graph.stream(...)` yield a `(mode, chunk)` tuple, so the test branches on `mode`. Each
  custom payload carries `kind="clause"`, `clause_index` 1..N, `clause_total=N`, `retrieval_path`, and
  `confidence` consistent with that clause's computed `path_taken`/`confidence_score`.
- **AC-2 (guarded acquisition, direct call):** calling `crag_retrieval_agent(state)` **directly** (no
  runnable context) with the flag on returns exactly today's partial dict and raises no error — because
  `get_stream_writer()` raises `RuntimeError` at acquisition in that context (not a no-op — D3), the node
  guards the `get_stream_writer()` call itself. A test asserts the direct call succeeds and **all existing
  CRAG unit tests pass unchanged**.
- **AC-3 (flag off ⇒ byte-identical):** with `CRAG_LIVE_CLAUSE_PROGRESS_ENABLED=False`, CRAG emits nothing,
  the worker passes no `on_clause`, `run_pipeline` streams `"values"` only (plain-state yields, no tuple
  unpacking), and behavior is byte-identical to pre-059.
- **AC-4 (runner forwards custom chunks, values unchanged):** `run_pipeline` with `on_clause` set invokes
  it for each `custom` chunk; the `values`-driven node-level `on_progress` behavior (incl. 012
  resume/dedup) is unchanged. **Custom chunks bypass the node-dedup logic entirely** — the `seen`/
  `last_node` dedup keys only on `current_node` from `values` chunks — so the custom callback is wired on a
  separate branch; a test asserts a custom chunk never touches the `seen` set.
- **AC-5 (worker updates JobRecord; polled status reflects it):** a forwarded clause payload updates the
  `JobRecord` clause-progress under its lock; after processing M clause payloads, `rec.to_status()` (hence
  `GET /jobs/{id}`) reports `clauses_done=M`, the correct `web_fallbacks` count, and a `recent` list of the
  last ≤`CRAG_PROGRESS_RECENT_MAX` clauses with their `retrieval_path`/`confidence`.
- **AC-6 (JobStatus back-compat):** a `JobStatus` with no clause progress serializes with
  `clause_progress=None`; deserializing a pre-059 `JobStatus` (field absent) still works (field optional).
- **AC-7 (path parity with the finding):** for a given clause the progress `retrieval_path` equals the
  `path_taken` that clause ends up with in the report (one decision, one source of truth).
- **AC-8 (empty/unscorable clause):** a clause CRAG cannot score (`path_taken=None`) produces a progress
  entry with `retrieval_path=None`/`confidence=None`, increments `clauses_done`, and is **not** counted as
  a web-fallback; no index is skipped, no crash.
- **AC-9 (recent ring buffer bounded):** with the flag on and a document of > `CRAG_PROGRESS_RECENT_MAX`
  clauses, `recent` never exceeds `CRAG_PROGRESS_RECENT_MAX` entries (oldest dropped) while the cumulative
  counters keep counting all clauses.
- **AC-10 (full backend suite green):** the whole `pytest` suite passes on Windows, including existing
  CRAG / runner / worker / registry / events tests (unchanged except where they assert the new behavior).

### Frontend (vitest + tsc + eslint + build, offline)
- **AC-11 (types mirror):** `JobStatus` in `types.ts` gains the optional `clause_progress` shape; mock
  fixtures and handlers compile against it (tsc).
- **AC-12 (live feed renders from polled status):** given a `JobStatus` whose `clause_progress` carries
  recent clause lines + counters, `ProcessingView` renders a per-clause line for each recent entry in the
  format `Clause {i}/{N} · {type?} — {source} ({conf}%)` (a `local_kb` entry reads "Local knowledge base",
  a `web_fallback` entry "Live web search") plus a running `{done}/{total} clauses · {m} web-fallbacks`
  counter.
- **AC-13 (fallback emphasis):** a `web_fallback` line is visually distinguished from a `local_kb` line
  (different tone/treatment from theme tokens — no raw hex in `src/components/**`).
- **AC-14 (node progress unaffected):** node-level stage progress (the 7 stage chips / step indicator)
  still advances exactly as today from `current_node`; clause progress does not change it, and the
  completed/failed phases are unchanged.
- **AC-15 (frontend suite green):** `npm test`, `tsc --noEmit`, eslint (no new errors), and `next build`
  all pass.

## 4. Edge cases
- **EC-1 — Large document (up to `MAX_CLAUSES_LIMIT`=500):** counters count all clauses; `recent` is capped
  at `CRAG_PROGRESS_RECENT_MAX` (AC-9). Polled-status payload stays small.
- **EC-2 — Poll granularity:** between two 2.5s polls CRAG may process several clauses; the counter is
  cumulative (accurate), and the feed shows the most recent ≤K — intermediate lines may not each be seen
  (the accepted §1 trade-off). No data integrity issue.
- **EC-3 — Circuit breaker opens mid-CRAG:** remaining clauses route to web with `confidence=None`; each
  still produces a progress entry (`retrieval_path="web_fallback"`, counted), so counters stay complete.
- **EC-4 — KB unavailable:** all clauses take `web_fallback`; `web_fallbacks == clauses_done`.
- **EC-5 — Resume after restart (feature 012):** a resumed run re-runs non-completed nodes from scratch
  (ephemeral checkpointer); if CRAG re-runs it re-emits clause payloads and the `JobRecord` counters
  reflect the re-run. Node-level dedup (`already_completed`) is unaffected (clause payloads are not
  node-progress and never touch the `seen` set — AC-4).
- **EC-6 — Flag off:** no clause payloads, no `on_clause`, `clause_progress` stays `None` everywhere;
  identical to today (AC-3).
- **EC-7 — Ingest error / zero clauses:** CRAG's existing guards return early with an empty clauses dict;
  zero clause payloads, `clause_progress` stays `None` (no crash).
- **EC-8 — Status read before CRAG starts / after it finishes:** polling before CRAG → `clause_progress`
  `None`; after CRAG → the final counters/recent remain on the record through completion (the feed is only
  *shown* while on the processing screen, which redirects to the report on completion).

## 5. Out of scope
- **The persisted report badge / evidence-source label** — feature **058** (shipped).
- **Any change to CRAG routing, the 0.73 threshold, or the `path_taken`/`confidence_score` computation** —
  `specs/005-crag-retrieval`; this feature only observes.
- **Switching the processing screen to SSE** — explicitly rejected (owner chose polling, §1); the SSE
  `openJobEvents`/`/events` path is left untouched and unused as today.
- **Live progress for other nodes** (Self-RAG, risk, redline) — a possible later reuse of the same
  mechanism; not built here.
- **Persisting the narration** (DB/report) — the progress is in-memory on `JobRecord` (§6); persisted
  provenance already lives in the 058 report.
- **A new API endpoint** — avoided (reuses `GET /jobs/{id}`).

## 6. Evaluation (metrics to log)
This feature surfaces CRAG retrieval behavior but performs **no scoring, retrieval, or validation itself**
— no new probabilistic measurement, no eval-harness change. CRAG already logs per-clause `path_taken`+
`confidence_score`; this feature reports the same values. For operability, the worker should log (debug)
the count of clause payloads applied per run so a mismatch between payloads-applied and clauses-processed
is detectable. The local-KB-vs-web-fallback hit rate is already observable from CRAG logs and the 058
badges; aggregating it is out of scope. No recall/precision/false-flag metric is affected.

## 7. Open questions
All resolved (owner, 2026-10-02) and folded into §2/§3:
- **Delivery mechanism → RESOLVED: polling via `JobStatus`** (not SSE), for reliability in dev + deploy (D1/§1).
- **Flag default → RESOLVED `False`** (D4), flip after live smoke.
- **UI density → RESOLVED: rolling window of recent K + running counter** (D5 / §2 frontend / AC-12).
- **Per-clause line copy → RESOLVED:** `Clause {i}/{N} · {clause_type?} — {Local knowledge base | Live web
  search} ({conf}%)` (AC-12).

No open questions remain.
