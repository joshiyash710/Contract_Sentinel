# Pipeline latency reduction round 2 (levers C + F) — Implementation Tasks

Implements `specs/029-pipeline-latency-round2/plan.md`. TDD per constitution §7 (write/observe the
test failing first, then implement until green; never weaken an assertion to force a pass). All work on
branch `feature/029-pipeline-latency-round2` (§11). Run all `pytest` and scripts from `backend/`.
Monkeypatch the **node/refiner module-level aliases**, never `app.config` (constants are bound at
import).

Legend: each task lists the file(s), the exact change, and the acceptance criteria (AC-n) it satisfies.

---

## Task 0 — Branch (prerequisite)
Only after spec.md + plan.md are approved and this tasks.md exists: `git checkout main` → `git pull
origin main` → `git checkout -b feature/029-pipeline-latency-round2` (use the git-start workflow). Do
not write any `app/` file before the branch exists.

---

## Task 1 — Config constants (AC-18)
**File:** `app/config.py`
Add four named constants with §3 rationale comments:
- Self-RAG section:
  ```python
  SELF_RAG_MERGE_JUDGMENTS: bool = True
  SELF_RAG_MERGED_NUM_PREDICT: int = 384
  ```
- ClauseSplitter section:
  ```python
  CLAUSE_SPLITTER_LLM_EMIT_TEXT: bool = False
  CLAUSE_SPLITTER_LLM_NUM_PREDICT: int = 1024
  ```
**Test first:** in `tests/unit/test_config.py` add:
`assert SELF_RAG_MERGE_JUDGMENTS is True`, `assert SELF_RAG_MERGED_NUM_PREDICT == 384`,
`assert CLAUSE_SPLITTER_LLM_EMIT_TEXT is False`, `assert CLAUSE_SPLITTER_LLM_NUM_PREDICT == 1024`.
Run `pytest tests/unit/test_config.py` → these fail (red) before adding the constants, pass after.
**Then:** run the whole suite `pytest -q` and note any existing test that changed behavior (should be
none yet — nothing reads the new constants). Record the list for Task 3/5 pinning.

---

## Task 2 — Lever C: combined reflector (`check_combined`) (AC-1, AC-2, AC-6, AC-7)
**File:** `app/graph/nodes/validators/reflectors.py`
**Test first** — add to `tests/unit/test_self_rag_reflectors.py` (mock `ollama.Client.chat` the same
way existing reflector tests do):
1. Happy path: chat returns content `'{"relevance":true,"isrel":true,"issup":true,"reason":"x"}'` →
   `check_combined(...)` returns `{"relevance": True, "isrel": True, "issup": True}` and `chat` called
   **once**. (AC-1, AC-2)
2. Whole-call failure → `None`: (a) content is non-JSON `'not json'`; (b) content is a JSON array/scalar
   (not an object) `'[1,2]'`; (c) `chat` raises / times out. Each → `check_combined(...) is None`. (AC-6)
3. Per-key None: (a) content missing `issup` → returned dict has `issup is None`, others bool; (b)
   `relevance` non-bool (`"yes"` and `1`) → `relevance is None`, others preserved. (AC-7)
4. `num_predict`: assert the `chat` call's `options["num_predict"] == SELF_RAG_MERGED_NUM_PREDICT`.
**Then implement:**
- Add module alias `SELF_RAG_MERGED_NUM_PREDICT = _config.SELF_RAG_MERGED_NUM_PREDICT`.
- Add `_COMBINED_PROMPT` merging the three existing rubrics (Relevance = substantive/analyzable
  provision; ISREL = evidence on-topic; ISSUP = evidence supports flagging material risk). It must ask
  for exactly: `{"relevance": true|false, "isrel": true|false, "issup": true|false, "reason": "<one
  short sentence>"}`, no markdown. Use the SAME truncation as `check_isrel`/`check_issup`:
  `clause_trunc = clause_text[:prompt_max_chars]`, `remaining = max(0, prompt_max_chars -
  len(clause_trunc))`, `evidence_str = format_evidence(evidence_snippets, remaining)`.
- `check_combined(clause_text, evidence_snippets, timeout_seconds, model_name, prompt_max_chars) ->
  Optional[dict]`: never raises. Contract exactly as plan §3.2 — `None` on whole-call failure; else
  `{"relevance": v, "isrel": v, "issup": v}` each `bool` or `None`.
- `_call_combined(prompt, timeout_seconds, model_name)`: `ThreadPoolExecutor` + `ollama.Client(timeout=
  timeout_seconds)` + `client.chat(model=..., messages=[{"role":"user","content":prompt}],
  format="json", think=False, options={"num_predict": SELF_RAG_MERGED_NUM_PREDICT, "temperature":
  OLLAMA_TEMPERATURE, **({"seed": OLLAMA_SEED} if OLLAMA_SEED is not None else {})})`. Mirror
  `_run_judgment` timeout/except handling → return `None` on any timeout/exception.
- `_parse_combined(raw) -> Optional[dict]`: `json.loads`; if it raises or result is not a `dict` →
  `None`. Else for each of `relevance`/`isrel`/`issup`: value is the bool if `isinstance(v, bool)` else
  `None` (reject ints/strings, same discipline as `_parse_verdict`).
Run `pytest tests/unit/test_self_rag_reflectors.py` → green. Existing reflector tests untouched.

---

## Task 3 — Lever C: orchestration in `_branch_c_normal` (AC-3, AC-4, AC-5, AC-8, AC-9, AC-10)
**File:** `app/graph/nodes/self_rag_validation_agent.py`
**Test first** — add to `tests/unit/test_self_rag_validation_agent.py`:
- **{T,F}³ parity (AC-3):** parametrize all 8 `(relevance,isrel,issup)` bool combos. For each: run the
  node once with `SELF_RAG_MERGE_JUDGMENTS=True` and `check_combined` monkeypatched to return that
  combo dict; run again with `SELF_RAG_MERGE_JUDGMENTS=False` and `check_relevance/check_isrel/
  check_issup` monkeypatched to the same bools; assert the two runs produce equal
  `final_status`, `relevance_verdict`, `isrel_verdict`, `issup_verdict`, `retry_count` for a non-floor
  clause **with evidence present**.
- **relevance False (AC-4):** merged `{relevance:False,isrel:True,issup:True}` →
  `final_status==DISCARDED`, `isrel_verdict is None`, `issup_verdict is None`.
- **recall-floor short-circuit (AC-5):** clause with a `clause_type ∈ SELF_RAG_RECALL_FLOOR_TYPES`,
  evidence present, merged `{relevance:True,isrel:False,issup:False}` → `final_status==VALIDATED`,
  `isrel_verdict is None`, `issup_verdict is None`.
- **one call per clause (AC-2):** 3-clause doc (all evidence present, non-floor); spy `check_combined`
  → called 3×; `check_relevance/check_isrel/check_issup` **not called**.
- **fail-open whole-call (AC-6):** `check_combined` → `None` → `VALIDATED`, all four verdict fields
  `None`.
- **partial None (AC-7):** merged `{relevance:True,isrel:True,issup:None}` → `VALIDATED`; merged dict
  missing `relevance` (`relevance None`) → `VALIDATED`.
- **per-call accounting (AC-8):** `check_combined` → `None` for `SELF_RAG_LLM_CIRCUIT_BREAKER_THRESHOLD`
  consecutive evidence-present clauses → breaker opens, remaining clauses fail-open VALIDATED, node
  returns `error_count == 1` once. Also assert `check_relevance/isrel/issup` **not** called (breaker
  trips on merged-call events only).
- **empty-evidence untouched (AC-10):** an empty-evidence floor clause still calls `check_issup`
  (text-only) once and NOT `check_combined`; an empty-evidence non-floor clause is a zero-LLM discard
  (neither `check_issup` nor `check_combined` called).
- **reversibility (AC-9):** with `SELF_RAG_MERGE_JUDGMENTS=False`, existing sequential tests still pass;
  pin `SELF_RAG_MERGE_JUDGMENTS=False` (monkeypatch `node_mod.SELF_RAG_MERGE_JUDGMENTS`) only on tests
  that must exercise the sequential path and would otherwise pick up the new `True` default.
**Then implement:**
- Add module alias `SELF_RAG_MERGE_JUDGMENTS = _config.SELF_RAG_MERGE_JUDGMENTS`; import
  `check_combined` from reflectors.
- Add helper `_validated_all_none()` returning `{"relevance_verdict": None, "isrel_verdict": None,
  "issup_verdict": None, "retry_count": None, "final_status": ValidationStatus.VALIDATED}`. Optionally
  refactor the existing inline fail-open/circuit-open literals in `_branch_c_normal`/`_branch_a_rescue`
  to call it (behavior identical).
- In `_branch_c_normal`, at entry branch on `SELF_RAG_MERGE_JUDGMENTS`:
  - `False` → existing sequential body unchanged.
  - `True` → implement exactly the plan §3.3 decision table:
    ```python
    if cb["open"]:
        return _validated_all_none()
    merged = check_combined(text, evidence, SELF_RAG_TIMEOUT_SECONDS, OLLAMA_MODEL_NAME,
                            SELF_RAG_PROMPT_MAX_CHARS)
    _account(None if merged is None else True, cb)
    if merged is None:
        return _validated_all_none()
    relevance, isrel, issup = merged["relevance"], merged["isrel"], merged["issup"]
    if relevance is None:
        return _validated_all_none()
    if relevance is False:
        return {"relevance_verdict": False, "isrel_verdict": None, "issup_verdict": None,
                "retry_count": None, "final_status": ValidationStatus.DISCARDED}
    if ct in SELF_RAG_RECALL_FLOOR_TYPES:
        return {"relevance_verdict": True, "isrel_verdict": None, "issup_verdict": None,
                "retry_count": None, "final_status": ValidationStatus.VALIDATED}
    if isrel is None:
        return {"relevance_verdict": True, "isrel_verdict": None, "issup_verdict": None,
                "retry_count": None, "final_status": ValidationStatus.VALIDATED}
    if isrel is False:
        return {"relevance_verdict": True, "isrel_verdict": False, "issup_verdict": None,
                "retry_count": None, "final_status": ValidationStatus.DISCARDED}
    if issup is None:
        return {"relevance_verdict": True, "isrel_verdict": True, "issup_verdict": None,
                "retry_count": None, "final_status": ValidationStatus.VALIDATED}
    if issup is True:
        return {"relevance_verdict": True, "isrel_verdict": True, "issup_verdict": True,
                "retry_count": 0, "final_status": ValidationStatus.VALIDATED}
    return {"relevance_verdict": True, "isrel_verdict": True, "issup_verdict": False,
            "retry_count": 0, "final_status": ValidationStatus.DISCARDED}
    ```
  - Note `ct` is the normalized `_clause_type_value(record.get("clause_type"))` the caller already
    passes into `_branch_c_normal` today (keep that arg). Do NOT route empty-evidence clauses here —
    `_process_clause` already gates Branch C on evidence present; leave that gate unchanged.
Run `pytest tests/unit/test_self_rag_validation_agent.py` → green.

---

## Task 4 — Lever F: slim refinement in `llm_refiner.py` (AC-11, AC-12, AC-13, AC-14, AC-15, AC-16)
**File:** `app/graph/nodes/splitters/llm_refiner.py`
**Test first** — add to `tests/unit/test_llm_refiner.py`:
- **reassembly exactness (AC-11/12):** `EMIT_TEXT=False` (monkeypatch module alias). Input =
  3 `ClauseBoundary` (positions 1,2,3). Mock `ollama.Client.chat` → content
  `'{"clauses":[{"indices":[1,2],"section_number":"1","clause_type":"payment"},
  {"indices":[3],"section_number":null,"clause_type":null}]}'`. Assert: result has 2 boundaries; the
  chat response carried **no `text` field** (i.e. the parser did not depend on text); `"\n".join(b.text
  for b in result) == "\n".join(c.text for c in input)`; `clause_id`/`position` renumbered `1,2`;
  first `clause_type == "payment"`, second `None`.
- **bad partition → fallback (AC-15):** for each of `indices=[1,1,3]` (dup), `indices=[1,2]` only
  (missing 3), `indices=[1,2,4]` (out of range), and empty `clauses:[]` → `refine_with_llm(...)`
  returns the **original** input list unchanged and does **not** raise.
- **num_predict (AC-14):** `EMIT_TEXT=False` → chat `options["num_predict"] ==
  CLAUSE_SPLITTER_LLM_NUM_PREDICT`; `EMIT_TEXT=True` → `== 4096`.
- **clause_type validation (AC-13):** grouping item with `clause_type:"not_a_type"` → output
  `clause_type is None`; valid value → preserved.
- **emit-text reversibility (AC-16):** with `EMIT_TEXT=True`, the existing refiner tests (text-emitting
  path) pass unchanged — pin `EMIT_TEXT=True` on those tests if the new `False` default would otherwise
  apply.
**Then implement:**
- Add module aliases `CLAUSE_SPLITTER_LLM_EMIT_TEXT = _config.CLAUSE_SPLITTER_LLM_EMIT_TEXT` and
  `CLAUSE_SPLITTER_LLM_NUM_PREDICT = _config.CLAUSE_SPLITTER_LLM_NUM_PREDICT`.
- Add `_GROUPING_PROMPT`: same numbered input segments (`index`, `section_number`, `text`) as the
  current prompt sends, but instruct the model to return, per output clause, the `indices` it groups +
  `section_number` + `clause_type`, and **no text**. Schema:
  `{"clauses":[{"indices":[1,2],"section_number":"1.2" or null,"clause_type":"..." or null}]}`. Rules:
  every input index appears in exactly one output clause; preserve document order; do not invent
  indices; do not split a segment; classify or null.
- In `_call_ollama`, choose by `CLAUSE_SPLITTER_LLM_EMIT_TEXT`:
  - `True` → existing `_LLM_PROMPT`, `num_predict=4096`, existing `_parse_response` (unchanged).
  - `False` → `_GROUPING_PROMPT`, `num_predict=CLAUSE_SPLITTER_LLM_NUM_PREDICT`, new
    `_parse_grouping_response(raw_content, regex_clauses)`.
- Add `_parse_grouping_response(raw_content, regex_clauses) -> list[ClauseBoundary]` (raise `ValueError`
  on any violation so the caller falls back):
  1. `json.loads`; require `data["clauses"]` is a non-empty list.
  2. Flatten `indices` across clauses in output order into `flat`; let `N = len(regex_clauses)`.
     Require `flat == list(range(1, N+1))` (exact ordered partition: each index once, ascending, no
     gaps/dupes/out-of-range). Else raise.
  3. For each output clause: `text = "\n".join(regex_clauses[i-1].text for i in indices)`;
     `section_number` = the LLM value if it is a non-empty `str` else `regex_clauses[indices[0]-1].
     section_number`; `clause_type` = value if in `_VALID_CLAUSE_TYPES` else `None`; build
     `ClauseBoundary(clause_id=f"clause_{k:03d}", text=..., position=k, section_number=..., clause_type=
     ...)` for `k` starting at 1.
  4. Keep the existing `output_chars >= input_chars * 0.5` backstop (always holds for a valid partition).
- `refine_with_llm` signature and fallback-to-`regex_clauses` behavior unchanged.
Run `pytest tests/unit/test_llm_refiner.py` → green. `clause_splitter_agent.py` is NOT edited.

---

## Task 5 — Lever F through the node (AC-17)
**File:** `tests/unit/test_clause_splitter_agent.py` (test only; no node code change)
Add one end-to-end test: default flags; `extracted_text` that regex-splits into a small count (≤
`CLAUSE_SPLITTER_LLM_MAX_CLAUSES` so the Lever-A gate stays inactive); mock the refiner's underlying
`ollama.Client.chat` to a valid grouping response. Assert the node's returned `clauses` dict preserves
the concatenated input text and sets `clause_type`s from the grouping. Confirm existing splitter tests
still pass (they use small clause counts and, if they assert the text-emitting path, pin
`CLAUSE_SPLITTER_LLM_EMIT_TEXT=True`).

---

## Task 6 — Full regression + no-scope-creep gate (AC-19, AC-21)
- Run the entire suite: `pytest -q` → all green.
- **Reversible-path regression (AC-19):** add/confirm a test (or a temporary local run) that with
  `SELF_RAG_MERGE_JUDGMENTS=False` **and** `CLAUSE_SPLITTER_LLM_EMIT_TEXT=True` the pipeline's
  per-clause outputs match pre-029 (the existing sequential + text-emitting tests all green on that
  path is sufficient evidence).
- **AC-21:** `git diff --name-only main` shows ONLY: `app/config.py`,
  `app/graph/nodes/validators/reflectors.py`, `app/graph/nodes/self_rag_validation_agent.py`,
  `app/graph/nodes/splitters/llm_refiner.py`, and the five test files. No graph/edge/state/migration/
  frontend/endpoint change; 7 nodes / 2 conditional edges intact; no `ContractState` field touched.

---

## Task 7 — Live smoke + latency/accuracy measurement (AC-20)
Real Ollama (qwen3:8b), delivery off. From `backend/`:
1. `python -X utf8 scripts/latency_measure.py` on the two corpus docs. Record `self_rag_validation` and
   `clause_splitter` node_timings and wall totals; compare to the 2026-07-28 baseline (self_rag
   ~42–47s, clause_splitter ~58–70s; wall ~177s / ~214s). Expect both node timings to drop.
2. Accuracy spot-check: run the 026 harness (`python -m eval.harness.run --gold eval/gold` then
   `python -m eval.harness.score <run_dir>`) and confirm precision/recall/false-flag and 027
   recall-floor behavior are within the documented noise band (no regression).
3. Record the before/after numbers and the accuracy result in this tasks.md (append a "Measurement
   note" section) so the merge decision is evidence-based (mirrors 025/028). A material accuracy
   regression blocks merge — investigate before proceeding.

---

## Acceptance-criteria coverage map
- AC-1,2 → Task 2 (+ one-call assertion Task 3) · AC-3 → Task 3 · AC-4,5 → Task 3 · AC-6,7 → Task 2 &
  Task 3 · AC-8 → Task 3 · AC-9 → Task 3 · AC-10 → Task 3 · AC-11,12 → Task 4 · AC-13 → Task 4 · AC-14
  → Task 4 · AC-15 → Task 4 · AC-16 → Task 4 · AC-17 → Task 5 · AC-18 → Task 1 · AC-19 → Task 6 · AC-20
  → Task 7 · AC-21 → Task 6.
