/**
 * AryaOS V1 — Stage 12: Adaptive Mission Replanner
 *
 * Implements immutable plan versioning (Plan v1 -> Plan v2) upon goal failure,
 * deadline pressure, or quality deficits.
 * Strictly preserves verified completed goals and generates an auditable replan trace.
 */

import {
  Mission,
  MissionExecutionPlan,
  MissionGoalReference,
} from '../types/missionControl';
import { missionPlanner } from './missionPlanner';
import { missionObservationService } from './missionObservationService';
import { executionPersistence } from './executionPersistence';

export class MissionReplanner {
  /**
   * Adapts an existing mission, producing a new immutable plan version while
   * preserving already completed or succeeded goals.
   */
  public replanMission(
    missionId: string,
    reason: string,
    updatedGoals?: MissionGoalReference[]
  ): { success: boolean; newPlan?: MissionExecutionPlan; error?: string } {
    const mission = executionPersistence.getMission(missionId);
    if (!mission) {
      return { success: false, error: `Mission '${missionId}' not found.` };
    }

    const previousPlan = mission.plans[mission.plans.length - 1];
    const newVersion = previousPlan ? previousPlan.planVersion + 1 : mission.plans.length + 1;

    // Apply updated goals if provided, while preserving completed status
    if (updatedGoals) {
      mission.goals = updatedGoals.map((ug) => {
        const existing = mission.goals.find((eg) => eg.goalId === ug.goalId);
        if (existing && (existing.status === 'COMPLETED' || (existing.status as string) === 'SUCCEEDED')) {
          return existing; // Preserve verified completed work
        }
        return ug;
      });
    }

    try {
      const newPlan = missionPlanner.generatePlan(
        mission,
        newVersion,
        reason,
        previousPlan
      );

      // Append new plan version without mutating previous plan
      mission.plans.push(newPlan);
      mission.currentPlanVersion = newVersion;
      mission.status = 'READY';
      mission.updatedAt = new Date().toISOString();

      executionPersistence.saveMission(mission);

      // Record replanning observation
      missionObservationService.recordObservation(
        missionId,
        'PROGRESS',
        `Mission replanned to Plan v${newVersion}: ${reason}`,
        {
          previousPlanVersion: previousPlan?.planVersion,
          newPlanVersion: newVersion,
          preservedGoals: newPlan.preservedGoals,
          affectedGoals: newPlan.affectedGoals,
        }
      );

      return { success: true, newPlan };
    } catch (err: unknown) {
      const errorMessage = err instanceof Error ? err.message : String(err);
      return { success: false, error: errorMessage };
    }
  }
}

export const missionReplanner = new MissionReplanner();
