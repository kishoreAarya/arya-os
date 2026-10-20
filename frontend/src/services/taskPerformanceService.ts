/**
 * AryaOS V1 — Stage 11: Task Performance Service
 *
 * Contextual task class performance analyzer.
 * Evaluates historical success, quality, and latency by taskType to guide
 * agent matching and plan optimization.
 */

import { TaskPerformanceProfile, ConfidenceBand } from '../types/agentEvaluation';
import { ProviderCapabilityType } from '../types/intelligenceProvider';
import { executionPersistence } from './executionPersistence';

export class TaskPerformanceService {
  /**
   * Helper to determine confidence band from sample size
   */
  public calculateConfidence(sampleSize: number): ConfidenceBand {
    if (sampleSize >= 8) return 'HIGH';
    if (sampleSize >= 3) return 'MEDIUM';
    return 'LOW';
  }

  /**
   * Builds a TaskPerformanceProfile for a specific taskType and optional agentId
   */
  public getTaskProfile(taskType: string, agentId?: string): TaskPerformanceProfile | null {
    const filter = agentId ? { taskType, agentId } : { taskType };
    const experiences = executionPersistence.getExperiences(filter);

    if (experiences.length === 0) {
      return null;
    }

    const sampleSize = experiences.length;
    const successes = experiences.filter(
      (e) =>
        e.status === 'COMPLETED' ||
        e.status === 'SUCCESS' ||
        e.status === 'SUCCEEDED' ||
        e.evaluation.outcome.isSuccess
    ).length;
    const successRate = sampleSize > 0 ? Number((successes / sampleSize).toFixed(2)) : 'UNKNOWN';

    const scored = experiences.filter((e) => typeof e.evaluation.overallScore === 'number');
    const averageQuality =
      scored.length > 0
        ? Number(
            (
              scored.reduce((acc, e) => acc + (e.evaluation.overallScore as number), 0) /
              scored.length
            ).toFixed(2)
          )
        : 'UNKNOWN';

    const averageLatencyMs =
      sampleSize > 0
        ? Number((experiences.reduce((acc, e) => acc + e.latencyMs, 0) / sampleSize).toFixed(0))
        : 'UNKNOWN';

    return {
      agentId: agentId || 'ALL_AGENTS',
      taskType,
      capability: experiences[0].capability,
      sampleSize,
      successRate,
      averageQuality,
      averageLatencyMs,
      confidence: this.calculateConfidence(sampleSize),
      lastObservedAt: experiences[experiences.length - 1].timestamp,
    };
  }

  /**
   * Recommends the highest performing agent for a given task type and capability
   */
  public recommendAgentForTask(
    taskType: string,
    capability?: ProviderCapabilityType
  ): {
    agentId?: string;
    confidence: ConfidenceBand;
    score: number | 'UNKNOWN';
    sampleSize: number;
  } {
    const experiences = executionPersistence.getExperiences({ taskType });
    const relevant = capability
      ? experiences.filter((e) => e.capability === capability)
      : experiences;

    if (relevant.length === 0) {
      return {
        confidence: 'LOW',
        score: 'UNKNOWN',
        sampleSize: 0,
      };
    }

    // Group by agentId
    const byAgent: Record<string, typeof relevant> = {};
    for (const exp of relevant) {
      if (!byAgent[exp.agentId]) byAgent[exp.agentId] = [];
      byAgent[exp.agentId].push(exp);
    }

    let bestAgentId: string | undefined;
    let highestScore = -1;
    let bestSampleSize = 0;

    for (const [agentId, list] of Object.entries(byAgent)) {
      const scored = list.filter((e) => typeof e.evaluation.overallScore === 'number');
      const avgScore =
        scored.length > 0
          ? scored.reduce((acc, e) => acc + (e.evaluation.overallScore as number), 0) /
            scored.length
          : 0;

      if (avgScore > highestScore) {
        highestScore = avgScore;
        bestAgentId = agentId;
        bestSampleSize = list.length;
      }
    }

    return {
      agentId: bestAgentId,
      confidence: this.calculateConfidence(bestSampleSize),
      score: highestScore >= 0 ? Number(highestScore.toFixed(2)) : 'UNKNOWN',
      sampleSize: bestSampleSize,
    };
  }
}

export const taskPerformanceService = new TaskPerformanceService();
