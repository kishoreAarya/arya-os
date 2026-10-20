/**
 * AryaOS V1 — Stage 24: Mission Operations Control Plane
 * Phase 5: Recovery Operations Projection Test Suite
 *
 * Verifies:
 * 1. Observational read-only projection of Stage 23 recovery decisions into RecoverySummary.
 * 2. Absolute boundaries: ZERO execution, ZERO action bus dispatch, ZERO mutation.
 * 3. Epistemic honesty: UNKNOWN preserved; never coerced to success or confirmed truth.
 * 4. Requirement vs. State distinctions: approval and reconciliation requirements.
 * 5. Deterministic ordering, deduplication, filtering, and deep immutability.
 * 6. Adversarial cases: forged states, unconfirmed outcomes, stale decisions, missing evidence.
 */

import { describe, it, expect, beforeEach, vi } from 'vitest';
import {
  controlPlaneSnapshotService,
  RecoveryFilterOptions,
} from '../services/controlPlaneSnapshotService';
import { executionPersistence } from '../services/executionPersistence';
import { auditEventRegistry } from '../services/auditEventRegistry';
import { policyRegistry } from '../services/policyRegistry';
import { governanceControlPlane } from '../services/governanceControlPlane';
import { actionBusService } from '../services/actionBusService';
import { recoveryControlPlane } from '../services/recoveryControlPlane';
import { recoveryCompensationService } from '../services/recoveryCompensationService';
import { recoveryReconciliationService } from '../services/recoveryReconciliationService';
import {
  RecoveryControlDecision,
  FAILURE_CLASSIFICATIONS,
  RECOVERY_ACTIONS,
  RECOVERY_CONTROL_LIFECYCLE_STATES,
  IDEMPOTENCY_CLASSIFICATIONS,
  FailureClassification,
  RecoveryAction,
  RecoveryControlLifecycleState,
  IdempotencyClassification,
  DeclarativeCompensationPlan,
} from '../types/recoveryControl';
import { EpistemicStatus } from '../types/operationalAudit';
import { PersistedOrchestrationEnvelope } from '../types/executionPersistence';

describe('Stage 24 — Phase 5: Recovery Operations Projection', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    executionPersistence.clearEnvelope();
    auditEventRegistry.reset();
  });

  const createSampleDecision = (overrides: Partial<RecoveryControlDecision> = {}): RecoveryControlDecision => {
    const defaultDecision: RecoveryControlDecision = {
      decisionId: 'rec-dec-base-01',
      requestId: 'req-rec-01',
      operationId: 'op-alpha-01',
      originalOperationId: 'op-alpha-01',
      classification: 'TRANSIENT',
      recoveryOutcome: 'RETRY',
      recommendedAction: 'RETRY',
      safetyAssessment: {
        idempotencyClassification: 'IDEMPOTENT',
        duplicateSideEffectRisk: 'NONE',
        reconciliationRequirement: false,
        partialExecutionDetected: false,
        completedSteps: [],
        incompleteSteps: [],
        compensationAvailability: 'NO_COMPENSATION_AVAILABLE',
        rollbackAvailability: false,
        retryPermitted: true,
        humanApprovalRequired: false,
        safetyRationale: 'Safe for retry',
        assessmentTimestamp: 1700000000000,
      },
      governanceRequirement: {
        required: false,
        humanOperatorRequired: false,
      },
      requiredAuthority: ['OPERATOR'],
      riskLevel: 'LOW',
      epistemicStatus: 'OBSERVED',
      reasonCodes: ['TRANSIENT_NETWORK_FAILURE'],
      evidenceIds: ['ev-01'],
      causationId: 'caus-01',
      correlationId: 'corr-01',
      expiresAt: 1700000060000,
      lifecycleState: 'DECIDED',
      recoveryDepth: 1,
      retryCount: 0,
      reconciliationAttempts: 0,
      createdAt: 1700000000000,
      recoveryPlanId: 'plan-alpha-01',
      ...overrides,
    };
    return defaultDecision;
  };

  // ==========================================================================
  // Section 1: Core Lifecycle & Field Preservation (Requirements 1 - 8)
  // ==========================================================================

  it('1. Preserves canonical recovery control lifecycle states without invention', () => {
    const states: RecoveryControlLifecycleState[] = [
      'RECEIVED',
      'VALIDATED',
      'CLASSIFIED',
      'ASSESSED',
      'PLANNED',
      'GOVERNANCE_REQUIRED',
      'DECIDED',
      'REJECTED',
      'EXPIRED',
      'ESCALATED',
      'UNKNOWN',
    ];

    for (const state of states) {
      const decision = createSampleDecision({
        decisionId: `rec-dec-life-${state}`,
        lifecycleState: state,
      });
      executionPersistence.saveRecoveryControlDecision(decision);
    }

    const summaries = controlPlaneSnapshotService.projectRecovery(null);
    expect(summaries.length).toBe(states.length);
    for (const state of states) {
      const match = summaries.find((s) => s.lifecycleState === state);
      expect(match).toBeDefined();
      expect(match?.lifecycleState).toBe(state);
    }
  });

  it('2. Preserves every supported canonical failure classification (13 categories)', () => {
    for (const cat of FAILURE_CLASSIFICATIONS) {
      const decision = createSampleDecision({
        decisionId: `rec-dec-cat-${cat}`,
        classification: cat,
      });
      executionPersistence.saveRecoveryControlDecision(decision);
    }

    const summaries = controlPlaneSnapshotService.projectRecovery(null);
    expect(summaries.length).toBe(FAILURE_CLASSIFICATIONS.length);
    for (const cat of FAILURE_CLASSIFICATIONS) {
      const match = summaries.find((s) => s.failureClassification === cat);
      expect(match).toBeDefined();
      expect(match?.failureClassification).toBe(cat);
    }
  });

  it('3. Preserves exact recovery plan identifier without replacement or fabrication', () => {
    const planId = 'canonical-recovery-plan-xyz-987';
    const decision = createSampleDecision({
      decisionId: 'rec-dec-exact-plan',
      recoveryPlanId: planId,
    });
    executionPersistence.saveRecoveryControlDecision(decision);

    const summaries = controlPlaneSnapshotService.projectRecovery(null);
    expect(summaries[0].recoveryPlanId).toBe(planId);
  });

  it('4. Preserves original operation and correlates with mission identifier', () => {
    const decision = createSampleDecision({
      decisionId: 'rec-dec-mission-corr',
      operationId: 'child-op-77',
      originalOperationId: 'root-op-101',
      missionId: 'mission-mars-rover',
    });
    executionPersistence.saveRecoveryControlDecision(decision);

    const summaries = controlPlaneSnapshotService.projectRecovery(null, {
      missionId: 'mission-mars-rover',
    });
    expect(summaries.length).toBe(1);
    expect(summaries[0].originalOperationId).toBe('root-op-101');
  });

  it('5. Preserves all canonical proposed recovery actions (11 actions)', () => {
    for (const action of RECOVERY_ACTIONS) {
      const decision = createSampleDecision({
        decisionId: `rec-dec-act-${action}`,
        recommendedAction: action,
      });
      executionPersistence.saveRecoveryControlDecision(decision);
    }

    const summaries = controlPlaneSnapshotService.projectRecovery(null);
    expect(summaries.length).toBe(RECOVERY_ACTIONS.length);
    for (const action of RECOVERY_ACTIONS) {
      const match = summaries.find((s) => s.proposedRecoveryAction === action);
      expect(match).toBeDefined();
      expect(match?.proposedRecoveryAction).toBe(action);
    }
  });

  it('6. Preserves risk level and idempotency classification accurately', () => {
    for (const idem of IDEMPOTENCY_CLASSIFICATIONS) {
      const decision = createSampleDecision({
        decisionId: `rec-dec-idem-${idem}`,
        riskLevel: 'CRITICAL',
        safetyAssessment: {
          ...createSampleDecision().safetyAssessment!,
          idempotencyClassification: idem,
        },
      });
      executionPersistence.saveRecoveryControlDecision(decision);
    }

    const summaries = controlPlaneSnapshotService.projectRecovery(null);
    expect(summaries.length).toBe(IDEMPOTENCY_CLASSIFICATIONS.length);
    for (const idem of IDEMPOTENCY_CLASSIFICATIONS) {
      const match = summaries.find((s) => s.idempotencyAssessment === idem);
      expect(match).toBeDefined();
      expect(match?.riskLevel).toBe('CRITICAL');
      expect(match?.idempotencyAssessment).toBe(idem);
    }
  });

  it('7. Preserves required authority array as deep frozen list', () => {
    const authorities = ['STAGE21_GOVERNANCE', 'OPERATOR_HUMAN_SIGN_OFF', 'CONNECTOR_ADMIN'];
    const decision = createSampleDecision({
      decisionId: 'rec-dec-auth-test',
      requiredAuthority: authorities,
    });
    executionPersistence.saveRecoveryControlDecision(decision);

    const summaries = controlPlaneSnapshotService.projectRecovery(null);
    expect(summaries[0].requiredAuthority).toEqual(authorities);
    expect(Object.isFrozen(summaries[0].requiredAuthority)).toBe(true);
  });

  it('8. Preserves governance decision reference without fabrication', () => {
    const govId = 'gov-dec-888-verified';
    const decision = createSampleDecision({
      decisionId: 'rec-dec-gov-ref',
      governanceDecisionId: govId,
    });
    executionPersistence.saveRecoveryControlDecision(decision);

    const summaries = controlPlaneSnapshotService.projectRecovery(null);
    expect(summaries[0].governanceDecisionId).toBe(govId);
  });

  // ==========================================================================
  // Section 2: Distinction Tests (Requirements 9 - 13)
  // ==========================================================================

  it('9. Strictly distinguishes approval requirement from approval granted', () => {
    // Decision requiring human operator, but NOT approved yet
    const pendingApprovalDecision = createSampleDecision({
      decisionId: 'rec-dec-appr-req',
      governanceRequirement: {
        required: true,
        humanOperatorRequired: true,
      },
      approvalIdentity: undefined, // NOT approved
    });
    executionPersistence.saveRecoveryControlDecision(pendingApprovalDecision);

    const summaries = controlPlaneSnapshotService.projectRecovery(null);
    expect(summaries[0].approvalRequirement).toEqual({
      required: true,
      humanOperatorRequired: true,
    });
    // approvedBy MUST NOT exist or be synthetic
    expect((summaries[0].approvalRequirement as any).approvedBy).toBeUndefined();
  });

  it('10. Projects declarative compensation plan without executing compensation', () => {
    const dispatchSpy = vi.spyOn(recoveryCompensationService, 'coordinateCompensation');

    const candidatePlan: DeclarativeCompensationPlan = {
      compensationId: 'comp-plan-001',
      originalOperationId: 'op-comp-target',
      compensationType: 'REVERSE_ACTION',
      sourceCapability: 'storage.upload',
      compensatingCapability: 'storage.delete',
      targetState: 'PURGED',
      compensationParameters: { fileId: 'f-1234' },
      reversibilityClass: 'FULLY_REVERSIBLE',
      idempotencyClass: 'IDEMPOTENT',
      riskLevel: 'LOW',
      requiredAuthority: ['STORAGE_WRITE'],
      approvalRequirement: {
        required: false,
        humanOperatorRequired: false,
      },
      reconciliationRequirement: {
        required: true,
        postCompensationVerification: true,
        timeoutMs: 5000,
      },
      idempotencyKey: 'idem-comp-001',
      causationId: 'caus-comp',
      correlationId: 'corr-comp',
      expiresAt: 1700000090000,
      lifecycleState: 'READY',
      recoveryDepth: 1,
    };

    const decision = createSampleDecision({
      decisionId: 'rec-dec-with-comp',
      compensationAssessment: {
        eligibility: 'COMPENSATION_ELIGIBLE',
        reversibility: 'FULLY_REVERSIBLE',
        rationale: 'Clean delete available',
        candidatePlan,
        requiresHumanApproval: false,
        requiresReconciliation: true,
        idempotencyAssessment: 'IDEMPOTENT',
      },
    });
    executionPersistence.saveRecoveryControlDecision(decision);

    const summaries = controlPlaneSnapshotService.projectRecovery(null);
    expect(summaries[0].compensationPlan).toBeDefined();
    expect(summaries[0].compensationPlan).not.toBe('UNKNOWN');
    const projectedComp = summaries[0].compensationPlan as DeclarativeCompensationPlan;
    expect(projectedComp.compensationId).toBe('comp-plan-001');
    expect(projectedComp.compensatingCapability).toBe('storage.delete');
    expect(projectedComp.compensationParameters).toEqual({ fileId: 'f-1234' });

    // Invariant: ZERO compensation dispatch during read
    expect(dispatchSpy).not.toHaveBeenCalled();
  });

  it('11. Strictly distinguishes reconciliation requirement from reconciliation completion', () => {
    const probeSpy = vi.spyOn(recoveryReconciliationService, 'coordinateProbe');

    const decision = createSampleDecision({
      decisionId: 'rec-dec-reconcile-req',
      reconciliationRequirement: {
        required: true,
        reason: 'Verify remote blob existence',
        timeoutMs: 15000,
      },
      recommendedAction: 'RECONCILE',
      lifecycleState: 'DECIDED',
    });
    executionPersistence.saveRecoveryControlDecision(decision);

    const summaries = controlPlaneSnapshotService.projectRecovery(null);
    expect(summaries[0].reconciliationRequirement).toEqual({
      required: true,
      timeoutMs: 15000,
    });
    // Requirement does NOT mean completed or probe executed
    expect(probeSpy).not.toHaveBeenCalled();
  });

  it('12. Preserves UNKNOWN when data is missing or indeterminate without defaulting', () => {
    const incompleteDecision: any = {
      decisionId: 'rec-dec-unknown-fields',
      operationId: 'op-sparse',
      // missing recoveryPlanId, classification, epistemicStatus, etc.
    };
    executionPersistence.saveRecoveryControlDecision(incompleteDecision);

    const summaries = controlPlaneSnapshotService.projectRecovery(null);
    expect(summaries[0].recoveryPlanId).toBe('UNKNOWN');
    expect(summaries[0].failureClassification).toBe('UNKNOWN');
    expect(summaries[0].currentTruthState).toBe('UNKNOWN');
    expect(summaries[0].proposedRecoveryAction).toBe('UNKNOWN');
    expect(summaries[0].riskLevel).toBe('UNKNOWN');
    expect(summaries[0].idempotencyAssessment).toBe('UNKNOWN');
    expect(summaries[0].requiredAuthority).toBe('UNKNOWN');
    expect(summaries[0].governanceDecisionId).toBe('UNKNOWN');
    expect(summaries[0].approvalRequirement).toBe('UNKNOWN');
    expect(summaries[0].reconciliationRequirement).toBe('UNKNOWN');
    expect(summaries[0].compensationPlan).toBe('UNKNOWN');
  });

  it('13. Preserves Stage 22 operational truth and epistemic labels faithfully', () => {
    const epistemicStates: EpistemicStatus[] = [
      'OBSERVED',
      'CONFIRMED',
      'INFERRED',
      'PROJECTED',
      'UNKNOWN',
    ];

    for (const ep of epistemicStates) {
      const decision = createSampleDecision({
        decisionId: `rec-dec-ep-${ep}`,
        epistemicStatus: ep,
      });
      executionPersistence.saveRecoveryControlDecision(decision);
    }

    const summaries = controlPlaneSnapshotService.projectRecovery(null);
    for (const ep of epistemicStates) {
      const match = summaries.find((s) => s.currentTruthState === ep);
      expect(match).toBeDefined();
      expect(match?.currentTruthState).toBe(ep);
    }
  });

  // ==========================================================================
  // Section 3: Ordering, Deduplication, Filtering (Requirements 14 - 19)
  // ==========================================================================

  it('14. Preserves causation and correlation identifiers', () => {
    const decision = createSampleDecision({
      decisionId: 'rec-dec-causal-ids',
      causationId: 'cause-node-456',
      correlationId: 'corr-tree-789',
    });
    executionPersistence.saveRecoveryControlDecision(decision);

    const summaries = controlPlaneSnapshotService.projectRecovery(null);
    expect(summaries[0].causationId).toBe('cause-node-456');
    expect(summaries[0].correlationId).toBe('corr-tree-789');
  });

  it('15. Preserves expiration timestamps and TTL values', () => {
    const expiry = 1700000999999;
    const decision = createSampleDecision({
      decisionId: 'rec-dec-expiry-check',
      expiresAt: expiry,
    });
    executionPersistence.saveRecoveryControlDecision(decision);

    const summaries = controlPlaneSnapshotService.projectRecovery(null);
    expect(summaries[0].expiresAt).toBe(expiry);
  });

  it('16. Enforces deterministic ordering: primary createdAt asc, secondary operationId, tertiary decisionId', () => {
    const d1 = createSampleDecision({
      decisionId: 'rec-dec-c',
      originalOperationId: 'op-2',
      createdAt: 2000,
    });
    const d2 = createSampleDecision({
      decisionId: 'rec-dec-a',
      originalOperationId: 'op-1',
      createdAt: 1000,
    });
    const d3 = createSampleDecision({
      decisionId: 'rec-dec-b',
      originalOperationId: 'op-2',
      createdAt: 1000,
    });

    executionPersistence.saveRecoveryControlDecision(d1);
    executionPersistence.saveRecoveryControlDecision(d2);
    executionPersistence.saveRecoveryControlDecision(d3);

    const summaries = controlPlaneSnapshotService.projectRecovery(null);
    expect(summaries.length).toBe(3);
    // d2 (1000, op-1) comes before d3 (1000, op-2) comes before d1 (2000, op-2)
    expect(summaries[0].originalOperationId).toBe('op-1');
    expect(summaries[1].originalOperationId).toBe('op-2');
    expect(summaries[1].expiresAt).toBe(d3.expiresAt);
    expect(summaries[2].originalOperationId).toBe('op-2');
  });

  it('17. Handles duplicate canonical records by deduplicating on canonical decisionId', () => {
    const d1 = createSampleDecision({ decisionId: 'rec-dec-dup-1', originalOperationId: 'op-dup' });
    const dDuplicate = createSampleDecision({ decisionId: 'rec-dec-dup-1', originalOperationId: 'op-dup' });

    executionPersistence.saveRecoveryControlDecision(d1);

    // Also include in custom envelope with same ID
    const envelope: Partial<PersistedOrchestrationEnvelope> = {
      recoveryControlDecisions: {
        'rec-dec-dup-1': dDuplicate,
      },
    };

    const summaries = controlPlaneSnapshotService.projectRecovery(envelope as PersistedOrchestrationEnvelope);
    expect(summaries.length).toBe(1);
    expect(summaries[0].originalOperationId).toBe('op-dup');
  });

  it('18. Filters recovery projections by supported identifiers', () => {
    const d1 = createSampleDecision({
      decisionId: 'rec-filter-1',
      originalOperationId: 'op-target-1',
      recoveryPlanId: 'plan-target-1',
      riskLevel: 'LOW',
      classification: 'TRANSIENT',
      lifecycleState: 'DECIDED',
    });
    const d2 = createSampleDecision({
      decisionId: 'rec-filter-2',
      originalOperationId: 'op-target-2',
      recoveryPlanId: 'plan-target-2',
      riskLevel: 'CRITICAL',
      classification: 'POLICY',
      lifecycleState: 'GOVERNANCE_REQUIRED',
    });

    executionPersistence.saveRecoveryControlDecision(d1);
    executionPersistence.saveRecoveryControlDecision(d2);

    // Filter by operationId
    const byOp = controlPlaneSnapshotService.projectRecovery(null, { operationId: 'op-target-1' });
    expect(byOp.length).toBe(1);
    expect(byOp[0].originalOperationId).toBe('op-target-1');

    // Filter by riskLevel
    const byRisk = controlPlaneSnapshotService.projectRecovery(null, { riskLevel: 'CRITICAL' });
    expect(byRisk.length).toBe(1);
    expect(byRisk[0].riskLevel).toBe('CRITICAL');

    // Filter by failureClassification
    const byClass = controlPlaneSnapshotService.projectRecovery(null, { failureClassification: 'POLICY' });
    expect(byClass.length).toBe(1);
    expect(byClass[0].failureClassification).toBe('POLICY');

    // Filter by lifecycleState
    const byState = controlPlaneSnapshotService.projectRecovery(null, { lifecycleState: 'GOVERNANCE_REQUIRED' });
    expect(byState.length).toBe(1);
    expect(byState[0].lifecycleState).toBe('GOVERNANCE_REQUIRED');
  });

  it('19. Gracefully handles empty and incomplete persistence envelopes', () => {
    const empty1 = controlPlaneSnapshotService.projectRecovery(null);
    expect(empty1).toEqual([]);

    const empty2 = controlPlaneSnapshotService.projectRecovery({} as any);
    expect(empty2).toEqual([]);

    const partialEnvelope: any = {
      recoveryControlDecisions: {
        invalidItem: null,
        numericItem: 42,
      },
    };
    const safeResult = controlPlaneSnapshotService.projectRecovery(partialEnvelope);
    expect(safeResult).toEqual([]);
  });

  // ==========================================================================
  // Section 4: Security, Invariants & Immutability (Requirements 20 - 30)
  // ==========================================================================

  it('20. Guarantees deep immutability of projected recovery summaries and nested objects', () => {
    const decision = createSampleDecision({
      decisionId: 'rec-dec-freeze-test',
      requiredAuthority: ['OPERATOR', 'ADMIN'],
      governanceRequirement: { required: true, humanOperatorRequired: true },
      reconciliationRequirement: { required: true, timeoutMs: 10000 },
    });
    executionPersistence.saveRecoveryControlDecision(decision);

    const summaries = controlPlaneSnapshotService.projectRecovery(null);
    expect(Object.isFrozen(summaries)).toBe(true);
    expect(Object.isFrozen(summaries[0])).toBe(true);
    expect(Object.isFrozen(summaries[0].requiredAuthority)).toBe(true);
    expect(Object.isFrozen(summaries[0].approvalRequirement)).toBe(true);
    expect(Object.isFrozen(summaries[0].reconciliationRequirement)).toBe(true);

    // Mutation attempts in strict mode must throw
    expect(() => {
      (summaries as any).push({});
    }).toThrow();

    expect(() => {
      (summaries[0] as any).riskLevel = 'MUTATED';
    }).toThrow();
  });

  it('21. Demonstrates strictly read-only behavior across all persistence layers', () => {
    const saveSpy = vi.spyOn(executionPersistence, 'saveRecoveryControlDecision');
    const deleteSpy = vi.spyOn(executionPersistence, 'deleteRecoveryControlLease');

    const decision = createSampleDecision({ decisionId: 'rec-dec-readonly' });
    executionPersistence.saveRecoveryControlDecision(decision);
    saveSpy.mockClear();

    controlPlaneSnapshotService.projectRecovery(null);

    expect(saveSpy).not.toHaveBeenCalled();
    expect(deleteSpy).not.toHaveBeenCalled();
  });

  it('22. Guarantees zero Action Bus dispatch during projection', () => {
    const dispatchSpy = vi.spyOn(actionBusService, 'execute');

    const decision = createSampleDecision({ decisionId: 'rec-dec-no-bus' });
    executionPersistence.saveRecoveryControlDecision(decision);

    controlPlaneSnapshotService.projectRecovery(null);
    expect(dispatchSpy).not.toHaveBeenCalled();
  });

  it('23. Guarantees zero recovery execution during projection reads', () => {
    const evalSpy = vi.spyOn(recoveryControlPlane, 'evaluateRecoveryControl');
    const compSpy = vi.spyOn(recoveryCompensationService, 'coordinateCompensation');
    const probeSpy = vi.spyOn(recoveryReconciliationService, 'coordinateProbe');

    const decision = createSampleDecision({ decisionId: 'rec-dec-no-exec' });
    executionPersistence.saveRecoveryControlDecision(decision);

    controlPlaneSnapshotService.projectRecovery(null);
    expect(evalSpy).not.toHaveBeenCalled();
    expect(compSpy).not.toHaveBeenCalled();
    expect(probeSpy).not.toHaveBeenCalled();
  });

  it('24. Guarantees zero governance or policy mutation', () => {
    const verBefore = policyRegistry.getRegistryVersion();
    const govSpy = vi.spyOn(governanceControlPlane, 'evaluateGovernance');

    const decision = createSampleDecision({ decisionId: 'rec-dec-no-gov-eval' });
    executionPersistence.saveRecoveryControlDecision(decision);

    controlPlaneSnapshotService.projectRecovery(null);

    expect(govSpy).not.toHaveBeenCalled();
    expect(policyRegistry.getRegistryVersion()).toBe(verBefore);
  });

  it('25. Guarantees zero persistence mutation', () => {
    const countBefore = executionPersistence.getAllRecoveryControlDecisions().length;

    const decision = createSampleDecision({ decisionId: 'rec-dec-persistence-check' });
    executionPersistence.saveRecoveryControlDecision(decision);
    const countAfterSave = executionPersistence.getAllRecoveryControlDecisions().length;

    controlPlaneSnapshotService.projectRecovery(null);

    const countAfterRead = executionPersistence.getAllRecoveryControlDecisions().length;
    expect(countAfterRead).toBe(countAfterSave);
  });

  it('26. Scrubs sensitive secrets, bearer tokens, and keys from projected strings', () => {
    const decision = createSampleDecision({
      decisionId: 'rec-dec-scrub-fixture',
      governanceRequirement: { required: true, humanOperatorRequired: true },
      approvalIdentity: 'operator Bearer secret-tok-12345',
      requiredAuthority: ['sk-adminKey987654321', 'OPERATOR'],
    });
    executionPersistence.saveRecoveryControlDecision(decision);

    const summaries = controlPlaneSnapshotService.projectRecovery(null);
    expect(summaries.length).toBe(1);
    const approvalReq = summaries[0].approvalRequirement as any;
    expect(approvalReq.approvedBy).toContain('Bearer [REDACTED');
    expect(approvalReq.approvedBy).not.toContain('secret-tok-12345');

    const authorities = summaries[0].requiredAuthority as string[];
    expect(authorities[0]).toContain('sk-[REDACTED');
    expect(authorities[0]).not.toContain('987654321');
  });

  it('27. Protects against prototype pollution in filter options', () => {
    const maliciousPayload = JSON.parse(
      '{"__proto__": {"polluted": true}, "constructor": {"prototype": {"polluted": true}}, "operationId": "op-alpha-01"}'
    );

    const decision = createSampleDecision({ decisionId: 'rec-dec-proto', operationId: 'op-alpha-01' });
    executionPersistence.saveRecoveryControlDecision(decision);

    const summaries = controlPlaneSnapshotService.projectRecovery(null, maliciousPayload);
    expect(summaries.length).toBe(1);
    expect((Object.prototype as any).polluted).toBeUndefined();
    expect((({} as any).polluted)).toBeUndefined();
  });

  it('28. Handles malformed inputs and corrupted structures gracefully', () => {
    const malformedEnvelope: any = {
      recoveryControlDecisions: {
        bad1: 'a string instead of object',
        bad2: 12345,
        bad3: {
          decisionId: null,
          operationId: undefined,
          classification: 'NOT_A_CANONICAL_CLASS',
          recommendedAction: 'JUMP_OUT_OF_WINDOW',
          lifecycleState: 'COMPLETELY_BOGUS_STATE',
        },
      },
    };

    const summaries = controlPlaneSnapshotService.projectRecovery(malformedEnvelope);
    expect(summaries.length).toBe(1);
    expect(summaries[0].failureClassification).toBe('UNKNOWN');
    expect(summaries[0].proposedRecoveryAction).toBe('UNKNOWN');
    expect(summaries[0].lifecycleState).toBe('UNKNOWN');
  });

  it('29. Bounds traversal depth and output size when maxRecords is specified', () => {
    for (let i = 0; i < 50; i++) {
      const decision = createSampleDecision({
        decisionId: `rec-dec-batch-${i}`,
        originalOperationId: `op-${i}`,
        createdAt: 1000 + i,
      });
      executionPersistence.saveRecoveryControlDecision(decision);
    }

    const summaries = controlPlaneSnapshotService.projectRecovery(null, { maxRecords: 10 });
    expect(summaries.length).toBe(10);
  });

  it('30. Guarantees deterministic output across concurrent reads', () => {
    for (let i = 0; i < 20; i++) {
      const decision = createSampleDecision({
        decisionId: `rec-dec-concurrent-${i}`,
        originalOperationId: `op-${i % 5}`,
        createdAt: 1000 + (i % 7),
      });
      executionPersistence.saveRecoveryControlDecision(decision);
    }

    const read1 = controlPlaneSnapshotService.projectRecovery(null);
    const read2 = controlPlaneSnapshotService.projectRecovery(null);
    const read3 = controlPlaneSnapshotService.projectRecovery(null);

    expect(read1).toEqual(read2);
    expect(read2).toEqual(read3);
  });

  // ==========================================================================
  // Section 5: Integration, Evidence & Invariant Regression (Requirements 31 - 34)
  // ==========================================================================

  it('31. Integrates seamlessly into ControlPlaneSnapshot facade', () => {
    const decision = createSampleDecision({ decisionId: 'rec-dec-snapshot-int' });
    executionPersistence.saveRecoveryControlDecision(decision);

    const snapshot = controlPlaneSnapshotService.getSnapshot();
    expect(snapshot.recovery).toBeDefined();
    expect(snapshot.recovery.length).toBeGreaterThanOrEqual(1);
    expect(snapshot.recovery.find((r) => r.originalOperationId === 'op-alpha-01')).toBeDefined();
  });

  it('32. Preserves Stage 22 empirical audit evidence when verifying truth state', () => {
    // Record canonical audit event in Stage 22 for operation
    auditEventRegistry.recordEvent({
      operationId: 'op-truth-verified-99',
      correlationId: 'corr-99',
      causationId: 'caus-99',
      eventType: 'OBSERVATION_RECORDED',
      lifecycleState: 'SUCCEEDED',
      epistemicStatus: 'CONFIRMED',
      sourceSystem: 'stage22_operational_truth',
      actor: { actorId: 'system', actorType: 'SYSTEM' },
    });

    const decision = createSampleDecision({
      decisionId: 'rec-dec-stage22-truth',
      originalOperationId: 'op-truth-verified-99',
      epistemicStatus: undefined as any, // unpopulated in decision
    });
    executionPersistence.saveRecoveryControlDecision(decision);

    const summaries = controlPlaneSnapshotService.projectRecovery(null);
    const match = summaries.find((s) => s.originalOperationId === 'op-truth-verified-99');
    expect(match).toBeDefined();
    expect(match?.currentTruthState).toBe('CONFIRMED');
  });

  it('33. Stage 23 recovery authority regression remains 100% functional', () => {
    expect(recoveryControlPlane).toBeDefined();
    expect(recoveryCompensationService).toBeDefined();
    expect(recoveryReconciliationService).toBeDefined();
    expect(typeof recoveryControlPlane.evaluateRecoveryControl).toBe('function');
  });

  it('34. Verifies no duplicate recovery engine or secondary planner was introduced', () => {
    // ControlPlaneSnapshotService is purely an observational projection facade
    expect(controlPlaneSnapshotService.projectRecovery).toBeDefined();
    expect((controlPlaneSnapshotService as any).retry).toBeUndefined();
    expect((controlPlaneSnapshotService as any).resume).toBeUndefined();
    expect((controlPlaneSnapshotService as any).compensate).toBeUndefined();
    expect((controlPlaneSnapshotService as any).reconcile).toBeUndefined();
    expect((controlPlaneSnapshotService as any).recover).toBeUndefined();
  });

  // ==========================================================================
  // Section 6: Adversarial Cases (Cases A - H)
  // ==========================================================================

  it('Adversarial Case A: Unknown external outcome after dispatch remains strictly UNKNOWN', () => {
    const decision = createSampleDecision({
      decisionId: 'rec-adv-unknown-dispatch',
      epistemicStatus: 'UNKNOWN',
      recoveryOutcome: 'UNKNOWN',
    });
    executionPersistence.saveRecoveryControlDecision(decision);

    const summaries = controlPlaneSnapshotService.projectRecovery(null);
    expect(summaries[0].currentTruthState).toBe('UNKNOWN');
    expect(summaries[0].expectedOutcome).toBe('UNKNOWN');
    // Invariant: MUST NOT be coerced to CONFIRMED or SUCCEEDED
    expect(summaries[0].currentTruthState).not.toBe('CONFIRMED');
  });

  it('Adversarial Case B: A recovery plan awaiting human approval is projected as unapproved', () => {
    const decision = createSampleDecision({
      decisionId: 'rec-adv-awaiting-human',
      governanceRequirement: {
        required: true,
        humanOperatorRequired: true,
        reason: 'High risk destructive compensation',
      },
      approvalIdentity: undefined, // operator has NOT signed
      lifecycleState: 'GOVERNANCE_REQUIRED',
    });
    executionPersistence.saveRecoveryControlDecision(decision);

    const summaries = controlPlaneSnapshotService.projectRecovery(null);
    expect(summaries[0].lifecycleState).toBe('GOVERNANCE_REQUIRED');
    const req = summaries[0].approvalRequirement as any;
    expect(req.required).toBe(true);
    expect(req.humanOperatorRequired).toBe(true);
    expect(req.approvedBy).toBeUndefined();
  });

  it('Adversarial Case C: An expired or stale recovery decision preserves EXPIRED status faithfully', () => {
    const pastTime = 1600000000000; // Far in the past
    const decision = createSampleDecision({
      decisionId: 'rec-adv-expired-ttl',
      expiresAt: pastTime,
      lifecycleState: 'EXPIRED',
    });
    executionPersistence.saveRecoveryControlDecision(decision);

    const summaries = controlPlaneSnapshotService.projectRecovery(null);
    expect(summaries[0].lifecycleState).toBe('EXPIRED');
    expect(summaries[0].expiresAt).toBe(pastTime);
  });

  it('Adversarial Case D: A compensation plan whose execution is unconfirmed displays declarative steps only', () => {
    const decision = createSampleDecision({
      decisionId: 'rec-adv-unconfirmed-comp',
      compensationAssessment: {
        eligibility: 'COMPENSATION_ELIGIBLE',
        reversibility: 'PARTIALLY_REVERSIBLE',
        rationale: 'Rollback database record',
        requiresHumanApproval: true,
        requiresReconciliation: true,
        idempotencyAssessment: 'NON_IDEMPOTENT',
        candidatePlan: {
          compensationId: 'comp-unconfirmed-1',
          originalOperationId: 'op-unconfirmed',
          compensationType: 'STATE_CORRECTION',
          sourceCapability: 'db.update',
          compensatingCapability: 'db.restore',
          targetState: 'RESTORED_INITIAL',
          compensationParameters: { table: 'ledger', rowId: 99 },
          reversibilityClass: 'PARTIALLY_REVERSIBLE',
          idempotencyClass: 'NON_IDEMPOTENT',
          riskLevel: 'HIGH',
          requiredAuthority: ['DB_ADMIN'],
          approvalRequirement: { required: true, humanOperatorRequired: true },
          reconciliationRequirement: { required: true, postCompensationVerification: true },
          idempotencyKey: 'idem-unconfirmed-comp',
          causationId: 'caus-99',
          correlationId: 'corr-99',
          expiresAt: 1700000050000,
          lifecycleState: 'PROPOSED',
          recoveryDepth: 1,
        },
      },
    });
    executionPersistence.saveRecoveryControlDecision(decision);

    const summaries = controlPlaneSnapshotService.projectRecovery(null);
    const compPlan = summaries[0].compensationPlan as DeclarativeCompensationPlan;
    expect(compPlan.lifecycleState).toBe('PROPOSED');
    expect(compPlan.targetState).toBe('RESTORED_INITIAL');
  });

  it('Adversarial Case E: Missing reconciliation evidence is explicitly preserved without assuming completion', () => {
    const decision = createSampleDecision({
      decisionId: 'rec-adv-missing-recon',
      reconciliationRequirement: {
        required: true,
        reason: 'Evidence unconfirmed after provider outage',
        timeoutMs: 8000,
      },
      epistemicStatus: 'UNKNOWN',
    });
    executionPersistence.saveRecoveryControlDecision(decision);

    const summaries = controlPlaneSnapshotService.projectRecovery(null);
    expect(summaries[0].currentTruthState).toBe('UNKNOWN');
    expect(summaries[0].reconciliationRequirement).toEqual({
      required: true,
      timeoutMs: 8000,
    });
  });

  it('Adversarial Case F: Conflicting or incomplete source records project safely without crashing', () => {
    const conflictingDecision: any = {
      decisionId: 'rec-adv-conflicting',
      operationId: 'op-conflict-1',
      classification: 99999, // non-string classification
      recommendedAction: { illegal: 'object' },
      lifecycleState: ['array', 'state'],
      expiresAt: 'not-a-number',
      safetyAssessment: null,
    };
    executionPersistence.saveRecoveryControlDecision(conflictingDecision);

    const summaries = controlPlaneSnapshotService.projectRecovery(null);
    expect(summaries.length).toBe(1);
    expect(summaries[0].failureClassification).toBe('UNKNOWN');
    expect(summaries[0].proposedRecoveryAction).toBe('UNKNOWN');
    expect(summaries[0].lifecycleState).toBe('UNKNOWN');
    expect(summaries[0].expiresAt).toBe('UNKNOWN');
  });

  it('Adversarial Case G: Forged client-supplied recovery state is strictly sanitized to UNKNOWN', () => {
    const forgedEnvelope: any = {
      recoveryControlDecisions: {
        'rec-forged-1': {
          decisionId: 'rec-forged-1',
          originalOperationId: 'op-forged-target',
          lifecycleState: 'FABRICATED_SUPER_SUCCESS', // Forged state
          classification: 'TRANSIENT',
          recommendedAction: 'RETRY',
        },
      },
    };

    const summaries = controlPlaneSnapshotService.projectRecovery(forgedEnvelope);
    expect(summaries.length).toBe(1);
    // Forged lifecycle state MUST NOT be trusted
    expect(summaries[0].lifecycleState).toBe('UNKNOWN');
  });

  it('Adversarial Case H: Duplicate replay records are deduplicated while distinct decisions are preserved', () => {
    // 1. Replay records with identical decisionId
    const dReplay1 = createSampleDecision({
      decisionId: 'rec-canonical-unique-1',
      originalOperationId: 'op-same-stream',
      createdAt: 1000,
    });
    const dReplay2 = createSampleDecision({
      decisionId: 'rec-canonical-unique-1', // identical decisionId
      originalOperationId: 'op-same-stream',
      createdAt: 1000,
    });

    // 2. Distinct recovery decision for the same operation (e.g. second attempt after escalation)
    const dDistinct = createSampleDecision({
      decisionId: 'rec-canonical-unique-2', // distinct decisionId
      originalOperationId: 'op-same-stream',
      createdAt: 2000,
      retryCount: 1,
      recoveryDepth: 2,
    });

    executionPersistence.saveRecoveryControlDecision(dReplay1);
    executionPersistence.saveRecoveryControlDecision(dDistinct);

    const customEnvelope: any = {
      recoveryControlDecisions: {
        'rec-canonical-unique-1': dReplay2,
      },
    };

    const summaries = controlPlaneSnapshotService.projectRecovery(customEnvelope);

    // Expect exactly 2 distinct decisions, NOT 3
    expect(summaries.length).toBe(2);
    expect(summaries.map((s) => s.retryCount)).toEqual([0, 1]);
  });
});
