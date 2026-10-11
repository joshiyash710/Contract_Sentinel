# Feature 065 — Shared embedded-replica connection — Implementation Tasks

Reference documents:
- Spec: `specs/065-embedded-replica-shared-conn/spec.md`
- Plan: `specs/065-embedded-replica-shared-conn/plan.md`
- Constitution: `specs/000-constitution.md` (**§2** no node/edge/state; **§7** TDD / never weaken a test;
  **§11** branch workflow)

Backend paths relative to `backend/`.

**Workflow reminders:**
- **Runner DB-backend only.** Changes `app/runner/db_backend.py` (embedded-mode singleton + an optional lock on
  `_LibsqlConn`). No config change (reuses 064's `TURSO_*` flags), no node/edge/`ContractState`/migration/
  dependency/API/frontend change. `threading`/`contextlib` are stdlib.
- **Fixes 064's `wal_insert_begin failed`:** three stores must share ONE embedded-replica connection (one
  syncer). Pure-remote + local SQLite paths stay **byte-identical** (lock only on the shared embedded conn).
- **Scope allow-list (AC-7)** = `app/runner/db_backend.py`, `tests/unit/test_db_backend.py`, the 065 specs.
- **TDD (§7):** write tests first (mock `db_backend.libsql`; reset the singleton per test), confirm FAIL,
  implement to green. Never log `TURSO_AUTH_TOKEN`. Never weaken a test.

---

## Task 0: Branch
- [ ] From up-to-date `main` (`git checkout main && git pull`), create `feature/065-embedded-replica-shared-conn`
  (`git-start`). Commit the APPROVED spec/plan/tasks on the branch.

**Verify:** `git branch --show-current` → `feature/065-embedded-replica-shared-conn`.

---

## Task 1: Write the failing tests first  [AC-1..AC-6]  (mock `db_backend.libsql`; reset singleton per test)
Extend `tests/unit/test_db_backend.py`. Add a fixture that calls `db_backend._reset_shared_for_tests()` before
each new test (so the singleton never leaks — EC-6). Reuse `FakeRawConn`/`FakeRawCursor`/`_RaiseConn`/`_DROP`.
- [ ] **AC-1 (one shared connection in embedded mode):** `_config.TURSO_DATABASE_URL="libsql://x.turso.io"`,
  `TURSO_EMBEDDED_REPLICA_ENABLED=True`, `TURSO_AUTH_TOKEN="tok"`, `TURSO_REPLICA_PATH=str(tmp_path/"r.db")`;
  `libsql.connect`=MagicMock → call `db_backend.connect("p")` **three times** → all three return the **same**
  object (`is`) and `db_backend.libsql.connect.call_count == 1`. Also assert the single call used the 064
  embedded shape (`database`=that path, `sync_url`, `sync_interval`, `_check_same_thread is False`) — AC-6.
- [ ] **AC-2 (pure-remote distinct, byte-identical):** flag off + URL set → three `connect()` calls return
  three **distinct** `_LibsqlConn` objects and `libsql.connect.call_count == 3`.
- [ ] **AC-3 (local sqlite unchanged):** `TURSO_DATABASE_URL=""` + `TURSO_EMBEDDED_REPLICA_ENABLED=True` → each
  `connect()` returns a new `sqlite3.Connection`.
- [ ] **AC-4 (lock entered — deterministic):** `conn = db_backend._LibsqlConn(FakeRawConn(cursor=FakeRawCursor(
  rows=[(1,)])), reconnect=None, lock=MagicMock())`; `conn.execute("SELECT 1")` → assert `conn._lock.__enter__`
  and `conn._lock.__exit__` were called. Also: `_LibsqlConn(FakeRawConn(), lock=None).execute("SELECT 1")`
  works (no-op context) — pure-remote unaffected.
- [ ] **AC-5 (063 reconnect under lock):** shared embedded conn (real `threading.Lock`) via `connect()` with
  `libsql.connect` side_effect `[_RaiseConn(_DROP), good]` + `TURSO_RECONNECT_MAX_RETRIES=2` + stubbed
  `time.sleep` → `conn.execute("SELECT 1")` reconnects + retries → succeeds; `libsql.connect.call_count == 2`.
- [ ] **AC-6 (embedded shape + token guard):** covered in AC-1 for the shape; add: flag on + URL set + empty
  `TURSO_AUTH_TOKEN` → `connect()` raises `ValueError` naming `TURSO_AUTH_TOKEN` (no token echoed).
- [ ] Run `python -X utf8 -m pytest -q tests/unit/test_db_backend.py` → CONFIRM FAIL (no singleton/lock yet:
  AC-1 sees 3 distinct + call_count 3; AC-4 lock not entered).

---

## Task 2: `db_backend.py` — shared singleton + lock  [AC-1..AC-6]
- [ ] Add `import threading` and `from contextlib import nullcontext`.
- [ ] Module global `_SHARED_EMBEDDED_CONN = None` + `def _reset_shared_for_tests(): global
  _SHARED_EMBEDDED_CONN; _SHARED_EMBEDDED_CONN = None`.
- [ ] `_shared_embedded_conn()`: lazily create once —
  `_LibsqlConn(_turso_raw_connect(), reconnect=_turso_raw_connect, lock=threading.Lock())` — and return it.
- [ ] In `connect(db_path)`: when `_config.TURSO_DATABASE_URL` set AND
  `_config.TURSO_EMBEDDED_REPLICA_ENABLED` → `return _shared_embedded_conn()`; else the existing branches
  (`_connect_turso()` for pure-remote; `sqlite3.connect(...)` + `row_factory` for local) **unchanged**.
- [ ] `_LibsqlConn.__init__`: add `lock=None` param → `self._lock = lock`.
- [ ] `_LibsqlConn._run`: wrap the existing 063 retry loop in `with (self._lock or nullcontext()):` (serializes
  only when a lock is set; `None` ⇒ genuine no-op). `execute`/`executemany`/`commit`/`close` otherwise
  unchanged (`close` stays tolerant — EC-3).

**Verify:** Task 1 AC-1..AC-6 tests pass.

---

## Task 3: Backend gate  [AC-1..AC-7]
- [ ] `python -X utf8 -m pytest -q` → new/extended db_backend tests pass AND the full suite stays green
  (stores / registry / 063 reconnect / 064 embedded-shape / migration tests unchanged). No network (libsql
  mocked). Fix code, not tests, on any surprise (§7).
- [ ] `git diff --name-only main` matches the §0 allow-list (only `db_backend.py` + its test + 065 specs).

---

## Task 4: Merge + rollout
- [ ] Gate green; diff scope matches §0. Rebase `main`, merge `feature/065-embedded-replica-shared-conn`,
  delete branch (`git-finish`). Ships with the flag still OFF (byte-identical).
- [ ] **Live smoke (AC-8, after deploy):** in Render re-enable `TURSO_EMBEDDED_REPLICA_ENABLED=True` → redeploy
  → confirm the `wal_insert_begin failed` error is GONE, dashboard/report loads are sub-second, and a fresh
  analysis runs (writes durable + visible). Instant revert via the flag if needed.

---

*Per §1/§11, implementation happens only on `feature/065-embedded-replica-shared-conn`, opened after spec +
plan + tasks are all spec-reviewer-APPROVED. Runner DB-backend only; embedded path gets a shared, lock-
serialized connection; pure-remote/local byte-identical; reuses 064 flags + the 063 reconnect; no new
dependency.*
