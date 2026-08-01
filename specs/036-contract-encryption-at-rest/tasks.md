# Feature 036 — Contract Encryption at Rest — Tasks

Implements plan.md. No node/edge/state/migration/frontend. TDD; run `python -X utf8 -m pytest` from `backend/`.

- **T1** `app/config.py`: add `CONTRACT_ENCRYPTION_AT_REST_ENABLED: bool = True`.
- **T2-test** `tests/unit/test_crypto.py`: AC-1 `decrypt_bytes(encrypt_bytes(b))==b` for a binary blob;
  `decrypt_bytes(b"not ciphertext")` raises `InvalidToken`. Run → FAIL.
- **T3-impl** `app/security/crypto.py`: add `encrypt_bytes`/`decrypt_bytes` (§2). Green.
- **T4-test** `tests/unit/test_ingest_agent.py`: (AC-3) an encrypted real PDF at `document_path` → ingest
  `extracted_text` equals the plaintext-parse result; (AC-4) after ingest the temp file is gone; (AC-5)
  a plaintext PDF still parses; (AC-6) flag OFF → parses in place, no temp created. Run → FAIL.
- **T5-impl** `app/api/routes.py` encrypt-on-save (§3) + `app/graph/nodes/ingest_agent.py`
  `materialize_plaintext` + decrypt-to-tempfile dispatch with `finally` cleanup (§4). Green.
- **T6-test** upload integration (AC-2 stored bytes are ciphertext, not a PDF/DOCX magic header; AC-7
  size limit still enforced). Green.
- **T7** Full backend suite green with flag ON (AC-8).

## AC map
AC-1→T2/3; AC-2→T6; AC-3,4,5,6→T4/5; AC-7→T6; AC-8→T7.
