# Feature 052 — Tasks: Report blob storage (Turso BLOBs; local disk default)

Implements `specs/052-turso-blob-storage/plan.md` (spec + plan spec-reviewer-APPROVED). TDD per §7:
write/run tests FAILING first, then implement; never weaken a test. **All unit/integration tests run on
Windows** — the Turso path is exercised via a real local SQLite `report_blobs` table (libsql not required
for the suite); the default path is real disk. Live Turso replay/durability is AC-9 (Linux, deferred).
Run from `backend/`. Each task cites its acceptance criterion.

---

## T0 — Preconditions (no code change)
0.1 `git branch --show-current` == `feature/052-turso-blob-storage`.
0.2 **Revert any local `OLLAMA_MODEL_NAME` qwen3:4b→qwen3:8b override** before `test_config`.
0.3 Baseline: `python -m pytest -q` green. (The 051 conftest already forces `TURSO_DATABASE_URL=""`
    suite-wide → blob_store defaults to disk in tests unless a test opts into the Turso path.)

## T1 — (TEST FIRST) blob_store — AC-1, AC-3
1.1 Create `tests/unit/test_blob_store.py`. For the Turso path, monkeypatch `blob_store._conn` to return
    a **real local `sqlite3` connection** (with `row_factory=sqlite3.Row`) on a tmp file whose
    `report_blobs (key TEXT PRIMARY KEY, data BLOB, created_at TEXT)` table was created — this validates
    the INSERT/SELECT/DELETE SQL offline. Tests:
    - **AC-1:** `_use_turso()` is False when `TURSO_DATABASE_URL==""` (disk) and True when set (monkeypatch
      `blob_store._config.TURSO_DATABASE_URL`).
    - **AC-3 (disk):** under `tmp_path`, `write(key,b)` then `read(key)==b`; `exists` True/False; `read`
      of a missing key → `BlobNotFound`; `delete` removes it; `materialize([k])` yields `{k: Path(k)}`
      (the real path).
    - **AC-3 (turso, via local sqlite):** same round-trip through the monkeypatched `_conn`; a re-`write`
      of the same key upserts (ON CONFLICT); `materialize([k1,k2])` yields tempfiles whose bytes match and
      that are **gone after the `with` block**, with basenames preserved (so `.with_suffix('.pdf')` works).
1.2 Run → **FAIL** (module absent).

## T2 — (IMPL) `app/blob_store.py` — AC-1, AC-3
2.1 Create per plan §1–§2: top-level `app/blob_store.py`; `import app.config as _config` at top;
    `BlobNotFound`; `_use_turso()`; `_conn()` with a **lazy** `from app.runner import db_backend` (avoids
    the runner package-init cycle from the report_agent node); `write`/`read`/`exists`/`delete` (disk vs
    Turso `report_blobs`, ON CONFLICT upsert, `row["data"]` via the 051 `_Row`, `bytes(...)`);
    `materialize()` context manager (disk → real paths; Turso → one `TemporaryDirectory` with
    basename-preserving tempfiles, cleaned on exit). Per-op connection open/close.
2.2 Run `test_blob_store.py` → **green**.

## T3 — (TEST FIRST) migration 0009 — AC-7
3.1 Create `tests/integration/test_migration_0009.py` (mirror `test_migration_0007.py`): apply Alembic to
    `head` on a tmp SQLite, assert a `report_blobs` table exists with columns `key`/`data`/`created_at`,
    and that revision `0009` has `down_revision == "0008"`.
3.2 Run → **FAIL** (revision 0009 absent).

## T4 — (IMPL) `alembic/versions/0009_report_blobs.py` — AC-7
4.1 Create per plan §4: `revision="0009"`, `down_revision="0008"`; `upgrade` = `op.create_table
    ("report_blobs", key TEXT PK, data LargeBinary NOT NULL, created_at TEXT NOT NULL)`; `downgrade` =
    `op.drop_table`. Plain SQLAlchemy DDL.
4.2 **Update the two hardcoded Alembic head-pin assertions** that adding `0009` necessarily breaks (a
    lockstep head-fact update, NOT a weakening — like T8's 404-message change):
    - `tests/integration/test_alembic_head.py::test_current_head_is_0008` (asserts head == `"0008"`)
    - `tests/integration/test_migration_0007.py::test_head_is_0008` (asserts head == `"0008"`)
    Change both assertions to `"0009"` and rename the functions/docstrings accordingly.
4.3 Run `test_migration_0009.py` + `tests/integration/test_alembic_head.py` +
    `tests/integration/test_migration_0007.py` (full upgrade still applies to the new head) → **green**.

## T5 — (TEST FIRST) report_agent write via blob_store — AC-4
5.1 In `tests/unit/test_report_agent.py`, add: `report_agent` persists `.json` then `.md` via
    `blob_store.write` (patch `app.graph.nodes.report_agent.blob_store.write` with a spy; assert both keys
    written, JSON-first ordering, and `report_path` == the `.md` key). Confirm the existing report_agent
    tests still assert their behavior (AC-2) — they run on the disk backend (real files) unchanged.
5.2 Run → **FAIL** (report_agent still uses `write_text`).

## T6 — (IMPL) report_agent — AC-4
6.1 In `app/graph/nodes/report_agent.py`: `from app import blob_store`; replace the two `Path.write_text`
    calls with `blob_store.write(str(json_path), json_text.encode("utf-8"))` /
    `blob_store.write(str(md_path), md_text.encode("utf-8"))`; drop the explicit `out_dir.mkdir` (the disk
    backend `write` mkdirs); keep `report_path = str(md_path)`. **Broaden the write-block
    `except (OSError, ValidationError)` to `except Exception as exc:`** so a Turso write error takes the
    same degrade branch (`error_count:1`, `report_path=None`).
6.2 Run `test_report_agent.py` + `tests/integration/test_report_graph.py` → **green**.

## T7 — (TEST FIRST) download endpoint via blob_store — AC-5
7.1 In `tests/integration/test_api_report.py`, add: the report download returns bytes via
    `blob_store.read` (patch it), a missing blob → **404**, an incomplete job → **409** (unchanged),
    `format=json` → the json bytes with `application/json`. The **existing** download tests pass
    unchanged on the disk backend (AC-2).
7.2 Run → **FAIL** (endpoint still `FileResponse`/`target.exists()`).

## T8 — (IMPL) download endpoint — AC-5
8.1 In `app/api/routes.py` download endpoint: keep the 409 branch; replace `target.exists()`→404 +
    `FileResponse` with `blob_store.exists(str(target))`→404 + `Response(content=blob_store.read(...),
    media_type=…)`. Add `from fastapi import Response`; **remove the now-unused `FileResponse` import**.
    Change the 404 detail to `"Report file not found"` (drop "on disk"); **update any test asserting the
    old message** in lockstep.
8.2 Run `test_api_report.py` → **green**.

## T9 — (TEST FIRST) delivery materialize + cleanup — AC-6
9.1 In `tests/unit/test_delivery_step.py` (and/or `tests/integration/test_delivery_integration.py`), add:
    on the Turso backend (monkeypatch `blob_store._conn` to local sqlite + seed a report), `delivery_step`
    gates on `blob_store.exists`, materializes md/json to tempfiles, renders the PDF into that set, the MCP
    attach (mocked) receives file paths, and **every tempfile is unlinked after delivery AND after a
    simulated mid-delivery exception** (assert the tempdir is gone / no leak). Existing delivery tests pass
    unchanged on the disk backend (AC-2).
9.2 Run → **FAIL** (delivery still uses `md_path.exists()` + real paths only).

## T10 — (IMPL) delivery_step — AC-6
10.1 In `app/delivery/delivery_step.py`: replace `if not md_path.exists()` with
     `if not blob_store.exists(str(md_path))`; wrap the report-consuming body in
     `with blob_store.materialize([str(md_path), str(json_path)]) as _paths:` and rebind
     `md_path=_paths[str(md_path)]`, `json_path=_paths[str(json_path)]` so `_load_summary`/`_load_report`,
     `pdf_path = md_path.with_suffix(".pdf")` + `render_report_pdf`, and the MCP attach all use the
     materialized paths (real on disk → byte-identical; tempfiles on Turso → cleaned up). Keep the
     OAuth-token tempfile `finally` cleanup nested inside. `from app import blob_store`.
10.2 Run `test_delivery_step.py` + `tests/integration/test_delivery_integration.py` → **green**.

## T11 — Full suite + diff-scope + lint — AC-8, AC-2
11.1 `python -m pytest -q` → whole suite **green** (AC-2: existing report/download/delivery *behavioral*
     suites pass unchanged on the disk backend; the only edits to existing tests are the two Alembic
     head-pin assertions → `"0009"` (T4.2) and any literal 404-message assertion (T8) — lockstep facts,
     not behavior changes).
11.2 `ruff check` clean on the touched files (pre-existing `config.py` E402 excluded; no dead
     `FileResponse` import left). `black` not enforced (match surrounding style).
11.3 `git diff --name-only <branch-point>` == plan §0 allow-list: `app/blob_store.py` (NEW),
     `app/graph/nodes/report_agent.py`, `app/api/routes.py`, `app/delivery/delivery_step.py`,
     `alembic/versions/0009_report_blobs.py` (NEW), the tests (incl. the two head-pin updates in
     `test_alembic_head.py` + `test_migration_0007.py`), `specs/052-**`. **No** `app/config.py`,
     graph/edge/`ContractState`/upload-path change; `OLLAMA_MODEL_NAME` unchanged.

## T12 — Merge (git-finish) — deferred: AC-9 (Linux)
12.1 T11 green + diff clean + `OLLAMA_MODEL_NAME` reverted. Rebase branch point, merge
     `feature/052-turso-blob-storage`, delete branch (still stacked on the unmerged 048→051 chain).
     Re-apply local qwen3:4b after.
12.2 **AC-9 (post-merge, LINUX only — NOT a merge blocker):** against the real Turso DB (per 051):
     `alembic upgrade head` creates `report_blobs`; generate a report → confirm the `.json`/`.md` BLOBs
     are in Turso (not disk); **restart** the backend and confirm the report downloads; a delivery run
     attaches md/json/pdf and leaves no temp. Add the report-durability note to `docs/DEPLOYMENT.md`
     (out of the gated diff). Record a `RESULTS.md`.

---

### Notes for the implementation model
- `blob_store` reads config via `_config.TURSO_DATABASE_URL` at call time; `db_backend` is imported
  **lazily** inside `_conn()` (never at module top — that would trigger the `app.runner` package init and
  a cycle when the `report_agent` node imports `blob_store`).
- Keys are the existing report path strings; `report_path` stays the `.md` key. No `ContractState` change.
- On the disk backend `materialize` yields the real `REPORT_OUTPUT_DIR` paths (no copy, no cleanup) →
  delivery/report behavior is byte-identical; only the Turso path adds tempfiles.
- Do not touch the upload path, `db_backend.py`, `persistence.py`, or any graph node besides
  `report_agent`.
