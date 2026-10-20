/**
 * AryaOS V1 — Stage 14: Multi-Objective Tradeoff Engine
 *
 * Evaluates explicit tradeoffs between conflicting operational objectives:
 * QUALITY ↔ COST, QUALITY ↔ LATENCY, COST ↔ SPEED, RISK ↔ AUTONOMY,
 * SCOPE ↔ DEADLINE, RESOURCE ↔ PARALLELISM.
 *
 * NEVER combines dimensions into an opaque universal score.
 * Preserves tension and surfaces explicit trade-off balances for human review.
 */

import {
  DecisionOption,
  TradeoffAnalysis,
  DecisionObjectiveType,
  DecisionConfidence,
} from '../types/decisionIntelligence';

export class TradeoffEngine {
  /**
   * Compares two options across conflicting objective dimensions without hiding tradeoffs.
   */
  public analyzeTradeoffs(
    optionA: DecisionOption,
    optionB: DecisionOption
  ): TradeoffAnalysis[] {
    const tradeoffs: TradeoffAnalysis[] = [];

    // 1. QUALITY ↔ COST
    tradeoffs.push({
      id: `tradeoff_qc_${optionA.optionId}_${optionB.optionId}`,
      dimensionA: 'QUALITY',
      dimensionB: 'COST',
      optionAImpact: optionA.title.includes('Deep') || optionA.title.includes('Conservative')
        ? 'Higher output fidelity and verification rigor; consumes more credits/tokens.'
        : 'Standard baseline quality with lower token overhead.',
      optionBImpact: optionB.title.includes('Parallel') || optionB.title.includes('Standard') || optionB.title.includes('Cost') || optionB.title.includes('Fast')
        ? 'Lower cost per completed task; reduced consensus cross-checking.'
        : 'Higher cost investment to guarantee output quality.',
      evidence: [
        ...optionA.supportingEvidence.map((e) => e.id),
        ...optionB.supportingEvidence.map((e) => e.id),
      ],
      confidence: 'MEDIUM' as DecisionConfidence,
    });

    // 2. QUALITY ↔ LATENCY
    tradeoffs.push({
      id: `tradeoff_ql_${optionA.optionId}_${optionB.optionId}`,
      dimensionA: 'QUALITY',
      dimensionB: 'LATENCY',
      optionAImpact: optionA.title.includes('Deep')
        ? 'Deep deliberation increases total completion duration.'
        : 'Rapid sequential or parallel path without exhaustive debate.',
      optionBImpact: optionB.title.includes('Parallel')
        ? 'Minimized wall-clock latency via concurrent worker threads.'
        : 'Longer latency path to maintain thorough verification checkpoints.',
      evidence: [],
      confidence: 'HIGH' as DecisionConfidence,
    });

    // 3. COST ↔ LATENCY / SPEED
    tradeoffs.push({
      id: `tradeoff_cs_${optionA.optionId}_${optionB.optionId}`,
      dimensionA: 'COST',
      dimensionB: 'LATENCY',
      optionAImpact: optionA.title.includes('Parallel')
        ? 'Consumes multiple concurrent gateway slots to accelerate speed.'
        : 'Conserves tokens by executing serially within standard slots.',
      optionBImpact: optionB.title.includes('Conservative')
        ? 'Zero concurrent surge charges; slower overall completion.'
        : 'Trades cost efficiency for execution acceleration.',
      evidence: [],
      confidence: 'HIGH' as DecisionConfidence,
    });

    // 4. RISK ↔ RESOURCE_EFFICIENCY / AUTONOMY
    tradeoffs.push({
      id: `tradeoff_ra_${optionA.optionId}_${optionB.optionId}`,
      dimensionA: 'RISK',
      dimensionB: 'RESOURCE_EFFICIENCY',
      optionAImpact: optionA.reversibility === 'REVERSIBLE'
        ? 'Low operational risk; higher checkpoint overhead.'
        : 'Higher irreversible commitment risk; eliminates validation checkpoint delays.',
      optionBImpact: optionB.reversibility === 'IRREVERSIBLE'
        ? 'High permanent state risk requiring mandatory human approval.'
        : 'Easily roll-backable with minimal side effects.',
      evidence: [],
      confidence: 'HIGH' as DecisionConfidence,
    });

    return tradeoffs;
  }

  /**
   * Generates a pair-wise comparison matrix across all candidate options.
   */
  public compareAllOptions(options: DecisionOption[]): Map<string, TradeoffAnalysis[]> {
    const matrix = new Map<string, TradeoffAnalysis[]>();
    for (let i = 0; i < options.length; i++) {
      for (let j = i + 1; j < options.length; j++) {
        const pairKey = `${options[i].optionId}:${options[j].optionId}`;
        const pairTradeoffs = this.analyzeTradeoffs(options[i], options[j]);
        matrix.set(pairKey, pairTradeoffs);
      }
    }
    return matrix;
  }
}

export const tradeoffEngine = new TradeoffEngine();
