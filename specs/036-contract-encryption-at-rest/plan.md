# Feature 036 — Contract Encryption at Rest — Technical Plan

**Branch:** `feature/036-contract-encryption-at-rest` — git workflow per constitution §11.

Implements the spec-reviewer-APPROVED `specs/036-contract-encryption-at-rest/spec.md`, authorized by the
§2 amendment (2026-08-01). **No node/edge/`ContractState`/migration/API change.** TDD per §7.

## 0. Grounding (verified)

- Upload save: `app/api/routes.py:104-134` streams chunks to `dest_path = UPLOAD_DIR/{job_id}{ext}` with
  the `MAX_UPLOAD_SIZE_BYTES` check during streaming.
- Ingest read: `app/graph/nodes/ingest_agent.py:59-84` reads `document_path`, derives `ext`, then calls
  `parse_pdf(document_path, timeout_seconds=...)` / `parse_docx(...)`.
- Crypto: `app/security/crypto.py` has `_fernet()`, `encrypt`/`decrypt` (str), `load_encryption_key`,
  `bootstrap_encryption_key`. Add byte variants alongside.

## 1. Config
`app/config.py`: `CONTRACT_ENCRYPTION_AT_REST_ENABLED: bool = True` (near the 032 encryption key config).

## 2. Crypto (`app/security/crypto.py`)
```python
def encrypt_bytes(data: bytes) -> bytes:
    return _fernet().encrypt(data)
def decrypt_bytes(token: bytes) -> bytes:
    return _fernet().decrypt(token)   # raises InvalidToken on non-ciphertext
```

## 3. Encrypt-on-save (`app/api/routes.py`)
After the streaming write completes and `total>0` check passes, if
`_cfg.CONTRACT_ENCRYPTION_AT_REST_ENABLED`: read `dest_path` bytes, `crypto.encrypt_bytes`, overwrite
`dest_path` with the ciphertext. (Streaming size-limit stays on the plaintext, AC-7.) Wrap in the
existing try/except so a failure cleans up `dest_path`.

## 4. Decrypt-to-tempfile shim (`app/graph/nodes/ingest_agent.py`)
Add a small helper (in ingest_agent or a sibling) `materialize_plaintext(document_path, ext) -> (path, is_temp)`:
- If `CONTRACT_ENCRYPTION_AT_REST_ENABLED`: read bytes; try `crypto.decrypt_bytes` → write plaintext to a
  `NamedTemporaryFile(suffix=ext, delete=False)` (0600 where supported), return (temp_path, True). On
  `InvalidToken` (legacy plaintext), return (document_path, False).
- Else return (document_path, False).
In the ingest dispatch: `real_path, is_temp = materialize_plaintext(document_path, ext)`; call
`parse_pdf/parse_docx(real_path, ...)`; in a `finally`, if `is_temp` `os.unlink(real_path)` (AC-4). The
error-return paths (`_error_return`) keep reporting the ORIGINAL `document_path` (unchanged).

## 5. Tests (TDD)
- `tests/unit/test_crypto.py` (extend): AC-1 `encrypt_bytes`/`decrypt_bytes` round-trip + `decrypt_bytes`
  raises on plaintext.
- `tests/unit/test_ingest_agent.py` (extend) or new: AC-3 encrypted PDF parses to same text; AC-4 temp
  cleaned; AC-5 legacy plaintext parses; AC-6 flag OFF parses in place (no temp).
- `tests/integration` upload test (extend if present): AC-2 stored file is ciphertext; AC-7 size limit.
- AC-8: full suite green with flag ON.

## 6. Files touched
`specs/000-constitution.md` (amendment), `app/config.py`, `app/security/crypto.py`,
`app/api/routes.py`, `app/graph/nodes/ingest_agent.py`, tests. **No builder/state/migration/frontend.**

## 7. Rollback
`CONTRACT_ENCRYPTION_AT_REST_ENABLED=False` → plaintext store + in-place parse (pre-036).
