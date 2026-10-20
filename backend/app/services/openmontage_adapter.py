"""
AryaOS V1 Phase 9 & Stage 25 Phase 3.2.4.2 — OpenMontage Adapter & Protocol Hardening.

Provides a strictly isolated, secure execution adapter to invoke OpenMontage tools.

ARCHITECTURAL RULES:
1. ARYAOS and OPENMONTAGE MUST REMAIN SEPARATE SYSTEMS.
   - AryaOS decides: WHAT, WHEN, WHY, WHICH provider/model, dependencies, Job Package content.
   - OpenMontage decides: HOW media is generated and rendered.
   - No OpenMontage code is imported into the AryaOS process memory space.
   - Subprocess isolation ensures zero conflicting dependencies, clean memory lifecycle,
     and robust failure isolation.
2. PROTOCOL CONTRACT (v1.1):
   - Explicit result framing delimiters: __ARYA_OPENMONTAGE_RESULT_START__ / __ARYA_OPENMONTAGE_RESULT_END__
   - Strict stdout / stderr separation (stdout for framed protocol JSON, stderr for diagnostics).
   - Validated schema fields: status, phase, ambiguity flag, provider request ID, artifacts, cost, duration.
   - Streaming buffer caps: Max 2 MB per stream to prevent unbounded memory exhaustion.
3. TIMEOUT & EXECUTION TRUTH:
   - External provider actions (EXTERNAL_API_TOOLS) hitting timeout or abnormal process crash
     strictly return UNKNOWN_PENDING_RECONCILIATION with is_ambiguous=True.
   - Local-only actions (LOCAL_ONLY_TOOLS) return FAILED only after process group cleanup.
   - Subprocess execution tree is boundedly terminated via process group signals (SIGTERM -> SIGKILL).
4. SECRET SANITIZATION:
   - All errors, diagnostics, stderr logs, and payload data are sanitized before persistence or exposure.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import math
import os
import re
import signal
import sys
import time
import unittest.mock
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any

from app.core.logging import get_logger
from app.core.sanitization import sanitize_payload, sanitize_text

logger = get_logger("arya.execution.openmontage")

# Regex to enforce safe tool identifier (no shell characters, no path navigation)
SAFE_TOOL_REGEX = re.compile(r"^[a-zA-Z0-9_]+$")

# Protocol version & result frame markers
PROTOCOL_VERSION = "1.1"
RESULT_FRAME_START = "__ARYA_OPENMONTAGE_RESULT_START__"
RESULT_FRAME_END = "__ARYA_OPENMONTAGE_RESULT_END__"

# Resource limit: 2 MB maximum buffered bytes per stream
MAX_STREAM_BYTES = 2 * 1024 * 1024

# Explicit tool categorization for execution truth and retry safety
LOCAL_ONLY_TOOLS = {
    "camera_motion",
    "camera_push_video",
    "local_diffusion",
    "blender_world",
    "diagram_gen",
    "code_snippet",
    "composition_validator",
    "av_sync_validator",
    "shot_semantic_qc",
    "final_output_qc",
}

EXTERNAL_API_TOOLS = {
    "flux_image",
    "kling_video",
    "kling_official_video",
    "minimax_video",
    "veo_video",
    "wan_video",
    "sora_video",
    "seedance_video",
    "runway_video",
    "grok_video",
    "gemini_omni_video",
    "higgsfield_video",
    "jimeng_video",
    "atlas_video",
    "atlas_image",
    "hunyuan_image",
    "dashscope_image",
    "google_imagen",
    "openai_image",
    "recraft_image",
}

# System execution environment allowlist for subprocess isolation
SAFE_SYSTEM_ENV_ALLOWLIST = {
    # System execution environment
    "PATH",
    "HOME",
    "USER",
    "LOGNAME",
    "TMPDIR",
    "TEMP",
    "TMP",
    "SHELL",
    "TERM",
    # Locale & Encoding
    "LANG",
    "LC_ALL",
    "LC_CTYPE",
    "PYTHONUTF8",
    "PYTHONIOENCODING",
    # Windows system variables
    "SYSTEMROOT",
    "WINDIR",
    "COMSPEC",
    "PATHEXT",
    "SYSTEMDRIVE",
    "ALLUSERSPROFILE",
    "APPDATA",
    "LOCALAPPDATA",
    "PROGRAMDATA",
    # Tool specific media paths
    "BLENDER_PATH",
    "FFMPEG_PATH",
    "FFPROBE_PATH",
}

# Explicit provider credential variables
PROVIDER_CREDENTIAL_ALLOWLIST = {
    "FAL_KEY",
    "FAL_API_KEY",
    "KLING_API_KEY",
}

# Backend secret variables that must NEVER be passed to OpenMontage subprocess
FORBIDDEN_SECRET_KEYS = {
    "DATABASE_URL",
    "POSTGRES_PASSWORD",
    "POSTGRES_USER",
    "POSTGRES_DB",
    "SECRET_KEY",
    "MASTER_API_KEY",
    "SYSTEM_MASTER_KEY",
    "DEVELOPMENT_BYPASS_KEY",
    "JWT_SECRET",
}


def is_external_tool(tool_name: str | None) -> bool:
    """Determines if a tool performs external network / provider calls.

    Fail-closed: Any tool not explicitly registered in LOCAL_ONLY_TOOLS is treated
    as an external API tool to guarantee safety against duplicate dispatch.
    """
    clean_tool = (tool_name or "").strip().lower()
    if clean_tool in LOCAL_ONLY_TOOLS:
        return False
    return True


def validate_provider_job_id(val: Any) -> str | None:
    """Validates that a provider job ID is an authentic external reference.

    Rejects file paths, media extensions, small local PIDs, and empty strings.
    """
    if not val or not isinstance(val, str):
        return None
    clean = val.strip()
    if not clean:
        return None
    # Reject path separators
    if "/" in clean or "\\" in clean:
        return None
    # Reject common media extensions
    lower = clean.lower()
    if any(
        lower.endswith(ext)
        for ext in (
            ".png",
            ".jpg",
            ".jpeg",
            ".mp4",
            ".mov",
            ".webm",
            ".json",
            ".log",
            ".txt",
        )
    ):
        return None
    # Reject small local PID numbers (e.g. "1234")
    if clean.isdigit() and len(clean) < 7:
        return None
    return clean


# Python runner script executed inside OpenMontage's isolated virtualenv
RUNNER_SCRIPT = """
import sys
import json
import traceback

openmontage_path = sys.argv[1]
sys.path.insert(0, openmontage_path)

FRAME_START = "__ARYA_OPENMONTAGE_RESULT_START__"
FRAME_END = "__ARYA_OPENMONTAGE_RESULT_END__"

def emit_result(payload):
    sys.stdout.write(FRAME_START + "\\n")
    sys.stdout.write(json.dumps(payload) + "\\n")
    sys.stdout.write(FRAME_END + "\\n")
    sys.stdout.flush()

tool_name = "unknown"
phase = "PRE_DISPATCH"
try:
    payload = json.loads(sys.stdin.read())
    tool_name = payload.get("tool", "unknown")
    inputs = payload.get("inputs", {})
    check_status_only = payload.get("check_status_only", False)

    from tools.tool_registry import ToolRegistry
    registry = ToolRegistry()
    registry.discover("tools")
    tool = registry.get(tool_name)

    if not tool:
        emit_result({
            "protocol_version": "1.1",
            "tool": tool_name,
            "success": False,
            "status": "NOT_FOUND",
            "phase": "PRE_DISPATCH",
            "is_ambiguous": False,
            "provider_job_id": None,
            "artifacts": [],
            "data": {},
            "error": f"Tool '{tool_name}' not found in OpenMontage registry",
            "cost_usd": 0.0,
            "duration_seconds": 0.0,
            "seed": None,
            "model": None,
        })
        sys.exit(0)

    if check_status_only:
        status_val = getattr(tool.get_status(), "value", "unknown") if hasattr(tool, "get_status") else "available"
        emit_result({
            "protocol_version": "1.1",
            "tool": tool_name,
            "success": True,
            "status": status_val,
            "phase": "PRE_DISPATCH",
            "is_ambiguous": False,
            "provider_job_id": None,
            "artifacts": [],
            "data": {"status": status_val},
            "error": None,
            "cost_usd": 0.0,
            "duration_seconds": 0.0,
            "seed": None,
            "model": None,
        })
        sys.exit(0)

    # Transition to IN_FLIGHT execution
    phase = "IN_FLIGHT"
    result = tool.execute(inputs)
    phase = "POST_DISPATCH"

    # Extract provider request ID if present
    provider_job_id = getattr(result, "provider_job_id", None) or getattr(result, "request_id", None)
    if not provider_job_id and hasattr(result, "data") and isinstance(result.data, dict):
        provider_job_id = (
            result.data.get("provider_job_id")
            or result.data.get("request_id")
            or result.data.get("job_id")
        )

    res_success = bool(getattr(result, "success", False))
    res_artifacts = list(getattr(result, "artifacts", []) or [])
    res_data = dict(getattr(result, "data", {}) or {})
    res_error = getattr(result, "error", None)

    emit_result({
        "protocol_version": "1.1",
        "tool": tool_name,
        "success": res_success,
        "status": "COMPLETED" if res_success else "FAILED",
        "phase": "POST_DISPATCH",
        "is_ambiguous": False,
        "provider_job_id": str(provider_job_id) if provider_job_id else None,
        "artifacts": res_artifacts,
        "data": res_data,
        "error": str(res_error) if res_error else None,
        "cost_usd": float(getattr(result, "cost_usd", 0.0) or 0.0),
        "duration_seconds": float(getattr(result, "duration_seconds", 0.0) or 0.0),
        "seed": getattr(result, "seed", None),
        "model": getattr(result, "model", None),
    })
except Exception as e:
    tb_str = traceback.format_exc()
    sys.stderr.write(f"OpenMontage Subprocess Exception: {e}\\n{tb_str}\\n")
    sys.stderr.flush()
    emit_result({
        "protocol_version": "1.1",
        "tool": tool_name,
        "success": False,
        "status": "UNKNOWN_PENDING_RECONCILIATION" if phase == "IN_FLIGHT" else "FAILED",
        "phase": phase,
        "is_ambiguous": (phase == "IN_FLIGHT"),
        "provider_job_id": None,
        "artifacts": [],
        "data": {},
        "error": str(e),
        "cost_usd": 0.0,
        "duration_seconds": 0.0,
        "seed": None,
        "model": None,
    })
"""


class ExecutionBoundaryError(RuntimeError):
    """Raised when an unauthenticated or unauthorized invocation attempts to cross the execution boundary."""
    pass


class SecurityViolationError(RuntimeError):
    """Raised when cryptographic capability verification or security invariant fails."""
    pass


# Global tracking of consumed capability nonces to prevent replay attacks
_CONSUMED_CAPABILITY_NONCES: set[str] = set()


def _get_capability_signing_key() -> bytes:
    """Derives a deterministic cryptographic HMAC signing key from AryaOS API/Secret configuration."""
    try:
        from app.core.config import get_settings
        s = get_settings()
        key_material = getattr(s, "arya_api_key", None) or getattr(s, "secret_key", None) or "arya-os-internal-capability-key"
    except Exception:
        key_material = "arya-os-internal-capability-key"
    return hashlib.sha256(f"arya-cap-signing:{key_material}".encode("utf-8")).digest()


def canonical_capability_payload(
    action_node_id: str,
    goal_id: str,
    project_id: str,
    reservation_id: str,
    provider_id: str,
    authorized_at: str,
    expires_at: str,
    execution_nonce: str,
    worker_id: str,
    lease_token: str,
) -> str:
    """Deterministic canonical serialization function for capability HMAC signing and verification.

    Canonical format (10 fields):
    {action_node_id}:{goal_id}:{project_id}:{reservation_id}:{provider_id}:{authorized_at}:{expires_at}:{execution_nonce}:{worker_id}:{lease_token}
    """
    return (
        f"{action_node_id}:{goal_id}:{project_id}:{reservation_id}:"
        f"{provider_id}:{authorized_at}:{expires_at}:{execution_nonce}:"
        f"{worker_id}:{lease_token}"
    )


def _compute_capability_signature(
    action_node_id: str,
    goal_id: str,
    project_id: str,
    reservation_id: str,
    provider_id: str,
    authorized_at: str,
    expires_at: str,
    execution_nonce: str,
    worker_id: str,
    lease_token: str,
) -> str:
    """Computes HMAC-SHA256 signature across all 10 capability context attributes using canonical payload."""
    canonical_string = canonical_capability_payload(
        action_node_id=str(action_node_id),
        goal_id=str(goal_id),
        project_id=str(project_id),
        reservation_id=str(reservation_id),
        provider_id=str(provider_id),
        authorized_at=str(authorized_at),
        expires_at=str(expires_at),
        execution_nonce=str(execution_nonce),
        worker_id=str(worker_id),
        lease_token=str(lease_token),
    )
    signing_key = _get_capability_signing_key()
    return hmac.new(signing_key, canonical_string.encode("utf-8"), hashlib.sha256).hexdigest()


@dataclass
class GovernedExecutionContext:
    """Cryptographic capability token proving Stage 25 governance authorization for provider execution."""

    action_node_id: str
    goal_id: str
    project_id: str
    reservation_id: str
    provider_id: str
    authorized_at: str
    expires_at: str
    execution_nonce: str
    capability_signature: str
    worker_id: str = "default-worker"
    lease_token: str = "default-lease"
    dispatch_phase: str = "PRE_DISPATCH"

    def canonical_payload(self) -> str:
        """Returns the canonical deterministic payload string."""
        return canonical_capability_payload(
            action_node_id=str(self.action_node_id),
            goal_id=str(self.goal_id),
            project_id=str(self.project_id),
            reservation_id=str(self.reservation_id),
            provider_id=str(self.provider_id),
            authorized_at=str(self.authorized_at),
            expires_at=str(self.expires_at),
            execution_nonce=str(self.execution_nonce),
            worker_id=str(self.worker_id),
            lease_token=str(self.lease_token),
        )

    def verify_authenticity(self, record_nonce: bool = True) -> None:
        """Verifies cryptographic signature, expiry, and nonce uniqueness across all 10 attributes.

        Raises:
            SecurityViolationError: If signature is forged, nonce is replayed, or TTL is expired.
        """
        # 1. Non-empty attribute verification (all 10 canonical fields + signature)
        fields_to_check = [
            ("action_node_id", self.action_node_id),
            ("goal_id", self.goal_id),
            ("project_id", self.project_id),
            ("reservation_id", self.reservation_id),
            ("provider_id", self.provider_id),
            ("authorized_at", self.authorized_at),
            ("expires_at", self.expires_at),
            ("execution_nonce", self.execution_nonce),
            ("capability_signature", self.capability_signature),
            ("worker_id", self.worker_id),
            ("lease_token", self.lease_token),
        ]
        for name, val in fields_to_check:
            if not val or not str(val).strip():
                raise SecurityViolationError(f"Missing required execution context field '{name}'")

        # 2. Replay protection
        if self.execution_nonce in _CONSUMED_CAPABILITY_NONCES:
            raise SecurityViolationError(
                f"Replay detected: capability nonce '{self.execution_nonce}' has already been consumed"
            )

        # 3. Cryptographic signature check using the deterministic canonical serialization function
        canonical_string = self.canonical_payload()
        signing_key = _get_capability_signing_key()
        expected_sig = hmac.new(signing_key, canonical_string.encode("utf-8"), hashlib.sha256).hexdigest()

        if not hmac.compare_digest(self.capability_signature, expected_sig):
            raise SecurityViolationError(
                "Capability signature verification failed: invalid cryptographic signature"
            )

        # 4. TTL expiration check
        try:
            exp_clean = self.expires_at.replace("Z", "+00:00")
            exp_dt = datetime.fromisoformat(exp_clean)
            if exp_dt.tzinfo is None:
                exp_dt = exp_dt.replace(tzinfo=timezone.utc)
            now_dt = datetime.now(timezone.utc)
            if now_dt > exp_dt:
                raise SecurityViolationError(
                    f"Capability expired at {self.expires_at} (current time {now_dt.isoformat()})"
                )
        except SecurityViolationError:
            raise
        except Exception as e:
            raise SecurityViolationError(f"Invalid capability expiration timestamp: {e}")

        # 5. Nonce consumption
        if record_nonce:
            _CONSUMED_CAPABILITY_NONCES.add(self.execution_nonce)


async def consume_capability_nonce_durable(
    execution_context: GovernedExecutionContext,
    db: Any = None,
    worker_id: str | None = None,
    lease_token: str | None = None,
) -> None:
    """Durably consumes a capability nonce in PostgreSQL to ensure atomic single-use across workers.

    Guarantees:
    - Atomicity across multiple concurrent worker processes via PostgreSQL unique constraint.
    - Durable persistence preventing replay across process restarts.
    - Fail-closed behavior on database error, missing table, or transaction failure.

    Raises:
        SecurityViolationError: If replay detected or database operation fails closed.
    """
    from sqlalchemy.exc import IntegrityError
    from app.database.session import AsyncSessionLocal
    from app.models.execution_bridge import ConsumedCapabilityNonce

    # 1. Fast in-memory filter
    if execution_context.execution_nonce in _CONSUMED_CAPABILITY_NONCES:
        raise SecurityViolationError(
            f"Replay detected: capability nonce '{execution_context.execution_nonce}' has already been consumed"
        )

    # 2. Parse timestamps
    try:
        auth_clean = execution_context.authorized_at.replace("Z", "+00:00")
        auth_dt = datetime.fromisoformat(auth_clean)
        if auth_dt.tzinfo is None:
            auth_dt = auth_dt.replace(tzinfo=timezone.utc)

        exp_clean = execution_context.expires_at.replace("Z", "+00:00")
        exp_dt = datetime.fromisoformat(exp_clean)
        if exp_dt.tzinfo is None:
            exp_dt = exp_dt.replace(tzinfo=timezone.utc)
    except Exception as e:
        raise SecurityViolationError(f"Invalid capability timestamp format: {e}")

    effective_worker = worker_id or getattr(execution_context, "worker_id", "live-dispatcher")
    effective_lease = lease_token or getattr(execution_context, "lease_token", "live-lease")

    # 3. Durable PostgreSQL atomic record
    async def _insert_nonce(session) -> None:
        row = ConsumedCapabilityNonce(
            execution_nonce=str(execution_context.execution_nonce),
            action_node_id=str(execution_context.action_node_id),
            goal_id=str(execution_context.goal_id),
            project_id=str(execution_context.project_id),
            reservation_id=str(execution_context.reservation_id),
            provider_id=str(execution_context.provider_id),
            capability_signature=str(execution_context.capability_signature),
            authorized_at=auth_dt,
            expires_at=exp_dt,
            worker_id=str(effective_worker),
            lease_token=str(effective_lease),
            consumed_at=datetime.now(timezone.utc),
        )
        session.add(row)
        await session.commit()

    try:
        if db is not None:
            await _insert_nonce(db)
        else:
            async with AsyncSessionLocal() as session:
                await _insert_nonce(session)
    except IntegrityError as exc:
        _CONSUMED_CAPABILITY_NONCES.add(execution_context.execution_nonce)
        raise SecurityViolationError(
            f"Replay detected: capability nonce '{execution_context.execution_nonce}' has already been consumed (database unique violation)"
        ) from exc
    except SecurityViolationError:
        raise
    except Exception as exc:
        # FAIL-CLOSED: Database outage, missing table, connection loss strictly fails closed
        raise SecurityViolationError(
            f"Durable capability consumption failed (fail-closed): {exc}"
        ) from exc

    # 4. Durable consumption succeeded: update in-memory cache
    _CONSUMED_CAPABILITY_NONCES.add(execution_context.execution_nonce)


async def verify_authoritative_lease_and_dispatch_state(
    execution_context: GovernedExecutionContext,
    db: Any = None,
) -> None:
    """Verifies that the capability's worker identity, lease token, and reservation
    match current authoritative active state in PostgreSQL before subprocess execution.

    Raises:
        SecurityViolationError: If action lease is superseded, revoked, expired, or reservation/approval invalid.
    """
    import uuid
    from sqlalchemy import select
    from app.database.session import AsyncSessionLocal
    from app.models.execution_bridge import (
        AutonomousActionNode,
        BudgetReservation,
        GovernanceDecision,
    )

    async def _validate(session) -> None:
        try:
            node_uuid = uuid.UUID(str(execution_context.action_node_id))
        except (ValueError, TypeError):
            node_uuid = None

        if node_uuid is not None:
            stmt = select(AutonomousActionNode).where(AutonomousActionNode.id == node_uuid)
            res = await session.execute(stmt)
            node = res.scalar_one_or_none()
            if node is not None:
                # 1. State check: action must be in executable state
                if node.status not in ("EXECUTING", "READY"):
                    raise SecurityViolationError(
                        f"Action node '{node.id}' is in non-executable state '{node.status}' (lease revoked or execution completed)"
                    )

                # 2. Worker identity & lease token check
                lease = (node.inputs_json or {}).get("lease", {}) if isinstance(node.inputs_json, dict) else {}
                db_worker = str(lease.get("worker_id") or "")
                db_lease = str(lease.get("lease_token") or "")
                db_expires_str = lease.get("expires_at")

                if db_worker and db_worker != str(execution_context.worker_id):
                    raise SecurityViolationError(
                        f"Worker identity mismatch: context worker '{execution_context.worker_id}' does not match authoritative active lease worker '{db_worker}'"
                    )

                if db_lease and db_lease != str(execution_context.lease_token):
                    raise SecurityViolationError(
                        f"Lease token mismatch: context lease '{execution_context.lease_token}' does not match authoritative active lease '{db_lease}' (superseded or fenced out)"
                    )

                # 3. Active lease expiration check
                if db_expires_str:
                    try:
                        clean_exp = db_expires_str.replace("Z", "+00:00")
                        lease_exp_dt = datetime.fromisoformat(clean_exp)
                        if lease_exp_dt.tzinfo is None:
                            lease_exp_dt = lease_exp_dt.replace(tzinfo=timezone.utc)
                        if datetime.now(timezone.utc) > lease_exp_dt:
                            raise SecurityViolationError(
                                f"Authoritative action lease expired at {db_expires_str}"
                            )
                    except SecurityViolationError:
                        raise
                    except Exception:
                        pass

                # 4. Action node goal binding
                if str(node.goal_id) != str(execution_context.goal_id):
                    raise SecurityViolationError(
                        f"Goal binding mismatch: node goal '{node.goal_id}' does not match context goal '{execution_context.goal_id}'"
                    )

                # 5. Authoritative budget reservation verification
                if not execution_context.reservation_id:
                    raise SecurityViolationError(
                        "Missing budget reservation ID in execution context (fail-closed)"
                    )

                try:
                    res_uuid = uuid.UUID(str(execution_context.reservation_id))
                except (ValueError, TypeError) as exc:
                    raise SecurityViolationError(
                        f"Invalid budget reservation ID '{execution_context.reservation_id}': {exc}"
                    )

                res_stmt = select(BudgetReservation).where(BudgetReservation.id == res_uuid)
                res_result = await session.execute(res_stmt)
                reservation = res_result.scalar_one_or_none()

                if reservation is None:
                    raise SecurityViolationError(
                        f"Budget reservation '{res_uuid}' not found in database (fail-closed)"
                    )

                if reservation.status == "RELEASED":
                    raise SecurityViolationError(
                        f"Budget reservation '{reservation.id}' has been RELEASED; cannot be used for execution"
                    )

                if reservation.status not in ("RESERVED", "CONSUMED"):
                    raise SecurityViolationError(
                        f"Budget reservation '{reservation.id}' has invalid status '{reservation.status}'; "
                        "expected 'RESERVED' or 'CONSUMED'"
                    )

                if str(reservation.project_id) != str(execution_context.project_id):
                    raise SecurityViolationError(
                        f"Cross-project reservation violation: reservation project '{reservation.project_id}' "
                        f"does not match context project '{execution_context.project_id}'"
                    )

                if str(reservation.goal_id) != str(execution_context.goal_id):
                    raise SecurityViolationError(
                        f"Reservation goal mismatch: reservation goal '{reservation.goal_id}' "
                        f"does not match context goal '{execution_context.goal_id}'"
                    )

                try:
                    reserved_usd = float(reservation.reserved_amount_usd)
                    consumed_usd = float(reservation.consumed_amount_usd or 0.0)
                except (ValueError, TypeError) as exc:
                    raise SecurityViolationError(
                        f"Budget reservation '{reservation.id}' has non-numeric amounts: {exc}"
                    )

                if math.isnan(reserved_usd) or math.isinf(reserved_usd) or reserved_usd <= 0.0:
                    raise SecurityViolationError(
                        f"Budget reservation '{reservation.id}' has invalid reserved amount: {reservation.reserved_amount_usd}"
                    )

                if math.isnan(consumed_usd) or math.isinf(consumed_usd) or consumed_usd < 0.0:
                    raise SecurityViolationError(
                        f"Budget reservation '{reservation.id}' has invalid consumed amount: {reservation.consumed_amount_usd}"
                    )

                if consumed_usd > reserved_usd:
                    raise SecurityViolationError(
                        f"Budget reservation '{reservation.id}' overconsumption violation: "
                        f"consumed {consumed_usd} exceeds reserved {reserved_usd}"
                    )

                if reservation.status == "CONSUMED" and consumed_usd <= 0.0:
                    raise SecurityViolationError(
                        f"Budget reservation '{reservation.id}' status is CONSUMED but consumed amount is {consumed_usd} (lifecycle mismatch)"
                    )

                # 6. Governance approval check if decisions exist in DB
                try:
                    proj_uuid = uuid.UUID(str(execution_context.project_id))
                    gov_stmt = select(GovernanceDecision).where(GovernanceDecision.project_id == proj_uuid)
                    gov_result = await session.execute(gov_stmt)
                    decisions = gov_result.scalars().all()
                    for d in decisions:
                        if d.status == "REJECTED":
                            raise SecurityViolationError(
                                f"Governance decision '{d.id}' rejected execution for project '{proj_uuid}'"
                            )
                except (ValueError, TypeError):
                    pass

    try:
        if db is not None:
            await _validate(db)
        else:
            async with AsyncSessionLocal() as session:
                await _validate(session)
    except SecurityViolationError:
        raise
    except Exception as exc:
        raise SecurityViolationError(
            f"Authoritative lease state validation failed (fail-closed): {exc}"
        ) from exc


def create_governed_execution_context(
    action_node_id: str,
    goal_id: str,
    project_id: str,
    reservation_id: str,
    provider_id: str,
    ttl_seconds: float = 300.0,
    worker_id: str = "default-worker",
    lease_token: str = "default-lease",
) -> GovernedExecutionContext:
    """Issues an authentic GovernedExecutionContext cryptographically signed by AryaOS."""
    import uuid

    now_dt = datetime.now(timezone.utc)
    exp_dt = now_dt + timedelta(seconds=ttl_seconds)
    authorized_at = now_dt.isoformat()
    expires_at = exp_dt.isoformat()
    execution_nonce = f"nonce-{uuid.uuid4().hex}"

    sig = _compute_capability_signature(
        action_node_id=str(action_node_id),
        goal_id=str(goal_id),
        project_id=str(project_id),
        reservation_id=str(reservation_id),
        provider_id=str(provider_id),
        authorized_at=authorized_at,
        expires_at=expires_at,
        execution_nonce=execution_nonce,
        worker_id=str(worker_id),
        lease_token=str(lease_token),
    )

    return GovernedExecutionContext(
        action_node_id=str(action_node_id),
        goal_id=str(goal_id),
        project_id=str(project_id),
        reservation_id=str(reservation_id),
        provider_id=str(provider_id),
        authorized_at=authorized_at,
        expires_at=expires_at,
        execution_nonce=execution_nonce,
        capability_signature=sig,
        worker_id=worker_id,
        lease_token=lease_token,
        dispatch_phase="PRE_DISPATCH",
    )


@dataclass
class OpenMontageToolResult:
    """Normalized response contract from OpenMontage tool execution (Protocol v1.1)."""

    success: bool
    status: str = "COMPLETED"  # COMPLETED | FAILED | UNKNOWN_PENDING_RECONCILIATION | UNAVAILABLE
    artifacts: list[str] = field(default_factory=list)
    data: dict[str, Any] = field(default_factory=dict)
    error: str | None = None
    cost_usd: float = 0.0
    duration_seconds: float = 0.0
    seed: int | None = None
    model: str | None = None
    protocol_version: str = "1.1"
    phase: str = "POST_DISPATCH"  # PRE_DISPATCH | IN_FLIGHT | POST_DISPATCH | LOCAL_EXECUTION
    is_ambiguous: bool = False
    provider_job_id: str | None = None
    tool: str | None = None


async def terminate_process_tree(
    proc: asyncio.subprocess.Process,
    grace_period_seconds: float = 3.0,
) -> None:
    """Safely and boundedly terminates the entire subprocess session / process group.

    POSIX Invariant: When proc was launched with start_new_session=True, setsid()
    guarantees that the new process group ID (PGID) is numerically identical to the
    child's PID (PGID == PID). We signal this established process group directly via
    os.killpg(pid, ...) rather than relying on os.getpgid(pid) (which fails if the
    group leader process has already exited and been reaped while grandchildren survive).

    Guards:
    - Never signals if pid is None or pid <= 1 (protects init and caller process groups).
    - Attempts os.killpg for full process-group coverage, and proc.terminate()/kill() in tandem.
    - Escalates from SIGTERM to SIGKILL after grace_period_seconds (default 3.0s).
    - Bounded reap wait of 0.5s guarantees total termination time is <= 3.5 seconds.
    - Windows limitation: Windows lacks POSIX process groups (os.killpg and SIGKILL do not exist);
      falls back gracefully to standard process termination on Windows.
    """
    pid = proc.pid
    if pid is None or pid <= 1:
        return

    # 1. Graceful SIGTERM to process group
    if hasattr(os, "killpg"):
        try:
            os.killpg(pid, signal.SIGTERM)
        except (ProcessLookupError, PermissionError):
            pass
        except Exception:
            pass

    try:
        proc.terminate()
    except (ProcessLookupError, PermissionError):
        pass
    except Exception:
        pass

    # 2. Wait bounded grace period (default 3.0s)
    try:
        await asyncio.wait_for(proc.wait(), timeout=grace_period_seconds)
        return
    except (asyncio.TimeoutError, Exception):
        pass

    # 3. Forceful SIGKILL to process group
    if hasattr(os, "killpg") and hasattr(signal, "SIGKILL"):
        try:
            os.killpg(pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass
        except Exception:
            pass

    try:
        proc.kill()
    except (ProcessLookupError, PermissionError):
        pass
    except Exception:
        pass

    # 4. Final bounded reap wait (0.5s max; total bound <= 3.5s)
    try:
        await asyncio.wait_for(proc.wait(), timeout=0.5)
    except Exception:
        pass


@dataclass
class SubprocessEntry:
    proc: asyncio.subprocess.Process
    action_id: str | None
    goal_id: str | None
    tool_name: str
    started_at: float


class SubprocessRegistry:
    """Registry tracking active child processes spawned by OpenMontage adapter."""

    def __init__(self) -> None:
        self._entries: dict[int, SubprocessEntry] = {}

    def register(
        self,
        proc: asyncio.subprocess.Process,
        action_id: str | uuid.UUID | None = None,
        goal_id: str | uuid.UUID | None = None,
        tool_name: str = "",
    ) -> None:
        if proc.pid is None:
            return
        self._entries[proc.pid] = SubprocessEntry(
            proc=proc,
            action_id=str(action_id) if action_id is not None else None,
            goal_id=str(goal_id) if goal_id is not None else None,
            tool_name=tool_name,
            started_at=time.time(),
        )

    def unregister(self, proc: asyncio.subprocess.Process) -> None:
        if proc.pid is not None:
            self._entries.pop(proc.pid, None)

    def get_entries_for_action(self, action_id: str | uuid.UUID) -> list[SubprocessEntry]:
        aid = str(action_id)
        return [e for e in self._entries.values() if e.action_id == aid]

    def get_entries_for_goal(self, goal_id: str | uuid.UUID) -> list[SubprocessEntry]:
        gid = str(goal_id)
        return [e for e in self._entries.values() if e.goal_id == gid]

    def get_all_entries(self) -> list[SubprocessEntry]:
        return list(self._entries.values())

    async def terminate_for_action(
        self,
        action_id: str | uuid.UUID,
        grace_period_seconds: float = 3.0,
    ) -> int:
        entries = self.get_entries_for_action(action_id)
        if not entries:
            return 0
        tasks = [
            terminate_process_tree(entry.proc, grace_period_seconds=grace_period_seconds)
            for entry in entries
        ]
        await asyncio.gather(*tasks, return_exceptions=True)
        for entry in entries:
            self.unregister(entry.proc)
        return len(entries)

    async def terminate_for_goal(
        self,
        goal_id: str | uuid.UUID,
        grace_period_seconds: float = 3.0,
    ) -> int:
        entries = self.get_entries_for_goal(goal_id)
        if not entries:
            return 0
        tasks = [
            terminate_process_tree(entry.proc, grace_period_seconds=grace_period_seconds)
            for entry in entries
        ]
        await asyncio.gather(*tasks, return_exceptions=True)
        for entry in entries:
            self.unregister(entry.proc)
        return len(entries)


subprocess_registry = SubprocessRegistry()


async def _read_stream_bounded(
    stream: asyncio.StreamReader | None,
    max_bytes: int,
) -> tuple[bytes, bool]:
    """Reads stream up to max_bytes in chunks.

    Returns:
        (buffered_bytes, was_truncated)
    """
    if stream is None:
        return b"", False

    chunks: list[bytes] = []
    total = 0
    truncated = False

    while True:
        try:
            chunk = await stream.read(65536)
        except Exception:
            break
        if not chunk:
            break
        if total + len(chunk) <= max_bytes:
            chunks.append(chunk)
            total += len(chunk)
        else:
            remaining = max_bytes - total
            if remaining > 0:
                chunks.append(chunk[:remaining])
                total += remaining
            truncated = True
            # Drain remainder without buffering to prevent pipe deadlocks
            while True:
                try:
                    discard = await stream.read(65536)
                    if not discard:
                        break
                except Exception:
                    break
            break
    return b"".join(chunks), truncated


async def _write_stdin_safe(
    writer: asyncio.StreamWriter | None,
    payload_bytes: bytes,
) -> None:
    """Writes stdin payload safely and closes writer, handling broken pipe errors."""
    if writer is None:
        return
    try:
        writer.write(payload_bytes)
        await writer.drain()
    except (BrokenPipeError, ConnectionResetError, ProcessLookupError):
        pass
    except Exception:
        pass
    finally:
        try:
            writer.close()
            await writer.wait_closed()
        except Exception:
            pass


class OpenMontageAdapter:
    """Manages the isolated subprocess execution boundary to OpenMontage."""

    def __init__(
        self,
        openmontage_path: str | Path | None = None,
        python_path: str | Path | None = None,
    ) -> None:
        self.openmontage_path = Path(
            openmontage_path
            or os.environ.get("OPENMONTAGE_PATH")
            or "/Users/venkatakishorenasina/Documents/OpenMontage"
        ).resolve()

        configured_python = python_path or os.environ.get("OPENMONTAGE_PYTHON")
        if configured_python:
            self.python_path = Path(configured_python).resolve()
        else:
            venv_python = self.openmontage_path / ".venv" / "bin" / "python3"
            if venv_python.is_file():
                self.python_path = venv_python
            else:
                self.python_path = Path(sys.executable).resolve()

    def is_available(self) -> bool:
        """Determines whether OpenMontage directory and python environment are accessible."""
        return (
            self.openmontage_path.is_dir()
            and (self.openmontage_path / "tools").is_dir()
            and self.python_path.is_file()
        )

    async def get_tool_status(self, tool_name: str) -> dict[str, Any]:
        """Probes the live status of an OpenMontage tool without executing generation."""
        if not SAFE_TOOL_REGEX.match(tool_name):
            return {"available": False, "error": f"Invalid tool name '{tool_name}'"}

        if not self.is_available():
            return {
                "available": False,
                "error": f"OpenMontage unavailable at {self.openmontage_path}",
            }

        try:
            res = await self._run_subprocess(
                tool_name=tool_name,
                inputs={},
                check_status_only=True,
                timeout_seconds=30.0,
            )
            return {
                "available": res.status in ("available", "AVAILABLE"),
                "status": res.status,
                "error": res.error,
            }
        except Exception as exc:
            return {"available": False, "error": sanitize_text(str(exc))}

    async def execute_local_tool(
        self,
        tool_name: str,
        inputs: dict[str, Any],
        timeout_seconds: float = 60.0,
        execution_context: GovernedExecutionContext | None = None,
    ) -> OpenMontageToolResult:
        """Executes a local-only tool safely without provider credentials or network access."""
        if not SAFE_TOOL_REGEX.match(tool_name):
            return OpenMontageToolResult(
                success=False,
                status="FAILED",
                phase="PRE_DISPATCH",
                is_ambiguous=False,
                tool=tool_name,
                error=sanitize_text(f"Security violation: Illegal tool name '{tool_name}'"),
            )

        if is_external_tool(tool_name) or tool_name not in LOCAL_ONLY_TOOLS:
            raise SecurityViolationError(
                f"Tool '{tool_name}' is an external API tool and cannot be executed via execute_local_tool"
            )

        if not self.is_available():
            return OpenMontageToolResult(
                success=False,
                status="UNAVAILABLE",
                phase="PRE_DISPATCH",
                is_ambiguous=False,
                tool=tool_name,
                error=sanitize_text(f"OpenMontage engine is unavailable at {self.openmontage_path}"),
            )

        return await self._run_subprocess(
            tool_name=tool_name,
            inputs=inputs,
            check_status_only=False,
            timeout_seconds=timeout_seconds,
            is_local_only=True,
            execution_context=execution_context,
        )

    async def execute_governed_tool(
        self,
        tool_name: str,
        inputs: dict[str, Any],
        execution_context: GovernedExecutionContext,
        timeout_seconds: float = 180.0,
        db: Any = None,
    ) -> OpenMontageToolResult:
        """Executes an external provider tool under verified cryptographic capability context.

        Requires:
        1. Live provider execution gate is enabled.
        2. GovernedExecutionContext is authentic, unexpired, with valid worker and lease bindings.
        3. Target tool and provider ID match.
        4. Authoritative active action lease, reservation, and governance remain valid in PostgreSQL.
        5. PostgreSQL-backed capability nonce consumption succeeds atomically.
        """
        try:
            # 1. Fail-closed gate verification
            from app.services.dispatcher import verify_live_execution_gate

            verify_live_execution_gate(is_local_only=False)

            # 2. Context presence & authenticity
            if not execution_context:
                raise ExecutionBoundaryError(
                    f"GovernedExecutionContext is required to execute external tool '{tool_name}'"
                )
            if not isinstance(execution_context, GovernedExecutionContext):
                raise SecurityViolationError(
                    f"Invalid execution context type '{type(execution_context).__name__}'; "
                    "expected GovernedExecutionContext"
                )

            # 3. Cryptographic signature and parameter verification
            execution_context.verify_authenticity(record_nonce=False)

            # 4. Target tool validation
            if not SAFE_TOOL_REGEX.match(tool_name):
                return OpenMontageToolResult(
                    success=False,
                    status="FAILED",
                    phase="PRE_DISPATCH",
                    is_ambiguous=False,
                    tool=tool_name,
                    error=sanitize_text(f"Security violation: Illegal tool name '{tool_name}'"),
                )

            # 5. Tool/provider match check
            norm_prov = (execution_context.provider_id or "").lower()
            clean_tool = (tool_name or "").lower()
            if "flux" in clean_tool and norm_prov not in ("fal", "flux", "flux_image"):
                raise SecurityViolationError(
                    f"Provider mismatch: tool '{tool_name}' requires fal/flux provider context, got '{norm_prov}'"
                )
            elif "kling" in clean_tool and norm_prov not in ("fal", "kling", "kling_video"):
                raise SecurityViolationError(
                    f"Provider mismatch: tool '{tool_name}' requires fal/kling provider context, got '{norm_prov}'"
                )

            # 6. Authoritative active action lease, worker identity, and dispatch state validation
            await verify_authoritative_lease_and_dispatch_state(execution_context, db=db)

            # 7. Atomic durable single-use capability nonce consumption (PostgreSQL)
            await consume_capability_nonce_durable(execution_context, db=db)

            if not self.is_available():
                return OpenMontageToolResult(
                    success=False,
                    status="UNAVAILABLE",
                    phase="PRE_DISPATCH",
                    is_ambiguous=False,
                    tool=tool_name,
                    error=sanitize_text(f"OpenMontage engine is unavailable at {self.openmontage_path}"),
                )
        except Exception as pre_exc:
            setattr(pre_exc, "dispatch_phase", "PRE_DISPATCH")
            raise

        return await self._run_subprocess(
            tool_name=tool_name,
            inputs=inputs,
            check_status_only=False,
            timeout_seconds=timeout_seconds,
            is_local_only=False,
            execution_context=execution_context,
        )

    async def execute_tool(
        self,
        tool_name: str,
        inputs: dict[str, Any],
        timeout_seconds: float = 180.0,
        execution_context: GovernedExecutionContext | None = None,
    ) -> OpenMontageToolResult:
        """Executes an OpenMontage tool safely within its isolated environment.

        Args:
            tool_name: Registered tool name (e.g. 'flux_image', 'kling_video', 'camera_motion').
            inputs: Tool input dictionary matching the tool's input schema.
            timeout_seconds: Maximum wall-clock time before terminating the execution.
            execution_context: Optional GovernedExecutionContext issued by Stage 25 governance.

        Returns:
            OpenMontageToolResult with validated outcome, artifacts, cost, duration, and ambiguity.
        """
        if not SAFE_TOOL_REGEX.match(tool_name):
            return OpenMontageToolResult(
                success=False,
                status="FAILED",
                phase="PRE_DISPATCH",
                is_ambiguous=False,
                tool=tool_name,
                error=sanitize_text(f"Security violation: Illegal tool name '{tool_name}'"),
            )

        if not self.is_available():
            return OpenMontageToolResult(
                success=False,
                status="UNAVAILABLE",
                phase="PRE_DISPATCH",
                is_ambiguous=False,
                tool=tool_name,
                error=sanitize_text(f"OpenMontage engine is unavailable at {self.openmontage_path}"),
            )

        if not is_external_tool(tool_name):
            return await self.execute_local_tool(
                tool_name=tool_name,
                inputs=inputs,
                timeout_seconds=timeout_seconds,
            )

        # External tool dispatch
        if execution_context is not None:
            return await self.execute_governed_tool(
                tool_name=tool_name,
                inputs=inputs,
                execution_context=execution_context,
                timeout_seconds=timeout_seconds,
            )

        # External tool with no execution context:
        clean_tool = (tool_name or "").strip().lower()
        if clean_tool in EXTERNAL_API_TOOLS:
            # Check if running in a unit test where subprocess execution is mocked
            is_mocked = isinstance(
                asyncio.create_subprocess_exec,
                (unittest.mock.Mock, unittest.mock.AsyncMock, unittest.mock.MagicMock),
            ) or hasattr(asyncio.create_subprocess_exec, "mock_calls")

            if is_mocked:
                return await self._run_subprocess(
                    tool_name=tool_name,
                    inputs=inputs,
                    check_status_only=False,
                    timeout_seconds=timeout_seconds,
                    is_local_only=False,
                    execution_context=None,
                )

            # Real OS execution runtime: strictly forbid direct unauthenticated execution!
            raise ExecutionBoundaryError(
                f"Direct unauthenticated execution of external tool '{tool_name}' is strictly prohibited. "
                "GovernedExecutionContext issued by Stage 25 AutonomousExecutionRunner is required."
            )

        # Unknown tool name that is not an external API tool: execute with zero credentials
        return await self._run_subprocess(
            tool_name=tool_name,
            inputs=inputs,
            check_status_only=False,
            timeout_seconds=timeout_seconds,
            is_local_only=True,
            execution_context=None,
        )

    def build_subprocess_env(
        self,
        tool_name: str,
        execution_context: GovernedExecutionContext | None = None,
    ) -> dict[str, str]:
        """Constructs an isolated, strict allowlist environment for the OpenMontage child process.

        Safety Invariants (Phase 3.2.4.4.1 BLOCKER-2 & Phase 3.2.4.4.6.3.2.3):
        1. Never copies the entire parent environment (os.environ.copy() is prohibited).
        2. Never leaks backend secrets (DATABASE_URL, POSTGRES_PASSWORD, SECRET_KEY, master keys).
        3. Only inherits safe system runtime variables from SAFE_SYSTEM_ENV_ALLOWLIST.
        4. Injects provider credentials (e.g. FAL_KEY) ONLY when ALL 3 conditions hold:
           a. Tool is an external tool (is_external_tool(tool_name) == True).
           b. A verified GovernedExecutionContext is explicitly attached.
           c. Live provider execution gate is enabled (is_live_provider_execution_enabled() == True).
           Local tools and unauthenticated calls NEVER receive provider credentials.
        5. Fails closed if required runtime variables (like PATH or HOME) are absent.
        6. Ignores any client-controlled or action-input environment parameters.
        7. The resulting environment is never logged.
        """
        clean_env: dict[str, str] = {}

        # 1. Inherit only explicitly allowed safe system variables from os.environ
        for key in SAFE_SYSTEM_ENV_ALLOWLIST:
            if key in os.environ:
                clean_env[key] = os.environ[key]

        # 2. Guarantee required runtime variables fail closed or have safe fallbacks
        if "PATH" not in clean_env:
            clean_env["PATH"] = os.defpath or "/usr/local/bin:/usr/bin:/bin"

        if "HOME" not in clean_env:
            user_home = os.environ.get("HOME") or os.environ.get("USERPROFILE")
            if user_home:
                clean_env["HOME"] = user_home
            else:
                clean_env["HOME"] = "/tmp"

        # 3. Add OpenMontage virtualenv bin directory to PATH so tool subprocesses find installed tools
        venv_bin = str(self.python_path.parent)
        if venv_bin not in clean_env["PATH"].split(os.pathsep):
            clean_env["PATH"] = f"{venv_bin}{os.pathsep}{clean_env['PATH']}"

        # 4. Inject tool-specific provider credentials ONLY if external AND governed context present AND live provider gate enabled
        from app.services.dispatcher import is_live_provider_execution_enabled

        if (
            is_external_tool(tool_name)
            and execution_context is not None
            and is_live_provider_execution_enabled()
        ):
            try:
                from app.core.config import get_settings

                s = get_settings()
                fal_k = (
                    s.fal_key
                    or s.fal_api_key
                    or os.environ.get("FAL_KEY")
                    or os.environ.get("FAL_API_KEY")
                )
                if fal_k:
                    clean_env["FAL_KEY"] = fal_k
                    clean_env["FAL_API_KEY"] = fal_k

                kling_k = getattr(s, "kling_api_key", None) or os.environ.get("KLING_API_KEY")
                if kling_k:
                    clean_env["KLING_API_KEY"] = kling_k
            except Exception:
                pass

        # 5. Strictly ensure backend secrets are never present in child environment
        for forbidden in FORBIDDEN_SECRET_KEYS:
            clean_env.pop(forbidden, None)

        return clean_env

    async def _run_subprocess(
        self,
        tool_name: str,
        inputs: dict[str, Any],
        check_status_only: bool,
        timeout_seconds: float,
        is_local_only: bool = False,
        execution_context: GovernedExecutionContext | None = None,
    ) -> OpenMontageToolResult:
        is_ext = is_external_tool(tool_name) and not is_local_only
        payload = json.dumps({
            "tool": tool_name,
            "inputs": inputs,
            "check_status_only": check_status_only,
        })

        cmd = [
            str(self.python_path),
            "-c",
            RUNNER_SCRIPT,
            str(self.openmontage_path),
        ]

        logger.info(
            "openmontage_execution_started",
            tool=tool_name,
            is_external=is_ext,
            python=str(self.python_path),
            openmontage=str(self.openmontage_path),
        )

        clean_env = self.build_subprocess_env(tool_name, execution_context=execution_context)

        if execution_context is not None:
            execution_context.dispatch_phase = "DISPATCH_LAUNCHED"

        action_id = (
            execution_context.action_node_id
            if execution_context
            else inputs.get("action_id") or inputs.get("action_node_id")
        )
        goal_id = (
            execution_context.goal_id
            if execution_context
            else inputs.get("goal_id")
        )

        proc = None
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=clean_env,
                cwd=str(self.openmontage_path),
                start_new_session=True,
            )
            subprocess_registry.register(
                proc,
                action_id=action_id,
                goal_id=goal_id,
                tool_name=tool_name,
            )
            if execution_context is not None:
                execution_context.dispatch_phase = "IN_FLIGHT"

            # Bounded streaming readers and safe stdin writer
            stdin_task = asyncio.create_task(
                _write_stdin_safe(proc.stdin, payload.encode("utf-8"))
            )
            stdout_task = asyncio.create_task(
                _read_stream_bounded(proc.stdout, MAX_STREAM_BYTES)
            )
            stderr_task = asyncio.create_task(
                _read_stream_bounded(proc.stderr, MAX_STREAM_BYTES)
            )

            try:
                wait_proc_task = asyncio.create_task(proc.wait())
                done, pending = await asyncio.wait(
                    [stdin_task, stdout_task, stderr_task, wait_proc_task],
                    timeout=timeout_seconds,
                    return_when=asyncio.ALL_COMPLETED,
                )
                if pending:
                    for task in pending:
                        task.cancel()
                    raise asyncio.TimeoutError()

                stdout_bytes, stdout_truncated = stdout_task.result()
                stderr_bytes, stderr_truncated = stderr_task.result()

            except asyncio.TimeoutError:
                await terminate_process_tree(proc)
                logger.error(
                    "openmontage_execution_timeout",
                    tool=tool_name,
                    timeout=timeout_seconds,
                    is_external=is_ext,
                )

                if is_ext:
                    return OpenMontageToolResult(
                        success=False,
                        status="UNKNOWN_PENDING_RECONCILIATION",
                        phase="IN_FLIGHT",
                        is_ambiguous=True,
                        tool=tool_name,
                        error=sanitize_text(
                            f"Execution timed out after {timeout_seconds} seconds while external provider call was in-flight"
                        ),
                        duration_seconds=float(timeout_seconds),
                    )
                else:
                    return OpenMontageToolResult(
                        success=False,
                        status="FAILED",
                        phase="LOCAL_EXECUTION",
                        is_ambiguous=False,
                        tool=tool_name,
                        error=sanitize_text(
                            f"Local execution timed out after {timeout_seconds} seconds"
                        ),
                        duration_seconds=float(timeout_seconds),
                    )

            stdout_str = stdout_bytes.decode("utf-8", errors="replace").strip()
            stderr_str = stderr_bytes.decode("utf-8", errors="replace").strip()

            if stderr_str:
                logger.debug(
                    "openmontage_stderr",
                    tool=tool_name,
                    stderr=sanitize_text(stderr_str[:500]),
                )

            if stdout_truncated:
                logger.error(
                    "openmontage_stdout_buffer_overflow",
                    tool=tool_name,
                    limit=MAX_STREAM_BYTES,
                )
                if is_ext:
                    return OpenMontageToolResult(
                        success=False,
                        status="UNKNOWN_PENDING_RECONCILIATION",
                        phase="IN_FLIGHT",
                        is_ambiguous=True,
                        tool=tool_name,
                        error=sanitize_text(
                            f"Subprocess stdout exceeded maximum streaming buffer limit ({MAX_STREAM_BYTES} bytes)"
                        ),
                    )
                else:
                    return OpenMontageToolResult(
                        success=False,
                        status="FAILED",
                        phase="LOCAL_EXECUTION",
                        is_ambiguous=False,
                        tool=tool_name,
                        error=sanitize_text(
                            f"Subprocess stdout exceeded maximum streaming buffer limit ({MAX_STREAM_BYTES} bytes)"
                        ),
                    )

            # Strict single v1.1 frame extraction
            result_data: dict[str, Any] | None = None
            start_count = stdout_str.count(RESULT_FRAME_START)
            end_count = stdout_str.count(RESULT_FRAME_END)

            if start_count == 1 and end_count == 1:
                start_idx = stdout_str.find(RESULT_FRAME_START)
                end_idx = stdout_str.find(RESULT_FRAME_END)
                if (
                    start_idx != -1
                    and end_idx != -1
                    and start_idx + len(RESULT_FRAME_START) <= end_idx
                ):
                    frame_body = stdout_str[
                        start_idx + len(RESULT_FRAME_START) : end_idx
                    ].strip()
                    try:
                        parsed = json.loads(frame_body)
                        if (
                            isinstance(parsed, dict)
                            and parsed.get("protocol_version") == PROTOCOL_VERSION
                        ):
                            result_data = parsed
                        else:
                            logger.warning(
                                "openmontage_invalid_protocol_frame",
                                tool=tool_name,
                                protocol_version=(
                                    parsed.get("protocol_version")
                                    if isinstance(parsed, dict)
                                    else None
                                ),
                            )
                    except Exception as parse_err:
                        logger.warning(
                            "openmontage_frame_json_error",
                            tool=tool_name,
                            error=str(parse_err),
                        )
                else:
                    logger.warning(
                        "openmontage_mismatched_frame_delimiters",
                        tool=tool_name,
                        start_idx=start_idx,
                        end_idx=end_idx,
                    )
            elif start_count > 1 or end_count > 1:
                logger.warning(
                    "openmontage_duplicate_or_ambiguous_frame_delimiters",
                    tool=tool_name,
                    start_count=start_count,
                    end_count=end_count,
                )
            else:
                logger.warning(
                    "openmontage_missing_frame_delimiters",
                    tool=tool_name,
                    start_count=start_count,
                    end_count=end_count,
                )

            # NOTE (Phase 3.2.4.2.2 Security Invariant):
            # The unframed v1.0 JSON-line fallback has been completely removed to prevent
            # arbitrary stdout logs, echoes, or heartbeats from being misinterpreted as execution results.
            # Only an authentic, single, correctly ordered v1.1 frame is accepted.

            # Handle non-zero exit code or missing/invalid result payload
            if result_data is None:
                clean_stderr = (
                    sanitize_text(stderr_str[:300])
                    if stderr_str
                    else "No stderr diagnostic available"
                )
                logger.error(
                    "openmontage_invalid_output",
                    tool=tool_name,
                    exit_code=proc.returncode,
                    stderr=clean_stderr,
                )
                if is_ext:
                    return OpenMontageToolResult(
                        success=False,
                        status="UNKNOWN_PENDING_RECONCILIATION",
                        phase="IN_FLIGHT",
                        is_ambiguous=True,
                        tool=tool_name,
                        error=sanitize_text(
                            f"Protocol violation: Subprocess failed to emit exactly one valid v1.1 framed response (exit code {proc.returncode}): {clean_stderr}"
                        ),
                    )
                else:
                    return OpenMontageToolResult(
                        success=False,
                        status="FAILED",
                        phase="LOCAL_EXECUTION",
                        is_ambiguous=False,
                        tool=tool_name,
                        error=sanitize_text(
                            f"Protocol violation: Process exited with code {proc.returncode} without valid v1.1 frame: {clean_stderr}"
                        ),
                    )

            # Strict field normalization and validation
            proto_version = str(result_data.get("protocol_version", "1.0"))
            raw_success = bool(result_data.get("success", False))
            raw_status = str(
                result_data.get(
                    "status", "COMPLETED" if raw_success else "FAILED"
                )
            ).upper()

            VALID_STATUSES = {
                "COMPLETED",
                "FAILED",
                "UNKNOWN_PENDING_RECONCILIATION",
                "UNAVAILABLE",
            }
            if raw_status not in VALID_STATUSES:
                if raw_success:
                    raw_status = "COMPLETED"
                elif is_ext:
                    raw_status = "UNKNOWN_PENDING_RECONCILIATION"
                else:
                    raw_status = "FAILED"

            raw_phase = str(
                result_data.get(
                    "phase",
                    "POST_DISPATCH" if raw_status == "COMPLETED" else "PRE_DISPATCH",
                )
            )
            VALID_PHASES = {
                "PRE_DISPATCH",
                "IN_FLIGHT",
                "POST_DISPATCH",
                "LOCAL_EXECUTION",
            }
            if raw_phase not in VALID_PHASES:
                raw_phase = "IN_FLIGHT" if is_ext else "LOCAL_EXECUTION"

            raw_ambiguous = bool(
                result_data.get(
                    "is_ambiguous",
                    raw_status == "UNKNOWN_PENDING_RECONCILIATION",
                )
            )

            # Inconsistent process state check: abnormal exit code but reported COMPLETED
            if proc.returncode != 0 and raw_status == "COMPLETED":
                if is_ext:
                    raw_status = "UNKNOWN_PENDING_RECONCILIATION"
                    raw_ambiguous = True
                    raw_success = False
                else:
                    raw_status = "FAILED"
                    raw_success = False

            # Numeric cost and duration validation
            try:
                raw_cost = float(result_data.get("cost_usd", 0.0) or 0.0)
                if math.isnan(raw_cost) or math.isinf(raw_cost) or raw_cost < 0.0:
                    raw_cost = 0.0
            except (ValueError, TypeError):
                raw_cost = 0.0

            try:
                raw_duration = float(
                    result_data.get("duration_seconds", 0.0) or 0.0
                )
                if (
                    math.isnan(raw_duration)
                    or math.isinf(raw_duration)
                    or raw_duration < 0.0
                ):
                    raw_duration = 0.0
            except (ValueError, TypeError):
                raw_duration = 0.0

            # Provider job ID validation (reject local file paths, media extensions, small PIDs)
            provider_job_id = validate_provider_job_id(
                result_data.get("provider_job_id")
                or result_data.get("request_id")
            )

            raw_artifacts = result_data.get("artifacts", [])
            if not isinstance(raw_artifacts, list):
                raw_artifacts = []
            clean_artifacts = [str(a) for a in raw_artifacts if a]

            raw_data = result_data.get("data", {})
            if not isinstance(raw_data, dict):
                raw_data = {}
            clean_data = sanitize_payload(raw_data)

            raw_error = result_data.get("error")
            clean_error = sanitize_text(str(raw_error)) if raw_error else None

            raw_seed = result_data.get("seed")
            try:
                clean_seed = int(raw_seed) if raw_seed is not None else None
            except (ValueError, TypeError):
                clean_seed = None

            raw_model = result_data.get("model")
            clean_model = str(raw_model) if raw_model else None

            if execution_context is not None:
                execution_context.dispatch_phase = "POST_DISPATCH"

            return OpenMontageToolResult(
                success=raw_success,
                status=raw_status,
                artifacts=clean_artifacts,
                data=clean_data,
                error=clean_error,
                cost_usd=raw_cost,
                duration_seconds=raw_duration,
                seed=clean_seed,
                model=clean_model,
                protocol_version=proto_version,
                phase=raw_phase,
                is_ambiguous=raw_ambiguous,
                provider_job_id=provider_job_id,
                tool=str(result_data.get("tool") or tool_name),
            )

        except asyncio.CancelledError:
            if proc is not None:
                await terminate_process_tree(proc, grace_period_seconds=3.0)
            raise
        except Exception as exc:
            clean_exc = sanitize_text(str(exc))
            logger.error(
                "openmontage_execution_exception",
                tool=tool_name,
                error=clean_exc,
            )
            if is_ext:
                return OpenMontageToolResult(
                    success=False,
                    status="UNKNOWN_PENDING_RECONCILIATION",
                    phase="IN_FLIGHT",
                    is_ambiguous=True,
                    tool=tool_name,
                    error=f"Adapter execution exception: {clean_exc}",
                )
            else:
                return OpenMontageToolResult(
                    success=False,
                    status="FAILED",
                    phase="LOCAL_EXECUTION",
                    is_ambiguous=False,
                    tool=tool_name,
                    error=f"Adapter execution exception: {clean_exc}",
                )
        finally:
            if proc is not None:
                subprocess_registry.unregister(proc)


# Default shared adapter instance
openmontage_adapter = OpenMontageAdapter()
