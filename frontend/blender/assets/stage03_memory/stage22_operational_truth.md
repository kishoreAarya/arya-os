# AryaOS V1 Stage 22 — Operational Truth & Epistemic Reconciliation

## 1. Executive Summary

In distributed autonomous systems, an architectural failure occurs whenever intent is conflated with truth. A system that assumes an action succeeded simply because an HTTP request was dispatched or a command queued creates catastrophic divergence between internal state and physical reality.

Stage 22 formalizes the **Operational Truth Layer** of AryaOS V1, providing mathematically rigorous separation between:
1. **Intent State**: What the agent or user requested, planned, or commanded.
2. **Authority State**: What governance and permissions permitted.
3. **Dispatch State**: What was transmitted to the external connector fabric.
4. **Execution State**: What the downstream provider confirmed executing.
5. **Reconciled Reality**: What direct observation and cryptographic verification prove actually exists in the target environment.

---

## 2. Canonical Operational Lifecycle States

Stage 22 enforces a monotonic state machine across all operations:

```
[RECEIVED]
    │
    ▼
[VALIDATED]
    │
    ▼
[GOVERNED] ────────► [DENIED] (Terminal)
    │           └──► [PAUSED / DEFERRED]
    ▼
[AUTHORIZED]
    │
    ▼
[DISPATCHED]
    │
    ▼
[EXECUTING]
    │
    ├──────────────────────┬──────────────────────┐
    ▼                      ▼                      ▼
[SUCCEEDED]             [FAILED]               [UNKNOWN]
    │                      │                      │
    └──────────────────────┴──────────────────────┘
                           │
                           ▼
                     [RECONCILED] (Strictly Terminal)
```

### Transition Invariants
- **Forward Progress Only**: Terminal states (`SUCCEEDED`, `FAILED`, `UNKNOWN`, `DENIED`) cannot transition backward to intermediate states (`RECEIVED`, `VALIDATED`, `DISPATCHED`).
- **Reconciliation Invariant**: `RECONCILED` is strictly terminal. Once reality has been verified against intent, no subsequent state transitions are allowed.
- **Fail-Closed on Unknown**: If an external connector does not provide a definitive callback within the timeout window, the operation transitions to `UNKNOWN`. It is never promoted to `SUCCEEDED`.

---

## 3. Epistemic Status Hierarchy

Every operational audit record is tagged with an epistemic certainty level:

| Epistemic Status | Definition | Verification Requirement |
|---|---|---|
| **CONFIRMED** | Highest epistemic certainty. Cryptographically signed or independently attested state observation. | Valid HMAC, ed25519 signature, or multi-source matching. |
| **OBSERVED** | Directly witnessed by internal runtime telemetry or synchronous connector response. | Direct payload capture by Stage 15/16/18. |
| **INFERRED** | Deterministically deduced by rule engine or causal graph analysis. | Transparent predicate evaluation (no hallucination). |
| **PROJECTED** | Anticipated outcome derived from Stage 14/20 impact simulations. | Pre-execution hypothesis; strictly non-factual. |
| **UNKNOWN** | Epistemic status when evidence is absent, timed out, or unverified. | Default state under partial failure. |

### Anti-Upgrade Epistemic Firewall
Stage 22 prohibits autonomous epistemic upgrading:
- An `INFERRED` state cannot be promoted to `CONFIRMED` without cryptographic evidence.
- An unconfirmed dispatch cannot be upgraded from `UNKNOWN` to `SUCCEEDED`.
- An audit event can never upgrade an authority grant or create a permission.

---

## 4. Truth Reconciliation Engine

The `OperationalTruthService` compares intent state with observed state:

$$\text{Discrepancy} = \Delta(\text{IntentState}, \text{ObservedState})$$

$$\text{ReconciliationStatus} = \begin{cases} 
\text{MATCHED} & \text{if } \text{Discrepancy} = \emptyset \wedge \text{ExternalSuccess} = \text{true} \\
\text{MISMATCHED} & \text{if } \text{Discrepancy} \neq \emptyset \\
\text{UNVERIFIED} & \text{if } \text{ObservedState} = \emptyset \vee \text{Timeout}
\end{cases}$$

When discrepancies exist:
1. The operation transitions to `FAILED` with a `RECONCILIATION_FAILURE` boundary.
2. The discrepancy list is appended to the operational audit ledger.
3. Downstream memory and knowledge updates are halted until reconciliation is resolved.
