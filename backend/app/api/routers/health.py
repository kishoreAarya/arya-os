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
from app.core.secrets import get_secrets_manager
from app.database.session import get_db
from app.models.core import WorkflowRun
from app.models.provider import Provider
from app.providers.capabilities import PROVIDER_CAPABILITIES
from app.storage import get_storage_provider
from app.validators import VALIDATOR_REGISTRY

router = APIRouter(tags=["health"])


@router.get("/health")
async def health(request: Request, db: AsyncSession = Depends(get_db)):
    checks: dict[str, str] = {}
    try:
        await db.execute(text("SELECT 1"))
        checks["postgres"] = "ok"
    except Exception as exc:  # noqa: BLE001
        checks["postgres"] = f"error: {exc}"

    try:
        pong = await request.app.state.redis.ping()
        checks["redis"] = "ok" if pong else "error: no pong"
    except Exception as exc:  # noqa: BLE001
        checks["redis"] = f"error: {exc}"

    overall = "healthy" if all(v == "ok" for v in checks.values()) else "degraded"
    return {"status": overall, "checks": checks}


@router.get("/ready")
async def ready(request: Request, db: AsyncSession = Depends(get_db)):
    liveness = await health(request, db)
    storage_ok = True
    storage_error = None
    try:
        storage = get_storage_provider()
        test_key = "_health/ready_check.txt"
        await storage.upload(test_key, b"ok")
        await storage.download(test_key)
        await storage.delete(test_key)
    except Exception as exc:  # noqa: BLE001
        storage_ok = False
        storage_error = str(exc)

    ready_state = liveness["status"] == "healthy" and storage_ok
    return {
        "ready": ready_state,
        "liveness": liveness,
        "storage": "ok" if storage_ok else f"error: {storage_error}",
    }


@router.get("/providers")
async def providers_status(db: AsyncSession = Depends(get_db)):
    secrets = get_secrets_manager()
    db_providers = {p.name: p for p in (await db.execute(select(Provider))).scalars().all()}

    result = []
    for name, cap in PROVIDER_CAPABILITIES.items():
        has_secret = True
        if cap.secret_name:
            try:
                secrets.get(cap.secret_name, required=True)
            except Exception:  # noqa: BLE001
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


@router.get("/database")
async def database_status(db: AsyncSession = Depends(get_db)):
    try:
        run_count = (await db.execute(select(func.count()).select_from(WorkflowRun))).scalar_one()
        return {"status": "ok", "workflow_run_count": run_count}
    except Exception as exc:  # noqa: BLE001
        return {"status": f"error: {exc}"}


@router.get("/storage")
async def storage_status():
    settings = get_settings()
    try:
        storage = get_storage_provider()
        test_key = "_health/storage_check.txt"
        await storage.upload(test_key, b"ok")
        exists = await storage.exists(test_key)
        await storage.delete(test_key)
        return {"backend": settings.storage_backend, "status": "ok" if exists else "degraded"}
    except Exception as exc:  # noqa: BLE001
        return {"backend": settings.storage_backend, "status": f"error: {exc}"}


@router.get("/validators")
async def validators_status():
    return {"validators": list(VALIDATOR_REGISTRY.keys())}
