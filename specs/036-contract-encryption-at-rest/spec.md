# Feature 036 — Contract Encryption at Rest

## Problem statement

Uploaded contract files are stored as **plaintext bytes on disk** in `UPLOAD_DIR`
(`data/uploads/{job_id}{ext}`, written by `app/api/routes.py`). These are the user's
confidential source documents — the highest at-rest exposure after the OAuth tokens
feature 032 already encrypts. This feature encrypts them at rest with Fernet (reusing
the 032 `app/security/crypto.py` key seam) and transparently decrypts them to a
short-lived temp file at ingest so the PDF/DOCX parsers are unchanged.

Authorized by the **constitution §2 amendment (2026-08-01, feature 036)**. **No
LangGraph node/edge change, no `ContractState` field, no DB migration** — files on
disk; the `document_path` reference is unchanged (same path, now ciphertext content).
Placement: security hardening of storage, entirely outside the fixed 7-node graph
(the encrypt is in the upload route; the decrypt is a shim at the head of IngestAgent
before it hands the path to `parse_pdf`/`parse_docx`).

## Inputs and outputs

- **No `ContractState` change.** `document_path` (001, added by IngestAgent) still
  points at the on-disk file; its content is now ciphertext when the flag is on.
- **New config (constitution §3):** `CONTRACT_ENCRYPTION_AT_REST_ENABLED: bool = True`
  — master reversible flag. False → files stored/read as plaintext (pre-036).
- **New crypto helpers** in `app/security/crypto.py`: `encrypt_bytes(data: bytes) -> bytes`
  and `decrypt_bytes(token: bytes) -> bytes`, using the same Fernet key as the string
  helpers. `decrypt_bytes` raises `InvalidToken` on a non-ciphertext (legacy plaintext)
  input, which the caller catches to tolerate legacy plaintext uploads.
- Output shapes of the upload route and IngestAgent are **unchanged**.

## Acceptance criteria

- **AC-1** `encrypt_bytes`/`decrypt_bytes` round-trip arbitrary bytes (incl. a small
  binary blob): `decrypt_bytes(encrypt_bytes(b)) == b`.
- **AC-2** With the flag ON, after a successful upload the file at `dest_path` is
  **ciphertext** — its bytes are not the original and do not begin with a PDF/DOCX
  magic header; `decrypt_bytes` of the stored bytes returns the original.
- **AC-3** IngestAgent parses an **encrypted** upload correctly: given a `document_path`
  whose content is `encrypt_bytes(<real pdf>)`, ingest decrypts to a temp file with the
  same extension, parses it, and yields the same `extracted_text` as parsing the
  plaintext original.
- **AC-4** The decrypted temp file is deleted after ingest (success OR parser failure)
  — no plaintext contract copy is left on disk.
- **AC-5** Legacy plaintext tolerance: a `document_path` whose content is a real
  plaintext PDF (pre-036 upload) is still parsed correctly (decrypt fails → treated as
  already-plaintext, parsed in place / copied as-is).
- **AC-6** With the flag OFF, upload stores plaintext and ingest parses in place —
  byte-for-byte pre-036 behavior (no temp file created).
- **AC-7** The upload size limit (`MAX_UPLOAD_SIZE_BYTES`) is still enforced on the
  **plaintext** size before encryption; an oversized upload is rejected as today.
- **AC-8** No LangGraph node/edge, `ContractState` field, DB migration, or API/response
  change; existing pipeline/ingest tests pass with the flag ON.

## Edge cases

- **Empty file** → rejected before encryption (unchanged 400).
- **Decrypt with wrong/rotated key** → `InvalidToken`; ingest treats as plaintext and
  the parser fails naturally (corrupted_file) — no crash, contained by IngestAgent's
  existing error handling.
- **Temp-file cleanup on parser exception** → guaranteed via `finally` (AC-4).
- **Very large upload** → encryption reads the whole (bounded ≤ `MAX_UPLOAD_SIZE_BYTES`)
  file once; acceptable.
- **Missing key at startup** → `bootstrap_encryption_key` already fails fast (032).

## Out of scope

- Encrypting the **generated reports / parsed text** in `data/reports/` (larger surface
  — delivery + Drive read them; deferred per the amendment).
- DB-column encryption (contracts are files, not DB rows).
- Key rotation / re-encryption tooling, KMS (PERMANENTLY CUT).
- Zero-Storage mode, PrivacyAgent, retention (Phase-2-DEFERRED).

## Resolved decisions

1. **Encrypt-on-save, decrypt-to-tempfile at ingest** (mirrors 032's central-token
   tempfile pattern) — keeps the PDF/DOCX parsers and `document_path` reference
   unchanged.
2. **Reuse the 032 Fernet key** (`crypto.load_encryption_key`) — one key seam, no new
   key management.
3. **Reversible flag `CONTRACT_ENCRYPTION_AT_REST_ENABLED`** (default True) — escape
   hatch; OFF = byte-identical pre-036.
4. **Legacy plaintext tolerated** (decrypt-fail → parse as-is), so existing uploads on
   disk keep working without a migration.

## Open questions

None — resolved inline. Scope deliberately limited to the uploaded contract file (the
user's core "encrypt contracts at rest" ask); report-file encryption is a noted
follow-up.
