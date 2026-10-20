/**
 * AryaOS V1 — Stage 08: End-to-End Autonomous Task Orchestration Types
 *
 * Domain contracts for Goal Management, Action Graph (DAG) Decomposition,
 * Dependency Resolution, Multi-Step Execution, Observation, and Replanning.
 */

import { ProviderCapabilityType } from './intelligenceProvider';

export type GoalStatus =
  | 'CREATED'
  | 'INTERPRETING'
  | 'PLANNING'
  | 'PLANNED'
  | 'AWAITING_APPROVAL'
  | 'WAITING_APPROVAL'
  | 'READY'
  | 'EXECUTING'
  | 'RUNNING'
  | 'OBSERVING'
  | 'PAUSED'
  | 'REPLANNING'
  | 'RECOVERING'
  | 'BLOCKED'
  | 'COMPLETED'
  | 'FAILED'
  | 'CANCELLED';

export type ActionStatus =
  | 'PENDING'
  | 'READY'
  | 'WAITING_DEPENDENCY'
  | 'AWAITING_APPROVAL'
  | 'EXECUTING'
  | 'SUCCEEDED'
  | 'FAILED'
  | 'CANCELLED'
  | 'BLOCKED'
  | 'SKIPPED'
  | 'RECOVERY_REQUIRED';

export type ActionRiskLevel =
  | 'READ_ONLY'
  | 'LOW_RISK'
  | 'CONSEQUENTIAL'
  | 'EXTERNAL_SIDE_EFFECT';

export interface ActionRetryPolicy {
  maxRetries: number;
  backoffMs: number;
  retriesAttempted: number;
}

export interface ActionApprovalRequirement {
  required: boolean;
  riskLevel: ActionRiskLevel;
  approvedBy?: string;
  approvedAt?: string;
  rejectionReason?: string;
}

export interface ActionNode {
  actionId: string;
  goalId: string;
  planId: string;
  title: string;
  type: string;
  description: string;
  inputs: Record<string, unknown>;
  dependencies: string[]; // actionIds that must succeed before this node is READY
  outputs?: Record<string, unknown>;
  requiredCapability: ProviderCapabilityType;
  status: ActionStatus;
  providerId?: string;
  modelId?: string;
  executionId?: string;
  retryPolicy: ActionRetryPolicy;
  approvalRequirement: ActionApprovalRequirement;
  completionCriteria: string[];
  provenance: Record<string, unknown>;
}

export interface Plan {
  planId: string;
  goalId: string;
  version: number;
  actions: ActionNode[];
  dependencies: Record<string, string[]>; // childActionId -> parentActionIds
  executionOrder: string[][]; // Topologically-sorted layers of concurrent action IDs
  estimatedCost: {
    minUsd: number | null;
    maxUsd: number | null;
    currency: 'USD';
  };
  estimatedLatencyMs: number;
  riskLevel: ActionRiskLevel;
  requiredApprovals: string[]; // actionIds requiring human confirmation
  completionCriteria: string[];
  status: 'ACTIVE' | 'SUPERSEDED' | 'COMPLETED' | 'FAILED' | 'CANCELLED';
  createdAt: string;
  supersededAt?: string;
  replanReason?: string;
}

export interface GoalApprovalPolicy {
  requireApprovalForConsequential: boolean;
  autoApproveReadOnly: boolean;
}

export interface GoalContextRequirements {
  targetMemoryId?: string;
  contextMemories: string[];
  entityNames: string[];
}

export interface GoalProvenance {
  sourceMemoryId?: string;
  sourceMemoryTitle?: string;
  commandText: string;
  operatorId?: string;
  createdAt: string;
}

export interface Goal {
  goalId: string;
  userIntent: string;
  objective: string;
  constraints: string[];
  priority: 'LOW' | 'MEDIUM' | 'HIGH' | 'CRITICAL';
  status: GoalStatus;
  createdAt: string;
  updatedAt: string;
  currentPlanId?: string;
  currentPlanVersion: number;
  plans: Plan[]; // Preserves historical plan versions (e.g. Plan v1, Plan v2)
  completionCriteria: string[];
  approvalPolicy: GoalApprovalPolicy;
  contextRequirements: GoalContextRequirements;
  provenance: GoalProvenance;
  finalSummary?: string;
  failureReason?: string;
}

export interface ProducedArtifact {
  id: string;
  type: string;
  name: string;
  content?: string;
  uri?: string;
}

export interface Observation {
  observationId: string;
  goalId: string;
  planId: string;
  actionId: string;
  executionId: string;
  status: 'SUCCESS' | 'FAILURE' | 'PARTIAL';
  resultSummary: string;
  producedArtifacts: ProducedArtifact[];
  providerId: string;
  modelId: string;
  latencyMs: number;
  failureReason?: string;
  confidence?: number;
  downstreamImplications: string[];
  memoryReferences: string[];
  timestamp: string;
}

export interface GoalExecutionOptions {
  maxConcurrentActions?: number;
  signal?: AbortSignal;
  autoApprove?: boolean;
  maxReplans?: number;
  onGoalProgress?: (goal: Goal, activePlan: Plan) => void;
}
