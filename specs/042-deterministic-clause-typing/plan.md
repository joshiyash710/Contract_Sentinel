# Feature 042 — Technical plan: deterministic clause-type fallback

Derived from `spec.md`. Adds a pure, deterministic clause-type tagger that fills `clause_type` when
the ClauseSplitter LLM refinement left it `None`, reviving the existing feature-027 Self-RAG recall
floor on large docs. **No graph/edge/`ContractState`/migration change and no Self-RAG-node change**
(§2 of constitution) — this feature only supplies typing input the 027 floor already consumes.

## 0. Scope of change (files touched)

Per **AC-5** the `git diff` must touch only these:

1. `backend/app/config.py` — add `DETERMINISTIC_CLAUSE_TYPING_ENABLED` (bool) +
   `DETERMINISTIC_CLAUSE_TYPE_PATTERNS` (ordered map).
2. `backend/app/graph/nodes/splitters/clause_typer.py` — **NEW** pure tagger `infer_clause_type`.
   (Single committed location — resolves spec §8's two-candidate ambiguity; it lives in the
   `splitters` package next to `regex_splitter`/`llm_refiner`.)
3. `backend/app/graph/nodes/clause_splitter_agent.py` — module aliases + a fill-`None`-only call in
   `_build_return`.
4. `backend/tests/unit/test_clause_typer.py` — **NEW** pure-tagger tests (AC-1/2/6).
5. `backend/tests/unit/test_clause_splitter_agent.py` — integration + reversibility (AC-3/4).
6. `backend/tests/unit/test_config.py` — flag type + valid-`ClauseType` key assertion (AC-4).

No other file changes. The 041/026 harness (`backend/eval/harness/`) is **run**, not modified (AC-7).

## 1. Config change (`app/config.py`)

Near the ClauseSplitter constants (`CLAUSE_SPLITTER_LLM_MAX_CLAUSES`, `MAX_CLAUSES_LIMIT`) add:

```python
DETERMINISTIC_CLAUSE_TYPING_ENABLED: bool = True
# Master switch (feature 042). When True, ClauseSplitter fills clause_type from a deterministic
# keyword tagger for any clause the LLM refinement left None (025 Lever-A skip on >40-clause docs,
# or an off-schema LLM failure). Revives the 027 recall floor on large docs with NO LLM dependence.
# False ⇒ byte-for-byte today's behavior (previously-None clauses stay None). Reversible (D5).

# Ordered map: ClauseType.value -> tuple of lowercase phrase patterns. ONLY the recall-floor types
# (SELF_RAG_RECALL_FLOOR_TYPES) — typing a non-floor type has no floor effect (D2). CONSERVATIVE,
# high-precision multi-word legal phrases (a floor-typed clause is VALIDATED even if ISSUP would
# discard, so over-matching = false flags, D3). Order = tie-break for a multi-match clause (EC-1).
DETERMINISTIC_CLAUSE_TYPE_PATTERNS: tuple = (
    ("confidentiality", ("confidential information", "non-disclosure", "shall not disclose",
                          "keep confidential", "proprietary information")),
    ("liability",       ("limitation of liability", "shall not be liable", "in no event shall",
                         "indemnif", "hold harmless", "consequential damages", "liquidated damages")),
    ("intellectual_property", ("intellectual property rights", "proprietary rights", "hereby assigns",
                               "assignment of intellectual property",
                               "ownership of the intellectual property",
                               "all right, title and interest in and to the intellectual property",
                               "work product")),
    ("termination",     ("termination of this agreement", "terminate this agreement",
                         "survive termination", "expiration or termination", "right to terminate")),
)
# ALL patterns are CONSERVATIVE MULTI-WORD LEGAL PHRASES (D3). Deliberately NO bare single words like
# "patent"/"copyright"/"trademark" (they appear in definitions/representations/license/notices clauses
# that are NOT IP-ownership risks → would be floor-VALIDATED as false flags). Deliberately NO generic
# fragments like "assignment of" (matches "assignment of this Agreement" = anti_assignment boilerplate)
# or "ownership of the" — each IP phrase carries its own IP context. NOTE: the 041-triage labels
# anti_assignment / audit_rights are triage CATEGORIES, NOT ClauseType values and NOT tagger outputs —
# the tagger emits only the four ClauseType.value keys above.
```

An ordered tuple (not a dict) makes the tie-break order explicit and stable.

## 2. Tagger (`app/graph/nodes/splitters/clause_typer.py`, NEW)

Pure, deterministic, no I/O, no Ollama:

```python
from typing import Optional
from app.graph.state import ClauseType
import app.config as _config

DETERMINISTIC_CLAUSE_TYPING_ENABLED = _config.DETERMINISTIC_CLAUSE_TYPING_ENABLED
DETERMINISTIC_CLAUSE_TYPE_PATTERNS = _config.DETERMINISTIC_CLAUSE_TYPE_PATTERNS
# read by BARE NAME so tests can monkeypatch the module attrs.

def infer_clause_type(text: Optional[str]) -> Optional[ClauseType]:
    """Best-effort deterministic clause type from text, or None if no confident match.
    Scans the ordered pattern map; first type with any phrase substring-present in the
    lowercased text wins (fixed order = deterministic multi-match tie-break, EC-1)."""
    if not text or not text.strip():
        return None                                   # EC-2
    low = text.lower()
    for ctype_value, phrases in DETERMINISTIC_CLAUSE_TYPE_PATTERNS:
        if any(p in low for p in phrases):
            try:
                return ClauseType(ctype_value)
            except ValueError:
                continue                              # defensive: skip a bad config key
    return None
```

Substring matching on lowercased text is intentionally simple and deterministic (AC-6). Precision is
tuned via the phrase list (conservative multi-word phrases), measured by AC-7 — not by matcher cleverness.

## 3. Wire-in (`clause_splitter_agent.py::_build_return`)

Add module aliases next to the existing `CLAUSE_SPLITTER_LLM_MAX_CLAUSES` / `MAX_CLAUSES_LIMIT` block:

```python
from app.graph.nodes.splitters.clause_typer import infer_clause_type
DETERMINISTIC_CLAUSE_TYPING_ENABLED = _config.DETERMINISTIC_CLAUSE_TYPING_ENABLED
```

In `_build_return`, at the existing `converted_type = _to_clause_type(c.clause_type)` (line ~168),
fill only when the LLM left it `None`:

```python
converted_type = _to_clause_type(c.clause_type)
if converted_type is None and DETERMINISTIC_CLAUSE_TYPING_ENABLED:
    converted_type = infer_clause_type(c.text)      # fill-None-only (D4); LLM type always wins
```

`_build_return` is the **single convergence point** for both the LLM-skipped path
(`refined = regex_clauses`, line ~115) and the LLM-failed→regex-fallback path (`refine_with_llm`
returns `regex_clauses` on any exception) — so both large-doc regimes are covered (spec-reviewer
confirmed). Nothing else in the node changes; `type_counts` (line ~175) naturally reflects the filled
types. Read `DETERMINISTIC_CLAUSE_TYPING_ENABLED` by bare name so the reversibility test can monkeypatch.

## 4. Control-flow / correctness

- **Fill-None-only (D4):** the guard `converted_type is None` guarantees an LLM-assigned type is never
  overwritten — small/typed docs are unchanged except for clauses the LLM already left `None`.
- **No downstream shape change (§2.3):** the clause record's `clause_type` field type is unchanged (a
  `ClauseType` or `None`); the recall floor's `ct in SELF_RAG_RECALL_FLOOR_TYPES` now simply sees a
  non-`None` value for typed clauses. RiskScore/redline/report key off `final_status`, not `clause_type`.
- **Reversibility (D5):** flag `False` ⇒ the `if` is skipped ⇒ output identical to today. Empty
  pattern map ⇒ `infer_clause_type` always returns `None` ⇒ same as flag off.
- **No new failure mode:** the tagger cannot raise on normal input (guards empty text; `ClauseType()`
  wrapped in try/except); it only ever adds a type or leaves `None`.
- **Small-doc hidden coupling (explicit):** on docs where the LLM refinement DID run but left some
  clauses `clause_type=None`, those clauses now also get deterministically typed. This is intended
  (fill-None-only, D4) but is a behavior change beyond the large-doc regime — it is covered by AC-3/AC-4
  and guarded by running the FULL suite (pin any surprised existing splitter test the way 027 did,
  rather than weakening it).

## 5. Test plan (TDD, `tests/unit/`)

Failing-first per §7. All backend tests are **offline** (no Ollama) — the tagger is pure.

- **AC-1 (`test_clause_typer.py`):** `infer_clause_type` returns `ClauseType.LIABILITY` for a
  limitation-of-liability / indemnification snippet; `TERMINATION` for a termination/survival snippet;
  `INTELLECTUAL_PROPERTY` for an IP-assignment/ownership snippet; `CONFIDENTIALITY` for an NDA snippet;
  `None` for neutral boilerplate (e.g. a notices/definitions clause). **Negative controls (lock in the
  conservative patterns):** a definitions/representation clause that merely *mentions* "patent",
  "copyright" or "trademark" in passing → `None` (NOT `intellectual_property`); an anti-assignment
  clause ("no assignment of this Agreement without consent") → `None` (NOT `intellectual_property`).
- **AC-2 (`test_clause_typer.py` + integration):** multi-match text resolves by the fixed map order
  (deterministic); empty/whitespace text → `None`.
- **AC-6:** repeated calls on the same input return identical results; no I/O/RNG (assert via a pure
  call, and that patching the map changes the result deterministically).
- **AC-3 (`test_clause_splitter_agent.py`):** drive `_build_return` (or the node) with regex-only
  clauses (`clause_type=None`) where one clause has liability language → output has that clause typed
  `liability`; an all-neutral set stays all-`None`. Assert an LLM-assigned type on another clause is
  **not** overwritten (AC-2 precedence at the integration level).
- **AC-4 reversibility (`test_clause_splitter_agent.py`):** monkeypatch
  `clause_splitter_agent.DETERMINISTIC_CLAUSE_TYPING_ENABLED = False` → previously-`None` clauses stay
  `None` (identical to today).
- **AC-4 config (`test_config.py`):** `DETERMINISTIC_CLAUSE_TYPING_ENABLED` is a `bool`; every key in
  `DETERMINISTIC_CLAUSE_TYPE_PATTERNS` is a valid `ClauseType.value` and a subset of
  `SELF_RAG_RECALL_FLOOR_TYPES` (guards against a floor-irrelevant or typo'd key), mirroring
  `test_self_rag_recall_floor_types_are_valid_clause_types`.
- **AC-5:** confirm (by review of the diff) only the six allow-listed files change; run whole `pytest`
  green. No new floor-type-discard breakers are expected (the tagger only *adds* types on
  previously-`None` clauses; existing splitter tests assert `None`/LLM types on small inputs where the
  gate doesn't fire — verify by running the suite, pin any surprise the same way 027 did).

## 6. Measurement (AC-7)

After backend green, re-run the 041/026 harness from `backend/` (delivery off via
`app.delivery.delivery_step.MCP_DELIVERY_ENABLED=False`): `python -X utf8 -m eval.harness.run` then
`python -X utf8 -m eval.harness.score eval/runs/<ts>` (exact entry points confirmed in tasks). Record
**before vs after**: clause_type non-`None` coverage, recall, miss rate, precision, false-flag rate,
severity accuracy, and the Self-RAG seen-but-discarded diagnostic.

- **Subset rule (pins spec AC-7's "representative"):** if a full 32-doc live run doesn't fit the
  deadline, run the subset = **all corpus docs whose regex clause count > `CLAUSE_SPLITTER_LLM_MAX_CLAUSES`
  (40)** — i.e. exactly the large-doc regime where the fix acts (baseline typing ~0). This is
  reproducible and targets the population the fix changes. Reuse the cached run
  `eval/runs/20260817-190549` as the "before" baseline where docs are unchanged; the "after" is a
  fresh run with the flag on.
- **Positive-half control (the gap the 041 experiment left):** confirm at least one previously-missed
  floor-type clause (e.g. a `cap_on_liability` in CybergyHoldings) is now typed `liability`, validated
  **via the recall floor** (record shape `relevance=True, isrel=None, issup=None`), and flips fn→tp.
  `scripts/exp_clausetype_floor.py`'s rescue-trace already reports the floor signature — reuse it.
- Report the recall gain **and** the false-flag cost honestly (D3); the candidate-labeled corpus is
  indicative, not authoritative (026/041 framing).
- **MERGE GATE on the measured precision cost (concrete pass/fail, D3):** the feature ships flag-ON
  (default `True`) only if, on the large-doc subset, (i) recall RISES, and (ii) the net trade is
  favorable — specifically the false-flag rate rises by **no more than +5 percentage points** AND the
  recall gain (pp) is **≥ the false-flag gain (pp)**. If either is violated, before merge either tighten
  the phrase map and re-measure, or ship with `DETERMINISTIC_CLAUSE_TYPING_ENABLED=False` as the default
  (feature still available, off) pending phrase tuning. The trade must be a MEASURED net win, not assumed.

## 7. Risks / limitations
- **D3 precision cost:** a conservative tagger can still mistype (e.g. a clause that merely mentions
  "confidential" in passing) and then be floor-validated → a false flag. Measured by AC-7; remedy is
  tightening phrases or narrowing the map/floor (documented options, not a code risk).
- **Coverage ceiling:** substring phrase-matching won't type every clause; unmatched clauses stay
  `None` (no floor) — an acceptable partial win vs today's ~0 coverage on large docs. Broadening the
  map or the fragile-LLM-typing fix (feature 042 §6 future work) can extend it later.
- **Live harness needs Ollama up** (qwen3:8b + bge-m3) — same constraint as 026/041; only AC-7 needs it.
