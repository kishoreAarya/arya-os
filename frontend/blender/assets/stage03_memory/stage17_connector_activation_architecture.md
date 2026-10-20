# AryaOS V1 — Stage 17: Real Connector Activation & Controlled Integration Architecture

## 1. Architectural Mission & Boundary Hierarchy

Stage 17 introduces controlled, secure, real external connectivity to external services (e.g., GitHub, Google Drive) while maintaining strict architectural boundaries across AryaOS V1.

### Boundary Separation Principle

```
+-----------------------------------------------------------------------------------+
|                        Stage 07: Execution Gateway                                |
|        (Sole boundary for AI Provider / LLM Reasoning — Gemini, Claude, GPT)      |
+-----------------------------------------------------------------------------------+
                                         │
                                         ▼
+-----------------------------------------------------------------------------------+
|                     Stage 16: Connector Fabric & Identity                         |
|   (Authority boundary: "IS ARYAOS AUTHORIZED TO USE THAT CONNECTION?")            |
|   - ConnectorRegistry, PermissionEngine, AgentCapabilityGrants, MissionGrants    |
+-----------------------------------------------------------------------------------+
                                         │
                                         ▼
+-----------------------------------------------------------------------------------+
|                     Stage 15: Universal Action Bus                                |
|   (Execution boundary: "EXECUTE EXTERNAL ACTION WITH POLICIES & AUDITING")        |
|   - ActionBusService, ActionAuthorizationService, ActionReconciliationService     |
+-----------------------------------------------------------------------------------+
                                         │
                                         ▼
+-----------------------------------------------------------------------------------+
|                 Stage 17: Real Connector Activation & Transport                  |
|   (Connectivity boundary: "HOW CAN ARYAOS SECURELY CONNECT TO EXTERNAL API?")    |
|   - ConnectorInstallationService, OAuthBoundary, CredentialResolver               |
|   - Real Capability Adapters (GitHub, Google Drive), ConnectorTransports          |
+-----------------------------------------------------------------------------------+
```

### Absolute Rules Maintained
1. **Execution Gateway Inviolability**: Stage 17 makes zero LLM calls and bypasses neither `executionGateway.execute()` nor provider governance.
2. **Action Bus Exclusivity**: All external operations flow exclusively through `actionBusService.execute()`. No adapter executes autonomously outside this pipeline.
3. **Connector Fabric Authority**: Stage 17 does not grant permissions or self-authorize. It verifies that valid `AgentCapabilityGrant` and `MissionCapabilityGrant` intersections exist before dispatching to transport.
4. **Zero-Secret Persistence Invariant**: Raw tokens, client secrets, and bearer strings never enter persistent storage, LocalStorage, ExecutionPersistence, Knowledge Graph, or log traces. Only opaque, non-sensitive `ConnectorCredentialRef` handles are persisted.

---

## 2. Controlled Installation Lifecycle

Every connector follows an explicit, governed state machine before reaching active status:

```
[ DISCOVERED ]
      │ (configure)
      ▼
[ CONFIGURING ]
      │ (request human signoff)
      ▼
[ AWAITING_HUMAN_AUTHORIZATION ]
      │ (explicit human signoff)
      ▼
[ AUTHENTICATING ]
      │ (OAuth code exchange / credential receipt)
      ▼
[ CONNECTED ]
      │ (health ping & scope check)
      ▼
[ HEALTH_CHECK ]
      │ (all checks passing)
      ▼
[ ACTIVE ]
```

### Lifecycle Rules & Invariants
- Direct jumps (such as `DISCOVERED -> ACTIVE`) are strictly rejected with lifecycle transition errors.
- Autonomous agents or automated systems CANNOT approve installation. Only explicit human operators (`OPERATOR_*`, `ADMIN_*`) can sign off on connector installation.
- At any point, a connector can transition to `SUSPENDED`, `REVOKED`, or `DISABLED`.
- Once `REVOKED`, a connector is permanently disabled and its credential handle is rendered invalid.

---

## 3. Ephemeral Credential Resolution Protocol

To prevent raw credentials from being exposed:
1. `Connector` records hold only `CredentialRef` (containing `credentialId`, `connectorId`, `credentialType`, `status`, and non-sensitive `metadata`).
2. When an authorized action requires transport execution, `CredentialResolver.resolve(ref)` accesses the secure in-memory store.
3. An `EphemeralCredential` object is synthesized containing HTTP headers (e.g. `Authorization: Bearer [ephemeral_token]`).
4. The transport request is dispatched.
5. In a strict `finally` block, all local references to `EphemeralCredential` are zeroed out and garbage collected.
6. If any transport error occurs, `CredentialResolver.sanitizeError(err)` strips bearer tokens, passwords, and secrets before bubbling to logs or Action Bus results.

---

## 4. Real Connector Adapters

- **GitHub Connector Adapter (`GitHubConnectorAdapter`)**:
  - Capabilities: `github.issue_read`, `github.issue_write` (aliased to `github.read_issue`, `github.create_issue`).
  - Supported operations: `get_issue`, `create_issue`.
  - Scoped to authorized repositories (`aryaos/*`).
  - High-risk operations (`github.issue_write`) strictly require human operator approval.
  - Normalizes HTTP 429 rate limit responses into `RATE_LIMIT` retries with backoff.

- **Google Drive Connector Adapter (`GoogleDriveConnectorAdapter`)**:
  - Capabilities: `google_drive.list_files`, `google_drive.read_file`.
  - Read-only operations (`list_files`, `read_file`).
  - Scoped strictly to authorized path trees (`/drive/root`, `/drive/workspace`).
  - Path traversal attacks (`../`, `/etc/shadow`) are intercepted and rejected prior to transport invocation.

---

## 5. Spatial HUD Integration

Three DOM-only overlay HUD panels are integrated into `SpatialCommandConsole`:
1. `connector-activation-hud`: Displays connector statuses, active installations, and lifecycle states.
2. `authentication-status-hud`: Displays OAuth session states, expiry indicators, and pending authorizer reviews.
3. `credential-status-hud`: Displays non-sensitive credential validity and isolation health.

All 3 HUD panels render as 2D React DOM overlays, introducing **0 additional WebGL draw calls**, maintaining 53–54 draw calls, 86,842 triangles, and 1.12–1.85 ms frame timings.
