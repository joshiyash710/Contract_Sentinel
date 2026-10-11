# Feature 064 — Technical plan: Turso embedded replica

Branch: `feature/064-turso-embedded-replica` (per constitution §11).

Derived from the approved `spec.md`. Open the store DB as a libSQL **embedded replica** (local synced SQLite
file) when `TURSO_EMBEDDED_REPLICA_ENABLED` — reads served locally (instant), writes forwarded to the India
primary (durable) — to fix the Oregon-backend ↔ Mumbai-primary cross-region latency that Free-tier
co-location can't solve. **Runner DB-backend + config only. Flag default off ⇒ today's pure-remote behavior
byte-identical. No node/edge/`ContractState`/migration/dependency/API/frontend change.**

## 0. Scope of change (files touched)
```
backend/app/config.py                 (TURSO_EMBEDDED_REPLICA_ENABLED, TURSO_REPLICA_PATH, TURSO_SYNC_INTERVAL_SECONDS)
backend/app/runner/db_backend.py      (_turso_raw_connect branches: embedded-replica vs pure-remote)
backend/tests/unit/test_db_backend.py (extend: embedded-replica connect shape, flag-off pure-remote, path+dir, token guard, 063 reconnect still applies)
specs/064-turso-embedded-replica/{spec,plan,tasks}.md
```
**NOT touched:** stores/registry (they use `_LibsqlConn` unchanged); `app/runner/migrations.py` (still migrates
the remote primary); any node/graph/`builder.py`/`ContractState`/Alembic migration/API/frontend;
`pyproject.toml` (libsql≥0.1.11 already declared — embedded replica is a built-in mode).

## 1. `config.py` (§3) — three constants near the other `TURSO_*`
- `TURSO_EMBEDDED_REPLICA_ENABLED: bool = _env_bool("TURSO_EMBEDDED_REPLICA_ENABLED", False)` — master flag;
  only meaningful when `TURSO_DATABASE_URL` is set. Off ⇒ pure-remote (today).
- `TURSO_REPLICA_PATH: str = "data/turso_replica.db"` — local replica file (backend-relative; lives on the
  `/app/data` volume; re-bootstrapped on Render's ephemeral disk each boot).
- `TURSO_SYNC_INTERVAL_SECONDS: int = _env_int("TURSO_SYNC_INTERVAL_SECONDS", 60)` — background auto-sync
  cadence; `0` ⇒ no periodic sync (bootstrap-on-connect only) — passed to the client as `None` (see §2).

## 2. `db_backend.py` — open an embedded replica when enabled
Refactor `_turso_raw_connect()` (the feature-063 reconnect factory) to branch on the flag; keep the empty-token
guard and everything downstream (`_connect_turso` still returns `_LibsqlConn(raw, reconnect=_turso_raw_connect)`
so the 063 reconnect/retry applies and the reconnect re-opens the SAME mode):
```python
from pathlib import Path   # add

def _resolve_replica_path() -> str:
    # backend-relative anchor (…/backend), like kb_retriever._resolve_backend_path; absolute path passes through.
    base = Path(_config.__file__).resolve().parent.parent
    return str(base / _config.TURSO_REPLICA_PATH)

def _turso_raw_connect():
    if not _config.TURSO_AUTH_TOKEN:
        raise ValueError(
            "TURSO_DATABASE_URL is set but TURSO_AUTH_TOKEN is empty. Set it in backend/.env "
            "(see docs/DEPLOYMENT.md). The token value is intentionally not shown."
        )
    if _config.TURSO_EMBEDDED_REPLICA_ENABLED:
        path = _resolve_replica_path()
        Path(path).parent.mkdir(parents=True, exist_ok=True)   # ensure dir BEFORE connect (reviewer note 1)
        interval = _config.TURSO_SYNC_INTERVAL_SECONDS or None  # 0 → None, never a literal 0 (reviewer note 2)
        logger.info("store DB: embedded-replica mode (path=%s, sync_interval=%s)", path, interval)  # no token
        return libsql.connect(
            path,
            sync_url=_config.TURSO_DATABASE_URL,
            auth_token=_config.TURSO_AUTH_TOKEN,
            sync_interval=interval,
            _check_same_thread=False,   # shared across worker + request threads (matches current model)
        )
    return libsql.connect(_config.TURSO_DATABASE_URL, auth_token=_config.TURSO_AUTH_TOKEN)  # pure-remote (today)
```
- `connect()` / `_connect_turso()` / `_LibsqlConn` / `_LibsqlCursor` are otherwise unchanged. The pure-remote
  branch is byte-identical to today (AC-2). The embedded branch's `database` is the LOCAL file; `sync_url` is
  the remote primary.
- `_check_same_thread=False`: the store connection is shared across the worker + request threads today; the
  embedded replica also runs a background sync thread (client-managed via `sync_interval`).

## 3. Tests (TDD — write first, confirm failing, then implement). `db_backend.libsql` mocked; no real sync.
Extend `backend/tests/unit/test_db_backend.py`. Monkeypatch `db_backend._config` fields + mock
`db_backend.libsql.connect` (capture call args).
- **AC-1 (embedded connect shape):** `TURSO_DATABASE_URL` set + `TURSO_EMBEDDED_REPLICA_ENABLED=True` +
  `TURSO_REPLICA_PATH` = an absolute `tmp_path/replica.db` + `TURSO_AUTH_TOKEN="tok"` + a sync interval →
  `connect()` calls `libsql.connect` with `database == <that path>`, `sync_url == TURSO_DATABASE_URL`,
  `auth_token == "tok"`, `sync_interval == <interval>`, `_check_same_thread == False`; returns `_LibsqlConn`.
  Also assert the parent dir exists **(created before the connect call — reviewer note 1)**.
- **AC-2 (flag off → pure-remote, byte-identical):** flag off → `libsql.connect(TURSO_DATABASE_URL,
  auth_token="tok")` with **no** `sync_url`/`sync_interval` kwargs; existing db_backend/store tests unchanged.
- **AC-3 (local dev unchanged):** `TURSO_DATABASE_URL` unset → `sqlite3.Connection` regardless of the replica
  flag (covered by the existing `test_connect_default_returns_sqlite`; add an assertion with the flag ON too).
- **AC-4 (path resolved + dir ensured):** the `database` arg equals the resolved `TURSO_REPLICA_PATH` and its
  parent dir exists after `connect()`.
- **AC-5 (empty-token guard):** flag on + URL set + empty token → `ValueError` naming `TURSO_AUTH_TOKEN`, no
  token echoed (same as 051/063).
- **AC-6 (063 reconnect still applies):** the embedded-mode `_LibsqlConn` has a reconnect factory; a dropped
  connection reconnects+retries (the existing 063 reconnect tests stay green; add one asserting the reconnect
  path re-invokes `_turso_raw_connect`, which in embedded mode re-opens with `sync_url`).
- **AC-7 (sync_interval=0 → None):** with `TURSO_SYNC_INTERVAL_SECONDS=0`, `libsql.connect` is called with
  `sync_interval=None` (reviewer note 2).
- Run `python -X utf8 -m pytest -q tests/unit/test_db_backend.py` → CONFIRM FAIL first (no embedded branch yet).

## 4. Correctness / constitution
- **§2/§10:** no node/edge/`ContractState`/migration — DB-connection factory + config only; `builder.py`
  untouched (AC-7/§0).
- **§3:** three named, env-overridable constants; flag default off ⇒ reversible/byte-identical (AC-2/AC-3).
- **No new dependency**; `libsql≥0.1.11` already declared, embedded replica is a built-in mode.
- **Migrations remote-first (D4/EC-2):** the entrypoint's `alembic upgrade head` runs against the remote
  primary before the app opens the replica; the replica bootstraps the migrated schema. Unchanged.
- **063 reuse:** embedded connection wrapped by `_LibsqlConn`; reconnect factory re-opens embedded mode.
- **§7:** tests first; the pure-remote path and `_LibsqlConn`/`_LibsqlCursor` surface are unchanged (no test
  weakened).

## 5. Verification gate (offline) + rollout
- `python -X utf8 -m pytest -q` → new/extended db_backend tests pass AND the full suite stays green (stores /
  registry / 063 reconnect / migration tests unchanged). No real network/sync (libsql mocked).
- `git diff --name-only main` == the §0 allow-list.
- **Live smoke (AC-8, post-merge):** in Render set `TURSO_EMBEDDED_REPLICA_ENABLED=True` → redeploy → confirm
  dashboard/report loads drop to sub-second and a fresh analysis runs (writes durable to the primary, visible
  on next read). If any concurrency issue appears, unset the flag (instant revert to pure-remote; primary is
  the source of truth — no data risk).

## 6. Risks / limitations
- **Live-only validation of latency/concurrency:** embedded replicas need a real remote to sync, so offline
  tests assert the connect shape; the actual speedup + thread-safety are confirmed by the AC-8 smoke. Fallback
  is the default-off flag.
- **Cold-boot bootstrap (EC-1):** first connect after a Render redeploy syncs the (small) DB; the keep-alive
  cron limits restart frequency.
- **Stale out-of-band reads:** bounded by `TURSO_SYNC_INTERVAL_SECONDS`; single-backend read-your-writes covers
  own-write freshness (EC-3).

## 7. Merge
Full backend gate green; diff scope matches §0. Rebase `main`, merge `feature/064-turso-embedded-replica`,
delete branch (`git-finish`). Ships default-off (byte-identical). Enable in Render with
`TURSO_EMBEDDED_REPLICA_ENABLED=True` + run the AC-8 live smoke → dashboard/reports become instant.
