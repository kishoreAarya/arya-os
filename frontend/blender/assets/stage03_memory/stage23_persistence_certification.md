# Stage 23 — Persistence & Durability Certification

**Stage**: AryaOS V1 — Stage 23: Governed Recovery & Self-Healing Control Plane  
**Phase**: Phase 13: Final Certification, Full Regression & Stage Freeze  
**Status**: CERTIFIED & FROZEN  

---

## 1. Stage 09 Durable Persistence Architecture Integration

Stage 23 delegates durable storage and crash-recovery mechanics entirely to Stage 09 (`ExecutionPersistence` and `ExecutionJournal`).

```
┌─────────────────────────────────────────────────────────────┐
│                          Stage 23                           │
│              Recovery Control & Self-Healing Plane          │
└──────────────────────────────┬──────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────┐
│             RecoveryControlPersistenceService               │
│          (Schema validation, Sanitization, Freezing)        │
└──────────────────────────────┬──────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────┐
│                          Stage 09                           │
│        ExecutionPersistence  &  ExecutionJournal            │
│   (Atomic writes, CRC checks, Snapshotting, Crash Recovery) │
└──────────────────────────────┬──────────────────────────────┘
                               │
          ┌────────────────────┴────────────────────┐
          ▼                                         ▼
┌────────────────────┐                    ┌───────────────────┐
│  Durable Storage   │                    │ In-Memory Fallback│
│  (e.g. IndexedDB,  │                    │   (Safe In-Mem)   │
│   localStorage)    │                    │                   │
└────────────────────┘                    └───────────────────┘
```

---

## 2. In-Memory Fallback & Durability Honesty

In environments where durable browser storage (e.g. `localStorage` or `IndexedDB`) is unavailable, restricted, or throws an error:

1. **Explicit Durability Status**: `recoveryControlPersistenceService.isDurableStorage()` queries `executionPersistence.isDurableStorageActive()`.
2. **Honest Reporting**: When operating on in-memory fallback, `isDurableStorage()` returns `false`.
3. **No False Guarantees**: System telemetry explicitly notes that persisted records will not survive a full process termination or browser tab close if durable storage is inactive.
4. **Verified Test (Test 390)**: Validated that `recoveryControlPersistenceService.isDurableStorage()` accurately reflects the underlying Stage 09 storage status.

---

## 3. Cold-Restart Recovery Resumption Invariants

1. **State Preservation**: Persisted recovery states include `recoveryPlanId`, `originalOperationId`, `recoveryDepth`, `retryCount`, `reconciliationAttempts`, `cascadeDepth`, `policySnapshotId`, `causationId`, and `correlationId`.
2. **Zero In-Memory Trust**: Upon restart, persisted records are treated as untrusted external inputs. They must pass schema validation and authority revalidation before any recovery action is resumed.
3. **No Counter Resets**: Retry and reconciliation counters do NOT reset to 0 upon cold restart; the saved count is preserved, preventing infinite looping across restarts.
4. **Idempotency Continuity**: Saved `idempotencyKey` values are maintained across restarts to ensure upstream service boundaries de-duplicate replays.
