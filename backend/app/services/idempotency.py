"""
AryaOS V1 Stage 25 Phase 3.2.3 — Idempotency Engine & Durable Reconciliation.

Provides:
1. Stable Idempotency Identity & Cryptographic Fingerprinting for logical action nodes.
2. Pre-Dispatch Intent Persistence before crossing the execution boundary.
3. Provider Capability Introspection (idempotency keys, status lookup, consistency guarantees).
4. Output Validation Boundary preventing unverified outcomes from being marked successful.
5. Authoritative Reconciliation Service distinguishing confirmed successes, confirmed failures,
   in-progress tasks, and ambiguous outcomes to enforce safe retry policies.

SAFETY INVARIANTS:
- Ambiguous outcomes strictly transition to or remain UNKNOWN_PENDING_RECONCILIATION / RECOVERY_REQUIRED.
- An unknown outcome is NEVER coerced into success without supporting provider evidence and output validation.
- An eventually consistent provider returning 'not found' is NEVER treated as safe to retry.
- Server authoritative identity cannot be overridden by client-supplied inputs.
- All reconciliation audit traces and error messages are sanitized before persistence.
"""
from __future__ import annotations

import enum
import hashlib
import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.core.sanitization import sanitize_payload, sanitize_text
from app.core.security import AuthenticatedPrincipal
from app.events.log import EventType, log_event
from app.models.approval import ApprovalCheckpoint
from app.models.core import ApiKey, ProjectMembership, WorkflowRun
from app.models.enums import ApprovalAction
from app.models.execution_bridge import AutonomousActionNode, AutonomousGoal
from app.services.authorization_service import get_authorized_project_ids
from app.services.dispatcher import BaseExecutionDispatcher, ExecutionResult
from app.services.execution_bridge_service import (
    VALID_ACTION_STATES,
    VALID_ACTION_TRANSITIONS,
    VALID_GOAL_STATES,
    VALID_GOAL_TRANSITIONS,
    validate_state_transition,
)

logger = get_logger("arya.execution.idempotency")

# Ephemeral runtime keys excluded from logical action fingerprinting
VOLATILE_INPUT_KEYS = {
    "lease",
    "dispatch_intent",
    "dispatch_history",
    "reconciliation_history",
    "mock_failure",
    "mock_unknown",
    "mock_lookup_status",
    "mock_lookup_output",
    "mock_lookup_error",
}


# -----------------------------------------------------------------------------
# 1. Enums and Data Models
# -----------------------------------------------------------------------------

class ProviderConsistencyGuarantee(str, enum.Enum):
    """Documented consistency guarantee for provider status lookup endpoints."""

    STRONGLY_CONSISTENT = "STRONGLY_CONSISTENT"
    EVENTUALLY_CONSISTENT = "EVENTUALLY_CONSISTENT"
    NO_LOOKUP = "NO_LOOKUP"


class ReconciliationVerdict(str, enum.Enum):
    """Explicit authoritative reconciliation verdict for an ambiguous action."""

    CONFIRMED_SUCCESS = "CONFIRMED_SUCCESS"
    CONFIRMED_FAILURE = "CONFIRMED_FAILURE"
    CONFIRMED_IN_PROGRESS = "CONFIRMED_IN_PROGRESS"
    CONFIRMED_NOT_STARTED = "CONFIRMED_NOT_STARTED"
    IN_PROGRESS = "IN_PROGRESS"
    AMBIGUOUS_RETRY_UNSAFE = "AMBIGUOUS_RETRY_UNSAFE"
    LOOKUP_UNSUPPORTED = "LOOKUP_UNSUPPORTED"
    LEASE_EXPIRED = "LEASE_EXPIRED"
    EXPIRED_LEASE_RESOLVED = "EXPIRED_LEASE_RESOLVED"
    APPROVAL_REVOKED = "APPROVAL_REVOKED"


@dataclass(frozen=True)
class ProviderCapabilityProfile:
    """Introspective capability profile defining provider idempotency & lookup guarantees."""

    provider_id: str
    supports_idempotency_key: bool
    supports_status_lookup: bool
    consistency_guarantee: ProviderConsistencyGuarantee
    lookup_terminal_states: set[str] = field(default_factory=set)


@dataclass
class ReconciliationResult:
    """Normalized response contract for action reconciliation."""

    action_id: uuid.UUID
    verdict: ReconciliationVerdict
    can_safely_retry: bool
    previous_status: str
    new_status: str
    provider_status: str | None = None
    outputs: dict[str, Any] | None = None
    error: str | None = None
    evidence: dict[str, Any] = field(default_factory=dict)


ReconciliationReport = ReconciliationResult


# -----------------------------------------------------------------------------
# 2. Known Provider Capability Profiles
# -----------------------------------------------------------------------------

PROVIDER_PROFILES: dict[str, ProviderCapabilityProfile] = {
    "offline-mock": ProviderCapabilityProfile(
        provider_id="offline-mock",
        supports_idempotency_key=True,
        supports_status_lookup=True,
        consistency_guarantee=ProviderConsistencyGuarantee.STRONGLY_CONSISTENT,
        lookup_terminal_states={"SUCCEEDED", "FAILED", "REJECTED"},
    ),
    "mock": ProviderCapabilityProfile(
        provider_id="mock",
        supports_idempotency_key=True,
        supports_status_lookup=True,
        consistency_guarantee=ProviderConsistencyGuarantee.STRONGLY_CONSISTENT,
        lookup_terminal_states={"SUCCEEDED", "FAILED", "REJECTED"},
    ),
    "fal": ProviderCapabilityProfile(
        provider_id="fal",
        supports_idempotency_key=False,
        supports_status_lookup=False,
        consistency_guarantee=ProviderConsistencyGuarantee.NO_LOOKUP,
        lookup_terminal_states=set(),
    ),
    "kling": ProviderCapabilityProfile(
        provider_id="kling",
        supports_idempotency_key=False,
        supports_status_lookup=False,
        consistency_guarantee=ProviderConsistencyGuarantee.NO_LOOKUP,
        lookup_terminal_states=set(),
    ),
    "camera_motion": ProviderCapabilityProfile(
        provider_id="camera_motion",
        supports_idempotency_key=True,
        supports_status_lookup=False,
        consistency_guarantee=ProviderConsistencyGuarantee.NO_LOOKUP,
        lookup_terminal_states=set(),
    ),
    "mock-eventual": ProviderCapabilityProfile(
        provider_id="mock-eventual",
        supports_idempotency_key=False,
        supports_status_lookup=True,
        consistency_guarantee=ProviderConsistencyGuarantee.EVENTUALLY_CONSISTENT,
        lookup_terminal_states={"SUCCEEDED", "FAILED"},
    ),
}

DEFAULT_UNKNOWN_PROFILE = ProviderCapabilityProfile(
    provider_id="unknown",
    supports_idempotency_key=False,
    supports_status_lookup=False,
    consistency_guarantee=ProviderConsistencyGuarantee.NO_LOOKUP,
    lookup_terminal_states=set(),
)


def get_provider_capability_profile(provider_id: str | None) -> ProviderCapabilityProfile:
    """Looks up the capability profile for a provider in a fail-closed manner."""
    if not provider_id:
        return DEFAULT_UNKNOWN_PROFILE
    normalized = provider_id.strip().lower()
    return PROVIDER_PROFILES.get(normalized, DEFAULT_UNKNOWN_PROFILE)


# -----------------------------------------------------------------------------
# 3. Stable Identity & Pre-Dispatch Intent
# -----------------------------------------------------------------------------

def generate_action_idempotency_key(
    project_id: uuid.UUID,
    goal_id: uuid.UUID,
    action_id: uuid.UUID,
    client_action_id: str,
) -> str:
    """Generates a stable, server-authoritative idempotency key for a logical action node.

    Safety: Bound to project, goal, action primary key, and client DAG action ID.
    Clients cannot override or spoof this identity.
    """
    clean_cid = client_action_id.strip()
    return f"arya:action:{project_id}:{goal_id}:{action_id}:{clean_cid}"


def compute_action_fingerprint(action: AutonomousActionNode) -> str:
    """Calculates a deterministic cryptographic fingerprint (SHA-256) of action parameters.

    Excludes volatile runtime fields (worker leases, execution intents, mock flags).
    """
    inputs = dict(action.inputs_json or {})
    stable_inputs = {k: v for k, v in inputs.items() if k not in VOLATILE_INPUT_KEYS}

    canonical_representation = {
        "action_type": action.action_type,
        "required_capability": action.required_capability,
        "title": action.title,
        "inputs": stable_inputs,
    }
    encoded = json.dumps(canonical_representation, sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def record_pre_dispatch_intent(
    action: AutonomousActionNode,
    project_id: uuid.UUID,
    worker_id: str,
    lease_token: str,
    lease_epoch: int,
    provider_id: str | None = None,
) -> dict[str, Any]:
    """Records pre-dispatch intent in action inputs_json before crossing external execution boundary.

    Mutates action.inputs_json in-place so caller can commit to DB atomically.
    """
    idempotency_key = generate_action_idempotency_key(
        project_id=project_id,
        goal_id=action.goal_id,
        action_id=action.id,
        client_action_id=action.client_action_id,
    )
    fingerprint = compute_action_fingerprint(action)

    inputs = dict(action.inputs_json or {})
    dispatch_history = list(inputs.get("dispatch_history", []))

    previous_intent = inputs.get("dispatch_intent")
    attempt_num = (previous_intent.get("attempt", 0) + 1) if isinstance(previous_intent, dict) else 1

    intent_record = {
        "idempotency_key": idempotency_key,
        "action_fingerprint": fingerprint,
        "fingerprint": fingerprint,
        "attempt": attempt_num,
        "dispatched_at": datetime.now(timezone.utc).isoformat(),
        "worker_id": worker_id,
        "lease_token": lease_token,
        "lease_epoch": lease_epoch,
        "provider_id": provider_id or "offline-mock",
        "dispatch_state": "DISPATCH_COMMITTED",
        "provider_job_id": None,
    }

    inputs["dispatch_intent"] = intent_record
    dispatch_history.append(intent_record)
    inputs["dispatch_history"] = dispatch_history

    action.inputs_json = inputs
    return intent_record


# -----------------------------------------------------------------------------
# 4. Output Validation Boundary
# -----------------------------------------------------------------------------

def validate_action_outputs(
    action_type: str,
    outputs: dict[str, Any] | None,
) -> tuple[bool, str | None]:
    """Validates execution outputs before allowing an action to transition to SUCCEEDED.

    Prevents corrupt, empty, or failed responses from being coerced into success.
    """
    if not outputs or not isinstance(outputs, dict):
        return False, "Action output must be a non-empty dictionary"

    # Explicit failure payload masquerading as success
    if outputs.get("status") == "FAILED":
        return False, f"Output contains explicit failure status: {outputs.get('error')}"

    # For synthesis or media generation actions, verify delivery of artifacts
    act_type = (action_type or "").upper()
    if act_type in ("SYNTHESIS", "JOB_PACKAGE", "EXTERNAL_ACTION"):
        has_artifact = any(
            k in outputs
            for k in (
                "asset_url",
                "artifact_url",
                "media_asset_id",
                "image_url",
                "video_url",
                "audio_url",
                "simulated_result",
                "result",
            )
        )
        if not has_artifact and "tokens" not in outputs:
            return False, "Synthesis action output lacks required artifact url or result key"

    return True, None


# -----------------------------------------------------------------------------
# 5. Authoritative Action Reconciliation Service
# -----------------------------------------------------------------------------

class ActionReconciliationService:
    """Authoritative service for resolving ambiguous action executions."""

    def __init__(
        self,
        db: AsyncSession,
        dispatcher: BaseExecutionDispatcher | None = None,
        settings: Any | None = None,
    ) -> None:
        self.db = db
        self.dispatcher = dispatcher
        self.settings = settings

    async def _check_approval_validity(
        self,
        node: AutonomousActionNode,
        goal: AutonomousGoal,
    ) -> tuple[bool, str | None]:
        """Verifies that human approval checkpoint and operator credentials remain active and valid."""
        if not node.approval_checkpoint_id:
            if (
                node.risk_level in ("HIGH", "CRITICAL")
                or node.action_type == "DECISION"
                or node.status == "AWAITING_APPROVAL"
            ):
                return False, "Consequential action lacks required approval checkpoint reference"
            return True, None

        checkpoint = await self.db.get(ApprovalCheckpoint, node.approval_checkpoint_id)
        if not checkpoint:
            return False, "Referenced approval checkpoint does not exist"
        if checkpoint.action != ApprovalAction.APPROVE or checkpoint.decided_at is None:
            return False, f"Approval checkpoint is not approved (current action: {checkpoint.action})"
        if checkpoint.reference_table != "autonomous_action_nodes" or checkpoint.reference_id != node.id:
            return False, "Approval checkpoint reference does not match action node identity"
        if checkpoint.decided_by_actor_type != "human":
            return False, f"Approving actor type '{checkpoint.decided_by_actor_type}' is not a verified human"
        if not checkpoint.decided_by_principal_id:
            return False, "Approving human operator credential record is missing"

        approver_key = await self.db.get(ApiKey, checkpoint.decided_by_principal_id)
        if not approver_key or not approver_key.is_active or approver_key.principal_type != "human":
            return False, "Approving human operator credential has been revoked or deleted"

        stmt_pm = select(ProjectMembership).where(
            ProjectMembership.project_id == goal.project_id,
            ProjectMembership.api_key_id == approver_key.id,
        )
        res_pm = await self.db.execute(stmt_pm)
        if not res_pm.scalar_one_or_none():
            return False, f"Approving operator lacks active membership in project '{goal.project_id}'"

        return True, None

    async def reconcile(
        self,
        action_id: uuid.UUID,
        principal: AuthenticatedPrincipal,
        dispatcher: BaseExecutionDispatcher | None = None,
        force_unverified_retry: bool = False,
    ) -> tuple[AutonomousActionNode, ReconciliationResult]:
        """Atomically reconciles an action in UNKNOWN_PENDING_RECONCILIATION or expired lease.

        Enforces:
        - Row-level locking (with_for_update)
        - IDOR & Project Authorization checks
        - Verification of remote provider execution truth before authorization checks
        - Durable preservation of verified outputs even if authorization is invalidated
        - Output validation before marking success
        - Sanitization of all evidence and errors
        - Prohibition of unsafe retry when consistency guarantees are insufficient
        """
        active_dispatcher = dispatcher or self.dispatcher or OfflineMockDispatcher()

        # 1. Row-level lock on action node
        stmt = (
            select(AutonomousActionNode)
            .where(AutonomousActionNode.id == action_id)
            .with_for_update()
        )
        res = await self.db.execute(stmt)
        node = res.scalar_one_or_none()
        if not node:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Action node not found"
            )

        goal = await self.db.get(AutonomousGoal, node.goal_id, with_for_update=True)
        if not goal:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Parent goal not found"
            )

        # 2. Authorization & IDOR masking
        if not principal.is_admin:
            allowed = await get_authorized_project_ids(self.db, principal)
            if allowed is None or goal.project_id not in allowed:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND, detail="Action node not found"
                )

        previous_status = node.status

        # 3. Idempotent short-circuit for terminal or legal states
        if node.status == "SUCCEEDED":
            return node, ReconciliationResult(
                action_id=node.id,
                verdict=ReconciliationVerdict.CONFIRMED_SUCCESS,
                can_safely_retry=False,
                previous_status=previous_status,
                new_status="SUCCEEDED",
                outputs=node.outputs_json,
                evidence={"message": "Action has already completed successfully."},
            )

        # 4. Check pre-dispatch intent and lease
        inputs = dict(node.inputs_json or {})
        dispatch_intent = inputs.get("dispatch_intent")

        if not dispatch_intent:
            # Action was NEVER actually dispatched across external boundary!
            lease = inputs.get("lease", {}) if isinstance(inputs.get("lease"), dict) else {}
            expires_at_str = lease.get("expires_at")
            is_expired = False
            if expires_at_str:
                try:
                    if datetime.now(timezone.utc) > datetime.fromisoformat(expires_at_str):
                        is_expired = True
                except ValueError:
                    pass

            # Check approval validity
            appr_ok, appr_err = await self._check_approval_validity(node, goal)
            if not appr_ok:
                validate_state_transition(
                    "ActionNode",
                    node.status,
                    "FAILED",
                    VALID_ACTION_STATES,
                    VALID_ACTION_TRANSITIONS,
                    is_authoritative_engine=True,
                )
                node.status = "FAILED"
                node.error = appr_err
                self._record_reconciliation_audit(node, ReconciliationVerdict.APPROVAL_REVOKED, {"error": appr_err}, principal)
                await self.db.commit()
                return node, ReconciliationResult(
                    action_id=node.id,
                    verdict=ReconciliationVerdict.APPROVAL_REVOKED,
                    can_safely_retry=False,
                    previous_status=previous_status,
                    new_status="FAILED",
                    error=node.error,
                )

            verdict = ReconciliationVerdict.EXPIRED_LEASE_RESOLVED if is_expired else ReconciliationVerdict.CONFIRMED_FAILURE
            validate_state_transition(
                "ActionNode",
                node.status,
                "READY",
                VALID_ACTION_STATES,
                VALID_ACTION_TRANSITIONS,
                is_authoritative_engine=True,
            )
            node.status = "READY"
            node.error = None
            evidence = {"detail": "Action lease expired or not dispatched before interruption; safe to retry."}
            self._record_reconciliation_audit(node, verdict, evidence, principal)
            await self.db.commit()
            return node, ReconciliationResult(
                action_id=node.id,
                verdict=verdict,
                can_safely_retry=True,
                previous_status=previous_status,
                new_status="READY",
                evidence=evidence,
            )

        provider_id = dispatch_intent.get("provider_id", "offline-mock")
        profile = get_provider_capability_profile(provider_id)

        # 6. Provider Capability Check: Does provider support status query?
        if not profile.supports_status_lookup:
            # Provider cannot confirm status. Retrying is UNSAFE because provider might have executed.
            # Remain in UNKNOWN_PENDING_RECONCILIATION.
            evidence = {
                "provider_id": provider_id,
                "reason": "Provider does not support status lookup; outcome remains ambiguous.",
                "supports_lookup": False,
            }
            self._record_reconciliation_audit(node, ReconciliationVerdict.LOOKUP_UNSUPPORTED, evidence, principal)
            await self.db.commit()
            return node, ReconciliationResult(
                action_id=node.id,
                verdict=ReconciliationVerdict.LOOKUP_UNSUPPORTED,
                can_safely_retry=False,
                previous_status=previous_status,
                new_status=node.status,
                error="Provider does not support status query; manual operator intervention required",
                evidence=evidence,
            )

        # 7. Query Provider Status via Dispatcher
        provider_job_id = dispatch_intent.get("provider_job_id")
        try:
            status_result = await active_dispatcher.query_status(node, provider_job_id=provider_job_id)
        except Exception as exc:
            clean_err = sanitize_text(str(exc))
            evidence = {"query_error": clean_err}
            self._record_reconciliation_audit(node, ReconciliationVerdict.AMBIGUOUS_RETRY_UNSAFE, evidence, principal)
            await self.db.commit()
            return node, ReconciliationResult(
                action_id=node.id,
                verdict=ReconciliationVerdict.AMBIGUOUS_RETRY_UNSAFE,
                can_safely_retry=False,
                previous_status=previous_status,
                new_status=node.status,
                error=clean_err,
                evidence=evidence,
            )

        # 8. Evaluate Provider Status Query Result
        prov_status = (status_result.status or "").upper()

        if prov_status == "SUCCEEDED":
            # Output validation before marking success
            clean_out = sanitize_payload(status_result.output or {})
            is_valid, val_err = validate_action_outputs(node.action_type, clean_out)
            if not is_valid:
                # Corrupt output: cannot mark SUCCEEDED!
                validate_state_transition(
                    "ActionNode",
                    node.status,
                    "FAILED",
                    VALID_ACTION_STATES,
                    VALID_ACTION_TRANSITIONS,
                    is_authoritative_engine=True,
                )
                node.status = "FAILED"
                node.error = sanitize_text(f"Output validation failed: {val_err}")
                self._record_reconciliation_audit(node, ReconciliationVerdict.CONFIRMED_FAILURE, {"validation_error": val_err}, principal)
                await self.db.commit()
                return node, ReconciliationResult(
                    action_id=node.id,
                    verdict=ReconciliationVerdict.CONFIRMED_FAILURE,
                    can_safely_retry=True,
                    previous_status=previous_status,
                    new_status="FAILED",
                    error=node.error,
                )

            # Remote provider execution is confirmed successful!
            # Check operator approval validity before transitioning to workflow SUCCEEDED
            appr_ok, appr_err = await self._check_approval_validity(node, goal)
            if not appr_ok:
                # REMEDIATION 1: Never mark confirmed remote success as execution FAILED!
                # Preserve verified outputs, external job ID, cost, and historical truth.
                # Transition node to BLOCKED (workflow ineligible) and record APPROVAL_REVOKED.
                validate_state_transition(
                    "ActionNode",
                    node.status,
                    "BLOCKED",
                    VALID_ACTION_STATES,
                    VALID_ACTION_TRANSITIONS,
                    is_authoritative_engine=True,
                )
                node.status = "BLOCKED"
                node.outputs_json = clean_out
                node.error = sanitize_text(
                    f"Remote execution confirmed SUCCEEDED, but operator approval is invalidated: {appr_err}"
                )
                if "dispatch_intent" in inputs and isinstance(inputs["dispatch_intent"], dict):
                    inputs["dispatch_intent"]["dispatch_state"] = "COMPLETED_AUTHORIZATION_INVALIDATED"
                    inputs["dispatch_intent"]["status"] = "BLOCKED"
                node.inputs_json = inputs
                evidence = {
                    "remote_execution_succeeded": True,
                    "provider_status": "SUCCEEDED",
                    "approval_invalidation": appr_err,
                    "outputs_summary": clean_out,
                }
                self._record_reconciliation_audit(node, ReconciliationVerdict.APPROVAL_REVOKED, evidence, principal)
                await self.db.commit()

                return node, ReconciliationResult(
                    action_id=node.id,
                    verdict=ReconciliationVerdict.APPROVAL_REVOKED,
                    can_safely_retry=False,
                    previous_status=previous_status,
                    new_status="BLOCKED",
                    outputs=clean_out,
                    error=node.error,
                    evidence=evidence,
                )

            # Legitimate verified success with valid approval
            validate_state_transition(
                "ActionNode",
                node.status,
                "SUCCEEDED",
                VALID_ACTION_STATES,
                VALID_ACTION_TRANSITIONS,
                is_authoritative_engine=True,
            )
            node.status = "SUCCEEDED"
            node.outputs_json = clean_out
            node.error = None
            if "dispatch_intent" in inputs and isinstance(inputs["dispatch_intent"], dict):
                inputs["dispatch_intent"]["dispatch_state"] = "COMPLETED"
                inputs["dispatch_intent"]["status"] = "SUCCEEDED"
            node.inputs_json = inputs
            self._record_reconciliation_audit(node, ReconciliationVerdict.CONFIRMED_SUCCESS, {"status": "SUCCEEDED"}, principal)
            await self.db.commit()

            return node, ReconciliationResult(
                action_id=node.id,
                verdict=ReconciliationVerdict.CONFIRMED_SUCCESS,
                can_safely_retry=False,
                previous_status=previous_status,
                new_status="SUCCEEDED",
                outputs=clean_out,
            )

        elif prov_status == "FAILED":
            # Confirmed provider failure: safe to retry if permitted by approval
            clean_err = sanitize_text(status_result.error or "Provider confirmed execution failure")
            appr_ok, appr_err = await self._check_approval_validity(node, goal)
            validate_state_transition(
                "ActionNode",
                node.status,
                "FAILED",
                VALID_ACTION_STATES,
                VALID_ACTION_TRANSITIONS,
                is_authoritative_engine=True,
            )
            node.status = "FAILED"
            node.error = clean_err if appr_ok else f"{clean_err} (Approval also invalidated: {appr_err})"
            self._record_reconciliation_audit(
                node,
                ReconciliationVerdict.CONFIRMED_FAILURE,
                {"error": clean_err, "approval_valid": appr_ok},
                principal,
            )
            await self.db.commit()

            return node, ReconciliationResult(
                action_id=node.id,
                verdict=ReconciliationVerdict.CONFIRMED_FAILURE,
                can_safely_retry=appr_ok,
                previous_status=previous_status,
                new_status="FAILED",
                error=node.error,
            )

        elif prov_status in ("IN_PROGRESS", "RUNNING"):
            # Task is currently executing on remote provider
            evidence = {"provider_status": prov_status}
            self._record_reconciliation_audit(node, ReconciliationVerdict.CONFIRMED_IN_PROGRESS, evidence, principal)
            await self.db.commit()
            return node, ReconciliationResult(
                action_id=node.id,
                verdict=ReconciliationVerdict.CONFIRMED_IN_PROGRESS,
                can_safely_retry=False,
                previous_status=previous_status,
                new_status=node.status,
                evidence=evidence,
            )

        elif prov_status == "NOT_FOUND":
            # INVARIANT 9: 404 is not sufficient evidence for retry under eventual consistency!
            if profile.consistency_guarantee == ProviderConsistencyGuarantee.STRONGLY_CONSISTENT:
                appr_ok, appr_err = await self._check_approval_validity(node, goal)
                if not appr_ok:
                    validate_state_transition(
                        "ActionNode",
                        node.status,
                        "BLOCKED",
                        VALID_ACTION_STATES,
                        VALID_ACTION_TRANSITIONS,
                        is_authoritative_engine=True,
                    )
                    node.status = "BLOCKED"
                    node.error = sanitize_text(f"Job not started on provider, but approval is invalidated: {appr_err}")
                    evidence = {"consistency": "STRONGLY_CONSISTENT", "reason": "Not started, approval revoked"}
                    self._record_reconciliation_audit(node, ReconciliationVerdict.APPROVAL_REVOKED, evidence, principal)
                    await self.db.commit()
                    return node, ReconciliationResult(
                        action_id=node.id,
                        verdict=ReconciliationVerdict.APPROVAL_REVOKED,
                        can_safely_retry=False,
                        previous_status=previous_status,
                        new_status="BLOCKED",
                        error=node.error,
                        evidence=evidence,
                    )

                # Strongly consistent provider confirms task never existed: safe to retry
                validate_state_transition(
                    "ActionNode",
                    node.status,
                    "READY",
                    VALID_ACTION_STATES,
                    VALID_ACTION_TRANSITIONS,
                    is_authoritative_engine=True,
                )
                node.status = "READY"
                node.error = None
                evidence = {"consistency": "STRONGLY_CONSISTENT", "reason": "Confirmed task not found on provider"}
                self._record_reconciliation_audit(node, ReconciliationVerdict.CONFIRMED_NOT_STARTED, evidence, principal)
                await self.db.commit()
                return node, ReconciliationResult(
                    action_id=node.id,
                    verdict=ReconciliationVerdict.CONFIRMED_NOT_STARTED,
                    can_safely_retry=True,
                    previous_status=previous_status,
                    new_status="READY",
                    evidence=evidence,
                )
            else:
                # Eventually consistent: 404 is NOT sufficient evidence for retry
                evidence = {
                    "consistency": "EVENTUALLY_CONSISTENT",
                    "reason": "Provider returned 404 under eventual consistency; task may still be ingesting. Retry unsafe.",
                }
                self._record_reconciliation_audit(node, ReconciliationVerdict.AMBIGUOUS_RETRY_UNSAFE, evidence, principal)
                await self.db.commit()
                return node, ReconciliationResult(
                    action_id=node.id,
                    verdict=ReconciliationVerdict.AMBIGUOUS_RETRY_UNSAFE,
                    can_safely_retry=False,
                    previous_status=previous_status,
                    new_status=node.status,
                    error="Ambiguous outcome: provider returned not found under eventual consistency; retry blocked",
                    evidence=evidence,
                )

        else:
            # Unrecognized status: fail closed
            evidence = {"unrecognized_status": prov_status}
            self._record_reconciliation_audit(node, ReconciliationVerdict.AMBIGUOUS_RETRY_UNSAFE, evidence, principal)
            await self.db.commit()
            return node, ReconciliationResult(
                action_id=node.id,
                verdict=ReconciliationVerdict.AMBIGUOUS_RETRY_UNSAFE,
                can_safely_retry=False,
                previous_status=previous_status,
                new_status=node.status,
                error=f"Unrecognized provider status: {prov_status}",
                evidence=evidence,
            )

    def _record_reconciliation_audit(
        self,
        node: AutonomousActionNode,
        verdict: ReconciliationVerdict,
        evidence: dict[str, Any],
        principal: AuthenticatedPrincipal | None = None,
    ) -> None:
        """Appends sanitized reconciliation audit trace to node.inputs_json."""
        inputs = dict(node.inputs_json or {})
        reconciliation_history = list(inputs.get("reconciliation_history", []))

        trace = {
            "reconciled_at": datetime.now(timezone.utc).isoformat(),
            "verdict": verdict.value,
            "evidence": sanitize_payload(evidence),
            "reconciled_by_actor_type": principal.principal_type if principal else "system",
            "reconciled_by_principal_id": str(principal.api_key_id) if principal and principal.api_key_id else None,
        }
        reconciliation_history.append(trace)
        inputs["reconciliation_history"] = reconciliation_history
        inputs["last_reconciliation"] = trace

        # Also mirror to dispatch_intent for easy inspection
        if "dispatch_intent" in inputs and isinstance(inputs["dispatch_intent"], dict):
            inputs["dispatch_intent"]["reconciliation_audit"] = trace
            inputs["dispatch_intent"]["status"] = node.status

        node.inputs_json = inputs
