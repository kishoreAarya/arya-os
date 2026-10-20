"""
AryaOS V1 Stage 25 Phase 2 — Execution Bridge Domain Service.

Implements core domain operations, authorization checks, co-tenancy enforcement,
DAG validation, and centralized lifecycle state machine transitions for:
- Missions
- Autonomous Goals
- Autonomous Action Nodes
- Governance Decisions
"""
from __future__ import annotations

import uuid
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.logging import get_logger
from app.core.security import AuthenticatedPrincipal
from app.models.approval import ApprovalCheckpoint
from app.models.core import Project, WorkflowRun
from app.models.execution_bridge import (
    AutonomousActionNode,
    AutonomousGoal,
    GovernanceDecision,
    Mission,
)
from app.models.production import ProductionJob
from app.schemas.execution_bridge import (
    AutonomousActionNodeCreate,
    AutonomousActionNodeUpdate,
    AutonomousGoalCreate,
    AutonomousGoalUpdate,
    GovernanceDecisionCreate,
    MissionCreate,
    MissionUpdate,
)
from app.services.authorization_service import (
    get_authorized_project_ids,
    verify_project_access,
)
from app.services.dag_validator import DAGValidationError, validate_plan_dag

logger = get_logger("arya.execution_bridge")


# -----------------------------------------------------------------------------
# Centralized Lifecycle State Machines
# -----------------------------------------------------------------------------

VALID_MISSION_STATES = {
    "PLANNED",
    "ACTIVE",
    "PAUSED",
    "COMPLETED",
    "FAILED",
    "CANCELLED",
}

VALID_MISSION_TRANSITIONS: dict[str, set[str]] = {
    "PLANNED": {"ACTIVE", "CANCELLED"},
    "ACTIVE": {"PAUSED", "COMPLETED", "FAILED", "CANCELLED"},
    "PAUSED": {"ACTIVE", "CANCELLED"},
    "COMPLETED": set(),
    "FAILED": {"PLANNED", "ACTIVE"},
    "CANCELLED": set(),
}

VALID_GOAL_STATES = {
    "DRAFT",
    "READY",
    "PLANNING",
    "EXECUTING",
    "PAUSED",
    "AWAITING_APPROVAL",
    "COMPLETED",
    "FAILED",
    "CANCELLED",
    "BLOCKED",
    "RECOVERY_REQUIRED",
}

VALID_GOAL_TRANSITIONS: dict[str, set[str]] = {
    "DRAFT": {"READY", "PLANNING", "CANCELLED"},
    "READY": {"EXECUTING", "PAUSED", "CANCELLED", "BLOCKED"},
    "PLANNING": {"READY", "FAILED", "CANCELLED"},
    "EXECUTING": {
        "PAUSED",
        "AWAITING_APPROVAL",
        "COMPLETED",
        "FAILED",
        "CANCELLED",
        "BLOCKED",
        "RECOVERY_REQUIRED",
    },
    "PAUSED": {"EXECUTING", "READY", "CANCELLED"},
    "AWAITING_APPROVAL": {"EXECUTING", "PAUSED", "CANCELLED", "BLOCKED"},
    "BLOCKED": {"READY", "EXECUTING", "FAILED", "CANCELLED"},
    "RECOVERY_REQUIRED": {"READY", "FAILED", "CANCELLED"},
    "COMPLETED": set(),
    "FAILED": {"DRAFT", "READY"},
    "CANCELLED": set(),
}

VALID_ACTION_STATES = {
    "PENDING",
    "READY",
    "EXECUTING",
    "AWAITING_APPROVAL",
    "SUCCEEDED",
    "FAILED",
    "BLOCKED",
    "SKIPPED",
    "UNKNOWN_PENDING_RECONCILIATION",
    "RECOVERY_REQUIRED",
    "CANCELLED",
}

VALID_ACTION_TRANSITIONS: dict[str, set[str]] = {
    "PENDING": {"READY", "BLOCKED", "SKIPPED", "AWAITING_APPROVAL", "CANCELLED"},
    "READY": {"EXECUTING", "BLOCKED", "SKIPPED", "AWAITING_APPROVAL", "CANCELLED"},
    "BLOCKED": {"READY", "SKIPPED", "FAILED", "AWAITING_APPROVAL", "CANCELLED"},
    "EXECUTING": {
        "AWAITING_APPROVAL",
        "SUCCEEDED",
        "FAILED",
        "UNKNOWN_PENDING_RECONCILIATION",
        "RECOVERY_REQUIRED",
        "READY",
        "BLOCKED",
        "CANCELLED",
    },
    "AWAITING_APPROVAL": {"EXECUTING", "SUCCEEDED", "FAILED", "SKIPPED", "BLOCKED", "READY", "CANCELLED"},
    "UNKNOWN_PENDING_RECONCILIATION": {"FAILED", "RECOVERY_REQUIRED", "SUCCEEDED", "READY", "BLOCKED"},
    "RECOVERY_REQUIRED": {"READY", "FAILED", "BLOCKED"},
    "SUCCEEDED": set(),
    "FAILED": {"PENDING", "READY"},
    "SKIPPED": set(),
    "CANCELLED": set(),
}

# Terminal success states that CANNOT be forced via ordinary client CRUD/PATCH
RESTRICTED_CLIENT_TERMINAL_STATES = {
    "COMPLETED",
    "SUCCEEDED",
}

# Unresolved uncertainty, executing, and recovery states that CANNOT be bypassed via ordinary client CRUD/PATCH
RESTRICTED_CLIENT_SOURCE_STATES = {
    "UNKNOWN_PENDING_RECONCILIATION",
    "RECOVERY_REQUIRED",
    "EXECUTING",
}


def validate_state_transition(
    entity_name: str,
    current_state: str,
    new_state: str,
    valid_states: set[str],
    transition_map: dict[str, set[str]],
    is_authoritative_engine: bool = False,
) -> None:
    """Validates state machine transitions and blocks unauthorized client state overrides."""
    if new_state not in valid_states:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Invalid {entity_name} state '{new_state}'. Allowed: {sorted(valid_states)}",
        )

    if not is_authoritative_engine and new_state in RESTRICTED_CLIENT_TERMINAL_STATES:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"Client cannot directly force {entity_name} into terminal state '{new_state}'. "
                "Terminal success must be recorded exclusively by authoritative execution engines."
            ),
        )

    if not is_authoritative_engine and current_state == "AWAITING_APPROVAL" and new_state == "READY":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"Client cannot directly transition {entity_name} from 'AWAITING_APPROVAL' to 'READY'. "
                "Approval must be recorded through authoritative approval mechanisms."
            ),
        )

    if (
        not is_authoritative_engine
        and current_state in RESTRICTED_CLIENT_SOURCE_STATES
        and new_state != current_state
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"Client cannot directly transition {entity_name} from '{current_state}' to '{new_state}'. "
                "Re-entry into execution requires authoritative reconciliation and recovery."
            ),
        )

    allowed = transition_map.get(current_state, set())
    if new_state != current_state and new_state not in allowed:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"Illegal {entity_name} state transition from '{current_state}' to '{new_state}'. "
                f"Allowed transitions: {sorted(allowed) if allowed else 'none (terminal state)'}"
            ),
        )


# -----------------------------------------------------------------------------
# 1. Mission Operations
# -----------------------------------------------------------------------------

async def create_mission(
    db: AsyncSession,
    project_id: uuid.UUID,
    data: MissionCreate,
    principal: AuthenticatedPrincipal,
) -> Mission:
    """Create a new mission in an authorized project."""
    await verify_project_access(db, principal, project_id)

    mission = Mission(
        project_id=project_id,
        title=data.title.strip(),
        objective=data.objective.strip(),
        status="PLANNED",
        priority=data.priority,
        deadline=data.deadline,
        completion_criteria_json=data.completion_criteria_json or {},
        execution_policy_json=data.execution_policy_json or {},
    )
    db.add(mission)
    await db.commit()
    await db.refresh(mission)
    return mission


async def list_missions(
    db: AsyncSession,
    project_id: uuid.UUID,
    principal: AuthenticatedPrincipal,
) -> list[Mission]:
    """List all missions belonging to an authorized project."""
    await verify_project_access(db, principal, project_id)

    stmt = select(Mission).where(Mission.project_id == project_id).order_by(Mission.created_at.desc())
    res = await db.execute(stmt)
    return list(res.scalars().all())


async def get_mission(
    db: AsyncSession,
    mission_id: uuid.UUID,
    principal: AuthenticatedPrincipal,
) -> Mission:
    """Fetch a mission by ID with IDOR protection."""
    mission = await db.get(Mission, mission_id)
    if not mission:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Mission not found")

    if not principal.is_admin:
        allowed_ids = await get_authorized_project_ids(db, principal)
        if allowed_ids is None or mission.project_id not in allowed_ids:
            # Mask existence on cross-project unauthorized access
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Mission not found")

    return mission


async def update_mission(
    db: AsyncSession,
    mission_id: uuid.UUID,
    data: MissionUpdate,
    principal: AuthenticatedPrincipal,
) -> Mission:
    """Update mission fields and enforce valid lifecycle transitions."""
    mission = await get_mission(db, mission_id, principal)

    if data.status is not None:
        validate_state_transition(
            "Mission",
            mission.status,
            data.status,
            VALID_MISSION_STATES,
            VALID_MISSION_TRANSITIONS,
        )
        mission.status = data.status

    if data.title is not None:
        mission.title = data.title.strip()
    if data.objective is not None:
        mission.objective = data.objective.strip()
    if data.priority is not None:
        mission.priority = data.priority
    if data.deadline is not None:
        mission.deadline = data.deadline
    if data.progress_json is not None:
        mission.progress_json = data.progress_json
    if data.completion_criteria_json is not None:
        mission.completion_criteria_json = data.completion_criteria_json
    if data.execution_policy_json is not None:
        mission.execution_policy_json = data.execution_policy_json

    await db.commit()
    await db.refresh(mission)
    return mission


# -----------------------------------------------------------------------------
# 2. Autonomous Goal Operations
# -----------------------------------------------------------------------------

async def create_goal(
    db: AsyncSession,
    project_id: uuid.UUID,
    data: AutonomousGoalCreate,
    principal: AuthenticatedPrincipal,
) -> AutonomousGoal:
    """Create an autonomous goal with optional DAG and initial action nodes."""
    await verify_project_access(db, principal, project_id)

    # 1. Cross-Project Co-Tenancy Check on Mission
    if data.mission_id is not None:
        mission = await db.get(Mission, data.mission_id)
        if not mission or mission.project_id != project_id:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Referenced mission does not belong to the authorized project",
            )

    # 2. Extract action client IDs and validate action dependencies
    action_cids = [a.client_action_id for a in data.actions] if data.actions else []
    validate_plan_dag(data.plan_dag_json or {}, action_client_ids=action_cids)

    # 3. Create Goal
    goal = AutonomousGoal(
        project_id=project_id,
        mission_id=data.mission_id,
        objective=data.objective.strip(),
        status="DRAFT",
        current_plan_version=data.current_plan_version,
        plan_dag_json=data.plan_dag_json or {},
        context_memory_ids=data.context_memory_ids or [],
    )
    db.add(goal)
    await db.flush()

    # 4. Create Action Nodes attached to Goal with Co-Tenancy validation
    for action_data in data.actions:
        await _validate_action_references(db, project_id, action_data)
        node = AutonomousActionNode(
            goal_id=goal.id,
            client_action_id=action_data.client_action_id.strip(),
            title=action_data.title.strip(),
            action_type=action_data.action_type,
            required_capability=action_data.required_capability.strip(),
            status="PENDING",
            risk_level=action_data.risk_level,
            inputs_json=action_data.inputs_json or {},
            production_job_id=action_data.production_job_id,
            approval_checkpoint_id=action_data.approval_checkpoint_id,
        )
        db.add(node)

    await db.commit()
    # Refresh with loaded actions
    stmt = (
        select(AutonomousGoal)
        .where(AutonomousGoal.id == goal.id)
        .options(selectinload(AutonomousGoal.actions))
    )
    res = await db.execute(stmt)
    return res.scalar_one()


async def list_goals(
    db: AsyncSession,
    project_id: uuid.UUID,
    mission_id: uuid.UUID | None,
    principal: AuthenticatedPrincipal,
) -> list[AutonomousGoal]:
    """List goals belonging to an authorized project, optionally filtered by mission."""
    await verify_project_access(db, principal, project_id)

    stmt = select(AutonomousGoal).where(AutonomousGoal.project_id == project_id)
    if mission_id is not None:
        stmt = stmt.where(AutonomousGoal.mission_id == mission_id)
    stmt = stmt.options(selectinload(AutonomousGoal.actions)).order_by(AutonomousGoal.created_at.desc())

    res = await db.execute(stmt)
    return list(res.scalars().all())


async def get_goal(
    db: AsyncSession,
    goal_id: uuid.UUID,
    principal: AuthenticatedPrincipal,
) -> AutonomousGoal:
    """Fetch an autonomous goal with IDOR protection."""
    stmt = (
        select(AutonomousGoal)
        .where(AutonomousGoal.id == goal_id)
        .options(
            selectinload(AutonomousGoal.actions),
            selectinload(AutonomousGoal.governance_decisions),
        )
    )
    res = await db.execute(stmt)
    goal = res.scalar_one_or_none()

    if not goal:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Goal not found")

    if not principal.is_admin:
        allowed_ids = await get_authorized_project_ids(db, principal)
        if allowed_ids is None or goal.project_id not in allowed_ids:
            # Mask existence on cross-project unauthorized access
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Goal not found")

    return goal


async def update_goal(
    db: AsyncSession,
    goal_id: uuid.UUID,
    data: AutonomousGoalUpdate,
    principal: AuthenticatedPrincipal,
) -> AutonomousGoal:
    """Update goal fields, enforce state machine transitions, and validate DAG modifications."""
    goal = await get_goal(db, goal_id, principal)

    if data.status is not None:
        validate_state_transition(
            "Goal",
            goal.status,
            data.status,
            VALID_GOAL_STATES,
            VALID_GOAL_TRANSITIONS,
        )
        # If transitioning to READY, verify that plan DAG is valid and acyclic
        if data.status == "READY":
            existing_cids = [a.client_action_id for a in goal.actions]
            validate_plan_dag(goal.plan_dag_json, action_client_ids=existing_cids)
        elif data.status == "CANCELLED":
            has_unknown = any(
                a.status in ("UNKNOWN_PENDING_RECONCILIATION", "RECOVERY_REQUIRED")
                for a in (goal.actions or [])
            )
            if not has_unknown:
                from datetime import timezone
                from app.models.execution_bridge import BudgetReservation
                stmt_res = select(BudgetReservation).where(
                    BudgetReservation.goal_id == goal.id,
                    BudgetReservation.plan_version == goal.current_plan_version,
                ).with_for_update()
                res_r = await db.execute(stmt_res)
                reservation = res_r.scalar_one_or_none()
                if reservation and reservation.status == "RESERVED":
                    reservation.status = "RELEASED"
                    reservation.updated_at = datetime.now(timezone.utc)
        goal.status = data.status

    if data.plan_dag_json is not None:
        existing_cids = [a.client_action_id for a in goal.actions]
        validate_plan_dag(data.plan_dag_json, action_client_ids=existing_cids)
        goal.plan_dag_json = data.plan_dag_json

    if data.objective is not None:
        goal.objective = data.objective.strip()
    if data.current_plan_version is not None:
        goal.current_plan_version = data.current_plan_version
    if data.context_memory_ids is not None:
        goal.context_memory_ids = data.context_memory_ids
    if data.final_summary is not None:
        goal.final_summary = data.final_summary
    if data.failure_reason is not None:
        goal.failure_reason = data.failure_reason

    await db.commit()
    return await get_goal(db, goal_id, principal)


# -----------------------------------------------------------------------------
# 3. Action Node Operations
# -----------------------------------------------------------------------------

async def _validate_action_references(
    db: AsyncSession,
    project_id: uuid.UUID,
    action_data: AutonomousActionNodeCreate | AutonomousActionNodeUpdate,
    node_id: uuid.UUID | None = None,
) -> None:
    """Validates that production jobs and approval checkpoints belong to the goal's project."""
    if action_data.production_job_id is not None:
        job = await db.get(ProductionJob, action_data.production_job_id)
        if not job or job.project_id != project_id:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Referenced production job does not belong to the authorized project",
            )

    if getattr(action_data, "approval_checkpoint_id", None) is not None:
        checkpoint = await db.get(ApprovalCheckpoint, action_data.approval_checkpoint_id)
        if not checkpoint:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Referenced approval checkpoint does not exist",
            )
        run = await db.get(WorkflowRun, checkpoint.workflow_run_id)
        if not run or run.project_id != project_id:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Referenced approval checkpoint does not belong to the authorized project",
            )
        if checkpoint.reference_table != "autonomous_action_nodes":
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Referenced approval checkpoint reference_table must be 'autonomous_action_nodes'",
            )
        if node_id is not None and checkpoint.reference_id != node_id:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Referenced approval checkpoint reference_id does not match this action node",
            )


async def create_action_node(
    db: AsyncSession,
    goal_id: uuid.UUID,
    data: AutonomousActionNodeCreate,
    principal: AuthenticatedPrincipal,
) -> AutonomousActionNode:
    """Add a new action node to an autonomous goal."""
    goal = await get_goal(db, goal_id, principal)

    # DAG Topology Freeze (SEC-FINDING-03): Action nodes can only be created when Goal is in DRAFT or PLANNING
    if goal.status not in ("DRAFT", "PLANNING"):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"Action node creation rejected: DAG topology is frozen while Goal is in '{goal.status}'. "
                "Actions can only be added when Goal status is 'DRAFT' or 'PLANNING'."
            ),
        )

    # Check for duplicate client_action_id within goal
    stmt = select(AutonomousActionNode).where(
        AutonomousActionNode.goal_id == goal_id,
        AutonomousActionNode.client_action_id == data.client_action_id.strip(),
    )
    res = await db.execute(stmt)
    if res.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Action node with client_action_id '{data.client_action_id}' already exists in this goal",
        )

    await _validate_action_references(db, goal.project_id, data)

    node = AutonomousActionNode(
        goal_id=goal_id,
        client_action_id=data.client_action_id.strip(),
        title=data.title.strip(),
        action_type=data.action_type,
        required_capability=data.required_capability.strip(),
        status="PENDING",
        risk_level=data.risk_level,
        inputs_json=data.inputs_json or {},
        production_job_id=data.production_job_id,
        approval_checkpoint_id=data.approval_checkpoint_id,
    )
    db.add(node)
    await db.commit()
    await db.refresh(node)
    return node


async def list_action_nodes(
    db: AsyncSession,
    goal_id: uuid.UUID,
    principal: AuthenticatedPrincipal,
) -> list[AutonomousActionNode]:
    """List action nodes for an authorized goal."""
    goal = await get_goal(db, goal_id, principal)
    stmt = (
        select(AutonomousActionNode)
        .where(AutonomousActionNode.goal_id == goal.id)
        .order_by(AutonomousActionNode.created_at.asc())
    )
    res = await db.execute(stmt)
    return list(res.scalars().all())


async def get_action_node(
    db: AsyncSession,
    action_id: uuid.UUID,
    principal: AuthenticatedPrincipal,
) -> AutonomousActionNode:
    """Fetch an action node by ID with IDOR protection."""
    node = await db.get(AutonomousActionNode, action_id)
    if not node:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Action node not found")

    goal = await db.get(AutonomousGoal, node.goal_id)
    if not goal:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Action node not found")

    if not principal.is_admin:
        allowed_ids = await get_authorized_project_ids(db, principal)
        if allowed_ids is None or goal.project_id not in allowed_ids:
            # Mask existence on cross-project unauthorized access
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Action node not found")

    return node


async def update_action_node(
    db: AsyncSession,
    action_id: uuid.UUID,
    data: AutonomousActionNodeUpdate,
    principal: AuthenticatedPrincipal,
    is_authoritative_engine: bool = False,
) -> AutonomousActionNode:
    """Update action node status or outputs, enforcing state machine and co-tenancy."""
    node = await get_action_node(db, action_id, principal)
    goal = await db.get(AutonomousGoal, node.goal_id)
    assert goal is not None

    if data.status is not None:
        if (
            not is_authoritative_engine
            and data.status == "READY"
            and (node.risk_level in ("HIGH", "CRITICAL") or node.action_type == "DECISION")
        ):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    f"Action '{node.client_action_id}' has risk_level '{node.risk_level}' "
                    "and cannot be transitioned to READY without authoritative approval."
                ),
            )

        validate_state_transition(
            "ActionNode",
            node.status,
            data.status,
            VALID_ACTION_STATES,
            VALID_ACTION_TRANSITIONS,
            is_authoritative_engine=is_authoritative_engine,
        )
        node.status = data.status

    await _validate_action_references(db, goal.project_id, data, node_id=node.id)

    if data.production_job_id is not None:
        node.production_job_id = data.production_job_id

    await db.commit()
    await db.refresh(node)
    return node


# -----------------------------------------------------------------------------
# 4. Governance Decisions (Append-Only)
# -----------------------------------------------------------------------------

async def create_governance_decision(
    db: AsyncSession,
    project_id: uuid.UUID,
    data: GovernanceDecisionCreate,
    principal: AuthenticatedPrincipal,
) -> GovernanceDecision:
    """Create an authoritative audit record of a governance evaluation. Append-only."""
    await verify_project_access(db, principal, project_id)

    # Co-Tenancy validation: Goal and Action must belong to project_id
    if data.goal_id is not None:
        goal = await db.get(AutonomousGoal, data.goal_id)
        if not goal or goal.project_id != project_id:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Referenced goal does not belong to the authorized project",
            )

    if data.action_node_id is not None:
        node = await db.get(AutonomousActionNode, data.action_node_id)
        if not node:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Referenced action node does not exist",
            )
        parent_goal = await db.get(AutonomousGoal, node.goal_id)
        if not parent_goal or parent_goal.project_id != project_id:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Referenced action node does not belong to the authorized project",
            )
        if data.goal_id is not None and node.goal_id != data.goal_id:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Referenced action node does not belong to the specified goal",
            )

    decision = GovernanceDecision(
        project_id=project_id,
        goal_id=data.goal_id,
        action_node_id=data.action_node_id,
        verdict=data.verdict,
        risk_level=data.risk_level,
        policy_evaluations=data.policy_evaluations or [],
        reasons=data.reasons or [],
    )
    db.add(decision)
    await db.commit()
    await db.refresh(decision)
    return decision


async def list_governance_decisions(
    db: AsyncSession,
    project_id: uuid.UUID,
    goal_id: uuid.UUID | None,
    principal: AuthenticatedPrincipal,
) -> list[GovernanceDecision]:
    """List governance decisions for an authorized project, optionally filtered by goal."""
    await verify_project_access(db, principal, project_id)

    stmt = select(GovernanceDecision).where(GovernanceDecision.project_id == project_id)
    if goal_id is not None:
        stmt = stmt.where(GovernanceDecision.goal_id == goal_id)
    stmt = stmt.order_by(GovernanceDecision.created_at.desc())

    res = await db.execute(stmt)
    return list(res.scalars().all())


async def get_governance_decision(
    db: AsyncSession,
    decision_id: uuid.UUID,
    principal: AuthenticatedPrincipal,
) -> GovernanceDecision:
    """Fetch a governance decision with IDOR protection."""
    decision = await db.get(GovernanceDecision, decision_id)
    if not decision:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Governance decision not found"
        )

    if not principal.is_admin:
        allowed_ids = await get_authorized_project_ids(db, principal)
        if allowed_ids is None or decision.project_id not in allowed_ids:
            # Mask existence on cross-project unauthorized access
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Governance decision not found"
            )

    return decision
