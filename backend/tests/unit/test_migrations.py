"""Feature 051 (AC-5/AC-6): upgrade_to_head selects the Turso `sqlite+libsql://` URL when
TURSO_DATABASE_URL is set (else the local sqlite:/// URL), and never leaks TURSO_AUTH_TOKEN.

`command.upgrade` is patched so the Linux-only `sqlalchemy-libsql` dialect is never invoked — these run
on Windows and assert only the Config the helper builds + the token-redaction guard.
"""

import pytest

import app.runner.migrations as migrations


def _capture_url(monkeypatch):
    calls = {}

    def fake_upgrade(cfg, rev):
        calls["url"] = cfg.get_main_option("sqlalchemy.url")
        calls["rev"] = rev

    monkeypatch.setattr(migrations.command, "upgrade", fake_upgrade)
    return calls


def test_local_sqlite_url_when_turso_unset(monkeypatch, tmp_path):
    monkeypatch.setattr(migrations._config, "TURSO_DATABASE_URL", "")
    calls = _capture_url(monkeypatch)
    migrations.upgrade_to_head(str(tmp_path / "s.db"))
    assert calls["url"].startswith("sqlite:///")
    assert "libsql" not in calls["url"]
    assert calls["rev"] == "head"


def test_turso_url_when_set(monkeypatch):
    monkeypatch.setattr(migrations._config, "TURSO_DATABASE_URL", "libsql://mydb-org.turso.io")
    monkeypatch.setattr(migrations._config, "TURSO_AUTH_TOKEN", "sekrit-token")
    calls = _capture_url(monkeypatch)
    migrations.upgrade_to_head("ignored")
    url = calls["url"]
    assert url.startswith("sqlite+libsql://")
    assert "mydb-org.turso.io" in url


def test_token_never_logged(monkeypatch, caplog):
    monkeypatch.setattr(migrations._config, "TURSO_DATABASE_URL", "libsql://mydb-org.turso.io")
    monkeypatch.setattr(migrations._config, "TURSO_AUTH_TOKEN", "sekrit-token-xyz")
    monkeypatch.setattr(migrations.command, "upgrade", lambda cfg, rev: None)
    with caplog.at_level("DEBUG"):
        migrations.upgrade_to_head("ignored")
    assert "sekrit-token-xyz" not in caplog.text


def test_exception_message_redacts_token(monkeypatch):
    token = "sekrit-token-xyz"
    monkeypatch.setattr(migrations._config, "TURSO_DATABASE_URL", "libsql://mydb-org.turso.io")
    monkeypatch.setattr(migrations._config, "TURSO_AUTH_TOKEN", token)

    def boom(cfg, rev):
        raise RuntimeError(f"connection failed for url ...authToken={token}...")

    monkeypatch.setattr(migrations.command, "upgrade", boom)
    with pytest.raises(Exception) as exc:
        migrations.upgrade_to_head("ignored")
    assert token not in str(exc.value)
    assert "<redacted>" in str(exc.value)
