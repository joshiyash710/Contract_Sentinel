# Feature 061 — Technical plan: per-user learned clause KB

Branch: `feature/061-learned-clause-kb` (per constitution §11).

Derived from the approved `spec.md` and the 2026-10-07/061 §2 amendment. Two seams, no graph change:
**(write)** a runner post-run side-effect appends the run's **validated-finding** clauses to the uploading
user's **private** FAISS index; **(read)** CRAG (node 3) additionally searches that user's index and takes the
**better** match vs the base KB, raising the local-hit rate. **No new node/edge, no `builder.py` change, no
`ContractState`/`specs/001` change, no migration, no new dependency** (faiss/numpy already present).
Reversible: `CRAG_USER_KB_ENABLED` default off ⇒ byte-identical to today.

## 0. Scope of change (files touched)
```
specs/000-constitution.md                               (the 061 amendment — already added)
backend/app/config.py                                   (CRAG_USER_KB_ENABLED, CRAG_USER_KB_DIR)
backend/app/rag/__init__.py                             (NEW — app.rag package init; see Location note)
backend/app/rag/user_kb.py                              (NEW — per-user load/append/lock/cache helper; see Location note)
backend/app/graph/nodes/retrievers/kb_retriever.py      (REUSE-ONLY, UNMODIFIED — _resolve_backend_path / _warn_on_provider_mismatch were already module-level)
backend/app/graph/nodes/crag_retrieval_agent.py         (read user_id via config; augment search with user KB)
backend/app/runner/core.py                              (user_id kwarg; forward via config; post-run append)
backend/app/runner/worker.py                            (pass rec.user_id into run_pipeline)
backend/tests/unit/test_user_kb.py                      (NEW — helper: load/append/lock/cache/provider)
backend/tests/unit/test_crag_user_kb_augment.py         (NEW — CRAG augmentation + isolation + guarded config)
backend/tests/unit/test_runner_user_kb_write.py         (NEW — post-run append: validated-only, best-effort, degenerate)
backend/tests/...                                       (pin CRAG_USER_KB_ENABLED off in any flip-exposed test, if needed)
specs/061-learned-clause-kb/{spec,plan,tasks}.md
```
**NOT touched:** `backend/app/graph/builder.py` (no node/edge); `specs/001`/`ContractState`; any Alembic
migration; the base KB files `data/kb/clauses.*`; the report renderers / delivery; any frontend file.

**Location note (as-built; differs from this plan's first draft):** `user_kb` lives in the **`app/rag/`**
package, NOT `app/graph/nodes/retrievers/`. The runner-isolation guard
(`tests/unit/test_runner_core.py::test_only_public_entrypoints_imported` and
`tests/integration/test_runner_graph_untouched.py::test_builder_not_modified_by_runner`) asserts that
`app/runner/core.py`'s source contains no `app.graph.nodes.` reference at all (even in a comment). Since the
runner must call the KB writer, the KB store had to be a **shared `app/rag` library** that BOTH CRAG (a node)
and the runner can import without crossing that boundary — which is also the home the spec (§2) hinted at
("an `app/rag`-style helper"). `kb_retriever.py` is unchanged (its `_resolve_backend_path` /
`_warn_on_provider_mismatch` were already module-level and are imported as-is). Merged to main in commit
`1ea50f86`; full backend suite 1182 passed.

## 1. `config.py` (§3, D5)
- `CRAG_USER_KB_ENABLED: bool = _env_bool("CRAG_USER_KB_ENABLED", False)` — gates BOTH the write and the read
  augmentation. Default off ⇒ today's behavior.
- `CRAG_USER_KB_DIR: str = "data/kb/users"` — base dir; a user's index is
  `{CRAG_USER_KB_DIR}/{user_id}/clauses.faiss` + `clauses_meta.jsonl` + `clauses.faiss.provider`, resolved
  backend-relative via `kb_retriever._resolve_backend_path` (reused).
- `user_id` is used only as a path segment; sanitize to a safe slug (the §019 `user_id` is already an
  opaque id, but the helper must reject path separators / `..` defensively — AC-4/security).

## 2. `user_kb.py` (NEW) — per-user index helper
A small module mirroring `kb_retriever` conventions (faiss + numpy + json + a `_LoadedKB`-shaped handle).
- **Paths:** `_user_paths(user_id) -> (index_path, meta_path, marker_path)` under `CRAG_USER_KB_DIR/{slug}`;
  `slug` rejects `/`, `\`, `..` (raise/clamp — never escape the base dir).
- **`load_user_kb(user_id) -> Optional[_LoadedKB]`:** same guards as `kb_retriever.load_kb` (missing index/
  sidecar → None; `faiss.read_index` failure → None; `len(meta) != index.ntotal` → None; provider-mismatch
  **warn** via the reused `kb_retriever._warn_on_provider_mismatch`). **Per-user cache** `dict[str,_LoadedKB]`
  (module-level), so repeated loads in one process are cheap; invalidated by `append_clauses`.
- **`append_clauses(user_id, items: list[dict])`** where each item is
  `{"text": <clause text>, "source_reference": <str>}`:
  - under a **per-user write lock** (`threading.Lock` kept in a module `dict[str, Lock]` via a guarded
    `setdefault`) — serializes concurrent same-user appends (AC-7/EC-5);
  - embed each `text` with BGE-M3 via `retrievers.embeddings.embed_query(text, CRAG_EMBED_TIMEOUT_SECONDS,
    OLLAMA_EMBED_MODEL_NAME)` (already L2-normalized, the exact vectors `search_kb` expects); skip items whose
    embedding is `None` (embed failure) — never write a vector/row pair out of sync;
  - load-or-create the index: if the file exists, `faiss.read_index`; else create a fresh
    `IndexFlatIP(dim)` matching the base KB's metric (inner-product on normalized vectors == cosine, as
    `search_kb` assumes). `faiss.add` the stacked vectors; append one JSONL meta row per added vector
    (`{"snippet_text": text, "source_reference": ref}`);
  - **persist atomically:** write the index to a temp path + `os.replace`; append-then-flush the sidecar (or
    rewrite both from the loaded state) so `ntotal` and the sidecar never desync even on a crash mid-write;
    write/refresh the `.provider` marker for the active `EMBED_PROVIDER`/model (reuse the base KB's marker
    JSON shape) on create;
  - **invalidate** the per-user cache entry for `user_id`.
  - Signature returns the count actually appended (for the runner's debug log / tests).
- **Dimension:** read the base KB's `index.d` when available, else the embedding length of the first item, so
  the user index matches the active embedding model's dim.

## 3. `crag_retrieval_agent.py` — read-side augmentation (AC-5, AC-6, AC-10)
- Re-expose `CRAG_USER_KB_ENABLED = _config.CRAG_USER_KB_ENABLED` module-level (monkeypatch seam, like the
  other CRAG constants).
- **Read `user_id` from the run config, guarded** (reviewer note 1 — do NOT cite 059; pin the exact API):
  ```python
  def _run_user_id():
      if not CRAG_USER_KB_ENABLED:
          return None
      try:
          from langgraph.config import get_config
          cfg = get_config()
      except RuntimeError:      # no runnable context (direct node call / CLI) — AC-6
          return None
      except Exception:         # noqa: BLE001 — any import/context issue → no user KB
          return None
      return (cfg or {}).get("configurable", {}).get("user_id")
  ```
  Call it once near the top of `crag_retrieval_agent` (same place `_clause_writer()` is acquired).
- Load the user KB once: `user_kb_handle = load_user_kb(uid) if uid else None`.
- In the per-clause decision (block **d**), when both `kb` and a `query_vec` exist, compute the base result
  as today **and**, when `user_kb_handle` is present, `user_res = search_kb(user_kb_handle, query_vec,
  CRAG_TOP_K)`. Use `confidence = max(base_score, user_score)` for the 0.73 routing (`>=` inclusive,
  unchanged). If the user KB is the max and clears the threshold, `path = LOCAL_KB`.
- In evidence gather (block **e**) for `LOCAL_KB`: merge `base.snippets + user.snippets` (user first when it
  was the stronger match) then cap at `CRAG_MAX_EVIDENCE_SNIPPETS` (block **f** cap unchanged). When the user
  KB is absent, behavior is byte-identical to today.
- `search_kb` / `load_kb` are unchanged; the user KB reuses `search_kb` with the user handle.

## 4. `runner/core.py` + `worker.py` — write-side + config forwarding (AC-1, AC-2, AC-3, AC-9, AC-10)
- **`run_pipeline` gains `user_id: Optional[str] = None`** (keyword-only, defaulted ⇒ existing callers
  byte-identical).
- **Forward to the graph config (reviewer note 2):** the config dict is currently built **only when
  `checkpointer` is set** (`core.py:74`). Thread `user_id` into that same dict without changing the
  no-checkpointer path:
  ```python
  configurable = {"thread_id": thread_id}
  if user_id is not None:
      configurable["user_id"] = user_id
  config = {"configurable": configurable} if checkpointer else None
  ```
  So the authenticated worker path (always checkpointed, 012) carries `user_id`; the CLI/no-checkpointer path
  stays `config=None` ⇒ CRAG resolves `user_id=None` (byte-identical streaming — AC-6/EC-2). Read-side
  augmentation is therefore active on the authenticated/checkpointed path (the only path with a real user).
- **Post-run append (best-effort, AC-9):** after `deliver_report_sync` / setting
  `processing_completed_at`, before returning `RunResult`:
  ```python
  if _config.CRAG_USER_KB_ENABLED and user_id:
      try:
          items = _validated_finding_items(final_state)   # [] when none
          if items:
              from app.rag import user_kb
              user_kb.append_clauses(user_id, items)
      except Exception:
          logger.warning("user-KB append failed (best-effort, run unaffected)", exc_info=True)
  ```
  - `_validated_finding_items(final_state)`: iterate `final_state.get("clauses", {})`, select records whose
    finding is **validated** using the **same predicate `report_assembler` uses** — `record.get("final_status")
    == ValidationStatus.VALIDATED`. The enum is `ValidationStatus` (defined in `app/graph/state.py:55`,
    imported into the assembler from `app.graph.state`; report_assembler.py:98 writes the negation `!=
    ValidationStatus.VALIDATED`). **Import `ValidationStatus` from `app.graph.state`** — there is NO
    `FindingStatus` symbol in the codebase. Build each item as `{"text": record["text"], "source_reference":
    f"Your contract: {final_state.get('original_filename') or document_id} — {risk} risk"}` where
    `risk = record.get("risk_level")` (a `RiskLevel` enum, `state.py:60`; use its `.value`/str, and fall back
    gracefully if absent). Keep this selection a single small function with a comment pointing at the assembler
    so the two can't drift.
- **`worker.py`:** the call site that invokes `run_pipeline` for a job passes `user_id=rec.user_id` (the
  `user_id` already stamped on the record, §019; worker.py ~110/129). No other worker change.

## 5. Tests (TDD — write first, confirm failing, then implement). No Ollama; embeddings mocked.
### `test_user_kb.py` (helper)
- append → `load_user_kb` returns a handle with `ntotal == len(items)` and matching sidecar rows (AC-2);
  provider marker written (AC-8); second append accumulates (AC-2); cache invalidated after append so a
  reload sees the new count (AC-7); two threads appending for one user don't lose rows / desync `ntotal`
  (AC-7/EC-5); a bad `user_id` with `..`/separators is rejected (AC-4/security); corrupt index → None (EC-8);
  embed→None item is skipped, no vector/row desync.
### `test_crag_user_kb_augment.py` (read side)
- Seed a user index with a clause vector that scores ≥ 0.73 for a query the **base KB** scores < 0.73 (mock
  both `search_kb` results / embeddings): CRAG routes `LOCAL_KB` using the max and includes the user snippet
  (AC-5). **Negative control:** an unrelated query still scores < 0.73 against the user KB → still
  `WEB_FALLBACK` (Evaluation guardrail). Isolation: a run for `user_B` never loads/returns `user_A`'s index
  (AC-4). Guarded config: direct node call (no runnable context) → `get_config` RuntimeError → `user_id=None`,
  byte-identical, user KB untouched (AC-6). Flag off → only base KB searched (AC-1).
### `test_runner_user_kb_write.py` (write side)
- With flag on + `user_id` + a `final_state` of N clauses / M validated → `append_clauses` called with exactly
  the M validated items (AC-2/AC-3), `source_reference` well-formed. Zero validated → not called (AC-10). Flag
  off → not called (AC-1). `user_id=None` → not called (AC-10). `append_clauses` raising → `run_pipeline`
  still returns a normal `RunResult` (AC-9). (Mock `user_kb.append_clauses` + build `final_state` fixtures;
  the graph stream itself is mocked as the existing runner tests do.)
### Regression
- Run the full suite; if any existing CRAG/runner test is exposed by the default-OFF flag resolution, it
  should already pass (flag defaults off) — only pin `CRAG_USER_KB_ENABLED=False` explicitly if a test builds
  a runnable context that would pick up a stray config `user_id` (§7 — pin, never weaken).

## 6. Correctness / constitution
- **§2 + 061 amendment:** no new node/edge; write is a runner side-effect, read augments node 3 in place;
  `builder.py` untouched (AC-11).
- **§4/§10:** `user_id` rides the run `config` channel, not `ContractState`; `specs/001` unchanged.
- **§019:** per-user index path-scoped and private; isolation test (AC-4); no cross-account read ever.
- **§8:** learned clauses embedded with BGE-M3 (embedding model), never the generative model; provider marker
  guards a mismatch (AC-8).
- **§3:** `CRAG_USER_KB_ENABLED` named + env-overridable; default off ⇒ reversible/byte-identical (AC-1).
- **§9:** the post-run embed of M clauses uses the local BGE-M3 and may take seconds — it runs **after** the
  report is produced/delivered and is **best-effort** (swallowed on failure, AC-9), so it never blocks or
  breaks the user-visible result.
- **§7:** new tests written first and confirmed failing; existing tests pinned (not weakened) only if exposed.

## 7. Risks / limitations
- **Self-reference / quality:** validated-only storage (D2) is the guardrail; the Evaluation negative-control
  test asserts unrelated clauses don't spuriously clear 0.73 against the user KB.
- **Unbounded growth (keep-forever, EC-10):** no TTL/GC in v1; bounded by disk, reversible by disabling the
  flag / deleting the user dir.
- **Durability:** v1 stores on disk under `CRAG_USER_KB_DIR`; a Turso/blob backend for the per-user index is a
  noted follow-up (spec §5), not built here. On an ephemeral deploy the learned KB would not persist across
  redeploys — acceptable for v1 (flag ships off).
- **Read-augmentation requires the checkpointed path:** by design (reviewer note 2) the CLI/no-checkpointer
  path carries no `user_id`; only authenticated worker runs augment. The write side is independent of the
  checkpointer and works whenever `user_id` is passed.

## 8. Verification gate (all offline)
- `python -X utf8 -m pytest -q` → the three new test modules pass AND the full suite stays green (base-KB
  CRAG tests, runner tests unchanged); no Ollama/network.
- `git diff --name-only main` == the §0 allow-list — no `builder.py` / node-edge / `ContractState` /
  `specs/001` / migration / dependency / frontend change (AC-11).

## 9. Merge
Full backend gate green; diff scope matches §0. Rebase `main`, merge `feature/061-learned-clause-kb`, delete
branch (`git-finish`). Ships with `CRAG_USER_KB_ENABLED` **off**; enabling it (and any durable-storage
follow-up) is a separate, deliberate step.
