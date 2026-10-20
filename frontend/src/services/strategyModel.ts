/**
 * AryaOS V1 — Stage 13: Strategy Model & Repository Service
 *
 * Models reusable, evidence-backed strategic approaches.
 * Invariant: A Strategy is NOT an executable workflow and never executes
 * automatically. It serves as advisory guidance and pattern-informed wisdom.
 */

import {
  KnowledgeStrategy,
  StrategyStatus,
  KnowledgeConfidence,
  KnowledgeProvenance,
} from '../types/strategicKnowledge';

export class StrategyModelService {
  private strategies: Map<string, KnowledgeStrategy> = new Map();

  /**
   * Creates a new CANDIDATE strategy.
   * Strategies start as CANDIDATE and require verified evidence before promotion to VALIDATED.
   */
  public createCandidateStrategy(params: {
    strategyId?: string;
    title: string;
    description: string;
    applicableTaskTypes: string[];
    supportingEvidence?: string[];
    observedOutcomes?: string[];
    confidence?: KnowledgeConfidence;
    knownRisks?: string[];
    constraints?: string[];
    provenance: KnowledgeProvenance;
  }): KnowledgeStrategy {
    const {
      strategyId = `strat:${Date.now()}-${Math.random().toString(36).substring(2, 7)}`,
      title,
      description,
      applicableTaskTypes,
      supportingEvidence = [],
      observedOutcomes = [],
      confidence = supportingEvidence.length >= 2 ? 'MEDIUM' : 'LOW',
      knownRisks = [],
      constraints = [],
      provenance,
    } = params;

    const strategy: KnowledgeStrategy = {
      strategyId,
      title,
      description,
      applicableTaskTypes,
      supportingEvidence,
      observedOutcomes,
      confidence,
      knownRisks,
      constraints,
      status: 'CANDIDATE',
      createdAt: new Date().toISOString(),
      updatedAt: new Date().toISOString(),
      provenance,
    };

    this.strategies.set(strategyId, strategy);
    return strategy;
  }

  /**
   * Promotes a CANDIDATE strategy to VALIDATED if sufficient empirical evidence exists.
   */
  public validateStrategy(strategyId: string, additionalEvidence: string[] = []): KnowledgeStrategy {
    const strategy = this.strategies.get(strategyId);
    if (!strategy) {
      throw new Error(`Strategy '${strategyId}' not found.`);
    }

    if (strategy.status === 'REJECTED') {
      throw new Error(`Cannot validate rejected strategy '${strategyId}'.`);
    }

    const mergedEvidence = Array.from(new Set([...strategy.supportingEvidence, ...additionalEvidence]));
    if (mergedEvidence.length < 2) {
      throw new Error(`Strategy requires at least 2 distinct pieces of supporting evidence to be VALIDATED.`);
    }

    strategy.supportingEvidence = mergedEvidence;
    strategy.status = 'VALIDATED';
    strategy.confidence = mergedEvidence.length >= 3 ? 'HIGH' : 'MEDIUM';
    strategy.validatedAt = new Date().toISOString();
    strategy.updatedAt = new Date().toISOString();

    this.strategies.set(strategyId, strategy);
    return strategy;
  }

  /**
   * Deprecates a strategy when superseding evidence or patterns emerge.
   */
  public deprecateStrategy(strategyId: string, reason: string): KnowledgeStrategy {
    const strategy = this.strategies.get(strategyId);
    if (!strategy) {
      throw new Error(`Strategy '${strategyId}' not found.`);
    }

    strategy.status = 'DEPRECATED';
    strategy.deprecatedAt = new Date().toISOString();
    strategy.updatedAt = new Date().toISOString();
    strategy.constraints.push(`DEPRECATED: ${reason}`);

    this.strategies.set(strategyId, strategy);
    return strategy;
  }

  /**
   * Rejects a candidate strategy if evidence disproves it or operator disallows it.
   */
  public rejectStrategy(strategyId: string, reason: string): KnowledgeStrategy {
    const strategy = this.strategies.get(strategyId);
    if (!strategy) {
      throw new Error(`Strategy '${strategyId}' not found.`);
    }

    strategy.status = 'REJECTED';
    strategy.updatedAt = new Date().toISOString();
    strategy.knownRisks.push(`REJECTED_REASON: ${reason}`);

    this.strategies.set(strategyId, strategy);
    return strategy;
  }

  /**
   * Retrieves strategies applicable to a task type.
   */
  public getStrategiesForTaskType(taskType: string, status?: StrategyStatus): KnowledgeStrategy[] {
    const matches: KnowledgeStrategy[] = [];
    for (const strat of this.strategies.values()) {
      if (status && strat.status !== status) continue;
      if (
        strat.applicableTaskTypes.includes(taskType) ||
        strat.applicableTaskTypes.includes('*')
      ) {
        matches.push(strat);
      }
    }
    return matches;
  }

  /**
   * Retrieves a strategy by ID.
   */
  public getStrategy(id: string): KnowledgeStrategy | null {
    return this.strategies.get(id) || null;
  }

  /**
   * Retrieves all strategies.
   */
  public getAllStrategies(status?: StrategyStatus): KnowledgeStrategy[] {
    const all = Array.from(this.strategies.values());
    if (!status) return all;
    return all.filter((s) => s.status === status);
  }

  /**
   * Saves strategy directly.
   */
  public saveStrategy(strat: KnowledgeStrategy): void {
    this.strategies.set(strat.strategyId, strat);
  }

  /**
   * Clears strategies in memory.
   */
  public clear(): void {
    this.strategies.clear();
  }
}

export const strategyModelService = new StrategyModelService();
