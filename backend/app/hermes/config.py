"""
Fail-closed validation for the Hermes runtime configuration (V2).

Spec: docs/architecture/HERMES_INTEGRATION_SPEC.md — §2 (commit pin),
§5 (configuration), §12 (resource limits).

Settings live on the central Settings object (app.core.config). This module
is the single place that decides whether a Hermes configuration is safe to
use. It never corrects or silently defaults invalid values — it rejects them.

Contract:
- hermes_enabled=False -> get_validated_hermes_config() returns None
  (Hermes features off; any leftover hermes_* settings are inert).
- hermes_enabled=True  -> every value must be present, well-formed, finite,
  and positive, or HermesConfigError is raised listing ALL violations.
  There is no unbounded mode: a missing limit is a failure, not infinity.

Hermes itself is not imported here and is not required to exist on this
machine. Source-level assertions (toolset allowlist, plugin load state,
commit-of-loaded-source) belong to the runtime adapter slice.
"""
import math
from dataclasses import dataclass
from pathlib import Path

from app.core.config import HERMES_COMMIT_PIN, Settings

# backend/app/hermes/config.py -> parents[3] is the AryaOS repository root,
# independent of the process working directory.
_ARYA_OS_ROOT = Path(__file__).resolve().parents[3]
_COMMIT_HEX_CHARS = set("0123456789abcdef")
_COMMIT_HEX_LENGTH = 40

_INT_LIMIT_FIELDS = (
    "hermes_max_iterations",
    "hermes_max_tool_calls",
    "hermes_max_tool_calls_per_capability",
    "hermes_max_context_tokens",
    "hermes_max_blocked_requests",
)

_FLOAT_LIMIT_FIELDS = (
    "hermes_max_execution_seconds",
    "hermes_max_generation_budget_usd",
)


class HermesConfigError(RuntimeError):
    """Invalid Hermes configuration. Fail-closed: the caller must not start
    (or continue into) any Hermes code path when this is raised.

    `violations` is a list of (code, detail) tuples with machine-readable
    codes such as "pin_missing" or "hermes_max_iterations_not_positive".
    """

    def __init__(self, violations: list[tuple[str, str]]):
        self.violations = violations
        rendered = "; ".join(f"{code}: {detail}" for code, detail in violations)
        super().__init__(f"invalid Hermes configuration ({rendered})")


@dataclass(frozen=True)
class HermesRuntimeConfig:
    """The validated Hermes configuration handed to the (future) runtime
    adapter. Every field is guaranteed present, finite, and positive."""

    commit_pin: str
    plugin_path: Path
    hermes_home: Path
    max_iterations: int
    max_execution_seconds: float
    max_tool_calls: int
    max_tool_calls_per_capability: int
    max_generation_budget_usd: float
    max_context_tokens: int
    max_blocked_requests: int


def _check_pin(settings: Settings, violations: list[tuple[str, str]]) -> str | None:
    pin = (settings.hermes_commit_pin or "").strip()
    if not pin:
        violations.append(
            ("pin_missing", "hermes_commit_pin is required when hermes_enabled=true")
        )
        return None
    if len(pin) != _COMMIT_HEX_LENGTH or any(c not in _COMMIT_HEX_CHARS for c in pin):
        violations.append(
            (
                "pin_malformed",
                "hermes_commit_pin must be a 40-character lowercase hex git commit SHA",
            )
        )
        return None
    if pin != HERMES_COMMIT_PIN:
        violations.append(
            (
                "pin_not_approved",
                f"hermes_commit_pin {pin} is not the approved pin; changing it "
                "requires spec §15 approval (source verification + runtime "
                "security verification + architecture review + explicit approval)",
            )
        )
        return None
    return pin


def _check_plugin_path(settings: Settings, violations: list[tuple[str, str]]) -> Path | None:
    raw = (settings.hermes_plugin_path or "").strip()
    if not raw:
        violations.append(
            ("plugin_path_missing", "hermes_plugin_path is required when hermes_enabled=true")
        )
        return None
    path = Path(raw)
    if not path.is_absolute():
        violations.append(
            ("plugin_path_not_absolute", "hermes_plugin_path must be an absolute path")
        )
        return None
    if not path.is_dir():
        violations.append(
            (
                "plugin_path_invalid",
                f"hermes_plugin_path {raw} must be an existing directory holding "
                "the AryaOS policy plugin",
            )
        )
        return None
    return path


def _check_hermes_home(settings: Settings, violations: list[tuple[str, str]]) -> Path | None:
    raw = (settings.hermes_home or "").strip()
    if not raw:
        violations.append(
            ("home_missing", "hermes_home is required when hermes_enabled=true")
        )
        return None
    path = Path(raw)
    if not path.is_absolute():
        violations.append(
            ("home_not_absolute", "hermes_home must be an absolute path")
        )
        return None
    resolved = path.resolve()
    user_home = Path.home()
    if user_home.is_relative_to(resolved):
        violations.append(
            (
                "home_invalid",
                f"hermes_home {raw} must not be the user home directory or contain it "
                f"(got {resolved})",
            )
        )
        return None
    if _ARYA_OS_ROOT.is_relative_to(resolved):
        violations.append(
            (
                "home_invalid",
                f"hermes_home {raw} must not be the AryaOS repository root or contain it "
                f"(got {resolved})",
            )
        )
        return None
    return resolved


def _check_limits(settings: Settings, violations: list[tuple[str, str]]) -> None:
    for field in _INT_LIMIT_FIELDS:
        value = getattr(settings, field)
        if value is None:
            violations.append(
                (f"{field}_missing", f"{field} must be set when hermes_enabled=true (unbounded is not permitted)")
            )
        elif value <= 0:
            violations.append(
                (f"{field}_not_positive", f"{field} must be a positive integer, got {value}")
            )

    for field in _FLOAT_LIMIT_FIELDS:
        value = getattr(settings, field)
        if value is None:
            violations.append(
                (f"{field}_missing", f"{field} must be set when hermes_enabled=true (unbounded is not permitted)")
            )
        elif not math.isfinite(value):
            violations.append(
                (f"{field}_not_finite", f"{field} must be a finite number, got {value}")
            )
        elif value <= 0:
            violations.append(
                (f"{field}_not_positive", f"{field} must be a positive number, got {value}")
            )

    if (
        settings.hermes_max_tool_calls_per_capability is not None
        and settings.hermes_max_tool_calls is not None
        and settings.hermes_max_tool_calls_per_capability > settings.hermes_max_tool_calls
    ):
        violations.append(
            (
                "per_capability_exceeds_total",
                "hermes_max_tool_calls_per_capability must not exceed hermes_max_tool_calls",
            )
        )


def get_validated_hermes_config(settings: Settings) -> HermesRuntimeConfig | None:
    """Validate the Hermes settings fail-closed.

    Returns None when Hermes is disabled (the only no-Hermes state).
    Returns a HermesRuntimeConfig when every value is valid.
    Raises HermesConfigError listing every violation otherwise.
    """
    if not settings.hermes_enabled:
        return None

    violations: list[tuple[str, str]] = []
    pin = _check_pin(settings, violations)
    plugin_path = _check_plugin_path(settings, violations)
    hermes_home = _check_hermes_home(settings, violations)
    _check_limits(settings, violations)

    if violations:
        raise HermesConfigError(violations)

    assert pin is not None and plugin_path is not None and hermes_home is not None
    return HermesRuntimeConfig(
        commit_pin=pin,
        plugin_path=plugin_path,
        hermes_home=hermes_home,
        max_iterations=settings.hermes_max_iterations,
        max_execution_seconds=settings.hermes_max_execution_seconds,
        max_tool_calls=settings.hermes_max_tool_calls,
        max_tool_calls_per_capability=settings.hermes_max_tool_calls_per_capability,
        max_generation_budget_usd=settings.hermes_max_generation_budget_usd,
        max_context_tokens=settings.hermes_max_context_tokens,
        max_blocked_requests=settings.hermes_max_blocked_requests,
    )
