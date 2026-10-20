"""
AryaOS V1 Phase 8 — Persistent Production REST API Router.

Exposes clean REST contracts under /api/v1 for:
- Projects (/api/v1/projects)
- Sequences (/api/v1/projects/{project_id}/sequences)
- Shots (/api/v1/projects/{project_id}/shots, /api/v1/shots/{shot_id})
- Jobs & AryaJobPackage (/api/v1/projects/{project_id}/jobs, /api/v1/jobs/{job_id})
- Real-time Telemetry Stream (/api/v1/projects/{project_id}/events)
"""

from __future__ import annotations

import asyncio
import json
import re
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import FileResponse, StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import AuthenticatedPrincipal, get_current_principal
from app.database.session import get_db
from app.models.production import ProductionShot
from app.services.artifact_validator import validate_artifact_file
from app.services.authorization_service import verify_project_access
from app.services.execution_gateway import STORAGE_ARTIFACTS_DIR, execution_gateway
from app.services.frame_extractor import frame_extractor
from app.services.continuity_validator import continuity_validator
from app.services.shot_graph_service import shot_graph_service
from app.schemas.production import (
    AryaJobPackageSchema,
    ContinuityCheckResponse,
    FrameExtractionResponse,
    FullProjectTreeResponse,
    JobResponse,
    JobStatusUpdate,
    ProjectCreate,
    ProjectResponse,
    ProjectUpdate,
    SequenceCreate,
    SequenceResponse,
    ShotCreate,
    ShotGraphResponse,
    ShotResponse,
    ShotUpdate,
)
from app.services import production_service

router = APIRouter(prefix="/api/v1", tags=["production"])


# -----------------------------------------------------------------------------
# 1. Projects API
# -----------------------------------------------------------------------------

@router.get(
    "/projects",
    response_model=list[ProjectResponse],
    summary="List accessible projects",
)
async def list_projects(
    db: Annotated[AsyncSession, Depends(get_db)],
    principal: Annotated[AuthenticatedPrincipal, Depends(get_current_principal)],
) -> list[dict]:
    return await production_service.list_projects(db, principal)


@router.post(
    "/projects",
    response_model=ProjectResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new production project",
)
async def create_project(
    data: ProjectCreate,
    db: Annotated[AsyncSession, Depends(get_db)],
    principal: Annotated[AuthenticatedPrincipal, Depends(get_current_principal)],
):
    return await production_service.create_project(db, data, principal)


@router.get(
    "/projects/{project_id}",
    response_model=ProjectResponse,
    summary="Get project by ID",
)
async def get_project(
    project_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    principal: Annotated[AuthenticatedPrincipal, Depends(get_current_principal)],
):
    return await production_service.get_project(db, project_id, principal)


@router.patch(
    "/projects/{project_id}",
    response_model=ProjectResponse,
    summary="Update project metadata",
)
async def update_project(
    project_id: uuid.UUID,
    data: ProjectUpdate,
    db: Annotated[AsyncSession, Depends(get_db)],
    principal: Annotated[AuthenticatedPrincipal, Depends(get_current_principal)],
):
    return await production_service.update_project(db, project_id, data, principal)


@router.delete(
    "/projects/{project_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete project",
)
async def delete_project(
    project_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    principal: Annotated[AuthenticatedPrincipal, Depends(get_current_principal)],
):
    await production_service.delete_project(db, project_id, principal)
    return None


@router.get(
    "/projects/{project_id}/tree",
    response_model=FullProjectTreeResponse,
    summary="Get full nested project tree (sequences and shots)",
)
async def get_project_tree(
    project_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    principal: Annotated[AuthenticatedPrincipal, Depends(get_current_principal)],
):
    return await production_service.get_project_tree(db, project_id, principal)


# -----------------------------------------------------------------------------
# 2. Sequences API
# -----------------------------------------------------------------------------

@router.get(
    "/projects/{project_id}/sequences",
    response_model=list[SequenceResponse],
    summary="List sequences for a project",
)
async def list_sequences(
    project_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    principal: Annotated[AuthenticatedPrincipal, Depends(get_current_principal)],
):
    return await production_service.list_sequences(db, project_id, principal)


@router.post(
    "/projects/{project_id}/sequences",
    response_model=SequenceResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new sequence in a project",
)
async def create_sequence(
    project_id: uuid.UUID,
    data: SequenceCreate,
    db: Annotated[AsyncSession, Depends(get_db)],
    principal: Annotated[AuthenticatedPrincipal, Depends(get_current_principal)],
):
    return await production_service.create_sequence(db, project_id, data, principal)


# -----------------------------------------------------------------------------
# 3. Shots API
# -----------------------------------------------------------------------------

@router.get(
    "/projects/{project_id}/shots",
    response_model=list[ShotResponse],
    summary="List shots for a project",
)
async def list_shots(
    project_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    principal: Annotated[AuthenticatedPrincipal, Depends(get_current_principal)],
    sequence_id: uuid.UUID | None = Query(default=None, description="Optional sequence filter"),
):
    return await production_service.list_shots(db, project_id, principal, sequence_id)


@router.post(
    "/projects/{project_id}/shots",
    response_model=ShotResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new shot in a project",
)
async def create_shot(
    project_id: uuid.UUID,
    data: ShotCreate,
    db: Annotated[AsyncSession, Depends(get_db)],
    principal: Annotated[AuthenticatedPrincipal, Depends(get_current_principal)],
):
    return await production_service.create_shot(db, project_id, data, principal)


@router.get(
    "/shots/{shot_id}",
    response_model=ShotResponse,
    summary="Get shot by ID",
)
async def get_shot(
    shot_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    principal: Annotated[AuthenticatedPrincipal, Depends(get_current_principal)],
):
    return await production_service.get_shot(db, shot_id, principal)


@router.patch(
    "/shots/{shot_id}",
    response_model=ShotResponse,
    summary="Update shot by ID",
)
async def update_shot(
    shot_id: uuid.UUID,
    data: ShotUpdate,
    db: Annotated[AsyncSession, Depends(get_db)],
    principal: Annotated[AuthenticatedPrincipal, Depends(get_current_principal)],
):
    return await production_service.update_shot(db, shot_id, data, principal)


# -----------------------------------------------------------------------------
# Phase 13: Shot Dependency Graph & Continuity API
# -----------------------------------------------------------------------------

@router.get(
    "/projects/{project_id}/graph",
    response_model=ShotGraphResponse,
    summary="Retrieve project shot dependency graph",
)
async def get_project_shot_graph(
    project_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    principal: Annotated[AuthenticatedPrincipal, Depends(get_current_principal)],
):
    await verify_project_access(db, principal, project_id)
    return await shot_graph_service.build_graph(db, project_id)


@router.get(
    "/shots/{shot_id}/dependencies",
    summary="Retrieve shot dependency details and anchors",
)
async def get_shot_dependencies(
    shot_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    principal: Annotated[AuthenticatedPrincipal, Depends(get_current_principal)],
):
    shot = await production_service.get_shot(db, shot_id, principal)
    meta = shot.metadata_json or {}
    return {
        "shot_id": str(shot.id),
        "project_id": str(shot.project_id),
        "predecessor_shot_id": shot.predecessor_shot_id,
        "dependency_state": getattr(shot, "dependency_state", "INDEPENDENT"),
        "continuity_status": shot.continuity_status,
        "frame_anchors": meta.get("frame_anchors", {}),
        "continuity_diagnostics": meta.get("continuity", {}),
    }


@router.get(
    "/shots/{shot_id}/continuity",
    response_model=ContinuityCheckResponse,
    summary="Evaluate and retrieve deterministic continuity for shot",
)
async def get_shot_continuity(
    shot_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    principal: Annotated[AuthenticatedPrincipal, Depends(get_current_principal)],
):
    shot = await production_service.get_shot(db, shot_id, principal)
    pred_shot = None
    if shot.predecessor_shot_id:
        try:
            pred_stmt = select(ProductionShot).where(ProductionShot.id == uuid.UUID(shot.predecessor_shot_id))
            pred_shot = (await db.execute(pred_stmt)).scalar_one_or_none()
        except ValueError:
            pass
    report = continuity_validator.validate(shot, pred_shot)
    return report.to_schema(shot.id, shot.predecessor_shot_id)


@router.post(
    "/shots/{shot_id}/extract-frames",
    response_model=FrameExtractionResponse,
    summary="Extract and validate visual frame anchors from shot artifact",
)
async def extract_shot_frames(
    shot_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    principal: Annotated[AuthenticatedPrincipal, Depends(get_current_principal)],
    force: bool = False,
):
    shot = await production_service.get_shot(db, shot_id, principal)
    if not shot.output_asset_url:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot extract frames: shot has no output artifact.",
        )

    filename = shot.output_asset_url.split("/")[-1].split("?")[0]
    art_path = STORAGE_ARTIFACTS_DIR / filename
    if not art_path.is_file():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Artifact file '{filename}' not found on disk.",
        )

    is_video = "video" in (shot.generation_type or "").lower() or filename.endswith(".mp4")
    if is_video:
        anchors = await frame_extractor.extract_video_anchors(
            art_path, str(shot.id), duration=shot.duration, force_reextract=force
        )
    else:
        anchors = await frame_extractor.extract_image_anchor(art_path, str(shot.id))

    shot_meta = dict(shot.metadata_json or {})
    shot_meta["frame_anchors"] = {k: v.model_dump() for k, v in anchors.items()}
    shot.metadata_json = shot_meta
    if "first_frame" in anchors and not shot.first_frame:
        shot.first_frame = anchors["first_frame"].artifact_url
    if "last_frame" in anchors and not shot.last_frame:
        shot.last_frame = anchors["last_frame"].artifact_url
    await db.commit()
    await db.refresh(shot)

    return FrameExtractionResponse(
        shot_id=shot.id,
        artifact_url=shot.output_asset_url,
        first_frame=anchors.get("first_frame"),
        last_frame=anchors.get("last_frame"),
    )


# -----------------------------------------------------------------------------
# 4. Jobs & AryaJobPackage Contract API (Step 5 & 6)
# -----------------------------------------------------------------------------

@router.get(
    "/projects/{project_id}/jobs",
    response_model=list[JobResponse],
    summary="List jobs for a project",
)
async def list_jobs(
    project_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    principal: Annotated[AuthenticatedPrincipal, Depends(get_current_principal)],
):
    return await production_service.list_jobs(db, project_id, principal)


@router.post(
    "/projects/{project_id}/jobs",
    response_model=JobResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Submit and persist an AryaJobPackage boundary contract",
)
async def create_job(
    project_id: uuid.UUID,
    job_package: AryaJobPackageSchema,
    db: Annotated[AsyncSession, Depends(get_db)],
    principal: Annotated[AuthenticatedPrincipal, Depends(get_current_principal)],
    dispatch: bool = Query(default=False, description="Automatically dispatch execution via ExecutionGateway"),
):
    job = await production_service.create_job_from_package(db, project_id, job_package, principal)
    if dispatch:
        asyncio.create_task(execution_gateway.dispatch_background(job.id, job_package))
    return job


@router.post(
    "/jobs/{job_id}/dispatch",
    response_model=JobResponse,
    summary="Explicitly dispatch a queued job to the Execution Gateway",
)
async def dispatch_job(
    job_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    principal: Annotated[AuthenticatedPrincipal, Depends(get_current_principal)],
    sync: bool = Query(default=False, description="Run synchronously for tests / CLI runs"),
):
    job = await production_service.get_job(db, job_id, principal)
    if job.status not in ("QUEUED", "FAILED", "CREATED"):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Cannot dispatch job in '{job.status}' state. Allowed: QUEUED, FAILED, CREATED",
        )

    pkg = AryaJobPackageSchema.model_validate(job.job_package_json) if job.job_package_json else None
    if not pkg:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Cannot dispatch job: no valid AryaJobPackage recorded",
        )

    if sync:
        return await execution_gateway.execute_job(job_id=job.id, pkg=pkg, db=db)
    else:
        asyncio.create_task(execution_gateway.dispatch_background(job.id, pkg))
        return job


@router.get(
    "/jobs/{job_id}",
    response_model=JobResponse,
    summary="Get job by ID",
)
async def get_job(
    job_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    principal: Annotated[AuthenticatedPrincipal, Depends(get_current_principal)],
):
    return await production_service.get_job(db, job_id, principal)


@router.patch(
    "/jobs/{job_id}",
    response_model=JobResponse,
    summary="Update job status adhering to centralized state machine",
)
async def update_job(
    job_id: uuid.UUID,
    data: JobStatusUpdate,
    db: Annotated[AsyncSession, Depends(get_db)],
    principal: Annotated[AuthenticatedPrincipal, Depends(get_current_principal)],
):
    return await production_service.update_job_status(
        db,
        job_id,
        new_status=data.status,
        progress=data.progress,
        error=data.error,
        external_job_id=data.external_job_id,
        principal=principal,
    )


@router.api_route(
    "/artifacts/{filename}",
    methods=["GET", "HEAD"],
    summary="Serve validated media artifacts",
)
async def get_artifact(filename: str):
    """Secure artifact serving endpoint with path traversal and binary integrity validation."""
    if not re.match(r"^[a-zA-Z0-9_\-\.]+$", filename) or ".." in filename:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid artifact filename",
        )

    file_path = (STORAGE_ARTIFACTS_DIR / filename).resolve()
    if not str(file_path).startswith(str(STORAGE_ARTIFACTS_DIR)):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access forbidden: Path traversal detected",
        )

    if not file_path.is_file():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Artifact '{filename}' not found",
        )

    # Server-side binary validation
    val = validate_artifact_file(file_path, expected_type="any")
    if not val.is_valid:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Artifact binary corrupted or invalid: {val.error}",
        )

    headers = {
        "X-Content-Type-Options": "nosniff",
        "Content-Security-Policy": "default-src 'none'; sandbox",
        "Cache-Control": "public, max-age=86400, immutable",
    }
    return FileResponse(path=file_path, media_type=val.mime_type, headers=headers)


# -----------------------------------------------------------------------------
# 5. Real-Time Telemetry Stream (Step 7)
# -----------------------------------------------------------------------------

@router.get(
    "/projects/{project_id}/events",
    summary="Server-Sent Events (SSE) stream for real-time telemetry",
)
async def stream_project_events(
    project_id: uuid.UUID,
    principal: Annotated[AuthenticatedPrincipal, Depends(get_current_principal)],
):
    """Provides a light-weight SSE transport stream for reactive UI telemetry."""
    q: asyncio.Queue = asyncio.Queue(maxsize=100)
    p_id_str = str(project_id)
    production_service.register_telemetry_subscriber(p_id_str, q)

    async def event_generator():
        try:
            # Yield initial connection heartbeat
            yield f"data: {json.dumps({'event': 'CONNECTED', 'project_id': p_id_str})}\n\n"
            while True:
                try:
                    event = await asyncio.wait_for(q.get(), timeout=15.0)
                    from app.core.sanitization import sanitize_payload
                    if hasattr(event, "payload") and isinstance(event.payload, dict):
                        event.payload = sanitize_payload(event.payload)
                    data_str = event.model_dump_json() if hasattr(event, "model_dump_json") else json.dumps(sanitize_payload(event))
                    yield f"data: {data_str}\n\n"
                except asyncio.TimeoutError:
                    # Keep-alive heartbeat
                    yield f": heartbeat\n\n"
        finally:
            production_service.unregister_telemetry_subscriber(p_id_str, q)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
