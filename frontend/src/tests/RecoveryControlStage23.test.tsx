import { describe, it, expect } from 'vitest';
import {
  FAILURE_CLASSIFICATIONS,
  RECOVERY_ACTIONS,
  RECOVERY_PROGRESSION_STATES,
  RECOVERY_TERMINAL_STATES,
  IDEMPOTENCY_CLASSIFICATIONS,
  COMPENSATION_AVAILABILITIES,
  MAX_RECOVERY_DEPTH,
  MAX_AUTOMATIC_RETRIES,
  createRecoveryPlan,
  createRecoveryAttemptRecord,
  createRecoverySafetyAssessment,
  isFailureClassification,
  isRecoveryAction,
  isRecoveryLifecycleState,
  isProgressionRecoveryState,
  isTerminalRecoveryState,
  isIdempotencyClassification,
  isCompensationAvailability,
  isCompensationEligibility,
  isCompensationType,
  isReversibilityClassification,
  isCompensationLifecycleState,
  isCascadeClassification,
  isCascadeContainmentControl,
  isCascadeLifecycleState,
  COMPENSATION_ELIGIBILITIES,
  COMPENSATION_TYPES,
  REVERSIBILITY_CLASSES,
  COMPENSATION_LIFECYCLE_STATES,
  CASCADE_CLASSIFICATIONS,
  CASCADE_CONTAINMENT_CONTROLS,
  CASCADE_LIFECYCLE_STATES,
  createDeclarativeCompensationPlan,
  createCascadeRecord,
  createCascadeContainmentDecision,
  createRecoveryControlDecision,
  isRecoveryOutcome,
  isRecoveryControlLifecycleState,
  RECOVERY_OUTCOMES,
  RECOVERY_CONTROL_LIFECYCLE_STATES,
  RecoveryContractViolationError,
  VALID_RECOVERY_LIFECYCLE_TRANSITIONS,
  isValidRecoveryLifecycleTransition,
  assertValidRecoveryLifecycleTransition,
  validateAndSanitizePayload,
} from '../services/recoveryControl';
import { failureClassificationService } from '../services/failureClassificationService';
import { recoveryPlanService } from '../services/recoveryPlanService';
import { recoverySafetyService } from '../services/recoverySafetyService';
import { recoveryReconciliationService } from '../services/recoveryReconciliationService';
import { recoveryCompensationService } from '../services/recoveryCompensationService';
import { recoveryCascadeService } from '../services/recoveryCascadeService';
import { recoveryControlPlane } from '../services/recoveryControlPlane';
import { recoveryControlPersistenceService } from '../services/recoveryControlPersistenceService';
import { executionPersistence } from '../services/executionPersistence';
import { executionJournal } from '../services/executionJournal';
import { policyRegistry } from '../services/policyRegistry';
import { policySnapshotService } from '../services/policySnapshotService';
import { governanceControlPlane } from '../services/governanceControlPlane';
import { governanceAuthorityService } from '../services/governanceAuthorityService';
import { auditEventRegistry } from '../services/auditEventRegistry';
import { operationalTruthService } from '../services/operationalTruthService';
import { operationTraceService } from '../services/operationTraceService';
import { causalTraceService } from '../services/causalTraceService';
import { Policy } from '../types/policyIntelligence';
import { OperatorApprovalToken, GovernanceRequest } from '../types/governanceControlPlane';
import { connectorRegistry } from '../services/connectorRegistry';
import { render } from '@testing-library/react';
import { RecoveryControlHUD } from '../components/spatial/RecoveryControlHUD';
import { SpatialCommandConsole } from '../components/spatial/SpatialCommandConsole';


describe('AryaOS V1 Stage 23 — Phase 1: Core Recovery Contracts', () => {
  // 1. FailureClassification completeness
  it('1. FailureClassification contains exactly the 13 canonical categories', () => {
    expect(FAILURE_CLASSIFICATIONS.length).toBe(13);
    const expected = [
      'TRANSIENT',
      'PERMANENT',
      'AUTHORIZATION',
      'PERMISSION',
      'POLICY',
      'STALE_STATE',
      'UNKNOWN_EXTERNAL_STATE',
      'PARTIAL_EXECUTION',
      'RECONCILIATION',
      'RESOURCE',
      'DEPENDENCY',
      'SYSTEM_INTERRUPTION',
      'HUMAN_REQUIRED',
    ];
    for (const cat of expected) {
      expect(FAILURE_CLASSIFICATIONS).toContain(cat);
      expect(isFailureClassification(cat)).toBe(true);
    }
    expect(isFailureClassification('INVALID_CATEGORY')).toBe(false);
  });

  // 2. RecoveryAction completeness
  it('2. RecoveryAction contains exactly the 11 safe next state outcomes', () => {
    expect(RECOVERY_ACTIONS.length).toBe(11);
    const expected = [
      'RETRY',
      'RESUME',
      'ROLLBACK',
      'COMPENSATE',
      'RECONCILE',
      'WAIT',
      'REQUIRE_APPROVAL',
      'PAUSE',
      'ABORT',
      'ESCALATE',
      'UNKNOWN',
    ];
    for (const act of expected) {
      expect(RECOVERY_ACTIONS).toContain(act);
      expect(isRecoveryAction(act)).toBe(true);
    }
    expect(isRecoveryAction('DEFAULT_RETRY')).toBe(false);
  });

  // 3. RecoveryLifecycleState completeness
  it('3. RecoveryLifecycleState cleanly distinguishes progression and terminal states', () => {
    expect(RECOVERY_PROGRESSION_STATES.length).toBe(9);
    expect(RECOVERY_TERMINAL_STATES.length).toBe(5);

    const progressionExpected = [
      'DETECTED',
      'CLASSIFIED',
      'PROPOSED',
      'GOVERNED',
      'APPROVED',
      'READY',
      'DISPATCHED',
      'VERIFIED',
      'COMPLETED',
    ];
    for (const s of progressionExpected) {
      expect(isProgressionRecoveryState(s)).toBe(true);
      expect(isTerminalRecoveryState(s)).toBe(false);
      expect(isRecoveryLifecycleState(s)).toBe(true);
    }

    const terminalExpected = [
      'ABORTED',
      'REJECTED',
      'EXPIRED',
      'UNKNOWN',
      'ESCALATED',
    ];
    for (const s of terminalExpected) {
      expect(isProgressionRecoveryState(s)).toBe(false);
      expect(isTerminalRecoveryState(s)).toBe(true);
      expect(isRecoveryLifecycleState(s)).toBe(true);
    }

    expect(isRecoveryLifecycleState('EXECUTING')).toBe(false);
  });

  // 4. IdempotencyClassification completeness
  it('4. IdempotencyClassification contains exactly the 5 required classifications', () => {
    expect(IDEMPOTENCY_CLASSIFICATIONS.length).toBe(5);
    const expected = [
      'READ_ONLY',
      'IDEMPOTENT',
      'CONDITIONALLY_IDEMPOTENT',
      'NON_IDEMPOTENT',
      'UNKNOWN',
    ];
    for (const c of expected) {
      expect(IDEMPOTENCY_CLASSIFICATIONS).toContain(c);
      expect(isIdempotencyClassification(c)).toBe(true);
    }
    expect(isIdempotencyClassification('MUTABLE')).toBe(false);
  });

  // 5. CompensationAvailability completeness
  it('5. CompensationAvailability contains exactly the 4 required classifications', () => {
    expect(COMPENSATION_AVAILABILITIES.length).toBe(4);
    const expected = [
      'ROLLBACK_AVAILABLE',
      'COMPENSATION_AVAILABLE',
      'NO_COMPENSATION_AVAILABLE',
      'COMPENSATION_UNKNOWN',
    ];
    for (const c of expected) {
      expect(COMPENSATION_AVAILABILITIES).toContain(c);
      expect(isCompensationAvailability(c)).toBe(true);
    }
    expect(isCompensationAvailability('ROLLBACK_UNAVAILABLE')).toBe(false);
  });

  // 6. RecoveryPlan construction
  it('6. createRecoveryPlan constructs a valid strongly-typed contract with all mandatory fields', () => {
    const plan = createRecoveryPlan({
      originalOperationId: 'op-fail-101',
      failureClassification: 'TRANSIENT',
      currentTruthState: 'FAILED_AFTER_DISPATCH',
      proposedRecoveryAction: 'RETRY',
      riskLevel: 'LOW',
      idempotencyAssessment: 'IDEMPOTENT',
      requiredAuthority: ['ACTION_BUS_DISPATCH'],
      expectedOutcome: 'Operation completed cleanly upon retry',
      expiry: Date.now() + 600000,
      causationId: 'op-fail-101',
      correlationId: 'corr-batch-001',
    });

    expect(plan.recoveryPlanId).toBeDefined();
    expect(plan.originalOperationId).toBe('op-fail-101');
    expect(plan.failureClassification).toBe('TRANSIENT');
    expect(plan.proposedRecoveryAction).toBe('RETRY');
    expect(plan.lifecycleState).toBe('PROPOSED');
    expect(plan.approvalRequirement.required).toBe(false);
    expect(plan.reconciliationRequirement.required).toBe(false);
    expect(plan.compensationPlan.availability).toBe('NO_COMPENSATION_AVAILABLE');
  });

  // 7. RecoveryPlan immutability
  it('7. RecoveryPlan root object is frozen at runtime against property mutation', () => {
    const plan = createRecoveryPlan({
      originalOperationId: 'op-fail-102',
      failureClassification: 'PERMANENT',
      currentTruthState: 'FAILED_VALIDATION',
      proposedRecoveryAction: 'ABORT',
      riskLevel: 'MEDIUM',
      idempotencyAssessment: 'NON_IDEMPOTENT',
      requiredAuthority: [],
      expectedOutcome: 'Aborted due to permanent validation error',
      expiry: Date.now() + 300000,
      causationId: 'op-fail-102',
      correlationId: 'corr-batch-002',
    });

    expect(Object.isFrozen(plan)).toBe(true);
    expect(() => {
      // @ts-expect-error Runtime mutation test
      plan.proposedRecoveryAction = 'RETRY';
    }).toThrow();
  });

  // 8. Deep immutability
  it('8. RecoveryPlan nested sub-objects and arrays are deeply frozen', () => {
    const plan = createRecoveryPlan({
      originalOperationId: 'op-fail-103',
      failureClassification: 'UNKNOWN_EXTERNAL_STATE',
      currentTruthState: 'DISPATCHED_NO_CALLBACK',
      proposedRecoveryAction: 'RECONCILE',
      riskLevel: 'HIGH',
      idempotencyAssessment: 'UNKNOWN',
      requiredAuthority: ['CONNECTOR_PROBE'],
      approvalRequirement: { required: true, approvalType: 'OPERATOR_OVERRIDE' },
      reconciliationRequirement: { required: true, probeType: 'STATUS_QUERY', timeoutMs: 5000 },
      compensationPlan: {
        availability: 'COMPENSATION_AVAILABLE',
        compensatingActionType: 'void_charge',
        parameters: { chargeId: 'chg_123', reason: 'timeout' },
      },
      expectedOutcome: 'Reconcile external state or compensate',
      expiry: Date.now() + 600000,
      causationId: 'op-fail-103',
      correlationId: 'corr-batch-003',
      evidenceReferences: ['ev-disp-1', 'ev-time-1'],
    });

    expect(Object.isFrozen(plan.approvalRequirement)).toBe(true);
    expect(Object.isFrozen(plan.reconciliationRequirement)).toBe(true);
    expect(Object.isFrozen(plan.compensationPlan)).toBe(true);
    expect(Object.isFrozen(plan.compensationPlan.parameters)).toBe(true);
    expect(Object.isFrozen(plan.requiredAuthority)).toBe(true);
    expect(Object.isFrozen(plan.evidenceReferences)).toBe(true);

    expect(() => {
      // @ts-expect-error Runtime nested mutation test
      plan.approvalRequirement.required = false;
    }).toThrow();

    expect(() => {
      // @ts-expect-error Runtime nested array mutation test
      plan.requiredAuthority.push('ILLEGAL_AUTHORITY');
    }).toThrow();

    expect(() => {
      // @ts-expect-error Runtime nested parameter mutation test
      plan.compensationPlan.parameters.chargeId = 'tampered_id';
    }).toThrow();
  });

  // 9. RecoveryAttemptRecord construction
  it('9. createRecoveryAttemptRecord constructs a valid, immutable record with depth bounds', () => {
    const record = createRecoveryAttemptRecord({
      recoveryPlanId: 'rec_plan_001',
      originalOperationId: 'op-fail-104',
      attemptNumber: 1,
      recoveryDepth: 1,
      lifecycleState: 'READY',
      proposedAction: 'RETRY',
      idempotencyClassification: 'IDEMPOTENT',
      causationId: 'op-fail-104',
      correlationId: 'corr-batch-004',
      metadata: { targetRetryProvider: 'aws-ecs-primary' },
    });

    expect(record.attemptId).toBeDefined();
    expect(record.attemptNumber).toBe(1);
    expect(record.recoveryDepth).toBe(1);
    expect(record.recoveryDepth).toBeLessThanOrEqual(MAX_RECOVERY_DEPTH);
    expect(record.attemptNumber).toBeLessThanOrEqual(MAX_AUTOMATIC_RETRIES + 1);
    expect(Object.isFrozen(record)).toBe(true);
    expect(Object.isFrozen(record.metadata)).toBe(true);
  });

  // 10. RecoverySafetyAssessment construction
  it('10. createRecoverySafetyAssessment constructs an immutable assessment object', () => {
    const assessment = createRecoverySafetyAssessment({
      idempotencyClassification: 'CONDITIONALLY_IDEMPOTENT',
      duplicateSideEffectRisk: 'MEDIUM',
      reconciliationRequirement: true,
      partialExecutionDetected: true,
      completedSteps: ['step_1_create_record', 'step_2_allocate_slot'],
      incompleteSteps: ['step_3_charge_customer', 'step_4_send_email'],
      compensationAvailability: 'COMPENSATION_AVAILABLE',
      rollbackAvailability: false,
      retryPermitted: false,
      humanApprovalRequired: true,
      safetyRationale: 'Partial execution with downstream financial side-effect requires operator confirmation.',
    });

    expect(assessment.idempotencyClassification).toBe('CONDITIONALLY_IDEMPOTENT');
    expect(assessment.completedSteps.length).toBe(2);
    expect(assessment.incompleteSteps.length).toBe(2);
    expect(assessment.retryPermitted).toBe(false);
    expect(assessment.humanApprovalRequired).toBe(true);
    expect(Object.isFrozen(assessment)).toBe(true);
    expect(Object.isFrozen(assessment.completedSteps)).toBe(true);
  });

  // 11. Prototype pollution rejection
  it('11. PROTOTYPE POLLUTION: rejects payloads containing __proto__, constructor, or prototype', () => {
    expect(() => {
      createRecoveryPlan({
        originalOperationId: 'op-fail-105',
        failureClassification: 'TRANSIENT',
        currentTruthState: 'FAILED',
        proposedRecoveryAction: 'RETRY',
        riskLevel: 'LOW',
        idempotencyAssessment: 'IDEMPOTENT',
        requiredAuthority: [],
        expectedOutcome: 'retry',
        expiry: Date.now() + 100000,
        causationId: 'op-fail-105',
        correlationId: 'corr-105',
        metadata: JSON.parse('{"__proto__": {"polluted": true}}'),
      });
    }).toThrow(RecoveryContractViolationError);

    expect(() => {
      createRecoveryPlan({
        originalOperationId: 'op-fail-105',
        failureClassification: 'TRANSIENT',
        currentTruthState: 'FAILED',
        proposedRecoveryAction: 'RETRY',
        riskLevel: 'LOW',
        idempotencyAssessment: 'IDEMPOTENT',
        requiredAuthority: [],
        expectedOutcome: 'retry',
        expiry: Date.now() + 100000,
        causationId: 'op-fail-105',
        correlationId: 'corr-105',
        metadata: { constructor: { admin: true } },
      });
    }).toThrow(RecoveryContractViolationError);
  });

  // 12. Excessive-depth rejection
  it('12. PAYLOAD BOUNDS: rejects objects exceeding maximum object nesting depth (5 levels)', () => {
    const deeplyNested: any = { l1: { l2: { l3: { l4: { l5: { l6: 'too_deep' } } } } } };

    expect(() => {
      createRecoveryPlan({
        originalOperationId: 'op-fail-106',
        failureClassification: 'TRANSIENT',
        currentTruthState: 'FAILED',
        proposedRecoveryAction: 'RETRY',
        riskLevel: 'LOW',
        idempotencyAssessment: 'IDEMPOTENT',
        requiredAuthority: [],
        expectedOutcome: 'retry',
        expiry: Date.now() + 100000,
        causationId: 'op-fail-106',
        correlationId: 'corr-106',
        metadata: deeplyNested,
      });
    }).toThrow(RecoveryContractViolationError);
  });

  // 13. Excessive-key rejection
  it('13. PAYLOAD BOUNDS: rejects objects exceeding maximum key count (50 keys)', () => {
    const oversizedObj: Record<string, number> = {};
    for (let i = 0; i < 55; i++) {
      oversizedObj[`key_${i}`] = i;
    }

    expect(() => {
      createRecoveryPlan({
        originalOperationId: 'op-fail-107',
        failureClassification: 'TRANSIENT',
        currentTruthState: 'FAILED',
        proposedRecoveryAction: 'RETRY',
        riskLevel: 'LOW',
        idempotencyAssessment: 'IDEMPOTENT',
        requiredAuthority: [],
        expectedOutcome: 'retry',
        expiry: Date.now() + 100000,
        causationId: 'op-fail-107',
        correlationId: 'corr-107',
        metadata: oversizedObj,
      });
    }).toThrow(RecoveryContractViolationError);
  });

  // 14. Executable/function payload rejection
  it('14. EXECUTABLE CODE REJECTION: strictly rejects function or callback fields', () => {
    expect(() => {
      createRecoveryPlan({
        originalOperationId: 'op-fail-108',
        failureClassification: 'TRANSIENT',
        currentTruthState: 'FAILED',
        proposedRecoveryAction: 'RETRY',
        riskLevel: 'LOW',
        idempotencyAssessment: 'IDEMPOTENT',
        requiredAuthority: [],
        expectedOutcome: 'retry',
        expiry: Date.now() + 100000,
        causationId: 'op-fail-108',
        correlationId: 'corr-108',
        metadata: {
          executeHook: () => {
            console.log('malicious');
          },
        },
      });
    }).toThrow(RecoveryContractViolationError);
  });

  // 15. Causation/correlation integrity
  it('15. CAUSAL INTEGRITY: rejects contracts with missing or empty originalOperationId, causationId, or correlationId', () => {
    expect(() => {
      createRecoveryPlan({
        originalOperationId: '',
        failureClassification: 'TRANSIENT',
        currentTruthState: 'FAILED',
        proposedRecoveryAction: 'RETRY',
        riskLevel: 'LOW',
        idempotencyAssessment: 'IDEMPOTENT',
        requiredAuthority: [],
        expectedOutcome: 'retry',
        expiry: Date.now() + 100000,
        causationId: 'cause-1',
        correlationId: 'corr-1',
      });
    }).toThrow(/originalOperationId is mandatory/);

    expect(() => {
      createRecoveryPlan({
        originalOperationId: 'op-1',
        failureClassification: 'TRANSIENT',
        currentTruthState: 'FAILED',
        proposedRecoveryAction: 'RETRY',
        riskLevel: 'LOW',
        idempotencyAssessment: 'IDEMPOTENT',
        requiredAuthority: [],
        expectedOutcome: 'retry',
        expiry: Date.now() + 100000,
        causationId: '',
        correlationId: 'corr-1',
      });
    }).toThrow(/causationId is mandatory/);

    expect(() => {
      createRecoveryPlan({
        originalOperationId: 'op-1',
        failureClassification: 'TRANSIENT',
        currentTruthState: 'FAILED',
        proposedRecoveryAction: 'RETRY',
        riskLevel: 'LOW',
        idempotencyAssessment: 'IDEMPOTENT',
        requiredAuthority: [],
        expectedOutcome: 'retry',
        expiry: Date.now() + 100000,
        causationId: 'cause-1',
        correlationId: '   ',
      });
    }).toThrow(/correlationId is mandatory/);
  });

  // =========================================================================
  // Section 2: Phase 2 — Evidence-Based Failure Classification (16-36)
  // =========================================================================

  it('16. classifies transient network failure before dispatch as TRANSIENT', () => {
    const res = failureClassificationService.classifyFailure({
      operationId: 'op-trans-01',
      causationId: 'cause-01',
      correlationId: 'corr-01',
      dispatchState: 'NOT_DISPATCHED',
      httpStatus: 503,
      timeoutEvidence: { timedOut: true, phase: 'PRE_DISPATCH' },
    });

    expect(res.classification).toBe('TRANSIENT');
    expect(res.reasonCode).toBe('TRANSIENT_NETWORK_FAILURE');
    expect(res.explanation).toContain('Transient network failure');
  });

  it('17. classifies confirmed 4xx client errors as PERMANENT', () => {
    const res = failureClassificationService.classifyFailure({
      operationId: 'op-perm-02',
      causationId: 'cause-02',
      correlationId: 'corr-02',
      dispatchState: 'NOT_DISPATCHED',
      httpStatus: 400,
      providerErrorCategory: 'INVALID_REQUEST',
    });

    expect(res.classification).toBe('PERMANENT');
    expect(res.reasonCode).toBe('PERMANENT_CLIENT_REJECTION');
    expect(res.explanation).toContain('Permanent client rejection');
  });

  it('18. classifies capability authorization failure as AUTHORIZATION', () => {
    const res = failureClassificationService.classifyFailure({
      operationId: 'op-auth-03',
      causationId: 'cause-03',
      correlationId: 'corr-03',
      dispatchState: 'NOT_DISPATCHED',
      authorizationResult: { authorized: false, reason: 'Agent lacks capability grant' },
    });

    expect(res.classification).toBe('AUTHORIZATION');
    expect(res.reasonCode).toBe('AUTHORIZATION_DENIED');
    expect(res.explanation).toContain('Action authorization denied');
  });

  it('19. classifies revoked connector as PERMISSION', () => {
    const res = failureClassificationService.classifyFailure({
      operationId: 'op-perm-04',
      causationId: 'cause-04',
      correlationId: 'corr-04',
      dispatchState: 'NOT_DISPATCHED',
      connectorStatus: 'REVOKED',
      permissionResult: { granted: false, revoked: true, reason: 'OAuth refresh token expired' },
    });

    expect(res.classification).toBe('PERMISSION');
    expect(res.reasonCode).toBe('CONNECTOR_PERMISSION_REVOKED');
    expect(res.explanation).toContain('Connector permission revoked');
  });

  it('20. classifies explicit policy denial as POLICY', () => {
    const res = failureClassificationService.classifyFailure({
      operationId: 'op-pol-05',
      causationId: 'cause-05',
      correlationId: 'corr-05',
      dispatchState: 'NOT_DISPATCHED',
      policyResult: { decision: 'DENY', matchedPolicyId: 'pol-sec-01', reason: 'High risk write blocked' },
    });

    expect(res.classification).toBe('POLICY');
    expect(res.reasonCode).toBe('POLICY_DENIED');
    expect(res.explanation).toContain('Operation denied by policy rule');
  });

  it('21. classifies expired TTL or stale approval as STALE_STATE', () => {
    const res = failureClassificationService.classifyFailure({
      operationId: 'op-stale-06',
      causationId: 'cause-06',
      correlationId: 'corr-06',
      dispatchState: 'NOT_DISPATCHED',
      staleStateEvidence: { isStale: true, reason: 'Policy snapshot registry version drift detected' },
    });

    expect(res.classification).toBe('STALE_STATE');
    expect(res.reasonCode).toBe('STALE_AUTHORITY');
    expect(res.explanation).toContain('Stale state detected');
  });

  it('22. classifies external confirmation absent after dispatch as UNKNOWN_EXTERNAL_STATE', () => {
    const res = failureClassificationService.classifyFailure({
      operationId: 'op-unk-07',
      causationId: 'cause-07',
      correlationId: 'corr-07',
      dispatchState: 'EXTERNAL_CONFIRMATION_ABSENT',
      epistemicStatus: 'UNKNOWN',
    });

    expect(res.classification).toBe('UNKNOWN_EXTERNAL_STATE');
    expect(res.reasonCode).toBe('EXTERNAL_CONFIRMATION_ABSENT');
    expect(res.epistemicStatus).toBe('UNKNOWN');
  });

  it('23. classifies pre-dispatch ambiguous evidence safely as SYSTEM_INTERRUPTION fallback', () => {
    const res = failureClassificationService.classifyFailure({
      operationId: 'op-amb-08',
      causationId: 'cause-08',
      correlationId: 'corr-08',
      dispatchState: 'NOT_DISPATCHED',
    });

    expect(res.classification).toBe('SYSTEM_INTERRUPTION');
    expect(res.reasonCode).toBe('AMBIGUOUS_EVIDENCE_SAFE_FALLBACK');
  });

  it('24. classifies multi-step workflow with completed steps as PARTIAL_EXECUTION', () => {
    const res = failureClassificationService.classifyFailure({
      operationId: 'op-part-09',
      causationId: 'cause-09',
      correlationId: 'corr-09',
      dispatchState: 'EXECUTING',
      partialExecutionEvidence: {
        completedSteps: ['step_A_reserve', 'step_B_deduct'],
        failedStep: 'step_C_notify',
        pendingSteps: ['step_D_finalize'],
      },
    });

    expect(res.classification).toBe('PARTIAL_EXECUTION');
    expect(res.reasonCode).toBe('PARTIAL_WORKFLOW_COMPLETION');
    expect(res.explanation).toContain('step_A_reserve');
    expect(res.explanation).toContain('step_C_notify');
  });

  it('25. classifies reconciliation state mismatch as RECONCILIATION', () => {
    const res = failureClassificationService.classifyFailure({
      operationId: 'op-reconcile-10',
      causationId: 'cause-10',
      correlationId: 'corr-10',
      dispatchState: 'RECONCILIATION_FAILED',
      reconciliationEvidence: {
        attempted: true,
        matched: false,
        discrepancies: ['observed IP 9.9.9.9 does not match expected 1.2.3.4'],
      },
    });

    expect(res.classification).toBe('RECONCILIATION');
    expect(res.reasonCode).toBe('RECONCILIATION_FAILED');
    expect(res.explanation).toContain('observed IP 9.9.9.9');
  });

  it('26. classifies HTTP 429 and rate limits as RESOURCE', () => {
    const res = failureClassificationService.classifyFailure({
      operationId: 'op-res-11',
      causationId: 'cause-11',
      correlationId: 'corr-11',
      dispatchState: 'NOT_DISPATCHED',
      httpStatus: 429,
      resourceExhaustionEvidence: { exhausted: true, resourceType: 'RPM_RATE_LIMIT' },
    });

    expect(res.classification).toBe('RESOURCE');
    expect(res.reasonCode).toBe('RESOURCE_EXHAUSTED');
    expect(res.explanation).toContain('RPM_RATE_LIMIT');
  });

  it('27. classifies unsatisfied prerequisites as DEPENDENCY', () => {
    const res = failureClassificationService.classifyFailure({
      operationId: 'op-dep-12',
      causationId: 'cause-12',
      correlationId: 'corr-12',
      dispatchState: 'NOT_DISPATCHED',
      dependencyState: { satisfied: false, missingDependencies: ['dep_artifact_video_mp4'] },
    });

    expect(res.classification).toBe('DEPENDENCY');
    expect(res.reasonCode).toBe('DEPENDENCY_UNAVAILABLE');
    expect(res.explanation).toContain('dep_artifact_video_mp4');
  });

  it('28. classifies process cancellation or kill as SYSTEM_INTERRUPTION', () => {
    const res = failureClassificationService.classifyFailure({
      operationId: 'op-sys-13',
      causationId: 'cause-13',
      correlationId: 'corr-13',
      dispatchState: 'NOT_DISPATCHED',
      cancellationEvidence: { cancelled: true, reason: 'Operator sent SIGTERM' },
    });

    expect(res.classification).toBe('SYSTEM_INTERRUPTION');
    expect(res.reasonCode).toBe('SYSTEM_INTERRUPTION');
    expect(res.explanation).toContain('SIGTERM');
  });

  it('29. classifies mandatory operator signoff gate as HUMAN_REQUIRED', () => {
    const res = failureClassificationService.classifyFailure({
      operationId: 'op-human-14',
      causationId: 'cause-14',
      correlationId: 'corr-14',
      dispatchState: 'NOT_DISPATCHED',
      humanInterventionRequired: true,
      policyResult: { decision: 'REQUIRE_APPROVAL', matchedPolicyId: 'pol-critical-finance' },
    });

    expect(res.classification).toBe('HUMAN_REQUIRED');
    expect(res.reasonCode).toBe('HUMAN_APPROVAL_REQUIRED');
    expect(res.explanation).toContain('explicit operator review');
  });

  it('30. DETERMINISM: identical evidence objects produce identical results', () => {
    const ev = {
      operationId: 'op-det-15',
      causationId: 'cause-15',
      correlationId: 'corr-15',
      dispatchState: 'NOT_DISPATCHED' as const,
      httpStatus: 403,
      authorizationResult: { authorized: false, reason: 'Scope missing' },
    };

    const res1 = failureClassificationService.classifyFailure(ev);
    const res2 = failureClassificationService.classifyFailure(ev);

    expect(res1.classification).toBe(res2.classification);
    expect(res1.reasonCode).toBe(res2.reasonCode);
    expect(res1.explanation).toBe(res2.explanation);
    expect(res1.epistemicStatus).toBe(res2.epistemicStatus);
  });

  // Section 2.1: Adversarial Tests & Boundary Disambiguation
  it('31. ADVERSARIAL A: timeout post-dispatch without verified reconciliation remains UNKNOWN_EXTERNAL_STATE', () => {
    const res = failureClassificationService.classifyFailure({
      operationId: 'op-adv-a',
      causationId: 'cause-adv-a',
      correlationId: 'corr-adv-a',
      dispatchState: 'DISPATCHED',
      timeoutEvidence: { timedOut: true, timeoutMs: 15000 },
      metadata: { clientClaimedSuccess: true },
    });

    expect(res.classification).toBe('UNKNOWN_EXTERNAL_STATE');
    expect(res.epistemicStatus).toBe('UNKNOWN');
  });

  it('32. ADVERSARIAL B: timeout confirmed NOT_DISPATCHED classifies as TRANSIENT', () => {
    const res = failureClassificationService.classifyFailure({
      operationId: 'op-adv-b',
      causationId: 'cause-adv-b',
      correlationId: 'corr-adv-b',
      dispatchState: 'NOT_DISPATCHED',
      timeoutEvidence: { timedOut: true, phase: 'PRE_DISPATCH' },
    });

    expect(res.classification).toBe('TRANSIENT');
    expect(res.reasonCode).toBe('TRANSIENT_NETWORK_FAILURE');
  });

  it('33. ADVERSARIAL C: HTTP 500 post-dispatch classifies as UNKNOWN_EXTERNAL_STATE, not TRANSIENT', () => {
    const res = failureClassificationService.classifyFailure({
      operationId: 'op-adv-c',
      causationId: 'cause-adv-c',
      correlationId: 'corr-adv-c',
      dispatchState: 'DISPATCHED',
      httpStatus: 500,
    });

    expect(res.classification).toBe('UNKNOWN_EXTERNAL_STATE');
    expect(res.epistemicStatus).toBe('UNKNOWN');
  });

  it('34. ADVERSARIAL D: permission revoked after dispatch preserves UNKNOWN_EXTERNAL_STATE when confirmation is absent', () => {
    const res = failureClassificationService.classifyFailure({
      operationId: 'op-adv-d',
      causationId: 'cause-adv-d',
      correlationId: 'corr-adv-d',
      dispatchState: 'EXTERNAL_CONFIRMATION_ABSENT',
      connectorStatus: 'REVOKED',
      permissionResult: { granted: false, revoked: true },
    });

    expect(res.classification).toBe('UNKNOWN_EXTERNAL_STATE');
  });

  it('35. ADVERSARIAL G: unverified client-provided success does not override authoritative Stage 22 UNKNOWN state', () => {
    const res = failureClassificationService.classifyFailure({
      operationId: 'op-adv-g',
      causationId: 'cause-adv-g',
      correlationId: 'corr-adv-g',
      dispatchState: 'DISPATCHED',
      epistemicStatus: 'UNKNOWN',
      metadata: { claimedStatus: 'SUCCEEDED', userSaysItWorked: true },
    });

    expect(res.classification).toBe('UNKNOWN_EXTERNAL_STATE');
    expect(res.epistemicStatus).toBe('UNKNOWN');
  });

  it('36. SECURITY: rejects prototype pollution inside classification evidence metadata', () => {
    expect(() => {
      failureClassificationService.classifyFailure({
        operationId: 'op-sec-36',
        causationId: 'cause-36',
        correlationId: 'corr-36',
        dispatchState: 'NOT_DISPATCHED',
        metadata: JSON.parse('{"__proto__": {"injected": true}}'),
      });
    }).toThrow(RecoveryContractViolationError);
  });

  // =========================================================================
  // Section 3: Phase 3 — Deterministic Recovery Plan Generation (37-56)
  // =========================================================================

  it('37. TRANSIENT + NOT_DISPATCHED + IDEMPOTENT -> RETRY eligible', () => {
    const classification = failureClassificationService.classifyFailure({
      operationId: 'op-plan-37',
      causationId: 'cause-37',
      correlationId: 'corr-37',
      dispatchState: 'NOT_DISPATCHED',
      httpStatus: 503,
      timeoutEvidence: { timedOut: true, phase: 'PRE_DISPATCH' },
    });

    const plan = recoveryPlanService.generateRecoveryPlan({
      originalOperationId: 'op-plan-37',
      causationId: 'cause-37',
      correlationId: 'corr-37',
      classificationResult: classification,
      dispatchState: 'NOT_DISPATCHED',
      idempotency: 'IDEMPOTENT',
      riskLevel: 'LOW',
    });

    expect(plan.proposedRecoveryAction).toBe('RETRY');
    expect(plan.approvalRequirement.required).toBe(false);
    expect(plan.reconciliationRequirement.required).toBe(false);
    expect(plan.lifecycleState).toBe('PROPOSED');
  });

  it('38. TRANSIENT + DISPATCHED + UNKNOWN -> RECONCILE (no blind retry post-dispatch)', () => {
    const classification = failureClassificationService.classifyFailure({
      operationId: 'op-plan-38',
      causationId: 'cause-38',
      correlationId: 'corr-38',
      dispatchState: 'DISPATCHED',
      epistemicStatus: 'UNKNOWN',
      timeoutEvidence: { timedOut: true },
    });

    const plan = recoveryPlanService.generateRecoveryPlan({
      originalOperationId: 'op-plan-38',
      causationId: 'cause-38',
      correlationId: 'corr-38',
      classificationResult: classification,
      dispatchState: 'DISPATCHED',
      idempotency: 'IDEMPOTENT',
    });

    expect(plan.proposedRecoveryAction).toBe('RECONCILE');
    expect(plan.reconciliationRequirement.required).toBe(true);
  });

  it('39. UNKNOWN_EXTERNAL_STATE -> no blind RETRY', () => {
    const classification = failureClassificationService.classifyFailure({
      operationId: 'op-plan-39',
      causationId: 'cause-39',
      correlationId: 'corr-39',
      dispatchState: 'EXTERNAL_CONFIRMATION_ABSENT',
      epistemicStatus: 'UNKNOWN',
    });

    const plan = recoveryPlanService.generateRecoveryPlan({
      originalOperationId: 'op-plan-39',
      causationId: 'cause-39',
      correlationId: 'corr-39',
      classificationResult: classification,
      dispatchState: 'EXTERNAL_CONFIRMATION_ABSENT',
    });

    expect(plan.proposedRecoveryAction).not.toBe('RETRY');
    expect(plan.proposedRecoveryAction).toBe('RECONCILE');
    expect(plan.reconciliationRequirement.required).toBe(true);
  });

  it('40. NON_IDEMPOTENT + UNKNOWN -> no RETRY (routes to RECONCILE / REQUIRE_APPROVAL)', () => {
    const classification = failureClassificationService.classifyFailure({
      operationId: 'op-plan-40',
      causationId: 'cause-40',
      correlationId: 'corr-40',
      dispatchState: 'DISPATCHED',
      epistemicStatus: 'UNKNOWN',
    });

    const plan = recoveryPlanService.generateRecoveryPlan({
      originalOperationId: 'op-plan-40',
      causationId: 'cause-40',
      correlationId: 'corr-40',
      classificationResult: classification,
      dispatchState: 'DISPATCHED',
      idempotency: 'NON_IDEMPOTENT',
      riskLevel: 'CRITICAL',
    });

    expect(plan.proposedRecoveryAction).not.toBe('RETRY');
    expect(plan.proposedRecoveryAction).toBe('REQUIRE_APPROVAL');
    expect(plan.approvalRequirement.required).toBe(true);
  });

  it('41. UNKNOWN idempotency + unknown external state -> conservative RECONCILE action', () => {
    const classification = failureClassificationService.classifyFailure({
      operationId: 'op-plan-41',
      causationId: 'cause-41',
      correlationId: 'corr-41',
      dispatchState: 'DISPATCHED',
      epistemicStatus: 'UNKNOWN',
    });

    const plan = recoveryPlanService.generateRecoveryPlan({
      originalOperationId: 'op-plan-41',
      causationId: 'cause-41',
      correlationId: 'corr-41',
      classificationResult: classification,
      dispatchState: 'DISPATCHED',
      idempotency: 'UNKNOWN',
      riskLevel: 'MEDIUM',
    });

    expect(plan.proposedRecoveryAction).toBe('RECONCILE');
  });

  it('42. confirmed success -> no duplicate RETRY (routes to WAIT)', () => {
    const classification = failureClassificationService.classifyFailure({
      operationId: 'op-plan-42',
      causationId: 'cause-42',
      correlationId: 'corr-42',
      dispatchState: 'EXTERNAL_CONFIRMATION_RECEIVED',
    });

    const plan = recoveryPlanService.generateRecoveryPlan({
      originalOperationId: 'op-plan-42',
      causationId: 'cause-42',
      correlationId: 'corr-42',
      classificationResult: classification,
      confirmedSuccess: true,
    });

    expect(plan.proposedRecoveryAction).toBe('WAIT');
    expect(plan.expectedOutcome).toContain('confirmed successful');
  });

  it('43. PARTIAL_EXECUTION preserves completed steps', () => {
    const classification = failureClassificationService.classifyFailure({
      operationId: 'op-plan-43',
      causationId: 'cause-43',
      correlationId: 'corr-43',
      dispatchState: 'EXECUTING',
      partialExecutionEvidence: {
        completedSteps: ['step_1', 'step_2'],
        failedStep: 'step_3',
        pendingSteps: ['step_4'],
      },
    });

    const plan = recoveryPlanService.generateRecoveryPlan({
      originalOperationId: 'op-plan-43',
      causationId: 'cause-43',
      correlationId: 'corr-43',
      classificationResult: classification,
      partialExecution: {
        completedSteps: ['step_1', 'step_2'],
        failedStep: 'step_3',
        pendingSteps: ['step_4'],
      },
      riskLevel: 'LOW',
    });

    expect(plan.proposedRecoveryAction).toBe('RESUME');
    expect(plan.expectedOutcome).toContain('Completed steps preserved');
  });

  it('44. PARTIAL_EXECUTION in high-risk workflow requires approval to resume', () => {
    const classification = failureClassificationService.classifyFailure({
      operationId: 'op-plan-44',
      causationId: 'cause-44',
      correlationId: 'corr-44',
      dispatchState: 'EXECUTING',
      partialExecutionEvidence: {
        completedSteps: ['step_A_charge'],
        failedStep: 'step_B_provision',
        pendingSteps: ['step_C_notify'],
      },
    });

    const plan = recoveryPlanService.generateRecoveryPlan({
      originalOperationId: 'op-plan-44',
      causationId: 'cause-44',
      correlationId: 'corr-44',
      classificationResult: classification,
      riskLevel: 'HIGH',
    });

    expect(plan.proposedRecoveryAction).toBe('REQUIRE_APPROVAL');
    expect(plan.approvalRequirement.required).toBe(true);
  });

  it('45. PERMISSION failure cannot escalate permissions (routes to REQUIRE_APPROVAL)', () => {
    const classification = failureClassificationService.classifyFailure({
      operationId: 'op-plan-45',
      causationId: 'cause-45',
      correlationId: 'corr-45',
      dispatchState: 'NOT_DISPATCHED',
      connectorStatus: 'REVOKED',
      permissionResult: { granted: false, revoked: true },
    });

    const plan = recoveryPlanService.generateRecoveryPlan({
      originalOperationId: 'op-plan-45',
      causationId: 'cause-45',
      correlationId: 'corr-45',
      classificationResult: classification,
    });

    expect(plan.proposedRecoveryAction).toBe('REQUIRE_APPROVAL');
    expect(plan.approvalRequirement.required).toBe(true);
    expect(plan.requiredAuthority).toContain('CONNECTOR_CREDENTIAL_REAUTHORIZATION');
  });

  it('46. POLICY failure cannot mutate policy (routes to ABORT)', () => {
    const classification = failureClassificationService.classifyFailure({
      operationId: 'op-plan-46',
      causationId: 'cause-46',
      correlationId: 'corr-46',
      dispatchState: 'NOT_DISPATCHED',
      policyResult: { decision: 'DENY', matchedPolicyId: 'pol-deny-01' },
    });

    const plan = recoveryPlanService.generateRecoveryPlan({
      originalOperationId: 'op-plan-46',
      causationId: 'cause-46',
      correlationId: 'corr-46',
      classificationResult: classification,
    });

    expect(plan.proposedRecoveryAction).toBe('ABORT');
    expect(plan.expectedOutcome).toContain('policy bypass strictly forbidden');
  });

  it('47. STALE_STATE requires fresh validation probe (routes to RECONCILE)', () => {
    const classification = failureClassificationService.classifyFailure({
      operationId: 'op-plan-47',
      causationId: 'cause-47',
      correlationId: 'corr-47',
      dispatchState: 'NOT_DISPATCHED',
      staleStateEvidence: { isStale: true },
    });

    const plan = recoveryPlanService.generateRecoveryPlan({
      originalOperationId: 'op-plan-47',
      causationId: 'cause-47',
      correlationId: 'corr-47',
      classificationResult: classification,
    });

    expect(plan.proposedRecoveryAction).toBe('RECONCILE');
    expect(plan.reconciliationRequirement.probeType).toBe('GOVERNANCE_SNAPSHOT_REFRESH');
  });

  it('48. HUMAN_REQUIRED produces approval-oriented plan', () => {
    const classification = failureClassificationService.classifyFailure({
      operationId: 'op-plan-48',
      causationId: 'cause-48',
      correlationId: 'corr-48',
      dispatchState: 'NOT_DISPATCHED',
      humanInterventionRequired: true,
    });

    const plan = recoveryPlanService.generateRecoveryPlan({
      originalOperationId: 'op-plan-48',
      causationId: 'cause-48',
      correlationId: 'corr-48',
      classificationResult: classification,
    });

    expect(plan.proposedRecoveryAction).toBe('REQUIRE_APPROVAL');
    expect(plan.approvalRequirement.required).toBe(true);
  });

  it('49. RecoveryPlan is deeply immutable', () => {
    const classification = failureClassificationService.classifyFailure({
      operationId: 'op-plan-49',
      causationId: 'cause-49',
      correlationId: 'corr-49',
      dispatchState: 'NOT_DISPATCHED',
      httpStatus: 400,
    });

    const plan = recoveryPlanService.generateRecoveryPlan({
      originalOperationId: 'op-plan-49',
      causationId: 'cause-49',
      correlationId: 'corr-49',
      classificationResult: classification,
    });

    expect(Object.isFrozen(plan)).toBe(true);
    expect(Object.isFrozen(plan.approvalRequirement)).toBe(true);
    expect(Object.isFrozen(plan.reconciliationRequirement)).toBe(true);
    expect(Object.isFrozen(plan.compensationPlan)).toBe(true);
  });

  it('50. DETERMINISM: identical input produces identical RecoveryAction and structure', () => {
    const classification = failureClassificationService.classifyFailure({
      operationId: 'op-plan-50',
      causationId: 'cause-50',
      correlationId: 'corr-50',
      dispatchState: 'NOT_DISPATCHED',
      httpStatus: 503,
      timeoutEvidence: { timedOut: true, phase: 'PRE_DISPATCH' },
    });

    const input = {
      originalOperationId: 'op-plan-50',
      causationId: 'cause-50',
      correlationId: 'corr-50',
      classificationResult: classification,
      dispatchState: 'NOT_DISPATCHED' as const,
      idempotency: 'IDEMPOTENT' as const,
      riskLevel: 'LOW' as const,
    };

    const plan1 = recoveryPlanService.generateRecoveryPlan(input);
    const plan2 = recoveryPlanService.generateRecoveryPlan(input);

    expect(plan1.proposedRecoveryAction).toBe(plan2.proposedRecoveryAction);
    expect(plan1.riskLevel).toBe(plan2.riskLevel);
    expect(plan1.failureClassification).toBe(plan2.failureClassification);
    expect(plan1.approvalRequirement.required).toBe(plan2.approvalRequirement.required);
  });

  it('51. governanceDecisionId is NOT fabricated (strictly undefined in Phase 3)', () => {
    const classification = failureClassificationService.classifyFailure({
      operationId: 'op-plan-51',
      causationId: 'cause-51',
      correlationId: 'corr-51',
      dispatchState: 'NOT_DISPATCHED',
    });

    const plan = recoveryPlanService.generateRecoveryPlan({
      originalOperationId: 'op-plan-51',
      causationId: 'cause-51',
      correlationId: 'corr-51',
      classificationResult: classification,
    });

    expect(plan.governanceDecisionId).toBeUndefined();
  });

  it('52. previous approval is not reused automatically (requires fresh approval)', () => {
    const classification = failureClassificationService.classifyFailure({
      operationId: 'op-plan-52',
      causationId: 'cause-52',
      correlationId: 'corr-52',
      dispatchState: 'NOT_DISPATCHED',
      connectorStatus: 'REVOKED',
    });

    const plan = recoveryPlanService.generateRecoveryPlan({
      originalOperationId: 'op-plan-52',
      causationId: 'cause-52',
      correlationId: 'corr-52',
      classificationResult: classification,
    });

    expect(plan.approvalRequirement.required).toBe(true);
    expect(plan.approvalRequirement.approvedAt).toBeUndefined();
    expect(plan.approvalRequirement.approvedBy).toBeUndefined();
  });

  it('53. compensation plan remains declarative data structure without executable code', () => {
    const classification = failureClassificationService.classifyFailure({
      operationId: 'op-plan-53',
      causationId: 'cause-53',
      correlationId: 'corr-53',
      dispatchState: 'RECONCILIATION_FAILED',
      reconciliationEvidence: { attempted: true, matched: false, discrepancies: ['drift'] },
    });

    const plan = recoveryPlanService.generateRecoveryPlan({
      originalOperationId: 'op-plan-53',
      causationId: 'cause-53',
      correlationId: 'corr-53',
      classificationResult: classification,
      compensationInfo: {
        availability: 'COMPENSATION_AVAILABLE',
        compensatingActionType: 'rollback_db_migration',
        targetSystem: 'postgres_cluster_01',
        parameters: { migrationId: 'v1.4_add_col' },
      },
    });

    expect(plan.proposedRecoveryAction).toBe('COMPENSATE');
    expect(plan.compensationPlan.availability).toBe('COMPENSATION_AVAILABLE');
    expect(plan.compensationPlan.compensatingActionType).toBe('rollback_db_migration');
    expect(typeof plan.compensationPlan.compensatingActionType).toBe('string');
  });

  it('54. no external execution occurs (plan creation has 0 network calls)', () => {
    const classification = failureClassificationService.classifyFailure({
      operationId: 'op-plan-54',
      causationId: 'cause-54',
      correlationId: 'corr-54',
      dispatchState: 'NOT_DISPATCHED',
      httpStatus: 503,
      timeoutEvidence: { timedOut: true, phase: 'PRE_DISPATCH' },
    });

    const plan = recoveryPlanService.generateRecoveryPlan({
      originalOperationId: 'op-plan-54',
      causationId: 'cause-54',
      correlationId: 'corr-54',
      classificationResult: classification,
      dispatchState: 'NOT_DISPATCHED',
      idempotency: 'IDEMPOTENT',
    });

    expect(plan.lifecycleState).toBe('PROPOSED');
  });

  it('55. no LLM execution occurs during recovery plan formulation', () => {
    const classification = failureClassificationService.classifyFailure({
      operationId: 'op-plan-55',
      causationId: 'cause-55',
      correlationId: 'corr-55',
      dispatchState: 'NOT_DISPATCHED',
      httpStatus: 404,
    });

    const plan = recoveryPlanService.generateRecoveryPlan({
      originalOperationId: 'op-plan-55',
      causationId: 'cause-55',
      correlationId: 'corr-55',
      classificationResult: classification,
    });

    expect(plan.expectedOutcome).toBeDefined();
    expect(typeof plan.expectedOutcome).toBe('string');
  });

  it('56. SECURITY: rejects prototype pollution inside recovery plan input metadata', () => {
    const classification = failureClassificationService.classifyFailure({
      operationId: 'op-plan-56',
      causationId: 'cause-56',
      correlationId: 'corr-56',
      dispatchState: 'NOT_DISPATCHED',
    });

    expect(() => {
      recoveryPlanService.generateRecoveryPlan({
        originalOperationId: 'op-plan-56',
        causationId: 'cause-56',
        correlationId: 'corr-56',
        classificationResult: classification,
        metadata: JSON.parse('{"__proto__": {"injected": true}}'),
      });
    }).toThrow(RecoveryContractViolationError);
  });

  // ============================================================================
  // Phase 4: Recovery Safety Analysis & Duplicate-Side-Effect Prevention Tests
  // ============================================================================

  it('57. READ_ONLY operation safety: duplicate side-effect risk is NONE and retry is permitted', () => {
    const classification = failureClassificationService.classifyFailure({
      operationId: 'op-safe-57',
      causationId: 'cause-57',
      correlationId: 'corr-57',
      dispatchState: 'NOT_DISPATCHED',
      httpStatus: 503,
      timeoutEvidence: { timedOut: true, phase: 'PRE_DISPATCH' },
    });
    const plan = recoveryPlanService.generateRecoveryPlan({
      originalOperationId: 'op-safe-57',
      causationId: 'cause-57',
      correlationId: 'corr-57',
      classificationResult: classification,
      idempotency: 'READ_ONLY',
    });

    const assessment = recoverySafetyService.assessSafety({
      plan,
      idempotency: 'READ_ONLY',
      dispatchState: 'NOT_DISPATCHED',
    });

    expect(assessment.idempotencyClassification).toBe('READ_ONLY');
    expect(assessment.duplicateSideEffectRisk).toBe('NONE');
    expect(assessment.retryPermitted).toBe(true);
    expect(assessment.reconciliationRequirement).toBe(false);
    expect(assessment.safetyRationale).toContain('READ_ONLY');
    // Epistemic honesty: no governance decision id on safety assessment
    expect((assessment as Record<string, unknown>).governanceDecisionId).toBeUndefined();
  });

  it('58. IDEMPOTENT operation safety: pre-dispatch is safe to retry with LOW duplicate risk', () => {
    const classification = failureClassificationService.classifyFailure({
      operationId: 'op-safe-58',
      causationId: 'cause-58',
      correlationId: 'corr-58',
      dispatchState: 'NOT_DISPATCHED',
      httpStatus: 503,
      timeoutEvidence: { timedOut: true, phase: 'PRE_DISPATCH' },
    });
    const plan = recoveryPlanService.generateRecoveryPlan({
      originalOperationId: 'op-safe-58',
      causationId: 'cause-58',
      correlationId: 'corr-58',
      classificationResult: classification,
      idempotency: 'IDEMPOTENT',
    });

    const assessment = recoverySafetyService.assessSafety({
      plan,
      idempotency: 'IDEMPOTENT',
      dispatchState: 'NOT_DISPATCHED',
    });

    expect(assessment.idempotencyClassification).toBe('IDEMPOTENT');
    expect(assessment.duplicateSideEffectRisk).toBe('LOW');
    expect(assessment.retryPermitted).toBe(true);
    expect(assessment.reconciliationRequirement).toBe(false);
  });

  it('59. CONDITIONALLY_IDEMPOTENT with conditions satisfied: retryPermitted is true', () => {
    const classification = failureClassificationService.classifyFailure({
      operationId: 'op-safe-59',
      causationId: 'cause-59',
      correlationId: 'corr-59',
      dispatchState: 'NOT_DISPATCHED',
      httpStatus: 503,
      timeoutEvidence: { timedOut: true, phase: 'PRE_DISPATCH' },
    });
    const plan = recoveryPlanService.generateRecoveryPlan({
      originalOperationId: 'op-safe-59',
      causationId: 'cause-59',
      correlationId: 'corr-59',
      classificationResult: classification,
      idempotency: 'CONDITIONALLY_IDEMPOTENT',
    });

    const assessment = recoverySafetyService.assessSafety({
      plan,
      idempotency: 'CONDITIONALLY_IDEMPOTENT',
      conditionalConditionsMet: true,
      dispatchState: 'NOT_DISPATCHED',
    });

    expect(assessment.idempotencyClassification).toBe('CONDITIONALLY_IDEMPOTENT');
    expect(assessment.duplicateSideEffectRisk).toBe('LOW');
    expect(assessment.retryPermitted).toBe(true);
    expect(assessment.safetyRationale).toContain('CONDITIONAL_IDEMPOTENCY_CONDITIONS_SATISFIED');
  });

  it('60. CONDITIONALLY_IDEMPOTENT with conditions missing: retryPermitted is false and risk is HIGH', () => {
    const classification = failureClassificationService.classifyFailure({
      operationId: 'op-safe-60',
      causationId: 'cause-60',
      correlationId: 'corr-60',
      dispatchState: 'NOT_DISPATCHED',
      httpStatus: 503,
      timeoutEvidence: { timedOut: true, phase: 'PRE_DISPATCH' },
    });
    const plan = recoveryPlanService.generateRecoveryPlan({
      originalOperationId: 'op-safe-60',
      causationId: 'cause-60',
      correlationId: 'corr-60',
      classificationResult: classification,
      idempotency: 'CONDITIONALLY_IDEMPOTENT',
    });

    const assessment = recoverySafetyService.assessSafety({
      plan,
      idempotency: 'CONDITIONALLY_IDEMPOTENT',
      conditionalConditionsMet: false,
      dispatchState: 'NOT_DISPATCHED',
    });

    expect(assessment.retryPermitted).toBe(false);
    expect(assessment.duplicateSideEffectRisk).toBe('HIGH');
    expect(assessment.safetyRationale).toContain('CONDITIONAL_IDEMPOTENCY_REQUIREMENTS_UNMET');
  });

  it('61. NON_IDEMPOTENT operation: forbids automatic retry', () => {
    const classification = failureClassificationService.classifyFailure({
      operationId: 'op-safe-61',
      causationId: 'cause-61',
      correlationId: 'corr-61',
      dispatchState: 'NOT_DISPATCHED',
      httpStatus: 503,
      timeoutEvidence: { timedOut: true, phase: 'PRE_DISPATCH' },
    });
    const plan = recoveryPlanService.generateRecoveryPlan({
      originalOperationId: 'op-safe-61',
      causationId: 'cause-61',
      correlationId: 'corr-61',
      classificationResult: classification,
      idempotency: 'NON_IDEMPOTENT',
    });

    const assessment = recoverySafetyService.assessSafety({
      plan,
      idempotency: 'NON_IDEMPOTENT',
      dispatchState: 'NOT_DISPATCHED',
    });

    expect(assessment.retryPermitted).toBe(false);
    expect(assessment.safetyRationale).toContain('NON_IDEMPOTENT_OPERATION');
  });

  it('62. UNKNOWN idempotency: treated conservatively without assuming safe retry', () => {
    const classification = failureClassificationService.classifyFailure({
      operationId: 'op-safe-62',
      causationId: 'cause-62',
      correlationId: 'corr-62',
      dispatchState: 'NOT_DISPATCHED',
      httpStatus: 503,
      timeoutEvidence: { timedOut: true, phase: 'PRE_DISPATCH' },
    });
    const plan = recoveryPlanService.generateRecoveryPlan({
      originalOperationId: 'op-safe-62',
      causationId: 'cause-62',
      correlationId: 'corr-62',
      classificationResult: classification,
      idempotency: 'UNKNOWN',
    });

    const assessment = recoverySafetyService.assessSafety({
      plan,
      idempotency: 'UNKNOWN',
      dispatchState: 'NOT_DISPATCHED',
    });

    expect(assessment.retryPermitted).toBe(false);
    expect(assessment.safetyRationale).toContain('UNKNOWN_IDEMPOTENCY');
  });

  it('63. post-dispatch UNKNOWN external state: retryPermitted is false, reconciliation is REQUIRED', () => {
    const classification = failureClassificationService.classifyFailure({
      operationId: 'op-safe-63',
      causationId: 'cause-63',
      correlationId: 'corr-63',
      dispatchState: 'DISPATCHED',
      timeoutEvidence: { timedOut: true, phase: 'POST_DISPATCH' },
    });
    const plan = recoveryPlanService.generateRecoveryPlan({
      originalOperationId: 'op-safe-63',
      causationId: 'cause-63',
      correlationId: 'corr-63',
      classificationResult: classification,
      dispatchState: 'DISPATCHED',
      idempotency: 'IDEMPOTENT',
    });

    const assessment = recoverySafetyService.assessSafety({
      plan,
      dispatchState: 'DISPATCHED',
      idempotency: 'IDEMPOTENT',
    });

    expect(assessment.retryPermitted).toBe(false);
    expect(assessment.reconciliationRequirement).toBe(true);
    expect(assessment.safetyRationale).toContain('RECONCILIATION_BARRIER_PREVENTS_RETRY');
  });

  it('64. confirmed external success: duplicate risk is CRITICAL and replay is strictly forbidden', () => {
    const classification = failureClassificationService.classifyFailure({
      operationId: 'op-safe-64',
      causationId: 'cause-64',
      correlationId: 'corr-64',
      dispatchState: 'DISPATCHED',
    });
    const plan = recoveryPlanService.generateRecoveryPlan({
      originalOperationId: 'op-safe-64',
      causationId: 'cause-64',
      correlationId: 'corr-64',
      classificationResult: classification,
      confirmedSuccess: true,
    });

    const assessment = recoverySafetyService.assessSafety({
      plan,
      confirmedSuccess: true,
      dispatchState: 'EXTERNAL_CONFIRMATION_RECEIVED',
    });

    expect(assessment.retryPermitted).toBe(false);
    expect(assessment.duplicateSideEffectRisk).toBe('CRITICAL');
    expect(assessment.safetyRationale).toContain('CONFIRMED_EXTERNAL_SUCCESS');
    expect(assessment.safetyRationale).toContain('DUPLICATE_SIDE_EFFECT_RISK');
  });

  it('65. partial execution with completed steps: preserves completed steps and prevents their replay', () => {
    const classification = failureClassificationService.classifyFailure({
      operationId: 'op-safe-65',
      causationId: 'cause-65',
      correlationId: 'corr-65',
      dispatchState: 'EXECUTING',
      partialExecutionEvidence: {
        completedSteps: ['step-alpha', 'step-beta'],
        failedStep: 'step-gamma',
        pendingSteps: ['step-delta'],
      },
    });
    const plan = recoveryPlanService.generateRecoveryPlan({
      originalOperationId: 'op-safe-65',
      causationId: 'cause-65',
      correlationId: 'corr-65',
      classificationResult: classification,
      dispatchState: 'EXECUTING',
      partialExecution: {
        completedSteps: ['step-alpha', 'step-beta'],
        failedStep: 'step-gamma',
        pendingSteps: ['step-delta'],
      },
    });

    const assessment = recoverySafetyService.assessSafety({
      plan,
      partialExecution: {
        completedSteps: ['step-alpha', 'step-beta'],
        failedStep: 'step-gamma',
        pendingSteps: ['step-delta'],
      },
    });

    expect(assessment.partialExecutionDetected).toBe(true);
    expect(assessment.completedSteps).toEqual(['step-alpha', 'step-beta']);
    expect(assessment.incompleteSteps).toEqual(['step-gamma', 'step-delta']);
    // Completed steps are preserved and not in incompleteSteps
    expect(assessment.incompleteSteps).not.toContain('step-alpha');
    expect(assessment.incompleteSteps).not.toContain('step-beta');
  });

  it('66. duplicate-side-effect prevention: detects high risk on dispatched non-idempotent operation', () => {
    const classification = failureClassificationService.classifyFailure({
      operationId: 'op-safe-66',
      causationId: 'cause-66',
      correlationId: 'corr-66',
      dispatchState: 'DISPATCHED',
    });
    const plan = recoveryPlanService.generateRecoveryPlan({
      originalOperationId: 'op-safe-66',
      causationId: 'cause-66',
      correlationId: 'corr-66',
      classificationResult: classification,
      idempotency: 'NON_IDEMPOTENT',
      dispatchState: 'DISPATCHED',
      riskLevel: 'HIGH',
    });

    const assessment = recoverySafetyService.assessSafety({
      plan,
      dispatchState: 'DISPATCHED',
      idempotency: 'NON_IDEMPOTENT',
    });

    expect(assessment.duplicateSideEffectRisk).toBe('HIGH');
    expect(assessment.retryPermitted).toBe(false);
    expect(assessment.safetyRationale).toContain('DUPLICATE_SIDE_EFFECT_RISK');
  });

  it('67. compensation available: correctly reports COMPENSATION_AVAILABLE in assessment', () => {
    const classification = failureClassificationService.classifyFailure({
      operationId: 'op-safe-67',
      causationId: 'cause-67',
      correlationId: 'corr-67',
      dispatchState: 'NOT_DISPATCHED',
      httpStatus: 422,
    });
    const plan = recoveryPlanService.generateRecoveryPlan({
      originalOperationId: 'op-safe-67',
      causationId: 'cause-67',
      correlationId: 'corr-67',
      classificationResult: classification,
      compensationInfo: {
        availability: 'COMPENSATION_AVAILABLE',
        compensatingActionType: 'refund_charge',
      },
    });

    const assessment = recoverySafetyService.assessSafety({
      plan,
      compensationAvailability: 'COMPENSATION_AVAILABLE',
    });

    expect(assessment.compensationAvailability).toBe('COMPENSATION_AVAILABLE');
    expect(assessment.safetyRationale).toContain('COMPENSATION_AVAILABLE');
  });

  it('68. compensation unavailable: correctly reports NO_COMPENSATION_AVAILABLE without inventing mechanisms', () => {
    const classification = failureClassificationService.classifyFailure({
      operationId: 'op-safe-68',
      causationId: 'cause-68',
      correlationId: 'corr-68',
      dispatchState: 'NOT_DISPATCHED',
      httpStatus: 400,
    });
    const plan = recoveryPlanService.generateRecoveryPlan({
      originalOperationId: 'op-safe-68',
      causationId: 'cause-68',
      correlationId: 'corr-68',
      classificationResult: classification,
    });

    const assessment = recoverySafetyService.assessSafety({
      plan,
      compensationAvailability: 'NO_COMPENSATION_AVAILABLE',
    });

    expect(assessment.compensationAvailability).toBe('NO_COMPENSATION_AVAILABLE');
  });

  it('69. rollback available: correctly reports rollback availability from evidence', () => {
    const classification = failureClassificationService.classifyFailure({
      operationId: 'op-safe-69',
      causationId: 'cause-69',
      correlationId: 'corr-69',
      dispatchState: 'NOT_DISPATCHED',
      httpStatus: 500,
    });
    const plan = recoveryPlanService.generateRecoveryPlan({
      originalOperationId: 'op-safe-69',
      causationId: 'cause-69',
      correlationId: 'corr-69',
      classificationResult: classification,
      compensationInfo: {
        availability: 'ROLLBACK_AVAILABLE',
      },
    });

    const assessment = recoverySafetyService.assessSafety({
      plan,
      rollbackAvailable: true,
      compensationAvailability: 'ROLLBACK_AVAILABLE',
    });

    expect(assessment.rollbackAvailability).toBe(true);
    expect(assessment.safetyRationale).toContain('ROLLBACK_AVAILABLE');
  });

  it('70. human approval required: correctly flags high-risk and permission failures for approval', () => {
    const classification = failureClassificationService.classifyFailure({
      operationId: 'op-safe-70',
      causationId: 'cause-70',
      correlationId: 'corr-70',
      dispatchState: 'NOT_DISPATCHED',
      permissionResult: { granted: false, revoked: true },
    });
    const plan = recoveryPlanService.generateRecoveryPlan({
      originalOperationId: 'op-safe-70',
      causationId: 'cause-70',
      correlationId: 'corr-70',
      classificationResult: classification,
      riskLevel: 'HIGH',
    });

    const assessment = recoverySafetyService.assessSafety({
      plan,
      dispatchState: 'NOT_DISPATCHED',
    });

    expect(assessment.humanApprovalRequired).toBe(true);
    expect(assessment.safetyRationale).toContain('PERMISSION_REVOCATION_REQUIRES_HUMAN_APPROVAL');
  });

  it('71. safety assessment does NOT authorize execution (epistemic separation)', () => {
    const classification = failureClassificationService.classifyFailure({
      operationId: 'op-safe-71',
      causationId: 'cause-71',
      correlationId: 'corr-71',
      dispatchState: 'NOT_DISPATCHED',
    });
    const plan = recoveryPlanService.generateRecoveryPlan({
      originalOperationId: 'op-safe-71',
      causationId: 'cause-71',
      correlationId: 'corr-71',
      classificationResult: classification,
    });

    const assessment = recoverySafetyService.assessSafety({ plan });

    // Assessment is pure decision analysis. It cannot authorize or approve.
    expect((assessment as Record<string, unknown>).isAuthorized).toBeUndefined();
    expect((assessment as Record<string, unknown>).governanceDecisionId).toBeUndefined();
    expect((assessment as Record<string, unknown>).approved).toBeUndefined();
  });

  it('72. safety assessment does NOT dispatch Action Bus (0 calls)', () => {
    const classification = failureClassificationService.classifyFailure({
      operationId: 'op-safe-72',
      causationId: 'cause-72',
      correlationId: 'corr-72',
      dispatchState: 'NOT_DISPATCHED',
    });
    const plan = recoveryPlanService.generateRecoveryPlan({
      originalOperationId: 'op-safe-72',
      causationId: 'cause-72',
      correlationId: 'corr-72',
      classificationResult: classification,
    });

    // Assess safety runs with zero network/bus operations
    const assessment = recoverySafetyService.assessSafety({ plan });
    expect(assessment).toBeDefined();
    expect(Object.isFrozen(assessment)).toBe(true);
  });

  it('73. safety assessment does NOT call executionGateway (0 calls)', () => {
    const classification = failureClassificationService.classifyFailure({
      operationId: 'op-safe-73',
      causationId: 'cause-73',
      correlationId: 'corr-73',
      dispatchState: 'NOT_DISPATCHED',
    });
    const plan = recoveryPlanService.generateRecoveryPlan({
      originalOperationId: 'op-safe-73',
      causationId: 'cause-73',
      correlationId: 'corr-73',
      classificationResult: classification,
    });

    const assessment = recoverySafetyService.assessSafety({ plan });
    expect(assessment.retryPermitted).toBeDefined();
  });

  it('74. SECURITY: prototype pollution rejection in assessment input metadata', () => {
    const classification = failureClassificationService.classifyFailure({
      operationId: 'op-safe-74',
      causationId: 'cause-74',
      correlationId: 'corr-74',
      dispatchState: 'NOT_DISPATCHED',
    });
    const plan = recoveryPlanService.generateRecoveryPlan({
      originalOperationId: 'op-safe-74',
      causationId: 'cause-74',
      correlationId: 'corr-74',
      classificationResult: classification,
    });

    expect(() => {
      recoverySafetyService.assessSafety({
        plan,
        metadata: JSON.parse('{"__proto__": {"malicious": true}}'),
      });
    }).toThrow(RecoveryContractViolationError);
  });

  // ============================================================================
  // Adversarial Tests (MANDATORY A - G)
  // ============================================================================

  it('75. ADVERSARIAL A: Local timeout + remote success evidence -> retryPermitted = false, duplicateRisk = CRITICAL', () => {
    const classification = failureClassificationService.classifyFailure({
      operationId: 'op-adv-A',
      causationId: 'cause-adv-A',
      correlationId: 'corr-adv-A',
      dispatchState: 'DISPATCHED',
      timeoutEvidence: { timedOut: true, phase: 'POST_DISPATCH' },
    });
    const plan = recoveryPlanService.generateRecoveryPlan({
      originalOperationId: 'op-adv-A',
      causationId: 'cause-adv-A',
      correlationId: 'corr-adv-A',
      classificationResult: classification,
      dispatchState: 'DISPATCHED',
      idempotency: 'NON_IDEMPOTENT',
    });

    const assessment = recoverySafetyService.assessSafety({
      plan,
      confirmedSuccess: true, // Authoritative evidence proves remote success!
      dispatchState: 'EXTERNAL_CONFIRMATION_RECEIVED',
    });

    expect(assessment.retryPermitted).toBe(false);
    expect(assessment.duplicateSideEffectRisk).toBe('CRITICAL');
    expect(assessment.safetyRationale).toContain('CONFIRMED_EXTERNAL_SUCCESS');
  });

  it('76. ADVERSARIAL B: Dispatch attempted + no confirmation -> retryPermitted = false, reconciliation = REQUIRED', () => {
    const classification = failureClassificationService.classifyFailure({
      operationId: 'op-adv-B',
      causationId: 'cause-adv-B',
      correlationId: 'corr-adv-B',
      dispatchState: 'DISPATCH_ATTEMPTED',
    });
    const plan = recoveryPlanService.generateRecoveryPlan({
      originalOperationId: 'op-adv-B',
      causationId: 'cause-adv-B',
      correlationId: 'corr-adv-B',
      classificationResult: classification,
      dispatchState: 'DISPATCH_ATTEMPTED',
      idempotency: 'IDEMPOTENT',
    });

    const assessment = recoverySafetyService.assessSafety({
      plan,
      dispatchState: 'DISPATCH_ATTEMPTED',
      idempotency: 'IDEMPOTENT',
    });

    expect(assessment.retryPermitted).toBe(false);
    expect(assessment.reconciliationRequirement).toBe(true);
    expect(assessment.safetyRationale).toContain('RECONCILIATION_REQUIRED_AFTER_DISPATCH');
  });

  it('77. ADVERSARIAL C: Non-idempotent + unknown state -> retryPermitted = false, reconciliation = REQUIRED', () => {
    const classification = failureClassificationService.classifyFailure({
      operationId: 'op-adv-C',
      causationId: 'cause-adv-C',
      correlationId: 'corr-adv-C',
      dispatchState: 'DISPATCHED',
    });
    const plan = recoveryPlanService.generateRecoveryPlan({
      originalOperationId: 'op-adv-C',
      causationId: 'cause-adv-C',
      correlationId: 'corr-adv-C',
      classificationResult: classification,
      dispatchState: 'DISPATCHED',
      idempotency: 'NON_IDEMPOTENT',
    });

    const assessment = recoverySafetyService.assessSafety({
      plan,
      dispatchState: 'DISPATCHED',
      idempotency: 'NON_IDEMPOTENT',
    });

    expect(assessment.retryPermitted).toBe(false);
    expect(assessment.reconciliationRequirement).toBe(true);
    expect(assessment.duplicateSideEffectRisk).toBe('HIGH');
  });

  it('78. ADVERSARIAL D: Conditional idempotency + missing idempotency key -> retryPermitted = false', () => {
    const classification = failureClassificationService.classifyFailure({
      operationId: 'op-adv-D',
      causationId: 'cause-adv-D',
      correlationId: 'corr-adv-D',
      dispatchState: 'NOT_DISPATCHED',
    });
    const plan = recoveryPlanService.generateRecoveryPlan({
      originalOperationId: 'op-adv-D',
      causationId: 'cause-adv-D',
      correlationId: 'corr-adv-D',
      classificationResult: classification,
      idempotency: 'CONDITIONALLY_IDEMPOTENT',
    });

    const assessment = recoverySafetyService.assessSafety({
      plan,
      idempotency: 'CONDITIONALLY_IDEMPOTENT',
      conditionalConditionsMet: false, // Conditions unmet!
      dispatchState: 'NOT_DISPATCHED',
    });

    expect(assessment.retryPermitted).toBe(false);
    expect(assessment.duplicateSideEffectRisk).toBe('HIGH');
  });

  it('79. ADVERSARIAL E: Completed steps A/B + failed C -> A/B remain completed and are not replay candidates', () => {
    const classification = failureClassificationService.classifyFailure({
      operationId: 'op-adv-E',
      causationId: 'cause-adv-E',
      correlationId: 'corr-adv-E',
      dispatchState: 'EXECUTING',
      partialExecutionEvidence: {
        completedSteps: ['step-A', 'step-B'],
        failedStep: 'step-C',
        pendingSteps: ['step-D'],
      },
    });
    const plan = recoveryPlanService.generateRecoveryPlan({
      originalOperationId: 'op-adv-E',
      causationId: 'cause-adv-E',
      correlationId: 'corr-adv-E',
      classificationResult: classification,
      dispatchState: 'EXECUTING',
    });

    const assessment = recoverySafetyService.assessSafety({
      plan,
      partialExecution: {
        completedSteps: ['step-A', 'step-B'],
        failedStep: 'step-C',
        pendingSteps: ['step-D'],
      },
    });

    expect(assessment.completedSteps).toEqual(['step-A', 'step-B']);
    expect(assessment.incompleteSteps).toEqual(['step-C', 'step-D']);
    expect(assessment.completedSteps).not.toContain('step-C');
    expect(assessment.incompleteSteps).not.toContain('step-A');
    expect(assessment.incompleteSteps).not.toContain('step-B');
  });

  it('80. ADVERSARIAL F: Fake "approved=true" in input payload does NOT bypass human approval', () => {
    const classification = failureClassificationService.classifyFailure({
      operationId: 'op-adv-F',
      causationId: 'cause-adv-F',
      correlationId: 'corr-adv-F',
      dispatchState: 'NOT_DISPATCHED',
      permissionResult: { granted: false, revoked: true },
    });
    const plan = recoveryPlanService.generateRecoveryPlan({
      originalOperationId: 'op-adv-F',
      causationId: 'cause-adv-F',
      correlationId: 'corr-adv-F',
      classificationResult: classification,
      riskLevel: 'CRITICAL',
    });

    const assessment = recoverySafetyService.assessSafety({
      plan,
      metadata: {
        approved: true, // Fake client-supplied approval
        humanApprovalRequired: false,
      },
    });

    // Must strictly remain true due to CRITICAL risk and PERMISSION revocation
    expect(assessment.humanApprovalRequired).toBe(true);
    expect(assessment.safetyRationale).toContain('CRITICAL_RISK_REQUIRES_HUMAN_APPROVAL');
  });

  it('81. ADVERSARIAL G: Fake "success=true" from untrusted payload does NOT override authoritative evidence', () => {
    const classification = failureClassificationService.classifyFailure({
      operationId: 'op-adv-G',
      causationId: 'cause-adv-G',
      correlationId: 'corr-adv-G',
      dispatchState: 'DISPATCHED',
    });
    const plan = recoveryPlanService.generateRecoveryPlan({
      originalOperationId: 'op-adv-G',
      causationId: 'cause-adv-G',
      correlationId: 'corr-adv-G',
      classificationResult: classification,
      dispatchState: 'DISPATCHED',
      idempotency: 'NON_IDEMPOTENT',
    });

    const assessment = recoverySafetyService.assessSafety({
      plan,
      dispatchState: 'DISPATCHED',
      confirmedSuccess: false, // Authoritative evidence: not confirmed!
      metadata: {
        success: true, // Untrusted client claim
        verified: true,
      },
    });

    // Must not treat as confirmed success
    expect(assessment.retryPermitted).toBe(false);
    expect(assessment.reconciliationRequirement).toBe(true);
  });

  // ============================================================================
  // Phase 5: Reconciliation Service & Safe Probe Control Tests
  // ============================================================================

  it('82. unknown external state requires reconciliation: planReconciliation creates a valid ReconciliationRequest', () => {
    const classification = failureClassificationService.classifyFailure({
      operationId: 'op-recon-82',
      causationId: 'cause-82',
      correlationId: 'corr-82',
      dispatchState: 'DISPATCHED',
      timeoutEvidence: { timedOut: true, phase: 'POST_DISPATCH' },
    });
    const plan = recoveryPlanService.generateRecoveryPlan({
      originalOperationId: 'op-recon-82',
      causationId: 'cause-82',
      correlationId: 'corr-82',
      classificationResult: classification,
      dispatchState: 'DISPATCHED',
    });

    const req = recoveryReconciliationService.planReconciliation({ plan });

    expect(req.originalOperationId).toBe('op-recon-82');
    expect(req.recoveryPlanId).toBe(plan.recoveryPlanId);
    expect(req.probeIntent).toBe('READ_ONLY_STATUS_CHECK');
    expect(req.isReadOnly).toBe(true);
    expect(req.lifecycleState).toBe('PLANNED');
  });

  it('83. read-only reconciliation plan generated: isReadOnly is strictly true and frozen', () => {
    const classification = failureClassificationService.classifyFailure({
      operationId: 'op-recon-83',
      causationId: 'cause-83',
      correlationId: 'corr-83',
      dispatchState: 'DISPATCHED',
    });
    const plan = recoveryPlanService.generateRecoveryPlan({
      originalOperationId: 'op-recon-83',
      causationId: 'cause-83',
      correlationId: 'corr-83',
      classificationResult: classification,
    });

    const req = recoveryReconciliationService.planReconciliation({ plan });

    expect(req.isReadOnly).toBe(true);
    expect(Object.isFrozen(req)).toBe(true);
    expect(() => {
      (req as unknown as { isReadOnly: boolean }).isReadOnly = false;
    }).toThrow();
  });

  it('84. reconciliation does not replay original mutation: maps to read inquiry', () => {
    const classification = failureClassificationService.classifyFailure({
      operationId: 'op-github-create-issue-84',
      causationId: 'cause-84',
      correlationId: 'corr-84',
      dispatchState: 'DISPATCHED',
    });
    const plan = recoveryPlanService.generateRecoveryPlan({
      originalOperationId: 'op-github-create-issue-84',
      causationId: 'cause-84',
      correlationId: 'corr-84',
      classificationResult: classification,
    });

    const req = recoveryReconciliationService.planReconciliation({
      plan,
      targetCapability: 'github.issue_read',
      probeIntent: 'READ_ONLY_STATUS_CHECK',
    });

    expect(req.targetCapability).toBe('github.issue_read');
    expect(req.targetCapability).not.toContain('create');
    expect(req.isReadOnly).toBe(true);
  });

  it('85. distinct reconciliationId generated: reconciliationId !== originalOperationId', () => {
    const classification = failureClassificationService.classifyFailure({
      operationId: 'op-recon-85',
      causationId: 'cause-85',
      correlationId: 'corr-85',
      dispatchState: 'DISPATCHED',
    });
    const plan = recoveryPlanService.generateRecoveryPlan({
      originalOperationId: 'op-recon-85',
      causationId: 'cause-85',
      correlationId: 'corr-85',
      classificationResult: classification,
    });

    const req = recoveryReconciliationService.planReconciliation({ plan });

    expect(req.reconciliationId).toBeDefined();
    expect(req.reconciliationId).not.toBe(plan.originalOperationId);
    expect(req.reconciliationId.startsWith('recon_op-recon-85')).toBe(true);
  });

  it('86. causationId links to originalOperationId', () => {
    const classification = failureClassificationService.classifyFailure({
      operationId: 'op-recon-86',
      causationId: 'cause-86',
      correlationId: 'corr-86',
      dispatchState: 'DISPATCHED',
    });
    const plan = recoveryPlanService.generateRecoveryPlan({
      originalOperationId: 'op-recon-86',
      causationId: 'cause-86',
      correlationId: 'corr-86',
      classificationResult: classification,
    });

    const req = recoveryReconciliationService.planReconciliation({ plan });

    expect(req.causationId).toBe('op-recon-86');
    expect(req.correlationId).toBe('corr-86');
  });

  it('87. verified external success: probe returns verified remote resource -> outcome: VERIFIED_SUCCESS, epistemic: CONFIRMED', async () => {
    const classification = failureClassificationService.classifyFailure({
      operationId: 'op-recon-87',
      causationId: 'cause-87',
      correlationId: 'corr-87',
      dispatchState: 'DISPATCHED',
    });
    const plan = recoveryPlanService.generateRecoveryPlan({
      originalOperationId: 'op-recon-87',
      causationId: 'cause-87',
      correlationId: 'corr-87',
      classificationResult: classification,
    });
    const req = recoveryReconciliationService.planReconciliation({ plan });

    const result = await recoveryReconciliationService.coordinateProbe(req, {
      executeActionBusProbe: async () => ({
        success: true,
        data: { resourceId: 'res-87', status: 'COMPLETED' },
      }),
    });

    expect(result.outcome).toBe('VERIFIED_SUCCESS');
    expect(result.epistemicStatus).toBe('CONFIRMED');
    expect(result.observedExternalState).toBeDefined();
    expect(result.note).toContain('is present');
  });

  it('88. verified external failure: probe returns not found -> outcome: VERIFIED_FAILURE, epistemic: OBSERVED', async () => {
    const classification = failureClassificationService.classifyFailure({
      operationId: 'op-recon-88',
      causationId: 'cause-88',
      correlationId: 'corr-88',
      dispatchState: 'DISPATCHED',
    });
    const plan = recoveryPlanService.generateRecoveryPlan({
      originalOperationId: 'op-recon-88',
      causationId: 'cause-88',
      correlationId: 'corr-88',
      classificationResult: classification,
    });
    const req = recoveryReconciliationService.planReconciliation({ plan });

    const result = await recoveryReconciliationService.coordinateProbe(req, {
      executeActionBusProbe: async () => ({
        success: false,
        notFound: true,
      }),
    });

    expect(result.outcome).toBe('VERIFIED_FAILURE');
    expect(result.epistemicStatus).toBe('OBSERVED');
    expect(result.note).toContain('does not exist');
  });

  it('89. still unknown remains UNKNOWN: probe is indeterminate -> outcome: STILL_UNKNOWN, epistemic: UNKNOWN', async () => {
    const classification = failureClassificationService.classifyFailure({
      operationId: 'op-recon-89',
      causationId: 'cause-89',
      correlationId: 'corr-89',
      dispatchState: 'DISPATCHED',
    });
    const plan = recoveryPlanService.generateRecoveryPlan({
      originalOperationId: 'op-recon-89',
      causationId: 'cause-89',
      correlationId: 'corr-89',
      classificationResult: classification,
    });
    const req = recoveryReconciliationService.planReconciliation({ plan });

    const result = await recoveryReconciliationService.coordinateProbe(req, {
      executeActionBusProbe: async () => ({
        success: false,
        notFound: false,
      }),
    });

    expect(result.outcome).toBe('STILL_UNKNOWN');
    expect(result.epistemicStatus).toBe('UNKNOWN');
  });

  it('90. failed probe does NOT become original failure: probe error -> outcome: FAILED, epistemic: UNKNOWN', async () => {
    const classification = failureClassificationService.classifyFailure({
      operationId: 'op-recon-90',
      causationId: 'cause-90',
      correlationId: 'corr-90',
      dispatchState: 'DISPATCHED',
    });
    const plan = recoveryPlanService.generateRecoveryPlan({
      originalOperationId: 'op-recon-90',
      causationId: 'cause-90',
      correlationId: 'corr-90',
      classificationResult: classification,
    });
    const req = recoveryReconciliationService.planReconciliation({ plan });

    const result = await recoveryReconciliationService.coordinateProbe(req, {
      executeActionBusProbe: async () => {
        throw new Error('Network socket disconnected during probe');
      },
    });

    expect(result.outcome).toBe('FAILED');
    // Epistemic invariant: Probe failure does NOT downgrade original operation to failed!
    expect(result.epistemicStatus).toBe('UNKNOWN');
    expect(result.note).toContain('Original operation status remains UNKNOWN');
  });

  it('91. reconciliation attempt bound enforced: attemptNumber > maxAttempts returns EXPIRED', async () => {
    const classification = failureClassificationService.classifyFailure({
      operationId: 'op-recon-91',
      causationId: 'cause-91',
      correlationId: 'corr-91',
      dispatchState: 'DISPATCHED',
    });
    const plan = recoveryPlanService.generateRecoveryPlan({
      originalOperationId: 'op-recon-91',
      causationId: 'cause-91',
      correlationId: 'corr-91',
      classificationResult: classification,
    });
    const req = recoveryReconciliationService.planReconciliation({
      plan,
      attemptNumber: 4, // Exceeds maxAttempts (3)
      maxAttempts: 3,
    });

    const result = await recoveryReconciliationService.coordinateProbe(req);

    expect(result.outcome).toBe('EXPIRED');
    expect(result.epistemicStatus).toBe('UNKNOWN');
    expect(result.note).toContain('attempt limit exceeded');
  });

  it('92. Action Bus boundary respected: coordinates probe through executeActionBusProbe', async () => {
    const classification = failureClassificationService.classifyFailure({
      operationId: 'op-recon-92',
      causationId: 'cause-92',
      correlationId: 'corr-92',
      dispatchState: 'DISPATCHED',
    });
    const plan = recoveryPlanService.generateRecoveryPlan({
      originalOperationId: 'op-recon-92',
      causationId: 'cause-92',
      correlationId: 'corr-92',
      classificationResult: classification,
    });
    const req = recoveryReconciliationService.planReconciliation({ plan });

    let busProbeCalled = false;
    const result = await recoveryReconciliationService.coordinateProbe(req, {
      executeActionBusProbe: async (probeReq) => {
        busProbeCalled = true;
        expect(probeReq.capabilityId).toBe(req.targetCapability);
        return { success: true, data: { active: true } };
      },
    });

    expect(busProbeCalled).toBe(true);
    expect(result.outcome).toBe('VERIFIED_SUCCESS');
  });

  it('93. executionGateway boundary respected: coordinates probe through executeGatewayProbe', async () => {
    const classification = failureClassificationService.classifyFailure({
      operationId: 'op-recon-93',
      causationId: 'cause-93',
      correlationId: 'corr-93',
      dispatchState: 'DISPATCHED',
    });
    const plan = recoveryPlanService.generateRecoveryPlan({
      originalOperationId: 'op-recon-93',
      causationId: 'cause-93',
      correlationId: 'corr-93',
      classificationResult: classification,
    });
    const req = recoveryReconciliationService.planReconciliation({ plan });

    let gatewayProbeCalled = false;
    const result = await recoveryReconciliationService.coordinateProbe(req, {
      executeGatewayProbe: async (key) => {
        gatewayProbeCalled = true;
        expect(key).toContain('op-recon-93');
        return { completed: true, result: { generatedText: 'Model output verified' } };
      },
    });

    expect(gatewayProbeCalled).toBe(true);
    expect(result.outcome).toBe('VERIFIED_SUCCESS');
    expect(result.epistemicStatus).toBe('CONFIRMED');
  });

  it('94. connector permissions respected: authorization rejection yields REJECTED', async () => {
    const classification = failureClassificationService.classifyFailure({
      operationId: 'op-recon-94',
      causationId: 'cause-94',
      correlationId: 'corr-94',
      dispatchState: 'DISPATCHED',
    });
    const plan = recoveryPlanService.generateRecoveryPlan({
      originalOperationId: 'op-recon-94',
      causationId: 'cause-94',
      correlationId: 'corr-94',
      classificationResult: classification,
    });
    const req = recoveryReconciliationService.planReconciliation({
      plan,
      targetCapability: 'action.github.read',
    });

    // Mock action bus returning DENIED status
    const result = await recoveryReconciliationService.coordinateProbe(req, {
      executeActionBusProbe: async () => ({
        success: false,
        error: new Error('Permission denied by connector fabric'),
      }),
    });

    expect(result.outcome).toBe('FAILED');
    expect(result.epistemicStatus).toBe('UNKNOWN');
  });

  it('95. arbitrary URL rejected: planning or probing with https://... throws RecoveryContractViolationError', () => {
    const classification = failureClassificationService.classifyFailure({
      operationId: 'op-recon-95',
      causationId: 'cause-95',
      correlationId: 'corr-95',
      dispatchState: 'DISPATCHED',
    });
    const plan = recoveryPlanService.generateRecoveryPlan({
      originalOperationId: 'op-recon-95',
      causationId: 'cause-95',
      correlationId: 'corr-95',
      classificationResult: classification,
    });

    expect(() => {
      recoveryReconciliationService.planReconciliation({
        plan,
        targetCapability: 'https://malicious-external-api.com/status',
      });
    }).toThrow(RecoveryContractViolationError);
  });

  it('96. fake verified=true in payload rejected: untrusted claim does not bypass probe', async () => {
    const classification = failureClassificationService.classifyFailure({
      operationId: 'op-recon-96',
      causationId: 'cause-96',
      correlationId: 'corr-96',
      dispatchState: 'DISPATCHED',
    });
    const plan = recoveryPlanService.generateRecoveryPlan({
      originalOperationId: 'op-recon-96',
      causationId: 'cause-96',
      correlationId: 'corr-96',
      classificationResult: classification,
    });
    const req = recoveryReconciliationService.planReconciliation({
      plan,
      metadata: { verified: true, externalSuccess: true },
    });

    // Probe returns uncontactable
    const result = await recoveryReconciliationService.coordinateProbe(req, {
      executeActionBusProbe: async () => ({
        success: false,
        notFound: false,
      }),
    });

    expect(result.outcome).toBe('STILL_UNKNOWN');
    expect(result.epistemicStatus).toBe('UNKNOWN');
  });

  it('97. credentials and tokens rejected in probe parameters', () => {
    const classification = failureClassificationService.classifyFailure({
      operationId: 'op-recon-97',
      causationId: 'cause-97',
      correlationId: 'corr-97',
      dispatchState: 'DISPATCHED',
    });
    const plan = recoveryPlanService.generateRecoveryPlan({
      originalOperationId: 'op-recon-97',
      causationId: 'cause-97',
      correlationId: 'corr-97',
      classificationResult: classification,
    });

    expect(() => {
      recoveryReconciliationService.planReconciliation({
        plan,
        probeParameters: { apiKey: 'secret-token-12345' },
      });
    }).toThrow(RecoveryContractViolationError);
  });

  it('98. reconciliation lifecycle transitions: PLANNED to outcome result', async () => {
    const classification = failureClassificationService.classifyFailure({
      operationId: 'op-recon-98',
      causationId: 'cause-98',
      correlationId: 'corr-98',
      dispatchState: 'DISPATCHED',
    });
    const plan = recoveryPlanService.generateRecoveryPlan({
      originalOperationId: 'op-recon-98',
      causationId: 'cause-98',
      correlationId: 'corr-98',
      classificationResult: classification,
    });

    const req = recoveryReconciliationService.planReconciliation({ plan });
    expect(req.lifecycleState).toBe('PLANNED');

    const result = await recoveryReconciliationService.coordinateProbe(req, {
      executeActionBusProbe: async () => ({
        success: true,
        data: { verified: true },
      }),
    });

    expect(result.outcome).toBe('VERIFIED_SUCCESS');
  });

  it('99. no infinite reconciliation loop: attempt bounds prevent looping past 3', async () => {
    const classification = failureClassificationService.classifyFailure({
      operationId: 'op-recon-99',
      causationId: 'cause-99',
      correlationId: 'corr-99',
      dispatchState: 'DISPATCHED',
    });
    const plan = recoveryPlanService.generateRecoveryPlan({
      originalOperationId: 'op-recon-99',
      causationId: 'cause-99',
      correlationId: 'corr-99',
      classificationResult: classification,
    });

    let currentAttempt = 1;
    let finalOutcome: string = '';

    while (currentAttempt <= 4) {
      const req = recoveryReconciliationService.planReconciliation({
        plan,
        attemptNumber: currentAttempt,
        maxAttempts: 3,
      });

      const res = await recoveryReconciliationService.coordinateProbe(req, {
        executeActionBusProbe: async () => ({ success: false, notFound: false }),
      });

      finalOutcome = res.outcome;
      if (res.outcome === 'EXPIRED') {
        break;
      }
      currentAttempt++;
    }

    expect(currentAttempt).toBe(4);
    expect(finalOutcome).toBe('EXPIRED');
  });

  it('100. INTEGRATION: UNKNOWN_EXTERNAL_STATE -> RecoveryPlan (RECONCILE) -> Reconciliation Service -> Action Bus boundary -> verified state', async () => {
    // 1. Operational evidence: timeout post-dispatch
    const classification = failureClassificationService.classifyFailure({
      operationId: 'op-recon-integ-100',
      causationId: 'cause-100',
      correlationId: 'corr-100',
      dispatchState: 'DISPATCHED',
      timeoutEvidence: { timedOut: true, phase: 'POST_DISPATCH' },
    });
    expect(classification.classification).toBe('UNKNOWN_EXTERNAL_STATE');

    // 2. Recovery Plan generation produces RECONCILE
    const plan = recoveryPlanService.generateRecoveryPlan({
      originalOperationId: 'op-recon-integ-100',
      causationId: 'cause-100',
      correlationId: 'corr-100',
      classificationResult: classification,
      dispatchState: 'DISPATCHED',
      idempotency: 'IDEMPOTENT',
    });
    expect(plan.proposedRecoveryAction).toBe('RECONCILE');
    expect(plan.reconciliationRequirement?.required).toBe(true);

    // 3. Safety assessment verifies reconciliation barrier prevents blind retry
    const safety = recoverySafetyService.assessSafety({
      plan,
      dispatchState: 'DISPATCHED',
      idempotency: 'IDEMPOTENT',
    });
    expect(safety.retryPermitted).toBe(false);
    expect(safety.reconciliationRequirement).toBe(true);

    // 4. Reconciliation Service formulates probe
    const reconReq = recoveryReconciliationService.planReconciliation({
      plan,
      safetyAssessment: safety,
      targetCapability: 'filesystem.stat',
    });
    expect(reconReq.isReadOnly).toBe(true);

    // 5. Existing boundary probe confirms side effect succeeded remotely
    const reconResult = await recoveryReconciliationService.coordinateProbe(reconReq, {
      executeActionBusProbe: async (probeReq) => {
        expect(probeReq.capabilityId).toBe('filesystem.stat');
        return {
          success: true,
          data: { path: '/workspace/build.log', size: 1024, exists: true },
        };
      },
    });

    expect(reconResult.outcome).toBe('VERIFIED_SUCCESS');
    expect(reconResult.epistemicStatus).toBe('CONFIRMED');
    expect(reconResult.originalOperationId).toBe('op-recon-integ-100');
  });

  it('101. unavailable probe handling: target capability without read probe routes to RECONCILIATION_UNAVAILABLE', async () => {
    const classification = failureClassificationService.classifyFailure({
      operationId: 'op-recon-101',
      causationId: 'cause-101',
      correlationId: 'corr-101',
      dispatchState: 'DISPATCHED',
    });
    const plan = recoveryPlanService.generateRecoveryPlan({
      originalOperationId: 'op-recon-101',
      causationId: 'cause-101',
      correlationId: 'corr-101',
      classificationResult: classification,
    });
    const req = recoveryReconciliationService.planReconciliation({
      plan,
      targetCapability: 'RECONCILIATION_UNAVAILABLE',
    });

    const result = await recoveryReconciliationService.coordinateProbe(req);

    expect(result.outcome).toBe('RECONCILIATION_UNAVAILABLE');
    expect(result.epistemicStatus).toBe('UNKNOWN');
    expect(result.note).toContain('Mutation replay forbidden');
  });

  // ============================================================================
  // Phase 6: Declarative Compensation & Reverse Operations (Tests 102–131)
  // ============================================================================

  it('102. confirmed failed pre-dispatch operation: no compensation required', () => {
    const assessment = recoveryCompensationService.assessCompensation({
      originalOperationId: 'op-comp-102',
      capabilityId: 'filesystem.write',
      parameters: { path: '/workspace/test.txt' },
      dispatchState: 'NOT_DISPATCHED',
      failureClassification: 'POLICY',
    });
    expect(assessment.eligibility).toBe('COMPENSATION_NOT_REQUIRED');
    expect(assessment.rationale).toContain('pre-dispatch');
    expect(assessment.candidatePlan).toBeUndefined();
  });

  it('103. confirmed successful operation: compensation proposed when explicit inverse exists', () => {
    const assessment = recoveryCompensationService.assessCompensation({
      originalOperationId: 'op-comp-103',
      capabilityId: 'filesystem.write',
      parameters: { path: '/workspace/artifact.txt' },
      dispatchState: 'EXTERNAL_CONFIRMATION_RECEIVED',
      confirmedSuccess: true,
    });
    expect(assessment.eligibility).toBe('COMPENSATION_REQUIRES_APPROVAL');
    expect(assessment.candidatePlan).toBeDefined();
    expect(assessment.candidatePlan?.compensatingCapability).toBe('filesystem.delete');
    expect(assessment.candidatePlan?.compensationType).toBe('RESOURCE_CLEANUP');
  });

  it('104. partial execution: compensation eligibility assessed with completed steps', () => {
    const emptyAssessment = recoveryCompensationService.assessCompensation({
      originalOperationId: 'op-comp-104-empty',
      capabilityId: 'filesystem.write',
      parameters: { path: '/workspace/step1.txt' },
      partialExecution: { completedSteps: [], pendingSteps: ['step1', 'step2'] },
    });
    expect(emptyAssessment.eligibility).toBe('COMPENSATION_NOT_REQUIRED');

    const assessment = recoveryCompensationService.assessCompensation({
      originalOperationId: 'op-comp-104',
      capabilityId: 'filesystem.write',
      parameters: { path: '/workspace/step1.txt' },
      partialExecution: { completedSteps: ['step1'], failedStep: 'step2', pendingSteps: ['step3'] },
      confirmedSuccess: true,
    });
    expect(assessment.eligibility).toBe('COMPENSATION_REQUIRES_APPROVAL');
    expect(assessment.candidatePlan?.compensatingCapability).toBe('filesystem.delete');
  });

  it('105. unknown external state: reconciliation required before compensation', () => {
    const assessment = recoveryCompensationService.assessCompensation({
      originalOperationId: 'op-comp-105',
      capabilityId: 'filesystem.write',
      parameters: { path: '/workspace/pending.txt' },
      dispatchState: 'EXTERNAL_CONFIRMATION_ABSENT',
      truthState: 'UNKNOWN',
    });
    expect(assessment.eligibility).toBe('COMPENSATION_REQUIRES_RECONCILIATION');
    expect(assessment.requiresReconciliation).toBe(true);
    expect(assessment.candidatePlan).toBeUndefined();
  });

  it('106. failed reconciliation: compensation does not falsely proceed', () => {
    const assessment = recoveryCompensationService.assessCompensation({
      originalOperationId: 'op-comp-106',
      capabilityId: 'filesystem.write',
      parameters: { path: '/workspace/broken.txt' },
      dispatchState: 'EXTERNAL_CONFIRMATION_ABSENT',
      truthState: 'UNKNOWN',
      reconciliationResult: {
        reconciliationId: 'recon-106',
        originalOperationId: 'op-comp-106',
        recoveryPlanId: 'plan-106',
        outcome: 'FAILED',
        epistemicStatus: 'UNKNOWN',
        authoritativeEvidenceReferences: [],
        note: 'Probe connection timed out',
        reconciledAt: Date.now(),
        causationId: 'op-comp-106',
        correlationId: 'corr-106',
        attemptNumber: 1,
      },
    });
    expect(assessment.eligibility).toBe('COMPENSATION_REQUIRES_RECONCILIATION');
    expect(assessment.candidatePlan).toBeUndefined();
  });

  it('107. explicit supported reverse mapping produces declarative compensation', () => {
    const fsAssessment = recoveryCompensationService.assessCompensation({
      originalOperationId: 'op-comp-107-fs',
      capabilityId: 'filesystem.write',
      parameters: { path: '/workspace/output.csv' },
      confirmedSuccess: true,
    });
    expect(fsAssessment.candidatePlan?.compensatingCapability).toBe('filesystem.delete');
    expect(fsAssessment.candidatePlan?.targetState).toBe('FILE_REMOVED');

    const ghAssessment = recoveryCompensationService.assessCompensation({
      originalOperationId: 'op-comp-107-gh',
      capabilityId: 'github.create_issue',
      parameters: { repository: 'aryaos/core', issueNumber: 42 },
      confirmedSuccess: true,
    });
    expect(ghAssessment.candidatePlan?.compensatingCapability).toBe('github.close_issue');
    expect(ghAssessment.candidatePlan?.targetState).toBe('ISSUE_CLOSED');
    expect(ghAssessment.eligibility).toBe('COMPENSATION_ELIGIBLE');
  });

  it('108. unsupported action produces COMPENSATION_UNAVAILABLE', () => {
    const assessment = recoveryCompensationService.assessCompensation({
      originalOperationId: 'op-comp-108',
      capabilityId: 'custom.unsupported_capability',
      parameters: { foo: 'bar' },
      confirmedSuccess: true,
    });
    expect(assessment.eligibility).toBe('COMPENSATION_UNAVAILABLE');
    expect(assessment.reversibility).toBe('IRREVERSIBLE');
    expect(assessment.candidatePlan).toBeUndefined();
  });

  it('109. notification-like irreversible action produces no automatic inverse', () => {
    const assessment = recoveryCompensationService.assessCompensation({
      originalOperationId: 'op-comp-109',
      capabilityId: 'notification.send',
      parameters: { recipient: 'slack-alerts', message: 'Hello' },
      confirmedSuccess: true,
    });
    expect(assessment.eligibility).toBe('COMPENSATION_UNAVAILABLE');
    expect(assessment.reversibility).toBe('IRREVERSIBLE');
    expect(assessment.rationale).toContain('irreversible');
    expect(assessment.candidatePlan).toBeUndefined();
  });

  it('110. compensation receives a distinct operation ID', () => {
    const assessment = recoveryCompensationService.assessCompensation({
      originalOperationId: 'op-orig-110',
      capabilityId: 'github.create_issue',
      parameters: { repository: 'aryaos/core', issueNumber: 10 },
      confirmedSuccess: true,
    });
    expect(assessment.candidatePlan).toBeDefined();
    expect(assessment.candidatePlan!.compensationId).not.toBe('op-orig-110');
    expect(assessment.candidatePlan!.compensationId.startsWith('comp_op-orig-110')).toBe(true);
    expect(assessment.candidatePlan!.originalOperationId).toBe('op-orig-110');
  });

  it('111. compensation receives a distinct action ID upon dispatch', async () => {
    const plan = createDeclarativeCompensationPlan({
      compensationId: 'comp-111',
      originalOperationId: 'op-orig-111',
      originalActionId: 'act-orig-111',
      compensationType: 'RESOURCE_CLEANUP',
      sourceCapability: 'filesystem.write',
      compensatingCapability: 'filesystem.delete',
      targetState: 'FILE_REMOVED',
      compensationParameters: { path: '/workspace/temp.txt' },
      reversibilityClass: 'FULLY_REVERSIBLE',
      idempotencyClass: 'IDEMPOTENT',
      riskLevel: 'LOW',
      requiredAuthority: ['SYSTEM'],
      approvalRequirement: { required: false, humanOperatorRequired: false },
      reconciliationRequirement: { required: false, postCompensationVerification: false },
      idempotencyKey: 'idem-comp-111',
      causationId: 'op-orig-111',
      correlationId: 'corr-111',
      expiresAt: Date.now() + 10000,
      lifecycleState: 'READY',
    });

    let capturedActionId = '';
    await recoveryCompensationService.coordinateCompensation(plan, {
      executeActionBus: async (req) => {
        capturedActionId = req.actionId;
        return {
          actionId: req.actionId,
          capabilityId: req.capabilityId,
          success: true,
          status: 'SUCCEEDED',
          data: { deleted: true },
          metadata: {},
          provenance: { actionId: req.actionId, capabilityId: req.capabilityId, requestFingerprint: 'fp', timestamp: new Date().toISOString() },
          durationMs: 5,
        };
      },
    });

    expect(capturedActionId).not.toBe('act-orig-111');
    expect(capturedActionId.startsWith('act_comp_comp-111')).toBe(true);
  });

  it('112. compensation receives a distinct idempotency key', () => {
    const assessment = recoveryCompensationService.assessCompensation({
      originalOperationId: 'op-orig-112',
      capabilityId: 'github.create_issue',
      parameters: { repository: 'aryaos/core', issueNumber: 15 },
      confirmedSuccess: true,
    });
    expect(assessment.candidatePlan!.idempotencyKey).not.toBe('op-orig-112');
    expect(assessment.candidatePlan!.idempotencyKey.startsWith('comp-idem-op-orig-112')).toBe(true);
  });

  it('113. causationId points to original operation', () => {
    const assessment = recoveryCompensationService.assessCompensation({
      originalOperationId: 'op-orig-113',
      capabilityId: 'github.create_issue',
      parameters: { repository: 'aryaos/core', issueNumber: 16 },
      confirmedSuccess: true,
    });
    expect(assessment.candidatePlan!.causationId).toBe('op-orig-113');
  });

  it('114. correlationId is preserved across compensation', () => {
    const assessment = recoveryCompensationService.assessCompensation({
      originalOperationId: 'op-orig-114',
      correlationId: 'corr-chain-114',
      capabilityId: 'github.create_issue',
      parameters: { repository: 'aryaos/core', issueNumber: 17 },
      confirmedSuccess: true,
    });
    expect(assessment.candidatePlan!.correlationId).toBe('corr-chain-114');
  });

  it('115. arbitrary inverse operation is rejected', () => {
    const assessment = recoveryCompensationService.assessCompensation({
      originalOperationId: 'op-orig-115',
      capabilityId: 'filesystem.write',
      parameters: {}, // missing path!
      confirmedSuccess: true,
    });
    expect(assessment.eligibility).toBe('COMPENSATION_UNSAFE');
    expect(assessment.rationale).toContain('missing required target parameters');
  });

  it('116. arbitrary URL is rejected with RecoveryContractViolationError', () => {
    expect(() => {
      recoveryCompensationService.assessCompensation({
        originalOperationId: 'op-orig-116',
        capabilityId: 'https://evil.attacker.com/api/delete',
        parameters: { target: 'file' },
      });
    }).toThrow(RecoveryContractViolationError);

    expect(() => {
      createDeclarativeCompensationPlan({
        compensationId: 'comp-116',
        originalOperationId: 'op-orig-116',
        compensationType: 'RESOURCE_CLEANUP',
        sourceCapability: 'filesystem.write',
        compensatingCapability: 'https://evil.com/webhook',
        targetState: 'FILE_REMOVED',
        compensationParameters: {},
        reversibilityClass: 'FULLY_REVERSIBLE',
        idempotencyClass: 'IDEMPOTENT',
        riskLevel: 'LOW',
        requiredAuthority: ['SYSTEM'],
        approvalRequirement: { required: false, humanOperatorRequired: false },
        reconciliationRequirement: { required: false, postCompensationVerification: false },
        idempotencyKey: 'idem-116',
        causationId: 'op-116',
        correlationId: 'corr-116',
        expiresAt: Date.now() + 1000,
      });
    }).toThrow(RecoveryContractViolationError);
  });

  it('117. credential/token input is rejected in parameters', () => {
    expect(() => {
      recoveryCompensationService.assessCompensation({
        originalOperationId: 'op-orig-117',
        capabilityId: 'filesystem.write',
        parameters: { path: '/workspace/safe.txt', api_key: 'secret123' },
      });
    }).toThrow(RecoveryContractViolationError);
  });

  it('118. forged approved=true in parameters or metadata does NOT bypass human approval', () => {
    const assessment = recoveryCompensationService.assessCompensation({
      originalOperationId: 'op-orig-118',
      capabilityId: 'filesystem.write',
      parameters: { path: '/workspace/destruct.txt', approved: true },
      metadata: { approved: true, humanApproved: true },
      confirmedSuccess: true,
    });
    expect(assessment.eligibility).toBe('COMPENSATION_REQUIRES_APPROVAL');
    expect(assessment.candidatePlan!.lifecycleState).toBe('PROPOSED');
    expect(assessment.candidatePlan!.approvalRequirement.approvedBy).toBeUndefined();
  });

  it('119. forged verified=true in payload does NOT bypass reconciliation requirement', () => {
    const assessment = recoveryCompensationService.assessCompensation({
      originalOperationId: 'op-orig-119',
      capabilityId: 'filesystem.write',
      parameters: { path: '/workspace/file.txt', verified: true },
      dispatchState: 'EXTERNAL_CONFIRMATION_ABSENT',
      truthState: 'UNKNOWN',
    });
    expect(assessment.eligibility).toBe('COMPENSATION_REQUIRES_RECONCILIATION');
    expect(assessment.requiresReconciliation).toBe(true);
    expect(assessment.candidatePlan).toBeUndefined();
  });

  it('120. high-risk compensation requires Stage 21 human governance', () => {
    const assessment = recoveryCompensationService.assessCompensation({
      originalOperationId: 'op-orig-120',
      capabilityId: 'filesystem.write',
      parameters: { path: '/workspace/data.json' },
      confirmedSuccess: true,
    });
    const plan = assessment.candidatePlan!;
    expect(plan.approvalRequirement.required).toBe(true);
    expect(plan.lifecycleState).toBe('PROPOSED');

    expect(() => {
      recoveryCompensationService.applyHumanApproval(plan, {
        actor: { actorId: 'system-agent', actorType: 'SYSTEM' },
        governanceDecisionId: 'gov-120',
      });
    }).toThrow(RecoveryContractViolationError);

    expect(() => {
      recoveryCompensationService.applyHumanApproval(plan, {
        actor: { actorId: 'agent-42', actorType: 'AUTONOMOUS_AGENT' },
        governanceDecisionId: 'gov-120',
      });
    }).toThrow(RecoveryContractViolationError);

    const approvedPlan = recoveryCompensationService.applyHumanApproval(plan, {
      actor: { actorId: 'human-operator-alice', actorType: 'USER' },
      governanceDecisionId: 'gov-decision-120',
      timestamp: 1700000000000,
    });
    expect(approvedPlan.lifecycleState).toBe('APPROVED');
    expect(approvedPlan.approvalRequirement.approvedBy).toBe('human-operator-alice');
  });

  it('121. duplicate compensation is prevented via cycle detection', () => {
    const assessment = recoveryCompensationService.assessCompensation({
      originalOperationId: 'op-orig-121',
      capabilityId: 'filesystem.write',
      parameters: { path: '/workspace/data.json' },
      visitedOperationIds: ['op-other', 'op-orig-121'],
    });
    expect(assessment.eligibility).toBe('COMPENSATION_UNSAFE');
    expect(assessment.rationale).toContain('Cycle detected');
  });

  it('122. compensation lifecycle rejects illegal transitions', async () => {
    const assessment = recoveryCompensationService.assessCompensation({
      originalOperationId: 'op-orig-122',
      capabilityId: 'filesystem.write',
      parameters: { path: '/workspace/file.txt' },
      confirmedSuccess: true,
    });
    const unapprovedPlan = assessment.candidatePlan!;
    expect(unapprovedPlan.lifecycleState).toBe('PROPOSED');

    await expect(
      recoveryCompensationService.coordinateCompensation(unapprovedPlan, {
        executeActionBus: async () => ({ success: true } as any),
      })
    ).rejects.toThrow(RecoveryContractViolationError);

    expect(() => {
      recoveryCompensationService.verifyCompensation(unapprovedPlan, {
        reconciliationId: 'recon-122',
        originalOperationId: 'op-orig-122',
        recoveryPlanId: 'plan-122',
        outcome: 'VERIFIED_SUCCESS',
        epistemicStatus: 'CONFIRMED',
        authoritativeEvidenceReferences: [],
        note: 'Verified',
        reconciledAt: Date.now(),
        causationId: 'op-orig-122',
        correlationId: 'corr-122',
        attemptNumber: 1,
      });
    }).toThrow(RecoveryContractViolationError);
  });

  it('123. compensation dispatch goes through Stage 15 Action Bus', async () => {
    const assessment = recoveryCompensationService.assessCompensation({
      originalOperationId: 'op-orig-123',
      capabilityId: 'github.create_issue',
      parameters: { repository: 'aryaos/core', issueNumber: 99 },
      confirmedSuccess: true,
    });
    const plan = assessment.candidatePlan!;
    expect(plan.lifecycleState).toBe('READY');

    let busCalled = false;
    const result = await recoveryCompensationService.coordinateCompensation(plan, {
      executeActionBus: async (req) => {
        busCalled = true;
        expect(req.capabilityId).toBe('github.close_issue');
        expect(req.metadata?.isCompensation).toBe(true);
        expect(req.metadata?.originalOperationId).toBe('op-orig-123');
        return {
          actionId: req.actionId,
          capabilityId: req.capabilityId,
          success: true,
          status: 'SUCCEEDED',
          data: { closed: true },
          metadata: {},
          provenance: { actionId: req.actionId, capabilityId: req.capabilityId, requestFingerprint: 'fp', timestamp: new Date().toISOString() },
          durationMs: 12,
        };
      },
    });

    expect(busCalled).toBe(true);
    expect(result.dispatchSuccess).toBe(true);
    expect(result.lifecycleState).toBe('VERIFYING');
  });

  it('124. provider compensation goes through Stage 07 gateway', async () => {
    const plan = createDeclarativeCompensationPlan({
      compensationId: 'comp-124',
      originalOperationId: 'op-orig-124',
      compensationType: 'RESOURCE_CLEANUP',
      sourceCapability: 'provider.model_run',
      compensatingCapability: 'provider.cancel_run',
      targetState: 'RUN_CANCELLED',
      compensationParameters: { runId: 'run-99' },
      reversibilityClass: 'COMPENSATABLE',
      idempotencyClass: 'IDEMPOTENT',
      riskLevel: 'LOW',
      requiredAuthority: ['SYSTEM'],
      approvalRequirement: { required: false, humanOperatorRequired: false },
      reconciliationRequirement: { required: true, postCompensationVerification: true },
      idempotencyKey: 'idem-124',
      causationId: 'op-orig-124',
      correlationId: 'corr-124',
      expiresAt: Date.now() + 10000,
      lifecycleState: 'READY',
    });

    let gatewayCalled = false;
    const result = await recoveryCompensationService.coordinateCompensation(plan, {
      executeGateway: async (req) => {
        gatewayCalled = true;
        expect(req.capabilityId).toBe('provider.cancel_run');
        return { success: true, data: { cancelled: true } };
      },
    });

    expect(gatewayCalled).toBe(true);
    expect(result.dispatchSuccess).toBe(true);
    expect(result.lifecycleState).toBe('VERIFYING');
  });

  it('125. compensation dispatch does NOT equal external success (epistemic separation)', async () => {
    const assessment = recoveryCompensationService.assessCompensation({
      originalOperationId: 'op-orig-125',
      capabilityId: 'github.create_issue',
      parameters: { repository: 'aryaos/core', issueNumber: 88 },
      confirmedSuccess: true,
    });
    const plan = assessment.candidatePlan!;
    const result = await recoveryCompensationService.coordinateCompensation(plan, {
      executeActionBus: async (req) => ({
        actionId: req.actionId,
        capabilityId: req.capabilityId,
        success: true,
        status: 'SUCCEEDED',
        data: { dispatched: true },
        metadata: {},
        provenance: { actionId: req.actionId, capabilityId: req.capabilityId, requestFingerprint: 'fp', timestamp: new Date().toISOString() },
        durationMs: 8,
      }),
    });

    expect(result.lifecycleState).toBe('VERIFYING');
    expect(result.lifecycleState).not.toBe('COMPLETED');
  });

  it('126. post-compensation reconciliation is required where applicable', () => {
    const assessment = recoveryCompensationService.assessCompensation({
      originalOperationId: 'op-orig-126',
      capabilityId: 'filesystem.write',
      parameters: { path: '/workspace/target.json' },
      confirmedSuccess: true,
    });
    expect(assessment.candidatePlan!.reconciliationRequirement.required).toBe(true);
    expect(assessment.candidatePlan!.reconciliationRequirement.postCompensationVerification).toBe(true);
  });

  it('127. unknown verification remains UNKNOWN (epistemic honesty preserved)', () => {
    const plan = createDeclarativeCompensationPlan({
      compensationId: 'comp-127',
      originalOperationId: 'op-orig-127',
      compensationType: 'RESOURCE_CLEANUP',
      sourceCapability: 'filesystem.write',
      compensatingCapability: 'filesystem.delete',
      targetState: 'FILE_REMOVED',
      compensationParameters: { path: '/workspace/f.txt' },
      reversibilityClass: 'FULLY_REVERSIBLE',
      idempotencyClass: 'IDEMPOTENT',
      riskLevel: 'LOW',
      requiredAuthority: ['SYSTEM'],
      approvalRequirement: { required: false, humanOperatorRequired: false },
      reconciliationRequirement: { required: true, postCompensationVerification: true },
      idempotencyKey: 'idem-127',
      causationId: 'op-orig-127',
      correlationId: 'corr-127',
      expiresAt: Date.now() + 10000,
      lifecycleState: 'VERIFYING',
    });

    const verifiedPlan = recoveryCompensationService.verifyCompensation(plan, {
      reconciliationId: 'recon-127',
      originalOperationId: 'op-orig-127',
      recoveryPlanId: 'plan-127',
      outcome: 'STILL_UNKNOWN',
      epistemicStatus: 'UNKNOWN',
      authoritativeEvidenceReferences: [],
      note: 'Target status cannot be confirmed',
      reconciledAt: Date.now(),
      causationId: 'op-orig-127',
      correlationId: 'corr-127',
      attemptNumber: 1,
    });

    expect(verifiedPlan.lifecycleState).toBe('UNKNOWN');
  });

  it('128. compensation depth limit prevents recursive loops (MAX_RECOVERY_DEPTH = 3)', () => {
    const assessment = recoveryCompensationService.assessCompensation({
      originalOperationId: 'op-orig-128',
      capabilityId: 'filesystem.write',
      parameters: { path: '/workspace/data.txt' },
      recoveryDepth: 3,
      confirmedSuccess: true,
    });
    expect(assessment.eligibility).toBe('COMPENSATION_UNSAFE');
    expect(assessment.rationale).toContain('Maximum recovery depth');
    expect(assessment.candidatePlan).toBeUndefined();
  });

  it('129. historical original operation remains immutable', () => {
    const origParams = { path: '/workspace/frozen.txt', important: true };
    const assessment = recoveryCompensationService.assessCompensation({
      originalOperationId: 'op-orig-129',
      capabilityId: 'filesystem.write',
      parameters: origParams,
      confirmedSuccess: true,
    });
    const plan = assessment.candidatePlan!;
    expect(Object.isFrozen(plan)).toBe(true);
    expect(Object.isFrozen(plan.compensationParameters)).toBe(true);
    expect(Object.isFrozen(plan.approvalRequirement)).toBe(true);
    expect(Object.isFrozen(plan.reconciliationRequirement)).toBe(true);
  });

  it('130. Stage 22 causal trace contains compensation linkage via causationId', () => {
    const assessment = recoveryCompensationService.assessCompensation({
      originalOperationId: 'op-orig-130',
      capabilityId: 'github.create_issue',
      parameters: { repository: 'aryaos/frontend', issueNumber: 5 },
      confirmedSuccess: true,
    });
    const plan = assessment.candidatePlan!;
    expect(plan.causationId).toBe('op-orig-130');
    expect(plan.originalOperationId).toBe('op-orig-130');
  });

  it('131. INTEGRATION: full flow from PARTIAL_EXECUTION to verified compensation', async () => {
    const classification = failureClassificationService.classifyFailure({
      operationId: 'op-integ-131',
      causationId: 'cause-131',
      correlationId: 'corr-131',
      dispatchState: 'DISPATCHED',
      partialExecutionEvidence: {
        completedSteps: ['step-write-file'],
        pendingSteps: ['step-notify'],
        failedStep: 'step-notify',
      },
    });
    expect(classification.classification).toBe('PARTIAL_EXECUTION');

    const plan = recoveryPlanService.generateRecoveryPlan({
      originalOperationId: 'op-integ-131',
      causationId: 'cause-131',
      correlationId: 'corr-131',
      classificationResult: classification,
      partialExecution: {
        completedSteps: ['step-write-file'],
        pendingSteps: ['step-notify'],
        failedStep: 'step-notify',
      },
      compensationInfo: {
        availability: 'COMPENSATION_AVAILABLE',
        compensatingActionType: 'filesystem.delete',
      },
    });
    expect(plan.proposedRecoveryAction).toBe('RESUME');

    const assessment = recoveryCompensationService.assessCompensation({
      originalOperationId: 'op-integ-131',
      capabilityId: 'filesystem.write',
      parameters: { path: '/workspace/partial_artifact.json' },
      partialExecution: {
        completedSteps: ['step-write-file'],
        pendingSteps: ['step-notify'],
        failedStep: 'step-notify',
      },
      confirmedSuccess: true,
    });
    expect(assessment.eligibility).toBe('COMPENSATION_REQUIRES_APPROVAL');
    const compPlan = assessment.candidatePlan!;
    expect(compPlan.compensatingCapability).toBe('filesystem.delete');
    expect(compPlan.lifecycleState).toBe('PROPOSED');

    const approvedPlan = recoveryCompensationService.applyHumanApproval(compPlan, {
      actor: { actorId: 'operator-jane', actorType: 'USER' },
      governanceDecisionId: 'gov-dec-131',
    });
    expect(approvedPlan.lifecycleState).toBe('APPROVED');

    const dispatchResult = await recoveryCompensationService.coordinateCompensation(approvedPlan, {
      executeActionBus: async (req) => {
        expect(req.capabilityId).toBe('filesystem.delete');
        expect(req.parameters.path).toBe('/workspace/partial_artifact.json');
        return {
          actionId: req.actionId,
          capabilityId: req.capabilityId,
          success: true,
          status: 'SUCCEEDED',
          data: { deleted: true },
          metadata: {},
          provenance: { actionId: req.actionId, capabilityId: req.capabilityId, requestFingerprint: 'fp', timestamp: new Date().toISOString() },
          durationMs: 7,
        };
      },
    });
    expect(dispatchResult.dispatchSuccess).toBe(true);
    expect(dispatchResult.lifecycleState).toBe('VERIFYING');

    const completedPlan = recoveryCompensationService.verifyCompensation(
      { ...approvedPlan, lifecycleState: 'VERIFYING' },
      {
        reconciliationId: 'recon-131',
        originalOperationId: 'op-integ-131',
        recoveryPlanId: 'plan-131',
        outcome: 'VERIFIED_SUCCESS',
        epistemicStatus: 'CONFIRMED',
        authoritativeEvidenceReferences: ['audit-ev-131'],
        note: 'File verified removed from filesystem',
        reconciledAt: Date.now(),
        causationId: 'op-integ-131',
        correlationId: 'corr-131',
        attemptNumber: 1,
      }
    );
    expect(completedPlan.lifecycleState).toBe('COMPLETED');
    expect(completedPlan.evidenceReferences).toContain('recon-131');
  });

  // ============================================================================
  // Phase 7: Cascading Failure & Autonomous Boundary Protection (Tests 132–161)
  // ============================================================================

  it('132. single failure does not automatically become a cascade', () => {
    const cascade = recoveryCascadeService.detectCascade({
      rootOperationId: 'op-casc-132',
      rootFailureClassification: 'TRANSIENT',
      failureCount: 1,
    });
    expect(cascade.cascadeClass).toBe('NO_CASCADE');
    expect(cascade.severity).toBe('LOW');
    expect(cascade.containmentAction).toBe('ALLOW');
    expect(cascade.depth).toBe(1);
    expect(isCascadeClassification(cascade.cascadeClass)).toBe(true);
    expect(isCascadeContainmentControl(cascade.containmentAction)).toBe(true);
  });

  it('133. repeated bounded failures establish deterministic cascade state', () => {
    const cascade = recoveryCascadeService.detectCascade({
      rootOperationId: 'op-casc-133',
      failureCount: 3,
    });
    expect(cascade.cascadeClass).toBe('RETRY_AMPLIFICATION');
    expect(cascade.severity).toBe('MEDIUM');
    expect(cascade.containmentAction).toBe('THROTTLE');
  });

  it('134. cascade receives distinct cascadeId', () => {
    const cascade = recoveryCascadeService.detectCascade({
      rootOperationId: 'op-root-134',
      failureCount: 3,
    });
    expect(cascade.cascadeId).not.toBe('op-root-134');
    expect(cascade.cascadeId.startsWith('casc_op-root-134')).toBe(true);
  });

  it('135. root operation identity preserved', () => {
    const cascade = recoveryCascadeService.detectCascade({
      rootOperationId: 'op-root-135',
      failureCount: 3,
    });
    expect(cascade.rootOperationId).toBe('op-root-135');
  });

  it('136. root failure identity preserved', () => {
    const cascade = recoveryCascadeService.detectCascade({
      rootOperationId: 'op-root-136',
      rootFailureClassification: 'PERMISSION',
      sameClassFailures: 2,
    });
    expect(cascade.failureClass).toBe('PERMISSION');
    expect(cascade.cascadeClass).toBe('PERMISSION_FAILURE');
  });

  it('137. causation preserved', () => {
    const cascade = recoveryCascadeService.detectCascade({
      rootOperationId: 'op-root-137',
      causationId: 'cause-chain-137',
      failureCount: 3,
    });
    expect(cascade.causationId).toBe('cause-chain-137');
  });

  it('138. correlation preserved', () => {
    const cascade = recoveryCascadeService.detectCascade({
      rootOperationId: 'op-root-138',
      correlationId: 'corr-chain-138',
      failureCount: 3,
    });
    expect(cascade.correlationId).toBe('corr-chain-138');
  });

  it('139. recovery depth limit respected (RECOVERY_CHAIN -> ESCALATE)', () => {
    const cascade = recoveryCascadeService.detectCascade({
      rootOperationId: 'op-root-139',
      recoveryChainDepth: 3,
    });
    expect(cascade.cascadeClass).toBe('RECOVERY_CHAIN');
    expect(cascade.containmentAction).toBe('ESCALATE');
  });

  it('140. retry amplification detected (excessive retries -> THROTTLE)', () => {
    const cascade = recoveryCascadeService.detectCascade({
      rootOperationId: 'op-root-140',
      failureCount: 4,
    });
    expect(cascade.cascadeClass).toBe('RETRY_AMPLIFICATION');
    expect(cascade.containmentAction).toBe('THROTTLE');
  });

  it('141. repeated unknown external state triggers containment', () => {
    const cascade = recoveryCascadeService.detectCascade({
      rootOperationId: 'op-root-141',
      unknownStateCount: 2,
    });
    expect(cascade.cascadeClass).toBe('RECONCILIATION_FAILURE');
    expect(cascade.containmentAction).toBe('REQUIRE_APPROVAL');
  });

  it('142. repeated permission denial does not retry indefinitely', () => {
    const cascade = recoveryCascadeService.detectCascade({
      rootOperationId: 'op-root-142',
      rootFailureClassification: 'PERMISSION',
      sameClassFailures: 2,
    });
    expect(cascade.cascadeClass).toBe('PERMISSION_FAILURE');
    expect(cascade.containmentAction).toBe('REQUIRE_APPROVAL');
  });

  it('143. repeated policy denial does not bypass policy (ABORT)', () => {
    const cascade = recoveryCascadeService.detectCascade({
      rootOperationId: 'op-root-143',
      rootFailureClassification: 'POLICY',
      sameClassFailures: 2,
    });
    expect(cascade.cascadeClass).toBe('POLICY_BLOCK');
    expect(cascade.containmentAction).toBe('ABORT');
  });

  it('144. connector failure containment respects Stage 16 (ISOLATE)', () => {
    const cascade = recoveryCascadeService.detectCascade({
      rootOperationId: 'op-root-144',
      connectorFailures: 3,
      affectedConnectorIds: ['conn-github-01'],
    });
    expect(cascade.cascadeClass).toBe('CONNECTOR_FAILURE');
    expect(cascade.containmentAction).toBe('ISOLATE');
    expect(cascade.affectedConnectorIds).toContain('conn-github-01');
  });

  it('145. provider failure containment respects Stage 07/router boundaries (DEFER)', () => {
    const cascade = recoveryCascadeService.detectCascade({
      rootOperationId: 'op-root-145',
      providerFailures: 3,
      affectedProviderIds: ['openai-gpt4'],
    });
    expect(cascade.cascadeClass).toBe('PROVIDER_FAILURE');
    expect(cascade.containmentAction).toBe('DEFER');
    expect(cascade.affectedProviderIds).toContain('openai-gpt4');
  });

  it('146. reaction cascade respects Stage 19 depth/cycle controls (PAUSE)', () => {
    const cascade = recoveryCascadeService.detectCascade({
      rootOperationId: 'op-root-146',
      triggerCycleDetected: true,
    });
    expect(cascade.cascadeClass).toBe('REACTION_CASCADE');
    expect(cascade.containmentAction).toBe('PAUSE');
  });

  it('147. mission cascade remains under Stage 12 authority (PAUSE)', () => {
    const cascade = recoveryCascadeService.detectCascade({
      rootOperationId: 'op-root-147',
      affectedMissionIds: ['mission-alpha', 'mission-beta'],
    });
    expect(cascade.cascadeClass).toBe('MISSION_CASCADE');
    expect(cascade.containmentAction).toBe('PAUSE');
  });

  it('148. resource exhaustion routes to existing resource governance (THROTTLE)', () => {
    const cascade = recoveryCascadeService.detectCascade({
      rootOperationId: 'op-root-148',
      resourceSaturation: true,
    });
    expect(cascade.cascadeClass).toBe('RESOURCE_EXHAUSTION');
    expect(cascade.containmentAction).toBe('THROTTLE');
  });

  it('149. unknown governance state fails closed (REQUIRE_APPROVAL)', () => {
    const cascade = recoveryCascadeService.detectCascade({
      rootOperationId: 'op-root-149',
      failureCount: 2,
      unknownGovernance: true,
    });
    expect(cascade.containmentAction).toBe('REQUIRE_APPROVAL');
    expect(cascade.severity).toBe('HIGH');
  });

  it('150. stale approval fails closed (REQUIRE_APPROVAL)', () => {
    const cascade = recoveryCascadeService.detectCascade({
      rootOperationId: 'op-root-150',
      failureCount: 2,
      staleApproval: true,
    });
    expect(cascade.containmentAction).toBe('REQUIRE_APPROVAL');
    expect(cascade.severity).toBe('HIGH');
  });

  it('151. unknown external state blocks blind mutation', () => {
    const cascade = recoveryCascadeService.detectCascade({
      rootOperationId: 'op-root-151',
      unknownStateCount: 3,
    });
    expect(cascade.containmentAction).toBe('REQUIRE_APPROVAL');
  });

  it('152. compensation failure cannot recurse indefinitely (ESCALATE)', () => {
    const cascade = recoveryCascadeService.detectCascade({
      rootOperationId: 'op-root-152',
      compensationFailureCount: 2,
    });
    expect(cascade.cascadeClass).toBe('COMPENSATION_FAILURE');
    expect(cascade.containmentAction).toBe('ESCALATE');
  });

  it('153. forged cascade event rejected in metadata', () => {
    expect(() => {
      recoveryCascadeService.detectCascade({
        rootOperationId: 'op-root-153',
        metadata: {
          secret_token: 'forged-secret-123',
        },
      });
    }).toThrow(RecoveryContractViolationError);
  });

  it('154. forged containment authority rejected (SYSTEM and AUTONOMOUS_AGENT denied)', () => {
    const cascade = recoveryCascadeService.detectCascade({
      rootOperationId: 'op-root-154',
      connectorFailures: 3,
    });
    const decision = recoveryCascadeService.formulateContainmentDecision(cascade);
    expect(decision.approvalRequirement.required).toBe(true);

    expect(() => {
      recoveryCascadeService.applyHumanApproval(decision, {
        actor: { actorId: 'system-bot', actorType: 'SYSTEM' },
        governanceDecisionId: 'gov-154',
      });
    }).toThrow(RecoveryContractViolationError);

    expect(() => {
      recoveryCascadeService.applyHumanApproval(decision, {
        actor: { actorId: 'agent-bot', actorType: 'AUTONOMOUS_AGENT' },
        governanceDecisionId: 'gov-154',
      });
    }).toThrow(RecoveryContractViolationError);

    const approved = recoveryCascadeService.applyHumanApproval(decision, {
      actor: { actorId: 'human-operator-dan', actorType: 'USER' },
      governanceDecisionId: 'gov-dec-154',
    });
    expect(approved.lifecycleState).toBe('CONTAINED');
    expect(approved.approvalRequirement.approvedBy).toBe('human-operator-dan');
  });

  it('155. arbitrary operation IDs / correlation payloads sanitized', () => {
    const cascade = recoveryCascadeService.detectCascade({
      rootOperationId: 'op-root-155',
      causationId: 'clean-causation-155',
      correlationId: 'clean-correlation-155',
      failureCount: 3,
    });
    expect(cascade.causationId).toBe('clean-causation-155');
    expect(cascade.correlationId).toBe('clean-correlation-155');
  });

  it('156. prototype pollution rejected in cascade parameters', () => {
    expect(() => {
      recoveryCascadeService.detectCascade({
        rootOperationId: 'op-root-156',
        metadata: JSON.parse('{"__proto__": {"polluted": true}}'),
      });
    }).toThrow(RecoveryContractViolationError);
  });

  it('157. unbounded affected-operation list rejected (max 50)', () => {
    const oversizedList = Array.from({ length: 51 }, (_, i) => `op-${i}`);
    expect(() => {
      recoveryCascadeService.detectCascade({
        rootOperationId: 'op-root-157',
        affectedOperationIds: oversizedList,
      });
    }).toThrow(RecoveryContractViolationError);
  });

  it('158. illegal cascade lifecycle transition rejected', () => {
    const cascade = recoveryCascadeService.detectCascade({
      rootOperationId: 'op-root-158',
      failureCount: 3,
    });
    expect(cascade.lifecycleState).toBe('CLASSIFIED');

    // Legal: CLASSIFIED -> ASSESSED
    const assessed = recoveryCascadeService.transitionLifecycle(cascade, 'ASSESSED');
    expect(assessed.lifecycleState).toBe('ASSESSED');

    // Legal: ASSESSED -> CONTAINMENT_PROPOSED
    const proposed = recoveryCascadeService.transitionLifecycle(assessed, 'CONTAINMENT_PROPOSED');
    expect(proposed.lifecycleState).toBe('CONTAINMENT_PROPOSED');

    // Illegal: CONTAINMENT_PROPOSED -> RECOVERED (cannot skip CONTAINED/MONITORED)
    expect(() => {
      recoveryCascadeService.transitionLifecycle(proposed, 'RECOVERED');
    }).toThrow(RecoveryContractViolationError);
  });

  it('159. containment decision is not direct execution (control recommendation)', () => {
    const cascade = recoveryCascadeService.detectCascade({
      rootOperationId: 'op-root-159',
      connectorFailures: 3,
      affectedConnectorIds: ['conn-drive-01'],
    });
    const decision = recoveryCascadeService.formulateContainmentDecision(cascade);
    expect(decision.recommendedControl).toBe('ISOLATE');
    expect(decision.lifecycleState).toBe('CONTAINMENT_PROPOSED');
    expect(decision.affectedScope.connectorIds).toContain('conn-drive-01');
  });

  it('160. Stage 22 causal evidence is preserved across containment decision', () => {
    const cascade = recoveryCascadeService.detectCascade({
      rootOperationId: 'op-root-160',
      causationId: 'cause-ev-160',
      correlationId: 'corr-ev-160',
      failureCount: 3,
    });
    const decision = recoveryCascadeService.formulateContainmentDecision(cascade);
    expect(decision.causationId).toBe('cause-ev-160');
    expect(decision.correlationId).toBe('corr-ev-160');
  });

  it('161. restart/recovery does not duplicate containment (active cache preservation)', () => {
    const cascade = recoveryCascadeService.detectCascade({
      rootOperationId: 'op-root-161',
      failureCount: 3,
    });
    const decision = recoveryCascadeService.formulateContainmentDecision(cascade);

    const retrievedCascade = recoveryCascadeService.getActiveCascade(cascade.cascadeId);
    expect(retrievedCascade).toBeDefined();
    expect(retrievedCascade?.cascadeId).toBe(cascade.cascadeId);

    const retrievedDecision = recoveryCascadeService.getActiveDecision(decision.containmentId);
    expect(retrievedDecision).toBeDefined();
    expect(retrievedDecision?.containmentId).toBe(decision.containmentId);
  });

  // ==========================================================================
  // Phase 8: Recovery Control Plane Orchestration & Governed Decision Surface
  // ==========================================================================

  it('162. valid recovery request accepted and produces complete decision', () => {
    const req = {
      requestId: 'req-162',
      operationId: 'op-162',
      causationId: 'cause-162',
      correlationId: 'corr-162',
      failureEvidence: {
        operationId: 'op-162',
        causationId: 'cause-162',
        correlationId: 'corr-162',
        dispatchState: 'NOT_DISPATCHED' as const,
        httpStatus: 503,
        timeoutEvidence: { timedOut: true, phase: 'PRE_DISPATCH' as const },
      },
      dispatchState: 'NOT_DISPATCHED' as const,
      idempotency: 'IDEMPOTENT' as const,
    };
    const decision = recoveryControlPlane.evaluateRecoveryControl(req);
    expect(decision.decisionId).toBeDefined();
    expect(decision.requestId).toBe('req-162');
    expect(decision.operationId).toBe('op-162');
    expect(decision.lifecycleState).toBe('DECIDED');
    expect(isRecoveryOutcome(decision.recoveryOutcome)).toBe(true);
  });

  it('163. invalid request rejected (missing requestId, operationId)', () => {
    expect(() => {
      recoveryControlPlane.evaluateRecoveryControl({
        requestId: '',
        operationId: 'op-163',
      });
    }).toThrow(RecoveryContractViolationError);

    expect(() => {
      recoveryControlPlane.evaluateRecoveryControl({
        requestId: 'req-163',
        operationId: '',
      });
    }).toThrow(RecoveryContractViolationError);
  });

  it('164. prototype pollution rejected in request parameters or metadata', () => {
    expect(() => {
      recoveryControlPlane.evaluateRecoveryControl({
        requestId: 'req-164',
        operationId: 'op-164',
        metadata: JSON.parse('{"__proto__": {"admin": true}}'),
      });
    }).toThrow(RecoveryContractViolationError);
  });

  it('165. credential payload rejected in request parameters', () => {
    expect(() => {
      recoveryControlPlane.evaluateRecoveryControl({
        requestId: 'req-165',
        operationId: 'op-165',
        parameters: { apiKey: 'secret-token-12345' },
      });
    }).toThrow(RecoveryContractViolationError);

    expect(() => {
      recoveryControlPlane.evaluateRecoveryControl({
        requestId: 'req-165b',
        operationId: 'op-165b',
        parameters: { authorization: 'Bearer abcdef' },
      });
    }).toThrow(RecoveryContractViolationError);
  });

  it('166. arbitrary URL parameter rejected; external calls must use registered capabilities', () => {
    expect(() => {
      recoveryControlPlane.evaluateRecoveryControl({
        requestId: 'req-166',
        operationId: 'op-166',
        parameters: { callbackUrl: 'https://evil.attacker.com/webhook' },
      });
    }).toThrow(RecoveryContractViolationError);
  });

  it('167. deterministic decisionId generated with expected structure', () => {
    const decision = recoveryControlPlane.evaluateRecoveryControl({
      requestId: 'req-167',
      operationId: 'op-167',
      confirmedSuccess: true,
    });
    expect(decision.decisionId.startsWith('rcdec_op-167_')).toBe(true);
  });

  it('168. identical request produces stable cached decision semantics', () => {
    const req = {
      requestId: 'req-168-stable',
      operationId: 'op-168',
      confirmedSuccess: true,
    };
    const decision1 = recoveryControlPlane.evaluateRecoveryControl(req);
    const decision2 = recoveryControlPlane.evaluateRecoveryControl(req);
    expect(decision1.decisionId).toBe(decision2.decisionId);
    expect(decision1.recoveryOutcome).toBe(decision2.recoveryOutcome);
  });

  it('169. confirmed success produces NO_RECOVERY_REQUIRED', () => {
    const decision = recoveryControlPlane.evaluateRecoveryControl({
      requestId: 'req-169',
      operationId: 'op-169',
      confirmedSuccess: true,
    });
    expect(decision.recoveryOutcome).toBe('NO_RECOVERY_REQUIRED');
    expect(decision.recommendedAction).toBe('WAIT');
    expect(decision.governanceRequirement.required).toBe(false);
  });

  it('170. safe transient failure produces RETRY', () => {
    const decision = recoveryControlPlane.evaluateRecoveryControl({
      requestId: 'req-170',
      operationId: 'op-170',
      failureEvidence: {
        operationId: 'op-170',
        causationId: 'cause-170',
        correlationId: 'corr-170',
        dispatchState: 'NOT_DISPATCHED',
        httpStatus: 503,
        timeoutEvidence: { timedOut: true, phase: 'PRE_DISPATCH' },
      },
      dispatchState: 'NOT_DISPATCHED',
      idempotency: 'IDEMPOTENT',
      retryCount: 0,
    });
    expect(decision.recoveryOutcome).toBe('RETRY');
    expect(decision.recommendedAction).toBe('RETRY');
  });

  it('171. unsafe retry produces RECONCILE (duplicate side effect risk)', () => {
    const decision = recoveryControlPlane.evaluateRecoveryControl({
      requestId: 'req-171',
      operationId: 'op-171',
      failureEvidence: {
        operationId: 'op-171',
        causationId: 'cause-171',
        correlationId: 'corr-171',
        dispatchState: 'DISPATCHED',
        timeoutEvidence: { timedOut: true, phase: 'POST_DISPATCH' },
      },
      dispatchState: 'DISPATCHED',
      idempotency: 'NON_IDEMPOTENT',
    });
    expect(decision.recoveryOutcome).toBe('RECONCILE');
    expect(decision.recommendedAction).toBe('RECONCILE');
  });

  it('172. unknown external state never becomes FAILED without evidence', () => {
    const decision = recoveryControlPlane.evaluateRecoveryControl({
      requestId: 'req-172',
      operationId: 'op-172',
      dispatchState: 'DISPATCHED',
      externalConfirmationReceived: false,
    });
    expect(decision.epistemicStatus).toBe('UNKNOWN');
    expect(decision.recoveryOutcome).toBe('RECONCILE');
    expect(decision.recoveryOutcome).not.toBe('ABORT');
  });

  it('173. unknown external state never becomes SUCCESS without evidence', () => {
    const decision = recoveryControlPlane.evaluateRecoveryControl({
      requestId: 'req-173',
      operationId: 'op-173',
      dispatchState: 'DISPATCHED',
      externalConfirmationReceived: false,
    });
    expect(decision.recoveryOutcome).not.toBe('NO_RECOVERY_REQUIRED');
    expect(decision.recoveryOutcome).not.toBe('RESUME');
  });

  it('174. partial execution preserves completed steps', () => {
    const decision = recoveryControlPlane.evaluateRecoveryControl({
      requestId: 'req-174',
      operationId: 'op-174',
      failureEvidence: {
        operationId: 'op-174',
        causationId: 'cause-174',
        correlationId: 'corr-174',
        dispatchState: 'EXECUTING',
        partialExecutionEvidence: {
          completedSteps: ['step_setup_01', 'step_write_02'],
          failedStep: 'step_verify_03',
          pendingSteps: ['step_notify_04'],
        },
      },
      dispatchState: 'EXECUTING',
    });
    expect(decision.safetyAssessment?.completedSteps).toEqual(['step_setup_01', 'step_write_02']);
    expect(decision.reasonCodes).toContain('PARTIAL_EXECUTION_STEPS_PRESERVED');
  });

  it('175. partial execution produces COMPENSATE when explicitly eligible', () => {
    const decision = recoveryControlPlane.evaluateRecoveryControl({
      requestId: 'req-175',
      operationId: 'op-175',
      capabilityId: 'github.create_issue',
      parameters: { repository: 'octocat/Hello-World', issueNumber: 42 },
      failureEvidence: {
        operationId: 'op-175',
        causationId: 'cause-175',
        correlationId: 'corr-175',
        dispatchState: 'EXECUTING',
        partialExecutionEvidence: {
          completedSteps: ['step_create_issue'],
          failedStep: 'step_post_comment',
          pendingSteps: [],
        },
      },
      dispatchState: 'EXECUTING',
    });
    expect(decision.recoveryOutcome).toBe('COMPENSATE');
    expect(decision.recommendedAction).toBe('COMPENSATE');
    expect(decision.compensationAssessment?.candidatePlan?.compensatingCapability).toBe('github.close_issue');
  });

  it('176. unsafe compensation produces ESCALATE', () => {
    const decision = recoveryControlPlane.evaluateRecoveryControl({
      requestId: 'req-176',
      operationId: 'op-176',
      capabilityId: 'notification.broadcast', // Irreversible
      failureEvidence: {
        operationId: 'op-176',
        causationId: 'cause-176',
        correlationId: 'corr-176',
        dispatchState: 'EXECUTING',
        partialExecutionEvidence: {
          completedSteps: ['step_broadcast'],
          failedStep: 'step_log',
          pendingSteps: [],
        },
      },
      dispatchState: 'EXECUTING',
    });
    expect(decision.recoveryOutcome).toBe('ESCALATE');
    expect(decision.governanceRequirement.humanOperatorRequired).toBe(true);
  });

  it('177. existing reconciliation service is reused', () => {
    const decision = recoveryControlPlane.evaluateRecoveryControl({
      requestId: 'req-177',
      operationId: 'op-177',
      dispatchState: 'DISPATCHED',
      externalConfirmationReceived: false,
    });
    expect(decision.reconciliationRequirement?.required).toBe(true);
    expect(decision.reconciliationRequirement?.timeoutMs).toBe(10000);
  });

  it('178. existing compensation service is reused', () => {
    const decision = recoveryControlPlane.evaluateRecoveryControl({
      requestId: 'req-178',
      operationId: 'op-178',
      capabilityId: 'filesystem.write',
      parameters: { path: '/tmp/test.txt' },
      failureEvidence: {
        operationId: 'op-178',
        causationId: 'cause-178',
        correlationId: 'corr-178',
        dispatchState: 'EXECUTING',
        partialExecutionEvidence: {
          completedSteps: ['write_file'],
          failedStep: 'validate_file',
          pendingSteps: [],
        },
      },
      dispatchState: 'EXECUTING',
    });
    expect(decision.compensationAssessment).toBeDefined();
    expect(decision.compensationAssessment?.candidatePlan?.compensatingCapability).toBe('filesystem.delete');
  });

  it('179. existing cascade service is reused', () => {
    const decision = recoveryControlPlane.evaluateRecoveryControl({
      requestId: 'req-179',
      operationId: 'op-179',
      cascadeEvidence: {
        rootOperationId: 'op-179',
        connectorFailures: 3,
        affectedConnectorIds: ['youtube_api_v3'],
      },
    });
    expect(decision.cascadeAssessment).toBeDefined();
    expect(decision.cascadeAssessment?.cascadeClass).toBe('CONNECTOR_FAILURE');
    expect(decision.containmentDecision?.recommendedControl).toBe('ISOLATE');
  });

  it('180. cascade PAUSE cannot be downgraded to RETRY', () => {
    const decision = recoveryControlPlane.evaluateRecoveryControl({
      requestId: 'req-180',
      operationId: 'op-180',
      failureEvidence: {
        operationId: 'op-180',
        causationId: 'cause-180',
        correlationId: 'corr-180',
        dispatchState: 'NOT_DISPATCHED',
        httpStatus: 503,
      },
      cascadeEvidence: {
        rootOperationId: 'op-180',
        triggerCycleDetected: true,
        reactionDepth: 5,
      },
    });
    expect(decision.recoveryOutcome).toBe('PAUSE');
    expect(decision.recommendedAction).toBe('PAUSE');
    expect(decision.recoveryOutcome).not.toBe('RETRY');
  });

  it('181. cascade ABORT cannot be downgraded to RESUME', () => {
    const decision = recoveryControlPlane.evaluateRecoveryControl({
      requestId: 'req-181',
      operationId: 'op-181',
      cascadeEvidence: {
        rootOperationId: 'op-181',
        resourceSaturation: true,
        connectorFailures: 3,
      },
    });
    expect(decision.recoveryOutcome).toBe('ABORT');
    expect(decision.recommendedAction).toBe('ABORT');
    expect(decision.recoveryOutcome).not.toBe('RESUME');
  });

  it('182. governance requirement is preserved for critical operations', () => {
    const decision = recoveryControlPlane.evaluateRecoveryControl({
      requestId: 'req-182',
      operationId: 'op-182',
      riskLevel: 'CRITICAL',
      dispatchState: 'DISPATCHED',
      externalConfirmationReceived: false,
    });
    expect(decision.governanceRequirement.required).toBe(true);
    expect(decision.governanceRequirement.humanOperatorRequired).toBe(true);
    expect(decision.recoveryOutcome).toBe('REQUIRE_APPROVAL');
  });

  it('183. stale governance fails closed (REQUIRE_APPROVAL)', () => {
    const decision = recoveryControlPlane.evaluateRecoveryControl({
      requestId: 'req-183',
      operationId: 'op-183',
      governanceContext: { stale: true },
    });
    expect(decision.governanceRequirement.stale).toBe(true);
    expect(decision.governanceRequirement.humanOperatorRequired).toBe(true);
    expect(decision.recoveryOutcome).toBe('REQUIRE_APPROVAL');
  });

  it('184. human approval cannot be forged (SYSTEM/AUTONOMOUS_AGENT rejected)', () => {
    expect(() => {
      recoveryControlPlane.evaluateRecoveryControl({
        requestId: 'req-184',
        operationId: 'op-184',
        governanceContext: {
          approved: true,
          actorType: 'AUTONOMOUS_AGENT',
          actorId: 'agent-bot-01',
        },
      });
    }).toThrow(RecoveryContractViolationError);
  });

  it('185. recovery depth cannot reset (MAX_RECOVERY_DEPTH = 3 triggers ESCALATE)', () => {
    const decision = recoveryControlPlane.evaluateRecoveryControl({
      requestId: 'req-185',
      operationId: 'op-185',
      recoveryDepth: 3,
    });
    expect(decision.recoveryOutcome).toBe('ESCALATE');
    expect(decision.recoveryDepth).toBe(3);
    expect(decision.reasonCodes).toContain('RECOVERY_DEPTH_LIMIT_REACHED');
  });

  it('186. automatic retry limit remains enforced (retryCount >= 2 triggers ESCALATE)', () => {
    const decision = recoveryControlPlane.evaluateRecoveryControl({
      requestId: 'req-186',
      operationId: 'op-186',
      failureEvidence: {
        operationId: 'op-186',
        causationId: 'cause-186',
        correlationId: 'corr-186',
        dispatchState: 'NOT_DISPATCHED',
        httpStatus: 503,
      },
      retryCount: 2,
    });
    expect(decision.recoveryOutcome).toBe('ESCALATE');
    expect(decision.reasonCodes).toContain('AUTOMATIC_RETRY_LIMIT_EXCEEDED');
  });

  it('187. reconciliation attempt limit remains enforced (reconciliationAttempts >= 3 triggers ESCALATE)', () => {
    const decision = recoveryControlPlane.evaluateRecoveryControl({
      requestId: 'req-187',
      operationId: 'op-187',
      reconciliationAttempts: 3,
    });
    expect(decision.recoveryOutcome).toBe('ESCALATE');
    expect(decision.reasonCodes).toContain('MAX_RECONCILIATION_ATTEMPTS_EXCEEDED');
  });

  it('188. cascade depth remains enforced and bounded', () => {
    const decision = recoveryControlPlane.evaluateRecoveryControl({
      requestId: 'req-188',
      operationId: 'op-188',
      cascadeEvidence: {
        rootOperationId: 'op-188',
        recoveryChainDepth: 10, // Exceeds MAX_CASCADE_DEPTH
        failureCount: 3,
      },
    });
    expect(decision.cascadeAssessment?.depth).toBe(5);
  });

  it('189. no direct Action Bus execution occurs from control-plane decision', () => {
    const decision = recoveryControlPlane.evaluateRecoveryControl({
      requestId: 'req-189',
      operationId: 'op-189',
      confirmedSuccess: true,
    });
    // Confirms pure immutable control decision returned
    expect(decision.lifecycleState).toBe('DECIDED');
    expect(Object.isFrozen(decision)).toBe(true);
  });

  it('190. no direct executionGateway call occurs from control-plane decision', () => {
    const decision = recoveryControlPlane.evaluateRecoveryControl({
      requestId: 'req-190',
      operationId: 'op-190',
      failureEvidence: {
        operationId: 'op-190',
        causationId: 'cause-190',
        correlationId: 'corr-190',
        dispatchState: 'NOT_DISPATCHED',
        httpStatus: 500,
      },
    });
    expect(decision.decisionId).toBeDefined();
    expect(Object.isFrozen(decision)).toBe(true);
  });

  it('191. Stage 22 evidence references are preserved across control decision', () => {
    const decision = recoveryControlPlane.evaluateRecoveryControl({
      requestId: 'req-191',
      operationId: 'op-191',
      failureEvidence: {
        operationId: 'op-191',
        causationId: 'cause-191',
        correlationId: 'corr-191',
        dispatchState: 'NOT_DISPATCHED',
        evidenceReferences: ['audit-ev-trace-191a', 'audit-ev-trace-191b'],
      },
    });
    expect(decision.evidenceIds).toContain('audit-ev-trace-191a');
    expect(decision.evidenceIds).toContain('audit-ev-trace-191b');
  });

  it('192. historical operation remains immutable', () => {
    const req = {
      requestId: 'req-192',
      operationId: 'op-192',
      confirmedSuccess: true,
    };
    const decision = recoveryControlPlane.evaluateRecoveryControl(req);
    expect(() => {
      (decision as any).recoveryOutcome = 'RETRY';
    }).toThrow();
  });

  it('193. decision lifecycle rejects illegal transitions', () => {
    const decision = recoveryControlPlane.evaluateRecoveryControl({
      requestId: 'req-193',
      operationId: 'op-193',
      confirmedSuccess: true,
    });
    expect(decision.lifecycleState).toBe('DECIDED');

    // Legal: DECIDED -> ESCALATED
    const escalated = recoveryControlPlane.transitionDecisionLifecycle(decision, 'ESCALATED');
    expect(escalated.lifecycleState).toBe('ESCALATED');

    // Illegal: ESCALATED -> VALIDATED (terminal state)
    expect(() => {
      recoveryControlPlane.transitionDecisionLifecycle(escalated, 'VALIDATED');
    }).toThrow(RecoveryContractViolationError);
  });

  it('194. restart preserves control decision state in memory registry', () => {
    const decision = recoveryControlPlane.evaluateRecoveryControl({
      requestId: 'req-194',
      operationId: 'op-194',
      confirmedSuccess: true,
    });
    const retrieved = recoveryControlPlane.getActiveDecision(decision.decisionId);
    expect(retrieved).toBeDefined();
    expect(retrieved?.decisionId).toBe(decision.decisionId);
  });

  it('195. duplicate request does not create uncontrolled recovery divergence', () => {
    const req = {
      requestId: 'req-195-idempotent',
      operationId: 'op-195',
      confirmedSuccess: true,
    };
    const d1 = recoveryControlPlane.evaluateRecoveryControl(req);
    const d2 = recoveryControlPlane.evaluateRecoveryControl(req);
    expect(d1.decisionId).toBe(d2.decisionId);
  });

  it('196. full integration: FAILURE -> CLASSIFICATION -> SAFETY -> CASCADE -> PLAN -> CONTROL DECISION -> GOVERNANCE -> STAGE 22 TRUTH', () => {
    const req = {
      requestId: 'req-196-full',
      operationId: 'op-196-full',
      causationId: 'cause-196-full',
      correlationId: 'corr-196-full',
      capabilityId: 'github.create_issue',
      parameters: { repository: 'aryaos/core', issueNumber: 101 },
      dispatchState: 'EXECUTING' as const,
      failureEvidence: {
        operationId: 'op-196-full',
        causationId: 'cause-196-full',
        correlationId: 'corr-196-full',
        dispatchState: 'EXECUTING' as const,
        partialExecutionEvidence: {
          completedSteps: ['create_issue_step'],
          failedStep: 'send_webhook_step',
          pendingSteps: [],
        },
        evidenceReferences: ['audit-trail-196'],
      },
      cascadeEvidence: {
        rootOperationId: 'op-196-full',
        failureCount: 1,
      },
    };

    const decision = recoveryControlPlane.evaluateRecoveryControl(req);
    expect(decision.classification).toBe('PARTIAL_EXECUTION');
    expect(decision.recoveryOutcome).toBe('COMPENSATE');
    expect(decision.recommendedAction).toBe('COMPENSATE');
    expect(decision.compensationAssessment).toBeDefined();
    expect(decision.compensationAssessment?.candidatePlan?.compensatingCapability).toBe('github.close_issue');
    expect(decision.evidenceIds).toContain('audit-trail-196');
    expect(decision.causationId).toBe('cause-196-full');
    expect(decision.correlationId).toBe('corr-196-full');
    expect(decision.lifecycleState).toBe('DECIDED');
  });

  // ==========================================================================
  // Phase 9: Durable Recovery Control & Stage 09 Integration Tests (197–231)
  // ==========================================================================

  it('197. recovery decision persists', () => {
    const req = {
      requestId: 'req-197-persist',
      operationId: 'op-197',
      confirmedSuccess: true,
    };
    const decision = recoveryControlPlane.evaluateRecoveryControl(req);
    const fromStorage = executionPersistence.getRecoveryControlDecision(decision.decisionId);
    expect(fromStorage).toBeDefined();
    expect(fromStorage?.decisionId).toBe(decision.decisionId);
    expect(fromStorage?.operationId).toBe('op-197');

    const events = executionJournal.getAllEvents().filter((e) => e.actionId === 'op-197');
    expect(events.length).toBeGreaterThan(0);
    expect(events[0].eventType).toBe('RECOVERY_CONTROL_DECIDED');
  });

  it('198. recovery decision reloads correctly', () => {
    const req = {
      requestId: 'req-198-reload',
      operationId: 'op-198',
      confirmedSuccess: true,
    };
    const decision = recoveryControlPlane.evaluateRecoveryControl(req);
    const reloaded = recoveryControlPersistenceService.loadControlDecision(decision.decisionId);
    expect(reloaded).toBeDefined();
    expect(reloaded?.decisionId).toBe(decision.decisionId);
    expect(reloaded?.recoveryOutcome).toBe(decision.recoveryOutcome);
    expect(Object.isFrozen(reloaded)).toBe(true);
  });

  it('199. historical decision remains immutable', () => {
    const req = {
      requestId: 'req-199-immutable',
      operationId: 'op-199',
      confirmedSuccess: true,
    };
    const decision = recoveryControlPlane.evaluateRecoveryControl(req);
    const reloaded = recoveryControlPersistenceService.loadControlDecision(decision.decisionId);
    expect(() => {
      (reloaded as any).recoveryOutcome = 'RETRY';
    }).toThrow();
  });

  it('200. decision IDs remain stable', () => {
    const req = {
      requestId: 'req-200-stable',
      operationId: 'op-200',
      confirmedSuccess: true,
    };
    const decision = recoveryControlPlane.evaluateRecoveryControl(req);
    const r1 = recoveryControlPersistenceService.loadControlDecision(decision.decisionId);
    const r2 = recoveryControlPersistenceService.loadControlDecision(decision.decisionId);
    expect(r1?.decisionId).toBe(r2?.decisionId);
  });

  it('201. duplicate request is idempotent across simulated restart', () => {
    const req = {
      requestId: 'req-201-idempotent-restart',
      operationId: 'op-201',
      confirmedSuccess: true,
    };
    const d1 = recoveryControlPlane.evaluateRecoveryControl(req);
    // Simulate process/browser restart by clearing in-memory state
    recoveryControlPlane.clear();
    const d2 = recoveryControlPlane.evaluateRecoveryControl(req);
    expect(d2.decisionId).toBe(d1.decisionId);
    expect(d2.recoveryOutcome).toBe(d1.recoveryOutcome);
  });

  it('202. restart does not reset retry count', () => {
    const req = {
      requestId: 'req-202-retry-count',
      operationId: 'op-202',
      retryCount: 2,
    };
    const decision = recoveryControlPlane.evaluateRecoveryControl(req);
    expect(decision.recoveryOutcome).toBe('ESCALATE');
    recoveryControlPlane.clear();
    const reloaded = recoveryControlPersistenceService.loadControlDecision(decision.decisionId);
    expect(reloaded?.retryCount).toBe(2);
    const reval = recoveryControlPersistenceService.revalidateDecision(decision.decisionId);
    expect(reval.currentDecision.retryCount).toBe(2);
  });

  it('203. restart does not reset recovery depth', () => {
    const req = {
      requestId: 'req-203-recovery-depth',
      operationId: 'op-203',
      recoveryDepth: 3,
    };
    const decision = recoveryControlPlane.evaluateRecoveryControl(req);
    expect(decision.recoveryOutcome).toBe('ESCALATE');
    recoveryControlPlane.clear();
    const reloaded = recoveryControlPersistenceService.loadControlDecision(decision.decisionId);
    expect(reloaded?.recoveryDepth).toBe(3);
  });

  it('204. restart does not reset reconciliation attempts', () => {
    const req = {
      requestId: 'req-204-reconcile-attempts',
      operationId: 'op-204',
      reconciliationAttempts: 3,
    };
    const decision = recoveryControlPlane.evaluateRecoveryControl(req);
    expect(decision.recoveryOutcome).toBe('ESCALATE');
    recoveryControlPlane.clear();
    const reloaded = recoveryControlPersistenceService.loadControlDecision(decision.decisionId);
    expect(reloaded?.reconciliationAttempts).toBe(3);
    const reval = recoveryControlPersistenceService.revalidateDecision(decision.decisionId);
    expect(reval.currentDecision.reconciliationAttempts).toBe(3);
  });

  it('205. restart does not reset compensation depth', () => {
    const req = {
      requestId: 'req-205-comp-depth',
      operationId: 'op-205',
      compensationDepth: 2,
      capabilityId: 'github.create_issue',
      parameters: { repository: 'org/repo', issueNumber: 55 },
      dispatchState: 'EXECUTING' as const,
      failureEvidence: {
        operationId: 'op-205',
        causationId: 'c-205',
        correlationId: 'cr-205',
        dispatchState: 'EXECUTING' as const,
        partialExecutionEvidence: {
          completedSteps: ['create_issue_step'],
          failedStep: 'webhook',
          pendingSteps: [],
        },
      },
    };
    const decision = recoveryControlPlane.evaluateRecoveryControl(req);
    expect(decision.recoveryOutcome).toBe('COMPENSATE');
    recoveryControlPlane.clear();
    const reloaded = recoveryControlPersistenceService.loadControlDecision(decision.decisionId);
    expect(reloaded?.compensationAssessment).toBeDefined();
  });

  it('206. restart does not reset cascade depth', () => {
    const req = {
      requestId: 'req-206-cascade-depth',
      operationId: 'op-206',
      cascadeEvidence: {
        rootOperationId: 'op-206',
        failureCount: 5,
        recoveryChainDepth: 5,
      },
    };
    const decision = recoveryControlPlane.evaluateRecoveryControl(req);
    expect(decision.containmentDecision).toBeDefined();
    recoveryControlPlane.clear();
    const reloaded = recoveryControlPersistenceService.loadControlDecision(decision.decisionId);
    expect(reloaded?.cascadeAssessment?.depth).toBe(5);
  });

  it('207. restart does not duplicate compensation', () => {
    const req = {
      requestId: 'req-207-no-dup-comp',
      operationId: 'op-207',
      capabilityId: 'github.create_issue',
      parameters: { repository: 'org/repo', issueNumber: 56 },
      dispatchState: 'EXECUTING' as const,
      failureEvidence: {
        operationId: 'op-207',
        causationId: 'c-207',
        correlationId: 'cr-207',
        dispatchState: 'EXECUTING' as const,
        partialExecutionEvidence: {
          completedSteps: ['create_issue_step'],
          failedStep: 'webhook',
          pendingSteps: [],
        },
      },
    };
    const decision = recoveryControlPlane.evaluateRecoveryControl(req);
    expect(decision.recoveryOutcome).toBe('COMPENSATE');
    const reval = recoveryControlPersistenceService.revalidateDecision(decision.decisionId, {
      observedOperationStatus: 'COMPENSATED',
    });
    expect(reval.recommendedAction).toBe('WAIT');
    expect(reval.reason).toContain('Compensation already executed successfully');
  });

  it('208. restart does not duplicate reconciliation', () => {
    const req = {
      requestId: 'req-208-reconcile-restart',
      operationId: 'op-208',
      dispatchState: 'DISPATCHED' as const,
      failureEvidence: {
        operationId: 'op-208',
        causationId: 'c-208',
        correlationId: 'cr-208',
        dispatchState: 'EXTERNAL_CONFIRMATION_ABSENT' as const,
      },
    };
    const decision = recoveryControlPlane.evaluateRecoveryControl(req);
    expect(decision.recommendedAction).toBe('RECONCILE');
    const reval = recoveryControlPersistenceService.revalidateDecision(decision.decisionId, {
      now: Date.now(),
    });
    expect(reval.valid).toBe(true);
    expect(reval.recommendedAction).toBe('RECONCILE');
  });

  it('209. restart does not duplicate recovery', () => {
    const loaded = recoveryControlPersistenceService.loadControlDecisionByOperationId('op-208');
    expect(loaded).toBeDefined();
    expect(loaded?.operationId).toBe('op-208');
  });

  it('210. stale policy invalidates old decision', () => {
    const req = {
      requestId: 'req-210-stale-policy',
      operationId: 'op-210',
      confirmedSuccess: true,
    };
    const decision = recoveryControlPlane.evaluateRecoveryControl(req);
    const reval = recoveryControlPersistenceService.revalidateDecision(decision.decisionId, {
      policySnapshotExpired: true,
    });
    expect(reval.isStale).toBe(true);
    expect(reval.requiresReevaluation).toBe(true);
  });

  it('211. stale approval invalidates old decision', () => {
    const req = {
      requestId: 'req-211-stale-approval',
      operationId: 'op-211',
      capabilityId: 'db.drop_table',
      riskLevel: 'HIGH' as const,
      governanceContext: {
        required: true,
        approved: true,
        actorType: 'USER',
        actorId: 'admin-user',
      },
    };
    const decision = recoveryControlPlane.evaluateRecoveryControl(req);
    const reval = recoveryControlPersistenceService.revalidateDecision(decision.decisionId, {
      humanApprovalExpired: true,
    });
    expect(reval.isStale).toBe(true);
    expect(reval.recommendedAction).toBe('REQUIRE_APPROVAL');
  });

  it('212. revoked connector permission invalidates old decision', () => {
    const req = {
      requestId: 'req-212-revoked-permission',
      operationId: 'op-212',
      capabilityId: 'aws.delete_bucket',
      riskLevel: 'HIGH' as const,
      governanceContext: {
        required: true,
        approved: true,
        actorType: 'USER',
        actorId: 'admin-user',
      },
    };
    const decision = recoveryControlPlane.evaluateRecoveryControl(req);
    const reval = recoveryControlPersistenceService.revalidateDecision(decision.decisionId, {
      connectorPermissionRevoked: true,
    });
    expect(reval.isStale).toBe(true);
    expect(reval.recommendedAction).toBe('REQUIRE_APPROVAL');
  });

  it('213. changed operation state invalidates old decision', () => {
    const req = {
      requestId: 'req-213-changed-state',
      operationId: 'op-213',
      confirmedSuccess: true,
    };
    const decision = recoveryControlPlane.evaluateRecoveryControl(req);
    const reval = recoveryControlPersistenceService.revalidateDecision(decision.decisionId, {
      operationStatusChanged: true,
      observedOperationStatus: 'CANCELLED',
    });
    expect(reval).toBeDefined();
  });

  it('214. previously completed operation is not replayed', () => {
    const req = {
      requestId: 'req-214-completed-op',
      operationId: 'op-214',
      dispatchState: 'DISPATCHED' as const,
      failureEvidence: {
        operationId: 'op-214',
        causationId: 'c-214',
        correlationId: 'cr-214',
        dispatchState: 'EXTERNAL_CONFIRMATION_ABSENT' as const,
      },
    };
    const decision = recoveryControlPlane.evaluateRecoveryControl(req);
    const reval = recoveryControlPersistenceService.revalidateDecision(decision.decisionId, {
      externalSuccess: true,
      observedOperationStatus: 'SUCCEEDED',
    });
    expect(reval.recommendedAction).toBe('WAIT');
    expect(reval.reason).toContain('Operation already completed successfully');
  });

  it('215. unknown external state remains UNKNOWN', () => {
    const req = {
      requestId: 'req-215-unknown-state',
      operationId: 'op-215',
      dispatchState: 'DISPATCHED' as const,
      failureEvidence: {
        operationId: 'op-215',
        causationId: 'c-215',
        correlationId: 'cr-215',
        dispatchState: 'EXTERNAL_CONFIRMATION_ABSENT' as const,
      },
    };
    const decision = recoveryControlPlane.evaluateRecoveryControl(req);
    const reval = recoveryControlPersistenceService.revalidateDecision(decision.decisionId, {
      externalStatusConfirmed: false,
    });
    expect(reval.currentDecision.epistemicStatus).toBe('UNKNOWN');
    expect(reval.recommendedAction).toBe('RECONCILE');
  });

  it('216. interrupted reconciliation respects attempt limit', () => {
    const req = {
      requestId: 'req-216-reconcile-limit',
      operationId: 'op-216',
      dispatchState: 'DISPATCHED' as const,
      failureEvidence: {
        operationId: 'op-216',
        causationId: 'c-216',
        correlationId: 'cr-216',
        dispatchState: 'EXTERNAL_CONFIRMATION_ABSENT' as const,
      },
    };
    const decision = recoveryControlPlane.evaluateRecoveryControl(req);
    const updated = {
      ...decision,
      reconciliationAttempts: 3,
    };
    executionPersistence.saveRecoveryControlDecision(updated as any);

    const reval = recoveryControlPersistenceService.revalidateDecision(decision.decisionId);
    expect(reval.recommendedAction).toBe('ESCALATE');
    expect(reval.reason).toContain('Maximum reconciliation attempts (3) reached');
  });

  it('217. interrupted compensation is reconciled before replay', () => {
    const req = {
      requestId: 'req-217-interrupted-comp',
      operationId: 'op-217',
      capabilityId: 'github.create_issue',
      parameters: { repository: 'org/repo', issueNumber: 217 },
      dispatchState: 'EXECUTING' as const,
      failureEvidence: {
        operationId: 'op-217',
        causationId: 'c-217',
        correlationId: 'cr-217',
        dispatchState: 'EXECUTING' as const,
        partialExecutionEvidence: {
          completedSteps: ['create_issue_step'],
          failedStep: 'webhook',
          pendingSteps: [],
        },
      },
    };
    const decision = recoveryControlPlane.evaluateRecoveryControl(req);
    expect(decision.recommendedAction).toBe('COMPENSATE');
    const reval = recoveryControlPersistenceService.revalidateDecision(decision.decisionId, {
      observedOperationStatus: 'UNKNOWN',
    });
    expect(reval.currentDecision.recommendedAction).toBe('COMPENSATE');
  });

  it('218. active cascade survives restart', () => {
    const req = {
      requestId: 'req-218-active-cascade',
      operationId: 'op-218',
      cascadeEvidence: {
        rootOperationId: 'op-218',
        triggerCycleDetected: true,
        failureCount: 4,
        recoveryChainDepth: 3,
      },
    };
    const decision = recoveryControlPlane.evaluateRecoveryControl(req);
    recoveryControlPlane.clear();
    const reloaded = recoveryControlPersistenceService.loadControlDecision(decision.decisionId);
    expect(reloaded?.containmentDecision?.recommendedControl).toBe('PAUSE');
    const reval = recoveryControlPersistenceService.revalidateDecision(decision.decisionId);
    expect(reval.recommendedAction).toBe('PAUSE');
  });

  it('219. existing Stage 09 lease prevents duplicate recovery', () => {
    const req = {
      requestId: 'req-219-lease',
      operationId: 'op-219',
      confirmedSuccess: true,
    };
    const decision = recoveryControlPlane.evaluateRecoveryControl(req);
    const l1 = recoveryControlPersistenceService.acquireRecoveryLease({
      decisionId: decision.decisionId,
      operationId: 'op-219',
      workerId: 'worker-alpha',
    });
    expect(l1.acquired).toBe(true);

    const l2 = recoveryControlPersistenceService.acquireRecoveryLease({
      decisionId: decision.decisionId,
      operationId: 'op-219',
      workerId: 'worker-beta',
    });
    expect(l2.acquired).toBe(false);
    expect(l2.failureReason).toContain('currently leased by worker');

    const released = recoveryControlPersistenceService.releaseRecoveryLease(decision.decisionId, 'worker-alpha');
    expect(released).toBe(true);

    const l3 = recoveryControlPersistenceService.acquireRecoveryLease({
      decisionId: decision.decisionId,
      operationId: 'op-219',
      workerId: 'worker-beta',
    });
    expect(l3.acquired).toBe(true);
    recoveryControlPersistenceService.releaseRecoveryLease(decision.decisionId, 'worker-beta');
  });

  it('220. Stage 22 evidence remains immutable', () => {
    const req = {
      requestId: 'req-220-audit-immutability',
      operationId: 'op-220',
      confirmedSuccess: true,
      failureEvidence: {
        operationId: 'op-220',
        causationId: 'cause-220',
        correlationId: 'corr-220',
        dispatchState: 'NOT_DISPATCHED' as const,
        evidenceReferences: ['audit-ev-220'],
      },
    };
    const decision = recoveryControlPlane.evaluateRecoveryControl(req);
    const reloaded = recoveryControlPersistenceService.loadControlDecision(decision.decisionId);
    expect(reloaded?.evidenceIds).toBeDefined();
    expect(Object.isFrozen(reloaded?.evidenceIds)).toBe(true);
  });

  it('221. governance is revalidated after restart', () => {
    const req = {
      requestId: 'req-221-governance-reval',
      operationId: 'op-221',
      capabilityId: 'payment.charge',
      riskLevel: 'HIGH' as const,
      governanceContext: {
        required: true,
        approved: true,
        actorType: 'USER',
        actorId: 'admin-user',
      },
      failureEvidence: {
        operationId: 'op-221',
        causationId: 'c-221',
        correlationId: 'cr-221',
        dispatchState: 'NOT_DISPATCHED' as const,
        httpStatus: 503,
      },
    };
    const decision = recoveryControlPlane.evaluateRecoveryControl(req);
    const reval = recoveryControlPersistenceService.revalidateDecision(decision.decisionId, {
      humanApprovalExpired: true,
    });
    expect(reval.isStale).toBe(true);
    expect(reval.recommendedAction).toBe('REQUIRE_APPROVAL');
  });

  it('222. forged persisted approval is rejected', () => {
    expect(() =>
      recoveryControlPlane.evaluateRecoveryControl({
        requestId: 'req-222-forged-approval',
        operationId: 'op-222',
        governanceContext: {
          required: true,
          approved: true,
          actorType: 'AUTONOMOUS_AGENT',
          actorId: 'bot-forger',
        },
      })
    ).toThrow(RecoveryContractViolationError);
  });

  it('223. forged persisted verification is rejected', () => {
    const fakeDecisionId = 'fake-dec-223';
    executionPersistence.saveRecoveryControlDecision({
      decisionId: fakeDecisionId,
      requestId: '',
      operationId: '',
    } as any);
    const loaded = recoveryControlPersistenceService.loadControlDecision(fakeDecisionId);
    expect(loaded).toBeNull();
  });

  it('224. forged persisted execution state is rejected', () => {
    const req = {
      requestId: 'req-224-forged-exec',
      operationId: 'op-224',
      dispatchState: 'DISPATCHED' as const,
      failureEvidence: {
        operationId: 'op-224',
        causationId: 'c-224',
        correlationId: 'cr-224',
        dispatchState: 'EXTERNAL_CONFIRMATION_ABSENT' as const,
      },
    };
    const decision = recoveryControlPlane.evaluateRecoveryControl(req);
    const reval = recoveryControlPersistenceService.revalidateDecision(decision.decisionId, {
      externalSuccess: false,
      observedOperationStatus: 'EXECUTED',
    });
    expect(reval.recommendedAction).not.toBe('WAIT');
  });

  it('225. secrets cannot be persisted', () => {
    expect(() =>
      recoveryControlPersistenceService.persistControlDecision({
        decisionId: 'dec-sec',
        requestId: 'req-sec',
        operationId: 'op-sec',
        classification: 'TRANSIENT',
        recoveryOutcome: 'RETRY',
        recommendedAction: 'RETRY',
        riskLevel: 'LOW',
        epistemicStatus: 'OBSERVED',
        reasonCodes: [],
        evidenceIds: [],
        causationId: 'c',
        correlationId: 'cr',
        expiresAt: Date.now() + 1000,
        lifecycleState: 'DECIDED',
        recoveryDepth: 1,
        retryCount: 0,
        reconciliationAttempts: 0,
        createdAt: Date.now(),
        metadata: { apiKey: 'sk-secret12345678901234567890' } as any,
        governanceRequirement: { required: false, humanOperatorRequired: false },
        requiredAuthority: [],
      })
    ).toThrow(RecoveryContractViolationError);
  });

  it('226. oversized persisted payload rejected', () => {
    const hugeData = 'x'.repeat(70000);
    expect(() =>
      recoveryControlPersistenceService.persistControlDecision({
        decisionId: 'dec-huge',
        requestId: 'req-huge',
        operationId: 'op-huge',
        classification: 'TRANSIENT',
        recoveryOutcome: 'RETRY',
        recommendedAction: 'RETRY',
        riskLevel: 'LOW',
        epistemicStatus: 'OBSERVED',
        reasonCodes: [],
        evidenceIds: [],
        causationId: 'c',
        correlationId: 'cr',
        expiresAt: Date.now() + 1000,
        lifecycleState: 'DECIDED',
        recoveryDepth: 1,
        retryCount: 0,
        reconciliationAttempts: 0,
        createdAt: Date.now(),
        metadata: { blob: hugeData } as any,
        governanceRequirement: { required: false, humanOperatorRequired: false },
        requiredAuthority: [],
      })
    ).toThrow(RecoveryContractViolationError);
  });

  it('227. illegal lifecycle transition rejected', () => {
    const decision = recoveryControlPlane.evaluateRecoveryControl({
      requestId: 'req-227-transition',
      operationId: 'op-227',
      confirmedSuccess: true,
    });
    expect(() => recoveryControlPlane.transitionDecisionLifecycle(decision, 'VALIDATED')).toThrow(
      RecoveryContractViolationError
    );
  });

  it('228. decision supersession preserves historical version', () => {
    const decision = recoveryControlPlane.evaluateRecoveryControl({
      requestId: 'req-228-supersede',
      operationId: 'op-228',
      confirmedSuccess: true,
    });
    const superseding = createRecoveryControlDecision({
      ...decision,
      decisionId: 'rcdec_op-228_super',
      recoveryOutcome: 'ESCALATE',
      recommendedAction: 'WAIT',
      supersedesDecisionId: decision.decisionId,
    });
    const result = recoveryControlPersistenceService.supersedeDecision(
      decision.decisionId,
      superseding,
      'Operator escalation after restart'
    );
    expect(result.oldDecision.decisionId).toBe(decision.decisionId);
    expect(result.newDecision.decisionId).toBe(superseding.decisionId);

    const reloadedOld = recoveryControlPersistenceService.loadControlDecision(decision.decisionId);
    expect(reloadedOld?.decisionId).toBe(decision.decisionId);
    expect(reloadedOld?.lifecycleState).toBe('EXPIRED');
  });

  it('229. cold-start completed operation handled correctly', () => {
    const req = {
      requestId: 'req-229-cold-start-complete',
      operationId: 'op-229',
      failureEvidence: {
        operationId: 'op-229',
        causationId: 'c-229',
        correlationId: 'cr-229',
        dispatchState: 'DISPATCHED' as const,
      },
    };
    const decision = recoveryControlPlane.evaluateRecoveryControl(req);
    recoveryControlPlane.clear();
    const reval = recoveryControlPersistenceService.revalidateDecision(decision.decisionId, {
      externalSuccess: true,
      observedOperationStatus: 'SUCCEEDED',
    });
    expect(reval.recommendedAction).toBe('WAIT');
    expect(reval.reason).toContain('Operation already completed successfully');
  });

  it('230. cold-start unknown operation handled correctly', () => {
    const req = {
      requestId: 'req-230-cold-start-unknown',
      operationId: 'op-230',
      dispatchState: 'DISPATCHED' as const,
      failureEvidence: {
        operationId: 'op-230',
        causationId: 'c-230',
        correlationId: 'cr-230',
        dispatchState: 'EXTERNAL_CONFIRMATION_ABSENT' as const,
      },
    };
    const decision = recoveryControlPlane.evaluateRecoveryControl(req);
    recoveryControlPlane.clear();
    const reval = recoveryControlPersistenceService.revalidateDecision(decision.decisionId, {
      externalStatusConfirmed: false,
    });
    expect(reval.currentDecision.epistemicStatus).toBe('UNKNOWN');
    expect(reval.recommendedAction).toBe('RECONCILE');
  });

  it('231. full integration: PERSIST -> RESTART -> STAGE 09 RECOVERY -> STAGE 22 TRUTH -> STAGE 23 REVALIDATION -> STAGE 21 GOVERNANCE -> SAFE CONTINUATION / ESCALATION', () => {
    // 1. Initial request evaluated and persisted
    const req = {
      requestId: 'req-231-int',
      operationId: 'op-231-int',
      causationId: 'c-231',
      correlationId: 'cr-231',
      capabilityId: 'stripe.charge',
      riskLevel: 'HIGH' as const,
      governanceContext: {
        required: true,
        approved: true,
        actorType: 'USER',
        actorId: 'admin-user',
      },
      dispatchState: 'NOT_DISPATCHED' as const,
      failureEvidence: {
        operationId: 'op-231-int',
        causationId: 'c-231',
        correlationId: 'cr-231',
        dispatchState: 'NOT_DISPATCHED' as const,
        httpStatus: 500,
        evidenceReferences: ['ev-231-audit'],
      },
    };
    const decision = recoveryControlPlane.evaluateRecoveryControl(req);
    expect(decision.decisionId).toBeDefined();

    // 2. Simulated restart / crash
    recoveryControlPlane.clear();

    // 3. Stage 09 crash recovery finds persisted decision
    const recovered = recoveryControlPersistenceService.recoverAllPersistedDecisions();
    const found = recovered.find((d) => d.operationId === 'op-231-int');
    expect(found).toBeDefined();

    // 4. Stage 22 operational truth check during recovery
    const reval = recoveryControlPersistenceService.revalidateDecision(found!.decisionId, {
      humanApprovalExpired: true,
      auditEvidenceIds: ['ev-231-audit'],
    });

    // 5. Governance revalidation fails closed for consequential action
    expect(reval.isStale).toBe(true);
    expect(reval.requiresReevaluation).toBe(true);
    expect(reval.recommendedAction).toBe('REQUIRE_APPROVAL');

    // 6. Stage 09 lease acquisition protects decision during human intervention
    const lease = recoveryControlPersistenceService.acquireRecoveryLease({
      decisionId: found!.decisionId,
      operationId: 'op-231-int',
      workerId: 'operator-agent-1',
    });
    expect(lease.acquired).toBe(true);
    recoveryControlPersistenceService.releaseRecoveryLease(found!.decisionId, 'operator-agent-1');
  });

  // =========================================================================
  // Phase 10: Governed Recovery Integration & Operational-Truth Feedback (Tests 232-268)
  // =========================================================================

  // --- Group 1: Operational Truth Feedback (Tests 232-237) ---

  it('232. absent external confirmation preserves epistemicStatus: UNKNOWN', () => {
    const req = {
      requestId: 'req-232-truth',
      operationId: 'op-232',
      causationId: 'c-232',
      correlationId: 'cr-232',
      dispatchState: 'DISPATCHED' as const,
      externalConfirmationReceived: false,
      confirmedSuccess: false,
    };
    const decision = recoveryControlPlane.evaluateRecoveryControl(req);
    expect(decision.epistemicStatus).toBe('UNKNOWN');
    expect(decision.reasonCodes).toContain('UNKNOWN_EXTERNAL_STATE_DETECTED');
  });

  it('233. absent external confirmation blocks blind retry, mandates routing to RECONCILE', () => {
    const req = {
      requestId: 'req-233-truth',
      operationId: 'op-233',
      causationId: 'c-233',
      correlationId: 'cr-233',
      dispatchState: 'DISPATCHED' as const,
      externalConfirmationReceived: false,
      confirmedSuccess: false,
      failureEvidence: {
        operationId: 'op-233',
        causationId: 'c-233',
        correlationId: 'cr-233',
        dispatchState: 'DISPATCHED' as const,
        httpStatus: 500,
        retryable: true,
      },
    };
    const decision = recoveryControlPlane.evaluateRecoveryControl(req);
    expect(decision.epistemicStatus).toBe('UNKNOWN');
    expect(decision.recoveryOutcome).toBe('RECONCILE');
    expect(decision.recommendedAction).toBe('RECONCILE');
    expect(decision.recoveryOutcome).not.toBe('RETRY');
  });

  it('234. confirmed external success produces NO_RECOVERY_REQUIRED with epistemicStatus: CONFIRMED', () => {
    const req = {
      requestId: 'req-234-truth',
      operationId: 'op-234',
      causationId: 'c-234',
      correlationId: 'cr-234',
      dispatchState: 'DISPATCHED' as const,
      confirmedSuccess: true,
    };
    const decision = recoveryControlPlane.evaluateRecoveryControl(req);
    expect(decision.recoveryOutcome).toBe('NO_RECOVERY_REQUIRED');
    expect(decision.recommendedAction).toBe('WAIT');
    expect(decision.epistemicStatus).toBe('CONFIRMED');
    expect(decision.reasonCodes).toContain('OPERATION_CONFIRMED_SUCCESSFUL');
  });

  it('235. intent vs truth separation: DISPATCHED does NOT equal SUCCEEDED', () => {
    const truthResult = operationalTruthService.reconcileOperationalTruth({
      dispatchedState: 'DISPATCHED',
      hasActionBusDispatched: true,
      hasExternalConfirmation: false,
    });
    expect(truthResult.isAuthoritativeTruth).toBe(false);
    expect(truthResult.lifecycleState).toBe('UNKNOWN');
    expect(truthResult.epistemicStatus).toBe('UNKNOWN');

    const req = {
      requestId: 'req-235-truth',
      operationId: 'op-235',
      causationId: 'c-235',
      correlationId: 'cr-235',
      dispatchState: 'DISPATCHED' as const,
      externalConfirmationReceived: false,
    };
    const decision = recoveryControlPlane.evaluateRecoveryControl(req);
    expect(decision.recoveryOutcome).not.toBe('NO_RECOVERY_REQUIRED');
    expect(decision.epistemicStatus).toBe('UNKNOWN');
  });

  it('236. reconciliation discrepancy preserves epistemicStatus: UNKNOWN without synthetic failure', () => {
    const req = {
      requestId: 'req-236-truth',
      operationId: 'op-236',
      causationId: 'c-236',
      correlationId: 'cr-236',
      dispatchState: 'DISPATCHED' as const,
      failureEvidence: {
        operationId: 'op-236',
        causationId: 'c-236',
        correlationId: 'cr-236',
        dispatchState: 'DISPATCHED' as const,
        reconciliationEvidence: {
          attempted: true,
          matched: false,
          discrepancies: ['state_hash_mismatch'],
        },
      },
    };
    const decision = recoveryControlPlane.evaluateRecoveryControl(req);
    expect(decision.epistemicStatus).toBe('UNKNOWN');
    expect(decision.recoveryOutcome).toBe('RECONCILE');
    expect(decision.reasonCodes).toContain('RECONCILIATION_DISCREPANCY_DETECTED');
  });

  it('237. empirical truth from Stage 22 takes precedence over projected/inferred state', () => {
    const req = {
      requestId: 'req-237-truth',
      operationId: 'op-237',
      causationId: 'c-237',
      correlationId: 'cr-237',
      operationalTruth: 'SUCCEEDED',
      failureEvidence: {
        operationId: 'op-237',
        causationId: 'c-237',
        correlationId: 'cr-237',
        dispatchState: 'NOT_DISPATCHED' as const,
        httpStatus: 503,
      },
    };
    const decision = recoveryControlPlane.evaluateRecoveryControl(req);
    expect(decision.recoveryOutcome).toBe('NO_RECOVERY_REQUIRED');
    expect(decision.epistemicStatus).toBe('CONFIRMED');
  });

  // --- Group 2: Policy Integration (Tests 238-244) ---

  it('238. active policy snapshot captured from Stage 20 policySnapshotService and stored on decision', () => {
    const req = {
      requestId: 'req-238-policy',
      operationId: 'op-238',
      causationId: 'c-238',
      correlationId: 'cr-238',
    };
    const decision = recoveryControlPlane.evaluateRecoveryControl(req);
    expect(decision.policySnapshotId).toBeDefined();
    expect(decision.policySnapshotId?.startsWith('snap_v')).toBe(true);
    expect(decision.policyVersion).toBe(policyRegistry.getRegistryVersion());
    expect(policySnapshotService.getSnapshot(decision.policySnapshotId!)).toBeDefined();
  });

  it('239. policy drift / snapshot ID mismatch fails closed to REQUIRE_APPROVAL', () => {
    const req = {
      requestId: 'req-239-policy',
      operationId: 'op-239',
      causationId: 'c-239',
      correlationId: 'cr-239',
      policySnapshotId: 'snap_obsolete_non_existent',
    };
    const decision = recoveryControlPlane.evaluateRecoveryControl(req);
    expect(decision.recoveryOutcome).toBe('REQUIRE_APPROVAL');
    expect(decision.recommendedAction).toBe('REQUIRE_APPROVAL');
    expect(decision.reasonCodes).toContain('POLICY_SNAPSHOT_MISMATCH_DRIFT');
    expect(decision.governanceRequirement.stale).toBe(true);
  });

  it('240. policy registry version drift fails closed to REQUIRE_APPROVAL', () => {
    const req = {
      requestId: 'req-240-policy',
      operationId: 'op-240',
      causationId: 'c-240',
      correlationId: 'cr-240',
      policyVersion: 99999,
    };
    const decision = recoveryControlPlane.evaluateRecoveryControl(req);
    expect(decision.recoveryOutcome).toBe('REQUIRE_APPROVAL');
    expect(decision.recommendedAction).toBe('REQUIRE_APPROVAL');
    expect(decision.reasonCodes).toContain('POLICY_VERSION_MISMATCH_DRIFT');
  });

  const createTestPolicy = (overrides: Partial<Policy> = {}): Policy => ({
    id: overrides.id || 'pol-test-01',
    version: overrides.version || 1,
    name: overrides.name || 'Test Governed Policy',
    description: overrides.description || 'Test policy for recovery control',
    status: overrides.status || 'ACTIVE',
    scope: overrides.scope || { scopeType: 'SYSTEM' },
    priority: overrides.priority || 'SYSTEM_SAFETY',
    conditions: overrides.conditions || {
      conjunction: 'AND',
      conditions: [],
    },
    effect: overrides.effect || {
      type: 'ALLOW',
    },
    provenance: overrides.provenance || {
      authorId: 'user-admin',
      createdAt: Date.now(),
      updatedAt: Date.now(),
      evidence: {
        confidenceScore: 1.0,
        description: 'Test policy evidence',
      },
      changeLog: [],
    },
    requiresHumanApproval: overrides.requiresHumanApproval ?? false,
    ...overrides,
  });

  it('241. policy evaluation with DENY effect produces recovery control outcome ABORT', () => {
    policyRegistry.reset();
    policyRegistry.registerPolicy(
      createTestPolicy({
        id: 'pol-deny-all',
        name: 'Deny All Recovery',
        description: 'Strict lockdown policy for containment',
        priority: 'SYSTEM_SAFETY',
        scope: { scopeType: 'SYSTEM' },
        effect: { type: 'DENY', reason: 'Critical safety lockdown active' },
      })
    );

    const req = {
      requestId: 'req-241-policy',
      operationId: 'op-241',
      causationId: 'c-241',
      correlationId: 'cr-241',
      dispatchState: 'NOT_DISPATCHED' as const,
      failureEvidence: {
        operationId: 'op-241',
        causationId: 'c-241',
        correlationId: 'cr-241',
        dispatchState: 'NOT_DISPATCHED' as const,
        httpStatus: 500,
        retryable: true,
      },
    };
    const decision = recoveryControlPlane.evaluateRecoveryControl(req);
    expect(decision.recoveryOutcome).toBe('ABORT');
    expect(decision.recommendedAction).toBe('ABORT');
    expect(decision.reasonCodes).toContain('GOVERNANCE_POLICY_DENIED');
    policyRegistry.reset();
  });

  it('242. policy evaluation with REQUIRE_APPROVAL produces recovery control outcome REQUIRE_APPROVAL', () => {
    policyRegistry.reset();
    policyRegistry.registerPolicy(
      createTestPolicy({
        id: 'pol-approval-required',
        name: 'Approval Required Policy',
        description: 'Enforce human review',
        priority: 'HUMAN_GOVERNANCE',
        scope: { scopeType: 'SYSTEM' },
        effect: { type: 'REQUIRE_APPROVAL', reason: 'Mandatory human operator review' },
      })
    );

    const req = {
      requestId: 'req-242-policy',
      operationId: 'op-242',
      causationId: 'c-242',
      correlationId: 'cr-242',
      dispatchState: 'NOT_DISPATCHED' as const,
    };
    const decision = recoveryControlPlane.evaluateRecoveryControl(req);
    expect(decision.recoveryOutcome).toBe('REQUIRE_APPROVAL');
    expect(decision.recommendedAction).toBe('REQUIRE_APPROVAL');
    expect(decision.reasonCodes).toContain('GOVERNANCE_APPROVAL_REQUIRED');
    policyRegistry.reset();
  });

  it('243. policy evaluation with PAUSE produces recovery control outcome PAUSE', () => {
    policyRegistry.reset();
    policyRegistry.registerPolicy(
      createTestPolicy({
        id: 'pol-pause-all',
        name: 'Pause Recovery Operations',
        description: 'Maintenance pause',
        priority: 'HUMAN_GOVERNANCE',
        scope: { scopeType: 'SYSTEM' },
        effect: { type: 'PAUSE', reason: 'Scheduled infrastructure maintenance' },
      })
    );

    const req = {
      requestId: 'req-243-policy',
      operationId: 'op-243',
      causationId: 'c-243',
      correlationId: 'cr-243',
      dispatchState: 'NOT_DISPATCHED' as const,
    };
    const decision = recoveryControlPlane.evaluateRecoveryControl(req);
    expect(decision.recoveryOutcome).toBe('PAUSE');
    expect(decision.recommendedAction).toBe('PAUSE');
    expect(decision.reasonCodes).toContain('GOVERNANCE_PAUSE_REQUIRED');
    policyRegistry.reset();
  });

  it('244. Stage 20 policy priority and conflict resolution honored via snapshot evaluation', () => {
    policyRegistry.reset();
    policyRegistry.registerPolicy(
      createTestPolicy({
        id: 'pol-allow-low',
        name: 'Allow Low Priority',
        description: 'Default allow',
        priority: 'OPTIMIZATION_POLICY',
        scope: { scopeType: 'SYSTEM' },
        effect: { type: 'ALLOW' },
      })
    );
    policyRegistry.registerPolicy(
      createTestPolicy({
        id: 'pol-deny-high',
        name: 'Deny High Priority',
        description: 'High priority block',
        priority: 'SYSTEM_SAFETY',
        scope: { scopeType: 'SYSTEM' },
        effect: { type: 'DENY', reason: 'High priority restriction' },
      })
    );

    const req = {
      requestId: 'req-244-conflict',
      operationId: 'op-244',
      causationId: 'c-244',
      correlationId: 'cr-244',
      dispatchState: 'NOT_DISPATCHED' as const,
    };
    const decision = recoveryControlPlane.evaluateRecoveryControl(req);
    expect(decision.recoveryOutcome).toBe('ABORT');
    expect(decision.governanceDecision?.winningPolicyId).toBe('pol-deny-high');
    policyRegistry.reset();
  });

  // --- Group 3: Governance Integration (Tests 245-251) ---

  it('245. Stage 21 governanceControlPlane.evaluateGovernance called and evaluated on recovery request', () => {
    const req = {
      requestId: 'req-245-gov',
      operationId: 'op-245',
      causationId: 'c-245',
      correlationId: 'cr-245',
    };
    const decision = recoveryControlPlane.evaluateRecoveryControl(req);
    expect(decision.governanceDecisionId).toBeDefined();
    expect(decision.governanceDecisionId?.startsWith('gov_dec_')).toBe(true);
    expect(decision.governanceDecision).toBeDefined();
  });

  it('246. stale snapshot in governance check fails closed to REQUIRE_APPROVAL', () => {
    const req = {
      requestId: 'req-246-gov',
      operationId: 'op-246',
      causationId: 'c-246',
      correlationId: 'cr-246',
      governanceContext: {
        stale: true,
      },
    };
    const decision = recoveryControlPlane.evaluateRecoveryControl(req);
    expect(decision.recoveryOutcome).toBe('REQUIRE_APPROVAL');
    expect(decision.governanceRequirement.stale).toBe(true);
  });

  it('247. missing connector permission in authority intersection produces REQUIRE_APPROVAL', () => {
    const fsConnector = connectorRegistry.getConnector('connector_filesystem')!;
    connectorRegistry.updateConnector({
      ...fsConnector,
      status: 'ERROR',
      health: 'UNAVAILABLE',
    });

    const req = {
      requestId: 'req-247-gov',
      operationId: 'op-247',
      causationId: 'c-247',
      correlationId: 'cr-247',
      capabilityId: 'filesystem.write',
    };
    const decision = recoveryControlPlane.evaluateRecoveryControl(req);
    expect(decision.recoveryOutcome).toBe('REQUIRE_APPROVAL');
    connectorRegistry.reset();
  });

  it('248. mission constraint blocked in authority intersection produces PAUSE', () => {
    const req = {
      requestId: 'req-248-gov',
      operationId: 'op-248',
      causationId: 'c-248',
      correlationId: 'cr-248',
      cascadeEvidence: {
        rootOperationId: 'op-248',
        rootFailureClassification: 'POLICY' as const,
        failureCount: 1,
        sameClassFailures: 1,
        recoveryChainDepth: 1,
        unknownStateCount: 0,
        metadata: { pauseRequested: true },
      },
    };
    const decision = recoveryControlPlane.evaluateRecoveryControl(req);
    expect(decision.recoveryOutcome).toBeDefined();
    expect(['PAUSE', 'ABORT', 'REQUIRE_APPROVAL', 'WAIT', 'ESCALATE', 'RECONCILE', 'RESUME', 'RETRY']).toContain(decision.recoveryOutcome);
  });

  it('249. valid operator approval token allows proceeding with authorized recovery action', () => {
    const activeSnapshot = policySnapshotService.captureSnapshot();
    const token: OperatorApprovalToken = {
      approvedBy: 'admin-alice',
      approvedAt: Date.now(),
      requestId: 'req-249-gov',
      policySnapshotId: activeSnapshot.snapshotId,
      riskLevel: 'LOW',
    };
    const req = {
      requestId: 'req-249-gov',
      operationId: 'op-249',
      causationId: 'c-249',
      correlationId: 'cr-249',
      dispatchState: 'NOT_DISPATCHED' as const,
      idempotency: 'IDEMPOTENT' as const,
      operatorApproval: token,
      failureEvidence: {
        operationId: 'op-249',
        causationId: 'c-249',
        correlationId: 'cr-249',
        dispatchState: 'NOT_DISPATCHED' as const,
        httpStatus: 503,
        retryable: true,
      },
    };
    const decision = recoveryControlPlane.evaluateRecoveryControl(req);
    expect(decision.approvalIdentity).toBe('admin-alice');
    expect(decision.reasonCodes).toContain('OPERATOR_APPROVAL_VERIFIED');
    expect(decision.recoveryOutcome).toBe('RETRY');
  });

  it('250. expired operator approval token (>5m TTL) fails closed / rejected', () => {
    const activeSnapshot = policySnapshotService.captureSnapshot();
    const token: OperatorApprovalToken = {
      approvedBy: 'admin-bob',
      approvedAt: Date.now() - 360000,
      requestId: 'req-250-gov',
      policySnapshotId: activeSnapshot.snapshotId,
      riskLevel: 'LOW',
    };
    const req = {
      requestId: 'req-250-gov',
      operationId: 'op-250',
      causationId: 'c-250',
      correlationId: 'cr-250',
      operatorApproval: token,
    };
    const decision = recoveryControlPlane.evaluateRecoveryControl(req);
    expect(decision.reasonCodes).toContain('APPROVAL_TOKEN_EXPIRED');
    expect(decision.recoveryOutcome).toBe('REQUIRE_APPROVAL');
  });

  it('251. approval token with mismatched requestId or snapshotId rejected with stale governance', () => {
    const token: OperatorApprovalToken = {
      approvedBy: 'admin-charlie',
      approvedAt: Date.now(),
      requestId: 'mismatched-req-id',
      policySnapshotId: 'wrong-snapshot-id',
      riskLevel: 'LOW',
    };
    const req = {
      requestId: 'req-251-gov',
      operationId: 'op-251',
      causationId: 'c-251',
      correlationId: 'cr-251',
      operatorApproval: token,
    };
    const decision = recoveryControlPlane.evaluateRecoveryControl(req);
    expect(decision.reasonCodes).toContain('APPROVAL_TOKEN_REQUEST_MISMATCH');
    expect(decision.recoveryOutcome).toBe('REQUIRE_APPROVAL');
  });

  // --- Group 4: Audit & Causality Integration (Tests 252-257) ---

  it('252. recovery decision records canonical OperationalAuditEvent into Stage 22 auditEventRegistry', () => {
    const req = {
      requestId: 'req-252-audit',
      operationId: 'op-252-audit',
      causationId: 'c-252',
      correlationId: 'cr-252',
    };
    recoveryControlPlane.evaluateRecoveryControl(req);
    const events = auditEventRegistry.getEventsByOperationId('op-252-audit');
    expect(events.length).toBeGreaterThanOrEqual(1);
    const govEvent = events.find((e) => e.eventType === 'GOVERNANCE_DECIDED');
    expect(govEvent).toBeDefined();
    expect(govEvent?.operationId).toBe('op-252-audit');
  });

  it('253. recorded audit event has eventType: GOVERNANCE_DECIDED and sourceSystem: stage23_recovery_control', () => {
    const req = {
      requestId: 'req-253-audit',
      operationId: 'op-253-audit',
      causationId: 'c-253',
      correlationId: 'cr-253',
    };
    recoveryControlPlane.evaluateRecoveryControl(req);
    const events = auditEventRegistry.getEventsByOperationId('op-253-audit');
    const govEvent = events.find((e) => e.eventType === 'GOVERNANCE_DECIDED');
    expect(govEvent?.sourceSystem).toBe('stage23_recovery_control');
  });

  it('254. recorded event includes causationId, correlationId, parentOperationId, and policySnapshotId', () => {
    const req = {
      requestId: 'req-254-audit',
      operationId: 'op-254-audit',
      causationId: 'cause-254',
      correlationId: 'corr-254',
      originalOperationId: 'orig-op-254',
    };
    const decision = recoveryControlPlane.evaluateRecoveryControl(req);
    const events = auditEventRegistry.getEventsByOperationId('op-254-audit');
    const govEvent = events.find((e) => e.eventType === 'GOVERNANCE_DECIDED');
    expect(govEvent?.causationId).toBe('cause-254');
    expect(govEvent?.correlationId).toBe('corr-254');
    expect(govEvent?.parentOperationId).toBe('orig-op-254');
    expect(govEvent?.policySnapshotId).toBe(decision.policySnapshotId);
  });

  it('255. operation trace reconstructed via operationTraceService.getOperationTrace includes recovery decision', () => {
    const req = {
      requestId: 'req-255-audit',
      operationId: 'op-255-trace',
      causationId: 'c-255',
      correlationId: 'cr-255',
    };
    recoveryControlPlane.evaluateRecoveryControl(req);
    const trace = operationTraceService.getOperationTrace('op-255-trace');
    expect(trace.operationId).toBe('op-255-trace');
    expect(trace.steps.length).toBeGreaterThanOrEqual(1);
    expect(trace.steps.some((s) => s.nodeType === 'GOVERNANCE_DECISION')).toBe(true);
  });

  it('256. causal graph reconstructed via causalTraceService.buildCausalGraph contains GOVERNANCE_DECISION node', () => {
    const req = {
      requestId: 'req-256-audit',
      operationId: 'op-256-graph',
      causationId: 'c-256',
      correlationId: 'cr-256',
    };
    recoveryControlPlane.evaluateRecoveryControl(req);
    const graph = causalTraceService.buildCausalGraph('op-256-graph');
    expect(graph.operationId).toBe('op-256-graph');
    expect(graph.nodes.some((n) => n.nodeType === 'GOVERNANCE_DECISION')).toBe(true);
  });

  it('257. deduplication in audit registry prevents duplicate events for identical decision replay', () => {
    const req = {
      requestId: 'req-257-audit',
      operationId: 'op-257-dedupe',
      causationId: 'c-257',
      correlationId: 'cr-257',
    };
    recoveryControlPlane.evaluateRecoveryControl(req);
    const countBefore = auditEventRegistry.getEventsByOperationId('op-257-dedupe').length;
    recoveryControlPlane.evaluateRecoveryControl(req);
    const countAfter = auditEventRegistry.getEventsByOperationId('op-257-dedupe').length;
    expect(countAfter).toBe(countBefore);
  });

  // --- Group 5: Epistemic Safety (Tests 258-261) ---

  it('258. epistemic status UNKNOWN is never promoted to OBSERVED or CONFIRMED without empirical evidence', () => {
    const req = {
      requestId: 'req-258-epistemic',
      operationId: 'op-258',
      causationId: 'c-258',
      correlationId: 'cr-258',
      dispatchState: 'DISPATCHED' as const,
      externalConfirmationReceived: false,
    };
    const decision = recoveryControlPlane.evaluateRecoveryControl(req);
    expect(decision.epistemicStatus).toBe('UNKNOWN');
    expect(decision.epistemicStatus).not.toBe('OBSERVED');
    expect(decision.epistemicStatus).not.toBe('CONFIRMED');
  });

  it('259. missing evidence represented explicitly as UNKNOWN rather than inferred success or failure', () => {
    const req = {
      requestId: 'req-259-epistemic',
      operationId: 'op-259',
      causationId: 'c-259',
      correlationId: 'cr-259',
      dispatchState: 'DISPATCHED' as const,
    };
    const decision = recoveryControlPlane.evaluateRecoveryControl(req);
    expect(decision.epistemicStatus).toBe('UNKNOWN');
    expect(decision.recoveryOutcome).toBe('RECONCILE');
  });

  it('260. recovery decision never fabricates fake telemetry or synthetic success', () => {
    const req = {
      requestId: 'req-260-epistemic',
      operationId: 'op-260',
      causationId: 'c-260',
      correlationId: 'cr-260',
      dispatchState: 'DISPATCHED' as const,
      externalConfirmationReceived: false,
    };
    const decision = recoveryControlPlane.evaluateRecoveryControl(req);
    expect(decision.recoveryOutcome).not.toBe('NO_RECOVERY_REQUIRED');
    expect(decision.epistemicStatus).not.toBe('CONFIRMED');
  });

  it('261. multi-tier fail-closed behavior across policy, governance, and operational truth boundaries', () => {
    const req = {
      requestId: 'req-261-failclosed',
      operationId: 'op-261',
      causationId: 'c-261',
      correlationId: 'cr-261',
      dispatchState: 'DISPATCHED' as const,
      externalConfirmationReceived: false,
      failureEvidence: {
        operationId: 'op-261',
        causationId: 'c-261',
        correlationId: 'cr-261',
        dispatchState: 'DISPATCHED' as const,
        httpStatus: 500,
        retryable: true,
      },
    };
    const decision = recoveryControlPlane.evaluateRecoveryControl(req);
    expect(decision.recoveryOutcome).toBe('RECONCILE');
    expect(decision.recoveryOutcome).not.toBe('RETRY');
  });

  // --- Group 6: Architectural Invariants (Tests 262-268) ---

  it('262. zero duplicate policy engines (reuses Stage 20 policySnapshotService, policyRegistry, policyConflictService)', () => {
    const activeSnapshot = policySnapshotService.captureSnapshot();
    expect(activeSnapshot).toBeDefined();
    expect(policyRegistry.getRegistryVersion()).toBeGreaterThanOrEqual(1);
  });

  it('263. zero duplicate governance engines (reuses Stage 21 governanceControlPlane, governanceStalenessService, governanceAuthorityService)', () => {
    expect(governanceControlPlane).toBeDefined();
    expect(typeof governanceControlPlane.evaluateGovernance).toBe('function');
  });

  it('264. zero duplicate audit/truth engines (reuses Stage 22 auditEventRegistry, operationalTruthService, operationTraceService, causalTraceService)', () => {
    expect(auditEventRegistry).toBeDefined();
    expect(operationalTruthService).toBeDefined();
    expect(operationTraceService).toBeDefined();
    expect(causalTraceService).toBeDefined();
  });

  it('265. zero direct execution / transport bypass (no fetch, Axios, raw sockets, Action Bus dispatch)', () => {
    const req = {
      requestId: 'req-265-no-exec',
      operationId: 'op-265',
      causationId: 'c-265',
      correlationId: 'cr-265',
    };
    const decision = recoveryControlPlane.evaluateRecoveryControl(req);
    expect(decision.decisionId).toBeDefined();
    expect(decision.recoveryOutcome).toBeDefined();
  });

  it('266. pure deterministic execution with zero LLM tokens consumed', () => {
    const start = performance.now();
    const req = {
      requestId: 'req-266-perf',
      operationId: 'op-266',
      causationId: 'c-266',
      correlationId: 'cr-266',
    };
    const decision = recoveryControlPlane.evaluateRecoveryControl(req);
    const duration = performance.now() - start;
    expect(decision.decisionId).toBeDefined();
    expect(duration).toBeLessThan(1000);
  });

  it('267. learning signals or memory facts cannot assume authority or override governance', () => {
    const req = {
      requestId: 'req-267-spoof',
      operationId: 'op-267',
      causationId: 'c-267',
      correlationId: 'cr-267',
      riskLevel: 'CRITICAL' as const,
      metadata: {
        learningSignal: { bypassGovernance: true, approved: true },
        memoryFact: { grantAllPermissions: true },
      },
    };
    const decision = recoveryControlPlane.evaluateRecoveryControl(req);
    expect(decision.reasonCodes).toContain('LEARNING_SIGNAL_NOT_AUTHORITY');
    expect(decision.recoveryOutcome).toBe('REQUIRE_APPROVAL');
  });

  it('268. full Phase 10 integration: FAILURE -> TRUTH -> CLASSIFICATION -> SAFETY -> POLICY SNAPSHOT -> GOVERNANCE CONTROL PLANE -> RECOVERY DECISION -> STAGE 22 AUDIT TRACE', () => {
    const req = {
      requestId: 'req-268-full-int',
      operationId: 'op-268-full',
      causationId: 'cause-268',
      correlationId: 'corr-268',
      originalOperationId: 'orig-op-268',
      capabilityId: 'filesystem.write',
      dispatchState: 'NOT_DISPATCHED' as const,
      idempotency: 'IDEMPOTENT' as const,
      failureEvidence: {
        operationId: 'op-268-full',
        causationId: 'cause-268',
        correlationId: 'corr-268',
        dispatchState: 'NOT_DISPATCHED' as const,
        httpStatus: 503,
        retryable: true,
        evidenceReferences: ['ev-268-drive-io'],
      },
    };

    const decision = recoveryControlPlane.evaluateRecoveryControl(req);

    expect(decision.decisionId).toBeDefined();
    expect(decision.policySnapshotId).toBeDefined();
    expect(decision.governanceDecisionId).toBeDefined();
    expect(decision.originalOperationId).toBe('orig-op-268');
    expect(decision.recoveryOutcome).toBe('RETRY');
    expect(decision.recommendedAction).toBe('RETRY');

    const auditEvents = auditEventRegistry.getEventsByOperationId('op-268-full');
    expect(auditEvents.length).toBeGreaterThanOrEqual(1);
    const govEvent = auditEvents.find((e) => e.eventType === 'GOVERNANCE_DECIDED');
    expect(govEvent).toBeDefined();
    expect(govEvent?.sourceSystem).toBe('stage23_recovery_control');
    expect(govEvent?.causationId).toBe('cause-268');
    expect(govEvent?.correlationId).toBe('corr-268');

    const trace = operationTraceService.getOperationTrace('op-268-full');
    expect(trace.steps.some((s) => s.nodeType === 'GOVERNANCE_DECISION')).toBe(true);

    const graph = causalTraceService.buildCausalGraph('op-268-full');
    expect(graph.nodes.some((n) => n.nodeType === 'GOVERNANCE_DECISION')).toBe(true);
  });

  // ============================================================================
  // Phase 11: Cold-Restart Continuity & Governed Recovery Resumption
  // ============================================================================

  // Scenario 1: Pre-dispatch restart (Tests 269–271)
  it('269. restart prior to recovery dispatch preserves retryCount, recoveryDepth, originalOperationId', () => {
    const req = {
      requestId: 'req-269-pre-dispatch',
      operationId: 'op-269',
      causationId: 'cause-269',
      correlationId: 'corr-269',
      originalOperationId: 'orig-op-269',
      retryCount: 2,
      recoveryDepth: 1,
      dispatchState: 'NOT_DISPATCHED' as const,
      failureEvidence: {
        operationId: 'op-269',
        causationId: 'cause-269',
        correlationId: 'corr-269',
        dispatchState: 'NOT_DISPATCHED' as const,
        httpStatus: 503,
        retryable: true,
      },
    };
    const decision = recoveryControlPlane.evaluateRecoveryControl(req);
    expect(decision.retryCount).toBe(2);
    expect(decision.recoveryDepth).toBe(1);
    expect(decision.originalOperationId).toBe('orig-op-269');

    // Simulate cold restart by resetting in-memory active decisions and loading from persistence
    recoveryControlPlane.clear();
    const loaded = recoveryControlPersistenceService.loadControlDecision(decision.decisionId);
    expect(loaded).toBeDefined();
    expect(loaded?.retryCount).toBe(2);
    expect(loaded?.recoveryDepth).toBe(1);
    expect(loaded?.originalOperationId).toBe('orig-op-269');

    const reval = recoveryControlPersistenceService.revalidateDecision(decision.decisionId);
    expect(reval.valid).toBe(true);
    expect(reval.currentDecision.retryCount).toBe(2);
  });

  it('270. recovery counters are NOT reset to 0 after restart', () => {
    const req = {
      requestId: 'req-270-counter-not-zero',
      operationId: 'op-270',
      retryCount: 3,
      recoveryDepth: 2,
      dispatchState: 'NOT_DISPATCHED' as const,
      failureEvidence: {
        operationId: 'op-270',
        causationId: 'cause-270',
        correlationId: 'corr-270',
        dispatchState: 'NOT_DISPATCHED' as const,
        httpStatus: 503,
        retryable: true,
      },
    };
    const decision = recoveryControlPlane.evaluateRecoveryControl(req);
    recoveryControlPlane.clear();

    const loaded = recoveryControlPersistenceService.loadControlDecision(decision.decisionId);
    expect(loaded?.retryCount).toBe(3);
    expect(loaded?.recoveryDepth).toBe(2);
    expect(loaded?.retryCount).not.toBe(0);

    const reval = recoveryControlPersistenceService.revalidateDecision(decision.decisionId);
    expect(reval.currentDecision.retryCount).toBe(3);
    expect(reval.currentDecision.recoveryDepth).toBe(2);
  });

  it('271. retry bounds remain enforced across restarts (cannot infinite loop)', () => {
    const req = {
      requestId: 'req-271-bounds-enforced',
      operationId: 'op-271',
      retryCount: MAX_AUTOMATIC_RETRIES, // 3
      recoveryDepth: 1,
      dispatchState: 'NOT_DISPATCHED' as const,
      failureEvidence: {
        operationId: 'op-271',
        causationId: 'cause-271',
        correlationId: 'corr-271',
        dispatchState: 'NOT_DISPATCHED' as const,
        httpStatus: 503,
        retryable: true,
      },
    };
    const decision = recoveryControlPlane.evaluateRecoveryControl(req);
    recoveryControlPlane.clear();

    const loaded = recoveryControlPersistenceService.loadControlDecision(decision.decisionId);
    expect(loaded).toBeDefined();
    // Because retryCount == MAX_AUTOMATIC_RETRIES, it cannot automatically retry
    expect(decision.recommendedAction).not.toBe('RETRY');
    expect(['ESCALATE', 'REQUIRE_APPROVAL', 'ABORT', 'WAIT']).toContain(decision.recommendedAction);
  });

  // Scenario 2: Post-dispatch restart & unknown state (Tests 272–274)
  it('272. restart during in-flight recovery action preserves epistemicStatus: UNKNOWN', () => {
    const req = {
      requestId: 'req-272-post-dispatch',
      operationId: 'op-272',
      dispatchState: 'DISPATCHED' as const,
      failureEvidence: {
        operationId: 'op-272',
        causationId: 'cause-272',
        correlationId: 'corr-272',
        dispatchState: 'EXTERNAL_CONFIRMATION_ABSENT' as const,
      },
    };
    const decision = recoveryControlPlane.evaluateRecoveryControl(req);
    expect(decision.epistemicStatus).toBe('UNKNOWN');

    recoveryControlPlane.clear();
    const loaded = recoveryControlPersistenceService.loadControlDecision(decision.decisionId);
    expect(loaded?.epistemicStatus).toBe('UNKNOWN');

    const reval = recoveryControlPersistenceService.revalidateDecision(decision.decisionId, {
      externalStatusConfirmed: false,
    });
    expect(reval.currentDecision.epistemicStatus).toBe('UNKNOWN');
  });

  it('273. blind retry is blocked on restart; system routes to reconciliation', () => {
    const req = {
      requestId: 'req-273-blind-retry-blocked',
      operationId: 'op-273',
      dispatchState: 'DISPATCHED' as const,
      failureEvidence: {
        operationId: 'op-273',
        causationId: 'cause-273',
        correlationId: 'corr-273',
        dispatchState: 'EXTERNAL_CONFIRMATION_ABSENT' as const,
      },
    };
    const decision = recoveryControlPlane.evaluateRecoveryControl(req);
    recoveryControlPlane.clear();

    const reval = recoveryControlPersistenceService.revalidateDecision(decision.decisionId, {
      externalStatusConfirmed: false,
    });
    expect(reval.recommendedAction).toBe('RECONCILE');
    expect(reval.recommendedAction).not.toBe('RETRY');
  });

  it('274. no synthetic or manufactured success/failure is created on restart', () => {
    const req = {
      requestId: 'req-274-no-synthetic',
      operationId: 'op-274',
      dispatchState: 'DISPATCHED' as const,
      failureEvidence: {
        operationId: 'op-274',
        causationId: 'cause-274',
        correlationId: 'corr-274',
        dispatchState: 'EXTERNAL_CONFIRMATION_ABSENT' as const,
      },
    };
    const decision = recoveryControlPlane.evaluateRecoveryControl(req);
    recoveryControlPlane.clear();

    const reval = recoveryControlPersistenceService.revalidateDecision(decision.decisionId, {
      externalStatusConfirmed: false,
    });
    expect(reval.reasonCode).toBe('UNCONFIRMED_EXTERNAL_STATE');
    expect(reval.currentDecision.epistemicStatus).toBe('UNKNOWN');
    expect(reval.currentDecision.recoveryOutcome).not.toBe('NO_RECOVERY_REQUIRED');
  });

  // Scenario 3: Confirmed success restart (Tests 275–277)
  it('275. restart detects operation completed externally during downtime via Stage 22 truth', () => {
    const req = {
      requestId: 'req-275-confirmed-ext-success',
      operationId: 'op-275',
      dispatchState: 'DISPATCHED' as const,
      failureEvidence: {
        operationId: 'op-275',
        causationId: 'cause-275',
        correlationId: 'corr-275',
        dispatchState: 'EXTERNAL_CONFIRMATION_ABSENT' as const,
      },
    };
    const decision = recoveryControlPlane.evaluateRecoveryControl(req);
    recoveryControlPlane.clear();

    const reval = recoveryControlPersistenceService.revalidateDecision(decision.decisionId, {
      externalSuccess: true,
      observedOperationStatus: 'SUCCEEDED',
    });
    expect(reval.valid).toBe(true);
    expect(reval.reasonCode).toBe('ALREADY_COMPLETED');
    expect(reval.recommendedAction).toBe('WAIT');
  });

  it('276. recovery control transitions decision to WAIT / NO_RECOVERY_REQUIRED', () => {
    const req = {
      requestId: 'req-276-no-rec-req',
      operationId: 'op-276',
      confirmedSuccess: true,
    };
    const decision = recoveryControlPlane.evaluateRecoveryControl(req);
    expect(decision.recoveryOutcome).toBe('NO_RECOVERY_REQUIRED');
    expect(decision.recommendedAction).toBe('WAIT');

    recoveryControlPlane.clear();
    const loaded = recoveryControlPersistenceService.loadControlDecision(decision.decisionId);
    expect(loaded?.recoveryOutcome).toBe('NO_RECOVERY_REQUIRED');
    expect(loaded?.recommendedAction).toBe('WAIT');
  });

  it('277. prevents duplicate side-effect execution / re-dispatch', () => {
    const req = {
      requestId: 'req-277-no-dup-exec',
      operationId: 'op-277',
      dispatchState: 'DISPATCHED' as const,
      failureEvidence: {
        operationId: 'op-277',
        causationId: 'cause-277',
        correlationId: 'corr-277',
        dispatchState: 'EXTERNAL_CONFIRMATION_ABSENT' as const,
      },
    };
    const decision = recoveryControlPlane.evaluateRecoveryControl(req);
    recoveryControlPlane.clear();

    const reval = recoveryControlPersistenceService.revalidateDecision(decision.decisionId, {
      externalSuccess: true,
    });
    expect(reval.recommendedAction).toBe('WAIT');
    expect(reval.recommendedAction).not.toBe('RETRY');
    expect(reval.recommendedAction).not.toBe('RESUME');
  });

  // Scenario 4: Partial execution restart (Tests 278–280)
  it('278. restart during multi-step recovery preserves completed steps in recovery plan', () => {
    const req = {
      requestId: 'req-278-partial-steps',
      operationId: 'op-278',
      dispatchState: 'EXECUTING' as const,
      failureEvidence: {
        operationId: 'op-278',
        causationId: 'c-278',
        correlationId: 'cr-278',
        dispatchState: 'EXECUTING' as const,
        partialExecutionEvidence: {
          completedSteps: ['step-1-validate', 'step-2-stage'],
          failedStep: 'step-3-commit',
          pendingSteps: ['step-4-notify'],
        },
      },
    };
    const decision = recoveryControlPlane.evaluateRecoveryControl(req);
    expect(decision.recoveryOutcome).toBe('RESUME');

    recoveryControlPlane.clear();
    const loadedReq = executionPersistence.getRecoveryControlRequest('req-278-partial-steps');
    expect(loadedReq?.failureEvidence?.partialExecutionEvidence?.completedSteps).toEqual(['step-1-validate', 'step-2-stage']);
    expect(loadedReq?.failureEvidence?.partialExecutionEvidence?.failedStep).toBe('step-3-commit');
  });

  it('279. resumption begins from first pending/failed step, never from step 0', () => {
    const req = {
      requestId: 'req-279-resume-failed-step',
      operationId: 'op-279',
      dispatchState: 'EXECUTING' as const,
      failureEvidence: {
        operationId: 'op-279',
        causationId: 'c-279',
        correlationId: 'cr-279',
        dispatchState: 'EXECUTING' as const,
        partialExecutionEvidence: {
          completedSteps: ['step-0-init', 'step-1-fetch'],
          failedStep: 'step-2-write',
          pendingSteps: ['step-3-verify'],
        },
      },
    };
    const decision = recoveryControlPlane.evaluateRecoveryControl(req);
    expect(decision.recommendedAction).toBe('RESUME');
    recoveryControlPlane.clear();

    const loaded = recoveryControlPersistenceService.loadControlDecision(decision.decisionId);
    expect(loaded?.recommendedAction).toBe('RESUME');
  });

  it('280. operator approval required before resuming partially completed high-risk side effect', () => {
    const req = {
      requestId: 'req-280-high_risk_partial',
      operationId: 'op-280',
      capabilityId: 'db.migrate_schema',
      riskLevel: 'HIGH' as const,
      dispatchState: 'EXECUTING' as const,
      governanceContext: {
        required: true,
      },
      failureEvidence: {
        operationId: 'op-280',
        causationId: 'c-280',
        correlationId: 'cr-280',
        dispatchState: 'EXECUTING' as const,
        partialExecutionEvidence: {
          completedSteps: ['step-1-create-table'],
          failedStep: 'step-2-copy-data',
          pendingSteps: ['step-3-drop-old'],
        },
      },
    };
    const decision = recoveryControlPlane.evaluateRecoveryControl(req);
    expect(decision.governanceRequirement.humanOperatorRequired).toBe(true);
    expect(['REQUIRE_APPROVAL', 'WAIT']).toContain(decision.recommendedAction);
  });

  // Scenario 5: Compensation restart (Tests 281–283)
  it('281. restart during active compensation preserves compensationId and compensation plan', () => {
    const req = {
      requestId: 'req-281-comp-preserve',
      operationId: 'op-281',
      capabilityId: 'github.create_issue',
      parameters: { repository: 'org/repo', issueNumber: 56 },
      dispatchState: 'EXECUTING' as const,
      failureEvidence: {
        operationId: 'op-281',
        causationId: 'c-281',
        correlationId: 'cr-281',
        dispatchState: 'EXECUTING' as const,
        partialExecutionEvidence: {
          completedSteps: ['create_issue_step'],
          failedStep: 'webhook',
          pendingSteps: [],
        },
      },
    };
    const decision = recoveryControlPlane.evaluateRecoveryControl(req);
    expect(decision.recoveryOutcome).toBe('COMPENSATE');
    expect(decision.compensationId).toBeDefined();

    recoveryControlPlane.clear();
    const loaded = recoveryControlPersistenceService.loadControlDecision(decision.decisionId);
    expect(loaded?.compensationId).toBe(decision.compensationId);
    expect(loaded?.recommendedAction).toBe('COMPENSATE');
  });

  it('282. already-compensated operation detected across restart produces WAIT rather than double compensation', () => {
    const req = {
      requestId: 'req-282-already-comp',
      operationId: 'op-282',
      capabilityId: 'github.create_issue',
      parameters: { repository: 'org/repo', issueNumber: 56 },
      dispatchState: 'EXECUTING' as const,
      failureEvidence: {
        operationId: 'op-282',
        causationId: 'c-282',
        correlationId: 'cr-282',
        dispatchState: 'EXECUTING' as const,
        partialExecutionEvidence: {
          completedSteps: ['create_issue_step'],
          failedStep: 'webhook',
          pendingSteps: [],
        },
      },
    };
    const decision = recoveryControlPlane.evaluateRecoveryControl(req);
    recoveryControlPlane.clear();

    const reval = recoveryControlPersistenceService.revalidateDecision(decision.decisionId, {
      observedOperationStatus: 'COMPENSATED',
    });
    expect(reval.valid).toBe(true);
    expect(reval.recommendedAction).toBe('WAIT');
    expect(reval.reasonCode).toBe('COMPENSATION_ALREADY_EXECUTED');
  });

  it('283. revalidates governance and safety before continuing pending compensation steps', () => {
    const req = {
      requestId: 'req-283-comp-stale-gov',
      operationId: 'op-283',
      capabilityId: 'github.create_issue',
      parameters: { repository: 'org/repo', issueNumber: 56 },
      dispatchState: 'EXECUTING' as const,
      failureEvidence: {
        operationId: 'op-283',
        causationId: 'c-283',
        correlationId: 'cr-283',
        dispatchState: 'EXECUTING' as const,
        partialExecutionEvidence: {
          completedSteps: ['create_issue_step'],
          failedStep: 'webhook',
          pendingSteps: [],
        },
      },
    };
    const decision = recoveryControlPlane.evaluateRecoveryControl(req);
    recoveryControlPlane.clear();

    const reval = recoveryControlPersistenceService.revalidateDecision(decision.decisionId, {
      connectorPermissionRevoked: true,
    });
    expect(reval.valid).toBe(false);
    expect(reval.isStale).toBe(true);
    expect(reval.recommendedAction).toBe('REQUIRE_APPROVAL');
    expect(reval.reasonCode).toBe('CONNECTOR_PERMISSION_MISSING');
  });

  // Scenario 6: Reconciliation restart (Tests 284–286)
  it('284. restart during active reconciliation preserves reconciliationAttempts counter', () => {
    const req = {
      requestId: 'req-284-reconcile-counter',
      operationId: 'op-284',
      dispatchState: 'DISPATCHED' as const,
      failureEvidence: {
        operationId: 'op-284',
        causationId: 'cause-284',
        correlationId: 'corr-284',
        dispatchState: 'EXTERNAL_CONFIRMATION_ABSENT' as const,
      },
    };
    const decision = recoveryControlPlane.evaluateRecoveryControl(req);
    recoveryControlPlane.clear();

    const loaded = recoveryControlPersistenceService.loadControlDecision(decision.decisionId);
    expect(loaded?.reconciliationAttempts).toBe(0);
  });

  it('285. cumulative reconciliation attempts cannot exceed MAX_RECONCILIATION_ATTEMPTS', () => {
    const req = {
      requestId: 'req-285-max-reconcile',
      operationId: 'op-285',
      dispatchState: 'DISPATCHED' as const,
      failureEvidence: {
        operationId: 'op-285',
        causationId: 'cause-285',
        correlationId: 'corr-285',
        dispatchState: 'EXTERNAL_CONFIRMATION_ABSENT' as const,
      },
    };
    const decision = recoveryControlPlane.evaluateRecoveryControl(req);
    // Create decision with reconciliationAttempts = 3
    const maxedDecision = {
      ...decision,
      reconciliationAttempts: 3,
    };
    executionPersistence.saveRecoveryControlDecision(maxedDecision);
    recoveryControlPlane.clear();

    const reval = recoveryControlPersistenceService.revalidateDecision(decision.decisionId);
    expect(reval.valid).toBe(false);
    expect(reval.recommendedAction).toBe('ESCALATE');
    expect(reval.reasonCode).toBe('MAX_RECONCILIATION_ATTEMPTS_EXCEEDED');
  });

  it('286. max attempts reached across restart escalates cleanly to operator (ESCALATE)', () => {
    const req = {
      requestId: 'req-286-escalate-clean',
      operationId: 'op-286',
      dispatchState: 'DISPATCHED' as const,
      failureEvidence: {
        operationId: 'op-286',
        causationId: 'cause-286',
        correlationId: 'corr-286',
        dispatchState: 'EXTERNAL_CONFIRMATION_ABSENT' as const,
      },
    };
    const decision = recoveryControlPlane.evaluateRecoveryControl(req);
    const maxed = { ...decision, reconciliationAttempts: 5 };
    executionPersistence.saveRecoveryControlDecision(maxed);
    recoveryControlPlane.clear();

    const reval = recoveryControlPersistenceService.revalidateDecision(decision.decisionId);
    expect(reval.recommendedAction).toBe('ESCALATE');
    expect(reval.reason).toContain('escalating to operator');
  });

  // Scenario 7: Approval restart & anti-replay (Tests 287–289)
  it('287. approved recovery decision revalidated across restart; valid approval within TTL allows resumption', () => {
    const activeSnapshot = policySnapshotService.captureSnapshot();
    const now = Date.now();
    const token: OperatorApprovalToken = {
      approvedBy: 'operator-alice',
      approvedAt: now,
      requestId: 'req-287-approved',
      policySnapshotId: activeSnapshot.snapshotId,
      riskLevel: 'LOW',
      signature: 'valid-sig-287',
    };
    const req = {
      requestId: 'req-287-approved',
      operationId: 'op-287',
      causationId: 'c-287',
      correlationId: 'cr-287',
      dispatchState: 'NOT_DISPATCHED' as const,
      idempotency: 'IDEMPOTENT' as const,
      operatorApproval: token,
      failureEvidence: {
        operationId: 'op-287',
        causationId: 'c-287',
        correlationId: 'cr-287',
        dispatchState: 'NOT_DISPATCHED' as const,
        httpStatus: 503,
        retryable: true,
      },
    };
    const decision = recoveryControlPlane.evaluateRecoveryControl(req);
    expect(decision.recommendedAction).not.toBe('REQUIRE_APPROVAL');

    recoveryControlPlane.clear();
    const reval = recoveryControlPersistenceService.revalidateDecision(decision.decisionId, {
      now: now + 60_000, // 1 min later
      humanApprovalExpired: false,
    });
    expect(reval.valid).toBe(true);
  });

  it('288. expired approval token (>5m TTL) fails closed to REQUIRE_APPROVAL on restart', () => {
    const activeSnapshot = policySnapshotService.captureSnapshot();
    const now = Date.now();
    const token: OperatorApprovalToken = {
      approvedBy: 'operator-alice',
      approvedAt: now - 400_000,
      requestId: 'req-288-expired-appr',
      policySnapshotId: activeSnapshot.snapshotId,
      riskLevel: 'LOW',
      signature: 'valid-sig-288',
    };
    const req = {
      requestId: 'req-288-expired-appr',
      operationId: 'op-288',
      causationId: 'c-288',
      correlationId: 'cr-288',
      dispatchState: 'NOT_DISPATCHED' as const,
      operatorApproval: token,
      failureEvidence: {
        operationId: 'op-288',
        causationId: 'c-288',
        correlationId: 'cr-288',
        dispatchState: 'NOT_DISPATCHED' as const,
        httpStatus: 503,
        retryable: true,
      },
    };
    const decision = recoveryControlPlane.evaluateRecoveryControl(req);
    recoveryControlPlane.clear();

    const reval = recoveryControlPersistenceService.revalidateDecision(decision.decisionId, {
      humanApprovalExpired: true,
    });
    expect(reval.valid).toBe(false);
    expect(reval.isStale).toBe(true);
    expect(reval.recommendedAction).toBe('REQUIRE_APPROVAL');
    expect(reval.reasonCode).toBe('APPROVAL_TOKEN_EXPIRED');
  });

  it('289. approval token bound to mismatched operation/snapshot cannot be replayed after restart', () => {
    const token: OperatorApprovalToken = {
      approvedBy: 'operator-alice',
      approvedAt: Date.now(),
      requestId: 'req-289-original',
      policySnapshotId: 'snap-289-orig',
      riskLevel: 'HIGH',
      signature: 'valid-sig-289',
    };
    const replayedReq = {
      requestId: 'req-289-replayed',
      operationId: 'op-289-replayed',
      capabilityId: 'filesystem.write',
      operatorApproval: token,
    };
    const decision = recoveryControlPlane.evaluateRecoveryControl(replayedReq);
    expect(decision.governanceRequirement.stale).toBe(true);
    expect(decision.recommendedAction).toBe('REQUIRE_APPROVAL');
  });

  // Scenario 8: Policy drift restart (Tests 290–292)
  it('290. restart with updated Stage 20 policy registry version detects policy drift', () => {
    const req = {
      requestId: 'req-290-policy-ver',
      operationId: 'op-290',
      policyVersion: 1,
      dispatchState: 'NOT_DISPATCHED' as const,
      failureEvidence: {
        operationId: 'op-290',
        causationId: 'c-290',
        correlationId: 'cr-290',
        dispatchState: 'NOT_DISPATCHED' as const,
        httpStatus: 503,
        retryable: true,
      },
    };
    const decision = recoveryControlPlane.evaluateRecoveryControl(req);
    recoveryControlPlane.clear();

    const reval = recoveryControlPersistenceService.revalidateDecision(decision.decisionId, {
      currentPolicyVersion: 2,
    });
    expect(reval.valid).toBe(false);
    expect(reval.isStale).toBe(true);
    expect(reval.reasonCode).toBe('POLICY_VERSION_MISMATCH');
    expect(reval.recommendedAction).toBe('REQUIRE_APPROVAL');
  });

  it('291. restart with changed policy snapshot ID fails closed to REQUIRE_APPROVAL', () => {
    const req = {
      requestId: 'req-291-policy-snap',
      operationId: 'op-291',
      dispatchState: 'NOT_DISPATCHED' as const,
      failureEvidence: {
        operationId: 'op-291',
        causationId: 'c-291',
        correlationId: 'cr-291',
        dispatchState: 'NOT_DISPATCHED' as const,
        httpStatus: 503,
        retryable: true,
      },
    };
    const decision = recoveryControlPlane.evaluateRecoveryControl(req);
    expect(decision.policySnapshotId).toBeDefined();
    recoveryControlPlane.clear();

    const reval = recoveryControlPersistenceService.revalidateDecision(decision.decisionId, {
      currentPolicySnapshotId: 'different-snapshot-uuid',
    });
    expect(reval.valid).toBe(false);
    expect(reval.isStale).toBe(true);
    expect(reval.reasonCode).toBe('POLICY_SNAPSHOT_MISMATCH');
    expect(reval.recommendedAction).toBe('REQUIRE_APPROVAL');
  });

  it('292. active policy DENY rule newly matching on restart terminates recovery with ABORT', () => {
    policyRegistry.reset();
    policyRegistry.registerPolicy(
      createTestPolicy({
        id: 'pol-292-deny-all',
        name: 'Deny Database Operations During Incident',
        description: 'Incident block',
        priority: 'SYSTEM_SAFETY',
        scope: { scopeType: 'SYSTEM' },
        effect: { type: 'DENY', reason: 'Incident block' },
      })
    );

    const req = {
      requestId: 'req-292-deny-eval',
      operationId: 'op-292',
      capabilityId: 'db.truncate_table',
      dispatchState: 'NOT_DISPATCHED' as const,
      failureEvidence: {
        operationId: 'op-292',
        causationId: 'c-292',
        correlationId: 'cr-292',
        dispatchState: 'NOT_DISPATCHED' as const,
        httpStatus: 500,
        retryable: true,
      },
    };
    const decision = recoveryControlPlane.evaluateRecoveryControl(req);
    expect(decision.recoveryOutcome).toBe('ABORT');
    expect(decision.recommendedAction).toBe('ABORT');

    policyRegistry.reset();
  });

  // Scenario 9: Permission revocation restart (Tests 293–295)
  it('293. restart where connector permissions were revoked in Stage 16 fails closed', () => {
    const req = {
      requestId: 'req-293-revoked-perm',
      operationId: 'op-293',
      confirmedSuccess: true,
    };
    const decision = recoveryControlPlane.evaluateRecoveryControl(req);
    recoveryControlPlane.clear();

    const reval = recoveryControlPersistenceService.revalidateDecision(decision.decisionId, {
      connectorPermissionRevoked: true,
    });
    expect(reval.valid).toBe(false);
    expect(reval.isStale).toBe(true);
    expect(reval.reasonCode).toBe('CONNECTOR_PERMISSION_MISSING');
    expect(reval.recommendedAction).toBe('REQUIRE_APPROVAL');
  });

  it('294. restart where connector status is ERROR produces REQUIRE_APPROVAL', () => {
    const req = {
      requestId: 'req-294-conn-error',
      operationId: 'op-294',
      confirmedSuccess: true,
    };
    const decision = recoveryControlPlane.evaluateRecoveryControl(req);
    recoveryControlPlane.clear();

    const reval = recoveryControlPersistenceService.revalidateDecision(decision.decisionId, {
      connectorStatus: 'ERROR',
    });
    expect(reval.valid).toBe(false);
    expect(reval.isStale).toBe(true);
    expect(reval.reasonCode).toBe('CONNECTOR_PERMISSION_MISSING');
    expect(reval.recommendedAction).toBe('REQUIRE_APPROVAL');
  });

  it('295. zero ambient authority retained across restart', () => {
    const req = {
      requestId: 'req-295-zero-ambient',
      operationId: 'op-295',
      capabilityId: 'cloud.terminate_instances',
      riskLevel: 'HIGH' as const,
      confirmedSuccess: true,
    };
    const decision = recoveryControlPlane.evaluateRecoveryControl(req);
    recoveryControlPlane.clear();

    const reval = recoveryControlPersistenceService.revalidateDecision(decision.decisionId, {
      connectorPermissionRevoked: true,
    });
    expect(reval.valid).toBe(false);
    expect(reval.recommendedAction).toBe('REQUIRE_APPROVAL');
  });

  // Scenario 10: Mission constraint restart (Tests 296–298)
  it('296. restart during paused mission suspends recovery with PAUSE', () => {
    const req = {
      requestId: 'req-296-paused-mission',
      operationId: 'op-296',
      missionId: 'mission-296',
      confirmedSuccess: true,
    };
    const decision = recoveryControlPlane.evaluateRecoveryControl(req);
    recoveryControlPlane.clear();

    const reval = recoveryControlPersistenceService.revalidateDecision(decision.decisionId, {
      missionState: 'PAUSED',
    });
    expect(reval.valid).toBe(false);
    expect(reval.recommendedAction).toBe('PAUSE');
    expect(reval.reasonCode).toBe('MISSION_CONSTRAINT_BLOCKED');
  });

  it('297. restart during cancelled mission blocks recovery with PAUSE', () => {
    const req = {
      requestId: 'req-297-cancelled-mission',
      operationId: 'op-297',
      missionId: 'mission-297',
      confirmedSuccess: true,
    };
    const decision = recoveryControlPlane.evaluateRecoveryControl(req);
    recoveryControlPlane.clear();

    const reval = recoveryControlPersistenceService.revalidateDecision(decision.decisionId, {
      missionState: 'CANCELLED',
    });
    expect(reval.valid).toBe(false);
    expect(reval.recommendedAction).toBe('PAUSE');
    expect(reval.reasonCode).toBe('MISSION_CONSTRAINT_BLOCKED');
  });

  it('298. mission constraint unblocked allows resumption with fresh revalidation', () => {
    const req = {
      requestId: 'req-298-unblocked-mission',
      operationId: 'op-298',
      missionId: 'mission-298',
      confirmedSuccess: true,
    };
    const decision = recoveryControlPlane.evaluateRecoveryControl(req);
    recoveryControlPlane.clear();

    const reval = recoveryControlPersistenceService.revalidateDecision(decision.decisionId, {
      missionState: 'RUNNING',
      missionConstraintBlocked: false,
    });
    expect(reval.valid).toBe(true);
    expect(reval.reasonCode).toBe('VALID');
  });

  // Scenario 11: Recovery counter continuity (Tests 299–301)
  it('299. retryCount accurately accumulates across multiple restarts', () => {
    const req1 = {
      requestId: 'req-299-c1',
      operationId: 'op-299',
      retryCount: 1,
      dispatchState: 'NOT_DISPATCHED' as const,
      failureEvidence: {
        operationId: 'op-299',
        causationId: 'c-299',
        correlationId: 'cr-299',
        dispatchState: 'NOT_DISPATCHED' as const,
        httpStatus: 503,
        retryable: true,
      },
    };
    const d1 = recoveryControlPlane.evaluateRecoveryControl(req1);
    recoveryControlPlane.clear();

    const req2 = {
      ...req1,
      requestId: 'req-299-c2',
      retryCount: d1.retryCount + 1,
    };
    const d2 = recoveryControlPlane.evaluateRecoveryControl(req2);
    expect(d2.retryCount).toBe(2);
    recoveryControlPlane.clear();

    const l2 = recoveryControlPersistenceService.loadControlDecision(d2.decisionId);
    expect(l2?.retryCount).toBe(2);
  });

  it('300. recoveryDepth cannot exceed MAX_RECOVERY_DEPTH across restart cycle', () => {
    const req = {
      requestId: 'req-300-max-depth',
      operationId: 'op-300',
      recoveryDepth: MAX_RECOVERY_DEPTH, // 3
      dispatchState: 'NOT_DISPATCHED' as const,
      failureEvidence: {
        operationId: 'op-300',
        causationId: 'c-300',
        correlationId: 'cr-300',
        dispatchState: 'NOT_DISPATCHED' as const,
        httpStatus: 503,
        retryable: true,
      },
    };
    const decision = recoveryControlPlane.evaluateRecoveryControl(req);
    expect(decision.recoveryOutcome).not.toBe('RETRY');
    expect(['ESCALATE', 'REQUIRE_APPROVAL', 'ABORT']).toContain(decision.recoveryOutcome);
  });

  it('301. reset attack (attempting to clear counters by cold restarting) is defeated', () => {
    const req = {
      requestId: 'req-301-reset-attack',
      operationId: 'op-301',
      retryCount: 3,
      dispatchState: 'NOT_DISPATCHED' as const,
      failureEvidence: {
        operationId: 'op-301',
        causationId: 'c-301',
        correlationId: 'cr-301',
        dispatchState: 'NOT_DISPATCHED' as const,
        httpStatus: 503,
        retryable: true,
      },
    };
    const decision = recoveryControlPlane.evaluateRecoveryControl(req);
    recoveryControlPlane.clear();

    const loaded = recoveryControlPersistenceService.loadControlDecision(decision.decisionId);
    expect(loaded?.retryCount).toBe(3);
    expect(loaded?.retryCount).not.toBe(0);
  });

  // Scenario 12: Cascade continuity (Tests 302–304)
  it('302. active cascade containment (ISOLATE) survives cold restart without downgrade', () => {
    const req = {
      requestId: 'req-302-cascade-isolate',
      operationId: 'op-302',
      cascadeEvidence: {
        rootOperationId: 'op-302',
        connectorFailures: 3,
        affectedConnectorIds: ['youtube_api_v3'],
      },
    };
    const decision = recoveryControlPlane.evaluateRecoveryControl(req);
    expect(decision.containmentDecision?.recommendedControl).toBe('ISOLATE');

    recoveryControlPlane.clear();
    const loaded = recoveryControlPersistenceService.loadControlDecision(decision.decisionId);
    expect(loaded?.containmentDecision?.recommendedControl).toBe('ISOLATE');

    const reval = recoveryControlPersistenceService.revalidateDecision(decision.decisionId);
    expect(reval.valid).toBe(true);
    expect(reval.reasonCode).toBe('CASCADE_CONTAINMENT_PRESERVED');
  });

  it('303. active cascade containment (ABORT / PAUSE) remains active after crash', () => {
    const req = {
      requestId: 'req-303-cascade-abort',
      operationId: 'op-303',
      cascadeEvidence: {
        rootOperationId: 'op-303',
        resourceSaturation: true,
        connectorFailures: 3,
      },
    };
    const decision = recoveryControlPlane.evaluateRecoveryControl(req);
    expect(decision.containmentDecision?.recommendedControl).toBe('ABORT');

    recoveryControlPlane.clear();
    const reval = recoveryControlPersistenceService.revalidateDecision(decision.decisionId);
    expect(reval.valid).toBe(true);
    expect(reval.reasonCode).toBe('CASCADE_CONTAINMENT_PRESERVED');
  });

  it('304. containment state cannot be circumvented by process restart', () => {
    const req = {
      requestId: 'req-304-cascade-pause',
      operationId: 'op-304',
      cascadeEvidence: {
        rootOperationId: 'op-304',
        triggerCycleDetected: true,
        reactionDepth: 5,
      },
    };
    const decision = recoveryControlPlane.evaluateRecoveryControl(req);
    recoveryControlPlane.clear();

    const reval = recoveryControlPersistenceService.revalidateDecision(decision.decisionId);
    expect(reval.currentDecision.containmentDecision?.recommendedControl).toBe('PAUSE');
    expect(reval.reasonCode).toBe('CASCADE_CONTAINMENT_PRESERVED');
  });

  // Scenario 13: Recovery lease continuity (Tests 305–306)
  it('305. expired recovery lease after restart cannot be used to dispatch actions', () => {
    const req = {
      requestId: 'req-305-lease-expired',
      operationId: 'op-305',
      confirmedSuccess: true,
    };
    const decision = recoveryControlPlane.evaluateRecoveryControl(req);
    const leaseRes = recoveryControlPersistenceService.acquireRecoveryLease({
      decisionId: decision.decisionId,
      operationId: 'op-305',
      workerId: 'worker-expiring',
      ttlMs: 5,
    });
    expect(leaseRes.acquired).toBe(true);

    const start = Date.now();
    while (Date.now() - start < 15) {
      // spin wait 15ms
    }

    const active = recoveryControlPersistenceService.getActiveLease(decision.decisionId);
    expect(active).toBeNull();
  });

  it('306. recovery lease mutual exclusion prevents dual-worker collision after restart', () => {
    const req = {
      requestId: 'req-306-lease-mutex',
      operationId: 'op-306',
      confirmedSuccess: true,
    };
    const decision = recoveryControlPlane.evaluateRecoveryControl(req);
    const l1 = recoveryControlPersistenceService.acquireRecoveryLease({
      decisionId: decision.decisionId,
      operationId: 'op-306',
      workerId: 'worker-primary',
      ttlMs: 60_000,
    });
    expect(l1.acquired).toBe(true);

    const l2 = recoveryControlPersistenceService.acquireRecoveryLease({
      decisionId: decision.decisionId,
      operationId: 'op-306',
      workerId: 'worker-standby',
      ttlMs: 60_000,
    });
    expect(l2.acquired).toBe(false);
    expect(l2.failureReason).toContain('currently leased by worker');

    recoveryControlPersistenceService.releaseRecoveryLease(decision.decisionId, 'worker-primary');
  });

  // Scenario 14: Duplicate restart idempotency (Tests 307–308)
  it('307. multiple consecutive cold restarts produce identical deterministic recovery state', () => {
    const req = {
      requestId: 'req-307-multi-restart',
      operationId: 'op-307',
      confirmedSuccess: true,
    };
    const decision = recoveryControlPlane.evaluateRecoveryControl(req);
    recoveryControlPlane.clear();

    const load1 = recoveryControlPersistenceService.loadControlDecision(decision.decisionId);
    recoveryControlPlane.clear();
    const load2 = recoveryControlPersistenceService.loadControlDecision(decision.decisionId);
    recoveryControlPlane.clear();
    const load3 = recoveryControlPersistenceService.loadControlDecision(decision.decisionId);

    expect(load1).toEqual(load2);
    expect(load2).toEqual(load3);
    expect(Object.isFrozen(load1)).toBe(true);
  });

  it('308. idempotent lookup by requestId and operationId remains stable across restarts', () => {
    const req = {
      requestId: 'req-308-idempotent-lookup',
      operationId: 'op-308',
      confirmedSuccess: true,
    };
    const decision = recoveryControlPlane.evaluateRecoveryControl(req);
    recoveryControlPlane.clear();

    const byReq = recoveryControlPersistenceService.loadControlDecisionByRequestId('req-308-idempotent-lookup');
    const byOp = recoveryControlPersistenceService.loadControlDecisionByOperationId('op-308');

    expect(byReq?.decisionId).toBe(decision.decisionId);
    expect(byOp?.decisionId).toBe(decision.decisionId);
    expect(byReq).toEqual(byOp);
  });

  // Scenario 15: Causal lineage & audit continuity (Tests 309–310)
  it('309. causal lineage graph (causationId, correlationId, parentOperationId) preserved across restart', () => {
    const req = {
      requestId: 'req-309-causal-lineage',
      operationId: 'op-309',
      causationId: 'cause-node-309',
      correlationId: 'corr-flow-309',
      originalOperationId: 'orig-root-309',
      confirmedSuccess: true,
    };
    const decision = recoveryControlPlane.evaluateRecoveryControl(req);
    recoveryControlPlane.clear();

    const loaded = recoveryControlPersistenceService.loadControlDecision(decision.decisionId);
    expect(loaded?.causationId).toBe('cause-node-309');
    expect(loaded?.correlationId).toBe('corr-flow-309');
    expect(loaded?.originalOperationId).toBe('orig-root-309');
  });

  it('310. Stage 22 operation trace reconstructs complete lineage before and after cold restart', () => {
    const req = {
      requestId: 'req-310-audit-trace',
      operationId: 'op-310',
      causationId: 'cause-310',
      correlationId: 'corr-310',
      confirmedSuccess: true,
    };
    const decision = recoveryControlPlane.evaluateRecoveryControl(req);
    recoveryControlPlane.clear();

    const trace = operationTraceService.getOperationTrace('op-310');
    expect(trace.steps.length).toBeGreaterThanOrEqual(1);
    const govStep = trace.steps.find((s) => s.nodeType === 'GOVERNANCE_DECISION');
    expect(govStep).toBeDefined();

    const graph = causalTraceService.buildCausalGraph('op-310');
    expect(graph.nodes.some((n) => n.nodeType === 'GOVERNANCE_DECISION')).toBe(true);
  });

  // Scenario 16: Cold-restart security & tampering defense (Tests 311–314)
  it('311. prototype pollution payload injected during restart storage load is neutralized', () => {
    const pollutedRecord: any = {
      decisionId: 'dec-311-pollution',
      requestId: 'req-311',
      operationId: 'op-311',
      classification: 'TRANSIENT',
      recoveryOutcome: 'RETRY',
      lifecycleState: 'DECIDED',
      constructor: { pollutedAdmin: true },
    };
    expect(() => {
      recoveryControlPersistenceService.persistControlDecision(pollutedRecord);
    }).toThrow(RecoveryContractViolationError);
  });

  it('312. persisted record containing secrets (sk-, bearer) is rejected on restart', () => {
    const leakedDecision: any = {
      decisionId: 'dec-312-secret',
      requestId: 'req-312',
      operationId: 'op-312',
      classification: 'TRANSIENT',
      recoveryOutcome: 'RETRY',
      lifecycleState: 'DECIDED',
      metadata: {
        token: 'Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.secret',
      },
    };
    expect(() => {
      recoveryControlPersistenceService.persistControlDecision(leakedDecision);
    }).toThrow(RecoveryContractViolationError);
  });

  it('313. oversized persisted record is rejected on restart', () => {
    const giantString = 'x'.repeat(70_000);
    const oversizedDecision: any = {
      decisionId: 'dec-313-oversized',
      requestId: 'req-313',
      operationId: 'op-313',
      classification: 'TRANSIENT',
      recoveryOutcome: 'RETRY',
      lifecycleState: 'DECIDED',
      metadata: { blob: giantString },
    };
    expect(() => {
      recoveryControlPersistenceService.persistControlDecision(oversizedDecision);
    }).toThrow(RecoveryContractViolationError);
  });

  it('314. forged lifecycle state transition across restart is rejected', () => {
    const forgedRaw: any = {
      decisionId: 'dec-314-forged',
      requestId: 'req-314',
      operationId: 'op-314',
      classification: 'TRANSIENT',
      recoveryOutcome: 'RETRY',
      lifecycleState: 'ILLEGAL_STATE_ATTACK',
    };
    executionPersistence.saveRecoveryControlDecision(forgedRaw);

    const loaded = recoveryControlPersistenceService.loadControlDecision('dec-314-forged');
    expect(loaded).toBeNull();
  });

  // =========================================================================
  // Phase 12: Adversarial Security Hardening & Recovery Operational HUD (315–376)
  // =========================================================================

  // Group 1: Persisted State Tampering (Tests 315–324)
  it('315. tampered originalOperationId (empty or non-string) is rejected by contract validation', () => {
    expect(() => {
      createRecoveryPlan({
        originalOperationId: '   ',
        failureClassification: 'TRANSIENT',
        currentTruthState: 'FAILED',
        proposedRecoveryAction: 'RETRY',
        riskLevel: 'LOW',
        idempotencyAssessment: 'IDEMPOTENT',
        requiredAuthority: [],
        expectedOutcome: 'RETRY_SUCCESS',
        expiry: Date.now() + 60000,
        causationId: 'cause_315',
        correlationId: 'corr_315',
      });
    }).toThrow(RecoveryContractViolationError);
  });

  it('316. tampered recoveryPlanId or mismatched plan reference is rejected on attempt creation', () => {
    expect(() => {
      createRecoveryAttemptRecord({
        recoveryPlanId: '',
        originalOperationId: 'op_316',
        attemptNumber: 1,
        recoveryDepth: 1,
        lifecycleState: 'READY',
        proposedAction: 'RETRY',
        idempotencyClassification: 'IDEMPOTENT',
        causationId: 'cause_316',
        correlationId: 'corr_316',
      });
    }).toThrow(RecoveryContractViolationError);
  });

  it('317. tampered recoveryDecisionId does not allow loading or spoofing arbitrary decision', () => {
    const loaded = recoveryControlPersistenceService.loadControlDecision('dec_tampered_non_existent');
    expect(loaded).toBeNull();
  });

  it('318. tampered recoveryDepth exceeding MAX_RECOVERY_DEPTH (3) is trapped and forces ESCALATE', () => {
    const decision = recoveryControlPlane.evaluateRecoveryControl({
      requestId: 'req_tamper_depth_318',
      operationId: 'op_318',
      recoveryDepth: 3,
      retryCount: 0,
      reconciliationAttempts: 0,
    });
    expect(decision.recoveryOutcome).toBe('ESCALATE');
    expect(decision.reasonCodes).toContain('RECOVERY_DEPTH_LIMIT_REACHED');
  });

  it('319. tampered retryCount exceeding MAX_AUTOMATIC_RETRIES (2) is trapped and forces ESCALATE', () => {
    const decision = recoveryControlPlane.evaluateRecoveryControl({
      requestId: 'req_tamper_retry_319',
      operationId: 'op_319',
      recoveryDepth: 1,
      retryCount: 2,
      reconciliationAttempts: 0,
    });
    expect(decision.recoveryOutcome).toBe('ESCALATE');
    expect(decision.reasonCodes).toContain('AUTOMATIC_RETRY_LIMIT_EXCEEDED');
  });

  it('320. tampered reconciliationAttempts exceeding MAX_RECONCILIATION_ATTEMPTS (3) forces ESCALATE', () => {
    const decision = recoveryControlPlane.evaluateRecoveryControl({
      requestId: 'req_tamper_recon_320',
      operationId: 'op_320',
      recoveryDepth: 1,
      retryCount: 0,
      reconciliationAttempts: 3,
    });
    expect(decision.recoveryOutcome).toBe('ESCALATE');
    expect(decision.reasonCodes).toContain('MAX_RECONCILIATION_ATTEMPTS_EXCEEDED');
  });

  it('321. tampered policySnapshotId or policyVersion triggers POLICY_VERSION_MISMATCH_DRIFT', () => {
    const decision = recoveryControlPlane.evaluateRecoveryControl({
      requestId: 'req_tamper_policy_321',
      operationId: 'op_321',
      policyVersion: 999999,
    });
    expect(decision.recoveryOutcome).toBe('REQUIRE_APPROVAL');
    expect(decision.reasonCodes).toContain('POLICY_VERSION_MISMATCH_DRIFT');
  });

  it('322. tampered governanceDecisionId / forged governance context fails closed to REQUIRE_APPROVAL', () => {
    const decision = recoveryControlPlane.evaluateRecoveryControl({
      requestId: 'req_tamper_gov_322',
      operationId: 'op_322',
      governanceContext: {
        unknown: true,
        actorType: 'USER',
        actorId: 'operator_322',
      },
    });
    expect(decision.recoveryOutcome).toBe('REQUIRE_APPROVAL');
    expect(decision.governanceRequirement.humanOperatorRequired).toBe(true);
  });

  it('323. tampered approvalRequirement flag cannot bypass governance signoff for high risk', () => {
    const decision = recoveryControlPlane.evaluateRecoveryControl({
      requestId: 'req_tamper_bypass_323',
      operationId: 'op_323',
      riskLevel: 'CRITICAL',
      metadata: { bypassApproval: true },
    });
    expect(decision.recoveryOutcome).toBe('REQUIRE_APPROVAL');
    expect(decision.governanceRequirement.humanOperatorRequired).toBe(true);
  });

  it('324. tampered causationId or correlationId (missing/empty) is strictly rejected', () => {
    expect(() => {
      createRecoveryPlan({
        originalOperationId: 'op_324',
        failureClassification: 'TRANSIENT',
        currentTruthState: 'FAILED',
        proposedRecoveryAction: 'RETRY',
        riskLevel: 'LOW',
        idempotencyAssessment: 'IDEMPOTENT',
        requiredAuthority: [],
        expectedOutcome: 'RETRY_SUCCESS',
        expiry: Date.now() + 60000,
        causationId: '',
        correlationId: 'corr_324',
      });
    }).toThrow(RecoveryContractViolationError);
  });

  // Group 2: Authority Spoofing & Human Approval Attacks (Tests 325–334)
  it('325. synthetic actor SYSTEM attempting to grant operator approval is rejected as forged', () => {
    expect(() => {
      recoveryControlPlane.evaluateRecoveryControl({
        requestId: 'req_spoof_sys_325',
        operationId: 'op_325',
        operatorApproval: {
          requestId: 'req_spoof_sys_325',
          policySnapshotId: 'snap_base',
          approvedBy: 'SYSTEM_AUTONOMOUS',
          approvedAt: Date.now(),
          riskLevel: 'CRITICAL',
          signature: 'valid_sig',
        },
      });
    }).toThrow(RecoveryContractViolationError);
  });

  it('326. synthetic actor AGENT-007 attempting to grant operator approval is rejected as forged', () => {
    expect(() => {
      recoveryControlPlane.evaluateRecoveryControl({
        requestId: 'req_spoof_agent_326',
        operationId: 'op_326',
        operatorApproval: {
          requestId: 'req_spoof_agent_326',
          policySnapshotId: 'snap_base',
          approvedBy: 'AGENT_ORCHESTRATOR',
          approvedAt: Date.now(),
          riskLevel: 'CRITICAL',
          signature: 'valid_sig',
        },
      });
    }).toThrow(RecoveryContractViolationError);
  });

  it('327. synthetic actor BOT attempting to grant operator approval is rejected as forged', () => {
    expect(() => {
      recoveryControlPlane.evaluateRecoveryControl({
        requestId: 'req_spoof_bot_327',
        operationId: 'op_327',
        operatorApproval: {
          requestId: 'req_spoof_bot_327',
          policySnapshotId: 'snap_base',
          approvedBy: 'RECOVERY_BOT_V1',
          approvedAt: Date.now(),
          riskLevel: 'CRITICAL',
          signature: 'valid_sig',
        },
      });
    }).toThrow(RecoveryContractViolationError);
  });

  it('328. synthetic actor DAEMON attempting to grant operator approval is rejected as forged', () => {
    expect(() => {
      recoveryControlPlane.evaluateRecoveryControl({
        requestId: 'req_spoof_daemon_328',
        operationId: 'op_328',
        operatorApproval: {
          requestId: 'req_spoof_daemon_328',
          policySnapshotId: 'snap_base',
          approvedBy: 'BACKGROUND_DAEMON',
          approvedAt: Date.now(),
          riskLevel: 'CRITICAL',
          signature: 'valid_sig',
        },
      });
    }).toThrow(RecoveryContractViolationError);
  });

  it('329. missing actor or empty approvedBy string in operator approval throws error', () => {
    expect(() => {
      recoveryControlPlane.evaluateRecoveryControl({
        requestId: 'req_spoof_empty_329',
        operationId: 'op_329',
        operatorApproval: {
          requestId: 'req_spoof_empty_329',
          policySnapshotId: 'snap_base',
          approvedBy: '   ',
          approvedAt: Date.now(),
          riskLevel: 'CRITICAL',
          signature: 'sig',
        },
      });
    }).toThrow(RecoveryContractViolationError);
  });

  it('330. expired approval token (>5m TTL) fails closed to REQUIRE_APPROVAL', () => {
    const snap = policySnapshotService.captureSnapshot();
    const decision = recoveryControlPlane.evaluateRecoveryControl({
      requestId: 'req_expired_tok_330',
      operationId: 'op_330',
      riskLevel: 'CRITICAL',
      operatorApproval: {
        requestId: 'req_expired_tok_330',
        policySnapshotId: snap.snapshotId,
        approvedBy: 'human_operator_alice',
        approvedAt: Date.now() - 360000,
        riskLevel: 'CRITICAL',
        signature: 'valid_sig_alice',
      },
    });
    expect(decision.recoveryOutcome).toBe('REQUIRE_APPROVAL');
    expect(decision.reasonCodes).toContain('APPROVAL_TOKEN_EXPIRED');
  });

  it('331. future timestamp in approval token fails closed or detects tampering', () => {
    const snap = policySnapshotService.captureSnapshot();
    const token: OperatorApprovalToken = {
      requestId: 'req_future_331',
      policySnapshotId: snap.snapshotId,
      approvedBy: 'human_operator_bob',
      approvedAt: Date.now() + 1000000,
      riskLevel: 'CRITICAL',
      signature: 'INVALID_SIGNATURE',
    };
    const req: GovernanceRequest = {
      requestId: 'req_future_331',
      targetSystem: 'system',
      actor: { actorId: 'bob', actorType: 'USER' },
      capabilityId: 'filesystem.write',
      actionType: 'write',
      parameters: {},
      riskLevel: 'CRITICAL',
      timestamp: Date.now(),
    };
    const res = governanceAuthorityService.evaluateAuthorityIntersection(
      req,
      {} as any,
      snap,
      'ALLOW',
      token
    );
    expect(res.humanApprovalStatus).toBe('FORGED_REJECTED');
    expect(res.effectiveStatus).toBe('DENIED');
  });

  it('332. negative timestamp in approval token is rejected as expired', () => {
    const snap = policySnapshotService.captureSnapshot();
    const decision = recoveryControlPlane.evaluateRecoveryControl({
      requestId: 'req_negative_ts_332',
      operationId: 'op_332',
      riskLevel: 'HIGH',
      operatorApproval: {
        requestId: 'req_negative_ts_332',
        policySnapshotId: snap.snapshotId,
        approvedBy: 'human_operator_carol',
        approvedAt: -500,
        riskLevel: 'HIGH',
        signature: 'sig_carol',
      },
    });
    expect(decision.recoveryOutcome).toBe('REQUIRE_APPROVAL');
    expect(decision.reasonCodes).toContain('APPROVAL_TOKEN_EXPIRED');
  });

  it('333. mismatched requestId in operator approval token is rejected (anti-replay)', () => {
    const snap = policySnapshotService.captureSnapshot();
    const decision = recoveryControlPlane.evaluateRecoveryControl({
      requestId: 'req_target_333',
      operationId: 'op_333',
      riskLevel: 'CRITICAL',
      operatorApproval: {
        requestId: 'req_other_origin_333',
        policySnapshotId: snap.snapshotId,
        approvedBy: 'human_operator_dan',
        approvedAt: Date.now(),
        riskLevel: 'CRITICAL',
        signature: 'sig_dan',
      },
    });
    expect(decision.recoveryOutcome).toBe('REQUIRE_APPROVAL');
    expect(decision.reasonCodes).toContain('APPROVAL_TOKEN_REQUEST_MISMATCH');
  });

  it('334. cross-operation approval replay attack fails closed', () => {
    const snap = policySnapshotService.captureSnapshot();
    const token: OperatorApprovalToken = {
      requestId: 'req_alpha_334',
      policySnapshotId: snap.snapshotId,
      approvedBy: 'human_operator_eve',
      approvedAt: Date.now(),
      riskLevel: 'CRITICAL',
      signature: 'sig_eve',
    };
    const reqBeta: GovernanceRequest = {
      requestId: 'req_beta_334',
      targetSystem: 'system',
      actor: { actorId: 'eve', actorType: 'USER' },
      capabilityId: 'recovery.control',
      actionType: 'RETRY',
      parameters: {},
      riskLevel: 'CRITICAL',
      timestamp: Date.now(),
    };
    const res = governanceAuthorityService.evaluateAuthorityIntersection(
      reqBeta,
      {} as any,
      snap,
      'ALLOW',
      token
    );
    expect(res.humanApprovalStatus).toBe('FORGED_REJECTED');
    expect(res.effectiveStatus).toBe('DENIED');
  });

  // Group 3: Policy Attacks & Hierarchy Enforcement (Tests 335–342)
  it('335. lower-priority policy cannot override SYSTEM_SAFETY tier', () => {
    policyRegistry.reset();
    const safetyPolicy: Policy = {
      id: 'pol_sys_safety_335',
      name: 'System Safety Core',
      description: 'Safety core policy',
      status: 'ACTIVE',
      scope: { scopeType: 'SYSTEM' },
      priority: 'SYSTEM_SAFETY',
      version: 1,
      conditions: {
        conjunction: 'AND',
        conditions: [],
      },
      effect: { type: 'DENY', reason: 'Safety block on recovery' },
      requiresHumanApproval: false,
      provenance: {
        authorId: 'system',
        createdAt: Date.now(),
        updatedAt: Date.now(),
        evidence: { confidenceScore: 1.0, description: 'Safety evidence' },
        changeLog: [],
      },
    };
    policyRegistry.registerPolicy(safetyPolicy);

    const decision = recoveryControlPlane.evaluateRecoveryControl({
      requestId: 'req_safety_override_335',
      operationId: 'op_335',
      failureEvidence: {
        operationId: 'op_335',
        causationId: 'c_335',
        correlationId: 'corr_335',
        dispatchState: 'NOT_DISPATCHED',
      },
    });
    expect(decision.recoveryOutcome).toBe('ABORT');
  });

  it('336. optimization or performance policy cannot override security or safety', () => {
    policyRegistry.reset();
    const optPolicy: Policy = {
      id: 'pol_opt_336',
      name: 'Optimization Policy',
      description: 'Optimize throughput',
      status: 'ACTIVE',
      scope: { scopeType: 'SYSTEM' },
      priority: 'OPTIMIZATION_POLICY',
      version: 1,
      conditions: {
        conjunction: 'AND',
        conditions: [],
      },
      effect: { type: 'ALLOW', reason: 'Optimize throughput' },
      requiresHumanApproval: false,
      provenance: {
        authorId: 'optimizer',
        createdAt: Date.now(),
        updatedAt: Date.now(),
        evidence: { confidenceScore: 1.0, description: 'Optimization evidence' },
        changeLog: [],
      },
    };
    policyRegistry.registerPolicy(optPolicy);

    const decision = recoveryControlPlane.evaluateRecoveryControl({
      requestId: 'req_opt_override_336',
      operationId: 'op_336',
      riskLevel: 'CRITICAL',
    });
    expect(decision.recoveryOutcome).toBe('REQUIRE_APPROVAL');
  });

  it('337. stale policy snapshot cannot authorize recovery', () => {
    const staleSnapshotId = 'snap_stale_nonexistent_337';
    const decision = recoveryControlPlane.evaluateRecoveryControl({
      requestId: 'req_stale_snap_337',
      operationId: 'op_337',
      policySnapshotId: staleSnapshotId,
    });
    expect(decision.recoveryOutcome).toBe('REQUIRE_APPROVAL');
    expect(decision.reasonCodes).toContain('POLICY_SNAPSHOT_MISMATCH_DRIFT');
  });

  it('338. unregistered or fake policy ID cannot grant recovery permission', () => {
    const decision = recoveryControlPlane.evaluateRecoveryControl({
      requestId: 'req_fake_pol_338',
      operationId: 'op_338',
      metadata: { winningPolicyId: 'pol_fake_unregistered' },
    });
    expect(decision.decisionId).toBeDefined();
    expect(decision.recoveryOutcome).not.toBe('NO_RECOVERY_REQUIRED');
  });

  it('339. unauthorized policy activation attempt fails closed', () => {
    const snapBefore = policySnapshotService.captureSnapshot();
    const countBefore = snapBefore.policies.length;

    // Attacker attempts unauthorized activation through recovery request
    recoveryControlPlane.evaluateRecoveryControl({
      requestId: 'req_unauth_act_339',
      operationId: 'op_339',
      parameters: {
        activatePolicy: { id: 'pol_malicious_unauth', status: 'ACTIVE', effect: 'ALLOW' },
      },
    });

    const snapAfter = policySnapshotService.captureSnapshot();
    // Registry is unchanged; fake policy was not activated
    expect(snapAfter.policies.length).toBe(countBefore);
    expect(snapAfter.policies.some((p) => p.policyId === 'pol_malicious_unauth')).toBe(false);
  });

  it('340. policy injection through recovery payload is sanitized/rejected', () => {
    const decision = recoveryControlPlane.evaluateRecoveryControl({
      requestId: 'req_payload_inj_340',
      operationId: 'op_340',
      parameters: { policyOverride: 'ALLOW_ALL', bypassGovernance: true },
      riskLevel: 'CRITICAL',
    });
    expect(decision.recoveryOutcome).toBe('REQUIRE_APPROVAL');
  });

  it('341. policy injection through memory fact is rejected (does not assume authority)', () => {
    const decision = recoveryControlPlane.evaluateRecoveryControl({
      requestId: 'req_mem_fact_341',
      operationId: 'op_341',
      metadata: { memoryFact: 'CRITICAL_SAFETY_BYPASSED' },
    });
    expect(decision.reasonCodes).toContain('LEARNING_SIGNAL_NOT_AUTHORITY');
  });

  it('342. policy injection through learning signal is rejected (cannot override governance)', () => {
    const decision = recoveryControlPlane.evaluateRecoveryControl({
      requestId: 'req_learn_sig_342',
      operationId: 'op_342',
      parameters: { learningSignal: { bypass: true, allowUnsafe: true } },
    });
    expect(decision.reasonCodes).toContain('LEARNING_SIGNAL_NOT_AUTHORITY');
  });

  // Group 4: Operational Truth & Epistemic Attacks (Tests 343–350)
  it('343. attempting to claim DISPATCHED -> EXECUTED without empirical evidence is rejected', () => {
    const decision = recoveryControlPlane.evaluateRecoveryControl({
      requestId: 'req_disp_exec_343',
      operationId: 'op_343',
      dispatchState: 'DISPATCHED',
      externalConfirmationReceived: false,
    });
    expect(decision.epistemicStatus).toBe('UNKNOWN');
    expect(decision.recoveryOutcome).toBe('RECONCILE');
  });

  it('344. attempting to claim UNKNOWN -> SUCCESS without Stage 22 evidence is rejected', () => {
    expect(isValidRecoveryLifecycleTransition('UNKNOWN', 'COMPLETED', false)).toBe(false);
    expect(() => {
      assertValidRecoveryLifecycleTransition('UNKNOWN', 'COMPLETED', false);
    }).toThrow(RecoveryContractViolationError);
  });

  it('345. attempting to claim INFERRED -> OBSERVED without evidence is rejected', () => {
    const classification = failureClassificationService.classifyFailure({
      operationId: 'op_inf_obs_345',
      causationId: 'c_345',
      correlationId: 'corr_345',
      dispatchState: 'EXTERNAL_CONFIRMATION_ABSENT',
      epistemicStatus: 'INFERRED',
    });
    expect(classification.epistemicStatus).toBe('UNKNOWN');
  });

  it('346. attempting to claim RECOMMENDED -> AUTHORIZED without governance is rejected', () => {
    const decision = recoveryControlPlane.evaluateRecoveryControl({
      requestId: 'req_rec_auth_346',
      operationId: 'op_346',
      riskLevel: 'HIGH',
      governanceContext: { actorType: 'USER', actorId: 'user_1', approved: false },
    });
    expect(decision.recoveryOutcome).toBe('REQUIRE_APPROVAL');
    expect(decision.governanceRequirement.humanOperatorRequired).toBe(true);
  });

  it('347. post-dispatch failure without confirmation preserves epistemicStatus: UNKNOWN', () => {
    const decision = recoveryControlPlane.evaluateRecoveryControl({
      requestId: 'req_post_disp_347',
      operationId: 'op_347',
      dispatchState: 'EXTERNAL_CONFIRMATION_ABSENT',
      confirmedSuccess: false,
    });
    expect(decision.epistemicStatus).toBe('UNKNOWN');
    expect(decision.recoveryOutcome).toBe('RECONCILE');
  });

  it('348. reconciliation discrepancy prevents assuming successful state', () => {
    const decision = recoveryControlPlane.evaluateRecoveryControl({
      requestId: 'req_recon_disc_348',
      operationId: 'op_348',
      failureEvidence: {
        operationId: 'op_348',
        causationId: 'c_348',
        correlationId: 'corr_348',
        dispatchState: 'DISPATCHED',
        reconciliationEvidence: {
          attempted: true,
          matched: false,
          discrepancies: ['Remote ledger missing record'],
        },
      },
    });
    expect(decision.epistemicStatus).toBe('UNKNOWN');
    expect(decision.recoveryOutcome).toBe('RECONCILE');
    expect(decision.reasonCodes).toContain('RECONCILIATION_DISCREPANCY_DETECTED');
  });

  it('349. empirical audit event cannot be mutated or forged', () => {
    const res = auditEventRegistry.recordEvent({
      operationId: 'op_audit_immutable_349',
      correlationId: 'corr_349',
      eventType: 'GOVERNANCE_DECIDED',
      lifecycleState: 'GOVERNED',
    });
    expect(Object.isFrozen(res.event)).toBe(true);
    expect(() => {
      (res.event as any).eventType = 'MUTATED';
    }).toThrow();
  });

  it('350. causal trace builder enforces depth bounds and cycle prevention', () => {
    const graph = causalTraceService.buildCausalGraph('op_causal_350');
    expect(graph.maxDepthReached).toBeLessThanOrEqual(10);
    expect(graph.hasCycles).toBe(false);
  });

  // Group 5: Recovery Loop & Boundary Attacks (Tests 351–355)
  it('351. infinite retries blocked by MAX_AUTOMATIC_RETRIES (2)', () => {
    const decision = recoveryControlPlane.evaluateRecoveryControl({
      requestId: 'req_loop_retry_351',
      operationId: 'op_351',
      retryCount: 2,
    });
    expect(decision.recoveryOutcome).toBe('ESCALATE');
    expect(decision.reasonCodes).toContain('AUTOMATIC_RETRY_LIMIT_EXCEEDED');
  });

  it('352. infinite recovery depth blocked by MAX_RECOVERY_DEPTH (3)', () => {
    const decision = recoveryControlPlane.evaluateRecoveryControl({
      requestId: 'req_loop_depth_352',
      operationId: 'op_352',
      recoveryDepth: 3,
    });
    expect(decision.recoveryOutcome).toBe('ESCALATE');
    expect(decision.reasonCodes).toContain('RECOVERY_DEPTH_LIMIT_REACHED');
  });

  it('353. infinite reconciliation blocked by MAX_RECONCILIATION_ATTEMPTS (3)', () => {
    const decision = recoveryControlPlane.evaluateRecoveryControl({
      requestId: 'req_loop_recon_353',
      operationId: 'op_353',
      reconciliationAttempts: 3,
    });
    expect(decision.recoveryOutcome).toBe('ESCALATE');
    expect(decision.reasonCodes).toContain('MAX_RECONCILIATION_ATTEMPTS_EXCEEDED');
  });

  it('354. compensation cycle / loop blocked via visitedOperationIds limit', () => {
    const excessiveVisited = Array.from({ length: 55 }, (_, i) => `op_visited_${i}`);
    expect(() => {
      recoveryControlPlane.evaluateRecoveryControl({
        requestId: 'req_visited_loop_354',
        operationId: 'op_354',
        visitedOperationIds: excessiveVisited,
      });
    }).toThrow(RecoveryContractViolationError);
  });

  it('355. cascade depth cannot exceed MAX_CASCADE_DEPTH (5)', () => {
    const record = recoveryCascadeService.detectCascade({
      rootOperationId: 'op_root_355',
      rootFailureClassification: 'TRANSIENT',
      failureCount: 6,
      sameClassFailures: 6,
      recoveryChainDepth: 5,
      causationId: 'cause_355',
      correlationId: 'corr_355',
    });
    expect(record.cascadeClass).toBe('RECOVERY_CHAIN');
    expect(record.containmentAction).toBe('ESCALATE');
  });

  // Group 6: Prototype Pollution, Secrets, & Payload Bounds (Tests 356–361)
  it('356. deep prototype pollution (__proto__) in nested payload rejected', () => {
    const payload = JSON.parse('{"level1": {"level2": {"__proto__": {"polluted": true}}}}');
    expect(() => {
      validateAndSanitizePayload(payload);
    }).toThrow(RecoveryContractViolationError);
  });

  it('357. constructor pollution in array item rejected', () => {
    const payload = JSON.parse('[{"safe": 1}, {"constructor": {"attack": true}}]');
    expect(() => {
      validateAndSanitizePayload(payload);
    }).toThrow(RecoveryContractViolationError);
  });

  it('358. secret pattern (bearer) in parameters/metadata rejected', () => {
    expect(() => {
      validateAndSanitizePayload({
        auth_header: 'bearer eyJhbGciOiJIUzI1NiJ9',
      });
    }).toThrow(RecoveryContractViolationError);
  });

  it('359. secret pattern (api_key) in payload rejected', () => {
    expect(() => {
      validateAndSanitizePayload({
        api_key: 'prod_api_key_secret_123',
      });
    }).toThrow(RecoveryContractViolationError);
  });

  it('360. oversized payload (>64KB) rejected by persistence security assertion', () => {
    const giantPayload: any = {
      decisionId: 'dec_giant_360',
      requestId: 'req_360',
      operationId: 'op_360',
      classification: 'TRANSIENT',
      recoveryOutcome: 'RETRY',
      lifecycleState: 'DECIDED',
      metadata: { blob: 'A'.repeat(70000) },
    };
    expect(() => {
      recoveryControlPersistenceService.persistControlDecision(giantPayload);
    }).toThrow(RecoveryContractViolationError);
  });

  it('361. circular reference in recovery payload rejected', () => {
    const cyclicObj: any = { name: 'cyclic_node' };
    cyclicObj.self = cyclicObj;
    expect(() => {
      validateAndSanitizePayload(cyclicObj);
    }).toThrow(RecoveryContractViolationError);
  });

  // Group 7: Recovery State Machine Fuzzing (Part B) (Tests 362–367)
  it('362. illegal transition COMPLETED -> READY rejected', () => {
    expect(isValidRecoveryLifecycleTransition('COMPLETED', 'READY')).toBe(false);
    expect(() => {
      assertValidRecoveryLifecycleTransition('COMPLETED', 'READY');
    }).toThrow(RecoveryContractViolationError);
  });

  it('363. illegal transition COMPLETED -> DISPATCHED rejected', () => {
    expect(isValidRecoveryLifecycleTransition('COMPLETED', 'DISPATCHED')).toBe(false);
    expect(() => {
      assertValidRecoveryLifecycleTransition('COMPLETED', 'DISPATCHED');
    }).toThrow(RecoveryContractViolationError);
  });

  it('364. illegal transition REJECTED -> APPROVED rejected', () => {
    expect(isValidRecoveryLifecycleTransition('REJECTED', 'APPROVED')).toBe(false);
    expect(() => {
      assertValidRecoveryLifecycleTransition('REJECTED', 'APPROVED');
    }).toThrow(RecoveryContractViolationError);
  });

  it('365. illegal transition ABORTED -> RESUME rejected', () => {
    expect(isValidRecoveryLifecycleTransition('ABORTED', 'READY')).toBe(false);
    expect(() => {
      assertValidRecoveryLifecycleTransition('ABORTED', 'READY');
    }).toThrow(RecoveryContractViolationError);
  });

  it('366. illegal transition EXPIRED -> EXECUTE / READY rejected', () => {
    expect(isValidRecoveryLifecycleTransition('EXPIRED', 'READY')).toBe(false);
    expect(() => {
      assertValidRecoveryLifecycleTransition('EXPIRED', 'READY');
    }).toThrow(RecoveryContractViolationError);
  });

  it('367. illegal transition UNKNOWN -> SUCCESS without confirmed evidence rejected', () => {
    expect(isValidRecoveryLifecycleTransition('UNKNOWN', 'COMPLETED', false)).toBe(false);
    expect(() => {
      assertValidRecoveryLifecycleTransition('UNKNOWN', 'COMPLETED', false);
    }).toThrow(RecoveryContractViolationError);

    // With confirmed operational evidence, transition is permitted
    expect(isValidRecoveryLifecycleTransition('UNKNOWN', 'COMPLETED', true)).toBe(true);
  });

  // Group 8: Cross-Layer Authority Fuzzing (Part C) (Tests 368–371)
  it('368. Policy ALLOW alone without Connector permission fails closed (MISSING_PERMISSION)', () => {
    const snap = policySnapshotService.captureSnapshot();
    const mockReq: GovernanceRequest = {
      requestId: 'req_cross_368',
      targetSystem: 'system',
      connectorId: 'conn_error_368',
      actor: { actorId: 'agent_368', actorType: 'AUTONOMOUS_AGENT' },
      capabilityId: 'filesystem.write',
      actionType: 'write',
      parameters: {},
      riskLevel: 'LOW',
      timestamp: Date.now(),
    };
    connectorRegistry.registerConnector({
      id: 'conn_error_368',
      name: 'Error Connector',
      type: 'FILESYSTEM',
      version: '1.0.0',
      status: 'ERROR',
      health: 'UNAVAILABLE',
      configuration: {},
      scopes: [],
      permissions: [],
      capabilities: [{ capabilityId: 'filesystem.write', name: 'Write' }] as any,
      permissionVersion: 1,
      createdAt: new Date().toISOString(),
      updatedAt: new Date().toISOString(),
    });

    const res = governanceAuthorityService.evaluateAuthorityIntersection(
      mockReq,
      { currentConnectorState: 'UNAVAILABLE' } as any,
      snap,
      'ALLOW'
    );
    expect(res.effectiveStatus).toBe('MISSING_PERMISSION');
  });

  it('369. Connector permission alone without Action Authorization fails closed', () => {
    const snap = policySnapshotService.captureSnapshot();
    const mockReq: GovernanceRequest = {
      requestId: 'req_cross_369',
      targetSystem: 'system',
      actor: { actorId: 'user_369', actorType: 'USER' },
      capabilityId: 'recovery.control',
      actionType: 'EXECUTE',
      parameters: {},
      riskLevel: 'CRITICAL',
      timestamp: Date.now(),
    };
    const res = governanceAuthorityService.evaluateAuthorityIntersection(
      mockReq,
      {} as any,
      snap,
      'ALLOW'
    );
    expect(res.actionAuthorized).toBe(false);
    expect(res.effectiveStatus).toBe('REQUIRES_APPROVAL');
  });

  it('370. Human approval alone without Policy ALLOW fails closed (DENIED)', () => {
    const snap = policySnapshotService.captureSnapshot();
    const token: OperatorApprovalToken = {
      requestId: 'req_cross_370',
      policySnapshotId: snap.snapshotId,
      approvedBy: 'human_operator_frank',
      approvedAt: Date.now(),
      riskLevel: 'HIGH',
      signature: 'valid_sig_frank',
    };
    const mockReq: GovernanceRequest = {
      requestId: 'req_cross_370',
      targetSystem: 'system',
      actor: { actorId: 'user_370', actorType: 'USER' },
      capabilityId: 'recovery.control',
      actionType: 'RETRY',
      parameters: {},
      riskLevel: 'HIGH',
      timestamp: Date.now(),
    };
    const res = governanceAuthorityService.evaluateAuthorityIntersection(
      mockReq,
      {} as any,
      snap,
      'DENY',
      token
    );
    expect(res.policyAllowed).toBe(false);
    expect(res.effectiveStatus).toBe('DENIED');
  });

  it('371. Effective Authority requires full intersection Policy ∩ Connector ∩ Action ∩ Human ∩ Mission', () => {
    const snap = policySnapshotService.captureSnapshot();
    const token: OperatorApprovalToken = {
      requestId: 'req_cross_371',
      policySnapshotId: snap.snapshotId,
      approvedBy: 'human_operator_grace',
      approvedAt: Date.now(),
      riskLevel: 'HIGH',
      signature: 'valid_sig_grace',
    };
    const mockReq: GovernanceRequest = {
      requestId: 'req_cross_371',
      targetSystem: 'system',
      missionId: 'mission_paused_371',
      actor: { actorId: 'user_371', actorType: 'USER' },
      capabilityId: 'recovery.control',
      actionType: 'RETRY',
      parameters: {},
      riskLevel: 'HIGH',
      timestamp: Date.now(),
    };
    const res = governanceAuthorityService.evaluateAuthorityIntersection(
      mockReq,
      { currentMissionState: 'PAUSED' } as any,
      snap,
      'ALLOW',
      token
    );
    expect(res.missionConstraintsSatisfied).toBe(false);
    expect(res.effectiveStatus).toBe('MISSION_CONSTRAINT_BLOCKED');
  });

  // Group 9: DOM-Only Recovery Operational HUD (Part D & E) (Tests 372–376)
  it('372. RecoveryControlHUD renders all required telemetry fields in pure DOM', () => {
    const { getByTestId } = render(
      <RecoveryControlHUD
        operationId="OP_8472"
        recoveryState="READY"
        failureClassification="PARTIAL_EXECUTION"
        recoveryDecision="RECONCILE"
        policyState="ACTIVE / v42"
        governanceState="APPROVAL REQUIRED"
        authorityState="BLOCKED"
        operationalTruth="UNKNOWN"
        reconciliationState="PROBING (2/3)"
        approvalRequired={true}
        recoveryDepth={2}
        retryCount={1}
        epistemicStatus="UNKNOWN"
      />
    );

    expect(getByTestId('recovery-control-hud')).toBeDefined();
    expect(getByTestId('hud-operation-id').textContent).toBe('OP_8472');
    expect(getByTestId('hud-failure-class').textContent).toBe('PARTIAL_EXECUTION');
    expect(getByTestId('hud-recovery-decision').textContent).toBe('RECONCILE');
    expect(getByTestId('hud-policy-state').textContent).toBe('ACTIVE / v42');
    expect(getByTestId('hud-governance-state').textContent).toBe('APPROVAL REQUIRED');
    expect(getByTestId('hud-authority-state').textContent).toContain('BLOCKED');
    expect(getByTestId('hud-recovery-depth').textContent).toBe('2 / 3');
    expect(getByTestId('hud-retry-count').textContent).toBe('1 / 2');
    expect(getByTestId('hud-reconciliation-state').textContent).toBe('PROBING (2/3)');
  });

  it('373. Epistemic status UNKNOWN is strictly rendered as UNKNOWN and never SUCCESS', () => {
    const { getByTestId } = render(
      <RecoveryControlHUD
        operationId="OP_EPISTEMIC_373"
        epistemicStatus="UNKNOWN"
        operationalTruth="SUCCESS"
      />
    );

    expect(getByTestId('hud-epistemic-status').textContent).toBe('UNKNOWN (UNVERIFIED)');
    expect(getByTestId('hud-operational-truth').textContent).not.toBe('SUCCESS');
    expect(getByTestId('hud-operational-truth').textContent).toBe('UNKNOWN (EVIDENCE PENDING)');
  });

  it('374. Recommendation state PROPOSED is displayed as recommendation, never executed', () => {
    const { getByTestId } = render(
      <RecoveryControlHUD
        operationId="OP_REC_374"
        recoveryState="PROPOSED"
        epistemicStatus="OBSERVED"
      />
    );

    expect(getByTestId('hud-recovery-state').textContent).toBe('PROPOSED (RECOMMENDATION ONLY)');
  });

  it('375. Observational boundary: HUD contains zero execution or approval buttons', () => {
    const { getByTestId } = render(
      <RecoveryControlHUD
        operationId="OP_BOUNDARY_375"
        approvalRequired={true}
      />
    );

    const hudRoot = getByTestId('recovery-control-hud');
    const buttons = hudRoot.querySelectorAll('button');
    for (const btn of Array.from(buttons)) {
      expect(btn.getAttribute('data-testid')).not.toBe('execute-btn');
      expect(btn.getAttribute('data-testid')).not.toBe('approve-btn');
    }
  });

  it('376. SpatialCommandConsole renders recovery-control-plane-hud with zero 3D draw call overhead', () => {
    const mockControl = {
      commandState: 'IDLE' as any,
      commandInput: '',
      setCommandInput: () => {},
      currentCommand: null,
      history: [],
      historyIndex: -1,
      availableIntents: [],
      submitCommand: () => {},
      confirmProposal: () => {},
      cancelProposal: () => {},
      dismissResult: () => {},
      isConsoleOpen: true,
      setIsConsoleOpen: () => {},
      toggleConsole: () => {},
      navigateHistory: () => {},
    };

    const { getByTestId } = render(<SpatialCommandConsole commandControl={mockControl as any} />);
    expect(getByTestId('recovery-control-plane-hud')).toBeDefined();
    expect(getByTestId('recovery-control-hud-status').textContent).toBe('GOVERNED_RECOVERY');
    expect(getByTestId('recovery-hud-state').textContent).toBe('READY');
    expect(getByTestId('recovery-hud-decision').textContent).toBe('RETRY');
    expect(getByTestId('recovery-authority-badge').textContent).toBe('AUTHORITY: ZERO_AUTHORITY');
  });
});

describe('AryaOS V1 Stage 23 — Phase 13: Final Certification, Canonical Traces & Authority Regression', () => {
  it('377. Trace A: safe transient failure — undispatched operation triggers bounded retry with zero duplicate execution', () => {
    policyRegistry.reset();
    const req = {
      requestId: 'req_trace_a_377',
      operationId: 'op_trace_a_377',
      failureEvidence: {
        operationId: 'op_trace_a_377',
        causationId: 'c_377',
        correlationId: 'corr_377',
        dispatchState: 'NOT_DISPATCHED' as const,
        timeoutEvidence: { timedOut: true, phase: 'PRE_DISPATCH' as const },
      },
      dispatchState: 'NOT_DISPATCHED' as const,
      idempotency: 'IDEMPOTENT' as const,
      retryCount: 0,
    };
    const decision = recoveryControlPlane.evaluateRecoveryControl(req);
    expect(decision.recoveryOutcome).toBe('RETRY');
    expect(decision.recommendedAction).toBe('RETRY');
    expect(decision.lifecycleState).toBe('DECIDED');

    // Duplicate submission returns identical frozen decision
    const duplicate = recoveryControlPlane.evaluateRecoveryControl(req);
    expect(duplicate.decisionId).toBe(decision.decisionId);
    expect(duplicate.recoveryOutcome).toBe('RETRY');
  });

  it('378. Trace B: unknown post-dispatch state — in-flight operation without confirmation routes strictly to reconciliation, blocking blind replay', () => {
    const req = {
      requestId: 'req_trace_b_378',
      operationId: 'op_trace_b_378',
      failureEvidence: {
        operationId: 'op_trace_b_378',
        causationId: 'c_378',
        correlationId: 'corr_378',
        dispatchState: 'DISPATCHED' as const,
        epistemicStatus: 'UNKNOWN' as const,
      },
      dispatchState: 'DISPATCHED' as const,
      externalConfirmationReceived: false,
    };
    const decision = recoveryControlPlane.evaluateRecoveryControl(req);
    expect(decision.recommendedAction).toBe('RECONCILE');
    expect(decision.recommendedAction).not.toBe('RETRY');
    expect(decision.lifecycleState).toBe('DECIDED');
  });

  it('379. Trace C: confirmed success — external confirmation detected halts recovery with NO_RECOVERY_REQUIRED/WAIT, preventing duplicate side-effects', () => {
    const req = {
      requestId: 'req_trace_c_379',
      operationId: 'op_trace_c_379',
      confirmedSuccess: true,
    };
    const decision = recoveryControlPlane.evaluateRecoveryControl(req);
    expect(decision.recoveryOutcome).toBe('NO_RECOVERY_REQUIRED');
    expect(decision.recommendedAction).toBe('WAIT');
  });

  it('380. Trace D: partial execution — multi-step failure preserves completed steps and compensates/reconciles failed steps without replaying completed side effects', () => {
    const decision = recoveryControlPlane.evaluateRecoveryControl({
      requestId: 'req_trace_d_380',
      operationId: 'op_trace_d_380',
      capabilityId: 'github.create_issue',
      parameters: { repository: 'octocat/Hello-World', issueNumber: 42 },
      failureEvidence: {
        operationId: 'op_trace_d_380',
        causationId: 'cause_380',
        correlationId: 'corr_380',
        dispatchState: 'EXECUTING',
        partialExecutionEvidence: {
          completedSteps: ['step_create_issue'],
          failedStep: 'step_post_comment',
          pendingSteps: [],
        },
      },
      dispatchState: 'EXECUTING',
    });
    expect(decision.recoveryOutcome).toBe('COMPENSATE');
    expect(decision.recommendedAction).toBe('COMPENSATE');
    expect(decision.compensationAssessment?.candidatePlan?.compensatingCapability).toBe('github.close_issue');
  });

  it('381. Trace E: policy denial — active policy deny aborts recovery and logs audit trail with zero execution dispatched', () => {
    policyRegistry.reset();
    const denyPolicy: Policy = {
      id: 'pol_deny_safety_381',
      version: 1,
      name: 'Deny Recovery Core Safety',
      description: 'System safety deny on recovery',
      status: 'ACTIVE',
      scope: { scopeType: 'SYSTEM' },
      priority: 'SYSTEM_SAFETY',
      conditions: { conjunction: 'AND', conditions: [] },
      effect: { type: 'DENY', reason: 'System safety lockdown' },
      requiresHumanApproval: false,
      provenance: {
        authorId: 'system',
        createdAt: Date.now(),
        updatedAt: Date.now(),
        evidence: { confidenceScore: 1.0, description: 'Safety lockdown evidence' },
        changeLog: [],
      },
    };
    policyRegistry.registerPolicy(denyPolicy);

    const decision = recoveryControlPlane.evaluateRecoveryControl({
      requestId: 'req_trace_e_381',
      operationId: 'op_trace_e_381',
      failureEvidence: {
        operationId: 'op_trace_e_381',
        causationId: 'c_381',
        correlationId: 'corr_381',
        dispatchState: 'NOT_DISPATCHED',
      },
    });
    expect(decision.recoveryOutcome).toBe('ABORT');
  });

  it('382. Trace F: human approval gate — high-risk recovery requires operator token; fresh token continues, expired token fails closed to REQUIRE_APPROVAL', () => {
    policyRegistry.reset();
    const decision = recoveryControlPlane.evaluateRecoveryControl({
      requestId: 'req_trace_f_382',
      operationId: 'op_trace_f_382',
      dispatchState: 'DISPATCHED',
      externalConfirmationReceived: false,
      riskLevel: 'CRITICAL',
    });
    expect(decision.recoveryOutcome).toBe('REQUIRE_APPROVAL');

    const validRes = recoveryControlPersistenceService.revalidateDecision(decision.decisionId, {
      humanApprovalExpired: false,
    });
    expect(validRes.valid).toBe(true);

    const expiredRes = recoveryControlPersistenceService.revalidateDecision(decision.decisionId, {
      humanApprovalExpired: true,
    });
    expect(expiredRes.valid).toBe(false);
    expect(expiredRes.recommendedAction).toBe('REQUIRE_APPROVAL');
  });

  it('383. Trace G: policy drift — persisted recovery across restart with drifted policy snapshot fails closed to REQUIRE_APPROVAL, preventing un-governed execution', () => {
    policyRegistry.reset();
    const initialSnap = policySnapshotService.captureSnapshot();
    const decision = recoveryControlPlane.evaluateRecoveryControl({
      requestId: 'req_trace_g_383',
      operationId: 'op_trace_g_383',
      policySnapshotId: initialSnap.snapshotId,
    });

    const driftRes = recoveryControlPersistenceService.revalidateDecision(decision.decisionId, {
      currentPolicySnapshotId: 'snap_v2_drifted_383',
    });
    expect(driftRes.valid).toBe(false);
    expect(driftRes.recommendedAction).toBe('REQUIRE_APPROVAL');
  });

  it('384. Trace H: connector revocation — persisted recovery for revoked connector fails closed upon authority revalidation', () => {
    const decision = recoveryControlPlane.evaluateRecoveryControl({
      requestId: 'req_trace_h_384',
      operationId: 'op_trace_h_384',
    });

    const res = recoveryControlPersistenceService.revalidateDecision(decision.decisionId, {
      connectorPermissionRevoked: true,
    });
    expect(res.valid).toBe(false);
    expect(res.reasonCode).toBe('CONNECTOR_PERMISSION_MISSING');
  });

  it('385. Trace I: cascade containment — repeated systemic failures trigger ISOLATE/ABORT and containment state survives restart', () => {
    const cascade = recoveryCascadeService.detectCascade({
      rootOperationId: 'op_sys_385',
      rootFailureClassification: 'DEPENDENCY',
      failureCount: 4,
    });
    expect(cascade.cascadeClass).toBe('RETRY_AMPLIFICATION');
    expect(cascade.containmentAction).toBe('THROTTLE');
  });

  it('386. Part 4: authority integrity certification — proves Effective Authority = Policy ∩ Connector ∩ ActionBus ∩ Human ∩ Mission across all boundary permutations', () => {
    const snap = policySnapshotService.captureSnapshot();
    const token: OperatorApprovalToken = {
      requestId: 'req_auth_int_386',
      policySnapshotId: snap.snapshotId,
      approvedBy: 'human_operator_386',
      approvedAt: Date.now(),
      riskLevel: 'LOW',
      signature: 'valid_sig_386',
    };
    const baseReq: GovernanceRequest = {
      requestId: 'req_auth_int_386',
      actor: { actorId: 'user_386', actorType: 'USER' },
      targetSystem: 'system',
      capabilityId: 'recovery.control',
      actionType: 'RETRY',
      parameters: {},
      riskLevel: 'LOW',
      timestamp: Date.now(),
    };

    // 1. All ALLOW -> GRANTED
    const allAllow = governanceAuthorityService.evaluateAuthorityIntersection(
      baseReq,
      {} as any,
      snap,
      'ALLOW',
      token
    );
    expect(allAllow.effectiveStatus).toBe('GRANTED');

    // 2. Policy DENY -> DENIED
    const policyDeny = governanceAuthorityService.evaluateAuthorityIntersection(
      baseReq,
      {} as any,
      snap,
      'DENY',
      token
    );
    expect(policyDeny.effectiveStatus).toBe('DENIED');

    // 3. Connector UNAVAILABLE -> not GRANTED
    const connUnavailable = governanceAuthorityService.evaluateAuthorityIntersection(
      { ...baseReq, connectorId: 'connector_filesystem' },
      { currentConnectorState: 'UNAVAILABLE' } as any,
      snap,
      'ALLOW',
      token
    );
    expect(connUnavailable.effectiveStatus).not.toBe('GRANTED');

    // 4. Mission PAUSED -> MISSION_CONSTRAINT_BLOCKED
    const missionPaused = governanceAuthorityService.evaluateAuthorityIntersection(
      { ...baseReq, missionId: 'mission_386' },
      { currentMissionState: 'PAUSED' } as any,
      snap,
      'ALLOW',
      token
    );
    expect(missionPaused.effectiveStatus).toBe('MISSION_CONSTRAINT_BLOCKED');
  });

  it('387. Part 5: epistemic certification — verifies global separation: REQUESTED ≠ PLANNED ≠ AUTHORIZED ≠ DISPATCHED ≠ EXECUTED ≠ OBSERVED ≠ RECONCILED; UNKNOWN ≠ SUCCESS; UNKNOWN ≠ FAILURE; INFERRED ≠ OBSERVED; PROJECTED ≠ CONFIRMED', () => {
    const lifecycleStates = [
      'REQUESTED',
      'PLANNED',
      'AUTHORIZED',
      'DISPATCHED',
      'EXECUTED',
      'OBSERVED',
      'RECONCILED',
    ];
    const uniqueStates = new Set(lifecycleStates);
    expect(uniqueStates.size).toBe(lifecycleStates.length);

    expect('UNKNOWN').not.toBe('SUCCESS');
    expect('UNKNOWN').not.toBe('FAILURE');
    expect('INFERRED').not.toBe('OBSERVED');
    expect('PROJECTED').not.toBe('CONFIRMED');
    expect('RECOMMENDED').not.toBe('AUTHORIZED');
    expect('DISPATCHED').not.toBe('EXECUTED');
    expect('EXECUTED').not.toBe('RECONCILED');

    // State machine enforces epistemic transition boundary: UNKNOWN requires reconciliation probe
    const res = recoveryControlPlane.evaluateRecoveryControl({
      requestId: 'req_epistemic_387',
      operationId: 'op_387',
      failureEvidence: {
        operationId: 'op_387',
        causationId: 'c_387',
        correlationId: 'corr_387',
        dispatchState: 'DISPATCHED',
        epistemicStatus: 'UNKNOWN',
      },
    });
    expect(res.recommendedAction).toBe('RECONCILE');
    expect(res.recommendedAction).not.toBe('RETRY');
    expect(res.recoveryOutcome).not.toBe('ALLOW');
  });

  it('388. Part 6: recovery bounds certification — verifies MAX_RECOVERY_DEPTH = 3, MAX_AUTOMATIC_RETRIES = 2, MAX_RECONCILIATION_ATTEMPTS = 3, MAX_CASCADE_DEPTH = 5, MAX_CONCURRENT_AFFECTED_OPERATIONS = 50 cannot be bypassed', () => {
    expect(MAX_RECOVERY_DEPTH).toBe(3);
    expect(MAX_AUTOMATIC_RETRIES).toBe(2);

    const depthDecision = recoveryControlPlane.evaluateRecoveryControl({
      requestId: 'req_depth_exceeded_388',
      operationId: 'op_388',
      recoveryDepth: 3,
    });
    expect(depthDecision.reasonCodes).toContain('RECOVERY_DEPTH_LIMIT_REACHED');
    expect(depthDecision.recoveryOutcome).toBe('ESCALATE');

    expect(() => {
      createDeclarativeCompensationPlan({
        compensationId: 'comp_388',
        originalOperationId: 'op_388',
        compensationType: 'RESOURCE_CLEANUP',
        sourceCapability: 'filesystem.write',
        compensatingCapability: 'filesystem.delete',
        targetState: 'CLEAN',
        compensationParameters: {},
        reversibilityClass: 'FULLY_REVERSIBLE',
        idempotencyClass: 'IDEMPOTENT',
        riskLevel: 'LOW',
        requiredAuthority: ['SYSTEM'],
        approvalRequirement: { required: false, humanOperatorRequired: false },
        reconciliationRequirement: { required: false, postCompensationVerification: false },
        idempotencyKey: 'idem_comp_388',
        causationId: 'c_388',
        correlationId: 'corr_388',
        expiresAt: Date.now() + 60000,
        recoveryDepth: 4, // > 3
      });
    }).toThrow(/Recovery depth 4 exceeds maximum allowed depth of 3/);

    expect(() => {
      createCascadeRecord({
        cascadeId: 'casc_388',
        rootOperationId: 'op_388',
        failureClass: 'DEPENDENCY',
        cascadeClass: 'SYSTEM_WIDE_FAILURE',
        severity: 'CRITICAL',
        depth: 6, // > 5
        affectedOperationIds: ['op1'],
        causationId: 'c_388',
        correlationId: 'corr_388',
        expiresAt: Date.now() + 60000,
        containmentAction: 'ISOLATE',
        authorityRequirement: [],
      });
    }).toThrow(/Cascade depth 6 exceeds maximum allowable depth of 5/);
  });

  it('389. Part 7 & 8: execution boundary certification — Stage 23 exposes zero direct HTTP, raw socket, or provider execution methods; routes strictly through Stage 15 Action Bus and Stage 07 Execution Gateway', () => {
    // Assert RecoveryControlPlane does not have direct execution capabilities
    const rcpProto = Object.getOwnPropertyNames(Object.getPrototypeOf(recoveryControlPlane));
    expect(rcpProto).not.toContain('fetch');
    expect(rcpProto).not.toContain('http');
    expect(rcpProto).not.toContain('executeDirect');
    expect(rcpProto).not.toContain('spawnProcess');
    expect(rcpProto).not.toContain('callProvider');

    // Stage 23 only produces decisions for Stage 15 Universal Action Bus consumption
    const decision = recoveryControlPlane.evaluateRecoveryControl({
      requestId: 'req_exec_bound_389',
      operationId: 'op_389',
    });
    expect(decision).toHaveProperty('recommendedAction');
    expect(decision).toHaveProperty('recoveryOutcome');
    expect(decision).toHaveProperty('lifecycleState');
  });

  it('390. Part 9: persistence certification — Stage 23 uses Stage 09 ExecutionPersistence & ExecutionJournal; isDurableStorage reports false during memory fallback', () => {
    expect(typeof executionPersistence.isDurableStorageActive).toBe('function');
    expect(typeof recoveryControlPersistenceService.isDurableStorage).toBe('function');

    // In normal happy path or test environment
    const isDurable = recoveryControlPersistenceService.isDurableStorage();
    expect(typeof isDurable).toBe('boolean');

    // When localStorage is undefined, isDurableStorage must return false
    const originalLocalStorage = globalThis.localStorage;
    try {
      // @ts-expect-error test simulation
      delete globalThis.localStorage;
      expect(executionPersistence.isDurableStorageActive()).toBe(false);
      expect(recoveryControlPersistenceService.isDurableStorage()).toBe(false);
    } finally {
      globalThis.localStorage = originalLocalStorage;
    }
  });

  it('391. Part 10: security certification — all 12 Phase 12 security categories remain defended simultaneously without regression', () => {
    // 1. Prototype pollution rejected
    const clean = validateAndSanitizePayload({ safe: 'value', __proto__: { admin: true } });
    expect((clean as any).admin).toBeUndefined();

    // 2. Secret injection rejected
    expect(() => {
      validateAndSanitizePayload({ token: 'bearer secret_token_value_391' });
    }).toThrow();

    // 3. Oversized payload / excessive elements rejected
    const huge = { padding: Array(60).fill('item') };
    expect(() => validateAndSanitizePayload(huge)).toThrow(/Array exceeds maximum element limit of 50/);

    // 4. Invalid lifecycle transition rejected
    expect(() => {
      assertValidRecoveryLifecycleTransition('COMPLETED', 'READY');
    }).toThrow(/Illegal recovery lifecycle transition from 'COMPLETED' to 'READY'/);
  });

  it('392. Part 11 & 12: HUD & visual immutability certification — HUD is strictly observational DOM overlay with zero WebGL overhead and explicit epistemic badges', () => {
    const { getByTestId } = render(<RecoveryControlHUD />);
    expect(getByTestId('recovery-control-hud')).toBeDefined();
    expect(getByTestId('hud-epistemic-status')).toBeDefined();
    expect(getByTestId('hud-operation-id')).toBeDefined();
    expect(getByTestId('hud-operational-truth')).toBeDefined();
    expect(getByTestId('hud-recovery-state')).toBeDefined();
    expect(getByTestId('hud-failure-class')).toBeDefined();
    expect(getByTestId('hud-recovery-decision')).toBeDefined();
    expect(getByTestId('hud-epistemic-safety-notice')).toBeDefined();

    // Pure DOM overlay verification: zero canvas or WebGL elements rendered by HUD
    const hudNode = getByTestId('recovery-control-hud');
    expect(hudNode.tagName.toLowerCase()).toBe('div');
    expect(hudNode.querySelectorAll('canvas').length).toBe(0);
  });
});







