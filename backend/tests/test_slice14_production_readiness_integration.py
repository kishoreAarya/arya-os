"""
Slice 14 Integration & Regression Tests: Production Operability, Observability & Deployment Safety.

Covers:
1. Production Configuration Validation (rejection of dev defaults, insecure CORS, placeholder credentials).
2. Health & Readiness Semantics (/live liveness, /ready 503 on dependency failure, zero error leaks).
3. Request Correlation ID & Global Unhandled Exception Sanitization (masking 500 stack traces, x-request-id header).
4. Cost Accounting Reconciliation (reconciling WorkflowRun.total_cost_usd against ProviderUsageLog sums).
5. Graceful Shutdown & Stale Workflow Recovery (lease release on shutdown, auto-recovery of stale leases).
"""

import asyncio
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch
import uuid
import pytest
import pytest_asyncio
from fastapi import FastAPI, HTTPException
from httpx import ASGITransport, AsyncClient
from starlette.requests import Request
from starlette.responses import JSONResponse

from app.api.routers.health import health, ready
from app.api.routers.workflow_runs import (
    _IS_SHUTTING_DOWN,
    _run_workflow_background_task,
    shutdown_background_workflow_tasks,
)
import app.api.routers.workflow_runs as wr_module
from app.core.config import Settings, validate_production_settings
from app.main import app
from app.models.core import Project, WorkflowRun
from app.models.enums import WorkflowMode, WorkflowStatus
from app.models.provider import Provider, ProviderCategory, ProviderUsageLog
from app.services.workflow_execution_service import (
    auto_recover_stale_workflow_runs,
    claim_execution_lease,
)
from app.workers.jobs import aggregate_costs

pytestmark = pytest.mark.asyncio(loop_scope="module")


# ---------------------------------------------------------------------------
# 1. Production Configuration & Secret Safety Tests
# ---------------------------------------------------------------------------


async def test_production_config_rejects_insecure_default_key():
    """Verify production mode rejects default development API keys."""
    settings = Settings(
        app_env="production",
        arya_api_key="arya_dev_secret_key_change_in_production",
        database_url="postgresql+asyncpg://arya:prod_strong_pass@prod-db.internal:5432/arya_os",
    )
    with pytest.raises(ValueError, match="insecure default placeholder"):
        settings.validate_production_safety()


async def test_production_config_rejects_missing_or_short_key():
    """Verify production mode rejects empty or short API keys."""
    settings_missing = Settings(
        app_env="production",
        arya_api_key=None,
        database_url="postgresql+asyncpg://arya:prod_strong_pass@prod-db.internal:5432/arya_os",
    )
    with pytest.raises(ValueError, match="ARYA_API_KEY must be set"):
        settings_missing.validate_production_safety()

    settings_short = Settings(
        app_env="production",
        arya_api_key="short_key",
        database_url="postgresql+asyncpg://arya:prod_strong_pass@prod-db.internal:5432/arya_os",
    )
    with pytest.raises(ValueError, match="at least 16 characters"):
        settings_short.validate_production_safety()


async def test_production_config_rejects_cors_wildcard_with_credentials():
    """Verify production mode forbids wildcard CORS origin with allow_credentials=True."""
    settings = Settings(
        app_env="production",
        arya_api_key="a_very_strong_production_api_key_12345",
        cors_allowed_origins=["*"],
        cors_allow_credentials=True,
        database_url="postgresql+asyncpg://arya:prod_strong_pass@prod-db.internal:5432/arya_os",
    )
    with pytest.raises(ValueError, match="CORS cannot allow credentials with wildcard"):
        settings.validate_production_safety()


async def test_production_config_rejects_default_database_password():
    """Verify production mode forbids change_me placeholder in DATABASE_URL."""
    settings = Settings(
        app_env="production",
        arya_api_key="a_very_strong_production_api_key_12345",
        database_url="postgresql+asyncpg://arya:change_me@prod-db.internal:5432/arya_os",
    )
    with pytest.raises(ValueError, match="DATABASE_URL contains default insecure placeholder"):
        settings.validate_production_safety()


async def test_valid_production_config_passes():
    """Verify a properly hardened production configuration passes validation cleanly."""
    settings = Settings(
        app_env="production",
        arya_api_key="a_very_strong_production_api_key_12345",
        cors_allowed_origins=["https://arya.example.com"],
        cors_allow_credentials=True,
        database_url="postgresql+asyncpg://arya:super_secret_db_pass@prod-db.internal:5432/arya_prod",
    )
    # Should not raise
    settings.validate_production_safety()
    validate_production_settings(settings)


async def test_development_config_allows_local_defaults():
    """Verify non-production mode does not raise errors on local development defaults."""
    settings = Settings(
        app_env="development",
        arya_api_key="arya_dev_secret_key_change_in_production",
        database_url="postgresql+asyncpg://arya:change_me@localhost:5432/arya_os",
    )
    # Should not raise in development
    settings.validate_production_safety()


# ---------------------------------------------------------------------------
# 2. Health & Readiness Semantics Tests
# ---------------------------------------------------------------------------


async def test_live_probe_returns_ok_without_dependencies():
    """Verify /live endpoint responds with 200 OK immediately."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        resp = await client.get("/live")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "alive"


async def test_ready_probe_returns_503_on_storage_failure():
    """Verify /ready returns HTTP 503 when storage round-trip fails."""
    mock_db = AsyncMock()
    mock_db.execute.return_value = None

    mock_request = MagicMock(spec=Request)
    mock_request.app.state.redis.ping = AsyncMock(return_value=True)

    with patch("app.api.routers.health.get_storage_provider") as mock_storage:
        storage_inst = mock_storage.return_value
        storage_inst.upload.side_effect = PermissionError("Disk full or read-only")

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://testserver") as client:
            with patch("app.api.routers.health.get_db", return_value=mock_db):
                resp = await client.get("/ready")
                assert resp.status_code == 503
                data = resp.json()
                assert data["ready"] is False
                assert data["storage"] == "error"
                # Ensure no stack trace or raw exception details are leaked
                assert "PermissionError" not in resp.text
                assert "Disk full" not in resp.text


# ---------------------------------------------------------------------------
# 3. Observability, Correlation ID & Global Exception Sanitization Tests
# ---------------------------------------------------------------------------


async def test_request_correlation_id_generated_and_echoed():
    """Verify requests without x-request-id receive a generated UUID in response header."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        resp = await client.get("/live")
        assert resp.status_code == 200
        req_id = resp.headers.get("x-request-id")
        assert req_id is not None
        assert len(req_id) > 10


async def test_request_correlation_id_propagated_from_client():
    """Verify client-supplied x-request-id is preserved in the response."""
    custom_id = "test-correlation-id-9988"
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        resp = await client.get("/live", headers={"x-request-id": custom_id})
        assert resp.status_code == 200
        assert resp.headers.get("x-request-id") == custom_id


async def test_global_exception_handler_sanitizes_500_errors():
    """Verify unhandled 500 errors return sanitized JSON with request_id and no tracebacks."""
    # Temporarily register a test route that raises an unexpected exception
    @app.get("/_test_unhandled_crash")
    async def crash_endpoint():
        raise RuntimeError("SecretDatabasePasswordFailure: db_pass=super_secret_xyz")

    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        resp = await client.get("/_test_unhandled_crash")
        assert resp.status_code == 500
        data = resp.json()
        assert data["detail"] == "Internal Server Error"
        assert "request_id" in data
        assert resp.headers.get("x-request-id") == data["request_id"]

        # CRITICAL: Confirm zero tracebacks or sensitive secrets are disclosed
        assert "RuntimeError" not in resp.text
        assert "SecretDatabasePasswordFailure" not in resp.text
        assert "super_secret_xyz" not in resp.text
        assert "Traceback" not in resp.text


# ---------------------------------------------------------------------------
# 4. Cost Accounting Reconciliation Tests
# ---------------------------------------------------------------------------


async def test_aggregate_costs_reconciles_drifted_workflow_runs(db_session):
    """Verify aggregate_costs correctly sums ProviderUsageLog and updates WorkflowRun.total_cost_usd."""
    project = Project(name=f"Cost Test Project {uuid.uuid4().hex[:6]}")
    db_session.add(project)
    await db_session.flush()

    run = WorkflowRun(
        project_id=project.id,
        topic="Cost Test Video",
        mode=WorkflowMode.AUTONOMOUS,
        status=WorkflowStatus.COMPLETED,
        total_cost_usd=Decimal("0.0000"),  # Drifted from actual spend
    )
    db_session.add(run)
    await db_session.flush()

    # Create dummy provider
    prov = Provider(
        name=f"test_provider_{uuid.uuid4().hex[:6]}",
        category=ProviderCategory.LLM,
        is_active=True,
    )
    db_session.add(prov)
    await db_session.flush()

    # Create usage logs totaling $0.75
    log1 = ProviderUsageLog(
        workflow_run_id=run.id,
        provider_id=prov.id,
        cost_usd=Decimal("0.2500"),
        succeeded=True,
    )
    log2 = ProviderUsageLog(
        workflow_run_id=run.id,
        provider_id=prov.id,
        cost_usd=Decimal("0.5000"),
        succeeded=True,
    )
    db_session.add_all([log1, log2])
    await db_session.commit()

    # Run cost aggregation job
    updated = await aggregate_costs(db=db_session)
    assert updated >= 1

    await db_session.refresh(run)
    assert run.total_cost_usd == Decimal("0.7500")


# ---------------------------------------------------------------------------
# 5. Graceful Shutdown & Stale Workflow Recovery Tests
# ---------------------------------------------------------------------------


async def test_workflow_task_interrupted_by_shutdown_releases_lease_without_failure(db_session):
    """Verify a workflow task cancelled during server shutdown releases its worker lease and is NOT marked FAILED."""
    project = Project(name=f"Shutdown Test Project {uuid.uuid4().hex[:6]}")
    db_session.add(project)
    await db_session.flush()

    from app.services.workflow_execution_service import get_current_worker_id

    worker_id = get_current_worker_id()
    run = WorkflowRun(
        project_id=project.id,
        topic="Shutdown Test Video",
        mode=WorkflowMode.AUTONOMOUS,
        status=WorkflowStatus.RUNNING,
        worker_id=worker_id,
    )
    db_session.add(run)
    await db_session.commit()


    # Simulate server shutdown flag being set
    wr_module._IS_SHUTTING_DOWN = True
    try:
        # Simulate background task executing and receiving CancelledError during Runner execution
        with patch("app.workflows.runner.Runner.execute_existing_run", side_effect=asyncio.CancelledError()):
            with pytest.raises(asyncio.CancelledError):
                await _run_workflow_background_task(
                    run_id=run.id,
                    topic="Shutdown Test Video",
                    mode=WorkflowMode.AUTONOMOUS,
                )

        await db_session.refresh(run)
        # In shutdown mode, worker lease should be released (worker_id=None), but run must NOT be marked FAILED
        assert run.worker_id is None
        assert run.status == WorkflowStatus.RUNNING
    finally:
        wr_module._IS_SHUTTING_DOWN = False


async def test_auto_recover_stale_workflow_runs(db_session):
    """Verify auto_recover_stale_workflow_runs clears worker leases for stale workflow runs."""
    project = Project(name=f"Recovery Test Project {uuid.uuid4().hex[:6]}")
    db_session.add(project)
    await db_session.flush()

    run = WorkflowRun(
        project_id=project.id,
        topic="Stale Run",
        mode=WorkflowMode.AUTONOMOUS,
        status=WorkflowStatus.RUNNING,
        worker_id="crashed-worker-999",
        last_heartbeat_at=None,  # Stale lease immediately
    )
    db_session.add(run)
    await db_session.commit()

    recovered_ids = await auto_recover_stale_workflow_runs(db_session, timeout_seconds=10)
    assert run.id in recovered_ids

    await db_session.refresh(run)
    assert run.worker_id is None
    assert run.status == WorkflowStatus.RUNNING
