"""
Fail-closed pre-import environment scrub for Hermes (V2).

Spec: docs/architecture/HERMES_INTEGRATION_SPEC.md — §5.5 (environment
scrubbing before import), §16/T14 (scrub step testable in isolation).

Contract (single, testable pre-import step):
- The runtime adapter MUST call scrub_hermes_environment() exactly once,
  AFTER AryaOS Settings construction (AryaOS reads its own HERMES_* setting
  names from the environment via pydantic-settings) and BEFORE importing any
  Hermes module. If the call raises, the runtime refuses to import Hermes.
- Matched variables are removed (``del``), never overridden. The result and
  any error carry variable NAMES only — never values (some matched names are
  credentials, e.g. SUDO_PASSWORD).
- The step is idempotent and deterministic (result names are sorted).
- Fail closed: after removal, every matched name is re-verified absent; any
  residual raises HermesEnvScrubError ("scrub_failed"). A caller that cannot
  scrub must not import Hermes.

Hermes itself is not imported here and is not required to exist.

Scrub rules (two layers, both frozen at the pinned commit
c0d7294769a38c17ceae51d8f7995e66e1dcae27):

1. Namespace rule. Every environment variable whose name starts with
   ``HERMES_`` or ``_HERMES_`` is scrubbed. The Hermes-owned namespace is
   behavior-configuration by definition (home resolution, gateway/CLI/cron
   enablement, sessions, plugins, tool/MCP pre-configuration). A prefix rule
   is required in addition to enumeration because the pinned source also
   reads Hermes-namespace variables through dynamic indirection that static
   enumeration cannot close (verified examples at the pin:
    ``cron_env_setting("HERMES_CRON_INFLIGHT_MAX_MINUTES")``,
    ``cron_env_setting("HERMES_CRON_MAX_PARALLEL")``,
    ``_env_get(env, "HERMES_REAL_HOME")``, profile-managed keys in
   ``hermes_cli/env_loader.py``).

2. Exact-name rule. Non-Hermes-namespace variables verified read by runtime
   code at the pin, grouped by the §5.5 categories (gateway/API-server/relay
   enablement and auth bypass; tool/terminal/browser pre-configuration;
   external-agent credential bridges). AryaOS itself reads none of these
   (verified against backend/app and .env.example).

Deliberately NOT scrubbed (documented decisions, not omissions):

- Host-process-generic variables (PATH, HOME, USERPROFILE, LOCALAPPDATA,
  APPDATA, TMPDIR, XDG_*, DISPLAY, ...) — AryaOS shares this process and
  its libraries require them; Hermes home isolation is enforced by the
  dedicated HERMES_HOME set by the runtime adapter slice (§5.2), not by
  scrubbing the host's HOME fallback chain. XDG_* reads at the pin are
  gateway/desktop/CLI-only code paths (§3 excludes those runtimes).
- TLS trust anchors (SSL_CERT_FILE, REQUESTS_CA_BUNDLE, CURL_CA_BUNDLE,
  SSL_CERT_DIR) and proxy variables (HTTP_PROXY/HTTPS_PROXY/NO_PROXY) —
  shared host deployment configuration that scrubbing would break for
  AryaOS's own outbound traffic. Hermes-side HERMES_CA_BUNDLE and
  HERMES_SKIP_SSL_GUARD ARE scrubbed via the namespace rule.
- Model/provider credentials and endpoints (OPENAI_API_KEY,
  OPENROUTER_API_KEY, ANTHROPIC_API_KEY, *_BASE_URL, ...) — AryaOS uses
  these in-process for its own provider stack. Hermes's model configuration
  is pinned through the AryaOS-generated config.yaml (§5.2, runtime slice);
  until that slice lands this remains a documented residual risk.
- Plugin-specific API keys (TAVILY_API_KEY, HONCHO_*, MEM0_*, ...) — only
  effective if the corresponding plugin is configured, and no MCP/plugin
  configuration is generated (§5.3).

Names below were enumerated from the pinned source by AST extraction of
static ``os.environ``/``os.getenv`` reads plus review of the dynamic
indirection sites and Hermes's own behavioral-variable inventory
(tests/conftest.py::_HERMES_BEHAVIORAL_VARS).
"""
import os
from collections.abc import Mapping
from dataclasses import dataclass


class HermesEnvScrubError(RuntimeError):
    """The pre-import scrub could not be completed. Fail-closed: the caller
    must refuse to import Hermes (spec §5.5).

    `violations` is a list of (code, detail) tuples, mirroring
    app.hermes.config.HermesConfigError. Details contain variable names
    only, never values.
    """

    def __init__(self, violations: list[tuple[str, str]]):
        self.violations = violations
        rendered = "; ".join(f"{code}: {detail}" for code, detail in violations)
        super().__init__(f"Hermes environment scrub failed ({rendered})")


# Layer 1: the Hermes-owned namespace. Every matching variable is scrubbed.
HERMES_ENV_SCRUB_PREFIXES: tuple[str, ...] = ("HERMES_", "_HERMES_")

# Layer 1 (audit trail): every Hermes-namespace variable name known to be
# read at the pinned commit (static reads + dynamic indirection + the
# upstream behavioral inventory). The prefix rule is what enforces the
# scrub; this frozen inventory documents what was enumerated and trips
# review when the pin changes (§15).
HERMES_NAMESPACED_ENV_KNOWN: frozenset[str] = frozenset(
    {
        "HERMES_ACCEPT_HOOKS",
        "HERMES_ACP_AUTH_METHOD",
        "HERMES_ACP_AUTO_APPROVE",
        "HERMES_ACP_SKIP_CONFIGURED_MCP",
        "HERMES_ACTION_ID",
        "HERMES_AGENT",
        "HERMES_AGENT_NOTIFY_INTERVAL",
        "HERMES_AGENT_TIMEOUT",
        "HERMES_AGENT_USE_LEGACY_SESSION_KEYS",
        "HERMES_ALLOW_PRIVATE_URLS",
        "HERMES_ALLOW_ROOT_GATEWAY",
        "HERMES_API_CALL_STALE_TIMEOUT",
        "HERMES_API_TIMEOUT",
        "HERMES_AUTO_CONTINUE_FRESHNESS",
        "HERMES_BACKGROUND_NOTIFICATIONS",
        "HERMES_BIN",
        "HERMES_BUNDLED_LOCALES",
        "HERMES_BUNDLED_PLUGINS",
        "HERMES_BUNDLES_DIR",
        "HERMES_CA_BUNDLE",
        "HERMES_CITATION_LEDGER",
        "HERMES_CJK_FTS",
        "HERMES_CODEX_BASE_URL",
        "HERMES_CODEX_TTFB_STRICT",
        "HERMES_COMPUTER_USE_BACKEND",
        "HERMES_COMPUTE_HOST_CHILD",
        "HERMES_COMPUTE_HOST_HEARTBEAT_SECS",
        "HERMES_CONTAINER",
        "HERMES_COPILOT_ACP_ARGS",
        "HERMES_COPILOT_ACP_COMMAND",
        "HERMES_CRON_AUTO_DELIVER_CHAT_ID",
        "HERMES_CRON_AUTO_DELIVER_PLATFORM",
        "HERMES_CRON_AUTO_DELIVER_THREAD_ID",
        "HERMES_CRON_INFLIGHT_MAX_MINUTES",
        "HERMES_CRON_MAX_PARALLEL",
        "HERMES_CRON_SCRIPT_TIMEOUT",
        "HERMES_CRON_SESSION",
        "HERMES_CRON_TIMEOUT",
        "HERMES_CUA_DRIVER_CMD",
        "HERMES_DASHBOARD_BASIC_AUTH_PASSWORD",
        "HERMES_DASHBOARD_DRAIN_SECRET",
        "HERMES_DASHBOARD_OAUTH_CLIENT_ID",
        "HERMES_DASHBOARD_PORTAL_URL",
        "HERMES_DASHBOARD_PUBLIC_URL",
        "HERMES_DASHBOARD_SESSION_TOKEN",
        "HERMES_DASHBOARD_WS_HOST",
        "HERMES_DDGS_ALLOW_TEST_HOOKS",
        "HERMES_DEFER_AGENT_STARTUP",
        "HERMES_DELEGATED_CHILD_CONTEXT",
        "HERMES_DESKTOP",
        "HERMES_DESKTOP_CHILD_PID",
        "HERMES_DESKTOP_DEV_SERVER",
        "HERMES_DESKTOP_READY_FILE",
        "HERMES_DESKTOP_TERMINAL",
        "HERMES_DEV",
        "HERMES_DEV_BILLING_FIXTURE",
        "HERMES_DEV_CREDITS",
        "HERMES_DEV_CREDITS_FIXTURE",
        "HERMES_DEV_SUBSCRIPTION_FIXTURE",
        "HERMES_DIAGNOSTICS_BASE_URL",
        "HERMES_DISABLE_FAST_CHAT_LAUNCH",
        "HERMES_DISABLE_FAST_SERVE_LAUNCH",
        "HERMES_DISABLE_FILE_STATE_GUARD",
        "HERMES_DISABLE_LAZY_INSTALLS",
        "HERMES_DISABLE_REDACTION",
        "HERMES_DISABLE_TELEMETRY",
        "HERMES_DISABLE_WINDOWS_UTF8",
        "HERMES_DISCORD_LIVENESS_FAILURE_THRESHOLD",
        "HERMES_DISCORD_LIVENESS_INTERVAL_SECONDS",
        "HERMES_DOCKER_BINARY",
        "HERMES_E2E_BROWSER",
        "HERMES_E2E_CAPTURE_LAUNCH",
        "HERMES_ENABLE_PROJECT_PLUGINS",
        "HERMES_ENVIRONMENT_HINT",
        "HERMES_EPHEMERAL_SYSTEM_PROMPT",
        "HERMES_EVAL_REPO",
        "HERMES_EXEC_ASK",
        "HERMES_FAST_STARTUP_BANNER",
        "HERMES_FTS5_CJK_SO",
        "HERMES_GATEWAY_ADAPTER_DISCONNECT_TIMEOUT",
        "HERMES_GATEWAY_BUSY_ACK_ENABLED",
        "HERMES_GATEWAY_BUSY_STEER_ACK_ENABLED",
        "HERMES_GATEWAY_DETACHED",
        "HERMES_GATEWAY_EXIT_DIAG",
        "HERMES_GATEWAY_EXTERNAL_SUPERVISOR",
        "HERMES_GATEWAY_LOCK_DIR",
        "HERMES_GATEWAY_MAX_STARTS",
        "HERMES_GATEWAY_NO_SUPERVISE",
        "HERMES_GATEWAY_PLATFORM_CONNECT_TIMEOUT",
        "HERMES_GATEWAY_SESSION",
        "HERMES_GATEWAY_START_WINDOW_S",
        "HERMES_GID",
        "HERMES_GIT_BASH_PATH",
        "HERMES_GWS_BIN",
        "HERMES_HOME",
        "HERMES_HOME_MODE",
        "HERMES_HOME_SOURCE",
        "HERMES_HONCHO_HOST",
        "HERMES_IGNORE_RULES",
        "HERMES_IGNORE_USER_CONFIG",
        "HERMES_INFERENCE_MODEL",
        "HERMES_INFERENCE_PROVIDER",
        "HERMES_INTERACTIVE",
        "HERMES_ISO_CERTIFY_SYNTH_TURN",
        "HERMES_KANBAN_ATTACHMENTS_ROOT",
        "HERMES_KANBAN_BOARD",
        "HERMES_KANBAN_CLAIM_LOCK",
        "HERMES_KANBAN_DB",
        "HERMES_KANBAN_DISPATCH_IN_GATEWAY",
        "HERMES_KANBAN_GOAL_MODE",
        "HERMES_KANBAN_HOME",
        "HERMES_KANBAN_LOGS_ROOT",
        "HERMES_KANBAN_RUN_ID",
        "HERMES_KANBAN_STOP_NUDGE",
        "HERMES_KANBAN_TASK",
        "HERMES_KANBAN_WORKSPACE",
        "HERMES_KANBAN_WORKSPACES_ROOT",
        "HERMES_LANGUAGE",
        "HERMES_LAZY_INSTALL_TARGET",
        "HERMES_LIVE_TESTS",
        "HERMES_MACHINE_ID",
        "HERMES_MANAGED",
        "HERMES_MANAGED_DIR",
        "HERMES_MATRIX_TEXT_BATCH_DELAY_SECONDS",
        "HERMES_MATRIX_TEXT_BATCH_SPLIT_DELAY_SECONDS",
        "HERMES_MAX_ITERATIONS",
        "HERMES_MAX_TOKENS",
        "HERMES_MEDIA_ALLOW_DIRS",
        "HERMES_MEDIA_DELIVERY_STRICT",
        "HERMES_MEDIA_TRUST_RECENT_FILES",
        "HERMES_MEDIA_TRUST_RECENT_SECONDS",
        "HERMES_MODEL",
        "HERMES_NATIVE_FILE_READ",
        "HERMES_NIX_BUILD",
        "HERMES_NODE",
        "HERMES_NODE_TARGET_MAJOR",
        "HERMES_NONINTERACTIVE",
        "HERMES_NOUS_MIN_KEY_TTL_SECONDS",
        "HERMES_NOUS_TIMEOUT_SECONDS",
        "HERMES_OAUTH_TRACE",
        "HERMES_OPENROUTER_CACHE",
        "HERMES_OPENROUTER_CACHE_TTL",
        "HERMES_OPTIONAL_MCPS",
        "HERMES_OSINT_CACHE",
        "HERMES_OSINT_UA",
        "HERMES_PARENT_NONCE",
        "HERMES_PARENT_PID",
        "HERMES_PARENT_START_MARKER",
        "HERMES_PERF_LOG",
        "HERMES_PERF_NODE",
        "HERMES_PET_IMAGE_PROVIDER",
        "HERMES_PET_REFERENCE_MAX_BYTES",
        "HERMES_PLATFORM",
        "HERMES_PLUGIN_PAYLOAD_MAX_CHARS",
        "HERMES_PORTAL_BASE_URL",
        "HERMES_PREFILL_MESSAGES_FILE",
        "HERMES_PROFILE",
        "HERMES_PYTHON_SRC_ROOT",
        "HERMES_QUIET",
        "HERMES_QWEN_BASE_URL",
        "HERMES_REAL_HOME",
        "HERMES_REDACT_SECRETS",
        "HERMES_RESTART_DRAIN_TIMEOUT",
        "HERMES_REVISION",
        "HERMES_ROOM_LINK_URL",
        "HERMES_RUN_E2E",
        "HERMES_RUN_NETWORK_TESTS",
        "HERMES_RUN_SLOW_PET_TESTS",
        "HERMES_S6_SUPERVISED_CHILD",
        "HERMES_SAFE_MODE",
        "HERMES_SEARCH_SLOW_MS",
        "HERMES_SERVE_HEADLESS",
        "HERMES_SERVE_WATCHDOG_POLL_S",
        "HERMES_SESSION_CHAT_ID",
        "HERMES_SESSION_CHAT_NAME",
        "HERMES_SESSION_CHAT_TYPE",
        "HERMES_SESSION_ID",
        "HERMES_SESSION_KEY",
        "HERMES_SESSION_PLATFORM",
        "HERMES_SESSION_SOURCE",
        "HERMES_SESSION_SOURCE_EXPLICIT",
        "HERMES_SESSION_THREAD_ID",
        "HERMES_SHARED_AUTH_DIR",
        "HERMES_SIMPLEX_TEXT_BATCH_DELAY",
        "HERMES_SINGLE_QUERY_SESSION",
        "HERMES_SKIP_CHMOD",
        "HERMES_SKIP_NODE_BOOTSTRAP",
        "HERMES_SKIP_SSL_GUARD",
        "HERMES_SPINNER_PAUSE",
        "HERMES_STREAM_READ_TIMEOUT",
        "HERMES_STREAM_RETRIES",
        "HERMES_SUPERVISED_CHILD",
        "HERMES_SYNC_BASE_URL",
        "HERMES_SYNC_DEVICE_NAME",
        "HERMES_TELEGRAM_DISABLE_FALLBACK_IPS",
        "HERMES_TELEGRAM_FOLLOWUP_GRACE_SECONDS",
        "HERMES_TELEGRAM_NOTIFICATIONS",
        "HERMES_TENANT",
        "HERMES_TERMINAL_SECURITY_MODE",
        "HERMES_TERMUX_DISABLE_FAST_CLI",
        "HERMES_TERMUX_FORCE_SKILLS_SYNC",
        "HERMES_TERMUX_PREFETCH_UPDATES",
        "HERMES_TEST_FILE_RETRIES",
        "HERMES_TEST_FILE_TIMEOUT",
        "HERMES_TEST_IMAGE",
        "HERMES_TEST_ISOLATION",
        "HERMES_TEST_KANBAN_PLUGIN",
        "HERMES_TEST_MODE",
        "HERMES_TEST_NETWORK",
        "HERMES_TEST_PATHS",
        "HERMES_TEST_PLUGIN_BOOTSTRAP",
        "HERMES_TEST_RUNTIME_KEY",
        "HERMES_TEST_SHARED_ADAPTER_CONFIG",
        "HERMES_TEST_SLICE",
        "HERMES_TEST_WORKERS",
        "HERMES_TIMEZONE",
        "HERMES_TOOL_PROGRESS",
        "HERMES_TOOL_PROGRESS_MODE",
        "HERMES_TUI",
        "HERMES_TUI_BACKGROUND",
        "HERMES_TUI_CHECKPOINTS",
        "HERMES_TUI_DIR",
        "HERMES_TUI_FORCE_BUILD",
        "HERMES_TUI_GATEWAY_NO_FLUSH",
        "HERMES_TUI_MAX_TURNS",
        "HERMES_TUI_NO_EARLY_DISABLE",
        "HERMES_TUI_PASS_SESSION_ID",
        "HERMES_TUI_PROVIDER",
        "HERMES_TUI_RPC_POOL_WORKERS",
        "HERMES_TUI_SIDECAR_URL",
        "HERMES_TUI_SKILLS",
        "HERMES_TUI_THEME",
        "HERMES_TUI_TOOLSETS",
        "HERMES_TUI_TOOL_PROGRESS",
        "HERMES_TURN_COMPLETION_EXPLAINER",
        "HERMES_TURN_LEASE_TIMEOUT",
        "HERMES_UID",
        "HERMES_UPDATE_POST_SWAP",
        "HERMES_VERIFY_ON_STOP",
        "HERMES_VISION_MAX_CONCURRENCY",
        "HERMES_VOICE",
        "HERMES_VOICE_DEBUG",
        "HERMES_VOICE_TTS",
        "HERMES_WEB_DIST",
        "HERMES_WORKTREE",
        "HERMES_WRITE_SAFE_ROOT",
        "HERMES_XAI_BASE_URL",
        "HERMES_YOLO_MODE",
        "_HERMES_CRON_EXTERNAL_WORKER",
        "_HERMES_GATEWAY",
    }
)

# Layer 2: exact non-Hermes-namespace names, grouped by the §5.5 categories.
# Each name was verified against the pinned source as either a runtime code
# read (direct os.environ/os.getenv or a wrapper/kwarg/tuple-loop
# indirection in agent/, tools/, plugins/, gateway/, cron/, hermes_cli/,
# tui_gateway/) or part of Hermes's documented env surface. The sole
# exception is SIGNAL_ALLOW_ALL_USERS: the pinned source documents it
# (website/docs/reference/environment-variables.md) and lists it in
# Hermes's own behavioral inventory (tests/conftest.py), but runtime code
# does not read it at this commit — kept as a conservative scrub entry.
# AryaOS itself reads none of these (verified against backend/app and
# .env.example).
HERMES_EXTERNAL_ENV_SCRUB: frozenset[str] = frozenset(
    {
        # Gateway API server bind/auth (gateway/config_env.py,
        # gateway/platforms/api_server.py, agent/secret_scope.py).
        "API_SERVER_CORS_ORIGINS",
        "API_SERVER_ENABLED",
        "API_SERVER_HOST",
        "API_SERVER_KEY",
        "API_SERVER_MODEL_NAME",
        "API_SERVER_PORT",
        # Gateway enablement, relay, proxy, health (gateway/).
        "GATEWAY_ALLOWED_USERS",
        "GATEWAY_ALLOW_ALL_USERS",
        "GATEWAY_HEALTH_TIMEOUT",
        "GATEWAY_HEALTH_URL",
        "GATEWAY_MULTIPLEX_PROFILES",
        "GATEWAY_PROXY_KEY",
        "GATEWAY_PROXY_URL",
        "GATEWAY_RELAY_BOT_IDS",
        "GATEWAY_RELAY_DELIVERY_KEY",
        "GATEWAY_RELAY_DISPLAY_NAME",
        "GATEWAY_RELAY_ENROLL_TOKEN",
        "GATEWAY_RELAY_ID",
        "GATEWAY_RELAY_PLATFORMS",
        "GATEWAY_RELAY_ROUTE_KEYS",
        "GATEWAY_RELAY_SECRET",
        "GATEWAY_RELAY_URL",
        # Platform adapter auth bypass (plugins/platforms/*/adapter.py,
        # gateway/authz_mixin.py; full family from tests/conftest.py).
        "DISCORD_ALLOWED_USERS",
        "DISCORD_ALLOW_ALL_USERS",
        "DINGTALK_ALLOWED_USERS",
        "EMAIL_ALLOWED_USERS",
        "EMAIL_ALLOW_ALL_USERS",
        "FEISHU_ALLOWED_USERS",
        "MATTERMOST_ALLOWED_USERS",
        "MATRIX_ALLOWED_USERS",
        "PHOTON_ALLOWED_USERS",
        "QQ_ALLOWED_USERS",
        "QQ_GROUP_ALLOWED_USERS",
        "SIGNAL_ALLOWED_USERS",
        "SIGNAL_ALLOW_ALL_USERS",
        "SIGNAL_GROUP_ALLOWED_USERS",
        "SLACK_ALLOWED_USERS",
        "SLACK_ALLOW_ALL_USERS",
        "SMS_ALLOWED_USERS",
        "SMS_ALLOW_ALL_USERS",
        "TELEGRAM_ALLOWED_USERS",
        "TELEGRAM_ALLOW_ALL_USERS",
        "TELEGRAM_GROUP_ALLOWED_CHATS",
        "TELEGRAM_GROUP_ALLOWED_USERS",
        "WECOM_ALLOWED_USERS",
        "WHATSAPP_ALLOWED_USERS",
        "WHATSAPP_ALLOW_ALL_USERS",
        # Browser/computer-use tool pre-configuration (tools/).
        "AGENT_BROWSER_ENGINE",
        "AGENT_BROWSER_EXECUTABLE_PATH",
        "AGENT_BROWSER_HEADED",
        "BROWSER_CDP_URL",
        "BROWSER_INACTIVITY_TIMEOUT",
        "BROWSERBASE_ADVANCED_STEALTH",
        "BROWSERBASE_KEEP_ALIVE",
        "BROWSERBASE_PROXIES",
        "BROWSERBASE_SESSION_TIMEOUT",
        "CAMOFOX_URL",
        "PLAYWRIGHT_BROWSERS_PATH",
        # Terminal tool pre-configuration (tools/, gateway/run.py,
        # agent/runtime_cwd.py; container/docker keys via tests/conftest.py).
        "MESSAGING_CWD",
        "TERMINAL_CONTAINER_CPU",
        "TERMINAL_CONTAINER_DISK",
        "TERMINAL_CONTAINER_MEMORY",
        "TERMINAL_CONTAINER_PERSISTENT",
        "TERMINAL_CWD",
        "TERMINAL_DOCKER_MOUNT_CWD_TO_WORKSPACE",
        "TERMINAL_DOCKER_ORPHAN_REAPER",
        "TERMINAL_DOCKER_PERSIST_ACROSS_PROCESSES",
        "TERMINAL_DOCKER_RUN_AS_HOST_USER",
        "TERMINAL_DOCKER_VOLUMES",
        "TERMINAL_ENV",
        "TERMINAL_HOME_MODE",
        "TERMINAL_LOCAL_MEMORY_MAX_MB",
        "TERMINAL_SANDBOX_DIR",
        "TERMINAL_SCRATCH_DIR",
        "TERMINAL_SSH_HOST",
        "TERMINAL_SSH_PORT",
        "TERMINAL_SSH_USER",
        "TERMINAL_TIMEOUT",
        "TERMINAL_VERCEL_RUNTIME",
        # Credential injected into the sudo-capable terminal tool
        # (tools/terminal_tool_sudo.py).
        "SUDO_PASSWORD",
        # Security-scanner binary override (tools/tirith_security.py).
        "TIRITH_BIN",
        # External-agent credential/config bridges
        # (agent/anthropic_credentials.py, agent/copilot_acp_client.py,
        # hermes_cli/auth_codex.py, plugins/platforms/a2a/).
        "A2A_PORT",
        "A2A_PROVIDER_ORG",
        "A2A_PROVIDER_URL",
        "A2A_REPLY_TIMEOUT",
        "CLAUDE_CONFIG_DIR",
        "CODEX_HOME",
        "COPILOT_ACP_BASE_URL",
        "COPILOT_CLI_PATH",
        "COPILOT_GH_HOST",
        "GH_TOKEN",
        "GITHUB_TOKEN",
        # Managed tool gateway routing (tools/managed_tool_gateway.py).
        "TOOL_GATEWAY_DOMAIN",
        "TOOL_GATEWAY_SCHEME",
        "TOOL_GATEWAY_USER_TOKEN",
    }
)


@dataclass(frozen=True)
class HermesEnvScrubResult:
    """Outcome of the single pre-import scrub step.

    `removed` holds the sorted names that were present and removed. Values
    are deliberately not captured.
    """

    removed: tuple[str, ...]


def _matches_scrub_rules(name: str) -> bool:
    return name.startswith(HERMES_ENV_SCRUB_PREFIXES) or (
        name in HERMES_EXTERNAL_ENV_SCRUB
    )


def get_hermes_scrub_names(environ: Mapping[str, str]) -> tuple[str, ...]:
    """Return the sorted names in `environ` matched by the scrub rules.

    Pure function over the given mapping; no mutation. Names only, never
    values.
    """
    return tuple(sorted(name for name in environ if _matches_scrub_rules(name)))


def scrub_hermes_environment(environ=None) -> HermesEnvScrubResult:
    """Perform the single §5.5 pre-import scrub step.

    Removes (never overrides) every matched variable from `environ`
    (default: the real process environment), verifies absence afterwards,
    and returns the sorted names removed. Raises HermesEnvScrubError on any
    residual match — the caller must then refuse to import Hermes.
    """
    target = os.environ if environ is None else environ
    removed = get_hermes_scrub_names(target)
    for name in removed:
        del target[name]
    residual = get_hermes_scrub_names(target)
    if residual:
        raise HermesEnvScrubError(
            [
                (
                    "scrub_failed",
                    f"environment variable {name} still matches the Hermes scrub "
                    f"rules after removal; refusing to import Hermes",
                )
                for name in residual
            ]
        )
    return HermesEnvScrubResult(removed=removed)
