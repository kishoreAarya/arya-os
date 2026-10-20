# AryaOS V1 Stage 24 — Phase 4 Authoritative Source Map
## Approval Center Projection Integration

**Date**: October 4, 2026  
**Status**: PHASE 4 RECONNAISSANCE & ARCHITECTURAL SOURCE MAPPING  
**Principle**: The Approval Center is **READ + PROJECT + EXPLAIN**. It is **NOT** an approval engine, authorization engine, governance engine, policy engine, Action Bus, or recovery engine.

---

## 1. Authoritative Approval Sources Inventory

| Subsystem Domain | Authoritative Service Singleton | Canonical Domain Types | Read / Query Methods | Lifecycle / State Storage |
|---|---|---|---|---|
| **Stage 09: Orchestration Persistence** | `executionPersistence` | `PersistedApprovalRecord` | `loadEnvelope().approvals` | LocalStorage + safe In-Memory fallback |
| **Stage 21: Governed Policy Control Plane** | `governanceControlPlane` | `GovernanceDecision`, `OperatorApprovalToken`, `HumanApprovalCheckStatus` | `executionPersistence.getAllGovernanceDecisions()` | Memory Cache + `envelope.governanceDecisions` |
| **Stage 19: Event Reaction Engine** | `reactionProposalService` | `ReactionProposal`, `TriggerRiskLevel` | `reactionProposalService.listProposals()` | Memory Cache + `executionPersistence.getAllReactionProposals()` |
| **Stage 20: Policy Intelligence** | `policyRegistry` | `PolicyProposal`, `PolicyStatus` | `policyRegistry.getAllPolicies()`, `executionPersistence` | Memory Map + `envelope.policies` |
| **Stage 23: Governed Recovery Control** | `recoveryControlPlane` | `RecoveryControlDecision`, `RecoveryPlanApprovalRequirement` | `executionPersistence.getAllRecoveryControlDecisions()` | Active decisions Map + persistence |
| **Stage 14: Decision Intelligence** | `decisionIntelligence` | `DecisionApproval`, `ConsequentialActionFlag` | Existing Decision models | Read-only inspection |
| **Stage 22: Operational Truth & Audit** | `auditEventRegistry` | `OperationalAuditEvent` | `auditEventRegistry.getAllEvents()` | Append-only in-memory index |

---

## 2. Comprehensive Field-by-Field Source Mapping

Every `ApprovalSummary` field is derived strictly from existing authoritative records without synthetic invention:

| `ApprovalSummary` Field | Authoritative Source | Source Property / Method | Canonical Type | Epistemic Meaning & Fallback Rule |
|---|---|---|---|---|
| `approvalId` | Stage 09 / 19 / 21 / 23 | `appr.approvalId` \|\| `prop.proposalId` \|\| `dec.decisionId` | `string` | Canonical unique identity of approval requirement |
| `requestId` | Stage 09 / 21 / 23 | `appr.planId` \|\| `appr.actionId` \|\| `dec.requestId` \|\| `prop.proposalId` | `string \| 'UNKNOWN'` | Action Bus or governance request identity bound to approval |
| `actorId` | Stage 09 / 21 / 19 / 23 | `appr.decidedBy` \|\| `dec.actor.actorId` \|\| `prop.operatorApproval?.approvedBy` | `string \| 'UNKNOWN'` | Identity of human operator or requesting actor; must distinguish human vs non-human |
| `riskLevel` | Stage 15 / 19 / 21 | `appr.riskLevel` \|\| `dec.riskLevel` \|\| `prop.riskLevel` | `ActionRiskLevel \| 'UNKNOWN'` | Action risk level (`READ_ONLY`, `LOW_RISK`, `CONSEQUENTIAL`, `EXTERNAL_SIDE_EFFECT` or `LOW`, `MEDIUM`, `HIGH`, `CRITICAL`) |
| `policySnapshotId` | Stage 20 / 21 | `dec.policySnapshotId` \|\| `token.policySnapshotId` | `string \| 'UNKNOWN'` | Immutable snapshot identifier under which approval was evaluated |
| `policyVersion` | Stage 20 / 21 | `dec.policyRegistryVersion` \|\| `token.policyVersion` | `number \| 'UNKNOWN'` | Exact policy version at time of evaluation; mismatches trigger staleness (`INVALID`) |
| `approvalState` | Stage 09 / 19 / 21 / 23 | Evaluated status from authoritative state machine | `ApprovalProjectionState` | Canonical 6 states: `PENDING`, `APPROVED`, `REJECTED`, `EXPIRED`, `INVALID`, `UNKNOWN` |
| `expiresAt` | Stage 09 / 19 / 21 / 23 | `appr.expiresAt` \|\| `dec.expiresAt` | `number \| string \| 'UNKNOWN'` | Absolute expiration timestamp; TTL expired -> `EXPIRED` |
| `createdAt` | Stage 09 / 19 / 21 / 23 | `appr.requestedAt` \|\| `prop.createdAt` \|\| `dec.createdAt` | `number \| string \| 'UNKNOWN'` | Timestamp when human approval requirement was first recorded |
| `approvedAt` | Stage 09 / 19 / 21 / 23 | `appr.decidedAt` \|\| `prop.operatorApproval?.approvedAt` | `number \| string \| 'UNKNOWN'` | Timestamp of operator signoff; `'UNKNOWN'` if pending/rejected |
| `rejectedAt` | Stage 09 / 19 / 21 / 23 | `appr.decidedAt` \|\| `dec.evaluatedAt` | `number \| string \| 'UNKNOWN'` | Timestamp of rejection; `'UNKNOWN'` if pending/approved |
| `actionTitle` | Stage 09 / 15 / 19 / 21 | `appr.actionTitle` \|\| `dec.explanation.whatWasRequested` \|\| `prop.reactionType` | `string \| 'UNKNOWN'` | Human-readable title of requested consequential action |
| `reason` | Stage 09 / 19 / 21 / 23 | `appr.rejectionReason` \|\| `dec.reason` \|\| `prop.rejectionReason` | `string \| 'UNKNOWN'` | Authoritative reason, governance explanation, or rejection cause |

---

## 3. Canonical 6 Approval States

The Approval Center strictly preserves the 6 Phase 1 approval projection states:

1. **`PENDING`**: Awaiting human operator signoff; action blocked at governance boundary.
2. **`APPROVED`**: Formally authorized by an authenticated human operator with valid binding.
3. **`REJECTED`**: Explicitly denied or rejected by operator or policy rule.
4. **`EXPIRED`**: Approval TTL expired before signoff was completed.
5. **`INVALID`**: Forged signature, autonomous agent spoofing, request ID mismatch, or stale snapshot.
6. **`UNKNOWN`**: Backend state ambiguous, disconnected, or uncorroborated by authoritative persistence.

### Absolute State Mapping Rules:
- **`INVALID` MUST NEVER be mapped to `REJECTED`**.
- **`UNKNOWN` MUST NEVER be mapped to `PENDING`**.
- **`EXPIRED` MUST NEVER be mapped to `REJECTED`**.
- **`PENDING` MUST NEVER become `APPROVED` via client input**.

---

## 4. Human Identity & Anti-Spoofing Rules

1. **Non-Human Identity Rejection**: Approvals granted by `AUTONOMOUS_AGENT`, `SYSTEM`, `DAEMON`, or `BOT` are strictly classified as **`INVALID`**.
2. **Signature Validity**: Tokens containing forged, fake, or invalid signatures are classified as **`INVALID`**.
3. **Binding Invariance**: Approval tokens bound to a different `requestId`, different `policySnapshotId`, or different `policyVersion` than the evaluating context fail closed to **`INVALID`** (stale/misaligned).
4. **Zero Client Authority**: Client-side filters or state parameters cannot alter the projected state; frontend is **view-only**.

---

## 5. Absolute Read-Only Prohibitions

During projection, `controlPlaneSnapshotService.projectApprovals()` MUST NEVER invoke:
- `approve()` or `reject()`
- `authorize()` or `evaluateGovernance()`
- `ActionBusService.execute()`
- `recoveryControlPlane.evaluateRecoveryControl()`
- `executionPersistence.saveApproval()` or any disk write
- External network requests (`fetch`, Axios, WebSockets)
- LLM tokens
