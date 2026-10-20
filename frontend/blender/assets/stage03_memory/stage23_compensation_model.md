# ARYAOS V1 — STAGE 23: DECLARATIVE COMPENSATION MODEL
## RESILIENT AUTONOMOUS OPERATIONS & REVERSE OPERATION GOVERNANCE

**STATUS:** FROZEN & RATIFIED ARCHITECTURAL CONTRACT  
**BOUNDARY:** STAGE 23 RECOVERY CONTROL PLANE  

---

### 1. Architectural Mission & Core Distinction

Stage 23 establishes the controlled recovery layer for the AryaOS runtime. When operational truth and failure classification determine that an operation has executed with unwanted or partial side effects, Stage 23 formulates and governs **Declarative Compensation**.

```
ORIGINAL OPERATION
        ↓
STAGE 22 OPERATIONAL TRUTH
        ↓
FAILURE CLASSIFICATION (Stage 23 Phase 2)
        ↓
RECOVERY PLAN (Stage 23 Phase 3)
        ↓
COMPENSATION ASSESSMENT (Stage 23 Phase 6)
        ↓
DECLARATIVE COMPENSATION PLAN
        ↓
STAGE 20 POLICY & STAGE 21 GOVERNANCE
        ↓
STAGE 15 ACTION BUS / STAGE 07 EXECUTION GATEWAY
        ↓
EXTERNAL COMPENSATING ACTION
        ↓
STAGE 22 VERIFICATION / RECONCILIATION (Stage 23 Phase 5)
        ↓
COMPENSATION RESULT RECORD
```

#### Compensation vs. Rollback: The Critical Distinction
- **Rollback**: An attempt to rewind or overwrite existing state as if the original operation never took place. Rollback assumes transactional reversibility and attempts to mutate historical state records.
- **Compensation**: Performs a **new, independently governed operation** whose explicit semantic purpose is to mitigate, correct, or reverse the observable external side effects of a prior operation.
- **Historic Immutability**: The original operation and its audit records remain **100% immutable**. Stage 23 NEVER mutates historical operational truth into "rolled back", nor does it rewrite Stage 22 audit journals.

---

### 2. Causal Provenance & Identity Invariants

Every compensation operation must maintain strict provenance without identity collision:

| Identity Property | Invariant | Rule |
| :--- | :--- | :--- |
| `compensationId` | Distinct from `originalOperationId` | `compensationId !== originalOperationId` (prefixed `comp_<origOp>_<ts>_<nonce>`) |
| `actionId` | Distinct from `originalActionId` | Dispatched action receives `act_comp_<compPlanId>_<ts>` |
| `idempotencyKey` | Distinct from `originalIdempotencyKey` | Deterministic key `comp-idem-<origOp>-<capability>-<ts>` prevents collision with original mutation |
| `causationId` | Explicit link to original operation | `causationId === originalOperationId` establishes causal lineage |
| `correlationId` | Preserved across entire lifecycle | Preserves root correlation chain from user/event trigger |
| `recoveryDepth` | Bounded execution depth | Increments original depth; strictly rejects `recoveryDepth >= MAX_RECOVERY_DEPTH (3)` |

---

### 3. Compensation Eligibility Model

Compensation is not an ambient right nor an automatic reflex. Stage 23 evaluates operational evidence to assign exactly one of six deterministic eligibility classes:

```
                                  [Assess Evidence]
                                          |
                +-------------------------+-------------------------+
                |                                                   |
       [Pre-Dispatch or Read-Only]                             [Post-Dispatch]
                |                                                   |
   COMPENSATION_NOT_REQUIRED                                        v
                                                        [External State Confirmed?]
                                                                    |
                                                     +--------------+--------------+
                                                     |                             |
                                                 [UNKNOWN]                    [CONFIRMED]
                                                     |                             |
                                        COMPENSATION_REQUIRES                      v
                                            RECONCILIATION             [Explicit Inverse Exists?]
                                                                                   |
                                                                    +--------------+--------------+
                                                                    |                             |
                                                                  [NO]                          [YES]
                                                                    |                             |
                                                              COMPENSATION_                       v
                                                               UNAVAILABLE              [High/Critical Risk?]
                                                                                                  |
                                                                                   +--------------+--------------+
                                                                                   |                             |
                                                                                 [YES]                          [NO]
                                                                                   |                             |
                                                                             COMPENSATION_                 COMPENSATION_
                                                                           REQUIRES_APPROVAL                 ELIGIBLE
```

1. **`COMPENSATION_NOT_REQUIRED`**:
   - Pre-dispatch failure (e.g. policy DENY, authorization refusal before socket connection).
   - Read-only queries (e.g. `web.search`, `filesystem.read`, `github.get_issue`).
   - Verified external non-existence via reconciliation probe (`VERIFIED_FAILURE`).
   - Zero completed milestones in partial workflows.
2. **`COMPENSATION_REQUIRES_RECONCILIATION`**:
   - External state is unconfirmed or indeterminate (`UNKNOWN_EXTERNAL_STATE`).
   - Dispatched operations with absent external confirmation.
   - Probe failure or indeterminate status (`STILL_UNKNOWN`).
   - **Rule**: Never compensate blindly when reality is unknown. Read-only reconciliation must precede compensation.
3. **`COMPENSATION_UNSAFE`**:
   - Recursive depth limit reached (`recoveryDepth >= 3`).
   - Dependency cycle detected (operation already present in `visitedOperationIds`).
   - Missing required target identification parameters (e.g. file path missing for deletion).
4. **`COMPENSATION_UNAVAILABLE`**:
   - Capability is intrinsically irreversible (e.g. `notification.send`, `email.send`, `webhook.trigger`).
   - No registered reverse mapping exists for the capability.
5. **`COMPENSATION_REQUIRES_APPROVAL`**:
   - Destructive operations (e.g. file deletion, database purge).
   - High or Critical risk level capabilities.
   - Requires Stage 21 human operator signature (`actorType === 'USER'`).
6. **`COMPENSATION_ELIGIBLE`**:
   - Confirmed side effect with registered, low/medium risk reverse mapping and all parameters validated.

---

### 4. Compensation Lifecycle State Machine

```
   [PROPOSED] ──(Evaluate Safety/Policy)──> [ASSESSED] ──(Stage 20 Policy)──> [GOVERNED]
        │                                                                           │
        │                                                                (Requires Human Approval?)
        │                                                                           │
        │                                                           +---------------+---------------+
        │                                                           |                               |
        │                                                         [YES]                            [NO]
        │                                                           |                               |
        │                                                           v                               v
        │                                                    (Operator Signoff)                 [READY]
        │                                                           |                               |
        │                                                           v                               │
        │                                                      [APPROVED]                           │
        │                                                           │                               │
        └───────────────────────────────────────────┬───────────────┴───────────────────────────────┘
                                                    │
                                          (Dispatch Boundary)
                                                    │
                                                    v
                                              [DISPATCHED]
                                                    │
                                         (Requires Verification?)
                                                    │
                                    +---------------+---------------+
                                    |                               |
                                  [YES]                            [NO]
                                    |                               |
                                    v                               v
                               [VERIFYING]                     [COMPLETED]
                                    │
                         (Reconciliation Result)
                                    │
                +-------------------+-------------------+
                |                   |                   |
        [VERIFIED_SUCCESS]  [VERIFIED_FAILURE]  [STILL_UNKNOWN / FAILED]
                |                   |                   |
                v                   v                   v
           [COMPLETED]          [FAILED]            [UNKNOWN]
```

#### Terminal States
- `COMPLETED`: Empirical verification confirms the compensating state has been realized.
- `FAILED`: External boundary reported execution error or verified target could not be removed.
- `UNKNOWN`: Probe could not confirm the outcome. Epistemic uncertainty is preserved faithfully.
- `REJECTED`: Stage 21 Governance denied authorization.
- `ABORTED`: Execution cancelled before dispatch.
- `ESCALATED`: Bounded recovery depth exceeded; human administrator intervention requested.

---

### 5. Governance & Human Approval Integration

Stage 23 does NOT invent a parallel authorization mechanism. It binds strictly to **Stage 21 Governance Control Plane**:
1. **Authenticated Human Operators Only**:
   - `actor.actorType` must strictly equal `'USER'`.
   - `actor.actorId` must be a non-empty human operator identity.
   - Roles like `SYSTEM` and `AUTONOMOUS_AGENT` are strictly **REJECTED** from approving destructive compensation.
2. **Cryptographic & Snapshot Integrity**:
   - Human approvals must reference an active `governanceDecisionId`.
   - Client-provided boolean flags (e.g. `approved: true` in metadata) are **STRICTLY REJECTED**.
3. **Execution Gate**:
   - `coordinateCompensation()` rejects any compensation plan in `PROPOSED` state whose `approvalRequirement.required` is `true`.

---

### 6. Execution Boundaries & Epistemic Separation

Stage 23 is a **Control Plane**, not an execution engine.
- **External Capabilities**: Dispatched exclusively through `Stage 15 Universal Action Bus` (`executeActionBus(ActionRequest)`).
- **AI Models & Providers**: Dispatched exclusively through `Stage 07 Execution Gateway` (`executeGateway()`).
- **Zero Direct Network**: ZERO `fetch()`, ZERO Axios, ZERO provider SDKs, ZERO direct filesystem or database mutations.
- **Epistemic Distinction**:
  $$\text{DISPATCHED} \neq \text{EXECUTED} \neq \text{EXTERNALLY\_CONFIRMED} \neq \text{RECONCILED}$$
  Dispatch success merely indicates the request entered transport. The compensation plan moves to `VERIFYING` until Stage 22 empirical observation corroborates `COMPLETED`.

---

### 7. Loop Protection & Anti-Recursion

Unbounded compensation cascades are strictly forbidden:
- **`MAX_RECOVERY_DEPTH = 3`**: Each recovery plan tracks its depth. An attempt to trigger compensation from a recovery action at depth 3 yields `COMPENSATION_UNSAFE` with immediate escalation.
- **Cycle Detection**: The system tracks `visitedOperationIds`. If an operation ID or compensation ID appears more than once in the lineage, the cycle is aborted immediately.
