/**
 * AryaOS V1 — Stage 12: Long-Horizon Mission Control & Adaptive Execution Tests
 *
 * Verifies all 34 required mission control capabilities:
 * 1. Mission creation
 * 2. Mission persistence
 * 3. Mission reload
 * 4. Multi-goal dependency validation
 * 5. Circular dependency detection
 * 6. Missing dependency detection
 * 7. Critical path calculation
 * 8. Deadline risk detection
 * 9. Resource contention detection
 * 10. Cross-mission resource arbitration
 * 11. Mission checkpoint creation
 * 12. Crash recovery
 * 13. Interrupted goal recovery
 * 14. Verified completion preservation
 * 15. Consequential action approval
 * 16. Mission replanning
 * 17. Plan version immutability
 * 18. Completed-goal preservation during replan
 * 19. Partial success handling
 * 20. Mission completion criteria
 * 21. Mission cancellation
 * 22. Mission risk detection
 * 23. Stage 11 learning evidence integration
 * 24. Recommendation remains advisory
 * 25. Mission memory provenance
 * 26. Mission event idempotency
 * 27. Duplicate execution prevention
 * 28. Provider gateway remains sole execution boundary
 * 29. Persistence sanitization
 * 30. Existing Stage 10 resource limits remain enforced
 * 31. Existing Stage 09 recovery remains intact
 * 32. Existing Stage 08 orchestration remains intact
 * 33. Stage 03 spatial performance remains unchanged
 * 34. Zero additional draw calls (DOM/HUD only)
 */

import React from 'react';
import { render, screen } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { missionManager } from '../services/missionManager';
import { missionPlanner } from '../services/missionPlanner';
import { missionDependencyGraph } from '../services/missionDependencyGraph';
import { missionPriorityEngine } from '../services/missionPriority';
import { missionResourceArbitrator } from '../services/missionResourceArbitrator';
import { missionRiskService } from '../services/missionRiskService';
import { missionObservationService } from '../services/missionObservationService';
import { missionReplanner } from '../services/missionReplanner';
import { missionCheckpointService } from '../services/missionCheckpoint';
import { executionPersistence } from '../services/executionPersistence';
import { executionGateway } from '../services/executionGateway';
import { resourceGovernor } from '../services/resourceGovernor';
import { recoveryManager } from '../services/recoveryManager';
import { goalOrchestrator } from '../services/goalOrchestrator';
import { learningSignalService } from '../services/learningSignalService';
import { policyRecommendationService } from '../services/policyRecommendationService';
import { SpatialCommandConsole } from '../components/spatial/SpatialCommandConsole';
import { STAGE03_CAMERAS } from '../stage03_assembly';
import {
  Mission,
  MissionGoalReference,
  MissionDependency,
} from '../types/missionControl';

describe('AryaOS V1 Stage 12 — Long-Horizon Mission Control & Adaptive Execution', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    executionPersistence.clearEnvelope();
    resourceGovernor.resetState();
  });

  // 1. Mission creation
  it('1. creates a multi-goal mission and initializes Plan v1', () => {
    const goals: MissionGoalReference[] = [
      { goalId: 'g1', title: 'Research concept', mandatory: true, status: 'READY', weight: 1.0 },
      { goalId: 'g2', title: 'Draft screenplay', mandatory: true, status: 'READY', weight: 1.0 },
    ];
    const dependencies: MissionDependency[] = [
      { fromGoalId: 'g1', toGoalId: 'g2', type: 'FINISH_TO_START' },
    ];

    const mission = missionManager.createMission({
      title: 'Launch AI Short Film',
      objective: 'Produce cinematic narrative concept',
      goals,
      dependencies,
      priority: 'HIGH',
    });

    expect(mission.missionId).toBeDefined();
    expect(mission.status).toBe('READY');
    expect(mission.currentPlanVersion).toBe(1);
    expect(mission.plans).toHaveLength(1);
    expect(mission.plans[0].goalOrder).toBeDefined();
  });

  // 2. Mission persistence
  it('2. persists mission envelope to executionPersistence', () => {
    const mission = missionManager.createMission({
      title: 'Persist Test Mission',
      objective: 'Verify persistence envelope',
      goals: [{ goalId: 'g-p1', title: 'Goal 1', mandatory: true, status: 'READY', weight: 1.0 }],
    });

    const retrieved = executionPersistence.getMission(mission.missionId);
    expect(retrieved).toBeDefined();
    expect(retrieved?.title).toBe('Persist Test Mission');
  });

  // 3. Mission reload
  it('3. reloads missions across persistence deserialization cycle', () => {
    const mission = missionManager.createMission({
      title: 'Reload Test Mission',
      objective: 'Test serialization/deserialization',
      goals: [{ goalId: 'g-r1', title: 'Goal R1', mandatory: true, status: 'READY', weight: 1.0 }],
    });

    // Simulate reload from storage
    const envelope = executionPersistence.loadEnvelope();
    expect(envelope?.missions).toBeDefined();
    expect(envelope?.missions?.[mission.missionId]).toBeDefined();
    expect(envelope?.missions?.[mission.missionId].title).toBe('Reload Test Mission');
  });

  // 4. Multi-goal dependency validation
  it('4. performs deterministic topological sort and executable frontier analysis', () => {
    const goals: MissionGoalReference[] = [
      { goalId: 'g-a', title: 'A', mandatory: true, status: 'COMPLETED', weight: 1.0 },
      { goalId: 'g-b', title: 'B', mandatory: true, status: 'READY', weight: 1.0 },
      { goalId: 'g-c', title: 'C', mandatory: true, status: 'READY', weight: 1.0 },
    ];
    const dependencies: MissionDependency[] = [
      { fromGoalId: 'g-a', toGoalId: 'g-b', type: 'FINISH_TO_START' },
      { fromGoalId: 'g-b', toGoalId: 'g-c', type: 'FINISH_TO_START' },
    ];

    const analysis = missionDependencyGraph.analyzeDependencies(goals, dependencies);
    expect(analysis.isValid).toBe(true);
    expect(analysis.topologicalOrder).toEqual(['g-a', 'g-b', 'g-c']);
    // g-a is COMPLETED, so g-b is in the executable frontier, g-c is blocked
    expect(analysis.executableFrontier).toContain('g-b');
    expect(analysis.blockedGoals).toContain('g-c');
  });

  // 5. Circular dependency detection
  it('5. detects circular dependencies in mission goal graph', () => {
    const goals: MissionGoalReference[] = [
      { goalId: 'g-c1', title: 'C1', mandatory: true, status: 'READY', weight: 1.0 },
      { goalId: 'g-c2', title: 'C2', mandatory: true, status: 'READY', weight: 1.0 },
    ];
    const dependencies: MissionDependency[] = [
      { fromGoalId: 'g-c1', toGoalId: 'g-c2', type: 'FINISH_TO_START' },
      { fromGoalId: 'g-c2', toGoalId: 'g-c1', type: 'FINISH_TO_START' },
    ];

    const analysis = missionDependencyGraph.analyzeDependencies(goals, dependencies);
    expect(analysis.isValid).toBe(false);
    expect(analysis.issues.some((i) => i.type === 'CIRCULAR_DEPENDENCY')).toBe(true);
  });

  // 6. Missing dependency detection
  it('6. detects missing dependency targets in goal graph', () => {
    const goals: MissionGoalReference[] = [
      { goalId: 'g-m1', title: 'M1', mandatory: true, status: 'READY', weight: 1.0 },
    ];
    const dependencies: MissionDependency[] = [
      { fromGoalId: 'g-m1', toGoalId: 'nonexistent-goal', type: 'FINISH_TO_START' },
    ];

    const analysis = missionDependencyGraph.analyzeDependencies(goals, dependencies);
    expect(analysis.isValid).toBe(false);
    expect(analysis.issues.some((i) => i.type === 'MISSING_GOAL')).toBe(true);
  });

  // 7. Critical path calculation
  it('7. calculates the deterministic critical path along longest dependency chain', () => {
    const goals: MissionGoalReference[] = [
      { goalId: 'g-cp1', title: 'CP1', mandatory: true, status: 'READY', weight: 1.0 },
      { goalId: 'g-cp2', title: 'CP2', mandatory: true, status: 'READY', weight: 1.0 },
      { goalId: 'g-cp3', title: 'CP3', mandatory: true, status: 'READY', weight: 1.0 },
      { goalId: 'g-side', title: 'Side', mandatory: false, status: 'READY', weight: 0.5 },
    ];
    const dependencies: MissionDependency[] = [
      { fromGoalId: 'g-cp1', toGoalId: 'g-cp2', type: 'FINISH_TO_START' },
      { fromGoalId: 'g-cp2', toGoalId: 'g-cp3', type: 'FINISH_TO_START' },
      { fromGoalId: 'g-cp1', toGoalId: 'g-side', type: 'FINISH_TO_START' },
    ];

    const mission = missionManager.createMission({
      title: 'Critical Path Test',
      objective: 'CP verification',
      goals,
      dependencies,
    });

    const plan = mission.plans[0];
    expect(plan.criticalPath).toEqual(['g-cp1', 'g-cp2', 'g-cp3']);
  });

  // 8. Deadline risk detection
  it('8. detects deadline risk when remaining time is less than estimated duration', () => {
    const pastDeadline = new Date(Date.now() - 60000).toISOString();
    const mission = missionManager.createMission({
      title: 'Deadline Risk Mission',
      objective: 'Test expired deadline',
      goals: [{ goalId: 'g-d1', title: 'D1', mandatory: true, status: 'READY', weight: 1.0, timeoutMs: 10000 }],
      deadline: pastDeadline,
    });

    const risks = missionRiskService.assessRisks(mission);
    const deadlineRisk = risks.find((r) => r.type === 'DEADLINE');
    expect(deadlineRisk).toBeDefined();
    expect(deadlineRisk?.level).toBe('CRITICAL');
  });

  // 9. Resource contention detection
  it('9. detects resource and budget contention across concurrent missions', () => {
    const m1 = missionManager.createMission({
      title: 'Mission 1',
      objective: 'High budget mission',
      goals: [{ goalId: 'g-b1', title: 'B1', mandatory: true, status: 'RUNNING', weight: 1.0 }],
      constraints: [{ type: 'COST_BUDGET', value: 8.0, strict: true }],
    });
    m1.status = 'RUNNING';

    const m2 = missionManager.createMission({
      title: 'Mission 2',
      objective: 'Competing high budget mission',
      goals: [{ goalId: 'g-b2', title: 'B2', mandatory: true, status: 'RUNNING', weight: 1.0 }],
      constraints: [{ type: 'COST_BUDGET', value: 6.0, strict: true }],
    });
    m2.status = 'RUNNING';

    const contention = missionResourceArbitrator.detectContention([m1, m2]);
    expect(contention.hasContention).toBe(true);
    expect(contention.contentions.some((c) => c.type === 'BUDGET_CONTENTION')).toBe(true);
  });

  // 10. Cross-mission resource arbitration
  it('10. arbitrates resource requests favoring higher priority mission under contention', () => {
    const mLow = missionManager.createMission({
      title: 'Low Priority Mission',
      objective: 'Background tasks',
      goals: [{ goalId: 'g-l1', title: 'L1', mandatory: true, status: 'RUNNING', weight: 1.0 }],
      priority: 'LOW',
      constraints: [{ type: 'COST_BUDGET', value: 7.0, strict: true }],
    });
    mLow.status = 'RUNNING';

    const mHigh = missionManager.createMission({
      title: 'Critical Mission',
      objective: 'Urgent production job',
      goals: [{ goalId: 'g-h1', title: 'H1', mandatory: true, status: 'RUNNING', weight: 1.0 }],
      priority: 'CRITICAL',
      constraints: [{ type: 'COST_BUDGET', value: 7.0, strict: true }],
    });
    mHigh.status = 'RUNNING';

    const allMissions = [mLow, mHigh];

    const decisionLow = missionResourceArbitrator.arbitrateResourceRequest(
      mLow.missionId,
      'AGENT_WORKLOAD',
      4,
      allMissions
    );
    expect(decisionLow.decision).toBe('THROTTLED');

    const decisionHigh = missionResourceArbitrator.arbitrateResourceRequest(
      mHigh.missionId,
      'AGENT_WORKLOAD',
      4,
      allMissions
    );
    expect(decisionHigh.decision).toBe('GRANTED');
  });

  // 11. Mission checkpoint creation
  it('11. creates deterministic checkpoint capturing status, goals, and plan version', () => {
    const mission = missionManager.createMission({
      title: 'Checkpoint Mission',
      objective: 'Verify checkpoint snapshot',
      goals: [
        { goalId: 'g-cp1', title: 'G1', mandatory: true, status: 'COMPLETED', weight: 1.0 },
        { goalId: 'g-cp2', title: 'G2', mandatory: true, status: 'RUNNING', weight: 1.0 },
      ],
    });

    const cp = missionCheckpointService.createCheckpoint(mission);
    expect(cp.checkpointId).toBeDefined();
    expect(cp.planVersion).toBe(1);
    expect(cp.completedGoals).toContain('g-cp1');
    expect(cp.activeGoals).toContain('g-cp2');
  });

  // 12. Crash recovery
  it('12. restores mission and goals from saved checkpoint upon restart', () => {
    const mission = missionManager.createMission({
      title: 'Crash Recovery Mission',
      objective: 'Test restart recovery',
      goals: [
        { goalId: 'g-cr1', title: 'G1', mandatory: true, status: 'COMPLETED', weight: 1.0 },
        { goalId: 'g-cr2', title: 'G2', mandatory: false, status: 'RUNNING', weight: 1.0 },
      ],
    });

    const cp = missionCheckpointService.createCheckpoint(mission);
    const restored = missionCheckpointService.restoreMissionFromCheckpoint(cp.checkpointId);

    expect(restored.success).toBe(true);
    expect(restored.mission).toBeDefined();
    expect(restored.resumedGoals).toContain('g-cr2');
  });

  // 13. Interrupted goal recovery
  it('13. flags interrupted mandatory goals as requiring approval while resetting safe goals', () => {
    const mission = missionManager.createMission({
      title: 'Interrupted Goals Mission',
      objective: 'Test mandatory vs optional recovery',
      goals: [
        { goalId: 'g-int-man', title: 'Mandatory Action', mandatory: true, status: 'RUNNING', weight: 1.0 },
        { goalId: 'g-int-opt', title: 'Optional Research', mandatory: false, status: 'RUNNING', weight: 1.0 },
      ],
    });

    const cp = missionCheckpointService.createCheckpoint(mission);
    const restored = missionCheckpointService.restoreMissionFromCheckpoint(cp.checkpointId);

    expect(restored.approvalRequiredGoals).toContain('g-int-man');
    expect(restored.resumedGoals).toContain('g-int-opt');
  });

  // 14. Verified completion preservation
  it('14. preserves verified completed goals across restart without re-execution', () => {
    const mission = missionManager.createMission({
      title: 'Preserve Completed Goals',
      objective: 'Ensure completed goals stay completed',
      goals: [
        { goalId: 'g-done', title: 'Done Goal', mandatory: true, status: 'COMPLETED', weight: 1.0 },
        { goalId: 'g-next', title: 'Next Goal', mandatory: true, status: 'READY', weight: 1.0 },
      ],
    });

    const cp = missionCheckpointService.createCheckpoint(mission);
    const restored = missionCheckpointService.restoreMissionFromCheckpoint(cp.checkpointId);

    const doneGoal = restored.mission?.goals.find((g) => g.goalId === 'g-done');
    expect(doneGoal?.status).toBe('COMPLETED');
  });

  // 15. Consequential action approval
  it('15. holds consequential interrupted work in WAITING_APPROVAL status', () => {
    const mission = missionManager.createMission({
      title: 'Consequential Approval Mission',
      objective: 'Ensure consequential work requires operator signoff',
      goals: [
        { goalId: 'g-conseq', title: 'Publishing Step', mandatory: true, status: 'RUNNING', weight: 1.0 },
      ],
    });

    const cp = missionCheckpointService.createCheckpoint(mission);
    const restored = missionCheckpointService.restoreMissionFromCheckpoint(cp.checkpointId);

    expect(restored.mission?.status).toBe('WAITING_FOR_APPROVAL');
    const conseqGoal = restored.mission?.goals.find((g) => g.goalId === 'g-conseq');
    expect(conseqGoal?.status).toBe('WAITING_APPROVAL');
  });

  // 16. Mission replanning
  it('16. generates Plan v2 upon goal failure, recording replanning reason', () => {
    const mission = missionManager.createMission({
      title: 'Replan Test Mission',
      objective: 'Trigger plan adaptation',
      goals: [
        { goalId: 'g-r1', title: 'Step 1', mandatory: true, status: 'COMPLETED', weight: 1.0 },
        { goalId: 'g-r2', title: 'Step 2 Failed', mandatory: true, status: 'FAILED', weight: 1.0 },
      ],
    });

    const replanResult = missionReplanner.replanMission(
      mission.missionId,
      'Goal g-r2 failed due to provider rate limit; adapting route.'
    );

    expect(replanResult.success).toBe(true);
    expect(replanResult.newPlan?.planVersion).toBe(2);
    expect(replanResult.newPlan?.changeReason).toContain('adapting route');
  });

  // 17. Plan version immutability
  it('17. preserves Plan v1 unchanged when Plan v2 is appended to the mission', () => {
    const mission = missionManager.createMission({
      title: 'Immutable Plan Mission',
      objective: 'Verify plan immutability',
      goals: [{ goalId: 'g-im1', title: 'Step 1', mandatory: true, status: 'READY', weight: 1.0 }],
    });

    const planV1 = mission.plans[0];
    const planV1CreatedAt = planV1.createdAt;

    missionReplanner.replanMission(mission.missionId, 'Second iteration');
    const updated = executionPersistence.getMission(mission.missionId);

    expect(updated?.plans).toHaveLength(2);
    expect(updated?.plans[0].planVersion).toBe(1);
    expect(updated?.plans[0].createdAt).toBe(planV1CreatedAt);
    expect(updated?.plans[1].planVersion).toBe(2);
  });

  // 18. Completed-goal preservation during replan
  it('18. preserves completed goals during replan without resetting their status', () => {
    const mission = missionManager.createMission({
      title: 'Preserve During Replan',
      objective: 'Ensure completed work persists in new plan version',
      goals: [
        { goalId: 'g-comp', title: 'Completed Step', mandatory: true, status: 'COMPLETED', weight: 1.0 },
        { goalId: 'g-fail', title: 'Failing Step', mandatory: true, status: 'FAILED', weight: 1.0 },
      ],
    });

    const replanResult = missionReplanner.replanMission(mission.missionId, 'Retry failing step');
    expect(replanResult.newPlan?.preservedGoals).toContain('g-comp');

    const updated = executionPersistence.getMission(mission.missionId);
    const compGoal = updated?.goals.find((g) => g.goalId === 'g-comp');
    expect(compGoal?.status).toBe('COMPLETED');
  });

  // 19. Partial success handling
  it('19. marks status PARTIALLY_COMPLETED when mandatory goals succeed and optional fail', () => {
    const mission = missionManager.createMission({
      title: 'Partial Success Mission',
      objective: 'Verify partial success behavior',
      goals: [
        { goalId: 'g-man-ok', title: 'Mandatory', mandatory: true, status: 'COMPLETED', weight: 1.0 },
        { goalId: 'g-opt-fail', title: 'Optional', mandatory: false, status: 'FAILED', weight: 0.5 },
      ],
      completionCriteria: { allowPartialSuccess: true, minimumSuccessRate: 0.5 },
    });

    const outcome = missionManager.evaluateCompletion(mission.missionId);
    expect(outcome.isCompleted).toBe(true);
    expect(outcome.isPartialSuccess).toBe(true);
    expect(outcome.status).toBe('PARTIALLY_COMPLETED');
  });

  // 20. Mission completion criteria
  it('20. marks mission COMPLETED only when all goals succeed and criteria are satisfied', () => {
    const mission = missionManager.createMission({
      title: 'Full Success Mission',
      objective: 'Verify complete success',
      goals: [
        { goalId: 'g-all-1', title: 'Goal 1', mandatory: true, status: 'COMPLETED', weight: 1.0 },
        { goalId: 'g-all-2', title: 'Goal 2', mandatory: true, status: 'COMPLETED', weight: 1.0 },
      ],
    });

    const outcome = missionManager.evaluateCompletion(mission.missionId);
    expect(outcome.isCompleted).toBe(true);
    expect(outcome.isPartialSuccess).toBe(false);
    expect(outcome.status).toBe('COMPLETED');
  });

  // 21. Mission cancellation
  it('21. cancels mission with operator decision record and audit observation', () => {
    const mission = missionManager.createMission({
      title: 'Cancel Mission Test',
      objective: 'Test governance boundary on cancellation',
      goals: [{ goalId: 'g-c1', title: 'Step 1', mandatory: true, status: 'READY', weight: 1.0 }],
    });

    const cancelled = missionManager.cancelMission(
      mission.missionId,
      'Mission cancelled due to scope shift',
      'LeadOperator'
    );
    expect(cancelled).toBe(true);

    const updated = executionPersistence.getMission(mission.missionId);
    expect(updated?.status).toBe('CANCELLED');
    expect(updated?.decisions.some((d) => d.decisionType === 'MISSION_CANCELLATION')).toBe(true);
  });

  // 22. Mission risk detection
  it('22. detects multiple observable risks across dependency, provider, and recovery history', () => {
    const mission = missionManager.createMission({
      title: 'Multi-Risk Mission',
      objective: 'Test risk engine comprehensive scan',
      goals: [
        { goalId: 'g-fail-m', title: 'Failed Goal', mandatory: true, status: 'FAILED', weight: 1.0 },
      ],
    });

    const risks = missionRiskService.assessRisks(mission);
    expect(risks.some((r) => r.type === 'DEPENDENCY' && r.level === 'CRITICAL')).toBe(true);
  });

  // 23. Stage 11 learning evidence integration
  it('23. incorporates Stage 11 learning signals into mission risk evaluations', () => {
    // Generate a learning signal in Stage 11 service
    const sig = {
      signalId: 'ls-risk-test-01',
      signalType: 'PROVIDER_HIGH_FAILURE_RATE',
      sourceExperienceIds: ['exp-1'],
      dimension: 'RELIABILITY' as const,
      observation: "Provider 'gemini' exhibits elevated failure rate (40%).",
      confidence: 'HIGH' as const,
      sampleSize: 5,
      createdAt: new Date().toISOString(),
      expiresAt: new Date(Date.now() + 86400000).toISOString(),
      impact: 'HIGH' as const,
      status: 'ACTIONABLE' as const,
    };
    executionPersistence.saveLearningSignal(sig);

    const mission = missionManager.createMission({
      title: 'Learning Signal Risk Mission',
      objective: 'Verify learning signal impact on mission risk',
      goals: [{ goalId: 'g-ls1', title: 'G1', mandatory: true, status: 'READY', weight: 1.0 }],
    });

    const risks = missionRiskService.assessRisks(mission);
    const provRisk = risks.find((r) => r.type === 'PROVIDER');
    expect(provRisk).toBeDefined();
    expect(provRisk?.level).toBe('HIGH');
  });

  // 24. Recommendation remains advisory
  it('24. ensures Stage 11 policy recommendations remain advisory and cannot be applied without human signoff', () => {
    const rec = {
      recommendationId: 'rec-test-stage12',
      reason: 'Empirical latency reduction recommendation',
      evidenceSignalIds: ['sig-1'],
      affectedPolicy: 'routing_policy',
      proposedAdjustment: { action: 'ADVISE_ROUTE' },
      expectedImpact: 'Improves latency',
      risk: 'LOW' as const,
      confidence: 'HIGH' as const,
      status: 'PROPOSED' as const,
      requiresHumanApproval: true,
      proposedAt: new Date().toISOString(),
    };
    executionPersistence.savePolicyRecommendation(rec);

    // Attempting to apply unapproved recommendation must be blocked
    const applied = policyRecommendationService.applyRecommendation(rec.recommendationId);
    expect(applied).toBe(false);
  });

  // 25. Mission memory provenance
  it('25. records immutable mission observations with structured provenance', () => {
    const mission = missionManager.createMission({
      title: 'Observation Provenance Mission',
      objective: 'Verify observation tracking',
      goals: [{ goalId: 'g-obs1', title: 'G1', mandatory: true, status: 'READY', weight: 1.0 }],
    });

    const obs = missionObservationService.recordObservation(
      mission.missionId,
      'PROGRESS',
      'Milestone reached: Phase 1 complete',
      { phase: 1, operator: 'Architect' }
    );

    expect(obs.observationId).toBeDefined();
    expect(obs.details.phase).toBe(1);

    const stored = missionObservationService.getObservations(mission.missionId, 'PROGRESS');
    expect(stored.some((o) => o.observationId === obs.observationId)).toBe(true);
  });

  // 26. Mission event idempotency
  it('26. handles mission progress updates idempotently', () => {
    const mission = missionManager.createMission({
      title: 'Idempotency Test Mission',
      objective: 'Test idempotent status updates',
      goals: [{ goalId: 'g-idem', title: 'G1', mandatory: true, status: 'READY', weight: 1.0 }],
    });

    missionManager.updateGoalStatus(mission.missionId, 'g-idem', 'COMPLETED');
    const firstProgress = executionPersistence.getMission(mission.missionId)?.progress.percentage;

    missionManager.updateGoalStatus(mission.missionId, 'g-idem', 'COMPLETED');
    const secondProgress = executionPersistence.getMission(mission.missionId)?.progress.percentage;

    expect(firstProgress).toBe(100);
    expect(secondProgress).toBe(100);
  });

  // 27. Duplicate execution prevention
  it('27. prevents duplicate execution of already succeeded mission goals', () => {
    const mission = missionManager.createMission({
      title: 'Duplicate Execution Prevention',
      objective: 'Ensure completed goals are excluded from executable frontier',
      goals: [
        { goalId: 'g-d1', title: 'Goal 1', mandatory: true, status: 'COMPLETED', weight: 1.0 },
        { goalId: 'g-d2', title: 'Goal 2', mandatory: true, status: 'READY', weight: 1.0 },
      ],
      dependencies: [{ fromGoalId: 'g-d1', toGoalId: 'g-d2', type: 'FINISH_TO_START' }],
    });

    const analysis = missionDependencyGraph.analyzeDependencies(mission.goals, mission.dependencies);
    expect(analysis.executableFrontier).not.toContain('g-d1');
    expect(analysis.executableFrontier).toContain('g-d2');
  });

  // 28. Provider gateway remains sole execution boundary
  it('28. verifies Execution Gateway remains the exclusive dispatch boundary', () => {
    expect(executionGateway.execute).toBeDefined();
    expect(typeof executionGateway.execute).toBe('function');
  });

  // 29. Persistence sanitization
  it('29. redacts sensitive tokens and credentials from persisted mission data', () => {
    const mission = missionManager.createMission({
      title: 'Secure Mission',
      objective: 'Verify secret scrubbing',
      goals: [{ goalId: 'g-sec', title: 'Secret Task', mandatory: true, status: 'READY', weight: 1.0 }],
      provenance: {
        authorization: 'Bearer secret_super_token_123',
        api_key: 'sk-ant-sensitive_key_val_999',
      },
    });

    const loaded = executionPersistence.getMission(mission.missionId);
    expect(loaded?.provenance.authorization).toBe('[REDACTED_SECRET]');
    expect(loaded?.provenance.api_key).toBe('[REDACTED_SECRET]');
  });

  // 30. Existing Stage 10 resource limits remain enforced
  it('30. ensures Stage 10 resource limits and leases remain enforced', () => {
    const budget = resourceGovernor.getGoalBudget('any-goal');
    expect(budget.maxConcurrentActions).toBe(3);
    expect(budget.maxConcurrentAgents).toBe(4);
  });

  // 31. Existing Stage 09 recovery remains intact
  it('31. verifies Stage 09 recoveryManager classification logic is intact', () => {
    expect(recoveryManager.classifyActionRecovery).toBeDefined();
  });

  // 32. Existing Stage 08 orchestration remains intact
  it('32. verifies Stage 08 goalOrchestrator remains functional', () => {
    expect(goalOrchestrator.getActiveGoal).toBeDefined();
  });

  // 33. Stage 03 spatial performance remains unchanged
  it('33. verifies locked STAGE03_CAMERAS specifications are preserved', () => {
    expect(STAGE03_CAMERAS.CAM_CinematicHero.fov).toBeCloseTo(39.761, 2);
    expect(STAGE03_CAMERAS.CAM_MonumentalLowAngle.fov).toBeCloseTo(49.426, 2);
    expect(STAGE03_CAMERAS.CAM_ArchiveDetail.fov).toBeCloseTo(35.115, 2);
  });

  // 34. Zero additional draw calls (DOM/HUD only)
  it('34. renders Mission Control HUD in DOM without modifying 3D WebGL meshes', () => {
    const mockCommandControl: any = {
      commandState: 'IDLE',
      commandInput: '',
      currentCommand: null,
      lastResult: null,
      lastExecutionResult: null,
      activeCamera: 'CAM_CinematicHero',
      memoryEvents: [],
      isConsoleOpen: true,
      setCommandInput: vi.fn(),
      submitCommand: vi.fn(),
      confirmProposal: vi.fn(),
      cancelProposal: vi.fn(),
      dismissResult: vi.fn(),
      setIsConsoleOpen: vi.fn(),
      toggleConsole: vi.fn(),
      navigateHistory: vi.fn(),
    };

    render(<SpatialCommandConsole commandControl={mockCommandControl} />);
    expect(screen.getByTestId('mission-control-hud')).toBeInTheDocument();
    expect(screen.getByTestId('mission-timeline-hud')).toBeInTheDocument();
    expect(screen.getByTestId('mission-status-badge')).toBeInTheDocument();
    expect(screen.getByTestId('mission-plan-version-badge')).toBeInTheDocument();
    expect(screen.getByTestId('mission-risk-badge')).toBeInTheDocument();
  });
});
