/**
 * AryaOS V1 — Stage 18: External Event Ingestion & State Synchronization Domain Models
 *
 * Establishes provider-neutral contracts for inbound external events, webhooks,
 * signatures, replay protection, and state reconciliation.
 *
 * CRITICAL ARCHITECTURAL BOUNDARIES:
 * - Stage 07 Execution Gateway: Sole boundary for AI LLM inference.
 * - Stage 15 Action Bus: Sole boundary for outbound external actions.
 * - Stage 16 Connector Fabric: Sole authority for connector identity and permissions.
 * - Stage 17 Connector Activation: Sole boundary for outbound transport.
 * - Stage 18 External Event Ingestion: Sole boundary for inbound events and callbacks.
 *
 * CORE INVARIANT:
 * EVENT != TRUTH. EVENT != AUTHORITY. EVENT != PERMISSION.
 * External events are untrusted inputs until authenticated, validated, normalized,
 * deduplicated, reconciled, and provenanced.
 */

export type ExternalEventSource = 'GITHUB' | 'GOOGLE_DRIVE' | 'WEBHOOK' | 'CUSTOM';

export type EventAuthenticationStatus =
  | 'AUTHENTICATED'
  | 'UNAUTHENTICATED'
  | 'INVALID_SIGNATURE'
  | 'MISSING_SIGNATURE'
  | 'EXPIRED_TIMESTAMP'
  | 'UNKNOWN_CONNECTOR'
  | 'CONNECTOR_REVOKED'
  | 'CONNECTOR_DISABLED';

export type EventProcessingStatus =
  | 'RECEIVED'
  | 'VALIDATED'
  | 'REJECTED'
  | 'DUPLICATE_EVENT'
  | 'RATE_LIMITED'
  | 'NORMALIZED'
  | 'OBSERVED'
  | 'RECONCILED'
  | 'CONFIRMED'
  | 'FAILED'
  | 'STATE_UNKNOWN';

export type NormalizedResourceType = 'ISSUE' | 'FILE' | 'NOTIFICATION' | 'RECORD' | 'CUSTOM';

export type NormalizedChangeType = 'CREATED' | 'UPDATED' | 'DELETED' | 'STATUS_CHANGED' | 'SYNCED';

export type EpistemicStatus = 'OBSERVED' | 'INFERRED' | 'CONFIRMED' | 'UNKNOWN';

export interface ExternalEventMetadata {
  signature?: string;
  timestamp?: string;
  nonce?: string;
  providerEventId?: string;
  deliveryAttempt?: number;
  ipAddress?: string;
  userAgent?: string;
  [key: string]: unknown;
}

export interface ExternalEventEnvelope {
  rawBody: string;
  headers: Record<string, string>;
  ingressTimestamp: string;
  connectorId?: string;
  endpointPath?: string;
}

export interface ExternalEvent {
  eventId: string;
  eventType: string;
  connectorId: string;
  sourceSystem: ExternalEventSource;
  receivedAt: string;
  occurredAt: string;
  payload: Record<string, unknown>;
  schemaVersion: string;
  authenticationStatus: EventAuthenticationStatus;
  processingStatus: EventProcessingStatus;
  metadata?: ExternalEventMetadata;
}

export interface EventProvenance {
  provider: ExternalEventSource;
  providerEventType: string;
  providerEventId: string;
  connectorId: string;
  occurredAt: string;
  receivedAt: string;
  authenticationMethod: string;
  ingestFingerprint: string;
}

export interface NormalizedExternalEvent {
  normalizedEventId: string;
  originalEventId: string;
  connectorId: string;
  resourceType: NormalizedResourceType;
  resourceId: string;
  changeType: NormalizedChangeType;
  sourceSystem: ExternalEventSource;
  provenance: EventProvenance;
  epistemicStatus: EpistemicStatus;
  data: Record<string, unknown>;
  timestamp: string;
}

export interface EventAuthenticationResult {
  authenticated: boolean;
  status: EventAuthenticationStatus;
  reason?: string;
  connectorId?: string;
  source?: ExternalEventSource;
}

export interface EventValidationResult {
  valid: boolean;
  errors: string[];
  sanitizedPayload?: Record<string, unknown>;
}

export interface EventProcessingResult {
  success: boolean;
  status: EventProcessingStatus;
  event?: ExternalEvent;
  normalizedEvent?: NormalizedExternalEvent;
  error?: string;
  isDuplicate?: boolean;
  reconciliationStatus?: 'CONFIRMED' | 'OBSERVED' | 'FAILED' | 'STATE_UNKNOWN';
}

export interface IngestionRateLimitPolicy {
  maxEventsPerWindow: number;
  windowMs: number;
  maxPayloadBytes: number;
  maxConcurrentProcessing: number;
}
