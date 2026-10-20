"""
AryaOS V1 Stage 25 Phase 3.1 — Offline Autonomous Execution Runner Core.

Provides bounded, deterministic, offline execution orchestration for persisted
missions, goals, and action DAGs.

MANDATORY BOUNDARIES:
- OFFLINE ONLY: Zero live provider API calls, zero outbound HTTP, zero OpenMontage
  subprocess spawning, zero filesystem production jobs, zero live connector actions.
- AUTHORITATIVE: Sole engine authorized to transition actions to SUCCEEDED and goals to COMPLETED.
- TRUTHFUL: Results are explicitly stamped as simulated (is_simulated=True).
- GOVERNED: Actions with risk_level in ("HIGH", "CRITICAL") halt at AWAITING_APPROVAL.
  Prohibits autonomous approval bypass.
- CONCURRENT LEASING: Employs database row locking (with_for_update) and worker leases
  to prevent concurrent workers from claiming the same action node.
- PRESERVATION OF UNKNOWN: Ambiguous outcomes transition to UNKNOWN_PENDING_RECONCILIATION
  and are NEVER coerced to SUCCEEDED.
"""
from __future__ import annotations

import asyncio
import json
import math
import re
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from sqlalchemy.orm.attributes import flag_modified

from app.core.logging import get_logger
from app.core.security import AuthenticatedPrincipal, is_safe_remote_url
from app.models.approval import ApprovalCheckpoint
from app.models.core import ApiKey, Project, ProjectMembership, WorkflowRun
from app.models.enums import ApprovalAction
from app.models.execution_bridge import (
    AutonomousActionNode,
    AutonomousGoal,
    BudgetReservation,
)
from app.services.authorization_service import get_authorized_project_ids, verify_project_access
from app.services.dag_validator import validate_plan_dag
from app.services.execution_bridge_service import (
    VALID_ACTION_STATES,
    VALID_ACTION_TRANSITIONS,
    VALID_GOAL_STATES,
    VALID_GOAL_TRANSITIONS,
    validate_state_transition,
)

logger = get_logger("arya.runner.offline")

from app.core.config import Settings
from app.core.sanitization import sanitize_payload, sanitize_text
from app.services.dispatcher import (
    BaseExecutionDispatcher,
    ExecutionResult,
    LiveExecutionGateError,
    LiveProviderDispatcher,
    MockExecutionResult,
    OfflineMockDispatcher,
    SIMULATION_WATERMARK,
    get_default_dispatcher,
    is_live_provider_execution_enabled,
    resolve_dispatcher,
    verify_live_execution_gate,
)
from app.services.idempotency import (
    ActionReconciliationService,
    ReconciliationReport,
    record_pre_dispatch_intent,
    validate_action_outputs,
)
from app.services.openmontage_adapter import (
    is_external_tool,
    subprocess_registry,
)


@dataclass
class ActiveTaskEntry:
    task: asyncio.Task[Any]
    goal_id: str
    action_id: str | None
    started_at: float


class ActiveTaskRegistry:
    """Registry tracking in-flight asyncio.Task instances executing goals and actions."""

    def __init__(self) -> None:
        self._tasks: dict[tuple[str, str | None], ActiveTaskEntry] = {}

    def register(
        self,
        task: asyncio.Task[Any],
        goal_id: str | uuid.UUID,
        action_id: str | uuid.UUID | None = None,
    ) -> None:
        gid = str(goal_id)
        aid = str(action_id) if action_id is not None else None
        self._tasks[(gid, aid)] = ActiveTaskEntry(
            task=task,
            goal_id=gid,
            action_id=aid,
            started_at=time.time(),
        )

    def unregister(
        self,
        goal_id: str | uuid.UUID,
        action_id: str | uuid.UUID | None = None,
    ) -> None:
        gid = str(goal_id)
        aid = str(action_id) if action_id is not None else None
        self._tasks.pop((gid, aid), None)

    def cancel_task(
        self,
        goal_id: str | uuid.UUID,
        action_id: str | uuid.UUID,
    ) -> bool:
        gid = str(goal_id)
        aid = str(action_id)
        entry = self._tasks.get((gid, aid))
        if entry and not entry.task.done():
            entry.task.cancel()
            return True
        return False

    def cancel_goal(
        self,
        goal_id: str | uuid.UUID,
    ) -> int:
        gid = str(goal_id)
        cancelled_count = 0
        for (g, a), entry in list(self._tasks.items()):
            if g == gid and not entry.task.done():
                entry.task.cancel()
                cancelled_count += 1
        return cancelled_count

    def get_active_tasks(
        self, goal_id: str | uuid.UUID | None = None
    ) -> list[ActiveTaskEntry]:
        if goal_id is None:
            return [e for e in self._tasks.values() if not e.task.done()]
        gid = str(goal_id)
        return [
            e for e in self._tasks.values() if e.goal_id == gid and not e.task.done()
        ]


active_task_registry = ActiveTaskRegistry()


def is_external_dispatch_committed(node: AutonomousActionNode) -> bool:
    """Evaluates whether an executing action has committed an external provider dispatch."""
    inputs = dict(node.inputs_json or {})
    intent = inputs.get("dispatch_intent")
    if not isinstance(intent, dict):
        return False
    dispatch_state = intent.get("dispatch_state")
    if dispatch_state != "DISPATCH_COMMITTED":
        return False
    provider_id = intent.get("provider_id", "")
    tool_name = inputs.get("tool") or inputs.get("tool_name") or node.required_capability
    if provider_id in ("offline-mock", "local", "mock", "offline", ""):
        return False
    if tool_name and not is_external_tool(tool_name):
        return False
    return True


# -----------------------------------------------------------------------------
# 1.5. Inter-Shot Binding & Multi-Shot Budget Exceptions (Phase 3.2.4.4.6 / 3.2.4.4.6.2)
# -----------------------------------------------------------------------------

class ActionValidationError(HTTPException, ValueError):
    """Raised when action node inputs violate authoritative validation rules (HTTP 422)."""
    def __init__(self, detail: str) -> None:
        HTTPException.__init__(self, status_code=422, detail=detail)
        ValueError.__init__(self, detail)


class BindingResolutionError(Exception):
    """Raised when an inter-shot input binding cannot be resolved."""
    pass


class BindingSecurityError(Exception):
    """Raised when an inter-shot input binding violates security constraints."""
    pass


class AggregateBudgetPreflightError(HTTPException, ValueError):
    """Raised when aggregate estimated cost exceeds available budget authority (HTTP 409)."""
    def __init__(self, detail: str) -> None:
        HTTPException.__init__(self, status_code=status.HTTP_409_CONFLICT, detail=detail)
        ValueError.__init__(self, detail)


RE_BINDING_EXPR = re.compile(r"^\$([a-zA-Z0-9_\-]+)\.([a-zA-Z0-9_]+)(?:\[(\d+)\])?$")


# -----------------------------------------------------------------------------
# 2. Dependency Graph Utilities
# -----------------------------------------------------------------------------

def extract_action_dependencies(
    plan_dag_json: dict[str, Any],
    actions: list[AutonomousActionNode] | None = None,
) -> dict[str, set[str]]:
    """Extracts a mapping of {client_action_id: set_of_prerequisite_ids} from DAG JSON."""
    deps: dict[str, set[str]] = {}

    # Initialize from actions if provided
    if actions:
        for a in actions:
            cid = a.client_action_id.strip()
            deps.setdefault(cid, set())
            # Support dependencies declared in inputs_json
            if isinstance(a.inputs_json, dict) and "dependencies" in a.inputs_json:
                for d in a.inputs_json["dependencies"]:
                    src = str(d).strip()
                    if src:
                        deps[cid].add(src)

    # 1. From "edges" list
    edges = plan_dag_json.get("edges")
    if isinstance(edges, list):
        for edge in edges:
            if isinstance(edge, dict):
                src = str(
                    edge.get("from") or edge.get("source") or edge.get("parent") or ""
                ).strip()
                tgt = str(
                    edge.get("to") or edge.get("target") or edge.get("child") or ""
                ).strip()
                if src and tgt:
                    deps.setdefault(tgt, set()).add(src)
                    deps.setdefault(src, set())

    # 2. From "action_dependencies" map: target -> list of sources
    dep_map = plan_dag_json.get("action_dependencies")
    if isinstance(dep_map, dict):
        for tgt_id, sources in dep_map.items():
            tgt = str(tgt_id).strip()
            if tgt:
                deps.setdefault(tgt, set())
                if isinstance(sources, list):
                    for s in sources:
                        src = str(s).strip()
                        if src:
                            deps[tgt].add(src)
                            deps.setdefault(src, set())

    return deps


# -----------------------------------------------------------------------------
# 2.5 Truthful Goal Summary Derivation
# -----------------------------------------------------------------------------

def derive_goal_completion_summary(actions: list[AutonomousActionNode]) -> str:
    """Derives a truthful goal completion summary based on authoritative action execution states.

    Preserves strict truth distinctions:
    - simulated/offline execution -> labeled '(simulated)'
    - real external-provider execution -> labeled '(real external)'
    - real local execution -> labeled '(real local)'
    - real mixed execution -> labeled '(real mixed)'
    - UNKNOWN / non-SUCCEEDED actions -> raises ValueError (refuses false success labeling)
    """
    if not actions:
        return "Goal completed successfully across 0 action nodes."

    # Validate that all actions are SUCCEEDED and none are UNKNOWN or AMBIGUOUS
    has_unknown = any(
        a.status in ("UNKNOWN_PENDING_RECONCILIATION", "RECOVERY_REQUIRED")
        or (isinstance(a.outputs_json, dict) and a.outputs_json.get("is_ambiguous") is True)
        or a.status != "SUCCEEDED"
        for a in actions
    )
    if has_unknown:
        raise ValueError("Cannot derive successful goal completion summary: actions contain non-SUCCEEDED or UNKNOWN status")

    EXTERNAL_PROVIDERS = {"kling", "fal", "flux", "openai", "anthropic", "minimax", "runway", "sora", "veo", "wan"}
    LOCAL_PROVIDERS = {"camera_motion", "camera_push", "local_diffusion", "blender_world"}

    modes: set[str] = set()
    for a in actions:
        outputs = a.outputs_json if isinstance(a.outputs_json, dict) else {}
        inputs = a.inputs_json if isinstance(a.inputs_json, dict) else {}
        intent = inputs.get("dispatch_intent", {}) if isinstance(inputs.get("dispatch_intent"), dict) else {}
        provider_id = intent.get("provider_id") or ""

        # 1. Authoritative check for simulated / offline execution
        if (
            outputs.get("is_simulated") is True
            or outputs.get("mock_mode") is True
            or provider_id in ("offline-mock", "mock")
        ):
            modes.add("simulated")
            continue

        # 2. Authoritative check for real external provider execution
        prov = (outputs.get("provider") or inputs.get("provider") or "").lower().strip()
        has_ext_job = bool(outputs.get("provider_job_id") or outputs.get("request_id") or intent.get("provider_job_id"))
        cost = float(a.cost_usd or 0.0)

        if prov in EXTERNAL_PROVIDERS or (cost > 0.0 and has_ext_job) or (has_ext_job and prov not in LOCAL_PROVIDERS):
            modes.add("real external")
        elif prov in LOCAL_PROVIDERS or outputs.get("format") in ("mp4", "png") or outputs.get("video_url") or outputs.get("artifacts"):
            modes.add("real local")
        elif provider_id == "openmontage-live":
            modes.add("real local")
        else:
            modes.add("simulated")

    n = len(actions)
    if modes == {"simulated"}:
        tag = "simulated"
    elif modes == {"real external"}:
        tag = "real external"
    elif modes == {"real local"}:
        tag = "real local"
    elif modes == {"real external", "real local"}:
        tag = "real mixed"
    else:
        tag = "mixed"

    return f"Goal completed successfully across {n} action nodes ({tag})."


# -----------------------------------------------------------------------------
# 3. Autonomous Execution Runner Core
# -----------------------------------------------------------------------------

class AutonomousExecutionRunner:
    """Coordinates offline autonomous DAG progression, leasing, and mock dispatch."""

    def __init__(
        self,
        db: AsyncSession,
        dispatcher: BaseExecutionDispatcher | str | None = None,
        worker_id: str | None = None,
        lease_duration_seconds: int = 120,
        settings: Settings | None = None,
        budget_authority_usd: float | None = None,
    ) -> None:
        self.db = db
        self.settings = settings
        self.dispatcher = resolve_dispatcher(dispatcher, settings=self.settings)
        self.worker_id = worker_id or f"worker-{uuid.uuid4().hex[:8]}"
        self.lease_duration_seconds = lease_duration_seconds
        self.budget_authority_usd = budget_authority_usd
        self.lease_token: str | None = None
        self.lease_epoch: int = 0

    def calculate_authoritative_action_cost(self, action: AutonomousActionNode) -> float:
        """Calculates authoritative estimated cost for an action node.

        Strictly ignores client-supplied cost values (e.g. inputs_json['cost_usd'],
        inputs_json['estimated_cost_usd'], inputs_json['cost']) to prevent bypass.
        """
        inputs = dict(action.inputs_json or {})
        cap = (action.required_capability or "").strip().upper()
        act_type = (action.action_type or "").strip().upper()

        if act_type not in ("GENERATION", "SYNTHESIS"):
            return 0.0

        provider = str(inputs.get("provider") or "").strip().lower()
        sim_prov = str(inputs.get("simulated_provider") or "").strip().lower()
        if not provider and sim_prov:
            provider = sim_prov
        elif not provider:
            from app.services.media_bridge import DEFAULT_PROVIDER_BY_CAPABILITY
            provider = DEFAULT_PROVIDER_BY_CAPABILITY.get(cap, "offline-mock")

        # If offline-mock is simulating a specific provider, inspect simulated_provider
        if provider in ("offline-mock", "mock"):
            if sim_prov and sim_prov not in ("offline-mock", "mock"):
                provider = sim_prov
            elif inputs.get("mock_authoritative_cost") is not None:
                try:
                    m_cost = float(inputs["mock_authoritative_cost"])
                except (ValueError, TypeError):
                    raise ActionValidationError(
                        f"Malformed mock_authoritative_cost '{inputs['mock_authoritative_cost']}': must be a valid number"
                    )
                if not math.isfinite(m_cost) or math.isnan(m_cost) or m_cost < 0:
                    raise ActionValidationError(
                        f"Invalid mock_authoritative_cost '{inputs['mock_authoritative_cost']}': must be finite and non-negative"
                    )
                return round(m_cost, 4)
            elif getattr(self.dispatcher, "mock_authoritative_cost_by_cid", {}).get(action.client_action_id) is not None:
                raw_c = self.dispatcher.mock_authoritative_cost_by_cid[action.client_action_id]
                m_cost = float(raw_c)
                if not math.isfinite(m_cost) or math.isnan(m_cost) or m_cost < 0:
                    raise ActionValidationError(f"Invalid dispatcher mock cost '{raw_c}': must be finite and non-negative")
                return round(m_cost, 4)
            elif getattr(self.dispatcher, "default_mock_authoritative_cost", None) is not None:
                raw_c = self.dispatcher.default_mock_authoritative_cost
                m_cost = float(raw_c)
                if not math.isfinite(m_cost) or math.isnan(m_cost) or m_cost < 0:
                    raise ActionValidationError(f"Invalid default mock cost '{raw_c}': must be finite and non-negative")
                return round(m_cost, 4)
            else:
                return 0.0

        if provider == "kling":
            raw_dur = inputs.get("duration_seconds")
            if raw_dur is None:
                raw_dur = inputs.get("duration")

            if raw_dur is None:
                # missing duration retains the provider baseline of 5.0 seconds
                dur = 5.0
            else:
                try:
                    dur = float(raw_dur)
                except (ValueError, TypeError):
                    raise ActionValidationError(
                        f"Invalid duration '{raw_dur}' for provider 'kling': malformed numeric value"
                    )

                if not math.isfinite(dur) or math.isnan(dur):
                    raise ActionValidationError(
                        f"Invalid duration '{raw_dur}' for provider 'kling': value must be finite"
                    )

                if dur <= 0:
                    raise ActionValidationError(
                        f"Invalid duration '{raw_dur}' for provider 'kling': duration must be strictly positive (got {dur})"
                    )

                if dur > 60.0:
                    raise ActionValidationError(
                        f"Invalid duration '{raw_dur}' for provider 'kling': duration exceeds maximum limit of 60 seconds (got {dur})"
                    )

            return round(0.10 * (dur / 5.0), 4)

        if provider in ("fal", "flux"):
            model = str(inputs.get("model") or "flux-pro/v1.1").lower()
            if "pro" in model or "1.1" in model:
                return 0.05
            return 0.03

        if provider in ("camera_motion", "local_motion", "local_diffusion", "blender_world"):
            return 0.0

        return 0.0

    def evaluate_aggregate_dag_budget(
        self,
        goal: AutonomousGoal,
        available_budget_usd: float | None = None,
        actions: list[AutonomousActionNode] | None = None,
    ) -> tuple[bool, float, float | None, str | None]:
        """Evaluates whether the aggregate estimated cost of all action nodes in a DAG
        can be satisfied by the available budget authority (GAP-01).

        Returns:
            (is_sufficient, aggregate_cost, budget_limit, error_reason)
        """
        if actions is not None:
            action_list = actions
        else:
            try:
                action_list = list(getattr(goal, "actions", []))
            except Exception:
                action_list = []
        aggregate_cost = sum(self.calculate_authoritative_action_cost(a) for a in action_list)
        aggregate_cost = round(aggregate_cost, 4)

        # 1. Establish budget limit
        plan_dag = dict(goal.plan_dag_json or {})
        budget_limit = available_budget_usd
        if budget_limit is None:
            for k in ("budget_limit_usd", "max_budget_usd", "budget_usd", "authorized_budget_usd"):
                if plan_dag.get(k) is not None:
                    try:
                        budget_limit = float(plan_dag[k])
                        break
                    except (ValueError, TypeError):
                        pass

        if budget_limit is None and getattr(self, "budget_authority_usd", None) is not None:
            budget_limit = float(self.budget_authority_usd)

        # 2. Check against budget limit if defined
        if budget_limit is not None:
            if aggregate_cost > budget_limit:
                err = (
                    f"Aggregate estimated cost ${aggregate_cost:.4f} exceeds available budget authority "
                    f"${budget_limit:.4f}. Preflight failed before Shot 01 dispatch."
                )
                return False, aggregate_cost, budget_limit, err

        return True, aggregate_cost, budget_limit, None

    async def reserve_aggregate_dag_budget(
        self,
        goal: AutonomousGoal,
        available_budget_usd: float | None = None,
    ) -> BudgetReservation:
        """Atomically reserves aggregate estimated budget for a Goal's current plan version.

        Critical Invariants (SEC-FINDING-01):
        - Serialized per project via PostgreSQL row lock: SELECT * FROM projects WHERE id = :id FOR UPDATE.
        - Calculates authoritative project budget ceiling.
        - Computes committed realized spend from SUCCEEDED actions in the project.
        - Computes active unconsumed reservations (status == 'RESERVED') for other goals.
        - available = authoritative_ceiling - committed - active_reservations.
        - If aggregate authoritative cost > available: fail closed before Shot 01 dispatch.
        - Otherwise creates or updates exactly ONE BudgetReservation for (goal_id, plan_version).
        - Idempotent: re-calling for the same (goal_id, plan_version) reuses the existing reservation.
        """
        now = datetime.now(timezone.utc)

        # 1. Row-level lock on Project
        stmt_proj = select(Project).where(Project.id == goal.project_id).with_for_update()
        res_proj = await self.db.execute(stmt_proj)
        project = res_proj.scalar_one_or_none()
        if not project:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")

        # 2. Authoritative project ceiling
        # Note: Client-supplied inputs or plan_dag_json must never inflate the authoritative ceiling.
        authoritative_ceiling = (
            float(project.budget_limit_usd)
            if project.budget_limit_usd is not None
            else (float(self.budget_authority_usd) if self.budget_authority_usd is not None else 100.0)
        )
        if available_budget_usd is not None:
            authoritative_ceiling = min(authoritative_ceiling, float(available_budget_usd))

        # Check plan_dag_json budget_limit_usd only if it sets a lower boundary, never higher
        plan_dag = dict(goal.plan_dag_json or {})
        for k in ("budget_limit_usd", "max_budget_usd", "budget_usd", "authorized_budget_usd"):
            if plan_dag.get(k) is not None:
                try:
                    plan_lim = float(plan_dag[k])
                    authoritative_ceiling = min(authoritative_ceiling, plan_lim)
                    break
                except (ValueError, TypeError):
                    pass

        # 3. Committed realized spend from authoritative AutonomousActionNode.cost_usd (SUCCEEDED actions in project)
        # Exclude current goal's actions from committed to prevent double-counting with its own reservation
        stmt_committed = (
            select(AutonomousActionNode.cost_usd)
            .join(AutonomousGoal, AutonomousActionNode.goal_id == AutonomousGoal.id)
            .where(
                AutonomousGoal.project_id == project.id,
                AutonomousGoal.id != goal.id,
                AutonomousActionNode.status == "SUCCEEDED",
                AutonomousActionNode.cost_usd.is_not(None),
            )
        )
        res_committed = await self.db.execute(stmt_committed)
        committed = sum(float(c) for c in res_committed.scalars().all())
        committed = round(committed, 4)

        # 4. Active unconsumed reservations: SUM(reserved_amount_usd - consumed_amount_usd) for status == 'RESERVED'
        stmt_reservations = select(BudgetReservation).where(
            BudgetReservation.project_id == project.id,
            BudgetReservation.status == "RESERVED",
        )
        res_reservations = await self.db.execute(stmt_reservations)
        all_active = list(res_reservations.scalars().all())

        curr_reservation: BudgetReservation | None = None
        active_reservations = 0.0
        for r in all_active:
            if r.goal_id == goal.id and r.plan_version == goal.current_plan_version:
                curr_reservation = r
            elif r.goal_id == goal.id and r.plan_version < goal.current_plan_version:
                # Previous plan version superseded by new governed replan: release unused residual
                r.status = "RELEASED"
                r.updated_at = now
            else:
                unconsumed = max(0.0, float(r.reserved_amount_usd) - float(r.consumed_amount_usd))
                active_reservations += unconsumed
        active_reservations = round(active_reservations, 4)

        # 5. Compute available headroom
        available = round(authoritative_ceiling - committed - active_reservations, 4)

        # 6. Aggregate authoritative cost for current goal actions
        stmt_act = select(AutonomousActionNode).where(AutonomousActionNode.goal_id == goal.id)
        res_act = await self.db.execute(stmt_act)
        actions = list(res_act.scalars().all())

        agg_cost = sum(self.calculate_authoritative_action_cost(a) for a in actions)
        agg_cost = round(agg_cost, 4)

        needed = agg_cost if curr_reservation is None else max(0.0, agg_cost - float(curr_reservation.reserved_amount_usd))

        if (curr_reservation is None and agg_cost > available) or (curr_reservation is not None and needed > available):
            err_msg = (
                f"Aggregate estimated cost ${agg_cost:.4f} exceeds available budget authority "
                f"${available:.4f}. Preflight failed before Shot 01 dispatch."
            )
            raise AggregateBudgetPreflightError(err_msg)

        # 7. Create or update exactly ONE reservation for (goal_id, plan_version)
        if curr_reservation:
            curr_reservation.reserved_amount_usd = agg_cost
            curr_reservation.updated_at = now
            reservation = curr_reservation
        else:
            stmt_existing = select(BudgetReservation).where(
                BudgetReservation.goal_id == goal.id,
                BudgetReservation.plan_version == goal.current_plan_version,
            )
            res_ex = await self.db.execute(stmt_existing)
            existing_rec = res_ex.scalar_one_or_none()
            if existing_rec:
                existing_rec.reserved_amount_usd = agg_cost
                existing_rec.status = "RESERVED"
                existing_rec.updated_at = now
                reservation = existing_rec
            else:
                reservation = BudgetReservation(
                    id=uuid.uuid4(),
                    project_id=project.id,
                    goal_id=goal.id,
                    plan_version=goal.current_plan_version,
                    reserved_amount_usd=agg_cost,
                    consumed_amount_usd=0.0,
                    status="RESERVED",
                    created_at=now,
                    updated_at=now,
                )
                self.db.add(reservation)

        await self.db.commit()
        await self.db.refresh(reservation)
        return reservation

    def resolve_action_input_bindings(
        self,
        goal: AutonomousGoal,
        node: AutonomousActionNode,
    ) -> None:
        """Resolves inter-shot input mappings ($<client_action_id>.<property>) from predecessor outputs (GAP-02).

        Enforces:
        - Resolves only completed predecessor actions (status == 'SUCCEEDED')
        - Resolves only persisted authoritative outputs (outputs_json)
        - Rejects missing predecessor outputs or unresolvable properties
        - Rejects references to actions outside the same Goal
        - Preserves project tenancy
        - Preserves artifact path confinement (rejects directory traversal '..')
        - Rejects system root escapes and sensitive directories
        - Preserves SSRF defenses (blocks private/loopback hosts)
        - Injects resolved values directly into inputs_json
        """
        inputs_data = dict(node.inputs_json or {})
        mapping = inputs_data.get("inputs_mapping")
        if not mapping or not isinstance(mapping, dict):
            return

        actions_by_cid = {a.client_action_id: a for a in goal.actions}
        updated_inputs = dict(inputs_data)
        resolved_bindings = dict(updated_inputs.get("resolved_bindings") or {})

        for target_param, expr in mapping.items():
            if not isinstance(expr, str):
                raise BindingResolutionError(
                    f"Binding expression for parameter '{target_param}' must be a string, got {type(expr)}"
                )

            m = RE_BINDING_EXPR.match(expr.strip())
            if not m:
                raise BindingResolutionError(
                    f"Malformed binding expression '{expr}' for input '{target_param}'. "
                    "Must follow syntax: '$<client_action_id>.<property>' or '$<client_action_id>.<property>[<index>]'"
                )

            pred_cid, prop_name, idx_str = m.group(1), m.group(2), m.group(3)
            idx = int(idx_str) if idx_str is not None else None

            # 1. Tenancy & Goal Scope Check
            pred_node = actions_by_cid.get(pred_cid)
            if not pred_node:
                raise BindingResolutionError(
                    f"Binding target action '{pred_cid}' does not exist in Goal '{goal.id}'"
                )

            if pred_node.goal_id != goal.id:
                raise BindingResolutionError(
                    f"Cross-goal reference rejected: action '{pred_cid}' belongs to goal '{pred_node.goal_id}', "
                    f"expected goal '{goal.id}'"
                )

            # 2. Predecessor Completion Check
            if pred_node.status != "SUCCEEDED":
                raise BindingResolutionError(
                    f"Cannot resolve binding for '{target_param}': predecessor action '{pred_cid}' has status "
                    f"'{pred_node.status}', expected 'SUCCEEDED'"
                )

            # 3. Output Presence Check
            outputs = dict(pred_node.outputs_json or {})
            if not outputs:
                raise BindingResolutionError(
                    f"Predecessor action '{pred_cid}' has empty or missing outputs_json"
                )

            # 4. Property Resolution
            resolved_val: Any = None
            if prop_name == "artifacts":
                raw_artifacts = outputs.get("artifacts") or []
                if not isinstance(raw_artifacts, list):
                    raise BindingResolutionError(
                        f"Predecessor '{pred_cid}' output 'artifacts' is not a list"
                    )
                if idx is not None:
                    if idx < 0 or idx >= len(raw_artifacts):
                        raise BindingResolutionError(
                            f"Artifact index [{idx}] out of bounds for predecessor '{pred_cid}' "
                            f"(total artifacts: {len(raw_artifacts)})"
                        )
                    resolved_val = raw_artifacts[idx]
                else:
                    resolved_val = raw_artifacts
            elif prop_name in outputs:
                raw_val = outputs[prop_name]
                if idx is not None:
                    if not isinstance(raw_val, (list, tuple)):
                        raise BindingResolutionError(
                            f"Property '{prop_name}' on predecessor '{pred_cid}' is not indexable"
                        )
                    if idx < 0 or idx >= len(raw_val):
                        raise BindingResolutionError(
                            f"Index [{idx}] out of bounds for property '{prop_name}' on predecessor '{pred_cid}'"
                        )
                    resolved_val = raw_val[idx]
                else:
                    resolved_val = raw_val
            elif prop_name in ("artifact_url", "image_url", "video_url"):
                raw_artifacts = outputs.get("artifacts") or []
                if isinstance(raw_artifacts, list) and raw_artifacts:
                    resolved_val = raw_artifacts[0]
                else:
                    raise BindingResolutionError(
                        f"Property '{prop_name}' not found in outputs of predecessor '{pred_cid}'"
                    )
            else:
                raise BindingResolutionError(
                    f"Property '{prop_name}' not found in outputs of predecessor '{pred_cid}'"
                )

            # 5. Security Validation
            if isinstance(resolved_val, str):
                clean_val = resolved_val.strip()
                # A. Path traversal guard
                if ".." in clean_val:
                    raise BindingSecurityError(
                        f"Security violation: Path traversal detected in resolved binding '{target_param}': '{clean_val}'"
                    )

                # B. SSRF guard
                if clean_val.startswith(("http://", "https://", "file://", "gcs://", "s3://", "ftp://")):
                    if not is_safe_remote_url(clean_val):
                        raise BindingSecurityError(
                            f"Security violation: SSRF blocked for URL '{clean_val}' in resolved binding '{target_param}'"
                        )
                # C. Sensitive filesystem escape guard
                elif clean_val.startswith("/"):
                    p = Path(clean_val).resolve()
                    for bad in ("/etc", "/var", "/usr", "/bin", "/sbin", "/root"):
                        if str(p).startswith(bad):
                            raise BindingSecurityError(
                                f"Security violation: Prohibited system path access in binding: '{clean_val}'"
                            )
                    for sensitive in (".ssh", ".env", ".gemini"):
                        if sensitive in str(p):
                            raise BindingSecurityError(
                                f"Security violation: Prohibited credential path access in binding: '{clean_val}'"
                            )

            updated_inputs[target_param] = resolved_val
            resolved_bindings[target_param] = expr

        updated_inputs["resolved_bindings"] = resolved_bindings
        node.inputs_json = updated_inputs

    @classmethod
    def resolve_dag_readiness(
        cls,
        plan_dag_json: dict[str, Any],
        actions: list[AutonomousActionNode],
    ) -> dict[str, str]:
        """Evaluates readiness of actions based on prerequisite statuses."""
        dep_graph = extract_action_dependencies(plan_dag_json, actions)
        status_by_cid = {a.client_action_id: a.status for a in actions}
        node_by_cid = {a.client_action_id: a for a in actions}
        updates: dict[str, str] = {}

        for a in actions:
            cid = a.client_action_id
            current_status = a.status

            if current_status == "PENDING":
                prereqs = dep_graph.get(cid, set())

                # Definitive prerequisite failure or block permanently blocks downstream
                has_definitive_failure = any(
                    status_by_cid.get(p) in ("FAILED", "BLOCKED", "SKIPPED", "CANCELLED")
                    for p in prereqs
                )
                if has_definitive_failure:
                    updates[cid] = "BLOCKED"
                    continue

                # Ambiguous or incomplete prerequisites keep downstream held in PENDING.
                # All prerequisites must be strictly SUCCEEDED to become READY.
                all_prereqs_succeeded = all(
                    status_by_cid.get(p) == "SUCCEEDED" for p in prereqs
                )
                if all_prereqs_succeeded:
                    # Check if action requires human approval
                    if a.risk_level in ("HIGH", "CRITICAL") or a.action_type == "DECISION":
                        updates[cid] = "AWAITING_APPROVAL"
                    else:
                        updates[cid] = "READY"

            elif current_status == "READY":
                prereqs = dep_graph.get(cid, set())
                # If a prerequisite failed, became ambiguous, or is no longer SUCCEEDED
                if any(
                    status_by_cid.get(p) in (
                        "FAILED",
                        "BLOCKED",
                        "SKIPPED",
                        "UNKNOWN_PENDING_RECONCILIATION",
                        "RECOVERY_REQUIRED",
                        "EXECUTING",
                        "CANCELLED",
                    )
                    for p in prereqs
                ):
                    updates[cid] = "BLOCKED"

            elif current_status == "BLOCKED":
                prereqs = dep_graph.get(cid, set())
                # If all prerequisites are now SUCCEEDED, unblock to READY or AWAITING_APPROVAL
                has_prereq_blocking = any(
                    status_by_cid.get(p) in (
                        "FAILED",
                        "BLOCKED",
                        "SKIPPED",
                        "UNKNOWN_PENDING_RECONCILIATION",
                        "RECOVERY_REQUIRED",
                        "CANCELLED",
                    )
                    for p in prereqs
                )
                if not has_prereq_blocking and prereqs:
                    all_prereqs_succeeded = all(
                        status_by_cid.get(p) == "SUCCEEDED" for p in prereqs
                    )
                    if all_prereqs_succeeded:
                        if a.risk_level in ("HIGH", "CRITICAL") or a.action_type == "DECISION":
                            updates[cid] = "AWAITING_APPROVAL"
                        else:
                            updates[cid] = "READY"

        return updates

    def evaluate_dag_readiness(
        self,
        goal: AutonomousGoal,
    ) -> dict[str, str]:
        """Evaluates readiness of PENDING actions based on prerequisite statuses.

        Returns:
            dict of {client_action_id: new_target_state} for actions whose state must update.
        """
        return self.resolve_dag_readiness(goal.plan_dag_json or {}, goal.actions or [])

    async def apply_dag_readiness_updates(
        self,
        goal_id: uuid.UUID,
        principal: AuthenticatedPrincipal,
    ) -> list[AutonomousActionNode]:
        """Calculates and applies DAG readiness state transitions for all actions in a goal."""
        stmt = (
            select(AutonomousGoal)
            .where(AutonomousGoal.id == goal_id)
            .options(selectinload(AutonomousGoal.actions))
        )
        res = await self.db.execute(stmt)
        goal = res.scalar_one_or_none()
        if not goal:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Goal not found"
            )

        if not principal.is_admin:
            allowed = await get_authorized_project_ids(self.db, principal)
            if allowed is None or goal.project_id not in allowed:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND, detail="Goal not found"
                )

        updates = self.evaluate_dag_readiness(goal)
        updated_nodes: list[AutonomousActionNode] = []

        if updates:
            for action in goal.actions:
                new_state = updates.get(action.client_action_id)
                if new_state and new_state != action.status:
                    validate_state_transition(
                        "ActionNode",
                        action.status,
                        new_state,
                        VALID_ACTION_STATES,
                        VALID_ACTION_TRANSITIONS,
                        is_authoritative_engine=True,
                    )
                    action.status = new_state
                    updated_nodes.append(action)

            await self.db.commit()

        return updated_nodes

    async def _fetch_goal_with_actions(self, goal_id: uuid.UUID) -> AutonomousGoal:
        """Helper to re-fetch a goal with all actions eagerly loaded to avoid greenlet errors."""
        stmt = (
            select(AutonomousGoal)
            .where(AutonomousGoal.id == goal_id)
            .options(selectinload(AutonomousGoal.actions))
        )
        res = await self.db.execute(stmt)
        return res.scalar_one()

    async def renew_lease(
        self,
        action_id: uuid.UUID,
        lease_token: str,
        lease_epoch: int,
        session: AsyncSession | None = None,
    ) -> bool:
        """Atomically renews the lease expiration timestamp for an executing action node.

        Enforces:
        - Row-level locking
        - Strict fencing token check: lease_token, epoch, and worker_id must match
        - Node status must be EXECUTING
        - If fencing check fails or status is not EXECUTING, rejects renewal and returns False.
        """
        async def _do_renew(s: AsyncSession) -> bool:
            stmt = (
                select(AutonomousActionNode)
                .where(AutonomousActionNode.id == action_id)
                .with_for_update()
            )
            res = await s.execute(stmt)
            node = res.scalar_one_or_none()
            if not node or node.status != "EXECUTING":
                return False

            curr_lease = (node.inputs_json or {}).get("lease", {})
            if not isinstance(curr_lease, dict):
                return False

            if (
                curr_lease.get("lease_token") != lease_token
                or curr_lease.get("epoch") != lease_epoch
                or curr_lease.get("worker_id") != self.worker_id
            ):
                logger.warning(
                    "lease_renewal_fencing_mismatch",
                    action_id=str(action_id),
                    expected_worker=self.worker_id,
                    found_worker=curr_lease.get("worker_id"),
                    expected_epoch=lease_epoch,
                    found_epoch=curr_lease.get("epoch"),
                )
                return False

            now = datetime.now(timezone.utc)
            inputs_data = dict(node.inputs_json or {})
            updated_lease = dict(curr_lease)
            updated_lease["expires_at"] = (
                now + timedelta(seconds=self.lease_duration_seconds)
            ).isoformat()
            updated_lease["last_heartbeat_at"] = now.isoformat()
            inputs_data["lease"] = updated_lease
            node.inputs_json = inputs_data
            await s.commit()
            return True

        if session is not None:
            return await _do_renew(session)
        else:
            async with AsyncSessionLocal() as s:
                return await _do_renew(s)

    async def _run_heartbeat_loop(
        self,
        action_id: uuid.UUID,
        lease_token: str,
        lease_epoch: int,
        interval_seconds: int,
    ) -> None:
        """Background coroutine that periodically renews the lease while dispatch is executing."""
        try:
            while True:
                await asyncio.sleep(interval_seconds)
                try:
                    success = await self.renew_lease(
                        action_id=action_id,
                        lease_token=lease_token,
                        lease_epoch=lease_epoch,
                    )
                    if not success:
                        logger.warning(
                            "heartbeat_renewal_stopped",
                            action_id=str(action_id),
                            reason="Renewal rejected by fencing or state mismatch",
                        )
                        break
                except Exception as exc:
                    logger.warning(
                        "heartbeat_renewal_tick_failed",
                        action_id=str(action_id),
                        error=str(exc),
                    )
        except asyncio.CancelledError:
            pass

    async def dispatch_action(
        self,
        action_id: uuid.UUID,
        principal: AuthenticatedPrincipal,
    ) -> AutonomousActionNode:
        """Atomically claims and dispatches a single action node offline.

        Enforces:
        - Atomic row-locking (with_for_update)
        - Project authorization & IDOR masking
        - Legal state validation (READY -> EXECUTING)
        - Idempotency & duplicate worker prevention
        - High-risk human approval verification
        - Preservation of UNKNOWN invariant
        """
        # 1. Lock action node row
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

        goal = await self.db.get(AutonomousGoal, node.goal_id)
        if not goal:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Parent goal not found"
            )

        # IDOR masking
        if not principal.is_admin:
            allowed = await get_authorized_project_ids(self.db, principal)
            if allowed is None or goal.project_id not in allowed:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND, detail="Action node not found"
                )

        # 2. Idempotency Check
        if node.status == "SUCCEEDED":
            # Action has already completed successfully
            return node

        # If node is PENDING, attempt to advance DAG readiness and goal state
        if node.status == "PENDING":
            parent_goal = await self._fetch_goal_with_actions(node.goal_id)

            if parent_goal.status in ("DRAFT", "PLANNING"):
                action_cids = [a.client_action_id for a in parent_goal.actions]
                validate_plan_dag(parent_goal.plan_dag_json or {}, action_client_ids=action_cids)
                validate_state_transition(
                    "Goal",
                    parent_goal.status,
                    "READY",
                    VALID_GOAL_STATES,
                    VALID_GOAL_TRANSITIONS,
                    is_authoritative_engine=True,
                )
                parent_goal.status = "READY"
                validate_state_transition(
                    "Goal",
                    parent_goal.status,
                    "EXECUTING",
                    VALID_GOAL_STATES,
                    VALID_GOAL_TRANSITIONS,
                    is_authoritative_engine=True,
                )
                parent_goal.status = "EXECUTING"
                await self.db.commit()
            elif parent_goal.status == "READY":
                validate_state_transition(
                    "Goal",
                    parent_goal.status,
                    "EXECUTING",
                    VALID_GOAL_STATES,
                    VALID_GOAL_TRANSITIONS,
                    is_authoritative_engine=True,
                )
                parent_goal.status = "EXECUTING"
                await self.db.commit()

            await self.apply_dag_readiness_updates(node.goal_id, principal)

            # Re-lock row with latest status
            stmt = (
                select(AutonomousActionNode)
                .where(AutonomousActionNode.id == action_id)
                .with_for_update()
            )
            res = await self.db.execute(stmt)
            node = res.scalar_one()

        # GAP-01 & SEC-FINDING-01: Atomic Aggregate Multi-Shot Budget Reservation before first shot dispatch
        parent_goal = await self._fetch_goal_with_actions(node.goal_id)
        has_executed_actions = any(
            a.status in ("EXECUTING", "SUCCEEDED") for a in parent_goal.actions if a.id != node.id
        )
        if not has_executed_actions and node.status != "SUCCEEDED":
            try:
                await self.reserve_aggregate_dag_budget(parent_goal)
            except (AggregateBudgetPreflightError, HTTPException) as b_err:
                detail_str = getattr(b_err, "detail", str(b_err))
                if parent_goal.status != "BLOCKED":
                    validate_state_transition(
                        "Goal",
                        parent_goal.status,
                        "BLOCKED",
                        VALID_GOAL_STATES,
                        VALID_GOAL_TRANSITIONS,
                        is_authoritative_engine=True,
                    )
                    parent_goal.status = "BLOCKED"
                    parent_goal.failure_reason = detail_str
                    await self.db.commit()
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=detail_str,
                )

        # 3. Active Worker Lease & Ambiguous Execution Check
        if node.status == "EXECUTING":
            lease = (node.inputs_json or {}).get("lease", {})
            expires_at_str = lease.get("expires_at")
            worker_id = lease.get("worker_id", "unknown")
            if expires_at_str:
                try:
                    expires_at = datetime.fromisoformat(expires_at_str)
                    if datetime.now(timezone.utc) < expires_at:
                        # Another active worker holds the unexpired lease
                        raise HTTPException(
                            status_code=status.HTTP_409_CONFLICT,
                            detail=(
                                f"Action '{node.client_action_id}' is currently claimed by worker "
                                f"'{worker_id}' until {expires_at_str}"
                            ),
                        )
                    else:
                        # Lease expired, but direct redispatch is strictly prohibited to prevent duplicate execution!
                        raise HTTPException(
                            status_code=status.HTTP_409_CONFLICT,
                            detail=(
                                f"Action '{node.client_action_id}' lease held by worker '{worker_id}' "
                                f"expired at {expires_at_str}. Direct redispatch is prohibited to prevent duplicate "
                                "execution. Action must be authoritatively reconciled via reconcile_action first."
                            ),
                        )
                except ValueError:
                    pass
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Action '{node.client_action_id}' is currently in status 'EXECUTING' and cannot be directly redispatched. Reconcile first.",
            )

        # 4. Human Approval Verification for AWAITING_APPROVAL or Consequential (High-Risk/Critical/Decision)
        requires_approval = (
            node.status == "AWAITING_APPROVAL"
            or node.risk_level in ("HIGH", "CRITICAL")
            or node.action_type == "DECISION"
        )
        if requires_approval:
            if not node.approval_checkpoint_id:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=f"Action '{node.client_action_id}' requires human operator approval before dispatch",
                )
            checkpoint = await self.db.get(ApprovalCheckpoint, node.approval_checkpoint_id)
            if not checkpoint:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="Referenced approval checkpoint does not exist",
                )
            if checkpoint.reference_table != "autonomous_action_nodes" or checkpoint.reference_id != node.id:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=(
                        f"Approval checkpoint reference ({checkpoint.reference_table}:{checkpoint.reference_id}) "
                        f"does not match action node ({node.id})"
                    ),
                )
            if checkpoint.action != ApprovalAction.APPROVE or checkpoint.decided_at is None:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=f"Action '{node.client_action_id}' requires decided human approval before dispatch (current: {checkpoint.action})",
                )
            run = await self.db.get(WorkflowRun, checkpoint.workflow_run_id)
            if not run or run.project_id != goal.project_id:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Approval checkpoint belongs to a different project",
                )

            # Durable human approval provenance & live credential verification
            if not checkpoint.decided_by_actor_type:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="Approval checkpoint lacks verifiable human provenance (legacy approval without actor attribution)",
                )

            if checkpoint.decided_by_actor_type != "human":
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=f"Action requires human operator approval; credential actor type '{checkpoint.decided_by_actor_type}' is not human",
                )

            if not checkpoint.decided_by_principal_id:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="Approving human operator credential record is missing or has been deleted",
                )

            approver_key = await self.db.get(ApiKey, checkpoint.decided_by_principal_id)
            if not approver_key or not approver_key.is_active:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="Approving human operator credential has been revoked or deleted",
                )

            if approver_key.principal_type != "human":
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=f"Approving credential '{approver_key.name}' is no longer designated as a human operator",
                )

            # Verify approving operator currently holds active project membership
            stmt_pm = select(ProjectMembership).where(
                ProjectMembership.project_id == goal.project_id,
                ProjectMembership.api_key_id == approver_key.id,
            )
            res_pm = await self.db.execute(stmt_pm)
            if not res_pm.scalar_one_or_none():
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail=f"Approving operator does not have active membership in project '{goal.project_id}'",
                )

        # 4.5. Fail-closed gate check: if dispatcher targets live execution, verify configuration gate
        if getattr(self.dispatcher, "is_live", False):
            is_local = getattr(self.dispatcher, "local_only", False)
            verify_live_execution_gate(self.settings, is_local_only=is_local)

        # 5. Must be READY (or approved AWAITING_APPROVAL)
        if node.status not in ("READY", "AWAITING_APPROVAL"):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Action cannot be dispatched from status '{node.status}'. Must be READY.",
            )

        # GAP-02: Resolve inter-shot input bindings from predecessor outputs
        parent_goal = await self._fetch_goal_with_actions(node.goal_id)
        try:
            self.resolve_action_input_bindings(parent_goal, node)
        except (BindingResolutionError, BindingSecurityError) as b_err:
            validate_state_transition(
                "ActionNode",
                node.status,
                "BLOCKED",
                VALID_ACTION_STATES,
                VALID_ACTION_TRANSITIONS,
                is_authoritative_engine=True,
            )
            node.status = "BLOCKED"
            node.error = f"Input binding resolution failed: {b_err}"
            await self.db.commit()
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=node.error,
            )

        # 6. Atomically claim lease and transition to EXECUTING
        parent_goal = await self._fetch_goal_with_actions(node.goal_id)
        if parent_goal.status in ("AWAITING_APPROVAL", "READY"):
            validate_state_transition(
                "Goal",
                parent_goal.status,
                "EXECUTING",
                VALID_GOAL_STATES,
                VALID_GOAL_TRANSITIONS,
                is_authoritative_engine=True,
            )
            parent_goal.status = "EXECUTING"

        if node.status != "EXECUTING":
            validate_state_transition(
                "ActionNode",
                node.status,
                "EXECUTING",
                VALID_ACTION_STATES,
                VALID_ACTION_TRANSITIONS,
                is_authoritative_engine=True,
            )
            node.status = "EXECUTING"

        now = datetime.now(timezone.utc)
        inputs_data = dict(node.inputs_json or {})
        prev_lease = inputs_data.get("lease", {}) if isinstance(inputs_data.get("lease"), dict) else {}
        prev_epoch = prev_lease.get("epoch", 0) if isinstance(prev_lease, dict) else 0
        lease_epoch = prev_epoch + 1
        lease_token = str(uuid.uuid4())
        self.lease_epoch = lease_epoch
        self.lease_token = lease_token

        inputs_data["lease"] = {
            "worker_id": self.worker_id,
            "lease_token": lease_token,
            "epoch": lease_epoch,
            "claimed_at": now.isoformat(),
            "expires_at": (now + timedelta(seconds=self.lease_duration_seconds)).isoformat(),
        }
        node.inputs_json = inputs_data
        await self.db.commit()

        # 6.5. Durably record pre-dispatch intent before crossing execution boundary
        provider_name = getattr(self.dispatcher, "provider_name", "offline-mock")
        record_pre_dispatch_intent(
            action=node,
            project_id=goal.project_id,
            worker_id=self.worker_id,
            lease_token=lease_token,
            lease_epoch=lease_epoch,
            provider_id=provider_name,
        )
        await self.db.commit()

        # 7. Execute via injected dispatcher (Strictly offline by default)
        if getattr(self.dispatcher, "is_live", False):
            is_local = getattr(self.dispatcher, "local_only", False)
            verify_live_execution_gate(self.settings, is_local_only=is_local)

        heartbeat_task = None
        hb_interval = getattr(self.settings, "lease_heartbeat_interval_seconds", 30) if self.settings else 30
        if hb_interval > 0:
            heartbeat_task = asyncio.create_task(
                self._run_heartbeat_loop(action_id, lease_token, lease_epoch, hb_interval)
            )

        current_task = asyncio.current_task()
        if current_task:
            active_task_registry.register(current_task, goal_id=goal.id, action_id=action_id)

        try:
            try:
                exec_result = await self.dispatcher.dispatch(node)
            except asyncio.CancelledError:
                logger.info(
                    "action_dispatch_task_cancelled",
                    action_id=str(action_id),
                    client_action_id=node.client_action_id,
                )
                raise
            except Exception as exc:
                clean_exc = sanitize_text(str(exc))
                logger.error(
                    "action_dispatcher_unhandled_exception",
                    action_id=str(action_id),
                    client_action_id=node.client_action_id,
                    error=clean_exc,
                )
                stmt = (
                    select(AutonomousActionNode)
                    .where(AutonomousActionNode.id == action_id)
                    .with_for_update()
                )
                res = await self.db.execute(stmt)
                node_locked = res.scalar_one_or_none()
                if node_locked:
                    curr_lease = (node_locked.inputs_json or {}).get("lease", {})
                    if (
                        curr_lease.get("lease_token") == lease_token
                        and curr_lease.get("epoch") == lease_epoch
                        and curr_lease.get("worker_id") == self.worker_id
                    ):
                        validate_state_transition(
                            "ActionNode",
                            node_locked.status,
                            "UNKNOWN_PENDING_RECONCILIATION",
                            VALID_ACTION_STATES,
                            VALID_ACTION_TRANSITIONS,
                            is_authoritative_engine=True,
                        )
                        node_locked.status = "UNKNOWN_PENDING_RECONCILIATION"
                        node_locked.error = sanitize_text(f"Dispatcher exception: {exc.__class__.__name__}: {clean_exc}")
                        intent_inputs = dict(node_locked.inputs_json or {})
                        if "dispatch_intent" in intent_inputs and isinstance(intent_inputs["dispatch_intent"], dict):
                            intent_inputs["dispatch_intent"]["status"] = "UNKNOWN_DISPATCH_ERROR"
                            intent_inputs["dispatch_intent"]["last_error"] = node_locked.error
                            node_locked.inputs_json = intent_inputs
                        parent_goal = await self.db.get(AutonomousGoal, node_locked.goal_id, with_for_update=True)
                        if parent_goal and parent_goal.status != "RECOVERY_REQUIRED":
                            parent_goal.status = "RECOVERY_REQUIRED"
                            parent_goal.failure_reason = sanitize_text(
                                f"Execution halted: action '{node_locked.client_action_id}' encountered unexpected dispatcher exception: {clean_exc}"
                            )
                        await self.db.commit()

                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail=sanitize_text(f"Dispatcher execution failed with unknown outcome: {clean_exc}"),
                )
        finally:
            if heartbeat_task and not heartbeat_task.done():
                heartbeat_task.cancel()
                try:
                    await heartbeat_task
                except asyncio.CancelledError:
                    pass
            active_task_registry.unregister(goal_id=goal.id, action_id=action_id)

        # 8. Re-lock row and verify worker lease fencing token before persisting result
        stmt = (
            select(AutonomousActionNode)
            .where(AutonomousActionNode.id == action_id)
            .execution_options(populate_existing=True)
            .with_for_update()
        )
        res = await self.db.execute(stmt)
        node = res.scalar_one()
        await self.db.refresh(node)

        if node.status != "EXECUTING":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    f"Action '{node.client_action_id}' is no longer in 'EXECUTING' status (current: '{node.status}'). "
                    "Execution result rejected to prevent stale overwrite."
                ),
            )

        curr_lease = (node.inputs_json or {}).get("lease", {})
        if not isinstance(curr_lease, dict):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Action '{node.client_action_id}' lacks valid persisted lease data. Execution result rejected.",
            )

        if (
            curr_lease.get("worker_id") != self.worker_id
            or curr_lease.get("lease_token") != lease_token
            or curr_lease.get("epoch") != lease_epoch
        ):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    f"Stale worker lease fencing token mismatch for action '{node.client_action_id}'. "
                    f"Expected worker={self.worker_id} token={lease_token} epoch={lease_epoch}, "
                    f"but found worker={curr_lease.get('worker_id')} token={curr_lease.get('lease_token')} epoch={curr_lease.get('epoch')}. "
                    "Execution result rejected to prevent split-brain overwrite."
                ),
            )

        expires_at_str = curr_lease.get("expires_at")
        if not expires_at_str:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Worker lease for action '{node.client_action_id}' is missing expiration timestamp. Execution result rejected.",
            )

        try:
            expires_at = datetime.fromisoformat(str(expires_at_str))
            if expires_at.tzinfo is None:
                expires_at = expires_at.replace(tzinfo=timezone.utc)
            if datetime.now(timezone.utc) > expires_at:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=(
                        f"Worker lease expired for action '{node.client_action_id}' at {expires_at_str}. "
                        "Execution result rejected to prevent stale overwrite."
                    ),
                )
        except (ValueError, TypeError):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Worker lease for action '{node.client_action_id}' contains invalid or unparseable expiration timestamp '{expires_at_str}'. Execution result rejected.",
            )

        clean_output = sanitize_payload(exec_result.output)
        clean_error = sanitize_text(exec_result.error) if exec_result.error else None

        if exec_result.status == "SUCCEEDED":
            val_ok, val_err = validate_action_outputs(node.action_type, clean_output)
            if not val_ok:
                validate_state_transition(
                    "ActionNode",
                    node.status,
                    "FAILED",
                    VALID_ACTION_STATES,
                    VALID_ACTION_TRANSITIONS,
                    is_authoritative_engine=True,
                )
                node.status = "FAILED"
                node.outputs_json = clean_output
                node.error = sanitize_text(f"Output validation failed: {val_err}")
            else:
                # Defense-in-depth: Validate real artifact files on disk for non-simulated executions
                art_ok = True
                art_err = None
                if (
                    not clean_output.get("is_simulated", False)
                    and not clean_output.get("mock_mode", False)
                    and not clean_output.get("skip_artifact_validation", False)
                ):
                    from app.services.artifact_validator import validate_artifact_file

                    cap_type = (node.required_capability or "").strip().upper()
                    exp_type = "image" if cap_type == "IMAGE_GENERATION" else ("video" if cap_type == "VIDEO_GENERATION" else "any")

                    reported_artifacts = list(clean_output.get("artifacts") or [])
                    if not reported_artifacts:
                        for single_k in ("artifact_url", "image_url", "video_url"):
                            v = clean_output.get(single_k)
                            if v and isinstance(v, str) and not v.startswith("http"):
                                reported_artifacts.append(v)
                                break

                    allowed_d = getattr(self.dispatcher, "output_dir", None)
                    for art_path_candidate in reported_artifacts:
                        if not str(art_path_candidate).startswith("http"):
                            res = validate_artifact_file(
                                art_path_candidate,
                                expected_type=exp_type,
                                allowed_dir=allowed_d,
                                strict_extension=True,
                            )
                            if not res.is_valid and res.extension_mismatch:
                                from app.services.artifact_validator import normalize_artifact_file
                                norm_res = normalize_artifact_file(
                                    art_path_candidate,
                                    expected_type=exp_type,
                                    allowed_dir=allowed_d,
                                    alias_legacy=True,
                                )
                                if norm_res.success and norm_res.validation_result and norm_res.validation_result.is_valid:
                                    res = norm_res.validation_result

                            if not res.is_valid:
                                art_ok = False
                                art_err = sanitize_text(f"Artifact file validation failed for '{art_path_candidate}': {res.error}")
                                break

                if not art_ok:
                    validate_state_transition(
                        "ActionNode",
                        node.status,
                        "FAILED",
                        VALID_ACTION_STATES,
                        VALID_ACTION_TRANSITIONS,
                        is_authoritative_engine=True,
                    )
                    node.status = "FAILED"
                    node.outputs_json = clean_output
                    node.error = art_err
                else:
                    validate_state_transition(
                        "ActionNode",
                        node.status,
                        "SUCCEEDED",
                        VALID_ACTION_STATES,
                        VALID_ACTION_TRANSITIONS,
                        is_authoritative_engine=True,
                    )
                    node.status = "SUCCEEDED"
                    node.outputs_json = clean_output
                    actual_cost = float(exec_result.cost_usd) if (exec_result.cost_usd is not None and exec_result.cost_usd > 0) else self.calculate_authoritative_action_cost(node)
                    node.cost_usd = actual_cost
                    node.duration_seconds = exec_result.duration_seconds
                    node.error = None

                    # SEC-FINDING-01: Update budget reservation consumed_amount_usd
                    if actual_cost > 0:
                        parent_goal_for_res = await self.db.get(AutonomousGoal, node.goal_id)
                        if parent_goal_for_res:
                            stmt_res = select(BudgetReservation).where(
                                BudgetReservation.goal_id == parent_goal_for_res.id,
                                BudgetReservation.plan_version == parent_goal_for_res.current_plan_version,
                            ).with_for_update()
                            res_r = await self.db.execute(stmt_res)
                            reservation = res_r.scalar_one_or_none()
                            if reservation:
                                new_consumed = round(float(reservation.consumed_amount_usd) + actual_cost, 4)
                                reservation.consumed_amount_usd = new_consumed
                                if new_consumed >= float(reservation.reserved_amount_usd):
                                    reservation.status = "CONSUMED"
                                reservation.updated_at = datetime.now(timezone.utc)
        elif exec_result.status == "FAILED":
            validate_state_transition(
                "ActionNode",
                node.status,
                "FAILED",
                VALID_ACTION_STATES,
                VALID_ACTION_TRANSITIONS,
                is_authoritative_engine=True,
            )
            node.status = "FAILED"
            node.outputs_json = clean_output
            node.error = clean_error or "Action execution failed"
        elif exec_result.status == "UNKNOWN_PENDING_RECONCILIATION":
            validate_state_transition(
                "ActionNode",
                node.status,
                "UNKNOWN_PENDING_RECONCILIATION",
                VALID_ACTION_STATES,
                VALID_ACTION_TRANSITIONS,
                is_authoritative_engine=True,
            )
            node.status = "UNKNOWN_PENDING_RECONCILIATION"
            node.outputs_json = clean_output
            node.error = clean_error or "External outcome unknown; pending reconciliation"
            parent_goal = await self.db.get(AutonomousGoal, node.goal_id, with_for_update=True)
            if parent_goal and parent_goal.status != "RECOVERY_REQUIRED":
                parent_goal.status = "RECOVERY_REQUIRED"
                parent_goal.failure_reason = sanitize_text(
                    f"Execution halted: action '{node.client_action_id}' outcome is unknown: {node.error}"
                )
        else:
            # Fallback fail-closed
            node.status = "FAILED"
            node.outputs_json = clean_output
            node.error = sanitize_text(f"Unrecognized execution result status: {exec_result.status}")

        intent_inputs = json.loads(json.dumps(node.inputs_json or {}))
        if "dispatch_intent" in intent_inputs and isinstance(intent_inputs["dispatch_intent"], dict):
            intent_inputs["dispatch_intent"]["status"] = node.status
            job_id = getattr(exec_result, "provider_job_id", None)
            if job_id:
                intent_inputs["dispatch_intent"]["provider_job_id"] = job_id
            node.inputs_json = intent_inputs
            flag_modified(node, "inputs_json")

        await self.db.commit()

        # 9. Cascade DAG readiness update for downstream nodes
        await self.apply_dag_readiness_updates(node.goal_id, principal)

        # Check if parent goal is completed
        parent_goal = await self._fetch_goal_with_actions(node.goal_id)
        if all(a.status == "SUCCEEDED" for a in parent_goal.actions) and parent_goal.actions:
            if parent_goal.status != "COMPLETED":
                validate_state_transition(
                    "Goal",
                    parent_goal.status,
                    "COMPLETED",
                    VALID_GOAL_STATES,
                    VALID_GOAL_TRANSITIONS,
                    is_authoritative_engine=True,
                )
                parent_goal.status = "COMPLETED"
                parent_goal.final_summary = derive_goal_completion_summary(parent_goal.actions)

                # SEC-FINDING-01: Release residual unconsumed reservation upon completion
                stmt_res = select(BudgetReservation).where(
                    BudgetReservation.goal_id == parent_goal.id,
                    BudgetReservation.plan_version == parent_goal.current_plan_version,
                ).with_for_update()
                res_r = await self.db.execute(stmt_res)
                reservation = res_r.scalar_one_or_none()
                if reservation and reservation.status == "RESERVED":
                    reservation.status = "RELEASED"
                    reservation.updated_at = datetime.now(timezone.utc)

                await self.db.commit()

        await self.db.refresh(node)
        return node

    async def execute_goal_step(
        self,
        goal_id: uuid.UUID,
        principal: AuthenticatedPrincipal,
        max_concurrent: int = 2,
    ) -> AutonomousGoal:
        """Executes one step of offline DAG progression for an autonomous goal."""
        goal = await self._fetch_goal_with_actions(goal_id)
        if not goal:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Goal not found"
            )

        if not principal.is_admin:
            allowed = await get_authorized_project_ids(self.db, principal)
            if allowed is None or goal.project_id not in allowed:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND, detail="Goal not found"
                )

        # Terminal goals cannot be re-executed
        if goal.status in ("COMPLETED", "CANCELLED"):
            return goal

        # Initialize DRAFT / PLANNING goals: DRAFT -> READY -> EXECUTING
        if goal.status in ("DRAFT", "PLANNING"):
            action_cids = [a.client_action_id for a in goal.actions]
            validate_plan_dag(goal.plan_dag_json or {}, action_client_ids=action_cids)
            validate_state_transition(
                "Goal",
                goal.status,
                "READY",
                VALID_GOAL_STATES,
                VALID_GOAL_TRANSITIONS,
                is_authoritative_engine=True,
            )
            goal.status = "READY"
            await self.db.commit()

        if goal.status == "READY":
            validate_state_transition(
                "Goal",
                goal.status,
                "EXECUTING",
                VALID_GOAL_STATES,
                VALID_GOAL_TRANSITIONS,
                is_authoritative_engine=True,
            )
            goal.status = "EXECUTING"
            await self.db.commit()

        # Apply readiness updates across DAG
        await self.apply_dag_readiness_updates(goal_id, principal)

        # Refresh actions
        goal = await self._fetch_goal_with_actions(goal_id)

        # Find READY actions
        ready_actions = [a for a in goal.actions if a.status == "READY"]

        if not ready_actions:
            # Check if awaiting approval
            awaiting = [a for a in goal.actions if a.status == "AWAITING_APPROVAL"]
            if awaiting:
                if goal.status != "AWAITING_APPROVAL":
                    validate_state_transition(
                        "Goal",
                        goal.status,
                        "AWAITING_APPROVAL",
                        VALID_GOAL_STATES,
                        VALID_GOAL_TRANSITIONS,
                        is_authoritative_engine=True,
                    )
                    goal.status = "AWAITING_APPROVAL"
                    await self.db.commit()
                return await self._fetch_goal_with_actions(goal_id)

            # Check if all completed
            all_succeeded = all(a.status == "SUCCEEDED" for a in goal.actions)
            if all_succeeded and goal.actions:
                if goal.status != "COMPLETED":
                    validate_state_transition(
                        "Goal",
                        goal.status,
                        "COMPLETED",
                        VALID_GOAL_STATES,
                        VALID_GOAL_TRANSITIONS,
                        is_authoritative_engine=True,
                    )
                    goal.status = "COMPLETED"
                    goal.final_summary = derive_goal_completion_summary(goal.actions)

                    # SEC-FINDING-01: Release residual unconsumed reservation upon completion
                    stmt_res = select(BudgetReservation).where(
                        BudgetReservation.goal_id == goal.id,
                        BudgetReservation.plan_version == goal.current_plan_version,
                    ).with_for_update()
                    res_r = await self.db.execute(stmt_res)
                    reservation = res_r.scalar_one_or_none()
                    if reservation and reservation.status == "RESERVED":
                        reservation.status = "RELEASED"
                        reservation.updated_at = datetime.now(timezone.utc)

                    await self.db.commit()
                return await self._fetch_goal_with_actions(goal_id)

            # Check if unknown / recovery required
            has_unknown = any(
                a.status in ("UNKNOWN_PENDING_RECONCILIATION", "RECOVERY_REQUIRED")
                for a in goal.actions
            )
            if has_unknown:
                if goal.status != "RECOVERY_REQUIRED":
                    validate_state_transition(
                        "Goal",
                        goal.status,
                        "RECOVERY_REQUIRED",
                        VALID_GOAL_STATES,
                        VALID_GOAL_TRANSITIONS,
                        is_authoritative_engine=True,
                    )
                    goal.status = "RECOVERY_REQUIRED"
                    goal.failure_reason = "Execution halted: action outcome is ambiguous and requires governed recovery."
                    await self.db.commit()
                return await self._fetch_goal_with_actions(goal_id)

            # Check if blocked or failed
            has_failed = any(a.status == "FAILED" for a in goal.actions)
            has_blocked = any(a.status == "BLOCKED" for a in goal.actions)
            if has_failed or has_blocked:
                target_state = "FAILED" if has_failed else "BLOCKED"
                if goal.status != target_state:
                    validate_state_transition(
                        "Goal",
                        goal.status,
                        target_state,
                        VALID_GOAL_STATES,
                        VALID_GOAL_TRANSITIONS,
                        is_authoritative_engine=True,
                    )
                    goal.status = target_state
                    goal.failure_reason = (
                        "Execution halted: one or more action nodes failed or were blocked."
                    )

                    # SEC-FINDING-01: If target_state == "FAILED" and no action is UNKNOWN, release residual
                    if target_state == "FAILED":
                        has_unknown = any(
                            a.status in ("UNKNOWN_PENDING_RECONCILIATION", "RECOVERY_REQUIRED")
                            for a in goal.actions
                        )
                        if not has_unknown:
                            stmt_res = select(BudgetReservation).where(
                                BudgetReservation.goal_id == goal.id,
                                BudgetReservation.plan_version == goal.current_plan_version,
                            ).with_for_update()
                            res_r = await self.db.execute(stmt_res)
                            reservation = res_r.scalar_one_or_none()
                            if reservation and reservation.status == "RESERVED":
                                reservation.status = "RELEASED"
                                reservation.updated_at = datetime.now(timezone.utc)

                    await self.db.commit()
                return await self._fetch_goal_with_actions(goal_id)

            return await self._fetch_goal_with_actions(goal_id)

        # Dispatch ready actions up to max_concurrent limit
        # GAP-01 & SEC-FINDING-01: Aggregate Multi-Shot Budget Reservation before first shot dispatch
        has_started = any(a.status in ("EXECUTING", "SUCCEEDED") for a in goal.actions)
        if not has_started and ready_actions:
            try:
                await self.reserve_aggregate_dag_budget(goal)
            except (AggregateBudgetPreflightError, HTTPException) as b_err:
                detail_str = getattr(b_err, "detail", str(b_err))
                if goal.status != "BLOCKED":
                    validate_state_transition(
                        "Goal",
                        goal.status,
                        "BLOCKED",
                        VALID_GOAL_STATES,
                        VALID_GOAL_TRANSITIONS,
                        is_authoritative_engine=True,
                    )
                    goal.status = "BLOCKED"
                    goal.failure_reason = detail_str
                    await self.db.commit()
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=detail_str,
                )

        to_dispatch = ready_actions[:max_concurrent]
        for act in to_dispatch:
            await self.dispatch_action(act.id, principal)

        # Re-apply readiness updates and check completion
        await self.apply_dag_readiness_updates(goal_id, principal)

        goal = await self._fetch_goal_with_actions(goal_id)

        if all(a.status == "SUCCEEDED" for a in goal.actions) and goal.actions:
            if goal.status != "COMPLETED":
                validate_state_transition(
                    "Goal",
                    goal.status,
                    "COMPLETED",
                    VALID_GOAL_STATES,
                    VALID_GOAL_TRANSITIONS,
                    is_authoritative_engine=True,
                )
                goal.status = "COMPLETED"
                goal.final_summary = derive_goal_completion_summary(goal.actions)

                # SEC-FINDING-01: Release residual unconsumed reservation upon completion
                stmt_res = select(BudgetReservation).where(
                    BudgetReservation.goal_id == goal.id,
                    BudgetReservation.plan_version == goal.current_plan_version,
                ).with_for_update()
                res_r = await self.db.execute(stmt_res)
                reservation = res_r.scalar_one_or_none()
                if reservation and reservation.status == "RESERVED":
                    reservation.status = "RELEASED"
                    reservation.updated_at = datetime.now(timezone.utc)

                await self.db.commit()
                goal = await self._fetch_goal_with_actions(goal_id)
        elif any(a.status == "FAILED" for a in goal.actions):
            if goal.status != "FAILED":
                validate_state_transition(
                    "Goal",
                    goal.status,
                    "FAILED",
                    VALID_GOAL_STATES,
                    VALID_GOAL_TRANSITIONS,
                    is_authoritative_engine=True,
                )
                goal.status = "FAILED"
                goal.failure_reason = "Execution halted: one or more action nodes failed."

                has_unknown = any(
                    a.status in ("UNKNOWN_PENDING_RECONCILIATION", "RECOVERY_REQUIRED")
                    for a in goal.actions
                )
                if not has_unknown:
                    stmt_res = select(BudgetReservation).where(
                        BudgetReservation.goal_id == goal.id,
                        BudgetReservation.plan_version == goal.current_plan_version,
                    ).with_for_update()
                    res_r = await self.db.execute(stmt_res)
                    reservation = res_r.scalar_one_or_none()
                    if reservation and reservation.status == "RESERVED":
                        reservation.status = "RELEASED"
                        reservation.updated_at = datetime.now(timezone.utc)

                await self.db.commit()
                goal = await self._fetch_goal_with_actions(goal_id)
        elif any(a.status in ("UNKNOWN_PENDING_RECONCILIATION", "RECOVERY_REQUIRED") for a in goal.actions):
            if goal.status != "RECOVERY_REQUIRED":
                validate_state_transition(
                    "Goal",
                    goal.status,
                    "RECOVERY_REQUIRED",
                    VALID_GOAL_STATES,
                    VALID_GOAL_TRANSITIONS,
                    is_authoritative_engine=True,
                )
                goal.status = "RECOVERY_REQUIRED"
                goal.failure_reason = "Execution halted: action outcome is ambiguous and requires governed recovery."
                await self.db.commit()
                goal = await self._fetch_goal_with_actions(goal_id)

        return goal

    async def cancel_goal(
        self,
        goal_id: uuid.UUID,
        principal: AuthenticatedPrincipal,
    ) -> AutonomousGoal:
        """Cancels an autonomous goal, all non-terminal action nodes, terminates running processes,
        fences in-flight leases, and safeguards budget ledgers."""
        goal = await self._fetch_goal_with_actions(goal_id)
        if not goal:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Goal not found")

        if not principal.is_admin:
            allowed = await get_authorized_project_ids(self.db, principal)
            if allowed is None or goal.project_id not in allowed:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Goal not found")

        # Idempotency: if already CANCELLED, return cleanly without duplicate side effects
        if goal.status == "CANCELLED":
            return goal

        # Terminal completed goals cannot be cancelled
        if goal.status == "COMPLETED":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Cannot cancel a goal that is already COMPLETED",
            )

        validate_state_transition(
            "Goal",
            goal.status,
            "CANCELLED",
            VALID_GOAL_STATES,
            VALID_GOAL_TRANSITIONS,
            is_authoritative_engine=True,
        )
        goal.status = "CANCELLED"
        goal.failure_reason = "Goal cancelled by operator"

        # Signal cooperative cancellation to any active runner tasks for this goal
        active_task_registry.cancel_goal(goal_id)

        # Boundedly terminate any active subprocesses running for this goal
        await subprocess_registry.terminate_for_goal(goal_id, grace_period_seconds=3.0)

        # Lock and cascade across all action nodes of the goal
        stmt_actions = (
            select(AutonomousActionNode)
            .where(AutonomousActionNode.goal_id == goal.id)
            .execution_options(populate_existing=True)
            .with_for_update()
        )
        res_actions = await self.db.execute(stmt_actions)
        actions = list(res_actions.scalars().all())

        now = datetime.now(timezone.utc)
        for act in actions:
            if act.status in ("SUCCEEDED", "CANCELLED"):
                # Retain terminal truth
                continue
            elif act.status in ("PENDING", "READY", "BLOCKED", "AWAITING_APPROVAL"):
                validate_state_transition(
                    "ActionNode",
                    act.status,
                    "CANCELLED",
                    VALID_ACTION_STATES,
                    VALID_ACTION_TRANSITIONS,
                    is_authoritative_engine=True,
                )
                act.status = "CANCELLED"
                act.error = "Cancelled due to goal cancellation"
            elif act.status == "EXECUTING":
                # Invalidate lease fencing token and increment epoch
                inputs_data = dict(act.inputs_json or {})
                lease_dict = dict(inputs_data.get("lease", {})) if isinstance(inputs_data.get("lease"), dict) else {}
                prev_epoch = lease_dict.get("epoch", 0)
                lease_dict["lease_token"] = str(uuid.uuid4())
                lease_dict["epoch"] = prev_epoch + 1
                lease_dict["cancelled_at"] = now.isoformat()
                inputs_data["lease"] = lease_dict
                act.inputs_json = inputs_data

                if is_external_dispatch_committed(act):
                    validate_state_transition(
                        "ActionNode",
                        act.status,
                        "UNKNOWN_PENDING_RECONCILIATION",
                        VALID_ACTION_STATES,
                        VALID_ACTION_TRANSITIONS,
                        is_authoritative_engine=True,
                    )
                    act.status = "UNKNOWN_PENDING_RECONCILIATION"
                    act.error = "Action was in-flight with external dispatch committed when cancelled; pending reconciliation."
                else:
                    validate_state_transition(
                        "ActionNode",
                        act.status,
                        "CANCELLED",
                        VALID_ACTION_STATES,
                        VALID_ACTION_TRANSITIONS,
                        is_authoritative_engine=True,
                    )
                    act.status = "CANCELLED"
                    act.error = "Action cancelled while executing."

        # Budget reservation handling:
        # Check if any action remains in UNKNOWN_PENDING_RECONCILIATION or RECOVERY_REQUIRED
        has_unknown = any(
            a.status in ("UNKNOWN_PENDING_RECONCILIATION", "RECOVERY_REQUIRED")
            for a in actions
        )

        stmt_res = select(BudgetReservation).where(
            BudgetReservation.goal_id == goal.id,
            BudgetReservation.plan_version == goal.current_plan_version,
        ).with_for_update()
        res_r = await self.db.execute(stmt_res)
        reservation = res_r.scalar_one_or_none()

        if reservation:
            # Realize any confirmed spend from SUCCEEDED actions
            realized_spend = 0.0
            for a in actions:
                if a.status == "SUCCEEDED":
                    out = a.outputs_json or {}
                    c = float(out.get("cost_usd", 0.0) or 0.0)
                    realized_spend += c
            if realized_spend > float(reservation.consumed_amount_usd):
                reservation.consumed_amount_usd = round(realized_spend, 4)

            if not has_unknown:
                if reservation.status == "RESERVED":
                    reservation.status = "RELEASED"
                    reservation.updated_at = now
            # If has_unknown is True, do NOT release reservation; keep RESERVED

        await self.db.commit()
        return await self._fetch_goal_with_actions(goal_id)

    async def cancel_action(
        self,
        action_id: uuid.UUID,
        principal: AuthenticatedPrincipal,
    ) -> AutonomousActionNode:
        """Authoritatively cancels an action node, terminates processes, and cascades DAG readiness."""
        stmt = (
            select(AutonomousActionNode)
            .where(AutonomousActionNode.id == action_id)
            .execution_options(populate_existing=True)
            .with_for_update()
        )
        res = await self.db.execute(stmt)
        node = res.scalar_one_or_none()
        if not node:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Action node not found")

        goal = await self._fetch_goal_with_actions(node.goal_id)
        if not goal:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Parent goal not found")

        if not principal.is_admin:
            allowed = await get_authorized_project_ids(self.db, principal)
            if allowed is None or goal.project_id not in allowed:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Action node not found")

        if node.status == "CANCELLED":
            return node

        if node.status == "SUCCEEDED":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Cannot cancel action '{node.client_action_id}' because it has already SUCCEEDED.",
            )

        now = datetime.now(timezone.utc)
        if node.status in ("PENDING", "READY", "BLOCKED", "AWAITING_APPROVAL"):
            validate_state_transition(
                "ActionNode",
                node.status,
                "CANCELLED",
                VALID_ACTION_STATES,
                VALID_ACTION_TRANSITIONS,
                is_authoritative_engine=True,
            )
            node.status = "CANCELLED"
            node.error = "Action cancelled by operator."

        elif node.status == "EXECUTING":
            # 1. Signal task cancellation
            active_task_registry.cancel_task(goal.id, node.id)
            # 2. Terminate local subprocesses
            await subprocess_registry.terminate_for_action(node.id, grace_period_seconds=3.0)
            # 3. Rotate fencing token
            inputs_data = dict(node.inputs_json or {})
            lease_dict = dict(inputs_data.get("lease", {})) if isinstance(inputs_data.get("lease"), dict) else {}
            prev_epoch = lease_dict.get("epoch", 0)
            lease_dict["lease_token"] = str(uuid.uuid4())
            lease_dict["epoch"] = prev_epoch + 1
            lease_dict["cancelled_at"] = now.isoformat()
            inputs_data["lease"] = lease_dict
            node.inputs_json = inputs_data

            # 4. Check external committed dispatch
            if is_external_dispatch_committed(node):
                validate_state_transition(
                    "ActionNode",
                    node.status,
                    "UNKNOWN_PENDING_RECONCILIATION",
                    VALID_ACTION_STATES,
                    VALID_ACTION_TRANSITIONS,
                    is_authoritative_engine=True,
                )
                node.status = "UNKNOWN_PENDING_RECONCILIATION"
                node.error = "Action was in-flight with external dispatch committed when cancelled; pending reconciliation."
            else:
                validate_state_transition(
                    "ActionNode",
                    node.status,
                    "CANCELLED",
                    VALID_ACTION_STATES,
                    VALID_ACTION_TRANSITIONS,
                    is_authoritative_engine=True,
                )
                node.status = "CANCELLED"
                node.error = "Action cancelled by operator while executing."

        await self.db.commit()

        # Cascade DAG readiness to downstream nodes
        await self.apply_dag_readiness_updates(goal.id, principal)

        # Budget reservation check if no more actions are active or ambiguous
        refreshed_goal = await self._fetch_goal_with_actions(goal.id)
        has_unknown = any(
            a.status in ("UNKNOWN_PENDING_RECONCILIATION", "RECOVERY_REQUIRED")
            for a in refreshed_goal.actions
        )
        has_active = any(
            a.status in ("PENDING", "READY", "EXECUTING", "AWAITING_APPROVAL")
            for a in refreshed_goal.actions
        )
        if not has_active and not has_unknown:
            stmt_res = select(BudgetReservation).where(
                BudgetReservation.goal_id == goal.id,
                BudgetReservation.plan_version == goal.current_plan_version,
            ).with_for_update()
            res_r = await self.db.execute(stmt_res)
            reservation = res_r.scalar_one_or_none()
            if reservation and reservation.status == "RESERVED":
                reservation.status = "RELEASED"
                reservation.updated_at = now
                await self.db.commit()

        await self.db.refresh(node)
        return node

    async def reconcile_action(
        self,
        action_id: uuid.UUID,
        principal: AuthenticatedPrincipal,
        force_unverified_retry: bool = False,
    ) -> tuple[AutonomousActionNode, ReconciliationReport]:
        """Authoritatively reconciles an action node with an ambiguous outcome or expired lease.

        Enforces:
        - Atomic row locking
        - Project authorization & IDOR masking
        - Live approver credential and project membership verification
        - Output validation before marking SUCCEEDED
        - Governed state transitions
        - DAG readiness updates cascading to dependent nodes
        - Goal recovery when ambiguous states are resolved
        """
        reconciliation_service = ActionReconciliationService(
            db=self.db,
            dispatcher=self.dispatcher,
            settings=self.settings,
        )
        node, report = await reconciliation_service.reconcile(
            action_id=action_id,
            principal=principal,
            force_unverified_retry=force_unverified_retry,
        )

        # Apply DAG readiness updates across the goal to cascade changes (e.g. unblock nodes if succeeded)
        await self.apply_dag_readiness_updates(node.goal_id, principal)

        # Refresh parent goal
        parent_goal = await self._fetch_goal_with_actions(node.goal_id)

        # If goal was RECOVERY_REQUIRED and no actions are ambiguous, blocked, or failed, recover to READY
        if parent_goal.status == "RECOVERY_REQUIRED":
            has_unknown_or_recovery = any(
                a.status in ("UNKNOWN_PENDING_RECONCILIATION", "RECOVERY_REQUIRED")
                for a in parent_goal.actions
            )
            has_blocked_or_failed = any(
                a.status in ("BLOCKED", "FAILED")
                for a in parent_goal.actions
            )
            if not has_unknown_or_recovery and not has_blocked_or_failed:
                validate_state_transition(
                    "Goal",
                    parent_goal.status,
                    "READY",
                    VALID_GOAL_STATES,
                    VALID_GOAL_TRANSITIONS,
                    is_authoritative_engine=True,
                )
                parent_goal.status = "READY"
                parent_goal.failure_reason = None
                await self.db.commit()

        # If all actions succeeded, advance goal to COMPLETED
        parent_goal = await self._fetch_goal_with_actions(node.goal_id)
        if all(a.status == "SUCCEEDED" for a in parent_goal.actions) and parent_goal.actions:
            if parent_goal.status != "COMPLETED":
                if parent_goal.status == "READY":
                    validate_state_transition(
                        "Goal",
                        parent_goal.status,
                        "EXECUTING",
                        VALID_GOAL_STATES,
                        VALID_GOAL_TRANSITIONS,
                        is_authoritative_engine=True,
                    )
                    parent_goal.status = "EXECUTING"
                validate_state_transition(
                    "Goal",
                    parent_goal.status,
                    "COMPLETED",
                    VALID_GOAL_STATES,
                    VALID_GOAL_TRANSITIONS,
                    is_authoritative_engine=True,
                )
                parent_goal.status = "COMPLETED"
                parent_goal.final_summary = (
                    f"Goal completed successfully across {len(parent_goal.actions)} action nodes (reconciled)."
                )
                await self.db.commit()

        await self.db.refresh(node)
        return node, report
