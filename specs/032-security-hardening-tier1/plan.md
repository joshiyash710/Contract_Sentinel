# Feature 032 — Security Hardening Tier 1 — Technical Plan

**Branch:** `feature/032-security-hardening-tier1` — git workflow per constitution §11 (this line is the
only workflow statement here; the rules live in §11, not restated).

Implements the spec-reviewer-APPROVED `specs/032-security-hardening-tier1/spec.md` (W1 OAuth-token
encryption at rest, W2 session/cookie hardening, W3 login rate-limiting & lockout). Authorized by the
constitution §2 amendment (2026-07-31, feature 032). **No LangGraph node/edge change; no `ContractState`
field.** Open questions Q1–Q4 resolved in spec §6 (30 min idle / 8 h absolute; force one-time re-login;
persist lockout to DB, no CAPTCHA; 5 fails→lockout, 10/60 s per IP).

TDD per constitution §7: for each work-stream the tests below are written and confirmed **failing**
first, then the implementation makes them pass; tests are never weakened to force a pass.

---

## 0. Grounding (verified against current code)

- Per-user token seam is a single choke point: `UserStore.set_google_credentials` /
  `get_google_credentials` / `clear_google_credentials` (`app/runner/user_store.py:143-177`). Every
  caller (`integrations.py:104/153/168`, `worker.py:103`) goes through these — so encrypting **inside**
  the store is transparent to all of them.
- Central token `data/secrets/google_token.json` (`config.py:391`) is read **inside the MCP subprocess**
  by `google_auth.load_credentials` → `Credentials.from_authorized_user_file` (`google_auth.py:23-27`),
  reached from `drive_server.py:37` (central fallback) and `gmail_server.py:72` (always central). The
  subprocess must receive **plaintext**; the master key must **not** be handed to the subprocess. →
  Parent decrypts the central file to a short-lived 0600 tempfile and passes its path as `token_path`
  (spec §2.2 / EC-3). Per-user delivery already materializes a plaintext tempfile
  (`delivery_step.py:224`, `oauth_credentials.write_token_tempfile`) — same mechanism.
- Auth: JWT `{sub,email,exp}` via `security.make_session`/`read_session` (`security.py:107-123`), pinned
  HS256; secret bootstrap `load_secret` (`security.py:61-94`) is the pattern to mirror for the Fernet
  key. Cookie set in `auth.py:_set_session_cookie` (`httponly`, `samesite=lax`, `secure=AUTH_COOKIE_SECURE`,
  `max_age=AUTH_SESSION_TTL_SECONDS`). `require_auth` (`auth.py:150-168`) already loads the user row on
  every request — the natural place to add epoch + idle checks and re-issue the sliding cookie.
- Current Alembic head is the file `0006_add_user_google_token.py` whose **revision id is literally the
  string `"0006"`** (nothing has `down_revision="0006"`), so `0007` is free and its `down_revision` must
  be exactly `"0006"` (NOT `"0006_add_user_google_token"`).
- Frontend real provider throws `ApiError` with `status` preserved (`lib/api/client.ts:59-66`), so a 401
  is already distinguishable at the fetch boundary.

---

## 1. Config (constitution §3 — all named constants in `app/config.py`, env-overridable)

Add / change (a helper `_env_int`/`_env_bool` reader may be introduced; keep the existing style):

```python
# ── Encryption at rest (feature 032, W1) ──────────────────────────────
ENCRYPTION_KEY_ENV = "CONTRACTSENTINEL_ENCRYPTION_KEY"   # env var name (value never logged)
ENCRYPTION_KEY_FILE: str = "data/encryption_key"          # persisted Fernet key if env unset; 0600

# ── Session hardening (feature 032, W2) — supersedes 014 values ────────
AUTH_COOKIE_SECURE: bool = _env_bool("AUTH_COOKIE_SECURE", default=True)  # was False; True needs TLS
AUTH_SESSION_TTL_SECONDS: int = _env_int("AUTH_SESSION_TTL_SECONDS", 8 * 3600)   # absolute cap (was 7d)
AUTH_IDLE_TIMEOUT_SECONDS: int = _env_int("AUTH_IDLE_TIMEOUT_SECONDS", 1800)     # 30 min sliding idle
AUTH_CLOCK_SKEW_SECONDS: int = 60                                                # EC-5 tolerance

# ── Rate-limit / lockout (feature 032, W3) ────────────────────────────
AUTH_RATE_LIMIT_MAX: int = _env_int("AUTH_RATE_LIMIT_MAX", 10)                   # per-IP attempts
AUTH_RATE_LIMIT_WINDOW_SECONDS: int = _env_int("AUTH_RATE_LIMIT_WINDOW_SECONDS", 60)
AUTH_LOCKOUT_MAX_FAILURES: int = _env_int("AUTH_LOCKOUT_MAX_FAILURES", 5)        # consecutive fails
AUTH_LOCKOUT_WINDOW_SECONDS: int = _env_int("AUTH_LOCKOUT_WINDOW_SECONDS", 15 * 60)
AUTH_LOCKOUT_DURATION_SECONDS: int = _env_int("AUTH_LOCKOUT_DURATION_SECONDS", 15 * 60)
```

`AUTH_COOKIE_SECURE` flips default to **True**; local plaintext-HTTP dev sets `AUTH_COOKIE_SECURE=False`
in `.env` (documented in README / `.env.example` — EC-10). No secret/key value is ever logged (AC-4).

Dependency: add `cryptography>=42.0.0` to `pyproject.toml` `[project].dependencies` and to
`002-tech-stack.md` §3 (new group note) + §4 block (spec §2.2 "New dependency"). It is a symmetric
primitive, **not** the KMS/Vault excluded by tech-stack §5.5 (state this in the tech-stack edit).

---

## 2. W1 — OAuth-token encryption at rest

### 2.1 New module `app/security/crypto.py` (pure, no FastAPI import)
- `load_encryption_key() -> bytes` — precedence env `CONTRACTSENTINEL_ENCRYPTION_KEY` → `ENCRYPTION_KEY_FILE`
  → generate `Fernet.generate_key()`, persist to the key file (`os.makedirs` parent, `chmod 0600` where
  supported), cache module-level. Mirrors `security.load_secret`. Never logs the key.
- `encrypt(plaintext: str) -> str` — `Fernet(key).encrypt(plaintext.encode()).decode()`.
- `decrypt(token: str) -> str` — `Fernet(key).decrypt(token.encode()).decode()`; raises
  `cryptography.fernet.InvalidToken` on bad key/ciphertext (callers catch — see legacy tolerance).
- `looks_like_plaintext_token(value: str) -> bool` — `True` if `value` parses as JSON with a
  `refresh_token`/`token` key (legacy plaintext detector for lazy upgrade).
- `bootstrap_encryption_key()` — called from app lifespan startup to fail-fast / pre-generate.

### 2.2 Wrap the per-user store seam (`app/runner/user_store.py`)
- `set_google_credentials`: store `crypto.encrypt(token_json)` when `token_json` is non-empty; store
  `NULL` for `None`/empty (EC-11 — never `encrypt("")`).
- `get_google_credentials`: read raw; if `None` → `None`; try `crypto.decrypt`; on `InvalidToken`, if
  `looks_like_plaintext_token(raw)` return `raw` as-is (legacy, AC-5) else return `None` (EC-1/EC-2 —
  corrupt/rotated-key → treated as not-connected, never a crash/garbage).
- `clear_google_credentials`: unchanged (nulls the column).
- Lazy re-encrypt (AC-5): after a successful legacy-plaintext read used for a real connect refresh, the
  next `set_google_credentials` (already how 031 re-persists refreshed creds) stores ciphertext. No extra
  write path needed beyond the normal connect/refresh flow; document this.

### 2.3 Central token decrypt-to-tempfile (parent side, no key in subprocess)
- New helper in `app/delivery/oauth_credentials.py`:
  `materialize_central_token_tempfile() -> str | None` — reads `config.GOOGLE_OAUTH_TOKEN_PATH`; if the
  bytes decrypt via `crypto.decrypt`, write plaintext JSON to a 0600 tempfile (reuse
  `write_token_tempfile`) and return its path; if the file is already plaintext (legacy), return the
  original path unchanged (no tempfile); if absent → `None`.
- `delivery_step.py`: for the **central** Drive path (currently `token_path=None`,
  `delivery_step.py:218`) and the **Gmail** path, materialize the central tempfile once, pass its path as
  `token_path` to both the drive client and the gmail client, and `os.unlink` it in a `finally` after
  delivery returns (AC-21). Thread a `token_path` param into `gmail_client` → `gmail_server`
  (new optional arg; default `None` → `config.GOOGLE_OAUTH_TOKEN_PATH` for back-compat, mirroring how
  `drive_server.py:37` already does `req.token_path or GOOGLE_OAUTH_TOKEN_PATH`).
- `google_auth.load_credentials` is **unchanged** (still reads a plaintext file path) — the subprocess
  never sees ciphertext or the key.

### 2.4 Central token write points (encrypt on write)
- `scripts/oauth_bootstrap.py:62` (`token_path.write_text(creds.to_json())`) → write
  `crypto.encrypt(creds.to_json())`. Keep tolerant read of a pre-existing plaintext token.
- Any other central write (none found beyond bootstrap) — confirm via grep during impl.

### 2.5 Migration `0007` (data step for W1 + DDL for W2/W3) — see §5.

---

## 3. W2 — Session/cookie hardening

### 3.1 JWT claims (`app/api/security.py`)
- `make_session(user, *, absolute_exp: datetime | None = None)`:
  - `iat = now`
  - `exp = min(now + AUTH_IDLE_TIMEOUT_SECONDS, absolute_exp)` (sliding idle expiry)
  - `aexp = absolute_exp or (now + AUTH_SESSION_TTL_SECONDS)` (fixed absolute cap; preserved across
    re-issues)
  - `epoch = user.session_epoch`
  - keep `sub`, `email`.
- **Caller change (important for the impl model):** `make_session` currently takes an `AuthUser`
  (`auth.py:220` signup, `auth.py:239` login), which has **no** `session_epoch`. Change these two call
  sites to pass the **`UserRow`** (which carries `session_epoch` after migration `0007`), or pass `epoch`
  explicitly. The two existing `make_session(user)` calls in `tests/unit/test_auth_security.py` must be
  updated to supply a subject with a `session_epoch` (and to assert the new `epoch`/`aexp` claims).
- `read_session` unchanged (decodes/validates HS256 + `exp`); the epoch/aexp/idle-refresh logic lives in
  `require_auth` so we can access the user row and the response.

### 3.2 `require_auth` becomes sliding + epoch-checked (`app/api/auth.py`)
- Signature gains `response: Response` (FastAPI injects and reuses it) so it can re-issue the cookie.
- Steps: read cookie → `read_session` (rejects expired-idle `exp`/tampered → 401). Then:
  1. **Absolute cap (AC-8):** reject if `now > aexp + skew` → 401.
  2. **Legacy pre-epoch tokens (Q2/EC-6):** if `epoch` claim is **absent** → 401 (force one-time
     re-login). A present `epoch` that ≠ the user row's `session_epoch` → 401 (AC-10).
  3. Load user row (already done); build `AuthUser`.
  4. **Sliding re-issue (AC-9):** mint a fresh token with the **same `aexp`** and a refreshed idle `exp`,
     `_set_session_cookie(response, token)`. Skip re-issue if `aexp` reached (let it lapse).
- Clock skew (`AUTH_CLOCK_SKEW_SECONDS`) tolerated on both `exp` and `aexp` (EC-5).

### 3.3 `session_epoch` storage + invalidation
- New `users.session_epoch INTEGER NOT NULL DEFAULT 0` (migration `0007`, §5).
- `UserStore`: `get_by_id`/`get_by_email` select `session_epoch`; `UserRow` gains the field;
  `bump_session_epoch(user_id)` does `UPDATE users SET session_epoch = session_epoch + 1 WHERE id=?`.
- `AuthUser` need NOT expose `session_epoch` on the wire (stays server-side); `make_session` reads it
  from the `UserRow`, so `login`/`signup` pass the row (they already have it).
- `change_password` (`auth.py:269`) calls `bump_session_epoch` after the password update, then re-issues
  **this** browser's cookie so the changer stays logged in (AC-11). Supersedes 023 D3's "session stays
  valid for others".
- New endpoint `POST /api/auth/logout-all` (authenticated, `require_auth`): `bump_session_epoch`,
  204/200 (AC-12). Add to `auth_router`.
- `POST /api/auth/logout` unchanged (clears this cookie only).

### 3.4 Frontend idle-logout UX (AC-19)
- `lib/api/realProvider.ts`: centralize fetch handling so any `ApiError` with `status === 401` from an
  authenticated call triggers a single `handleSessionExpired()` — clear the current-user cache
  (`useCurrentUser` clear, reuse the login/logout cache-clear from commit `32cbd03`) and hard-navigate
  `window.location.assign("/login")` (not `router.replace`, per the account-switch Router-Cache fix).
  Guard against loops (don't trigger on the `login`/`me` bootstrap 401 that simply means "not logged
  in"; only on a previously-authenticated session going 401).
- Add `logoutAll()` to `ApiClient` + both providers (real → `POST /api/auth/logout-all`; mock → clears
  fake session) for a "sign out of all devices" affordance (wire a button in
  `settings/AccountSettingsView.tsx` Security tab; minimal).
- Polling hooks (`useJobStatus`) already tolerate transient failures (2026-07-28 fix); ensure a 401 is
  treated as terminal-for-session (stop polling, redirect) not a transient blip.

---

## 4. W3 — Login/signup rate-limiting & lockout

### 4.1 Per-IP rate limiter (in-process, `app/api/rate_limit.py`)
- A small thread-safe sliding-window counter keyed by client IP: `hit(key) -> bool` (True = allowed).
  In-memory dict of deque[timestamp], pruned to `AUTH_RATE_LIMIT_WINDOW_SECONDS`. EC-8/EC-9 documented
  (per-process; Phase-1 single process).
- Client IP from `request.client.host` (no proxy trust in Phase-1; note X-Forwarded-For is deployment
  concern). Applied to `login`, `signup`, and `me/password` (AC-15, AC-20). Over limit → `429` +
  `Retry-After` header.

### 4.2 Per-account lockout (persisted, survives restart — Q3)
- Storage: additive columns on `users` (migration `0007`): `failed_login_count INTEGER NOT NULL
  DEFAULT 0`, `first_failure_at TEXT NULL` (ISO — anchors the failure window), `lockout_until TEXT NULL`
  (ISO). (A separate `login_attempts` table is an alternative but columns are simpler and match the
  single-owner model; chosen for minimal surface.)
- `UserStore`: `record_login_failure(email)` — the count only accumulates **within**
  `AUTH_LOCKOUT_WINDOW_SECONDS`: on a failure, if `first_failure_at` is null or older than the window,
  reset the counter to 1 and stamp `first_failure_at = now`; otherwise increment. Set `lockout_until =
  now + AUTH_LOCKOUT_DURATION_SECONDS` when the count reaches `AUTH_LOCKOUT_MAX_FAILURES` consecutive
  failures inside the window. `reset_login_failures(email)` (on success — AC-14, clears count +
  `first_failure_at` + `lockout_until`), `is_locked(email) -> bool` (now < `lockout_until`). Keyed by
  email; unknown email is a no-op (don't create rows / don't disclose — AC-16).
- `login` flow (`auth.py:225`): (1) per-IP limit check → 429; (2) `is_locked(email)` → 429 + Retry-After
  even if the password is correct (AC-13); (3) existing timing-equalized verify; (4) on failure
  `record_login_failure`, on success `reset_login_failures` then issue session. Unknown-email path still
  runs the dummy bcrypt verify (AC-16, 014 M2 preserved) and does NOT reveal existence.

### 4.3 Response discipline
- 429 body is generic; never distinguishes locked-existing vs locked-nonexistent (AC-16). `Retry-After`
  = remaining lockout/limit seconds.

---

## 5. Alembic migration `0007` (single, `down_revision = "0006"`)

`alembic/versions/0007_security_tier1.py`:
- `upgrade()`:
  1. `add_column('users', session_epoch INTEGER NOT NULL server_default '0')`.
  2. `add_column('users', failed_login_count INTEGER NOT NULL server_default '0')`.
  3. `add_column('users', first_failure_at TEXT NULL)`.
  4. `add_column('users', lockout_until TEXT NULL)`.
  5. Data backfill (idempotent): for each `users` row with a non-null `google_oauth_token`, if it is NOT
     already Fernet-decryptable (i.e. legacy plaintext), `UPDATE` it to `crypto.encrypt(value)`. Rows
     already encrypted or NULL are skipped (no double-encrypt, AC-5). Runs via a data loop in the
     migration using `op.get_bind()`.
- `downgrade()`: drop the four added columns (`session_epoch`, `failed_login_count`, `first_failure_at`,
  `lockout_until`). Token values are left encrypted (downgrade does not decrypt) — documented; a true
  rollback would need the key, out of scope.
- Central `google_token.json` backfill is a **file**, not DB → handled lazily by
  `materialize_central_token_tempfile` tolerance + re-encrypted on next `oauth_bootstrap` write (not in
  Alembic). AC-3/AC-5.
- `test_alembic_head` and existing migration tests updated to expect `0007` as head.

---

## 6. Test plan (TDD — failing first) — every AC mapped

Backend (`backend/tests/`):
- **crypto** (`unit/test_crypto.py`): AC-1 round-trip; decrypt of foreign-key value raises; key precedence
  env→file→generate + 0600 (AC-4); key/plaintext never logged (caplog assert) (AC-4).
- **user_store encryption** (`unit/test_user_store.py` extend): AC-2 stored value ≠ plaintext & no
  `refresh_token` substring, round-trips; AC-5 legacy-plaintext read + re-encrypt-on-write; AC-6
  disconnect/revoke still work; EC-1/EC-2 corrupt/rotated → None; EC-11 empty → NULL.
- **central token** (`unit/test_oauth_credentials.py` / `unit/test_delivery_step.py` extend): AC-3 central
  file ciphertext on disk yet delivery obtains creds; AC-21 tempfile removed in `finally` even on raise;
  no key in subprocess (assert `load_credentials` still reads plaintext path only).
- **bootstrap script** (`unit/test_oauth_bootstrap.py` new/extend): writes ciphertext; tolerates existing
  plaintext.
- **session** (`unit/test_auth_security.py` — the existing file, already calls `make_session`; +
  `integration/test_auth_session.py` new): AC-7 cookie flags
  (Secure/HttpOnly/SameSite; Secure absent only when override off); AC-8 absolute cap even with activity;
  AC-9 idle expiry + sliding refresh (freeze/advance time); AC-10 epoch mismatch → 401 + fresh token ok;
  AC-11 password change bumps epoch (other session dies, changer stays); AC-12 logout-all auth + 200;
  EC-5 skew; EC-6/Q2 pre-epoch token → 401.
- **rate-limit/lockout** (`unit/test_rate_limit.py` + `integration/test_auth_bruteforce.py` new): AC-13
  lockout after N fails incl. correct-password-still-429 + Retry-After + auto-clear; AC-14 success resets;
  AC-15 per-IP over-limit 429, other IP unaffected; AC-16 no email-existence disclosure + dummy-verify
  still runs; AC-17 thresholds read from config (monkeypatch a constant changes behavior); AC-20
  me/password rate-limited but not lockable; EC-7 self-DoS documented (behavioral: victim gets 429 not
  permanent lock); EC-8 lockout persists across a store re-open.
- **migration** (`integration/test_alembic_head.py` + new `test_migration_0007.py`): head is `0007`;
  upgrade adds columns + encrypts legacy plaintext row idempotently (run twice = stable); downgrade drops
  columns; AC-18 graph/pipeline suites still green (no node/edge/state change).

Frontend (`frontend/src/__tests__/`):
- `realProvider` 401 handling: an authenticated call returning 401 calls `handleSessionExpired`
  (cache-clear + `window.location.assign('/login')`), and the initial unauthenticated `me()` bootstrap
  401 does **not** redirect-loop (AC-19).
- `logoutAll` in both providers; Security-tab button calls it (settings test extend).
- `useJobStatus` treats 401 as terminal-for-session (stop polling) — extend `processing.test.tsx`.

Run: backend `python -X utf8 -m pytest` from `backend/`; frontend `npm test` from `frontend/`.

---

## 7. Delivery / smoke (constitution §9 + user's real-smoke rule)

After green tests, a real local smoke (documented in tasks): (a) connect a Google account, confirm the
DB `google_oauth_token` is ciphertext (no `refresh_token` in cleartext), a report still delivers to the
user's Drive + email (proves decrypt seam + central tempfile); (b) log in, idle > 30 min → next request
redirects to `/login`; change password in one browser → a second browser's session is logged out;
(c) 5 wrong passwords → 429 with Retry-After, correct password still blocked until it clears. This also
closes the still-open Gate-1 Drive-connect verification ([[project_security_phase_plan]]).

## 8. Out of scope (mirrors spec §5)

TLS/cert config (deployment), encryption of stored contracts/reports (Tier 3), Zero-Storage/PrivacyAgent/
audit/retention (Phase 2), KMS/Vault, CAPTCHA/MFA/SSO, and all Tier 2 items (prompt-injection, honest
LLM-failure surfacing, security headers/dep-scan, upload magic-byte hardening) → future **feature 033**.

## 9. Rollout / reversibility

- Encryption seam has no master toggle (once tokens are encrypted, decrypt is required); the key file must
  be backed up (document — losing it orphans tokens → users re-connect, graceful per EC-1).
- `AUTH_COOKIE_SECURE`, all TTL/idle/rate-limit values are env-overridable (AC-17). Session/lockout
  changes are additive DDL, downgradable via `0007` `downgrade()`.
- No graph, `ContractState`, checkpointer, or report-format change — the pipeline and its test suites are
  untouched (AC-18).
