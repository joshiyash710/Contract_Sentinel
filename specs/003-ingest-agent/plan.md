# IngestAgent Technical Plan

## Git Branch

`feature/003-ingest-agent` — branching workflow per `specs/000-constitution.md` §11.

---

## 1. Overview

This plan details how to implement the IngestAgent (Node 1) as specified in `specs/003-ingest-agent/spec.md`. The IngestAgent parses uploaded PDF/DOCX contracts into clean extracted text, with OCR fallback for scanned or low-density documents, populating the IngestAgent slice of `ContractState` defined in `specs/001-contract-state-schema.md`.

All configurable thresholds live in a shared config module per the constitution's §3 (Configurable Thresholds Rule). The node function returns only the state keys it actually updates per §5 (Partial-Update Rule). Regarding §6 (State Minimality Rule): `extracted_text` is a `str` field defined directly in `ContractState` by `specs/001-contract-state-schema.md` — this is the spec's own design decision, as the extracted text is what downstream nodes consume directly. The raw PDF/DOCX binary is never placed in state; only `document_path` (a file-path reference) is stored.

---

## 2. Files to Create / Modify

### Package Init Files

#### [NEW] `backend/app/__init__.py`
#### [NEW] `backend/app/graph/__init__.py`
#### [NEW] `backend/app/graph/nodes/__init__.py`

Empty `__init__.py` files to make `app`, `app.graph`, and `app.graph.nodes` importable Python packages. These are required for the import paths used throughout this plan (e.g., `from app.config import ...`, `from app.graph.state import ...`, `from app.graph.nodes.ingest_agent import ...`).

---

### Shared Config Module

#### [NEW] `backend/app/config.py`

Central configuration module housing all named, configurable constants referenced across nodes. The IngestAgent constants are the first entries; future nodes (CRAG, Self-RAG) will add their own constants to this same file.

```python
# IngestAgent thresholds (from specs/003-ingest-agent/spec.md §6)
MIN_TEXT_LENGTH_THRESHOLD: int = 50
MIN_CHAR_DENSITY_THRESHOLD: int = 100
OCR_LOW_CONFIDENCE_THRESHOLD: float = 0.6
INGEST_TIMEOUT_SECONDS: int = 60

# CRAG thresholds (placeholder — will be populated by 005-crag-retrieval plan)
CRAG_CONFIDENCE_THRESHOLD: float = 0.73

# Self-RAG thresholds (placeholder — will be populated by 006-self-rag-validation plan)
SELF_RAG_MAX_RETRIES: int = 3
```

Values are plain module-level constants (not dataclass/Pydantic) — simple, importable, and overridable in tests via monkeypatching. The `.env.example` already exposes `CRAG_CONFIDENCE_THRESHOLD` and `MAX_RETRY_ATTEMPTS` as environment variables; IngestAgent constants do not need env-var overrides at this time but the pattern is established if tuning demands it later.

---

### Graph State Implementation

#### [MODIFY] `backend/app/graph/state.py`

Replace the current placeholder with the full `ContractState` TypedDict, the reducer functions (`merge_dicts`, `merge_nested_clause_dicts`), and all supporting enums as defined verbatim in `specs/001-contract-state-schema.md` §3.

This is implemented now (rather than deferred) because:
1. The IngestAgent node function must return a partial dict typed against `ContractState`.
2. Other future node implementations import from this same module — establishing it now avoids drift.
3. The spec is finalized with no remaining open questions.

No modifications to the schema — this is a direct transcription of the spec.

---

### Document Parsers

#### [NEW] `backend/app/graph/nodes/parsers/__init__.py`

Exports the shared `ParseResult` dataclass used by both parser modules:

```python
from dataclasses import dataclass
from typing import Optional

@dataclass
class ParseResult:
    text: str
    page_count: int
    ocr_used: bool
    ocr_confidence: Optional[float]
```

This lives here (rather than in either parser module) so that `pdf_parser.py` and `docx_parser.py` can both import it without creating a cross-dependency between parsers.

#### [NEW] `backend/app/graph/nodes/parsers/pdf_parser.py`

Responsible for PDF text extraction and OCR fallback. Uses `pymupdf` (PyMuPDF) for direct text extraction and page-count metadata, and `pytesseract` for OCR. Imports `ParseResult` from `app.graph.nodes.parsers`.

**Public interface:**

```python
from app.graph.nodes.parsers import ParseResult

def parse_pdf(file_path: str, timeout_seconds: int) -> ParseResult:
    """
    Extract text from a PDF file.

    Strategy:
    1. Open the PDF with pymupdf, extract text from all pages.
    2. Count pages via len(doc).
    3. Evaluate whether OCR is needed (see OCR Decision Logic below).
    4. If OCR is needed, render each page to an image, run pytesseract,
       aggregate text and confidence scores.
    5. Return ParseResult with the best available text.

    Raises:
        FileNotFoundError: if file_path does not exist
        PermissionError: if file_path is not readable
        ValueError: if the PDF is corrupted / cannot be opened by pymupdf
        TimeoutError: if processing exceeds timeout_seconds
    """
```

**OCR Decision Logic** (applied after direct extraction):

```
extracted_text = join all page texts
char_density = len(extracted_text) / page_count

if len(extracted_text) < MIN_TEXT_LENGTH_THRESHOLD:
    → OCR required (empty/near-empty document)
elif char_density < MIN_CHAR_DENSITY_THRESHOLD:
    → OCR required (low density — likely scanned)
else:
    → Direct extraction is sufficient, no OCR
```

**OCR confidence aggregation**: Pytesseract returns per-word confidence via `image_to_data()`. The page-level confidence is the mean of all word confidences (excluding words with confidence = -1, which indicates "not recognized"). The document-level `ocr_confidence` is the mean of all page-level confidences, normalized to 0.0–1.0 by dividing by 100 (pytesseract reports 0–100).

**Timeout enforcement**: The `parse_pdf` function wraps the entire operation in a `concurrent.futures.ThreadPoolExecutor` with the configured timeout. If the timeout fires, a `TimeoutError` is raised. This approach is used instead of `signal.alarm` because:
1. `signal.alarm` is Unix-only (project runs on Windows too per `.env.example`).
2. Pytesseract spawns a subprocess; thread-based timeout with executor shutdown handles this gracefully.

#### [NEW] `backend/app/graph/nodes/parsers/docx_parser.py`

Responsible for DOCX text extraction and OCR fallback. Uses `python-docx` for direct text extraction. Imports `ParseResult` from `app.graph.nodes.parsers`.

**Public interface:**

```python
from app.graph.nodes.parsers import ParseResult

def parse_docx(file_path: str, timeout_seconds: int) -> ParseResult:
    """
    Extract text from a DOCX file.

    Strategy:
    1. Open the DOCX with python-docx.
    2. Extract text from all paragraphs (joining with newlines).
    3. Estimate page_count: python-docx does not expose a direct page count.
       Use the heuristic: page_count = max(1, len(full_text) // 3000).
       Rationale: ~3000 chars/page is a reasonable estimate for legal contracts
       with standard formatting. This is only used for the char_density check
       to decide OCR fallback — it does not affect downstream processing.
    4. Evaluate OCR need using the same density logic as PDF.
    5. For OCR on DOCX: attempt to open the file with pymupdf for
       page-image rendering and run pytesseract. If pymupdf cannot render
       the DOCX (some DOCX variants are unsupported), catch the rendering
       error, log a warning, and return the direct-extracted text with
       ocr_used=False — do NOT set ingest_error, since direct text was
       already obtained. Only set ingest_error if both direct extraction
       AND OCR fail entirely.
    6. Return ParseResult.

    Raises:
        Same exceptions as parse_pdf.
    """
```

> **Note on DOCX page count**: `python-docx` does not expose page count because DOCX is a flow-based format where pagination depends on the rendering engine. The heuristic (`len(text) // 3000`) is sufficient for the OCR-trigger density check. If this proves too inaccurate, a future refinement could use pymupdf's DOCX rendering to count actual pages, but that adds latency and is not justified for Phase 1.

---

### IngestAgent Node

#### [NEW] `backend/app/graph/nodes/ingest_agent.py`

The LangGraph node function. This is the only file that interacts with `ContractState`.

**Public interface:**

```python
import logging

logger = logging.getLogger("contractsentinel.ingest")

def ingest_agent(state: ContractState) -> dict:
    """
    LangGraph node function for document ingestion.

    Reads: state["document_path"]
    Returns: partial dict with keys:
        document_id, document_path, original_filename, uploaded_at,
        extracted_text, ocr_used, ocr_confidence, ingest_error,
        current_node, node_timings
        (plus error_count on error paths only)

    Note: processing_started_at is a pipeline-level metadata field
    (not an IngestAgent-owned field per spec §2). It should be set by
    the caller that invokes the graph (e.g., the API upload handler).
    The IngestAgent does not set it.
    """
```

**Internal flow:**

```
1. Set current_node = "ingest_agent"
2. Record start_time
3. Resolve document_path from state
4. Validate file extension (.pdf or .docx)
   → On invalid: return partial dict with ingest_error = {"error_type": "unsupported_format", "message": "..."}
5. Check file exists and is readable
   → On FileNotFoundError: ingest_error with error_type = "corrupted_file"
     (Rationale: the spec defines four error_type values — "unsupported_format",
     "corrupted_file", "permission_denied", "timeout" — and FileNotFoundError
     does not map cleanly to any. We use "corrupted_file" as the closest match
     because: the file path was presumably valid at upload time, so a missing
     file at processing time indicates the reference is broken / the file was
     removed — semantically closer to "corrupted" than to any other category.
     The error message will contain the actual exception detail for diagnostics.
     If a dedicated "file_not_found" error_type is needed, the spec must be
     updated first per constitution §10.)
   → On PermissionError: ingest_error with error_type = "permission_denied"
6. Dispatch to parse_pdf() or parse_docx() based on extension
   → On ValueError (corrupted): ingest_error with error_type = "corrupted_file"
   → On TimeoutError: ingest_error with error_type = "timeout"
   → On any unexpected exception: ingest_error with error_type = "corrupted_file"
     (conservative — treat unknown parse failures as corruption)
7. On success: populate all output fields from ParseResult
8. Log evaluation metrics (see Logging section below)
9. Record elapsed time in node_timings
10. Return partial dict (only keys this node owns)
```

**Error path return shape** (every error path returns the same key set to avoid downstream KeyError):

```python
return {
    "document_id": document_id,
    "document_path": state["document_path"],
    "original_filename": original_filename,
    "uploaded_at": uploaded_at,
    "extracted_text": "",
    "ocr_used": False,
    "ocr_confidence": None,
    "ingest_error": {"error_type": "...", "message": "..."},
    "current_node": "ingest_agent",
    "node_timings": {"ingest_agent": elapsed},
    "error_count": 1,
}
```

**Success path return shape:**

```python
return {
    "document_id": document_id,
    "document_path": state["document_path"],
    "original_filename": original_filename,
    "uploaded_at": uploaded_at,
    "extracted_text": result.text,
    "ocr_used": result.ocr_used,
    "ocr_confidence": result.ocr_confidence,
    "ingest_error": None,
    "current_node": "ingest_agent",
    "node_timings": {"ingest_agent": elapsed},
}
```

Note: `error_count: 1` is included only on error paths. Since `error_count` uses `operator.add` as its reducer, returning `1` increments the pipeline-wide counter. On success, the key is omitted entirely (partial-update rule).

---

### Graph Wiring (Minimal — IngestAgent Only)

#### [NEW] `backend/app/graph/builder.py`

Constructs the LangGraph `StateGraph` for Phase 1. For this feature, we wire only the IngestAgent node and a conditional edge that short-circuits the pipeline when `ingest_error` is set. The remaining 6 nodes will be added by their respective feature specs.

```python
from langgraph.graph import StateGraph, END
from langgraph.graph.state import CompiledStateGraph
from app.graph.state import ContractState
from app.graph.nodes.ingest_agent import ingest_agent

def build_graph() -> CompiledStateGraph:
    graph = StateGraph(ContractState)
    graph.add_node("ingest_agent", ingest_agent)

    # Short-circuit: if ingest_error is set, skip to END
    # (In the full pipeline, this will route to a terminal error state
    #  or an error report node. For now, END is sufficient.)
    def route_after_ingest(state: ContractState) -> str:
        if state.get("ingest_error"):
            return "end"
        return "clause_splitter"  # placeholder — next node not yet implemented

    graph.add_conditional_edges(
        "ingest_agent",
        route_after_ingest,
        {"end": END, "clause_splitter": END},  # clause_splitter → END temporarily
    )

    graph.set_entry_point("ingest_agent")
    return graph.compile()
```

> **Important**: This is NOT a third conditional edge violating the constitution's "exactly 2 conditional edges" rule. The short-circuit on `ingest_error` is a **guard/error-path routing**, not one of the two domain-logic conditional edges (CRAG confidence routing and `route_on_risk`). When the full pipeline is assembled, this guard will be folded into the entry routing logic rather than remaining a standalone conditional edge. The plan documents this explicitly to avoid future confusion.

---

### Test Fixtures

#### [NEW] `backend/tests/fixtures/sample.pdf`

A minimal valid PDF with extractable text (at least 200 characters of legal-sounding contract text). Created programmatically via pymupdf in a setup script or committed as a binary fixture.

#### [NEW] `backend/tests/fixtures/sample.docx`

A minimal valid DOCX with extractable text (at least 200 characters). Created via python-docx in a setup script or committed as a binary fixture.

#### [NEW] `backend/tests/fixtures/scanned.pdf`

A PDF where the text layer is empty/minimal (< 50 characters) to trigger OCR fallback. This can be a single-page image-only PDF.

#### [NEW] `backend/tests/fixtures/corrupted.pdf`

A file with `.pdf` extension but invalid/corrupted binary content.

#### [NEW] `backend/tests/fixtures/unsupported.txt`

A plain text file to test format rejection.

#### [NEW] `backend/tests/conftest.py`

Shared pytest fixtures available to both `unit/` and `integration/` test directories. Provides:
- Paths to the above fixture files
- Common test utilities (e.g., helper to create minimal ContractState dicts for invoking the node)
- `pytest.mark.skipif` marker for tests requiring Tesseract OCR to be installed

> **Note**: This file is placed at `backend/tests/conftest.py` (not inside `fixtures/`) so that pytest's conftest discovery makes all fixtures available to every test file under `tests/`.

---

### Unit Tests

#### [NEW] `backend/tests/unit/test_pdf_parser.py`

Tests for `parse_pdf()`:

| Test | Verifies |
|------|----------|
| `test_parse_pdf_digital_text` | Direct extraction from a text-layer PDF returns correct text, `ocr_used=False`, `ocr_confidence=None` |
| `test_parse_pdf_empty_triggers_ocr` | PDF with < 50 chars of text triggers OCR, `ocr_used=True` |
| `test_parse_pdf_low_density_triggers_ocr` | PDF with char density < 100/page but > 50 total triggers OCR |
| `test_parse_pdf_ocr_confidence_captured` | OCR path captures and normalizes confidence score to 0.0–1.0 |
| `test_parse_pdf_corrupted_raises_value_error` | Corrupted PDF raises `ValueError` |
| `test_parse_pdf_not_found_raises` | Missing file raises `FileNotFoundError` |
| `test_parse_pdf_permission_denied_raises` | Unreadable file raises `PermissionError` |
| `test_parse_pdf_timeout_raises` | Processing exceeding timeout raises `TimeoutError` |
| `test_parse_pdf_page_count` | Correct page count returned from pymupdf metadata |

#### [NEW] `backend/tests/unit/test_docx_parser.py`

Tests for `parse_docx()`:

| Test | Verifies |
|------|----------|
| `test_parse_docx_digital_text` | Direct extraction from a standard DOCX |
| `test_parse_docx_empty_triggers_ocr` | DOCX with < 50 chars triggers OCR |
| `test_parse_docx_page_count_heuristic` | Page count heuristic (`len(text) // 3000`) is reasonable |
| `test_parse_docx_corrupted_raises_value_error` | Corrupted DOCX raises `ValueError` |
| `test_parse_docx_timeout_raises` | Timeout enforcement works |
| `test_parse_docx_ocr_rendering_failure_graceful` | pymupdf rendering failure on DOCX falls back to direct text without error |

#### [NEW] `backend/tests/unit/test_ingest_agent.py`

Tests for the `ingest_agent()` node function:

| Test | Verifies |
|------|----------|
| `test_ingest_pdf_success` | Full success path: correct state keys populated, `ingest_error` is `None` |
| `test_ingest_docx_success` | Same for DOCX format |
| `test_ingest_unsupported_format` | `.txt` file → `ingest_error` with `error_type: "unsupported_format"` |
| `test_ingest_corrupted_file` | Corrupted PDF → `ingest_error` with `error_type: "corrupted_file"` |
| `test_ingest_file_not_found` | Missing file → `ingest_error` with `error_type: "corrupted_file"`, message contains `FileNotFoundError` detail |
| `test_ingest_permission_denied` | Unreadable file → `ingest_error` with `error_type: "permission_denied"` |
| `test_ingest_timeout` | Slow processing → `ingest_error` with `error_type: "timeout"` |
| `test_ingest_document_id_is_uuid` | `document_id` is a valid UUID4 string |
| `test_ingest_uploaded_at_is_iso` | `uploaded_at` is a valid ISO 8601 timestamp |
| `test_ingest_partial_update_only` | Return dict contains only IngestAgent-owned keys (no clause data, no report data) |
| `test_ingest_error_increments_error_count` | Error paths include `error_count: 1` |
| `test_ingest_ocr_fallback_with_low_confidence` | OCR with confidence < 0.6: processing continues, score stored |
| `test_ingest_node_timing_recorded` | `node_timings["ingest_agent"]` is a positive float |
| `test_ingest_no_clause_output` | Return dict does not contain `clauses` key |
| `test_ingest_does_not_set_processing_started_at` | Return dict does not contain `processing_started_at` (pipeline-level, not IngestAgent-owned) |

#### [NEW] `backend/tests/unit/test_config.py`

Tests for `backend/app/config.py`:

| Test | Verifies |
|------|----------|
| `test_threshold_values_match_spec` | All constants match the values specified in spec §6 |
| `test_thresholds_are_correct_types` | Type checking (int for char thresholds, float for confidence, int for timeout) |

---

### Integration Tests

#### [NEW] `backend/tests/integration/test_ingest_graph.py`

Tests the IngestAgent wired into the LangGraph graph:

| Test | Verifies |
|------|----------|
| `test_graph_ingest_success_to_end` | Graph runs IngestAgent on a valid PDF and reaches END with populated state |
| `test_graph_ingest_error_short_circuits` | Graph runs IngestAgent on unsupported format and short-circuits to END without passing to clause_splitter |
| `test_graph_checkpointing` | State is checkpointed after IngestAgent completes (verifies langgraph-checkpoint-sqlite integration) |

---

## 3. Dependency & Import Map

```
app/__init__.py                          (empty — package marker)
app/graph/__init__.py                    (empty — package marker)
app/graph/nodes/__init__.py              (empty — package marker)

app/config.py
    └── (no imports — pure constants)

app/graph/state.py
    └── typing, enum, operator (stdlib only)

app/graph/nodes/parsers/__init__.py
    └── dataclasses, typing (stdlib only — defines ParseResult)

app/graph/nodes/parsers/pdf_parser.py
    ├── pymupdf (fitz)
    ├── pytesseract
    ├── concurrent.futures (stdlib)
    ├── app.graph.nodes.parsers (ParseResult)
    └── app.config (thresholds)

app/graph/nodes/parsers/docx_parser.py
    ├── docx (python-docx)
    ├── pymupdf (fitz) — for DOCX-to-image rendering during OCR
    ├── pytesseract
    ├── concurrent.futures (stdlib)
    ├── app.graph.nodes.parsers (ParseResult)
    └── app.config (thresholds)

app/graph/nodes/ingest_agent.py
    ├── uuid, datetime, os, pathlib, logging (stdlib)
    ├── app.graph.state (ContractState)
    ├── app.graph.nodes.parsers.pdf_parser (parse_pdf)
    ├── app.graph.nodes.parsers.docx_parser (parse_docx)
    └── app.config (INGEST_TIMEOUT_SECONDS)

app/graph/builder.py
    ├── langgraph.graph (StateGraph, END)
    ├── langgraph.graph.state (CompiledStateGraph)
    ├── app.graph.state (ContractState)
    └── app.graph.nodes.ingest_agent (ingest_agent)
```

---

## 4. Implementation Order

Following TDD per constitution §7 — tests are written and confirmed failing before implementation.

| Step | Action | Files |
|------|--------|-------|
| 1 | Create package `__init__.py` files | `app/__init__.py`, `app/graph/__init__.py`, `app/graph/nodes/__init__.py` |
| 2 | Implement `ContractState` TypedDict + enums + reducers (direct transcription of spec 001 — not feature code, no TDD needed) | `app/graph/state.py` |
| 3 | Write unit tests for config (confirm failing — module doesn't exist yet) | `tests/unit/test_config.py` |
| 4 | Implement shared config constants | `app/config.py` |
| 5 | Run config tests (confirm passing) | — |
| 6 | Create test fixtures + shared conftest | `tests/fixtures/*`, `tests/conftest.py` |
| 7 | Implement `ParseResult` dataclass in parsers package | `app/graph/nodes/parsers/__init__.py` |
| 8 | Write unit tests for PDF parser (confirm failing) | `tests/unit/test_pdf_parser.py` |
| 9 | Implement PDF parser | `app/graph/nodes/parsers/pdf_parser.py` |
| 10 | Run PDF parser tests (confirm passing) | — |
| 11 | Write unit tests for DOCX parser (confirm failing) | `tests/unit/test_docx_parser.py` |
| 12 | Implement DOCX parser | `app/graph/nodes/parsers/docx_parser.py` |
| 13 | Run DOCX parser tests (confirm passing) | — |
| 14 | Write unit tests for ingest_agent node (confirm failing) | `tests/unit/test_ingest_agent.py` |
| 15 | Implement ingest_agent node function | `app/graph/nodes/ingest_agent.py` |
| 16 | Run ingest_agent tests (confirm passing) | — |
| 17 | Implement graph builder (IngestAgent wiring) | `app/graph/builder.py` |
| 18 | Write and run integration tests | `tests/integration/test_ingest_graph.py` |
| 19 | Full test suite pass | all tests |

> **Note on Step 2**: `state.py` is a direct transcription of `specs/001-contract-state-schema.md` §3 — it is a spec artifact, not feature logic, so it does not require a TDD cycle. It is implemented first because both `config.py` tests and parser tests may import from it for type references.

---

## 5. Design Decisions & Rationale

### Why separate parser modules from the node function?

The `ingest_agent.py` node function is a thin orchestrator: it validates the file extension, dispatches to the correct parser, maps results to `ContractState` keys, and handles timing/error-wrapping. The actual parsing logic lives in `parsers/pdf_parser.py` and `parsers/docx_parser.py`. This separation:

1. Makes parsers independently testable without LangGraph state machinery.
2. Keeps the node function focused on state management (per constitution's partial-update and state-minimality rules).
3. Allows parser logic to be reused outside the graph if needed (e.g., in evaluation scripts).

### Why `concurrent.futures` for timeout instead of `asyncio`?

The LangGraph node functions in this project are synchronous (standard LangGraph convention for CPU-bound work). Pytesseract OCR spawns a subprocess (`tesseract` binary) and blocks the calling thread. `ThreadPoolExecutor` with a timeout is the simplest cross-platform approach that correctly handles subprocess-based blocking. An `asyncio.wait_for` approach would require making the entire parser async and wrapping the synchronous pytesseract call in `run_in_executor` anyway — adding complexity with no benefit.

### Why implement the full `ContractState` now?

Even though only IngestAgent fields are used, implementing the complete TypedDict from spec 001 now:
1. Ensures the schema is locked in as the single source of truth.
2. Prevents incremental drift where each node's plan re-interprets the schema.
3. Enables type checking to catch any mismatches between the node's return dict and the full state shape.

### Why `ParseResult` lives in `parsers/__init__.py`?

Both `pdf_parser.py` and `docx_parser.py` return a `ParseResult`. If it were defined in `pdf_parser.py`, then `docx_parser.py` would need to import from `pdf_parser` — creating a misleading dependency. Placing it in the package's `__init__.py` makes both parsers peer consumers of a shared type with no cross-dependency.

### DOCX page-count heuristic

`python-docx` has no page-count API because DOCX is a flow format. The heuristic `max(1, len(text) // 3000)` is only used for the character-density OCR-trigger check — not for any downstream processing. If it's off by ±30%, the worst case is a false-positive OCR trigger (which just re-extracts the same text that was already good) or a missed OCR trigger (which would only happen on documents that have reasonable text density anyway). This tradeoff is acceptable for Phase 1.

### DOCX OCR fallback resilience

pymupdf's DOCX rendering support is less robust than its PDF handling. If pymupdf cannot render a DOCX for OCR, the parser catches the error, logs a warning, and returns the direct-extracted text with `ocr_used=False`. This avoids failing the entire ingestion when direct extraction already produced usable text. Only if both direct extraction AND OCR fail entirely does the parser raise an error that maps to `ingest_error`.

### `FileNotFoundError` mapping to `corrupted_file`

The spec (§8, resolved question 4) defines four `ingest_error` `error_type` values: `unsupported_format`, `corrupted_file`, `permission_denied`, `timeout`. A `FileNotFoundError` does not map cleanly to any. We map it to `corrupted_file` because: the IngestAgent receives `document_path` from state, which was set by an upstream caller (API upload handler) that validated the file's existence. If the file is gone by the time the IngestAgent runs, the reference is broken — semantically closer to "corrupted reference" than any other category. The `message` field will contain the original `FileNotFoundError` detail for diagnostics. If a dedicated `file_not_found` error type is desired in the future, `specs/003-ingest-agent/spec.md` must be updated first per constitution §10 (Spec-First Change Rule).

### Logging strategy

The IngestAgent uses a named logger (`contractsentinel.ingest`) via Python's standard `logging` module. Per spec §7 (Evaluation), the following are logged at `INFO` level on every invocation:

- `ocr_used` (bool) — feeds OCR Usage Rate metric
- `ocr_confidence` (float or None) — feeds OCR Confidence Distribution metric
- `format` (pdf/docx) — feeds Format Success Rates metric
- `elapsed_seconds` (float) — feeds Processing Time metric
- `char_density` (float) — feeds Character Density Analysis metric
- `error_type` (str or None) — feeds OCR Failure Rate and format error tracking

No dedicated eval script is created in this plan — the logger output is the raw data source. A future eval spec will consume these logs to compute the histograms and percentages described in spec §7.

### `processing_started_at` is not set by IngestAgent

`processing_started_at` is a pipeline-level metadata field in `ContractState`, not listed under "Added by IngestAgent" in `specs/001-contract-state-schema.md`. It should be set by the caller that invokes the graph (e.g., the API upload handler or the test harness). The IngestAgent does not set it to respect the spec's field-ownership boundaries.

---

## 6. Risks & Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| Tesseract not installed on dev machine | OCR tests fail with `TesseractNotFoundError` | Document Tesseract install requirement in README; skip OCR tests with `pytest.mark.skipif` if Tesseract is unavailable, with a clear message |
| Pytesseract timeout on large scanned PDFs | Processing exceeds 60s default | Timeout is enforced via `ThreadPoolExecutor`; the constant is tunable in `config.py` |
| DOCX page-count heuristic inaccuracy | OCR triggers unnecessarily or misses scanned DOCXs | Acceptable for Phase 1; document the tradeoff; add eval metric for char-density distribution |
| pymupdf cannot render some DOCX files for OCR | OCR fallback fails on DOCX | Parser catches rendering errors gracefully, falls back to direct-extracted text with a warning log. Only fails if both extraction paths produce no text. |
| Windows vs Unix path handling | `pathlib` inconsistencies | Use `pathlib.Path` consistently; tests use `tmp_path` pytest fixture for OS-agnostic temp directories |
| `CompiledStateGraph` import path changes across LangGraph versions | `builder.py` import breaks | Pin `langgraph>=1.2.0,<2.0.0` per spec 002; verify import path during Step 17 implementation |

---

## 7. Out of Scope for This Plan

- **Nodes 2–7**: Not wired or implemented. `builder.py` stubs the next node as END.
- **API endpoints**: No FastAPI routes — the graph is exercised via tests only.
- **Database storage**: No SQLite/aiosqlite usage — document state exists only in LangGraph's in-memory + checkpoint store.
- **MCP integration**: No Drive/Gmail delivery.
- **Evaluation scripts**: Metrics are logged (via standard Python `logging`) but no eval script under `backend/eval/` is created in this plan. That will come with a dedicated eval spec.
- **Privacy/security**: Per Phase 2 deferral in constitution.
- **`processing_started_at` / `processing_completed_at`**: Pipeline-level timestamps set by the graph invoker, not by any individual node.
