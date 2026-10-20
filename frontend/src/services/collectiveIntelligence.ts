/**
 * AryaOS V1 — Stage 11: Collective Intelligence Service
 *
 * Multi-opinion aggregation, evidence-weighted consensus, and structured
 * disagreement preservation without discarding minority views.
 */

import {
  AgentOpinion,
  CollectiveDecision,
  CollectiveStrategy,
} from '../types/agentEvaluation';
import { evidenceGraph } from './evidenceGraph';

export interface EvaluateConsensusInput {
  goalId: string;
  taskId: string;
  strategy: CollectiveStrategy;
  opinions: AgentOpinion[];
}

export class CollectiveIntelligenceService {
  /**
   * Evaluates multiple agent opinions and forms a structured collective decision
   * preserving minority opinions and evidence chains.
   */
  public evaluateOpinions(input: EvaluateConsensusInput): CollectiveDecision {
    const { goalId, taskId, strategy, opinions } = input;
    const decidedAt = new Date().toISOString();
    const decisionId = `cdec-${Date.now()}-${Math.random().toString(36).substr(2, 6)}`;

    if (!opinions || opinions.length === 0) {
      return {
        decisionId,
        goalId,
        taskId,
        strategy,
        participatingAgents: [],
        opinions: [],
        selectedOutput: '',
        consensusAchieved: false,
        disagreementDetected: false,
        supportingEvidenceIds: [],
        decidedAt,
        status: 'REVIEW_REQUIRED',
      };
    }

    const participatingAgents = opinions.map((o) => o.agentId);

    // Check for disagreement in outputs
    const uniqueOutputs = Array.from(new Set(opinions.map((o) => o.output.trim())));
    const disagreementDetected = uniqueOutputs.length > 1;

    let selectedOutput = opinions[0].output;
    let selectedStructured = opinions[0].structuredOutput;
    let consensusAchieved = !disagreementDetected;
    let status: CollectiveDecision['status'] = 'RESOLVED';
    const supportingEvidenceIds: string[] = [];

    // Collect all supporting evidence
    for (const op of opinions) {
      supportingEvidenceIds.push(...op.evidence);
    }

    switch (strategy) {
      case 'SINGLE_RESULT':
        selectedOutput = opinions[0].output;
        selectedStructured = opinions[0].structuredOutput;
        consensusAchieved = true;
        status = 'RESOLVED';
        break;

      case 'MERGE':
        if (disagreementDetected) {
          selectedOutput = opinions
            .map((o) => `[Agent ${o.agentId}]: ${o.output}`)
            .join('\n\n');
          consensusAchieved = true;
          status = 'RESOLVED';
        } else {
          selectedOutput = opinions[0].output;
          consensusAchieved = true;
          status = 'RESOLVED';
        }
        break;

      case 'CONSENSUS':
        if (disagreementDetected) {
          consensusAchieved = false;
          status = 'REVIEW_REQUIRED';
          // Fall back to first or vote
          const votes: Record<string, number> = {};
          for (const op of opinions) {
            votes[op.output] = (votes[op.output] || 0) + 1;
          }
          let highestVotes = 0;
          for (const [out, count] of Object.entries(votes)) {
            if (count > highestVotes) {
              highestVotes = count;
              selectedOutput = out;
            }
          }
        } else {
          consensusAchieved = true;
          status = 'RESOLVED';
        }
        break;

      case 'EVIDENCE_WEIGHTED_CONSENSUS': {
        // Calculate weight based on confidence and evaluation score if available
        let bestScore = -1;
        let bestOpinion = opinions[0];

        for (const op of opinions) {
          let weight = 1.0;
          if (op.confidence === 'HIGH') weight *= 1.5;
          if (op.confidence === 'LOW') weight *= 0.5;

          if (op.evaluation && typeof op.evaluation.overallScore === 'number') {
            weight *= op.evaluation.overallScore;
          }

          if (weight > bestScore) {
            bestScore = weight;
            bestOpinion = op;
          }
        }

        selectedOutput = bestOpinion.output;
        selectedStructured = bestOpinion.structuredOutput;
        consensusAchieved = !disagreementDetected || opinions.length === 1;
        status = disagreementDetected ? 'RESOLVED' : 'RESOLVED';
        break;
      }

      case 'EXPERT_REVIEW':
        if (disagreementDetected) {
          consensusAchieved = false;
          status = 'REVIEW_REQUIRED';
        } else {
          consensusAchieved = true;
          status = 'RESOLVED';
        }
        break;

      case 'HUMAN_REVIEW':
        if (disagreementDetected) {
          consensusAchieved = false;
          status = 'HUMAN_REVIEW_REQUIRED';
        } else {
          consensusAchieved = true;
          status = 'RESOLVED';
        }
        break;
    }

    const decision: CollectiveDecision = {
      decisionId,
      goalId,
      taskId,
      strategy,
      participatingAgents,
      opinions,
      selectedOutput,
      structuredOutput: selectedStructured,
      consensusAchieved,
      disagreementDetected,
      supportingEvidenceIds: Array.from(new Set(supportingEvidenceIds)),
      decidedAt,
      status,
    };

    // Register evidence in EvidenceGraph
    evidenceGraph.createEvidenceItem(
      'DECISION',
      decisionId,
      `Collective decision (${strategy}) with ${opinions.length} agents. Status: ${status}`,
      'CollectiveIntelligenceService'
    );
    evidenceGraph.linkEntities(taskId, decisionId, 'RESOLVED_BY_DECISION');

    return decision;
  }
}

export const collectiveIntelligence = new CollectiveIntelligenceService();
