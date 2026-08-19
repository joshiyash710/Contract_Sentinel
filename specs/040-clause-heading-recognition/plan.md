# Feature 040 — Technical plan: spelled-out clause-heading recognition

Derived from `spec.md`. Adds a fixed spelled-out-ordinal vocabulary and two `\b`-guarded regex
patterns to the ClauseSplitter regex pre-pass so `CLAUSE ONE` / `ARTICLE FIRST` / `SECTION TWO` style
headings segment correctly. **No graph/edge/`ContractState`/migration/config change** — additive
patterns inside one existing module.

Branch: `feature/040-clause-heading-recognition` (per constitution §11).

> Reconstruction note: artifacts were lost after approval; this plan is rebuilt to match the
> already-implemented change (in `git stash@{0}`) and re-gated before merge.

## 0. Scope of change (files touched)

Per **AC-8** the `git diff main` must touch only:
1. `backend/app/graph/nodes/splitters/regex_splitter.py` — add `_ORDINAL_WORDS` + two compiled
   patterns.
2. `backend/tests/unit/test_regex_splitter.py` — add the AC-1…AC-10 tests + the documented
   `TWENTY-FIRST` partial-match and ordinal spot-check.
3. `specs/040-clause-heading-recognition/{spec,plan,tasks}.md` — the artifacts.

No other file changes. **The mixed `stash@{0}` also contains unrelated frontend WIP
(`ReportHistoryView.tsx`, `Dropdown.tsx`, `reportHistory.test.tsx`) — those are NOT part of 040 and
must NOT be applied.** Only the two backend files above come from the stash.

## 1. Vocabulary constant (`regex_splitter.py`)

Add near the top of the module (below `import re`), beside the existing pattern list:

```python
# Spelled-out clause ordinals (feature 040) — a fixed English linguistic vocabulary (NOT a tunable
# threshold, so per constitution §3 it stays inline like the recital-keyword list below). Longer
# forms precede the bare cardinals they contain as a prefix so the trailing \b never truncates
# (e.g. "twentieth" before "twenty"). Covers cardinals ONE–TWENTY and ordinals FIRST–TWENTIETH.
_ORDINAL_WORDS = (
    "first|second|third|fourth|fifth|sixth|seventh|eighth|ninth|tenth|"
    "eleventh|twelfth|thirteenth|fourteenth|fifteenth|sixteenth|seventeenth|"
    "eighteenth|nineteenth|twentieth|"
    "eleven|twelve|thirteen|fourteen|fifteen|sixteen|seventeen|eighteen|nineteen|twenty|"
    "one|two|three|four|five|six|seven|eight|nine|ten"
)
```

**Ordering is load-bearing (spec D2):** every longer form appears before any shorter form it prefixes
(`twentieth` before `twenty`; the whole ordinal block before the cardinal block; `nineteen` before
`nine`). Because the patterns are substring-anchored with a trailing `\b`, a shorter-first ordering
would truncate `twentieth` → `twenty`.

## 2. Two patterns appended to `_COMPILED_PATTERNS`

Append after the recital-keyword pattern (order relative to the digit patterns does not matter for
correctness because of first-match-wins dedup by start position, §3):

```python
    # feature 040: "CLAUSE 1" / "CLAUSE 1.2" / "CLAUSE ONE" / "Clause First". CLAUSE had no prior
    # pattern; here it accepts a digit OR a spelled-out ordinal. \b blocks prose ("Clause headings").
    re.compile(rf"(?mi)^[ \t]*(clause\s+(?:\d+(?:\.\d+)*|(?:{_ORDINAL_WORDS})))\b"),
    # feature 040: spelled-out ARTICLE/SECTION — "ARTICLE ONE" / "SECTION FIRST". Digit forms of
    # article/section are already matched by the pre-existing patterns above (which win by order).
    re.compile(rf"(?mi)^[ \t]*((?:article|section)\s+(?:{_ORDINAL_WORDS}))\b"),
```

- **CLAUSE pattern:** `CLAUSE` had no pattern at all, so this one carries **both** the digit form
  (`CLAUSE 1`, `CLAUSE 1.2`) and the spelled-out form (`CLAUSE ONE`). `(?mi)` = multiline +
  case-insensitive. The capture group is the whole heading → `section_number` is verbatim (AC-2).
- **ARTICLE/SECTION pattern:** only the **spelled-out** form. Digit `Article N` / `Section N` are
  already matched by the pre-existing patterns; via first-match-wins those earlier patterns win at the
  same start position, so `SECTION 1.2` is captured once by the digit pattern and never double-counted
  (AC-9). The two are in fact mutually exclusive (digit vs word), which is even stronger.
- **`\b` guard:** blocks prose (`"Clause headings are for convenience"`) and glued tokens
  (`"CLAUSEONE"`) from creating a boundary (AC-10).

Nothing else in `regex_splitter.py` changes — `split_by_regex`, the `marker_map` first-match-wins
collection, `_extract_section_number`, and both fallbacks are untouched.

## 3. Control-flow / correctness

- **First-match-wins preserved (D4):** `marker_map[pos]` keeps the first pattern that matched at a
  start position; iterating patterns in list order, the pre-existing digit/marker patterns are tried
  before (or independently of) the new ones and are never overridden. `SECTION 1.2` → one boundary.
- **No new field / shape change:** `section_number` is still the first non-`None` capture group
  (`_extract_section_number`), so the verbatim heading flows through unchanged; `ClauseBoundary`
  fields are identical.
- **Deterministic, offline (D5):** pure regex; no Ollama, no I/O, no RNG. Repeated calls identical.
- **No regression path:** the change only **adds** patterns; any text that matched a boundary before
  still matches the same boundary first (AC-6 pins the 7-marker document at 7).

## 4. Test plan (TDD, `tests/unit/test_regex_splitter.py`)

Failing-first against the pre-040 module (the CLAUSE-word cases return the paragraph-fallback count,
not the per-heading count, until the patterns are added). Reuse the existing `_assert_valid_boundaries`
helper. All offline.

- **AC-1 / AC-2 / AC-7:** an 8-clause `CLAUSE ONE…EIGHT` fixture (PII-free student-loan sample) → 8
  boundaries; verbatim `section_number` (`"CLAUSE ONE"`, `"CLAUSE SIX"`); ×3 → 24 boundaries.
- **AC-3:** `ARTICLE <WORD>` (3→3) and `SECTION <WORD>` (2→2).
- **AC-4:** digit `CLAUSE 1` / `Clause 1.2` / `ARTICLE 4` → 3.
- **AC-5:** `clause one` / `Clause One` / `CLAUSE ONE` identical (2 each).
- **AC-6:** 7-distinct-pre-existing-marker doc → 7 (no regression).
- **AC-9:** `SECTION 1.2` → 1 boundary (not doubled).
- **AC-10:** prose `Clause` + glued `CLAUSEONE` → 1 clause, `section_number is None`.
- **Spec D1/D2 spot-checks:** `ARTICLE FIRST` + `CLAUSE TWENTIETH` resolve verbatim (no
  `twentieth`→`twenty` truncation); `CLAUSE TWENTY-FIRST` → one boundary labeled `"CLAUSE TWENTY"`
  (documented partial match, EC-1).
- **AC-8:** confirm (by diff review) only the three allow-listed paths change; whole `pytest` green.

## 5. Risks / limitations
- **Compound ordinals > twenty** (`TWENTY-FIRST`) partial-match at the `TWENTY` prefix — accepted and
  test-pinned (still creates a boundary; only the label is the prefix). Extending the vocabulary is a
  future option, not needed now.
- **English-only** vocabulary — out of scope (spec §6).
- **Coverage, not correctness ceiling:** headings outside the recognized marker set still fall through
  to paragraph splitting exactly as today (no worse than before).

## 6. Merge
- Whole `pytest` green; `git diff --name-only main` shows **exactly** these five paths and nothing
  else (in particular, none of the mixed stash's frontend WIP):
  ```
  backend/app/graph/nodes/splitters/regex_splitter.py
  backend/tests/unit/test_regex_splitter.py
  specs/040-clause-heading-recognition/spec.md
  specs/040-clause-heading-recognition/plan.md
  specs/040-clause-heading-recognition/tasks.md
  ```
- Rebase `main`, merge `feature/040-clause-heading-recognition`, delete branch (`git-finish`).
