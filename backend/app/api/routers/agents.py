"""
Agent execution router.

Missing API route, flagged explicitly in agents/storyboard.py's own
docstring ("a future backend route... not built here, out of scope
for this agent-layer-only milestone") and confirmed by inspection: no
router anywhere in app/api/routers/ calls into AGENT_REGISTRY or
instantiates an agent. Every agent (TrendAgent, ScriptAgent,
ImageAgent, ...), ExecutionEngine, and DecisionEngine are fully wired
to each other, but nothing HTTP-reachable invokes any of it — n8n (the
orchestrator) has no way to actually ask this backend to run a stage.

This route is deliberately thin: look up the agent class in the
EXISTING `AGENT_REGISTRY` (app/agents/registry.py, unmodified),
instantiate it the same way the registry's own docstring documents
(`AGENT_REGISTRY[name](db)` if it takes a session, `AGENT_REGISTRY[name]()`
if not), call `.run(context)` (awaiting it if the agent is async — the
three stub agents, ScriptAgent/PromptAgent/MusicAgent, are sync and
raise NotImplementedError, which this route reports as a normal 501,
not a 500), and return the resulting AgentResult as JSON.

No agent, ExecutionEngine, or DecisionEngine code is modified.
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
    """True if this agent's __init__ takes anything beyond `self`
    (every real agent takes `db: AsyncSession`; ScriptAgent, PromptAgent,
    and MusicAgent don't define __init__ at all, per registry.py's own
    docstring)."""
    params = inspect.signature(agent_cls.__init__).parameters
    return len(params) > 1  # more than just `self`


def _serialize(value: object) -> object:
    """AgentResult.output often holds a nested dataclass (e.g.
    TrendAgent's ResearchResult, StoryboardAgent's StoryboardResult) —
    plain `dict()` on AgentResult wouldn't recurse into those. This
    converts any dataclass instance (top-level or nested in a
    dict/list) into a JSON-safe structure without needing to know each
    agent's specific output dataclass ahead of time."""
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return {k: _serialize(v) for k, v in dataclasses.asdict(value).items()}
    if isinstance(value, dict):
        return {k: _serialize(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_serialize(v) for v in value]
    return value


@router.get("/")
async def list_agents():
    """Which agent names are callable via POST /agents/{name}/run —
    lets n8n (or a human) discover this without reading source."""
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
        # The three pure stubs (ScriptAgent/PromptAgent/MusicAgent)
        # raise this on purpose — a 501 accurately reports "this agent
        # isn't built yet" instead of looking like a server error.
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
