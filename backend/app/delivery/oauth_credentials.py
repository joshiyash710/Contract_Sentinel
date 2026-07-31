"""
Per-user OAuth credential helpers (feature 031).

Pure/utility helpers used by the delivery layer to materialize a per-user Google
token for the Drive MCP subprocess, and to best-effort revoke a token on disconnect.
Never raise on network/parse errors.
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
from typing import Optional

import httpx
from cryptography.fernet import InvalidToken

import app.config as _config
from app.security import crypto

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


def materialize_central_token_tempfile() -> Optional[str]:
    """Return a filesystem path to the PLAINTEXT central Google token (feature 032, W1).

    The central token file (`GOOGLE_OAUTH_TOKEN_PATH`) is encrypted at rest. The MCP Drive/Gmail
    servers run as subprocesses that read the token file directly with `from_authorized_user_file`
    (plaintext only) and must NOT receive the master key — so the parent decrypts here to a short-lived
    0600 temp file and returns its path (the CALLER unlinks it after delivery). Behavior:
      - file absent            → None (delivery fails naturally, as before)
      - file is ciphertext     → decrypt to a temp file, return its path (path != the config path)
      - file is legacy plaintext (or undecryptable) → return the original config path UNCHANGED
        (no temp file — nothing to clean up; a truly corrupt token then fails in the subprocess).
    """
    path = _config.GOOGLE_OAUTH_TOKEN_PATH
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            raw = f.read()
    except OSError:
        return None
    try:
        plaintext = crypto.decrypt(raw)
    except InvalidToken:
        # Legacy plaintext token (or unparseable) — hand back the original path unchanged.
        return path
    return write_token_tempfile(plaintext)


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
