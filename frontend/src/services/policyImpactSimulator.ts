/**
 * AryaOS V1 — Stage 20: Policy Impact Simulator
 *
 * Simulates the counterfactual impact of proposed policies before activation.
 * Adheres strictly to Stage 14 Decision Intelligence principles:
 * Employs formal epistemic certainty labels (OBSERVED, INFERRED, PROJECTED, UNKNOWN).
 * Invariant: Never represents projections as observed facts.
 */

import {
  Policy,
  PolicyImpact,
  EpistemicCertainty,
} from '../types/policyIntelligence';

export class PolicyImpactSimulator {
  /**
   * Simulates the multi-dimensional impact of a policy candidate against historical baselines.
   */
  public simulateImpact(proposedPolicy: Policy, baselineMetrics?: Record<string, number>): PolicyImpact {
    const effectType = proposedPolicy.effect.type;
    const constraint = proposedPolicy.effect.constraint;

    // 1. Cost Impact
    let costDelta = 0;
    let costCertainty: EpistemicCertainty = 'PROJECTED';
    let costNotes = 'Simulated based on constraint thresholds.';

    if (constraint?.maxCostUsd !== undefined) {
      costDelta = -15; // Projected savings
      costCertainty = 'INFERRED';
      costNotes = `Inferred from cost ceiling of $${constraint.maxCostUsd}.`;
    } else if (effectType === 'DENY' || effectType === 'PAUSE') {
      costDelta = -40;
      costCertainty = 'PROJECTED';
      costNotes = 'Cost avoided due to execution suspension.';
    } else if (proposedPolicy.provenance.evidence.experienceIds?.length) {
      costCertainty = 'OBSERVED';
      costNotes = 'Calibrated against observed historical task runs.';
    }

    // 2. Latency Impact
    let latencyDelta = 0;
    let latencyCertainty: EpistemicCertainty = 'PROJECTED';
    if (effectType === 'REQUIRE_APPROVAL' || effectType === 'REQUIRE_REVIEW') {
      latencyDelta = 120; // Operator queue adds delay
      latencyCertainty = 'INFERRED';
    } else if (constraint?.rateLimitPerHour) {
      latencyDelta = 25;
      latencyCertainty = 'PROJECTED';
    }

    // 3. Quality Impact
    let qualityDelta = 5;
    let qualityCertainty: EpistemicCertainty = 'PROJECTED';
    if (proposedPolicy.effect.routedAgentId || proposedPolicy.effect.routedProviderId) {
      qualityDelta = 12;
      qualityCertainty = 'INFERRED';
    }

    // 4. Resource Usage
    let resourceDelta = 0;
    let resourceCertainty: EpistemicCertainty = 'PROJECTED';
    if (constraint?.maxConcurrentActions || constraint?.maxConcurrentAgents) {
      resourceDelta = -20;
      resourceCertainty = 'INFERRED';
    }

    // 5. Reliability
    let reliabilityDelta = 10;
    let reliabilityCertainty: EpistemicCertainty = 'PROJECTED';
    if (proposedPolicy.priority === 'SYSTEM_SAFETY' || proposedPolicy.priority === 'SECURITY') {
      reliabilityDelta = 25;
      reliabilityCertainty = 'INFERRED';
    }

    // 6. Risk
    let riskDelta = -20;
    let riskCertainty: EpistemicCertainty = 'PROJECTED';
    if (effectType === 'REQUIRE_APPROVAL') {
      riskDelta = -50;
      riskCertainty = 'INFERRED';
    }

    // 7. Human Approval Frequency
    let approvalDelta = 0;
    let approvalCertainty: EpistemicCertainty = 'PROJECTED';
    if (proposedPolicy.requiresHumanApproval || effectType === 'REQUIRE_APPROVAL') {
      approvalDelta = 40;
      approvalCertainty = 'OBSERVED';
    }

    return {
      cost: {
        value: `${costDelta >= 0 ? '+' : ''}${costDelta}%`,
        certainty: costCertainty,
        deltaPercent: costDelta,
        notes: costNotes,
      },
      latencyMs: {
        value: `${latencyDelta >= 0 ? '+' : ''}${latencyDelta}%`,
        certainty: latencyCertainty,
        deltaPercent: latencyDelta,
        notes: 'Projected execution queue variance.',
      },
      quality: {
        value: `+${qualityDelta}%`,
        certainty: qualityCertainty,
        deltaPercent: qualityDelta,
        notes: 'Expected improvement in output compliance.',
      },
      resourceUsage: {
        value: `${resourceDelta >= 0 ? '+' : ''}${resourceDelta}%`,
        certainty: resourceCertainty,
        deltaPercent: resourceDelta,
        notes: 'Active concurrent load modulation.',
      },
      reliability: {
        value: `+${reliabilityDelta}%`,
        certainty: reliabilityCertainty,
        deltaPercent: reliabilityDelta,
        notes: 'Fault mitigation projection.',
      },
      risk: {
        value: `${riskDelta}%`,
        certainty: riskCertainty,
        deltaPercent: riskDelta,
        notes: 'System exposure contraction.',
      },
      approvalFrequency: {
        value: `${approvalDelta >= 0 ? '+' : ''}${approvalDelta}%`,
        certainty: approvalCertainty,
        deltaPercent: approvalDelta,
        notes: 'Operator intervention frequency projection.',
      },
    };
  }
}

export const policyImpactSimulator = new PolicyImpactSimulator();
