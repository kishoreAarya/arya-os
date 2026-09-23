"""Unit tests for Hermes runtime configuration validation (Slice 1).

Spec: docs/architecture/HERMES_INTEGRATION_SPEC.md §2 (pin), §5
(configuration), §12 (resource limits).

These tests cover ONLY the AryaOS-owned settings and the fail-closed
validation layer. They do not import, fake, or require Hermes.
"""
import os
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.core.config import HERMES_COMMIT_PIN, Settings
from app.hermes.config import (
    HermesConfigError,
    HermesRuntimeConfig,
    get_validated_hermes_config,
)

# backend/tests/test_hermes_config_unit.py -> parents[2] is the AryaOS repo root.
REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(autouse=True)
def _clean_hermes_env(monkeypatch):
    """Tests must not be affected by HERMES_* variables in the real
    environment; validation behavior is tested via explicit Settings kwargs."""
    for name in list(os.environ):
        if name.upper().startswith("HERMES_"):
            monkeypatch.delenv(name, raising=False)


@pytest.fixture(scope="module")
def plugin_dir(tmp_path_factory) -> Path:
    return tmp_path_factory.mktemp("hermes_plugins")


@pytest.fixture(scope="module")
def home_dir(tmp_path_factory) -> Path:
    return tmp_path_factory.mktemp("hermes_home")


def _valid_settings(plugin_dir: Path, home_dir: Path, **overrides) -> Settings:
    base = dict(
        hermes_enabled=True,
        hermes_commit_pin=HERMES_COMMIT_PIN,
        hermes_plugin_path=str(plugin_dir),
        hermes_home=str(home_dir),
        hermes_max_iterations=50,
        hermes_max_execution_seconds=900.0,
        hermes_max_tool_calls=100,
        hermes_max_tool_calls_per_capability=25,
        hermes_max_generation_budget_usd=5.0,
        hermes_max_context_tokens=32_000,
        hermes_max_blocked_requests=5,
    )
    base.update(overrides)
    return Settings(**base)


def _codes(exc_info: pytest.ExceptionInfo[HermesConfigError]) -> set[str]:
    return {code for code, _ in exc_info.value.violations}


# ---------------------------------------------------------------------------
# 1. Valid configuration accepted
# ---------------------------------------------------------------------------

def test_valid_configuration_accepted(plugin_dir, home_dir):
    config = get_validated_hermes_config(_valid_settings(plugin_dir, home_dir))
    assert isinstance(config, HermesRuntimeConfig)
    assert config.commit_pin == HERMES_COMMIT_PIN
    assert config.plugin_path == plugin_dir
    assert config.hermes_home == home_dir
    assert config.max_iterations == 50
    assert config.max_execution_seconds == 900.0
    assert config.max_tool_calls == 100
    assert config.max_tool_calls_per_capability == 25
    assert config.max_generation_budget_usd == 5.0
    assert config.max_context_tokens == 32_000
    assert config.max_blocked_requests == 5


def test_home_inside_repo_data_directory_is_allowed(plugin_dir):
    """Spec §5.2: HERMES_HOME under the AryaOS data directory is sanctioned
    ('e.g. under the AryaOS data directory'). Only the repo root itself
    (or a container of it) is rejected."""
    settings = _valid_settings(
        plugin_dir,
        REPO_ROOT / "data" / "hermes-home",
    )
    config = get_validated_hermes_config(settings)
    assert config.hermes_home == (REPO_ROOT / "data" / "hermes-home").resolve()


# ---------------------------------------------------------------------------
# 2. Disabled -> explicit None (inert settings, no validation errors)
# ---------------------------------------------------------------------------

def test_disabled_returns_none():
    assert get_validated_hermes_config(Settings(hermes_enabled=False)) is None


def test_disabled_with_leftover_settings_is_inert():
    settings = Settings(
        hermes_enabled=False,
        hermes_commit_pin="not-a-pin",
        hermes_max_iterations=-1,
    )
    assert get_validated_hermes_config(settings) is None


def test_default_settings_keep_hermes_disabled_and_pinned():
    settings = Settings()
    assert settings.hermes_enabled is False
    assert settings.hermes_commit_pin == HERMES_COMMIT_PIN


# ---------------------------------------------------------------------------
# 3. Commit pin validation
# ---------------------------------------------------------------------------

def test_missing_pin_rejected(plugin_dir, home_dir):
    with pytest.raises(HermesConfigError) as exc_info:
        get_validated_hermes_config(_valid_settings(plugin_dir, home_dir, hermes_commit_pin=""))
    assert _codes(exc_info) == {"pin_missing"}


@pytest.mark.parametrize(
    "bad_pin",
    [
        "c0d729",  # too short
        "C0D7294769A38C17CEAE51D8F7995E66E1DAE27",  # uppercase
        "c0d7294769a38c17ceae51d8f7995e66e1dcae2g",  # non-hex char
    ],
)
def test_malformed_pin_rejected(plugin_dir, home_dir, bad_pin):
    with pytest.raises(HermesConfigError) as exc_info:
        get_validated_hermes_config(_valid_settings(plugin_dir, home_dir, hermes_commit_pin=bad_pin))
    assert _codes(exc_info) == {"pin_malformed"}


def test_unapproved_pin_rejected(plugin_dir, home_dir):
    other_sha = "0" * 40
    with pytest.raises(HermesConfigError) as exc_info:
        get_validated_hermes_config(_valid_settings(plugin_dir, home_dir, hermes_commit_pin=other_sha))
    assert _codes(exc_info) == {"pin_not_approved"}


# ---------------------------------------------------------------------------
# 4. Resource limit validation
# ---------------------------------------------------------------------------

def test_missing_limits_rejected(plugin_dir, home_dir):
    settings = _valid_settings(
        plugin_dir,
        home_dir,
        hermes_max_iterations=None,
        hermes_max_execution_seconds=None,
        hermes_max_tool_calls=None,
        hermes_max_tool_calls_per_capability=None,
        hermes_max_generation_budget_usd=None,
        hermes_max_context_tokens=None,
        hermes_max_blocked_requests=None,
    )
    with pytest.raises(HermesConfigError) as exc_info:
        get_validated_hermes_config(settings)
    assert _codes(exc_info) == {
        "hermes_max_iterations_missing",
        "hermes_max_execution_seconds_missing",
        "hermes_max_tool_calls_missing",
        "hermes_max_tool_calls_per_capability_missing",
        "hermes_max_generation_budget_usd_missing",
        "hermes_max_context_tokens_missing",
        "hermes_max_blocked_requests_missing",
    }


def test_zero_and_negative_limits_rejected(plugin_dir, home_dir):
    settings = _valid_settings(
        plugin_dir,
        home_dir,
        hermes_max_iterations=0,
        hermes_max_execution_seconds=-1.0,
        hermes_max_tool_calls=0,
        hermes_max_tool_calls_per_capability=0,
        hermes_max_blocked_requests=0,
    )
    with pytest.raises(HermesConfigError) as exc_info:
        get_validated_hermes_config(settings)
    assert _codes(exc_info) == {
        "hermes_max_iterations_not_positive",
        "hermes_max_execution_seconds_not_positive",
        "hermes_max_tool_calls_not_positive",
        "hermes_max_tool_calls_per_capability_not_positive",
        "hermes_max_blocked_requests_not_positive",
    }


def test_non_finite_float_limits_rejected(plugin_dir, home_dir):
    settings = _valid_settings(
        plugin_dir,
        home_dir,
        hermes_max_execution_seconds=float("inf"),
        hermes_max_generation_budget_usd=float("nan"),
    )
    with pytest.raises(HermesConfigError) as exc_info:
        get_validated_hermes_config(settings)
    assert _codes(exc_info) == {
        "hermes_max_execution_seconds_not_finite",
        "hermes_max_generation_budget_usd_not_finite",
    }


def test_per_capability_exceeding_total_rejected(plugin_dir, home_dir):
    settings = _valid_settings(
        plugin_dir,
        home_dir,
        hermes_max_tool_calls=10,
        hermes_max_tool_calls_per_capability=11,
    )
    with pytest.raises(HermesConfigError) as exc_info:
        get_validated_hermes_config(settings)
    assert "per_capability_exceeds_total" in _codes(exc_info)


NUMERIC_LIMIT_FIELDS = (
    "hermes_max_iterations",
    "hermes_max_execution_seconds",
    "hermes_max_tool_calls",
    "hermes_max_tool_calls_per_capability",
    "hermes_max_generation_budget_usd",
    "hermes_max_context_tokens",
    "hermes_max_blocked_requests",
)


@pytest.mark.parametrize("field", NUMERIC_LIMIT_FIELDS)
@pytest.mark.parametrize("value", [True, False])
def test_boolean_values_rejected_for_numeric_limits(plugin_dir, home_dir, field, value):
    """bool is a subclass of int; lax coercion True -> 1 would silently turn a
    flag into a limit. The settings layer must reject it at parse time."""
    with pytest.raises(ValidationError):
        _valid_settings(plugin_dir, home_dir, **{field: value})


def test_env_string_values_still_parse(monkeypatch):
    """Env vars arrive as strings; numeric strings must keep parsing (this is
    the legitimate configuration channel — rejecting them would break .env)."""
    monkeypatch.setenv("HERMES_MAX_ITERATIONS", "50")
    monkeypatch.setenv("HERMES_MAX_EXECUTION_SECONDS", "900")
    monkeypatch.setenv("HERMES_MAX_GENERATION_BUDGET_USD", "5.5")
    settings = Settings()
    assert settings.hermes_max_iterations == 50
    assert settings.hermes_max_execution_seconds == 900.0
    assert settings.hermes_max_generation_budget_usd == 5.5


@pytest.mark.parametrize(
    ("env_name", "raw"),
    [
        ("HERMES_MAX_ITERATIONS", "true"),
        ("HERMES_MAX_GENERATION_BUDGET_USD", "false"),
    ],
)
def test_env_boolean_strings_rejected(monkeypatch, env_name, raw):
    monkeypatch.setenv(env_name, raw)
    with pytest.raises(ValidationError):
        Settings()


# ---------------------------------------------------------------------------
# 5. Plugin path validation
# ---------------------------------------------------------------------------

def test_missing_plugin_path_rejected(home_dir):
    with pytest.raises(HermesConfigError) as exc_info:
        get_validated_hermes_config(_valid_settings(Path("/nonexistent"), home_dir, hermes_plugin_path=None))
    assert _codes(exc_info) == {"plugin_path_missing"}


def test_empty_plugin_path_rejected(home_dir):
    with pytest.raises(HermesConfigError) as exc_info:
        get_validated_hermes_config(_valid_settings(Path("/nonexistent"), home_dir, hermes_plugin_path="  "))
    assert _codes(exc_info) == {"plugin_path_missing"}


def test_relative_plugin_path_rejected(home_dir):
    with pytest.raises(HermesConfigError) as exc_info:
        get_validated_hermes_config(
            _valid_settings(Path("/nonexistent"), home_dir, hermes_plugin_path="plugins/hermes-policy")
        )
    assert _codes(exc_info) == {"plugin_path_not_absolute"}


def test_nonexistent_plugin_path_rejected(home_dir, tmp_path):
    missing = tmp_path / "no-such-plugin-dir"
    with pytest.raises(HermesConfigError) as exc_info:
        get_validated_hermes_config(_valid_settings(missing, home_dir, hermes_plugin_path=str(missing)))
    assert _codes(exc_info) == {"plugin_path_invalid"}


# ---------------------------------------------------------------------------
# 6. HERMES_HOME validation
# ---------------------------------------------------------------------------

def test_missing_home_rejected(plugin_dir):
    with pytest.raises(HermesConfigError) as exc_info:
        get_validated_hermes_config(_valid_settings(plugin_dir, Path("/nonexistent"), hermes_home=None))
    assert _codes(exc_info) == {"home_missing"}


def test_relative_home_rejected(plugin_dir):
    with pytest.raises(HermesConfigError) as exc_info:
        get_validated_hermes_config(
            _valid_settings(plugin_dir, Path("/nonexistent"), hermes_home="./hermes-home")
        )
    assert _codes(exc_info) == {"home_not_absolute"}


def test_user_home_rejected(plugin_dir):
    with pytest.raises(HermesConfigError) as exc_info:
        get_validated_hermes_config(_valid_settings(plugin_dir, Path("/nonexistent"), hermes_home=str(Path.home())))
    assert _codes(exc_info) == {"home_invalid"}


def test_filesystem_root_rejected(plugin_dir):
    with pytest.raises(HermesConfigError) as exc_info:
        get_validated_hermes_config(_valid_settings(plugin_dir, Path("/nonexistent"), hermes_home="/"))
    assert _codes(exc_info) == {"home_invalid"}


def test_repo_root_rejected(plugin_dir):
    with pytest.raises(HermesConfigError) as exc_info:
        get_validated_hermes_config(_valid_settings(plugin_dir, Path("/nonexistent"), hermes_home=str(REPO_ROOT)))
    assert _codes(exc_info) == {"home_invalid"}


# ---------------------------------------------------------------------------
# 7. All violations collected, none silently corrected
# ---------------------------------------------------------------------------

def test_multiple_violations_all_reported(home_dir, tmp_path):
    settings = _valid_settings(
        tmp_path / "missing-plugin-dir",
        home_dir,
        hermes_commit_pin="bad",
        hermes_plugin_path=str(tmp_path / "missing-plugin-dir"),
        hermes_max_iterations=0,
    )
    with pytest.raises(HermesConfigError) as exc_info:
        get_validated_hermes_config(settings)
    codes = _codes(exc_info)
    assert {"pin_malformed", "plugin_path_invalid", "hermes_max_iterations_not_positive"}.issubset(codes)
