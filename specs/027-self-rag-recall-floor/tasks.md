# Feature 027 — Tasks: Self-RAG recall floor

TDD order (§7): write/adjust failing tests → implement → green → measure. Each task lists its
acceptance link. Files limited to the four in plan §0 (AC-6).

---

## T1 — Config: add `SELF_RAG_RECALL_FLOOR_TYPES` (§2.1, D2, D6)
- [ ] In `app/config.py`, after `SELF_RAG_HIGH_RISK_CLAUSE_TYPES`, add
      `SELF_RAG_RECALL_FLOOR_TYPES` = frozenset of the 5 values (liability, termination,
      intellectual_property, dispute_resolution, confidentiality) with the doc-comment (plan §1).
- [ ] Add a one-line "superseded by SELF_RAG_RECALL_FLOOR_TYPES" note on the old high-risk comment.
- **AC:** AC-5 (config), AC-6.

## T2 — Config test (TDD-first) (AC-5)
- [ ] In `tests/unit/test_config.py` add `test_self_rag_recall_floor_types_are_valid_clause_types`
      (subset of `{ct.value for ct in ClauseType}`), mirroring the high-risk test at line 147.
- [ ] Add `frozenset` + `all(isinstance(t, str))` assertions for the new set (extend existing
      self-rag config-types test or a new one).
- [ ] Run → passes once T1 is in (config-only, no node dependency).
- **AC:** AC-5.

## T3 — Node: module alias (plan §2a)
- [ ] In `self_rag_validation_agent.py` (~line 50) add
      `SELF_RAG_RECALL_FLOOR_TYPES = _config.SELF_RAG_RECALL_FLOOR_TYPES` (bare-name read).
- **AC:** enables monkeypatching for AC-1..5.

## T4 — Failing tests first: AC-1..4 recall-floor behavior (§7 TDD)
Add to `tests/unit/test_self_rag_validation_agent.py` (all mock reflectors at node module level):
- [ ] **AC-1** `test_recall_floor_evidence_issup_false_validates` (+ non-floor `GENERAL` discards).
- [ ] **AC-2** `test_recall_floor_evidence_isrel_false_validates` (+ non-floor discards).
- [ ] **AC-3** `test_recall_floor_empty_evidence_validates` (Branch A; ISSUP not called) +
      **AC-3b** `test_recall_floor_confidentiality_empty_evidence_validates`.
- [ ] **AC-4** `test_recall_floor_relevance_false_discards` +
      `test_recall_floor_relevance_none_validates`.
- [ ] **AC-4c** floor Branch-C skips `check_isrel`/`check_issup` after relevance True (asserts
      not-called).
- [ ] Run → these FAIL against current node (no floor yet). Confirm red.
- **AC:** AC-1, AC-2, AC-3, AC-4.

## T5 — Node: implement recall floor (plan §2b–2f)
- [ ] `_process_clause`: empty-evidence condition `ct in SELF_RAG_RECALL_FLOOR_TYPES`; pass `ct`
      into `_branch_c_normal`.
- [ ] `_branch_a_rescue`: for floor `ct`, after `relevance True` return VALIDATED without
      `_issup_loop`; keep the `_issup_loop` tail for empty/narrowed set (D6).
- [ ] `_branch_c_normal(text, evidence, cb, ct)`: after `relevance True`, before `check_isrel`,
      return VALIDATED for floor `ct`.
- [ ] Leave all relevance-False/None, circuit-breaker, empty-text, `_issup_loop`, `_account` paths
      untouched (plan §2e).
- [ ] Run T4 → green.
- **AC:** AC-1, AC-2, AC-3, AC-4.

## T6 — Reversibility test + pin existing breakers (AC-5, §7)
- [ ] Add `test_recall_floor_empty_set_restores_old_behavior` (monkeypatch node set to
      `frozenset()`; floor-type + evidence + ISSUP False → DISCARDED).
- [ ] Run full `tests/unit/test_self_rag_validation_agent.py`; for EVERY newly-failing test that
      asserts a *floor-type* clause DISCARDS (ISREL/ISSUP/empty-evidence), pin it by monkeypatching
      `node_mod.SELF_RAG_RECALL_FLOOR_TYPES = frozenset()` — do NOT weaken assertions. Known:
      `test_empty_evidence_high_risk_issup_false_discards`. Check candidates listed in plan §4.
- **AC:** AC-5.

## T7 — Full backend suite green (AC-6)
- [ ] `python -m pytest` (from `backend/`) — whole suite green.
- [ ] `git diff --name-only` shows only: `app/config.py`,
      `app/graph/nodes/self_rag_validation_agent.py`,
      `tests/unit/test_self_rag_validation_agent.py`, `tests/unit/test_config.py`.
- **AC:** AC-6.

## T8 — Live harness measurement, before vs. after (AC-7)
- [ ] Confirm exact run/score entry points in `eval/harness/run.py` + `score.py`.
- [ ] With Ollama up and delivery disabled (`MCP_DELIVERY_ENABLED=False`), capture baseline metrics
      on the current default set, then (recall floor is already on by default) capture post metrics
      by comparing against the 026 recorded baseline (recall 63.6%, precision 100%, false-flag 0%).
      If a clean A/B is needed, run once with `SELF_RAG_RECALL_FLOOR_TYPES` empty (env/monkeypatch)
      vs. default.
- [ ] Record recall, miss, precision, false-flag, severity accuracy for both; note the four rescued
      misses and any new governing-law false-flag (D3).
- **AC:** AC-7.

## T9 — Wrap up
- [ ] Update spec/plan/tasks if the harness numbers suggest narrowing the default set (D2/D3 knob).
- [ ] Commit on `feature/027-self-rag-recall-floor`; summarize the measured recall/precision trade.
- [ ] Update memory (feature 027 status).

---

### Notes
- No graph/edge/`ContractState`/migration change (AC-6). Delivery stays off for harness (026 note).
- Runtime generative model: qwen3 via Ollama (harness only; unit tests mock all LLM calls).
