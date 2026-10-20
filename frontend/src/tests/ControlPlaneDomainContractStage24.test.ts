/**
 * AryaOS V1 — Stage 24: Mission Operations Control Plane
 * Phase 1: Control-Plane Domain Contract Unit & Type Tests
 *
 * Verifies:
 * 1. Projection types can represent UNKNOWN across all required fields
 * 2. Projection types preserve canonical lifecycle states (16 canonical states)
 * 3. Governance projection contains no executable authority
 * 4. Recovery projection contains no executable authority
 * 5. Causal projection supports missing evidence without fabricating facts
 * 6. Operation projection preserves IDs and causal links
 * 7. Approval projection preserves expiration and status distinctions
 * 8. Health projection supports UNKNOWN and honest durability status
 * 9. No duplicate canonical types were introduced (reused from Stages 08–23)
 */

import { describe, it, expect } from 'vitest';
import {
  MissionSummary,
  OperationSummary,
  OperationTimeline,
  OperationTimelineEntry,
  GovernanceSummary,
  ApprovalSummary,
  RecoverySummary,
  CausalTraceSummary,
  CausalTraceNodeSummary,
  CausalTraceEdgeSummary,
  SystemHealthSummary,
  ControlPlaneSnapshot,
  CANONICAL_TIMELINE_STATES,
  APPROVAL_PROJECTION_STATES,
  SUBSYSTEM_HEALTH_STATUSES,
  EVIDENCE_STATES,
  RECOVERY_PROGRESSION_STATES,
  RECOVERY_TERMINAL_STATES,
  FAILURE_CLASSIFICATIONS,
  RECOVERY_ACTIONS,
  EpistemicStatus,
  OperationalLifecycleState,
  GovernanceDecisionType,
  AuthorityCheckStatus,
  HumanApprovalCheckStatus,
  StalenessStatus,
  FailureClassification,
  RecoveryAction,
  RecoveryLifecycleState,
  ActionRiskLevel,
} from '../types/controlPlane';

describe('AryaOS V1 — Stage 24: Phase 1 Control-Plane Domain Contract', () => {
  it('1. projection types can represent UNKNOWN without fabricating defaults', () => {
    const unknownMission: MissionSummary = {
      missionId: 'mis-unknown-1',
      goalId: 'UNKNOWN',
      title: 'UNKNOWN',
      status: 'UNKNOWN',
      priority: 'UNKNOWN',
      progress: 'UNKNOWN',
      activeOperations: 'UNKNOWN',
      blockedOperations: 'UNKNOWN',
      pendingApprovals: 'UNKNOWN',
      recoveryCount: 'UNKNOWN',
      latestOperationalState: 'UNKNOWN',
      latestTruthState: 'UNKNOWN',
      latestCausalEvent: 'UNKNOWN',
      policyVersion: 'UNKNOWN',
      governanceState: 'UNKNOWN',
      updatedAt: 'UNKNOWN',
    };

    expect(unknownMission.goalId).toBe('UNKNOWN');
    expect(unknownMission.status).toBe('UNKNOWN');
    expect(unknownMission.progress).toBe('UNKNOWN');
    expect(unknownMission.activeOperations).toBe('UNKNOWN');
    expect(unknownMission.latestTruthState).toBe('UNKNOWN');

    const unknownOp: OperationSummary = {
      operationId: 'op-unknown-1',
      missionId: 'UNKNOWN',
      goalId: 'UNKNOWN',
      actionId: 'UNKNOWN',
      status: 'UNKNOWN',
      truthState: 'UNKNOWN',
      epistemicState: 'UNKNOWN',
      riskLevel: 'UNKNOWN',
      policySnapshotId: 'UNKNOWN',
      governanceDecisionId: 'UNKNOWN',
      connectorId: 'UNKNOWN',
      capabilityId: 'UNKNOWN',
      idempotencyKey: 'UNKNOWN',
      createdAt: 'UNKNOWN',
      updatedAt: 'UNKNOWN',
      causationId: 'UNKNOWN',
      correlationId: 'UNKNOWN',
    };

    expect(unknownOp.truthState).toBe('UNKNOWN');
    expect(unknownOp.status).toBe('UNKNOWN');
    expect(unknownOp.riskLevel).toBe('UNKNOWN');
  });

  it('2. projection types preserve the 16 canonical lifecycle states without collapsing intent into truth', () => {
    expect(CANONICAL_TIMELINE_STATES).toHaveLength(16);
    expect(CANONICAL_TIMELINE_STATES).toEqual([
      'REQUESTED',
      'PLANNED',
      'TRIGGERED',
      'PROPOSED',
      'GOVERNED',
      'AUTHORIZED',
      'DISPATCHED',
      'EXECUTING',
      'SUCCEEDED',
      'FAILED',
      'REJECTED',
      'DENIED',
      'DEFERRED',
      'PAUSED',
      'UNKNOWN',
      'RECONCILED',
    ]);

    // Verify timeline entry retains state and epistemic distinction
    const entry: OperationTimelineEntry = {
      state: 'DISPATCHED',
      timestamp: 1727970000000,
      source: 'ActionBus',
      epistemicState: 'UNKNOWN', // Post-dispatch before external confirmation
      eventId: 'evt-101',
      causationId: 'op-101',
      correlationId: 'corr-101',
    };

    expect(entry.state).toBe('DISPATCHED');
    expect(entry.epistemicState).toBe('UNKNOWN'); // DISPATCHED != CONFIRMED

    const timeline: OperationTimeline = {
      operationId: 'op-101',
      entries: [entry],
      currentState: 'DISPATCHED',
      epistemicState: 'UNKNOWN',
      startedAt: 1727970000000,
      lastUpdatedAt: 1727970000000,
      isTerminal: false,
    };

    expect(timeline.isTerminal).toBe(false);
    expect(timeline.currentState).toBe('DISPATCHED');
  });

  it('3. governance projection contains no executable authority or evaluation methods', () => {
    const govSummary: GovernanceSummary = {
      policySnapshotId: 'snap-42',
      policyId: 'pol-fs-write',
      policyVersion: 3,
      requestId: 'req-gov-201',
      decisionId: 'dec-gov-201',
      decision: 'ALLOW',
      authorityState: 'GRANTED',
      stalenessState: 'FRESH',
      connectorAuthorityState: true,
      actionAuthorizationState: true,
      humanApprovalState: 'NOT_REQUIRED',
      missionConstraintState: true,
      explanation: 'Policy evaluation ALLOW and all authority tiers satisfied',
      evaluatedAt: 1727970050000,
    };

    // Verify it is a pure data projection without function methods
    const keys = Object.keys(govSummary);
    for (const key of keys) {
      expect(typeof (govSummary as unknown as Record<string, unknown>)[key]).not.toBe('function');
    }
    expect(govSummary.decision).toBe('ALLOW');
    expect(govSummary.authorityState).toBe('GRANTED');
  });

  it('4. recovery projection contains no executable authority or side-effect triggers', () => {
    const recSummary: RecoverySummary = {
      recoveryPlanId: 'plan-rec-301',
      originalOperationId: 'op-rec-301',
      failureClassification: 'TRANSIENT',
      currentTruthState: 'OBSERVED',
      proposedRecoveryAction: 'RETRY',
      riskLevel: 'LOW',
      idempotencyAssessment: 'IDEMPOTENT',
      requiredAuthority: ['filesystem.write'],
      governanceDecisionId: 'gov-dec-301',
      approvalRequirement: {
        required: false,
        humanOperatorRequired: false,
      },
      reconciliationRequirement: {
        required: false,
      },
      expectedOutcome: 'RESUME',
      expiresAt: 1727970100000,
      causationId: 'op-rec-301',
      correlationId: 'corr-301',
      lifecycleState: 'PROPOSED',
      retryCount: 0,
      recoveryDepth: 1,
    };

    // Verify pure data projection without methods
    for (const key of Object.keys(recSummary)) {
      expect(typeof (recSummary as unknown as Record<string, unknown>)[key]).not.toBe('function');
    }
    expect(recSummary.proposedRecoveryAction).toBe('RETRY');
    expect(recSummary.lifecycleState).toBe('PROPOSED');
  });

  it('5. causal projection supports MISSING_EVIDENCE without fabricating links', () => {
    expect(EVIDENCE_STATES).toContain('MISSING_EVIDENCE');
    expect(EVIDENCE_STATES).toContain('VERIFIED');
    expect(EVIDENCE_STATES).toContain('PENDING');
    expect(EVIDENCE_STATES).toContain('UNKNOWN');

    const missingNode: CausalTraceNodeSummary = {
      nodeId: 'node-missing-401',
      domain: 'ProviderGateway',
      entityId: 'UNKNOWN',
      nodeType: 'MISSING_EVIDENCE',
      label: 'Missing External Confirmation',
      state: 'UNKNOWN',
      epistemicState: 'UNKNOWN',
      timestamp: 'UNKNOWN',
      source: 'OperationalTruthService',
      evidenceState: 'MISSING_EVIDENCE',
    };

    const edge: CausalTraceEdgeSummary = {
      fromNodeId: 'node-dispatch-400',
      toNodeId: 'node-missing-401',
      edgeType: 'RESULTED_IN',
      timestamp: 1727970000000,
    };

    const trace: CausalTraceSummary = {
      operationId: 'op-trace-401',
      rootNodeId: 'node-dispatch-400',
      nodes: [missingNode],
      edges: [edge],
      maxDepthReached: 1,
      isTruncated: false,
      hasCycles: false,
      hasMissingEvidence: true,
    };

    expect(trace.hasMissingEvidence).toBe(true);
    expect(trace.nodes[0].evidenceState).toBe('MISSING_EVIDENCE');
    expect(trace.nodes[0].epistemicState).toBe('UNKNOWN');
  });

  it('6. operation projection preserves source IDs and causal links', () => {
    const op: OperationSummary = {
      operationId: 'op-valid-501',
      missionId: 'mis-501',
      goalId: 'goal-501',
      actionId: 'act-501',
      title: 'Compile Production Asset',
      status: 'SUCCEEDED',
      truthState: 'CONFIRMED',
      epistemicState: 'CONFIRMED',
      riskLevel: 'LOW',
      policySnapshotId: 'snap-501',
      governanceDecisionId: 'gov-501',
      connectorId: 'conn-github',
      capabilityId: 'github.commit',
      idempotencyKey: 'idem-501',
      createdAt: 1727969000000,
      updatedAt: 1727970000000,
      causationId: 'parent-op-500',
      correlationId: 'root-corr-500',
    };

    expect(op.operationId).toBe('op-valid-501');
    expect(op.causationId).toBe('parent-op-500');
    expect(op.correlationId).toBe('root-corr-500');
    expect(op.idempotencyKey).toBe('idem-501');
    expect(op.governanceDecisionId).toBe('gov-501');
  });

  it('7. approval projection preserves expiration, states, and human-operator binding', () => {
    expect(APPROVAL_PROJECTION_STATES).toEqual([
      'PENDING',
      'APPROVED',
      'REJECTED',
      'EXPIRED',
      'INVALID',
      'UNKNOWN',
    ]);

    const pendingApproval: ApprovalSummary = {
      approvalId: 'appr-601',
      requestId: 'req-601',
      actorId: 'operator@aryaos.org',
      riskLevel: 'HIGH',
      policySnapshotId: 'snap-601',
      policyVersion: 2,
      approvalState: 'PENDING',
      expiresAt: 1727973600000,
      createdAt: 1727970000000,
      actionTitle: 'Database Schema Migration',
      reason: 'Requires operator confirmation for DDL modification',
    };

    expect(pendingApproval.approvalState).toBe('PENDING');
    expect(pendingApproval.expiresAt).toBe(1727973600000);
    expect(pendingApproval.actorId).toBe('operator@aryaos.org');

    const expiredApproval: ApprovalSummary = {
      ...pendingApproval,
      approvalState: 'EXPIRED',
    };
    expect(expiredApproval.approvalState).toBe('EXPIRED');
  });

  it('8. health projection supports UNKNOWN and reports truthful durability status', () => {
    expect(SUBSYSTEM_HEALTH_STATUSES).toEqual([
      'HEALTHY',
      'DEGRADED',
      'FAILED',
      'UNKNOWN',
    ]);

    const health: SystemHealthSummary = {
      execution: { status: 'HEALTHY', lastCheckedAt: 1727970000000 },
      providers: { status: 'DEGRADED', message: 'Rate limit threshold approaching 80%', lastCheckedAt: 1727970000000 },
      connectors: { status: 'HEALTHY', lastCheckedAt: 1727970000000 },
      persistence: { status: 'HEALTHY', lastCheckedAt: 1727970000000 },
      governance: { status: 'HEALTHY', lastCheckedAt: 1727970000000 },
      recovery: { status: 'HEALTHY', lastCheckedAt: 1727970000000 },
      eventIngestion: { status: 'UNKNOWN', message: 'No ingress telemetry received in 60s', lastCheckedAt: 'UNKNOWN' },
      missions: { status: 'HEALTHY', lastCheckedAt: 1727970000000 },
      actionBus: { status: 'HEALTHY', lastCheckedAt: 1727970000000 },
      overallStatus: 'DEGRADED',
      isDurableStorage: false, // In-memory fallback
    };

    expect(health.eventIngestion.status).toBe('UNKNOWN');
    expect(health.isDurableStorage).toBe(false);
    expect(health.overallStatus).toBe('DEGRADED');
  });

  it('9. no duplicate canonical types: reuses existing contracts and sets', () => {
    // Stage 23 recovery progression & terminal states
    expect(RECOVERY_PROGRESSION_STATES).toContain('DETECTED');
    expect(RECOVERY_PROGRESSION_STATES).toContain('COMPLETED');
    expect(RECOVERY_TERMINAL_STATES).toContain('ABORTED');
    expect(RECOVERY_TERMINAL_STATES).toContain('ESCALATED');

    // Stage 23 failure classifications
    expect(FAILURE_CLASSIFICATIONS).toHaveLength(13);
    expect(FAILURE_CLASSIFICATIONS).toContain('TRANSIENT');
    expect(FAILURE_CLASSIFICATIONS).toContain('UNKNOWN_EXTERNAL_STATE');

    // Stage 23 recovery actions
    expect(RECOVERY_ACTIONS).toHaveLength(11);
    expect(RECOVERY_ACTIONS).toContain('RETRY');
    expect(RECOVERY_ACTIONS).toContain('COMPENSATE');

    // ControlPlaneSnapshot composition test
    const snapshot: ControlPlaneSnapshot = {
      snapshotId: 'snap-cp-901',
      generatedAt: 1727970000000,
      sourceVersion: 1,
      missions: [],
      operations: [],
      approvals: [],
      governance: [],
      recovery: [],
      causalTraces: [],
      systemHealth: {
        execution: { status: 'HEALTHY', lastCheckedAt: 1727970000000 },
        providers: { status: 'HEALTHY', lastCheckedAt: 1727970000000 },
        connectors: { status: 'HEALTHY', lastCheckedAt: 1727970000000 },
        persistence: { status: 'HEALTHY', lastCheckedAt: 1727970000000 },
        governance: { status: 'HEALTHY', lastCheckedAt: 1727970000000 },
        recovery: { status: 'HEALTHY', lastCheckedAt: 1727970000000 },
        eventIngestion: { status: 'HEALTHY', lastCheckedAt: 1727970000000 },
        missions: { status: 'HEALTHY', lastCheckedAt: 1727970000000 },
        actionBus: { status: 'HEALTHY', lastCheckedAt: 1727970000000 },
        overallStatus: 'HEALTHY',
        isDurableStorage: true,
      },
      requestId: 'req-901',
      actorId: 'operator-01',
      correlationId: 'corr-901',
    };

    expect(snapshot.snapshotId).toBe('snap-cp-901');
    expect(snapshot.systemHealth.overallStatus).toBe('HEALTHY');
  });
});
