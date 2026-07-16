"""Feature 023 — account settings endpoints (spec AC-1..7).

PATCH /api/auth/me (edit name/title) and POST /api/auth/me/password (change password).
Uses the integration `client` fixture (already authenticated as _AUTH_EMAIL / _AUTH_PASSWORD).
"""

from tests.integration.conftest import (
    _AUTH_EMAIL,
    _AUTH_PASSWORD,
    authenticate_as,
)


# ── PATCH /api/auth/me — profile ────────────────────────────────────────────


def test_patch_me_updates_profile(client):  # AC-1
    r = client.patch("/api/auth/me", json={"name": "Updated Name", "title": "Counsel"})
    assert r.status_code == 200, r.text
    assert r.json()["user"]["name"] == "Updated Name"
    assert r.json()["user"]["title"] == "Counsel"

    me = client.get("/api/auth/me")
    assert me.json()["user"]["name"] == "Updated Name"
    assert me.json()["user"]["title"] == "Counsel"


def test_patch_me_blank_name_rejected(client):  # AC-2
    r = client.patch("/api/auth/me", json={"name": "   ", "title": "X"})
    assert r.status_code == 422


def test_patch_me_long_title_rejected(client):  # AC-2
    r = client.patch("/api/auth/me", json={"name": "Ok", "title": "x" * 101})
    assert r.status_code == 422


def test_patch_me_unauthenticated(client):  # AC-3
    client.cookies.clear()
    r = client.patch("/api/auth/me", json={"name": "Nope"})
    assert r.status_code == 401


# ── POST /api/auth/me/password — change password ────────────────────────────


def test_change_password_happy_then_relogin(client):  # AC-4
    r = client.post(
        "/api/auth/me/password",
        json={"current_password": _AUTH_PASSWORD, "new_password": "BrandNewPw1!"},
    )
    assert r.status_code == 200, r.text
    assert r.json().get("ok") is True

    client.cookies.clear()
    new_ok = client.post(
        "/api/auth/login", json={"email": _AUTH_EMAIL, "password": "BrandNewPw1!"}
    )
    assert new_ok.status_code == 200

    client.cookies.clear()
    old_bad = client.post(
        "/api/auth/login", json={"email": _AUTH_EMAIL, "password": _AUTH_PASSWORD}
    )
    assert old_bad.status_code == 401


def test_change_password_wrong_current(client):  # AC-5
    r = client.post(
        "/api/auth/me/password",
        json={"current_password": "not-the-password", "new_password": "BrandNewPw1!"},
    )
    assert r.status_code == 400
    # hash unchanged → the original password still logs in
    client.cookies.clear()
    still_ok = client.post(
        "/api/auth/login", json={"email": _AUTH_EMAIL, "password": _AUTH_PASSWORD}
    )
    assert still_ok.status_code == 200


def test_change_password_weak_new_rejected(client):  # AC-6
    r = client.post(
        "/api/auth/me/password",
        json={"current_password": _AUTH_PASSWORD, "new_password": "short"},
    )
    assert r.status_code == 422


def test_change_password_unauthenticated(client):  # AC-6
    client.cookies.clear()
    r = client.post(
        "/api/auth/me/password",
        json={"current_password": "x", "new_password": "BrandNewPw1!"},
    )
    assert r.status_code == 401


def test_account_isolation(client):  # AC-7
    # Switch the session to a second account and change ITS password.
    authenticate_as(client, "other023@x.com", "OtherPw1!")
    r = client.post(
        "/api/auth/me/password",
        json={"current_password": "OtherPw1!", "new_password": "OtherNewPw2!"},
    )
    assert r.status_code == 200, r.text

    # Account A is untouched — still logs in with its original password.
    client.cookies.clear()
    a_ok = client.post(
        "/api/auth/login", json={"email": _AUTH_EMAIL, "password": _AUTH_PASSWORD}
    )
    assert a_ok.status_code == 200
