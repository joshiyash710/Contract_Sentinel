"""
Integration tests for GET /api/jobs/{job_id}/report?format=md|json.

TDD red phase: all tests FAIL (ImportError) until Task 19 implements create_app.
Run: python -m pytest tests/integration/test_api_report.py -v
"""

import threading

from tests.integration.conftest import _wait_for


def _submit(client, filename="c.pdf"):
    r = client.post(
        "/api/analyze",
        files={"file": (filename, b"%PDF-1.4", "application/pdf")},
    )
    assert r.status_code == 202
    return r.json()["job_id"]


def test_download_markdown(client):
    """Completed job GET /report?format=md → text/markdown body (AC-12)."""
    job_id = _submit(client)
    _wait_for(client, job_id, "completed")

    r = client.get(f"/api/jobs/{job_id}/report?format=md")
    assert r.status_code == 200
    assert "text/markdown" in r.headers.get("content-type", "")
    assert "Risk Report" in r.text


def test_download_json(client):
    """GET /report?format=json → application/json sibling (AC-12)."""
    job_id = _submit(client)
    _wait_for(client, job_id, "completed")

    r = client.get(f"/api/jobs/{job_id}/report?format=json")
    assert r.status_code == 200
    assert "application/json" in r.headers.get("content-type", "")
    data = r.json()
    assert isinstance(data, dict)


def test_report_before_ready_409(client, monkeypatch):
    """GET /report on a still-running job → 409 (AC-14)."""
    import app.runner.worker as worker_mod

    hold = threading.Event()

    def slow_run(document_path, *, recipient=None, on_progress=None):
        hold.wait(timeout=10.0)
        from dataclasses import dataclass
        from typing import Optional

        @dataclass
        class _FR:
            final_state: dict
            report_path: Optional[str]
            mcp_delivery_status: dict
            ingest_error: Optional[dict]

        return _FR(
            final_state={},
            report_path="r.md",
            mcp_delivery_status={},
            ingest_error=None,
        )

    monkeypatch.setattr(worker_mod, "run_pipeline", slow_run)

    job_id = _submit(client)

    # Job is running (held) — /report should be 409
    import time

    time.sleep(0.1)
    r = client.get(f"/api/jobs/{job_id}/report")
    assert r.status_code == 409

    hold.set()  # release before teardown (review T1)
    _wait_for(client, job_id, "completed")


def test_report_path_only_from_record(client):
    """Served file is the record's report_path (no client path honored — AC-13)."""
    job_id = _submit(client)
    _wait_for(client, job_id, "completed")

    # The record's report_path is what was set by the fake graph (test_contract.md)
    # We can verify that the file served has the content the fake wrote
    r = client.get(f"/api/jobs/{job_id}/report?format=md")
    assert r.status_code == 200
    assert "Risk Report" in r.text  # content matches what _fake_build_graph wrote


def test_missing_file_on_disk_404(client, tmp_path):
    """report_path set but file deleted → 404; report_available False (EC-8)."""
    job_id = _submit(client)
    _wait_for(client, job_id, "completed")

    # Verify it's currently available
    status = client.get(f"/api/jobs/{job_id}").json()
    assert status["report_available"] is True
    report_path = status["report_path"]

    # Delete the report file
    import os

    if report_path and os.path.exists(report_path):
        os.remove(report_path)

    # Now the file is gone
    r = client.get(f"/api/jobs/{job_id}/report?format=md")
    assert r.status_code == 404

    # report_available reflects disk state
    status2 = client.get(f"/api/jobs/{job_id}").json()
    assert status2["report_available"] is False


def test_report_unknown_job_404(client):
    """GET /report on unknown id → 404 (AC-17)."""
    r = client.get("/api/jobs/does-not-exist/report")
    assert r.status_code == 404
