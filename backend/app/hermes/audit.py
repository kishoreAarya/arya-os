"""
AryaOS-owned persistent audit — §13 (V2).

Spec: docs/architecture/HERMES_INTEGRATION_SPEC.md — §13 ("AryaOS records,
for every Hermes job and every tool request ... decision (ALLOW/BLOCK) and
policy reason code; parameter digest (full parameters in the audit store;
digests in logs — never log secrets or raw credentials) ... Blocked/denied
requests are first-class audit events, not noise").

This module implements the persistent authorization-decision audit record slice:
1. Deterministic SHA-256 parameter digest computation (safe for logging & correlation).
2. Immutable AuthorizationDecisionAuditRecord capturing the policy decision.
3. Thread-safe AuditSink protocol with InMemoryAuditSink (testing/inspection)
   and FileAuditSink (persistent append-only JSON Lines).
4. Active audit-sink binding managed alongside AuthorizationContext during job execution.
5. Structured logging via structlog that NEVER logs parameter values or secrets.
6. Additive final-outcome records (§13.1): a request that passed §4 but was
   finally rejected by the §9 schema-validation layer or the §12 limit layer
   gets its own BLOCK record with the rejecting layer's deterministic reason
   code; the §4 record is never rewritten. Audit remains authorization-
   preserving and best-effort: recording failures never alter any decision.
7. Job-boundary records (§13): one JOB_START and one JOB_END record per job
   carrying the job identity block, verified Hermes commit/tree pin, the
   SHA-256 of the generated config.yaml (never its contents), the actual
   plugin-verification result, §12 ledger snapshots before/after, wall-clock
   duration, and the final job outcome. Job-boundary lines share the
   persistent audit store and are discriminated by record_type; per-request
   readers are unaffected. Still best-effort and secret-free.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import threading
from typing import Any, Protocol
import uuid

from app.core.logging import get_logger

logger = get_logger("arya.hermes.audit")


def compute_parameter_digest(parameters: Any) -> str:
    """Compute a deterministic SHA-256 hex digest of tool parameters.

    Used for logs, lineage, and audit correlation — never logs raw parameter values.
    Empty or None parameters map to sha256("{}"). Key ordering is normalized.
    """
    if parameters is None:
        return hashlib.sha256(b"{}").hexdigest()
    if isinstance(parameters, dict):
        try:
            serialized = json.dumps(parameters, sort_keys=True, default=str)
            return hashlib.sha256(serialized.encode("utf-8")).hexdigest()
        except Exception:
            pass
    return hashlib.sha256(repr(parameters).encode("utf-8", errors="replace")).hexdigest()


@dataclass(frozen=True)
class AuthorizationDecisionAuditRecord:
    """One immutable record of an authorization decision at the §4 policy boundary (§13).

    `audit_id` — unique identifier for this audit event.
    `occurred_at` — ISO-8601 UTC timestamp.
    `user_id`, `project_id`, `job_id`, `agent_id`, `lineage_id` — identity context.
    `tool_name` — requested tool or capability name.
    `decision` — "ALLOW" or "BLOCK".
    `reason_code` — stable machine-readable reason code from PolicyDecision.
    `parameter_digest` — SHA-256 digest of parameters (never raw secrets in logs).
    `parameters` — full parameters preserved in the persistent audit record.
    """

    user_id: str
    project_id: str
    job_id: str
    agent_id: str
    lineage_id: str
    tool_name: str
    decision: str
    reason_code: str
    parameter_digest: str
    audit_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    occurred_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    parameters: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to a JSON-serializable dictionary."""
        return {
            "audit_id": self.audit_id,
            "occurred_at": self.occurred_at,
            "user_id": self.user_id,
            "project_id": self.project_id,
            "job_id": self.job_id,
            "agent_id": self.agent_id,
            "lineage_id": self.lineage_id,
            "tool_name": self.tool_name,
            "decision": self.decision,
            "reason_code": self.reason_code,
            "parameter_digest": self.parameter_digest,
            "parameters": self.parameters,
        }

    def to_json(self) -> str:
        """Serialize to a JSON string."""
        return json.dumps(self.to_dict(), default=str)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AuthorizationDecisionAuditRecord:
        """Reconstruct from dictionary."""
        return cls(
            audit_id=str(data.get("audit_id", "")),
            occurred_at=str(data.get("occurred_at", "")),
            user_id=str(data.get("user_id", "")),
            project_id=str(data.get("project_id", "")),
            job_id=str(data.get("job_id", "")),
            agent_id=str(data.get("agent_id", "")),
            lineage_id=str(data.get("lineage_id", "")),
            tool_name=str(data.get("tool_name", "")),
            decision=str(data.get("decision", "")),
            reason_code=str(data.get("reason_code", "")),
            parameter_digest=str(data.get("parameter_digest", "")),
            parameters=data.get("parameters") if isinstance(data.get("parameters"), dict) else None,
        )


class AuditSink(Protocol):
    """Protocol for persistent audit sinks."""

    def record(self, record: AuthorizationDecisionAuditRecord) -> None: ...


# ---------------------------------------------------------------------------
# Job-boundary records (§13)
# ---------------------------------------------------------------------------

# Line discriminator written into every job-boundary record; per-request
# records carry no record_type (they predate it), which is what keeps the
# two shapes distinguishable in the shared persistent audit store.
JOB_BOUNDARY_RECORD_TYPE = "job_boundary"
JOB_START = "JOB_START"
JOB_END = "JOB_END"


@dataclass(frozen=True)
class HermesJobAuditRecord:
    """One immutable job-boundary audit record (§13): JOB_START or JOB_END.

    `event` — "JOB_START" | "JOB_END".
    Identity — the job-bound AuthorizationContext fields, matching the
    per-request records, plus `runtime_job_id` (the AryaOS runtime job token
    that names the per-job Hermes home).
    `hermes_commit` / `hermes_tree` / `hermes_git_verified` — the identity
    returned by the runtime's source verification (§2/§14.1), never a new
    pin source.
    `config_sha256` — SHA-256 of the generated config.yaml text (a digest
    only; the config contents and every secret stay out of the audit store).
    `plugin_verification` — the ACTUAL runtime verification outcome:
    "pending" (start: not yet verified), "verified", "failed" (the runtime
    assertion raised), or "not_reached" (the job ended before verification).
    `limits_snapshot` — a JobLimitLedger.counts() snapshot (start: before
    execution; end: final state). Counters only — never policy input.
    `duration_seconds` / `outcome` / `error_code` / `violation_code` —
    wall-clock duration (monotonic delta) and the final runtime job result.
    """

    event: str
    user_id: str
    project_id: str
    job_id: str
    agent_id: str
    lineage_id: str
    runtime_job_id: str = ""
    occurred_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    audit_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    hermes_commit: str | None = None
    hermes_tree: str | None = None
    hermes_git_verified: bool | None = None
    config_sha256: str | None = None
    plugin_verification: str | None = None
    limits_snapshot: dict[str, Any] | None = None
    duration_seconds: float | None = None
    outcome: str | None = None
    error_code: str | None = None
    violation_code: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to a JSON-serializable dictionary."""
        return {
            "record_type": JOB_BOUNDARY_RECORD_TYPE,
            "event": self.event,
            "audit_id": self.audit_id,
            "occurred_at": self.occurred_at,
            "user_id": self.user_id,
            "project_id": self.project_id,
            "job_id": self.job_id,
            "agent_id": self.agent_id,
            "lineage_id": self.lineage_id,
            "runtime_job_id": self.runtime_job_id,
            "hermes_commit": self.hermes_commit,
            "hermes_tree": self.hermes_tree,
            "hermes_git_verified": self.hermes_git_verified,
            "config_sha256": self.config_sha256,
            "plugin_verification": self.plugin_verification,
            "limits_snapshot": dict(self.limits_snapshot) if self.limits_snapshot else None,
            "duration_seconds": self.duration_seconds,
            "outcome": self.outcome,
            "error_code": self.error_code,
            "violation_code": self.violation_code,
        }

    def to_json(self) -> str:
        """Serialize to a JSON string."""
        return json.dumps(self.to_dict(), default=str)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> HermesJobAuditRecord:
        """Reconstruct from dictionary."""
        snapshot = data.get("limits_snapshot")
        duration = data.get("duration_seconds")
        return cls(
            event=str(data.get("event", "")),
            user_id=str(data.get("user_id", "")),
            project_id=str(data.get("project_id", "")),
            job_id=str(data.get("job_id", "")),
            agent_id=str(data.get("agent_id", "")),
            lineage_id=str(data.get("lineage_id", "")),
            runtime_job_id=str(data.get("runtime_job_id", "")),
            occurred_at=str(data.get("occurred_at", "")),
            audit_id=str(data.get("audit_id", "")),
            hermes_commit=data.get("hermes_commit"),
            hermes_tree=data.get("hermes_tree"),
            hermes_git_verified=data.get("hermes_git_verified")
            if isinstance(data.get("hermes_git_verified"), bool)
            else None,
            config_sha256=data.get("config_sha256"),
            plugin_verification=data.get("plugin_verification"),
            limits_snapshot=dict(snapshot) if isinstance(snapshot, dict) else None,
            duration_seconds=float(duration) if isinstance(duration, (int, float)) else None,
            outcome=data.get("outcome"),
            error_code=data.get("error_code"),
            violation_code=data.get("violation_code"),
        )


class InMemoryAuditSink:
    """Thread-safe in-memory sink for testing, inspection, and verification."""

    def __init__(self) -> None:
        self._records: list[AuthorizationDecisionAuditRecord | HermesJobAuditRecord] = []
        self._lock = threading.Lock()

    def record(self, record: AuthorizationDecisionAuditRecord | HermesJobAuditRecord) -> None:
        with self._lock:
            self._records.append(record)

    def records(self) -> list[AuthorizationDecisionAuditRecord]:
        """All per-request records (job-boundary records excluded)."""
        with self._lock:
            return [r for r in self._records if isinstance(r, AuthorizationDecisionAuditRecord)]

    def job_records(self) -> list[HermesJobAuditRecord]:
        """The job-boundary records only."""
        with self._lock:
            return [r for r in self._records if isinstance(r, HermesJobAuditRecord)]

    def clear(self) -> None:
        with self._lock:
            self._records.clear()


class FileAuditSink:
    """Persistent append-only file sink writing JSON Lines.

    Thread-safe; creates parent directory on demand. The single audit store
    holds both record shapes, discriminated per line by ``record_type``
    (absent = per-request authorization record, §13 precedent).
    """

    def __init__(self, file_path: Path | str) -> None:
        self._file_path = Path(file_path)
        self._lock = threading.Lock()

    @property
    def file_path(self) -> Path:
        return self._file_path

    def record(self, record: AuthorizationDecisionAuditRecord | HermesJobAuditRecord) -> None:
        with self._lock:
            self._file_path.parent.mkdir(parents=True, exist_ok=True)
            with self._file_path.open("a", encoding="utf-8") as f:
                f.write(record.to_json() + "\n")

    def _read_lines(self) -> list[dict[str, Any]]:
        if not self._file_path.is_file():
            return []
        lines = []
        with self._file_path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    parsed = json.loads(line)
                except Exception:
                    continue
                if isinstance(parsed, dict):
                    lines.append(parsed)
        return lines

    def read_records(self) -> list[AuthorizationDecisionAuditRecord]:
        """Per-request authorization records (job-boundary lines excluded)."""
        with self._lock:
            records = []
            for data in self._read_lines():
                if data.get("record_type") == JOB_BOUNDARY_RECORD_TYPE:
                    continue
                try:
                    records.append(AuthorizationDecisionAuditRecord.from_dict(data))
                except Exception:
                    pass
            return records

    def read_job_records(self) -> list[HermesJobAuditRecord]:
        """The job-boundary records (JOB_START / JOB_END) from the same store."""
        with self._lock:
            records = []
            for data in self._read_lines():
                if data.get("record_type") != JOB_BOUNDARY_RECORD_TYPE:
                    continue
                try:
                    records.append(HermesJobAuditRecord.from_dict(data))
                except Exception:
                    pass
            return records


# ---------------------------------------------------------------------------
# Global per-job active audit sink binding (mirrors AuthorizationContext)
# ---------------------------------------------------------------------------

_ACTIVE_AUDIT_SINK: AuditSink | None = None
_ACTIVE_AUDIT_SINK_LOCK = threading.Lock()


def set_active_audit_sink(sink: AuditSink | None) -> None:
    """Bind the active audit sink under the runtime lock."""
    global _ACTIVE_AUDIT_SINK
    with _ACTIVE_AUDIT_SINK_LOCK:
        _ACTIVE_AUDIT_SINK = sink


def get_active_audit_sink() -> AuditSink | None:
    """Retrieve the active audit sink for the currently executing job."""
    with _ACTIVE_AUDIT_SINK_LOCK:
        return _ACTIVE_AUDIT_SINK


def record_policy_decision(
    authorization_context: Any,
    tool_name: Any,
    parameters: Any,
    decision: Any,
    sink: AuditSink | None = None,
) -> AuthorizationDecisionAuditRecord | None:
    """Record one §4 policy authorization decision.

    Emits structured logging (digests only, never secrets) and persists
    the record to the provided or active audit sink.
    Total function: never raises — audit failures must never take down the policy gate.
    """
    try:
        # Extract identity fields safely from context
        user_id = getattr(authorization_context, "user_id", None) or "<unknown>"
        project_id = getattr(authorization_context, "project_id", None) or "<unknown>"
        job_id = getattr(authorization_context, "job_id", None) or "<unknown>"
        agent_id = getattr(authorization_context, "agent_id", None) or "<unknown>"
        lineage_id = getattr(authorization_context, "lineage_id", None) or "<unknown>"

        tool_str = str(tool_name) if tool_name is not None else "<none>"
        param_digest = compute_parameter_digest(parameters)
        decision_str = "ALLOW" if getattr(decision, "allowed", False) else "BLOCK"
        reason_code = str(getattr(decision, "reason_code", "unknown"))

        record = AuthorizationDecisionAuditRecord(
            user_id=str(user_id),
            project_id=str(project_id),
            job_id=str(job_id),
            agent_id=str(agent_id),
            lineage_id=str(lineage_id),
            tool_name=tool_str,
            decision=decision_str,
            reason_code=reason_code,
            parameter_digest=param_digest,
            parameters=parameters if isinstance(parameters, dict) else None,
        )

        # Structured logging: only parameter_digest, never raw parameter values
        if record.decision == "ALLOW":
            logger.info(
                "hermes_policy_decision",
                audit_id=record.audit_id,
                decision=record.decision,
                reason_code=record.reason_code,
                tool_name=record.tool_name,
                parameter_digest=record.parameter_digest,
                job_id=record.job_id,
                lineage_id=record.lineage_id,
            )
        else:
            logger.warning(
                "hermes_policy_decision",
                audit_id=record.audit_id,
                decision=record.decision,
                reason_code=record.reason_code,
                tool_name=record.tool_name,
                parameter_digest=record.parameter_digest,
                job_id=record.job_id,
                lineage_id=record.lineage_id,
            )

        # Persistent audit sink
        target_sink = sink if sink is not None else get_active_audit_sink()
        if target_sink is not None:
            try:
                target_sink.record(record)
            except Exception as sink_exc:
                logger.error("hermes_audit_sink_record_failed", error=str(sink_exc), audit_id=record.audit_id)

        return record
    except Exception as exc:
        logger.error("hermes_record_policy_decision_failed", error=str(exc))
        return None


def record_final_outcome(
    tool_name: Any,
    parameters: Any,
    reason_code: str,
    sink: AuditSink | None = None,
) -> AuthorizationDecisionAuditRecord | None:
    """Record one additive final-outcome BLOCK (§13.1).

    For a request that PASSED §4 — whose §4 ALLOW audit record stands
    unchanged — but was finally rejected downstream by the §9 schema
    validation layer (reason "capability_schema_invalid") or the §12
    resource-limit layer (reason "tool_call_limit_exceeded", ...). The
    resulting trail distinguishes:

        §4 decision = ALLOW  (unmodified §4 record)
        final outcome = BLOCK (this record, layer's reason code)

    Identity fields come from the runtime-bound active authorization
    context when available (the §9/§12 wrappers close over no context);
    a missing context degrades to "<unknown>" fields, never an error.

    Total function: never raises — audit is authorization-preserving and
    best-effort; a recording failure must never bypass §4, flip a
    decision, or fail the job.
    """
    try:
        try:
            from app.hermes.runtime import get_active_authorization_context

            authorization_context = get_active_authorization_context()
        except Exception:
            authorization_context = None

        user_id = getattr(authorization_context, "user_id", None) or "<unknown>"
        project_id = getattr(authorization_context, "project_id", None) or "<unknown>"
        job_id = getattr(authorization_context, "job_id", None) or "<unknown>"
        agent_id = getattr(authorization_context, "agent_id", None) or "<unknown>"
        lineage_id = getattr(authorization_context, "lineage_id", None) or "<unknown>"

        tool_str = str(tool_name) if tool_name is not None else "<none>"

        record = AuthorizationDecisionAuditRecord(
            user_id=str(user_id),
            project_id=str(project_id),
            job_id=str(job_id),
            agent_id=str(agent_id),
            lineage_id=str(lineage_id),
            tool_name=tool_str,
            decision="BLOCK",
            reason_code=str(reason_code),
            parameter_digest=compute_parameter_digest(parameters),
            parameters=parameters if isinstance(parameters, dict) else None,
        )

        # Structured logging: only the parameter digest, never raw values
        logger.warning(
            "hermes_final_outcome",
            audit_id=record.audit_id,
            decision=record.decision,
            reason_code=record.reason_code,
            tool_name=record.tool_name,
            parameter_digest=record.parameter_digest,
            job_id=record.job_id,
            lineage_id=record.lineage_id,
        )

        target_sink = sink if sink is not None else get_active_audit_sink()
        if target_sink is not None:
            try:
                target_sink.record(record)
            except Exception as sink_exc:
                logger.error("hermes_audit_sink_record_failed", error=str(sink_exc), audit_id=record.audit_id)

        return record
    except Exception as exc:
        logger.error("hermes_record_final_outcome_failed", error=str(exc))
        return None


def record_job_boundary(
    event: str,
    authorization_context: Any,
    *,
    sink: AuditSink | None = None,
    runtime_job_id: str | None = None,
    hermes_commit: str | None = None,
    hermes_tree: str | None = None,
    hermes_git_verified: bool | None = None,
    config_sha256: str | None = None,
    plugin_verification: str | None = None,
    limits_snapshot: dict[str, Any] | None = None,
    duration_seconds: float | None = None,
    outcome: str | None = None,
    error_code: str | None = None,
    violation_code: str | None = None,
) -> HermesJobAuditRecord | None:
    """Record one job-boundary event (§13): JOB_START or JOB_END.

    Emits a structured log (identity, outcome, verified pin, config digest,
    plugin verification — never secrets or raw configuration) and persists
    the HermesJobAuditRecord to the provided or active audit sink.

    Total function: never raises — audit is authorization-preserving and
    best-effort; a recording failure must never change the job outcome.
    """
    try:
        user_id = getattr(authorization_context, "user_id", None) or "<unknown>"
        project_id = getattr(authorization_context, "project_id", None) or "<unknown>"
        job_id = getattr(authorization_context, "job_id", None) or "<unknown>"
        agent_id = getattr(authorization_context, "agent_id", None) or "<unknown>"
        lineage_id = getattr(authorization_context, "lineage_id", None) or "<unknown>"

        record = HermesJobAuditRecord(
            event=str(event),
            user_id=str(user_id),
            project_id=str(project_id),
            job_id=str(job_id),
            agent_id=str(agent_id),
            lineage_id=str(lineage_id),
            runtime_job_id=str(runtime_job_id) if runtime_job_id is not None else "",
            hermes_commit=hermes_commit,
            hermes_tree=hermes_tree,
            hermes_git_verified=hermes_git_verified,
            config_sha256=config_sha256,
            plugin_verification=plugin_verification,
            limits_snapshot=dict(limits_snapshot) if isinstance(limits_snapshot, dict) else None,
            duration_seconds=round(float(duration_seconds), 6)
            if isinstance(duration_seconds, (int, float))
            else None,
            outcome=outcome,
            error_code=error_code,
            violation_code=violation_code,
        )

        logger.info(
            "hermes_job_boundary",
            boundary_event=record.event,
            audit_id=record.audit_id,
            runtime_job_id=record.runtime_job_id,
            job_id=record.job_id,
            lineage_id=record.lineage_id,
            hermes_commit=record.hermes_commit,
            config_sha256=record.config_sha256,
            plugin_verification=record.plugin_verification,
            duration_seconds=record.duration_seconds,
            outcome=record.outcome,
            error_code=record.error_code,
            violation_code=record.violation_code,
        )

        target_sink = sink if sink is not None else get_active_audit_sink()
        if target_sink is not None:
            try:
                target_sink.record(record)
            except Exception as sink_exc:
                logger.error("hermes_audit_sink_record_failed", error=str(sink_exc), audit_id=record.audit_id)

        return record
    except Exception as exc:
        logger.error("hermes_record_job_boundary_failed", error=str(exc))
        return None
