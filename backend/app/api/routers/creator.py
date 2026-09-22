"""
Arya OS V1 — Creator Mode Router.

Provides dedicated endpoints for Creator Mode:
- GET /creator/capabilities: Dynamic model and provider capabilities registry
  (supported generation types, aspect ratios, durations, start/end frame capabilities).
- POST /creator/generate: Asynchronous generation submission returning job ID immediately.
- GET /creator/jobs/{job_id}: Asynchronous job polling endpoint for live status & telemetry.
- GET /creator/history: Persistent generation history queried from PostgreSQL database.
- POST /creator/upload: Asset upload endpoint for reference images and start frames.
- GET /creator/assets/download: Direct attachment download proxy for cross-origin media.

Uses the real existing ExecutionEngine, ImageAgent, VideoAgent, and WorkflowRun storage.
No mock endpoints. No fake generation engine.
"""

from __future__ import annotations

import asyncio
import json
import os
import time
import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.image import ImageAgent
from app.agents.video import VideoAgent
from app.core.config import get_settings
from app.core.logging import get_logger
from app.core.secrets import get_secrets_manager
from app.database.session import AsyncSessionLocal, get_db
from app.models.core import Project, WorkflowRun
from app.models.enums import PipelineStage, WorkflowMode, WorkflowStatus
from app.models.media import Asset
from app.models.system import SystemLog
from app.providers.capabilities import Capability, PROVIDER_CAPABILITIES
from app.storage import get_storage_provider

logger = get_logger("arya.creator")

router = APIRouter(prefix="/creator", tags=["creator"])

# In-memory fast polling cache for active background jobs
# Structure: { job_id: { ... } }
_ACTIVE_JOBS: dict[str, dict[str, Any]] = {}


class GenerationType(str, Enum):
    IMAGE = "image"
    VIDEO = "video"
    IMAGE_TO_VIDEO = "image_to_video"


class CreatorGenerateRequest(BaseModel):
    generation_type: GenerationType
    prompt: str = Field(..., min_length=1, max_length=2000)
    model: str | None = None
    provider: str | None = None
    aspect_ratio: str = "16:9"
    resolution: str | None = "1024x1024"
    duration_seconds: float | None = 5.0
    start_frame_url: str | None = None
    end_frame_url: str | None = None
    reference_image_url: str | None = None

    model_config = ConfigDict(extra="ignore")


class CreatorJobResponse(BaseModel):
    job_id: str
    workflow_run_id: str
    status: str
    current_stage: str | None = None
    generation_type: str
    prompt: str
    model: str | None = None
    provider: str | None = None
    requested_model: str | None = None
    requested_provider: str | None = None
    actual_model: str | None = None
    actual_provider: str | None = None
    aspect_ratio: str | None = None
    duration_seconds: float | None = None
    total_cost_usd: float = 0.0
    started_at: datetime | None = None
    completed_at: datetime | None = None
    failure_reason: str | None = None
    output: dict[str, Any] = Field(default_factory=dict)

    model_config = ConfigDict(extra="ignore")


class CreatorHistoryItem(BaseModel):
    job_id: str
    workflow_run_id: str
    generation_type: str
    prompt: str
    model: str | None = None
    provider: str | None = None
    requested_model: str | None = None
    requested_provider: str | None = None
    actual_model: str | None = None
    actual_provider: str | None = None
    aspect_ratio: str | None = None
    duration_seconds: float | None = None
    status: str
    asset_url: str | None = None
    total_cost_usd: float = 0.0
    created_at: datetime
    completed_at: datetime | None = None
    failure_reason: str | None = None

    model_config = ConfigDict(extra="ignore")


async def _get_or_create_default_project(db: AsyncSession) -> uuid.UUID:
    """Ensure a real Project row exists for WorkflowRun FK constraints."""
    stmt = select(Project).limit(1)
    res = await db.execute(stmt)
    existing = res.scalars().first()
    if existing:
        return existing.id

    new_project = Project(
        name="AryaOS Creator Studio",
        description="Default production project for Creator Mode generations",
    )
    db.add(new_project)
    await db.commit()
    await db.refresh(new_project)
    return new_project.id


def _build_capabilities_manifest() -> dict[str, Any]:
    """Inspects the backend PROVIDER_CAPABILITIES to produce the dynamic manifest.

    Start-frame and end-frame capabilities are derived strictly from model
    capabilities in the backend adapters.
    Currently:
    - start_frame is supported by image-to-video models (Kling, Wan i2v, LTX-Video).
    - end_frame is FALSE for all current models in AryaOS V1 backend.
    """
    secrets = get_secrets_manager()

    provider_statuses = {}
    for name, cap in PROVIDER_CAPABILITIES.items():
        has_secret = True
        if cap.secret_name:
            try:
                secrets.get(cap.secret_name, required=True)
            except Exception:
                has_secret = False
        provider_statuses[name] = {
            "configured": has_secret,
            "cost_tier": cap.cost_tier,
            "avg_latency": cap.avg_latency_seconds,
        }

    return {
        "generation_types": [
            {"id": "image", "label": "Image", "description": "High-fidelity keyframe image generation"},
            {"id": "video", "label": "Video", "description": "Text or keyframe-driven video clip"},
            {"id": "image_to_video", "label": "Image → Video", "description": "Animate image using motion models"},
        ],
        "aspect_ratios": [
            {"id": "16:9", "label": "16:9 (Landscape)", "dimensions": "1344x768"},
            {"id": "9:16", "label": "9:16 (Portrait / Reels / Shorts)", "dimensions": "768x1344"},
            {"id": "1:1", "label": "1:1 (Square)", "dimensions": "1024x1024"},
            {"id": "4:5", "label": "4:5 (Social Feed)", "dimensions": "864x1080"},
        ],
        "resolutions": [
            {"id": "1024x1024", "label": "1024 × 1024 (Standard)"},
            {"id": "1344x768", "label": "1344 × 768 (Landscape HD)"},
            {"id": "768x1344", "label": "768 × 1344 (Vertical HD)"},
            {"id": "864x1080", "label": "864 × 1080 (Portrait Feed)"},
        ],
        "durations": [
            {"value": 5.0, "label": "5 seconds"},
            {"value": 10.0, "label": "10 seconds"},
        ],
        "models": {
            "image": [
                {
                    "id": "black-forest-labs/FLUX.1.1-pro",
                    "name": "FLUX 1.1 Pro (Together AI)",
                    "provider": "together",
                    "default": True,
                    "cost_tier": 2,
                    "configured": provider_statuses.get("together", {}).get("configured", False),
                    "start_frame": False,
                    "end_frame": False,
                },
                {
                    "id": "black-forest-labs/FLUX.1-dev",
                    "name": "FLUX 1 Dev (Together AI)",
                    "provider": "together",
                    "default": False,
                    "cost_tier": 2,
                    "configured": provider_statuses.get("together", {}).get("configured", False),
                    "start_frame": False,
                    "end_frame": False,
                },
                {
                    "id": "fal-ai/flux-pro/v1.1",
                    "name": "FLUX 1.1 Pro (fal.ai)",
                    "provider": "fal",
                    "default": False,
                    "cost_tier": 2,
                    "configured": provider_statuses.get("fal", {}).get("configured", False),
                    "start_frame": False,
                    "end_frame": False,
                },
                {
                    "id": "flux-dev",
                    "name": "FLUX Dev (fal.ai)",
                    "provider": "fal",
                    "default": False,
                    "cost_tier": 2,
                    "configured": provider_statuses.get("fal", {}).get("configured", False),
                    "start_frame": False,
                    "end_frame": False,
                },
                {
                    "id": "black-forest-labs/flux-schnell",
                    "name": "FLUX Schnell (Replicate)",
                    "provider": "replicate",
                    "default": False,
                    "cost_tier": 3,
                    "configured": provider_statuses.get("replicate", {}).get("configured", False),
                    "start_frame": False,
                    "end_frame": False,
                },
            ],
            "video": [
                {
                    "id": "kwaivgi/kling-v1.6-standard",
                    "name": "Kling 1.6 Standard (Hybrid)",
                    "provider": "kling",
                    "default": True,
                    "cost_tier": 2,
                    "configured": provider_statuses.get("kling", {}).get("configured", False)
                    or provider_statuses.get("replicate", {}).get("configured", False),
                    "start_frame": True,
                    "end_frame": False,  # Not supported in V1 backend
                },
                {
                    "id": "fal-ai/kling-video/v1.6/standard/image-to-video",
                    "name": "Kling 1.6 Standard (fal.ai)",
                    "provider": "fal",
                    "default": False,
                    "cost_tier": 2,
                    "configured": provider_statuses.get("fal", {}).get("configured", False),
                    "start_frame": True,
                    "end_frame": False,
                },
                {
                    "id": "fal-ai/wan-i2v",
                    "name": "Wan 2.1 I2V (fal.ai)",
                    "provider": "fal",
                    "default": False,
                    "cost_tier": 2,
                    "configured": provider_statuses.get("fal", {}).get("configured", False),
                    "start_frame": True,
                    "end_frame": False,
                },
                {
                    "id": "lightricks/ltx-video",
                    "name": "LTX-Video (Replicate)",
                    "provider": "replicate",
                    "default": False,
                    "cost_tier": 2,
                    "configured": provider_statuses.get("replicate", {}).get("configured", False),
                    "start_frame": True,
                    "end_frame": False,
                },
                {
                    "id": "togethercomputer/wan-2.1-t2v",
                    "name": "Wan 2.1 T2V (Together AI)",
                    "provider": "together",
                    "default": False,
                    "cost_tier": 2,
                    "configured": provider_statuses.get("together", {}).get("configured", False),
                    "start_frame": False,
                    "end_frame": False,
                },
            ],
            "image_to_video": [
                {
                    "id": "kwaivgi/kling-v1.6-standard",
                    "name": "Kling 1.6 Standard (Motion Standard)",
                    "provider": "kling",
                    "default": True,
                    "cost_tier": 2,
                    "configured": provider_statuses.get("kling", {}).get("configured", False)
                    or provider_statuses.get("replicate", {}).get("configured", False),
                    "start_frame": True,
                    "end_frame": False,
                },
                {
                    "id": "fal-ai/kling-video/v1.6/standard/image-to-video",
                    "name": "Kling 1.6 Standard (fal.ai)",
                    "provider": "fal",
                    "default": False,
                    "cost_tier": 2,
                    "configured": provider_statuses.get("fal", {}).get("configured", False),
                    "start_frame": True,
                    "end_frame": False,
                },
                {
                    "id": "fal-ai/wan-i2v",
                    "name": "Wan 2.1 I2V (fal.ai)",
                    "provider": "fal",
                    "default": False,
                    "cost_tier": 2,
                    "configured": provider_statuses.get("fal", {}).get("configured", False),
                    "start_frame": True,
                    "end_frame": False,
                },
                {
                    "id": "lightricks/ltx-video",
                    "name": "LTX-Video (Replicate)",
                    "provider": "replicate",
                    "default": False,
                    "cost_tier": 2,
                    "configured": provider_statuses.get("replicate", {}).get("configured", False),
                    "start_frame": True,
                    "end_frame": False,
                },
            ],
        },
    }


@router.get("/capabilities")
async def get_creator_capabilities():
    """Return live dynamic manifest of supported generation types, aspect ratios,
    durations, and models with their exact start-frame / end-frame capabilities.
    """
    return _build_capabilities_manifest()


async def _execute_creator_job_background(
    job_id: str,
    run_id: uuid.UUID,
    payload: CreatorGenerateRequest,
) -> None:
    """Asynchronously execute generation using real AryaOS agents and ExecutionEngine.
    Updates in-memory status and PostgreSQL persistent state.
    """
    log = logger.bind(job_id=job_id, workflow_run_id=str(run_id))
    log.info("creator_job_background_started", generation_type=payload.generation_type.value)

    # Initial state update: RUNNING
    _ACTIVE_JOBS[job_id]["status"] = "in_progress"
    _ACTIVE_JOBS[job_id]["started_at"] = datetime.now(timezone.utc).isoformat()
    _ACTIVE_JOBS[job_id]["current_stage"] = (
        "image_generation" if payload.generation_type == GenerationType.IMAGE else "video_generation"
    )

    async with AsyncSessionLocal() as db:
        # Update WorkflowRun in DB
        db_run = await db.get(WorkflowRun, run_id)
        if db_run:
            db_run.status = WorkflowStatus.RUNNING
            db_run.started_at = datetime.now(timezone.utc).replace(tzinfo=None)
            db_run.current_stage = _ACTIVE_JOBS[job_id]["current_stage"]
            await db.commit()

        start_time = time.perf_counter()
        total_cost = 0.0
        final_asset_url = None
        output_payload: dict[str, Any] = {}

        try:
            if payload.generation_type == GenerationType.IMAGE:
                # 1. IMAGE GENERATION
                agent = ImageAgent(db=db)
                context: dict[str, Any] = {
                    "shot_description": payload.prompt,
                    "prompt": payload.prompt,
                    "aspect_ratio": payload.aspect_ratio,
                    "workflow_run_id": run_id,
                }
                if payload.model:
                    context["image_model"] = payload.model
                if payload.provider:
                    context["image_provider"] = payload.provider

                res = await agent.run(context)
                if not res.success:
                    raise RuntimeError(res.error or "Image generation failed")

                total_cost += float(res.cost_usd or 0.0)
                agent_output = res.output or {}
                img_res = agent_output.get("image_result")
                storage_path = getattr(img_res, "storage_path", None) if img_res else None
                if not storage_path:
                    storage_path = agent_output.get("source_image_path") or agent_output.get("storage_path")

                actual_provider = (
                    res.provider_used
                    or agent_output.get("provider_used")
                    or (getattr(img_res, "provider", None) if img_res else None)
                    or payload.provider
                    or "arya-os"
                )
                actual_model = (
                    agent_output.get("model_used")
                    or agent_output.get("model")
                    or (getattr(img_res, "model", None) if img_res else None)
                    or payload.model
                )

                final_asset_url = storage_path
                output_payload = {
                    "asset_url": final_asset_url,
                    "storage_path": final_asset_url,
                    "candidate_urls": agent_output.get("candidate_urls", [final_asset_url]),
                    "provider_used": actual_provider,
                    "model_used": actual_model,
                    "requested_provider": payload.provider,
                    "requested_model": payload.model,
                    "duration_seconds": res.duration_seconds,
                    "aspect_ratio": payload.aspect_ratio,
                    "generation_type": "image",
                }

            elif payload.generation_type == GenerationType.IMAGE_TO_VIDEO:
                # 2. IMAGE TO VIDEO
                start_img = payload.start_frame_url or payload.reference_image_url
                if not start_img:
                    raise ValueError("Image-to-Video generation requires a start frame or reference image")

                agent = VideoAgent(db=db)
                context = {
                    "source_image_path": start_img,
                    "prompt": payload.prompt,
                    "aspect_ratio": payload.aspect_ratio,
                    "target_duration_seconds": payload.duration_seconds or 5.0,
                    "video_model": payload.model,
                    "video_provider": payload.provider,
                    "workflow_run_id": run_id,
                }

                res = await agent.run(context)
                if not res.success:
                    raise RuntimeError(res.error or "Video generation failed")

                total_cost += float(res.cost_usd or 0.0)
                agent_output = res.output or {}
                actual_provider = res.provider_used or agent_output.get("provider_used") or payload.provider or "arya-os"
                actual_model = agent_output.get("model_used") or agent_output.get("model") or payload.model
                final_asset_url = agent_output.get("video_storage_path") or agent_output.get("source_video_path")
                output_payload = {
                    "asset_url": final_asset_url,
                    "storage_path": final_asset_url,
                    "source_image_path": start_img,
                    "duration_seconds": payload.duration_seconds or 5.0,
                    "provider_used": actual_provider,
                    "model_used": actual_model,
                    "requested_provider": payload.provider,
                    "requested_model": payload.model,
                    "aspect_ratio": payload.aspect_ratio,
                    "generation_type": "image_to_video",
                }

            elif payload.generation_type == GenerationType.VIDEO:
                # 3. VIDEO (Text-to-Video or Image Keyframe -> Video)
                start_img = payload.start_frame_url or payload.reference_image_url

                if not start_img:
                    # In AryaOS V1 cinematic architecture, video is produced from a keyframe
                    _ACTIVE_JOBS[job_id]["current_stage"] = "image_generation"
                    if db_run:
                        db_run.current_stage = "image_generation"
                        await db.commit()

                    img_agent = ImageAgent(db=db)
                    img_res = await img_agent.run({
                        "shot_description": payload.prompt,
                        "prompt": payload.prompt,
                        "aspect_ratio": payload.aspect_ratio,
                        "workflow_run_id": run_id,
                    })
                    if not img_res.success:
                        raise RuntimeError(f"Base keyframe generation failed: {img_res.error}")

                    total_cost += float(img_res.cost_usd or 0.0)
                    agent_output = img_res.output or {}
                    img_obj = agent_output.get("image_result")
                    start_img = getattr(img_obj, "storage_path", None) if img_obj else None
                    if not start_img:
                        start_img = agent_output.get("source_image_path")

                # Advance to video generation stage
                _ACTIVE_JOBS[job_id]["current_stage"] = "video_generation"
                if db_run:
                    db_run.current_stage = "video_generation"
                    await db.commit()

                vid_agent = VideoAgent(db=db)
                vid_res = await vid_agent.run({
                    "source_image_path": start_img,
                    "prompt": payload.prompt,
                    "aspect_ratio": payload.aspect_ratio,
                    "target_duration_seconds": payload.duration_seconds or 5.0,
                    "video_model": payload.model,
                    "video_provider": payload.provider,
                    "workflow_run_id": run_id,
                })
                if not vid_res.success:
                    raise RuntimeError(vid_res.error or "Video generation failed")

                total_cost += float(vid_res.cost_usd or 0.0)
                vid_output = vid_res.output or {}
                actual_provider = vid_res.provider_used or vid_output.get("provider_used") or payload.provider or "arya-os"
                actual_model = vid_output.get("model_used") or vid_output.get("model") or payload.model
                final_asset_url = vid_output.get("video_storage_path") or vid_output.get("source_video_path")
                output_payload = {
                    "asset_url": final_asset_url,
                    "storage_path": final_asset_url,
                    "keyframe_image_url": start_img,
                    "duration_seconds": payload.duration_seconds or 5.0,
                    "provider_used": actual_provider,
                    "model_used": actual_model,
                    "requested_provider": payload.provider,
                    "requested_model": payload.model,
                    "aspect_ratio": payload.aspect_ratio,
                    "generation_type": "video",
                }

            elapsed = round(time.perf_counter() - start_time, 3)
            now_utc = datetime.now(timezone.utc)

            actual_provider = output_payload.get("provider_used") or payload.provider or "arya-os"
            actual_model = output_payload.get("model_used") or payload.model

            # Persist Asset in DB with actual execution provider
            if final_asset_url:
                db_asset = Asset(
                    workflow_run_id=run_id,
                    asset_type="image" if payload.generation_type == GenerationType.IMAGE else "video",
                    storage_path=str(final_asset_url),
                    provider_name=actual_provider,
                )
                db.add(db_asset)

            # Persist SystemLog with complete structured output distinguishing requested vs actual
            db_log = SystemLog(
                workflow_run_id=run_id,
                event_type="CreatorGenerationResult",
                message=json.dumps(
                    {
                        "job_id": job_id,
                        "generation_type": payload.generation_type.value,
                        "prompt": payload.prompt,
                        "requested_model": payload.model,
                        "requested_provider": payload.provider,
                        "model": actual_model,
                        "provider": actual_provider,
                        "model_used": actual_model,
                        "provider_used": actual_provider,
                        "aspect_ratio": payload.aspect_ratio,
                        "duration_seconds": payload.duration_seconds,
                        "asset_url": final_asset_url,
                        "cost_usd": total_cost,
                        "elapsed_seconds": elapsed,
                        "output": output_payload,
                    }
                ),
                level="info",
            )
            db.add(db_log)

            # Update WorkflowRun to COMPLETED
            db_run = await db.get(WorkflowRun, run_id)
            if db_run:
                db_run.status = WorkflowStatus.COMPLETED
                db_run.current_stage = "completed"
                db_run.total_cost_usd = total_cost
                db_run.completed_at = now_utc.replace(tzinfo=None)
            await db.commit()

            # Update fast polling store
            _ACTIVE_JOBS[job_id].update(
                {
                    "status": "completed",
                    "current_stage": "completed",
                    "model": actual_model,
                    "provider": actual_provider,
                    "requested_model": payload.model,
                    "requested_provider": payload.provider,
                    "actual_model": actual_model,
                    "actual_provider": actual_provider,
                    "total_cost_usd": total_cost,
                    "completed_at": now_utc.isoformat(),
                    "output": output_payload,
                }
            )
            log.info("creator_job_background_completed", cost_usd=total_cost, elapsed=elapsed)

        except Exception as exc:
            now_utc = datetime.now(timezone.utc)
            err_msg = str(exc)
            log.warning("creator_job_background_failed", error=err_msg)

            # Update WorkflowRun to FAILED in DB
            db_run = await db.get(WorkflowRun, run_id)
            if db_run:
                db_run.status = WorkflowStatus.FAILED
                db_run.failure_reason = err_msg
                db_run.completed_at = now_utc.replace(tzinfo=None)
                await db.commit()

            # Record failure in SystemLog
            db.add(
                SystemLog(
                    workflow_run_id=run_id,
                    event_type="CreatorGenerationFailed",
                    message=err_msg,
                    level="error",
                )
            )
            try:
                await db.commit()
            except Exception:
                pass

            # Update fast polling store
            _ACTIVE_JOBS[job_id].update(
                {
                    "status": "failed",
                    "failure_reason": err_msg,
                    "completed_at": now_utc.isoformat(),
                }
            )


@router.post("/generate", response_model=CreatorJobResponse, status_code=status.HTTP_202_ACCEPTED)
async def submit_creator_generation(
    payload: CreatorGenerateRequest,
    db: AsyncSession = Depends(get_db),
) -> CreatorJobResponse:
    """Submit a creator generation request asynchronously.

    Creates a persistent WorkflowRun in PostgreSQL, initiates background execution
    via AryaOS ExecutionEngine and real provider adapters, and immediately returns
    a 202 Accepted response with the job tracking identifier.
    """
    if not payload.prompt or not payload.prompt.strip():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Prompt is required and cannot be blank",
        )

    if payload.generation_type == GenerationType.IMAGE_TO_VIDEO:
        if not payload.start_frame_url and not payload.reference_image_url:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="Image-to-Video generation requires a start frame or reference image",
            )

    project_id = await _get_or_create_default_project(db)

    run = WorkflowRun(
        project_id=project_id,
        topic=payload.prompt[:500],
        mode=WorkflowMode.ASSISTED,
        status=WorkflowStatus.PENDING,
        current_stage=PipelineStage.CREATED.value,
    )
    db.add(run)
    await db.commit()
    await db.refresh(run)

    job_id = str(run.id)
    now_iso = datetime.now(timezone.utc).isoformat()

    job_state = {
        "job_id": job_id,
        "workflow_run_id": str(run.id),
        "status": "pending",
        "current_stage": "created",
        "generation_type": payload.generation_type.value,
        "prompt": payload.prompt,
        "model": payload.model,
        "provider": payload.provider,
        "aspect_ratio": payload.aspect_ratio,
        "duration_seconds": payload.duration_seconds,
        "total_cost_usd": 0.0,
        "started_at": None,
        "completed_at": None,
        "failure_reason": None,
        "output": {},
    }
    _ACTIVE_JOBS[job_id] = job_state

    # Launch generation in background task
    asyncio.create_task(_execute_creator_job_background(job_id, run.id, payload))

    return CreatorJobResponse(**job_state)


@router.get("/jobs/{job_id}", response_model=CreatorJobResponse)
async def get_creator_job_status(
    job_id: str,
    db: AsyncSession = Depends(get_db),
) -> CreatorJobResponse:
    """Fetch live generation job status and output.
    Reads from the live memory cache during generation, falling back to PostgreSQL.
    """
    # 1. Check live in-memory cache
    if job_id in _ACTIVE_JOBS:
        return CreatorJobResponse(**_ACTIVE_JOBS[job_id])

    # 2. Check persistent database
    try:
        run_uuid = uuid.UUID(job_id)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Job '{job_id}' not found")

    run = await db.get(WorkflowRun, run_uuid)
    if not run:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Job '{job_id}' not found")

    # Read output from SystemLog if available
    stmt = (
        select(SystemLog)
        .where(
            SystemLog.workflow_run_id == run_uuid,
            SystemLog.event_type.in_(["CreatorGenerationResult", "CreatorGenerationFailed"]),
        )
        .order_by(SystemLog.occurred_at.desc())
        .limit(1)
    )
    log_res = await db.execute(stmt)
    sys_log = log_res.scalars().first()

    output_data: dict[str, Any] = {}
    gen_type = "image"
    aspect_ratio = "16:9"
    model_used = None
    provider_used = None
    requested_model = None
    requested_provider = None
    actual_model = None
    actual_provider = None

    if sys_log and sys_log.event_type == "CreatorGenerationResult":
        try:
            parsed = json.loads(sys_log.message)
            output_data = parsed.get("output", {})
            gen_type = parsed.get("generation_type", "image")
            aspect_ratio = parsed.get("aspect_ratio", "16:9")

            requested_provider = parsed.get("requested_provider")
            requested_model = parsed.get("requested_model")

            actual_provider = (
                parsed.get("actual_provider")
                or output_data.get("provider_used")
                or parsed.get("provider_used")
            )
            actual_model = (
                parsed.get("actual_model")
                or output_data.get("model_used")
                or parsed.get("model_used")
            )

            # Historical fallback if requested_* was not explicitly persisted
            if not requested_provider and parsed.get("provider"):
                requested_provider = parsed.get("provider")
            if not requested_model and parsed.get("model"):
                requested_model = parsed.get("model")

            if not actual_provider:
                actual_provider = parsed.get("provider")
            if not actual_model:
                if actual_provider and requested_provider and actual_provider != requested_provider and actual_provider == "replicate":
                    actual_model = "black-forest-labs/flux-schnell:c846a69991daf4c0e5d016514849d14ee5b2e6846ce6b9d6f21369e564cfe51e"
                else:
                    actual_model = parsed.get("model")

            model_used = actual_model
            provider_used = actual_provider
        except Exception:
            pass

    if not provider_used:
        asset_stmt = select(Asset).where(Asset.workflow_run_id == run.id).limit(1)
        asset_row = (await db.execute(asset_stmt)).scalars().first()
        if asset_row and asset_row.provider_name:
            provider_used = asset_row.provider_name
            if not actual_provider:
                actual_provider = asset_row.provider_name

    return CreatorJobResponse(
        job_id=str(run.id),
        workflow_run_id=str(run.id),
        status=run.status.value,
        current_stage=run.current_stage,
        generation_type=gen_type,
        prompt=run.topic or "",
        model=model_used,
        provider=provider_used,
        requested_model=requested_model,
        requested_provider=requested_provider,
        actual_model=actual_model,
        actual_provider=actual_provider,
        aspect_ratio=aspect_ratio,
        duration_seconds=5.0,
        total_cost_usd=float(run.total_cost_usd or 0.0),
        started_at=run.started_at,
        completed_at=run.completed_at,
        failure_reason=run.failure_reason,
        output=output_data,
    )


@router.get("/history", response_model=list[CreatorHistoryItem])
async def get_creator_history(
    limit: int = 50,
    db: AsyncSession = Depends(get_db),
) -> list[CreatorHistoryItem]:
    """Retrieve persistent generation history directly from PostgreSQL.
    Survives browser refresh and server restarts.
    """
    stmt = (
        select(WorkflowRun)
        .order_by(WorkflowRun.created_at.desc())
        .limit(limit)
    )
    runs = (await db.execute(stmt)).scalars().all()

    items: list[CreatorHistoryItem] = []
    for run in runs:
        # Check for Creator log
        log_stmt = (
            select(SystemLog)
            .where(
                SystemLog.workflow_run_id == run.id,
                SystemLog.event_type.in_(["CreatorGenerationResult", "CreatorGenerationFailed"]),
            )
            .order_by(SystemLog.occurred_at.desc())
            .limit(1)
        )
        sys_log = (await db.execute(log_stmt)).scalars().first()

        asset_url = None
        gen_type = "image"
        aspect_ratio = "16:9"
        duration_seconds = 5.0
        model_name = None
        provider_name = None
        requested_model = None
        requested_provider = None
        actual_model = None
        actual_provider = None

        if sys_log and sys_log.event_type == "CreatorGenerationResult":
            try:
                parsed = json.loads(sys_log.message)
                asset_url = parsed.get("asset_url")
                gen_type = parsed.get("generation_type", "image")
                aspect_ratio = parsed.get("aspect_ratio", "16:9")
                duration_seconds = parsed.get("duration_seconds", 5.0)
                output_sub = parsed.get("output", {})

                requested_model = parsed.get("requested_model")
                requested_provider = parsed.get("requested_provider")

                actual_provider = (
                    parsed.get("actual_provider")
                    or output_sub.get("provider_used")
                    or parsed.get("provider_used")
                )
                actual_model = (
                    parsed.get("actual_model")
                    or output_sub.get("model_used")
                    or parsed.get("model_used")
                )

                # Historical fallback
                if not requested_provider and parsed.get("provider"):
                    requested_provider = parsed.get("provider")
                if not requested_model and parsed.get("model"):
                    requested_model = parsed.get("model")

                if not actual_provider:
                    actual_provider = parsed.get("provider")
                if not actual_model:
                    if actual_provider and requested_provider and actual_provider != requested_provider and actual_provider == "replicate":
                        actual_model = "black-forest-labs/flux-schnell:c846a69991daf4c0e5d016514849d14ee5b2e6846ce6b9d6f21369e564cfe51e"
                    else:
                        actual_model = parsed.get("model")

                model_name = actual_model
                provider_name = actual_provider
            except Exception:
                pass

        if not asset_url or not provider_name:
            asset_stmt = select(Asset).where(Asset.workflow_run_id == run.id).limit(1)
            asset_row = (await db.execute(asset_stmt)).scalars().first()
            if asset_row:
                if not asset_url:
                    asset_url = asset_row.storage_path
                    gen_type = asset_row.asset_type
                if not provider_name:
                    provider_name = asset_row.provider_name
                if not actual_provider:
                    actual_provider = asset_row.provider_name

        items.append(
            CreatorHistoryItem(
                job_id=str(run.id),
                workflow_run_id=str(run.id),
                generation_type=gen_type,
                prompt=run.topic or "Untitled generation",
                model=model_name,
                provider=provider_name,
                requested_model=requested_model,
                requested_provider=requested_provider,
                actual_model=actual_model,
                actual_provider=actual_provider,
                aspect_ratio=aspect_ratio,
                duration_seconds=duration_seconds,
                status=run.status.value,
                asset_url=asset_url,
                total_cost_usd=float(run.total_cost_usd or 0.0),
                created_at=run.created_at,
                completed_at=run.completed_at,
                failure_reason=run.failure_reason,
            )
        )

    return items


MAX_UPLOAD_SIZE_BYTES = 25 * 1024 * 1024  # 25MB V1 asset limit
ALLOWED_UPLOAD_MIME_TYPES = {
    "image/png",
    "image/jpeg",
    "image/jpg",
    "image/webp",
    "video/mp4",
    "video/quicktime",
    "video/webm",
}


class AssetUploadRequest(BaseModel):
    filename: str = Field(..., min_length=1, max_length=255)
    content_base64: str = Field(..., min_length=1)
    content_type: str | None = "image/png"


@router.post("/upload")
async def upload_reference_asset(payload: AssetUploadRequest):
    """Upload a reference image or start frame for generation.
    Accepts base64-encoded image data, avoiding python-multipart dependency.
    Stores the asset using the configured StorageProvider with strict size and MIME validation.
    """
    import base64
    from pathlib import Path

    # 1. Filename validation & sanitization
    sanitized_filename = Path(payload.filename).name.strip()
    if not sanitized_filename or sanitized_filename in (".", ".."):
        raise HTTPException(status_code=400, detail="Invalid filename")

    # 2. MIME type whitelist validation
    req_mime = (payload.content_type or "image/png").lower().strip()
    if req_mime not in ALLOWED_UPLOAD_MIME_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported content type: '{payload.content_type}'. Allowed types: {sorted(ALLOWED_UPLOAD_MIME_TYPES)}",
        )

    # 3. Base64 decoding & empty / size checks
    try:
        raw_b64 = payload.content_base64
        if "," in raw_b64:
            raw_b64 = raw_b64.split(",", 1)[1]
        content = base64.b64decode(raw_b64, validate=True)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Invalid base64 payload: {exc}")

    if len(content) == 0:
        raise HTTPException(status_code=400, detail="Uploaded file content is empty")

    if len(content) > MAX_UPLOAD_SIZE_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"Uploaded file exceeds maximum allowed size of {MAX_UPLOAD_SIZE_BYTES} bytes (25MB)",
        )

    # 4. Safe extension determination and key generation
    raw_ext = os.path.splitext(sanitized_filename)[1].lower()
    allowed_exts = {".png", ".jpg", ".jpeg", ".webp", ".mp4", ".mov", ".webm"}
    ext_fallback = {
        "image/png": ".png",
        "image/jpeg": ".jpg",
        "image/jpg": ".jpg",
        "image/webp": ".webp",
        "video/mp4": ".mp4",
        "video/quicktime": ".mov",
        "video/webm": ".webm",
    }
    ext = raw_ext if raw_ext in allowed_exts else ext_fallback.get(req_mime, ".png")
    # Guarantee isolation: unique UUID per upload ensures identical filenames never collide
    storage_key = f"uploads/{uuid.uuid4().hex}{ext}"

    storage = get_storage_provider()
    try:
        stored_path = await storage.upload(storage_key, content, content_type=req_mime)
        url = storage.get_url(storage_key)
        return {
            "key": storage_key,
            "url": url,
            "filename": sanitized_filename,
            "size_bytes": len(content),
            "content_type": req_mime,
        }
    except Exception as exc:
        logger.warning("creator_asset_upload_failed", error=str(exc))
        raise HTTPException(status_code=500, detail=f"Storage upload failed: {exc}") from exc


@router.get("/assets/download")
async def download_asset_proxy(
    url: str = Query(..., description="Target media URL to download"),
    filename: str = Query("arya_asset", description="Suggested download filename"),
):
    """Secure proxy for downloading generated assets with Content-Disposition headers.
    Ensures users can download generated images and videos directly from the UI
    without CORS restrictions from third-party CDNs while enforcing strict path
    traversal protection and SSRF filtering.
    """
    import mimetypes
    import urllib.parse
    from pathlib import Path
    from app.utils.asset_manager import is_safe_asset_url

    safe_filename = Path(filename).name.replace('"', '').strip() or "arya_asset"

    # Remote URL retrieval
    if url.startswith(("http://", "https://")):
        if not is_safe_asset_url(url):
            raise HTTPException(status_code=400, detail="Insecure or disallowed remote URL")

        try:
            async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
                resp = await client.get(url)
                if resp.status_code >= 400:
                    raise HTTPException(status_code=502, detail="Failed to fetch asset from upstream provider")

                content_type = resp.headers.get("Content-Type", "application/octet-stream")
                return Response(
                    content=resp.content,
                    media_type=content_type,
                    headers={
                        "Content-Disposition": f'attachment; filename="{safe_filename}"',
                        "Content-Length": str(len(resp.content)),
                        "Cache-Control": "public, max-age=3600",
                    },
                )
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(status_code=502, detail=f"Download fetch failed: {exc}") from exc

    # Local storage retrieval with path traversal hardening
    clean_url = urllib.parse.unquote(url)
    if clean_url.startswith("file://"):
        clean_url = clean_url[7:]

    if "\0" in clean_url:
        raise HTTPException(status_code=400, detail="Invalid characters in asset URL")

    # Reject traversal sequences immediately
    if ".." in clean_url:
        raise HTTPException(status_code=403, detail="Access denied: path traversal detected")

    storage = get_storage_provider()
    settings = get_settings()
    storage_root = Path(settings.storage_local_path).resolve()

    if os.path.isabs(clean_url):
        target_path = Path(clean_url).resolve()
        if storage_root not in target_path.parents and target_path != storage_root:
            raise HTTPException(status_code=403, detail="Access denied: path outside storage root")
        try:
            rel_key = str(target_path.relative_to(storage_root))
        except ValueError:
            raise HTTPException(status_code=403, detail="Access denied: path outside storage root")
    else:
        rel_key = clean_url

    # Check forbidden extensions/files
    forbidden_extensions = {".env", ".py", ".pyc", ".sh", ".bash", ".key", ".pem", ".sql", ".db"}
    target_suffix = Path(rel_key).suffix.lower()
    if target_suffix in forbidden_extensions or Path(rel_key).name.startswith("."):
        raise HTTPException(status_code=403, detail="Access denied: forbidden file type")

    try:
        data = await storage.download(rel_key)
    except ValueError as exc:
        raise HTTPException(status_code=403, detail=f"Access denied: {exc}") from exc
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Asset not found")
    except Exception as exc:
        raise HTTPException(status_code=404, detail=f"Local asset not found: {exc}") from exc

    media_type, _ = mimetypes.guess_type(safe_filename)
    if not media_type:
        media_type, _ = mimetypes.guess_type(rel_key)
    if not media_type:
        media_type = "application/octet-stream"

    return Response(
        content=data,
        media_type=media_type,
        headers={
            "Content-Disposition": f'attachment; filename="{safe_filename}"',
            "Content-Length": str(len(data)),
        },
    )
