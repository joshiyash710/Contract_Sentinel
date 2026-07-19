# Feature 027 — Technical plan: Self-RAG recall floor

Derived from `spec.md`. Implements a config-driven recall floor inside Node 4 (Self-RAG
validation). **No graph/edge/`ContractState`/migration change** (§2 of constitution).

## 0. Scope of change (files touched)

Per **AC-6** the `git diff` must touch only these:

1. `backend/app/config.py` — add `SELF_RAG_RECALL_FLOOR_TYPES` frozenset.
2. `backend/app/graph/nodes/self_rag_validation_agent.py` — module alias + three branch edits.
3. `backend/tests/unit/test_self_rag_validation_agent.py` — new AC-1..4 tests; pin existing
   floor-type-discard tests to an empty floor.
4. `backend/tests/unit/test_config.py` — type + valid-`ClauseType` subset assertion for the new set.

No other file changes. The 026 harness (`backend/eval/harness/`) is **run**, not modified (§2.3 note).

## 1. Config change (`app/config.py`)

Immediately after `SELF_RAG_HIGH_RISK_CLAUSE_TYPES` (currently `config.py:135-147`) add:

```python
SELF_RAG_RECALL_FLOOR_TYPES: frozenset = frozenset(
    {
        "liability",
        "termination",
        "intellectual_property",
        "dispute_resolution",
        "confidentiality",
    }
)
# ClauseType.value strings that get the Self-RAG "recall floor" (spec 027): once a
# clause of one of these types passes the light relevance gate, it is VALIDATED
# (surfaced as a finding for human review) even if ISSUP/ISREL would discard it, or
# if it had no evidence. Rationale: for a legal tool a missed risk (false negative)
# is far costlier than a false flag, and 026 measured 0% false-flags (headroom to
# spend). SUPERSEDES SELF_RAG_HIGH_RISK_CLAUSE_TYPES inside the node (which is a
# subset of this set); the old constant is kept for back-compat/config tests but is
# no longer read by the node. Empty set ⇒ byte-for-byte today's Self-RAG behavior
# (reversible, D6). The 026 harness measures the recall/precision trade (AC-7).
```

**Note (documentation only, no code):** `SELF_RAG_HIGH_RISK_CLAUSE_TYPES` stays defined but is
superseded; add a one-line comment on it pointing to `SELF_RAG_RECALL_FLOOR_TYPES` so a future
reader doesn't wire the node back to the old set. (Comment edit is inside the already-touched
`config.py`, so AC-6 holds.)

## 2. Node change (`self_rag_validation_agent.py`)

### 2a. Module-level alias (line ~50)
Next to `SELF_RAG_HIGH_RISK_CLAUSE_TYPES = _config.SELF_RAG_HIGH_RISK_CLAUSE_TYPES` add:

```python
SELF_RAG_RECALL_FLOOR_TYPES = _config.SELF_RAG_RECALL_FLOOR_TYPES
```

Read by **bare name** in node logic (never `_config.NAME`) so tests monkeypatch the node-module
attribute. Keep the old alias line (harmless; no longer read).

### 2b. Empty-evidence routing (`_process_clause`, line 163-164)
Change the empty-evidence branch condition:

```python
if empty_evidence:
    if ct in SELF_RAG_RECALL_FLOOR_TYPES:   # was SELF_RAG_HIGH_RISK_CLAUSE_TYPES
        return _branch_a_rescue(text, ct, cb)
    else:
        return _all_none_discard()          # Branch B zero-LLM discard (unchanged)
else:
    return _branch_c_normal(text, evidence, cb, ct)   # thread ct in (2d)
```

Because the default floor set ⊇ the old high-risk set, this preserves+extends Branch-A routing
(now also `confidentiality`). Rescues the `confidentiality` empty-evidence miss (§1 table).

### 2c. Branch A override (`_branch_a_rescue`)
`_branch_a_rescue` already takes `ct`. After `relevance is True` (currently falls through to
`_issup_loop` at line 209), for a recall-floor type return VALIDATED **without** entering the
ISSUP loop:

```python
# relevance True
if ct in SELF_RAG_RECALL_FLOOR_TYPES:
    return {
        "relevance_verdict": True,
        "isrel_verdict": None,
        "issup_verdict": None,
        "retry_count": None,
        "final_status": ValidationStatus.VALIDATED,
    }
# (non-floor empty-evidence types never reach _branch_a_rescue under the default set,
#  but keep the _issup_loop tail so an empty floor / narrowed set still works — D6)
issup_verdict, retry_count, final_status = _issup_loop(text, None, cb)
...
```

Rescues `confidentiality` and any empty-evidence floor type ISSUP would drop
(e.g. `intellectual_property` ISSUP-false — the known test breaker, AC-5).

### 2d. Branch C override (`_branch_c_normal`) — thread `ct` in
Current signature `(text, evidence, cb)` at line 219 lacks the clause type. Change to
`_branch_c_normal(text, evidence, cb, ct)` and pass `ct` from `_process_clause` (2b).

Insert the override **after `relevance is True` but before `check_isrel`** (i.e. after the
relevance-None/False handling around line 250, before the ISREL block at 262):

```python
# relevance True
if ct in SELF_RAG_RECALL_FLOOR_TYPES:
    return {
        "relevance_verdict": True,
        "isrel_verdict": None,
        "issup_verdict": None,
        "retry_count": None,
        "final_status": ValidationStatus.VALIDATED,
    }
# non-floor types: full ISREL → ISSUP gate (unchanged)
```

Rescues `liability`/indemnification ISSUP-false and `termination` ISREL-false misses; side
benefit: skips 1–2 LLM calls per floor clause with evidence.

### 2e. Unchanged (must stay exactly as-is)
- `relevance is False` → DISCARDED (both branches).
- `relevance is None` → VALIDATED fail-open (both branches).
- `cb["open"]` fail-open guards at the top of both branches and inside `_issup_loop`.
- Empty/whitespace text zero-LLM discard (`_process_clause` line 151, Edge Case 6).
- `_issup_loop`, `_account`, circuit breaker, `_clause_type_value`, `_all_none_discard`.
- Non-floor clause types: identical behavior.

### 2f. Record shape (§2.3)
Recall-floor validations carry `relevance_verdict=True, isrel_verdict=None, issup_verdict=None,
retry_count=None` — the **same shape as existing fail-open validations**, so RiskScore/redline/report
(which key off `final_status == VALIDATED`) are untouched, and the AC-16a invariant
`isrel_verdict is not False` holds.

## 3. Ordering / control-flow correctness

The override sits **after** the relevance gate in both branches, so:
- off-topic (`relevance False`) still wins → DISCARDED (EC-2),
- LLM failure (`relevance None`) still fail-opens → VALIDATED (EC-1),
- circuit-open fail-open guards run first → VALIDATED (EC-4),
- empty text discard runs before any branch (EC-5),
- `clause_type=None` is never in the set → no floor (EC-3, D5).

This is the whole safety argument: the floor only ever converts a would-be **ISREL/ISSUP/empty-
evidence discard** into a VALIDATE; it never overrides a relevance discard or an empty-text discard.

## 4. Test plan (TDD, `tests/unit/`)

Follow §7 (TDD failing-first). New tests use a **floor-type** `clause_type` (e.g.
`ClauseType.LIABILITY`) and mock the reflectors so ISSUP/ISREL *would* return False.

- **AC-1** `test_recall_floor_evidence_issup_false_validates`: evidence, relevance True, ISSUP mock
  returns False → VALIDATED; assert a non-floor type (`GENERAL`) in the same scenario → DISCARDED.
- **AC-2** `test_recall_floor_evidence_isrel_false_validates`: evidence, relevance True, ISREL mock
  returns False → VALIDATED; non-floor `GENERAL` → DISCARDED.
- **AC-3** `test_recall_floor_empty_evidence_validates`: empty evidence, floor type, relevance True →
  VALIDATED via Branch A rescue (ISSUP mock **not called**); non-floor empty evidence → zero-LLM
  discard (unchanged; relevance mock not called).
- **AC-3b** `test_recall_floor_confidentiality_empty_evidence_validates`: `CONFIDENTIALITY` (the type
  NOT in the old high-risk set) empty evidence + relevance True → VALIDATED (proves 2b routing fix).
- **AC-4** `test_recall_floor_relevance_false_discards` + `test_recall_floor_relevance_none_validates`:
  relevance False → DISCARDED; relevance None → VALIDATED (fail-open) — both on a floor type.
- **AC-4c** floor override skips extra LLM calls: assert `check_isrel`/`check_issup` **not called**
  for a Branch-C floor clause once relevance passes (documents the side-benefit + locks the path).
- **AC-5 reversibility** `test_recall_floor_empty_set_restores_old_behavior`: monkeypatch
  `node_mod.SELF_RAG_RECALL_FLOOR_TYPES = frozenset()`; a floor-type clause with evidence + ISSUP
  False → DISCARDED (old behavior restored).
- **Pin existing breakers:** after the config change, run the suite; every test that asserts a
  *floor-type* clause is DISCARDED via ISREL/ISSUP/empty-evidence must be pinned by monkeypatching
  `node_mod.SELF_RAG_RECALL_FLOOR_TYPES = frozenset()` (never weakened). Known:
  `test_empty_evidence_high_risk_issup_false_discards` (INTELLECTUAL_PROPERTY, ISSUP-false).
  Candidates to check: `test_isrel_fail_discards_short_circuit`, `test_issup_exhaustion_discarded`,
  `test_only_issup_retries`, `test_no_isrel_false_with_validated` — pin only those that use a
  floor-type `clause_type` AND assert a discard/ISSUP-false-driven path.
- **Config** `test_config.py`: add `test_self_rag_recall_floor_types_are_valid_clause_types`
  mirroring `test_self_rag_high_risk_types_are_valid_clause_types` (subset of `ClauseType` values),
  and a `frozenset`/`all(str)` type assertion in the existing self-rag config-types test.

## 5. Measurement (AC-7)

After backend green, re-run the 026 harness from `backend/` before vs. after (delivery off via
`app.delivery.delivery_step.MCP_DELIVERY_ENABLED=False`, per 026 notes):
`python -m eval.harness.run` then `python -m eval.harness.score` (confirm exact entry points from
`eval/harness/run.py` / `score.py` in tasks). Record recall, miss, precision, false-flag, severity
accuracy before/after; expected: the four measured misses become caught (recall ↑) and the mis-typed
governing-law clause becomes a false-flag (false-flag ↑ from 0%). Report both — a measured trade (D3).

## 6. Risks / limitations
- **D5 limitation:** large 025-gated docs (regex-only, `clause_type=None`) get no floor — documented,
  not fixed here.
- **D3 precision cost:** `dispute_resolution` in the default set false-flags mis-typed governing-law;
  narrowing the set is a documented option, remedy is better clause typing (out of scope, §6).
- Live harness needs Ollama up (qwen3) — same constraint as 026.
