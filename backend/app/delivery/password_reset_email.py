"""
Reset-password email (feature 034) — builder + central-Gmail sender.

`build_reset_email(reset_url)` returns (subject, plain, html): a branded email whose CTA links to the
frontend /reset page carrying the single-use token. `send_reset_email` sends it through the CENTRAL
Gmail MCP path (feature 010/030/032), mirroring the delivery layer's decrypted-central-token tempfile
handling. Never per-user Gmail (031 amendment keeps gmail.send central).
"""

from __future__ import annotations

import html as _html
import logging
import os

import app.config as _config
from app.delivery.mcp_clients import send_report_via_gmail
from app.delivery.oauth_credentials import materialize_central_token_tempfile

logger = logging.getLogger("contractsentinel.delivery.reset_email")

_TTL_MIN = _config.AUTH_RESET_TOKEN_TTL_SECONDS // 60


def build_reset_email(reset_url: str) -> tuple[str, str, str]:
    """Return (subject, plain_text, branded_html) for a password-reset email."""
    brand = _config.REPORT_BRAND_NAME
    subject = f"Reset your {brand} password"

    plain = "\n".join(
        [
            f"We received a request to reset your {brand} password.",
            "",
            f"Use this link to choose a new password (it expires in {_TTL_MIN} minutes):",
            reset_url,
            "",
            "If you did not request a password reset, you can safely ignore this email — "
            "your password will not change.",
        ]
    )

    html = _build_html(brand, reset_url)
    return subject, plain, html


def _build_html(brand: str, reset_url: str) -> str:
    accent = _html.escape(_config.REPORT_BRAND_ACCENT_HEX)
    b = _html.escape(brand)
    href = _html.escape(reset_url, quote=True)
    footer = _html.escape(_config.REPORT_BRAND_FOOTER)
    return f"""\
<!DOCTYPE html>
<html><body style="margin:0;padding:0;background:#f8fafc;font-family:-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#f8fafc;padding:24px 0;">
<tr><td align="center">
<table role="presentation" width="600" cellpadding="0" cellspacing="0" style="background:#ffffff;border-radius:10px;overflow:hidden;border:1px solid #e2e8f0;">
  <tr><td style="background:{accent};padding:22px 28px;">
    <div style="color:#ffffff;font-size:20px;font-weight:700;letter-spacing:0.2px;">{b}</div>
    <div style="color:#cbd5e1;font-size:12px;margin-top:2px;">Password reset</div>
  </td></tr>
  <tr><td style="padding:26px 28px;">
    <p style="margin:0 0 12px;color:#334155;font-size:14px;">
      We received a request to reset your {b} password.</p>
    <p style="margin:12px 0;color:#475569;font-size:13px;line-height:1.5;">
      Click the button below to choose a new password. This link expires in
      <strong>{_TTL_MIN} minutes</strong>.</p>
    <p style="margin:20px 0;"><a href="{href}"
      style="background:{accent};color:#ffffff;text-decoration:none;padding:11px 20px;
      border-radius:6px;font-size:14px;font-weight:600;display:inline-block;">Reset password</a></p>
    <p style="margin:12px 0;color:#94a3b8;font-size:12px;line-height:1.5;">
      If you did not request this, you can safely ignore this email — your password will not change.</p>
  </td></tr>
  <tr><td style="padding:16px 28px;border-top:1px solid #e2e8f0;background:#f8fafc;">
    <div style="color:#94a3b8;font-size:11px;line-height:1.5;">{footer}</div>
  </td></tr>
</table>
</td></tr>
</table>
</body></html>"""


async def send_reset_email(to: str, reset_url: str) -> None:
    """Send the reset email via the CENTRAL Gmail token. Never raises out (AC-9): the caller logs.

    Mirrors delivery_step's decrypted-central-token tempfile handling — importantly, only unlinks a
    real temp file, never the live GOOGLE_OAUTH_TOKEN_PATH (legacy-plaintext case).
    """
    subject, plain, html = build_reset_email(reset_url)
    central = materialize_central_token_tempfile()
    is_temp = bool(central) and central != _config.GOOGLE_OAUTH_TOKEN_PATH
    try:
        result = await send_report_via_gmail(
            to,
            subject,
            plain,
            None,  # no attachment
            None,
            timeout_seconds=_config.MCP_DELIVERY_TIMEOUT_SECONDS,
            max_retries=_config.MCP_DELIVERY_MAX_RETRIES,
            html_body=html,
            token_path=central,
        )
        if not result.ok:
            logger.warning("reset email send failed: %s", result.error_message)
    finally:
        if is_temp:
            try:
                os.unlink(central)
            except OSError:
                pass
