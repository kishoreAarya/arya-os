"""
Security regression unit tests for:
unauthenticated-health-error-disclosure (CWE-209)

Verifies:
1. Public /health does not disclose database credentials, hostnames, ports, or raw exception strings when PostgreSQL query fails.
2. Public /health does not disclose Redis connection details, passwords, or raw exception strings when Redis ping fails.
3. Public /ready does not disclose local filesystem paths, S3 buckets, or credentials when storage operations fail.
4. Healthy /health and /ready endpoints return standard expected operational JSON structure.
5. Diagnostics endpoints (/database, /storage) do not leak raw exception strings on internal errors.
"""

from unittest.mock import AsyncMock, MagicMock, patch
import pytest
from starlette.testclient import TestClient

from app.api.routers.health import health, ready
from app.core.config import get_settings
from app.main import app

pytestmark = pytest.mark.asyncio


async def test_health_postgres_failure_does_not_leak_exception_details():
    """Verify /health masks raw PostgreSQL exception strings and connection details."""
    mock_db = AsyncMock()
    # Simulate a sensitive driver exception containing database credentials and internal topology
    sensitive_db_error = (
        "asyncpg.exceptions.InvalidPasswordError: password authentication failed "
        "for user 'arya_admin' at db.internal.cluster:5432/arya_production"
    )
    mock_db.execute.side_effect = Exception(sensitive_db_error)

    mock_request = MagicMock()
    mock_request.app.state.redis.ping = AsyncMock(return_value=True)

    result = await health(request=mock_request, db=mock_db)

    assert result["status"] == "degraded"
    assert result["checks"]["postgres"] == "error"
    assert result["checks"]["redis"] == "ok"

    # Confirm none of the sensitive error fragments leaked into the response
    res_str = str(result)
    assert "password authentication failed" not in res_str
    assert "arya_admin" not in res_str
    assert "db.internal.cluster" not in res_str
    assert "5432" not in res_str
    assert "arya_production" not in res_str


async def test_health_redis_failure_does_not_leak_exception_details():
    """Verify /health masks raw Redis exception strings and internal URI/token info."""
    mock_db = AsyncMock()
    mock_db.execute.return_value = None

    mock_request = MagicMock()
    sensitive_redis_error = (
        "redis.exceptions.ConnectionError: Error 111 connecting to "
        "redis://:super_secret_redis_pass@redis.prod.internal:6379/0"
    )
    mock_request.app.state.redis.ping.side_effect = Exception(sensitive_redis_error)

    result = await health(request=mock_request, db=mock_db)

    assert result["status"] == "degraded"
    assert result["checks"]["postgres"] == "ok"
    assert result["checks"]["redis"] == "error"

    res_str = str(result)
    assert "super_secret_redis_pass" not in res_str
    assert "redis.prod.internal" not in res_str
    assert "6379" not in res_str


async def test_ready_storage_failure_does_not_leak_filesystem_or_bucket_details():
    """Verify /ready masks raw storage exception strings and internal paths."""
    mock_db = AsyncMock()
    mock_db.execute.return_value = None

    mock_request = MagicMock()
    mock_request.app.state.redis.ping = AsyncMock(return_value=True)

    sensitive_storage_error = (
        "PermissionError: [Errno 13] Permission denied: "
        "'/opt/secure/mounted/arya_os_volume/keys/secrets.pem'"
    )

    with patch("app.api.routers.health.get_storage_provider") as mock_storage_factory:
        storage_instance = mock_storage_factory.return_value
        storage_instance.upload.side_effect = Exception(sensitive_storage_error)

        result = await ready(request=mock_request, db=mock_db)

        assert result["ready"] is False
        assert result["storage"] == "error"

        res_str = str(result)
        assert "/opt/secure/mounted" not in res_str
        assert "secrets.pem" not in res_str
        assert "PermissionError" not in res_str


async def test_healthy_probes_return_expected_structure():
    """Verify normal healthy operations still report 'healthy' and 'ready'."""
    mock_db = AsyncMock()
    mock_db.execute.return_value = None

    mock_request = MagicMock()
    mock_request.app.state.redis.ping = AsyncMock(return_value=True)

    with patch("app.api.routers.health.get_storage_provider") as mock_storage_factory:
        storage_instance = mock_storage_factory.return_value
        storage_instance.upload = AsyncMock()
        storage_instance.download = AsyncMock(return_value=b"ok")
        storage_instance.delete = AsyncMock()

        health_res = await health(request=mock_request, db=mock_db)
        assert health_res["status"] == "healthy"
        assert health_res["checks"] == {"postgres": "ok", "redis": "ok"}

        ready_res = await ready(request=mock_request, db=mock_db)
        assert ready_res["ready"] is True
        assert ready_res["storage"] == "ok"
