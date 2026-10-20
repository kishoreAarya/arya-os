/**
 * AryaOS V1 — Stage 21: Governance Explanation Service
 *
 * Produces structured, deterministic 10-point governance decision explanations.
 * Preserves Stage 14 epistemic certainty labels (OBSERVED, INFERRED, PROJECTED, UNKNOWN).
 * Guarantees explainability: no opaque "policy says no" responses.
 */

import {
  GovernanceRequest,
  GovernanceContext,
  PolicySnapshot,
  GovernanceDecisionType,
  AuthorityIntersectionResult,
  GovernanceExplanation,
  EpistemicStatus,
} from '../types/governanceControlPlane';

export class GovernanceExplanationService {
  /**
   * Generates a comprehensive 10-point governance explanation.
   */
  public generateExplanation(params: {
    request: GovernanceRequest;
    context: GovernanceContext;
    snapshot: PolicySnapshot;
    matchedPolicies: string[];
    conflictingPolicies: Array<{ conflictId: string; policyAId: string; policyBId: string; precedenceReason: string }>;
    precedenceResolution: string;
    resultingPolicyDecision: GovernanceDecisionType;
    authorityIntersection: AuthorityIntersectionResult;
    epistemicStatus?: EpistemicStatus;
  }): GovernanceExplanation {
    const {
      request,
      snapshot,
      matchedPolicies,
      conflictingPolicies,
      precedenceResolution,
      resultingPolicyDecision,
      authorityIntersection,
      epistemicStatus = 'OBSERVED',
    } = params;

    // 1. What was requested
    const targetDesc = request.capabilityId
      ? `capability '${request.capabilityId}'`
      : request.actionType
      ? `actionType '${request.actionType}'`
      : `operation on system '${request.targetSystem}'`;
    const whatWasRequested = `Actor '${request.actor.actorId}' (${request.actor.actorType}) requested execution of ${targetDesc}`;

    // 2. Which policy snapshot was used
    const snapshotUsed = `PolicySnapshot '${snapshot.snapshotId}' (Registry v${snapshot.registryVersion}, activePolicies: ${snapshot.activePolicyCount})`;

    // 3. Policies matched
    const policiesMatched = [...matchedPolicies];

    // 4. Conflicts
    const formattedConflicts = conflictingPolicies.map((c) => ({
      policyA: c.policyAId,
      policyB: c.policyBId,
      reason: c.precedenceReason,
    }));

    // 7. Authority required
    const authorityRequired = [...authorityIntersection.requiredAuthority];

    // 8. Human approval required
    const humanApprovalRequired = authorityIntersection.requiredAuthority.includes('HUMAN_OPERATOR_APPROVAL');

    // 9. Was approval present
    const approvalPresent = authorityIntersection.humanApprovalStatus === 'GRANTED';

    // 10. Executing or blocking boundary
    let executingOrBlockingBoundary: string;
    if (authorityIntersection.effectiveStatus === 'GRANTED') {
      executingOrBlockingBoundary = request.connectorId || request.capabilityId
        ? 'Stage 15 Universal Action Bus (outbound external execution)'
        : request.triggerId
        ? 'Stage 19 Reaction Execution Engine'
        : request.missionId
        ? 'Stage 12 Mission Manager'
        : 'Existing Application Runtime Boundary';
    } else {
      executingOrBlockingBoundary = `Blocked at Governance Control Plane (${authorityIntersection.blockingReasons.join('; ') || 'Denied by policy'})`;
    }

    return {
      whatWasRequested,
      snapshotUsed,
      policiesMatched,
      matchedPolicies: [...matchedPolicies],
      policiesConflicted: formattedConflicts,
      precedenceResolution,
      resultingPolicyDecision,
      authorityRequired,
      humanApprovalRequired,
      approvalPresent,
      executingOrBlockingBoundary,
      epistemicStatus,
      requestId: request.requestId,
      actor: request.actor,
      contextSummary: {
        actorId: request.actor.actorId,
        actorType: request.actor.actorType,
        riskLevel: request.riskLevel || 'LOW',
        scopeType: params.context.scopeType,
      },
      deterministicRationale: precedenceResolution || (matchedPolicies.length === 0 ? 'No active policies matched request scope; default allow' : 'Resolved by policy precedence'),
      policySnapshotId: snapshot.snapshotId,
      authorityTiers: {
        policyTier: { evaluated: true, allowed: authorityIntersection.policyAllowed, decision: resultingPolicyDecision },
        connectorTier: { required: authorityIntersection.requiredAuthority.includes('CONNECTOR_FABRIC_PERMISSION'), granted: authorityIntersection.connectorPermissionGranted },
        actionTier: { authorized: authorityIntersection.actionAuthorized },
        humanTier: { required: humanApprovalRequired, status: authorityIntersection.humanApprovalStatus },
        missionTier: { satisfied: authorityIntersection.missionConstraintsSatisfied },
      },
      humanApprovalCheck: {
        required: humanApprovalRequired,
        status: authorityIntersection.humanApprovalStatus,
        riskLevel: request.riskLevel || 'LOW',
      },
      stalenessEvaluation: {
        isStale: false,
        status: 'FRESH',
      },
      deterministicMetadata: {
        evaluationLatencyMs: 1,
        fingerprint: snapshot.fingerprint,
      },
    };
  }

  /**
   * Formats the 10-point explanation into a clean human-readable narrative string.
   */
  public formatNarrative(explanation: GovernanceExplanation): string {
    return [
      `1. REQUEST: ${explanation.whatWasRequested}`,
      `2. SNAPSHOT: ${explanation.snapshotUsed}`,
      `3. MATCHED POLICIES: ${explanation.policiesMatched.length > 0 ? explanation.policiesMatched.join(', ') : 'None'}`,
      `4. CONFLICTS: ${explanation.policiesConflicted.length > 0 ? `${explanation.policiesConflicted.length} detected` : 'None'}`,
      `5. PRECEDENCE: ${explanation.precedenceResolution}`,
      `6. DECISION: ${explanation.resultingPolicyDecision}`,
      `7. AUTHORITY REQUIRED: ${explanation.authorityRequired.join(' ∩ ')}`,
      `8. APPROVAL REQUIRED: ${explanation.humanApprovalRequired ? 'YES' : 'NO'}`,
      `9. APPROVAL PRESENT: ${explanation.approvalPresent ? 'YES' : 'NO'}`,
      `10. BOUNDARY: ${explanation.executingOrBlockingBoundary}`,
      `[EPISTEMIC CERTAINTY: ${explanation.epistemicStatus}]`,
    ].join('\n');
  }
}

export const governanceExplanationService = new GovernanceExplanationService();
