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


# ── Feature 063: reconnect-and-retry on dropped Hrana connections ─────────────
_DROP = ValueError("Hrana: http error: connection closed before message completed")


class _RaiseConn:
    """Raw conn whose execute/commit always raise `exc` (a dropped connection)."""

    def __init__(self, exc):
        self._exc = exc
        self.closed = False

    def execute(self, sql, params=()):
        raise self._exc

    def commit(self):
        raise self._exc

    def close(self):
        self.closed = True


def test_reconnect_then_retry_succeeds(monkeypatch):  # AC-1
    monkeypatch.setattr(db_backend.time, "sleep", lambda *_: None)
    monkeypatch.setattr(db_backend._config, "TURSO_RECONNECT_MAX_RETRIES", 2)
    good = FakeRawConn(cursor=FakeRawCursor(rows=[(1,)]))
    reconnect = MagicMock(return_value=good)
    conn = db_backend._LibsqlConn(_RaiseConn(_DROP), reconnect=reconnect)
    cur = conn.execute("SELECT 1")
    assert isinstance(cur, db_backend._LibsqlCursor)
    assert reconnect.call_count == 1          # dead conn replaced once
    assert good.executed == [("SELECT 1", ())]


def test_retry_budget_exhausted_raises(monkeypatch):  # AC-2
    monkeypatch.setattr(db_backend.time, "sleep", lambda *_: None)
    monkeypatch.setattr(db_backend._config, "TURSO_RECONNECT_MAX_RETRIES", 2)
    reconnect = MagicMock(side_effect=lambda: _RaiseConn(_DROP))  # every reconnect still drops
    conn = db_backend._LibsqlConn(_RaiseConn(_DROP), reconnect=reconnect)
    with pytest.raises(ValueError):
        conn.execute("SELECT 1")
    assert reconnect.call_count == 2          # reconnect tried exactly the budget, then raised


def test_non_drop_error_not_retried(monkeypatch):  # AC-3
    monkeypatch.setattr(db_backend.time, "sleep", lambda *_: None)
    monkeypatch.setattr(db_backend._config, "TURSO_RECONNECT_MAX_RETRIES", 2)
    reconnect = MagicMock()
    conn = db_backend._LibsqlConn(_RaiseConn(ValueError("UNIQUE constraint failed")), reconnect=reconnect)
    with pytest.raises(ValueError) as exc:
        conn.execute("INSERT INTO t VALUES (1)")
    assert "UNIQUE" in str(exc.value)
    assert reconnect.call_count == 0          # non-drop error propagates immediately, no retry


def test_executemany_and_commit_retry_on_drop(monkeypatch):  # AC-4
    monkeypatch.setattr(db_backend.time, "sleep", lambda *_: None)
    monkeypatch.setattr(db_backend._config, "TURSO_RECONNECT_MAX_RETRIES", 2)
    good_em = FakeRawConn()
    db_backend._LibsqlConn(_RaiseConn(_DROP), reconnect=MagicMock(return_value=good_em)).executemany(
        "DELETE FROM jobs WHERE job_id=?", [("a",), ("b",)]
    )
    assert good_em.executed == [
        ("DELETE FROM jobs WHERE job_id=?", ("a",)),
        ("DELETE FROM jobs WHERE job_id=?", ("b",)),
    ]
    good_commit = FakeRawConn()
    db_backend._LibsqlConn(_RaiseConn(_DROP), reconnect=MagicMock(return_value=good_commit)).commit()
    assert good_commit.committed == 1


def test_reconnect_warning_omits_token_and_params(monkeypatch, caplog):  # AC-6
    sleeps = []
    monkeypatch.setattr(db_backend.time, "sleep", lambda *_: sleeps.append(1))
    monkeypatch.setattr(db_backend._config, "TURSO_DATABASE_URL", "libsql://x.turso.io")
    monkeypatch.setattr(db_backend._config, "TURSO_AUTH_TOKEN", "sekrettoken123")
    monkeypatch.setattr(db_backend._config, "TURSO_RECONNECT_MAX_RETRIES", 2)
    good = FakeRawConn(cursor=FakeRawCursor(rows=[(1,)]))
    # connect() builds the wrapper with the real _turso_raw_connect reconnect factory; first raw drops,
    # the reconnect returns a good conn.
    monkeypatch.setattr(db_backend.libsql, "connect", MagicMock(side_effect=[_RaiseConn(_DROP), good]))
    conn = db_backend.connect("ignored")
    with caplog.at_level("WARNING"):
        conn.execute("UPDATE users SET x=? WHERE token=?", ("userdata", "usersecret"))
    assert any("reconnect" in r.getMessage().lower() for r in caplog.records)  # a reconnect was logged
    assert "sekrettoken123" not in caplog.text                                 # token never logged
    assert "usersecret" not in caplog.text and "userdata" not in caplog.text   # SQL params never logged
    assert sleeps                                                              # backoff sleep (stubbed) ran


def test_retry_count_honors_config(monkeypatch):  # AC-7
    monkeypatch.setattr(db_backend.time, "sleep", lambda *_: None)
    monkeypatch.setattr(db_backend._config, "TURSO_RECONNECT_MAX_RETRIES", 1)
    reconnect = MagicMock(side_effect=lambda: _RaiseConn(_DROP))
    conn = db_backend._LibsqlConn(_RaiseConn(_DROP), reconnect=reconnect)
    with pytest.raises(ValueError):
        conn.execute("SELECT 1")
    assert reconnect.call_count == 1          # budget=1 → exactly one reconnect, then raise
