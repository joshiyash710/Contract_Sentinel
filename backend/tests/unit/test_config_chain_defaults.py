"""Feature 060 — the 055/056 chain flags default to True (AC-1/AC-2/AC-3).

`app.config` resolves `_env_bool` at import, so the DEFAULT a flag takes when its env var is unset is only
observable by reloading the module under a controlled environment. An autouse module-teardown fixture
reloads `app.config` once after this file's tests (with the real, monkeypatch-restored environment) so no
mutated module leaks into the rest of the suite.
"""

import importlib

import pytest

import app.config as config_mod


@pytest.fixture(autouse=True, scope="module")
def _restore_config_after_module():
    # After every test in this module has run (and all function-scoped monkeypatches have been undone),
    # reload app.config under the real environment so later test modules see the true defaults.
    yield
    importlib.reload(config_mod)


def test_pdf_source_locator_defaults_true_when_unset(monkeypatch):
    # AC-1: PDF_SOURCE_LOCATOR_ENABLED defaults to True when the env var is unset.
    monkeypatch.delenv("PDF_SOURCE_LOCATOR_ENABLED", raising=False)
    importlib.reload(config_mod)
    assert config_mod.PDF_SOURCE_LOCATOR_ENABLED is True


def test_upload_source_retention_defaults_true_when_unset(monkeypatch):
    # AC-2: UPLOAD_SOURCE_RETENTION_ENABLED defaults to True when the env var is unset.
    monkeypatch.delenv("UPLOAD_SOURCE_RETENTION_ENABLED", raising=False)
    importlib.reload(config_mod)
    assert config_mod.UPLOAD_SOURCE_RETENTION_ENABLED is True


def test_env_override_still_wins(monkeypatch):
    # AC-3: an explicit falsey env override still resolves False — the override path is unchanged.
    monkeypatch.setenv("PDF_SOURCE_LOCATOR_ENABLED", "False")
    monkeypatch.setenv("UPLOAD_SOURCE_RETENTION_ENABLED", "False")
    importlib.reload(config_mod)
    assert config_mod.PDF_SOURCE_LOCATOR_ENABLED is False
    assert config_mod.UPLOAD_SOURCE_RETENTION_ENABLED is False
