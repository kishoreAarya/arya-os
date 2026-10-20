/**
 * AryaOS V1 — Stage 13: Strategic Pattern Detection Service
 *
 * Discovers empirical recurring patterns across missions, evaluations, and resources.
 * Invariant: Prevents pattern overfitting by requiring explicit evidence thresholds
 * (minimum 2 or 3 distinct occurrences) before promoting to a StrategicPattern.
 */

import {
  KnowledgePattern,
  StrategicPatternType,
  KnowledgeConfidence,
} from '../types/strategicKnowledge';

export interface PatternDetectionInput {
  missions?: Array<{
    missionId: string;
    status: string;
    failures?: string[];
    replans?: number;
    tokens?: number;
    durationMs?: number;
  }>;
  experiences?: Array<{
    experienceId: string;
    taskType: string;
    agentId: string;
    providerId: string;
    success: boolean;
    qualityScore?: number;
    latencyMs?: number;
  }>;
  evaluations?: Array<{
    evaluationId: string;
    agentId: string;
    qualityScore: number;
    reliabilityScore: number;
  }>;
  conflicts?: Array<{
    conflictId: string;
    contendingAgentIds: string[];
    resourceType: string;
  }>;
}

export class StrategicPatternService {
  private patterns: Map<string, KnowledgePattern> = new Map();
  private readonly MIN_OCCURRENCE_THRESHOLD = 2; // Strict anti-overfitting threshold

  /**
   * Scans inputs and detects strategic patterns.
   */
  public detectPatterns(input: PatternDetectionInput): KnowledgePattern[] {
    const detected: KnowledgePattern[] = [];

    // 1. Detect REPEATED_FAILURE patterns for (agent, taskType)
    if (input.experiences) {
      const failureGroups: Record<string, string[]> = {};
      const successGroups: Record<string, string[]> = {};

      for (const exp of input.experiences) {
        const key = `${exp.agentId}::${exp.taskType}`;
        if (!exp.success) {
          if (!failureGroups[key]) failureGroups[key] = [];
          failureGroups[key].push(exp.experienceId);
        } else {
          if (!successGroups[key]) successGroups[key] = [];
          successGroups[key].push(exp.experienceId);
        }
      }

      // Repeated Failures
      for (const [key, evidenceIds] of Object.entries(failureGroups)) {
        if (evidenceIds.length >= this.MIN_OCCURRENCE_THRESHOLD) {
          const [agentId, taskType] = key.split('::');
          const id = `pat:repeated_failure:${agentId}_${taskType}`;
          const confidence: KnowledgeConfidence = evidenceIds.length >= 4 ? 'HIGH' : 'MEDIUM';

          const pattern: KnowledgePattern = {
            id,
            type: 'REPEATED_FAILURE',
            label: `Repeated Task Failures for Agent ${agentId} on ${taskType}`,
            description: `Agent '${agentId}' has failed ${evidenceIds.length} times when executing '${taskType}'.`,
            applicableEntities: [agentId, taskType],
            supportingEvidence: evidenceIds,
            occurrenceCount: evidenceIds.length,
            confidence,
            detectedAt: new Date().toISOString(),
            lastObservedAt: new Date().toISOString(),
            suggestedAction: `Consider routing '${taskType}' to alternative specialized agents or updating prompt instructions.`,
          };
          detected.push(pattern);
          this.patterns.set(id, pattern);
        }
      }

      // Repeated Success / Specialization
      for (const [key, evidenceIds] of Object.entries(successGroups)) {
        if (evidenceIds.length >= this.MIN_OCCURRENCE_THRESHOLD) {
          const [agentId, taskType] = key.split('::');
          const id = `pat:agent_spec:${agentId}_${taskType}`;
          const confidence: KnowledgeConfidence = evidenceIds.length >= 4 ? 'HIGH' : 'MEDIUM';

          const pattern: KnowledgePattern = {
            id,
            type: 'AGENT_SPECIALIZATION',
            label: `Agent Specialization: ${agentId} for ${taskType}`,
            description: `Agent '${agentId}' has succeeded ${evidenceIds.length} times with high reliability for '${taskType}'.`,
            applicableEntities: [agentId, taskType],
            supportingEvidence: evidenceIds,
            occurrenceCount: evidenceIds.length,
            confidence,
            detectedAt: new Date().toISOString(),
            lastObservedAt: new Date().toISOString(),
            suggestedAction: `Prioritize '${agentId}' for '${taskType}' in automated dispatch.`,
          };
          detected.push(pattern);
          this.patterns.set(id, pattern);
        }
      }
    }

    // 2. Detect RECURRING_REPLAN patterns in missions
    if (input.missions) {
      const highReplanMissions = input.missions.filter((m) => (m.replans || 0) >= 2);
      if (highReplanMissions.length >= this.MIN_OCCURRENCE_THRESHOLD) {
        const id = 'pat:recurring_replan:frequent_plan_instability';
        const evidenceIds = highReplanMissions.map((m) => m.missionId);

        const pattern: KnowledgePattern = {
          id,
          type: 'RECURRING_REPLAN',
          label: 'Systemic Mission Replanning Volatility',
          description: `${highReplanMissions.length} missions required repeated dynamic replanning due to upstream failures.`,
          applicableEntities: evidenceIds,
          supportingEvidence: evidenceIds,
          occurrenceCount: highReplanMissions.length,
          confidence: 'MEDIUM',
          detectedAt: new Date().toISOString(),
          lastObservedAt: new Date().toISOString(),
          suggestedAction: 'Add pre-validation checkpoints or increase duration bounds on initial plans.',
        };
        detected.push(pattern);
        this.patterns.set(id, pattern);
      }
    }

    // 3. Detect RECURRING_CONFLICT patterns between agents
    if (input.conflicts) {
      const pairConflicts: Record<string, string[]> = {};
      for (const conf of input.conflicts) {
        if (conf.contendingAgentIds && conf.contendingAgentIds.length >= 2) {
          const sortedPair = [...conf.contendingAgentIds].sort().join('::');
          if (!pairConflicts[sortedPair]) pairConflicts[sortedPair] = [];
          pairConflicts[sortedPair].push(conf.conflictId);
        }
      }

      for (const [pair, conflictIds] of Object.entries(pairConflicts)) {
        if (conflictIds.length >= this.MIN_OCCURRENCE_THRESHOLD) {
          const [agent1, agent2] = pair.split('::');
          const id = `pat:recurring_conflict:${agent1}_vs_${agent2}`;

          const pattern: KnowledgePattern = {
            id,
            type: 'RECURRING_CONFLICT',
            label: `Resource Contention: ${agent1} vs ${agent2}`,
            description: `Agents '${agent1}' and '${agent2}' repeatedly collided over resources ${conflictIds.length} times.`,
            applicableEntities: [agent1, agent2],
            supportingEvidence: conflictIds,
            occurrenceCount: conflictIds.length,
            confidence: 'MEDIUM',
            detectedAt: new Date().toISOString(),
            lastObservedAt: new Date().toISOString(),
            suggestedAction: 'Partition agent execution schedules or enforce staggered milestone dispatch.',
          };
          detected.push(pattern);
          this.patterns.set(id, pattern);
        }
      }
    }

    return detected;
  }

  /**
   * Retrieves all detected patterns, optionally filtered by type.
   */
  public getPatterns(type?: StrategicPatternType): KnowledgePattern[] {
    const all = Array.from(this.patterns.values());
    if (!type) return all;
    return all.filter((p) => p.type === type);
  }

  /**
   * Saves or updates a pattern directly.
   */
  public savePattern(pattern: KnowledgePattern): void {
    this.patterns.set(pattern.id, pattern);
  }

  /**
   * Clears in-memory patterns.
   */
  public clear(): void {
    this.patterns.clear();
  }
}

export const strategicPatternService = new StrategicPatternService();
