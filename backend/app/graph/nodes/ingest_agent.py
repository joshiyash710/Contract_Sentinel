"""
IngestAgent — Node 1 of the ContractSentinel LangGraph pipeline.

Responsibility: parse an uploaded PDF or DOCX contract into clean extracted
text and populate the IngestAgent slice of ContractState.

Constitution rules observed:
  §3  — all thresholds sourced from app.config, never hardcoded here
  §5  — returns only the state keys this node owns (partial-update rule)
  §6  — document_path (reference) stored; raw binary never placed in state
  §7  — implementation follows TDD cycle defined in tasks.md

Reads from state:
    document_path (str) — path to the uploaded document file

Writes to state (partial dict):
    document_id, document_path, original_filename, uploaded_at,
    extracted_text, ocr_used, ocr_confidence, ingest_error,
    current_node, node_timings
    (+ error_count on error paths only — operator.add reducer)

Does NOT write:
    clauses, report_path, evidence_trail, processing_started_at,
    processing_completed_at, mcp_delivery_status, retry_budgets
"""

import logging
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

import os
import tempfile

import app.config as _config  # Import module, not names, to allow monkeypatching in tests
from app.graph.state import ContractState
from app.graph.nodes.parsers.pdf_parser import parse_pdf
from app.graph.nodes.parsers.docx_parser import parse_docx
from app.graph.nodes.ingest.text_cleaner import strip_document_chrome

# Re-expose as a module-level name so tests can monkeypatch it (feature 044).
INGEST_STRIP_DOCUMENT_CHROME_ENABLED = _config.INGEST_STRIP_DOCUMENT_CHROME_ENABLED


def _materialize_plaintext(document_path: str, ext: str) -> tuple[str, bool]:
    """Return (parse_path, is_temp) for the contract source.

    Feature 036: decrypt an at-rest-encrypted contract to a short-lived temp file. Feature 054: when
    TURSO_DATABASE_URL is set the source lives as a durable blob (not on the ephemeral disk), so read it
    from the blob store; a rehydrated job after a container restart still finds it. On the disk backend
    behavior is byte-identical to pre-054: legacy plaintext (decrypt raises InvalidToken) or encryption
    OFF → return (document_path, False) so the parser reads the original in place."""
    turso = bool(_config.TURSO_DATABASE_URL)
    if not _config.CONTRACT_ENCRYPTION_AT_REST_ENABLED and not turso:
        return document_path, False  # pre-054 disk fast-path (encryption off), unchanged
    from cryptography.fernet import InvalidToken
    from app.security import crypto

    if turso:
        from app import blob_store

        try:
            raw = blob_store.read(document_path, table="upload_blobs")
        except blob_store.BlobNotFound as exc:
            # No durable source (never persisted / already terminal-deleted). FileNotFoundError is an
            # OSError, so the ingest node maps it to 'corrupted_file' (EC-3 parity with the disk path).
            raise FileNotFoundError(str(document_path)) from exc
    else:
        with open(document_path, "rb") as f:
            raw = f.read()

    if _config.CONTRACT_ENCRYPTION_AT_REST_ENABLED:
        try:
            data = crypto.decrypt_bytes(raw)
        except InvalidToken:
            if not turso:
                return document_path, False  # DISK legacy plaintext — parse in place (pre-036, AC-7)
            data = raw  # TURSO: no readable disk path → materialize the plaintext blob below (AC-5)
    else:
        data = raw  # encryption OFF + Turso (encryption OFF + disk already returned above)

    tmp = tempfile.NamedTemporaryFile(suffix=ext, delete=False)
    try:
        tmp.write(data)
        tmp.close()  # close before the parser opens the path (Windows file-lock safety)
    except Exception:
        # A write failure (e.g. disk full) must not leave a plaintext contract temp behind.
        tmp.close()
        try:
            os.unlink(tmp.name)
        except OSError:
            pass
        raise
    return tmp.name, True

logger = logging.getLogger("contractsentinel.ingest")

ALLOWED_EXTENSIONS = {".pdf", ".docx"}

# Re-expose as a module-level name so tests can monkeypatch it directly:
#   monkeypatch.setattr(ingest_agent_module, "INGEST_TIMEOUT_SECONDS", 0)
INGEST_TIMEOUT_SECONDS = _config.INGEST_TIMEOUT_SECONDS


def ingest_agent(state: ContractState) -> dict:
    """LangGraph node function: parse a document and populate ContractState.

    Args:
        state: Current pipeline state. Must have 'document_path' set.

    Returns:
        Partial dict with all IngestAgent-owned keys populated.
        error_count is included only on error paths (operator.add reducer).
    """
    start_time = time.monotonic()
    document_id = str(uuid.uuid4())
    document_path = state["document_path"]
    # Prefer the real uploaded name seeded by the runner (feature 018 / 001-alignment);
    # fall back to the path basename for tests / legacy callers that don't seed it.
    original_filename = state.get("original_filename") or Path(document_path).name
    uploaded_at = datetime.now(timezone.utc).isoformat()
    ext = Path(document_path).suffix.lower()

    # ── Format validation ──────────────────────────────────────────────────────
    if ext not in ALLOWED_EXTENSIONS:
        return _error_return(
            document_id,
            document_path,
            original_filename,
            uploaded_at,
            "unsupported_format",
            f"Unsupported file format '{ext}'. Only .pdf and .docx are accepted.",
            start_time,
        )

    # ── Dispatch to parser ────────────────────────────────────────────────────
    # Feature 036: decrypt an at-rest-encrypted contract to a temp file first; always clean it up.
    try:
        parse_path, _is_temp = _materialize_plaintext(document_path, ext)
    except PermissionError as exc:
        return _error_return(
            document_id, document_path, original_filename, uploaded_at,
            "permission_denied", str(exc), start_time,
        )
    except OSError as exc:  # FileNotFoundError + any read/write failure while materializing
        return _error_return(
            document_id, document_path, original_filename, uploaded_at,
            "corrupted_file", str(exc), start_time,
        )
    try:
        timeout = INGEST_TIMEOUT_SECONDS  # read from module attr — monkeypatchable
        if ext == ".pdf":
            result = parse_pdf(parse_path, timeout_seconds=timeout)
        else:  # .docx
            result = parse_docx(parse_path, timeout_seconds=timeout)

    except FileNotFoundError as exc:
        # Maps to 'corrupted_file': the file was presumably valid at upload time;
        # missing at processing time means the reference is broken.
        # See plan §5 (FileNotFoundError mapping rationale).
        return _error_return(
            document_id,
            document_path,
            original_filename,
            uploaded_at,
            "corrupted_file",
            str(exc),
            start_time,
        )
    except PermissionError as exc:
        return _error_return(
            document_id,
            document_path,
            original_filename,
            uploaded_at,
            "permission_denied",
            str(exc),
            start_time,
        )
    except ValueError as exc:
        return _error_return(
            document_id,
            document_path,
            original_filename,
            uploaded_at,
            "corrupted_file",
            str(exc),
            start_time,
        )
    except TimeoutError as exc:
        return _error_return(
            document_id,
            document_path,
            original_filename,
            uploaded_at,
            "timeout",
            str(exc),
            start_time,
        )
    except Exception as exc:  # noqa: BLE001
        # Catch-all: unknown parse failures treated as corruption (conservative)
        return _error_return(
            document_id,
            document_path,
            original_filename,
            uploaded_at,
            "corrupted_file",
            f"Unexpected error: {exc}",
            start_time,
        )
    finally:
        # Feature 036 (AC-4): delete the decrypted temp file on success OR any parser failure, so no
        # plaintext contract copy is left on disk.
        if _is_temp:
            try:
                os.unlink(parse_path)
            except OSError:
                pass

    # ── Success path ──────────────────────────────────────────────────────────
    elapsed = time.monotonic() - start_time

    # Log evaluation metrics per spec §7 (Evaluation)
    logger.info(
        "IngestAgent completed",
        extra={
            "document_id": document_id,
            "format": ext,
            "ocr_used": result.ocr_used,
            "ocr_confidence": result.ocr_confidence,
            "elapsed_seconds": round(elapsed, 4),
            "char_density": round(len(result.text) / max(1, result.page_count), 2),
            "error_type": None,
        },
    )

    # Feature 044: strip recognizable EDGAR page-footer chrome from the parsed text before it flows
    # into clause segmentation (removes artifact-driven false flags / broken segments). Reversible.
    extracted_text = result.text
    if INGEST_STRIP_DOCUMENT_CHROME_ENABLED:
        extracted_text = strip_document_chrome(result.text)

    # Partial-update: return only keys this node owns (constitution §5)
    return {
        "document_id": document_id,
        "document_path": document_path,
        "original_filename": original_filename,
        "uploaded_at": uploaded_at,
        "extracted_text": extracted_text,
        "ocr_used": result.ocr_used,
        "ocr_confidence": result.ocr_confidence,
        "ingest_error": None,
        "current_node": "ingest_agent",
        "node_timings": {"ingest_agent": elapsed},
        # error_count intentionally OMITTED on success (partial-update rule)
    }


def _error_return(
    document_id: str,
    document_path: str,
    original_filename: str,
    uploaded_at: str,
    error_type: str,
    message: str,
    start_time: float,
) -> dict:
    """Build the standardised error-path return dict.

    Includes error_count: 1 so the operator.add reducer increments the
    pipeline-wide error counter in ContractState.
    """
    elapsed = time.monotonic() - start_time

    logger.warning(
        "IngestAgent error",
        extra={
            "error_type": error_type,
            "error_message": message,
            "elapsed_seconds": round(elapsed, 4),
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
        "error_count": 1,  # operator.add reducer — increments pipeline counter
    }
