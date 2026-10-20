# Stage 18: External State Reconciliation & Epistemic Boundaries

## 1. The Core Principle: EVENT ≠ TRUTH
An external webhook is an unverified, external claim. A compromised external actor, man-in-the-middle, or stale queue could deliver an event describing an action that did not happen or a resource that does not exist.

Therefore:
- Inbound events enter AryaOS with `epistemicStatus: 'OBSERVED'`.
- Only events verified by active read-back or constrained path verification can be promoted to `'CONFIRMED'`.
- Unreachable, ambiguous, or unverifiable claims remain strictly `'OBSERVED'` or `'STATE_UNKNOWN'`.

## 2. Read-Back Verification Flow
`externalStateReconciliationService.ts` performs active reconciliation by delegating to Stage 15 Universal Action Bus:

```
Normalized Event Arrives (epistemicStatus: OBSERVED)
               ↓
Is read-back verification capability available?
   ├── YES (e.g., github.issue_read)
   │     ↓
   │   Dispatch read action via ActionBus
   │     ↓
   │   Does external state match payload?
   │     ├── MATCH: Status -> CONFIRMED, Confidence -> 0.90
   │     └── MISMATCH / FAILED: Status -> OBSERVED, Confidence -> 0.60
   └── NO
         ↓
       Path boundary check (e.g. traversal guard)
         ├── Traversals detected (../): Status -> FAILED, Discrepancy logged
         └── Valid path: Status -> CONFIRMED (Scoped sandbox)
```

## 3. Epistemic Status Definitions
| Status | Meaning | Knowledge Graph Confidence |
| :--- | :--- | :--- |
| `OBSERVED` | Event received and authenticated, but not confirmed by independent query | 0.60 |
| `CONFIRMED` | Event confirmed through direct Action Bus read-back or sandboxed verification | 0.90 |
| `CONTRADICTED` | Observed event differs from actual remote state | 0.20 |
| `STATE_UNKNOWN`| Resource target does not exist or read verification failed | 0.30 |
| `FAILED` | Event targets illegal paths or attempts directory traversal | 0.00 |
