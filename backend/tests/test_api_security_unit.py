"""
Unit tests for API Security & Authentication (Task 8).

Tests:
- Missing Authorization header returns 401 Unauthorized
- Malformed / non-Bearer Authorization header returns 401 Unauthorized
- Wrong Bearer token returns 401 Unauthorized
- Correct Bearer token succeeds
- WWW-Authenticate: Bearer header is returned on 401
- Public endpoints (/health, /ready, /, /docs, /openapi.json) are accessible without token
- All sensitive endpoints reject unauthenticated requests
- Constant-time secret comparison (hmac.compare_digest) is verified
- Development bypass functions when api_auth_enabled=False in non-production
- Production environment strictly enforces authentication even if api_auth_enabled=False
- Production environment fails securely (500) if ARYA_API_KEY is not configured
- No secret key is leaked in error response bodies or headers
"""
from __future__ import annotations

import uuid
from unittest.mock import patch

import httpx
import pytest
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials
from httpx import ASGITransport

from app.core.config import Settings
from app.core.security import verify_api_key
from app.main import app

TEST_SECRET_KEY = "test-arya-secret-token-12345"


# ---------------------------------------------------------------------------
# Direct unit tests for verify_api_key()
# ---------------------------------------------------------------------------

def test_verify_api_key_success():
    """Valid Bearer token matching configured ARYA_API_KEY succeeds."""
    settings = Settings(
        app_env="development",
        api_auth_enabled=True,
        arya_api_key=TEST_SECRET_KEY,
    )
    creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials=TEST_SECRET_KEY)
    result = verify_api_key(credentials=creds, settings=settings)
    assert result == TEST_SECRET_KEY


def test_verify_api_key_whitespace_stripping():
    """Valid Bearer token with surrounding whitespace is stripped cleanly."""
    settings = Settings(
        app_env="development",
        api_auth_enabled=True,
        arya_api_key=f"  {TEST_SECRET_KEY}  ",
    )
    creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials=f"  {TEST_SECRET_KEY}  ")
    result = verify_api_key(credentials=creds, settings=settings)
    assert result == TEST_SECRET_KEY


def test_verify_api_key_missing_credentials_raises_401():
    """Missing credentials raises 401 with WWW-Authenticate: Bearer."""
    settings = Settings(
        app_env="development",
        api_auth_enabled=True,
        arya_api_key=TEST_SECRET_KEY,
    )
    with pytest.raises(HTTPException) as exc_info:
        verify_api_key(credentials=None, settings=settings)

    assert exc_info.value.status_code == 401
    assert exc_info.value.headers.get("WWW-Authenticate") == "Bearer"
    assert "credentials" in exc_info.value.detail.lower() or "unauthorized" in exc_info.value.detail.lower()


def test_verify_api_key_empty_token_raises_401():
    """Empty credentials raises 401."""
    settings = Settings(
        app_env="development",
        api_auth_enabled=True,
        arya_api_key=TEST_SECRET_KEY,
    )
    creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials="   ")
    with pytest.raises(HTTPException) as exc_info:
        verify_api_key(credentials=creds, settings=settings)

    assert exc_info.value.status_code == 401
    assert exc_info.value.headers.get("WWW-Authenticate") == "Bearer"


def test_verify_api_key_invalid_scheme_raises_401():
    """Non-Bearer scheme raises 401."""
    settings = Settings(
        app_env="development",
        api_auth_enabled=True,
        arya_api_key=TEST_SECRET_KEY,
    )
    creds = HTTPAuthorizationCredentials(scheme="Basic", credentials=TEST_SECRET_KEY)
    with pytest.raises(HTTPException) as exc_info:
        verify_api_key(credentials=creds, settings=settings)

    assert exc_info.value.status_code == 401
    assert exc_info.value.headers.get("WWW-Authenticate") == "Bearer"
    assert "scheme" in exc_info.value.detail.lower()


def test_verify_api_key_wrong_token_raises_401():
    """Incorrect Bearer token raises 401 and does NOT leak the real secret."""
    settings = Settings(
        app_env="development",
        api_auth_enabled=True,
        arya_api_key=TEST_SECRET_KEY,
    )
    creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials="wrong-secret-token")
    with pytest.raises(HTTPException) as exc_info:
        verify_api_key(credentials=creds, settings=settings)

    assert exc_info.value.status_code == 401
    assert exc_info.value.headers.get("WWW-Authenticate") == "Bearer"
    assert TEST_SECRET_KEY not in exc_info.value.detail


def test_verify_api_key_constant_time_comparison_used():
    """Verifies that hmac.compare_digest is called for token verification."""
    settings = Settings(
        app_env="development",
        api_auth_enabled=True,
        arya_api_key=TEST_SECRET_KEY,
    )
    creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials=TEST_SECRET_KEY)
    with patch("app.core.security.hmac.compare_digest", wraps=__import__("hmac").compare_digest) as mock_compare:
        result = verify_api_key(credentials=creds, settings=settings)
        assert result == TEST_SECRET_KEY
        mock_compare.assert_called_once_with(TEST_SECRET_KEY, TEST_SECRET_KEY)


def test_verify_api_key_dev_bypass():
    """In development, setting api_auth_enabled=False bypasses authentication."""
    settings = Settings(
        app_env="development",
        api_auth_enabled=False,
        arya_api_key=None,
    )
    result = verify_api_key(credentials=None, settings=settings)
    assert result == "bypassed"


def test_verify_api_key_production_forbids_bypass():
    """In production, api_auth_enabled=False is ignored and auth is enforced."""
    settings = Settings(
        app_env="production",
        api_auth_enabled=False,  # Should be ignored in production!
        arya_api_key=TEST_SECRET_KEY,
    )
    # Unauthenticated request in production must still raise 401
    with pytest.raises(HTTPException) as exc_info:
        verify_api_key(credentials=None, settings=settings)

    assert exc_info.value.status_code == 401
    assert exc_info.value.headers.get("WWW-Authenticate") == "Bearer"


def test_verify_api_key_production_missing_secret_fails_securely():
    """In production, missing ARYA_API_KEY fails securely with HTTP 500."""
    settings = Settings(
        app_env="production",
        api_auth_enabled=True,
        arya_api_key=None,
    )
    creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials=TEST_SECRET_KEY)
    with pytest.raises(HTTPException) as exc_info:
        verify_api_key(credentials=creds, settings=settings)

    assert exc_info.value.status_code == 500
    assert "misconfigured" in exc_info.value.detail.lower()


def test_verify_api_key_dev_auth_enabled_missing_secret_fails_securely():
    """In dev, if auth is enabled but ARYA_API_KEY is unset, fails with HTTP 500."""
    settings = Settings(
        app_env="development",
        api_auth_enabled=True,
        arya_api_key=None,
    )
    creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials="any-token")
    with pytest.raises(HTTPException) as exc_info:
        verify_api_key(credentials=creds, settings=settings)

    assert exc_info.value.status_code == 500
    assert "not configured" in exc_info.value.detail.lower()


# ---------------------------------------------------------------------------
# HTTP integration tests via FastAPI App
# ---------------------------------------------------------------------------

@pytest.fixture
def override_settings(monkeypatch):
    """Fixture ensuring consistent Settings for HTTP tests."""
    from app.core.config import get_settings
    settings = get_settings()
    monkeypatch.setattr(settings, "arya_api_key", TEST_SECRET_KEY)
    monkeypatch.setattr(settings, "api_auth_enabled", True)
    monkeypatch.setattr(settings, "app_env", "development")
    return settings


@pytest.mark.asyncio
async def test_public_endpoints_accessible_without_token(override_settings):
    """Public endpoints (/health, /ready, /, /docs, /openapi.json) require no auth."""
    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        # Root endpoint
        resp = await client.get("/")
        assert resp.status_code == 200

        # Health probes
        resp_health = await client.get("/health")
        assert resp_health.status_code == 200

        resp_ready = await client.get("/ready")
        assert resp_ready.status_code == 200

        # OpenAPI documentation
        resp_docs = await client.get("/docs")
        assert resp_docs.status_code == 200

        resp_openapi = await client.get("/openapi.json")
        assert resp_openapi.status_code == 200


@pytest.mark.asyncio
async def test_protected_endpoints_reject_unauthenticated_requests(override_settings):
    """Every sensitive route rejects requests lacking the Authorization header with 401."""
    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        fake_uuid = uuid.uuid4()
        endpoints_to_test = [
            ("GET", "/agents/"),
            ("POST", "/agents/ScriptAgent/run"),
            ("POST", "/approvals/"),
            ("GET", f"/approvals/{fake_uuid}"),
            ("GET", f"/approvals/pending/{fake_uuid}"),
            ("GET", "/feature-flags/"),
            ("GET", "/feature-flags/test_flag"),
            ("GET", f"/lineage/{fake_uuid}"),
            ("GET", f"/workflow-runs/{fake_uuid}"),
            ("POST", "/workflow-runs/"),
            ("POST", "/workflows/youtube"),
            ("GET", "/providers"),
            ("GET", "/database"),
            ("GET", "/storage"),
            ("GET", "/validators"),
        ]

        for method, path in endpoints_to_test:
            if method == "GET":
                resp = await client.get(path)
            else:
                resp = await client.post(path, json={})

            assert resp.status_code == 401, f"{method} {path} expected 401 but got {resp.status_code}"
            assert resp.headers.get("WWW-Authenticate") == "Bearer"
            # Ensure configured secret is not leaked in error response
            assert TEST_SECRET_KEY not in resp.text


@pytest.mark.asyncio
async def test_protected_endpoints_reject_invalid_token(override_settings):
    """Requests with wrong bearer token receive 401."""
    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        headers = {"Authorization": "Bearer wrong-secret-token"}
        resp = await client.get("/feature-flags/", headers=headers)
        assert resp.status_code == 401
        assert resp.headers.get("WWW-Authenticate") == "Bearer"
        assert TEST_SECRET_KEY not in resp.text


@pytest.mark.asyncio
async def test_protected_endpoints_reject_malformed_auth_header(override_settings):
    """Requests with non-Bearer or malformed header receive 401."""
    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        # Basic auth instead of Bearer
        resp_basic = await client.get("/feature-flags/", headers={"Authorization": "Basic dXNlcjpwYXNz"})
        assert resp_basic.status_code == 401
        assert resp_basic.headers.get("WWW-Authenticate") == "Bearer"

        # Bearer without token
        resp_empty = await client.get("/feature-flags/", headers={"Authorization": "Bearer"})
        assert resp_empty.status_code == 401
        assert resp_empty.headers.get("WWW-Authenticate") == "Bearer"


@pytest.mark.asyncio
async def test_protected_endpoints_accept_valid_token(override_settings):
    """Requests with valid Bearer token proceed through authentication."""
    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        headers = {"Authorization": f"Bearer {TEST_SECRET_KEY}"}
        # /agents/ lists registered agents and doesn't require complex body
        resp = await client.get("/agents/", headers=headers)
        assert resp.status_code == 200
        assert "agents" in resp.json()

        # /validators lists registered validators
        resp_val = await client.get("/validators", headers=headers)
        assert resp_val.status_code == 200
        assert "validators" in resp_val.json()


@pytest.mark.asyncio
async def test_development_bypass_via_api_auth_enabled_false(override_settings, monkeypatch):
    """When api_auth_enabled=False in development, unauthenticated requests succeed."""
    monkeypatch.setattr(override_settings, "api_auth_enabled", False)
    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        resp = await client.get("/agents/")
        assert resp.status_code == 200
        assert "agents" in resp.json()


@pytest.mark.asyncio
async def test_production_rejects_bypass(override_settings, monkeypatch):
    """When app_env=production, api_auth_enabled=False is ignored and auth is enforced."""
    monkeypatch.setattr(override_settings, "app_env", "production")
    monkeypatch.setattr(override_settings, "api_auth_enabled", False)
    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        resp = await client.get("/agents/")
        assert resp.status_code == 401
        assert resp.headers.get("WWW-Authenticate") == "Bearer"
