"""
In-memory job registry and per-job record with thread-safe field mutation.

Threading discipline (review R1):
- JobRecord fields are mutated ONLY through mark_running, record_progress,
  mark_terminal — never by direct attribute writes from outside the record.
- Every mutation and to_status() projection acquires the record's own _lock.
- JobRegistry guards its OrderedDict with its own lock; record fields are
  a separate concern (record lock, not registry lock).
"""

import threading
from collections import OrderedDict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.runner.events import JobEventBuffer
from app.runner.models import ErrorInfo, JobState, JobStatus


def _coerce_status(mcp_delivery_status: Dict[str, Any]) -> Dict[str, Any]:
    """Normalize MCPDeliveryInfo status enums to .value strings for JSON serialization."""
    result = {}
    for channel, info in mcp_delivery_status.items():
        if isinstance(info, dict):
            coerced = dict(info)
            status_val = coerced.get("status")
            if status_val is not None and hasattr(status_val, "value"):
                coerced["status"] = status_val.value  # type: ignore[union-attr]
            result[channel] = coerced
        else:
            result[channel] = info
    return result


@dataclass
class JobRecord:
    job_id: str
    document_path: str
    submitted_at: str
    buffer: JobEventBuffer
    recipient: Optional[str] = None

    # Mutable fields — written only via lock methods
    _status: JobState = field(default=JobState.queued, init=False, repr=False)
    _started_at: Optional[str] = field(default=None, init=False, repr=False)
    _finished_at: Optional[str] = field(default=None, init=False, repr=False)
    _current_node: Optional[str] = field(default=None, init=False, repr=False)
    _completed_nodes: List[str] = field(default_factory=list, init=False, repr=False)
    _report_path: Optional[str] = field(default=None, init=False, repr=False)
    _mcp_delivery_status: Dict[str, Any] = field(
        default_factory=dict, init=False, repr=False
    )
    _error: Optional[ErrorInfo] = field(default=None, init=False, repr=False)
    _lock: threading.Lock = field(
        default_factory=threading.Lock, init=False, repr=False, compare=False
    )

    def mark_running(self, started_at: str) -> None:
        with self._lock:
            self._status = JobState.running
            self._started_at = started_at

    def record_progress(self, node: str) -> None:
        with self._lock:
            self._current_node = node
            self._completed_nodes.append(node)

    @property
    def report_path(self) -> Optional[str]:
        """Thread-safe accessor for the on-disk report path.

        Kept OFF the boundary JobStatus (spec §2.3 exposes report_available, not
        the server filesystem path); the /report handler resolves the file from
        this accessor alone (AC-13 — never a client-supplied path)."""
        with self._lock:
            return self._report_path

    def mark_terminal(
        self,
        *,
        status: JobState,
        finished_at: str,
        report_path: Optional[str],
        mcp_delivery_status: Optional[Dict[str, Any]] = None,
        error: Optional[ErrorInfo] = None,
    ) -> None:
        with self._lock:
            self._status = status
            self._finished_at = finished_at
            self._report_path = report_path
            self._mcp_delivery_status = mcp_delivery_status or {}
            self._error = error

    def to_status(self) -> JobStatus:
        """Project internal state to the boundary Pydantic type (under lock)."""
        with self._lock:
            completed_nodes = list(self._completed_nodes)
            report_path = self._report_path
            report_available = bool(report_path and Path(report_path).exists())
            return JobStatus(
                job_id=self.job_id,
                status=self._status,
                submitted_at=self.submitted_at,
                started_at=self._started_at,
                finished_at=self._finished_at,
                current_node=self._current_node,
                completed_nodes=completed_nodes,
                report_available=report_available,
                mcp_delivery_status=_coerce_status(self._mcp_delivery_status),
                error=self._error,
            )


class JobRegistry:
    def __init__(self, max_jobs: int) -> None:
        self._max_jobs = max_jobs
        self._records: OrderedDict = OrderedDict()
        self._lock = threading.Lock()

    def add(self, rec: JobRecord) -> None:
        with self._lock:
            self._records[rec.job_id] = rec
            if len(self._records) > self._max_jobs:
                # Evict oldest by insertion order
                self._records.popitem(last=False)

    def get(self, job_id: str) -> Optional[JobRecord]:
        with self._lock:
            return self._records.get(job_id)
