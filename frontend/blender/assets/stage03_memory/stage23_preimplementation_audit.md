# AryaOS V1 Stage 23 — Pre-Implementation Architectural Audit & Contract Freeze
## Resilient Autonomous Operations & Recovery Control Plane

### Status: PHASE 0 CONTRACT FREEZE — STAGES 01–22 FROZEN

---

## 1. Executive Summary & Objective

Stage 23 establishes the **Recovery Control Plane** of AryaOS V1. Its objective is to determine the **SAFE NEXT STATE** after any operational failure, timeout, cancellation, connector revocation, stale policy, stale approval, partial execution, unknown external result, reconciliation failure, mission pause, trigger disablement, provider failure, or system interruption.

Stage 23 operates strictly according to the deterministic causal flow:
$$\text{FAILURE / INTERRUPTION} \longrightarrow \text{OPERATIONAL TRUTH} \longrightarrow \text{FAILURE CLASSIFICATION} \longrightarrow \text{RECOVERY PLAN} \longrightarrow \text{RECOVERY SAFETY ANALYSIS} \longrightarrow \text{GOVERNANCE} \longrightarrow \text{APPROVAL IF REQUIRED} \longrightarrow \text{EXISTING EXECUTION BOUNDARY} \longrightarrow \text{NEW OPERATION} \longrightarrow \text{VERIFICATION} \longrightarrow \text{AUDIT / CAUSAL TRACE}$$

**Core Invariant**: Recovery **NEVER** means *"retry everything"*. Recovery is a governed decision about the safe next state chosen from:
`RETRY`, `RESUME`, `ROLLBACK`, `COMPENSATE`, `RECONCILE`, `WAIT`, `REQUIRE_APPROVAL`, `PAUSE`, `ABORT`, `ESCALATE`, `UNKNOWN`.

---

## 2. Immutable System Ownership Boundaries

Stage 23 integrates with existing authoritative stages without duplication or usurpation of responsibilities.

### 2.1 Stage 09 Recovery Ownership (Immutable)
- **Authoritative Subsystem**: `RecoveryManager` (`src/services/recoveryManager.ts`), `executionPersistence.ts`, `executionJournal.ts`.
- **Stage 09 Responsibility**:
  1. Goal, Plan, and ActionNode DAG state reconstruction.
  2. ActionNode dependency checking and executable frontier calculation (`getExecutableFrontier`).
  3. Boot-time goal recovery (`recoverAllGoals`).
  4. Local Stage 07 gateway idempotency cache lookup (`executionGateway.getCompletedExecution`).
  5. ActionNode status restoration (`EXECUTING` $\to$ `AWAITING_APPROVAL` or `READY`).
  6. Persistence of goals and appending `RECOVERY_INITIATED` / `RECOVERY_COMPLETED` events to `executionJournal`.
- **Stage 23 Boundary**: Stage 23 **NEVER** replaces or duplicates `recoveryManager.recoverGoal()`. When goal/plan action recovery is required, Stage 23 coordinates directly with Stage 09.

### 2.2 Stage 07 Execution Gateway Boundary (Immutable)
- **Authoritative Subsystem**: `ExecutionGateway` (`src/services/executionGateway.ts`), `providerRouter.ts`.
- **Stage 07 Responsibility**: Provider routing, execution gateway dispatch, provider idempotency caching, provider cancellation, and fallback handling.
- **Stage 23 Boundary**: Stage 23 **NEVER** executes LLM or intelligence providers directly.

### 2.3 Stage 12 Mission Boundary (Immutable)
- **Authoritative Subsystem**: `MissionManager` (`src/services/missionManager.ts`), `missionPlanner.ts`, `missionDependencyGraph.ts`.
- **Stage 12 Responsibility**: Long-horizon mission planning, dependency management, mission scheduling, and resource arbitration.
- **Stage 23 Boundary**: Stage 23 provides recovery proposals, pause signals, or dependency advisories to Stage 12. It **NEVER** directly mutates mission authority or schedules tasks.

### 2.4 Stage 15 Action Bus Boundary (Immutable)
- **Authoritative Subsystem**: `ActionBusService` (`src/types/actionBus.ts`).
- **Stage 15 Responsibility**: External capability dispatch, adapter invocation, action authorization, output normalization, and execution result reconciliation.
- **Stage 23 Boundary**: Stage 23 **NEVER** calls external APIs, transports, fetch, or network connectors directly. All external recovery actions are routed through Stage 15.

### 2.5 Stage 16 Connector Fabric Boundary (Immutable)
- **Authoritative Subsystem**: `ConnectorPermissionService` (`src/types/connectorFabric.ts`), `oauthBoundary.ts`.
- **Stage 16 Responsibility**: Connector identity, scopes, credentials, and token lifecycle management.
- **Stage 23 Boundary**: Stage 23 **CANNOT** grant permissions, forge scopes, refresh revoked connectors, or bypass credential boundaries. If a connector is revoked, recovery halts closed and requests credential re-authorization.

### 2.6 Stage 19 Reaction Engine Boundary (Immutable)
- **Authoritative Subsystem**: `ReactionExecutionEngine` (`src/services/reactionExecutionEngine.ts`), `triggerConditionEngine.ts`.
- **Stage 19 Responsibility**: Event trigger evaluation, reactive condition matching, and reaction proposal formation.
- **Stage 23 Boundary**: Stage 23 does not evaluate trigger conditions or create unmonitored event loops. Recovery actions are distinct from reactive trigger cycles.

### 2.7 Stage 20 Policy Intelligence Boundary (Immutable)
- **Authoritative Subsystem**: `PolicyRegistry` (`src/services/policyRegistry.ts`), `policyEvaluationService.ts`.
- **Stage 20 Responsibility**: Policy lifecycle, experience-based learning, simulation, conflict resolution, and active policy sets.
- **Stage 23 Boundary**: Stage 23 **NEVER** evaluates or alters policies in `PolicyRegistry`. It consumes active policies to constrain recovery (e.g., retry limits, prohibited compensation).

### 2.8 Stage 21 Governed Policy Control Plane Boundary (Immutable)
- **Authoritative Subsystem**: `GovernanceControlPlane` (`src/services/governanceControlPlane.ts`), `governanceAuthorityService.ts`.
- **Stage 21 Responsibility**: 5-tier fail-closed authority intersection:
  $$\text{Effective Authority} = \text{Policy Decision} \cap \text{Connector Permissions} \cap \text{Action Authorization} \cap \text{Human Approval} \cap \text{Mission Constraints}$$
- **Stage 23 Boundary**: **EVERY CONSEQUENTIAL RECOVERY ACTION IS A NEW REQUEST**. Recovery cannot bypass Stage 21. A prior approval for the failed operation does not transfer to recovery. Stale policies or approvals detected by `governanceStalenessService` immediately invalidate recovery proposals.

### 2.9 Stage 22 Operational Truth & Causal Audit Boundary (Immutable)
- **Authoritative Subsystem**: `OperationalAuditFabric` (`src/services/operationalAudit.ts`), `auditEventRegistry.ts`, `operationalTruthService.ts`.
- **Stage 22 Responsibility**: Causal traces, evidence verification, failure boundary diagnosis (`diagnoseFailure`), and truth reconciliation.
- **Stage 23 Boundary**:
  1. Stage 23 consumes Stage 22 operational truth and failure boundaries as input evidence.
  2. If Stage 22 reports `epistemicStatus: UNKNOWN`, Stage 23 enforces **Reconciliation-First** (no blind retry).
  3. Every recovery lifecycle milestone produces a **NEW** canonical `OperationalAuditEvent` in Stage 22 with `causationId = originalOperationId`. Stage 23 **NEVER** mutates or overwrites historical failure records.

---

## 3. Responsibilities That Stage 23 Explicitly Refuses to Own

To prevent architectural entropy, Stage 23 explicitly refuses to own:
1. **Direct Network/Provider Execution**: Stage 23 will not contain `fetch()`, Axios, provider SDK clients, or connector transports.
2. **Ambient Authorization**: Stage 23 will not decide whether an action is permitted without invoking Stage 21.
3. **Automatic Privilege Escalation**: Stage 23 will not grant scopes or bypass human approval.
4. **Second Mission Engine**: Stage 23 will not schedule, re-order, or prioritize mission queues.
5. **Second Policy Engine**: Stage 23 will not define, evaluate, or mutate policy rules.
6. **Second Persistence Engine**: Stage 23 will not create standalone databases, envelopes, or storage formats.
7. **Second Crash-Recovery Engine**: Stage 23 will not duplicate Stage 09's `recoverGoal()` or DAG frontier calculations.
8. **Blind Retries**: Stage 23 will not retry operations when external state is unknown, non-idempotent, or revoked.
9. **Mutation of Historical Evidence**: Stage 23 will not overwrite, edit, or delete past failed audit events.
10. **LLM Inference**: Stage 23 will consume **0 LLM tokens**; all recovery classification, safety assessment, and plan generation are 100% deterministic.

---

## 4. Stage 23 Unique Responsibilities

Stage 23 is uniquely responsible for:
1. **Evidence-Based Failure Classification**: Deterministically categorizing failures into 13 canonical types (`TRANSIENT`, `PERMANENT`, `AUTHORIZATION`, `PERMISSION`, `POLICY`, `STALE_STATE`, `UNKNOWN_EXTERNAL_STATE`, `PARTIAL_EXECUTION`, `RECONCILIATION`, `RESOURCE`, `DEPENDENCY`, `SYSTEM_INTERRUPTION`, `HUMAN_REQUIRED`).
2. **Deterministic Recovery Plan Formulation**: Determining the safe next state among 11 outcomes (`RETRY`, `RESUME`, `ROLLBACK`, `COMPENSATE`, `RECONCILE`, `WAIT`, `REQUIRE_APPROVAL`, `PAUSE`, `ABORT`, `ESCALATE`, `UNKNOWN`).
3. **Idempotency & Duplicate Side-Effect Prevention**: Analyzing operation idempotency (`READ_ONLY`, `IDEMPOTENT`, `CONDITIONALLY_IDEMPOTENT`, `NON_IDEMPOTENT`, `UNKNOWN`) and verifying idempotency keys and parameters before allowing retry.
4. **Reconciliation-First Routing for Unknown States**: Enforcing bounded reconciliation probes via Stage 15/07 whenever external execution status is unconfirmed.
5. **Partial Execution Accounting**: In multi-step workflows, preserving completed steps ($A, B$), isolating the failed step ($C$), and deferring downstream steps ($D$) without duplicate execution.
6. **Compensation & Rollback Evaluation**: Determining whether compensation exists (`ROLLBACK_AVAILABLE`, `COMPENSATION_AVAILABLE`, `NO_COMPENSATION`, `UNKNOWN`) and formatting compensating actions as governed, non-privileged requests.
7. **Recovery Loop Guard**: Enforcing hard boundaries ($\text{MAX\_RECOVERY\_DEPTH} \le 3$, $\text{MAX\_AUTOMATIC\_RETRIES} \le 2$), detecting oscillation, and forcing `ESCALATE` or `REQUIRE_APPROVAL`.
8. **Interrupted Recovery State Restoration**: Re-evaluating in-flight recovery plans across process restarts without reusing stale approvals.

---

## 5. Visual Asset & Spatial Baseline Confirmation

- **Blender Master Scene**: `blender/scenes/stage03_aryaos_memory_environment.blend`  
  **SHA256**: `c4577c47fa60f8beb1f77a1feb25ffb84b34ff9c38cfc6dbd4a8bc2628c8a13f` (strictly preserved).
- **14 GLB Files**: 100% matched across `blender/assets/stage03_memory` and `public/assets/stage03_memory`.
- **Camera Configurations**: Cinematic Hero, Monumental Low Angle, and Archive Detail cameras verified intact.
- **WebGL Performance Baseline**: 53–54 draw calls, 86,842 triangles, 1.14–1.82 ms frame render time. Telemetry panels in `SpatialCommandConsole.tsx` must be pure DOM with 0 additional draw calls.
