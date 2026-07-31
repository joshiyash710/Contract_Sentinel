"""
Feature 032 (W3) — login rate-limiting & account lockout integration tests.

Covers AC-13 (lockout after N failures, 429 even with correct pw, auto-clears), AC-14 (success
resets), AC-15 (per-IP limit + independence), AC-16 (no email-existence disclosure), AC-20
(me/password rate-limited, not lockable).
"""

import time

from starlette.testclient import TestClient

from tests.integration.conftest import _AUTH_EMAIL, _AUTH_PASSWORD


def _wrong(client, email=None):
    return client.post("/api/auth/login", json={"email": email or _AUTH_EMAIL, "password": "wrong"})


def test_account_lockout_after_max_failures(client, monkeypatch):
    import app.config as _c

    monkeypatch.setattr(_c, "AUTH_LOCKOUT_MAX_FAILURES", 3)
    monkeypatch.setattr(_c, "AUTH_LOCKOUT_WINDOW_SECONDS", 1000)
    monkeypatch.setattr(_c, "AUTH_LOCKOUT_DURATION_SECONDS", 1)
    monkeypatch.setattr(_c, "AUTH_RATE_LIMIT_MAX", 1000)  # isolate lockout from per-IP limit
    client.app.state.rate_limiter.reset()

    for _ in range(3):
        assert _wrong(client).status_code == 401
    # Locked: correct password is now rejected with 429 + Retry-After (AC-13).
    r = client.post("/api/auth/login", json={"email": _AUTH_EMAIL, "password": _AUTH_PASSWORD})
    assert r.status_code == 429
    assert "retry-after" in {k.lower() for k in r.headers}
    # Auto-clears after the duration.
    time.sleep(1.2)
    r = client.post("/api/auth/login", json={"email": _AUTH_EMAIL, "password": _AUTH_PASSWORD})
    assert r.status_code == 200


def test_success_resets_failure_counter(client, monkeypatch):
    import app.config as _c

    monkeypatch.setattr(_c, "AUTH_LOCKOUT_MAX_FAILURES", 3)
    monkeypatch.setattr(_c, "AUTH_LOCKOUT_WINDOW_SECONDS", 1000)
    monkeypatch.setattr(_c, "AUTH_RATE_LIMIT_MAX", 1000)
    client.app.state.rate_limiter.reset()

    assert _wrong(client).status_code == 401
    assert _wrong(client).status_code == 401
    # A success before the threshold resets the counter (AC-14).
    assert client.post("/api/auth/login", json={"email": _AUTH_EMAIL, "password": _AUTH_PASSWORD}).status_code == 200
    # Two more failures now do not lock (counter was reset).
    assert _wrong(client).status_code == 401
    assert _wrong(client).status_code == 401
    assert client.post("/api/auth/login", json={"email": _AUTH_EMAIL, "password": _AUTH_PASSWORD}).status_code == 200


def test_per_ip_rate_limit_and_independence(client, monkeypatch):
    import app.config as _c

    monkeypatch.setattr(_c, "AUTH_RATE_LIMIT_MAX", 3)
    monkeypatch.setattr(_c, "AUTH_RATE_LIMIT_WINDOW_SECONDS", 100)
    monkeypatch.setattr(_c, "AUTH_LOCKOUT_MAX_FAILURES", 1000)  # don't lock in this test
    client.app.state.rate_limiter.reset()

    for _ in range(3):
        assert _wrong(client).status_code == 401  # within per-IP budget
    assert _wrong(client).status_code == 429       # over the per-IP limit (AC-15)

    # A different client IP is unaffected in the same window.
    other = TestClient(client.app, client=("9.9.9.9", 1234))
    assert _wrong(other).status_code == 401


def test_lockout_does_not_disclose_unknown_email(client, monkeypatch):
    import app.config as _c

    monkeypatch.setattr(_c, "AUTH_LOCKOUT_MAX_FAILURES", 2)
    monkeypatch.setattr(_c, "AUTH_LOCKOUT_WINDOW_SECONDS", 1000)
    monkeypatch.setattr(_c, "AUTH_LOCKOUT_DURATION_SECONDS", 1000)
    monkeypatch.setattr(_c, "AUTH_RATE_LIMIT_MAX", 1000)
    client.app.state.rate_limiter.reset()

    # An unknown email never enters the lockout path → always plain 401 (never 429 lock), and the
    # dummy bcrypt verify still runs (AC-16 / 014 M2). It also never creates a row.
    for _ in range(5):
        r = client.post("/api/auth/login", json={"email": "nobody@x.com", "password": "x"})
        assert r.status_code == 401
    assert client.app.state.user_store.get_by_email("nobody@x.com") is None


def test_me_password_rate_limited_but_not_lockable(client, monkeypatch):
    import app.config as _c

    monkeypatch.setattr(_c, "AUTH_RATE_LIMIT_MAX", 2)
    monkeypatch.setattr(_c, "AUTH_RATE_LIMIT_WINDOW_SECONDS", 100)
    client.app.state.rate_limiter.reset()

    body = {"current_password": "wrong", "new_password": "NewStrongPass1!"}
    # First 2 attempts: wrong current password → 400 (no lockout applies here).
    for _ in range(2):
        assert client.post("/api/auth/me/password", json=body).status_code == 400
    # 3rd exceeds the per-IP budget → 429 (AC-20).
    assert client.post("/api/auth/me/password", json=body).status_code == 429
