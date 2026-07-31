"""Feature 032 (W1): the central OAuth bootstrap writes the token ENCRYPTED at rest."""

import importlib.util
from pathlib import Path


def _load_bootstrap():
    path = Path(__file__).resolve().parents[2] / "scripts" / "oauth_bootstrap.py"
    spec = importlib.util.spec_from_file_location("oauth_bootstrap_mod", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_bootstrap_writes_encrypted_token(tmp_path):
    mod = _load_bootstrap()
    from app.security import crypto

    token_json = '{"refresh_token": "boot-secret", "token": "t"}'
    dest = tmp_path / "google_token.json"
    mod._write_token_encrypted(dest, token_json)

    raw = dest.read_text(encoding="utf-8")
    assert "boot-secret" not in raw          # not plaintext on disk
    assert "refresh_token" not in raw        # field name doesn't leak
    assert crypto.decrypt(raw) == token_json  # decrypts back to the original
