# Feature 051 — Technical plan: Turso (libSQL) persistence for the Alembic-managed store (SQLite default)

Branch: `feature/051-turso-persistence` (per constitution §11).

Derived from `spec.md` (spec-reviewer-APPROVED) + the **live Turso probe (2026-08-29)**. Routes the single
Alembic-managed store DB (`jobs` + `users` + `password_reset_tokens`) to Turso when `TURSO_DATABASE_URL`
is set, via a connection factory + a `sqlite3.Row`-faithful dict-row wrapper; local SQLite stays the
default (byte-identical). Checkpointer stays local/ephemeral. **No graph/edge/`ContractState`/new-
migration change.**

### Probe-confirmed facts this plan is built on (measured against a real Turso DB)
- **Runtime connect form:** `libsql.connect(TURSO_DATABASE_URL, auth_token=TURSO_AUTH_TOKEN)` — connect,
  read/write, shared-connection + lock across threads, **`cursor.rowcount` after UPDATE == 1**, and
  **`cursor.description`** all work (Windows). `libsql` (0.1.11) installs on Windows **and** Linux.
- **Auth:** must be a **database** auth token (the account/platform API token 401s
  "invalid JWT … can't be decoded").
- **Migrations are Linux-only:** SQLAlchemy's built-in `sqlite` dialect **cannot** drive libsql
  (`Connection` has no `create_function`) → migrations require **`sqlalchemy-libsql`**, whose transitive
  `libsql-experimental` **does not build on Windows**. Alembic **offline `--sql`** is ruled out because
  **migration 0007 does a live data-read** (`.fetchall()`). ⇒ `alembic upgrade head` against Turso runs
  **only in the Linux (Docker/Render) container**; **Windows dev always uses local SQLite**.

## 0. Scope of change (files touched)
`git diff` (vs the branch point) must show only:
```
backend/app/config.py                          (2 new §3 constants: TURSO_DATABASE_URL/_AUTH_TOKEN)
backend/app/runner/db_backend.py               (NEW — connect() factory + libsql sqlite3.Row wrapper)
backend/app/runner/store.py                    (JobStore.__init__: 2 conn lines → db_backend.connect)
backend/app/runner/user_store.py               (same one-line connection swap)
backend/app/runner/password_reset_store.py     (same one-line connection swap)
backend/app/runner/migrations.py               (Turso → sqlite+libsql:// url; else sqlite:/// as today)
backend/pyproject.toml + backend/uv.lock       (libsql core; sqlalchemy-libsql linux-marked)
backend/tests/unit/test_db_backend.py          (NEW — factory + wrapper/shim, libsql MOCKED)
backend/tests/unit/test_config.py              (AC-7)
backend/tests/unit/test_migrations*.py         (AC-5 URL selection; may extend existing)
specs/051-turso-persistence/{spec,plan,tasks}.md
```
`alembic/env.py` is **unchanged** (URL-agnostic). The existing migration files are **unchanged** (no new
migration). `persistence.py` (checkpointer) is **unchanged**. **⚠ Revert any local `OLLAMA_MODEL_NAME`
qwen3:4b→qwen3:8b override before committing** (config-test gotcha).

## 1. Config (`app/config.py`)
Near `JOB_STORE_DB_PATH` (~line 596), env-read (`load_dotenv()` already present):
```python
TURSO_DATABASE_URL: str = os.getenv("TURSO_DATABASE_URL", "").strip()   # "" ⇒ local SQLite (default)
TURSO_AUTH_TOKEN: str = os.getenv("TURSO_AUTH_TOKEN", "")               # DB auth token; NEVER logged
```
Comment: empty URL ⇒ byte-for-byte today (local SQLite); a URL routes the store DB to Turso (a
**Linux-deploy-only** config — migrations need `sqlalchemy-libsql`, which builds only on Linux). Never
log `TURSO_AUTH_TOKEN`.

## 2. Connection factory + wrapper (NEW `app/runner/db_backend.py`) — the core
```python
"""Store-DB connection factory (feature 051). Default: sqlite3 (byte-identical). Turso: a libsql
connection wrapped to the sqlite3.Connection/Cursor surface the stores use, with rows that faithfully
mimic sqlite3.Row (by-name incl. aggregate aliases, positional [0], .keys()). TURSO_AUTH_TOKEN never
logged. libsql.connect(url, auth_token=...) is the probe-confirmed remote form."""
import sqlite3
import app.config as _config


def connect(db_path: str):
    if _config.TURSO_DATABASE_URL:
        return _connect_turso()
    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def _connect_turso():
    if not _config.TURSO_AUTH_TOKEN:
        raise ValueError(
            "TURSO_DATABASE_URL is set but TURSO_AUTH_TOKEN is empty. Set it in backend/.env "
            "(see docs/DEPLOYMENT.md). The token value is intentionally not shown."
        )
    import libsql  # lazy: only needed on the Turso path
    raw = libsql.connect(_config.TURSO_DATABASE_URL, auth_token=_config.TURSO_AUTH_TOKEN)
    return _LibsqlConn(raw)


class _Row:
    """Faithful sqlite3.Row stand-in built from (columns, values)."""
    __slots__ = ("_cols", "_vals")
    def __init__(self, cols, vals): self._cols, self._vals = cols, tuple(vals)
    def __getitem__(self, k):
        return self._vals[k] if isinstance(k, int) else self._vals[self._cols.index(k)]
    def keys(self): return list(self._cols)
    def __contains__(self, k): return k in self._cols        # supports `"col" in row` (defensive)
    def __iter__(self): return iter(self._vals)
    def __len__(self): return len(self._vals)


class _LibsqlCursor:
    def __init__(self, raw): self._raw = raw
    @property
    def description(self): return self._raw.description
    @property
    def rowcount(self): return self._raw.rowcount            # load-bearing: mark_used single-use
    @property
    def lastrowid(self): return getattr(self._raw, "lastrowid", None)
    def _cols(self): return [d[0] for d in (self._raw.description or [])]
    def fetchone(self):
        r = self._raw.fetchone()
        return None if r is None else _Row(self._cols(), r)
    def fetchall(self):
        cols = self._cols()
        return [_Row(cols, r) for r in self._raw.fetchall()]
    def __iter__(self): return iter(self.fetchall())


class _LibsqlConn:
    def __init__(self, raw): self._raw = raw
    def execute(self, sql, params=()):
        return _LibsqlCursor(self._raw.execute(sql, params))
    def executemany(self, sql, seq):
        # Emulate via execute-loop (robust regardless of libsql executemany support); prune path only.
        # Empty seq is a no-op (mirrors sqlite3.executemany([])) — must NOT run `sql` with () params,
        # which would raise a parameter-count mismatch on the parameterized DELETE.
        cur = None
        for params in seq:
            cur = self._raw.execute(sql, params)
        if cur is None:                                   # empty seq → benign empty cursor, rowcount 0
            cur = self._raw.execute("SELECT 1 WHERE 1=0")
        return _LibsqlCursor(cur)
    def commit(self): self._raw.commit()
    def close(self): self._raw.close()
```
- **`_Row` covers the audited surface** (spec §2.3/EC-4): `row["col"]` (incl. aggregate alias `["n"]`),
  positional `row[0]` (unaliased `COUNT(*)`), `.keys()` (the `"col" in row.keys()` idiom), iteration.
- **`rowcount`** delegates to the raw libsql cursor (probe: UPDATE → 1) → `mark_used` single-use works.
- `lastrowid` delegated defensively though unused (client-generated PKs) — deliberately **not** covered
  by an AC (no store uses it); don't add speculative test coverage for it.
- **`_LibsqlConn` intentionally has NO `row_factory` attribute.** The store swap (§3) deletes the
  `self._conn.row_factory = sqlite3.Row` line, so nothing ever sets `row_factory` on the wrapper — the
  Turso path yields `_Row` unconditionally. (Spec §2.3's "settable `row_factory` (accepted/ignored)" is
  therefore dead and deliberately not implemented; §2/§3 are consistent on this.)
- `_LibsqlCursor.__iter__` returns `iter(self.fetchall())` — used only where a store does
  `for r in cur.fetchall()` (it already calls `fetchall()` explicitly, so `__iter__` is a defensive
  convenience, not a hot path); it materializes once and is not iterated twice by any store.

## 3. Store wire-in (3 stores)
In each of `store.py`, `user_store.py`, `password_reset_store.py` `__init__`, replace:
```python
self._conn = sqlite3.connect(db_path, check_same_thread=False)
self._conn.row_factory = sqlite3.Row
```
with:
```python
from app.runner import db_backend      # module-level import
self._conn = db_backend.connect(db_path)
```
**Both original lines — including `self._conn.row_factory = sqlite3.Row` — are DELETED**; the factory owns
`row_factory` on the sqlite path, and the Turso wrapper yields `_Row` objects directly, so no store sets
`row_factory`. With that, **no other line changes** — every
`execute`/`executemany`/`commit`/`fetchone`/`fetchall`/`row["col"]`/`row.keys()`/`rowcount` call in the
stores is satisfied by the returned object. The shared-connection +
`threading.Lock` discipline is unchanged (probe confirmed threading holds on libsql).

## 4. Migrations (`app/runner/migrations.py`) — Turso URL (Linux-only path)
```python
import app.config as _config     # migrations.py may import config (it is NOT env.py)

def upgrade_to_head(db_path: str) -> None:
    cfg = Config()
    cfg.set_main_option("script_location", str(alembic_dir))
    if _config.TURSO_DATABASE_URL:
        cfg.set_main_option("sqlalchemy.url", _turso_sqlalchemy_url())   # sqlite+libsql://…
    else:
        cfg.set_main_option("sqlalchemy.url", f"sqlite:///{db_path}")    # unchanged default
    command.upgrade(cfg, "head")
```
- `_turso_sqlalchemy_url()` converts `libsql://<host>` →
  `sqlite+libsql://<host>/?authToken=<token>&secure=true` — the standard `sqlalchemy-libsql` form. This
  keeps **`alembic/env.py` UNCHANGED** (it still does `engine_from_config` on the injected
  `sqlalchemy.url`), and the URL is fully capturable from the Config object (AC-5).
- **Token hygiene (AC-6):** the token lives only in the URL held on the Config's `sqlalchemy.url`
  main-option; we never print it, **SQLAlchemy echo stays off**, and Alembic's default logging does not
  emit the URL. Belt-and-suspenders: `upgrade_to_head` wraps `command.upgrade` in a `try/except` that
  **redacts the token substring from any exception message before re-raising** (it already re-raises on
  error per its docstring) — so a connection error that echoes the URL cannot leak the token.
- This branch imports/uses `sqlalchemy-libsql`, which exists only on Linux → it executes only in the
  Linux deploy.

## 5. Dependencies (`pyproject.toml`)
- **Core:** `libsql>=0.1.11` (cross-platform; the runtime store connection).
- **Linux-only (migrations):** `sqlalchemy-libsql>=0.2.0 ; sys_platform == "linux"` — a PEP-508
  environment marker so `uv sync` **skips it on Windows** (it can't build there) and installs it in the
  Linux Docker image. `uv lock` resolves metadata without building. **Fallback if `uv lock` cannot get
  metadata on Windows:** drop the marker line and instead `pip install sqlalchemy-libsql` in the
  `Dockerfile` only (not in pyproject) — decided in tasks after trying the marker. The `Dockerfile`
  lives in the 048 deploy infra, so a Dockerfile edit under this fallback is a deploy-infra change
  **outside** this feature's AC-9 store-code allow-list (called out so it isn't read as scope drift).
  CI dep-audit still runs.

## 6. Checkpointer — unchanged
`app/runner/persistence.py::build_saver` keeps building a local `SqliteSaver` on `CHECKPOINTER_DB_PATH`
(spike: libsql-incompatible). On Render's ephemeral disk checkpoints don't survive a restart → mid-flight
resume is lost; completed jobs/accounts stay durable in Turso. Documented in `docs/DEPLOYMENT.md` (a doc
task, kept out of the gated diff).

## 7. Test plan (TDD, `tests/unit/`) — failing-first per §7; **libsql MOCKED, no network**
- **AC-1 (`test_db_backend.py`):** `connect(path)` → real `sqlite3.Connection` when `TURSO_DATABASE_URL`
  empty; the `_LibsqlConn` wrapper when set (monkeypatch `db_backend._config.TURSO_DATABASE_URL` +
  `TURSO_AUTH_TOKEN`; mock `libsql.connect`).
- **AC-2 (default byte-identical):** the **existing** `test_store` / `test_user_store` /
  `test_password_reset_store` suites pass **unchanged** with the empty-URL path (they hit a real local
  SQLite via the factory — the empty-URL branch returns a genuine `sqlite3.Connection` with
  `row_factory = sqlite3.Row`).
- **AC-3 (dict-row shim, read):** `_Row` from a mocked `(description, tuple)` supports `row["col"]`
  (incl. an aggregate alias), `row[0]`, `.keys()`, iteration; drive each store's `_decode` over a
  `_LibsqlConn` whose mocked cursor yields such rows and assert the dataclass reconstructs.
- **AC-3b (rowcount / single-use, mutation):** a `_LibsqlCursor` over a mocked raw cursor with
  `rowcount=1` reports `1`; drive `password_reset_store.mark_used` over the wrapper and assert it returns
  `True` once then `False` on a second call (single-use). Also assert `executemany` (prune path) issues
  N executes.
- **AC-4 (stores route through factory):** each store `__init__` calls `db_backend.connect` (spy).
- **AC-5 (migration URL selection):** with `command.upgrade` **patched** (so the Linux-only dialect is
  never invoked), `upgrade_to_head` passes a `Config` whose `sqlalchemy.url` scheme is `sqlite+libsql`
  with the host present when `TURSO_DATABASE_URL` is set, and `sqlite:///{db_path}` when not. Assert by
  capturing the `Config` from the patched `command.upgrade` (the URL — token included — lives on the
  Config, so it is capturable).
- **AC-6 (token hygiene):** `TURSO_AUTH_TOKEN` never appears in any log record; a simulated
  `command.upgrade` that raises an error whose message contains the token is re-raised by
  `upgrade_to_head` with the token **redacted**; `db_backend._connect_turso` with `TURSO_DATABASE_URL`
  set + an empty token raises a clear `ValueError` that echoes no token material.
- **AC-7 (`test_config.py`):** `TURSO_DATABASE_URL`/`TURSO_AUTH_TOKEN` default `""`, are `str`.
- **AC-8 (checkpointer unchanged):** `persistence.build_saver` still builds a local `SqliteSaver`; a
  test asserts the checkpointer path never consults `TURSO_DATABASE_URL`.
- **AC-9 (scope):** whole `pytest` green; diff = §0 allow-list; no graph/state/new-migration/checkpointer
  change; `OLLAMA_MODEL_NAME` unchanged.

All unit tests run on **Windows** (libsql mocked; default path is real SQLite). No test imports
`sqlalchemy-libsql` (the Linux-only migration execution is exercised by AC-10, not the unit suite).

## 8. Live validation (AC-10 — Linux only; deferred from the merge gate)
In a **Linux** environment (the Render container, a Docker run, or WSL with `sqlalchemy-libsql`
installed) against the real Turso DB: `alembic upgrade head` replays `0001…0008` (0007's data-read is a
no-op on the fresh/empty DB); then a full round-trip (register → login → submit job → read back via
`/api/jobs`); then **kill + restart** the backend and confirm the account + job persist. Record in a
`RESULTS.md`. This is the only step that cannot run on Windows dev.

## 9. Risks / platform constraints
- **Migrations Linux-only** (probe): the whole Turso path is a **Linux-deploy config**; Windows dev = SQLite.
  Setting `TURSO_DATABASE_URL` on Windows is unsupported (store connects, but `upgrade_to_head` can't).
  This fails **honestly** — the Turso migration branch surfaces a clear `ImportError` (no
  `sqlalchemy-libsql`) rather than silently connecting to an unmigrated DB. Documented; guarded by the
  default-off design.
- **Migration replay on Turso is unvalidated until AC-10 (Linux).** Mitigation: the reviewer confirmed
  the migrations use only plain SQLAlchemy DDL (no `batch_alter`/PRAGMA), and 0007's data step is a
  no-op on a fresh DB → high confidence, but **must be run in Linux before the deploy is trusted**.
- **Token hygiene:** the auth token lives in the `sqlalchemy.url` held on the Config (the standard
  `sqlalchemy-libsql` `?authToken=…` form — §4), protected by **no SQLAlchemy echo + never-logged +
  token-redaction of any re-raised exception** in `upgrade_to_head` (AC-6). *(This supersedes the
  spec's older §2.5 wording that floated a `connect_args` option; the plan commits to token-in-URL so
  AC-5 can capture it from the Config on Windows.)*
- **Per-query network latency** (remote-only, D2) — fine at deploy traffic; embedded-replica is a later
  optimization. **Turso free-tier caps** (10 M writes/mo) — ample.
- **`uv lock` with the linux marker** may need the Docker-install fallback (§5) if metadata resolution
  fails on Windows.

## 10. Merge
Whole `pytest` green (Windows, unit); diff = §0 allow-list; `OLLAMA_MODEL_NAME` reverted; `uv lock`
updated. Rebase the branch point, merge `feature/051-turso-persistence` (still stacked on the unmerged
048→050 deploy chain — merge order handled at deploy-phase end), delete branch. **AC-10 (Linux live
replay + restart-survival) + the `docs/DEPLOYMENT.md` note follow** the unit-green merge (like 046's
AC-9 / 050's AC-10). 052 (Turso blob storage for uploads/reports) stacks next.
