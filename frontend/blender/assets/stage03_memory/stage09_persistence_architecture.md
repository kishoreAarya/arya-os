# ARYAOS V1 — STAGE 09: PERSISTENCE ARCHITECTURE

## 1. Executive Summary & Design Principles

Stage 09 implements the **Persistent Autonomous Operations & Recovery Layer** for AryaOS V1. Prior to Stage 09, closed-loop goal execution (Stage 08) operated strictly within transient in-memory runtime state: a browser refresh, process crash, or network interruption would lose active execution graphs, pending approvals, and scheduled tasks.

Stage 09 establishes a durable, crash-resilient persistence layer founded on four core principles:

1. **Clean Separation of Concerns**: Intelligent goal orchestration persistence (`executionPersistence.ts`) is completely isolated from timeline/shot production persistence (`projectPersistence.ts`). No duplication or schema bleed exists.
2. **Deterministic Durability**: All goal definitions, action dependency graphs (DAGs), observation feeds, human approvals, and operational telemetry are persisted through versioned envelopes (`CURRENT_ORCHESTRATION_SCHEMA_VERSION = 1`).
3. **Zero Secret Leakage**: Strict, recursive scrubbing intercepts all sensitive credentials (`sk-...`, Bearer tokens, private keys) before any record reaches storage, memory fallbacks, or journals.
4. **Resilient Fallback Hierarchy**: Storage gracefully degrades from primary localStorage to an in-memory cache if quota limits are exceeded or storage is restricted, emitting telemetry rather than throwing unhandled exceptions.

```
       ┌────────────────────────────────────────────────────────┐
       │                AryaOS Goal Orchestrator                │
       └───────┬──────────────────────┬──────────────────┬──────┘
               │                      │                  │
               ▼                      ▼                  ▼
       ┌───────────────┐      ┌───────────────┐  ┌───────────────┐
       │   Execution   │      │   Execution   │  │   Recovery    │
       │  Persistence  │      │    Journal    │  │    Manager    │
       └───────┬───────┘      └───────┬───────┘  └───────┬───────┘
               │                      │                  │
               ▼                      ▼                  ▼
    ┌─────────────────────┐  ┌─────────────────┐ ┌───────────────┐
    │ Versioned Envelopes │  │ Append-Only Log │ │ DAG Frontier  │
    │  - Goals            │  │  - Monotonic Seq│ │  Resolution & │
    │  - Action DAGs      │  │  - 22 Event     │ │  Idempotency  │
    │  - Approvals        │  │    Types        │ │  Cache        │
    │  - Scrubbed Secrets │  │  - Scrubbed     │ │  Verification │
    └─────────────────────┘  └─────────────────┘ └───────────────┘
```

---

## 2. Envelope Schema & Versioning

All persisted records are enclosed in a strictly typed `PersistedOrchestrationEnvelope<T>`:

```typescript
export interface PersistedOrchestrationEnvelope<T> {
  schemaVersion: number;       // Currently 1
  id: string;                  // Unique entity identifier
  entityType: 'GOAL' | 'ACTION_GRAPH' | 'OBSERVATION' | 'APPROVAL' | 'TELEMETRY' | 'RECOVERY_STATE';
  timestamp: string;           // ISO 8601 creation time
  lastUpdated: string;         // ISO 8601 last modification time
  data: T;                     // Scrubbed payload
  checksum?: string;           // Checksum for payload integrity
}
```

### Forward Compatibility & Migrations
- Schema version 1 sets the baseline.
- Future versions must supply migration functions (`migrateEnvelope(envelope)`) that sequentially advance data payloads without data loss.
- Deserialization rejects unsupported future schema versions to prevent corrupting state.

---

## 3. Storage Hierarchy & Quota Management

`executionPersistence` provides transparent fallback:
1. **Primary**: Synchronous, browser-managed Web Storage API (`localStorage`), scoped under namespaced keys:
   - `aryaos_v1_orchestration_goals`
   - `aryaos_v1_orchestration_approvals`
   - `aryaos_v1_orchestration_telemetry`
2. **Quota Handling**: If `QuotaExceededError` is trapped during `setItem`:
   - An operational telemetry warning event is emitted.
   - The payload is retained in an in-memory replica so active runtime operations continue without crash.
   - Non-critical telemetry entries are pruned using FIFO eviction.

---

## 4. Zero-Knowledge Secret Scrubbing

To prevent accidental persistence of API keys, bearer tokens, or provider credentials:
- `sanitizeForPersistence<T>(obj: T): T` recursively traverses objects and arrays.
- String values matching known secret formats (`sk-`, `Bearer `, `ey...`, passwords, API tokens) or keys matching sensitive regex patterns (`key`, `secret`, `token`, `auth`, `credential`, `password`) are masked to `[REDACTED_SECRET]`.
- All writes to `executionPersistence` and `executionJournal` pass through this sanitizer before encoding.

---

## 5. Gateway Conformance

Persistence operations never invoke AI provider endpoints directly. All execution flows remain strictly mediated through Stage 07's `executionGateway.execute()`. Completed executions recorded in the gateway's idempotency store are queried by `recoveryManager` during boot recovery to avoid redundant provider invocations.
