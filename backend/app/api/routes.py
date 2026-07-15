"""
FastAPI route handlers for the ContractSentinel runner/API layer.

Public router (no auth):
  GET  /api/health

Gated router (require_auth dependency applied at include time in main.py):
  POST /api/analyze
  GET  /api/jobs
  GET  /api/dashboard
  GET  /api/jobs/{job_id}
  GET  /api/jobs/{job_id}/events
  GET  /api/jobs/{job_id}/report
"""

import asyncio
import logging
import os
import uuid
from dataclasses import dataclass
from pathlib import Path

_logger = logging.getLogger(__name__)
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile, Form
from fastapi.responses import FileResponse
from sse_starlette.sse import EventSourceResponse

import app.config as _cfg
from app.api.auth import AuthUser, require_auth
from app.api.aggregate import build_dashboard_metrics, build_job_list, read_report_data
from app.runner.events import JobEventBuffer
from app.runner.models import (
    AnalyzeAccepted,
    DashboardMetrics,
    JobList,
    JobState,
    JobStatus,
)
from app.runner.registry import JobRecord, JobRegistry
from app.runner.worker import PipelineWorker

from datetime import date, datetime, timezone


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class RunnerContext:
    registry: JobRegistry
    worker: PipelineWorker
    loop: asyncio.AbstractEventLoop


def _get_ctx(request: Request) -> RunnerContext:
    return request.app.state.ctx


def _owned_or_404(ctx: RunnerContext, job_id: str, current_user: AuthUser):
    """Fetch a job the caller owns, else raise 404 (feature 019 — AC-A3/A4/EC-1).

    A non-owned or legacy (NULL-owner) job is indistinguishable from a nonexistent one:
    both raise the SAME 404, so job-ids never leak across accounts. Must be called BEFORE
    any file is served / SSE stream is opened.
    """
    rec = ctx.registry.get(job_id)
    if rec is None or rec.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Job not found")
    return rec


public_router = APIRouter(prefix="/api")
router = APIRouter(prefix="/api")


@public_router.get("/health")
async def health():
    return {"status": "ok"}


@router.post("/analyze", status_code=202)
async def analyze(
    request: Request,
    file: UploadFile,
    recipient: Optional[str] = Form(default=None),
    current_user: AuthUser = Depends(require_auth),
) -> AnalyzeAccepted:
    ctx: RunnerContext = _get_ctx(request)

    # Validate extension
    ext = Path(file.filename or "").suffix.lower()
    if ext not in _cfg.ALLOWED_UPLOAD_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file extension {ext!r}. Allowed: {sorted(_cfg.ALLOWED_UPLOAD_EXTENSIONS)}",
        )

    # Ensure upload dir exists
    os.makedirs(_cfg.UPLOAD_DIR, exist_ok=True)

    job_id = str(uuid.uuid4())
    dest_path = os.path.join(_cfg.UPLOAD_DIR, f"{job_id}{ext}")

    # Stream-write file enforcing size limit
    total = 0
    try:
        with open(dest_path, "wb") as f:
            while True:
                chunk = await file.read(65536)
                if not chunk:
                    break
                total += len(chunk)
                if total > _cfg.MAX_UPLOAD_SIZE_BYTES:
                    f.close()
                    os.unlink(dest_path)
                    raise HTTPException(
                        status_code=413,
                        detail=f"File exceeds {_cfg.MAX_UPLOAD_SIZE_BYTES} bytes limit",
                    )
                f.write(chunk)
    except HTTPException:
        raise
    except Exception as exc:
        if os.path.exists(dest_path):
            os.unlink(dest_path)
        _logger.exception("Upload write failed")
        raise HTTPException(status_code=500, detail="Internal error saving upload") from exc

    if total == 0:
        os.unlink(dest_path)
        raise HTTPException(status_code=400, detail="Empty file upload rejected")

    submitted_at = _now_iso()
    buf = JobEventBuffer(ctx.loop)
    rec = JobRecord(
        job_id=job_id,
        document_path=dest_path,
        submitted_at=submitted_at,
        buffer=buf,
        recipient=recipient,
        # Persist the REAL uploaded name (feature 018 / 001-alignment); fall back to the
        # job-id-based name if the client didn't send a filename.
        original_filename=file.filename or f"{job_id}{ext}",
        # Stamp the owning account (feature 019 — AC-A1) so reads can be scoped to it.
        user_id=current_user.id,
    )
    ctx.registry.add(rec)
    ctx.worker.submit(job_id)

    return AnalyzeAccepted(
        job_id=job_id,
        status=JobState.queued,
        submitted_at=submitted_at,
    )


def _utc_today() -> date:
    return datetime.now(timezone.utc).date()


@router.get("/jobs", response_model=JobList)
async def list_jobs(
    request: Request,
    limit: int = _cfg.JOBS_LIST_DEFAULT_LIMIT,
    offset: int = 0,
    current_user: AuthUser = Depends(require_auth),
) -> JobList:
    # NOTE: coexists with GET /jobs/{job_id} below — different segment counts, no shadowing.
    limit = max(1, min(limit, _cfg.JOBS_LIST_MAX_LIMIT))  # EC-6 clamp
    offset = max(0, offset)
    reg = _get_ctx(request).registry
    return build_job_list(
        reg.list_jobs(current_user.id, limit, offset),
        read_report_data,
        limit,
        offset,
        reg.count(current_user.id),
    )


@router.get("/dashboard", response_model=DashboardMetrics)
async def dashboard(
    request: Request,
    current_user: AuthUser = Depends(require_auth),
) -> DashboardMetrics:
    reg = _get_ctx(request).registry
    return build_dashboard_metrics(
        reg.all_rows(current_user.id), read_report_data, today=_utc_today()
    )


@router.get("/jobs/{job_id}", response_model=JobStatus)
async def get_job(
    job_id: str,
    request: Request,
    current_user: AuthUser = Depends(require_auth),
) -> JobStatus:
    ctx: RunnerContext = _get_ctx(request)
    rec = _owned_or_404(ctx, job_id, current_user)
    return rec.to_status()


@router.get("/jobs/{job_id}/events")
async def get_job_events(
    job_id: str,
    request: Request,
    current_user: AuthUser = Depends(require_auth),
):
    ctx: RunnerContext = _get_ctx(request)
    rec = _owned_or_404(ctx, job_id, current_user)

    async def event_generator():
        backlog, q, closed = rec.buffer.subscribe()
        try:
            for ev in backlog:
                yield {"event": ev.event, "data": ev.model_dump_json()}
            if closed:
                return
            while True:
                if await request.is_disconnected():
                    break
                try:
                    ev = await asyncio.wait_for(q.get(), timeout=1.0)
                except asyncio.TimeoutError:
                    continue
                yield {"event": ev.event, "data": ev.model_dump_json()}
                if ev.event in ("completed", "failed"):
                    return
        finally:
            if q is not None:
                rec.buffer.unsubscribe(q)

    return EventSourceResponse(event_generator())


@router.get("/jobs/{job_id}/report")
async def get_job_report(
    job_id: str,
    request: Request,
    format: str = "md",
    current_user: AuthUser = Depends(require_auth),
):
    ctx: RunnerContext = _get_ctx(request)
    rec = _owned_or_404(ctx, job_id, current_user)

    # report_path is intentionally NOT on the boundary JobStatus (spec §2.3);
    # resolve it from the record's thread-safe accessor alone (AC-13).
    report_path = rec.report_path
    if rec.to_status().status != JobState.completed or not report_path:
        raise HTTPException(status_code=409, detail="Report not yet available")

    md_path = Path(report_path)

    if format == "json":
        target = md_path.with_suffix(".json")
        media_type = "application/json"
    else:
        target = md_path
        media_type = "text/markdown"

    if not target.exists():
        raise HTTPException(status_code=404, detail="Report file not found on disk")

    return FileResponse(str(target), media_type=media_type)
