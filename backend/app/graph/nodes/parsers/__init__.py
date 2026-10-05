"""
Shared types for document parser modules.

ParseResult is the single return type for both:
  - pdf_parser.parse_pdf()
  - docx_parser.parse_docx()

Defined here (in the parsers package __init__) so both parsers can import it
as a peer without either one depending on the other's module.
"""

from dataclasses import dataclass
from typing import List, Optional


@dataclass
class ParseResult:
    """Result of parsing a document file.

    Attributes:
        text: The full extracted text content (direct or OCR).
        page_count: Number of pages in the document.
        ocr_used: Whether OCR was needed for text extraction.
        ocr_confidence: OCR confidence score normalised to 0.0–1.0,
            or None when ocr_used is False.
        page_spans: Feature 055 — a char->(page,bbox) map over `text`, each entry
            {"start": int, "end": int, "page": int, "bbox": [x0,y0,x1,y1]}. Populated only by the
            PDF text-layer path when PDF_SOURCE_LOCATOR_ENABLED; None for DOCX, OCR, and flag-off.
    """

    text: str
    page_count: int
    ocr_used: bool
    ocr_confidence: Optional[float]
    page_spans: Optional[List[dict]] = None
