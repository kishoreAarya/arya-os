"""
AryaOS-owned Hermes integration surface (V2).

Spec: docs/architecture/HERMES_INTEGRATION_SPEC.md.

Slice 1 added the fail-closed configuration validation layer
(app.hermes.config). Slice 3 added source-integrity verification and the
verified build-boundary record generator (app.hermes.source). Slice 4
added the §5.5 pre-import environment scrub (app.hermes.env_scrub).
Slice 5 added the frozen §5.1 toolset allowlist and its fail-closed
validation (app.hermes.toolsets). The runtime adapter, policy plugin, and
typed capabilities are intentionally absent and arrive in later slices.
"""
