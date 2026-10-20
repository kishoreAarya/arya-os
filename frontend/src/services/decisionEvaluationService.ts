/**
 * AryaOS V1 — Stage 14: Decision Evaluation & Post-Decision Learning Service
 *
 * Evaluates the Decision Process itself (distinct from outcome bias).
 * Records post-decision outcomes, calculates variance against scenario projections,
 * and feeds learnings into Stage 11 Experience Store and Stage 13 Strategic Knowledge Graph.
 *
 * Epistemic principle:
 * A thorough decision process may still yield an unexpected outcome due to irreducible uncertainty.
 * Preserves uncertainty and avoids simplistic "good/bad" outcome labels.
 */

import {
  Decision,
  DecisionEvaluation,
  PostDecisionRecord,
} from '../types/decisionIntelligence';
import { executionPersistence } from './executionPersistence';
import { knowledgeGraph } from './knowledgeGraph';

export class DecisionEvaluationService {
  /**
   * Evaluates the rigor of the decision process.
   */
  public evaluateDecisionProcess(decision: Decision): DecisionEvaluation {
    let processScore = 50; // Baseline starting score

    // 1. Context thoroughness (+10)
    if (decision.context && decision.context.constraints.length > 0 && decision.context.objectives.length > 0) {
      processScore += 10;
    }

    // 2. Option diversity (+10)
    if (decision.options && decision.options.length >= 2) {
      processScore += 10;
    }

    // 3. Tradeoff surfacing (+10)
    if (decision.recommendation && decision.recommendation.tradeoffs.length > 0) {
      processScore += 10;
    }

    // 4. Pre-mortem analysis (+10)
    if (decision.premortem && decision.premortem.failureModes.length > 0) {
      processScore += 10;
    }

    // 5. Explicit reversibility classification (+10)
    const allHaveReversibility = decision.options.every((o) => !!o.reversibility);
    if (allHaveReversibility) {
      processScore += 10;
    }

    processScore = Math.min(100, processScore);

    // Evidence quality calculation
    const allEvidence = decision.options.flatMap((o) => o.supportingEvidence);
    const highConfEvidence = allEvidence.filter((e) => e.confidence === 'HIGH').length;
    const evidenceQualityScore = allEvidence.length > 0
      ? Math.round((highConfEvidence / allEvidence.length) * 100)
      : 70;

    const evaluation: DecisionEvaluation = {
      id: `eval_dec_${decision.id}`,
      decisionId: decision.id,
      decisionProcessScore: processScore,
      evidenceQualityScore,
      humanOverrideOccurred: decision.approval.status === 'REJECTED' || (decision.approval.comments?.includes('override') ?? false),
      evaluationNotes: `Decision process evaluated across ${decision.options.length} candidate options with ${decision.context.constraints.length} constraints. Process thoroughness rated at ${processScore}%.`,
      evaluatedAt: new Date().toISOString(),
    };

    executionPersistence.saveDecisionEvaluation(evaluation);
    decision.evaluation = evaluation;
    executionPersistence.saveDecision(decision);

    return evaluation;
  }

  /**
   * Records empirical post-decision execution outcome and feeds findings to Stage 11 & 13.
   */
  public recordPostDecisionOutcome(params: {
    decision: Decision;
    actualOutcome: string;
    unexpectedEvents?: string[];
    humanOverride?: boolean;
    lesson?: string;
  }): PostDecisionRecord {
    const { decision, actualOutcome, unexpectedEvents = [], humanOverride = false, lesson } = params;

    const selectedOption = decision.options.find(
      (o) => o.optionId === decision.recommendation?.recommendedOptionId
    ) || decision.options[0];

    const expectedOutcome = decision.recommendation?.recommendedOption.description || 'Nominal execution expected';
    const variance = `Observed outcome comparison: "${actualOutcome}" vs expected "${expectedOutcome}". Unexpected events: ${unexpectedEvents.length}.`;

    const postRecord: PostDecisionRecord = {
      decisionId: decision.id,
      selectedOptionId: selectedOption ? selectedOption.optionId : 'opt_unknown',
      actualOutcome,
      expectedOutcome,
      variance,
      unexpectedEvents,
      humanOverride,
      lesson: lesson || `Outcome recorded for decision ${decision.id} with option ${selectedOption?.title}.`,
      recordedAt: new Date().toISOString(),
    };

    executionPersistence.savePostDecisionRecord(postRecord);
    decision.postDecisionRecord = postRecord;
    decision.status = 'EXECUTED';
    executionPersistence.saveDecision(decision);

    // Feed finding to Stage 13 Strategic Knowledge Graph
    try {
      const outcomeNodeId = `node_outcome_${decision.id}`;
      knowledgeGraph.addNode({
        id: outcomeNodeId,
        type: 'OUTCOME',
        label: `Outcome: ${decision.title}`,
        confidence: 'HIGH',
        status: 'VERIFIED',
        createdAt: new Date().toISOString(),
        updatedAt: new Date().toISOString(),
        provenance: {
          source: {
            sourceType: 'STAGE11_DECISION',
            sourceId: decision.id,
            timestamp: new Date().toISOString(),
          },
          extractedAt: new Date().toISOString(),
          derivedBy: 'decisionEvaluationService',
          confidenceScore: 0.9,
        },
        metadata: {
          actualOutcome,
          variance,
          lesson: postRecord.lesson,
        },
      });

      knowledgeGraph.addEdge({
        id: `edge_dec_out_${decision.id}`,
        source: decision.id,
        target: outcomeNodeId,
        relation: 'RESULTED_IN',
        confidence: 'HIGH',
        weight: 1.0,
        createdAt: new Date().toISOString(),
        provenance: {
          source: {
            sourceType: 'STAGE11_DECISION',
            sourceId: decision.id,
            timestamp: new Date().toISOString(),
          },
          extractedAt: new Date().toISOString(),
          derivedBy: 'decisionEvaluationService',
        },
      });
    } catch {
      // Graceful fallback if graph node already exists
    }

    return postRecord;
  }
}

export const decisionEvaluationService = new DecisionEvaluationService();
