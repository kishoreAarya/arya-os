# AryaOS V1 Stage 19 — Durable Persistence, Crash Recovery & Replay Protection

## 1. Overview & Durable Execution Guarantee

The Event-Driven Reaction Engine integrates with Stage 09 Durable Execution Memory (`executionPersistence`) to ensure that triggers, pending proposals, and reaction results survive process crashes, reboots, and network partitions without duplicate side-effect execution.

---

## 2. Persistence Envelope Extensions

In `src/types/executionPersistence.ts`, the root `PersistenceEnvelope` is extended with Stage 19 collections:
```typescript
interface PersistenceEnvelope {
  // Existing Stage 09-18 collections...
  triggers: Record<string, Trigger>;
  reactionProposals: Record<string, ReactionProposal>;
  reactionResults: Record<string, ReactionExecutionResult>;
}
```

### Dedicated Persistence Operations
`src/services/executionPersistence.ts` provides transactional atomic persistence methods:
- `saveTrigger(trigger: Trigger)`: Stores trigger definition in envelope and emits journal event.
- `getTrigger(triggerId: string)`: Rehydrates trigger by ID.
- `getAllTriggers()`: Lists all saved triggers.
- `saveReactionProposal(proposal: ReactionProposal)`: Persists proposal state mutations.
- `getReactionProposal(proposalId: string)`: Retrieves proposal.
- `saveReactionResult(result: ReactionExecutionResult)`: Persists completed/failed reaction execution.
- `getReactionResult(proposalId: string)`: Retrieves cached execution result for idempotency checking.

---

## 3. Immutable Journal Events

Every trigger lifecycle event and reaction phase is committed to the append-only journal:

| Journal Event Type | Emitted When | Payload Metadata |
|---|---|---|
| `TRIGGER_REGISTERED` | New trigger added to catalog | `triggerId`, `name`, `version`, `riskLevel` |
| `TRIGGER_UPDATED` | Trigger status or filter modified | `triggerId`, `newVersion`, `status` |
| `TRIGGER_DEACTIVATED` | Trigger paused, disabled, or revoked | `triggerId`, `previousStatus`, `reason` |
| `TRIGGER_MATCHED` | Inbound event matches trigger filter/conditions | `triggerId`, `eventId`, `sourceSystem` |
| `REACTION_PROPOSED` | ReactionProposal record generated | `proposalId`, `triggerId`, `riskLevel`, `status` |
| `REACTION_AUTHORIZED` | Proposal authorized (auto or human) | `proposalId`, `approverId`, `approvalReason` |
| `REACTION_REJECTED` | Proposal rejected (human or scope violation) | `proposalId`, `rejectionReason` |
| `REACTION_EXECUTED` | Reaction completed via Action Bus / Mission | `proposalId`, `durationMs`, `actionBusResultId` |
| `REACTION_FAILED` | Reaction execution threw an error | `proposalId`, `error`, `durationMs` |
| `REACTION_CHAIN_LIMIT` | Depth limit or trigger cycle detected | `proposalId`, `triggerId`, `depth`, `visitedTriggerIds` |

---

## 4. Idempotency & Replay Protection

When external events are replayed (e.g. from webhook retries or recovery replay), the Reaction Engine prevents duplicate execution:

1. **Deterministic Idempotency Key**:
   Constructed from proposal ID or composite event hash:
   `idempotencyKey = proposal.reaction.idempotencyKeyTemplate || proposal.id;`
2. **Pre-Execution Check**:
   Before dispatching to the Action Bus or internal managers, `ReactionExecutionEngine` checks:
   ```typescript
   if (this.executedProposals.has(proposal.id)) {
     return this.executedProposals.get(proposal.id)!;
   }
   ```
3. **Persisted Result Rehydration**:
   On system reboot, `executedProposals` is rehydrated from `executionPersistence.getAllReactionResults()`. Any re-submitted proposal returns the previous result without invoking external systems.

---

## 5. Cold Restart Recovery Lifecycle

```
SYSTEM BOOT / RESTART
         │
         ▼
RELOAD PERSISTENCE ENVELOPE (executionPersistence.loadEnvelope())
         │
         ├── 1. Rehydrate Triggers ──► TriggerRegistry.registerTrigger(t)
         │      (Status, conditions, and filters restored)
         │
         ├── 2. Rehydrate Proposals ──► ReactionProposalService.setProposals()
         │      (AWAITING_APPROVAL proposals restored to operator queue)
         │
         └── 3. Rehydrate Results ──► ReactionExecutionEngine.setExecutedProposals()
                (Idempotency cache repopulated; duplicate executions prevented)
```

---

## 6. Test Suite Verification

Verified in `src/tests/EventReactionStage19.test.tsx`:
- Test 47: Enforces idempotency deduplication (repeated execution returns existing result without re-executing).
- Test 56: Verifies persistence saves triggers, proposals, and results in `executionPersistence`.
- Test 57: Verifies restart cleanly reloads triggers and proposals from disk/localStorage envelope.
