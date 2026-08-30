# Feature 054 — Spec: Durable uploaded-contract storage (Turso blob store)

Status: DRAFT (pre spec-reviewer gate)
Branch: `feature/054-turso-upload-storage` (constitution §11)
Depends on: 051 (Turso `db_backend`), 052 (`app/blob_store.py` + `report_blobs`), 012 (resume-on-boot).

## 1. Problem

The uploaded contract is the **last artifact still written only to Render's ephemeral disk**. On upload,
`routes.py` streams the file to `data/uploads/{job_id}{ext}` (Fernet-encrypted at rest, feature 036) and
stores that path as the job's `document_path`. The DB rows (051) and report artifacts (052) already live
in Turso, but the **source upload does not**.

Render free-tier containers recycle constantly — redeploys, OOM at 512 MB, and (absent a keep-alive) the
15-minute idle spin-down. Feature 012's resume-on-boot re-enqueues every non-terminal job on startup, but
when it re-runs the job the ingest step does `open(document_path)` against a disk file that the restart
**already wiped** → `FileNotFoundError` → the job dies with
`[Errno 2] No such file or directory: 'data/uploads/…pdf'` (observed live 2026-08-30).

So today a job only survives if it both starts *and* finishes inside a single container lifetime. Any
restart mid-analysis permanently loses the source and the job fails. This feature closes that seam.

## 2. Goal

Persist the uploaded contract bytes durably (Turso when configured, exactly like reports in 052) so that a
job **resumed after any container restart can re-read its source and complete**. When Turso is not
configured (local dev), behavior is **byte-identical to today** (disk).

## 3. In scope

1. **Upload persistence** — after the existing stream → size-limit → magic-byte → at-rest-encrypt steps in
   `routes.py`, also persist the final stored bytes to the blob store keyed by `document_path`.
2. **Ingest read-through** — `ingest_agent._materialize_plaintext` reads the source bytes from the blob
   store (so a rehydrated job finds its upload) instead of assuming a local disk file.
3. **Terminal cleanup** — when a job reaches a terminal state, best-effort delete its upload blob (reports
   are already persisted; a terminal job is never re-run, so the source is no longer needed).
4. **Storage** — a new `upload_blobs` table (Alembic `0010`, mirrors `report_blobs`), and a small
   `table=` parameter on `blob_store` so uploads and reports use distinct tables.

## 4. Out of scope / non-goals

- **No disk-backend behavior change.** With `TURSO_DATABASE_URL` unset, uploads stay on disk and every
  existing 036/ingest test remains byte-identical (this is the reversibility switch, mirroring 052).
- **No `ContractState` change and no `jobs`-schema change.** `document_path` stays the key/reference; the
  raw bytes never enter graph state (constitution §6).
- **No checkpointer change.** The LangGraph checkpointer stays ephemeral (051 finding); resume re-runs a
  non-terminal job from scratch, which is exactly why the *source* must be durable.
- **No upload de-dup, GC sweep, or retention policy** beyond the terminal-delete in §3.3. (Disk today never
  GCs uploads either; we are not regressing, and terminal-delete keeps Turso from growing unboundedly.)
- **No new secret/provider.** Reuses the 051 `TURSO_DATABASE_URL`/`db_backend`; no config-default change.

## 5. Design (summary; detail in plan.md)

- **`blob_store`**: add a keyword-only `table: str = "report_blobs"` to `write/read/exists/delete` and to
  `materialize`. Default preserves every 052 call site byte-for-byte. Uploads pass `table="upload_blobs"`.
  Disk backend ignores `table` (it is path-keyed files, as today).
- **`routes.py`**: after the `document_path` file is finalized (post-encrypt), if `TURSO_DATABASE_URL` is
  set, read the finalized bytes and `blob_store.write(document_path, data, table="upload_blobs")`. The
  transient disk file may then be wiped by any restart without harm. On the disk backend this call is
  skipped (file already durable-enough locally) → no redundant rewrite.
- **`ingest_agent._materialize_plaintext`**: when `TURSO_DATABASE_URL` is set, obtain the source bytes via
  `blob_store.read(document_path, table="upload_blobs")`, decrypt (or accept legacy plaintext on
  `InvalidToken`), and write them to the existing short-lived temp file for the parser. A missing blob
  (`BlobNotFound`) maps to the same graceful `corrupted_file` ingest error the disk `FileNotFoundError`
  path already produces (EC-3 parity). The disk branch is unchanged.
- **`registry.mark_terminal`**: after persisting the terminal row, best-effort
  `blob_store.delete(document_path, table="upload_blobs")` (guarded so a delete failure never affects the
  job outcome; no-op/None-safe when `document_path` is unset).

## 6. Acceptance criteria

- **AC-1** With `TURSO_DATABASE_URL` set, a successful upload writes the encrypted bytes as an
  `upload_blobs` row keyed by `document_path`; `blob_store.exists(document_path, table="upload_blobs")` is
  True after the analyze call returns.
- **AC-2** With Turso set, `ingest_agent` on a job whose **local disk upload has been removed** (simulating
  a container restart) still parses successfully by reading the blob — proving restart-survival.
- **AC-3** Resume-on-boot parity: a non-terminal job recovered on startup (012) whose source exists only in
  the blob store runs to a terminal state (not stuck, not `corrupted_file`).
- **AC-4** A job reaching a terminal state best-effort deletes its `upload_blobs` row; a delete failure is
  swallowed and does not change the job's terminal status.
- **AC-5** Legacy/plaintext parity: with encryption off (or a pre-036 plaintext blob), the Turso ingest
  path still materializes and parses correctly (`InvalidToken` → treat bytes as plaintext).
- **AC-6** Missing-source parity: with Turso set and **no** blob for `document_path`, ingest returns the
  graceful `corrupted_file` error and the job terminates (mirrors the existing disk EC-3 test).
- **AC-7** Disk-backend byte-identity: with `TURSO_DATABASE_URL` unset, `routes.py` and
  `_materialize_plaintext` take exactly the pre-054 code paths; all existing upload/036/ingest/recover
  tests pass unchanged.
- **AC-8** Migration `0010` creates `upload_blobs` (key TEXT PK, data BLOB NOT NULL, created_at TEXT) with
  a working `downgrade()`; the alembic head-pin tests are updated `0009 → 0010`.
- **AC-9** `TURSO_AUTH_TOKEN` is never logged (inherited from `db_backend`); no raw upload bytes are logged.
- **AC-10** Whole `pytest` suite green on Windows (unit + integration), diff within the plan §0 allow-list.

## 7. Edge cases

- **EC-1** Restart *after upload, before ingest* → blob present, disk gone → resume ingests from blob (AC-2/3).
- **EC-2** Restart *after ingest, mid-pipeline* → job still non-terminal → resume re-runs from scratch
  (ephemeral checkpointer) → re-reads the still-present blob (terminal-delete has not run yet). ✔
- **EC-3** Truly missing source (blob never written / already deleted) → graceful `corrupted_file` (AC-6).
- **EC-4** Very large upload within `MAX_UPLOAD_SIZE_BYTES` → one in-memory read of the finalized file to
  write the blob; bounded by the existing upload-size cap (no new limit needed).
- **EC-5** Blob-store write failure at upload time (Turso down) → surfaces as a 500 on analyze, consistent
  with the existing "internal error saving upload" contract; the job is not created half-durable.

## 8. Risks / limitations

- **Turso storage growth** — mitigated by terminal-delete (§3.3); free tier is 5 GB and contracts are small.
- **Turso free-tier reliability** — an upload now depends on a Turso write (EC-5); acceptable, same
  dependency class the DB/report paths already carry.
- **Reversibility** — unset `TURSO_DATABASE_URL` fully reverts to disk behavior (no data migration needed).

## 9. Testing (TDD — detail in tasks.md)

Failing-first unit + integration tests for AC-1..AC-8, all Windows-runnable with the Turso path exercised
offline via a monkeypatched local-sqlite `upload_blobs` (same technique 052 used for `report_blobs`), plus
the disk-parity assertions (AC-7) and the head-pin bump (AC-8).
