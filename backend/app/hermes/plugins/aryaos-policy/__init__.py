"""AryaOS policy plugin — the ONLY Hermes plugin AryaOS permits (§5.3/§4).

Loaded by Hermes plugin discovery from the AryaOS-controlled plugin
directory (HERMES_BUNDLED_PLUGINS, set by app.hermes.runtime after the
§5.5 scrub). Hermes loads this file via spec_from_file_location and calls
``register(ctx)`` (plugins_loader._load_plugin_scoped), so plain absolute
imports resolve against the AryaOS process's sys.path.

The per-job AuthorizationContext is bound by the runtime before discovery
(app.hermes.runtime.set_active_authorization_context); if it is absent
this register() raises, the plugin fails to load, and the runtime's
plugin-surface verification fails closed (§4.3).
"""


def register(ctx) -> None:
    from app.hermes.limits import make_limit_enforcing_hook
    from app.hermes.policy import make_pre_tool_call_hook
    from app.hermes.runtime import get_active_authorization_context, get_active_job_ledger

    hook = make_pre_tool_call_hook(get_active_authorization_context())
    ledger = get_active_job_ledger()
    if ledger is not None:
        # §12 enforcement wraps the §4 decision hook; §4 directives pass
        # through verbatim and the wrapper carries the plugin marker.
        hook = make_limit_enforcing_hook(hook, ledger)
    ctx.register_hook("pre_tool_call", hook)
