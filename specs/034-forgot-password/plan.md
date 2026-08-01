# Feature 034 — Forgot-Password — Technical Plan

**Branch:** `feature/034-forgot-password` — git workflow per constitution §11 (this line is the only
workflow statement here; the rules live in §11, not restated).

Implements the spec-reviewer-APPROVED `specs/034-forgot-password/spec.md`. **Auth-surface only: no
LangGraph node/edge change, no `ContractState` field.** Authorized under the 014 + 031 amendments per
the 032 no-amendment precedent. All new tunables are named `app/config.py` constants (§3); all HTTP
bodies are Pydantic (§4). Decisions 1–7 are resolved in the spec and are not re-opened here.

TDD per constitution §7: for each work-stream the tests below are written and confirmed **failing**
first, then the implementation makes them pass; tests are never weakened. Run backend tests with
`python -X utf8 -m pytest` from `backend/`.

---

## 0. Grounding (verified against current code)

- **Unguarded auth router** `auth_router = APIRouter(prefix="/api/auth")` (`app/api/auth.py:253`); new
  endpoints attach here (no `require_auth`, AC-18). `_enforce_ip_rate_limit(request)` (`auth.py:156`)
  reads `request.app.state.rate_limiter` and raises `429 + Retry-After` — reuse verbatim (AC-6/AC-16).
- **Session invalidation** `UserStore.bump_session_epoch(user_id)` (`user_store.py:236`) increments
  `session_epoch`; `require_auth` (`auth.py:210`) 401s on epoch mismatch → AC-11 is a direct consequence.
- **Password write** `UserStore.update_password(user_id, new_hash)` (`user_store.py:162`) +
  `hash_password` (`security.py:35`) — reset reuses both.
- **User lookup** `get_by_email` (normalizes nothing — caller lowercases; `user_store.py:125`) and
  `get_by_id` → `Optional[UserRow]` (None for a deleted user → AC-14b).
- **App secret** `security.load_secret()` (`security.py:61`) → the HMAC key for token hashing
  (Decision 2). `AUTH_SECRET` is process-cached.
- **Central Gmail send** `send_report_via_gmail(to, subject, body, attachment_path, attachment_name, *,
  timeout_seconds, max_retries, html_body=None, token_path=None)` (`gmail_client.py:15`) is generic
  enough for a no-attachment email. Central token via
  `materialize_central_token_tempfile()` → 0600 temp path, cleaned with `os.unlink`
  (pattern in `delivery_step.py:221-290`) — the reset send mirrors this (AC-8).
- **Rate limiter** `RateLimiter.check(key, *, max_hits=None, window_seconds=None)`
  (`rate_limit.py`) — reused for BOTH the per-IP limit (default thresholds) AND the per-email
  cooldown (`max_hits=1, window_seconds=AUTH_RESET_EMAIL_COOLDOWN_SECONDS`, AC-7).
- **Lifespan wiring** (`app/api/main.py:57-90`): `upgrade_to_head(JOB_STORE_DB_PATH)` runs migrations;
  `UserStore(JOB_STORE_DB_PATH)` + `RateLimiter()` are put on `application.state`. Add the new
  `PasswordResetStore(JOB_STORE_DB_PATH)` here and `.close()` it in the `finally`.
- **Migration head** is `alembic/versions/0007_security_tier1.py`, `revision = "0007"`. So the new
  migration is `0008`, `down_revision = "0007"` (literal strings).
- **Config** has `_env_int`/`_env_bool` helpers and `FRONTEND_INTEGRATIONS_URL` (`config.py:450`) as the
  precedent for a frontend URL constant. `AUTH_RATE_LIMIT_MAX/_WINDOW`, `AUTH_PASSWORD_MIN/MAX` exist.
- **Frontend** provider seam: `frontend/src/lib/api/` with a `real` provider proxying to `:8000`;
  auth pages under `frontend/src/app/` (login exists). New pages mirror those patterns.

---

## 1. Config (constitution §3 — named constants in `app/config.py`, near the AUTH block ~L534-577)

```python
AUTH_RESET_TOKEN_TTL_SECONDS: int = _env_int("AUTH_RESET_TOKEN_TTL_SECONDS", 30 * 60)   # 30 min (Decision 3)
AUTH_RESET_TOKEN_BYTES: int = 32                                                          # secrets.token_urlsafe(32)
AUTH_RESET_EMAIL_COOLDOWN_SECONDS: int = _env_int("AUTH_RESET_EMAIL_COOLDOWN_SECONDS", 60)
FRONTEND_RESET_URL: str = "http://localhost:3000/reset"   # mirrors FRONTEND_INTEGRATIONS_URL
```

## 2. Migration 0008 — `alembic/versions/0008_password_reset_tokens.py`

`revision = "0008"`, `down_revision = "0007"`. `upgrade`: `op.create_table("password_reset_tokens", …)`
with columns `id TEXT PK, user_id TEXT NOT NULL, token_hash TEXT NOT NULL, created_at TEXT NOT NULL,
expires_at TEXT NOT NULL, used_at TEXT NULL` + `op.create_index` on `token_hash` and on `user_id`.
`downgrade`: drop indexes + `op.drop_table`. Purely additive; in
`tests/integration/test_alembic_head.py` update **both** the head assertion (`== "0007"` → `"0008"`,
~L78) **and** the test function name + docstring (`test_current_head_is_0007` → `_0008`, L69-70) so the
suite stays self-consistent.

## 3. `PasswordResetStore` — `app/runner/password_reset_store.py`

Mirrors `UserStore`'s lock/connection pattern (one shared `sqlite3` connection, `check_same_thread=False`,
`threading.Lock`, `row_factory=Row`). Pure SQL; no HTTP/crypto here (hashing is done by the caller).

```python
@dataclass
class ResetTokenRow: id: str; user_id: str; token_hash: str; created_at: str; expires_at: str; used_at: Optional[str]

class PasswordResetStore:
    def create(self, user_id, token_hash, created_at, expires_at) -> str            # returns new id
    def get_by_hash(self, token_hash) -> Optional[ResetTokenRow]
    def mark_used(self, token_id, used_at) -> None                                   # single-use (AC-12)
    def invalidate_user_tokens(self, user_id, used_at) -> None                       # set used_at on all UNUSED rows (AC-5)
    def delete_expired_or_used_for_user(self, user_id, now_iso) -> None              # scoped cleanup (AC-20)
```

## 4. Token helpers — add to `app/api/security.py`

```python
import hmac, hashlib, secrets
def generate_reset_token() -> str:
    return secrets.token_urlsafe(_cfg.AUTH_RESET_TOKEN_BYTES)          # ~43 chars, ~256-bit (Decision 1)
def hash_reset_token(raw: str) -> str:
    return hmac.new(load_secret().encode(), raw.encode(), hashlib.sha256).hexdigest()   # Decision 2
```
`load_secret()` never logs; the raw token is never logged (S3 discipline).

## 5. Reset email — `app/delivery/password_reset_email.py`

- `build_reset_email(reset_url: str) -> tuple[str, str, str]` — returns `(subject, plain, html)`. Reuses
  the brand constants (`REPORT_BRAND_NAME/_ACCENT_HEX/_FOOTER`, `config.py:396`) and the HTML shell style
  from `email_html._build_html` (extract/share a minimal shell, or inline a small branded template).
  Both bodies contain `reset_url`; plaintext is the fallback (AC-8).
- `send_reset_email(to: str, reset_url: str) -> None` (async) — materializes the central token
  (`materialize_central_token_tempfile`), calls `send_report_via_gmail(to, subject, plain, None, None,
  timeout_seconds=MCP_DELIVERY_TIMEOUT_SECONDS, max_retries=MCP_DELIVERY_MAX_RETRIES, html_body=html,
  token_path=central)`, and cleans up the temp token in a `finally`. **Cleanup guard (do NOT unlink the
  live central token file):** only `os.unlink` when the returned path is a real temp file, i.e.
  `_central_is_temp = bool(central) and central != _config.GOOGLE_OAUTH_TOKEN_PATH` — copy the exact
  guard from `delivery_step.py:222/286`, because `materialize_central_token_tempfile()` returns the
  ORIGINAL `GOOGLE_OAUTH_TOKEN_PATH` in the legacy-plaintext case. Never raises out (AC-9): callers wrap
  in try/except and log.

## 6. Endpoints + models — `app/api/auth.py`

New imports/module state this feature adds to `auth.py` (currently only `time`, `datetime`, `timezone`
are imported): `import asyncio`, `import uuid`, `from datetime import timedelta`, `from fastapi import
BackgroundTasks`, a module `logger = logging.getLogger("contractsentinel.auth")`, and the new
helpers/store types. (Call this out so a missing-import error in the TDD red phase is not mistaken for a
logic failure.)

Pydantic bodies (mirror `LoginRequest`):
```python
class ForgotPasswordRequest(BaseModel):
    email: str
    @field_validator("email") ... normalize strip().lower()
class ResetPasswordRequest(BaseModel):
    token: str
    new_password: str
    @field_validator("new_password") -> _validate_password       # 422 on policy fail (AC-15)
```

`POST /api/auth/forgot-password` (background-task, constant-work sync path — Decision 4):
```python
@auth_router.post("/forgot-password")
async def forgot_password(body, request, background_tasks: BackgroundTasks):
    _enforce_ip_rate_limit(request)                              # AC-6
    user_store = request.app.state.user_store
    row = user_store.get_by_email(body.email)                    # SAME single lookup for known/unknown (AC-10a)
    if row is not None:
        limiter = request.app.state.rate_limiter
        if limiter.check(f"reset-email:{body.email}", max_hits=1,
                         window_seconds=_cfg.AUTH_RESET_EMAIL_COOLDOWN_SECONDS):   # cooldown, known-only (AC-7)
            background_tasks.add_task(_reset_email_task, request.app.state, row.id, row.email)
    return {"ok": True, "message": _GENERIC_RESET_MSG}           # byte-identical always (AC-2/AC-3)
```

`POST /api/auth/reset-password`:
```python
@auth_router.post("/reset-password")
async def reset_password(body, request):
    _enforce_ip_rate_limit(request)                              # AC-16
    reset_store = request.app.state.password_reset_store
    user_store  = request.app.state.user_store
    token_row = reset_store.get_by_hash(hash_reset_token(body.token))
    now = datetime.now(timezone.utc)
    if (token_row is None or token_row.used_at is not None
            or _expired(token_row.expires_at, now)):
        raise HTTPException(400, detail=_GENERIC_RESET_BAD)      # AC-12/13/14 one message
    user = user_store.get_by_id(token_row.user_id)               # bind to token's own user_id (AC-10b)
    if user is None:
        raise HTTPException(400, detail=_GENERIC_RESET_BAD)      # deleted user (AC-14b)
    user_store.update_password(user.id, hash_password(body.new_password))
    reset_store.mark_used(token_row.id, now.isoformat())         # single-use (AC-12)
    user_store.bump_session_epoch(user.id)                       # log out all sessions (AC-11)
    return {"ok": True}                                          # NO cookie set (AC-17)
```
`_GENERIC_RESET_MSG` / `_GENERIC_RESET_BAD` are module constants so the body is provably identical.

## 7. Background task — `_reset_email_task(app_state, user_id, email)` in `app/api/auth.py`

Sync function (FastAPI runs sync BackgroundTasks in a threadpool → no running loop; `asyncio.run` is
safe there). Order per AC-20:
```python
def _reset_email_task(app_state, user_id, email):
    reset_store = app_state.password_reset_store
    now = datetime.now(timezone.utc)
    reset_store.delete_expired_or_used_for_user(user_id, now.isoformat())   # cleanup (AC-20)
    reset_store.invalidate_user_tokens(user_id, now.isoformat())            # AC-5
    raw = generate_reset_token()
    expires = (now + timedelta(seconds=_cfg.AUTH_RESET_TOKEN_TTL_SECONDS)).isoformat()
    reset_store.create(str(uuid.uuid4()), user_id, hash_reset_token(raw), now.isoformat(), expires)  # AC-4
    url = f"{_cfg.FRONTEND_RESET_URL}?token={raw}"
    try:
        asyncio.run(send_reset_email(email, url))                           # AC-1
    except Exception:                                                       # AC-9
        logger.warning("reset email send failed", exc_info=True)
```
The raw token exists only in `url`/the email; the DB holds only the HMAC.

## 8. Frontend (`frontend/src/`)

- Seam methods on the provider (real + mock): `requestPasswordReset(email)` → POST `/api/auth/forgot-password`;
  `resetPassword(token, newPassword)` → POST `/api/auth/reset-password`.
- **`/forgot-password`** page: email field → calls `requestPasswordReset` → always renders the generic
  confirmation (no existence signal). Linked from `/login` ("Forgot password?").
- **`/reset`** page: reads `?token=` (client component), new-password + confirm fields → `resetPassword`
  → success: redirect to `/login` with a success flash; 400: generic "invalid or expired" + link back to
  `/forgot-password`. Password field validated client-side to `AUTH_PASSWORD_MIN` for UX (server is
  authoritative).

## 9. Test plan (TDD — write failing first)

Store unit tests (`tests/unit/test_password_reset_store.py`): create/get_by_hash round-trip; mark_used;
invalidate_user_tokens sets used_at on unused only; delete_expired_or_used_for_user scoped to user_id.

Security unit tests (`tests/unit/test_reset_token.py`): `generate_reset_token` length/uniqueness;
`hash_reset_token` deterministic + differs from raw + changes with AUTH_SECRET.

Endpoint tests (`tests/integration/test_forgot_password.py`, FastAPI `TestClient`, Gmail send stubbed):
- AC-1 known email → 200 + email stub called once with URL containing the token; AC-4 row has HMAC (raw
  absent), expiry, used_at NULL, correct user_id.
- AC-2 unknown → 200 same body, stub NOT called, no row.
- AC-3 assert known/unknown/cooldown bodies byte-identical — the cooldown case must be a **second
  request for a KNOWN email within the window** (so it actually exercises the suppression branch), not
  two unknown-email calls.
- AC-5 second request marks prior token used; AC-20 cleanup order (expired/used purged).
- AC-6 per-IP 429; AC-7 cooldown → no second email, same body.
- AC-9 send raises in stub → still 200.
- AC-10 valid token+password → 200, new pw verifies/old fails; AC-10b applies to token's user_id.
- AC-11 pre-reset JWT → 401 after reset (mint via make_session, assert require_auth path).
- AC-12 reuse → 400; AC-13 expired (insert past expiry) → 400; AC-14 unknown token → 400; AC-14b deleted
  user → 400.
- AC-15 weak password → 422 AND token still unused (redeemable).
- AC-16 reset per-IP 429; AC-17 no Set-Cookie on reset response; AC-18 both endpoints work with no auth.
- AC-19 existing auth tests stay green.

Frontend tests (Vitest): forgot-password page posts + shows generic message; reset page reads token,
posts, redirects on success / shows generic error on 400.

## 10. AC-coverage map

| AC | Where | Test |
|----|-------|------|
| AC-1,4,5,20 | §6 handler + §7 task + §3 store | test_forgot_password / test_password_reset_store |
| AC-2,3,10a | §6 sync path + constants | test_forgot_password |
| AC-6,7,16 | `_enforce_ip_rate_limit` + cooldown | test_forgot_password |
| AC-8,9 | §5 email | test_forgot_password (stub) |
| AC-10,10b,12,13,14,14b | §6 reset handler | test_forgot_password |
| AC-11 | `bump_session_epoch` + require_auth | test_forgot_password |
| AC-15 | Pydantic `_validate_password` | test_forgot_password |
| AC-17,18 | no cookie / no require_auth | test_forgot_password |
| AC-19 | unchanged auth paths | existing suites |

## 11. Files touched

Backend: `app/config.py`; `alembic/versions/0008_password_reset_tokens.py` (new);
`app/runner/password_reset_store.py` (new); `app/api/security.py` (2 helpers);
`app/delivery/password_reset_email.py` (new); `app/api/auth.py` (2 models, 2 endpoints, 1 task);
`app/api/main.py` (register/close PasswordResetStore); `tests/integration/test_alembic_head.py` (head→0008);
new tests: `tests/unit/test_password_reset_store.py`, `tests/unit/test_reset_token.py`,
`tests/integration/test_forgot_password.py`.
Frontend: provider seam methods (real + mock); `app/forgot-password/page.tsx` (new);
`app/reset/page.tsx` (new); a "Forgot password?" link on the login page; Vitest specs.
**No graph/, no ContractState, exactly one migration (0008).**

## 12. Rollback

No feature flag (a recovery flow is either present or not), but the surface is additive and isolated:
the two new endpoints + table + frontend pages can be reverted without touching any existing auth path
(login/signup/logout/me/password all unchanged). Dropping migration 0008 removes the table.
