"""
Frozen toolset allowlist and fail-closed validation for Hermes (V2).

Spec: docs/architecture/HERMES_INTEGRATION_SPEC.md — §5.1 (toolsets),
§16/T6 (dangerous toolsets unavailable; ``enabled_toolsets is None``
rejected by startup validation), §15 (upgrade policy for any change).

Contract:
- The ONLY Hermes toolsets AryaOS may ever pass as ``enabled_toolsets`` are
  the names in HERMES_TOOLSET_ALLOWLIST. Every other name — dangerous
  categories, legacy aliases, pseudo-toolsets ("all", "*"), plugin/MCP
  toolset names, typos — is rejected by validate_enabled_toolsets() and
  must never reach Hermes.
- Why AryaOS validates instead of trusting Hermes: the pinned source FAILS
  OPEN on unknown toolset names — ``model_tools._apply_toolset_selection``
  prints a warning and silently skips them (model_tools.py:302-305 at the
  pin) — and ``enabled_toolsets=None`` exposes the FULL tool surface
  (model_tools.py:317-325). Authorization is AryaOS-owned (§4.1); this
  module is the fail-closed startup-validation half of that boundary.
- The allowlist approach is mandatory (§5.1): adding a toolset means
  editing this frozen constant under §15 review, never editing a denylist.

Enumeration provenance (pinned commit c0d7294769a38c17ceae51d8f7995e66e1dcae27):
- HERMES_STATIC_TOOLSETS_AT_PIN is the complete static ``TOOLSETS`` dict of
  ``toolsets.py`` (61 names). It is an audit trail: the runtime compares
  against it and any pin change (§15) trips review of this file.
- HERMES_TOOLSET_ALLOWLIST is the subset AryaOS permits. Everything else is
  excluded, with the controlling reason per group:
  * shell/terminal, arbitrary file write, browser, code execution/IDE,
    delegation/subagents, MCP, cron/scheduler, messaging/communication —
    the §5.1 dangerous categories (terminal, debugging, coding, file,
    skills [skill_manage is a create/patch/delete file engine], browser,
    code_execution, computer_use, delegation, kanban, connections, cronjob,
    memory [§6], session_search [§6], all hermes-* bundles and platform
    toolsets, bot_room, homeassistant, spotify, project, desktop_ui,
    setup).
  * clarify — excluded by deliberate operator policy (minimum exposed
    Hermes surface), NOT because it was proven to fit a §5.1 dangerous
    category. Source review at the pin (operator decision recorded after
    review): clarify_tool has no filesystem, network, subprocess, or
    credential behavior, and it is inert in the embedded runtime —
    agent.clarify_callback defaults to None (agent/agent_init.py:2327),
    only the §3-excluded CLI/gateway/TUI runtimes inject a callback, and
    without one the tool returns a not-available error
    (tools/clarify_tool.py). The specification neither requires it nor
    assigns it to an excluded category.
  * web, search, x_search, vision, video — arbitrary network egress beyond
    AryaOS-approved model/provider endpoints (§16/T11; vision_tools.py
    fetches arbitrary HTTP(S) URLs). Sanctioned research is the §9
    ``research.search`` typed capability.
  * image_gen, video_gen, tts — generation through Hermes's own provider
    configuration, bypassing AryaOS provider routing (§1, §9
    ``provider.generate``, AGENTS.md §9).
  * context_engine — statically empty, dynamically populated by the active
    context engine (toolsets.py:134; registration at agent_init.py:2061 ff);
    not statically boundable, so excluded fail-closed.
  * safe — composite of web + vision + image_gen (all excluded above).
- "todo" is the sole permitted static toolset: todo_list is in-memory,
  per-agent planning state with no filesystem, network, or subprocess
  behavior (tools/todo_tool.py). §5.1 requires the allowlist to be
  non-empty; "todo" is the only static toolset with no §5.1 dangerous
  category and no source-verified boundary violation.

The AryaOS typed-capability toolset (§9) does not exist yet; when that
slice registers one, its name joins this frozen constant through the §15
change process. Hermes is not imported here.
"""


class HermesToolsetError(RuntimeError):
    """Invalid ``enabled_toolsets`` value. Fail-closed: the caller must not
    construct (or continue into) any Hermes agent path when this is raised.

    `violations` is a list of (code, detail) tuples, mirroring
    app.hermes.config.HermesConfigError.
    """

    def __init__(self, violations: list[tuple[str, str]]):
        self.violations = violations
        rendered = "; ".join(f"{code}: {detail}" for code, detail in violations)
        super().__init__(f"invalid Hermes enabled_toolsets ({rendered})")


# The complete static toolset registry at the approved pin (audit trail;
# enforceable surface is the allowlist below).
HERMES_STATIC_TOOLSETS_AT_PIN: frozenset[str] = frozenset(
    {
        "bot_room",
        "browser",
        "clarify",
        "code_execution",
        "coding",
        "computer_use",
        "connections",
        "context_engine",
        "cronjob",
        "debugging",
        "delegation",
        "desktop_ui",
        "discord",
        "discord_admin",
        "feishu_doc",
        "feishu_drive",
        "file",
        "hermes-acp",
        "hermes-api-server",
        "hermes-bluebubbles",
        "hermes-cli",
        "hermes-cron",
        "hermes-dingtalk",
        "hermes-discord",
        "hermes-email",
        "hermes-feishu",
        "hermes-gateway",
        "hermes-homeassistant",
        "hermes-matrix",
        "hermes-mattermost",
        "hermes-qqbot",
        "hermes-signal",
        "hermes-slack",
        "hermes-sms",
        "hermes-telegram",
        "hermes-webhook",
        "hermes-wecom",
        "hermes-wecom-callback",
        "hermes-weixin",
        "hermes-whatsapp",
        "hermes-yuanbao",
        "homeassistant",
        "image_gen",
        "kanban",
        "memory",
        "project",
        "safe",
        "search",
        "session_search",
        "setup",
        "skills",
        "spotify",
        "terminal",
        "todo",
        "tts",
        "video",
        "video_gen",
        "vision",
        "web",
        "x_search",
        "yuanbao",
    }
)

# The frozen §5.1 allowlist: the ONLY toolset names AryaOS may ever pass to
# Hermes as enabled_toolsets. Changes follow §15 (source verification +
# runtime security verification + architecture review + explicit approval).
HERMES_TOOLSET_ALLOWLIST: tuple[str, ...] = ("todo",)


def get_frozen_enabled_toolsets() -> tuple[str, ...]:
    """The validated ``enabled_toolsets`` value the runtime adapter will
    pass to Hermes: the frozen allowlist, sorted, as a new tuple each call.
    """
    return tuple(sorted(HERMES_TOOLSET_ALLOWLIST))


def validate_enabled_toolsets(value: object) -> tuple[str, ...]:
    """Fail-closed §5.1 startup validation of an ``enabled_toolsets`` value.

    Returns the validated names as a sorted tuple. Raises
    HermesToolsetError listing every violation otherwise:

    - None            -> "toolsets_none"   (None means FULL surface at the
                      pin; rejected per §5.1/T6)
    - empty           -> "toolsets_empty"  (§5.1: non-empty is mandatory)
    - non-sequence    -> "toolsets_type"
    - non-str member  -> "toolset_not_str"
    - duplicate name  -> "toolset_duplicate"
    - any name not in the frozen allowlist -> "toolset_not_allowed"
      (covers dangerous categories, legacy aliases such as
      ``terminal_tools`` (model_tools.py:176 at the pin), pseudo-toolsets
      ``all``/``*``, plugin/MCP toolset names, and typos — Hermes itself
      fails open on unknown names, so AryaOS must fail closed here).
    """
    if value is None:
        raise HermesToolsetError(
            [
                (
                    "toolsets_none",
                    "enabled_toolsets must never be None: at the pinned commit "
                    "None exposes the FULL tool surface (model_tools.py:317-325); "
                    "an explicit non-empty allowlist is required (§5.1)",
                )
            ]
        )
    if isinstance(value, (str, bytes)) or not isinstance(value, (list, tuple, set, frozenset)):
        raise HermesToolsetError(
            [
                (
                    "toolsets_type",
                    f"enabled_toolsets must be a list/tuple of toolset names, got {type(value).__name__}",
                )
            ]
        )
    names = list(value)
    if not names:
        raise HermesToolsetError(
            [
                (
                    "toolsets_empty",
                    "enabled_toolsets must be a non-empty allowlist (§5.1); "
                    "unbounded is not permitted",
                )
            ]
        )

    violations: list[tuple[str, str]] = []
    seen: set[str] = set()
    for item in names:
        if not isinstance(item, str):
            violations.append(
                (
                    "toolset_not_str",
                    f"enabled_toolsets entries must be str, got {type(item).__name__}",
                )
            )
            continue
        if item in seen:
            violations.append(
                ("toolset_duplicate", f"enabled_toolsets contains duplicate entry {item!r}")
            )
            continue
        seen.add(item)
        if item not in HERMES_TOOLSET_ALLOWLIST:
            violations.append(
                (
                    "toolset_not_allowed",
                    f"toolset {item!r} is not in the frozen §5.1 allowlist "
                    f"{list(HERMES_TOOLSET_ALLOWLIST)}; adding a toolset requires "
                    "editing the frozen allowlist under §15 review",
                )
            )
    if violations:
        raise HermesToolsetError(violations)
    return tuple(sorted(seen))
