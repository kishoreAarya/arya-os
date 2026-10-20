# AryaOS V1 — Stage 23: Deterministic Safe-Next-State Recovery Matrix

**Status:** APPROVED & VERIFIED (Stage 23 Phase 3)  
**Baseline:** Stages 01–22 Frozen  
**Subsystem:** `RecoveryPlanService` (`src/services/recoveryPlanService.ts`)  
**Architectural Axioms:**
1. `CLASSIFICATION ≠ RECOVERY DECISION`
2. `RECOVERY PLAN ≠ EXECUTION`
3. `Zero Execution Logic`: No direct API calls, no network dispatches, zero LLM tokens.
4. `Reconciliation-First on Ambiguity`: Never blind retry on UNKNOWN external state or post-dispatch unconfirmed operations.
5. `No Duplicate Side-Effects`: Confirmed success routes strictly to `WAIT`.

---

## 1. Matrix Input Vector

Every evaluation of the Safe-Next-State matrix accepts an immutable context tuple:

```typescript
type RecoveryMatrixInput = {
  classification: FailureClassification;           // 13 classifications from Phase 2
  dispatchState: DispatchState;                     // NOT_DISPATCHED | DISPATCHED | UNKNOWN | ...
  epistemicStatus: EpistemicStatus;                 // OBSERVED | INFERRED | UNKNOWN
  idempotency: IdempotencyClassification;           // IDEMPOTENT | NON_IDEMPOTENT | CONDITIONALLY_IDEMPOTENT | READ_ONLY | UNKNOWN
  riskLevel: RiskLevel;                             // LOW | MEDIUM | HIGH | CRITICAL
  confirmedSuccess: boolean;                        // Confirmed side-effect already materialized
  partialExecution?: PartialExecutionInfo;          // Step progress if multi-step workflow
  compensationAvailability: CompensationAvailability;// AVAILABLE | UNAVAILABLE | PARTIAL | NO_COMPENSATION_AVAILABLE
};
```

---

## 2. Matrix Output Vector

The evaluation produces deterministic parameters for constructing a frozen `RecoveryPlan`:

```typescript
type RecoveryMatrixOutput = {
  proposedAction: RecoveryAction;                   // Exactly one of the 11 safe next actions
  approvalRequired: boolean;                        // Whether human signoff is required before execution
  approvalType?: ApprovalType;                      // EXPLICIT_CONFIRMATION | SUPERVISOR_OVERRIDE | ESCALATION
  reconciliationRequired: boolean;                  // Whether state reconciliation probe is required
  probeType?: ReconciliationProbeType;              // STATUS_CHECK | GET_BY_IDEMPOTENCY_KEY | RECONCILE_DIFF
  requiredAuthority: string[];                      // Stage 21 authority tokens needed
  expectedOutcome: string;                          // Deterministic audit narrative
};
```

---

## 3. Evaluated Rules & Precedence Hierarchy

The rules are evaluated in a strict, descending precedence order (first match wins):

```
+---------------------------------------------------------------------------------------+
| Rule 1: Confirmed Success Invariant                                                   |
|   confirmedSuccess == true -> WAIT (Approval: false, Reconciliation: false)           |
+---------------------------------------------------------------------------------------+
                                           | (false)
                                           v
+---------------------------------------------------------------------------------------+
| Rule 2: Epistemic Ambiguity / Post-Dispatch Unknown State                             |
|   classification == UNKNOWN_EXTERNAL_STATE OR dispatchState in [DISPATCHED, UNKNOWN]  |
|   -> If CRITICAL: REQUIRE_APPROVAL (SUPERVISOR_OVERRIDE)                              |
|   -> Else: RECONCILE (Probe: STATUS_CHECK / GET_BY_IDEMPOTENCY_KEY)                   |
|   -> If HIGH: approvalRequired = true                                                 |
+---------------------------------------------------------------------------------------+
                                           | (false)
                                           v
+---------------------------------------------------------------------------------------+
| Rule 3: Partial Multi-Step Execution                                                  |
|   classification == PARTIAL_EXECUTION                                                 |
|   -> If [HIGH, CRITICAL]: RESUME (Approval: true)                                     |
|   -> Else: RESUME (Approval: false, Resume Target: resumeTargetStepId)                |
+---------------------------------------------------------------------------------------+
                                           | (false)
                                           v
+---------------------------------------------------------------------------------------+
| Rule 4: Explicit Policy Denial                                                        |
|   classification == POLICY                                                            |
|   -> ABORT (Policy cannot be bypassed or self-mutated)                                |
+---------------------------------------------------------------------------------------+
                                           | (false)
                                           v
+---------------------------------------------------------------------------------------+
| Rule 5: Missing or Revoked Permission                                                 |
|   classification == PERMISSION                                                        |
|   -> REQUIRE_APPROVAL (ESCALATION; agent cannot self-escalate)                        |
+---------------------------------------------------------------------------------------+
                                           | (false)
                                           v
+---------------------------------------------------------------------------------------+
| Rule 6: Capability Authorization Failure                                              |
|   classification == AUTHORIZATION                                                     |
|   -> REQUIRE_APPROVAL (EXPLICIT_CONFIRMATION)                                         |
+---------------------------------------------------------------------------------------+
                                           | (false)
                                           v
+---------------------------------------------------------------------------------------+
| Rule 7: Stale State or Expired TTL                                                    |
|   classification == STALE_STATE                                                       |
|   -> RECONCILE (Probe: RECONCILE_DIFF; snapshot refresh required)                     |
+---------------------------------------------------------------------------------------+
                                           | (false)
                                           v
+---------------------------------------------------------------------------------------+
| Rule 8: Reconciliation Discrepancy                                                    |
|   classification == RECONCILIATION                                                    |
|   -> RECONCILE (Probe: RECONCILE_DIFF)                                                |
|   -> If [HIGH, CRITICAL]: approvalRequired = true                                     |
+---------------------------------------------------------------------------------------+
                                           | (false)
                                           v
+---------------------------------------------------------------------------------------+
| Rule 9: Human Signoff Gate Required                                                   |
|   classification == HUMAN_REQUIRED                                                    |
|   -> REQUIRE_APPROVAL (EXPLICIT_CONFIRMATION)                                         |
+---------------------------------------------------------------------------------------+
                                           | (false)
                                           v
+---------------------------------------------------------------------------------------+
| Rule 10: Permanent Client Error                                                       |
|   classification == PERMANENT                                                         |
|   -> If compensation AVAILABLE: COMPENSATE                                            |
|   -> Else: ABORT                                                                      |
+---------------------------------------------------------------------------------------+
                                           | (false)
                                           v
+---------------------------------------------------------------------------------------+
| Rule 11: Dependency Unsatisfied                                                       |
|   classification == DEPENDENCY                                                        |
|   -> DEGRADE                                                                          |
+---------------------------------------------------------------------------------------+
                                           | (false)
                                           v
+---------------------------------------------------------------------------------------+
| Rule 12: Resource Exhaustion / Rate Limit                                             |
|   classification == RESOURCE                                                          |
|   -> WAIT (Exponential backoff backpressure)                                          |
+---------------------------------------------------------------------------------------+
                                           | (false)
                                           v
+---------------------------------------------------------------------------------------+
| Rule 13: System Interruption / Process Kill                                           |
|   classification == SYSTEM_INTERRUPTION                                               |
|   -> If NOT_DISPATCHED & IDEMPOTENT: RETRY                                            |
|   -> Else: RECONCILE                                                                  |
+---------------------------------------------------------------------------------------+
                                           | (false)
                                           v
+---------------------------------------------------------------------------------------+
| Rule 14: Pure Transient Network Failure                                               |
|   classification == TRANSIENT & NOT_DISPATCHED                                        |
|   -> If IDEMPOTENT: RETRY (Approval: false)                                           |
|   -> If NON_IDEMPOTENT / UNKNOWN: REQUIRE_APPROVAL (Approval: true)                   |
|   -> Fallback: RECONCILE                                                              |
+---------------------------------------------------------------------------------------+
```

---

## 4. Comprehensive Safe-Next-State Matrix Table

| Classification | Dispatch State | Idempotency | Risk Level | Confirmed Success | Recovery Action | Approval Req? | Approval Type | Reconciliation? | Probe Type |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| Any | Any | Any | Any | **true** | `WAIT` | No | — | No | — |
| `UNKNOWN_EXTERNAL_STATE` | `DISPATCHED`/`TIMEOUT` | Non-Idempotent / Unknown | `CRITICAL` | false | `REQUIRE_APPROVAL` | Yes | `SUPERVISOR_OVERRIDE` | Yes | `STATUS_CHECK` |
| `UNKNOWN_EXTERNAL_STATE` | `DISPATCHED`/`TIMEOUT` | Non-Idempotent / Idempotent | `LOW`/`MED`/`HIGH` | false | `RECONCILE` | Yes (if High) | `EXPLICIT_CONFIRMATION` | Yes | `STATUS_CHECK` |
| `PARTIAL_EXECUTION` | `PARTIALLY_DISPATCHED` | Any | `LOW`/`MED` | false | `RESUME` | No | — | No | — |
| `PARTIAL_EXECUTION` | `PARTIALLY_DISPATCHED` | Any | `HIGH`/`CRITICAL` | false | `RESUME` | Yes | `EXPLICIT_CONFIRMATION` | No | — |
| `POLICY` | Any | Any | Any | false | `ABORT` | No | — | No | — |
| `PERMISSION` | Any | Any | Any | false | `REQUIRE_APPROVAL` | Yes | `ESCALATION` | No | — |
| `AUTHORIZATION` | Any | Any | Any | false | `REQUIRE_APPROVAL` | Yes | `EXPLICIT_CONFIRMATION` | No | — |
| `STALE_STATE` | Any | Any | Any | false | `RECONCILE` | No | — | Yes | `RECONCILE_DIFF` |
| `RECONCILIATION` | `DISPATCHED` | Any | `LOW`/`MED` | false | `RECONCILE` | No | — | Yes | `RECONCILE_DIFF` |
| `RECONCILIATION` | `DISPATCHED` | Any | `HIGH`/`CRITICAL` | false | `RECONCILE` | Yes | `EXPLICIT_CONFIRMATION` | Yes | `RECONCILE_DIFF` |
| `HUMAN_REQUIRED` | Any | Any | Any | false | `REQUIRE_APPROVAL` | Yes | `EXPLICIT_CONFIRMATION` | No | — |
| `PERMANENT` | Any | Any | Any | false | `COMPENSATE` (if avail) / `ABORT` | Yes (if comp) | `SUPERVISOR_OVERRIDE` | No | — |
| `DEPENDENCY` | Any | Any | Any | false | `DEGRADE` | No | — | No | — |
| `RESOURCE` | Any | Any | Any | false | `WAIT` | No | — | No | — |
| `SYSTEM_INTERRUPTION`| `NOT_DISPATCHED` | Idempotent | `LOW`/`MED` | false | `RETRY` | No | — | No | — |
| `SYSTEM_INTERRUPTION`| `DISPATCHED` / Other | Any | Any | false | `RECONCILE` | No | — | Yes | `STATUS_CHECK` |
| `TRANSIENT` | `NOT_DISPATCHED` | Idempotent | `LOW`/`MED` | false | `RETRY` | No | — | No | — |
| `TRANSIENT` | `NOT_DISPATCHED` | Non-Idempotent / Unknown | Any | false | `REQUIRE_APPROVAL` | Yes | `EXPLICIT_CONFIRMATION` | No | — |
| `TRANSIENT` | `DISPATCHED` | Any | Any | false | `RECONCILE` | No | — | Yes | `STATUS_CHECK` |

---

## 5. Architectural Verification & Governance Guarantees

1. **Deterministic Execution**:
   - Zero randomness (`Math.random` is used solely for unique plan ID nonce generation).
   - Identical evidence and operational context produce identically structured recovery plans every time.

2. **Epistemic Honesty**:
   - Plans default strictly to `lifecycleState: 'PROPOSED'`.
   - `governanceDecisionId: undefined` — The recovery plan generator never claims or fabricates governance authorization. Stage 21 Governance integration occurs explicitly in later phases.

3. **No Execution Leakage**:
   - No HTTP requests (`fetch`, `axios`), no WebSockets, no Action Bus dispatches (`actionBus.dispatch`), and zero LLM calls.
   - Generation cost: 0 tokens, 0ms network latency.
