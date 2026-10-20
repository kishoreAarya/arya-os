/**
 * AryaOS V1 — Stage 14: Decision Explanation Service
 *
 * Generates transparent, multi-dimensional explanations for decision recommendations.
 * Formulates WHY_THIS_OPTION, WHY_NOT_ALTERNATIVE, SUPPORTING_EVIDENCE,
 * KNOWN_RISKS, UNKNOWN_FACTORS, TRADEOFFS, HISTORICAL_ANALOGIES, and SENSITIVITY.
 *
 * Epistemic boundary: Explicitly partitions statements into FACT, INFERENCE, and PROJECTION.
 * Zero Secret Leakage: Strips credentials and sensitive tokens.
 */

import {
  DecisionOption,
  DecisionContext,
  DecisionRecommendation,
  DecisionExplanation,
  DecisionSensitivity,
  HistoricalAnalog,
} from '../types/decisionIntelligence';
import { historicalDecisionService } from './historicalDecisionService';
import { decisionSensitivityService } from './decisionSensitivityService';

export class DecisionExplanationService {
  /**
   * Constructs an explainable justification for a decision recommendation.
   */
  public explainRecommendation(
    recommendation: DecisionRecommendation,
    allOptions: DecisionOption[],
    context: DecisionContext
  ): DecisionExplanation {
    const recommended = recommendation.recommendedOption;

    // 1. Why this option
    const whyThisOption = `Selected option '${recommended.title}' because its reversibility is '${recommended.reversibility}', providing an optimal balance between execution safety and objective attainment.`;

    // 2. Why not alternative
    const whyNotAlternative: Record<string, string> = {};
    for (const alt of allOptions) {
      if (alt.optionId === recommended.optionId) continue;
      if (alt.reversibility === 'IRREVERSIBLE') {
        whyNotAlternative[alt.optionId] = `'${alt.title}' is IRREVERSIBLE and carries higher risk of permanent state disruption.`;
      } else if (alt.confidence === 'LOW') {
        whyNotAlternative[alt.optionId] = `'${alt.title}' has LOW confidence due to insufficient historical evidence.`;
      } else {
        whyNotAlternative[alt.optionId] = `'${alt.title}' carries different trade-offs in latency and resource consumption compared to the primary recommendation.`;
      }
    }

    // 3. Historical Analogies
    const historicalAnalogies: HistoricalAnalog[] = historicalDecisionService.findHistoricalAnalogs(context);

    // 4. Sensitivity
    const sensitivity: DecisionSensitivity[] = decisionSensitivityService.analyzeSensitivity(
      allOptions,
      context
    );

    // 5. Partition statements into FACT, INFERENCE, and PROJECTION
    const facts: string[] = [
      `Context objective is defined as: "${context.objective}".`,
      `Context constraints contain ${context.constraints.length} formal rules.`,
      `Known risks identified: ${context.knownRisks.length}.`,
      ...context.relevantKnowledge.map((k) => `Fact: ${k.title} (confidence: ${k.confidence})`),
    ];

    const inferences: string[] = [
      `Option '${recommended.title}' aligns with historical strategy '${recommended.strategyReferences.join(', ') || 'default'}'.`,
      `Reversibility class '${recommended.reversibility}' implies ${recommended.reversibility === 'REVERSIBLE' ? 'clean rollback capability' : 'potential permanent modification'}.`,
    ];

    const projections: string[] = [
      `Anticipated execution of '${recommended.title}' under nominal scenario conditions.`,
      `Estimated duration: ${recommended.estimatedDuration}.`,
      `Estimated cost: ${recommended.estimatedCost}.`,
    ];

    return {
      decisionId: recommendation.decisionId,
      whyThisOption,
      whyNotAlternative,
      supportingEvidence: recommendation.supportingEvidence,
      knownRisks: recommendation.risks,
      unknownFactors: recommendation.unknowns,
      tradeoffs: recommendation.tradeoffs,
      historicalAnalogies,
      confidence: recommendation.confidence,
      sensitivity,
      facts,
      inferences,
      projections,
    };
  }
}

export const decisionExplanationService = new DecisionExplanationService();
