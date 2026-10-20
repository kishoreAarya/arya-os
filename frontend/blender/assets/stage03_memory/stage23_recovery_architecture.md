# AryaOS V1 — Stage 23: Resilient Autonomous Operations & Recovery Control Plane Architecture

**Status:** APPROVED & VERIFIED (Stage 23 Phase 3)  
**Baseline:** Stages 01–22 Frozen  
**Subsystems:** `recoveryControl.ts`, `failureClassificationService.ts`, `recoveryPlanService.ts`

---

## 1. Architectural Mission & Absolute Boundaries

Stage 22 established **Operational Truth & Causal Observability**: reconstructing what happened across the runtime without executing new actions.

Stage 23 establishes the **Recovery Control Plane**: determining the **Safe Next State** after failure, interruption, or divergence.

```
       Stage 22 Operational Truth & Causal Trace
                          │
                          ▼
       Stage 23 Phase 2: Failure Classification
       (Evidence -> Deterministic FailureClassification)
                          │
                          ▼
       Stage 23 Phase 3: Recovery Plan Generation
       (FailureClassification + Context -> Proposed RecoveryPlan)
                          │
                          ▼
       Stage 23 Phase 4: Recovery Safety Analysis
       (Plan -> Risk/Loop Guard/Safety Assessment)  [NEXT PHASE]
                          │
                          ▼
       Stage 21: Governed Policy Control Plane
       (Assessment + Context -> Governance Decision)
                          │
                          ▼
       Human Approval (if required)
                          │
                          ▼
       Stage 07/15: Existing Execution Gateway / Action Bus
       (Execution occurs ONLY within established boundaries)
                          │
                          ▼
       Stage 22: Causal Trace & Audit Verification
```

### Absolute Negative Boundaries: What Stage 23 Is NOT
1. **NOT an Execution Engine**: Stage 23 does not call APIs, invoke connectors, dispatch Action Bus messages, or call `executionGateway.execute()`.
2. **NOT an Authorization Authority**: Stage 23 cannot grant permissions or self-escalate capabilities.
3. **NOT a Policy Engine**: Stage 23 cannot mutate or bypass Stage 20/21 policies. If an operation violates policy, the recovery plan routes strictly to `ABORT`.
4. **NOT a Replacement for Stage 09 Goal Recovery**: Stage 09 `recoveryManager` remains authoritative for Goal/Plan/ActionNode DAG frontier recovery. Stage 23 operates at the cross-layer operational control plane.
5. **NOT an LLM Prompt Loop**: Stage 23 runs 100% deterministic TypeScript logic with 0 LLM tokens and 0 stochastic inference.

---

## 2. Separation of Concerns Across Phases

| Phase | Subsystem | Responsibility | Invariant |
| :--- | :--- | :--- | :--- |
| **Phase 1** | `types/recoveryControl.ts`, `services/recoveryControl.ts` | Type definitions, contract schemas, runtime immutability (`deepFreeze`), prototype pollution defenses. | Contract-only. Zero logic. |
| **Phase 2** | `services/failureClassificationService.ts` | Pure evidence-based categorization into 13 failure classifications. | `CLASSIFICATION ≠ ACTION`. Answers *what* failed, never *what to do*. |
| **Phase 3** | `services/recoveryPlanService.ts` | Deterministic safe-next-state evaluation producing an immutable `RecoveryPlan`. | `RECOVERY PLAN ≠ EXECUTION`. Plans default to `PROPOSED`. |
| **Phase 4** | `services/recoverySafetyService.ts` | Safety assessment, anti-loop guards, blast-radius verification. | Rejects unbounded cascades. |
| **Phase 5** | `services/recoveryReconciliationService.ts` | Reconciliation probe formulation before retry. | Read-only probes only. |
| **Phase 6** | `services/recoveryCompensationService.ts` | Declarative reverse-operation compensation graphs. | Zero autonomous reversal. |
| **Phase 7** | `services/recoveryControlPlane.ts` | Unified façade coordinating phases 2–6. | Coordinated control plane. |
| **Phase 8** | Integration & Persistence | Stage 09/20/21/22 integration and durable crash recovery. | Fully audited recovery lifecycle. |

---

## 3. Causal Provenance & Epistemic Guarantees

Every `RecoveryPlan` generated in Phase 3 carries rigorous causal provenance:

1. **`originalOperationId`**: Identifies the exact operational event that encountered failure.
2. **`causationId`**: Direct link to the immediate predecessor event in the Stage 22 causal graph.
3. **`correlationId`**: Cross-cutting trace identifier tracking the overarching user request / mission run.
4. **`epistemicStatus`**:
   - `OBSERVED`: Grounded in unambiguous runtime evidence (e.g., HTTP status code, verified provider payload).
   - `INFERRED`: Derived from environmental heuristics (e.g., timeout without socket response).
   - `UNKNOWN`: Unverifiable external state requiring reconciliation probes prior to side-effect actions.

---

## 4. Idempotency & Reconciliation Invariants

1. **Reconciliation-First on Ambiguity**:
   When an operation times out or returns an unconfirmed status post-dispatch:
   $$\text{DispatchState} \in \{\text{DISPATCHED}, \text{TIMEOUT}\} \land \text{ConfirmedSuccess} = \text{false} \implies \text{RecoveryAction} = \text{RECONCILE}$$
   Blind retries are structurally prohibited.

2. **No Duplicate Side-Effects on Confirmed Success**:
   If Stage 22 operational evidence verifies that the side-effect materialized:
   $$\text{ConfirmedSuccess} = \text{true} \implies \text{RecoveryAction} = \text{WAIT}$$
   Even if the downstream client reported a subsequent timeout or failure, duplicate execution is blocked.

3. **Partial Execution Preservation**:
   If a multi-step operation fails after completing steps $1 \dots k$:
   $$\text{RecoveryAction} = \text{RESUME} \quad \text{with} \quad \text{resumeTargetStepId} = \text{step}_{k+1}$$
   Already completed side-effects are protected from re-execution.

---

## 5. Security & Runtime Hardening

1. **Prototype Pollution Protection**:
   All incoming metadata, parameters, and payloads are recursively checked for malicious keys (`__proto__`, `constructor`, `prototype`). Violations immediately throw `RecoveryContractViolationError`.

2. **Payload Bounding**:
   - Maximum object nesting depth: 5 levels.
   - Maximum key count: 50 keys.
   - Strictly prohibits functions, callbacks, or executable bytecode payloads.

3. **Deep Immutability (`deepFreeze`)**:
   Every generated `RecoveryPlan` and `RecoveryAttemptRecord` is frozen recursively at creation. Any attempt to modify a property raises a runtime `TypeError`.

4. **Zero Governance Fabrication**:
   Generated recovery plans have `governanceDecisionId: undefined`. Stage 23 never pretends to have governance signoff until Stage 21 explicitly grants it.
