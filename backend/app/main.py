"""
Project Arya OS — FastAPI entrypoint.

Sprint 1 scope: app boots, connects to Postgres + Redis, exposes a health
check, and logs are structured. Everything else (agents, providers,
pipeline routes) attaches in later sprints without touching this file's
core shape.
"""
from contextlib import asynccontextmanager

import redis.asyncio as redis
from fastapi import FastAPI

from app.core.config import get_settings
from app.core.logging import configure_logging, get_logger
from app.api.routers import approvals, feature_flags, health, lineage, workflow_runs
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
    logger.info("shutdown")


app = FastAPI(
    title="Project Arya OS",
    description="Personal AI Content Factory — backend services",
    version="0.1.0",
    lifespan=lifespan,
)

# One FastAPI app, multiple routers — NOT separate microservices.
# Add future routers (agents, artifacts, quality-scores, ...) the same way.
app.include_router(approvals.router)
app.include_router(health.router)
app.include_router(feature_flags.router)
app.include_router(lineage.router)
app.include_router(workflow_runs.router)


@app.get("/")
async def root():
    return {"service": "arya-os", "status": "running", "sprint": 3}
