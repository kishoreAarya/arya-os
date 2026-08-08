"""
Agent execution router.

Looks up the agent class in AGENT_REGISTRY, instantiates it with
db session injection when required, runs it, and returns AgentResult
as JSON.

All agents in AGENT_REGISTRY are async and fully implemented.
"""
import dataclasses
import inspect
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.base import AgentResult
from app.agents.registry import AGENT_REGISTRY
from app.database.session import get_db
from app.schemas.agent_run import AgentRunRequest, AgentRunResponse

router = APIRouter(prefix="/agents", tags=["agents"])


def _needs_db_session(agent_cls: type) -> bool:
    """True if the agent's __init__ takes anything beyond `self`."""
    params = inspect.signature(agent_cls.__init__).parameters
    return len(params) > 1  # more than just `self`


def _serialize(value: object) -> object:
    """Recursively serialize dataclass instances to JSON-safe dicts."""
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return {k: _serialize(v) for k, v in dataclasses.asdict(value).items()}
    if isinstance(value, dict):
        return {k: _serialize(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_serialize(v) for v in value]
    return value


@router.get("/")
async def list_agents():
    """Return all registered agent names callable via POST /agents/{name}/run."""
    return {"agents": list(AGENT_REGISTRY.keys())}


@router.post("/{agent_name}/run", response_model=AgentRunResponse)
async def run_agent_endpoint(
    agent_name: str,
    payload: AgentRunRequest,
    db: AsyncSession = Depends(get_db),
) -> AgentRunResponse:
    agent_cls = AGENT_REGISTRY.get(agent_name)
    if agent_cls is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No agent registered as '{agent_name}'. "
            f"Registered: {list(AGENT_REGISTRY.keys())}",
        )

    agent = agent_cls(db) if _needs_db_session(agent_cls) else agent_cls()

    context = dict(payload.context)
    if payload.workflow_run_id is not None:
        context.setdefault("workflow_run_id", payload.workflow_run_id)

    try:
        maybe_result = agent.run(context)
        result: AgentResult = (
            await maybe_result if inspect.isawaitable(maybe_result) else maybe_result
        )
    except NotImplementedError as exc:
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED, detail=str(exc)
        ) from exc

    return AgentRunResponse(
        success=result.success,
        output=_serialize(result.output),
        provider_used=result.provider_used,
        cost_usd=result.cost_usd,
        duration_seconds=result.duration_seconds,
        error=result.error,
    )