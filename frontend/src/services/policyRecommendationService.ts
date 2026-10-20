/**
 * AryaOS V1 — Stage 11: Policy Recommendation Service
 *
 * Advisory-only policy recommendation engine.
 * strictly forbids autonomous self-modification of executable policies or code.
 * Every recommendation requires explicit human operator review and approval
 * before any policy adjustment can be applied.
 */

import {
  PolicyRecommendation,
  RecommendationStatus,
} from '../types/agentEvaluation';
import { executionPersistence } from './executionPersistence';
import { learningSignalService } from './learningSignalService';
import { evidenceGraph } from './evidenceGraph';

export class PolicyRecommendationService {
  /**
   * Generates advisory policy recommendations derived from active learning signals.
   */
  public generateRecommendationsFromSignals(): PolicyRecommendation[] {
    const signals = learningSignalService.getSignals({ status: 'ACTIONABLE' });
    const generated: PolicyRecommendation[] = [];
    const nowIso = new Date().toISOString();

    for (const signal of signals) {
      if (signal.signalType === 'PROVIDER_HIGH_FAILURE_RATE') {
        const providerMatch = signal.observation.match(/Provider '([^']+)'/);
        const providerId = providerMatch ? providerMatch[1] : 'UNKNOWN';

        const recId = `rec-demote-${providerId}-${Date.now()}`;
        const rec: PolicyRecommendation = {
          recommendationId: recId,
          reason: `Signal ${signal.signalId}: Provider '${providerId}' exhibits high failure rate. Recommend demoting from primary route.`,
          evidenceSignalIds: [signal.signalId],
          affectedPolicy: 'intelligence_provider_routing',
          proposedAdjustment: {
            action: 'DEMOTE_PROVIDER',
            providerId,
            suggestedFallbackProvider: 'mock',
          },
          expectedImpact: 'Reduces goal failure rate and prevents cascading task timeouts.',
          risk: 'MEDIUM',
          confidence: signal.confidence,
          status: 'PROPOSED',
          requiresHumanApproval: true,
          proposedAt: nowIso,
        };
        generated.push(rec);
        executionPersistence.savePolicyRecommendation(rec);
      } else if (signal.signalType === 'AGENT_HIGH_QUALITY_FOR_TASK') {
        const agentMatch = signal.observation.match(/Agent '([^']+)'/);
        const taskMatch = signal.observation.match(/task '([^']+)'/);
        const agentId = agentMatch ? agentMatch[1] : 'UNKNOWN';
        const taskType = taskMatch ? taskMatch[1] : 'UNKNOWN';

        const recId = `rec-pref-${agentId}-${taskType}-${Date.now()}`;
        const rec: PolicyRecommendation = {
          recommendationId: recId,
          reason: `Signal ${signal.signalId}: Agent '${agentId}' exhibits consistently high quality on task '${taskType}'. Recommend setting as preferred specialist.`,
          evidenceSignalIds: [signal.signalId],
          affectedPolicy: 'agent_task_dispatch',
          proposedAdjustment: {
            action: 'SET_PREFERRED_AGENT',
            agentId,
            taskType,
          },
          expectedImpact: 'Improves first-pass output quality and reduces replanning frequency.',
          risk: 'LOW',
          confidence: signal.confidence,
          status: 'PROPOSED',
          requiresHumanApproval: true,
          proposedAt: nowIso,
        };
        generated.push(rec);
        executionPersistence.savePolicyRecommendation(rec);
      } else if (signal.signalType === 'ROUTE_REPEATEDLY_FAILED') {
        const routeMatch = signal.observation.match(/agent '([^']+)' to provider '([^']+)'/);
        const agentId = routeMatch ? routeMatch[1] : 'UNKNOWN';
        const providerId = routeMatch ? routeMatch[2] : 'UNKNOWN';

        const recId = `rec-block-route-${agentId}-${providerId}-${Date.now()}`;
        const rec: PolicyRecommendation = {
          recommendationId: recId,
          reason: `Signal ${signal.signalId}: Route '${agentId} -> ${providerId}' repeatedly failed. Recommend temporarily routing agent to alternate provider.`,
          evidenceSignalIds: [signal.signalId],
          affectedPolicy: 'agent_provider_bindings',
          proposedAdjustment: {
            action: 'REROUTE_AGENT',
            agentId,
            disallowedProviderId: providerId,
          },
          expectedImpact: 'Prevents repeated route stalls and preserves goal execution momentum.',
          risk: 'HIGH',
          confidence: signal.confidence,
          status: 'PROPOSED',
          requiresHumanApproval: true,
          proposedAt: nowIso,
        };
        generated.push(rec);
        executionPersistence.savePolicyRecommendation(rec);
      }
    }

    return generated;
  }

  /**
   * Human operator reviews a policy recommendation.
   */
  public reviewRecommendation(
    recommendationId: string,
    decision: 'APPROVED' | 'REJECTED',
    reviewedBy: string,
    rejectionReason?: string
  ): PolicyRecommendation | null {
    const list = executionPersistence.getPolicyRecommendations();
    const rec = list.find((r) => r.recommendationId === recommendationId);
    if (!rec) return null;

    rec.status = decision === 'APPROVED' ? 'APPROVED' : 'REJECTED';
    rec.reviewedAt = new Date().toISOString();
    rec.reviewedBy = reviewedBy;
    if (decision === 'REJECTED' && rejectionReason) {
      rec.rejectionReason = rejectionReason;
    }

    executionPersistence.savePolicyRecommendation(rec);

    // Record human decision in EvidenceGraph
    evidenceGraph.createEvidenceItem(
      'HUMAN_APPROVAL',
      `gov-${recommendationId}`,
      `Operator ${reviewedBy} ${decision} recommendation ${recommendationId}`,
      reviewedBy,
      'HIGH',
      { decision, rejectionReason }
    );
    evidenceGraph.linkEntities(recommendationId, `gov-${recommendationId}`, 'REVIEWED_BY_OPERATOR');

    return rec;
  }

  /**
   * Applies an APPROVED recommendation.
   * strictly fails if the recommendation is not explicitly approved by an operator.
   */
  public applyRecommendation(recommendationId: string): boolean {
    const list = executionPersistence.getPolicyRecommendations();
    const rec = list.find((r) => r.recommendationId === recommendationId);
    if (!rec) return false;

    // Enforce Human Governance Invariant: Cannot apply without human approval
    if (rec.status !== 'APPROVED') {
      console.warn(
        `[PolicyRecommendationService] Security Boundary: Cannot apply recommendation '${recommendationId}' because status is '${rec.status}', not 'APPROVED'.`
      );
      return false;
    }

    rec.status = 'IMPLEMENTED';
    executionPersistence.savePolicyRecommendation(rec);
    return true;
  }

  /**
   * Retrieves pending recommendations requiring human review.
   */
  public getPendingRecommendations(): PolicyRecommendation[] {
    return executionPersistence.getPolicyRecommendations('PROPOSED');
  }

  /**
   * Retrieves all recommendations.
   */
  public getAllRecommendations(): PolicyRecommendation[] {
    return executionPersistence.getPolicyRecommendations();
  }
}

export const policyRecommendationService = new PolicyRecommendationService();
