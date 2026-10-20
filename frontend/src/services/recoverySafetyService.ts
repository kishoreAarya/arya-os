/**
 * AryaOS V1 — Stage 23: Recovery Safety Analysis & Duplicate-Side-Effect Prevention
 *
 * Phase 4: Evaluates RecoveryPlan, Operational Evidence, Idempotency, Partial Execution,
 * and External Confirmation State to determine whether the proposed recovery action
 * is SAFE TO PROCEED WITH.
 *
 * ABSOLUTE BOUNDARIES:
 * - ZERO execution (no fetch, no Axios, no provider SDKs, no Action Bus dispatch, no executionGateway).
 * - ZERO governance evaluation (never generates governanceDecisionId, does not authorize).
 * - ZERO reconciliation execution (determines requirement only).
 * - ZERO LLM calls (0 tokens, 100% deterministic TypeScript logic).
 * - ZERO second idempotency cache or second DAG engine.
 */

import {
  RecoveryPlan,
  RecoverySafetyAssessment,
  AssessRecoverySafetyInput,
  IdempotencyClassification,
  CompensationAvailability,
  DispatchState,
} from '../types/recoveryControl';
import {
  createRecoverySafetyAssessment,
  validateAndSanitizePayload,
  RecoveryContractViolationError,
} from './recoveryControl';

export class RecoverySafetyService {
  /**
   * Deterministically evaluates the safety of a proposed RecoveryPlan.
   * Answers: "Is the proposed recovery action safe to proceed with?"
   * Pure decision analysis with zero external side effects.
   */
  public assessSafety(input: AssessRecoverySafetyInput): Readonly<RecoverySafetyAssessment> {
    // 1. Mandatory Input Verification
    if (!input || !input.plan) {
      throw new RecoveryContractViolationError('RecoveryPlan is mandatory for safety assessment');
    }
    if (!input.plan.originalOperationId || input.plan.originalOperationId.trim() === '') {
      throw new RecoveryContractViolationError('plan.originalOperationId is mandatory');
    }
    if (!input.plan.causationId || input.plan.causationId.trim() === '') {
      throw new RecoveryContractViolationError('plan.causationId is mandatory');
    }
    if (!input.plan.correlationId || input.plan.correlationId.trim() === '') {
      throw new RecoveryContractViolationError('plan.correlationId is mandatory');
    }

    // 2. Security Sanitization (Prototype Pollution & Payload Bounding)
    if (input.metadata) {
      validateAndSanitizePayload(input.metadata);
    }
    if (input.evidence?.metadata) {
      validateAndSanitizePayload(input.evidence.metadata);
    }

    // 3. Normalized Operational Context
    const plan = input.plan;
    const classification = plan.failureClassification;
    const proposedAction = plan.proposedRecoveryAction;

    // Idempotency: Input override or plan assessment, defaulting conservatively to UNKNOWN
    const idempotency: IdempotencyClassification =
      input.idempotency || plan.idempotencyAssessment || 'UNKNOWN';

    // Dispatch State: Input override or evidence dispatch state, defaulting to NOT_DISPATCHED
    const dispatchState: DispatchState =
      input.dispatchState || input.evidence?.dispatchState || 'NOT_DISPATCHED';

    // Confirmed Success: ONLY authoritative evidence accepted.
    // Client-supplied / unverified metadata claiming "success" is strictly ignored.
    const confirmedSuccess = Boolean(
      input.confirmedSuccess ||
      input.externalConfirmationReceived ||
      dispatchState === 'EXTERNAL_CONFIRMATION_RECEIVED' ||
      input.evidence?.dispatchState === 'EXTERNAL_CONFIRMATION_RECEIVED'
    );

    // Partial Execution extraction
    const partialSource = input.partialExecution || input.evidence?.partialExecutionEvidence;
    const completedSteps: string[] = partialSource?.completedSteps ? [...partialSource.completedSteps] : [];
    const incompleteSteps: string[] = [];
    if (partialSource?.failedStep) {
      incompleteSteps.push(partialSource.failedStep);
    }
    if (partialSource?.pendingSteps) {
      for (const step of partialSource.pendingSteps) {
        if (!incompleteSteps.includes(step)) {
          incompleteSteps.push(step);
        }
      }
    }

    const partialExecutionDetected = Boolean(
      classification === 'PARTIAL_EXECUTION' ||
      completedSteps.length > 0 ||
      incompleteSteps.length > 0 ||
      input.partialExecution !== undefined ||
      input.evidence?.partialExecutionEvidence !== undefined
    );

    // Compensation & Rollback
    const compensationAvailability: CompensationAvailability =
      input.compensationAvailability ||
      plan.compensationPlan?.availability ||
      'NO_COMPENSATION_AVAILABLE';

    const rollbackAvailability = Boolean(
      input.rollbackAvailable ||
      compensationAvailability === 'ROLLBACK_AVAILABLE' ||
      plan.compensationPlan?.availability === 'ROLLBACK_AVAILABLE'
    );

    // 4. Deterministic Safety Evaluation
    const safetyReasons: string[] = [];

    // --- A. Duplicate Side-Effect Risk ---
    let duplicateSideEffectRisk: 'NONE' | 'LOW' | 'MEDIUM' | 'HIGH' | 'CRITICAL' = 'LOW';

    if (idempotency === 'READ_ONLY') {
      duplicateSideEffectRisk = 'NONE';
      safetyReasons.push('READ_ONLY_OPERATION_NO_SIDE_EFFECT_RISK');
    } else if (confirmedSuccess) {
      duplicateSideEffectRisk = 'CRITICAL';
      safetyReasons.push('CONFIRMED_EXTERNAL_SUCCESS');
      safetyReasons.push('DUPLICATE_SIDE_EFFECT_RISK');
    } else if (idempotency === 'IDEMPOTENT') {
      if (dispatchState === 'NOT_DISPATCHED') {
        duplicateSideEffectRisk = 'LOW';
      } else {
        duplicateSideEffectRisk = 'MEDIUM';
      }
    } else if (idempotency === 'CONDITIONALLY_IDEMPOTENT') {
      if (input.conditionalConditionsMet === true) {
        duplicateSideEffectRisk = 'LOW';
        safetyReasons.push('CONDITIONAL_IDEMPOTENCY_CONDITIONS_SATISFIED');
      } else {
        duplicateSideEffectRisk = 'HIGH';
        safetyReasons.push('CONDITIONAL_IDEMPOTENCY_REQUIREMENTS_UNMET');
      }
    } else if (idempotency === 'NON_IDEMPOTENT') {
      if (dispatchState === 'NOT_DISPATCHED') {
        duplicateSideEffectRisk = 'MEDIUM';
        safetyReasons.push('NON_IDEMPOTENT_OPERATION');
      } else {
        duplicateSideEffectRisk = plan.riskLevel === 'CRITICAL' ? 'CRITICAL' : 'HIGH';
        safetyReasons.push('NON_IDEMPOTENT_OPERATION');
        safetyReasons.push('DUPLICATE_SIDE_EFFECT_RISK');
      }
    } else {
      // UNKNOWN idempotency
      if (dispatchState === 'NOT_DISPATCHED') {
        duplicateSideEffectRisk = 'MEDIUM';
        safetyReasons.push('UNKNOWN_IDEMPOTENCY');
      } else {
        duplicateSideEffectRisk = 'HIGH';
        safetyReasons.push('UNKNOWN_IDEMPOTENCY');
        safetyReasons.push('DUPLICATE_SIDE_EFFECT_RISK');
      }
    }

    // --- B. Reconciliation Requirement ---
    let reconciliationRequirement = false;

    if (confirmedSuccess) {
      // Authoritatively confirmed, no reconciliation probe needed to discover outcome
      reconciliationRequirement = false;
    } else if (
      classification === 'UNKNOWN_EXTERNAL_STATE' ||
      classification === 'RECONCILIATION' ||
      classification === 'STALE_STATE' ||
      proposedAction === 'RECONCILE'
    ) {
      reconciliationRequirement = true;
      if (classification === 'UNKNOWN_EXTERNAL_STATE') {
        safetyReasons.push('UNKNOWN_EXTERNAL_STATE_REQUIRES_RECONCILIATION');
      } else if (classification === 'STALE_STATE') {
        safetyReasons.push('STALE_STATE_REQUIRES_RECONCILIATION');
      } else {
        safetyReasons.push('RECONCILIATION_REQUIRED_AFTER_DISPATCH');
      }
    } else if (dispatchState !== 'NOT_DISPATCHED' && dispatchState !== 'EXTERNAL_CONFIRMATION_RECEIVED') {
      // Post-dispatch without confirmed success requires reconciliation
      reconciliationRequirement = true;
      if (!safetyReasons.includes('RECONCILIATION_REQUIRED_AFTER_DISPATCH')) {
        safetyReasons.push('RECONCILIATION_REQUIRED_AFTER_DISPATCH');
      }
    } else if (idempotency === 'NON_IDEMPOTENT' && dispatchState !== 'NOT_DISPATCHED') {
      reconciliationRequirement = true;
    } else if (idempotency === 'UNKNOWN' && dispatchState !== 'NOT_DISPATCHED') {
      reconciliationRequirement = true;
    }

    // --- C. Retry Permitted ---
    // Invariant: retryPermitted means safety analysis finds NO known duplicate-side-effect
    // or state uncertainty barrier preventing retry. It is NOT authorization.
    let retryPermitted = false;

    if (confirmedSuccess) {
      // Never replay already successful side effects
      retryPermitted = false;
    } else if (classification === 'POLICY') {
      // Policy denial is terminal; cannot retry to bypass policy
      retryPermitted = false;
      safetyReasons.push('POLICY_DENIAL_TERMINAL');
    } else if (classification === 'PERMANENT') {
      // Permanent 4xx errors will not succeed on blind retry
      retryPermitted = false;
      safetyReasons.push('PERMANENT_CLIENT_ERROR_NO_RETRY');
    } else if (reconciliationRequirement) {
      // Reconciliation barrier: must resolve external state before retry
      retryPermitted = false;
      safetyReasons.push('RECONCILIATION_BARRIER_PREVENTS_RETRY');
    } else if (idempotency === 'NON_IDEMPOTENT') {
      retryPermitted = false;
    } else if (idempotency === 'UNKNOWN') {
      retryPermitted = false;
    } else if (idempotency === 'CONDITIONALLY_IDEMPOTENT' && input.conditionalConditionsMet !== true) {
      retryPermitted = false;
    } else if (dispatchState !== 'NOT_DISPATCHED') {
      retryPermitted = false;
      safetyReasons.push('POST_DISPATCH_UNCERTAINTY_PREVENTS_RETRY');
    } else if (
      proposedAction === 'ABORT' ||
      proposedAction === 'WAIT' ||
      proposedAction === 'COMPENSATE' ||
      proposedAction === 'PAUSE' ||
      proposedAction === 'ROLLBACK'
    ) {
      retryPermitted = false;
    } else {
      // Safe retry conditions met:
      if (idempotency === 'READ_ONLY') {
        retryPermitted = true;
        safetyReasons.push('READ_ONLY_RETRY_SAFE');
      } else if (idempotency === 'IDEMPOTENT' && dispatchState === 'NOT_DISPATCHED') {
        retryPermitted = true;
        safetyReasons.push('PRE_DISPATCH_IDEMPOTENT_RETRY_SAFE');
      } else if (
        idempotency === 'CONDITIONALLY_IDEMPOTENT' &&
        input.conditionalConditionsMet === true &&
        dispatchState === 'NOT_DISPATCHED'
      ) {
        retryPermitted = true;
        safetyReasons.push('PRE_DISPATCH_CONDITIONAL_IDEMPOTENT_RETRY_SAFE');
      }
    }

    // --- D. Human Approval Required ---
    // Determined only from risk, failure classification, action, idempotency, partial execution.
    // Adversarial: Fake "approved=true" in untrusted input metadata CANNOT turn this off.
    let humanApprovalRequired = false;

    if (plan.approvalRequirement?.required === true) {
      humanApprovalRequired = true;
      safetyReasons.push('HUMAN_APPROVAL_REQUIRED');
    }
    if (classification === 'HUMAN_REQUIRED') {
      humanApprovalRequired = true;
      if (!safetyReasons.includes('HUMAN_APPROVAL_REQUIRED')) {
        safetyReasons.push('HUMAN_APPROVAL_REQUIRED');
      }
    }
    if (classification === 'PERMISSION') {
      // Cannot self-escalate connector permissions
      humanApprovalRequired = true;
      safetyReasons.push('PERMISSION_REVOCATION_REQUIRES_HUMAN_APPROVAL');
    }
    if (classification === 'AUTHORIZATION') {
      humanApprovalRequired = true;
      safetyReasons.push('AUTHORIZATION_FAILURE_REQUIRES_HUMAN_APPROVAL');
    }
    if (plan.riskLevel === 'CRITICAL') {
      humanApprovalRequired = true;
      safetyReasons.push('CRITICAL_RISK_REQUIRES_HUMAN_APPROVAL');
    }
    if (
      plan.riskLevel === 'HIGH' &&
      (partialExecutionDetected || proposedAction === 'COMPENSATE' || proposedAction === 'RESUME')
    ) {
      humanApprovalRequired = true;
      safetyReasons.push('HIGH_RISK_OPERATION_REQUIRES_HUMAN_APPROVAL');
    }
    if (
      idempotency === 'NON_IDEMPOTENT' &&
      dispatchState !== 'NOT_DISPATCHED' &&
      proposedAction !== 'ABORT' &&
      !confirmedSuccess
    ) {
      humanApprovalRequired = true;
      safetyReasons.push('NON_IDEMPOTENT_POST_DISPATCH_REQUIRES_HUMAN_APPROVAL');
    }

    // --- E. Partial Execution Context Rationale ---
    if (partialExecutionDetected) {
      safetyReasons.push('PARTIAL_EXECUTION_DETECTED');
    }

    // --- F. Compensation & Rollback Rationales ---
    if (compensationAvailability === 'COMPENSATION_AVAILABLE') {
      safetyReasons.push('COMPENSATION_AVAILABLE');
    }
    if (rollbackAvailability) {
      safetyReasons.push('ROLLBACK_AVAILABLE');
    }

    // Construct deterministic safety rationale (deduplicated)
    const uniqueReasons = Array.from(new Set(safetyReasons));
    const safetyRationale = uniqueReasons.length > 0 ? uniqueReasons.join('; ') : 'SAFE_TO_EVALUATE';

    // 5. Construct and Deeply Freeze RecoverySafetyAssessment
    return createRecoverySafetyAssessment({
      idempotencyClassification: idempotency,
      duplicateSideEffectRisk,
      reconciliationRequirement,
      partialExecutionDetected,
      completedSteps,
      incompleteSteps,
      compensationAvailability,
      rollbackAvailability,
      retryPermitted,
      humanApprovalRequired,
      safetyRationale,
    });
  }
}

export const recoverySafetyService = new RecoverySafetyService();
