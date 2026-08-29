"""Unit tests for the feature-051 store-DB connection factory (app/runner/db_backend.py).

libsql is MOCKED — no network. Covers AC-1 (factory dispatch), AC-3 (dict-row read shim),
AC-3b (rowcount / executemany mutation shim), AC-6 (missing-token error without leaking).
The default path uses a real local SQLite (byte-identical); only the Turso path is mocked.
"""

import sqlite3
from unittest.mock import MagicMock

import pytest

import app.runner.db_backend as db_backend


class FakeRawCursor:
    def __init__(self, description=None, rows=None, rowcount=-1):
        self.description = description
        self._rows = list(rows or [])
        self.rowcount = rowcount

    def fetchone(self):
        return self._rows.pop(0) if self._rows else None

    def fetchall(self):
        r = list(self._rows)
        self._rows = []
        return r


class FakeRawConn:
    def __init__(self, cursor=None):
        self.executed = []
        self._cursor = cursor or FakeRawCursor()
        self.committed = 0
        self.closed = False

    def execute(self, sql, params=()):
        self.executed.append((sql, tuple(params)))
        return self._cursor

    def commit(self):
        self.committed += 1

    def close(self):
        self.closed = True


# ── AC-1: factory dispatch ───────────────────────────────────────────────────
def test_connect_default_returns_sqlite(monkeypatch, tmp_path):
    monkeypatch.setattr(db_backend._config, "TURSO_DATABASE_URL", "")
    conn = db_backend.connect(str(tmp_path / "x.db"))
    assert isinstance(conn, sqlite3.Connection)
    assert conn.row_factory is sqlite3.Row
    conn.close()


def test_connect_turso_returns_wrapper(monkeypatch):
    monkeypatch.setattr(db_backend._config, "TURSO_DATABASE_URL", "libsql://x.turso.io")
    monkeypatch.setattr(db_backend._config, "TURSO_AUTH_TOKEN", "tok")
    raw = FakeRawConn()
    monkeypatch.setattr(db_backend.libsql, "connect", MagicMock(return_value=raw))
    conn = db_backend.connect("ignored")
    assert isinstance(conn, db_backend._LibsqlConn)
    call = db_backend.libsql.connect.call_args
    assert call.args[0] == "libsql://x.turso.io"
    assert call.kwargs.get("auth_token") == "tok"


# ── AC-3: read shim ──────────────────────────────────────────────────────────
def test_row_by_name_positional_keys_iter():
    row = db_backend._Row(["id", "v"], (1, "x"))
    assert row["v"] == "x" and row["id"] == 1
    assert row[0] == 1
    assert list(row.keys()) == ["id", "v"]
    assert "v" in row.keys()
    assert list(iter(row)) == [1, "x"]
    assert len(row) == 2


def test_row_aggregate_alias_and_positional():
    row = db_backend._Row(["n"], (3,))
    assert row["n"] == 3
    assert row[0] == 3


def test_cursor_fetch_wraps_into_row():
    raw = FakeRawCursor(
        description=[("id", None, None, None, None, None, None),
                     ("v", None, None, None, None, None, None)],
        rows=[(1, "a"), (2, "b")],
    )
    cur = db_backend._LibsqlCursor(raw)
    r1 = cur.fetchone()
    assert r1["v"] == "a" and r1[0] == 1
    rest = cur.fetchall()
    assert rest[0]["id"] == 2


def test_cursor_fetchone_none_passthrough():
    cur = db_backend._LibsqlCursor(FakeRawCursor(description=[("v", 0, 0, 0, 0, 0, 0)], rows=[]))
    assert cur.fetchone() is None


# ── AC-3b: mutation shim ─────────────────────────────────────────────────────
def test_cursor_rowcount_delegates():
    assert db_backend._LibsqlCursor(FakeRawCursor(rowcount=1)).rowcount == 1


def test_executemany_issues_n_executes():
    raw = FakeRawConn()
    db_backend._LibsqlConn(raw).executemany(
        "DELETE FROM jobs WHERE job_id=?", [("a",), ("b",), ("c",)]
    )
    assert raw.executed == [
        ("DELETE FROM jobs WHERE job_id=?", ("a",)),
        ("DELETE FROM jobs WHERE job_id=?", ("b",)),
        ("DELETE FROM jobs WHERE job_id=?", ("c",)),
    ]


def test_executemany_empty_seq_is_noop():
    raw = FakeRawConn()
    db_backend._LibsqlConn(raw).executemany("DELETE FROM jobs WHERE job_id=?", [])
    # MUST NOT run the parameterized DELETE with empty params (would raise on a real driver).
    assert all(sql != "DELETE FROM jobs WHERE job_id=?" for sql, _ in raw.executed)


def test_conn_execute_commit_close_delegate():
    raw = FakeRawConn(cursor=FakeRawCursor(rows=[(1,)]))
    conn = db_backend._LibsqlConn(raw)
    assert isinstance(conn.execute("SELECT 1"), db_backend._LibsqlCursor)
    conn.commit()
    conn.close()
    assert raw.committed == 1 and raw.closed


# ── AC-6: missing token → clear error, no leak ───────────────────────────────
def test_turso_missing_token_raises_without_leaking(monkeypatch):
    monkeypatch.setattr(db_backend._config, "TURSO_DATABASE_URL", "libsql://x.turso.io")
    monkeypatch.setattr(db_backend._config, "TURSO_AUTH_TOKEN", "")
    with pytest.raises(ValueError) as exc:
        db_backend.connect("ignored")
    assert "TURSO_AUTH_TOKEN" in str(exc.value)  # names the missing var
    assert "hf_" not in str(exc.value) and "eyJ" not in str(exc.value)  # no token material
