"""
Per-user OAuth credential helpers (feature 031).

Pure/utility helpers used by the delivery layer to materialize a per-user Google
token for the Drive MCP subprocess, and to best-effort revoke a token on disconnect.
Never raise on network/parse errors.
"""

from __future__ import annotations

import json
import logging
import tempfile

import httpx

logger = logging.getLogger("contractsentinel.delivery.oauth_credentials")

_REVOKE_URL = "https://oauth2.googleapis.com/revoke"
_REVOKE_TIMEOUT_SECONDS = 10


def write_token_tempfile(token_json: str) -> str:
    """Write the per-user credentials JSON to a temp file and return its path.

    Created with delete=False so the Drive MCP subprocess can re-open it (Windows);
    the CALLER owns deletion (unlink in a finally AFTER the upload returns).
    """
    fh = tempfile.NamedTemporaryFile(
        mode="w", suffix=".json", prefix="cs_usertoken_", delete=False, encoding="utf-8"
    )
    try:
        fh.write(token_json)
    finally:
        fh.close()
    return fh.name


def revoke_token(token_json: str) -> bool:
    """Best-effort revoke of a Google OAuth token. Returns True on a 2xx, else False.
    Never raises — a revoke failure must never block a local disconnect."""
    try:
        data = json.loads(token_json)
    except (json.JSONDecodeError, TypeError):
        logger.warning("revoke_token: credentials JSON unparseable; skipping revoke")
        return False
    token = data.get("refresh_token") or data.get("token")
    if not token:
        return False
    try:
        resp = httpx.post(
            _REVOKE_URL,
            data={"token": token},
            headers={"content-type": "application/x-www-form-urlencoded"},
            timeout=_REVOKE_TIMEOUT_SECONDS,
        )
        return 200 <= resp.status_code < 300
    except Exception:  # noqa: BLE001 — never raise
        logger.warning("revoke_token: revoke request failed", exc_info=True)
        return False
