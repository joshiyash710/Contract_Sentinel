"""Unit tests for app.delivery.oauth_credentials (feature 031 + 032)."""

import os
from unittest.mock import patch, MagicMock

import app.config as _cfg
from app.delivery.oauth_credentials import (
    materialize_central_token_tempfile,
    write_token_tempfile,
    revoke_token,
)


def test_write_token_tempfile_roundtrip():
    token = '{"refresh_token":"abc","client_id":"x"}'
    path = write_token_tempfile(token)
    try:
        assert os.path.exists(path)
        assert open(path, encoding="utf-8").read() == token
    finally:
        os.unlink(path)


def test_revoke_token_posts_and_returns_true():
    resp = MagicMock(status_code=200)
    with patch("app.delivery.oauth_credentials.httpx.post", return_value=resp) as post:
        ok = revoke_token('{"refresh_token":"abc"}')
    assert ok is True
    assert post.called


def test_revoke_token_never_raises_on_network_error():
    with patch("app.delivery.oauth_credentials.httpx.post", side_effect=Exception("net")):
        assert revoke_token('{"refresh_token":"abc"}') is False


def test_revoke_token_handles_bad_json():
    assert revoke_token("not json") is False  # no raise


# ── Feature 032 (W1): central-token decrypt-to-tempfile ──────────────────────────


def test_materialize_central_token_absent_returns_none(monkeypatch, tmp_path):
    monkeypatch.setattr(_cfg, "GOOGLE_OAUTH_TOKEN_PATH", str(tmp_path / "nope.json"))
    assert materialize_central_token_tempfile() is None


def test_materialize_central_token_encrypted_decrypts_to_tempfile(monkeypatch, tmp_path):
    from app.security import crypto

    plaintext = '{"refresh_token": "central-secret"}'
    central = tmp_path / "google_token.json"
    central.write_text(crypto.encrypt(plaintext), encoding="utf-8")
    monkeypatch.setattr(_cfg, "GOOGLE_OAUTH_TOKEN_PATH", str(central))

    path = materialize_central_token_tempfile()
    try:
        assert path is not None and path != str(central)  # a fresh tempfile, not the ciphertext file
        assert open(path, encoding="utf-8").read() == plaintext  # decrypted plaintext
    finally:
        os.unlink(path)


def test_materialize_central_token_legacy_plaintext_returns_original(monkeypatch, tmp_path):
    plaintext = '{"refresh_token": "legacy-central"}'
    central = tmp_path / "google_token.json"
    central.write_text(plaintext, encoding="utf-8")
    monkeypatch.setattr(_cfg, "GOOGLE_OAUTH_TOKEN_PATH", str(central))

    # Legacy plaintext file → returned unchanged (no tempfile).
    assert materialize_central_token_tempfile() == str(central)
