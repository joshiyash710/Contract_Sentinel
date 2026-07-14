"""
Pure aggregation tests (feature 018). No disk, no HTTP: build JobRow lists in memory and
inject a `read` stub returning ReportData | None. Covers the derived health/band, risk
aggregates, null-bucketing, dense usage timeline, and missing-report handling.
"""

from datetime import date

from app.runner.models import JobState
from app.runner.store import JobRow
from app.api.aggregate import (
    ReportData,
    derive_band,
    portfolio_health,
    build_job_list,
    build_dashboard_metrics,
)


def _row(job_id, submitted_at, *, status=JobState.completed, report_path="/r/x.md",
         original_filename="c.pdf", finished_at=None):
    return JobRow(
        job_id=job_id, document_path=f"/u/{job_id}.pdf", recipient=None, status=status,
        submitted_at=submitted_at, started_at=None, finished_at=finished_at,
        current_node="report", completed_nodes=[], report_path=report_path,
        mcp_delivery_status={}, error=None, original_filename=original_filename,
    )


def _rd(high=0, medium=0, low=0, findings=None):
    total = high + medium + low
    return ReportData(
        high=high, medium=medium, low=low, total_clauses=total,
        validated_findings=total, findings=findings or [],
    )


# ── derive_band (must match 017 TS deriveRiskBand) ──────────────────────────────
def test_derive_band_four_cases():
    assert derive_band(1, 5, 9, 15) == "high"
    assert derive_band(0, 2, 0, 2) == "medium"
    assert derive_band(0, 0, 3, 3) == "low"
    assert derive_band(0, 0, 0, 0) == "none"


# ── portfolio_health (D3) ───────────────────────────────────────────────────────
def test_health_all_low_is_healthy():
    pct, band = portfolio_health(0, 0, 10)
    assert pct == 100 and band == "healthy"


def test_health_high_dominated_is_at_risk():
    pct, band = portfolio_health(9, 0, 1)  # 1 - 9/10 = 0.1 → 10%
    assert pct == 10 and band == "at_risk"


def test_health_medium_weighted_half():
    pct, _ = portfolio_health(0, 4, 0)  # 1 - (0.5*4)/4 = 0.5 → 50%
    assert pct == 50


def test_health_zero_graded_guarded():
    pct, band = portfolio_health(0, 0, 0)  # max(1, graded) guard, no div-by-zero
    assert pct == 100 and band == "healthy"


# ── build_dashboard_metrics ─────────────────────────────────────────────────────
def test_empty_store():
    m = build_dashboard_metrics([], lambda p: None, today=date(2026, 1, 10))
    assert m.total_contracts == 0 and m.completed_contracts == 0
    assert m.risk_distribution.high == 0
    assert m.portfolio_health_pct == 100
    assert len(m.usage_timeline) == 30  # dense, all zero (N5)
    assert all(b.count == 0 for b in m.usage_timeline)
    assert m.risk_by_clause_type == [] and m.top_risky_clause_types == []


def test_risk_distribution_and_health():
    rows = [_row("j1", "2026-01-10T00:00:00+00:00"), _row("j2", "2026-01-10T00:00:00+00:00")]
    reports = {
        "j1": _rd(high=2, medium=1, low=0, findings=[
            {"clause_type": "liability", "risk_level": "high"},
            {"clause_type": "liability", "risk_level": "high"},
            {"clause_type": "payment", "risk_level": "medium"},
        ]),
        "j2": _rd(high=0, medium=0, low=3, findings=[
            {"clause_type": "term", "risk_level": "low"},
            {"clause_type": None, "risk_level": "low"},  # null clause_type → Uncategorized
            {"clause_type": "term", "risk_level": None},  # null risk → excluded from severity
        ]),
    }
    read = lambda path: reports.get(path.split("/")[-1].split(".")[0] if path else "")
    # map report_path → report by job id embedded; simpler: build rows with distinct paths
    rows[0].report_path = "/r/j1.md"
    rows[1].report_path = "/r/j2.md"
    read = lambda path: reports.get({"/r/j1.md": "j1", "/r/j2.md": "j2"}.get(path))

    m = build_dashboard_metrics(rows, read, today=date(2026, 1, 10))
    assert m.total_contracts == 2 and m.completed_contracts == 2
    assert (m.risk_distribution.high, m.risk_distribution.medium, m.risk_distribution.low) == (2, 1, 3)
    # by clause type includes an "Uncategorized" bucket (null clause_type)
    types = {c.clause_type for c in m.risk_by_clause_type}
    assert "Uncategorized" in types
    liability = next(c for c in m.risk_by_clause_type if c.clause_type == "liability")
    assert liability.high == 2
    # heatmap cols fixed; rows match the clause types present
    assert m.clause_risk_heatmap.cols == ["low", "medium", "high"]
    assert set(m.clause_risk_heatmap.rows) == types
    # top risky by high count
    assert m.top_risky_clause_types[0].clause_type == "liability"
    assert m.top_risky_clause_types[0].high_count == 2


def test_missing_report_and_failed_counted_not_risked():
    rows = [
        _row("done", "2026-01-10T00:00:00+00:00", report_path="/r/gone.md"),  # read→None
        _row("fail", "2026-01-10T00:00:00+00:00", status=JobState.failed, report_path=None),
    ]
    m = build_dashboard_metrics(rows, lambda p: None, today=date(2026, 1, 10))
    assert m.total_contracts == 2
    assert m.completed_contracts == 1  # only "done" is completed status
    assert m.risk_distribution.high == 0 and m.risk_distribution.low == 0  # nothing folded


def test_usage_timeline_dense_and_counts():
    rows = [
        _row("a", "2026-01-10T09:00:00+00:00"),
        _row("b", "2026-01-10T10:00:00+00:00"),
        _row("c", "2026-01-08T10:00:00+00:00"),
    ]
    m = build_dashboard_metrics(rows, lambda p: _rd(low=1), today=date(2026, 1, 10))
    assert len(m.usage_timeline) == 30
    assert m.usage_timeline[-1].period == "2026-01-10" and m.usage_timeline[-1].count == 2
    day08 = next(b for b in m.usage_timeline if b.period == "2026-01-08")
    assert day08.count == 1


# ── build_job_list ──────────────────────────────────────────────────────────────
def test_job_list_completed_vs_pending():
    rows = [
        _row("j1", "2026-01-10T00:00:00+00:00", finished_at="2026-01-10T00:05:00+00:00"),
        _row("j2", "2026-01-09T00:00:00+00:00", status=JobState.running, report_path=None),
    ]
    read = lambda path: _rd(high=1, medium=0, low=2) if path == "/r/x.md" else None
    jl = build_job_list(rows, read, limit=20, offset=0, total=2)
    assert jl.total == 2 and len(jl.items) == 2
    done = next(i for i in jl.items if i.job_id == "j1")
    assert done.report_available and done.high == 1 and done.low == 2 and done.risk_band == "high"
    pending = next(i for i in jl.items if i.job_id == "j2")
    assert pending.report_available is False and pending.risk_band is None and pending.high is None


def test_job_list_legacy_filename_fallback():
    r = _row("j1", "2026-01-10T00:00:00+00:00", original_filename=None)
    jl = build_job_list([r], lambda p: None, limit=20, offset=0, total=1)
    assert jl.items[0].original_filename == "j1.pdf"  # falls back to document_path basename
