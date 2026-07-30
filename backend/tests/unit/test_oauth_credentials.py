"""Unit tests for app.delivery.oauth_credentials (feature 031)."""

import os
from unittest.mock import patch, MagicMock

from app.delivery.oauth_credentials import write_token_tempfile, revoke_token


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
