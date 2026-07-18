# Pipeline latency reduction (levers A + B) — Implementation Tasks

Reference documents:
- Spec: `specs/025-pipeline-latency/spec.md`
- Plan: `specs/025-pipeline-latency/plan.md`
- Constitution: `specs/000-constitution.md` (**§3** configurable constants, **§7** TDD; no amendment,
  no new node/edge, no `ContractState` change, no migration, no frontend)

Backend paths relative to `backend/`.

**Workflow reminders:**
- TDD (§7): tests written/observed FAILING before implementation.
- **Both levers are named config constants (§3)** — never hardcode either value in node logic.
- Nodes bind the constant at import (`X = _config.X`); tests must monkeypatch the **node-module**
  attribute (e.g. `node_mod.SELF_RAG_MAX_ATTEMPTS`, `clause_splitter_agent_module.CLAUSE_SPLITTER_LLM_MAX_CLAUSES`),
  NOT `_config`.
- **No** graph/edge change, **no** `self_rag_validation_agent.py` logic change (Lever B is config-only),
  **no** `ContractState`/migration/endpoint/frontend change.
- Do not weaken any existing assertion — pins encode the OLD default explicitly.

---

## Task 0: Branch
- [ ] From up-to-date `main`, create `feature/025-pipeline-latency` (`git-start`). Commit the 025
  `spec.md`/`plan.md`/`tasks.md` on the branch.

**Verify:** `git branch --show-current` → `feature/025-pipeline-latency`.

---

## Task 1: Config change + surface the breaks (red)
- [ ] **[MODIFY] `app/config.py`** — near the ClauseSplitter section add:
  ```python
  # §3: above this regex-clause count, skip the ClauseSplitter LLM refinement and use the regex
  # splitter (latency lever A). Corpus clusters ~8-clause (normal) vs ~185-clause (large); 40 keeps
  # LLM quality for normal contracts, gates only large-doc outliers. Tunable vs node_timings.
  CLAUSE_SPLITTER_LLM_MAX_CLAUSES: int = 40
  ```
  and change the Self-RAG constant's default (keep the existing comment; add the latency note):
  `SELF_RAG_MAX_ATTEMPTS: int = 1  # was 3 — one ISSUP attempt, no retries (latency lever B, §3)`.
- [ ] Run `pytest` and CONFIRM exactly two kinds of red (proves the defaults took effect):
  - `tests/unit/test_config.py` — the `assert SELF_RAG_MAX_ATTEMPTS == 3` at **L127**.
  - `tests/unit/test_self_rag_validation_agent.py::test_issup_retry_then_pass_validated` (needs ≥ 2
    attempts). Note any OTHER attempt-dependent failure the run surfaces (e.g. re-check
    `test_only_issup_retries`) — pin only those that genuinely need > 1 attempt in Task 2.

**Verify:** the two expected tests are red; catalog any extra reds for Task 2.

---

## Task 2: Fix/pin the affected tests (green) — no logic yet
- [ ] **[MODIFY] `tests/unit/test_config.py`** — change the existing `assert SELF_RAG_MAX_ATTEMPTS ==
  3` (L127) to `== 1`; **add** `assert CLAUSE_SPLITTER_LLM_MAX_CLAUSES == 40` (import it alongside).
- [ ] **[MODIFY] `tests/unit/test_self_rag_validation_agent.py`:**
  - `test_issup_retry_then_pass_validated` (L135) — add `monkeypatch.setattr(node_mod,
    "SELF_RAG_MAX_ATTEMPTS", 3)` at the top (add the `monkeypatch` fixture param) so it still
    exercises the [False, True] retry path; assertions unchanged.
  - Pin any additional > 1-attempt test found in Task 1 the same way. Do **not** touch
    `test_issup_exhaustion_discarded` (reads the constant dynamically — still passes at 1) or
    `test_attempt_cap_enforced` (already self-pins to 2).
  - **NEW test (AC-4):** `SELF_RAG_MAX_ATTEMPTS = 1` (monkeypatch node_mod) + `check_issup`
    returning `False` **once** → assert `check_issup` called exactly once, `retry_count == 0`, and the
    clause's `final_status`/outcome is `DISCARDED` (mirror the fixtures used by the other issup tests).

**Verify:** `pytest tests/unit/test_config.py tests/unit/test_self_rag_validation_agent.py` → GREEN.
Self-RAG node code is UNCHANGED (config-only lever).

---

## Task 3: Clause-splitter gated-path test (red)
- [ ] **[MODIFY] `tests/unit/test_clause_splitter_agent.py`** — add `test_splitter_gated_skips_llm`
  (confirm FAILING): call `clause_splitter_agent(make_state(LONG_TEXT))` — the module's `LONG_TEXT`
  (L40) is > `MIN_CLAUSE_LENGTH`, so the **normal** path runs and `split_by_regex` is invoked (this,
  NOT the boundary text length, is what selects the normal path — see agent L77
  `if len(extracted_text) < MIN_CLAUSE_LENGTH`). Then `monkeypatch.setattr(clause_splitter_agent_module,
  "CLAUSE_SPLITTER_LLM_MAX_CLAUSES", 2)`; monkeypatch `split_by_regex` → **3** `ClauseBoundary`s (their
  own text may be short); `refine_with_llm` = a `MagicMock`. Assert:
  - `refine_with_llm.assert_not_called()`,
  - `result["clauses"]` has the **3** regex boundaries verbatim (ids/text/positions match;
    `clause_type` is `None`),
  - (optional) the `llm_used=False` completion log via `caplog`. **Do NOT** assert a `llm_used`
    return key — it is not in the return dict.
  Also keep an existing/added assertion that at ≤ threshold `refine_with_llm` **is** called
  (`test_splitter_success_basic` already covers this at 1 clause ≤ 40 — leave it unchanged).

**Verify:** `test_splitter_gated_skips_llm` fails (gate not yet implemented).

---

## Task 4: Implement Lever A gate (green)
- [ ] **[MODIFY] `app/graph/nodes/clause_splitter_agent.py`:**
  - Add a module-level alias by the others (~L40): `CLAUSE_SPLITTER_LLM_MAX_CLAUSES =
    _config.CLAUSE_SPLITTER_LLM_MAX_CLAUSES`.
  - In the **normal path**, after `split_by_regex` + the existing `MAX_CLAUSES_LIMIT` pre-clamp
    (~L94-103), gate the refine call:
    ```python
    if len(regex_clauses) > CLAUSE_SPLITTER_LLM_MAX_CLAUSES:
        logger.info("ClauseSplitter: %d regex clauses > %d — skipping LLM refine (latency gate)",
                    len(regex_clauses), CLAUSE_SPLITTER_LLM_MAX_CLAUSES)
        refined = regex_clauses
    else:
        refined = refine_with_llm(regex_clauses, CLAUSE_SPLITTER_TIMEOUT_SECONDS, OLLAMA_MODEL_NAME)
    ```
  - Leave the post-refine `MAX_CLAUSES_LIMIT` re-clamp/`_renumber` block and
    `llm_used = refined is not regex_clauses` as-is (llm_used is correctly False in the gated branch).
  - **Do NOT** gate the short-text path (~L88) — a single clause is always ≤ threshold; it keeps the LLM.

**Verify:** `pytest tests/unit/test_clause_splitter_agent.py` → GREEN (gated test passes; existing
LLM-path tests still pass).

---

## Task 5: Full verification
- [ ] `pytest` (whole backend) GREEN.
- [ ] `git diff --name-only main` shows ONLY: `app/config.py`,
  `app/graph/nodes/clause_splitter_agent.py`, `tests/unit/test_config.py`,
  `tests/unit/test_self_rag_validation_agent.py`, `tests/unit/test_clause_splitter_agent.py`. No
  `app/graph/**` edge/state file, no `self_rag_validation_agent.py`, no migration, no frontend.
- [ ] (Optional) `mypy`/lint per project norm if run for other backend features.

---

## Task 6: Live smoke (AC-8)
- [ ] Before starting Ollama, kill any stale uvicorn/python on :8000 from a prior session (see
  [[feature-023-complete]] gotcha). Ensure the configured model (`qwen3:8b`) is available.
- [ ] Run the full pipeline (via the API/runner) on a **large ~185-clause PDF** and on a normal
  **~8-clause** doc; capture `node_timings` for each, before vs after (compare against `main`).
  Expect: large doc → `clause_splitter` near-0 (no LLM), Self-RAG not larger, total wall-clock
  materially lower, coherent report (findings/risk bands/redlines) still produced; small doc →
  clause_splitter unchanged (LLM still runs), only Self-RAG slightly faster. Report the numbers.

---

## Task 7: Merge
- [ ] Whole `pytest` green; `git diff` scope confirmed; smoke `node_timings` noted.
- [ ] Rebase `main`, merge `feature/025-pipeline-latency`, delete branch (`git-finish`).

---

*Per §1/§11, implementation happens only on `feature/025-pipeline-latency`, opened after spec + plan +
tasks are approved. No migration, no frontend. Both levers reversible via config.*
