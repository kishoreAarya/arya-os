"""
AryaOS-owned Hermes runtime adapter — §3 embedding boundary (V2).

Spec: docs/architecture/HERMES_INTEGRATION_SPEC.md — §3 (embedding model),
§2 (pin assertion), §5.2 (per-job HERMES_HOME, generated config.yaml),
§5.3 (only plugin: the AryaOS policy plugin), §5.5 (environment scrub
before import), §6 (memory/session flags), §7 (no delegation), §8 (no
cron/gateway), §12 (AryaOS-owned resource limits), §4.3 (policy plugin
verified before agent construction), §16 (acceptance tests).

This module is the single embedding surface. Ordering is the security
property: it is enforced by run_hermes_job() and nothing else may import
Hermes. Concretely:

1.  Settings (app.core.config.get_settings, lru_cache'd) and
    get_validated_hermes_config() — § config slice.
2.  verify_hermes_source() — § source slice; refuses before any import.
3.  Fresh per-job HERMES_HOME (<hermes_home>/jobs/<job_id>, mode 0700,
    no .env ever written) — kills the dotenv reinjection channel
    (run_agent.py:109-113 loads <home>/.env AT IMPORT TIME; the vendor
    tree has no .env at the pin).
4.  Minimal generated config.yaml (plugins.enabled + security only).
5.  scrub_hermes_environment() — §5.5 slice.
6.  Post-scrub verification (no scrub-rule name remains set).
7.  Runtime-owned environment: HERMES_HOME=<job home>,
    HERMES_BUNDLED_PLUGINS=<plugin_path> (so the bundled-dir scan —
    hermes_cli/plugins.py:69-74 — sees ONLY the AryaOS plugin directory;
    user dir is the empty job home; project plugins are env-gated off by
    the scrub), plus removal of the two non-Hermes-namespace LANGFUSE
    keys (plugins/observability/langfuse/__init__.py:252 composes
    f"LANGFUSE_{n}" at the pin).
8.  Deferred ``import run_agent`` — the FIRST Hermes import, strictly
    after the scrub.
9.  Explicit discover_plugins(); assert the loaded plugin set is exactly
    {aryaos-policy} (covers bundled/user/project/entry-point sources —
    entry-point group "hermes_agent.plugins", none shipped at the pin).
10. verify_policy_plugin_registered(iter_hook_callbacks("pre_tool_call"))
    — §4.3: refuse to construct the agent without the policy gate.
11. AIAgent construction with the frozen safe configuration: §5.1 frozen
    toolsets (never None), §6 skip flags, §12 limits (native
    max_iterations/run_budget_seconds PLUS the AryaOS watchdog), and
    EXPLICIT provider/base_url/api_key/model from AryaOS so Hermes never
    resolves model credentials from environment state
    (agent_init._init_openai_client: explicit api_key+base_url bypasses
    routed/env credential resolution).
12. Post-construction assertions: exact toolset list, tool surface within
    the sanctioned native set, pinned credentials, no cron/gateway/TUI/MCP
    modules imported.
13. Optional chat() behind an AryaOS-owned wall-clock watchdog (§12: AryaOS
    owns the truth even if Hermes misreports; the worker thread is a
    daemon and is abandoned on timeout).
14. agent.close() (idempotent, guarded per phase — run_agent.py:958).
15. Per-job home deleted on BOTH success and failure (§6: AryaOS is the
    system of record; no Hermes state survives a job).
16. Runtime-owned env vars removed and the authorization-context holder
    cleared in finally.
17. A process-local lock serializes jobs: the env-var HERMES_HOME binding
    cannot support concurrent embedded jobs (plugin managers cache per
    resolved home, hermes_cli/plugins.py:1591).

Out of scope by design (later slices): §9 typed capability bindings,
§10 expanded context, §11 approval flow, §13 audit store, concurrency.
"""
import os
import shutil
import threading
from dataclasses import dataclass
from pathlib import Path

from app.core.config import Settings, get_settings
from app.hermes.config import HermesRuntimeConfig, get_validated_hermes_config
from app.hermes.env_scrub import get_hermes_scrub_names, scrub_hermes_environment
from app.hermes.policy import AuthorizationContext, verify_policy_plugin_registered
from app.hermes.source import verify_hermes_source
from app.hermes.toolsets import get_frozen_enabled_toolsets

# Module import must never touch Hermes; runtime.py imports only stdlib and
# AryaOS modules (asserted by test_hermes_runtime_unit.py).
_PLUGIN_DIR_NAME = "aryaos-policy"
# Module import of cron/gateway is a property of Hermes' transitive import
# graph and is inert; §3/T7/T8 forbid ACTIVATION. Cron activity is
# introspectable via cron.scheduler.get_running_job_ids() (pin:
# cron/scheduler.py:662) and its worker threads are named cron-*
# (cron/scheduler.py:1381,1936,3858). Gateway threads carry gateway names.
_ACTIVATION_THREAD_PATTERNS = ("gateway", "cron", "scheduler")
_LANGFUSE_KEYS = ("LANGFUSE_PUBLIC_KEY", "LANGFUSE_SECRET_KEY")
_RUNTIME_ENV_KEYS = ("HERMES_HOME", "HERMES_BUNDLED_PLUGINS")
_JOB_HOME_MODE = 0o700

# Process-local runtime lock: exactly one embedded Hermes job at a time
# (§3 slice 1 — no concurrency).
_RUNTIME_LOCK = threading.Lock()

# Per-job authorization context supplied to the policy plugin's register().
# Set under the runtime lock before plugin discovery; cleared in finally.
_ACTIVE_CONTEXT: AuthorizationContext | None = None
_ACTIVE_CONTEXT_LOCK = threading.Lock()


def set_active_authorization_context(context: AuthorizationContext | None) -> None:
    """Bind the per-job AuthorizationContext the policy plugin registers with."""
    global _ACTIVE_CONTEXT
    with _ACTIVE_CONTEXT_LOCK:
        _ACTIVE_CONTEXT = context


def get_active_authorization_context() -> AuthorizationContext:
    """The context bound by the runtime. Raises if absent (the plugin then
    fails to load, which fails plugin-surface verification — fail closed)."""
    with _ACTIVE_CONTEXT_LOCK:
        if _ACTIVE_CONTEXT is None:
            raise RuntimeError(
                "no active AryaOS authorization context; the policy plugin may "
                "only load inside a runtime-managed Hermes job"
            )
        return _ACTIVE_CONTEXT


class HermesRuntimeError(RuntimeError):
    """A §3 runtime gate failed. Fail-closed: the job must not run (or must
    stop). `code` is a stable machine-readable reason; `detail` carries
    names/paths only — never secrets (the request carries an api_key).
    """

    def __init__(self, code: str, detail: str):
        self.code = code
        self.detail = detail
        super().__init__(f"Hermes runtime gate failed [{code}]: {detail}")


@dataclass(frozen=True)
class HermesJobRequest:
    """One bounded Hermes job. Model routing is EXPLICIT and AryaOS-owned."""

    job_id: str
    task_message: str | None  # None = construction-only job (no model call)
    authorization_context: AuthorizationContext
    provider: str
    base_url: str
    api_key: str
    model: str


@dataclass(frozen=True)
class HermesJobResult:
    job_id: str
    status: str  # "completed" | "failed"
    final_response: str | None
    error_code: str | None
    error_detail: str | None


def completed(request: HermesJobRequest, final_response: str | None) -> HermesJobResult:
    return HermesJobResult(
        job_id=request.job_id,
        status="completed",
        final_response=final_response,
        error_code=None,
        error_detail=None,
    )


# ---------------------------------------------------------------------------
# Step helpers (pure / independently testable)
# ---------------------------------------------------------------------------


def render_config_yaml() -> str:
    """The minimal §5.2/§5.3 generated config.yaml — deterministic text.

    plugins.enabled lists exactly the AryaOS policy plugin (opt-in gate,
    hermes_cli/plugins_discovery.gate_manifest); security.tirith_fail_open
    is the verified-safe value; tools.tool_search.enabled is "off" so the
    pinned default ("auto" = on, with todo_list in the curated defer list —
    hermes_cli/config_defaults.py:1952+) never wraps the sanctioned tools
    in the tool_search/tool_describe/tool_call bridge
    (model_tools.py:535 skips assembly when enabled == "off"). Nothing
    else: no MCP, gateway, cron, memory, browser, terminal, or model
    sections.
    """
    return (
        "plugins:\n"
        "  enabled:\n"
        f"  - {_PLUGIN_DIR_NAME}\n"
        "  disabled: []\n"
        "security:\n"
        "  tirith_fail_open: false\n"
        "tools:\n"
        "  tool_search:\n"
        '    enabled: "off"\n'
    )


def create_job_home(base_home: Path, job_id: str) -> Path:
    """Fresh per-job HERMES_HOME: <base>/jobs/<job_id>, mode 0700.

    Refuses a non-fresh home (exists and non-empty) so no stale Hermes
    state (notably a leftover .env) can survive into a job.
    """
    if not job_id or not isinstance(job_id, str) or any(c in job_id for c in "/\\."):
        raise HermesRuntimeError("job_id_invalid", f"job_id {job_id!r} must be a non-empty path-free token")
    jobs_root = base_home / "jobs"
    jobs_root.mkdir(parents=True, exist_ok=True, mode=_JOB_HOME_MODE)
    os.chmod(jobs_root, _JOB_HOME_MODE)
    job_home = jobs_root / job_id
    if job_home.exists():
        if job_home.is_dir() and not any(job_home.iterdir()):
            pass  # an empty dir is usable
        else:
            raise HermesRuntimeError(
                "job_home_not_fresh",
                f"job home {job_home} already exists and is not empty; refusing to "
                f"reuse possibly-stale Hermes state",
            )
    else:
        job_home.mkdir(mode=_JOB_HOME_MODE)
    os.chmod(job_home, _JOB_HOME_MODE)
    return job_home


def apply_runtime_environment(job_home: Path, plugin_path: Path) -> list[str]:
    """Set the runtime-owned Hermes environment for this job (§5.2/§5.3).

    Runs AFTER the §5.5 scrub (which removed any inherited values for
    these names). Returns the list of names touched, for deterministic
    cleanup. Only these names may be set by the runtime.
    """
    touched = list(_RUNTIME_ENV_KEYS)
    for name in _RUNTIME_ENV_KEYS + _LANGFUSE_KEYS:
        if name in os.environ:
            del os.environ[name]
    os.environ["HERMES_HOME"] = str(job_home)
    os.environ["HERMES_BUNDLED_PLUGINS"] = str(plugin_path)
    return touched


def clear_runtime_environment(names: list[str]) -> None:
    """Remove the runtime-owned environment names (called in finally)."""
    for name in names:
        os.environ.pop(name, None)


def run_with_watchdog(fn, timeout_seconds: float) -> tuple[str, object, BaseException | None]:
    """Run fn() in a daemon worker thread under an AryaOS wall-clock cap.

    Returns ("completed", value, None) | ("error", None, exc) |
    ("timeout", None, None). On timeout the daemon worker is abandoned
    (§12: limits are enforced even if Hermes never returns).
    """
    outcome: dict = {}

    def _worker():
        try:
            outcome["value"] = fn()
        except BaseException as exc:  # noqa: BLE001 — reported to the caller
            outcome["error"] = exc

    worker = threading.Thread(target=_worker, daemon=True, name="aryaos-hermes-job")
    worker.start()
    worker.join(timeout_seconds)
    if worker.is_alive():
        return ("timeout", None, None)
    if "error" in outcome:
        return ("error", None, outcome["error"])
    return ("completed", outcome.get("value"), None)


def _assert_plugin_surface() -> None:
    """Steps 10a/9: exactly the AryaOS policy plugin is loaded and enabled."""
    from hermes_cli.plugins import get_plugin_manager

    plugins = get_plugin_manager().list_plugins()
    loaded = {p["key"] for p in plugins}
    if loaded != {_PLUGIN_DIR_NAME}:
        raise HermesRuntimeError(
            "plugin_surface_violation",
            f"Hermes plugin discovery loaded {sorted(loaded)}; expected exactly "
            f"[{_PLUGIN_DIR_NAME}] (§5.3: the AryaOS policy plugin is the only "
            f"permitted plugin)",
        )
    if not all(p["enabled"] and not p["error"] for p in plugins):
        raise HermesRuntimeError(
            "plugin_surface_violation",
            f"the {_PLUGIN_DIR_NAME} plugin did not load cleanly (§5.3)",
        )


def _assert_policy_hook_registered() -> None:
    """Step 10b/§4.3: the policy gate is registered before construction."""
    from hermes_cli.plugins import iter_hook_callbacks

    verify_policy_plugin_registered(list(iter_hook_callbacks("pre_tool_call")))


def _construct_agent(request: HermesJobRequest, config: HermesRuntimeConfig, baseline_threads: frozenset[str]):
    """Steps 11-12: AIAgent with the frozen safe configuration."""
    from app.hermes.policy import SANCTIONED_NATIVE_TOOLS
    from run_agent import AIAgent

    enabled = list(get_frozen_enabled_toolsets())  # never None (§5.1)
    agent = AIAgent(
        base_url=request.base_url,
        api_key=request.api_key,
        provider=request.provider,
        model=request.model,
        enabled_toolsets=enabled,
        disabled_toolsets=None,
        skip_memory=True,
        skip_context_files=True,
        skip_background_review=True,
        max_iterations=config.max_iterations,
        run_budget_seconds=config.max_execution_seconds,
        quiet_mode=True,
        save_trajectories=False,
        cwd=str(_active_job_home()),
    )

    if list(agent.enabled_toolsets or []) != enabled:
        raise HermesRuntimeError(
            "tool_surface_violation",
            f"agent enabled_toolsets {list(agent.enabled_toolsets or [])} != frozen "
            f"allowlist {enabled}",
        )
    resolved = set(getattr(agent, "valid_tool_names", None) or ())
    if resolved != set(SANCTIONED_NATIVE_TOOLS):
        raise HermesRuntimeError(
            "tool_surface_violation",
            f"agent tool surface {sorted(resolved)} != the sanctioned native "
            f"tools {sorted(SANCTIONED_NATIVE_TOOLS)} (Tool Search is disabled "
            f"in the generated config; any bridge tool here is a violation)",
        )
    if agent.api_key != request.api_key or agent.base_url != request.base_url:
        raise HermesRuntimeError(
            "credential_pin_violation",
            "agent credentials were not pinned to the AryaOS-supplied values",
        )
    _assert_no_runtime_activation(baseline_threads)
    return agent


def _assert_no_runtime_activation(baseline_threads: frozenset[str]) -> None:
    """T7/T8: no cron/scheduler/gateway ACTIVITY — running cron jobs, or
    threads matching the activation patterns, must not appear during an
    embedded job. (Module imports alone are inert at the pin.)"""
    import cron.scheduler as cron_scheduler

    running = cron_scheduler.get_running_job_ids()
    if running:
        raise HermesRuntimeError(
            "cron_activated",
            f"Hermes cron jobs are running during an embedded job: {sorted(running)}",
        )
    new_threads = [
        t.name for t in threading.enumerate() if t.name not in baseline_threads
    ]
    activated = [
        name
        for name in new_threads
        if any(pattern in name.lower() for pattern in _ACTIVATION_THREAD_PATTERNS)
    ]
    if activated:
        raise HermesRuntimeError(
            "runtime_activation_violation",
            f"threads matching cron/gateway/scheduler patterns appeared during "
            f"startup: {sorted(activated)}",
        )


def _active_job_home() -> Path:
    home = os.environ.get("HERMES_HOME", "")
    if not home:
        raise HermesRuntimeError("runtime_env_missing", "HERMES_HOME is not set for this job")
    return Path(home)


# ---------------------------------------------------------------------------
# The embedding boundary
# ---------------------------------------------------------------------------


def run_hermes_job(
    request: HermesJobRequest,
    settings: Settings | None = None,
) -> HermesJobResult:
    """Run one bounded Hermes job under the §3 ordering contract.

    Never raises for job-level failures — returns HermesJobResult with
    status "failed" and a stable error code. Cleanup runs on both paths.
    """
    with _RUNTIME_LOCK:
        return _run_job_locked(request, settings)


def _run_job_locked(request: HermesJobRequest, settings: Settings | None) -> HermesJobResult:
    job_home: Path | None = None
    env_touched: list[str] = []
    agent = None
    context_was_set = False
    try:
        # 1. Settings + validated Hermes configuration (§ config slice).
        settings = settings if settings is not None else get_settings()
        try:
            config = get_validated_hermes_config(settings)
        except Exception as exc:
            raise HermesRuntimeError("settings_invalid", str(exc)) from exc
        if config is None:
            raise HermesRuntimeError("hermes_disabled", "hermes_enabled=false; no embedded runtime")
        plugin_path = config.plugin_path
        for required in (plugin_path / _PLUGIN_DIR_NAME / "__init__.py", plugin_path / _PLUGIN_DIR_NAME / "plugin.yaml"):
            if not required.is_file():
                raise HermesRuntimeError(
                    "policy_plugin_missing_on_disk",
                    f"expected plugin file {required} does not exist (§5.3)",
                )

        # 2. Source integrity (§2/§14.1) — before any Hermes import.
        try:
            verify_hermes_source()
        except Exception as exc:
            raise HermesRuntimeError("source_verification_failed", str(exc)) from exc

        # 3. Fresh per-job HERMES_HOME (no .env is ever created).
        job_home = create_job_home(config.hermes_home, request.job_id)

        # 4. Minimal generated config.yaml.
        (job_home / "config.yaml").write_text(render_config_yaml(), encoding="utf-8")

        # 5-6. §5.5 scrub + verification (BEFORE any Hermes import).
        try:
            scrub_hermes_environment()
        except Exception as exc:
            raise HermesRuntimeError("scrub_failed", str(exc)) from exc
        residual = get_hermes_scrub_names(os.environ)
        if residual:
            raise HermesRuntimeError(
                "scrub_verification_failed",
                f"environment still holds scrub-rule names after scrub: {list(residual)}",
            )

        # 7. Runtime-owned environment.
        env_touched = apply_runtime_environment(job_home, plugin_path)

        # 8. Bind the authorization context for the policy plugin.
        set_active_authorization_context(request.authorization_context)
        context_was_set = True
        baseline_threads = frozenset(t.name for t in threading.enumerate())

        # 9. FIRST Hermes import — strictly after the scrub.
        import run_agent  # noqa: F401 — import side effect is the boundary

        # 10. Plugin discovery: only the AryaOS policy plugin may load.
        from hermes_cli.plugins import discover_plugins

        discover_plugins()
        _assert_plugin_surface()
        _assert_policy_hook_registered()

        # 11-12. Construct + assert the frozen safe configuration.
        agent = _construct_agent(request, config, baseline_threads)

        # 13. Optional chat behind the AryaOS watchdog.
        final_response = None
        if request.task_message is not None:
            status, value, exc = run_with_watchdog(
                lambda: agent.chat(request.task_message),  # noqa: B023 — bound at call time
                config.max_execution_seconds,
            )
            if status == "timeout":
                raise HermesRuntimeError(
                    "chat_timeout",
                    f"job exceeded hermes_max_execution_seconds={config.max_execution_seconds}",
                )
            if status == "error":
                raise HermesRuntimeError("chat_failed", f"{type(exc).__name__}")
            final_response = str(value) if value is not None else None

        return completed(request, final_response)
    except HermesRuntimeError as exc:
        return HermesJobResult(
            job_id=request.job_id,
            status="failed",
            final_response=None,
            error_code=exc.code,
            error_detail=exc.detail,
        )
    except BaseException as exc:  # noqa: BLE001 — job boundary never raises
        return HermesJobResult(
            job_id=request.job_id,
            status="failed",
            final_response=None,
            error_code="unexpected_runtime_failure",
            error_detail=f"{type(exc).__name__}",
        )
    finally:
        # 14-16. Deterministic cleanup on BOTH paths.
        if agent is not None:
            try:
                agent.close()
            except Exception:
                pass
        if job_home is not None:
            shutil.rmtree(job_home, ignore_errors=True)
        if env_touched:
            clear_runtime_environment(env_touched)
        if context_was_set:
            set_active_authorization_context(None)
