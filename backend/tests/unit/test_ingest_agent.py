"""
Unit tests for app.graph.nodes.ingest_agent.ingest_agent().

TDD phase: written BEFORE ingest_agent.py exists (Task 11).
Run: python -m pytest tests/unit/test_ingest_agent.py -v
Expected before Task 12: FAIL with ImportError
Expected after  Task 12: PASS
"""

import uuid
from datetime import datetime
import pytest

# This import will raise ImportError until Task 12 — expected for TDD.
from app.graph.nodes.ingest_agent import ingest_agent

# ─── Success paths ─────────────────────────────────────────────────────────────


def test_ingest_pdf_success(sample_pdf_path):
    """Success path for PDF: all state keys populated, ingest_error is None."""
    state = {"document_path": sample_pdf_path}
    result = ingest_agent(state)

    assert result["ingest_error"] is None
    assert len(result["extracted_text"]) >= 200
    assert result["ocr_used"] is False
    assert result["document_path"] == sample_pdf_path
    assert result["original_filename"] == "sample.pdf"
    assert result["current_node"] == "ingest_agent"


def test_ingest_docx_success(sample_docx_path):
    """Success path for DOCX: all state keys populated, ingest_error is None."""
    state = {"document_path": sample_docx_path}
    result = ingest_agent(state)

    assert result["ingest_error"] is None
    assert len(result["extracted_text"]) >= 200
    assert result["original_filename"] == "sample.docx"


# ─── Format validation ─────────────────────────────────────────────────────────


def test_ingest_unsupported_format(unsupported_txt_path):
    """Unsupported format returns ingest_error with error_type 'unsupported_format'."""
    state = {"document_path": unsupported_txt_path}
    result = ingest_agent(state)

    assert result["ingest_error"] is not None
    assert result["ingest_error"]["error_type"] == "unsupported_format"
    assert result["extracted_text"] == ""
    assert result["error_count"] == 1


# ─── File-level error handling ─────────────────────────────────────────────────


def test_ingest_corrupted_file(corrupted_pdf_path):
    """Corrupted PDF returns ingest_error with error_type 'corrupted_file'."""
    state = {"document_path": corrupted_pdf_path}
    result = ingest_agent(state)

    assert result["ingest_error"] is not None
    assert result["ingest_error"]["error_type"] == "corrupted_file"
    assert result["error_count"] == 1


def test_ingest_file_not_found(nonexistent_path):
    """Missing file returns ingest_error with error_type 'corrupted_file'.

    FileNotFoundError maps to 'corrupted_file' per plan §5 rationale.
    The ingest_error message must contain the exception detail.
    """
    state = {"document_path": nonexistent_path}
    result = ingest_agent(state)

    assert result["ingest_error"] is not None
    assert result["ingest_error"]["error_type"] == "corrupted_file"
    assert "message" in result["ingest_error"]
    assert result["error_count"] == 1


def test_ingest_permission_denied(unreadable_pdf_path, mock_permission_error):
    """Unreadable file returns ingest_error with error_type 'permission_denied'.

    On Unix: os.chmod(0o000) prevents the real OS open() from succeeding.
    On Windows: mock_permission_error patches pathlib.Path.open to raise
    PermissionError, since os.chmod does not reliably deny reads for the
    process owner on Windows.
    """
    state = {"document_path": unreadable_pdf_path}
    result = ingest_agent(state)

    assert result["ingest_error"] is not None
    assert result["ingest_error"]["error_type"] == "permission_denied"
    assert result["error_count"] == 1


def test_ingest_timeout(sample_pdf_path):
    """Parsing that exceeds INGEST_TIMEOUT_SECONDS returns error_type 'timeout'.

    We mock parse_pdf to raise TimeoutError directly (the same exception the
    ThreadPoolExecutor raises after timeout). This tests the except TimeoutError
    handler in ingest_agent without relying on actual wall-clock timing.
    """
    from unittest.mock import patch

    def raise_timeout(*args, **kwargs):
        raise TimeoutError("PDF parsing exceeded timeout of 0s")

    with patch("app.graph.nodes.ingest_agent.parse_pdf", raise_timeout):
        state = {"document_path": sample_pdf_path}
        result = ingest_agent(state)

    assert result["ingest_error"] is not None
    assert result["ingest_error"]["error_type"] == "timeout"
    assert result["error_count"] == 1


# ─── State field correctness ───────────────────────────────────────────────────


def test_ingest_document_id_is_uuid(sample_pdf_path):
    """document_id is a valid UUID4 string."""
    state = {"document_path": sample_pdf_path}
    result = ingest_agent(state)

    parsed = uuid.UUID(result["document_id"], version=4)
    assert str(parsed) == result["document_id"]


def test_ingest_uploaded_at_is_iso(sample_pdf_path):
    """uploaded_at is a valid ISO 8601 timestamp string."""
    state = {"document_path": sample_pdf_path}
    result = ingest_agent(state)

    dt = datetime.fromisoformat(result["uploaded_at"])
    assert dt is not None


def test_ingest_node_timing_recorded(sample_pdf_path):
    """node_timings['ingest_agent'] is a positive float."""
    state = {"document_path": sample_pdf_path}
    result = ingest_agent(state)

    assert "ingest_agent" in result["node_timings"]
    assert isinstance(result["node_timings"]["ingest_agent"], float)
    assert result["node_timings"]["ingest_agent"] >= 0


# ─── Partial-update rule (constitution §5) ─────────────────────────────────────


def test_ingest_partial_update_only(sample_pdf_path):
    """Return dict must NOT contain keys owned by other nodes."""
    state = {"document_path": sample_pdf_path}
    result = ingest_agent(state)

    forbidden_keys = [
        "clauses",
        "report_path",
        "evidence_trail",
        "mcp_delivery_status",
        "retry_budgets",
        "processing_started_at",
        "processing_completed_at",
    ]
    for key in forbidden_keys:
        assert key not in result, f"Return dict must not contain '{key}'"


def test_ingest_success_omits_error_count(sample_pdf_path):
    """Success path must NOT include error_count (partial-update rule)."""
    state = {"document_path": sample_pdf_path}
    result = ingest_agent(state)

    assert "error_count" not in result


def test_ingest_error_increments_error_count(corrupted_pdf_path):
    """Error paths must include error_count: 1 for the operator.add reducer."""
    state = {"document_path": corrupted_pdf_path}
    result = ingest_agent(state)

    assert result.get("error_count") == 1


def test_ingest_does_not_set_processing_started_at(sample_pdf_path):
    """processing_started_at is pipeline-level, NOT set by IngestAgent."""
    state = {"document_path": sample_pdf_path}
    result = ingest_agent(state)

    assert "processing_started_at" not in result


def test_ingest_no_clause_output(sample_pdf_path):
    """IngestAgent must not produce any clauses key output."""
    state = {"document_path": sample_pdf_path}
    result = ingest_agent(state)

    assert "clauses" not in result


@pytest.mark.skipif(
    not __import__("shutil").which("tesseract"),
    reason="Tesseract OCR is not installed",
)
def test_ingest_ocr_fallback_with_low_confidence(scanned_pdf_path):
    """OCR: processing continues with low confidence; score is stored 0–1."""
    state = {"document_path": scanned_pdf_path}
    result = ingest_agent(state)

    assert result["ingest_error"] is None
    assert result["ocr_used"] is True
    assert result["ocr_confidence"] is not None
    assert 0.0 <= result["ocr_confidence"] <= 1.0


# ── Feature 036: contract encryption at rest ─────────────────────────────────


def _encrypted_copy(src_path, tmp_path, suffix):
    from app.security import crypto

    with open(src_path, "rb") as f:
        enc = crypto.encrypt_bytes(f.read())
    dest = tmp_path / f"enc{suffix}"
    dest.write_bytes(enc)
    return str(dest)


def test_ingest_encrypted_pdf_parses_like_plaintext(sample_pdf_path, tmp_path):
    """AC-3: an at-rest-encrypted PDF yields the same extracted_text as the plaintext."""
    import app.graph.nodes.ingest_agent as ia

    plain = ia.ingest_agent({"document_path": sample_pdf_path})
    enc_path = _encrypted_copy(sample_pdf_path, tmp_path, ".pdf")
    enc = ia.ingest_agent({"document_path": enc_path})

    assert enc.get("ingest_error") is None
    assert enc["extracted_text"] == plain["extracted_text"]
    # AC-4: no leftover temp file — only our encrypted source remains in tmp_path
    leftover = [p for p in tmp_path.iterdir()]
    assert leftover == [__import__("pathlib").Path(enc_path)]


def test_ingest_legacy_plaintext_still_parses(sample_pdf_path):
    """AC-5: a plaintext PDF (pre-036) is parsed in place even with the flag ON."""
    from app.graph.nodes.ingest_agent import ingest_agent

    result = ingest_agent({"document_path": sample_pdf_path})
    assert result.get("ingest_error") is None
    assert len(result["extracted_text"]) > 100


def test_ingest_flag_off_parses_in_place(sample_pdf_path, tmp_path, monkeypatch):
    """AC-6: flag OFF → no decrypt/temp; plaintext parsed in place."""
    import app.config as _cfg
    from app.graph.nodes.ingest_agent import ingest_agent

    monkeypatch.setattr(_cfg, "CONTRACT_ENCRYPTION_AT_REST_ENABLED", False)
    result = ingest_agent({"document_path": sample_pdf_path})
    assert result.get("ingest_error") is None
    assert len(result["extracted_text"]) > 100


# ─── Feature 044: document-chrome stripping (AC-5) ─────────────────────────────

import app.graph.nodes.ingest_agent as ingest_agent_module  # noqa: E402
from types import SimpleNamespace  # noqa: E402


def _fake_parse_with_footer(*args, **kwargs):
    """A parse result whose text carries an EDGAR page footer + a clean clause."""
    return SimpleNamespace(
        text=(
            "1. Definitions. The parties agree to the following terms.\n"
            "Source: ARCONIC ROLLED PRODUCTS CORP, 10-12B, 12/17/2019\n"
            "2. Payment. Net thirty (30) days from invoice."
        ),
        ocr_used=False,
        ocr_confidence=None,
        page_count=1,
    )


def test_ingest_strips_edgar_footer_when_enabled(monkeypatch, sample_pdf_path):
    """AC-5: with the flag ON, the EDGAR footer is removed from extracted_text."""
    monkeypatch.setattr(ingest_agent_module, "INGEST_STRIP_DOCUMENT_CHROME_ENABLED", True)
    monkeypatch.setattr(ingest_agent_module, "parse_pdf", _fake_parse_with_footer)

    result = ingest_agent({"document_path": sample_pdf_path})

    assert result["ingest_error"] is None
    assert "Source: ARCONIC" not in result["extracted_text"]
    assert "1. Definitions." in result["extracted_text"]
    assert "2. Payment." in result["extracted_text"]


def test_ingest_strip_reversible_when_disabled(monkeypatch, sample_pdf_path):
    """AC-5 reversibility: flag OFF ⇒ extracted_text is the raw parser text (footer intact)."""
    monkeypatch.setattr(ingest_agent_module, "INGEST_STRIP_DOCUMENT_CHROME_ENABLED", False)
    monkeypatch.setattr(ingest_agent_module, "parse_pdf", _fake_parse_with_footer)

    result = ingest_agent({"document_path": sample_pdf_path})

    assert result["ingest_error"] is None
    assert result["extracted_text"] == _fake_parse_with_footer().text  # byte-identical to today
