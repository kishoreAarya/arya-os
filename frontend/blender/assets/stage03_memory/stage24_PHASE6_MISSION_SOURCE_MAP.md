# ARYAOS V1 — STAGE 24 — PHASE 6
# MISSION OPERATIONS PROJECTION SOURCE MAP

**STATUS:** AUTHORITATIVE ARCHITECTURAL SPECIFICATION & SOURCE MAP  
**SUBSYSTEM:** Stage 24 Mission Operations Control Plane  
**PROJECTION FAÇADE:** `controlPlaneSnapshotService.projectMissions()` & `controlPlaneSnapshotService.projectMissionDetail()`  
**TARGET CONTRACT:** `MissionSummary` & `ControlPlaneSnapshot` (`src/types/controlPlane.ts`), `MissionDetailProjection` (`src/services/controlPlaneSnapshotService.ts`)  

---

## 1. ARCHITECTURAL BOUNDARIES & AUTHORITY HIERARCHY

Stage 24 is strictly an **observational projection**, NOT a mission controller, goal scheduler, or execution engine.

```
Existing Subsystems & Authoritative Owners:
┌────────────────────────────────────────────────────────────────────────┐
│ Stage 12: Mission Control (Sole Mission Lifecycle & Plan Authority)    │
│           - MissionManager (missionManager.listMissions(), getMission())│
│           - MissionPlanner, MissionObservationService                  │
│           - Mission, MissionGoalReference, MissionDependency, Plan     │
├────────────────────────────────────────────────────────────────────────┤
│ Stage 08: Goal Orchestration (Goal Lifecycle & Execution Owner)        │
│           - GoalOrchestrator (goalOrchestrator.getAllGoals(), getGoal())│
│           - GoalStatus, ActionStatus, GoalExecutionOptions             │
├────────────────────────────────────────────────────────────────────────┤
│ Stage 10: Resource Governance (Budgets, Leases & Cost Tracking Owner)  │
│           - ResourceGovernor (resourceGovernor.getActiveLeases())      │
│           - getGoalBudget(goalId), getGoalCostTracking(goalId)         │
│           - ResourceBudget, ResourceLease, Telemetry                   │
├────────────────────────────────────────────────────────────────────────┤
│ Stage 09: Execution Persistence & Journal (Durable Storage Owner)      │
│           - executionPersistence.getMissions()                         │
│           - executionPersistence.getMission(missionId)                 │
│           - executionPersistence.getMissionCheckpoints(missionId)      │
│           - executionPersistence.loadEnvelope().missions               │
│           - executionJournal.appendEvent() (read-only audit trail)     │
├────────────────────────────────────────────────────────────────────────┤
│ Stage 22: Operational Truth & Causal Audit (Empirical Reality Owner)   │
│           - operationalTruthService.getOperationState()                │
│           - auditEventRegistry.getEventsByMissionId(missionId)         │
│           - causalTraceService.buildCausalGraph()                      │
├────────────────────────────────────────────────────────────────────────┤
│ Stage 23: Recovery Control Plane (Recovery Decision Owner)             │
│           - executionPersistence.getAllRecoveryControlDecisions()      │
│           - envelope.recoveryControlDecisions                          │
└────────────────────────────────────────────────────────────────────────┘
                                    │ (READ-ONLY PROJECTION)
                                    ▼
┌────────────────────────────────────────────────────────────────────────┐
│ Stage 24: Mission Operations Control Plane Facade                      │
│           - controlPlaneSnapshotService.projectMissions()              │
│           - controlPlaneSnapshotService.projectMissionDetail()         │
│           - Output: readonly MissionSummary[] (Deeply Frozen)          │
│           - Output: Readonly<MissionDetailProjection> (Deeply Frozen)  │
└────────────────────────────────────────────────────────────────────────┘
```

### Absolute Invariants & Prohibitions
1. **Zero Mission Authority Created:** Stage 24 does not create, update, pause, resume, cancel, or delete missions.
2. **Zero Goal Scheduling / Dispatch:** Stage 24 does not create goals, plan goals, dispatch actions, or trigger tasks.
3. **Zero Replanning / Plan Mutation:** Stage 24 does not generate new plans or replan existing missions.
4. **Zero Resource Allocation Mutation:** Stage 24 does not acquire or release leases, set budgets, or reserve resources.
5. **Zero Action Bus Dispatch:** `actionBusService.execute()` and `dispatchAction()` are never called.
6. **Zero External / LLM Activity:** Zero network calls, zero provider calls, zero LLM tokens consumed.
7. **Epistemic Honesty:**
   - `REQUESTED ≠ PLANNED ≠ AUTHORIZED ≠ DISPATCHED ≠ EXECUTED ≠ OBSERVED ≠ RECONCILED`
   - `UNKNOWN ≠ SUCCESS`, `UNKNOWN ≠ FAILURE`
   - `INFERRED ≠ OBSERVED`, `PROJECTED ≠ CONFIRMED`
   - Goal completion does NOT fabricate mission completion: even if 100% of goals are completed, the mission status remains strictly what the canonical mission record states.
   - Missing dependency evidence is preserved explicitly (`MISSING_EVIDENCE`).
   - Resource allocation does NOT prove utilization: utilization is only reported when authoritative cost tracking records exist; otherwise it remains `UNKNOWN`.
   - A planned checkpoint does NOT prove checkpoint completion.
   - Missing progress is represented honestly without synthetic percentages.

---

## 2. FIELD-BY-FIELD AUTHORITATIVE MAPPING MATRIX

### A. `MissionSummary` Contract (`src/types/controlPlane.ts`)

| `MissionSummary` Field | Authoritative Source Entity | Source Read Method / Path | Canonical Domain Type | Epistemic Meaning & Fallback Rules |
| :--- | :--- | :--- | :--- | :--- |
| `missionId` | `Mission` / `PersistedOrchestrationEnvelope` | `mission.missionId` | `string` | Canonical identifier of the mission. Stable identity deduplication key. |
| `goalId` | `MissionGoalReference` | `mission.goals[0]?.goalId` | `string \| 'UNKNOWN'` | Primary or leading goal ID associated with the mission. Falls back to `'UNKNOWN'` if no goals exist. |
| `title` | `Mission` | `scrubSensitiveString(mission.title)` | `string \| 'UNKNOWN'` | Human-readable mission title, recursively scrubbed for credentials and secrets. |
| `status` | `Mission` | `mission.status` | `MissionStatus \| 'UNKNOWN'` | Canonical lifecycle state (14 canonical enum values). Validated against enum; falls back to `'UNKNOWN'`. Never auto-promoted based on goal completion. |
| `priority` | `Mission` | `mission.priority` | `MissionPriority \| 'UNKNOWN'` | Priority class (`LOW`, `NORMAL`, `HIGH`, `CRITICAL`). Validated against enum; falls back to `'UNKNOWN'`. |
| `progress` | `MissionProgress` | `mission.progress` | `MissionProgress \| 'UNKNOWN'` | Grounded in canonical progress record or derived from goals. If missing/unreliable, exposed honestly or as `'UNKNOWN'`. |
| `activeOperations` | `MissionProgress` / `GoalOrchestrator` / `goals` | `m.progress?.inProgressGoals` or count of RUNNING goals | `number \| 'UNKNOWN'` | Number of actively executing operations. Validated non-negative finite integer. |
| `blockedOperations` | `MissionProgress` / `GoalOrchestrator` / `goals` | `m.progress?.blockedGoals` or count of BLOCKED goals | `number \| 'UNKNOWN'` | Number of currently blocked operations. Validated non-negative finite integer. |
| `pendingApprovals` | `envelope.approvals` / `executionPersistence` | Count of `PENDING` approvals matching mission or goal IDs | `number \| 'UNKNOWN'` | Number of outstanding approvals required for mission operations. |
| `recoveryCount` | `envelope.recoveryControlDecisions` / `executionPersistence` | Count of recovery decisions matching mission or goal IDs | `number \| 'UNKNOWN'` | Number of recovery operations recorded for this mission or its goals. |
| `latestOperationalState` | Stage 22 `auditEventRegistry` | `auditEventRegistry.getEventsByMissionId()` | `OperationalLifecycleState \| 'UNKNOWN'` | Most recent operational lifecycle state recorded in Stage 22 audit trail. |
| `latestTruthState` | Stage 22 `auditEventRegistry` | `auditEventRegistry.getEventsByMissionId()` | `EpistemicStatus \| 'UNKNOWN'` | Most recent epistemic certainty status (`OBSERVED`, `CONFIRMED`, `INFERRED`, `PROJECTED`, `UNKNOWN`). |
| `latestCausalEvent` | Stage 22 `auditEventRegistry` | `auditEventRegistry.getEventsByMissionId()` | `string \| 'UNKNOWN'` | Most recent audit event type identifier. |
| `policyVersion` | Stage 20 `policyRegistry` | `policyRegistry.getRegistryVersion()` | `number \| 'UNKNOWN'` | Current policy registry version governing operations. |
| `governanceState` | Stage 21 `governanceControlPlane` | `envelope.governanceDecisions` or audit | `GovernanceDecisionType \| 'UNKNOWN'` | Prevailing governance state for the mission. |
| `riskLevel` | `Mission` | `mission.riskLevel` | `ActionRiskLevel \| 'UNKNOWN'` | Consequential risk rating (`READ_ONLY`, `LOW_RISK`, `CONSEQUENTIAL`, `EXTERNAL_SIDE_EFFECT`, or mapped from `LOW`/`MEDIUM`/`HIGH`/`CRITICAL`). |
| `updatedAt` | `Mission` | `mission.updatedAt` | `string \| 'UNKNOWN'` | ISO timestamp of last recorded update. |
| `createdAt` | `Mission` | `mission.createdAt` | `string \| 'UNKNOWN'` | ISO timestamp of mission creation. |

---

### B. `MissionDetailProjection` Contract (`src/services/controlPlaneSnapshotService.ts`)

| `MissionDetailProjection` Field | Authoritative Source Entity | Source Read Method / Path | Canonical Domain Type | Epistemic Meaning & Fallback Rules |
| :--- | :--- | :--- | :--- | :--- |
| `missionId` | `Mission` | `mission.missionId` | `string` | Canonical mission ID. |
| `title` | `Mission` | `scrubSensitiveString(mission.title)` | `string` | Scrubbed mission title. |
| `objective` | `Mission` | `scrubSensitiveString(mission.objective)` | `string` | Scrubbed mission objective description. |
| `status` | `Mission` | `mission.status` | `MissionStatus \| 'UNKNOWN'` | Validated canonical lifecycle state. |
| `priority` | `Mission` | `mission.priority` | `MissionPriority \| 'UNKNOWN'` | Validated priority level. |
| `riskLevel` | `Mission` | `mission.riskLevel` | `ActionRiskLevel \| 'UNKNOWN'` | Risk rating. |
| `goals` | `MissionGoalReference` / `GoalOrchestrator` | `mission.goals` matched against `goalOrchestrator.getAllGoals()` | `readonly MissionGoalSummary[]` | Granular list of goal references with title, mandatory flag, weight, timeout, current status, operational state. |
| `dependencies` | `MissionDependency` | `mission.dependencies` evaluated against goal evidence | `readonly MissionDependencySummary[]` | Granular list of dependencies with satisfaction state (`SATISFIED`, `PENDING`, `BLOCKED`, `MISSING_EVIDENCE`, `UNKNOWN`), cycle detection flag (`isCycle`), and evidence notes. |
| `progress` | `MissionProgress` / `goals` | `mission.progress` validated against goal counts | `MissionProgressSummary` | Grounded progress breakdown with `progressProvenance` (`RECORDED`, `DERIVED`, `UNKNOWN`). |
| `checkpoints` | `MissionCheckpoint` / `executionPersistence` | `executionPersistence.getMissionCheckpoints(missionId)` | `readonly MissionCheckpointSummary[]` | Historical snapshots recorded at checkpoints. Distinguishes planned vs completed states. |
| `resourceAllocations` | `ResourceGovernor` / `mission.constraints` | `resourceGovernor.getGoalCostTracking()` & `mission.constraints` | `readonly MissionResourceSummary[]` | Explicit separation of allocated resource versus verified actual utilization. Utilization is `UNKNOWN` if not tracked. |
| `recoveryReferences` | `RecoveryControlDecision` | `executionPersistence.getAllRecoveryControlDecisions()` | `readonly string[]` | List of recovery plan IDs associated with the mission or its goals. |
| `operationReferences` | Stage 22 `auditEventRegistry` | `auditEventRegistry.getEventsByMissionId()` | `readonly string[]` | List of operation IDs associated with the mission. |
| `risks` | `MissionRisk` | `mission.plans[currentPlanVersion]?.riskAssessment` | `readonly MissionRisk[]` | Scrubbed risk assessments from the current active plan. |
| `blockers` | `MissionGoalReference` / `dependencies` | Blocked goals and unsatisfied blocking dependencies | `readonly string[]` | Concrete list of blockers impeding mission progress. |
| `epistemicStatus` | Stage 22 `OperationalAuditEvent` | Derived from latest audit events | `EpistemicStatus` | Epistemic certainty of the overall mission projection. |
| `sourceIntegrity` | Multi-source comparison | Persistence vs Memory vs Envelope comparison | `'AUTHORITATIVE' \| 'INCOMPLETE' \| 'CONFLICTING' \| 'STALE' \| 'UNAVAILABLE'` | Indicates whether source data is complete, conflicting, or stale. |
| `unresolvedDiscrepancies` | Conflict detection | Discrepancies between sources | `readonly string[]` | Explicit human-readable list of contradictions between sources. |
| `createdAt` | `Mission` | `mission.createdAt` | `string \| 'UNKNOWN'` | ISO timestamp. |
| `updatedAt` | `Mission` | `mission.updatedAt` | `string \| 'UNKNOWN'` | ISO timestamp. |
| `projectedAt` | Local monotonic clock | `Date.now()` | `number` | Unix epoch millisecond of projection generation. |

---

## 3. CANONICAL ENUM PRESERVATION MATRIX

Stage 24 Phase 6 preserves all Stage 12 and Stage 08 canonical enums without alteration:

### A. Mission Status (14 Canonical Enums)
1. `DRAFT`
2. `PLANNED`
3. `READY`
4. `RUNNING`
5. `PAUSED`
6. `WAITING_FOR_APPROVAL`
7. `BLOCKED`
8. `DEGRADED`
9. `REPLANNING`
10. `COMPLETED`
11. `PARTIALLY_COMPLETED`
12. `FAILED`
13. `CANCELLED`
14. `ARCHIVED`

### B. Mission Priority (4 Canonical Enums)
1. `LOW`
2. `NORMAL`
3. `HIGH`
4. `CRITICAL`

### C. Dependency Types (2 Canonical Enums)
1. `FINISH_TO_START`
2. `START_TO_START`

### D. Dependency Satisfaction States (5 Projection Enums)
1. `SATISFIED`: Predecessor goal has authoritative `COMPLETED` or `SUCCEEDED` status.
2. `PENDING`: Predecessor goal is `READY`, `RUNNING`, `EXECUTING`, or `PLANNED`.
3. `BLOCKED`: Predecessor goal is `BLOCKED`, `FAILED`, or `CANCELLED`.
4. `MISSING_EVIDENCE`: Predecessor goal record is absent from goal registry, persistence, and envelope.
5. `UNKNOWN`: Predecessor goal state is ambiguous or explicitly `UNKNOWN`.

### E. Source Integrity Categories (5 Enums)
1. `AUTHORITATIVE`: Records match across durable persistence and active runtime without discrepancies.
2. `INCOMPLETE`: Required records (goals, progress, or dependencies) are partially missing.
3. `CONFLICTING`: Durable persistence and active memory report contradictory lifecycle states.
4. `STALE`: Records contain timestamps older than allowed freshness threshold.
5. `UNAVAILABLE`: No records exist in either persistence or runtime memory.

---

## 4. SECURITY & ADVERSARIAL HARDENING RULES

1. **Prototype-Pollution Defense:**
   - All filter and query inputs are stripped of `__proto__`, `constructor`, and `prototype`.
   - String inputs are bounded to 200 characters; numeric inputs are validated as finite, positive integers.
2. **Recursive Secret Scrubbing:**
   - All string fields (mission title, objective, constraints, conditions, risk mitigations) are filtered against token, API key, password, secret, and authorization bearer patterns.
3. **Graph Cycle Protection:**
   - Dependency graph traversal incorporates cycle detection (visited set / Tarjan DFS) with a maximum recursion depth of 20 to prevent infinite loops from malicious or circular dependency graphs.
4. **Numeric Range Clamping:**
   - Progress percentage is strictly clamped to `[0, 100]` and verified finite. If NaN or negative, replaced with honest `0` or `'UNKNOWN'`.
5. **No Forged Status Override:**
   - Client-provided status parameters in query or context cannot override authoritative persistence or runtime state.
6. **Deep Immutability:**
   - All returned summaries and detailed projections are recursively frozen via `deepFreeze()`. Any downstream attempt to mutate properties throws in strict mode and has zero effect.
