"""
Structured logging setup using structlog.

Every log line is JSON in production, human-readable in dev.
This is what feeds the Observability layer later (workflow history,
provider usage, execution time, failure reports all start here).
"""
import logging
import sys

import structlog

from app.core.config import get_settings


_SENSITIVE_PATTERNS = {
    "api_key",
    "token",
    "password",
    "secret",
    "client_secret",
    "refresh_token",
    "authorization",
    "arya_api_key",
    "access_token",
    "cookie",
}


def _redact_value(val: any) -> any:
    if isinstance(val, dict):
        return {
            k: ("***REDACTED***" if any(p in k.lower() for p in _SENSITIVE_PATTERNS) else _redact_value(v))
            for k, v in val.items()
        }
    if isinstance(val, list):
        return [_redact_value(item) for item in val]
    return val


def redact_sensitive_data(logger, method_name, event_dict):
    """Ensure sensitive credentials and authorization headers are never logged."""
    for k, v in list(event_dict.items()):
        if any(p in k.lower() for p in _SENSITIVE_PATTERNS):
            event_dict[k] = "***REDACTED***"
        elif isinstance(v, (dict, list)):
            event_dict[k] = _redact_value(v)
    return event_dict


def configure_logging() -> None:
    settings = get_settings()

    shared_processors: list = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        redact_sensitive_data,
        structlog.processors.StackInfoRenderer(),
    ]

    if settings.debug:
        renderer = structlog.dev.ConsoleRenderer()
    else:
        renderer = structlog.processors.JSONRenderer()

    structlog.configure(
        processors=shared_processors + [
            structlog.processors.format_exc_info,
            renderer,
        ],
        wrapper_class=structlog.make_filtering_bound_logger(
            getattr(logging, settings.log_level.upper(), logging.INFO)
        ),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )

    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=getattr(logging, settings.log_level.upper(), logging.INFO),
    )


def get_logger(name: str = "arya-os") -> structlog.BoundLogger:
    return structlog.get_logger(name)
