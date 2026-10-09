"""
Health Monitoring endpoints.

/health    — overall liveness (Postgres + Redis), same check main.py
             had before, moved here so it lives with its siblings.
/ready     — stricter readiness: liveness + storage backend reachable.
             Use this one for orchestrator/deploy readiness gates.
/providers — what the Provider Capability Registry knows, plus which
             providers currently have a secret configured.
/database  — Postgres connectivity + row counts for a couple of core
             tables, a fast sanity check without a DB console.
/validators — which validators are registered (VALIDATOR_REGISTRY).
/storage   — active storage backend + a round-trip write/read/delete
             smoke test.
"""
from fastapi import APIRouter, Depends, Request
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.logging import get_logger
from app.core.secrets import get_secrets_manager
from app.core.security import verify_api_key
from app.database.session import get_db
from app.models.core import WorkflowRun
from app.models.provider import Provider
from app.providers.capabilities import PROVIDER_CAPABILITIES
from app.storage import get_storage_provider
from app.validators import VALIDATOR_REGISTRY

logger = get_logger(__name__)

router = APIRouter(tags=["health"])


@router.get("/health")
async def health(request: Request, db: AsyncSession = Depends(get_db)):
    checks: dict[str, str] = {}
    try:
        await db.execute(text("SELECT 1"))
        checks["postgres"] = "ok"
    except Exception as exc:
        # Public endpoint: never echo internal exception details (DSNs,
        # hostnames, credentials). Full detail goes to server-side logs only.
        logger.warning("health_check_failed", component="postgres", error=str(exc))
        checks["postgres"] = "error"

    try:
        pong = await request.app.state.redis.ping()
        checks["redis"] = "ok" if pong else "error: no pong"
    except Exception as exc:
        logger.warning("health_check_failed", component="redis", error=str(exc))
        checks["redis"] = "error"

    overall = "healthy" if all(v == "ok" for v in checks.values()) else "degraded"
    return {"status": overall, "checks": checks}


@router.get("/ready")
async def ready(request: Request, db: AsyncSession = Depends(get_db)):
    liveness = await health(request, db)
    storage_ok = True
    try:
        storage = get_storage_provider()
        test_key = "_health/ready_check.txt"
        await storage.upload(test_key, b"ok")
        await storage.download(test_key)
        await storage.delete(test_key)
    except Exception as exc:
        # Public endpoint: generic error only; detail stays in server logs.
        logger.warning("health_check_failed", component="storage", error=str(exc))
        storage_ok = False

    ready_state = liveness["status"] == "healthy" and storage_ok
    return {
        "ready": ready_state,
        "liveness": liveness,
        "storage": "ok" if storage_ok else "error",
    }


@router.get("/providers", dependencies=[Depends(verify_api_key)])
async def providers_status(db: AsyncSession = Depends(get_db)):
    secrets = get_secrets_manager()
    db_providers = {p.name: p for p in (await db.execute(select(Provider))).scalars().all()}

    result = []
    for name, cap in PROVIDER_CAPABILITIES.items():
        has_secret = True
        if cap.secret_name:
            try:
                secrets.get(cap.secret_name, required=True)
            except Exception:
                has_secret = False
        db_row = db_providers.get(name)
        result.append(
            {
                "name": name,
                "capabilities": [c.value for c in cap.capabilities],
                "cost_tier": cap.cost_tier,
                "avg_latency_seconds": cap.avg_latency_seconds,
                "configured": has_secret,
                "active_in_db": db_row.is_active if db_row else None,
            }
        )
    return {"providers": result}


@router.get("/database", dependencies=[Depends(verify_api_key)])
async def database_status(db: AsyncSession = Depends(get_db)):
    try:
        run_count = (await db.execute(select(func.count()).select_from(WorkflowRun))).scalar_one()
        return {"status": "ok", "workflow_run_count": run_count}
    except Exception as exc:
        return {"status": f"error: {exc}"}


@router.get("/storage", dependencies=[Depends(verify_api_key)])
async def storage_status():
    settings = get_settings()
    try:
        storage = get_storage_provider()
        test_key = "_health/storage_check.txt"
        await storage.upload(test_key, b"ok")
        exists = await storage.exists(test_key)
        await storage.delete(test_key)
        return {"backend": settings.storage_backend, "status": "ok" if exists else "degraded"}
    except Exception as exc:
        return {"backend": settings.storage_backend, "status": f"error: {exc}"}


@router.get("/validators", dependencies=[Depends(verify_api_key)])
async def validators_status():
    return {"validators": list(VALIDATOR_REGISTRY.keys())}
