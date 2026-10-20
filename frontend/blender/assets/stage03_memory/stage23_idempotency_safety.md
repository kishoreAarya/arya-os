# AryaOS V1 — Stage 23: Recovery Safety Analysis, Idempotency Semantics & Duplicate-Side-Effect Prevention

**Status:** APPROVED & VERIFIED (Stage 23 Phase 4)  
**Baseline:** Stages 01–22 Frozen  
**Subsystem:** `RecoverySafetyService` (`src/services/recoverySafetyService.ts`)  
**Core Invariant:**  
> **"Safety assessment is NOT authorization and is NOT execution."**

---

## 1. Purpose

The Stage 23 Recovery Safety Analysis layer evaluates a proposed `RecoveryPlan` in the context of verified operational truth to answer one fundamental question:

$$\textbf{"Is the proposed recovery action SAFE TO PROCEED WITH?"}$$

It evaluates duplicate-side-effect risk, epistemic certainty, idempotency constraints, partial step preservation, and human signoff requirements.

It does **NOT** execute the recovery, authorize the recovery, perform reconciliation, or dispatch external actions.

```
       RecoveryPlan (Phase 3)
                 +
       Operational Truth (Stage 22)
                 +
       Idempotency Context
                 +
       Partial Execution State
                 +
       External Confirmation State
                 │
                 ▼
       RecoverySafetyAssessment (Phase 4)
       [Pure Safety Analysis — Zero Execution — Zero Authorization]
```

---

## 2. Idempotency Classifications & Safety Interpretations

The system evaluates operations according to five canonical idempotency categories:

| Classification | Meaning & Operational Constraint | Retry Safety Semantics |
| :--- | :--- | :--- |
| **`READ_ONLY`** | The operation produces zero external side-effects (e.g. GET requests, cache lookups, status checks). | Safe to repeat from a side-effect perspective (`duplicateSideEffectRisk = 'NONE'`, `retryPermitted = true`). Does **not** confer authorization. |
| **`IDEMPOTENT`** | The operation can be repeated multiple times without changing the final result beyond the initial application (e.g. PUT with deterministic resource state). | Pre-dispatch retry is permitted with `LOW` duplicate risk. Post-dispatch retry requires verified reconciliation. |
| **`CONDITIONALLY_IDEMPOTENT`** | Idempotence is contingent upon specific runtime invariants (e.g. presence of a unique idempotency key, immutable parameters, resource version match). | If conditional requirements are verified, retry is permitted (`LOW` risk). If conditions are unmet or missing, `retryPermitted = false` (`HIGH` risk). |
| **`NON_IDEMPOTENT`** | The operation causes irreversible or accumulating side-effects (e.g. payment transactions, message sends, resource creations). | Blind retries are strictly prohibited (`retryPermitted = false`). Post-dispatch errors route to `reconciliationRequirement = true` and `HIGH`/`CRITICAL` risk. |
| **`UNKNOWN`** | Idempotency semantics cannot be authoritatively established. | Evaluated conservatively. Treated as non-idempotent: `retryPermitted = false`, post-dispatch requires reconciliation. |

---

## 3. Retry Safety Semantics (`retryPermitted`)

The `retryPermitted` boolean field has a strict, unambiguous definition:

> **`retryPermitted` means:**  
> *"Safety analysis finds NO known duplicate-side-effect or state uncertainty barrier preventing a retry."*

### Explicit Non-Meanings
- It does **NOT** mean: "Retry is authorized."
- It does **NOT** mean: "Retry will happen."
- It does **NOT** mean: "Governance approved retry."

### Pre-conditions for `retryPermitted = true`:
1. `confirmedSuccess === false` (action has not already succeeded remotely).
2. `classification !== 'POLICY'` (policy violations cannot be retried).
3. `classification !== 'PERMANENT'` (permanent client rejections will not resolve via retry).
4. `reconciliationRequirement === false` (no outstanding remote uncertainty).
5. `dispatchState === 'NOT_DISPATCHED'` (operation was not dispatched to the network).
6. Idempotency is `READ_ONLY`, `IDEMPOTENT`, or `CONDITIONALLY_IDEMPOTENT` with conditions met.

---

## 4. Duplicate-Side-Effect Prevention

Duplicate execution of external actions can cause severe real-world harm (double charging, duplicate notification blasts, corrupting persistent datasets).

The safety service enforces:
1. **Generic Side-Effect Risk Classification**: Classifies operations into `'NONE'`, `'LOW'`, `'MEDIUM'`, `'HIGH'`, and `'CRITICAL'` risk tiers without numerical heuristics.
2. **Post-Dispatch Replay Guard**: Once dispatch has been attempted (`DISPATCH_ATTEMPTED` or `DISPATCHED`), duplicate side-effect risk is immediately escalated.
3. **Non-Idempotent Protection**: Non-idempotent operations post-dispatch are flagged with `HIGH` or `CRITICAL` duplicate risk, blocking re-execution.

---

## 5. Unknown External State & Reconciliation-First

When network sockets drop, timeouts occur, or HTTP 500/503 errors are returned post-dispatch:

$$\text{DispatchAttempted} \land \text{NoAuthoritativeConfirmation} \implies \text{reconciliationRequirement} = \textbf{true} \land \text{retryPermitted} = \textbf{false}$$

The safety service mandates that reconciliation occur before any recovery action may be considered. Crucially, **the safety service does not perform reconciliation itself**; it only emits the requirement.

---

## 6. Confirmed Success Invariant

A common failure mode in distributed systems is a **local timeout occurring after successful remote execution**:
- Upstream server executes the transaction.
- Response packet is lost or delayed.
- Local client marks the call as timed out.

**Safety Invariant**:  
If authoritative Stage 22 operational evidence indicates `EXTERNAL_CONFIRMATION_RECEIVED` or `confirmedSuccess === true`:
- `retryPermitted = false`
- `duplicateSideEffectRisk = 'CRITICAL'`
- `safetyRationale` contains `CONFIRMED_EXTERNAL_SUCCESS`

This structurally eliminates the catastrophe of replaying a transaction that already succeeded.

---

## 7. Partial Execution Preservation

In multi-step workflows (e.g. step A $\to$ step B $\to$ step C):
- If steps A and B succeed, and step C fails:
  - `completedSteps = ['step-A', 'step-B']`
  - `incompleteSteps = ['step-C', ...]`
- **Preservation Invariant**: `completedSteps` are confirmed complete and **MUST NOT** be marked for replay.
- The service accounts strictly for supplied evidence and does not recalculate DAG execution order.

---

## 8. Compensation & Rollback Availability

- Evaluates `CompensationAvailability` (`'ROLLBACK_AVAILABLE'`, `'COMPENSATION_AVAILABLE'`, `'NO_COMPENSATION_AVAILABLE'`, `'COMPENSATION_UNKNOWN'`).
- If compensation or rollback is available, it is recorded in the assessment for downstream human review or execution planning.
- **Zero Execution**: The safety service does not trigger compensation or rollback; it merely documents their availability from evidence.

---

## 9. Human Approval Separation

The `humanApprovalRequired` flag is derived deterministically from:
- `plan.riskLevel === 'CRITICAL'`
- `plan.riskLevel === 'HIGH'` with partial execution or compensation
- `classification === 'HUMAN_REQUIRED'`
- `classification === 'PERMISSION'` (cannot self-escalate connector permissions)
- `classification === 'AUTHORIZATION'` (unauthorized requests require operator review)
- Post-dispatch non-idempotent operations

**Adversarial Defense**: Untrusted client or HUD payloads supplying `approved: true` or `humanApprovalRequired: false` are strictly ignored. If the operational truth requires human signoff, `humanApprovalRequired` remains `true`.

---

## 10. Governance Separation

- Phase 4 does **NOT** call `governanceControlPlane` or `governanceAuthorityService`.
- It never mutates policies or authority sets.
- It **never generates a `governanceDecisionId`**.
- Safety assessment identifies what approval is needed; Stage 21 Governance Control Plane evaluates authority and generates approval records in later phases.

---

## 11. Architectural Boundaries (Stages 07, 09, 15)

1. **No Second Idempotency Engine**:
   - Stage 07 owns provider/model execution idempotency.
   - Stage 15 owns Action Bus external action idempotency.
   - Stage 23 Phase 4 does not create an idempotency database, cache, or token store.
2. **No Second DAG Engine**:
   - Stage 09 `recoveryManager` remains authoritative for DAG frontier calculation (`getExecutableFrontier()`) and goal crash recovery.
   - Phase 4 consumes supplied step evidence only.

---

## 12. Security & Hardening

1. **Prototype Pollution Defense**:
   All metadata and payload inputs are sanitized via `validateAndSanitizePayload()`. Injections of `__proto__`, `constructor`, or `prototype` immediately trigger `RecoveryContractViolationError`.
2. **Payload Bounding**:
   Enforces maximum nesting depth of 5 and maximum 50 keys. Rejects functions, closures, and executable callbacks.
3. **Deep Immutability**:
   All `RecoverySafetyAssessment` objects are deeply frozen via `deepFreeze()`. Any runtime modification raises a `TypeError`.
