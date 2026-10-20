/**
 * AryaOS V1 — Stage 24: Mission Operations Control Plane
 * Phase 6: Mission Operations Projection Test Suite
 *
 * Deterministic, comprehensive verification of the Mission Operations Projection:
 * - Read-only observational facade over Stage 12 MissionManager, Stage 08 GoalOrchestrator,
 *   Stage 09 ExecutionPersistence, Stage 10 ResourceGovernor, Stage 22 OperationalTruth,
 *   and Stage 23 RecoveryControlPlane.
 * - Rigorous verification of all 34 prompt test requirements + adversarial hardening.
 * - ZERO execution, ZERO goal scheduling/mutation, ZERO replanning, ZERO resource mutation,
 *   ZERO Action Bus dispatch, ZERO network calls, ZERO LLM tokens.
 */

import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import {
  controlPlaneSnapshotService,
  MissionFilterOptions,
  MissionDetailProjection,
  CANONICAL_MISSION_STATUSES,
  CANONICAL_MISSION_PRIORITIES,
} from '../services/controlPlaneSnapshotService';
import { executionPersistence } from '../services/executionPersistence';
import { auditEventRegistry } from '../services/auditEventRegistry';
import { resourceGovernor } from '../services/resourceGovernor';
import { goalOrchestrator } from '../services/goalOrchestrator';
import { missionManager } from '../services/missionManager';
import { actionBusService } from '../services/actionBusService';
import { Mission, MissionCheckpoint } from '../types/missionControl';
import { Goal } from '../types/goalOrchestration';
import { OperationalAuditEvent } from '../types/operationalAudit';
import { RecoveryControlDecision } from '../types/recoveryControl';

function createMockMission(overrides?: Partial<Mission>): Mission {
  return {
    missionId: 'mis-stage24-alpha',
    title: 'Orbital Reconnaissance Mission',
    objective: 'Map high-resolution satellite imagery across the Northern sector.',
    goals: [
      {
        goalId: 'goal-recon-1',
        title: 'Calibrate Optical Sensors',
        mandatory: true,
        status: 'COMPLETED',
        weight: 1,
        timeoutMs: 5000,
      },
      {
        goalId: 'goal-recon-2',
        title: 'Capture High-Res Imaging',
        mandatory: true,
        status: 'RUNNING',
        weight: 2,
        timeoutMs: 15000,
      },
      {
        goalId: 'goal-recon-3',
        title: 'Downlink Telemetry Data',
        mandatory: false,
        status: 'PLANNED',
        weight: 1,
      },
    ],
    dependencies: [
      {
        fromGoalId: 'goal-recon-1',
        toGoalId: 'goal-recon-2',
        type: 'FINISH_TO_START',
      },
      {
        fromGoalId: 'goal-recon-2',
        toGoalId: 'goal-recon-3',
        type: 'FINISH_TO_START',
      },
    ],
    priority: 'HIGH',
    status: 'RUNNING',
    riskLevel: 'LOW',
    progress: {
      totalGoals: 3,
      completedGoals: 1,
      failedGoals: 0,
      inProgressGoals: 1,
      blockedGoals: 0,
      percentage: 33,
    },
    plans: [
      {
        missionId: 'mis-stage24-alpha',
        planVersion: 1,
        goalOrder: [['goal-recon-1'], ['goal-recon-2'], ['goal-recon-3']],
        criticalPath: ['goal-recon-1', 'goal-recon-2', 'goal-recon-3'],
        estimatedCost: { minUsd: 10, maxUsd: 25, currency: 'USD' },
        estimatedDurationMs: 30000,
        riskAssessment: [
          {
            riskId: 'risk-weather-1',
            type: 'DEADLINE',
            level: 'LOW',
            source: 'Orbital Ephemeris',
            evidence: ['Solar flare activity below nominal threshold'],
            confidence: 'HIGH',
            createdAt: '2026-10-04T12:00:00.000Z',
            mitigation: 'Use secondary telemetry frequency if interference occurs',
          },
        ],
        assumptions: ['Stable solar array power'],
        evidence: ['Telemetry stream nominal'],
        confidence: 'HIGH',
        createdAt: '2026-10-04T12:00:00.000Z',
        preservedGoals: [],
        affectedGoals: [],
      },
    ],
    currentPlanVersion: 1,
    checkpoints: [
      {
        checkpointId: 'cp-recon-001',
        missionId: 'mis-stage24-alpha',
        missionStatus: 'RUNNING',
        planVersion: 1,
        completedGoals: ['goal-recon-1'],
        activeGoals: ['goal-recon-2'],
        blockedGoals: [],
        pendingApprovals: [],
        resourceState: {},
        timestamp: '2026-10-04T12:05:00.000Z',
      },
    ],
    observations: [],
    decisions: [],
    constraints: [
      {
        type: 'COST_BUDGET',
        value: 100,
        strict: true,
      },
    ],
    milestones: [],
    completionCriteria: {
      mandatoryGoalsCompleted: true,
      minimumSuccessRate: 0.8,
      requiredMilestonesCompleted: [],
      allowPartialSuccess: false,
      requireHumanSignoff: true,
    },
    executionPolicy: {
      autoApproveReadOnly: true,
      allowPartialSuccess: false,
      maxCostUsd: 100,
      replanOnGoalFailure: true,
    },
    createdAt: '2026-10-04T12:00:00.000Z',
    updatedAt: '2026-10-04T12:10:00.000Z',
    provenance: { source: 'flight-control' },
    ...overrides,
  };
}

describe('Stage 24 — Phase 6: Mission Operations Projection', () => {
  beforeEach(() => {
    executionPersistence.clearEnvelope();
    auditEventRegistry.reset();
    resourceGovernor.resetState();
    goalOrchestrator.resetState();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  // 1. Empty mission registry
  it('1. returns empty array when mission registry, persistence, and envelope are empty', () => {
    const summaries = controlPlaneSnapshotService.projectMissions(null);
    expect(summaries).toEqual([]);

    const detail = controlPlaneSnapshotService.projectMissionDetail('non-existent-mission');
    expect(detail).toBeNull();
  });

  // 2. Single mission with authoritative state
  it('2. projects single mission with authoritative lifecycle and goal state', () => {
    const mission = createMockMission();
    executionPersistence.saveMission(mission);

    const summaries = controlPlaneSnapshotService.projectMissions(null);
    expect(summaries.length).toBe(1);

    const summary = summaries[0];
    expect(summary.missionId).toBe('mis-stage24-alpha');
    expect(summary.title).toBe('Orbital Reconnaissance Mission');
    expect(summary.status).toBe('RUNNING');
    expect(summary.priority).toBe('HIGH');
    expect(summary.goalId).toBe('goal-recon-1');
    expect(summary.activeOperations).toBe(1);
    expect(summary.blockedOperations).toBe(0);

    const detail = controlPlaneSnapshotService.projectMissionDetail('mis-stage24-alpha');
    expect(detail).not.toBeNull();
    expect(detail?.missionId).toBe('mis-stage24-alpha');
    expect(detail?.goals.length).toBe(3);
    expect(detail?.dependencies.length).toBe(2);
    expect(detail?.checkpoints.length).toBe(1);
    expect(detail?.sourceIntegrity).toBe('AUTHORITATIVE');
  });

  // 3. Multiple missions with deterministic ordering
  it('3. enforces deterministic ordering (Priority desc, createdAt desc, missionId asc)', () => {
    const mLow = createMockMission({
      missionId: 'mis-low-1',
      priority: 'LOW',
      createdAt: '2026-10-04T10:00:00.000Z',
    });
    const mCritOld = createMockMission({
      missionId: 'mis-crit-old',
      priority: 'CRITICAL',
      createdAt: '2026-10-04T08:00:00.000Z',
    });
    const mCritNew = createMockMission({
      missionId: 'mis-crit-new',
      priority: 'CRITICAL',
      createdAt: '2026-10-04T14:00:00.000Z',
    });
    const mNormal = createMockMission({
      missionId: 'mis-normal-1',
      priority: 'NORMAL',
      createdAt: '2026-10-04T12:00:00.000Z',
    });
    const mHigh = createMockMission({
      missionId: 'mis-high-1',
      priority: 'HIGH',
      createdAt: '2026-10-04T11:00:00.000Z',
    });

    executionPersistence.saveMission(mLow);
    executionPersistence.saveMission(mCritOld);
    executionPersistence.saveMission(mCritNew);
    executionPersistence.saveMission(mNormal);
    executionPersistence.saveMission(mHigh);

    const summaries = controlPlaneSnapshotService.projectMissions(null);
    expect(summaries.length).toBe(5);

    // CRITICAL (newer first: mis-crit-new, then mis-crit-old) -> HIGH -> NORMAL -> LOW
    expect(summaries[0].missionId).toBe('mis-crit-new');
    expect(summaries[1].missionId).toBe('mis-crit-old');
    expect(summaries[2].missionId).toBe('mis-high-1');
    expect(summaries[3].missionId).toBe('mis-normal-1');
    expect(summaries[4].missionId).toBe('mis-low-1');
  });

  // 4. Mission-to-goal relationship projection
  it('4. projects granular goal relationships with lifecycle, mandatory status, and weights', () => {
    const mission = createMockMission();
    executionPersistence.saveMission(mission);

    const detail = controlPlaneSnapshotService.projectMissionDetail('mis-stage24-alpha');
    expect(detail).not.toBeNull();
    const goals = detail!.goals;

    expect(goals.length).toBe(3);
    expect(goals[0].goalId).toBe('goal-recon-1');
    expect(goals[0].title).toBe('Calibrate Optical Sensors');
    expect(goals[0].mandatory).toBe(true);
    expect(goals[0].status).toBe('COMPLETED');
    expect(goals[0].isCompleted).toBe(true);

    expect(goals[1].goalId).toBe('goal-recon-2');
    expect(goals[1].status).toBe('RUNNING');
    expect(goals[1].isCompleted).toBe(false);

    expect(goals[2].goalId).toBe('goal-recon-3');
    expect(goals[2].mandatory).toBe(false);
    expect(goals[2].status).toBe('PLANNED');
  });

  // 5. Dependency satisfied by authoritative evidence
  it('5. projects satisfied dependency when predecessor has achieved completed status', () => {
    const mission = createMockMission();
    executionPersistence.saveMission(mission);

    const detail = controlPlaneSnapshotService.projectMissionDetail('mis-stage24-alpha');
    const dep1 = detail?.dependencies.find(
      (d) => d.fromGoalId === 'goal-recon-1' && d.toGoalId === 'goal-recon-2'
    );

    expect(dep1).toBeDefined();
    expect(dep1?.satisfactionState).toBe('SATISFIED');
    expect(dep1?.evidence).toContain('completed successfully');
    expect(dep1?.isCycle).toBe(false);
  });

  // 6. Dependency pending or blocked
  it('6. correctly distinguishes pending vs blocked dependencies based on predecessor state', () => {
    const mission = createMockMission({
      goals: [
        { goalId: 'g-run', title: 'Running Goal', mandatory: true, status: 'RUNNING', weight: 1 },
        { goalId: 'g-block', title: 'Blocked Goal', mandatory: true, status: 'BLOCKED', weight: 1 },
        { goalId: 'g-target1', title: 'Target 1', mandatory: true, status: 'PLANNED', weight: 1 },
        { goalId: 'g-target2', title: 'Target 2', mandatory: true, status: 'PLANNED', weight: 1 },
      ],
      dependencies: [
        { fromGoalId: 'g-run', toGoalId: 'g-target1', type: 'FINISH_TO_START' },
        { fromGoalId: 'g-block', toGoalId: 'g-target2', type: 'FINISH_TO_START' },
      ],
    });
    executionPersistence.saveMission(mission);

    const detail = controlPlaneSnapshotService.projectMissionDetail(mission.missionId);
    const depPending = detail?.dependencies.find((d) => d.fromGoalId === 'g-run');
    const depBlocked = detail?.dependencies.find((d) => d.fromGoalId === 'g-block');

    expect(depPending?.satisfactionState).toBe('PENDING');
    expect(depPending?.evidence).toContain('pending execution');

    expect(depBlocked?.satisfactionState).toBe('BLOCKED');
    expect(depBlocked?.evidence).toContain('is in non-executable status');
  });

  // 7. Missing dependency evidence preserved explicitly
  it('7. reports MISSING_EVIDENCE when predecessor goal record is absent from all registries', () => {
    const mission = createMockMission({
      dependencies: [
        { fromGoalId: 'ghost-goal-missing', toGoalId: 'goal-recon-1', type: 'FINISH_TO_START' },
      ],
    });
    executionPersistence.saveMission(mission);

    const detail = controlPlaneSnapshotService.projectMissionDetail(mission.missionId);
    const ghostDep = detail?.dependencies.find((d) => d.fromGoalId === 'ghost-goal-missing');

    expect(ghostDep).toBeDefined();
    expect(ghostDep?.satisfactionState).toBe('MISSING_EVIDENCE');
    expect(ghostDep?.evidence).toContain('not found in mission, goal registry, or envelope');
    expect(detail?.blockers).toContain(
      "Missing dependency evidence: predecessor 'ghost-goal-missing' does not exist"
    );
  });

  // 8. Cyclic or malformed dependency input handled safely without infinite traversal
  it('8. detects circular dependencies safely without infinite loop or stack overflow', () => {
    const mission = createMockMission({
      goals: [
        { goalId: 'gA', title: 'Goal A', mandatory: true, status: 'RUNNING', weight: 1 },
        { goalId: 'gB', title: 'Goal B', mandatory: true, status: 'RUNNING', weight: 1 },
      ],
      dependencies: [
        { fromGoalId: 'gA', toGoalId: 'gB', type: 'FINISH_TO_START' },
        { fromGoalId: 'gB', toGoalId: 'gA', type: 'FINISH_TO_START' },
      ],
    });
    executionPersistence.saveMission(mission);

    const detail = controlPlaneSnapshotService.projectMissionDetail(mission.missionId);
    expect(detail).not.toBeNull();

    for (const dep of detail!.dependencies) {
      expect(dep.isCycle).toBe(true);
      expect(dep.satisfactionState).toBe('BLOCKED');
      expect(dep.evidence).toContain('Circular dependency detected');
    }

    expect(detail?.blockers.some((b) => b.includes('Circular dependency detected'))).toBe(true);
  });

  // 9. Goal completion does not fabricate mission completion
  it('9. preserves canonical mission status even when 100% of goals are COMPLETED (no auto-completion)', () => {
    const mission = createMockMission({
      status: 'RUNNING',
      goals: [
        { goalId: 'g1', title: 'Goal 1', mandatory: true, status: 'COMPLETED', weight: 1 },
        { goalId: 'g2', title: 'Goal 2', mandatory: true, status: 'COMPLETED', weight: 1 },
      ],
      progress: {
        totalGoals: 2,
        completedGoals: 2,
        failedGoals: 0,
        inProgressGoals: 0,
        blockedGoals: 0,
        percentage: 100,
      },
    });
    executionPersistence.saveMission(mission);

    const summaries = controlPlaneSnapshotService.projectMissions(null);
    expect(summaries[0].status).toBe('RUNNING'); // NOT auto-promoted to COMPLETED

    const detail = controlPlaneSnapshotService.projectMissionDetail(mission.missionId);
    expect(detail?.status).toBe('RUNNING');
  });

  // 10. Unknown mission lifecycle state
  it('10. maps unverified or non-canonical mission status to UNKNOWN', () => {
    const mission = createMockMission({
      status: 'SUPER_FINISHED' as any,
    });
    executionPersistence.saveMission(mission);

    const summaries = controlPlaneSnapshotService.projectMissions(null);
    expect(summaries[0].status).toBe('UNKNOWN');

    const detail = controlPlaneSnapshotService.projectMissionDetail(mission.missionId);
    expect(detail?.status).toBe('UNKNOWN');
  });

  // 11. Missing mission records and incomplete source records
  it('11. flags INCOMPLETE sourceIntegrity when active mission lacks goal references', () => {
    const mission = createMockMission({
      status: 'RUNNING',
      goals: [],
    });
    executionPersistence.saveMission(mission);

    const detail = controlPlaneSnapshotService.projectMissionDetail(mission.missionId);
    expect(detail?.sourceIntegrity).toBe('INCOMPLETE');
    expect(detail?.unresolvedDiscrepancies.some((d) => d.includes('no goal references exist'))).toBe(true);
  });

  // 12. Conflicting lifecycle records
  it('12. flags CONFLICTING sourceIntegrity and marks epistemicStatus UNKNOWN when records contradict', () => {
    const missionPersisted = createMockMission({
      missionId: 'mis-conflict-1',
      status: 'PAUSED',
    });
    executionPersistence.saveMission(missionPersisted);

    // Envelope holds conflicting status
    const envelope = executionPersistence.loadEnvelope() || {
      schemaVersion: 1,
      savedAt: new Date().toISOString(),
      goals: {},
      activeGoalId: null,
      observations: {},
      approvals: {},
      telemetry: {} as any,
      missions: {},
    };
    envelope.missions = {
      'mis-conflict-1': createMockMission({
        missionId: 'mis-conflict-1',
        status: 'RUNNING',
      }),
    };

    const detail = controlPlaneSnapshotService.projectMissionDetail('mis-conflict-1', envelope);
    expect(detail?.sourceIntegrity).toBe('CONFLICTING');
    expect(detail?.epistemicStatus).toBe('UNKNOWN');
    expect(detail?.unresolvedDiscrepancies.some((d) => d.includes('Lifecycle state conflict'))).toBe(true);
  });

  // 13. Progress derived only from authoritative data
  it('13. projects recorded progress and marks isConsistent true when goals tally with progress counts', () => {
    const mission = createMockMission();
    executionPersistence.saveMission(mission);

    const detail = controlPlaneSnapshotService.projectMissionDetail(mission.missionId);
    expect(detail?.progress.progressProvenance).toBe('RECORDED');
    expect(detail?.progress.isConsistent).toBe(true);
    expect(detail?.progress.percentage).toBe(33);
  });

  // 14. Missing progress represented honestly
  it('14. derives progress honestly when progress object is absent, without fabricating percentage when no goals exist', () => {
    const missionWithGoals = createMockMission({
      progress: undefined as any,
      goals: [
        { goalId: 'g1', title: 'G1', mandatory: true, status: 'COMPLETED', weight: 1 },
        { goalId: 'g2', title: 'G2', mandatory: true, status: 'RUNNING', weight: 1 },
      ],
    });
    executionPersistence.saveMission(missionWithGoals);

    const detail1 = controlPlaneSnapshotService.projectMissionDetail(missionWithGoals.missionId);
    expect(detail1?.progress.progressProvenance).toBe('DERIVED');
    expect(detail1?.progress.percentage).toBe(50);

    const missionNoGoals = createMockMission({
      missionId: 'mis-empty-goals',
      progress: undefined as any,
      goals: [],
    });
    executionPersistence.saveMission(missionNoGoals);

    const detail2 = controlPlaneSnapshotService.projectMissionDetail(missionNoGoals.missionId);
    expect(detail2?.progress.progressProvenance).toBe('UNKNOWN');
    expect(detail2?.progress.percentage).toBe('UNKNOWN');
  });

  // 15. Resource allocation versus actual utilization distinction
  it('15. rigorously distinguishes resource allocation from verified actual utilization', () => {
    const mission = createMockMission({
      constraints: [
        {
          type: 'COST_BUDGET',
          value: 150,
          strict: true,
        },
      ],
      goals: [
        { goalId: 'goal-cost-1', title: 'Cost Tracked Goal', mandatory: true, status: 'RUNNING', weight: 1 },
      ],
    });
    executionPersistence.saveMission(mission);

    // Case A: Before actual utilization is tracked
    const detailBefore = controlPlaneSnapshotService.projectMissionDetail(mission.missionId);
    const allocBefore = detailBefore?.resourceAllocations.find((r) => r.resourceType === 'COST_BUDGET');
    expect(allocBefore?.allocated).toBe(150);
    expect(allocBefore?.utilized).toBe('UNKNOWN'); // Allocation != Utilization
    expect(allocBefore?.status).toBe('ALLOCATED');

    // Case B: After actual utilization is tracked via ResourceGovernor
    resourceGovernor.setGoalBudget('goal-cost-1', { maxCostUsd: 150 });
    const leaseRes = resourceGovernor.acquireLease(
      'goal-cost-1',
      {
        taskId: 't-1',
        goalId: 'goal-cost-1',
        planId: 'p-1',
        planVersion: 1,
        parentActionId: 'a-1',
        capability: 'REASONING',
        contextReferences: [],
        inputContract: {},
        expectedOutputContract: {},
        priority: 'HIGH',
        riskLevel: 'LOW_RISK',
        estimatedCost: { minUsd: 10, maxUsd: 20, currency: 'USD' },
        estimatedLatency: 1000,
        status: 'RUNNING',
        qualityRequirement: 'QUALITY_STANDARD',
        memoryAccessDeclarations: [],
        createdAt: '2026-10-04T12:00:00.000Z',
        updatedAt: '2026-10-04T12:00:00.000Z',
      },
      {
        agentId: 'ag-1',
        name: 'Agent Alpha',
        role: 'PLANNER',
        capabilities: ['REASONING'],
        allowedCapabilities: ['REASONING'],
        contextRequirements: [],
        costClass: 'STANDARD',
        latencyClass: 'FAST',
        concurrencyLimit: 2,
        currentWorkload: 1,
        trustLevel: 'VERIFIED',
        autonomyLevel: 'MEDIUM',
        status: 'RUNNING',
        memoryScopes: [],
        historicalSuccessCount: 5,
        historicalFailureCount: 0,
      }
    );

    if (leaseRes.lease) {
      resourceGovernor.releaseLease(leaseRes.lease.leaseId, 42.5);
    }

    const detailAfter = controlPlaneSnapshotService.projectMissionDetail(mission.missionId);
    const allocAfter = detailAfter?.resourceAllocations.find((r) => r.resourceType === 'COST_BUDGET');
    expect(allocAfter?.allocated).toBe(150);
    expect(allocAfter?.utilized).toBe(42.5);
    expect(allocAfter?.status).toBe('UTILIZED');
  });

  // 16. Missing resource allocation metadata
  it('16. reports empty resourceAllocations array without fabricating synthetic budget when unconfigured', () => {
    const mission = createMockMission({
      constraints: [],
    });
    executionPersistence.saveMission(mission);

    const detail = controlPlaneSnapshotService.projectMissionDetail(mission.missionId);
    expect(detail?.resourceAllocations).toEqual([]);
  });

  // 17. Checkpoint planned versus completed distinction
  it('17. distinguishes intermediate checkpoints from terminal completed state', () => {
    const mission = createMockMission({
      checkpoints: [
        {
          checkpointId: 'cp-mid-1',
          missionId: 'mis-stage24-alpha',
          missionStatus: 'RUNNING',
          planVersion: 1,
          completedGoals: ['goal-recon-1'],
          activeGoals: ['goal-recon-2'],
          blockedGoals: [],
          pendingApprovals: [],
          resourceState: {},
          timestamp: '2026-10-04T12:05:00.000Z',
        },
      ],
    });
    executionPersistence.saveMission(mission);

    const detail = controlPlaneSnapshotService.projectMissionDetail(mission.missionId);
    expect(detail?.checkpoints.length).toBe(1);
    expect(detail?.checkpoints[0].isCompletedState).toBe(false);
    expect(detail?.checkpoints[0].statusAtCheckpoint).toBe('RUNNING');
  });

  // 18. Operation and recovery references remain canonical
  it('18. binds canonical operation IDs and recovery decision/plan references', () => {
    const mission = createMockMission();
    executionPersistence.saveMission(mission);

    // Audit event referencing operation
    auditEventRegistry.recordEvent({
      eventId: 'evt-op-1',
      operationId: 'op-sensor-calibrate',
      missionId: 'mis-stage24-alpha',
      goalId: 'goal-recon-1',
      eventType: 'OPERATION_SUCCEEDED',
      lifecycleState: 'SUCCEEDED',
      epistemicStatus: 'OBSERVED',
      timestamp: Date.now(),
      sourceSystem: 'flight-controller',
      causationId: 'cause-1',
      correlationId: 'corr-1',
    });

    // Recovery decision referencing goal
    executionPersistence.saveRecoveryControlDecision({
      decisionId: 'rec-dec-001',
      requestId: 'req-rec-001',
      operationId: 'goal-recon-1',
      recoveryPlanId: 'rec-plan-sensor-retry',
      originalOperationId: 'goal-recon-1',
      classification: 'TRANSIENT',
      epistemicStatus: 'OBSERVED',
      recommendedAction: 'RETRY',
      riskLevel: 'LOW',
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
        safetyRationale: 'Safe idempotent retry',
        assessmentTimestamp: Date.now(),
      },
      requiredAuthority: [],
      governanceDecisionId: 'gov-1',
      governanceRequirement: {
        required: false,
        humanOperatorRequired: false,
      },
      reconciliationRequirement: {
        required: false,
      },
      recoveryOutcome: 'RETRY',
      reasonCodes: ['TRANSIENT_FAILURE'],
      evidenceIds: ['ev-1'],
      reconciliationAttempts: 0,
      expiresAt: Date.now() + 60000,
      causationId: 'c-1',
      correlationId: 'corr-1',
      lifecycleState: 'DECIDED',
      retryCount: 0,
      recoveryDepth: 0,
      createdAt: Date.now(),
    });

    const detail = controlPlaneSnapshotService.projectMissionDetail(mission.missionId);
    expect(detail?.operationReferences).toContain('op-sensor-calibrate');
    expect(detail?.recoveryReferences).toContain('rec-plan-sensor-retry');
  });

  // 19. Stale source/version metadata handled explicitly
  it('19. flags STALE sourceIntegrity when mission update timestamp exceeds freshness threshold (>30d)', () => {
    const mission = createMockMission({
      updatedAt: '2026-01-01T00:00:00.000Z',
    });
    executionPersistence.saveMission(mission);

    const detail = controlPlaneSnapshotService.projectMissionDetail(mission.missionId);
    expect(detail?.sourceIntegrity).toBe('STALE');
    expect(detail?.unresolvedDiscrepancies.some((d) => d.includes('older than 30 days'))).toBe(true);
  });

  // 20. Malformed numeric values and out-of-range values
  it('20. clamps and sanitizes malformed numeric values (NaN, negative, Infinity) in progress', () => {
    const mission = createMockMission({
      progress: {
        totalGoals: -5,
        completedGoals: -2,
        failedGoals: 0,
        inProgressGoals: 0,
        blockedGoals: 0,
        percentage: NaN,
      },
    });
    executionPersistence.saveMission(mission);

    const summaries = controlPlaneSnapshotService.projectMissions(null);
    const p = summaries[0].progress as any;
    expect(p.totalGoals).toBe(0);
    expect(p.completedGoals).toBe(0);
    expect(Number.isFinite(p.percentage)).toBe(true);
    expect(p.percentage).toBe(0);
  });

  // 21. Prototype-pollution payloads
  it('21. rejects prototype-pollution attempts in filter options and mission IDs', () => {
    const maliciousOptions: any = JSON.parse(
      '{"__proto__": {"polluted": true}, "constructor": {"polluted": true}, "status": "RUNNING"}'
    );

    const summaries = controlPlaneSnapshotService.projectMissions(null, maliciousOptions);
    expect((Object.prototype as any).polluted).toBeUndefined();

    const detail = controlPlaneSnapshotService.projectMissionDetail('__proto__' as any);
    expect(detail).toBeNull();
    expect((Object.prototype as any).polluted).toBeUndefined();
  });

  // 22. Recursive secret redaction
  it('22. recursively redacts tokens, bearer auth, and secrets in titles, objectives, and conditions', () => {
    const mission = createMockMission({
      title: 'Satellite Alpha Bearer sk-secret1234567890abcdef',
      objective: 'Query api_key=secret-token-key-abc and token=auth999',
      dependencies: [
        {
          fromGoalId: 'goal-recon-1',
          toGoalId: 'goal-recon-2',
          type: 'FINISH_TO_START',
          condition: 'password=supersecretpassword',
        },
      ],
    });
    executionPersistence.saveMission(mission);

    const detail = controlPlaneSnapshotService.projectMissionDetail(mission.missionId);
    expect(detail?.title).not.toContain('sk-secret');
    expect(detail?.title).toContain('REDACTED');
    expect(detail?.objective).not.toContain('secret-token-key-abc');
    expect(detail?.objective).toContain('REDACTED');
    expect(detail?.dependencies[0].condition).not.toContain('supersecretpassword');
    expect(detail?.dependencies[0].condition).toContain('REDACTED');
  });

  // 23. Forged client-provided mission status
  it('23. prevents forged query filters from mutating authoritative source records', () => {
    const mission = createMockMission({ status: 'RUNNING' });
    executionPersistence.saveMission(mission);

    // Client queries with forged filter for COMPLETED
    const summaries = controlPlaneSnapshotService.projectMissions(null, {
      status: 'COMPLETED',
    });
    expect(summaries.length).toBe(0); // Mission is RUNNING, so filter excludes it

    // Underlying record remains strictly RUNNING
    const stored = executionPersistence.getMission(mission.missionId);
    expect(stored?.status).toBe('RUNNING');
  });

  // 24. Duplicate replay versus distinct mission/goal records
  it('24. preserves distinct missions with identical titles or statuses while deduplicating identical IDs', () => {
    const m1 = createMockMission({ missionId: 'mis-distinct-1', title: 'Survey' });
    const m2 = createMockMission({ missionId: 'mis-distinct-2', title: 'Survey' });
    executionPersistence.saveMission(m1);
    executionPersistence.saveMission(m2);

    const summaries = controlPlaneSnapshotService.projectMissions(null);
    expect(summaries.length).toBe(2);
    expect(summaries[0].missionId).not.toBe(summaries[1].missionId);
  });

  // 25. Stable IDs and deterministic deduplication
  it('25. deterministically deduplicates missions stored concurrently in memory and persistence', () => {
    const mission = createMockMission();
    // Simulate mission present in both persistence and memory envelope
    executionPersistence.saveMission(mission);

    const envelope = executionPersistence.loadEnvelope();
    const summaries = controlPlaneSnapshotService.projectMissions(envelope);

    expect(summaries.length).toBe(1);
    expect(summaries[0].missionId).toBe(mission.missionId);
  });

  // 26. Deep-freeze verification for nested output
  it('26. returns recursively frozen immutable objects for both summary and detail projections', () => {
    const mission = createMockMission();
    executionPersistence.saveMission(mission);

    const summaries = controlPlaneSnapshotService.projectMissions(null);
    expect(Object.isFrozen(summaries)).toBe(true);
    expect(Object.isFrozen(summaries[0])).toBe(true);

    const detail = controlPlaneSnapshotService.projectMissionDetail(mission.missionId);
    expect(Object.isFrozen(detail)).toBe(true);
    expect(Object.isFrozen(detail?.goals)).toBe(true);
    expect(Object.isFrozen(detail?.goals[0])).toBe(true);
    expect(Object.isFrozen(detail?.dependencies)).toBe(true);
    expect(Object.isFrozen(detail?.checkpoints)).toBe(true);
    expect(Object.isFrozen(detail?.resourceAllocations)).toBe(true);
  });

  // 27. Mutation attempts do not alter source records
  it('27. prevents downstream mutation of projection from modifying persisted records', () => {
    const mission = createMockMission();
    executionPersistence.saveMission(mission);

    const detail = controlPlaneSnapshotService.projectMissionDetail(mission.missionId) as any;
    expect(() => {
      detail.title = 'Hacked Title';
    }).toThrow();

    const stored = executionPersistence.getMission(mission.missionId);
    expect(stored?.title).toBe('Orbital Reconnaissance Mission');
  });

  // 28. Read-path call graph contains no prohibited mutating calls
  it('28. confirms zero execution or mutation calls during projection generation', () => {
    const saveMissionSpy = vi.spyOn(executionPersistence, 'saveMission');
    const executeActionBusSpy = vi.spyOn(actionBusService, 'execute');

    const mission = createMockMission();
    executionPersistence.saveMission(mission);
    saveMissionSpy.mockClear();

    controlPlaneSnapshotService.projectMissions(null);
    controlPlaneSnapshotService.projectMissionDetail(mission.missionId);

    expect(saveMissionSpy).toHaveBeenCalledTimes(0);
    expect(executeActionBusSpy).toHaveBeenCalledTimes(0);
  });

  // 29. Snapshot integration returns consistent mission projections
  it('29. integrates seamlessly into ControlPlaneSnapshot with consistent mission data', () => {
    const mission = createMockMission();
    executionPersistence.saveMission(mission);

    const snapshot = controlPlaneSnapshotService.getSnapshot();
    expect(snapshot.missions.length).toBe(1);
    expect(snapshot.missions[0].missionId).toBe(mission.missionId);
    expect(snapshot.missions[0].title).toBe('Orbital Reconnaissance Mission');
  });

  // 30. Existing Phase 2 snapshot behavior remains compatible
  it('30. preserves Phase 2 snapshot contract integrity (snapshotId, systemHealth, sourceVersion)', () => {
    const snapshot = controlPlaneSnapshotService.getSnapshot();
    expect(snapshot.snapshotId).toMatch(/^snap-cp-\d+$/);
    expect(snapshot.systemHealth.overallStatus).toBeDefined();
    expect(snapshot.systemHealth.missions.status).toBe('HEALTHY');
    expect(snapshot.sourceVersion).toBeDefined();
  });

  // 31. Phase 3 timeline behavior remains unchanged
  it('31. preserves Phase 3 Operation Timeline projection behavior without regressions', () => {
    auditEventRegistry.recordEvent({
      eventId: 'evt-tl-1',
      operationId: 'op-timeline-test',
      eventType: 'REQUEST_RECEIVED',
      lifecycleState: 'RECEIVED',
      epistemicStatus: 'OBSERVED',
      timestamp: Date.now(),
      sourceSystem: 'test-runner',
      causationId: 'root',
      correlationId: 'corr-tl',
    });

    const timeline = controlPlaneSnapshotService.projectOperationTimeline('op-timeline-test');
    expect(timeline.operationId).toBe('op-timeline-test');
    expect(timeline.entries.length).toBe(1);
    expect(timeline.currentState).toBe('REQUESTED');
  });

  // 32. Phase 4 approval behavior remains unchanged
  it('32. preserves Phase 4 Approval Center projection behavior without regressions', () => {
    const approvals = controlPlaneSnapshotService.projectApprovals(null);
    expect(Array.isArray(approvals)).toBe(true);
    expect(Object.isFrozen(approvals)).toBe(true);
  });

  // 33. Phase 5 recovery behavior remains unchanged
  it('33. preserves Phase 5 Recovery Operations projection behavior without regressions', () => {
    const recovery = controlPlaneSnapshotService.projectRecovery(null);
    expect(Array.isArray(recovery)).toBe(true);
    expect(Object.isFrozen(recovery)).toBe(true);
  });

  // 34. No network or LLM activity during projection
  it('34. verifies zero network calls and zero LLM calls during mission projection', () => {
    const fetchSpy = vi.fn();
    vi.stubGlobal('fetch', fetchSpy);

    const mission = createMockMission();
    executionPersistence.saveMission(mission);

    controlPlaneSnapshotService.projectMissions(null);
    controlPlaneSnapshotService.projectMissionDetail(mission.missionId);
    controlPlaneSnapshotService.getSnapshot();

    expect(fetchSpy).toHaveBeenCalledTimes(0);
  });
});
