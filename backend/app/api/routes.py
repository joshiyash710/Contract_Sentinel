"""
FastAPI route handlers for the ContractSentinel runner/API layer.

Five endpoints:
  GET  /api/health
  POST /api/analyze
  GET  /api/jobs/{job_id}
  GET  /api/jobs/{job_id}/events
  GET  /api/jobs/{job_id}/report
"""

import asyncio
import os
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException, Request, UploadFile, Form
from fastapi.responses import FileResponse
from sse_starlette.sse import EventSourceResponse

import app.config as _cfg
from app.runner.events import JobEventBuffer
from app.runner.models import AnalyzeAccepted, JobState, JobStatus
from app.runner.registry import JobRecord, JobRegistry
from app.runner.worker import PipelineWorker

from datetime import datetime, timezone


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class RunnerContext:
    registry: JobRegistry
    worker: PipelineWorker
    loop: asyncio.AbstractEventLoop


def _get_ctx(request: Request) -> RunnerContext:
    return request.app.state.ctx


router = APIRouter(prefix="/api")


@router.get("/health")
async def health():
    return {"status": "ok"}


@router.post("/analyze", status_code=202)
async def analyze(
    request: Request,
    file: UploadFile,
    recipient: Optional[str] = Form(default=None),
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
        raise HTTPException(status_code=500, detail=str(exc)) from exc

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
    )
    ctx.registry.add(rec)
    ctx.worker.submit(job_id)

    return AnalyzeAccepted(
        job_id=job_id,
        status=JobState.queued,
        submitted_at=submitted_at,
    )


@router.get("/jobs/{job_id}", response_model=JobStatus)
async def get_job(job_id: str, request: Request) -> JobStatus:
    ctx: RunnerContext = _get_ctx(request)
    rec = ctx.registry.get(job_id)
    if rec is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return rec.to_status()


@router.get("/jobs/{job_id}/events")
async def get_job_events(job_id: str, request: Request):
    ctx: RunnerContext = _get_ctx(request)
    rec = ctx.registry.get(job_id)
    if rec is None:
        raise HTTPException(status_code=404, detail="Job not found")

    async def event_generator():
        backlog, q, closed = rec.buffer.subscribe()
        try:
            for ev in backlog:
                yield {"data": ev.model_dump_json()}
            if closed:
                return
            while True:
                if await request.is_disconnected():
                    break
                try:
                    ev = await asyncio.wait_for(q.get(), timeout=1.0)
                except asyncio.TimeoutError:
                    continue
                yield {"data": ev.model_dump_json()}
                if ev.event in ("completed", "failed"):
                    return
        finally:
            if q is not None:
                rec.buffer.unsubscribe(q)

    return EventSourceResponse(event_generator())


@router.get("/jobs/{job_id}/report")
async def get_job_report(job_id: str, request: Request, format: str = "md"):
    ctx: RunnerContext = _get_ctx(request)
    rec = ctx.registry.get(job_id)
    if rec is None:
        raise HTTPException(status_code=404, detail="Job not found")

    status = rec.to_status()
    if status.status != JobState.completed or not status.report_path:
        raise HTTPException(status_code=409, detail="Report not yet available")

    md_path = Path(status.report_path)

    if format == "json":
        target = md_path.with_suffix(".json")
        media_type = "application/json"
    else:
        target = md_path
        media_type = "text/markdown"

    if not target.exists():
        raise HTTPException(status_code=404, detail="Report file not found on disk")

    return FileResponse(str(target), media_type=media_type)
