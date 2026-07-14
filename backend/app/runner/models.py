"""
Boundary Pydantic models for the runner/API layer (constitution §4).

These types are validated at the HTTP/SSE boundary and never stored in graph state.
JobState is a runner concept distinct from ContractState's ValidationStatus /
MCPDeliveryStatus (specs/001-contract-state-schema.md).
"""

from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class JobState(str, Enum):
    queued = "queued"
    running = "running"
    completed = "completed"
    failed = "failed"


class ErrorInfo(BaseModel):
    kind: str
    message: str


class AnalyzeAccepted(BaseModel):
    job_id: str
    status: JobState
    submitted_at: str


class JobStatus(BaseModel):
    job_id: str
    status: JobState
    submitted_at: str
    started_at: Optional[str] = None
    finished_at: Optional[str] = None
    current_node: Optional[str] = None
    completed_nodes: List[str] = Field(default_factory=list)
    report_available: bool = False
    mcp_delivery_status: Dict[str, Any] = Field(default_factory=dict)
    error: Optional[ErrorInfo] = None


class ProgressEvent(BaseModel):
    event: str  # "progress" | "completed" | "failed"
    job_id: str
    node: Optional[str] = None
    index: Optional[int] = None
    total: Optional[int] = None
    elapsed_seconds: Optional[float] = None
    final: Optional[JobStatus] = None


# ── Dynamic dashboard boundary models (feature 018) ────────────────────────────
# Read-only aggregate/list surfaces. Pydantic (constitution §4); mirrored field-for-field
# in frontend types.ts. Built from the 012 job store + 009 report JSONs — never from
# internal ContractState.


class JobListItem(BaseModel):
    """One row of GET /api/jobs (spec §2.2). Risk fields are null for non-completed
    jobs (no report yet). risk_band is the 017-style derived band from the report's
    counts. report_available uses a disk-existence check on the report .json (D1/B-2)."""

    job_id: str
    original_filename: str
    status: JobState
    submitted_at: str
    finished_at: Optional[str] = None
    report_available: bool = False
    risk_band: Optional[str] = None  # "high" | "medium" | "low" | "none"
    high: Optional[int] = None
    medium: Optional[int] = None
    low: Optional[int] = None


class JobList(BaseModel):
    items: List[JobListItem]
    total: int


class RiskDistribution(BaseModel):
    high: int = 0
    medium: int = 0
    low: int = 0


class UsageBucket(BaseModel):
    period: str  # "YYYY-MM-DD" (UTC day)
    count: int


class ClauseTypeRisk(BaseModel):
    clause_type: str  # ClauseType.value, or "Uncategorized" for null (D14)
    high: int = 0
    medium: int = 0
    low: int = 0


class ClauseRiskHeatmap(BaseModel):
    rows: List[str] = Field(default_factory=list)  # clause_type labels
    cols: List[str] = Field(default_factory=lambda: ["low", "medium", "high"])
    cells: List[List[int]] = Field(default_factory=list)  # cells[r][c]


class TopClause(BaseModel):
    clause_type: str
    high_count: int


class DashboardMetrics(BaseModel):
    """GET /api/dashboard aggregate (spec §2.3). Every field grounded in real data."""

    total_contracts: int
    completed_contracts: int
    risk_distribution: RiskDistribution
    portfolio_health_pct: int  # DERIVED (D3), never a fabricated score
    portfolio_health_band: str  # "healthy" | "elevated" | "at_risk"
    usage_timeline: List[UsageBucket] = Field(default_factory=list)
    risk_by_clause_type: List[ClauseTypeRisk] = Field(default_factory=list)
    clause_risk_heatmap: ClauseRiskHeatmap = Field(default_factory=ClauseRiskHeatmap)
    top_risky_clause_types: List[TopClause] = Field(default_factory=list)
