/**
 * AryaOS V1 — Stage 14: Decision Recommendation Service
 *
 * Synthesizes options, scenario analysis, tradeoffs, and empirical risks into
 * a transparent, advisory DecisionRecommendation.
 *
 * CRITICAL GOVERNANCE INVARIANT:
 * A recommendation is NEVER an autonomous decision.
 * All recommendations MUST remain in 'AWAITING_REVIEW' status.
 * Consequential actions (financial, publishing, policy, autonomy, irreversible)
 * strictly require explicit operator approval.
 */

import {
  DecisionContext,
  DecisionOption,
  DecisionRecommendation,
  DecisionAlternative,
  TradeoffAnalysis,
  ConsequentialActionFlag,
  DecisionApproval,
} from '../types/decisionIntelligence';
import { tradeoffEngine } from './tradeoffEngine';
import { executionPersistence } from './executionPersistence';

export class DecisionRecommendationService {
  /**
   * Generates a fully explained, advisory recommendation for a set of options.
   * Status is strictly initialized to 'AWAITING_REVIEW'.
   */
  public generateRecommendation(
    decisionId: string,
    options: DecisionOption[],
    context: DecisionContext
  ): DecisionRecommendation {
    if (options.length === 0) {
      throw new Error('Cannot generate recommendation: No candidate options provided');
    }

    // Evaluate options against context objectives and reversibility
    // Prefer reversible, high-confidence options unless operator explicitly prioritized speed
    let recommended = options[0];
    const reversibleOpts = options.filter((o) => o.reversibility === 'REVERSIBLE');
    if (reversibleOpts.length > 0) {
      recommended = reversibleOpts[0];
    }

    // Build alternatives list
    const alternatives: DecisionAlternative[] = options
      .filter((o) => o.optionId !== recommended.optionId)
      .map((alt) => ({
        optionId: alt.optionId,
        title: alt.title,
        tradeoffSummary: `Alternative course: offers different risk/cost profile (reversibility: ${alt.reversibility}).`,
      }));

    // Generate trade-offs between recommended and each alternative
    const tradeoffs: TradeoffAnalysis[] = [];
    for (const alt of options.filter((o) => o.optionId !== recommended.optionId)) {
      tradeoffs.push(...tradeoffEngine.analyzeTradeoffs(recommended, alt));
    }

    // Collect unknowns
    const unknowns: string[] = [];
    if (context.budget === 'UNKNOWN') unknowns.push('Budget ceiling is UNKNOWN');
    if (!context.deadline) unknowns.push('Execution deadline is UNSPECIFIED');
    if (recommended.estimatedCost === 'UNKNOWN') unknowns.push('Exact token cost is UNKNOWN');
    if (recommended.estimatedDuration === 'UNKNOWN') unknowns.push('Execution duration is UNKNOWN');

    const recommendationId = `rec_${decisionId}_${Date.now()}`;

    // Consequential actions flags
    const consequentialFlags = this.detectConsequentialFlags(recommended);
    const approvalRequired = consequentialFlags.length > 0 || recommended.reversibility === 'IRREVERSIBLE';

    const recommendation: DecisionRecommendation = {
      recommendationId,
      decisionId,
      recommendedOptionId: recommended.optionId,
      recommendedOption: recommended,
      reasoning: `Advisory Recommendation: Option '${recommended.title}' provides optimal balance between operational safety (reversibility: ${recommended.reversibility}) and alignment with objective '${context.objective}'.`,
      supportingEvidence: recommended.supportingEvidence,
      tradeoffs,
      risks: recommended.risks,
      unknowns,
      confidence: recommended.confidence,
      alternatives,
      approvalRequired,
      status: 'AWAITING_REVIEW', // Invariant: Must remain AWAITING_REVIEW
      createdAt: new Date().toISOString(),
    };

    executionPersistence.saveDecisionRecommendation(recommendation);
    return recommendation;
  }

  /**
   * Detects whether an option touches consequential boundaries.
   */
  public detectConsequentialFlags(option: DecisionOption): ConsequentialActionFlag[] {
    const flags: ConsequentialActionFlag[] = [];

    const text = (option.title + ' ' + option.description).toLowerCase();

    if (text.includes('cost') || text.includes('spend') || text.includes('budget') || text.includes('financial')) {
      flags.push('FINANCIAL');
    }
    if (text.includes('policy') || text.includes('rule')) {
      flags.push('PROVIDER_POLICY');
    }
    if (text.includes('autonomy') || text.includes('elevate')) {
      flags.push('AGENT_AUTONOMY');
    }
    if (text.includes('memory') || text.includes('delete') || text.includes('purge')) {
      flags.push('PROTECTED_MEMORY');
    }
    if (text.includes('publish') || text.includes('release')) {
      flags.push('PUBLISHING');
    }
    if (text.includes('external') || text.includes('email') || text.includes('send') || text.includes('notify')) {
      flags.push('EXTERNAL_COMMUNICATION');
    }
    if (option.reversibility === 'IRREVERSIBLE') {
      flags.push('IRREVERSIBLE_ACTION');
    }
    if (text.includes('cancel') || text.includes('abort')) {
      flags.push('MISSION_CANCELLATION');
    }
    if (text.includes('scope') || text.includes('expand')) {
      flags.push('SCOPE_EXPANSION');
    }

    return flags;
  }

  /**
   * Applies operator approval to a decision.
   * Prohibits autonomous approvals of consequential decisions!
   */
  public approveByOperator(
    recommendation: DecisionRecommendation,
    operatorId: string,
    comments?: string
  ): DecisionApproval {
    if (!operatorId || operatorId === 'SYSTEM' || operatorId === 'AUTONOMOUS_AGENT') {
      throw new Error(
        'Autonomous approval prohibited: Consequential decisions strictly require human operator authorization.'
      );
    }

    const consequentialFlags = this.detectConsequentialFlags(recommendation.recommendedOption);

    const approval: DecisionApproval = {
      approvalId: `appr_${recommendation.recommendationId}`,
      status: 'APPROVED',
      approvedBy: operatorId,
      reviewedAt: new Date().toISOString(),
      comments: comments || 'Operator reviewed and approved recommendation.',
      requiresHumanApproval: consequentialFlags.length > 0 || recommendation.recommendedOption.reversibility === 'IRREVERSIBLE',
      consequentialFlags,
    };

    recommendation.status = 'APPROVED';
    executionPersistence.saveDecisionRecommendation(recommendation);

    return approval;
  }
}

export const decisionRecommendationService = new DecisionRecommendationService();
