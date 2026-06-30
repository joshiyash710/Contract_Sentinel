"""
DOCX document parser for the ContractSentinel IngestAgent.

Public API:
    parse_docx(file_path: str, timeout_seconds: int) -> ParseResult

Strategy:
    1. Validate file existence and readability before entering the executor.
    2. Wrap all CPU-bound work in a ThreadPoolExecutor with timeout.
    3. Use python-docx for direct paragraph text extraction.
    4. Estimate page count via heuristic: max(1, len(text) // 3000).
       Rationale: ~3000 chars/page for standard legal contract formatting.
       This value is ONLY used for the char-density OCR decision, not downstream.
    5. Same OCR decision thresholds as pdf_parser (from app.config).
    6. For OCR, attempt to render DOCX pages via pymupdf.
       If pymupdf cannot render the DOCX (some variants unsupported), catch the
       rendering error, log a warning, and return direct text with ocr_used=False.
       The parser only fails if BOTH direct extraction AND OCR fail entirely.
"""

import logging
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
from pathlib import Path
from typing import List

import docx  # python-docx

from app.config import MIN_CHAR_DENSITY_THRESHOLD, MIN_TEXT_LENGTH_THRESHOLD
from app.graph.nodes.parsers import ParseResult

logger = logging.getLogger("contractsentinel.ingest.docx_parser")


def parse_docx(file_path: str, timeout_seconds: float) -> ParseResult:
    """Extract text from a DOCX file, with OCR fallback for scanned documents.

    Args:
        file_path: Absolute or relative path to the DOCX file.
        timeout_seconds: Maximum wall-clock seconds for the entire operation.

    Returns:
        ParseResult with extracted text, page count, OCR flag, and confidence.

    Raises:
        FileNotFoundError: file_path does not exist.
        PermissionError: file_path is not readable.
        ValueError: DOCX is corrupted / cannot be opened by python-docx.
        TimeoutError: processing exceeded timeout_seconds.
    """
    path = Path(file_path)

    # ── Pre-flight checks ──────────────────────────────────────────────────────
    if not path.exists():
        raise FileNotFoundError(f"File not found: {file_path}")
    try:
        with path.open("rb"):
            pass
    except PermissionError as exc:
        raise PermissionError(f"Permission denied reading: {file_path}") from exc

    # ── CPU-bound work in executor for cross-platform timeout ─────────────────
    def _do_parse() -> ParseResult:
        return _parse_docx_inner(file_path)

    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(_do_parse)
        try:
            return future.result(timeout=timeout_seconds)
        except FuturesTimeoutError:
            raise TimeoutError(
                f"DOCX parsing exceeded timeout of {timeout_seconds}s: {file_path}"
            )


def _parse_docx_inner(file_path: str) -> ParseResult:
    """Inner parsing logic — runs inside the ThreadPoolExecutor thread."""
    # ── Direct extraction via python-docx ────────────────────────────────────
    try:
        document = docx.Document(file_path)
    except Exception as exc:
        raise ValueError(f"Corrupted DOCX (cannot open): {file_path}") from exc

    extracted_text = "\n".join(p.text for p in document.paragraphs)

    # Heuristic page count (python-docx has no page count API)
    page_count = max(1, len(extracted_text) // 3000)
    char_density = len(extracted_text) / max(1, page_count)

    needs_ocr = (
        len(extracted_text) < MIN_TEXT_LENGTH_THRESHOLD
        or char_density < MIN_CHAR_DENSITY_THRESHOLD
    )

    if not needs_ocr:
        logger.debug(
            "Direct extraction successful",
            extra={
                "file": file_path,
                "chars": len(extracted_text),
                "pages": page_count,
            },
        )
        return ParseResult(
            text=extracted_text,
            page_count=page_count,
            ocr_used=False,
            ocr_confidence=None,
        )

    # ── OCR path: attempt pymupdf rendering ──────────────────────────────────
    logger.debug(
        "OCR triggered for DOCX",
        extra={
            "file": file_path,
            "chars": len(extracted_text),
            "density": char_density,
            "pages": page_count,
        },
    )

    try:
        import fitz  # pymupdf — DOCX rendering is best-effort

        fitz_doc = fitz.open(file_path)
    except Exception as render_exc:
        # pymupdf cannot render this DOCX variant — fall back to direct text
        logger.warning(
            "pymupdf cannot render DOCX for OCR, falling back to direct text: %s (%s)",
            file_path,
            render_exc,
        )
        return ParseResult(
            text=extracted_text,
            page_count=page_count,
            ocr_used=False,
            ocr_confidence=None,
        )

    # pymupdf succeeded — run pytesseract on rendered pages
    try:
        import io
        import pytesseract
        from PIL import Image

        ocr_texts: List[str] = []
        page_confidences: List[float] = []

        for page in fitz_doc:
            pix = page.get_pixmap(dpi=300)
            img_bytes = io.BytesIO(pix.tobytes("png"))
            image = Image.open(img_bytes)

            data = pytesseract.image_to_data(image, output_type=pytesseract.Output.DICT)
            valid_confs = [c for c in data["conf"] if c != -1]
            page_conf = sum(valid_confs) / len(valid_confs) if valid_confs else 0.0
            page_confidences.append(page_conf)

            ocr_texts.append(pytesseract.image_to_string(image))

        doc_confidence = (
            sum(page_confidences) / len(page_confidences) / 100.0
            if page_confidences
            else 0.0
        )
        doc_confidence = max(0.0, min(1.0, doc_confidence))

        return ParseResult(
            text="\n".join(ocr_texts),
            page_count=page_count,
            ocr_used=True,
            ocr_confidence=doc_confidence,
        )

    except Exception as ocr_exc:
        # OCR failed after rendering — return direct text gracefully
        logger.warning(
            "OCR failed on DOCX after rendering, falling back to direct text: %s (%s)",
            file_path,
            ocr_exc,
        )
        return ParseResult(
            text=extracted_text,
            page_count=page_count,
            ocr_used=False,
            ocr_confidence=None,
        )
    finally:
        fitz_doc.close()
