/**
 * AryaOS V1 — Stage 14: Decision Option Generator
 *
 * Generates materially diverse, evidence-backed decision options.
 * Detects duplicates deterministically, enforces explicit reversibility,
 * and preserves 'UNKNOWN' rather than fabricating estimates.
 */

import {
  DecisionContext,
  DecisionOption,
  DecisionReversibility,
  DecisionEvidence,
  RiskAssessment,
  DecisionConfidence,
} from '../types/decisionIntelligence';
import { createDeterministicHash } from './decisionContextService';

export interface GenerateOptionsParams {
  context: DecisionContext;
  customOptions?: Array<Partial<DecisionOption>>;
}

export class DecisionOptionGenerator {
  /**
   * Generates materially diverse options for a given DecisionContext.
   */
  public generateOptions(params: GenerateOptionsParams): DecisionOption[] {
    const { context, customOptions = [] } = params;
    const options: DecisionOption[] = [];

    // Helper to calculate option fingerprint for duplicate detection
    const calculateOptionFingerprint = (
      title: string,
      reversibility: DecisionReversibility,
      strategyRefs: string[],
      resources: string[]
    ): string => {
      const sortedStrats = [...strategyRefs].sort().join(',');
      const sortedRes = [...resources].sort().join(',');
      const normalizedTitle = title.toLowerCase().replace(/[^a-z0-9]/g, '');
      return createDeterministicHash(`${normalizedTitle}:${reversibility}:${sortedStrats}:${sortedRes}`);
    };

    // 1. Option A: Conservative / High Reliability (Reversible, low risk)
    const optAStrat = context.historicalStrategies[0]?.id || 'strat_verified_sequential';
    const optAEvidence: DecisionEvidence[] = context.relevantKnowledge.slice(0, 2).map((k) => ({
      id: `ev_${k.id}`,
      label: 'OBSERVED',
      sourceType: 'KNOWLEDGE_NODE',
      sourceId: k.id,
      description: `Observed strategic knowledge: ${k.title}`,
      confidence: (k.confidence as DecisionConfidence) || 'MEDIUM',
      timestamp: new Date().toISOString(),
    }));

    const optA: DecisionOption = {
      optionId: `opt_conservative_${createDeterministicHash(context.contextId + '_a').slice(3, 9)}`,
      title: 'Conservative Sequential Execution',
      description: 'Execute actions sequentially with strict validation gates and checkpoints to minimize risk.',
      reversibility: 'REVERSIBLE',
      requiredGoals: context.goalId ? [context.goalId] : ['goal_verified_sequence'],
      requiredResources: ['WORKER_AGENT', 'EXECUTION_GATEWAY'],
      strategyReferences: [optAStrat],
      supportingEvidence: optAEvidence,
      assumptions: ['Sequential validation reduces risk of cascading failure'],
      risks: context.knownRisks.slice(0, 1),
      estimatedCost: 'UNKNOWN', // Never fabricate unknown costs
      estimatedDuration: 'UNKNOWN',
      confidence: 'HIGH',
    };
    optA.fingerprint = calculateOptionFingerprint(optA.title, optA.reversibility, optA.strategyReferences, optA.requiredResources);
    options.push(optA);

    // 2. Option B: High-Throughput Parallel Execution (Partially reversible, optimizes speed/latency)
    const optBStrat = context.historicalStrategies[1]?.id || 'strat_parallel_dispatch';
    const optBEvidence: DecisionEvidence[] = context.relevantExperiences.slice(0, 2).map((e) => ({
      id: `ev_${e.id}`,
      label: 'INFERRED',
      sourceType: 'EXPERIENCE',
      sourceId: e.id,
      description: `Inferred from historical task experience (${e.pattern} -> ${e.outcome})`,
      confidence: 'MEDIUM',
      timestamp: new Date().toISOString(),
    }));

    const optB: DecisionOption = {
      optionId: `opt_parallel_${createDeterministicHash(context.contextId + '_b').slice(3, 9)}`,
      title: 'Parallel Multi-Agent Acceleration',
      description: 'Dispatch independent sub-tasks concurrently across multiple agents to minimize completion latency.',
      reversibility: 'PARTIALLY_REVERSIBLE',
      requiredGoals: context.goalId ? [context.goalId] : ['goal_parallel_dispatch'],
      requiredResources: ['WORKER_AGENT', 'COORDINATOR_AGENT', 'EXECUTION_GATEWAY'],
      strategyReferences: [optBStrat],
      supportingEvidence: optBEvidence,
      assumptions: ['Sub-tasks are sufficiently decoupled for parallel worker execution'],
      risks: [
        ...context.knownRisks.slice(0, 2),
        {
          id: 'risk_resource_contention',
          classification: 'INFERRED',
          title: 'Potential Resource Contention',
          description: 'High concurrency may stress provider rate limits or token budgets',
          severity: 'MEDIUM',
          likelihood: 'MEDIUM',
          evidenceIds: [],
        },
      ],
      estimatedCost: 'UNKNOWN',
      estimatedDuration: 'UNKNOWN',
      confidence: 'MEDIUM',
    };
    optB.fingerprint = calculateOptionFingerprint(optB.title, optB.reversibility, optB.strategyReferences, optB.requiredResources);
    options.push(optB);

    // 3. Option C: Deep Synthesis / Maximum Quality (Irreversible if external publishing is required)
    const optC: DecisionOption = {
      optionId: `opt_deep_${createDeterministicHash(context.contextId + '_c').slice(3, 9)}`,
      title: 'Deep Multi-Perspective Synthesis',
      description: 'Perform exhaustive cross-agent verification, debate, and multi-model consensus before final output.',
      reversibility: 'IRREVERSIBLE', // High impact, consequential
      requiredGoals: context.goalId ? [context.goalId] : ['goal_deep_synthesis'],
      requiredResources: ['WORKER_AGENT', 'COORDINATOR_AGENT', 'EXECUTION_GATEWAY', 'SPATIAL_CONSOLE'],
      strategyReferences: ['strat_multi_agent_consensus'],
      supportingEvidence: optAEvidence,
      assumptions: ['Higher cognitive deliberation yields superior fidelity and fewer hallucinations'],
      risks: [
        {
          id: 'risk_cost_overrun',
          classification: 'PROJECTED',
          title: 'Increased Token Consumption',
          description: 'Multi-perspective deliberation consumes significantly more provider tokens',
          severity: 'HIGH',
          likelihood: 'HIGH',
          evidenceIds: [],
        },
      ],
      estimatedCost: 'UNKNOWN',
      estimatedDuration: 'UNKNOWN',
      confidence: 'MEDIUM',
    };
    optC.fingerprint = calculateOptionFingerprint(optC.title, optC.reversibility, optC.strategyReferences, optC.requiredResources);
    options.push(optC);

    // 4. Incorporate and deduplicate any custom caller options
    for (const custom of customOptions) {
      if (!custom.title || !custom.description) continue;
      const reversibility: DecisionReversibility = custom.reversibility || 'REVERSIBLE';
      const stratRefs = custom.strategyReferences || [];
      const resources = custom.requiredResources || ['WORKER_AGENT'];
      const fp = calculateOptionFingerprint(custom.title, reversibility, stratRefs, resources);

      // Check if duplicate already exists
      const isDuplicate = options.some((existing) => existing.fingerprint === fp);
      if (!isDuplicate) {
        const optionId = custom.optionId || `opt_custom_${createDeterministicHash(fp).slice(3, 9)}`;
        options.push({
          optionId,
          title: custom.title,
          description: custom.description,
          reversibility,
          requiredGoals: custom.requiredGoals || [],
          requiredResources: resources,
          strategyReferences: stratRefs,
          supportingEvidence: custom.supportingEvidence || [],
          assumptions: custom.assumptions || [],
          risks: custom.risks || [],
          estimatedCost: custom.estimatedCost !== undefined ? custom.estimatedCost : 'UNKNOWN',
          estimatedDuration: custom.estimatedDuration !== undefined ? custom.estimatedDuration : 'UNKNOWN',
          confidence: custom.confidence || 'MEDIUM',
          fingerprint: fp,
        });
      }
    }

    return options;
  }

  /**
   * Deterministic duplicate option detector.
   */
  public isDuplicateOption(optA: DecisionOption, optB: DecisionOption): boolean {
    if (optA.fingerprint && optB.fingerprint && optA.fingerprint === optB.fingerprint) {
      return true;
    }
    const normA = optA.title.toLowerCase().replace(/[^a-z0-9]/g, '');
    const normB = optB.title.toLowerCase().replace(/[^a-z0-9]/g, '');
    return normA === normB && optA.reversibility === optB.reversibility;
  }
}

export const decisionOptionGenerator = new DecisionOptionGenerator();
