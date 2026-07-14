"""
Pure aggregation for the dynamic-dashboard endpoints (feature 018).

`build_job_list` / `build_dashboard_metrics` take a list of `JobRow` plus an injected
`read` callable (JobRow.report_path -> ReportData | None), so they are pure and unit-
testable with no filesystem. The route layer wires `read = read_report_data` (which reads
the 009 report `.json` on demand) and `rows` from the durable store.

Grounded per spec 018 §2.3–2.4: derived health (D3, no fabricated score), clause-type not
contract-type (D4/D5), null→"Uncategorized" (D14), dense day-buckets (D7/N5).
"""

import json
import logging
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Callable, List, Optional

import app.config as _cfg
from app.runner.models import (
    ClauseRiskHeatmap,
    ClauseTypeRisk,
    DashboardMetrics,
    JobList,
    JobListItem,
    JobState,
    RiskDistribution,
    TopClause,
    UsageBucket,
)
from app.runner.store import JobRow

logger = logging.getLogger("contractsentinel.dashboard")

_UNCATEGORIZED = "Uncategorized"
_SEVERITIES = ("low", "medium", "high")


@dataclass
class ReportData:
    """The slice of a 009 ContractReport the dashboard needs."""

    high: int
    medium: int
    low: int
    total_clauses: int
    validated_findings: int
    findings: List[dict] = field(default_factory=list)  # [{clause_type, risk_level}]


ReadFn = Callable[[Optional[str]], Optional[ReportData]]


def read_report_data(report_path: Optional[str]) -> Optional[ReportData]:
    """Read the `.json` sibling of a report `.md` path (same resolution as the 011 report
    handler). Returns None if the path is unset, the file is missing, or it is malformed
    (EC-3/EC-10) — logged, never raised."""
    if not report_path:
        return None
    json_path = Path(report_path).with_suffix(".json")
    try:
        if not json_path.exists():
            return None
        data = json.loads(json_path.read_text(encoding="utf-8"))
        summary = data.get("summary") or {}
        return ReportData(
            high=int(summary.get("high", 0)),
            medium=int(summary.get("medium", 0)),
            low=int(summary.get("low", 0)),
            total_clauses=int(summary.get("total_clauses", 0)),
            validated_findings=int(summary.get("validated_findings", 0)),
            findings=list(data.get("findings") or []),
        )
    except (OSError, ValueError, TypeError) as exc:
        logger.warning("dashboard: could not read report %s: %s", json_path, exc)
        return None


def derive_band(high: int, medium: int, low: int, validated: int) -> str:
    """017-style band (matches frontend deriveRiskBand). `low` is unused by the rule but
    kept for signature symmetry with the counts."""
    if high > 0:
        return "high"
    if medium > 0:
        return "medium"
    if validated > 0:
        return "low"
    return "none"


def portfolio_health(high: int, medium: int, low: int) -> tuple[int, str]:
    """Derived portfolio health (D3): 100·(1 − (high + W·medium)/max(1, graded))."""
    graded = high + medium + low
    penalty = (high + _cfg.PORTFOLIO_HEALTH_MEDIUM_WEIGHT * medium) / max(1, graded)
    pct = round(100 * (1 - penalty))
    pct = max(0, min(100, pct))
    if pct >= _cfg.PORTFOLIO_HEALTH_BAND_HEALTHY:
        band = "healthy"
    elif pct >= _cfg.PORTFOLIO_HEALTH_BAND_ELEVATED:
        band = "elevated"
    else:
        band = "at_risk"
    return pct, band


def _is_completed(row: JobRow) -> bool:
    return row.status == JobState.completed


def _display_name(row: JobRow) -> str:
    """Real filename, falling back to the document-path basename for legacy rows (EC-7)."""
    return row.original_filename or Path(row.document_path).name


def build_job_list(
    rows: List[JobRow], read: ReadFn, limit: int, offset: int, total: int
) -> JobList:
    """Map an already-paginated `rows` slice into JobListItems (spec §2.2). `limit`/`offset`
    are accepted for symmetry but the caller has already paged; `total` is the store count."""
    items: List[JobListItem] = []
    for row in rows:
        item = JobListItem(
            job_id=row.job_id,
            original_filename=_display_name(row),
            status=row.status,
            submitted_at=row.submitted_at,
            finished_at=row.finished_at,
            report_available=False,
        )
        if _is_completed(row):
            rd = read(row.report_path)
            if rd is not None:
                item.report_available = True
                item.high, item.medium, item.low = rd.high, rd.medium, rd.low
                item.risk_band = derive_band(rd.high, rd.medium, rd.low, rd.validated_findings)
        items.append(item)
    return JobList(items=items, total=total)


def _day(submitted_at: str) -> str:
    """UTC calendar day of an ISO submitted_at ('YYYY-MM-DD' prefix is sufficient)."""
    return (submitted_at or "")[:10]


def build_dashboard_metrics(
    rows: List[JobRow], read: ReadFn, *, today: date
) -> DashboardMetrics:
    total_contracts = len(rows)
    completed_rows = [r for r in rows if _is_completed(r)]

    # Fold each completed report's risk (skip missing/malformed — EC-3).
    reports: List[ReportData] = []
    for r in completed_rows:
        rd = read(r.report_path)
        if rd is not None:
            reports.append(rd)

    high = sum(r.high for r in reports)
    medium = sum(r.medium for r in reports)
    low = sum(r.low for r in reports)
    pct, band = portfolio_health(high, medium, low)

    # Per-clause-type severity counts (D4/D5/D14).
    by_type: dict = defaultdict(lambda: {"low": 0, "medium": 0, "high": 0})
    for rd in reports:
        for f in rd.findings:
            sev = f.get("risk_level")
            if sev not in _SEVERITIES:  # null / unknown severity excluded (D14)
                continue
            ctype = f.get("clause_type") or _UNCATEGORIZED
            by_type[ctype][sev] += 1

    ordered_types = sorted(by_type.keys())
    risk_by_clause_type = [
        ClauseTypeRisk(clause_type=t, low=by_type[t]["low"],
                       medium=by_type[t]["medium"], high=by_type[t]["high"])
        for t in ordered_types
    ]
    heatmap = ClauseRiskHeatmap(
        rows=ordered_types,
        cols=list(_SEVERITIES),
        cells=[[by_type[t][s] for s in _SEVERITIES] for t in ordered_types],
    )
    top = sorted(
        ((t, by_type[t]["high"]) for t in ordered_types if by_type[t]["high"] > 0),
        key=lambda kv: kv[1], reverse=True,
    )[:5]
    top_risky = [TopClause(clause_type=t, high_count=n) for t, n in top]

    # Dense usage timeline (D7/N5): all USAGE_TIMELINE_DAYS days, zero-filled.
    counts: dict = defaultdict(int)
    for r in rows:
        counts[_day(r.submitted_at)] += 1
    days = _cfg.USAGE_TIMELINE_DAYS
    usage_timeline = []
    for i in range(days - 1, -1, -1):
        d = (today - timedelta(days=i)).isoformat()
        usage_timeline.append(UsageBucket(period=d, count=counts.get(d, 0)))

    return DashboardMetrics(
        total_contracts=total_contracts,
        completed_contracts=len(completed_rows),
        risk_distribution=RiskDistribution(high=high, medium=medium, low=low),
        portfolio_health_pct=pct,
        portfolio_health_band=band,
        usage_timeline=usage_timeline,
        risk_by_clause_type=risk_by_clause_type,
        clause_risk_heatmap=heatmap,
        top_risky_clause_types=top_risky,
    )
