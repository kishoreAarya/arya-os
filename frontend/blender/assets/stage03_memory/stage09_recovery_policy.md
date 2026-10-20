# ARYAOS V1 — STAGE 09: RECOVERY POLICY & CLASSIFICATION SPECIFICATION

## 1. Core Principles of Autonomous Recovery

When AryaOS reboots or recovers from an abnormal termination, it must reconcile the state of all in-flight goals, plans, and actions. The system must never guess, never duplicate external side-effects, and never leave goals permanently stuck in limbo.

The Recovery Engine evaluates interrupted nodes against five deterministic policies:

```
                          ┌───────────────────────────┐
                          │ Interrupted Action Node   │
                          └─────────────┬─────────────┘
                                        │
                         Is action terminal (DONE/FAIL)?
                                       ╱ ╲
                                     YES  NO
                                     ╱     ╲
         ┌───────────────────────────┐      │
         │ TERMINAL_STATE_PRESERVE   │      │
         └───────────────────────────┘      │
                                            ▼
                           Does Gateway Idempotency Cache
                           have a verified completion?
                                       ╱ ╲
                                     YES  NO
                                     ╱     ╲
         ┌───────────────────────────┐      │
         │ DETERMINISTIC_IDEMPOTENT_ │      │
         │ RESUME (Restore Result)   │      │
         └───────────────────────────┘      │
                                            ▼
                           Is action consequential or
                           side-effecting (API/Video)?
                                       ╱ ╲
                                     YES  NO
                                     ╱     ╲
         ┌───────────────────────────┐      │
         │ CONSEQUENTIAL_APPROVAL_   │      │
         │ GATE (Reset & Require     │      │
         │ Human Confirmation)       │      │
         └───────────────────────────┘      │
                                            ▼
                           Is action idempotent & safe?
                                       ╱ ╲
                                     YES  NO
                                     ╱     ╲
         ┌───────────────────────────┐  ┌───────────────────────────┐
         │ DETERMINISTIC_IDEMPOTENT_ │  │ NON_IDEMPOTENT_CANCEL     │
         │ RESUME (Re-enqueue)       │  │ (Mark RECOVERY_REQUIRED)  │
         └───────────────────────────┘  └───────────────────────────┘
```

---

## 2. The Five Classification Policies

### 1. `TERMINAL_STATE_PRESERVE`
- **Applicability**: Actions already in `COMPLETED`, `FAILED`, or `CANCELLED` status at time of snapshot.
- **Action**: Preserved unchanged. Outputs and timestamps remain canonical.

### 2. `DETERMINISTIC_IDEMPOTENT_RESUME`
- **Applicability**:
  - Read-only actions (e.g., `SEARCH_MEMORY`, `ANALYZE_CONTEXT`, `QUERY_VITRINE`).
  - Actions with deterministically verified results in Stage 07's `executionGateway` idempotency cache.
- **Action**: If a verified completion exists in the gateway, it is immediately transitioned to `COMPLETED` with its cached result. Otherwise, it is reset to `PENDING` to be re-executed by the scheduler.

### 3. `CONSEQUENTIAL_APPROVAL_GATE`
- **Applicability**:
  - Any action with consequential impact (`CONSEQUENTIAL`, `EXTERNAL_SIDE_EFFECT`, `VIDEO_GENERATION`, state mutation).
  - Actions that were `EXECUTING` or `AWAITING_APPROVAL` when interrupted.
- **Action**: The action is transitioned to `AWAITING_APPROVAL`. Any prior `approvedAt` timestamp is cleared. A persistent approval record is registered. **Execution will never proceed until an operator explicitly re-confirms the action.**

### 4. `EPHEMERAL_RETRY_BACKOFF`
- **Applicability**: Actions that suffered network dropouts, rate limit (HTTP 429), or transient provider timeout.
- **Action**: Retried via `executionScheduler` using exponential backoff with jitter:
  $$\text{delay} = \min(\text{maxDelay}, \text{baseDelay} \times 2^{\text{attempt}} + \text{jitter})$$

### 5. `NON_IDEMPOTENT_CANCEL`
- **Applicability**: Non-idempotent operations whose execution state is ambiguous and cannot be verified via idempotency keys.
- **Action**: Transitioned to `RECOVERY_REQUIRED` and flagged for manual operator resolution, preventing state corruption.

---

## 3. DAG Frontier Resolution

During recovery, `recoveryManager.getExecutableFrontier(dag)` inspects the dependency graph:
1. An action is eligible for the executable frontier if and only if:
   - Its current status is `PENDING` or `READY`.
   - **All** its direct parent dependencies (`dependencies` array) have reached status `COMPLETED`.
2. Nodes with unmet dependencies remain `BLOCKED`.
3. If any parent has `FAILED` or `CANCELLED`, dependent children are flagged `BLOCKED` or evaluated by replanning.

---

## 4. Boot Recovery Lifecycle

On application mount:
1. `useGoalOrchestration` calls `recoveryManager.recoverAllGoals()`.
2. Any active goal (`RUNNING`, `PLANNING`, `WAITING_APPROVAL`, `RECOVERING`) is inspected.
3. Every action node is classified and updated in persistent storage.
4. The goal status is updated (e.g., restored to `RUNNING` or set to `WAITING_APPROVAL`).
5. A `RECOVERY_COMPLETED` journal event is appended.
6. The UI (`SpatialCommandConsole`) is notified and renders the `DURABLE RECOVERED` badge.
