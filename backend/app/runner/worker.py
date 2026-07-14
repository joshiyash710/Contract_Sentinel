"""
Background worker — drives run_pipeline on daemon threads.

Threading discipline (review R1): all JobRecord mutations go through the record's
own lock methods (mark_running, record_progress, mark_terminal). Direct attribute
writes to a JobRecord are forbidden here.

Deterministic shutdown (review T1): stop() sets the stop event, enqueues one
sentinel per thread, then joins each thread. This guarantees no worker is still
mid-run (and publishing via loop.call_soon_threadsafe) after lifespan returns.
Daemon threads still prevent a hard hang if a run genuinely wedges past the timeout.

Feature 012 additions:
- PipelineWorker accepts saver= (shared SqliteSaver, may be None).
- submit() accepts resume=False flag; queue item is now a (job_id, resume) tuple.
- _run_one unpacks the tuple, picks up already_completed on resume, and threads
  checkpointer/thread_id/resume/already_completed into run_pipeline.
"""

import logging
import queue
import threading
from datetime import datetime, timezone
from typing import Optional

from app.runner.core import run_pipeline, NodeProgress
from app.runner.models import ErrorInfo, JobState, ProgressEvent
from app.runner.registry import JobRecord, JobRegistry

logger = logging.getLogger(__name__)

_SENTINEL = object()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class PipelineWorker:
    def __init__(self, registry: JobRegistry, saver=None, concurrency: int = 1) -> None:
        self._registry = registry
        self._saver = saver
        self._concurrency = concurrency
        self._queue: queue.Queue = queue.Queue()
        self._stop_event = threading.Event()
        self._threads: list = []

    def start(self) -> None:
        for _ in range(self._concurrency):
            t = threading.Thread(target=self._loop, daemon=True)
            t.start()
            self._threads.append(t)

    def submit(self, job_id: str, resume: bool = False) -> None:
        self._queue.put((job_id, resume))

    def stop(self, join_timeout: float = 5.0) -> None:
        self._stop_event.set()
        for _ in self._threads:
            self._queue.put(_SENTINEL)
        for t in self._threads:
            t.join(timeout=join_timeout)

    def _loop(self) -> None:
        while not self._stop_event.is_set():
            item = self._queue.get()
            if item is _SENTINEL:
                break
            self._run_one(item)

    def _run_one(self, item) -> None:
        job_id, resume = item
        rec: Optional[JobRecord] = self._registry.get(job_id)
        if rec is None:
            return

        if not resume:
            rec.mark_running(_now_iso())
            already = None
        else:
            rec.mark_running(rec._started_at or _now_iso())
            already = rec.snapshot_completed_nodes()

        def _on_progress(p: NodeProgress) -> None:
            rec.record_progress(p.node)
            rec.buffer.publish(
                ProgressEvent(
                    event="progress",
                    job_id=job_id,
                    node=p.node,
                    index=p.index,
                    total=p.total,
                    elapsed_seconds=p.elapsed_seconds,
                )
            )

        try:
            result = run_pipeline(
                rec.document_path,
                recipient=rec.recipient,
                original_filename=rec.original_filename,
                on_progress=_on_progress,
                checkpointer=self._saver,
                thread_id=job_id,
                resume=resume,
                already_completed=already,
            )

            error: Optional[ErrorInfo] = None
            if result.ingest_error:
                msg = result.ingest_error.get("message", str(result.ingest_error))
                error = ErrorInfo(kind="ingest_error", message=msg)

            rec.mark_terminal(
                status=JobState.completed,
                finished_at=_now_iso(),
                report_path=result.report_path,
                mcp_delivery_status=result.mcp_delivery_status,
                error=error,
            )
            rec.buffer.publish(
                ProgressEvent(
                    event="completed",
                    job_id=job_id,
                    final=rec.to_status(),
                )
            )

        except Exception as exc:
            logger.exception("Pipeline run failed for job %s", job_id)
            rec.mark_terminal(
                status=JobState.failed,
                finished_at=_now_iso(),
                report_path=None,
                error=ErrorInfo(kind="runner_exception", message=str(exc)),
            )
            rec.buffer.publish(
                ProgressEvent(
                    event="failed",
                    job_id=job_id,
                    final=rec.to_status(),
                )
            )
