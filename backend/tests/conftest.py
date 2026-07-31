"""
Shared pytest fixtures for ContractSentinel backend tests.

Placed at tests/conftest.py (NOT inside fixtures/) so that pytest's
conftest discovery makes all fixtures available to every test file under
tests/unit/ and tests/integration/.
"""

import os
import sys
import pytest
from unittest.mock import patch

FIXTURES_DIR = os.path.join(os.path.dirname(__file__), "fixtures")


@pytest.fixture(autouse=True)
def _isolate_encryption_key_suite_wide(tmp_path_factory, monkeypatch):
    """Feature 032: keep the at-rest Fernet key out of the repo's data/ dir for EVERY test.

    Without this, the first test that touches OAuth-token storage would generate/read the real
    data/encryption_key. Points the key file at a per-session temp path and resets the module cache
    so no test writes into the working tree.
    """
    import app.config as _cfg
    from app.security import crypto

    enc_dir = tmp_path_factory.mktemp("enc")
    key_path = enc_dir / "encryption_key"
    monkeypatch.setattr(crypto, "_KEY", None, raising=False)
    monkeypatch.delenv(_cfg.ENCRYPTION_KEY_ENV, raising=False)
    monkeypatch.setattr(_cfg, "ENCRYPTION_KEY_FILE", str(key_path))
    # Feature 032 (W1): point the central token at an ABSENT temp path by default so
    # materialize_central_token_tempfile() is deterministic (returns None) regardless of whether a
    # real data/secrets/google_token.json exists on the dev box. Tests that exercise a central token
    # set GOOGLE_OAUTH_TOKEN_PATH explicitly.
    monkeypatch.setattr(_cfg, "GOOGLE_OAUTH_TOKEN_PATH", str(enc_dir / "central_token_absent.json"))
    # Feature 032 (W2): AUTH_COOKIE_SECURE now defaults to True (needs TLS). The TestClient talks
    # plain http, so — like local dev over http — force it False for the suite. Tests that assert the
    # Secure flag (AC-7) monkeypatch it back to True explicitly.
    monkeypatch.setattr(_cfg, "AUTH_COOKIE_SECURE", False)
    yield
    monkeypatch.setattr(crypto, "_KEY", None, raising=False)


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
    """Path to a PDF file that exists but cannot be read.

    On Unix/macOS: removes read permissions via os.chmod so that the actual
    OS-level open() raises PermissionError.
    On Windows: os.chmod(0o000) does not deny reads for the process owner, so
    the file is created normally. Tests on Windows that need a permission-denied
    scenario must use the `mock_permission_error` fixture alongside this one.
    """
    path = tmp_path / "unreadable.pdf"
    path.write_bytes(b"%PDF-1.4 minimal content")

    if sys.platform != "win32":
        os.chmod(str(path), 0o000)
        yield str(path)
        os.chmod(str(path), 0o644)
    else:
        yield str(path)


@pytest.fixture
def mock_permission_error():
    """Patch pathlib.Path.open to raise PermissionError on all platforms.

    Use this on Windows (where os.chmod cannot reliably deny reads) to simulate
    a permission-denied condition at the parser's readability-check layer.
    The patch targets pathlib.Path.open because both pdf_parser and docx_parser
    check readability with `path.open("rb")` before doing any real work.

    Usage in a test function::

        def test_something(unreadable_pdf_path, mock_permission_error):
            with pytest.raises(PermissionError):
                parse_pdf(unreadable_pdf_path, timeout_seconds=60)
    """
    with patch(
        "pathlib.Path.open", side_effect=PermissionError("Access denied (mocked)")
    ):
        yield


# Single source of truth for this marker lives in tests/markers.py.
# Import it here so it is available both to conftest-fixture consumers
# and to any test file that imports it directly from tests.markers.
from tests.markers import requires_tesseract  # noqa: E402,F401


def make_ingest_state(document_path: str) -> dict:
    """Create a minimal state dict suitable for invoking the ingest_agent node.

    Only supplies the key the IngestAgent reads from state (document_path).
    All other ContractState keys are left to LangGraph to initialise from
    its schema defaults.
    """
    return {"document_path": document_path}
