"""Unit tests for the §5.5 pre-import environment scrub (V2).

Spec: docs/architecture/HERMES_INTEGRATION_SPEC.md — §5.5, §16/T14
("dangerous env vars ... are absent from the environment seen by the
Hermes import; scrub step is testable in isolation").

These tests exercise ONLY the AryaOS-owned scrub step against ordinary
dicts (and, for the default-path test, the real process environment via
monkeypatch). Hermes itself is not imported, faked, or required.
"""
import pytest

from app.hermes.env_scrub import (
    HERMES_ENV_SCRUB_PREFIXES,
    HERMES_EXTERNAL_ENV_SCRUB,
    HERMES_NAMESPACED_ENV_KNOWN,
    HermesEnvScrubError,
    get_hermes_scrub_names,
    scrub_hermes_environment,
)

# AryaOS reads these in-process (provider stack / settings / storage) and
# the spec §5.5 scrub must never touch them (see env_scrub module docstring
# "Deliberately NOT scrubbed").
ARYA_OS_PROCESS_ENV_MUST_SURVIVE = (
    "PATH",
    "HOME",
    "OPENAI_API_KEY",
    "OPENROUTER_API_KEY",
    "ANTHROPIC_API_KEY",
    "FAL_KEY",
    "GEMINI_API_KEY",
    "TOGETHER_API_KEY",
    "REPLICATE_API_KEY",
    "RUNPOD_API_KEY",
    "ELEVENLABS_API_KEY",
    "TELEGRAM_BOT_TOKEN",
    "DATABASE_URL",
    "REDIS_URL",
    "STORAGE_BACKEND",
    "ARYA_API_KEY",
    "SSL_CERT_FILE",
    "HTTP_PROXY",
)


# ---------------------------------------------------------------------------
# 1. Frozen-rule integrity
# ---------------------------------------------------------------------------

def test_known_namespaced_names_all_match_prefix_rule():
    """The enumerated audit inventory must be a subset of the namespace
    rule (the prefix rule is what enforces the scrub)."""
    assert HERMES_NAMESPACED_ENV_KNOWN
    assert all(
        name.startswith(HERMES_ENV_SCRUB_PREFIXES)
        for name in HERMES_NAMESPACED_ENV_KNOWN
    )


def test_external_names_are_not_in_hermes_namespace():
    """Layer 2 must contain only non-Hermes-namespace names (namespace names
    belong to the prefix rule / inventory)."""
    assert HERMES_EXTERNAL_ENV_SCRUB
    assert not any(
        name.startswith(HERMES_ENV_SCRUB_PREFIXES) for name in HERMES_EXTERNAL_ENV_SCRUB
    )


def test_external_names_do_not_touch_aryaos_process_env():
    """The exact-name scrub list must never contain a variable AryaOS itself
    needs in-process (verified against .env.example / backend/app usage at
    implementation time; frozen here so a future edit fails loudly)."""
    assert not (HERMES_EXTERNAL_ENV_SCRUB & set(ARYA_OS_PROCESS_ENV_MUST_SURVIVE))


def test_dynamic_indirection_names_are_covered():
    """Names read via dynamic indirection at the pin (invisible to static
    enumeration) are covered by the prefix rule."""
    dynamic_names = {
        "HERMES_CRON_INFLIGHT_MAX_MINUTES",
        "HERMES_CRON_MAX_PARALLEL",
        "HERMES_REAL_HOME",
        "HERMES_ACP_AUTO_APPROVE",
    }
    env = {name: "1" for name in dynamic_names}
    assert set(get_hermes_scrub_names(env)) == dynamic_names


# ---------------------------------------------------------------------------
# 2. Scrub behavior on an isolated dict (testable in isolation, T14)
# ---------------------------------------------------------------------------

def test_scrub_removes_by_deletion_not_override():
    env = {
        "HERMES_YOLO_MODE": "1",
        "GATEWAY_ALLOW_ALL_USERS": "1",
        "PATH": "/usr/bin",
    }
    scrub_hermes_environment(env)
    assert "HERMES_YOLO_MODE" not in env  # absent, not overridden to ""
    assert "GATEWAY_ALLOW_ALL_USERS" not in env
    assert env["PATH"] == "/usr/bin"


def test_scrub_covers_representative_namespaced_and_external_vars():
    """One representative per §5.5 category, straight from the enumeration:
    home (HERMES_HOME), gateway (GATEWAY_*), cron (_HERMES_*), approval
    bypass (HERMES_YOLO_MODE), tools/MCP (TERMINAL_*/BROWSER_*,
    HERMES_OPTIONAL_MCPS), credentials (SUDO_PASSWORD)."""
    env = {
        "HERMES_HOME": "/elsewhere",
        "HERMES_OPTIONAL_MCPS": "everything",
        "HERMES_YOLO_MODE": "1",
        "HERMES_GATEWAY_SESSION": "x",
        "_HERMES_CRON_EXTERNAL_WORKER": "1",
        "GATEWAY_ALLOW_ALL_USERS": "1",
        "API_SERVER_ENABLED": "true",
        "TERMINAL_CWD": "/",
        "TERMINAL_ENV": "LEAK=1",
        "BROWSER_CDP_URL": "http://127.0.0.1:9222",
        "SUDO_PASSWORD": "secret",
        "TIRITH_BIN": "/tmp/evil",
    }
    result = scrub_hermes_environment(env)
    assert env == {}
    assert result.removed == tuple(sorted(result.removed))
    assert set(result.removed) == {
        "HERMES_HOME",
        "HERMES_OPTIONAL_MCPS",
        "HERMES_YOLO_MODE",
        "HERMES_GATEWAY_SESSION",
        "_HERMES_CRON_EXTERNAL_WORKER",
        "GATEWAY_ALLOW_ALL_USERS",
        "API_SERVER_ENABLED",
        "TERMINAL_CWD",
        "TERMINAL_ENV",
        "BROWSER_CDP_URL",
        "SUDO_PASSWORD",
        "TIRITH_BIN",
    }


def test_scrub_prefix_rule_covers_unknown_future_hermes_vars():
    env = {"HERMES_SOME_FUTURE_FLAG": "1", "_HERMES_PRIVATE": "1"}
    result = scrub_hermes_environment(env)
    assert set(result.removed) == {"HERMES_SOME_FUTURE_FLAG", "_HERMES_PRIVATE"}


def test_scrub_preserves_unrelated_and_aryaos_vars():
    keep = {name: "value" for name in ARYA_OS_PROCESS_ENV_MUST_SURVIVE}
    keep.update({"APP_ENV": "dev", "SOME_TOOL": "1"})
    env = dict(keep)
    env["HERMES_SESSION_KEY"] = "k"
    scrub_hermes_environment(env)
    assert {k: v for k, v in env.items() if k in keep} == keep


def test_scrub_is_deterministic_and_idempotent():
    env = {"HERMES_B": "1", "HERMES_A": "1", "SUDO_PASSWORD": "x"}
    first = scrub_hermes_environment(env)
    assert first.removed == ("HERMES_A", "HERMES_B", "SUDO_PASSWORD")
    second = scrub_hermes_environment(env)
    assert second.removed == ()


def test_scrub_result_and_errors_carry_names_not_values():
    env = {"SUDO_PASSWORD": "top-secret-value", "HERMES_HOME": "/secret/path"}
    result = scrub_hermes_environment(env)
    rendered = repr(result)
    assert "top-secret-value" not in rendered
    assert "/secret/path" not in rendered


def test_get_scrub_names_is_pure_over_mapping():
    env = {"HERMES_A": "1", "KEEP": "1"}
    names = get_hermes_scrub_names(env)
    assert names == ("HERMES_A",)
    assert env == {"HERMES_A": "1", "KEEP": "1"}  # untouched


# ---------------------------------------------------------------------------
# 3. Fail-closed behavior (§5.5: refuse to import Hermes)
# ---------------------------------------------------------------------------

def test_scrub_fails_closed_when_removal_is_ineffective():
    class RefusesDeletion(dict):
        def __delitem__(self, key):
            super().__delitem__(key)
            self[key] = "resurrected"  # simulates a mapping that ignores del

    env = RefusesDeletion({"HERMES_YOLO_MODE": "SECRET-VALUE"})
    with pytest.raises(HermesEnvScrubError) as exc_info:
        scrub_hermes_environment(env)
    codes = {code for code, _ in exc_info.value.violations}
    assert codes == {"scrub_failed"}
    # Error details contain the variable NAME only, never the value.
    assert "HERMES_YOLO_MODE" in str(exc_info.value)
    assert "SECRET-VALUE" not in str(exc_info.value)


# ---------------------------------------------------------------------------
# 4. Default target: the real process environment
# ---------------------------------------------------------------------------

def test_scrub_defaults_to_process_environ(monkeypatch):
    monkeypatch.setenv("HERMES_YOLO_MODE", "1")
    monkeypatch.setenv("ARYA_API_KEY", "keep")
    result = scrub_hermes_environment()
    assert "HERMES_YOLO_MODE" in result.removed
    import os

    assert "HERMES_YOLO_MODE" not in os.environ
    assert os.environ["ARYA_API_KEY"] == "keep"


def test_scrub_module_does_not_import_hermes():
    """The scrub step must be usable without Hermes present: importing it
    must not pull in any vendored Hermes module. Checked in a fresh
    subprocess: the runtime integration tests legitimately import Hermes
    into the shared pytest process, so a process-global sys.modules scan
    would test file ordering, not this module."""
    import subprocess
    import sys as _sys
    from pathlib import Path

    backend_dir = Path(__file__).resolve().parents[1]
    code = (
        "import sys\n"
        f"sys.path.insert(0, {str(backend_dir)!r})\n"
        "import app.hermes.env_scrub\n"
        "assert not any(\n"
        "    mod == 'agent' or mod.startswith(('agent.', 'hermes', 'hermes_'))\n"
        "    for mod in sys.modules), 'env_scrub import pulled in Hermes'\n"
    )
    result = subprocess.run(
        [_sys.executable, "-c", code], capture_output=True, text=True, timeout=60
    )
    assert result.returncode == 0, result.stderr
