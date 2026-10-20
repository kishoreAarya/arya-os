# AryaOS V1 Stage 21 — Deterministic Governance Explainability & 10-Point Explanation

## 1. Overview

Governance decisions in AryaOS V1 are not black-box verdicts. Every evaluation generates a structured, transparent, and deterministic `GovernanceExplanation` contract.

No probabilistic natural language generation or LLM inference is employed. The explanation is constructed deterministically from evaluated rules, matched condition trees, authority intersection statuses, and policy provenance.

---

## 2. The 10-Point Explanation Structure

Every `GovernanceExplanation` includes the following 10 mandatory dimensions:

```typescript
export interface GovernanceExplanation {
  // 1. What was requested (request identity & action intent)
  whatWasRequested: string;

  // 2. Snapshot used (snapshot ID, version, fingerprint)
  snapshotUsed: string;

  // 3. Policies matched (IDs and versions of all matching active policies)
  policiesMatched: string[];

  // 4. Policies conflicted (competing policy pairs with rationale)
  policiesConflicted: Array<{ policyA: string; policyB: string; reason: string }>;

  // 5. Precedence resolution (category hierarchy and deterministic tie-breaker)
  precedenceResolution: string;

  // 6. Resulting policy decision (ALLOW, DENY, REQUIRE_APPROVAL, LIMIT, DEFER, PAUSE)
  resultingPolicyDecision: GovernanceDecisionType;

  // 7. Authority required (list of all 5 authority tiers required for execution)
  authorityRequired: string[];

  // 8. Human approval check (status, required flag, risk level, anti-spoofing)
  humanApprovalRequired: boolean;
  approvalPresent: boolean;

  // 9. Executing or blocking boundary (exact service enforcing or blocking)
  executingOrBlockingBoundary: string;

  // 10. Epistemic certainty status (OBSERVED, INFERRED, PROJECTED, UNKNOWN)
  epistemicStatus: EpistemicStatus;

  // Extended deterministic metadata
  requestId?: string;
  actor?: GovernanceActor;
  contextSummary?: Record<string, unknown>;
  deterministicRationale?: string;
  authorityTiers?: { ... };
  humanApprovalCheck?: { ... };
  stalenessEvaluation?: { ... };
  deterministicMetadata?: { evaluationLatencyMs: number; fingerprint: string };
}
```

---

## 3. Explanatory Narrative Generation

In addition to structured data fields, `GovernanceExplanationService.generateHumanReadableNarrative()` synthesizes an operator-facing summary string:
- Details the actor and target system.
- Explains why the decision was rendered (e.g. *"Governed by System Safety policy 'pol-safety-critical' overriding resource limits"*).
- Lists missing authorities and required remediation steps (e.g. *"Awaiting operator approval for CRITICAL capability"*).
- Specifies the exact boundary responsible for enforcing or executing the operation.

---

## 4. Epistemic Certainty Classification

- **`OBSERVED`**: Real-time evaluation against verified physical system state and concrete policies.
- **`INFERRED`**: Inferred context or permissions derived from role hierarchy.
- **`PROJECTED`**: Counterfactual evaluation during consequence simulation (Stage 14 integration).
- **`UNKNOWN`**: Incomplete context leading to conservative fail-closed denial.
