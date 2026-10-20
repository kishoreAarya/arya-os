# AryaOS V1 Stage 16 — Connector Fabric Architecture

## 1. Overview & Architectural Role

The **Connector Fabric** introduces the secure, provider-neutral lifecycle infrastructure for connecting external systems to AryaOS. It acts as the trusted identity, authentication abstraction, and permission management layer that mediates between AI actors and the Stage 15 Universal Action Bus.

---

## 2. The Complete Security & Execution Chain

Stage 16 establishes the end-to-end authorization and execution chain:

```
+-----------------------------------------------------------------------------------+
|                                  AGENT (Stage 10)                                 |
+-----------------------------------------------------------------------------------+
                                         │
                                         ▼
+-----------------------------------------------------------------------------------+
|                                 MISSION (Stage 12)                                |
+-----------------------------------------------------------------------------------+
                                         │
                                         ▼
+-----------------------------------------------------------------------------------+
|                             CONNECTOR FABRIC (Stage 16)                           |
|  * Credential Boundary (`CredentialRef`, zero raw secrets)                        |
|  * Scoped Permission Matching (`ConnectorPermission`, `ConnectorScope`)           |
|  * Permission Versioning (`permissionVersion` invalidation)                       |
|  * Health Gatekeeping (`ConnectorHealth`, bounded checks)                         |
+-----------------------------------------------------------------------------------+
                                         │
                                         ▼
+-----------------------------------------------------------------------------------+
|                           UNIVERSAL ACTION BUS (Stage 15)                         |
|  * Idempotency Check & De-duplication                                            |
|  * Schema Validation                                                              |
|  * Sandboxing & Traversal Prevention                                              |
|  * Capability Adapter Dispatch                                                    |
+-----------------------------------------------------------------------------------+
                                         │
                                         ▼
+-----------------------------------------------------------------------------------+
|                     HUMAN APPROVAL (CRITICAL / High Risk Actions)                 |
+-----------------------------------------------------------------------------------+
                                         │
                                         ▼
+-----------------------------------------------------------------------------------+
|                                EXTERNAL SYSTEM                                    |
|  * GitHub API / Sandboxed Filesystem / HTTP Endpoints / Slack Notifications       |
+-----------------------------------------------------------------------------------+
```

---

## 3. Critical Separation of Concepts

AryaOS strictly maintains clear boundaries between distinct architectural concerns:

1. **CONNECTOR**: Authenticated external system connection with lifecycle state, health, scopes, and credential reference (e.g. `connector_github`).
2. **CAPABILITY**: Specific operation exposed by a connector or system (e.g. `github.create_issue`).
3. **PERMISSION**: Scoped authorization required to invoke an operation (e.g. `perm_gh_write` on `aryaos/*`).
4. **CREDENTIAL**: Secret required to authenticate with the external system (encapsulated in `CredentialRef`; raw secrets never enter core state).
5. **ACTION**: Concrete invocation request processed by Stage 15 Action Bus (`ActionRequest`).
6. **PROVIDER**: AI LLM reasoning backend handled exclusively by Stage 07 Execution Gateway (`executionGateway.execute()`).

---

## 4. Key Services & Domain Models

* **`ConnectorRegistry` (`src/services/connectorRegistry.ts`)**: Catalog of registered connectors with deterministic registration and duplicate prevention.
* **`ConnectorLifecycleService` (`src/services/connectorLifecycleService.ts`)**: State machine governing transitions (`DISCOVERED` $\to$ `CONFIGURING` $\to$ `AUTHENTICATING` $\to$ `CONNECTED` $\to$ `ACTIVE` $\to$ `REVOKED`), preventing invalid state jumps.
* **`CredentialBoundary` (`src/services/credentialBoundary.ts`)**: Generates non-sensitive `ConnectorCredentialRef` objects, evaluates expiration, and asserts zero raw credential leakage.
* **`ConnectorPermissionService` (`src/services/connectorPermissionService.ts`)**: Enforces default-DENY authorization, agent grants, mission grants, resource scope matching, and permission versioning.
* **`ConnectorHealthService` (`src/services/connectorHealthService.ts`)**: Bounded on-demand health verification and health-based action blocking.
* **`ConnectorDiscoveryService` (`src/services/connectorDiscoveryService.ts`)**: Catalog of discoverable connector blueprints with governance checks for privileged installation.
