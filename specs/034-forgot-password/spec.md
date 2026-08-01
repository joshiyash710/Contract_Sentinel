# Feature 034 — Forgot-Password (emailed time-limited reset link)

## Problem statement

The single-user auth gate (feature 014 amendment; hardened by 023 password-change
and 032 session/rate-limit work) has **no self-service password recovery**: a user
who forgets their password is locked out with no path back in except a manual DB
edit. This feature adds a standard **forgot-password → emailed reset link → set new
password** flow.

Placement in the fixed architecture: this is **auth-surface only**. It adds **no
LangGraph node/edge and no `ContractState` field** (constitution §2). It is
authorized under the **014 amendment** (single-user login gate is in scope) and the
**031 amendment** (central Gmail sending is in scope) — exactly the basis on which
feature 032's session hardening and rate-limiting were added with **no
constitutional amendment required**. The reset email is sent through the **central
Gmail** MCP path (feature 010/030/032), never per-user Gmail.

Security posture mirrors the existing auth code:
- **No email-existence disclosure** — the request endpoint returns an identical
  generic response whether or not the email is registered (mirrors 014 M2 /
  `is_locked`/`record_login_failure` "unknown email → no-op, no disclosure").
- **Single-use, time-limited, hashed** reset tokens (the raw token lives only in the
  emailed link; the DB stores a hash).
- **Session invalidation on reset** — a successful reset **bumps `session_epoch`**
  (feature 032, W2) so every outstanding session for that account is logged out.
- **Rate-limited** — per-IP (reusing the 032 `RateLimiter`) plus a per-email send
  throttle to prevent mailbombing a victim.

## Inputs and outputs

This feature crosses HTTP + DB + MCP boundaries, so all request/response bodies are
**Pydantic** models (constitution §4). It does **not** touch the TypedDict graph
state in `specs/001-contract-state-schema.md` — no `ContractState` field is read or
written, and no reducer/field is added there.

### New endpoints (on the unguarded `auth_router`, prefix `/api/auth`)

**`POST /api/auth/forgot-password`**
- Request `ForgotPasswordRequest`: `{ email: str }` (validator normalizes
  `strip().lower()`, mirroring `LoginRequest`).
- Response: **always** `200` with a fixed generic body
  `{ "ok": true, "message": "If an account exists for that email, a reset link has been sent." }`
  — identical for known and unknown emails (AC-2/AC-3). Never returns 404/409.
- `429 + Retry-After` when the per-IP limit is exceeded (AC-6).

**`POST /api/auth/reset-password`**
- Request `ResetPasswordRequest`: `{ token: str, new_password: str }`
  (`new_password` reuses `_validate_password`: `AUTH_PASSWORD_MIN..MAX`).
- Response: `200 { "ok": true }` on success (AC-10). No session cookie is set
  (AC-17). `400 { "detail": "Invalid or expired reset link." }` — a single generic
  message for unknown/expired/used/tampered tokens (AC-12/13/14).
- `429 + Retry-After` when the per-IP limit is exceeded (AC-16).

### New persistence — Alembic migration `0008` (down_revision literal `"0007"`)

A new table `password_reset_tokens` (a table, not `users` columns — Decision 2):

| column | type | notes |
|--------|------|-------|
| `id` | TEXT PK | uuid4 |
| `user_id` | TEXT | FK-by-convention to `users.id` (no hard FK, mirroring existing store style) |
| `token_hash` | TEXT | `HMAC-SHA256(AUTH_SECRET, raw_token)` hex — **never** the raw token (Decision 2) |
| `created_at` | TEXT | ISO-8601 UTC |
| `expires_at` | TEXT | ISO-8601 UTC = created_at + `AUTH_RESET_TOKEN_TTL_SECONDS` |
| `used_at` | TEXT NULL | set when consumed; NULL = unused |

Index on `token_hash` (lookup) and `user_id` (invalidation/cleanup). Migration is
purely additive (new table); `downgrade` drops it. New `PasswordResetStore` (or
methods on a store) owns all SQL, mirroring `UserStore`'s lock/connection pattern.

### New configuration (constitution §3 — named constants in `app/config.py`)

```python
AUTH_RESET_TOKEN_TTL_SECONDS: int = _env_int("AUTH_RESET_TOKEN_TTL_SECONDS", 30 * 60)   # 30 min
AUTH_RESET_TOKEN_BYTES: int = 32                       # secrets.token_urlsafe(32) → ~43-char token
AUTH_RESET_EMAIL_COOLDOWN_SECONDS: int = _env_int("AUTH_RESET_EMAIL_COOLDOWN_SECONDS", 60)
FRONTEND_RESET_URL: str = "http://localhost:3000/reset"  # mirrors FRONTEND_INTEGRATIONS_URL (config.py:450)
```
Per-IP limits reuse the existing `AUTH_RATE_LIMIT_MAX` / `AUTH_RATE_LIMIT_WINDOW_SECONDS`.

### Reset link

`f"{FRONTEND_RESET_URL}?token={raw_token}"`. The frontend `/reset` page reads
`?token=` and POSTs it with the new password to `/api/auth/reset-password`.

### Frontend (Next.js, `frontend/src/`)

- A **"Forgot password?"** link on `/login` → a `/forgot-password` page: email field →
  `POST /api/auth/forgot-password` → always shows the same generic confirmation.
- A **`/reset`** page: reads `?token=`, shows a new-password (+ confirm) form →
  `POST /api/auth/reset-password` → on success redirect to `/login` with a success
  flash; on 400 show the generic "invalid or expired" message with a link back to
  `/forgot-password`.

## Acceptance criteria

Backend criteria are FastAPI `TestClient` tests with the Gmail send path stubbed and
a temp DB; timing/rate tests use the injected `RateLimiter`. Each is directly
testable.

### Request endpoint — `POST /api/auth/forgot-password`

> **Timing / testability model (applies to AC-1..AC-10a).** The synchronous handler
> does *identical* work for known and unknown emails: validate + normalize the email,
> perform **one** `get_by_email` lookup, then — only if a row exists **and** the email
> is not within its send-cooldown — schedule a **single FastAPI `BackgroundTask`** that
> performs all side effects (cleanup → invalidate prior → issue new token → send email).
> The slow Gmail round-trip therefore never runs on the synchronous path (no timing
> oracle, Decision 4/AC-10a). FastAPI's `TestClient` **executes background tasks before
> returning the response**, so AC-1/AC-4/AC-5/AC-7 are asserted on the post-task DB /
> mail-stub state deterministically.

- **AC-1** A registered email → `200` generic body **and**, after the background task
  runs, exactly one reset email is sent via the central Gmail send path, addressed to
  that email, whose body contains `FRONTEND_RESET_URL?token=<raw>`.
- **AC-2** An unregistered email → `200` with the **same** generic body; **no**
  background task is scheduled, **no** email is sent, and **no** `password_reset_tokens`
  row is created (and no `users` row).
- **AC-3** The HTTP status and response body are **byte-identical** for the known and
  unknown cases — and also for the cooldown-suppressed case (AC-7) — so the response
  never discloses existence. (Assert the three bodies are equal byte-for-byte.)
- **AC-4** For a known email, the background task writes a `password_reset_tokens` row
  with `token_hash = HMAC-SHA256(AUTH_SECRET, raw)` (assert the raw token is **not**
  present anywhere in the DB), `expires_at = created_at + AUTH_RESET_TOKEN_TTL_SECONDS`,
  `used_at IS NULL`, and `user_id` = the resolved user's id.
- **AC-5** Issuing a new token for a user first **invalidates prior outstanding tokens**
  for that user by setting their `used_at` (mark-used, not delete — keeps AC-12/AC-20
  semantics uniform); only the newest link is redeemable. Invalidation runs inside the
  known-email background task only (never a synchronous branch on existence).
- **AC-6** Exceeding `AUTH_RATE_LIMIT_MAX` requests from one IP → `429` with a
  `Retry-After` header (reuses `_enforce_ip_rate_limit`).
- **AC-7** Repeated requests for the **same email** within
  `AUTH_RESET_EMAIL_COOLDOWN_SECONDS` schedule **no** background task, so **no**
  additional email is sent and **no** new token is issued (the prior link stands),
  while still returning the byte-identical generic `200` (AC-3). The cooldown is keyed
  by email in server-side memory and is established only for known emails, so it is not
  probeable to distinguish known vs unknown (an unknown email schedules nothing either
  way → identical observable behavior).
- **AC-8** The email is built with a subject, a branded **HTML** body, and a
  **plaintext** fallback, both containing the reset URL; it is sent through the
  **central** Gmail token (feature 032 `materialize_central_token_tempfile`), not a
  per-user token. Because the central send path is `async`, the background task runs it
  correctly (e.g. `asyncio.run` inside the task) and **mirrors the decrypted-central-
  token tempfile cleanup** (`os.unlink`) so the reset path leaks no plaintext token file.
- **AC-9** If the Gmail send fails (e.g. `invalid_grant`, missing central token), the
  endpoint still returns the generic `200` and does **not** raise; the failure is
  logged only. (The token row is still written, so a re-request is not required by a
  transient send failure.)
- **AC-10a** The synchronous response is constant-work regardless of existence: the
  only difference between a known and unknown email is whether a `BackgroundTask` is
  *scheduled* (negligible, no I/O), never whether the slow SMTP send runs inline — so
  request timing does not disclose existence.

### Reset endpoint — `POST /api/auth/reset-password`

- **AC-10** A valid, unused, unexpired token + a policy-valid `new_password` → `200`;
  afterwards the new password verifies and the old one does not.
- **AC-10b** The reset applies to the user identified by the **token row's own
  `user_id`** — the request body carries `{token, new_password}` and **no** email/user
  identifier, so a valid token can never be redirected to change a different account's
  password. The lookup is by `token_hash = HMAC-SHA256(AUTH_SECRET, token)`.
- **AC-11** A successful reset **bumps the user's `session_epoch`**; a JWT minted
  before the reset now fails `require_auth` (401) — all prior sessions are logged out.
- **AC-12** The token is **single-use**: a second `reset-password` with the same token
  → `400` generic; the password is not changed again.
- **AC-13** An **expired** token (`now > expires_at`) → `400` generic; password
  unchanged; no epoch bump.
- **AC-14** An **unknown/tampered** token → `400` with the **same** generic message as
  expired/used (no distinction leaked).
- **AC-14b** A token whose `user_id` points at a **since-deleted user** → the same
  `400` generic message; no crash, no password write, no epoch bump.
- **AC-15** A `new_password` violating `AUTH_PASSWORD_MIN..MAX` → validation error
  (`422`), and the token is **NOT** consumed (the user can retry with the same link).
- **AC-16** Exceeding the per-IP limit on `reset-password` → `429 + Retry-After`. This
  is belt-and-suspenders: the primary defense against token brute-force is the ~256-bit
  token entropy + 30-min TTL + single-use (Decision 1), not the shared per-IP limiter.
- **AC-17** Reset sets **no** session cookie — the user is not auto-logged-in; they
  must log in with the new password (and all old sessions are already dead via AC-11).
- **AC-18** Both endpoints are **unauthenticated** (no `require_auth`); they work with
  no session cookie and also work unchanged if a session cookie is present.

### Non-regression

- **AC-19** The logged-in password-change flow (`POST /api/auth/me/password`, 023/032)
  and all existing auth behavior are unchanged.
- **AC-20** Opportunistic cleanup: inside the known-email background task, **before**
  issuing the new token, expired/used token rows **for that resolved `user_id` only**
  are deleted (scoped, O(user's rows), under the store mutex — never a global
  full-table sweep; no scheduled job). Order within the task: cleanup → invalidate
  prior (AC-5) → issue new (AC-4) → send (AC-8).

## Edge cases

- **Known email but Gmail send fails** (expired refresh token / central token absent):
  the token row is still written and the response is still generic `200`; the user
  simply never receives the mail and can re-request. Logged, never raised (AC-9). See
  memory: `invalid_grant` is the usual real-world cause — an ops concern, not a bug.
- **Concurrent forgot-password for the same user**: two requests each write a token
  and each invalidates older ones — benign last-writer-wins; both hashes are distinct;
  at most the newest remains redeemable. No locking beyond the store's existing mutex.
- **Token points at a since-deleted user**: `reset-password` resolves the token but
  the user no longer exists → `400` generic (treated like an invalid token).
- **Reused/expired/tampered token**: all collapse to the single `400` generic message
  (AC-12/13/14) — no oracle distinguishing "wrong" from "expired" from "used".
- **`new_password` == old password**: allowed (not worth a compare that leaks nothing);
  the reset still succeeds and bumps epoch. (No history check — out of scope.)
- **Password-policy failure after clicking the link** (AC-15): the token is preserved
  (not marked used) so the user can submit a valid password with the same link before
  it expires.
- **Very long / non-string / whitespace token input**: Pydantic coerces/validates to
  `str`; a hash miss → `400` generic. No unbounded work.
- **Clock skew on `expires_at`**: the 30-min TTL dwarfs allowed skew; expiry is
  compared strictly in UTC (no skew leniency needed, unlike the JWT idle check).
- **Rate-limit / cooldown state is per-process, in-memory** (mirrors 032 `RateLimiter`
  EC-8): it resets on restart and is per-worker under multiple uvicorn workers.
  Phase-1 runs single-process — acceptable. The token table itself is durable (a
  restart never resurrects a used/expired token).
- **Mailbomb attempt**: the per-email cooldown (AC-7) plus prior-token invalidation
  (AC-5) bound how many mails a target can receive.
- **TLS/`AUTH_COOKIE_SECURE`**: unaffected — reset sets no cookie (AC-17); the user
  logs in through the existing (already-hardened) login path afterward.

## Out of scope

- **Any LangGraph node/edge, `ContractState`, or pipeline change** — none occur; this
  is auth-surface only (constitution §2/§10). If that turns out false, STOP and amend
  `001` first.
- **Per-user Gmail** — the reset email is sent from the **central** app Google account
  (031 amendment keeps `gmail.send` central); this is not per-user email.
- **SMS / TOTP / MFA / security-question recovery** — password-by-email only.
- **Password-strength scoring, breach (HIBP) checks, password-history/reuse
  prevention** — future hardening, not here; policy stays `AUTH_PASSWORD_MIN..MAX`.
- **A scheduled cleanup job / retention policy for tokens** — remains **Phase-2
  DEFERRED** (retention policy). Only opportunistic purge (AC-20) is in scope.
- **Distributed / cross-worker rate-limit or token state** — single-process only,
  same posture as 032 (EC-8).
- **Changing the logged-in password-change flow** (`/me/password`, owned by 023/032)
  or the login/lockout flow (owned by 014/032) — unchanged.
- **Real SSO / OAuth login** — still deferred (014); this is email+password recovery.
- **Email deliverability/SPF/DKIM/bounce handling** — ops, not code.

## Resolved decisions

All open questions were resolved inline (owner preference for inline decisions with
rationale rather than blocking prompts). No open questions remain.

1. **Emailed link, not a 6-digit code.** A single-use token embedded in a link to the
   frontend `/reset` page (owner already chose "link over code" in planning). Token =
   `secrets.token_urlsafe(AUTH_RESET_TOKEN_BYTES)` (~43 chars, ~256-bit entropy) →
   brute-force infeasible; the per-IP limit (AC-16) is belt-and-suspenders.

2. **Separate `password_reset_tokens` table, storing an HMAC.** A table (not `users`
   columns) cleanly supports single-use marking, prior-token invalidation, and
   opportunistic cleanup without bloating `users`. The DB stores
   **`HMAC-SHA256(AUTH_SECRET, raw)`** (key from `security.load_secret`), not the raw
   token and not a bare hash: HMAC binds the stored value to the app secret so a DB
   leak **alone** cannot be used to precompute or forge a lookup, directly mirroring
   032 W1's "secret-keyed, never store the secret in the clear" discipline. (Bare
   SHA-256 would be adequate for a 256-bit random token, but HMAC costs nothing extra
   and is the stronger, consistent choice.)

3. **TTL = 30 min** (`AUTH_RESET_TOKEN_TTL_SECONDS`, env-overridable) — matches the
   planning note; short enough to bound exposure, long enough to be usable.

4. **No email-existence disclosure, enforced two ways.** (a) The request endpoint
   returns a byte-identical generic `200` for known / unknown / cooldown-suppressed
   cases (AC-3); (b) **all** side effects for a known email — cleanup, prior-token
   invalidation, new-token write, and the Gmail send — run inside a **single FastAPI
   `BackgroundTask`** (ordered per AC-20). The synchronous handler does identical work
   in every case (normalize + one `get_by_email`); the only divergence is whether a
   background task is *scheduled*, which performs no inline I/O — so neither the
   response body nor the response timing branches on existence (AC-10a). Under
   `TestClient` the task is drained before the response returns, keeping AC-1/4/5/7
   deterministically testable. This mirrors 014 M2's timing-equalization intent with a
   mechanism suited to the slow-email path.

5. **Reset bumps `session_epoch`; no auto-login.** On success we call the existing
   `bump_session_epoch` (feature 032) so every outstanding session dies (AC-11), and we
   set **no** new cookie (AC-17). Rationale: whoever triggered the reset proves control
   of the mailbox, but forcing a fresh login with the new password is the safer default
   and reuses the hardened login path. (Auto-login was considered and rejected.)

6. **Works logged-in or logged-out; rate-limited on both endpoints.** The two endpoints
   are public (no `require_auth`, AC-18); per-IP limiting reuses `_enforce_ip_rate_limit`
   / `RateLimiter`, and a per-email cooldown (AC-7) plus prior-token invalidation (AC-5)
   prevent mailbombing. A logged-in user who resets is simply logged out everywhere by
   the epoch bump.

7. **Password-policy failure preserves the token** (AC-15) so a mistyped weak password
   doesn't burn the user's only link before it expires; the token is marked used only
   on a fully successful reset.

## Open questions

None — all seven decisions above were resolved inline. This spec is final pending
review approval.
