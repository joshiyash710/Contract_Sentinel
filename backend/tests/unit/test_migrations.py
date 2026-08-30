"""Feature 051/053 (AC-5/AC-6): upgrade_to_head migrates local SQLite by default, or Turso via
sqlalchemy-libsql with the auth token in connect_args (NOT the URL query) + an injected Alembic
connection. Never leaks TURSO_AUTH_TOKEN. The Turso path mocks create_engine (sqlalchemy-libsql is
Linux-only; these run on Windows and never touch the network)."""

import pytest

import app.runner.migrations as migrations


class _FakeConn:
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class _FakeEngine:
    def __init__(self):
        self.disposed = False

    def connect(self):
        return _FakeConn()

    def dispose(self):
        self.disposed = True


def test_local_sqlite_url_when_turso_unset(monkeypatch, tmp_path):
    monkeypatch.setattr(migrations._config, "TURSO_DATABASE_URL", "")
    calls = {}
    monkeypatch.setattr(
        migrations.command, "upgrade",
        lambda cfg, rev: calls.update(url=cfg.get_main_option("sqlalchemy.url"), rev=rev),
    )
    migrations.upgrade_to_head(str(tmp_path / "s.db"))
    assert calls["url"].startswith("sqlite:///")
    assert "libsql" not in calls["url"]
    assert calls["rev"] == "head"


def test_turso_uses_connect_args_auth_token(monkeypatch):
    monkeypatch.setattr(migrations._config, "TURSO_DATABASE_URL", "libsql://mydb-org.turso.io")
    monkeypatch.setattr(migrations._config, "TURSO_AUTH_TOKEN", "sekrit-token")
    captured = {}

    def fake_create_engine(url, connect_args=None):
        captured["url"] = url
        captured["connect_args"] = connect_args
        return _FakeEngine()

    monkeypatch.setattr(migrations, "create_engine", fake_create_engine)
    monkeypatch.setattr(
        migrations.command, "upgrade",
        lambda cfg, rev: captured.update(injected=cfg.attributes.get("connection")),
    )
    migrations.upgrade_to_head("ignored")

    # remote URL WITHOUT the token; token is in connect_args; live connection injected into Alembic.
    assert captured["url"].startswith("sqlite+libsql://")
    assert "mydb-org.turso.io" in captured["url"]
    assert "authToken" not in captured["url"] and "sekrit-token" not in captured["url"]
    assert captured["connect_args"] == {"auth_token": "sekrit-token"}
    assert captured["injected"] is not None


def test_token_never_logged(monkeypatch, caplog):
    monkeypatch.setattr(migrations._config, "TURSO_DATABASE_URL", "libsql://mydb-org.turso.io")
    monkeypatch.setattr(migrations._config, "TURSO_AUTH_TOKEN", "sekrit-token-xyz")
    monkeypatch.setattr(migrations, "create_engine", lambda url, connect_args=None: _FakeEngine())
    monkeypatch.setattr(migrations.command, "upgrade", lambda cfg, rev: None)
    with caplog.at_level("DEBUG"):
        migrations.upgrade_to_head("ignored")
    assert "sekrit-token-xyz" not in caplog.text


def test_exception_message_redacts_token(monkeypatch):
    token = "sekrit-token-xyz"
    monkeypatch.setattr(migrations._config, "TURSO_DATABASE_URL", "libsql://mydb-org.turso.io")
    monkeypatch.setattr(migrations._config, "TURSO_AUTH_TOKEN", token)
    monkeypatch.setattr(migrations, "create_engine", lambda url, connect_args=None: _FakeEngine())

    def boom(cfg, rev):
        raise RuntimeError(f"connection failed ...auth_token={token}...")

    monkeypatch.setattr(migrations.command, "upgrade", boom)
    with pytest.raises(Exception) as exc:
        migrations.upgrade_to_head("ignored")
    assert token not in str(exc.value)
    assert "<redacted>" in str(exc.value)
