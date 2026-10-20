/**
 * AryaOS V1 — Stage 23: Evidence-Based Failure Classification Service
 *
 * Converts verified operational evidence into exactly one deterministic FailureClassification.
 * Enforces deterministic precedence, epistemic safety, dispatch-state boundaries,
 * bounded reason codes, prototype pollution protection, and deep immutability.
 *
 * IMPORTANT: Pure classification only. Zero RecoveryAction routing, zero execution.
 */

import {
  FailureClassification,
  FailureReasonCode,
  ClassificationEvidence,
  ClassificationResult,
} from '../types/recoveryControl';
import {
  deepFreeze,
  validateAndSanitizePayload,
  RecoveryContractViolationError,
} from './recoveryControl';

export class FailureClassificationService {
  /**
   * Deterministically classifies verified operational evidence into a single FailureClassification.
   * Pure decision function over structured evidence with 0 side effects and 0 LLM tokens.
   */
  public classifyFailure(rawEvidence: ClassificationEvidence): Readonly<ClassificationResult> {
    // 1. Structural & Causal Integrity Check
    if (!rawEvidence.operationId || typeof rawEvidence.operationId !== 'string' || rawEvidence.operationId.trim() === '') {
      throw new RecoveryContractViolationError('operationId is mandatory in classification evidence');
    }
    if (!rawEvidence.causationId || typeof rawEvidence.causationId !== 'string' || rawEvidence.causationId.trim() === '') {
      throw new RecoveryContractViolationError('causationId is mandatory in classification evidence');
    }
    if (!rawEvidence.correlationId || typeof rawEvidence.correlationId !== 'string' || rawEvidence.correlationId.trim() === '') {
      throw new RecoveryContractViolationError('correlationId is mandatory in classification evidence');
    }
    if (!rawEvidence.dispatchState || typeof rawEvidence.dispatchState !== 'string') {
      throw new RecoveryContractViolationError('dispatchState is mandatory in classification evidence');
    }

    // 2. Input Sanitization & Security Defenses
    const sanitizedEvidence: ClassificationEvidence = {
      ...rawEvidence,
      metadata: rawEvidence.metadata ? validateAndSanitizePayload(rawEvidence.metadata) : undefined,
    };

    // 3. Deterministic Precedence Evaluation
    const { classification, reasonCode, explanation, epistemicStatus } = this.evaluateEvidence(sanitizedEvidence);

    const result: ClassificationResult = {
      classification,
      reasonCode,
      epistemicStatus,
      explanation,
      evidenceReferences: Object.freeze([...(sanitizedEvidence.evidenceReferences || [])]),
      causationId: sanitizedEvidence.causationId,
      correlationId: sanitizedEvidence.correlationId,
      classifiedAt: Date.now(),
      metadata: sanitizedEvidence.metadata ? Object.freeze(sanitizedEvidence.metadata) : undefined,
    };

    return deepFreeze(result);
  }

  /**
   * Evaluates structured evidence strictly adhering to the 13-tier deterministic precedence.
   */
  private evaluateEvidence(evidence: ClassificationEvidence): {
    classification: FailureClassification;
    reasonCode: FailureReasonCode;
    explanation: string;
    epistemicStatus: string;
  } {
    const defaultEpistemic = evidence.epistemicStatus || 'OBSERVED';

    // ------------------------------------------------------------------------
    // TIER 1: PARTIAL_EXECUTION
    // Workflow where one or more steps completed before a subsequent step failed.
    // ------------------------------------------------------------------------
    if (
      evidence.partialExecutionEvidence &&
      Array.isArray(evidence.partialExecutionEvidence.completedSteps) &&
      evidence.partialExecutionEvidence.completedSteps.length > 0 &&
      (evidence.partialExecutionEvidence.failedStep || (evidence.partialExecutionEvidence.pendingSteps && evidence.partialExecutionEvidence.pendingSteps.length > 0))
    ) {
      const completed = evidence.partialExecutionEvidence.completedSteps.join(', ');
      const failed = evidence.partialExecutionEvidence.failedStep || 'unknown_step';
      return {
        classification: 'PARTIAL_EXECUTION',
        reasonCode: 'PARTIAL_WORKFLOW_COMPLETION',
        explanation: `Partial workflow execution detected: completed [${completed}], failed at '${failed}'. Completed side-effects must be preserved.`,
        epistemicStatus: defaultEpistemic,
      };
    }

    // ------------------------------------------------------------------------
    // TIER 2: UNKNOWN_EXTERNAL_STATE
    // Dispatched to external system but external confirmation is absent, timed out,
    // or epistemic certainty is strictly UNKNOWN.
    // ------------------------------------------------------------------------
    const isPostDispatch =
      evidence.dispatchState === 'DISPATCHED' ||
      evidence.dispatchState === 'EXECUTING' ||
      evidence.dispatchState === 'EXTERNAL_CONFIRMATION_ABSENT';

    // Adversarial rule A & G: Client claims success or timeout, but external confirmation is unverified
    const hasVerifiedReconciliation =
      evidence.reconciliationEvidence?.attempted === true &&
      evidence.reconciliationEvidence?.matched === true;

    if (
      (isPostDispatch && evidence.dispatchState === 'EXTERNAL_CONFIRMATION_ABSENT') ||
      (isPostDispatch && evidence.epistemicStatus === 'UNKNOWN') ||
      (isPostDispatch && evidence.timeoutEvidence?.timedOut === true && !hasVerifiedReconciliation) ||
      (isPostDispatch && evidence.httpStatus === 500)
    ) {
      return {
        classification: 'UNKNOWN_EXTERNAL_STATE',
        reasonCode: 'EXTERNAL_CONFIRMATION_ABSENT',
        explanation: `Action was dispatched to external system but confirmation is absent or timed out (dispatchState: ${evidence.dispatchState}, epistemicStatus: ${evidence.epistemicStatus || 'UNKNOWN'}). Status unconfirmed.`,
        epistemicStatus: 'UNKNOWN',
      };
    }

    // ------------------------------------------------------------------------
    // TIER 3: RECONCILIATION
    // Target environment was observed but does not match expected intent.
    // ------------------------------------------------------------------------
    if (
      evidence.dispatchState === 'RECONCILIATION_FAILED' ||
      (evidence.reconciliationEvidence?.attempted === true && evidence.reconciliationEvidence?.matched === false)
    ) {
      const disc = evidence.reconciliationEvidence?.discrepancies?.join('; ') || 'Observed reality contradicts expected intent';
      return {
        classification: 'RECONCILIATION',
        reasonCode: 'RECONCILIATION_FAILED',
        explanation: `Reconciliation failure: ${disc}. State drift detected.`,
        epistemicStatus: defaultEpistemic,
      };
    }

    // ------------------------------------------------------------------------
    // TIER 4: PERMISSION
    // Connector credentials revoked, token expired, or connector scope missing in Stage 16.
    // ------------------------------------------------------------------------
    if (
      evidence.permissionResult?.revoked === true ||
      evidence.connectorStatus === 'REVOKED' ||
      evidence.permissionResult?.granted === false
    ) {
      return {
        classification: 'PERMISSION',
        reasonCode: 'CONNECTOR_PERMISSION_REVOKED',
        explanation: `Connector permission revoked or missing: ${evidence.permissionResult?.reason || 'Access denied by Stage 16 Connector Fabric'}.`,
        epistemicStatus: defaultEpistemic,
      };
    }

    // ------------------------------------------------------------------------
    // TIER 5: AUTHORIZATION
    // Capability authorization denied in Stage 15 / 21 authority intersection.
    // ------------------------------------------------------------------------
    if (evidence.authorizationResult && evidence.authorizationResult.authorized === false) {
      return {
        classification: 'AUTHORIZATION',
        reasonCode: 'AUTHORIZATION_DENIED',
        explanation: `Action authorization denied: ${evidence.authorizationResult.reason || 'Agent capability grant missing'}.`,
        epistemicStatus: defaultEpistemic,
      };
    }

    // ------------------------------------------------------------------------
    // TIER 6: POLICY
    // Stage 20/21 policy evaluation returned explicit DENY.
    // ------------------------------------------------------------------------
    if (evidence.policyResult && evidence.policyResult.decision === 'DENY') {
      return {
        classification: 'POLICY',
        reasonCode: 'POLICY_DENIED',
        explanation: `Operation denied by policy rule '${evidence.policyResult.matchedPolicyId || 'unspecified'}': ${evidence.policyResult.reason || 'Safety/Security constraint violated'}.`,
        epistemicStatus: defaultEpistemic,
      };
    }

    // ------------------------------------------------------------------------
    // TIER 7: STALE_STATE
    // Stale policy snapshot, expired TTL, or invalidated approval signature.
    // ------------------------------------------------------------------------
    if (evidence.staleStateEvidence && evidence.staleStateEvidence.isStale === true) {
      return {
        classification: 'STALE_STATE',
        reasonCode: 'STALE_AUTHORITY',
        explanation: `Stale state detected: ${evidence.staleStateEvidence.reason || 'Policy snapshot or approval signature has expired'}.`,
        epistemicStatus: defaultEpistemic,
      };
    }

    // ------------------------------------------------------------------------
    // TIER 8: RESOURCE
    // System quota exhausted, rate limit reached, memory/disk bound.
    // ------------------------------------------------------------------------
    if (
      evidence.resourceExhaustionEvidence?.exhausted === true ||
      evidence.providerErrorCategory === 'RATE_LIMIT' ||
      evidence.httpStatus === 429
    ) {
      return {
        classification: 'RESOURCE',
        reasonCode: 'RESOURCE_EXHAUSTED',
        explanation: `Resource exhaustion: ${evidence.resourceExhaustionEvidence?.resourceType || 'Rate limit or resource quota exceeded'}.`,
        epistemicStatus: defaultEpistemic,
      };
    }

    // ------------------------------------------------------------------------
    // TIER 9: DEPENDENCY
    // Upstream prerequisite task failed, missing input dependency.
    // ------------------------------------------------------------------------
    if (
      evidence.dependencyState &&
      (evidence.dependencyState.satisfied === false || (evidence.dependencyState.missingDependencies && evidence.dependencyState.missingDependencies.length > 0))
    ) {
      const missing = evidence.dependencyState.missingDependencies?.join(', ') || 'prerequisite unsatisfied';
      return {
        classification: 'DEPENDENCY',
        reasonCode: 'DEPENDENCY_UNAVAILABLE',
        explanation: `Dependency failure: missing or unsatisfied dependencies [${missing}].`,
        epistemicStatus: defaultEpistemic,
      };
    }

    // ------------------------------------------------------------------------
    // TIER 10: PERMANENT
    // Confirmed 4xx client errors (400, 404, 422), unrecoverable input syntax.
    // ------------------------------------------------------------------------
    if (
      (evidence.httpStatus && evidence.httpStatus >= 400 && evidence.httpStatus < 500 && evidence.httpStatus !== 429) ||
      evidence.providerErrorCategory === 'INVALID_REQUEST' ||
      evidence.providerErrorCategory === 'MALFORMED_INPUT'
    ) {
      return {
        classification: 'PERMANENT',
        reasonCode: 'PERMANENT_CLIENT_REJECTION',
        explanation: `Permanent client rejection (HTTP ${evidence.httpStatus || 400}): invalid request structure or rejected parameters.`,
        epistemicStatus: defaultEpistemic,
      };
    }

    // ------------------------------------------------------------------------
    // TIER 11: SYSTEM_INTERRUPTION
    // Cancellation, SIGTERM/SIGKILL, process crash before dispatch.
    // ------------------------------------------------------------------------
    if (
      evidence.cancellationEvidence?.cancelled === true ||
      evidence.providerErrorCategory === 'PROCESS_TERMINATED' ||
      evidence.lifecycleState === 'INTERRUPTED'
    ) {
      return {
        classification: 'SYSTEM_INTERRUPTION',
        reasonCode: 'SYSTEM_INTERRUPTION',
        explanation: `System interruption: ${evidence.cancellationEvidence?.reason || 'Process cancelled or killed prior to terminal state'}.`,
        epistemicStatus: defaultEpistemic,
      };
    }

    // ------------------------------------------------------------------------
    // TIER 12: TRANSIENT
    // Network gateway errors prior to dispatch (502, 503, 504), socket timeout
    // before dispatch.
    // ------------------------------------------------------------------------
    const isPreDispatchTimeout =
      evidence.timeoutEvidence?.timedOut === true &&
      (evidence.dispatchState === 'NOT_DISPATCHED' || evidence.timeoutEvidence?.phase === 'PRE_DISPATCH');

    if (
      isPreDispatchTimeout ||
      (evidence.httpStatus && [502, 503, 504].includes(evidence.httpStatus) && evidence.dispatchState === 'NOT_DISPATCHED') ||
      (evidence.providerErrorCategory === 'TRANSIENT_NETWORK' && evidence.dispatchState === 'NOT_DISPATCHED')
    ) {
      return {
        classification: 'TRANSIENT',
        reasonCode: 'TRANSIENT_NETWORK_FAILURE',
        explanation: `Transient network failure before dispatch (HTTP ${evidence.httpStatus || 'Timeout'}). Network connection or upstream gateway unavailable.`,
        epistemicStatus: defaultEpistemic,
      };
    }

    // ------------------------------------------------------------------------
    // TIER 13: HUMAN_REQUIRED
    // Explicit operator gate required, safety pause, unresolvable ambiguity.
    // ------------------------------------------------------------------------
    if (
      evidence.humanInterventionRequired === true ||
      evidence.policyResult?.decision === 'REQUIRE_APPROVAL'
    ) {
      return {
        classification: 'HUMAN_REQUIRED',
        reasonCode: 'HUMAN_APPROVAL_REQUIRED',
        explanation: `Human intervention required: operation mandates explicit operator review or signature.`,
        epistemicStatus: defaultEpistemic,
      };
    }

    // ------------------------------------------------------------------------
    // SAFE FALLBACK: If evidence is ambiguous, fail-closed based on dispatch state
    // ------------------------------------------------------------------------
    if (isPostDispatch) {
      return {
        classification: 'UNKNOWN_EXTERNAL_STATE',
        reasonCode: 'AMBIGUOUS_EVIDENCE_SAFE_FALLBACK',
        explanation: 'Ambiguous evidence post-dispatch: external state cannot be determined safely. Failing closed to UNKNOWN_EXTERNAL_STATE.',
        epistemicStatus: 'UNKNOWN',
      };
    }

    return {
      classification: 'SYSTEM_INTERRUPTION',
      reasonCode: 'AMBIGUOUS_EVIDENCE_SAFE_FALLBACK',
      explanation: 'Ambiguous evidence pre-dispatch: failing closed to SYSTEM_INTERRUPTION.',
      epistemicStatus: defaultEpistemic,
    };
  }
}

export const failureClassificationService = new FailureClassificationService();
