/**
 * AryaOS V1 — Stage 10: Agent Conflict Resolution Engine
 *
 * Deterministically identifies and records multi-agent conflicts:
 * - Shared memory write collisions
 * - Contradictory task outputs
 * - Duplicate execution / assignment attempts
 * - Circular task dependencies
 *
 * Preserves full provenance for both sides of the conflict and enables
 * structured resolution strategies: REVIEW, REPLAN, RESOLVE.
 */

import {
  ConflictRecord,
  ConflictCategory,
  ConflictResolutionStrategy,
  AgentTask,
  AggregatedAgentResult,
} from '../types/agentCoordination';

class AgentConflictManager {
  private conflicts: Map<string, ConflictRecord> = new Map(); // conflictId -> record

  constructor() {
    this.resetState();
  }

  public resetState(): void {
    this.conflicts.clear();
  }

  public getConflictsForGoal(goalId: string): ConflictRecord[] {
    return Array.from(this.conflicts.values()).filter((c) => c.goalId === goalId);
  }

  public getAllConflicts(): ConflictRecord[] {
    return Array.from(this.conflicts.values());
  }

  /**
   * Registers a newly detected conflict.
   */
  public recordConflict(
    conflict: Omit<ConflictRecord, 'conflictId' | 'detectedAt'>
  ): ConflictRecord {
    const conflictId = `CONF-${Date.now()}-${Math.floor(Math.random() * 10000)}`;
    const fullRecord: ConflictRecord = {
      ...conflict,
      conflictId,
      detectedAt: new Date().toISOString(),
    };
    this.conflicts.set(conflictId, fullRecord);
    return fullRecord;
  }

  /**
   * Checks a set of tasks for concurrent memory write collisions.
   */
  public checkMemoryWriteConflicts(tasks: AgentTask[]): ConflictRecord[] {
    const memoryWrites: Map<string, { taskId: string; agentId: string; taskTitle: string }[]> = new Map();

    for (const task of tasks) {
      if (task.status === 'RUNNING' || task.status === 'ASSIGNED') {
        for (const decl of task.memoryAccessDeclarations) {
          if (decl.accessType === 'WRITE' || decl.accessType === 'READ_WRITE') {
            const list = memoryWrites.get(decl.memoryId) || [];
            list.push({
              taskId: task.taskId,
              agentId: task.assignedAgentId || 'unassigned',
              taskTitle: task.parentActionId,
            });
            memoryWrites.set(decl.memoryId, list);
          }
        }
      }
    }

    const detected: ConflictRecord[] = [];
    for (const [memoryId, writers] of memoryWrites.entries()) {
      if (writers.length > 1) {
        const record = this.recordConflict({
          goalId: tasks[0]?.goalId || 'unknown-goal',
          category: 'MEMORY_WRITE_CONFLICT',
          conflictingTaskIds: writers.map((w) => w.taskId),
          conflictingAgentIds: writers.map((w) => w.agentId),
          resourceOrMemoryId: memoryId,
          description: `Concurrent write collision detected on memory entity '${memoryId}' by tasks: ${writers.map((w) => w.taskId).join(', ')}.`,
          provenanceRecords: writers.map((w) => ({ ...w })),
        });
        detected.push(record);
      }
    }

    return detected;
  }

  /**
   * Evaluates if results on the same task/subject contradict each other.
   */
  public detectContradictoryOutputs(
    results: AggregatedAgentResult[],
    goalId: string
  ): ConflictRecord | null {
    if (results.length < 2) return null;

    // Check for contradictory status or opposing assertions
    const hasSuccess = results.some((r) => r.status === 'SUCCEEDED');
    const hasFailure = results.some((r) => r.status === 'FAILED');

    if (hasSuccess && hasFailure) {
      return this.recordConflict({
        goalId,
        category: 'CONTRADICTORY_OUTPUT',
        conflictingTaskIds: results.map((r) => r.taskId),
        conflictingAgentIds: results.map((r) => r.agentId),
        description: `Contradictory execution outputs across ${results.length} worker agents on task group.`,
        provenanceRecords: results.map((r) => ({
          agentId: r.agentId,
          taskId: r.taskId,
          status: r.status,
          output: r.output,
        })),
      });
    }

    return null;
  }

  /**
   * Resolves a conflict with a specific strategy.
   */
  public resolveConflict(
    conflictId: string,
    strategy: ConflictResolutionStrategy,
    details: string
  ): boolean {
    const record = this.conflicts.get(conflictId);
    if (!record) return false;

    record.resolvedAt = new Date().toISOString();
    record.resolutionStrategy = strategy;
    record.resolutionDetails = details;
    return true;
  }
}

export const agentConflictManager = new AgentConflictManager();
