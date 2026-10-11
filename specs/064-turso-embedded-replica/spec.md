# Feature 064 — Spec: Turso embedded replica (local-synced reads for low latency)

Status: DRAFT (pre spec-reviewer gate)
Branch: `feature/064-turso-embedded-replica` (constitution §11).

> Production latency fix. The Turso primary is in `aws-ap-south-1` (Mumbai) but the Render backend runs in
> Oregon (US-West); every query is a cross-continent HTTP round-trip (~250 ms), so dashboard/report loads are
> multi-second and time out. The Free tier cannot co-locate (databases only live in the default India group).
> This feature opens the store DB as a **libSQL embedded replica**: a local synced SQLite file on the Render
> box serves **reads locally (instant)** while **writes forward to the India primary** (durable). **Runner
> DB-backend only; flag-gated, default off (today's pure-remote behavior).**

## 1. Problem statement

`db_backend.connect()` (feature 051), when `TURSO_DATABASE_URL` is set, opens a **pure-remote** libSQL
connection: `libsql.connect(TURSO_DATABASE_URL, auth_token=…)`. Every `execute` is an HTTP round-trip to the
primary. With the primary in Mumbai and the backend in Oregon, each round-trip is ~250 ms; a dashboard/report
page issues several queries + report-BLOB reads → multi-second loads and timeouts (the observed
"crashing"/slowness). Co-location is the ideal fix but the **Turso Free tier only allows databases in the
default group** (India) — it won't place a DB in an Oregon group — so the primary can't be moved to Oregon
without a paid plan.

libSQL's **embedded replica** solves this without moving the primary or changing DB engines: the client keeps
a **local SQLite file** that it bootstraps and syncs from the remote primary. Reads are served from the local
file (no network → instant); writes are forwarded to the primary and applied locally (read-your-writes), so a
single-backend app sees its own writes immediately. The installed `libsql` client supports it — verified:
`connect(database, …, sync_url=None, sync_interval=None, auth_token='', _check_same_thread=True, …)` plus a
`Connection.sync()` method.

This feature makes the Turso path open an embedded replica (local file + `sync_url`) **when enabled**, keeping
the exact `_LibsqlConn` surface (so the stores + the feature-063 reconnect/retry are unchanged), and leaving
the pure-remote path as the default.

### Position relative to the constitution
- **No LangGraph node/edge/`ContractState` change (§2).** Only `db_backend.connect` / `_connect_turso` (the
  runner DB-connection factory) + config. No pipeline, API, schema, or migration change.
- **No Alembic migration change.** Migrations still run against the **remote** primary (feature 051,
  `app/runner/migrations.py` / the entrypoint) BEFORE the app opens the replica, so the replica bootstraps an
  already-migrated schema.
- **§3 configurable, reversible, default off.** New named constants gate it; `TURSO_EMBEDDED_REPLICA_ENABLED`
  default `False` ⇒ byte-identical to today (pure-remote). `TURSO_AUTH_TOKEN` is **never logged**.
- **No new dependency.** `libsql` is already the connection dep (feature 051, `002-tech-stack`); embedded
  replicas are a built-in mode of that same client.
- **Reuses feature 063.** The embedded-replica connection is still wrapped by `_LibsqlConn`; the 063
  reconnect-and-retry (and its reconnect factory) continue to apply (the factory re-opens the replica).

## 2. Inputs and outputs

### New config (§3) — `app/config.py`
- `TURSO_EMBEDDED_REPLICA_ENABLED: bool = _env_bool("TURSO_EMBEDDED_REPLICA_ENABLED", False)` — master flag.
  Only meaningful when `TURSO_DATABASE_URL` is set. Off ⇒ pure-remote (today).
- `TURSO_REPLICA_PATH: str = "data/turso_replica.db"` — local embedded-replica file, resolved under the
  backend/ working dir (same anchor as other `data/` paths); lives on the mounted `/app/data` volume. On
  Render's ephemeral disk it is simply re-bootstrapped on boot.
- `TURSO_SYNC_INTERVAL_SECONDS: int = _env_int("TURSO_SYNC_INTERVAL_SECONDS", 60)` — background auto-sync
  cadence for pulling remote changes (single-backend ⇒ local writes already visible; this bounds staleness of
  any out-of-band change). `0`/unset-equivalent ⇒ no periodic sync (bootstrap-on-connect only).

### `db_backend.py` — open an embedded replica when enabled
- `_turso_raw_connect()` (the 063 factory) branches on the flag:
  - **enabled:** `libsql.connect(_resolve(TURSO_REPLICA_PATH), sync_url=TURSO_DATABASE_URL,
    auth_token=TURSO_AUTH_TOKEN, sync_interval=TURSO_SYNC_INTERVAL_SECONDS or None, _check_same_thread=False)`
    — `database` is the LOCAL file, `sync_url` is the remote primary. `_check_same_thread=False` because the
    store connection is shared across the worker + request threads (matching the current shared-connection
    model). The empty-token guard (051/063) is preserved.
  - **disabled:** today's `libsql.connect(TURSO_DATABASE_URL, auth_token=TURSO_AUTH_TOKEN)` (byte-identical).
- The replica file's parent dir is created if missing (`data/` already exists as the volume mount).
- Everything downstream is unchanged: `_connect_turso` still returns `_LibsqlConn(raw, reconnect=…)`; reads
  hit the local replica, writes forward to the primary, `_LibsqlCursor`/row shims unchanged.

### Behavioral effect (flag on, prod)
- **Reads** (`SELECT` for dashboard/jobs/reports/report-BLOBs) are served from the local file → instant, no
  cross-region round-trip.
- **Writes** (`upsert`/progress/user/reset) forward to the India primary → durable; applied locally so
  subsequent reads on this backend see them (read-your-writes).
- **Boot:** the first `connect` bootstraps the local file from the (already-migrated) remote; thereafter
  `sync_interval` pulls any remote changes. On a Render redeploy (ephemeral disk) the file is re-bootstrapped.

### Resolved decisions (inline)
- **D1 — Embedded replica, not co-location/engine-switch.** Free tier blocks an Oregon primary; Postgres would
  be a full rewrite with the same network-latency class. Embedded replica gives local reads with no migration.
- **D2 — Flag-gated, default off.** Pure-remote stays the default (local dev uses SQLite anyway; the replica
  only matters on the Turso deploy). Reversible by unsetting the flag.
- **D3 — Reuse `_LibsqlConn` + 063.** The replica is still a libSQL connection behind the same wrapper; the
  063 reconnect/retry and the stores are untouched.
- **D4 — Migrations stay remote-first.** `alembic upgrade head` runs against the remote primary (unchanged);
  the replica bootstraps the migrated schema at connect time.

## 3. Acceptance criteria

Backend, offline (pytest; `db_backend.libsql.connect` is already patchable). Embedded replicas need a real
remote to actually sync, so the OFFLINE tests assert the connection is **opened in the right mode** (the
`libsql.connect` call shape) and that the flag/paths/guards behave; the real low-latency behavior is an
operational live smoke (AC-8).

- **AC-1 (enabled → embedded-replica connect shape):** with `TURSO_DATABASE_URL` set and
  `TURSO_EMBEDDED_REPLICA_ENABLED=True`, `db_backend.connect()` calls `libsql.connect` with the **local replica
  path** as `database`, `sync_url=TURSO_DATABASE_URL`, `auth_token=<token>`, a `sync_interval` from config, and
  `_check_same_thread=False`; it returns a `_LibsqlConn`.
- **AC-2 (disabled → pure-remote, byte-identical):** with the flag off (default), `connect()` calls
  `libsql.connect(TURSO_DATABASE_URL, auth_token=…)` with **no** `sync_url` (today's behavior); existing
  db_backend/store tests pass unchanged.
- **AC-3 (local dev unchanged):** with `TURSO_DATABASE_URL` unset, `connect()` returns a `sqlite3.Connection`
  regardless of the replica flag (byte-identical local path).
- **AC-4 (replica path resolved + dir ensured):** the `database` passed to `libsql.connect` is the configured
  `TURSO_REPLICA_PATH` resolved under backend/; its parent directory exists after `connect()` (created if
  needed).
- **AC-5 (empty-token guard preserved):** `TURSO_EMBEDDED_REPLICA_ENABLED=True` + `TURSO_DATABASE_URL` set +
  empty `TURSO_AUTH_TOKEN` → the clear fail-fast `ValueError` (no token echoed), same as 051/063.
- **AC-6 (063 reconnect still applies):** the embedded-replica connection is wrapped by `_LibsqlConn` with a
  reconnect factory that also opens embedded-replica mode; a dropped-connection error still triggers
  reconnect+retry (the 063 tests remain green; the reconnect re-opens with `sync_url`).
- **AC-7 (no architecture change):** `git diff main` touches only `app/config.py`, `app/runner/db_backend.py`,
  the db_backend tests, and the 064 specs. No node/edge/`ContractState`/migration/dependency/API/frontend
  change. Full backend suite green.
- **AC-8 (live smoke — operational, not a unit test):** with the flag on in Render (Turso URL/token set),
  dashboard and report pages load in well under a second (vs multi-second before), and a fresh analysis runs
  end-to-end (writes forward to the primary; subsequent reads reflect them). Verified on the deploy; recorded
  informally.

## 4. Edge cases
- **EC-1 — Ephemeral disk / cold boot:** the replica file is absent on a fresh Render boot → the first
  `connect` bootstraps it from the remote (one-time sync of a small DB, a few MB). Acceptable; subsequent reads
  are local. The keep-alive cron limits how often this happens.
- **EC-2 — Migrations vs replica:** the entrypoint runs `alembic upgrade head` on the **remote** primary
  before the app opens the replica, so the bootstrap pulls the migrated schema (D4). The replica is never the
  migration target.
- **EC-3 — Write-then-read consistency:** single backend → writes forward to the primary and apply locally
  (read-your-writes), so a just-submitted job/updated status is visible to this backend's next read without
  waiting for `sync_interval`.
- **EC-4 — Sync failure / primary unreachable:** a failed background sync leaves the last-good local data for
  reads (stale-but-serving) and surfaces on the next write/sync; combined with 063, a dropped sync/connection
  reconnects. The app degrades to stale reads rather than hard-failing.
- **EC-5 — Concurrency (shared connection across threads):** `_check_same_thread=False` matches the current
  shared-connection model (worker + request threads use the one `_LibsqlConn`); the embedded replica adds a
  background sync thread (via `sync_interval`) managed by the client. If a concurrency problem surfaces in the
  live smoke (AC-8), the fallback is unsetting the flag (pure-remote) while it's addressed — no data risk
  (primary is the source of truth).
- **EC-6 — Replica file corruption:** delete the file (or redeploy) → re-bootstrap from the remote. No primary
  data loss (replica is a cache of the durable primary).
- **EC-7 — Local dev / tests:** flag irrelevant locally (no `TURSO_DATABASE_URL` → plain SQLite, AC-3); tests
  mock `libsql.connect` and assert the call shape (no real sync).

## 5. Out of scope
- **Co-locating the primary in Oregon** — blocked by the Turso Free tier (needs an upgrade); this feature
  avoids it.
- **Switching DB engine to Postgres** — a full SQL/driver rewrite with the same network-latency class; not done.
- **Render persistent disk / paid tier** — out of scope ($0 constraint); ephemeral + bootstrap is accepted.
- **Multi-writer / multi-backend sync semantics** — single Render backend only; no cross-backend write
  coordination.
- **Any node/edge/`ContractState`/migration/dependency/API/frontend change.**

## 6. Evaluation (metrics to log)
No accuracy/retrieval change. Operability: log (debug) at startup whether the store opened in embedded-replica
mode (replica path + sync interval) vs pure-remote — never the token. The live smoke (AC-8) is the real
measure: dashboard/report load time before vs after, and that a fresh analysis's writes are durable + visible.
No eval-harness change.

## 7. Open questions
Resolved inline (2026-10-11); none architecturally significant:
- **OQ-1 — Embedded replica vs co-location vs Postgres? → RESOLVED: embedded replica** (D1) — the only $0,
  no-migration way to get local-latency reads given the Free-tier co-location block.
- **OQ-2 — Sync cadence? → RESOLVED: bootstrap-on-connect + `TURSO_SYNC_INTERVAL_SECONDS` (default 60)** (§2).
  Single-backend read-your-writes covers own-write freshness; the interval only bounds out-of-band staleness.
- **OQ-3 — Flagged or default-on? → RESOLVED: flag default off** (D2) — pure-remote stays the safe default;
  enable in the Render deploy after the live smoke (AC-8), reversible instantly by unsetting the flag.

No open questions remain.
