"""
In-memory job registry and per-job record with thread-safe field mutation.

Threading discipline (review R1):
- JobRecord fields are mutated ONLY through mark_running, record_progress,
  mark_terminal — never by direct attribute writes from outside the record.
- Every mutation and to_status() projection acquires the record's own _lock.
- JobRegistry guards its live dict with its own lock; record fields are
  a separate concern (record lock, not registry lock).

Feature 012 additions:
- JobRecord gains an optional _store handle and write-through persistence.
  _store=None keeps the record a pure in-memory object (011 behaviour, AC-7a).
- JobRegistry wraps a JobStore + live in-memory dict. get() rehydrates from the
  store on a miss (cross-restart GET, spec AC-2). add() prunes + deletes
  checkpoint threads to keep the two stores in sync (spec D5).
"""

import threading
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
    # Real uploaded filename (feature 018 / 001-alignment). Defaulted + placed after the
    # last defaulted init field (recipient) and before the field(init=False) block, so the
    # dataclass "no non-default after default" rule holds. Seeded by the analyze route.
    original_filename: Optional[str] = None
    # Owning account (feature 019 — per-user data isolation). Set once by the analyze route;
    # persisted with the row and never mutated. NULL = legacy/unowned.
    user_id: Optional[str] = None

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
    _store: Optional[Any] = field(
        default=None, init=False, repr=False, compare=False
    )

    # ── write-through helpers ──────────────────────────────────────────────────

    def _to_row(self) -> "JobRow":  # type: ignore[name-defined]
        from app.runner.store import JobRow

        return JobRow(
            job_id=self.job_id,
            document_path=self.document_path,
            recipient=self.recipient,
            original_filename=self.original_filename,
            user_id=self.user_id,
            status=self._status,
            submitted_at=self.submitted_at,
            started_at=self._started_at,
            finished_at=self._finished_at,
            current_node=self._current_node,
            completed_nodes=list(self._completed_nodes),
            report_path=self._report_path,
            mcp_delivery_status=dict(self._mcp_delivery_status),
            error=self._error,
        )

    def _persist(self) -> None:
        """Persist current state to the store. Caller must hold self._lock."""
        if self._store is not None:
            self._store.upsert(self._to_row())

    def _persist_initial(self) -> None:
        """INSERT the initial queued row. Caller does NOT hold the lock."""
        with self._lock:
            self._persist()

    # ── lock methods (011 API preserved) ──────────────────────────────────────

    def mark_running(self, started_at: str) -> None:
        with self._lock:
            self._status = JobState.running
            self._started_at = started_at
            self._persist()

    def record_progress(self, node: str) -> None:
        with self._lock:
            self._current_node = node
            self._completed_nodes.append(node)
            self._persist()

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
            self._persist()

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

    # ── feature 012 additions ─────────────────────────────────────────────────

    def reset_for_rerun(self) -> None:
        """Fresh re-run after restart with NO usable checkpoint (spec AC-12/13, EC-2).

        Clears progress so completed_nodes re-accumulates from zero.
        """
        with self._lock:
            self._status = JobState.queued
            self._started_at = None
            self._finished_at = None
            self._current_node = None
            self._completed_nodes = []
            self._error = None
            self._persist()

    def snapshot_completed_nodes(self) -> List[str]:
        """Lock-guarded copy for the resume dedup seed (spec EC-1)."""
        with self._lock:
            return list(self._completed_nodes)

    @classmethod
    def from_row(cls, row: "JobRow", *, buffer: JobEventBuffer, store: Any) -> "JobRecord":  # type: ignore[name-defined]
        """Rebuild a JobRecord from a durable JobRow (rehydration on miss, spec AC-2)."""
        from app.runner.store import JobRow as _JobRow  # noqa: F401

        rec = cls(
            job_id=row.job_id,
            document_path=row.document_path,
            submitted_at=row.submitted_at,
            buffer=buffer,
            recipient=row.recipient,
            original_filename=row.original_filename,
            user_id=row.user_id,
        )
        rec._status = row.status
        rec._started_at = row.started_at
        rec._finished_at = row.finished_at
        rec._current_node = row.current_node
        rec._completed_nodes = list(row.completed_nodes)
        rec._report_path = row.report_path
        rec._mcp_delivery_status = dict(row.mcp_delivery_status)
        rec._error = row.error
        rec._store = store
        return rec


class JobRegistry:
    def __init__(
        self,
        store: Any,
        saver: Any,
        loop: Any,
        max_jobs: int,
    ) -> None:
        self._store = store
        self._saver = saver
        self._loop = loop
        self._max = max_jobs
        self._lock = threading.Lock()
        self._live: Dict[str, JobRecord] = {}

    def add(self, rec: JobRecord) -> None:
        rec._store = self._store
        with self._lock:
            self._live[rec.job_id] = rec
        rec._persist_initial()  # INSERT the queued row durably (spec AC-1)

        if self._store is None:
            # In-memory-only mode (store=None): evict by insertion order (011 behaviour)
            with self._lock:
                while len(self._live) > self._max:
                    self._live.pop(next(iter(self._live)))
            return

        # First prune: delete oldest rows from the store (spec D5)
        victims = self._store.prune(self._max)

        # Evict from live dict and null out _store handles under each record's lock.
        # The lock-guarded null-out serializes with any ongoing _persist() call so
        # no write can sneak in AFTER this point for the evicted records.
        evicted_records = []
        with self._lock:
            for v in victims:
                evicted = self._live.pop(v, None)
                if evicted is not None:
                    evicted_records.append(evicted)
        for evicted in evicted_records:
            with evicted._lock:
                evicted._store = None  # stop future write-through

        # Second prune: catch any rows that were re-inserted by in-flight workers
        # between the first prune and the null-out above. After the null-out no
        # further writes can happen for the evicted records, so this is definitive.
        victims2 = self._store.prune(self._max)
        all_victims = list(set(victims) | set(victims2))

        for v in all_victims:
            if self._saver is not None:
                self._saver.delete_thread(v)

    def get(self, job_id: str) -> Optional[JobRecord]:
        with self._lock:
            rec = self._live.get(job_id)
        if rec is not None:
            return rec
        if self._store is None:
            return None
        row = self._store.get(job_id)
        if row is None:
            return None
        rec = JobRecord.from_row(
            row,
            buffer=JobEventBuffer(self._loop),
            store=self._store,
        )
        with self._lock:
            self._live.setdefault(job_id, rec)
        return rec

    # ── feature 018 read pass-throughs (durable store, not just the live dict) ──────

    def list_jobs(self, user_id: str, limit: int, offset: int):
        """Newest-first page of the owner's JobRows for GET /api/jobs (018 AC-1; scoped to
        user_id in feature 019 — AC-A2)."""
        if self._store is None:
            return []
        return self._store.list(user_id, limit, offset)

    def count(self, user_id: str) -> int:
        if self._store is None:
            return 0
        return self._store.count(user_id)

    def all_rows(self, user_id: str):
        """All of the owner's JobRows for dashboard aggregation (018 §2.3; scoped in 019 —
        AC-A5)."""
        if self._store is None:
            return []
        return self._store.all(user_id)
