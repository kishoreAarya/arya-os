# ARYAOS V1 — STAGE 23 — PHASE 9
# STAGE 09 EXECUTION PERSISTENCE & CRASH RECOVERY INTEGRATION

**STATUS:** FROZEN ARCHITECTURAL SPECIFICATION  
**PRIMARY SUBSYSTEMS:**  
- Stage 09: [`ExecutionPersistence`](file:///Users/venkatakishorenasina/Documents/arya-os-v1/frontend/src/services/executionPersistence.ts), [`ExecutionJournal`](file:///Users/venkatakishorenasina/Documents/arya-os-v1/frontend/src/services/executionJournal.ts)  
- Stage 23: [`RecoveryControlPlane`](file:///Users/venkatakishorenasina/Documents/arya-os-v1/frontend/src/services/recoveryControlPlane.ts), [`RecoveryControlPersistenceService`](file:///Users/venkatakishorenasina/Documents/arya-os-v1/frontend/src/services/recoveryControlPersistenceService.ts)  

---

### 1. Architectural Integration Principles

Stage 23 enforces a strict non-duplication principle:
- **STAGE 09 OWNS PERSISTENCE & CRASH RECOVERY.**
- **STAGE 23 OWNS RECOVERY DECISION SEMANTICS.**
- **STAGE 22 OWNS OPERATIONAL TRUTH & CAUSAL AUDIT.**
- **STAGE 21 OWNS GOVERNANCE & AUTHORITY.**
- **STAGE 15 & 07 OWN EXECUTION TRANSPORT.**

Stage 23 does NOT create a second database, local storage store, journal, or crash recovery manager. Instead, it natively extends and delegates to Stage 09 primitives.

```
┌───────────────────────────────────────────────────────────┐
│              STAGE 23 RECOVERY CONTROL PLANE              │
│       (Decision surface, Precedence, Bounds Protection)    │
└─────────────────────────────┬─────────────────────────────┘
                              │ delegates persistence
                              ▼
┌───────────────────────────────────────────────────────────┐
│        STAGE 23 RECOVERY CONTROL PERSISTENCE SERVICE      │
│  (Sanitization, Revalidation, Lease Coordination, TTL)   │
└──────────────┬────────────────────────────┬───────────────┘
               │ saves envelope             │ appends events
               ▼                            ▼
┌─────────────────────────────┐  ┌──────────────────────────┐
│ STAGE 09 EXECUTION          │  │ STAGE 09 EXECUTION       │
│ PERSISTENCE                 │  │ JOURNAL                  │
│ (Envelope: recoveryDecisions│  │ (Events: RECOVERY_DECIDED│
│  requests, leases)          │  │  STALE, EXPIRED, LEASE)  │
└─────────────────────────────┘  └──────────────────────────┘
```

---

### 2. Envelope Schema Extensions

The Stage 09 root envelope (`PersistedOrchestrationEnvelope`) in [`src/types/executionPersistence.ts`](file:///Users/venkatakishorenasina/Documents/arya-os-v1/frontend/src/types/executionPersistence.ts) has been extended with Stage 23 namespaces:

```typescript
export interface PersistedOrchestrationEnvelope {
  // Existing Stage 09–22 fields...
  goals: Record<string, Goal>;
  missions?: Record<string, Mission>;
  governanceDecisions?: Record<string, GovernanceDecision>;
  auditEvents?: Record<string, OperationalAuditEvent>;

  // Stage 23 extensions
  recoveryControlDecisions?: Record<string, RecoveryControlDecision>;
  recoveryControlRequests?: Record<string, RecoveryControlRequest>;
  recoveryControlLeases?: Record<string, RecoveryControlLease>;
}
```

---

### 3. Event-Sourced Journal Integration

Stage 23 emits append-only, monotonically sequenced domain events to [`ExecutionJournal`](file:///Users/venkatakishorenasina/Documents/arya-os-v1/frontend/src/services/executionJournal.ts):

| Event Type | Trigger | Payload Contents |
| :--- | :--- | :--- |
| `RECOVERY_CONTROL_CREATED` | Request received & validated | `requestId`, `operationId`, `causationId` |
| `RECOVERY_CONTROL_CLASSIFIED`| Phase 2 classification finished | `classification`, `epistemicStatus` |
| `RECOVERY_CONTROL_ASSESSED` | Phase 4 safety & Phase 7 cascade completed | `duplicateRisk`, `containmentAction` |
| `RECOVERY_CONTROL_DECIDED` | Control decision finalized | `decisionId`, `recommendedAction`, `outcome` |
| `RECOVERY_CONTROL_STALE` | Authority drift detected on restart | `decisionId`, `reason`, `staleAuthority` |
| `RECOVERY_CONTROL_SUPERSEDED`| New decision replaces old record | `oldDecisionId`, `newDecisionId`, `reason` |
| `RECOVERY_CONTROL_EXPIRED` | Decision TTL elapsed during downtime | `decisionId`, `expiresAt`, `elapsedMs` |
| `RECOVERY_CONTROL_ESCALATED` | Bounds exhausted or human signoff needed | `decisionId`, `boundExhausted` |
| `LEASE_ACQUIRED` | Single-runtime execution lock granted | `leaseId`, `decisionId`, `workerId`, `expiresAt`|
| `LEASE_RELEASED` | Execution lock voluntarily surrendered | `leaseId`, `decisionId`, `workerId` |

---

### 4. Lease & Single-Runtime Execution Safety

To eliminate race conditions between multiple autonomous recovery workers or distributed tab processes:

1. **Atomic Acquisition**: [`acquireRecoveryLease`](file:///Users/venkatakishorenasina/Documents/arya-os-v1/frontend/src/services/recoveryControlPersistenceService.ts) checks active leases in the Stage 09 envelope.
2. **Conflict Detection**: If worker `beta` attempts to acquire a lease held by `alpha` where `now < expiresAt`, the request is denied with a `failureReason`.
3. **Automatic Expiry**: Leases feature a deterministic TTL (default: 30,000ms). Expired leases are evicted automatically upon subsequent queries.
4. **Clean Release**: Upon recovery completion or delegation, the lease is released and logged to the journal.

---

### 5. Persistence Security & Zero-Secret Guarantee

Before serializing any record into the Stage 09 storage envelope, [`RecoveryControlPersistenceService`](file:///Users/venkatakishorenasina/Documents/arya-os-v1/frontend/src/services/recoveryControlPersistenceService.ts) and [`ExecutionPersistence`](file:///Users/venkatakishorenasina/Documents/arya-os-v1/frontend/src/services/executionPersistence.ts) apply multi-layer defenses:

1. **Recursive Secret Scrubbing**:
   Scans all fields for `bearer`, `sk-`, `ghp_`, `apiKey`, `token`, `password`, `authorization`, `privateKey`. Prohibited credentials cause validation errors or are redacted to `[REDACTED_SECRET]`.
2. **Payload Size Bounds**:
   Max serialized payload size is capped at 64 KB (`MAX_PERSISTED_PAYLOAD_SIZE = 65536`). Oversized payloads are rejected to prevent storage quota exhaustion.
3. **Hostile Input & URL Rejection**:
   Arbitrary `http://` and `https://` URLs in parameters are rejected; external communications must use registered capability identifiers.
4. **Prototype Pollution Immunity**:
   Disallows `__proto__`, `constructor`, and `prototype` in metadata or parameters.
5. **Fail-Closed on Forged Authority**:
   Records claiming `approved: true` or `executed: true` without valid Stage 21 operator signatures (`actorType === 'USER'`) or Stage 22 empirical evidence are rejected on load.
