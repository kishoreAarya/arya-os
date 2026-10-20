/**
 * AryaOS V1 — Stage 09: Persistent Autonomous Operations & Recovery Types
 *
 * Contracts for Durable Orchestration State, Event-Sourced Execution Journal,
 * Crash Recovery Policies, Action Resume Classifications, and Scheduler Jobs.
 */

import { Goal, Plan, ActionNode, Observation } from './goalOrchestration';

/**
 * 1. Action Recovery Classifications
 * Explicit safety policies governing how an action behaves during crash recovery.
 */
export type ActionRecoveryClassification =
  | 'SAFE_TO_RETRY'             // Read-only or pure query operations safe to execute again
  | 'IDEMPOTENT_RETRY'          // Operations protected by Stage 07 idempotency keys
  | 'REQUIRES_REVALIDATION'     // Ambiguous execution requiring state check before retry
  | 'REQUIRES_HUMAN_APPROVAL'   // Consequential/side-effect actions requiring operator confirmation
  | 'DO_NOT_RETRY';             // Succeeded, cancelled, or permanently failed actions

/**
 * 2. Immutable Event Types for Event-Sourced Execution Journal
 */
export type OrchestrationJournalEventType =
  | 'GOAL_CREATED'
  | 'GOAL_INTERPRETED'
  | 'PLAN_CREATED'
  | 'ACTION_READY'
  | 'ACTION_STARTED'
  | 'ACTION_SUCCEEDED'
  | 'ACTION_FAILED'
  | 'ACTION_TIMEOUT'
  | 'ACTION_CANCELLED'
  | 'PROVIDER_FALLBACK'
  | 'APPROVAL_REQUIRED'
  | 'APPROVAL_GRANTED'
  | 'APPROVAL_REJECTED'
  | 'GOAL_PAUSED'
  | 'GOAL_RESUMED'
  | 'GOAL_REPLANNED'
  | 'MEMORY_COMMITTED'
  | 'GOAL_COMPLETED'
  | 'GOAL_FAILED'
  | 'GOAL_CANCELLED'
  | 'RECOVERY_INITIATED'
  | 'RECOVERY_COMPLETED'
  | 'AGENT_ASSIGNED'
  | 'ACTION_SCHEDULED'
  | 'ACTION_DISPATCHED'
  | 'LEASE_ACQUIRED'
  | 'LEASE_RELEASED'
  | 'CONFLICT_DETECTED'
  | 'CONFLICT_RESOLVED'
  | 'QUALITY_GATE_EVALUATED'
  | 'EVALUATION_RECORDED'
  | 'EXPERIENCE_STORED'
  | 'LEARNING_SIGNAL_DERIVED'
  | 'POLICY_RECOMMENDED'
  | 'POLICY_RECOMMENDATION_DECIDED'
  | 'PLAN_EVALUATION_COMPLETED'
  | 'EXTERNAL_EVENT_RECEIVED'
  | 'EXTERNAL_EVENT_REJECTED'
  | 'EXTERNAL_EVENT_DUPLICATE'
  | 'EXTERNAL_EVENT_AUTHENTICATED'
  | 'EXTERNAL_EVENT_NORMALIZED'
  | 'EXTERNAL_EVENT_RECONCILED'
  | 'EXTERNAL_EVENT_FAILED'
  // Stage 19 event types
  | 'TRIGGER_MATCHED'
  | 'TRIGGER_SKIPPED'
  | 'REACTION_PROPOSED'
  | 'REACTION_AUTHORIZED'
  | 'REACTION_REJECTED'
  | 'REACTION_AWAITING_APPROVAL'
  | 'REACTION_EXECUTING'
  | 'REACTION_SUCCEEDED'
  | 'REACTION_FAILED'
  | 'REACTION_DUPLICATE'
  | 'REACTION_CHAIN_LIMIT'
  // Stage 20 event types
  | 'POLICY_REGISTERED'
  | 'POLICY_UPDATED'
  | 'POLICY_PROPOSED'
  | 'POLICY_APPROVED'
  | 'POLICY_REJECTED'
  | 'POLICY_ACTIVATED'
  | 'POLICY_DEACTIVATED'
  | 'POLICY_ROLLED_BACK'
  | 'POLICY_EVALUATED'
  | 'POLICY_CONFLICT_DETECTED'
  | 'POLICY_DRIFT_DETECTED'
  | 'POLICY_SHADOW_EVALUATED'
  // Stage 21 event types
  | 'GOVERNANCE_REQUESTED'
  | 'GOVERNANCE_CONTEXT_BUILT'
  | 'POLICY_SNAPSHOT_CREATED'
  | 'GOVERNANCE_EVALUATED'
  | 'GOVERNANCE_ALLOWED'
  | 'GOVERNANCE_DENIED'
  | 'GOVERNANCE_LIMITED'
  | 'GOVERNANCE_APPROVAL_REQUIRED'
  | 'GOVERNANCE_REVIEW_REQUIRED'
  | 'GOVERNANCE_DEFERRED'
  | 'GOVERNANCE_PAUSED'
  | 'GOVERNANCE_STALE'
  | 'GOVERNANCE_REEVALUATED'
  // Stage 23 event types
  | 'RECOVERY_CONTROL_CREATED'
  | 'RECOVERY_CONTROL_CLASSIFIED'
  | 'RECOVERY_CONTROL_ASSESSED'
  | 'RECOVERY_CONTROL_DECIDED'
  | 'RECOVERY_CONTROL_STALE'
  | 'RECOVERY_CONTROL_SUPERSEDED'
  | 'RECOVERY_CONTROL_EXPIRED'
  | 'RECOVERY_CONTROL_ESCALATED';

/**
 * 3. Journal Event Record
 */
export interface JournalEvent {
  eventId: string;
  sequenceNumber: number;
  timestamp: string;
  goalId: string;
  planId?: string;
  planVersion?: number;
  actionId?: string;
  eventType: OrchestrationJournalEventType;
  previousState?: string;
  newState?: string;
  provenance: Record<string, unknown>;
  payload: Record<string, unknown>;
  schemaVersion: number;
}

/**
 * 4. Human Approval Persistence Envelope
 */
export interface PersistedApprovalRecord {
  approvalId: string;
  goalId: string;
  planId: string;
  actionId: string;
  actionTitle: string;
  riskLevel: string;
  requestedAt: string;
  status: 'PENDING' | 'APPROVED' | 'REJECTED' | 'EXPIRED';
  decidedAt?: string;
  decidedBy?: string;
  rejectionReason?: string;
  expiresAt: string;
}

/**
 * 5. Operational Telemetry Model
 */
export interface OperationalTelemetry {
  totalGoalsStarted: number;
  totalGoalsCompleted: number;
  totalGoalsFailed: number;
  totalGoalsRecovered: number;
  totalActionsExecuted: number;
  totalFallbacksTriggered: number;
  totalReplans: number;
  averageLatencyMs: number | 'UNKNOWN';
  totalCostUsd: number | 'UNKNOWN';
  lastRecoveryAt?: string;
}

/**
 * 6. Root Persisted Orchestration Envelope
 */
import {
  ExperienceRecord,
  EvaluationRecord,
  LearningSignal,
  PolicyRecommendation,
  PlanEvaluation,
} from './agentEvaluation';
import { Mission, MissionCheckpoint } from './missionControl';
import {
  KnowledgeNode,
  KnowledgeEdge,
  KnowledgeFact,
  KnowledgeContradiction,
  KnowledgePattern,
  KnowledgeStrategy,
  MissionKnowledgeSnapshot,
  KnowledgeSnapshot,
} from './strategicKnowledge';
import {
  Decision,
  DecisionContext,
  DecisionRecommendation,
  PostDecisionRecord,
  DecisionEvaluation,
} from './decisionIntelligence';
import {
  ActionAuditRecord,
  ActionResult,
  ActionRequest,
} from './actionBus';

export interface PersistedOrchestrationEnvelope {
  schemaVersion: number;
  savedAt: string;
  goals: Record<string, Goal>;
  activeGoalId: string | null;
  observations: Record<string, Observation[]>;
  approvals: Record<string, PersistedApprovalRecord>;
  telemetry: OperationalTelemetry;
  agentTasks?: Record<string, unknown>;
  conflictRecords?: Record<string, unknown>;
  experiences?: Record<string, ExperienceRecord>;
  evaluations?: Record<string, EvaluationRecord>;
  learningSignals?: Record<string, LearningSignal>;
  policyRecommendations?: Record<string, PolicyRecommendation>;
  planEvaluations?: Record<string, PlanEvaluation>;
  // Stage 12 extensions
  missions?: Record<string, Mission>;
  activeMissionId?: string | null;
  missionCheckpoints?: Record<string, MissionCheckpoint>;
  // Stage 13 extensions
  knowledgeNodes?: Record<string, KnowledgeNode>;
  knowledgeEdges?: KnowledgeEdge[];
  knowledgeFacts?: Record<string, KnowledgeFact>;
  knowledgeContradictions?: Record<string, KnowledgeContradiction>;
  knowledgePatterns?: Record<string, KnowledgePattern>;
  knowledgeStrategies?: Record<string, KnowledgeStrategy>;
  missionKnowledgeSnapshots?: Record<string, MissionKnowledgeSnapshot[]>;
  knowledgeSnapshots?: KnowledgeSnapshot[];
  // Stage 14 extensions
  decisions?: Record<string, Decision>;
  decisionContexts?: Record<string, DecisionContext>;
  decisionRecommendations?: Record<string, DecisionRecommendation>;
  postDecisionRecords?: Record<string, PostDecisionRecord>;
  decisionEvaluations?: Record<string, DecisionEvaluation>;
  // Stage 15 extensions
  actionAuditRecords?: Record<string, ActionAuditRecord>;
  actionResults?: Record<string, ActionResult>;
  persistedActionRequests?: Record<string, ActionRequest>;
  // Stage 16 extensions
  connectors?: Record<string, import('./connectorFabric').Connector>;
  connectorAuditEvents?: import('./connectorFabric').ConnectorLifecycleEvent[];
  agentCapabilityGrants?: Record<string, import('./connectorFabric').AgentCapabilityGrant>;
  missionCapabilityGrants?: Record<string, import('./connectorFabric').MissionCapabilityGrant>;
  // Stage 19 extensions
  triggers?: Record<string, import('./eventTrigger').Trigger>;
  reactionProposals?: Record<string, import('./eventTrigger').ReactionProposal>;
  reactionResults?: Record<string, import('./eventTrigger').ReactionExecutionResult>;
  // Stage 20 extensions
  policies?: Record<string, import('./policyIntelligence').Policy>;
  policyProposals?: Record<string, import('./policyIntelligence').PolicyProposal>;
  policyActivations?: Record<string, import('./policyIntelligence').PolicyActivationRecord>;
  policyRollbacks?: Record<string, import('./policyIntelligence').PolicyRollbackRecord>;
  policyShadows?: Record<string, import('./policyIntelligence').PolicyShadowRecord>;
  policyDrifts?: Record<string, import('./policyIntelligence').PolicyDriftRecord>;
  policyConflicts?: Record<string, import('./policyIntelligence').PolicyConflictRecord>;
  // Stage 21 extensions
  governanceDecisions?: Record<string, import('./governanceControlPlane').GovernanceDecision>;
  policySnapshots?: Record<string, import('./governanceControlPlane').PolicySnapshot>;
  // Stage 22 extensions
  auditEvents?: Record<string, import('./operationalAudit').OperationalAuditEvent>;
  // Stage 23 extensions
  recoveryControlDecisions?: Record<string, import('./recoveryControl').RecoveryControlDecision>;
  recoveryControlRequests?: Record<string, import('./recoveryControl').RecoveryControlRequest>;
  recoveryControlLeases?: Record<string, import('./recoveryControl').RecoveryControlLease>;
}

/**
 * 7. Recovery Action Decision
 */
export interface RecoveryActionDecision {
  actionId: string;
  previousStatus: string;
  recoveryClassification: ActionRecoveryClassification;
  actionToTake:
    | 'RESUME_IMMEDIATELY'
    | 'HOLD_FOR_APPROVAL'
    | 'MARK_FAILED'
    | 'REVALIDATE_IDEMPOTENCY'
    | 'PRESERVE_SUCCEEDED'
    | 'SKIP';
  reason: string;
  idempotencyKey?: string;
}

/**
 * 8. Goal Recovery Result
 */
export interface GoalRecoveryResult {
  goalId: string;
  previousStatus: string;
  recoveredStatus: string;
  planVersion: number;
  executableFrontier: string[]; // Action IDs that are ready to run next
  actionDecisions: RecoveryActionDecision[];
  approvalsPending: string[];
  resumed: boolean;
  summary: string;
}

/**
 * 9. Scheduler Job Specification
 */
export type SchedulerJobType =
  | 'IMMEDIATE_ACTION'
  | 'DELAYED_ACTION'
  | 'RETRY_BACKOFF'
  | 'DEPENDENCY_TRIGGERED'
  | 'APPROVAL_CONTINUATION';

export interface SchedulerJob {
  jobId: string;
  goalId: string;
  planId: string;
  actionId: string;
  type: SchedulerJobType;
  scheduledFor: string;
  status: 'PENDING' | 'RUNNING' | 'COMPLETED' | 'CANCELLED';
  attempt: number;
  backoffMs?: number;
  createdAt: string;
}
