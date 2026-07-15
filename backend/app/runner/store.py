"""
Synchronous SQLite job store (spec D2, §2.2).

Schema is owned by Alembic — this class assumes `alembic upgrade head` has
already run and only reads/writes rows. Every method that touches the connection
executes under a threading.Lock (spec EC-5) so the worker thread and the asyncio
loop can share one instance safely.
"""

import json
import sqlite3
import threading
from dataclasses import dataclass
from typing import List, Optional

from app.runner.models import ErrorInfo, JobState

_TERMINAL = (JobState.completed, JobState.failed)


@dataclass
class JobRow:
    """Durable projection of JobRecord (spec §2.2).

    List / dict / ErrorInfo fields are JSON-encoded in SQLite and decoded here.
    """

    job_id: str
    document_path: str
    recipient: Optional[str]
    status: JobState
    submitted_at: str
    started_at: Optional[str]
    finished_at: Optional[str]
    current_node: Optional[str]
    completed_nodes: list
    report_path: Optional[str]
    mcp_delivery_status: dict
    error: Optional[ErrorInfo]
    # Appended LAST (feature 018, then 019). Keep this ordering identical in _encode(), the
    # INSERT column list/VALUES, and _decode() — the encode tuple is positional (plan §3.2).
    original_filename: Optional[str] = None
    # Owning account (feature 019 — per-user data isolation). NULL = legacy/unowned row,
    # hidden from every scoped read. Set once at create; never mutated.
    user_id: Optional[str] = None


class JobStore:
    """Thread-safe synchronous SQLite job store.

    One shared sqlite3 connection with check_same_thread=False, guarded by a
    lock, because the background worker thread write-through-persists while the
    asyncio loop GETs (spec EC-5).
    """

    def __init__(self, db_path: str) -> None:
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row

    def upsert(self, row: JobRow) -> None:
        with self._lock:
            self._conn.execute(
                """INSERT INTO jobs (job_id, document_path, recipient, status,
                       submitted_at, started_at, finished_at, current_node,
                       completed_nodes, report_path, mcp_delivery_status, error,
                       original_filename, user_id)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(job_id) DO UPDATE SET
                       status=excluded.status,
                       started_at=excluded.started_at,
                       finished_at=excluded.finished_at,
                       current_node=excluded.current_node,
                       completed_nodes=excluded.completed_nodes,
                       report_path=excluded.report_path,
                       mcp_delivery_status=excluded.mcp_delivery_status,
                       error=excluded.error,
                       original_filename=excluded.original_filename""",
                self._encode(row),
            )
            self._conn.commit()

    def get(self, job_id: str) -> Optional[JobRow]:
        with self._lock:
            cur = self._conn.execute("SELECT * FROM jobs WHERE job_id=?", (job_id,))
            r = cur.fetchone()
        return self._decode(r) if r else None

    def nonterminal(self) -> List[JobRow]:
        """Rows in queued/running — the recovery candidates (spec D6)."""
        with self._lock:
            cur = self._conn.execute(
                "SELECT * FROM jobs WHERE status IN (?,?) ORDER BY submitted_at",
                (JobState.queued.value, JobState.running.value),
            )
            rows = cur.fetchall()
        return [self._decode(r) for r in rows]

    def list(self, user_id: str, limit: int, offset: int) -> List[JobRow]:
        """Newest-first page of the owner's jobs for GET /api/jobs (feature 018; scoped to
        user_id in feature 019 — AC-A2). NULL-owner (legacy) rows are excluded."""
        with self._lock:
            cur = self._conn.execute(
                "SELECT * FROM jobs WHERE user_id=? ORDER BY submitted_at DESC LIMIT ? OFFSET ?",
                (user_id, limit, offset),
            )
            rows = cur.fetchall()
        return [self._decode(r) for r in rows]

    def count(self, user_id: str) -> int:
        """The owner's job count (feature 018 total_contracts; scoped in 019 — AC-A2)."""
        with self._lock:
            cur = self._conn.execute(
                "SELECT COUNT(*) AS n FROM jobs WHERE user_id=?", (user_id,)
            )
            return int(cur.fetchone()["n"])

    def all(self, user_id: str) -> List[JobRow]:
        """All of the owner's jobs newest-first for dashboard aggregation (feature 018;
        scoped in 019 — AC-A5). Bounded by the insert-time retention cap
        (JOB_STORE_RETENTION_MAX). NULL-owner (legacy) rows are excluded."""
        with self._lock:
            cur = self._conn.execute(
                "SELECT * FROM jobs WHERE user_id=? ORDER BY submitted_at DESC", (user_id,)
            )
            rows = cur.fetchall()
        return [self._decode(r) for r in rows]

    def prune(self, keep_max: int) -> List[str]:
        """Delete rows beyond keep_max oldest-first by submitted_at.

        Returns the pruned job_ids so the caller can delete their checkpoint
        threads (spec D5).
        """
        with self._lock:
            cur = self._conn.execute(
                "SELECT job_id FROM jobs ORDER BY submitted_at DESC LIMIT -1 OFFSET ?",
                (keep_max,),
            )
            victims = [r["job_id"] for r in cur.fetchall()]
            if victims:
                self._conn.executemany(
                    "DELETE FROM jobs WHERE job_id=?", [(v,) for v in victims]
                )
                self._conn.commit()
        return victims

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    # ── private encoding/decoding ──────────────────────────────────────────────

    def _encode(self, row: JobRow) -> tuple:
        error_json: Optional[str] = None
        if row.error is not None:
            error_json = json.dumps({"kind": row.error.kind, "message": row.error.message})
        return (
            row.job_id,
            row.document_path,
            row.recipient,
            row.status.value if isinstance(row.status, JobState) else row.status,
            row.submitted_at,
            row.started_at,
            row.finished_at,
            row.current_node,
            json.dumps(row.completed_nodes),
            row.report_path,
            json.dumps(row.mcp_delivery_status),
            error_json,
            row.original_filename,
            row.user_id,
        )

    def _decode(self, r: sqlite3.Row) -> JobRow:
        error: Optional[ErrorInfo] = None
        if r["error"] is not None:
            raw = json.loads(r["error"])
            error = ErrorInfo(kind=raw["kind"], message=raw["message"])
        return JobRow(
            job_id=r["job_id"],
            document_path=r["document_path"],
            recipient=r["recipient"],
            status=JobState(r["status"]),
            submitted_at=r["submitted_at"],
            started_at=r["started_at"],
            finished_at=r["finished_at"],
            current_node=r["current_node"],
            completed_nodes=json.loads(r["completed_nodes"]),
            report_path=r["report_path"],
            mcp_delivery_status=json.loads(r["mcp_delivery_status"]),
            error=error,
            original_filename=(
                r["original_filename"] if "original_filename" in r.keys() else None
            ),
            user_id=(r["user_id"] if "user_id" in r.keys() else None),
        )
