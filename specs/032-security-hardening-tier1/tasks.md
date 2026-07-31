# Feature 032 — Security Hardening Tier 1 — Tasks

Implements the APPROVED `plan.md` against the APPROVED `spec.md`. Branch (per constitution §11):
`feature/032-security-hardening-tier1` — open it with the `git-start` workflow **after** this tasks.md
exists (spec + plan already approved).

**Conventions for the implementing model:**
- TDD (constitution §7): write each test task and **run it to confirm it FAILS** before writing the
  implementation task that makes it pass. Never weaken a test to force a pass; fix the code.
- Run backend tests from `E:\Desktop\ContractSentinel\backend` with **`python -X utf8 -m pytest`** (the
  `-X utf8` avoids cp1252 crashes on ✓ output — known harness gotcha).
- Run frontend tests from `E:\Desktop\ContractSentinel\frontend` with `npm test`.
- All numeric/string thresholds come from `app/config.py` named constants (constitution §3) — never
  hardcode them in endpoint/store logic.
- Do NOT touch any LangGraph node/edge, `ContractState`, the checkpointer, or report format (AC-18).

Legend: each task lists the spec **AC(s)** it serves and the file(s) it touches.

---

## Phase A — Dependency & config scaffolding

- **T1.** Add `cryptography>=42.0.0` to `backend/pyproject.toml` `[project].dependencies`. Run
  `pip install -e .` (or `pip install cryptography`) in the backend venv so it imports. (Serves W1.)
- **T2.** Update `specs/002-tech-stack.md`: add `cryptography` to §3 (a short "Security / encryption at
  rest" note) and to the §4 `pyproject.toml` block, with one line stating it is a **symmetric-crypto
  primitive (Fernet), explicitly NOT the KMS/Vault excluded by §5.5**. (Spec §2.2 "New dependency".)
- **T3.** Add the config constants to `app/config.py` exactly as in plan §1: `ENCRYPTION_KEY_ENV`,
  `ENCRYPTION_KEY_FILE`; change `AUTH_COOKIE_SECURE` default→`True` (env-overridable), change
  `AUTH_SESSION_TTL_SECONDS`→`8*3600`, add `AUTH_IDLE_TIMEOUT_SECONDS=1800`, `AUTH_CLOCK_SKEW_SECONDS=60`,
  and the W3 block (`AUTH_RATE_LIMIT_MAX=10`, `AUTH_RATE_LIMIT_WINDOW_SECONDS=60`,
  `AUTH_LOCKOUT_MAX_FAILURES=5`, `AUTH_LOCKOUT_WINDOW_SECONDS=900`, `AUTH_LOCKOUT_DURATION_SECONDS=900`).
  Add an env-reader helper (`_env_bool`/`_env_int`) if not already present, matching existing style.
  (Serves AC-7, AC-8, AC-9, AC-13, AC-15, AC-17.)
- **T4.** Update `backend/.env.example` (create if absent) + README note: for local plaintext-HTTP dev set
  `AUTH_COOKIE_SECURE=False`; document `CONTRACTSENTINEL_ENCRYPTION_KEY` and that losing the key orphans
  stored tokens (users re-connect). (Spec EC-10, plan §9.)

---

## Phase B — W1: encryption utility (crypto module)

- **T5 (test).** `tests/unit/test_crypto.py`: assert (a) `encrypt`→`decrypt` round-trips (AC-1);
  (b) `decrypt` of a token made with a different key raises `InvalidToken`; (c) key precedence env →
  file → generate+persist, generated file is 0600 where supported (AC-4); (d) `looks_like_plaintext_token`
  detects a legacy `{"refresh_token": ...}` JSON and rejects ciphertext/garbage; (e) neither the key nor a
  decrypted token string is emitted to logs (use `caplog`) (AC-4). Confirm FAILS.
- **T6 (impl).** Create `app/security/__init__.py` (if needed) and `app/security/crypto.py` per plan §2.1:
  `load_encryption_key`, `encrypt`, `decrypt`, `looks_like_plaintext_token`, `bootstrap_encryption_key`.
  Mirror `security.load_secret` for key bootstrap; module-level key cache; never log the key. Make T5 pass.
- **T7 (impl).** Call `bootstrap_encryption_key()` in the FastAPI lifespan startup (where
  `bootstrap_secret()` is called — find via grep in `app/api/main.py`) so key issues fail fast. (AC-4.)

---

## Phase C — W1: per-user token encryption in the store

- **T8 (test).** Extend `tests/unit/test_user_store.py`: (a) after `set_google_credentials(u, token, email)`
  the raw DB value ≠ `token` and does NOT contain the substring `refresh_token` in cleartext; and
  `get_google_credentials(u)` returns the original `token` (AC-2); (b) a row pre-seeded with **plaintext**
  JSON is read back as-is (legacy tolerance) and, after a subsequent `set_google_credentials`, is stored
  encrypted (AC-5); (c) a row with corrupt/foreign ciphertext → `get` returns `None` (EC-1/EC-2);
  (d) `set_google_credentials(u, None/"" , ...)` stores SQL `NULL`, `get` returns `None` (EC-11);
  (e) `clear_google_credentials` still nulls the column and `revoke_token` receives decrypted JSON (AC-6).
  Confirm FAILS.
- **T9 (impl).** Edit `app/runner/user_store.py` per plan §2.2: `set_google_credentials` encrypts non-empty
  tokens (NULL for empty/None); `get_google_credentials` decrypts, with legacy-plaintext tolerance and
  corrupt→None. Import `app.security.crypto`. Do NOT change the column DDL. Make T8 pass.
- **T10 (verify).** Confirm callers (`integrations.py`, `worker.py:103`) need no change — the store is the
  seam. Run the existing integrations/worker tests; they must stay green (AC-6, AC-18).

---

## Phase D — W1: central token encryption (decrypt-to-tempfile, key stays in parent)

- **T11 (test).** Extend `tests/unit/test_oauth_credentials.py`: new
  `materialize_central_token_tempfile()` — given an encrypted `GOOGLE_OAUTH_TOKEN_PATH`, returns a temp
  file path whose contents are the decrypted plaintext JSON (0600); given a legacy-plaintext file, returns
  the original path (no tempfile); given absent file, returns `None`. Confirm FAILS.
- **T12 (impl).** Add `materialize_central_token_tempfile()` to `app/delivery/oauth_credentials.py`
  (reuse `write_token_tempfile`). Make T11 pass.
- **T13 (test).** Extend `tests/unit/test_delivery_step.py`: for the **central** Drive path and the Gmail
  path, the parent materializes a decrypted central tempfile, passes its path as `token_path` to both
  clients, and unlinks it in a `finally` even when the delivery call raises — assert no leftover temp file
  after success AND after an exception (AC-21); assert the on-disk central token is ciphertext yet valid
  creds are obtained (AC-3). Confirm FAILS.
- **T14 (impl).** Edit `app/delivery/delivery_step.py` per plan §2.3: central Drive path (currently
  `token_path=None`) and Gmail path use the materialized tempfile; `os.unlink` in `finally`. Thread a new
  optional `token_path` param through `app/delivery/mcp_clients/gmail_client.py` →
  `app/delivery/mcp_servers/gmail_server.py` (default `None` → `config.GOOGLE_OAUTH_TOKEN_PATH`, mirroring
  `drive_server.py:37`). `google_auth.load_credentials` stays unchanged (plaintext path only; subprocess
  never gets the key). Make T13 pass.
- **T15 (test+impl).** `tests/unit/test_oauth_bootstrap.py` (new/extend): `scripts/oauth_bootstrap.py`
  writes **ciphertext** (`crypto.encrypt(creds.to_json())`) and tolerates an existing plaintext token.
  Confirm FAILS, then edit `scripts/oauth_bootstrap.py:62`. (AC-3/AC-5.)

---

## Phase E — Migration 0007 (DDL + idempotent token backfill)

- **T16 (test).** `tests/integration/test_migration_0007.py` (new): on a DB seeded with a user whose
  `google_oauth_token` is legacy **plaintext**, `alembic upgrade head` (a) makes head `0007`, (b) adds the
  four columns (`session_epoch`, `failed_login_count`, `first_failure_at`, `lockout_until`) with correct
  defaults, (c) encrypts the plaintext token in place, and (d) is **idempotent** — a second run (or a row
  already encrypted / NULL) does not double-encrypt. `downgrade` drops the four columns. Also add an
  assertion to `tests/integration/test_alembic_head.py` that the current Alembic head revision is `0007`
  (that file presently asserts schema/idempotency, not a literal head string — add the head check).
  Confirm FAILS.
- **T17 (impl).** Create `alembic/versions/0007_security_tier1.py` with `revision="0007"`,
  `down_revision="0006"` (the literal revision id of `0006_add_user_google_token.py` is `"0006"` — NOT the
  filename). `upgrade()` adds the four columns then runs the idempotent encrypt-backfill via
  `op.get_bind()` + `app.security.crypto` (skip already-encrypted/NULL using `looks_like_plaintext_token`).
  `downgrade()` drops the four columns (leaves token values encrypted). Make T16 pass. (AC-18.)

---

## Phase F — W2: session/cookie hardening

- **T18 (test).** Extend `tests/unit/test_auth_security.py` (the existing file that already calls
  `make_session`): update the two existing `make_session(user)` call sites to a subject carrying
  `session_epoch`; assert the JWT now carries `iat`, sliding `exp` (=now+idle capped by `aexp`), fixed
  `aexp`, and `epoch`. Confirm FAILS.
- **T19 (impl).** Edit `app/api/security.py::make_session` per plan §3.1 (add `iat`, `exp`, `aexp`,
  `epoch`; `absolute_exp` kwarg preserved across re-issues). Make T18 pass.
- **T20 (impl).** Edit `app/runner/user_store.py`: `UserRow` gains `session_epoch` (default 0);
  `get_by_id`/`get_by_email` select it; add `bump_session_epoch(user_id)`. Update `signup`/`login`
  (`auth.py:220/239`) to pass the `UserRow` (or explicit epoch) to `make_session`.
- **T21 (test).** `tests/integration/test_auth_session.py` (new), using time-freezing/monkeypatched clock:
  AC-7 cookie has `HttpOnly`+`SameSite=Lax`+`Secure` (Secure absent only when `AUTH_COOKIE_SECURE=False`);
  AC-8 session past `aexp` rejected even with continuous activity; AC-9 idle-expired → 401, and a request
  within the window succeeds AND refreshes the window (a later request one idle-window-minus-ε succeeds);
  AC-10 epoch mismatch → 401 while a freshly minted token succeeds; EC-5 small clock skew tolerated;
  EC-6/Q2 a token with NO `epoch` claim → 401 (forced re-login). Confirm FAILS.
- **T22 (impl).** Edit `app/api/auth.py::require_auth` per plan §3.2: add `response: Response` param;
  enforce absolute cap, reject missing/mismatched epoch, re-issue sliding cookie on valid requests
  (same `aexp`), tolerate `AUTH_CLOCK_SKEW_SECONDS`. Note: `AuthUser` (the response model) deliberately
  does NOT gain `session_epoch` — the epoch stays server-side (read from the `UserRow`), never on the
  wire (plan §3.3). Make T21 pass.
- **T23 (test).** Extend session tests: AC-11 `POST /api/auth/me/password` (correct current pw) bumps
  `session_epoch` so a second existing session for that account 401s next request, while the changing
  client keeps a valid (freshly issued) cookie; AC-12 `POST /api/auth/logout-all` requires auth (401
  without session) and returns 200 after incrementing epoch. Confirm FAILS.
- **T24 (impl).** Edit `app/api/auth.py`: `change_password` (`auth.py:269`) calls `bump_session_epoch`
  then re-issues this client's cookie; add `POST /api/auth/logout-all` (authenticated) to `auth_router`.
  Make T23 pass. (Supersedes 023 D3 for security.)

---

## Phase G — W3: rate-limiting & lockout

- **T25 (test).** `tests/unit/test_rate_limit.py` (new): a sliding-window per-key limiter allows up to
  `AUTH_RATE_LIMIT_MAX` hits per `AUTH_RATE_LIMIT_WINDOW_SECONDS`, then denies; window slides; distinct
  keys are independent; monkeypatching the config constant changes behavior (AC-15, AC-17). Confirm FAILS.
- **T26 (impl).** Create `app/api/rate_limit.py`: thread-safe in-process sliding-window counter keyed by
  string (client IP). Make T25 pass. Document per-process/EC-8/EC-9 limitation in the module docstring.
- **T27 (test).** Extend `tests/unit/test_user_store.py`: `record_login_failure` accumulates only within
  `AUTH_LOCKOUT_WINDOW_SECONDS` (older `first_failure_at` resets the counter), sets `lockout_until` at
  `AUTH_LOCKOUT_MAX_FAILURES`; `is_locked` true until `lockout_until`; `reset_login_failures` clears all
  three fields; unknown email is a no-op; lockout state **persists across a store re-open** (EC-8, AC-14).
  Confirm FAILS.
- **T28 (impl).** Edit `app/runner/user_store.py`: add `record_login_failure`, `reset_login_failures`,
  `is_locked` per plan §4.2 (uses the `failed_login_count`/`first_failure_at`/`lockout_until` columns from
  T17). Make T27 pass.
- **T29 (test).** `tests/integration/test_auth_bruteforce.py` (new): AC-13 `AUTH_LOCKOUT_MAX_FAILURES`
  wrong-password logins → next attempt (even correct password) returns **429 + `Retry-After`**, and after
  the duration the correct password succeeds; AC-14 a success before threshold resets the counter; AC-15
  >`AUTH_RATE_LIMIT_MAX` attempts from one IP → 429, a different IP unaffected; AC-16 locked responses
  don't disclose email existence and the unknown-email path still runs the dummy bcrypt verify; AC-20
  `POST /api/auth/me/password` is per-IP rate-limited (429) but NOT lockable. Confirm FAILS.
- **T30 (impl).** Edit `app/api/auth.py` `login`/`signup`/`change_password` per plan §4: per-IP limit
  (`request.client.host`) on all three; per-account lockout gate on `login` only (check before verify;
  record failure on wrong pw; reset on success). 429 + `Retry-After`, generic body (AC-16). Preserve the
  014 M2 timing-equalized unknown-email path. Make T29 pass.

---

## Phase H — Frontend idle-logout UX (AC-19)

- **T31 (test).** Extend `frontend/src/__tests__` (realProvider + processing + settings): an authenticated
  call returning `ApiError{status:401}` calls a single `handleSessionExpired()` → clears the current-user
  cache + `window.location.assign('/login')`; the initial unauthenticated `me()` bootstrap 401 does NOT
  redirect-loop; `useJobStatus` (`frontend/src/lib/useJobStatus.ts`) treats 401 as terminal-for-session
  (stops polling); `logoutAll()` exists on both providers and the Security tab button calls it. Confirm
  FAILS.
- **T32 (impl).** `frontend/src/lib/api/realProvider.ts`: centralize 401 handling → `handleSessionExpired`
  (reuse the cache-clear + hard-nav from commit `32cbd03`; hard `window.location.assign`, not
  `router.replace`). Add `logoutAll()` to `ApiClient` (`lib/api/client.ts`) + both providers
  (real → `POST /api/auth/logout-all`; mock → clears fake session). Wire a "Sign out of all devices"
  button in `components/settings/AccountSettingsView.tsx` Security tab. Ensure `useJobStatus` stops on
  401. Make T31 pass.

---

## Phase I — Full suite, smoke, finish

- **T33.** Run the FULL backend suite (`python -X utf8 -m pytest`) from `backend/` and the full frontend
  suite (`npm test`) from `frontend/`. All green. Confirm the graph/pipeline/delivery suites are unchanged
  and passing (AC-18). Run `/security-review` on the branch diff.
- **T34 (real smoke — user's real-smoke rule + closes Gate-1 Drive-connect).** Documented manual smoke
  (plan §7): (a) connect a Google account → verify the DB `google_oauth_token` is ciphertext (no
  `refresh_token` cleartext) AND a report still delivers to the user's own Drive + email; (b) log in →
  idle > 30 min → next action redirects to `/login`; change password in browser A → browser B's session
  is logged out; (c) 5 wrong passwords → 429 + `Retry-After`, correct password blocked until it clears.
- **T35.** Finish per constitution §11 via the `git-finish` workflow (rebase on latest main, suite green,
  merge, delete branch). Update the feature-032 memory to MERGED.

---

## Acceptance-criteria coverage map

| AC | Task(s) |
|----|---------|
| AC-1 | T5, T6 |
| AC-2 | T8, T9 |
| AC-3 | T13, T14, T15 |
| AC-4 | T5, T6, T7 |
| AC-5 | T8, T9, T15, T16, T17 |
| AC-6 | T8, T9, T10 |
| AC-7 | T21, T22 |
| AC-8 | T21, T22 |
| AC-9 | T21, T22 |
| AC-10 | T21, T22 |
| AC-11 | T23, T24 |
| AC-12 | T23, T24 |
| AC-13 | T29, T30 |
| AC-14 | T27, T28, T29 |
| AC-15 | T25, T26, T29, T30 |
| AC-16 | T29, T30 |
| AC-17 | T3, T25, T29 |
| AC-18 | T10, T16, T17, T33 |
| AC-19 | T31, T32 |
| AC-20 | T29, T30 |
| AC-21 | T13, T14 |
