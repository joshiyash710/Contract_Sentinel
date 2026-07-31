# Feature 032 — Security Hardening Tier 1

**Status:** spec (draft)
**Authorized by:** constitution §2 amendment (2026-07-31, feature 032) — OAuth-token
encryption at rest is now IN scope. Session/cookie hardening and login rate-limiting harden
already-in-scope authentication (§2 amendment 2026-07-14, feature 014) and need no further
constitutional change.

## 1. Problem statement

ContractSentinel now behaves like a real, trustworthy legal-AI SaaS (per-user accounts, per-user
Google Drive delivery, professional reports). Three concrete at-rest / auth weaknesses remain that
undercut that trust. This feature closes them. It is an **infrastructure / delivery-layer + auth-layer**
feature: it touches OAuth-token storage, the session cookie, and the login/signup endpoints. It adds
**no** LangGraph node or edge and **no** `ContractState` field (constitution §2 amendment mechanics;
§1 schema is unchanged — see §2 below).

The three weaknesses, all confirmed in code:

- **W1 — OAuth tokens are plaintext at rest.** The per-user `users.google_oauth_token` column
  (feature 031 — `user_store.py:33`, comment *"unencrypted interim"*) and the central
  `data/secrets/google_token.json` (feature 010 — `config.py:391`) both store a Google refresh token
  in cleartext. A refresh token is a long-lived credential to the user's Drive; disk/DB exfiltration =
  standing Drive access. This is the single highest at-rest exposure and the reason for the §2 amendment.
- **W2 — Session cookie is weak.** `AUTH_COOKIE_SECURE=False` (`config.py:502`), a **7-day** absolute
  TTL (`config.py:501`), **no idle timeout**, and **no server-side invalidation** — the JWT is
  stateless, so `logout` only deletes the browser cookie; a copied token stays valid for the full 7
  days, and changing the password does **not** end other sessions. The user explicitly asked for
  idle-timeout auto-logout.
- **W3 — No brute-force protection.** `POST /api/auth/login` and `/api/auth/signup` have no
  rate-limiting and no account lockout, so password guessing and signup abuse are unbounded.

Where this sits in the fixed architecture: entirely **outside** the 7-node graph — in the auth layer
(`app/api/auth.py`, `app/api/security.py`), the user/token store (`app/runner/user_store.py`), the
delivery credential layer (`app/delivery/oauth_credentials.py`, `app/delivery/mcp_servers/google_auth.py`),
and a small frontend change for the idle-logout UX. The pipeline, its nodes, checkpointing, and report
delivery semantics are untouched.

## 2. Inputs and outputs

### 2.1 Relationship to `ContractState` (001)

**This feature does not read or write `ContractState`** and adds no field to it. Per constitution §2
amendment mechanics, the DB `users.google_oauth_token` column is unchanged in *shape* (still a single
text column) — its *contents* change from plaintext JSON to a Fernet ciphertext token. The graph state
in `001-contract-state-schema.md` is therefore unaffected; §10 (spec-first change rule) is **not**
triggered.

### 2.2 W1 — OAuth-token encryption at rest

New encryption seam (utility module + config), transparent to callers:

- **Key material (input):** a Fernet key, resolved in this priority — env `CONTRACTSENTINEL_ENCRYPTION_KEY`
  → key file (default `data/encryption_key`, git-ignored, 0600 where supported) → generate-and-persist
  on first run. Mirrors the `AUTH_SECRET` bootstrap in `security.py:load_secret`. The key is **never**
  logged and **never** returned in any API response.
- **Encrypt-at-write / decrypt-at-read points (per-user token):**
  - Write: `UserStore.set_google_credentials(user_id, token_json, email)` stores `encrypt(token_json)`.
  - Read: `UserStore.get_google_credentials(user_id)` returns the **decrypted** plaintext JSON (callers
    — `delivery_step`, `integrations`, `oauth_credentials` — are unchanged and still receive plaintext).
- **Encrypt-at-write / decrypt-at-read points (central token):** the central token **is encrypted too**
  (resolved: the §2 feature-032 amendment mandates encrypting *both* the per-user column and the central
  file — it holds `gmail.send` + `drive.file` refresh). `data/secrets/google_token.json` is
  stored encrypted; the central-token consumers (`google_auth.load_credentials`, invoked in the MCP
  subprocess, and `scripts/oauth_bootstrap.py` / `scripts/delivery_smoke.py`) receive plaintext via the
  same decrypt seam. Because the MCP server runs as a **subprocess** that reads the token file directly
  with `Credentials.from_authorized_user_file` (plaintext-only), the parent process decrypts to a
  short-lived temp file before launching the subprocess and unlinks it afterward — reusing the existing
  per-user tempfile pattern (`oauth_credentials.write_token_tempfile`). See EC-3.
- **Migration (input: existing plaintext rows/files):** a one-way, idempotent migration so already-stored
  tokens are not orphaned. Two mechanisms, both required:
  1. **Read-side tolerance / lazy upgrade:** a value that fails Fernet decryption but parses as the
     expected token JSON is treated as legacy plaintext, used as-is, and re-encrypted on its next write.
  2. **Backfill:** an Alembic data migration (or an idempotent one-shot script) encrypts existing
     plaintext `users.google_oauth_token` values and the central token file in place.
- **Output/format:** ciphertext is the URL-safe base64 Fernet token string, stored in the **same** text
  column / same file path — the token-encryption change is itself DDL-free (contents change, column shape
  does not). The token **backfill** (encrypt existing plaintext values) is a **data step inside migration
  `0007`**; that same migration `0007` also carries the additive DDL for W2 (see §2.3 / §2.4). Migration
  ordering is fixed: **`0007` has `down_revision = "0006"`** (`0006_add_user_google_token` is the current
  Alembic head). See §2.6 for the consolidated description of migration `0007`.

- **New dependency:** Fernet comes from the `cryptography` library. It is currently only a *transitive*
  dependency of the stack, so this feature promotes it to a **first-class declared dependency** in
  `pyproject.toml` (and `002-tech-stack.md` §3/§4 is updated to list it, per the constitution's
  spec-first discipline for the dependency surface). To be explicit against tech-stack §5.5: `cryptography`
  / Fernet is a **symmetric-crypto primitive**, **not** the "dedicated KMS/Vault key management" that §5.5
  and the constitution PERMANENTLY-CUT list exclude — the key lives in a single env var / local file, with
  no external key-management service. This dependency addition is authorized by the §2 feature-032
  amendment.

### 2.3 W2 — Session/cookie hardening

Changes to the session cookie and `require_auth`; no new endpoint shape beyond the two below.

- **Secure flag:** `AUTH_COOKIE_SECURE` becomes environment-driven and **defaults to `True`**; it is set
  `False` only for local plaintext-HTTP dev via an explicit env override. Because a `Secure` cookie is
  dropped by browsers over plain HTTP, this depends on TLS in front of the app (TLS itself is
  deployment/ops — see §5 Out of scope).
- **Absolute lifetime cap:** `AUTH_SESSION_TTL_SECONDS` reduced from 7 days to a shorter absolute cap
  (proposed **8 hours**, config-driven). This is the maximum a session can live regardless of activity.
- **Idle timeout (sliding session):** a session is invalid after `AUTH_IDLE_TIMEOUT_SECONDS` (proposed
  **30 minutes**) of no authenticated requests. Implemented server-side: the JWT carries a `last_active`
  (or is re-issued) and `require_auth` (a) rejects a token whose idle window has elapsed → 401, and
  (b) on a valid request re-issues the cookie with a refreshed idle window, never exceeding the absolute
  cap. The cookie `max_age` tracks the idle window so the browser also drops it. Activity = any
  authenticated `/api/*` request.
- **Server-side invalidation ("logout everywhere") / session epoch:** a per-user monotonic
  `session_epoch` (integer, new `users` column, default 0) is embedded in the JWT at issue time.
  `require_auth` rejects any token whose `session_epoch` ≠ the user's current stored value → 401.
  Incrementing the user's `session_epoch` invalidates **all** outstanding sessions for that user. It is
  incremented by:
  - `POST /api/auth/me/password` (feature 023 change-password) — a password change now ends all other
    sessions (was explicitly *not* the case in 023 D3; this feature supersedes that for security).
  - a new `POST /api/auth/logout-all` endpoint (authenticated) — "sign out of all devices".
- **`POST /api/auth/logout`** stays as-is functionally (clears this browser's cookie) but is documented
  as single-device; whole-account revocation is `logout-all`.

### 2.4 W3 — Login/signup rate-limiting & account lockout

A rate-limit/lockout layer applied to `POST /api/auth/login` and `POST /api/auth/signup`. The
authenticated `POST /api/auth/me/password` endpoint (which verifies `current_password`) **also gets the
per-IP rate limit** to blunt online guessing of the current password, but **not** the per-account
lockout (a session-holder locking their own account is pointless, and lockout there would be a footgun).

- **Per-account lockout:** after `AUTH_LOCKOUT_MAX_FAILURES` (proposed **5**) consecutive failed logins
  for a given email within `AUTH_LOCKOUT_WINDOW_SECONDS` (proposed **15 min**), further login attempts
  for that email are rejected with **429** for `AUTH_LOCKOUT_DURATION_SECONDS` (proposed **15 min**),
  regardless of whether the next password is correct. A successful login resets the counter.
- **Per-IP rate limit:** login and signup are limited to `AUTH_RATE_LIMIT_MAX` (proposed **10**) attempts
  per `AUTH_RATE_LIMIT_WINDOW_SECONDS` (proposed **60 s**) per client IP → **429** beyond that. This caps
  distributed guessing and signup spam.
- **Response discipline:** lockout/limit responses reuse the generic `401 "Invalid email or password"`
  wording where possible but use **429** with a `Retry-After` header when throttled, and must **not**
  reveal whether an email exists (preserve feature 014 M2 timing-equalization; the unknown-email path
  still runs a bcrypt verify).
- **Storage:** counters are keyed by email and by client IP. Given single-node SQLite Phase-1 scope
  (tech-stack §f), an in-process store is acceptable for the per-IP window; the per-account lockout
  state should survive a restart (persisted in the `users` row or a small table) so a lockout is not
  trivially cleared by bouncing the process. Final persistence choice is a plan decision (Open Q3).
- **Config:** every threshold above is a named constant in `app/config.py` (constitution §3), overridable
  by env; no value is hardcoded in endpoint logic.

### 2.5 Frontend output (idle-logout UX only)

The only frontend change: when an authenticated request returns 401 due to idle/absolute expiry or
epoch invalidation, the app clears the current-user cache and redirects to `/login` (reusing the
existing hard-nav logout path from the account-switch fix, commit `32cbd03`). Optionally a brief
"signed out due to inactivity" notice. No other UI redesign.

### 2.6 Alembic migration `0007` (single, consolidated)

There is exactly **one** new migration for this feature, `0007`, with `down_revision = "0006"`
(`0006_add_user_google_token` is the current head). It performs, in order:

1. **DDL (additive, reversible):** add `users.session_epoch INTEGER NOT NULL DEFAULT 0` (W2, §2.3), and
   the per-account lockout-state storage (W3, §2.4 — a small additive set of `users` columns and/or a
   dedicated `login_attempts` table; exact shape is a plan decision, but it lives in this migration).
2. **Data (idempotent):** backfill — encrypt any existing plaintext `users.google_oauth_token` values in
   place (W1, §2.2). Running the migration on a DB with already-encrypted or NULL values is a no-op for
   those rows (no double-encryption). The central `google_token.json` file backfill is handled by an
   idempotent one-shot at first use / a helper script (a file, not DB, so outside Alembic).

`upgrade()` and `downgrade()` both apply cleanly to an existing DB; `downgrade()` drops the added
column(s)/table (the encrypted token values are left as-is — downgrade does not attempt to decrypt).

## 3. Acceptance criteria

Encryption (W1):
- **AC-1** A round-trip through the encryption util (`encrypt` then `decrypt`) returns the original
  plaintext; `decrypt` of a value not produced by the current key raises (caught by the legacy-tolerance
  path, AC-5), never returns garbage silently.
- **AC-2** After `UserStore.set_google_credentials(u, token_json, email)`, the raw stored DB value is
  **not** equal to `token_json` and does **not** contain the substring `"refresh_token"` in cleartext;
  `get_google_credentials(u)` returns exactly the original `token_json`.
- **AC-3** After a central-token write, the on-disk `google_token.json` bytes are ciphertext (do not
  contain `"refresh_token"` in cleartext); the delivery path still obtains valid, refreshable
  credentials (existing delivery round-trip tests pass unchanged).
- **AC-4** The Fernet key is resolved by the documented precedence (env → key file → generate+persist);
  a generated key file is created with 0600 where the OS supports it; neither the key value **nor the
  decrypted token JSON** (the actual credential) ever appears in any log record or API response body
  (asserted).
- **AC-5** A pre-existing plaintext token value (DB or file, written before this feature) is still
  usable: it is read successfully and, on its next write, is stored encrypted. The backfill migration
  is idempotent — running it twice leaves already-encrypted values unchanged and does not double-encrypt.
- **AC-6** Disconnect (`clear_google_credentials`) and revoke (`oauth_credentials.revoke_token`) continue
  to work: the token is decrypted before the Google revoke call and the row is nulled.

Session/cookie (W2):
- **AC-7** With the default config, the login/signup `Set-Cookie` carries `HttpOnly`, `SameSite=Lax`,
  and `Secure`; `Secure` is absent only when the dev override disables it.
- **AC-8** A session older than the absolute cap (`AUTH_SESSION_TTL_SECONDS`) is rejected with 401 even
  with continuous activity.
- **AC-9** A session idle longer than `AUTH_IDLE_TIMEOUT_SECONDS` (no authenticated requests in that
  window) is rejected with 401; a request within the window succeeds **and** refreshes the idle window
  (a subsequent request one idle-window-minus-epsilon later still succeeds).
- **AC-10** Incrementing a user's `session_epoch` (via `logout-all` or password change) causes every
  previously issued token for that user to return 401 on the next request, while a freshly issued token
  (post-increment) succeeds.
- **AC-11** `POST /api/auth/me/password` (correct current password) rotates `session_epoch`, so a second
  browser's existing session for that account is invalidated; the changing browser receives a fresh valid
  cookie and stays logged in.
- **AC-12** `POST /api/auth/logout-all` requires auth (401 without a session), increments the epoch, and
  returns 200.

Rate-limit / lockout (W3):
- **AC-13** `AUTH_LOCKOUT_MAX_FAILURES` consecutive wrong-password logins for one email cause the
  next attempt — **even with the correct password** — to be rejected with 429 + `Retry-After` for the
  configured duration; after the duration elapses the correct password succeeds.
- **AC-14** A successful login before the threshold resets the failure counter (no premature lockout).
- **AC-15** More than `AUTH_RATE_LIMIT_MAX` login (or signup) attempts from one IP within the window
  return 429; a different IP is unaffected in the same window.
- **AC-16** Lockout/limit responses do not disclose whether the email exists (same body for
  locked-existing vs locked-nonexistent within the lockout path) and the unknown-email path still runs a
  bcrypt verify (feature 014 M2 preserved).
- **AC-17** All thresholds (AC-8/9/13/15 values) are read from `app/config.py` named constants, not
  hardcoded in `auth.py`; overriding the env var changes the behavior without a code edit.

- **AC-20** `POST /api/auth/me/password` is subject to the per-IP rate limit (429 beyond
  `AUTH_RATE_LIMIT_MAX` in the window) but is **not** subject to per-account lockout.
- **AC-21** The decrypt-to-tempfile path for the central token (EC-3) removes the plaintext temp file in
  a `finally` even when the delivery call raises; after a delivery attempt (success or exception) no
  `cs_usertoken_*` / central-token plaintext temp file remains on disk.

Cross-cutting:
- **AC-18** No LangGraph node/edge is added or changed; the graph compiles and the existing pipeline /
  delivery test suites pass unchanged. No `ContractState` field is added. All schema/data change is
  carried by the single Alembic migration `0007` described in §2.6 (`down_revision = "0006"`): additive
  DDL (`users.session_epoch` + lockout-state storage) plus the idempotent token backfill. `0007`
  `upgrade()` and `downgrade()` both apply cleanly on an existing DB (downgrade drops the added
  columns/table; it does not decrypt token values). `cryptography` is added to `pyproject.toml` and
  `002-tech-stack.md`.
- **AC-19** Frontend: an authenticated fetch that 401s due to session expiry/epoch redirects to `/login`
  and clears the current-user cache (no infinite retry loop; polling hooks tolerate the 401 as terminal
  for the session — consistent with the 2026-07-28 polling-resilience fix).

## 4. Edge cases

- **EC-1 — Missing/rotated encryption key.** If `CONTRACTSENTINEL_ENCRYPTION_KEY` is set but wrong (was
  rotated), every stored token fails Fernet decryption *and* fails the legacy-plaintext JSON check →
  treated as "not connected / needs re-auth" (delivery falls back to email-only per 031; central token
  → `CredentialsError` → honest delivery failure), never a crash or a fake success. Key rotation without
  re-encrypting existing tokens is a documented operational consequence, not silently masked.
- **EC-2 — Partial/corrupt ciphertext.** A truncated or tampered token value fails decryption; handled
  identically to EC-1 (not connected). Never surfaced to the user as their real token.
- **EC-3 — MCP subprocess needs plaintext.** The Drive/Gmail MCP server is a separate process reading the
  token file directly; the parent must materialize a decrypted temp file (0600, caller-unlinked in a
  `finally` after the call returns — existing pattern) and must ensure it is removed even on exception.
  A leaked plaintext temp token is a regression this feature must guard (AC-3 area).
- **EC-4 — Idle-timeout vs. long pipeline run.** A contract analysis can take minutes with no user
  interaction, but progress polling (`GET /api/jobs/{id}`) **is** authenticated activity, so an active
  watcher keeps the session alive; a user who closes the tab during a long run and returns after the idle
  window is correctly logged out. Confirm the polling cadence < idle window so a watching user is never
  logged out mid-run (30-min idle ≫ poll interval — safe).
- **EC-5 — Clock skew / `last_active` in the future.** Idle/absolute checks must tolerate small skew and
  never treat a slightly-future timestamp as an infinite session; bound both ends.
- **EC-6 — Epoch column absent on legacy rows.** Rows created before migration `0007` get
  `session_epoch = 0` (column default). The handling of pre-feature tokens that carry no epoch claim
  (accept as epoch 0 vs. force re-login) is the single decision tracked in Open Q2 — not a separate one.
- **EC-7 — Lockout self-DoS.** An attacker could lock a victim's account by failing logins on their
  email. Mitigation: lockout returns 429 (temporary, auto-clears), the legitimate user is told to retry
  after `Retry-After`, and per-IP limiting blunts targeted lockout spam. Accepted Phase-1 tradeoff (no
  CAPTCHA — Open Q3); documented, not hidden.
- **EC-8 — Rate-limit counters lost on restart.** Per-IP in-memory windows reset on process restart
  (acceptable — a short window). Per-account lockout, if in-memory only, would also reset — so lockout
  state is persisted (see §2.4 / Open Q3) to prevent trivial reset-by-restart.
- **EC-9 — Multiple uvicorn workers.** In-process counters are per-worker; with >1 worker the effective
  limit multiplies. Phase-1 runs single-process (tech-stack §f, `RUNNER_WORKER_CONCURRENCY=1` context);
  document that horizontal scaling would need shared counter storage (out of scope, noted).
- **EC-10 — Secure cookie over local HTTP.** With `AUTH_COOKIE_SECURE=True` default, a developer running
  plain `http://localhost` would have the browser drop the cookie and appear unable to log in. The dev
  env override (`AUTH_COOKIE_SECURE=False`) must be documented prominently so local dev is not broken.
- **EC-11 — Empty/oversized inputs.** Encrypting an empty/`None` token is a no-op that stores `NULL`
  (not `encrypt("")`); `get` of a `NULL` returns `None` (still "not connected").

## 5. Out of scope

- **TLS / HTTPS termination** — deployment/ops concern (reverse proxy or uvicorn TLS). This feature makes
  the cookie *ready* for TLS (`Secure` default True) and documents the dependency, but does not configure
  certificates or a proxy. Owned by deployment docs, not a spec file.
- **Encryption at rest for stored contracts, extracted text, and reports** — explicitly DEFERRED (Tier 3;
  constitution §2 amendment "Stays DEFERRED"). This feature encrypts **OAuth tokens only**.
- **Zero Storage mode, PrivacyAgent, audit log, retention/delete-my-data** — Phase-2 DEFERRED
  (constitution §2). No audit log of security events beyond ordinary application logging.
- **KMS / Vault / key rotation automation** — PERMANENTLY CUT (constitution §2; tech-stack §5.5). The key
  seam is a single env/file value; rotation is a manual op, not an automated subsystem.
- **CAPTCHA, email-based 2FA/MFA, device fingerprinting, IP allow/deny lists** — not in Tier 1.
- **Google SSO login** — still deferred (feature 014); this feature does not touch the login *method*.
- **RBAC / roles / teams / cross-account sharing** — PERMANENTLY CUT.
- **Prompt-injection defense, honest-LLM-failure surfacing, security headers (CSP/HSTS), dependency
  scanning, upload magic-byte hardening** — these are **Tier 2**, owned by a fast-follow feature (033),
  not this one.

## 6. Open questions

All resolved by the owner on 2026-07-31 (each chose the recommended default). Recorded here as the
finalized config defaults; every value remains an env-overridable named constant in `app/config.py`.

- **Q1 — Idle timeout and absolute cap values.** **RESOLVED → 30 min idle / 8 h absolute.**
  `AUTH_IDLE_TIMEOUT_SECONDS = 1800`, `AUTH_SESSION_TTL_SECONDS = 8 * 3600` (down from the current 7 days).
- **Q2 — Legacy tokens (pre-epoch) on upgrade.** **RESOLVED → (b) force a one-time re-login.** A JWT with
  no `session_epoch` claim is rejected by `require_auth` (401), so all pre-feature sessions re-authenticate
  once under the new rules. Clean baseline (drives AC-10/EC-6).
- **Q3 — Lockout persistence & CAPTCHA.** **RESOLVED → persist per-account lockout to the DB; no CAPTCHA
  in Tier 1.** Lockout state survives a process restart (cannot be cleared by bouncing the server); the
  EC-7 self-DoS tradeoff is accepted and documented.
- **Q4 — Rate-limit thresholds.** **RESOLVED → 5 failures → lockout; 10 attempts / 60 s per IP.**
  `AUTH_LOCKOUT_MAX_FAILURES = 5`, `AUTH_RATE_LIMIT_MAX = 10`, `AUTH_RATE_LIMIT_WINDOW_SECONDS = 60`
  (lockout window/duration per §2.4 defaults: 15 min each).

(An earlier draft's "encrypt the central token too" question is resolved inline in §2.2 per the §2
amendment — the central token is encrypted.)
