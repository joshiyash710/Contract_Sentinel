"""
Unit tests for the reset-token helpers (feature 034) — generate_reset_token + hash_reset_token.

hash_reset_token is HMAC-SHA256 keyed with AUTH_SECRET (Decision 2), so the stored value is bound to
the app secret, deterministic for a given (secret, raw), and never equal to the raw token.
"""

import app.api.security as security


def test_generate_reset_token_unique_and_long():
    a = security.generate_reset_token()
    b = security.generate_reset_token()
    assert isinstance(a, str) and isinstance(b, str)
    assert a != b
    assert len(a) >= 40


def test_hash_reset_token_deterministic_hex_and_not_raw():
    h1 = security.hash_reset_token("abc")
    h2 = security.hash_reset_token("abc")
    assert h1 == h2
    assert h1 != "abc"
    assert len(h1) == 64  # sha256 hexdigest
    int(h1, 16)  # valid hex


def test_hash_reset_token_is_secret_keyed(monkeypatch):
    """Changing AUTH_SECRET changes the hash for the same input (proves HMAC keying)."""
    monkeypatch.setattr(security, "_SECRET", None)
    monkeypatch.setenv("AUTH_SECRET", "secret-one")
    h_one = security.hash_reset_token("same-token")

    monkeypatch.setattr(security, "_SECRET", None)
    monkeypatch.setenv("AUTH_SECRET", "secret-two")
    h_two = security.hash_reset_token("same-token")

    assert h_one != h_two
