"""Feature flag CRUD — lets the dashboard flip flags without a redeploy."""
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from app.core.security import AuthenticatedPrincipal, get_current_principal
from app.services import feature_flags as svc

router = APIRouter(prefix="/feature-flags", tags=["feature-flags"])


class SetFlagRequest(BaseModel):
    enabled: bool
    description: str | None = None


@router.get("/")
async def list_flags(principal: AuthenticatedPrincipal = Depends(get_current_principal)):
    flags = await svc.list_flags()
    return [{"name": f.name, "enabled": f.enabled, "description": f.description} for f in flags]


@router.get("/{name}")
async def get_flag(name: str, principal: AuthenticatedPrincipal = Depends(get_current_principal)):
    return {"name": name, "enabled": await svc.is_enabled(name)}


@router.put("/{name}")
async def set_flag(
    name: str,
    payload: SetFlagRequest,
    principal: AuthenticatedPrincipal = Depends(get_current_principal),
):
    if not principal.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Forbidden: Admin access required to modify feature flags",
        )
    if name.lower().strip() in (
        "enable_live_provider_execution",
        "live_provider_execution",
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Modification of ENABLE_LIVE_PROVIDER_EXECUTION via API endpoint is strictly prohibited. It must be configured via server configuration only.",
        )
    flag = await svc.set_flag(name, payload.enabled, payload.description)
    return {"name": flag.name, "enabled": flag.enabled, "description": flag.description}
