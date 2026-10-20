# AryaOS V1 Stage 19 — Multi-Tier Authorization Model & Human Approval Boundary

## 1. Overview & Defense-in-Depth

Stage 19 establishes a rigorous multi-tier authorization model ensuring that no trigger, incoming event, or internal agent can autonomously execute privileged operations without explicit, verified authority.

```
Incoming Event (Stage 18)
          │
          ▼
1. TRIGGER REGISTRATION AUTHORITY
   • Must be registered in TriggerRegistry (Status: ACTIVE)
   • Sensitive fields scrubbed ([REDACTED])
          │
          ▼
2. CONNECTOR PERMISSION BOUNDARY (Stage 16)
   • connectorRegistry: Connector must be registered & ACTIVE
   • connectorPermissionService: Required scopes verified
          │
          ▼
3. RISK-BASED GATING (Stage 19)
   • LOW: Auto-authorized
   • HIGH / CRITICAL: Gated in AWAITING_APPROVAL
          │
          ▼
4. HUMAN OPERATOR SIGN-OFF
   • Authorized Human Operator (user-*) ONLY
   • Autonomous Agent (AUTONOMOUS_AGENT-*) REJECTED
   • System Daemons (SYSTEM-*) REJECTED
          │
          ▼
5. ACTION BUS BOUNDARY (Stage 15)
   • Sole external gateway: actionBusService.execute()
   • Pre-dispatch validation & credential injection
```

---

## 2. Prohibition of Autonomous Privilege Escalation

A critical vulnerability in event-driven systems is "agent self-approval" where an LLM agent or background cron loop approves its own triggered proposals. Stage 19 enforces a hard code-level check in `ReactionProposalService.grantApproval()`:

```typescript
grantApproval(
  proposalId: string,
  approverId: string,
  reason: string
): ReactionProposal {
  const proposal = this.proposals.get(proposalId);
  if (!proposal) throw new Error(`Proposal '${proposalId}' not found`);

  // Strictly disallow autonomous agents or system accounts from approving
  if (approverId.startsWith('AUTONOMOUS_AGENT') || approverId.startsWith('SYSTEM')) {
    throw new Error(
      `Security Violation: Approver '${approverId}' is not authorized. ` +
      `Only verified human operators can approve consequential reaction proposals.`
    );
  }

  proposal.status = 'AUTHORIZED';
  proposal.approvalMetadata = {
    approvedBy: approverId,
    approvedAt: Date.now(),
    approvalReason: reason
  };
  return proposal;
}
```

### Invariant Proof
- In test 38, approval attempted with `approverId: 'AUTONOMOUS_AGENT_007'` threw `Security Violation: Approver 'AUTONOMOUS_AGENT_007' is not authorized`.
- In test 39, approval attempted with `approverId: 'SYSTEM_DAEMON'` threw `Security Violation: Approver 'SYSTEM_DAEMON' is not authorized`.
- In test 36, approval by `approverId: 'user-operator-kishore'` succeeded and promoted proposal status to `AUTHORIZED`.

---

## 3. Connector Fabric Scope Verification

Every reaction proposal targeting an external connector must prove active permission via Stage 16 Connector Fabric.

```typescript
if (trigger.targetConnectorId && trigger.requiredScopes && trigger.requiredScopes.length > 0) {
  const isAuthorized = connectorPermissionService.hasPermission(
    trigger.targetConnectorId,
    trigger.reaction.actionCapability || 'EXECUTE',
    trigger.requiredScopes
  );

  if (!isAuthorized) {
    proposal.status = 'REJECTED';
    proposal.rejectionReason = `Target connector '${trigger.targetConnectorId}' lacks required scopes: ${trigger.requiredScopes.join(', ')}`;
    return proposal;
  }
}
```

If the connector has been revoked, disabled, expired, or lacks the necessary scopes, the proposal is rejected before reaching any execution queue.

---

## 4. Test Suite Verification

Verified in `src/tests/EventReactionStage19.test.tsx`:
- Test 36: Human operator approval successfully grants authorization.
- Test 37: Human operator rejection marks proposal `REJECTED`.
- Test 38: Autonomous agent approval is strictly rejected with a security exception.
- Test 39: System daemon approval is strictly rejected with a security exception.
- Test 40: Connector scope checks reject proposals when scopes are insufficient.
- Tests 44–45: Execution engine blocks execution of unapproved or rejected proposals.
