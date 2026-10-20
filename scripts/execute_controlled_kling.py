"""
AryaOS Stage 25 — Phase 3.2.4.4 Controlled Single-Shot Kling Video Execution Script.

EXPLICIT OPERATOR AUTHORIZATION: ONE REAL EXTERNAL CALL ONLY.
Executes exactly one Kling video generation request through the governed
AryaOS execution pipeline:
    AutonomousExecutionRunner
    -> LiveProviderDispatcher
    -> VideoProviderRegistry
    -> KlingVideoProvider
    -> OpenMontageAdapter
    -> OpenMontage subprocess
    -> Fal.ai / Kling API queue
    -> Protocol v1.1 framing
    -> Real physical MP4 artifact validation
    -> PostgreSQL persistence
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

# Add backend directory to sys.path
backend_dir = Path(__file__).resolve().parent.parent / "backend"
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from app.core.config import Settings, get_settings
from app.core.security import AuthenticatedPrincipal
from app.database.session import AsyncSessionLocal
from app.models.core import Project
from app.models.execution_bridge import AutonomousActionNode, AutonomousGoal
from app.services.artifact_validator import (
    STORAGE_ARTIFACTS_DIR,
    validate_artifact_file,
)
from app.services.autonomous_execution_runner import AutonomousExecutionRunner
from app.services.dispatcher import LiveProviderDispatcher
from app.services.openmontage_adapter import validate_provider_job_id


TARGET_ARTIFACT = STORAGE_ARTIFACTS_DIR / "phase3_2_4_4_kling_astrolabe.mp4"
PROMPT = "Cinematic slow orbital sweep of an ancient brass astrolabe mechanism, photorealistic, 4k"


async def main():
    print("=" * 70)
    print("ARYAOS STAGE 25 — PHASE 3.2.4.4 CONTROLLED KLING VIDEO EXECUTION")
    print("=" * 70)

    # Safety Guard: Ensure no previous execution artifact exists
    if TARGET_ARTIFACT.exists():
        print(f"ABORT: Target artifact already exists at {TARGET_ARTIFACT}!")
        print("To prevent duplicate billing, refusing to re-execute.")
        sys.exit(1)

    # 1. Environment & Pre-flight verification
    settings = get_settings()
    fal_key = settings.fal_key or settings.fal_api_key or os.environ.get("FAL_KEY")
    if not fal_key or len(fal_key) < 32:
        print("ABORT: FAL_KEY missing or invalid in server environment!")
        sys.exit(1)

    print("[1/6] Sourcing server-side environment... FAL_KEY verified present (REDACTED).")

    # 2. Database Session & Entity Creation
    async with AsyncSessionLocal() as db_session:
        print("[2/6] Initializing PostgreSQL governance records...")
        project = Project(
            name="Controlled Single-Shot Kling Video Project",
            description="Phase 3.2.4.4 Controlled Kling execution sandbox",
        )
        db_session.add(project)
        await db_session.flush()

        principal = AuthenticatedPrincipal(
            api_key_id=uuid.uuid4(),
            name="Security Operator",
            is_admin=True,
            principal_type="system",
        )

        goal = AutonomousGoal(
            project_id=project.id,
            objective="Controlled Single-Shot Kling Video Execution",
            status="EXECUTING",
            plan_dag_json={
                "nodes": [{"client_action_id": "shot_kling_single_shot_001"}],
                "edges": [],
            },
        )
        db_session.add(goal)
        await db_session.flush()

        action = AutonomousActionNode(
            goal_id=goal.id,
            client_action_id="shot_kling_single_shot_001",
            title="Shot 001 Kling Video Generation",
            action_type="GENERATION",
            required_capability="VIDEO_GENERATION",
            status="READY",
            inputs_json={
                "prompt": PROMPT,
                "provider": "kling",
                "model": "kling-video/v3/standard",
                "duration": 5.0,
                "aspect_ratio": "16:9",
                "output_path": str(TARGET_ARTIFACT),
            },
        )
        db_session.add(action)
        await db_session.commit()
        action_id = action.id
        print(f"      Action initialized: id={action_id}, status=READY, capability=VIDEO_GENERATION")

        # 3. Configure Dispatcher & Runner
        controlled_settings = Settings(
            enable_live_provider_execution=True,
            enable_live_local_execution=False,
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
            worker_id="worker-kling-single-shot-01",
            settings=controlled_settings,
        )

        # 4. Dispatch Single-Shot Execution
        print("[3/6] Dispatching controlled single-shot execution across provider boundary...")
        print("      Provider: kling")
        print("      Model: kling-video/v3/standard")
        print("      Duration: 5 seconds")
        print("      Aspect ratio: 16:9")
        print(f"      Output: {TARGET_ARTIFACT}")
        print("      Submitting to Fal queue API (timeout: 300s)...")

        t_start = time.time()
        start_iso = datetime.now(timezone.utc).isoformat()

        exec_node = await runner.dispatch_action(action_id, principal)

        t_end = time.time()
        end_iso = datetime.now(timezone.utc).isoformat()
        duration_total = round(t_end - t_start, 2)

        print(f"[4/6] Execution returned in {duration_total}s with status={exec_node.status}")

        # 5. Inspect Results & Extract Telemetry
        intent = (exec_node.inputs_json or {}).get("dispatch_intent", {})
        provider_job_id = (
            intent.get("provider_job_id")
            or (exec_node.outputs_json or {}).get("provider_job_id")
            or (exec_node.outputs_json or {}).get("request_id")
        )
        accounting_warning = (exec_node.outputs_json or {}).get("accounting_warning")
        cost_usd = float(exec_node.cost_usd or 0.0)

        print("[5/6] Execution Telemetry:")
        print(f"      Provider Request ID: {provider_job_id}")
        print(f"      Cost: ${cost_usd:.4f}")
        print(f"      Duration: {duration_total}s")
        print(f"      Accounting Warning: {accounting_warning}")

        # 6. Physical Artifact Verification
        print("[6/6] Inspecting physical video artifact on disk...")
        if not TARGET_ARTIFACT.is_file():
            print(f"CRITICAL ERROR: Artifact file does not exist at {TARGET_ARTIFACT}!")
            sys.exit(2)

        raw_bytes = TARGET_ARTIFACT.read_bytes()
        file_size = len(raw_bytes)
        sha256_hash = hashlib.sha256(raw_bytes).hexdigest()

        # Run ffprobe for detailed container/stream metrics
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
                    str(TARGET_ARTIFACT),
                ],
                capture_output=True,
                text=True,
            )
            if proc.returncode == 0:
                probe_json = json.loads(proc.stdout)

        fmt_info = probe_json.get("format", {})
        v_stream = next((s for s in probe_json.get("streams", []) if s.get("codec_type") == "video"), {})

        video_codec = v_stream.get("codec_name", "unknown")
        width = int(v_stream.get("width", 0))
        height = int(v_stream.get("height", 0))
        r_fps = v_stream.get("r_frame_rate", "")
        v_duration = float(fmt_info.get("duration", 0.0) or 0.0)

        summary = {
            "status": exec_node.status,
            "provider": "kling",
            "model": "fal-ai/kling-video/v3/standard/text-to-video",
            "provider_request_id": provider_job_id,
            "start_time": start_iso,
            "end_time": end_iso,
            "duration_seconds": duration_total,
            "cost_usd": cost_usd,
            "accounting_warning": accounting_warning,
            "artifact_path": str(TARGET_ARTIFACT),
            "artifact_size_bytes": file_size,
            "artifact_sha256": sha256_hash,
            "container": fmt_info.get("format_name", "mp4"),
            "codec": video_codec,
            "dimensions": f"{width}x{height}",
            "fps": r_fps,
            "video_duration_seconds": v_duration,
        }

        print("\n" + "=" * 70)
        print("EXECUTION EVIDENCE SUMMARY:")
        print("=" * 70)
        print(json.dumps(summary, indent=2))
        print("=" * 70)


if __name__ == "__main__":
    asyncio.run(main())
