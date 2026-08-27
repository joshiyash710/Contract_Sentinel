"""
Auth endpoints, models, and require_auth dependency for feature 014.

Endpoints (all under /api/auth — unguarded):
  POST /api/auth/signup
  POST /api/auth/login
  POST /api/auth/logout
  GET  /api/auth/me

require_auth: FastAPI dependency applied router-level to the existing gated router.
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, Response
from pydantic import BaseModel, field_validator

import app.config as _cfg
from app.api.security import (
    DUMMY_HASH,
    generate_reset_token,
    hash_password,
    hash_reset_token,
    make_session,
    read_session,
    verify_password,
)
from app.delivery.password_reset_email import send_reset_email
from app.runner.user_store import EmailExists

logger = logging.getLogger("contractsentinel.auth")

# Fixed generic response strings — module constants so byte-equality (034 AC-3) is provable and the
# reset-error message is a single value regardless of the failure cause (AC-12/13/14, no oracle).
_GENERIC_RESET_MSG = "If an account exists for that email, a reset link has been sent."
_GENERIC_RESET_BAD = "Invalid or expired reset link."


# ---------------------------------------------------------------------------
# Shared field validators (reused by signup + feature-023 profile/password edits)
# ---------------------------------------------------------------------------


def _validate_password(v: str) -> str:
    if len(v) < _cfg.AUTH_PASSWORD_MIN or len(v) > _cfg.AUTH_PASSWORD_MAX:
        raise ValueError(
            f"Password must be between {_cfg.AUTH_PASSWORD_MIN} and "
            f"{_cfg.AUTH_PASSWORD_MAX} characters"
        )
    return v


def _validate_name(v: str) -> str:
    v = (v or "").strip()
    if not (1 <= len(v) <= 100):
        raise ValueError("Name must be between 1 and 100 characters")
    return v


def _validate_title(v: Optional[str]) -> Optional[str]:
    if v is None:
        return None
    v = v.strip()
    if v == "":
        return None
    if len(v) > 100:
        raise ValueError("Title must be at most 100 characters")
    return v


# ---------------------------------------------------------------------------
# Pydantic boundary models (spec §2.1 / AC-19)
# ---------------------------------------------------------------------------


class SignupRequest(BaseModel):
    email: str
    password: str
    name: str
    title: Optional[str] = None

    @field_validator("email")
    @classmethod
    def normalize_email(cls, v: str) -> str:
        return v.strip().lower()

    @field_validator("password")
    @classmethod
    def validate_password(cls, v: str) -> str:
        return _validate_password(v)

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        return _validate_name(v)

    @field_validator("title")
    @classmethod
    def validate_title(cls, v: Optional[str]) -> Optional[str]:
        return _validate_title(v)


class UpdateProfileRequest(BaseModel):
    """Feature 023 — PATCH /api/auth/me body."""

    name: str
    title: Optional[str] = None

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        return _validate_name(v)

    @field_validator("title")
    @classmethod
    def validate_title(cls, v: Optional[str]) -> Optional[str]:
        return _validate_title(v)


class ChangePasswordRequest(BaseModel):
    """Feature 023 — POST /api/auth/me/password body."""

    current_password: str
    new_password: str

    @field_validator("new_password")
    @classmethod
    def validate_new_password(cls, v: str) -> str:
        return _validate_password(v)


class LoginRequest(BaseModel):
    email: str
    password: str

    @field_validator("email")
    @classmethod
    def normalize_email(cls, v: str) -> str:
        return v.strip().lower()


class ForgotPasswordRequest(BaseModel):
    """Feature 034 — POST /api/auth/forgot-password body."""

    email: str

    @field_validator("email")
    @classmethod
    def normalize_email(cls, v: str) -> str:
        return v.strip().lower()


class ResetPasswordRequest(BaseModel):
    """Feature 034 — POST /api/auth/reset-password body."""

    token: str
    new_password: str

    @field_validator("new_password")
    @classmethod
    def validate_new_password(cls, v: str) -> str:
        return _validate_password(v)  # 422 on policy violation (AC-15) before the handler runs


class AuthUser(BaseModel):
    id: str
    email: str
    name: Optional[str] = None
    title: Optional[str] = None


class AuthResponse(BaseModel):
    user: AuthUser


# ---------------------------------------------------------------------------
# Rate-limiting helpers (feature 032, W3)
# ---------------------------------------------------------------------------


def _client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def _enforce_ip_rate_limit(request: Request) -> None:
    """Per-IP sliding-window limit on auth-sensitive endpoints → 429 + Retry-After (AC-15/AC-20)."""
    limiter = getattr(request.app.state, "rate_limiter", None)
    if limiter is not None and not limiter.check(_client_ip(request)):
        raise HTTPException(
            status_code=429,
            detail="Too many attempts. Please try again later.",
            headers={"Retry-After": str(_cfg.AUTH_RATE_LIMIT_WINDOW_SECONDS)},
        )


# ---------------------------------------------------------------------------
# require_auth dependency
# ---------------------------------------------------------------------------


def require_auth(request: Request, response: Response) -> AuthUser:
    """FastAPI dependency — verifies the session cookie, returns the AuthUser.

    Reads UserStore from request.app.state.user_store (set in lifespan).
    Raises HTTP 401 on any failure (missing / expired / tampered cookie).

    Feature 032 (W2) adds, on top of the base signature check:
      - absolute lifetime cap (`aexp`) enforcement (AC-8);
      - server-side invalidation via `epoch` vs the user's stored session_epoch (AC-10/11/12);
      - forced re-login of pre-032 tokens that carry no `aexp`/`epoch` (Q2/EC-6);
      - a SLIDING re-issue of the cookie on each valid request, refreshing the idle window while
        preserving the fixed absolute cap (AC-9). Note: routes that return their OWN Response object
        (e.g. redirects/streams) won't carry the re-issued cookie — acceptable, the next plain request
        refreshes it.
    """
    token = request.cookies.get(_cfg.AUTH_COOKIE_NAME)
    if not token:
        raise HTTPException(status_code=401, detail="Authentication required")
    try:
        claims = read_session(token)  # raises on tampered / idle-expired `exp`
    except Exception:
        raise HTTPException(status_code=401, detail="Authentication required")

    # Pre-032 tokens have no aexp/epoch → force a one-time re-login (Q2/EC-6).
    aexp = claims.get("aexp")
    epoch = claims.get("epoch")
    if aexp is None or epoch is None:
        raise HTTPException(status_code=401, detail="Authentication required")

    # Absolute lifetime cap, skew-tolerant (AC-8 / EC-5).
    if time.time() > aexp + _cfg.AUTH_CLOCK_SKEW_SECONDS:
        raise HTTPException(status_code=401, detail="Authentication required")

    user_store = request.app.state.user_store
    row = user_store.get_by_id(claims.get("sub", ""))
    if row is None:
        raise HTTPException(status_code=401, detail="Authentication required")
    # Server-side invalidation: any bump of session_epoch kills older tokens (AC-10/11/12).
    if getattr(row, "session_epoch", 0) != epoch:
        raise HTTPException(status_code=401, detail="Authentication required")

    # Sliding re-issue — refresh the idle window, keep the fixed absolute cap.
    aexp_dt = datetime.fromtimestamp(aexp, tz=timezone.utc)
    if datetime.now(timezone.utc) < aexp_dt:
        _set_session_cookie(response, make_session(row, absolute_exp=aexp_dt))

    return AuthUser(id=row.id, email=row.email, name=row.name, title=row.title)


# ---------------------------------------------------------------------------
# Cookie helper
# ---------------------------------------------------------------------------


def _set_session_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        key=_cfg.AUTH_COOKIE_NAME,
        value=token,
        httponly=True,
        samesite=_cfg.AUTH_COOKIE_SAMESITE,  # 048: "none" for cross-site deploy; default "lax"
        secure=_cfg.AUTH_COOKIE_SECURE,
        max_age=_cfg.AUTH_SESSION_TTL_SECONDS,
        path="/",
        # No domain attribute — binds to request host; works same-origin through
        # the Next dev proxy (spec D1 / review N1).
    )


def _clear_session_cookie(response: Response) -> None:
    response.delete_cookie(
        key=_cfg.AUTH_COOKIE_NAME,
        path="/",
        httponly=True,
        samesite=_cfg.AUTH_COOKIE_SAMESITE,  # 048: match the set-cookie policy
        secure=_cfg.AUTH_COOKIE_SECURE,  # 048: a Secure cookie can only be cleared by a Secure delete
    )


# ---------------------------------------------------------------------------
# Auth router (unguarded — included without require_auth dependency)
# ---------------------------------------------------------------------------

auth_router = APIRouter(prefix="/api/auth")


@auth_router.post("/signup", response_model=AuthResponse)
async def signup(body: SignupRequest, request: Request, response: Response):
    _enforce_ip_rate_limit(request)  # W3: cap signup abuse per IP
    user_store = request.app.state.user_store

    if not _cfg.AUTH_SIGNUP_OPEN and user_store.count() > 0:
        raise HTTPException(status_code=403, detail="Signup is closed")

    pw_hash = hash_password(body.password)
    try:
        row = user_store.create(body.email, pw_hash, body.name, body.title)
    except EmailExists:
        raise HTTPException(status_code=409, detail="Email already registered")

    user = AuthUser(id=row.id, email=row.email, name=row.name, title=row.title)
    # feature 032: pass the UserRow so the JWT carries the user's session_epoch (AuthUser has none).
    token = make_session(row)
    _set_session_cookie(response, token)
    return AuthResponse(user=user)


@auth_router.post("/login", response_model=AuthResponse)
async def login(body: LoginRequest, request: Request, response: Response):
    _enforce_ip_rate_limit(request)  # W3: per-IP cap first
    user_store = request.app.state.user_store

    # W3: per-account lockout — a locked account is rejected with 429 even with the correct
    # password (AC-13). is_locked is False for unknown emails, so this never discloses existence.
    if user_store.is_locked(body.email):
        raise HTTPException(
            status_code=429,
            detail="Too many failed attempts. Please try again later.",
            headers={"Retry-After": str(_cfg.AUTH_LOCKOUT_DURATION_SECONDS)},
        )

    row = user_store.get_by_email(body.email)

    if row is None:
        # Timing-equalize unknown-email path: still run a bcrypt verify (M2).
        verify_password(body.password, DUMMY_HASH)
        raise HTTPException(status_code=401, detail="Invalid email or password")

    if not verify_password(body.password, row.password_hash):
        user_store.record_login_failure(body.email)  # W3: count consecutive failures
        raise HTTPException(status_code=401, detail="Invalid email or password")

    user_store.reset_login_failures(body.email)  # W3: success clears the counter (AC-14)
    user = AuthUser(id=row.id, email=row.email, name=row.name, title=row.title)
    token = make_session(row)  # feature 032: carry session_epoch from the DB row
    _set_session_cookie(response, token)
    return AuthResponse(user=user)


@auth_router.post("/logout")
async def logout(response: Response):
    _clear_session_cookie(response)
    return {"ok": True}


@auth_router.post("/logout-all")
async def logout_all(request: Request, current_user: AuthUser = Depends(require_auth)):
    """Feature 032 (W2) — 'sign out of all devices'. Bumps the user's session_epoch so EVERY
    outstanding token for this account (including this browser's) is invalidated (AC-12)."""
    request.app.state.user_store.bump_session_epoch(current_user.id)
    return {"ok": True}


# ---------------------------------------------------------------------------
# Forgot-password (feature 034) — unauthenticated
# ---------------------------------------------------------------------------


def _reset_email_task(app_state, user_id: str, email: str) -> None:
    """Background side effects for a known-email reset request (034 §7 / AC-20 ordering):
    cleanup → invalidate prior → issue new (hashed) → send email. Runs in a threadpool worker
    (sync BackgroundTask → no running loop, so asyncio.run is safe). Never lets an exception escape
    (AC-9). The raw token is never logged (S3)."""
    reset_store = app_state.password_reset_store
    now = datetime.now(timezone.utc)
    now_iso = now.isoformat()
    try:
        reset_store.delete_expired_or_used_for_user(user_id, now_iso)  # AC-20 cleanup (scoped)
        reset_store.invalidate_user_tokens(user_id, now_iso)          # AC-5
        raw = generate_reset_token()
        expires = (now + timedelta(seconds=_cfg.AUTH_RESET_TOKEN_TTL_SECONDS)).isoformat()
        reset_store.create(str(uuid.uuid4()), user_id, hash_reset_token(raw), now_iso, expires)  # AC-4
        url = f"{_cfg.FRONTEND_RESET_URL}?token={raw}"
        asyncio.run(send_reset_email(email, url))                     # AC-1
    except Exception:  # noqa: BLE001 — a send/DB failure must never surface to the caller (AC-9)
        logger.warning("password-reset email task failed", exc_info=True)


@auth_router.post("/forgot-password")
async def forgot_password(
    body: ForgotPasswordRequest, request: Request, background_tasks: BackgroundTasks
):
    """Request a reset link. Always returns the same generic 200 (no email-existence disclosure).

    The synchronous path does identical work for known/unknown emails (normalize + one get_by_email);
    only a known, not-cooled email schedules the background task that issues the token and sends the
    email (Decision 4 / AC-10a). Per-IP rate-limited (AC-6)."""
    _enforce_ip_rate_limit(request)
    user_store = request.app.state.user_store
    row = user_store.get_by_email(body.email)
    if row is not None:
        limiter = request.app.state.rate_limiter
        # Per-email cooldown (AC-7): one email per window. Keyed distinctly from the per-IP limit,
        # and only touched for KNOWN emails, so it is not a probeable existence oracle.
        if limiter.check(
            f"reset-email:{row.email}",
            max_hits=1,
            window_seconds=_cfg.AUTH_RESET_EMAIL_COOLDOWN_SECONDS,
        ):
            background_tasks.add_task(_reset_email_task, request.app.state, row.id, row.email)
    return {"ok": True, "message": _GENERIC_RESET_MSG}


def _reset_token_expired(expires_at: str, now: datetime) -> bool:
    try:
        return now >= datetime.fromisoformat(expires_at)
    except ValueError:
        return True  # unparseable expiry → treat as expired/invalid


@auth_router.post("/reset-password")
async def reset_password(body: ResetPasswordRequest, request: Request):
    """Consume a reset token and set a new password. Bumps session_epoch (logs out all sessions,
    AC-11) and sets NO cookie (no auto-login, AC-17). Unknown/expired/used tokens → one generic 400
    (AC-12/13/14). Per-IP rate-limited (AC-16)."""
    _enforce_ip_rate_limit(request)
    reset_store = request.app.state.password_reset_store
    user_store = request.app.state.user_store

    token_row = reset_store.get_by_hash(hash_reset_token(body.token))
    now = datetime.now(timezone.utc)
    if (
        token_row is None
        or token_row.used_at is not None
        or _reset_token_expired(token_row.expires_at, now)
    ):
        raise HTTPException(status_code=400, detail=_GENERIC_RESET_BAD)

    user = user_store.get_by_id(token_row.user_id)  # bind to the token's own user (AC-10b/14b)
    if user is None:
        raise HTTPException(status_code=400, detail=_GENERIC_RESET_BAD)

    # Consume the token FIRST, atomically (used_at IS NULL guard) — this both closes the read-then-write
    # TOCTOU (concurrent same-token redemptions) and fails closed: if a later write errored, the token is
    # already spent rather than the password being changed by a still-redeemable link.
    if not reset_store.mark_used(token_row.id, now.isoformat()):
        raise HTTPException(status_code=400, detail=_GENERIC_RESET_BAD)  # lost the race / already used

    user_store.update_password(user.id, hash_password(body.new_password))
    user_store.bump_session_epoch(user.id)  # invalidate all sessions (AC-11)
    return {"ok": True}


@auth_router.get("/me", response_model=AuthResponse)
async def me(current_user: AuthUser = Depends(require_auth)):
    return AuthResponse(user=current_user)


@auth_router.patch("/me", response_model=AuthResponse)
async def update_me(
    body: UpdateProfileRequest,
    request: Request,
    current_user: AuthUser = Depends(require_auth),
):
    """Feature 023 — edit the caller's own profile (name/title). Scoped to current_user (019)."""
    user_store = request.app.state.user_store
    row = user_store.update_profile(current_user.id, body.name, body.title)
    return AuthResponse(
        user=AuthUser(id=row.id, email=row.email, name=row.name, title=row.title)
    )


@auth_router.post("/me/password")
async def change_password(
    body: ChangePasswordRequest,
    request: Request,
    response: Response,
    current_user: AuthUser = Depends(require_auth),
):
    """Change the caller's own password after verifying the current one.

    Wrong current password → 400 with no write. Feature 032 (W2, AC-11): a successful change bumps
    session_epoch so all OTHER sessions for this account are logged out, then re-issues THIS browser's
    cookie (carrying the new epoch) so the changer stays logged in — superseding 023 D3.

    Feature 032 (W3, AC-20): per-IP rate-limited (blunts online current-password guessing); NOT subject
    to the per-account lockout (a session-holder locking their own account is pointless).
    """
    _enforce_ip_rate_limit(request)
    user_store = request.app.state.user_store
    row = user_store.get_by_id(current_user.id)
    if row is None or not verify_password(body.current_password, row.password_hash):
        raise HTTPException(status_code=400, detail="Current password is incorrect")
    user_store.update_password(current_user.id, hash_password(body.new_password))
    user_store.bump_session_epoch(current_user.id)
    # Re-issue this browser's cookie with the new epoch (last Set-Cookie wins over the sliding one
    # require_auth set with the pre-bump epoch), so the caller is not logged out by their own change.
    fresh = user_store.get_by_id(current_user.id)
    _set_session_cookie(response, make_session(fresh))
    return {"ok": True}
