# Feature 061 — Per-user learned clause KB — Implementation Tasks

Reference documents:
- Spec: `specs/061-learned-clause-kb/spec.md`
- Plan: `specs/061-learned-clause-kb/plan.md`
- Constitution: `specs/000-constitution.md` (**§2 + the 2026-10-07/061 amendment**; **§3** named config;
  **§4/§10** no `ContractState` change; **§7** TDD / never weaken a test; **§8** BGE-M3 embeddings, model
  separation; **§9** local-model latency; **§11** branch workflow; **§019** per-user isolation)

Backend paths relative to `backend/`.

**Workflow reminders:**
- **No new graph node/edge.** Write = runner post-run side-effect; read = in-node augmentation of CRAG
  (node 3). `app/graph/builder.py` is NOT touched. No `ContractState`/`specs/001` change. No migration. No
  new dependency (faiss/numpy already present).
- **Reversible flag `CRAG_USER_KB_ENABLED`, default `False`** — off ⇒ byte-identical to today (no per-user
  write, no per-user read).
- **Scope allow-list (AC-11)** = plan §0 files + the new tests. Nothing else — especially NOT `builder.py`,
  `specs/001`, any migration, the base KB files, the renderers/delivery, or any frontend file.
- **TDD (§7):** write each layer's tests first, confirm FAIL, then implement to green. Never weaken a test.
- **Isolation (§019):** a user's index is private; one account can NEVER read another's — enforced by the
  `user_id`-scoped path. Store ONLY validated findings (`ValidationStatus.VALIDATED`).

---

## Task 0: Branch
- [ ] From up-to-date `main` (`git checkout main && git pull`), create `feature/061-learned-clause-kb`
  (`git-start`). Commit the APPROVED spec/plan/tasks AND the `specs/000` 061 amendment on the branch.

**Verify:** `git branch --show-current` → `feature/061-learned-clause-kb`.

---

## Task 1: `config.py` — flags (§3)  [AC-1]
- [ ] Add `CRAG_USER_KB_ENABLED: bool = _env_bool("CRAG_USER_KB_ENABLED", False)` in the CRAG config block.
- [ ] Add `CRAG_USER_KB_DIR: str = "data/kb/users"` with a comment: a user's index lives at
  `{CRAG_USER_KB_DIR}/{user_id}/clauses.faiss` (+ `clauses_meta.jsonl` + `clauses.faiss.provider`), resolved
  backend-relative like the base KB.

---

## Task 2: Write the failing tests first  [AC-1..AC-11]  (no Ollama; embeddings mocked; faiss in-proc)
Create the three modules below; confirm they FAIL (symbols absent). Mock `embed_query` to return small fixed
unit vectors; use `tmp_path` + monkeypatch `CRAG_USER_KB_DIR` for an isolated user-KB dir.

- [ ] **[NEW] `tests/unit/test_user_kb.py`** (helper):
  - AC-2: `append_clauses(uid, items)` then `load_user_kb(uid)` → `ntotal == len(items)`, sidecar rows match
    (`snippet_text`/`source_reference`), `len(meta) == ntotal`; a second append accumulates.
  - AC-7: after append, a fresh `load_user_kb` (cache invalidated) sees the new count; two threads appending
    for one user don't lose rows / desync `ntotal` (use the real lock).
  - AC-8: `.provider` marker written for the active provider/model on create.
  - AC-4/security: a `user_id` containing `/`, `\`, or `..` is rejected (no escape of `CRAG_USER_KB_DIR`).
  - EC-8: a corrupt index file → `load_user_kb` returns None (no raise). An item whose `embed_query` → None is
    skipped (no vector/row desync).
- [ ] **[NEW] `tests/unit/test_crag_user_kb_augment.py`** (read side):
  - AC-5: seed a user index so the query's user-KB score ≥ 0.73 while the base-KB score < 0.73 (monkeypatch
    `search_kb`/embeddings to return controlled scores) → CRAG uses the **max**, routes `LOCAL_KB`, includes
    the user snippet. **Negative control:** an unrelated query scoring < 0.73 against the user KB still routes
    `WEB_FALLBACK`.
  - AC-4: a CRAG run for `user_B` never loads/returns `user_A`'s index.
  - AC-6: a direct `crag_retrieval_agent(state)` call (no runnable context) → `get_config` raises
    `RuntimeError` → `user_id=None`, byte-identical, user KB untouched.
  - AC-1: `CRAG_USER_KB_ENABLED=False` → only the base KB is searched (existing CRAG behavior).
- [ ] **[NEW] `tests/unit/test_runner_user_kb_write.py`** (write side):
  - AC-2/AC-3: flag on + `user_id` + a `final_state` with N clauses / M validated (`final_status ==
    ValidationStatus.VALIDATED`) → `user_kb.append_clauses` called with exactly the M validated items, each
    `source_reference` well-formed. (Mock `append_clauses`; build `final_state` fixtures; mock the graph
    stream as existing runner tests do.)
  - AC-10: zero validated → not called; `user_id=None` → not called.
  - AC-1: flag off → not called.
  - AC-9: `append_clauses` raising → `run_pipeline` still returns a normal `RunResult` (error swallowed).
- [ ] Run `python -X utf8 -m pytest -q tests/unit/test_user_kb.py tests/unit/test_crag_user_kb_augment.py
  tests/unit/test_runner_user_kb_write.py` → CONFIRM FAIL for the expected reasons.

---

## Task 3: `app/graph/nodes/retrievers/user_kb.py` (NEW)  [AC-2, AC-4, AC-7, AC-8, EC-8]
- [ ] Module mirrors `kb_retriever` conventions (faiss, numpy, json). Reuse
  `kb_retriever._resolve_backend_path` and `kb_retriever._warn_on_provider_mismatch`.
- [ ] `_user_paths(user_id)` → `(index_path, meta_path, marker_path)` under `CRAG_USER_KB_DIR/{slug}`; `slug`
  rejects `/`, `\`, `..` (raise `ValueError` — never escape the base dir).
- [ ] `load_user_kb(user_id) -> Optional[_LoadedKB]`: same guards as `load_kb` (missing/corrupt index or
  sidecar → None; `len(meta) != index.ntotal` → None; provider-mismatch → warn, not fail). Per-user cache
  `dict[str,_LoadedKB]`, invalidated by `append_clauses`.
- [ ] `append_clauses(user_id, items)` (`items`: `[{"text","source_reference"}]`) → returns count appended:
  - acquire a per-user `threading.Lock` (module `dict[str,Lock]` via a guarded `setdefault` under a module
    lock);
  - embed each `text` with `embed_query(text, CRAG_EMBED_TIMEOUT_SECONDS, OLLAMA_EMBED_MODEL_NAME)` (import
    both constants from `app.config`, mirroring `kb_retriever`'s `import app.config as _config`); skip `None`
    results (embed failure) — keep vectors and rows 1:1;
  - load-or-create the index: existing → `faiss.read_index`; new → `faiss.IndexFlatIP(dim)` (inner product on
    L2-normalized vectors == cosine, matching the base KB). `dim` = base KB `index.d` if available else the
    first embedding's length;
  - `index.add` the stacked vectors; append one meta row per vector (`{"snippet_text","source_reference"}`);
  - persist **atomically**: write index to a temp file + `os.replace`; write the sidecar so `ntotal` and rows
    never desync; write/refresh the `.provider` marker (base-KB JSON shape) on create;
  - invalidate the per-user cache entry.

---

## Task 4: `crag_retrieval_agent.py` — read augmentation  [AC-5, AC-6, AC-1]
- [ ] Re-expose `CRAG_USER_KB_ENABLED = _config.CRAG_USER_KB_ENABLED` module-level (monkeypatch seam).
- [ ] Add a guarded helper (reviewer-pinned API — do NOT cite 059):
  ```python
  def _run_user_id():
      if not CRAG_USER_KB_ENABLED:
          return None
      try:
          from langgraph.config import get_config
          cfg = get_config()
      except RuntimeError:   # no runnable context (direct call / CLI) — AC-6
          return None
      except Exception:      # noqa: BLE001
          return None
      return (cfg or {}).get("configurable", {}).get("user_id")
  ```
  Call it once near where `_clause_writer()` is acquired; `user_kb_handle = load_user_kb(uid) if uid else None`.
- [ ] In block **d** (KB + `query_vec` present): keep the base `kb_result = search_kb(kb, query_vec,
  CRAG_TOP_K)`; when `user_kb_handle`, also `user_res = search_kb(user_kb_handle, query_vec, CRAG_TOP_K)`.
  `confidence = max(base_score, user_score)`; `>=` threshold routing unchanged.
- [ ] In block **e** for `LOCAL_KB`: merge snippets (the stronger source first), then block **f** caps at
  `CRAG_MAX_EVIDENCE_SNIPPETS` (unchanged). User KB absent ⇒ byte-identical to today.

---

## Task 5: `runner/core.py` — user_id kwarg + forward + post-run write  [AC-2, AC-3, AC-9, AC-10, AC-6]
- [ ] Add keyword-only `user_id: Optional[str] = None` to `run_pipeline`.
- [ ] Forward via config WITHOUT changing the no-checkpointer path (reviewer note):
  ```python
  configurable = {"thread_id": thread_id}
  if user_id is not None:
      configurable["user_id"] = user_id
  config = {"configurable": configurable} if checkpointer else None
  ```
- [ ] After `deliver_report_sync` + `processing_completed_at`, before `return RunResult(...)`, best-effort:
  ```python
  if _config.CRAG_USER_KB_ENABLED and user_id:
      try:
          items = _validated_finding_items(final_state)
          if items:
              from app.graph.nodes.retrievers import user_kb
              user_kb.append_clauses(user_id, items)
      except Exception:
          logger.warning("user-KB append failed (best-effort, run unaffected)", exc_info=True)
  ```
- [ ] `_validated_finding_items(final_state)`: iterate `final_state.get("clauses", {})`; select records with
  `record.get("final_status") == ValidationStatus.VALIDATED` (**import `ValidationStatus` from
  `app.graph.state`** — same enum `report_assembler.py:98` uses; there is NO `FindingStatus`). Build
  `{"text": record["text"], "source_reference": f"Your contract: {final_state.get('original_filename') or
  document_id} — {risk} risk"}` where `risk = record.get("risk_level")` (a `RiskLevel`, but it may round-trip
  as a plain `str` after checkpointing — normalize it the way the assembler does by reusing
  `report_assembler._enum_value`, NOT a blind `.value`; graceful fallback if absent). One small function with a
  comment pointing at the assembler to prevent drift.

---

## Task 6: `runner/worker.py` — pass the user_id  [AC-2]
- [ ] At the `run_pipeline(...)` call site, pass `user_id=rec.user_id` (already stamped on the record, §019).
  No other worker change.

---

## Task 7: Backend gate  [AC-1..AC-11]
- [ ] `python -X utf8 -m pytest -q` → the three new modules pass AND the full suite stays green (base-KB CRAG
  tests + runner tests unchanged). Fix code, not tests, on any surprise (§7); pin `CRAG_USER_KB_ENABLED=False`
  only in a test that builds a runnable context picking up a stray config `user_id` (hermetic, not weakened).
- [ ] `git diff --name-only main` matches the §0 allow-list — NO `builder.py` / node-edge / `ContractState` /
  `specs/001` / migration / dependency / frontend change (AC-11).

---

## Task 8: Merge
- [ ] Backend gate green; diff scope matches §0. Rebase `main`, merge `feature/061-learned-clause-kb`, delete
  branch (`git-finish`). Ships with `CRAG_USER_KB_ENABLED` **off**; enabling it (and any durable-storage
  follow-up) is a separate, deliberate step.

---

*Per §1/§11, implementation happens only on `feature/061-learned-clause-kb`, opened after spec + plan + tasks
are all spec-reviewer-APPROVED. No new graph node/edge; `user_id` via the run `config` channel, not
`ContractState`; store only validated findings; per-user isolation (§019); flag ships OFF.*
