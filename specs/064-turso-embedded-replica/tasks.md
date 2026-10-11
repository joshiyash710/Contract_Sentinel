# Feature 064 — Turso embedded replica — Implementation Tasks

Reference documents:
- Spec: `specs/064-turso-embedded-replica/spec.md`
- Plan: `specs/064-turso-embedded-replica/plan.md`
- Constitution: `specs/000-constitution.md` (**§2** no node/edge/state; **§3** named config; **§7** TDD / never
  weaken a test; **§11** branch workflow)

Backend paths relative to `backend/`.

**Workflow reminders:**
- **Runner DB-backend + config only.** Changes `app/runner/db_backend.py` (`_turso_raw_connect` branch) + three
  config constants. No node/edge/`ContractState`/migration/dependency/API/frontend change. Reuses the 063
  `_LibsqlConn`/reconnect wrapper (unchanged).
- **Flag default off ⇒ byte-identical** pure-remote (today). Embedded replica only engages when
  `TURSO_EMBEDDED_REPLICA_ENABLED=True` AND `TURSO_DATABASE_URL` is set.
- **Scope allow-list (AC-7)** = `app/config.py`, `app/runner/db_backend.py`, `tests/unit/test_db_backend.py`,
  the 064 specs. Nothing else.
- **TDD (§7):** write the tests first (mock `db_backend.libsql`), confirm FAIL, implement to green. Never
  weaken a test. Never log `TURSO_AUTH_TOKEN`.
- **Latency/concurrency are confirmed by a live smoke (AC-8), not offline** — offline tests assert the
  `libsql.connect` call shape.

---

## Task 0: Branch
- [ ] From up-to-date `main` (`git checkout main && git pull`), create `feature/064-turso-embedded-replica`
  (`git-start`). Commit the APPROVED spec/plan/tasks on the branch.

**Verify:** `git branch --show-current` → `feature/064-turso-embedded-replica`.

---

## Task 1: `config.py` — three constants (§3)  [AC-1..AC-4, AC-7]
- [ ] Near the other `TURSO_*` constants add:
  - `TURSO_EMBEDDED_REPLICA_ENABLED: bool = _env_bool("TURSO_EMBEDDED_REPLICA_ENABLED", False)`
  - `TURSO_REPLICA_PATH: str = "data/turso_replica.db"`  (backend-relative; on the /app/data volume)
  - `TURSO_SYNC_INTERVAL_SECONDS: int = _env_int("TURSO_SYNC_INTERVAL_SECONDS", 60)`  (0 ⇒ no periodic sync)

---

## Task 2: Write the failing tests first  [AC-1..AC-7]  (mock `db_backend.libsql`; no real sync)
Extend `tests/unit/test_db_backend.py`. Monkeypatch `db_backend._config` fields; mock
`db_backend.libsql.connect` (a MagicMock) and inspect its `call_args`.
- [ ] **AC-1 (embedded connect shape):** `_config.TURSO_DATABASE_URL="libsql://x.turso.io"`,
  `TURSO_EMBEDDED_REPLICA_ENABLED=True`, `TURSO_AUTH_TOKEN="tok"`, `TURSO_SYNC_INTERVAL_SECONDS=60`,
  `TURSO_REPLICA_PATH=str(tmp_path/"replica.db")` (absolute) → `connect("ignored")` calls `libsql.connect` with
  `database == str(tmp_path/"replica.db")`, `sync_url == "libsql://x.turso.io"`, `auth_token == "tok"`,
  `sync_interval == 60`, `_check_same_thread is False`; returns a `_LibsqlConn`. Assert `(tmp_path).exists()`
  (parent dir ensured **before** the connect call).
- [ ] **AC-2 (flag off → pure-remote, byte-identical):** flag off → `libsql.connect` called with
  `("libsql://x.turso.io",)` + `auth_token="tok"` and **no** `sync_url`/`sync_interval` kwargs. (Existing
  `test_connect_turso_returns_wrapper` already covers the pure-remote shape — keep it green.)
- [ ] **AC-3 (local dev unchanged):** `TURSO_DATABASE_URL=""` → `connect()` returns `sqlite3.Connection` even
  with `TURSO_EMBEDDED_REPLICA_ENABLED=True`.
- [ ] **AC-4 (path resolved + dir ensured):** the `database` arg equals the resolved `TURSO_REPLICA_PATH` and
  its parent dir exists after `connect()`.
- [ ] **AC-5 (empty-token guard):** flag on + URL set + `TURSO_AUTH_TOKEN=""` → `ValueError` naming
  `TURSO_AUTH_TOKEN`, no token echoed.
- [ ] **AC-6 (063 reconnect still applies in embedded mode):** build a `_LibsqlConn` via `connect()` in
  embedded mode where `libsql.connect` side-effects `[<_RaiseConn drop>, <good conn>]`; a drop on `execute`
  reconnects (second `libsql.connect` call) + retries → succeeds. (Confirms the reconnect factory re-opens
  embedded mode and 063 behavior holds.)
- [ ] **AC-7 (sync_interval=0 → None):** `TURSO_SYNC_INTERVAL_SECONDS=0` → `libsql.connect` called with
  `sync_interval=None`.
- [ ] Run `python -X utf8 -m pytest -q tests/unit/test_db_backend.py` → CONFIRM FAIL (no embedded branch yet).

---

## Task 3: `db_backend.py` — embedded-replica branch  [AC-1..AC-7]
- [ ] Add `from pathlib import Path`.
- [ ] Add `_resolve_replica_path()` returning `str(Path(_config.__file__).resolve().parent.parent /
  _config.TURSO_REPLICA_PATH)` (backend anchor; an absolute `TURSO_REPLICA_PATH` passes through).
- [ ] In `_turso_raw_connect()` (keep the empty-token guard first), branch on
  `_config.TURSO_EMBEDDED_REPLICA_ENABLED`:
  - **enabled:** `path = _resolve_replica_path()`; `Path(path).parent.mkdir(parents=True, exist_ok=True)`
    (BEFORE connect); `interval = _config.TURSO_SYNC_INTERVAL_SECONDS or None`;
    `logger.info("store DB: embedded-replica mode (path=%s, sync_interval=%s)", path, interval)` (NO token);
    `return libsql.connect(path, sync_url=_config.TURSO_DATABASE_URL, auth_token=_config.TURSO_AUTH_TOKEN,
    sync_interval=interval, _check_same_thread=False)`.
  - **disabled:** `return libsql.connect(_config.TURSO_DATABASE_URL, auth_token=_config.TURSO_AUTH_TOKEN)`
    (unchanged — byte-identical to today).
- [ ] `_connect_turso` / `_LibsqlConn` / `_LibsqlCursor` are otherwise untouched (reconnect factory already
  points at `_turso_raw_connect`, so it re-opens the same mode).

**Verify:** Task 2 AC-1..AC-7 tests pass.

---

## Task 4: Backend gate  [AC-1..AC-7]
- [ ] `python -X utf8 -m pytest -q` → new/extended db_backend tests pass AND the full suite stays green
  (stores / registry / 063 reconnect / migration tests unchanged). No network/sync (libsql mocked). Fix code,
  not tests, on any surprise (§7).
- [ ] `git diff --name-only main` matches the §0 allow-list (no node/edge/`builder.py`/`ContractState`/
  `specs/001`/migration/dependency/API/frontend change).

---

## Task 5: Merge + rollout
- [ ] Gate green; diff scope matches §0. Rebase `main`, merge `feature/064-turso-embedded-replica`, delete
  branch (`git-finish`). Ships default-off (byte-identical).
- [ ] **Live smoke (AC-8, after deploy):** in Render set `TURSO_EMBEDDED_REPLICA_ENABLED=True` → redeploy →
  confirm dashboard/report loads are sub-second and a fresh analysis runs (writes durable to the India primary,
  visible on next read). If any concurrency issue appears, unset the flag (instant revert to pure-remote; no
  data risk — primary is the source of truth).

---

*Per §1/§11, implementation happens only on `feature/064-turso-embedded-replica`, opened after spec + plan +
tasks are all spec-reviewer-APPROVED. Runner DB-backend + config only; flag default off ⇒ pure-remote
byte-identical; reuses the 063 reconnect wrapper; no new dependency.*
