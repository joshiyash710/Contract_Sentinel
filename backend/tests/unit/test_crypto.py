"""
Feature 032 (W1) — encryption-at-rest utility tests.

Covers spec AC-1 (round-trip), AC-4 (key precedence env→file→generate, 0600, never-logged),
and the legacy-plaintext detector used for the lazy-upgrade / migration paths (AC-5).
"""

import json
import logging
import os
import stat

import pytest
from cryptography.fernet import Fernet, InvalidToken

import app.config as _cfg
from app.security import crypto


@pytest.fixture(autouse=True)
def _reset_key_cache_and_env(monkeypatch, tmp_path):
    """Isolate every test: clear the module key cache + env, point the key file at tmp."""
    monkeypatch.setattr(crypto, "_KEY", None, raising=False)
    monkeypatch.delenv(_cfg.ENCRYPTION_KEY_ENV, raising=False)
    monkeypatch.setattr(_cfg, "ENCRYPTION_KEY_FILE", str(tmp_path / "encryption_key"))
    yield
    monkeypatch.setattr(crypto, "_KEY", None, raising=False)


def test_encrypt_decrypt_round_trips():
    # AC-1
    plaintext = '{"refresh_token": "abc123", "token": "xyz"}'
    token = crypto.encrypt(plaintext)
    assert token != plaintext
    assert "refresh_token" not in token  # ciphertext must not leak the field name
    assert crypto.decrypt(token) == plaintext


def test_decrypt_of_foreign_key_raises():
    # A value encrypted under a different key must not silently decode to garbage.
    foreign = Fernet(Fernet.generate_key()).encrypt(b"hello").decode()
    with pytest.raises(InvalidToken):
        crypto.decrypt(foreign)


def test_key_precedence_env_over_file(monkeypatch, tmp_path):
    # AC-4: env var wins over the key file.
    key = Fernet.generate_key().decode()
    monkeypatch.setenv(_cfg.ENCRYPTION_KEY_ENV, key)
    # Even if a file exists with a different key, env is used.
    (tmp_path / "encryption_key").write_text(Fernet.generate_key().decode())
    assert crypto.load_encryption_key() == key.encode()


def test_key_generated_and_persisted_0600_when_absent(monkeypatch, tmp_path):
    # AC-4: no env, no file → generate + persist + reuse.
    key_path = tmp_path / "sub" / "encryption_key"
    monkeypatch.setattr(_cfg, "ENCRYPTION_KEY_FILE", str(key_path))
    monkeypatch.setattr(crypto, "_KEY", None, raising=False)
    k1 = crypto.load_encryption_key()
    assert key_path.exists()
    # A valid Fernet key round-trips.
    assert Fernet(k1).decrypt(Fernet(k1).encrypt(b"x")) == b"x"
    if os.name != "nt":  # 0600 only meaningful where POSIX perms apply
        mode = stat.S_IMODE(key_path.stat().st_mode)
        assert mode == 0o600
    # Cached: a second call returns the same key without regenerating.
    monkeypatch.setattr(crypto, "_KEY", None, raising=False)
    assert crypto.load_encryption_key() == k1


def test_looks_like_plaintext_token():
    # AC-5 legacy detector
    assert crypto.looks_like_plaintext_token('{"refresh_token": "r", "token": "t"}')
    assert crypto.looks_like_plaintext_token('{"token": "t"}')
    assert not crypto.looks_like_plaintext_token("not json")
    assert not crypto.looks_like_plaintext_token('{"unrelated": 1}')
    assert not crypto.looks_like_plaintext_token(crypto.encrypt('{"refresh_token":"r"}'))


def test_key_and_plaintext_never_logged(monkeypatch, caplog):
    # AC-4: neither the key nor decrypted token JSON appears in any log record.
    key = Fernet.generate_key().decode()
    monkeypatch.setenv(_cfg.ENCRYPTION_KEY_ENV, key)
    monkeypatch.setattr(crypto, "_KEY", None, raising=False)
    secret = '{"refresh_token": "super-secret-value-42"}'
    with caplog.at_level(logging.DEBUG):
        token = crypto.encrypt(secret)
        assert crypto.decrypt(token) == secret
        crypto.load_encryption_key()
    blob = " ".join(r.getMessage() for r in caplog.records)
    assert key not in blob
    assert "super-secret-value-42" not in blob
