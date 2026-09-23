"""
AryaOS-owned Hermes integration surface (V2).

Spec: docs/architecture/HERMES_INTEGRATION_SPEC.md.

Slice 1 contains only the fail-closed configuration validation layer
(app.hermes.config). The runtime adapter, policy plugin, and typed
capabilities are intentionally absent and arrive in later slices.
"""
