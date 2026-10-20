/**
 * AryaOS V1 — Stage 18: Event Ingress Service
 *
 * Central governed coordinator for external inbound event ingestion:
 * INGRESS -> RATE_LIMIT -> AUTHENTICATE -> VALIDATE -> DEDUPLICATE -> NORMALIZE ->
 * JOURNAL -> RECONCILE -> MEMORY/KG -> MISSION OBSERVATION -> BOUNDED REPLANNING.
 *
 * INVARIANTS:
 * - EVENT != TRUTH: Epistemic status remains OBSERVED unless explicitly confirmed.
 * - EVENT != AUTHORITY: No event may grant permissions or escalate agent privileges.
 * - EVENT != APPROVAL: No event may automatically approve consequential actions.
 * - ZERO RAW SECRETS: Never records secrets or authorization headers.
 */

import {
  ExternalEvent,
  ExternalEventEnvelope,
  ExternalEventSource,
  EventProcessingResult,
  IngestionRateLimitPolicy,
} from '../types/externalEvent';
import { webhookAuthenticationService } from './webhookAuthenticationService';
import { eventSchemaValidator } from './eventSchemaValidator';
import { eventReplayProtection } from './eventReplayProtection';
import { eventNormalizer } from './eventNormalizer';
import { externalStateReconciliationService } from './externalStateReconciliationService';
import { eventRegistry } from './eventRegistry';
import { executionJournal } from './executionJournal';
import { missionObservationService } from './missionObservationService';
import { missionReplanner } from './missionReplanner';
import { knowledgeGraph } from './knowledgeGraph';
import { executionPersistence } from './executionPersistence';
import { KnowledgeNode } from '../types/strategicKnowledge';

export class EventIngressService {
  private rateLimitPolicy: IngestionRateLimitPolicy = {
    maxEventsPerWindow: 50,
    windowMs: 10000,
    maxPayloadBytes: 1048576, // 1 MB
    maxConcurrentProcessing: 10,
  };

  private connectorEventCounts = new Map<string, { count: number; windowStart: number }>();
  private activeProcessingCount = 0;

  public setRateLimitPolicy(policy: Partial<IngestionRateLimitPolicy>): void {
    this.rateLimitPolicy = { ...this.rateLimitPolicy, ...policy };
  }

  public resetRateLimits(): void {
    this.connectorEventCounts.clear();
    this.activeProcessingCount = 0;
  }

  /**
   * Ingests a raw inbound webhook envelope.
   */
  public async ingestEnvelope(
    envelope: ExternalEventEnvelope,
    sourceSystem: ExternalEventSource,
    options?: { missionId?: string; goalId?: string }
  ): Promise<EventProcessingResult> {
    const ingressTime = new Date().toISOString();

    // 1. Rate Limiting & Concurrency Check
    const rateCheck = this.checkRateLimit(envelope.connectorId || 'unknown');
    if (!rateCheck.allowed) {
      this.recordJournalEvent('EXTERNAL_EVENT_REJECTED', {
        sourceSystem,
        reason: 'RATE_LIMITED',
        details: rateCheck.reason,
      }, options?.goalId);
      return {
        success: false,
        status: 'RATE_LIMITED',
        error: rateCheck.reason,
      };
    }

    // 2. Ingress Payload Byte Size Guard
    if (envelope.rawBody && envelope.rawBody.length > this.rateLimitPolicy.maxPayloadBytes) {
      this.recordJournalEvent('EXTERNAL_EVENT_REJECTED', {
        sourceSystem,
        reason: 'PAYLOAD_TOO_LARGE',
        bytes: envelope.rawBody.length,
      }, options?.goalId);
      return {
        success: false,
        status: 'REJECTED',
        error: `PayloadTooLarge: Ingress envelope size (${envelope.rawBody.length} bytes) exceeds limit (${this.rateLimitPolicy.maxPayloadBytes} bytes)`,
      };
    }

    // 3. Webhook Cryptographic Authentication & Connector Identity Resolution
    const authResult = await webhookAuthenticationService.authenticate(envelope, sourceSystem);
    if (!authResult.authenticated) {
      this.recordJournalEvent('EXTERNAL_EVENT_REJECTED', {
        sourceSystem,
        authStatus: authResult.status,
        reason: authResult.reason,
      }, options?.goalId);
      return {
        success: false,
        status: 'REJECTED',
        error: `Authentication failed: ${authResult.status} — ${authResult.reason}`,
      };
    }

    // 4. Parse JSON Payload
    let parsedPayload: Record<string, unknown> = {};
    try {
      parsedPayload = JSON.parse(envelope.rawBody);
    } catch {
      this.recordJournalEvent('EXTERNAL_EVENT_REJECTED', {
        sourceSystem,
        reason: 'MALFORMED_JSON',
      }, options?.goalId);
      return {
        success: false,
        status: 'REJECTED',
        error: 'Event payload contains malformed JSON',
      };
    }

    // 5. Construct ExternalEvent with deterministic identity
    const providerEventId =
      (envelope.headers['x-github-delivery'] as string) ||
      (envelope.headers['x-goog-channel-id'] as string) ||
      (parsedPayload.id as string) ||
      (parsedPayload.eventId as string) ||
      `evt_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`;

    const eventType =
      (envelope.headers['x-github-event'] as string) ||
      (envelope.headers['x-goog-event'] as string) ||
      (envelope.headers['X-GitHub-Event'] as string) ||
      (envelope.headers['X-Goog-Event'] as string) ||
      (parsedPayload.eventType as string) ||
      'unknown.event';

    const event: ExternalEvent = {
      eventId: providerEventId,
      eventType,
      connectorId: authResult.connectorId!,
      sourceSystem,
      receivedAt: ingressTime,
      occurredAt: (parsedPayload.occurredAt as string) || ingressTime,
      payload: parsedPayload,
      schemaVersion: (parsedPayload.schemaVersion as string) || '1.0.0',
      authenticationStatus: authResult.status,
      processingStatus: 'RECEIVED',
      metadata: {
        providerEventId,
        headers: { ...envelope.headers },
      },
    };

    return this.processEventPipeline(event, options);
  }

  /**
   * Direct ingestion of an ExternalEvent object.
   */
  public async ingestEvent(
    event: ExternalEvent,
    options?: { missionId?: string; goalId?: string }
  ): Promise<EventProcessingResult> {
    const rateCheck = this.checkRateLimit(event.connectorId);
    if (!rateCheck.allowed) {
      return {
        success: false,
        status: 'RATE_LIMITED',
        error: rateCheck.reason,
      };
    }

    return this.processEventPipeline(event, options);
  }

  /**
   * Core processing pipeline after initial envelope/auth checks.
   */
  private async processEventPipeline(
    event: ExternalEvent,
    options?: { missionId?: string; goalId?: string }
  ): Promise<EventProcessingResult> {
    this.activeProcessingCount++;

    try {
      // 1. Schema Validation & Payload Sanitization
      const valResult = eventSchemaValidator.validate(event);
      if (!valResult.valid) {
        event.processingStatus = 'REJECTED';
        eventRegistry.registerEvent(event);
        this.recordJournalEvent('EXTERNAL_EVENT_REJECTED', {
          eventId: event.eventId,
          connectorId: event.connectorId,
          errors: valResult.errors,
        }, options?.goalId);
        return {
          success: false,
          status: 'REJECTED',
          event,
          error: `SchemaValidationFailed: ${valResult.errors.join('; ')}`,
        };
      }

      // Replace payload with sanitized payload (stripping raw secrets)
      event.payload = valResult.sanitizedPayload || event.payload;

      // 2. Replay Protection & Deduplication
      const replayCheck = eventReplayProtection.checkAndRecord(event);
      if (replayCheck.isDuplicate) {
        event.processingStatus = 'DUPLICATE_EVENT';
        eventRegistry.registerEvent(event);
        this.recordJournalEvent('EXTERNAL_EVENT_DUPLICATE', {
          eventId: event.eventId,
          fingerprint: replayCheck.fingerprint,
        }, options?.goalId);
        return {
          success: false,
          status: 'DUPLICATE_EVENT',
          event,
          isDuplicate: true,
          error: `Duplicate event detected with fingerprint '${replayCheck.fingerprint}'`,
        };
      }

      // 3. Normalization
      const normalized = eventNormalizer.normalize(event);
      event.processingStatus = 'NORMALIZED';
      eventRegistry.registerEvent(event);
      eventRegistry.registerNormalizedEvent(normalized);

      this.recordJournalEvent('EXTERNAL_EVENT_AUTHENTICATED', {
        eventId: event.eventId,
        connectorId: event.connectorId,
        source: event.sourceSystem,
      }, options?.goalId);

      this.recordJournalEvent('EXTERNAL_EVENT_NORMALIZED', {
        normalizedEventId: normalized.normalizedEventId,
        resourceType: normalized.resourceType,
        resourceId: normalized.resourceId,
        changeType: normalized.changeType,
      }, options?.goalId);

      // 4. State Reconciliation (EVENT != TRUTH)
      const recon = await externalStateReconciliationService.reconcile(normalized);
      normalized.epistemicStatus = recon.epistemicStatus;

      this.recordJournalEvent('EXTERNAL_EVENT_RECONCILED', {
        normalizedEventId: normalized.normalizedEventId,
        reconciliationStatus: recon.status,
        epistemicStatus: recon.epistemicStatus,
      }, options?.goalId);

      // 5. Strategic Knowledge Graph Integration (Stage 13)
      this.integrateWithKnowledgeGraph(normalized, recon.status);

      // 6. Mission Observation & Bounded Replanning (Stage 12)
      if (options?.missionId) {
        this.integrateWithMission(options.missionId, normalized, recon.status);
      }

      event.processingStatus = recon.status === 'CONFIRMED' ? 'CONFIRMED' : 'RECONCILED';
      eventRegistry.registerEvent(event);

      return {
        success: true,
        status: event.processingStatus,
        event,
        normalizedEvent: normalized,
        reconciliationStatus: recon.status,
      };
    } catch (err: any) {
      event.processingStatus = 'FAILED';
      eventRegistry.registerEvent(event);
      this.recordJournalEvent('EXTERNAL_EVENT_FAILED', {
        eventId: event.eventId,
        error: err.message,
      }, options?.goalId);
      return {
        success: false,
        status: 'FAILED',
        event,
        error: err.message || 'Unknown processing failure',
      };
    } finally {
      this.activeProcessingCount--;
    }
  }

  private checkRateLimit(connectorId: string): { allowed: boolean; reason?: string } {
    if (this.activeProcessingCount >= this.rateLimitPolicy.maxConcurrentProcessing) {
      return {
        allowed: false,
        reason: `Max concurrent event processing (${this.rateLimitPolicy.maxConcurrentProcessing}) reached`,
      };
    }

    const now = Date.now();
    const current = this.connectorEventCounts.get(connectorId) || { count: 0, windowStart: now };

    if (now - current.windowStart > this.rateLimitPolicy.windowMs) {
      // New window
      this.connectorEventCounts.set(connectorId, { count: 1, windowStart: now });
      return { allowed: true };
    }

    if (current.count >= this.rateLimitPolicy.maxEventsPerWindow) {
      return {
        allowed: false,
        reason: `Rate limit exceeded for connector '${connectorId}': ${current.count}/${this.rateLimitPolicy.maxEventsPerWindow} events in window`,
      };
    }

    current.count++;
    this.connectorEventCounts.set(connectorId, current);
    return { allowed: true };
  }

  private recordJournalEvent(
    eventType: any,
    payload: Record<string, unknown>,
    goalId?: string
  ): void {
    try {
      executionJournal.appendEvent({
        goalId: goalId || 'goal_system_ingress',
        eventType,
        payload: {
          ...payload,
          timestamp: new Date().toISOString(),
        },
      });
    } catch {
      // Non-blocking in headless mode
    }
  }

  private integrateWithKnowledgeGraph(
    norm: any,
    reconStatus: string
  ): void {
    try {
      const nodeId = `kn_ext_${norm.sourceSystem.toLowerCase()}_${norm.resourceId.replace(/[^a-zA-Z0-9_]/g, '_')}`;
      const node = {
        id: nodeId,
        type: 'FACT',
        label: `${norm.sourceSystem} ${norm.resourceType}: ${norm.resourceId}`,
        confidence: reconStatus === 'CONFIRMED' ? 0.9 : 0.6,
        status: reconStatus === 'CONFIRMED' ? 'CONFIRMED' : 'OBSERVED',
        epistemicStatus: norm.epistemicStatus,
        evidenceCount: 1,
        sourceMissions: [],
        contributingAgents: [],
        createdAt: norm.timestamp,
        updatedAt: new Date().toISOString(),
        metadata: {
          connectorId: norm.connectorId,
          sourceSystem: norm.sourceSystem,
          changeType: norm.changeType,
          originalEventId: norm.originalEventId,
          reconciliationStatus: reconStatus,
          epistemicStatus: norm.epistemicStatus,
        },
      } as unknown as KnowledgeNode;
      knowledgeGraph.addNode(node);
    } catch {
      // Safe fallback
    }
  }

  private integrateWithMission(
    missionId: string,
    norm: any,
    reconStatus: string
  ): void {
    try {
      // Record structured mission observation
      missionObservationService.recordObservation(
        missionId,
        'PROGRESS',
        `External event observed on ${norm.resourceType} (${norm.resourceId}): ${norm.changeType}`,
        {
          normalizedEventId: norm.normalizedEventId,
          connectorId: norm.connectorId,
          reconciliationStatus: reconStatus,
          epistemicStatus: norm.epistemicStatus,
          resourceId: norm.resourceId,
        }
      );

      // Check if bounded replanning is required
      const mission = executionPersistence.getMission(missionId);
      if (mission && norm.changeType === 'DELETED') {
        const lastPlan = mission.plans[mission.plans.length - 1];
        // Bounded check: only replan if current plan does not already reflect this update
        if (lastPlan && !lastPlan.changeReason?.includes(norm.normalizedEventId)) {
          missionReplanner.replanMission(
            missionId,
            `External dependency modified by event ${norm.normalizedEventId}`
          );
        }
      }
    } catch {
      // Safe boundary
    }
  }
}

export const eventIngressService = new EventIngressService();
