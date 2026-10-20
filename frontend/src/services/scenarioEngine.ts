/**
 * AryaOS V1 — Stage 14: Scenario Engine
 *
 * Simulates option behaviors under distinct operational scenario models:
 * BASELINE, OPTIMISTIC, CONSTRAINED, FAILURE, DEADLINE_PRESSURE, BUDGET_PRESSURE.
 * Preserves epistemic honesty: scenarios are projections, never masquerading as facts.
 */

import {
  DecisionOption,
  DecisionContext,
  Scenario,
  ScenarioType,
  ScenarioOutcome,
  DecisionConfidence,
} from '../types/decisionIntelligence';
import { consequenceSimulator } from './consequenceSimulator';

export class ScenarioEngine {
  /**
   * Generates all scenario projections for a given option and decision context.
   */
  public generateScenarios(option: DecisionOption, context: DecisionContext): Scenario[] {
    const baseOutcome = consequenceSimulator.simulateOutcome(option, context);
    const scenarioTypes: ScenarioType[] = [
      'BASELINE',
      'OPTIMISTIC',
      'CONSTRAINED',
      'FAILURE',
      'DEADLINE_PRESSURE',
      'BUDGET_PRESSURE',
    ];

    return scenarioTypes.map((type) => this.buildScenario(type, option, context, baseOutcome));
  }

  private buildScenario(
    type: ScenarioType,
    option: DecisionOption,
    context: DecisionContext,
    baseOutcome: ScenarioOutcome
  ): Scenario {
    switch (type) {
      case 'BASELINE':
        return {
          id: `scen_base_${option.optionId}`,
          type: 'BASELINE',
          name: 'Baseline Operational Scenario',
          description: 'Standard operational conditions with nominal provider latency and standard availability.',
          outcome: {
            ...baseOutcome,
            expectedOutcome: `Option '${option.title}' executes under expected operational conditions.`,
            label: 'PROJECTED',
          },
          keyAssumptions: [
            'Provider API latency remains within nominal bounds (500ms - 2000ms)',
            'Worker agents are unblocked and responsive',
          ],
          confidence: option.confidence,
        };

      case 'OPTIMISTIC':
        return {
          id: `scen_opt_${option.optionId}`,
          type: 'OPTIMISTIC',
          name: 'Optimistic Performance Scenario',
          description: 'Zero transient provider errors, optimal cache hits, immediate agent convergence.',
          outcome: {
            ...baseOutcome,
            expectedOutcome: `Maximum efficiency: task finishes early with superior quality.`,
            deadlineImpact: 'Completes 30-50% faster than baseline estimates.',
            label: 'PROJECTED',
          },
          keyAssumptions: [
            '100% provider availability with zero retries',
            'No multi-agent resource contention',
          ],
          confidence: 'LOW' as DecisionConfidence,
        };

      case 'CONSTRAINED':
        return {
          id: `scen_constr_${option.optionId}`,
          type: 'CONSTRAINED',
          name: 'Constrained Resource Scenario',
          description: 'Reduced worker concurrency, strict token quota throttling, and serialized operations.',
          outcome: {
            ...baseOutcome,
            expectedOutcome: `Option execution delayed due to rate limiting or resource arbitration holds.`,
            resourceImpact: 'High contention on shared gateway slots.',
            label: 'PROJECTED',
          },
          keyAssumptions: [
            'Concurrent execution quota restricted by ResourceGovernor',
            'Worker agents queue for available provider leases',
          ],
          confidence: 'MEDIUM' as DecisionConfidence,
        };

      case 'FAILURE':
        return {
          id: `scen_fail_${option.optionId}`,
          type: 'FAILURE',
          name: 'Fault & Degradation Scenario',
          description: 'Provider timeout, model divergence, or unhandled dependency failure.',
          outcome: {
            ...baseOutcome,
            expectedOutcome: `Task encounters execution failure; recovery policy required.`,
            failureModes: [
              ...baseOutcome.failureModes,
              {
                description: 'Provider API returns repeated 5xx errors or network disconnection',
                type: 'SPECULATIVE',
                evidenceIds: [],
              },
            ],
            recoveryImplications:
              option.reversibility === 'REVERSIBLE'
                ? 'Automatic rollback to last valid checkpoint via Stage 09 durable recovery.'
                : 'Irreversible action causes partial divergence requiring human intervention.',
            label: 'PROJECTED',
          },
          keyAssumptions: [
            'Upstream provider failure triggers fallback routing or error classification',
          ],
          confidence: 'MEDIUM' as DecisionConfidence,
        };

      case 'DEADLINE_PRESSURE':
        return {
          id: `scen_dead_${option.optionId}`,
          type: 'DEADLINE_PRESSURE',
          name: 'Deadline Pressure Scenario',
          description: 'Immediate deadline forces accelerated execution or scope shedding.',
          outcome: {
            ...baseOutcome,
            expectedOutcome:
              option.title.includes('Parallel')
                ? 'Accelerates execution to meet strict deadline with higher cost.'
                : 'Sequential execution risks missing the target deadline.',
            deadlineImpact: 'Requires trade-off between speed and deep verification.',
            label: 'PROJECTED',
          },
          keyAssumptions: [
            'Strict deadline cannot be extended; operator requires immediate delivery',
          ],
          confidence: 'MEDIUM' as DecisionConfidence,
        };

      case 'BUDGET_PRESSURE':
        return {
          id: `scen_budg_${option.optionId}`,
          type: 'BUDGET_PRESSURE',
          name: 'Budget Pressure Scenario',
          description: 'Tight budget ceiling requires cost conservation and cheaper model routing.',
          outcome: {
            ...baseOutcome,
            expectedOutcome:
              option.title.includes('Conservative')
                ? 'Maintains strict cost control within budget limits.'
                : 'Token usage may approach budget threshold, triggering approval gate.',
            resourceImpact: 'Budget throttling activated; expensive model routing prohibited.',
            label: 'PROJECTED',
          },
          keyAssumptions: [
            'Operational cost ceiling strictly enforced by ResourceGovernor',
          ],
          confidence: 'MEDIUM' as DecisionConfidence,
        };
    }
  }
}

export const scenarioEngine = new ScenarioEngine();
