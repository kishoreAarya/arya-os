/**
 * AryaOS V1 — Stage 23: Core Recovery Contracts & Validation Engine
 *
 * Provides strongly typed, immutable data contracts for recovery plans,
 * recovery attempt records, and recovery safety assessments.
 *
 * Enforces deep immutability, prototype pollution defense, depth/key bounds,
 * function rejection, credential scrubbing, and causal/correlation integrity.
 *
 * IMPORTANT: This module is contract-only. Zero execution or retry logic.
 */

import {
  FailureClassification,
  FAILURE_CLASSIFICATIONS,
  RecoveryAction,
  RECOVERY_ACTIONS,
  RecoveryLifecycleState,
  RecoveryLifecycleProgressionState,
  RecoveryLifecycleTerminalState,
  RECOVERY_PROGRESSION_STATES,
  RECOVERY_TERMINAL_STATES,
  IdempotencyClassification,
  IDEMPOTENCY_CLASSIFICATIONS,
  CompensationAvailability,
  COMPENSATION_AVAILABILITIES,
  MAX_RECOVERY_DEPTH,
  MAX_AUTOMATIC_RETRIES,
  MAX_RECOVERY_OBJECT_DEPTH,
  MAX_RECOVERY_KEYS_PER_OBJECT,
  RecoveryPlan,
  RecoveryAttemptRecord,
  RecoverySafetyAssessment,
  COMPENSATION_ELIGIBILITIES,
  COMPENSATION_TYPES,
  REVERSIBILITY_CLASSES,
  COMPENSATION_LIFECYCLE_STATES,
  CompensationEligibility,
  CompensationType,
  ReversibilityClassification,
  CompensationLifecycleState,
  DeclarativeCompensationPlan,
  CASCADE_CLASSIFICATIONS,
  CASCADE_CONTAINMENT_CONTROLS,
  CASCADE_LIFECYCLE_STATES,
  CascadeClassification,
  CascadeContainmentControl,
  CascadeLifecycleState,
  CascadeRecord,
  CascadeContainmentDecision,
  MAX_CASCADE_DEPTH,
  MAX_CONCURRENT_AFFECTED_OPERATIONS,
  RECOVERY_OUTCOMES,
  RecoveryOutcome,
  RECOVERY_CONTROL_LIFECYCLE_STATES,
  RecoveryControlLifecycleState,
  RecoveryControlRequest,
  RecoveryControlDecision,
} from '../types/recoveryControl';

export * from '../types/recoveryControl';

// ============================================================================
// Security & Input Validation Constants
// ============================================================================
const FORBIDDEN_PROTOTYPE_KEYS = new Set(['__proto__', 'constructor', 'prototype']);

const SENSITIVE_KEY_PATTERNS = [
  /api[_-]?key/i,
  /token/i,
  /secret/i,
  /password/i,
  /passwd/i,
  /auth[_-]?header/i,
  /private[_-]?key/i,
  /bearer/i,
];

export class RecoveryContractViolationError extends Error {
  constructor(message: string) {
    super(`[RecoveryContractViolation] ${message}`);
    this.name = 'RecoveryContractViolationError';
  }
}

// ============================================================================
// Deep Immutability & Input Validation Utilities
// ============================================================================

/**
 * Recursively deep freezes an object graph at runtime.
 */
export function deepFreeze<T>(obj: T): Readonly<T> {
  if (obj === null || typeof obj !== 'object') {
    return obj;
  }

  Object.freeze(obj);

  for (const key of Object.getOwnPropertyNames(obj)) {
    const val = (obj as Record<string, unknown>)[key];
    if (val !== null && typeof val === 'object' && !Object.isFrozen(val)) {
      deepFreeze(val);
    }
  }

  return obj;
}

/**
 * Validates untrusted payload input against prototype pollution, functions,
 * excessive depth, excessive keys, circular references, and credential leakage.
 */
export function validateAndSanitizePayload<T>(
  input: T,
  currentDepth = 0,
  visited: WeakSet<object> = new WeakSet()
): T {
  if (input === null || input === undefined) {
    return input;
  }

  if (typeof input === 'function') {
    throw new RecoveryContractViolationError('Executable functions/callbacks are strictly forbidden in recovery contracts');
  }

  if (typeof input === 'symbol') {
    throw new RecoveryContractViolationError('Symbols are forbidden in recovery contracts');
  }

  if (typeof input !== 'object') {
    return input;
  }

  if (visited.has(input as object)) {
    throw new RecoveryContractViolationError('Circular reference detected and rejected in recovery payload');
  }
  visited.add(input as object);

  if (currentDepth >= MAX_RECOVERY_OBJECT_DEPTH) {
    throw new RecoveryContractViolationError(
      `Payload exceeds maximum object nesting depth of ${MAX_RECOVERY_OBJECT_DEPTH}`
    );
  }

  if (Array.isArray(input)) {
    if (input.length > MAX_RECOVERY_KEYS_PER_OBJECT) {
      throw new RecoveryContractViolationError(
        `Array exceeds maximum element limit of ${MAX_RECOVERY_KEYS_PER_OBJECT}`
      );
    }
    const sanitizedArray = input.map((item) =>
      validateAndSanitizePayload(item, currentDepth + 1, visited)
    );
    return sanitizedArray as unknown as T;
  }

  const entries = Object.entries(input as Record<string, unknown>);
  if (entries.length > MAX_RECOVERY_KEYS_PER_OBJECT) {
    throw new RecoveryContractViolationError(
      `Object exceeds maximum key count of ${MAX_RECOVERY_KEYS_PER_OBJECT}`
    );
  }

  const sanitized: Record<string, unknown> = {};

  for (const [key, value] of entries) {
    if (FORBIDDEN_PROTOTYPE_KEYS.has(key)) {
      throw new RecoveryContractViolationError(`Prototype pollution key '${key}' detected and rejected`);
    }

    if (typeof value === 'function') {
      throw new RecoveryContractViolationError(
        `Executable function detected on key '${key}'; functions are forbidden`
      );
    }

    if (SENSITIVE_KEY_PATTERNS.some((pattern) => pattern.test(key))) {
      throw new RecoveryContractViolationError(
        `Sensitive credential key '${key}' detected; secrets are strictly forbidden in recovery contracts`
      );
    }

    sanitized[key] = validateAndSanitizePayload(value, currentDepth + 1, visited);
  }

  return sanitized as T;
}

// ============================================================================
// Type Guards & Predicates
// ============================================================================

export function isFailureClassification(val: unknown): val is FailureClassification {
  return typeof val === 'string' && FAILURE_CLASSIFICATIONS.includes(val as FailureClassification);
}

export function isRecoveryAction(val: unknown): val is RecoveryAction {
  return typeof val === 'string' && RECOVERY_ACTIONS.includes(val as RecoveryAction);
}

export function isProgressionRecoveryState(val: unknown): val is RecoveryLifecycleProgressionState {
  return typeof val === 'string' && RECOVERY_PROGRESSION_STATES.includes(val as RecoveryLifecycleProgressionState);
}

export function isTerminalRecoveryState(val: unknown): val is RecoveryLifecycleTerminalState {
  return typeof val === 'string' && RECOVERY_TERMINAL_STATES.includes(val as RecoveryLifecycleTerminalState);
}

export function isRecoveryLifecycleState(val: unknown): val is RecoveryLifecycleState {
  return isProgressionRecoveryState(val) || isTerminalRecoveryState(val);
}

// ============================================================================
// Lifecycle State Transition Matrix & Validation (Phase 12 State Machine Fuzzing)
// ============================================================================

/**
 * Valid transitions for RecoveryLifecycleState:
 * Progression: DETECTED -> CLASSIFIED -> PROPOSED -> GOVERNED -> APPROVED -> READY -> DISPATCHED -> VERIFIED -> COMPLETED
 * Terminal: ABORTED, REJECTED, EXPIRED, UNKNOWN, ESCALATED
 */
export const VALID_RECOVERY_LIFECYCLE_TRANSITIONS: Readonly<Record<RecoveryLifecycleState, readonly RecoveryLifecycleState[]>> = Object.freeze({
  DETECTED: Object.freeze(['CLASSIFIED', 'ABORTED', 'UNKNOWN', 'ESCALATED', 'REJECTED'] as readonly RecoveryLifecycleState[]),
  CLASSIFIED: Object.freeze(['PROPOSED', 'ABORTED', 'UNKNOWN', 'ESCALATED', 'REJECTED'] as readonly RecoveryLifecycleState[]),
  PROPOSED: Object.freeze(['GOVERNED', 'ABORTED', 'UNKNOWN', 'ESCALATED', 'REJECTED', 'EXPIRED'] as readonly RecoveryLifecycleState[]),
  GOVERNED: Object.freeze(['APPROVED', 'READY', 'ABORTED', 'UNKNOWN', 'ESCALATED', 'REJECTED', 'EXPIRED'] as readonly RecoveryLifecycleState[]),
  APPROVED: Object.freeze(['READY', 'ABORTED', 'UNKNOWN', 'ESCALATED', 'EXPIRED'] as readonly RecoveryLifecycleState[]),
  READY: Object.freeze(['DISPATCHED', 'ABORTED', 'UNKNOWN', 'ESCALATED', 'EXPIRED'] as readonly RecoveryLifecycleState[]),
  DISPATCHED: Object.freeze(['VERIFIED', 'ABORTED', 'UNKNOWN', 'ESCALATED'] as readonly RecoveryLifecycleState[]),
  VERIFIED: Object.freeze(['COMPLETED', 'ABORTED', 'UNKNOWN', 'ESCALATED'] as readonly RecoveryLifecycleState[]),
  COMPLETED: Object.freeze([] as readonly RecoveryLifecycleState[]), // Terminal! Cannot transition to READY, DISPATCHED, etc.
  ABORTED: Object.freeze([] as readonly RecoveryLifecycleState[]),   // Terminal! Cannot RESUME
  REJECTED: Object.freeze([] as readonly RecoveryLifecycleState[]),  // Terminal! Cannot transition to APPROVED
  EXPIRED: Object.freeze([] as readonly RecoveryLifecycleState[]),   // Terminal! Cannot transition to READY or EXECUTE
  UNKNOWN: Object.freeze(['ESCALATED', 'ABORTED'] as readonly RecoveryLifecycleState[]), // Cannot transition to COMPLETED/SUCCESS without evidence
  ESCALATED: Object.freeze([] as readonly RecoveryLifecycleState[]), // Terminal!
});

/**
 * Validates whether a state transition from fromState to toState is legally permitted.
 * If hasConfirmedEvidence is true, UNKNOWN may transition to VERIFIED or COMPLETED.
 */
export function isValidRecoveryLifecycleTransition(
  fromState: RecoveryLifecycleState,
  toState: RecoveryLifecycleState,
  hasConfirmedEvidence: boolean = false
): boolean {
  if (!isRecoveryLifecycleState(fromState) || !isRecoveryLifecycleState(toState)) {
    return false;
  }
  // Terminals have no outgoing transitions
  if (
    fromState === 'COMPLETED' ||
    fromState === 'ABORTED' ||
    fromState === 'REJECTED' ||
    fromState === 'EXPIRED' ||
    fromState === 'ESCALATED'
  ) {
    return false;
  }
  // UNKNOWN cannot transition to VERIFIED or COMPLETED without confirmed operational evidence
  if (fromState === 'UNKNOWN') {
    if ((toState === 'COMPLETED' || toState === 'VERIFIED') && hasConfirmedEvidence) {
      return true;
    }
    const allowedFromUnknown = VALID_RECOVERY_LIFECYCLE_TRANSITIONS['UNKNOWN'];
    return allowedFromUnknown.includes(toState);
  }
  const allowed = VALID_RECOVERY_LIFECYCLE_TRANSITIONS[fromState];
  if (!allowed) return false;
  return allowed.includes(toState);
}

/**
 * Asserts that a state transition is legally permitted; throws RecoveryContractViolationError if not.
 */
export function assertValidRecoveryLifecycleTransition(
  fromState: RecoveryLifecycleState,
  toState: RecoveryLifecycleState,
  hasConfirmedEvidence: boolean = false
): void {
  if (!isValidRecoveryLifecycleTransition(fromState, toState, hasConfirmedEvidence)) {
    throw new RecoveryContractViolationError(
      `Illegal recovery lifecycle transition from '${fromState}' to '${toState}'. Terminal and out-of-order transitions are strictly forbidden.`
    );
  }
}

export function isIdempotencyClassification(val: unknown): val is IdempotencyClassification {
  return typeof val === 'string' && IDEMPOTENCY_CLASSIFICATIONS.includes(val as IdempotencyClassification);
}

export function isCompensationAvailability(val: unknown): val is CompensationAvailability {
  return typeof val === 'string' && COMPENSATION_AVAILABILITIES.includes(val as CompensationAvailability);
}

// ============================================================================
// Deterministic Contract Factory Functions (Deep Frozen & Validated)
// ============================================================================

export interface CreateRecoveryPlanParams {
  recoveryPlanId?: string;
  originalOperationId: string;
  failureClassification: FailureClassification;
  currentTruthState: string;
  proposedRecoveryAction: RecoveryAction;
  riskLevel: 'LOW' | 'MEDIUM' | 'HIGH' | 'CRITICAL';
  idempotencyAssessment: IdempotencyClassification;
  requiredAuthority: string[];
  governanceDecisionId?: string;
  approvalRequirement?: {
    required: boolean;
    approvalType?: string;
    approvedBy?: string;
    approvedAt?: number;
  };
  reconciliationRequirement?: {
    required: boolean;
    probeType?: string;
    timeoutMs?: number;
  };
  compensationPlan?: {
    availability: CompensationAvailability;
    compensatingActionType?: string;
    targetSystem?: string;
    parameters?: Record<string, unknown>;
  };
  expectedOutcome: string;
  expiry: number;
  causationId: string;
  correlationId: string;
  createdAt?: number;
  lifecycleState?: RecoveryLifecycleState;
  evidenceReferences?: string[];
  metadata?: Record<string, unknown>;
}

export function createRecoveryPlan(params: CreateRecoveryPlanParams): Readonly<RecoveryPlan> {
  // Causal & Correlation Integrity Check
  if (!params.originalOperationId || typeof params.originalOperationId !== 'string' || params.originalOperationId.trim() === '') {
    throw new RecoveryContractViolationError('originalOperationId is mandatory and cannot be empty');
  }
  if (!params.causationId || typeof params.causationId !== 'string' || params.causationId.trim() === '') {
    throw new RecoveryContractViolationError('causationId is mandatory and cannot be empty');
  }
  if (!params.correlationId || typeof params.correlationId !== 'string' || params.correlationId.trim() === '') {
    throw new RecoveryContractViolationError('correlationId is mandatory and cannot be empty');
  }

  // Type & Value Verifications
  if (!isFailureClassification(params.failureClassification)) {
    throw new RecoveryContractViolationError(`Invalid failureClassification: '${params.failureClassification}'`);
  }
  if (!isRecoveryAction(params.proposedRecoveryAction)) {
    throw new RecoveryContractViolationError(`Invalid proposedRecoveryAction: '${params.proposedRecoveryAction}'`);
  }
  if (!isIdempotencyClassification(params.idempotencyAssessment)) {
    throw new RecoveryContractViolationError(`Invalid idempotencyAssessment: '${params.idempotencyAssessment}'`);
  }
  if (typeof params.expiry !== 'number' || isNaN(params.expiry)) {
    throw new RecoveryContractViolationError('expiry timestamp must be a valid number');
  }

  const lifecycleState = params.lifecycleState || 'PROPOSED';
  if (!isRecoveryLifecycleState(lifecycleState)) {
    throw new RecoveryContractViolationError(`Invalid lifecycleState: '${lifecycleState}'`);
  }

  // Input Sanitization & Payload Bounding
  const sanitizedParams = params.compensationPlan?.parameters
    ? validateAndSanitizePayload(params.compensationPlan.parameters)
    : undefined;
  const sanitizedMetadata = params.metadata
    ? validateAndSanitizePayload(params.metadata)
    : undefined;

  const createdAt = params.createdAt ?? Date.now();
  const recoveryPlanId = params.recoveryPlanId || `rec_plan_${params.originalOperationId}_${createdAt}_${Math.random().toString(36).substring(2, 7)}`;

  const plan: RecoveryPlan = {
    recoveryPlanId,
    originalOperationId: params.originalOperationId,
    failureClassification: params.failureClassification,
    currentTruthState: params.currentTruthState,
    proposedRecoveryAction: params.proposedRecoveryAction,
    riskLevel: params.riskLevel,
    idempotencyAssessment: params.idempotencyAssessment,
    requiredAuthority: Object.freeze([...(params.requiredAuthority || [])]),
    governanceDecisionId: params.governanceDecisionId,
    approvalRequirement: Object.freeze({
      required: params.approvalRequirement?.required ?? false,
      approvalType: params.approvalRequirement?.approvalType,
      approvedBy: params.approvalRequirement?.approvedBy,
      approvedAt: params.approvalRequirement?.approvedAt,
    }),
    reconciliationRequirement: Object.freeze({
      required: params.reconciliationRequirement?.required ?? false,
      probeType: params.reconciliationRequirement?.probeType,
      timeoutMs: params.reconciliationRequirement?.timeoutMs,
    }),
    compensationPlan: Object.freeze({
      availability: params.compensationPlan?.availability ?? 'NO_COMPENSATION_AVAILABLE',
      compensatingActionType: params.compensationPlan?.compensatingActionType,
      targetSystem: params.compensationPlan?.targetSystem,
      parameters: sanitizedParams ? Object.freeze(sanitizedParams) : undefined,
    }),
    expectedOutcome: params.expectedOutcome,
    expiry: params.expiry,
    causationId: params.causationId,
    correlationId: params.correlationId,
    createdAt,
    lifecycleState,
    evidenceReferences: params.evidenceReferences ? Object.freeze([...params.evidenceReferences]) : undefined,
    metadata: sanitizedMetadata ? Object.freeze(sanitizedMetadata) : undefined,
  };

  return deepFreeze(plan);
}

export interface CreateRecoveryAttemptParams {
  attemptId?: string;
  recoveryPlanId: string;
  originalOperationId: string;
  attemptNumber: number;
  recoveryDepth: number;
  lifecycleState: RecoveryLifecycleState;
  proposedAction: RecoveryAction;
  idempotencyClassification: IdempotencyClassification;
  governanceDecisionId?: string;
  approvalReference?: string;
  causationId: string;
  correlationId: string;
  startedAt?: number;
  completedAt?: number;
  outcomeReference?: string;
  metadata?: Record<string, unknown>;
}

export function createRecoveryAttemptRecord(params: CreateRecoveryAttemptParams): Readonly<RecoveryAttemptRecord> {
  if (!params.originalOperationId || params.originalOperationId.trim() === '') {
    throw new RecoveryContractViolationError('originalOperationId is mandatory');
  }
  if (!params.recoveryPlanId || params.recoveryPlanId.trim() === '') {
    throw new RecoveryContractViolationError('recoveryPlanId is mandatory');
  }
  if (!params.causationId || params.causationId.trim() === '') {
    throw new RecoveryContractViolationError('causationId is mandatory');
  }
  if (!params.correlationId || params.correlationId.trim() === '') {
    throw new RecoveryContractViolationError('correlationId is mandatory');
  }
  if (typeof params.attemptNumber !== 'number' || params.attemptNumber < 1) {
    throw new RecoveryContractViolationError('attemptNumber must be a positive integer >= 1');
  }
  if (typeof params.recoveryDepth !== 'number' || params.recoveryDepth < 0) {
    throw new RecoveryContractViolationError('recoveryDepth must be a non-negative integer >= 0');
  }
  if (!isRecoveryLifecycleState(params.lifecycleState)) {
    throw new RecoveryContractViolationError(`Invalid lifecycleState: '${params.lifecycleState}'`);
  }
  if (!isRecoveryAction(params.proposedAction)) {
    throw new RecoveryContractViolationError(`Invalid proposedAction: '${params.proposedAction}'`);
  }
  if (!isIdempotencyClassification(params.idempotencyClassification)) {
    throw new RecoveryContractViolationError(`Invalid idempotencyClassification: '${params.idempotencyClassification}'`);
  }

  const sanitizedMetadata = params.metadata ? validateAndSanitizePayload(params.metadata) : undefined;
  const startedAt = params.startedAt ?? Date.now();
  const attemptId = params.attemptId || `rec_att_${params.recoveryPlanId}_${params.attemptNumber}_${startedAt}`;

  const record: RecoveryAttemptRecord = {
    attemptId,
    recoveryPlanId: params.recoveryPlanId,
    originalOperationId: params.originalOperationId,
    attemptNumber: params.attemptNumber,
    recoveryDepth: params.recoveryDepth,
    lifecycleState: params.lifecycleState,
    proposedAction: params.proposedAction,
    idempotencyClassification: params.idempotencyClassification,
    governanceDecisionId: params.governanceDecisionId,
    approvalReference: params.approvalReference,
    causationId: params.causationId,
    correlationId: params.correlationId,
    startedAt,
    completedAt: params.completedAt,
    outcomeReference: params.outcomeReference,
    metadata: sanitizedMetadata ? Object.freeze(sanitizedMetadata) : undefined,
  };

  return deepFreeze(record);
}

export interface CreateRecoverySafetyAssessmentParams {
  idempotencyClassification: IdempotencyClassification;
  duplicateSideEffectRisk: 'NONE' | 'LOW' | 'MEDIUM' | 'HIGH' | 'CRITICAL';
  reconciliationRequirement: boolean;
  partialExecutionDetected: boolean;
  completedSteps: string[];
  incompleteSteps: string[];
  compensationAvailability: CompensationAvailability;
  rollbackAvailability: boolean;
  retryPermitted: boolean;
  humanApprovalRequired: boolean;
  safetyRationale: string;
  assessmentTimestamp?: number;
}

export function createRecoverySafetyAssessment(params: CreateRecoverySafetyAssessmentParams): Readonly<RecoverySafetyAssessment> {
  if (!isIdempotencyClassification(params.idempotencyClassification)) {
    throw new RecoveryContractViolationError(`Invalid idempotencyClassification: '${params.idempotencyClassification}'`);
  }
  if (!isCompensationAvailability(params.compensationAvailability)) {
    throw new RecoveryContractViolationError(`Invalid compensationAvailability: '${params.compensationAvailability}'`);
  }
  if (!params.safetyRationale || params.safetyRationale.trim() === '') {
    throw new RecoveryContractViolationError('safetyRationale must not be empty');
  }

  const assessment: RecoverySafetyAssessment = {
    idempotencyClassification: params.idempotencyClassification,
    duplicateSideEffectRisk: params.duplicateSideEffectRisk,
    reconciliationRequirement: Boolean(params.reconciliationRequirement),
    partialExecutionDetected: Boolean(params.partialExecutionDetected),
    completedSteps: Object.freeze([...(params.completedSteps || [])]),
    incompleteSteps: Object.freeze([...(params.incompleteSteps || [])]),
    compensationAvailability: params.compensationAvailability,
    rollbackAvailability: Boolean(params.rollbackAvailability),
    retryPermitted: Boolean(params.retryPermitted),
    humanApprovalRequired: Boolean(params.humanApprovalRequired),
    safetyRationale: params.safetyRationale,
    assessmentTimestamp: params.assessmentTimestamp ?? Date.now(),
  };

  return deepFreeze(assessment);
}

// ============================================================================
// Phase 5: Reconciliation Contract Factories
// ============================================================================

export interface CreateReconciliationRequestParams {
  reconciliationId: string;
  originalOperationId: string;
  recoveryPlanId: string;
  targetCapability: string;
  probeIntent: 'READ_ONLY_STATUS_CHECK' | 'READ_ONLY_RESOURCE_GET' | 'READ_ONLY_IDEMPOTENCY_QUERY' | 'READ_ONLY_DIFF_CHECK';
  isReadOnly: true;
  causationId: string;
  correlationId: string;
  timeoutMs?: number;
  attemptNumber?: number;
  maxAttempts?: number;
  evidenceReferences?: string[];
  governanceRequired?: boolean;
  lifecycleState?: 'REQUIRED' | 'PLANNED' | 'GOVERNED' | 'READY' | 'PROBED' | 'VERIFIED';
  probeParameters?: Record<string, unknown>;
  metadata?: Record<string, unknown>;
}

export function createReconciliationRequest(params: CreateReconciliationRequestParams): Readonly<import('../types/recoveryControl').ReconciliationRequest> {
  if (!params.reconciliationId || params.reconciliationId.trim() === '') {
    throw new RecoveryContractViolationError('reconciliationId is mandatory');
  }
  if (!params.originalOperationId || params.originalOperationId.trim() === '') {
    throw new RecoveryContractViolationError('originalOperationId is mandatory');
  }
  if (!params.recoveryPlanId || params.recoveryPlanId.trim() === '') {
    throw new RecoveryContractViolationError('recoveryPlanId is mandatory');
  }
  if (!params.causationId || params.causationId.trim() === '') {
    throw new RecoveryContractViolationError('causationId is mandatory');
  }
  if (!params.correlationId || params.correlationId.trim() === '') {
    throw new RecoveryContractViolationError('correlationId is mandatory');
  }
  if (!params.targetCapability || params.targetCapability.trim() === '') {
    throw new RecoveryContractViolationError('targetCapability is mandatory');
  }
  if (params.isReadOnly !== true) {
    throw new RecoveryContractViolationError('isReadOnly must be strictly true for all reconciliation requests');
  }
  if (/^https?:\/\//i.test(params.targetCapability)) {
    throw new RecoveryContractViolationError('Arbitrary URLs are strictly forbidden as targetCapability');
  }

  const sanitizedProbeParams = params.probeParameters ? validateAndSanitizePayload(params.probeParameters) : undefined;
  const sanitizedMetadata = params.metadata ? validateAndSanitizePayload(params.metadata) : undefined;

  // Verify parameters do not contain raw URLs to bypass network boundaries
  if (sanitizedProbeParams) {
    for (const val of Object.values(sanitizedProbeParams)) {
      if (typeof val === 'string' && /^https?:\/\//i.test(val)) {
        throw new RecoveryContractViolationError('Arbitrary URLs in probeParameters are strictly forbidden');
      }
    }
  }

  const req: import('../types/recoveryControl').ReconciliationRequest = {
    reconciliationId: params.reconciliationId,
    originalOperationId: params.originalOperationId,
    recoveryPlanId: params.recoveryPlanId,
    targetCapability: params.targetCapability,
    probeIntent: params.probeIntent,
    isReadOnly: true,
    causationId: params.causationId,
    correlationId: params.correlationId,
    timeoutMs: params.timeoutMs ?? 10000,
    attemptNumber: params.attemptNumber ?? 1,
    maxAttempts: params.maxAttempts ?? 3,
    evidenceReferences: Object.freeze([...(params.evidenceReferences || [])]),
    governanceRequired: params.governanceRequired ?? false,
    lifecycleState: params.lifecycleState ?? 'REQUIRED',
    probeParameters: sanitizedProbeParams ? Object.freeze(sanitizedProbeParams) : undefined,
    metadata: sanitizedMetadata ? Object.freeze(sanitizedMetadata) : undefined,
  };

  return deepFreeze(req);
}

export interface CreateReconciliationResultParams {
  reconciliationId: string;
  originalOperationId: string;
  recoveryPlanId: string;
  outcome: import('../types/recoveryControl').ReconciliationOutcome;
  epistemicStatus: import('../types/recoveryControl').ReconciliationEpistemicStatus;
  observedExternalState?: Record<string, unknown>;
  authoritativeEvidenceReferences?: string[];
  probeOperationReference?: string;
  note: string;
  reconciledAt?: number;
  causationId: string;
  correlationId: string;
  attemptNumber?: number;
  metadata?: Record<string, unknown>;
}

export function createReconciliationResultRecord(params: CreateReconciliationResultParams): Readonly<import('../types/recoveryControl').ReconciliationResultRecord> {
  if (!params.reconciliationId || params.reconciliationId.trim() === '') {
    throw new RecoveryContractViolationError('reconciliationId is mandatory');
  }
  if (!params.originalOperationId || params.originalOperationId.trim() === '') {
    throw new RecoveryContractViolationError('originalOperationId is mandatory');
  }
  if (!params.recoveryPlanId || params.recoveryPlanId.trim() === '') {
    throw new RecoveryContractViolationError('recoveryPlanId is mandatory');
  }
  if (!params.causationId || params.causationId.trim() === '') {
    throw new RecoveryContractViolationError('causationId is mandatory');
  }
  if (!params.correlationId || params.correlationId.trim() === '') {
    throw new RecoveryContractViolationError('correlationId is mandatory');
  }
  if (!params.note || params.note.trim() === '') {
    throw new RecoveryContractViolationError('note is mandatory');
  }

  const sanitizedObservedState = params.observedExternalState ? validateAndSanitizePayload(params.observedExternalState) : undefined;
  const sanitizedMetadata = params.metadata ? validateAndSanitizePayload(params.metadata) : undefined;

  const result: import('../types/recoveryControl').ReconciliationResultRecord = {
    reconciliationId: params.reconciliationId,
    originalOperationId: params.originalOperationId,
    recoveryPlanId: params.recoveryPlanId,
    outcome: params.outcome,
    epistemicStatus: params.epistemicStatus,
    observedExternalState: sanitizedObservedState ? Object.freeze(sanitizedObservedState) : undefined,
    authoritativeEvidenceReferences: Object.freeze([...(params.authoritativeEvidenceReferences || [])]),
    probeOperationReference: params.probeOperationReference,
    note: params.note,
    reconciledAt: params.reconciledAt ?? Date.now(),
    causationId: params.causationId,
    correlationId: params.correlationId,
    attemptNumber: params.attemptNumber ?? 1,
    metadata: sanitizedMetadata ? Object.freeze(sanitizedMetadata) : undefined,
  };

  return deepFreeze(result);
}

// ============================================================================
// Phase 6: Declarative Compensation Contract Factories & Guards
// ============================================================================

export function isCompensationEligibility(val: unknown): val is CompensationEligibility {
  return typeof val === 'string' && (COMPENSATION_ELIGIBILITIES as readonly string[]).includes(val);
}

export function isCompensationType(val: unknown): val is CompensationType {
  return typeof val === 'string' && (COMPENSATION_TYPES as readonly string[]).includes(val);
}

export function isReversibilityClassification(val: unknown): val is ReversibilityClassification {
  return typeof val === 'string' && (REVERSIBILITY_CLASSES as readonly string[]).includes(val);
}

export function isCompensationLifecycleState(val: unknown): val is CompensationLifecycleState {
  return typeof val === 'string' && (COMPENSATION_LIFECYCLE_STATES as readonly string[]).includes(val);
}

export interface CreateDeclarativeCompensationPlanParams {
  compensationId: string;
  originalOperationId: string;
  originalActionId?: string;
  compensationType: CompensationType;
  sourceCapability: string;
  compensatingCapability: string;
  sourceStateRequirement?: string;
  targetState: string;
  compensationParameters: Record<string, unknown>;
  reversibilityClass: ReversibilityClassification;
  idempotencyClass: IdempotencyClassification;
  riskLevel: 'LOW' | 'MEDIUM' | 'HIGH' | 'CRITICAL';
  requiredAuthority: string[];
  approvalRequirement: {
    required: boolean;
    humanOperatorRequired: boolean;
    approvedBy?: string;
    approvedAt?: number;
    governanceDecisionId?: string;
  };
  reconciliationRequirement: {
    required: boolean;
    postCompensationVerification: boolean;
    timeoutMs?: number;
  };
  idempotencyKey: string;
  causationId: string;
  correlationId: string;
  expiresAt: number;
  lifecycleState?: CompensationLifecycleState;
  recoveryDepth?: number;
  evidenceReferences?: string[];
  metadata?: Record<string, unknown>;
}

export function createDeclarativeCompensationPlan(params: CreateDeclarativeCompensationPlanParams): Readonly<DeclarativeCompensationPlan> {
  if (!params.compensationId || params.compensationId.trim() === '') {
    throw new RecoveryContractViolationError('compensationId is mandatory and cannot be empty');
  }
  if (!params.originalOperationId || params.originalOperationId.trim() === '') {
    throw new RecoveryContractViolationError('originalOperationId is mandatory and cannot be empty');
  }
  if (params.compensationId === params.originalOperationId) {
    throw new RecoveryContractViolationError('compensationId must be distinct from originalOperationId');
  }
  if (!params.sourceCapability || params.sourceCapability.trim() === '') {
    throw new RecoveryContractViolationError('sourceCapability is mandatory');
  }
  if (!params.compensatingCapability || params.compensatingCapability.trim() === '') {
    throw new RecoveryContractViolationError('compensatingCapability is mandatory');
  }
  if (/^https?:\/\//i.test(params.compensatingCapability)) {
    throw new RecoveryContractViolationError('Arbitrary URLs are strictly forbidden as compensatingCapability');
  }
  if (!params.targetState || params.targetState.trim() === '') {
    throw new RecoveryContractViolationError('targetState is mandatory');
  }
  if (/^https?:\/\//i.test(params.targetState)) {
    throw new RecoveryContractViolationError('Arbitrary URLs are strictly forbidden in targetState');
  }
  if (!params.idempotencyKey || params.idempotencyKey.trim() === '') {
    throw new RecoveryContractViolationError('idempotencyKey is mandatory');
  }
  if (params.idempotencyKey === params.originalOperationId) {
    throw new RecoveryContractViolationError('Compensation must receive a distinct idempotency key');
  }
  if (!params.causationId || params.causationId.trim() === '') {
    throw new RecoveryContractViolationError('causationId is mandatory');
  }
  if (!params.correlationId || params.correlationId.trim() === '') {
    throw new RecoveryContractViolationError('correlationId is mandatory');
  }

  const recoveryDepth = params.recoveryDepth ?? 1;
  if (recoveryDepth > MAX_RECOVERY_DEPTH) {
    throw new RecoveryContractViolationError(`Recovery depth ${recoveryDepth} exceeds maximum allowed depth of ${MAX_RECOVERY_DEPTH}`);
  }

  const sanitizedParams = params.compensationParameters
    ? validateAndSanitizePayload(params.compensationParameters)
    : {};
  const sanitizedMetadata = params.metadata
    ? validateAndSanitizePayload(params.metadata)
    : undefined;

  // Security check: no raw URLs in parameters
  for (const val of Object.values(sanitizedParams)) {
    if (typeof val === 'string' && /^https?:\/\//i.test(val)) {
      throw new RecoveryContractViolationError('Arbitrary URLs in compensationParameters are strictly forbidden');
    }
  }

  const plan: import('../types/recoveryControl').DeclarativeCompensationPlan = {
    compensationId: params.compensationId,
    originalOperationId: params.originalOperationId,
    originalActionId: params.originalActionId,
    compensationType: params.compensationType,
    sourceCapability: params.sourceCapability,
    compensatingCapability: params.compensatingCapability,
    sourceStateRequirement: params.sourceStateRequirement,
    targetState: params.targetState,
    compensationParameters: Object.freeze(sanitizedParams),
    reversibilityClass: params.reversibilityClass,
    idempotencyClass: params.idempotencyClass,
    riskLevel: params.riskLevel,
    requiredAuthority: Object.freeze([...(params.requiredAuthority || [])]),
    approvalRequirement: Object.freeze({
      required: Boolean(params.approvalRequirement?.required),
      humanOperatorRequired: Boolean(params.approvalRequirement?.humanOperatorRequired),
      approvedBy: params.approvalRequirement?.approvedBy,
      approvedAt: params.approvalRequirement?.approvedAt,
      governanceDecisionId: params.approvalRequirement?.governanceDecisionId,
    }),
    reconciliationRequirement: Object.freeze({
      required: Boolean(params.reconciliationRequirement?.required),
      postCompensationVerification: Boolean(params.reconciliationRequirement?.postCompensationVerification),
      timeoutMs: params.reconciliationRequirement?.timeoutMs ?? 10000,
    }),
    idempotencyKey: params.idempotencyKey,
    causationId: params.causationId,
    correlationId: params.correlationId,
    expiresAt: params.expiresAt,
    lifecycleState: params.lifecycleState ?? 'PROPOSED',
    recoveryDepth,
    evidenceReferences: params.evidenceReferences ? Object.freeze([...params.evidenceReferences]) : undefined,
    metadata: sanitizedMetadata ? Object.freeze(sanitizedMetadata) : undefined,
  };

  return deepFreeze(plan);
}

// ============================================================================
// Phase 7: Cascading Failure & Autonomous Boundary Protection Factories & Guards
// ============================================================================

export function isCascadeClassification(val: unknown): val is CascadeClassification {
  return typeof val === 'string' && (CASCADE_CLASSIFICATIONS as readonly string[]).includes(val);
}

export function isCascadeContainmentControl(val: unknown): val is CascadeContainmentControl {
  return typeof val === 'string' && (CASCADE_CONTAINMENT_CONTROLS as readonly string[]).includes(val);
}

export function isCascadeLifecycleState(val: unknown): val is CascadeLifecycleState {
  return typeof val === 'string' && (CASCADE_LIFECYCLE_STATES as readonly string[]).includes(val);
}

export interface CreateCascadeRecordParams {
  cascadeId: string;
  rootOperationId: string;
  rootFailureId?: string;
  rootMissionId?: string;
  rootGoalId?: string;
  failureClass: FailureClassification;
  cascadeClass: CascadeClassification;
  severity: 'LOW' | 'MEDIUM' | 'HIGH' | 'CRITICAL';
  depth: number;
  affectedOperationIds: string[];
  affectedMissionIds?: string[];
  affectedConnectorIds?: string[];
  affectedProviderIds?: string[];
  causationId: string;
  correlationId: string;
  detectedAt?: number;
  expiresAt: number;
  lifecycleState?: CascadeLifecycleState;
  containmentAction: CascadeContainmentControl;
  authorityRequirement: string[];
  evidenceReferences?: string[];
  metadata?: Record<string, unknown>;
}

export function createCascadeRecord(params: CreateCascadeRecordParams): Readonly<CascadeRecord> {
  if (!params.cascadeId || params.cascadeId.trim() === '') {
    throw new RecoveryContractViolationError('cascadeId is mandatory and cannot be empty');
  }
  if (!params.rootOperationId || params.rootOperationId.trim() === '') {
    throw new RecoveryContractViolationError('rootOperationId is mandatory and cannot be empty');
  }
  if (params.cascadeId === params.rootOperationId) {
    throw new RecoveryContractViolationError('cascadeId must be distinct from rootOperationId');
  }
  if (!params.causationId || params.causationId.trim() === '') {
    throw new RecoveryContractViolationError('causationId is mandatory');
  }
  if (!params.correlationId || params.correlationId.trim() === '') {
    throw new RecoveryContractViolationError('correlationId is mandatory');
  }

  if (params.depth > MAX_CASCADE_DEPTH) {
    throw new RecoveryContractViolationError(
      `Cascade depth ${params.depth} exceeds maximum allowable depth of ${MAX_CASCADE_DEPTH}`
    );
  }

  if (params.affectedOperationIds.length > MAX_CONCURRENT_AFFECTED_OPERATIONS) {
    throw new RecoveryContractViolationError(
      `Affected operations count ${params.affectedOperationIds.length} exceeds safety limit of ${MAX_CONCURRENT_AFFECTED_OPERATIONS}`
    );
  }

  const sanitizedMetadata = params.metadata ? validateAndSanitizePayload(params.metadata) : undefined;

  const record: CascadeRecord = {
    cascadeId: params.cascadeId,
    rootOperationId: params.rootOperationId,
    rootFailureId: params.rootFailureId,
    rootMissionId: params.rootMissionId,
    rootGoalId: params.rootGoalId,
    failureClass: params.failureClass,
    cascadeClass: params.cascadeClass,
    severity: params.severity,
    depth: params.depth,
    affectedOperationIds: Object.freeze([...params.affectedOperationIds]),
    affectedMissionIds: params.affectedMissionIds ? Object.freeze([...params.affectedMissionIds]) : undefined,
    affectedConnectorIds: params.affectedConnectorIds ? Object.freeze([...params.affectedConnectorIds]) : undefined,
    affectedProviderIds: params.affectedProviderIds ? Object.freeze([...params.affectedProviderIds]) : undefined,
    causationId: params.causationId,
    correlationId: params.correlationId,
    detectedAt: params.detectedAt ?? Date.now(),
    expiresAt: params.expiresAt,
    lifecycleState: params.lifecycleState ?? 'DETECTED',
    containmentAction: params.containmentAction,
    authorityRequirement: Object.freeze([...params.authorityRequirement]),
    evidenceReferences: params.evidenceReferences ? Object.freeze([...params.evidenceReferences]) : undefined,
    metadata: sanitizedMetadata ? Object.freeze(sanitizedMetadata) : undefined,
  };

  return deepFreeze(record);
}

export interface CreateCascadeContainmentDecisionParams {
  containmentId: string;
  cascadeId: string;
  recommendedControl: CascadeContainmentControl;
  severity: 'LOW' | 'MEDIUM' | 'HIGH' | 'CRITICAL';
  affectedScope: {
    operationIds: string[];
    connectorIds?: string[];
    providerIds?: string[];
    missionIds?: string[];
  };
  reasonCodes: string[];
  evidenceIds: string[];
  requiredAuthority: string[];
  governanceDecisionId?: string;
  approvalRequirement?: {
    required: boolean;
    humanOperatorRequired: boolean;
    approvedBy?: string;
    approvedAt?: number;
  };
  expiresAt: number;
  causationId: string;
  correlationId: string;
  lifecycleState?: CascadeLifecycleState;
  timestamp?: number;
  metadata?: Record<string, unknown>;
}

export function createCascadeContainmentDecision(
  params: CreateCascadeContainmentDecisionParams
): Readonly<CascadeContainmentDecision> {
  if (!params.containmentId || params.containmentId.trim() === '') {
    throw new RecoveryContractViolationError('containmentId is mandatory and cannot be empty');
  }
  if (!params.cascadeId || params.cascadeId.trim() === '') {
    throw new RecoveryContractViolationError('cascadeId is mandatory and cannot be empty');
  }
  if (!params.causationId || params.causationId.trim() === '') {
    throw new RecoveryContractViolationError('causationId is mandatory');
  }
  if (!params.correlationId || params.correlationId.trim() === '') {
    throw new RecoveryContractViolationError('correlationId is mandatory');
  }

  const sanitizedMetadata = params.metadata ? validateAndSanitizePayload(params.metadata) : undefined;

  const decision: CascadeContainmentDecision = {
    containmentId: params.containmentId,
    cascadeId: params.cascadeId,
    recommendedControl: params.recommendedControl,
    severity: params.severity,
    affectedScope: {
      operationIds: Object.freeze([...params.affectedScope.operationIds]),
      connectorIds: params.affectedScope.connectorIds ? Object.freeze([...params.affectedScope.connectorIds]) : undefined,
      providerIds: params.affectedScope.providerIds ? Object.freeze([...params.affectedScope.providerIds]) : undefined,
      missionIds: params.affectedScope.missionIds ? Object.freeze([...params.affectedScope.missionIds]) : undefined,
    },
    reasonCodes: Object.freeze([...params.reasonCodes]),
    evidenceIds: Object.freeze([...params.evidenceIds]),
    requiredAuthority: Object.freeze([...params.requiredAuthority]),
    governanceDecisionId: params.governanceDecisionId,
    approvalRequirement: {
      required: Boolean(params.approvalRequirement?.required),
      humanOperatorRequired: Boolean(params.approvalRequirement?.humanOperatorRequired),
      approvedBy: params.approvalRequirement?.approvedBy,
      approvedAt: params.approvalRequirement?.approvedAt,
    },
    expiresAt: params.expiresAt,
    causationId: params.causationId,
    correlationId: params.correlationId,
    lifecycleState: params.lifecycleState ?? 'CONTAINMENT_PROPOSED',
    timestamp: params.timestamp ?? Date.now(),
    metadata: sanitizedMetadata ? Object.freeze(sanitizedMetadata) : undefined,
  };

  return deepFreeze(decision);
}

// ============================================================================
// Phase 8: Recovery Control Plane Orchestration Contract Factories & Guards
// ============================================================================

export function isRecoveryOutcome(val: unknown): val is RecoveryOutcome {
  return typeof val === 'string' && (RECOVERY_OUTCOMES as readonly string[]).includes(val);
}

export function isRecoveryControlLifecycleState(val: unknown): val is RecoveryControlLifecycleState {
  return typeof val === 'string' && (RECOVERY_CONTROL_LIFECYCLE_STATES as readonly string[]).includes(val);
}

export interface CreateRecoveryControlDecisionParams {
  decisionId: string;
  requestId: string;
  operationId: string;
  classification: FailureClassification;
  recoveryOutcome: RecoveryOutcome;
  recommendedAction: RecoveryAction;
  safetyAssessment?: RecoverySafetyAssessment;
  reconciliationRequirement?: {
    required: boolean;
    reason?: string;
    timeoutMs?: number;
  };
  compensationAssessment?: import('../types/recoveryControl').CompensationAssessmentResult;
  cascadeAssessment?: CascadeRecord;
  containmentDecision?: CascadeContainmentDecision;
  governanceRequirement?: {
    required: boolean;
    humanOperatorRequired: boolean;
    reason?: string;
    stale?: boolean;
  };
  requiredAuthority: readonly string[];
  riskLevel?: 'LOW' | 'MEDIUM' | 'HIGH' | 'CRITICAL';
  epistemicStatus?: string;
  reasonCodes: readonly string[];
  evidenceIds: readonly string[];
  causationId: string;
  correlationId: string;
  expiresAt?: number;
  lifecycleState?: RecoveryControlLifecycleState;
  recoveryDepth?: number;
  retryCount?: number;
  reconciliationAttempts?: number;
  createdAt?: number;
  actionId?: string;
  missionId?: string;
  goalId?: string;
  supersedesDecisionId?: string;
  policySnapshotId?: string;
  policyVersion?: number;
  governanceDecisionId?: string;
  recoveryPlanId?: string;
  recoveryAttemptId?: string;
  reconciliationId?: string;
  compensationId?: string;
  originalOperationId?: string;
  approvalIdentity?: string;
  governanceDecision?: import('../types/governanceControlPlane').GovernanceDecision;
  metadata?: Record<string, unknown>;
}

export function createRecoveryControlDecision(
  params: CreateRecoveryControlDecisionParams
): Readonly<RecoveryControlDecision> {
  if (!params.decisionId || params.decisionId.trim() === '') {
    throw new RecoveryContractViolationError('decisionId is mandatory');
  }
  if (!params.requestId || params.requestId.trim() === '') {
    throw new RecoveryContractViolationError('requestId is mandatory');
  }
  if (!params.operationId || params.operationId.trim() === '') {
    throw new RecoveryContractViolationError('operationId is mandatory');
  }
  if (!isRecoveryOutcome(params.recoveryOutcome)) {
    throw new RecoveryContractViolationError(`Invalid recoveryOutcome: '${params.recoveryOutcome}'`);
  }
  if (!isRecoveryAction(params.recommendedAction)) {
    throw new RecoveryContractViolationError(`Invalid recommendedAction: '${params.recommendedAction}'`);
  }
  if (!params.causationId || params.causationId.trim() === '') {
    throw new RecoveryContractViolationError('causationId is mandatory');
  }
  if (!params.correlationId || params.correlationId.trim() === '') {
    throw new RecoveryContractViolationError('correlationId is mandatory');
  }

  const sanitizedMetadata = params.metadata ? validateAndSanitizePayload(params.metadata) : undefined;
  const createdAt = params.createdAt ?? Date.now();
  const expiresAt = params.expiresAt ?? (createdAt + 300000); // 5 minutes TTL

  const decision: RecoveryControlDecision = {
    decisionId: params.decisionId,
    requestId: params.requestId,
    operationId: params.operationId,
    classification: params.classification,
    recoveryOutcome: params.recoveryOutcome,
    recommendedAction: params.recommendedAction,
    safetyAssessment: params.safetyAssessment,
    reconciliationRequirement: params.reconciliationRequirement ? {
      required: Boolean(params.reconciliationRequirement.required),
      reason: params.reconciliationRequirement.reason,
      timeoutMs: params.reconciliationRequirement.timeoutMs,
    } : undefined,
    compensationAssessment: params.compensationAssessment,
    cascadeAssessment: params.cascadeAssessment,
    containmentDecision: params.containmentDecision,
    governanceRequirement: {
      required: Boolean(params.governanceRequirement?.required),
      humanOperatorRequired: Boolean(params.governanceRequirement?.humanOperatorRequired),
      reason: params.governanceRequirement?.reason,
      stale: params.governanceRequirement?.stale,
    },
    requiredAuthority: Object.freeze([...(params.requiredAuthority || [])]),
    riskLevel: params.riskLevel ?? 'MEDIUM',
    epistemicStatus: params.epistemicStatus ?? 'OBSERVED',
    reasonCodes: Object.freeze([...(params.reasonCodes || [])]),
    evidenceIds: Object.freeze([...(params.evidenceIds || [])]),
    causationId: params.causationId,
    correlationId: params.correlationId,
    expiresAt,
    lifecycleState: params.lifecycleState ?? 'DECIDED',
    recoveryDepth: params.recoveryDepth ?? 1,
    retryCount: params.retryCount ?? 0,
    reconciliationAttempts: params.reconciliationAttempts ?? 0,
    createdAt,
    actionId: params.actionId,
    missionId: params.missionId,
    goalId: params.goalId,
    supersedesDecisionId: params.supersedesDecisionId,
    policySnapshotId: params.policySnapshotId,
    policyVersion: params.policyVersion,
    governanceDecisionId: params.governanceDecisionId,
    recoveryPlanId: params.recoveryPlanId,
    recoveryAttemptId: params.recoveryAttemptId,
    reconciliationId: params.reconciliationId,
    compensationId: params.compensationId,
    originalOperationId: params.originalOperationId,
    approvalIdentity: params.approvalIdentity,
    governanceDecision: params.governanceDecision,
    metadata: sanitizedMetadata ? Object.freeze(sanitizedMetadata) : undefined,
  };

  return deepFreeze(decision);
}



