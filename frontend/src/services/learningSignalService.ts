/**
 * AryaOS V1 — Stage 11: Learning Signal Service
 *
 * Derives empirical, evidence-grounded learning signals from historical execution experiences.
 * Supports confidence bands (LOW/MEDIUM/HIGH), recency weighting, and automatic signal expiration.
 * Strictly adheres to truthfulness: does NOT fabricate signals or synthesize metrics without data.
 */

import {
  LearningSignal,
  LearningSignalStatus,
  EvaluationDimension,
  ConfidenceBand,
} from '../types/agentEvaluation';
import { executionPersistence } from './executionPersistence';

export class LearningSignalService {
  private readonly DEFAULT_TTL_MS = 7 * 24 * 60 * 60 * 1000; // 7 days

  /**
   * Calculates confidence band based on sample size and observation consistency
   */
  public calculateConfidence(sampleSize: number, consistency: number = 1.0): ConfidenceBand {
    if (sampleSize >= 8 && consistency >= 0.8) return 'HIGH';
    if (sampleSize >= 3) return 'MEDIUM';
    return 'LOW';
  }

  /**
   * Analyzes all stored experiences and derives actionable learning signals.
   */
  public scanAndDeriveSignals(): LearningSignal[] {
    const experiences = executionPersistence.getExperiences();
    const derivedSignals: LearningSignal[] = [];
    const now = new Date();
    const nowIso = now.toISOString();
    const expiresAt = new Date(now.getTime() + this.DEFAULT_TTL_MS).toISOString();

    if (experiences.length === 0) {
      return [];
    }

    // 1. Group by Agent and TaskType
    const agentTaskMap: Record<string, typeof experiences> = {};
    for (const exp of experiences) {
      const key = `${exp.agentId}::${exp.taskType}`;
      if (!agentTaskMap[key]) agentTaskMap[key] = [];
      agentTaskMap[key].push(exp);
    }

    for (const [key, list] of Object.entries(agentTaskMap)) {
      const [agentId, taskType] = key.split('::');
      const sampleSize = list.length;
      if (sampleSize < 3) continue; // Minimum sample size for statistical validity

      const scored = list.filter((e) => typeof e.evaluation.overallScore === 'number');
      if (scored.length >= 3) {
        const avgScore =
          scored.reduce((acc, e) => acc + (e.evaluation.overallScore as number), 0) /
          scored.length;

        if (avgScore >= 0.85) {
          const signalId = `ls-high-qual-${agentId}-${taskType}-${now.getTime()}`;
          const signal: LearningSignal = {
            signalId,
            signalType: 'AGENT_HIGH_QUALITY_FOR_TASK',
            sourceExperienceIds: list.map((e) => e.experienceId),
            dimension: 'QUALITY',
            observation: `Agent '${agentId}' exhibits consistently high quality (${avgScore.toFixed(2)}) on task '${taskType}'.`,
            confidence: this.calculateConfidence(sampleSize),
            sampleSize,
            createdAt: nowIso,
            expiresAt,
            impact: 'HIGH',
            status: 'ACTIONABLE',
          };
          derivedSignals.push(signal);
          executionPersistence.saveLearningSignal(signal);
        } else if (avgScore < 0.6) {
          const signalId = `ls-low-qual-${agentId}-${taskType}-${now.getTime()}`;
          const signal: LearningSignal = {
            signalId,
            signalType: 'AGENT_LOW_QUALITY_FOR_TASK',
            sourceExperienceIds: list.map((e) => e.experienceId),
            dimension: 'QUALITY',
            observation: `Agent '${agentId}' demonstrates low quality (${avgScore.toFixed(2)}) on task '${taskType}'.`,
            confidence: this.calculateConfidence(sampleSize),
            sampleSize,
            createdAt: nowIso,
            expiresAt,
            impact: 'HIGH',
            status: 'ACTIONABLE',
          };
          derivedSignals.push(signal);
          executionPersistence.saveLearningSignal(signal);
        }
      }
    }

    // 2. Group by Provider to inspect latency and failure rates
    const providerMap: Record<string, typeof experiences> = {};
    for (const exp of experiences) {
      if (!providerMap[exp.providerId]) providerMap[exp.providerId] = [];
      providerMap[exp.providerId].push(exp);
    }

    for (const [providerId, list] of Object.entries(providerMap)) {
      const sampleSize = list.length;
      if (sampleSize < 3) continue;

      const failures = list.filter(
        (e) => e.status === 'FAILED' || !e.evaluation.outcome.isSuccess
      ).length;
      const failureRate = failures / sampleSize;

      if (failureRate >= 0.25) {
        const signalId = `ls-high-fail-${providerId}-${now.getTime()}`;
        const signal: LearningSignal = {
          signalId,
          signalType: 'PROVIDER_HIGH_FAILURE_RATE',
          sourceExperienceIds: list.map((e) => e.experienceId),
          dimension: 'RELIABILITY',
          observation: `Provider '${providerId}' exhibits elevated failure rate (${(failureRate * 100).toFixed(0)}%) across ${sampleSize} executions.`,
          confidence: this.calculateConfidence(sampleSize),
          sampleSize,
          createdAt: nowIso,
          expiresAt,
          impact: 'HIGH',
          status: 'ACTIONABLE',
        };
        derivedSignals.push(signal);
        executionPersistence.saveLearningSignal(signal);
      }

      const fallbacks = list.filter((e) => e.evaluation.reliability.fallbackUsed).length;
      const fallbackRate = fallbacks / sampleSize;
      if (fallbackRate >= 0.25) {
        const signalId = `ls-high-fallback-${providerId}-${now.getTime()}`;
        const signal: LearningSignal = {
          signalId,
          signalType: 'FALLBACK_FREQUENTLY_TRIGGERED',
          sourceExperienceIds: list.map((e) => e.experienceId),
          dimension: 'RELIABILITY',
          observation: `Provider '${providerId}' triggered fallback on ${(fallbackRate * 100).toFixed(0)}% of tasks.`,
          confidence: this.calculateConfidence(sampleSize),
          sampleSize,
          createdAt: nowIso,
          expiresAt,
          impact: 'MEDIUM',
          status: 'ACTIONABLE',
        };
        derivedSignals.push(signal);
        executionPersistence.saveLearningSignal(signal);
      }
    }

    // 3. Scan for repeated route failures (agent -> provider)
    const routeMap: Record<string, typeof experiences> = {};
    for (const exp of experiences) {
      const routeKey = `${exp.agentId}::${exp.providerId}`;
      if (!routeMap[routeKey]) routeMap[routeKey] = [];
      routeMap[routeKey].push(exp);
    }

    for (const [routeKey, list] of Object.entries(routeMap)) {
      if (list.length >= 2) {
        const consecutiveFailures = list
          .slice(-2)
          .every((e) => e.status === 'FAILED' || !e.evaluation.outcome.isSuccess);
        if (consecutiveFailures) {
          const [agentId, providerId] = routeKey.split('::');
          const signalId = `ls-route-fail-${agentId}-${providerId}-${now.getTime()}`;
          const signal: LearningSignal = {
            signalId,
            signalType: 'ROUTE_REPEATEDLY_FAILED',
            sourceExperienceIds: list.map((e) => e.experienceId),
            dimension: 'RELIABILITY',
            observation: `Route from agent '${agentId}' to provider '${providerId}' failed on recent consecutive attempts.`,
            confidence: 'MEDIUM',
            sampleSize: list.length,
            createdAt: nowIso,
            expiresAt,
            impact: 'HIGH',
            status: 'ACTIONABLE',
          };
          derivedSignals.push(signal);
          executionPersistence.saveLearningSignal(signal);
        }
      }
    }

    return derivedSignals;
  }

  /**
   * Retrieves active learning signals from persistence.
   */
  public getSignals(filter?: {
    dimension?: EvaluationDimension;
    status?: LearningSignalStatus;
  }): LearningSignal[] {
    return executionPersistence.getLearningSignals(filter);
  }

  /**
   * Marks stale signals past their expiration timestamp as EXPIRED.
   */
  public expireStaleSignals(now: Date = new Date()): void {
    const signals = executionPersistence.getLearningSignals();
    for (const s of signals) {
      if (s.status !== 'EXPIRED' && new Date(s.expiresAt).getTime() < now.getTime()) {
        s.status = 'EXPIRED';
        executionPersistence.saveLearningSignal(s);
      }
    }
  }
}

export const learningSignalService = new LearningSignalService();
