# Feature 065 — Technical plan: single shared connection for the Turso embedded replica

Branch: `feature/065-embedded-replica-shared-conn` (per constitution §11).

Derived from the approved `spec.md`. Fixes 064's `wal_insert_begin failed`: in embedded-replica mode, make
`db_backend.connect()` return **one shared, lock-serialized `_LibsqlConn`** (reused by all three stores)
instead of a new per-store connection that each syncs the same local file. **Runner DB-backend only.
Pure-remote + local SQLite paths byte-identical. No node/edge/`ContractState`/config/migration/dependency/
API/frontend change; no new dependency** (`threading`/`contextlib` are stdlib; reuses 064 flags + 063 reconnect).

## 0. Scope of change (files touched)
```
backend/app/runner/db_backend.py       (shared-singleton for embedded mode + a lock on _LibsqlConn)
backend/tests/unit/test_db_backend.py  (extend: singleton/one-connect, pure-remote distinct, lock entered, reconnect-under-lock)
specs/065-embedded-replica-shared-conn/{spec,plan,tasks}.md
```
**NOT touched:** `app/config.py` (reuses 064's `TURSO_EMBEDDED_REPLICA_ENABLED`/`TURSO_REPLICA_PATH`/
`TURSO_SYNC_INTERVAL_SECONDS`); the stores (`store.py`/`user_store.py`/`password_reset_store.py` keep
`self._conn = db_backend.connect(db_path)` — they transparently receive the shared instance); `main.py`;
migrations; any node/graph/`builder.py`/`ContractState`; API/frontend.

## 1. `db_backend.py` — shared embedded connection + lock
- Add `import threading` and `from contextlib import nullcontext`.
- Module singleton: `_SHARED_EMBEDDED_CONN = None`.
- **`connect(db_path)`** routes the embedded path to the singleton:
  ```python
  def connect(db_path):
      if _config.TURSO_DATABASE_URL:
          if _config.TURSO_EMBEDDED_REPLICA_ENABLED:
              return _shared_embedded_conn()      # feature 065: one owner/one syncer
          return _connect_turso()                 # pure-remote, per-call (unchanged)
      conn = sqlite3.connect(db_path, check_same_thread=False)  # unchanged
      conn.row_factory = sqlite3.Row
      return conn
  ```
- **Singleton factory** (lazy; one `libsql.connect` for the whole process; a lock serializes the shared conn):
  ```python
  def _shared_embedded_conn():
      global _SHARED_EMBEDDED_CONN
      if _SHARED_EMBEDDED_CONN is None:
          _SHARED_EMBEDDED_CONN = _LibsqlConn(
              _turso_raw_connect(), reconnect=_turso_raw_connect, lock=threading.Lock()
          )
      return _SHARED_EMBEDDED_CONN
  ```
  (`_turso_raw_connect` already takes the 064 embedded branch when the flag is on — one `libsql.connect(local,
  sync_url=…, _check_same_thread=False)`; the empty-token guard stays first. The reconnect factory re-opens the
  same embedded mode.)
- **Test reset hook:** `def _reset_shared_for_tests(): global _SHARED_EMBEDDED_CONN; _SHARED_EMBEDDED_CONN =
  None` (tests call it / monkeypatch the global so one test's singleton can't leak — EC-6).
- **`_LibsqlConn` gains a lock** (serialize the shared connection across worker + request threads; `None` ⇒ no
  locking, so pure-remote/local per-call connections are byte-identical):
  ```python
  def __init__(self, raw, reconnect=None, lock=None):
      self._raw = raw
      self._reconnect = reconnect
      self._lock = lock

  def _run(self, op):
      with (self._lock or nullcontext()):   # serialize only when a lock is set (shared embedded conn)
          <existing 063 reconnect/retry loop unchanged>
  ```
  `execute`/`executemany`/`commit` are unchanged (they call `self._run(...)`); the lock now wraps the whole op
  **including** the 063 reconnect/retry, so a heal is serialized and all stores keep the healed `self._raw`
  (EC-1/AC-5). `close()` stays tolerant (064); at shutdown the three stores call `close()` on the same shared
  conn — the first closes the raw, the 2nd/3rd hit an already-closed conn and are **swallowed** by the
  tolerant `close()` (EC-3).

## 2. Tests (TDD — write first, confirm failing, then implement). `db_backend.libsql` mocked; singleton reset per test.
Extend `backend/tests/unit/test_db_backend.py`. Add a fixture (autouse or explicit) that calls
`db_backend._reset_shared_for_tests()` before each new test so the singleton never leaks.
- **AC-1 (one shared connection):** flag on + `TURSO_DATABASE_URL` set; `libsql.connect`=MagicMock → call
  `db_backend.connect("p")` **three times** → all three are the **same** object (`is`) AND
  `db_backend.libsql.connect.call_count == 1` (the one-syncer fix). The `database` arg is the resolved replica
  path and `sync_url`/`_check_same_thread=False` present (AC-6 shape preserved).
- **AC-2 (pure-remote distinct):** flag off + URL set → three `connect()` calls return **distinct**
  `_LibsqlConn` objects and `libsql.connect.call_count == 3` (byte-identical to 063/064).
- **AC-3 (local sqlite):** no `TURSO_DATABASE_URL` → each `connect()` is a new `sqlite3.Connection`, even with
  the replica flag on.
- **AC-4 (lock entered — deterministic, no thread timing):** construct `_LibsqlConn(FakeRawConn(cursor=…),
  reconnect=None, lock=MagicMock())` and call `.execute("SELECT 1")`; assert the injected lock's `__enter__`
  (and `__exit__`) **were called** (i.e. `_run` ran under `with self._lock`). Also assert a `_LibsqlConn` with
  `lock=None` still works (no-op context) — pure-remote unaffected.
- **AC-5 (063 reconnect under lock):** a shared embedded conn (real `threading.Lock`) whose raw `execute` raises
  a `_DROP` once then succeeds (via `libsql.connect` side_effect `[_RaiseConn(_DROP), good]`) → reconnects +
  retries → succeeds; `self._raw` healed.
- **AC-6 (embedded shape + token guard):** the single `libsql.connect` uses the 064 embedded shape; empty token
  + flag on → `ValueError` naming `TURSO_AUTH_TOKEN` (no token echoed).
- Run `python -X utf8 -m pytest -q tests/unit/test_db_backend.py` → CONFIRM FAIL first (no singleton/lock yet:
  AC-1 sees 3 distinct + call_count 3; AC-4 lock not entered).

## 3. Correctness / constitution
- **§2/§10:** DB-connection factory + wrapper only; no node/edge/`ContractState`/migration; `builder.py`
  untouched (AC-7).
- **§3:** no new config — reuses 064's `TURSO_*` flags (the fix is behavioral within the existing flag).
- **No new dependency**; `threading`/`contextlib` stdlib; `libsql` already present.
- **Pure-remote/local byte-identical:** singleton + lock apply ONLY to the embedded path (lock=None elsewhere);
  the flag-off prod (current) is unchanged (AC-2/AC-3, EC-5).
- **063 reuse:** reconnect runs inside the locked `_run`; the shared `self._raw` is swapped on heal (AC-5/EC-1).
- **§7:** tests first; the pure-remote path, `_LibsqlCursor`, and store code are unchanged (no test weakened).

## 4. Verification gate (offline) + rollout
- `python -X utf8 -m pytest -q` → new/extended db_backend tests pass AND the full suite stays green (stores /
  registry / 063 reconnect / 064 embedded-shape / migration tests unchanged). No network (libsql mocked).
- `git diff --name-only main` == the §0 allow-list.
- **Live smoke (AC-8, post-merge):** in Render re-enable `TURSO_EMBEDDED_REPLICA_ENABLED=True` → redeploy →
  confirm the `wal_insert_begin failed` error is GONE, dashboard/report loads are sub-second, and a fresh
  analysis runs (writes durable + visible). Instant revert via the flag if needed.

## 5. Risks / limitations
- **Lock contention:** all store ops serialize on one lock; embedded reads are local sub-ms so negligible; rare
  writes forward to the primary under the lock (EC-2). Acceptable for a single-backend app.
- **Live-only validation of the sync fix:** offline tests prove one `libsql.connect` (one syncer) + lock usage;
  the actual disappearance of `wal_insert_begin failed` + speed is the AC-8 smoke. Fallback = the default-off flag.
- **Shutdown close ordering:** tolerated by `_LibsqlConn.close()` (EC-3).

## 6. Merge
Full backend gate green; diff scope matches §0. Rebase `main`, merge `feature/065-embedded-replica-shared-conn`,
delete branch (`git-finish`). Ships with the flag still off (byte-identical); re-enable
`TURSO_EMBEDDED_REPLICA_ENABLED=True` in Render + run the AC-8 smoke → dashboard/reports fast *and* correct.
