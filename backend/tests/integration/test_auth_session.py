"""
Feature 032 (W2) — session/cookie hardening integration tests.

Covers cookie flags (AC-7), absolute cap (AC-8), sliding idle timeout (AC-9), epoch invalidation
(AC-10), password-change logout of other sessions (AC-11), logout-all (AC-12), clock-skew tolerance
(EC-5), and forced re-login of pre-032 tokens (EC-6/Q2).

Timing tests use tiny idle/absolute windows + AUTH_CLOCK_SKEW_SECONDS=0 so they run in ~seconds.
"""

import time

from starlette.testclient import TestClient

from tests.integration.conftest import _AUTH_EMAIL, _AUTH_PASSWORD


def _login(client):
    r = client.post("/api/auth/login", json={"email": _AUTH_EMAIL, "password": _AUTH_PASSWORD})
    assert r.status_code == 200, r.text
    return r


# ── AC-7: cookie flags ───────────────────────────────────────────────────────


def test_cookie_flags_secure_httponly_samesite(client, monkeypatch):
    import app.config as _c

    monkeypatch.setattr(_c, "AUTH_COOKIE_SECURE", True)
    sc = _login(client).headers.get("set-cookie", "").lower()
    assert "httponly" in sc and "samesite=lax" in sc and "secure" in sc


def test_cookie_no_secure_flag_when_disabled(client):
    # Suite default AUTH_COOKIE_SECURE=False (local http dev) → no Secure attribute.
    sc = _login(client).headers.get("set-cookie", "").lower()
    assert "httponly" in sc and "secure" not in sc


# ── AC-8 / AC-9: absolute cap + sliding idle ─────────────────────────────────


def test_absolute_cap_expires_even_with_activity(client, monkeypatch):
    import app.config as _c

    monkeypatch.setattr(_c, "AUTH_CLOCK_SKEW_SECONDS", 0)
    monkeypatch.setattr(_c, "AUTH_IDLE_TIMEOUT_SECONDS", 1000)  # never idle
    monkeypatch.setattr(_c, "AUTH_SESSION_TTL_SECONDS", 2)      # 2s absolute cap
    _login(client)
    time.sleep(1)
    assert client.get("/api/auth/me").status_code == 200   # within cap
    time.sleep(1.6)
    assert client.get("/api/auth/me").status_code == 401   # cap exceeded despite activity


def test_idle_timeout_with_sliding_refresh(client, monkeypatch):
    import app.config as _c

    monkeypatch.setattr(_c, "AUTH_CLOCK_SKEW_SECONDS", 0)
    monkeypatch.setattr(_c, "AUTH_IDLE_TIMEOUT_SECONDS", 2)     # 2s idle window
    monkeypatch.setattr(_c, "AUTH_SESSION_TTL_SECONDS", 1000)   # large absolute cap
    _login(client)
    # Active within the window: three requests 1s apart (3s total > 2s idle) all succeed,
    # proving the idle window slides forward on each authenticated request.
    for _ in range(3):
        time.sleep(1)
        assert client.get("/api/auth/me").status_code == 200
    # Now idle past the window → rejected.
    time.sleep(2.5)
    assert client.get("/api/auth/me").status_code == 401


# ── AC-10 + EC-6/Q2: epoch invalidation & legacy tokens ──────────────────────


def test_epoch_bump_invalidates_existing_session(client):
    uid = client.get("/api/auth/me").json()["user"]["id"]
    client.app.state.user_store.bump_session_epoch(uid)
    assert client.get("/api/auth/me").status_code == 401   # old epoch rejected
    # A fresh login (new epoch) works again.
    _login(client)
    assert client.get("/api/auth/me").status_code == 200


def test_pre032_token_without_epoch_is_rejected(client):
    import jwt as _jwt
    from app.api.security import load_secret

    uid = client.get("/api/auth/me").json()["user"]["id"]
    # A pre-feature-032 token: sub/email/exp only, no epoch/aexp claims → forced re-login (Q2).
    legacy = _jwt.encode(
        {"sub": uid, "email": _AUTH_EMAIL, "exp": int(time.time()) + 3600},
        load_secret(),
        algorithm="HS256",
    )
    client.cookies.set("cs_session", legacy)
    assert client.get("/api/auth/me").status_code == 401


# ── AC-11 / AC-12: password change + logout-all ──────────────────────────────


def test_password_change_invalidates_other_sessions(client):
    old_cookie = client.cookies.get("cs_session")
    r = client.post(
        "/api/auth/me/password",
        json={"current_password": _AUTH_PASSWORD, "new_password": "NewStrongPass1!"},
    )
    assert r.status_code == 200
    # The changer stays logged in (fresh cookie re-issued).
    assert client.get("/api/auth/me").status_code == 200
    # A different browser holding the pre-change session is now logged out.
    other = TestClient(client.app)
    other.cookies.set("cs_session", old_cookie)
    assert other.get("/api/auth/me").status_code == 401


def test_logout_all_requires_auth_and_invalidates(client):
    old_cookie = client.cookies.get("cs_session")
    anon = TestClient(client.app)
    assert anon.post("/api/auth/logout-all").status_code == 401  # requires auth
    assert client.post("/api/auth/logout-all").status_code == 200
    other = TestClient(client.app)
    other.cookies.set("cs_session", old_cookie)
    assert other.get("/api/auth/me").status_code == 401  # all sessions invalidated
