/**
 * AryaOS V1 — Stage 23: Resilient Autonomous Operations & Recovery Control
 * Core Recovery Contracts & Schema Definitions
 */

// ============================================================================
// 1. Failure Classification (13 Canonical Categories)
// ============================================================================
export const FAILURE_CLASSIFICATIONS = [
  'TRANSIENT',
  'PERMANENT',
  'AUTHORIZATION',
  'PERMISSION',
  'POLICY',
  'STALE_STATE',
  'UNKNOWN_EXTERNAL_STATE',
  'PARTIAL_EXECUTION',
  'RECONCILIATION',
  'RESOURCE',
  'DEPENDENCY',
  'SYSTEM_INTERRUPTION',
  'HUMAN_REQUIRED',
] as const;

export type FailureClassification = (typeof FAILURE_CLASSIFICATIONS)[number];

// ============================================================================
// 2. Recovery Action (11 Safe Next State Outcomes)
// ============================================================================
export const RECOVERY_ACTIONS = [
  'RETRY',
  'RESUME',
  'ROLLBACK',
  'COMPENSATE',
  'RECONCILE',
  'WAIT',
  'REQUIRE_APPROVAL',
  'PAUSE',
  'ABORT',
  'ESCALATE',
  'UNKNOWN',
] as const;

export type RecoveryAction = (typeof RECOVERY_ACTIONS)[number];

// ============================================================================
// 3. Recovery Lifecycle State (Progression & Terminal)
// ============================================================================
export const RECOVERY_PROGRESSION_STATES = [
  'DETECTED',
  'CLASSIFIED',
  'PROPOSED',
  'GOVERNED',
  'APPROVED',
  'READY',
  'DISPATCHED',
  'VERIFIED',
  'COMPLETED',
] as const;

export type RecoveryLifecycleProgressionState = (typeof RECOVERY_PROGRESSION_STATES)[number];

export const RECOVERY_TERMINAL_STATES = [
  'ABORTED',
  'REJECTED',
  'EXPIRED',
  'UNKNOWN',
  'ESCALATED',
] as const;

export type RecoveryLifecycleTerminalState = (typeof RECOVERY_TERMINAL_STATES)[number];

export type RecoveryLifecycleState =
  | RecoveryLifecycleProgressionState
  | RecoveryLifecycleTerminalState;

// ============================================================================
// 4. Idempotency Classification
// ============================================================================
export const IDEMPOTENCY_CLASSIFICATIONS = [
  'READ_ONLY',
  'IDEMPOTENT',
  'CONDITIONALLY_IDEMPOTENT',
  'NON_IDEMPOTENT',
  'UNKNOWN',
] as const;

export type IdempotencyClassification = (typeof IDEMPOTENCY_CLASSIFICATIONS)[number];

// ============================================================================
// 5. Compensation Availability
// ============================================================================
export const COMPENSATION_AVAILABILITIES = [
  'ROLLBACK_AVAILABLE',
  'COMPENSATION_AVAILABLE',
  'NO_COMPENSATION_AVAILABLE',
  'COMPENSATION_UNKNOWN',
] as const;

export type CompensationAvailability = (typeof COMPENSATION_AVAILABILITIES)[number];

// ============================================================================
// 6. Recovery Constants & Bounds
// ============================================================================
export const MAX_RECOVERY_DEPTH = 3;
export const MAX_AUTOMATIC_RETRIES = 2;
export const MAX_RECOVERY_OBJECT_DEPTH = 5;
export const MAX_RECOVERY_KEYS_PER_OBJECT = 50;

// ============================================================================
// 7. Domain Data Contracts (Pure Immutable Data Structures)
// ============================================================================

export interface RecoveryPlanApprovalRequirement {
  readonly required: boolean;
  readonly approvalType?: string;
  readonly approvedBy?: string;
  readonly approvedAt?: number;
}

export interface RecoveryPlanReconciliationRequirement {
  readonly required: boolean;
  readonly probeType?: string;
  readonly timeoutMs?: number;
}

export interface RecoveryPlanCompensationPlan {
  readonly availability: CompensationAvailability;
  readonly compensatingActionType?: string;
  readonly targetSystem?: string;
  readonly parameters?: Readonly<Record<string, unknown>>;
}

export interface RecoveryPlan {
  readonly recoveryPlanId: string;
  readonly originalOperationId: string;
  readonly failureClassification: FailureClassification;
  readonly currentTruthState: string;
  readonly proposedRecoveryAction: RecoveryAction;
  readonly riskLevel: 'LOW' | 'MEDIUM' | 'HIGH' | 'CRITICAL';
  readonly idempotencyAssessment: IdempotencyClassification;
  readonly requiredAuthority: readonly string[];
  readonly governanceDecisionId?: string;
  readonly approvalRequirement: RecoveryPlanApprovalRequirement;
  readonly reconciliationRequirement: RecoveryPlanReconciliationRequirement;
  readonly compensationPlan: RecoveryPlanCompensationPlan;
  readonly expectedOutcome: string;
  readonly expiry: number;
  readonly causationId: string;
  readonly correlationId: string;
  readonly createdAt: number;
  readonly lifecycleState: RecoveryLifecycleState;
  readonly evidenceReferences?: readonly string[];
  readonly metadata?: Readonly<Record<string, unknown>>;
}

export interface RecoveryAttemptRecord {
  readonly attemptId: string;
  readonly recoveryPlanId: string;
  readonly originalOperationId: string;
  readonly attemptNumber: number;
  readonly recoveryDepth: number;
  readonly lifecycleState: RecoveryLifecycleState;
  readonly proposedAction: RecoveryAction;
  readonly idempotencyClassification: IdempotencyClassification;
  readonly governanceDecisionId?: string;
  readonly approvalReference?: string;
  readonly causationId: string;
  readonly correlationId: string;
  readonly startedAt: number;
  readonly completedAt?: number;
  readonly outcomeReference?: string;
  readonly metadata?: Readonly<Record<string, unknown>>;
}

export interface RecoverySafetyAssessment {
  readonly idempotencyClassification: IdempotencyClassification;
  readonly duplicateSideEffectRisk: 'NONE' | 'LOW' | 'MEDIUM' | 'HIGH' | 'CRITICAL';
  readonly reconciliationRequirement: boolean;
  readonly partialExecutionDetected: boolean;
  readonly completedSteps: readonly string[];
  readonly incompleteSteps: readonly string[];
  readonly compensationAvailability: CompensationAvailability;
  readonly rollbackAvailability: boolean;
  readonly retryPermitted: boolean;
  readonly humanApprovalRequired: boolean;
  readonly safetyRationale: string;
  readonly assessmentTimestamp: number;
}

// ============================================================================
// 8. Phase 2: Evidence-Based Failure Classification Contracts
// ============================================================================

export const DISPATCH_STATES = [
  'NOT_DISPATCHED',
  'DISPATCH_ATTEMPTED',
  'DISPATCHED',
  'EXECUTING',
  'EXTERNAL_CONFIRMATION_RECEIVED',
  'EXTERNAL_CONFIRMATION_ABSENT',
  'RECONCILIATION_COMPLETED',
  'RECONCILIATION_FAILED',
] as const;

export type DispatchState = (typeof DISPATCH_STATES)[number];

export const FAILURE_REASON_CODES = [
  'TRANSIENT_NETWORK_FAILURE',
  'PERMANENT_CLIENT_REJECTION',
  'AUTHORIZATION_DENIED',
  'CONNECTOR_PERMISSION_REVOKED',
  'POLICY_DENIED',
  'STALE_AUTHORITY',
  'EXTERNAL_CONFIRMATION_ABSENT',
  'PARTIAL_WORKFLOW_COMPLETION',
  'RECONCILIATION_FAILED',
  'RESOURCE_EXHAUSTED',
  'DEPENDENCY_UNAVAILABLE',
  'SYSTEM_INTERRUPTION',
  'HUMAN_APPROVAL_REQUIRED',
  'AMBIGUOUS_EVIDENCE_SAFE_FALLBACK',
] as const;

export type FailureReasonCode = (typeof FAILURE_REASON_CODES)[number];

export interface ClassificationEvidence {
  readonly operationId: string;
  readonly causationId: string;
  readonly correlationId: string;
  readonly lifecycleState?: string;
  readonly epistemicStatus?: string;
  readonly dispatchState: DispatchState;
  readonly httpStatus?: number;
  readonly providerErrorCategory?: string;
  readonly connectorStatus?: string;
  readonly authorizationResult?: {
    readonly authorized: boolean;
    readonly reason?: string;
  };
  readonly permissionResult?: {
    readonly granted: boolean;
    readonly revoked?: boolean;
    readonly reason?: string;
  };
  readonly policyResult?: {
    readonly decision: string;
    readonly matchedPolicyId?: string;
    readonly reason?: string;
  };
  readonly staleStateEvidence?: {
    readonly isStale: boolean;
    readonly reason?: string;
  };
  readonly timeoutEvidence?: {
    readonly timedOut: boolean;
    readonly timeoutMs?: number;
    readonly phase?: 'PRE_DISPATCH' | 'POST_DISPATCH';
  };
  readonly cancellationEvidence?: {
    readonly cancelled: boolean;
    readonly reason?: string;
  };
  readonly dependencyState?: {
    readonly satisfied: boolean;
    readonly missingDependencies?: readonly string[];
  };
  readonly resourceExhaustionEvidence?: {
    readonly exhausted: boolean;
    readonly resourceType?: string;
  };
  readonly partialExecutionEvidence?: {
    readonly completedSteps: readonly string[];
    readonly failedStep?: string;
    readonly pendingSteps: readonly string[];
  };
  readonly reconciliationEvidence?: {
    readonly attempted: boolean;
    readonly matched: boolean;
    readonly discrepancies?: readonly string[];
  };
  readonly humanInterventionRequired?: boolean;
  readonly evidenceReferences?: readonly string[];
  readonly metadata?: Readonly<Record<string, unknown>>;
}

export interface ClassificationResult {
  readonly classification: FailureClassification;
  readonly reasonCode: FailureReasonCode;
  readonly epistemicStatus: string;
  readonly explanation: string;
  readonly evidenceReferences: readonly string[];
  readonly causationId: string;
  readonly correlationId: string;
  readonly classifiedAt: number;
  readonly metadata?: Readonly<Record<string, unknown>>;
}

// ============================================================================
// 9. Phase 3: Recovery Plan Generation Contracts
// ============================================================================

export interface GenerateRecoveryPlanInput {
  readonly originalOperationId: string;
  readonly causationId: string;
  readonly correlationId: string;
  readonly classificationResult: ClassificationResult;
  readonly currentTruthState?: string;
  readonly dispatchState?: DispatchState;
  readonly idempotency?: IdempotencyClassification;
  readonly riskLevel?: 'LOW' | 'MEDIUM' | 'HIGH' | 'CRITICAL';
  readonly confirmedSuccess?: boolean;
  readonly partialExecution?: {
    readonly completedSteps: readonly string[];
    readonly failedStep?: string;
    readonly pendingSteps: readonly string[];
  };
  readonly compensationInfo?: {
    readonly availability: CompensationAvailability;
    readonly compensatingActionType?: string;
    readonly targetSystem?: string;
    readonly parameters?: Record<string, unknown>;
  };
  readonly expiryMs?: number;
  readonly metadata?: Readonly<Record<string, unknown>>;
}

// ============================================================================
// 10. Phase 4: Recovery Safety Analysis Contracts
// ============================================================================

export interface AssessRecoverySafetyInput {
  readonly plan: RecoveryPlan;
  readonly evidence?: ClassificationEvidence;
  readonly dispatchState?: DispatchState;
  readonly idempotency?: IdempotencyClassification;
  readonly conditionalConditionsMet?: boolean;
  readonly confirmedSuccess?: boolean;
  readonly externalConfirmationReceived?: boolean;
  readonly partialExecution?: {
    readonly completedSteps: readonly string[];
    readonly failedStep?: string;
    readonly pendingSteps: readonly string[];
  };
  readonly compensationAvailability?: CompensationAvailability;
  readonly rollbackAvailable?: boolean;
  readonly metadata?: Readonly<Record<string, unknown>>;
}

// ============================================================================
// 11. Phase 5: Reconciliation Service & Safe Probe Control Contracts
// ============================================================================

export const MAX_RECONCILIATION_ATTEMPTS = 3;

export const RECONCILIATION_LIFECYCLE_STATES = [
  'REQUIRED',
  'PLANNED',
  'GOVERNED',
  'READY',
  'PROBED',
  'VERIFIED',
] as const;

export type ReconciliationLifecycleState = (typeof RECONCILIATION_LIFECYCLE_STATES)[number];

export const RECONCILIATION_OUTCOMES = [
  'VERIFIED_SUCCESS',
  'VERIFIED_FAILURE',
  'STILL_UNKNOWN',
  'RECONCILIATION_UNAVAILABLE',
  'REJECTED',
  'EXPIRED',
  'FAILED',
] as const;

export type ReconciliationOutcome = (typeof RECONCILIATION_OUTCOMES)[number];

export const RECONCILIATION_EPISTEMIC_STATUSES = [
  'OBSERVED',
  'CONFIRMED',
  'INFERRED',
  'UNKNOWN',
] as const;

export type ReconciliationEpistemicStatus = (typeof RECONCILIATION_EPISTEMIC_STATUSES)[number];

export const RECONCILIATION_PROBE_INTENTS = [
  'READ_ONLY_STATUS_CHECK',
  'READ_ONLY_RESOURCE_GET',
  'READ_ONLY_IDEMPOTENCY_QUERY',
  'READ_ONLY_DIFF_CHECK',
] as const;

export type ReconciliationProbeIntent = (typeof RECONCILIATION_PROBE_INTENTS)[number];

export interface ReconciliationRequest {
  readonly reconciliationId: string;
  readonly originalOperationId: string;
  readonly recoveryPlanId: string;
  readonly targetCapability: string;
  readonly probeIntent: ReconciliationProbeIntent;
  readonly isReadOnly: true;
  readonly causationId: string;
  readonly correlationId: string;
  readonly timeoutMs: number;
  readonly attemptNumber: number;
  readonly maxAttempts: number;
  readonly evidenceReferences: readonly string[];
  readonly governanceRequired: boolean;
  readonly lifecycleState: ReconciliationLifecycleState;
  readonly probeParameters?: Readonly<Record<string, unknown>>;
  readonly metadata?: Readonly<Record<string, unknown>>;
}

export interface ReconciliationResultRecord {
  readonly reconciliationId: string;
  readonly originalOperationId: string;
  readonly recoveryPlanId: string;
  readonly outcome: ReconciliationOutcome;
  readonly epistemicStatus: ReconciliationEpistemicStatus;
  readonly observedExternalState?: Readonly<Record<string, unknown>>;
  readonly authoritativeEvidenceReferences: readonly string[];
  readonly probeOperationReference?: string;
  readonly note: string;
  readonly reconciledAt: number;
  readonly causationId: string;
  readonly correlationId: string;
  readonly attemptNumber: number;
  readonly metadata?: Readonly<Record<string, unknown>>;
}

export interface PlanReconciliationInput {
  readonly plan: RecoveryPlan;
  readonly safetyAssessment?: RecoverySafetyAssessment;
  readonly targetCapability?: string;
  readonly probeIntent?: ReconciliationProbeIntent;
  readonly probeParameters?: Record<string, unknown>;
  readonly timeoutMs?: number;
  readonly attemptNumber?: number;
  readonly maxAttempts?: number;
  readonly governanceRequired?: boolean;
  readonly metadata?: Readonly<Record<string, unknown>>;
}

// ============================================================================
// 12. Phase 6: Declarative Compensation & Reverse Operations Contracts
// ============================================================================

export const COMPENSATION_ELIGIBILITIES = [
  'COMPENSATION_ELIGIBLE',
  'COMPENSATION_REQUIRES_RECONCILIATION',
  'COMPENSATION_UNSAFE',
  'COMPENSATION_UNAVAILABLE',
  'COMPENSATION_NOT_REQUIRED',
  'COMPENSATION_REQUIRES_APPROVAL',
] as const;

export type CompensationEligibility = (typeof COMPENSATION_ELIGIBILITIES)[number];

export const COMPENSATION_TYPES = [
  'REVERSE_ACTION',
  'RESOURCE_CLEANUP',
  'STATE_CORRECTION',
  'COMPENSATING_TRANSACTION',
] as const;

export type CompensationType = (typeof COMPENSATION_TYPES)[number];

export const REVERSIBILITY_CLASSES = [
  'FULLY_REVERSIBLE',
  'PARTIALLY_REVERSIBLE',
  'IRREVERSIBLE',
  'COMPENSATABLE',
] as const;

export type ReversibilityClassification = (typeof REVERSIBILITY_CLASSES)[number];

export const COMPENSATION_LIFECYCLE_STATES = [
  'PROPOSED',
  'ASSESSED',
  'GOVERNED',
  'APPROVED',
  'READY',
  'DISPATCHED',
  'VERIFYING',
  'COMPLETED',
  'REJECTED',
  'ABORTED',
  'EXPIRED',
  'FAILED',
  'UNKNOWN',
  'ESCALATED',
] as const;

export type CompensationLifecycleState = (typeof COMPENSATION_LIFECYCLE_STATES)[number];

export interface CompensationApprovalRequirement {
  readonly required: boolean;
  readonly humanOperatorRequired: boolean;
  readonly approvedBy?: string;
  readonly approvedAt?: number;
  readonly governanceDecisionId?: string;
}

export interface CompensationReconciliationRequirement {
  readonly required: boolean;
  readonly postCompensationVerification: boolean;
  readonly timeoutMs?: number;
}

export interface DeclarativeCompensationPlan {
  readonly compensationId: string;
  readonly originalOperationId: string;
  readonly originalActionId?: string;
  readonly compensationType: CompensationType;
  readonly sourceCapability: string;
  readonly compensatingCapability: string;
  readonly sourceStateRequirement?: string;
  readonly targetState: string;
  readonly compensationParameters: Readonly<Record<string, unknown>>;
  readonly reversibilityClass: ReversibilityClassification;
  readonly idempotencyClass: IdempotencyClassification;
  readonly riskLevel: 'LOW' | 'MEDIUM' | 'HIGH' | 'CRITICAL';
  readonly requiredAuthority: readonly string[];
  readonly approvalRequirement: CompensationApprovalRequirement;
  readonly reconciliationRequirement: CompensationReconciliationRequirement;
  readonly idempotencyKey: string;
  readonly causationId: string;
  readonly correlationId: string;
  readonly expiresAt: number;
  readonly lifecycleState: CompensationLifecycleState;
  readonly recoveryDepth: number;
  readonly evidenceReferences?: readonly string[];
  readonly metadata?: Readonly<Record<string, unknown>>;
}

export interface CompensationAssessmentResult {
  readonly eligibility: CompensationEligibility;
  readonly reversibility: ReversibilityClassification;
  readonly rationale: string;
  readonly candidatePlan?: DeclarativeCompensationPlan;
  readonly requiresHumanApproval: boolean;
  readonly requiresReconciliation: boolean;
  readonly idempotencyAssessment: IdempotencyClassification;
}

export interface AssessCompensationInput {
  readonly originalOperationId: string;
  readonly originalActionId?: string;
  readonly capabilityId: string;
  readonly operation?: string;
  readonly parameters?: Record<string, unknown>;
  readonly truthState?: string;
  readonly failureClassification?: FailureClassification;
  readonly recoveryPlan?: RecoveryPlan;
  readonly dispatchState?: DispatchState;
  readonly confirmedSuccess?: boolean;
  readonly externalConfirmationReceived?: boolean;
  readonly reconciliationResult?: ReconciliationResultRecord;
  readonly partialExecution?: {
    readonly completedSteps: readonly string[];
    readonly failedStep?: string;
    readonly pendingSteps: readonly string[];
  };
  readonly recoveryDepth?: number;
  readonly visitedOperationIds?: readonly string[];
  readonly causationId?: string;
  readonly correlationId?: string;
  readonly metadata?: Readonly<Record<string, unknown>>;
}

export interface CompensationDispatchResult {
  readonly compensationId: string;
  readonly originalOperationId: string;
  readonly dispatchSuccess: boolean;
  readonly lifecycleState: CompensationLifecycleState;
  readonly dispatchedActionId?: string;
  readonly dispatchedIdempotencyKey?: string;
  readonly rawResultData?: unknown;
  readonly error?: string;
  readonly timestamp: number;
}

// ============================================================================
// 13. Phase 7: Cascading Failure & Autonomous Boundary Protection Contracts
// ============================================================================

export const CASCADE_CLASSIFICATIONS = [
  'NO_CASCADE',
  'RECOVERY_CHAIN',
  'RETRY_AMPLIFICATION',
  'DEPENDENCY_FAILURE',
  'CONNECTOR_FAILURE',
  'PROVIDER_FAILURE',
  'AUTHORIZATION_FAILURE',
  'PERMISSION_FAILURE',
  'POLICY_BLOCK',
  'RESOURCE_EXHAUSTION',
  'RECONCILIATION_FAILURE',
  'COMPENSATION_FAILURE',
  'REACTION_CASCADE',
  'MISSION_CASCADE',
  'SYSTEM_WIDE_FAILURE',
  'UNKNOWN_CASCADE',
] as const;

export type CascadeClassification = (typeof CASCADE_CLASSIFICATIONS)[number];

export const CASCADE_CONTAINMENT_CONTROLS = [
  'ALLOW',
  'THROTTLE',
  'PAUSE',
  'DEFER',
  'REQUIRE_APPROVAL',
  'ISOLATE',
  'ABORT',
  'ESCALATE',
] as const;

export type CascadeContainmentControl = (typeof CASCADE_CONTAINMENT_CONTROLS)[number];

export const CASCADE_LIFECYCLE_STATES = [
  'DETECTED',
  'CLASSIFIED',
  'ASSESSED',
  'CONTAINMENT_PROPOSED',
  'GOVERNED',
  'CONTAINED',
  'MONITORED',
  'RECOVERED',
  'REJECTED',
  'EXPIRED',
  'ESCALATED',
  'UNRESOLVED',
  'ABORTED',
] as const;

export type CascadeLifecycleState = (typeof CASCADE_LIFECYCLE_STATES)[number];

// Cascade Thresholds
export const MAX_FAILURES_PER_OPERATION = 3;
export const MAX_FAILURES_PER_DEPENDENCY = 2;
export const MAX_FAILURES_PER_CONNECTOR = 3;
export const MAX_FAILURES_PER_PROVIDER = 3;
export const MAX_CASCADE_DEPTH = 5;
export const MAX_CONCURRENT_AFFECTED_OPERATIONS = 50;
export const MAX_REPEATED_UNKNOWN_STATE = 2;
export const MAX_COMPENSATION_FAILURES = 2;

export interface CascadeEvidence {
  readonly rootOperationId: string;
  readonly rootFailureClassification?: FailureClassification;
  readonly failureCount?: number;
  readonly sameClassFailures?: number;
  readonly dependencyFailures?: number;
  readonly connectorFailures?: number;
  readonly providerFailures?: number;
  readonly recoveryChainDepth?: number;
  readonly unknownStateCount?: number;
  readonly compensationFailureCount?: number;
  readonly reactionDepth?: number;
  readonly triggerCycleDetected?: boolean;
  readonly affectedOperationIds?: readonly string[];
  readonly affectedMissionIds?: readonly string[];
  readonly affectedConnectorIds?: readonly string[];
  readonly affectedProviderIds?: readonly string[];
  readonly resourceSaturation?: boolean;
  readonly governanceDenials?: number;
  readonly staleApproval?: boolean;
  readonly stalePolicy?: boolean;
  readonly unknownGovernance?: boolean;
  readonly causationId?: string;
  readonly correlationId?: string;
  readonly metadata?: Readonly<Record<string, unknown>>;
}

export interface CascadeRecord {
  readonly cascadeId: string;
  readonly rootOperationId: string;
  readonly rootFailureId?: string;
  readonly rootMissionId?: string;
  readonly rootGoalId?: string;
  readonly failureClass: FailureClassification;
  readonly cascadeClass: CascadeClassification;
  readonly severity: 'LOW' | 'MEDIUM' | 'HIGH' | 'CRITICAL';
  readonly depth: number;
  readonly affectedOperationIds: readonly string[];
  readonly affectedMissionIds?: readonly string[];
  readonly affectedConnectorIds?: readonly string[];
  readonly affectedProviderIds?: readonly string[];
  readonly causationId: string;
  readonly correlationId: string;
  readonly detectedAt: number;
  readonly expiresAt: number;
  readonly lifecycleState: CascadeLifecycleState;
  readonly containmentAction: CascadeContainmentControl;
  readonly authorityRequirement: readonly string[];
  readonly evidenceReferences?: readonly string[];
  readonly metadata?: Readonly<Record<string, unknown>>;
}

export interface CascadeContainmentDecision {
  readonly containmentId: string;
  readonly cascadeId: string;
  readonly recommendedControl: CascadeContainmentControl;
  readonly severity: 'LOW' | 'MEDIUM' | 'HIGH' | 'CRITICAL';
  readonly affectedScope: {
    readonly operationIds: readonly string[];
    readonly connectorIds?: readonly string[];
    readonly providerIds?: readonly string[];
    readonly missionIds?: readonly string[];
  };
  readonly reasonCodes: readonly string[];
  readonly evidenceIds: readonly string[];
  readonly requiredAuthority: readonly string[];
  readonly governanceDecisionId?: string;
  readonly approvalRequirement: {
    readonly required: boolean;
    readonly humanOperatorRequired: boolean;
    readonly approvedBy?: string;
    readonly approvedAt?: number;
  };
  readonly expiresAt: number;
  readonly causationId: string;
  readonly correlationId: string;
  readonly lifecycleState: CascadeLifecycleState;
  readonly timestamp: number;
  readonly metadata?: Readonly<Record<string, unknown>>;
}

// ============================================================================
// 14. Phase 8: Recovery Control Plane Orchestration & Decision Surface
// ============================================================================

export const RECOVERY_OUTCOMES = [
  'NO_RECOVERY_REQUIRED',
  'RETRY',
  'RESUME',
  'ROLLBACK',
  'COMPENSATE',
  'RECONCILE',
  'WAIT',
  'REQUIRE_APPROVAL',
  'PAUSE',
  'ABORT',
  'ESCALATE',
  'UNKNOWN',
] as const;

export type RecoveryOutcome = (typeof RECOVERY_OUTCOMES)[number];

export const RECOVERY_CONTROL_LIFECYCLE_STATES = [
  'RECEIVED',
  'VALIDATED',
  'CLASSIFIED',
  'ASSESSED',
  'PLANNED',
  'GOVERNANCE_REQUIRED',
  'DECIDED',
  'REJECTED',
  'EXPIRED',
  'ESCALATED',
  'UNKNOWN',
] as const;

export type RecoveryControlLifecycleState = (typeof RECOVERY_CONTROL_LIFECYCLE_STATES)[number];

export interface RecoveryControlRequest {
  readonly requestId: string;
  readonly operationId: string;
  readonly actionId?: string;
  readonly missionId?: string;
  readonly goalId?: string;
  readonly capabilityId?: string;
  readonly operation?: string;
  readonly parameters?: Readonly<Record<string, unknown>>;
  readonly failureEvidence?: ClassificationEvidence;
  readonly dispatchState?: DispatchState;
  readonly operationalTruth?: string;
  readonly confirmedSuccess?: boolean;
  readonly externalConfirmationReceived?: boolean;
  readonly recoveryDepth?: number;
  readonly retryCount?: number;
  readonly reconciliationAttempts?: number;
  readonly compensationDepth?: number;
  readonly visitedOperationIds?: readonly string[];
  readonly visitedTriggerIds?: readonly string[];
  readonly policySnapshotId?: string;
  readonly idempotency?: IdempotencyClassification;
  readonly riskLevel?: 'LOW' | 'MEDIUM' | 'HIGH' | 'CRITICAL';
  readonly governanceContext?: {
    readonly required?: boolean;
    readonly approved?: boolean;
    readonly actorType?: string;
    readonly actorId?: string;
    readonly stale?: boolean;
    readonly unknown?: boolean;
  };
  readonly cascadeEvidence?: CascadeEvidence;
  readonly causationId?: string;
  readonly correlationId?: string;
  readonly createdAt?: number;
  readonly originalOperationId?: string;
  readonly recoveryPlanId?: string;
  readonly policyVersion?: number;
  readonly reconciliationId?: string;
  readonly compensationId?: string;
  readonly operatorApproval?: import('./governanceControlPlane').OperatorApprovalToken;
  readonly metadata?: Readonly<Record<string, unknown>>;
}

export interface RecoveryControlDecision {
  readonly decisionId: string;
  readonly requestId: string;
  readonly operationId: string;
  readonly classification: FailureClassification;
  readonly recoveryOutcome: RecoveryOutcome;
  readonly recommendedAction: RecoveryAction;
  readonly safetyAssessment?: RecoverySafetyAssessment;
  readonly reconciliationRequirement?: {
    readonly required: boolean;
    readonly reason?: string;
    readonly timeoutMs?: number;
  };
  readonly compensationAssessment?: CompensationAssessmentResult;
  readonly cascadeAssessment?: CascadeRecord;
  readonly containmentDecision?: CascadeContainmentDecision;
  readonly governanceRequirement: {
    readonly required: boolean;
    readonly humanOperatorRequired: boolean;
    readonly reason?: string;
    readonly stale?: boolean;
  };
  readonly requiredAuthority: readonly string[];
  readonly riskLevel: 'LOW' | 'MEDIUM' | 'HIGH' | 'CRITICAL';
  readonly epistemicStatus: string;
  readonly reasonCodes: readonly string[];
  readonly evidenceIds: readonly string[];
  readonly causationId: string;
  readonly correlationId: string;
  readonly expiresAt: number;
  readonly lifecycleState: RecoveryControlLifecycleState;
  readonly recoveryDepth: number;
  readonly retryCount: number;
  readonly reconciliationAttempts: number;
  readonly createdAt: number;
  readonly actionId?: string;
  readonly missionId?: string;
  readonly goalId?: string;
  readonly supersedesDecisionId?: string;
  readonly policySnapshotId?: string;
  readonly policyVersion?: number;
  readonly governanceDecisionId?: string;
  readonly recoveryPlanId?: string;
  readonly recoveryAttemptId?: string;
  readonly reconciliationId?: string;
  readonly compensationId?: string;
  readonly originalOperationId?: string;
  readonly approvalIdentity?: string;
  readonly governanceDecision?: import('./governanceControlPlane').GovernanceDecision;
  readonly metadata?: Readonly<Record<string, unknown>>;
}

// ============================================================================
// 15. Phase 9: Durable Recovery Control & Lease Contracts
// ============================================================================

export interface RecoveryControlLease {
  readonly leaseId: string;
  readonly decisionId: string;
  readonly operationId: string;
  readonly workerId: string;
  readonly acquiredAt: number;
  readonly expiresAt: number;
  readonly metadata?: Readonly<Record<string, unknown>>;
}

export interface RevalidationContext {
  readonly currentPolicyVersion?: number;
  readonly currentPolicySnapshotId?: string;
  readonly policySnapshotExpired?: boolean;
  readonly connectorPermissionRevoked?: boolean;
  readonly connectorPermissionChanged?: boolean;
  readonly connectorStatus?: string;
  readonly humanApprovalExpired?: boolean;
  readonly operationStatusChanged?: boolean;
  readonly observedOperationStatus?: string;
  readonly externalStatusConfirmed?: boolean;
  readonly externalSuccess?: boolean;
  readonly externalFailure?: boolean;
  readonly missionState?: string;
  readonly missionConstraintBlocked?: boolean;
  readonly now?: number;
  readonly governanceDecision?: import('./governanceControlPlane').GovernanceDecision;
  readonly auditEvidenceIds?: readonly string[];
}

export interface DecisionRevalidationResult {
  readonly valid: boolean;
  readonly isStale: boolean;
  readonly isExpired: boolean;
  readonly requiresReevaluation: boolean;
  readonly currentDecision: RecoveryControlDecision;
  readonly supersedingDecision?: RecoveryControlDecision;
  readonly reason: string;
  readonly reasonCode?: string;
  readonly recommendedAction: RecoveryAction;
}
