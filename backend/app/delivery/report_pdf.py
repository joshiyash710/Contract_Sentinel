"""
Branded PDF renderer for the delivery layer (feature 030, Phase 1).

Turns a ContractReport (the JSON sibling Node 7 already writes) into a polished,
trustworthy-SaaS-looking PDF. Delivery-layer only — NOT a graph node; reads no
ContractState. Pure and offline: same report → same document.

Content is built via the pure `report_text_blocks(report)` seam (the ordered list
of escaped/truncated text strings) so the layout is unit-testable without parsing
the PDF. `render_report_pdf` composes those into reportlab flowables and writes the file.
"""

from __future__ import annotations

from pathlib import Path
from typing import List
from xml.sax.saxutils import escape as _xml_escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import LETTER
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import (
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

import app.config as _config
from app.models.report import ContractReport, ReportFinding

# Module-level config aliases (mirrors delivery_step.py re-exposure; monkeypatchable in tests).
REPORT_PDF_CLAUSE_MAX_CHARS = _config.REPORT_PDF_CLAUSE_MAX_CHARS
REPORT_PDF_RATIONALE_MAX_CHARS = _config.REPORT_PDF_RATIONALE_MAX_CHARS
REPORT_PDF_REWRITE_MAX_CHARS = _config.REPORT_PDF_REWRITE_MAX_CHARS
REPORT_BRAND_NAME = _config.REPORT_BRAND_NAME
REPORT_BRAND_ACCENT_HEX = _config.REPORT_BRAND_ACCENT_HEX
REPORT_BRAND_FOOTER = _config.REPORT_BRAND_FOOTER

_SEVERITY_COLORS = {
    "high": colors.HexColor("#dc2626"),   # red
    "medium": colors.HexColor("#d97706"),  # amber
    "low": colors.HexColor("#0f766e"),     # teal
}
_SEVERITY_LABELS = {"high": "High", "medium": "Medium", "low": "Low"}

# Feature 038: degraded-analysis banner text (single source for the seam + the flowable).
_DEGRADED_BANNER = (
    "⚠ Degraded analysis — the AI model was unavailable for part or all of this run. "
    "Severities marked (auto-assigned) were set by a fail-safe default, not by model "
    "judgment. Do not rely on them; re-run this analysis when the model is available."
)


def _esc(s) -> str:
    """Escape for both safety and reportlab Paragraph mini-markup correctness."""
    return _xml_escape(str(s if s is not None else ""))


def _trunc(s: str, n: int) -> str:
    s = s or ""
    return s if len(s) <= n else s[: max(0, n - 1)].rstrip() + "…"


def _finding_blocks(f: ReportFinding) -> List[str]:
    """Ordered escaped/truncated text strings for one finding."""
    level = (f.risk_level or "").lower()
    sev = _SEVERITY_LABELS.get(level, "Severity unavailable")
    # Feature 038: mark an auto-defaulted (fail-safe) severity as not a real model judgment.
    auto = " (auto-assigned)" if f.is_failsafe else ""
    ctype = f.clause_type or "general"
    sec = f" · Section {f.section_number}" if f.section_number else ""
    blocks = [
        f"{sev}{auto} — {_esc(ctype)}{_esc(sec)}",
        _esc(_trunc(f.clause_text, REPORT_PDF_CLAUSE_MAX_CHARS)),
    ]
    if f.risk_rationale:
        blocks.append("Why this is flagged: " + _esc(_trunc(f.risk_rationale, REPORT_PDF_RATIONALE_MAX_CHARS)))
    if f.rewrite_state == "rewritten" and f.suggested_rewrite:
        blocks.append("Suggested rewrite: " + _esc(_trunc(f.suggested_rewrite, REPORT_PDF_REWRITE_MAX_CHARS)))
    if f.evidence:
        blocks.append(f"Evidence: {len(f.evidence)} source(s)")
    return blocks


def report_text_blocks(report: ContractReport) -> List[str]:
    """Pure seam: the ordered list of text strings the PDF renders (all escaped/truncated).

    Used by the renderer to build flowables and by tests to assert content without
    parsing the emitted PDF. Deterministic.
    """
    s = report.summary
    date = report.generated_at or report.uploaded_at or ""
    blocks: List[str] = [
        _esc(REPORT_BRAND_NAME),
        "Contract Risk Report",
        f"Document: {_esc(report.original_filename)}",
        f"Generated: {_esc(date[:10])}",
        f"Clauses reviewed: {s.total_clauses}  ·  Findings: {s.validated_findings}  ·  "
        f"Clean: {s.clean_clauses}",
        f"High: {s.high}   Medium: {s.medium}   Low: {s.low}",
    ]
    if report.analysis_degraded:
        blocks.append(_DEGRADED_BANNER)
    if not report.findings:
        blocks.append(f"No risks flagged — {s.total_clauses} clauses reviewed, all clean.")
    else:
        for f in report.findings:
            blocks.extend(_finding_blocks(f))
    blocks.append(_esc(REPORT_BRAND_FOOTER))
    return blocks


# ── reportlab layout ─────────────────────────────────────────────────────────
def _styles():
    ss = getSampleStyleSheet()
    accent = colors.HexColor(REPORT_BRAND_ACCENT_HEX)
    return {
        "wordmark": ParagraphStyle(
            "wordmark", parent=ss["Title"], textColor=colors.white, fontSize=22,
            leading=26, alignment=TA_LEFT,
        ),
        "subtitle": ParagraphStyle(
            "subtitle", parent=ss["Normal"], textColor=colors.white, fontSize=11,
        ),
        "meta": ParagraphStyle("meta", parent=ss["Normal"], fontSize=10, textColor=accent),
        "sevH": ParagraphStyle("sevH", parent=ss["Heading3"], fontSize=12, spaceBefore=10),
        "body": ParagraphStyle("body", parent=ss["Normal"], fontSize=10, leading=14),
        "rewrite": ParagraphStyle(
            "rewrite", parent=ss["Normal"], fontSize=10, leading=14,
            leftIndent=8, textColor=colors.HexColor("#0f766e"),
        ),
        "footer": ParagraphStyle("footer", parent=ss["Normal"], fontSize=8, textColor=colors.grey),
        "accent": accent,
    }


def _header_band(report: ContractReport, st) -> Table:
    inner = [
        Paragraph(_esc(REPORT_BRAND_NAME), st["wordmark"]),
        Paragraph("Contract Risk Report", st["subtitle"]),
    ]
    t = Table([[inner]], colWidths=[6.5 * inch])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), st["accent"]),
        ("LEFTPADDING", (0, 0), (-1, -1), 14),
        ("RIGHTPADDING", (0, 0), (-1, -1), 14),
        ("TOPPADDING", (0, 0), (-1, -1), 12),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 12),
    ]))
    return t


def _summary_band(report: ContractReport, st) -> Table:
    s = report.summary
    header = ["Clauses", "Findings", "Clean", "High", "Medium", "Low"]
    row = [s.total_clauses, s.validated_findings, s.clean_clauses, s.high, s.medium, s.low]
    t = Table([header, [str(x) for x in row]], colWidths=[1.08 * inch] * 6)
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#f1f5f9")),
        ("TEXTCOLOR", (0, 0), (-1, 0), st["accent"]),
        ("TEXTCOLOR", (3, 1), (3, 1), _SEVERITY_COLORS["high"]),
        ("TEXTCOLOR", (4, 1), (4, 1), _SEVERITY_COLORS["medium"]),
        ("TEXTCOLOR", (5, 1), (5, 1), _SEVERITY_COLORS["low"]),
        ("FONTSIZE", (0, 0), (-1, -1), 10),
        ("FONTSIZE", (0, 1), (-1, 1), 14),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#e2e8f0")),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))
    return t


def _build_flowables(report: ContractReport) -> list:
    st = _styles()
    flow: list = [_header_band(report, st), Spacer(1, 10)]
    date = (report.generated_at or report.uploaded_at or "")[:10]
    flow.append(Paragraph(f"Document: {_esc(report.original_filename)}", st["meta"]))
    flow.append(Paragraph(f"Generated: {_esc(date)}", st["meta"]))
    flow.append(Spacer(1, 10))
    flow.append(_summary_band(report, st))
    flow.append(Spacer(1, 14))

    # Feature 038: degraded-analysis banner before the findings (AC-7).
    if report.analysis_degraded:
        banner_style = ParagraphStyle(
            "degraded", parent=st["body"], textColor=colors.white,
            fontSize=10, leading=14,
        )
        banner = Table([[Paragraph(_esc(_DEGRADED_BANNER), banner_style)]], colWidths=[6.5 * inch])
        banner.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), _SEVERITY_COLORS["high"]),
            ("LEFTPADDING", (0, 0), (-1, -1), 12),
            ("RIGHTPADDING", (0, 0), (-1, -1), 12),
            ("TOPPADDING", (0, 0), (-1, -1), 10),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
        ]))
        flow.append(banner)
        flow.append(Spacer(1, 12))

    if not report.findings:
        flow.append(Paragraph(
            f"No risks flagged — {report.summary.total_clauses} clauses reviewed, all clean.",
            st["body"],
        ))
    else:
        for f in report.findings:
            blocks = _finding_blocks(f)
            level = (f.risk_level or "").lower()
            sev_style = ParagraphStyle(
                f"sev_{f.clause_id}", parent=st["sevH"],
                textColor=_SEVERITY_COLORS.get(level, st["accent"]),
            )
            flow.append(Paragraph(blocks[0], sev_style))
            for b in blocks[1:]:
                style = st["rewrite"] if b.startswith("Suggested rewrite:") else st["body"]
                flow.append(Paragraph(b, style))
            flow.append(Spacer(1, 8))

    flow.append(Spacer(1, 12))
    flow.append(Paragraph(_esc(REPORT_BRAND_FOOTER), st["footer"]))
    return flow


def _on_page(canvas, doc):
    canvas.saveState()
    canvas.setFont("Helvetica", 8)
    canvas.setFillColor(colors.grey)
    canvas.drawRightString(7.5 * inch, 0.5 * inch, f"Page {doc.page}")
    canvas.restoreState()


def render_report_pdf(report: ContractReport, out_path: Path) -> Path:
    """Render `report` to a branded PDF at `out_path`. Returns out_path."""
    out_path = Path(out_path)
    doc = SimpleDocTemplate(
        str(out_path), pagesize=LETTER,
        leftMargin=0.75 * inch, rightMargin=0.75 * inch,
        topMargin=0.6 * inch, bottomMargin=0.7 * inch,
        title=f"{REPORT_BRAND_NAME} — {report.original_filename}",
    )
    doc.build(_build_flowables(report), onFirstPage=_on_page, onLaterPages=_on_page)
    return out_path
