/**
 * AryaOS V1 — Stage 22: System Observability, Causal Audit & Operational Truth
 *
 * Domain contracts for the unified Operational Event & Causal Audit Fabric.
 * Observes, records, correlates, and reconstructs runtime causality from origin to outcome.
 *
 * CRITICAL ARCHITECTURAL AXIOMS:
 * - AUDIT EVENT != AUTHORITY
 * - AUDIT EVENT != PERMISSION
 * - AUDIT EVENT != KNOWLEDGE FACT
 * - STAGE 22 DOES NOT EXECUTE ACTIONS OR AUTHORIZE CAPABILITIES
 * - OPERATIONAL INTENT != OPERATIONAL TRUTH
 *   (REQUESTED != PLANNED != AUTHORIZED != DISPATCHED != EXECUTED != OBSERVED != RECONCILED)
 * - ACTION BUS DISPATCH != EXTERNAL SUCCESS
 *   (If external confirmation is unavailable: status = UNKNOWN)
 */

import { ActionRiskLevel } from './actionBus';
import { GovernanceActor, GovernanceDecisionType } from './governanceControlPlane';

// ============================================================================
// 1. Constants & Security Limits
// ============================================================================

export const MAX_OBJECT_DEPTH = 5;
export const MAX_KEYS_PER_OBJECT = 50;
export const MAX_CAUSAL_DEPTH = 10;
export const MAX_CAUSAL_NODES = 100;
export const DEFAULT_AUDIT_TTL_MS = 300000; // 5 minutes

// ============================================================================
// 2. Operational Lifecycle States
// ============================================================================

export type OperationalLifecycleState =
  | 'RECEIVED'
  | 'VALIDATED'
  | 'PLANNED'
  | 'TRIGGERED'
  | 'PROPOSED'
  | 'GOVERNED'
  | 'AUTHORIZED'
  | 'DISPATCHED'
  | 'EXECUTING'
  | 'SUCCEEDED'
  | 'FAILED'
  | 'REJECTED'
  | 'DENIED'
  | 'DEFERRED'
  | 'PAUSED'
  | 'CANCELLED'
  | 'UNKNOWN'
  | 'RECONCILED';

export const TERMINAL_LIFECYCLE_STATES: ReadonlySet<OperationalLifecycleState> = new Set([
  'SUCCEEDED',
  'FAILED',
  'REJECTED',
  'DENIED',
  'DEFERRED',
  'PAUSED',
  'CANCELLED',
  'UNKNOWN',
  'RECONCILED',
]);

// ============================================================================
// 3. Epistemic Status (Evidence Level)
// ============================================================================

export type EpistemicStatus =
  | 'OBSERVED'    // Directly verified empirical evidence from authenticated boundary
  | 'CONFIRMED'   // Corroborated by independent post-execution state observation
  | 'INFERRED'    // Deductions derived from verified intermediate states
  | 'PROJECTED'   // Counterfactual evaluation or future simulation
  | 'UNKNOWN';    // Missing or ambiguous external confirmation (NEVER auto-promoted)

// ============================================================================
// 4. Failure Boundaries
// ============================================================================

export type FailureBoundaryType =
  | 'POLICY_DENIED'             // Stage 20/21 policy evaluated to DENY
  | 'AUTHORIZATION_DENIED'      // Stage 16/21 authority intersection failed closed
  | 'HUMAN_APPROVAL_PENDING'    // Stage 21 awaiting operator review
  | 'CONNECTOR_REVOKED'         // Stage 16 connector in invalid/unhealthy state
  | 'CONNECTOR_PERMISSION_DENIED' // Stage 16 missing capability grant
  | 'ACTION_TIMEOUT'            // Stage 15 Action Bus execution exceeded timeout
  | 'PROVIDER_FAILURE'          // Stage 07 provider execution error
  | 'NETWORK_FAILURE'           // Downstream transport failure
  | 'EXTERNAL_RESULT_UNKNOWN'   // Dispatched but no external confirmation received
  | 'RECONCILIATION_FAILURE'    // Post-execution state reconciliation mismatch
  | 'STALE_POLICY'              // In-flight policy registry version changed
  | 'STALE_APPROVAL'            // Approval token snapshot misaligned
  | 'TRIGGER_DISABLED'          // Stage 19 trigger suspended/disabled
  | 'MISSION_PAUSED'            // Stage 12 mission paused
  | 'UNKNOWN_BOUNDARY';

export interface FailureBoundaryDetail {
  boundary: FailureBoundaryType;
  stoppingStage: string;
  reason: string;
  remedialAction?: string;
  evidenceId?: string;
}

// ============================================================================
// 5. Canonical Operational Audit Event
// ============================================================================

export type OperationalAuditEventType =
  | 'REQUEST_RECEIVED'
  | 'REQUEST_VALIDATED'
  | 'GOAL_ORCHESTRATED'
  | 'TRIGGER_EVALUATED'
  | 'REACTION_PROPOSED'
  | 'POLICY_EVALUATED'
  | 'GOVERNANCE_DECIDED'
  | 'AUTHORITY_CHECKED'
  | 'ACTION_DISPATCHED'
  | 'ACTION_EXECUTED'
  | 'OBSERVATION_RECORDED'
  | 'STATE_RECONCILED'
  | 'OPERATION_SUCCEEDED'
  | 'OPERATION_FAILED'
  | 'OPERATION_DENIED'
  | 'OPERATION_PAUSED'
  | 'OPERATION_DEFERRED'
  | 'OPERATION_UNKNOWN'
  | 'EVENT_CORRECTED';

export interface OperationalAuditEvent {
  // Identity & Causality
  eventId: string;
  operationId: string;
  correlationId: string;
  causationId?: string;
  parentOperationId?: string;
  timestamp: number;

  // Taxonomy & Actor
  eventType: OperationalAuditEventType;
  actor: GovernanceActor;
  sourceSystem: string;

  // Cross-Stage Context IDs
  missionId?: string;
  goalId?: string;
  planId?: string;
  triggerId?: string;
  triggerVersion?: number;
  reactionId?: string;
  proposalId?: string;
  policyId?: string;
  policyVersion?: number;
  policySnapshotId?: string;
  governanceDecisionId?: string;
  governanceDecision?: GovernanceDecisionType;
  authorizationId?: string;
  actionId?: string;
  capabilityId?: string;
  connectorId?: string;
  providerId?: string;
  resultId?: string;
  observationId?: string;

  // State & Truth
  lifecycleState: OperationalLifecycleState;
  epistemicStatus: EpistemicStatus;
  riskLevel?: ActionRiskLevel;

  // Failure & Semantics
  failureBoundary?: FailureBoundaryDetail;
  reason?: string;
  parameters?: Record<string, unknown>;
  output?: Record<string, unknown>;

  // Integrity & Provenance
  evidenceReferences: string[];
  payloadFingerprint: string;
  schemaVersion: number;
}

// ============================================================================
// 6. Causal Graph & Relationships
// ============================================================================

export type CausalNodeType =
  | 'USER_REQUEST'
  | 'EXTERNAL_EVENT'
  | 'MISSION'
  | 'GOAL'
  | 'TRIGGER'
  | 'REACTION'
  | 'POLICY'
  | 'GOVERNANCE_DECISION'
  | 'AUTHORIZATION'
  | 'ACTION'
  | 'CONNECTOR'
  | 'PROVIDER'
  | 'RESULT'
  | 'OBSERVATION'
  | 'MEMORY_UPDATE'
  | 'KNOWLEDGE_UPDATE'
  | 'MISSING_EVIDENCE';

export type CausalEdgeType =
  | 'CAUSED_BY'
  | 'TRIGGERED'
  | 'PROPOSED'
  | 'GOVERNED_BY'
  | 'AUTHORIZED_BY'
  | 'DISPATCHED_TO'
  | 'RESULTED_IN'
  | 'RECONCILED_TO'
  | 'OBSERVED_AS'
  | 'UPDATED'
  | 'PARENT_OF';

export interface CausalNode {
  nodeId: string;
  nodeType: CausalNodeType;
  label: string;
  timestamp: number;
  stageSource: string;
  status: OperationalLifecycleState;
  epistemicStatus: EpistemicStatus;
  metadata?: Record<string, unknown>;
}

export interface CausalEdge {
  fromNodeId: string;
  toNodeId: string;
  edgeType: CausalEdgeType;
  label?: string;
  timestamp: number;
}

export interface CausalGraph {
  operationId: string;
  rootNodeId: string;
  nodes: CausalNode[];
  edges: CausalEdge[];
  maxDepthReached: number;
  isTruncated: boolean;
  hasCycles: boolean;
}

// ============================================================================
// 7. Operation Trace (Reconstructed Audit Trace)
// ============================================================================

export interface CausalTraceStep {
  stepIndex: number;
  stageName: string;
  nodeType: CausalNodeType;
  referenceId: string;
  timestamp: number;
  status: OperationalLifecycleState;
  epistemicStatus: EpistemicStatus;
  description: string;
  evidenceId?: string;
  isMissingEvidence?: boolean;
}

export interface OperationTrace {
  operationId: string;
  correlationId: string;
  causationId?: string;
  parentOperationId?: string;
  rootOrigin: {
    originType: string;
    originId: string;
    actor: GovernanceActor;
    timestamp: number;
  };
  terminalStatus: OperationalLifecycleState;
  epistemicStatus: EpistemicStatus;
  isCompleted: boolean;
  totalDurationMs: number;
  steps: CausalTraceStep[];
  causalGraph: CausalGraph;
  failureBoundary?: FailureBoundaryDetail;
  deterministicExplanation: string;
  evidenceLedger: string[];
}

// ============================================================================
// 8. Deterministic Observability Metrics
// ============================================================================

export interface OperationalMetrics {
  totalOperations: number;
  activeOperations: number;
  succeededOperations: number;
  failedOperations: number;
  deniedOperations: number;
  deferredOperations: number;
  pausedOperations: number;
  unknownResultOperations: number;
  averageOperationDurationMs: number;
  averageGovernanceLatencyMs: number;
  averageActionBusLatencyMs: number;
  averageReconciliationLatencyMs: number;
  totalRetriesRecorded: number;
  staleDecisionsDetected: number;
  epistemicBreakdown: {
    observedCount: number;
    confirmedCount: number;
    inferredCount: number;
    projectedCount: number;
    unknownCount: number;
  };
  computedAt: number;
}
