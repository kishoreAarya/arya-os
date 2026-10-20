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

### 2.2 `MissionSummary` Field Mapping

| Field Name | Authoritative Source | Source Method / Property | Canonical Type | Fallback When Missing |
|---|---|---|---|---|
| `missionId` | `Mission` | `mission.missionId` | `string` | Mandatory from source |
| `goalId` | `Mission` | `mission.goals[0]?.goalId` | `string \| 'UNKNOWN'` | `'UNKNOWN'` if goals array is empty |
| `title` | `Mission` | `mission.title` | `string \| 'UNKNOWN'` | `'UNKNOWN'` |
| `status` | `Mission` | `mission.status` | `MissionStatus \| 'UNKNOWN'` | `'UNKNOWN'` |
| `priority` | `Mission` | `mission.priority` | `MissionPriority \| 'UNKNOWN'` | `'UNKNOWN'` |
| `progress` | `Mission` | `mission.progress` | `MissionProgress \| 'UNKNOWN'` | `'UNKNOWN'` |
| `activeOperations` | `Mission` | `mission.progress?.inProgressGoals` | `number \| 'UNKNOWN'` | `0` if empty, `'UNKNOWN'` if progress absent |
| `blockedOperations` | `Mission` | `mission.progress?.blockedGoals` | `number \| 'UNKNOWN'` | `0` if empty, `'UNKNOWN'` if progress absent |
| `pendingApprovals` | `executionPersistence` | Filter `envelope.approvals` where `status === 'PENDING'` | `number \| 'UNKNOWN'` | Count or `'UNKNOWN'` |
| `recoveryCount` | `executionPersistence` | Filter `envelope.recoveryControlDecisions` by mission | `number \| 'UNKNOWN'` | Count or `'UNKNOWN'` |
| `latestOperationalState` | `auditEventRegistry` | Latest event for mission `e.lifecycleState` | `OperationalLifecycleState \| 'UNKNOWN'` | `'UNKNOWN'` |
| `latestTruthState` | `auditEventRegistry` | Latest event for mission `e.epistemicStatus` | `EpistemicStatus \| 'UNKNOWN'` | `'UNKNOWN'` |
| `latestCausalEvent` | `auditEventRegistry` | Latest event for mission `e.eventType` | `string \| 'UNKNOWN'` | `'UNKNOWN'` |
| `policyVersion` | `policyRegistry` | `policyRegistry.getRegistryVersion()` | `number \| 'UNKNOWN'` | `'UNKNOWN'` |
| `governanceState` | `executionPersistence` | Latest decision for mission `dec.decision` | `GovernanceDecisionType \| 'UNKNOWN'` | `'UNKNOWN'` |
| `riskLevel` | `Mission` | `mission.riskLevel` | `ActionRiskLevel \| 'UNKNOWN'` | `'UNKNOWN'` |
| `updatedAt` | `Mission` | `mission.updatedAt` | `string \| 'UNKNOWN'` | `'UNKNOWN'` |
| `createdAt` | `Mission` | `mission.createdAt` | `string \| 'UNKNOWN'` | `'UNKNOWN'` |

---

### 2.3 `OperationSummary` Field Mapping

| Field Name | Authoritative Source | Source Method / Property | Canonical Type | Fallback When Missing |
|---|---|---|---|---|
| `operationId` | `OperationalAuditEvent` / `Goal` | `event.operationId` / `goal.id` | `string` | Mandatory from source |
| `missionId` | `OperationalAuditEvent` / `Goal` | `event.missionId` / `goal.missionId` | `string \| 'UNKNOWN'` | `'UNKNOWN'` |
| `goalId` | `OperationalAuditEvent` / `Goal` | `event.goalId` / `goal.id` | `string \| 'UNKNOWN'` | `'UNKNOWN'` |
| `actionId` | `OperationalAuditEvent` | `event.actionId` | `string \| 'UNKNOWN'` | `'UNKNOWN'` |
| `title` | `Goal` / `OperationalAuditEvent` | `goal.title` / `event.eventType` | `string \| 'UNKNOWN'` | `'UNKNOWN'` |
| `status` | `OperationalAuditEvent` | `event.lifecycleState` | `OperationalLifecycleState \| 'UNKNOWN'`| `'UNKNOWN'` |
| `truthState` | `OperationalAuditEvent` | `event.epistemicStatus` | `EpistemicStatus \| 'UNKNOWN'` | `'UNKNOWN'` |
| `epistemicState` | `OperationalAuditEvent` | `event.epistemicStatus` | `EpistemicStatus` | Default `'UNKNOWN'` if absent |
| `riskLevel` | `OperationalAuditEvent` | `event.riskLevel` | `ActionRiskLevel \| 'UNKNOWN'` | `'UNKNOWN'` |
| `policySnapshotId` | `OperationalAuditEvent` | `event.policySnapshotId` | `string \| 'UNKNOWN'` | `'UNKNOWN'` |
| `governanceDecisionId` | `OperationalAuditEvent` | `event.governanceDecisionId` | `string \| 'UNKNOWN'` | `'UNKNOWN'` |
| `connectorId` | `OperationalAuditEvent` | `event.connectorId` | `string \| 'UNKNOWN'` | `'UNKNOWN'` |
| `capabilityId` | `OperationalAuditEvent` | `event.capabilityId` | `string \| 'UNKNOWN'` | `'UNKNOWN'` |
| `idempotencyKey` | `OperationalAuditEvent` | `event.parameters?.idempotencyKey` | `string \| 'UNKNOWN'` | `'UNKNOWN'` |
| `createdAt` | `OperationalAuditEvent` | `event.timestamp` | `number \| string \| 'UNKNOWN'` | `'UNKNOWN'` |
| `updatedAt` | `OperationalAuditEvent` | `event.timestamp` | `number \| string \| 'UNKNOWN'` | `'UNKNOWN'` |
| `causationId` | `OperationalAuditEvent` | `event.causationId` | `string \| 'UNKNOWN'` | `'UNKNOWN'` |
| `correlationId` | `OperationalAuditEvent` | `event.correlationId` | `string \| 'UNKNOWN'` | `'UNKNOWN'` |

---

### 2.4 `GovernanceSummary` Field Mapping

| Field Name | Authoritative Source | Source Method / Property | Canonical Type | Fallback When Missing |
|---|---|---|---|---|
| `policySnapshotId` | `GovernanceDecision` | `decision.policySnapshotId` | `string \| 'UNKNOWN'` | `'UNKNOWN'` |
| `policyId` | `GovernanceDecision` | `decision.winningPolicyId` | `string \| 'UNKNOWN'` | `'UNKNOWN'` |
| `policyVersion` | `GovernanceDecision` | `decision.policyRegistryVersion` | `number \| 'UNKNOWN'` | `'UNKNOWN'` |
| `requestId` | `GovernanceDecision` | `decision.requestId` | `string` | Mandatory from source |
| `decisionId` | `GovernanceDecision` | `decision.decisionId` | `string \| 'UNKNOWN'` | `'UNKNOWN'` |
| `decision` | `GovernanceDecision` | `decision.decision` | `GovernanceDecisionType \| 'UNKNOWN'`| `'UNKNOWN'` |
| `authorityState` | `GovernanceDecision` | `decision.authorityIntersection.effectiveStatus` | `AuthorityCheckStatus \| 'UNKNOWN'` | `'UNKNOWN'` |
| `stalenessState` | `GovernanceDecision` | `decision.staleness.status` | `StalenessStatus \| 'UNKNOWN'` | `'UNKNOWN'` |
| `connectorAuthorityState` | `GovernanceDecision` | `decision.authorityIntersection.connectorPermissionGranted` | `boolean \| 'UNKNOWN'` | `'UNKNOWN'` |
| `actionAuthorizationState`| `GovernanceDecision` | `decision.authorityIntersection.actionAuthorized` | `boolean \| 'UNKNOWN'` | `'UNKNOWN'` |
| `humanApprovalState` | `GovernanceDecision` | `decision.authorityIntersection.humanApprovalStatus` | `HumanApprovalCheckStatus \| 'UNKNOWN'`| `'UNKNOWN'` |
| `missionConstraintState` | `GovernanceDecision` | `decision.authorityIntersection.missionConstraintsSatisfied` | `boolean \| 'UNKNOWN'` | `'UNKNOWN'` |
| `explanation` | `GovernanceDecision` | `decision.explanation.whatWasRequested` | `string \| 'UNKNOWN'` | `'UNKNOWN'` |
| `evaluatedAt` | `GovernanceDecision` | `decision.deterministicMetadata.evaluatedAt` | `number \| 'UNKNOWN'` | `'UNKNOWN'` |

---

### 2.5 `ApprovalSummary` Field Mapping

| Field Name | Authoritative Source | Source Method / Property | Canonical Type | Fallback When Missing |
|---|---|---|---|---|
| `approvalId` | `PersistedApprovalRecord` | `record.approvalId` | `string` | Mandatory from source |
| `requestId` | `PersistedApprovalRecord` | `record.planId` / `record.actionId` | `string \| 'UNKNOWN'` | `'UNKNOWN'` |
| `actorId` | `PersistedApprovalRecord` | `record.decidedBy` | `string \| 'UNKNOWN'` | `'UNKNOWN'` |
| `riskLevel` | `PersistedApprovalRecord` | `record.riskLevel` | `ActionRiskLevel \| 'UNKNOWN'` | `'UNKNOWN'` |
| `approvalState` | `PersistedApprovalRecord` | `record.status` | `ApprovalProjectionState` | Preserves `PENDING`, `APPROVED`, etc. |
| `expiresAt` | `PersistedApprovalRecord` | `record.expiresAt` | `number \| string \| 'UNKNOWN'` | `'UNKNOWN'` |
| `createdAt` | `PersistedApprovalRecord` | `record.requestedAt` | `number \| string \| 'UNKNOWN'` | `'UNKNOWN'` |
| `approvedAt` | `PersistedApprovalRecord` | `record.decidedAt` | `number \| string \| 'UNKNOWN'` | `'UNKNOWN'` |
| `rejectedAt` | `PersistedApprovalRecord` | `record.decidedAt` (if REJECTED) | `number \| string \| 'UNKNOWN'` | `'UNKNOWN'` |
| `actionTitle` | `PersistedApprovalRecord` | `record.actionTitle` | `string \| 'UNKNOWN'` | `'UNKNOWN'` |
| `reason` | `PersistedApprovalRecord` | `record.rejectionReason` | `string \| 'UNKNOWN'` | `'UNKNOWN'` |

---

### 2.6 `RecoverySummary` Field Mapping

| Field Name | Authoritative Source | Source Method / Property | Canonical Type | Fallback When Missing |
|---|---|---|---|---|
| `recoveryPlanId` | `RecoveryControlDecision` | `decision.recoveryPlanId` | `string \| 'UNKNOWN'` | `'UNKNOWN'` |
| `originalOperationId` | `RecoveryControlDecision` | `decision.originalOperationId` | `string` | Mandatory from source |
| `failureClassification` | `RecoveryControlDecision` | `decision.failureClassification` | `FailureClassification \| 'UNKNOWN'` | `'UNKNOWN'` |
| `currentTruthState` | `RecoveryControlDecision` | `decision.epistemicStatus` | `EpistemicStatus \| 'UNKNOWN'` | `'UNKNOWN'` |
| `proposedRecoveryAction` | `RecoveryControlDecision` | `decision.proposedRecoveryAction` | `RecoveryAction \| 'UNKNOWN'` | `'UNKNOWN'` |
| `riskLevel` | `RecoveryControlDecision` | `decision.riskLevel` | `ActionRiskLevel \| 'UNKNOWN'` | `'UNKNOWN'` |
| `idempotencyAssessment` | `RecoveryControlDecision` | `decision.idempotencyClass` | `IdempotencyClassification \| 'UNKNOWN'`| `'UNKNOWN'` |
| `requiredAuthority` | `RecoveryControlDecision` | `decision.requiredAuthority` | `readonly string[] \| 'UNKNOWN'` | `'UNKNOWN'` |
| `governanceDecisionId` | `RecoveryControlDecision` | `decision.governanceDecisionId` | `string \| 'UNKNOWN'` | `'UNKNOWN'` |
| `approvalRequirement` | `RecoveryControlDecision` | `decision.approvalRequirement` | `{ required: boolean; humanOperatorRequired: boolean } \| 'UNKNOWN'` | `'UNKNOWN'` |
| `reconciliationRequirement`| `RecoveryControlDecision` | `decision.reconciliationRequirement` | `{ required: boolean } \| 'UNKNOWN'` | `'UNKNOWN'` |
| `compensationPlan` | `RecoveryControlDecision` | `decision.compensationPlan` | `DeclarativeCompensationPlan \| 'UNKNOWN'` | `'UNKNOWN'` |
| `expectedOutcome` | `RecoveryControlDecision` | `decision.recoveryOutcome` | `RecoveryOutcome \| 'UNKNOWN'` | `'UNKNOWN'` |
| `expiresAt` | `RecoveryControlDecision` | `decision.expiresAt` | `number \| 'UNKNOWN'` | `'UNKNOWN'` |
| `causationId` | `RecoveryControlDecision` | `decision.causationId` | `string \| 'UNKNOWN'` | `'UNKNOWN'` |
| `correlationId` | `RecoveryControlDecision` | `decision.correlationId` | `string \| 'UNKNOWN'` | `'UNKNOWN'` |
| `lifecycleState` | `RecoveryControlDecision` | `decision.lifecycleState` | `RecoveryLifecycleState \| 'UNKNOWN'` | `'UNKNOWN'` |
| `retryCount` | `RecoveryControlDecision` | `decision.retryCount` | `number \| 'UNKNOWN'` | `'UNKNOWN'` |
| `recoveryDepth` | `RecoveryControlDecision` | `decision.recoveryDepth` | `number \| 'UNKNOWN'` | `'UNKNOWN'` |

---

### 2.7 `CausalTraceSummary` Field Mapping

| Field Name | Authoritative Source | Source Method / Property | Canonical Type | Transformation Rule |
|---|---|---|---|---|
| `operationId` | `CausalGraph` | `graph.operationId` | `string` | Direct from `causalTraceService` |
| `rootNodeId` | `CausalGraph` | `graph.rootNodeId` | `string` | Direct from `causalTraceService` |
| `nodes` | `CausalGraph` | `graph.nodes` | `readonly CausalTraceNodeSummary[]` | Maps `CausalNode` with explicit `MISSING_EVIDENCE` support |
| `edges` | `CausalGraph` | `graph.edges` | `readonly CausalTraceEdgeSummary[]` | Maps `CausalEdge` preserving `timestamp` and `edgeType` |
| `maxDepthReached` | `CausalGraph` | `graph.maxDepthReached` | `number` | Respects `MAX_CAUSAL_DEPTH = 10` |
| `isTruncated` | `CausalGraph` | `graph.isTruncated` | `boolean` | Flagged if `MAX_CAUSAL_NODES = 100` reached |
| `hasCycles` | `CausalGraph` | `graph.hasCycles` | `boolean` | Cycle detection invariant |
| `hasMissingEvidence` | `CausalGraph` | `nodes.some(n => n.nodeType === 'MISSING_EVIDENCE')` | `boolean` | True if unconfirmed state present |

---

### 2.8 `SystemHealthSummary` Field Mapping

| Subsystem | Authoritative Source | Source Probe / Query Method | Status Logic | Fallback When Missing |
|---|---|---|---|---|
| `execution` | `executionPersistence` | `getTelemetry()` | `HEALTHY` if telemetry accessible | `'UNKNOWN'` |
| `providers` | `executionPersistence` | Check telemetry fallback count | `DEGRADED` if high fallbacks; `HEALTHY` otherwise | `'UNKNOWN'` |
| `connectors` | `connectorRegistry` | `listConnectors()` & `getConnectorHealth()` | `HEALTHY` if connectors active; `DEGRADED` if any degraded | `'UNKNOWN'` |
| `persistence` | `executionPersistence` | `isDurableStorageActive()` | `HEALTHY` if durable; `DEGRADED` if in-memory fallback | `'UNKNOWN'` |
| `governance` | `policyRegistry` & `governanceControlPlane` | Check policy registry version > 0 | `HEALTHY` if policies loaded | `'UNKNOWN'` |
| `recovery` | `recoveryControlPlane` | Check active recovery count | `HEALTHY` if under limits; `DEGRADED` if circuit broken | `'UNKNOWN'` |
| `eventIngestion` | `auditEventRegistry` | Check recent events | `HEALTHY` if registry active | `'UNKNOWN'` |
| `missions` | `missionManager` | `listMissions()` | `HEALTHY` if missions loadable | `'UNKNOWN'` |
| `actionBus` | `actionBusService` | Check ActionBus singleton active | `HEALTHY` (observational only; never executes) | `'UNKNOWN'` |
| `isDurableStorage`| `executionPersistence` | `isDurableStorageActive()` | `boolean` (Truthful reporting) | `false` if in-memory |

---

## 3. Read-Only Invariant & Absolute Prohibitions

1. **Zero Execution**: `controlPlaneSnapshotService` MUST NEVER invoke `actionBusService.execute()`, `executionGateway.dispatch()`, or provider adapters.
2. **Zero Mutation**: Snapshot generation MUST NEVER invoke `saveMission()`, `savePolicy()`, `saveGovernanceDecision()`, `registerPolicy()`, or `saveApproval()`.
3. **Zero Policy Evaluation**: Snapshot generation MUST NEVER call `governanceControlPlane.evaluateGovernance()` or `policyRegistry.registerPolicy()`.
4. **Zero Recovery Action**: Snapshot generation MUST NEVER call `recoveryControlPlane.evaluateRecoveryControl()` or trigger retries/compensations.
5. **Zero External Calls**: Snapshot generation MUST NEVER invoke `fetch()`, Axios, WebSockets, or provider endpoints.
