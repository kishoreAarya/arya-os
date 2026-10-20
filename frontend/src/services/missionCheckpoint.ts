/**
 * AryaOS V1 — Stage 12: Mission Checkpoint & Recovery Service
 *
 * Persists deterministic mission checkpoints and integrates with Stage 09 crash recovery.
 * Preserves verified completed goals, prevents duplicate executions, and enforces
 * human approval on consequential interrupted work across restarts.
 */

import {
  Mission,
  MissionCheckpoint,
} from '../types/missionControl';
import { executionPersistence } from './executionPersistence';

export class MissionCheckpointService {
  /**
   * Creates a deterministic checkpoint of the mission state.
   */
  public createCheckpoint(mission: Mission): MissionCheckpoint {
    const timestamp = new Date().toISOString();
    const checkpointId = `mcp-${mission.missionId}-v${mission.currentPlanVersion}-${Date.now()}`;

    const completedGoals = mission.goals
      .filter((g) => g.status === 'COMPLETED' || (g.status as string) === 'SUCCEEDED')
      .map((g) => g.goalId);

    const activeGoals = mission.goals
      .filter((g) => g.status === 'RUNNING' || (g.status as string) === 'EXECUTING')
      .map((g) => g.goalId);

    const blockedGoals = mission.goals
      .filter((g) => g.status === 'BLOCKED')
      .map((g) => g.goalId);

    const pendingApprovals = mission.decisions
      .filter((d) => d.status === 'PROPOSED' && d.requiresHumanApproval)
      .map((d) => d.decisionId);

    const lastObservation = mission.observations[mission.observations.length - 1];
    const lastDecision = mission.decisions[mission.decisions.length - 1];

    const checkpoint: MissionCheckpoint = {
      checkpointId,
      missionId: mission.missionId,
      missionStatus: mission.status,
      planVersion: mission.currentPlanVersion,
      completedGoals,
      activeGoals,
      blockedGoals,
      pendingApprovals,
      resourceState: {
        totalGoals: mission.goals.length,
        completedCount: completedGoals.length,
      },
      lastObservationId: lastObservation?.observationId,
      lastDecisionId: lastDecision?.decisionId,
      timestamp,
    };

    // Save checkpoint
    executionPersistence.saveMissionCheckpoint(checkpoint);

    // Attach to mission
    if (!mission.checkpoints) mission.checkpoints = [];
    mission.checkpoints.push(checkpoint);
    executionPersistence.saveMission(mission);

    return checkpoint;
  }

  /**
   * Restores a mission from a saved checkpoint following application crash or restart.
   */
  public restoreMissionFromCheckpoint(checkpointId: string): {
    success: boolean;
    mission?: Mission;
    resumedGoals: string[];
    approvalRequiredGoals: string[];
    error?: string;
  } {
    const checkpoints = executionPersistence.getMissionCheckpoints();
    const checkpoint = checkpoints.find((c) => c.checkpointId === checkpointId);
    if (!checkpoint) {
      return {
        success: false,
        resumedGoals: [],
        approvalRequiredGoals: [],
        error: `Checkpoint '${checkpointId}' not found.`,
      };
    }

    const mission = executionPersistence.getMission(checkpoint.missionId);
    if (!mission) {
      return {
        success: false,
        resumedGoals: [],
        approvalRequiredGoals: [],
        error: `Associated Mission '${checkpoint.missionId}' not found.`,
      };
    }

    const resumedGoals: string[] = [];
    const approvalRequiredGoals: string[] = [];

    // Analyze goals to resume safely
    for (const g of mission.goals) {
      // 1. Preserve verified completed work
      if (checkpoint.completedGoals.includes(g.goalId)) {
        g.status = 'COMPLETED';
        continue;
      }

      // 2. Interrupted goals
      if (checkpoint.activeGoals.includes(g.goalId)) {
        if (g.mandatory) {
          // Consequential/mandatory goals require human review before resuming
          g.status = 'WAITING_APPROVAL';
          approvalRequiredGoals.push(g.goalId);
        } else {
          // Safe optional goals reset to READY
          g.status = 'READY';
          resumedGoals.push(g.goalId);
        }
      }
    }

    // Set restored status
    mission.status = approvalRequiredGoals.length > 0 ? 'WAITING_FOR_APPROVAL' : 'READY';
    mission.updatedAt = new Date().toISOString();
    executionPersistence.saveMission(mission);

    return {
      success: true,
      mission,
      resumedGoals,
      approvalRequiredGoals,
    };
  }
}

export const missionCheckpointService = new MissionCheckpointService();
