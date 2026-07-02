"""
Unit tests for app.graph.nodes.parsers.pdf_parser.parse_pdf().

TDD phase: written before pdf_parser.py exists; import fails until Task 8.
Run: python -m pytest tests/unit/test_pdf_parser.py -v
Expected before Task 8: FAIL with ImportError
Expected after  Task 8: PASS (OCR tests skipped if Tesseract absent)
"""

import pytest
import fitz  # pymupdf — used to create in-test PDFs

from app.graph.nodes.parsers import ParseResult

# This import will raise ImportError until Task 8 creates the module — expected.
from app.graph.nodes.parsers.pdf_parser import parse_pdf

# ─── Direct text extraction ────────────────────────────────────────────────────


def test_parse_pdf_digital_text(sample_pdf_path):
    """Text-layer PDF: direct extraction succeeds without OCR."""
    result = parse_pdf(sample_pdf_path, timeout_seconds=60)
    assert isinstance(result, ParseResult)
    assert len(result.text) >= 200
    assert result.ocr_used is False
    assert result.ocr_confidence is None
    assert result.page_count >= 1


def test_parse_pdf_page_count(sample_pdf_path):
    """Page count in result matches pymupdf's own page count."""
    doc = fitz.open(sample_pdf_path)
    expected_pages = len(doc)
    doc.close()

    result = parse_pdf(sample_pdf_path, timeout_seconds=60)
    assert result.page_count == expected_pages


# ─── OCR fallback ──────────────────────────────────────────────────────────────


@pytest.mark.skipif(
    not __import__("shutil").which("tesseract"),
    reason="Tesseract OCR is not installed",
)
def test_parse_pdf_empty_triggers_ocr(scanned_pdf_path):
    """PDF with <50 extractable chars triggers OCR (ocr_used=True)."""
    result = parse_pdf(scanned_pdf_path, timeout_seconds=60)
    assert result.ocr_used is True


@pytest.mark.skipif(
    not __import__("shutil").which("tesseract"),
    reason="Tesseract OCR is not installed",
)
def test_parse_pdf_low_density_triggers_ocr(tmp_path):
    """Multi-page PDF where char density <100/page triggers OCR."""
    # 3-page PDF, each page has ~10 chars: total ~30, density ~10/page < 100
    doc = fitz.open()
    for i in range(3):
        page = doc.new_page()
        page.insert_text((72, 72), f"p{i + 1}", fontsize=11)
    path = str(tmp_path / "low_density.pdf")
    doc.save(path)
    doc.close()

    result = parse_pdf(path, timeout_seconds=60)
    assert result.ocr_used is True


@pytest.mark.skipif(
    not __import__("shutil").which("tesseract"),
    reason="Tesseract OCR is not installed",
)
def test_parse_pdf_ocr_confidence_captured(scanned_pdf_path):
    """OCR path normalises confidence to 0.0–1.0 range."""
    result = parse_pdf(scanned_pdf_path, timeout_seconds=60)
    assert result.ocr_used is True
    assert result.ocr_confidence is not None
    assert 0.0 <= result.ocr_confidence <= 1.0


# ─── Error handling ────────────────────────────────────────────────────────────


def test_parse_pdf_corrupted_raises_value_error(corrupted_pdf_path):
    """Corrupted PDF content raises ValueError."""
    with pytest.raises(ValueError):
        parse_pdf(corrupted_pdf_path, timeout_seconds=60)


def test_parse_pdf_not_found_raises(nonexistent_path):
    """Missing file raises FileNotFoundError before entering executor."""
    with pytest.raises(FileNotFoundError):
        parse_pdf(nonexistent_path, timeout_seconds=60)


def test_parse_pdf_permission_denied_raises(unreadable_pdf_path, mock_permission_error):
    """File that cannot be read raises PermissionError.

    On Unix: os.chmod(0o000) prevents the real OS open() from succeeding.
    On Windows: mock_permission_error patches pathlib.Path.open to raise
    PermissionError, simulating the same condition since os.chmod cannot
    reliably deny reads on Windows for the process owner.
    """
    with pytest.raises(PermissionError):
        parse_pdf(unreadable_pdf_path, timeout_seconds=60)


def test_parse_pdf_timeout_raises(sample_pdf_path):
    """Processing that exceeds timeout raises TimeoutError.

    timeout_seconds=0 forces future.result(timeout=0) to raise immediately
    because the executor job cannot possibly complete in 0 seconds.
    """
    with pytest.raises(TimeoutError):
        parse_pdf(sample_pdf_path, timeout_seconds=0)
