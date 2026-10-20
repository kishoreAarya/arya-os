# AryaOS V1 Stage 15 — Recovery & Reconciliation Model

## 1. The Distributed State Problem

When an external capability request is interrupted by a browser reload, process termination, network partition, or execution timeout, the exact state of the external world is inherently ambiguous:
* Did the HTTP POST reach the server?
* Was the GitHub issue created before the connection dropped?
* Did the filesystem write flush to disk?

Blindly retrying non-idempotent operations produces catastrophic side effects (e.g. duplicate issue filings, double billing, or corrupted files).

---

## 2. Action Reconciliation Architecture

AryaOS resolves this with the `ActionReconciliationService` (`src/services/actionReconciliationService.ts`):

```
       Network Timeout / Crash / Resume
                      │
                      ▼
           actionReconciliationService
                      │
        ┌─────────────┴─────────────┐
        ▼                           ▼
[Query Capability]          [Check Persistence]
Check if entity exists       Check persisted record
(e.g., read issue by title,
 verify file content)
        │                           │
        └─────────────┬─────────────┘
                      ▼
           State Discovered?
             /          \
           YES           NO
           /              \
         ▼                 ▼
 Mark SUCCEEDED       Can verify absence?
 (Avoid duplicate)         /        \
                         YES         NO
                         /            \
                       ▼               ▼
                 Safe to Retry    Mark STATE_UNKNOWN
                                  (Block auto-retry)
```

---

## 3. Idempotency Keys & De-duplication

* Every mutating ActionRequest is assigned an `idempotencyKey`.
* When an incoming request matches a cached key:
  1. The cached `ActionResult` is returned immediately.
  2. No duplicate adapter execution or external API request occurs.
  3. Provenance and audit records reflect the deduplication.

---

## 4. `STATE_UNKNOWN` Handling

When an action's side effect cannot be verified or queried through a neutral read operation, the Action Bus marks the result status as `STATE_UNKNOWN`.
* Automatic retries are immediately halted.
* The action is flagged for operator inspection or durable journal review.
* Preserves data integrity without risking uncontrolled cascading mutations.
