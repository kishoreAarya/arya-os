# AryaOS V1 Stage 24 — Phase 2 Authoritative Source Map
## Control-Plane Snapshot Service Integration

**Date**: October 3, 2026  
**Status**: PHASE 2 RECONNAISSANCE & ARCHITECTURAL SOURCE MAPPING  
**Principle**: The snapshot service answers *"What does the system currently know?"* and **NEVER** *"What should the system do?"*. It executes zero mutations and consumes existing authoritative singletons.

---

## 1. Authoritative Source Singletons Inventory

| Subsystem Domain | Authoritative Service Singleton | Module Path | Access Pattern | Read / Query Methods | Lifecycle / State Source |
|---|---|---|---|---|---|
| **Stage 12: Mission Control** | `missionManager` | `src/services/missionManager.ts` | Exported singleton instance | `listMissions()`, `getMission(id)` | `executionPersistence` (`envelope.missions`) |
| **Stage 20: Policy Intelligence** | `policyRegistry` | `src/services/policyRegistry.ts` | Exported singleton instance | `getRegistryVersion()`, `getAllPolicies()`, `getActivePolicies()` | Memory Map + `executionPersistence` (`envelope.policies`) |
| **Stage 21: Governance** | `governanceControlPlane` | `src/services/governanceControlPlane.ts` | Exported singleton instance | Pure inspection; historical records via `executionPersistence.getAllGovernanceDecisions()` | Memory Cache + `executionPersistence` (`envelope.governanceDecisions`) |
| **Stage 22: Operational Truth** | `operationalTruthService` | `src/services/operationalTruthService.ts` | Exported singleton instance | `isIntentOnly(state)`, `isObservedState(state)`, `reconcileOperationalTruth(params)` | Stage 22 truth state evaluator |
| **Stage 22: Causal Trace** | `causalTraceService` | `src/services/causalTraceService.ts` | Exported singleton instance | `buildCausalGraph(operationId)` | `auditEventRegistry` event index |
| **Stage 22: Audit Event Registry** | `auditEventRegistry` | `src/services/auditEventRegistry.ts` | Exported singleton instance | `getAllEvents()`, `getEventsByOperationId(id)`, `getEventsByMissionId(id)` | In-memory append-only chronological index |
| **Stage 23: Recovery Control** | `recoveryControlPlane` | `src/services/recoveryControlPlane.ts` | Exported singleton instance | `getActiveDecision(id)`, plus historical records via `executionPersistence.getAllRecoveryControlDecisions()` | Active decisions Map + Stage 09 persistence |
| **Stage 09: Execution Persistence** | `executionPersistence` | `src/services/executionPersistence.ts` | Exported singleton instance | `loadEnvelope()`, `getTelemetry()`, `isDurableStorageActive()`, `getAllGovernanceDecisions()`, `getAllRecoveryControlDecisions()` | LocalStorage with safe In-Memory fallback |
| **Stage 16: Connector Fabric** | `connectorRegistry` | `src/services/connectorRegistry.ts` | Exported singleton instance | `listConnectors()`, `getConnector(id)`, `getConnectorHealth(id)` | Registered connector instances Map |

---

## 2. Comprehensive Field-by-Field Source Mapping

### 2.1 `ControlPlaneSnapshot` Top-Level Fields

| Field Name | Authoritative Source | Source Query Method | Canonical Type | Transformation / Fallback Rule |
|---|---|---|---|---|
| `snapshotId` | Snapshot Generator | Deterministic composition | `string` | Format: `snap-cp-${timestamp}` |
| `generatedAt` | Snapshot Generator / Context | Deterministic timestamp | `number` | Context `timestamp` or `Date.now()` if unspecified |
| `sourceVersion` | `policyRegistry` / `executionPersistence` | `policyRegistry.getRegistryVersion()` | `number \| 'UNKNOWN'` | Version integer or `'UNKNOWN'` |
| `missions` | `missionManager` | `missionManager.listMissions()` | `readonly MissionSummary[]` | Projected via `projectMissionSummary` |
| `operations` | `auditEventRegistry` & `executionPersistence` | `auditEventRegistry.getAllEvents()`, `envelope.goals` | `readonly OperationSummary[]` | Projected via `projectOperationSummary` |
| `approvals` | `executionPersistence` | `envelope.approvals` | `readonly ApprovalSummary[]` | Projected via `projectApprovalSummary` |
| `governance` | `executionPersistence` | `getAllGovernanceDecisions()` | `readonly GovernanceSummary[]` | Projected via `projectGovernanceSummary` |
| `recovery` | `executionPersistence` & `recoveryControlPlane` | `getAllRecoveryControlDecisions()` | `readonly RecoverySummary[]` | Projected via `projectRecoverySummary` |
| `causalTraces` | `causalTraceService` | `causalTraceService.buildCausalGraph(opId)` | `readonly CausalTraceSummary[]` | Projected via `projectCausalTraceSummary` |
| `systemHealth` | Multi-Subsystem Health Probe | Read-only status aggregation | `SystemHealthSummary` | Observational health only; no execution authority |
| `requestId` | Snapshot Context | Context param | `string \| 'UNKNOWN'` | Preserves caller request ID or `'UNKNOWN'` |
| `actorId` | Snapshot Context | Context param | `string \| 'UNKNOWN'` | Preserves caller actor ID or `'UNKNOWN'` |
| `correlationId` | Snapshot Context | Context param | `string \| 'UNKNOWN'` | Preserves caller correlation ID or `'UNKNOWN'` |

---

## 3. Read-Only Invariant & Absolute Prohibitions

1. **Zero Execution**: `controlPlaneSnapshotService` MUST NEVER invoke `actionBusService.execute()`, `executionGateway.dispatch()`, or provider adapters.
2. **Zero Mutation**: Snapshot generation MUST NEVER invoke `saveMission()`, `savePolicy()`, `saveGovernanceDecision()`, `registerPolicy()`, or `saveApproval()`.
3. **Zero Policy Evaluation**: Snapshot generation MUST NEVER call `governanceControlPlane.evaluateGovernance()` or `policyRegistry.registerPolicy()`.
4. **Zero Recovery Action**: Snapshot generation MUST NEVER call `recoveryControlPlane.evaluateRecoveryControl()` or trigger retries/compensations.
5. **Zero External Calls**: Snapshot generation MUST NEVER invoke `fetch()`, Axios, WebSockets, or provider endpoints.
