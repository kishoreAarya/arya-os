"""Feature flag CRUD — lets the dashboard flip flags without a redeploy."""
from fastapi import APIRouter
from pydantic import BaseModel

from app.services import feature_flags as svc

router = APIRouter(prefix="/feature-flags", tags=["feature-flags"])


class SetFlagRequest(BaseModel):
    enabled: bool
    description: str | None = None


@router.get("/")
async def list_flags():
    flags = await svc.list_flags()
    return [{"name": f.name, "enabled": f.enabled, "description": f.description} for f in flags]


@router.get("/{name}")
async def get_flag(name: str):
    return {"name": name, "enabled": await svc.is_enabled(name)}


@router.put("/{name}")
async def set_flag(name: str, payload: SetFlagRequest):
    flag = await svc.set_flag(name, payload.enabled, payload.description)
    return {"name": flag.name, "enabled": flag.enabled, "description": flag.description}
