"""
Integration tests for the per-user Google Drive OAuth endpoints (feature 031).

Uses the shared `client` TestClient fixture + authenticate helpers. The Google OAuth
Flow (_build_flow) and email lookup (_email_of) are mocked — no real Google calls.
"""

from urllib.parse import urlparse, parse_qs
from unittest.mock import MagicMock, patch

from tests.integration.conftest import authenticate, authenticate_as


def _fake_flow():
    """A fake google-auth-oauthlib Flow: authorization_url echoes the state into the URL;
    fetch_token is a no-op; credentials.to_json() returns a token."""
    flow = MagicMock()

    def _auth_url(**kw):
        st = kw.get("state", "S")
        return (
            f"https://accounts.google.com/o/oauth2/auth?scope="
            f"https%3A%2F%2Fwww.googleapis.com%2Fauth%2Fdrive.file"
            f"&access_type=offline&prompt=consent&state={st}",
            st,
        )

    flow.authorization_url.side_effect = _auth_url
    flow.code_verifier = "test-code-verifier-123"  # PKCE verifier carried authorize→callback
    creds = MagicMock()
    creds.to_json.return_value = '{"refresh_token":"USERTOK","scopes":["drive.file"]}'
    flow.credentials = creds
    return flow


def _authorize_and_get_state(client):
    """Hit /authorize (mocked flow) and return the generated state from the redirect URL."""
    with patch("app.api.integrations._build_flow", return_value=_fake_flow()):
        r = client.get("/api/integrations/google/authorize", follow_redirects=False)
    assert r.status_code == 302
    loc = r.headers["location"]
    assert "drive.file" in loc  # AC-5: scope present
    assert "access_type=offline" in loc and "prompt=consent" in loc
    return parse_qs(urlparse(loc).query)["state"][0]


# ── AC-4 / AC-9: status ──────────────────────────────────────────────────────
def test_status_requires_auth(client):
    client.cookies.clear()  # the shared client fixture auto-authenticates; drop the session
    r = client.get("/api/integrations/google/status")
    assert r.status_code == 401


def test_status_false_for_new_user(client):
    authenticate(client)
    r = client.get("/api/integrations/google/status")
    assert r.status_code == 200
    body = r.json()
    assert body["connected"] is False
    assert body.get("google_email") is None
    # AC-9: no token ever on the wire
    assert "USERTOK" not in r.text and "refresh_token" not in r.text


# ── AC-5/AC-6: authorize → callback connects ─────────────────────────────────
def test_full_connect_flow(client):
    authenticate(client)
    state = _authorize_and_get_state(client)
    with (
        patch("app.api.integrations._build_flow", return_value=_fake_flow()),
        patch("app.api.integrations._email_of", return_value="me@gmail.com"),
    ):
        r = client.get(
            f"/api/integrations/google/callback?code=abc&state={state}",
            follow_redirects=False,
        )
    assert r.status_code == 302
    assert "google=connected" in r.headers["location"]
    # now connected
    s = client.get("/api/integrations/google/status").json()
    assert s["connected"] is True
    assert s["google_email"] == "me@gmail.com"


# ── AC-7: CSRF ───────────────────────────────────────────────────────────────
def test_callback_rejects_bad_state(client):
    authenticate(client)
    _authorize_and_get_state(client)
    r = client.get(
        "/api/integrations/google/callback?code=abc&state=WRONG",
        follow_redirects=False,
    )
    assert r.status_code == 400
    assert client.get("/api/integrations/google/status").json()["connected"] is False


def test_callback_denied_stores_nothing(client):
    authenticate(client)
    r = client.get(
        "/api/integrations/google/callback?error=access_denied",
        follow_redirects=False,
    )
    assert r.status_code == 302
    assert "google=denied" in r.headers["location"]
    assert client.get("/api/integrations/google/status").json()["connected"] is False


# ── AC-7a: replay ────────────────────────────────────────────────────────────
def test_callback_state_is_single_use(client):
    authenticate(client)
    state = _authorize_and_get_state(client)
    with (
        patch("app.api.integrations._build_flow", return_value=_fake_flow()),
        patch("app.api.integrations._email_of", return_value="me@gmail.com"),
    ):
        r1 = client.get(
            f"/api/integrations/google/callback?code=abc&state={state}",
            follow_redirects=False,
        )
        assert r1.status_code == 302  # first use OK
        r2 = client.get(
            f"/api/integrations/google/callback?code=abc&state={state}",
            follow_redirects=False,
        )
    assert r2.status_code == 400  # replay rejected


# ── AC-8: disconnect ─────────────────────────────────────────────────────────
def test_disconnect_clears(client):
    authenticate(client)
    state = _authorize_and_get_state(client)
    with (
        patch("app.api.integrations._build_flow", return_value=_fake_flow()),
        patch("app.api.integrations._email_of", return_value="me@gmail.com"),
    ):
        client.get(
            f"/api/integrations/google/callback?code=abc&state={state}",
            follow_redirects=False,
        )
    assert client.get("/api/integrations/google/status").json()["connected"] is True
    # revoke is best-effort — patch it to raise; disconnect must still succeed
    with patch("app.api.integrations.revoke_token", side_effect=Exception("revoke down")):
        d = client.post("/api/integrations/google/disconnect")
    assert d.status_code == 200
    assert d.json()["connected"] is False
    assert client.get("/api/integrations/google/status").json()["connected"] is False


# ── PKCE: code_verifier carried authorize → callback ─────────────────────────
def test_pkce_code_verifier_threaded_to_callback(client):
    """Regression: the PKCE code_verifier from authorize must be restored on the callback
    Flow before fetch_token (else Google rejects with 'Missing code verifier')."""
    authenticate(client)

    authorize_flow = _fake_flow()
    authorize_flow.code_verifier = "AUTH_VERIFIER"
    callback_flow = _fake_flow()
    callback_flow.code_verifier = None  # a fresh Flow has no verifier until we restore it

    with patch("app.api.integrations._build_flow", return_value=authorize_flow):
        r = client.get("/api/integrations/google/authorize", follow_redirects=False)
    state = parse_qs(urlparse(r.headers["location"]).query)["state"][0]

    with (
        patch("app.api.integrations._build_flow", return_value=callback_flow),
        patch("app.api.integrations._email_of", return_value="me@gmail.com"),
    ):
        client.get(
            f"/api/integrations/google/callback?code=abc&state={state}",
            follow_redirects=False,
        )
    # the callback Flow had the authorize step's verifier restored onto it
    assert callback_flow.code_verifier == "AUTH_VERIFIER"
    callback_flow.fetch_token.assert_called_once()


# ── AC-17: per-user isolation ────────────────────────────────────────────────
def test_connection_is_per_user(client):
    # user A connects
    authenticate_as(client, "aaa@iso.test")
    state = _authorize_and_get_state(client)
    with (
        patch("app.api.integrations._build_flow", return_value=_fake_flow()),
        patch("app.api.integrations._email_of", return_value="aaa@gmail.com"),
    ):
        client.get(
            f"/api/integrations/google/callback?code=abc&state={state}",
            follow_redirects=False,
        )
    assert client.get("/api/integrations/google/status").json()["connected"] is True
    # user B (same client, re-auth as a different account) is NOT connected
    authenticate_as(client, "bbb@iso.test")
    assert client.get("/api/integrations/google/status").json()["connected"] is False
