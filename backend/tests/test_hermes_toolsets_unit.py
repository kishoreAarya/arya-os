"""Unit tests for the frozen §5.1 toolset allowlist (V2).

Spec: docs/architecture/HERMES_INTEGRATION_SPEC.md — §5.1 (toolsets),
§16/T6 (dangerous toolsets unavailable; ``enabled_toolsets is None``
rejected by startup validation).

These tests cover ONLY the AryaOS-owned frozen allowlist and its
fail-closed validation. Hermes is not imported, faked, or required. The
agent-instantiation half of T6 belongs to the future runtime-adapter slice.
"""

import pytest

from app.hermes.toolsets import (
    HERMES_STATIC_TOOLSETS_AT_PIN,
    HERMES_TOOLSET_ALLOWLIST,
    HermesToolsetError,
    get_frozen_enabled_toolsets,
    validate_enabled_toolsets,
)

# Static toolset names at the pin that the spec's §5.1 dangerous categories
# (plus §6 memory, §7 delegation, §8 cron) structurally exclude. Frozen
# here so an allowlist edit that admits any of them fails loudly.
SPEC_EXCLUDED_STATIC_TOOLSETS = (
    # shell/terminal + composites carrying core tools
    "terminal",
    "debugging",
    "coding",
    "hermes-acp",
    "hermes-api-server",
    "hermes-cli",
    "hermes-cron",
    "hermes-gateway",
    "hermes-telegram",
    "hermes-discord",
    "hermes-whatsapp",
    "hermes-slack",
    "hermes-signal",
    "hermes-bluebubbles",
    "hermes-homeassistant",
    "hermes-email",
    "hermes-mattermost",
    "hermes-matrix",
    "hermes-dingtalk",
    "hermes-feishu",
    "hermes-weixin",
    "hermes-qqbot",
    "hermes-wecom",
    "hermes-wecom-callback",
    "hermes-yuanbao",
    "hermes-sms",
    "hermes-webhook",
    # arbitrary file write
    "file",
    "skills",
    # browser / code execution / desktop control
    "browser",
    "code_execution",
    "computer_use",
    # delegation / subagents / multi-agent coordination (§7)
    "delegation",
    "kanban",
    # MCP / connectors (§5.1, §5.3)
    "connections",
    # cron/scheduler (§8)
    "cronjob",
    # memory authority is AryaOS-owned (§6)
    "memory",
    "session_search",
    # messaging/communication surfaces
    "discord",
    "discord_admin",
    "yuanbao",
    "feishu_doc",
    "feishu_drive",
    "spotify",
    "bot_room",
    "homeassistant",
    # operator policy: minimum exposed surface (spec-neutral — inert in the
    # embedded runtime; see toolsets.py docstring for the recorded decision)
    "clarify",
    # network egress beyond approved endpoints (§16/T11)
    "web",
    "search",
    "x_search",
    "vision",
    "video",
    # generation bypasses AryaOS provider routing (§1, §9)
    "image_gen",
    "video_gen",
    "tts",
    # dynamic / GUI / role-gated surfaces
    "context_engine",
    "project",
    "desktop_ui",
    "setup",
    "safe",
)


def _codes(exc_info: pytest.ExceptionInfo[HermesToolsetError]) -> set[str]:
    return {code for code, _ in exc_info.value.violations}


# ---------------------------------------------------------------------------
# 1. Frozen allowlist contents
# ---------------------------------------------------------------------------

def test_allowlist_contents_are_frozen():
    assert HERMES_TOOLSET_ALLOWLIST == ("todo",)


def test_allowlist_members_exist_in_static_registry_at_pin():
    """Every allowed name must be a real static toolset at the pin (a
    typo'd allowlist entry would silently enable nothing because Hermes
    fails open on unknown names)."""
    for name in HERMES_TOOLSET_ALLOWLIST:
        assert name in HERMES_STATIC_TOOLSETS_AT_PIN


def test_allowlist_disjoint_from_spec_excluded_toolsets():
    assert not (set(HERMES_TOOLSET_ALLOWLIST) & set(SPEC_EXCLUDED_STATIC_TOOLSETS))


def test_spec_excluded_names_are_all_real_at_pin():
    """The frozen exclusion inventory must track the pinned registry, so a
    pin change (§15) that renames or removes entries trips this test."""
    for name in SPEC_EXCLUDED_STATIC_TOOLSETS:
        assert name in HERMES_STATIC_TOOLSETS_AT_PIN


def test_static_registry_size_at_pin():
    """Audit-trail constant: the pinned toolsets.py TOOLSETS dict has
    exactly 61 entries (verified by AST extraction at implementation time)."""
    assert len(HERMES_STATIC_TOOLSETS_AT_PIN) == 61


# ---------------------------------------------------------------------------
# 2. Immutability / determinism
# ---------------------------------------------------------------------------

def test_constants_are_frozen_types():
    assert isinstance(HERMES_TOOLSET_ALLOWLIST, tuple)
    assert isinstance(HERMES_STATIC_TOOLSETS_AT_PIN, frozenset)


def test_get_frozen_enabled_toolsets_is_deterministic_and_copy_safe():
    first = get_frozen_enabled_toolsets()
    second = get_frozen_enabled_toolsets()
    assert first == second == tuple(sorted(HERMES_TOOLSET_ALLOWLIST))
    assert first is not second  # fresh tuple; callers cannot mutate the constant


# ---------------------------------------------------------------------------
# 3. Fail-closed validation (§5.1 / T6)
# ---------------------------------------------------------------------------

def test_none_rejected():
    """T6: ``enabled_toolsets is None`` rejected by startup validation
    (None = FULL tool surface at the pin)."""
    with pytest.raises(HermesToolsetError) as exc_info:
        validate_enabled_toolsets(None)
    assert _codes(exc_info) == {"toolsets_none"}


def test_empty_rejected():
    with pytest.raises(HermesToolsetError) as exc_info:
        validate_enabled_toolsets([])
    assert _codes(exc_info) == {"toolsets_empty"}


def test_non_sequence_rejected():
    for bad in ("todo", 42, {"todo": True}):
        with pytest.raises(HermesToolsetError) as exc_info:
            validate_enabled_toolsets(bad)
        assert _codes(exc_info) == {"toolsets_type"}


def test_non_string_member_rejected():
    with pytest.raises(HermesToolsetError) as exc_info:
        validate_enabled_toolsets(["todo", 7])
    assert _codes(exc_info) == {"toolset_not_str"}


def test_duplicate_rejected():
    with pytest.raises(HermesToolsetError) as exc_info:
        validate_enabled_toolsets(["todo", "todo"])
    assert _codes(exc_info) == {"toolset_duplicate"}


def test_dangerous_and_unknown_names_rejected():
    """Dangerous categories, legacy aliases, pseudo-toolsets, and plugin/MCP
    names are all outside the frozen allowlist and fail closed."""
    bad_names = [
        "terminal",
        "file",
        "browser",
        "code_execution",
        "delegation",
        "connections",
        "cronjob",
        "memory",
        "session_search",
        "computer_use",
        "web",
        "vision",
        "image_gen",
        "context_engine",
        "hermes-cli",
        "hermes-gateway",
        # legacy aliases resolving to real dangerous tools (model_tools.py:176)
        "terminal_tools",
        "file_tools",
        "browser_tools",
        # pseudo-toolsets spanning everything
        "all",
        "*",
        # plugin/MCP-style names
        "mcp-aryaos",
        # typos
        "todo ",
        "TODO",
    ]
    with pytest.raises(HermesToolsetError) as exc_info:
        validate_enabled_toolsets(["todo", *bad_names])
    assert _codes(exc_info) == {"toolset_not_allowed"}
    denied = {detail.split("'")[1] for code, detail in exc_info.value.violations}
    assert set(bad_names) <= denied


def test_valid_allowlist_accepted_and_sorted():
    assert validate_enabled_toolsets(list(HERMES_TOOLSET_ALLOWLIST)) == ("todo",)
    assert validate_enabled_toolsets(tuple(HERMES_TOOLSET_ALLOWLIST)) == ("todo",)
    assert validate_enabled_toolsets(["todo"]) == ("todo",)


def test_validation_is_deterministic():
    assert validate_enabled_toolsets(["todo"]) == validate_enabled_toolsets(["todo"])


# ---------------------------------------------------------------------------
# 4. No Hermes import
# ---------------------------------------------------------------------------

def test_module_does_not_import_hermes():
    """Importing app.hermes.toolsets must not import Hermes. Checked in a
    fresh subprocess: the runtime integration tests legitimately import
    Hermes into the shared pytest process, so a process-global sys.modules
    scan would test file ordering, not this module."""
    import subprocess
    import sys as _sys
    from pathlib import Path

    backend_dir = Path(__file__).resolve().parents[1]
    code = (
        "import sys\n"
        f"sys.path.insert(0, {str(backend_dir)!r})\n"
        "import app.hermes.toolsets\n"
        "assert not any(\n"
        "    mod == 'toolsets' or mod.startswith(('toolsets.', 'model_tools', 'agent', 'hermes', 'hermes_'))\n"
        "    for mod in sys.modules), 'toolsets module imported Hermes'\n"
    )
    result = subprocess.run(
        [_sys.executable, "-c", code], capture_output=True, text=True, timeout=60
    )
    assert result.returncode == 0, result.stderr
