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

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, field_validator

import app.config as _cfg
from app.api.security import (
    DUMMY_HASH,
    hash_password,
    make_session,
    read_session,
    verify_password,
)
from app.runner.user_store import EmailExists


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
        if len(v) < _cfg.AUTH_PASSWORD_MIN or len(v) > _cfg.AUTH_PASSWORD_MAX:
            raise ValueError(
                f"Password must be between {_cfg.AUTH_PASSWORD_MIN} and "
                f"{_cfg.AUTH_PASSWORD_MAX} characters"
            )
        return v

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        v = (v or "").strip()
        if not (1 <= len(v) <= 100):
            raise ValueError("Name must be between 1 and 100 characters")
        return v

    @field_validator("title")
    @classmethod
    def validate_title(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        v = v.strip()
        if v == "":
            return None
        if len(v) > 100:
            raise ValueError("Title must be at most 100 characters")
        return v


class LoginRequest(BaseModel):
    email: str
    password: str

    @field_validator("email")
    @classmethod
    def normalize_email(cls, v: str) -> str:
        return v.strip().lower()


class AuthUser(BaseModel):
    id: str
    email: str
    name: Optional[str] = None
    title: Optional[str] = None


class AuthResponse(BaseModel):
    user: AuthUser


# ---------------------------------------------------------------------------
# require_auth dependency
# ---------------------------------------------------------------------------


def require_auth(request: Request) -> AuthUser:
    """FastAPI dependency — verifies the session cookie, returns the AuthUser.

    Reads UserStore from request.app.state.user_store (set in lifespan).
    Raises HTTP 401 on any failure (missing / expired / tampered cookie).
    """
    token = request.cookies.get(_cfg.AUTH_COOKIE_NAME)
    if not token:
        raise HTTPException(status_code=401, detail="Authentication required")
    try:
        claims = read_session(token)
    except Exception:
        raise HTTPException(status_code=401, detail="Authentication required")

    user_store = request.app.state.user_store
    row = user_store.get_by_id(claims.get("sub", ""))
    if row is None:
        raise HTTPException(status_code=401, detail="Authentication required")
    return AuthUser(id=row.id, email=row.email, name=row.name, title=row.title)


# ---------------------------------------------------------------------------
# Cookie helper
# ---------------------------------------------------------------------------


def _set_session_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        key=_cfg.AUTH_COOKIE_NAME,
        value=token,
        httponly=True,
        samesite="lax",
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
        samesite="lax",
    )


# ---------------------------------------------------------------------------
# Auth router (unguarded — included without require_auth dependency)
# ---------------------------------------------------------------------------

auth_router = APIRouter(prefix="/api/auth")


@auth_router.post("/signup", response_model=AuthResponse)
async def signup(body: SignupRequest, request: Request, response: Response):
    user_store = request.app.state.user_store

    if not _cfg.AUTH_SIGNUP_OPEN and user_store.count() > 0:
        raise HTTPException(status_code=403, detail="Signup is closed")

    pw_hash = hash_password(body.password)
    try:
        row = user_store.create(body.email, pw_hash, body.name, body.title)
    except EmailExists:
        raise HTTPException(status_code=409, detail="Email already registered")

    user = AuthUser(id=row.id, email=row.email, name=row.name, title=row.title)
    token = make_session(user)  # JWT uses only id/email — name/title stay in the DB
    _set_session_cookie(response, token)
    return AuthResponse(user=user)


@auth_router.post("/login", response_model=AuthResponse)
async def login(body: LoginRequest, request: Request, response: Response):
    user_store = request.app.state.user_store
    row = user_store.get_by_email(body.email)

    if row is None:
        # Timing-equalize unknown-email path: still run a bcrypt verify (M2).
        verify_password(body.password, DUMMY_HASH)
        raise HTTPException(status_code=401, detail="Invalid email or password")

    if not verify_password(body.password, row.password_hash):
        raise HTTPException(status_code=401, detail="Invalid email or password")

    user = AuthUser(id=row.id, email=row.email, name=row.name, title=row.title)
    token = make_session(user)
    _set_session_cookie(response, token)
    return AuthResponse(user=user)


@auth_router.post("/logout")
async def logout(response: Response):
    _clear_session_cookie(response)
    return {"ok": True}


@auth_router.get("/me", response_model=AuthResponse)
async def me(current_user: AuthUser = Depends(require_auth)):
    return AuthResponse(user=current_user)
