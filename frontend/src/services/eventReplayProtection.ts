/**
 * AryaOS V1 — Stage 18: Event Replay Protection Service
 *
 * Implements deterministic event fingerprinting and duplicate detection.
 * Ensures an incoming event is never dispatched to downstream state reconciliation
 * or mission observation twice.
 */

import { ExternalEvent } from '../types/externalEvent';

export interface ProcessedEventRecord {
  fingerprint: string;
  eventId: string;
  connectorId: string;
  sourceSystem: string;
  occurredAt: string;
  recordedAt: number;
}

export class EventReplayProtection {
  private readonly processedEvents = new Map<string, ProcessedEventRecord>();
  private readonly ttlMs = 24 * 60 * 60 * 1000; // 24 hours retention

  /**
   * Generates a deterministic fingerprint for an external event.
   */
  public generateFingerprint(
    eventId: string,
    connectorId: string,
    sourceSystem: string,
    timestamp: string
  ): string {
    const raw = `${sourceSystem.trim().toLowerCase()}:${connectorId.trim().toLowerCase()}:${eventId.trim()}:${timestamp.trim()}`;
    // Simple deterministic string hash for fast memory indexing
    let hash = 0;
    for (let i = 0; i < raw.length; i++) {
      const char = raw.charCodeAt(i);
      hash = (hash << 5) - hash + char;
      hash |= 0; // Convert to 32bit integer
    }
    return `fp_${Math.abs(hash).toString(16)}_${eventId}`;
  }

  /**
   * Checks if an event has already been processed or is a duplicate replay.
   * If not seen, records it atomically.
   */
  public checkAndRecord(event: ExternalEvent): { isDuplicate: boolean; fingerprint: string } {
    const occurred = event.occurredAt || event.receivedAt || '';
    const fp = this.generateFingerprint(
      event.eventId,
      event.connectorId,
      event.sourceSystem,
      occurred
    );

    // Also check eventId directly per connector
    const directKey = `direct:${event.connectorId}:${event.eventId}`;

    if (this.processedEvents.has(fp) || this.processedEvents.has(directKey)) {
      return { isDuplicate: true, fingerprint: fp };
    }

    const record: ProcessedEventRecord = {
      fingerprint: fp,
      eventId: event.eventId,
      connectorId: event.connectorId,
      sourceSystem: event.sourceSystem,
      occurredAt: occurred,
      recordedAt: Date.now(),
    };

    this.processedEvents.set(fp, record);
    this.processedEvents.set(directKey, record);

    return { isDuplicate: false, fingerprint: fp };
  }

  /**
   * Checks if a fingerprint is already recorded without recording a new one.
   */
  public hasSeen(eventId: string, connectorId: string): boolean {
    const directKey = `direct:${connectorId}:${eventId}`;
    return this.processedEvents.has(directKey);
  }

  /**
   * Prunes records older than TTL.
   */
  public pruneStaleRecords(): number {
    const now = Date.now();
    let pruned = 0;
    for (const [key, record] of this.processedEvents.entries()) {
      if (now - record.recordedAt > this.ttlMs) {
        this.processedEvents.delete(key);
        pruned++;
      }
    }
    return pruned;
  }

  /**
   * Clears in-memory records (for tests).
   */
  public clear(): void {
    this.processedEvents.clear();
  }
}

export const eventReplayProtection = new EventReplayProtection();
