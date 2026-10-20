# ARYAOS V1 — STAGE 23: FAILURE CONTAINMENT MATRIX
## DETERMINISTIC CASCADE CLASSIFICATION, CONTAINMENT CONTROLS & THRESHOLDS

**STATUS:** FROZEN & RATIFIED ARCHITECTURAL CONTRACT  
**BOUNDARY:** STAGE 23 RECOVERY CONTROL PLANE  

---

### 1. Architectural Axioms

1. **Control and Boundary Protection Only**: Phase 7 evaluates evidence, detects failure cascades, and formulates containment recommendations. It executes zero external network calls, alters zero connector credentials, mutates zero policies, and schedules zero tasks.
2. **Single Failure $\neq$ Cascade**: An isolated failure with single occurrence is deterministically classified as `NO_CASCADE` with containment action `ALLOW`. Cascades require empirical multi-occurrence evidence or structural saturation.
3. **Fail-Closed on Uncertainty**: When governance state, policy currency, or operational truth is ambiguous or stale, Stage 23 immediately selects `REQUIRE_APPROVAL` or `ESCALATE`. Uncertainty is never converted into ambient permission.
4. **Deterministic Thresholds**: All cascade evaluations utilize empirical counters with bounded constants; 0 LLM tokens are consumed.
5. **Anti-Looping Bounds**: Recursion depth is strictly capped at `MAX_CASCADE_DEPTH = 5` and affected operations are capped at `MAX_CONCURRENT_AFFECTED_OPERATIONS = 50`.
6. **Authenticated Operator Gating**: High-severity containment controls (`ISOLATE`, `ABORT`) require authenticated human operator approval (`actorType === 'USER'`) verified via Stage 21 Governance. Synthetic or autonomous actors (`SYSTEM`, `AUTONOMOUS_AGENT`) are rejected.

---

### 2. Failure Containment Matrix

| Cascade Classification | Trigger Conditions | Severity | Containment Action | Required Authority | Scope / Target Boundary | Human Approval Required? |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **NO_CASCADE** | Single failure, failure count $\le 1$, zero dependency/connector faults, zero saturation | `LOW` | `ALLOW` | None | Single operation | **NO** |
| **RETRY_AMPLIFICATION** | Single operation failure count $\ge 3$ consecutive attempts | `MEDIUM` | `THROTTLE` | `RATE_LIMITER_CONTROL` | Operation / Dispatch Queue | **NO** |
| **DEPENDENCY_FAILURE** | Dependency failures $\ge 2$ in operation DAG | `HIGH` | `DEFER` | `DEPENDENCY_ARBITRATION` | Operation + Downstream Dependents | **NO** |
| **CONNECTOR_FAILURE** | Connector-specific transport/adapter failures $\ge 3$ | `HIGH` | `ISOLATE` | `CONNECTOR_LIFECYCLE_CONTROL`, `HUMAN_APPROVAL` | Affected Connector (Stage 16) | **YES** (`actorType === 'USER'`) |
| **PROVIDER_FAILURE** | Model/provider-specific failures $\ge 3$ | `HIGH` | `DEFER` | `PROVIDER_ROUTER_CONTROL` | Affected Provider (Stage 07) | **NO** |
| **PERMISSION_FAILURE** | Stage 16 permission denial / revoked credentials $\ge 2$ | `HIGH` | `REQUIRE_APPROVAL` | `CONNECTOR_CREDENTIAL_REAUTHORIZATION`, `HUMAN_APPROVAL` | Connector Credentials (Stage 16) | **YES** (`actorType === 'USER'`) |
| **POLICY_BLOCK** | Repeated Stage 20/21 policy denial (`DENY`) $\ge 2$ | `HIGH` | `ABORT` | `POLICY_ADMINISTRATION` | Operation Chain | **YES** (`actorType === 'USER'`) |
| **RECONCILIATION_FAILURE** | Repeated `UNKNOWN` external states $\ge 2$ (epistemic drift) | `HIGH` | `REQUIRE_APPROVAL` | `RECONCILIATION_GATEWAY`, `HUMAN_APPROVAL` | Reconciliation Probe (Stage 15/22) | **YES** (`actorType === 'USER'`) |
| **COMPENSATION_FAILURE** | Reversal/compensation attempts fail $\ge 2$ | `HIGH` | `ESCALATE` | `COMPENSATION_ADMINISTRATION`, `HUMAN_APPROVAL` | Compensation Chain (Stage 23) | **YES** (`actorType === 'USER'`) |
| **REACTION_CASCADE** | Stage 19 trigger cycle detected or reaction depth $\ge 5$ | `HIGH` | `PAUSE` | `TRIGGER_GOVERNANCE`, `HUMAN_APPROVAL` | Trigger Subsystem (Stage 19) | **YES** (`actorType === 'USER'`) |
| **RECOVERY_CHAIN** | Recursive recovery chain depth $\ge 3$ (`MAX_RECOVERY_DEPTH`) | `HIGH` | `ESCALATE` | `RECOVERY_GOVERNANCE`, `HUMAN_APPROVAL` | Recovery Controller (Stage 23) | **YES** (`actorType === 'USER'`) |
| **RESOURCE_EXHAUSTION** | Memory / disk / quota saturation observed | `HIGH` | `THROTTLE` | `RESOURCE_GOVERNOR` | Subsystem Execution Pool | **NO** |
| **AUTHORIZATION_FAILURE** | Governance approval denials $\ge 2$ | `HIGH` | `REQUIRE_APPROVAL` | `GOVERNANCE_CONTROL_PLANE`, `HUMAN_APPROVAL` | Governance Layer (Stage 21) | **YES** (`actorType === 'USER'`) |
| **MISSION_CASCADE** | Failures impacting $\ge 2$ distinct active missions | `HIGH` | `PAUSE` | `MISSION_CONTROL`, `HUMAN_APPROVAL` | Mission Orchestrator (Stage 12) | **YES** (`actorType === 'USER'`) |
| **SYSTEM_WIDE_FAILURE** | Resource saturation combined with multiple connector or provider failures | `CRITICAL` | `ABORT` | `SYSTEM_ADMIN_INTERVENTION`, `HUMAN_APPROVAL` | Global Control Plane | **YES** (`actorType === 'USER'`) |
| **UNKNOWN_CASCADE** | Unclassified composite failure pattern with multiple symptoms | `MEDIUM` | `ESCALATE` | `SYSTEM_RECOVERY` | Root Operation + Context | **NO** |

---

### 3. Containment Control Definitions

1. **ALLOW**: Operation is safe to execute according to baseline operational policies. No containment intervention required.
2. **THROTTLE**: Rate-limit subsequent invocations using exponential backoff with jitter. Prevents thundering herd and retry storms.
3. **PAUSE**: Temporarily halt execution of triggers, reaction loops, or missions pending queue draining or state inspection.
4. **DEFER**: Delay dispatch until upstream prerequisites or alternative provider routes become available.
5. **REQUIRE_APPROVAL**: Halt automated execution and solicit explicit human confirmation via Stage 21 Governance.
6. **ISOLATE**: Quarantine the faulty connector, provider, or subsystem to prevent cross-boundary contamination.
7. **ABORT**: Terminate the affected operation DAG and record a terminal audit record in Stage 22.
8. **ESCALATE**: Raise operational alert to SecOps / system operators with diagnostic causal context.

---

### 4. Hard Limits & Threshold Constants

```typescript
export const MAX_FAILURES_PER_OPERATION = 3;
export const MAX_FAILURES_PER_DEPENDENCY = 2;
export const MAX_FAILURES_PER_CONNECTOR = 3;
export const MAX_FAILURES_PER_PROVIDER = 3;
export const MAX_CASCADE_DEPTH = 5;
export const MAX_CONCURRENT_AFFECTED_OPERATIONS = 50;
export const MAX_REPEATED_UNKNOWN_STATE = 2;
export const MAX_COMPENSATION_FAILURES = 2;
```

---

### 5. Deterministic Lifecycle State Machine

```
              +-------------------+
              |     DETECTED      |
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
              |CONTAINMENT_PROPOSED|
              +----+---------+----+
                   |         |
     (Governance)  |         | (Direct Human Signoff)
                   v         |
              +---------+    |
              |GOVERNED |    |
              +----+----+    |
                   |         |
                   +----+----+
                        |
                        v
              +-------------------+
              |     CONTAINED     |
              +----+---------+----+
                   |         |
       (Monitoring)|         | (Escalation / Unresolved)
                   v         v
              +---------+ +-------------+
              |MONITORED| |  ESCALATED  |
              +----+----+ +------+------+
                   |             |
        +----------+-------------+
        |          |             |
        v          v             v
  +-----------+ +----------+ +----------+
  | RECOVERED | | REJECTED | | ABORTED  |  (Terminal States)
  +-----------+ +----------+ +----------+
```

---

### 6. Human Operator Approval Validation Contract

To transition a high-severity containment decision into `CONTAINED`:
- The approval actor MUST have `actorType === 'USER'`.
- The approval actor MUST provide a valid, non-empty `actorId`.
- The approval MUST reference a verifiable `governanceDecisionId` from Stage 21.
- Decisions in terminal states (`RECOVERED`, `REJECTED`, `ABORTED`, `EXPIRED`) CANNOT be re-approved.
- Rejection of autonomous / synthetic credentials (`SYSTEM`, `AUTONOMOUS_AGENT`) is absolute.
