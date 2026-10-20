# ARYAOS V1 — STAGE 10: AGENT CONFLICT RESOLUTION SPECIFICATION

## 1. Conflict Management Overview

When multiple autonomous agents operate against the same goal or shared spatial memory, conflicts can arise across resource access, data mutation, and reasoning outputs. 

The `agentConflictManager` provides deterministic conflict detection, structured provenance recording, and non-destructive resolution strategies.

```
                          ┌───────────────────────────┐
                          │   Active Agent Operations │
                          └─────────────┬─────────────┘
                                        │
                         Conflict Condition Detected?
                                       ╱ ╲
                                     YES  NO
                                     ╱     ╲
         ┌───────────────────────────┐      │
         │ Record ConflictRecord     │      │ Normal Flow Continues
         │  - Conflicting Tasks      │      │
         │  - Conflicting Agents     │      │
         │  - Provenance Chains      │      │
         └─────────────┬─────────────┘      │
                       │                    │
                       ▼                    ▼
         ┌───────────────────────────┐
         │ Select Resolution Strategy│
         ├───────────────────────────┤
         │ 1. REVIEW  (Human Gate)   │
         │ 2. REPLAN  (New Plan vN+1)│
         │ 3. RESOLVE (Deterministic)│
         └───────────────────────────┘
```

---

## 2. The Six Conflict Categories

| Category | Description | Detection Mechanism |
| :--- | :--- | :--- |
| `MEMORY_WRITE_CONFLICT` | Two or more tasks attempt concurrent `WRITE` or `READ_WRITE` locks on the same Stage 04 memory entity. | Evaluated via `memoryLockManager.acquireLocks()`. |
| `CONTRADICTORY_OUTPUT` | Multiple agents assigned to evaluate the same question produce incompatible assertions (e.g. one claims success while another reports critical failure). | Evaluated via `agentConflictManager.detectContradictoryOutputs()`. |
| `DUPLICATE_TASK_ASSIGNMENT` | An action is inadvertently assigned to two agents simultaneously. | Evaluated via `agentCoordinator.activeTasks` map. |
| `DUPLICATE_EXECUTION` | An identical action payload is dispatched while already in-flight. | Evaluated via `executionGateway.hasInFlightExecution()`. |
| `INCOMPATIBLE_RESOURCE_OWNERSHIP`| Two agents attempt to claim exclusive ownership of the same video/audio rendering pipeline stage. | Evaluated via `resourceGovernor` lease table. |
| `CIRCULAR_DEPENDENCY` | An action graph contains an acyclic violation where node A depends on B and B depends on A. | Evaluated via Kahn's algorithm in `planGenerator`. |

---

## 3. Conflict Record Schema

All detected conflicts are recorded as first-class entities:

```typescript
export interface ConflictRecord {
  conflictId: string;
  goalId: string;
  category: ConflictCategory;
  conflictingTaskIds: string[];
  conflictingAgentIds: string[];
  resourceOrMemoryId?: string;
  description: string;
  detectedAt: string;
  resolvedAt?: string;
  resolutionStrategy?: ConflictResolutionStrategy;
  resolutionDetails?: string;
  provenanceRecords: Record<string, unknown>[];
}
```

---

## 4. Resolution Strategies

1. **`REVIEW`**:
   - The affected tasks are suspended in `BLOCKED` status.
   - A human approval request is recorded in `executionPersistence`.
   - The operator inspects the contradictory evidence and selects the canonical result.
2. **`REPLAN`**:
   - The conflict is logged into the goal's replan reason.
   - The goal transitions to `REPLANNING`.
   - `planGenerator.generateReplan()` produces `Plan vN+1`, serializing dependent operations or allocating segregated memory partitions.
3. **`RESOLVE`**:
   - Deterministic policy-based arbitration:
     - For memory write conflicts: The task with higher priority (`CRITICAL` > `HIGH` > `MEDIUM` > `LOW`) or earlier creation timestamp is granted the lock; the other task is queued.
     - For consensus voting: If consensus threshold is met, the outlier is marked `SKIPPED`.
