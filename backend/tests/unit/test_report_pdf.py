"""
Unit tests for app.delivery.report_pdf — the branded reportlab PDF renderer (feature 030).

Content is asserted via the pure `report_text_blocks(report)` seam (the ordered list of
escaped/truncated text strings the PDF renders), so we do not need to parse the emitted PDF.
The emitted file is checked only for the %PDF- magic header (AC-1).
"""

from app.models.report import (
    ContractReport,
    ReportSummary,
    ReportFinding,
    ReportEvidence,
)
from app.delivery.report_pdf import render_report_pdf, report_text_blocks


def _finding(**kw):
    base = dict(
        clause_id="clause_001",
        position=1,
        section_number="4.1",
        clause_type="liability",
        risk_level="high",
        risk_rationale="Uncapped liability exposes the client to unlimited damages.",
        clause_text="The Provider shall bear unlimited liability for all damages.",
        rewrite_state="rewritten",
        suggested_rewrite="Liability is capped at fees paid in the prior 12 months.",
        path_taken="local_kb",
        confidence_score=0.82,
        evidence=[ReportEvidence(source_reference="kb/liability", snippet_text="Caps are standard.")],
    )
    base.update(kw)
    return ReportFinding(**base)


def _report(findings=None, summary=None):
    if findings is None:
        findings = [
            _finding(),
            _finding(clause_id="clause_002", position=2, section_number="7.2", risk_level="low"),
        ]
    summary = summary or ReportSummary(
        total_clauses=40, validated_findings=len(findings), clean_clauses=38,
        high=1, medium=0, low=1,
    )
    return ContractReport(
        document_id="doc-1",
        original_filename="Master Services Agreement.docx",
        uploaded_at="2026-07-28T10:00:00+00:00",
        generated_at="2026-07-28T10:03:00+00:00",
        ocr_used=False,
        summary=summary,
        findings=findings,
    )


def _joined(report) -> str:
    return "\n".join(report_text_blocks(report))


# ── AC-1: real PDF file with %PDF- header ────────────────────────────────────
def test_render_produces_pdf_with_magic_header(tmp_path):
    out = tmp_path / "report.pdf"
    result = render_report_pdf(_report(), out)
    assert result == out
    assert out.exists() and out.stat().st_size > 0
    assert out.read_bytes()[:5] == b"%PDF-"


# ── AC-2: brand + metadata ───────────────────────────────────────────────────
def test_blocks_include_brand_and_metadata():
    from app.config import REPORT_BRAND_NAME

    text = _joined(_report())
    assert REPORT_BRAND_NAME in text
    assert "Master Services Agreement.docx" in text
    assert "2026-07-28" in text  # generated/upload date appears


# ── AC-3: risk summary ───────────────────────────────────────────────────────
def test_blocks_include_risk_summary():
    text = _joined(_report())
    assert "40" in text  # total clauses
    assert "2" in text   # validated findings (default fixture = 2 findings)
    # explicit high/med/low labels
    for label in ("High", "Medium", "Low"):
        assert label in text


# ── AC-4: per-finding detail + before→after ──────────────────────────────────
def test_blocks_include_finding_detail_and_rewrite():
    text = _joined(_report())
    assert "liability" in text.lower()
    assert "4.1" in text  # section number
    assert "unlimited liability" in text.lower()  # clause text
    assert "Uncapped liability" in text  # rationale
    assert "capped at fees" in text.lower()  # suggested rewrite (before→after)


def test_finding_without_rewrite_has_no_after_block():
    f = _finding(rewrite_state="not_eligible", suggested_rewrite=None)
    text = _joined(_report(findings=[f]))
    assert "capped at fees" not in text.lower()  # no rewrite text
    assert "unlimited liability" in text.lower()  # clause text still rendered


# ── AC-5: zero findings ──────────────────────────────────────────────────────
def test_zero_findings_report(tmp_path):
    summary = ReportSummary(
        total_clauses=12, validated_findings=0, clean_clauses=12, high=0, medium=0, low=0
    )
    report = _report(findings=[], summary=summary)
    text = _joined(report)
    assert "no risk" in text.lower() or "no findings" in text.lower()
    assert "12" in text  # clean clause count
    # still renders a valid PDF
    out = tmp_path / "clean.pdf"
    render_report_pdf(report, out)
    assert out.read_bytes()[:5] == b"%PDF-"


# ── AC-7: truncation ─────────────────────────────────────────────────────────
def test_long_fields_are_truncated():
    from app.config import (
        REPORT_PDF_CLAUSE_MAX_CHARS,
        REPORT_PDF_RATIONALE_MAX_CHARS,
        REPORT_PDF_REWRITE_MAX_CHARS,
    )

    f = _finding(
        clause_text="A" * 5000,
        risk_rationale="B" * 5000,
        suggested_rewrite="C" * 6000,
    )
    blocks = report_text_blocks(_report(findings=[f]))
    # no single block exceeds its cap by more than a short label prefix + ellipsis
    longest = max(len(b) for b in blocks)
    assert longest <= max(
        REPORT_PDF_CLAUSE_MAX_CHARS,
        REPORT_PDF_RATIONALE_MAX_CHARS,
        REPORT_PDF_REWRITE_MAX_CHARS,
    ) + 40  # allow "Suggested rewrite: " / "Why this is flagged: " labels
    # and the raw runs are actually cut
    joined = "\n".join(blocks)
    assert "A" * 5000 not in joined
    assert "C" * 6000 not in joined


# ── escaping (safety + reportlab correctness) ────────────────────────────────
def test_html_metachars_are_escaped_in_blocks(tmp_path):
    f = _finding(clause_text="<script>alert(1)</script> a & b \"q\"")
    report = _report(findings=[f])
    text = _joined(report)
    assert "&lt;script&gt;" in text
    assert "&amp;" in text
    assert "<script>" not in text  # raw tag never present
    # and the escaped content still renders a valid PDF (reportlab Paragraph safe)
    out = tmp_path / "esc.pdf"
    render_report_pdf(report, out)
    assert out.read_bytes()[:5] == b"%PDF-"


# ── AC-6: pure / deterministic ───────────────────────────────────────────────
def test_blocks_are_deterministic():
    r = _report()
    assert report_text_blocks(r) == report_text_blocks(r)


# ── Feature 038: degraded banner + per-finding auto tag (AC-7, AC-8) ──────────
def test_degraded_banner_in_blocks_and_pdf(tmp_path):
    r = _report(summary=ReportSummary(
        total_clauses=3, validated_findings=1, clean_clauses=2,
        high=1, medium=0, low=0, failsafe_count=1,
    ))
    r.analysis_degraded = True
    assert "Degraded analysis" in _joined(r)
    out = render_report_pdf(r, tmp_path / "d.pdf")
    assert out.read_bytes()[:5] == b"%PDF-"


def test_no_degraded_banner_when_healthy():
    r = _report()
    assert r.analysis_degraded is False
    assert "Degraded analysis" not in _joined(r)


def test_failsafe_finding_tagged_auto():
    r = _report(findings=[_finding(is_failsafe=True)])
    assert "auto-assigned" in _joined(r)


def test_genuine_finding_not_tagged_auto():
    r = _report(findings=[_finding(is_failsafe=False)])
    assert "auto-assigned" not in _joined(r)
