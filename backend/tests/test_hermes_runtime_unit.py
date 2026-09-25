"""Unit tests for the §3 runtime adapter (V2), slice 1.

Spec: docs/architecture/HERMES_INTEGRATION_SPEC.md — §3, §4.3, §5.2,
§5.5, §12, §16.

Two profiles in one file:

- Unit tests: ordering, scrub verification, config.yaml generation,
  runtime-owned environment, failure-before-import, cleanup-on-failure,
  watchdog, and module-import purity. No Hermes required.
- Integration tests: run the REAL pinned Hermes through
  run_hermes_job(...) construction-only (task_message=None; no model
  call). Per §16, a missing pinned Hermes source is an explicit
  integration-environment FAILURE, never a silent skip.
"""
import importlib.util
import os
import sys
import time
from pathlib import Path

import pytest

from app.core.config import HERMES_COMMIT_PIN, Settings
from app.hermes.policy import AuthorizationContext
from app.hermes.runtime import (
    HermesJobRequest,
    apply_runtime_environment,
    clear_runtime_environment,
    create_job_home,
    render_config_yaml,
    run_hermes_job,
    run_with_watchdog,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
PLUGIN_PATH = REPO_ROOT / "backend" / "app" / "hermes" / "plugins"

CONTEXT = AuthorizationContext(
    user_id="u", project_id="p", job_id="j", workflow_run_id="w", agent_id="a", lineage_id="l"
)

HERMES_AVAILABLE = importlib.util.find_spec("run_agent") is not None


def _valid_settings(tmp_path: Path) -> Settings:
    return Settings(
        hermes_enabled=True,
        hermes_commit_pin=HERMES_COMMIT_PIN,
        hermes_plugin_path=str(PLUGIN_PATH),
        hermes_home=str(tmp_path / "hermes-root"),
        hermes_max_iterations=5,
        hermes_max_execution_seconds=10.0,
        hermes_max_tool_calls=10,
        hermes_max_tool_calls_per_capability=5,
        hermes_max_generation_budget_usd=1.0,
        hermes_max_context_tokens=8_000,
        hermes_max_blocked_requests=3,
    )


def _request(job_id: str = "job-1", task_message: str | None = None) -> HermesJobRequest:
    return HermesJobRequest(
        job_id=job_id,
        task_message=task_message,
        authorization_context=CONTEXT,
        provider="openai",
        base_url="http://127.0.0.1:9/v1",
        api_key="aryaos-explicit-test-key",
        model="aryaos-test-model",
    )


@pytest.fixture(autouse=True)
def _clean_hermes_env(monkeypatch):
    for name in list(os.environ):
        if name.upper().startswith("HERMES_") or name.startswith("LANGFUSE_"):
            monkeypatch.delenv(name, raising=False)


# ---------------------------------------------------------------------------
# 1. Module-import purity: no Hermes at import time
# ---------------------------------------------------------------------------

def test_runtime_module_never_imports_hermes():
    """Importing app.hermes.runtime must not import Hermes (fresh process:
    the runtime integration tests in THIS file legitimately import Hermes,
    so a process-global sys.modules scan would test ordering, not purity)."""
    import subprocess
    import sys as _sys
    from pathlib import Path

    backend_dir = Path(__file__).resolve().parents[1]
    code = (
        "import sys\n"
        f"sys.path.insert(0, {str(backend_dir)!r})\n"
        "import app.hermes.runtime\n"
        "assert not any(\n"
        "    m == 'run_agent' or m.startswith(('agent.', 'hermes_cli', 'model_tools', 'toolsets'))\n"
        "    for m in sys.modules), 'runtime module imported Hermes at import time'\n"
    )
    result = subprocess.run(
        [_sys.executable, "-c", code], capture_output=True, text=True, timeout=60
    )
    assert result.returncode == 0, result.stderr


def test_plugin_adapter_files_exist():
    assert (PLUGIN_PATH / "aryaos-policy" / "__init__.py").is_file()
    assert (PLUGIN_PATH / "aryaos-policy" / "plugin.yaml").is_file()


# ---------------------------------------------------------------------------
# 2. config.yaml generation (exact minimal surface)
# ---------------------------------------------------------------------------

def test_config_yaml_exact_surface():
    text = render_config_yaml()
    assert text == (
        "plugins:\n"
        "  enabled:\n"
        "  - aryaos-policy\n"
        "  disabled: []\n"
        "security:\n"
        "  tirith_fail_open: false\n"
        "tools:\n"
        "  tool_search:\n"
        '    enabled: "off"\n'
    )


def test_config_yaml_parses_to_expected_mapping():
    import yaml

    parsed = yaml.safe_load(render_config_yaml())
    assert parsed == {
        "plugins": {"enabled": ["aryaos-policy"], "disabled": []},
        "security": {"tirith_fail_open": False},
        "tools": {"tool_search": {"enabled": "off"}},
    }
    # The disablement is the STRING "off" (unquoted YAML 1.1 'off' would be
    # boolean False; tools/tool_search._tri_state handles both, but the
    # generated text is pinned to the explicit string).
    assert parsed["tools"]["tool_search"]["enabled"] == "off"
    # Forbidden surfaces are absent, not merely false.
    text = render_config_yaml()
    for forbidden in ("mcp", "gateway", "cron", "terminal", "browser", "memory", "model"):
        assert forbidden not in text


# ---------------------------------------------------------------------------
# 3. Per-job home creation
# ---------------------------------------------------------------------------

def test_job_home_fresh_and_scoped(tmp_path):
    home = create_job_home(tmp_path, "job-42")
    assert home == tmp_path / "jobs" / "job-42"
    assert home.is_dir()
    assert (home.stat().st_mode & 0o777) == 0o700


def test_job_home_refuses_non_fresh(tmp_path):
    home = create_job_home(tmp_path, "job-1")
    (home / "leftover.env").write_text("HERMES_YOLO_MODE=1\n")
    with pytest.raises(Exception) as exc_info:
        create_job_home(tmp_path, "job-1")
    assert "job_home_not_fresh" in str(exc_info.value) or exc_info.value.code == "job_home_not_fresh"


def test_job_home_rejects_path_traversal(tmp_path):
    for bad in ("../escape", "a/b", "", "a.b"):
        with pytest.raises(Exception):
            create_job_home(tmp_path, bad)


# ---------------------------------------------------------------------------
# 4. Runtime-owned environment boundary
# ---------------------------------------------------------------------------

def test_apply_runtime_environment_sets_only_owned_names(tmp_path):
    touched = apply_runtime_environment(tmp_path / "home", PLUGIN_PATH)
    assert sorted(touched) == ["HERMES_BUNDLED_PLUGINS", "HERMES_HOME"]
    assert os.environ["HERMES_HOME"] == str(tmp_path / "home")
    assert os.environ["HERMES_BUNDLED_PLUGINS"] == str(PLUGIN_PATH)
    clear_runtime_environment(touched)
    assert "HERMES_HOME" not in os.environ
    assert "HERMES_BUNDLED_PLUGINS" not in os.environ


def test_apply_runtime_environment_removes_langfuse_escape_keys(monkeypatch, tmp_path):
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "x")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "y")
    apply_runtime_environment(tmp_path / "home", PLUGIN_PATH)
    assert "LANGFUSE_PUBLIC_KEY" not in os.environ
    assert "LANGFUSE_SECRET_KEY" not in os.environ


def test_apply_runtime_environment_replaces_inherited_hermes_home(monkeypatch, tmp_path):
    # Post-scrub this cannot happen; if it did, the runtime value must win.
    monkeypatch.setenv("HERMES_HOME", "/inherited")
    apply_runtime_environment(tmp_path / "job", PLUGIN_PATH)
    assert os.environ["HERMES_HOME"] == str(tmp_path / "job")
    clear_runtime_environment(["HERMES_HOME", "HERMES_BUNDLED_PLUGINS"])


# ---------------------------------------------------------------------------
# 5. Watchdog (§12: AryaOS owns the wall clock)
# ---------------------------------------------------------------------------

def test_watchdog_completes_fast_callable():
    status, value, exc = run_with_watchdog(lambda: "ok", 5.0)
    assert (status, value, exc) == ("completed", "ok", None)


def test_watchdog_times_out_blocking_callable():
    def block():
        time.sleep(30)

    start = time.monotonic()
    status, value, exc = run_with_watchdog(block, 0.2)
    assert time.monotonic() - start < 5.0
    assert (status, value, exc) == ("timeout", None, None)


def test_watchdog_reports_error():
    def boom():
        raise ValueError("kaboom")

    status, value, exc = run_with_watchdog(boom, 5.0)
    assert status == "error" and value is None and isinstance(exc, ValueError)


# ---------------------------------------------------------------------------
# 6. Failure BEFORE Hermes import (fail closed, no import side effects)
# ---------------------------------------------------------------------------

def _run_isolated(code_body: str, settings: Settings) -> str:
    """Run a fresh-interpreter scenario and return its stderr (empty on
    success). Used for 'fails BEFORE Hermes import' proofs: other test
    files legitimately import Hermes into the shared pytest process, so
    'run_agent not in sys.modules' is only observable in a clean process."""
    import subprocess
    import sys as _sys
    from pathlib import Path

    backend_dir = Path(__file__).resolve().parents[1]
    code = (
        "import sys\n"
        f"sys.path.insert(0, {str(backend_dir)!r})\n"
        "from pathlib import Path\n"
        "import app.hermes.runtime as runtime\n"
        "from app.core.config import Settings\n"
        f"settings = Settings(**{dict(settings.model_dump())!r})\n"
        "request = runtime.HermesJobRequest(\n"
        "    job_id='iso-1', task_message=None,\n"
        "    authorization_context=runtime.AuthorizationContext(\n"
        "        user_id='u', project_id='p', job_id='j', workflow_run_id='w', agent_id='a', lineage_id='l'),\n"
        "    provider='openai', base_url='http://127.0.0.1:9/v1',\n"
        "    api_key='k', model='m')\n"
        f"{code_body}\n"
        "assert 'run_agent' not in sys.modules, 'Hermes was imported despite the gate'\n"
    )
    result = subprocess.run(
        [_sys.executable, "-c", code], capture_output=True, text=True, timeout=120
    )
    return result.stderr


def test_invalid_settings_fail_before_import(tmp_path):
    bad = Settings(hermes_enabled=True)  # missing limits/plugin path/home
    result = run_hermes_job(_request(), settings=bad)
    assert result.status == "failed"
    assert result.error_code == "settings_invalid"
    assert _run_isolated("", bad) == ""


def test_missing_plugin_on_disk_fails_before_import(tmp_path):
    settings = _valid_settings(tmp_path)
    settings = settings.model_copy(update={"hermes_plugin_path": str(tmp_path / "nope")})
    result = run_hermes_job(_request(), settings=settings)
    assert result.status == "failed"
    assert result.error_code in ("settings_invalid", "policy_plugin_missing_on_disk")
    assert _run_isolated("", settings) == ""


def test_scrub_failure_fails_before_import(tmp_path):
    import app.hermes.runtime as runtime

    def broken_scrub():
        raise RuntimeError("scrub exploded")

    settings = _valid_settings(tmp_path)
    result = run_hermes_job_with_broken_scrub(runtime, settings)
    assert result.status == "failed"
    assert result.error_code == "scrub_failed"
    # Fresh-interpreter proof: a raising scrub still prevents the import.
    body = (
        "def broken_scrub():\n"
        "    raise RuntimeError('scrub exploded')\n"
        "runtime.scrub_hermes_environment = broken_scrub\n"
        "result = runtime.run_hermes_job(request, settings=settings)\n"
        "assert result.status == 'failed' and result.error_code == 'scrub_failed'\n"
    )
    assert _run_isolated(body, settings) == ""


def run_hermes_job_with_broken_scrub(runtime, settings):
    original = runtime.scrub_hermes_environment

    def broken_scrub():
        raise RuntimeError("scrub exploded")

    runtime.scrub_hermes_environment = broken_scrub
    try:
        return run_hermes_job(_request(), settings=settings)
    finally:
        runtime.scrub_hermes_environment = original


def test_job_home_cleanup_on_construction_failure(tmp_path):
    """Cleanup contract: a failure AFTER import still deletes the job home
    and clears the runtime-owned environment."""
    import app.hermes.runtime as runtime

    settings = _valid_settings(tmp_path)
    original = runtime._construct_agent

    def broken_construct(request, config, baseline_threads):
        raise runtime.HermesRuntimeError("agent_construction_failed", "forced")

    runtime._construct_agent = broken_construct
    try:
        result = run_hermes_job(_request(), settings=settings)
    finally:
        runtime._construct_agent = original
    assert result.status == "failed"
    assert result.error_code == "agent_construction_failed"
    jobs_root = Path(settings.hermes_home) / "jobs"
    assert not (jobs_root / "job-1").exists()
    assert "HERMES_HOME" not in os.environ
    assert "HERMES_BUNDLED_PLUGINS" not in os.environ


# ---------------------------------------------------------------------------
# 7. Ordering: scrub runs BEFORE import (spy proof via lazy import hook)
# ---------------------------------------------------------------------------

def test_scrub_precedes_hermes_import(tmp_path, monkeypatch):
    import app.hermes.runtime as runtime

    events: list[str] = []
    real_scrub = runtime.scrub_hermes_environment

    def spying_scrub():
        events.append("scrub")
        real_scrub()

    import builtins

    real_import = builtins.__import__

    def spying_import(name, *args, **kwargs):
        if name == "run_agent":
            events.append("import-run_agent")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(runtime, "scrub_hermes_environment", spying_scrub)
    monkeypatch.setattr(builtins, "__import__", spying_import)
    if not HERMES_AVAILABLE:
        pytest.fail("pinned Hermes source required for §3 runtime tests is unavailable")
    result = run_hermes_job(_request(), settings=_valid_settings(tmp_path))
    assert result.error_code != "settings_invalid"
    assert events.index("scrub") < events.index("import-run_agent")


# ---------------------------------------------------------------------------
# 8. REAL Hermes integration (construction-only; §16 — no silent skips)
# ---------------------------------------------------------------------------

def test_real_construction_only_job(tmp_path):
    if not HERMES_AVAILABLE:
        pytest.fail("§16: pinned Hermes source missing — integration environment failure")
    settings = _valid_settings(tmp_path)
    result = run_hermes_job(_request(job_id="it-1", task_message=None), settings=settings)
    assert result.status == "completed", (result.error_code, result.error_detail)
    # Tool surface is EXACTLY the sanctioned native set: no Tool Search bridge.
    from app.hermes.policy import SANCTIONED_NATIVE_TOOLS

    import model_tools
    from app.hermes.capabilities import EXPOSED_CAPABILITIES

    resolved = set(model_tools._last_resolved_tool_names or [])
    expected = set(SANCTIONED_NATIVE_TOOLS) | set(EXPOSED_CAPABILITIES)
    assert resolved == expected == {"todo_list", "research.search", "asset.get"}
    assert not ({"tool_search", "tool_describe", "tool_call"} & resolved)
    # Per-job home deleted (§6/T13).
    assert not (Path(settings.hermes_home) / "jobs" / "it-1").exists()
    # No .env was ever created anywhere under the base home.
    assert not list(Path(settings.hermes_home).rglob(".env"))
    # Runtime env cleared.
    assert "HERMES_HOME" not in os.environ
    assert "HERMES_BUNDLED_PLUGINS" not in os.environ
    # Hermes was actually imported (the boundary ran).
    assert "run_agent" in sys.modules


def test_real_policy_plugin_loaded_and_tool_surface(tmp_path):
    """Plugin isolation + policy behavior, captured DURING the job (plugin
    managers are cached per resolved HERMES_HOME — hermes_cli/plugins.py:1591
    — so post-cleanup inspection would resolve a different, empty manager)."""
    if not HERMES_AVAILABLE:
        pytest.fail("§16: pinned Hermes source missing — integration environment failure")
    import app.hermes.runtime as runtime

    captured: dict = {}
    original_assert = runtime._assert_plugin_surface

    def capturing_assert():
        from hermes_cli.plugins import get_plugin_manager, iter_hook_callbacks

        captured["plugins"] = {p["key"]: p for p in get_plugin_manager().list_plugins()}
        captured["callbacks"] = list(iter_hook_callbacks("pre_tool_call"))
        original_assert()

    runtime._assert_plugin_surface = capturing_assert
    try:
        result = run_hermes_job(_request(job_id="it-2", task_message=None), settings=_valid_settings(tmp_path))
    finally:
        runtime._assert_plugin_surface = original_assert
    assert result.status == "completed", (result.error_code, result.error_detail)
    plugins = captured["plugins"]
    assert set(plugins) == {"aryaos-policy"}
    assert plugins["aryaos-policy"]["enabled"] and not plugins["aryaos-policy"]["error"]
    callbacks = captured["callbacks"]
    assert callbacks, "policy hook must be registered"
    verdict = callbacks[0]("shell", {})
    assert verdict["action"] == "block"
    # §9 capability allowed with VALID parameters (the registered chain
    # now includes live schema validation — invalid params would BLOCK).
    assert callbacks[0]("research.search", {"topic": "ai"}) is None


def test_real_watchdog_timeout_fails_closed(tmp_path):
    """§12: a job whose chat never returns is failed by the AryaOS watchdog."""
    if not HERMES_AVAILABLE:
        pytest.fail("§16: pinned Hermes source missing — integration environment failure")
    import app.hermes.runtime as runtime

    settings = _valid_settings(tmp_path)
    settings = settings.model_copy(update={"hermes_max_execution_seconds": 0.5})
    original = runtime._construct_agent
    # Stub only construction (keep the REAL watchdog): a chat that never
    # returns must be failed by the AryaOS wall clock.
    runtime._construct_agent = lambda request, config, baseline_threads: _BlockingAgent()
    try:
        result = run_hermes_job(_request(job_id="it-3", task_message="never returns"), settings=settings)
    finally:
        runtime._construct_agent = original
    assert result.status == "failed"
    assert result.error_code == "chat_timeout"
    assert not (Path(settings.hermes_home) / "jobs" / "it-3").exists()
    assert "HERMES_HOME" not in os.environ


class _BlockingAgent:
    enabled_toolsets = ["todo"]
    valid_tool_names = {"todo_list"}
    api_key = "aryaos-explicit-test-key"
    base_url = "http://127.0.0.1:9/v1"

    def chat(self, _message):
        time.sleep(30)
        return "never"

    def close(self):
        pass
