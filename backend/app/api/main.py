"""
FastAPI application factory and lifespan for the ContractSentinel runner/API.

create_app() builds and returns a FastAPI app with:
  - Async lifespan: builds store/saver/registry/worker, UserStore, loads auth secret,
    runs startup recovery, stores RunnerContext + user_store on app.state.
  - CORSMiddleware with the configured localhost allowlist (spec D7).
  - Three routers: public (health), auth (unguarded), gated (require_auth dependency).

module-level 'app = create_app()' for uvicorn entry: uvicorn app.api.main:app
"""

import asyncio
from contextlib import asynccontextmanager

import uvicorn
from fastapi import Depends, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

import app.config as _cfg
from app.runner.migrations import upgrade_to_head
from app.runner.store import JobStore
from app.runner.persistence import build_saver, has_checkpoint
from app.runner.registry import JobRegistry
from app.runner.worker import PipelineWorker
from app.runner.models import JobState
from app.runner.user_store import UserStore
from app.api.security import bootstrap_secret
from app.api.auth import auth_router, require_auth
from app.api.routes import RunnerContext, router, public_router


def _recover(registry: JobRegistry, store: JobStore, saver, worker: PipelineWorker) -> None:
    """Idempotent startup recovery (spec AC-15, D6, D8).

    Enumerates nonterminal store rows once. Terminal jobs are never touched
    (spec AC-14). Orphan checkpoint threads with no job row are ignored (EC-6).
    """
    for row in store.nonterminal():
        rec = registry.get(row.job_id)
        resumable = (
            row.status == JobState.running
            and saver is not None
            and has_checkpoint(saver, row.job_id)
        )
        if not resumable:
            rec.reset_for_rerun()
        worker.submit(row.job_id, resume=resumable)


@asynccontextmanager
async def lifespan(application: FastAPI):
    """Startup: migrate DB, build store/saver/registry/worker, recover; Shutdown: tear down.

    Reads config at startup time (not import time) so monkeypatching config
    constants in tests affects the lifespan-created objects.
    """
    loop = asyncio.get_running_loop()
    bootstrap_secret()
    upgrade_to_head(_cfg.JOB_STORE_DB_PATH)
    store = JobStore(_cfg.JOB_STORE_DB_PATH)
    user_store = UserStore(_cfg.JOB_STORE_DB_PATH)
    saver = build_saver(_cfg.CHECKPOINTER_DB_PATH) if _cfg.CHECKPOINTER_ENABLED else None
    registry = JobRegistry(store, saver, loop, max_jobs=_cfg.JOB_STORE_RETENTION_MAX)
    worker = PipelineWorker(registry, saver=saver, concurrency=_cfg.RUNNER_WORKER_CONCURRENCY)
    worker.start()
    if _cfg.STARTUP_RECOVERY_ENABLED:
        _recover(registry, store, saver, worker)
    application.state.ctx = RunnerContext(registry=registry, worker=worker, loop=loop)
    application.state.user_store = user_store
    try:
        yield
    finally:
        worker.stop()
        store.close()
        user_store.close()
        if saver is not None:
            saver.conn.close()


def create_app() -> FastAPI:
    """Build and return a configured FastAPI application."""
    application = FastAPI(title="ContractSentinel API", lifespan=lifespan)

    @application.exception_handler(RequestValidationError)
    async def _validation_error_handler(request: Request, exc: RequestValidationError):
        # Strip 'input' from error details so user-supplied values (e.g. passwords)
        # are never echoed back in 422 responses (AC-7a / S3).
        # Also convert non-serializable ctx values (e.g. ValueError objects) to strings.
        errors = []
        for e in exc.errors():
            safe = {k: v for k, v in e.items() if k != "input"}
            if "ctx" in safe and isinstance(safe["ctx"], dict):
                safe["ctx"] = {ck: str(cv) for ck, cv in safe["ctx"].items()}
            errors.append(safe)
        return JSONResponse(status_code=422, content={"detail": errors})

    application.add_middleware(
        CORSMiddleware,
        allow_origins=list(_cfg.CORS_ALLOWED_ORIGINS),
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Router order: public (health) → auth (unguarded) → gated (require_auth on every route)
    application.include_router(public_router)
    application.include_router(auth_router)
    application.include_router(router, dependencies=[Depends(require_auth)])
    return application


app = create_app()


def run() -> None:
    uvicorn.run(app, host=_cfg.API_BIND_HOST, port=_cfg.API_BIND_PORT)
