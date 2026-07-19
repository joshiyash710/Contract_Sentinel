# Feature 027 — Self-RAG recall floor for high-risk clause types

## 1. Problem statement

The evaluation harness (026) measured ContractSentinel on a seed corpus and found the system is
**precise but under-sensitive**: **100% precision / 0% false-flags, but only ~64% recall (36% of
genuinely risky clauses missed)**. The harness's per-clause verdict sidecar localized the cause
exactly — **every miss is Self-RAG discarding a genuinely risky clause it already analyzed**
("seen-but-discarded", 0 "never-split"):

| Missed clause | pipeline `clause_type` | relevance | ISREL | ISSUP | discard point |
| --- | --- | --- | --- | --- | --- |
| indemnification (×2) | `liability` | ✓ | ✓ | **✗** | ISSUP-false (Branch C) |
| termination | `termination` | ✓ | **✗** | — | ISREL-false (Branch C) |
| confidentiality | `confidentiality` | None | None | None | zero-LLM discard (Branch B) |

The harness also **disproved the obvious fix**: raising `SELF_RAG_MAX_ATTEMPTS` (which 025 cut 3→1)
would not help — retries only re-run ISSUP on an ISSUP-*false* verdict, re-asking the identical
prompt, and a near-deterministic local model returns the same "no." The real cause is that Self-RAG's
discard gates (ISSUP, ISREL, and the no-evidence/type rescue) are too aggressive for **known-dangerous
clause types**.

This feature adds a **recall floor**: for a configurable set of high-risk `clause_type`s, once a
clause is confirmed on-topic (relevance passed), it is **flagged for human review even if ISSUP/ISREL
would discard it, or if it had no evidence.** For a legal tool a **false negative (missed risk) is far
more dangerous than a false positive**, and precision has large headroom (0% false-flags today) to
spend. The change is config-driven and reversible, and **its recall gain vs. precision cost is
measured by the 026 harness** (the first data-driven tuning loop).

### Position relative to the constitution

**No graph/edge change, no `ContractState` change, no migration.** This tunes the *internal decision
logic* of the existing Self-RAG node (Node 4) — the 7-node graph and 2 conditional edges are
untouched (§2). The recall-floor clause-type set is a **named config constant** (§3), reversible to
today's behavior with an empty set. Per §7 the new branch logic is TDD-unit-tested; per §1/§11 it is
developed on `feature/027-self-rag-recall-floor` and its effect is re-measured with the 026 harness.

## 2. Inputs and outputs

### 2.1 New config (§3)
- `SELF_RAG_RECALL_FLOOR_TYPES: frozenset` — clause types that get the recall floor. **Default:**
  `{"liability", "termination", "intellectual_property", "dispute_resolution", "confidentiality"}`
  — the members of `SELF_RAG_HIGH_RISK_CLAUSE_TYPES` **plus `confidentiality`**. All five are valid
  `ClauseType` values (state.py). Empty set ⇒ exactly today's behavior (reversible).
- **Consolidation:** `SELF_RAG_RECALL_FLOOR_TYPES` **supersedes** `SELF_RAG_HIGH_RISK_CLAUSE_TYPES`
  inside the node — the node reads only the recall-floor set (for BOTH the empty-evidence routing at
  `self_rag_validation_agent.py:164` and the discard-override). Because the default recall-floor set
  is a superset of the old high-risk set, the empty-evidence Branch-A routing is preserved and
  extended (now also covers `confidentiality`). `SELF_RAG_HIGH_RISK_CLAUSE_TYPES` remains defined in
  `config.py` (kept for its own config test / back-compat) but is **no longer read by the node**;
  the plan notes it as superseded to avoid two competing frozensets governing the same node.

### 2.2 Behavior change in Self-RAG (`self_rag_validation_agent.py`)
For a clause whose `clause_type` ∈ `SELF_RAG_RECALL_FLOOR_TYPES`:
- **Empty-evidence routing (fix vs. today):** change the `_process_clause` empty-evidence condition
  (`self_rag_validation_agent.py:164`) from `ct in SELF_RAG_HIGH_RISK_CLAUSE_TYPES` to `ct in
  SELF_RAG_RECALL_FLOOR_TYPES`, so a recall-floor type with no evidence takes the **Branch A rescue**
  (which runs relevance) instead of the Branch B **zero-LLM discard**. Without this change the
  `confidentiality` miss (which is not in the old high-risk set) would NOT be rescued.
- **Discard-gate override — branch-precise:**
  - **Branch A** (`_branch_a_rescue`, empty evidence) has no ISREL; its only post-relevance gate is
    the text-only `_issup_loop` (`self_rag_validation_agent.py:209`). For a recall-floor type, once
    `relevance == True`, **return `VALIDATED` WITHOUT entering `_issup_loop`** (`isrel_verdict=None`,
    `issup_verdict=None`, `retry_count=None`). (Rescues `confidentiality`, and any empty-evidence
    floor type that ISSUP would have dropped — e.g. today's `intellectual_property` ISSUP-false case.)
  - **Branch C** (`_branch_c_normal`, evidence present): for a recall-floor type, once `relevance ==
    True`, **skip both the ISREL check and the ISSUP loop and return `VALIDATED`** (`isrel_verdict=
    None`, `issup_verdict=None`, `retry_count=None`). (Rescues the `liability`/indemnification
    ISSUP-false and `termination` ISREL-false misses; side benefit: skips 1–2 LLM calls per such
    clause.)
- **Unchanged safety gates:** `relevance == False` still **DISCARDS** (respects a genuine off-topic
  signal); `relevance == None` still **fail-opens to VALIDATED** (unchanged); the circuit-breaker
  fail-open paths and the empty-/whitespace-text zero-LLM discard (Edge Case 6) are unchanged;
  **non-recall-floor clause types are completely unchanged.**

### 2.3 Output
No new state field or boundary-model field. The only observable change is that more high-risk clauses
reach `final_status = VALIDATED` and therefore appear as findings in the 009 report (and flow to
risk-scoring/redline as usual). The recall-floor validations carry `relevance_verdict = True,
isrel_verdict = None, issup_verdict = None, retry_count = None` — the **same record shape as the
existing fail-open validations** (e.g. Branch C relevance-None), so no downstream consumer breaks
(RiskScore keys off `final_status == VALIDATED`, not the sub-verdicts; the AC-16a invariant
`isrel_verdict is not False` still holds). **026 harness note:** a rescued clause becomes a *finding*
(caught), so it leaves the harness's FN/miss set entirely — the "seen-but-discarded" miss diagnostic
is computed only over remaining misses and is not affected. (No harness code change is needed; this
is just a note that recall-floor validations are not discards.)

## 3. Resolved decisions (inline)

- **D1 — Recall floor keyed on `clause_type`, gated by relevance.** Relevance stays a light gate
  (drops off-topic garbage); ISREL/ISSUP lose their *discard* power for recall-floor types. Rationale:
  the misses were all ISREL/ISSUP/no-evidence discards on on-topic high-risk clauses (§1 table).
- **D2 — Default set = existing high-risk set + `confidentiality`.** This rescues all four measured
  misses (indemnification→`liability`, termination→`termination`, confidentiality→`confidentiality`).
  The set is the one tuning knob; the harness measures the effect and it can be widened/narrowed.
- **D3 — Accept + MEASURE the precision cost; don't pretend it's free.** The harness revealed the
  pipeline mis-types "Governing Law" as `dispute_resolution`; because `dispute_resolution` is in the
  default set, that *clean* clause will now be **false-flagged**. This is the expected precision cost
  of trading toward recall, and the 026 harness quantifies it (false-flag rate will rise from 0%).
  The real remedy for that specific case is better clause typing — a **separate** concern (§6), not
  this feature. Narrowing the default (e.g. dropping `dispute_resolution`) is a documented option.
- **D4 — Not a retry change.** `SELF_RAG_MAX_ATTEMPTS` stays at 1 (025) — the harness showed retries
  don't recover recall. This feature does not touch it.
- **D5 — Depends on `clause_type` being inferred.** Large documents whose clause typing is gated off
  by 025 (regex-only, `clause_type = None`) get **no** recall floor — a documented limitation (the
  floor helps normal/typed contracts). Tie-in: [[feature-025-paused]].
- **D6 — Config §3, reversible.** Empty `SELF_RAG_RECALL_FLOOR_TYPES` ⇒ byte-for-byte today's Self-RAG
  behavior.

## 4. Acceptance criteria

### Backend (pytest)
- **AC-1:** A recall-floor clause type with evidence, `relevance=True`, and an ISSUP that would return
  **False** → `final_status = VALIDATED` (not discarded); `check_issup` is **not** relied on to
  validate (it may be skipped). A non-recall-floor type in the same scenario → **DISCARDED** (today's
  behavior, unchanged).
- **AC-2:** A recall-floor clause type with evidence, `relevance=True`, and an ISREL that would return
  **False** → `VALIDATED` (not discarded). Non-recall-floor type → **DISCARDED**.
- **AC-3:** A recall-floor clause type with **empty evidence** → routed to the Branch-A rescue (runs
  relevance); with `relevance=True` → `VALIDATED`. A non-recall-floor type with empty evidence still
  hits the Branch-B **zero-LLM discard** (unchanged).
- **AC-4:** `relevance == False` on a recall-floor type → still **DISCARDED**; `relevance == None` →
  still **VALIDATED** (fail-open). Circuit-breaker fail-open paths unchanged.
- **AC-5 (reversibility):** With the node's `SELF_RAG_RECALL_FLOOR_TYPES` monkeypatched to
  `frozenset()`, Self-RAG behaves **exactly as before** (relevance→ISREL→ISSUP discards restored).
  The **shipped default is non-empty** (the D2 set), so existing tests that assert a *floor-type*
  clause is discarded run under the new default and **will break unless pinned** — per §7 they are
  updated to pin the floor set empty (or use a non-floor `clause_type`), never weakened. Known
  breaker to pin: `test_empty_evidence_high_risk_issup_false_discards`
  (`ClauseType.INTELLECTUAL_PROPERTY`, ISSUP-false → asserts DISCARDED — must now VALIDATE under the
  floor); the exact full set is surfaced by running the suite after the config change (like 025's
  step 1). A `test_config` assertion is added that `SELF_RAG_RECALL_FLOOR_TYPES` is a `frozenset` of
  valid `ClauseType` values (mirroring the existing high-risk-set subset check).
- **AC-6:** No graph/edge/`ContractState` change (`git diff` shows only `app/config.py`, the Self-RAG
  node, and Self-RAG/config tests); whole `pytest` green.

### Live measurement (harness — AC-7)
- **AC-7:** Re-run the 026 harness (`run` + `score`) on the seed corpus before vs. after. **Recall
  rises** (target: the four measured misses become caught) and the **precision/false-flag cost is
  reported** (expected: the mis-typed governing-law clause becomes a false-flag). Record both numbers
  — the point is a *measured* trade, not an assumed one.

## 5. Edge cases
- **EC-1 — Recall-floor type, `relevance=None` (LLM failure)** → VALIDATED via the existing fail-open
  (unchanged); not a special case.
- **EC-2 — Recall-floor type, `relevance=False`** → DISCARDED (off-topic wins over the floor).
- **EC-3 — `clause_type=None`** (e.g. 025-gated large docs) → never in the set → no floor (D5).
- **EC-4 — Circuit breaker open** → existing fail-open (VALIDATED) paths win before the floor logic is
  reached; unchanged.
- **EC-5 — Empty/whitespace clause text** → the pre-existing zero-LLM discard (Edge Case 6) still wins
  (no text to assess); the floor does not resurrect empty clauses.

## 6. Out of scope
- **Fixing clause-type mis-inference** (e.g. Governing Law → `dispute_resolution`) — a separate
  clause-typing improvement; this feature only *reveals* it via the measured false-flag (D3).
- **Prompt-tuning ISSUP/ISREL** — the user chose the recall-floor approach over prompt changes; not
  done here.
- **Re-raising `SELF_RAG_MAX_ATTEMPTS`** (D4) and **any graph/`ContractState`/migration change** — none.
- **Growing the gold corpus / lawyer review** — belongs to 026's data effort.

## 7. Evaluation (metrics to log)
This feature is validated by the **026 harness** before/after: **recall, miss rate, precision,
false-flag rate, severity accuracy**, and the Self-RAG **discard-contribution-to-misses** diagnostic
(expected: seen-but-discarded count drops toward 0 for recall-floor types). The honest framing stands
— the seed corpus is indicative, not authoritative; the harness shows the *direction and rough
magnitude* of the recall/precision trade, to be re-measured on a larger expert-labeled corpus.

## 8. Notes for plan.md / tasks.md (pointers)
- **Config:** add `SELF_RAG_RECALL_FLOOR_TYPES` (default per D2) near `SELF_RAG_HIGH_RISK_CLAUSE_TYPES`
  in `app/config.py`. In `self_rag_validation_agent.py` add the module-level alias next to the
  existing one (`self_rag_validation_agent.py:50` has `SELF_RAG_HIGH_RISK_CLAUSE_TYPES =
  _config.…`): `SELF_RAG_RECALL_FLOOR_TYPES = _config.SELF_RAG_RECALL_FLOOR_TYPES` (read by bare name
  so tests monkeypatch the node-module attr).
- **Node:** in `self_rag_validation_agent.py` — (a) `_process_clause` line 164: change the
  empty-evidence condition to `ct in SELF_RAG_RECALL_FLOOR_TYPES` (supersedes the high-risk set, §2.1);
  (b) `_branch_a_rescue`: for a recall-floor `ct`, after `relevance == True` return `VALIDATED`
  WITHOUT calling `_issup_loop`; (c) `_branch_c_normal`: **thread `clause_type` in** (its current
  signature `(text, evidence, cb)` at `self_rag_validation_agent.py:219` lacks it — pass `ct` from
  `_process_clause` line 161/170), and for a recall-floor `ct`, after `relevance == True` return
  `VALIDATED` WITHOUT running `check_isrel` or `_issup_loop`.
- **Tests:** extend `tests/unit/test_self_rag_validation_agent.py` for AC-1..4 (recall-floor validate
  on ISSUP-would-fail / ISREL-would-fail / empty-evidence; non-floor type still discards;
  relevance-false→discard; relevance-none→validate); **pin** existing floor-type-discard tests
  (at minimum `test_empty_evidence_high_risk_issup_false_discards`; find the rest by running the
  suite after the config change) by monkeypatching `SELF_RAG_RECALL_FLOOR_TYPES` empty — not
  weakened (§7). Add a `test_config` subset assertion for `SELF_RAG_RECALL_FLOOR_TYPES` mirroring
  `test_self_rag_high_risk_types_are_valid_clause_types` (test_config.py:147-153). TDD failing-first.
- **Measurement:** re-run the 026 harness for AC-7 (`run` + `score`) before/after; report recall &
  false-flag deltas.
