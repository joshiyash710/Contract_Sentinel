"""
PDF document parser for the ContractSentinel IngestAgent.

Public API:
    parse_pdf(file_path: str, timeout_seconds: int) -> ParseResult

Strategy:
    1. Validate file existence and readability before entering the executor.
    2. Wrap all CPU-bound work (pymupdf + pytesseract) in a
       ThreadPoolExecutor with a configurable timeout.  Uses threads rather
       than asyncio because pytesseract is subprocess-based and blocks the
       calling thread; this is also cross-platform (signal.alarm is Unix-only).
    3. Apply the OCR decision logic defined in plan §2:
         - len(text) < MIN_TEXT_LENGTH_THRESHOLD  → OCR required
         - char_density  < MIN_CHAR_DENSITY_THRESHOLD → OCR required
         - otherwise                               → direct extraction
    4. Aggregate per-word pytesseract confidence into a 0.0–1.0 score.
"""

import logging
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
from pathlib import Path
from typing import List

import fitz  # pymupdf
import pytesseract

import app.config as _config
from app.config import MIN_CHAR_DENSITY_THRESHOLD, MIN_TEXT_LENGTH_THRESHOLD
from app.graph.nodes.parsers import ParseResult

logger = logging.getLogger("contractsentinel.ingest.pdf_parser")

# Feature 055 — re-exposed module-level so tests can monkeypatch it.
PDF_SOURCE_LOCATOR_ENABLED = _config.PDF_SOURCE_LOCATOR_ENABLED


def _extract_text_with_spans(doc) -> tuple:
    """Feature 055: build extracted_text AND a char->(page,bbox) span map from one get_text('dict')
    pass, so offsets and bboxes are exact by construction. Returns (text, page_spans). Lines are joined
    with '\\n' (spans within a line concatenated directly); image blocks (no 'lines') contribute no
    spans. NOTE (OQ-2): this text may differ slightly from plain get_text() — accepted under the flag."""
    buf = []
    spans = []
    offset = 0
    for pageno, page in enumerate(doc, start=1):
        data = page.get_text("dict")
        for block in data.get("blocks", []):
            for line in block.get("lines", []):
                for span in line.get("spans", []):
                    t = span.get("text", "")
                    if not t:
                        continue
                    start = offset
                    buf.append(t)
                    offset += len(t)
                    bbox = span.get("bbox", [0.0, 0.0, 0.0, 0.0])
                    spans.append(
                        {
                            "start": start,
                            "end": offset,
                            "page": pageno,
                            "bbox": [float(c) for c in bbox],
                        }
                    )
                buf.append("\n")  # line separator (mirrors get_text() line breaks)
                offset += 1
    return "".join(buf), spans


def parse_pdf(file_path: str, timeout_seconds: float) -> ParseResult:
    """Extract text from a PDF file, with OCR fallback for scanned documents.

    Args:
        file_path: Absolute or relative path to the PDF file.
        timeout_seconds: Maximum wall-clock seconds for the entire operation.

    Returns:
        ParseResult with extracted text, page count, OCR flag, and confidence.

    Raises:
        FileNotFoundError: file_path does not exist.
        PermissionError: file_path is not readable.
        ValueError: PDF is corrupted / cannot be opened by pymupdf.
        TimeoutError: processing exceeded timeout_seconds.
    """
    path = Path(file_path)

    # ── Pre-flight checks (outside executor — fast, no timeout needed) ─────────
    if not path.exists():
        raise FileNotFoundError(f"File not found: {file_path}")
    # Explicitly test read access. On Windows, os.chmod(0o000) may not block
    # the process owner, so we attempt an actual open() to get the real OS verdict.
    try:
        with path.open("rb"):
            pass
    except PermissionError as exc:
        raise PermissionError(f"Permission denied reading: {file_path}") from exc

    # ── CPU-bound work wrapped in executor for cross-platform timeout ──────────
    def _do_parse() -> ParseResult:
        return _parse_pdf_inner(file_path)

    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(_do_parse)
        try:
            return future.result(timeout=timeout_seconds)
        except FuturesTimeoutError:
            raise TimeoutError(
                f"PDF parsing exceeded timeout of {timeout_seconds}s: {file_path}"
            )


def _parse_pdf_inner(file_path: str) -> ParseResult:
    """Inner parsing logic — runs inside the ThreadPoolExecutor thread."""
    try:
        doc = fitz.open(file_path)
    except Exception as exc:
        raise ValueError(f"Corrupted PDF (cannot open): {file_path}") from exc

    try:
        page_count = len(doc)
        # Feature 055: flag ON → build text + char->(page,bbox) map together (offsets exact). Flag OFF
        # → the current plain join, no span map (byte-identical extracted_text, AC-2).
        if PDF_SOURCE_LOCATOR_ENABLED:
            extracted_text, page_spans = _extract_text_with_spans(doc)
        else:
            extracted_text, page_spans = "\n".join(page.get_text() for page in doc), None
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
                page_spans=page_spans,  # feature 055 (None when flag off)
            )

        # ── OCR path ────────────────────────────────────────────────────────────
        logger.debug(
            "OCR triggered",
            extra={
                "file": file_path,
                "chars": len(extracted_text),
                "density": char_density,
                "pages": page_count,
            },
        )
        ocr_texts: List[str] = []
        page_confidences: List[float] = []

        for page in doc:
            pix = page.get_pixmap(dpi=300)
            # Convert pymupdf pixmap to PIL Image
            import io
            from PIL import Image

            img_bytes = io.BytesIO(pix.tobytes("png"))
            image = Image.open(img_bytes)

            # Collect per-word confidence scores
            data = pytesseract.image_to_data(image, output_type=pytesseract.Output.DICT)
            valid_confs = [c for c in data["conf"] if c != -1]
            page_conf = sum(valid_confs) / len(valid_confs) if valid_confs else 0.0
            page_confidences.append(page_conf)

            # Collect OCR text
            page_text = pytesseract.image_to_string(image)
            ocr_texts.append(page_text)

        # Normalise document-level confidence from pytesseract's 0–100 scale to 0–1
        doc_confidence = (
            sum(page_confidences) / len(page_confidences) / 100.0
            if page_confidences
            else 0.0
        )
        doc_confidence = max(0.0, min(1.0, doc_confidence))  # clamp

        return ParseResult(
            text="\n".join(ocr_texts),
            page_count=page_count,
            ocr_used=True,
            ocr_confidence=doc_confidence,
        )

    finally:
        doc.close()
