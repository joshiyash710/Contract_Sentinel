# Feature 042 — Deterministic clause-type fallback — Implementation Tasks

Reference documents:
- Spec: `specs/042-deterministic-clause-typing/spec.md`
- Plan: `specs/042-deterministic-clause-typing/plan.md`
- Constitution: `specs/000-constitution.md` (**§1/§11** branch-gated implementation; **§2** no graph
  node/edge change, no `ContractState` change, no migration; **§3** config constants; **§7** TDD +
  never weaken a test to pass)

Backend paths relative to `backend/`.

**Workflow reminders:**
- **TDD (§7):** every unit test is written FAILING first, then the implementation makes it green. Do
  not weaken a surprised existing test to pass — pin it the way 027 did and justify.
- **Scope is exactly six files (AC-5).** `git diff main` must touch only: `app/config.py`,
  `app/graph/nodes/splitters/clause_typer.py` (NEW), `app/graph/nodes/clause_splitter_agent.py`,
  `tests/unit/test_clause_typer.py` (NEW), `tests/unit/test_clause_splitter_agent.py`,
  `tests/unit/test_config.py` (+ the `specs/042-**` docs). **No** graph/edge/`ContractState`/
  migration/Self-RAG-node/frontend change. The 041/026 harness (`eval/harness/`) is **run**, not
  modified (AC-7).
- **Fill-`None`-only (D4).** The tagger never overwrites an LLM-assigned `clause_type`; it only fills
  clauses left `None`. The `converted_type is None` guard in `_build_return` enforces this.
- **Conservative map (D2/D3).** The default `DETERMINISTIC_CLAUSE_TYPE_PATTERNS` covers ONLY the four
  recall-floor types (`{liability, termination, intellectual_property, confidentiality}` =
  `SELF_RAG_RECALL_FLOOR_TYPES`). NO bare single words (`patent`/`copyright`/`trademark`) and NO
  generic fragments (`assignment of`/`ownership of the`) — a floor-typed clause is VALIDATED even if
  ISSUP would discard, so over-matching = false flags.
- **Reversibility (D5).** `DETERMINISTIC_CLAUSE_TYPING_ENABLED = False` (or an empty map) ⇒
  byte-for-byte today's `clause_type` behavior.
- **Monkeypatch pattern.** `clause_typer.py` and `clause_splitter_agent.py` read the flag/map by
  **bare module-level name** (re-exposed from `app.config`, mirroring the existing
  `MAX_CLAUSES_LIMIT` block) so tests can monkeypatch.
- **All backend tests are OFFLINE** (no Ollama) — the tagger is a pure function. Only AC-7 (Task 6)
  needs live Ollama.

---

## Task 0: Branch (already done — confirm)
- [x] On `feature/042-deterministic-clause-typing` (tree clean); `spec.md` (`b1c601a8`) + `plan.md`
  (`53f3409c`) committed and spec-reviewer-APPROVED. This task commits `tasks.md` after its own
  reviewer gate passes.

**Verify:** `git branch --show-current` → `feature/042-deterministic-clause-typing`.

---

## Task 1: Config constants (§3)  [AC-4]
- [ ] **[MODIFY] `app/config.py`** — near the ClauseSplitter constants (after
  `CLAUSE_SPLITTER_LLM_MAX_CLAUSES`, ~line 105) add, exactly as designed in plan §1:
  - `DETERMINISTIC_CLAUSE_TYPING_ENABLED: bool = True` — master switch (feature 042); `False` ⇒
    byte-for-byte today's behavior (D5). Comment explains it revives the 027 floor on large docs with
    no LLM dependence.
  - `DETERMINISTIC_CLAUSE_TYPE_PATTERNS: tuple` — the ORDERED tuple-of-`(clause_type_value, phrases)`
    from plan §1 (confidentiality → liability → intellectual_property → termination). Conservative
    multi-word legal phrases only; the ordering is the multi-match tie-break (EC-1). Keep the plan's
    inline comment documenting why no bare single words / generic fragments, and that the four keys
    are exactly `SELF_RAG_RECALL_FLOOR_TYPES`.

**Verify:** `python -c "import app.config as c; print(c.DETERMINISTIC_CLAUSE_TYPING_ENABLED, len(c.DETERMINISTIC_CLAUSE_TYPE_PATTERNS))"`
from `backend/` → `True 4`.

---

## Task 2: Config validity test (red → green)  [AC-4]
- [ ] **[MODIFY] `tests/unit/test_config.py`** (confirm FAILING first): add a test mirroring the
  existing `test_self_rag_recall_floor_types_are_valid_clause_types` that asserts:
  - `DETERMINISTIC_CLAUSE_TYPING_ENABLED` is a `bool`.
  - Every key in `DETERMINISTIC_CLAUSE_TYPE_PATTERNS` is a valid `ClauseType.value` (guards typos /
    enum drift).
  - The set of keys is a **subset of `SELF_RAG_RECALL_FLOOR_TYPES`** (guards a floor-irrelevant key —
    typing a non-floor type has no floor effect, D2).
  - Each phrase group is a non-empty tuple/list of lowercase `str` (guards a stray upper-case phrase
    that could never match the lowercased clause text).
- [ ] Task 1 makes this green.

**Verify:** `python -m pytest tests/unit/test_config.py -q` → PASS.

---

## Task 3: Deterministic tagger — test (red) → implementation (green)  [AC-1, AC-2, AC-6]
- [ ] **[NEW] `tests/unit/test_clause_typer.py`** (confirm FAILING — module does not exist yet):
  - **AC-1 positives:** `infer_clause_type` returns `ClauseType.LIABILITY` for a
    limitation-of-liability / indemnification snippet; `ClauseType.TERMINATION` for a
    termination/survival snippet; `ClauseType.INTELLECTUAL_PROPERTY` for an IP-assignment/ownership
    snippet; `ClauseType.CONFIDENTIALITY` for an NDA snippet.
  - **AC-1 negatives (lock in the conservative map):** neutral boilerplate (notices/definitions) →
    `None`; a definitions/representation clause that merely mentions `patent`/`copyright`/`trademark`
    in passing → `None` (NOT `intellectual_property`); an anti-assignment clause ("no assignment of
    this Agreement without consent") → `None` (NOT `intellectual_property`).
  - **AC-2 / EC-1:** a clause containing both confidentiality and liability language resolves to the
    fixed map order (confidentiality precedes liability in the default map). **EC-2:** empty / `None` /
    whitespace text → `None`.
  - **AC-6 determinism:** repeated calls on the same input are identical; monkeypatching
    `clause_typer.DETERMINISTIC_CLAUSE_TYPE_PATTERNS` to a different map changes the result
    deterministically (proves it reads the module attr, no hidden state/RNG/I/O).
- [ ] **[NEW] `app/graph/nodes/splitters/clause_typer.py`** — implement the pure
  `infer_clause_type(text: Optional[str]) -> Optional[ClauseType]` from plan §2: guard empty text
  (EC-2), lowercase once, scan the ordered map, first type whose any-phrase is a substring wins, wrap
  `ClauseType(value)` in try/except (defensive skip of a bad key). Re-expose
  `DETERMINISTIC_CLAUSE_TYPING_ENABLED` / `DETERMINISTIC_CLAUSE_TYPE_PATTERNS` as bare module names
  from `app.config` for monkeypatching.

**Verify:** `python -m pytest tests/unit/test_clause_typer.py -q` → PASS.

---

## Task 4: Wire-in to ClauseSplitter — test (red) → implementation (green)  [AC-3, AC-4]
- [ ] **[MODIFY] `tests/unit/test_clause_splitter_agent.py`** (confirm the new cases FAIL first):
  - **AC-3 fill:** drive `_build_return` with a regex-only `ClauseBoundary` list (all
    `clause_type=None`) where one clause carries clear liability language → its output
    `clause_type == ClauseType.LIABILITY`; an all-neutral set stays all-`None`.
  - **AC-3 precedence / AC-2 at integration:** a `ClauseBoundary` already carrying a (string)
    `clause_type` the LLM assigned is **not** overwritten by the tagger, while a sibling `None` clause
    with floor language IS filled.
  - **AC-4 reversibility:** monkeypatch
    `clause_splitter_agent.DETERMINISTIC_CLAUSE_TYPING_ENABLED = False` → previously-`None` clauses
    stay `None` (output identical to today).
- [ ] **[MODIFY] `app/graph/nodes/clause_splitter_agent.py`** per plan §3:
  - Add imports/aliases next to the existing re-exposed constants:
    `from app.graph.nodes.splitters.clause_typer import infer_clause_type` and
    `DETERMINISTIC_CLAUSE_TYPING_ENABLED = _config.DETERMINISTIC_CLAUSE_TYPING_ENABLED`.
  - In `_build_return`, immediately after `converted_type = _to_clause_type(c.clause_type)` (line
    ~168): `if converted_type is None and DETERMINISTIC_CLAUSE_TYPING_ENABLED: converted_type = infer_clause_type(c.text)`.
    Nothing else changes; `type_counts` naturally reflects the filled types. This is the single
    convergence point for both the LLM-skipped (`refined = regex_clauses`) and LLM-failed
    (regex-fallback) large-doc paths.

**Verify:** `python -m pytest tests/unit/test_clause_splitter_agent.py -q` → PASS.

---

## Task 5: Full-suite + scope gate  [AC-5]
- [ ] Run the **whole** backend suite: `python -m pytest -q` → GREEN. If any pre-existing splitter/
  Self-RAG test is surprised by a now-typed previously-`None` clause on a small doc (the explicit
  small-doc hidden-coupling call-out in plan §4), **pin it the way 027 did** (update the expectation
  with a justification), never weaken the assertion.
- [ ] `git diff --name-only main` shows ONLY the six allow-listed files (+ `specs/042-**`) —
  **no** graph/edge/`ContractState`/migration/Self-RAG-node/frontend change.

**Verify:** suite green; `git diff --name-only main` scope confirmed.

---

## Task 6: Live measurement (harness, AC-7) + MERGE GATE  [AC-7]
> Needs Ollama up (`qwen3:8b` generative + `bge-m3` embedding). Delivery OFF via the import-bound name
> `app.delivery.delivery_step.MCP_DELIVERY_ENABLED = False`. Run from `backend/` with `python -X utf8`
> (the ✓ print crashes cp1252 — 027/041 harness gotcha).

- [ ] **Subset (plan §6):** the "before" baseline is the cached run `eval/runs/20260817-190549`
  (docs unchanged). The "after" is a fresh flag-ON run restricted to the **large-doc regime** — all
  corpus docs whose regex clause count > `CLAUSE_SPLITTER_LLM_MAX_CLAUSES` (40), where baseline typing
  is ~0. If a full 32-doc run fits the deadline, run it; otherwise document the reduced scope.
- [ ] Run `python -X utf8 -m eval.harness.run` then `python -X utf8 -m eval.harness.score eval/runs/<ts>`.
- [ ] Record **before vs after**: clause_type non-`None` coverage, recall, miss rate, precision,
  false-flag rate, severity accuracy, and the Self-RAG **seen-but-discarded** diagnostic.
- [ ] **Positive-half control (the gap the 041 experiment left):** confirm ≥1 previously-missed
  floor-type clause (e.g. a `cap_on_liability` in CybergyHoldings) is now typed `liability`, validated
  **via the recall floor** (record shape `relevance=True, isrel=None, issup=None`), and flips fn→tp.
  Reuse `scripts/exp_clausetype_floor.py`'s rescue-trace (read-only reuse; not modified here).
- [ ] **APPLY THE MERGE GATE (plan §6, D3), concrete pass/fail:** ship flag-ON (default `True`) only
  if on the large-doc subset (i) recall RISES, AND (ii) false-flag rate rises by **≤ +5 pp** AND the
  recall gain (pp) is **≥ the false-flag gain (pp)**. If either is violated: first tighten the phrase
  map and re-measure (loops back to Task 3); if still not a net win, ship with
  `DETERMINISTIC_CLAUSE_TYPING_ENABLED = False` as the default (feature present, off) pending tuning.
  The trade must be a MEASURED net win, not assumed.

**Verify:** a short **before/after** results note (coverage, recall, false-flag deltas + the fn→tp
positive control) is captured; the merge-gate decision (flag ON vs OFF) is recorded with its numbers.

---

## Task 7: Merge
- [ ] Whole `pytest` green; `git diff` scope confirmed (six files); AC-7 numbers + merge-gate decision
  noted.
- [ ] Rebase `main`, merge `feature/042-deterministic-clause-typing`, delete branch (`git-finish`).

---

*Per §1/§11, implementation happens only on `feature/042-deterministic-clause-typing`, opened after
spec + plan + tasks are approved. Within-node deterministic fallback only — no graph node/edge, no
`ContractState`, no migration, no Self-RAG-node, no frontend change. The recall floor (027) and the
025 size gate are reused as-is (D6). The precision/recall trade is a MEASURED net win (AC-7 merge
gate), never assumed (D3).*
