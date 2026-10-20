"""
Authorization and Project Isolation Service for AryaOS V1.

Enforces multi-project isolation, role-based ownership, and IDOR protection:
- Principal resolution and project membership checks.
- Constant-time and secure SHA-256 API key hashing.
- Scoped query builders for WorkflowRuns and ApprovalCheckpoints.
- Strict 404 (Not Found) responses on cross-project unauthorized resource access
  to prevent information leakage / IDOR enumeration.
- 403 (Forbidden) on explicit unauthorized project resource creation.
"""
from __future__ import annotations

import hashlib
import secrets
import uuid
from typing import TYPE_CHECKING

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.models.approval import ApprovalCheckpoint
from app.models.core import ApiKey, Project, ProjectMembership, WorkflowRun

if TYPE_CHECKING:
    from app.core.security import AuthenticatedPrincipal

logger = get_logger("arya.services.authorization")


def hash_api_key(key: str) -> str:
    """Generate SHA-256 hex digest of an API key."""
    return hashlib.sha256(key.strip().encode("utf-8")).hexdigest()


def generate_api_key(prefix: str = "arya_") -> str:
    """Generate a high-entropy random API key."""
    return f"{prefix}{secrets.token_urlsafe(32)}"


async def create_api_key(
    db: AsyncSession,
    name: str,
    is_admin: bool = False,
    principal_type: str = "service_account",
    raw_key: str | None = None,
    creator_principal: AuthenticatedPrincipal | None = None,
) -> tuple[ApiKey, str]:
    """Create a new API key record and return (ApiKey, raw_key_string)."""
    if creator_principal is not None and not creator_principal.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Forbidden: Admin access required to create API keys",
        )

    if raw_key is None:
        raw_key = generate_api_key()
    raw_key = raw_key.strip()
    key_hash = hash_api_key(raw_key)
    key_prefix = raw_key[:12]

    api_key = ApiKey(
        name=name,
        key_hash=key_hash,
        key_prefix=key_prefix,
        is_admin=is_admin,
        is_active=True,
        principal_type=principal_type,
    )
    db.add(api_key)
    await db.commit()
    await db.refresh(api_key)
    return api_key, raw_key


async def promote_api_key_to_human(
    db: AsyncSession,
    target_key_id: uuid.UUID,
    admin_principal: AuthenticatedPrincipal,
) -> ApiKey:
    """Administratively promote an active API key to human operator status.

    Requirements:
    - Caller must be an authenticated administrator (admin_principal.is_admin is True).
    - System master keys and development bypass principals are excluded (cannot perform promotion).
    - Target key must exist and be currently active.
    - Emits structured audit log for full provenance tracking.
    """
    if admin_principal.principal_type in ("system", "development") or not admin_principal.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Forbidden: Only authenticated human administrators can promote API keys",
        )

    target_key = await db.get(ApiKey, target_key_id)
    if not target_key:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"API key '{target_key_id}' not found",
        )

    if not target_key.is_active:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Cannot promote inactive API key '{target_key.name}'",
        )

    target_key.principal_type = "human"
    await db.commit()
    await db.refresh(target_key)

    logger.info(
        "api_key_promoted_to_human",
        target_key_id=str(target_key.id),
        target_key_name=target_key.name,
        promoted_by_principal_id=str(admin_principal.api_key_id) if admin_principal.api_key_id else None,
        promoted_by_principal_name=admin_principal.name,
        promoted_by_actor_type=admin_principal.principal_type,
    )
    return target_key


async def add_project_membership(
    db: AsyncSession,
    project_id: uuid.UUID,
    api_key_id: uuid.UUID,
    role: str = "owner",
    creator_principal: AuthenticatedPrincipal | None = None,
) -> ProjectMembership:
    """Associate an API key with a project."""
    if creator_principal is not None and not creator_principal.is_admin:
        allowed = await get_authorized_project_ids(db, creator_principal)
        if allowed is None or project_id not in allowed:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Forbidden: Not authorized to add members to this project",
            )

    membership = ProjectMembership(
        project_id=project_id,
        api_key_id=api_key_id,
        role=role,
    )
    db.add(membership)
    await db.commit()
    await db.refresh(membership)
    return membership


async def get_authorized_project_ids(
    db: AsyncSession,
    principal: AuthenticatedPrincipal,
) -> set[uuid.UUID] | None:
    """Return the set of project UUIDs authorized for this principal.

    Returns:
        None if principal is an admin (unrestricted access to all projects).
        set of UUIDs if principal is a scoped key.
        empty set if principal has no project memberships.
    """
    if principal.is_admin:
        return None
    if principal.api_key_id is None:
        return set()

    stmt = select(ProjectMembership.project_id).where(
        ProjectMembership.api_key_id == principal.api_key_id
    )
    result = await db.execute(stmt)
    return set(result.scalars().all())


async def verify_project_access(
    db: AsyncSession,
    principal: AuthenticatedPrincipal,
    project_id: uuid.UUID,
    not_found_status_code: int = status.HTTP_404_NOT_FOUND,
) -> Project:
    """Verify that principal has access to the specified project.

    Raises:
        HTTPException(not_found_status_code): If project does not exist.
        HTTPException(403): If principal is not authorized for this project.
    """
    project = await db.get(Project, project_id)
    if project is None:
        raise HTTPException(
            status_code=not_found_status_code,
            detail=f"Project {project_id} not found",
        )
    if principal.is_admin:
        return project

    allowed_ids = await get_authorized_project_ids(db, principal)
    if allowed_ids is None or project_id in allowed_ids:
        return project

    logger.warning(
        "unauthorized_project_access_attempt",
        principal=principal.name,
        project_id=str(project_id),
    )
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Forbidden: Not authorized for this project",
    )


async def verify_workflow_access(
    db: AsyncSession,
    principal: AuthenticatedPrincipal,
    workflow_run_id: uuid.UUID,
) -> WorkflowRun:
    """Verify that principal has access to the specified workflow run.

    IDOR Protection: If run does not exist OR principal is not authorized,
    raises 404 (Not Found) to avoid leaking resource existence across projects.

    Raises:
        HTTPException(404): If run does not exist or principal is unauthorized.
    """
    from app.services.workflow_service import get_workflow_run

    run = await get_workflow_run(db, workflow_run_id)
    if run is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"WorkflowRun {workflow_run_id} not found",
        )
    if principal.is_admin:
        return run

    allowed_ids = await get_authorized_project_ids(db, principal)
    if allowed_ids is None or run.project_id in allowed_ids:
        return run

    logger.warning(
        "idor_workflow_run_access_blocked",
        principal=principal.name,
        workflow_run_id=str(workflow_run_id),
        run_project_id=str(run.project_id),
    )
    # Mask existence with 404
    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail=f"WorkflowRun {workflow_run_id} not found",
    )


async def verify_checkpoint_access(
    db: AsyncSession,
    principal: AuthenticatedPrincipal,
    checkpoint_id: uuid.UUID,
    for_update: bool = False,
) -> tuple[ApprovalCheckpoint, WorkflowRun]:
    """Verify that principal has access to the specified approval checkpoint.

    IDOR Protection: If checkpoint does not exist, run does not exist,
    or principal is not authorized, raises 404 (Not Found).

    Raises:
        HTTPException(404): If checkpoint does not exist or principal is unauthorized.
    """
    stmt = select(ApprovalCheckpoint).where(ApprovalCheckpoint.id == checkpoint_id)
    if for_update:
        stmt = stmt.with_for_update()
    result = await db.execute(stmt)
    checkpoint = result.scalar_one_or_none()

    if checkpoint is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Checkpoint not found",
        )

    if for_update:
        run = await db.get(WorkflowRun, checkpoint.workflow_run_id, with_for_update=True)
    else:
        run = await db.get(WorkflowRun, checkpoint.workflow_run_id)
    if run is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Checkpoint not found",
        )

    if principal.is_admin:
        return checkpoint, run

    allowed_ids = await get_authorized_project_ids(db, principal)
    if allowed_ids is None or run.project_id in allowed_ids:
        return checkpoint, run

    logger.warning(
        "idor_checkpoint_access_blocked",
        principal=principal.name,
        checkpoint_id=str(checkpoint_id),
        workflow_run_id=str(checkpoint.workflow_run_id),
    )
    # Mask existence with 404
    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail="Checkpoint not found",
    )
