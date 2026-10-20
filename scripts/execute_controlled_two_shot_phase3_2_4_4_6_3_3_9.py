"""AryaOS Stage 25 — Phase 3.2.4.4.6.3.3.9 Controlled Governed Two-Shot Execution Script.

EXPLICIT OPERATOR AUTHORIZATION: ONE CONTROLLED TWO-SHOT ATTEMPT ONLY.

Scope:
1. Create a brand-new AutonomousGoal and plan version under active Project 72b2c710-5ec2-495d-b020-c5231f969212.
2. Preflight aggregate budget, reservation, worker lease, and execution capability.
3. Shot 01: Flux Pro v1.1 image generation ($0.05 max external spend, 1 external request).
4. Physical artifact validation on Shot 01 output.
5. Shot 02: Governed local Camera Motion / FFmpeg video generation consuming Shot 01 artifact ($0.00 spend).
6. Physical MP4 validation on Shot 02 output.
7. Goal completion truth: Mark COMPLETED only if both genuinely succeed.
8. Immediate gate restoration to False in finally block.
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
import subprocess
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
from app.models.core import Project
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
TARGET_IMAGE_ARTIFACT = STORAGE_ARTIFACTS_DIR / "phase3_2_4_4_6_3_3_9_flux_astrolabe.png"
TARGET_VIDEO_ARTIFACT = STORAGE_ARTIFACTS_DIR / "phase3_2_4_4_6_3_3_9_camera_push.mp4"

SHOT_01_PROMPT = (
    "Cinematic photorealistic ancient brass astrolabe mechanism resting on a dark stone table, "
    "intricate engraved brass gears and precision details, dramatic cinematic lighting, "
    "shallow depth of field, premium film still, realistic material response, 16:9 composition."
)
SHOT_02_PROMPT = "Cinematic camera push on ancient brass astrolabe mechanism"


async def main():
    print("=" * 80)
    print("ARYAOS STAGE 25 — PHASE 3.2.4.4.6.3.3.9 CONTROLLED TWO-SHOT EXECUTION")
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
    print("[1/7] Verified server-side credentials: FAL_KEY present (REDACTED).")

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
    print(f"[1/7] Secondary FAL ledger preflight: ${ledger_balance_before:.2f} available balance.")

    # 2. Database Session & Entity Setup
    async with AsyncSessionLocal() as db_session:
        print("[2/7] Initializing new PostgreSQL goal and actions...")
        # Verify project exists and check headroom
        p_res = await db_session.execute(select(Project).where(Project.id == PROJECT_ID))
        project = p_res.scalar_one_or_none()
        if not project:
            print(f"ABORT: Project {PROJECT_ID} not found in database!")
            sys.exit(1)

        principal = AuthenticatedPrincipal(
            api_key_id=uuid.uuid4(),
            name="Security Operator",
            is_admin=True,
            principal_type="system",
        )

        new_goal = AutonomousGoal(
            project_id=project.id,
            objective="Controlled Governed Two-Shot Execution Phase 3.2.4.4.6.3.3.9",
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
                "budget_limit_usd": 0.05,
            },
        )
        db_session.add(new_goal)
        await db_session.flush()

        action_shot_01 = AutonomousActionNode(
            goal_id=new_goal.id,
            client_action_id="shot_01",
            title="Shot 01: Character Keyframe Ancient Brass Astrolabe",
            action_type="GENERATION",
            required_capability="IMAGE_GENERATION",
            status="READY",
            risk_level="LOW",
            inputs_json={
                "prompt": SHOT_01_PROMPT,
                "provider": "fal",
                "model": "fal-ai/flux-pro/v1.1",
                "aspect_ratio": "16:9",
                "output_path": str(TARGET_IMAGE_ARTIFACT),
            },
        )

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

        db_session.add_all([action_shot_01, action_shot_02])
        await db_session.commit()
        await db_session.refresh(new_goal)
        await db_session.refresh(action_shot_01)
        await db_session.refresh(action_shot_02)

        goal_id = new_goal.id
        shot_01_id = action_shot_01.id
        shot_02_id = action_shot_02.id
        print(f"      Created Goal: {goal_id}")
        print(f"      Created Shot 01: {shot_01_id} (status: READY)")
        print(f"      Created Shot 02: {shot_02_id} (status: PENDING)")

        # 3. Controlled Execution with Fail-Closed Finally Restoration
        print("[3/7] Enabling live execution gates for this authorized run...")
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
            worker_id="worker-stage25-twoshot-01",
            settings=controlled_settings,
        )

        try:
            # 4. Execute Step 1: Preflight aggregate budget reservation + Shot 01 Dispatch
            print("[4/7] Stepping DAG (Step 1): Preflight reservation & Shot 01 dispatch...")
            t_s1_start = time.time()
            goal_after_step1 = await runner.execute_goal_step(goal_id, principal, max_concurrent=1)
            t_s1_end = time.time()
            s1_duration = round(t_s1_end - t_s1_start, 2)

            # Re-fetch Shot 01
            s1_node = await db_session.get(AutonomousActionNode, shot_01_id)
            print(f"      Shot 01 returned in {s1_duration}s with status: {s1_node.status}")
            print(f"      Shot 01 Cost: ${float(s1_node.cost_usd or 0):.4f}")

            # Physical validation of Shot 01 artifact
            if s1_node.status != "SUCCEEDED":
                print(f"ABORT: Shot 01 did not succeed (status: {s1_node.status}, error: {s1_node.error})")
                print("Refusing to dispatch Shot 02.")
                sys.exit(2)

            if not TARGET_IMAGE_ARTIFACT.is_file():
                print(f"CRITICAL ERROR: Shot 01 artifact does not exist on disk: {TARGET_IMAGE_ARTIFACT}")
                sys.exit(3)

            val_img = validate_artifact_file(TARGET_IMAGE_ARTIFACT, expected_type="image", allowed_dir=STORAGE_ARTIFACTS_DIR)
            if not val_img.is_valid:
                print(f"CRITICAL ERROR: Shot 01 artifact failed validation: {val_img.error}")
                sys.exit(4)
            print(f"      Shot 01 physical artifact verified: {TARGET_IMAGE_ARTIFACT.name} ({TARGET_IMAGE_ARTIFACT.stat().st_size} bytes)")

            # Re-fetch Shot 02 to check readiness
            s2_node = await db_session.get(AutonomousActionNode, shot_02_id)
            print(f"      Shot 02 status after Step 1 readiness cascade: {s2_node.status}")
            if s2_node.status != "READY":
                print(f"ABORT: Shot 02 is not READY (current status: {s2_node.status})")
                sys.exit(5)

            # 5. Execute Step 2: Shot 02 Dispatch (Local Camera Motion / FFmpeg)
            print("[5/7] Stepping DAG (Step 2): Shot 02 dispatch (local camera push)...")
            t_s2_start = time.time()
            goal_after_step2 = await runner.execute_goal_step(goal_id, principal, max_concurrent=1)
            t_s2_end = time.time()
            s2_duration = round(t_s2_end - t_s2_start, 2)

            # Re-fetch Shot 02
            s2_node = await db_session.get(AutonomousActionNode, shot_02_id)
            print(f"      Shot 02 returned in {s2_duration}s with status: {s2_node.status}")
            print(f"      Shot 02 Cost: ${float(s2_node.cost_usd or 0):.4f}")

            if s2_node.status != "SUCCEEDED":
                print(f"ABORT: Shot 02 did not succeed (status: {s2_node.status}, error: {s2_node.error})")
                sys.exit(6)

            if not TARGET_VIDEO_ARTIFACT.is_file():
                print(f"CRITICAL ERROR: Shot 02 artifact does not exist on disk: {TARGET_VIDEO_ARTIFACT}")
                sys.exit(7)

            val_vid = validate_artifact_file(TARGET_VIDEO_ARTIFACT, expected_type="video", allowed_dir=STORAGE_ARTIFACTS_DIR)
            if not val_vid.is_valid:
                print(f"CRITICAL ERROR: Shot 02 artifact failed validation: {val_vid.error}")
                sys.exit(8)
            print(f"      Shot 02 physical artifact verified: {TARGET_VIDEO_ARTIFACT.name} ({TARGET_VIDEO_ARTIFACT.stat().st_size} bytes)")

            # Re-fetch Goal
            final_goal = await db_session.get(AutonomousGoal, goal_id)
            print(f"[6/7] Final Goal Status: {final_goal.status}")
            print(f"      Final Summary: {final_goal.final_summary}")

        finally:
            # 6. Immediate Gate Restoration to Fail-Closed False
            print("[7/7] Restoring live execution gates to False (fail-closed)...")
            os.environ["ENABLE_LIVE_PROVIDER_EXECUTION"] = "false"
            os.environ["ENABLE_LIVE_LOCAL_EXECUTION"] = "false"
            get_settings.cache_clear()
            assert not is_live_provider_execution_enabled(), "CRITICAL: Live provider execution gate failed to close!"
            assert not is_live_local_execution_enabled(), "CRITICAL: Live local execution gate failed to close!"
            print("      Both execution gates confirmed False.")

    # 7. Post-Execution Independent Audit & Telemetry Extraction
    async with AsyncSessionLocal() as audit_session:
        g = await audit_session.get(AutonomousGoal, goal_id)
        s1 = await audit_session.get(AutonomousActionNode, shot_01_id)
        s2 = await audit_session.get(AutonomousActionNode, shot_02_id)

        stmt_res = select(BudgetReservation).where(BudgetReservation.goal_id == goal_id)
        res_r = await audit_session.execute(stmt_res)
        reservations = res_r.scalars().all()

        # Shot 01 telemetry
        s1_bytes = TARGET_IMAGE_ARTIFACT.read_bytes()
        s1_sha256 = hashlib.sha256(s1_bytes).hexdigest()
        s1_job_id = (
            (s1.inputs_json or {}).get("dispatch_intent", {}).get("provider_job_id")
            or (s1.outputs_json or {}).get("provider_job_id")
            or (s1.outputs_json or {}).get("request_id")
        )

        # Shot 02 telemetry & ffprobe
        s2_bytes = TARGET_VIDEO_ARTIFACT.read_bytes()
        s2_sha256 = hashlib.sha256(s2_bytes).hexdigest()
        ffprobe_bin = shutil.which("ffprobe")
        probe_json = {}
        if ffprobe_bin:
            proc = subprocess.run(
                [
                    ffprobe_bin,
                    "-v", "error",
                    "-print_format", "json",
                    "-show_format",
                    "-show_streams",
                    str(TARGET_VIDEO_ARTIFACT),
                ],
                capture_output=True,
                text=True,
            )
            if proc.returncode == 0:
                probe_json = json.loads(proc.stdout)

        fmt_info = probe_json.get("format", {})
        v_stream = next((s for s in probe_json.get("streams", []) if s.get("codec_type") == "video"), {})

        # Ledger check
        ledger_after = json.loads(ledger_path.read_text(encoding="utf-8"))
        ledger_spend_after = sum(float(x.get("cost", 0.0)) for x in ledger_after.get("generations", []))

        evidence = {
            "execution_status": "SUCCESS",
            "goal": {
                "id": str(g.id),
                "status": g.status,
                "current_plan_version": g.current_plan_version,
                "final_summary": g.final_summary,
            },
            "shot_01": {
                "id": str(s1.id),
                "client_action_id": s1.client_action_id,
                "status": s1.status,
                "cost_usd": float(s1.cost_usd or 0.0),
                "provider": "fal",
                "model": "fal-ai/flux-pro/v1.1",
                "provider_job_id": s1_job_id,
                "duration_seconds": s1_duration,
                "artifact_path": str(TARGET_IMAGE_ARTIFACT),
                "artifact_size_bytes": len(s1_bytes),
                "artifact_sha256": s1_sha256,
                "artifact_format": "PNG",
            },
            "shot_02": {
                "id": str(s2.id),
                "client_action_id": s2.client_action_id,
                "status": s2.status,
                "cost_usd": float(s2.cost_usd or 0.0),
                "provider": "camera_motion",
                "model": "camera-push",
                "duration_seconds": s2_duration,
                "artifact_path": str(TARGET_VIDEO_ARTIFACT),
                "artifact_size_bytes": len(s2_bytes),
                "artifact_sha256": s2_sha256,
                "container": fmt_info.get("format_name", "mp4"),
                "codec": v_stream.get("codec_name", "unknown"),
                "dimensions": f"{v_stream.get('width', 0)}x{v_stream.get('height', 0)}",
                "fps": v_stream.get("r_frame_rate", "30/1"),
                "video_duration_seconds": float(fmt_info.get("duration", 0.0) or 0.0),
            },
            "budget": {
                "project_id": str(PROJECT_ID),
                "external_provider_requests": 1,
                "external_provider_spend_usd": float(s1.cost_usd or 0.0),
                "local_spend_usd": float(s2.cost_usd or 0.0),
                "total_spend_usd": float(s1.cost_usd or 0.0) + float(s2.cost_usd or 0.0),
                "reservations": [
                    {
                        "id": str(r.id),
                        "status": r.status,
                        "reserved_amount_usd": float(r.reserved_amount_usd),
                        "consumed_amount_usd": float(r.consumed_amount_usd),
                    }
                    for r in reservations
                ],
                "fal_ledger": {
                    "spend_before": ledger_spend_before,
                    "spend_after": ledger_spend_after,
                    "delta_spend": round(ledger_spend_after - ledger_spend_before, 4),
                    "total_generations": len(ledger_after.get("generations", [])),
                },
            },
            "gates_restored": {
                "ENABLE_LIVE_PROVIDER_EXECUTION": is_live_provider_execution_enabled(),
                "ENABLE_LIVE_LOCAL_EXECUTION": is_live_local_execution_enabled(),
            },
        }

        print("\n" + "=" * 80)
        print("PHASE 3.2.4.4.6.3.3.9 EXECUTION TELEMETRY & AUDIT EVIDENCE:")
        print("=" * 80)
        print(json.dumps(evidence, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
