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


class InMemoryAuditSink:
    """Thread-safe in-memory sink for testing, inspection, and verification."""

    def __init__(self) -> None:
        self._records: list[AuthorizationDecisionAuditRecord] = []
        self._lock = threading.Lock()

    def record(self, record: AuthorizationDecisionAuditRecord) -> None:
        with self._lock:
            self._records.append(record)

    def records(self) -> list[AuthorizationDecisionAuditRecord]:
        with self._lock:
            return list(self._records)

    def clear(self) -> None:
        with self._lock:
            self._records.clear()


class FileAuditSink:
    """Persistent append-only file sink writing JSON Lines.

    Thread-safe; creates parent directory on demand.
    """

    def __init__(self, file_path: Path | str) -> None:
        self._file_path = Path(file_path)
        self._lock = threading.Lock()

    @property
    def file_path(self) -> Path:
        return self._file_path

    def record(self, record: AuthorizationDecisionAuditRecord) -> None:
        with self._lock:
            self._file_path.parent.mkdir(parents=True, exist_ok=True)
            with self._file_path.open("a", encoding="utf-8") as f:
                f.write(record.to_json() + "\n")

    def read_records(self) -> list[AuthorizationDecisionAuditRecord]:
        with self._lock:
            if not self._file_path.is_file():
                return []
            records = []
            with self._file_path.open("r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        try:
                            records.append(AuthorizationDecisionAuditRecord.from_dict(json.loads(line)))
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
