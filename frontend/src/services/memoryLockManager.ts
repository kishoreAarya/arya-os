/**
 * AryaOS V1 — Stage 10: Shared Memory Locking Engine
 *
 * Implements deterministic read/write lock coordination over Stage 04 memory entities:
 * - Concurrent READs are permitted.
 * - WRITE / READ_WRITE locks require exclusive access.
 * - Conflicting concurrent writes or read-after-write collisions are held in CONFLICT state.
 * - Leases feature deterministic TTL expiration to guard against deadlocks.
 */

import {
  MemoryLock,
  MemoryLockState,
  MemoryAccessType,
  TaskMemoryAccessDeclaration,
} from '../types/agentCoordination';

export interface LockAcquisitionResult {
  acquired: boolean;
  conflictingLocks: MemoryLock[];
  acquiredLocks: MemoryLock[];
  failureReason?: string;
}

class MemoryLockManager {
  private activeLocks: Map<string, MemoryLock[]> = new Map(); // memoryId -> array of active locks
  private defaultTtlMs: number = 60000; // 60s TTL

  constructor() {
    this.resetState();
  }

  public resetState(): void {
    this.activeLocks.clear();
  }

  /**
   * Prunes locks whose TTL has elapsed.
   */
  private pruneExpiredLocks(): void {
    const now = Date.now();
    for (const [memId, locks] of this.activeLocks.entries()) {
      const active = locks.filter((l) => new Date(l.expiresAt).getTime() > now);
      if (active.length === 0) {
        this.activeLocks.delete(memId);
      } else {
        this.activeLocks.set(memId, active);
      }
    }
  }

  /**
   * Returns current lock state for a given memory entity.
   */
  public getLockState(memoryId: string): MemoryLockState {
    this.pruneExpiredLocks();
    const locks = this.activeLocks.get(memoryId);
    if (!locks || locks.length === 0) return 'AVAILABLE';
    const hasWrite = locks.some((l) => l.accessType === 'WRITE' || l.accessType === 'READ_WRITE');
    return hasWrite ? 'WRITE_LOCKED' : 'READ_LOCKED';
  }

  /**
   * Returns all active non-expired locks.
   */
  public getActiveLocks(): MemoryLock[] {
    this.pruneExpiredLocks();
    const all: MemoryLock[] = [];
    for (const locks of this.activeLocks.values()) {
      all.push(...locks);
    }
    return all;
  }

  /**
   * Attempts to acquire locks for all memory declarations required by a task.
   * If any declaration is in conflict, none are acquired (all-or-nothing atomicity).
   */
  public acquireLocks(
    taskId: string,
    agentId: string,
    declarations: TaskMemoryAccessDeclaration[],
    ttlMs: number = this.defaultTtlMs
  ): LockAcquisitionResult {
    this.pruneExpiredLocks();

    const conflicts: MemoryLock[] = [];
    const now = Date.now();
    const expiresAt = new Date(now + ttlMs).toISOString();

    // 1. Check for conflicts across all requested declarations
    for (const decl of declarations) {
      const existing = this.activeLocks.get(decl.memoryId) || [];

      if (decl.accessType === 'READ') {
        // READ conflicts if an existing lock from another task is WRITE or READ_WRITE
        const writeConflicts = existing.filter(
          (l) => l.ownerTaskId !== taskId && (l.accessType === 'WRITE' || l.accessType === 'READ_WRITE')
        );
        if (writeConflicts.length > 0) {
          conflicts.push(...writeConflicts);
        }
      } else {
        // WRITE or READ_WRITE conflicts if ANY existing lock from another task exists
        const anyConflicts = existing.filter((l) => l.ownerTaskId !== taskId);
        if (anyConflicts.length > 0) {
          conflicts.push(...anyConflicts);
        }
      }
    }

    if (conflicts.length > 0) {
      return {
        acquired: false,
        conflictingLocks: conflicts,
        acquiredLocks: [],
        failureReason: `Memory lock conflict on entities: ${conflicts.map((c) => c.memoryId).join(', ')}`,
      };
    }

    // 2. Commit lock acquisitions atomically
    const newlyAcquired: MemoryLock[] = [];
    for (const decl of declarations) {
      const lock: MemoryLock = {
        lockId: `LOCK-${Date.now()}-${Math.floor(Math.random() * 10000)}`,
        memoryId: decl.memoryId,
        ownerTaskId: taskId,
        ownerAgentId: agentId,
        accessType: decl.accessType,
        acquiredAt: new Date(now).toISOString(),
        expiresAt,
      };

      const existing = this.activeLocks.get(decl.memoryId) || [];
      // Remove any previous lock by this exact task on this entity before adding new
      const filtered = existing.filter((l) => l.ownerTaskId !== taskId);
      filtered.push(lock);
      this.activeLocks.set(decl.memoryId, filtered);
      newlyAcquired.push(lock);
    }

    return {
      acquired: true,
      conflictingLocks: [],
      acquiredLocks: newlyAcquired,
    };
  }

  /**
   * Releases all locks held by a specific task.
   */
  public releaseLocksForTask(taskId: string): void {
    for (const [memId, locks] of this.activeLocks.entries()) {
      const remaining = locks.filter((l) => l.ownerTaskId !== taskId);
      if (remaining.length === 0) {
        this.activeLocks.delete(memId);
      } else {
        this.activeLocks.set(memId, remaining);
      }
    }
  }
}

export const memoryLockManager = new MemoryLockManager();
