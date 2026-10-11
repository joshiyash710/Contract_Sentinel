# Feature 065 — Spec: single shared connection for the Turso embedded replica

Status: DRAFT (pre spec-reviewer gate)
Branch: `feature/065-embedded-replica-shared-conn` (constitution §11).

> Fix for feature 064. Enabling `TURSO_EMBEDDED_REPLICA_ENABLED` crashed the replica sync in prod with
> `ERROR libsql::database::builder: Error syncing database: SQLite failure: wal_insert_begin failed`. Cause:
> the app opens **three** store connections (`JobStore`/`UserStore`/`PasswordResetStore`, `app/api/main.py:69-71`)
> and in embedded-replica mode each one opens + syncs the **same local file** → competing WAL writers. This
> feature makes embedded-replica mode return **one shared, serialized connection** reused by all stores, so a
> single owner syncs the local file. **Runner DB-backend only; pure-remote and local SQLite paths unchanged.**

## 1. Problem statement

Feature 064 added embedded-replica mode: when `TURSO_EMBEDDED_REPLICA_ENABLED`, `db_backend._turso_raw_connect`
opens `libsql.connect(local_path, sync_url=…, sync_interval=…)`. But `connect()` is called **once per store**,
and the app creates three stores against the same DB path at startup (`app/api/main.py:69-71`:
`JobStore`/`UserStore`/`PasswordResetStore`, all `JOB_STORE_DB_PATH`). In pure-remote mode three connections to
the same remote URL is harmless; in **embedded-replica mode** each connection opens and bootstraps/syncs the
**same local SQLite file** (`data/turso_replica.db`) → three concurrent WAL writers → libSQL fails the sync
with `wal_insert_begin failed`. The replica never bootstraps cleanly, so reads are empty/stale.

The 064 spec assumed "one shared connection across threads," but the real architecture is one connection
**per store**. This feature corrects that for the embedded-replica path only: `connect()` returns a **single
process-wide shared `_LibsqlConn`** (lazily created once) for the embedded replica, so exactly one connection
owns the local file and its sync. Because that one connection is now shared across the worker + request threads,
its operations are **serialized with a lock** (safe + still fast — embedded reads are local/sub-ms).

### Position relative to the constitution
- **No LangGraph node/edge/`ContractState` change (§2).** Only `app/runner/db_backend.py` (the connection
  factory + the `_LibsqlConn` wrapper). No pipeline/API/schema/migration change.
- **Fixes 064 within its established flag.** No new config; reuses `TURSO_EMBEDDED_REPLICA_ENABLED` /
  `TURSO_REPLICA_PATH` / `TURSO_SYNC_INTERVAL_SECONDS` and the 063 reconnect wrapper. `TURSO_AUTH_TOKEN` never
  logged.
- **No new dependency** (`libsql` already present; `threading` is stdlib).
- **Pure-remote + local SQLite paths byte-identical.** The singleton + lock apply ONLY to the embedded-replica
  path (which is itself default-off via 064's flag). With the flag off, each store still gets its own plain
  connection exactly as today.

## 2. Inputs and outputs

### `db_backend.py` — one shared embedded-replica connection
- A module-level singleton holds the embedded-replica `_LibsqlConn` (lazily created on first `connect()` in
  embedded mode; reused by every subsequent `connect()` in the process). A small reset hook lets tests clear it.
- `connect(db_path)`:
  - `TURSO_DATABASE_URL` set **and** `TURSO_EMBEDDED_REPLICA_ENABLED` → return the **shared** embedded
    `_LibsqlConn` (create once via the existing `_turso_raw_connect` embedded branch; wrap with a lock).
  - `TURSO_DATABASE_URL` set, flag off → today's behavior: a **new** pure-remote `_LibsqlConn` each call
    (unchanged).
  - no `TURSO_DATABASE_URL` → a **new** `sqlite3.Connection` each call (unchanged).
- `_LibsqlConn` gains an optional `lock` (a `threading.Lock`): when present, `execute`/`executemany`/`commit`
  run their whole op (including the 063 reconnect/retry) **under the lock**, serializing concurrent access from
  the worker + request threads to the one shared connection. Per-store (pure-remote) connections pass no lock
  → no serialization (byte-identical). Reads from the embedded replica are local (sub-ms), so serialized access
  stays fast.
- `close()` on the shared connection stays tolerant (064) and does not break other holders — closing is a
  process-shutdown concern; the shared instance is simply closed once.

### Behavioral effect (flag on, prod)
- Exactly **one** `libsql.connect(local_path, sync_url=…)` → **one** syncer → no `wal_insert_begin` conflict;
  the replica bootstraps cleanly and reads are local/instant. All three stores share that connection.

### Resolved decisions (inline)
- **D1 — Shared singleton, not per-store replicas.** One connection owning the local file is cleaner than N
  separate replica files (which would be N full local copies + N syncers). One owner, one sync.
- **D2 — Serialize with a lock.** A single shared connection across threads needs serialized ops; a lock is
  cheap given local sub-ms reads. Applies only to the shared embedded connection.
- **D3 — Embedded path only; everything else byte-identical.** Pure-remote keeps per-call connections; local
  SQLite unchanged. The fix is scoped to the flag 064 already gates.
- **D4 — Reuse 063 reconnect.** A dropped sync/connection still reconnects (the reconnect re-opens the shared
  embedded connection); the retry runs under the lock.

## 3. Acceptance criteria

Backend, offline (pytest; `db_backend.libsql.connect` mocked). The singleton is reset per test.

- **AC-1 (one shared connection in embedded mode):** with `TURSO_DATABASE_URL` set +
  `TURSO_EMBEDDED_REPLICA_ENABLED=True`, calling `connect()` **three times** returns the **same** `_LibsqlConn`
  instance, and `libsql.connect` is invoked **exactly once** (one syncer — the `wal_insert_begin` fix).
- **AC-2 (pure-remote unchanged):** flag off + `TURSO_DATABASE_URL` set → each `connect()` returns a **distinct**
  `_LibsqlConn` and `libsql.connect` is called once per `connect()` (byte-identical to 063/064; no singleton).
- **AC-3 (local sqlite unchanged):** no `TURSO_DATABASE_URL` → each `connect()` returns a new
  `sqlite3.Connection` (unchanged), regardless of the replica flag.
- **AC-4 (serialized access):** the shared embedded `_LibsqlConn` holds a lock; concurrent `execute` calls from
  multiple threads are serialized (no interleaving / no error) — verified with a lock whose acquisition is
  observed, or threads hitting the shared connection without raising.
- **AC-5 (063 reconnect under lock):** a dropped-connection error on the shared connection still reconnects +
  retries (the shared instance's `self._raw` is replaced) and succeeds; the retry runs within the lock.
- **AC-6 (embedded connect shape preserved):** the single `libsql.connect` still uses the 064 embedded shape
  (`database`=local replica path, `sync_url`=remote, `sync_interval`, `_check_same_thread=False`); the empty-token
  guard still fires.
- **AC-7 (no architecture change):** `git diff main` touches only `app/runner/db_backend.py`, the db_backend
  tests, and the 065 specs. No node/edge/`ContractState`/config/migration/dependency/API/frontend change. Full
  backend suite green.
- **AC-8 (live smoke — operational):** re-enable `TURSO_EMBEDDED_REPLICA_ENABLED=True` in Render → the startup
  `wal_insert_begin failed` error is **gone**, dashboard/report loads are sub-second, and a fresh analysis runs
  (writes durable, visible on next read). Verified on the deploy.

## 4. Edge cases
- **EC-1 — Reconnect replaces the shared raw:** on a drop, `_run` (under the lock) swaps `self._raw` on the
  shared instance via the 063 factory (embedded mode) → all stores keep using the healed shared connection.
- **EC-2 — Lock contention:** all store ops serialize on one lock; embedded reads are local/sub-ms so contention
  is negligible; the rare write forwards to the primary while holding the lock (acceptable — writes are
  infrequent: job submit/progress).
- **EC-3 — `close()` on the shared connection:** tolerant (064); a store closing it at shutdown doesn't corrupt
  data (primary is durable); the singleton is cleared so a later `connect()` re-creates it.
- **EC-4 — Flag toggled without restart:** not supported in practice (flag read at process start via the stores
  created in the lifespan); a change takes effect on redeploy. Acceptable.
- **EC-5 — Pure-remote path:** no singleton, no lock → three independent connections exactly as today (AC-2);
  no behavior change for the current (flag-off) prod.
- **EC-6 — Tests:** the singleton must be reset between tests (a reset helper/fixture) so one test's shared
  connection doesn't leak into another.

## 5. Out of scope
- **Per-store separate replica files** — rejected (D1): N local copies + N syncers; the shared connection is
  simpler and lighter.
- **A general connection pool** — single shared connection + lock is sufficient for this single-backend app.
- **Co-location / Postgres / Render paid disk** — unchanged scope decisions from 064.
- **Any node/edge/`ContractState`/config/migration/dependency/API/frontend change.**

## 6. Evaluation (metrics to log)
No accuracy/retrieval change. Operability: the 064 startup log ("embedded-replica mode …") now fires once; the
`wal_insert_begin failed` sync error should disappear (AC-8). No eval-harness change.

## 7. Open questions
Resolved inline (2026-10-11); none architecturally significant:
- **OQ-1 — Shared singleton vs per-store replica files? → RESOLVED: shared singleton** (D1) — one owner/one sync.
- **OQ-2 — Thread-safety of the shared connection? → RESOLVED: serialize ops with a `threading.Lock`** on the
  shared embedded `_LibsqlConn` only (D2); local reads keep it fast.
- **OQ-3 — Scope? → RESOLVED: embedded path only** (D3) — pure-remote/local byte-identical; reuses 064's flag
  and the 063 reconnect.

No open questions remain.
