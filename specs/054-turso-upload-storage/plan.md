# Feature 054 — Technical plan: Durable uploaded-contract storage (Turso blob store)

Branch: `feature/054-turso-upload-storage` (constitution §11). Derived from `spec.md`
(spec-reviewer-APPROVED). Folds in the reviewer's non-blocking notes: (1) explicit `BlobNotFound`→ingest
error translation, (2) AC-2 asserts the disk file is absent, (4) `table=` added to
`write/read/exists/delete` only — **not** `materialize` (uploads never use it).

Resume-on-boot already exists (012 `main.py::_recover` → `store.nonterminal()`); this feature adds NO
recovery code — it only makes the source durable so the existing resume can finish. No graph/edge/
`ContractState`/`jobs`-schema change.

## 0. Scope of change (files touched — the allow-list)
```
backend/alembic/versions/0010_upload_blobs.py     (NEW — upload_blobs table, mirrors 0009)
backend/app/blob_store.py                          (add keyword-only table="report_blobs" to write/read/exists/delete)
backend/app/api/routes.py                          (post-encrypt: persist upload bytes to blob_store on Turso)
backend/app/graph/nodes/ingest_agent.py            (_materialize_plaintext: Turso read-through + BlobNotFound→FileNotFoundError)
backend/app/runner/registry.py                     (mark_terminal: best-effort delete upload blob)
backend/tests/unit/test_blob_store.py              (extend — table= param, upload_blobs isolation)
backend/tests/unit/test_migration_0010.py          (NEW — AC-8)
backend/tests/unit/test_upload_blob_persist.py     (NEW — AC-1, AC-7 route parity)
backend/tests/unit/test_ingest_blob_source.py      (NEW — AC-2, AC-5, AC-6 materialize-from-blob)
backend/tests/unit/test_registry_writethrough.py   (extend — AC-4 terminal-delete)
backend/tests/integration/test_recover_from_blob.py(NEW — AC-3 resume-from-blob)
backend/tests/integration/test_alembic_head.py     (bump head-pin 0009→0010 + rename fn ...is_0010, AC-8)
backend/tests/integration/test_migration_0007.py   (bump head-pin 0009→0010, AC-8)
backend/tests/integration/test_migration_0009.py   (bump head-pin 0009→0010, AC-8)
specs/054-turso-upload-storage/{spec,plan,tasks}.md
```
- **No config-default change** → avoids the `OLLAMA_MODEL_NAME` config-test gotcha; reversibility is the
  existing `TURSO_DATABASE_URL` gate (mirrors 052). **⚠ Verify no local `OLLAMA_MODEL_NAME` qwen3:4b
  override before committing.**
- **Head-pin bumps (reviewer-corrected):** the three `get_current_head() == "0009"` assertions are ALL in
  `tests/integration/` — `test_alembic_head.py` (also rename `test_current_head_is_0009`→`_is_0010`),
  `test_migration_0007.py`, and `test_migration_0009.py`. All mechanical `0009→0010`. `tests/unit/
  test_migrations.py` uses the symbolic `"head"` → **no change**.

## 1. Migration `0010_upload_blobs.py` (mirror 0009 EXACTLY)
Mirror `0009_report_blobs.py`'s full structure — typed module vars + imports + `-> None` signatures (not
the abbreviated form):
```python
from typing import Sequence, Union
import sqlalchemy as sa
from alembic import op

revision: str = "0010"
down_revision: Union[str, None] = "0009"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

def upgrade() -> None:
    op.create_table(
        "upload_blobs",
        sa.Column("key", sa.Text, primary_key=True),
        sa.Column("data", sa.LargeBinary, nullable=False),
        sa.Column("created_at", sa.Text, nullable=False),
    )

def downgrade() -> None:
    op.drop_table("upload_blobs")
```
Additive; disk backend leaves it empty. Head-pin tests move `0009 → 0010` (§0).

## 2. `blob_store.py` — `table=` parameter (backward-compatible)
Add a keyword-only `table: str = "report_blobs"` to `write`, `read`, `exists`, `delete`. Interpolate the
table name into the SQL **from the fixed default or the literal `"upload_blobs"` only** — never from
user/request data (no injection surface; assert-guard the allowed set to be explicit):
```python
_ALLOWED_TABLES = {"report_blobs", "upload_blobs"}
def _tbl(table: str) -> str:
    if table not in _ALLOWED_TABLES:
        raise ValueError(f"unknown blob table {table!r}")
    return table
```
- `write/read/exists/delete` use `f"... {_tbl(table)} ..."`. Every 052 call site omits `table` → unchanged.
- Disk backend ignores `table` (path-keyed files, exactly as today).
- `materialize()` is **not** touched (uploads use `read` only — reviewer note 4).
- `BlobNotFound` unchanged (still raised by `read`).

## 3. `routes.py` — persist the upload (post-encrypt, Turso only)
Immediately after the feature-036 encrypt block finalizes `dest_path` (and before building the
`JobRecord`), add:
```python
# Feature 054: persist the durable source to the blob store so a job resumed after a container
# restart (Render ephemeral disk) can re-read it. Disk backend already has the file → skip.
if _cfg.TURSO_DATABASE_URL:
    try:
        with open(dest_path, "rb") as f:
            _stored = f.read()
        from app import blob_store
        blob_store.write(dest_path, _stored, table="upload_blobs")
        del _stored
    except Exception as exc:  # noqa: BLE001 — do not create a half-durable job (EC-5)
        if os.path.exists(dest_path):
            os.unlink(dest_path)
        _logger.exception("Upload blob persist failed")
        raise HTTPException(status_code=500, detail="Internal error saving upload") from exc
```
- Runs on the **already-encrypted** bytes (blob holds ciphertext when 036 is on; plaintext when off — the
  ingest path handles both). `MAX_UPLOAD_SIZE_BYTES` already bounds the in-memory read (EC-4).
- Failure → 500, consistent with the existing "internal error saving upload" contract (EC-5); the disk temp
  is cleaned so nothing half-durable remains.
- `document_path` stays `dest_path` (the blob key) — no row/state change.

## 4. `ingest_agent._materialize_plaintext` — read-through + error mapping
Today it does `open(document_path, "rb").read()`. Split on the Turso gate so the disk branch is
byte-identical (AC-7) and the Turso branch reads the blob (AC-2):
```python
def _materialize_plaintext(document_path, ext):
    turso = bool(_config.TURSO_DATABASE_URL)
    if not _config.CONTRACT_ENCRYPTION_AT_REST_ENABLED and not turso:
        return document_path, False                     # pre-054 disk fast-path (enc off), unchanged
    from cryptography.fernet import InvalidToken
    from app.security import crypto

    if turso:
        from app import blob_store
        try:
            raw = blob_store.read(document_path, table="upload_blobs")
        except blob_store.BlobNotFound as exc:
            raise FileNotFoundError(str(document_path)) from exc   # → ingest `except OSError` → corrupted_file (AC-6)
    else:
        with open(document_path, "rb") as f:
            raw = f.read()

    if _config.CONTRACT_ENCRYPTION_AT_REST_ENABLED:
        try:
            data = crypto.decrypt_bytes(raw)
        except InvalidToken:
            if not turso:
                return document_path, False             # DISK legacy-plaintext: parse in place (pre-054, AC-7)
            data = raw                                  # TURSO: no disk path → must materialize below (AC-5)
    else:
        data = raw                                      # enc off + Turso only (enc off + disk returned above)

    tmp = tempfile.NamedTemporaryFile(suffix=ext, delete=False)
    try:
        tmp.write(data); tmp.close()
    except Exception:
        tmp.close()
        try: os.unlink(tmp.name)
        except OSError: pass
        raise
    return tmp.name, True
```
- **AC-7 disk byte-identity (reviewer blocking #2 fixed):** (enc off, no Turso) → early `return
  document_path, False`; (enc on, no Turso, valid ciphertext) → decrypt→temp→`(tmp, True)`; (enc on, no
  Turso, legacy plaintext) → `InvalidToken` → `return document_path, False` **in place** — exactly pre-054
  (guards `test_ingest_legacy_plaintext_still_parses`). Only the Turso branch ever materializes a temp on
  `InvalidToken` (no readable disk path there).
- **`BlobNotFound`→`FileNotFoundError`** (reviewer note 1): `FileNotFoundError` IS an `OSError`, caught at
  `ingest_agent.py:124` → `corrupted_file`, so no ingest-node edit (AC-6, EC-3 parity).
- The temp cleanup (`os.unlink(parse_path)` in `ingest_agent`) is unchanged and still fires for the temp.

## 5. `registry.mark_terminal` — best-effort upload-blob delete
After the existing `self._persist()` inside `mark_terminal` (still under `self._lock` is fine; delete is
cheap and off the hot path), add:
```python
# Feature 054: a terminal job is never re-run (012 resume touches only nonterminal rows), so its
# durable source is no longer needed — best-effort delete to bound Turso growth. Never affects outcome.
if _config.TURSO_DATABASE_URL and self.document_path:
    try:
        blob_store.delete(self.document_path, table="upload_blobs")
    except Exception:  # noqa: BLE001
        logger.debug("upload-blob delete skipped", exc_info=True)
```
- `registry.py` already has `from app import blob_store` (line 23) and `self.document_path` (dataclass
  field, line 46), but has **no** module `logger` and **no** `import app.config` (reviewer-confirmed) —
  add both. `blob_store.delete` under `self._lock` is safe: `db_backend` does not import `registry`, so no
  re-entrancy/deadlock.
- Guarded so AC-4's forced-failure case leaves the terminal status intact.

## 6. Test plan (TDD, failing-first; Windows-runnable, Turso path offline)
Reuse 052's offline technique: monkeypatch `blob_store._conn` (or force `TURSO_DATABASE_URL` + point
`JOB_STORE_DB_PATH` at a temp sqlite that has `upload_blobs` via `upgrade_to_head`) so the Turso branch runs
against local sqlite.
- **AC-8 `test_migration_0010`**: `upgrade_to_head` creates `upload_blobs` (columns/PK); `downgrade` drops
  it; head is `0010`. Bump the three integration head-pins `0009→0010` (`test_alembic_head.py` — also
  rename its fn `..._is_0009`→`..._is_0010`; `test_migration_0007.py`; `test_migration_0009.py`).
- **AC-1/AC-7 `test_upload_blob_persist`**: with Turso set, an analyze/upload writes an `upload_blobs` row
  keyed by `document_path` and `blob_store.exists(dp, table="upload_blobs")` is True; with Turso unset, **no**
  `upload_blobs` write occurs and the disk file is written exactly as pre-054.
- **AC-2/AC-5/AC-6 `test_ingest_blob_source`**: (2) write an encrypted blob, **remove the disk file, assert
  `not os.path.exists(dp)`**, call `_materialize_plaintext` → parses (reviewer note 2); (5) plaintext blob
  with encryption on → `InvalidToken` path still materializes; (6) no blob → `_materialize_plaintext` raises
  `FileNotFoundError` and `ingest_agent` returns `corrupted_file`.
- **AC-4 `test_registry_writethrough`**: `mark_terminal` calls `blob_store.delete(dp, table="upload_blobs")`
  under Turso; a monkeypatched `delete` that raises does not change the terminal status.
- **AC-3 `test_recover_from_blob`** (integration): seed a non-terminal job whose source exists **only** as an
  `upload_blobs` blob (no disk file), boot with recovery → job reaches a terminal state via the blob.
  ⚠ The existing `test_recover_missing_upload` harness fully fakes the graph (`_fake_build_graph`), so it
  never calls the real `_materialize_plaintext`. This AC-3 test MUST drive the real ingest read (real graph
  ingest, or a fake whose ingest calls the real `_materialize_plaintext`) so the blob read is genuinely
  exercised — otherwise it's a no-op.
- **AC-10**: whole suite green; `blob_store` default-`table` keeps all 052 tests untouched.

## 7. Risks / limitations
- **Turso growth** — bounded by terminal-delete (§5); 5 GB free, small PDFs.
- **Upload now needs a Turso write** (EC-5) — same dependency class as the DB/report writes; surfaces as the
  existing 500 contract.
- **Reversibility** — unset `TURSO_DATABASE_URL` → pure disk behavior, no data migration.

## 8. Merge
Whole `pytest` green (Windows, unit+integration); diff = §0 allow-list; `OLLAMA_MODEL_NAME` reverted if
locally overridden. Commit on `feature/054-turso-upload-storage`; git-finish to `main` (the deploy branch
Render tracks — repoint Render to `main` is a separate op already pending). AC live-validation (restart mid-
job survives) is operator-run on Render post-merge, recorded in `docs/DEPLOYMENT.md`. This closes the last
ephemeral-disk seam of the Render + Turso deploy ([[project_render_turso_deploy]]).
