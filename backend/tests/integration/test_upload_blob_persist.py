"""Feature 054: POST /api/analyze persists the uploaded contract to the Turso blob store (AC-1, AC-7, EC-5).

Integration test (drives the real analyze route). The Turso backend is simulated by pointing
`blob_store._conn` at the already-migrated local `job_store.db` (which has `upload_blobs` via migration
0010). The `client` fixture pre-authenticates and disables startup recovery.
"""

import os
import sqlite3

import app.blob_store as blob_store
import app.config as _config


def _use_local_turso(monkeypatch):
    """Enable the Turso code path but route blob_store at the local migrated job_store.db."""

    def _mk_conn():
        c = sqlite3.connect(_config.JOB_STORE_DB_PATH, check_same_thread=False)
        c.row_factory = sqlite3.Row
        return c

    monkeypatch.setattr(_config, "TURSO_DATABASE_URL", "libsql://x.turso.io")
    monkeypatch.setattr(blob_store, "_conn", _mk_conn)


# ── AC-1: upload persisted to upload_blobs under Turso ────────────────────────────────────────
def test_upload_persisted_to_upload_blobs_on_turso(client, monkeypatch):
    _use_local_turso(monkeypatch)
    # The terminal-delete (T5) would race this assertion — neutralize it here (delete has its own test).
    monkeypatch.setattr(blob_store, "delete", lambda *a, **k: None)

    resp = client.post(
        "/api/analyze",
        files={"file": ("contract.pdf", b"%PDF-1.4 hello world", "application/pdf")},
    )
    assert resp.status_code == 202
    job_id = resp.json()["job_id"]

    dp = os.path.join(_config.UPLOAD_DIR, f"{job_id}.pdf")
    assert blob_store.exists(dp, table="upload_blobs") is True
    with open(dp, "rb") as f:
        assert blob_store.read(dp, table="upload_blobs") == f.read()  # blob == finalized (ciphertext) bytes


# ── AC-7: no upload-blob write on the disk backend (Turso unset) ──────────────────────────────
def test_no_blob_write_when_turso_unset(client, monkeypatch):
    monkeypatch.setattr(_config, "TURSO_DATABASE_URL", "")
    calls = []
    monkeypatch.setattr(blob_store, "write", lambda *a, **k: calls.append(a))

    resp = client.post(
        "/api/analyze",
        files={"file": ("contract.pdf", b"%PDF-1.4 hi", "application/pdf")},
    )
    assert resp.status_code == 202
    job_id = resp.json()["job_id"]
    dp = os.path.join(_config.UPLOAD_DIR, f"{job_id}.pdf")
    assert os.path.exists(dp)  # disk write unchanged (pre-054)
    assert calls == []  # no upload-blob persist on the disk backend


# ── EC-5: a blob-store write failure surfaces as 500, no half-durable job ─────────────────────
def test_blob_write_failure_returns_500(client, monkeypatch):
    monkeypatch.setattr(_config, "TURSO_DATABASE_URL", "libsql://x.turso.io")

    def _boom(*a, **k):
        raise RuntimeError("turso down")

    monkeypatch.setattr(blob_store, "write", _boom)

    resp = client.post(
        "/api/analyze",
        files={"file": ("contract.pdf", b"%PDF-1.4 hi", "application/pdf")},
    )
    assert resp.status_code == 500
