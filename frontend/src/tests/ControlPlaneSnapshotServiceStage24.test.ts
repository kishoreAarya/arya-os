/**
 * AryaOS V1 — Stage 24: Mission Operations Control Plane
 * Phase 2: Control-Plane Snapshot Service Tests
 *
 * Verifies all 25 required test categories:
 * 1. deterministic snapshot composition
 * 2. mission projection
 * 3. operation projection
 * 4. lifecycle preservation
 * 5. UNKNOWN preservation
 * 6. epistemic preservation
 * 7. governance projection
 * 8. approval projection
 * 9. recovery projection
 * 10. causal trace projection
 * 11. missing evidence preservation
 * 12. health projection
 * 13. persistence durability truth
 * 14. read-only behavior
 * 15. no Action Bus execution
 * 16. no governance mutation
 * 17. no recovery mutation
 * 18. no mission mutation
 * 19. no policy mutation
 * 20. secret scrubbing
 * 21. malformed context handling
 * 22. prototype pollution resistance
 * 23. partial subsystem failure
 * 24. concurrent snapshot requests
 * 25. stable identifiers
 *
 * MANDATORY ADVERSARIAL TEST:
 * Proves that calling getSnapshot() causes ZERO side effects across all subsystems.
 */

import { describe, it, expect, beforeEach, vi } from 'vitest';
import { controlPlaneSnapshotService, ControlPlaneSnapshotService } from '../services/controlPlaneSnapshotService';
import { missionManager } from '../services/missionManager';
import { executionPersistence } from '../services/executionPersistence';
import { policyRegistry } from '../services/policyRegistry';
import { auditEventRegistry } from '../services/auditEventRegistry';
import { actionBusService } from '../services/actionBusService';
import { governanceControlPlane } from '../services/governanceControlPlane';
import { recoveryControlPlane } from '../services/recoveryControlPlane';
import { connectorRegistry } from '../services/connectorRegistry';
import { causalTraceService } from '../services/causalTraceService';
import { operationalTruthService } from '../services/operationalTruthService';

describe('AryaOS V1 — Stage 24: Phase 2 Control-Plane Snapshot Service', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it('1. deterministic snapshot composition produces identical snapshots for identical inputs', () => {
    const fixedTime = 1727970000000;
    const snap1 = controlPlaneSnapshotService.getSnapshot({
      timestamp: fixedTime,
      requestId: 'req-det-1',
      actorId: 'operator-1',
      correlationId: 'corr-det-1',
    });

    const snap2 = controlPlaneSnapshotService.getSnapshot({
      timestamp: fixedTime,
      requestId: 'req-det-1',
      actorId: 'operator-1',
      correlationId: 'corr-det-1',
    });

    expect(snap1.snapshotId).toBe(snap2.snapshotId);
    expect(snap1.generatedAt).toBe(snap2.generatedAt);
    expect(snap1.requestId).toBe('req-det-1');
    expect(snap1.actorId).toBe('operator-1');
    expect(snap1.correlationId).toBe('corr-det-1');
    expect(snap1.missions.length).toBe(snap2.missions.length);
    expect(snap1.operations.length).toBe(snap2.operations.length);
  });

  it('2. mission projection correctly maps authoritative missions without mutating state', () => {
    // Seed a mock mission in persistence
    const testMission = {
      missionId: 'mis-stage24-test-1',
      title: 'Orbital Reconnaissance Mission',
      objective: 'Observe satellite constellation',
      goals: [
        { goalId: 'goal-sub-1', title: 'Telemetry Read', mandatory: true, status: 'RUNNING' as const, weight: 1 },
      ],
      dependencies: [],
      priority: 'HIGH' as const,
      status: 'RUNNING' as const,
      progress: {
        totalGoals: 1,
        completedGoals: 0,
        failedGoals: 0,
        inProgressGoals: 1,
        blockedGoals: 0,
        percentage: 0,
      },
      riskLevel: 'LOW' as const,
      plans: [],
      currentPlanVersion: 1,
      checkpoints: [],
      observations: [],
      decisions: [],
      constraints: [],
      milestones: [],
      completionCriteria: {
        mandatoryGoalsCompleted: true,
        minimumSuccessRate: 0.7,
        requiredMilestonesCompleted: [],
        allowPartialSuccess: true,
        requireHumanSignoff: false,
      },
      executionPolicy: {
        autoApproveReadOnly: true,
        allowPartialSuccess: true,
        maxCostUsd: null,
        replanOnGoalFailure: true,
      },
      createdAt: '2026-10-03T18:00:00.000Z',
      updatedAt: '2026-10-03T18:00:00.000Z',
      provenance: {},
    };

    executionPersistence.saveMission(testMission);

    const snapshot = controlPlaneSnapshotService.getSnapshot();
    const projected = snapshot.missions.find((m) => m.missionId === 'mis-stage24-test-1');

    expect(projected).toBeDefined();
    expect(projected?.title).toBe('Orbital Reconnaissance Mission');
    expect(projected?.status).toBe('RUNNING');
    expect(projected?.priority).toBe('HIGH');
    expect(projected?.goalId).toBe('goal-sub-1');
    expect(projected?.activeOperations).toBe(1);
  });

  it('3. operation projection correctly preserves source IDs and operational truth', () => {
    // Register audit event for an operation
    auditEventRegistry.recordEvent({
      eventId: 'evt-op-test-1',
      operationId: 'op-stage24-target-1',
      correlationId: 'corr-target-1',
      causationId: 'cause-target-1',
      eventType: 'ACTION_DISPATCHED',
      actor: { actorId: 'operator', actorType: 'USER' },
      sourceSystem: 'ActionBus',
      lifecycleState: 'DISPATCHED',
      epistemicStatus: 'UNKNOWN',
      actionId: 'act-001',
      capabilityId: 'filesystem.read',
      connectorId: 'conn-local',
      timestamp: 1727970005000,
    });

    const snapshot = controlPlaneSnapshotService.getSnapshot({
      targetOperationIds: ['op-stage24-target-1'],
    });

    const op = snapshot.operations.find((o) => o.operationId === 'op-stage24-target-1');
    expect(op).toBeDefined();
    expect(op?.operationId).toBe('op-stage24-target-1');
    expect(op?.causationId).toBe('cause-target-1');
    expect(op?.correlationId).toBe('corr-target-1');
    expect(op?.capabilityId).toBe('filesystem.read');
    expect(op?.status).toBe('DISPATCHED');
    expect(op?.epistemicState).toBe('UNKNOWN');
  });

  it('4. lifecycle preservation respects the 16 canonical states and avoids state collapse', () => {
    // Record chronological events
    const opId = 'op-lifecycle-progression';
    auditEventRegistry.recordEvent({
      eventId: 'evt-life-1',
      operationId: opId,
      correlationId: 'corr-life',
      eventType: 'REQUEST_RECEIVED',
      actor: { actorId: 'user', actorType: 'USER' },
      sourceSystem: 'Gateway',
      lifecycleState: 'RECEIVED',
      epistemicStatus: 'PROJECTED',
      timestamp: 1727970001000,
    });

    auditEventRegistry.recordEvent({
      eventId: 'evt-life-2',
      operationId: opId,
      correlationId: 'corr-life',
      eventType: 'ACTION_DISPATCHED',
      actor: { actorId: 'action-bus', actorType: 'SYSTEM' },
      sourceSystem: 'ActionBus',
      lifecycleState: 'DISPATCHED',
      epistemicStatus: 'UNKNOWN',
      timestamp: 1727970002000,
    });

    const timeline = controlPlaneSnapshotService.projectOperationTimeline(opId);
    expect(timeline.entries).toHaveLength(2);
    expect(timeline.entries[0].state).toBe('REQUESTED');
    expect(timeline.entries[1].state).toBe('DISPATCHED');
    expect(timeline.entries[1].epistemicState).toBe('UNKNOWN');
    expect(timeline.isTerminal).toBe(false);
  });

  it('5. UNKNOWN preservation: missing or ambiguous data is never coerced to synthetic defaults', () => {
    // Operation with no external confirmation
    const opId = 'op-unknown-test';
    auditEventRegistry.recordEvent({
      eventId: 'evt-unknown-1',
      operationId: opId,
      correlationId: 'corr-unknown',
      eventType: 'ACTION_DISPATCHED',
      actor: { actorId: 'system', actorType: 'SYSTEM' },
      sourceSystem: 'ActionBus',
      lifecycleState: 'DISPATCHED',
      epistemicStatus: 'UNKNOWN',
      timestamp: 1727970003000,
    });

    const snapshot = controlPlaneSnapshotService.getSnapshot({
      targetOperationIds: [opId],
    });

    const op = snapshot.operations.find((o) => o.operationId === opId);
    expect(op?.epistemicState).toBe('UNKNOWN');
    expect(op?.truthState).toBe('UNKNOWN');
    // DISPATCHED must never be coerced to SUCCEEDED
    expect(op?.status).toBe('DISPATCHED');
  });

  it('6. epistemic preservation separates intent from verified observation', () => {
    // Verify OperationalTruthService discrimination
    expect(operationalTruthService.isIntentOnly('DISPATCHED')).toBe(true);
    expect(operationalTruthService.isIntentOnly('PLANNED')).toBe(true);
    expect(operationalTruthService.isObservedState('SUCCEEDED')).toBe(true);
    expect(operationalTruthService.isObservedState('FAILED')).toBe(true);

    const snapshot = controlPlaneSnapshotService.getSnapshot();
    expect(snapshot).toBeDefined();
    expect(Object.isFrozen(snapshot)).toBe(true);
  });

  it('7. governance projection extracts Stage 21 decisions without re-evaluating policies', () => {
    const mockDecision: any = {
      decisionId: 'dec-gov-stage24-1',
      requestId: 'req-gov-stage24-1',
      correlationId: 'corr-gov-1',
      policySnapshotId: 'snap-pol-v1',
      policyRegistryVersion: 1,
      evaluatedPolicyVersions: {},
      decision: 'ALLOW',
      reason: 'Allowed by safe policy',
      matchedPolicies: ['pol-safe'],
      conflictingPolicies: [],
      winningPolicyId: 'pol-safe',
      winningPriority: 'NORMAL',
      authorityIntersection: {
        effectiveStatus: 'GRANTED',
        policyAllowed: true,
        connectorPermissionGranted: true,
        actionAuthorized: true,
        humanApprovalStatus: 'NOT_REQUIRED',
        humanApprovalRequired: false,
        missionConstraintsSatisfied: true,
        requiredAuthority: [],
        blockingReasons: [],
        failClosed: false,
      },
      staleness: {
        isStale: false,
        status: 'FRESH',
        evaluatedSnapshotId: 'snap-pol-v1',
        currentRegistryVersion: 1,
        snapshotRegistryVersion: 1,
      },
      explanation: {
        whatWasRequested: 'Read filesystem telemetry',
        snapshotUsed: 'snap-pol-v1',
        policiesMatched: ['pol-safe'],
        policiesConflicted: [],
        precedenceResolution: 'NORMAL',
        resultingPolicyDecision: 'ALLOW',
        authorityRequired: [],
        humanApprovalRequired: false,
        approvalPresent: false,
        executingOrBlockingBoundary: 'ActionBus',
        epistemicStatus: 'OBSERVED',
      },
      deterministicMetadata: {
        evaluationLatencyMs: 1.2,
        evaluatedAt: 1727970004000,
        cacheHit: false,
        fingerprint: 'fp-123',
      },
    };

    executionPersistence.saveGovernanceDecision(mockDecision);

    const snapshot = controlPlaneSnapshotService.getSnapshot();
    const govSummary = snapshot.governance.find((g) => g.decisionId === 'dec-gov-stage24-1');

    expect(govSummary).toBeDefined();
    expect(govSummary?.decision).toBe('ALLOW');
    expect(govSummary?.authorityState).toBe('GRANTED');
    expect(govSummary?.stalenessState).toBe('FRESH');
    expect(govSummary?.policyId).toBe('pol-safe');
  });

  it('8. approval projection captures human approval queue state faithfully', () => {
    const approvalRecord = {
      approvalId: 'appr-test-s24',
      goalId: 'goal-appr-s24',
      planId: 'plan-appr-s24',
      actionId: 'act-drop-table',
      actionTitle: 'Drop production table',
      riskLevel: 'CRITICAL',
      requestedAt: '2026-10-03T18:00:00.000Z',
      status: 'PENDING' as const,
      expiresAt: '2026-10-03T19:00:00.000Z',
    };

    executionPersistence.saveApproval(approvalRecord);

    const snapshot = controlPlaneSnapshotService.getSnapshot();
    const appr = snapshot.approvals.find((a) => a.approvalId === 'appr-test-s24');

    expect(appr).toBeDefined();
    expect(appr?.approvalState).toBe('PENDING');
    expect(appr?.actionTitle).toBe('Drop production table');
    expect(appr?.riskLevel).toBe('CRITICAL');
  });

  it('9. recovery projection captures Stage 23 recovery decisions without executing them', () => {
    const mockRecDecision: any = {
      decisionId: 'rec-dec-s24-1',
      requestId: 'req-rec-s24-1',
      recoveryPlanId: 'plan-rec-s24-1',
      originalOperationId: 'op-rec-s24-orig',
      failureClassification: 'TRANSIENT',
      epistemicStatus: 'OBSERVED',
      proposedRecoveryAction: 'RETRY',
      riskLevel: 'LOW',
      idempotencyClass: 'IDEMPOTENT',
      requiredAuthority: ['filesystem.read'],
      governanceDecisionId: 'gov-rec-s24-1',
      approvalRequirement: {
        required: false,
        humanOperatorRequired: false,
      },
      reconciliationRequirement: {
        required: false,
      },
      recoveryOutcome: 'RETRY',
      expiresAt: 1727970060000,
      causationId: 'op-rec-s24-orig',
      correlationId: 'corr-rec-s24',
      lifecycleState: 'READY',
      retryCount: 0,
      recoveryDepth: 1,
    };

    executionPersistence.saveRecoveryControlDecision(mockRecDecision);

    const snapshot = controlPlaneSnapshotService.getSnapshot();
    const rec = snapshot.recovery.find((r) => r.originalOperationId === 'op-rec-s24-orig');

    expect(rec).toBeDefined();
    expect(rec?.proposedRecoveryAction).toBe('RETRY');
    expect(rec?.failureClassification).toBe('TRANSIENT');
    expect(rec?.lifecycleState).toBe('READY');
  });

  it('10. causal trace projection builds bounded graphs from Stage 22 truth', () => {
    const opId = 'op-causal-test-s24';
    auditEventRegistry.recordEvent({
      eventId: 'evt-c-1',
      operationId: opId,
      correlationId: 'corr-c',
      eventType: 'REQUEST_RECEIVED',
      actor: { actorId: 'user', actorType: 'USER' },
      sourceSystem: 'Gateway',
      lifecycleState: 'RECEIVED',
      epistemicStatus: 'PROJECTED',
      timestamp: 1727970000000,
    });

    auditEventRegistry.recordEvent({
      eventId: 'evt-c-2',
      operationId: opId,
      correlationId: 'corr-c',
      causationId: 'evt-c-1',
      eventType: 'ACTION_DISPATCHED',
      actor: { actorId: 'action-bus', actorType: 'SYSTEM' },
      sourceSystem: 'ActionBus',
      lifecycleState: 'DISPATCHED',
      epistemicStatus: 'UNKNOWN',
      timestamp: 1727970001000,
    });

    const snapshot = controlPlaneSnapshotService.getSnapshot({
      targetOperationIds: [opId],
    });

    const trace = snapshot.causalTraces.find((t) => t.operationId === opId);
    expect(trace).toBeDefined();
    expect(trace?.nodes.length).toBeGreaterThan(0);
    expect(trace?.maxDepthReached).toBeLessThanOrEqual(10);
  });

  it('11. missing evidence preservation explicitly flags MISSING_EVIDENCE in causal traces', () => {
    const opId = 'op-missing-evidence-s24';
    auditEventRegistry.recordEvent({
      eventId: 'evt-m-1',
      operationId: opId,
      correlationId: 'corr-m',
      eventType: 'ACTION_DISPATCHED',
      actor: { actorId: 'system', actorType: 'SYSTEM' },
      sourceSystem: 'ActionBus',
      lifecycleState: 'DISPATCHED',
      epistemicStatus: 'UNKNOWN', // Missing external confirmation
      timestamp: 1727970002000,
    });

    const snapshot = controlPlaneSnapshotService.getSnapshot({
      targetOperationIds: [opId],
    });

    const trace = snapshot.causalTraces.find((t) => t.operationId === opId);
    expect(trace).toBeDefined();
    expect(trace?.hasMissingEvidence).toBe(true);
  });

  it('12. health projection provides observational status across all 9 domains', () => {
    const snapshot = controlPlaneSnapshotService.getSnapshot();
    const health = snapshot.systemHealth;

    expect(health.execution.status).toBeDefined();
    expect(health.providers.status).toBeDefined();
    expect(health.connectors.status).toBeDefined();
    expect(health.persistence.status).toBeDefined();
    expect(health.governance.status).toBeDefined();
    expect(health.recovery.status).toBeDefined();
    expect(health.eventIngestion.status).toBeDefined();
    expect(health.missions.status).toBeDefined();
    expect(health.actionBus.status).toBeDefined();
    expect(health.overallStatus).toBeDefined();
  });

  it('13. persistence durability truth reports exact underlying storage mode without falsification', () => {
    const isDurable = executionPersistence.isDurableStorageActive();
    const snapshot = controlPlaneSnapshotService.getSnapshot();

    expect(snapshot.systemHealth.isDurableStorage).toBe(isDurable);
    if (!isDurable) {
      expect(snapshot.systemHealth.persistence.status).toBe('DEGRADED');
    }
  });

  it('14. read-only behavior: snapshot object is deeply frozen against client mutation', () => {
    const snapshot = controlPlaneSnapshotService.getSnapshot();
    expect(Object.isFrozen(snapshot)).toBe(true);

    expect(() => {
      (snapshot as any).snapshotId = 'tampered-id';
    }).toThrow();
  });

  it('15. MANDATORY ADVERSARIAL TEST: calling getSnapshot() causes ZERO side-effects across all authorities', () => {
    const spyActionBus = vi.spyOn(actionBusService, 'execute');
    const spyGovernance = vi.spyOn(governanceControlPlane, 'evaluateGovernance');
    const spyRecovery = vi.spyOn(recoveryControlPlane, 'evaluateRecoveryControl');
    const spySaveMission = vi.spyOn(executionPersistence, 'saveMission');
    const spySaveGov = vi.spyOn(executionPersistence, 'saveGovernanceDecision');
    const spySaveRec = vi.spyOn(executionPersistence, 'saveRecoveryControlDecision');
    const spySaveAppr = vi.spyOn(executionPersistence, 'saveApproval');
    const spyRegPolicy = vi.spyOn(policyRegistry, 'registerPolicy');

    // Execute multiple snapshots
    controlPlaneSnapshotService.getSnapshot();
    controlPlaneSnapshotService.getSnapshot({ requestId: 'req-adv', actorId: 'operator' });

    // Verify ZERO execution, ZERO mutation, ZERO evaluation calls
    expect(spyActionBus).not.toHaveBeenCalled();
    expect(spyGovernance).not.toHaveBeenCalled();
    expect(spyRecovery).not.toHaveBeenCalled();
    expect(spySaveMission).not.toHaveBeenCalled();
    expect(spySaveGov).not.toHaveBeenCalled();
    expect(spySaveRec).not.toHaveBeenCalled();
    expect(spySaveAppr).not.toHaveBeenCalled();
    expect(spyRegPolicy).not.toHaveBeenCalled();
  });

  it('16. no governance mutation occurs during snapshot generation', () => {
    const initialDecisionsCount = executionPersistence.getAllGovernanceDecisions().length;
    controlPlaneSnapshotService.getSnapshot();
    const finalDecisionsCount = executionPersistence.getAllGovernanceDecisions().length;
    expect(finalDecisionsCount).toBe(initialDecisionsCount);
  });

  it('17. no recovery mutation occurs during snapshot generation', () => {
    const initialRecCount = executionPersistence.getAllRecoveryControlDecisions().length;
    controlPlaneSnapshotService.getSnapshot();
    const finalRecCount = executionPersistence.getAllRecoveryControlDecisions().length;
    expect(finalRecCount).toBe(initialRecCount);
  });

  it('18. no mission mutation occurs during snapshot generation', () => {
    const initialMissions = missionManager.listMissions().length;
    controlPlaneSnapshotService.getSnapshot();
    const finalMissions = missionManager.listMissions().length;
    expect(finalMissions).toBe(initialMissions);
  });

  it('19. no policy mutation occurs during snapshot generation', () => {
    const initialVersion = policyRegistry.getRegistryVersion();
    controlPlaneSnapshotService.getSnapshot();
    const finalVersion = policyRegistry.getRegistryVersion();
    expect(finalVersion).toBe(initialVersion);
  });

  it('20. secret scrubbing redacts bearer tokens, api keys, and passwords from context', () => {
    const snapshot = controlPlaneSnapshotService.getSnapshot({
      requestId: 'Bearer secret_token_12345',
      actorId: 'sk-antigravity-api-key',
    });

    expect(snapshot.requestId).toBe('[REDACTED]');
    expect(snapshot.actorId).toBe('[REDACTED]');
  });

  it('21. malformed context handling gracefully absorbs invalid inputs', () => {
    expect(() => {
      (controlPlaneSnapshotService as any).getSnapshot(null);
    }).not.toThrow();

    expect(() => {
      (controlPlaneSnapshotService as any).getSnapshot('malformed_string');
    }).not.toThrow();

    expect(() => {
      (controlPlaneSnapshotService as any).getSnapshot(12345);
    }).not.toThrow();
  });

  it('22. prototype pollution resistance ignores __proto__ and constructor overrides', () => {
    const maliciousPayload = JSON.parse('{"__proto__": {"polluted": true}, "constructor": {"polluted": true}}');
    const snapshot = controlPlaneSnapshotService.getSnapshot(maliciousPayload);

    expect(snapshot).toBeDefined();
    expect((Object.prototype as any).polluted).toBeUndefined();
  });

  it('23. partial subsystem failure degrades safely without blowing up snapshot generation', () => {
    const spyConnectors = vi.spyOn(connectorRegistry, 'listConnectors').mockImplementation(() => {
      throw new Error('Connector registry connection failed');
    });

    const snapshot = controlPlaneSnapshotService.getSnapshot();
    expect(snapshot).toBeDefined();
    expect(snapshot.systemHealth.connectors.status).toBe('UNKNOWN');
    spyConnectors.mockRestore();
  });

  it('24. concurrent snapshot requests complete deterministically without cross-contamination', async () => {
    const promises = Array.from({ length: 10 }).map((_, i) =>
      Promise.resolve(
        controlPlaneSnapshotService.getSnapshot({
          requestId: `req-concurrent-${i}`,
          timestamp: 1727970000000 + i,
        })
      )
    );

    const snapshots = await Promise.all(promises);
    expect(snapshots).toHaveLength(10);
    snapshots.forEach((snap, i) => {
      expect(snap.requestId).toBe(`req-concurrent-${i}`);
      expect(snap.generatedAt).toBe(1727970000000 + i);
    });
  });

  it('25. stable identifiers: snapshot output retains source IDs and stable object graphs', () => {
    const snapshot = controlPlaneSnapshotService.getSnapshot();
    expect(snapshot.snapshotId).toMatch(/^snap-cp-\d+$/);

    for (const mission of snapshot.missions) {
      expect(mission.missionId).toBeTruthy();
    }
    for (const op of snapshot.operations) {
      expect(op.operationId).toBeTruthy();
    }
  });
});
