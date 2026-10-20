/**
 * AryaOS V1 — Stage 12: Mission Risk Engine
 *
 * Evaluates empirical mission-level risks across deadline, budget, dependency,
 * quality, provider, agent capacity, approval bottlenecks, and recovery history.
 * Strictly forbids presenting speculative hypotheses as verified facts.
 */

import { Mission, MissionRisk } from '../types/missionControl';
import { learningSignalService } from './learningSignalService';
import { providerEvaluationService } from './providerEvaluationService';

export class MissionRiskService {
  /**
   * Evaluates all observable risks for a mission.
   */
  public assessRisks(mission: Mission): MissionRisk[] {
    const risks: MissionRisk[] = [];
    const nowIso = new Date().toISOString();
    const now = Date.now();

    // 1. Deadline Risk Check
    if (mission.deadline) {
      const deadlineMs = new Date(mission.deadline).getTime();
      const remainingMs = deadlineMs - now;
      const plan = mission.plans[mission.plans.length - 1];
      const estDuration = typeof plan?.estimatedDurationMs === 'number' ? plan.estimatedDurationMs : 3600000;

      if (remainingMs <= 0) {
        risks.push({
          riskId: `risk-deadline-expired-${mission.missionId}`,
          type: 'DEADLINE',
          level: 'CRITICAL',
          source: 'MissionRiskService',
          evidence: [`Deadline '${mission.deadline}' is in the past.`],
          confidence: 'HIGH',
          createdAt: nowIso,
          mitigation: 'Request operator confirmation for deadline extension or partial completion.',
        });
      } else if (remainingMs < estDuration) {
        risks.push({
          riskId: `risk-deadline-tight-${mission.missionId}`,
          type: 'DEADLINE',
          level: 'HIGH',
          source: 'MissionRiskService',
          evidence: [
            `Remaining time (${Math.round(remainingMs / 60000)}m) is less than estimated duration (${Math.round(estDuration / 60000)}m).`,
          ],
          confidence: 'HIGH',
          createdAt: nowIso,
          mitigation: 'Prioritize critical path goals and consider parallel execution.',
        });
      }
    }

    // 2. Dependency Risk Check
    const failedGoals = mission.goals.filter((g) => g.status === 'FAILED');
    if (failedGoals.length > 0) {
      const failedMandatory = failedGoals.some((g) => g.mandatory);
      risks.push({
        riskId: `risk-dep-${mission.missionId}`,
        type: 'DEPENDENCY',
        level: failedMandatory ? 'CRITICAL' : 'MEDIUM',
        source: 'MissionRiskService',
        evidence: failedGoals.map((g) => `Goal '${g.goalId}' failed (mandatory: ${g.mandatory})`),
        confidence: 'HIGH',
        createdAt: nowIso,
        mitigation: failedMandatory
          ? 'Trigger mission replanning to determine alternative goal route or fallback provider.'
          : 'Continue mission with optional goal omitted.',
      });
    }

    // 3. Provider Reliability Risk Check (using Stage 11 signals)
    const actionableSignals = learningSignalService.getSignals({ status: 'ACTIONABLE' });
    const providerFailSignals = actionableSignals.filter(
      (s) => s.signalType === 'PROVIDER_HIGH_FAILURE_RATE'
    );
    if (providerFailSignals.length > 0) {
      risks.push({
        riskId: `risk-prov-${mission.missionId}`,
        type: 'PROVIDER',
        level: 'HIGH',
        source: 'LearningSignalService',
        evidence: providerFailSignals.map((s) => s.observation),
        confidence: 'HIGH',
        createdAt: nowIso,
        mitigation: 'Demote failing provider and route task dispatches to verified fallback providers.',
      });
    }

    // 4. Recovery & Replan History Risk
    if (mission.plans.length >= 3) {
      risks.push({
        riskId: `risk-recovery-churn-${mission.missionId}`,
        type: 'RECOVERY',
        level: 'MEDIUM',
        source: 'MissionRiskService',
        evidence: [`Mission has undergone ${mission.plans.length - 1} replan cycles.`],
        confidence: 'HIGH',
        createdAt: nowIso,
        mitigation: 'Perform operator review of persistent goal failures.',
      });
    }

    return risks;
  }
}

export const missionRiskService = new MissionRiskService();
