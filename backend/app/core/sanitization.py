"""
AryaOS V1 Stage 25 Phase 3.2.2 — Centralized Secret Redaction & Sanitization Engine.

Provides deterministic, fail-safe secret masking across all boundaries:
- Persisted action outputs & inputs (autonomous_action_nodes.outputs_json/inputs_json)
- Action errors and goal failure reasons (node.error, goal.failure_reason)
- Database event logs (system_logs table via log_event)
- Structured logging (structlog via redact_sensitive_data)
- Real-time SSE telemetry streams (TelemetryEvent payload & broadcast)
- API response serialization (AutonomousActionNodeResponse, etc.)

SAFETY INVARIANTS:
1. FAIL-SAFE: Any unexpected, circular, or malformed data structure fails closed,
   returning safe redacted placeholders rather than leaking unredacted secrets.
2. CONTEXT-PRESERVING: Masking replaces only secret values, preserving useful
   diagnostic context (HTTP status codes, exception class names, safe URL paths).
3. MULTI-LAYERED: Applies before persistence to the database AND before external
   exposure across API endpoints and SSE streams.
"""
from __future__ import annotations

import os
import re
import urllib.parse
import uuid
from datetime import date, datetime
from typing import Any

from pydantic import BaseModel

REDACTION_MARKER = "***REDACTED***"

# -----------------------------------------------------------------------------
# 1. Sensitive Key Name Patterns (Case-Insensitive)
# -----------------------------------------------------------------------------
SENSITIVE_KEY_NAMES: set[str] = {
    "api_key",
    "apikey",
    "api-key",
    "x-api-key",
    "arya_api_key",
    "secret",
    "secret_key",
    "client_secret",
    "token",
    "access_token",
    "refresh_token",
    "auth_token",
    "bearer_token",
    "authorization",
    "proxy-authorization",
    "password",
    "passphrase",
    "private_key",
    "credentials",
    "cookie",
    "set-cookie",
}

# -----------------------------------------------------------------------------
# 2. Token & Credential Regex Patterns
# -----------------------------------------------------------------------------
# Authorization header values (Bearer / Basic)
RE_BEARER = re.compile(r"(?i)\b(bearer\s+)([a-zA-Z0-9_\-\.+=~]{8,})")
RE_BASIC = re.compile(r"(?i)\b(basic\s+)([a-zA-Z0-9+/=]{8,})")

# Header-style key-values: Authorization: Bearer ... or "Authorization": "..."
RE_AUTH_HEADER = re.compile(
    r"(?i)(['\"]?(?:authorization|proxy-authorization)['\"]?\s*:\s*['\"]?)(?:bearer\s+|basic\s+)?([^\r\n,'\"]+)(['\"]?)",
)

# Known provider token formats
RE_ARYA_KEY = re.compile(r"\b(arya_[a-zA-Z0-9_\-]{16,})\b")
RE_OPENAI_KEY = re.compile(r"\b(sk-[a-zA-Z0-9_\-]{20,})\b")
RE_ANTHROPIC_KEY = re.compile(r"\b(sk-ant-[a-zA-Z0-9_\-]{20,})\b")
RE_GOOGLE_AI_KEY = re.compile(r"\b(AIza[0-9A-Za-z-_]{30,45})\b")
RE_FAL_KEY = re.compile(r"\b([a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}:[a-f0-9]{32})\b")
RE_AWS_KEY = re.compile(r"\b(AKIA[0-9A-Z]{16})\b")
RE_GITHUB_TOKEN = re.compile(r"\b(gh[pousr]_[A-Za-z0-9_]{36,})\b")
RE_SLACK_TOKEN = re.compile(r"\b(xox[baprs]-[A-Za-z0-9_\-]{10,})\b")
RE_JWT_TOKEN = re.compile(r"\b(eyJ[a-zA-Z0-9_\-]{10,}\.eyJ[a-zA-Z0-9_\-]{10,}\.[a-zA-Z0-9_\-]{10,})\b")

# Credentials embedded in URLs: https://user:password@host/path
RE_URL_USERPASS = re.compile(r"(https?://)([^:\s/@]+):([^@\s/]+)@")

# Query string credentials: ?key=secret or &token=secret
RE_URL_QUERY_SECRET = re.compile(
    r"([?&](?:api[-_]?key|key|token|access[-_]?token|secret|password|sig|signature)=)([^&\s]+)",
    re.IGNORECASE,
)

# Key-Value assignments in text/errors: api_key=secret, token: "secret", password='secret'
RE_KV_ASSIGNMENT = re.compile(
    r"(?i)\b((?:api_key|apikey|api-key|secret|password|client_secret|access_token|refresh_token)\s*[:=]\s*['\"]?)([^'\"\s,;&]{6,})(['\"]?)",
)


def get_known_configured_secrets() -> set[str]:
    """Retrieves all non-empty configured secret strings from application settings.

    Excludes short or generic strings (len < 6) to avoid false positives.
    """
    secrets: set[str] = set()
    try:
        from app.core.config import get_settings

        settings = get_settings()
        secret_fields = [
            "arya_api_key",
            "openrouter_api_key",
            "gemini_api_key",
            "anthropic_api_key",
            "openai_api_key",
            "runpod_api_key",
            "fal_api_key",
            "fal_key",
            "together_api_key",
            "replicate_api_key",
            "elevenlabs_api_key",
            "telegram_bot_token",
            "storage_secret_key",
            "storage_access_key",
            "youtube_api_key",
            "youtube_client_secret",
            "youtube_refresh_token",
            "reddit_client_secret",
            "postiz_api_key",
        ]
        for field_name in secret_fields:
            val = getattr(settings, field_name, None)
            if val and isinstance(val, str):
                cleaned = val.strip()
                if len(cleaned) >= 6:
                    secrets.add(cleaned)

        # Extract password from database_url if present
        db_url = getattr(settings, "database_url", None)
        if db_url and isinstance(db_url, str):
            try:
                parsed = urllib.parse.urlsplit(db_url)
                if parsed.password and len(parsed.password.strip()) >= 6:
                    secrets.add(parsed.password.strip())
            except Exception:
                pass
    except Exception:
        pass
    return secrets


def is_sensitive_key(key: str) -> bool:
    """Evaluates whether a dictionary or header key is sensitive based on name."""
    if not isinstance(key, str):
        return False
    normalized = key.lower().strip().replace("-", "_")
    return any(p in normalized for p in SENSITIVE_KEY_NAMES)


def sanitize_text(text: str) -> str:
    """Sanitizes sensitive tokens, credentials, headers, and URLs in raw string content.

    Preserves general sentence structure, HTTP error status codes, and non-sensitive text.
    Fails safely if an unexpected exception occurs.
    """
    if not isinstance(text, str):
        try:
            text = str(text)
        except Exception:
            return REDACTION_MARKER

    if not text:
        return text

    try:
        sanitized = text

        # 1. Mask exact known configured application secrets
        known_secrets = get_known_configured_secrets()
        for secret_val in sorted(known_secrets, key=len, reverse=True):
            if secret_val in sanitized:
                sanitized = sanitized.replace(secret_val, REDACTION_MARKER)

        # 2. Mask URL user:password credentials
        sanitized = RE_URL_USERPASS.sub(rf"\1{REDACTION_MARKER}:{REDACTION_MARKER}@", sanitized)

        # 3. Mask URL query string credentials
        sanitized = RE_URL_QUERY_SECRET.sub(rf"\1{REDACTION_MARKER}", sanitized)

        # 4. Mask Authorization headers in text
        sanitized = RE_AUTH_HEADER.sub(rf"\1{REDACTION_MARKER}\3", sanitized)

        # 5. Mask Bearer and Basic authentication tokens
        sanitized = RE_BEARER.sub(rf"\1{REDACTION_MARKER}", sanitized)
        sanitized = RE_BASIC.sub(rf"\1{REDACTION_MARKER}", sanitized)

        # 6. Mask key-value assignments in logs/errors (e.g. api_key=secret)
        sanitized = RE_KV_ASSIGNMENT.sub(rf"\1{REDACTION_MARKER}\3", sanitized)

        # 7. Mask provider-specific token patterns
        sanitized = RE_ARYA_KEY.sub(REDACTION_MARKER, sanitized)
        sanitized = RE_OPENAI_KEY.sub(REDACTION_MARKER, sanitized)
        sanitized = RE_ANTHROPIC_KEY.sub(REDACTION_MARKER, sanitized)
        sanitized = RE_GOOGLE_AI_KEY.sub(REDACTION_MARKER, sanitized)
        sanitized = RE_FAL_KEY.sub(REDACTION_MARKER, sanitized)
        sanitized = RE_AWS_KEY.sub(REDACTION_MARKER, sanitized)
        sanitized = RE_GITHUB_TOKEN.sub(REDACTION_MARKER, sanitized)
        sanitized = RE_SLACK_TOKEN.sub(REDACTION_MARKER, sanitized)
        sanitized = RE_JWT_TOKEN.sub(REDACTION_MARKER, sanitized)

        return sanitized
    except Exception:
        # Fail safely: never return potentially sensitive content unredacted
        return f"[REDACTED_CONTENT_SANITIZATION_FAILED]"


def sanitize_payload(
    obj: Any,
    max_depth: int = 50,
    _seen: set[int] | None = None,
) -> Any:
    """Recursively sanitizes JSON-like payloads, dictionaries, lists, and objects.

    - Sensitive dictionary keys have their values completely replaced with REDACTION_MARKER.
    - Other strings are sanitized for embedded tokens, credentials, and URLs.
    - Primitives (ints, floats, bools, None) and timestamps are preserved.
    - Circular references and deeply nested structures are bounded safely.
    - Any unexpected exception fails closed to a safe redacted placeholder.
    """
    if _seen is None:
        _seen = set()

    if max_depth <= 0:
        return "[MAX_DEPTH_EXCEEDED_REDACTED]"

    try:
        # None and basic primitives are safe
        if obj is None or isinstance(obj, (bool, int, float)):
            return obj

        # Date/time, UUID primitives are safe
        if isinstance(obj, (datetime, date, uuid.UUID)):
            return obj

        # Strings are sanitized directly
        if isinstance(obj, str):
            return sanitize_text(obj)

        # Check for circular reference
        obj_id = id(obj)
        if obj_id in _seen:
            return "[CIRCULAR_REFERENCE_REDACTED]"
        _seen.add(obj_id)

        # Dictionaries
        if isinstance(obj, dict):
            sanitized_dict: dict[str, Any] = {}
            for k, v in obj.items():
                k_str = str(k)
                clean_k = sanitize_text(k_str)
                if is_sensitive_key(k_str):
                    sanitized_dict[clean_k] = REDACTION_MARKER
                else:
                    sanitized_dict[clean_k] = sanitize_payload(v, max_depth - 1, _seen)
            return sanitized_dict

        # Lists
        if isinstance(obj, list):
            return [sanitize_payload(item, max_depth - 1, _seen) for item in obj]

        # Tuples
        if isinstance(obj, tuple):
            return tuple(sanitize_payload(item, max_depth - 1, _seen) for item in obj)

        # Sets
        if isinstance(obj, set):
            return {sanitize_payload(item, max_depth - 1, _seen) for item in obj}

        # Pydantic BaseModel instances
        if isinstance(obj, BaseModel):
            dumped = obj.model_dump()
            return sanitize_payload(dumped, max_depth - 1, _seen)

        # Exception objects
        if isinstance(obj, Exception):
            return sanitize_text(f"{obj.__class__.__name__}: {str(obj)}")

        # Objects with __dict__
        if hasattr(obj, "__dict__"):
            return sanitize_payload(vars(obj), max_depth - 1, _seen)

        # Default string conversion fallback
        return sanitize_text(str(obj))

    except Exception:
        # Fail-closed guarantee
        return {"__sanitized__": False, "error": "[MALFORMED_PAYLOAD_REDACTED]"}


def sanitize_exception_message(exc: Exception) -> str:
    """Extracts and sanitizes an exception message while preserving the error type."""
    try:
        class_name = exc.__class__.__name__
        msg = str(exc)
        sanitized_msg = sanitize_text(msg)
        return f"{class_name}: {sanitized_msg}"
    except Exception:
        return "Exception: [REDACTED_EXCEPTION_DETAILS]"
