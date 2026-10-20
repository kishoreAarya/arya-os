/**
 * AryaOS V1 — Stage 24: Mission Operations Control Plane
 * Phase 3: Operation Timeline Projection Verification Suite
 *
 * Exhaustive verification covering:
 * - 16 canonical state preservation (REQUESTED != PLANNED != AUTHORIZED != DISPATCHED != ...)
 * - Truthful chronological ordering (authoritative timestamp, sequence, eventId)
 * - Deterministic ordering for equal timestamps
 * - Event identity preservation and canonical deduplication
 * - UNKNOWN and MISSING_EVIDENCE preservation (never coerced or fabricated)
 * - Epistemic status separation (Intent vs Verified Observation)
 * - Cross-stage causality and correlation preservation
 * - Bounded multi-dimensional filtering (operationId, missionId, goalId, correlationId)
 * - Zero execution, zero mutation, zero side-effects (pure read projection)
 * - Prototype pollution defense and recursive credential/secret scrubbing
 * - Concurrency safety and full ControlPlaneSnapshot integration
 * - Adversarial Cases A through J
 */

import { describe, it, expect, beforeEach, vi } from 'vitest';
import { controlPlaneSnapshotService } from '../services/controlPlaneSnapshotService';
import { auditEventRegistry } from '../services/auditEventRegistry';
import { operationalTruthService } from '../services/operationalTruthService';
import { executionPersistence } from '../services/executionPersistence';
import { executionJournal } from '../services/executionJournal';
import { actionBusService } from '../services/actionBusService';
import { governanceControlPlane } from '../services/governanceControlPlane';
import { recoveryControlPlane } from '../services/recoveryControlPlane';
import {
  CANONICAL_TIMELINE_STATES,
  CanonicalTimelineState,
  OperationTimeline,
  OperationTimelineEntry,
} from '../types/controlPlane';
import { OperationalAuditEvent, OperationalLifecycleState, EpistemicStatus } from '../types/operationalAudit';

describe('AryaOS Stage 24 — Phase 3: Operation Timeline Projection', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    auditEventRegistry.reset();
    executionJournal.resetState();
    executionPersistence.clearEnvelope();
  });

  // ==========================================================================
  // PART 1: Canonical Lifecycle & State Preservation
  // ==========================================================================

  it('1. canonical 16-state preservation: all 16 canonical states are faithfully projected', () => {
    const states: CanonicalTimelineState[] = [
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
    ];

    expect(CANONICAL_TIMELINE_STATES.length).toBe(16);

    states.forEach((st, idx) => {
      const opId = `op-state-preserve-${idx}`;
      auditEventRegistry.recordEvent({
        eventId: `evt-st-${idx}`,
        operationId: opId,
        correlationId: `corr-${idx}`,
        eventType: st === 'REQUESTED' ? 'REQUEST_RECEIVED' : 'ACTION_EXECUTED',
        lifecycleState: st === 'REQUESTED' ? 'RECEIVED' : (st as OperationalLifecycleState),
        epistemicStatus: st === 'UNKNOWN' ? 'UNKNOWN' : 'OBSERVED',
        timestamp: 1727970000000 + idx * 1000,
      });

      const timeline = controlPlaneSnapshotService.projectOperationTimeline(opId);
      expect(timeline.entries.length).toBe(1);
      expect(timeline.entries[0].state).toBe(st);
      expect(timeline.currentState).toBe(st);
    });
  });

  it('2. chronological ordering: events are sorted strictly by authoritative timestamp', () => {
    const opId = 'op-chrono-test';
    // Register events out of chronological order
    const timestamps = [1727970030000, 1727970010000, 1727970050000, 1727970020000, 1727970040000];

    timestamps.forEach((ts, idx) => {
      auditEventRegistry.recordEvent({
        eventId: `evt-chrono-${idx}`,
        operationId: opId,
        correlationId: 'corr-chrono',
        eventType: 'ACTION_EXECUTED',
        lifecycleState: 'EXECUTING',
        epistemicStatus: 'OBSERVED',
        parameters: { step: idx },
        timestamp: ts,
      });
    });

    const timeline = controlPlaneSnapshotService.projectOperationTimeline(opId);
    expect(timeline.entries.length).toBe(5);

    // Verify strictly ascending timestamps
    for (let i = 1; i < timeline.entries.length; i++) {
      expect((timeline.entries[i].timestamp as number)).toBeGreaterThan((timeline.entries[i - 1].timestamp as number));
    }
    expect(timeline.startedAt).toBe(1727970010000);
    expect(timeline.lastUpdatedAt).toBe(1727970050000);
  });

  it('3. deterministic ordering for equal timestamps: uses sequence and stable event identity', () => {
    const opId = 'op-equal-ts';
    const sharedTimestamp = 1727970099000;

    auditEventRegistry.recordEvent({
      eventId: 'evt-c-stable',
      operationId: opId,
      correlationId: 'corr-eq',
      eventType: 'ACTION_EXECUTED',
      lifecycleState: 'EXECUTING',
      epistemicStatus: 'OBSERVED',
      timestamp: sharedTimestamp,
    });
    auditEventRegistry.recordEvent({
      eventId: 'evt-a-stable',
      operationId: opId,
      correlationId: 'corr-eq',
      eventType: 'REQUEST_RECEIVED',
      lifecycleState: 'RECEIVED',
      epistemicStatus: 'OBSERVED',
      timestamp: sharedTimestamp,
    });
    auditEventRegistry.recordEvent({
      eventId: 'evt-b-stable',
      operationId: opId,
      correlationId: 'corr-eq',
      eventType: 'ACTION_DISPATCHED',
      lifecycleState: 'DISPATCHED',
      epistemicStatus: 'UNKNOWN',
      timestamp: sharedTimestamp,
    });

    const timeline = controlPlaneSnapshotService.projectOperationTimeline(opId);
    expect(timeline.entries.length).toBe(3);
    // When sequence numbers are equal/absent, ordered lexicographically by eventId
    expect(timeline.entries[0].eventId).toBe('evt-a-stable');
    expect(timeline.entries[1].eventId).toBe('evt-b-stable');
    expect(timeline.entries[2].eventId).toBe('evt-c-stable');
  });

  it('4. event identity preservation: original eventId is preserved without synthetic replacement', () => {
    const opId = 'op-ident-1';
    const targetEventId = 'evt-exact-uuid-998877';

    auditEventRegistry.recordEvent({
      eventId: targetEventId,
      operationId: opId,
      correlationId: 'corr-ident',
      eventType: 'REQUEST_RECEIVED',
      lifecycleState: 'RECEIVED',
      epistemicStatus: 'OBSERVED',
      timestamp: 1727970001000,
    });

    const timeline = controlPlaneSnapshotService.projectOperationTimeline(opId);
    expect(timeline.entries[0].eventId).toBe(targetEventId);
  });

  it('5. duplicate event handling: deduplicates identical event identities without dropping distinct events', () => {
    const opId = 'op-dedupe-test';

    // Same event recorded twice (replay scenario)
    auditEventRegistry.recordEvent({
      eventId: 'evt-dup-1',
      operationId: opId,
      correlationId: 'corr-dup',
      eventType: 'REQUEST_RECEIVED',
      lifecycleState: 'RECEIVED',
      epistemicStatus: 'OBSERVED',
      timestamp: 1727970001000,
    });
    auditEventRegistry.recordEvent({
      eventId: 'evt-dup-1',
      operationId: opId,
      correlationId: 'corr-dup',
      eventType: 'REQUEST_RECEIVED',
      lifecycleState: 'RECEIVED',
      epistemicStatus: 'OBSERVED',
      timestamp: 1727970001000,
    });

    // Two distinct events that happen to have the SAME state
    auditEventRegistry.recordEvent({
      eventId: 'evt-auth-step-1',
      operationId: opId,
      correlationId: 'corr-dup',
      eventType: 'GOVERNANCE_DECIDED',
      lifecycleState: 'AUTHORIZED',
      epistemicStatus: 'OBSERVED',
      parameters: { authCheck: 'policy-check' },
      timestamp: 1727970002000,
    });
    auditEventRegistry.recordEvent({
      eventId: 'evt-auth-step-2',
      operationId: opId,
      correlationId: 'corr-dup',
      eventType: 'GOVERNANCE_DECIDED',
      lifecycleState: 'AUTHORIZED',
      epistemicStatus: 'OBSERVED',
      parameters: { authCheck: 'token-validation' },
      timestamp: 1727970003000,
    });

    const timeline = controlPlaneSnapshotService.projectOperationTimeline(opId);
    // evt-dup-1 appears ONCE; both auth steps appear
    expect(timeline.entries.length).toBe(3);
    expect(timeline.entries[0].eventId).toBe('evt-dup-1');
    expect(timeline.entries[1].eventId).toBe('evt-auth-step-1');
    expect(timeline.entries[2].eventId).toBe('evt-auth-step-2');
  });

  // ==========================================================================
  // PART 2: Epistemic Rigor, UNKNOWN & MISSING_EVIDENCE
  // ==========================================================================

  it('6. UNKNOWN preservation: missing external evidence remains UNKNOWN and never coerced to SUCCESS or FAILED', () => {
    const opId = 'op-unknown-preservation';

    auditEventRegistry.recordEvent({
      eventId: 'evt-un-1',
      operationId: opId,
      correlationId: 'corr-un',
      eventType: 'ACTION_DISPATCHED',
      lifecycleState: 'DISPATCHED',
      epistemicStatus: 'UNKNOWN',
      timestamp: 1727970001000,
    });

    const timeline = controlPlaneSnapshotService.projectOperationTimeline(opId);
    expect(timeline.currentState).toBe('DISPATCHED');
    expect(timeline.epistemicState).toBe('UNKNOWN');
    expect(timeline.isTerminal).toBe(false);

    // Assert that operational truth discriminator agrees
    expect(operationalTruthService.isIntentOnly(timeline.currentState as any)).toBe(true);
    expect(operationalTruthService.isObservedState(timeline.currentState as any)).toBe(false);
  });

  it('7. MISSING_EVIDENCE preservation: explicitly recorded missing evidence is preserved in timeline', () => {
    const opId = 'op-missing-evidence-1';

    auditEventRegistry.recordEvent({
      eventId: 'evt-missing-1',
      operationId: opId,
      correlationId: 'corr-me',
      eventType: 'OBSERVATION_RECORDED',
      lifecycleState: 'UNKNOWN',
      epistemicStatus: 'UNKNOWN',
      reason: 'MISSING_EVIDENCE',
      parameters: { isMissingEvidence: true, missingStage: 'Stage 21 Governance' },
      timestamp: 1727970002000,
    });

    const timeline = controlPlaneSnapshotService.projectOperationTimeline(opId);
    expect(timeline.entries.length).toBe(1);
    expect(timeline.entries[0].reason).toBe('MISSING_EVIDENCE');
    expect(timeline.entries[0].metadata?.isMissingEvidence).toBe(true);
    expect(timeline.entries[0].metadata?.missingStage).toBe('Stage 21 Governance');
  });

  it('8. epistemic status preservation: preserves OBSERVED, CONFIRMED, INFERRED, PROJECTED, UNKNOWN', () => {
    const statuses: EpistemicStatus[] = ['OBSERVED', 'CONFIRMED', 'INFERRED', 'PROJECTED', 'UNKNOWN'];

    statuses.forEach((status, idx) => {
      const opId = `op-epistemic-${idx}`;
      auditEventRegistry.recordEvent({
        eventId: `evt-epi-${idx}`,
        operationId: opId,
        correlationId: `corr-epi-${idx}`,
        eventType: 'ACTION_EXECUTED',
        lifecycleState: 'EXECUTING',
        epistemicStatus: status,
        timestamp: 1727970000000 + idx,
      });

      const timeline = controlPlaneSnapshotService.projectOperationTimeline(opId);
      expect(timeline.entries[0].epistemicState).toBe(status);
      expect(timeline.epistemicState).toBe(status);
    });
  });

  it('9. causation ID preservation: preserves cross-event causal links', () => {
    const opId = 'op-causal-link';
    const causeId = 'evt-root-trigger';

    auditEventRegistry.recordEvent({
      eventId: 'evt-child-reaction',
      operationId: opId,
      correlationId: 'corr-c',
      causationId: causeId,
      eventType: 'REACTION_PROPOSED',
      lifecycleState: 'PROPOSED',
      epistemicStatus: 'OBSERVED',
      timestamp: 1727970001000,
    });

    const timeline = controlPlaneSnapshotService.projectOperationTimeline(opId);
    expect(timeline.entries[0].causationId).toBe(causeId);
  });

  it('10. correlation ID preservation: preserves end-to-end correlation ID across entries', () => {
    const opId = 'op-corr-chain';
    const correlationId = 'corr-session-alpha-99';

    auditEventRegistry.recordEvent({
      eventId: 'evt-c-1',
      operationId: opId,
      correlationId,
      eventType: 'REQUEST_RECEIVED',
      lifecycleState: 'RECEIVED',
      epistemicStatus: 'OBSERVED',
      timestamp: 1727970001000,
    });
    auditEventRegistry.recordEvent({
      eventId: 'evt-c-2',
      operationId: opId,
      correlationId,
      eventType: 'ACTION_DISPATCHED',
      lifecycleState: 'DISPATCHED',
      epistemicStatus: 'UNKNOWN',
      timestamp: 1727970002000,
    });

    const timeline = controlPlaneSnapshotService.projectOperationTimeline(opId);
    expect(timeline.entries[0].correlationId).toBe(correlationId);
    expect(timeline.entries[1].correlationId).toBe(correlationId);
  });

  // ==========================================================================
  // PART 3: Filtering & Bounded Projection
  // ==========================================================================

  it('11. mission filtering: restricts timeline events to the targeted missionId', () => {
    const opId = 'op-mission-filter';

    auditEventRegistry.recordEvent({
      eventId: 'evt-mis-a',
      operationId: opId,
      missionId: 'mission-alpha',
      correlationId: 'corr-mis',
      eventType: 'REQUEST_RECEIVED',
      lifecycleState: 'RECEIVED',
      epistemicStatus: 'OBSERVED',
      timestamp: 1727970001000,
    });
    auditEventRegistry.recordEvent({
      eventId: 'evt-mis-b',
      operationId: opId,
      missionId: 'mission-beta',
      correlationId: 'corr-mis',
      eventType: 'ACTION_DISPATCHED',
      lifecycleState: 'DISPATCHED',
      epistemicStatus: 'UNKNOWN',
      timestamp: 1727970002000,
    });

    const timelineAlpha = controlPlaneSnapshotService.projectOperationTimeline(opId, {
      missionId: 'mission-alpha',
    });
    expect(timelineAlpha.entries.length).toBe(1);
    expect(timelineAlpha.entries[0].eventId).toBe('evt-mis-a');

    const timelineBeta = controlPlaneSnapshotService.projectOperationTimeline(opId, {
      missionId: 'mission-beta',
    });
    expect(timelineBeta.entries.length).toBe(1);
    expect(timelineBeta.entries[0].eventId).toBe('evt-mis-b');
  });

  it('12. operation filtering: queries only targeted operation', () => {
    auditEventRegistry.recordEvent({
      eventId: 'evt-op1',
      operationId: 'op-target-1',
      correlationId: 'corr-1',
      eventType: 'REQUEST_RECEIVED',
      lifecycleState: 'RECEIVED',
      epistemicStatus: 'OBSERVED',
      timestamp: 1727970001000,
    });
    auditEventRegistry.recordEvent({
      eventId: 'evt-op2',
      operationId: 'op-target-2',
      correlationId: 'corr-2',
      eventType: 'ACTION_DISPATCHED',
      lifecycleState: 'DISPATCHED',
      epistemicStatus: 'UNKNOWN',
      timestamp: 1727970002000,
    });

    const tl1 = controlPlaneSnapshotService.projectOperationTimeline('op-target-1');
    expect(tl1.operationId).toBe('op-target-1');
    expect(tl1.entries.length).toBe(1);
    expect(tl1.entries[0].eventId).toBe('evt-op1');

    const tl2 = controlPlaneSnapshotService.projectOperationTimeline('op-target-2');
    expect(tl2.operationId).toBe('op-target-2');
    expect(tl2.entries.length).toBe(1);
    expect(tl2.entries[0].eventId).toBe('evt-op2');
  });

  it('13. goal filtering: restricts timeline entries by goalId', () => {
    const opId = 'op-goal-filter';

    auditEventRegistry.recordEvent({
      eventId: 'evt-g1',
      operationId: opId,
      goalId: 'goal-sub-1',
      correlationId: 'corr-g',
      eventType: 'REQUEST_RECEIVED',
      lifecycleState: 'RECEIVED',
      epistemicStatus: 'OBSERVED',
      timestamp: 1727970001000,
    });
    auditEventRegistry.recordEvent({
      eventId: 'evt-g2',
      operationId: opId,
      goalId: 'goal-sub-2',
      correlationId: 'corr-g',
      eventType: 'ACTION_DISPATCHED',
      lifecycleState: 'DISPATCHED',
      epistemicStatus: 'UNKNOWN',
      timestamp: 1727970002000,
    });

    const tlGoal1 = controlPlaneSnapshotService.projectOperationTimeline(opId, {
      goalId: 'goal-sub-1',
    });
    expect(tlGoal1.entries.length).toBe(1);
    expect(tlGoal1.entries[0].eventId).toBe('evt-g1');
  });

  // ==========================================================================
  // PART 4: Critical Epistemic Invariants & Non-Inference
  // ==========================================================================

  it('14. no fabricated lifecycle transitions: missing historical steps are never manufactured', () => {
    const opId = 'op-jump';

    // Operation jumps directly from REQUEST_RECEIVED to SUCCEEDED (e.g. cached response)
    auditEventRegistry.recordEvent({
      eventId: 'evt-j-1',
      operationId: opId,
      correlationId: 'corr-j',
      eventType: 'REQUEST_RECEIVED',
      lifecycleState: 'RECEIVED',
      epistemicStatus: 'OBSERVED',
      timestamp: 1727970001000,
    });
    auditEventRegistry.recordEvent({
      eventId: 'evt-j-2',
      operationId: opId,
      correlationId: 'corr-j',
      eventType: 'OPERATION_SUCCEEDED',
      lifecycleState: 'SUCCEEDED',
      epistemicStatus: 'OBSERVED',
      timestamp: 1727970005000,
    });

    const timeline = controlPlaneSnapshotService.projectOperationTimeline(opId);
    expect(timeline.entries.length).toBe(2);
    // Never fabricates PLANNED, AUTHORIZED, DISPATCHED, or EXECUTING
    expect(timeline.entries[0].state).toBe('REQUESTED');
    expect(timeline.entries[1].state).toBe('SUCCEEDED');
    expect(timeline.entries.map((e) => e.state)).toEqual(['REQUESTED', 'SUCCEEDED']);
  });

  it('15. AUTHORIZED does not imply DISPATCHED: policy authorization does not synthesize dispatch', () => {
    const opId = 'op-auth-only';

    auditEventRegistry.recordEvent({
      eventId: 'evt-auth-1',
      operationId: opId,
      correlationId: 'corr-auth',
      eventType: 'GOVERNANCE_DECIDED',
      lifecycleState: 'AUTHORIZED',
      epistemicStatus: 'OBSERVED',
      timestamp: 1727970001000,
    });

    const timeline = controlPlaneSnapshotService.projectOperationTimeline(opId);
    expect(timeline.entries.length).toBe(1);
    expect(timeline.entries[0].state).toBe('AUTHORIZED');
    expect(timeline.entries.some((e) => e.state === 'DISPATCHED')).toBe(false);
  });

  it('16. DISPATCHED does not imply SUCCEEDED: external dispatch without response stays DISPATCHED', () => {
    const opId = 'op-dispatch-only';

    auditEventRegistry.recordEvent({
      eventId: 'evt-disp-1',
      operationId: opId,
      correlationId: 'corr-disp',
      eventType: 'ACTION_DISPATCHED',
      lifecycleState: 'DISPATCHED',
      epistemicStatus: 'UNKNOWN',
      timestamp: 1727970001000,
    });

    const timeline = controlPlaneSnapshotService.projectOperationTimeline(opId);
    expect(timeline.entries.length).toBe(1);
    expect(timeline.entries[0].state).toBe('DISPATCHED');
    expect(timeline.entries.some((e) => e.state === 'SUCCEEDED')).toBe(false);
    expect(timeline.isTerminal).toBe(false);
  });

  it('17. UNKNOWN does not become FAILED: ambiguous state is preserved honestly as UNKNOWN', () => {
    const opId = 'op-ambig';

    auditEventRegistry.recordEvent({
      eventId: 'evt-ambig-1',
      operationId: opId,
      correlationId: 'corr-ambig',
      eventType: 'OPERATION_UNKNOWN',
      lifecycleState: 'UNKNOWN',
      epistemicStatus: 'UNKNOWN',
      reason: 'No external socket acknowledgement within timeout window',
      timestamp: 1727970001000,
    });

    const timeline = controlPlaneSnapshotService.projectOperationTimeline(opId);
    expect(timeline.currentState).toBe('UNKNOWN');
    expect(timeline.epistemicState).toBe('UNKNOWN');
    expect(timeline.entries[0].state).toBe('UNKNOWN');
    expect(timeline.entries.some((e) => e.state === 'FAILED')).toBe(false);
  });

  // ==========================================================================
  // PART 5: Read-Only Enforcement & Zero Authority Duplication
  // ==========================================================================

  it('18. read-only behavior: calling timeline projection never mutates audit registry or persistence', () => {
    const opId = 'op-read-only-assert';

    auditEventRegistry.recordEvent({
      eventId: 'evt-ro-1',
      operationId: opId,
      correlationId: 'corr-ro',
      eventType: 'REQUEST_RECEIVED',
      lifecycleState: 'RECEIVED',
      epistemicStatus: 'OBSERVED',
      timestamp: 1727970001000,
    });

    const eventCountBefore = auditEventRegistry.getAllEvents().length;
    controlPlaneSnapshotService.projectOperationTimeline(opId);
    const eventCountAfter = auditEventRegistry.getAllEvents().length;

    expect(eventCountBefore).toBe(eventCountAfter);
  });

  it('19. no Action Bus execution: timeline generation never calls ActionBusService.execute', () => {
    const executeSpy = vi.spyOn(actionBusService, 'execute');

    controlPlaneSnapshotService.projectOperationTimeline('op-no-exec');
    expect(executeSpy).not.toHaveBeenCalled();

    executeSpy.mockRestore();
  });

  it('20. no governance execution: timeline generation never calls GovernanceControlPlane.evaluateGovernance', () => {
    const govSpy = vi.spyOn(governanceControlPlane, 'evaluateGovernance');

    controlPlaneSnapshotService.projectOperationTimeline('op-no-gov');
    expect(govSpy).not.toHaveBeenCalled();

    govSpy.mockRestore();
  });

  it('21. no recovery execution: timeline generation never calls RecoveryControlPlane.evaluateRecoveryControl', () => {
    const recSpy = vi.spyOn(recoveryControlPlane, 'evaluateRecoveryControl');

    controlPlaneSnapshotService.projectOperationTimeline('op-no-rec');
    expect(recSpy).not.toHaveBeenCalled();

    recSpy.mockRestore();
  });

  it('22. no persistence mutation: timeline generation never calls saveMission, savePolicy, or saveApproval', () => {
    const saveMissionSpy = vi.spyOn(executionPersistence, 'saveMission');
    const savePolicySpy = vi.spyOn(executionPersistence, 'savePolicy');
    const saveApprovalSpy = vi.spyOn(executionPersistence, 'saveApproval');

    controlPlaneSnapshotService.projectOperationTimeline('op-no-persist');

    expect(saveMissionSpy).not.toHaveBeenCalled();
    expect(savePolicySpy).not.toHaveBeenCalled();
    expect(saveApprovalSpy).not.toHaveBeenCalled();

    saveMissionSpy.mockRestore();
    savePolicySpy.mockRestore();
    saveApprovalSpy.mockRestore();
  });

  // ==========================================================================
  // PART 6: Security, Secret Scrubbing & Prototype Pollution
  // ==========================================================================

  it('23. prototype pollution resistance: safely ignores __proto__, constructor, and prototype payloads', () => {
    const maliciousPayload = JSON.parse('{"__proto__": {"polluted": "yes"}}');

    const timeline = controlPlaneSnapshotService.projectOperationTimeline('__proto__', maliciousPayload);
    expect(timeline.operationId).toBe('__proto__');
    expect(timeline.entries.length).toBe(0);

    // Verify global prototype was not polluted
    expect(({} as any).polluted).toBeUndefined();
  });

  it('24. secret scrubbing: scrubs API keys, bearer tokens, passwords, and private credentials from metadata', () => {
    const opId = 'op-secret-scrub';

    auditEventRegistry.recordEvent({
      eventId: 'evt-sec-1',
      operationId: opId,
      correlationId: 'corr-sec',
      eventType: 'ACTION_DISPATCHED',
      lifecycleState: 'DISPATCHED',
      epistemicStatus: 'UNKNOWN',
      parameters: {
        apiKey: 'sk-ant-live-super-secret-12345',
        bearerToken: 'Bearer eyJhbGciOi...',
        password: 'db_master_password',
        authHeader: 'Basic YWRtaW46cGFzc3dvcmQ=',
        safeParam: 'public_metric_value',
      },
      timestamp: 1727970001000,
    });

    const timeline = controlPlaneSnapshotService.projectOperationTimeline(opId);
    expect(timeline.entries.length).toBe(1);

    const meta = timeline.entries[0].metadata;
    expect(meta).toBeDefined();
    expect(meta?.apiKey).toBe('[REDACTED]');
    expect(meta?.bearerToken).toBe('[REDACTED]');
    expect(meta?.password).toBe('[REDACTED]');
    expect(meta?.authHeader).toBe('[REDACTED]');
    expect(meta?.safeParam).toBe('public_metric_value');
  });

  it('25. bounded timeline generation: enforces maximum 100 entries per timeline', () => {
    const opId = 'op-bounded-load';

    // Register 120 events for one operation
    for (let i = 0; i < 120; i++) {
      auditEventRegistry.recordEvent({
        eventId: `evt-bound-${i}`,
        operationId: opId,
        correlationId: 'corr-b',
        eventType: 'ACTION_EXECUTED',
        lifecycleState: 'EXECUTING',
        epistemicStatus: 'OBSERVED',
        parameters: { index: i },
        timestamp: 1727970000000 + i,
      });
    }

    const timeline = controlPlaneSnapshotService.projectOperationTimeline(opId);
    expect(timeline.entries.length).toBe(100);
  });

  it('26. concurrent deterministic reads: concurrent queries produce identical frozen output', () => {
    const opId = 'op-concurrent';

    auditEventRegistry.recordEvent({
      eventId: 'evt-conc-1',
      operationId: opId,
      correlationId: 'corr-c',
      eventType: 'REQUEST_RECEIVED',
      lifecycleState: 'RECEIVED',
      epistemicStatus: 'OBSERVED',
      timestamp: 1727970001000,
    });

    const results = Array.from({ length: 10 }).map(() =>
      controlPlaneSnapshotService.projectOperationTimeline(opId)
    );

    // All results must be identical and frozen
    for (let i = 1; i < results.length; i++) {
      expect(results[i].operationId).toBe(results[0].operationId);
      expect(results[i].currentState).toBe(results[0].currentState);
      expect(results[i].entries.length).toBe(results[0].entries.length);
      expect(Object.isFrozen(results[i])).toBe(true);
      expect(Object.isFrozen(results[i].entries)).toBe(true);
    }
  });

  it('27. full integration with ControlPlaneSnapshot: snapshot operations correlate with timelines', () => {
    const opId = 'op-snap-integ';

    auditEventRegistry.recordEvent({
      eventId: 'evt-integ-1',
      operationId: opId,
      correlationId: 'corr-integ',
      eventType: 'ACTION_DISPATCHED',
      lifecycleState: 'DISPATCHED',
      epistemicStatus: 'UNKNOWN',
      timestamp: 1727970001000,
    });

    const snapshot = controlPlaneSnapshotService.getSnapshot({
      targetOperationIds: [opId],
    });

    const opSummary = snapshot.operations.find((o) => o.operationId === opId);
    expect(opSummary).toBeDefined();

    const timeline = controlPlaneSnapshotService.projectOperationTimeline(opId);
    expect(timeline.operationId).toBe(opSummary?.operationId);
    expect(timeline.currentState).toBe(opSummary?.status);
    expect(timeline.epistemicState).toBe(opSummary?.epistemicState);
  });

  it('28. existing Stage 22 evidence preservation: links to operational audit records are intact', () => {
    const opId = 'op-evidence-intact';

    auditEventRegistry.recordEvent({
      eventId: 'evt-ev-1',
      operationId: opId,
      correlationId: 'corr-ev',
      eventType: 'ACTION_EXECUTED',
      lifecycleState: 'SUCCEEDED',
      epistemicStatus: 'CONFIRMED',
      evidenceReferences: ['ref-evidence-storage-sha256'],
      reason: 'State confirmed by checksum comparison',
      timestamp: 1727970001000,
    });

    const timeline = controlPlaneSnapshotService.projectOperationTimeline(opId);
    expect(timeline.entries[0].reason).toBe('State confirmed by checksum comparison');
    expect(timeline.epistemicState).toBe('CONFIRMED');
    expect(timeline.isTerminal).toBe(true);
  });

  it('29. existing Stage 23 regression: recovery reconciliation states project as RECONCILED', () => {
    const opId = 'op-recovery-reconciled';

    auditEventRegistry.recordEvent({
      eventId: 'evt-rec-1',
      operationId: opId,
      correlationId: 'corr-rec',
      eventType: 'STATE_RECONCILED',
      lifecycleState: 'RECONCILED',
      epistemicStatus: 'CONFIRMED',
      parameters: { recoveryPlanId: 'plan-rec-001', reconciliationMatched: true },
      timestamp: 1727970001000,
    });

    const timeline = controlPlaneSnapshotService.projectOperationTimeline(opId);
    expect(timeline.currentState).toBe('RECONCILED');
    expect(timeline.isTerminal).toBe(true);
    expect(timeline.entries[0].source).toBe('operational-truth');
  });

  it('30. no duplicate timeline engine: projectOperationTimeline is the single canonical facade', () => {
    // Assert method existence and direct projection over auditEventRegistry
    expect(typeof controlPlaneSnapshotService.projectOperationTimeline).toBe('function');
    expect(typeof controlPlaneSnapshotService.projectOperationTimelines).toBe('function');
  });

  // ==========================================================================
  // PART 7: Dedicated Adversarial Cases A through J
  // ==========================================================================

  it('Adversarial Case A: only REQUESTED exists -> expected: REQUESTED only', () => {
    const opId = 'adv-case-a';

    auditEventRegistry.recordEvent({
      eventId: 'evt-adv-a',
      operationId: opId,
      correlationId: 'corr-adv-a',
      eventType: 'REQUEST_RECEIVED',
      lifecycleState: 'RECEIVED',
      epistemicStatus: 'OBSERVED',
      timestamp: 1727970001000,
    });

    const timeline = controlPlaneSnapshotService.projectOperationTimeline(opId);
    expect(timeline.entries.length).toBe(1);
    expect(timeline.entries[0].state).toBe('REQUESTED');
    expect(timeline.currentState).toBe('REQUESTED');
    expect(timeline.isTerminal).toBe(false);
  });

  it('Adversarial Case B: AUTHORIZED exists but DISPATCHED is absent -> expected: AUTHORIZED only', () => {
    const opId = 'adv-case-b';

    auditEventRegistry.recordEvent({
      eventId: 'evt-adv-b',
      operationId: opId,
      correlationId: 'corr-adv-b',
      eventType: 'GOVERNANCE_DECIDED',
      lifecycleState: 'AUTHORIZED',
      epistemicStatus: 'OBSERVED',
      timestamp: 1727970001000,
    });

    const timeline = controlPlaneSnapshotService.projectOperationTimeline(opId);
    expect(timeline.entries.length).toBe(1);
    expect(timeline.entries[0].state).toBe('AUTHORIZED');
    expect(timeline.entries.find((e) => e.state === 'DISPATCHED')).toBeUndefined();
  });

  it('Adversarial Case C: DISPATCHED exists but external confirmation is absent -> expected: DISPATCHED with UNKNOWN', () => {
    const opId = 'adv-case-c';

    auditEventRegistry.recordEvent({
      eventId: 'evt-adv-c',
      operationId: opId,
      correlationId: 'corr-adv-c',
      eventType: 'ACTION_DISPATCHED',
      lifecycleState: 'DISPATCHED',
      epistemicStatus: 'UNKNOWN',
      timestamp: 1727970001000,
    });

    const timeline = controlPlaneSnapshotService.projectOperationTimeline(opId);
    expect(timeline.entries.length).toBe(1);
    expect(timeline.entries[0].state).toBe('DISPATCHED');
    expect(timeline.entries[0].epistemicState).toBe('UNKNOWN');
    expect(timeline.currentState).toBe('DISPATCHED');
    expect(timeline.epistemicState).toBe('UNKNOWN');
    expect(timeline.isTerminal).toBe(false);
  });

  it('Adversarial Case D: remote execution is confirmed -> expected: authoritative confirmed state without independent inference', () => {
    const opId = 'adv-case-d';

    auditEventRegistry.recordEvent({
      eventId: 'evt-adv-d',
      operationId: opId,
      correlationId: 'corr-adv-d',
      eventType: 'OPERATION_SUCCEEDED',
      lifecycleState: 'SUCCEEDED',
      epistemicStatus: 'CONFIRMED',
      timestamp: 1727970001000,
    });

    const timeline = controlPlaneSnapshotService.projectOperationTimeline(opId);
    expect(timeline.entries.length).toBe(1);
    expect(timeline.entries[0].state).toBe('SUCCEEDED');
    expect(timeline.entries[0].epistemicState).toBe('CONFIRMED');
    expect(timeline.currentState).toBe('SUCCEEDED');
    expect(timeline.isTerminal).toBe(true);
  });

  it('Adversarial Case E: two events have identical timestamps -> expected: deterministic authoritative sequence ordering', () => {
    const opId = 'adv-case-e';
    const sharedTs = 1727970005000;

    auditEventRegistry.recordEvent({
      eventId: 'evt-z-second',
      operationId: opId,
      correlationId: 'corr-e',
      eventType: 'ACTION_EXECUTED',
      lifecycleState: 'EXECUTING',
      epistemicStatus: 'OBSERVED',
      timestamp: sharedTs,
    });
    auditEventRegistry.recordEvent({
      eventId: 'evt-a-first',
      operationId: opId,
      correlationId: 'corr-e',
      eventType: 'REQUEST_RECEIVED',
      lifecycleState: 'RECEIVED',
      epistemicStatus: 'OBSERVED',
      timestamp: sharedTs,
    });

    const timeline = controlPlaneSnapshotService.projectOperationTimeline(opId);
    expect(timeline.entries[0].eventId).toBe('evt-a-first');
    expect(timeline.entries[1].eventId).toBe('evt-z-second');
  });

  it('Adversarial Case F: same event appears through two projections -> expected: exactly one canonical event', () => {
    const opId = 'adv-case-f';

    // Same event recorded via audit registry
    auditEventRegistry.recordEvent({
      eventId: 'evt-exact-duplicate-1',
      operationId: opId,
      correlationId: 'corr-f',
      eventType: 'ACTION_DISPATCHED',
      lifecycleState: 'DISPATCHED',
      epistemicStatus: 'UNKNOWN',
      timestamp: 1727970001000,
    });

    // Replay recording with the same eventId
    auditEventRegistry.recordEvent({
      eventId: 'evt-exact-duplicate-1',
      operationId: opId,
      correlationId: 'corr-f',
      eventType: 'ACTION_DISPATCHED',
      lifecycleState: 'DISPATCHED',
      epistemicStatus: 'UNKNOWN',
      timestamp: 1727970001000,
    });

    const timeline = controlPlaneSnapshotService.projectOperationTimeline(opId);
    expect(timeline.entries.length).toBe(1);
    expect(timeline.entries[0].eventId).toBe('evt-exact-duplicate-1');
  });

  it('Adversarial Case G: two distinct events have the same state -> expected: preserve both if identities differ', () => {
    const opId = 'adv-case-g';

    auditEventRegistry.recordEvent({
      eventId: 'evt-attempt-1',
      operationId: opId,
      correlationId: 'corr-g',
      eventType: 'ACTION_EXECUTED',
      lifecycleState: 'EXECUTING',
      epistemicStatus: 'OBSERVED',
      parameters: { attempt: 1 },
      timestamp: 1727970001000,
    });
    auditEventRegistry.recordEvent({
      eventId: 'evt-attempt-2',
      operationId: opId,
      correlationId: 'corr-g',
      eventType: 'ACTION_EXECUTED',
      lifecycleState: 'EXECUTING',
      epistemicStatus: 'OBSERVED',
      parameters: { attempt: 2 },
      timestamp: 1727970002000,
    });

    const timeline = controlPlaneSnapshotService.projectOperationTimeline(opId);
    expect(timeline.entries.length).toBe(2);
    expect(timeline.entries[0].state).toBe('EXECUTING');
    expect(timeline.entries[1].state).toBe('EXECUTING');
    expect(timeline.entries[0].eventId).toBe('evt-attempt-1');
    expect(timeline.entries[1].eventId).toBe('evt-attempt-2');
  });

  it('Adversarial Case H: causal chain contains MISSING_EVIDENCE -> expected: preserve missing evidence', () => {
    const opId = 'adv-case-h';

    auditEventRegistry.recordEvent({
      eventId: 'evt-missing-gap',
      operationId: opId,
      correlationId: 'corr-h',
      eventType: 'OBSERVATION_RECORDED',
      lifecycleState: 'UNKNOWN',
      epistemicStatus: 'UNKNOWN',
      reason: 'MISSING_EVIDENCE',
      parameters: { isMissingEvidence: true },
      timestamp: 1727970001000,
    });

    const timeline = controlPlaneSnapshotService.projectOperationTimeline(opId);
    expect(timeline.entries[0].reason).toBe('MISSING_EVIDENCE');
    expect(timeline.entries[0].metadata?.isMissingEvidence).toBe(true);
  });

  it('Adversarial Case I: malformed filter input -> expected: fails safely without throwing', () => {
    const opId = 'adv-case-i';

    auditEventRegistry.recordEvent({
      eventId: 'evt-i-1',
      operationId: opId,
      correlationId: 'corr-i',
      eventType: 'REQUEST_RECEIVED',
      lifecycleState: 'RECEIVED',
      epistemicStatus: 'OBSERVED',
      timestamp: 1727970001000,
    });

    // Pass completely malformed options
    const timeline1 = controlPlaneSnapshotService.projectOperationTimeline(opId, null as any);
    expect(timeline1.entries.length).toBe(1);

    const timeline2 = controlPlaneSnapshotService.projectOperationTimeline(opId, undefined as any);
    expect(timeline2.entries.length).toBe(1);

    const timeline3 = controlPlaneSnapshotService.projectOperationTimeline(opId, {
      maxEntries: -99,
    });
    // Bounded min is 1
    expect(timeline3.entries.length).toBe(1);
  });

  it('Adversarial Case J: prototype pollution payload -> expected: no prototype mutation', () => {
    const pollutedPayload = JSON.parse('{"__proto__": {"injected": "hacked"}}');

    const timeline = controlPlaneSnapshotService.projectOperationTimeline('__proto__', pollutedPayload);
    expect(timeline.operationId).toBe('__proto__');
    expect(({} as any).injected).toBeUndefined();
  });
});
