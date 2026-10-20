/**
 * AryaOS V1 — Stage 14: Consequence Simulator
 *
 * Deterministic consequence simulator operating strictly on empirical evidence,
 * historical patterns, and strategic rules without executing providers.
 *
 * Enforces explicit labeling: OBSERVED | INFERRED | PROJECTED | UNKNOWN.
 */

import {
  DecisionOption,
  DecisionContext,
  Consequence,
  ScenarioOutcome,
  DecisionEvidenceLabel,
  RiskAssessment,
} from '../types/decisionIntelligence';

export class ConsequenceSimulator {
  /**
   * Simulates multidimensional consequences for a decision option.
   */
  public simulateConsequences(option: DecisionOption, context: DecisionContext): Consequence[] {
    const consequences: Consequence[] = [];

    // 1. Quality Consequence
    if (option.title.includes('Deep Multi-Perspective') || option.title.includes('Quality')) {
      consequences.push({
        id: `c_qual_${option.optionId}`,
        description: 'Elevated output correctness and hallucination suppression through multi-model consensus',
        label: 'PROJECTED',
        dimension: 'QUALITY',
        impact: 'POSITIVE',
        evidenceIds: option.supportingEvidence.map((e) => e.id),
      });
    } else if (option.title.includes('Conservative')) {
      const hasObservedSuccess = context.relevantExperiences.some((e) => e.outcome === 'SUCCESS');
      consequences.push({
        id: `c_qual_${option.optionId}`,
        description: 'Consistent, stable execution quality verified across sequential task executions',
        label: hasObservedSuccess ? 'OBSERVED' : 'INFERRED',
        dimension: 'QUALITY',
        impact: 'POSITIVE',
        evidenceIds: option.supportingEvidence.map((e) => e.id),
      });
    } else {
      consequences.push({
        id: `c_qual_${option.optionId}`,
        description: 'Standard baseline quality across executed tasks',
        label: 'INFERRED',
        dimension: 'QUALITY',
        impact: 'NEUTRAL',
        evidenceIds: [],
      });
    }

    // 2. Cost & Resource Consequence
    if (option.title.includes('Parallel') || option.title.includes('Deep')) {
      consequences.push({
        id: `c_cost_${option.optionId}`,
        description: 'Increased concurrent token consumption and provider bandwidth load',
        label: 'PROJECTED',
        dimension: 'COST',
        impact: 'NEGATIVE',
        evidenceIds: [],
        estimatedMetric: {
          name: 'estimatedCostDelta',
          value: option.estimatedCost !== 'UNKNOWN' ? option.estimatedCost : 'UNKNOWN',
          unit: 'USD',
        },
      });
    } else {
      consequences.push({
        id: `c_cost_${option.optionId}`,
        description: 'Controlled sequential token consumption within standard budget boundaries',
        label: 'INFERRED',
        dimension: 'COST',
        impact: 'POSITIVE',
        evidenceIds: [],
        estimatedMetric: {
          name: 'estimatedCostDelta',
          value: 'UNKNOWN',
          unit: 'USD',
        },
      });
    }

    // 3. Latency / Speed Consequence
    if (option.title.includes('Parallel')) {
      consequences.push({
        id: `c_lat_${option.optionId}`,
        description: 'Significant reduction in critical path duration via concurrent DAG execution',
        label: 'PROJECTED',
        dimension: 'LATENCY',
        impact: 'POSITIVE',
        evidenceIds: [],
      });
    } else if (option.title.includes('Deep')) {
      consequences.push({
        id: `c_lat_${option.optionId}`,
        description: 'Higher total wall-clock latency due to consensus rounds and cross-verification',
        label: 'PROJECTED',
        dimension: 'LATENCY',
        impact: 'NEGATIVE',
        evidenceIds: [],
      });
    } else {
      consequences.push({
        id: `c_lat_${option.optionId}`,
        description: 'Nominal linear execution duration without concurrent acceleration',
        label: 'INFERRED',
        dimension: 'LATENCY',
        impact: 'NEUTRAL',
        evidenceIds: [],
      });
    }

    // 4. Reversibility & Recovery Consequence
    if (option.reversibility === 'IRREVERSIBLE') {
      consequences.push({
        id: `c_rev_${option.optionId}`,
        description: 'Permanent state commitment. Rollback requires manual human remediation',
        label: 'INFERRED',
        dimension: 'RECOVERY',
        impact: 'NEGATIVE',
        evidenceIds: [],
      });
    } else if (option.reversibility === 'PARTIALLY_REVERSIBLE') {
      consequences.push({
        id: `c_rev_${option.optionId}`,
        description: 'Sub-actions can be independently halted or retried; shared artifacts require reconciliation',
        label: 'INFERRED',
        dimension: 'RECOVERY',
        impact: 'NEUTRAL',
        evidenceIds: [],
      });
    } else {
      consequences.push({
        id: `c_rev_${option.optionId}`,
        description: 'Zero lasting state side-effects if cancelled prior to completion checkpoint',
        label: 'OBSERVED',
        dimension: 'RECOVERY',
        impact: 'POSITIVE',
        evidenceIds: [],
      });
    }

    // 5. Unknown Consequence if context is incomplete
    if (context.budget === 'UNKNOWN' || context.deadline === undefined) {
      consequences.push({
        id: `c_unk_${option.optionId}`,
        description: 'Unspecified budget ceiling or deadline makes exact cost/timeline adherence uncertain',
        label: 'UNKNOWN',
        dimension: 'DEADLINE',
        impact: 'UNKNOWN',
        evidenceIds: [],
      });
    }

    return consequences;
  }

  /**
   * Simulates full ScenarioOutcome for an option.
   */
  public simulateOutcome(option: DecisionOption, context: DecisionContext): ScenarioOutcome {
    const consequences = this.simulateConsequences(option, context);

    // Derive risks
    const risks: RiskAssessment[] = [
      ...option.risks,
      ...context.knownRisks.map((kr) => ({
        ...kr,
        classification: kr.classification || ('KNOWN' as const),
      })),
    ];

    // Failure modes
    const failureModes: Array<{
      description: string;
      type: 'EVIDENCE_BACKED' | 'SPECULATIVE';
      evidenceIds: string[];
    }> = [];

    if (context.openContradictions.length > 0) {
      failureModes.push({
        description: `Contradiction in strategic knowledge: ${context.openContradictions[0].description}`,
        type: 'EVIDENCE_BACKED',
        evidenceIds: [context.openContradictions[0].id],
      });
    }

    if (option.reversibility === 'IRREVERSIBLE') {
      failureModes.push({
        description: 'Premature execution without human verification leads to unrecoverable state divergence',
        type: 'SPECULATIVE',
        evidenceIds: [],
      });
    }

    const overallLabel: DecisionEvidenceLabel = consequences.some((c) => c.label === 'UNKNOWN')
      ? 'UNKNOWN'
      : consequences.some((c) => c.label === 'PROJECTED')
      ? 'PROJECTED'
      : 'INFERRED';

    return {
      expectedOutcome: `Execution of option '${option.title}' under current operational context.`,
      consequences,
      risks,
      resourceImpact: `Requires resources: ${option.requiredResources.join(', ')}.`,
      deadlineImpact: context.deadline ? `Target deadline: ${context.deadline}` : 'Deadline: UNKNOWN',
      qualityImplications: option.title.includes('Deep')
        ? 'High fidelity through consensus'
        : 'Standard baseline quality',
      failureModes,
      recoveryImplications:
        option.reversibility === 'REVERSIBLE'
          ? 'Fully recoverable with clean checkpoint rollback'
          : option.reversibility === 'PARTIALLY_REVERSIBLE'
          ? 'Requires selective sub-task replay'
          : 'Irreversible action requires manual human remediation',
      label: overallLabel,
    };
  }
}

export const consequenceSimulator = new ConsequenceSimulator();
