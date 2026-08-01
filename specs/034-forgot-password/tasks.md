# Feature 034 — Forgot-Password — Tasks

Implements `specs/034-forgot-password/plan.md` (spec + plan spec-reviewer-APPROVED).
Auth-surface only: **no `graph/`, no `ContractState`, exactly ONE Alembic migration (0008).**

**Conventions for the implementer (constitution §7, §8):**
- TDD: write each `T*-test`, **run it and confirm it FAILS** before the impl task that follows. Never
  weaken a test to pass — fix the code.
- Run backend tests from `backend/` with `python -X utf8 -m pytest <path> -q`.
- Secrets discipline (S3): never log the raw reset token, `AUTH_SECRET`, or a password.
- The two response bodies must be **module constants** so byte-equality (AC-3) is provable:
  `_GENERIC_RESET_MSG = "If an account exists for that email, a reset link has been sent."` and
  `_GENERIC_RESET_BAD = "Invalid or expired reset link."`.
- Do not touch existing auth paths (login/signup/logout/me/password) — AC-19.

---

## Phase A — Config (no test)

- **T1** In `app/config.py` (near the AUTH block ~L534-577) add the four constants from plan §1 exactly:
  `AUTH_RESET_TOKEN_TTL_SECONDS` (`_env_int`, default `30*60`), `AUTH_RESET_TOKEN_BYTES = 32`,
  `AUTH_RESET_EMAIL_COOLDOWN_SECONDS` (`_env_int`, default `60`),
  `FRONTEND_RESET_URL = "http://localhost:3000/reset"`.

---

## Phase B — Migration 0008 + head test

- **T2** Create `alembic/versions/0008_password_reset_tokens.py`: `revision = "0008"`,
  `down_revision = "0007"`. `upgrade()` → `op.create_table("password_reset_tokens", ...)` with columns
  `id TEXT PK, user_id TEXT NOT NULL, token_hash TEXT NOT NULL, created_at TEXT NOT NULL,
  expires_at TEXT NOT NULL, used_at TEXT NULL` + `op.create_index("ix_prt_token_hash", ...,
  ["token_hash"])` and `ix_prt_user_id` on `["user_id"]`. `downgrade()` drops indexes + table.
- **T3** In `tests/integration/test_alembic_head.py` update the head assertion `"0007"`→`"0008"` (~L78)
  AND rename `test_current_head_is_0007`→`_0008` + its docstring (L69-70). Run it → green (proves the
  migration graph resolves to a single head 0008).

---

## Phase C — Token helpers (`app/api/security.py`) — TDD

- **T4-test** `tests/unit/test_reset_token.py` (run → FAIL):
  - `generate_reset_token()` returns a str; two calls differ; length ≥ 40.
  - `hash_reset_token("abc")` is a 64-char hex str, deterministic for the same input, and **≠ "abc"**.
  - Monkeypatching a different `AUTH_SECRET` (reset `security._SECRET=None` first) changes the hash for
    the same input (proves it's keyed — HMAC, Decision 2).
- **T5-impl** Add to `app/api/security.py` (imports `hmac, hashlib, secrets`):
  `generate_reset_token()` → `secrets.token_urlsafe(_cfg.AUTH_RESET_TOKEN_BYTES)`;
  `hash_reset_token(raw)` → `hmac.new(load_secret().encode(), raw.encode(), hashlib.sha256).hexdigest()`.
  Make T4 green.

---

## Phase D — `PasswordResetStore` (`app/runner/password_reset_store.py`) — TDD

- **T6-test** `tests/unit/test_password_reset_store.py` (run → FAIL). Build the store on a temp DB that
  has run `upgrade_to_head` (mirror how `test_*` build UserStore). Assert:
  - `create(id, user_id, token_hash, created_at, expires_at)` then `get_by_hash(token_hash)` returns a
    `ResetTokenRow` with matching fields and `used_at is None`.
  - `get_by_hash("nope")` → None.
  - `mark_used(id, used_iso)` → `get_by_hash` now has `used_at == used_iso`.
  - `invalidate_user_tokens(user_id, used_iso)` sets `used_at` on **unused** rows for that user only,
    and does NOT touch another user's rows or already-used rows.
  - `delete_expired_or_used_for_user(user_id, now_iso)` deletes rows for that user whose `used_at IS NOT
    NULL` OR `expires_at < now_iso`, and leaves a fresh unused row and other users' rows intact.
- **T7-impl** Create `app/runner/password_reset_store.py` mirroring `UserStore` (shared `sqlite3` conn,
  `check_same_thread=False`, `threading.Lock`, `row_factory=Row`, `close()`), with the `ResetTokenRow`
  dataclass and the 5 methods (plan §3). Make T6 green.

---

## Phase E — Reset email (`app/delivery/password_reset_email.py`)

- **T8-test** `tests/unit/test_password_reset_email.py` (run → FAIL):
  - `build_reset_email("http://x/reset?token=RAW")` → `(subject, plain, html)`; `subject` non-empty;
    both `plain` and `html` contain the exact URL; `html` contains `REPORT_BRAND_NAME`.
- **T9-impl** Create `app/delivery/password_reset_email.py`:
  - `build_reset_email(reset_url)` → branded `(subject, plain, html)` reusing `REPORT_BRAND_*` constants
    (a small branded HTML shell; may share `email_html`'s shell). Plain text includes the URL + a
    "link expires in 30 minutes" line.
  - `async def send_reset_email(to, reset_url)`: `central = materialize_central_token_tempfile()`;
    build bodies; `await send_report_via_gmail(to, subject, plain, None, None,
    timeout_seconds=_cfg.MCP_DELIVERY_TIMEOUT_SECONDS, max_retries=_cfg.MCP_DELIVERY_MAX_RETRIES,
    html_body=html, token_path=central)`; in `finally`, unlink the temp ONLY when
    `central and central != _cfg.GOOGLE_OAUTH_TOKEN_PATH` (do NOT unlink the live central token file).
  Make T8 green. (Send is exercised via stub in Phase F.)

---

## Phase F — Endpoints + models + background task (`app/api/auth.py`, `app/api/main.py`) — TDD

- **T10-impl (wiring, no logic branch)** In `app/api/main.py` lifespan: after `user_store = ...`, add
  `password_reset_store = PasswordResetStore(_cfg.JOB_STORE_DB_PATH)`, set
  `application.state.password_reset_store = password_reset_store`, and `.close()` it in the `finally`.

- **T11-test** `tests/integration/test_forgot_password.py` (FastAPI `TestClient`; patch
  `app.api.auth.send_reset_email` — or the symbol the task imports — with an `AsyncMock`/recorder;
  seed a user via the signup endpoint or a direct store insert). Write ALL of the following, run → FAIL:
  - **AC-1** POST `/api/auth/forgot-password` {known email} → 200 body `{"ok":true,"message":_GENERIC_RESET_MSG}`;
    the send stub was called once. The stub records its **2nd positional arg** `reset_url` (signature is
    `send_reset_email(to, reset_url)`); assert `reset_url` starts with `FRONTEND_RESET_URL` and contains
    `?token=`. Parse `raw = reset_url.split("token=")[1]` for use by AC-4.
  - **AC-4** after the call, a `password_reset_tokens` row exists with `token_hash == hash_reset_token(raw)`
    (raw from the AC-1 `reset_url` capture), `used_at IS NULL`, `user_id ==` the seeded user; and the RAW
    token string is **not** equal to any stored `token_hash`.
  - **AC-2** unknown email → 200 same body; stub NOT called; no token row.
  - **AC-3** capture bodies for (known first request), (unknown), and (known second request **within
    cooldown**) → assert all three `response.content` are byte-identical.
  - **AC-5** two known requests with the cooldown cleared between them —
    `client.app.state.rate_limiter.reset(f"reset-email:{email}")` — so the second issuance actually runs:
    the first token row is `used_at != NULL` after the second issuance (invalidated by AC-5 logic).
  - **AC-6** exceed `AUTH_RATE_LIMIT_MAX` from one client → 429 with `Retry-After`.
  - **AC-7** two known requests within cooldown → send stub called only ONCE; both bodies == generic 200.
  - **AC-9** stub raises → endpoint still returns 200 (no 500).
  - **AC-10 / AC-10b** seed a valid token (call forgot then read raw from stub), POST
    `/api/auth/reset-password` {token, new_password="NewPassw0rd!"} → 200; the seeded user's password now
    verifies with the new value and NOT the old; password applied to the token's `user_id`.
  - **AC-11** mint a JWT for the user via `make_session(row)` and set it as the cookie on a GET
    `/api/auth/me` → 200 BEFORE reset; after a successful reset, the same cookie → 401 (epoch bumped).
  - **AC-12** reusing the same token → 400 `_GENERIC_RESET_BAD`; password unchanged.
  - **AC-13** insert a token row **directly** via the store with `token_hash = hash_reset_token(RAW)` for
    a known `RAW` and `expires_at` in the past, then POST `RAW` → the lookup succeeds but expiry triggers
    400 (this proves the *expiry* branch, not the AC-14 unknown-token branch); password unchanged; no
    epoch bump.
  - **AC-14** unknown/garbage token → 400 same message.
  - **AC-14b** token row whose `user_id` is a non-existent id → 400 (no 500).
  - **AC-15** reset with `new_password="short"` → 422; the token row is still `used_at IS NULL`
    (redeemable).
  - **AC-16** exceed per-IP limit on `/reset-password` → 429.
  - **AC-17** a successful reset response has **no** `set-cookie` header.
  - **AC-18** both endpoints succeed with no auth cookie present.

- **T12-impl** In `app/api/auth.py`:
  1. Add imports/logger per plan §6 (`asyncio`, `uuid`, `timedelta`, `BackgroundTasks`, module `logger`,
     `generate_reset_token`/`hash_reset_token` from security, `send_reset_email`, `PasswordResetStore`
     types as needed) + the two `_GENERIC_*` constants.
  2. `ForgotPasswordRequest` (email, normalize `strip().lower()`) and `ResetPasswordRequest`
     (token: str, new_password: str with `@field_validator("new_password") -> _validate_password`).
  3. `_reset_email_task(app_state, user_id, email)` — sync; order per plan §7/AC-20:
     `delete_expired_or_used_for_user` → `invalidate_user_tokens` → generate raw → `create` (hashed) →
     `asyncio.run(send_reset_email(email, f"{FRONTEND_RESET_URL}?token={raw}"))` wrapped in
     try/except-log (AC-9). Never log `raw`.
  4. `POST /api/auth/forgot-password` — `_enforce_ip_rate_limit`; `row = user_store.get_by_email(...)`
     (same single lookup either way); if `row` and
     `rate_limiter.check(f"reset-email:{row.email}", max_hits=1, window_seconds=AUTH_RESET_EMAIL_COOLDOWN_SECONDS)`
     → `background_tasks.add_task(_reset_email_task, request.app.state, row.id, row.email)`; always return
     the generic 200 (AC-2/3/10a).
  5. `POST /api/auth/reset-password` — `_enforce_ip_rate_limit`; look up
     `reset_store.get_by_hash(hash_reset_token(body.token))`; if None / `used_at` set / expired → 400
     `_GENERIC_RESET_BAD`; `user = user_store.get_by_id(token_row.user_id)`; if None → 400; else
     `update_password(user.id, hash_password(body.new_password))`, `mark_used(token_row.id, now)`,
     `bump_session_epoch(user.id)`; return `{"ok": True}` with **no** cookie (AC-17).
  Make T11 green.

---

## Phase G — Frontend (`frontend/src/`)

- **T13-test** Vitest specs: `/forgot-password` posts the email via the provider seam and renders the
  generic confirmation regardless of the response; `/reset` reads `?token=`, posts token+password, and
  on success navigates to `/login` (success flash), on 400 shows the generic error + a link to
  `/forgot-password`. Run → FAIL.
- **T14-impl** Add provider seam methods `requestPasswordReset(email)` and `resetPassword(token, newPassword)`
  to BOTH the real and mock providers; create `app/forgot-password/page.tsx` and `app/reset/page.tsx`
  (reset is a client component reading `useSearchParams().get("token")`); add a "Forgot password?" link
  on the login page. Make T13 green. Run `tsc`/lint clean.

---

## Phase H — Regression + smoke

- **T15** Full backend suite `python -X utf8 -m pytest -q` from `backend/` → all green (existing auth
  suites included, AC-19). Frontend `npm run test` + `tsc` green.
- **T16** (live smoke, if OAuth central token valid) Start backend+frontend, use `/forgot-password` with
  the owner email, confirm the reset email arrives via central Gmail with a working link, complete the
  reset, confirm old sessions are logged out and login works with the new password. If the central token
  is expired (`invalid_grant`), note it and rely on T15 + the stubbed AC-1/AC-8.

---

## AC-coverage map

| AC | Task |
|----|------|
| AC-1,4,5,20 | T11/T12 (+T6/T7 store) |
| AC-2,3,10a | T11/T12 |
| AC-6,7,16 | T11/T12 |
| AC-8,9 | T8/T9 + T11 |
| AC-10,10b,12,13,14,14b | T11/T12 |
| AC-11 | T11/T12 (make_session + require_auth) |
| AC-15 | T11/T12 (Pydantic) |
| AC-17,18 | T11/T12 |
| AC-19 | T15 |

## Files touched (must match plan §11)

Backend: `app/config.py`; `alembic/versions/0008_password_reset_tokens.py` (new);
`tests/integration/test_alembic_head.py`; `app/api/security.py`;
`app/runner/password_reset_store.py` (new); `app/delivery/password_reset_email.py` (new);
`app/api/auth.py`; `app/api/main.py`; new tests `tests/unit/test_reset_token.py`,
`tests/unit/test_password_reset_store.py`, `tests/unit/test_password_reset_email.py`,
`tests/integration/test_forgot_password.py`.
Frontend: provider seam (real + mock); `app/forgot-password/page.tsx` (new); `app/reset/page.tsx` (new);
login-page link; Vitest specs.
