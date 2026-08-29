# Feature 051 — Tasks: Turso (libSQL) persistence for the Alembic-managed store (SQLite default)

Implements `specs/051-turso-persistence/plan.md` (spec + plan spec-reviewer-APPROVED). TDD per §7: write/
run tests FAILING first, then implement; never weaken a test. **All unit tests run on Windows** — libsql
is MOCKED and the default path is real local SQLite. The live Turso migration replay (AC-10) is Linux-only
and deferred (T12). Run from `backend/`. Each task cites the acceptance criterion it satisfies.

---

## T0 — Preconditions (no code change)
0.1 `git branch --show-current` == `feature/051-turso-persistence`.
0.2 **Revert any local `OLLAMA_MODEL_NAME` qwen3:4b→qwen3:8b override** in `.env`/env before running
    `test_config`. Re-apply after merge.
0.3 Baseline: `python -m pytest -q` green.

## T1 — Dependencies (`pyproject.toml` + `uv.lock`)
1.1 Add to `[project].dependencies`: `"libsql>=0.1.11"` (cross-platform runtime store client).
1.2 Add the Linux-only migration dialect with a PEP-508 marker:
    `"sqlalchemy-libsql>=0.2.0 ; sys_platform == 'linux'"`.
1.3 `uv lock` then `uv sync --extra dev`.
    - **If `uv lock` fails on Windows** because it must *build* `sqlalchemy-libsql`/`libsql-experimental`
      to read metadata (they have no Windows wheel): **remove line 1.2 from `pyproject.toml`** and instead
      add `RUN pip install sqlalchemy-libsql` to `backend/Dockerfile` (048 infra — a deploy-infra edit,
      noted as outside the AC-9 store-code allow-list). Re-run `uv lock` + `uv sync`.
1.4 Verify `python -c "import libsql"` works (it should — installs on Windows). `sqlalchemy-libsql` will
    NOT import on Windows; that is expected (migrations are Linux-only).

## T2 — (TEST FIRST) config asserts — AC-7
2.1 In `tests/unit/test_config.py`, add a test: `TURSO_DATABASE_URL` and `TURSO_AUTH_TOKEN` both default
    `""` (when the env vars are unset) and are `str`.
2.2 Run → **FAIL** (constants absent).

## T3 — (IMPL) config constants — AC-7
3.1 In `app/config.py` near `JOB_STORE_DB_PATH`, add (env-read; `load_dotenv()` already present):
    ```python
    TURSO_DATABASE_URL: str = os.getenv("TURSO_DATABASE_URL", "").strip()   # "" ⇒ local SQLite (default)
    TURSO_AUTH_TOKEN: str = os.getenv("TURSO_AUTH_TOKEN", "")               # DB auth token; NEVER logged
    ```
    Comment: empty URL ⇒ byte-for-byte today; a URL routes the store DB to Turso (a **Linux-deploy-only**
    config — migrations need `sqlalchemy-libsql`). Never log `TURSO_AUTH_TOKEN`.
3.2 Run `test_config.py` → **green**.

## T4 — (TEST FIRST) connection factory + wrapper — AC-1, AC-3, AC-3b, AC-6
4.1 Create `tests/unit/test_db_backend.py`. Mock the module-level `db_backend.libsql` (monkeypatch
    `db_backend.libsql.connect` to return a fake raw connection/cursor exposing `execute`, `commit`,
    `close`, `fetchone`, `fetchall`, `description`, `rowcount`). Monkeypatch
    `db_backend._config.TURSO_DATABASE_URL` / `TURSO_AUTH_TOKEN` per case. Tests:
    - **AC-1:** `connect(path)` → a real `sqlite3.Connection` (with `row_factory is sqlite3.Row`) when
      `TURSO_DATABASE_URL==""`; a `_LibsqlConn` when it is set (token stubbed).
    - **AC-3 (read shim):** a `_Row` built from `(description=[("id",…),("v",…)], (1,"x"))` supports
      `row["v"]`, `row[0]`, `list(row.keys())==["id","v"]`, `"v" in row.keys()`, iteration; a
      `_LibsqlCursor.fetchone()/fetchall()` wrap raw tuples into `_Row`; an **aggregate alias** row
      (`description=[("n",…)]`, `(3,)`) yields `row["n"]==3`; **positional** `row[0]==3` too.
    - **AC-3b (mutation):** `_LibsqlCursor.rowcount` delegates to the raw cursor; `executemany(sql, seq)`
      issues `len(seq)` executes and an **empty seq is a no-op** (does NOT run `sql` with `()`); a
      `_LibsqlConn`-backed `mark_used`-style UPDATE returning `rowcount==1` then `0` models single-use.
    - **AC-6:** `_connect_turso` with `TURSO_DATABASE_URL` set + empty `TURSO_AUTH_TOKEN` raises a clear
      `ValueError` whose message contains no token material.
4.2 Run → **FAIL** (module absent).

## T5 — (IMPL) `app/runner/db_backend.py` — AC-1, AC-3, AC-3b, AC-6
5.1 Create per plan §2: **module-level `import libsql`** (libsql is a cross-platform core dep, so a
    top-level import is safe and keeps `db_backend.libsql` patchable — mirrors `embed_client`'s
    `import ollama`); `connect(db_path)` (sqlite default sets `row_factory = sqlite3.Row`; Turso →
    `_connect_turso`); `_connect_turso` (empty-token → `ValueError`; `libsql.connect(URL,
    auth_token=TOKEN)` → `_LibsqlConn`); `_Row` (by-name incl. alias, positional `[0]`, `.keys()`,
    `__contains__`, `__iter__`, `__len__`); `_LibsqlCursor` (`description`, `rowcount`, `lastrowid`,
    `fetchone`/`fetchall` → `_Row`); `_LibsqlConn` (`execute`, `executemany` as execute-loop with the
    empty-seq benign-cursor guard, `commit`, `close`; **no `row_factory` attribute**).
5.2 Run `test_db_backend.py` → **green**.

## T6 — (TEST FIRST) store wire-in — AC-4 (and AC-2 pre-check)
6.1 In `tests/unit/test_job_store.py` / `test_user_store.py` / `test_password_reset_store.py` (or a new
    `test_store_backend_wiring.py`), add an **AC-4** test per store: constructing the store calls
    `app.runner.db_backend.connect` (patch it with a spy returning a real in-memory/tmp
    `sqlite3.Connection` so the rest of the store still works).
6.2 Run the new AC-4 tests → **FAIL** (stores still call `sqlite3.connect` directly).

## T7 — (IMPL) store wire-in — AC-2, AC-4
7.1 In `store.py`, `user_store.py`, `password_reset_store.py` `__init__`, replace the two lines
    ```python
    self._conn = sqlite3.connect(db_path, check_same_thread=False)
    self._conn.row_factory = sqlite3.Row
    ```
    with (add `from app.runner import db_backend` at module level):
    ```python
    self._conn = db_backend.connect(db_path)
    ```
    **Delete the `row_factory` line** (the factory owns it). Remove the now-unused `import sqlite3` only
    if `ruff` flags it (note: some stores still reference `sqlite3` elsewhere — check before removing).
7.2 Run the **existing** `test_job_store.py` + `test_store_list.py` + `test_user_store.py` +
    `test_password_reset_store.py` suites (AC-2 — must pass **unchanged**) + the T6 AC-4 spy tests →
    **green**.

## T8 — (TEST FIRST) migrations URL + token hygiene — AC-5, AC-6
8.1 In `tests/unit/test_migrations.py` (create if absent), patch `app.runner.migrations.command.upgrade`
    with a spy that captures the `Config`. Tests:
    - **AC-5:** with `TURSO_DATABASE_URL` set, the captured `Config`'s `sqlalchemy.url` has scheme
      `sqlite+libsql` and contains the host; with it empty, the url is `sqlite:///{db_path}`.
    - **AC-6:** `TURSO_AUTH_TOKEN` never appears in caplog; when the spy `command.upgrade` raises an
      exception whose message contains the token, `upgrade_to_head` re-raises with the token **redacted**.
8.2 Run → **FAIL**.

## T9 — (IMPL) migrations Turso URL + redaction — AC-5, AC-6
9.1 In `app/runner/migrations.py`: `import app.config as _config`; in `upgrade_to_head`, set
    `sqlalchemy.url` to `_turso_sqlalchemy_url()` (`sqlite+libsql://<host>/?authToken=<token>&secure=true`,
    derived from `TURSO_DATABASE_URL`+`TURSO_AUTH_TOKEN`) when `TURSO_DATABASE_URL` is set, else the
    existing `sqlite:///{db_path}`. Wrap `command.upgrade(...)` in a `try/except Exception as e:` that
    re-raises with `TURSO_AUTH_TOKEN` replaced by `<redacted>` in the message (only when the token is
    non-empty). Do not enable SQLAlchemy echo.
9.2 Run `test_migrations.py` → **green**.

## T10 — (TEST) checkpointer unchanged — AC-8
10.1 In `tests/unit/test_build_graph_checkpointer.py`, assert `build_saver(path)` returns a
     `langgraph.checkpoint.sqlite.SqliteSaver` and that `persistence.py` never reads `TURSO_DATABASE_URL`
     (grep-style source assertion or behavior test). Run → **green** (implementation already satisfies
     this; if the assertion is new, it should pass without code change).

## T11 — Full suite + diff-scope + lint — AC-9
11.1 `python -m pytest -q` → whole suite **green**.
11.2 `ruff check` clean on the touched files (pre-existing `config.py` E402 excluded — it predates this
     feature). `black` is not enforced project-wide (existing files are non-compliant); match surrounding
     style, do not reformat pre-existing files.
11.3 `git diff --name-only <branch-point>` == plan §0 allow-list (`app/config.py`,
     `app/runner/db_backend.py` NEW, the 3 store files, `app/runner/migrations.py`,
     `pyproject.toml`+`uv.lock`, the tests, `specs/051-**`; + `backend/Dockerfile` ONLY if the T1.3
     fallback was used). **No** graph/edge/`ContractState`/new-migration/checkpointer-logic/frontend
     change; existing Alembic migration files unchanged; `OLLAMA_MODEL_NAME` unchanged (qwen3:8b).

## T12 — Merge (git-finish) — deferred: AC-10 (Linux)
12.1 T11 green + diff clean + `OLLAMA_MODEL_NAME` reverted + `uv.lock` updated. Rebase branch point, merge
     `feature/051-turso-persistence`, delete branch (still stacked on the unmerged 048→050 chain —
     merge-order handled at deploy-phase end). Re-apply local qwen3:4b after.
12.2 **AC-10 (post-merge, LINUX only — NOT a merge blocker):** in the Render container / a Docker run /
     WSL with `sqlalchemy-libsql` installed, against the real Turso DB: `alembic upgrade head` replays
     `0001…0008` (0007's data-read is a no-op on the empty DB); full round-trip (register → login →
     submit job → read back via `/api/jobs`); **kill + restart** the backend and confirm the account +
     job persist. Add the checkpointer-durability trade + Turso-provenance operator note to
     `docs/DEPLOYMENT.md` alongside (out of the gated merge diff). Record a `RESULTS.md`.

---

### Notes for the implementation model
- `db_backend` reads config via `_config.TURSO_DATABASE_URL` / `_config.TURSO_AUTH_TOKEN` at call time
  (so tests monkeypatch `db_backend._config.<NAME>`); `libsql` is imported at module level (patch
  `db_backend.libsql.connect`).
- **Never log or embed `TURSO_AUTH_TOKEN`**; the migration URL carries it, so keep echo off and redact it
  from any re-raised exception (T9).
- The `_Row` wrapper must satisfy EVERY audited store access: `row["col"]` (incl. aggregate alias),
  `row[0]`, `.keys()` (the `"col" in row.keys()` idiom), iteration — plus `cursor.rowcount` for the
  `mark_used` single-use guarantee and `executemany` for the prune path.
- Do not touch `alembic/env.py`, the existing migration files, or `persistence.py` (checkpointer).
