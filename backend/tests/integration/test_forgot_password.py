"""
Integration tests for the forgot-password + reset-password endpoints (feature 034).

The `client` fixture (conftest) auto-authenticates the shared user `_AUTH_EMAIL` and redirects the DB
to tmp. We patch `app.api.auth.send_reset_email` with a recorder so no real Gmail is hit; FastAPI's
TestClient drains the background task before returning, so post-response DB/mail assertions are
deterministic.
"""

from datetime import datetime, timedelta, timezone

import pytest

import app.config as _cfg
from app.api.security import hash_reset_token, make_session
from tests.integration.conftest import _AUTH_EMAIL, _AUTH_PASSWORD

_NEW_PASSWORD = "NewPassw0rd!"


@pytest.fixture
def sent(monkeypatch):
    """Record calls to send_reset_email as (to, reset_url) without hitting Gmail."""
    calls = []

    async def _record(to, reset_url):
        calls.append((to, reset_url))

    monkeypatch.setattr("app.api.auth.send_reset_email", _record)
    return calls


def _raw_from(reset_url: str) -> str:
    return reset_url.split("token=")[1]


def _user_id(client) -> str:
    return client.app.state.user_store.get_by_email(_AUTH_EMAIL).id


def _reset_limiters(client):
    client.app.state.rate_limiter.reset()


# ── forgot-password ────────────────────────────────────────────────────────────


def test_known_email_sends_link(client, sent):  # AC-1
    r = client.post("/api/auth/forgot-password", json={"email": _AUTH_EMAIL})
    assert r.status_code == 200
    assert r.json()["ok"] is True
    assert len(sent) == 1
    to, url = sent[0]
    assert to == _AUTH_EMAIL
    assert url.startswith(_cfg.FRONTEND_RESET_URL)
    assert "?token=" in url


def test_token_row_hashed_and_bound(client, sent):  # AC-4
    client.post("/api/auth/forgot-password", json={"email": _AUTH_EMAIL})
    raw = _raw_from(sent[0][1])
    store = client.app.state.password_reset_store
    row = store.get_by_hash(hash_reset_token(raw))
    assert row is not None
    assert row.used_at is None
    assert row.user_id == _user_id(client)
    # the RAW token is never stored as the hash
    assert row.token_hash != raw


def test_unknown_email_no_send_no_row(client, sent):  # AC-2
    r = client.post("/api/auth/forgot-password", json={"email": "nobody@nowhere.test"})
    assert r.status_code == 200
    assert r.json()["ok"] is True
    assert sent == []


def test_responses_byte_identical(client, sent):  # AC-3
    known1 = client.post("/api/auth/forgot-password", json={"email": _AUTH_EMAIL})
    unknown = client.post("/api/auth/forgot-password", json={"email": "ghost@nowhere.test"})
    # second KNOWN request WITHIN cooldown (do NOT reset the limiter) → suppression branch
    known2 = client.post("/api/auth/forgot-password", json={"email": _AUTH_EMAIL})
    assert known1.content == unknown.content == known2.content


def test_prior_token_invalidated(client, sent):  # AC-5
    client.post("/api/auth/forgot-password", json={"email": _AUTH_EMAIL})
    raw1 = _raw_from(sent[0][1])
    _reset_limiters(client)  # clear the per-email cooldown so the 2nd issuance runs
    client.post("/api/auth/forgot-password", json={"email": _AUTH_EMAIL})
    store = client.app.state.password_reset_store
    assert store.get_by_hash(hash_reset_token(raw1)).used_at is not None  # invalidated


def test_per_ip_rate_limit(client, sent):  # AC-6
    _reset_limiters(client)
    codes = [
        client.post("/api/auth/forgot-password", json={"email": _AUTH_EMAIL}).status_code
        for _ in range(_cfg.AUTH_RATE_LIMIT_MAX + 1)
    ]
    assert codes[-1] == 429


def test_cooldown_suppresses_second_email(client, sent):  # AC-7
    client.post("/api/auth/forgot-password", json={"email": _AUTH_EMAIL})
    r2 = client.post("/api/auth/forgot-password", json={"email": _AUTH_EMAIL})  # within cooldown
    assert r2.status_code == 200
    assert len(sent) == 1  # no second email


def test_send_failure_still_200(client, monkeypatch):  # AC-9
    async def _boom(to, reset_url):
        raise RuntimeError("smtp down")

    monkeypatch.setattr("app.api.auth.send_reset_email", _boom)
    r = client.post("/api/auth/forgot-password", json={"email": _AUTH_EMAIL})
    assert r.status_code == 200


# ── reset-password ───────────────────────────────────────────────────────────


def _issue_and_get_raw(client, sent) -> str:
    _reset_limiters(client)
    client.post("/api/auth/forgot-password", json={"email": _AUTH_EMAIL})
    return _raw_from(sent[-1][1])


def test_reset_changes_password(client, sent):  # AC-10 / AC-10b
    raw = _issue_and_get_raw(client, sent)
    r = client.post("/api/auth/reset-password", json={"token": raw, "new_password": _NEW_PASSWORD})
    assert r.status_code == 200
    _reset_limiters(client)
    # new password logs in; old does not
    assert client.post("/api/auth/login", json={"email": _AUTH_EMAIL, "password": _NEW_PASSWORD}).status_code == 200
    _reset_limiters(client)
    assert client.post("/api/auth/login", json={"email": _AUTH_EMAIL, "password": _AUTH_PASSWORD}).status_code == 401


def test_reset_bumps_epoch_logs_out_sessions(client, sent):  # AC-11
    user = client.app.state.user_store.get_by_email(_AUTH_EMAIL)
    old_cookie = make_session(user)  # epoch at time of mint
    # a request bearing the pre-reset token works
    assert client.get("/api/auth/me", cookies={_cfg.AUTH_COOKIE_NAME: old_cookie}).status_code == 200

    raw = _issue_and_get_raw(client, sent)
    client.post("/api/auth/reset-password", json={"token": raw, "new_password": _NEW_PASSWORD})

    # the same pre-reset token is now rejected (epoch bumped)
    assert client.get("/api/auth/me", cookies={_cfg.AUTH_COOKIE_NAME: old_cookie}).status_code == 401


def test_token_single_use(client, sent):  # AC-12
    raw = _issue_and_get_raw(client, sent)
    assert client.post("/api/auth/reset-password", json={"token": raw, "new_password": _NEW_PASSWORD}).status_code == 200
    _reset_limiters(client)
    r2 = client.post("/api/auth/reset-password", json={"token": raw, "new_password": "Another0ne!"})
    assert r2.status_code == 400


def test_expired_token_rejected(client, sent):  # AC-13
    raw = "expired-raw-token-xyz"
    store = client.app.state.password_reset_store
    now = datetime.now(timezone.utc)
    store.create(
        "exp1", _user_id(client), hash_reset_token(raw), now.isoformat(),
        (now - timedelta(minutes=1)).isoformat(),  # already expired
    )
    r = client.post("/api/auth/reset-password", json={"token": raw, "new_password": _NEW_PASSWORD})
    assert r.status_code == 400
    # password unchanged
    _reset_limiters(client)
    assert client.post("/api/auth/login", json={"email": _AUTH_EMAIL, "password": _AUTH_PASSWORD}).status_code == 200


def test_unknown_token_rejected(client, sent):  # AC-14
    r = client.post("/api/auth/reset-password", json={"token": "does-not-exist", "new_password": _NEW_PASSWORD})
    assert r.status_code == 400


def test_deleted_user_token_rejected(client, sent):  # AC-14b
    raw = "orphan-raw-token"
    store = client.app.state.password_reset_store
    now = datetime.now(timezone.utc)
    store.create(
        "orph1", "ghost-user-id", hash_reset_token(raw), now.isoformat(),
        (now + timedelta(minutes=30)).isoformat(),
    )
    r = client.post("/api/auth/reset-password", json={"token": raw, "new_password": _NEW_PASSWORD})
    assert r.status_code == 400  # no crash


def test_weak_password_422_token_preserved(client, sent):  # AC-15
    raw = _issue_and_get_raw(client, sent)
    r = client.post("/api/auth/reset-password", json={"token": raw, "new_password": "short"})
    assert r.status_code == 422
    store = client.app.state.password_reset_store
    assert store.get_by_hash(hash_reset_token(raw)).used_at is None  # still redeemable


def test_reset_per_ip_rate_limit(client, sent):  # AC-16
    _reset_limiters(client)
    codes = [
        client.post("/api/auth/reset-password", json={"token": "x", "new_password": _NEW_PASSWORD}).status_code
        for _ in range(_cfg.AUTH_RATE_LIMIT_MAX + 1)
    ]
    assert codes[-1] == 429


def test_reset_sets_no_cookie(client, sent):  # AC-17
    raw = _issue_and_get_raw(client, sent)
    r = client.post("/api/auth/reset-password", json={"token": raw, "new_password": _NEW_PASSWORD})
    assert r.status_code == 200
    assert "set-cookie" not in {k.lower() for k in r.headers.keys()}


def test_endpoints_work_without_auth(client, sent):  # AC-18
    client.cookies.clear()
    assert client.post("/api/auth/forgot-password", json={"email": _AUTH_EMAIL}).status_code == 200
    raw = _raw_from(sent[-1][1])
    _reset_limiters(client)
    client.cookies.clear()
    assert client.post("/api/auth/reset-password", json={"token": raw, "new_password": _NEW_PASSWORD}).status_code == 200
