/**
 * AryaOS V1 — Stage 23: Recovery Control Plane Orchestration & Governed Decision Surface
 *
 * Phase 8: Unifies the already implemented Stage 23 recovery capabilities into ONE
 * deterministic recovery-control decision surface.
 *
 * Integrates:
 * - Phase 1: Recovery contracts
 * - Phase 2: Failure classification (FailureClassificationService)
 * - Phase 3: Recovery planning (RecoveryPlanService)
 * - Phase 4: Recovery safety assessment (RecoverySafetyService)
 * - Phase 5: Reconciliation (RecoveryReconciliationService)
 * - Phase 6: Compensation (RecoveryCompensationService)
 * - Phase 7: Cascade detection & autonomous boundary protection (RecoveryCascadeService)
 *
 * ABSOLUTE BOUNDARIES:
 * - CONTROL PLANE ONLY: Zero direct execution, zero direct network calls (no fetch, Axios, raw sockets).
 * - Does NOT replace Stage 09 crash recovery, Stage 12 mission control, Stage 15 Action Bus,
 *   Stage 16 connector permissions, Stage 19 trigger engine, Stage 20 policy intelligence,
 *   Stage 21 governance control plane, or Stage 22 operational audit.
 * - Fail-closed: Never interpret uncertainty as permission.
 * - Precedence: System Safety > Unknown External State > Partial Execution > Cascade Containment
 *   > Governance > Reconciliation > Compensation > Stale State > Resource/Dependency > Transient Retry.
 * - Deterministic, bounded threshold evaluation: Zero LLM token consumption.
 */

import {
  RecoveryControlRequest,
  RecoveryControlDecision,
  RecoveryOutcome,
  RecoveryAction,
  FailureClassification,
  RecoveryControlLifecycleState,
  ClassificationEvidence,
  ClassificationResult,
  RecoveryPlan,
  RecoverySafetyAssessment,
  CascadeEvidence,
  CascadeRecord,
  CascadeContainmentDecision,
  CompensationAssessmentResult,
  MAX_RECOVERY_DEPTH,
  MAX_AUTOMATIC_RETRIES,
  MAX_RECONCILIATION_ATTEMPTS,
  MAX_CASCADE_DEPTH,
  MAX_CONCURRENT_AFFECTED_OPERATIONS,
} from '../types/recoveryControl';
import {
  createRecoveryControlDecision,
  validateAndSanitizePayload,
  RecoveryContractViolationError,
  deepFreeze,
  isRecoveryOutcome,
  isRecoveryControlLifecycleState,
} from './recoveryControl';
import { failureClassificationService } from './failureClassificationService';
import { recoveryPlanService } from './recoveryPlanService';
import { recoverySafetyService } from './recoverySafetyService';
import { recoveryReconciliationService } from './recoveryReconciliationService';
import { recoveryCompensationService } from './recoveryCompensationService';
import { recoveryCascadeService } from './recoveryCascadeService';
import { recoveryControlPersistenceService } from './recoveryControlPersistenceService';
import { policySnapshotService } from './policySnapshotService';
import { governanceControlPlane } from './governanceControlPlane';
import { governanceStalenessService } from './governanceStalenessService';
import { auditEventRegistry } from './auditEventRegistry';
import { operationalTruthService } from './operationalTruthService';
import { GovernanceRequest, GovernanceDecision, OperatorApprovalToken } from '../types/governanceControlPlane';
import { EpistemicStatus } from '../types/operationalAudit';

export class RecoveryControlPlane {
  private readonly activeDecisions: Map<string, RecoveryControlDecision> = new Map();
  private readonly requestDecisionMap: Map<string, string> = new Map();

  /**
   * Evaluates a bounded recovery context and produces a deterministic RecoveryControlDecision.
   * Coordinates classification, safety, cascade, reconciliation, compensation, and governance.
   * ZERO direct execution or transport bypass.
   */
  public evaluateRecoveryControl(request: RecoveryControlRequest): Readonly<RecoveryControlDecision> {
    // ------------------------------------------------------------------------
    // 1. Mandatory Request Validation
    // ------------------------------------------------------------------------
    if (!request) {
      throw new RecoveryContractViolationError('RecoveryControlRequest is mandatory');
    }
    if (!request.requestId || typeof request.requestId !== 'string' || request.requestId.trim() === '') {
      throw new RecoveryContractViolationError('requestId is mandatory and cannot be empty');
    }
    if (!request.operationId || typeof request.operationId !== 'string' || request.operationId.trim() === '') {
      throw new RecoveryContractViolationError('operationId is mandatory and cannot be empty');
    }

    // ------------------------------------------------------------------------
    // 2. Security Sanitization & Hostile Input Defenses
    // ------------------------------------------------------------------------
    if (request.metadata) {
      validateAndSanitizePayload(request.metadata);
    }
    if (request.parameters) {
      this.validateSecurityParameters(request.parameters);
      validateAndSanitizePayload(request.parameters);
    }
    if (request.visitedOperationIds && request.visitedOperationIds.length > MAX_CONCURRENT_AFFECTED_OPERATIONS) {
      throw new RecoveryContractViolationError(
        `Visited operations count ${request.visitedOperationIds.length} exceeds safety limit of ${MAX_CONCURRENT_AFFECTED_OPERATIONS}`
      );
    }

    // Reject forged human approvals
    if (request.governanceContext?.approved === true) {
      if (request.governanceContext.actorType !== 'USER') {
        throw new RecoveryContractViolationError(
          `Invalid governance approval actor type '${request.governanceContext.actorType}'. Only authenticated human operators ('USER') can authorize recovery.`
        );
      }
      if (!request.governanceContext.actorId || request.governanceContext.actorId.trim() === '') {
        throw new RecoveryContractViolationError('Governance approval requires non-empty actorId');
      }
    }

    if (request.operatorApproval) {
      const approverUpper = request.operatorApproval.approvedBy?.toUpperCase() || '';
      if (
        approverUpper.includes('AGENT') ||
        approverUpper.includes('DAEMON') ||
        approverUpper.includes('SYSTEM') ||
        approverUpper.includes('BOT')
      ) {
        throw new RecoveryContractViolationError(
          `Invalid operator approval actor '${request.operatorApproval.approvedBy}'. Only authenticated human operators ('USER') can grant approval.`
        );
      }
      if (!request.operatorApproval.approvedBy || request.operatorApproval.approvedBy.trim() === '') {
        throw new RecoveryContractViolationError('Operator approval token requires valid approvedBy');
      }
    }

    // ------------------------------------------------------------------------
    // 3. Idempotency & Stability Check (Memory + Stage 09 Persistence)
    // ------------------------------------------------------------------------
    const existingDecisionId = this.requestDecisionMap.get(request.requestId);
    if (existingDecisionId) {
      const existing = this.activeDecisions.get(existingDecisionId);
      if (existing && existing.operationId === request.operationId) {
        return existing;
      }
    }

    const persisted = recoveryControlPersistenceService.loadControlDecisionByRequestId(request.requestId);
    if (persisted && persisted.operationId === request.operationId) {
      this.activeDecisions.set(persisted.decisionId, persisted);
      this.requestDecisionMap.set(request.requestId, persisted.decisionId);
      return persisted;
    }

    const causationId = request.causationId || request.operationId;
    const correlationId = request.correlationId || request.operationId;
    const timestamp = Date.now();
    const nonce = Math.random().toString(36).substring(2, 7);
    const decisionId = `rcdec_${request.operationId}_${timestamp}_${nonce}`;

    // Loop bounds extraction (counters cannot reset)
    const recoveryDepth = request.recoveryDepth ?? 1;
    const retryCount = request.retryCount ?? 0;
    const reconciliationAttempts = request.reconciliationAttempts ?? 0;
    const reasonCodes: string[] = [];
    const evidenceIds: string[] = [];
    const requiredAuthority: string[] = [];

    // Learning signals or memory facts can never assume authority
    if (
      (request.parameters as any)?.learningSignal ||
      (request.metadata as any)?.learningSignal ||
      (request.metadata as any)?.memoryFact
    ) {
      reasonCodes.push('LEARNING_SIGNAL_NOT_AUTHORITY');
    }

    // ------------------------------------------------------------------------
    // 4. PRECEDENCE 1: System Safety & Recursion Bounds Protection
    // ------------------------------------------------------------------------
    if (recoveryDepth >= MAX_RECOVERY_DEPTH) {
      reasonCodes.push('RECOVERY_DEPTH_LIMIT_REACHED');
      evidenceIds.push(`ev_depth_${recoveryDepth}`);
      requiredAuthority.push('RECOVERY_GOVERNANCE', 'HUMAN_APPROVAL');

      return this.finalizeDecision({
        decisionId,
        requestId: request.requestId,
        operationId: request.operationId,
        classification: 'SYSTEM_INTERRUPTION',
        recoveryOutcome: 'ESCALATE',
        recommendedAction: 'WAIT',
        requiredAuthority,
        riskLevel: 'HIGH',
        epistemicStatus: 'OBSERVED',
        reasonCodes,
        evidenceIds,
        causationId,
        correlationId,
        recoveryDepth,
        retryCount,
        reconciliationAttempts,
        governanceRequirement: {
          required: true,
          humanOperatorRequired: true,
          reason: 'Recovery recursion depth limit reached; autonomous recovery escalated to human operator.',
        },
      }, request);
    }

    if (reconciliationAttempts >= MAX_RECONCILIATION_ATTEMPTS) {
      reasonCodes.push('MAX_RECONCILIATION_ATTEMPTS_EXCEEDED');
      evidenceIds.push(`ev_reconcile_${reconciliationAttempts}`);
      requiredAuthority.push('RECONCILIATION_ADMINISTRATION', 'HUMAN_APPROVAL');

      return this.finalizeDecision({
        decisionId,
        requestId: request.requestId,
        operationId: request.operationId,
        classification: 'UNKNOWN_EXTERNAL_STATE',
        recoveryOutcome: 'ESCALATE',
        recommendedAction: 'WAIT',
        requiredAuthority,
        riskLevel: 'HIGH',
        epistemicStatus: 'UNKNOWN',
        reasonCodes,
        evidenceIds,
        causationId,
        correlationId,
        recoveryDepth,
        retryCount,
        reconciliationAttempts,
        governanceRequirement: {
          required: true,
          humanOperatorRequired: true,
          reason: 'Max reconciliation probes exhausted without state resolution; operator escalation required.',
        },
      }, request);
    }

    if (retryCount >= MAX_AUTOMATIC_RETRIES) {
      reasonCodes.push('AUTOMATIC_RETRY_LIMIT_EXCEEDED');
      evidenceIds.push(`ev_retry_${retryCount}`);
      requiredAuthority.push('RECOVERY_GOVERNANCE', 'HUMAN_APPROVAL');

      return this.finalizeDecision({
        decisionId,
        requestId: request.requestId,
        operationId: request.operationId,
        classification: 'TRANSIENT',
        recoveryOutcome: 'ESCALATE',
        recommendedAction: 'WAIT',
        requiredAuthority,
        riskLevel: 'HIGH',
        epistemicStatus: 'OBSERVED',
        reasonCodes,
        evidenceIds,
        causationId,
        correlationId,
        recoveryDepth,
        retryCount,
        reconciliationAttempts,
        governanceRequirement: {
          required: true,
          humanOperatorRequired: true,
          reason: 'Automatic retry limit exceeded; escalated to human operator.',
        },
      }, request);
    }

    // ------------------------------------------------------------------------
    // 5. Special Case: Confirmed Success / No Recovery Required (Section 17)
    // ------------------------------------------------------------------------
    if (request.confirmedSuccess === true || request.operationalTruth === 'SUCCEEDED') {
      reasonCodes.push('OPERATION_CONFIRMED_SUCCESSFUL', 'NO_RECOVERY_REQUIRED');
      evidenceIds.push(`ev_success_${request.operationId}`);

      return this.finalizeDecision({
        decisionId,
        requestId: request.requestId,
        operationId: request.operationId,
        classification: 'SYSTEM_INTERRUPTION',
        recoveryOutcome: 'NO_RECOVERY_REQUIRED',
        recommendedAction: 'WAIT',
        requiredAuthority: [],
        riskLevel: 'LOW',
        epistemicStatus: 'CONFIRMED',
        reasonCodes,
        evidenceIds,
        causationId,
        correlationId,
        recoveryDepth,
        retryCount,
        reconciliationAttempts,
        originalOperationId: request.originalOperationId ?? request.operationId,
        recoveryPlanId: request.recoveryPlanId,
        governanceRequirement: {
          required: false,
          humanOperatorRequired: false,
          reason: 'Operation confirmed successful; no recovery intervention required.',
        },
      }, request);
    }

    // ------------------------------------------------------------------------
    // 6. Subsystem Coordination: Classification (Phase 2)
    // ------------------------------------------------------------------------
    let classificationResult: ClassificationResult;
    if (request.failureEvidence) {
      const evidenceToClassify: ClassificationEvidence = {
        ...request.failureEvidence,
        dispatchState: request.failureEvidence.dispatchState ?? request.dispatchState!,
      };
      classificationResult = failureClassificationService.classifyFailure(evidenceToClassify);
    } else {
      classificationResult = {
        classification: 'SYSTEM_INTERRUPTION',
        reasonCode: 'SYSTEM_INTERRUPTION',
        epistemicStatus: 'OBSERVED',
        explanation: 'Default operational classification from control plane context',
        evidenceReferences: [`ev_default_${request.operationId}`],
        causationId,
        correlationId,
        classifiedAt: timestamp,
      };
    }
    evidenceIds.push(...classificationResult.evidenceReferences);

    // ------------------------------------------------------------------------
    // 7. Subsystem Coordination: Cascade Detection (Phase 7)
    // ------------------------------------------------------------------------
    const cascadeEvidence: CascadeEvidence = request.cascadeEvidence ?? {
      rootOperationId: request.operationId,
      rootFailureClassification: classificationResult.classification,
      failureCount: retryCount + 1,
      sameClassFailures: retryCount + 1,
      recoveryChainDepth: recoveryDepth,
      unknownStateCount: reconciliationAttempts,
      staleApproval: request.governanceContext?.stale,
      stalePolicy: request.governanceContext?.stale,
      unknownGovernance: request.governanceContext?.unknown,
      causationId,
      correlationId,
      metadata: request.metadata,
    };

    const cascadeRecord = recoveryCascadeService.detectCascade(cascadeEvidence);
    let containmentDecision: CascadeContainmentDecision | undefined;
    if (cascadeRecord.cascadeClass !== 'NO_CASCADE') {
      containmentDecision = recoveryCascadeService.formulateContainmentDecision(cascadeRecord);
      evidenceIds.push(`ev_cascade_${cascadeRecord.cascadeId}`);
      reasonCodes.push(`CASCADE_${cascadeRecord.cascadeClass}`, `CONTROL_${cascadeRecord.containmentAction}`);
    }

    // ------------------------------------------------------------------------
    // 8. Subsystem Coordination: Compensation Assessment (Phase 6)
    // ------------------------------------------------------------------------
    let compensationAssessment: CompensationAssessmentResult | undefined;
    const hasCompletedSteps = Boolean(request.failureEvidence?.partialExecutionEvidence?.completedSteps?.length);
    if (hasCompletedSteps || request.capabilityId) {
      compensationAssessment = recoveryCompensationService.assessCompensation({
        originalOperationId: request.operationId,
        originalActionId: request.actionId,
        capabilityId: request.capabilityId || 'filesystem.write',
        operation: request.operation,
        parameters: request.parameters ? { ...request.parameters } : undefined,
        dispatchState: request.dispatchState,
        confirmedSuccess: request.confirmedSuccess,
        partialExecution: request.failureEvidence?.partialExecutionEvidence,
        recoveryDepth: request.compensationDepth ?? 1,
        visitedOperationIds: request.visitedOperationIds,
        causationId,
        correlationId,
      });
      if (compensationAssessment && compensationAssessment.candidatePlan) {
        evidenceIds.push(`ev_comp_${compensationAssessment.candidatePlan.compensationId}`);
      }
    }

    // ------------------------------------------------------------------------
    // 9. Subsystem Coordination: Recovery Plan Generation (Phase 3)
    // ------------------------------------------------------------------------
    const recoveryPlan = recoveryPlanService.generateRecoveryPlan({
      originalOperationId: request.operationId,
      classificationResult,
      dispatchState: request.dispatchState || 'NOT_DISPATCHED',
      idempotency: request.idempotency || 'UNKNOWN',
      riskLevel: request.riskLevel || 'MEDIUM',
      confirmedSuccess: request.confirmedSuccess,
      partialExecution: request.failureEvidence?.partialExecutionEvidence,
      compensationInfo: compensationAssessment?.candidatePlan
        ? {
            availability: 'COMPENSATION_AVAILABLE',
            compensatingActionType: compensationAssessment.candidatePlan.compensatingCapability,
            parameters: compensationAssessment.candidatePlan.compensationParameters as Record<string, unknown>,
          }
        : undefined,
      causationId,
      correlationId,
      metadata: request.metadata,
    });
    evidenceIds.push(`ev_plan_${recoveryPlan.originalOperationId}`);

    // ------------------------------------------------------------------------
    // 10. Subsystem Coordination: Recovery Safety Assessment (Phase 4)
    // ------------------------------------------------------------------------
    const safetyAssessment = recoverySafetyService.assessSafety({
      plan: recoveryPlan,
      evidence: request.failureEvidence,
      idempotency: request.idempotency,
      partialExecution: request.failureEvidence?.partialExecutionEvidence,
      confirmedSuccess: request.confirmedSuccess,
      metadata: request.metadata,
    });
    evidenceIds.push(`ev_safety_${safetyAssessment.assessmentTimestamp}`);

    // ------------------------------------------------------------------------
    // 11. Subsystem Coordination: Reconciliation Formulation (Phase 5)
    // ------------------------------------------------------------------------
    const isReconciliationNeeded =
      recoveryPlan.reconciliationRequirement.required ||
      safetyAssessment.reconciliationRequirement ||
      compensationAssessment?.requiresReconciliation === true;

    // ------------------------------------------------------------------------
    // 12. DETERMINISTIC DECISION PRECEDENCE SYNTHESIS (Section 7)
    // ------------------------------------------------------------------------
    let recoveryOutcome: RecoveryOutcome = 'UNKNOWN';
    let recommendedAction: RecoveryAction = recoveryPlan.proposedRecoveryAction;
    let riskLevel = request.riskLevel || recoveryPlan.riskLevel || 'MEDIUM';
    let epistemicStatus = classificationResult.epistemicStatus || 'OBSERVED';
    let humanOperatorRequired = false;
    let governanceRequired = false;
    let governanceReason = 'Routine automated recovery under baseline policy.';

    // --- Precedence 2: Unknown External State (Section 8) ---
    const isPostDispatch =
      request.dispatchState === 'DISPATCHED' ||
      request.dispatchState === 'EXECUTING' ||
      request.dispatchState === 'EXTERNAL_CONFIRMATION_ABSENT' ||
      request.operationalTruth === 'DISPATCHED';

    const hasReconciliationDiscrepancy = Boolean(
      request.failureEvidence?.reconciliationEvidence?.attempted &&
      !request.failureEvidence?.reconciliationEvidence?.matched
    );

    if (
      !hasCompletedSteps &&
      (classificationResult.classification === 'UNKNOWN_EXTERNAL_STATE' ||
        (isPostDispatch && !request.externalConfirmationReceived && !request.confirmedSuccess) ||
        hasReconciliationDiscrepancy)
    ) {
      epistemicStatus = 'UNKNOWN';
      reasonCodes.push('UNKNOWN_EXTERNAL_STATE_DETECTED');
      if (hasReconciliationDiscrepancy) {
        reasonCodes.push('RECONCILIATION_DISCREPANCY_DETECTED');
      }

      if (riskLevel === 'CRITICAL') {
        recoveryOutcome = 'REQUIRE_APPROVAL';
        recommendedAction = 'REQUIRE_APPROVAL';
        humanOperatorRequired = true;
        governanceRequired = true;
        governanceReason = 'Critical operation dispatched but external state unconfirmed; operator signoff required.';
      } else {
        recoveryOutcome = 'RECONCILE';
        recommendedAction = 'RECONCILE';
        reasonCodes.push('RECONCILIATION_MANDATED_BEFORE_RETRY');
      }
    }

    // --- Precedence 3: Partial Execution (Section 9) ---
    else if (hasCompletedSteps) {
      reasonCodes.push('PARTIAL_EXECUTION_STEPS_PRESERVED');

      if (compensationAssessment && compensationAssessment.eligibility === 'COMPENSATION_ELIGIBLE') {
        if (compensationAssessment.requiresHumanApproval) {
          recoveryOutcome = 'REQUIRE_APPROVAL';
          recommendedAction = 'REQUIRE_APPROVAL';
          humanOperatorRequired = true;
          governanceRequired = true;
          governanceReason = 'Partial execution requires human-governed compensation action.';
        } else {
          recoveryOutcome = 'COMPENSATE';
          recommendedAction = 'COMPENSATE';
        }
      } else if (compensationAssessment && compensationAssessment.eligibility === 'COMPENSATION_REQUIRES_RECONCILIATION') {
        recoveryOutcome = 'RECONCILE';
        recommendedAction = 'RECONCILE';
      } else if (compensationAssessment && compensationAssessment.eligibility === 'COMPENSATION_UNAVAILABLE') {
        recoveryOutcome = 'ESCALATE';
        recommendedAction = 'WAIT';
        humanOperatorRequired = true;
        governanceRequired = true;
        governanceReason = 'Partial execution cannot be safely compensated; escalation required.';
      } else {
        recoveryOutcome = 'RESUME';
        recommendedAction = 'RESUME';
      }
    }

    // --- Precedence 4: Cascade Containment Override (Section 10) ---
    if (cascadeRecord.cascadeClass !== 'NO_CASCADE') {
      const containment = cascadeRecord.containmentAction;
      reasonCodes.push(`CASCADE_OVERRIDE_${containment}`);

      if (containment === 'ABORT') {
        recoveryOutcome = 'ABORT';
        recommendedAction = 'ABORT';
        humanOperatorRequired = true;
        governanceRequired = true;
        riskLevel = 'HIGH';
        governanceReason = `Cascade containment action '${containment}' mandates immediate termination.`;
      } else if (containment === 'PAUSE') {
        recoveryOutcome = 'PAUSE';
        recommendedAction = 'PAUSE';
        humanOperatorRequired = true;
        governanceRequired = true;
        riskLevel = 'HIGH';
        governanceReason = `Cascade containment action '${containment}' mandates execution pause.`;
      } else if (containment === 'ISOLATE') {
        recoveryOutcome = 'ABORT';
        recommendedAction = 'ABORT';
        humanOperatorRequired = true;
        governanceRequired = true;
        riskLevel = 'HIGH';
        governanceReason = `Connector/provider quarantine (${containment}) mandates aborting operation.`;
      } else if (containment === 'REQUIRE_APPROVAL') {
        recoveryOutcome = 'REQUIRE_APPROVAL';
        recommendedAction = 'REQUIRE_APPROVAL';
        humanOperatorRequired = true;
        governanceRequired = true;
        riskLevel = 'HIGH';
        governanceReason = 'Cascade boundary protection mandates explicit operator approval.';
      } else if (containment === 'ESCALATE') {
        recoveryOutcome = 'ESCALATE';
        recommendedAction = 'ESCALATE';
        humanOperatorRequired = true;
        governanceRequired = true;
        riskLevel = 'HIGH';
        governanceReason = 'Cascade escalation boundary triggered.';
      } else if (containment === 'DEFER') {
        recoveryOutcome = 'WAIT';
        recommendedAction = 'WAIT';
      } else if (containment === 'THROTTLE') {
        recoveryOutcome = 'WAIT';
        recommendedAction = 'WAIT';
      }
    }

    // ------------------------------------------------------------------------
    const activeSnapshot =
      (request.operatorApproval?.policySnapshotId && policySnapshotService.getSnapshot(request.operatorApproval.policySnapshotId)) ||
      (request.policySnapshotId && policySnapshotService.getSnapshot(request.policySnapshotId)) ||
      policySnapshotService.captureSnapshot();
    let policyMismatchDetected = false;
    if (request.policyVersion !== undefined && request.policyVersion !== activeSnapshot.registryVersion) {
      policyMismatchDetected = true;
      reasonCodes.push('POLICY_VERSION_MISMATCH_DRIFT');
    }
    if (request.policySnapshotId && request.policySnapshotId !== activeSnapshot.snapshotId) {
      policyMismatchDetected = true;
      reasonCodes.push('POLICY_SNAPSHOT_MISMATCH_DRIFT');
    }

    let approvalTokenValid = false;
    let approvalTokenStale = false;
    let approvalIdentity: string | undefined = undefined;
    if (request.operatorApproval) {
      const token = request.operatorApproval;
      approvalIdentity = token.approvedBy;
      const now = Date.now();
      const MAX_TTL_MS = 300000; // 5 minutes
      if (token.approvedAt && (now - token.approvedAt > MAX_TTL_MS)) {
        approvalTokenStale = true;
        reasonCodes.push('APPROVAL_TOKEN_EXPIRED');
      }
      if (token.requestId !== request.requestId) {
        approvalTokenStale = true;
        reasonCodes.push('APPROVAL_TOKEN_REQUEST_MISMATCH');
      }
      if (token.policySnapshotId && token.policySnapshotId !== activeSnapshot.snapshotId) {
        approvalTokenStale = true;
        reasonCodes.push('APPROVAL_TOKEN_SNAPSHOT_MISMATCH');
      }
      if (!approvalTokenStale) {
        approvalTokenValid = true;
        reasonCodes.push('OPERATOR_APPROVAL_VERIFIED');
      }
    }

    // Formulate Stage 21 GovernanceRequest
    const govRequest: GovernanceRequest = {
      requestId: request.requestId,
      targetSystem: request.capabilityId || 'recovery.control',
      actor: {
        actorId: request.operatorApproval?.approvedBy || request.governanceContext?.actorId || 'recovery-system',
        actorType: (request.operatorApproval ? 'USER' : (request.governanceContext?.actorType as any)) || 'SYSTEM',
      },
      capabilityId: request.capabilityId || 'recovery.control',
      actionType: request.operation || recoveryPlan.proposedRecoveryAction,
      parameters: (request.parameters as Record<string, unknown>) || {},
      riskLevel: (riskLevel as any) || 'MEDIUM',
      missionId: request.missionId,
      goalId: request.goalId,
      correlationId,
      timestamp: request.createdAt ?? Date.now(),
    };

    let govDecision: GovernanceDecision | undefined;
    try {
      govDecision = governanceControlPlane.evaluateGovernance(govRequest, {
        snapshot: activeSnapshot,
        operatorApproval: approvalTokenValid ? request.operatorApproval : undefined,
        epistemicStatus: epistemicStatus as any,
      });
    } catch {
      govDecision = undefined;
    }

    if (govDecision) {
      evidenceIds.push(`ev_gov_${govDecision.decisionId}`);
      if (govDecision.matchedPolicies && govDecision.matchedPolicies.length > 0) {
        evidenceIds.push(...govDecision.matchedPolicies.map((p) => `ev_pol_${p}`));
      }
    }

    const winningPolicy = govDecision?.winningPolicyId
      ? activeSnapshot.policies.find((p) => p.policyId === govDecision.winningPolicyId)
      : undefined;
    const winningPolicyEffect = winningPolicy?.effect?.type;

    // --- Precedence 5: Governance / Authorization Requirements (Section 15) ---
    if (
      policyMismatchDetected ||
      approvalTokenStale ||
      (govDecision && govDecision.staleness && govDecision.staleness.isStale)
    ) {
      if (
        recoveryOutcome !== 'ABORT' &&
        recoveryOutcome !== 'PAUSE' &&
        recoveryOutcome !== 'ESCALATE'
      ) {
        recoveryOutcome = 'REQUIRE_APPROVAL';
        recommendedAction = 'REQUIRE_APPROVAL';
      }
      humanOperatorRequired = true;
      governanceRequired = true;
      reasonCodes.push('GOVERNANCE_STALE_OR_DRIFT');
      governanceReason = 'Policy drift or stale governance detected; human operator re-authorization required.';
    } else if (govDecision?.authorityIntersection?.effectiveStatus === 'MISSING_PERMISSION') {
      if (
        recoveryOutcome !== 'ABORT' &&
        recoveryOutcome !== 'PAUSE' &&
        recoveryOutcome !== 'ESCALATE'
      ) {
        recoveryOutcome = 'REQUIRE_APPROVAL';
        recommendedAction = 'REQUIRE_APPROVAL';
      }
      humanOperatorRequired = true;
      governanceRequired = true;
      reasonCodes.push('CONNECTOR_PERMISSION_MISSING');
      governanceReason = `Missing connector permission: ${govDecision.authorityIntersection.blockingReasons.join(', ')}`;
    } else if (winningPolicyEffect === 'PAUSE' || govDecision?.decision === 'PAUSE') {
      recoveryOutcome = 'PAUSE';
      recommendedAction = 'PAUSE';
      humanOperatorRequired = true;
      governanceRequired = true;
      reasonCodes.push('GOVERNANCE_PAUSE_REQUIRED');
      governanceReason = winningPolicy?.effect?.reason || govDecision?.reason || 'Policy requires pause';
    } else if (
      winningPolicyEffect === 'REQUIRE_APPROVAL' ||
      govDecision?.decision === 'REQUIRE_APPROVAL' ||
      govDecision?.decision === 'REQUIRE_REVIEW'
    ) {
      if (
        recoveryOutcome !== 'ABORT' &&
        recoveryOutcome !== 'PAUSE' &&
        recoveryOutcome !== 'ESCALATE' &&
        recoveryOutcome !== 'RECONCILE'
      ) {
        recoveryOutcome = 'REQUIRE_APPROVAL';
        recommendedAction = 'REQUIRE_APPROVAL';
      }
      humanOperatorRequired = true;
      governanceRequired = true;
      reasonCodes.push('GOVERNANCE_APPROVAL_REQUIRED');
      governanceReason = winningPolicy?.effect?.reason || govDecision?.reason || 'Policy requires human approval';
    } else if (winningPolicyEffect === 'DENY' || govDecision?.decision === 'DENY') {
      recoveryOutcome = 'ABORT';
      recommendedAction = 'ABORT';
      humanOperatorRequired = true;
      governanceRequired = true;
      reasonCodes.push('GOVERNANCE_POLICY_DENIED');
      governanceReason = winningPolicy?.effect?.reason || govDecision?.reason || 'Policy denied recovery action';
    } else if (govDecision?.authorityIntersection?.effectiveStatus === 'MISSION_CONSTRAINT_BLOCKED') {
      recoveryOutcome = 'PAUSE';
      recommendedAction = 'PAUSE';
      humanOperatorRequired = true;
      governanceRequired = true;
      reasonCodes.push('MISSION_CONSTRAINT_BLOCKED');
      governanceReason = `Mission constraints prohibit recovery action: ${govDecision.authorityIntersection.blockingReasons.join(', ')}`;
    } else if (
      request.governanceContext?.stale === true ||
      request.governanceContext?.unknown === true ||
      safetyAssessment.humanApprovalRequired ||
      recoveryPlan.approvalRequirement.required
    ) {
      if (approvalTokenValid) {
        humanOperatorRequired = false;
        governanceRequired = false;
        governanceReason = `Operator approval verified: ${request.operatorApproval?.approvedBy}`;
        reasonCodes.push('OPERATOR_APPROVAL_VERIFIED');
      } else {
        if (
          request.governanceContext?.stale === true ||
          request.governanceContext?.unknown === true ||
          riskLevel === 'CRITICAL' ||
          (recoveryOutcome !== 'ABORT' &&
            recoveryOutcome !== 'PAUSE' &&
            recoveryOutcome !== 'ESCALATE' &&
            recoveryOutcome !== 'RECONCILE')
        ) {
          recoveryOutcome = 'REQUIRE_APPROVAL';
          recommendedAction = 'REQUIRE_APPROVAL';
        }
        humanOperatorRequired = true;
        governanceRequired = true;
        governanceReason = request.governanceContext?.stale
          ? 'Governance context is stale; operator re-authorization required.'
          : request.governanceContext?.unknown
          ? 'Governance context is uncertain; fail-closed gate triggered.'
          : 'High-risk or destructive recovery action requires Stage 21 human operator approval.';
      }
    }

    // --- Precedence 6: Reconciliation Requirement ---
    if (recoveryOutcome === 'UNKNOWN' && isReconciliationNeeded) {
      recoveryOutcome = 'RECONCILE';
      recommendedAction = 'RECONCILE';
      reasonCodes.push('RECONCILIATION_REQUIRED');
    }

    // --- Precedence 7: Compensation Requirement ---
    if (recoveryOutcome === 'UNKNOWN' && recoveryPlan.proposedRecoveryAction === 'COMPENSATE') {
      recoveryOutcome = 'COMPENSATE';
      recommendedAction = 'COMPENSATE';
    }

    // --- Precedence 8: Stale State ---
    if (recoveryOutcome === 'UNKNOWN' && classificationResult.classification === 'STALE_STATE') {
      recoveryOutcome = 'RECONCILE';
      recommendedAction = 'RECONCILE';
      reasonCodes.push('STALE_STATE_RECONCILIATION_REQUIRED');
    }

    // --- Precedence 9: Resource / Dependency ---
    if (recoveryOutcome === 'UNKNOWN' && classificationResult.classification === 'RESOURCE') {
      recoveryOutcome = 'WAIT';
      recommendedAction = 'WAIT';
      reasonCodes.push('RESOURCE_EXHAUSTION_THROTTLE');
    } else if (recoveryOutcome === 'UNKNOWN' && classificationResult.classification === 'DEPENDENCY') {
      recoveryOutcome = 'WAIT';
      recommendedAction = 'WAIT';
      reasonCodes.push('DEPENDENCY_DEFER');
    }

    // --- Precedence 10: Transient Retry ---
    if (recoveryOutcome === 'UNKNOWN' && classificationResult.classification === 'TRANSIENT') {
      if (safetyAssessment.retryPermitted && retryCount < MAX_AUTOMATIC_RETRIES) {
        recoveryOutcome = 'RETRY';
        recommendedAction = 'RETRY';
        reasonCodes.push('SAFE_TRANSIENT_RETRY_PERMITTED');
      } else if (safetyAssessment.duplicateSideEffectRisk !== 'NONE' && safetyAssessment.duplicateSideEffectRisk !== 'LOW') {
        recoveryOutcome = 'RECONCILE';
        recommendedAction = 'RECONCILE';
        reasonCodes.push('UNSAFE_RETRY_FALLBACK_TO_RECONCILE');
      } else {
        recoveryOutcome = 'ESCALATE';
        recommendedAction = 'WAIT';
        humanOperatorRequired = true;
        governanceRequired = true;
        reasonCodes.push('AUTOMATIC_RETRY_LIMIT_EXCEEDED');
      }
    }

    // --- Precedence 11: Policy / Permanent / Fallback ---
    if (recoveryOutcome === 'UNKNOWN') {
      if (classificationResult.classification === 'POLICY') {
        recoveryOutcome = 'ABORT';
        recommendedAction = 'ABORT';
        reasonCodes.push('POLICY_VIOLATION_ABORT');
      } else if (classificationResult.classification === 'PERMISSION') {
        recoveryOutcome = 'REQUIRE_APPROVAL';
        recommendedAction = 'REQUIRE_APPROVAL';
        humanOperatorRequired = true;
        governanceRequired = true;
        reasonCodes.push('PERMISSION_REVOCATION_REQUIRE_APPROVAL');
      } else if (classificationResult.classification === 'PERMANENT') {
        recoveryOutcome = 'ABORT';
        recommendedAction = 'ABORT';
        reasonCodes.push('PERMANENT_FAILURE_ABORT');
      } else {
        recoveryOutcome = 'RESUME';
        recommendedAction = 'RESUME';
        reasonCodes.push('DEFAULT_RESUME');
      }
    }

    // Safety override: if safety assessment disallows retry and outcome is RETRY, convert to RECONCILE or ESCALATE
    if (!safetyAssessment.retryPermitted && recoveryOutcome === 'RETRY') {
      if (safetyAssessment.reconciliationRequirement || isPostDispatch) {
        recoveryOutcome = 'RECONCILE';
        recommendedAction = 'RECONCILE';
        reasonCodes.push('SAFETY_OVERRIDE_RETRY_TO_RECONCILE');
      } else {
        recoveryOutcome = 'ESCALATE';
        recommendedAction = 'WAIT';
        humanOperatorRequired = true;
        governanceRequired = true;
        reasonCodes.push('SAFETY_OVERRIDE_UNSAFE_RECOVERY');
      }
    }

    // Epistemic safety override: if external state is UNKNOWN and outcome is RETRY, block blind retry
    if (epistemicStatus === 'UNKNOWN' && recoveryOutcome === 'RETRY') {
      recoveryOutcome = 'RECONCILE';
      recommendedAction = 'RECONCILE';
      reasonCodes.push('UNKNOWN_STATE_BLOCKS_RETRY_TO_RECONCILE');
    }

    requiredAuthority.push(...recoveryPlan.requiredAuthority);
    if (containmentDecision) {
      requiredAuthority.push(...containmentDecision.requiredAuthority);
    }
    if (govDecision?.authorityIntersection?.requiredAuthority) {
      requiredAuthority.push(...govDecision.authorityIntersection.requiredAuthority);
    }
    const uniqueAuthority = Array.from(new Set(requiredAuthority));

    return this.finalizeDecision({
      decisionId,
      requestId: request.requestId,
      operationId: request.operationId,
      classification: classificationResult.classification,
      recoveryOutcome,
      recommendedAction,
      safetyAssessment,
      reconciliationRequirement: isReconciliationNeeded
        ? {
            required: true,
            reason: recoveryPlan.reconciliationRequirement.probeType || 'Operational state reconciliation needed',
            timeoutMs: recoveryPlan.reconciliationRequirement.timeoutMs || 10000,
          }
        : undefined,
      compensationAssessment,
      cascadeAssessment: cascadeRecord,
      containmentDecision,
      governanceRequirement: {
        required: governanceRequired,
        humanOperatorRequired,
        reason: governanceReason,
        stale: request.governanceContext?.stale || Boolean(policyMismatchDetected || approvalTokenStale),
      },
      requiredAuthority: uniqueAuthority,
      riskLevel,
      epistemicStatus,
      reasonCodes,
      evidenceIds,
      causationId,
      correlationId,
      recoveryDepth,
      retryCount,
      reconciliationAttempts,
      policySnapshotId: activeSnapshot.snapshotId,
      policyVersion: activeSnapshot.registryVersion,
      governanceDecisionId: govDecision?.decisionId,
      governanceDecision: govDecision,
      recoveryPlanId: request.recoveryPlanId ?? recoveryPlan.recoveryPlanId,
      recoveryAttemptId: `attempt_${request.operationId}_${recoveryDepth}_${retryCount}`,
      reconciliationId: request.reconciliationId,
      compensationId: request.compensationId ?? compensationAssessment?.candidatePlan?.compensationId,
      originalOperationId: request.originalOperationId ?? request.operationId,
      approvalIdentity: approvalIdentity ?? (request.governanceContext?.actorType === 'USER' ? request.governanceContext.actorId : undefined),
      metadata: request.metadata,
    }, request);
  }

  /**
   * Transitions a RecoveryControlDecision through its deterministic lifecycle states.
   * Enforces illegal transition rejections.
   */
  public transitionDecisionLifecycle(
    decision: RecoveryControlDecision,
    nextState: RecoveryControlLifecycleState
  ): Readonly<RecoveryControlDecision> {
    if (!decision) {
      throw new RecoveryContractViolationError('RecoveryControlDecision is mandatory');
    }
    if (!isRecoveryControlLifecycleState(nextState)) {
      throw new RecoveryContractViolationError(`Invalid RecoveryControlLifecycleState '${nextState}'`);
    }

    const validTransitions: Record<RecoveryControlLifecycleState, readonly RecoveryControlLifecycleState[]> = {
      RECEIVED: ['VALIDATED', 'REJECTED', 'EXPIRED'],
      VALIDATED: ['CLASSIFIED', 'REJECTED', 'EXPIRED'],
      CLASSIFIED: ['ASSESSED', 'REJECTED', 'EXPIRED'],
      ASSESSED: ['PLANNED', 'GOVERNANCE_REQUIRED', 'DECIDED', 'ESCALATED', 'REJECTED', 'EXPIRED'],
      PLANNED: ['GOVERNANCE_REQUIRED', 'DECIDED', 'ESCALATED', 'REJECTED', 'EXPIRED'],
      GOVERNANCE_REQUIRED: ['DECIDED', 'ESCALATED', 'REJECTED', 'EXPIRED'],
      DECIDED: ['ESCALATED'],
      REJECTED: [], // Terminal
      EXPIRED: [],  // Terminal
      ESCALATED: [],// Terminal
      UNKNOWN: [],  // Terminal
    };

    const allowed = validTransitions[decision.lifecycleState] || [];
    if (!allowed.includes(nextState)) {
      throw new RecoveryContractViolationError(
        `Illegal recovery control decision lifecycle transition from '${decision.lifecycleState}' to '${nextState}'`
      );
    }

    const updated: RecoveryControlDecision = {
      ...decision,
      lifecycleState: nextState,
    };

    const frozen = deepFreeze(updated);
    this.activeDecisions.set(decision.decisionId, frozen);
    recoveryControlPersistenceService.persistControlDecision(frozen);
    return frozen;
  }

  public getActiveDecision(decisionId: string): RecoveryControlDecision | undefined {
    return this.activeDecisions.get(decisionId);
  }

  public clear(): void {
    this.activeDecisions.clear();
    this.requestDecisionMap.clear();
  }

  public initFromPersistence(): void {
    const all = recoveryControlPersistenceService.recoverAllPersistedDecisions();
    for (const d of all) {
      this.activeDecisions.set(d.decisionId, d);
      this.requestDecisionMap.set(d.requestId, d.decisionId);
    }
  }

  private finalizeDecision(
    params: import('./recoveryControl').CreateRecoveryControlDecisionParams,
    request?: RecoveryControlRequest
  ): Readonly<RecoveryControlDecision> {
    const enrichedParams = {
      ...params,
      actionId: params.actionId ?? request?.actionId,
      missionId: params.missionId ?? request?.missionId,
      goalId: params.goalId ?? request?.goalId,
      originalOperationId: params.originalOperationId ?? request?.originalOperationId ?? params.operationId,
      recoveryPlanId: params.recoveryPlanId ?? request?.recoveryPlanId,
      policySnapshotId: params.policySnapshotId ?? request?.policySnapshotId,
      policyVersion: params.policyVersion ?? request?.policyVersion,
      reconciliationId: params.reconciliationId ?? request?.reconciliationId,
      compensationId: params.compensationId ?? request?.compensationId,
      approvalIdentity:
        params.approvalIdentity ??
        request?.operatorApproval?.approvedBy ??
        (request?.governanceContext?.actorType === 'USER' ? request.governanceContext.actorId : undefined),
    };
    const decision = createRecoveryControlDecision(enrichedParams);
    this.activeDecisions.set(decision.decisionId, decision);
    this.requestDecisionMap.set(decision.requestId, decision.decisionId);
    recoveryControlPersistenceService.persistControlDecision(decision, request);

    // Stage 22 Operational Audit Integration: Record canonical audit event
    try {
      auditEventRegistry.recordEvent({
        operationId: decision.operationId,
        correlationId: decision.correlationId,
        causationId: decision.causationId,
        parentOperationId: decision.originalOperationId,
        eventType: 'GOVERNANCE_DECIDED',
        lifecycleState: decision.lifecycleState === 'DECIDED' ? 'GOVERNED' : 'UNKNOWN',
        epistemicStatus: (decision.epistemicStatus as any) || 'UNKNOWN',
        sourceSystem: 'stage23_recovery_control',
        actor: {
          actorId: decision.approvalIdentity || 'stage23_recovery_control_plane',
          actorType: decision.approvalIdentity ? 'USER' : 'SYSTEM',
        },
        actionId: decision.actionId,
        missionId: decision.missionId,
        goalId: decision.goalId,
        policySnapshotId: decision.policySnapshotId,
        policyVersion: decision.policyVersion,
        governanceDecisionId: decision.governanceDecisionId,
        riskLevel: decision.riskLevel as any,
        reason: decision.reasonCodes.join('; '),
        parameters: {
          outcome: decision.recoveryOutcome,
          action: decision.recommendedAction,
          classification: decision.classification,
        },
        output: {
          decisionId: decision.decisionId,
          recoveryOutcome: decision.recoveryOutcome,
          recommendedAction: decision.recommendedAction,
          lifecycleState: decision.lifecycleState,
        },
        evidenceReferences: [...decision.evidenceIds],
      });
    } catch {
      // Non-blocking in case of formatting variations, preserving audit logging
    }

    return decision;
  }

  private validateSecurityParameters(params: Record<string, unknown>): void {
    const forbiddenKeys = ['token', 'secret', 'password', 'authorization', 'apiKey', 'privateKey', 'authHeader'];
    for (const [key, value] of Object.entries(params)) {
      if (forbiddenKeys.some((f) => key.toLowerCase().includes(f.toLowerCase()))) {
        throw new RecoveryContractViolationError(
          `Security violation: Parameter '${key}' contains prohibited sensitive credential field`
        );
      }
      if (typeof value === 'string') {
        if (value.startsWith('http://') || value.startsWith('https://')) {
          throw new RecoveryContractViolationError(
            `Security violation: Arbitrary URL parameter '${value}' is rejected; external calls must use registered capabilities`
          );
        }
      }
    }
  }
}

export const recoveryControlPlane = new RecoveryControlPlane();
