"""
Minimal Markdown → PDF renderer (reportlab only; no pandoc/weasyprint needed).

Handles the constructs used in PROJECT_REPORT.md: #/##/### headers, **bold**, `inline code`,
- bullet lists, | markdown | tables |, ```code blocks```, _italics_, and paragraphs.

Usage: python scripts/md_to_pdf.py <input.md> <output.pdf>
"""

import html
import re
import sys

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm
from reportlab.platypus import (
    SimpleDocTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
    Preformatted,
)

_ACCENT = colors.HexColor("#1e293b")


def _inline(text: str) -> str:
    """Convert inline markdown (**bold**, `code`) to reportlab mini-HTML, escaping the rest."""
    out, i = [], 0
    token = re.compile(r"\*\*(.+?)\*\*|`(.+?)`")
    for m in token.finditer(text):
        out.append(html.escape(text[i : m.start()]))
        if m.group(1) is not None:
            out.append(f"<b>{html.escape(m.group(1))}</b>")
        else:
            out.append(
                f'<font face="Courier" backColor="#eef2f7">{html.escape(m.group(2))}</font>'
            )
        i = m.end()
    out.append(html.escape(text[i:]))
    return "".join(out)


def _styles():
    s = getSampleStyleSheet()
    s.add(ParagraphStyle("H1x", parent=s["Title"], fontSize=20, spaceAfter=10, textColor=_ACCENT))
    s.add(ParagraphStyle("H2x", parent=s["Heading1"], fontSize=14, spaceBefore=12, spaceAfter=6, textColor=_ACCENT))
    s.add(ParagraphStyle("H3x", parent=s["Heading2"], fontSize=11.5, spaceBefore=8, spaceAfter=4, textColor=_ACCENT))
    s.add(ParagraphStyle("BodyX", parent=s["BodyText"], fontSize=9.5, leading=13.5, spaceAfter=4))
    s.add(ParagraphStyle("BulletX", parent=s["BodyText"], fontSize=9.5, leading=13, leftIndent=14, bulletIndent=4, spaceAfter=2))
    s.add(ParagraphStyle("CellX", parent=s["BodyText"], fontSize=8, leading=10.5))
    return s


def render(md_path: str, pdf_path: str) -> None:
    S = _styles()
    lines = open(md_path, encoding="utf-8").read().splitlines()
    flow = []
    i = 0
    while i < len(lines):
        ln = lines[i]

        # code block
        if ln.strip().startswith("```"):
            block = []
            i += 1
            while i < len(lines) and not lines[i].strip().startswith("```"):
                block.append(lines[i])
                i += 1
            flow.append(Preformatted("\n".join(block), ParagraphStyle("Code", fontName="Courier", fontSize=8, leading=10, backColor="#f5f7fa", borderPadding=6)))
            flow.append(Spacer(1, 4))
            i += 1
            continue

        # table
        if ln.strip().startswith("|") and i + 1 < len(lines) and re.match(r"^\s*\|[\s:|-]+\|\s*$", lines[i + 1]):
            rows = []
            while i < len(lines) and lines[i].strip().startswith("|"):
                cells = [c.strip() for c in lines[i].strip().strip("|").split("|")]
                rows.append(cells)
                i += 1
            header, body = rows[0], rows[2:]  # rows[1] is the --- separator
            data = [[Paragraph(_inline(c), S["CellX"]) for c in header]] + [
                [Paragraph(_inline(c), S["CellX"]) for c in r] for r in body
            ]
            t = Table(data, hAlign="LEFT")
            t.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (-1, 0), _ACCENT),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#cbd5e1")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f8fafc")]),
                ("LEFTPADDING", (0, 0), (-1, -1), 4),
                ("RIGHTPADDING", (0, 0), (-1, -1), 4),
            ]))
            flow.append(t)
            flow.append(Spacer(1, 6))
            continue

        stripped = ln.strip()
        if not stripped:
            i += 1
            continue
        if stripped.startswith("### "):
            flow.append(Paragraph(_inline(stripped[4:]), S["H3x"]))
        elif stripped.startswith("## "):
            flow.append(Paragraph(_inline(stripped[3:]), S["H2x"]))
        elif stripped.startswith("# "):
            flow.append(Paragraph(_inline(stripped[2:]), S["H1x"]))
        elif stripped.startswith("- "):
            flow.append(Paragraph("• " + _inline(stripped[2:]), S["BulletX"]))
        elif re.match(r"^_.+_$", stripped):
            flow.append(Paragraph(f"<i>{html.escape(stripped.strip('_'))}</i>", S["BodyX"]))
        else:
            flow.append(Paragraph(_inline(stripped), S["BodyX"]))
        i += 1

    SimpleDocTemplate(
        pdf_path, pagesize=A4,
        leftMargin=1.8 * cm, rightMargin=1.8 * cm, topMargin=1.6 * cm, bottomMargin=1.6 * cm,
        title="ContractSentinel — Project Report",
    ).build(flow)


if __name__ == "__main__":
    render(sys.argv[1], sys.argv[2])
    print(f"Wrote {sys.argv[2]}")
