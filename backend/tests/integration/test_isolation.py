"""
Integration tests for feature 019 — per-user data isolation.

Two accounts (Alice, Bob) share one backend/DB; each must see ONLY its own jobs. We drive
both from a single lifespan-managed `client` (from conftest) by clearing cookies and
re-authenticating — TestClient stores cookies per instance, so this switches the acting
account against the same server state.

Covers AC-A2 (scoped list), AC-A3/A4 (non-owned by-id → 404), AC-A5 (scoped dashboard),
AC-A6 (legacy NULL-owner rows hidden), AC-A7 (second account starts empty).
"""

from tests.integration.conftest import authenticate_as, current_user_id, _wait_for


def _submit(client, filename="c.pdf"):
    r = client.post(
        "/api/analyze",
        files={"file": (filename, b"%PDF-1.4", "application/pdf")},
    )
    assert r.status_code == 202
    return r.json()["job_id"]


def _as(client, email):
    """Switch the acting account on this client."""
    client.cookies.clear()
    authenticate_as(client, email)


def test_two_accounts_are_isolated(client):
    # ── Alice creates a job and sees it ──────────────────────────────────────
    _as(client, "alice@iso.com")
    alice_id = current_user_id(client)
    job_id = _submit(client, "alice_contract.pdf")
    _wait_for(client, job_id, "completed")

    alice_jobs = client.get("/api/jobs").json()
    assert alice_jobs["total"] == 1
    assert [i["job_id"] for i in alice_jobs["items"]] == [job_id]
    assert client.get(f"/api/jobs/{job_id}").status_code == 200          # AC-A3 owner ok
    assert client.get(f"/api/jobs/{job_id}/report").status_code == 200   # AC-A4 owner ok
    alice_dash = client.get("/api/dashboard").json()
    assert alice_dash["total_contracts"] == 1                            # AC-A5

    # ── Bob signs up fresh → empty workspace, no access to Alice's job ───────
    _as(client, "bob@iso.com")
    assert current_user_id(client) != alice_id
    bob_jobs = client.get("/api/jobs").json()
    assert bob_jobs["total"] == 0 and bob_jobs["items"] == []            # AC-A2 / AC-A7
    assert client.get(f"/api/jobs/{job_id}").status_code == 404          # AC-A3
    assert client.get(f"/api/jobs/{job_id}/report").status_code == 404   # AC-A4
    assert client.get(f"/api/jobs/{job_id}/events").status_code == 404   # AC-A4
    bob_dash = client.get("/api/dashboard").json()
    assert bob_dash["total_contracts"] == 0                              # AC-A5

    # ── Back as Alice → her data is intact ───────────────────────────────────
    _as(client, "alice@iso.com")
    assert client.get("/api/jobs").json()["total"] == 1
    assert client.get(f"/api/jobs/{job_id}").status_code == 200


def test_legacy_null_owner_row_hidden_from_all(client):
    # Seed a completed row with NO owner directly into the store (pre-019 legacy row).
    from app.runner.store import JobRow
    from app.runner.models import JobState

    store = client.app.state.ctx.registry._store
    store.upsert(
        JobRow(
            job_id="legacy-xyz",
            document_path="/tmp/legacy.pdf",
            recipient=None,
            status=JobState.completed,
            submitted_at="2026-01-01T00:00:00+00:00",
            started_at=None,
            finished_at="2026-01-01T00:05:00+00:00",
            current_node="report",
            completed_nodes=[],
            report_path=None,
            mcp_delivery_status={},
            error=None,
            original_filename="legacy.pdf",
            user_id=None,
        )
    )

    _as(client, "carol@iso.com")
    jobs = client.get("/api/jobs").json()
    assert all(i["job_id"] != "legacy-xyz" for i in jobs["items"])       # AC-A6
    assert client.get("/api/jobs/legacy-xyz").status_code == 404         # AC-A6 / EC-1
