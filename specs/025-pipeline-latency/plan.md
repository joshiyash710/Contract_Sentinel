# Pipeline latency reduction (levers A + B) — Technical Plan

## Git Branch

`feature/025-pipeline-latency` — branching workflow per `specs/000-constitution.md` §11.

---

## 1. Overview

Implements `specs/025-pipeline-latency/spec.md` — a **backend/config** tuning feature that reduces
LLM-call volume in the two hottest nodes, via **named configurable constants** (§3), with **no new
node/edge and no `ContractState` change**:
- **Lever A — size-gate the ClauseSplitter LLM refinement** (Node 2): skip `refine_with_llm` only for
  documents whose regex-clause count exceeds `CLAUSE_SPLITTER_LLM_MAX_CLAUSES` (default 40), falling
  back to the regex splitter already in the node. Normal contracts (≤ 40 clauses) are unchanged.
- **Lever B — cut the Self-RAG ISSUP retry loop** (Node 4): `SELF_RAG_MAX_ATTEMPTS` 3 → 1.

Both are reversible via config; no model swap. Lever C (merging Self-RAG's 3 checks) is out of scope.

---

## 2. Files to Create / Modify

### Backend (`backend/`)
```
app/config.py                                 [MODIFY] add CLAUSE_SPLITTER_LLM_MAX_CLAUSES = 40; change SELF_RAG_MAX_ATTEMPTS default 3 → 1 (with §3 rationale comments)
app/graph/nodes/clause_splitter_agent.py      [MODIFY] module alias + size-gate the normal-path refine_with_llm call
tests/unit/test_clause_splitter_agent.py      [MODIFY] add gated-path test (regex count > threshold → refine skipped); existing tests unaffected (≤ threshold)
tests/unit/test_self_rag_validation_agent.py  [MODIFY] pin >1-attempt tests to SELF_RAG_MAX_ATTEMPTS=3; add a MAX_ATTEMPTS=1 single-attempt test
tests/unit/test_config.py                     [MODIFY] change existing `SELF_RAG_MAX_ATTEMPTS == 3` (L127) → `== 1`; add `CLAUSE_SPLITTER_LLM_MAX_CLAUSES == 40`
```
No `self_rag_validation_agent.py` logic change (it already reads the constant). No graph/edge change,
no `ContractState` change, no migration, no endpoint change, no frontend change.

---

## 3. Backend design

### 3.1 `app/config.py`
- Add near the ClauseSplitter section:
  ```python
  # §3: above this regex-clause count, skip the ClauseSplitter LLM refinement and use the regex
  # splitter (latency lever A). Real corpus clusters ~8-clause (normal) vs ~185-clause (large);
  # 40 keeps LLM quality for normal contracts, gates only large-doc outliers. Tunable vs node_timings.
  CLAUSE_SPLITTER_LLM_MAX_CLAUSES: int = 40
  ```
- Change the Self-RAG constant's **default** (keep the existing comment, note the latency rationale):
  `SELF_RAG_MAX_ATTEMPTS: int = 1  # was 3 — one ISSUP attempt, no retries (latency lever B, §3)`.

### 3.2 `app/graph/nodes/clause_splitter_agent.py`
- Add a module-level alias next to the others so tests can monkeypatch:
  `CLAUSE_SPLITTER_LLM_MAX_CLAUSES = _config.CLAUSE_SPLITTER_LLM_MAX_CLAUSES`.
- In the **normal path**, after `split_by_regex` and the existing `MAX_CLAUSES_LIMIT` pre-LLM clamp
  (~L94–103), gate the refine call:
  ```python
  if len(regex_clauses) > CLAUSE_SPLITTER_LLM_MAX_CLAUSES:
      logger.info("ClauseSplitter: %d regex clauses > %d — skipping LLM refine (latency gate)",
                  len(regex_clauses), CLAUSE_SPLITTER_LLM_MAX_CLAUSES)
      refined = regex_clauses
  else:
      refined = refine_with_llm(regex_clauses, CLAUSE_SPLITTER_TIMEOUT_SECONDS, OLLAMA_MODEL_NAME)
  ```
  The post-refine `MAX_CLAUSES_LIMIT` re-clamp/`_renumber` block stays (harmless when `refined is
  regex_clauses`, already ≤ limit from the pre-clamp). `llm_used = refined is not regex_clauses`
  remains correct (False in the gated branch).
- The **short-text path** (single clause, ~L88) is **unchanged** — one clause is always ≤ threshold,
  so it keeps the LLM (clause-type inference preserved for short docs). No gate added there.

### 3.3 `app/graph/nodes/self_rag_validation_agent.py`
- **No change.** It already aliases `SELF_RAG_MAX_ATTEMPTS = _config.SELF_RAG_MAX_ATTEMPTS` (module
  L46) and `_issup_loop` iterates `range(1, SELF_RAG_MAX_ATTEMPTS + 1)`. At the new default `1`, that
  yields one attempt, `retry_count = 0` on validate, `DISCARDED` on a single False — verified, no
  off-by-one.

---

## 4. Tests mapped to acceptance criteria

**Backend (pytest).**
- `test_clause_splitter_agent.py`:
  - **NEW (AC-1):** monkeypatch `clause_splitter_agent_module.CLAUSE_SPLITTER_LLM_MAX_CLAUSES = 2`;
    `split_by_regex` → 3 boundaries; spy `refine_with_llm` (a `MagicMock`). Assert `refine_with_llm.
    assert_not_called()` and that the returned `result["clauses"]` are the 3 regex boundaries verbatim
    (ids/text/positions match; `clause_type` is `None`). **Do NOT assert a `llm_used` return key** — it
    is not in the return dict (`_build_return` only logs it in `extra`); optionally assert the
    `llm_used=False` log record via `caplog`.
  - **NEW/existing (AC-2):** with the default threshold and a small clause count (≤ 40),
    `refine_with_llm` **is** called — the existing `test_splitter_success_basic` already covers this
    (1 clause ≤ 40, refine invoked); optionally add an explicit assertion. Existing tests need **no
    change** (all use ≤ 40 clauses).
  - **Short-text (AC-3):** existing `test_splitter_short_text_single_clause` continues to refine
    (single clause ≤ threshold) — unchanged.
- `test_self_rag_validation_agent.py` (precise pin set — verified against the file):
  - **PIN (AC-5, REQUIRED):** `test_issup_retry_then_pass_validated` (L135, `side_effect=[False,
    True]`, expects `retry_count=1`) **breaks** at the new default (only 1 attempt → DISCARDED); add
    `monkeypatch.setattr(node_mod, "SELF_RAG_MAX_ATTEMPTS", 3)`. Assertions unchanged (not weakened).
  - **OPTIONAL pin:** `test_issup_exhaustion_discarded` (L152) reads `max_attempts =
    node_mod.SELF_RAG_MAX_ATTEMPTS` **dynamically** and asserts `retry_count == max_attempts - 1`, so
    it still **passes** at default=1 (does not require pinning); pin it to 3 only if you want to keep
    exercising multi-attempt exhaustion.
  - **LEAVE:** `test_attempt_cap_enforced` (L169) already self-pins to 2 — do not touch.
  - **Step 1 surfaces the rest:** run the suite after the config flip (§5.1) to catch any other
    attempt-dependent test (e.g. re-check `test_only_issup_retries`, L184); pin only those that
    genuinely need > 1 attempt.
  - **NEW (AC-4):** with `node_mod.SELF_RAG_MAX_ATTEMPTS = 1` and `check_issup` returning `False`
    once, assert `check_issup` is called **once**, `retry_count = 0`, outcome `DISCARDED`.
- `test_config.py` (**AC-6**): the existing `assert SELF_RAG_MAX_ATTEMPTS == 3` (**L127**) must be
  **changed to `== 1`** (it is a hard break, not an addition); add
  `assert CLAUSE_SPLITTER_LLM_MAX_CLAUSES == 40`.
- **AC-7:** whole `pytest` green after the pins; `git diff` shows no graph/edge/`ContractState`
  change.

**Live smoke (AC-8):** real Ollama, run the full pipeline on a large (100+ clause) contract and on a
normal one; capture `node_timings` before/after. Large doc → `clause_splitter` drops to near-0 (no
LLM); Self-RAG time does not grow; total wall-clock materially lower; a coherent report (findings,
risk bands, redlines) is still produced.

---

## 5. Implementation order (TDD — §7)

1. **Config (red-enabling):** add `CLAUSE_SPLITTER_LLM_MAX_CLAUSES = 40`; flip `SELF_RAG_MAX_ATTEMPTS`
   → 1. Run `pytest` — expect **two** kinds of failure that prove the defaults took effect:
   `test_config.py::…` (the `== 3` assertion, L127) and the > 1-attempt Self-RAG test(s)
   (`test_issup_retry_then_pass_validated`). This pinpoints exactly which tests need the D6 pin/edit.
2. **Pin Self-RAG tests (green):** add `monkeypatch.setattr(node_mod, "SELF_RAG_MAX_ATTEMPTS", 3)` to
   the multi-attempt tests; add the new `MAX_ATTEMPTS=1` single-attempt test.
3. **Node A test (red) → gate (green):** write the gated-path clause-splitter test (threshold 2,
   3 clauses, spy refine) — failing; then add the module alias + size-gate to
   `clause_splitter_agent.py` until it passes. Confirm existing clause-splitter tests still green
   (≤ threshold → refine still called).
4. **Config test:** assert the new defaults in `test_config.py`.
5. **Verify:** whole `pytest` green; `git diff --name-only main` shows only `app/config.py`,
   `app/graph/nodes/clause_splitter_agent.py`, and the three test files — no graph/edge/state/
   migration/frontend change.
6. **Live smoke (AC-8):** before/after `node_timings` on a large + a normal contract (real Ollama).

Tests are written/observed failing first (§7). The Self-RAG pins are the one sanctioned change to
existing tests — they encode the OLD default explicitly, not a weakened assertion.

---

## 6. Notes / risks

- **Existing clause-splitter tests don't break** because they all use ≤ 40 clauses (mostly 1), so the
  gate is inactive and `refine_with_llm` still runs — verified against the current fixtures. Also
  checked and **unaffected**: `tests/unit/test_llm_refiner.py` (targets the refiner unit directly, not
  the agent gate) and `tests/integration/test_clause_splitter_graph.py` (patches the whole node /
  uses small clause counts).
- **Two existing tests break at the new defaults** (not one): (a) `test_config.py` L127
  `assert SELF_RAG_MAX_ATTEMPTS == 3` → edit to `== 1`; (b)
  `test_self_rag_validation_agent.py::test_issup_retry_then_pass_validated` needs ≥ 2 attempts → pin
  to 3. `test_issup_exhaustion_discarded` reads the constant dynamically and does **not** break;
  `test_attempt_cap_enforced` self-pins to 2. Step 1 runs the suite to confirm this exact set — do not
  weaken assertions, only pin the attempt count each test intends (or edit the config-value assertion).
- **Monkeypatch the node-module alias, not `_config`** — both nodes bind the constant at import
  (`X = _config.X`), so tests must set `node_mod.X` for it to take effect inside the function.
- **Small docs get no Lever-A speedup** (they keep the LLM) — expected (spec D1); Lever B still helps
  them. The AC-8 smoke should use a large doc to observe the clause-splitter win.
- **`clause_type=None` on gated large docs** flows to existing null-safe handling (017 titles,
  Self-RAG rescue simply not firing) — no crash; covered by existing null-severity/degraded paths.
- **Fully reversible:** raise `CLAUSE_SPLITTER_LLM_MAX_CLAUSES` and `SELF_RAG_MAX_ATTEMPTS` to restore
  today's behavior.

---

*Per §1/§11, a `feature/025-pipeline-latency` branch opens only after this plan.md + spec.md are
approved and `tasks.md` exists. No migration, no frontend. No `tasks.md`/implementation in this pass
— plan only.*
