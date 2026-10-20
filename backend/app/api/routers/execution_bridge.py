"""
AryaOS V1 Stage 25 Phase 2 — Execution Bridge REST API Router.

Exposes REST contracts under /api/v1 for:
- Missions (/api/v1/projects/{project_id}/missions, /api/v1/missions/{mission_id})
- Autonomous Goals (/api/v1/projects/{project_id}/goals, /api/v1/goals/{goal_id})
- Action Nodes (/api/v1/goals/{goal_id}/actions, /api/v1/actions/{action_id})
- Governance Decisions (/api/v1/projects/{project_id}/governance-decisions, /api/v1/governance-decisions/{decision_id})

Enforces:
- Bearer token authentication on all endpoints via get_current_principal
- Project-level authorization & IDOR masking
- Co-tenancy & DAG cycle detection
- Centralized state machine transition validation
- Strictly append-only semantics for governance decisions (no PUT, PATCH, or DELETE)
"""
from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import AuthenticatedPrincipal, get_current_principal
from app.database.session import get_db
from app.schemas.execution_bridge import (
    AutonomousActionNodeCreate,
    AutonomousActionNodeResponse,
    AutonomousActionNodeUpdate,
    AutonomousGoalCreate,
    AutonomousGoalResponse,
    AutonomousGoalUpdate,
    GovernanceDecisionCreate,
    GovernanceDecisionResponse,
    MissionCreate,
    MissionResponse,
    MissionUpdate,
)
from app.services import execution_bridge_service
from app.services.autonomous_execution_runner import AutonomousExecutionRunner

router = APIRouter(prefix="/api/v1", tags=["execution-bridge"])


# -----------------------------------------------------------------------------
# 1. Missions API
# -----------------------------------------------------------------------------

@router.post(
    "/projects/{project_id}/missions",
    response_model=MissionResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new mission in an authorized project",
)
async def create_mission(
    project_id: uuid.UUID,
    data: MissionCreate,
    db: Annotated[AsyncSession, Depends(get_db)],
    principal: Annotated[AuthenticatedPrincipal, Depends(get_current_principal)],
) -> MissionResponse:
    mission = await execution_bridge_service.create_mission(db, project_id, data, principal)
    return MissionResponse.model_validate(mission)


@router.get(
    "/projects/{project_id}/missions",
    response_model=list[MissionResponse],
    summary="List all missions belonging to an authorized project",
)
async def list_missions(
    project_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    principal: Annotated[AuthenticatedPrincipal, Depends(get_current_principal)],
) -> list[MissionResponse]:
    missions = await execution_bridge_service.list_missions(db, project_id, principal)
    return [MissionResponse.model_validate(m) for m in missions]


@router.get(
    "/missions/{mission_id}",
    response_model=MissionResponse,
    summary="Get mission by ID",
)
async def get_mission(
    mission_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    principal: Annotated[AuthenticatedPrincipal, Depends(get_current_principal)],
) -> MissionResponse:
    mission = await execution_bridge_service.get_mission(db, mission_id, principal)
    return MissionResponse.model_validate(mission)


@router.patch(
    "/missions/{mission_id}",
    response_model=MissionResponse,
    summary="Update mission metadata and lifecycle status",
)
async def update_mission(
    mission_id: uuid.UUID,
    data: MissionUpdate,
    db: Annotated[AsyncSession, Depends(get_db)],
    principal: Annotated[AuthenticatedPrincipal, Depends(get_current_principal)],
) -> MissionResponse:
    mission = await execution_bridge_service.update_mission(db, mission_id, data, principal)
    return MissionResponse.model_validate(mission)


# -----------------------------------------------------------------------------
# 2. Autonomous Goals API
# -----------------------------------------------------------------------------

@router.post(
    "/projects/{project_id}/goals",
    response_model=AutonomousGoalResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create an autonomous goal with plan DAG and action nodes",
)
async def create_goal(
    project_id: uuid.UUID,
    data: AutonomousGoalCreate,
    db: Annotated[AsyncSession, Depends(get_db)],
    principal: Annotated[AuthenticatedPrincipal, Depends(get_current_principal)],
) -> AutonomousGoalResponse:
    goal = await execution_bridge_service.create_goal(db, project_id, data, principal)
    return AutonomousGoalResponse.model_validate(goal)


@router.get(
    "/projects/{project_id}/goals",
    response_model=list[AutonomousGoalResponse],
    summary="List autonomous goals for an authorized project",
)
async def list_goals(
    project_id: uuid.UUID,
    mission_id: uuid.UUID | None = Query(default=None, description="Filter by mission ID"),
    db: Annotated[AsyncSession, Depends(get_db)] = None,
    principal: Annotated[AuthenticatedPrincipal, Depends(get_current_principal)] = None,
) -> list[AutonomousGoalResponse]:
    goals = await execution_bridge_service.list_goals(db, project_id, mission_id, principal)
    return [AutonomousGoalResponse.model_validate(g) for g in goals]


@router.get(
    "/goals/{goal_id}",
    response_model=AutonomousGoalResponse,
    summary="Get autonomous goal by ID with action nodes",
)
async def get_goal(
    goal_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    principal: Annotated[AuthenticatedPrincipal, Depends(get_current_principal)],
) -> AutonomousGoalResponse:
    goal = await execution_bridge_service.get_goal(db, goal_id, principal)
    return AutonomousGoalResponse.model_validate(goal)


@router.patch(
    "/goals/{goal_id}",
    response_model=AutonomousGoalResponse,
    summary="Update goal metadata, DAG, or lifecycle status",
)
async def update_goal(
    goal_id: uuid.UUID,
    data: AutonomousGoalUpdate,
    db: Annotated[AsyncSession, Depends(get_db)],
    principal: Annotated[AuthenticatedPrincipal, Depends(get_current_principal)],
) -> AutonomousGoalResponse:
    goal = await execution_bridge_service.update_goal(db, goal_id, data, principal)
    return AutonomousGoalResponse.model_validate(goal)


@router.post(
    "/goals/{goal_id}/execute",
    response_model=AutonomousGoalResponse,
    summary="Trigger offline DAG execution progression for an autonomous goal",
)
async def execute_goal(
    goal_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    principal: Annotated[AuthenticatedPrincipal, Depends(get_current_principal)],
) -> AutonomousGoalResponse:
    runner = AutonomousExecutionRunner(db=db)
    goal = await runner.execute_goal_step(goal_id, principal)
    return AutonomousGoalResponse.model_validate(goal)


@router.post(
    "/goals/{goal_id}/cancel",
    response_model=AutonomousGoalResponse,
    summary="Cancel an autonomous goal and all non-terminal action nodes",
)
async def cancel_goal(
    goal_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    principal: Annotated[AuthenticatedPrincipal, Depends(get_current_principal)],
) -> AutonomousGoalResponse:
    runner = AutonomousExecutionRunner(db=db)
    goal = await runner.cancel_goal(goal_id, principal)
    return AutonomousGoalResponse.model_validate(goal)


# -----------------------------------------------------------------------------
# 3. Action Nodes API
# -----------------------------------------------------------------------------

@router.post(
    "/goals/{goal_id}/actions",
    response_model=AutonomousActionNodeResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Add an action node to an autonomous goal",
)
async def create_action_node(
    goal_id: uuid.UUID,
    data: AutonomousActionNodeCreate,
    db: Annotated[AsyncSession, Depends(get_db)],
    principal: Annotated[AuthenticatedPrincipal, Depends(get_current_principal)],
) -> AutonomousActionNodeResponse:
    node = await execution_bridge_service.create_action_node(db, goal_id, data, principal)
    return AutonomousActionNodeResponse.model_validate(node)


@router.get(
    "/goals/{goal_id}/actions",
    response_model=list[AutonomousActionNodeResponse],
    summary="List action nodes for a goal",
)
async def list_action_nodes(
    goal_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    principal: Annotated[AuthenticatedPrincipal, Depends(get_current_principal)],
) -> list[AutonomousActionNodeResponse]:
    nodes = await execution_bridge_service.list_action_nodes(db, goal_id, principal)
    return [AutonomousActionNodeResponse.model_validate(n) for n in nodes]


@router.get(
    "/actions/{action_id}",
    response_model=AutonomousActionNodeResponse,
    summary="Get action node by ID",
)
async def get_action_node(
    action_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    principal: Annotated[AuthenticatedPrincipal, Depends(get_current_principal)],
) -> AutonomousActionNodeResponse:
    node = await execution_bridge_service.get_action_node(db, action_id, principal)
    return AutonomousActionNodeResponse.model_validate(node)


@router.patch(
    "/actions/{action_id}",
    response_model=AutonomousActionNodeResponse,
    summary="Update action node status, outputs, or error",
)
async def update_action_node(
    action_id: uuid.UUID,
    data: AutonomousActionNodeUpdate,
    db: Annotated[AsyncSession, Depends(get_db)],
    principal: Annotated[AuthenticatedPrincipal, Depends(get_current_principal)],
) -> AutonomousActionNodeResponse:
    node = await execution_bridge_service.update_action_node(db, action_id, data, principal)
    return AutonomousActionNodeResponse.model_validate(node)


@router.post(
    "/actions/{action_id}/dispatch",
    response_model=AutonomousActionNodeResponse,
    summary="Dispatch a ready action node to the offline execution runner",
)
async def dispatch_action(
    action_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    principal: Annotated[AuthenticatedPrincipal, Depends(get_current_principal)],
) -> AutonomousActionNodeResponse:
    runner = AutonomousExecutionRunner(db=db)
    node = await runner.dispatch_action(action_id, principal)
    return AutonomousActionNodeResponse.model_validate(node)


@router.post(
    "/actions/{action_id}/reconcile",
    response_model=AutonomousActionNodeResponse,
    summary="Authoritatively reconcile an ambiguous action node or expired lease",
)
async def reconcile_action(
    action_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    principal: Annotated[AuthenticatedPrincipal, Depends(get_current_principal)],
    force_unverified_retry: bool = Query(default=False, description="Force unverified retry (Admin only)"),
) -> AutonomousActionNodeResponse:
    runner = AutonomousExecutionRunner(db=db)
    node, _report = await runner.reconcile_action(
        action_id=action_id,
        principal=principal,
        force_unverified_retry=force_unverified_retry,
    )
    return AutonomousActionNodeResponse.model_validate(node)


@router.post(
    "/actions/{action_id}/cancel",
    response_model=AutonomousActionNodeResponse,
    summary="Cancel an action node, boundedly terminate processes, and update DAG readiness",
)
async def cancel_action(
    action_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    principal: Annotated[AuthenticatedPrincipal, Depends(get_current_principal)],
) -> AutonomousActionNodeResponse:
    runner = AutonomousExecutionRunner(db=db)
    node = await runner.cancel_action(action_id, principal)
    return AutonomousActionNodeResponse.model_validate(node)


# -----------------------------------------------------------------------------
# 4. Governance Decisions API (Append-Only)
# -----------------------------------------------------------------------------

@router.post(
    "/projects/{project_id}/governance-decisions",
    response_model=GovernanceDecisionResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Record an authoritative governance evaluation decision",
)
async def create_governance_decision(
    project_id: uuid.UUID,
    data: GovernanceDecisionCreate,
    db: Annotated[AsyncSession, Depends(get_db)],
    principal: Annotated[AuthenticatedPrincipal, Depends(get_current_principal)],
) -> GovernanceDecisionResponse:
    decision = await execution_bridge_service.create_governance_decision(
        db, project_id, data, principal
    )
    return GovernanceDecisionResponse.model_validate(decision)


@router.get(
    "/projects/{project_id}/governance-decisions",
    response_model=list[GovernanceDecisionResponse],
    summary="List governance decisions for an authorized project",
)
async def list_governance_decisions(
    project_id: uuid.UUID,
    goal_id: uuid.UUID | None = Query(default=None, description="Filter by goal ID"),
    db: Annotated[AsyncSession, Depends(get_db)] = None,
    principal: Annotated[AuthenticatedPrincipal, Depends(get_current_principal)] = None,
) -> list[GovernanceDecisionResponse]:
    decisions = await execution_bridge_service.list_governance_decisions(
        db, project_id, goal_id, principal
    )
    return [GovernanceDecisionResponse.model_validate(d) for d in decisions]


@router.get(
    "/governance-decisions/{decision_id}",
    response_model=GovernanceDecisionResponse,
    summary="Get governance decision by ID",
)
async def get_governance_decision(
    decision_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    principal: Annotated[AuthenticatedPrincipal, Depends(get_current_principal)],
) -> GovernanceDecisionResponse:
    decision = await execution_bridge_service.get_governance_decision(
        db, decision_id, principal
    )
    return GovernanceDecisionResponse.model_validate(decision)
