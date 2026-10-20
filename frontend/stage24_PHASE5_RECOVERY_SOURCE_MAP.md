# ARYAOS V1 — STAGE 24 — PHASE 5
# RECOVERY OPERATIONS PROJECTION SOURCE MAP

**STATUS:** AUTHORITATIVE ARCHITECTURAL SPECIFICATION & SOURCE MAP  
**SUBSYSTEM:** Stage 24 Mission Operations Control Plane  
**PROJECTION FACADE:** `controlPlaneSnapshotService.projectRecovery()`  
**TARGET CONTRACT:** `RecoverySummary` & `ControlPlaneSnapshot` (`src/types/controlPlane.ts`)  

---

## 1. ARCHITECTURAL BOUNDARIES & AUTHORITY HIERARCHY

Stage 24 is strictly an **observational projection**, NOT a recovery controller.

```
Existing Subsystems & Authoritative Owners:
┌────────────────────────────────────────────────────────────────────────┐
│ Stage 23: Recovery Control Plane (Sole Recovery Decision Authority)    │
│           - FailureClassification, RecoveryPlan, SafetyAssessment      │
│           - ReconciliationRequirement, CompensationPlan, CascadeRecord │
│           - RecoveryControlDecision                                    │
├────────────────────────────────────────────────────────────────────────┤
│ Stage 09: Execution Persistence & Journal (Durable Storage Owner)      │
│           - executionPersistence.getAllRecoveryControlDecisions()      │
│           - executionPersistence.loadEnvelope().recoveryControlDecisions│
│           - executionJournal.appendEvent() (read-only audit trail)     │
├────────────────────────────────────────────────────────────────────────┤
│ Stage 22: Operational Truth & Causal Audit (Empirical Reality Owner)   │
│           - operationalTruthService.getOperationState()                │
│           - auditEventRegistry.getAllEvents()                          │
│           - causalTraceService.buildCausalGraph()                      │
├────────────────────────────────────────────────────────────────────────┤
│ Stage 21: Governed Policy Control Plane (Policy Authority Owner)       │
│           - governanceControlPlane                                     │
│           - governanceStalenessService                                 │
└────────────────────────────────────────────────────────────────────────┘
                                    │ (READ-ONLY PROJECTION)
                                    ▼
┌────────────────────────────────────────────────────────────────────────┐
│ Stage 24: Mission Operations Control Plane Facade                      │
│           - controlPlaneSnapshotService.projectRecovery()              │
│           - Output: readonly RecoverySummary[] (Deeply Frozen)         │
└────────────────────────────────────────────────────────────────────────┘
```

### Absolute Invariants & Prohibitions
1. **Zero Recovery Authority Created:** Stage 24 does not evaluate safety, does not generate recovery plans, does not decide next actions.
2. **Zero Recovery Execution:** The following operations are strictly PROHIBITED during projection reads:
   `retry`, `resume`, `rollback`, `compensate`, `reconcile`, `dispatch`, `abort`, `approve`, `authorize`, `execute`, `recover`.
3. **Zero Policy Mutation:** Stage 20/21 policy evaluations and snapshots are never modified or re-evaluated.
4. **Zero Action Bus Dispatch:** `actionBusService.dispatchAction` is never invoked.
5. **Zero Persistence Mutation:** No records are inserted, updated, or deleted in `executionPersistence`.
6. **Epistemic Honesty:** Unverified, absent, or ambiguous external states remain `'UNKNOWN'`; never converted to synthetic success or failure.
7. **Requirement != Outcome:**
   - `approvalRequirement.required: true` does NOT mean approval granted.
   - `reconciliationRequirement.required: true` does NOT mean reconciliation completed.
   - `compensationPlan` present does NOT mean compensation executed.

---

## 2. FIELD-BY-FIELD AUTHORITATIVE MAPPING MATRIX

Every field projected in `RecoverySummary` is bound to its canonical authoritative source, read method, data type, and epistemic meaning:

| `RecoverySummary` Field | Authoritative Source Entity | Source Read Method / Path | Canonical Domain Type | Epistemic Meaning & Fallback Rules |
| :--- | :--- | :--- | :--- | :--- |
| `recoveryPlanId` | `RecoveryControlDecision` / `RecoveryPlan` | `decision.recoveryPlanId` / `plan.recoveryPlanId` | `string \| 'UNKNOWN'` | Exact canonical ID of the proposed recovery plan. Falls back to `'UNKNOWN'` if missing. Never fabricated. |
| `originalOperationId` | `RecoveryControlDecision` | `decision.originalOperationId \|\| decision.operationId` | `string` | The canonical identifier of the failed or interrupted operation being recovered. |
| `failureClassification` | `RecoveryControlDecision` | `decision.classification` | `FailureClassification` (13 canonical categories) | Empirical classification determined by Stage 23 `FailureClassificationService`. Preserves all 13 canonical categories; `'UNKNOWN'` if missing. |
| `currentTruthState` | Stage 22 `OperationalAuditEvent` / `RecoveryControlDecision` | `decision.epistemicStatus` verified against Stage 22 audit | `EpistemicStatus \| 'UNKNOWN'` | Empirical truth state from Stage 22 (`OBSERVED`, `CONFIRMED`, `INFERRED`, `PROJECTED`, `DISPUTED`, `CONTRADICTED`, `STALE`, `UNKNOWN`). Preserves `'UNKNOWN'` when external confirmation is absent. |
| `proposedRecoveryAction` | `RecoveryControlDecision` | `decision.recommendedAction` | `RecoveryAction` (11 canonical outcomes) | The deterministic safe next action recommended by Stage 23 matrix (`RETRY`, `RESUME`, `ROLLBACK`, `COMPENSATE`, `RECONCILE`, `WAIT`, `REQUIRE_APPROVAL`, `PAUSE`, `ABORT`, `ESCALATE`, `UNKNOWN`). |
| `riskLevel` | `RecoveryControlDecision` | `decision.riskLevel` | `ActionRiskLevel \| 'UNKNOWN'` | Consequential risk rating (`LOW`, `MEDIUM`, `HIGH`, `CRITICAL`). |
| `idempotencyAssessment` | `RecoverySafetyAssessment` | `decision.safetyAssessment.idempotencyClassification` | `IdempotencyClassification \| 'UNKNOWN'` | Side-effect profile (`READ_ONLY`, `IDEMPOTENT`, `CONDITIONALLY_IDEMPOTENT`, `NON_IDEMPOTENT`, `UNKNOWN`). |
| `requiredAuthority` | `RecoveryControlDecision` | `decision.requiredAuthority` | `readonly string[] \| 'UNKNOWN'` | Array of authority roles/capabilities required before dispatch. Deeply frozen. |
| `governanceDecisionId` | `RecoveryControlDecision` | `decision.governanceDecisionId` | `string \| 'UNKNOWN'` | Canonical ID of the associated Stage 21 `GovernanceDecision`. `'UNKNOWN'` if not yet governed. Never fabricated. |
| `approvalRequirement` | `RecoveryControlDecision` | `decision.governanceRequirement` + `decision.approvalIdentity` | `{ required: boolean; humanOperatorRequired: boolean; approvedBy?: string } \| 'UNKNOWN'` | Distinguishes approval *requirement* from approval *grant*. `approvedBy` is populated ONLY if authoritative `approvalIdentity` exists. |
| `reconciliationRequirement` | `RecoveryControlDecision` / `RecoverySafetyAssessment` | `decision.reconciliationRequirement` | `{ required: boolean; postCompensationVerification?: boolean; timeoutMs?: number } \| 'UNKNOWN'` | Distinguishes reconciliation *requirement* from *completion*. Declarative probe bounds only. |
| `compensationPlan` | `CompensationAssessmentResult` | `decision.compensationAssessment.candidatePlan` | `DeclarativeCompensationPlan \| 'UNKNOWN'` | Declarative reverse-operation metadata (`compensationType`, `targetState`, `reversibilityClass`, `idempotencyKey`). Strictly declarative; NO dispatch. |
| `expectedOutcome` | `RecoveryControlDecision` | `decision.recoveryOutcome` | `RecoveryOutcome \| 'UNKNOWN'` | Safe anticipated outcome (`NO_RECOVERY_REQUIRED`, `RETRY`, `RESUME`, etc.). |
| `expiresAt` | `RecoveryControlDecision` | `decision.expiresAt` | `number \| 'UNKNOWN'` | Unix epoch millisecond TTL of the recovery decision. |
| `causationId` | `RecoveryControlDecision` | `decision.causationId` | `string \| 'UNKNOWN'` | Causal antecedent ID for Stage 22 causal audit tracking. |
| `correlationId` | `RecoveryControlDecision` | `decision.correlationId` | `string \| 'UNKNOWN'` | Correlation root ID tracking the overarching transaction/workflow. |
| `lifecycleState` | `RecoveryControlDecision` | `decision.lifecycleState` | `RecoveryLifecycleState \| RecoveryControlLifecycleState \| 'UNKNOWN'` | Current lifecycle progression or terminal state (`RECEIVED`, `VALIDATED`, `CLASSIFIED`, `ASSESSED`, `PLANNED`, `GOVERNANCE_REQUIRED`, `DECIDED`, `REJECTED`, `EXPIRED`, `ESCALATED`, `UNKNOWN`). |
| `retryCount` | `RecoveryControlDecision` | `decision.retryCount` | `number \| 'UNKNOWN'` | Number of retry attempts previously dispatched for this operation. Bounded by `MAX_AUTOMATIC_RETRIES`. |
| `recoveryDepth` | `RecoveryControlDecision` | `decision.recoveryDepth` | `number \| 'UNKNOWN'` | Current recursion depth of the recovery chain. Bounded by `MAX_RECOVERY_DEPTH` (3). |

---

## 3. CANONICAL ENUM PRESERVATION MATRIX

Stage 24 Phase 5 preserves all Stage 23 canonical enums without alteration:

### A. Failure Classifications (13 Categories)
1. `TRANSIENT`
2. `PERMANENT`
3. `AUTHORIZATION`
4. `PERMISSION`
5. `POLICY`
6. `STALE_STATE`
7. `UNKNOWN_EXTERNAL_STATE`
8. `PARTIAL_EXECUTION`
9. `RECONCILIATION`
10. `RESOURCE`
11. `DEPENDENCY`
12. `SYSTEM_INTERRUPTION`
13. `HUMAN_REQUIRED`

### B. Recovery Actions (11 Outcomes)
1. `RETRY`
2. `RESUME`
3. `ROLLBACK`
4. `COMPENSATE`
5. `RECONCILE`
6. `WAIT`
7. `REQUIRE_APPROVAL`
8. `PAUSE`
9. `ABORT`
10. `ESCALATE`
11. `UNKNOWN`

### C. Recovery Control Lifecycle States
- Progression: `RECEIVED`, `VALIDATED`, `CLASSIFIED`, `ASSESSED`, `PLANNED`, `GOVERNANCE_REQUIRED`, `DECIDED`
- Terminal: `REJECTED`, `EXPIRED`, `ESCALATED`, `UNKNOWN`

### D. Idempotency Classifications
- `READ_ONLY`
- `IDEMPOTENT`
- `CONDITIONALLY_IDEMPOTENT`
- `NON_IDEMPOTENT`
- `UNKNOWN`

---

## 4. DEDUPLICATION, ORDERING & FILTERING RULES

1. **Canonical Deduplication:**
   - Primary key: `decisionId` (or composite key `originalOperationId + recoveryPlanId`).
   - If a duplicate replay record arrives with identical `decisionId`, it is deduplicated.
   - If two distinct decisions exist for the same `operationId` (e.g. initial attempt + escalated attempt), both are preserved.

2. **Deterministic Ordering:**
   - Primary sort: `createdAt` timestamp ascending (oldest first).
   - Secondary sort: `originalOperationId` ascending.
   - Tertiary sort: `decisionId` / `recoveryPlanId` ascending.

3. **Filtering Capabilities:**
   - `operationId` / `originalOperationId`
   - `recoveryPlanId`
   - `decisionId`
   - `missionId`
   - `failureClassification`
   - `lifecycleState`
   - `riskLevel`
   - `maxRecords` (bounded array length)

---

## 5. SECURITY & HOSTILE INPUT DEFENSES

1. **Secret Scrubbing:**
   - Any credentials, bearer tokens (`Bearer ...`), API keys (`sk-...`, `key-...`), or authorization headers in `reasonCodes`, `metadata`, or parameters are scrubbed using regex patterns to `[REDACTED]`.
2. **Prototype Pollution Guard:**
   - Filter options are sanitized: properties with keys `__proto__`, `constructor`, or `prototype` are rejected or dropped.
3. **Deep Immutability:**
   - All returned `RecoverySummary` objects and nested structures (`requiredAuthority`, `approvalRequirement`, `reconciliationRequirement`, `compensationPlan`) are frozen via `deepFreeze()`.
4. **No Code Execution:**
   - Absolutely no `eval()`, `new Function()`, or dynamic code evaluation.
