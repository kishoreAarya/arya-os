# ARYAOS V1 — STAGE 09: EXECUTION SCHEDULER DESIGN

## 1. Architectural Mission

The AryaOS Execution Scheduler (`executionScheduler.ts`) manages asynchronous job dispatch, timed retries, priority queues, and dependency-triggered unblocking. It functions as the single-runtime scheduling engine for all DAG operations while strictly routing actual provider tasks through Stage 07's `executionGateway`.

```
                    ┌─────────────────────────────────┐
                    │    Goal Orchestration Engine    │
                    └────────────────┬────────────────┘
                                     │
                     scheduleJob(job)│  unblockDependencies()
                                     ▼
                    ┌─────────────────────────────────┐
                    │       Execution Scheduler       │
                    │  - Priority Queue (High/Norm)   │
                    │  - Timer Wheel / Delay Engine   │
                    │  - Exponential Backoff & Jitter │
                    │  - Single Active Execution Lock │
                    └────────────────┬────────────────┘
                                     │
                                     │ dispatch()
                                     ▼
                    ┌─────────────────────────────────┐
                    │    Stage 07 Execution Gateway   │
                    │  (executionGateway.execute)     │
                    └─────────────────────────────────┘
```

---

## 2. Job Model & States

Every scheduled unit of work is modeled as a `SchedulerJob`:

```typescript
export interface SchedulerJob {
  id: string;                     // Unique job ID
  goalId: string;                 // Owning goal
  actionId: string;               // Target action in the DAG
  priority: 'HIGH' | 'NORMAL' | 'LOW';
  status: 'QUEUED' | 'RUNNING' | 'COMPLETED' | 'FAILED' | 'CANCELLED';
  scheduledAt: string;            // Time registered
  executeAfter?: string;          // ISO timestamp for delayed execution
  retryCount: number;             // Current retry attempt
  maxRetries: number;             // Maximum allowable retries
  handler: () => Promise<unknown>;
}
```

---

## 3. Core Scheduling Mechanisms

### Priority Resolution
- Jobs are dequeued by priority: `HIGH` (approvals, recovery reconciliation) precedes `NORMAL` (action execution) and `LOW` (telemetry pruning).
- Equal-priority jobs are dequeued in First-In-First-Out (FIFO) sequence.

### Delayed Execution & Backoff with Jitter
- For delayed operations or rate-limited retry cycles, the scheduler computes:
  $$\text{delay} = \min\left(30000, 1000 \times 2^{\text{attempt}} + \text{floor}(\text{random}() \times 200)\right)\text{ ms}$$
- Timer handles are tracked cleanly to allow cancellation on goal pause or abort.

### Dependency Unblocking
- When an action finishes (`ACTION_COMPLETED`), `unblockDependencies(completedActionId, dag)` is invoked:
  1. Finds all successor nodes in the DAG that declare `completedActionId` in `dependencies`.
  2. Evaluates if all upstream dependencies are now `COMPLETED`.
  3. Automatically schedules newly unblocked nodes into the active queue.

### Single-Runtime Lease & Idempotency Protection
- The scheduler tracks running jobs in `activeJobs: Map<string, SchedulerJob>`.
- Multiple concurrent triggers for the same `actionId` are rejected as duplicates (`IDEMPOTENCY_HIT`).
- If an action already has an in-flight execution registered in `executionGateway`, duplicate dispatch is blocked.
