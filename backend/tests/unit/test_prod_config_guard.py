"""Feature 053 (AC-7): validate_prod_config() fails-fast on the common deploy misconfig and never
echoes a secret value. Warns (not raises) when Turso is set but the at-rest key is not pinned via env."""

import logging

import pytest

import app.config as cfg


def _defaults(monkeypatch):
    monkeypatch.setattr(cfg, "EMBED_PROVIDER", "ollama")
    monkeypatch.setattr(cfg, "LLM_PROVIDER", "ollama")
    monkeypatch.setattr(cfg, "TURSO_DATABASE_URL", "")
    monkeypatch.setattr(cfg, "TURSO_AUTH_TOKEN", "")
    monkeypatch.setattr(cfg, "HF_API_TOKEN", "")
    monkeypatch.setattr(cfg, "GROQ_API_KEY", "")


def test_hf_without_token_raises(monkeypatch):
    _defaults(monkeypatch)
    monkeypatch.setattr(cfg, "EMBED_PROVIDER", "hf")
    with pytest.raises(RuntimeError) as exc:
        cfg.validate_prod_config()
    assert "HF_API_TOKEN" in str(exc.value)


def test_groq_without_key_raises(monkeypatch):
    _defaults(monkeypatch)
    monkeypatch.setattr(cfg, "LLM_PROVIDER", "groq")
    with pytest.raises(RuntimeError) as exc:
        cfg.validate_prod_config()
    assert "GROQ_API_KEY" in str(exc.value)


def test_turso_without_token_raises(monkeypatch):
    _defaults(monkeypatch)
    monkeypatch.setattr(cfg, "TURSO_DATABASE_URL", "libsql://x.turso.io")
    with pytest.raises(RuntimeError) as exc:
        cfg.validate_prod_config()
    assert "TURSO_AUTH_TOKEN" in str(exc.value)


def test_defaults_no_raise(monkeypatch):
    _defaults(monkeypatch)
    cfg.validate_prod_config()  # must not raise


def test_turso_unpinned_key_warns_without_leaking(monkeypatch, caplog):
    _defaults(monkeypatch)
    monkeypatch.setattr(cfg, "TURSO_DATABASE_URL", "libsql://x.turso.io")
    monkeypatch.setattr(cfg, "TURSO_AUTH_TOKEN", "sekrit-token-123")
    monkeypatch.delenv(cfg.ENCRYPTION_KEY_ENV, raising=False)
    with caplog.at_level(logging.WARNING):
        cfg.validate_prod_config()  # no raise — just a warning
    assert any(cfg.ENCRYPTION_KEY_ENV in r.getMessage() for r in caplog.records)
    assert "sekrit-token-123" not in caplog.text  # token never logged
