# Feature 052 — Technical plan: Report blob storage (Turso BLOBs; local disk default)

Branch: `feature/052-turso-blob-storage` (per constitution §11).

Derived from `spec.md` (spec-reviewer-APPROVED). Stores the durable report artifacts (`.json` + `.md`)
in Turso when `TURSO_DATABASE_URL` is set (feature 051's switch), behind a `blob_store` seam keyed by the
existing report path strings; local disk stays the default (byte-identical). The PDF stays a
delivery-local tempfile. **No `ContractState` change; one additive migration (`0009`).**

## 0. Scope of change (files touched)
`git diff` (vs the branch point) must show only:
```
backend/app/blob_store.py                          (NEW — write/read/exists/delete/materialize; 2 backends)
backend/app/graph/nodes/report_agent.py            (write .json/.md via blob_store)
backend/app/api/routes.py                          (download: read via blob_store → Response(bytes))
backend/app/delivery/delivery_step.py              (exists()+materialize()+attach via blob_store)
backend/alembic/versions/0009_report_blobs.py      (NEW — report_blobs table; down_revision 0008)
backend/tests/unit/test_blob_store.py              (NEW)
backend/tests/unit/test_report_agent*.py           (AC-4, extend)
backend/tests/unit/test_routes*.py / report download (AC-5, extend)
backend/tests/unit/test_delivery*.py               (AC-6, extend)
backend/tests/unit/test_migrations_0009.py         (AC-7; or extend test_migrations)
specs/052-turso-blob-storage/{spec,plan,tasks}.md
```
- **No `app/config.py` change** — reuses the existing `TURSO_DATABASE_URL` (OQ3 → reuse 051's switch).
- **No `ContractState`/graph/edge/upload-path change.** `report_path` stays the `.md` key string.
- **⚠ Revert any local `OLLAMA_MODEL_NAME` qwen3:4b→qwen3:8b override before committing.**

## 1. Module location + circular-import safety
`blob_store` lives at **`app/blob_store.py`** (top-level; `app/__init__.py` is empty), NOT under
`app/runner/`. Reason: `app/runner/__init__.py` eagerly imports `core → builder → nodes → report_agent`,
so a **node** (`report_agent`) importing `from app.runner import …` risks a partial-init cycle. `blob_store`
imports only `app.config` at module top and imports `db_backend` **lazily inside the Turso branch**
(`from app.runner import db_backend` at call time), so importing `blob_store` from the node pulls no
runner package-init. Consumers import `from app import blob_store`.

## 2. The `blob_store` seam (NEW `app/blob_store.py`)
```python
"""Report artifact storage (feature 052). Default: local disk under REPORT_OUTPUT_DIR (byte-identical).
When TURSO_DATABASE_URL is set: BLOBs in the Turso `report_blobs` table (via feature-051 db_backend).
Keys are the existing report path strings (report_path + its .json/.pdf siblings), so no ContractState
change. TURSO_AUTH_TOKEN never logged (inherited from db_backend)."""
import os, tempfile, datetime
from contextlib import contextmanager
from pathlib import Path
import app.config as _config


class BlobNotFound(Exception):
    pass


def _use_turso() -> bool:
    return bool(_config.TURSO_DATABASE_URL)


def _conn():
    from app.runner import db_backend       # lazy — avoids the runner package-init cycle from nodes
    return db_backend.connect(_config.JOB_STORE_DB_PATH)   # Turso when TURSO_DATABASE_URL set


def write(key: str, data: bytes) -> None:
    if _use_turso():
        conn = _conn()
        try:
            conn.execute(
                "INSERT INTO report_blobs (key, data, created_at) VALUES (?,?,?) "
                "ON CONFLICT(key) DO UPDATE SET data=excluded.data, created_at=excluded.created_at",
                (key, data, datetime.datetime.utcnow().isoformat()),
            )
            conn.commit()
        finally:
            conn.close()
    else:
        p = Path(key)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)


def read(key: str) -> bytes:
    if _use_turso():
        conn = _conn()
        try:
            row = conn.execute("SELECT data FROM report_blobs WHERE key=?", (key,)).fetchone()
        finally:
            conn.close()
        if row is None:
            raise BlobNotFound(key)
        return bytes(row["data"])          # _Row supports by-name (feature 051 shim)
    p = Path(key)
    if not p.exists():
        raise BlobNotFound(key)
    return p.read_bytes()


def exists(key: str) -> bool:
    if _use_turso():
        conn = _conn()
        try:
            return conn.execute("SELECT 1 FROM report_blobs WHERE key=?", (key,)).fetchone() is not None
        finally:
            conn.close()
    return Path(key).exists()


def delete(key: str) -> None:
    if _use_turso():
        conn = _conn()
        try:
            conn.execute("DELETE FROM report_blobs WHERE key=?", (key,)); conn.commit()
        finally:
            conn.close()
    else:
        Path(key).unlink(missing_ok=True)


@contextmanager
def materialize(keys):
    """Yield {key: local Path} for the given report keys.

    local backend → the real REPORT_OUTPUT_DIR paths (no copy, no cleanup). Turso → each blob written to
    a tempfile in ONE tempdir, preserving basename so `.with_suffix('.pdf')` siblings work; the tempdir
    is removed on exit (even on error).
    """
    keys = list(keys)
    if not _use_turso():
        yield {k: Path(k) for k in keys}
        return
    with tempfile.TemporaryDirectory(prefix="cs_report_") as d:
        out = {}
        for k in keys:
            tp = Path(d) / Path(k).name           # preserve basename+suffix for the PDF sibling
            tp.write_bytes(read(k))
            out[k] = tp
        yield out
```
- **Per-operation connection** (open/close per call) — report I/O is low-frequency (once per job / on
  download), so no cached connection is needed (unlike the job-store hot path).
- `read` uses the feature-051 `_Row` by-name access (`row["data"]`); `bytes(...)` normalizes libsql's
  BLOB return to `bytes`.
- `write` uses `ON CONFLICT` upsert (idempotent re-writes; libsql-proven in the 051 spike).

## 3. Wire-ins
### 3.1 `report_agent` (write) — AC-4
Replace the two `Path.write_text` calls + the `out_dir.mkdir`:
```python
from app import blob_store
blob_store.write(str(json_path), json_text.encode("utf-8"))   # JSON first (AC-19a ordering preserved)
blob_store.write(str(md_path), md_text.encode("utf-8"))       # MD second
report_path = str(md_path)                                    # unchanged key
```
The local backend's `write` does the `mkdir(parents=True)`, so the explicit `out_dir.mkdir` is removed.
**Error handling — broaden the existing write-block `except (OSError, ValidationError)` to
`except Exception as exc:`** so a Turso/libsql write error (a `ValueError`, not an `OSError`) takes the
SAME degrade branch (`error_count:1`, `report_path=None`) — deterministic, matching the current "any
report-write failure degrades" intent. (`BlobNotFound` is a read-only error, never raised on write.)

### 3.2 Download endpoint (`routes.py`) — AC-5
Keep the **409** (incomplete / no `report_path`) branch. Replace the disk read:
```python
key = str(target)                       # target = md_path or md_path.with_suffix(".json")
if not blob_store.exists(key):
    raise HTTPException(status_code=404, detail="Report file not found")
data = blob_store.read(key)
return Response(content=data, media_type=media_type)   # was FileResponse(path)
```
- Add `from fastapi import Response`; **remove the now-unused `FileResponse` import** (it was its only
  use — leaving it is a dead import / lint failure).
- The 404 detail drops the old "on disk" wording (now inaccurate for the Turso path):
  `"Report file not found"` (was `"Report file not found on disk"`). **Update any test asserting the
  exact old message in lockstep** (AC-2's "existing suites unchanged" holds for behavior; a literal
  message-text assertion must be updated).

### 3.3 `delivery_step` — AC-6 (the invasive part)
- Replace the `if not md_path.exists()` gate (line 205) with `if not blob_store.exists(str(md_path))`.
- Wrap the report-consuming body in `blob_store.materialize([str(md_path), str(json_path)])`, rebinding
  the local `md_path`/`json_path` to the yielded paths (real on disk, tempfiles on Turso), so
  `_load_summary(json_path)`, `_load_report(json_path)`, `render_report_pdf(report, pdf_path)` (with
  `pdf_path = md_path.with_suffix(".pdf")` in the materialized dir), and the MCP attach (which takes
  file paths) all work unchanged. On the local backend the yielded paths ARE the real
  `REPORT_OUTPUT_DIR` files → byte-identical (PDF still written next to the md on disk). On Turso the
  tempdir (incl. the rendered PDF) is unlinked on exit, even on a mid-delivery exception (EC-3).
- The existing central/user OAuth-token tempfile handling and its `finally` cleanup are untouched (they
  are nested inside the `materialize` context).

## 4. Migration `0009_report_blobs`
```python
revision = "0009"; down_revision = "0008"
def upgrade():
    op.create_table(
        "report_blobs",
        sa.Column("key", sa.Text(), primary_key=True),
        sa.Column("data", sa.LargeBinary(), nullable=False),
        sa.Column("created_at", sa.Text(), nullable=False),
    )
def downgrade():
    op.drop_table("report_blobs")
```
Plain SQLAlchemy DDL → replays on libSQL (Linux, AC-9), like 051's migrations. Runs on both backends
(the local SQLite table stays empty since the local blob backend uses disk).

## 5. Test plan (TDD, `tests/unit/`) — failing-first per §7; libsql/Turso path tested via a real local SQLite `report_blobs`
- **AC-1 (`test_blob_store.py`):** `_use_turso()` False by default (conftest forces `TURSO_DATABASE_URL=""`) → disk backend; True when set → Turso branch. To exercise the Turso SQL offline, monkeypatch `blob_store._conn` to return a **real local `sqlite3` connection** (with `row_factory=sqlite3.Row`) whose `report_blobs` table was created in a tmp file — this validates the INSERT/SELECT/DELETE SQL without a network (libSQL is SQLite-compatible).
- **AC-3 (round-trip both backends):** disk — `write`/`read`/`exists`/`delete` under `tmp_path`; Turso — the same via the monkeypatched local-sqlite `_conn`; `read` of a missing key → `BlobNotFound`; `materialize` (disk) yields real paths, (Turso) yields tempfiles that contain the blob bytes and are gone after the `with`.
- **AC-4 (report_agent):** writes `.json`+`.md` via `blob_store.write` (spy); `report_path` is still the `.md` key; JSON-first ordering preserved.
- **AC-5 (download):** returns report bytes via `blob_store.read` (patched); missing blob → 404; incomplete job → 409 (unchanged); `format=json` → json bytes + `application/json`.
- **AC-6 (delivery):** `delivery_step` gates on `blob_store.exists`, materializes md/json, renders the PDF into the materialized set, the MCP attach receives file paths; on the Turso backend (monkeypatched) every tempfile is unlinked after delivery **and** after a simulated mid-delivery exception (no temp leak). On the disk backend the existing delivery tests pass unchanged (AC-2).
- **AC-2 (default byte-identical):** the existing `report_agent`, report-download, and `delivery` suites pass **unchanged** on the disk backend.
- **AC-7 (migration):** a test asserts migration `0009` creates `report_blobs(key,data,created_at)` and `down_revision=="0008"` (apply `upgrade` on a tmp sqlite; assert the table + columns).
- **AC-8 (scope):** whole `pytest` green; diff = §0 allow-list; no graph/state/upload/config change; `OLLAMA_MODEL_NAME` unchanged.

All unit tests run on **Windows** (Turso path exercised via local sqlite; libsql not required for the suite). The real-Turso replay/durability is AC-9 (Linux).

## 6. Live validation (AC-9 — Linux/Turso; deferred from the merge gate)
In a Linux env against the real Turso DB (per 051): `alembic upgrade head` creates `report_blobs`;
generate a report → confirm the `.json`/`.md` BLOBs are in Turso (not on disk); **restart** the backend
and confirm the report still downloads; a delivery run attaches md/json/pdf and leaves no temp. Record a
`RESULTS.md`.

## 7. Risks / limitations
- **Delivery refactor** is the invasive change — mitigated by `materialize()` returning real paths on the
  disk backend (byte-identical) so only the Turso path is new; tempfile cleanup guaranteed by the
  context manager's `TemporaryDirectory` (EC-3).
- **Turso BLOB row-size** — `.json`/`.md` are KB-sized; the PDF is never stored. A write that ever
  exceeds libSQL's row cap fails loudly (no silent truncation); external object storage is the documented
  fallback (out of scope). Confirm headroom in the AC-9 probe.
- **Migration `0009` replay on Turso** — validated only in Linux (AC-9), like 051.
- **Per-op Turso connection latency** — acceptable at report frequency (once/job, on download).
- Third-party egress of report content — same opt-in posture as 046/050/051 (OFF by default).

## 8. Merge
Whole `pytest` green (Windows, unit); diff = §0 allow-list; `OLLAMA_MODEL_NAME` reverted. Rebase the
branch point, merge `feature/052-turso-blob-storage` (still stacked on the unmerged 048→051 chain —
merge-order at deploy-phase end), delete branch. AC-9 (Linux replay + restart-survival) + the
`docs/DEPLOYMENT.md` note follow the unit-green merge (like 046/050/051). 053 (deploy wiring) stacks next
and is the last feature of the chain.
