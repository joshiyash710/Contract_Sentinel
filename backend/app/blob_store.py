"""Report artifact storage (feature 052).

Default: local disk under `REPORT_OUTPUT_DIR` (byte-identical to today). When `TURSO_DATABASE_URL` is set
(feature 051's switch), the durable report artifacts (`.json`/`.md`) live as BLOBs in the Turso
`report_blobs` table via the feature-051 `db_backend` libsql connection. Keys are the existing report
path strings (`report_path` and its `.json`/`.pdf` siblings), so there is no `ContractState` change.

`db_backend` is imported LAZILY inside `_conn()` — importing this module at the top of a graph node
(`report_agent`) must not trigger `app.runner`'s package __init__ (which eagerly imports the graph
builder) and a circular import. `TURSO_AUTH_TOKEN` is never logged (inherited from `db_backend`).
"""

import datetime
import tempfile
from contextlib import contextmanager
from pathlib import Path

import app.config as _config


class BlobNotFound(Exception):
    """Raised by `read()` when no blob/file exists for the key."""


# Feature 054: uploads and reports live in DISTINCT Turso tables so their lifecycles stay separate
# (reports are durable; uploads are terminal-deleted). The table name is NEVER taken from request/user
# data — only the two literals below — so interpolating it into the SQL has no injection surface.
_ALLOWED_TABLES = {"report_blobs", "upload_blobs"}


def _tbl(table: str) -> str:
    if table not in _ALLOWED_TABLES:
        raise ValueError(f"unknown blob table {table!r}")
    return table


def _use_turso() -> bool:
    return bool(_config.TURSO_DATABASE_URL)


def _conn():
    # Lazy import: avoids the app.runner package-init cycle when a graph node imports blob_store.
    from app.runner import db_backend

    return db_backend.connect(_config.JOB_STORE_DB_PATH)  # Turso when TURSO_DATABASE_URL is set


def write(key: str, data: bytes, *, table: str = "report_blobs") -> None:
    if _use_turso():
        tbl = _tbl(table)
        conn = _conn()
        try:
            conn.execute(
                f"INSERT INTO {tbl} (key, data, created_at) VALUES (?,?,?) "
                "ON CONFLICT(key) DO UPDATE SET data=excluded.data, created_at=excluded.created_at",
                (key, data, datetime.datetime.utcnow().isoformat()),
            )
            conn.commit()
        finally:
            conn.close()
    else:
        p = Path(key)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)


def read(key: str, *, table: str = "report_blobs") -> bytes:
    if _use_turso():
        tbl = _tbl(table)
        conn = _conn()
        try:
            row = conn.execute(f"SELECT data FROM {tbl} WHERE key=?", (key,)).fetchone()
        finally:
            conn.close()
        if row is None:
            raise BlobNotFound(key)
        return bytes(row["data"])
    p = Path(key)
    if not p.exists():
        raise BlobNotFound(key)
    return p.read_bytes()


def exists(key: str, *, table: str = "report_blobs") -> bool:
    if _use_turso():
        tbl = _tbl(table)
        conn = _conn()
        try:
            return (
                conn.execute(f"SELECT 1 FROM {tbl} WHERE key=?", (key,)).fetchone() is not None
            )
        finally:
            conn.close()
    return Path(key).exists()


def delete(key: str, *, table: str = "report_blobs") -> None:
    if _use_turso():
        tbl = _tbl(table)
        conn = _conn()
        try:
            conn.execute(f"DELETE FROM {tbl} WHERE key=?", (key,))
            conn.commit()
        finally:
            conn.close()
    else:
        Path(key).unlink(missing_ok=True)


@contextmanager
def materialize(keys):
    """Yield `{key: local Path}` for the given report keys.

    Local backend → the real `REPORT_OUTPUT_DIR` paths (no copy, no cleanup). Turso → each blob written
    to a tempfile in ONE tempdir, preserving basename so `.with_suffix('.pdf')` siblings work; the
    tempdir is removed on exit (even on error).
    """
    keys = list(keys)
    if not _use_turso():
        yield {k: Path(k) for k in keys}
        return
    with tempfile.TemporaryDirectory(prefix="cs_report_") as d:
        out = {}
        for k in keys:
            tp = Path(d) / Path(k).name  # preserve basename+suffix for the PDF sibling
            tp.write_bytes(read(k))
            out[k] = tp
        yield out
