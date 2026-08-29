"""Unit tests for the feature-052 report blob store (app/blob_store.py).

The Turso path is exercised via a REAL local SQLite `report_blobs` table (libSQL is SQLite-compatible),
so no network / libsql is needed. The disk path uses real tmp files. Covers AC-1 (backend dispatch),
AC-3 (round-trip + materialize on both backends, BlobNotFound).
"""

import sqlite3
from pathlib import Path

import pytest

import app.blob_store as blob_store


@pytest.fixture
def turso_local(tmp_path, monkeypatch):
    """Simulate the Turso backend with a real local SQLite report_blobs table + per-op connections."""
    dbfile = tmp_path / "blobs.db"

    def _mk_conn():
        c = sqlite3.connect(str(dbfile), check_same_thread=False)
        c.row_factory = sqlite3.Row
        return c

    seed = _mk_conn()
    seed.execute(
        "CREATE TABLE report_blobs (key TEXT PRIMARY KEY, data BLOB NOT NULL, created_at TEXT NOT NULL)"
    )
    seed.commit()
    seed.close()

    monkeypatch.setattr(blob_store._config, "TURSO_DATABASE_URL", "libsql://x.turso.io")
    monkeypatch.setattr(blob_store, "_conn", _mk_conn)


# ── AC-1: backend dispatch ───────────────────────────────────────────────────
def test_use_turso_dispatch(monkeypatch):
    monkeypatch.setattr(blob_store._config, "TURSO_DATABASE_URL", "")
    assert blob_store._use_turso() is False
    monkeypatch.setattr(blob_store._config, "TURSO_DATABASE_URL", "libsql://x")
    assert blob_store._use_turso() is True


# ── AC-3: disk backend round-trip ────────────────────────────────────────────
def test_disk_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setattr(blob_store._config, "TURSO_DATABASE_URL", "")
    key = str(tmp_path / "reports" / "j1.md")
    assert blob_store.exists(key) is False
    with pytest.raises(blob_store.BlobNotFound):
        blob_store.read(key)
    blob_store.write(key, b"hello")
    assert blob_store.exists(key) is True
    assert blob_store.read(key) == b"hello"
    blob_store.delete(key)
    assert blob_store.exists(key) is False


def test_disk_materialize_yields_real_paths(tmp_path, monkeypatch):
    monkeypatch.setattr(blob_store._config, "TURSO_DATABASE_URL", "")
    k = str(tmp_path / "reports" / "j1.md")
    blob_store.write(k, b"x")
    with blob_store.materialize([k]) as paths:
        assert paths[k] == Path(k)  # real path, no copy


# ── AC-3: Turso backend round-trip (real local sqlite) ───────────────────────
def test_turso_roundtrip(turso_local):
    key = "data/reports/j1.md"
    assert blob_store.exists(key) is False
    with pytest.raises(blob_store.BlobNotFound):
        blob_store.read(key)
    blob_store.write(key, b"hello")
    assert blob_store.exists(key) is True
    assert blob_store.read(key) == b"hello"
    blob_store.write(key, b"updated")  # ON CONFLICT upsert
    assert blob_store.read(key) == b"updated"
    blob_store.delete(key)
    assert blob_store.exists(key) is False


def test_turso_materialize_tempfiles_cleaned(turso_local):
    md_key = "data/reports/j1.md"
    json_key = "data/reports/j1.json"
    blob_store.write(md_key, b"# report")
    blob_store.write(json_key, b'{"a":1}')
    captured = {}
    with blob_store.materialize([md_key, json_key]) as paths:
        assert paths[md_key].read_bytes() == b"# report"
        assert paths[json_key].read_bytes() == b'{"a":1}'
        assert paths[md_key].name == "j1.md"  # basename preserved → .with_suffix('.pdf') works
        assert paths[md_key].with_suffix(".pdf").parent == paths[md_key].parent
        captured["md"] = paths[md_key]
    assert not captured["md"].exists()  # tempdir removed on exit
