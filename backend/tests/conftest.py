"""
Shared pytest fixtures for ContractSentinel backend tests.

Placed at tests/conftest.py (NOT inside fixtures/) so that pytest's
conftest discovery makes all fixtures available to every test file under
tests/unit/ and tests/integration/.
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
    """Path to a file with .pdf extension but invalid binary content."""
    return os.path.join(FIXTURES_DIR, "corrupted.pdf")


@pytest.fixture
def unsupported_txt_path():
    """Path to a .txt file — used to test format rejection."""
    return os.path.join(FIXTURES_DIR, "unsupported.txt")


@pytest.fixture
def nonexistent_path(tmp_path):
    """Path to a file that does not exist on disk."""
    return str(tmp_path / "does_not_exist.pdf")


@pytest.fixture
def unreadable_pdf_path(tmp_path):
    """Path to a PDF file that exists but cannot be read (permissions stripped).

    Note: On Windows, os.chmod(0o000) may not fully remove read permissions
    for the process owner. Tests using this fixture should be treated as
    best-effort on Windows — they may pass or be skipped if the OS ignores
    the permission change.
    """
    path = tmp_path / "unreadable.pdf"
    path.write_bytes(b"%PDF-1.4 minimal content")
    os.chmod(str(path), 0o000)
    yield str(path)
    # Restore permissions so pytest tmp_path cleanup can delete the file
    os.chmod(str(path), 0o644)


def _has_tesseract() -> bool:
    """Return True if the tesseract binary is available in PATH."""
    return shutil.which("tesseract") is not None


requires_tesseract = pytest.mark.skipif(
    not _has_tesseract(),
    reason="Tesseract OCR is not installed — install it to run OCR tests",
)


def make_ingest_state(document_path: str) -> dict:
    """Create a minimal state dict suitable for invoking the ingest_agent node.

    Only supplies the key the IngestAgent reads from state (document_path).
    All other ContractState keys are left to LangGraph to initialise from
    its schema defaults.
    """
    return {"document_path": document_path}
