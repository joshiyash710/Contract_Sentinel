# Feature 051 — Turso (libSQL) persistence for the Alembic-managed store (SQLite default)

Branch: `feature/051-turso-persistence` (per constitution §11).

## 1. Problem statement

The durable store DB is a single Alembic-managed SQLite file, `JOB_STORE_DB_PATH` (`data/job_store.db`),
holding the `jobs`, `users`, and `password_reset_tokens` tables. The FastAPI lifespan
(`app/api/main.py`) runs `upgrade_to_head(JOB_STORE_DB_PATH)` then constructs `JobStore`, `UserStore`,
and `PasswordResetStore` — all three on that one file, each via
`sqlite3.connect(db_path, check_same_thread=False)` + `row_factory = sqlite3.Row` under a shared
`threading.Lock`.

On **Render's free tier the disk is ephemeral** — that file is wiped on every restart/redeploy, losing
all accounts, job history, and reset tokens (see [[project_render_turso_deploy]]). This feature moves
that single store DB to **Turso** (a durable, network-hosted **libSQL** database that is
**SQLite-file-format compatible**, free tier: 5 GB / no expiry), while keeping **local SQLite as the
default** (byte-for-byte today when `TURSO_DATABASE_URL` is unset).

A **live spike (2026-08-29, see [[project_render_turso_deploy]])** established the shape:
- `libsql` (pip, Windows-installable) is a **sqlite3-compatible** client for our SQL: `?` placeholders,
  `ON CONFLICT` upsert, `executemany`, and the shared-connection + `check_same_thread=False` + lock
  threading model all work.
- BUT libsql returns **plain tuples with no `row_factory`** → the stores' by-name `row["col"]` access
  needs a **dict-row shim** (built from `cursor.description`, proven in the spike).
- `langgraph`'s **`SqliteSaver` is INCOMPATIBLE** with a libsql connection → the **checkpointer stays on
  local ephemeral SQLite** (accepted trade: only *mid-flight-resume-across-restart* is lost; completed
  reports, accounts, and history are durable in Turso).

### Position relative to the constitution
No LangGraph node/edge change, no `ContractState` change, **no new Alembic migration** (the schema is
unchanged — the existing migrations `0001…0008` simply replay against Turso, whose libSQL dialect IS
SQLite). §3 the Turso settings are named config constants read at call time. §4 unchanged (stores use
plain rows, not graph state). §8 unrelated (no model). Reversible: empty `TURSO_DATABASE_URL` ⇒ local
SQLite, exactly today. Developed on `feature/051-turso-persistence`.

### Privacy / data-egress posture (explicit — mirrors 046/050)
With Turso configured, the store DB — **user accounts (email + password *hash*), job metadata, and
reset-token hashes** — lives on Turso (a third-party managed DB) over TLS. Resolution, opt-in:
- **OFF by default** (`TURSO_DATABASE_URL` empty ⇒ fully local). Egress happens only when an operator
  sets it for the deploy.
- **What is stored:** password **hashes** (never plaintext), job rows, and reset-token **hashes**.
  Google OAuth tokens are already **Fernet-encrypted at rest** (feature 032) and remain ciphertext in
  Turso. **No** encryption keys, `AUTH_SECRET`, or plaintext credentials are stored.
- **Secret hygiene:** `TURSO_AUTH_TOKEN` is read from env/`.env` (gitignored) and **never logged**
  (AC-6), mirroring the 032/046/050 discipline.
- **Reversibility:** clearing `TURSO_DATABASE_URL` restores the fully-local posture.

## 2. Inputs and outputs

No `ContractState` change (constitution §4/§10). This feature changes only *where* the store rows live.

### 2.1 New config (§3, env-overridable; near `JOB_STORE_DB_PATH`)
- `TURSO_DATABASE_URL: str` — default `""`. Empty ⇒ local SQLite (byte-for-byte today). A Turso DB URL
  (e.g. `libsql://<db>-<org>.turso.io`) routes the store DB to Turso.
- `TURSO_AUTH_TOKEN: str` — from env; default `""`. **Never logged.**

### 2.2 New dependencies
- `libsql` — the sqlite3-compatible libSQL Python client (Windows-installable; the runtime store
  connection).
- `sqlalchemy-libsql` — the SQLAlchemy dialect (`sqlite+libsql://…`) so Alembic can migrate Turso via
  the existing `engine_from_config` path in `alembic/env.py`.

### 2.3 Connection factory (NEW `app/runner/db_backend.py`)
`connect(db_path: str)` returns:
- **default** (`TURSO_DATABASE_URL` empty) → `sqlite3.connect(db_path, check_same_thread=False)` with
  `row_factory = sqlite3.Row` (byte-for-byte today's store connection).
- **Turso** (`TURSO_DATABASE_URL` set) → a **libsql connection wrapped** to expose the exact
  `sqlite3.Connection`/`Cursor` surface the three stores use. A code audit of the three stores shows the
  wrapper **MUST** support (these are all in live use, not hypothetical):
  - `execute(sql, params=())` and **`executemany(...)`** (`store.py` uses `executemany` in the prune
    path) and `commit()` / `close()`;
  - a settable `row_factory` (accepted/ignored; the wrapper's rows are already by-name-accessible);
  - **Row objects built from `cursor.description`** supporting **by-name (`row["col"]`, incl. aggregate
    aliases like `cur.fetchone()["n"]`), positional (`row[0]`, used for an unaliased `COUNT(*)`), and
    `.keys()`** (every `_decode` uses the `"col" in row.keys()` idiom for the additive-nullable columns)
    — a faithful `sqlite3.Row` stand-in (the spike-proven dict-row shim);
  - a correct **`cursor.rowcount` for UPDATE/DELETE** — `password_reset_store.mark_used` returns
    `rowcount == 1` to guarantee **single-use** token consumption (TOCTOU-safe), so `rowcount` parity is
    **load-bearing for auth security**, not cosmetic.
  `cursor.lastrowid` is **not** required (all three tables use client-generated UUID/text primary keys,
  never AUTOINCREMENT). The plan-phase audit (Open Question 3) **confirms completeness** of this list
  against the real code, rather than discovering whether the surface exists.

### 2.4 Store wire-in (3 stores)
`JobStore`, `UserStore`, `PasswordResetStore` `__init__` replace
`self._conn = sqlite3.connect(db_path, check_same_thread=False)` (+ the `row_factory` line) with
`self._conn = db_backend.connect(db_path)`. **No SQL, method, lock, or `_decode` change** — the wrapper
matches the connection/row surface those methods already use.

### 2.5 Migrations (`app/runner/migrations.py`)
`upgrade_to_head(db_path)`: when `TURSO_DATABASE_URL` is set, inject a `sqlalchemy.url` of the form
`sqlite+libsql://<host>?authToken=<token>&secure=true` (exact format pinned by the plan-phase probe)
instead of `sqlite:///{db_path}`, so `alembic upgrade head` replays the existing migrations against
Turso. `alembic/env.py` is **unchanged** (it already runs `engine_from_config` on the injected URL).
The **token is never logged**, including in any Alembic/SQLAlchemy echo.

### 2.6 Checkpointer — explicitly UNCHANGED
`app/runner/persistence.py::build_saver` keeps constructing a local `SqliteSaver` on
`CHECKPOINTER_DB_PATH` (spike: `SqliteSaver` is libsql-incompatible). On Render's ephemeral disk this
means **checkpoints do not survive a restart** → a job interrupted mid-run cannot auto-resume, but its
inputs and any completed result are durable in Turso. This trade is documented in `docs/DEPLOYMENT.md`.
A durable checkpointer (e.g. blob-snapshotting the checkpoint file) is **out of scope** (noted follow-up).

### 2.7 Output
No new state field, report, or schema change. With `TURSO_DATABASE_URL` set (and `alembic upgrade head`
run once against Turso), accounts/jobs/reset-tokens persist in Turso and survive a Render restart;
graph, edges, and downstream contracts are unchanged.

## 3. Resolved decisions (inline)
- **D1 — Default local SQLite** (empty `TURSO_DATABASE_URL`) ⇒ zero behavior change. Reversible.
- **D2 — Remote-only libsql connection** (not embedded-replica) — simplest and correct; a local replica
  file is pointless on Render's ephemeral disk. Embedded-replica read-latency optimization is a later
  follow-up.
- **D3 — Dict-row shim mimics `sqlite3.Row`** (by-name incl. aggregate aliases, positional `[0]`, and
  `.keys()`) AND the wrapped cursor preserves `rowcount` for UPDATE/DELETE (load-bearing for
  `mark_used`'s single-use guarantee) + `executemany`/`commit` — so store `_decode` and mutation code is
  untouched. `lastrowid` is not needed (client-generated UUID/text PKs).
- **D4 — Alembic via the `sqlalchemy-libsql` dialect URL** — reuses the existing `engine_from_config`
  path; no `env.py` change; the existing migrations replay (libSQL = SQLite dialect).
- **D5 — Checkpointer stays local/ephemeral** (spike: `SqliteSaver` incompatible). Accepted durability
  trade; documented.
- **D6 — `TURSO_AUTH_TOKEN` never logged**; a set URL with an empty token raises a clear config error.
- **D7 — Reversible** via empty `TURSO_DATABASE_URL`.

## 4. Acceptance criteria

### Backend (pytest — libsql MOCKED / local-SQLite paths only; no network)
- **AC-1 (factory dispatch):** `db_backend.connect(path)` returns a real `sqlite3.Connection` when
  `TURSO_DATABASE_URL` is empty, and the libsql wrapper when it is set (libsql client mocked).
- **AC-2 (default byte-identical):** with `TURSO_DATABASE_URL` empty, all three stores behave exactly as
  today — the **existing** `test_store` / `test_user_store` / `test_password_reset_store` suites pass
  **unchanged** (they run against a real local SQLite via the factory). Closes the loop with AC-1: the
  empty-URL branch returns a genuine `sqlite3.Connection` with `row_factory = sqlite3.Row`, so those
  suites exercise the unmodified sqlite3 object — the factory is a pass-through on the default path.
- **AC-3 (dict-row shim — read path):** a wrapped-cursor row built from a mocked libsql
  `(description, tuple)` supports `row["col"]` (incl. an aggregate alias), `row[0]`, and `.keys()` for
  every column the three stores read; a round-trip of each store's `_decode` over a shim row
  reconstructs the dataclass correctly.
- **AC-3b (cursor.rowcount parity — mutation path):** a wrapped-cursor `UPDATE`/`DELETE` reports a
  `rowcount` matching `sqlite3` semantics, and specifically `password_reset_store.mark_used` over the
  wrapper returns `True` iff exactly one still-unused row was consumed and `False` on a second attempt —
  so the single-use-token (TOCTOU) guarantee is regression-tested on the Turso path, not assumed.
- **AC-4 (stores route through the factory):** each store's `__init__` obtains its connection from
  `db_backend.connect` (spy), not a direct `sqlite3.connect`.
- **AC-5 (migration URL):** `upgrade_to_head` builds a `sqlite+libsql://…authToken=…` URL when
  `TURSO_DATABASE_URL` is set and `sqlite:///{db_path}` when not (assert the URL shape; the token value
  never appears in logs).
- **AC-6 (token hygiene):** `TURSO_AUTH_TOKEN` never appears in any log/exception; `TURSO_DATABASE_URL`
  set with an empty token raises a clear, actionable config error (not a silent local fallback).
- **AC-7 (config validity):** `TURSO_DATABASE_URL` / `TURSO_AUTH_TOKEN` default `""`; `test_config`
  asserts the defaults and types.
- **AC-8 (checkpointer unchanged):** `build_saver` still constructs a local `SqliteSaver`; a test
  asserts the checkpointer path is never routed to Turso even when `TURSO_DATABASE_URL` is set.
- **AC-9 (scope):** `git diff` (vs the branch point) touches only `app/config.py`,
  `app/runner/db_backend.py` (NEW), the three store files, `app/runner/migrations.py`,
  `pyproject.toml` + `uv.lock` (add `libsql`, `sqlalchemy-libsql`), the tests, and `specs/051-**`. **No**
  graph/edge/`ContractState`/new-migration/checkpointer-logic/frontend change; the existing Alembic
  migration files are unchanged. Whole `pytest` green.

### Live (AC-10 — needs the operator's Turso DB; deferred from the merge gate, per plan)
- **AC-10:** against a real Turso DB (`TURSO_DATABASE_URL`/`TURSO_AUTH_TOKEN`): `alembic upgrade head`
  succeeds on Turso (all `0001…0008` replay); a full round-trip works (register a user → log in → submit
  a job → read it back via `/api/jobs`); and the data **survives a process restart** (kill + restart the
  backend, confirm the account + job are still present). Report as a `RESULTS.md`.

## 5. Edge cases
- **EC-1 — libsql remote connect fails at startup** (bad URL/token/network): raise a clear error during
  store construction / migration, not a silent fall-back to a fresh local DB (which would look like data
  loss).
- **EC-2 — a migration fails to replay on Turso** (a SQLite-ism libSQL rejects): surfaced loudly by
  `upgrade_to_head` (it already re-raises); this is **the key risk** — the plan-phase probe runs
  `alembic upgrade head` against Turso before merge to confirm all `0001…0008` apply. (Same probe as
  Open Question 2 — one obligation, not two.)
- **EC-3 — thread-safety under the wrapper:** the shared connection + lock + `check_same_thread=False`
  model must hold on libsql (spike proved the basic pattern; the wrapper must not break it — the worker
  thread and asyncio loop share one wrapped connection).
- **EC-4 — row-access surface (already audited — required, not conditional):** the wrapper MUST support
  `.keys()` (used in every `_decode`), positional `row[0]` (unaliased `COUNT(*)`), by-name incl.
  aggregate aliases, `executemany`, `commit`, and a correct `cursor.rowcount` for UPDATE/DELETE
  (`password_reset_store.mark_used` single-use consumption). A missing/incorrect one of these is a
  silent correctness/security bug. `lastrowid` is not used (client-generated PKs). The plan-phase audit
  confirms this list is complete against the real store code (Open Question 3); it does not discover
  whether the surface exists.
- **EC-5 — `TURSO_AUTH_TOKEN` empty while URL set:** clear config error (EC-1 sibling), never a silent
  local fallback.
- **EC-6 — per-query network latency** (remote-only): acceptable at the deploy's low traffic; noted, not
  optimized (D2). **EC-7 — Turso free-tier row-op caps** (10 M writes/mo): ample for this workload; a
  degraded/again-later error surfaces loudly rather than corrupting.

## 6. Out of scope
- **Uploads/reports blob storage** in Turso — **feature 052** ([[project_render_turso_deploy]]).
- **Deploy wiring** (`render.yaml`, keep-alive, resume-on-boot) — **feature 053**.
- **Durable checkpointer** — stays local/ephemeral (D5); a blob-snapshot approach is a noted later
  follow-up, not this feature.
- **Embedded-replica** read-latency optimization (D2); multi-DB/sharding; any Postgres path.
- **New schema/migrations** — the schema is unchanged; this only relocates it.

## 7. Open questions (resolved by a live Turso probe in the plan phase — needs the operator's Turso DB)
1. **Exact `libsql` Python remote-connection API** — pure-remote signature (`libsql.connect(url,
   auth_token=…)` vs an embedded-replica `sync_url` form) and whether it accepts `check_same_thread`
   and a shared connection across the worker + asyncio threads under our lock. **Blocks the wrapper.**
2. **`sqlalchemy-libsql` URL format + full migration replay** — the exact `sqlite+libsql://…` URL
   (authToken/secure params) AND whether **all** existing migrations `0001…0008` apply cleanly on Turso
   with no rejected SQLite-ism. **The key merge risk** — probe `alembic upgrade head` on Turso first.
3. **Full row-access surface of the 3 stores** — the required surface is already enumerated in
   §2.3/EC-4 (`.keys()`, positional `[0]`, aggregate aliases, `executemany`, `commit`, `rowcount`); the
   plan audit **confirms that list is complete** and that no store uses `lastrowid` (client-generated
   PKs). Not a discovery task — a completeness check (EC-4).
4. **Transaction/commit parity** — the stores call `.commit()` explicitly; confirm libsql's
   commit/autocommit semantics match sqlite3 (no lost writes, no implicit-transaction surprises). In
   particular, confirm libsql does not silently autocommit mid-`executemany` (the `prune` path) in a way
   that diverges from sqlite3's single-transaction semantics, and that `mark_used`/`invalidate_user_tokens`
   commit-before-return holds.
5. **Windows dev/test installability** — `libsql` (0.1.11) installed on Windows in the 050 spike, but
   `libsql-experimental` did **not** build; confirm `sqlalchemy-libsql` has a usable Windows wheel so
   the AC-10 live probe + any Turso-path tests run on the dev machine (else run them in the Linux
   container / defer to deploy).
