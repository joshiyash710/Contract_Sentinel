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

## T8 — Live harness measurement, before vs. after (AC-7) ✅
- [x] Confirm exact run/score entry points (`python -m eval.harness.run` / `... score <run_dir>`).
- [x] Clean A/B on the current gold: BEFORE = checkout `main`'s config+node, run; AFTER = 027 branch
      (default floor). (Empty-floor monkeypatch does NOT reproduce true pre-027 because §2.1
      consolidated the empty-evidence routing onto the same set — so the true BEFORE is main's code.)
- [x] Recorded recall/miss/precision/false-flag/severity + seen-but-discarded for both. See
      "Measured result" table below.
- **AC:** AC-7. ✅

## T9 — Wrap up
- [ ] Update spec/plan/tasks if the harness numbers suggest narrowing the default set (D2/D3 knob).
- [x] Commit on `feature/027-self-rag-recall-floor`; summarize the measured recall/precision trade.
- [x] Update memory (feature 027 status).

---

## Measured result (AC-7) — clean same-corpus A/B, qwen3:8b, seed gold (11 risky + 3 clean)

BEFORE = pre-027 `main` source; AFTER = 027 default recall floor. Same gold, same box/model.

| metric | BEFORE (main) | AFTER (027) | delta |
| --- | --- | --- | --- |
| recall | 45.5% (tp=5, fn=6) | **100%** (tp=11, fn=0) | **+54.5pp** |
| miss rate | 54.5% | **0%** | −54.5pp |
| precision | 100% | 84.6% | −15.4pp |
| false-flag rate | 0% (fp=0) | 66.7% (fp_clean=2) | +66.7pp |
| F1 | 62.5% | **91.7%** | +29.2pp |
| severity exact | 20% | 45.5% | +25.5pp |
| Self-RAG seen-but-discarded misses | 6 | **0** | −6 |

**Read:** the recall floor rescued **all 6** "seen-but-discarded" misses (recall 45.5%→100%,
seen-but-discarded 6→0) at the cost of **2** false flags on 3 clean-labeled clauses (D3's expected
precision cost — the mis-typed governing-law→`dispute_resolution` case). Net F1 +29pp. The trade is
measured, not assumed. Knob to narrow (e.g. drop `dispute_resolution`) is documented (D2/D3).
Note: BEFORE recall (45.5%) differs from the 026 memory note (63.6%) because the gold corpus grew
since 026; this A/B is on the current gold under identical conditions.

Harness note: run.py's `✓` progress print crashes on Windows cp1252 stdout — run with
`PYTHONIOENCODING=utf-8` / `python -X utf8`. Pre-existing harness bug, out of 027's file scope.

---

### Notes
- No graph/edge/`ContractState`/migration change (AC-6). Delivery stays off for harness (026 note).
- Runtime generative model: qwen3 via Ollama (harness only; unit tests mock all LLM calls).
