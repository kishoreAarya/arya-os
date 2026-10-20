"""
AryaOS V1 Phase 8 — Pydantic Schemas for Production Persistence API.

Defines the clean REST API request and response contracts for:
- Projects
- Production Sequences
- Production Shots
- Production Jobs (including AryaJobPackage boundary contract validation)
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.core.sanitization import sanitize_payload, sanitize_text


# -----------------------------------------------------------------------------
# Project Schemas
# -----------------------------------------------------------------------------

class ProjectCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(..., min_length=1, max_length=255, description="Project name")
    description: str | None = Field(default=None, max_length=2000, description="Project description")


class ProjectUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=2000)
    status: str | None = Field(default=None, max_length=50)


class ProjectResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    description: str | None = None
    status: str = "ACTIVE"
    created_at: datetime
    updated_at: datetime
    sequences_count: int = 0
    shots_count: int = 0


# -----------------------------------------------------------------------------
# Shot Schemas
# -----------------------------------------------------------------------------

class ShotCreate(BaseModel):
    model_config = ConfigDict(extra="ignore")

    sequence_id: uuid.UUID
    shot_number: int = Field(default=1, ge=1)
    title: str = Field(..., min_length=1, max_length=255)
    prompt: str = Field(..., min_length=1)
    negative_prompt: str | None = None
    generation_type: str = Field(default="image", max_length=50)
    model: str = Field(..., min_length=1, max_length=255)
    provider: str = Field(..., min_length=1, max_length=100)
    aspect_ratio: str = Field(default="16:9", max_length=50)
    resolution: str | None = None
    duration: float | None = None
    status: str = Field(default="READY", max_length=50)
    first_frame: str | None = None
    last_frame: str | None = None
    reference_assets: list[str] = Field(default_factory=list)
    continuity_status: str | None = "PASS"
    dependency_state: str = Field(default="INDEPENDENT", max_length=50)
    predecessor_shot_id: str | None = None
    output_asset_url: str | None = None
    metadata_json: dict[str, Any] = Field(default_factory=dict)


class ShotUpdate(BaseModel):
    model_config = ConfigDict(extra="ignore")

    title: str | None = None
    prompt: str | None = None
    negative_prompt: str | None = None
    generation_type: str | None = None
    model: str | None = None
    provider: str | None = None
    aspect_ratio: str | None = None
    resolution: str | None = None
    duration: float | None = None
    status: str | None = None
    first_frame: str | None = None
    last_frame: str | None = None
    reference_assets: list[str] | None = None
    continuity_status: str | None = None
    dependency_state: str | None = None
    predecessor_shot_id: str | None = None
    output_asset_url: str | None = None
    metadata_json: dict[str, Any] | None = None


class ShotResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    project_id: uuid.UUID
    sequence_id: uuid.UUID
    shot_number: int
    title: str
    prompt: str
    negative_prompt: str | None = None
    generation_type: str
    model: str
    provider: str
    aspect_ratio: str
    resolution: str | None = None
    duration: float | None = None
    status: str
    first_frame: str | None = None
    last_frame: str | None = None
    reference_assets: list[str] = Field(default_factory=list)
    continuity_status: str | None = "PASS"
    dependency_state: str = "INDEPENDENT"
    predecessor_shot_id: str | None = None
    output_asset_url: str | None = None
    metadata_json: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime


# -----------------------------------------------------------------------------
# Sequence Schemas
# -----------------------------------------------------------------------------

class SequenceCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(..., min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=2000)
    order_index: int = Field(default=1, ge=1)
    status: str = Field(default="READY", max_length=50)


class SequenceResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    project_id: uuid.UUID
    name: str
    description: str | None = None
    order_index: int
    status: str
    created_at: datetime
    updated_at: datetime
    shots: list[ShotResponse] = Field(default_factory=list)


class FullProjectTreeResponse(BaseModel):
    """Unified project hierarchy matching the frontend Project interface."""
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    description: str | None = None
    status: str = "ACTIVE"
    created_at: datetime
    updated_at: datetime
    sequences: list[SequenceResponse] = Field(default_factory=list)


# -----------------------------------------------------------------------------
# Job & AryaJobPackage Boundary Contract Schemas
# -----------------------------------------------------------------------------

class AryaJobPackagePlan(BaseModel):
    model_config = ConfigDict(extra="ignore")

    title: str
    prompt: str
    generationType: str
    mode: str | None = None
    durationSeconds: float | None = None
    predecessorShotId: str | None = None
    successorShotId: str | None = None
    sourceShot: str | None = None
    predecessorShot: str | None = None
    dependencies: list[str] = Field(default_factory=list)
    isFirstShotInSequence: bool = True


class AryaJobPackageReferences(BaseModel):
    model_config = ConfigDict(extra="ignore")

    startFrameUrl: str | None = None
    endFrameUrl: str | None = None
    firstFrame: str | None = None
    lastFrame: str | None = None
    referenceImageUrl: str | None = None
    referenceAssets: list[str] = Field(default_factory=list)
    referenceVideos: list[str] = Field(default_factory=list)
    visualIdentityReferences: list[str] | None = None


class AryaJobPackageModelRoute(BaseModel):
    model_config = ConfigDict(extra="ignore")

    provider: str
    model: str
    modelName: str
    mode: str
    preflightReady: bool
    preflightReasons: list[str] = Field(default_factory=list)
    availability: str = "AVAILABLE"
    estimatedCostUsd: float | None = None
    qualityTier: str | None = None


class AryaJobPackageShotConfig(BaseModel):
    model_config = ConfigDict(extra="ignore")

    aspectRatio: str = "16:9"
    resolution: str | None = None
    duration: float | None = None
    fps: int | None = None
    firstFrame: str | None = None
    lastFrame: str | None = None


class AryaJobPackageContinuity(BaseModel):
    model_config = ConfigDict(extra="ignore")

    character: str = "UNAVAILABLE"
    environment: str = "PASS"
    visual: str = "PASS"
    temporal: str = "PASS"
    startFrame: str = "NOT_APPLICABLE"


class AryaJobPackageSchema(BaseModel):
    """Validates the Phase 7 AryaJobPackage boundary contract from frontend."""
    model_config = ConfigDict(extra="ignore")

    jobPackageId: str = Field(..., min_length=1)
    intentId: str | None = None
    createdAt: str
    projectId: str
    sequenceId: str
    shotId: str
    shotOrder: int = 1
    plan: AryaJobPackagePlan
    references: AryaJobPackageReferences
    modelRoute: AryaJobPackageModelRoute
    shotConfiguration: AryaJobPackageShotConfig
    continuityRequirements: AryaJobPackageContinuity
    outputRequirements: dict[str, Any]
    decisionBoundary: Literal["ARYAOS_ORCHESTRATION_VALIDATED"] = "ARYAOS_ORCHESTRATION_VALIDATED"
    executionPayload: dict[str, Any]


class JobCreate(BaseModel):
    model_config = ConfigDict(extra="ignore")

    shot_id: uuid.UUID | None = None
    job_package_id: str | None = None
    provider: str | None = None
    model: str | None = None
    job_package: AryaJobPackageSchema | None = None


class JobStatusUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["CREATED", "QUEUED", "SUBMITTED", "RUNNING", "COMPLETED", "FAILED", "CANCELLED"]
    progress: float | None = Field(default=None, ge=0.0, le=1.0)
    external_job_id: str | None = None
    error: str | None = None


class JobResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    project_id: uuid.UUID
    shot_id: uuid.UUID | None = None
    job_package_id: str
    provider: str
    model: str
    status: str
    progress: float
    external_job_id: str | None = None
    error: str | None = None
    job_package: dict[str, Any] | None = None
    created_at: datetime
    updated_at: datetime

    @field_validator("job_package", mode="after")
    @classmethod
    def sanitize_job_package(cls, v: Any) -> Any:
        if v is not None:
            return sanitize_payload(v)
        return v

    @field_validator("error", mode="after")
    @classmethod
    def sanitize_job_error(cls, v: str | None) -> str | None:
        if v is not None:
            return sanitize_text(v)
        return v


# -----------------------------------------------------------------------------
# Real-Time Telemetry Event Schema (Step 6 & 7)
# -----------------------------------------------------------------------------

class TelemetryEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_type: Literal[
        "JOB_CREATED",
        "JOB_QUEUED",
        "JOB_SUBMITTED",
        "JOB_STARTED",
        "JOB_PROGRESS",
        "JOB_COMPLETED",
        "JOB_FAILED",
        "JOB_CANCELLED",
        "ARTIFACT_READY",
        "SHOT_UPDATED",
        "CONTINUITY_UPDATED",
        "ROUTE_UPDATED",
        # Phase 13 Temporal & Dependency Telemetry Events
        "SHOT_BLOCKED",
        "SHOT_UNLOCKED",
        "FRAME_EXTRACTION_STARTED",
        "FRAME_EXTRACTION_COMPLETED",
        "CONTINUITY_CHECK_STARTED",
        "CONTINUITY_CHECK_COMPLETED",
        "CONTINUITY_WARNING",
        "CONTINUITY_BLOCKED",
        "CONTINUITY_PASSED",
    ]
    project_id: uuid.UUID
    sequence_id: uuid.UUID | None = None
    shot_id: uuid.UUID | None = None
    job_id: uuid.UUID | None = None
    payload: dict[str, Any] = Field(default_factory=dict)
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @field_validator("payload", mode="after")
    @classmethod
    def sanitize_telemetry_payload(cls, v: Any) -> Any:
        if v is not None:
            return sanitize_payload(v)
        return v


# -----------------------------------------------------------------------------
# Phase 13: Shot Graph & Frame Anchor Schemas
# -----------------------------------------------------------------------------

class FrameAnchorInfo(BaseModel):
    model_config = ConfigDict(extra="ignore")

    anchor_type: Literal["first_frame", "last_frame", "keyframe"]
    file_path: str
    artifact_url: str
    timestamp: float = 0.0
    width: int
    height: int
    mime_type: str = "image/png"
    sha256: str
    status: Literal["VERIFIED", "MISSING", "INVALID"] = "VERIFIED"


class FrameExtractionResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    shot_id: uuid.UUID
    artifact_url: str
    first_frame: FrameAnchorInfo | None = None
    last_frame: FrameAnchorInfo | None = None
    extracted_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class ContinuityCheckResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    shot_id: uuid.UUID
    predecessor_shot_id: str | None = None
    status: Literal["PASS", "WARNING", "BLOCKED"]
    technical_status: Literal["PASS", "WARNING", "BLOCKED"]
    dependency_status: Literal["PASS", "WARNING", "BLOCKED"]
    temporal_status: Literal["PASS", "WARNING", "BLOCKED"]
    reasons: list[str] = Field(default_factory=list)
    diagnostics: dict[str, Any] = Field(default_factory=dict)


class ShotGraphNode(BaseModel):
    model_config = ConfigDict(extra="ignore")

    shot_id: str
    sequence_id: str
    shot_number: int
    title: str
    generation_type: str
    status: str
    dependency_state: str
    continuity_status: str | None = None
    predecessor_shot_id: str | None = None
    successor_shot_ids: list[str] = Field(default_factory=list)
    first_frame: str | None = None
    last_frame: str | None = None
    output_asset_url: str | None = None
    frame_anchors: dict[str, Any] = Field(default_factory=dict)
    can_dispatch: bool = True
    is_blocked: bool = False
    unmet_dependencies: list[str] = Field(default_factory=list)


class ShotGraphEdge(BaseModel):
    model_config = ConfigDict(extra="ignore")

    source_shot_id: str
    target_shot_id: str
    relationship_type: Literal["last_frame_to_first_frame", "reference_asset", "independent_branch"] = "last_frame_to_first_frame"
    status: Literal["SATISFIED", "PENDING", "BLOCKED"] = "PENDING"


class ShotGraphResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    project_id: uuid.UUID
    nodes: list[ShotGraphNode] = Field(default_factory=list)
    edges: list[ShotGraphEdge] = Field(default_factory=list)
    roots: list[str] = Field(default_factory=list)
    has_cycles: bool = False
    cycle_nodes: list[str] = Field(default_factory=list)
