/**
 * AryaOS V1 — Stage 14: Historical Analogy Retrieval Service
 *
 * Retrieves historical missions, goals, and decisions resembling the current context.
 * Compares objectives, constraints, strategies, resources, and empirical outcomes.
 *
 * Epistemic principle:
 * Never claims "This will succeed."
 * Explicitly states: "Previous mission X shares these characteristics and produced outcome Y."
 */

import {
  DecisionContext,
  HistoricalAnalog,
  DecisionConfidence,
} from '../types/decisionIntelligence';
import { executionPersistence } from './executionPersistence';

export class HistoricalDecisionService {
  /**
   * Retrieves relevant historical analogs from past persisted missions, goals, and decisions.
   */
  public findHistoricalAnalogs(context: DecisionContext): HistoricalAnalog[] {
    const analogs: HistoricalAnalog[] = [];

    // 1. Inspect persisted missions
    const envelope = executionPersistence.loadEnvelope();
    const missions = envelope?.missions ? Object.values(envelope.missions) : [];

    for (const mission of missions) {
      if (mission.missionId === context.missionId) continue; // Skip self

      const similarityFactors: string[] = [];
      const differences: string[] = [];

      // Check objective similarity
      const missionWords = mission.objective.toLowerCase().split(/\s+/);
      const contextWords = context.objective.toLowerCase().split(/\s+/);
      const sharedWords = missionWords.filter((w) => w.length > 3 && contextWords.includes(w));

      if (sharedWords.length > 0) {
        similarityFactors.push(`Shared objective terms: ${sharedWords.slice(0, 3).join(', ')}`);
      } else {
        differences.push('Distinct primary mission domain');
      }

      // Check priority/risk similarity
      if (mission.priority === 'HIGH' || mission.priority === 'CRITICAL') {
        similarityFactors.push(`Comparable high priority tier: ${mission.priority}`);
      }

      // Check mission plans or tags if available
      if (mission.plans && mission.plans.length > 0) {
        similarityFactors.push(`Has ${mission.plans.length} mission execution plan(s)`);
      }

      if (similarityFactors.length > 0) {
        const outcomeDescription = mission.status === 'COMPLETED'
          ? `Previous mission '${mission.title}' completed successfully.`
          : mission.status === 'FAILED'
          ? `Previous mission '${mission.title}' encountered failure during execution.`
          : `Previous mission '${mission.title}' reached status ${mission.status}.`;

        analogs.push({
          id: `analog_m_${mission.missionId}`,
          sourceMissionId: mission.missionId,
          similarityFactors,
          outcome: outcomeDescription,
          evidence: [mission.missionId],
          differences: differences.length > 0 ? differences : ['Different operational timestamp and runtime environment'],
          confidence: sharedWords.length > 1 ? ('HIGH' as DecisionConfidence) : ('MEDIUM' as DecisionConfidence),
        });
      }
    }

    // 2. Inspect historical experiences (Stage 11)
    const experiences = executionPersistence.getExperiences();
    for (const exp of experiences.slice(0, 5)) {
      if (exp.taskType && context.objective.toLowerCase().includes(exp.taskType.toLowerCase())) {
        analogs.push({
          id: `analog_exp_${exp.experienceId}`,
          sourceMissionId: 'mission_historical',
          sourceGoalId: exp.goalId,
          similarityFactors: [`Matched task pattern: ${exp.taskType}`],
          outcome: `Historical task execution resulted in ${exp.status} with latency ${exp.latencyMs}ms.`,
          evidence: [exp.experienceId],
          differences: ['Isolated sub-agent task rather than end-to-end mission context'],
          confidence: 'MEDIUM' as DecisionConfidence,
        });
      }
    }

    // 3. Fallback baseline analog if no past records exist yet
    if (analogs.length === 0) {
      analogs.push({
        id: 'analog_baseline_reference',
        sourceMissionId: 'mission_ref_baseline',
        similarityFactors: ['Nominal sequential DAG execution baseline'],
        outcome: 'Baseline sequential task execution previously verified under Stage 08 orchestration.',
        evidence: ['stage08_orchestration_baseline'],
        differences: ['Specific goal parameters and agent workloads vary'],
        confidence: 'LOW' as DecisionConfidence,
      });
    }

    return analogs.slice(0, 5);
  }
}

export const historicalDecisionService = new HistoricalDecisionService();
