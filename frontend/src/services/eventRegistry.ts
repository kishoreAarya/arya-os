/**
 * AryaOS V1 — Stage 18: Event Registry
 *
 * In-memory index of processed, normalized, and reconciled external events.
 * Provides query filters and audit access without retaining raw credentials or secrets.
 */

import {
  ExternalEvent,
  NormalizedExternalEvent,
  EventProcessingStatus,
  ExternalEventSource,
} from '../types/externalEvent';

export class EventRegistry {
  private events = new Map<string, ExternalEvent>();
  private normalizedEvents = new Map<string, NormalizedExternalEvent>();

  public registerEvent(event: ExternalEvent): void {
    this.events.set(event.eventId, { ...event });
  }

  public getEvent(eventId: string): ExternalEvent | undefined {
    return this.events.get(eventId);
  }

  public updateEventStatus(
    eventId: string,
    status: EventProcessingStatus,
    metadataUpdates?: Record<string, unknown>
  ): void {
    const existing = this.events.get(eventId);
    if (existing) {
      existing.processingStatus = status;
      if (metadataUpdates) {
        existing.metadata = { ...existing.metadata, ...metadataUpdates };
      }
      this.events.set(eventId, existing);
    }
  }

  public registerNormalizedEvent(normEvent: NormalizedExternalEvent): void {
    this.normalizedEvents.set(normEvent.normalizedEventId, { ...normEvent });
  }

  public getNormalizedEvent(normalizedEventId: string): NormalizedExternalEvent | undefined {
    return this.normalizedEvents.get(normalizedEventId);
  }

  public listEvents(filter?: {
    connectorId?: string;
    sourceSystem?: ExternalEventSource;
    status?: EventProcessingStatus;
  }): ExternalEvent[] {
    let list = Array.from(this.events.values());
    if (filter?.connectorId) {
      list = list.filter((e) => e.connectorId === filter.connectorId);
    }
    if (filter?.sourceSystem) {
      list = list.filter((e) => e.sourceSystem === filter.sourceSystem);
    }
    if (filter?.status) {
      list = list.filter((e) => e.processingStatus === filter.status);
    }
    return list;
  }

  public listNormalizedEvents(): NormalizedExternalEvent[] {
    return Array.from(this.normalizedEvents.values());
  }

  public clear(): void {
    this.events.clear();
    this.normalizedEvents.clear();
  }
}

export const eventRegistry = new EventRegistry();
