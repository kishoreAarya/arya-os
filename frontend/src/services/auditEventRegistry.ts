/**
 * AryaOS V1 — Stage 22: Audit Event Registry
 *
 * Append-only, indexed, deduplicated registry for canonical OperationalAuditEvents.
 * Guarantees event immutability, replay protection, and cross-stage indexing.
 */

import {
  OperationalAuditEvent,
  OperationalAuditEventType,
  OperationalLifecycleState,
} from '../types/operationalAudit';
import { auditIntegrityService } from './auditIntegrityService';

export class AuditEventRegistry {
  private events: Map<string, OperationalAuditEvent> = new Map();
  private eventsChronological: OperationalAuditEvent[] = [];

  // Deduplication & Replay tracking
  private seenFingerprints: Set<string> = new Set();
  private duplicateCount = 0;

  // Cross-Stage Correlation Indexes
  private indexByOperationId: Map<string, string[]> = new Map();
  private indexByCorrelationId: Map<string, string[]> = new Map();
  private indexByCausationId: Map<string, string[]> = new Map();
  private indexByParentOperationId: Map<string, string[]> = new Map();
  private indexByActionId: Map<string, string[]> = new Map();
  private indexByConnectorId: Map<string, string[]> = new Map();
  private indexByTriggerId: Map<string, string[]> = new Map();
  private indexByPolicyId: Map<string, string[]> = new Map();
  private indexByGovernanceDecisionId: Map<string, string[]> = new Map();
  private indexByGoalId: Map<string, string[]> = new Map();
  private indexByMissionId: Map<string, string[]> = new Map();

  private monotonicSequence = 0;

  /**
   * Resets the registry (used for clean test isolation).
   */
  public reset(): void {
    this.events.clear();
    this.eventsChronological = [];
    this.seenFingerprints.clear();
    this.duplicateCount = 0;
    this.monotonicSequence = 0;

    this.indexByOperationId.clear();
    this.indexByCorrelationId.clear();
    this.indexByCausationId.clear();
    this.indexByParentOperationId.clear();
    this.indexByActionId.clear();
    this.indexByConnectorId.clear();
    this.indexByTriggerId.clear();
    this.indexByPolicyId.clear();
    this.indexByGovernanceDecisionId.clear();
    this.indexByGoalId.clear();
    this.indexByMissionId.clear();
  }

  /**
   * Generates a deterministic event ID.
   */
  public generateEventId(params: {
    operationId: string;
    eventType: OperationalAuditEventType;
    sourceSystem?: string;
  }): string {
    this.monotonicSequence++;
    const prefix = params.eventType.toLowerCase().replace(/_/g, '-');
    const opSuffix = params.operationId.slice(-8);
    return `evt-${prefix}-${opSuffix}-${this.monotonicSequence}`;
  }

  /**
   * Records an operational audit event with deduplication and immutability.
   * Returns: { event: OperationalAuditEvent, isDuplicate: boolean }
   */
  public recordEvent(rawEvent: Partial<OperationalAuditEvent> & {
    operationId: string;
    correlationId: string;
    eventType: OperationalAuditEventType;
    lifecycleState: OperationalLifecycleState;
  }): { event: OperationalAuditEvent; isDuplicate: boolean } {
    // 1. Sanitize parameters & outputs
    const sanitizedParams = rawEvent.parameters
      ? auditIntegrityService.sanitizePayload(rawEvent.parameters)
      : undefined;
    const sanitizedOutput = rawEvent.output
      ? auditIntegrityService.sanitizePayload(rawEvent.output)
      : undefined;

    // 2. Deterministic fingerprint
    const fingerprint = rawEvent.payloadFingerprint || auditIntegrityService.computeFingerprint({
      op: rawEvent.operationId,
      corr: rawEvent.correlationId,
      type: rawEvent.eventType,
      state: rawEvent.lifecycleState,
      params: sanitizedParams,
    });

    // 3. Deduplication check
    const dedupeKey = `${rawEvent.operationId}:${rawEvent.eventType}:${fingerprint}`;
    if (this.seenFingerprints.has(dedupeKey)) {
      this.duplicateCount++;
      const existing = this.getEventsByOperationId(rawEvent.operationId).find(
        (e) => e.eventType === rawEvent.eventType && e.payloadFingerprint === fingerprint
      );
      if (existing) {
        return { event: existing, isDuplicate: true };
      }
    }

    // 4. Resolve event ID
    const eventId = rawEvent.eventId || this.generateEventId({
      operationId: rawEvent.operationId,
      eventType: rawEvent.eventType,
      sourceSystem: rawEvent.sourceSystem,
    });

    // If an event with this exact eventId already exists: IMMUTABILITY ENFORCEMENT
    if (this.events.has(eventId)) {
      this.duplicateCount++;
      return { event: this.events.get(eventId)!, isDuplicate: true };
    }

    // 5. Construct canonical event
    const canonicalEvent: OperationalAuditEvent = {
      eventId,
      operationId: rawEvent.operationId,
      correlationId: rawEvent.correlationId,
      causationId: rawEvent.causationId,
      parentOperationId: rawEvent.parentOperationId,
      timestamp: rawEvent.timestamp || Date.now(),
      eventType: rawEvent.eventType,
      actor: rawEvent.actor || { actorId: 'system', actorType: 'SYSTEM' },
      sourceSystem: rawEvent.sourceSystem || 'runtime',
      missionId: rawEvent.missionId,
      goalId: rawEvent.goalId,
      planId: rawEvent.planId,
      triggerId: rawEvent.triggerId,
      triggerVersion: rawEvent.triggerVersion,
      reactionId: rawEvent.reactionId,
      proposalId: rawEvent.proposalId,
      policyId: rawEvent.policyId,
      policyVersion: rawEvent.policyVersion,
      policySnapshotId: rawEvent.policySnapshotId,
      governanceDecisionId: rawEvent.governanceDecisionId,
      governanceDecision: rawEvent.governanceDecision,
      authorizationId: rawEvent.authorizationId,
      actionId: rawEvent.actionId,
      capabilityId: rawEvent.capabilityId,
      connectorId: rawEvent.connectorId,
      providerId: rawEvent.providerId,
      resultId: rawEvent.resultId,
      observationId: rawEvent.observationId,
      lifecycleState: rawEvent.lifecycleState,
      epistemicStatus: rawEvent.epistemicStatus || 'UNKNOWN',
      riskLevel: rawEvent.riskLevel,
      failureBoundary: rawEvent.failureBoundary,
      reason: rawEvent.reason,
      parameters: sanitizedParams,
      output: sanitizedOutput,
      evidenceReferences: rawEvent.evidenceReferences || [],
      payloadFingerprint: fingerprint,
      schemaVersion: rawEvent.schemaVersion || 1,
    };

    // 6. Deep freeze for append-only immutability
    const frozenEvent = auditIntegrityService.deepFreeze(canonicalEvent);

    // 7. Store and Index
    this.events.set(eventId, frozenEvent as OperationalAuditEvent);
    this.eventsChronological.push(frozenEvent as OperationalAuditEvent);
    this.seenFingerprints.add(dedupeKey);

    this.addToIndex(this.indexByOperationId, frozenEvent.operationId, eventId);
    this.addToIndex(this.indexByCorrelationId, frozenEvent.correlationId, eventId);
    if (frozenEvent.causationId) this.addToIndex(this.indexByCausationId, frozenEvent.causationId, eventId);
    if (frozenEvent.parentOperationId) this.addToIndex(this.indexByParentOperationId, frozenEvent.parentOperationId, eventId);
    if (frozenEvent.actionId) this.addToIndex(this.indexByActionId, frozenEvent.actionId, eventId);
    if (frozenEvent.connectorId) this.addToIndex(this.indexByConnectorId, frozenEvent.connectorId, eventId);
    if (frozenEvent.triggerId) this.addToIndex(this.indexByTriggerId, frozenEvent.triggerId, eventId);
    if (frozenEvent.policyId) this.addToIndex(this.indexByPolicyId, frozenEvent.policyId, eventId);
    if (frozenEvent.governanceDecisionId) this.addToIndex(this.indexByGovernanceDecisionId, frozenEvent.governanceDecisionId, eventId);
    if (frozenEvent.goalId) this.addToIndex(this.indexByGoalId, frozenEvent.goalId, eventId);
    if (frozenEvent.missionId) this.addToIndex(this.indexByMissionId, frozenEvent.missionId, eventId);

    return { event: frozenEvent as OperationalAuditEvent, isDuplicate: false };
  }

  // =========================================================================
  // Query & Indexing API
  // =========================================================================

  public getEvent(eventId: string): OperationalAuditEvent | undefined {
    return this.events.get(eventId);
  }

  public getAllEvents(): readonly OperationalAuditEvent[] {
    return this.eventsChronological;
  }

  public getEventsByOperationId(operationId: string): OperationalAuditEvent[] {
    const ids = this.indexByOperationId.get(operationId) || [];
    return ids.map((id) => this.events.get(id)!).filter(Boolean);
  }

  public getEventsByCorrelationId(correlationId: string): OperationalAuditEvent[] {
    const ids = this.indexByCorrelationId.get(correlationId) || [];
    return ids.map((id) => this.events.get(id)!).filter(Boolean);
  }

  public getEventsByCausationId(causationId: string): OperationalAuditEvent[] {
    const ids = this.indexByCausationId.get(causationId) || [];
    return ids.map((id) => this.events.get(id)!).filter(Boolean);
  }

  public getEventsByActionId(actionId: string): OperationalAuditEvent[] {
    const ids = this.indexByActionId.get(actionId) || [];
    return ids.map((id) => this.events.get(id)!).filter(Boolean);
  }

  public getEventsByConnectorId(connectorId: string): OperationalAuditEvent[] {
    const ids = this.indexByConnectorId.get(connectorId) || [];
    return ids.map((id) => this.events.get(id)!).filter(Boolean);
  }

  public getEventsByTriggerId(triggerId: string): OperationalAuditEvent[] {
    const ids = this.indexByTriggerId.get(triggerId) || [];
    return ids.map((id) => this.events.get(id)!).filter(Boolean);
  }

  public getEventsByPolicyId(policyId: string): OperationalAuditEvent[] {
    const ids = this.indexByPolicyId.get(policyId) || [];
    return ids.map((id) => this.events.get(id)!).filter(Boolean);
  }

  public getEventsByGovernanceDecisionId(decisionId: string): OperationalAuditEvent[] {
    const ids = this.indexByGovernanceDecisionId.get(decisionId) || [];
    return ids.map((id) => this.events.get(id)!).filter(Boolean);
  }

  public getEventsByGoalId(goalId: string): OperationalAuditEvent[] {
    const ids = this.indexByGoalId.get(goalId) || [];
    return ids.map((id) => this.events.get(id)!).filter(Boolean);
  }

  public getEventsByMissionId(missionId: string): OperationalAuditEvent[] {
    const ids = this.indexByMissionId.get(missionId) || [];
    return ids.map((id) => this.events.get(id)!).filter(Boolean);
  }

  public getDuplicateCount(): number {
    return this.duplicateCount;
  }

  private addToIndex(index: Map<string, string[]>, key: string, eventId: string): void {
    const existing = index.get(key);
    if (existing) {
      existing.push(eventId);
    } else {
      index.set(key, [eventId]);
    }
  }
}

export const auditEventRegistry = new AuditEventRegistry();
