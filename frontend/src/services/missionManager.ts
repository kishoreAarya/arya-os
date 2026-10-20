/**
 * AryaOS V1 — Stage 12: Mission Manager Service
 *
 * Central coordinator for multi-goal missions.
 * Manages mission creation, persistence, pause/resume, cancellation, and deterministic
 * completion evaluation (full completion vs partial success vs failure).
 * STRICT BOUNDARY: The Mission Manager does NOT directly execute provider calls.
 */

import {
  Mission,
  MissionStatus,
  MissionPriority,
  MissionGoalReference,
  MissionDependency,
  MissionConstraint,
  MissionMilestone,
  MissionCompletionCriteria,
  MissionExecutionPolicy,
  MissionProgress,
} from '../types/missionControl';
import { GoalStatus } from '../types/goalOrchestration';
import { missionPlanner } from './missionPlanner';
import { missionObservationService } from './missionObservationService';
import { executionPersistence } from './executionPersistence';

export interface CreateMissionInput {
  missionId?: string;
  title: string;
  objective: string;
  goals: MissionGoalReference[];
  dependencies?: MissionDependency[];
  priority?: MissionPriority;
  deadline?: string;
  constraints?: MissionConstraint[];
  milestones?: MissionMilestone[];
  completionCriteria?: Partial<MissionCompletionCriteria>;
  executionPolicy?: Partial<MissionExecutionPolicy>;
  provenance?: Record<string, unknown>;
}

export class MissionManager {
  /**
   * Creates a new Mission, plans its initial execution DAG (Plan v1), and persists it.
   */
  public createMission(input: CreateMissionInput): Mission {
    const timestamp = new Date().toISOString();
    const missionId = input.missionId || `mis-${Date.now()}-${Math.random().toString(36).substr(2, 6)}`;

    const dependencies = input.dependencies || [];
    const priority = input.priority || 'NORMAL';
    const constraints = input.constraints || [];
    const milestones = input.milestones || [];

    const completionCriteria: MissionCompletionCriteria = {
      mandatoryGoalsCompleted: true,
      minimumSuccessRate: 0.7,
      requiredMilestonesCompleted: [],
      allowPartialSuccess: true,
      requireHumanSignoff: false,
      ...input.completionCriteria,
    };

    const executionPolicy: MissionExecutionPolicy = {
      autoApproveReadOnly: true,
      allowPartialSuccess: true,
      maxCostUsd: null,
      deadline: input.deadline,
      replanOnGoalFailure: true,
      ...input.executionPolicy,
    };

    const progress: MissionProgress = {
      totalGoals: input.goals.length,
      completedGoals: 0,
      failedGoals: 0,
      inProgressGoals: 0,
      blockedGoals: 0,
      percentage: 0,
    };

    const sanitizedProvenance = executionPersistence.sanitizeForPersistence(input.provenance || {});

    const mission: Mission = {
      missionId,
      title: input.title,
      objective: input.objective,
      goals: input.goals,
      dependencies,
      priority,
      deadline: input.deadline,
      constraints,
      milestones,
      completionCriteria,
      executionPolicy,
      riskLevel: 'LOW',
      status: 'PLANNED',
      progress,
      plans: [],
      currentPlanVersion: 1,
      checkpoints: [],
      observations: [],
      decisions: [],
      createdAt: timestamp,
      updatedAt: timestamp,
      provenance: sanitizedProvenance,
    };

    // Generate initial plan (Plan v1)
    const initialPlan = missionPlanner.generatePlan(mission, 1, 'Initial mission plan generation');
    mission.plans.push(initialPlan);
    mission.status = 'READY';

    // Persist mission
    executionPersistence.saveMission(mission);

    // Record initial observation
    missionObservationService.recordObservation(
      missionId,
      'PROGRESS',
      `Mission '${input.title}' created with ${input.goals.length} goals. Plan v1 generated.`,
      { goalCount: input.goals.length, initialPlanVersion: 1 }
    );

    return mission;
  }

  /**
   * Retrieves a mission by ID.
   */
  public getMission(missionId: string): Mission | null {
    return executionPersistence.getMission(missionId);
  }

  /**
   * Lists all persisted missions.
   */
  public listMissions(): Mission[] {
    return executionPersistence.getMissions();
  }

  /**
   * Pauses an active mission.
   */
  public pauseMission(missionId: string): boolean {
    const mission = this.getMission(missionId);
    if (!mission || mission.status === 'COMPLETED' || mission.status === 'CANCELLED') {
      return false;
    }
    mission.status = 'PAUSED';
    mission.updatedAt = new Date().toISOString();
    executionPersistence.saveMission(mission);

    missionObservationService.recordObservation(
      missionId,
      'PROGRESS',
      `Mission '${missionId}' paused by operator.`,
      { status: 'PAUSED' }
    );
    return true;
  }

  /**
   * Resumes a paused mission.
   */
  public resumeMission(missionId: string): boolean {
    const mission = this.getMission(missionId);
    if (!mission || mission.status !== 'PAUSED') {
      return false;
    }
    mission.status = 'RUNNING';
    mission.updatedAt = new Date().toISOString();
    executionPersistence.saveMission(mission);

    missionObservationService.recordObservation(
      missionId,
      'PROGRESS',
      `Mission '${missionId}' resumed.`,
      { status: 'RUNNING' }
    );
    return true;
  }

  /**
   * Cancels a mission under explicit human governance.
   */
  public cancelMission(missionId: string, reason?: string, operatorId?: string): boolean {
    const mission = this.getMission(missionId);
    if (!mission || mission.status === 'COMPLETED' || mission.status === 'CANCELLED') {
      return false;
    }
    mission.status = 'CANCELLED';
    mission.updatedAt = new Date().toISOString();

    const decision = {
      decisionId: `mdec-cancel-${Date.now()}`,
      missionId,
      decisionType: 'MISSION_CANCELLATION',
      status: 'APPROVED' as const,
      decidedBy: operatorId || 'Operator',
      reason: reason || 'Mission cancelled by operator.',
      timestamp: new Date().toISOString(),
      requiresHumanApproval: true,
    };
    mission.decisions.push(decision);

    executionPersistence.saveMission(mission);

    missionObservationService.recordObservation(
      missionId,
      'HUMAN_DECISION',
      `Mission '${missionId}' cancelled: ${reason || 'Operator instruction'}`,
      { operatorId: operatorId || 'Operator', reason }
    );
    return true;
  }

  /**
   * Archives a completed or cancelled mission.
   */
  public archiveMission(missionId: string): boolean {
    const mission = this.getMission(missionId);
    if (!mission) return false;
    mission.status = 'ARCHIVED';
    mission.updatedAt = new Date().toISOString();
    return executionPersistence.saveMission(mission);
  }

  /**
   * Updates a goal's status within the mission and recalculates progress.
   */
  public updateGoalStatus(
    missionId: string,
    goalId: string,
    status: GoalStatus
  ): boolean {
    const mission = this.getMission(missionId);
    if (!mission) return false;

    const targetGoal = mission.goals.find((g) => g.goalId === goalId);
    if (!targetGoal) return false;

    targetGoal.status = status;

    // Recalculate progress
    const total = mission.goals.length;
    const completed = mission.goals.filter(
      (g) => g.status === 'COMPLETED' || (g.status as string) === 'SUCCEEDED'
    ).length;
    const failed = mission.goals.filter((g) => g.status === 'FAILED').length;
    const inProgress = mission.goals.filter(
      (g) => g.status === 'RUNNING' || (g.status as string) === 'EXECUTING'
    ).length;
    const blocked = mission.goals.filter((g) => g.status === 'BLOCKED').length;

    mission.progress = {
      totalGoals: total,
      completedGoals: completed,
      failedGoals: failed,
      inProgressGoals: inProgress,
      blockedGoals: blocked,
      percentage: total > 0 ? Number(((completed / total) * 100).toFixed(1)) : 0,
    };

    mission.updatedAt = new Date().toISOString();
    executionPersistence.saveMission(mission);

    missionObservationService.recordObservation(
      missionId,
      'PROGRESS',
      `Goal '${goalId}' status transitioned to ${status}. Mission progress: ${mission.progress.percentage}%`,
      { goalId, status, progressPercentage: mission.progress.percentage }
    );

    return true;
  }

  /**
   * Deterministically evaluates mission completion status against its criteria.
   */
  public evaluateCompletion(missionId: string): {
    status: MissionStatus;
    isCompleted: boolean;
    isPartialSuccess: boolean;
    summary: string;
  } {
    const mission = this.getMission(missionId);
    if (!mission) {
      return {
        status: 'FAILED',
        isCompleted: false,
        isPartialSuccess: false,
        summary: `Mission '${missionId}' not found.`,
      };
    }

    const { completionCriteria, goals } = mission;

    const mandatoryGoals = goals.filter((g) => g.mandatory);
    const optionalGoals = goals.filter((g) => !g.mandatory);

    const mandatoryCompleted = mandatoryGoals.every(
      (g) => g.status === 'COMPLETED' || (g.status as string) === 'SUCCEEDED'
    );
    const mandatoryFailed = mandatoryGoals.some((g) => g.status === 'FAILED');

    const totalCompleted = goals.filter(
      (g) => g.status === 'COMPLETED' || (g.status as string) === 'SUCCEEDED'
    ).length;
    const successRate = goals.length > 0 ? totalCompleted / goals.length : 0;

    let resultStatus: MissionStatus = 'RUNNING';
    let isCompleted = false;
    let isPartialSuccess = false;
    let summary = '';

    if (mandatoryFailed) {
      resultStatus = 'FAILED';
      isCompleted = false;
      summary = `Mission failed: One or more mandatory goals failed.`;
    } else if (mandatoryCompleted) {
      if (totalCompleted === goals.length) {
        resultStatus = 'COMPLETED';
        isCompleted = true;
        summary = `Mission completed successfully: All ${goals.length} goals succeeded.`;
      } else if (completionCriteria.allowPartialSuccess && successRate >= completionCriteria.minimumSuccessRate) {
        resultStatus = 'PARTIALLY_COMPLETED';
        isCompleted = true;
        isPartialSuccess = true;
        summary = `Mission achieved partial success: All mandatory goals completed, with ${totalCompleted}/${goals.length} total goals succeeded (${(successRate * 100).toFixed(0)}%).`;
      } else {
        resultStatus = 'FAILED';
        summary = `Mission failed: Success rate (${(successRate * 100).toFixed(0)}%) fell below minimum required (${(completionCriteria.minimumSuccessRate * 100).toFixed(0)}%).`;
      }
    } else {
      resultStatus = 'RUNNING';
      summary = `Mission in progress: ${totalCompleted}/${goals.length} goals completed.`;
    }

    if (isCompleted || resultStatus === 'FAILED') {
      mission.status = resultStatus;
      mission.updatedAt = new Date().toISOString();
      executionPersistence.saveMission(mission);
    }

    return {
      status: resultStatus,
      isCompleted,
      isPartialSuccess,
      summary,
    };
  }
}

export const missionManager = new MissionManager();
