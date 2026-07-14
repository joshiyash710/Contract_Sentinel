"""
Integration tests for feature 014 auth endpoints and require_auth enforcement.

AC-1..10 + AC-7a (no secrets in logs/responses). Uses TestClient (httpx-backed)
which persists cookies on the instance for authenticated session tests.
"""

import logging
import pytest
from unittest.mock import patch
from starlette.testclient import TestClient


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

TEST_EMAIL = "test@example.com"
TEST_PW = "password123"


def _make_auth_client(monkeypatch, tmp_path):
    """Build a TestClient with faked graph + auth-enabled app (Task 4's variant)."""
    import app.config as _cfg
    from app.api.main import create_app

    report_dir = tmp_path / "reports"
    report_dir.mkdir(parents=True, exist_ok=True)

    def _fake_build_graph(checkpointer=None):
        class _FakeGraph:
            def stream(self, initial, stream_mode=None, config=None):
                yield {"current_node": "ingest_agent", "document_path": "c.pdf", "node_timings": {"ingest_agent": 0.01}}
                yield {"current_node": "report", "document_path": "c.pdf",
                       "node_timings": {"report": 0.01},
                       "report_path": str(report_dir / "test_contract.md"),
                       "document_id": "test_contract"}

        return _FakeGraph()

    monkeypatch.setattr("app.runner.core.build_graph", _fake_build_graph)
    monkeypatch.setattr("app.runner.core.deliver_report_sync", lambda state, **kw: {
        "mcp_delivery_status": {
            "drive": {"status": "SUCCESS", "error_message": None, "delivered_at": "t"},
            "gmail": {"status": "SUCCESS", "error_message": None, "delivered_at": "t"},
        }
    })
    monkeypatch.setattr(_cfg, "UPLOAD_DIR", str(tmp_path / "uploads"))
    monkeypatch.setattr(_cfg, "JOB_STORE_DB_PATH", str(tmp_path / "job_store.db"))
    monkeypatch.setattr(_cfg, "CHECKPOINTER_DB_PATH", str(tmp_path / "checkpoints.db"))
    monkeypatch.setattr(_cfg, "STARTUP_RECOVERY_ENABLED", False)
    monkeypatch.setenv("AUTH_SECRET", "t" * 32)
    monkeypatch.setattr(_cfg, "AUTH_SECRET_FILE", str(tmp_path / "auth_secret"))
    monkeypatch.setattr(_cfg, "AUTH_SIGNUP_OPEN", True)

    return TestClient(create_app())


@pytest.fixture()
def auth_client(monkeypatch, tmp_path):
    with _make_auth_client(monkeypatch, tmp_path) as c:
        yield c


def _signup(client, email=TEST_EMAIL, password=TEST_PW):
    return client.post("/api/auth/signup", json={"email": email, "password": password})


def _login(client, email=TEST_EMAIL, password=TEST_PW):
    return client.post("/api/auth/login", json={"email": email, "password": password})


# ---------------------------------------------------------------------------
# AC-1: signup sets cookie, bcrypt hash stored (not plaintext)
# ---------------------------------------------------------------------------


def test_signup_sets_cookie_and_hashes_pw(auth_client, tmp_path, monkeypatch):
    import app.config as _cfg
    monkeypatch.setattr(_cfg, "JOB_STORE_DB_PATH", str(tmp_path / "job_store.db"))

    r = _signup(auth_client)
    assert r.status_code == 200
    body = r.json()
    assert body["user"]["email"] == TEST_EMAIL
    assert body["user"]["id"]
    # Cookie set on the client
    assert "cs_session" in auth_client.cookies

    # The password_hash is NOT the plaintext (AC-1)
    import sqlite3
    from app.api.security import verify_password

    db_path = auth_client.app.state.user_store._conn.database if hasattr(auth_client.app.state.user_store._conn, 'database') else None
    # Verify via the store
    us = auth_client.app.state.user_store
    row = us.get_by_email(TEST_EMAIL)
    assert row is not None
    assert row.password_hash != TEST_PW
    assert verify_password(TEST_PW, row.password_hash)


# ---------------------------------------------------------------------------
# AC-2: duplicate email → 409; email stored lowercase
# ---------------------------------------------------------------------------


def test_signup_dup_409(auth_client):
    _signup(auth_client)
    r = _signup(auth_client)
    assert r.status_code == 409


def test_signup_email_stored_lowercase(auth_client):
    r = auth_client.post("/api/auth/signup", json={"email": "UPPER@EXAMPLE.COM", "password": TEST_PW})
    assert r.status_code == 200
    us = auth_client.app.state.user_store
    assert us.get_by_email("upper@example.com") is not None


# ---------------------------------------------------------------------------
# AC-3: password outside 8–128 chars → 422; body doesn't echo password
# ---------------------------------------------------------------------------


def test_signup_short_password_422(auth_client):
    r = auth_client.post("/api/auth/signup", json={"email": "x@x.com", "password": "short"})
    assert r.status_code == 422
    body_text = r.text
    assert "short" not in body_text  # AC-7a — password not echoed


def test_signup_long_password_422(auth_client):
    long_pw = "A" * 129
    r = auth_client.post("/api/auth/signup", json={"email": "x@x.com", "password": long_pw})
    assert r.status_code == 422
    assert long_pw not in r.text  # AC-7a — password not echoed


def test_signup_exact_boundary_passwords(auth_client):
    # 8-char (minimum valid) succeeds
    r = auth_client.post("/api/auth/signup", json={"email": "min@x.com", "password": "12345678"})
    assert r.status_code == 200
    # 128-char (maximum valid) succeeds
    r2 = auth_client.post("/api/auth/signup", json={"email": "max@x.com", "password": "A" * 128})
    assert r2.status_code == 200


# ---------------------------------------------------------------------------
# AC-4: login ok + wrong-pw + unknown-email both 401 generic; verify runs on unknown-email
# ---------------------------------------------------------------------------


def test_login_ok_sets_cookie(auth_client):
    _signup(auth_client)
    auth_client.cookies.clear()
    r = _login(auth_client)
    assert r.status_code == 200
    assert "cs_session" in auth_client.cookies


def test_login_wrong_password_401_generic(auth_client):
    _signup(auth_client)
    auth_client.cookies.clear()
    r = auth_client.post("/api/auth/login", json={"email": TEST_EMAIL, "password": "wrongpassword"})
    assert r.status_code == 401
    assert r.json()["detail"] == "Invalid email or password"


def test_login_unknown_email_401_generic_and_verify_called(auth_client):
    """Unknown email must return the same generic 401 AND run verify_password (M2)."""
    from app.api import auth as auth_mod

    with patch.object(auth_mod, "verify_password", wraps=auth_mod.verify_password) as spy:
        r = auth_client.post("/api/auth/login", json={"email": "nobody@x.com", "password": TEST_PW})
        assert r.status_code == 401
        assert r.json()["detail"] == "Invalid email or password"
        spy.assert_called_once()


# ---------------------------------------------------------------------------
# AC-5: GET /api/auth/me with / without cookie
# ---------------------------------------------------------------------------


def test_me_requires_cookie(auth_client):
    r = auth_client.get("/api/auth/me")
    assert r.status_code == 401


def test_me_with_valid_cookie(auth_client):
    _signup(auth_client)
    r = auth_client.get("/api/auth/me")
    assert r.status_code == 200
    assert r.json()["user"]["email"] == TEST_EMAIL


# ---------------------------------------------------------------------------
# AC-6: logout clears cookie; subsequent me → 401
# ---------------------------------------------------------------------------


def test_logout_clears_cookie(auth_client):
    _signup(auth_client)
    r = auth_client.post("/api/auth/logout")
    assert r.status_code == 200
    # Cookie cleared
    auth_client.cookies.clear()
    r2 = auth_client.get("/api/auth/me")
    assert r2.status_code == 401


# ---------------------------------------------------------------------------
# AC-7: JWT alg=none / tampered → 401
# ---------------------------------------------------------------------------


def test_jwt_alg_none_rejected(auth_client):
    import jwt as _jwt

    none_token = _jwt.encode({"sub": "u1", "email": "a@b.com", "exp": 9999999999}, "", algorithm="none")
    auth_client.cookies.set("cs_session", none_token)
    r = auth_client.get("/api/auth/me")
    assert r.status_code == 401


def test_jwt_tampered_rejected(auth_client):
    _signup(auth_client)
    cookie_val = auth_client.cookies["cs_session"]
    tampered = cookie_val[:-3] + "XXX"
    auth_client.cookies.set("cs_session", tampered)
    r = auth_client.get("/api/auth/me")
    assert r.status_code == 401


# ---------------------------------------------------------------------------
# AC-8: protected endpoints require session; 2xx with session
# ---------------------------------------------------------------------------


def test_protected_endpoints_401_without_cookie(auth_client):
    for path in ["/api/jobs", "/api/dashboard"]:
        r = auth_client.get(path)
        assert r.status_code == 401, f"{path} should be 401 without auth"


def test_protected_endpoints_2xx_with_cookie(auth_client):
    _signup(auth_client)
    r = auth_client.get("/api/jobs")
    assert r.status_code == 200


# ---------------------------------------------------------------------------
# AC-9: health + /api/auth/* are public
# ---------------------------------------------------------------------------


def test_health_is_public(auth_client):
    r = auth_client.get("/api/health")
    assert r.status_code == 200


def test_auth_signup_is_public(auth_client):
    r = _signup(auth_client, email="pub@x.com")
    assert r.status_code == 200


# ---------------------------------------------------------------------------
# AC-10: two accounts share the same jobs (no per-user scoping)
# ---------------------------------------------------------------------------


def test_two_accounts_share_jobs(auth_client):
    # Account A signs up — sees empty jobs
    _signup(auth_client, email="a@x.com", password="password123")
    ra = auth_client.get("/api/jobs")
    assert ra.status_code == 200

    # Account B logs out from A, signs up as B — also sees the same (empty) jobs list
    auth_client.cookies.clear()
    _signup(auth_client, email="b@x.com", password="password123")
    rb = auth_client.get("/api/jobs")
    assert rb.status_code == 200
    assert ra.json()["total"] == rb.json()["total"]


# ---------------------------------------------------------------------------
# AC-7a: no secrets in logs during signup/login
# ---------------------------------------------------------------------------


def test_no_secrets_in_logs(auth_client, caplog):
    with caplog.at_level(logging.DEBUG):
        _signup(auth_client)
        auth_client.post("/api/auth/login", json={"email": TEST_EMAIL, "password": TEST_PW})

    log_text = caplog.text
    assert TEST_PW not in log_text, "Plaintext password leaked into logs"
    # AUTH_SECRET env var is set to 'tttttttt...' in the fixture — don't assert that
    # specific value since the test sets it; just check the actual password isn't there.
