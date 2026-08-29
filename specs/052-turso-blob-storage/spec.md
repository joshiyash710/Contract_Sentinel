# Feature 052 — Report blob storage (Turso BLOBs; local disk default)

Branch: `feature/052-turso-blob-storage` (per constitution §11).

## 1. Problem statement

Generated reports are written to the `REPORT_OUTPUT_DIR` (`data/reports/`) filesystem: `report_agent`
writes a `.json` sibling and a `.md` (`report_path = str(md_path)`), and `delivery_step` renders a `.pdf`
(`md_path.with_suffix(".pdf")`) for the Gmail/Drive MCP attach. The download endpoint
(`GET …/report`) serves the **`.md`/`.json`** by path via `FileResponse`.

On **Render's free tier the disk is ephemeral** — those report files are wiped on every restart. After
feature 051 the *job records* are durable in Turso, so a user's history survives a restart but every
`report_path` then points at a **vanished file** (the download 404s). This feature stores the durable
report artifacts (`.json` + `.md`) in **Turso** (BLOBs in a new `report_blobs` table) so downloads
survive restarts, keeping **local disk as the default** (byte-identical when `TURSO_DATABASE_URL` is
unset). Per the scope decision (2026-08-29), **uploads are out of scope** — they are consumed once by
the ingest node and **never re-served** (only `report_path` is served, `routes.py:303`), so they carry
no post-run durability requirement (consistent with 051's already-ephemeral checkpointer).

### Position relative to the constitution
No LangGraph node/edge change. **No `ContractState` change** — `report_path` (and the `.json`/`.pdf`
siblings derived from it) stay **path-like reference strings** (constitution §6: large content by
reference, never in state); this feature only changes *where the bytes behind those references live*.
It **adds one additive Alembic migration** (`0009`, the `report_blobs` table) — a schema addition, not a
`ContractState`/§10 change. §3 the backend selection is a named config constant. Reversible: without
`TURSO_DATABASE_URL` the report bytes live on disk exactly as today. Developed on
`feature/052-turso-blob-storage` (stacked on 051).

### Privacy / data-egress posture
With Turso configured, report **content** (clause text, findings, rationale — the same material already
sent to Groq under 046 when `LLM_PROVIDER=groq`) is stored in Turso (a third-party managed DB) over TLS.
This is the same opt-in posture as 046/050/051: OFF by default (no `TURSO_DATABASE_URL` ⇒ fully local);
reports contain no auth tokens/keys/PII beyond the contract content; `TURSO_AUTH_TOKEN` never logged
(inherited from 051). Report-file encryption at rest remains **Phase-2-DEFERRED** (as today on disk) —
this feature relocates the bytes, it does not change their encryption posture.

## 2. Inputs and outputs

No `ContractState` input/output change. The report reference strings are unchanged; only the storage of
the bytes moves.

### 2.1 New config (§3, env-overridable)
- The backend is selected by the **existing `TURSO_DATABASE_URL`** (feature 051): set ⇒ report bytes go
  to Turso; unset (default) ⇒ local disk, byte-identical. (No separate flag — reports and stores share
  one durability switch; see Open Question 3.)

### 2.2 New module — `app/delivery/blob_store.py` (or `app/runner/blob_store.py`)
A small storage seam keyed by the existing path strings:
- `write(key: str, data: bytes) -> None`
- `read(key: str) -> bytes` (raises a `BlobNotFound` on a missing key)
- `exists(key: str) -> bool`
- `delete(key: str) -> None`
- `materialize(keys) -> context manager yielding `{ext: local_path}`` — for the MCP delivery, which
  attaches **by file path**. On the **local** backend it yields the real disk paths (no copy); on the
  **Turso** backend it writes the blobs to tempfiles and unlinks them on exit.

Backends:
- **local** (`TURSO_DATABASE_URL` unset) → reads/writes files under `REPORT_OUTPUT_DIR`, byte-identical
  to today (`write_text`/`read`/`FileResponse` semantics preserved).
- **turso** → BLOBs in the `report_blobs` table via the feature-051 `db_backend.connect()` libsql
  connection (`key TEXT PRIMARY KEY`, `data BLOB`).

### 2.3 New Alembic migration — `0009_report_blobs`
Additive: `CREATE TABLE report_blobs (key TEXT PRIMARY KEY, data BLOB NOT NULL, created_at TEXT NOT
NULL)`. Down-revision `0008`. Plain SQLAlchemy DDL so it replays on libSQL (like 051's migrations). It
runs on both backends (the local SQLite table simply stays empty, since the local blob backend uses
disk).

### 2.4 Wire-in (the report read/write sites)
- **`report_agent`** — write the `.json` and `.md` via `blob_store.write(json_key, …)` /
  `write(md_key, …)` instead of `Path.write_text`. `report_path` stays the `.md` key string.
- **Download endpoint (`routes.py`)** — read the requested `.md`/`.json` via `blob_store.read(key)` and
  return a `Response(content=bytes, media_type=…)` instead of `FileResponse(path)`; a missing blob →
  the existing 404.
- **`delivery_step`** — route **every** report read through the store on the Turso backend, not only the
  attach: it also **reads the json** to build the summary/report (`_load_summary`/`_load_report`) and
  **gates on `md_path.exists()`** before delivering. Use `blob_store.materialize({"md":…, "json":…})` to
  get local paths for the MCP attach (which attaches **by path**), render the PDF into that same tempdir
  (`render_report_pdf(report, <tempdir>/…pdf)`), attach, and clean up. On the Turso backend the
  `exists()` gate must consult the store (`blob_store.exists`) — else delivery would `.exists()`-skip a
  Turso-only report. The PDF is **not** persisted (it is regenerated each delivery and never re-served —
  the download endpoint doesn't serve PDF), so it needs no blob storage.

### 2.5 Output
No new state field or schema-of-report change. With `TURSO_DATABASE_URL` set, report `.json`/`.md` bytes
live in Turso and survive a Render restart; the download endpoint serves them; delivery still attaches
md/json/pdf. Graph, edges, and the report content are unchanged.

## 3. Resolved decisions (inline)
- **D1 — Default local disk** (no `TURSO_DATABASE_URL`) ⇒ byte-for-byte today. Reversible.
- **D2 — Keys are the existing path strings** (`report_path` and its `.json`/`.pdf` siblings) ⇒ no
  `ContractState` change, no report-model change.
- **D3 — PDF stays delivery-local** (tempfile on Turso, disk on local) — it is regenerated each delivery
  and never re-served, so it is not a durable artifact.
- **D4 — Reports share 051's `TURSO_DATABASE_URL` switch** — one durability config for the deploy; no
  separate flag (Open Question 3 records the alternative).
- **D5 — `report_blobs` in the same Turso DB** as the 051 stores (5 GB free tier is ample); created by
  the additive migration `0009`, keyed by the path string.
- **D6 — `materialize()` context manager** unifies the local (real paths) and Turso (tempfiles) delivery
  read, with guaranteed tempfile cleanup (mirrors ingest's decrypt-to-tempfile discipline).

## 4. Acceptance criteria

### Backend (pytest — libsql/Turso MOCKED or a local-SQLite `report_blobs`; no network)
- **AC-1 (backend dispatch):** the blob store uses the disk backend when `TURSO_DATABASE_URL==""` and the
  Turso backend when set (libsql mocked).
- **AC-2 (default byte-identical):** with `TURSO_DATABASE_URL==""`, the existing `report_agent`,
  download-endpoint, and `delivery_step` tests pass **unchanged** (reports still on disk; `FileResponse`
  equivalent bytes).
- **AC-3 (blob round-trip):** `write(key, data)` then `read(key)` returns `data` on both backends;
  `exists` is True/False correctly; `read` of a missing key raises `BlobNotFound`; `delete` removes it.
  The Turso backend round-trips through a real local-SQLite `report_blobs` table (proving the SQL) with
  libsql mocked, or via the wrapper.
- **AC-4 (report_agent writes via the store):** `report_agent` persists `.json` + `.md` through
  `blob_store.write` (spy), and `report_path` is still the `.md` key.
- **AC-5 (download reads via the store):** the download endpoint returns the report bytes via
  `blob_store.read`; a missing blob → 404; `format=json` returns the json bytes with
  `application/json`.
- **AC-6 (delivery materialize + cleanup):** `delivery_step` obtains local paths via
  `blob_store.materialize`, the PDF is rendered into the materialized set, the MCP attach receives file
  paths, and on the Turso backend every tempfile created is unlinked (even on a delivery error) — no
  temp leak.
- **AC-7 (config/migration validity):** `test_config`/migration tests assert the backend selection and
  that migration `0009` defines `report_blobs` with the expected columns; the down-revision is `0008`.
- **AC-8 (no architecture change):** `git diff` touches only the blob-store module (NEW), `report_agent`,
  `routes.py` (download), `delivery_step`, the new migration `0009`, config, the tests, and
  `specs/052-**`. **No** graph/edge/`ContractState` change; no upload-path change; whole `pytest` green.

### Live (AC-9 — Linux/Turso, deferred from the merge gate)
- **AC-9:** against a real Turso DB (Linux, per 051): `alembic upgrade head` creates `report_blobs`;
  generate a report → confirm the `.json`/`.md` BLOBs are in Turso; **restart** the backend and confirm
  the report still downloads; a delivery run attaches md/json/pdf. Record a `RESULTS.md`.

## 5. Edge cases
- **EC-1 — blob missing on read** (download of a report whose blob was never written / pruned): the
  existing **404** ("Report file not found") path, not a 500. This is distinct from the **409**
  ("Report not yet available") branch for an incomplete job / absent `report_path` — both branches must
  be preserved (409 = not-ready, 404 = ready-but-blob-missing).
- **EC-2 — Turso BLOB size limit:** libSQL/Turso caps row size. `.json`/`.md` are small (KB); the PDF is
  never stored. Probed in the plan (Open Question 2); a write that exceeds the cap must fail loudly
  (delivery/report degrades honestly), not silently truncate.
- **EC-3 — tempfile cleanup on delivery failure (Turso):** `materialize()` must unlink every tempfile in
  a `finally`, including on a mid-delivery exception (mirrors ingest EC handling / feature 036).
- **EC-4 — partial write ordering:** `report_agent` writes json then md (AC-19a ordering preserved) —
  the store must not reorder in a way that leaves `report_path` (md) present without its json sibling.
- **EC-5 — local backend unchanged:** the disk backend must preserve `REPORT_OUTPUT_DIR` mkdir, encoding
  (utf-8), and the `FileResponse`-equivalent media types.
- **EC-6 — migration `0009` replay on Turso** (a libSQL rejection of the DDL): surfaced by
  `upgrade_to_head` (Linux, AC-9), like 051's migrations.

## 6. Out of scope
- **Uploaded-contract durability** — uploads are transient/never re-served; they stay on ephemeral disk
  (a documented limitation: a job whose upload is lost to a restart before ingest cannot run — already
  the case with 051's ephemeral checkpointer). A future feature could add it if the product exposes
  original-contract re-download.
- **Report encryption at rest** — remains Phase-2-DEFERRED (unchanged on disk today; unchanged in Turso).
- **Deploy wiring** (`render.yaml`, keep-alive, resume-on-boot) — feature 053.
- **Object storage (R2/S3)** as an alternative to Turso BLOBs (Open Question 2 fallback if size limits
  bite) — not built here.
- Streaming large downloads; multi-part blobs; a durable PDF.

## 7. Open questions
1. **`materialize()` for the local backend** — yield the real `REPORT_OUTPUT_DIR` paths directly (zero
   copy, but delivery then unlinks nothing) vs always copy to a tempdir (uniform cleanup). Plan decides;
   leaning "local yields real paths, Turso yields tempfiles," with cleanup a no-op on local.
2. **Turso BLOB row-size limit for reports** — confirm `.json`/`.md` (and headroom) fit libSQL's max row
   size via a plan-phase probe against the real Turso DB (low risk — KB-sized). If a large report ever
   exceeds it, fall back to chunking or external object storage (out of scope here).
3. **Gate on `TURSO_DATABASE_URL` vs a separate `REPORT_STORAGE_BACKEND` flag** — D4 reuses 051's switch
   for one deploy config; a separate flag would allow disk-reports-with-Turso-stores. Recommend reuse
   (simpler); confirm.
4. **Migration `0009` replay on Turso** — validated only in Linux (AC-9), like 051's migrations.
5. **Module location** — `app/delivery/blob_store.py` (near delivery/report I/O) vs
   `app/runner/blob_store.py` (near `db_backend`). Plan decides; it depends on `db_backend` for the
   Turso backend either way.
