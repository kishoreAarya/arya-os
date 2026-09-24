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
    from app.hermes.policy import register_policy_plugin
    from app.hermes.runtime import get_active_authorization_context

    register_policy_plugin(ctx, get_active_authorization_context())
