/**
 * AryaOS V1 — Stage 19: Event-Driven Reaction Engine & Trigger Orchestration
 *
 * Provider-neutral domain models for declarative triggers, deterministic conditions,
 * risk classification, reaction proposals, causal chain tracking, and bounded loop protection.
 *
 * ABSOLUTE AXIOMS:
 * - EVENT ≠ ACTION
 * - EVENT ≠ AUTHORITY
 * - TRIGGER ≠ PERMISSION
 * - TRIGGER ≠ HUMAN APPROVAL
 * - REACTION PROPOSAL ≠ EXECUTION
 */

import { ExternalEventSource, NormalizedResourceType, NormalizedChangeType } from './externalEvent';

export type TriggerId = string;
export type TriggerVersion = number;

export type TriggerStatus =
  | 'DRAFT'
  | 'ACTIVE'
  | 'PAUSED'
  | 'SUSPENDED'
  | 'DISABLED'
  | 'REVOKED';

export type TriggerRiskLevel = 'LOW' | 'MEDIUM' | 'HIGH' | 'CRITICAL';

export type TriggerConditionOperator =
  | 'equals'
  | 'not_equals'
  | 'contains'
  | 'starts_with'
  | 'ends_with'
  | 'greater_than'
  | 'less_than'
  | 'exists'
  | 'not_exists'
  | 'in'
  | 'not_in';

export interface TriggerCondition {
  field: string;
  operator: TriggerConditionOperator;
  value?: unknown;
}

export interface TriggerConditionGroup {
  logicalOperator: 'AND' | 'OR';
  conditions: Array<TriggerCondition | TriggerConditionGroup>;
}

export interface TriggerEventFilter {
  connectorId?: string;
  sourceSystem?: ExternalEventSource | string;
  eventType?: string;
  resourceType?: NormalizedResourceType | string;
  resourceId?: string;
  changeType?: NormalizedChangeType | string;
  missionId?: string;
  projectId?: string;
}

export type TriggerReactionType =
  | 'CREATE_GOAL'
  | 'CREATE_OBSERVATION'
  | 'UPDATE_MISSION'
  | 'REQUEST_RESEARCH'
  | 'REQUEST_ANALYSIS'
  | 'REQUEST_HUMAN_APPROVAL'
  | 'PAUSE_MISSION'
  | 'REPLAN_MISSION'
  | 'EXTERNAL_ACTION';

export interface TriggerActionIntent {
  capabilityId: string;
  operation: string;
  parameters: Record<string, unknown>;
  requiredRisk?: TriggerRiskLevel;
}

export interface TriggerReaction {
  reactionType: TriggerReactionType;
  targetMissionId?: string;
  targetGoalId?: string;
  goalIntent?: string;
  observationSummary?: string;
  actionIntent?: TriggerActionIntent;
  parameters?: Record<string, unknown>;
}

export interface TriggerExecutionPolicy {
  maxRetries?: number;
  timeoutMs?: number;
  maxReactionDepth?: number; // Bounded reaction chain depth (default: 3)
  allowAutonomousExecution?: boolean; // Only for LOW risk
  rateLimit?: {
    maxTriggersPerMinute?: number;
  };
}

export interface TriggerAuthorizationPolicy {
  requiredPermissions?: string[];
  requiredRole?: string;
  requiresHumanApproval?: boolean;
}

export interface TriggerProvenance {
  createdBy: string;
  createdAt?: string;
  updatedAt?: string;
  source?: string;
  changeReason?: string;
  [key: string]: unknown;
}

export interface Trigger {
  triggerId: TriggerId;
  version: TriggerVersion;
  name: string;
  description?: string;
  status: TriggerStatus;
  eventFilter: TriggerEventFilter;
  conditions?: TriggerConditionGroup | TriggerCondition[] | TriggerCondition;
  reaction: TriggerReaction;
  riskLevel: TriggerRiskLevel;
  authorizationPolicy?: TriggerAuthorizationPolicy;
  executionPolicy?: TriggerExecutionPolicy;
  createdAt?: string;
  updatedAt?: string;
  provenance?: TriggerProvenance;
}

export interface TriggerEvaluationContext {
  event: {
    eventId: string;
    sourceSystem: string;
    eventType: string;
    connectorId: string;
    resourceType: string;
    resourceId: string;
    changeType: string;
    timestamp: string;
    epistemicStatus: string;
    data: Record<string, unknown>;
  };
  missionId?: string;
  projectId?: string;
  causationId?: string;
  correlationId?: string;
  depth?: number;
  visitedTriggerIds?: string[];
}

export type ProposalStatus =
  | 'PROPOSED'
  | 'AUTHORIZED'
  | 'AWAITING_APPROVAL'
  | 'REJECTED'
  | 'EXECUTING'
  | 'SUCCEEDED'
  | 'FAILED'
  | 'SKIPPED';

export interface ReactionProposal {
  proposalId: string;
  triggerId: TriggerId;
  triggerVersion: TriggerVersion;
  trigger?: Trigger;
  eventId: string;
  missionId?: string;
  goalId?: string;
  reactionType: TriggerReactionType;
  riskLevel: TriggerRiskLevel;
  proposedAction?: TriggerActionIntent;
  reactionParameters: Record<string, unknown>;
  authorizationRequirements: {
    requiresHumanApproval: boolean;
    requiredPermissions: string[];
    requiredRole?: string;
  };
  requiresHumanApproval?: boolean;
  provenance: {
    triggeredAt?: string;
    eventFingerprint?: string;
    causationId: string;
    correlationId: string;
    depth: number;
    visitedTriggerIds: string[];
    [key: string]: unknown;
  };
  status: ProposalStatus;
  rejectionReason?: string;
  operatorApproval?: {
    approvedBy: string;
    approvedAt: string;
    signature?: string;
  };
  createdAt?: string;
  proposedAt?: string;
}

export type ReactionExecutionStatus =
  | 'SUCCEEDED'
  | 'FAILED'
  | 'AWAITING_APPROVAL'
  | 'REQUIRES_APPROVAL'
  | 'REJECTED'
  | 'DUPLICATE'
  | 'CHAIN_LIMIT'
  | 'RATE_LIMITED';

export interface ReactionExecutionResult {
  reactionId: string;
  proposalId: string;
  triggerId: TriggerId;
  triggerVersion: TriggerVersion;
  eventId: string;
  status: ReactionExecutionStatus;
  output?: unknown;
  error?: string;
  executedAt: string;
  latencyMs: number;
  replayed: boolean;
}
