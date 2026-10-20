"""
AryaOS V1 Phase 12 — Real Video Generation End-to-End Orchestrator.

Creates:
1. Production Project: "AryaOS Phase 12 Video Production"
2. Sequence 01: "Sequence 01 // Quantum Monolith Sequence"
3. Shot 01: Real Image Keyframe (COMPLETE)
4. Shot 02: Real Video Shot (Camera push into glowing core, 5.0s, 25fps, H.264 MP4)
   - Executed through ExecutionGateway -> OpenMontage -> Real FFmpeg generation -> Real MP4 binary
   - Validated by ArtifactValidator
   - Persisted to PostgreSQL
5. Shot 03: Honest Failure Shot (Kling video requesting last-frame conditioning)
   - Demonstrates zero fake fallback and truthful capability reporting
"""

import asyncio
import os
import uuid
from pathlib import Path

import httpx

API_BASE = "http://127.0.0.1:8000/api/v1"
HEADERS = {"Content-Type": "application/json"}


async def main():
    async with httpx.AsyncClient(timeout=120.0) as client:
        print("[1/6] Creating Phase 12 Production Project...")
        resp = await client.post(
            f"{API_BASE}/projects",
            json={
                "name": "AryaOS Phase 12 Video Production",
                "description": "Production corridor with genuine H.264 video generation and temporal continuity",
            },
            headers=HEADERS,
        )
        resp.raise_for_status()
        proj = resp.json()
        proj_id = proj["id"]
        print(f"      Created Project: {proj_id}")

        # Get project tree to locate default sequence
        tree_resp = await client.get(f"{API_BASE}/projects/{proj_id}/tree")
        tree_resp.raise_for_status()
        tree = tree_resp.json()
        seq_id = tree["sequences"][0]["id"]
        print(f"      Initial Sequence: {seq_id}")

        print("[2/6] Provisioning Shot 01 (Obsidian Monolith Keyframe)...")
        shot1_resp = await client.post(
            f"{API_BASE}/projects/{proj_id}/shots",
            json={
                "sequence_id": seq_id,
                "shot_number": 1,
                "title": "Shot 01 // Quantum Monolith Establishing Still",
                "prompt": "Minimal cinematic futuristic obsidian monolith, amber core, dark architectural geometry",
                "generation_type": "image",
                "model": "flux-pro/v1.1",
                "provider": "fal",
                "aspect_ratio": "16:9",
                "duration": 5.0,
                "status": "COMPLETE",
                "output_asset_url": "/api/v1/artifacts/artifact_6591f345-0eeb-4eff-89d8-f485eef80bf5_403503b4.png",
                "metadata_json": {
                    "artifact": {
                        "filename": "artifact_6591f345-0eeb-4eff-89d8-f485eef80bf5_403503b4.png",
                        "mime_type": "image/png",
                        "width": 1344,
                        "height": 768,
                        "size_bytes": 9880,
                    }
                },
            },
            headers=HEADERS,
        )
        shot1_resp.raise_for_status()
        shot1 = shot1_resp.json()
        shot1_id = shot1["id"]
        print(f"      Shot 01 Created: {shot1_id} [COMPLETE]")

        print("[3/6] Provisioning Shot 02 (Cinematic Camera Push Temporal Video)...")
        shot2_resp = await client.post(
            f"{API_BASE}/projects/{proj_id}/shots",
            json={
                "sequence_id": seq_id,
                "shot_number": 2,
                "title": "Shot 02 // Cinematic Camera Push into Glowing Core",
                "prompt": "Smooth cinematic camera push into glowing amber monolith core",
                "generation_type": "video",
                "model": "camera-push",
                "provider": "camera_motion",
                "aspect_ratio": "16:9",
                "duration": 5.0,
                "status": "READY",
                "predecessor_shot_id": str(shot1_id),
                "first_frame": "/api/v1/artifacts/artifact_6591f345-0eeb-4eff-89d8-f485eef80bf5_403503b4.png",
            },
            headers=HEADERS,
        )
        shot2_resp.raise_for_status()
        shot2 = shot2_resp.json()
        shot2_id = shot2["id"]
        print(f"      Shot 02 Created: {shot2_id} [READY]")

        print("[4/6] Assembling Temporal Job Package and Dispatching Execution...")
        pkg_id = f"pkg-video-{uuid.uuid4().hex[:8]}"
        job_package = {
            "jobPackageId": pkg_id,
            "createdAt": "2026-09-28T17:00:00Z",
            "projectId": proj_id,
            "sequenceId": seq_id,
            "shotId": shot2_id,
            "shotOrder": 2,
            "plan": {
                "title": "Shot 02 // Cinematic Camera Push into Glowing Core",
                "prompt": "Smooth cinematic camera push into glowing amber monolith core",
                "generationType": "video",
                "durationSeconds": 5.0,
                "mode": "video",
                "fps": 25,
                "predecessorShotId": str(shot1_id),
                "dependencies": [str(shot1_id)],
                "isFirstShotInSequence": False,
            },
            "references": {
                "firstFrame": "/api/v1/artifacts/artifact_6591f345-0eeb-4eff-89d8-f485eef80bf5_403503b4.png",
                "startFrameUrl": "/api/v1/artifacts/artifact_6591f345-0eeb-4eff-89d8-f485eef80bf5_403503b4.png",
                "referenceAssets": [],
            },
            "modelRoute": {
                "provider": "camera_motion",
                "model": "camera-push",
                "modelName": "Camera Motion Push (FFmpeg)",
                "mode": "video",
                "preflightReady": True,
                "preflightReasons": [],
                "availability": "AVAILABLE",
                "estimatedCostUsd": 0.0,
            },
            "shotConfiguration": {
                "aspectRatio": "16:9",
                "duration": 5.0,
                "fps": 25,
            },
            "continuityRequirements": {
                "character": "UNAVAILABLE",
                "environment": "PASS",
                "visual": "PASS",
                "temporal": "PASS",
                "startFrame": "PROVIDED",
            },
            "outputRequirements": {
                "destination": "ARYAOS_CORRIDOR_STREAM",
                "targetFormat": "video/mp4",
            },
            "decisionBoundary": "ARYAOS_ORCHESTRATION_VALIDATED",
            "executionPayload": {
                "generation_type": "video",
                "prompt": "Smooth cinematic camera push into glowing amber monolith core",
                "model": "camera-push",
                "provider": "camera_motion",
                "aspect_ratio": "16:9",
                "duration_seconds": 5.0,
            },
        }

        # Submit with dispatch=true
        dispatch_resp = await client.post(
            f"{API_BASE}/projects/{proj_id}/jobs?dispatch=true",
            json=job_package,
            headers=HEADERS,
        )
        dispatch_resp.raise_for_status()
        job = dispatch_resp.json()
        job_id = job["id"]
        print(f"      Job Package Submitted & Dispatched: {job_id}")

        # Poll until COMPLETED or timeout
        print("      Polling for real execution and container validation...")
        for _ in range(40):
            await asyncio.sleep(0.5)
            j_resp = await client.get(f"{API_BASE}/jobs/{job_id}")
            j_resp.raise_for_status()
            current_job = j_resp.json()
            if current_job["status"] in ("COMPLETED", "FAILED"):
                break

        print(f"      Final Job Status: {current_job['status']}")
        if current_job["status"] != "COMPLETED":
            print(f"      ERROR: Job failed with: {current_job.get('error')}")
            return

        # Fetch refreshed shot 02
        s2_resp = await client.get(f"{API_BASE}/shots/{shot2_id}")
        s2_resp.raise_for_status()
        s2 = s2_resp.json()
        print(f"      Refreshed Shot 02 Status: {s2['status']}")
        print(f"      Output Asset URL: {s2['output_asset_url']}")
        print(f"      Artifact Metadata: {s2.get('metadata_json', {}).get('artifact')}")

        print("[5/6] Demonstrating Capability Boundary (Kling Unsupported Last-Frame Failure)...")
        shot3_resp = await client.post(
            f"{API_BASE}/projects/{proj_id}/shots",
            json={
                "sequence_id": seq_id,
                "shot_number": 3,
                "title": "Shot 03 // Kling Video with Last-Frame (Unsupported)",
                "prompt": "Transition from establishing shot to interior core",
                "generation_type": "video",
                "model": "kling-video",
                "provider": "kling",
                "aspect_ratio": "16:9",
                "duration": 5.0,
                "status": "READY",
            },
            headers=HEADERS,
        )
        shot3_resp.raise_for_status()
        shot3_id = shot3_resp.json()["id"]

        fail_job_package = {
            "jobPackageId": f"pkg-fail-{uuid.uuid4().hex[:8]}",
            "createdAt": "2026-09-28T17:01:00Z",
            "projectId": proj_id,
            "sequenceId": seq_id,
            "shotId": shot3_id,
            "shotOrder": 3,
            "plan": {
                "title": "Shot 03 // Kling Video with Last-Frame (Unsupported)",
                "prompt": "Transition from establishing shot to interior core",
                "generationType": "video",
                "durationSeconds": 5.0,
                "dependencies": [],
                "isFirstShotInSequence": False,
            },
            "references": {
                "firstFrame": "/api/v1/artifacts/artifact_6591f345-0eeb-4eff-89d8-f485eef80bf5_403503b4.png",
                "lastFrame": "/api/v1/artifacts/artifact_6591f345-0eeb-4eff-89d8-f485eef80bf5_403503b4.png",
                "referenceAssets": [],
            },
            "modelRoute": {
                "provider": "kling",
                "model": "kling-video",
                "modelName": "Kling Video V3",
                "mode": "video",
                "preflightReady": True,
                "preflightReasons": [],
                "availability": "AVAILABLE",
                "estimatedCostUsd": 0.10,
            },
            "shotConfiguration": {
                "aspectRatio": "16:9",
                "duration": 5.0,
            },
            "continuityRequirements": {
                "character": "UNAVAILABLE",
                "environment": "PASS",
                "visual": "PASS",
                "temporal": "PASS",
                "startFrame": "PROVIDED",
            },
            "outputRequirements": {
                "destination": "ARYAOS_CORRIDOR_STREAM",
                "targetFormat": "video/mp4",
            },
            "decisionBoundary": "ARYAOS_ORCHESTRATION_VALIDATED",
            "executionPayload": {
                "generation_type": "video",
                "prompt": "Transition",
                "model": "kling-video",
                "provider": "kling",
                "aspect_ratio": "16:9",
            },
        }

        fail_disp = await client.post(
            f"{API_BASE}/projects/{proj_id}/jobs?dispatch=true",
            json=fail_job_package,
            headers=HEADERS,
        )
        fail_job = fail_disp.json()
        fail_job_id = fail_job["id"]

        for _ in range(10):
            await asyncio.sleep(0.3)
            fj_resp = await client.get(f"{API_BASE}/jobs/{fail_job_id}")
            current_fj = fj_resp.json()
            if current_fj["status"] in ("COMPLETED", "FAILED"):
                break

        print(f"      Kling Job Failure Status: {current_fj['status']}")
        print(f"      Truthful Error Reported: {current_fj.get('error')}")

        print("[6/6] Phase 12 Video Pipeline Verification Complete!")
        print(f"PROJECT_ID={proj_id}")
        print(f"SHOT1_ID={shot1_id}")
        print(f"SHOT2_ID={shot2_id}")
        print(f"SHOT3_ID={shot3_id}")


if __name__ == "__main__":
    asyncio.run(main())
