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
