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
    from app.hermes.capabilities import (
        CAPABILITY_TOOLSET,
        capability_tool_definitions,
        make_capability_tool_handler,
        make_capability_validating_hook,
    )
    from app.hermes.limits import make_limit_enforcing_hook
    from app.hermes.policy import make_pre_tool_call_hook
    from app.hermes.runtime import get_active_authorization_context, get_active_job_ledger

    # Hook chain (§4 authorization -> §9 schema validation -> §12 limits,
    # outermost): §4 directives pass through verbatim; each wrapper
    # carries the plugin marker so §4.3 verification still passes.
    hook = make_pre_tool_call_hook(get_active_authorization_context())
    hook = make_capability_validating_hook(hook)
    ledger = get_active_job_ledger()
    if ledger is not None:
        hook = make_limit_enforcing_hook(hook, ledger)
    ctx.register_hook("pre_tool_call", hook)

    # §9 tool exposure: ONLY the frozen registry determines what is
    # registered — toolset "aryaos", no override, no model input.
    for name, schema in capability_tool_definitions().items():
        ctx.register_tool(
            name=name,
            toolset=CAPABILITY_TOOLSET,
            schema=schema,
            handler=make_capability_tool_handler(name),
            is_async=True,
        )
