/**
 * AryaOS V1 — Stage 14: Decision Sensitivity Service
 *
 * Evaluates which operational assumptions most dramatically impact decision outcomes.
 * Classifies sensitivity into HIGH_IMPACT_ASSUMPTION, MEDIUM_IMPACT_ASSUMPTION,
 * and LOW_IMPACT_ASSUMPTION with transparent rationales and evidence links.
 */

import {
  DecisionContext,
  DecisionOption,
  DecisionSensitivity,
  SensitivityImpact,
} from '../types/decisionIntelligence';

export class DecisionSensitivityService {
  /**
   * Analyzes sensitivity of options to underlying assumptions.
   */
  public analyzeSensitivity(
    options: DecisionOption[],
    context: DecisionContext
  ): DecisionSensitivity[] {
    const sensitivities: DecisionSensitivity[] = [];

    // 1. Provider Latency / Availability Assumption
    const parallelOrDeepOpts = options.filter(
      (o) => o.title.includes('Parallel') || o.title.includes('Deep')
    );
    if (parallelOrDeepOpts.length > 0) {
      sensitivities.push({
        id: 'sens_provider_latency',
        assumption: 'Provider API maintains stable response latency (< 2.5s) under high concurrency',
        impact: 'HIGH_IMPACT_ASSUMPTION',
        evidence: context.relevantKnowledge.map((k) => k.id),
        affectedOptions: parallelOrDeepOpts.map((o) => o.optionId),
        rationale:
          'If provider latency spikes or rate-limits trigger, parallel and consensus strategies experience severe latency degradation.',
      });
    }

    // 2. Budget Ceiling Assumption
    if (context.budget !== 'UNKNOWN') {
      sensitivities.push({
        id: 'sens_budget_ceiling',
        assumption: `Operational cost must not exceed ${context.budget} USD`,
        impact: 'HIGH_IMPACT_ASSUMPTION',
        evidence: [],
        affectedOptions: options.map((o) => o.optionId),
        rationale:
          'A fixed budget ceiling will abruptly throttle high-concurrency or deep multi-model synthesis options.',
      });
    } else {
      sensitivities.push({
        id: 'sens_budget_unknown',
        assumption: 'Budget ceiling is unconstrained or UNKNOWN',
        impact: 'MEDIUM_IMPACT_ASSUMPTION',
        evidence: [],
        affectedOptions: options.map((o) => o.optionId),
        rationale:
          'Lack of explicit budget ceiling creates risk of uncontrolled provider token accumulation.',
      });
    }

    // 3. Reversibility / Rollback Assumption
    const irreversibleOpts = options.filter((o) => o.reversibility === 'IRREVERSIBLE');
    if (irreversibleOpts.length > 0) {
      sensitivities.push({
        id: 'sens_reversibility',
        assumption: 'Action side-effects cannot be cleanly undone via automatic checkpoint rollback',
        impact: 'HIGH_IMPACT_ASSUMPTION',
        evidence: [],
        affectedOptions: irreversibleOpts.map((o) => o.optionId),
        rationale:
          'Irreversible actions carry permanent state risk; human verification is strictly required before dispatch.',
      });
    }

    // 4. Strategic Contradictions Assumption
    if (context.openContradictions.length > 0) {
      sensitivities.push({
        id: 'sens_contradictions',
        assumption: 'Conflicting historical knowledge does not invalidate execution prerequisites',
        impact: 'MEDIUM_IMPACT_ASSUMPTION',
        evidence: context.openContradictions.map((c) => c.id),
        affectedOptions: options.map((o) => o.optionId),
        rationale:
          'Open contradictions in the strategic knowledge graph may indicate divergent reality models.',
      });
    }

    // 5. Worker Agent Responsiveness (Low impact baseline)
    sensitivities.push({
      id: 'sens_agent_health',
      assumption: 'Assigned worker agent processes will remain alive and responsive in runtime loop',
      impact: 'LOW_IMPACT_ASSUMPTION',
      evidence: [],
      affectedOptions: options.map((o) => o.optionId),
      rationale:
        'Stage 09 durable recovery automatically recovers from isolated worker process crashes.',
    });

    return sensitivities;
  }
}

export const decisionSensitivityService = new DecisionSensitivityService();
