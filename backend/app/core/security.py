"""
API Security and Authentication module for Project Arya OS.

Enforces Bearer token (shared-secret) authentication across sensitive endpoints.
Protects single-operator deployment against unauthorized access while providing:
- Constant-time token verification using hmac.compare_digest
- Clear 401 Unauthorized responses with WWW-Authenticate header
- Secure handling (secrets never leaked in logs or error bodies)
- Explicit development bypass (api_auth_enabled=False in non-production only)
- Strict production enforcement (never allow bypass in production, fail fast if unconfigured)
"""
from __future__ import annotations

import hmac
from typing import Annotated

from fastapi import Depends, HTTPException, Security, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.config import Settings, get_settings
from app.core.logging import get_logger
from app.core.secrets import SecretsManager, get_secrets_manager

logger = get_logger(__name__)

# auto_error=False allows handling missing or malformed credentials explicitly,
# returning RFC 6750-compliant 401 Unauthorized with WWW-Authenticate: Bearer header
# instead of FastAPI's default 403 Forbidden.
bearer_scheme = HTTPBearer(auto_error=False)


def verify_api_key(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Security(bearer_scheme)] = None,
    settings: Annotated[Settings, Depends(get_settings)] = None,
) -> str:
    """Validate incoming request Bearer token against configured ARYA_API_KEY.

    Returns:
        The validated token string or 'bypassed' if development bypass is active.

    Raises:
        HTTPException(500): If production is misconfigured without ARYA_API_KEY,
                            or auth is enabled without ARYA_API_KEY configured.
        HTTPException(401): If authorization credentials are missing, malformed,
                            or invalid.
    """
    if settings is None:
        settings = get_settings()

    is_production = (settings.app_env or "").lower() == "production"

    # Development / testing bypass:
    # Allowed ONLY in non-production environments when api_auth_enabled is explicitly False.
    if not is_production and not settings.api_auth_enabled:
        logger.debug("API authentication bypassed (api_auth_enabled=False in non-production)")
        return "bypassed"

    # In production, bypass is strictly prohibited
    if is_production and not settings.api_auth_enabled:
        logger.warning(
            "api_auth_enabled=False is ignored in production environment; authentication is enforced"
        )

    # Retrieve configured secret (from Settings or SecretsManager scoped to settings)
    secrets_mgr = SecretsManager(settings=settings)
    expected_key = secrets_mgr.get("arya_api_key", required=False)
    if expected_key:
        expected_key = expected_key.strip()

    if not expected_key:
        if is_production:
            logger.error("API authentication misconfigured: ARYA_API_KEY is not set in production")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="API authentication misconfigured in production: ARYA_API_KEY is not set",
            )
        else:
            logger.error("API authentication is enabled but ARYA_API_KEY is not configured")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="API authentication is enabled but ARYA_API_KEY is not configured",
            )

    # Validate presence of credentials
    if credentials is None or not credentials.credentials or not credentials.credentials.strip():
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Unauthorized: Missing or invalid authentication credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Validate scheme
    if credentials.scheme.lower() != "bearer":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Unauthorized: Invalid authentication scheme, Bearer required",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token = credentials.credentials.strip()

    # Constant-time comparison to protect against timing attacks
    if not hmac.compare_digest(token, expected_key):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Unauthorized: Invalid authentication token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return token
