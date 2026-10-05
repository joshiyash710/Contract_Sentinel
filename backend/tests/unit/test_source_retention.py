"""
Feature 056 — upload retention + shared decrypt core. Unit tests.

Covers: registry.mark_terminal retention gate (AC-1/AC-2) and crypto.decrypt_bytes_tolerant (D3).
"""

from unittest.mock import MagicMock

import app.runner.registry as reg_mod
from app.runner.registry import JobRecord
from app.runner.models import JobState
from app.security import crypto


def _record():
    rec = JobRecord(job_id="j1", document_path="data/uploads/j1.pdf", submitted_at="t", buffer=MagicMock())
    rec._store = None
    return rec


def _mark(rec):
    rec.mark_terminal(status=JobState.completed, finished_at="t", report_path=None)


def test_ac1_retention_keeps_upload_blob(monkeypatch):
    # Turso configured + retention ON → the 054 terminal-delete is SKIPPED.
    monkeypatch.setattr(reg_mod._config, "TURSO_DATABASE_URL", "libsql://x")
    monkeypatch.setattr(reg_mod._config, "UPLOAD_SOURCE_RETENTION_ENABLED", True)
    delete = MagicMock()
    monkeypatch.setattr(reg_mod.blob_store, "delete", delete)
    _mark(_record())
    delete.assert_not_called()


def test_ac2_delete_when_retention_off(monkeypatch):
    # Turso configured + retention OFF → 054 behavior unchanged (blob deleted).
    monkeypatch.setattr(reg_mod._config, "TURSO_DATABASE_URL", "libsql://x")
    monkeypatch.setattr(reg_mod._config, "UPLOAD_SOURCE_RETENTION_ENABLED", False)
    delete = MagicMock()
    monkeypatch.setattr(reg_mod.blob_store, "delete", delete)
    _mark(_record())
    delete.assert_called_once()
    assert delete.call_args.kwargs.get("table") == "upload_blobs"


def test_ac2_no_delete_without_turso(monkeypatch):
    # Disk backend (no Turso) → never deletes, regardless of the retention flag.
    monkeypatch.setattr(reg_mod._config, "TURSO_DATABASE_URL", "")
    monkeypatch.setattr(reg_mod._config, "UPLOAD_SOURCE_RETENTION_ENABLED", False)
    delete = MagicMock()
    monkeypatch.setattr(reg_mod.blob_store, "delete", delete)
    _mark(_record())
    delete.assert_not_called()


def test_d3_decrypt_bytes_tolerant_roundtrip_and_passthrough(monkeypatch):
    # valid ciphertext round-trips; non-Fernet (legacy plaintext) bytes pass through unchanged.
    monkeypatch.setattr(crypto, "_KEY", None)  # force a fresh key load
    token = crypto.encrypt_bytes(b"%PDF-1.4 real pdf bytes")
    assert crypto.decrypt_bytes_tolerant(token) == b"%PDF-1.4 real pdf bytes"
    assert crypto.decrypt_bytes_tolerant(b"not a fernet token") == b"not a fernet token"
