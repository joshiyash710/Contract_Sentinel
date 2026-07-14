"""
Integration tests for the feature-018 endpoints: GET /api/jobs and GET /api/dashboard,
plus POST /api/analyze persisting the real filename. Uses the shared `client` fixture
(conftest) and seeds the registry/store directly with completed jobs + on-disk report
JSONs for full control over the aggregation.
"""

import io
import json

from app.runner.events import JobEventBuffer
from app.runner.models import JobState
from app.runner.registry import JobRecord


def _seed_completed(client, tmp_path, job_id, filename, summary, findings, submitted_at):
    reports = tmp_path / "dash_reports"
    reports.mkdir(exist_ok=True)
    md = reports / f"{job_id}.md"
    md.write_text("# report", encoding="utf-8")
    (reports / f"{job_id}.json").write_text(
        json.dumps({"summary": summary, "findings": findings}), encoding="utf-8"
    )
    reg = client.app.state.ctx.registry
    rec = JobRecord(
        job_id=job_id,
        document_path=f"/u/{job_id}.pdf",
        submitted_at=submitted_at,
        buffer=JobEventBuffer(loop=None),
        original_filename=filename,
    )
    reg.add(rec)
    rec.mark_running(submitted_at)
    rec.mark_terminal(status=JobState.completed, finished_at=submitted_at, report_path=str(md))


def _seed_status(client, job_id, status, submitted_at):
    reg = client.app.state.ctx.registry
    rec = JobRecord(
        job_id=job_id,
        document_path=f"/u/{job_id}.pdf",
        submitted_at=submitted_at,
        buffer=JobEventBuffer(loop=None),
        original_filename=f"{job_id}.pdf",
    )
    reg.add(rec)
    if status != JobState.queued:
        rec.mark_running(submitted_at)


def test_list_empty(client):
    r = client.get("/api/jobs")
    assert r.status_code == 200
    assert r.json() == {"items": [], "total": 0}  # AC-3


def test_dashboard_empty(client):
    r = client.get("/api/dashboard")
    assert r.status_code == 200
    m = r.json()
    assert m["total_contracts"] == 0 and m["completed_contracts"] == 0
    assert m["risk_distribution"] == {"high": 0, "medium": 0, "low": 0}
    assert m["portfolio_health_pct"] == 100  # AC-9, no div-by-zero
    assert len(m["usage_timeline"]) == 30 and all(b["count"] == 0 for b in m["usage_timeline"])
    assert m["risk_by_clause_type"] == [] and m["top_risky_clause_types"] == []


def test_list_shape_and_pagination(client, tmp_path):
    _seed_completed(client, tmp_path, "j1", "alpha.pdf",
                    {"high": 1, "medium": 0, "low": 1, "total_clauses": 2, "validated_findings": 2},
                    [{"clause_type": "liability", "risk_level": "high"}],
                    "2026-01-03T00:00:00+00:00")
    _seed_completed(client, tmp_path, "j2", "beta.pdf",
                    {"high": 0, "medium": 0, "low": 0, "total_clauses": 0, "validated_findings": 0},
                    [], "2026-01-02T00:00:00+00:00")
    _seed_status(client, "j3", JobState.running, "2026-01-01T00:00:00+00:00")

    r = client.get("/api/jobs")
    body = r.json()
    assert body["total"] == 3
    assert [i["job_id"] for i in body["items"]] == ["j1", "j2", "j3"]  # newest-first (AC-1)
    j1 = body["items"][0]
    assert j1["original_filename"] == "alpha.pdf" and j1["report_available"] is True
    assert j1["high"] == 1 and j1["low"] == 1 and j1["risk_band"] == "high"  # AC-2
    j3 = body["items"][2]
    assert j3["report_available"] is False and j3["risk_band"] is None and j3["high"] is None

    page2 = client.get("/api/jobs?limit=2&offset=2").json()
    assert [i["job_id"] for i in page2["items"]] == ["j3"] and page2["total"] == 3


def test_list_limit_clamped(client, tmp_path):
    _seed_status(client, "j1", JobState.queued, "2026-01-01T00:00:00+00:00")
    r = client.get("/api/jobs?limit=9999&offset=-5")  # EC-6
    assert r.status_code == 200 and r.json()["total"] == 1


def test_dashboard_aggregates(client, tmp_path):
    _seed_completed(client, tmp_path, "j1", "a.pdf",
                    {"high": 2, "medium": 1, "low": 0, "total_clauses": 3, "validated_findings": 3},
                    [{"clause_type": "liability", "risk_level": "high"},
                     {"clause_type": "liability", "risk_level": "high"},
                     {"clause_type": "payment", "risk_level": "medium"}],
                    "2026-01-03T00:00:00+00:00")
    _seed_completed(client, tmp_path, "j2", "b.pdf",
                    {"high": 0, "medium": 0, "low": 2, "total_clauses": 2, "validated_findings": 2},
                    [{"clause_type": "term", "risk_level": "low"},
                     {"clause_type": None, "risk_level": "low"}],
                    "2026-01-03T00:00:00+00:00")

    m = client.get("/api/dashboard").json()
    assert m["total_contracts"] == 2 and m["completed_contracts"] == 2  # AC-4/D10
    assert m["risk_distribution"] == {"high": 2, "medium": 1, "low": 2}  # AC-4/D8
    assert 0 <= m["portfolio_health_pct"] <= 100 and m["portfolio_health_band"] in {
        "healthy", "elevated", "at_risk"}  # AC-5
    types = {c["clause_type"] for c in m["risk_by_clause_type"]}
    assert "Uncategorized" in types and "liability" in types  # AC-6/D14
    assert m["clause_risk_heatmap"]["cols"] == ["low", "medium", "high"]
    assert m["top_risky_clause_types"][0]["clause_type"] == "liability"  # AC-7


def test_dashboard_missing_report_skipped(client, tmp_path):
    # Completed job whose report .json is absent (no _seed_completed files written).
    reg = client.app.state.ctx.registry
    rec = JobRecord(job_id="gone", document_path="/u/gone.pdf",
                    submitted_at="2026-01-03T00:00:00+00:00",
                    buffer=JobEventBuffer(loop=None), original_filename="gone.pdf")
    reg.add(rec)
    rec.mark_running("2026-01-03T00:00:00+00:00")
    rec.mark_terminal(status=JobState.completed, finished_at="t", report_path="/nope/x.md")

    m = client.get("/api/dashboard").json()
    assert m["total_contracts"] == 1  # counted
    assert m["risk_distribution"] == {"high": 0, "medium": 0, "low": 0}  # AC-10, skipped
    j = client.get("/api/jobs").json()["items"][0]
    assert j["report_available"] is False


def test_analyze_persists_real_filename(client):
    files = {"file": ("heavy_contract.docx", io.BytesIO(b"dummy contents"),
                      "application/vnd.openxmlformats-officedocument.wordprocessingml.document")}
    r = client.post("/api/analyze", files=files)
    assert r.status_code == 202
    listed = client.get("/api/jobs").json()["items"]
    assert any(i["original_filename"] == "heavy_contract.docx" for i in listed)  # AC-11


def test_jobs_routes_coexist(client, tmp_path):
    _seed_status(client, "j1", JobState.queued, "2026-01-01T00:00:00+00:00")
    assert client.get("/api/jobs").status_code == 200          # list
    assert client.get("/api/jobs/j1").status_code == 200        # per-job (no shadowing)
    assert client.get("/api/jobs/nope").status_code == 404
