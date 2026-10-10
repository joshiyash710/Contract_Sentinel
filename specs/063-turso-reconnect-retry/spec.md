# Feature 063 — Spec: Turso (libSQL/Hrana) reconnect-and-retry on dropped connections

Status: DRAFT (pre spec-reviewer gate)
Branch: `feature/063-turso-reconnect-retry` (constitution §11).

> Production stability fix. The store DB uses one **long-lived libSQL connection** (feature 051,
> `app/runner/db_backend.py::_LibsqlConn`). A transient Hrana drop
> (`ValueError: Hrana: http error: connection closed before message completed`) leaves that shared
> connection **dead with no reconnect**, so every subsequent DB op fails until the service restarts —
> surfacing as mid-analysis "retry" prompts and very slow/failing dashboard/report loads. This feature makes
> the libSQL wrapper **reconnect and retry** on a dropped-connection error. **Runner DB-backend only.**

## 1. Problem statement

`db_backend.connect()` returns, when `TURSO_DATABASE_URL` is set, a `_LibsqlConn` wrapping a single
`libsql.connect(...)` handle (`self._raw`). The three stores (`JobStore`/`UserStore`/`PasswordResetStore`)
hold that one wrapper for the process lifetime and call `execute`/`executemany`/`commit` on it. There is **no
error handling**: `_LibsqlConn.execute` is `return _LibsqlCursor(self._raw.execute(sql, params))`.

Turso's Hrana protocol runs over HTTP; the connection can be dropped (idle, network blip, server-side close).
When it is, `self._raw.execute(...)` raises `ValueError: Hrana: http error: connection closed before message
completed` (observed in prod). Because the dead `self._raw` is never replaced, **all later operations on that
store keep failing** until the container restarts. Observed fallout:
- A pipeline run's `registry._persist` → `store.upsert` write fails mid-run → the job errors → the UI shows a
  retry prompt (seen in the logs: `worker._on_progress → registry.record_progress → store.upsert →
  db_backend.execute → ValueError: Hrana …`).
- Dashboard / report / job-status requests (all Turso reads) hit the same dead connection → stall then 500 →
  the app feels like it "keeps disconnecting." (`/api/health` doesn't touch the DB, so it stays 200 — which is
  why the service looks up while everything else fails.)

The fix: on a **connection-drop** error, `_LibsqlConn` transparently **reconnects** (a fresh
`libsql.connect`) and **retries** the operation a bounded number of times with small backoff. A non-connection
error (SQL/constraint) is **not** retried — it propagates unchanged.

### Position relative to the constitution
- **No LangGraph node/edge/`ContractState` change (§2).** Purely the runner DB-connection wrapper
  (`app/runner/db_backend.py`); no pipeline, API, or schema change. No Alembic migration.
- **§3 configurable.** The retry budget is a named config constant (`TURSO_RECONNECT_MAX_RETRIES`); the
  reconnect uses the existing `TURSO_DATABASE_URL`/`TURSO_AUTH_TOKEN`. `TURSO_AUTH_TOKEN` is **never logged**.
- **No new dependency.** `libsql` is already the connection dep (feature 051, `002-tech-stack`).
- **Local SQLite path unchanged.** `connect()` still returns a plain `sqlite3.Connection` when
  `TURSO_DATABASE_URL` is unset — byte-identical to today (local dev untouched). The reconnect logic lives in
  `_LibsqlConn`, which is only used on the Turso path.
- **Always-on resilience (no flag).** This only *adds* recovery on an otherwise-fatal error path; there is no
  behavior to turn off (a successful op is unchanged). Reversible by revert if ever needed.

## 2. Inputs and outputs

### New config (§3) — `app/config.py`
- `TURSO_RECONNECT_MAX_RETRIES: int = _env_int("TURSO_RECONNECT_MAX_RETRIES", 2)` — reconnect+retry attempts
  after the first failure (so up to 3 total tries). Bounded; env-overridable.

### `_LibsqlConn` — reconnect + retry (`app/runner/db_backend.py`)
- `_connect_turso()` passes a **reconnect factory** into `_LibsqlConn` (a zero-arg callable returning a fresh
  `libsql.connect(TURSO_DATABASE_URL, auth_token=TURSO_AUTH_TOKEN)`), so the wrapper can rebuild `self._raw`.
- A pure `_is_connection_drop(exc) -> bool` predicate: True when the raised error is a transport/connection
  drop (match the libSQL/Hrana signature — the error is a `ValueError`/`Exception` whose message contains any
  of: `"connection closed"`, `"Hrana"`, `"stream closed"`, `"error communicating"`, `"connection reset"`,
  `"Broken pipe"`). A normal SQL error (constraint/syntax) does **not** match → not retried.
- `execute`, `executemany`, and `commit` run through a shared retry helper: attempt the op; on an exception
  for which `_is_connection_drop` is True and attempts remain, **reconnect** (`self._raw = self._reconnect()`)
  after a small backoff and retry; otherwise re-raise. On success, return the normal result. The retry helper
  must re-run the *whole* op (so a reconnected `self._raw` is used).
- Reconnect/retry events are logged at WARNING (count + that a reconnect happened) — **never** the token or SQL
  params (which may contain user data); keep the log to "reconnected after a dropped Turso connection".

### Resolved decisions (inline)
- **D1 — Reconnect the shared wrapper in place.** The stores hold the `_LibsqlConn`; swapping its `self._raw`
  transparently heals every store without touching store code (the wrapper indirection makes this clean).
- **D2 — Retry only connection drops.** SQL/constraint/programming errors propagate immediately (retrying
  them is wrong and could mask bugs or double-apply). Detection is by error-signature (libSQL raises plain
  `ValueError`s, so type alone is insufficient).
- **D3 — Bounded retries + backoff.** `TURSO_RECONNECT_MAX_RETRIES` (default 2) with a short backoff; after
  exhaustion the original error propagates (caller/job fails as today, but only after a real retry).
- **D4 — Local SQLite untouched.** Only `_LibsqlConn` (Turso) gains this; `sqlite3` connections are unchanged.

## 3. Acceptance criteria

Backend, offline (pytest; `db_backend.libsql` is already patchable per its module comment — mock a raw conn
whose `execute` raises a Hrana-style error once/twice then succeeds; assert reconnect + retry).

- **AC-1 (reconnect + retry on drop):** a `_LibsqlConn` whose raw `execute` raises a connection-drop
  `ValueError` once, then succeeds, returns the successful cursor; the reconnect factory was called once (a
  fresh raw connection replaced the dead one); the op's result is correct.
- **AC-2 (retry budget exhausted → raise):** raw `execute` raises a connection-drop error on every attempt →
  after `TURSO_RECONNECT_MAX_RETRIES` reconnect attempts the original error propagates; reconnect was tried
  exactly `TURSO_RECONNECT_MAX_RETRIES` times.
- **AC-3 (non-connection error NOT retried):** raw `execute` raises a non-drop error (e.g.
  `ValueError("UNIQUE constraint failed")` or a SQL error) → it propagates on the **first** attempt; the
  reconnect factory is **not** called.
- **AC-4 (executemany + commit resilient):** `executemany` and `commit` also reconnect+retry on a drop
  (same predicate/budget), since a run's writes and commits hit the dead connection too.
- **AC-5 (local sqlite unchanged):** with `TURSO_DATABASE_URL` unset, `connect()` returns a `sqlite3.Connection`
  and no reconnect wrapper/logic is exercised — byte-identical to today (existing db_backend/store tests pass).
- **AC-6 (token/params never logged):** on a reconnect, no log record contains `TURSO_AUTH_TOKEN` or the SQL
  params (which may carry user data); the warning names only that a reconnect occurred and the attempt count.
- **AC-7 (config constant):** `TURSO_RECONNECT_MAX_RETRIES` is a named, env-overridable config constant;
  monkeypatching it changes the retry count (AC-2).
- **AC-8 (no architecture change):** `git diff main` touches only `app/config.py`, `app/runner/db_backend.py`,
  the new/updated db_backend tests, and the 063 specs. No node/edge/`ContractState`/migration/dependency/API/
  frontend change. Full backend suite green.

## 4. Edge cases
- **EC-1 — Reconnect itself fails:** the reconnect factory (`libsql.connect`) raises (Turso down / auth) →
  treat as a failed attempt; after the budget, propagate the LAST error (connection unavailable). No infinite
  loop (bounded by the budget).
- **EC-2 — Mid-transaction drop:** the retry re-runs the single `execute` on a fresh connection. The stores
  use autocommit-style single statements (`upsert`, etc.) + explicit `commit()`; a retried write is idempotent
  for `upsert` (INSERT … ON CONFLICT) — safe. (No multi-statement transaction spans the wrapper today.)
- **EC-3 — Drop on `commit()`:** commit is retried after reconnect; if the prior write didn't land, the caller
  re-issues on the next persist (progress is re-persisted each node). Acceptable.
- **EC-4 — A genuinely persistent outage:** budget exhausts → the job/request fails exactly as today, but only
  after real retries — no worse than current behavior, and self-heals the moment Turso recovers (next op
  reconnects).
- **EC-5 — False-positive signature match:** the predicate matches connection-drop phrases only; a SQL error
  whose message happens to contain a matched phrase is unlikely, but a retried idempotent `upsert`/read is
  harmless even if mis-retried once. Non-idempotent writes aren't used through this path.
- **EC-6 — `PasswordResetStore.mark_used` single-use (rowcount):** the retry wraps one `execute`; `rowcount`
  is read from the final successful cursor, so the single-use guarantee is preserved (a reconnect+retry of the
  same `used_at IS NULL`-guarded UPDATE still affects at most one row). `execute` and `commit()` are
  **separate** retry-wrapped ops: a drop detected only on `commit()` reconnects a fresh connection and the
  write may not have landed → the reset **fails closed** (token not consumed, reset still retryable), matching
  today's behavior on any commit failure.

## 5. Out of scope
- **Render free-tier cold-start latency** — the ~1-min spin-up after 15-min idle is a platform property, not a
  DB-connection bug; the keep-alive cron (docs/DEPLOYMENT.md) already mitigates it. This feature fixes the
  *connection-drop failures/slowness*, not baseline cold starts.
- **Connection pooling / multiple connections** — the single-connection model is unchanged; we only heal it on
  drop.
- **Retrying non-connection errors** (SQL/constraint) — explicitly not retried (D2).
- **The embeddings/`EMBED_PROVIDER` prod issue** — separate; tracked under feature 062 + the deploy env var.
- **Any API / graph / `ContractState` / migration / frontend change.**

## 6. Evaluation (metrics to log)
No accuracy/retrieval change. Operability only: a WARNING log on each reconnect
(`"reconnected after a dropped Turso connection (attempt N/…)"`, no token/params) so the frequency of Hrana
drops is observable in prod. No eval-harness change.

## 7. Open questions
Resolved inline (2026-10-10); none architecturally significant:
- **OQ-1 — Detect drops by type or message? → RESOLVED: message signature** (D2) — libSQL raises plain
  `ValueError`s for Hrana transport errors, so a substring match on the known drop phrases is the practical
  detector; a conservative allow-list keeps SQL errors out of the retry path.
- **OQ-2 — Flagged or always-on? → RESOLVED: always-on** (no flag) — it only adds recovery to a fatal path and
  is Turso-only; a successful op is unchanged.
- **OQ-3 — Retry budget → RESOLVED: `TURSO_RECONNECT_MAX_RETRIES` default 2** (3 total tries) with short
  backoff; env-overridable.

No open questions remain.
