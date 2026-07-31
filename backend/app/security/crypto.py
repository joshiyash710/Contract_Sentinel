"""
Encryption-at-rest for OAuth tokens (feature 032, W1).

Symmetric Fernet (AES-128-CBC + HMAC-SHA256) encryption of Google OAuth tokens at rest — the
per-user `users.google_oauth_token` column and the central `google_token.json` file. Authorized by
the constitution §2 amendment (2026-07-31, feature 032).

Key management (deliberately a single local key, NOT a KMS/Vault — see tech-stack §5.5):
  precedence  env $CONTRACTSENTINEL_ENCRYPTION_KEY  >  key file (data/encryption_key)  >  generate+persist
mirrors the AUTH_SECRET bootstrap in `app.api.security.load_secret`.

SECURITY: the key and any decrypted token plaintext are NEVER logged here.
"""

from __future__ import annotations

import logging
import os
import stat
from typing import Optional

from cryptography.fernet import Fernet, InvalidToken  # noqa: F401 — InvalidToken re-exported

import app.config as _cfg

logger = logging.getLogger("contractsentinel.security.crypto")

# Module-level cache — loaded once per process, never logged.
_KEY: Optional[bytes] = None


def load_encryption_key() -> bytes:
    """Return the Fernet key bytes, bootstrapping if necessary.

    Priority: env var > key file > generate + persist (0600 where supported). Never logs the value.
    """
    global _KEY
    if _KEY is not None:
        return _KEY

    env_val = os.environ.get(_cfg.ENCRYPTION_KEY_ENV, "").strip()
    if env_val:
        _KEY = env_val.encode("ascii")
        return _KEY

    key_path = _cfg.ENCRYPTION_KEY_FILE
    if os.path.exists(key_path):
        with open(key_path, "rb") as f:
            _KEY = f.read().strip()
        return _KEY

    # Generate, persist, and use.
    generated = Fernet.generate_key()
    parent = os.path.dirname(key_path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    with open(key_path, "wb") as f:
        f.write(generated)
    try:
        os.chmod(key_path, stat.S_IRUSR | stat.S_IWUSR)  # 0600 where supported
    except OSError:
        pass  # Windows; acceptable for a localhost-only tool
    logger.info("Generated a new encryption key at %s (value not logged)", key_path)
    _KEY = generated
    return _KEY


def bootstrap_encryption_key() -> None:
    """Call at app startup to pre-load/generate the key (fail-fast on key problems)."""
    load_encryption_key()


def _fernet() -> Fernet:
    return Fernet(load_encryption_key())


def encrypt(plaintext: str) -> str:
    """Encrypt a plaintext string → URL-safe base64 Fernet token string."""
    return _fernet().encrypt(plaintext.encode("utf-8")).decode("ascii")


def decrypt(token: str) -> str:
    """Decrypt a Fernet token string → plaintext. Raises InvalidToken on bad key/ciphertext."""
    return _fernet().decrypt(token.encode("utf-8")).decode("utf-8")


def looks_like_plaintext_token(value: str) -> bool:
    """True if `value` parses as JSON carrying a `refresh_token`/`token` key.

    Used to recognise a LEGACY plaintext OAuth token (written before feature 032) so it can be read
    as-is and re-encrypted on next write. Ciphertext / non-JSON returns False.
    """
    import json

    try:
        data = json.loads(value)
    except (ValueError, TypeError):
        return False
    return isinstance(data, dict) and ("refresh_token" in data or "token" in data)
