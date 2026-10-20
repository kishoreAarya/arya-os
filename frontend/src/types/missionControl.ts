/**
 * AryaOS V1 — Stage 12: Long-Horizon Mission Control Domain Models
 *
 * Provider-neutral, durable domain contracts for:
 * - Long-horizon Missions coordinating multiple Goals
 * - Deterministic Mission Dependencies & Critical Paths
 * - Transparent Multi-factor Mission Prioritization
 * - Cross-Mission Resource Arbitration
 * - Deterministic Checkpoints & Crash Recovery Integration
 * - Adaptive Mission Replanning & Plan Versioning (v1, v2, etc.)
 * - Multi-category Mission Observations & Risk Engine
 * - Human Governance Boundaries for Mission-level Operations
 */

import { GoalStatus, ActionRiskLevel } from './goalOrchestration';
import { ConfidenceBand } from './agentEvaluation';

export type MissionStatus =
  | 'DRAFT'
  | 'PLANNED'
  | 'READY'
  | 'RUNNING'
  | 'PAUSED'
  | 'WAITING_FOR_APPROVAL'
  | 'BLOCKED'
  | 'DEGRADED'
  | 'REPLANNING'
  | 'COMPLETED'
  | 'PARTIALLY_COMPLETED'
  | 'FAILED'
  | 'CANCELLED'
  | 'ARCHIVED';

export type MissionPriority = 'LOW' | 'NORMAL' | 'HIGH' | 'CRITICAL';

export interface MissionGoalReference {
  goalId: string;
  title: string;
  mandatory: boolean;
  status: GoalStatus;
  weight: number;
  timeoutMs?: number;
}

export type DependencyType = 'FINISH_TO_START' | 'START_TO_START';

export interface MissionDependency {
  fromGoalId: string;
  toGoalId: string;
  type: DependencyType;
  condition?: string;
}

export interface MissionMilestone {
  milestoneId: string;
  title: string;
  targetDate?: string;
  requiredGoalIds: string[];
  achieved: boolean;
  achievedAt?: string;
}

export type ConstraintType =
  | 'COST_BUDGET'
  | 'TIME_DEADLINE'
  | 'PROVIDER_ALLOWLIST'
  | 'MAX_CONCURRENCY';

export interface MissionConstraint {
  type: ConstraintType;
  value: unknown;
  strict: boolean;
}

export type MissionRiskCategory =
  | 'DEADLINE'
  | 'BUDGET'
  | 'DEPENDENCY'
  | 'QUALITY'
  | 'PROVIDER'
  | 'AGENT_CAPACITY'
  | 'APPROVAL_BOTTLENECK'
  | 'RECOVERY';

export interface MissionRisk {
  riskId: string;
  type: MissionRiskCategory;
  level: 'LOW' | 'MEDIUM' | 'HIGH' | 'CRITICAL';
  source: string;
  evidence: string[];
  confidence: ConfidenceBand;
  createdAt: string;
  mitigation?: string;
}

export interface MissionProgress {
  totalGoals: number;
  completedGoals: number;
  failedGoals: number;
  inProgressGoals: number;
  blockedGoals: number;
  percentage: number;
  currentMilestoneId?: string;
}

export type MissionObservationCategory =
  | 'PROGRESS'
  | 'QUALITY'
  | 'RESOURCE'
  | 'DEADLINE'
  | 'FAILURE'
  | 'RISK'
  | 'DEPENDENCY'
  | 'LEARNING'
  | 'HUMAN_DECISION';

export interface MissionObservation {
  observationId: string;
  missionId: string;
  category: MissionObservationCategory;
  summary: string;
  timestamp: string;
  details: Record<string, unknown>;
}

export interface MissionDecision {
  decisionId: string;
  missionId: string;
  decisionType: string;
  status: 'PROPOSED' | 'APPROVED' | 'REJECTED' | 'APPLIED';
  decidedBy?: string;
  reason?: string;
  timestamp: string;
  requiresHumanApproval: boolean;
}

export interface MissionExecutionPolicy {
  autoApproveReadOnly: boolean;
  allowPartialSuccess: boolean;
  maxCostUsd: number | null;
  deadline?: string;
  replanOnGoalFailure: boolean;
}

export interface MissionCompletionCriteria {
  mandatoryGoalsCompleted: boolean;
  minimumSuccessRate: number;
  requiredMilestonesCompleted: string[];
  allowPartialSuccess: boolean;
  requireHumanSignoff: boolean;
}

export interface MissionCheckpoint {
  checkpointId: string;
  missionId: string;
  missionStatus: MissionStatus;
  planVersion: number;
  completedGoals: string[];
  activeGoals: string[];
  blockedGoals: string[];
  pendingApprovals: string[];
  resourceState: Record<string, unknown>;
  lastObservationId?: string;
  lastDecisionId?: string;
  timestamp: string;
}

export interface MissionExecutionPlan {
  missionId: string;
  planVersion: number;
  goalOrder: string[][];
  criticalPath: string[];
  estimatedCost: {
    minUsd: number | null;
    maxUsd: number | null;
    currency: 'USD';
  };
  estimatedDurationMs: number | 'UNKNOWN';
  riskAssessment: MissionRisk[];
  assumptions: string[];
  evidence: string[];
  confidence: ConfidenceBand;
  createdAt: string;
  previousPlanVersion?: number;
  changeReason?: string;
  preservedGoals: string[];
  affectedGoals: string[];
}

export interface Mission {
  missionId: string;
  title: string;
  objective: string;
  goals: MissionGoalReference[];
  dependencies: MissionDependency[];
  priority: MissionPriority;
  deadline?: string;
  constraints: MissionConstraint[];
  milestones: MissionMilestone[];
  completionCriteria: MissionCompletionCriteria;
  executionPolicy: MissionExecutionPolicy;
  riskLevel: 'LOW' | 'MEDIUM' | 'HIGH' | 'CRITICAL';
  status: MissionStatus;
  progress: MissionProgress;
  plans: MissionExecutionPlan[];
  currentPlanVersion: number;
  checkpoints: MissionCheckpoint[];
  observations: MissionObservation[];
  decisions: MissionDecision[];
  createdAt: string;
  updatedAt: string;
  provenance: Record<string, unknown>;
}

export interface ResourceAllocationDecision {
  missionId: string;
  requestedResource: string;
  availableResource: string | number;
  decision: 'GRANTED' | 'THROTTLED' | 'QUEUED' | 'REJECTED';
  reason: string;
  affectedMissions: string[];
  provenance: Record<string, unknown>;
}
