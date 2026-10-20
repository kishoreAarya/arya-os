"""
AryaOS V1 Phase 13 — Multi-Shot Temporal Continuity & Production Graph E2E Orchestrator.

Proves the complete real multi-shot temporal dependency pipeline:
USER INTENTION -> SHOT GRAPH -> ROUTING -> SHOT 01 EXECUTION -> REAL MP4 ARTIFACT
-> REAL LAST FRAME EXTRACTION (PNG) -> BINARY VALIDATION -> SHOT 02 UNLOCKED
-> FIRST FRAME CONDITIONING PROPAGATED -> SHOT 02 EXECUTION -> CONTINUITY VALIDATION (PASS)
-> PRODUCTION TIMELINE READY
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
        print("================================================================================")
        print("  AryaOS V1 Phase 13: Multi-Shot Temporal Continuity & Production Graph E2E")
        print("================================================================================")

        # 1. Create Production Project
        print("\n[1/8] Creating Phase 13 Production Project...")
        resp = await client.post(
            f"{API_BASE}/projects",
            json={
                "name": "AryaOS Phase 13 Multi-Shot Temporal Production",
                "description": "Deterministic shot dependency graph with frame extraction and structural continuity",
            },
            headers=HEADERS,
        )
        resp.raise_for_status()
        proj = resp.json()
        proj_id = proj["id"]
        print(f"      Project Created: {proj_id}")

        tree_resp = await client.get(f"{API_BASE}/projects/{proj_id}/tree")
        tree_resp.raise_for_status()
        tree = tree_resp.json()
        seq_id = tree["sequences"][0]["id"]
        print(f"      Target Sequence: {seq_id}")

        # 2. Provision Shot 01 (Root Shot)
        print("\n[2/8] Provisioning Shot 01 (Root Video Shot)...")
        shot1_resp = await client.post(
            f"{API_BASE}/projects/{proj_id}/shots",
            json={
                "sequence_id": seq_id,
                "shot_number": 1,
                "title": "Shot 01 // Quantum Monolith Awakening",
                "prompt": "Cinematic wide angle, obsidian monolith activating with amber pulse",
                "generation_type": "video",
                "model": "camera-push",
                "provider": "camera_motion",
                "aspect_ratio": "16:9",
                "duration": 4.0,
                "status": "READY",
                "first_frame": "/api/v1/artifacts/artifact_6591f345-0eeb-4eff-89d8-f485eef80bf5_403503b4.png",
            },
            headers=HEADERS,
        )
        shot1_resp.raise_for_status()
        shot1 = shot1_resp.json()
        shot1_id = shot1["id"]
        print(f"      Shot 01 Created: {shot1_id} [READY, dependency_state=INDEPENDENT]")

        # 3. Provision Shot 02 (Dependent on Shot 01)
        print("\n[3/8] Provisioning Shot 02 (Dependent on Shot 01)...")
        shot2_resp = await client.post(
            f"{API_BASE}/projects/{proj_id}/shots",
            json={
                "sequence_id": seq_id,
                "shot_number": 2,
                "title": "Shot 02 // Orbital Core Approach",
                "prompt": "Slow dolly approach into central monolithic chamber continuing from previous shot",
                "generation_type": "video",
                "model": "camera-push",
                "provider": "camera_motion",
                "aspect_ratio": "16:9",
                "duration": 4.0,
                "status": "BLOCKED",
                "predecessor_shot_id": str(shot1_id),
                "dependency_shot_ids": [str(shot1_id)],
            },
            headers=HEADERS,
        )
        shot2_resp.raise_for_status()
        shot2 = shot2_resp.json()
        shot2_id = shot2["id"]
        print(f"      Shot 02 Created: {shot2_id} [BLOCKED, predecessor={shot1_id}]")

        # 4. Verify Production Graph State Before Execution
        print("\n[4/8] Inspecting Production Graph & Pre-dispatch Dependencies...")
        graph_resp = await client.get(f"{API_BASE}/projects/{proj_id}/graph")
        graph_resp.raise_for_status()
        graph = graph_resp.json()
        nodes = {n["shot_id"]: n for n in graph["nodes"]}
        print(f"      Graph Nodes: {len(nodes)}, Has Cycles: {graph['has_cycles']}")
        print(f"      Shot 01 Dispatchable: {nodes[str(shot1_id)]['can_dispatch']}")
        print(f"      Shot 02 Dispatchable: {nodes[str(shot2_id)]['can_dispatch']} (Blocked: {nodes[str(shot2_id)]['is_blocked']})")
        assert nodes[str(shot1_id)]["can_dispatch"] is True, "Shot 01 must be dispatchable"
        assert nodes[str(shot2_id)]["can_dispatch"] is False, "Shot 02 must NOT be dispatchable"
        assert str(shot1_id) in nodes[str(shot2_id)]["unmet_dependencies"], "Shot 01 must be an unmet dependency of Shot 02"

        # 5. Dispatch Shot 01 and Poll Until Complete
        print("\n[5/8] Dispatching Shot 01 (Real Video Generation)...")
        pkg1_id = f"pkg-video-{uuid.uuid4().hex[:8]}"
        job1_pkg = {
            "jobPackageId": pkg1_id,
            "createdAt": "2026-09-28T18:00:00Z",
            "projectId": proj_id,
            "sequenceId": seq_id,
            "shotId": shot1_id,
            "shotOrder": 1,
            "plan": {
                "title": "Shot 01 // Quantum Monolith Awakening",
                "prompt": "Cinematic wide angle, obsidian monolith activating with amber pulse",
                "generationType": "video",
                "durationSeconds": 4.0,
                "mode": "video",
                "fps": 25,
                "isFirstShotInSequence": True,
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
                "duration": 4.0,
                "fps": 25,
            },
            "continuityRequirements": {
                "character": "UNAVAILABLE",
                "environment": "PASS",
                "visual": "PASS",
                "temporal": "PASS",
                "startFrame": "NOT_APPLICABLE",
            },
            "outputRequirements": {
                "destination": "ARYAOS_CORRIDOR_STREAM",
                "targetFormat": "video/mp4",
            },
            "decisionBoundary": "ARYAOS_ORCHESTRATION_VALIDATED",
            "executionPayload": {
                "generation_type": "video",
                "prompt": "Cinematic wide angle, obsidian monolith activating with amber pulse",
                "model": "camera-push",
                "provider": "camera_motion",
                "aspect_ratio": "16:9",
                "duration_seconds": 4.0,
            },
        }

        dispatch1_resp = await client.post(
            f"{API_BASE}/projects/{proj_id}/jobs?dispatch=true",
            json=job1_pkg,
            headers=HEADERS,
        )
        dispatch1_resp.raise_for_status()
        job1 = dispatch1_resp.json()
        job1_id = job1["id"]
        print(f"      Shot 01 Job Dispatched: {job1_id}")

        print("      Polling Shot 01 execution, frame extraction, and successor unlocking...")
        for _ in range(40):
            await asyncio.sleep(0.5)
            j_resp = await client.get(f"{API_BASE}/jobs/{job1_id}")
            j_resp.raise_for_status()
            current_job = j_resp.json()
            if current_job["status"] in ("COMPLETED", "FAILED"):
                break

        print(f"      Shot 01 Job Status: {current_job['status']}")
        assert current_job["status"] == "COMPLETED", f"Shot 01 execution failed: {current_job.get('error')}"

        # Verify Shot 01 Artifact and Extracted Anchors
        s1_resp = await client.get(f"{API_BASE}/shots/{shot1_id}")
        s1_resp.raise_for_status()
        s1_data = s1_resp.json()
        print(f"      Shot 01 Output Video: {s1_data['output_asset_url']}")
        anchors1 = s1_data.get("metadata_json", {}).get("frame_anchors", {})
        print(f"      Shot 01 Extracted First Frame: {anchors1.get('first_frame', {}).get('filename')} (Hash: {anchors1.get('first_frame', {}).get('sha256', '')[:12]}...)")
        print(f"      Shot 01 Extracted Last Frame:  {anchors1.get('last_frame', {}).get('filename')} (Hash: {anchors1.get('last_frame', {}).get('sha256', '')[:12]}...)")
        assert "last_frame" in anchors1, "Shot 01 must have extracted last frame"
        assert s1_data["last_frame"], "Shot 01 last_frame column must be populated"

        # 6. Verify Shot 02 is now Unlocked with Propagated Conditioning
        print("\n[6/8] Verifying Shot 02 Unlocking and First-Frame Conditioning...")
        s2_check_resp = await client.get(f"{API_BASE}/shots/{shot2_id}")
        s2_check_resp.raise_for_status()
        s2_check = s2_check_resp.json()
        print(f"      Shot 02 Status:           {s2_check['status']}")
        print(f"      Shot 02 Dependency State: {s2_check['dependency_state']}")
        print(f"      Shot 02 First Frame URL:  {s2_check['first_frame']}")
        assert s2_check["status"] == "READY", f"Shot 02 should be READY, got {s2_check['status']}"
        assert s2_check["dependency_state"] == "READY", f"Shot 02 dependency_state should be READY, got {s2_check['dependency_state']}"
        assert s2_check["first_frame"] == s1_data["last_frame"], "Shot 02 first_frame must match Shot 01 verified last frame"

        # Check graph dispatchability
        graph2_resp = await client.get(f"{API_BASE}/projects/{proj_id}/graph")
        graph2_resp.raise_for_status()
        graph2 = graph2_resp.json()
        nodes2 = {n["shot_id"]: n for n in graph2["nodes"]}
        print(f"      Shot 02 Now Dispatchable: {nodes2[str(shot2_id)]['can_dispatch']} (Blocked: {nodes2[str(shot2_id)]['is_blocked']})")
        assert nodes2[str(shot2_id)]["can_dispatch"] is True, "Shot 02 must now be dispatchable"

        # 7. Dispatch Shot 02 Conditioned on Shot 01
        print("\n[7/8] Dispatching Shot 02 (Conditioned on Shot 01 Verified Last Frame)...")
        pkg2_id = f"pkg-video-{uuid.uuid4().hex[:8]}"
        job2_pkg = {
            "jobPackageId": pkg2_id,
            "createdAt": "2026-09-28T18:05:00Z",
            "projectId": proj_id,
            "sequenceId": seq_id,
            "shotId": shot2_id,
            "shotOrder": 2,
            "plan": {
                "title": "Shot 02 // Orbital Core Approach",
                "prompt": "Slow dolly approach into central monolithic chamber continuing from previous shot",
                "generationType": "video",
                "durationSeconds": 4.0,
                "mode": "video",
                "fps": 25,
                "predecessorShotId": str(shot1_id),
                "dependencies": [str(shot1_id)],
                "isFirstShotInSequence": False,
            },
            "references": {
                "firstFrame": s2_check["first_frame"],
                "startFrameUrl": s2_check["first_frame"],
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
                "duration": 4.0,
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
                "prompt": "Slow dolly approach into central monolithic chamber continuing from previous shot",
                "model": "camera-push",
                "provider": "camera_motion",
                "aspect_ratio": "16:9",
                "duration_seconds": 4.0,
            },
        }

        dispatch2_resp = await client.post(
            f"{API_BASE}/projects/{proj_id}/jobs?dispatch=true",
            json=job2_pkg,
            headers=HEADERS,
        )
        dispatch2_resp.raise_for_status()
        job2 = dispatch2_resp.json()
        job2_id = job2["id"]
        print(f"      Shot 02 Job Dispatched: {job2_id}")

        print("      Polling Shot 02 execution, frame extraction, and continuity evaluation...")
        for _ in range(40):
            await asyncio.sleep(0.5)
            j_resp = await client.get(f"{API_BASE}/jobs/{job2_id}")
            j_resp.raise_for_status()
            current_job = j_resp.json()
            if current_job["status"] in ("COMPLETED", "FAILED"):
                break

        print(f"      Shot 02 Job Status: {current_job['status']}")
        assert current_job["status"] == "COMPLETED", f"Shot 02 execution failed: {current_job.get('error')}"

        # 8. Query Final Continuity Verification & Report
        print("\n[8/8] Inspecting Final Temporal Continuity Report...")
        cont_resp = await client.get(f"{API_BASE}/shots/{shot2_id}/continuity")
        cont_resp.raise_for_status()
        continuity = cont_resp.json()

        print("\n" + "=" * 80)
        print("  TEMPORAL CONTINUITY CERTIFICATION REPORT")
        print("=" * 80)
        print(f"  Target Shot:       Shot 02 ({shot2_id})")
        print(f"  Predecessor Shot:  Shot 01 ({shot1_id})")
        print(f"  Overall Status:    {continuity['status']}")
        print(f"  Technical Status:  {continuity['technical_status']}")
        print(f"  Dependency Status: {continuity['dependency_status']}")
        print(f"  Temporal Status:   {continuity['temporal_status']}")
        print(f"  Reasons:           {continuity.get('reasons', [])}")
        print(f"  Validation Level:  {continuity.get('diagnostics', {}).get('validation_level', 'STRUCTURAL_TECHNICAL_CONTINUITY')}")
        print(f"  Diagnostics:       {continuity.get('diagnostics', {})}")
        print("=" * 80)

        assert continuity["status"] in ("PASS", "WARNING"), f"Continuity should be PASS/WARNING, got {continuity['status']}"
        assert continuity["technical_status"] == "PASS"
        assert continuity["dependency_status"] == "PASS"
        assert continuity["temporal_status"] == "PASS"

        print("\n>>> ALL MULTI-SHOT TEMPORAL CONTINUITY REQUIREMENTS CERTIFIED 100% <<<")


if __name__ == "__main__":
    asyncio.run(main())
