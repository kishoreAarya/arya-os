# AryaOS V1 — Stage 12: Mission Recovery & State Reconciliation Design

## 1. Crash Recovery Philosophy & Objectives

In long-horizon mission execution spanning hours or days, interruptions are inevitable: browser refreshes, application restarts, process crashes, network loss, and provider timeouts.

AryaOS treats crash recovery as a **deterministic state reconciliation problem**. The recovery architecture guarantees that:
1. **Zero Duplicate Work**: Goals that reached `COMPLETED` or `SUCCEEDED` prior to the crash are never re-executed.
2. **Orphaned State Resolution**: Goals that were `RUNNING` at the moment of failure are identified, audited, and safely rolled back to `PENDING` or evaluated for idempotency.
3. **Deterministic State Replay**: The mission state is reconstructed identically from the latest immutable `MissionCheckpoint` and persistent journal logs.

---

## 2. The Mission Checkpoint Contract

Checkpoints are captured deterministically in `missionCheckpoint.ts` and stored durably in `executionPersistence`:

```typescript
export interface MissionCheckpoint {
  id: string;                      // Unique checkpoint ID (e.g. "chk-m1-v1-step3")
  missionId: string;               // Target mission ID
  planVersion: number;             // Execution plan version (e.g. 1)
  timestamp: string;               // ISO 8601 creation timestamp
  completedGoalIds: string[];      // Verified completed goal IDs
  inFlightGoalIds: string[];       // Goal IDs active when checkpoint was created
  failedGoalIds: string[];         // Goal IDs marked failed
  pendingGoalIds: string[];        // Unstarted goals in graph
  totalTokensConsumed: number;     // Cumulative tokens used up to this point
  totalDurationMs: number;         // Cumulative execution time
  stateHash: string;               // Deterministic SHA-256 state vector fingerprint
}
```

Checkpoints are automatically triggered:
- Prior to entering any new Milestone.
- Immediately after any Goal completes.
- Before pausing, yielding, or initiating a replan.
- At regular time intervals during long-running tasks.

---

## 3. Crash Detection & State Reconciliation Algorithm

When AryaOS initializes (`missionManager.recoverFromCrash()` or `missionCheckpointService.reconcile()`):

```
+-----------------------------------------------------------------------------------+
| 1. Scan Persistent Journal (Stage 09 Storage) for Active / Interrupted Missions    |
+-----------------------------------------------------------------------------------+
                                         |
                                         v
+-----------------------------------------------------------------------------------+
| 2. Load Most Recent Valid Checkpoint for Target Mission                           |
+-----------------------------------------------------------------------------------+
                                         |
                                         v
+-----------------------------------------------------------------------------------+
| 3. State Reconciliation Loop:                                                     |
|    For each Goal in Plan:                                                         |
|      - If Goal in completedGoalIds -> Status remains COMPLETED (IMMUTABLE)        |
|      - If Goal was RUNNING during crash -> Mark as ORPHANED:                       |
|           a. Log recovery audit event                                             |
|           b. Check idempotency contract                                           |
|           c. Reset status to PENDING (re-queue for frontier evaluation)           |
|      - If Goal in pendingGoalIds -> Status remains PENDING                        |
+-----------------------------------------------------------------------------------+
                                         |
                                         v
+-----------------------------------------------------------------------------------+
| 4. Recompute Executable Frontier F(t) from Validated Completed Goals              |
+-----------------------------------------------------------------------------------+
                                         |
                                         v
+-----------------------------------------------------------------------------------+
| 5. Transition Mission State: RECOVERY_REQUIRED -> ACTIVE (or WAITING_APPROVAL)    |
+-----------------------------------------------------------------------------------+
```

---

## 4. Preservation of Completed Work (Strict Invariant)

To guarantee operational efficiency and financial economy:
- All completed artifacts, tool outputs, and memory events produced by finished goals are retained in the Stage 04 Spatial Memory Archive.
- Re-executing a completed goal is treated as a critical system invariant violation.
- If an upstream failure requires re-generating data, the system triggers the **Adaptive Replanner**, which creates an explicit new goal ID rather than mutating the completed goal's record.

---

## 5. Failure Classification & Operator Escalation

If state reconciliation detects inconsistent hashes or unrecoverable journal corruption:
- The mission is marked `RECOVERY_REQUIRED`.
- Automated dispatch is halted.
- The Spatial HUD presents an urgent recovery modal with diagnostic diffs, allowing the human operator to inspect the boundary and approve resumption.
