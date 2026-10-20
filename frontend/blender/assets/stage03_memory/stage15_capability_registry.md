# AryaOS V1 Stage 15 — Capability Registry Specification

## 1. Overview

The **Capability Registry** (`src/services/capabilityRegistry.ts`) serves as the dynamic catalog of external capabilities available to AryaOS. It defines the formal interfaces, parameter requirements, execution semantics, risk classifications, and sandbox constraints for all integrated tools and integrations.

---

## 2. Capability Data Model

Each registered capability conforms to the `ActionCapability` interface:

```typescript
export interface ActionCapability {
  capabilityId: string;                     // Unique identifier (e.g. 'filesystem.write')
  name: string;                             // Human-readable capability name
  type: ActionCapabilityType;               // 'FILE' | 'WEB' | 'HTTP' | 'GITHUB' | 'NOTIFICATION' | 'MEDIA' | 'CONNECTOR' | 'CUSTOM'
  description: string;                      // Operational description
  version: string;                          // Semantic version
  riskLevel: ActionRiskLevel;               // 'LOW' | 'MEDIUM' | 'HIGH' | 'CRITICAL'
  requiredPermissions: ActionPermission[];  // Minimal permissions required
  supportedOperations: string[];            // Supported operations (e.g. ['read_file', 'list_directory'])
  inputSchema: ActionSchemaDefinition;      // JSON schema for parameter validation
  outputSchema?: ActionSchemaDefinition;     // Output shape definition
  timeoutMs: number;                        // Execution timeout limit
  retryPolicy: ActionRetryPolicy;           // Max retries, backoff, and retryable error categories
  idempotencyPolicy: ActionIdempotencyPolicy;// Deduplication rules
  availability: 'ONLINE' | 'DEGRADED' | 'OFFLINE';
  sandboxConfig?: ActionSandboxConfig;      // Sandboxing boundaries
}
```

---

## 3. Registered Core Capabilities

| Capability ID | Type | Risk Level | Required Permissions | Supported Operations | Idempotent |
|---|---|---|---|---|---|
| `filesystem.read` | `FILE` | `LOW` | `['FILES_READ']` | `read_file`, `list_directory` | Yes |
| `filesystem.write` | `FILE` | `HIGH` / `CRITICAL` | `['FILES_WRITE']` | `write_file`, `delete_file` | Yes (keyed) |
| `web.search` | `WEB` | `LOW` | `['WEB_SEARCH']` | `query` | Yes |
| `external.http` | `HTTP` | `MEDIUM` / `HIGH` | `['NETWORK_EGRESS']` | `get`, `post`, `put`, `delete` | Method-dependent |
| `github.read_issue` | `GITHUB` | `LOW` | `['GITHUB_READ']` | `get_issue`, `list_issues` | Yes |
| `github.create_issue` | `GITHUB` | `MEDIUM` | `['GITHUB_WRITE']` | `create_issue`, `comment_issue` | Yes (keyed) |
| `notification.send` | `NOTIFICATION` | `LOW` | `['NOTIFICATION_SEND']` | `send_message`, `alert` | Yes (keyed) |

---

## 4. Schema Validation & Defensive Typing

The Capability Registry enforces parameter checks before dispatching any request to adapters:
* **Required Properties**: Evaluates whether all required fields are provided.
* **Type Safety**: Verifies primitives (`string`, `number`, `boolean`, `array`, `object`).
* **Enum Enforcement**: Constrains string values to enumerated options where declared.
* **Payload Boundary**: Blocks oversized inputs prior to network transmission.
