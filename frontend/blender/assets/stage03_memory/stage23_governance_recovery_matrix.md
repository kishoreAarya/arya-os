# ARYAOS V1 — STAGE 23: STAGE 21 GOVERNANCE RECOVERY MATRIX

**STATUS:** AUTHORITATIVE SPECIFICATION & MAPPING REFERENCE  
**STAGE:** STAGE 23 — RESILIENT AUTONOMOUS OPERATIONS & RECOVERY CONTROL  
**PHASE:** PHASE 10 — GOVERNED RECOVERY INTEGRATION & OPERATIONAL-TRUTH FEEDBACK  
**INTEGRATION BOUNDARY:** STAGE 21 GOVERNANCE CONTROL PLANE  

---

### 1. Executive Summary

This matrix specifies the integration of the Stage 23 Recovery Control Plane with the Stage 21 Governance Control Plane. Stage 21 evaluates the fail-closed authority intersection across all five governance tiers before any recovery action can proceed.

**The Five Governance Authority Boundaries**:
$$\text{Authority Intersection} = \text{Policy Decision} \cap \text{Connector Permissions} \cap \text{Action Authorization} \cap \text{Human Approval} \cap \text{Mission Constraints}$$

If ANY boundary fails to grant permission, the authority intersection fails closed.

---

### 2. Authority Intersection Mapping to Recovery Control Decisions

| Authority Intersection Status (`effectiveStatus`) | Stage 21 Governance Decision | Stage 23 Recovery Outcome | Recommended Action | Human Required | Primary Reason Code | Operational Handling |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **`GRANTED`** | `ALLOW` | `RETRY` / `RESUME` / `RECONCILE` | `RETRY` / `RESUME` / `RECONCILE` | `false` | `OPERATOR_APPROVAL_VERIFIED` / `GOVERNANCE_POLICY_ALLOWED` | All 5 authority tiers verified. Downstream safety engine evaluates execution eligibility. |
| **`REQUIRES_APPROVAL`** | `REQUIRE_APPROVAL` | `REQUIRE_APPROVAL` | `REQUIRE_APPROVAL` | `true` | `GOVERNANCE_APPROVAL_REQUIRED` | Human signoff missing for high-risk operation, compensation, or critical task. |
| **`MISSING_PERMISSION`** | `DENY` | `REQUIRE_APPROVAL` | `REQUIRE_APPROVAL` | `true` | `CONNECTOR_PERMISSION_MISSING` | Connector is unavailable, in error status, or lacks Stage 16 capability grant. Requires operator intervention. |
| **`MISSION_CONSTRAINT_BLOCKED`** | `PAUSE` | `PAUSE` | `PAUSE` | `true` | `MISSION_CONSTRAINT_BLOCKED` | Target mission is `PAUSED` or `CANCELLED`. Recovery operations paused to respect mission boundaries. |
| **`DENIED`** (Policy Deny) | `DENY` | `ABORT` | `ABORT` | `true` | `GOVERNANCE_POLICY_DENIED` | Active policy explicitly prohibits the recovery action. Execution terminated. |
| **`DENIED`** (Forged Token) | `DENY` | `ABORT` | `ABORT` | `true` | `GOVERNANCE_POLICY_DENIED` | Anti-spoofing rejection: non-human agent attempted to grant operator approval. |
| **`STALE`** | `REQUIRE_REVIEW` | `REQUIRE_APPROVAL` | `REQUIRE_APPROVAL` | `true` | `GOVERNANCE_STALE_OR_DRIFT` | Snapshot or approval token has exceeded TTL (>5m) or drifted. Fails closed. |

---

### 3. Anti-Spoofing & Human Operator Approval Token Verification

To prevent autonomous agents or compromised workers from assuming operator authority, Stage 23 coordinates with Stage 21 anti-spoofing defenses:

```mermaid
flowchart TD
    Token[Operator Approval Token] --> IdentityCheck{Approver Identity Check}
    IdentityCheck -- "Contains AGENT, DAEMON, SYSTEM, BOT" --> RejectSpoof[Status: FORGED_REJECTED<br>Outcome: ABORT]
    IdentityCheck -- "Human Operator Identity" --> TTLCheck{TTL Check<br>Date.now() - approvedAt > 5m}
    TTLCheck -- "Expired (>300,000ms)" --> ExpireToken[Status: STALE<br>Reason: APPROVAL_TOKEN_EXPIRED<br>Outcome: REQUIRE_APPROVAL]
    TTLCheck -- "Within TTL" --> ReqMatch{Request ID Match}
    ReqMatch -- "Mismatched" --> RejectReq[Status: FORGED_REJECTED<br>Reason: APPROVAL_TOKEN_REQUEST_MISMATCH<br>Outcome: REQUIRE_APPROVAL]
    ReqMatch -- "Matches" --> SnapMatch{Snapshot ID Match}
    SnapMatch -- "Mismatched" --> RejectSnap[Status: STALE<br>Reason: APPROVAL_TOKEN_SNAPSHOT_MISMATCH<br>Outcome: REQUIRE_APPROVAL]
    SnapMatch -- "Valid Snapshot" --> Approve[Status: GRANTED<br>Outcome: RETRY / RESUME<br>Reason: OPERATOR_APPROVAL_VERIFIED]
```

**Anti-Spoofing Rules Enforced**:
1. **Human Identity**: Tokens containing `AGENT`, `DAEMON`, `SYSTEM`, or `BOT` are rejected as forged.
2. **Signature Verification**: Signatures with `FORGED`, `FAKE`, or `INVALID` fail immediately to `DENY`/`ABORT`.
3. **Strict 5-Minute TTL**: Approvals older than 300,000ms are treated as expired and require re-authorization.
4. **Request Binding**: Token `requestId` must strictly match `request.requestId`.
5. **Snapshot Binding**: Token must be evaluated against the snapshot in effect at the time of approval.
