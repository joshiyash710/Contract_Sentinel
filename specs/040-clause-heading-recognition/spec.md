# Feature 040 — Spelled-out clause-heading recognition (regex splitter)

> **Reconstruction note (2026-08-19):** this feature was implemented and its spec/plan/tasks were
> spec-reviewer-APPROVED in an earlier session, but the artifacts were never committed and were lost.
> This spec is rebuilt from the committed intent, the implementation, and the AC-anchored test suite
> (`tests/unit/test_regex_splitter.py`), then re-gated before the implementation is merged. Behavior
> is unchanged from the approved implementation; only the documents are reconstructed.

## 1. Problem statement

The ClauseSplitterAgent's regex pre-pass (`app/graph/nodes/splitters/regex_splitter.py`) recognizes
structural markers — `1.` / `1.1`, `Article N`, `Section N`, `§N`, `(a)` / `(ii)`, `a.`, and the
recital keywords (`WHEREAS`, …). It does **not** recognize **spelled-out** headings such as
`CLAUSE ONE`, `ARTICLE ONE`, or `SECTION FIRST`, and it has **no `CLAUSE` pattern at all** (not even
`CLAUSE 1`).

A real contract that headings its sections `CLAUSE ONE … CLAUSE EIGHT` therefore matches **no**
marker, falls through to paragraph splitting, and **catastrophically under-segments** — an 8-clause
agreement collapses toward a handful of paragraph blobs. Downstream this is silent and dangerous: the
pipeline reports few or no findings and still marks the analysis clean (`analysis_degraded` stays
`false`), because under-segmentation is not itself an error signal. The observed trigger was a
student-loan agreement with `CLAUSE ONE … CLAUSE EIGHT` headings.

This feature makes the regex splitter recognize spelled-out clause/article/section headings, so such
contracts segment correctly and reach the rest of the pipeline as discrete clauses.

### Position relative to the constitution
**No graph/edge change, no `ContractState` change, no migration, no config/flag change.** This adds
**patterns to an existing regex list inside `regex_splitter.py`** (step 1 of the ClauseSplitter's
regex→LLM pipeline). The spelled-out-ordinal vocabulary is a **fixed English linguistic constant**
(like the existing recital-keyword list), **not** a tunable threshold — so per §3 it stays inline in
the module rather than in `app/config.py`. Per §7 it is TDD-unit-tested (pure, no Ollama, no I/O). Per
§1/§11 it is developed on `feature/040-clause-heading-recognition`.

## 2. Inputs and outputs

- **Input:** contract `text` passed to `split_by_regex(text)` (unchanged signature).
- **Output:** the same `list[ClauseBoundary]` as today, but text that uses spelled-out
  clause/article/section headings now produces one boundary per heading (instead of collapsing to
  paragraph fallback). `section_number` carries the **verbatim** matched heading (original casing).
- **No** new state field, config constant, boundary-model field, or report/schema change.

### 2.1 Behavior change (`regex_splitter.py`)
Add, to the module:
- `_ORDINAL_WORDS` — a `|`-joined alternation of the spelled-out cardinals **one–twenty** and ordinals
  **first–twentieth**. Longer forms that contain a shorter form as a prefix are listed **first**
  (e.g. `twentieth` before `twenty`, `nineteen` before `nine`) so the trailing `\b` never truncates a
  longer word to its prefix.

Add, to `_COMPILED_PATTERNS`:
- `CLAUSE` heading: `^[ \t]*(clause\s+(?:\d+(?:\.\d+)*|(?:<ordinals>)))\b` — accepts a **digit** form
  (`CLAUSE 1`, `CLAUSE 1.2`) **or** a spelled-out ordinal (`CLAUSE ONE`, `Clause First`), case-
  insensitive. (`CLAUSE` had no prior pattern; this adds both digit and word forms.)
- `ARTICLE`/`SECTION` spelled-out heading: `^[ \t]*((?:article|section)\s+(?:<ordinals>))\b`. Digit
  forms of `Article N` / `Section N` are already matched by the pre-existing patterns, which win by
  the existing first-match-wins rule; this pattern only **adds** the spelled-out forms.

The `\b` word boundary prevents false matches on prose (`"Clause headings are for convenience"`) and on
glued tokens (`"CLAUSEONE"`). The rest of `split_by_regex` (marker collection, first-match-wins
dedup by start position, clause building, paragraph fallback) is unchanged.

## 3. Resolved decisions (inline)

- **D1 — Vocabulary scope one–twenty / first–twentieth.** Covers the overwhelmingly common
  hand-numbered-heading range. Beyond twenty, hyphenated compounds (`TWENTY-FIRST`) are out of scope
  (EC / §5): such a heading matches at its `TWENTY` prefix (a boundary is still created, just labeled
  `CLAUSE TWENTY`) — a documented partial match, not a crash or a miss.
- **D2 — Longer-before-shorter ordering is load-bearing.** Because matching is substring-anchored with
  a trailing `\b`, `twenty` listed before `twentieth` would truncate `twentieth`→`twenty`. The
  vocabulary lists every longer form before any shorter form it prefixes.
- **D3 — Inline vocabulary, not §3 config.** It is a fixed linguistic fact, not an operator-tunable
  threshold; it lives inline beside the recital-keyword list (mirrors that precedent).
- **D4 — Additive only; first-match-wins preserved.** Digit `Article N`/`Section N`/`§N`/`1.` markers
  keep their existing behavior; the new patterns never override an earlier match at the same start
  position (`SECTION 1.2` is captured once by the digit pattern, not doubled).
- **D5 — `\b`-guarded, no LLM.** The change is purely additional regex; deterministic, offline,
  independently unit-testable (no Ollama, no I/O).

## 4. Acceptance criteria (pytest — all offline, no Ollama)

- **AC-1:** eight `CLAUSE <WORD>` headings (`CLAUSE ONE … CLAUSE EIGHT`) produce **eight** boundaries.
- **AC-2:** `section_number` is the **verbatim** heading with original casing (`"CLAUSE ONE"`,
  `"CLAUSE SIX"`), never `None` for a matched heading.
- **AC-3:** `ARTICLE <WORD>` and `SECTION <WORD>` headings segment symmetrically (3 → 3, 2 → 2).
- **AC-4:** digit-numbered `CLAUSE 1` / `Clause 1.2` / `ARTICLE 4` also match (not only spelled-out).
- **AC-5:** case-insensitive — `clause one` / `Clause One` / `CLAUSE ONE` behave identically.
- **AC-6:** pre-existing markers still segment exactly as before — a 7-distinct-marker document
  (`1.`, `Article 5`, `Section 1.2`, `§3`, `(a)`, `a.`, `WHEREAS`) still yields **7** boundaries.
- **AC-7 (motivating case):** the 8-clause agreement repeated 3× → **24** boundaries (previously
  collapsed to ~3 via paragraph fallback).
- **AC-8 (no architecture change):** `git diff` touches only `regex_splitter.py` and its test (+ the
  `specs/040-**` docs) — no config/state/graph/edge/migration/frontend change; whole `pytest` green.
- **AC-9:** first-match-wins — `SECTION 1.2` is captured **once** (by the pre-existing digit pattern),
  not doubled by the new spelled-out pattern.
- **AC-10:** no false boundary — `Clause` used in prose (no number/ordinal) and the glued token
  `CLAUSEONE` do **not** create a boundary (single clause, `section_number is None`).

## 5. Edge cases
- **EC-1 — `CLAUSE TWENTY-FIRST`** (beyond the vocabulary): matches at the `TWENTY` prefix →
  `section_number == "CLAUSE TWENTY"`. Documented partial match (D1); a boundary is still created.
- **EC-2 — Ordinal-prefix truncation** (`twentieth` vs `twenty`): prevented by the longer-before-
  shorter ordering (D2); `CLAUSE TWENTIETH` / `ARTICLE FIRST` resolve verbatim.
- **EC-3 — Prose / glued tokens:** `\b` blocks `"Clause headings…"` and `"CLAUSEONE"` (AC-10).
- **EC-4 — Mixed digit + word headings** in one document: both match; ordering by start position is
  unchanged.

## 6. Out of scope
- Hyphenated / compound ordinals beyond twenty (`TWENTY-FIRST`, `THIRTY-SECOND`) — partial-match
  behavior is accepted and documented (D1/EC-1).
- Any non-English heading vocabulary.
- Changing the LLM refinement step, config, state, graph, or the paragraph fallback logic.
- Surfacing under-segmentation as an `analysis_degraded` signal — a separate concern.

## 7. Evaluation (metrics to log)
Deterministic unit tests only (no harness/eval run needed): the AC suite in
`tests/unit/test_regex_splitter.py`. Correctness is exact boundary counts + verbatim `section_number`
assertions; no probabilistic measurement.

## 8. Notes for plan.md / tasks.md (pointers)
- **File:** `app/graph/nodes/splitters/regex_splitter.py` — add `_ORDINAL_WORDS` (module constant) and
  two `re.compile(...)` entries to `_COMPILED_PATTERNS`; nothing else in the module changes.
- **Tests:** extend `tests/unit/test_regex_splitter.py` with the AC-1…AC-10 cases + the documented
  `TWENTY-FIRST` partial-match and ordinal-spot-check tests, reusing the existing
  `_assert_valid_boundaries` helper. TDD failing-first against the pre-040 module.
- **Decision 1 (§8 anchor in tests):** ordinal vocabulary resolves and `twentieth` is not truncated.
