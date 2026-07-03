# ClauseSplitterAgent Technical Plan

## Git Branch

`feature/004-clause-splitter-agent` — branching workflow per `specs/000-constitution.md` §11.

---

## 1. Overview

This plan details how to implement the ClauseSplitterAgent (Node 2) as specified in `specs/004-clause-splitter-agent/spec.md`. The ClauseSplitterAgent segments the full extracted text from IngestAgent (Node 1) into discrete, individually addressable clauses using a hybrid regex + LLM approach, populating the `clauses` slice of `ContractState` defined in `specs/001-contract-state-schema.md`.

All configurable thresholds live in `app/config.py` per the constitution's §3 (Configurable Thresholds Rule). The node function returns only the state keys it actually updates per §5 (Partial-Update Rule). The `extracted_text` field is read from state but never re-written — only the `clauses` dict (plus pipeline metadata) is returned.

**Resolved design decisions** (from spec §7):
- **Clause IDs**: Positional — `"clause_001"`, `"clause_002"`, etc.
- **LLM output format**: JSON mode via `format="json"` in Ollama call, with explicit JSON schema in the prompt
- **Clause type inference**: Same LLM call as boundary refinement (single round-trip)
- **Timeout**: 120s starting value, benchmark on first real integration test

---

## 2. Files to Create / Modify

### Shared Config Module

#### [MODIFY] `backend/app/config.py`

Add the ClauseSplitterAgent constants below the existing IngestAgent thresholds:

```python
# ── ClauseSplitterAgent thresholds ─────────────────────────────────────────────
# Source: specs/004-clause-splitter-agent/spec.md §6

OLLAMA_MODEL_NAME: str = "qwen3:14b"
# The Ollama model identifier for LLM calls in the pipeline.
# Qwen3 14B runs locally via Ollama — no cloud API cost.
# Fits in ~10GB VRAM at Q4_K_M quantization (any 12–16GB GPU).
# Used by ClauseSplitterAgent for semantic refinement and clause_type inference.
# Future nodes (CRAG, Self-RAG, etc.) may also use this constant.

CLAUSE_SPLITTER_TIMEOUT_SECONDS: int = 120
# Wall-clock timeout for the LLM call in ClauseSplitterAgent.
# Set to 120s as a conservative starting value — Qwen3 14B running locally
# is fast on GPU (~20–40 tok/sec) but needs headroom for long contracts
# and CPU-only or lower-end hardware — per constitution §9.
# On timeout, the node falls back to regex-only output.
# Benchmark on first real integration test and tune down if possible.

MIN_CLAUSE_LENGTH: int = 100
# Minimum character count for extracted_text to be worth splitting.
# Documents shorter than this are treated as a single clause.
# 100 chars ≈ 1–2 short sentences — below this, splitting is meaningless.

MAX_CLAUSES_LIMIT: int = 500
# Maximum number of clauses the node will produce.
# Documents exceeding this are truncated with a logged warning.
# 500 is generous — a typical 50-page contract has 100–200 clauses.
# This is a safety valve against pathological regex matches on unusual
# formatting (e.g. every line treated as a separate clause).
```

---

### Splitters Package

#### [NEW] `backend/app/graph/nodes/splitters/__init__.py`

Exports the shared `ClauseBoundary` dataclass used by both splitter modules, following the same pattern as `parsers/__init__.py` (which exports `ParseResult`):

```python
from dataclasses import dataclass
from typing import Optional


@dataclass
class ClauseBoundary:
    """A single detected clause boundary with its metadata.

    Attributes:
        clause_id: Stable positional key (e.g. "clause_001").
        text: The full text content of the clause.
        position: 1-indexed position in the document.
        section_number: Detected section number (e.g. "1.2", "Article 5"),
            or None if no section marker detected.
        clause_type: Raw string clause type before enum conversion
            (e.g. "definitions", "payment"), or None if not inferred.
    """

    clause_id: str
    text: str
    position: int
    section_number: Optional[str]
    clause_type: Optional[str]  # raw string before ClauseType enum conversion
```

This lives here (rather than in either splitter module) so that `regex_splitter.py` and `llm_refiner.py` can both import it without creating a cross-dependency between modules — same rationale as `ParseResult` in `parsers/__init__.py`.

---

#### [NEW] `backend/app/graph/nodes/splitters/regex_splitter.py`

Responsible for Step 1: the regex pre-pass that detects clause boundaries using structural markers. No LLM dependency — independently testable.

**Public interface:**

```python
from app.graph.nodes.splitters import ClauseBoundary

def split_by_regex(text: str) -> list[ClauseBoundary]:
    """Split contract text into clauses using regex-detected structural markers.

    Strategy:
    1. Compile the pattern set (see below) into a single alternation regex.
    2. Find all match positions in the text.
    3. If no structural markers are found, fall back to paragraph splitting
       (double-newline boundaries).
    4. If paragraph splitting also produces zero boundaries (single unbroken
       block), return the entire text as a single clause.
    5. Extract text between consecutive boundaries.
    6. Assign positional clause_ids ("clause_001", "clause_002", ...).
    7. Extract section_number from the matched marker (if any).
    8. Set clause_type = None (regex pass does not infer types).

    Returns:
        List of ClauseBoundary objects, sorted by position.
        Always returns at least 1 clause for non-empty input.
        Returns empty list for empty input.
    """
```

**Pattern set** — the regex pre-pass must handle at minimum:

```python
CLAUSE_PATTERNS = [
    # Numbered sections: "1.", "1.1", "1.1.1", etc.
    r"(?m)^[ \t]*(\d+(?:\.\d+)*)\.?\s",

    # "Article N" / "ARTICLE N" (case-insensitive)
    r"(?mi)^[ \t]*(article\s+\d+)",

    # "Section N" / "SECTION N" (case-insensitive)
    r"(?mi)^[ \t]*(section\s+\d+(?:\.\d+)*)",

    # "§N" / "§ N"
    r"(?m)^[ \t]*(§\s*\d+(?:\.\d+)*)",

    # Lettered sections: "(a)", "(b)", "(i)", "(ii)", etc.
    r"(?m)^[ \t]*(\([a-z]+\)|\([ivxlcdm]+\))\s",

    # Lettered with dot: "a.", "b.", etc. (only at start of line)
    r"(?m)^[ \t]*([a-z])\.[ \t]",

    # Common contract headers (case-insensitive)
    r"(?mi)^[ \t]*(WHEREAS|NOW\s+THEREFORE|IN\s+WITNESS\s+WHEREOF|RECITALS?|BACKGROUND)",
]

# Paragraph-based fallback: double newline
PARAGRAPH_PATTERN = r"\n\s*\n"
```

**Section number extraction logic:**

When a structural marker is matched, the section number is extracted from the match group:
- `"1.2.3"` → `section_number = "1.2.3"`
- `"Article 5"` → `section_number = "Article 5"`
- `"Section 3.1"` → `section_number = "Section 3.1"`
- `"§2"` → `section_number = "§2"`
- `"WHEREAS"` → `section_number = "WHEREAS"`
- `"(a)"` → `section_number = "(a)"`
- Paragraph split (no marker) → `section_number = None`

**Identifying which pattern matched**: since the pattern set is combined into a single alternation with 7 capture groups, "extract the match group" requires knowing which alternative fired. Use **named groups** (`(?P<name>...)`) and read `match.lastgroup` / the first non-`None` entry in `match.groupdict()`, or iterate `match.groups()` for the first non-`None` value. Do not depend on a fixed positional group index across the alternation. This is driven out by the `test_split_section_number_extracted` unit test (tasks.md Task 4/5).

**Empty text handling**: If `text` is empty string, return `[]` immediately.

---

#### [NEW] `backend/app/graph/nodes/splitters/llm_refiner.py`

Responsible for Steps 2+3: LLM semantic refinement of regex-detected boundaries and clause_type inference via Ollama. Uses the `ollama` Python client.

**Public interface:**

```python
from app.graph.nodes.splitters import ClauseBoundary

def refine_with_llm(
    regex_clauses: list[ClauseBoundary],
    timeout_seconds: int,
    model_name: str,
) -> list[ClauseBoundary]:
    """Refine regex-detected clause boundaries using Qwen3 14B via Ollama.

    Sends the regex-detected clauses to the LLM with a prompt asking it to:
    1. Merge fragments that belong to the same clause.
    2. Split run-on segments that contain multiple clauses.
    3. Infer clause_type for each clause from the ClauseType enum.

    Uses format="json" in the Ollama call with an explicit JSON schema
    in the prompt.

    Args:
        regex_clauses: Output from split_by_regex().
        timeout_seconds: Wall-clock timeout for the Ollama call.
        model_name: Ollama model identifier (e.g. "qwen3:14b").

    Returns:
        Refined list of ClauseBoundary objects with updated clause_ids
        (re-numbered sequentially), corrected boundaries, and inferred
        clause_type values.

    Raises:
        No exceptions — all failures are caught internally and trigger
        a fallback to returning regex_clauses unchanged.
    """
```

**The prompt template:**

```python
LLM_PROMPT = """You are a contract clause analysis assistant. You are given a list of clause segments
that were detected by a regex-based pre-pass on a legal contract. Your job is to:

1. REVIEW the clause boundaries. Merge fragments that belong to the same logical clause.
   Split any run-on segments that contain multiple distinct clauses.
2. CLASSIFY each clause into one of these types: "definitions", "payment", "delivery",
   "term", "termination", "confidentiality", "intellectual_property", "liability",
   "force_majeure", "dispute_resolution", "general", "other".
   If you cannot confidently classify a clause, set clause_type to null.

Respond with ONLY a JSON object matching this exact schema — no markdown, no explanation:

{{
  "clauses": [
    {{
      "text": "The full text of the clause",
      "section_number": "1.2" or null,
      "clause_type": "one of the types listed above" or null
    }}
  ]
}}

Rules:
- Preserve ALL original text — do not rewrite, summarize, or omit any clause content.
- Maintain the original document order.
- Every piece of input text must appear in exactly one output clause.
- If a clause has a section number (e.g. "1.2", "Article 5", "§3"), include it.
  If it has no section marker, set section_number to null.
- If you are uncertain about the clause_type, set it to null rather than guessing.

Here are the regex-detected clause segments:

{clauses_json}
"""
```

The `{clauses_json}` placeholder is populated with a JSON array of the regex-detected clauses:

```json
[
  {"index": 1, "section_number": "1", "text": "Definitions. In this Agreement..."},
  {"index": 2, "section_number": "1.1", "text": "\"Affiliate\" means..."},
  ...
]
```

**Ollama call:**

```python
import ollama
import json

response = ollama.chat(
    model=model_name,
    messages=[{"role": "user", "content": prompt}],
    format="json",
    options={"num_predict": 4096},  # cap output tokens
)
result = json.loads(response["message"]["content"])
```

**Timeout enforcement**: Same `concurrent.futures.ThreadPoolExecutor` pattern used by the parsers module in IngestAgent, but with `CLAUSE_SPLITTER_TIMEOUT_SECONDS` (120s default). The Ollama call is submitted to the executor; if it exceeds the timeout, a `TimeoutError` is caught and the function returns `regex_clauses` unchanged.

```python
import concurrent.futures

def refine_with_llm(regex_clauses, timeout_seconds, model_name):
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(_call_ollama, regex_clauses, model_name)
        try:
            refined = future.result(timeout=timeout_seconds)
            return refined
        except concurrent.futures.TimeoutError:
            logger.warning("LLM refinement timed out after %ds, using regex-only output", timeout_seconds)
            return regex_clauses
        except Exception:
            logger.warning("LLM refinement failed, using regex-only output", exc_info=True)
            return regex_clauses
```

**Response parsing and validation:**

1. Parse the JSON response.
2. Validate that `"clauses"` key exists and is a list.
3. Validate each clause has `"text"` (non-empty string).
4. Map `clause_type` strings to valid `ClauseType` enum values — if the string doesn't match any enum value, set to `None`.
5. Re-assign positional `clause_id` values (`"clause_001"`, `"clause_002"`, ...) and `position` (1-indexed).
6. If any validation step fails, log a warning (with the truncated raw response) and return `regex_clauses` unchanged.

**Connection error handling**: If the Ollama server is unreachable (`ConnectionError`, `httpx.ConnectError`, etc.), the exception is caught in the outer `except Exception` block and treated the same as a timeout — regex-only fallback with a warning log.

---

### ClauseSplitterAgent Node

#### [NEW] `backend/app/graph/nodes/clause_splitter_agent.py`

The LangGraph node function. This is the only file that interacts with `ContractState`.

**Public interface:**

```python
import logging

logger = logging.getLogger("contractsentinel.clause_splitter")

def clause_splitter_agent(state: ContractState) -> dict:
    """LangGraph node function for clause splitting.

    Reads: state["extracted_text"], state["document_id"], state["ingest_error"]
    Returns: partial dict with keys:
        clauses, current_node, node_timings
    """
```

**Internal flow:**

```
1. Set current_node = "clause_splitter"
2. Record start_time
3. Defensive check: if state.get("ingest_error") is not None → return {}
   with current_node and node_timings only
4. Read extracted_text from state
5. If extracted_text is empty string → return empty clauses dict, log warning
6. If len(extracted_text) < MIN_CLAUSE_LENGTH → build a single-clause list and
   pass it through the SAME refine_with_llm call (step 9) for clause_type
   inference; skip steps 7–8. (Latency tradeoff accepted — see tasks.md Task 9
   step 5 and spec §4.2.)
7. Run regex pre-pass: regex_clauses = split_by_regex(extracted_text)
8. Pre-LLM cap: if len(regex_clauses) > MAX_CLAUSES_LIMIT → truncate to
   MAX_CLAUSES_LIMIT, log warning (bounds the prompt size fed to the LLM)
9. Run LLM refinement: refined_clauses = refine_with_llm(
       regex_clauses, CLAUSE_SPLITTER_TIMEOUT_SECONDS, OLLAMA_MODEL_NAME)
9b. Post-refinement re-clamp: the LLM may split run-ons, so len(refined_clauses)
    can exceed MAX_CLAUSES_LIMIT even after step 8. If so, truncate to
    MAX_CLAUSES_LIMIT and re-number clause_id/position contiguously, log warning.
    This guarantees the spec §6 invariant "maximum number of clauses the node
    will PRODUCE" (see spec §4.6).
10. Convert list[ClauseBoundary] to clauses dict format:
    {
        "clause_001": {
            "text": "...",
            "position": 1,
            "section_number": "1.2" or None,
            "clause_type": ClauseType.PAYMENT or None,
        },
        ...
    }
11. Log evaluation metrics (see Logging section below)
12. Record elapsed time in node_timings
13. Return partial dict: {"clauses": ..., "current_node": ..., "node_timings": ...}
```

**clause_type enum conversion** (step 10):

```python
from app.graph.state import ClauseType

def _to_clause_type(raw: Optional[str]) -> Optional[ClauseType]:
    """Convert raw string to ClauseType enum, or None if invalid/absent."""
    if raw is None:
        return None
    try:
        return ClauseType(raw)
    except ValueError:
        return None
```

**Return shape (success):**

```python
return {
    "clauses": clauses_dict,
    "current_node": "clause_splitter",
    "node_timings": {"clause_splitter": elapsed},
}
```

**Return shape (defensive — ingest_error set or empty text):**

```python
return {
    "clauses": {},
    "current_node": "clause_splitter",
    "node_timings": {"clause_splitter": elapsed},
}
```

Note: Unlike IngestAgent, ClauseSplitterAgent does NOT set `error_count` on its failure paths because all its failure modes (LLM timeout, malformed response, Ollama down) result in graceful degradation to regex-only output, not pipeline errors. The pipeline continues successfully with potentially lower-quality clause boundaries.

---

### Graph Wiring

#### [MODIFY] `backend/app/graph/builder.py`

Add the `clause_splitter` node and update the routing so `route_after_ingest` routes to the actual `clause_splitter` node instead of the current END stub.

```python
from app.graph.nodes.clause_splitter_agent import clause_splitter_agent

# Inside build_graph():
graph.add_node("clause_splitter", clause_splitter_agent)

# Update conditional edges:
graph.add_conditional_edges(
    "ingest_agent",
    route_after_ingest,
    {
        "end": END,
        "clause_splitter": "clause_splitter",  # was END temporarily
    },
)

# Clause splitter → next node (placeholder until feature-005)
graph.add_edge("clause_splitter", END)  # → END temporarily
```

The existing `route_after_ingest` function is unchanged — it already returns `"clause_splitter"` on the success path.

---

### Unit Tests

#### [NEW] `backend/tests/unit/test_regex_splitter.py`

Tests for `split_by_regex()` — no LLM dependency, no mocks needed:

| Test | Verifies |
|------|----------|
| `test_split_numbered_sections` | Standard numbered contract (`"1. ...\n2. ...\n3. ..."`) produces correct clause boundaries |
| `test_split_nested_numbers` | Nested numbering (`"1.\n1.1\n1.2\n2.\n2.1"`) produces one clause per number |
| `test_split_article_headers` | `"Article 1 ...\nArticle 2 ..."` produces correct boundaries |
| `test_split_section_headers` | `"Section 1 ...\nSection 2 ..."` produces correct boundaries |
| `test_split_section_symbol` | `"§1 ...\n§2 ..."` produces correct boundaries |
| `test_split_lettered_sections` | `"(a) ...\n(b) ..."` produces correct boundaries |
| `test_split_contract_headers` | `"WHEREAS ...\nNOW THEREFORE ..."` produces correct boundaries |
| `test_split_mixed_numbering` | Mixed patterns in one document — best-effort, no crash |
| `test_split_paragraph_fallback` | No structural markers → falls back to `\n\n` splitting |
| `test_split_single_block_fallback` | No markers AND no `\n\n` → entire text as one clause |
| `test_split_empty_text` | Empty string → empty list |
| `test_split_clause_ids_positional` | Clause IDs are `"clause_001"`, `"clause_002"`, etc. |
| `test_split_position_1_indexed` | Position values are 1, 2, 3, ... (no gaps) |
| `test_split_section_number_extracted` | Section numbers correctly extracted from matched markers |
| `test_split_clause_type_always_none` | `clause_type` is always `None` from regex pass |
| `test_split_deterministic` | Same input → same output (run twice, compare) |

#### [NEW] `backend/tests/unit/test_llm_refiner.py`

Tests for `refine_with_llm()` — uses mocks for the Ollama client, does NOT require a running Ollama instance:

| Test | Verifies |
|------|----------|
| `test_refine_merges_fragments` | LLM response that merges two regex fragments into one clause is correctly parsed |
| `test_refine_splits_runon` | LLM response that splits a run-on clause into two is correctly parsed |
| `test_refine_infers_clause_type` | `clause_type` values from LLM response are mapped to `ClauseType` enum values |
| `test_refine_null_clause_type_accepted` | LLM returns `null` for `clause_type` → `None` in output |
| `test_refine_invalid_clause_type_becomes_none` | LLM returns unrecognised type string → `None` |
| `test_refine_clause_ids_renumbered` | Output clause IDs are re-numbered sequentially after merge/split |
| `test_refine_timeout_returns_regex_output` | Timeout → returns input `regex_clauses` unchanged |
| `test_refine_malformed_json_returns_regex_output` | LLM returns invalid JSON → fallback to regex output, warning logged |
| `test_refine_missing_clauses_key_returns_regex_output` | LLM returns JSON without `"clauses"` key → fallback |
| `test_refine_empty_clause_text_returns_regex_output` | LLM returns clause with empty `"text"` → fallback |
| `test_refine_connection_error_returns_regex_output` | Ollama unreachable → fallback, warning logged |
| `test_refine_preserves_all_text` | All input text appears in output (no text dropped by LLM) |
| `test_refine_json_mode_used` | Ollama call includes `format="json"` parameter |

**Mocking strategy**: All tests use `unittest.mock.patch("ollama.chat")` to mock the Ollama client. The mock returns pre-crafted JSON responses. No real Ollama instance is needed.

#### [NEW] `backend/tests/unit/test_clause_splitter_agent.py`

Tests for the `clause_splitter_agent()` node function:

| Test | Verifies |
|------|----------|
| `test_splitter_success_basic` | Full success path: correct clauses dict with required fields |
| `test_splitter_ingest_error_returns_empty` | `ingest_error` set → empty clauses dict, no regex/LLM calls |
| `test_splitter_empty_text_returns_empty` | Empty `extracted_text` → empty clauses dict, warning logged |
| `test_splitter_short_text_single_clause` | Text < `MIN_CLAUSE_LENGTH` → single clause |
| `test_splitter_max_clauses_truncated` | Regex produces > `MAX_CLAUSES_LIMIT` clauses → truncated |
| `test_splitter_partial_update_only` | Return dict contains ONLY `clauses`, `current_node`, `node_timings` |
| `test_splitter_clause_type_enum_conversion` | Raw `clause_type` strings converted to `ClauseType` enum values |
| `test_splitter_clause_type_none_preserved` | `None` clause_type preserved (not forced) |
| `test_splitter_position_sequential` | Positions are 1-indexed, sequential, contiguous |
| `test_splitter_required_fields_present` | Every clause has `text`, `position`, `section_number`, `clause_type` |
| `test_splitter_node_timing_recorded` | `node_timings["clause_splitter"]` is a positive float |
| `test_splitter_current_node_set` | `current_node` is `"clause_splitter"` |
| `test_splitter_no_error_count_on_fallback` | LLM fallback path does NOT set `error_count` |

**Mocking strategy**: Tests mock both `split_by_regex` and `refine_with_llm` at the module level to control inputs/outputs without needing real text processing or an Ollama instance.

#### [MODIFY] `backend/tests/unit/test_config.py`

Add tests for the new ClauseSplitterAgent constants:

| Test | Verifies |
|------|----------|
| `test_clause_splitter_constants_match_spec` | `OLLAMA_MODEL_NAME`, `CLAUSE_SPLITTER_TIMEOUT_SECONDS`, `MIN_CLAUSE_LENGTH`, `MAX_CLAUSES_LIMIT` match spec §6 values |
| `test_clause_splitter_constants_correct_types` | Type checking: `str` for model name, `int` for timeout/length/limit |

---

### Integration Tests

#### [NEW] `backend/tests/integration/test_clause_splitter_graph.py`

Tests the ClauseSplitterAgent wired into the LangGraph graph:

| Test | Verifies |
|------|----------|
| `test_graph_ingest_then_clause_splitter_success` | Graph runs IngestAgent → ClauseSplitterAgent on a valid PDF, reaches END with populated `clauses` dict |
| `test_graph_ingest_error_skips_clause_splitter` | Graph runs IngestAgent on unsupported format → short-circuits to END without reaching ClauseSplitterAgent |
| `test_graph_clause_splitter_llm_fallback` | With mocked Ollama (timeout), ClauseSplitterAgent produces regex-only output and graph completes |
| `test_graph_checkpointing_after_clause_splitter` | State is checkpointed after ClauseSplitterAgent completes |

**Note**: Integration tests that involve the LLM will mock `ollama.chat` to avoid requiring a running Ollama instance. A separate manual integration test (not in the automated suite) can be run with a real Ollama instance once it's set up.

---

## 3. Dependency & Import Map

```
app/config.py
    └── (no imports — pure constants)

app/graph/nodes/splitters/__init__.py
    └── dataclasses, typing (stdlib only — defines ClauseBoundary)

app/graph/nodes/splitters/regex_splitter.py
    ├── re (stdlib)
    ├── app.graph.nodes.splitters (ClauseBoundary)
    └── (no external dependencies)

app/graph/nodes/splitters/llm_refiner.py
    ├── json, logging, concurrent.futures (stdlib)
    ├── ollama (Python client)
    ├── app.graph.nodes.splitters (ClauseBoundary)
    └── app.graph.state (ClauseType — for validation only)

app/graph/nodes/clause_splitter_agent.py
    ├── time, logging (stdlib)
    ├── app.graph.state (ContractState, ClauseType)
    ├── app.graph.nodes.splitters.regex_splitter (split_by_regex)
    ├── app.graph.nodes.splitters.llm_refiner (refine_with_llm)
    └── app.config — imported AS A MODULE (`import app.config as _config`),
                     NOT `from app.config import ...`. The four tunables
                     (OLLAMA_MODEL_NAME, CLAUSE_SPLITTER_TIMEOUT_SECONDS,
                     MIN_CLAUSE_LENGTH, MAX_CLAUSES_LIMIT) are re-exposed as
                     module-level names and read by bare name, mirroring the
                     IngestAgent precedent (ingest_agent.py:33,44,78). This is
                     required so tests can monkeypatch them on the node module;
                     `from app.config import` would bind the values at import
                     time and defeat monkeypatching (see tasks.md Task 9).

app/graph/builder.py
    ├── langgraph.graph (StateGraph, END)
    ├── app.graph.state (ContractState)
    ├── app.graph.nodes.ingest_agent (ingest_agent)
    └── app.graph.nodes.clause_splitter_agent (clause_splitter_agent)
```

---

## 4. Implementation Order

Following TDD per constitution §7 — tests are written and confirmed failing before implementation.

| Step | Action | Files |
|------|--------|-------|
| 1 | Write config tests for new constants (confirm failing) | `tests/unit/test_config.py` |
| 2 | Add ClauseSplitterAgent constants to config | `app/config.py` |
| 3 | Run config tests (confirm passing) | — |
| 4 | Implement `ClauseBoundary` dataclass in splitters package | `app/graph/nodes/splitters/__init__.py` |
| 5 | Write unit tests for regex splitter (confirm failing) | `tests/unit/test_regex_splitter.py` |
| 6 | Implement regex splitter | `app/graph/nodes/splitters/regex_splitter.py` |
| 7 | Run regex splitter tests (confirm passing) | — |
| 8 | Write unit tests for LLM refiner (confirm failing) | `tests/unit/test_llm_refiner.py` |
| 9 | Implement LLM refiner | `app/graph/nodes/splitters/llm_refiner.py` |
| 10 | Run LLM refiner tests (confirm passing) | — |
| 11 | Write unit tests for clause_splitter_agent node (confirm failing) | `tests/unit/test_clause_splitter_agent.py` |
| 12 | Implement clause_splitter_agent node function | `app/graph/nodes/clause_splitter_agent.py` |
| 13 | Run clause_splitter_agent tests (confirm passing) | — |
| 14 | Update graph builder (add clause_splitter node, update routing) | `app/graph/builder.py` |
| 15 | Write and run integration tests | `tests/integration/test_clause_splitter_graph.py` |
| 16 | Full test suite pass (all existing + new tests) | all tests |

> **Note on Step 4**: `ClauseBoundary` in `splitters/__init__.py` is a shared type (like `ParseResult` in `parsers/__init__.py`) — it is a data structure, not feature logic, so it does not require its own TDD cycle. It is implemented before the splitter tests because those tests import it.

---

## 5. Design Decisions & Rationale

### Why regex + LLM hybrid instead of LLM-only?

1. **Cost**: The regex pre-pass is free (no LLM tokens). LLM-only would burn tokens on every document, even structurally obvious ones.
2. **Reliability**: Regex is deterministic. LLM output varies between calls. The regex pass provides a reliable baseline that the LLM only needs to improve, not replace.
3. **Graceful degradation**: If the LLM is unavailable (Ollama down, timeout, malformed response), the regex output is still usable. LLM-only would mean total failure.
4. **Speed**: Regex runs in milliseconds. The LLM call is the latency bottleneck. Doing less work in the LLM (refinement, not primary segmentation) reduces prompt size and output token count.

### Why separate `regex_splitter.py` and `llm_refiner.py` modules?

1. **Independent testability**: Regex splitter tests need no mocks, no Ollama, no network. LLM refiner tests use mocks but are focused on response parsing, timeout handling, and fallback logic.
2. **Follows the parsers pattern**: `pdf_parser.py` and `docx_parser.py` are separate modules imported by `ingest_agent.py`. Similarly, `regex_splitter.py` and `llm_refiner.py` are separate modules imported by `clause_splitter_agent.py`.
3. **Replaceability**: If a better regex strategy or a different LLM is needed later, only one module changes.

### Clause ID scheme: positional (`"clause_001"`)

Decided in spec §7 (Resolved Question 1). Positional IDs provide:
- Uniform format across all document types (numbered, prose, mixed)
- No collision risk (section numbers can repeat)
- Predictable format for downstream nodes (CRAG retrieval uses clause_id to key evidence)
- Section numbers preserved in the `section_number` field for display

### JSON mode via `format="json"`

Decided in spec §7 (Resolved Question 2). JSON mode is used because:
- The `ollama` Python client supports `format="json"` for Qwen3 14B
- Eliminates fragile free-text parsing of LLM responses
- The prompt includes an explicit JSON schema, making the contract clear
- Fallback to regex-only output if JSON parsing fails provides safety

### Same LLM call for boundary refinement and clause_type inference

Decided in spec §7 (Resolved Question 3). Combined call because:
- Halves latency (one Ollama round-trip instead of two)
- The LLM needs to read each clause's text anyway — inferring type simultaneously is natural
- The prompt is manageable in complexity (review boundaries + classify from a 12-value enum)
- Failure of the combined call falls back cleanly to regex-only with `clause_type = None`

### `ClauseBoundary` lives in `splitters/__init__.py`

Same rationale as `ParseResult` in `parsers/__init__.py`: both `regex_splitter.py` and `llm_refiner.py` produce `ClauseBoundary` objects. Placing it in the package init avoids cross-dependencies between the two splitter modules.

### No `error_count` increment on ClauseSplitterAgent failures

Unlike IngestAgent (which sets `error_count: 1` on error paths), ClauseSplitterAgent does not increment the pipeline error counter when it falls back to regex-only output. Rationale: the fallback is a graceful degradation (valid output with potentially lower quality), not a pipeline error. The pipeline continues normally. The `error_count` reducer (`operator.add`) should only be incremented for actual errors that compromise pipeline correctness.

### Logging strategy

The ClauseSplitterAgent uses a named logger (`contractsentinel.clause_splitter`) via Python's standard `logging` module. Per spec §8 (Evaluation), the following are logged at `INFO` level on every invocation:

- `clause_count` (int) — number of clauses produced
- `llm_used` (bool) — whether LLM refinement was used vs regex-only fallback
- `llm_latency_seconds` (float or None) — wall-clock time for Ollama call
- `clause_types` (dict) — count of each ClauseType value
- `section_marker_rate` (float) — percentage of clauses with non-None section_number
- `elapsed_seconds` (float) — total node execution time

---

## 6. Risks & Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| Qwen3 14B latency on long contracts | LLM call exceeds 120s timeout on CPU-only or very long contracts | Timeout fallback to regex-only output; logged warning; timeout tunable in config |
| Ollama server not running | `ConnectionError` on LLM call | Caught in `refine_with_llm`'s except block; falls back to regex-only with warning log |
| Regex pre-pass produces too many fragments | Unusual formatting triggers excessive splits (e.g. every line matches a pattern) | `MAX_CLAUSES_LIMIT` truncation with logged warning; LLM refinement may merge excess fragments |
| LLM merging/splitting incorrectly | LLM produces wrong clause boundaries | Downstream nodes (CRAG, Self-RAG) have their own validation. Don't over-engineer correction here — the regex baseline is already usable |
| LLM returns malformed JSON | JSON parsing fails despite `format="json"` | Full fallback to regex-only output; warning logged with truncated raw response |
| Qwen3 14B not pulled in Ollama | Model not available locally | Log clear error message; fall back to regex-only. Documentation should note `ollama pull qwen3:14b` as a setup step |
| `format="json"` not supported for specific Qwen3 14B quantization | Ollama returns error on JSON mode | Caught as general exception; fallback to regex-only. Test with actual Qwen3 14B pull during first integration run |
| Windows vs Unix newline handling | `\r\n` vs `\n` affects regex patterns | Regex patterns use `\n`; the regex splitter should normalize `\r\n` to `\n` at the start of `split_by_regex()` |

---

## 7. Out of Scope for This Plan

- **Nodes 3–7**: Not wired or implemented. `builder.py` routes `clause_splitter` → END.
- **API endpoints**: No FastAPI routes — the graph is exercised via tests only.
- **Database storage**: No SQLite/aiosqlite usage — state exists only in LangGraph's in-memory + checkpoint store.
- **MCP integration**: No Drive/Gmail delivery.
- **Evaluation scripts**: Metrics are logged (via standard Python `logging`) but no eval script is created. That will come with a dedicated eval spec.
- **Privacy/security**: Per Phase 2 deferral in constitution.
- **Non-English contracts**: Phase 1 assumes English only (spec §5.4).
- **`processing_started_at` / `processing_completed_at`**: Pipeline-level timestamps set by the graph invoker, not by any individual node.
