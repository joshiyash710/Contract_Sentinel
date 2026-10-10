"""Store-DB connection factory (feature 051).

`connect(db_path)` returns today's `sqlite3` connection by default (byte-identical) or, when
`TURSO_DATABASE_URL` is set, a `libsql` connection wrapped to the exact `sqlite3.Connection`/`Cursor`
surface the three stores use (`JobStore`/`UserStore`/`PasswordResetStore`) — with rows that faithfully
mimic `sqlite3.Row` (by-name incl. aggregate aliases, positional `[0]`, `.keys()`), a delegated
`cursor.rowcount` (load-bearing for `PasswordResetStore.mark_used`'s single-use guarantee), and an
`executemany` (the prune path).

Turso routing is a **Linux-deploy-only** config: this runtime connection uses `libsql` (cross-platform),
but Alembic migrations against Turso need `sqlalchemy-libsql`, which builds only on Linux (see
`app/runner/migrations.py`). `TURSO_AUTH_TOKEN` is read from config and NEVER logged.
"""

import logging
import sqlite3
import time

import libsql  # cross-platform core dep; module-level so tests can patch db_backend.libsql.connect

import app.config as _config

logger = logging.getLogger("contractsentinel.runner.db_backend")


def connect(db_path: str):
    """Return the store-DB connection for the configured backend (read live).

    `TURSO_DATABASE_URL` set → a libsql wrapper; else a local `sqlite3.Connection` (byte-identical).
    """
    if _config.TURSO_DATABASE_URL:
        return _connect_turso()
    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def _turso_raw_connect():
    """Open a fresh raw libsql connection (feature 063: also the reconnect factory for _LibsqlConn)."""
    if not _config.TURSO_AUTH_TOKEN:
        # The token is empty here; the message must never echo any token material.
        raise ValueError(
            "TURSO_DATABASE_URL is set but TURSO_AUTH_TOKEN is empty. Set it in backend/.env "
            "(see docs/DEPLOYMENT.md). The token value is intentionally not shown."
        )
    return libsql.connect(_config.TURSO_DATABASE_URL, auth_token=_config.TURSO_AUTH_TOKEN)


def _connect_turso():
    return _LibsqlConn(_turso_raw_connect(), reconnect=_turso_raw_connect)


# Feature 063: libSQL/Hrana transport-drop signatures (matched case-insensitively on the error message). A
# dropped connection self-heals via reconnect+retry; a SQL/constraint error does NOT match → propagates.
_DROP_MARKERS = (
    "connection closed", "hrana", "stream closed",
    "error communicating", "connection reset", "broken pipe",
)


def _is_connection_drop(exc) -> bool:
    return any(m in str(exc).lower() for m in _DROP_MARKERS)


class _Row:
    """Faithful sqlite3.Row stand-in built from (columns, values)."""

    __slots__ = ("_cols", "_vals")

    def __init__(self, cols, vals):
        self._cols = list(cols)
        self._vals = tuple(vals)

    def __getitem__(self, k):
        return self._vals[k] if isinstance(k, int) else self._vals[self._cols.index(k)]

    def keys(self):
        return list(self._cols)

    def __contains__(self, k):
        return k in self._cols

    def __iter__(self):
        return iter(self._vals)

    def __len__(self):
        return len(self._vals)


class _LibsqlCursor:
    """Wraps a libsql cursor to yield `_Row` objects and expose sqlite3-Cursor attributes."""

    def __init__(self, raw):
        self._raw = raw

    @property
    def description(self):
        return self._raw.description

    @property
    def rowcount(self):
        return self._raw.rowcount  # load-bearing: PasswordResetStore.mark_used single-use

    @property
    def lastrowid(self):
        return getattr(self._raw, "lastrowid", None)

    def _cols(self):
        return [d[0] for d in (self._raw.description or [])]

    def fetchone(self):
        r = self._raw.fetchone()
        return None if r is None else _Row(self._cols(), r)

    def fetchall(self):
        cols = self._cols()
        return [_Row(cols, r) for r in self._raw.fetchall()]

    def __iter__(self):
        return iter(self.fetchall())


class _LibsqlConn:
    """Wraps a libsql connection to the sqlite3.Connection surface the stores use.

    Intentionally has NO `row_factory` attribute — the store swap deletes the
    `self._conn.row_factory = sqlite3.Row` line, and this wrapper yields `_Row` unconditionally.
    """

    def __init__(self, raw, reconnect=None):
        self._raw = raw
        self._reconnect = reconnect  # feature 063: zero-arg factory for a fresh raw conn (None ⇒ no retry)

    def _run(self, op):
        """Feature 063: run op(raw); on a dropped-connection error, reconnect and retry (bounded by
        TURSO_RECONNECT_MAX_RETRIES). A non-drop error, or an exhausted budget, propagates. The whole op
        re-runs against the fresh self._raw, so a reconnected handle is used."""
        attempts = _config.TURSO_RECONNECT_MAX_RETRIES
        last = None
        for i in range(attempts + 1):
            try:
                return op(self._raw)
            except Exception as exc:  # noqa: BLE001 — classified by _is_connection_drop below
                if not (self._reconnect and _is_connection_drop(exc) and i < attempts):
                    raise  # non-drop error, or retries exhausted → propagate (AC-2/AC-3)
                last = exc
                logger.warning(
                    "reconnecting after a dropped Turso connection (attempt %d/%d)", i + 1, attempts
                )  # NEVER log the token or SQL params
                time.sleep(min(2.0 ** i, 8.0))
                try:
                    self._raw = self._reconnect()
                except Exception:  # noqa: BLE001 — reconnect failed; next attempt / exhaust (EC-1)
                    continue
        raise last  # last op (drop) exception = connection unavailable after exhausting retries (EC-1)

    def execute(self, sql, params=()):
        return _LibsqlCursor(self._run(lambda raw: raw.execute(sql, params)))

    def executemany(self, sql, seq):
        # Emulate via an execute-loop (robust regardless of libsql executemany support). An empty seq
        # is a no-op (mirrors sqlite3.executemany([])) — must NOT run `sql` with () params, which would
        # raise a parameter-count mismatch on the parameterized DELETE (prune path). Feature 063:
        # materialize `seq` so a reconnect+retry can re-iterate it.
        rows = list(seq)

        def _op(raw):
            cur = None
            for params in rows:
                cur = raw.execute(sql, params)
            if cur is None:  # empty seq → benign empty cursor (rowcount 0)
                cur = raw.execute("SELECT 1 WHERE 1=0")
            return cur

        return _LibsqlCursor(self._run(_op))

    def commit(self):
        self._run(lambda raw: raw.commit())

    def close(self):
        try:
            self._raw.close()
        except Exception:  # noqa: BLE001 — tolerate an already-dead connection (feature 063)
            pass
