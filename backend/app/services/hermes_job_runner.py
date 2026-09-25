"""AryaOS production Hermes job-runner — §3.1 (V2).

Spec: docs/architecture/HERMES_INTEGRATION_SPEC.md — §3 (the embedding
model: AryaOS drives the agent loop under AryaOS resource limits), §9
(side-effect bookkeeping), §12, §13 (job-boundary records).

This is the FIRST production caller of
app.hermes.runtime.run_hermes_job(). Operator decisions D1-D6 (locked):

- D1: internal service only — no FastAPI route, no API-surface change.
- D2: the existing §13 JOB_START/JOB_END audit records are the Hermes job
  lifecycle records; WorkflowRun stays the AryaOS run identity; no new
  table/model/migration; the runner never mutates WorkflowRun.
- D3: ONE Hermes job per WorkflowRun (the ratified budget-accumulator
  scope). Enforced by an in-process served-run registry under a lock;
  a second active job for the same run fails deterministically. NOT
  enforced via audit reads (audit is best-effort observability and must
  never gate execution); a process restart clears the registry — accepted
  under the single-process contract (D5).
- D4: run_hermes_job(request, settings=None) — the runtime validation and
  the §9.3 provider.generate binding therefore consume the same cached
  get_settings() source; no explicit settings plumbing exists.
- D5: synchronous, in-process; the runtime's _RUNTIME_LOCK stays the sole
  serialization authority; no queue/worker/distributed locking.
- D6: model routing is fixed and AryaOS-owned — provider "openrouter",
  model settings.default_llm_model, api_key SecretsManager
  ("openrouter_api_key"), base_url the /v1 root of the existing OpenRouter
  adapter endpoint constant. None of it is task-controllable.

Sub-decisions (recorded): job_id is a fresh UUID token per invocation;
agent_id is minted deterministically as "hermes-<job_id>" (no registry —
the §10 issuance system remains a deferred slice); lineage_id defaults to
the workflow_run_id (the existing lineage anchor); an OPTIONAL caller-
asserted project_id enables tenant verification (mismatch and nonexistent
runs fail with one uniform code — no tenant-existence oracle).

Fail-closed contract: every admission/validation failure returns a typed
runner error (this function never raises for expected failures, never
retries Hermes, and passes HermesJobResult error_code/detail through
unchanged — settings_invalid, hermes_disabled, chat_timeout, §12
violations, unexpected_runtime_failure included). The wall-clock watchdog
remains entirely inside runtime.py.
"""
import threading
import uuid
from dataclasses import dataclass

from app.core.config import get_settings
from app.core.secrets import get_secrets_manager
from app.hermes.policy import AuthorizationContext
from app.hermes.runtime import HermesJobRequest, HermesJobResult, run_hermes_job
from app.providers.openrouter import _API_URL as _OPENROUTER_ENDPOINT

# D6: the chat-completions /v1 root of the existing adapter endpoint
# (providers/openrouter.py: "_API_URL = .../v1/chat/completions").
_OPENROUTER_BASE_URL = _OPENROUTER_ENDPOINT[: -len("/chat/completions")]
_PROVIDER_NAME = "openrouter"
_API_KEY_SETTING = "openrouter_api_key"

# Deterministic, value-free runner admission error codes.
_RUN_INPUT_INVALID = "runner_input_invalid"
_RUN_ID_INVALID = "runner_workflow_run_id_invalid"
_RUN_NOT_FOUND = "runner_workflow_run_not_found"  # uniform: nonexistent AND foreign
_RUN_ALREADY_ACTIVE = "runner_workflow_run_already_active"
_RUN_VERIFY_FAILED = "runner_verification_failed"
_RUN_CREDENTIALS_MISSING = "runner_model_credentials_missing"

# D3: in-process served-run registry (one Hermes job per WorkflowRun).
_ACTIVE_RUNS: set[str] = set()
_ACTIVE_RUNS_LOCK = threading.Lock()


@dataclass(frozen=True)
class HermesRunnerCall:
    """One runner invocation. Caller identity is `user_id`; the project/
    tenant scope is resolved from the verified WorkflowRun (or, when the
    optional `project_id` is supplied, asserted against it)."""

    workflow_run_id: uuid.UUID | str
    task_message: str
    user_id: str
    lineage_id: str | None = None
    project_id: str | None = None  # optional caller-asserted tenant scope


@dataclass(frozen=True)
class HermesRunnerResult:
    """Either the unchanged HermesJobResult passthrough (admitted jobs)
    or a typed runner admission failure. `job_id` is the minted runtime
    job token (None when the call was never admitted)."""

    hermes: HermesJobResult | None
    job_id: str | None
    error_code: str | None
    error_detail: str | None

    @property
    def admitted(self) -> bool:
        return self.hermes is not None


def _failure(code: str, detail: str) -> HermesRunnerResult:
    return HermesRunnerResult(hermes=None, job_id=None, error_code=code, error_detail=detail)


def _resolve_run_project(run_uuid: uuid.UUID, asserted_project: str | None) -> tuple[str | None, str | None]:
    """Read-only WorkflowRun verification: returns (project_id, None) on
    success or (None, error_code) fail-closed. Nonexistent runs and
    project mismatches share ONE uniform code (no tenant-existence
    oracle); infrastructure failures never raise."""
    try:
        import asyncio

        from sqlalchemy.ext.asyncio import async_sessionmaker

        from app.hermes.capabilities import _make_capability_engine
        from app.models.core import WorkflowRun

        async def _verify() -> tuple[str | None, str | None]:
            engine = _make_capability_engine()
            try:
                async with async_sessionmaker(bind=engine, expire_on_commit=False)() as session:
                    run = await session.get(WorkflowRun, run_uuid)
                    if run is None:
                        return None, _RUN_NOT_FOUND
                    project = str(run.project_id)
                    if asserted_project is not None and project != asserted_project.strip():
                        return None, _RUN_NOT_FOUND
                    return project, None
            finally:
                await engine.dispose()

        return asyncio.run(_verify())
    except Exception:
        return None, _RUN_VERIFY_FAILED


def run_aryaos_hermes_job(call: HermesRunnerCall) -> HermesRunnerResult:
    """Run one production Hermes job for a WorkflowRun (§3.1). See the
    module docstring for the locked D1-D6 contract. Total for expected
    failures; returns the HermesJobResult unchanged when admitted."""
    task = call.task_message if isinstance(call.task_message, str) else ""
    user = call.user_id if isinstance(call.user_id, str) else ""
    if not task.strip() or not user.strip():
        return _failure(_RUN_INPUT_INVALID, "task_message and user_id must be non-empty strings")

    if isinstance(call.workflow_run_id, uuid.UUID):
        run_uuid = call.workflow_run_id
    elif isinstance(call.workflow_run_id, str):
        try:
            run_uuid = uuid.UUID(call.workflow_run_id.strip())
        except (ValueError, TypeError):
            return _failure(_RUN_ID_INVALID, "workflow_run_id is not a valid identifier")
    else:
        return _failure(_RUN_ID_INVALID, "workflow_run_id is not a valid identifier")

    registry_key = str(run_uuid)
    with _ACTIVE_RUNS_LOCK:
        if registry_key in _ACTIVE_RUNS:
            return _failure(
                _RUN_ALREADY_ACTIVE,
                "another Hermes job is already active for this workflow run (§3.1 D3)",
            )
        _ACTIVE_RUNS.add(registry_key)
    try:
        project, verify_error = _resolve_run_project(run_uuid, call.project_id)
        if verify_error is not None:
            return _failure(verify_error, "workflow run unavailable for this caller")

        try:
            api_key = get_secrets_manager().get(_API_KEY_SETTING)
        except Exception:
            return _failure(
                _RUN_CREDENTIALS_MISSING,
                "the configured model provider credential is not available",
            )

        job_id = str(uuid.uuid4())
        context = AuthorizationContext(
            user_id=user.strip(),
            project_id=project,
            job_id=job_id,
            workflow_run_id=registry_key,
            agent_id=f"hermes-{job_id}",
            lineage_id=(call.lineage_id.strip() if isinstance(call.lineage_id, str) and call.lineage_id.strip() else registry_key),
        )
        request = HermesJobRequest(
            job_id=job_id,
            task_message=task,
            authorization_context=context,
            provider=_PROVIDER_NAME,
            base_url=_OPENROUTER_BASE_URL,
            api_key=api_key,
            model=get_settings().default_llm_model,
        )
        result = run_hermes_job(request, settings=None)  # D4: single settings source
        return HermesRunnerResult(
            hermes=result, job_id=job_id, error_code=None, error_detail=None
        )
    finally:
        with _ACTIVE_RUNS_LOCK:
            _ACTIVE_RUNS.discard(registry_key)
