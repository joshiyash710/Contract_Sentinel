"""
Feature 056 — integration tests for GET /api/jobs/{job_id}/source.

Owner-scoped + auth'd; serves the decrypted original PDF; PDF-only (415 for DOCX); missing source → 404.
"""

import os

import app.config as _config
from tests.integration.conftest import authenticate_as


def _submit_pdf(client, content=b"%PDF-1.4 hello", filename="c.pdf"):
    r = client.post("/api/analyze", files={"file": (filename, content, "application/pdf")})
    assert r.status_code == 202, r.text
    return r.json()["job_id"]


def test_ac3_serves_decrypted_pdf(client):
    content = b"%PDF-1.4 the original contract bytes"
    job_id = _submit_pdf(client, content=content)
    r = client.get(f"/api/jobs/{job_id}/source")
    assert r.status_code == 200
    assert "application/pdf" in r.headers.get("content-type", "")
    assert r.content == content  # decrypted → original pre-encryption bytes


def test_ac8_docx_returns_415(client):
    r = client.post(
        "/api/analyze",
        files={"file": ("c.docx", b"PK\x03\x04 docx", "application/vnd.openxmlformats-officedocument.wordprocessingml.document")},
    )
    assert r.status_code == 202, r.text
    job_id = r.json()["job_id"]
    assert client.get(f"/api/jobs/{job_id}/source").status_code == 415


def test_ac7_missing_source_404(client):
    job_id = _submit_pdf(client)
    # Simulate a vanished source (disk upload removed) → graceful 404.
    os.remove(os.path.join(_config.UPLOAD_DIR, f"{job_id}.pdf"))
    assert client.get(f"/api/jobs/{job_id}/source").status_code == 404


def test_ac5_unauthenticated_401(client):
    from app.api.main import create_app
    from starlette.testclient import TestClient

    job_id = _submit_pdf(client)  # a real owned job on the shared DB
    with TestClient(create_app()) as anon:  # no authenticate() → no session cookie
        assert anon.get(f"/api/jobs/{job_id}/source").status_code == 401


def test_ac4_owner_isolation_404(client):
    from app.api.main import create_app
    from starlette.testclient import TestClient

    job_id = _submit_pdf(client)  # owned by the shared integration user
    with TestClient(create_app()) as other:
        authenticate_as(other, "other_owner_056@iso.test")  # a DIFFERENT account
        assert other.get(f"/api/jobs/{job_id}/source").status_code == 404
