# Pipeline latency reduction round 2 (levers C + F) — Technical Plan

## Git Branch

`feature/029-pipeline-latency-round2` — branching workflow per `specs/000-constitution.md` §11.

---

## 1. Overview

Implements `specs/029-pipeline-latency-round2/spec.md` — a **backend/config + prompt** tuning feature
that reduces generative LLM cost in the two hottest nodes, via **named configurable constants** (§3),
with **no new node/edge and no `ContractState` change** (§2):

- **Lever C — merge Self-RAG's three judgment calls into ONE combined prompt** (Node 4): the
  evidence-present validation path ("Branch C") issues a single LLM call returning all three verdicts
  (`relevance`, `isrel`, `issup`) instead of up to three sequential calls. Toggle
  `SELF_RAG_MERGE_JUDGMENTS` (default `True`); `False` = pre-029 sequential path byte-for-byte.
- **Lever F — slim the ClauseSplitter refinement call** (Node 2): the LLM returns **index-grouping +
  `clause_type`** metadata instead of re-emitting full clause text; the refiner **reassembles text
  locally** from the regex segments and uses a reduced output-token cap. Toggles
  `CLAUSE_SPLITTER_LLM_EMIT_TEXT` (default `False`) and `CLAUSE_SPLITTER_LLM_NUM_PREDICT` (default
  1024); `EMIT_TEXT=True` = pre-029 text-re-emitting path byte-for-byte.

Both reversible via config; no model swap. Resolved Open Questions (spec §6) adopted as defaults:
**Q1(a)** index-grouping only (no intra-segment split — the finest granularity is the regex boundary);
**Q2** both levers ON by default; **Q3** per-call circuit-breaker accounting accepted (one event/clause);
**Q4** a merged `issup=False` is terminal (retries require `SELF_RAG_MERGE_JUDGMENTS=False`).
Cross-node merges remain out of scope (would need a §2 amendment).

---

## 2. Files to Create / Modify

### Backend (`backend/`)
```
app/config.py                                     [MODIFY] add 4 constants (2 for Lever C, 2 for Lever F) with §3 rationale comments
app/graph/nodes/validators/reflectors.py          [MODIFY] add _COMBINED_PROMPT + check_combined() + _call_combined()/_parse_combined()
app/graph/nodes/self_rag_validation_agent.py       [MODIFY] add SELF_RAG_MERGE_JUDGMENTS alias; branch _branch_c_normal → merged path
app/graph/nodes/splitters/llm_refiner.py           [MODIFY] add grouping prompt + emit-text branch (index-group parse + local reassembly), num_predict from config
tests/unit/test_self_rag_reflectors.py             [MODIFY] add check_combined unit tests (parse, per-key None, whole-call None)
tests/unit/test_self_rag_validation_agent.py       [MODIFY] add merged-path tests ({T,F}³ parity, fail-open, floor short-circuit, 1-call, per-call accounting); keep sequential tests green with merge OFF where needed
tests/unit/test_llm_refiner.py                     [MODIFY] add grouping-mode tests (reassembly exactness, bad partition → fallback, num_predict, clause_type); keep emit-text tests via EMIT_TEXT=True
tests/unit/test_clause_splitter_agent.py           [MODIFY] add one end-to-end grouping-mode test through the node (text preserved, types set); existing tests unaffected
tests/unit/test_config.py                          [MODIFY] assert the 4 new constants + their defaults
```
No change to `clause_splitter_agent.py` logic (Lever F is fully contained in `llm_refiner.py`, which
already receives `regex_clauses` and can reassemble there). No graph/edge change, no `ContractState`
change, no migration, no endpoint change, no frontend change. The graph still has 7 nodes / 2
conditional edges.

---

## 3. Backend design

### 3.1 `app/config.py` (§3 — named constants, all reversible)
Add near the Self-RAG section:
```python
# Lever C (feature 029, §3): when True, the evidence-present Self-RAG path issues ONE combined-judgment
# LLM call (relevance+isrel+issup) instead of up to 3 sequential calls. False → pre-029 sequential path.
SELF_RAG_MERGE_JUDGMENTS: bool = True
# Output-token cap for the combined judgment call. Sized for a 3-verdict + short-reason JSON object;
# larger than the single-verdict reflectors' 256 so the object cannot truncate. Tunable §3.
SELF_RAG_MERGED_NUM_PREDICT: int = 384
```
Add near the ClauseSplitter section:
```python
# Lever F (feature 029, §3): when False (default), the ClauseSplitter refinement LLM returns index-
# grouping + clause_type metadata (no full text) and the refiner reassembles clause text locally from
# the regex segments. True → pre-029 text-re-emitting prompt (fully reversible).
CLAUSE_SPLITTER_LLM_EMIT_TEXT: bool = False
# Output-token cap for the refinement call when EMIT_TEXT is False (metadata is small). Replaces the
# hardcoded 4096; the emit-text path reverts to 4096. Tunable §3.
CLAUSE_SPLITTER_LLM_NUM_PREDICT: int = 1024
```

### 3.2 `app/graph/nodes/validators/reflectors.py` (Lever C — new combined judgment)
- **New prompt** `_COMBINED_PROMPT` — merges the three existing rubrics (Relevance = is the clause a
  substantive/analyzable provision; ISREL = is the evidence on-topic; ISSUP = does the evidence support
  flagging it as material risk). Instructs a single JSON object, no markdown:
  ```json
  {"relevance": true|false, "isrel": true|false, "issup": true|false, "reason": "<one short sentence>"}
  ```
  Reuses the existing clause/evidence truncation (`clause_text[:prompt_max_chars]` +
  `format_evidence(...)` for the remaining budget) exactly as `check_isrel`/`check_issup` do today.
  This is the evidence-present variant only (Branch C); the empty-evidence text-only ISSUP prompt is
  untouched.
- **New public function** `check_combined(clause_text, evidence_snippets, timeout_seconds, model_name,
  prompt_max_chars) -> Optional[dict]`. Contract (this is the crisp AC-6 vs AC-7 boundary — reviewer
  suggestion #2):
  - Returns **`None`** (whole-call failure → caller fail-opens) when: the call times out / raises, the
    response is non-JSON, or the parsed JSON is not an object.
  - Otherwise returns a **dict** `{"relevance": v, "isrel": v, "issup": v}` where each `v` is a genuine
    `bool` if that key is present and boolean, else **`None`** (per-key missing/non-bool → that verdict
    is `None`, caller applies existing per-verdict fail-open at the point it is consumed).
  - Never raises. Mirrors `_run_judgment`'s `ThreadPoolExecutor` + `ollama.Client(timeout=...)` +
    `think=False` structure; uses `num_predict = SELF_RAG_MERGED_NUM_PREDICT`,
    `temperature=OLLAMA_TEMPERATURE`, `seed=OLLAMA_SEED` (028 determinism preserved).
- **New helpers** `_call_combined(...)` (ollama chat + `_parse_combined`) and `_parse_combined(raw) ->
  Optional[dict]` (reuse the `isinstance(x, bool)` discipline from `_parse_verdict` per key; reject
  ints/strings). Add module aliases `SELF_RAG_MERGED_NUM_PREDICT = _config.SELF_RAG_MERGED_NUM_PREDICT`.

### 3.3 `app/graph/nodes/self_rag_validation_agent.py` (Lever C — orchestration)
- Add module alias `SELF_RAG_MERGE_JUDGMENTS = _config.SELF_RAG_MERGE_JUDGMENTS` and import
  `check_combined`.
- In `_branch_c_normal` (the evidence-present path), branch at the top:
  - **Merge OFF** → existing sequential body unchanged.
  - **Merge ON** → single combined call + the **same decision table**, preserving every verdict field
    and `retry_count` exactly as the sequential path (AC-3). Pseudocode:
    ```python
    if cb["open"]:
        return _validated_all_none()                    # unchanged circuit-open fail-open
    merged = check_combined(text, evidence, SELF_RAG_TIMEOUT_SECONDS, OLLAMA_MODEL_NAME,
                            SELF_RAG_PROMPT_MAX_CHARS)
    _account(None if merged is None else True, cb)       # ONE accounting event per clause (AC-8/Q3):
                                                         #   whole-call failure counts; a parsed object
                                                         #   with a bad key does NOT (call succeeded)
    if merged is None:
        return _validated_all_none()                     # fail-open (AC-6)
    relevance, isrel, issup = merged["relevance"], merged["isrel"], merged["issup"]  # each bool|None
    if relevance is None:      return {rel=None,  isrel=None,  issup=None, retry=None, VALIDATED}  # fail-open (AC-7)
    if relevance is False:     return {rel=False, isrel=None,  issup=None, retry=None, DISCARDED}
    if ct in SELF_RAG_RECALL_FLOOR_TYPES:                                                       # 027
                               return {rel=True,  isrel=None,  issup=None, retry=None, VALIDATED}
    if isrel is None:          return {rel=True,  isrel=None,  issup=None, retry=None, VALIDATED}  # fail-open
    if isrel is False:         return {rel=True,  isrel=False, issup=None, retry=None, DISCARDED}
    if issup is None:          return {rel=True,  isrel=True,  issup=None, retry=None, VALIDATED}  # fail-open
    if issup is True:          return {rel=True,  isrel=True,  issup=True, retry=0,    VALIDATED}
    return                            {rel=True,  isrel=True,  issup=False,retry=0,    DISCARDED}  # terminal (Q4)
    ```
    (`_validated_all_none()` = **add a small helper** returning the all-`None`-verdicts + `VALIDATED`
    dict; today that outcome is written as inline literals in `_branch_c_normal`/`_branch_a_rescue`, so
    introduce the helper and, optionally, refactor those existing literals to call it.) `retry_count`
    is `0` only on the two paths
    that reach ISSUP (matching the sequential `attempt-1`/`MAX_ATTEMPTS-1` at attempts=1) and `None`
    everywhere else — identical to the sequential path's field values.
- **Unchanged:** `_process_clause` routing (empty text → discard; empty evidence → Branch A floor
  single text-only ISSUP / Branch B zero-LLM discard). Lever C never routes an empty-evidence clause
  through the combined prompt (AC-10). `_branch_a_rescue` and `_issup_loop` are untouched.

### 3.4 `app/graph/nodes/splitters/llm_refiner.py` (Lever F — slim refinement, self-contained)
- Add module aliases `CLAUSE_SPLITTER_LLM_EMIT_TEXT = _config.CLAUSE_SPLITTER_LLM_EMIT_TEXT` and
  `CLAUSE_SPLITTER_LLM_NUM_PREDICT = _config.CLAUSE_SPLITTER_LLM_NUM_PREDICT`.
- **New prompt** `_GROUPING_PROMPT` — same numbered input segments as today (`index`, `section_number`,
  `text`) but asks the model to MERGE by referencing indices and CLASSIFY, returning **no text**:
  ```json
  {"clauses": [{"indices": [1, 2], "section_number": "1.2" or null, "clause_type": "..." or null}]}
  ```
  Rules in-prompt: every input index appears in exactly one output clause; preserve document order;
  do not invent indices; classify or use null. **No splitting** of a segment (Q1a) — the regex
  boundary is the finest unit.
- `_call_ollama` chooses prompt + `num_predict` by the flag:
  - `EMIT_TEXT=True` → existing `_LLM_PROMPT`, `num_predict=4096`, existing `_parse_response` (byte-for-
    byte pre-029 path, AC-16).
  - `EMIT_TEXT=False` → `_GROUPING_PROMPT`, `num_predict=CLAUSE_SPLITTER_LLM_NUM_PREDICT`, new
    `_parse_grouping_response(raw, regex_clauses)`.
- **New** `_parse_grouping_response(raw, regex_clauses) -> list[ClauseBoundary]` (raises on any
  violation so `refine_with_llm`'s except falls back to `regex_clauses` — AC-15):
  1. Parse JSON; require non-empty `clauses` list (as today).
  2. Collect the flattened, in-output-order list of `indices`. **Validate it is an exact ordered
     partition of `[1..N]`** (N = len(regex_clauses)): every input index used exactly once, ascending,
     no gaps/dupes/out-of-range. Any failure → raise → regex fallback. (This is the structural text-
     preservation guarantee — AC-12.)
  3. Build each output `ClauseBoundary`: `text = "\n".join(regex_clauses[i-1].text for i in indices)`;
     `section_number` = LLM value if a non-empty string else the first grouped segment's
     `section_number`; `clause_type` validated against `_VALID_CLAUSE_TYPES` (else `None`), as today;
     `clause_id`/`position` renumbered `1..M` sequentially.
  4. Keep the existing `output_chars >= input_chars * 0.5` guard as a cheap backstop (with an exact
     ordered-partition it always holds; harmless).
- `refine_with_llm` signature and its fallback-to-`regex_clauses` behavior are **unchanged**; only the
  internal prompt/parse path forks on the flag. `clause_splitter_agent.py` needs no edit.

### 3.5 What is NOT touched
CRAG (Node 3), RiskScore (Node 5), route_on_risk, Redline (Node 6), Report (Node 7); all existing
timeouts, prompt-max-char budgets, circuit-breaker thresholds, 028 temperature/seed, 027 recall-floor
type set. No `ContractState` field added/renamed.

---

## 4. Tests mapped to acceptance criteria (pytest, TDD §7)

### `test_self_rag_reflectors.py` (Lever C unit)
- **check_combined happy path (AC-1/2):** mock `ollama.Client.chat` to return
  `{"relevance":true,"isrel":true,"issup":true,...}`; assert the dict `{relevance:True,isrel:True,
  issup:True}` and that `chat` was called **once**.
- **whole-call failure → None (AC-6):** non-JSON content, and a raised exception / timeout → returns
  `None`.
- **per-key None (AC-7):** JSON missing `issup`, and a non-bool `relevance` (e.g. `"yes"`/`1`) → that
  key is `None` in the returned dict, others preserved.
- **num_predict (suggestion #3):** assert the chat `options["num_predict"] == SELF_RAG_MERGED_NUM_PREDICT`.

### `test_self_rag_validation_agent.py` (Lever C orchestration)
- **{T,F}³ verdict parity (AC-3):** parametrized over all 8 `(relevance,isrel,issup)` bool combos:
  with `SELF_RAG_MERGE_JUDGMENTS=True` and `check_combined` mocked to return that combo, assert the
  resulting `final_status` + `relevance_verdict`/`isrel_verdict`/`issup_verdict`/`retry_count` equal
  what the sequential path (`MERGE=False`, `check_relevance/isrel/issup` mocked to the same bools)
  produces for the same combo. (One test drives both paths and asserts equality — strongest guard.)
- **relevance False (AC-4):** merged `{relevance:False,isrel:True,issup:True}` → `DISCARDED`,
  `isrel_verdict=None`, `issup_verdict=None`.
- **recall-floor short-circuit (AC-5):** floor `clause_type` + merged `{relevance:True,isrel:False,
  issup:False}` → `VALIDATED`.
- **fail-open (AC-6):** `check_combined` → `None` → `VALIDATED`, all verdicts `None`.
- **partial None (AC-7):** merged `{relevance:True,isrel:True,issup:None}` → `VALIDATED` (fail-open at
  ISSUP); merged missing `relevance` → `VALIDATED`.
- **one call per clause (AC-2):** spy `check_combined` across a 3-clause doc → called 3×, and
  `check_relevance/isrel/issup` **not** called.
- **per-call accounting (AC-8):** `check_combined` → `None` for `SELF_RAG_LLM_CIRCUIT_BREAKER_THRESHOLD`
  consecutive clauses → breaker opens; remaining clauses fail-open; `error_count=1` emitted once. Also
  assert `check_relevance/isrel/issup` are **not** called on the merged failing path (breaker trips on
  merged-call events only).
- **empty-evidence untouched (AC-10):** empty-evidence floor clause still calls `check_issup` (text-
  only) once and not `check_combined`; empty-evidence non-floor still zero-LLM discard.
- **reversibility (AC-9):** with `SELF_RAG_MERGE_JUDGMENTS=False`, existing sequential tests pass
  unchanged (they mock `check_relevance/isrel/issup`; add the pin only where a test would otherwise
  pick up the new default — Step 1 surfaces these).

### `test_llm_refiner.py` (Lever F unit)
- **reassembly exactness (AC-11/12):** `EMIT_TEXT=False`; input 3 regex segments; mock chat →
  `{"clauses":[{"indices":[1,2],...},{"indices":[3],...}]}`; assert 2 output clauses, response carried
  **no text**, and the concatenation of output texts reconstructs the input exactly — build the
  assertion against the same `"\n"` join string the parser uses (`"\n".join(out.text)` ==
  `"\n".join(seg.text)`); ids/positions renumbered.
- **bad partition → fallback (AC-15):** duplicated index, missing index, out-of-range, and empty
  `clauses` each → `refine_with_llm` returns the original `regex_clauses` (never raises).
- **num_predict (AC-14):** grouping mode uses `CLAUSE_SPLITTER_LLM_NUM_PREDICT`; emit-text mode uses 4096.
- **clause_type (AC-13):** invalid type string → `None`; valid → the `ClauseType` value.
- **emit-text reversibility (AC-16):** with `EMIT_TEXT=True`, existing refiner tests pass unchanged.

### `test_clause_splitter_agent.py` (Lever F through the node)
- **end-to-end grouping (AC-11/12/17):** default flags, small doc (≤ `CLAUSE_SPLITTER_LLM_MAX_CLAUSES`
  so Lever-A gate inactive), mock the refiner's chat to a valid grouping → node returns clauses whose
  concatenated text preserves the input and whose `clause_type`s are set. Existing tests unaffected.

### `test_config.py` (AC-18)
- Assert `SELF_RAG_MERGE_JUDGMENTS is True`, `SELF_RAG_MERGED_NUM_PREDICT == 384`,
  `CLAUSE_SPLITTER_LLM_EMIT_TEXT is False`, `CLAUSE_SPLITTER_LLM_NUM_PREDICT == 1024`.

### Regression + measured (AC-19/20/21)
- **AC-19:** with `MERGE=False` + `EMIT_TEXT=True`, per-clause outputs identical to pre-029 (whole
  suite green on the reversible path).
- **AC-21:** `git diff --name-only main` shows only the files in §2 — no graph/edge/state/migration.
- **AC-20 (measured, not a unit assertion):** re-run `python -X utf8 scripts/latency_measure.py`
  (from `backend/`) on defaults; record `self_rag_validation` and `clause_splitter` node_timings vs the
  2026-07-28 baseline (self_rag ~42–47s, clause_splitter ~58–70s) in the tasks.md measurement note, and
  spot-check the 026 harness for no accuracy regression beyond noise.

---

## 5. Implementation order (TDD — §7)

1. **Config (red-enabling):** add the 4 constants. Run `pytest` — `test_config.py` new asserts fail
   (red) and any existing test that implicitly assumed the old prompt/path surfaces; note the exact set.
2. **Lever C unit:** write `check_combined` tests (red) → implement `_COMBINED_PROMPT` + `check_combined`
   + `_call_combined`/`_parse_combined` (green).
3. **Lever C orchestration:** write the `{T,F}³` parity + fail-open + floor + accounting + one-call
   tests (red) → branch `_branch_c_normal` on `SELF_RAG_MERGE_JUDGMENTS` (green). Confirm sequential
   tests still green with merge OFF; pin only tests that need the OFF path.
4. **Lever F unit:** write reassembly/partition/num_predict/clause_type tests (red) → add
   `_GROUPING_PROMPT` + emit-text branch + `_parse_grouping_response` to `llm_refiner.py` (green).
   Confirm emit-text=True path leaves existing refiner tests green.
5. **Lever F through node:** the end-to-end grouping test (green); confirm Lever-A gate interaction
   (AC-17) and existing splitter tests unaffected.
6. **Verify:** whole `pytest` green; `git diff --name-only main` shows only the §2 files.
7. **Live smoke + measure (AC-20):** real Ollama; `scripts/latency_measure.py` before/after on the two
   corpus docs; record node_timings deltas + a 026-harness accuracy spot-check in tasks.md.

Tests are written/observed failing first (§7). No existing assertion is weakened — the only edits to
existing tests are (a) pinning `SELF_RAG_MERGE_JUDGMENTS=False` where a sequential test must keep using
the sequential path, and (b) pinning `CLAUSE_SPLITTER_LLM_EMIT_TEXT=True` for the legacy refiner tests.

---

## 6. Notes / risks

- **Circuit-breaker accounting divergence (accepted, Q3):** merged path accounts **once per clause**
  (whole-call failure) whereas the sequential path could account up to 3× and treats a bad *sub-call*
  (e.g. isrel None) as a failure. So a parsed-object-with-one-bad-key is a non-event for the breaker on
  the merged path but a +1 on the sequential path. This is intrinsic to merging and is the exact
  semantics the user accepted (spec §6 Q3 / AC-8). Documented here so the implementer does not "fix" it
  to match the sequential count.
- **Lever F drops intra-segment splitting (accepted, Q1a):** the regex boundary is the finest unit; the
  LLM can only merge + classify. If a real contract needs a regex segment split, that split is not
  performed (regex boundary retained) — acceptable per spec; the exact ordered-partition guarantee makes
  text loss impossible (bad grouping → regex fallback, never corruption).
- **Monkeypatch the node-module / refiner-module aliases, not `_config`** — both modules bind the
  constants at import (`X = _config.X`); tests must set the module-local name for it to take effect.
- **Determinism (028) preserved:** both new calls pass `temperature=OLLAMA_TEMPERATURE` and (when set)
  `seed=OLLAMA_SEED`, and `think=False`, exactly like the existing calls.
- **num_predict sizing:** `SELF_RAG_MERGED_NUM_PREDICT=384` (vs 256 single-verdict) guards against JSON
  truncation of the 3-verdict object; `CLAUSE_SPLITTER_LLM_NUM_PREDICT=1024` is ample for index/type
  metadata (no text). Both are §3-tunable if a real doc shows truncation → regex/fail-open fallback.
- **Fully reversible:** set `SELF_RAG_MERGE_JUDGMENTS=False` and `CLAUSE_SPLITTER_LLM_EMIT_TEXT=True`
  to restore pre-029 behavior exactly (AC-9/16/19).
- **Accuracy watch:** merging three rubrics into one prompt could shift the verdict mix; AC-20 requires
  a 026-harness spot-check (precision/recall/false-flag, 027 recall behavior) before merge, mirroring
  025's measure-before-merge discipline.

---

*Per §1/§11, the `feature/029-pipeline-latency-round2` branch opens only after this plan.md + spec.md
are approved and `tasks.md` exists. No migration, no frontend. No `tasks.md`/implementation in this
pass — plan only.*
