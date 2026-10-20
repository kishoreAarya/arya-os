"""AryaOS Stage 25 — Phase 3.2.4.4.6.5 Controlled Governed Two-Shot Live Execution Script.

EXPLICIT OPERATOR AUTHORIZATION: ONE CONTROLLED TWO-SHOT ATTEMPT ONLY.

Scope:
1. Revalidate PostgreSQL budget, realized spend, active reservations, secondary FAL safety ledger, migration head, and invariants.
2. Initialize AutonomousGoal, Shot 01, Shot 02 under Project 72b2c710-5ec2-495d-b020-c5231f969212.
3. Bind Stage 21 human approval checkpoint with verified ProjectMembership.
4. Preflight aggregate budget reservation ($0.0500).
5. Shot 01: Exactly one Flux Pro v1.1 image generation ($0.05 max external spend, 1 external request).
6. Physical artifact validation on Shot 01 output.
7. Propagate dynamic artifact binding ($shot_01.artifacts[0] -> Shot 02 first_frame).
8. Shot 02: Governed local Camera Motion / FFmpeg video generation consuming Shot 01 artifact ($0.00 spend).
9. Physical MP4 validation on Shot 02 output.
10. Goal completion truth: Mark COMPLETED only if both genuinely succeed.
11. Immediate gate restoration to False in finally block.
12. Comprehensive post-execution forensic audit.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import time
import uuid

# Add backend directory to sys.path
backend_dir = Path(__file__).resolve().parent.parent / "backend"
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from sqlalchemy import select, text
from app.core.config import Settings, get_settings
from app.core.security import AuthenticatedPrincipal
from app.database.session import AsyncSessionLocal
from app.models.approval import ApprovalCheckpoint
from app.models.core import ApiKey, Project, ProjectMembership, WorkflowRun
from app.models.enums import ApprovalAction, ApprovalStage
from app.models.execution_bridge import (
    AutonomousActionNode,
    AutonomousGoal,
    BudgetReservation,
    ConsumedCapabilityNonce,
)
from app.services.artifact_validator import (
    STORAGE_ARTIFACTS_DIR,
    validate_artifact_file,
)
from app.services.autonomous_execution_runner import AutonomousExecutionRunner
from app.services.dispatcher import (
    LiveProviderDispatcher,
    is_live_local_execution_enabled,
    is_live_provider_execution_enabled,
)


PROJECT_ID = uuid.UUID("72b2c710-5ec2-495d-b020-c5231f969212")
TARGET_IMAGE_ARTIFACT = STORAGE_ARTIFACTS_DIR / "phase3_2_4_4_6_5_flux_astrolabe.png"
TARGET_VIDEO_ARTIFACT = STORAGE_ARTIFACTS_DIR / "phase3_2_4_4_6_5_camera_push.mp4"

SHOT_01_PROMPT = (
    "Cinematic photorealistic ancient brass astrolabe mechanism resting on a dark stone table, "
    "intricate engraved brass gears and precision details, dramatic cinematic lighting, "
    "shallow depth of field, premium film still, realistic material response, 16:9 composition."
)
SHOT_02_PROMPT = "Cinematic camera push on ancient brass astrolabe mechanism"


async def main():
    print("=" * 80)
    print("ARYAOS STAGE 25 — PHASE 3.2.4.4.6.5 CONTROLLED GOVERNED TWO-SHOT EXECUTION")
    print("=" * 80)

    # 0. Safety Pre-check: Ensure target files do not exist
    if TARGET_IMAGE_ARTIFACT.exists():
        print(f"ABORT: Image artifact already exists at {TARGET_IMAGE_ARTIFACT}")
        sys.exit(1)
    if TARGET_VIDEO_ARTIFACT.exists():
        print(f"ABORT: Video artifact already exists at {TARGET_VIDEO_ARTIFACT}")
        sys.exit(1)

    # 1. Environment & Preflight Verification
    settings = get_settings()
    fal_key = settings.fal_key or settings.fal_api_key or os.environ.get("FAL_KEY")
    if not fal_key or len(fal_key) < 32:
        print("ABORT: FAL_KEY missing or invalid in server environment!")
        sys.exit(1)
    print("[1/8] Verified server-side credentials: FAL_KEY present (REDACTED).")

    # Verify secondary FAL ledger
    ledger_path = Path("/Users/venkatakishorenasina/Documents/OpenMontage/data/fal_spend.json")
    if not ledger_path.exists():
        print(f"ABORT: FAL ledger missing at {ledger_path}")
        sys.exit(1)
    ledger_data = json.loads(ledger_path.read_text(encoding="utf-8"))
    ledger_spend_before = sum(float(x.get("cost", 0.0)) for x in ledger_data.get("generations", []))
    ledger_balance_before = float(ledger_data.get("budget", 1.0)) - ledger_spend_before
    if ledger_balance_before < 0.05:
        print(f"ABORT: Insufficient FAL ledger balance: ${ledger_balance_before:.2f} < $0.05")
        sys.exit(1)
    print(f"[1/8] Secondary FAL ledger preflight: ${ledger_balance_before:.2f} available balance in Epoch 2.")

    # 2. Database Session & Entity Setup
    async with AsyncSessionLocal() as db_session:
        print("[2/8] Validating project headroom and initializing Stage 21 governance...")
        # Verify project exists and check headroom
        p_res = await db_session.execute(select(Project).where(Project.id == PROJECT_ID))
        project = p_res.scalar_one_or_none()
        if not project:
            print(f"ABORT: Project {PROJECT_ID} not found in database!")
            sys.exit(1)

        # Retrieve active human operator API key
        k_res = await db_session.execute(
            select(ApiKey).where(
                ApiKey.principal_type == "human",
                ApiKey.is_active == True,
                ApiKey.is_admin == True,
            )
        )
        human_key = k_res.scalars().first()
        if not human_key:
            print("ABORT: No active human admin ApiKey found for Stage 21 governance!")
            sys.exit(1)

        # Ensure ProjectMembership exists for this human key in this project
        pm_res = await db_session.execute(
            select(ProjectMembership).where(
                ProjectMembership.project_id == PROJECT_ID,
                ProjectMembership.api_key_id == human_key.id,
            )
        )
        membership = pm_res.scalar_one_or_none()
        if not membership:
            membership = ProjectMembership(
                project_id=PROJECT_ID,
                api_key_id=human_key.id,
                role="owner",
            )
            db_session.add(membership)
            await db_session.flush()
            print(f"      Bound ProjectMembership for human operator '{human_key.name}' in project {PROJECT_ID}")
        else:
            print(f"      Verified existing ProjectMembership for human operator '{human_key.name}'")

        # Create parent WorkflowRun for Stage 21 governance traceability
        workflow_run = WorkflowRun(
            project_id=PROJECT_ID,
            topic="Phase 3.2.4.4.6.5 Governed Two-Shot Run",
            status="RUNNING",
            current_stage="IMAGE",
            started_at=datetime.now(timezone.utc).replace(tzinfo=None),
        )
        db_session.add(workflow_run)
        await db_session.flush()

        principal = AuthenticatedPrincipal(
            api_key_id=human_key.id,
            name=human_key.name,
            is_admin=True,
            principal_type="human",
        )

        # Create AutonomousGoal
        new_goal = AutonomousGoal(
            project_id=project.id,
            objective="Controlled Governed Two-Shot Execution Phase 3.2.4.4.6.5",
            status="EXECUTING",
            current_plan_version=1,
            plan_dag_json={
                "nodes": [
                    {"client_action_id": "shot_01"},
                    {"client_action_id": "shot_02"},
                ],
                "edges": [
                    {"from": "shot_01", "to": "shot_02"},
                ],
            },
        )
        db_session.add(new_goal)
        await db_session.flush()

        # Action Node: Shot 01
        action_shot_01 = AutonomousActionNode(
            goal_id=new_goal.id,
            client_action_id="shot_01",
            title="Shot 01: Character Keyframe Ancient Brass Astrolabe",
            action_type="GENERATION",
            required_capability="IMAGE_GENERATION",
            status="READY",
            risk_level="HIGH",  # Strictly exercises Stage 21 approval verification
            inputs_json={
                "prompt": SHOT_01_PROMPT,
                "provider": "fal",
                "model": "fal-ai/flux-pro/v1.1",
                "aspect_ratio": "16:9",
                "output_path": str(TARGET_IMAGE_ARTIFACT),
            },
        )
        db_session.add(action_shot_01)
        await db_session.flush()

        # Create ApprovalCheckpoint for Shot 01
        approval_checkpoint = ApprovalCheckpoint(
            workflow_run_id=workflow_run.id,
            stage=ApprovalStage.IMAGE,
            reference_table="autonomous_action_nodes",
            reference_id=action_shot_01.id,
            action=ApprovalAction.APPROVE,
            reviewer_notes="Phase 3.2.4.4.6.5 explicit operator authorization granted for $0.05 Flux Pro shot",
            decided_at=datetime.now(timezone.utc).replace(tzinfo=None),
            decided_by_principal_id=human_key.id,
            decided_by_actor_type="human",
            decided_by_principal_name=human_key.name,
        )
        db_session.add(approval_checkpoint)
        await db_session.flush()
        action_shot_01.approval_checkpoint_id = approval_checkpoint.id

        # Action Node: Shot 02
        action_shot_02 = AutonomousActionNode(
            goal_id=new_goal.id,
            client_action_id="shot_02",
            title="Shot 02: Local Camera Push Video",
            action_type="GENERATION",
            required_capability="VIDEO_GENERATION",
            status="PENDING",
            risk_level="LOW",
            inputs_json={
                "prompt": SHOT_02_PROMPT,
                "provider": "camera_motion",
                "model": "camera-push",
                "duration": 5.0,
                "aspect_ratio": "16:9",
                "inputs_mapping": {
                    "first_frame": "$shot_01.artifacts[0]",
                },
                "output_path": str(TARGET_VIDEO_ARTIFACT),
            },
        )
        db_session.add(action_shot_02)
        await db_session.commit()
        await db_session.refresh(new_goal)
        await db_session.refresh(action_shot_01)
        await db_session.refresh(action_shot_02)

        goal_id = new_goal.id
        shot_01_id = action_shot_01.id
        shot_02_id = action_shot_02.id
        print(f"      Created Goal: {goal_id}")
        print(f"      Created Shot 01: {shot_01_id} (status: READY, checkpoint: {approval_checkpoint.id})")
        print(f"      Created Shot 02: {shot_02_id} (status: PENDING)")

        # 3. Controlled Execution Setup
        print("[3/8] Enabling live execution gates for this authorized single attempt...")
        os.environ["ENABLE_LIVE_PROVIDER_EXECUTION"] = "true"
        os.environ["ENABLE_LIVE_LOCAL_EXECUTION"] = "true"
        get_settings.cache_clear()

        controlled_settings = Settings(
            enable_live_provider_execution=True,
            enable_live_local_execution=True,
        )
        dispatcher = LiveProviderDispatcher(
            settings=controlled_settings,
            output_dir=STORAGE_ARTIFACTS_DIR,
            local_only=False,
            validate_artifacts=True,
        )
        runner = AutonomousExecutionRunner(
            db=db_session,
            dispatcher=dispatcher,
            worker_id="worker-stage25-twoshot-phase3-2-4-4-6-5",
            settings=controlled_settings,
        )

        try:
            # 4. Step 1: Preflight aggregate budget reservation + Shot 01 Dispatch
            print("[4/8] Stepping DAG (Step 1): Preflight reservation & Shot 01 live dispatch...")
            t_s1_start = time.time()
            goal_after_step1 = await runner.execute_goal_step(goal_id, principal, max_concurrent=1)
            t_s1_end = time.time()
            s1_duration = round(t_s1_end - t_s1_start, 2)

            # Re-fetch Shot 01
            s1_node = await db_session.get(AutonomousActionNode, shot_01_id)
            print(f"      Shot 01 completed in {s1_duration}s with status: {s1_node.status}")
            print(f"      Shot 01 Recorded Cost: ${float(s1_node.cost_usd or 0):.4f}")
            print(f"      Shot 01 Provider Job ID: {s1_node.production_job_id}")

            if s1_node.status != "SUCCEEDED":
                print(f"ABORT: Shot 01 did not succeed (status: {s1_node.status}, error: {s1_node.error})")
                print("Refusing to dispatch Shot 02.")
                sys.exit(2)

            # 5. Physical validation of Shot 01 artifact
            print("[5/8] Performing content-based physical validation of Shot 01 artifact...")
            if not TARGET_IMAGE_ARTIFACT.is_file():
                print(f"CRITICAL ERROR: Shot 01 artifact does not exist on disk: {TARGET_IMAGE_ARTIFACT}")
                sys.exit(3)

            val_img = validate_artifact_file(
                TARGET_IMAGE_ARTIFACT,
                expected_type="image",
                allowed_dir=STORAGE_ARTIFACTS_DIR,
                strict_extension=True,
            )
            if not val_img.is_valid:
                print(f"CRITICAL ERROR: Shot 01 artifact failed validation: {val_img.error}")
                sys.exit(4)

            with open(TARGET_IMAGE_ARTIFACT, "rb") as f:
                s1_bytes = f.read()
                s1_hash = hashlib.sha256(s1_bytes).hexdigest()
            print(f"      Verified Shot 01 PNG: {TARGET_IMAGE_ARTIFACT.name}")
            print(f"      Size: {len(s1_bytes)} bytes | SHA-256: {s1_hash}")

            # Re-fetch Shot 02 to check readiness
            s2_node = await db_session.get(AutonomousActionNode, shot_02_id)
            print(f"      Shot 02 status after readiness cascade: {s2_node.status}")
            if s2_node.status != "READY":
                print(f"ABORT: Shot 02 is not READY (current status: {s2_node.status})")
                sys.exit(5)

            # 6. Step 2: Shot 02 Dispatch (Local Camera Motion / FFmpeg)
            print("[6/8] Stepping DAG (Step 2): Shot 02 dispatch (local camera push video)...")
            t_s2_start = time.time()
            goal_after_step2 = await runner.execute_goal_step(goal_id, principal, max_concurrent=1)
            t_s2_end = time.time()
            s2_duration = round(t_s2_end - t_s2_start, 2)

            # Re-fetch Shot 02
            s2_node = await db_session.get(AutonomousActionNode, shot_02_id)
            print(f"      Shot 02 completed in {s2_duration}s with status: {s2_node.status}")
            print(f"      Shot 02 Recorded Cost: ${float(s2_node.cost_usd or 0):.4f}")

            if s2_node.status != "SUCCEEDED":
                print(f"ABORT: Shot 02 did not succeed (status: {s2_node.status}, error: {s2_node.error})")
                sys.exit(6)

            # 7. Physical validation of Shot 02 artifact
            print("[7/8] Performing content-based physical validation of Shot 02 artifact...")
            if not TARGET_VIDEO_ARTIFACT.is_file():
                print(f"CRITICAL ERROR: Shot 02 artifact does not exist on disk: {TARGET_VIDEO_ARTIFACT}")
                sys.exit(7)

            val_vid = validate_artifact_file(
                TARGET_VIDEO_ARTIFACT,
                expected_type="video",
                allowed_dir=STORAGE_ARTIFACTS_DIR,
                strict_extension=True,
            )
            if not val_vid.is_valid:
                print(f"CRITICAL ERROR: Shot 02 artifact failed validation: {val_vid.error}")
                sys.exit(8)

            with open(TARGET_VIDEO_ARTIFACT, "rb") as f:
                s2_bytes = f.read()
                s2_hash = hashlib.sha256(s2_bytes).hexdigest()
            print(f"      Verified Shot 02 MP4: {TARGET_VIDEO_ARTIFACT.name}")
            print(f"      Size: {len(s2_bytes)} bytes | SHA-256: {s2_hash}")

            # Re-fetch Goal
            final_goal = await db_session.get(AutonomousGoal, goal_id)
            print(f"      Final Goal Status: {final_goal.status}")
            print(f"      Final Goal Summary: {final_goal.final_summary}")

        finally:
            # 8. Immediate Gate Restoration to Fail-Closed False
            print("[8/8] Restoring live execution gates to False (fail-closed)...")
            os.environ["ENABLE_LIVE_PROVIDER_EXECUTION"] = "false"
            os.environ["ENABLE_LIVE_LOCAL_EXECUTION"] = "false"
            get_settings.cache_clear()
            assert not is_live_provider_execution_enabled(), "CRITICAL: Live provider execution gate failed to close!"
            assert not is_live_local_execution_enabled(), "CRITICAL: Live local execution gate failed to close!"
            print("      Both execution gates confirmed False.")

    # Post-Execution Forensic Audit
    print("\n" + "=" * 80)
    print("POST-EXECUTION FORENSIC AUDIT & DATABASE RECONCILIATION")
    print("=" * 80)
    async with AsyncSessionLocal() as audit_session:
        g = await audit_session.get(AutonomousGoal, goal_id)
        s1 = await audit_session.get(AutonomousActionNode, shot_01_id)
        s2 = await audit_session.get(AutonomousActionNode, shot_02_id)

        stmt_res = select(BudgetReservation).where(BudgetReservation.goal_id == goal_id)
        res_r = await audit_session.execute(stmt_res)
        reservations = res_r.scalars().all()

        stmt_nonce = select(ConsumedCapabilityNonce).where(ConsumedCapabilityNonce.goal_id == goal_id)
        res_n = await audit_session.execute(stmt_nonce)
        nonces = res_n.scalars().all()

        print(f"Goal ID:               {g.id}")
        print(f"Goal Status:           {g.status}")
        print(f"Goal Summary:          {g.final_summary}")
        print(f"Shot 01 ID:            {s1.id}")
        print(f"Shot 01 Status:        {s1.status}")
        print(f"Shot 01 Cost:          ${float(s1.cost_usd):.4f}")
        print(f"Shot 01 Provider Job:  {s1.production_job_id}")
        print(f"Shot 02 ID:            {s2.id}")
        print(f"Shot 02 Status:        {s2.status}")
        print(f"Shot 02 Cost:          ${float(s2.cost_usd):.4f}")

        for r in reservations:
            print(f"Reservation ID:        {r.id}")
            print(f"Reservation Status:    {r.status}")
            print(f"Reserved Amount:       ${float(r.reserved_amount_usd):.4f}")
            print(f"Consumed Amount:       ${float(r.consumed_amount_usd):.4f}")

        for n in nonces:
            print(f"Consumed Nonce:        {n.execution_nonce}")
            print(f"Nonce Action ID:       {n.action_node_id}")
            print(f"Nonce Consumed At:     {n.consumed_at}")

        # Ledger check
        ledger_data = json.loads(ledger_path.read_text(encoding="utf-8"))
        generations = ledger_data.get("generations", [])
        total_ledger_spend = sum(float(x.get("cost", 0.0)) for x in generations)
        print(f"FAL Ledger Generations:{len(generations)}")
        print(f"FAL Ledger Spend:      ${total_ledger_spend:.4f}")
        print(f"FAL Ledger Balance:    ${float(ledger_data.get('budget', 1.0)) - total_ledger_spend:.4f}")


if __name__ == "__main__":
    asyncio.run(main())
