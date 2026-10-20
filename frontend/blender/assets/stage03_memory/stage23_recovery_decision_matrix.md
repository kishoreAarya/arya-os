# ARYAOS V1 — STAGE 23: RECOVERY DECISION MATRIX
## UNIFIED DECISION SURFACE, PRECEDENCE HIERARCHY & RECOVERY OUTCOME MAPPINGS

**STATUS:** FROZEN & RATIFIED ARCHITECTURAL CONTRACT  
**BOUNDARY:** STAGE 23 RECOVERY CONTROL PLANE (`RecoveryControlPlane`)  

---

### 1. Architectural Axioms

1. **Unified Control Plane Façade**: Phase 8 unifies all recovery capabilities implemented across Phases 1 through 7 into a single deterministic decision surface ([`RecoveryControlPlane`](file:///Users/venkatakishorenasina/Documents/arya-os-v1/frontend/src/services/recoveryControlPlane.ts)).
2. **Zero Direct Execution**: The control plane emits immutable, strongly-typed decisions ([`RecoveryControlDecision`](file:///Users/venkatakishorenasina/Documents/arya-os-v1/frontend/src/types/recoveryControl.ts)). It does NOT execute external network calls, invoke provider SDKs, dispatch Action Bus requests, or bypass connector transports.
3. **Safety & Epistemic Honesty Dominate Optimization**: An operation whose external state is unknown can never be assumed successful or failed without verification. Retry optimization is strictly subordinated to state certainty and cascade containment.
4. **Fail-Closed on Uncertainty**: Ambiguity or staleness in governance, approvals, or policies strictly demands human intervention (`REQUIRE_APPROVAL`) or escalation (`ESCALATE`).
5. **Finite Bounded Loops**: All recovery dimensions enforce strict constants:
   - `MAX_RECOVERY_DEPTH = 3`
   - `MAX_AUTOMATIC_RETRIES = 2`
   - `MAX_RECONCILIATION_ATTEMPTS = 3`
   - `MAX_CASCADE_DEPTH = 5`
   - `MAX_CONCURRENT_AFFECTED_OPERATIONS = 50`

---

### 2. Deterministic Decision Precedence Hierarchy

When evaluating operational evidence, the Recovery Control Plane evaluates conditions strictly in the following precedence order:

```
+----+----------------------------------+-----------------------------------------------------------+
|Tier| Precedence Category              | Primary Decision Impact                                   |
+----+----------------------------------+-----------------------------------------------------------+
| 1  | SYSTEM SAFETY & RECURSION BOUNDS | ESCALATE / ABORT (depth >= 3, retries >= 2, probes >= 3)  |
| 2  | UNKNOWN EXTERNAL STATE           | RECONCILE / REQUIRE_APPROVAL (never blind retry)          |
| 3  | PARTIAL EXECUTION                | COMPENSATE / RECONCILE / RESUME (preserve completed steps)|
| 4  | CASCADE CONTAINMENT OVERRIDE     | ABORT / PAUSE / ISOLATE / ESCALATE (cannot downgrade)    |
| 5  | GOVERNANCE / AUTH REQUIREMENT    | REQUIRE_APPROVAL (Stage 21 human operator gate)           |
| 6  | RECONCILIATION REQUIREMENT       | RECONCILE (bounded status probe via Stage 15/22)          |
| 7  | COMPENSATION REQUIREMENT         | COMPENSATE (declarative reverse action via Phase 6)       |
| 8  | STALE STATE                      | RECONCILE (refresh snapshot / token)                      |
| 9  | RESOURCE / DEPENDENCY            | WAIT (backoff throttle / await prerequisite DAG)          |
| 10 | TRANSIENT RETRY                  | RETRY (safe idempotency + unexhausted retry budget)       |
| 11 | CONFIRMED SUCCESS / RESUME       | NO_RECOVERY_REQUIRED / RESUME                             |
+----+----------------------------------+-----------------------------------------------------------+
```

---

### 3. Unified Recovery Decision Matrix

| Operational Evidence / State Pattern | Classification | Safety / Cascade Context | Recovery Outcome | Recommended Action | Risk Level | Human Approval Required? |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| Confirmed Success (`confirmedSuccess: true`) | `SYSTEM_INTERRUPTION` | Operational truth confirms completion | **NO_RECOVERY_REQUIRED** | `WAIT` | `LOW` | **NO** |
| Recovery Depth $\ge 3$ (`MAX_RECOVERY_DEPTH`) | `SYSTEM_INTERRUPTION` | Recursion depth limit exhausted | **ESCALATE** | `WAIT` | `HIGH` | **YES** (`actorType === 'USER'`) |
| Retry Count $\ge 2$ (`MAX_AUTOMATIC_RETRIES`) | `TRANSIENT` | Automatic retries exhausted | **ESCALATE** | `WAIT` | `HIGH` | **YES** (`actorType === 'USER'`) |
| Reconciliation Attempts $\ge 3$ | `UNKNOWN_EXTERNAL_STATE` | External probes unresolved | **ESCALATE** | `WAIT` | `HIGH` | **YES** (`actorType === 'USER'`) |
| Post-dispatch timeout / Unconfirmed state | `UNKNOWN_EXTERNAL_STATE` | Epistemic state `UNKNOWN` (Standard) | **RECONCILE** | `RECONCILE` | `MEDIUM` | **NO** (Read-only probe) |
| Post-dispatch timeout on Critical operation | `UNKNOWN_EXTERNAL_STATE` | Epistemic state `UNKNOWN` (Critical risk) | **REQUIRE_APPROVAL** | `REQUIRE_APPROVAL` | `CRITICAL` | **YES** (`actorType === 'USER'`) |
| Partial execution with safe declarative inverse | `PARTIAL_EXECUTION` | Step 1 succeeded, Step 2 failed | **COMPENSATE** | `COMPENSATE` | `MEDIUM` | **NO** (Automated governance) |
| Partial execution with destructive inverse | `PARTIAL_EXECUTION` | High-risk reverse mapping (e.g. delete file) | **REQUIRE_APPROVAL** | `REQUIRE_APPROVAL` | `HIGH` | **YES** (`actorType === 'USER'`) |
| Partial execution with irreversible action | `PARTIAL_EXECUTION` | `COMPENSATION_UNAVAILABLE` (email/broadcast)| **ESCALATE** | `WAIT` | `HIGH` | **YES** (`actorType === 'USER'`) |
| Cascade: Trigger cycle / Deep reaction ($\ge 5$) | Any | `REACTION_CASCADE` (Stage 19) | **PAUSE** | `PAUSE` | `HIGH` | **YES** (`actorType === 'USER'`) |
| Cascade: Connector failure ($\ge 3$ faults) | Any | `CONNECTOR_FAILURE` (Stage 16) | **ABORT** | `ABORT` | `HIGH` | **YES** (`actorType === 'USER'`) |
| Cascade: System-wide failure (Resource + API) | Any | `SYSTEM_WIDE_FAILURE` | **ABORT** | `ABORT` | `CRITICAL` | **YES** (`actorType === 'USER'`) |
| Stale Governance Approval (`stale: true`) | Any | Snapshot expired or drifted | **REQUIRE_APPROVAL** | `REQUIRE_APPROVAL` | `HIGH` | **YES** (`actorType === 'USER'`) |
| Unknown Governance Authority (`unknown: true`) | Any | Governance engine unreachable | **REQUIRE_APPROVAL** | `REQUIRE_APPROVAL` | `HIGH` | **YES** (`actorType === 'USER'`) |
| Pre-dispatch transient error on idempotent op | `TRANSIENT` | Safe idempotency, retryCount < 2 | **RETRY** | `RETRY` | `LOW`/`MEDIUM` | **NO** |
| Post-dispatch transient on non-idempotent op | `TRANSIENT` | Duplicate side effect risk | **RECONCILE** | `RECONCILE` | `HIGH` | **NO** (Read-only probe) |
| Stale state snapshot | `STALE_STATE` | Epistemic drift | **RECONCILE** | `RECONCILE` | `MEDIUM` | **NO** |
| Resource quota saturation | `RESOURCE` | Memory / rate limit threshold | **WAIT** | `WAIT` | `MEDIUM` | **NO** |
| Upstream dependency missing | `DEPENDENCY` | Prerequisite DAG node pending | **WAIT** | `WAIT` | `MEDIUM` | **NO** |
| Policy rejection (`matchedPolicy: DENY`) | `POLICY` | Security policy blocked execution | **ABORT** | `ABORT` | `HIGH` | **NO** (Terminal abort) |
| Permission revocation | `PERMISSION` | Connector scope/grant revoked | **REQUIRE_APPROVAL** | `REQUIRE_APPROVAL` | `HIGH` | **YES** (`actorType === 'USER'`) |
| Permanent client error (HTTP 4xx / malformed) | `PERMANENT` | Unrecoverable client syntax | **ABORT** | `ABORT` | `LOW` | **NO** |

---

### 4. Recovery Outcome Definitions

1. **NO_RECOVERY_REQUIRED**: Operation is already confirmed completed or successful; retries and recovery are strictly prohibited to avoid duplicate side effects.
2. **RETRY**: Immediate or backoff retry permitted strictly for pre-dispatch failures on idempotent operations.
3. **RESUME**: Continue interrupted execution from last verified checkpoint without replaying completed steps.
4. **ROLLBACK**: Revert local transactional state to a previous clean snapshot.
5. **COMPENSATE**: Execute a newly governed, declarative compensating operation to counteract completed side effects.
6. **RECONCILE**: Schedule a bounded, read-only status inquiry to inspect actual external reality without mutating state.
7. **WAIT**: Defer execution pending prerequisite resolution, rate-limit window reset, or queue draining.
8. **REQUIRE_APPROVAL**: Suspend autonomous execution until an authenticated human operator (`actorType === 'USER'`) approves progression via Stage 21 Governance.
9. **PAUSE**: Temporarily halt execution of triggers, reactions, or missions to contain active feedback loops.
10. **ABORT**: Terminate the affected operation DAG and record a terminal audit record in Stage 22.
11. **ESCALATE**: Raise operational alert to SecOps / system operators with diagnostic causal context.
12. **UNKNOWN**: Fallback state when operational evidence is completely indeterminate; defaults to fail-closed containment.

---

### 5. Control-Plane Lifecycle State Machine

```
              +-------------------+
              |     RECEIVED      |
              +---------+---------+
                        |
                        v
              +-------------------+
              |     VALIDATED     |
              +---------+---------+
                        |
                        v
              +-------------------+
              |    CLASSIFIED     |
              +---------+---------+
                        |
                        v
              +-------------------+
              |     ASSESSED      |
              +---------+---------+
                        |
                        v
              +-------------------+
              |      PLANNED      |
              +----+---------+----+
                   |         |
     (Governance)  |         | (Direct Decision)
                   v         |
         +-----------------+ |
         |GOVERNANCE_REQ'D | |
         +---------+-------+ |
                   |         |
                   +----+----+
                        |
                        v
              +-------------------+
              |      DECIDED      |
              +---------+---------+
                        |
                        v
              +-------------------+
              |     ESCALATED     |  (Terminal State)
              +-------------------+
```
