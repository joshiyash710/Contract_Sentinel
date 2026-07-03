# ClauseSplitterAgent Implementation Tasks

Reference documents:
- Spec: `specs/004-clause-splitter-agent/spec.md`
- Plan: `specs/004-clause-splitter-agent/plan.md`
- State schema: `specs/001-contract-state-schema.md`
- Tech stack: `specs/002-tech-stack.md`
- Constitution: `specs/000-constitution.md`

All file paths below are relative to `backend/` unless stated otherwise.

**Workflow reminders:**
- Follow TDD per constitution §7 — write tests, confirm they FAIL, then implement to make them PASS.
- Node returns ONLY the state keys it updates per constitution §5 (Partial-Update Rule): `clauses`, `current_node`, `node_timings`.
- All thresholds live in `app/config.py` per constitution §3 — never hardcode inline.
- Branch: `feature/004-clause-splitter-agent` per constitution §11.

---

## Task 0: Create feature branch

- [ ] From an up-to-date `main`, create and check out `feature/004-clause-splitter-agent`

**Why**: Per constitution §11, every feature is developed on its own branch. IngestAgent (003) is already merged to `main`.

**Verify**: `git branch --show-current` prints `feature/004-clause-splitter-agent`.

**Note**: There are uncommitted 003 test refinements in the working tree (`tests/markers.py`, edits to `conftest.py`, `test_ingest_agent.py`, `test_pdf_parser.py`, `test_ingest_graph.py`). Confirm with the user whether those should be committed to `main` (or a fixup branch) before branching, so 004 starts from a clean tree.

---

## Task 1: Write config tests for ClauseSplitter constants (confirm FAILING)

- [ ] Open `tests/unit/test_config.py` (created in feature 003)
- [ ] Add 2 new test functions for the ClauseSplitterAgent constants:

```python
def test_clause_splitter_constants_match_spec():
    """Verify ClauseSplitterAgent constants match specs/004 §6."""
    from app.config import (
        OLLAMA_MODEL_NAME,
        CLAUSE_SPLITTER_TIMEOUT_SECONDS,
        MIN_CLAUSE_LENGTH,
        MAX_CLAUSES_LIMIT,
    )
    assert OLLAMA_MODEL_NAME == "qwen3:14b"
    assert CLAUSE_SPLITTER_TIMEOUT_SECONDS == 120
    assert MIN_CLAUSE_LENGTH == 100
    assert MAX_CLAUSES_LIMIT == 500


def test_clause_splitter_constants_correct_types():
    """Verify types: str for model name, int for timeout/length/limit."""
    from app.config import (
        OLLAMA_MODEL_NAME,
        CLAUSE_SPLITTER_TIMEOUT_SECONDS,
        MIN_CLAUSE_LENGTH,
        MAX_CLAUSES_LIMIT,
    )
    assert isinstance(OLLAMA_MODEL_NAME, str)
    assert isinstance(CLAUSE_SPLITTER_TIMEOUT_SECONDS, int)
    assert isinstance(MIN_CLAUSE_LENGTH, int)
    assert isinstance(MAX_CLAUSES_LIMIT, int)
```

**Verify**: Run `python -m pytest tests/unit/test_config.py -v` — the 2 new tests must FAIL with `ImportError` (constants not defined yet). The existing IngestAgent config tests must still PASS. This confirms the TDD cycle.

---

## Task 2: Add ClauseSplitterAgent constants to config

- [ ] Open `app/config.py`
- [ ] Add the following block **below** the existing IngestAgent thresholds (and, to keep related constants grouped, above or beside the CRAG/Self-RAG placeholders — placement is cosmetic):

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
# Conservative starting value — Qwen3 14B is fast on GPU but needs headroom
# for long contracts and CPU-only hardware. On timeout, fall back to
# regex-only output. Benchmark on first real integration test and tune down.

MIN_CLAUSE_LENGTH: int = 100
# Minimum character count for extracted_text to be worth splitting.
# Documents shorter than this are treated as a single clause.

MAX_CLAUSES_LIMIT: int = 500
# Maximum number of clauses the node will produce.
# Documents exceeding this are truncated with a logged warning.
# Safety valve against pathological regex matches on unusual formatting.
```

**Why**: `OLLAMA_MODEL_NAME` is intentionally a shared pipeline-level constant (not ClauseSplitter-specific) because future LLM nodes reuse it. See spec §6 note.

**Verify**: Run `python -m pytest tests/unit/test_config.py -v` — all config tests (IngestAgent + ClauseSplitter) must now PASS.

---

## Task 3: Implement `ClauseBoundary` dataclass in the splitters package

- [ ] Create directory `app/graph/nodes/splitters/`
- [ ] Create file `app/graph/nodes/splitters/__init__.py`
- [ ] Contents:

```python
"""
Shared types for clause-splitter modules.

ClauseBoundary is the return element type for both
regex_splitter.split_by_regex() and llm_refiner.refine_with_llm().
Placing it in the package __init__ (like ParseResult in parsers/__init__.py)
lets regex_splitter.py and llm_refiner.py both import it without creating a
cross-dependency between the two modules.
"""
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

**Why**: `ClauseBoundary` is a shared data structure, not feature logic — like `ParseResult`, it needs no dedicated TDD cycle and is implemented before the splitter tests that import it (plan §4 note on Step 4).

**Verify**: Run the following from `backend/`:
```
python -c "from app.graph.nodes.splitters import ClauseBoundary; b = ClauseBoundary('clause_001', 'hi', 1, None, None); print(b)"
```

---

## Task 4: Write unit tests for the regex splitter (confirm FAILING)

- [ ] Create file `tests/unit/test_regex_splitter.py`
- [ ] The import `from app.graph.nodes.splitters.regex_splitter import split_by_regex` will fail until Task 5 — that is expected for TDD.
- [ ] Write these 16 test functions (per plan §2 test matrix). No mocks, no Ollama, no network:

| Test function | Verifies |
|---------------|----------|
| `test_split_numbered_sections` | `"1. ...\n2. ...\n3. ..."` → one clause per numbered section |
| `test_split_nested_numbers` | `"1.\n1.1\n1.2\n2.\n2.1"` → one clause per number |
| `test_split_article_headers` | `"Article 1 ...\nArticle 2 ..."` → correct boundaries |
| `test_split_section_headers` | `"Section 1 ...\nSection 2 ..."` → correct boundaries |
| `test_split_section_symbol` | `"§1 ...\n§2 ..."` → correct boundaries |
| `test_split_lettered_sections` | `"(a) ...\n(b) ..."` → correct boundaries |
| `test_split_contract_headers` | `"WHEREAS ...\nNOW THEREFORE ..."` → correct boundaries |
| `test_split_mixed_numbering` | Mixed patterns in one doc — best-effort, no crash |
| `test_split_paragraph_fallback` | No structural markers → falls back to `\n\n` splitting |
| `test_split_single_block_fallback` | No markers AND no `\n\n` → entire text as one clause |
| `test_split_empty_text` | `""` → `[]` (empty list) |
| `test_split_clause_ids_positional` | IDs are `"clause_001"`, `"clause_002"`, ... zero-padded to 3 digits |
| `test_split_position_1_indexed` | Positions are 1, 2, 3, ... contiguous, no gaps |
| `test_split_section_number_extracted` | `section_number` correctly extracted from matched markers |
| `test_split_clause_type_always_none` | `clause_type` is always `None` from the regex pass |
| `test_split_deterministic` | Same input → identical output (run twice, compare) |

- [ ] Each test asserts on `List[ClauseBoundary]`. Import `ClauseBoundary` from `app.graph.nodes.splitters`.
- [ ] Recommended shared assertion helper: verify every returned boundary has non-empty `text`, an `int` `position`, and a `clause_id` matching `r"clause_\d{3}"`.

**Verify**: Run `python -m pytest tests/unit/test_regex_splitter.py -v` — all 16 tests must FAIL (ImportError). Confirms the TDD cycle.

---

## Task 5: Implement the regex splitter

- [ ] Create file `app/graph/nodes/splitters/regex_splitter.py`
- [ ] Public interface:

```python
def split_by_regex(text: str) -> list[ClauseBoundary]:
    """Split contract text into clauses using regex-detected structural markers.

    Returns a list of ClauseBoundary objects sorted by position.
    Always returns >= 1 clause for non-empty input; returns [] for empty input.
    """
```

- [ ] **Imports**: `re` (stdlib), `from app.graph.nodes.splitters import ClauseBoundary`. No external deps.
- [ ] **Pattern set** (plan §2) — compile these into the marker-detection logic:

```python
CLAUSE_PATTERNS = [
    r"(?m)^[ \t]*(\d+(?:\.\d+)*)\.?\s",                 # "1.", "1.1", "1.1.1"
    r"(?mi)^[ \t]*(article\s+\d+)",                      # "Article N"
    r"(?mi)^[ \t]*(section\s+\d+(?:\.\d+)*)",            # "Section N", "Section 3.1"
    r"(?m)^[ \t]*(§\s*\d+(?:\.\d+)*)",                   # "§N", "§ N"
    r"(?m)^[ \t]*(\([a-z]+\)|\([ivxlcdm]+\))\s",         # "(a)", "(ii)"
    r"(?m)^[ \t]*([a-z])\.[ \t]",                        # "a.", "b."
    r"(?mi)^[ \t]*(WHEREAS|NOW\s+THEREFORE|IN\s+WITNESS\s+WHEREOF|RECITALS?|BACKGROUND)",
]

PARAGRAPH_PATTERN = r"\n\s*\n"  # double-newline fallback
```

- [ ] **Algorithm** (plan §1, §2):
  1. **Normalize newlines** — replace `\r\n` and `\r` with `\n` at the very start (mitigates Windows `\r\n`, plan §6 risk).
  2. If `text` is empty (or whitespace-only per your judgment) → return `[]` immediately.
  3. Compile the pattern set into a single alternation regex; find all match start positions.
  4. If no structural markers found → fall back to splitting on `PARAGRAPH_PATTERN`.
  5. If paragraph splitting also yields zero boundaries (single unbroken block) → return the whole text as one clause.
  6. Extract the text spanning each pair of consecutive boundaries.
  7. Assign positional `clause_id` (`"clause_001"`, ...) zero-padded to 3 digits, and `position` (1-indexed).
  8. Extract `section_number` from the matched marker group; `None` for paragraph-split clauses.
  9. Set `clause_type = None` (regex never infers types).

- [ ] **Section-number extraction** — this is the one non-trivial part of the splitter. With 7 alternated patterns each carrying a capture group, "extract the group" requires identifying *which* pattern matched. Use one of these approaches (implementer's choice, driven by `test_split_section_number_extracted`):
  - **Recommended**: give each pattern a **named group** (e.g. `(?P<num>...)`, `(?P<article>...)`) and read `match.lastgroup` / the first non-`None` named group from `match.groupdict()`; OR
  - iterate `match.groups()` and take the first non-`None` entry (each pattern contributes exactly one group).
  - Do NOT rely on positional group index alone across the combined alternation — it's brittle when patterns are reordered.
- [ ] **Section-number extraction examples** (plan §2): `"1.2.3"` → `"1.2.3"`, `"Article 5"` → `"Article 5"`, `"§2"` → `"§2"`, `"WHEREAS"` → `"WHEREAS"`, `"(a)"` → `"(a)"`, paragraph split → `None`.

**Verify**: Run `python -m pytest tests/unit/test_regex_splitter.py -v` — all 16 tests must PASS.

---

## Task 6: Write unit tests for the LLM refiner (confirm FAILING)

- [ ] Create file `tests/unit/test_llm_refiner.py`
- [ ] **Mocking strategy**: All tests use `unittest.mock.patch("ollama.chat")` to mock the Ollama client with pre-crafted JSON responses. **No real Ollama instance is required.**
- [ ] Helper: build a small list of input `ClauseBoundary` objects (the "regex output") to pass into `refine_with_llm(...)`.
- [ ] Write these 13 test functions (plan §2 test matrix):

| Test function | Verifies |
|---------------|----------|
| `test_refine_merges_fragments` | LLM response merging two regex fragments into one clause is parsed correctly |
| `test_refine_splits_runon` | LLM response splitting a run-on clause into two is parsed correctly |
| `test_refine_infers_clause_type` | `clause_type` strings map to `ClauseType` enum values |
| `test_refine_null_clause_type_accepted` | LLM `null` clause_type → `None` in output |
| `test_refine_invalid_clause_type_becomes_none` | Unrecognised type string → `None` |
| `test_refine_clause_ids_renumbered` | Output IDs re-numbered sequentially after merge/split |
| `test_refine_timeout_returns_regex_output` | Timeout → returns input `regex_clauses` unchanged |
| `test_refine_malformed_json_returns_regex_output` | Invalid JSON → regex fallback, warning logged |
| `test_refine_missing_clauses_key_returns_regex_output` | JSON without `"clauses"` key → fallback |
| `test_refine_empty_clause_text_returns_regex_output` | Clause with empty `"text"` → fallback |
| `test_refine_connection_error_returns_regex_output` | Ollama unreachable (`ConnectionError`) → fallback, warning logged |
| `test_refine_preserves_all_text` | All input text appears in output (no text dropped) |
| `test_refine_json_mode_used` | Ollama call includes `format="json"` |

- [ ] For timeout simulation: make the mocked `ollama.chat` sleep longer than the passed `timeout_seconds` (pass a tiny `timeout_seconds` like `0.05`), or patch the executor — assert the function returns the input list unchanged.
- [ ] For `test_refine_json_mode_used`: assert on `mock_chat.call_args` that `format="json"` was passed.
- [ ] For warning assertions: use pytest's `caplog` fixture at `WARNING` level.

**Verify**: Run `python -m pytest tests/unit/test_llm_refiner.py -v` — all 13 tests must FAIL (ImportError). Confirms the TDD cycle.

---

## Task 7: Implement the LLM refiner

- [ ] Create file `app/graph/nodes/splitters/llm_refiner.py`
- [ ] **Imports**: `json`, `logging`, `concurrent.futures` (stdlib); `ollama` (client); `from app.graph.nodes.splitters import ClauseBoundary`; `from app.graph.state import ClauseType` (for validation only).
- [ ] **Logger**: `logger = logging.getLogger("contractsentinel.clause_splitter.llm_refiner")`
- [ ] Public interface:

```python
def refine_with_llm(
    regex_clauses: list[ClauseBoundary],
    timeout_seconds: int,
    model_name: str,
) -> list[ClauseBoundary]:
    """Refine regex-detected boundaries via Qwen3 14B (Ollama). Never raises —
    all failures fall back to returning regex_clauses unchanged."""
```

- [ ] **Prompt template** — use the exact `LLM_PROMPT` from plan §2 (asks the LLM to review/merge/split boundaries and classify each clause into the 12 `ClauseType` values or `null`, and to preserve ALL text in original order). Populate `{clauses_json}` with a JSON array of `{"index", "section_number", "text"}` for each regex clause.
- [ ] **Ollama call** (inside a private `_call_ollama(regex_clauses, model_name)` helper):

```python
response = ollama.chat(
    model=model_name,
    messages=[{"role": "user", "content": prompt}],
    format="json",
    options={"num_predict": 4096},
)
result = json.loads(response["message"]["content"])
```

- [ ] **Timeout enforcement** — use the same `concurrent.futures.ThreadPoolExecutor(max_workers=1)` pattern the parsers use:

```python
def refine_with_llm(regex_clauses, timeout_seconds, model_name):
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(_call_ollama, regex_clauses, model_name)
        try:
            return future.result(timeout=timeout_seconds)
        except concurrent.futures.TimeoutError:
            logger.warning("LLM refinement timed out after %ds, using regex-only output", timeout_seconds)
            return regex_clauses
        except Exception:
            logger.warning("LLM refinement failed, using regex-only output", exc_info=True)
            return regex_clauses
```

- [ ] **Response parsing & validation** (inside `_call_ollama`, or a `_parse_response` it calls — so failures raise and are caught by the outer `except`):
  1. Parse JSON response.
  2. Validate `"clauses"` key exists and is a list.
  3. Validate each clause has a non-empty string `"text"`.
  4. Map `clause_type` strings to `ClauseType` — unrecognised string → `None` (do NOT raise). Keep it as a raw string on `ClauseBoundary` OR pre-validate here; final enum conversion happens in the node (Task 10). Recommended: validate here and store only recognised type strings, else `None`.
  5. Re-assign positional `clause_id` (`"clause_001"`, ...) and `position` (1-indexed) to the refined list.
  6. On any validation failure → raise (so the outer handler logs a warning with the **truncated** raw response and returns `regex_clauses`).
- [ ] **CRITICAL — parse/validate INSIDE the submitted callable**: `_call_ollama` (the function submitted to the executor) must perform the JSON parse and all validation itself, so that malformed-JSON / missing-key / empty-text failures raise *inside* `future.result()` and are caught by the outer `except Exception` → regex fallback. Do NOT parse the response after `future.result()` returns — that would place the parse outside the try/except protection and outside the timeout boundary.
- [ ] **Connection errors** (`ConnectionError`, `httpx.ConnectError`, Ollama-down): caught by the outer `except Exception` → regex fallback with warning (same as timeout).

**Verify**: Run `python -m pytest tests/unit/test_llm_refiner.py -v` — all 13 tests must PASS.

---

## Task 8: Write unit tests for the `clause_splitter_agent` node (confirm FAILING)

- [ ] Create file `tests/unit/test_clause_splitter_agent.py`
- [ ] **Mocking strategy**: patch `split_by_regex` and `refine_with_llm` **at the node module level** (`app.graph.nodes.clause_splitter_agent`) to control inputs/outputs without real text processing or Ollama.
- [ ] Helper: `make_splitter_state(extracted_text, ingest_error=None, document_id="doc-1")` returning a minimal state dict with the keys the node reads.
- [ ] Write these 13 test functions (plan §2 test matrix):

| Test function | Verifies |
|---------------|----------|
| `test_splitter_success_basic` | Full success path: correct clauses dict with all required fields |
| `test_splitter_ingest_error_returns_empty` | `ingest_error` set → empty clauses dict; regex/LLM NOT called |
| `test_splitter_empty_text_returns_empty` | Empty `extracted_text` → empty clauses dict, warning logged |
| `test_splitter_short_text_single_clause` | Text < `MIN_CLAUSE_LENGTH` → single clause (`clause_001`, position 1) |
| `test_splitter_max_clauses_truncated` | With `MAX_CLAUSES_LIMIT` monkeypatched small (e.g. 2), a regex output exceeding it → final `clauses` dict has exactly the limit count, warning logged (see monkeypatch note below) |
| `test_splitter_partial_update_only` | Return dict contains ONLY `clauses`, `current_node`, `node_timings` |
| `test_splitter_clause_type_enum_conversion` | Raw `clause_type` strings → `ClauseType` enum values in output |
| `test_splitter_clause_type_none_preserved` | `None` clause_type preserved (not forced to a value) |
| `test_splitter_position_sequential` | Positions are 1-indexed, sequential, contiguous |
| `test_splitter_required_fields_present` | Every clause has `text`, `position`, `section_number`, `clause_type` |
| `test_splitter_node_timing_recorded` | `node_timings["clause_splitter"]` is a positive float |
| `test_splitter_current_node_set` | `current_node == "clause_splitter"` |
| `test_splitter_no_error_count_on_fallback` | LLM-fallback path does NOT set `error_count` |

- [ ] For `test_splitter_ingest_error_returns_empty`: assert the mocked `split_by_regex` / `refine_with_llm` were **not** called (`mock.assert_not_called()`).
- [ ] For `test_splitter_max_clauses_truncated`: monkeypatch the limit on the **node module**, not `app.config` — `monkeypatch.setattr(clause_splitter_agent_module, "MAX_CLAUSES_LIMIT", 2)` — then feed a mocked `split_by_regex` returning e.g. 5 `ClauseBoundary` objects. This avoids building a 500+ element list. Because the node also re-clamps *after* refinement (Task 9 step 8b), have the mocked `refine_with_llm` return its input unchanged so the assertion targets the final clamped count. Assert `len(result["clauses"]) == 2`.
- [ ] For `test_splitter_partial_update_only`: assert forbidden keys absent — e.g. `document_id`, `extracted_text`, `ocr_used`, `report_path`, `evidence_trail`, `mcp_delivery_status`, `error_count`.

**Verify**: Run `python -m pytest tests/unit/test_clause_splitter_agent.py -v` — all 13 tests must FAIL (ImportError). Confirms the TDD cycle.

---

## Task 9: Implement the `clause_splitter_agent` node function

- [ ] Create file `app/graph/nodes/clause_splitter_agent.py`
- [ ] **Imports**: `time`, `logging` (stdlib); `from typing import Optional`; `from app.graph.state import ContractState, ClauseType`; `from app.graph.nodes.splitters.regex_splitter import split_by_regex`; `from app.graph.nodes.splitters.llm_refiner import refine_with_llm`.
- [ ] **CRITICAL — config import pattern (mirror `ingest_agent.py`)**: Do NOT do `from app.config import MAX_CLAUSES_LIMIT, ...`. That binds the *values* into this module at import time, so `monkeypatch.setattr(module, "MAX_CLAUSES_LIMIT", 2)` (Task 8's `test_splitter_max_clauses_truncated`) would have no effect. Instead follow the IngestAgent precedent (`ingest_agent.py:33,44,78`) — import the module and re-expose each tunable as a monkeypatchable module-level name that the function reads by bare name:

```python
import app.config as _config  # import module, not names, to allow monkeypatching in tests

# Re-expose as module-level names so tests can do:
#   monkeypatch.setattr(clause_splitter_agent_module, "MAX_CLAUSES_LIMIT", 2)
OLLAMA_MODEL_NAME = _config.OLLAMA_MODEL_NAME
CLAUSE_SPLITTER_TIMEOUT_SECONDS = _config.CLAUSE_SPLITTER_TIMEOUT_SECONDS
MIN_CLAUSE_LENGTH = _config.MIN_CLAUSE_LENGTH
MAX_CLAUSES_LIMIT = _config.MAX_CLAUSES_LIMIT
```

  The function body must read the bare module-level names (`MAX_CLAUSES_LIMIT`, `MIN_CLAUSE_LENGTH`, `CLAUSE_SPLITTER_TIMEOUT_SECONDS`, `OLLAMA_MODEL_NAME`) — never `_config.MAX_CLAUSES_LIMIT` — otherwise monkeypatching the re-exposed name has no effect (same subtlety as `ingest_agent.py:78`).
- [ ] **Logger**: `logger = logging.getLogger("contractsentinel.clause_splitter")`
- [ ] Public interface:

```python
def clause_splitter_agent(state: ContractState) -> dict:
    """LangGraph Node 2. Reads extracted_text/document_id/ingest_error;
    returns partial dict: clauses, current_node, node_timings."""
```

- [ ] **Internal flow** (plan §2):
  1. `start_time = time.monotonic()`; `current_node = "clause_splitter"`.
  2. **Defensive `ingest_error` check** — if `state.get("ingest_error") is not None` → return empty clauses dict (do NOT call regex or LLM).
  3. Read `extracted_text = state.get("extracted_text", "")`.
  4. If `extracted_text` is empty → log warning, return empty clauses dict.
  5. **Short-text path** — if `len(extracted_text) < MIN_CLAUSE_LENGTH` → build a single-element `[ClauseBoundary("clause_001", extracted_text, 1, None, None)]` and pass it through the **same** `refine_with_llm(...)` call (step 8) so the one clause still gets classified. The merge/split prompt is harmless for a single sub-100-char clause, and the timeout fallback still yields `clause_type=None` on failure. Skip the regex pre-pass (step 6) and the pre-LLM cap (step 7) for this path. **Latency note**: this can cost up to `CLAUSE_SPLITTER_TIMEOUT_SECONDS` to classify one tiny clause; that is the accepted tradeoff for a single code path and honors spec §4.2 ("clause_type inferred by the LLM if available"). Do NOT invent a separate lightweight LLM call.
  6. `regex_clauses = split_by_regex(extracted_text)`.
  7. **Pre-LLM cap** — if `len(regex_clauses) > MAX_CLAUSES_LIMIT` → truncate to `MAX_CLAUSES_LIMIT`, log warning with the original count. This bounds the prompt size fed to the LLM.
  8. `refined = refine_with_llm(regex_clauses, CLAUSE_SPLITTER_TIMEOUT_SECONDS, OLLAMA_MODEL_NAME)`.
     - **8b. Post-refinement re-clamp** — the LLM is allowed to split run-ons (plan §2), so `len(refined)` can exceed `MAX_CLAUSES_LIMIT` even after step 7. Re-clamp: if `len(refined) > MAX_CLAUSES_LIMIT` → truncate to `MAX_CLAUSES_LIMIT` and re-number `clause_id`/`position` contiguously, logging a warning. This guarantees the spec §6 invariant "maximum number of clauses the node will **produce**." See spec §4.6.
  9. Convert `list[ClauseBoundary]` → clauses dict keyed by `clause_id`, each value `{text, position, section_number, clause_type}` with `clause_type` run through the enum converter below.
  10. Log evaluation metrics (see Logging below).
  11. Record `node_timings["clause_splitter"] = time.monotonic() - start_time`.
  12. Return the partial dict.

- [ ] **Enum conversion helper**:

```python
def _to_clause_type(raw: Optional[str]) -> Optional[ClauseType]:
    if raw is None:
        return None
    try:
        return ClauseType(raw)
    except ValueError:
        return None
```

- [ ] **Return shape (success)**:

```python
return {
    "clauses": clauses_dict,
    "current_node": "clause_splitter",
    "node_timings": {"clause_splitter": elapsed},
}
```

- [ ] **Return shape (defensive — ingest_error set or empty text)**: same three keys with `"clauses": {}`.
- [ ] **CRITICAL — no `error_count`**: unlike IngestAgent, this node NEVER sets `error_count`. All failure modes (LLM timeout, malformed response, Ollama down) are graceful degradation to regex-only output, not pipeline errors (plan §5).
- [ ] **Logging** (INFO, per spec §8 / plan §5) on every non-defensive invocation: `clause_count`, `llm_used` (bool), `llm_latency_seconds` (float or None), `clause_types` (dict count per type incl. `None`), `section_marker_rate` (fraction non-None `section_number`), `elapsed_seconds`.

**Verify**: Run `python -m pytest tests/unit/test_clause_splitter_agent.py -v` — all 13 tests must PASS.

---

## Task 10: Wire the node into the graph builder

- [ ] Open `app/graph/builder.py`
- [ ] Add the import: `from app.graph.nodes.clause_splitter_agent import clause_splitter_agent`
- [ ] Register the node: `graph.add_node("clause_splitter", clause_splitter_agent)`
- [ ] Update the conditional edges so the `"clause_splitter"` route maps to the real node instead of `END`:

```python
graph.add_conditional_edges(
    "ingest_agent",
    route_after_ingest,
    {
        "end": END,
        "clause_splitter": "clause_splitter",  # was END temporarily
    },
)

# Clause splitter → END temporarily (until feature-005 adds Node 3)
graph.add_edge("clause_splitter", END)
```

- [ ] `route_after_ingest` is unchanged — it already returns `"clause_splitter"` on the success path.
- [ ] Update the module docstring to reflect that Node 2 is now wired and routes to END temporarily until feature-005.

**Verify**: Run from `backend/`:
```
python -c "from app.graph.builder import build_graph; g = build_graph(); print(type(g))"
```
Should print the compiled graph type without errors.

---

## Task 11: Write and run integration tests

- [ ] Create file `tests/integration/test_clause_splitter_graph.py`
- [ ] Tests exercise IngestAgent → ClauseSplitterAgent through the compiled graph. Mock `ollama.chat` (patch it) so no running Ollama instance is required.
- [ ] Reuse existing conftest fixtures (`sample_pdf_path`, `unsupported_txt_path`) and the inline `{"document_path": ...}` initial-state pattern (matching `test_ingest_graph.py`).
- [ ] Write these 4 test functions (plan §2 test matrix):

| Test function | Verifies |
|---------------|----------|
| `test_graph_ingest_then_clause_splitter_success` | Graph runs IngestAgent → ClauseSplitterAgent on a valid PDF, reaches END with a populated `clauses` dict (>= 1 clause, required fields present) |
| `test_graph_ingest_error_skips_clause_splitter` | IngestAgent on unsupported format → short-circuits to END; ClauseSplitterAgent not reached; assert with `assert not final_state.get("clauses")` (see KeyError note below) |
| `test_graph_clause_splitter_llm_fallback` | With `ollama.chat` mocked to time out/raise, ClauseSplitterAgent produces regex-only output and the graph completes (no crash) |
| `test_graph_checkpointing_after_clause_splitter` | State is checkpointed after ClauseSplitterAgent (SqliteSaver; `pytest.skip` if the import path is unavailable, mirroring `test_ingest_graph.py`) |

- [ ] **KeyError caution** (`test_graph_ingest_error_skips_clause_splitter`): `clauses` is an `Annotated[dict, merge_nested_clause_dicts]` channel with no default. When the error short-circuit skips ClauseSplitterAgent, that channel is never written and LangGraph omits it from the output — so `final_state["clauses"] == {}` will raise `KeyError`. Assert `assert not final_state.get("clauses")` (or `"clauses" not in final_state or final_state["clauses"] == {}`) instead. The existing `test_ingest_graph.py::test_graph_ingest_error_short_circuits` never touches `clauses`, which is why this hasn't surfaced before.
- [ ] For the checkpointing test, recompile the graph with the checkpointer attached (same approach as `test_ingest_graph.py::test_graph_checkpointing`), or attach a checkpointer to `build_graph()`'s output if the builder supports it.

**Verify**: Run `python -m pytest tests/integration/test_clause_splitter_graph.py -v` — all 4 tests must PASS (checkpointing may skip if the SQLite saver import path is unavailable — acceptable).

---

## Task 12: Full test suite pass

- [ ] Run the complete suite:
```
python -m pytest tests/ -v --tb=short
```
- [ ] All existing IngestAgent tests (feature 003) must still pass — the ClauseSplitter changes must not regress them.
- [ ] Expected NEW test count for feature 004: 2 (config) + 16 (regex splitter) + 13 (LLM refiner) + 13 (node) + 4 (integration) = **48 new tests**.
- [ ] OCR-gated IngestAgent tests may be skipped if Tesseract is not installed — acceptable. No ClauseSplitter test requires Tesseract or a live Ollama.

---

## Task 13: Linting and type checking

- [ ] Run `black app/ tests/` — auto-format.
- [ ] Run `ruff check app/ tests/` — no lint errors.
- [ ] Run `mypy app/` — no type errors (if mypy is installed).
- [ ] Do NOT weaken tests to satisfy lint/type checks — fix the implementation instead (constitution §7).

---

## Task 14: Manual Ollama smoke test (optional, not in automated suite)

- [ ] Ensure Ollama is running and the model is pulled: `ollama pull qwen3:14b`.
- [ ] Run a one-off script that invokes `clause_splitter_agent` (or the full graph) on a real multi-clause contract with a live Ollama call.
- [ ] Confirm: LLM refinement path is used (`llm_used=True` in logs), `clause_type` values are populated, and the observed LLM latency is well under `CLAUSE_SPLITTER_TIMEOUT_SECONDS`.
- [ ] Record the observed latency — per spec §7 / plan §5, use it to consider tuning `CLAUSE_SPLITTER_TIMEOUT_SECONDS` down in a follow-up.

**Why**: The automated suite mocks Ollama, so this is the only step that validates the real `format="json"` behavior of Qwen3 14B and the true latency envelope (plan §6 risks).

---

## Summary of all files created/modified

| # | File | Action |
|---|------|--------|
| 1 | `app/config.py` | MODIFIED (add 4 ClauseSplitter constants) |
| 2 | `app/graph/nodes/splitters/__init__.py` | NEW (`ClauseBoundary` dataclass) |
| 3 | `app/graph/nodes/splitters/regex_splitter.py` | NEW (`split_by_regex`) |
| 4 | `app/graph/nodes/splitters/llm_refiner.py` | NEW (`refine_with_llm`) |
| 5 | `app/graph/nodes/clause_splitter_agent.py` | NEW (node function) |
| 6 | `app/graph/builder.py` | MODIFIED (add node + rewire routing) |
| 7 | `tests/unit/test_config.py` | MODIFIED (+2 tests) |
| 8 | `tests/unit/test_regex_splitter.py` | NEW (16 tests) |
| 9 | `tests/unit/test_llm_refiner.py` | NEW (13 tests) |
| 10 | `tests/unit/test_clause_splitter_agent.py` | NEW (13 tests) |
| 11 | `tests/integration/test_clause_splitter_graph.py` | NEW (4 tests) |

---

## Acceptance-criteria traceability (spec §3 → tasks)

| Spec §3 criterion | Covered by |
|-------------------|-----------|
| 1. Boundary detection — numbered contracts | Task 4/5 (`test_split_numbered_sections`, `test_split_nested_numbers`) |
| 2. Non-empty output | Task 4/5 (regex always returns >= 1 clause for non-empty input) |
| 3. Required fields | Task 8/9 (`test_splitter_required_fields_present`) |
| 4. No-section-markers fallback | Task 4/5 (`test_split_paragraph_fallback`, `test_split_single_block_fallback`) |
| 5. Defensive ingest_error check | Task 8/9 (`test_splitter_ingest_error_returns_empty`) |
| 6. Ollama client usage | Task 6/7 (`test_refine_json_mode_used`; `OLLAMA_MODEL_NAME` from config) |
| 7. Timeout fallback | Task 6/7 (`test_refine_timeout_returns_regex_output`) |
| 8. Optional clause_type | Task 8/9 (`test_splitter_clause_type_none_preserved`, `test_refine_invalid_clause_type_becomes_none`) |
| 9. Partial update only | Task 8/9 (`test_splitter_partial_update_only`) |
| 10. Clause ID determinism | Task 4/5 (`test_split_deterministic`, `test_split_clause_ids_positional`) |
| 11. Position correctness | Task 4/5 (`test_split_position_1_indexed`), Task 8/9 (`test_splitter_position_sequential`) |
</content>
</invoke>
