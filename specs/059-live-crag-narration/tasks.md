# Feature 059 — Live per-clause CRAG progress (polled) — Implementation Tasks

Reference documents:
- Spec: `specs/059-live-crag-narration/spec.md`
- Plan: `specs/059-live-crag-narration/plan.md`
- Constitution: `specs/000-constitution.md` (**§1/§11** branch workflow; **§7** TDD / never weaken a test;
  **§2** no new node/edge; **§3** named config constants; **§5** partial-update; **§6** state minimality)

Backend paths are relative to `backend/`; frontend paths relative to `frontend/`.

**Workflow reminders:**
- **No new node/edge, no `ContractState`/`specs/001` change, no Alembic migration, no `routes.py`/SSE/
  `events.py`/buffer change.** CRAG still returns only its three evidence keys. Per-clause progress lives on
  the runner's `JobRecord` (in-memory) and rides the existing polled `GET /jobs/{id}` via `to_status()`.
- **Reversible flag `CRAG_LIVE_CLAUSE_PROGRESS_ENABLED`, default `False`** — off ⇒ byte-identical to today.
- **Scope allow-list (AC-10/AC-15)** — `git diff --name-only main` shows ONLY:
  - Backend: `app/config.py`, `app/graph/nodes/crag_retrieval_agent.py`, `app/runner/core.py`,
    `app/runner/registry.py`, `app/runner/models.py`, `app/runner/worker.py`, + backend tests.
  - Frontend: `src/lib/api/types.ts`, `src/lib/useJobStatus.ts`,
    `src/components/processing/ProcessingView.tsx`, `src/lib/api/fixtures.ts`, `src/lib/api/mockProvider.ts`,
    `src/__tests__/_fakeClient.ts`, + frontend tests.
  - `specs/059-live-crag-narration/{spec,plan,tasks}.md`.
- **TDD (§7):** write each layer's tests first and confirm they FAIL, then implement to green. Never weaken
  a surprised pre-existing test — fix the code.
- **Exact payload shape** (CRAG → worker → JobRecord → JobStatus): `{kind:"clause", clause_index, clause_total,
  clause_type, retrieval_path, confidence}`. **Line copy** (frontend): `Clause {i}/{N} · {clause_type?} —
  {Local knowledge base | Live web search} ({conf}%)`. **Counter:** `{done}/{total} clauses · {m} web-fallbacks`.

---

## Task 0: Branch
- [ ] From up-to-date `main` (`git checkout main && git pull`), create `feature/059-live-crag-narration`
  (use `git-start`). Commit the APPROVED `spec.md`/`plan.md`/`tasks.md` on the branch.

**Verify:** `git branch --show-current` → `feature/059-live-crag-narration`.

---

## Task 1: Backend — write failing tests first  [AC-1..AC-9]
Create/extend these tests (they will fail until Tasks 2–7 land). Use the existing CRAG test mocking style
(embeddings/KB/web mocked). Enable the flag in-test via `monkeypatch.setattr(<module>, "CRAG_LIVE_CLAUSE_PROGRESS_ENABLED", True)`.

- [ ] **[NEW] `tests/unit/test_crag_clause_progress.py`** — AC-1 (build the graph / call the node inside a
  `graph.stream(stream_mode=["values","custom"])`; branch on the `(mode, chunk)` tuple; assert N `custom`
  payloads with `kind="clause"`, `clause_index` 1..N, `clause_total=N`, and `retrieval_path`/`confidence`
  matching each clause's computed `path_taken`/`confidence_score`); AC-7 (streamed `retrieval_path` ==
  final `path_taken`); AC-8 (an empty-text clause → payload with `retrieval_path=None`, `confidence=None`,
  index not skipped); AC-2 (call `crag_retrieval_agent(state)` **directly** with the flag on → returns
  today's partial dict, raises no error — the guarded `get_stream_writer()` acquisition swallows the
  `RuntimeError`); AC-3 (flag off → zero custom payloads).
- [ ] **[EXTEND] the runner-core test** (`tests/unit/test_runner_core*.py`) — AC-4 (pass `on_clause`; assert
  it is invoked once per custom chunk; node-level `on_progress` + the 012 `seen`/resume dedup unchanged; a
  custom chunk never adds to the `seen` set); AC-3 (no `on_clause` → single `"values"` stream, byte-identical).
- [ ] **[EXTEND] the registry test** — AC-5 (apply M payloads via `update_clause_progress`; assert
  `to_status().clause_progress` has `clauses_done=M`, correct `web_fallbacks`, and `recent` with the right
  lines); AC-9 (with > `CRAG_PROGRESS_RECENT_MAX` clauses, `recent` length == cap, oldest dropped, counters
  keep counting); no-persist (rehydrate a record from the store → `clause_progress is None`).
- [ ] **[EXTEND] the worker test** — AC-5 (flag on → `_on_clause` wired → record updated → visible via
  `rec.to_status()`); AC-3 (flag off → `on_clause` not passed).
- [ ] **[EXTEND] the models test** — AC-6 (a `JobStatus` built without clause progress has
  `clause_progress is None`; a pre-059 `JobStatus` dict — no `clause_progress` key — deserializes fine).
- [ ] Run `python -X utf8 -m pytest -q` and CONFIRM the new assertions FAIL (symbols/fields not yet present).

**Verify:** the new/extended tests fail for the expected reasons.

---

## Task 2: `config.py`  [AC-3, AC-9, D4/D5]
- [ ] Add `CRAG_LIVE_CLAUSE_PROGRESS_ENABLED: bool = _env_bool("CRAG_LIVE_CLAUSE_PROGRESS_ENABLED", False)`.
- [ ] Add `CRAG_PROGRESS_RECENT_MAX: int = _env_int("CRAG_PROGRESS_RECENT_MAX", 8)`.

---

## Task 3: `runner/models.py` — additive boundary models  [AC-6]
- [ ] Add `class ClauseProgressLine(BaseModel)` with `clause_index: int`, `clause_total: int`,
  `clause_type: Optional[str] = None`, `retrieval_path: Optional[str] = None`, `confidence: Optional[float] = None`.
- [ ] Add `class ClauseProgress(BaseModel)` with `clauses_done: int = 0`, `clauses_total: int = 0`,
  `web_fallbacks: int = 0`, `recent: List[ClauseProgressLine] = Field(default_factory=list)`.
- [ ] On `JobStatus`, add `clause_progress: Optional[ClauseProgress] = None` (all-defaulted → back-compat).

---

## Task 4: `runner/registry.py` — JobRecord clause-progress  [AC-5, AC-9]
- [ ] Add `field(init=False)` state to `JobRecord`: `_clauses_done: int = 0`, `_clauses_total: int = 0`,
  `_web_fallbacks: int = 0`, `_recent_clauses: list = field(default_factory=list)`,
  `_has_clause_progress: bool = False`.
- [ ] Add a **single lock-guarded** method `update_clause_progress(self, payload: dict) -> None` that, inside
  one `with self._lock:` block, sets `_has_clause_progress = True`, `_clauses_done += 1`, updates
  `_clauses_total` from `payload.get("clause_total")`, increments `_web_fallbacks` when
  `payload.get("retrieval_path") == "web_fallback"`, appends a line dict
  `{clause_index, clause_total, clause_type, retrieval_path, confidence}` to `_recent_clauses`, and trims it
  to the last `_config.CRAG_PROGRESS_RECENT_MAX` entries (AC-9).
- [ ] In `to_status()` (already lock-held), when `_has_clause_progress` set
  `clause_progress=ClauseProgress(clauses_done=…, clauses_total=…, web_fallbacks=…, recent=[ClauseProgressLine(**l) for l in _recent_clauses])`; else leave it `None`.
- [ ] **Do NOT** add these fields to `_to_row`/`JobRow`/persistence — progress is in-memory only (a
  rehydrated record shows `clause_progress=None`).

---

## Task 5: `graph/nodes/crag_retrieval_agent.py` — guarded per-clause emit  [AC-1, AC-2, AC-3, AC-7, AC-8]
- [ ] Re-expose the flag module-level: `CRAG_LIVE_CLAUSE_PROGRESS_ENABLED = _config.CRAG_LIVE_CLAUSE_PROGRESS_ENABLED`.
- [ ] Add a module-level helper `_clause_writer()` that returns `None` when the flag is off; else
  `try: from langgraph.config import get_stream_writer; return get_stream_writer()` and `except Exception:
  return None` (guards the **acquisition** — a direct/CLI call raises `RuntimeError` there; AC-2).
- [ ] Change the loop header from `for clause_id, record in ordered:` to
  `for idx, (clause_id, record) in enumerate(ordered, start=1):`; compute `total = len(ordered)` and
  `writer = _clause_writer()` before the loop.
- [ ] In the **empty-text guard** (before its `continue`): `if writer is not None: writer({"kind":"clause",
  "clause_index": idx, "clause_total": total, "clause_type": getattr(record.get("clause_type"), "value",
  record.get("clause_type")), "retrieval_path": None, "confidence": None})` (AC-8).
- [ ] In the **main path** (after staging `clause_updates[clause_id]`, so `path`/`confidence` are known):
  ```python
  if writer is not None:
      ct = record.get("clause_type")
      writer({
          "kind": "clause", "clause_index": idx, "clause_total": total,
          "clause_type": getattr(ct, "value", ct),
          "retrieval_path": (path.value if path is not None else None),
          "confidence": confidence,
      })
  ```
  (`retrieval_path` mirrors the existing per-clause log line → AC-7 parity.)

---

## Task 6: `runner/core.py` — dual-mode stream  [AC-1, AC-3, AC-4]
- [ ] Add param `on_clause: Optional[Callable[[dict], None]] = None` to `run_pipeline`.
- [ ] `live = on_clause is not None`; `stream_mode = ["values", "custom"] if live else "values"`.
- [ ] In the stream loop: when `live`, unpack `mode, chunk = item`; if `mode == "custom"`: `on_clause(chunk)`
  then `continue` (never touches `seen`/`last_node` — AC-4); else `state = chunk`. When not `live`,
  `state = item` (plain state — byte-identical, AC-3). Keep all existing `current_node`/`seen`/`on_progress`
  node-progress logic operating on `state`, and the delivery/return unchanged.

---

## Task 7: `runner/worker.py` — gate + apply  [AC-3, AC-5]
- [ ] `import app.config as _config` (read the flag live).
- [ ] In `_run_one`, define `def _on_clause(payload: dict) -> None: rec.update_clause_progress(payload)`.
- [ ] Compute `on_clause = _on_clause if _config.CRAG_LIVE_CLAUSE_PROGRESS_ENABLED else None` and pass
  `on_clause=on_clause` to `run_pipeline(...)`.

---

## Task 8: Backend gate  [AC-1..AC-10]
- [ ] `python -X utf8 -m pytest -q` → the new/extended tests pass AND the full suite stays green (existing
  CRAG/core/worker/registry/models tests unchanged except where they assert the new behavior). Fix code, not
  tests, on any surprise (§7).

**Verify:** full backend suite green.

---

## Task 9: Frontend — write failing tests first  [AC-11..AC-14]
- [ ] **[EXTEND] `src/__tests__/_fakeClient.ts`** — add a helper
  `runningStatusWithClauseProgress(clauseProgress, currentNode = "crag_retrieval")` that returns
  `{ ...runningStatus(currentNode), clause_progress: clauseProgress }`.
- [ ] **[NEW] `src/__tests__/clauseProgress.test.tsx`** — mock `getApiClient()` (as `report.test.tsx` does)
  so `getJob` returns a running status carrying `clause_progress` (via `makeFakeClient({ statuses: [...] })`);
  render `<ProcessingView jobId=... />`. Assert: AC-12 (a line for each `recent` entry in the format
  `Clause {i}/{N} · {type?} — {source} ({conf}%)`, with "Local knowledge base" for `local_kb` and "Live web
  search" for `web_fallback`, plus the `{done}/{total} clauses · {m} web-fallbacks` counter); AC-13 (the
  `web_fallback` line carries the emphasis tone class `text-risk-medium`, the `local_kb` line a calm token;
  no raw hex); AC-14 (the 7 stage chips / step indicator still reflect `current_node`, unchanged).
- [ ] Run `npm test` and CONFIRM these fail (the hook/view don't surface `clause_progress` yet).

**Verify:** `clauseProgress.test.tsx` fails for the expected reasons.

---

## Task 10: `src/lib/api/types.ts`  [AC-11]
- [ ] Mirror `ClauseProgressLine` and `ClauseProgress` interfaces field-for-field; add
  `clause_progress?: ClauseProgress | null` to `JobStatus`.

---

## Task 11: `src/lib/useJobStatus.ts`  [AC-12, AC-14]
- [ ] Add `clauseProgress?: ClauseProgress | null` to `JobEventsState`.
- [ ] In `mapStatus`, set `clauseProgress: js.clause_progress ?? null`. Node-progress mapping unchanged (AC-14).

---

## Task 12: `src/components/processing/ProcessingView.tsx`  [AC-12, AC-13, AC-14]
- [ ] Import `evidenceSourceLabel` from `@/components/report/EvidenceSourceBadge`.
- [ ] In the running branch, below the stage chips, when `state.clauseProgress` is present render:
  - the counter `{clauses_done}/{clauses_total} clauses · {web_fallbacks} web-fallbacks`;
  - the `recent` lines, each `Clause {i}/{N} · {clause_type?} — {evidenceSourceLabel(retrieval_path)}
    ({Math.round(confidence*100)}%)` with `clause_type` and the `(…%)` shown only when present; a
    `web_fallback` line uses `text-risk-medium`, a `local_kb` line a calm token (`text-risk-low`/
    `text-text-secondary`) — theme tokens, no hex (AC-13).
- [ ] Do not change the stage chips / step logic (AC-14).

---

## Task 13: `src/lib/api/fixtures.ts` + `src/lib/api/mockProvider.ts`  [offline exercisable]
- [ ] **fixtures.ts:** add `clauseProgressFixture: ClauseProgress` (e.g. `clauses_done:7, clauses_total:12,
  web_fallbacks:2, recent:[{clause_index:6,clause_total:12,clause_type:"liability",retrieval_path:"local_kb",confidence:0.82},{clause_index:7,clause_total:12,clause_type:"indemnification",retrieval_path:"web_fallback",confidence:0.61}]}`).
- [ ] **mockProvider.ts `getJob`:** make it script a short per-`jobId` sequence via a module-level call
  counter — 1st call `queued`; next two `running` (`current_node:"crag_retrieval"`) carrying a growing
  `clause_progress` (reuse `clauseProgressFixture`/a smaller variant); thereafter `completed` (sticky,
  `completedStatusFixture`). If any existing mock-based test assumed `getJob` returns completed immediately,
  pin it to the new sequence (never weaken, §7).

---

## Task 14: Frontend gate  [AC-11..AC-15]
- [ ] `npm test` (vitest) → `clauseProgress.test.tsx` + full existing suite green.
- [ ] `npx tsc --noEmit` → clean (types mirrored). eslint → no new errors. `npm run build` → compiles.
- [ ] `git diff --name-only main` matches the Task-0/plan §0 allow-list (no routes/SSE/ContractState/
  migration change).

**Verify:** all four FE gate commands pass; diff scope matches.

---

## Task 15: Merge
- [ ] Full backend + frontend gate green; diff scope confirmed. Rebase `main`, merge
  `feature/059-live-crag-narration`, delete branch (`git-finish`). **Flag ships OFF (default False)**; a live
  smoke + flip-on is a follow-up (D4).

---

*Per §1/§11, implementation happens only on `feature/059-live-crag-narration`, opened after spec + plan +
tasks are all spec-reviewer-APPROVED. Observability only — no graph/`ContractState`/API/migration change;
`routes.py`, the SSE `events.py`/`/events` path, and `JobRow`/persistence are NOT modified.*
