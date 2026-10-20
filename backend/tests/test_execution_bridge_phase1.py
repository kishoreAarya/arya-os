"""
AryaOS V1 Stage 25 Phase 1 — Autonomous Execution Bridge Unit & Integration Tests.

Validates the Stage 25 Phase 1 PostgreSQL data foundation:
1. Mission model creation and project relationship
2. AutonomousGoal model creation with action DAG relationship
3. AutonomousActionNode creation with production_job and approval_checkpoint foreign keys
4. GovernanceDecision creation and relationship linking
5. Project cascade deletion across missions, goals, action nodes, and governance decisions
6. Mission deletion sets goal.mission_id to NULL (preserving goals)
7. Foreign key enforcement on invalid references
8. Pydantic schema validation (forbid extra, type/literal enforcement)
9. Lifecycle state defaults (never defaulting to completion)
10. Database migration verification (alembic revision matches h8c9d0e1f2a3)
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
from pydantic import ValidationError
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.approval import ApprovalCheckpoint
from app.models.core import Project, WorkflowRun
from app.models.enums import ApprovalStage, WorkflowMode, WorkflowStatus
from app.models.execution_bridge import (
    AutonomousActionNode,
    AutonomousGoal,
    GovernanceDecision,
    Mission,
)
from app.models.production import ProductionJob, ProductionSequence, ProductionShot
from app.schemas.execution_bridge import (
    AutonomousActionNodeCreate,
    AutonomousGoalCreate,
    GovernanceDecisionCreate,
    MissionCreate,
)

pytestmark = pytest.mark.asyncio(loop_scope="module")


async def test_01_create_mission(db_session: AsyncSession, test_project: uuid.UUID):
    """Verify Mission creation, JSON handling, and Project relationship."""
    mission = Mission(
        project_id=test_project,
        title="Cinematic Lore Campaign",
        objective="Generate multi-scene concept teasers for memory environment",
        priority="HIGH",
        status="PLANNED",
        deadline=datetime.now(timezone.utc),
        progress_json={"total_goals": 3, "completed_goals": 0, "percentage": 0.0},
        completion_criteria_json={"minimum_success_rate": 0.8, "require_human_signoff": True},
        execution_policy_json={"auto_retry": True, "max_cost_usd": 5.0},
    )
    db_session.add(mission)
    await db_session.commit()
    await db_session.refresh(mission)

    assert mission.id is not None
    assert mission.project_id == test_project
    assert mission.status == "PLANNED"
    assert mission.priority == "HIGH"
    assert mission.progress_json["total_goals"] == 3
    assert mission.completion_criteria_json["minimum_success_rate"] == 0.8
    assert mission.execution_policy_json["max_cost_usd"] == 5.0

    # Test Project relationship back_populates
    proj = await db_session.get(Project, test_project)
    assert proj is not None
    # Re-fetch with relationship
    res = await db_session.execute(
        select(Project).where(Project.id == test_project)
    )
    p = res.scalar_one()
    # Query missions for project
    missions_res = await db_session.execute(
        select(Mission).where(Mission.project_id == test_project)
    )
    missions = missions_res.scalars().all()
    assert any(m.id == mission.id for m in missions)


async def test_02_create_autonomous_goal_with_actions(
    db_session: AsyncSession, test_project: uuid.UUID
):
    """Verify AutonomousGoal creation with ordered action DAG nodes."""
    goal = AutonomousGoal(
        project_id=test_project,
        objective="Research obsidian architecture references and formulate teaser prompt",
        status="DRAFT",
        current_plan_version=1,
        plan_dag_json={
            "nodes": ["act-01", "act-02"],
            "edges": [{"source": "act-01", "target": "act-02"}],
        },
        context_memory_ids=["MEM-0001", "MEM-0002"],
    )
    db_session.add(goal)
    await db_session.flush()

    action1 = AutonomousActionNode(
        goal_id=goal.id,
        client_action_id="act-01",
        title="Synthesize obsidian lore references",
        action_type="RESEARCH",
        required_capability="REASONING",
        status="READY",
        risk_level="LOW",
        inputs_json={"prompt": "Analyze architectural style of vitrine towers"},
    )
    action2 = AutonomousActionNode(
        goal_id=goal.id,
        client_action_id="act-02",
        title="Generate shot prompt package",
        action_type="JOB_PACKAGE",
        required_capability="IMAGE_GENERATION",
        status="PENDING",
        risk_level="MEDIUM",
        inputs_json={"style": "cinematic_hero", "aspect": "16:9"},
    )
    db_session.add_all([action1, action2])
    await db_session.commit()
    await db_session.refresh(goal)

    # Query actions
    actions_res = await db_session.execute(
        select(AutonomousActionNode)
        .where(AutonomousActionNode.goal_id == goal.id)
        .order_by(AutonomousActionNode.client_action_id)
    )
    actions = actions_res.scalars().all()
    assert len(actions) == 2
    assert actions[0].client_action_id == "act-01"
    assert actions[0].action_type == "RESEARCH"
    assert actions[0].status == "READY"
    assert actions[1].client_action_id == "act-02"
    assert actions[1].status == "PENDING"
    assert actions[1].risk_level == "MEDIUM"


async def test_03_link_action_to_production_job_and_checkpoint(
    db_session: AsyncSession, test_project: uuid.UUID
):
    """Verify linking AutonomousActionNode to existing ProductionJob and ApprovalCheckpoint."""
    # 1. Create Production Sequence and Shot
    seq = ProductionSequence(
        project_id=test_project,
        name="Sequence Alpha",
        order_index=1,
    )
    db_session.add(seq)
    await db_session.flush()

    shot = ProductionShot(
        project_id=test_project,
        sequence_id=seq.id,
        shot_number=1,
        title="Hero Arrival",
        prompt="Dramatic entrance to obsidian sanctuary",
        model="fal-sd-v1",
        provider="fal",
    )
    db_session.add(shot)
    await db_session.flush()

    # 2. Create Production Job
    job = ProductionJob(
        project_id=test_project,
        shot_id=shot.id,
        job_package_id="pkg-test-01",
        provider="fal",
        model="fal-sd-v1",
        status="QUEUED",
        progress=0.0,
    )
    db_session.add(job)

    # 3. Create WorkflowRun and ApprovalCheckpoint
    wrun = WorkflowRun(
        project_id=test_project,
        mode=WorkflowMode.ASSISTED,
        status=WorkflowStatus.RUNNING,
    )
    db_session.add(wrun)
    await db_session.flush()

    checkpoint = ApprovalCheckpoint(
        workflow_run_id=wrun.id,
        stage=ApprovalStage.IMAGE,
        reference_table="production_jobs",
        reference_id=job.id,
    )
    db_session.add(checkpoint)
    await db_session.flush()

    # 4. Create Goal and Action Node linking to job and checkpoint
    goal = AutonomousGoal(
        project_id=test_project,
        objective="Generate keyframe and require human review",
        status="EXECUTING",
    )
    db_session.add(goal)
    await db_session.flush()

    action = AutonomousActionNode(
        goal_id=goal.id,
        client_action_id="act-render-01",
        title="Render Hero Keyframe",
        action_type="JOB_PACKAGE",
        required_capability="IMAGE_GENERATION",
        status="AWAITING_APPROVAL",
        risk_level="HIGH",
        production_job_id=job.id,
        approval_checkpoint_id=checkpoint.id,
        cost_usd=0.0250,
        duration_seconds=3.45,
    )
    db_session.add(action)
    await db_session.commit()
    await db_session.refresh(action)

    assert action.production_job_id == job.id
    assert action.approval_checkpoint_id == checkpoint.id
    assert float(action.cost_usd) == 0.0250
    assert action.duration_seconds == 3.45

    # Verify relationships can be queried
    q_action = await db_session.get(AutonomousActionNode, action.id)
    assert q_action is not None
    assert q_action.production_job.id == job.id
    assert q_action.approval_checkpoint.id == checkpoint.id

    # Clean up test entities so conftest fixture teardown does not hit FK issues
    await db_session.delete(action)
    await db_session.delete(goal)
    await db_session.delete(checkpoint)
    await db_session.delete(wrun)
    await db_session.delete(job)
    await db_session.delete(shot)
    await db_session.delete(seq)
    await db_session.commit()


async def test_04_governance_decision_creation_and_links(
    db_session: AsyncSession, test_project: uuid.UUID
):
    """Verify GovernanceDecision model and links to Goal and ActionNode."""
    goal = AutonomousGoal(
        project_id=test_project,
        objective="Deploy automated publishing task",
        status="READY",
    )
    db_session.add(goal)
    await db_session.flush()

    action = AutonomousActionNode(
        goal_id=goal.id,
        client_action_id="act-publish-01",
        title="Auto-publish video teaser",
        action_type="EXTERNAL_ACTION",
        required_capability="PUBLISHING",
        status="READY",
        risk_level="HIGH",
    )
    db_session.add(action)
    await db_session.flush()

    decision = GovernanceDecision(
        project_id=test_project,
        goal_id=goal.id,
        action_node_id=action.id,
        verdict="REQUIRES_ESCALATION",
        risk_level="HIGH",
        policy_evaluations=[
            {"policy_id": "pol-no-unattended-publish", "passed": False, "rule": "require_operator_signoff"}
        ],
        reasons=["Direct external publishing blocked without explicit human checkpoint"],
    )
    db_session.add(decision)
    await db_session.commit()
    await db_session.refresh(decision)

    assert decision.id is not None
    assert decision.project_id == test_project
    assert decision.goal_id == goal.id
    assert decision.action_node_id == action.id
    assert decision.verdict == "REQUIRES_ESCALATION"
    assert len(decision.policy_evaluations) == 1
    assert decision.policy_evaluations[0]["policy_id"] == "pol-no-unattended-publish"


async def test_05_project_cascade_deletion(db_session: AsyncSession):
    """Verify that deleting a Project cascades to missions, goals, actions, and governance."""
    # Create isolated project
    proj = Project(name=f"cascade-test-{uuid.uuid4()}")
    db_session.add(proj)
    await db_session.flush()

    mission = Mission(
        project_id=proj.id,
        title="Cascade Mission",
        objective="Test Cascade",
    )
    db_session.add(mission)
    await db_session.flush()

    goal = AutonomousGoal(
        project_id=proj.id,
        mission_id=mission.id,
        objective="Cascade Goal",
    )
    db_session.add(goal)
    await db_session.flush()

    action = AutonomousActionNode(
        goal_id=goal.id,
        client_action_id="act-casc",
        title="Cascade Action",
        action_type="RESEARCH",
        required_capability="REASONING",
    )
    db_session.add(action)
    await db_session.flush()

    decision = GovernanceDecision(
        project_id=proj.id,
        goal_id=goal.id,
        action_node_id=action.id,
        verdict="APPROVED",
        risk_level="LOW",
    )
    db_session.add(decision)
    await db_session.commit()

    m_id, g_id, a_id, d_id = mission.id, goal.id, action.id, decision.id

    # Delete project
    await db_session.delete(proj)
    await db_session.commit()

    # Verify everything cascaded
    assert await db_session.get(Mission, m_id) is None
    assert await db_session.get(AutonomousGoal, g_id) is None
    assert await db_session.get(AutonomousActionNode, a_id) is None
    assert await db_session.get(GovernanceDecision, d_id) is None


async def test_06_mission_deletion_nulls_goal_mission_id(
    db_session: AsyncSession, test_project: uuid.UUID
):
    """Verify that deleting a Mission sets goal.mission_id to NULL without deleting the Goal."""
    mission = Mission(
        project_id=test_project,
        title="Temporary Mission",
        objective="Group goals temporarily",
    )
    db_session.add(mission)
    await db_session.flush()

    goal = AutonomousGoal(
        project_id=test_project,
        mission_id=mission.id,
        objective="Independent Goal that survives mission deletion",
    )
    db_session.add(goal)
    await db_session.commit()
    g_id = goal.id

    # Delete mission
    await db_session.delete(mission)
    await db_session.commit()

    # Query fresh from DB using populate_existing=True to refresh identity map without expiring other objects
    res = await db_session.execute(
        select(AutonomousGoal).where(AutonomousGoal.id == g_id).execution_options(populate_existing=True)
    )
    q_goal = res.scalar_one_or_none()

    # Goal must still exist with mission_id = None
    assert q_goal is not None
    assert q_goal.mission_id is None

    # Clean up goal
    await db_session.delete(q_goal)
    await db_session.commit()



async def test_07_foreign_key_violations_rejected(
    db_session: AsyncSession
):
    """Verify that invalid foreign keys fail with IntegrityError."""
    fake_id = uuid.uuid4()
    # Invalid project_id on mission
    bad_mission = Mission(
        project_id=fake_id,
        title="Bad Mission",
        objective="Should fail FK check",
    )
    db_session.add(bad_mission)
    with pytest.raises(IntegrityError):
        await db_session.commit()
    await db_session.rollback()

    # Invalid goal_id on action node
    bad_action = AutonomousActionNode(
        goal_id=fake_id,
        client_action_id="bad-act",
        title="Bad Action",
        action_type="RESEARCH",
        required_capability="REASONING",
    )
    db_session.add(bad_action)
    with pytest.raises(IntegrityError):
        await db_session.commit()
    await db_session.rollback()


async def test_08_pydantic_schema_validation():
    """Verify that Pydantic schemas enforce type safety and reject forbidden extras."""
    # Valid MissionCreate
    m = MissionCreate(
        title="New Mission",
        objective="Execute goal",
        priority="HIGH",
    )
    assert m.priority == "HIGH"

    # Extra fields forbidden
    with pytest.raises(ValidationError):
        MissionCreate(
            title="Bad Mission",
            objective="Obj",
            unknown_extra_field="malicious_payload",
        )

    # Invalid priority enum
    with pytest.raises(ValidationError):
        MissionCreate(
            title="Bad Mission",
            objective="Obj",
            priority="SUPER_URGENT",  # type: ignore
        )

    # Valid ActionNodeCreate
    a = AutonomousActionNodeCreate(
        client_action_id="act-01",
        title="Valid Action",
        action_type="RESEARCH",
        required_capability="REASONING",
        risk_level="MEDIUM",
    )
    assert a.action_type == "RESEARCH"

    # Invalid action_type
    with pytest.raises(ValidationError):
        AutonomousActionNodeCreate(
            client_action_id="act-02",
            title="Invalid Action",
            action_type="SELF_DESTRUCT",  # type: ignore
            required_capability="NONE",
        )


async def test_09_lifecycle_state_defaults(
    db_session: AsyncSession, test_project: uuid.UUID
):
    """Verify lifecycle state defaults: records never default to completed/successful."""
    m = Mission(project_id=test_project, title="M1", objective="Obj")
    g = AutonomousGoal(project_id=test_project, objective="Obj")
    db_session.add_all([m, g])
    await db_session.flush()

    a = AutonomousActionNode(
        goal_id=g.id,
        client_action_id="act-def",
        title="A1",
        action_type="RESEARCH",
        required_capability="REASONING",
    )
    db_session.add(a)
    await db_session.commit()

    assert m.status == "PLANNED"  # Never COMPLETED
    assert g.status == "DRAFT"    # Never COMPLETED
    assert a.status == "PENDING"  # Never SUCCEEDED


async def test_10_migration_head_is_h8c9d0e1f2a3(db_session: AsyncSession):
    """Verify that the database's current Alembic revision is at least h8c9d0e1f2a3."""
    res = await db_session.execute(text("SELECT version_num FROM alembic_version"))
    current_rev = res.scalar()
    assert current_rev in ("h8c9d0e1f2a3", "i9d0e1f2a3b4", "j0e1f2a3b4c5")
