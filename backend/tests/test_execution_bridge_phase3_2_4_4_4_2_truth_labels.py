"""
AryaOS Stage 25 — Phase 3.2.4.4.4.2 Operator Truth Label Tests.

Validates that goal completion summaries truthfully reflect authoritative execution state:
- Real external execution (e.g. Kling, Fal/Flux) is NOT labeled "(simulated)"
- Simulated / offline execution retains the truthful "(simulated)" label
- Real local execution (e.g. camera push FFmpeg) is labeled "(real local)"
- Ambiguous / UNKNOWN / non-SUCCEEDED executions strictly refuse false success labeling
"""

from __future__ import annotations

import uuid
from decimal import Decimal
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import AuthenticatedPrincipal
from app.models.core import Project
from app.models.execution_bridge import AutonomousActionNode, AutonomousGoal
from app.services.autonomous_execution_runner import (
    AutonomousExecutionRunner,
    derive_goal_completion_summary,
)
from app.services.dispatcher import (
    BaseExecutionDispatcher,
    ExecutionResult,
    OfflineMockDispatcher,
)

pytestmark = pytest.mark.asyncio(loop_scope="module")


async def test_01_real_external_execution_not_labeled_simulated():
    """Test 01: Real external provider execution is labeled '(real external)' and NEVER '(simulated)'."""
    # 1. Kling video external execution node
    kling_node = AutonomousActionNode(
        id=uuid.uuid4(),
        goal_id=uuid.uuid4(),
        client_action_id="shot_kling_001",
        title="Kling Video Generation",
        action_type="GENERATION",
        required_capability="VIDEO_GENERATION",
        status="SUCCEEDED",
        cost_usd=Decimal("0.1000"),
        inputs_json={
            "provider": "kling",
            "model": "kling-video/v3/standard",
            "dispatch_intent": {
                "provider_id": "openmontage-live",
                "provider_job_id": "01a11745-f136-7e33-85ff-decc80c5c134",
                "dispatch_state": "DISPATCH_COMMITTED",
            },
        },
        outputs_json={
            "provider": "kling",
            "model": "fal-ai/kling-video/v3/standard/text-to-video",
            "status": "SUCCEEDED",
            "request_id": "01a11745-f136-7e33-85ff-decc80c5c134",
            "provider_job_id": "01a11745-f136-7e33-85ff-decc80c5c134",
            "artifacts": ["/path/artifacts/video.mp4"],
        },
    )

    summary_kling = derive_goal_completion_summary([kling_node])
    assert "(simulated)" not in summary_kling
    assert "real external" in summary_kling
    assert summary_kling == "Goal completed successfully across 1 action nodes (real external)."

    # 2. Flux image external execution node
    flux_node = AutonomousActionNode(
        id=uuid.uuid4(),
        goal_id=uuid.uuid4(),
        client_action_id="shot_flux_001",
        title="Flux Image Generation",
        action_type="GENERATION",
        required_capability="IMAGE_GENERATION",
        status="SUCCEEDED",
        cost_usd=Decimal("0.0300"),
        inputs_json={
            "provider": "fal",
            "model": "flux/dev",
            "dispatch_intent": {
                "provider_id": "openmontage-live",
                "provider_job_id": "feaa745a-6fcb-4d43-bb92-0692a7e780dc",
                "dispatch_state": "DISPATCH_COMMITTED",
            },
        },
        outputs_json={
            "provider": "fal",
            "model": "flux/dev",
            "status": "SUCCEEDED",
            "request_id": "feaa745a-6fcb-4d43-bb92-0692a7e780dc",
            "artifacts": ["/path/artifacts/image.png"],
        },
    )

    summary_flux = derive_goal_completion_summary([flux_node])
    assert "(simulated)" not in summary_flux
    assert "real external" in summary_flux
    assert summary_flux == "Goal completed successfully across 1 action nodes (real external)."


async def test_02_real_local_execution_labeled_real_local():
    """Test 02: Real local execution (FFmpeg camera push) is labeled '(real local)' and NEVER '(simulated)'."""
    local_node = AutonomousActionNode(
        id=uuid.uuid4(),
        goal_id=uuid.uuid4(),
        client_action_id="shot_local_001",
        title="Camera Push Local Generation",
        action_type="GENERATION",
        required_capability="VIDEO_GENERATION",
        status="SUCCEEDED",
        cost_usd=Decimal("0.0000"),
        inputs_json={
            "provider": "camera_motion",
            "dispatch_intent": {
                "provider_id": "openmontage-live",
                "dispatch_state": "DISPATCH_COMMITTED",
            },
        },
        outputs_json={
            "provider": "camera_motion",
            "status": "SUCCEEDED",
            "video_url": "/path/artifacts/camera_push.mp4",
            "format": "mp4",
            "artifacts": ["/path/artifacts/camera_push.mp4"],
        },
    )

    summary_local = derive_goal_completion_summary([local_node])
    assert "(simulated)" not in summary_local
    assert "real local" in summary_local
    assert summary_local == "Goal completed successfully across 1 action nodes (real local)."


async def test_03_simulated_execution_retains_simulated_label():
    """Test 03: Offline simulated execution strictly retains its truthful '(simulated)' label."""
    mock_node = AutonomousActionNode(
        id=uuid.uuid4(),
        goal_id=uuid.uuid4(),
        client_action_id="shot_mock_001",
        title="Mock Offline Generation",
        action_type="GENERATION",
        required_capability="IMAGE_GENERATION",
        status="SUCCEEDED",
        cost_usd=Decimal("0.0000"),
        inputs_json={
            "dispatch_intent": {
                "provider_id": "offline-mock",
                "dispatch_state": "DISPATCH_COMMITTED",
            },
        },
        outputs_json={
            "is_simulated": True,
            "mock_mode": True,
            "simulated_provider": "mock-provider-offline",
            "status": "SUCCEEDED",
        },
    )

    summary_mock = derive_goal_completion_summary([mock_node])
    assert "(simulated)" in summary_mock
    assert summary_mock == "Goal completed successfully across 1 action nodes (simulated)."


async def test_04_unknown_execution_cannot_be_labeled_as_successful_real_execution():
    """Test 04: UNKNOWN or ambiguous executions fail closed and refuse false success labeling."""
    unknown_node = AutonomousActionNode(
        id=uuid.uuid4(),
        goal_id=uuid.uuid4(),
        client_action_id="shot_ambiguous_001",
        title="Ambiguous Execution",
        action_type="GENERATION",
        required_capability="VIDEO_GENERATION",
        status="UNKNOWN_PENDING_RECONCILIATION",
        cost_usd=Decimal("0.1000"),
        outputs_json={
            "status": "UNKNOWN_PENDING_RECONCILIATION",
            "is_ambiguous": True,
        },
    )

    with pytest.raises(ValueError) as exc_unknown:
        derive_goal_completion_summary([unknown_node])
    assert "UNKNOWN" in str(exc_unknown.value) or "non-SUCCEEDED" in str(exc_unknown.value)

    failed_node = AutonomousActionNode(
        id=uuid.uuid4(),
        goal_id=uuid.uuid4(),
        client_action_id="shot_failed_001",
        title="Failed Execution",
        action_type="GENERATION",
        required_capability="VIDEO_GENERATION",
        status="FAILED",
        cost_usd=Decimal("0.0000"),
        outputs_json={"status": "FAILED", "error": "Fatal crash"},
    )

    with pytest.raises(ValueError) as exc_failed:
        derive_goal_completion_summary([failed_node])
    assert "non-SUCCEEDED" in str(exc_failed.value)


async def test_05_runner_end_to_end_sets_truthful_goal_summary_on_completion(
    db_session: AsyncSession,
):
    """Test 05: AutonomousExecutionRunner produces truthful goal summaries end-to-end for both modes."""
    # Part 1: Offline simulated execution produces (simulated)
    project = Project(name="Truth Label Test Project")
    db_session.add(project)
    await db_session.flush()

    principal = AuthenticatedPrincipal(
        api_key_id=uuid.uuid4(),
        name="Truth Auditor",
        is_admin=True,
        principal_type="system",
    )

    goal_sim = AutonomousGoal(
        project_id=project.id,
        objective="Simulated Goal Run",
        status="EXECUTING",
        plan_dag_json={"nodes": [{"client_action_id": "act_sim_01"}]},
    )
    db_session.add(goal_sim)
    await db_session.flush()

    action_sim = AutonomousActionNode(
        goal_id=goal_sim.id,
        client_action_id="act_sim_01",
        title="Simulated Action",
        action_type="GENERATION",
        required_capability="IMAGE_GENERATION",
        status="READY",
        inputs_json={"prompt": "Test mock"},
    )
    db_session.add(action_sim)
    await db_session.commit()

    runner_sim = AutonomousExecutionRunner(
        db=db_session,
        dispatcher=OfflineMockDispatcher(),
        worker_id="sim-worker-01",
    )
    await runner_sim.dispatch_action(action_sim.id, principal)

    await db_session.refresh(goal_sim)
    assert goal_sim.status == "COMPLETED"
    assert "(simulated)" in goal_sim.final_summary

    # Part 2: Real external dispatch mock produces (real external) and NOT (simulated)
    goal_real = AutonomousGoal(
        project_id=project.id,
        objective="Real External Goal Run",
        status="EXECUTING",
        plan_dag_json={"nodes": [{"client_action_id": "act_real_01"}]},
    )
    db_session.add(goal_real)
    await db_session.flush()

    action_real = AutonomousActionNode(
        goal_id=goal_real.id,
        client_action_id="act_real_01",
        title="Real External Action",
        action_type="GENERATION",
        required_capability="VIDEO_GENERATION",
        status="READY",
        inputs_json={"prompt": "Astrolabe", "provider": "kling"},
    )
    db_session.add(action_real)
    await db_session.commit()

    class MockRealExternalDispatcher(BaseExecutionDispatcher):
        is_live: bool = False  # Avoids network calls during unit test
        provider_name: str = "openmontage-live"

        async def dispatch(self, action: AutonomousActionNode) -> ExecutionResult:
            return ExecutionResult(
                success=True,
                status="SUCCEEDED",
                cost_usd=0.1000,
                duration_seconds=5.2,
                provider_job_id="01a11745-f136-7e33-85ff-decc80c5c134",
                output={
                    "is_simulated": False,
                    "provider": "kling",
                    "status": "SUCCEEDED",
                    "request_id": "01a11745-f136-7e33-85ff-decc80c5c134",
                    "provider_job_id": "01a11745-f136-7e33-85ff-decc80c5c134",
                    "skip_artifact_validation": True,
                },
            )

    runner_real = AutonomousExecutionRunner(
        db=db_session,
        dispatcher=MockRealExternalDispatcher(),
        worker_id="real-mock-worker-01",
    )
    await runner_real.dispatch_action(action_real.id, principal)

    await db_session.refresh(goal_real)
    assert goal_real.status == "COMPLETED"
    assert "(simulated)" not in goal_real.final_summary
    assert "real external" in goal_real.final_summary
    assert goal_real.final_summary == "Goal completed successfully across 1 action nodes (real external)."
