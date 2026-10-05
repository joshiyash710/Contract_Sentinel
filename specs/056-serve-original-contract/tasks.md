# Feature 056 — Serve the original contract + upload retention — Implementation Tasks

Reference documents:
- Spec: `specs/056-serve-original-contract/spec.md`
- Plan: `specs/056-serve-original-contract/plan.md`
- Constitution: `specs/000-constitution.md` (**§1/§11** branch workflow; **§7** TDD / never weaken a test;
  **§2** no node/edge; **§3** named config; **§019** owner-scope; **§036** decrypt transient-only)

Backend paths relative to `backend/`.

**Workflow reminders:**
- **No node/edge/`ContractState` change, no Alembic migration.** API + registry + a crypto helper only.
- **Reversible flag `UPLOAD_SOURCE_RETENTION_ENABLED`, default `False`** → 054 terminal-delete behavior
  unchanged; the `/source` endpoint still exists but 404s when the source is gone.
- **Owner-scoped + auth'd** endpoint (mirror `/report`: `require_auth` + `_owned_or_404`); never leak the
  server path; decrypt only transiently into the response (never re-store plaintext).
- **Scope allow-list (AC-10)** = `config.py`, `security/crypto.py`, `graph/nodes/ingest_agent.py`,
  `runner/registry.py`, `api/routes.py`, + tests + the specs. Nothing else.
- **TDD (§7):** write tests first, confirm FAIL, then implement; never weaken a surprised test.
- **Owner decisions:** keep-forever (no TTL/opt-in); separate flag; no completed-gate; PDF-only (415 DOCX).

---

## Task 0: Branch
- [ ] From up-to-date `main` (`git checkout main && git pull`), create `feature/056-serve-original-contract`
  (`git-start`). Commit the APPROVED spec/plan/tasks.

**Verify:** `git branch --show-current` → `feature/056-serve-original-contract`.

---

## Task 1: Write the failing tests first  [AC-1..AC-9]
- [ ] **[NEW] `tests/unit/test_source_retention.py`** — registry (AC-1/AC-2): with a monkeypatched Turso +
  local-sqlite `upload_blobs` (054 technique), `mark_terminal` with `UPLOAD_SOURCE_RETENTION_ENABLED=True`
  leaves the blob (`blob_store.exists(document_path, table="upload_blobs")` True); with the flag False the
  blob is deleted. crypto (D3): `crypto.decrypt_bytes_tolerant` round-trips ciphertext and returns
  non-Fernet bytes unchanged.
- [ ] **[NEW/EXTEND] API test** (`tests/integration/` or `tests/unit/` per the jobs-endpoint tests) —
  AC-3 (owner GET `/jobs/{id}/source` → 200, `application/pdf`, body == original PDF bytes), AC-4 (other
  user → 404; unknown job → 404), AC-5 (no auth → 401), AC-6 (plaintext upload → correct bytes), AC-7
  (no stored source → 404), AC-8 (`.docx` upload → 415).
- [ ] **[VERIFY existing]** the ingest tests (esp. `test_disk_legacy_plaintext_parses_in_place_when_turso_unset`)
  are the AC-9 guard — do NOT modify them; the Task-4 refactor must keep them green.
- [ ] Run `pytest` → CONFIRM the new tests FAIL (symbols/endpoint absent).

**Verify:** new tests fail for the expected reasons.

---

## Task 2: `config.py`  [AC-1/AC-2, D2]
- [ ] Add `UPLOAD_SOURCE_RETENTION_ENABLED: bool = _env_bool("UPLOAD_SOURCE_RETENTION_ENABLED", False)`.

---

## Task 3: `security/crypto.py` — shared decrypt core  [D3]
- [ ] Add `decrypt_bytes_tolerant(raw: bytes) -> bytes`: `try: return decrypt_bytes(raw)` / `except
  InvalidToken: return raw`. Pure, no I/O.

---

## Task 4: `ingest_agent.py` — use the core (behavior-preserving)  [AC-9]
- [ ] In `_materialize_plaintext`, restructure the encryption-on block EXACTLY per plan §3: Turso sub-case
  → `data = crypto.decrypt_bytes_tolerant(raw)`; disk sub-case → keep the `try: decrypt_bytes except
  InvalidToken: return document_path, False` (parse-in-place). Leave the encryption-off disk fast-path
  untouched. Do NOT collapse the whole shared try/except (would break the pinned disk test).

**Verify:** all existing ingest/036/054 tests pass unchanged.

---

## Task 5: `runner/registry.py` — gate the terminal-delete  [AC-1, AC-2]
- [ ] In `mark_terminal`, change the 054 guard to
  `if _config.TURSO_DATABASE_URL and self.document_path and not _config.UPLOAD_SOURCE_RETENTION_ENABLED:`
  before `blob_store.delete(self.document_path, table="upload_blobs")`. (Read `_config.*` live.)

---

## Task 6: `api/routes.py` — `GET /jobs/{job_id}/source`  [AC-3..AC-8]
- [ ] Add the endpoint per plan §5: `Depends(require_auth)` + `_get_ctx` + `_owned_or_404` (AC-4/AC-5);
  415 when `original_filename`/`document_path` is not `.pdf` (AC-8); read raw (Turso `blob_store.read(...,
  table="upload_blobs")` else `open(document_path,"rb")`) mapping `BlobNotFound`/`FileNotFoundError`/`OSError`
  → 404 (AC-7); `data = crypto.decrypt_bytes_tolerant(raw) if CONTRACT_ENCRYPTION_AT_REST_ENABLED else raw`
  (AC-6), mapping an unexpected decrypt error → 500 (EC-4); return `Response(content=data,
  media_type="application/pdf")` (AC-3). Debug-log Turso-vs-disk + decrypt-vs-plaintext + byte length only.

---

## Task 7: Backend gate  [AC-1..AC-10]
- [ ] `python -X utf8 -m pytest -q` → new tests pass + full suite green (ingest/036/054 unchanged). Fix
  code, not tests, on any surprise (§7).
- [ ] `git diff --name-only main` matches the §0 allow-list (no node/graph/`ContractState`/migration/
  renderer change).

**Verify:** full backend suite green; diff scope matches.

---

## Task 8: Merge
- [ ] Gate green; diff scope confirmed. Rebase `main`, merge `feature/056-serve-original-contract`, delete
  branch (`git-finish`). Flag ships OFF; 057 (viewer) follows, flips the chain on + live-smokes.

---

*Per §1/§11, implementation happens only on `feature/056-serve-original-contract`, opened after spec + plan
+ tasks are all spec-reviewer-APPROVED. API + registry + crypto-helper only — no node/edge/`ContractState`/
migration change; owner-scoped + auth'd; decrypt transient-only (§036); flag ships OFF.*
