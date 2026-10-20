/**
 * AryaOS V1 — Stage 11: Provider Evaluation Service
 *
 * Evaluates provider reliability, latency, cost efficiency, and fallback rates
 * from empirical execution records without mocking or fabricating telemetry.
 */

import {
  ProviderPerformanceProfile,
  ConfidenceBand,
} from '../types/agentEvaluation';
import { ProviderCapabilityType } from '../types/intelligenceProvider';
import { executionPersistence } from './executionPersistence';

export class ProviderEvaluationService {
  /**
   * Helper to determine confidence band from sample size
   */
  public calculateConfidence(sampleSize: number): ConfidenceBand {
    if (sampleSize >= 8) return 'HIGH';
    if (sampleSize >= 3) return 'MEDIUM';
    return 'LOW';
  }

  /**
   * Builds an empirical ProviderPerformanceProfile for a given provider
   */
  public buildProviderProfile(providerId: string): ProviderPerformanceProfile {
    const experiences = executionPersistence.getExperiences({ providerId });
    const capabilities: ProviderPerformanceProfile['capabilities'] = {};

    // Group by capability
    const byCapability: Record<string, typeof experiences> = {};
    for (const exp of experiences) {
      if (!byCapability[exp.capability]) byCapability[exp.capability] = [];
      byCapability[exp.capability].push(exp);
    }

    let overallSuccesses = 0;
    let overallCount = 0;

    for (const [cap, list] of Object.entries(byCapability)) {
      const sampleSize = list.length;
      const successes = list.filter(
        (e) =>
          e.status === 'COMPLETED' ||
          e.status === 'SUCCESS' ||
          e.status === 'SUCCEEDED' ||
          e.evaluation.outcome.isSuccess
      ).length;
      overallSuccesses += successes;
      overallCount += sampleSize;

      const successRate = sampleSize > 0 ? Number((successes / sampleSize).toFixed(2)) : 'UNKNOWN';

      const fallbacks = list.filter((e) => e.evaluation.reliability.fallbackUsed).length;
      const fallbackRate = sampleSize > 0 ? Number((fallbacks / sampleSize).toFixed(2)) : 'UNKNOWN';

      const avgLatency =
        sampleSize > 0
          ? Number((list.reduce((acc, e) => acc + e.latencyMs, 0) / sampleSize).toFixed(0))
          : 'UNKNOWN';

      const scoredCost = list.filter(
        (e) => typeof e.evaluation.cost.efficiencyScore === 'number'
      );
      const costEfficiency =
        scoredCost.length > 0
          ? Number(
              (
                scoredCost.reduce(
                  (acc, e) => acc + (e.evaluation.cost.efficiencyScore as number),
                  0
                ) / scoredCost.length
              ).toFixed(2)
            )
          : 'UNKNOWN';

      capabilities[cap] = {
        observedSuccessRate: successRate,
        averageLatencyMs: avgLatency,
        observedReliability: successRate,
        fallbackRate,
        costEfficiency,
        sampleSize,
        confidence: this.calculateConfidence(sampleSize),
      };
    }

    let availabilityStatus = 'HEALTHY';
    if (overallCount > 0) {
      const overallRate = overallSuccesses / overallCount;
      if (overallRate < 0.4) {
        availabilityStatus = 'UNAVAILABLE';
      } else if (overallRate < 0.8) {
        availabilityStatus = 'DEGRADED';
      }
    }

    return {
      providerId,
      capabilities,
      availabilityStatus,
      lastUpdated: new Date().toISOString(),
    };
  }

  /**
   * Returns profiles for all providers observed in the experience store.
   */
  public getAllProviderProfiles(): ProviderPerformanceProfile[] {
    const experiences = executionPersistence.getExperiences();
    const providerIds = Array.from(new Set(experiences.map((e) => e.providerId)));
    return providerIds.map((id) => this.buildProviderProfile(id));
  }

  /**
   * Recommends the highest reliability provider for a given capability.
   */
  public getRecommendedProvider(
    capability: ProviderCapabilityType
  ): { providerId: string; confidence: ConfidenceBand; successRate: number } | null {
    const profiles = this.getAllProviderProfiles();
    let best: { providerId: string; confidence: ConfidenceBand; successRate: number } | null = null;

    for (const profile of profiles) {
      const capData = profile.capabilities[capability];
      if (capData && typeof capData.observedSuccessRate === 'number') {
        if (!best || capData.observedSuccessRate > best.successRate) {
          best = {
            providerId: profile.providerId,
            confidence: capData.confidence,
            successRate: capData.observedSuccessRate,
          };
        }
      }
    }

    return best;
  }
}

export const providerEvaluationService = new ProviderEvaluationService();
