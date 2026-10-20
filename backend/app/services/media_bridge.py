"""
AryaOS V1 Stage 25 Phase 3.2.4.1 — Bridge Contract & Job Package Schema Synthesis.

Provides an offline, typed transformation and boundary validation layer connecting
AryaOS autonomous action nodes (AutonomousActionNode) to OpenMontage's existing
AryaJobPackageSchema boundary contract.

ARCHITECTURAL BOUNDARIES:
- AryaOS retains total authority over WHAT, WHY, WHEN, and WHICH provider/model.
- OpenMontage remains a separate downstream media-execution project.
- Zero live provider dispatch in this phase (ENABLE_LIVE_PROVIDER_EXECUTION=False).
- Pure offline transformation; zero network, zero subprocess calls, zero live SDK imports.
- Rejects unsupported capabilities explicitly (e.g. last-frame conditioning).
- Guards against secret leakage: credentials and sensitive tokens are strictly rejected.
- Deterministic output for identical normalized inputs.
"""
from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse

from app.core.logging import get_logger
from app.core.security import is_safe_remote_url
from app.core.sanitization import (
    RE_ANTHROPIC_KEY,
    RE_ARYA_KEY,
    RE_AUTH_HEADER,
    RE_BEARER,
    RE_FAL_KEY,
    RE_OPENAI_KEY,
    sanitize_payload,
)
from app.models.execution_bridge import AutonomousActionNode
from app.schemas.production import (
    AryaJobPackageContinuity,
    AryaJobPackageModelRoute,
    AryaJobPackagePlan,
    AryaJobPackageReferences,
    AryaJobPackageSchema,
    AryaJobPackageShotConfig,
)
from app.services.idempotency import generate_action_idempotency_key

logger = get_logger("arya.execution.media_bridge")

# -----------------------------------------------------------------------------
# 1. Custom Exceptions
# -----------------------------------------------------------------------------

class JobPackageSynthesisError(Exception):
    """Base exception for Job Package synthesis and transformation failures."""
    pass


class UnsupportedCapabilityError(JobPackageSynthesisError):
    """Raised when an action requests a capability unsupported by the provider."""
    pass


class JobPackageValidationError(JobPackageSynthesisError):
    """Raised when action inputs violate the Job Package contract or schema rules."""
    pass


class SecretDetectedError(JobPackageSynthesisError):
    """Raised when sensitive credentials or secrets are detected in inputs."""
    pass


# -----------------------------------------------------------------------------
# 2. Supported Constants & Compatibility Mappings
# -----------------------------------------------------------------------------

SUPPORTED_ACTION_TYPES = {"SYNTHESIS", "GENERATION"}
SUPPORTED_CAPABILITIES = {"IMAGE_GENERATION", "VIDEO_GENERATION"}

ALLOWED_ASPECT_RATIOS = {"16:9", "9:16", "1:1", "21:9", "4:3"}

PROVIDER_CAPABILITY_MAP: dict[str, set[str]] = {
    "fal": {"IMAGE_GENERATION"},
    "flux": {"IMAGE_GENERATION"},
    "diagram": {"IMAGE_GENERATION"},
    "kling": {"VIDEO_GENERATION"},
    "camera_motion": {"VIDEO_GENERATION"},
    "offline-mock": {"IMAGE_GENERATION", "VIDEO_GENERATION"},
    "mock": {"IMAGE_GENERATION", "VIDEO_GENERATION"},
}

DEFAULT_PROVIDER_BY_CAPABILITY = {
    "IMAGE_GENERATION": "fal",
    "VIDEO_GENERATION": "kling",
}

DEFAULT_MODEL_BY_PROVIDER = {
    "fal": "flux-pro/v1.1",
    "flux": "flux-pro/v1.1",
    "diagram": "diagram-boxes",
    "kling": "kling-video/v3/standard",
    "camera_motion": "camera-push",
    "offline-mock": "mock-media-v1",
    "mock": "mock-media-v1",
}

SECRET_PATTERNS = [
    RE_FAL_KEY,
    RE_OPENAI_KEY,
    RE_ANTHROPIC_KEY,
    RE_ARYA_KEY,
    RE_BEARER,
    RE_AUTH_HEADER,
]


# -----------------------------------------------------------------------------
# 3. Secret & Safety Inspectors
# -----------------------------------------------------------------------------

def scan_for_secrets(val: Any) -> None:
    """Recursively inspects data structures for credential patterns and raises SecretDetectedError."""
    if isinstance(val, str):
        for pat in SECRET_PATTERNS:
            if pat.search(val):
                raise SecretDetectedError(
                    f"Security violation: Sensitive credential pattern detected in input: {pat.pattern}"
                )
    elif isinstance(val, dict):
        for k, v in val.items():
            if str(k).lower() in ("api_key", "apikey", "secret", "token", "password", "fal_key"):
                raise SecretDetectedError(f"Security violation: Sensitive field '{k}' detected in action inputs")
            scan_for_secrets(v)
    elif isinstance(val, (list, tuple, set)):
        for item in val:
            scan_for_secrets(item)


def validate_reference_url(url: str | None, field_name: str) -> None:
    """Validates reference URLs for SSRF safety and scheme."""
    if not url:
        return
    clean = url.strip()
    if clean.startswith("http://") or clean.startswith("https://"):
        if not is_safe_remote_url(clean):
            raise JobPackageValidationError(
                f"Security violation: SSRF blocked for URL '{clean}' in field '{field_name}'"
            )
    elif clean.startswith("/") or clean.startswith("storage/"):
        # Local storage artifact path: verify no directory traversal
        if ".." in clean:
            raise JobPackageValidationError(
                f"Security violation: Path traversal detected in field '{field_name}': '{clean}'"
            )
    else:
        raise JobPackageValidationError(
            f"Invalid reference URL format in field '{field_name}': must be http(s) URL or safe storage path"
        )


# -----------------------------------------------------------------------------
# 4. Job Package Transformer
# -----------------------------------------------------------------------------

def synthesize_job_package(
    action: AutonomousActionNode,
    project_id: uuid.UUID,
    goal_id: uuid.UUID | None = None,
    created_at: str | None = None,
) -> AryaJobPackageSchema:
    """Explicit, typed transformer from an AutonomousActionNode into an AryaJobPackageSchema.

    Args:
        action: Source autonomous action node.
        project_id: Target project UUID.
        goal_id: Parent goal UUID (defaults to action.goal_id).
        created_at: Optional ISO 8601 creation timestamp for deterministic testing.

    Returns:
        AryaJobPackageSchema validated and ready for execution gateway / dispatcher ingestion.

    Raises:
        JobPackageSynthesisError: If action type or capability is invalid.
        JobPackageValidationError: If required fields or parameters are missing/malformed.
        UnsupportedCapabilityError: If unsupported generation capabilities are requested.
        SecretDetectedError: If credentials or tokens are present in action inputs.
    """
    effective_goal_id = goal_id or action.goal_id
    inputs = dict(action.inputs_json or {})

    # 1. Secret Scanning
    scan_for_secrets(inputs)

    # 2. Action Type Verification
    act_type = (action.action_type or "").strip().upper()
    if act_type not in SUPPORTED_ACTION_TYPES:
        raise JobPackageSynthesisError(
            f"Action type '{action.action_type}' cannot be transformed into a media Job Package. "
            f"Allowed types: {sorted(SUPPORTED_ACTION_TYPES)}"
        )

    # 3. Capability Verification
    capability = (action.required_capability or "").strip().upper()
    if capability not in SUPPORTED_CAPABILITIES:
        raise JobPackageSynthesisError(
            f"Capability '{action.required_capability}' is not a supported media generation capability. "
            f"Allowed: {sorted(SUPPORTED_CAPABILITIES)}"
        )

    is_video = capability == "VIDEO_GENERATION"
    generation_type = "video" if is_video else "image"

    # 4. Prompt Validation
    raw_prompt = inputs.get("prompt")
    if raw_prompt is None or not str(raw_prompt).strip():
        # Fall back to action title only if inputs lack prompt, but prompt must be explicit
        raise JobPackageValidationError(
            f"Missing required field 'prompt' in action inputs for action '{action.client_action_id}'"
        )
    prompt = str(raw_prompt).strip()
    if len(prompt) > 4000:
        raise JobPackageValidationError("Prompt exceeds maximum allowed length of 4000 characters")

    # 5. Provider & Model Resolution
    req_provider = inputs.get("provider")
    if req_provider:
        provider = str(req_provider).strip().lower()
    else:
        provider = DEFAULT_PROVIDER_BY_CAPABILITY[capability]

    # Validate provider compatibility with requested capability
    allowed_caps = PROVIDER_CAPABILITY_MAP.get(provider)
    if not allowed_caps or capability not in allowed_caps:
        raise JobPackageSynthesisError(
            f"Provider '{provider}' is incompatible with required capability '{capability}'. "
            f"Supported providers for {capability}: {[p for p, caps in PROVIDER_CAPABILITY_MAP.items() if capability in caps]}"
        )

    req_model = inputs.get("model")
    if req_model:
        model = str(req_model).strip()
    else:
        model = DEFAULT_MODEL_BY_PROVIDER.get(provider, "default-model")

    model_name = inputs.get("model_name") or model

    # 6. Aspect Ratio Validation
    raw_aspect = inputs.get("aspect_ratio") or inputs.get("aspectRatio") or "16:9"
    aspect_ratio = str(raw_aspect).strip()
    if aspect_ratio not in ALLOWED_ASPECT_RATIOS:
        raise JobPackageValidationError(
            f"Invalid aspect ratio '{aspect_ratio}'. Allowed aspect ratios: {sorted(ALLOWED_ASPECT_RATIOS)}"
        )

    # 7. Explicit Capability Enforcement: Last-Frame Conditioning Rejection
    # Rule: Reject unsupported capabilities explicitly; do not pretend last-frame conditioning is supported.
    last_frame_candidate = (
        inputs.get("last_frame")
        or inputs.get("lastFrame")
        or inputs.get("end_frame_url")
        or inputs.get("endFrameUrl")
        or inputs.get("last_frame_url")
    )
    if last_frame_candidate:
        raise UnsupportedCapabilityError(
            f"Unsupported capability: Provider '{provider}' does not support last-frame conditioning "
            "(FIRST_LAST_FRAME_TO_VIDEO). Only first-frame conditioning is supported."
        )

    # 8. First Frame / Reference Resolution & SSRF check
    first_frame_candidate = (
        inputs.get("first_frame")
        or inputs.get("firstFrame")
        or inputs.get("start_frame_url")
        or inputs.get("startFrameUrl")
        or inputs.get("first_frame_url")
        or inputs.get("image_url")
        or inputs.get("reference_image_url")
    )
    if first_frame_candidate:
        validate_reference_url(str(first_frame_candidate), "firstFrame")

    reference_assets = list(inputs.get("reference_assets") or inputs.get("referenceAssets") or [])
    for ref in reference_assets:
        validate_reference_url(str(ref), "referenceAssets")

    # 9. Duration & Video Configuration
    duration_seconds: float | None = None
    if is_video:
        raw_duration = inputs.get("duration_seconds") or inputs.get("duration") or 5.0
        try:
            duration_seconds = float(raw_duration)
            if duration_seconds <= 0:
                raise ValueError()
        except (ValueError, TypeError):
            raise JobPackageValidationError(f"Invalid duration '{raw_duration}': must be a positive number")

        # Specific provider duration constraints
        if provider == "kling" and duration_seconds not in (5.0, 10.0):
            # Kling standard API natively operates on 5s or 10s increments
            duration_seconds = 5.0 if duration_seconds < 7.5 else 10.0

    # 10. Identifiers & Trace Metadata Preservation
    job_package_id = str(inputs.get("job_package_id") or f"pkg:{project_id}:{action.id}")
    idempotency_key = generate_action_idempotency_key(
        project_id=project_id,
        goal_id=effective_goal_id,
        action_id=action.id,
        client_action_id=action.client_action_id,
    )
    intent_id = str(inputs.get("intent_id") or idempotency_key)
    sequence_id = str(inputs.get("sequence_id") or effective_goal_id)
    shot_id = str(inputs.get("shot_id") or action.id)
    shot_order = int(inputs.get("shot_order", 1))

    # Deterministic Timestamp
    if created_at:
        timestamp_str = created_at
    elif getattr(action, "created_at", None):
        timestamp_str = action.created_at.isoformat()
    else:
        timestamp_str = datetime.now(timezone.utc).isoformat()

    # 11. Submodel Construction
    mode = inputs.get("mode") or ("image_to_video" if (is_video and first_frame_candidate) else ("text_to_video" if is_video else "text_to_image"))

    plan = AryaJobPackagePlan(
        title=action.title,
        prompt=prompt,
        generationType=generation_type,
        mode=mode,
        durationSeconds=duration_seconds,
        dependencies=list(inputs.get("dependencies", [])),
        isFirstShotInSequence=bool(inputs.get("is_first_shot", True)),
    )

    references = AryaJobPackageReferences(
        startFrameUrl=str(first_frame_candidate) if first_frame_candidate else None,
        firstFrame=str(first_frame_candidate) if first_frame_candidate else None,
        referenceImageUrl=str(first_frame_candidate) if first_frame_candidate else None,
        referenceAssets=[str(r) for r in reference_assets],
    )

    model_route = AryaJobPackageModelRoute(
        provider=provider,
        model=model,
        modelName=model_name,
        mode=generation_type,
        preflightReady=True,
        preflightReasons=[],
        availability="AVAILABLE",
        estimatedCostUsd=float(inputs.get("estimated_cost_usd", 0.05 if not is_video else 0.10)),
    )

    shot_config = AryaJobPackageShotConfig(
        aspectRatio=aspect_ratio,
        duration=duration_seconds,
        firstFrame=str(first_frame_candidate) if first_frame_candidate else None,
        fps=int(inputs.get("fps", 25)) if is_video else None,
    )

    continuity = AryaJobPackageContinuity(
        character=inputs.get("continuity_character", "UNAVAILABLE"),
        environment=inputs.get("continuity_environment", "PASS"),
        visual=inputs.get("continuity_visual", "PASS"),
        temporal=inputs.get("continuity_temporal", "PASS"),
        startFrame="PASS" if first_frame_candidate else "NOT_APPLICABLE",
    )

    output_requirements = {
        "targetFormat": "video/mp4" if is_video else "image/png",
        "destination": "ARYAOS_CORRIDOR_STREAM",
        "aspectRatio": aspect_ratio,
    }

    # Preserved trace metadata in executionPayload
    execution_payload = {
        "action_id": str(action.id),
        "client_action_id": action.client_action_id,
        "goal_id": str(effective_goal_id),
        "project_id": str(project_id),
        "idempotency_key": idempotency_key,
        "risk_level": action.risk_level,
        "required_capability": action.required_capability,
        "prompt": prompt,
        "provider": provider,
        "model": model,
        "aspect_ratio": aspect_ratio,
    }

    # 12. Construct and Validate Complete Job Package
    package = AryaJobPackageSchema(
        jobPackageId=job_package_id,
        intentId=intent_id,
        createdAt=timestamp_str,
        projectId=str(project_id),
        sequenceId=sequence_id,
        shotId=shot_id,
        shotOrder=shot_order,
        plan=plan,
        references=references,
        modelRoute=model_route,
        shotConfiguration=shot_config,
        continuityRequirements=continuity,
        outputRequirements=output_requirements,
        decisionBoundary="ARYAOS_ORCHESTRATION_VALIDATED",
        executionPayload=execution_payload,
    )

    validate_job_package_boundary(package)
    return package


def validate_job_package_boundary(pkg: AryaJobPackageSchema) -> None:
    """Performs strict boundary validation on an assembled Job Package before dispatch."""
    if pkg.decisionBoundary != "ARYAOS_ORCHESTRATION_VALIDATED":
        raise JobPackageValidationError(
            f"Invalid decision boundary: '{pkg.decisionBoundary}'. Must be 'ARYAOS_ORCHESTRATION_VALIDATED'"
        )

    if not pkg.jobPackageId or not pkg.projectId or not pkg.shotId or not pkg.sequenceId:
        raise JobPackageValidationError("Job Package missing mandatory identification fields")

    if not pkg.plan.prompt or not pkg.plan.prompt.strip():
        raise JobPackageValidationError("Job Package plan prompt cannot be empty")

    if pkg.shotConfiguration.aspectRatio not in ALLOWED_ASPECT_RATIOS:
        raise JobPackageValidationError(
            f"Unsupported aspect ratio in shotConfiguration: {pkg.shotConfiguration.aspectRatio}"
        )

    # Re-verify that no credentials exist in execution payload
    scan_for_secrets(pkg.executionPayload)
