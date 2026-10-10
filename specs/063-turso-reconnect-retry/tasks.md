# Feature 063 — Turso reconnect-and-retry — Implementation Tasks

Reference documents:
- Spec: `specs/063-turso-reconnect-retry/spec.md`
- Plan: `specs/063-turso-reconnect-retry/plan.md`
- Constitution: `specs/000-constitution.md` (**§2** no node/edge/state; **§3** named config; **§7** TDD / never
  weaken a test; **§11** branch workflow)

Backend paths relative to `backend/`.

**Workflow reminders:**
- **Runner DB-backend only.** Changes `app/runner/db_backend.py` (`_LibsqlConn`, Turso path) + one config
  constant. No node/edge/`ContractState`/migration/dependency/API/frontend change. Local `sqlite3` path
  byte-identical.
- **Scope allow-list (AC-8)** = `app/config.py`, `app/runner/db_backend.py`,
  `tests/unit/test_db_backend.py`, the 063 specs. Nothing else (NOT store.py/registry.py — healing is
  transparent through the wrapper).
- **TDD (§7):** write the tests first (mock `db_backend.libsql`), confirm FAIL, implement to green. Retry only
  connection drops; never retry SQL/constraint errors; never weaken a test.
- **Secret safety:** never log `TURSO_AUTH_TOKEN` or SQL `params` (may carry user data).

---

## Task 0: Branch
- [ ] From up-to-date `main` (`git checkout main && git pull`), create `feature/063-turso-reconnect-retry`
  (`git-start`). Commit the APPROVED spec/plan/tasks on the branch.

**Verify:** `git branch --show-current` → `feature/063-turso-reconnect-retry`.

---

## Task 1: `config.py` — retry budget (§3)  [AC-7]
- [ ] Near the other `TURSO_*` constants add:
  `TURSO_RECONNECT_MAX_RETRIES: int = _env_int("TURSO_RECONNECT_MAX_RETRIES", 2)` — reconnect attempts after
  the first failure (≤ 3 total tries); env-overridable.

---

## Task 2: Write the failing tests first  [AC-1..AC-7]  (mock `db_backend.libsql`; no network)
Extend `tests/unit/test_db_backend.py`. Build a fake raw-conn whose `execute` raises a drop-style
`ValueError("Hrana: http error: connection closed before message completed")` a controlled number of times
then returns a fake cursor; patch `db_backend.libsql.connect` to return a fresh fake on reconnect;
`monkeypatch.setattr(db_backend.time, "sleep", lambda *_: None)` (no real backoff).
- [ ] **AC-1:** `execute` raises a drop once then succeeds → returns the cursor; `db_backend.libsql.connect`
  (reconnect) was called once; result correct.
- [ ] **AC-2:** `execute` always raises a drop → after `TURSO_RECONNECT_MAX_RETRIES` reconnects the original
  error propagates; reconnect tried exactly that many times (monkeypatch the constant to e.g. 2).
- [ ] **AC-3:** `execute` raises a NON-drop error (`ValueError("UNIQUE constraint failed")`) → propagates on
  the FIRST attempt; reconnect NOT called.
- [ ] **AC-4:** `executemany` and `commit` reconnect+retry on a drop (same predicate/budget).
- [ ] **AC-5:** `TURSO_DATABASE_URL` unset → `connect()` returns a `sqlite3.Connection`; the existing
  db_backend/store tests still pass (byte-identical local path — add/keep an assertion).
- [ ] **AC-6:** on reconnect, `caplog` contains neither the token value nor the SQL params; also assert the
  `time.sleep` stub was used (guards against a real sleep slowing the suite).
- [ ] **AC-7:** monkeypatching `TURSO_RECONNECT_MAX_RETRIES` changes the retry count (drives AC-2).
- [ ] Run `python -X utf8 -m pytest -q tests/unit/test_db_backend.py` → CONFIRM FAIL (no reconnect/retry yet).

---

## Task 3: `db_backend.py` — reconnect + retry  [AC-1..AC-6]
- [ ] Add `import logging`, `import time`; `logger = logging.getLogger("contractsentinel.runner.db_backend")`.
- [ ] Refactor the Turso connect into a reusable factory and pass it as the reconnect callable:
  ```python
  def _turso_raw_connect():
      if not _config.TURSO_AUTH_TOKEN:
          raise ValueError("TURSO_DATABASE_URL is set but TURSO_AUTH_TOKEN is empty. Set it in backend/.env "
                           "(see docs/DEPLOYMENT.md). The token value is intentionally not shown.")
      return libsql.connect(_config.TURSO_DATABASE_URL, auth_token=_config.TURSO_AUTH_TOKEN)

  def _connect_turso():
      return _LibsqlConn(_turso_raw_connect(), reconnect=_turso_raw_connect)
  ```
- [ ] Add the drop predicate (D2):
  ```python
  _DROP_MARKERS = ("connection closed", "hrana", "stream closed", "error communicating",
                   "connection reset", "broken pipe")
  def _is_connection_drop(exc) -> bool:
      return any(m in str(exc).lower() for m in _DROP_MARKERS)
  ```
- [ ] `_LibsqlConn`: add `reconnect=None` to `__init__`; add the shared `_run(op)` helper (whole-op re-run on a
  fresh `self._raw`; non-drop OR budget-exhaustion → `raise`; reconnect-failure → `continue`; after the loop
  `raise last` — add a one-line comment that `last` is the last op (drop) exception = "connection unavailable"
  per EC-1):
  ```python
  def _run(self, op):
      attempts = _config.TURSO_RECONNECT_MAX_RETRIES
      last = None
      for i in range(attempts + 1):
          try:
              return op(self._raw)
          except Exception as exc:
              if not (self._reconnect and _is_connection_drop(exc) and i < attempts):
                  raise
              last = exc
              logger.warning("reconnecting after a dropped Turso connection (attempt %d/%d)", i + 1, attempts)
              time.sleep(min(2.0 ** i, 8.0))
              try:
                  self._raw = self._reconnect()
              except Exception:
                  continue
      raise last  # last op (drop) exception — connection unavailable after exhausting retries (EC-1)
  ```
- [ ] Wrap the ops:
  - `execute`: `return _LibsqlCursor(self._run(lambda raw: raw.execute(sql, params)))`.
  - `executemany`: `rows = list(seq)` first (re-iterable on retry), then wrap the existing execute-loop (incl.
    the empty-`rows` `SELECT 1 WHERE 1=0` no-op) in `self._run(op)`.
  - `commit`: `self._run(lambda raw: raw.commit())`.
  - `close`: `try: self._raw.close() except Exception: pass` (tolerate an already-dead connection).

**Verify:** Task 2 AC-1..AC-6 tests pass.

---

## Task 4: Backend gate  [AC-1..AC-8]
- [ ] `python -X utf8 -m pytest -q` → new/extended db_backend tests pass AND the full suite stays green
  (store / registry / password-reset / migration tests unchanged). No network (libsql mocked). Fix code, not
  tests, on any surprise (§7).
- [ ] `git diff --name-only main` matches the §0 allow-list (no node/edge/`builder.py`/`ContractState`/
  `specs/001`/migration/dependency/API/frontend change).

---

## Task 5: Merge
- [ ] Gate green; diff scope matches §0. Rebase `main`, merge `feature/063-turso-reconnect-retry`, delete
  branch (`git-finish`). Auto-deploys; prod self-heals on Turso drops (no more "keeps disconnecting" until a
  restart). Embeddings/`EMBED_PROVIDER=cloudflare` remains a separate deploy step (feature 062).

---

*Per §1/§11, implementation happens only on `feature/063-turso-reconnect-retry`, opened after spec + plan +
tasks are all spec-reviewer-APPROVED. Runner DB-backend only; retry only connection drops; local SQLite path
byte-identical; no new dependency.*
