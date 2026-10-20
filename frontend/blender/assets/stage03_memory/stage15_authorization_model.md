# AryaOS V1 Stage 15 — Action Bus Authorization Model

## 1. Zero Trust & Defense in Depth

The Action Bus Authorization Service (`src/services/actionAuthorizationService.ts`) implements a layered security model:
1. **Default DENY**: In the absence of an explicit granted permission or policy allow-rule, execution is denied immediately.
2. **Capability Denylist**: Policies can explicitly blacklist capabilities regardless of granted permissions.
3. **Multi-Tier Risk Assessment**: Dynamically assesses risk from both the capability's baseline classification and runtime parameters (e.g. destructive commands, financial terms).
4. **Mandatory Human Signoff for CRITICAL Actions**: Operations classified as `CRITICAL` strictly require a valid human operator signature. Autonomous approvals (e.g., from `SYSTEM` or `AUTONOMOUS_AGENT`) are rejected unconditionally.
5. **Sandboxed Operational Boundaries**:
   * File access confined to strictly declared directory roots (`/workspace`, `/data`, `/tmp/sandbox`).
   * Path traversal (`../`, `..\`) rejected unconditionally.
   * Egress HTTP restricted to allowlisted target domains.
   * Version control interactions restricted to authorized GitHub repositories.
   * Payload size ceiling (default 10MB) to prevent buffer exhaustion.

---

## 2. Risk Matrix & Escalation Logic

```
+-----------+-------------------------+----------------------------------------------+
| Risk Tier | Human Approval Needed?  | Typical Operations                           |
+-----------+-------------------------+----------------------------------------------+
| LOW       | No                      | Read filesystem, web query, read GitHub issue|
| MEDIUM    | Conditional             | HTTP GET/POST, issue comment, send notice    |
| HIGH      | Yes (by policy)         | Write filesystem, update remote resource     |
| CRITICAL  | MANDATORY (Human Only)  | Delete file, financial payment, release/purge|
+-----------+-------------------------+----------------------------------------------+
```

### Dynamic Escalation Triggers:
* **Financial Keywords**: `credit`, `payment`, `billing`, `spend` $\to$ escalate to `CRITICAL`.
* **Destructive File Actions**: `delete_file`, `destroy`, `purge` $\to$ escalate to `CRITICAL`.
* **Publishing Actions**: `publish`, `release` $\to$ escalate to `CRITICAL`.

---

## 3. Human Operator Signoff Enforcement

```typescript
if (requiresHumanApproval) {
  if (!operatorApproval || !operatorApproval.approvedBy) {
    return {
      authorized: false,
      status: 'REQUIRES_APPROVAL',
      riskLevel: effectiveRiskLevel,
      requiresHumanApproval: true,
      reason: `Action requires explicit operator review (Risk: ${effectiveRiskLevel})`,
      grantedPermissions: capability.requiredPermissions,
    };
  }

  // Reject autonomous approval spoofing
  if (
    operatorApproval.approvedBy === 'SYSTEM' ||
    operatorApproval.approvedBy === 'AUTONOMOUS_AGENT'
  ) {
    return {
      authorized: false,
      status: 'DENIED',
      riskLevel: effectiveRiskLevel,
      requiresHumanApproval: true,
      reason: 'Autonomous approval is prohibited for CRITICAL risk actions',
      grantedPermissions: [],
    };
  }
}
```

---

## 4. Integration with Stage 14 Decisions

A Stage 14 decision approval (e.g., `decisionIntelligenceService.approveDecision()`) does **not** grant bypass authority to the Action Bus. Every downstream ActionRequest spawned from an approved strategic decision must still present valid permissions, satisfy sandbox constraints, and provide explicit human operator approval if the action itself is `CRITICAL`.
