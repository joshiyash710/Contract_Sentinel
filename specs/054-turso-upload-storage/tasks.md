# Feature 054 — Tasks: Durable uploaded-contract storage (Turso blob store)

Branch: `feature/054-turso-upload-storage`. Derived from the spec-reviewer-APPROVED `spec.md` + `plan.md`.
TDD per constitution §7: write failing tests first, then implement to green. Offline-Turso technique =
force `TURSO_DATABASE_URL` + point `JOB_STORE_DB_PATH` at a temp sqlite migrated via `upgrade_to_head`
(so `upload_blobs`/`report_blobs` exist), exactly as 052 exercised the Turso branch. All Windows-runnable.

**⚠ Before ANY commit:** verify no local `OLLAMA_MODEL_NAME` qwen3:4b override lingers (would fail
`test_config`); this feature touches NO config defaults, so the suite should otherwise be clean.

---

## T1 — Migration `0010_upload_blobs` (AC-8)  [RED→GREEN]
- **T1.1 (test, red):** `tests/unit/test_migration_0010.py` — on a temp DB, `upgrade_to_head` yields an
  `upload_blobs` table with `key` TEXT PK, `data` BLOB NOT NULL, `created_at` TEXT; `alembic downgrade -1`
  (or `command.downgrade` to `0009`) drops it; assert current head == `"0010"`.
- **T1.2 (impl):** add `backend/alembic/versions/0010_upload_blobs.py` mirroring `0009_report_blobs.py`'s
  full typed structure (plan §1), `down_revision="0009"`.
- **T1.3 (head-pin bumps):** in `tests/integration/` set `"0009"→"0010"` in `test_alembic_head.py`
  (and rename fn `test_current_head_is_0009`→`test_current_head_is_0010`), `test_migration_0007.py`,
  `test_migration_0009.py`. Do NOT touch the `down_revision == "0008"` assertion in `test_migration_0009.py`
  nor `tests/unit/test_migrations.py` (symbolic `"head"`).

## T2 — `blob_store` `table=` parameter (AC-1/2/4 enabler, AC-7 non-regression)  [RED→GREEN]
- **T2.1 (test, red):** extend `tests/unit/test_blob_store.py` — with the Turso branch (monkeypatched local
  sqlite having both tables): `write/read/exists/delete(key, table="upload_blobs")` round-trips and is
  ISOLATED from `report_blobs` (a key written to one is absent from the other); `_tbl("bogus")` →
  `ValueError`; **default (no `table=`) still targets `report_blobs`** (existing 052 assertions unchanged).
- **T2.2 (impl):** add keyword-only `table: str = "report_blobs"` + `_ALLOWED_TABLES`/`_tbl()` guard to
  `write/read/exists/delete`; interpolate `_tbl(table)` into the Turso SQL. Leave `materialize` and the disk
  branch untouched (plan §2).

## T3 — Upload persistence in `routes.py` (AC-1, AC-7)  [RED→GREEN]
- **T3.1 (test, red):** `tests/unit/test_upload_blob_persist.py` — drive the analyze/upload route (or the
  extracted save path) under (a) Turso set → after the call, `blob_store.exists(document_path,
  table="upload_blobs")` is True and the stored bytes == the on-disk finalized bytes (ciphertext when 036
  on); (b) Turso unset → NO `upload_blobs` row is written and the disk file is written exactly as pre-054
  (parity). Also assert a `blob_store.write` failure under Turso → HTTP 500 and no half-durable job (EC-5).
- **T3.2 (impl):** insert the plan §3 block after the 036 encrypt finalizes `dest_path`, before building
  `JobRecord`; gated on `_cfg.TURSO_DATABASE_URL`; on failure unlink the temp + raise 500. No walrus.

## T4 — Ingest read-through in `_materialize_plaintext` (AC-2, AC-5, AC-6, AC-7)  [RED→GREEN]
- **T4.1 (test, red):** `tests/unit/test_ingest_blob_source.py` —
  - **AC-2:** write an encrypted `upload_blobs` blob for `dp`, ensure `not os.path.exists(dp)` (disk gone),
    call `_materialize_plaintext(dp, ext)` → returns a temp path that decrypts to the original bytes.
  - **AC-5:** plaintext blob + encryption ON (Turso) → `InvalidToken` path still materializes correct bytes.
  - **AC-6:** no blob for `dp` (Turso) → `_materialize_plaintext` raises `FileNotFoundError`, and
    `ingest_agent(state)` returns `error_type == "corrupted_file"` and a terminal error dict.
  - **AC-7 (disk parity):** with Turso unset — (enc off) → `(document_path, False)`; (enc on, ciphertext) →
    temp; (enc on, legacy plaintext) → `(document_path, False)` in place. (The pre-existing
    `test_ingest_legacy_plaintext_still_parses` must also stay green.)
- **T4.2 (impl):** replace `_materialize_plaintext` body with the plan §4 revision (turso gate; blob read +
  `BlobNotFound`→`FileNotFoundError`; disk `InvalidToken`→in-place return preserved). No change to the
  `ingest_agent` node body (its `except OSError`→`corrupted_file` already maps the wrapped error).

## T5 — Terminal upload-blob delete in `registry.mark_terminal` (AC-4)  [RED→GREEN]
- **T5.1 (test, red):** extend `tests/unit/test_registry_writethrough.py` — under Turso, a job driven to a
  terminal state calls `blob_store.delete(document_path, table="upload_blobs")` (assert the row is gone);
  a monkeypatched `blob_store.delete` that RAISES does not change the persisted terminal status (AC-4 guard).
- **T5.2 (impl):** add module `logger` + `import app.config as _config` to `registry.py` if missing; in
  `mark_terminal`, after `self._persist()`, best-effort `blob_store.delete(self.document_path,
  table="upload_blobs")` gated on `_config.TURSO_DATABASE_URL and self.document_path`, wrapped in
  try/except→`logger.debug`. (Reviewer non-blocking: may capture `document_path` and delete just after the
  `with self._lock` block to keep I/O off the lock — either satisfies AC-4.)

## T6 — Resume-from-blob integration (AC-3)  [RED→GREEN]
- **T6.1 (test, red):** `tests/integration/test_recover_from_blob.py` — seed a NON-terminal job whose source
  exists ONLY as an `upload_blobs` blob (no disk file); boot the app with recovery enabled + Turso set;
  poll `/api/jobs/{id}` until terminal. The fake/real graph MUST call the real `_materialize_plaintext` so
  the blob read is genuinely exercised (do NOT reuse the fully-faked `_fake_build_graph` verbatim — plan §6
  warning). Assert the job reaches `completed`/`failed` via the blob (not stuck, not `corrupted_file`).

## T7 — Full suite + hygiene (AC-9, AC-10)
- **T7.1:** run whole `pytest` (unit + integration) on Windows → green; the `blob_store` default-`table`
  keeps every 052 test untouched.
- **T7.2:** grep the diff — no `TURSO_AUTH_TOKEN` and no raw upload bytes logged (AC-9); diff ⊆ plan §0
  allow-list; ruff clean; `OLLAMA_MODEL_NAME` not locally overridden.

## T8 — Commit + merge (plan §8)
- Commit on `feature/054-turso-upload-storage` (`feat(054): durable uploaded-contract storage in Turso`).
- git-finish to `main` (the branch Render tracks). AC live-validation (restart mid-job survives) is
  operator-run on Render post-merge; record in `docs/DEPLOYMENT.md`. Closes the last ephemeral-disk seam.

---

### AC → task map
AC-1 T3 · AC-2 T4 · AC-3 T6 · AC-4 T5 · AC-5 T4 · AC-6 T4 · AC-7 T3+T4 · AC-8 T1 · AC-9 T7 · AC-10 T7
