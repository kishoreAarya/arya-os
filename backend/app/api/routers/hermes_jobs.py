"""AryaOS Hermes invocation surface — §9.6 (V2).

The FIRST production HTTP caller of
app.services.hermes_job_runner.run_aryaos_hermes_job(). Operator
decisions D1-D10 (locked):

- D1: additive FastAPI route; the runner stays the canonical execution
  service (no second Hermes execution path).
- D2: 202 Accepted + background execution + polling. The runner is
  SYNCHRONOUS/BLOCKING (threading locks + its own watchdog thread) and
  MUST NEVER run on the FastAPI event loop: the background coroutine
  offloads it via starlette.concurrency.run_in_threadpool (an existing
  dependency — no queue, no Celery, no worker processes).
- D3: `user_id` is CALLER-SUPPLIED METADATA only. The current
  authentication is the service-level ARYA_API_KEY bearer and derives no
  human identity; user_id is recorded in the §13 identity trail exactly
  as the runner receives it and authorizes nothing.
- D4: `workflow_run_id` is the authoritative execution anchor. The
  optional `project_id` is passed straight through as the runner's
  existing cross-check assertion — this route performs NO authorization
  of its own and duplicates no runner logic.
- D5: approval semantics are UNCHANGED and stage-scoped. Known policy
  residual (ratified frozen): "Approval currently authorizes the
  workflow-run stage rather than an immutable parameter snapshot."
- D6: Hermes is single-process (F1). `uvicorn_workers=1` remains the
  operational requirement (config default; pinned by the production
  hardening test). No distributed/Redis/DB locking exists here.
- D7: no rate limiter. Residual: sequential submissions across distinct
  runs are not rate-limited (threadpool-queued, watchdog-bounded).
- D8: no HermesJob table. Live state is the in-memory `_HERMES_JOBS`
  registry; the durable terminal-state fallback is the existing §13
  JOB_START/JOB_END audit records (D2-of-§3.1 contract).
- D9: no notifications — the caller polls.
- D10: no idempotency keys. Concurrent same-run submissions are rejected
  by the existing runner registry; sequential resubmission is valid
  Job N+1 behavior.
"""
import asyncio
import threading
import uuid
from datetime import UTC, datetime

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict, Field

from app.core.logging import get_logger
from app.services.hermes_job_runner import HermesRunnerCall, run_aryaos_hermes_job

logger = get_logger("arya.api.hermes_jobs")

router = APIRouter(prefix="/api/hermes/jobs", tags=["hermes"])

# D8: in-memory live job state (creator.py _ACTIVE_JOBS pattern). Lost on
# restart by design — the §13 audit store is the durable fallback.
_HERMES_JOBS: dict[str, dict] = {}
_HERMES_JOBS_LOCK = threading.Lock()

_STATUS_SUBMITTED = "submitted"
_STATUS_RUNNING = "running"
_STATUS_COMPLETED = "completed"
_STATUS_FAILED = "failed"
_STATUS_AWAITING = "awaiting_approval"
# Deterministic terminal mapping for a job whose process died mid-run:
# JOB_START exists with no JOB_END (§13 fallback). Never reported as
# completed; never persisted as a new state anywhere else.
_STATUS_INTERRUPTED = "failed"


class HermesJobSubmitRequest(BaseModel):
    """§9.6 request contract — mirrors HermesRunnerCall exactly.

    D3: user_id is caller-supplied metadata, NOT authenticated identity.
    D4: project_id is the runner's optional cross-check assertion only.
    No provider/model/credential/platform/destination/capability fields
    can cross this boundary (extra="forbid")."""

    model_config = ConfigDict(extra="forbid")

    workflow_run_id: uuid.UUID
    task_message: str = Field(min_length=1, pattern=r"\S")  # non-blank
    user_id: str = Field(min_length=1, pattern=r"\S")  # non-blank metadata
    lineage_id: str | None = None
    project_id: str | None = None


class HermesJobSubmitResponse(BaseModel):
    job_id: str
    workflow_run_id: str
    status: str
    submitted_at: str


class HermesJobStatusResponse(BaseModel):
    job_id: str
    workflow_run_id: str
    status: str
    error_code: str | None = None
    error_detail: str | None = None
    final_response: str | None = None
    duration_seconds: float | None = None
    submitted_at: str
    completed_at: str | None = None
    # R-s1 remediation (operator-authorized additive field): the frozen
    # runner's runtime job id — the key §13 audit records carry. None
    # until the runner has produced it; purely an identifier (never an
    # authorization credential). Backward compatible: pre-existing
    # consumers ignore it.
    runtime_job_id: str | None = None


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _run_scope_mismatch(actual: str | None, asserted: str | None) -> bool:
    """D8-F: explicit read-only run-scope assertion for job polling. True
    only when the caller SUPPLIED a scope and it does not match the
    record's workflow run. An omitted/blank assertion never filters
    (backward compatible). The check authorizes nothing — the API key
    remains the authentication boundary — and a mismatch is reported as
    an ordinary not-found (no oracle)."""
    if asserted is None or not asserted.strip():
        return False
    return (actual or "").strip().lower() != asserted.strip().lower()


async def _run_hermes_job_background(job_id: str, call: HermesRunnerCall) -> None:
    """D2: execute the blocking runner OFF the event loop via the existing
    Starlette threadpool primitive; convert the runner result verbatim."""
    with _HERMES_JOBS_LOCK:
        entry = _HERMES_JOBS.get(job_id)
        if entry is not None:
            entry["status"] = _STATUS_RUNNING
    try:
        from starlette.concurrency import run_in_threadpool

        result = await run_in_threadpool(run_aryaos_hermes_job, call)
    except BaseException as exc:  # surface-level boundary
        logger.error("hermes_job_surface_crashed", job_id=job_id, error=type(exc).__name__)
        with _HERMES_JOBS_LOCK:
            entry = _HERMES_JOBS.get(job_id)
            if entry is not None:
                entry["status"] = _STATUS_FAILED
                entry["error_code"] = "surface_execution_error"
                entry["error_detail"] = type(exc).__name__
                entry["completed_at"] = _now()
        return
    if not result.admitted:
        # Runner admission failure (duplicate-active run, invalid input,
        # unavailable run, missing credentials): surfaced verbatim.
        with _HERMES_JOBS_LOCK:
            entry = _HERMES_JOBS.get(job_id)
            if entry is not None:
                entry["status"] = _STATUS_FAILED
                entry["error_code"] = result.error_code
                entry["error_detail"] = result.error_detail
                entry["completed_at"] = _now()
        return
    hermes = result.hermes
    with _HERMES_JOBS_LOCK:
        entry = _HERMES_JOBS.get(job_id)
        if entry is not None:
            entry["status"] = hermes.status  # completed | failed | awaiting_approval
            entry["error_code"] = hermes.error_code
            entry["error_detail"] = hermes.error_detail
            entry["final_response"] = hermes.final_response if hermes.status == _STATUS_COMPLETED else None
            entry["completed_at"] = _now()
            # R-s1: preserve the frozen runner's runtime job id — the key
            # §13 records carry — so the caller can recover the terminal
            # record across a process restart via runtime-id polling.
            entry["runner_job_id"] = result.job_id


@router.post("", response_model=HermesJobSubmitResponse, status_code=202)
async def submit_hermes_job(payload: HermesJobSubmitRequest) -> HermesJobSubmitResponse:
    """Submit one Hermes job (D2: 202 + background execution + polling)."""
    job_id = str(uuid.uuid4())
    submitted_at = _now()
    entry = {
        "job_id": job_id,
        "workflow_run_id": str(payload.workflow_run_id),
        "status": _STATUS_SUBMITTED,
        "error_code": None,
        "error_detail": None,
        "final_response": None,
        "duration_seconds": None,
        "submitted_at": submitted_at,
        "completed_at": None,
        "runner_job_id": None,
    }
    with _HERMES_JOBS_LOCK:
        _HERMES_JOBS[job_id] = entry
    call = HermesRunnerCall(
        workflow_run_id=payload.workflow_run_id,
        task_message=payload.task_message,
        user_id=payload.user_id,
        lineage_id=payload.lineage_id,
        project_id=payload.project_id,
    )
    asyncio.create_task(_run_hermes_job_background(job_id, call))
    return HermesJobSubmitResponse(
        job_id=job_id,
        workflow_run_id=str(payload.workflow_run_id),
        status=_STATUS_SUBMITTED,
        submitted_at=submitted_at,
    )


def _reconstruct_from_audit(
    job_id: str, workflow_run_id: str | None = None
) -> HermesJobStatusResponse | None:
    """D8 §13 fallback: rebuild the terminal state of a surface job from
    the existing persistent audit records (runtime_job_id == job_id).
    D8-F: an asserted workflow_run_id additionally scopes the lookup — a
    mismatching run returns None (the caller sees the ordinary 404),
    indistinguishable from an absent job."""
    try:
        from pathlib import Path

        from app.core.config import get_settings
        from app.hermes.audit import FileAuditSink

        audit_file = Path(get_settings().hermes_home or "") / "audit" / "hermes_policy_audit.jsonl"
        if not audit_file.is_file():
            return None
        records = [r for r in FileAuditSink(audit_file).read_job_records() if r.runtime_job_id == job_id]
    except Exception:  # best-effort fallback: any failure is not-found
        return None
    if not records:
        return None
    start = next((r for r in records if r.event == "JOB_START"), None)
    end = next((r for r in records if r.event == "JOB_END"), None)
    if start is None:
        return None
    if _run_scope_mismatch(start.workflow_run_id, workflow_run_id):
        return None
    workflow_run_id = start.workflow_run_id
    submitted_at = start.occurred_at
    if end is None:
        # JOB_START without JOB_END: the process died mid-run (or the job
        # is genuinely still executing in another incarnation of this
        # service). Deterministic interrupted-failure — never "completed".
        return HermesJobStatusResponse(
            job_id=job_id,
            workflow_run_id=workflow_run_id,
            status=_STATUS_INTERRUPTED,
            error_code="surface_job_interrupted",
            error_detail="JOB_START exists without JOB_END; the executing process did not report a terminal state",
            final_response=None,
            duration_seconds=None,
            submitted_at=submitted_at,
            completed_at=None,
            runtime_job_id=job_id,  # the fallback is runtime-id keyed (R-s1)
        )
    status = end.outcome if end.outcome in (_STATUS_COMPLETED, _STATUS_FAILED, _STATUS_AWAITING) else _STATUS_FAILED
    return HermesJobStatusResponse(
        job_id=job_id,
        workflow_run_id=workflow_run_id,
        status=status,
        error_code=end.error_code,
        error_detail=None,
        final_response=None,
        duration_seconds=end.duration_seconds,
        submitted_at=submitted_at,
        completed_at=end.occurred_at,
        runtime_job_id=job_id,  # the fallback is runtime-id keyed (R-s1)
    )


@router.get("/{job_id}", response_model=HermesJobStatusResponse)
async def get_hermes_job_status(job_id: str, workflow_run_id: str | None = None) -> HermesJobStatusResponse:
    """Poll one Hermes job: live in-memory state (by surface id, or by the
    R-s1 runtime id once the runner has produced one), else §13 audit
    fallback (runtime-id keyed). Both lookups are behind the same
    API-key dependency; the runtime id is an identifier only.
    D8-F: an OPTIONAL workflow_run_id query parameter asserts a run
    scope on BOTH lookups — supplied and mismatching, the poll is the
    ordinary 404 (no oracle). It is a read-only scope assertion only:
    it authorizes nothing and the API key remains the authentication
    boundary."""
    from fastapi import HTTPException
    from starlette import status as http_status

    with _HERMES_JOBS_LOCK:
        entry = _HERMES_JOBS.get(job_id)
        if entry is None:
            # R-s1 additive lookup: the caller may poll by the runtime id.
            entry = next(
                (e for e in _HERMES_JOBS.values() if e.get("runner_job_id") == job_id),
                None,
            )
        snapshot = dict(entry) if entry is not None else None
    if snapshot is not None:
        # D8-F: a mismatching run scope is reported exactly like an
        # unknown job — never another run's status, never fall-through to
        # the audit fallback for the same id.
        if _run_scope_mismatch(snapshot.get("workflow_run_id"), workflow_run_id):
            raise HTTPException(status_code=http_status.HTTP_404_NOT_FOUND, detail=f"Job '{job_id}' not found")
        return HermesJobStatusResponse(
            job_id=snapshot["job_id"],
            workflow_run_id=snapshot["workflow_run_id"],
            status=snapshot["status"],
            error_code=snapshot.get("error_code"),
            error_detail=snapshot.get("error_detail"),
            final_response=snapshot.get("final_response"),
            duration_seconds=snapshot.get("duration_seconds"),
            submitted_at=snapshot["submitted_at"],
            completed_at=snapshot.get("completed_at"),
            runtime_job_id=snapshot.get("runner_job_id"),
        )

    reconstructed = _reconstruct_from_audit(job_id, workflow_run_id=workflow_run_id)
    if reconstructed is None:
        raise HTTPException(status_code=http_status.HTTP_404_NOT_FOUND, detail=f"Job '{job_id}' not found")
    return reconstructed
