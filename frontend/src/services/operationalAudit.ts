/**
 * AryaOS V1 — Stage 22: Operational Audit Fabric (Façade & Coordinator)
 *
 * Single authoritative façade for operational observability, causal correlation,
 * and truth reconstruction across AryaOS V1.
 *
 * INVARIANTS:
 * - OBSERVES, RECORDS, CORRELATES, RECONSTRUCTS, EXPLAINS
 * - DOES NOT EXECUTE ACTIONS (Stage 15 ActionBus is exclusive dispatch)
 * - DOES NOT AUTHORIZE OPERATIONS (Stage 16/21 are exclusive authority)
 * - DOES NOT EVALUATE POLICIES (Stage 20/21 are exclusive policy engines)
 * - DOES NOT INVENT FAKE SUCCESS OR FABRICATED TELEMETRY
 */

import {
  OperationalAuditEvent,
  OperationalAuditEventType,
  OperationalLifecycleState,
  EpistemicStatus,
  OperationTrace,
  CausalGraph,
  OperationalMetrics,
  FailureBoundaryDetail,
} from '../types/operationalAudit';
import { auditEventRegistry } from './auditEventRegistry';
import { causalTraceService } from './causalTraceService';
import { operationTraceService } from './operationTraceService';
import { operationalLifecycleService } from './operationalLifecycleService';
import { operationalTruthService, TruthReconciliationResult } from './operationalTruthService';
import { auditEvidenceService, EvidenceRecord } from './auditEvidenceService';
import { failureBoundaryService } from './failureBoundaryService';
import { auditMetricsService } from './auditMetricsService';
import { executionPersistence } from './executionPersistence';
import { executionJournal } from './executionJournal';

export class OperationalAuditFabric {
  /**
   * Resets all internal stores (used for test isolation).
   */
  public reset(): void {
    auditEventRegistry.reset();
    auditEvidenceService.reset();
  }

  // =========================================================================
  // Ingestion & Observation API
  // =========================================================================

  /**
   * Records an operational event and mirrors it to executionPersistence & executionJournal.
   */
  public recordEvent(params: {
    eventId?: string;
    operationId: string;
    correlationId: string;
    causationId?: string;
    parentOperationId?: string;
    timestamp?: number;
    eventType: OperationalAuditEventType;
    lifecycleState: OperationalLifecycleState;
    epistemicStatus?: EpistemicStatus;
    actor?: OperationalAuditEvent['actor'];
    sourceSystem?: string;
    missionId?: string;
    goalId?: string;
    planId?: string;
    triggerId?: string;
    triggerVersion?: number;
    reactionId?: string;
    proposalId?: string;
    policyId?: string;
    policyVersion?: number;
    policySnapshotId?: string;
    governanceDecisionId?: string;
    governanceDecision?: OperationalAuditEvent['governanceDecision'];
    authorizationId?: string;
    actionId?: string;
    capabilityId?: string;
    connectorId?: string;
    providerId?: string;
    resultId?: string;
    observationId?: string;
    riskLevel?: OperationalAuditEvent['riskLevel'];
    failureBoundary?: FailureBoundaryDetail;
    reason?: string;
    parameters?: Record<string, unknown>;
    output?: Record<string, unknown>;
    evidenceReferences?: string[];
  }): { event: OperationalAuditEvent; isDuplicate: boolean } {
    const recordResult = auditEventRegistry.recordEvent({
      ...params,
      actor: params.actor || { actorId: 'system', actorType: 'SYSTEM' },
    });

    const evt = recordResult.event;

    // Append to Execution Journal and Persistence only if not a duplicate
    if (!recordResult.isDuplicate) {
      try {
        executionJournal.appendEvent({
          goalId: evt.goalId || evt.operationId,
          planId: evt.planId,
          actionId: evt.actionId,
          eventType: 'EXTERNAL_EVENT_NORMALIZED',
          provenance: {
            source: 'OperationalAuditFabric',
            eventId: evt.eventId,
            operationId: evt.operationId,
            correlationId: evt.correlationId,
          },
          payload: {
            eventType: evt.eventType,
            lifecycleState: evt.lifecycleState,
            epistemicStatus: evt.epistemicStatus,
            reason: evt.reason,
          },
        });

        // Store into executionPersistence if available
        (executionPersistence as any).saveOperationalAuditEvent?.(evt);
      } catch {
        // Safe fallback in isolated test environments
      }
    }

    return recordResult;
  }

  // =========================================================================
  // Specific Stage Observational Helpers
  // =========================================================================

  public observeExternalEvent(params: {
    operationId: string;
    correlationId: string;
    externalEventId: string;
    sourceSystem: string;
    actorId?: string;
    data?: Record<string, unknown>;
    epistemicStatus?: EpistemicStatus;
  }): OperationalAuditEvent {
    const { event } = this.recordEvent({
      operationId: params.operationId,
      correlationId: params.correlationId,
      causationId: params.externalEventId,
      eventType: 'REQUEST_RECEIVED',
      lifecycleState: 'RECEIVED',
      epistemicStatus: params.epistemicStatus || 'OBSERVED',
      sourceSystem: params.sourceSystem,
      actor: { actorId: params.actorId || 'external-source', actorType: 'SYSTEM' },
      parameters: params.data,
      evidenceReferences: [params.externalEventId],
      reason: `Inbound event received from ${params.sourceSystem}`,
    });
    return event;
  }

  public observeTriggerMatch(params: {
    operationId: string;
    correlationId: string;
    triggerId: string;
    triggerVersion: number;
    causationEventId: string;
    missionId?: string;
  }): OperationalAuditEvent {
    const { event } = this.recordEvent({
      operationId: params.operationId,
      correlationId: params.correlationId,
      causationId: params.causationEventId,
      eventType: 'TRIGGER_EVALUATED',
      lifecycleState: 'TRIGGERED',
      epistemicStatus: 'INFERRED',
      sourceSystem: 'Stage 19 Reaction Engine',
      triggerId: params.triggerId,
      triggerVersion: params.triggerVersion,
      missionId: params.missionId,
      reason: `Trigger '${params.triggerId}' matched inbound event conditions`,
    });
    return event;
  }

  public observeGovernanceDecision(params: {
    operationId: string;
    correlationId: string;
    decisionId: string;
    decision: OperationalAuditEvent['governanceDecision'];
    policySnapshotId: string;
    policyRegistryVersion: number;
    matchedPolicies: string[];
    riskLevel?: OperationalAuditEvent['riskLevel'];
    reason?: string;
    causationId?: string;
  }): OperationalAuditEvent {
    let lifecycleState: OperationalLifecycleState = 'GOVERNED';
    let failureBoundary: FailureBoundaryDetail | undefined;

    if (params.decision === 'DENY') {
      lifecycleState = 'DENIED';
      failureBoundary = failureBoundaryService.createDetail(
        'POLICY_DENIED',
        'Stage 21 Governance Control Plane',
        params.reason || 'Operation denied by policy'
      );
    } else if (params.decision === 'REQUIRE_APPROVAL') {
      lifecycleState = 'GOVERNED';
      failureBoundary = failureBoundaryService.createDetail(
        'HUMAN_APPROVAL_PENDING',
        'Stage 21 Human Operator Gate',
        'Operation requires explicit operator approval'
      );
    } else if (params.decision === 'PAUSE') {
      lifecycleState = 'PAUSED';
      failureBoundary = failureBoundaryService.createDetail(
        'MISSION_PAUSED',
        'Stage 21 Authority Intersection',
        'Mission paused'
      );
    }

    const { event } = this.recordEvent({
      operationId: params.operationId,
      correlationId: params.correlationId,
      causationId: params.causationId,
      eventType: 'GOVERNANCE_DECIDED',
      lifecycleState,
      epistemicStatus: 'OBSERVED',
      sourceSystem: 'Stage 21 Governance Control Plane',
      governanceDecisionId: params.decisionId,
      governanceDecision: params.decision,
      policySnapshotId: params.policySnapshotId,
      policyVersion: params.policyRegistryVersion,
      policyId: params.matchedPolicies[0],
      riskLevel: params.riskLevel,
      failureBoundary,
      reason: params.reason,
    });
    return event;
  }

  public observeActionDispatch(params: {
    operationId: string;
    correlationId: string;
    actionId: string;
    capabilityId: string;
    connectorId?: string;
    parameters?: Record<string, unknown>;
    causationId?: string;
  }): OperationalAuditEvent {
    const { event } = this.recordEvent({
      operationId: params.operationId,
      correlationId: params.correlationId,
      causationId: params.causationId,
      eventType: 'ACTION_DISPATCHED',
      lifecycleState: 'DISPATCHED',
      epistemicStatus: 'OBSERVED',
      sourceSystem: 'Stage 15 Universal Action Bus',
      actionId: params.actionId,
      capabilityId: params.capabilityId,
      connectorId: params.connectorId,
      parameters: params.parameters,
      reason: `Action '${params.actionId}' dispatched to ActionBus`,
    });
    return event;
  }

  public observeActionResult(params: {
    operationId: string;
    correlationId: string;
    actionId: string;
    success: boolean;
    output?: Record<string, unknown>;
    error?: { message: string; code?: string };
    causationId?: string;
  }): OperationalAuditEvent {
    const lifecycleState: OperationalLifecycleState = params.success ? 'SUCCEEDED' : 'FAILED';
    const failureBoundary: FailureBoundaryDetail | undefined = !params.success
      ? failureBoundaryService.createDetail(
          'PROVIDER_FAILURE',
          'Stage 15 / Adapter Execution',
          params.error?.message || 'Action execution failed'
        )
      : undefined;

    const { event } = this.recordEvent({
      operationId: params.operationId,
      correlationId: params.correlationId,
      causationId: params.causationId || params.actionId,
      eventType: 'ACTION_EXECUTED',
      lifecycleState,
      epistemicStatus: 'OBSERVED',
      sourceSystem: 'Stage 15 Universal Action Bus',
      actionId: params.actionId,
      output: params.output,
      failureBoundary,
      reason: params.success ? 'Action executed successfully' : params.error?.message,
    });
    return event;
  }

  // =========================================================================
  // Query & Trace API
  // =========================================================================

  public getOperationTrace(operationId: string): OperationTrace {
    return operationTraceService.getOperationTrace(operationId);
  }

  public getCausalGraph(operationId: string): CausalGraph {
    return causalTraceService.buildCausalGraph(operationId);
  }

  public getMetrics(): OperationalMetrics {
    return auditMetricsService.computeMetrics();
  }

  public diagnoseFailure(operationId: string): FailureBoundaryDetail | undefined {
    const events = auditEventRegistry.getEventsByOperationId(operationId);
    return failureBoundaryService.diagnoseFailureBoundary(events);
  }

  public reconcileOperationalTruth(params: {
    dispatchedState: OperationalLifecycleState;
    hasActionBusDispatched: boolean;
    hasExternalConfirmation: boolean;
    externalSuccess?: boolean;
    expectedStateDelta?: Record<string, unknown>;
    observedStateDelta?: Record<string, unknown>;
    reconciliationMatched?: boolean;
  }): TruthReconciliationResult {
    return operationalTruthService.reconcileOperationalTruth(params);
  }

  public recordEvidence(evidence: EvidenceRecord): void {
    auditEvidenceService.recordEvidence(evidence);
  }
}

export const operationalAudit = new OperationalAuditFabric();
