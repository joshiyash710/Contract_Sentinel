# IngestAgent Implementation Tasks

Reference documents:
- Spec: `specs/003-ingest-agent/spec.md`
- Plan: `specs/003-ingest-agent/plan.md`
- State schema: `specs/001-contract-state-schema.md`
- Tech stack: `specs/002-tech-stack.md`
- Constitution: `specs/000-constitution.md`

All file paths below are relative to `backend/` unless stated otherwise.

---

## Task 1: Create package `__init__.py` files

- [x] Create empty file `app/__init__.py` (zero bytes, no content needed)
- [x] Create empty file `app/graph/__init__.py`
- [x] Create empty file `app/graph/nodes/__init__.py`

**Why**: These make `app`, `app.graph`, and `app.graph.nodes` importable Python packages. Without them, `from app.config import ...` and similar imports will fail with `ModuleNotFoundError`.

**Verify**: Run `python -c "import app; import app.graph; import app.graph.nodes"` from `backend/` — it should exit with no errors.

---

## Task 2: Implement `ContractState` TypedDict in `app/graph/state.py`

- [ ] Open `app/graph/state.py` (currently contains a placeholder comment)
- [ ] Replace the entire contents with the full `ContractState` TypedDict, reducer functions, and enums copied verbatim from `specs/001-contract-state-schema.md` §3

The file must contain exactly these items in this order:

1. Imports:
   ```python
   from typing import TypedDict, List, Optional, Dict, Any, Annotated
   from enum import Enum
   import operator
   ```

2. Reducer function `merge_dicts(left: dict, right: dict) -> dict`:
   - Returns a copy of `left`, updated with `right`
   - Handles `None`/empty safely for both arguments

3. Reducer function `merge_nested_clause_dicts(left: dict, right: dict) -> dict`:
   - Merges nested clause dictionaries
   - For existing `clause_id` keys, merges the inner dict (new data takes precedence)
   - For new `clause_id` keys, adds them directly

4. Enums (all `str, Enum` subclasses):
   - `ClauseType` with values: `definitions`, `payment`, `delivery`, `term`, `termination`, `confidentiality`, `intellectual_property`, `liability`, `force_majeure`, `dispute_resolution`, `general`, `other`
   - `RetrievalPath` with values: `local_kb`, `web_fallback`
   - `ValidationStatus` with values: `discarded`, `validated`
   - `RiskLevel` with values: `low`, `medium`, `high`
   - `MCPDeliveryStatus` with values: `pending`, `success`, `failed`

5. `MCPDeliveryInfo(TypedDict)` with fields:
   - `status: MCPDeliveryStatus`
   - `error_message: Optional[str]`
   - `delivered_at: Optional[str]`

6. `ContractState(TypedDict)` with all fields exactly as defined in spec §3, including `Annotated` reducer declarations on `clauses`, `evidence_trail`, `error_count`, `retry_budgets`, `node_timings`, `mcp_delivery_status`

**Do NOT add, rename, or remove any fields from what the spec defines.**

**Verify**: Run `python -c "from app.graph.state import ContractState, ClauseType, RiskLevel, merge_dicts, merge_nested_clause_dicts"` from `backend/` — no errors.

---

## Task 3: Write unit tests for config module

- [ ] Create file `tests/unit/test_config.py`
- [ ] Write 2 test functions:

```python
# test_config.py
import pytest


def test_threshold_values_match_spec():
    """Verify all IngestAgent constants match specs/003-ingest-agent/spec.md §6."""
    from app.config import (
        MIN_TEXT_LENGTH_THRESHOLD,
        MIN_CHAR_DENSITY_THRESHOLD,
        OCR_LOW_CONFIDENCE_THRESHOLD,
        INGEST_TIMEOUT_SECONDS,
    )
    assert MIN_TEXT_LENGTH_THRESHOLD == 50
    assert MIN_CHAR_DENSITY_THRESHOLD == 100
    assert OCR_LOW_CONFIDENCE_THRESHOLD == 0.6
    assert INGEST_TIMEOUT_SECONDS == 60


def test_thresholds_are_correct_types():
    """Verify threshold types: int for counts, float for ratios, int for seconds."""
    from app.config import (
        MIN_TEXT_LENGTH_THRESHOLD,
        MIN_CHAR_DENSITY_THRESHOLD,
        OCR_LOW_CONFIDENCE_THRESHOLD,
        INGEST_TIMEOUT_SECONDS,
    )
    assert isinstance(MIN_TEXT_LENGTH_THRESHOLD, int)
    assert isinstance(MIN_CHAR_DENSITY_THRESHOLD, int)
    assert isinstance(OCR_LOW_CONFIDENCE_THRESHOLD, float)
    assert isinstance(INGEST_TIMEOUT_SECONDS, int)
```

**Verify**: Run `python -m pytest tests/unit/test_config.py -v` — both tests must FAIL with `ModuleNotFoundError` (since `app/config.py` does not exist yet). This confirms the TDD cycle is correct.

---

## Task 4: Implement shared config constants

- [ ] Create file `app/config.py`
- [ ] Add the following module-level constants (no classes, no imports, just plain assignments):

```python
"""
Shared configurable constants for ContractSentinel pipeline nodes.

All threshold values referenced by node logic must be defined here as named
constants — never hardcoded inline — per specs/000-constitution.md §3.
"""

# IngestAgent thresholds (specs/003-ingest-agent/spec.md §6)
MIN_TEXT_LENGTH_THRESHOLD: int = 50
MIN_CHAR_DENSITY_THRESHOLD: int = 100
OCR_LOW_CONFIDENCE_THRESHOLD: float = 0.6
INGEST_TIMEOUT_SECONDS: int = 60

# CRAG thresholds (placeholder — will be populated by 005-crag-retrieval)
CRAG_CONFIDENCE_THRESHOLD: float = 0.73

# Self-RAG thresholds (placeholder — will be populated by 006-self-rag-validation)
SELF_RAG_MAX_RETRIES: int = 3
```

**Verify**: Run `python -m pytest tests/unit/test_config.py -v` — both tests must now PASS.

---

## Task 5: Create test fixtures and shared conftest

- [ ] Create `tests/fixtures/` directory if it does not already exist

### 5a: Create `tests/fixtures/sample.pdf`

Write a Python helper script (run it once, do not commit the script) that creates a minimal valid PDF:

```python
import fitz  # pymupdf

doc = fitz.open()
page = doc.new_page()
text = (
    "SERVICES AGREEMENT\n\n"
    "This Services Agreement ('Agreement') is entered into as of the date "
    "last signed below, by and between the Client and the Service Provider. "
    "The Service Provider agrees to perform the services described in "
    "Exhibit A attached hereto. Payment shall be made within thirty (30) "
    "days of receipt of invoice. This Agreement shall be governed by the "
    "laws of the State of Delaware."
)
page.insert_text((72, 72), text, fontsize=11)
doc.save("tests/fixtures/sample.pdf")
doc.close()
```

The resulting PDF must have at least 200 characters of extractable text.

### 5b: Create `tests/fixtures/sample.docx`

```python
from docx import Document

doc = Document()
doc.add_paragraph(
    "SERVICES AGREEMENT\n\n"
    "This Services Agreement ('Agreement') is entered into as of the date "
    "last signed below, by and between the Client and the Service Provider. "
    "The Service Provider agrees to perform the services described in "
    "Exhibit A attached hereto. Payment shall be made within thirty (30) "
    "days of receipt of invoice. This Agreement shall be governed by the "
    "laws of the State of Delaware."
)
doc.save("tests/fixtures/sample.docx")
```

### 5c: Create `tests/fixtures/scanned.pdf`

Create a single-page PDF where the text layer has fewer than 50 characters. This triggers the OCR fallback.

```python
import fitz
from PIL import Image, ImageDraw, ImageFont
import io

# Create an image with text (simulates a scanned page)
img = Image.new("RGB", (612, 792), "white")
draw = ImageDraw.Draw(img)
draw.text((72, 72), "This is a scanned contract page with legal terms.", fill="black")

# Save image to bytes
img_bytes = io.BytesIO()
img.save(img_bytes, format="PNG")
img_bytes.seek(0)

# Create a PDF with the image as the page content (no text layer)
doc = fitz.open()
page = doc.new_page(width=612, height=792)
page.insert_image(fitz.Rect(0, 0, 612, 792), stream=img_bytes.read())
doc.save("tests/fixtures/scanned.pdf")
doc.close()
```

### 5d: Create `tests/fixtures/corrupted.pdf`

```python
with open("tests/fixtures/corrupted.pdf", "wb") as f:
    f.write(b"This is not a valid PDF file content - just garbage bytes 12345")
```

### 5e: Create `tests/fixtures/unsupported.txt`

```python
with open("tests/fixtures/unsupported.txt", "w") as f:
    f.write("This is a plain text file, not a valid contract format.")
```

### 5f: Create `tests/conftest.py`

- [ ] Create file `tests/conftest.py` (at the `tests/` root, NOT inside `fixtures/`)
- [ ] Contents:

```python
"""
Shared pytest fixtures for ContractSentinel tests.

Placed at tests/conftest.py so all fixtures are available to both
tests/unit/ and tests/integration/ via pytest's conftest discovery.
"""
import os
import shutil
import pytest

FIXTURES_DIR = os.path.join(os.path.dirname(__file__), "fixtures")


@pytest.fixture
def sample_pdf_path():
    """Path to a valid PDF with extractable text (>200 chars)."""
    return os.path.join(FIXTURES_DIR, "sample.pdf")


@pytest.fixture
def sample_docx_path():
    """Path to a valid DOCX with extractable text (>200 chars)."""
    return os.path.join(FIXTURES_DIR, "sample.docx")


@pytest.fixture
def scanned_pdf_path():
    """Path to a PDF with no/minimal text layer (<50 chars) to trigger OCR."""
    return os.path.join(FIXTURES_DIR, "scanned.pdf")


@pytest.fixture
def corrupted_pdf_path():
    """Path to a file with .pdf extension but invalid content."""
    return os.path.join(FIXTURES_DIR, "corrupted.pdf")


@pytest.fixture
def unsupported_txt_path():
    """Path to a .txt file for testing format rejection."""
    return os.path.join(FIXTURES_DIR, "unsupported.txt")


@pytest.fixture
def nonexistent_path(tmp_path):
    """Path to a file that does not exist."""
    return str(tmp_path / "does_not_exist.pdf")


@pytest.fixture
def unreadable_pdf_path(tmp_path):
    """Path to a PDF file that exists but is not readable (permissions removed).
    
    Note: On Windows, os.chmod may not fully remove read permissions.
    Tests using this fixture should be skipped on Windows if they fail
    due to platform permission model differences.
    """
    path = tmp_path / "unreadable.pdf"
    path.write_bytes(b"%PDF-1.4 minimal content")
    os.chmod(str(path), 0o000)
    yield str(path)
    # Restore permissions for cleanup
    os.chmod(str(path), 0o644)


def _has_tesseract():
    """Check if Tesseract OCR is installed and accessible."""
    return shutil.which("tesseract") is not None


requires_tesseract = pytest.mark.skipif(
    not _has_tesseract(),
    reason="Tesseract OCR is not installed — install it to run OCR tests"
)


def make_ingest_state(document_path: str) -> dict:
    """Create a minimal state dict to invoke the ingest_agent node.

    Only includes the key that ingest_agent reads from state.
    All other ContractState keys are left to LangGraph defaults.
    """
    return {"document_path": document_path}
```

**Verify**: Run `python -m pytest tests/ --collect-only` — it should discover the fixtures without errors.

---

## Task 6: Implement `ParseResult` dataclass

- [ ] Create file `app/graph/nodes/parsers/__init__.py`
- [ ] Contents:

```python
"""
Shared types for document parser modules.

ParseResult is the return type for both pdf_parser.parse_pdf()
and docx_parser.parse_docx().
"""
from dataclasses import dataclass
from typing import Optional


@dataclass
class ParseResult:
    """Result of parsing a document file.
    
    Attributes:
        text: The extracted text content.
        page_count: Number of pages in the document.
        ocr_used: Whether OCR was needed for text extraction.
        ocr_confidence: OCR confidence score normalized to 0.0–1.0,
            or None if OCR was not used.
    """
    text: str
    page_count: int
    ocr_used: bool
    ocr_confidence: Optional[float]
```

**Verify**: Run `python -c "from app.graph.nodes.parsers import ParseResult; r = ParseResult('hi', 1, False, None); print(r)"` from `backend/`.

---

## Task 7: Write unit tests for PDF parser

- [ ] Create file `tests/unit/test_pdf_parser.py`
- [ ] Write these 9 test functions. Each test is described in detail below.

```python
"""Unit tests for app.graph.nodes.parsers.pdf_parser.parse_pdf()."""
import os
import pytest
from app.graph.nodes.parsers import ParseResult

# Import will fail until Task 8 implements the module — that's expected for TDD.
from app.graph.nodes.parsers.pdf_parser import parse_pdf

# Use the conftest.py fixtures: sample_pdf_path, scanned_pdf_path,
# corrupted_pdf_path, nonexistent_path, unreadable_pdf_path
# Use the conftest.py marker: requires_tesseract


def test_parse_pdf_digital_text(sample_pdf_path):
    """A text-layer PDF extracts text directly without OCR."""
    result = parse_pdf(sample_pdf_path, timeout_seconds=60)
    assert isinstance(result, ParseResult)
    assert len(result.text) >= 200  # fixture has >200 chars
    assert result.ocr_used is False
    assert result.ocr_confidence is None
    assert result.page_count >= 1


@requires_tesseract
def test_parse_pdf_empty_triggers_ocr(scanned_pdf_path):
    """A PDF with <50 chars of text triggers OCR fallback."""
    result = parse_pdf(scanned_pdf_path, timeout_seconds=60)
    assert result.ocr_used is True


@requires_tesseract
def test_parse_pdf_low_density_triggers_ocr(tmp_path):
    """A multi-page PDF with <100 chars/page triggers OCR."""
    import fitz
    doc = fitz.open()
    # 3 pages with ~60 chars total = 20 chars/page density
    for i in range(3):
        page = doc.new_page()
        page.insert_text((72, 72), f"Page {i+1}: short", fontsize=11)
    path = str(tmp_path / "low_density.pdf")
    doc.save(path)
    doc.close()

    result = parse_pdf(path, timeout_seconds=60)
    assert result.ocr_used is True


@requires_tesseract
def test_parse_pdf_ocr_confidence_captured(scanned_pdf_path):
    """OCR path captures confidence score normalized to 0.0–1.0."""
    result = parse_pdf(scanned_pdf_path, timeout_seconds=60)
    assert result.ocr_used is True
    assert result.ocr_confidence is not None
    assert 0.0 <= result.ocr_confidence <= 1.0


def test_parse_pdf_corrupted_raises_value_error(corrupted_pdf_path):
    """Corrupted PDF raises ValueError."""
    with pytest.raises(ValueError):
        parse_pdf(corrupted_pdf_path, timeout_seconds=60)


def test_parse_pdf_not_found_raises(nonexistent_path):
    """Missing file raises FileNotFoundError."""
    with pytest.raises(FileNotFoundError):
        parse_pdf(nonexistent_path, timeout_seconds=60)


def test_parse_pdf_permission_denied_raises(unreadable_pdf_path):
    """Unreadable file raises PermissionError."""
    with pytest.raises(PermissionError):
        parse_pdf(unreadable_pdf_path, timeout_seconds=60)


def test_parse_pdf_timeout_raises(sample_pdf_path):
    """Processing exceeding timeout raises TimeoutError.
    
    Use timeout_seconds=0 to force immediate timeout.
    The implementation should not complete in 0 seconds.
    """
    # timeout of near-zero to force timeout. Use a very small value.
    # Note: 0 may behave differently across platforms, use 0.001
    with pytest.raises(TimeoutError):
        parse_pdf(sample_pdf_path, timeout_seconds=0.001)


def test_parse_pdf_page_count(sample_pdf_path):
    """Page count matches pymupdf's actual page count."""
    import fitz
    doc = fitz.open(sample_pdf_path)
    expected_pages = len(doc)
    doc.close()

    result = parse_pdf(sample_pdf_path, timeout_seconds=60)
    assert result.page_count == expected_pages
```

**Verify**: Run `python -m pytest tests/unit/test_pdf_parser.py -v` — all 9 tests must FAIL (either `ImportError` because the module doesn't exist, or test failures). This confirms the TDD cycle.

---

## Task 8: Implement PDF parser

- [ ] Create file `app/graph/nodes/parsers/pdf_parser.py`
- [ ] Implementation requirements:

**Imports:**
```python
import logging
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
from pathlib import Path
from typing import Optional

import fitz  # pymupdf
import pytesseract

from app.config import MIN_TEXT_LENGTH_THRESHOLD, MIN_CHAR_DENSITY_THRESHOLD
from app.graph.nodes.parsers import ParseResult
```

**Logger:** `logger = logging.getLogger("contractsentinel.ingest.pdf_parser")`

**Function `parse_pdf(file_path: str, timeout_seconds: int) -> ParseResult`:**

1. Validate `file_path` exists → raise `FileNotFoundError` if not
2. Validate `file_path` is readable → raise `PermissionError` if not
3. Wrap all remaining work in `ThreadPoolExecutor(max_workers=1)` with `future.result(timeout=timeout_seconds)`. Catch `FuturesTimeoutError` and re-raise as `TimeoutError("Processing exceeded {timeout_seconds}s")`
4. Inside the executor:
   a. Open with `fitz.open(file_path)`. Catch `fitz.FileDataError` (or similar) and raise `ValueError("Corrupted PDF: ...")`
   b. `page_count = len(doc)`
   c. Extract text: `extracted_text = "\n".join(page.get_text() for page in doc)`
   d. Compute `char_density = len(extracted_text) / max(1, page_count)`
   e. Decide OCR:
      - If `len(extracted_text) < MIN_TEXT_LENGTH_THRESHOLD` → OCR needed
      - Elif `char_density < MIN_CHAR_DENSITY_THRESHOLD` → OCR needed
      - Else → no OCR, return `ParseResult(text=extracted_text, page_count=page_count, ocr_used=False, ocr_confidence=None)`
   f. If OCR needed:
      - For each page, render to pixmap: `pix = page.get_pixmap(dpi=300)`
      - Convert pixmap to PIL Image
      - Run `pytesseract.image_to_data(image, output_type=pytesseract.Output.DICT)`
      - Collect word confidences (filter out entries where `conf == -1`)
      - Collect text from `pytesseract.image_to_string(image)`
      - Page confidence = mean of valid word confidences, or 0.0 if none
   g. Document-level confidence = mean of all page confidences / 100.0 (normalize to 0–1)
   h. Join all OCR text
   i. Close doc
   j. Return `ParseResult(text=ocr_text, page_count=page_count, ocr_used=True, ocr_confidence=doc_confidence)`

**Verify**: Run `python -m pytest tests/unit/test_pdf_parser.py -v` — all 9 tests must PASS. (OCR tests will be skipped if Tesseract is not installed — that is acceptable.)

---

## Task 9: Write unit tests for DOCX parser

- [ ] Create file `tests/unit/test_docx_parser.py`
- [ ] Write these 6 test functions:

```python
"""Unit tests for app.graph.nodes.parsers.docx_parser.parse_docx()."""
import pytest
from app.graph.nodes.parsers import ParseResult
from app.graph.nodes.parsers.docx_parser import parse_docx
from conftest import requires_tesseract


def test_parse_docx_digital_text(sample_docx_path):
    """A standard DOCX extracts text directly without OCR."""
    result = parse_docx(sample_docx_path, timeout_seconds=60)
    assert isinstance(result, ParseResult)
    assert len(result.text) >= 200
    assert result.ocr_used is False
    assert result.ocr_confidence is None


@requires_tesseract
def test_parse_docx_empty_triggers_ocr(tmp_path):
    """A DOCX with <50 chars triggers OCR fallback."""
    from docx import Document
    doc = Document()
    doc.add_paragraph("Hi")  # <50 chars
    path = str(tmp_path / "empty.docx")
    doc.save(path)

    result = parse_docx(path, timeout_seconds=60)
    # OCR was attempted (may or may not succeed depending on pymupdf DOCX support)
    # At minimum, the function should not crash
    assert isinstance(result, ParseResult)


def test_parse_docx_page_count_heuristic(sample_docx_path):
    """Page count heuristic produces max(1, len(text) // 3000)."""
    result = parse_docx(sample_docx_path, timeout_seconds=60)
    # Our fixture has ~400 chars, so page count should be max(1, 400//3000) = 1
    assert result.page_count >= 1


def test_parse_docx_corrupted_raises_value_error(tmp_path):
    """Corrupted DOCX raises ValueError."""
    path = str(tmp_path / "bad.docx")
    with open(path, "wb") as f:
        f.write(b"not a valid docx file")
    with pytest.raises(ValueError):
        parse_docx(path, timeout_seconds=60)


def test_parse_docx_timeout_raises(sample_docx_path):
    """Processing exceeding timeout raises TimeoutError."""
    with pytest.raises(TimeoutError):
        parse_docx(sample_docx_path, timeout_seconds=0.001)


def test_parse_docx_ocr_rendering_failure_graceful(tmp_path):
    """If pymupdf cannot render DOCX for OCR, fall back to direct text gracefully.
    
    Create a DOCX with enough text to pass (>50 chars) but mock pymupdf
    rendering to fail. The parser should return direct-extracted text with
    ocr_used=False instead of raising an error.
    """
    from docx import Document
    doc = Document()
    doc.add_paragraph("A" * 60)  # >50 chars but density will be low
    path = str(tmp_path / "rendertest.docx")
    doc.save(path)

    # Even if OCR rendering fails, the function should still succeed
    # with the direct-extracted text. Test that no exception propagates.
    result = parse_docx(path, timeout_seconds=60)
    assert isinstance(result, ParseResult)
    assert "A" * 60 in result.text
```

**Verify**: Run `python -m pytest tests/unit/test_docx_parser.py -v` — all 6 tests must FAIL (ImportError). This confirms the TDD cycle.

---

## Task 10: Implement DOCX parser

- [ ] Create file `app/graph/nodes/parsers/docx_parser.py`
- [ ] Implementation requirements:

**Imports:**
```python
import logging
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
from pathlib import Path

import docx  # python-docx
import fitz  # pymupdf — used only for DOCX-to-image rendering during OCR
import pytesseract

from app.config import MIN_TEXT_LENGTH_THRESHOLD, MIN_CHAR_DENSITY_THRESHOLD
from app.graph.nodes.parsers import ParseResult
```

**Logger:** `logger = logging.getLogger("contractsentinel.ingest.docx_parser")`

**Function `parse_docx(file_path: str, timeout_seconds: int) -> ParseResult`:**

1. Validate `file_path` exists → raise `FileNotFoundError` if not
2. Validate `file_path` is readable → raise `PermissionError` if not
3. Wrap all remaining work in `ThreadPoolExecutor` with timeout (same pattern as `parse_pdf`). Catch and re-raise as `TimeoutError`.
4. Inside the executor:
   a. Open with `docx.Document(file_path)`. Catch `docx.opc.exceptions.PackageNotFoundError` (or generic `Exception` from python-docx on bad files) and raise `ValueError("Corrupted DOCX: ...")`
   b. Extract text: `extracted_text = "\n".join(p.text for p in document.paragraphs)`
   c. Estimate page count: `page_count = max(1, len(extracted_text) // 3000)`
   d. Compute `char_density = len(extracted_text) / max(1, page_count)`
   e. Decide OCR (same logic as PDF):
      - If `len(extracted_text) < MIN_TEXT_LENGTH_THRESHOLD` → OCR needed
      - Elif `char_density < MIN_CHAR_DENSITY_THRESHOLD` → OCR needed
      - Else → return `ParseResult(text=extracted_text, page_count=page_count, ocr_used=False, ocr_confidence=None)`
   f. If OCR needed:
      - **Try** to open with `fitz.open(file_path)` for rendering
      - **If rendering fails** (any exception from fitz): log a warning `"pymupdf cannot render DOCX for OCR, falling back to direct text"`, return `ParseResult(text=extracted_text, page_count=page_count, ocr_used=False, ocr_confidence=None)`
      - **If rendering succeeds**: same OCR logic as PDF parser (render pages to pixmap, run pytesseract, aggregate confidence)
   g. Return `ParseResult`

**Critical**: The DOCX OCR fallback must be resilient. If pymupdf can't render the DOCX, the parser does NOT raise an error — it logs a warning and returns whatever direct text was extracted.

**Verify**: Run `python -m pytest tests/unit/test_docx_parser.py -v` — all 6 tests must PASS. (OCR tests skipped if Tesseract not installed — acceptable.)

---

## Task 11: Write unit tests for ingest_agent node

- [ ] Create file `tests/unit/test_ingest_agent.py`
- [ ] Write these 15 test functions:

```python
"""Unit tests for app.graph.nodes.ingest_agent.ingest_agent()."""
import uuid
from datetime import datetime
import pytest

from app.graph.nodes.ingest_agent import ingest_agent
from conftest import make_ingest_state, requires_tesseract


def test_ingest_pdf_success(sample_pdf_path):
    """Success path for PDF: all state keys populated, no error."""
    state = make_ingest_state(sample_pdf_path)
    result = ingest_agent(state)

    assert result["ingest_error"] is None
    assert len(result["extracted_text"]) >= 200
    assert result["ocr_used"] is False
    assert result["document_path"] == sample_pdf_path
    assert result["original_filename"] == "sample.pdf"
    assert result["current_node"] == "ingest_agent"


def test_ingest_docx_success(sample_docx_path):
    """Success path for DOCX: all state keys populated, no error."""
    state = make_ingest_state(sample_docx_path)
    result = ingest_agent(state)

    assert result["ingest_error"] is None
    assert len(result["extracted_text"]) >= 200
    assert result["original_filename"] == "sample.docx"


def test_ingest_unsupported_format(unsupported_txt_path):
    """Unsupported format → ingest_error with error_type 'unsupported_format'."""
    state = make_ingest_state(unsupported_txt_path)
    result = ingest_agent(state)

    assert result["ingest_error"] is not None
    assert result["ingest_error"]["error_type"] == "unsupported_format"
    assert result["extracted_text"] == ""


def test_ingest_corrupted_file(corrupted_pdf_path):
    """Corrupted PDF → ingest_error with error_type 'corrupted_file'."""
    state = make_ingest_state(corrupted_pdf_path)
    result = ingest_agent(state)

    assert result["ingest_error"] is not None
    assert result["ingest_error"]["error_type"] == "corrupted_file"


def test_ingest_file_not_found(nonexistent_path):
    """Missing file → ingest_error with error_type 'corrupted_file'.
    
    FileNotFoundError maps to 'corrupted_file' per plan §5
    (FileNotFoundError mapping rationale). The message must contain
    the original exception detail for diagnostics.
    """
    state = make_ingest_state(nonexistent_path)
    result = ingest_agent(state)

    assert result["ingest_error"] is not None
    assert result["ingest_error"]["error_type"] == "corrupted_file"
    assert "message" in result["ingest_error"]


def test_ingest_permission_denied(unreadable_pdf_path):
    """Unreadable file → ingest_error with error_type 'permission_denied'."""
    state = make_ingest_state(unreadable_pdf_path)
    result = ingest_agent(state)

    assert result["ingest_error"] is not None
    assert result["ingest_error"]["error_type"] == "permission_denied"


def test_ingest_timeout(sample_pdf_path, monkeypatch):
    """Slow processing → ingest_error with error_type 'timeout'.
    
    Monkeypatch INGEST_TIMEOUT_SECONDS to a very small value to force timeout.
    """
    import app.config
    monkeypatch.setattr(app.config, "INGEST_TIMEOUT_SECONDS", 0.001)

    state = make_ingest_state(sample_pdf_path)
    result = ingest_agent(state)

    assert result["ingest_error"] is not None
    assert result["ingest_error"]["error_type"] == "timeout"


def test_ingest_document_id_is_uuid(sample_pdf_path):
    """document_id is a valid UUID4 string."""
    state = make_ingest_state(sample_pdf_path)
    result = ingest_agent(state)

    # This should not raise ValueError
    parsed = uuid.UUID(result["document_id"], version=4)
    assert str(parsed) == result["document_id"]


def test_ingest_uploaded_at_is_iso(sample_pdf_path):
    """uploaded_at is a valid ISO 8601 timestamp."""
    state = make_ingest_state(sample_pdf_path)
    result = ingest_agent(state)

    # This should not raise ValueError
    dt = datetime.fromisoformat(result["uploaded_at"])
    assert dt is not None


def test_ingest_partial_update_only(sample_pdf_path):
    """Return dict contains only IngestAgent-owned keys.
    
    Must NOT contain keys owned by other nodes:
    clauses, report_path, evidence_trail, mcp_delivery_status,
    retry_budgets, processing_started_at, processing_completed_at
    """
    state = make_ingest_state(sample_pdf_path)
    result = ingest_agent(state)

    forbidden_keys = [
        "clauses", "report_path", "evidence_trail",
        "mcp_delivery_status", "retry_budgets",
        "processing_started_at", "processing_completed_at",
    ]
    for key in forbidden_keys:
        assert key not in result, f"Return dict should not contain '{key}'"


def test_ingest_error_increments_error_count(corrupted_pdf_path):
    """Error paths include error_count: 1 for the operator.add reducer."""
    state = make_ingest_state(corrupted_pdf_path)
    result = ingest_agent(state)

    assert result.get("error_count") == 1


def test_ingest_success_omits_error_count(sample_pdf_path):
    """Success paths must NOT include error_count (partial-update rule)."""
    state = make_ingest_state(sample_pdf_path)
    result = ingest_agent(state)

    assert "error_count" not in result


@requires_tesseract
def test_ingest_ocr_fallback_with_low_confidence(scanned_pdf_path):
    """OCR with low confidence: processing continues, score stored.
    
    We can't control exact confidence, but verify ocr_used=True
    and ocr_confidence is a float in [0.0, 1.0].
    """
    state = make_ingest_state(scanned_pdf_path)
    result = ingest_agent(state)

    assert result["ingest_error"] is None
    assert result["ocr_used"] is True
    assert result["ocr_confidence"] is not None
    assert 0.0 <= result["ocr_confidence"] <= 1.0


def test_ingest_node_timing_recorded(sample_pdf_path):
    """node_timings['ingest_agent'] is a positive float."""
    state = make_ingest_state(sample_pdf_path)
    result = ingest_agent(state)

    assert "ingest_agent" in result["node_timings"]
    assert isinstance(result["node_timings"]["ingest_agent"], float)
    assert result["node_timings"]["ingest_agent"] > 0


def test_ingest_does_not_set_processing_started_at(sample_pdf_path):
    """processing_started_at is pipeline-level, not set by IngestAgent."""
    state = make_ingest_state(sample_pdf_path)
    result = ingest_agent(state)

    assert "processing_started_at" not in result
```

**Verify**: Run `python -m pytest tests/unit/test_ingest_agent.py -v` — all 15 tests must FAIL. This confirms the TDD cycle.

---

## Task 12: Implement ingest_agent node function

- [ ] Create file `app/graph/nodes/ingest_agent.py`
- [ ] Implementation requirements:

**Imports:**
```python
import logging
import os
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

from app.config import INGEST_TIMEOUT_SECONDS
from app.graph.state import ContractState
from app.graph.nodes.parsers.pdf_parser import parse_pdf
from app.graph.nodes.parsers.docx_parser import parse_docx
```

**Logger:** `logger = logging.getLogger("contractsentinel.ingest")`

**Function `ingest_agent(state: ContractState) -> dict`:**

1. `start_time = time.monotonic()`
2. `document_id = str(uuid.uuid4())`
3. `document_path = state["document_path"]`
4. `original_filename = Path(document_path).name`
5. `uploaded_at = datetime.now(timezone.utc).isoformat()`
6. Define `ALLOWED_EXTENSIONS = {".pdf", ".docx"}`
7. Get file extension: `ext = Path(document_path).suffix.lower()`

**Format validation:**
```python
if ext not in ALLOWED_EXTENSIONS:
    elapsed = time.monotonic() - start_time
    return {
        "document_id": document_id,
        "document_path": document_path,
        "original_filename": original_filename,
        "uploaded_at": uploaded_at,
        "extracted_text": "",
        "ocr_used": False,
        "ocr_confidence": None,
        "ingest_error": {
            "error_type": "unsupported_format",
            "message": f"Unsupported file format '{ext}'. Only .pdf and .docx are accepted."
        },
        "current_node": "ingest_agent",
        "node_timings": {"ingest_agent": elapsed},
        "error_count": 1,
    }
```

**Parsing with error handling:**
```python
try:
    if ext == ".pdf":
        result = parse_pdf(document_path, timeout_seconds=INGEST_TIMEOUT_SECONDS)
    else:  # .docx
        result = parse_docx(document_path, timeout_seconds=INGEST_TIMEOUT_SECONDS)
except FileNotFoundError as e:
    # Map to corrupted_file — see plan §5 rationale
    return _error_return(document_id, document_path, original_filename,
                         uploaded_at, "corrupted_file", str(e), start_time)
except PermissionError as e:
    return _error_return(document_id, document_path, original_filename,
                         uploaded_at, "permission_denied", str(e), start_time)
except ValueError as e:
    return _error_return(document_id, document_path, original_filename,
                         uploaded_at, "corrupted_file", str(e), start_time)
except TimeoutError as e:
    return _error_return(document_id, document_path, original_filename,
                         uploaded_at, "timeout", str(e), start_time)
except Exception as e:
    # Catch-all: treat unknown failures as corruption
    return _error_return(document_id, document_path, original_filename,
                         uploaded_at, "corrupted_file", f"Unexpected error: {e}", start_time)
```

**Success path:**
```python
elapsed = time.monotonic() - start_time

# Log evaluation metrics per spec §7
logger.info(
    "IngestAgent completed",
    extra={
        "document_id": document_id,
        "format": ext,
        "ocr_used": result.ocr_used,
        "ocr_confidence": result.ocr_confidence,
        "elapsed_seconds": elapsed,
        "char_density": len(result.text) / max(1, result.page_count),
        "error_type": None,
    },
)

return {
    "document_id": document_id,
    "document_path": document_path,
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

**Helper `_error_return`:**
```python
def _error_return(document_id, document_path, original_filename,
                  uploaded_at, error_type, message, start_time):
    elapsed = time.monotonic() - start_time
    logger.warning(
        "IngestAgent error",
        extra={
            "document_id": document_id,
            "error_type": error_type,
            "message": message,
            "elapsed_seconds": elapsed,
        },
    )
    return {
        "document_id": document_id,
        "document_path": document_path,
        "original_filename": original_filename,
        "uploaded_at": uploaded_at,
        "extracted_text": "",
        "ocr_used": False,
        "ocr_confidence": None,
        "ingest_error": {"error_type": error_type, "message": message},
        "current_node": "ingest_agent",
        "node_timings": {"ingest_agent": elapsed},
        "error_count": 1,
    }
```

**Key constraints:**
- Do NOT return `clauses`, `report_path`, `evidence_trail`, `processing_started_at`, or any key not owned by IngestAgent
- Do NOT include `error_count` in the success path return dict
- `error_count: 1` is included ONLY in error path returns

**Verify**: Run `python -m pytest tests/unit/test_ingest_agent.py -v` — all 15 tests must PASS.

---

## Task 13: Implement graph builder

- [ ] Create file `app/graph/builder.py`
- [ ] Contents:

```python
"""
LangGraph StateGraph builder for ContractSentinel pipeline.

Currently wires only the IngestAgent node (Node 1) with an
error-based short-circuit. Remaining nodes will be added by
their respective feature plans.
"""
from langgraph.graph import StateGraph, END

from app.graph.state import ContractState
from app.graph.nodes.ingest_agent import ingest_agent


def build_graph():
    """Build and compile the ContractSentinel pipeline graph.
    
    Returns the compiled graph (a CompiledStateGraph).
    
    Note: the return type is not annotated with CompiledStateGraph
    to avoid breaking if langgraph changes the internal class path.
    The actual type is whatever graph.compile() returns.
    """
    graph = StateGraph(ContractState)
    graph.add_node("ingest_agent", ingest_agent)

    def route_after_ingest(state: ContractState) -> str:
        """Short-circuit pipeline if ingest_error is set.
        
        This is a guard/error-path routing, NOT one of the two
        domain-logic conditional edges defined in the constitution
        (CRAG confidence and route_on_risk).
        """
        if state.get("ingest_error"):
            return "end"
        return "clause_splitter"

    graph.add_conditional_edges(
        "ingest_agent",
        route_after_ingest,
        {"end": END, "clause_splitter": END},  # clause_splitter → END temporarily
    )

    graph.set_entry_point("ingest_agent")
    return graph.compile()
```

**Note on return type**: The plan specifies `CompiledStateGraph` as the return type, but the exact import path may vary across LangGraph versions. If `from langgraph.graph.state import CompiledStateGraph` works, add the annotation. If it raises `ImportError`, omit the type annotation and leave a comment explaining why. Do NOT let a type annotation import block the build.

**Verify**: Run `python -c "from app.graph.builder import build_graph; g = build_graph(); print(type(g))"` from `backend/` — should print the compiled graph type without errors.

---

## Task 14: Write and run integration tests

- [ ] Create file `tests/integration/test_ingest_graph.py`
- [ ] Write these 3 test functions:

```python
"""Integration tests: IngestAgent wired into the LangGraph graph."""
import pytest
from app.graph.builder import build_graph
from conftest import make_ingest_state


def test_graph_ingest_success_to_end(sample_pdf_path):
    """Graph runs IngestAgent on a valid PDF, reaches END with populated state."""
    graph = build_graph()
    initial_state = make_ingest_state(sample_pdf_path)

    final_state = graph.invoke(initial_state)

    assert final_state["ingest_error"] is None
    assert len(final_state["extracted_text"]) >= 200
    assert final_state["current_node"] == "ingest_agent"
    assert final_state["document_path"] == sample_pdf_path


def test_graph_ingest_error_short_circuits(unsupported_txt_path):
    """Graph runs IngestAgent on unsupported format, short-circuits to END.
    
    The graph should not crash and the final state should contain the error.
    """
    graph = build_graph()
    initial_state = make_ingest_state(unsupported_txt_path)

    final_state = graph.invoke(initial_state)

    assert final_state["ingest_error"] is not None
    assert final_state["ingest_error"]["error_type"] == "unsupported_format"
    assert final_state["extracted_text"] == ""


def test_graph_checkpointing(sample_pdf_path, tmp_path):
    """State is checkpointed after IngestAgent completes.
    
    Uses langgraph-checkpoint-sqlite to verify checkpointing works.
    """
    from langgraph.checkpoint.sqlite import SqliteSaver

    db_path = str(tmp_path / "checkpoints.db")

    with SqliteSaver.from_conn_string(db_path) as checkpointer:
        graph = build_graph()
        # Recompile with checkpointer
        from langgraph.graph import StateGraph, END
        from app.graph.state import ContractState
        from app.graph.nodes.ingest_agent import ingest_agent

        g = StateGraph(ContractState)
        g.add_node("ingest_agent", ingest_agent)

        def route_after_ingest(state):
            if state.get("ingest_error"):
                return "end"
            return "clause_splitter"

        g.add_conditional_edges(
            "ingest_agent",
            route_after_ingest,
            {"end": END, "clause_splitter": END},
        )
        g.set_entry_point("ingest_agent")
        compiled = g.compile(checkpointer=checkpointer)

        config = {"configurable": {"thread_id": "test-thread-1"}}
        initial_state = make_ingest_state(sample_pdf_path)

        final_state = compiled.invoke(initial_state, config=config)

        # Verify checkpoint was created
        checkpoint = checkpointer.get(config)
        assert checkpoint is not None
        # The checkpoint should contain the final state values
        assert "ingest_agent" in str(checkpoint)
```

**Verify**: Run `python -m pytest tests/integration/test_ingest_graph.py -v` — all 3 tests must PASS.

---

## Task 15: Full test suite pass

- [ ] Run the complete test suite:
  ```
  python -m pytest tests/ -v --tb=short
  ```
- [ ] Verify all tests pass (OCR tests may be skipped if Tesseract is not installed — that is acceptable)
- [ ] Expected test count: 2 (config) + 9 (pdf parser) + 6 (docx parser) + 15 (ingest agent) + 3 (integration) = **35 tests total**

---

## Task 16: Run linting and type checking

- [ ] Run `black app/ tests/` — auto-format all code
- [ ] Run `ruff check app/ tests/` — verify no lint errors
- [ ] Run `mypy app/` — verify no type errors (if mypy is installed)

Fix any issues found. Do NOT weaken any tests to fix lint/type errors — fix the implementation instead (per constitution §7).

---

## Summary of all files created/modified

| # | File | Action |
|---|------|--------|
| 1 | `app/__init__.py` | NEW (empty) |
| 2 | `app/graph/__init__.py` | NEW (empty) |
| 3 | `app/graph/nodes/__init__.py` | NEW (empty) |
| 4 | `app/graph/state.py` | MODIFIED (placeholder → full ContractState) |
| 5 | `app/config.py` | NEW |
| 6 | `app/graph/nodes/parsers/__init__.py` | NEW (ParseResult dataclass) |
| 7 | `app/graph/nodes/parsers/pdf_parser.py` | NEW |
| 8 | `app/graph/nodes/parsers/docx_parser.py` | NEW |
| 9 | `app/graph/nodes/ingest_agent.py` | NEW |
| 10 | `app/graph/builder.py` | NEW |
| 11 | `tests/conftest.py` | NEW |
| 12 | `tests/fixtures/sample.pdf` | NEW (binary) |
| 13 | `tests/fixtures/sample.docx` | NEW (binary) |
| 14 | `tests/fixtures/scanned.pdf` | NEW (binary) |
| 15 | `tests/fixtures/corrupted.pdf` | NEW (binary) |
| 16 | `tests/fixtures/unsupported.txt` | NEW |
| 17 | `tests/unit/test_config.py` | NEW |
| 18 | `tests/unit/test_pdf_parser.py` | NEW |
| 19 | `tests/unit/test_docx_parser.py` | NEW |
| 20 | `tests/unit/test_ingest_agent.py` | NEW |
| 21 | `tests/integration/test_ingest_graph.py` | NEW |
