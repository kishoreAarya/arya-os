# ARYAOS V1 — STAGE 09: EXECUTION JOURNAL SCHEMA

## 1. Specification Overview

The Execution Journal provides an append-only, strictly ordered, monotonically sequenced event log for all autonomous operations within AryaOS V1. It serves as both an immutable operational audit trail and the primary event source for state reconstruction during recovery.

### Storage Key & Sizing
- **Storage Key**: `aryaos_v1_orchestration_journal`
- **Max In-Memory/Local Records**: 1,000 entries (sliding window with oldest entry archiving).
- **Monotonic Sequencing**: Sequenced via `seq` integer incrementing from `1`.

---

## 2. Event Structure

Every event in the journal conforms to `JournalEvent`:

```typescript
export interface JournalEvent {
  seq: number;                          // Monotonically increasing sequence number (1, 2, 3...)
  eventId: string;                      // Unique UUIDv4 identifier
  timestamp: string;                    // ISO 8601 UTC timestamp
  eventType: OrchestrationJournalEventType; // One of 22 strongly-typed events
  goalId?: string;                      // Associated goal ID
  actionId?: string;                    // Associated action ID (if applicable)
  details: Record<string, unknown>;     // Structured event payload (guaranteed scrubbed of secrets)
}
```

---

## 3. The 22 Journal Event Types

| Category | Event Type | Description |
| :--- | :--- | :--- |
| **Goal Lifecycle** | `GOAL_CREATED` | Goal submitted and initialized into persistence |
| | `GOAL_STATUS_CHANGED` | Transition between `PENDING`, `PLANNING`, `RUNNING`, `PAUSED`, `RECOVERING`, `COMPLETED`, `FAILED`, `CANCELLED` |
| **Planning & DAG** | `PLAN_GENERATED` | Decomposition completed with action nodes and dependency edges |
| | `DAG_MUTATION` | Dynamic graph modification during execution or replanning |
| | `REPLAN_TRIGGERED` | Plan evaluation triggered due to failure, drift, or new observations |
| **Action Execution** | `ACTION_SCHEDULED` | Action enqueued into the Execution Scheduler |
| | `ACTION_DISPATCHED` | Action dispatched to `executionGateway.execute()` |
| | `ACTION_COMPLETED` | Execution returned with normalized success result |
| | `ACTION_FAILED` | Execution threw error or returned provider failure |
| | `ACTION_PAUSED` | Action execution paused due to user command or system halt |
| | `ACTION_RESUMED` | Action execution resumed from pause |
| | `ACTION_RECOVERY_REQUIRED`| Action interrupted by crash or timeout, requiring recovery classification |
| **Human Approvals**| `APPROVAL_REQUESTED` | High-impact / consequential action suspended pending human consent |
| | `APPROVAL_GRANTED` | Operator approved execution |
| | `APPROVAL_REJECTED` | Operator rejected execution, triggering replan or failure |
| **Recovery Engine** | `RECOVERY_INITIATED` | Boot recovery process initiated for interrupted goals |
| | `RECOVERY_COMPLETED` | Goal and DAG frontier successfully reconciled and restored |
| | `IDEMPOTENCY_HIT` | Interrupted action verified as completed via Gateway idempotency cache |
| **Scheduler** | `JOB_ENQUEUED` | Scheduler job scheduled with delay or dependency trigger |
| | `SCHEDULER_HEARTBEAT` | Periodic execution loop tick |
| **Safety & Telemetry**| `SECRET_SCRUBBED` | Sensitive credential detected and masked prior to storage |
| | `TELEMETRY_LOGGED` | Quota warning, timing metric, or operational signal recorded |

---

## 4. Replay & Audit Capabilities

1. **Deterministic State Reconstruction**:
   Starting from `GOAL_CREATED`, the exact state of any goal and DAG can be reconstructed by playing forward events up to sequence $N$.
2. **Crash-Safe Sequence Counter**:
   The sequence counter persists in `localStorage` alongside the event array, ensuring sequence monotonicity across page reloads.
3. **Real-time Subscriptions**:
   `executionJournal.subscribe(listener)` notifies subscribers synchronously on every append, allowing UI components like `SpatialCommandConsole` to mirror the live operational trace.
