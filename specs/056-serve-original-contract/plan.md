# Feature 056 — Technical plan: serve the original contract + upload retention

Branch: `feature/056-serve-original-contract` (per constitution §11).

Derived from the approved `spec.md`. API + registry + a shared decrypt helper. (a) Skip the 054
terminal-delete of the upload blob when `UPLOAD_SOURCE_RETENTION_ENABLED`; (b) add an authenticated,
owner-scoped `GET /api/jobs/{job_id}/source` that reads + Fernet-decrypts the upload and streams it as
`application/pdf`. **No node/edge/`ContractState` change; no Alembic migration.** Reversible flag default
False. Owner decisions: keep-forever (no TTL/opt-in); separate flag; no completed-gate.

## 0. Scope of change (files touched)
```
backend/app/config.py                             (UPLOAD_SOURCE_RETENTION_ENABLED flag)
backend/app/security/crypto.py                    (shared decrypt_bytes_tolerant core)
backend/app/graph/nodes/ingest_agent.py           (Turso branch uses the shared core — behavior-preserving)
backend/app/runner/registry.py                    (gate the 054 terminal-delete)
backend/app/api/routes.py                          (GET /jobs/{id}/source)
backend/tests/...                                  (new/updated unit + API tests)
specs/056-serve-original-contract/{spec,plan,tasks}.md
```
**NOT touched:** any pipeline node/graph/builder; `ContractState`/`specs/001`; blob_store schema / any
migration (the `upload_blobs` table + `UPLOAD_DIR` already exist from 054/036); the report/md/pdf/email
renderers.

## 1. `config.py`
- `UPLOAD_SOURCE_RETENTION_ENABLED: bool = _env_bool("UPLOAD_SOURCE_RETENTION_ENABLED", False)` (§3, D2).
  Default off ⇒ 054 behavior unchanged. Flipped on with `PDF_SOURCE_LOCATOR_ENABLED` when 057 ships.

## 2. `crypto.py` — shared decrypt-tolerance core (D3)
- Add `decrypt_bytes_tolerant(raw: bytes) -> bytes`: `try: return decrypt_bytes(raw) except InvalidToken:
  return raw` (legacy/plaintext passes through — the exact tolerance both callers need). Pure, no I/O.
- **Why only the decrypt core (not read+decrypt):** `ingest_agent._materialize_plaintext` keeps two
  *disk parse-in-place fast-paths* (encryption off; disk legacy plaintext → return the original path, no
  tempfile) that must be byte-preserved (AC-9). The read (blob vs disk) + tempfile orchestration therefore
  stays per-caller; only the decrypt tolerance — the real drift risk (AC-6) — is shared.

## 3. `ingest_agent.py` — use the shared core (behavior-preserving, AC-9)
- `_materialize_plaintext` today has ONE shared `try: data = crypto.decrypt_bytes(raw) except InvalidToken:`
  block whose `except` does `if not turso: return document_path, False` (DISK legacy-plaintext parse-in-place
  fast-path) `else: data = raw` (TURSO). **Do NOT collapse the whole block** — that would delete the disk
  early-return and break `test_disk_legacy_plaintext_parses_in_place_when_turso_unset`. Instead restructure
  so the shared core is used ONLY for the Turso sub-case:
  ```python
  if _config.CONTRACT_ENCRYPTION_AT_REST_ENABLED:
      if turso:
          data = crypto.decrypt_bytes_tolerant(raw)      # valid→plaintext, InvalidToken→raw (== today)
      else:                                              # disk + encryption on
          try:
              data = crypto.decrypt_bytes(raw)
          except InvalidToken:
              return document_path, False                # disk legacy plaintext → parse in place (unchanged)
  else:
      data = raw
  ```
  The encryption-off disk fast-path (the `if not CONTRACT_ENCRYPTION_AT_REST_ENABLED and not turso: return
  document_path, False` earlier in the function) is untouched. Net: byte-identical behavior; the shared
  core is used by ingest's Turso path.

## 4. `registry.py` — gate the terminal-delete (AC-1, AC-2)
- `mark_terminal` currently: `if _config.TURSO_DATABASE_URL and self.document_path: blob_store.delete(...,
  table="upload_blobs")`. Change the guard to `if (_config.TURSO_DATABASE_URL and self.document_path and
  not _config.UPLOAD_SOURCE_RETENTION_ENABLED):`. Flag on ⇒ upload kept forever (AC-1); flag off ⇒ 054
  delete unchanged (AC-2). (Read `_config.*` live — monkeypatch-friendly, as the module already does.)

## 5. `routes.py` — `GET /jobs/{id}/source` (AC-3..AC-8)
Mirror the `/report` endpoint:
```python
@router.get("/jobs/{job_id}/source")
async def get_job_source(job_id, request, current_user=Depends(require_auth)):
    ctx = _get_ctx(request); rec = _owned_or_404(ctx, job_id, current_user)  # 401 if unauth, 404 if not owner
    doc_path = rec.document_path
    # PDF only (057 is PDF-only; DOCX has no source_locator) — AC-8
    if not str(rec.original_filename or doc_path).lower().endswith(".pdf"):
        raise HTTPException(415, "Only PDF sources can be served")
    # read raw bytes: Turso blob or disk
    try:
        if _cfg.TURSO_DATABASE_URL:
            raw = blob_store.read(doc_path, table="upload_blobs")
        else:
            with open(doc_path, "rb") as f: raw = f.read()
    except (blob_store.BlobNotFound, FileNotFoundError, OSError):
        raise HTTPException(404, "Source document not available")   # AC-7
    try:
        data = crypto.decrypt_bytes_tolerant(raw) if _cfg.CONTRACT_ENCRYPTION_AT_REST_ENABLED else raw
    except Exception:
        raise HTTPException(500, "Could not read source")           # EC-4 corrupt ciphertext
    return Response(content=data, media_type="application/pdf")      # AC-3
```
- Owner-scope + auth via `_owned_or_404` + `require_auth` (AC-4/AC-5), identical to `/report`. The server
  path is never returned (resolved server-side from the owned record). No completed-gate (OQ-2 resolved).
- Debug-log (not the bytes/key): Turso-vs-disk read, decrypt-vs-plaintext branch, byte length (§6).

## 6. Tests (TDD — write first, confirm failing, then implement)
### Registry (AC-1/AC-2)
- `mark_terminal` with `UPLOAD_SOURCE_RETENTION_ENABLED=True` + a monkeypatched Turso + local-sqlite
  `upload_blobs` (054 technique): assert the blob row still exists after terminal. With the flag False:
  assert it is deleted (the existing 054 terminal-delete test stays green).
### crypto (D3)
- `decrypt_bytes_tolerant`: round-trips ciphertext; returns raw unchanged on non-Fernet bytes (InvalidToken).
### API (AC-3..AC-8) — FastAPI TestClient, authed session like the existing jobs tests
- AC-3: owner GETs `/source` for a job whose encrypted PDF upload exists → 200, `application/pdf`, body ==
  original PDF bytes. AC-4: other user → 404; unknown job → 404. AC-5: no auth → 401. AC-6: plaintext
  upload (encryption off) → correct bytes. AC-7: no upload stored → 404. AC-8: `.docx` upload → 415.
### Ingest (AC-9)
- All existing ingest/036/054 `_materialize_plaintext` tests pass unchanged (the Turso-branch swap is
  behavior-preserving).

## 7. Correctness / constitution
- **§2/§10:** no node/edge/`ContractState` change, no migration (API + registry + crypto helper only).
- **§036:** the source is decrypted only transiently into the response body; never re-stored in plaintext.
- **§019:** owner-scoped + auth'd; no cross-account access; no server-path leak.
- **Reversibility:** flag off ⇒ 054 delete + today's behavior exactly; the endpoint still exists but 404s
  when the source is gone.

## 8. Verification gate (all offline)
- `python -X utf8 -m pytest -q` full suite green (new registry/crypto/API tests + unchanged ingest/036/054).
- `git diff --name-only main` == §0 allow-list (no node/graph/ContractState/migration/renderer change).
- Flag ships OFF; the live value (serving a real PDF to the viewer) arrives with 057.

## 9. Risks / limitations
- **Storage growth (keep-forever):** accepted owner decision; Turso free tier 5 GB, contracts small. No GC.
- **In-memory read+decrypt** bounded by `MAX_UPLOAD_SIZE_BYTES` (25 MB) — same magnitude as the report.
- **Retroactive:** sources already terminal-deleted before this feature stay gone (EC-6) — not restorable.

## 10. Merge
Full backend gate green; diff scope matches §0. Rebase `main`, merge `feature/056-serve-original-contract`,
delete branch (`git-finish`). Flag ships OFF; 057 (viewer) follows and flips the chain on + live-smokes.
