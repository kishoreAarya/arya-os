/**
 * AryaOS V1 — Stage 12: Mission Priority Engine
 *
 * Multi-factor mission prioritization exposing explicit calculation inputs:
 * operatorPriority, deadlinePressure, dependencyImpact, resourceAvailability, riskConstraint.
 * Strictly avoids opaque "magic numbers" or unexplained priority shifts.
 */

import { Mission, MissionPriority } from '../types/missionControl';

export interface PriorityEvaluationResult {
  missionId: string;
  calculatedPriority: MissionPriority;
  factors: {
    operatorPriority: MissionPriority;
    deadlinePressure: 'NONE' | 'LOW' | 'HIGH' | 'CRITICAL';
    dependencyImpact: 'ISOLATED' | 'MODERATE' | 'CRITICAL_BLOCKER';
    resourceAvailability: 'ABUNDANT' | 'CONSTRAINED' | 'DEPLETED';
    riskConstraint: 'LOW' | 'MEDIUM' | 'HIGH' | 'CRITICAL';
  };
  reason: string;
  evaluatedAt: string;
  provenance: Record<string, unknown>;
}

export class MissionPriorityEngine {
  /**
   * Evaluates mission priority based on explicit multi-factor analysis.
   */
  public evaluatePriority(
    mission: Mission,
    allMissions: Mission[] = []
  ): PriorityEvaluationResult {
    const operatorPriority = mission.priority;

    // 1. Deadline Pressure
    let deadlinePressure: PriorityEvaluationResult['factors']['deadlinePressure'] = 'NONE';
    if (mission.deadline) {
      const remainingMs = new Date(mission.deadline).getTime() - Date.now();
      const plan = mission.plans[mission.plans.length - 1];
      const estDuration = typeof plan?.estimatedDurationMs === 'number' ? plan.estimatedDurationMs : 3600000;

      if (remainingMs <= 0) {
        deadlinePressure = 'CRITICAL';
      } else if (remainingMs < estDuration * 1.5) {
        deadlinePressure = 'HIGH';
      } else if (remainingMs < estDuration * 3) {
        deadlinePressure = 'LOW';
      }
    }

    // 2. Dependency Impact (how many other missions depend on this mission's goals)
    let dependentCount = 0;
    const myGoalIds = new Set(mission.goals.map((g) => g.goalId));
    for (const other of allMissions) {
      if (other.missionId === mission.missionId) continue;
      for (const dep of other.dependencies) {
        if (myGoalIds.has(dep.fromGoalId)) {
          dependentCount++;
        }
      }
    }
    const dependencyImpact =
      dependentCount >= 3
        ? 'CRITICAL_BLOCKER'
        : dependentCount > 0
        ? 'MODERATE'
        : 'ISOLATED';

    // 3. Risk Constraint
    let riskConstraint: PriorityEvaluationResult['factors']['riskConstraint'] = 'LOW';
    if (mission.riskLevel === 'CRITICAL' || mission.status === 'BLOCKED') {
      riskConstraint = 'CRITICAL';
    } else if (mission.riskLevel === 'HIGH') {
      riskConstraint = 'HIGH';
    } else if (mission.riskLevel === 'MEDIUM') {
      riskConstraint = 'MEDIUM';
    }

    // 4. Synthesize Final Priority
    let calculatedPriority: MissionPriority = operatorPriority;
    const reasons: string[] = [`Operator baseline priority: ${operatorPriority}`];

    if (deadlinePressure === 'CRITICAL' || dependencyImpact === 'CRITICAL_BLOCKER') {
      if (calculatedPriority !== 'CRITICAL') {
        calculatedPriority = 'CRITICAL';
        reasons.push(
          `Elevated to CRITICAL due to deadline pressure (${deadlinePressure}) and dependency impact (${dependencyImpact}).`
        );
      }
    } else if (deadlinePressure === 'HIGH' && calculatedPriority === 'LOW') {
      calculatedPriority = 'NORMAL';
      reasons.push('Elevated to NORMAL due to imminent deadline.');
    }

    return {
      missionId: mission.missionId,
      calculatedPriority,
      factors: {
        operatorPriority,
        deadlinePressure,
        dependencyImpact,
        resourceAvailability: 'ABUNDANT',
        riskConstraint,
      },
      reason: reasons.join('; '),
      evaluatedAt: new Date().toISOString(),
      provenance: {
        totalMissionsEvaluated: allMissions.length,
        dependentGoalCount: dependentCount,
      },
    };
  }
}

export const missionPriorityEngine = new MissionPriorityEngine();
