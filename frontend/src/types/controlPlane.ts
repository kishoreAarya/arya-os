/**
 * AryaOS V1 — Stage 24: Mission Operations Control Plane
 * Phase 1: Control-Plane Domain Contract
 *
 * Strict read-oriented domain projections over existing AryaOS authorities:
 * - Stage 08: Autonomous Task Orchestration
 * - Stage 09: Durable Persistence, Journaling & Crash Recovery
 * - Stage 10: Multi-Agent Coordination & Resource Governance
 * - Stage 11: Agent Evaluation & Learning
 * - Stage 12: Mission Control
 * - Stage 13: Strategic Knowledge Graph
 * - Stage 14: Decision Intelligence
 * - Stage 15: Universal Action Bus
 * - Stage 16 & 17: Connector Fabric & Real Activation
 * - Stage 18 & 19: External Event Ingestion & Reaction Engine
 * - Stage 20: Policy Intelligence
 * - Stage 21: Governed Policy Control Plane
 * - Stage 22: Operational Truth & Causal Audit
 * - Stage 23: Governed Recovery Control Plane
 *
 * ABSOLUTE ARCHITECTURAL RULES:
 * 1. CONTRACT DEFINITION ONLY: Zero execution, zero authorization, zero policy mutation.
 * 2. PROJECTION ONLY: Does NOT replace or duplicate underlying domain entities.
 * 3. EXPLICIT UNKNOWN: Missing or unconfirmed data must remain 'UNKNOWN'; no synthetic defaults.
 * 4. REUSE CANONICAL TYPES: All domain lifecycles, epistemic states, and outcomes are reused directly.
 * 5. DETERMINISM: Zero Math.random(), zero Date.now(), zero network calls in type contracts.
 */

import {
  OperationalLifecycleState,
  EpistemicStatus,
  CausalNodeType,
  CausalEdgeType,
} from './operationalAudit';

import {
  MissionStatus,
  MissionPriority,
  MissionProgress,
} from './missionControl';

import {
  GovernanceDecisionType,
  GovernanceActor,
  AuthorityCheckStatus,
  HumanApprovalCheckStatus,
  StalenessStatus,
} from './governanceControlPlane';

import {
  RecoveryLifecycleState,
  RecoveryControlLifecycleState,
  RecoveryLifecycleProgressionState,
  RecoveryLifecycleTerminalState,
  RecoveryAction,
  FailureClassification,
  IdempotencyClassification,
  RecoveryOutcome,
  DeclarativeCompensationPlan,
  RECOVERY_PROGRESSION_STATES,
  RECOVERY_TERMINAL_STATES,
  FAILURE_CLASSIFICATIONS,
  RECOVERY_ACTIONS,
} from './recoveryControl';

import { ActionRiskLevel } from './actionBus';

// Re-export canonical domain types so consumers have a unified, consistent contract import
export type {
  OperationalLifecycleState,
  EpistemicStatus,
  CausalNodeType,
  CausalEdgeType,
  MissionStatus,
  MissionPriority,
  MissionProgress,
  GovernanceDecisionType,
  GovernanceActor,
  AuthorityCheckStatus,
  HumanApprovalCheckStatus,
  StalenessStatus,
  RecoveryLifecycleState,
  RecoveryControlLifecycleState,
  RecoveryLifecycleProgressionState,
  RecoveryLifecycleTerminalState,
  RecoveryAction,
  FailureClassification,
  IdempotencyClassification,
  RecoveryOutcome,
  DeclarativeCompensationPlan,
  ActionRiskLevel,
};

export {
  RECOVERY_PROGRESSION_STATES,
  RECOVERY_TERMINAL_STATES,
  FAILURE_CLASSIFICATIONS,
  RECOVERY_ACTIONS,
};

// ============================================================================
// 1. Canonical Operation Lifecycle Distinctions (16 Canonical States)
// ============================================================================

/**
 * 16 Canonical Lifecycle States representing the full progression of operations:
 * REQUESTED != PLANNED != AUTHORIZED != DISPATCHED != EXECUTING != OBSERVED != RECONCILED.
 * Prevents collapsing operational intent into observed truth.
 */
export const CANONICAL_TIMELINE_STATES = [
  'REQUESTED',
  'PLANNED',
  'TRIGGERED',
  'PROPOSED',
  'GOVERNED',
  'AUTHORIZED',
  'DISPATCHED',
  'EXECUTING',
  'SUCCEEDED',
  'FAILED',
  'REJECTED',
  'DENIED',
  'DEFERRED',
  'PAUSED',
  'UNKNOWN',
  'RECONCILED',
] as const;

export type CanonicalTimelineState = (typeof CANONICAL_TIMELINE_STATES)[number];

// ============================================================================
// 2. Mission Summary Projection
// ============================================================================

export interface MissionSummary {
  readonly missionId: string;
  readonly goalId: string | 'UNKNOWN';
  readonly title?: string | 'UNKNOWN';
  readonly status: MissionStatus | 'UNKNOWN';
  readonly priority: MissionPriority | 'UNKNOWN';
  readonly progress: MissionProgress | 'UNKNOWN';
  readonly activeOperations: number | 'UNKNOWN';
  readonly blockedOperations: number | 'UNKNOWN';
  readonly pendingApprovals: number | 'UNKNOWN';
  readonly recoveryCount: number | 'UNKNOWN';
  readonly latestOperationalState: OperationalLifecycleState | 'UNKNOWN';
  readonly latestTruthState: EpistemicStatus | 'UNKNOWN';
  readonly latestCausalEvent: string | 'UNKNOWN';
  readonly policyVersion: number | 'UNKNOWN';
  readonly governanceState: GovernanceDecisionType | 'UNKNOWN';
  readonly riskLevel?: ActionRiskLevel | 'UNKNOWN';
  readonly updatedAt: string | 'UNKNOWN';
  readonly createdAt?: string | 'UNKNOWN';
}

// ============================================================================
// 3. Operation Summary Projection
// ============================================================================

export interface OperationSummary {
  readonly operationId: string;
  readonly missionId?: string | 'UNKNOWN';
  readonly goalId?: string | 'UNKNOWN';
  readonly actionId?: string | 'UNKNOWN';
  readonly title?: string | 'UNKNOWN';
  readonly status: OperationalLifecycleState | 'UNKNOWN';
  readonly truthState: EpistemicStatus | 'UNKNOWN';
  readonly epistemicState: EpistemicStatus;
  readonly riskLevel: ActionRiskLevel | 'UNKNOWN';
  readonly policySnapshotId?: string | 'UNKNOWN';
  readonly governanceDecisionId?: string | 'UNKNOWN';
  readonly connectorId?: string | 'UNKNOWN';
  readonly capabilityId?: string | 'UNKNOWN';
  readonly idempotencyKey?: string | 'UNKNOWN';
  readonly createdAt: number | string | 'UNKNOWN';
  readonly updatedAt: number | string | 'UNKNOWN';
  readonly causationId?: string | 'UNKNOWN';
  readonly correlationId?: string | 'UNKNOWN';
}

// ============================================================================
// 4. Operation Timeline Projection
// ============================================================================

export interface OperationTimelineEntry {
  readonly state: CanonicalTimelineState | OperationalLifecycleState;
  readonly timestamp: number | 'UNKNOWN';
  readonly source: string | 'UNKNOWN';
  readonly epistemicState: EpistemicStatus;
  readonly eventId?: string | 'UNKNOWN';
  readonly causationId?: string | 'UNKNOWN';
  readonly correlationId?: string | 'UNKNOWN';
  readonly reason?: string | 'UNKNOWN';
  readonly metadata?: Readonly<Record<string, unknown>>;
}

export interface OperationTimeline {
  readonly operationId: string;
  readonly entries: readonly OperationTimelineEntry[];
  readonly currentState: CanonicalTimelineState | OperationalLifecycleState;
  readonly epistemicState: EpistemicStatus;
  readonly startedAt: number | 'UNKNOWN';
  readonly lastUpdatedAt: number | 'UNKNOWN';
  readonly isTerminal: boolean;
}

// ============================================================================
// 5. Governance Summary Projection (Stage 21)
// ============================================================================

export interface GovernanceSummary {
  readonly policySnapshotId: string | 'UNKNOWN';
  readonly policyId?: string | 'UNKNOWN';
  readonly policyVersion: number | 'UNKNOWN';
  readonly requestId: string;
  readonly decisionId?: string | 'UNKNOWN';
  readonly decision: GovernanceDecisionType | 'UNKNOWN';
  readonly authorityState: AuthorityCheckStatus | 'UNKNOWN';
  readonly stalenessState: StalenessStatus | 'UNKNOWN';
  readonly connectorAuthorityState: boolean | 'UNKNOWN';
  readonly actionAuthorizationState: boolean | 'UNKNOWN';
  readonly humanApprovalState: HumanApprovalCheckStatus | 'UNKNOWN';
  readonly missionConstraintState: boolean | 'UNKNOWN';
  readonly explanation?: string | 'UNKNOWN';
  readonly evaluatedAt: number | 'UNKNOWN';
  readonly actor?: GovernanceActor;
  readonly epistemicStatus?: EpistemicStatus;
}

// ============================================================================
// 6. Approval Summary Projection
// ============================================================================

export const APPROVAL_PROJECTION_STATES = [
  'PENDING',
  'APPROVED',
  'REJECTED',
  'EXPIRED',
  'INVALID',
  'UNKNOWN',
] as const;

export type ApprovalProjectionState = (typeof APPROVAL_PROJECTION_STATES)[number];

export interface ApprovalSummary {
  readonly approvalId: string;
  readonly requestId?: string | 'UNKNOWN';
  readonly actorId?: string | 'UNKNOWN';
  readonly riskLevel: ActionRiskLevel | 'UNKNOWN';
  readonly policySnapshotId?: string | 'UNKNOWN';
  readonly policyVersion?: number | 'UNKNOWN';
  readonly approvalState: ApprovalProjectionState;
  readonly expiresAt: number | string | 'UNKNOWN';
  readonly createdAt: number | string | 'UNKNOWN';
  readonly approvedAt?: number | string | 'UNKNOWN';
  readonly rejectedAt?: number | string | 'UNKNOWN';
  readonly actionTitle?: string | 'UNKNOWN';
  readonly reason?: string | 'UNKNOWN';
}

// ============================================================================
// 7. Recovery Summary Projection (Stage 23)
// ============================================================================

export interface RecoverySummary {
  readonly recoveryPlanId: string | 'UNKNOWN';
  readonly originalOperationId: string;
  readonly failureClassification: FailureClassification | 'UNKNOWN';
  readonly currentTruthState: EpistemicStatus | 'UNKNOWN';
  readonly proposedRecoveryAction: RecoveryAction | 'UNKNOWN';
  readonly riskLevel: ActionRiskLevel | 'UNKNOWN';
  readonly idempotencyAssessment: IdempotencyClassification | 'UNKNOWN';
  readonly requiredAuthority: readonly string[] | 'UNKNOWN';
  readonly governanceDecisionId?: string | 'UNKNOWN';
  readonly approvalRequirement: {
    readonly required: boolean;
    readonly humanOperatorRequired: boolean;
    readonly approvedBy?: string;
  } | 'UNKNOWN';
  readonly reconciliationRequirement: {
    readonly required: boolean;
    readonly postCompensationVerification?: boolean;
    readonly timeoutMs?: number;
  } | 'UNKNOWN';
  readonly compensationPlan?: DeclarativeCompensationPlan | 'UNKNOWN';
  readonly expectedOutcome?: RecoveryOutcome | 'UNKNOWN';
  readonly expiresAt: number | 'UNKNOWN';
  readonly causationId: string | 'UNKNOWN';
  readonly correlationId: string | 'UNKNOWN';
  readonly lifecycleState: RecoveryLifecycleState | RecoveryControlLifecycleState | 'UNKNOWN';
  readonly retryCount?: number | 'UNKNOWN';
  readonly recoveryDepth?: number | 'UNKNOWN';
}

// ============================================================================
// 8. Causal Trace Summary Projection (Stage 22)
// ============================================================================

export const EVIDENCE_STATES = [
  'VERIFIED',
  'PENDING',
  'MISSING_EVIDENCE',
  'UNKNOWN',
] as const;

export type EvidenceState = (typeof EVIDENCE_STATES)[number];

export interface CausalTraceNodeSummary {
  readonly nodeId: string;
  readonly domain: string | 'UNKNOWN';
  readonly entityId: string | 'UNKNOWN';
  readonly nodeType: CausalNodeType;
  readonly label: string;
  readonly state: OperationalLifecycleState | 'UNKNOWN';
  readonly epistemicState: EpistemicStatus;
  readonly timestamp: number | 'UNKNOWN';
  readonly causationId?: string | 'UNKNOWN';
  readonly correlationId?: string | 'UNKNOWN';
  readonly source: string | 'UNKNOWN';
  readonly evidenceState: EvidenceState;
  readonly metadata?: Readonly<Record<string, unknown>>;
}

export interface CausalTraceEdgeSummary {
  readonly fromNodeId: string;
  readonly toNodeId: string;
  readonly edgeType: CausalEdgeType;
  readonly timestamp: number | 'UNKNOWN';
}

export interface CausalTraceSummary {
  readonly operationId: string;
  readonly rootNodeId: string;
  readonly nodes: readonly CausalTraceNodeSummary[];
  readonly edges: readonly CausalTraceEdgeSummary[];
  readonly maxDepthReached: number;
  readonly isTruncated: boolean;
  readonly hasCycles: boolean;
  readonly hasMissingEvidence: boolean;
}

// ============================================================================
// 9. System Health Summary Projection
// ============================================================================

export const SUBSYSTEM_HEALTH_STATUSES = [
  'HEALTHY',
  'DEGRADED',
  'FAILED',
  'UNKNOWN',
] as const;

export type SubsystemHealthStatus = (typeof SUBSYSTEM_HEALTH_STATUSES)[number];

export interface SubsystemHealthRecord {
  readonly status: SubsystemHealthStatus;
  readonly message?: string;
  readonly lastCheckedAt: number | string | 'UNKNOWN';
  readonly metrics?: Readonly<Record<string, unknown>>;
}

export interface SystemHealthSummary {
  readonly execution: SubsystemHealthRecord;
  readonly providers: SubsystemHealthRecord;
  readonly connectors: SubsystemHealthRecord;
  readonly persistence: SubsystemHealthRecord;
  readonly governance: SubsystemHealthRecord;
  readonly recovery: SubsystemHealthRecord;
  readonly eventIngestion: SubsystemHealthRecord;
  readonly missions: SubsystemHealthRecord;
  readonly actionBus: SubsystemHealthRecord;
  readonly overallStatus: SubsystemHealthStatus;
  readonly isDurableStorage: boolean;
}

// ============================================================================
// 10. Control Plane Snapshot (Top-Level Read Projection)
// ============================================================================

export interface ControlPlaneSnapshot {
  readonly snapshotId: string;
  readonly generatedAt: number;
  readonly sourceVersion?: string | number | 'UNKNOWN';
  readonly missions: readonly MissionSummary[];
  readonly operations: readonly OperationSummary[];
  readonly approvals: readonly ApprovalSummary[];
  readonly governance: readonly GovernanceSummary[];
  readonly recovery: readonly RecoverySummary[];
  readonly causalTraces: readonly CausalTraceSummary[];
  readonly systemHealth: SystemHealthSummary;
  readonly requestId?: string | 'UNKNOWN';
  readonly actorId?: string | 'UNKNOWN';
  readonly correlationId?: string | 'UNKNOWN';
}
