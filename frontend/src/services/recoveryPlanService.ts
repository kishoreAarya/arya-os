/**
 * AryaOS V1 — Stage 23: Deterministic Recovery Plan Service & Safe-Next-State Matrix
 *
 * Evaluates FailureClassification, Operational Truth, Idempotency, Dispatch State,
 * and Risk Context to determine the SAFE NEXT STATE.
 *
 * Produces an immutable, strongly-typed RecoveryPlan.
 *
 * IMPORTANT: RecoveryPlan generation is a decision only. ZERO execution.
 */

import {
  RecoveryAction,
  RecoveryPlan,
  GenerateRecoveryPlanInput,
  IdempotencyClassification,
  CompensationAvailability,
} from '../types/recoveryControl';
import {
  createRecoveryPlan,
  validateAndSanitizePayload,
  RecoveryContractViolationError,
} from './recoveryControl';

export class RecoveryPlanService {
  /**
   * Generates a deterministic, immutable RecoveryPlan from verified classification and context.
   * Pure decision function over evidence with zero external execution.
   */
  public generateRecoveryPlan(input: GenerateRecoveryPlanInput): Readonly<RecoveryPlan> {
    // 1. Mandatory Input & Causal Integrity Verifications
    if (!input.originalOperationId || typeof input.originalOperationId !== 'string' || input.originalOperationId.trim() === '') {
      throw new RecoveryContractViolationError('originalOperationId is mandatory');
    }
    if (!input.causationId || typeof input.causationId !== 'string' || input.causationId.trim() === '') {
      throw new RecoveryContractViolationError('causationId is mandatory');
    }
    if (!input.correlationId || typeof input.correlationId !== 'string' || input.correlationId.trim() === '') {
      throw new RecoveryContractViolationError('correlationId is mandatory');
    }
    if (!input.classificationResult || !input.classificationResult.classification) {
      throw new RecoveryContractViolationError('classificationResult is mandatory');
    }

    // 2. Security Sanitization of Nested Payloads
    const sanitizedMetadata = input.metadata ? validateAndSanitizePayload(input.metadata) : undefined;
    const sanitizedCompParams = input.compensationInfo?.parameters
      ? validateAndSanitizePayload(input.compensationInfo.parameters)
      : undefined;

    // 3. Normalized Context Extraction
    const classification = input.classificationResult.classification;
    const dispatchState = input.dispatchState || 'NOT_DISPATCHED';
    const epistemicStatus = input.classificationResult.epistemicStatus || 'OBSERVED';
    const idempotency: IdempotencyClassification = input.idempotency || 'UNKNOWN';
    const riskLevel = input.riskLevel || 'MEDIUM';
    const confirmedSuccess = Boolean(input.confirmedSuccess);

    // 4. Deterministic Recovery Matrix Evaluation
    const {
      proposedAction,
      approvalRequired,
      approvalType,
      reconciliationRequired,
      probeType,
      requiredAuthority,
      expectedOutcome,
    } = this.evaluateRecoveryMatrix({
      classification,
      dispatchState,
      epistemicStatus,
      idempotency,
      riskLevel,
      confirmedSuccess,
      partialExecution: input.partialExecution,
      compensationAvailability: input.compensationInfo?.availability || 'NO_COMPENSATION_AVAILABLE',
    });

    // 5. Construct Deterministic RecoveryPlan (Lifecycle: PROPOSED, Governance: undefined)
    const createdAt = Date.now();
    const expiry = createdAt + (input.expiryMs ?? 300000); // 5 minutes default TTL
    const currentTruthState = input.currentTruthState || `${classification}_AT_${dispatchState}`;

    const plan = createRecoveryPlan({
      originalOperationId: input.originalOperationId,
      failureClassification: classification,
      currentTruthState,
      proposedRecoveryAction: proposedAction,
      riskLevel,
      idempotencyAssessment: idempotency,
      requiredAuthority,
      governanceDecisionId: undefined, // Never fabricated; populated in Phase 8 governance integration
      approvalRequirement: {
        required: approvalRequired,
        approvalType,
      },
      reconciliationRequirement: {
        required: reconciliationRequired,
        probeType,
        timeoutMs: reconciliationRequired ? 10000 : undefined,
      },
      compensationPlan: {
        availability: input.compensationInfo?.availability || 'NO_COMPENSATION_AVAILABLE',
        compensatingActionType: input.compensationInfo?.compensatingActionType,
        targetSystem: input.compensationInfo?.targetSystem,
        parameters: sanitizedCompParams,
      },
      expectedOutcome,
      expiry,
      causationId: input.causationId,
      correlationId: input.correlationId,
      createdAt,
      lifecycleState: 'PROPOSED', // Pure proposed plan; never GOVERNED or DISPATCHED in Phase 3
      evidenceReferences: input.classificationResult.evidenceReferences ? [...input.classificationResult.evidenceReferences] : undefined,
      metadata: sanitizedMetadata,
    });

    return plan;
  }

  /**
   * Deterministic Safe-Next-State Matrix Routing.
   */
  private evaluateRecoveryMatrix(ctx: {
    classification: string;
    dispatchState: string;
    epistemicStatus: string;
    idempotency: IdempotencyClassification;
    riskLevel: 'LOW' | 'MEDIUM' | 'HIGH' | 'CRITICAL';
    confirmedSuccess: boolean;
    partialExecution?: {
      completedSteps: readonly string[];
      failedStep?: string;
      pendingSteps: readonly string[];
    };
    compensationAvailability: CompensationAvailability;
  }): {
    proposedAction: RecoveryAction;
    approvalRequired: boolean;
    approvalType?: string;
    reconciliationRequired: boolean;
    probeType?: string;
    requiredAuthority: string[];
    expectedOutcome: string;
  } {
    // ------------------------------------------------------------------------
    // RULE 2: CONFIRMED SUCCESS (Anti-Duplication Guard)
    // If the original operation confirmed successful, RETRY is strictly forbidden.
    // ------------------------------------------------------------------------
    if (ctx.confirmedSuccess) {
      return {
        proposedAction: 'WAIT',
        approvalRequired: false,
        reconciliationRequired: false,
        requiredAuthority: [],
        expectedOutcome: 'Original operation already confirmed successful. No recovery action needed; retry prohibited.',
      };
    }

    // ------------------------------------------------------------------------
    // RULE 1, 4 & 5: UNKNOWN EXTERNAL STATE / POST-DISPATCH TIMEOUT / UNKNOWN EPISYSTEMIC
    // Blind retry strictly forbidden; state reconciliation mandatory.
    // ------------------------------------------------------------------------
    const isPostDispatch =
      ctx.dispatchState === 'DISPATCHED' ||
      ctx.dispatchState === 'EXECUTING' ||
      ctx.dispatchState === 'EXTERNAL_CONFIRMATION_ABSENT';

    if (
      ctx.classification === 'UNKNOWN_EXTERNAL_STATE' ||
      (isPostDispatch && ctx.epistemicStatus === 'UNKNOWN') ||
      (isPostDispatch && ctx.idempotency === 'NON_IDEMPOTENT') ||
      (isPostDispatch && ctx.idempotency === 'UNKNOWN')
    ) {
      if (ctx.riskLevel === 'CRITICAL') {
        return {
          proposedAction: 'REQUIRE_APPROVAL',
          approvalRequired: true,
          approvalType: 'CRITICAL_RISK_UNKNOWN_STATE_OPERATOR_GATE',
          reconciliationRequired: true,
          probeType: 'STATUS_POLL',
          requiredAuthority: ['CONNECTOR_PROBE', 'HUMAN_APPROVAL'],
          expectedOutcome: 'Action dispatched but external state unconfirmed for critical operation. Mandatory operator signoff required.',
        };
      }

      return {
        proposedAction: 'RECONCILE',
        approvalRequired: false,
        reconciliationRequired: true,
        probeType: 'STATUS_POLL',
        requiredAuthority: ['CONNECTOR_PROBE', 'ACTION_RECONCILIATION'],
        expectedOutcome: 'Action dispatched but external state unconfirmed. Bounded reconciliation probe scheduled before progression.',
      };
    }

    // ------------------------------------------------------------------------
    // RULE 6: PARTIAL EXECUTION
    // Workflow where prior steps succeeded and a downstream step failed.
    // Must preserve completed steps; never replay them.
    // ------------------------------------------------------------------------
    if (ctx.classification === 'PARTIAL_EXECUTION') {
      const isHighRisk = ctx.riskLevel === 'HIGH' || ctx.riskLevel === 'CRITICAL';

      if (isHighRisk) {
        return {
          proposedAction: 'REQUIRE_APPROVAL',
          approvalRequired: true,
          approvalType: 'PARTIAL_WORKFLOW_RESUMPTION_APPROVAL',
          reconciliationRequired: false,
          requiredAuthority: ['WORKFLOW_RESUME', 'HUMAN_APPROVAL'],
          expectedOutcome: 'Partial execution in high-risk workflow. Completed steps preserved; operator approval required to resume.',
        };
      }

      return {
        proposedAction: 'RESUME',
        approvalRequired: false,
        reconciliationRequired: false,
        requiredAuthority: ['WORKFLOW_RESUME'],
        expectedOutcome: 'Partial execution detected. Completed steps preserved without replay; resuming from failed milestone.',
      };
    }

    // ------------------------------------------------------------------------
    // RULE 7: PERMISSION FAILURE
    // Connector revoked / missing scope. Cannot grant ambient permissions.
    // ------------------------------------------------------------------------
    if (ctx.classification === 'PERMISSION') {
      if (ctx.riskLevel === 'CRITICAL') {
        return {
          proposedAction: 'ESCALATE',
          approvalRequired: true,
          approvalType: 'CRITICAL_PERMISSION_REVOCATION_ESCALATION',
          reconciliationRequired: false,
          requiredAuthority: ['SECURITY_ADMIN_INTERVENTION'],
          expectedOutcome: 'Connector permission revoked on critical operation. Escalated to security administration.',
        };
      }

      return {
        proposedAction: 'REQUIRE_APPROVAL',
        approvalRequired: true,
        approvalType: 'CONNECTOR_REAUTHORIZATION_REQUIRED',
        reconciliationRequired: false,
        requiredAuthority: ['CONNECTOR_CREDENTIAL_REAUTHORIZATION', 'HUMAN_APPROVAL'],
        expectedOutcome: 'Connector permission revoked or missing. Operator must refresh credential authorization through Stage 16.',
      };
    }

    // ------------------------------------------------------------------------
    // RULE 8: AUTHORIZATION FAILURE
    // Capability unauthorized. Cannot self-authorize.
    // ------------------------------------------------------------------------
    if (ctx.classification === 'AUTHORIZATION') {
      return {
        proposedAction: 'REQUIRE_APPROVAL',
        approvalRequired: true,
        approvalType: 'ACTION_AUTHORIZATION_APPROVAL',
        reconciliationRequired: false,
        requiredAuthority: ['ACTION_AUTHORIZATION_GRANT', 'HUMAN_APPROVAL'],
        expectedOutcome: 'Action authorization denied. Cannot self-authorize; awaiting operator capability grant.',
      };
    }

    // ------------------------------------------------------------------------
    // RULE 9: POLICY FAILURE
    // Policy DENIED. Active policy remains authoritative.
    // ------------------------------------------------------------------------
    if (ctx.classification === 'POLICY') {
      return {
        proposedAction: 'ABORT',
        approvalRequired: false,
        reconciliationRequired: false,
        requiredAuthority: [],
        expectedOutcome: 'Operation denied by active governance policy. Aborting execution; policy bypass strictly forbidden.',
      };
    }

    // ------------------------------------------------------------------------
    // RULE 10: STALE STATE
    // Stale snapshot / expired TTL. Must revalidate before progression.
    // ------------------------------------------------------------------------
    if (ctx.classification === 'STALE_STATE') {
      return {
        proposedAction: 'RECONCILE',
        approvalRequired: false,
        reconciliationRequired: true,
        probeType: 'GOVERNANCE_SNAPSHOT_REFRESH',
        requiredAuthority: ['GOVERNANCE_SNAPSHOT_REFRESH'],
        expectedOutcome: 'Stale governance snapshot or expired approval detected. Revalidation required before proceeding.',
      };
    }

    // ------------------------------------------------------------------------
    // RULE 11: RECONCILIATION FAILURE
    // Discrepancy observed.
    // ------------------------------------------------------------------------
    if (ctx.classification === 'RECONCILIATION') {
      if (ctx.compensationAvailability === 'COMPENSATION_AVAILABLE') {
        return {
          proposedAction: 'COMPENSATE',
          approvalRequired: ctx.riskLevel !== 'LOW',
          approvalType: 'COMPENSATION_EXECUTION_APPROVAL',
          reconciliationRequired: true,
          probeType: 'POST_COMPENSATION_VERIFICATION',
          requiredAuthority: ['COMPENSATION_DISPATCH'],
          expectedOutcome: 'Environmental reconciliation mismatch detected. Formulating compensating action to reconcile reality.',
        };
      }

      return {
        proposedAction: 'RECONCILE',
        approvalRequired: ctx.riskLevel === 'HIGH' || ctx.riskLevel === 'CRITICAL',
        approvalType: 'RECONCILIATION_OVERRIDE_APPROVAL',
        reconciliationRequired: true,
        probeType: 'STATE_RESYNC',
        requiredAuthority: ['STATE_RECONCILIATION_SYNC'],
        expectedOutcome: 'Observed reality contradicts intent. Additional state synchronization probe required.',
      };
    }

    // ------------------------------------------------------------------------
    // RULE 12: PERMANENT FAILURE
    // Unrecoverable 4xx / malformed syntax.
    // ------------------------------------------------------------------------
    if (ctx.classification === 'PERMANENT') {
      return {
        proposedAction: 'ABORT',
        approvalRequired: false,
        reconciliationRequired: false,
        requiredAuthority: [],
        expectedOutcome: 'Confirmed permanent rejection (HTTP 4xx / malformed request). Aborting operation; retries prohibited.',
      };
    }

    // ------------------------------------------------------------------------
    // RULE 14: HUMAN REQUIRED
    // Operator signoff mandatory.
    // ------------------------------------------------------------------------
    if (ctx.classification === 'HUMAN_REQUIRED') {
      return {
        proposedAction: 'REQUIRE_APPROVAL',
        approvalRequired: true,
        approvalType: 'MANDATORY_OPERATOR_SIGNOFF',
        reconciliationRequired: false,
        requiredAuthority: ['HUMAN_APPROVAL'],
        expectedOutcome: 'Operation mandates explicit operator review or signature prior to any recovery progression.',
      };
    }

    // ------------------------------------------------------------------------
    // RESOURCE EXHAUSTION (Rate Limit / Quota)
    // ------------------------------------------------------------------------
    if (ctx.classification === 'RESOURCE') {
      return {
        proposedAction: 'WAIT',
        approvalRequired: false,
        reconciliationRequired: false,
        requiredAuthority: [],
        expectedOutcome: 'Resource quota or rate limit exceeded. Backing off and waiting for quota window to reset.',
      };
    }

    // ------------------------------------------------------------------------
    // DEPENDENCY MISSING
    // ------------------------------------------------------------------------
    if (ctx.classification === 'DEPENDENCY') {
      return {
        proposedAction: 'WAIT',
        approvalRequired: false,
        reconciliationRequired: false,
        requiredAuthority: [],
        expectedOutcome: 'Prerequisite dependency missing or unsatisfied. Awaiting upstream prerequisite completion.',
      };
    }

    // ------------------------------------------------------------------------
    // RULE 13: SYSTEM INTERRUPTION
    // ------------------------------------------------------------------------
    if (ctx.classification === 'SYSTEM_INTERRUPTION') {
      if (isPostDispatch) {
        return {
          proposedAction: 'RECONCILE',
          approvalRequired: false,
          reconciliationRequired: true,
          probeType: 'STATUS_POLL',
          requiredAuthority: ['CONNECTOR_PROBE'],
          expectedOutcome: 'Process interrupted after dispatch. Reconciling external state before resuming.',
        };
      }

      return {
        proposedAction: 'RESUME',
        approvalRequired: false,
        reconciliationRequired: false,
        requiredAuthority: ['PROCESS_RESUME'],
        expectedOutcome: 'Process interrupted prior to dispatch. Resuming execution from last saved checkpoint.',
      };
    }

    // ------------------------------------------------------------------------
    // RULE 3: TRANSIENT FAILURE (Safe Retry Eligibility)
    // Transient error strictly before dispatch.
    // ------------------------------------------------------------------------
    if (ctx.classification === 'TRANSIENT') {
      const isSafeIdempotent =
        ctx.idempotency === 'READ_ONLY' ||
        ctx.idempotency === 'IDEMPOTENT' ||
        ctx.riskLevel === 'LOW';

      if (ctx.dispatchState === 'NOT_DISPATCHED' && isSafeIdempotent) {
        return {
          proposedAction: 'RETRY',
          approvalRequired: false,
          reconciliationRequired: false,
          requiredAuthority: ['ACTION_BUS_DISPATCH'],
          expectedOutcome: 'Transient network failure occurred strictly before dispatch on idempotent operation. Eligible for safe retry.',
        };
      }

      // Non-idempotent or unknown idempotency: require approval
      return {
        proposedAction: 'REQUIRE_APPROVAL',
        approvalRequired: true,
        approvalType: 'TRANSIENT_NON_IDEMPOTENT_RETRY_APPROVAL',
        reconciliationRequired: false,
        requiredAuthority: ['ACTION_BUS_DISPATCH', 'HUMAN_APPROVAL'],
        expectedOutcome: 'Transient failure on non-idempotent operation. Automatic retry prohibited; operator signoff required.',
      };
    }

    // ------------------------------------------------------------------------
    // SAFE FALLBACK
    // ------------------------------------------------------------------------
    return {
      proposedAction: 'WAIT',
      approvalRequired: true,
      approvalType: 'UNKNOWN_STATE_OPERATOR_REVIEW',
      reconciliationRequired: false,
      requiredAuthority: ['HUMAN_APPROVAL'],
      expectedOutcome: 'Ambiguous operational context. Holding in safe wait state pending operator review.',
    };
  }
}

export const recoveryPlanService = new RecoveryPlanService();
