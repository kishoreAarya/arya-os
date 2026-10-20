# AryaOS V1 Stage 21 — Bounded Context Construction & Sanitization Model

## 1. Overview

The `GovernanceContextService` transforms arbitrary runtime events, tool requests, trigger executions, and mission dispatches into a strictly bounded, sanitized, and deeply typed `GovernanceContext` structure. 

To eliminate attack vectors such as prototype pollution, unbounded payload memory exhaustion, and ambient credential leaks, all incoming requests pass through deterministic sanitization filters before any policy evaluation occurs.

---

## 2. Sanitization & Security Constraints

### 2.1 Prototype Pollution Protection
All inputs are stripped of prototype pollution keys. Keys matching `__proto__`, `constructor`, or `prototype` are excised recursively across all object tiers.

### 2.2 Recursive Credential Scrubbing
To guarantee zero secret persistence in policy traces and journals, parameters are scrubbed of sensitive fields:
- `apiKey`, `token`, `secret`, `password`, `authHeader`, `credentialRef`, `privateKey`, `accessToken`, `bearerToken`
- Values matching credential patterns are replaced with `[REDACTED]` or omitted entirely.

### 2.3 Depth & Cardinality Bounds
- **Maximum Nesting Depth**: Limited to **5 levels**. Keys exceeding depth 5 are truncated to prevent call-stack exhaustion.
- **Maximum Key Cardinality**: Limited to **50 keys per object level**. Prevents payload bloating attacks.

---

## 3. Context Schema & Fields

```typescript
export interface GovernanceContext {
  requestId: string;
  correlationId: string;
  actor: GovernanceActor;
  scopeType: PolicyScopeType;
  targetId?: string;
  capability?: string;
  actionType?: string;
  missionId?: string;
  goalId?: string;
  triggerId?: string;
  connectorId?: string;
  providerId?: string;
  riskLevel: ActionRiskLevel;
  sanitizedParameters: Record<string, unknown>;
  currentMissionState?: string;
  currentConnectorState?: string;
  currentPermissionScopes?: string[];
  activeConcurrentActions?: number;
  activeConcurrentAgents?: number;
  costUsd?: number;
  tokenCount?: number;
  requestFrequency?: number;
  timestamp: number;
}
```

---

## 4. Actor Categorization & Scoping

The context service classifies actors into four explicit types with distinct authorization implications:
1. **`USER`**: Direct interactive human operator.
2. **`OPERATOR`**: Privileged operational console role.
3. **`AUTONOMOUS_AGENT`**: Autonomous AI worker agent (governed by Default DENY).
4. **`SYSTEM`**: Internal runtime process or scheduler daemon.

Scope mapping automatically resolves the most specific scope applicable:
- If `actionType` is present -> `ACTION_TYPE`
- If `connectorId` is present -> `CONNECTOR`
- If `missionId` is present -> `MISSION`
- If `triggerId` is present -> `TRIGGER`
- If `targetSystem` is present -> `SYSTEM`
- Default fallback -> `GLOBAL`

---

## 5. Controlled Runtime Overrides

During testing, simulation, and long-horizon projection, controlled overrides can inject verified state (e.g. `currentMissionState: 'PAUSED'`, `currentConnectorState: 'UNAVAILABLE'`, `activeConcurrentActions: 5`). 
Arbitrary keys injected outside the authorized schema are strictly rejected, preventing parameter injection attacks.
