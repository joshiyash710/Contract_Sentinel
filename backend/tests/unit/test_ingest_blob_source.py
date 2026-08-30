"""Feature 054: ingest reads the contract source from the Turso blob store (durable uploads).

The Turso backend is exercised via a REAL local SQLite `upload_blobs` table (libSQL is SQLite-compatible),
so no network/libsql is needed. Covers AC-2 (restart-survival read from blob), AC-5 (plaintext blob with
encryption on), AC-6 (missing blob → corrupted_file), and AC-7 (disk branch byte-identity when Turso unset).
"""

import os
import sqlite3

import pytest

import app.blob_store as blob_store
import app.config as _cfg
from app.graph.nodes.ingest_agent import _materialize_plaintext, ingest_agent
from app.security import crypto


@pytest.fixture
def turso_uploads(tmp_path, monkeypatch):
    """Simulate the Turso backend with a real local SQLite upload_blobs table + per-op connections."""
    dbfile = tmp_path / "blobs.db"

    def _mk_conn():
        c = sqlite3.connect(str(dbfile), check_same_thread=False)
        c.row_factory = sqlite3.Row
        return c

    seed = _mk_conn()
    seed.execute(
        "CREATE TABLE upload_blobs (key TEXT PRIMARY KEY, data BLOB NOT NULL, created_at TEXT NOT NULL)"
    )
    seed.commit()
    seed.close()

    monkeypatch.setattr(_cfg, "TURSO_DATABASE_URL", "libsql://x.turso.io")
    monkeypatch.setattr(blob_store, "_conn", _mk_conn)
    return dbfile


# ── AC-2: restart-survival — read the source from the blob when the disk file is gone ─────────
def test_materialize_reads_encrypted_blob_after_disk_gone(turso_uploads, sample_pdf_path, tmp_path):
    dp = str(tmp_path / "uploads" / "job1.pdf")  # a path that is NEVER created on disk
    with open(sample_pdf_path, "rb") as f:
        original = f.read()
    blob_store.write(dp, crypto.encrypt_bytes(original), table="upload_blobs")
    assert not os.path.exists(dp)  # simulate the ephemeral-disk wipe after a container restart

    parse_path, is_temp = _materialize_plaintext(dp, ".pdf")
    try:
        assert is_temp is True
        assert os.path.exists(parse_path)
        with open(parse_path, "rb") as f:
            assert f.read() == original  # decrypted blob == original bytes
    finally:
        os.unlink(parse_path)


def test_ingest_agent_reads_from_blob_after_disk_gone(turso_uploads, sample_pdf_path, tmp_path):
    dp = str(tmp_path / "uploads" / "job1.pdf")
    with open(sample_pdf_path, "rb") as f:
        blob_store.write(dp, crypto.encrypt_bytes(f.read()), table="upload_blobs")
    assert not os.path.exists(dp)

    result = ingest_agent({"document_path": dp})
    assert result.get("ingest_error") is None
    assert len(result["extracted_text"]) > 100


# ── AC-5: plaintext blob with encryption ON → InvalidToken path still materializes ────────────
def test_ingest_plaintext_blob_with_encryption_on(turso_uploads, sample_pdf_path, tmp_path):
    dp = str(tmp_path / "uploads" / "plain.pdf")
    with open(sample_pdf_path, "rb") as f:
        blob_store.write(dp, f.read(), table="upload_blobs")  # PLAINTEXT blob (no encrypt)
    assert not os.path.exists(dp)

    result = ingest_agent({"document_path": dp})  # flag ON by default
    assert result.get("ingest_error") is None
    assert len(result["extracted_text"]) > 100


# ── AC-6: no blob for the key → graceful corrupted_file (EC-3 parity with the disk path) ──────
def test_ingest_missing_blob_is_corrupted_file(turso_uploads, tmp_path):
    dp = str(tmp_path / "uploads" / "missing.pdf")
    with pytest.raises(FileNotFoundError):
        _materialize_plaintext(dp, ".pdf")

    result = ingest_agent({"document_path": dp})
    assert result["ingest_error"] is not None
    assert result["ingest_error"]["error_type"] == "corrupted_file"
    assert result["error_count"] == 1


# ── AC-7: disk branch byte-identity when Turso is unset ───────────────────────────────────────
def test_disk_legacy_plaintext_parses_in_place_when_turso_unset(sample_pdf_path, monkeypatch):
    monkeypatch.setattr(_cfg, "TURSO_DATABASE_URL", "")  # disk backend
    # Encryption ON (default) + a plaintext file → InvalidToken → parse in place, no temp (pre-054).
    parse_path, is_temp = _materialize_plaintext(sample_pdf_path, ".pdf")
    assert (parse_path, is_temp) == (sample_pdf_path, False)


def test_disk_flag_off_parses_in_place_when_turso_unset(sample_pdf_path, monkeypatch):
    monkeypatch.setattr(_cfg, "TURSO_DATABASE_URL", "")
    monkeypatch.setattr(_cfg, "CONTRACT_ENCRYPTION_AT_REST_ENABLED", False)
    parse_path, is_temp = _materialize_plaintext(sample_pdf_path, ".pdf")
    assert (parse_path, is_temp) == (sample_pdf_path, False)
