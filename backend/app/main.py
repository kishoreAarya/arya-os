"""
Project Arya OS — FastAPI entrypoint.

Sprint 1 scope: app boots, connects to Postgres + Redis, exposes a health
check, and logs are structured. Everything else (agents, providers,
pipeline routes) attaches in later sprints without touching this file's
core shape.
"""
import uuid
from contextlib import asynccontextmanager

import redis.asyncio as redis
import structlog
from fastapi import Depends, FastAPI, HTTPException, Request, Response, status
from fastapi.exceptions import RequestValidationError
from fastapi.exception_handlers import (
    http_exception_handler,
    request_validation_exception_handler,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.config import get_settings
from app.core.logging import configure_logging, get_logger
from app.core.security import get_current_principal, verify_api_key
from app.api.routers import agents, analytics, approvals, creator, execution_bridge, feature_flags, health, learning, lineage, production, publishing, research, workflow_runs, workflows
from app.workers.scheduler import start_scheduler, stop_scheduler

settings = get_settings()
configure_logging()
logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    if (settings.app_env or "").lower() == "production":
        settings.validate_production_safety()

    logger.info("startup", app_name=settings.app_name, env=settings.app_env)
    app.state.redis = redis.from_url(settings.redis_url, decode_responses=True)
    start_scheduler()  # internal maintenance jobs only — n8n remains the pipeline orchestrator

    if settings.enable_workflow_auto_recovery:
        try:
            from app.database.session import AsyncSessionLocal
            from app.services.workflow_execution_service import auto_recover_stale_workflow_runs

            async with AsyncSessionLocal() as session:
                recovered = await auto_recover_stale_workflow_runs(session)
                if recovered:
                    logger.info("startup_auto_recovered_workflows", count=len(recovered), ids=[str(i) for i in recovered])
        except Exception as exc:
            logger.warning("startup_auto_recovery_failed", error=str(exc))

    yield

    from app.api.routers.workflow_runs import shutdown_background_workflow_tasks

    await shutdown_background_workflow_tasks(timeout=5.0)
    stop_scheduler()
    await app.state.redis.aclose()
    from app.database.session import engine

    await engine.dispose()
    logger.info("shutdown")


app = FastAPI(
    title="Project Arya OS",
    description="Personal AI Content Factory — backend services",
    version="0.1.0",
    lifespan=lifespan,
)

cors_origins = [o.strip() for o in settings.cors_allowed_origins if o.strip()]
has_wildcard = "*" in cors_origins
# Enforce security invariant: allow_credentials must NEVER be combined with wildcard origins
cors_allow_credentials = settings.cors_allow_credentials and not has_wildcard

app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=cors_allow_credentials,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def request_correlation_middleware(request: Request, call_next):
    request_id = (
        request.headers.get("x-request-id")
        or request.headers.get("x-correlation-id")
        or str(uuid.uuid4())
    )
    request.state.request_id = request_id
    structlog.contextvars.bind_contextvars(request_id=request_id)
    try:
        response: Response = await call_next(request)
        response.headers["x-request-id"] = request_id
        return response
    finally:
        structlog.contextvars.clear_contextvars()


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    if isinstance(exc, (HTTPException, StarletteHTTPException)):
        return await http_exception_handler(request, exc)
    if isinstance(exc, RequestValidationError):
        return await request_validation_exception_handler(request, exc)

    request_id = getattr(request.state, "request_id", None) or str(uuid.uuid4())
    logger.error(
        "unhandled_server_exception",
        error=str(exc),
        request_id=request_id,
        exc_info=True,
    )
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={
            "detail": "Internal Server Error",
            "request_id": request_id,
        },
        headers={"x-request-id": request_id},
    )


# One FastAPI app, multiple routers — NOT separate microservices.
# Sensitive routers protected by Bearer token authentication:
app.include_router(approvals.router, dependencies=[Depends(get_current_principal)])
app.include_router(feature_flags.router, dependencies=[Depends(get_current_principal)])
app.include_router(lineage.router, dependencies=[Depends(get_current_principal)])
app.include_router(workflow_runs.router, dependencies=[Depends(get_current_principal)])
app.include_router(agents.router, dependencies=[Depends(get_current_principal)])
app.include_router(workflows.router, dependencies=[Depends(get_current_principal)])
app.include_router(creator.router, dependencies=[Depends(get_current_principal)])
app.include_router(research.router, dependencies=[Depends(get_current_principal)])
app.include_router(publishing.router, dependencies=[Depends(get_current_principal)])
app.include_router(analytics.router, dependencies=[Depends(get_current_principal)])
app.include_router(learning.router, dependencies=[Depends(get_current_principal)])
app.include_router(production.router, dependencies=[Depends(get_current_principal)])
app.include_router(execution_bridge.router, dependencies=[Depends(get_current_principal)])

# Health router includes public probes (/health, /ready) and protected diagnostics (/providers, /database, /storage, /validators)
app.include_router(health.router)


@app.get("/")
async def root():
    return {"service": "arya-os", "status": "running", "sprint": 3}


import os
from fastapi.staticfiles import StaticFiles

_frontend_dist = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "frontend",
    "dist",
)
if os.path.exists(_frontend_dist):
    app.mount("/app", StaticFiles(directory=_frontend_dist, html=True), name="creator_app")
