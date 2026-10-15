"""Feature 066 — compact per-job risk summary (denormalized onto the jobs row to kill the dashboard N+1).

ONE shared `summarize_report` builds the summary from a parsed report `.json`; it feeds BOTH the write path
(stamped on the job row at completion, via `load_report_summary`) AND the read-path legacy fallback, so the
stored summary and a live report read cannot diverge (structural parity).

Neutral runner-level module: imports only `blob_store` (runner-safe) + stdlib — the runner can use it without
importing `app.api.*` or graph-node modules (preserves the 061 runner-isolation guard).
"""

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from app import blob_store

logger = logging.getLogger("contractsentinel.runner.risk_summary")

_UNCATEGORIZED = "Uncategorized"
_SEVERITIES = ("low", "medium", "high")


@dataclass
class RiskSummary:
    """Compact risk rollup for ONE completed report (what the dashboard/jobs endpoints need)."""

    high: int
    medium: int
    low: int
    validated_findings: int
    total_clauses: int
    analysis_degraded: bool
    # Per-clause-type severity counts: {clause_type: {"low","medium","high"}} — same labels the dashboard uses.
    risk_by_type: dict = field(default_factory=dict)


def summarize_report(report: dict) -> RiskSummary:
    """Pure: build a RiskSummary from a parsed report `.json` (`summary` + `findings` + `analysis_degraded`).

    `risk_by_type` is built from `findings` with the SAME rule the dashboard uses: null/unknown severities are
    excluded, a null clause_type buckets to 'Uncategorized'."""
    summary = report.get("summary") or {}
    by_type: dict = {}
    for f in report.get("findings") or []:
        sev = f.get("risk_level")
        if sev not in _SEVERITIES:  # null / unknown severity excluded (D14)
            continue
        ctype = f.get("clause_type") or _UNCATEGORIZED
        by_type.setdefault(ctype, {"low": 0, "medium": 0, "high": 0})[sev] += 1
    return RiskSummary(
        high=int(summary.get("high", 0)),
        medium=int(summary.get("medium", 0)),
        low=int(summary.get("low", 0)),
        validated_findings=int(summary.get("validated_findings", 0)),
        total_clauses=int(summary.get("total_clauses", 0)),
        analysis_degraded=bool(report.get("analysis_degraded", False)),
        risk_by_type=by_type,
    )


def load_report_summary(report_path: Optional[str]) -> Optional[RiskSummary]:
    """Best-effort: read the `.json` sibling of a report path and summarize it. None on unset/missing/malformed
    (logged, never raised). The single seam the write path AND the read-path fallback both use (parity)."""
    if not report_path:
        return None
    json_key = str(Path(report_path).with_suffix(".json"))
    try:
        if not blob_store.exists(json_key):  # feature 052: disk (default) or Turso BLOB
            return None
        data = json.loads(blob_store.read(json_key).decode("utf-8"))
        return summarize_report(data)
    except (OSError, ValueError, TypeError, blob_store.BlobNotFound) as exc:
        logger.warning("risk_summary: could not read report %s: %s", json_key, exc)
        return None


def to_row_fields(s: RiskSummary) -> dict:
    """RiskSummary → the JobRow risk-column values (python-native; the store serializes risk_by_type/bool)."""
    return {
        "risk_high": s.high,
        "risk_medium": s.medium,
        "risk_low": s.low,
        "validated_findings": s.validated_findings,
        "total_clauses": s.total_clauses,
        "analysis_degraded": s.analysis_degraded,
        "risk_by_type": s.risk_by_type,
    }


def from_row(row) -> Optional[RiskSummary]:
    """JobRow → RiskSummary, or None when the row has no stored summary (`risk_high` is None) or the
    `risk_by_type` is unparseable (EC-7 → fall back to the live read)."""
    if getattr(row, "risk_high", None) is None:
        return None
    rbt = getattr(row, "risk_by_type", None)
    if isinstance(rbt, str):
        try:
            rbt = json.loads(rbt)
        except (ValueError, TypeError):
            return None
    if not isinstance(rbt, dict):
        rbt = {}
    return RiskSummary(
        high=row.risk_high or 0,
        medium=row.risk_medium or 0,
        low=row.risk_low or 0,
        validated_findings=row.validated_findings or 0,
        total_clauses=row.total_clauses or 0,
        analysis_degraded=bool(row.analysis_degraded),
        risk_by_type=rbt,
    )
