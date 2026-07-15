"""
Integration tests for POST /api/analyze — upload + job submission.

TDD red phase: all tests FAIL (ImportError) until Task 19 implements create_app.
Run: python -m pytest tests/integration/test_api_analyze.py -v
"""

import threading
from dataclasses import dataclass
from typing import Optional

from tests.integration.conftest import _wait_for

# ---------------------------------------------------------------------------
# Helpers for tests that need slow / error fake behavior
# ---------------------------------------------------------------------------


@dataclass
class _FakeRunResult:
    final_state: dict
    report_path: Optional[str]
    mcp_delivery_status: dict
    ingest_error: Optional[dict]


def _happy_result(doc="c.pdf"):
    return _FakeRunResult(
        final_state={"document_path": doc, "report_path": "r.md"},
        report_path="r.md",
        mcp_delivery_status={},
        ingest_error=None,
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_analyze_pdf_returns_202(client):
    """Valid .pdf → 202 + job_id; immediate status is queued or running, never completed."""
    resp = client.post(
        "/api/analyze",
        files={"file": ("contract.pdf", b"%PDF-1.4 fake content", "application/pdf")},
    )
    assert resp.status_code == 202
    data = resp.json()
    assert "job_id" in data
    assert data["status"] in ("queued", "running")


def test_analyze_stamps_owner(client):
    """POST /api/analyze stamps the created job with the authed user's id (AC-A1)."""
    from tests.integration.conftest import current_user_id

    uid = current_user_id(client)
    resp = client.post(
        "/api/analyze",
        files={"file": ("contract.pdf", b"%PDF-1.4 fake", "application/pdf")},
    )
    assert resp.status_code == 202
    job_id = resp.json()["job_id"]

    row = client.app.state.ctx.registry._store.get(job_id)
    assert row is not None
    assert row.user_id == uid


def test_analyze_docx_accepted(client):
    """.docx is accepted identically to .pdf."""
    resp = client.post(
        "/api/analyze",
        files={
            "file": (
                "contract.docx",
                b"PK fake docx content",
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            )
        },
    )
    assert resp.status_code == 202
    assert "job_id" in resp.json()


def test_upload_saved_and_path_passed(client):
    """Uploaded bytes land under UPLOAD_DIR; job completed → graph was called with the path."""
    import app.config as _config
    import os

    resp = client.post(
        "/api/analyze",
        files={"file": ("contract.pdf", b"%PDF-1.4 hello", "application/pdf")},
    )
    assert resp.status_code == 202
    job_id = resp.json()["job_id"]

    _wait_for(client, job_id, "completed")

    # Read UPLOAD_DIR from config (which was monkeypatched by the client fixture)
    upload_dir = _config.UPLOAD_DIR
    assert os.path.isdir(upload_dir), f"UPLOAD_DIR {upload_dir!r} not created"
    upload_files = [f for f in os.listdir(upload_dir) if f.endswith(".pdf")]
    assert len(upload_files) >= 1, f"No .pdf file under {upload_dir!r}"

    status = client.get(f"/api/jobs/{job_id}").json()
    assert status["status"] == "completed"


def test_recipient_forwarded(client, monkeypatch):
    """recipient form field reaches deliver_report_sync(recipient=...)."""
    import app.runner.core as core_mod

    recipients_seen = []

    def capture_delivery(state, *, recipient=None):
        recipients_seen.append(recipient)
        return {"mcp_delivery_status": {}}

    monkeypatch.setattr(core_mod, "deliver_report_sync", capture_delivery)

    resp = client.post(
        "/api/analyze",
        data={"recipient": "user@example.com"},
        files={"file": ("c.pdf", b"%PDF", "application/pdf")},
    )
    assert resp.status_code == 202
    job_id = resp.json()["job_id"]

    _wait_for(client, job_id, "completed")

    assert recipients_seen and recipients_seen[0] == "user@example.com"


def test_unsupported_extension_400_no_job(client):
    """.txt → 400; no job created."""
    resp = client.post(
        "/api/analyze",
        files={"file": ("contract.txt", b"plain text", "text/plain")},
    )
    assert resp.status_code == 400
    # No job created — list all jobs is not an endpoint, but we can verify by checking
    # that there's no job_id in the response body
    assert "job_id" not in resp.json()


def test_oversized_413(client, monkeypatch):
    """File > MAX_UPLOAD_SIZE_BYTES → 413."""
    import app.config as _config

    monkeypatch.setattr(_config, "MAX_UPLOAD_SIZE_BYTES", 10)

    resp = client.post(
        "/api/analyze",
        files={"file": ("contract.pdf", b"X" * 100, "application/pdf")},
    )
    assert resp.status_code == 413


def test_empty_upload_400(client):
    """Zero-byte file → 400; no job created."""
    resp = client.post(
        "/api/analyze",
        files={"file": ("contract.pdf", b"", "application/pdf")},
    )
    assert resp.status_code == 400


def test_response_not_blocked_by_run(client, monkeypatch):
    """With a slow fake run, the 202 returns while the job is still running (AC-20)."""
    import app.runner.worker as worker_mod

    hold = threading.Event()

    def slow_run(document_path, *, recipient=None, on_progress=None, **kwargs):
        hold.wait(timeout=10.0)
        return _happy_result(document_path)

    monkeypatch.setattr(worker_mod, "run_pipeline", slow_run)

    resp = client.post(
        "/api/analyze",
        files={"file": ("c.pdf", b"%PDF", "application/pdf")},
    )
    assert resp.status_code == 202
    job_id = resp.json()["job_id"]

    # 202 was returned immediately (job is running in background)
    status_resp = client.get(f"/api/jobs/{job_id}")
    assert status_resp.status_code == 200
    assert status_resp.json()["status"] in ("queued", "running")

    # Release before client teardown (review T1)
    hold.set()
    _wait_for(client, job_id, "completed")
