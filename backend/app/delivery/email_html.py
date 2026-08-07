"""
Branded email bodies for the delivery layer (feature 030, Phase 1).

`build_email_bodies` returns (subject, plain_text, html):
  - plain_text: the accessible fallback (preserves the pre-030 body content).
  - html: a branded, inline-CSS, table-based (email-client-safe) SaaS-style email.

All interpolated report-derived values are HTML-escaped (AC-18). Delivery-layer only.
"""

from __future__ import annotations

import html as _html
from typing import Optional

import app.config as _config
from app.models.report import ReportSummary

REPORT_BRAND_NAME = _config.REPORT_BRAND_NAME
REPORT_BRAND_ACCENT_HEX = _config.REPORT_BRAND_ACCENT_HEX
REPORT_BRAND_FOOTER = _config.REPORT_BRAND_FOOTER


# Feature 038: degraded-analysis notice (single source for plain-text + HTML).
_DEGRADED_NOTICE = (
    "Degraded analysis — the AI model was unavailable for part or all of this run. "
    "Some severities were set by a fail-safe default, not by model judgment. Do not "
    "rely on them; re-run this analysis when the model is available."
)


def build_email_bodies(
    document_id: str,
    summary: Optional[ReportSummary],
    original_filename: str,
    drive_ref: Optional[str],
    analysis_degraded: bool = False,
) -> tuple[str, str, str]:
    fn = original_filename or document_id

    if summary is not None:
        subject = (
            f"{REPORT_BRAND_NAME} report — {fn}: "
            f"{summary.validated_findings} findings "
            f"({summary.high} high / {summary.medium} med / {summary.low} low)"
        )
        plain_lines = [
            f"{REPORT_BRAND_NAME} has completed analysis of {fn}.",
            "",
            f"Summary: {summary.validated_findings} findings — "
            f"{summary.high} high, {summary.medium} medium, {summary.low} low.",
        ]
    else:
        subject = f"{REPORT_BRAND_NAME} report — {fn}"
        plain_lines = [f"{REPORT_BRAND_NAME} has completed analysis of {fn}."]

    if analysis_degraded:
        plain_lines = [f"⚠ {_DEGRADED_NOTICE}", ""] + plain_lines
    if drive_ref:
        plain_lines += ["", f"View report on Google Drive: {drive_ref}"]
    plain_lines += ["", "The full report is attached to this email (PDF)."]
    plain = "\n".join(plain_lines)

    html = _build_html(fn, summary, drive_ref, analysis_degraded)
    return subject, plain, html


def _build_html(
    filename: str,
    summary: Optional[ReportSummary],
    drive_ref: Optional[str],
    analysis_degraded: bool = False,
) -> str:
    accent = _html.escape(REPORT_BRAND_ACCENT_HEX)
    brand = _html.escape(REPORT_BRAND_NAME)
    fn = _html.escape(filename)
    footer = _html.escape(REPORT_BRAND_FOOTER)

    if summary is not None:
        chips = "".join(
            _chip(label, value, color)
            for label, value, color in (
                ("Findings", summary.validated_findings, "#0f172a"),
                ("High", summary.high, "#dc2626"),
                ("Medium", summary.medium, "#d97706"),
                ("Low", summary.low, "#0f766e"),
            )
        )
        summary_block = (
            f'<p style="margin:0 0 12px;color:#334155;font-size:14px;">'
            f'We reviewed <strong>{summary.total_clauses}</strong> clauses in '
            f'<strong>{fn}</strong> and flagged '
            f'<strong>{summary.validated_findings}</strong> for your attention.</p>'
            f'<table role="presentation" cellpadding="0" cellspacing="0" style="margin:8px 0;">'
            f"<tr>{chips}</tr></table>"
        )
    else:
        summary_block = (
            f'<p style="margin:0 0 12px;color:#334155;font-size:14px;">'
            f"{brand} has completed analysis of <strong>{fn}</strong>.</p>"
        )

    degraded_banner = ""
    if analysis_degraded:
        degraded_banner = (
            f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" '
            f'style="margin:0 0 18px;"><tr><td style="background:#fef2f2;border:1px solid '
            f'#dc2626;border-radius:8px;padding:12px 14px;color:#991b1b;font-size:13px;'
            f'line-height:1.5;">&#9888; <strong>Degraded analysis</strong> — {_html.escape(_DEGRADED_NOTICE)}'
            f"</td></tr></table>"
        )

    cta = ""
    if drive_ref:
        ref = _html.escape(drive_ref)
        cta = (
            f'<p style="margin:20px 0;"><a href="{ref}" '
            f'style="background:{accent};color:#ffffff;text-decoration:none;'
            f'padding:11px 20px;border-radius:6px;font-size:14px;font-weight:600;'
            f'display:inline-block;">View report on Google Drive</a></p>'
        )

    return f"""\
<!DOCTYPE html>
<html><body style="margin:0;padding:0;background:#f8fafc;font-family:-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#f8fafc;padding:24px 0;">
<tr><td align="center">
<table role="presentation" width="600" cellpadding="0" cellspacing="0" style="background:#ffffff;border-radius:10px;overflow:hidden;border:1px solid #e2e8f0;">
  <tr><td style="background:{accent};padding:22px 28px;">
    <div style="color:#ffffff;font-size:20px;font-weight:700;letter-spacing:0.2px;">{brand}</div>
    <div style="color:#cbd5e1;font-size:12px;margin-top:2px;">Contract Risk Report</div>
  </td></tr>
  <tr><td style="padding:26px 28px;">
    {degraded_banner}
    {summary_block}
    <p style="margin:12px 0;color:#475569;font-size:13px;line-height:1.5;">
      Your professional PDF report is attached. It details each flagged clause, why it
      matters, and a suggested safer rewrite where available.</p>
    {cta}
  </td></tr>
  <tr><td style="padding:16px 28px;border-top:1px solid #e2e8f0;background:#f8fafc;">
    <div style="color:#94a3b8;font-size:11px;line-height:1.5;">{footer}</div>
  </td></tr>
</table>
</td></tr>
</table>
</body></html>"""


def _chip(label: str, value: int, color: str) -> str:
    return (
        f'<td style="padding:0 6px 0 0;">'
        f'<div style="background:#f1f5f9;border-radius:6px;padding:8px 14px;text-align:center;">'
        f'<div style="color:{color};font-size:18px;font-weight:700;">{value}</div>'
        f'<div style="color:#64748b;font-size:11px;">{_html.escape(label)}</div>'
        f"</div></td>"
    )
