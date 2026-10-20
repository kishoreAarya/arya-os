/**
 * AryaOS V1 — Stage 18: Event Normalizer
 *
 * Normalizes provider-specific external events (GitHub, Google Drive) into
 * standard provider-neutral NormalizedExternalEvent records while preserving
 * complete provider provenance and epistemic boundaries (OBSERVED).
 */

import {
  ExternalEvent,
  NormalizedExternalEvent,
  NormalizedResourceType,
  NormalizedChangeType,
} from '../types/externalEvent';

export class EventNormalizer {
  /**
   * Transforms an ExternalEvent into a NormalizedExternalEvent.
   */
  public normalize(event: ExternalEvent): NormalizedExternalEvent {
    let resourceType: NormalizedResourceType = 'RECORD';
    let resourceId = 'unknown';
    let changeType: NormalizedChangeType = 'SYNCED';

    const payload = event.payload || {};

    if (event.sourceSystem === 'GITHUB') {
      resourceType = 'ISSUE';
      const repo = (payload.repository as string) || 'unknown_repo';
      const issueNum = payload.issueNumber || payload.number || '0';
      resourceId = `${repo}#${issueNum}`;

      if (event.eventType.includes('created') || payload.action === 'opened') {
        changeType = 'CREATED';
      } else if (event.eventType.includes('closed') || payload.action === 'closed') {
        changeType = 'DELETED';
      } else {
        changeType = 'UPDATED';
      }
    } else if (event.sourceSystem === 'GOOGLE_DRIVE') {
      resourceType = 'FILE';
      resourceId = (payload.fileId as string) || (payload.id as string) || 'unknown_file';

      if (event.eventType.includes('created')) {
        changeType = 'CREATED';
      } else if (event.eventType.includes('deleted')) {
        changeType = 'DELETED';
      } else {
        changeType = 'UPDATED';
      }
    }

    const normalizedEventId = `norm_${event.sourceSystem.toLowerCase()}_${event.eventId}`;

    return {
      normalizedEventId,
      originalEventId: event.eventId,
      connectorId: event.connectorId,
      resourceType,
      resourceId,
      changeType,
      sourceSystem: event.sourceSystem,
      provenance: {
        provider: event.sourceSystem,
        providerEventType: event.eventType,
        providerEventId: event.metadata?.providerEventId || event.eventId,
        connectorId: event.connectorId,
        occurredAt: event.occurredAt,
        receivedAt: event.receivedAt,
        authenticationMethod: event.authenticationStatus === 'AUTHENTICATED' ? 'HMAC_OR_TOKEN' : 'NONE',
        ingestFingerprint: `fp_${event.connectorId}_${event.eventId}`,
      },
      epistemicStatus: 'OBSERVED', // Core Invariant: always OBSERVED, never blindly CONFIRMED
      data: { ...payload },
      timestamp: event.occurredAt || event.receivedAt || new Date().toISOString(),
    };
  }
}

export const eventNormalizer = new EventNormalizer();
