"""Unit tests for Production Deployment Hardening in Arya OS (Task 12).

Tests:
- Strict production authentication enforcement (no bypass, fail fast on missing key)
- Structured logging secret redaction processor
- Health / Readiness HTTP 503 status on degraded state
- Database connection pool settings and production configuration
- Dockerfile, .dockerignore, and entrypoint verification
"""
from __future__ import annotations

import os
import stat
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
import pytest
from fastapi import HTTPException, Request, Response, status
from fastapi.security import HTTPAuthorizationCredentials

from app.api.routers.health import health, ready
from app.core.config import Settings
from app.core.logging import redact_sensitive_data
from app.core.security import verify_api_key


# ---------------------------------------------------------------------------
# 1. Production Authentication Enforcement
# ---------------------------------------------------------------------------

def test_production_auth_strict_enforcement():
    """Verify that in production (APP_ENV=production), auth cannot be disabled and requires API key."""
    # 1. Auth bypass attempt in production MUST be ignored, enforcing auth and rejecting unauthenticated request with 401
    prod_settings_bypass = Settings(
        app_env="production",
        api_auth_enabled=False,
        arya_api_key="secret-key",
    )
    with pytest.raises(HTTPException) as exc_info:
        verify_api_key(credentials=None, settings=prod_settings_bypass)
    assert exc_info.value.status_code == status.HTTP_401_UNAUTHORIZED
    assert "Missing or invalid authentication credentials" in exc_info.value.detail

    # 2. Missing ARYA_API_KEY in production MUST raise 500
    prod_settings_no_key = Settings(
        app_env="production",
        api_auth_enabled=True,
        arya_api_key=None,
    )
    with pytest.raises(HTTPException) as exc_info:
        verify_api_key(credentials=None, settings=prod_settings_no_key)
    assert exc_info.value.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR
    assert "ARYA_API_KEY is not set" in exc_info.value.detail

    # 3. Valid Bearer credentials in production must pass
    prod_settings_valid = Settings(
        app_env="production",
        api_auth_enabled=True,
        arya_api_key="production-secret-token-12345",
    )
    creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials="production-secret-token-12345")
    assert verify_api_key(credentials=creds, settings=prod_settings_valid) == "production-secret-token-12345"

    # 4. Invalid Bearer token must raise 401
    bad_creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials="wrong-token")
    with pytest.raises(HTTPException) as exc_info:
        verify_api_key(credentials=bad_creds, settings=prod_settings_valid)
    assert exc_info.value.status_code == status.HTTP_401_UNAUTHORIZED


# ---------------------------------------------------------------------------
# 2. Structured Logging Secret Redaction Processor
# ---------------------------------------------------------------------------

def test_log_redaction_masks_sensitive_keys():
    """Verify that redact_sensitive_data masks secrets, keys, and tokens in log event dictionaries."""
    sample_event = {
        "event": "provider_call",
        "stage": "script_generation",
        "gemini_api_key": "AIzaSySecretApiKey123",
        "auth_token": "bearer-token-abc",
        "client_secret": "my-client-secret",
        "nested": {
            "password": "db-password",
            "safe_key": "safe_value",
            "tokens": ["tok1", "tok2"],
        },
        "safe_number": 42,
    }

    sanitized = redact_sensitive_data(None, "info", sample_event)

    assert sanitized["gemini_api_key"] == "***REDACTED***"
    assert sanitized["auth_token"] == "***REDACTED***"
    assert sanitized["client_secret"] == "***REDACTED***"
    assert sanitized["nested"]["password"] == "***REDACTED***"
    assert sanitized["nested"]["safe_key"] == "safe_value"
    assert sanitized["safe_number"] == 42
    assert sanitized["stage"] == "script_generation"


# ---------------------------------------------------------------------------
# 3. Health & Readiness Probes (HTTP 503 on degraded state)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_health_probe_detects_database_failure():
    """Verify /health returns degraded status when PostgreSQL is unreachable."""
    mock_db = AsyncMock()
    mock_db.execute.side_effect = ConnectionRefusedError("Postgres down")

    mock_request = MagicMock(spec=Request)
    mock_request.app.state.redis.ping = AsyncMock(return_value=True)

    res = await health(request=mock_request, db=mock_db)

    assert res["status"] == "degraded"
    assert "error" in res["checks"]["postgres"]


@pytest.mark.asyncio
async def test_health_probe_returns_healthy():
    """Verify /health returns healthy status when all dependencies are connected."""
    mock_db = AsyncMock()
    mock_db.execute.return_value = None

    mock_request = MagicMock(spec=Request)
    mock_request.app.state.redis.ping = AsyncMock(return_value=True)

    res = await health(request=mock_request, db=mock_db)

    assert res["status"] == "healthy"
    assert res["checks"]["postgres"] == "ok"
    assert res["checks"]["redis"] == "ok"


@pytest.mark.asyncio
async def test_ready_probe_detects_storage_failure():
    """Verify /ready detects when storage roundtrip fails."""
    mock_db = AsyncMock()
    mock_db.execute.return_value = None

    mock_request = MagicMock(spec=Request)
    mock_request.app.state.redis.ping = AsyncMock(return_value=True)

    with patch("app.api.routers.health.get_storage_provider") as mock_storage:
        instance = mock_storage.return_value
        instance.upload.side_effect = PermissionError("Storage disk full or read-only")

        res = await ready(request=mock_request, db=mock_db)

        assert res["ready"] is False
        assert "error" in res["storage"]


# ---------------------------------------------------------------------------
# 4. Production Configuration Defaults
# ---------------------------------------------------------------------------

def test_production_settings_and_pool_defaults():
    """Verify production settings, single worker default, and connection pool configuration."""
    s = Settings()
    assert s.uvicorn_workers == 1  # Required due to in-process APScheduler
    assert s.uvicorn_timeout_keep_alive == 65
    assert s.uvicorn_timeout_graceful_shutdown == 60
    assert s.auto_run_migrations is True
    assert s.db_pool_size >= 10
    assert s.db_max_overflow >= 5
    assert s.db_pool_timeout >= 10
    assert s.db_pool_recycle >= 300


# ---------------------------------------------------------------------------
# 5. Dockerfile, .dockerignore, and Entrypoint Verification
# ---------------------------------------------------------------------------

def test_dockerignore_excludes_sensitive_files():
    """Verify .dockerignore excludes secrets, venv, and build artifacts."""
    dockerignore_path = Path(".dockerignore")
    assert dockerignore_path.exists(), ".dockerignore must exist"
    content = dockerignore_path.read_text(encoding="utf-8")
    assert ".env" in content
    assert ".git" in content
    assert ".venv" in content
    assert "data/storage" in content


def test_entrypoint_script_executable_and_fail_fast():
    """Verify docker/entrypoint.sh exists, is executable, and contains migration fail-fast."""
    entrypoint = Path("docker/entrypoint.sh")
    assert entrypoint.exists(), "docker/entrypoint.sh must exist"
    st = os.stat(entrypoint)
    assert bool(st.st_mode & stat.S_IXUSR), "docker/entrypoint.sh must be executable"

    content = entrypoint.read_text(encoding="utf-8")
    assert "alembic upgrade head" in content
    assert "exit 1" in content
    assert "uvicorn app.main:app" in content


def test_dockerfile_contains_ffmpeg_and_non_root_user():
    """Verify docker/Dockerfile.backend installs ffmpeg, creates non-root user, and exposes healthcheck."""
    dockerfile = Path("docker/Dockerfile.backend")
    assert dockerfile.exists()
    content = dockerfile.read_text(encoding="utf-8")
    assert "ffmpeg" in content
    assert "curl" in content
    assert "useradd" in content
    assert "USER appuser" in content
    assert "HEALTHCHECK" in content
    assert "ENTRYPOINT" in content
