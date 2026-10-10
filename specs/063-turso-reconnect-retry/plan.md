# Feature 063 — Technical plan: Turso (libSQL/Hrana) reconnect-and-retry

Branch: `feature/063-turso-reconnect-retry` (per constitution §11).

Derived from the approved `spec.md`. Make `app/runner/db_backend.py::_LibsqlConn` **reconnect and retry** on a
dropped-connection (Hrana) error, so a transient Turso drop self-heals instead of leaving the shared
connection dead until a restart. **Runner DB-backend + one config constant only. No node/edge/`ContractState`/
migration/dependency/API/frontend change.** Local SQLite path byte-identical.

## 0. Scope of change (files touched)
```
backend/app/config.py                 (TURSO_RECONNECT_MAX_RETRIES)
backend/app/runner/db_backend.py      (reconnect factory + drop predicate + retry-wrapped execute/executemany/commit; tolerant close)
backend/tests/unit/test_db_backend.py (extend: reconnect+retry, budget, non-drop-not-retried, sqlite unchanged, token/params not logged)
specs/063-turso-reconnect-retry/{spec,plan,tasks}.md
```
**NOT touched:** any LangGraph node/graph/`builder.py`; `specs/001`/`ContractState`; Alembic migrations;
`store.py`/`registry.py`/the stores (they call the wrapper unchanged — healing is transparent); API/routes;
frontend; `pyproject.toml` (libsql already a dep).

## 1. `config.py` (§3)
- `TURSO_RECONNECT_MAX_RETRIES: int = _env_int("TURSO_RECONNECT_MAX_RETRIES", 2)` — reconnect attempts after
  the first failure (≤ 3 total tries). Place near the other `TURSO_*` constants; env-overridable.

## 2. `db_backend.py` — reconnect + retry
- Add `import logging` + `import time`; `logger = logging.getLogger("contractsentinel.runner.db_backend")`.
- **Reconnect factory:** refactor `_connect_turso` so the raw-connect is a reusable zero-arg helper and pass it
  to the wrapper:
  ```python
  def _turso_raw_connect():
      if not _config.TURSO_AUTH_TOKEN:
          raise ValueError("TURSO_DATABASE_URL is set but TURSO_AUTH_TOKEN is empty. Set it in backend/.env "
                           "(see docs/DEPLOYMENT.md). The token value is intentionally not shown.")
      return libsql.connect(_config.TURSO_DATABASE_URL, auth_token=_config.TURSO_AUTH_TOKEN)

  def _connect_turso():
      return _LibsqlConn(_turso_raw_connect(), reconnect=_turso_raw_connect)
  ```
  (Keeps the existing empty-token guard; `libsql.connect` stays patchable via `db_backend.libsql`.)
- **Drop predicate** (D2 — message signature; libSQL raises plain `ValueError`s):
  ```python
  _DROP_MARKERS = ("connection closed", "hrana", "stream closed", "error communicating",
                   "connection reset", "broken pipe")
  def _is_connection_drop(exc) -> bool:
      return any(m in str(exc).lower() for m in _DROP_MARKERS)
  ```
- **`_LibsqlConn`** gains `reconnect=None` and a shared retry runner:
  ```python
  def __init__(self, raw, reconnect=None):
      self._raw = raw
      self._reconnect = reconnect

  def _run(self, op):   # op: callable(raw) -> result; whole op re-run on a fresh raw after a drop
      attempts = _config.TURSO_RECONNECT_MAX_RETRIES
      last = None
      for i in range(attempts + 1):
          try:
              return op(self._raw)
          except Exception as exc:
              if not (self._reconnect and _is_connection_drop(exc) and i < attempts):
                  raise                      # non-drop OR budget exhausted → propagate (AC-2/AC-3)
              last = exc
              logger.warning("reconnecting after a dropped Turso connection (attempt %d/%d)", i + 1, attempts)
              time.sleep(min(2.0 ** i, 8.0))
              try:
                  self._raw = self._reconnect()
              except Exception:
                  continue                   # reconnect failed → next attempt / exhaust (EC-1)
      raise last
  ```
  - `execute`: `return _LibsqlCursor(self._run(lambda raw: raw.execute(sql, params)))`.
  - `executemany`: **materialize** the seq first so a retry can re-iterate — `rows = list(seq)` — then wrap the
    existing execute-loop (incl. the empty-`rows` `SELECT 1 WHERE 1=0` no-op) in `self._run(op)`.
  - `commit`: `self._run(lambda raw: raw.commit())`.
  - `close`: tolerate an already-dead connection — `try: self._raw.close() except Exception: pass` (reviewer
    note; a close on a dropped conn must never raise).
- **Logging discipline (AC-6):** the warning names only the reconnect + attempt count — **never** the token or
  the SQL/`params` (params may carry user data).

## 3. Tests (TDD — write first, confirm failing, then implement). `db_backend.libsql` mocked; no network.
Extend `backend/tests/unit/test_db_backend.py`. A fake raw-conn whose `execute` raises a drop-style
`ValueError("Hrana: ... connection closed before message completed")` N times then returns a fake cursor;
patch `db_backend.libsql.connect` to hand back a fresh fake on reconnect; `monkeypatch` `db_backend.time.sleep`
to a no-op.
- **AC-1:** execute raises a drop once then succeeds → returns the cursor; `libsql.connect` (reconnect) called
  once; result correct.
- **AC-2:** execute always raises a drop → after `TURSO_RECONNECT_MAX_RETRIES` reconnects the original error
  propagates; reconnect tried exactly that many times (monkeypatch the constant to a small number).
- **AC-3:** execute raises a NON-drop error (e.g. `ValueError("UNIQUE constraint failed")`) → propagates on the
  first attempt; reconnect NOT called.
- **AC-4:** `executemany` and `commit` reconnect+retry on a drop (same predicate/budget).
- **AC-5:** `TURSO_DATABASE_URL` unset → `connect()` returns a `sqlite3.Connection`; existing db_backend/store
  tests pass unchanged (byte-identical local path).
- **AC-6:** on reconnect, captured logs contain neither the token value nor the SQL params (assert with caplog).
- **AC-7:** monkeypatch `TURSO_RECONNECT_MAX_RETRIES` changes the retry count (drives AC-2).
- Run `python -X utf8 -m pytest -q tests/unit/test_db_backend.py` → CONFIRM FAIL first (no retry/reconnect yet).

## 4. Correctness / constitution
- **§2/§10:** no node/edge/`ContractState`/migration — runner DB wrapper + one config constant; `builder.py`
  untouched (AC-8).
- **§3:** `TURSO_RECONNECT_MAX_RETRIES` named + env-overridable; retry bounded.
- **§7:** tests written first; the stores/`_LibsqlCursor` surface is unchanged (rowcount read from the final
  successful cursor → `mark_used` single-use preserved, EC-6).
- **No new dependency**; `libsql` already present (051). Local `sqlite3` path unchanged (AC-5).
- Retry only connection drops (D2) — SQL/constraint errors propagate; the only writes through this path are
  idempotent `upsert` + the guarded single-row UPDATE, so a retried idempotent op is safe (EC-2/EC-5/EC-6).

## 5. Verification gate (offline)
- `python -X utf8 -m pytest -q` → new/extended db_backend tests pass AND the full suite stays green (store /
  registry / password-reset / migration tests unchanged). No network (libsql mocked).
- `git diff --name-only main` == the §0 allow-list (no node/edge/`ContractState`/migration/dependency/API/
  frontend change).

## 6. Risks / limitations
- **Render cold-start latency** is NOT addressed (platform; out of scope, spec §5) — this fixes the
  connection-drop failures/slowness, not the ~1-min free-tier spin-up.
- **Persistent Turso outage:** budget exhausts → fails as today, but self-heals on the next op once Turso
  recovers (reconnect).
- **Message-signature detection** is heuristic; the conservative allow-list + idempotent-only writes through
  this path bound the risk (a mis-retried idempotent op is harmless, EC-5).
- **`commit()`-side drop:** fails closed for `mark_used` (token not consumed, reset retryable) — EC-6.

## 7. Merge
Full backend gate green; diff scope matches §0. Rebase `main`, merge `feature/063-turso-reconnect-retry`,
delete branch (`git-finish`). Deploys via the existing auto-deploy; prod stops crash-feeling on Turso drops
(self-heals). Embeddings/`EMBED_PROVIDER=cloudflare` remains a separate deploy step (feature 062).
