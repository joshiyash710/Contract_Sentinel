# Feature 045 — Keep enumerated sub-list items with their governing clause — Tasks

Reference documents:
- Spec: `specs/045-sublist-fragment-merge/spec.md`
- Plan: `specs/045-sublist-fragment-merge/plan.md`
- Constitution: `specs/000-constitution.md` (**§2** no graph/edge/state; **§3** named reversible flag +
  inline fixed patterns; **§7** TDD + never weaken a test; **§1/§11** branch-gated)

Backend paths relative to `backend/`.

**Workflow reminders:**
- **TDD (§7):** cleaner/splitter tests written FAILING first, then implementation makes them green.
  Pin any surprised existing `test_regex_splitter` test (never weaken).
- **Scope = exactly 4 code files (AC-6):** `app/config.py`,
  `app/graph/nodes/splitters/regex_splitter.py`, `tests/unit/test_regex_splitter.py`,
  `tests/unit/test_config.py` (+ `specs/045-**`). No graph/edge/`ContractState`/migration/Self-RAG
  change.
- **⚠ Revert the local `OLLAMA_MODEL_NAME` qwen3:4b → qwen3:8b in `app/config.py` BEFORE committing**
  (it breaks 4 `test_config` model-name assertions); re-apply after the merge for local runs.
- **Reversibility is byte-identical (verified):** flag `True` ⇒ today's exact segmentation; the moved
  sub-list patterns are mutually exclusive at any line-start with the reordered base patterns, so
  append-order is safe. A test locks this.
- **Flag read at call time by bare module name** so tests can monkeypatch
  `regex_splitter.CLAUSE_SPLITTER_SPLIT_SUBLIST_MARKERS` — do NOT capture it in a default arg.

---

## Task 0: Branch (done — confirm)
- [x] On `feature/045-sublist-fragment-merge`; spec.md + plan.md spec-reviewer-APPROVED. Commit
  spec/plan/tasks on the branch.

**Verify:** `git branch --show-current` → `feature/045-sublist-fragment-merge`.

---

## Task 1: Config flag (§3)  [AC-3]
- [ ] **[MODIFY] `app/config.py`** — near the ClauseSplitter constants add
  `CLAUSE_SPLITTER_SPLIT_SUBLIST_MARKERS: bool = False` with the plan §1 comment (default False = don't
  split sub-lists = new behavior; True = today's segmentation, reversible).

**Verify:** `python -c "import app.config as c; print(c.CLAUSE_SPLITTER_SPLIT_SUBLIST_MARKERS)"` → `False`.

---

## Task 2: Config validity test (red → green)  [AC-3]
- [ ] **[MODIFY] `tests/unit/test_config.py`** (FAIL first): assert
  `CLAUSE_SPLITTER_SPLIT_SUBLIST_MARKERS` is a `bool`. Task 1 makes it green.

**Verify:** `python -m pytest tests/unit/test_config.py -q -k "sublist"` → PASS.

---

## Task 3: Splitter tests — write FAILING (red)  [AC-1..AC-5, AC-7]
- [ ] **[MODIFY] `tests/unit/test_regex_splitter.py`** — add feature-045 cases (reuse
  `_assert_valid_boundaries`). **Name each new test with `sublist` in the function name** (e.g.
  `test_sublist_items_merge_with_stem`) so the `-k "sublist"` filter selects them. The test file
  already imports the module — use its existing alias when monkeypatching the flag (below it is shown
  as `regex_splitter`; match whatever alias the file actually uses):
  - **AC-1/AC-2 (fixed-fixture hard equality):** the plan §3 fixture (a `"2.4 The Distributor shall
    not:\n(a) …; or\n(b) …; or\n(f) act as the agent … competitive with the Product; or\n2.5 Next
    obligation. …"` block). With the flag at DEFAULT (`False`): assert **exactly 2** clauses; clause 1
    contains both `"shall not"` and `"competitive with the Product"`; clause 2 is the `2.5` clause.
  - **AC-3 reversibility:** monkeypatch the splitter module's
    `CLAUSE_SPLITTER_SPLIT_SUBLIST_MARKERS = True` (via the file's import alias for
    `app.graph.nodes.splitters.regex_splitter`) → the SAME fixture
    yields more clauses, each `(a)`/`(b)`/`(f)` opening its own clause, and `(f)` is a stem-less
    fragment (no `"shall not"`). Lock byte-identical-to-today by asserting the exact flag-True boundary
    count/section_numbers.
  - **AC-4 no-regression:** a doc with only `1.`/`Article N`/`§N`/`WHEREAS` (no `(a)`/`a.`) yields the
    **same** boundaries with the flag `False` and `True`.
  - **AC-5 `a.`/`b.` block:** an `a. … \n b. … \n` list (avoid leading letters `i`/`v`/`x`) under a
    `1.` stem is one clause when `False`, split when `True`.
  - **AC-7 determinism:** repeated calls on the same input+flag are identical.

**Verify (RED):** `python -m pytest tests/unit/test_regex_splitter.py -q -k "sublist"` (the `-k`
expression MUST be a single quoted argument) — the new cases FAIL (the sub-list still splits by
default).

---

## Task 4: Splitter implementation (green)  [AC-1..AC-5, AC-7]
- [ ] **[MODIFY] `app/graph/nodes/splitters/regex_splitter.py`** per plan §2:
  - Add `import app.config as _config` and re-expose
    `CLAUSE_SPLITTER_SPLIT_SUBLIST_MARKERS = _config.CLAUSE_SPLITTER_SPLIT_SUBLIST_MARKERS` (bare name).
  - Move the two sub-list patterns (current indices 4-5: `(\([a-z]+\)|\([ivxlcdm]+\))\s` and
    `([a-z])\.[ \t]`) out of `_COMPILED_PATTERNS` into a new `_SUBLIST_PATTERNS` tuple; base
    `_COMPILED_PATTERNS` keeps every other pattern in its current order.
  - In `split_by_regex`, build `patterns = list(_COMPILED_PATTERNS)`; if
    `CLAUSE_SPLITTER_SPLIT_SUBLIST_MARKERS` is True, `patterns += list(_SUBLIST_PATTERNS)`; iterate
    `patterns` in the existing `marker_map` first-match-wins loop. Read the flag by the bare
    module-level name (not a default arg) so monkeypatch works.

**Verify (GREEN):** `python -m pytest tests/unit/test_regex_splitter.py -q` → all PASS (new + existing).

---

## Task 5: Full suite + scope gate  [AC-6]
- [ ] `python -m pytest -q` → GREEN (pin any surprised existing test with justification; never weaken).
- [ ] `git diff --name-only main` shows exactly the 4 code files (+ `specs/045-**`) — no
  graph/edge/`ContractState`/migration/Self-RAG change, and (after the revert) **no `OLLAMA_MODEL_NAME`
  change**.

**Verify:** suite green; diff scope matches the plan §0 allow-list; `OLLAMA_MODEL_NAME == "qwen3:8b"`
in the staged diff.

---

## Task 6: Merge
- [ ] Revert local qwen3:4b → qwen3:8b; whole `pytest` green; diff scope confirmed. Rebase `main`,
  merge `feature/045-sublist-fragment-merge`, delete branch (`git-finish`). Re-apply qwen3:4b locally.

---

*Per §1/§11, implementation happens only on `feature/045-sublist-fragment-merge`. Segmentation-input
only — no `ContractState`, no graph/edge, no migration, no Self-RAG change. The change is a reversible
§3 flag (default = the measured-better no-split behavior); flag True reproduces today's segmentation
byte-for-byte.*
