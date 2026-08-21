# Feature 045 — Technical plan: keep enumerated sub-list items with their governing clause

Branch: `feature/045-sublist-fragment-merge` (per constitution §11).

Derived from `spec.md`. Gates the two sub-list-marker regex patterns in `regex_splitter.py` behind a
new §3 flag so enumerated `(a)`/`(ii)`/`a.` sub-items stay attached to their governing clause. **No
graph/edge/`ContractState`/migration change.**

## 0. Scope of change (files touched)

Per **AC-6** the `git diff --name-only main` must show **exactly**:
```
backend/app/config.py
backend/app/graph/nodes/splitters/regex_splitter.py
backend/tests/unit/test_regex_splitter.py
backend/tests/unit/test_config.py
specs/045-sublist-fragment-merge/{spec,plan,tasks}.md
```
No other file. **⚠ The local uncommitted `OLLAMA_MODEL_NAME = "qwen3:4b"` in `app/config.py` must be
reverted to `"qwen3:8b"` before committing** (it breaks 4 `test_config` model-name assertions);
re-apply it after the merge for local runs.

## 1. Config change (`app/config.py`)

Near the ClauseSplitter constants add (mirroring the default-OFF bool convention of
`DETERMINISTIC_CLAUSE_TYPING_ENABLED`):

```python
CLAUSE_SPLITTER_SPLIT_SUBLIST_MARKERS: bool = False
# Feature 045. When False (default), the regex splitter does NOT split on enumerated sub-list markers
# "(a)"/"(ii)"/"a." — those sub-items stay attached to their governing clause (measured: recovers
# material obligations buried in sub-items, e.g. a non-compete in item (f) of a "shall not:" list,
# and yields healthier segmentation). True ⇒ byte-for-byte today's segmentation (sub-lists split).
```

## 2. Splitter change (`regex_splitter.py`)

- Add a minimal config read (the module currently imports none):
  ```python
  import app.config as _config
  CLAUSE_SPLITTER_SPLIT_SUBLIST_MARKERS = _config.CLAUSE_SPLITTER_SPLIT_SUBLIST_MARKERS
  ```
  Re-exposed as a bare module name so tests can monkeypatch it.
- Split the current `_COMPILED_PATTERNS` (indices 4 and 5 are the sub-list markers) into two constants:
  ```python
  _SUBLIST_PATTERNS = (
      re.compile(r"(?m)^[ \t]*(\([a-z]+\)|\([ivxlcdm]+\))\s"),  # "(a)", "(ii)"
      re.compile(r"(?m)^[ \t]*([a-z])\.[ \t]"),                 # "a.", "b."
  )
  ```
  `_COMPILED_PATTERNS` (base) keeps every other pattern in its current order (the numeric `\d+.`,
  Article/Section/§, recital, and the two feature-040 CLAUSE/ARTICLE-ordinal patterns) — the two
  sub-list patterns are *removed* from `_COMPILED_PATTERNS` and live only in `_SUBLIST_PATTERNS`.
- In `split_by_regex`, assemble the active pattern list **at call time** (so the flag is honored per
  call / monkeypatchable), reading the module-level flag:
  ```python
  patterns = list(_COMPILED_PATTERNS)
  if CLAUSE_SPLITTER_SPLIT_SUBLIST_MARKERS:
      patterns = patterns + list(_SUBLIST_PATTERNS)
  ```
  Then iterate `patterns` (not `_COMPILED_PATTERNS`) in the existing `marker_map` first-match-wins
  collection loop. Nothing else in the function changes.

### Correctness
- **Flag True ⇒ identical to today (AC-3):** `patterns` = base + sub-list. Since first-match-wins keys
  by start position and the sub-list patterns are appended (base patterns tried first at any shared
  position — same as today's ordering where they sat at indices 4-5 among later patterns; **note:** no
  higher-level pattern matches at a `(a)`/`a.` line-start, so append-order does not change which marker
  wins at a sub-list position). The plan's tasks include an explicit byte-identical A/B assertion to
  lock this.
- **Flag False ⇒ sub-list positions produce no marker** → those lines are absorbed into the clause
  opened by the nearest preceding higher-level marker (or the paragraph/whole-text fallback, EC-1).
- **No under-segmentation (D4):** `\d+.`/Article/Section/§/Clause/recital markers remain, so real
  clause boundaries are still detected (A/B: 187→117 clauses, not →a few blobs).
- **Pure/deterministic (D5):** flag read at call time; no I/O/RNG.

## 3. Test plan (TDD, `tests/unit/test_regex_splitter.py`)
Failing-first per §7. All offline. Reuse the existing `_assert_valid_boundaries` helper.

- **AC-1 / AC-2 (fixed-fixture hard equality — spec-reviewer suggestion 1):** a fixed input string
  ```
  2.4 The Distributor shall not:
  (a) represent itself as an agent; or
  (b) pledge the Supplier's credit; or
  (f) act as the agent or the buying agent, for any goods which are competitive with the Product; or
  2.5 Next obligation. The Distributor shall keep records.
  ```
  with the flag at default (`False`): assert **exactly 2** clauses (`2.4` incl. all sub-items, `2.5`),
  the first contains both `"shall not"` and `"competitive with the Product"`, and the count is a hard
  equality (not `> 1`).
- **AC-3 reversibility:** monkeypatch `regex_splitter.CLAUSE_SPLITTER_SPLIT_SUBLIST_MARKERS = True` →
  the same input yields the pre-045 boundary set (each `(a)`/`(b)`/`(f)` opens its own clause — assert
  the higher clause count and that `(f)` is now its own stem-less fragment). Also assert that toggling
  the flag True reproduces today's output byte-for-byte on this fixture.
- **AC-4 no-regression:** a doc with only `1.`/`Article N`/`§N`/`WHEREAS` (no `(a)`/`a.`) yields the
  **same** boundaries with the flag False and True (the removed patterns never matched it). The rest of
  the existing `test_regex_splitter` suite must stay green unchanged (pin any surprise, never weaken).
- **AC-5 `a.`/`b.` block:** an `a. … \n b. … \n` enumerated block under a `1.` stem is one clause when
  False, split when True.
- **AC-7 determinism:** repeated calls on the same input+flag identical.
- **AC-3 config (`test_config.py`):** `CLAUSE_SPLITTER_SPLIT_SUBLIST_MARKERS` is a `bool`.

## 4. Measurement (AC-8, optional/offline evidence)
The offline splitter A/B already recorded in the spec (FuseMedical: 187→117 clauses, non-compete
113-char fragment → 915-char clause with its `"2.4 The Distributor shall not:"` stem, short<80 59→31)
is the primary evidence. A live harness re-run (flag default) to confirm the fn→tp on the non-compete
needs Ollama and is deferred (AC-8), not required to merge.

## 5. Risks / limitations
- **Larger clauses:** merged sub-lists make some clauses longer; bounded by the unchanged
  `MAX_CLAUSES_LIMIT` re-clamp (the 915-char case is well under the 4561-char max already present).
- **Leading-`(a)` docs (EC-1):** a document that opens directly into `(a)/(b)` with no higher marker
  falls to the paragraph/whole-text fallback with the flag off — acceptable (keeps items together, no
  worse than a fragment); rare in real contracts.
- **Numeric-schedule noise NOT addressed** (out of scope, D3) — a separate future concern.

## 6. Merge
- Whole `pytest` green; `git diff --name-only main` = the four code files (+ `specs/045-**`). **Revert
  the local qwen3:4b override first.** Rebase `main`, merge `feature/045-sublist-fragment-merge`,
  delete branch (`git-finish`); re-apply qwen3:4b locally after.
