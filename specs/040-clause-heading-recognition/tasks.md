# Feature 040 — Spelled-out clause-heading recognition — Implementation Tasks

Reference documents:
- Spec: `specs/040-clause-heading-recognition/spec.md`
- Plan: `specs/040-clause-heading-recognition/plan.md`
- Constitution: `specs/000-constitution.md` (**§2** no node/edge change; **§3** inline linguistic
  vocabulary, NOT a tunable config threshold; **§7** TDD + never weaken a test; **§1/§11** branch-gated)

Backend paths relative to `backend/`.

**Workflow reminders:**
- **TDD (§7):** the AC tests are written/confirmed FAILING against the pre-040 module first, then the
  two patterns make them green. Do not weaken a surprised existing test — pin it with justification.
- **Scope is exactly 5 paths (AC-8).** `git diff --name-only main` must show only
  `app/graph/nodes/splitters/regex_splitter.py`, `tests/unit/test_regex_splitter.py`, and the three
  `specs/040-**` docs. **No** config/state/graph/edge/migration/frontend change.
- **The implementation already exists in `git stash@{0}` — a MIXED stash.** It also contains unrelated
  frontend WIP (`frontend/src/components/history/ReportHistoryView.tsx`,
  `frontend/src/components/ui/Dropdown.tsx`, `frontend/src/__tests__/reportHistory.test.tsx`). Apply
  **ONLY** the two backend files; the frontend WIP must NOT come along.
- **Additive only:** the change only appends to `_COMPILED_PATTERNS` + adds `_ORDINAL_WORDS`. Existing
  markers and `split_by_regex` control flow are untouched (AC-6 pins no-regression).
- **Inline vocabulary (§3):** `_ORDINAL_WORDS` lives in `regex_splitter.py`, NOT `app/config.py` — it
  is a fixed English linguistic fact, not an operator-tunable threshold (mirrors the recital keywords).

---

## Task 0: Branch
- [x] From up-to-date `main`, create `feature/040-clause-heading-recognition`. Commit the reconstructed
  `spec.md`/`plan.md`/`tasks.md` on the branch (each spec-reviewer-APPROVED before proceeding).

**Verify:** `git branch --show-current` → `feature/040-clause-heading-recognition`.

---

## Task 1: AC tests — write/confirm FAILING (red)  [AC-1…AC-10]
- [ ] **[MODIFY] `tests/unit/test_regex_splitter.py`** — append the feature-040 block (recover it
  verbatim from `git stash@{0}`; it is already AC-anchored), reusing the existing
  `_assert_valid_boundaries` helper. Cases:
  - `test_clause_word_headings_split` (AC-1: 8 `CLAUSE ONE…EIGHT` → 8)
  - `test_clause_word_section_number_captured` (AC-2: verbatim `section_number`, casing preserved)
  - `test_article_word_headings_split` (AC-3: `ARTICLE <WORD>` 3→3, `SECTION <WORD>` 2→2)
  - `test_clause_article_digit_forms` (AC-4: `CLAUSE 1` / `Clause 1.2` / `ARTICLE 4` → 3)
  - `test_clause_heading_case_insensitive` (AC-5)
  - `test_existing_markers_no_regression` (AC-6: 7-marker doc → 7)
  - `test_student_loan_fixture_24_clauses` (AC-7: 8-clause fixture ×3 → 24; PII-free sample)
  - `test_first_match_wins_no_double_count` (AC-9: `SECTION 1.2` → 1)
  - `test_clause_prose_no_false_boundary` (AC-10: prose `Clause` + glued `CLAUSEONE` → 1, `None`)
  - `test_ordinal_vocabulary_spot_check` (spec D1/D2: `ARTICLE FIRST` + `CLAUSE TWENTIETH` verbatim, no
    `twentieth`→`twenty` truncation)
  - `test_clause_twenty_first_partial_match` (spec §5/EC-1: `CLAUSE TWENTY-FIRST` → 1 boundary labeled
    `"CLAUSE TWENTY"`, documented partial match)
- [ ] If the pre-040 file's module docstring/header states an exact passing count (e.g. "all 16 PASS"),
  update that stale comment to reflect the new total (do not leave a misleading count).

**Verify (RED):** `python -m pytest tests/unit/test_regex_splitter.py -q` — the CLAUSE-word / spelled-out
cases FAIL (they collapse to the paragraph-fallback count) while the pre-existing tests still pass.

---

## Task 2: Implementation — make green (§2 of plan)  [AC-1…AC-7, AC-9, AC-10]
- [ ] **[MODIFY] `app/graph/nodes/splitters/regex_splitter.py`** — add, below `import re`, the
  `_ORDINAL_WORDS` constant (cardinals one–twenty + ordinals first–twentieth, **longer forms before
  shorter prefixes** — `twentieth` before `twenty`, ordinal block before cardinal block). Then append
  two `re.compile(...)` entries to `_COMPILED_PATTERNS`:
  - `(?mi)^[ \t]*(clause\s+(?:\d+(?:\.\d+)*|(?:{_ORDINAL_WORDS})))\b` (digit **or** ordinal; CLAUSE had
    no prior pattern)
  - `(?mi)^[ \t]*((?:article|section)\s+(?:{_ORDINAL_WORDS}))\b` (spelled-out only; digit article/
    section already handled by existing patterns via first-match-wins)
  Recover the exact text from `git stash@{0}`. Nothing else in the module changes.

**Verify (GREEN):** `python -m pytest tests/unit/test_regex_splitter.py -q` → all PASS.

---

## Task 3: Full suite + scope gate  [AC-8]
- [ ] Whole backend suite: `python -m pytest -q` → GREEN (no surprised existing test; if one appears,
  pin it with justification, never weaken).
- [ ] `git diff --name-only main` shows **exactly** the 5 allow-listed paths (2 backend + 3 spec docs)
  and **no** frontend WIP from the mixed stash, no config/state/graph/edge/migration change.

**Verify:** suite green; diff scope matches the plan §6 allow-list exactly.

---

## Task 4: Merge
- [ ] Whole `pytest` green; diff scope confirmed. Rebase `main`, merge
  `feature/040-clause-heading-recognition`, delete branch (`git-finish`).

---

*Per §1/§11, implementation happens only on `feature/040-clause-heading-recognition`, opened after
spec + plan + tasks are (re-)approved. Additive regex only — no `ContractState`, no config, no graph/
edge, no migration, no frontend. Only the two backend files are taken from the mixed `stash@{0}`.*
