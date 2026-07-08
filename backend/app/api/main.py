"""
FastAPI application factory and lifespan for the ContractSentinel runner/API.

create_app() builds and returns a FastAPI app with:
  - Async lifespan: starts/stops the PipelineWorker, captures the event loop,
    stores RunnerContext on app.state.ctx.
  - CORSMiddleware with the configured localhost allowlist (spec D7).
  - The /api router from routes.py.

module-level 'app = create_app()' for uvicorn entry: uvicorn app.api.main:app
"""

import asyncio
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

import app.config as _cfg
from app.runner.registry import JobRegistry
from app.runner.worker import PipelineWorker
from app.api.routes import RunnerContext, router


@asynccontextmanager
async def lifespan(application: FastAPI):
    """Startup: capture loop, build registry + worker; Shutdown: drain worker.

    Reads config at startup time (not import time) so monkeypatching config
    constants in tests affects the lifespan-created objects.
    """
    loop = asyncio.get_running_loop()
    registry = JobRegistry(max_jobs=_cfg.JOB_REGISTRY_MAX)
    worker = PipelineWorker(registry, concurrency=_cfg.RUNNER_WORKER_CONCURRENCY)
    worker.start()
    application.state.ctx = RunnerContext(registry=registry, worker=worker, loop=loop)
    try:
        yield
    finally:
        worker.stop()


def create_app() -> FastAPI:
    """Build and return a configured FastAPI application."""
    application = FastAPI(title="ContractSentinel API", lifespan=lifespan)

    application.add_middleware(
        CORSMiddleware,
        allow_origins=list(_cfg.CORS_ALLOWED_ORIGINS),
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    application.include_router(router)
    return application


app = create_app()


def run() -> None:
    uvicorn.run(app, host=_cfg.API_BIND_HOST, port=_cfg.API_BIND_PORT)
