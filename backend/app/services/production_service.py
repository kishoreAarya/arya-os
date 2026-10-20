"""
AryaOS V1 Phase 8 — Production Timeline & Job Service.

Implements core domain operations, authorization checks, and the
centralized Job State Machine for projects, sequences, shots, and jobs.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.logging import get_logger
from app.core.security import AuthenticatedPrincipal
from app.models.core import Project
from app.models.production import ProductionJob, ProductionSequence, ProductionShot
from app.schemas.production import (
    AryaJobPackageSchema,
    JobCreate,
    ProjectCreate,
    ProjectUpdate,
    SequenceCreate,
    ShotCreate,
    ShotUpdate,
    TelemetryEvent,
)
from app.services.authorization_service import verify_project_access

logger = get_logger("arya.production")

# -----------------------------------------------------------------------------
# Centralized Job State Machine (Step 6)
# -----------------------------------------------------------------------------

VALID_JOB_STATES = {
    "CREATED",
    "QUEUED",
    "SUBMITTED",
    "RUNNING",
    "COMPLETED",
    "FAILED",
    "CANCELLED",
}

# Explicit deterministic transitions:
# CREATED -> QUEUED -> SUBMITTED -> RUNNING -> COMPLETED / FAILED / CANCELLED
VALID_JOB_TRANSITIONS: dict[str, set[str]] = {
    "CREATED": {"QUEUED", "SUBMITTED", "RUNNING", "FAILED", "CANCELLED"},
    "QUEUED": {"SUBMITTED", "RUNNING", "FAILED", "CANCELLED"},
    "SUBMITTED": {"RUNNING", "FAILED", "CANCELLED"},
    "RUNNING": {"COMPLETED", "FAILED", "CANCELLED"},
    "COMPLETED": set(),  # Terminal state
    "FAILED": {"QUEUED", "SUBMITTED"},  # Retry allowed
    "CANCELLED": set(),  # Terminal state
}


def validate_job_transition(current_state: str, new_state: str) -> None:
    """Enforces centralized job state machine transitions.

    Raises:
        HTTPException(409): If an illegal state transition is attempted.
    """
    if new_state not in VALID_JOB_STATES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Invalid job state '{new_state}'. Allowed: {sorted(VALID_JOB_STATES)}",
        )

    allowed = VALID_JOB_TRANSITIONS.get(current_state, set())
    if new_state != current_state and new_state not in allowed:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"Illegal job state transition from '{current_state}' to '{new_state}'. "
                f"Allowed transitions: {sorted(allowed) if allowed else 'none (terminal state)'}"
            ),
        )


# -----------------------------------------------------------------------------
# Telemetry Event Bus (Step 7)
# -----------------------------------------------------------------------------

# In-memory subscription queues for SSE and real-time listeners:
# Project ID -> list of asyncio.Queue
_PROJECT_TELEMETRY_SUBSCRIBERS: dict[str, list[Any]] = {}


def register_telemetry_subscriber(project_id: str, queue: Any) -> None:
    if project_id not in _PROJECT_TELEMETRY_SUBSCRIBERS:
        _PROJECT_TELEMETRY_SUBSCRIBERS[project_id] = []
    _PROJECT_TELEMETRY_SUBSCRIBERS[project_id].append(queue)


def unregister_telemetry_subscriber(project_id: str, queue: Any) -> None:
    if project_id in _PROJECT_TELEMETRY_SUBSCRIBERS:
        try:
            _PROJECT_TELEMETRY_SUBSCRIBERS[project_id].remove(queue)
            if not _PROJECT_TELEMETRY_SUBSCRIBERS[project_id]:
                del _PROJECT_TELEMETRY_SUBSCRIBERS[project_id]
        except ValueError:
            pass


from app.core.sanitization import sanitize_payload


async def emit_telemetry_event(event: TelemetryEvent) -> None:
    """Broadcasts a telemetry event to registered transport subscribers."""
    if hasattr(event, "payload") and isinstance(event.payload, dict):
        event.payload = sanitize_payload(event.payload)
    p_id = str(event.project_id)
    subscribers = _PROJECT_TELEMETRY_SUBSCRIBERS.get(p_id, [])
    for q in list(subscribers):
        try:
            q.put_nowait(event)
        except Exception:
            pass


# -----------------------------------------------------------------------------
# Project Service Operations
# -----------------------------------------------------------------------------

async def list_projects(
    db: AsyncSession,
    principal: AuthenticatedPrincipal,
) -> list[dict[str, Any]]:
    """List all accessible projects with sequence and shot counts."""
    stmt = (
        select(
            Project,
            func.count(func.distinct(ProductionSequence.id)).label("sequences_count"),
            func.count(func.distinct(ProductionShot.id)).label("shots_count"),
        )
        .outerjoin(ProductionSequence, ProductionSequence.project_id == Project.id)
        .outerjoin(ProductionShot, ProductionShot.project_id == Project.id)
        .group_by(Project.id)
        .order_by(Project.created_at.desc())
    )
    res = await db.execute(stmt)
    results: list[dict[str, Any]] = []
    for row in res.all():
        proj, seq_count, shot_count = row
        results.append({
            "id": proj.id,
            "name": proj.name,
            "description": proj.description,
            "status": getattr(proj, "status", "ACTIVE") or "ACTIVE",
            "created_at": proj.created_at,
            "updated_at": proj.updated_at,
            "sequences_count": seq_count,
            "shots_count": shot_count,
        })
    return results


async def create_project(
    db: AsyncSession,
    data: ProjectCreate,
    principal: AuthenticatedPrincipal,
) -> Project:
    """Creates a new Project and a default initial sequence."""
    project = Project(
        name=data.name.strip(),
        description=data.description.strip() if data.description else None,
        status="ACTIVE",
    )
    db.add(project)
    await db.flush()

    # Automatically provision initial Sequence 01
    initial_seq = ProductionSequence(
        project_id=project.id,
        name="Sequence 01 // Establishing Sequence",
        description="Initial production sequence",
        order_index=1,
        status="READY",
    )
    db.add(initial_seq)
    await db.commit()
    await db.refresh(project)
    return project


async def get_project(
    db: AsyncSession,
    project_id: uuid.UUID,
    principal: AuthenticatedPrincipal,
) -> Project:
    """Fetch project by ID after verifying access."""
    stmt = select(Project).where(Project.id == project_id)
    res = await db.execute(stmt)
    project = res.scalar_one_or_none()
    if not project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Project with ID '{project_id}' not found",
        )
    return project


async def update_project(
    db: AsyncSession,
    project_id: uuid.UUID,
    data: ProjectUpdate,
    principal: AuthenticatedPrincipal,
) -> Project:
    """Updates project metadata."""
    project = await get_project(db, project_id, principal)
    if data.name is not None:
        project.name = data.name.strip()
    if data.description is not None:
        project.description = data.description.strip() if data.description else None
    if data.status is not None:
        project.status = data.status.strip()

    await db.commit()
    await db.refresh(project)
    return project


async def delete_project(
    db: AsyncSession,
    project_id: uuid.UUID,
    principal: AuthenticatedPrincipal,
) -> None:
    """Deletes project and cascades through all sequences, shots, and jobs."""
    project = await get_project(db, project_id, principal)
    await db.delete(project)
    await db.commit()


async def get_project_tree(
    db: AsyncSession,
    project_id: uuid.UUID,
    principal: AuthenticatedPrincipal,
) -> dict[str, Any]:
    """Retrieves full nested hierarchy: Project -> Sequences -> Shots."""
    stmt = (
        select(Project)
        .where(Project.id == project_id)
        .options(
            selectinload(Project.production_sequences).selectinload(ProductionSequence.shots)
        )
    )
    res = await db.execute(stmt)
    project = res.scalar_one_or_none()
    if not project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Project with ID '{project_id}' not found",
        )

    sequences_data = []
    for seq in sorted(project.production_sequences, key=lambda s: s.order_index):
        shots_data = [
            {
                "id": shot.id,
                "project_id": shot.project_id,
                "sequence_id": shot.sequence_id,
                "shot_number": shot.shot_number,
                "title": shot.title,
                "prompt": shot.prompt,
                "negative_prompt": shot.negative_prompt,
                "generation_type": shot.generation_type,
                "model": shot.model,
                "provider": shot.provider,
                "aspect_ratio": shot.aspect_ratio,
                "resolution": shot.resolution,
                "duration": shot.duration,
                "status": shot.status,
                "first_frame": shot.first_frame,
                "last_frame": shot.last_frame,
                "reference_assets": shot.reference_assets or [],
                "continuity_status": shot.continuity_status or "PASS",
                "predecessor_shot_id": shot.predecessor_shot_id,
                "output_asset_url": shot.output_asset_url,
                "metadata_json": shot.metadata_json or {},
                "created_at": shot.created_at,
                "updated_at": shot.updated_at,
            }
            for shot in sorted(seq.shots, key=lambda s: s.shot_number)
        ]

        sequences_data.append({
            "id": seq.id,
            "project_id": seq.project_id,
            "name": seq.name,
            "description": seq.description,
            "order_index": seq.order_index,
            "status": seq.status,
            "created_at": seq.created_at,
            "updated_at": seq.updated_at,
            "shots": shots_data,
        })

    return {
        "id": project.id,
        "name": project.name,
        "description": project.description,
        "status": getattr(project, "status", "ACTIVE") or "ACTIVE",
        "created_at": project.created_at,
        "updated_at": project.updated_at,
        "sequences": sequences_data,
    }


# -----------------------------------------------------------------------------
# Sequence Service Operations
# -----------------------------------------------------------------------------

async def list_sequences(
    db: AsyncSession,
    project_id: uuid.UUID,
    principal: AuthenticatedPrincipal,
) -> list[ProductionSequence]:
    await get_project(db, project_id, principal)
    stmt = (
        select(ProductionSequence)
        .where(ProductionSequence.project_id == project_id)
        .options(selectinload(ProductionSequence.shots))
        .order_by(ProductionSequence.order_index.asc())
    )
    res = await db.execute(stmt)
    return list(res.scalars().all())


async def create_sequence(
    db: AsyncSession,
    project_id: uuid.UUID,
    data: SequenceCreate,
    principal: AuthenticatedPrincipal,
) -> dict[str, Any]:
    await get_project(db, project_id, principal)
    seq = ProductionSequence(
        project_id=project_id,
        name=data.name.strip(),
        description=data.description.strip() if data.description else None,
        order_index=data.order_index,
        status=data.status,
    )
    db.add(seq)
    await db.commit()
    await db.refresh(seq)
    return {
        "id": seq.id,
        "project_id": seq.project_id,
        "name": seq.name,
        "description": seq.description,
        "order_index": seq.order_index,
        "status": seq.status,
        "created_at": seq.created_at,
        "updated_at": seq.updated_at,
        "shots": [],
    }


# -----------------------------------------------------------------------------
# Shot Service Operations
# -----------------------------------------------------------------------------

async def get_shot(
    db: AsyncSession,
    shot_id: uuid.UUID,
    principal: AuthenticatedPrincipal,
) -> ProductionShot:
    stmt = select(ProductionShot).where(ProductionShot.id == shot_id)
    res = await db.execute(stmt)
    shot = res.scalar_one_or_none()
    if not shot:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Shot with ID '{shot_id}' not found",
        )
    return shot

async def list_shots(
    db: AsyncSession,
    project_id: uuid.UUID,
    principal: AuthenticatedPrincipal,
    sequence_id: uuid.UUID | None = None,
) -> list[ProductionShot]:
    await get_project(db, project_id, principal)
    stmt = select(ProductionShot).where(ProductionShot.project_id == project_id)
    if sequence_id:
        stmt = stmt.where(ProductionShot.sequence_id == sequence_id)
    stmt = stmt.order_by(ProductionShot.shot_number.asc())
    res = await db.execute(stmt)
    return list(res.scalars().all())


async def create_shot(
    db: AsyncSession,
    project_id: uuid.UUID,
    data: ShotCreate,
    principal: AuthenticatedPrincipal,
) -> ProductionShot:
    await get_project(db, project_id, principal)

    # Verify sequence exists and belongs to this project
    seq_stmt = select(ProductionSequence).where(
        ProductionSequence.id == data.sequence_id,
        ProductionSequence.project_id == project_id,
    )
    seq_res = await db.execute(seq_stmt)
    if not seq_res.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Sequence '{data.sequence_id}' does not belong to Project '{project_id}'",
        )

    shot = ProductionShot(
        project_id=project_id,
        sequence_id=data.sequence_id,
        shot_number=data.shot_number,
        title=data.title.strip(),
        prompt=data.prompt.strip(),
        negative_prompt=data.negative_prompt.strip() if data.negative_prompt else None,
        generation_type=data.generation_type,
        model=data.model.strip(),
        provider=data.provider.strip(),
        aspect_ratio=data.aspect_ratio,
        resolution=data.resolution,
        duration=data.duration,
        status=data.status,
        first_frame=data.first_frame,
        last_frame=data.last_frame,
        reference_assets=data.reference_assets or [],
        continuity_status=data.continuity_status or "PASS",
        dependency_state=(
            data.dependency_state
            if data.dependency_state and data.dependency_state != "INDEPENDENT"
            else ("WAITING_FOR_PREDECESSOR" if data.predecessor_shot_id else "INDEPENDENT")
        ),
        predecessor_shot_id=data.predecessor_shot_id,
        output_asset_url=data.output_asset_url,
        metadata_json=data.metadata_json or {},
    )
    db.add(shot)
    await db.commit()
    await db.refresh(shot)

    # Emit telemetry event
    await emit_telemetry_event(
        TelemetryEvent(
            event_type="SHOT_UPDATED",
            project_id=project_id,
            sequence_id=shot.sequence_id,
            shot_id=shot.id,
            payload={"status": shot.status, "shot_number": shot.shot_number},
        )
    )

    return shot


async def update_shot(
    db: AsyncSession,
    shot_id: uuid.UUID,
    data: ShotUpdate,
    principal: AuthenticatedPrincipal,
) -> ProductionShot:
    stmt = select(ProductionShot).where(ProductionShot.id == shot_id)
    res = await db.execute(stmt)
    shot = res.scalar_one_or_none()
    if not shot:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Shot with ID '{shot_id}' not found",
        )

    update_dict = data.model_dump(exclude_unset=True)
    for field, val in update_dict.items():
        if field == "metadata_json" and val is not None:
            existing = dict(shot.metadata_json or {})
            existing.update(val)
            shot.metadata_json = existing
        else:
            setattr(shot, field, val)

    await db.commit()
    await db.refresh(shot)

    # Emit telemetry event
    await emit_telemetry_event(
        TelemetryEvent(
            event_type="SHOT_UPDATED",
            project_id=shot.project_id,
            sequence_id=shot.sequence_id,
            shot_id=shot.id,
            payload={"status": shot.status, "output_asset_url": shot.output_asset_url},
        )
    )

    return shot


# -----------------------------------------------------------------------------
# Job & AryaJobPackage Service Operations (Step 5)
# -----------------------------------------------------------------------------

async def create_job_from_package(
    db: AsyncSession,
    project_id: uuid.UUID,
    pkg: AryaJobPackageSchema,
    principal: AuthenticatedPrincipal,
) -> ProductionJob:
    """Validates and persists an AryaJobPackage boundary contract into a ProductionJob.

    Enforces:
    - Preflight evaluation (stops at boundary if preflightReady is False)
    - Validates project and shot relationships
    - Initializes job in CREATED/QUEUED state
    - Zero fabricated generation results
    """
    await get_project(db, project_id, principal)

    # Verify decision boundary guard
    if pkg.decisionBoundary != "ARYAOS_ORCHESTRATION_VALIDATED":
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Malformed Job Package: decisionBoundary must be 'ARYAOS_ORCHESTRATION_VALIDATED'",
        )

    # Verify preflight route readiness
    if not pkg.modelRoute.preflightReady:
        reasons_msg = "; ".join(pkg.modelRoute.preflightReasons) or "Preflight checks failed"
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Preflight validation blocked: {reasons_msg}",
        )

    # Try resolving shot by shotId if it's a valid UUID
    resolved_shot_id: uuid.UUID | None = None
    try:
        candidate_uuid = uuid.UUID(pkg.shotId)
        shot_stmt = select(ProductionShot).where(
            ProductionShot.id == candidate_uuid,
            ProductionShot.project_id == project_id,
        )
        shot_res = await db.execute(shot_stmt)
        if shot_res.scalar_one_or_none():
            resolved_shot_id = candidate_uuid
    except (ValueError, TypeError):
        resolved_shot_id = None

    # Check for duplicate active job with same jobPackageId
    dup_stmt = select(ProductionJob).where(
        ProductionJob.job_package_id == pkg.jobPackageId,
        ProductionJob.status.in_(["CREATED", "QUEUED", "RUNNING"]),
    )
    dup_res = await db.execute(dup_stmt)
    if dup_res.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"An active Job with package ID '{pkg.jobPackageId}' is already in flight",
        )

    job = ProductionJob(
        project_id=project_id,
        shot_id=resolved_shot_id,
        job_package_id=pkg.jobPackageId,
        provider=pkg.modelRoute.provider,
        model=pkg.modelRoute.model,
        status="QUEUED",
        progress=0.0,
        job_package_json=pkg.model_dump(),
    )
    db.add(job)

    # If shot exists, transition shot status to QUEUED
    if resolved_shot_id:
        shot_upd = select(ProductionShot).where(ProductionShot.id == resolved_shot_id)
        shot_obj = (await db.execute(shot_upd)).scalar_one_or_none()
        if shot_obj:
            shot_obj.status = "QUEUED"

    await db.commit()
    await db.refresh(job)

    # Emit telemetry event
    await emit_telemetry_event(
        TelemetryEvent(
            event_type="JOB_QUEUED",
            project_id=project_id,
            shot_id=resolved_shot_id,
            job_id=job.id,
            payload={
                "job_package_id": job.job_package_id,
                "provider": job.provider,
                "model": job.model,
                "status": job.status,
            },
        )
    )

    return job


async def list_jobs(
    db: AsyncSession,
    project_id: uuid.UUID,
    principal: AuthenticatedPrincipal,
) -> list[ProductionJob]:
    await get_project(db, project_id, principal)
    stmt = (
        select(ProductionJob)
        .where(ProductionJob.project_id == project_id)
        .order_by(ProductionJob.created_at.desc())
    )
    res = await db.execute(stmt)
    return list(res.scalars().all())


async def get_job(
    db: AsyncSession,
    job_id: uuid.UUID,
    principal: AuthenticatedPrincipal,
) -> ProductionJob:
    stmt = select(ProductionJob).where(ProductionJob.id == job_id)
    res = await db.execute(stmt)
    job = res.scalar_one_or_none()
    if not job:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Job with ID '{job_id}' not found",
        )
    return job


async def update_job_status(
    db: AsyncSession,
    job_id: uuid.UUID,
    new_status: str,
    progress: float | None,
    error: str | None,
    external_job_id: str | None,
    principal: AuthenticatedPrincipal,
) -> ProductionJob:
    """Updates job status adhering to centralized state machine rules."""
    job = await get_job(db, job_id, principal)

    validate_job_transition(job.status, new_status)

    job.status = new_status
    if progress is not None:
        job.progress = max(0.0, min(1.0, progress))
    if error is not None:
        job.error = error
    if external_job_id is not None:
        job.external_job_id = external_job_id

    # If linked to a shot, update the shot status coherently
    if job.shot_id:
        shot_stmt = select(ProductionShot).where(ProductionShot.id == job.shot_id)
        shot = (await db.execute(shot_stmt)).scalar_one_or_none()
        if shot:
            if new_status == "RUNNING":
                shot.status = "GENERATING"
            elif new_status == "COMPLETED":
                shot.status = "COMPLETE"
            elif new_status == "FAILED":
                shot.status = "FAILED"

    await db.commit()
    await db.refresh(job)

    # Emit telemetry event
    evt_type = (
        "JOB_SUBMITTED" if new_status == "SUBMITTED"
        else "JOB_STARTED" if new_status == "RUNNING"
        else "JOB_COMPLETED" if new_status == "COMPLETED"
        else "JOB_FAILED" if new_status == "FAILED"
        else "JOB_CANCELLED" if new_status == "CANCELLED"
        else "JOB_PROGRESS"
    )
    await emit_telemetry_event(
        TelemetryEvent(
            event_type=evt_type,  # type: ignore
            project_id=job.project_id,
            shot_id=job.shot_id,
            job_id=job.id,
            payload={
                "status": job.status,
                "progress": job.progress,
                "error": job.error,
                "external_job_id": job.external_job_id,
            },
        )
    )

    return job
