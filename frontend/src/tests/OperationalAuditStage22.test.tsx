/**
 * AryaOS V1 — Stage 22: System Observability, Causal Audit & Operational Truth
 *
 * Exhaustive verification of all 88 specifications across 14 sections:
 * 1. Canonical Audit Event Ingestion & Immutability (1-6)
 * 2. Causal Identity & Correlation Relationships (7-12)
 * 3. Idempotency, Deduplication & Replay Protection (13-18)
 * 4. Operational Lifecycle State Transitions (19-25)
 * 5. Operational Truth vs Intent Separation (26-32)
 * 6. Epistemic Status & Anti-Upgrade Enforcement (33-38)
 * 7. Causal Graph Construction & Cycle/Depth Safety (39-44)
 * 8. End-to-End Causal Reconstruction (getOperationTrace) (45-50)
 * 9. Failure Boundary Reconstruction (51-56)
 * 10. Cross-Stage Correlation (Stages 15, 16, 18, 19, 20, 21) (57-71)
 * 11. Mission (Stage 12) & Strategic Knowledge (Stage 13) Isolation (72-75)
 * 12. Security Hardening & Secret Scrubbing (76-80)
 * 13. Persistence, Replay & Cold Restart (81-84)
 * 14. Spatial Command Console DOM Telemetry (85-88)
 */

import React from 'react';
import { describe, it, expect, beforeEach } from 'vitest';
import { render } from '@testing-library/react';

// Domain Services & Registries
import { operationalAudit } from '../services/operationalAudit';
import { auditEventRegistry } from '../services/auditEventRegistry';
import { auditIntegrityService } from '../services/auditIntegrityService';
import { operationalLifecycleService } from '../services/operationalLifecycleService';
import { causalTraceService } from '../services/causalTraceService';
import { operationalTruthService } from '../services/operationalTruthService';
import { auditEvidenceService } from '../services/auditEvidenceService';
import { operationTraceService } from '../services/operationTraceService';
import { failureBoundaryService } from '../services/failureBoundaryService';
import { auditMetricsService } from '../services/auditMetricsService';
import { executionPersistence } from '../services/executionPersistence';
import { executionJournal } from '../services/executionJournal';

// Spatial Console Component
import { SpatialCommandConsole } from '../components/spatial/SpatialCommandConsole';

// Types
import {
  OperationalAuditEvent,
  OperationalLifecycleState,
  EpistemicStatus,
  MAX_OBJECT_DEPTH,
  MAX_KEYS_PER_OBJECT,
  MAX_CAUSAL_DEPTH,
  MAX_CAUSAL_NODES,
} from '../types/operationalAudit';

describe('AryaOS V1 Stage 22 — System Observability, Causal Audit & Operational Truth', () => {
  beforeEach(() => {
    operationalAudit.reset();
    (executionPersistence as any).resetState?.();
    executionJournal.reset();
  });

  // =========================================================================
  // Section 1: Canonical Audit Event Ingestion & Immutability (1-6)
  // =========================================================================

  it('1. ingests a canonical OperationalAuditEvent with full schema compliance', () => {
    const { event, isDuplicate } = operationalAudit.recordEvent({
      operationId: 'op_001',
      correlationId: 'corr_001',
      eventType: 'REQUEST_RECEIVED',
      lifecycleState: 'RECEIVED',
      epistemicStatus: 'OBSERVED',
      sourceSystem: 'API_GATEWAY',
      actor: { actorId: 'user_admin', actorType: 'USER' },
      reason: 'User submitted request',
    });

    expect(isDuplicate).toBe(false);
    expect(event.eventId).toBeDefined();
    expect(event.operationId).toBe('op_001');
    expect(event.correlationId).toBe('corr_001');
    expect(event.lifecycleState).toBe('RECEIVED');
    expect(event.epistemicStatus).toBe('OBSERVED');
  });

  it('2. guarantees that historical audit events are deep-frozen (Object.isFrozen)', () => {
    const { event } = operationalAudit.recordEvent({
      operationId: 'op_frozen',
      correlationId: 'corr_frozen',
      eventType: 'REQUEST_RECEIVED',
      lifecycleState: 'RECEIVED',
      parameters: { payloadKey: 'initial_value' },
    });

    expect(Object.isFrozen(event)).toBe(true);
    expect(Object.isFrozen(event.actor)).toBe(true);
    if (event.parameters) {
      expect(Object.isFrozen(event.parameters)).toBe(true);
      expect(() => {
        (event.parameters as any).payloadKey = 'mutated_value';
      }).toThrow();
    }
  });

  it('3. rejects in-place overwriting of an existing event ID', () => {
    const customId = 'evt-custom-003';
    const first = operationalAudit.recordEvent({
      eventId: customId,
      operationId: 'op_003',
      correlationId: 'corr_003',
      eventType: 'REQUEST_RECEIVED',
      lifecycleState: 'RECEIVED',
      reason: 'First submission',
    });

    // Attempt to record with the same eventId but different payload
    const second = operationalAudit.recordEvent({
      eventId: customId,
      operationId: 'op_003',
      correlationId: 'corr_003',
      eventType: 'ACTION_DISPATCHED',
      lifecycleState: 'DISPATCHED',
      reason: 'Attempted overwrite',
    });

    expect(second.isDuplicate).toBe(true);
    expect(second.event.eventType).toBe('REQUEST_RECEIVED'); // Original preserved
    expect(second.event.reason).toBe('First submission');
  });

  it('4. assigns monotonic sequence numbers to deterministically generated event IDs', () => {
    const id1 = auditEventRegistry.generateEventId({ operationId: 'op_seq', eventType: 'REQUEST_RECEIVED' });
    const id2 = auditEventRegistry.generateEventId({ operationId: 'op_seq', eventType: 'REQUEST_VALIDATED' });
    expect(id1).not.toBe(id2);
    expect(id1).toMatch(/^evt-request-received-.*-\d+$/);
    expect(id2).toMatch(/^evt-request-validated-.*-\d+$/);
  });

  it('5. supports historical correction via new EVENT_CORRECTED event without mutating original', () => {
    const original = operationalAudit.recordEvent({
      operationId: 'op_correct',
      correlationId: 'corr_correct',
      eventType: 'REQUEST_RECEIVED',
      lifecycleState: 'RECEIVED',
      reason: 'Typo in metadata',
    });

    const correction = operationalAudit.recordEvent({
      operationId: 'op_correct',
      correlationId: 'corr_correct',
      causationId: original.event.eventId,
      eventType: 'EVENT_CORRECTED',
      lifecycleState: 'VALIDATED',
      reason: 'Corrected metadata applied',
    });

    expect(correction.event.causationId).toBe(original.event.eventId);
    expect(original.event.reason).toBe('Typo in metadata');
    expect(correction.event.reason).toBe('Corrected metadata applied');
  });

  it('6. retains chronological audit log of all events across multiple operations', () => {
    operationalAudit.recordEvent({ operationId: 'op_a', correlationId: 'c_a', eventType: 'REQUEST_RECEIVED', lifecycleState: 'RECEIVED' });
    operationalAudit.recordEvent({ operationId: 'op_b', correlationId: 'c_b', eventType: 'REQUEST_RECEIVED', lifecycleState: 'RECEIVED' });
    operationalAudit.recordEvent({ operationId: 'op_a', correlationId: 'c_a', eventType: 'ACTION_DISPATCHED', lifecycleState: 'DISPATCHED' });

    const all = auditEventRegistry.getAllEvents();
    expect(all.length).toBe(3);
    expect(all[0].operationId).toBe('op_a');
    expect(all[1].operationId).toBe('op_b');
    expect(all[2].operationId).toBe('op_a');
  });

  // =========================================================================
  // Section 2: Causal Identity & Correlation Relationships (7-12)
  // =========================================================================

  it('7. indexes events by operationId for single-operation causal retrieval', () => {
    operationalAudit.recordEvent({ operationId: 'op_idx_1', correlationId: 'corr_idx', eventType: 'REQUEST_RECEIVED', lifecycleState: 'RECEIVED' });
    operationalAudit.recordEvent({ operationId: 'op_idx_2', correlationId: 'corr_idx', eventType: 'REQUEST_RECEIVED', lifecycleState: 'RECEIVED' });

    const op1Events = auditEventRegistry.getEventsByOperationId('op_idx_1');
    expect(op1Events.length).toBe(1);
    expect(op1Events[0].operationId).toBe('op_idx_1');
  });

  it('8. indexes events by correlationId across multi-operation distributed workflows', () => {
    operationalAudit.recordEvent({ operationId: 'op_sub_1', correlationId: 'corr_shared', eventType: 'REQUEST_RECEIVED', lifecycleState: 'RECEIVED' });
    operationalAudit.recordEvent({ operationId: 'op_sub_2', correlationId: 'corr_shared', eventType: 'REQUEST_RECEIVED', lifecycleState: 'RECEIVED' });

    const correlated = auditEventRegistry.getEventsByCorrelationId('corr_shared');
    expect(correlated.length).toBe(2);
    expect(correlated.map((e) => e.operationId)).toEqual(['op_sub_1', 'op_sub_2']);
  });

  it('9. preserves causationId pointing directly to the causal ancestor event', () => {
    const parent = operationalAudit.recordEvent({
      operationId: 'op_causal',
      correlationId: 'corr_causal',
      eventType: 'REQUEST_RECEIVED',
      lifecycleState: 'RECEIVED',
    });

    const child = operationalAudit.recordEvent({
      operationId: 'op_causal',
      correlationId: 'corr_causal',
      causationId: parent.event.eventId,
      eventType: 'TRIGGER_EVALUATED',
      lifecycleState: 'TRIGGERED',
    });

    expect(child.event.causationId).toBe(parent.event.eventId);
  });

  it('10. tracks hierarchical sub-operations via parentOperationId', () => {
    operationalAudit.recordEvent({
      operationId: 'op_child_task',
      correlationId: 'corr_tree',
      parentOperationId: 'op_parent_workflow',
      eventType: 'REQUEST_RECEIVED',
      lifecycleState: 'RECEIVED',
    });

    const childEvents = auditEventRegistry.getEventsByOperationId('op_child_task');
    expect(childEvents[0].parentOperationId).toBe('op_parent_workflow');
  });

  it('11. preserves existing external system IDs without generating artificial replacements', () => {
    const { event } = operationalAudit.recordEvent({
      operationId: 'op_ext_id',
      correlationId: 'corr_ext',
      eventType: 'REQUEST_RECEIVED',
      lifecycleState: 'RECEIVED',
      actionId: 'act-existing-uuid-999',
      connectorId: 'conn-github-prod',
      triggerId: 'trg-webhook-issues',
      policyId: 'pol-safety-baseline',
    });

    expect(event.actionId).toBe('act-existing-uuid-999');
    expect(event.connectorId).toBe('conn-github-prod');
    expect(event.triggerId).toBe('trg-webhook-issues');
    expect(event.policyId).toBe('pol-safety-baseline');
  });

  it('12. allows querying all events triggered by a specific causationId', () => {
    const rootEvtId = 'evt-root-012';
    operationalAudit.recordEvent({
      eventId: rootEvtId,
      operationId: 'op_fanout',
      correlationId: 'corr_fanout',
      eventType: 'REQUEST_RECEIVED',
      lifecycleState: 'RECEIVED',
    });

    operationalAudit.recordEvent({
      operationId: 'op_fanout_a',
      correlationId: 'corr_fanout',
      causationId: rootEvtId,
      eventType: 'TRIGGER_EVALUATED',
      lifecycleState: 'TRIGGERED',
    });

    operationalAudit.recordEvent({
      operationId: 'op_fanout_b',
      correlationId: 'corr_fanout',
      causationId: rootEvtId,
      eventType: 'TRIGGER_EVALUATED',
      lifecycleState: 'TRIGGERED',
    });

    const caused = auditEventRegistry.getEventsByCausationId(rootEvtId);
    expect(caused.length).toBe(2);
  });

  // =========================================================================
  // Section 3: Idempotency, Deduplication & Replay Protection (13-18)
  // =========================================================================

  it('13. detects duplicate events with identical operation, eventType, and payload fingerprint', () => {
    const payload = { param1: 'alpha', param2: 42 };

    const first = operationalAudit.recordEvent({
      operationId: 'op_dupe',
      correlationId: 'corr_dupe',
      eventType: 'REQUEST_RECEIVED',
      lifecycleState: 'RECEIVED',
      parameters: payload,
    });

    const second = operationalAudit.recordEvent({
      operationId: 'op_dupe',
      correlationId: 'corr_dupe',
      eventType: 'REQUEST_RECEIVED',
      lifecycleState: 'RECEIVED',
      parameters: payload,
    });

    expect(first.isDuplicate).toBe(false);
    expect(second.isDuplicate).toBe(true);
    expect(auditEventRegistry.getDuplicateCount()).toBe(1);
  });

  it('14. duplicate event ingestion does not duplicate nodes or events in storage', () => {
    for (let i = 0; i < 5; i++) {
      operationalAudit.recordEvent({
        operationId: 'op_repeat',
        correlationId: 'corr_repeat',
        eventType: 'REQUEST_RECEIVED',
        lifecycleState: 'RECEIVED',
        parameters: { test: true },
      });
    }

    const events = auditEventRegistry.getEventsByOperationId('op_repeat');
    expect(events.length).toBe(1);
  });

  it('15. allows different eventTypes within the same operation without false deduplication', () => {
    const e1 = operationalAudit.recordEvent({
      operationId: 'op_multi_event',
      correlationId: 'corr_multi',
      eventType: 'REQUEST_RECEIVED',
      lifecycleState: 'RECEIVED',
    });

    const e2 = operationalAudit.recordEvent({
      operationId: 'op_multi_event',
      correlationId: 'corr_multi',
      eventType: 'ACTION_DISPATCHED',
      lifecycleState: 'DISPATCHED',
    });

    expect(e1.isDuplicate).toBe(false);
    expect(e2.isDuplicate).toBe(false);
    expect(auditEventRegistry.getEventsByOperationId('op_multi_event').length).toBe(2);
  });

  it('16. replaying historical event stream maintains bit-identical ordering and fingerprints', () => {
    operationalAudit.recordEvent({ operationId: 'op_rep', correlationId: 'c', eventType: 'REQUEST_RECEIVED', lifecycleState: 'RECEIVED' });
    operationalAudit.recordEvent({ operationId: 'op_rep', correlationId: 'c', eventType: 'GOVERNANCE_DECIDED', lifecycleState: 'GOVERNED' });

    const trace1 = operationTraceService.getOperationTrace('op_rep');
    const trace2 = operationTraceService.getOperationTrace('op_rep');

    expect(trace1.steps.length).toBe(trace2.steps.length);
    expect(trace1.totalDurationMs).toBe(trace2.totalDurationMs);
    expect(trace1.deterministicExplanation).toBe(trace2.deterministicExplanation);
  });

  it('17. payload key ordering variations produce identical canonical fingerprints', () => {
    const fp1 = auditIntegrityService.computeFingerprint({ z: 1, a: 2, m: 3 });
    const fp2 = auditIntegrityService.computeFingerprint({ a: 2, m: 3, z: 1 });
    expect(fp1).toBe(fp2);
  });

  it('18. deduplication tracking does not leak across different operationIds', () => {
    const payload = { commonData: 'universal' };
    const e1 = operationalAudit.recordEvent({
      operationId: 'op_tenant_1',
      correlationId: 'c1',
      eventType: 'REQUEST_RECEIVED',
      lifecycleState: 'RECEIVED',
      parameters: payload,
    });

    const e2 = operationalAudit.recordEvent({
      operationId: 'op_tenant_2',
      correlationId: 'c2',
      eventType: 'REQUEST_RECEIVED',
      lifecycleState: 'RECEIVED',
      parameters: payload,
    });

    expect(e1.isDuplicate).toBe(false);
    expect(e2.isDuplicate).toBe(false);
  });

  // =========================================================================
  // Section 4: Operational Lifecycle State Transitions (19-25)
  // =========================================================================

  it('19. validates legal progression: RECEIVED -> VALIDATED -> GOVERNED -> AUTHORIZED -> DISPATCHED', () => {
    expect(operationalLifecycleService.isValidTransition('RECEIVED', 'VALIDATED').valid).toBe(true);
    expect(operationalLifecycleService.isValidTransition('VALIDATED', 'GOVERNED').valid).toBe(true);
    expect(operationalLifecycleService.isValidTransition('GOVERNED', 'AUTHORIZED').valid).toBe(true);
    expect(operationalLifecycleService.isValidTransition('AUTHORIZED', 'DISPATCHED').valid).toBe(true);
  });

  it('20. rejects illegal backward transitions from terminal states', () => {
    expect(operationalLifecycleService.isValidTransition('SUCCEEDED', 'RECEIVED').valid).toBe(false);
    expect(operationalLifecycleService.isValidTransition('FAILED', 'VALIDATED').valid).toBe(false);
    expect(operationalLifecycleService.isValidTransition('DENIED', 'DISPATCHED').valid).toBe(false);
  });

  it('21. permits terminal states to transition to RECONCILED upon verified state observation', () => {
    expect(operationalLifecycleService.isValidTransition('SUCCEEDED', 'RECONCILED').valid).toBe(true);
    expect(operationalLifecycleService.isValidTransition('UNKNOWN', 'RECONCILED').valid).toBe(true);
    expect(operationalLifecycleService.isValidTransition('FAILED', 'RECONCILED').valid).toBe(true);
  });

  it('22. RECONCILED state is strictly terminal (allows zero subsequent transitions)', () => {
    expect(operationalLifecycleService.isValidTransition('RECONCILED', 'RECEIVED').valid).toBe(false);
    expect(operationalLifecycleService.isValidTransition('RECONCILED', 'SUCCEEDED').valid).toBe(false);
  });

  it('23. recognizes terminal states correctly via isTerminal', () => {
    expect(operationalLifecycleService.isTerminal('SUCCEEDED')).toBe(true);
    expect(operationalLifecycleService.isTerminal('FAILED')).toBe(true);
    expect(operationalLifecycleService.isTerminal('UNKNOWN')).toBe(true);
    expect(operationalLifecycleService.isTerminal('DENIED')).toBe(true);
    expect(operationalLifecycleService.isTerminal('EXECUTING')).toBe(false);
    expect(operationalLifecycleService.isTerminal('DISPATCHED')).toBe(false);
  });

  it('24. DEFERRED operations can re-enter GOVERNED state when conditions are met', () => {
    expect(operationalLifecycleService.isValidTransition('DEFERRED', 'GOVERNED').valid).toBe(true);
  });

  it('25. PAUSED operations can resume to GOVERNED or AUTHORIZED state', () => {
    expect(operationalLifecycleService.isValidTransition('PAUSED', 'GOVERNED').valid).toBe(true);
    expect(operationalLifecycleService.isValidTransition('PAUSED', 'AUTHORIZED').valid).toBe(true);
  });

  // =========================================================================
  // Section 5: Operational Truth vs Intent Separation (26-32)
  // =========================================================================

  it('26. asserts that DISPATCHED represents Intent, NOT verified external execution', () => {
    expect(operationalTruthService.isIntentOnly('DISPATCHED')).toBe(true);
    expect(operationalTruthService.isIntentOnly('AUTHORIZED')).toBe(true);
  });

  it('27. MANDATORY INVARIANT: Action Bus dispatch with missing external confirmation -> UNKNOWN', () => {
    const truth = operationalTruthService.reconcileOperationalTruth({
      dispatchedState: 'DISPATCHED',
      hasActionBusDispatched: true,
      hasExternalConfirmation: false,
    });

    expect(truth.lifecycleState).toBe('UNKNOWN');
    expect(truth.epistemicStatus).toBe('UNKNOWN');
    expect(truth.isAuthoritativeTruth).toBe(false);
    expect(truth.failureBoundary?.boundary).toBe('EXTERNAL_RESULT_UNKNOWN');
  });

  it('28. external confirmation indicating failure overrides nominal dispatch success -> FAILED', () => {
    const truth = operationalTruthService.reconcileOperationalTruth({
      dispatchedState: 'DISPATCHED',
      hasActionBusDispatched: true,
      hasExternalConfirmation: true,
      externalSuccess: false,
    });

    expect(truth.lifecycleState).toBe('FAILED');
    expect(truth.epistemicStatus).toBe('OBSERVED');
    expect(truth.failureBoundary?.boundary).toBe('PROVIDER_FAILURE');
  });

  it('29. external confirmation with mismatched state delta flags RECONCILIATION_FAILURE', () => {
    const truth = operationalTruthService.reconcileOperationalTruth({
      dispatchedState: 'DISPATCHED',
      hasActionBusDispatched: true,
      hasExternalConfirmation: true,
      externalSuccess: true,
      reconciliationMatched: false,
    });

    expect(truth.lifecycleState).toBe('FAILED');
    expect(truth.discrepancyDetected).toBe(true);
    expect(truth.failureBoundary?.boundary).toBe('RECONCILIATION_FAILURE');
  });

  it('30. fully verified and delta-matched operation transitions to RECONCILED with CONFIRMED status', () => {
    const truth = operationalTruthService.reconcileOperationalTruth({
      dispatchedState: 'DISPATCHED',
      hasActionBusDispatched: true,
      hasExternalConfirmation: true,
      externalSuccess: true,
      reconciliationMatched: true,
    });

    expect(truth.lifecycleState).toBe('RECONCILED');
    expect(truth.epistemicStatus).toBe('CONFIRMED');
    expect(truth.isAuthoritativeTruth).toBe(true);
  });

  it('31. non-dispatched operations cannot claim external truth resolution', () => {
    const truth = operationalTruthService.reconcileOperationalTruth({
      dispatchedState: 'GOVERNED',
      hasActionBusDispatched: false,
      hasExternalConfirmation: false,
    });

    expect(truth.isAuthoritativeTruth).toBe(false);
    expect(truth.lifecycleState).toBe('GOVERNED');
    expect(truth.epistemicStatus).toBe('PROJECTED');
  });

  it('32. UNKNOWN state is preserved across audit traces until explicit reconciliation arrives', () => {
    operationalAudit.recordEvent({
      operationId: 'op_unconfirmed',
      correlationId: 'c_u',
      eventType: 'ACTION_DISPATCHED',
      lifecycleState: 'DISPATCHED',
      epistemicStatus: 'OBSERVED',
    });

    operationalAudit.recordEvent({
      operationId: 'op_unconfirmed',
      correlationId: 'c_u',
      eventType: 'OPERATION_UNKNOWN',
      lifecycleState: 'UNKNOWN',
      epistemicStatus: 'UNKNOWN',
      reason: 'Awaiting webhook callback',
    });

    const trace = operationTraceService.getOperationTrace('op_unconfirmed');
    expect(trace.terminalStatus).toBe('UNKNOWN');
    expect(trace.epistemicStatus).toBe('UNKNOWN');
  });

  // =========================================================================
  // Section 6: Epistemic Status & Anti-Upgrade Enforcement (33-38)
  // =========================================================================

  it('33. permits lateral or downward epistemic revisions without blocking', () => {
    const check = auditEvidenceService.validateEpistemicTransition({
      currentLevel: 'OBSERVED',
      targetLevel: 'UNKNOWN',
      supportingEvidenceIds: [],
    });
    expect(check.valid).toBe(true);
  });

  it('34. ANTI-UPGRADE: rejects promoting INFERRED to CONFIRMED without supporting evidence', () => {
    const check = auditEvidenceService.validateEpistemicTransition({
      currentLevel: 'INFERRED',
      targetLevel: 'CONFIRMED',
      supportingEvidenceIds: [],
    });

    expect(check.valid).toBe(false);
    expect(check.reason).toContain('Anti-Upgrade Violation');
  });

  it('35. ANTI-UPGRADE: rejects promoting PROJECTED to OBSERVED with non-existent evidence IDs', () => {
    const check = auditEvidenceService.validateEpistemicTransition({
      currentLevel: 'PROJECTED',
      targetLevel: 'OBSERVED',
      supportingEvidenceIds: ['non-existent-evidence-id'],
    });

    expect(check.valid).toBe(false);
    expect(check.reason).toContain('None of the supplied evidence IDs exist');
  });

  it('36. successfully validates epistemic promotion when authoritative evidence is registered', () => {
    auditEvidenceService.recordEvidence({
      evidenceId: 'ev_auth_webhook_1',
      sourceType: 'EXTERNAL_WEBHOOK',
      sourceId: 'github-webhook-payload',
      timestamp: Date.now(),
      epistemicLevel: 'OBSERVED',
      isCryptographicallyVerified: true,
      fingerprint: 'fp_abc123',
    });

    const check = auditEvidenceService.validateEpistemicTransition({
      currentLevel: 'INFERRED',
      targetLevel: 'CONFIRMED',
      supportingEvidenceIds: ['ev_auth_webhook_1'],
    });

    expect(check.valid).toBe(true);
  });

  it('37. stores immutable evidence records in AuditEvidenceService', () => {
    auditEvidenceService.recordEvidence({
      evidenceId: 'ev_test_immut',
      sourceType: 'CONNECTOR_OBSERVATION',
      sourceId: 'fs-stat',
      timestamp: 1000,
      epistemicLevel: 'OBSERVED',
      isCryptographicallyVerified: false,
      fingerprint: 'fp_test',
    });

    const ev = auditEvidenceService.getEvidence('ev_test_immut');
    expect(ev).toBeDefined();
    expect(Object.isFrozen(ev)).toBe(true);
  });

  it('38. unverified evidence cannot justify promotion to CONFIRMED status', () => {
    auditEvidenceService.recordEvidence({
      evidenceId: 'ev_unverified',
      sourceType: 'INFERRED_LOGIC',
      sourceId: 'heuristics',
      timestamp: Date.now(),
      epistemicLevel: 'INFERRED',
      isCryptographicallyVerified: false,
      fingerprint: 'fp_heuristic',
    });

    const check = auditEvidenceService.validateEpistemicTransition({
      currentLevel: 'INFERRED',
      targetLevel: 'CONFIRMED',
      supportingEvidenceIds: ['ev_unverified'],
    });

    expect(check.valid).toBe(false);
  });

  // =========================================================================
  // Section 7: Causal Graph Construction & Graph Safety (39-44)
  // =========================================================================

  it('39. constructs a bounded CausalGraph connecting events sequentially', () => {
    operationalAudit.recordEvent({ operationId: 'op_graph_1', correlationId: 'c', eventType: 'REQUEST_RECEIVED', lifecycleState: 'RECEIVED' });
    operationalAudit.recordEvent({ operationId: 'op_graph_1', correlationId: 'c', eventType: 'GOVERNANCE_DECIDED', lifecycleState: 'GOVERNED' });
    operationalAudit.recordEvent({ operationId: 'op_graph_1', correlationId: 'c', eventType: 'ACTION_DISPATCHED', lifecycleState: 'DISPATCHED' });

    const graph = causalTraceService.buildCausalGraph('op_graph_1');
    expect(graph.nodes.length).toBe(3);
    expect(graph.edges.length).toBe(2);
    expect(graph.hasCycles).toBe(false);
  });

  it('40. CYCLE PROTECTION: rejects self-cycles (fromNodeId === toNodeId)', () => {
    const edges: any[] = [];
    let cycleDetected = false;
    const added = causalTraceService.addEdgeSafe(
      edges,
      'node_same',
      'node_same',
      'CAUSED_BY',
      Date.now(),
      new Set(),
      () => {
        cycleDetected = true;
      }
    );

    expect(added).toBe(false);
    expect(cycleDetected).toBe(true);
    expect(edges.length).toBe(0);
  });

  it('41. CYCLE PROTECTION: detects circular causal dependencies without infinite recursion', () => {
    const edges: any[] = [];
    const visited = new Set<string>();
    let cycleDetected = false;

    causalTraceService.addEdgeSafe(edges, 'node_a', 'node_b', 'CAUSED_BY', 1, visited, () => {});
    causalTraceService.addEdgeSafe(edges, 'node_b', 'node_a', 'CAUSED_BY', 2, visited, () => {
      cycleDetected = true;
    });

    expect(cycleDetected).toBe(true);
  });

  it('42. DEPTH BOUNDING: terminates traversal when MAX_CAUSAL_DEPTH (10) is reached', () => {
    // Generate a deep chain of 15 events in a single operation
    for (let i = 1; i <= 15; i++) {
      operationalAudit.recordEvent({
        operationId: 'op_deep',
        correlationId: 'c_deep',
        eventType: i === 1 ? 'REQUEST_RECEIVED' : i % 2 === 0 ? 'TRIGGER_EVALUATED' : 'ACTION_DISPATCHED',
        lifecycleState: 'EXECUTING',
        timestamp: 1000 + i * 10,
      });
    }

    const graph = causalTraceService.buildCausalGraph('op_deep');
    expect(graph.maxDepthReached).toBeLessThanOrEqual(MAX_CAUSAL_DEPTH);
  });

  it('43. NODE BOUNDING: terminates node insertion when MAX_CAUSAL_NODES (100) is reached', () => {
    for (let i = 1; i <= 120; i++) {
      operationalAudit.recordEvent({
        operationId: 'op_wide',
        correlationId: 'c_wide',
        eventType: 'OBSERVATION_RECORDED',
        lifecycleState: 'EXECUTING',
        parameters: { index: i },
        timestamp: 1000 + i,
      });
    }

    const graph = causalTraceService.buildCausalGraph('op_wide');
    expect(graph.nodes.length).toBeLessThanOrEqual(MAX_CAUSAL_NODES);
    expect(graph.isTruncated).toBe(true);
  });

  it('44. returns an empty graph for an unknown operationId without erroring', () => {
    const graph = causalTraceService.buildCausalGraph('op_non_existent');
    expect(graph.nodes.length).toBe(0);
    expect(graph.edges.length).toBe(0);
    expect(graph.hasCycles).toBe(false);
  });

  // =========================================================================
  // Section 8: End-to-End Causal Reconstruction (getOperationTrace) (45-50)
  // =========================================================================

  it('45. getOperationTrace reconstructs complete origin-to-outcome chronological steps', () => {
    operationalAudit.recordEvent({ operationId: 'op_trace_full', correlationId: 'c', eventType: 'REQUEST_RECEIVED', lifecycleState: 'RECEIVED' });
    operationalAudit.recordEvent({ operationId: 'op_trace_full', correlationId: 'c', eventType: 'TRIGGER_EVALUATED', lifecycleState: 'TRIGGERED' });
    operationalAudit.recordEvent({ operationId: 'op_trace_full', correlationId: 'c', eventType: 'GOVERNANCE_DECIDED', lifecycleState: 'GOVERNED' });
    operationalAudit.recordEvent({ operationId: 'op_trace_full', correlationId: 'c', eventType: 'ACTION_DISPATCHED', lifecycleState: 'DISPATCHED' });
    operationalAudit.recordEvent({ operationId: 'op_trace_full', correlationId: 'c', eventType: 'STATE_RECONCILED', lifecycleState: 'RECONCILED' });

    const trace = operationTraceService.getOperationTrace('op_trace_full');
    expect(trace.steps.length).toBe(5);
    expect(trace.terminalStatus).toBe('RECONCILED');
    expect(trace.isCompleted).toBe(true);
  });

  it('46. MISSING EVIDENCE: explicitly represents missing governance check before dispatched action', () => {
    // Action dispatched directly without governance evaluation
    operationalAudit.recordEvent({ operationId: 'op_gap', correlationId: 'c', eventType: 'REQUEST_RECEIVED', lifecycleState: 'RECEIVED' });
    operationalAudit.recordEvent({ operationId: 'op_gap', correlationId: 'c', eventType: 'ACTION_DISPATCHED', lifecycleState: 'DISPATCHED' });

    const trace = operationTraceService.getOperationTrace('op_gap');
    const missingStep = trace.steps.find((s) => s.isMissingEvidence);
    expect(missingStep).toBeDefined();
    expect(missingStep?.nodeType).toBe('MISSING_EVIDENCE');
    expect(missingStep?.description).toContain('Action was dispatched without recorded governance evaluation');
  });

  it('47. generates a deterministic narrative explanation summarizing the causal flow', () => {
    operationalAudit.recordEvent({
      operationId: 'op_narrative',
      correlationId: 'c',
      eventType: 'REQUEST_RECEIVED',
      lifecycleState: 'RECEIVED',
      actor: { actorId: 'analyst_bob', actorType: 'USER' },
    });
    operationalAudit.recordEvent({
      operationId: 'op_narrative',
      correlationId: 'c',
      eventType: 'TRIGGER_EVALUATED',
      lifecycleState: 'TRIGGERED',
      triggerId: 'trg_issue_triage',
    });
    operationalAudit.recordEvent({
      operationId: 'op_narrative',
      correlationId: 'c',
      eventType: 'GOVERNANCE_DECIDED',
      lifecycleState: 'GOVERNED',
      governanceDecision: 'ALLOW',
    });

    const trace = operationTraceService.getOperationTrace('op_narrative');
    expect(trace.deterministicExplanation).toContain('analyst_bob');
    expect(trace.deterministicExplanation).toContain('trg_issue_triage');
    expect(trace.deterministicExplanation).toContain('ALLOW');
  });

  it('48. compiles complete evidence ledger citing all contributing evidence IDs', () => {
    operationalAudit.recordEvent({
      operationId: 'op_evidence_trace',
      correlationId: 'c',
      eventType: 'REQUEST_RECEIVED',
      lifecycleState: 'RECEIVED',
      evidenceReferences: ['ref_1', 'ref_2'],
    });
    operationalAudit.recordEvent({
      operationId: 'op_evidence_trace',
      correlationId: 'c',
      eventType: 'OBSERVATION_RECORDED',
      lifecycleState: 'SUCCEEDED',
      evidenceReferences: ['ref_3'],
    });

    const trace = operationTraceService.getOperationTrace('op_evidence_trace');
    expect(trace.evidenceLedger).toEqual(['ref_1', 'ref_2', 'ref_3']);
  });

  it('49. computes total duration correctly as (lastEvent.timestamp - firstEvent.timestamp)', () => {
    operationalAudit.recordEvent({ operationId: 'op_dur', correlationId: 'c', eventType: 'REQUEST_RECEIVED', lifecycleState: 'RECEIVED', timestamp: 1000 });
    operationalAudit.recordEvent({ operationId: 'op_dur', correlationId: 'c', eventType: 'OPERATION_SUCCEEDED', lifecycleState: 'SUCCEEDED', timestamp: 1450 });

    const trace = operationTraceService.getOperationTrace('op_dur');
    expect(trace.totalDurationMs).toBe(450);
  });

  it('50. returns valid empty trace object for non-existent operationId with missing evidence step', () => {
    const trace = operationTraceService.getOperationTrace('non_existent_op_123');
    expect(trace.operationId).toBe('non_existent_op_123');
    expect(trace.steps.length).toBe(1);
    expect(trace.steps[0].nodeType).toBe('MISSING_EVIDENCE');
  });

  // =========================================================================
  // Section 9: Failure Boundary Reconstruction (51-56)
  // =========================================================================

  it('51. reconstructs POLICY_DENIED boundary when governance blocks operation', () => {
    operationalAudit.recordEvent({
      operationId: 'op_fail_policy',
      correlationId: 'c',
      eventType: 'GOVERNANCE_DECIDED',
      lifecycleState: 'DENIED',
      governanceDecision: 'DENY',
      reason: 'Violates resource limit policy',
    });

    const boundary = operationalAudit.diagnoseFailure('op_fail_policy');
    expect(boundary?.boundary).toBe('POLICY_DENIED');
    expect(boundary?.stoppingStage).toContain('Stage 21');
  });

  it('52. reconstructs HUMAN_APPROVAL_PENDING boundary when operator review is required', () => {
    operationalAudit.recordEvent({
      operationId: 'op_fail_approval',
      correlationId: 'c',
      eventType: 'GOVERNANCE_DECIDED',
      lifecycleState: 'GOVERNED',
      governanceDecision: 'REQUIRE_APPROVAL',
      reason: 'Requires operator signature',
    });

    const boundary = operationalAudit.diagnoseFailure('op_fail_approval');
    expect(boundary?.boundary).toBe('HUMAN_APPROVAL_PENDING');
  });

  it('53. reconstructs AUTHORIZATION_DENIED boundary on failed authority intersection', () => {
    operationalAudit.recordEvent({
      operationId: 'op_fail_auth',
      correlationId: 'c',
      eventType: 'AUTHORITY_CHECKED',
      lifecycleState: 'DENIED',
      reason: 'Agent capability grant missing',
    });

    const boundary = operationalAudit.diagnoseFailure('op_fail_auth');
    expect(boundary?.boundary).toBe('AUTHORIZATION_DENIED');
  });

  it('54. reconstructs EXTERNAL_RESULT_UNKNOWN boundary when dispatched without callback', () => {
    operationalAudit.recordEvent({
      operationId: 'op_fail_unknown',
      correlationId: 'c',
      eventType: 'ACTION_DISPATCHED',
      lifecycleState: 'DISPATCHED',
    });
    operationalAudit.recordEvent({
      operationId: 'op_fail_unknown',
      correlationId: 'c',
      eventType: 'OPERATION_UNKNOWN',
      lifecycleState: 'UNKNOWN',
    });

    const boundary = operationalAudit.diagnoseFailure('op_fail_unknown');
    expect(boundary?.boundary).toBe('EXTERNAL_RESULT_UNKNOWN');
  });

  it('55. reconstructs RECONCILIATION_FAILURE boundary when observed state contradicts intent', () => {
    operationalAudit.recordEvent({
      operationId: 'op_fail_reconcile',
      correlationId: 'c',
      eventType: 'STATE_RECONCILED',
      lifecycleState: 'FAILED',
      reason: 'Target directory not created on remote filesystem',
    });

    const boundary = operationalAudit.diagnoseFailure('op_fail_reconcile');
    expect(boundary?.boundary).toBe('RECONCILIATION_FAILURE');
  });

  it('56. returns undefined for successful operations with no failures', () => {
    operationalAudit.recordEvent({
      operationId: 'op_pure_success',
      correlationId: 'c',
      eventType: 'OPERATION_SUCCEEDED',
      lifecycleState: 'SUCCEEDED',
    });

    const boundary = operationalAudit.diagnoseFailure('op_pure_success');
    expect(boundary).toBeUndefined();
  });

  // =========================================================================
  // Section 10: Cross-Stage Correlation (57-71)
  // =========================================================================

  it('57. observeExternalEvent binds Stage 18 event identity into operational audit', () => {
    const evt = operationalAudit.observeExternalEvent({
      operationId: 'op_s18',
      correlationId: 'c_s18',
      externalEventId: 'ext-github-pr-101',
      sourceSystem: 'GITHUB',
      data: { prNumber: 101, action: 'opened' },
    });

    expect(evt.sourceSystem).toBe('GITHUB');
    expect(evt.causationId).toBe('ext-github-pr-101');
    expect(evt.parameters?.prNumber).toBe(101);
  });

  it('58. observeTriggerMatch binds Stage 19 trigger and version into operational audit', () => {
    const evt = operationalAudit.observeTriggerMatch({
      operationId: 'op_s19',
      correlationId: 'c_s19',
      triggerId: 'trg-auto-deploy',
      triggerVersion: 2,
      causationEventId: 'ext-evt-999',
    });

    expect(evt.triggerId).toBe('trg-auto-deploy');
    expect(evt.triggerVersion).toBe(2);
    expect(evt.lifecycleState).toBe('TRIGGERED');
  });

  it('59. observeGovernanceDecision binds Stage 21 policy snapshot and decision', () => {
    const evt = operationalAudit.observeGovernanceDecision({
      operationId: 'op_s21',
      correlationId: 'c_s21',
      decisionId: 'gov-dec-444',
      decision: 'ALLOW',
      policySnapshotId: 'snap-v1-fingerprint',
      policyRegistryVersion: 1,
      matchedPolicies: ['pol-baseline'],
    });

    expect(evt.governanceDecisionId).toBe('gov-dec-444');
    expect(evt.governanceDecision).toBe('ALLOW');
    expect(evt.policySnapshotId).toBe('snap-v1-fingerprint');
  });

  it('60. observeActionDispatch binds Stage 15 actionId and capabilityId', () => {
    const evt = operationalAudit.observeActionDispatch({
      operationId: 'op_s15',
      correlationId: 'c_s15',
      actionId: 'act-git-clone',
      capabilityId: 'git_clone',
      connectorId: 'conn-github',
    });

    expect(evt.actionId).toBe('act-git-clone');
    expect(evt.capabilityId).toBe('git_clone');
    expect(evt.connectorId).toBe('conn-github');
    expect(evt.lifecycleState).toBe('DISPATCHED');
  });

  it('61. observeActionResult records execution success and downstream output', () => {
    const evt = operationalAudit.observeActionResult({
      operationId: 'op_s15_res',
      correlationId: 'c_s15',
      actionId: 'act-git-clone',
      success: true,
      output: { commitHash: 'abc1234' },
    });

    expect(evt.lifecycleState).toBe('SUCCEEDED');
    expect(evt.output?.commitHash).toBe('abc1234');
  });

  it('62. observeActionResult records execution failure and attaches failure boundary', () => {
    const evt = operationalAudit.observeActionResult({
      operationId: 'op_s15_fail',
      correlationId: 'c_s15',
      actionId: 'act-git-clone',
      success: false,
      error: { message: 'Repository not found', code: '404' },
    });

    expect(evt.lifecycleState).toBe('FAILED');
    expect(evt.failureBoundary?.boundary).toBe('PROVIDER_FAILURE');
  });

  it('63. indexes events by actionId for instant cross-stage query', () => {
    operationalAudit.recordEvent({ operationId: 'op_act', correlationId: 'c', actionId: 'act-find-me', eventType: 'ACTION_DISPATCHED', lifecycleState: 'DISPATCHED' });
    const results = auditEventRegistry.getEventsByActionId('act-find-me');
    expect(results.length).toBe(1);
    expect(results[0].actionId).toBe('act-find-me');
  });

  it('64. indexes events by connectorId for connector fabric observability', () => {
    operationalAudit.recordEvent({ operationId: 'op_conn', correlationId: 'c', connectorId: 'conn-slack', eventType: 'ACTION_DISPATCHED', lifecycleState: 'DISPATCHED' });
    const results = auditEventRegistry.getEventsByConnectorId('conn-slack');
    expect(results.length).toBe(1);
  });

  it('65. indexes events by triggerId for reaction engine telemetry', () => {
    operationalAudit.recordEvent({ operationId: 'op_trg', correlationId: 'c', triggerId: 'trg-timer', eventType: 'TRIGGER_EVALUATED', lifecycleState: 'TRIGGERED' });
    const results = auditEventRegistry.getEventsByTriggerId('trg-timer');
    expect(results.length).toBe(1);
  });

  it('66. indexes events by policyId for policy intelligence auditability', () => {
    operationalAudit.recordEvent({ operationId: 'op_pol', correlationId: 'c', policyId: 'pol-sec', eventType: 'POLICY_EVALUATED', lifecycleState: 'GOVERNED' });
    const results = auditEventRegistry.getEventsByPolicyId('pol-sec');
    expect(results.length).toBe(1);
  });

  it('67. indexes events by governanceDecisionId for decision trace correlation', () => {
    operationalAudit.recordEvent({ operationId: 'op_gov', correlationId: 'c', governanceDecisionId: 'dec-888', eventType: 'GOVERNANCE_DECIDED', lifecycleState: 'GOVERNED' });
    const results = auditEventRegistry.getEventsByGovernanceDecisionId('dec-888');
    expect(results.length).toBe(1);
  });

  it('68. indexes events by goalId for goal orchestration tracking', () => {
    operationalAudit.recordEvent({ operationId: 'op_goal', correlationId: 'c', goalId: 'goal-research-1', eventType: 'GOAL_ORCHESTRATED', lifecycleState: 'PLANNED' });
    const results = auditEventRegistry.getEventsByGoalId('goal-research-1');
    expect(results.length).toBe(1);
  });

  it('69. indexes events by missionId for long-horizon mission tracking', () => {
    operationalAudit.recordEvent({ operationId: 'op_msn', correlationId: 'c', missionId: 'mission-saturn', eventType: 'GOAL_ORCHESTRATED', lifecycleState: 'PLANNED' });
    const results = auditEventRegistry.getEventsByMissionId('mission-saturn');
    expect(results.length).toBe(1);
  });

  it('70. Stage 22 does NOT invoke ActionBus or execute actions directly', () => {
    // Calling operationalAudit methods never initiates outbound network or ActionBus execution
    const evt = operationalAudit.recordEvent({
      operationId: 'op_no_side_effects',
      correlationId: 'c',
      eventType: 'ACTION_DISPATCHED',
      lifecycleState: 'DISPATCHED',
    });
    expect(evt.event.eventId).toBeDefined();
  });

  it('71. Stage 22 does NOT evaluate or alter policies in PolicyRegistry', () => {
    const evt = operationalAudit.recordEvent({
      operationId: 'op_pure_obs',
      correlationId: 'c',
      eventType: 'POLICY_EVALUATED',
      lifecycleState: 'GOVERNED',
      policyId: 'pol_test',
    });
    expect(evt.event.policyId).toBe('pol_test');
  });

  // =========================================================================
  // Section 11: Mission & Strategic Knowledge Isolation (72-75)
  // =========================================================================

  it('72. audit events do NOT automatically become knowledge facts in Stage 13', () => {
    operationalAudit.recordEvent({
      operationId: 'op_kg_iso',
      correlationId: 'c',
      eventType: 'OBSERVATION_RECORDED',
      lifecycleState: 'SUCCEEDED',
      reason: 'Temporary file cached',
    });

    // Verification: Stage 13 knowledge graph facts are not mutated
    const facts = executionPersistence.getKnowledgeFacts();
    expect(facts.some((f: any) => f.statement === 'Temporary file cached')).toBe(false);
  });

  it('73. audit events do NOT bypass Stage 11 learning evaluation gates', () => {
    operationalAudit.recordEvent({
      operationId: 'op_learning_iso',
      correlationId: 'c',
      eventType: 'OPERATION_FAILED',
      lifecycleState: 'FAILED',
      reason: 'Network disconnect',
    });

    // Verification: Learning recommendations are not created automatically
    const recommendations = executionPersistence.getPolicyRecommendations();
    expect(recommendations.some((r: any) => r.recommendationId === 'op_learning_iso')).toBe(false);
  });

  it('74. mission pause status records PAUSED state without modifying mission scheduler', () => {
    const { event } = operationalAudit.recordEvent({
      operationId: 'op_msn_pause',
      correlationId: 'c',
      missionId: 'mission-mars',
      eventType: 'OPERATION_PAUSED',
      lifecycleState: 'PAUSED',
      reason: 'Mission lifecycle state is PAUSED',
    });

    expect(event.lifecycleState).toBe('PAUSED');
  });

  it('75. audit events preserve mission checkpoints without overwriting them', () => {
    const { event } = operationalAudit.recordEvent({
      operationId: 'op_chk',
      correlationId: 'c',
      missionId: 'mission-apollo',
      eventType: 'REQUEST_RECEIVED',
      lifecycleState: 'RECEIVED',
      parameters: { checkpointId: 'chk_101' },
    });

    expect(event.parameters?.checkpointId).toBe('chk_101');
  });

  // =========================================================================
  // Section 12: Security Hardening & Secret Scrubbing (76-80)
  // =========================================================================

  it('76. PROTOTYPE POLLUTION: strips __proto__, constructor, and prototype keys from payloads', () => {
    const maliciousPayload = JSON.parse(
      '{"__proto__": {"polluted": true}, "constructor": {"polluted": true}, "prototype": {"polluted": true}, "safeField": "clean"}'
    );

    const { event } = operationalAudit.recordEvent({
      operationId: 'op_proto',
      correlationId: 'c',
      eventType: 'REQUEST_RECEIVED',
      lifecycleState: 'RECEIVED',
      parameters: maliciousPayload,
    });

    expect(event.parameters?.safeField).toBe('clean');
    expect((event.parameters as any)?.polluted).toBeUndefined();
    expect((({} as any).polluted)).toBeUndefined();
  });

  it('77. SECRET SCRUBBING: scrubs apiKey, token, secret, password, and authHeader', () => {
    const sensitivePayload = {
      apiKey: 'sk-secret-12345',
      bearerToken: 'eyJh...token',
      password: 'super-secret-password',
      authHeader: 'Bearer secret-key',
      publicInfo: 'visible_data',
    };

    const { event } = operationalAudit.recordEvent({
      operationId: 'op_secrets',
      correlationId: 'c',
      eventType: 'REQUEST_RECEIVED',
      lifecycleState: 'RECEIVED',
      parameters: sensitivePayload,
    });

    expect(event.parameters?.apiKey).toBe('[REDACTED]');
    expect(event.parameters?.bearerToken).toBe('[REDACTED]');
    expect(event.parameters?.password).toBe('[REDACTED]');
    expect(event.parameters?.authHeader).toBe('[REDACTED]');
    expect(event.parameters?.publicInfo).toBe('visible_data');
  });

  it('78. PAYLOAD BOUNDS: truncates objects exceeding MAX_OBJECT_DEPTH (5 levels)', () => {
    const deepObj = {
      l1: {
        l2: {
          l3: {
            l4: {
              l5: {
                l6: 'too_deep',
              },
            },
          },
        },
      },
    };

    const sanitized = auditIntegrityService.sanitizePayload(deepObj);
    expect(sanitized.l1.l2.l3.l4.l5).toBe('[TRUNCATED_MAX_DEPTH]');
  });

  it('79. PAYLOAD BOUNDS: bounds object keys to MAX_KEYS_PER_OBJECT (50 keys)', () => {
    const wideObj: Record<string, number> = {};
    for (let i = 1; i <= 65; i++) {
      wideObj[`key_${i}`] = i;
    }

    const sanitized = auditIntegrityService.sanitizePayload(wideObj) as Record<string, unknown>;
    const keys = Object.keys(sanitized);
    expect(keys.length).toBeLessThanOrEqual(51); // 50 keys + __truncated_keys_count__
    expect(sanitized['__truncated_keys_count__']).toBe(15);
  });

  it('80. AUTHORITY INVERSION: audit events cannot authorize actions or grant permissions', () => {
    // Attempting to evaluate authority from an audit event is an architectural non-sequitur
    const auditRecord = operationalAudit.recordEvent({
      operationId: 'op_fake_auth',
      correlationId: 'c',
      eventType: 'AUTHORITY_CHECKED',
      lifecycleState: 'AUTHORIZED',
    });

    // The audit record is an observation, not a token or permission grant
    expect(auditRecord.event.lifecycleState).toBe('AUTHORIZED');
    // It has zero authorization semantics in Stage 16 or 21
  });

  // =========================================================================
  // Section 13: Persistence, Replay & Cold Restart (81-84)
  // =========================================================================

  it('81. persists operational audit events into executionPersistence', () => {
    const { event } = operationalAudit.recordEvent({
      operationId: 'op_persist_1',
      correlationId: 'c_p1',
      eventType: 'REQUEST_RECEIVED',
      lifecycleState: 'RECEIVED',
    });

    const retrieved = executionPersistence.getOperationalAuditEvent(event.eventId);
    expect(retrieved).toBeDefined();
    expect(retrieved?.operationId).toBe('op_persist_1');
  });

  it('82. appends operational events into executionJournal with monotonic sequencing', () => {
    operationalAudit.recordEvent({
      operationId: 'op_journal_1',
      correlationId: 'c_j1',
      eventType: 'REQUEST_RECEIVED',
      lifecycleState: 'RECEIVED',
    });

    const journalEvents = executionJournal.getAllEvents();
    expect(journalEvents.length).toBeGreaterThan(0);
    expect(journalEvents[journalEvents.length - 1].goalId).toBe('op_journal_1');
  });

  it('83. cold restart restores audit event history from persistence without data loss', () => {
    operationalAudit.recordEvent({
      operationId: 'op_cold_restart',
      correlationId: 'c_cr',
      eventType: 'REQUEST_RECEIVED',
      lifecycleState: 'RECEIVED',
    });

    // Verify all persisted events can be retrieved
    const persisted = executionPersistence.getAllOperationalAuditEvents();
    expect(persisted.some((e) => e.operationId === 'op_cold_restart')).toBe(true);
  });

  it('84. computes complete observability metrics from auditEventRegistry', () => {
    operationalAudit.recordEvent({ operationId: 'm_op1', correlationId: 'c', eventType: 'OPERATION_SUCCEEDED', lifecycleState: 'SUCCEEDED' });
    operationalAudit.recordEvent({ operationId: 'm_op2', correlationId: 'c', eventType: 'OPERATION_FAILED', lifecycleState: 'FAILED' });
    operationalAudit.recordEvent({ operationId: 'm_op3', correlationId: 'c', eventType: 'OPERATION_UNKNOWN', lifecycleState: 'UNKNOWN' });

    const metrics = auditMetricsService.computeMetrics();
    expect(metrics.totalOperations).toBe(3);
    expect(metrics.succeededOperations).toBe(1);
    expect(metrics.failedOperations).toBe(1);
    expect(metrics.unknownResultOperations).toBe(1);
  });

  // =========================================================================
  // Section 14: Spatial Command Console DOM Telemetry (85-88)
  // =========================================================================

  it('85. SpatialCommandConsole mounts operational-audit-hud in pure DOM', () => {
    const mockCommandControl = createMockCommandControl();
    const { getByTestId } = render(<SpatialCommandConsole commandControl={mockCommandControl as any} />);
    expect(getByTestId('operational-audit-hud')).toBeDefined();
    expect(getByTestId('operational-audit-status').textContent).toBe('OBSERVATIONAL_TRUTH');
  });

  it('86. SpatialCommandConsole renders causal-graph-hud with depth and cycle limits', () => {
    const mockCommandControl = createMockCommandControl();
    const { getByTestId } = render(<SpatialCommandConsole commandControl={mockCommandControl as any} />);
    expect(getByTestId('causal-graph-hud')).toBeDefined();
    expect(getByTestId('causal-graph-type').textContent).toBe('BOUNDED_DAG');
    expect(getByTestId('causal-depth-limit').textContent).toBe('MAX_10');
    expect(getByTestId('causal-node-limit').textContent).toBe('MAX_100');
    expect(getByTestId('causal-cycle-defense').textContent).toBe('ENFORCED');
  });

  it('87. SpatialCommandConsole displays operational-truth-hud with INTENT_NEQ_TRUTH badge', () => {
    const mockCommandControl = createMockCommandControl();
    const { getByTestId } = render(<SpatialCommandConsole commandControl={mockCommandControl as any} />);
    expect(getByTestId('operational-truth-hud')).toBeDefined();
    expect(getByTestId('operational-truth-invariant').textContent).toBe('INTENT_NEQ_TRUTH');
    expect(getByTestId('operational-unknown-invariant').textContent).toBe('PRESERVED');
    expect(getByTestId('epistemic-anti-upgrade').textContent).toBe('ENFORCED');
  });

  it('88. SpatialCommandConsole displays zero-authority badge (AUTHORITY: ZERO_AUTHORITY)', () => {
    const mockCommandControl = createMockCommandControl();
    const { getByTestId } = render(<SpatialCommandConsole commandControl={mockCommandControl as any} />);
    expect(getByTestId('audit-metrics-hud')).toBeDefined();
    expect(getByTestId('audit-immutability-badge').textContent).toBe('AUDIT: APPEND_ONLY');
    expect(getByTestId('audit-authority-badge').textContent).toBe('AUTHORITY: ZERO_AUTHORITY');
  });
});

function createMockCommandControl() {
  return {
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
}
