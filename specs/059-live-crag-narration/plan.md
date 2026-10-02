# Feature 059 — Technical plan: live per-clause CRAG retrieval progress (polled)

Branch: `feature/059-live-crag-narration` (per constitution §11).

Derived from the approved `spec.md`. **Backend + frontend.** CRAG emits a per-clause progress payload via
LangGraph's `get_stream_writer()` (custom stream) while it loops; `run_pipeline` forwards custom chunks to
a callback; the worker applies them to a lock-guarded `JobRecord` clause-progress; the existing polled
`GET /jobs/{id}` (`to_status()`) carries it to the UI, which renders a live counter + recent-clause feed.
**No new node/edge, no `ContractState`/`specs/001` change, no Alembic migration, no `routes.py`/SSE/buffer
change.** Reversible via `CRAG_LIVE_CLAUSE_PROGRESS_ENABLED` (default `False`).

## 0. Scope of change (files touched)
Per **AC-10/AC-15** the `git diff --name-only main` must show only:

Backend:
```
backend/app/config.py
backend/app/graph/nodes/crag_retrieval_agent.py
backend/app/runner/core.py
backend/app/runner/registry.py
backend/app/runner/models.py
backend/app/runner/worker.py
backend/tests/...            (new/updated unit tests — see §8)
```
Frontend:
```
frontend/src/lib/api/types.ts
frontend/src/lib/useJobStatus.ts
frontend/src/components/processing/ProcessingView.tsx
frontend/src/lib/api/fixtures.ts
frontend/src/lib/api/mockProvider.ts
frontend/src/__tests__/_fakeClient.ts        (add a clause-progress running-status helper)
frontend/src/__tests__/...                    (new/updated tests — see §8)
```
Plus `specs/059-live-crag-narration/{spec,plan,tasks}.md`. **Not touched:** `routes.py`, the SSE
`events.py`/`/events` path, `ContractState`/graph, any Alembic migration, `JobRow`/persistence row schema.

## 1. `config.py` — two §3 constants
- `CRAG_LIVE_CLAUSE_PROGRESS_ENABLED: bool = _env_bool("CRAG_LIVE_CLAUSE_PROGRESS_ENABLED", False)` (D4).
- `CRAG_PROGRESS_RECENT_MAX: int = _env_int("CRAG_PROGRESS_RECENT_MAX", 8)` (D5 — ring-buffer cap).

## 2. `crag_retrieval_agent.py` — guarded per-clause emit (AC-1/AC-2/AC-3/AC-7/AC-8)
- Re-expose the flag module-level (monkeypatch pattern): `CRAG_LIVE_CLAUSE_PROGRESS_ENABLED = _config.CRAG_LIVE_CLAUSE_PROGRESS_ENABLED`.
- Helper to acquire the writer **defensively** (guards the *acquisition*, per spec D3/AC-2):
  ```python
  def _clause_writer():
      if not CRAG_LIVE_CLAUSE_PROGRESS_ENABLED:
          return None
      try:
          from langgraph.config import get_stream_writer
          return get_stream_writer()          # RuntimeError if no runnable context (direct call/CLI)
      except Exception:                        # RuntimeError (no context) → no writer; never break the node
          return None
  ```
  Acquire once before the loop: `writer = _clause_writer()`.
- Change the loop header from the current `for clause_id, record in ordered:` to
  `for idx, (clause_id, record) in enumerate(ordered, start=1):`, and compute `total = len(ordered)` before
  the loop — so both emit sites (the empty-text guard and the main path) have `idx`/`total`.
- **Empty-text guard path** (the early `continue`): before `continue`, emit with `retrieval_path=None`,
  `confidence=None` (AC-8), using `idx`/`total`.
- **Main path**: after staging `clause_updates[clause_id]` (so `path`/`confidence` are known), emit the
  payload. `clause_type` is read from the clause **record** (there is NO `converted_type`/`_enum_value` in
  this module) and normalized enum-or-str → value with `getattr`, passing `None` through unchanged
  (`specs/001`/`state.py` type the clause record's `clause_type` as `Optional[ClauseType]`, and a
  checkpoint round-trip can yield a plain str):
  ```python
  if writer is not None:
      ct = record.get("clause_type")                       # ClauseType | str | None
      writer({
          "kind": "clause",
          "clause_index": idx,
          "clause_total": total,
          "clause_type": getattr(ct, "value", ct),         # enum→value, str→str, None→None
          "retrieval_path": (path.value if path is not None else None),  # RetrievalPath.value | None
          "confidence": confidence,                                      # float | None
      })
  ```
  The emitted `retrieval_path` is the same `path` written to `path_taken` → AC-7 parity. (`getattr(None,
  "value", None)` is `None`; `getattr("payment", "value", "payment")` is `"payment"`; `getattr(
  ClauseType.PAYMENT, "value", …)` is `"payment"`.)
- Flag off or no writer ⇒ zero emits ⇒ byte-identical (AC-3). Direct unit-test call ⇒ `get_stream_writer()`
  raises → `_clause_writer()` returns `None` → no emit, no error (AC-2).

## 3. `core.run_pipeline` — dual-mode stream, forward custom chunks (AC-1/AC-4)
- Add param `on_clause: Optional[Callable[[dict], None]] = None`.
- `live = on_clause is not None` (core does NOT read the flag — the worker gates passing `on_clause`; keeps
  core decoupled and the off-path a single-mode stream).
- Stream mode: `stream_mode = ["values", "custom"] if live else "values"`.
- Iterate:
  ```python
  for item in graph.stream(stream_input, stream_mode=stream_mode, config=config):
      if live:
          mode, chunk = item
          if mode == "custom":
              on_clause(chunk)      # separate branch — never touches seen/last_node (AC-4)
              continue
          state = chunk             # mode == "values"
      else:
          state = item              # single-mode: plain state (byte-identical, AC-3)
      final_state = state
      # ... existing current_node / seen / on_progress node-progress logic unchanged ...
  ```
- Custom chunks bypass the `seen`/`last_node` dedup entirely (AC-4). `values` path and delivery/return are
  unchanged.

## 4. `registry.py` — JobRecord clause-progress (AC-5/AC-9) + no-persist (suggestion)
- Add `field(init=False)` state to `JobRecord`: `_clauses_done: int = 0`, `_clauses_total: int = 0`,
  `_web_fallbacks: int = 0`, `_recent_clauses: list = field(default_factory=list, init=False)`, and a flag
  `_has_clause_progress: bool = False` (so `to_status()` emits `clause_progress=None` until the first update
  — EC-6/EC-7).
- One **locked** mutator that does append + increment **in the same lock acquisition** (suggestion #1):
  ```python
  def update_clause_progress(self, payload: dict) -> None:
      with self._lock:
          self._has_clause_progress = True
          self._clauses_done += 1
          self._clauses_total = payload.get("clause_total") or self._clauses_total
          if payload.get("retrieval_path") == "web_fallback":
              self._web_fallbacks += 1
          self._recent_clauses.append({...payload line fields...})
          if len(self._recent_clauses) > _config.CRAG_PROGRESS_RECENT_MAX:
              self._recent_clauses = self._recent_clauses[-_config.CRAG_PROGRESS_RECENT_MAX:]  # AC-9
  ```
- `to_status()` (already lock-held): when `_has_clause_progress`, set
  `clause_progress=ClauseProgress(clauses_done=…, clauses_total=…, web_fallbacks=…, recent=[ClauseProgressLine(**l) …])`; else `None`.
- **Not persisted (suggestion #2):** do NOT add these to `_to_row`/`JobRow`/the store. A rehydrated record
  after restart shows `clause_progress=None` (consistent with D6 in-memory-only; progress is transient).

## 5. `models.py` — additive boundary models (AC-6)
```python
class ClauseProgressLine(BaseModel):
    clause_index: int
    clause_total: int
    clause_type: Optional[str] = None
    retrieval_path: Optional[str] = None
    confidence: Optional[float] = None

class ClauseProgress(BaseModel):
    clauses_done: int = 0
    clauses_total: int = 0
    web_fallbacks: int = 0
    recent: List[ClauseProgressLine] = Field(default_factory=list)

# on JobStatus:
clause_progress: Optional[ClauseProgress] = None
```
All-defaulted ⇒ a pre-059 `JobStatus` deserializes unchanged (AC-6).

## 6. `worker.py` — gate + apply (AC-5)
- `import app.config as _config` (read the flag live for monkeypatch-ability).
- In `_run_one`, define `def _on_clause(payload: dict) -> None: rec.update_clause_progress(payload)`.
- Pass it only when the flag is on:
  `on_clause = _on_clause if _config.CRAG_LIVE_CLAUSE_PROGRESS_ENABLED else None`, then
  `run_pipeline(..., on_clause=on_clause)`. Flag off ⇒ `on_clause=None` ⇒ core single-mode (AC-3).

## 7. Frontend
### 7.1 `types.ts` (AC-11)
Mirror field-for-field: `ClauseProgressLine`, `ClauseProgress`, and `clause_progress?: ClauseProgress | null`
on `JobStatus`.
### 7.2 `useJobStatus.ts` (AC-12/AC-14)
In `mapStatus`, carry `clauseProgress: js.clause_progress ?? null` into `JobEventsState` (add the field to
the interface). Node-progress mapping unchanged (AC-14).
### 7.3 `ProcessingView.tsx` (AC-12/AC-13/AC-14)
In the running branch, when `state.clauseProgress` is present render, under the stage chips, a feed block:
- Counter: `{clauses_done}/{clauses_total} clauses · {web_fallbacks} web-fallbacks`.
- The `recent` lines (newest last), each: `Clause {i}/{N} · {clause_type?} — {label} ({conf}%)` where
  `label = evidenceSourceLabel(retrieval_path)` **reused from `@/components/report/EvidenceSourceBadge`**
  (058) so wording is DRY; clause_type and `({conf}%)` shown only when present. Tone (theme tokens, no hex —
  AC-13), mirroring 058's StatusBadge tones: a `web_fallback` line is emphasized with the warning token
  (e.g. `text-risk-medium`), a `local_kb` line uses a calmer token (e.g. `text-risk-low` / `text-text-secondary`).
  Node stage indicator is untouched (AC-14).
### 7.4 `fixtures.ts` + `mockProvider.ts` (offline exercisable; suggestion #3 — pinned shapes)
- `fixtures.ts`: add `clauseProgressFixture: ClauseProgress` (e.g. `clauses_done:7, clauses_total:12,
  web_fallbacks:2, recent:[{clause_index:6,clause_total:12,clause_type:"liability",retrieval_path:"local_kb",confidence:0.82},{clause_index:7,clause_total:12,clause_type:"indemnification",retrieval_path:"web_fallback",confidence:0.61}]}`.
- `mockProvider.ts` `getJob`: make it script a short per-`jobId` sequence via a module-level call counter —
  first call `queued`, next two `running` (`current_node:"crag_retrieval"`) carrying a growing
  `clause_progress`, then `completed` (sticky, `completedStatusFixture`). Keeps the dev mock showing the
  live feed. Run the full FE suite; if any existing test asserted the mock's immediate-completed `getJob`,
  pin it to the new sequence (never weaken, §7).

## 8. Tests (TDD — write first, confirm failing, then implement)
### Backend (pytest)
- **CRAG** (`test_crag_retrieval_agent.py` or a new `test_crag_clause_progress.py`): AC-1 (run graph with
  `stream_mode=["values","custom"]`, branch on `mode`, assert N custom payloads with correct fields/parity),
  AC-2 (direct `crag_retrieval_agent(state)` call with flag on → no error, no emit; existing CRAG tests
  unchanged), AC-3 (flag off → no custom payloads), AC-7 (streamed `retrieval_path` == final `path_taken`),
  AC-8 (empty-text clause → `retrieval_path=None`, counted, no skip).
- **core** (`test_runner_core*.py`): AC-4 (with `on_clause`, custom chunks forwarded; `values` node-progress
  + 012 dedup unchanged; a custom chunk never adds to `seen`); AC-3 (no `on_clause` → single `"values"`
  stream, byte-identical).
- **registry** (`test_*registry*`/new): AC-5 (apply M payloads → `to_status().clause_progress` counters +
  recent correct), AC-9 (recent capped at `CRAG_PROGRESS_RECENT_MAX`; counters keep counting), no-persist
  (rehydrate from store → `clause_progress=None`).
- **worker** (`test_*worker*`): AC-5 (flag on → `_on_clause` wired, record updated; reachable via
  `rec.to_status()`); AC-3 (flag off → `on_clause=None`).
- **models** (`test_*models*`): AC-6 (JobStatus back-compat; pre-059 dict deserializes with
  `clause_progress=None`).
### Frontend (vitest)
- New `__tests__/clauseProgress.test.tsx` (or extend a processing test): AC-12 (mock `getApiClient().getJob`
  via `makeFakeClient({ statuses: [runningStatusWithClauseProgress(...)] })` — add a
  `runningStatusWithClauseProgress()` helper to `_fakeClient.ts` building on `runningStatus("crag_retrieval")`
  + `clause_progress` — render `ProcessingView`, assert the counter text and per-line text incl. "Local
  knowledge base"/"Live web search"), AC-13 (web-fallback line has a distinct tone class; no hex), AC-14
  (stage chips still advance from `current_node`; completed/failed unchanged).
- Types drift: `tsc` + any existing report/status drift test stays green (AC-11).

## 9. Correctness / AC mapping
- **No graph/state/migration/route change (AC-10/§2 spec):** only the §0 files; CRAG return dict unchanged
  (§5), progress on `JobRecord` not `ContractState` (§6), `JobStatus` additive (§4).
- **Reversibility (AC-3/EC-6):** flag off ⇒ node silent, worker passes no `on_clause`, core single-mode.
- **Guarded acquisition (AC-2):** `_clause_writer()` swallows the out-of-context `RuntimeError` → direct
  calls/CLI/tests byte-identical.
- **Thread-safety (AC-5):** single locked `update_clause_progress` (append + counters together).
- **Bounded payload (AC-9/EC-1):** `recent` capped; counters cumulative.
- **One source of truth (AC-7):** streamed `retrieval_path` == `path_taken`; wording reused from 058's
  `evidenceSourceLabel`.

## 10. Verification gate (all offline)
- Backend: `.venv/Scripts/python.exe -X utf8 -m pytest -q` — full suite green (new + existing CRAG/core/
  worker/registry/models).
- Frontend: `npm test` (vitest, incl. the new clause-progress test + existing processing/report tests),
  `npx tsc --noEmit`, eslint (no new errors), `npm run build`.
- `git diff --name-only main` matches the §0 allow-list (no routes/SSE/ContractState/migration change).
- **Live smoke is deferred (D4):** the flag ships `False`; flip on + live-run to confirm the feed, then
  flip default if desired (project pattern).

## 11. Risks / limitations
- **Poll granularity (EC-2):** feed shows recent ≤K at 2.5s cadence; counters accurate — accepted trade-off.
- **Mock `getJob` scripting** could surprise a test that assumed immediate completion — caught by the full
  FE suite; pin (never weaken) any such test.
- **Cross-module import** (processing → `EvidenceSourceBadge.evidenceSourceLabel`) is a pure-helper reuse;
  acceptable (keeps 058/059 wording DRY). If undesired, duplicate the two strings instead.
- Observability only — no change to CRAG routing, analysis output, or the report (§2/§5 spec).

## 12. Merge
Full backend + frontend gate green; `git diff --name-only main` matches §0. Rebase `main`, merge
`feature/059-live-crag-narration`, delete branch (`git-finish`). Flag ships OFF; live smoke + flip is a
follow-up.
