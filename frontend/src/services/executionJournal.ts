/**
 * AryaOS V1 — Stage 09: Execution Journal Service
 *
 * Append-only, event-sourced journal recording every meaningful orchestration
 * transition with monotonic sequencing, state deltas, and immutable audit guarantees.
 */

import {
  JournalEvent,
  OrchestrationJournalEventType,
} from '../types/executionPersistence';
import { executionPersistence } from './executionPersistence';

export const STORAGE_KEY_JOURNAL = 'arya_persisted_execution_journal';
export const CURRENT_JOURNAL_SCHEMA_VERSION = 1;

export class ExecutionJournal {
  private inMemoryEvents: JournalEvent[] = [];
  private sequenceCounter: number = 0;
  private listeners: Set<(event: JournalEvent) => void> = new Set();

  constructor() {
    this.loadFromStorage();
  }

  /**
   * Resets the journal state (useful for test isolation).
   */
  public resetState(): void {
    this.inMemoryEvents = [];
    this.sequenceCounter = 0;
    try {
      if (typeof localStorage !== 'undefined') {
        localStorage.removeItem(STORAGE_KEY_JOURNAL);
      }
    } catch {
      // Ignored in test / restricted environments
    }
  }

  public reset(): void {
    this.resetState();
  }

  /**
   * Appends an immutable event to the execution journal.
   */
  public appendEvent(params: {
    goalId: string;
    planId?: string;
    planVersion?: number;
    actionId?: string;
    eventType: OrchestrationJournalEventType;
    previousState?: string;
    newState?: string;
    provenance?: Record<string, unknown>;
    payload?: Record<string, unknown>;
  }): JournalEvent {
    this.sequenceCounter++;
    const eventId = `JRN-${Date.now()}-${this.sequenceCounter}`;

    const rawEvent: JournalEvent = {
      eventId,
      sequenceNumber: this.sequenceCounter,
      timestamp: new Date().toISOString(),
      goalId: params.goalId,
      planId: params.planId,
      planVersion: params.planVersion,
      actionId: params.actionId,
      eventType: params.eventType,
      previousState: params.previousState,
      newState: params.newState,
      provenance: params.provenance || {},
      payload: params.payload || {},
      schemaVersion: CURRENT_JOURNAL_SCHEMA_VERSION,
    };

    // Scrub all raw secrets prior to recording
    const sanitizedEvent: JournalEvent = executionPersistence.sanitizeForPersistence(rawEvent);

    this.inMemoryEvents.push(sanitizedEvent);
    this.persistToStorage();

    // Notify listeners
    this.listeners.forEach((listener) => {
      try {
        listener(sanitizedEvent);
      } catch (err) {
        console.warn('ExecutionJournal listener error:', err);
      }
    });

    return sanitizedEvent;
  }

  /**
   * Retrieves all journal events for a specific goal.
   */
  public getEventsForGoal(goalId: string): JournalEvent[] {
    return this.inMemoryEvents.filter((e) => e.goalId === goalId);
  }

  /**
   * Retrieves all journal events across all goals.
   */
  public getAllEvents(): JournalEvent[] {
    return [...this.inMemoryEvents];
  }

  /**
   * Subscribes to real-time journal events.
   */
  public subscribe(listener: (event: JournalEvent) => void): () => void {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  }

  /**
   * Persists in-memory events array to local storage safely.
   */
  private persistToStorage(): void {
    try {
      if (typeof localStorage !== 'undefined') {
        const payload = JSON.stringify({
          schemaVersion: CURRENT_JOURNAL_SCHEMA_VERSION,
          savedAt: new Date().toISOString(),
          events: this.inMemoryEvents,
        });
        localStorage.setItem(STORAGE_KEY_JOURNAL, payload);
      }
    } catch (err) {
      console.warn('Failed to persist execution journal to localStorage:', err);
    }
  }

  /**
   * Loads journal events from local storage on initialization.
   */
  private loadFromStorage(): void {
    try {
      if (typeof localStorage === 'undefined') return;
      const raw = localStorage.getItem(STORAGE_KEY_JOURNAL);
      if (!raw) return;

      const parsed = JSON.parse(raw);
      if (parsed && Array.isArray(parsed.events)) {
        this.inMemoryEvents = parsed.events;
        const highestSeq = this.inMemoryEvents.reduce(
          (max, ev) => Math.max(max, ev.sequenceNumber || 0),
          0
        );
        this.sequenceCounter = highestSeq;
      }
    } catch (err) {
      console.warn('Failed to load execution journal from localStorage:', err);
    }
  }
}

export const executionJournal = new ExecutionJournal();
