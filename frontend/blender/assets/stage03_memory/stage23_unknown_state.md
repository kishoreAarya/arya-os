# AryaOS V1 — Stage 23: Unknown External State & Safe Read-Only Reconciliation Control

**Status:** APPROVED & VERIFIED (Stage 23 Phase 5)  
**Baseline:** Stages 01–22 Frozen  
**Subsystem:** `RecoveryReconciliationService` (`src/services/recoveryReconciliationService.ts`)  
**Core Invariant:**  
> **"Reconciliation determines external state; it does NOT repeat the original side effect."**

---

## 1. The Unknown-State Model

In distributed systems and agentic autonomous operations, operational uncertainty is inevitable:
- A network socket drops mid-transmission.
- An upstream provider responds with an HTTP 504 Gateway Timeout.
- A client-side execution crash occurs after dispatching an external mutation.
- A process is cancelled while an Action Bus request is in flight.

### The Axiom of Operational Truth
$$\text{No Response} \neq \text{Failure} \qquad \text{Local Timeout} \neq \text{Remote Failure} \qquad \text{Dispatch} \neq \text{Execution}$$

When external confirmation is absent, the state is strictly **`UNKNOWN_EXTERNAL_STATE`** with epistemic certainty **`UNKNOWN`**. The system must never convert uncertainty into synthetic failure or assumed success.

---

## 2. The Reconciliation-First Rule

Under no circumstances may the system perform a blind retry on an operation in `UNKNOWN_EXTERNAL_STATE`:

$$\textbf{UNKNOWN\_EXTERNAL\_STATE} \implies \textbf{RECONCILE} \quad (\text{NEVER BLIND RETRY})$$

Reconciliation is the safe epistemic bridge that queries remote state before any corrective action (retry, resume, compensate, or abort) is authorized.

---

## 3. Read-Only Probe Definition

A critical distinction separates the original operation from its reconciliation probe:

| Context | Original Consequential Operation | Safe Reconciliation Probe |
| :--- | :--- | :--- |
| **Filesystem** | `filesystem.write` (Mutates disk) | `filesystem.stat` / `filesystem.read` (Verifies presence & checksum) |
| **GitHub** | `github.create_issue` (Creates issue) | `github.issue_read` (Queries issue by title & metadata) |
| **Deployment** | `deploy.start` (Triggers production rollout) | `deploy.status` (Reads pipeline execution status) |
| **AI Provider** | `provider.generate` (Consumes budget/tokens) | `executionGateway.getCompletedExecution` (Queries execution journal) |

### Strict Invariant: Zero Mutation Replay
Reconciliation must be **strictly read-only** (`isReadOnly: true`). It must **NEVER** "test" whether an operation succeeded by attempting the mutation again. If a capability cannot provide a safe read-only status inquiry, reconciliation is marked `RECONCILIATION_UNAVAILABLE`.

---

## 4. Reconciliation Lifecycle

```
    REQUIRED (Triggered by Safety Assessment in Phase 4)
       │
       ▼
    PLANNED (Formulated by RecoveryReconciliationService)
       │
       ▼
    GOVERNED (Stage 21 Authority Verification)
       │
       ▼
    READY (Pre-flight checks passed; probe parameters verified)
       │
       ▼
    PROBED (Dispatched across Stage 15 Action Bus / Stage 07 Gateway)
       │
       ▼
    VERIFIED (Authoritative result recorded in Stage 22 Operational Truth)
```

---

## 5. Result Mapping & Epistemic Status

Every probe response maps deterministically to an immutable `ReconciliationResultRecord`:

| Probe Finding | Outcome | Epistemic Status | Operational Action |
| :--- | :--- | :--- | :--- |
| Remote resource exists & side-effect confirmed | `VERIFIED_SUCCESS` | `CONFIRMED` | Resolves original operation as successful; suppresses retry. |
| Remote resource confirmed absent (e.g. 404) | `VERIFIED_FAILURE` | `OBSERVED` | Confirms side-effect never occurred; safe for retry if idempotent. |
| Remote status indeterminate / unreachable | `STILL_UNKNOWN` | `UNKNOWN` | Uncertainty preserved; hold or escalate. |
| No read-only probe capability exists | `RECONCILIATION_UNAVAILABLE` | `UNKNOWN` | Mutation replay blocked; requires human intervention. |
| Probe rejected by authorization / permissions | `REJECTED` | `UNKNOWN` | Permission boundary respected; halts probe. |
| Probe exceeds finite attempt limit (3 attempts) | `EXPIRED` | `UNKNOWN` | Halts continuous polling; escalates to operator review. |
| Probe execution throws internal socket/network error | `FAILED` | `UNKNOWN` | **Probe failed $\neq$ Original operation failed.** Original status remains `UNKNOWN`. |

---

## 6. Architectural Boundary Enforcement

### 6.1 Stage 15 Universal Action Bus Boundary
All external capability reconciliation queries must execute through the Stage 15 Action Bus:
- No direct connector transport or HTTP calls.
- Preserves capability sandboxing, action auditing, and parameter normalization.

### 6.2 Stage 07 Execution Gateway Boundary
All provider, model, and reasoning reconciliation must query Stage 07 `executionGateway`:
- Queries the execution journal and idempotency cache via `getCompletedExecution()`.
- Zero direct provider SDK invocations.

### 6.3 Stage 16 Connector Permission Boundary
Reconciliation probes are subject to connector permission scopes. A read probe cannot execute if connector access has been revoked or expired.

### 6.4 Stage 21 Governance Boundary
Read-only probes still require Stage 21 governance authority. The service never fabricates approval or decision tokens.

---

## 7. Attempt Limits & Anti-Loop Safeguards

To prevent infinite polling or resource starvation:
- `MAX_RECONCILIATION_ATTEMPTS = 3`
- If a probe returns indeterminate results across 3 attempts, the request transitions to `EXPIRED`.
- The system terminates automated probing and surfaces an explicit operator signoff requirement.

---

## 8. Epistemic Integrity: Failed-Probe Semantics

A paramount architectural principle:

$$\textbf{Probe Failure} \neq \textbf{Original Operation Failure}$$

If a network glitch causes the reconciliation probe itself to throw an exception, **the original operation must not be marked failed**. The original operation's state remains strictly `UNKNOWN`.

---

## 9. Security & Anti-Abuse Controls

1. **No Arbitrary HTTP URLs**:
   The service strictly rejects raw URLs (`https://...` or `http://...`). Any attempt to pass an unrestricted URL triggers `RecoveryContractViolationError`.
2. **Untrusted Payload Defense**:
   Untrusted client or HUD metadata claiming `verified: true` or `externalSuccess: true` is ignored. Only authoritative probes through Stage 15/07 are accepted.
3. **Secret Hygiene**:
   Probe parameters are sanitized; credentials, tokens, and API keys are rejected.
4. **Prototype Pollution Protection**:
   All metadata and parameters are validated against prototype pollution attacks (`__proto__`, `constructor`, `prototype`).
5. **Causal Trace Preservation**:
   - `causationId`: Directly links to `originalOperationId`.
   - `correlationId`: Preserves the global trace chain.
   - `reconciliationId`: Strictly distinct from the original operation ID.
