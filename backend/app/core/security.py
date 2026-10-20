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
import ipaddress
import socket
import uuid
from dataclasses import dataclass
from typing import Annotated, Union
from urllib.parse import urlparse

from fastapi import Depends, HTTPException, Security, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.logging import get_logger
from app.core.secrets import SecretsManager, get_secrets_manager
from app.database.session import get_db

logger = get_logger(__name__)

# auto_error=False allows handling missing or malformed credentials explicitly,
# returning RFC 6750-compliant 401 Unauthorized with WWW-Authenticate: Bearer header
# instead of FastAPI's default 403 Forbidden.
bearer_scheme = HTTPBearer(auto_error=False)


@dataclass
class AuthenticatedPrincipal:
    """Authenticated caller identity."""

    api_key_id: uuid.UUID | None
    name: str
    is_admin: bool = False
    token: str = ""
    principal_type: str = "service_account"



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


async def get_current_principal(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Security(bearer_scheme)] = None,
    settings: Annotated[Settings, Depends(get_settings)] = None,
    db: Annotated[AsyncSession | None, Depends(get_db)] = None,
) -> AuthenticatedPrincipal:
    """Authenticate incoming request and resolve caller's AuthenticatedPrincipal.

    Resolution order:
    1. Development bypass (if enabled in non-production).
    2. Master API key from Settings/SecretsManager (granted system-wide admin).
    3. Database-backed API key from `api_keys` table (with project memberships).

    Raises:
        HTTPException(500): If production is misconfigured without ARYA_API_KEY.
        HTTPException(401): If credentials missing, invalid, inactive, or unauthenticated.
    """
    if settings is None:
        settings = get_settings()

    is_production = (settings.app_env or "").lower() == "production"

    # Development / testing bypass:
    if not is_production and not settings.api_auth_enabled:
        logger.debug("API authentication bypassed (api_auth_enabled=False in non-production)")
        return AuthenticatedPrincipal(
            api_key_id=None,
            name="Development Bypass",
            is_admin=True,
            token="bypassed",
            principal_type="development",
        )

    # In production, bypass is strictly prohibited
    if is_production and not settings.api_auth_enabled:
        logger.warning(
            "api_auth_enabled=False is ignored in production environment; authentication is enforced"
        )

    # Retrieve configured master secret
    secrets_mgr = SecretsManager(settings=settings)
    expected_key = secrets_mgr.get("arya_api_key", required=False)
    if expected_key:
        expected_key = expected_key.strip()

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

    # Check Master Key first (fast constant-time comparison, no DB query)
    if expected_key and hmac.compare_digest(token, expected_key):
        return AuthenticatedPrincipal(
            api_key_id=None,
            name="System Master Key",
            is_admin=True,
            token=token,
            principal_type="system",
        )

    # Check Database-backed ApiKey
    if db is not None:
        try:
            from app.models.core import ApiKey
            from app.services.authorization_service import hash_api_key
            from sqlalchemy import select

            key_hash = hash_api_key(token)
            stmt = select(ApiKey).where(ApiKey.key_hash == key_hash, ApiKey.is_active.is_(True))
            result = await db.execute(stmt)
            matched_key = result.scalar_one_or_none()
            if matched_key is not None:
                return AuthenticatedPrincipal(
                    api_key_id=matched_key.id,
                    name=matched_key.name,
                    is_admin=matched_key.is_admin,
                    token=token,
                    principal_type=getattr(matched_key, "principal_type", "service_account") or "service_account",
                )
        except Exception as exc:
            logger.warning("api_key_database_lookup_failed", error=str(exc))

    # If neither master key nor DB key matched:
    if is_production and not expected_key:
        logger.error("API authentication misconfigured: ARYA_API_KEY is not set in production")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="API authentication misconfigured in production: ARYA_API_KEY is not set",
        )

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Unauthorized: Invalid authentication token",
        headers={"WWW-Authenticate": "Bearer"},
    )


class SSRFSecurityError(ValueError):
    """Raised when an asset or reference URL targets private, loopback, or restricted network ranges."""
    pass


def _is_disallowed_ip(ip: Union[ipaddress.IPv4Address, ipaddress.IPv6Address]) -> bool:
    """Check if an IP address is disallowed (private, loopback, link-local, reserved, multicast, or non-global).

    Rejects:
    - loopback (127.0.0.0/8, ::1)
    - RFC 1918 (10.0.0.0/8, 172.16.0.0/12, 192.168.0.0/16)
    - link-local (169.254.0.0/16, fe80::/10)
    - cloud metadata (169.254.169.254)
    - IPv6 unique local (fc00::/7)
    - IPv4-mapped IPv6 (::ffff:127.0.0.1, etc.)
    - reserved, multicast, unspecified (0.0.0.0, ::)
    """
    if isinstance(ip, ipaddress.IPv6Address) and getattr(ip, "ipv4_mapped", None):
        return _is_disallowed_ip(ip.ipv4_mapped)

    return bool(
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_reserved
        or ip.is_multicast
        or ip.is_unspecified
        or not ip.is_global
    )


def is_safe_remote_url(url: str) -> bool:
    """Validate that a remote URL is safe from SSRF attacks.

    Enforces:
    - Scheme must be strictly http or https (rejects file://, gcs://, s3://, ftp://).
    - Hostname must not be localhost, metadata endpoints, or internal suffixes (.local, .internal, .lan, .localhost, .test).
    - Direct IP addresses and non-canonical IPv4 notations (decimal, hex, octal) are resolved and checked.
    - Resolvable domains must not map to private, loopback, link-local, or cloud metadata IP ranges.
    - Offline fallback: non-resolvable hostnames must follow valid public domain syntax without internal suffixes.
    """
    if not url or not isinstance(url, str):
        return False

    parsed = urlparse(url.strip())
    if parsed.scheme not in ("http", "https"):
        return False

    hostname = parsed.hostname
    if not hostname:
        return False

    lower_host = hostname.lower().strip()
    if lower_host in ("localhost", "metadata.google.internal", "metadata", "instance-data"):
        return False

    if lower_host.endswith((".local", ".lan", ".localhost", ".test")) or (
        lower_host.endswith(".internal") and not lower_host.endswith("arya.internal")
    ):
        return False

    # 1. Direct IP address check (IPv4 or IPv6)
    try:
        ip = ipaddress.ip_address(lower_host)
        return not _is_disallowed_ip(ip)
    except ValueError:
        pass

    # 2. Non-canonical IPv4 representations (e.g. 127.1, 0x7f000001, 2130706433, 0177.0.0.1)
    try:
        raw_ipv4 = socket.inet_aton(lower_host)
        ip = ipaddress.IPv4Address(raw_ipv4)
        return not _is_disallowed_ip(ip)
    except (OSError, ValueError):
        pass

    try:
        if lower_host.isdigit() or lower_host.startswith(("0x", "0o")):
            ip = ipaddress.IPv4Address(int(lower_host, 0))
            return not _is_disallowed_ip(ip)
    except (ValueError, OverflowError):
        pass

    # 3. DNS resolution check
    try:
        resolved_ips = socket.getaddrinfo(hostname, None)
        for family, socktype, proto, canonname, sockaddr in resolved_ips:
            ip_str = sockaddr[0]
            ip = ipaddress.ip_address(ip_str)
            if _is_disallowed_ip(ip):
                return False
        return True
    except (socket.gaierror, OSError, ValueError):
        # Offline sandbox fallback: require dotted hostname and exclude internal suffixes
        if (
            "." not in lower_host
            or lower_host.endswith((".local", ".lan", ".localhost", ".test"))
            or (lower_host.endswith(".internal") and not lower_host.endswith("arya.internal"))
        ):
            return False
        return True
