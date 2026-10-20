# ARYAOS V1 — STAGE 23: CONTROL PLANE ARCHITECTURE
## UNIFIED RECOVERY ORCHESTRATION, CROSS-STAGE INTEGRATION & GOVERNED BOUNDARIES

**STATUS:** FROZEN & RATIFIED ARCHITECTURAL CONTRACT  
**BOUNDARY:** STAGE 23 RECOVERY CONTROL PLANE (`RecoveryControlPlane`)  

---

### 1. Conceptual Architecture

The Stage 23 **Recovery Control Plane** serves as the authoritative, deterministic decision façade that unifies all resilient autonomous operations capabilities of AryaOS V1 without becoming a second execution engine.

```
                                  STAGE 22 OPERATIONAL TRUTH
                                              │
                                              ▼
                                    FAILURE CLASSIFICATION
                                     (Phase 2: 13 Classes)
                                              │
                                              ▼
                                   RECOVERY CONTROL PLANE
                                              │
                    ┌─────────────────────────┼─────────────────────────┐
                    │                         │                         │
                    ▼                         ▼                         ▼
             SAFETY ASSESSMENT         RECONCILIATION            CASCADE CONTROL
            (Phase 4: Side-Effects)   (Phase 5: Probes)      (Phase 7: Containment)
                    │                         │                         │
                    └─────────────────────────┼─────────────────────────┘
                                              │
                                              ▼
                                        RECOVERY PLAN
                                    (Phase 3: 11 Actions)
                                              │
                                ┌─────────────┴─────────────┐
                                │                           │
                                ▼                           ▼
                          COMPENSATION                   RECOVERY
                     (Phase 6: Reversals)          (Phase 1/3: Retries)
                                │                           │
                                └─────────────┬─────────────┘
                                              ▼
                                       STAGE 20 POLICY
                                              ▼
                                     STAGE 21 GOVERNANCE
                                              ▼
                                 EXISTING EXECUTION BOUNDARY
                                 (Stage 15 Bus / Stage 07 GW)
                                              ▼
                                    STAGE 22 VERIFICATION
                                              ▼
                                   UPDATED OPERATIONAL TRUTH
```

---

### 2. The Fail-Closed Principle

In autonomous systems, the fundamental invariant is:
> **Epistemic uncertainty must never be converted into ambient permission.**

1. **Unknown External State**:
   - If an operation was dispatched and external confirmation is absent, the system does not infer success or failure.
   - It issues `RECONCILE` (for standard operations) or `REQUIRE_APPROVAL` (for critical operations).
   - Re-dispatching mutations while external state is unknown is strictly prohibited.
2. **Ambiguous or Stale Governance**:
   - If `governanceContext.stale === true` or `governanceContext.unknown === true`, the control plane immediately enters `REQUIRE_APPROVAL`.
   - Local flags (e.g., `approved: true`) provided by unauthenticated callers or autonomous agents are aggressively rejected.
3. **Cascade Containment Dominance**:
   - When Stage 23 Phase 7 cascade containment issues `ABORT`, `PAUSE`, `ISOLATE`, or `ESCALATE`, the control plane CANNOT downgrade that control to `RETRY` or `RESUME`.

---

### 3. Cross-Stage Jurisdictional Separation

Stage 23 orchestrates recovery decision-making while strictly honoring the established ownership of earlier frozen stages:

| Stage | Domain Authority | Phase 8 Interaction Boundary |
| :--- | :--- | :--- |
| **Stage 09** | Plan & ActionNode Crash Recovery | Respects Stage 09 ownership of goal/plan execution; signals Stage 09 when retry budgets expire or throttles are mandated. |
| **Stage 12** | Mission Control & Multi-Agent Planning | Recommends `PAUSE` on mission cascades; defers mission replanning, arbitration, and checkpoint restoration to Stage 12. |
| **Stage 15** | External Action Bus Execution Boundary | Issues zero direct network calls (`fetch`, Axios, raw sockets); all execution directives pass through Stage 15 Action Bus. |
| **Stage 16** | Connector Permissions & Token Lifecycle | Coordinates connector quarantine (`ISOLATE`); never directly deletes or mutates OAuth/API credentials. |
| **Stage 19** | Reactive Triggers & Event Loops | Detects trigger recursion loops ($\text{depth} \ge 5$) and cycles; recommends `PAUSE` on trigger channels. |
| **Stage 20** | Policy Intelligence & Hierarchy | Enforces `POLICY_BLOCK` $\rightarrow$ `ABORT`; never mutates policy rules or manufactures policy exemptions. |
| **Stage 21** | Governance Control Plane | Gating authority for operator signoffs; enforces `actorType === 'USER'` for high-severity/destructive actions. |
| **Stage 22** | Operational Truth & Causal Audit Fabric | Consumes Stage 22 operational truth; preserves `rootOperationId`, `causationId`, and `correlationId` across all decisions. |

---

### 4. Bounded Recursion & Loop Protection

To ensure the control plane itself never enters an infinite recovery recursion loop:
1. **Recovery Depth Bounding**:
   `recoveryDepth >= MAX_RECOVERY_DEPTH` (3) immediately halts autonomous recovery and produces `ESCALATE`.
2. **Automatic Retry Bounding**:
   `retryCount >= MAX_AUTOMATIC_RETRIES` (2) immediately halts retries and produces `ESCALATE`.
3. **Reconciliation Probe Bounding**:
   `reconciliationAttempts >= MAX_RECONCILIATION_ATTEMPTS` (3) halts automated probing and produces `ESCALATE`.
4. **Cascade Depth Bounding**:
   `MAX_CASCADE_DEPTH = 5` and `MAX_CONCURRENT_AFFECTED_OPERATIONS = 50`.

---

### 5. Hostile Input & Security Defenses

The Recovery Control Plane enforces rigorous defense-in-depth:
- **Prototype Pollution Prevention**: Rejects payloads containing `__proto__`, `constructor`, or `prototype`.
- **Sensitive Credential Scrubbing**: Automatically rejects parameters containing `apiKey`, `password`, `token`, `secret`, `authorization`, or `privateKey`.
- **Arbitrary URL Parameter Rejection**: Rejects arbitrary `http://` or `https://` parameters; all external integrations must use pre-registered, authenticated capabilities.
- **Forged Human Approval Defense**: Enforces that approvals originate from verified human operators (`actorType === 'USER'`). Synthetically forged approvals from `SYSTEM` or `AUTONOMOUS_AGENT` are rejected with `RecoveryContractViolationError`.
- **Deep Immutability**: All decisions returned by `evaluateRecoveryControl()` are deep-frozen via `Object.freeze` (`deepFreeze()`).
