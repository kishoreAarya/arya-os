"""
Project Arya OS — FastAPI entrypoint.

Sprint 1 scope: app boots, connects to Postgres + Redis, exposes a health
check, and logs are structured. Everything else (agents, providers,
pipeline routes) attaches in later sprints without touching this file's
core shape.
"""
from contextlib import asynccontextmanager

import redis.asyncio as redis
from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import get_settings
from app.core.logging import configure_logging, get_logger
from app.core.security import verify_api_key
from app.api.routers import agents, analytics, approvals, creator, feature_flags, health, hermes_jobs, lineage, publishing, research, workflow_runs, workflows
from app.workers.scheduler import start_scheduler, stop_scheduler

settings = get_settings()
configure_logging()
logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("startup", app_name=settings.app_name, env=settings.app_env)
    app.state.redis = redis.from_url(settings.redis_url, decode_responses=True)
    start_scheduler()  # internal maintenance jobs only — n8n remains the pipeline orchestrator
    yield
    stop_scheduler()
    await app.state.redis.aclose()
    from app.database.session import engine
    await engine.dispose()
    logger.info("shutdown")


# API docs/OpenAPI schema are dev/test conveniences; an anonymous caller
# must not be able to enumerate the full route/schema surface in production.
_is_production = (settings.app_env or "").lower() == "production"

app = FastAPI(
    title="Project Arya OS",
    description="Personal AI Content Factory — backend services",
    version="0.1.0",
    lifespan=lifespan,
    docs_url=None if _is_production else "/docs",
    redoc_url=None if _is_production else "/redoc",
    openapi_url=None if _is_production else "/openapi.json",
)

# CORS: explicit origin allowlist only — no wildcard origins. Auth is a
# Bearer header (no cookie sessions), so credentials are not exposed to
# any origin. The Vite dev proxy and the backend's own static mount are
# same-origin and unaffected.
_cors_allowed_origins = [o.strip() for o in settings.cors_origins.split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_allowed_origins,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# One FastAPI app, multiple routers — NOT separate microservices.
# Sensitive routers protected by Bearer token authentication:
app.include_router(approvals.router, dependencies=[Depends(verify_api_key)])
app.include_router(feature_flags.router, dependencies=[Depends(verify_api_key)])
app.include_router(lineage.router, dependencies=[Depends(verify_api_key)])
app.include_router(workflow_runs.router, dependencies=[Depends(verify_api_key)])
app.include_router(agents.router, dependencies=[Depends(verify_api_key)])
app.include_router(workflows.router, dependencies=[Depends(verify_api_key)])
app.include_router(creator.router, dependencies=[Depends(verify_api_key)])
app.include_router(research.router, dependencies=[Depends(verify_api_key)])
app.include_router(publishing.router, dependencies=[Depends(verify_api_key)])
app.include_router(analytics.router, dependencies=[Depends(verify_api_key)])
app.include_router(hermes_jobs.router, dependencies=[Depends(verify_api_key)])

# Health router includes public probes (/health, /ready) and protected diagnostics (/providers, /database, /storage, /validators)
app.include_router(health.router)


@app.get("/")
async def root():
    return {"service": "arya-os", "status": "running", "sprint": 3}


import os  # noqa: E402 — grouped with the static-mount section that uses it
from fastapi.staticfiles import StaticFiles  # noqa: E402

_frontend_dist = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "frontend",
    "dist",
)
if os.path.exists(_frontend_dist):
    app.mount("/app", StaticFiles(directory=_frontend_dist, html=True), name="creator_app")
