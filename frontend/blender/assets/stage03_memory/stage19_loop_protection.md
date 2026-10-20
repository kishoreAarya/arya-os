# AryaOS V1 Stage 19 — Loop Protection, Cycle Detection & Causal Depth Bounding

## 1. The Risk of Event-Action Feedback Loops

In reactive architectures, external actions frequently generate subsequent events. For example:
```
External Issue Created
  ──► AryaOS Trigger: Post Comment
         ──► GitHub Comment Created Event
                ──► AryaOS Trigger: Post Reply Comment
                       ──► Infinite Recursive Loop (Financial/Resource Exhaustion)
```

Without strict causal loop protection, event-driven engines risk cascading amplification, API quota exhaustion, and denial of service.

---

## 2. Causal Context Contract

Every execution in `ReactionExecutionEngine` requires or instantiates a causal context:
```typescript
interface ReactionCausalContext {
  causationId: string;        // ID of the immediate causal parent (event or proposal)
  correlationId: string;      // Trace ID spanning the entire chain
  depth: number;              // Current recursion depth (0-indexed)
  visitedTriggerIds: string[]; // List of trigger IDs traversed along this causal path
}
```

---

## 3. Dual Protection Mechanisms

### A. Strict Depth Bounding (`maxDepth`)
- Configured default limit: `maxDepth = 3`.
- Evaluation Rule: If `causalContext.depth >= this.maxDepth`, execution is halted immediately:
  ```typescript
  if (depth >= this.maxDepth) {
    return this.recordFailure(
      proposal,
      'CHAIN_LIMIT',
      `Reaction depth limit exceeded (current: ${depth}, max: ${this.maxDepth})`,
      context
    );
  }
  ```
- Result Status: `CHAIN_LIMIT`.
- Journal Event: Emits `REACTION_CHAIN_LIMIT` with full causal ancestry.

### B. Cycle Detection (`visitedTriggerIds`)
- A trigger cannot appear more than once along an unbroken causal lineage.
- Evaluation Rule:
  ```typescript
  const occurrences = visitedTriggerIds.filter(id => id === proposal.triggerId).length;
  if (occurrences > 1 || (visitedTriggerIds.slice(0, -1).includes(proposal.triggerId))) {
    return this.recordFailure(
      proposal,
      'CHAIN_LIMIT',
      `Causal trigger cycle detected: trigger '${proposal.triggerId}' visited multiple times in causal path`,
      context
    );
  }
  ```
- Result Status: `CHAIN_LIMIT`.
- Journal Event: Emits `REACTION_CHAIN_LIMIT` and logs the cycle trail.

---

## 4. Concurrency Throttling

To prevent resource starvation from event floods:
- `activeExecutions`: Atomic tracking counter.
- `maxConcurrentReactions`: Default capped at 10.
- If `activeExecutions >= maxConcurrentReactions`, new executions return status `THROTTLED` and are queued or discarded based on trigger policy.

---

## 5. Journal Recording for Incident Response

Whenever a chain limit or cycle is triggered, `executionPersistence.appendJournalEvent()` commits an immutable audit record:
```json
{
  "type": "REACTION_CHAIN_LIMIT",
  "proposalId": "prop-loop-01",
  "triggerId": "trig-pingpong",
  "depth": 3,
  "visitedTriggerIds": ["trig-pingpong", "trig-pongping", "trig-pingpong"],
  "error": "Causal trigger cycle detected: trigger 'trig-pingpong' visited multiple times in causal path",
  "timestamp": 1790957500000
}
```

This guarantees operators complete visibility into misconfigured triggers without service degradation.

---

## 6. Test Suite Verification

Verified in `src/tests/EventReactionStage19.test.tsx`:
- Test 48: Verified causal context propagation (`causationId`, `correlationId`, `depth`, `visitedTriggerIds`).
- Test 49: Verified chain termination when depth exceeds `maxDepth` (`status: CHAIN_LIMIT`).
- Test 50: Verified immediate detection of cyclic trigger chains via `visitedTriggerIds`.
- Test 51: Verified emission of `REACTION_CHAIN_LIMIT` to the execution journal.
- Test 52: Verified failure audit trail preservation without recursive stack overflow.
