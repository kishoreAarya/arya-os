/**
 * AryaOS V1 — Stage 23: Declarative Compensation & Reverse Operations
 *
 * Phase 6: Formulates, evaluates, governs, and coordinates safe declarative
 * compensation plans for operations requiring mitigation or reversal.
 *
 * ABSOLUTE BOUNDARIES:
 * - ZERO direct network calls (no fetch, no Axios, no provider SDK, no raw sockets).
 * - ZERO arbitrary inverse generation or executable callbacks.
 * - Compensation != Rollback: Original operation and audit history remain immutable.
 * - Compensation has distinct operationId, distinct actionId, distinct idempotencyKey,
 *   explicit causationId link, and preserved correlationId.
 * - Human approval is strictly enforced via Stage 21 Governance contracts.
 * - Execution strictly delegates to Stage 15 Action Bus or Stage 07 Execution Gateway.
 * - Epistemic honesty: Dispatched != Confirmed. Post-compensation verification required.
 * - Anti-looping: Bounded recovery depth (MAX_RECOVERY_DEPTH = 3) and cycle rejection.
 */

import {
  DeclarativeCompensationPlan,
  CompensationAssessmentResult,
  AssessCompensationInput,
  CompensationDispatchResult,
  CompensationEligibility,
  ReversibilityClassification,
  CompensationType,
  CompensationLifecycleState,
  ReconciliationResultRecord,
  MAX_RECOVERY_DEPTH,
} from '../types/recoveryControl';
import {
  createDeclarativeCompensationPlan,
  validateAndSanitizePayload,
  RecoveryContractViolationError,
  deepFreeze,
} from './recoveryControl';
import { ActionRequest, ActionResult } from '../types/actionBus';
import { GovernanceActor } from '../types/governanceControlPlane';

export interface ReverseMappingEntry {
  readonly compensatingCapability: string;
  readonly compensationType: CompensationType;
  readonly reversibilityClass: ReversibilityClassification;
  readonly defaultTargetState: string;
  readonly riskLevel: 'LOW' | 'MEDIUM' | 'HIGH' | 'CRITICAL';
  readonly requiresHumanApproval: boolean;
  readonly requiredParameters: readonly string[];
  readonly parameterMapper?: (originalParams: Record<string, unknown>) => Record<string, unknown>;
}

export interface CompensationExecutionBoundary {
  readonly executeActionBus?: (request: ActionRequest) => Promise<ActionResult>;
  readonly executeGateway?: (request: {
    actionId: string;
    capabilityId: string;
    parameters: Record<string, unknown>;
    idempotencyKey: string;
  }) => Promise<{ success: boolean; data?: unknown; error?: unknown }>;
}

export class RecoveryCompensationService {
  /**
   * Explicit, bounded, declarative reverse mapping table.
   * Arbitrary capabilities not listed here receive COMPENSATION_UNAVAILABLE.
   */
  private readonly reverseMappings: Readonly<Record<string, ReverseMappingEntry>> = Object.freeze({
    'filesystem.write': {
      compensatingCapability: 'filesystem.delete',
      compensationType: 'RESOURCE_CLEANUP',
      reversibilityClass: 'FULLY_REVERSIBLE',
      defaultTargetState: 'FILE_REMOVED',
      riskLevel: 'HIGH',
      requiresHumanApproval: true,
      requiredParameters: ['path'],
      parameterMapper: (params) => ({
        path: params.path || params.filePath,
      }),
    },
    'filesystem.create_directory': {
      compensatingCapability: 'filesystem.delete_directory',
      compensationType: 'RESOURCE_CLEANUP',
      reversibilityClass: 'FULLY_REVERSIBLE',
      defaultTargetState: 'DIRECTORY_REMOVED',
      riskLevel: 'HIGH',
      requiresHumanApproval: true,
      requiredParameters: ['path'],
      parameterMapper: (params) => ({
        path: params.path || params.dirPath,
      }),
    },
    'github.create_issue': {
      compensatingCapability: 'github.close_issue',
      compensationType: 'STATE_CORRECTION',
      reversibilityClass: 'COMPENSATABLE',
      defaultTargetState: 'ISSUE_CLOSED',
      riskLevel: 'MEDIUM',
      requiresHumanApproval: false,
      requiredParameters: ['repository'],
      parameterMapper: (params) => ({
        repository: params.repository,
        issueNumber: params.issueNumber || params.issue_number,
        comment: 'Closed automatically by AryaOS Stage 23 recovery compensation.',
      }),
    },
    'github.create_comment': {
      compensatingCapability: 'github.delete_comment',
      compensationType: 'RESOURCE_CLEANUP',
      reversibilityClass: 'FULLY_REVERSIBLE',
      defaultTargetState: 'COMMENT_DELETED',
      riskLevel: 'MEDIUM',
      requiresHumanApproval: false,
      requiredParameters: ['repository', 'commentId'],
      parameterMapper: (params) => ({
        repository: params.repository,
        commentId: params.commentId || params.comment_id,
      }),
    },
  });

  /**
   * Known irreversible capabilities that produce no automatic inverse.
   */
  private readonly irreversibleCapabilities: ReadonlySet<string> = new Set([
    'notification.send',
    'notification.broadcast',
    'email.send',
    'webhook.trigger',
    'external_http.post',
  ]);

  /**
   * Known read-only capabilities that produce no external side effects.
   */
  private readonly readOnlyCapabilities: ReadonlySet<string> = new Set([
    'web.search',
    'filesystem.read',
    'filesystem.stat',
    'github.read',
    'github.get_issue',
    'external_http.get',
    'database.read',
  ]);

  /**
   * Deterministically assesses compensation eligibility and formulates a candidate DeclarativeCompensationPlan.
   * Does NOT dispatch any external action.
   */
  public assessCompensation(input: AssessCompensationInput): Readonly<CompensationAssessmentResult> {
    if (!input) {
      throw new RecoveryContractViolationError('AssessCompensationInput is mandatory');
    }
    if (!input.originalOperationId || input.originalOperationId.trim() === '') {
      throw new RecoveryContractViolationError('originalOperationId is mandatory');
    }
    if (!input.capabilityId || input.capabilityId.trim() === '') {
      throw new RecoveryContractViolationError('capabilityId is mandatory');
    }

    // Security check: reject prototype pollution, arbitrary URLs, and secrets
    if (input.metadata) {
      validateAndSanitizePayload(input.metadata);
    }
    if (input.parameters) {
      validateAndSanitizePayload(input.parameters);
    }

    // Hard Boundary: No arbitrary URLs as capability
    if (/^https?:\/\//i.test(input.capabilityId)) {
      throw new RecoveryContractViolationError('Arbitrary URLs are strictly forbidden as capability');
    }

    // 1. Loop and Depth Protection (Rule 13)
    const currentDepth = input.recoveryDepth ?? 0;
    if (currentDepth >= MAX_RECOVERY_DEPTH) {
      return deepFreeze({
        eligibility: 'COMPENSATION_UNSAFE',
        reversibility: 'IRREVERSIBLE',
        rationale: `Maximum recovery depth of ${MAX_RECOVERY_DEPTH} reached. Prevents recursive compensation loops.`,
        requiresHumanApproval: false,
        requiresReconciliation: false,
        idempotencyAssessment: 'NON_IDEMPOTENT',
      });
    }

    if (input.visitedOperationIds && input.visitedOperationIds.includes(input.originalOperationId)) {
      return deepFreeze({
        eligibility: 'COMPENSATION_UNSAFE',
        reversibility: 'IRREVERSIBLE',
        rationale: `Cycle detected: operation '${input.originalOperationId}' is already in visited compensation chain.`,
        requiresHumanApproval: false,
        requiresReconciliation: false,
        idempotencyAssessment: 'NON_IDEMPOTENT',
      });
    }

    // 2. Pre-Dispatch Failure Check (Rule 4 Scenario 1)
    if (
      input.dispatchState === 'NOT_DISPATCHED' ||
      input.failureClassification === 'POLICY' ||
      input.failureClassification === 'PERMISSION'
    ) {
      return deepFreeze({
        eligibility: 'COMPENSATION_NOT_REQUIRED',
        reversibility: 'IRREVERSIBLE',
        rationale: 'Operation failed pre-dispatch before any external side effect occurred.',
        requiresHumanApproval: false,
        requiresReconciliation: false,
        idempotencyAssessment: 'READ_ONLY',
      });
    }

    // 3. Read-Only Actions (No persistent side effects)
    if (this.readOnlyCapabilities.has(input.capabilityId)) {
      return deepFreeze({
        eligibility: 'COMPENSATION_NOT_REQUIRED',
        reversibility: 'IRREVERSIBLE',
        rationale: `Capability '${input.capabilityId}' is read-only and produces no external side effects requiring compensation.`,
        requiresHumanApproval: false,
        requiresReconciliation: false,
        idempotencyAssessment: 'READ_ONLY',
      });
    }

    // 4. Reconciliation Verification Outcomes (Rule 4 Scenario 4 & 5)
    if (input.reconciliationResult) {
      const recon = input.reconciliationResult;
      if (recon.outcome === 'VERIFIED_FAILURE') {
        return deepFreeze({
          eligibility: 'COMPENSATION_NOT_REQUIRED',
          reversibility: 'IRREVERSIBLE',
          rationale: 'Reconciliation verified that the original operation did not take effect externally.',
          requiresHumanApproval: false,
          requiresReconciliation: false,
          idempotencyAssessment: 'READ_ONLY',
        });
      }
      if (recon.outcome === 'STILL_UNKNOWN' || recon.outcome === 'FAILED') {
        return deepFreeze({
          eligibility: 'COMPENSATION_REQUIRES_RECONCILIATION',
          reversibility: 'IRREVERSIBLE',
          rationale: 'Reconciliation probe failed or indeterminate. External state remains UNKNOWN; cannot safely formulate compensation.',
          requiresHumanApproval: false,
          requiresReconciliation: true,
          idempotencyAssessment: 'UNKNOWN',
        });
      }
    }

    // 5. Unknown External State Check (Must reconcile first)
    const isUnknownState =
      input.dispatchState === 'EXTERNAL_CONFIRMATION_ABSENT' ||
      input.dispatchState === 'DISPATCH_ATTEMPTED' ||
      input.dispatchState === 'DISPATCHED' ||
      input.failureClassification === 'UNKNOWN_EXTERNAL_STATE' ||
      input.truthState === 'UNKNOWN';

    if (isUnknownState && !input.confirmedSuccess && (!input.reconciliationResult || input.reconciliationResult.outcome !== 'VERIFIED_SUCCESS')) {
      return deepFreeze({
        eligibility: 'COMPENSATION_REQUIRES_RECONCILIATION',
        reversibility: 'IRREVERSIBLE',
        rationale: 'External operational state is UNKNOWN. Read-only reconciliation is required before compensation can be evaluated.',
        requiresHumanApproval: false,
        requiresReconciliation: true,
        idempotencyAssessment: 'UNKNOWN',
      });
    }

    // 6. Partial Execution Handling (Rule 4 Scenario 3)
    if (input.partialExecution) {
      if (input.partialExecution.completedSteps.length === 0) {
        return deepFreeze({
          eligibility: 'COMPENSATION_NOT_REQUIRED',
          reversibility: 'IRREVERSIBLE',
          rationale: 'Partial execution has zero completed steps; no external side effects require compensation.',
          requiresHumanApproval: false,
          requiresReconciliation: false,
          idempotencyAssessment: 'READ_ONLY',
        });
      }
    }

    // 7. Irreversible Capability Check (Rule 6)
    if (this.irreversibleCapabilities.has(input.capabilityId)) {
      return deepFreeze({
        eligibility: 'COMPENSATION_UNAVAILABLE',
        reversibility: 'IRREVERSIBLE',
        rationale: `Capability '${input.capabilityId}' produces irreversible external side effects (e.g., notifications). No automatic inverse exists.`,
        requiresHumanApproval: false,
        requiresReconciliation: false,
        idempotencyAssessment: 'NON_IDEMPOTENT',
      });
    }

    // 8. Reverse Mapping Lookup
    const mapping = this.reverseMappings[input.capabilityId];
    if (!mapping) {
      return deepFreeze({
        eligibility: 'COMPENSATION_UNAVAILABLE',
        reversibility: 'IRREVERSIBLE',
        rationale: `No explicit compensating reverse mapping exists for capability '${input.capabilityId}'.`,
        requiresHumanApproval: false,
        requiresReconciliation: false,
        idempotencyAssessment: 'NON_IDEMPOTENT',
      });
    }

    // 9. Check Required Parameters for Compensation
    const originalParams = input.parameters || {};
    const missingParams = mapping.requiredParameters.filter((param) => {
      if (param === 'path') {
        return !originalParams.path && !originalParams.filePath && !originalParams.dirPath;
      }
      return originalParams[param] === undefined;
    });

    if (missingParams.length > 0) {
      return deepFreeze({
        eligibility: 'COMPENSATION_UNSAFE',
        reversibility: mapping.reversibilityClass,
        rationale: `Cannot formulate compensation for '${input.capabilityId}': missing required target parameters [${missingParams.join(', ')}].`,
        requiresHumanApproval: mapping.requiresHumanApproval,
        requiresReconciliation: false,
        idempotencyAssessment: 'NON_IDEMPOTENT',
      });
    }

    // 10. Formulate Declarative Compensation Plan
    const timestamp = Date.now();
    const nonce = Math.random().toString(36).substring(2, 7);
    const compensationId = `comp_${input.originalOperationId}_${timestamp}_${nonce}`;
    const idempotencyKey = `comp-idem-${input.originalOperationId}-${mapping.compensatingCapability}-${timestamp}`;
    const causationId = input.originalOperationId;
    const correlationId = input.correlationId || input.recoveryPlan?.correlationId || input.originalOperationId;

    const compensationParameters = mapping.parameterMapper
      ? mapping.parameterMapper(originalParams)
      : { ...originalParams };

    const plan = createDeclarativeCompensationPlan({
      compensationId,
      originalOperationId: input.originalOperationId,
      originalActionId: input.originalActionId,
      compensationType: mapping.compensationType,
      sourceCapability: input.capabilityId,
      compensatingCapability: mapping.compensatingCapability,
      targetState: mapping.defaultTargetState,
      compensationParameters,
      reversibilityClass: mapping.reversibilityClass,
      idempotencyClass: 'IDEMPOTENT',
      riskLevel: mapping.riskLevel,
      requiredAuthority: mapping.requiresHumanApproval ? ['OPERATOR_HUMAN_APPROVAL'] : ['SYSTEM_RECOVERY'],
      approvalRequirement: {
        required: mapping.requiresHumanApproval,
        humanOperatorRequired: mapping.requiresHumanApproval,
      },
      reconciliationRequirement: {
        required: true,
        postCompensationVerification: true,
        timeoutMs: 10000,
      },
      idempotencyKey,
      causationId,
      correlationId,
      expiresAt: timestamp + 300000, // 5 minutes
      lifecycleState: mapping.requiresHumanApproval ? 'PROPOSED' : 'READY',
      recoveryDepth: currentDepth + 1,
      metadata: input.metadata ? { ...input.metadata } : undefined,
    });

    const eligibility: CompensationEligibility = mapping.requiresHumanApproval
      ? 'COMPENSATION_REQUIRES_APPROVAL'
      : 'COMPENSATION_ELIGIBLE';

    return deepFreeze({
      eligibility,
      reversibility: mapping.reversibilityClass,
      rationale: mapping.requiresHumanApproval
        ? `Declarative compensation '${mapping.compensatingCapability}' formulated. High risk / destructive operation requires Stage 21 human approval.`
        : `Declarative compensation '${mapping.compensatingCapability}' formulated and ready for governed dispatch.`,
      candidatePlan: plan,
      requiresHumanApproval: mapping.requiresHumanApproval,
      requiresReconciliation: false,
      idempotencyAssessment: 'IDEMPOTENT',
    });
  }

  /**
   * Applies an authenticated human approval to a proposed compensation plan.
   * Bound to Stage 21 Governance requirements (actorId, actorType === 'USER').
   * Rejects SYSTEM, AUTONOMOUS_AGENT, and client-supplied boolean flags.
   */
  public applyHumanApproval(
    plan: DeclarativeCompensationPlan,
    approval: {
      actor: GovernanceActor;
      governanceDecisionId: string;
      policySnapshotId?: string;
      policyVersion?: number;
      timestamp?: number;
    }
  ): Readonly<DeclarativeCompensationPlan> {
    if (!plan) {
      throw new RecoveryContractViolationError('DeclarativeCompensationPlan is mandatory');
    }
    if (!approval || !approval.actor) {
      throw new RecoveryContractViolationError('Governance approval actor is mandatory');
    }
    if (approval.actor.actorType !== 'USER') {
      throw new RecoveryContractViolationError(
        `Invalid approval actor type '${approval.actor.actorType}'. Only authenticated human operators ('USER') can authorize compensation.`
      );
    }
    if (!approval.actor.actorId || approval.actor.actorId.trim() === '') {
      throw new RecoveryContractViolationError('actor.actorId is mandatory and cannot be empty');
    }
    if (!approval.governanceDecisionId || approval.governanceDecisionId.trim() === '') {
      throw new RecoveryContractViolationError('governanceDecisionId is mandatory');
    }

    // Verify lifecycle transition
    if (plan.lifecycleState !== 'PROPOSED' && plan.lifecycleState !== 'GOVERNED') {
      throw new RecoveryContractViolationError(
        `Cannot apply approval to compensation plan in '${plan.lifecycleState}' state (must be PROPOSED or GOVERNED)`
      );
    }

    const updatedPlan: DeclarativeCompensationPlan = {
      ...plan,
      approvalRequirement: {
        required: true,
        humanOperatorRequired: true,
        approvedBy: approval.actor.actorId,
        approvedAt: approval.timestamp ?? Date.now(),
        governanceDecisionId: approval.governanceDecisionId,
      },
      lifecycleState: 'APPROVED',
    };

    return deepFreeze(updatedPlan);
  }

  /**
   * Coordinates execution of a declared compensation plan across Stage 15 Action Bus
   * or Stage 07 Execution Gateway.
   * STRICT INVARIANT: ZERO direct network calls.
   */
  public async coordinateCompensation(
    plan: DeclarativeCompensationPlan,
    boundary: CompensationExecutionBoundary
  ): Promise<CompensationDispatchResult> {
    if (!plan) {
      throw new RecoveryContractViolationError('DeclarativeCompensationPlan is mandatory');
    }

    // Check approval gating
    if (plan.approvalRequirement.required && !plan.approvalRequirement.approvedBy) {
      throw new RecoveryContractViolationError(
        `Compensation plan '${plan.compensationId}' requires human approval before dispatch`
      );
    }

    // Check lifecycle readiness
    if (plan.lifecycleState !== 'READY' && plan.lifecycleState !== 'APPROVED') {
      throw new RecoveryContractViolationError(
        `Compensation plan '${plan.compensationId}' is in '${plan.lifecycleState}' state; must be READY or APPROVED to dispatch`
      );
    }

    const timestamp = Date.now();
    const actionId = `act_comp_${plan.compensationId}_${timestamp}`;

    // 1. Stage 15 Action Bus Delegation
    if (boundary.executeActionBus) {
      const actionRequest: ActionRequest = {
        actionId,
        capabilityId: plan.compensatingCapability,
        operation: 'execute',
        parameters: { ...plan.compensationParameters },
        idempotencyKey: plan.idempotencyKey,
        context: {
          timestamp: new Date(timestamp).toISOString(),
        },
        metadata: {
          compensationId: plan.compensationId,
          originalOperationId: plan.originalOperationId,
          causationId: plan.causationId,
          correlationId: plan.correlationId,
          isCompensation: true,
        },
      };

      try {
        const actionResult = await boundary.executeActionBus(actionRequest);
        const nextState: CompensationLifecycleState = plan.reconciliationRequirement.postCompensationVerification
          ? 'VERIFYING'
          : 'DISPATCHED';

        return deepFreeze({
          compensationId: plan.compensationId,
          originalOperationId: plan.originalOperationId,
          dispatchSuccess: actionResult.success,
          lifecycleState: nextState,
          dispatchedActionId: actionId,
          dispatchedIdempotencyKey: plan.idempotencyKey,
          rawResultData: actionResult.data,
          error: actionResult.error?.message,
          timestamp,
        });
      } catch (err) {
        return deepFreeze({
          compensationId: plan.compensationId,
          originalOperationId: plan.originalOperationId,
          dispatchSuccess: false,
          lifecycleState: 'FAILED',
          dispatchedActionId: actionId,
          dispatchedIdempotencyKey: plan.idempotencyKey,
          error: err instanceof Error ? err.message : String(err),
          timestamp,
        });
      }
    }

    // 2. Stage 07 Execution Gateway Delegation
    if (boundary.executeGateway) {
      try {
        const gatewayResult = await boundary.executeGateway({
          actionId,
          capabilityId: plan.compensatingCapability,
          parameters: { ...plan.compensationParameters },
          idempotencyKey: plan.idempotencyKey,
        });

        const nextState: CompensationLifecycleState = plan.reconciliationRequirement.postCompensationVerification
          ? 'VERIFYING'
          : 'DISPATCHED';

        return deepFreeze({
          compensationId: plan.compensationId,
          originalOperationId: plan.originalOperationId,
          dispatchSuccess: gatewayResult.success,
          lifecycleState: nextState,
          dispatchedActionId: actionId,
          dispatchedIdempotencyKey: plan.idempotencyKey,
          rawResultData: gatewayResult.data,
          error: gatewayResult.error ? String(gatewayResult.error) : undefined,
          timestamp,
        });
      } catch (err) {
        return deepFreeze({
          compensationId: plan.compensationId,
          originalOperationId: plan.originalOperationId,
          dispatchSuccess: false,
          lifecycleState: 'FAILED',
          dispatchedActionId: actionId,
          dispatchedIdempotencyKey: plan.idempotencyKey,
          error: err instanceof Error ? err.message : String(err),
          timestamp,
        });
      }
    }

    throw new RecoveryContractViolationError(
      'No valid execution boundary (Action Bus or Execution Gateway) provided for compensation dispatch'
    );
  }

  /**
   * Verifies the outcome of a dispatched compensation plan using empirical reconciliation evidence.
   * Enforces epistemic honesty: indeterminate verification remains UNKNOWN.
   */
  public verifyCompensation(
    plan: DeclarativeCompensationPlan,
    reconciliationResult: ReconciliationResultRecord
  ): Readonly<DeclarativeCompensationPlan> {
    if (!plan) {
      throw new RecoveryContractViolationError('DeclarativeCompensationPlan is mandatory');
    }
    if (!reconciliationResult) {
      throw new RecoveryContractViolationError('ReconciliationResultRecord is mandatory');
    }

    // Legal transitions from VERIFYING or DISPATCHED
    if (plan.lifecycleState !== 'VERIFYING' && plan.lifecycleState !== 'DISPATCHED') {
      throw new RecoveryContractViolationError(
        `Cannot verify compensation plan in '${plan.lifecycleState}' state (must be VERIFYING or DISPATCHED)`
      );
    }

    let nextState: CompensationLifecycleState;

    switch (reconciliationResult.outcome) {
      case 'VERIFIED_SUCCESS':
        nextState = 'COMPLETED';
        break;
      case 'VERIFIED_FAILURE':
        nextState = 'FAILED';
        break;
      case 'STILL_UNKNOWN':
      case 'FAILED':
      default:
        // Epistemic honesty: uncertainty is strictly preserved!
        nextState = 'UNKNOWN';
        break;
    }

    const updatedPlan: DeclarativeCompensationPlan = {
      ...plan,
      lifecycleState: nextState,
      evidenceReferences: Object.freeze([
        ...(plan.evidenceReferences || []),
        reconciliationResult.reconciliationId,
      ]),
    };

    return deepFreeze(updatedPlan);
  }
}

export const recoveryCompensationService = new RecoveryCompensationService();
