"""
AryaOS-owned Hermes integration surface (V2).

Spec: docs/architecture/HERMES_INTEGRATION_SPEC.md.

Slice 1 added the fail-closed configuration validation layer
(app.hermes.config). Slice 3 added source-integrity verification and the
verified build-boundary record generator (app.hermes.source). Slice 4
added the §5.5 pre-import environment scrub (app.hermes.env_scrub).
Slice 5 added the frozen §5.1 toolset allowlist and its fail-closed
validation (app.hermes.toolsets). Slice 6 added the §4 policy-gate
decision core, hook adapter, and registration assertion
(app.hermes.policy). Slice 7 added the §3 runtime-adapter boundary
(app.hermes.runtime) and the aryaos-policy plugin package
(app.hermes.plugins). Typed capabilities are intentionally absent and
arrive in later slices.
"""
