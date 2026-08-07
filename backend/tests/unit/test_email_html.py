"""
Unit tests for app.delivery.email_html.build_email_bodies (feature 030).

Returns (subject, plain, html): a branded SaaS-style HTML email with a plain-text fallback.
"""

from app.models.report import ReportSummary
from app.delivery.email_html import build_email_bodies

_SUMMARY = ReportSummary(
    total_clauses=40, validated_findings=3, clean_clauses=37, high=1, medium=1, low=1
)


def _bodies(summary=_SUMMARY, filename="MSA.docx", drive_ref=None):
    return build_email_bodies("doc-1", summary, filename, drive_ref)


# ── AC-8: HTML body has brand + summary ──────────────────────────────────────
def test_html_has_brand_and_summary():
    from app.config import REPORT_BRAND_NAME

    subject, plain, html = _bodies()
    assert REPORT_BRAND_NAME in html
    assert "3" in html  # findings
    for label in ("High", "Medium", "Low"):
        assert label in html
    # subject preserves the findings roll-up
    assert "3 findings" in subject
    assert "MSA.docx" in subject


# ── AC-9: plain-text fallback conveys the summary ────────────────────────────
def test_plain_fallback_present_and_has_summary():
    subject, plain, html = _bodies()
    assert plain and isinstance(plain, str)
    assert "3 findings" in plain or "3 findings" in plain.replace("  ", " ")
    assert "1 high" in plain
    assert "attached" in plain.lower()


def test_none_summary_generic_email():
    subject, plain, html = _bodies(summary=None)
    assert "MSA.docx" in subject
    assert "completed analysis" in plain.lower()
    assert "MSA.docx" in html


# ── AC-10: CTA present only when drive_ref given ─────────────────────────────
def test_cta_present_when_drive_ref():
    ref = "https://drive.google.com/file/ABC"
    _, plain, html = _bodies(drive_ref=ref)
    assert ref in html  # CTA link in HTML
    assert ref in plain  # and in the plain fallback (existing behavior)


def test_no_cta_when_drive_ref_absent():
    _, plain, html = _bodies(drive_ref=None)
    assert "drive.google.com" not in html
    assert "drive.google.com" not in plain


# ── AC-18: HTML-injection escaping ───────────────────────────────────────────
def test_html_fields_escaped():
    _, plain, html = _bodies(filename='<script>alert(1)</script> a & b "q"')
    assert "&lt;script&gt;" in html
    assert "&amp;" in html
    assert "<script>" not in html  # raw tag never present


def test_returns_three_strings():
    result = _bodies()
    assert isinstance(result, tuple) and len(result) == 3
    assert all(isinstance(x, str) for x in result)


# ── Feature 038: degraded-analysis notice in HTML + plain text (AC-7) ─────────
def test_degraded_notice_present_when_degraded():
    subject, plain, html = build_email_bodies(
        "doc-1", _SUMMARY, "MSA.docx", None, analysis_degraded=True
    )
    assert "Degraded analysis" in html
    assert "Degraded analysis" in plain


def test_no_degraded_notice_when_healthy():
    subject, plain, html = build_email_bodies(
        "doc-1", _SUMMARY, "MSA.docx", None, analysis_degraded=False
    )
    assert "Degraded analysis" not in html
    assert "Degraded analysis" not in plain
