"""
Security primitives for feature 014 — passwords, JWT, and secret bootstrap.

Design decisions (spec §2.3):
  D1 — HS256 JWT in an httpOnly cookie; algorithms pinned to reject alg=none (M1).
  D2 — bcrypt with SHA-256 pre-hash to bypass bcrypt's 72-byte truncation (S2).
  S3 — plaintext password / AUTH_SECRET / raw JWT are NEVER logged here.
  S4 — AUTH_SECRET is never a hardcoded default; generated + persisted on first run.

Uses the `bcrypt` package directly (not passlib) to avoid passlib 1.7.4 / bcrypt 5.x
compatibility issues (passlib can't find bcrypt.__about__ in 5.x). bcrypt's API
(hashpw / checkpw / gensalt) is stable across versions.
"""

import base64
import hashlib
import hmac
import os
import secrets
import stat
from datetime import datetime, timezone, timedelta
from typing import Any, Optional

import bcrypt as _bcrypt
import jwt

import app.config as _cfg


def _sha256_b64(pw: str) -> bytes:
    """SHA-256(password) → base64-encoded bytes (44 bytes) — always < 72-byte bcrypt cap."""
    digest = hashlib.sha256(pw.encode("utf-8")).digest()
    return base64.b64encode(digest)


def hash_password(pw: str) -> str:
    """Hash a plaintext password with SHA-256 pre-hash + bcrypt."""
    pre = _sha256_b64(pw)  # 44 bytes — well under bcrypt's 72-byte limit
    salt = _bcrypt.gensalt(rounds=_cfg.AUTH_BCRYPT_ROUNDS)
    return _bcrypt.hashpw(pre, salt).decode("utf-8")


def verify_password(pw: str, hashed: str) -> bool:
    """Constant-time verify of plaintext password against a bcrypt hash."""
    pre = _sha256_b64(pw)
    return _bcrypt.checkpw(pre, hashed.encode("utf-8"))


# Precomputed dummy hash used to timing-equalize the unknown-email login path (M2).
# Computed once at module load so the first unknown-email login is not measurably slower.
DUMMY_HASH: str = hash_password("__dummy_sentinel_auth_v014__")


# ---------------------------------------------------------------------------
# Secret bootstrap (S4 / D1)
# ---------------------------------------------------------------------------

# Module-level cache — loaded once, never changes within a process.
_SECRET: str | None = None


def load_secret() -> str:
    """Return the signing secret, bootstrapping it if necessary.

    Priority: AUTH_SECRET env var > AUTH_SECRET_FILE > generate + persist.
    Never returns a hardcoded literal. Never logs the value.
    """
    global _SECRET
    if _SECRET is not None:
        return _SECRET

    env_val = os.environ.get("AUTH_SECRET", "").strip()
    if env_val:
        _SECRET = env_val
        return _SECRET

    secret_path = _cfg.AUTH_SECRET_FILE
    if os.path.exists(secret_path):
        with open(secret_path, "r") as f:
            _SECRET = f.read().strip()
        return _SECRET

    # Generate, persist, and use
    generated = secrets.token_urlsafe(48)
    parent = os.path.dirname(secret_path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    with open(secret_path, "w") as f:
        f.write(generated)
    try:
        os.chmod(secret_path, stat.S_IRUSR | stat.S_IWUSR)  # 0600 where supported
    except OSError:
        pass  # Windows; acceptable for localhost-only tool
    _SECRET = generated
    return _SECRET


def bootstrap_secret() -> None:
    """Call at app startup to pre-load the secret (and fail-fast if needed)."""
    load_secret()


# ---------------------------------------------------------------------------
# JWT (D1 / M1)
# ---------------------------------------------------------------------------


def make_session(user: Any, *, absolute_exp: Optional[datetime] = None) -> str:
    """Encode a signed HS256 session JWT (feature 032, W2).

    Claims: {sub, email, iat, exp, aexp, epoch}.
      - exp   = sliding IDLE expiry = min(now + AUTH_IDLE_TIMEOUT_SECONDS, aexp). `require_auth`
                re-issues the cookie on each authenticated request, sliding this forward.
      - aexp  = ABSOLUTE lifetime cap, fixed at first login (now + AUTH_SESSION_TTL_SECONDS) and
                PRESERVED across re-issues by passing `absolute_exp` — a session can never live past it.
      - epoch = the user's session_epoch; bumping it server-side invalidates all outstanding tokens.
    """
    now = datetime.now(timezone.utc)
    aexp = absolute_exp or (now + timedelta(seconds=_cfg.AUTH_SESSION_TTL_SECONDS))
    idle_exp = now + timedelta(seconds=_cfg.AUTH_IDLE_TIMEOUT_SECONDS)
    exp = min(idle_exp, aexp)
    payload = {
        "sub": user.id,
        "email": user.email,
        "iat": now,
        "exp": exp,
        "aexp": int(aexp.timestamp()),
        "epoch": getattr(user, "session_epoch", 0),
    }
    return jwt.encode(payload, load_secret(), algorithm="HS256")


# ---------------------------------------------------------------------------
# Password-reset tokens (feature 034)
# ---------------------------------------------------------------------------


def generate_reset_token() -> str:
    """A high-entropy, URL-safe single-use reset token (~256-bit; Decision 1).

    The raw token is emailed to the user and NEVER stored or logged (S3). Only its
    HMAC (hash_reset_token) is persisted.
    """
    return secrets.token_urlsafe(_cfg.AUTH_RESET_TOKEN_BYTES)


def hash_reset_token(raw: str) -> str:
    """HMAC-SHA256(AUTH_SECRET, raw) hex — the value stored in password_reset_tokens.

    Keying with the app secret (Decision 2) means a DB leak alone cannot be used to
    precompute or forge a token lookup.
    """
    return hmac.new(load_secret().encode("utf-8"), raw.encode("utf-8"), hashlib.sha256).hexdigest()


def read_session(token: str) -> dict[str, Any]:
    """Decode and verify a session JWT; raise on any failure (tampered/expired/alg-swap).

    algorithms=["HS256"] pins the algorithm — alg=none and any other alg are rejected. A small
    `leeway` tolerates minor clock skew on the idle `exp` check (feature 032, EC-5).
    """
    return jwt.decode(
        token,
        load_secret(),
        algorithms=["HS256"],
        leeway=_cfg.AUTH_CLOCK_SKEW_SECONDS,
    )
