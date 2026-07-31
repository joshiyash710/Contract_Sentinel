"""
Unit tests for app.api.security — password hashing, JWT encode/verify, secret bootstrap.

All AC-7 / M1 / M2 / S2 / S4 criteria verified here (no HTTP layer).
"""

import os
import time
import pytest


# ---------------------------------------------------------------------------
# Password hashing (AC-1 substrate / D2 / S2)
# ---------------------------------------------------------------------------


def test_hash_verify_roundtrip():
    from app.api.security import hash_password, verify_password

    pw = "correct-horse-battery-staple"
    hsh = hash_password(pw)
    assert hsh != pw  # not stored plaintext
    assert verify_password(pw, hsh) is True
    assert verify_password("wrong", hsh) is False


def test_long_password_honored():
    """SHA-256 pre-hash means passwords >72 bytes are honored in full (D2/S2)."""
    from app.api.security import hash_password, verify_password

    # Two passwords that share the same first 72 bytes but differ at byte 73+
    prefix = "A" * 72
    pw_a = prefix + "X"
    pw_b = prefix + "Y"

    hsh_a = hash_password(pw_a)
    assert verify_password(pw_a, hsh_a) is True
    assert verify_password(pw_b, hsh_a) is False, (
        "Passwords differing only past byte 72 must NOT collide — pre-hash required"
    )

    # 100-char password round-trips
    pw_100 = "Z" * 100
    hsh_100 = hash_password(pw_100)
    assert verify_password(pw_100, hsh_100) is True


# ---------------------------------------------------------------------------
# JWT encode / verify (AC-7 / M1)
# ---------------------------------------------------------------------------


@pytest.fixture()
def _fake_secret(monkeypatch, tmp_path):
    """Set AUTH_SECRET env var to a known test value and redirect AUTH_SECRET_FILE."""
    monkeypatch.setenv("AUTH_SECRET", "t" * 32)
    import app.config as _cfg

    monkeypatch.setattr(_cfg, "AUTH_SECRET_FILE", str(tmp_path / "auth_secret"))
    # Re-import security so load_secret() picks up the monkeypatched env
    import importlib
    import app.api.security as sec

    importlib.reload(sec)
    yield sec
    # Reload once more to clear module-level SECRET after the test
    importlib.reload(sec)


def test_jwt_roundtrip(_fake_secret):
    sec = _fake_secret
    from app.api.auth import AuthUser

    user = AuthUser(id="u1", email="a@b.com")
    token = sec.make_session(user)
    claims = sec.read_session(token)
    assert claims["sub"] == "u1"
    assert claims["email"] == "a@b.com"


def test_jwt_rejects_tampered(_fake_secret):
    sec = _fake_secret
    from app.api.auth import AuthUser
    import jwt as _jwt

    user = AuthUser(id="u1", email="a@b.com")
    token = sec.make_session(user)
    # Tamper the last character of the signature
    tampered = token[:-3] + "XXX"
    with pytest.raises(Exception):
        sec.read_session(tampered)


def test_jwt_rejects_alg_none(_fake_secret):
    """Token with alg=none must be rejected (M1 — algorithm pinning)."""
    sec = _fake_secret
    import jwt as _jwt

    payload = {"sub": "u1", "email": "a@b.com", "exp": int(time.time()) + 3600}
    # Build a raw none-algorithm token
    none_token = _jwt.encode(payload, "", algorithm="none")
    with pytest.raises(Exception):
        sec.read_session(none_token)


def test_jwt_rejects_hs512_confusion(_fake_secret):
    """Token signed with HS512 (not HS256) must be rejected (M1)."""
    sec = _fake_secret
    import jwt as _jwt

    payload = {"sub": "u1", "email": "a@b.com", "exp": int(time.time()) + 3600}
    other_token = _jwt.encode(payload, "t" * 32, algorithm="HS512")
    with pytest.raises(Exception):
        sec.read_session(other_token)


def test_jwt_rejects_expired(_fake_secret):
    """Expired token (beyond the clock-skew leeway) must raise (AC-7 — exp check).

    Feature 032 added a small `leeway` (AUTH_CLOCK_SKEW_SECONDS) to read_session, so the expiry here
    is set well past that window to prove genuine expiry is still rejected.
    """
    sec = _fake_secret
    import jwt as _jwt

    payload = {"sub": "u1", "email": "a@b.com", "exp": int(time.time()) - 3600}
    expired_token = _jwt.encode(payload, "t" * 32, algorithm="HS256")
    with pytest.raises(Exception):
        sec.read_session(expired_token)


# ---------------------------------------------------------------------------
# Feature 032 (W2): sliding idle exp + absolute cap + session epoch claims
# ---------------------------------------------------------------------------


def test_make_session_carries_epoch_iat_and_aexp(_fake_secret):
    sec = _fake_secret
    from types import SimpleNamespace

    user = SimpleNamespace(id="u1", email="a@b.com", session_epoch=3)
    claims = sec.read_session(sec.make_session(user))
    assert claims["epoch"] == 3
    assert "iat" in claims and "aexp" in claims
    # exp is the sliding idle expiry, never beyond the absolute cap.
    assert claims["exp"] <= claims["aexp"]


def test_make_session_absolute_exp_preserved_across_reissue(_fake_secret):
    sec = _fake_secret
    from types import SimpleNamespace
    from datetime import datetime, timezone, timedelta

    user = SimpleNamespace(id="u1", email="a@b.com", session_epoch=0)
    fixed_aexp = datetime.now(timezone.utc) + timedelta(hours=2)
    claims = sec.read_session(sec.make_session(user, absolute_exp=fixed_aexp))
    # A re-issued token keeps the SAME absolute cap (does not extend the session forever).
    assert claims["aexp"] == int(fixed_aexp.timestamp())


def test_make_session_defaults_epoch_zero_for_epochless_subject(_fake_secret):
    sec = _fake_secret
    from app.api.auth import AuthUser

    # An AuthUser (no session_epoch attr) still encodes — epoch defaults to 0.
    claims = sec.read_session(sec.make_session(AuthUser(id="u1", email="a@b.com")))
    assert claims["epoch"] == 0


# ---------------------------------------------------------------------------
# Secret bootstrap (S4)
# ---------------------------------------------------------------------------


def test_secret_bootstrap_generates_and_persists(monkeypatch, tmp_path):
    """Without env var or file, load_secret() creates + persists a ≥32-byte secret."""
    monkeypatch.delenv("AUTH_SECRET", raising=False)
    secret_path = tmp_path / "auth_secret"

    import app.config as _cfg

    monkeypatch.setattr(_cfg, "AUTH_SECRET_FILE", str(secret_path))

    import importlib
    import app.api.security as sec

    importlib.reload(sec)

    s1 = sec.load_secret()
    assert len(s1) >= 32
    assert secret_path.exists()

    # Second call reads the same value
    s2 = sec.load_secret()
    assert s1 == s2

    # Reload the module too to clear module cache
    importlib.reload(sec)


def test_secret_env_var_wins(monkeypatch, tmp_path):
    """When AUTH_SECRET is set, it is used regardless of the file."""
    expected = "x" * 40
    monkeypatch.setenv("AUTH_SECRET", expected)

    import app.config as _cfg

    monkeypatch.setattr(_cfg, "AUTH_SECRET_FILE", str(tmp_path / "auth_secret"))

    import importlib
    import app.api.security as sec

    importlib.reload(sec)

    assert sec.load_secret() == expected

    importlib.reload(sec)


def test_secret_never_hardcoded_default(monkeypatch, tmp_path):
    """load_secret() must NEVER return a hardcoded literal (S4)."""
    monkeypatch.delenv("AUTH_SECRET", raising=False)
    secret_path = tmp_path / "auth_secret"

    import app.config as _cfg

    monkeypatch.setattr(_cfg, "AUTH_SECRET_FILE", str(secret_path))

    import importlib
    import app.api.security as sec

    importlib.reload(sec)

    s = sec.load_secret()
    # Not a known hardcoded literal (any short/empty/trivial string)
    assert s != ""
    assert s != "secret"
    assert s != "changeme"
    assert len(s) >= 32

    importlib.reload(sec)
