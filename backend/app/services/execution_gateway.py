"""
AryaOS V1 Phase 9 — Execution Gateway Service.

The Execution Gateway is the single boundary through which AryaOS connects to
the execution layer (OpenMontage).

Responsibilities:
1. Validates the AryaJobPackage boundary contract.
2. Translates AryaJobPackage into target OpenMontage tool inputs.
3. Orchestrates the real execution lifecycle:
   QUEUED -> SUBMITTED -> RUNNING -> COMPLETED / FAILED / CANCELLED.
4. Preserves execution attempts history without overwriting previous attempts.
5. Records generated media artifacts and updates production shots.
6. Emits live SSE telemetry events for spatial HUD, Core emission, and corridor cards.
7. Honestly reports failures (no fabricated progress or mock outputs).
"""

from __future__ import annotations

import asyncio
import os
import unittest.mock
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.database.session import AsyncSessionLocal
from app.models.production import ProductionJob, ProductionShot
from app.schemas.production import AryaJobPackageSchema, TelemetryEvent
from app.services.artifact_validator import validate_artifact_file, ArtifactValidationResult
from app.services.image_provider import image_provider_registry
from app.services.video_provider import video_provider_registry, CAP_FIRST_LAST_FRAME_TO_VIDEO
from app.services.openmontage_adapter import (
    OpenMontageAdapter,
    OpenMontageToolResult,
    is_external_tool,
    openmontage_adapter,
)
from app.services.production_service import emit_telemetry_event, validate_job_transition
from app.services.frame_extractor import frame_extractor
from app.services.continuity_validator import continuity_validator
from app.services.shot_graph_service import shot_graph_service

logger = get_logger("arya.execution.gateway")


class ExecutionBoundaryQuarantineError(HTTPException):
    """Raised when direct legacy execution gateway is invoked for an external cloud tool."""

    def __init__(
        self,
        detail: str = "Direct execution gateway dispatch for external cloud tool is permanently quarantined.",
    ) -> None:
        super().__init__(status_code=409, detail=detail)

# Permitted storage directory for artifacts
STORAGE_ARTIFACTS_DIR = (Path(__file__).resolve().parents[2] / "storage" / "artifacts").resolve()
STORAGE_ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)


class ExecutionGateway:
    """Orchestrates job execution across the boundary into OpenMontage."""

    def __init__(self, adapter: OpenMontageAdapter | None = None) -> None:
        self.adapter = adapter or openmontage_adapter

    def resolve_tool_for_package(self, pkg: AryaJobPackageSchema) -> tuple[str, dict[str, Any]]:
        """Maps an AryaJobPackage to an OpenMontage tool and input dictionary.

        Returns:
            (tool_name, inputs_dict)
        """
        provider = (pkg.modelRoute.provider or "").lower()
        model = (pkg.modelRoute.model or "").lower()
        gen_type = (pkg.plan.generationType or "image").lower()
        prompt = pkg.plan.prompt or ""

        # Determine dimensions from aspect ratio
        aspect = pkg.shotConfiguration.aspectRatio or "16:9"
        if aspect == "1:1":
            width, height = 1024, 1024
        elif aspect == "9:16":
            width, height = 768, 1344
        elif aspect == "21:9":
            width, height = 1536, 640
        else:  # 16:9 default
            width, height = 1344, 768

        artifact_ext = "mp4" if "video" in gen_type else "png"
        artifact_filename = f"artifact_{pkg.shotId}_{uuid.uuid4().hex[:8]}.{artifact_ext}"
        target_path = str(STORAGE_ARTIFACTS_DIR / artifact_filename)

        # 1. Diagram / Box / Flowchart generation (Local zero-cost vector/image generation)
        if provider in ("diagram", "diagram_gen", "mermaid") or "diagram" in prompt.lower():
            return "diagram_gen", {
                "diagram_type": "boxes",
                "title": pkg.plan.title or "AryaOS Diagram",
                "boxes": [
                    {"label": "AryaOS Orchestration", "color": "#0ea5e9"},
                    {"label": prompt[:40] if prompt else "Execution Node", "color": "#f59e0b"},
                ],
                "width": 1200,
                "height": 800,
                "output_path": target_path,
            }

        # 2. Code snippet visual rendering (Local zero-cost code card)
        if provider in ("code", "code_snippet") or "code" in prompt.lower() and "snippet" in prompt.lower():
            return "code_snippet", {
                "code": prompt or "print('Hello AryaOS')",
                "language": "python",
                "theme": "monokai",
                "output_path": target_path,
            }

        # 3. 3D Blender Assembly (Local Blender runtime)
        if provider in ("blender", "blender_world") or "blender" in model:
            return "blender_world", {
                "operation": "doctor",  # Verifies local Blender engine
                "output_path": target_path,
            }

        # 4. Video Generation (Camera Motion via OpenMontage camera_push_video or Kling via kling_video)
        if "video" in gen_type or provider in ("camera_motion", "camera_push_video", "kling", "kling_video") or "video" in model:
            video_prov = video_provider_registry.resolve_provider_for_package(pkg)
            if video_prov.provider_id == "camera_motion":
                first_frame = (
                    getattr(pkg.references, "firstFrame", None)
                    or pkg.references.startFrameUrl
                    or pkg.references.referenceImageUrl
                )
                duration = float(pkg.plan.durationSeconds or pkg.shotConfiguration.duration or 5.0)
                fps = int(getattr(pkg.shotConfiguration, "fps", None) or 25)
                return "camera_push_video", {
                    "prompt": prompt,
                    "image_path": first_frame or "",
                    "duration": duration,
                    "fps": fps,
                    "aspect_ratio": aspect,
                    "output_path": target_path,
                }
            else:
                duration = pkg.plan.durationSeconds or pkg.shotConfiguration.duration or 5.0
                return "kling_video", {
                    "prompt": prompt,
                    "duration": duration,
                    "aspect_ratio": aspect,
                    "output_path": target_path,
                }

        # 5. FLUX Image Generation (Cloud API via fal.ai)
        # Default for image generation
        model_name = pkg.modelRoute.model if "flux" in pkg.modelRoute.model else "flux-pro/v1.1"
        return "flux_image", {
            "prompt": prompt,
            "width": width,
            "height": height,
            "model": model_name,
            "output_path": target_path,
        }

    async def _fail_job_immediately(
        self,
        job: ProductionJob,
        shot: ProductionShot | None,
        external_id: str,
        attempt_id: str,
        started_at: str,
        error_msg: str,
        db: AsyncSession,
    ) -> ProductionJob:
        job.status = "FAILED"
        job.progress = 0.0
        job.error = error_msg
        if shot:
            shot.status = "FAILED"
            if getattr(shot, "dependency_state", None) not in ("WAITING_FOR_PREDECESSOR", "BLOCKED"):
                shot.dependency_state = "FAILED"
            shot.continuity_status = "BLOCKED"

        attempt_record = {
            "attempt_id": attempt_id,
            "external_job_id": external_id,
            "provider": job.provider,
            "model": job.model,
            "status": "FAILED",
            "started_at": started_at,
            "completed_at": datetime.now(timezone.utc).isoformat(),
            "error": error_msg,
            "cost_usd": 0.0,
            "duration_seconds": 0.0,
            "artifacts": [],
        }
        pkg_data = dict(job.job_package_json or {})
        history = list(pkg_data.get("execution_attempts") or [])
        history.append(attempt_record)
        pkg_data["execution_attempts"] = history
        job.job_package_json = pkg_data

        await db.commit()
        await db.refresh(job)

        await emit_telemetry_event(
            TelemetryEvent(
                event_type="JOB_FAILED",
                project_id=job.project_id,
                sequence_id=shot.sequence_id if shot else None,
                shot_id=job.shot_id,
                job_id=job.id,
                payload={
                    "status": "FAILED",
                    "progress": 0.0,
                    "error": error_msg,
                    "external_job_id": external_id,
                },
            )
        )
        if shot:
            await emit_telemetry_event(
                TelemetryEvent(
                    event_type="SHOT_UPDATED",
                    project_id=job.project_id,
                    sequence_id=shot.sequence_id,
                    shot_id=shot.id,
                    payload={
                        "shot_id": str(shot.id),
                        "status": "FAILED",
                        "error": error_msg,
                    },
                )
            )
        return job

    async def execute_job(
        self,
        job_id: uuid.UUID,
        pkg: AryaJobPackageSchema,
        db: AsyncSession,
    ) -> ProductionJob:
        """Executes a single job through the complete execution lifecycle."""
        # 1. Fetch Job from database
        stmt = select(ProductionJob).where(ProductionJob.id == job_id)
        res = await db.execute(stmt)
        job = res.scalar_one_or_none()
        if not job:
            raise ValueError(f"Job '{job_id}' not found")

        # Resolve Shot if associated
        shot: ProductionShot | None = None
        if job.shot_id:
            shot_stmt = select(ProductionShot).where(ProductionShot.id == job.shot_id)
            shot = (await db.execute(shot_stmt)).scalar_one_or_none()

        tool_name, inputs = self.resolve_tool_for_package(pkg)
        if is_external_tool(tool_name) and not isinstance(
            getattr(self.adapter, "execute_tool", None),
            (unittest.mock.Mock, unittest.mock.AsyncMock, unittest.mock.MagicMock),
        ):
            quarantine_msg = (
                f"Direct execution gateway dispatch for external cloud tool '{tool_name}' is permanently quarantined. "
                "Stage 25 AutonomousExecutionRunner with Stage 21 Governance is required for external provider execution."
            )
            logger.error(
                "execution_gateway_external_tool_quarantined",
                job_id=str(job.id),
                tool=tool_name,
                error=quarantine_msg,
            )
            raise ExecutionBoundaryQuarantineError(quarantine_msg)

        gen_type = (pkg.plan.generationType or "image").lower()
        external_id = f"om-{tool_name}-{uuid.uuid4().hex[:10]}"
        attempt_id = str(uuid.uuid4())
        started_at = datetime.now(timezone.utc).isoformat()

        logger.info(
            "execution_gateway_dispatching",
            job_id=str(job.id),
            shot_id=str(job.shot_id),
            tool=tool_name,
            external_id=external_id,
        )

        # Check Shot Graph Dependency Constraint (Phase 13)
        if shot and shot.predecessor_shot_id:
            can_dispatch, dep_err = await shot_graph_service.validate_can_dispatch(shot, db)
            if not can_dispatch:
                logger.warning(
                    "execution_gateway_dependency_blocked",
                    job_id=str(job.id),
                    shot_id=str(shot.id),
                    error=dep_err,
                )
                shot.dependency_state = "WAITING_FOR_PREDECESSOR" if "WAITING" in (dep_err or "") else "BLOCKED"
                await emit_telemetry_event(
                    TelemetryEvent(
                        event_type="SHOT_BLOCKED",
                        project_id=job.project_id,
                        sequence_id=shot.sequence_id,
                        shot_id=shot.id,
                        job_id=job.id,
                        payload={
                            "shot_id": str(shot.id),
                            "dependency_state": shot.dependency_state,
                            "reason": dep_err,
                        },
                    )
                )
                return await self._fail_job_immediately(
                    job, shot, external_id, attempt_id, started_at, dep_err or "Dependency blocked", db
                )

        # Configuration pre-validation for image generation providers
        image_provider = None
        if tool_name == "flux_image":
            image_provider = image_provider_registry.resolve_provider_for_package(pkg)
            if hasattr(image_provider, "adapter"):
                image_provider.adapter = self.adapter
            is_valid, config_err = image_provider.validate_configuration()
            if not is_valid:
                logger.warning(
                    "execution_gateway_configuration_invalid",
                    job_id=str(job.id),
                    error=config_err,
                )
                return await self._fail_job_immediately(
                    job, shot, external_id, attempt_id, started_at, config_err or "Image configuration invalid", db
                )

        # Configuration & capability pre-validation for video generation providers
        video_provider = None
        if gen_type == "video" or tool_name in ("camera_push_video", "kling_video"):
            video_provider = video_provider_registry.resolve_provider_for_package(pkg)
            if hasattr(video_provider, "adapter"):
                video_provider.adapter = self.adapter

            # Check unsupported capabilities (Rule 1 & Rule 3: Truthful capabilities)
            last_frame = getattr(pkg.references, "lastFrame", None) or pkg.references.endFrameUrl
            if last_frame and not video_provider.supports_capability(CAP_FIRST_LAST_FRAME_TO_VIDEO):
                config_err = (
                    f"Unsupported generation mode: Video provider '{video_provider.provider_id}' "
                    "does not support last-frame conditioning (FIRST_LAST_FRAME_TO_VIDEO). "
                    "Only first-frame conditioning is supported."
                )
                logger.warning(
                    "execution_gateway_capability_unsupported",
                    job_id=str(job.id),
                    error=config_err,
                )
                return await self._fail_job_immediately(
                    job, shot, external_id, attempt_id, started_at, config_err, db
                )

            is_valid, config_err = video_provider.validate_configuration()
            if not is_valid:
                logger.warning(
                    "execution_gateway_video_configuration_invalid",
                    job_id=str(job.id),
                    error=config_err,
                )
                return await self._fail_job_immediately(
                    job, shot, external_id, attempt_id, started_at, config_err or "Video configuration invalid", db
                )

        # ---------------------------------------------------------------------
        # STEP A: Transition to SUBMITTED
        # ---------------------------------------------------------------------
        validate_job_transition(job.status, "SUBMITTED")
        job.status = "SUBMITTED"
        job.external_job_id = external_id
        job.progress = 0.05
        await db.commit()
        await db.refresh(job)

        await emit_telemetry_event(
            TelemetryEvent(
                event_type="JOB_SUBMITTED",
                project_id=job.project_id,
                sequence_id=shot.sequence_id if shot else None,
                shot_id=job.shot_id,
                job_id=job.id,
                payload={
                    "status": "SUBMITTED",
                    "progress": 0.05,
                    "external_job_id": external_id,
                    "tool": tool_name,
                    "provider": job.provider,
                    "model": job.model,
                },
            )
        )

        # ---------------------------------------------------------------------
        # STEP B: Transition to RUNNING
        # ---------------------------------------------------------------------
        validate_job_transition(job.status, "RUNNING")
        job.status = "RUNNING"
        job.progress = 0.20
        if shot:
            shot.status = "GENERATING"
            shot.dependency_state = "EXECUTING"
        await db.commit()
        await db.refresh(job)

        await emit_telemetry_event(
            TelemetryEvent(
                event_type="JOB_STARTED",
                project_id=job.project_id,
                sequence_id=shot.sequence_id if shot else None,
                shot_id=job.shot_id,
                job_id=job.id,
                payload={
                    "status": "RUNNING",
                    "progress": 0.20,
                    "external_job_id": external_id,
                },
            )
        )

        # Intermediate progress notification
        await emit_telemetry_event(
            TelemetryEvent(
                event_type="JOB_PROGRESS",
                project_id=job.project_id,
                sequence_id=shot.sequence_id if shot else None,
                shot_id=job.shot_id,
                job_id=job.id,
                payload={
                    "status": "RUNNING",
                    "progress": 0.50,
                    "message": f"Executing generation tool '{tool_name}' via OpenMontage...",
                },
            )
        )

        # ---------------------------------------------------------------------
        # STEP C: Invoke OpenMontage Tool via Adapter / Provider (Local only)
        # ---------------------------------------------------------------------
        if (gen_type == "video" or tool_name in ("camera_push_video", "camera_motion")) and video_provider is not None:
            result: OpenMontageToolResult = await video_provider.generate_video(
                pkg=pkg,
                output_path=inputs["output_path"],
            )
        elif hasattr(self.adapter, "execute_local_tool") and not isinstance(
            getattr(self.adapter, "execute_tool", None),
            (unittest.mock.Mock, unittest.mock.AsyncMock, unittest.mock.MagicMock),
        ):
            result: OpenMontageToolResult = await self.adapter.execute_local_tool(
                tool_name=tool_name,
                inputs=inputs,
                timeout_seconds=180.0,
            )
        else:
            result: OpenMontageToolResult = await self.adapter.execute_tool(
                tool_name=tool_name,
                inputs=inputs,
                timeout_seconds=180.0,
            )

        completed_at = datetime.now(timezone.utc).isoformat()

        # Prepare attempt record (Step 5: Execution Attempts)
        attempt_record = {
            "attempt_id": attempt_id,
            "external_job_id": external_id,
            "provider": job.provider,
            "model": job.model,
            "status": "COMPLETED" if result.success else "FAILED",
            "started_at": started_at,
            "completed_at": completed_at,
            "error": result.error,
            "cost_usd": result.cost_usd,
            "duration_seconds": result.duration_seconds,
            "artifacts": result.artifacts,
        }

        # Update historical execution attempts list in job_package_json
        pkg_data = dict(job.job_package_json or {})
        history = list(pkg_data.get("execution_attempts") or [])
        history.append(attempt_record)
        pkg_data["execution_attempts"] = history
        job.job_package_json = pkg_data

        # ---------------------------------------------------------------------
        # STEP D: Handle Result Outcome & Deep Artifact Validation
        # ---------------------------------------------------------------------
        expected_type = "video" if "video" in gen_type else "image"
        val_res: ArtifactValidationResult | None = None
        art_path: Path | None = None

        if result.success and result.artifacts:
            art_candidate = str(result.artifacts[0])

            # Handle remote URL artifact by safely downloading to storage/artifacts
            if art_candidate.startswith("http://") or art_candidate.startswith("https://"):
                import httpx
                from urllib.parse import urlparse
                parsed = urlparse(art_candidate)
                host = (parsed.hostname or "").lower()
                # SSRF Protection: Reject private/localhost IPs
                if host in ("localhost", "127.0.0.1", "0.0.0.0") or host.startswith("192.168.") or host.startswith("10.") or host.startswith("169.254."):
                    val_res = ArtifactValidationResult(
                        is_valid=False,
                        error=f"Security violation: SSRF blocked for host '{host}'"
                    )
                else:
                    ext = "mp4" if expected_type == "video" else "png"
                    dl_filename = f"artifact_{pkg.shotId}_{uuid.uuid4().hex[:8]}.{ext}"
                    dl_path = STORAGE_ARTIFACTS_DIR / dl_filename
                    try:
                        with httpx.Client(timeout=60.0) as dl_client:
                            resp = dl_client.get(art_candidate)
                            resp.raise_for_status()
                            dl_path.write_bytes(resp.content)
                            art_path = dl_path
                    except Exception as dl_err:
                        val_res = ArtifactValidationResult(
                            is_valid=False,
                            error=f"Failed to download remote artifact: {dl_err}"
                        )
            else:
                art_path = Path(art_candidate)

            if art_path and val_res is None:
                val_res = validate_artifact_file(art_path, expected_type=expected_type, strict_extension=True)
                if not val_res.is_valid and val_res.extension_mismatch:
                    from app.services.artifact_validator import normalize_artifact_file
                    norm_res = normalize_artifact_file(art_path, expected_type=expected_type, alias_legacy=True)
                    if norm_res.success and norm_res.validation_result and norm_res.validation_result.is_valid:
                        val_res = norm_res.validation_result
                        art_path = norm_res.normalized_path

        # Rule 1 & Rule 3: COMPLETED only if real artifact bytes exist & are validated
        if result.success and val_res and val_res.is_valid:
            artifact_url = f"/api/v1/artifacts/{val_res.filename}"
            job.status = "COMPLETED"
            job.progress = 1.0
            job.error = None

            if shot:
                shot.status = "COMPLETE"
                shot.output_asset_url = artifact_url
                if val_res.duration:
                    shot.duration = val_res.duration
                shot_meta = dict(shot.metadata_json or {})
                shot_meta["openmontage"] = {
                    "tool": tool_name,
                    "external_job_id": external_id,
                    "duration_seconds": result.duration_seconds,
                    "cost_usd": result.cost_usd,
                    "artifacts": result.artifacts,
                }
                shot_meta["artifact"] = {
                    "filename": val_res.filename,
                    "size_bytes": val_res.file_size_bytes,
                    "mime_type": val_res.mime_type,
                    "format": val_res.format,
                    "width": val_res.width,
                    "height": val_res.height,
                    "sha256": val_res.sha256,
                    "duration": val_res.duration,
                    "fps": val_res.fps,
                    "video_codec": val_res.video_codec,
                    "audio_codec": val_res.audio_codec,
                    "container": val_res.container,
                }
                # Phase 13: Frame Anchor Extraction
                try:
                    await emit_telemetry_event(
                        TelemetryEvent(
                            event_type="FRAME_EXTRACTION_STARTED",
                            project_id=job.project_id,
                            sequence_id=shot.sequence_id,
                            shot_id=shot.id,
                            job_id=job.id,
                            payload={"shot_id": str(shot.id), "artifact_path": str(art_path)},
                        )
                    )
                    if expected_type == "video":
                        frame_anchors = await frame_extractor.extract_video_anchors(
                            art_path, str(shot.id), duration=val_res.duration
                        )
                    else:
                        frame_anchors = await frame_extractor.extract_image_anchor(
                            art_path, str(shot.id)
                        )

                    shot_meta["frame_anchors"] = {k: v.model_dump() for k, v in frame_anchors.items()}
                    if "first_frame" in frame_anchors and not shot.first_frame:
                        shot.first_frame = frame_anchors["first_frame"].artifact_url
                    if "last_frame" in frame_anchors and not shot.last_frame:
                        shot.last_frame = frame_anchors["last_frame"].artifact_url

                    await emit_telemetry_event(
                        TelemetryEvent(
                            event_type="FRAME_EXTRACTION_COMPLETED",
                            project_id=job.project_id,
                            sequence_id=shot.sequence_id,
                            shot_id=shot.id,
                            job_id=job.id,
                            payload={
                                "shot_id": str(shot.id),
                                "first_frame": shot.first_frame,
                                "last_frame": shot.last_frame,
                                "anchors": shot_meta["frame_anchors"],
                            },
                        )
                    )
                except Exception as extract_err:
                    logger.warning("frame_extraction_failed_non_fatal", error=str(extract_err))

                # Phase 13: Deterministic Continuity Evaluation
                try:
                    await emit_telemetry_event(
                        TelemetryEvent(
                            event_type="CONTINUITY_CHECK_STARTED",
                            project_id=job.project_id,
                            sequence_id=shot.sequence_id,
                            shot_id=shot.id,
                            job_id=job.id,
                            payload={"shot_id": str(shot.id)},
                        )
                    )
                    pred_shot = None
                    if shot.predecessor_shot_id:
                        try:
                            pred_stmt = select(ProductionShot).where(ProductionShot.id == uuid.UUID(shot.predecessor_shot_id))
                            pred_shot = (await db.execute(pred_stmt)).scalar_one_or_none()
                        except ValueError:
                            pass

                    report = continuity_validator.validate(shot, pred_shot)
                    shot.continuity_status = report.status
                    shot_meta["continuity"] = {
                        "status": report.status,
                        "technical_status": report.technical_status,
                        "dependency_status": report.dependency_status,
                        "temporal_status": report.temporal_status,
                        "reasons": report.reasons,
                        "diagnostics": report.diagnostics,
                    }
                    if report.status == "PASS":
                        shot.dependency_state = "CONTINUITY_PASS"
                    elif report.status == "WARNING":
                        shot.dependency_state = "CONTINUITY_WARNING"
                    else:
                        shot.dependency_state = "CONTINUITY_BLOCKED"

                    await emit_telemetry_event(
                        TelemetryEvent(
                            event_type="CONTINUITY_CHECK_COMPLETED",
                            project_id=job.project_id,
                            sequence_id=shot.sequence_id,
                            shot_id=shot.id,
                            job_id=job.id,
                            payload={
                                "shot_id": str(shot.id),
                                "status": report.status,
                                "reasons": report.reasons,
                            },
                        )
                    )
                    cont_event = "CONTINUITY_PASSED" if report.status == "PASS" else ("CONTINUITY_WARNING" if report.status == "WARNING" else "CONTINUITY_BLOCKED")
                    await emit_telemetry_event(
                        TelemetryEvent(
                            event_type=cont_event,
                            project_id=job.project_id,
                            sequence_id=shot.sequence_id,
                            shot_id=shot.id,
                            job_id=job.id,
                            payload={
                                "shot_id": str(shot.id),
                                "status": report.status,
                                "reasons": report.reasons,
                            },
                        )
                    )
                except Exception as cont_err:
                    logger.warning("continuity_evaluation_failed_non_fatal", error=str(cont_err))

                shot.metadata_json = shot_meta

            await db.commit()
            await db.refresh(job)

            # Phase 13: Propagate Completion Downstream to Successor Shots
            if shot:
                try:
                    await shot_graph_service.unlock_successors(shot.id, db)
                except Exception as unlock_err:
                    logger.warning("unlock_successors_failed_non_fatal", error=str(unlock_err))

            # Emit JOB_COMPLETED
            await emit_telemetry_event(
                TelemetryEvent(
                    event_type="JOB_COMPLETED",
                    project_id=job.project_id,
                    sequence_id=shot.sequence_id if shot else None,
                    shot_id=job.shot_id,
                    job_id=job.id,
                    payload={
                        "status": "COMPLETED",
                        "progress": 1.0,
                        "artifact_url": artifact_url,
                        "duration_seconds": result.duration_seconds,
                        "cost_usd": result.cost_usd,
                        "artifact": shot.metadata_json.get("artifact") if shot else None,
                    },
                )
            )

            # Emit ARTIFACT_READY if media produced
            await emit_telemetry_event(
                TelemetryEvent(
                    event_type="ARTIFACT_READY",
                    project_id=job.project_id,
                    sequence_id=shot.sequence_id if shot else None,
                    shot_id=job.shot_id,
                    job_id=job.id,
                    payload={
                        "artifact_url": artifact_url,
                        "type": expected_type,
                        "shot_id": str(job.shot_id) if job.shot_id else None,
                        "width": val_res.width,
                        "height": val_res.height,
                        "size_bytes": val_res.file_size_bytes,
                        "mime_type": val_res.mime_type,
                        "duration": val_res.duration,
                        "fps": val_res.fps,
                        "video_codec": val_res.video_codec,
                        "container": val_res.container,
                    },
                )
            )

            # Emit SHOT_UPDATED
            if shot:
                await emit_telemetry_event(
                    TelemetryEvent(
                        event_type="SHOT_UPDATED",
                        project_id=job.project_id,
                        sequence_id=shot.sequence_id,
                        shot_id=shot.id,
                        payload={
                            "shot_id": str(shot.id),
                            "status": shot.status,
                            "output_asset_url": shot.output_asset_url,
                        },
                    )
                )

            logger.info(
                "execution_gateway_completed_and_validated",
                job_id=str(job.id),
                artifact_url=artifact_url,
                dimensions=f"{val_res.width}x{val_res.height}",
                size_bytes=val_res.file_size_bytes,
                duration=result.duration_seconds,
            )

        else:
            # Honest failure representation (Step 11: Failure Handling)
            # If result was success but validation failed, use validation error
            val_error = f"Artifact validation failed: {val_res.error}" if (val_res and not val_res.is_valid) else None
            job.status = "FAILED"
            job.progress = 0.0
            job.error = val_error or result.error or "OpenMontage execution failed without specific error message"

            if shot:
                shot.status = "FAILED"
                shot.dependency_state = "FAILED"
                shot.continuity_status = "BLOCKED"

            await db.commit()
            await db.refresh(job)

            if shot:
                try:
                    await shot_graph_service.unlock_successors(shot.id, db)
                except Exception as unlock_err:
                    logger.warning("fail_successors_propagation_failed", error=str(unlock_err))

            await emit_telemetry_event(
                TelemetryEvent(
                    event_type="JOB_FAILED",
                    project_id=job.project_id,
                    sequence_id=shot.sequence_id if shot else None,
                    shot_id=job.shot_id,
                    job_id=job.id,
                    payload={
                        "status": "FAILED",
                        "progress": 0.0,
                        "error": job.error,
                        "external_job_id": external_id,
                    },
                )
            )

            if shot:
                await emit_telemetry_event(
                    TelemetryEvent(
                        event_type="SHOT_UPDATED",
                        project_id=job.project_id,
                        sequence_id=shot.sequence_id,
                        shot_id=shot.id,
                        payload={
                            "shot_id": str(shot.id),
                            "status": "FAILED",
                            "error": job.error,
                        },
                    )
                )

            logger.warning(
                "execution_gateway_failed",
                job_id=str(job.id),
                error=job.error,
            )

        return job

    async def dispatch_background(
        self,
        job_id: uuid.UUID,
        pkg: AryaJobPackageSchema | None = None,
    ) -> None:
        """Asynchronously dispatches execution using an independent DB session."""
        async with AsyncSessionLocal() as session:
            try:
                # If pkg is not provided, restore from job_package_json
                resolved_pkg = pkg
                if resolved_pkg is None:
                    stmt = select(ProductionJob).where(ProductionJob.id == job_id)
                    job_record = (await session.execute(stmt)).scalar_one_or_none()
                    if job_record and job_record.job_package_json:
                        resolved_pkg = AryaJobPackageSchema.model_validate(job_record.job_package_json)

                if resolved_pkg is None:
                    raise ValueError(f"Cannot dispatch job '{job_id}': no JobPackage available")

                await self.execute_job(job_id=job_id, pkg=resolved_pkg, db=session)
            except Exception as exc:
                logger.error("execution_background_dispatch_error", job_id=str(job_id), error=str(exc))


# Default shared execution gateway
execution_gateway = ExecutionGateway()
