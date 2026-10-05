# Feature 056 — Spec: Serve the original contract (authenticated) + upload retention

Status: DRAFT (pre spec-reviewer gate)
Branch: `feature/056-serve-original-contract` (constitution §11).

> Second of the "Suggestion 1 — clause traceability" chain (**055 locator capture ✅ → 056 serve-original
> → 057 pdf.js viewer**). 056 makes the uploaded PDF retrievable by its owner so 057 can render it and
> draw the 055 highlights. API + persistence only; renders nothing.

## 1. Problem statement

The 057 viewer must display the **original uploaded PDF** in the browser to draw the 055 `source_locator`
highlights on it. Today the original is not retrievable: (a) on the Turso deploy, `registry.mark_terminal`
best-effort **deletes** the upload blob when a job reaches a terminal state (feature 054 — to bound Turso
growth), so a completed job's source is gone; and (b) there is **no endpoint** that returns the uploaded
file — the upload is Fernet-encrypted at rest (036) and only ever decrypted to a short-lived temp file
inside IngestAgent (`_materialize_plaintext`). So a finished report has no way to show its source document.

This feature (a) **retains the uploaded PDF indefinitely** (owner decision: keep forever) when the
traceability chain is enabled, by not terminal-deleting it, and (b) adds an authenticated, owner-scoped
**`GET /api/jobs/{job_id}/source`** that reads the stored upload (Turso blob or disk), Fernet-decrypts it
(tolerating legacy plaintext), and streams it as `application/pdf`.

### Position relative to the constitution
- **No LangGraph node/edge/`ContractState` change (§2).** All work is in the runner registry +
  the FastAPI route layer. No change to any pipeline node.
- **No Alembic migration.** The `upload_blobs` table (054) and the disk `UPLOAD_DIR` (036) already exist;
  this feature only changes *whether* the blob is deleted and *adds a read endpoint*.
- **§2 encryption-at-rest amendment (036) is honored:** the source is stored encrypted and only decrypted
  transiently at the point of use (here, in the response stream), never re-stored in plaintext.
- **Per-user isolation (§019 amendment):** the endpoint is `require_auth` + owner-scoped (`_owned_or_404`),
  exactly like `GET /jobs/{id}/report`; no cross-account access.
- Reversible via a config flag (§3): off ⇒ 054 terminal-delete behavior is unchanged and the endpoint
  simply 404s when the source is gone.

## 2. Inputs and outputs

### Retention — stop terminal-deleting the upload
- `registry.mark_terminal` currently runs `blob_store.delete(document_path, table="upload_blobs")` when
  `TURSO_DATABASE_URL` is set (054). When **`UPLOAD_SOURCE_RETENTION_ENABLED`** is True, this delete is
  **skipped** — the upload blob is kept indefinitely (keep-forever). When False, byte-identical to 054.
  (On the local disk backend the upload already persists in `UPLOAD_DIR`, so retention is Turso-relevant;
  the disk path is unchanged either way.)

### `GET /api/jobs/{job_id}/source` — serve the decrypted original
- **Auth + ownership:** `Depends(require_auth)` + `_owned_or_404(ctx, job_id, current_user)` (mirrors the
  report endpoint). A non-owner / unknown job → 404; unauthenticated → 401.
- **Read + decrypt:** obtain the stored upload bytes via the existing seam — `blob_store.read(document_path,
  table="upload_blobs")` when `TURSO_DATABASE_URL` is set, else read the disk file at `document_path` —
  then `crypto.decrypt_bytes` when `CONTRACT_ENCRYPTION_AT_REST_ENABLED`, tolerating legacy plaintext on
  `InvalidToken` (same decrypt rules as `ingest_agent._materialize_plaintext`; factor a shared helper so
  the two cannot drift).
- **Response:** `application/pdf` body (the decrypted bytes). The feature targets PDFs (057 is PDF-only); a
  non-PDF upload (e.g. `.docx`) → **415** (the viewer never requests it for DOCX).
- **Missing source:** blob/file absent (never retained, or retention off + already terminal-deleted on
  Turso) → **404** (graceful; 057 shows "original no longer available").
- The server filesystem path / document_path is never exposed to the client (resolved server-side from the
  owned record, as the report endpoint does).

### Resolved decisions (inline)
- **D1 — Keep forever (owner decision).** No TTL, no opt-in. Retention is all-or-nothing behind the flag.
- **D2 — Reversible flag `UPLOAD_SOURCE_RETENTION_ENABLED`, default `False`.** Off ⇒ 054 terminal-delete
  unchanged; the endpoint still exists but 404s when the source is gone. Ships OFF with the 055–057 chain;
  flipped on (with `PDF_SOURCE_LOCATOR_ENABLED`) when 057 lands.
- **D3 — Shared read+decrypt helper.** Extract the Turso/disk read + Fernet-decrypt (tolerant of legacy
  plaintext) used by `ingest_agent._materialize_plaintext` into one helper both it and the endpoint call,
  so decrypt semantics cannot drift. (Refactor is behavior-preserving for ingest.)
- **D4 — PDF only (415 for others).** Matches the PDF-only locator chain; DOCX has no `source_locator`.
- **D5 — No node/edge/state/migration change.** Registry + routes + a crypto/read helper only.

## 3. Acceptance criteria

Backend, offline (pytest; FastAPI TestClient; no Ollama). Encryption/blob paths exercised as existing
036/054 tests do (monkeypatched local-sqlite `upload_blobs` / disk).

- **AC-1 (retention keeps the blob):** with `UPLOAD_SOURCE_RETENTION_ENABLED=True` and Turso configured,
  `registry.mark_terminal` does NOT delete the `upload_blobs` row — `blob_store.exists(document_path,
  table="upload_blobs")` is True after the job reaches a terminal state.
- **AC-2 (054 parity when off):** with the flag False, `mark_terminal` deletes the upload blob exactly as
  today (the existing 054 terminal-delete test passes unchanged).
- **AC-3 (serve decrypted PDF):** `GET /jobs/{id}/source` for the owning user of a job whose encrypted PDF
  upload exists returns 200, `content-type: application/pdf`, and a body byte-equal to the original
  pre-encryption PDF bytes.
- **AC-4 (owner isolation):** a different authenticated user requesting another user's job → 404; an
  unknown job → 404.
- **AC-5 (auth required):** an unauthenticated request → 401.
- **AC-6 (legacy plaintext tolerated):** when the stored upload is plaintext (pre-036 / encryption off),
  the endpoint still returns the correct PDF bytes (InvalidToken → treat as plaintext).
- **AC-7 (missing source → 404):** when no upload blob/file exists for `document_path` (retention off +
  terminal-deleted, or never stored), the endpoint returns 404 (no 500, no path leak).
- **AC-8 (DOCX → 415):** a `.docx` upload's `/source` request returns 415 (PDF-only).
- **AC-9 (shared decrypt helper, ingest unchanged):** `ingest_agent._materialize_plaintext` uses the same
  extracted helper; all existing ingest/036/054 tests pass unchanged (behavior-preserving refactor).
- **AC-10 (no architecture change):** `git diff main` touches only the registry, routes, the crypto/read
  helper, ingest_agent (refactor), config, and tests + the specs; no node/edge/`ContractState`/migration
  change. Full backend suite green on Windows.

## 4. Edge cases
- **EC-1 — Flag off, Turso:** completed job's upload was terminal-deleted (054) → `/source` 404 (AC-7).
- **EC-2 — Flag off, disk:** upload persists in `UPLOAD_DIR` → `/source` serves it (disk never GC'd today).
- **EC-3 — Job not completed yet:** `/source` may still serve the (already-stored) upload — the file is
  written at upload time, before the run — so a running job's source is retrievable by its owner. (No
  completion gate, unlike the report endpoint; the source exists from upload onward.)
- **EC-4 — Corrupted/undecryptable ciphertext (not legacy plaintext):** `crypto.decrypt_bytes` raises on
  truly corrupt data → map to 500 "could not read source" (never leak internals); this is distinct from
  the InvalidToken-legacy-plaintext tolerance (AC-6).
- **EC-5 — Very large upload (within `MAX_UPLOAD_SIZE_BYTES`):** one in-memory read+decrypt, bounded by
  the existing 25 MB upload cap; streamed as the response body (acceptable, same magnitude as the report).
- **EC-6 — Retention on but a pre-056 job (already terminal-deleted):** `/source` 404 (retention is not
  retroactive). Accepted.

## 5. Out of scope
- **The pdf.js viewer + click-to-highlight UI** — feature **057** (consumes this endpoint + 055's
  `source_locator`).
- **TTL / opt-in retention / a GC sweep** — explicitly not built (owner chose keep-forever, D1).
- **Serving DOCX or any non-PDF original** (415) and DOCX→PDF conversion — out of the PDF-only chain.
- **Encryption-at-rest of generated reports / parsed text** — unrelated, still deferred.
- **Any pipeline node / graph / `ContractState` change.**
- **Retroactively restoring sources already terminal-deleted** before this feature (EC-6).

## 6. Evaluation (metrics to log)
No accuracy/retrieval change. For operability, log (debug) at `/source`: whether the read hit Turso vs
disk, whether decrypt took the ciphertext vs legacy-plaintext branch, and the served byte length (never
the bytes, never the key). No eval-harness change.

## 7. Open questions

Both resolved by the owner (2026-10-05); they confirm the spec's primary design (already in §2 / the
decisions / the ACs) — no scope change:
- **OQ-1 — Flag coupling → RESOLVED: separate flag `UPLOAD_SOURCE_RETENTION_ENABLED` (default off)**, flipped
  on together with `PDF_SOURCE_LOCATOR_ENABLED` when 057 ships (D2). Retention stays independently
  reversible from locator capture.
- **OQ-2 — Completed-gate → RESOLVED: no gate** (EC-3) — the owner may fetch their uploaded source anytime;
  it exists from upload time.

No open questions remain.
