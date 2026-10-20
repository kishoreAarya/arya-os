/**
 * AryaOS V1 — Stage 13: Strategic Decision Context & Ranking Service
 *
 * Assembles bounded, prioritized strategic context for Goals and Missions.
 * Provides multi-dimensional, transparent, explainable ranking scores.
 * Enforces human review when strategic risks or policy boundaries are detected.
 */

import {
  KnowledgeContext,
  KnowledgeDecisionContext,
  KnowledgeFact,
  KnowledgeStrategy,
  KnowledgeContradiction,
  RankedKnowledgeFact,
  ContextRankingExplanation,
} from '../types/strategicKnowledge';
import { executionPersistence } from './executionPersistence';

export class StrategicContextService {
  /**
   * Weights for context ranking dimensions
   */
  private readonly RANKING_WEIGHTS = {
    semanticRelevance: 0.25,
    taskSimilarity: 0.25,
    recency: 0.15,
    confidenceWeight: 0.15,
    outcomeRelevance: 0.10,
    missionSimilarity: 0.10,
  };

  /**
   * Computes an explainable score for a fact given task and mission contexts.
   */
  public rankFact(
    fact: KnowledgeFact,
    taskType?: string,
    missionContext?: string
  ): { score: number; explanation: ContextRankingExplanation } {
    // 1. Semantic Relevance
    let semanticRelevance = 0.5;
    if (taskType && (fact.subject.toLowerCase().includes(taskType.toLowerCase()) || fact.object.toLowerCase().includes(taskType.toLowerCase()))) {
      semanticRelevance = 1.0;
    } else if (missionContext && fact.subject.toLowerCase().includes(missionContext.toLowerCase())) {
      semanticRelevance = 0.8;
    }

    // 2. Task Similarity
    let taskSimilarity = 0.5;
    if (taskType && fact.predicate.toLowerCase().includes(taskType.toLowerCase())) {
      taskSimilarity = 0.9;
    } else if (fact.metadata && fact.metadata.taskType === taskType) {
      taskSimilarity = 1.0;
    }

    // 3. Recency (exponential decay based on observation time)
    const observedMs = new Date(fact.observedAt).getTime();
    const ageDays = Math.max(0, (Date.now() - observedMs) / (1000 * 60 * 60 * 24));
    const recency = Math.pow(2, -ageDays / 60);

    // 4. Confidence Weight
    const confidenceMap: Record<string, number> = {
      HIGH: 1.0,
      MEDIUM: 0.7,
      LOW: 0.35,
      UNKNOWN: 0.1,
    };
    const confidenceWeight = confidenceMap[fact.confidence] ?? 0.5;

    // 5. Outcome Relevance
    let outcomeRelevance = 0.5;
    if (fact.validity === 'ACTIVE' && fact.status === 'VERIFIED') {
      outcomeRelevance = 1.0;
    } else if (fact.validity === 'DISPUTED' || fact.status === 'UNCERTAIN') {
      outcomeRelevance = 0.3;
    }

    // 6. Mission Similarity
    let missionSimilarity = 0.5;
    if (missionContext && fact.provenance.missionId === missionContext) {
      missionSimilarity = 1.0;
    }

    // Composite Score [0, 100]
    const compositeFraction =
      semanticRelevance * this.RANKING_WEIGHTS.semanticRelevance +
      taskSimilarity * this.RANKING_WEIGHTS.taskSimilarity +
      recency * this.RANKING_WEIGHTS.recency +
      confidenceWeight * this.RANKING_WEIGHTS.confidenceWeight +
      outcomeRelevance * this.RANKING_WEIGHTS.outcomeRelevance +
      missionSimilarity * this.RANKING_WEIGHTS.missionSimilarity;

    const finalScore = Number((compositeFraction * 100).toFixed(1));

    const explanation: ContextRankingExplanation = {
      semanticRelevance: Number(semanticRelevance.toFixed(2)),
      taskSimilarity: Number(taskSimilarity.toFixed(2)),
      recency: Number(recency.toFixed(2)),
      confidenceWeight: Number(confidenceWeight.toFixed(2)),
      outcomeRelevance: Number(outcomeRelevance.toFixed(2)),
      missionSimilarity: Number(missionSimilarity.toFixed(2)),
      finalScore,
      rationale: `Composite score: ${finalScore}/100 [Semantic: ${(semanticRelevance * 100).toFixed(0)}%, Task: ${(taskSimilarity * 100).toFixed(0)}%, Recency: ${(recency * 100).toFixed(0)}%, Confidence: ${(confidenceWeight * 100).toFixed(0)}%]`,
    };

    return { score: finalScore, explanation };
  }

  /**
   * Assembles a bounded, ranked KnowledgeContext for a Goal or Mission.
   */
  public assembleContext(params: {
    querySubject: string;
    taskType?: string;
    missionId?: string;
    limitFacts?: number;
    availableFacts?: KnowledgeFact[];
    availableStrategies?: KnowledgeStrategy[];
    availableContradictions?: KnowledgeContradiction[];
  }): KnowledgeContext {
    const {
      querySubject,
      taskType,
      missionId,
      limitFacts = 6, // Strict bounding: never dumps unbounded graph
      availableFacts = executionPersistence.getKnowledgeFacts(),
      availableStrategies = executionPersistence.getKnowledgeStrategies(),
      availableContradictions = executionPersistence.getKnowledgeContradictions(),
    } = params;

    // Filter and rank facts
    const rankedFacts: RankedKnowledgeFact[] = availableFacts
      .filter((f) => f.validity !== 'OBSOLETE')
      .map((fact) => {
        const { score, explanation } = this.rankFact(fact, taskType, missionId);
        return { fact, score, explanation };
      })
      .sort((a, b) => b.score - a.score)
      .slice(0, limitFacts);

    // Filter relevant strategies (VALIDATED or CANDIDATE)
    const strategies = availableStrategies
      .filter(
        (s) =>
          s.status !== 'DEPRECATED' &&
          s.status !== 'REJECTED' &&
          (!taskType || s.applicableTaskTypes.includes(taskType) || s.applicableTaskTypes.includes('*'))
      )
      .slice(0, 4);

    // Filter active contradictions concerning this subject or returned facts
    const relevantFactIds = new Set(rankedFacts.map((rf) => rf.fact.id));
    const contradictions = availableContradictions.filter(
      (c) =>
        (c.resolutionStatus === 'OPEN' || c.resolutionStatus === 'UNDER_REVIEW') &&
        (relevantFactIds.has(c.factA) || relevantFactIds.has(c.factB))
    );

    const summary = `Assembled bounded strategic context for '${querySubject}': ${rankedFacts.length} ranked facts, ${strategies.length} strategies, ${contradictions.length} open contradictions.`;

    return {
      querySubject,
      memories: [],
      experiences: [],
      historicalMissions: [],
      strategies,
      risks: [],
      contradictions,
      learningSignals: [],
      agentProviderEvidence: [],
      rankedFacts,
      generatedAt: new Date().toISOString(),
      summary,
    };
  }

  /**
   * Constructs Decision Context with human governance gating checks.
   */
  public createDecisionContext(params: {
    targetGoalId?: string;
    targetMissionId?: string;
    taskType?: string;
    querySubject: string;
  }): KnowledgeDecisionContext {
    const strategicContext = this.assembleContext({
      querySubject: params.querySubject,
      taskType: params.taskType,
      missionId: params.targetMissionId,
    });

    const governanceReasons: string[] = [];

    // Governance Rule 1: Open Critical Contradictions require human review
    const criticalContradictions = strategicContext.contradictions.filter((c) => c.severity === 'CRITICAL');
    if (criticalContradictions.length > 0) {
      governanceReasons.push(`Open CRITICAL contradiction detected affecting decision facts (${criticalContradictions.length} found).`);
    }

    // Governance Rule 2: Strategies with known risks or constraints
    const highRiskStrategies = strategicContext.strategies.filter((s) => s.knownRisks.length > 2);
    if (highRiskStrategies.length > 0) {
      governanceReasons.push(`Referenced strategy has elevated known risks requiring human review.`);
    }

    const requiresHumanReview = governanceReasons.length > 0;

    return {
      contextId: `dctx:${Date.now()}-${Math.random().toString(36).substring(2, 7)}`,
      targetGoalId: params.targetGoalId,
      targetMissionId: params.targetMissionId,
      strategicContext,
      governanceThresholdExceeded: requiresHumanReview,
      requiresHumanReview,
      governanceReasons,
      createdAt: new Date().toISOString(),
    };
  }
}

export const strategicContextService = new StrategicContextService();
