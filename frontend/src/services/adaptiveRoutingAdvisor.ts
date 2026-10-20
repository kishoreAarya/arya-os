/**
 * AryaOS V1 — Stage 11: Adaptive Routing Advisor
 *
 * Safe-mode advisory service for the task planner and operator.
 * Queries empirical task, agent, and provider profiles plus active learning signals
 * to provide optimal routing suggestions without directly dispatching execution or
 * mutating runtime policies.
 */

import { RoutingRecommendation, ConfidenceBand } from '../types/agentEvaluation';
import { ProviderCapabilityType } from '../types/intelligenceProvider';
import { taskPerformanceService } from './taskPerformanceService';
import { providerEvaluationService } from './providerEvaluationService';
import { learningSignalService } from './learningSignalService';

export class AdaptiveRoutingAdvisor {
  /**
   * Generates a safe-mode routing advisory for a task type and capability
   */
  public adviseRoute(
    taskType: string,
    capability: ProviderCapabilityType,
    riskLevel: 'LOW' | 'MEDIUM' | 'HIGH' = 'LOW'
  ): RoutingRecommendation {
    const signals = learningSignalService.getSignals({ status: 'ACTIONABLE' });
    const supportingEvidence: string[] = [];

    // Find best performing agent for this task
    const agentRec = taskPerformanceService.recommendAgentForTask(taskType, capability);
    if (agentRec.agentId) {
      supportingEvidence.push(
        `Agent '${agentRec.agentId}' task score: ${agentRec.score} (${agentRec.sampleSize} samples)`
      );
    }

    // Find best provider for this capability
    const providerRec = providerEvaluationService.getRecommendedProvider(capability);
    let recommendedProviderId = providerRec?.providerId || 'mock';

    if (providerRec) {
      supportingEvidence.push(
        `Provider '${providerRec.providerId}' observed success rate: ${(providerRec.successRate * 100).toFixed(0)}%`
      );
    }

    // Check for negative signals that would disqualify the recommended provider
    const failingProviderSignals = signals.filter(
      (s) =>
        s.signalType === 'PROVIDER_HIGH_FAILURE_RATE' &&
        s.observation.includes(`Provider '${recommendedProviderId}'`)
    );

    if (failingProviderSignals.length > 0) {
      supportingEvidence.push(
        `Provider '${recommendedProviderId}' penalized due to signal: ${failingProviderSignals[0].signalId}`
      );
      // Fallback to safe mock provider
      recommendedProviderId = 'mock';
    }

    if (supportingEvidence.length === 0) {
      supportingEvidence.push(
        `Default baseline route configured: assigned fallback provider '${recommendedProviderId}' for capability '${capability}'.`
      );
    }

    // Calculate aggregated confidence
    let confidence: ConfidenceBand = 'LOW';
    if (agentRec.confidence === 'HIGH' || providerRec?.confidence === 'HIGH') {
      confidence = 'HIGH';
    } else if (agentRec.confidence === 'MEDIUM' || providerRec?.confidence === 'MEDIUM') {
      confidence = 'MEDIUM';
    }

    const reason = agentRec.agentId
      ? `Recommended Agent '${agentRec.agentId}' on Provider '${recommendedProviderId}' based on empirical task score (${agentRec.score}) and provider stability.`
      : `Defaulting to Provider '${recommendedProviderId}' with baseline configuration for task '${taskType}'.`;

    return {
      recommendedAgentId: agentRec.agentId || 'specialist-analyst',
      recommendedProviderId,
      reason,
      supportingEvidence,
      confidence,
      expectedCostTier: 1,
      expectedLatencyMs: 1200,
      riskLevel,
    };
  }
}

export const adaptiveRoutingAdvisor = new AdaptiveRoutingAdvisor();
