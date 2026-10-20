# ARYAOS V1 — STAGE 10: RESOURCE GOVERNANCE & COST SPECIFICATION

## 1. Principles of Autonomous Economy

In AryaOS V1, autonomous agents are not granted an unlimited blank check. Intelligence consumption is governed by four strict economic boundaries:

1. **Financial Preflight Gates**: High-risk or expensive tasks undergo budget verification *prior* to dispatch.
2. **Truthful Accounting**: Costs are never fabricated or guessed based on latency. Missing provider usage is explicitly tracked as `UNKNOWN`.
3. **Strict Concurrency Leases**: Tasks must acquire a `ResourceLease` before dispatching to prevent runtime saturation.
4. **Temporal Feasibility**: Tasks with deadlines are evaluated against estimated provider latency; unfeasible paths trigger `ROUTE_RECONSIDERATION_REQUIRED`.

```
                    ┌───────────────────────────────┐
                    │    Agent Task Scheduled       │
                    └───────────────┬───────────────┘
                                    │
                                    ▼
                    ┌───────────────────────────────┐
                    │   checkBudgetPreflight()      │
                    │   Cost So Far + Est <= Budget?│
                    └───────────────┬───────────────┘
                             NO ╱       ╲ YES
                              ╱           ╲
       ┌────────────────────────┐       ┌───────────────────────────────┐
       │ RESOURCE_BUDGET_       │       │ checkDeadlineFeasibility()    │
       │ EXCEEDED (Halt/Replan) │       │ Now + Latency <= Deadline?    │
       └────────────────────────┘       └───────────────┬───────────────┘
                                                 NO ╱       ╲ YES
                                                  ╱           ╲
                 ┌──────────────────────────────────┐       ┌───────────────────────┐
                 │ ROUTE_RECONSIDERATION_REQUIRED   │       │ acquireLease()        │
                 │ (Replan / Alternate Provider)    │       │ Concurrency Available?│
                 └──────────────────────────────────┘       └───────────┬───────────┘
                                                                 NO ╱       ╲ YES
                                                                  ╱           ╲
                               ┌────────────────────────────────────┐       ┌───────────────────────┐
                               │ CONCURRENCY_LIMIT_REACHED (Queue)  │       │ Grant Resource Lease  │
                               └────────────────────────────────────┘       │ & Dispatch to Gateway │
                                                                            └───────────────────────┘
```

---

## 2. Cost Governance Model

Every goal supports an optional `ResourceBudget`:

```typescript
export interface ResourceBudget {
  maxCostUsd?: number;
  maxLatencyMs?: number;
  maxConcurrentActions: number;     // Default: 3
  maxConcurrentAgents: number;      // Default: 4
  maxRetries: number;               // Default: 2
  maxTokenEstimate?: number;
}
```

### Preflight Budget Verification
Before an action is dispatched to Stage 07's `executionGateway`, the `ResourceGovernor` evaluates:

$$\text{costSoFar} + \text{estimatedUsd} \le \text{maxCostUsd}$$

If this inequality is violated:
- The governor returns `{ allowed: false, reason: 'RESOURCE_BUDGET_EXCEEDED' }`.
- The task is flagged `BLOCKED`.
- The orchestrator can either solicit human approval for a budget increase or replan with cheaper economy models.

### Truthful Cost Accounting
Providers exhibit varying levels of billing transparency:
- If a provider returns usage with `costUsd`: `costSoFar` is incremented accurately.
- If a provider returns `null` or no cost metadata: `actualCost = UNKNOWN` and `costStatus = 'PARTIALLY_KNOWN' | 'UNKNOWN'`.
- **AryaOS never fabricates pricing or multiplies token counts by hardcoded constants to simulate billing.**

---

## 3. Concurrency Governance & Single-Runtime Leases

Every active execution must hold a valid `ResourceLease`:

```typescript
export interface ResourceLease {
  leaseId: string;
  goalId: string;
  taskId: string;
  agentId: string;
  providerId?: string;
  grantedAt: string;
  expiresAt: string;
  estimatedCost: number | null;
  estimatedTokens: number;
}
```

### Concurrency Rules
1. **Per-Goal Action Limit**: Bounded by `budget.maxConcurrentActions` (default 3).
2. **Per-Goal Agent Limit**: Bounded by `budget.maxConcurrentAgents` (default 4).
3. **Per-Agent Limit**: Bounded by `agent.concurrencyLimit` from the Agent Profile.
4. **TTL Expiration**: Leases feature an automatic expiration window (minimum 30 seconds) to prevent permanent resource leaks if a worker terminates abnormally.

---

## 4. Latency Governance & Deadline Feasibility

When a task declares an explicit `deadline`:
- Predicted completion is computed:
  $$\text{predictedTime} = \text{Date.now}() + \text{estimatedLatencyMs}$$
- If $\text{predictedTime} > \text{task.deadline}$:
  - The governor returns `{ allowed: false, reason: 'ROUTE_RECONSIDERATION_REQUIRED' }`.
  - The router/planner is prompted to select a lower-latency model or split the task into parallel sub-tasks rather than risking deadline breach.
