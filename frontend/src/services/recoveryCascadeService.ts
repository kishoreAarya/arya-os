/**
 * AryaOS V1 — Stage 23: Cascading Failure & Autonomous Boundary Protection
 *
 * Phase 7: Protects AryaOS from cascading recovery/reaction/compensation failures,
 * retry amplification, dependency propagation, resource exhaustion, repeated authorization
 * denials, external uncertainty loops, and unbounded autonomous cascades.
 *
 * ABSOLUTE BOUNDARIES:
 * - CONTROL AND BOUNDARY PROTECTION ONLY: Zero direct execution, zero direct scheduling.
 * - Does NOT replace Stage 09 crash recovery, Stage 12 mission control, Stage 15 Action Bus,
 *   Stage 16 connector permissions, Stage 19 trigger engine, Stage 20 policy intelligence,
 *   Stage 21 governance control plane, or Stage 22 operational audit.
 * - Fail-closed: Never interpret uncertainty as permission.
 * - Deterministic, bounded threshold evaluation: Zero LLM token consumption.
 * - Anti-looping: Enforces MAX_CASCADE_DEPTH (5) and MAX_CONCURRENT_AFFECTED_OPERATIONS (50).
 */

import {
  CascadeClassification,
  CascadeContainmentControl,
  CascadeLifecycleState,
  CascadeEvidence,
  CascadeRecord,
  CascadeContainmentDecision,
  MAX_FAILURES_PER_OPERATION,
  MAX_FAILURES_PER_DEPENDENCY,
  MAX_FAILURES_PER_CONNECTOR,
  MAX_FAILURES_PER_PROVIDER,
  MAX_CASCADE_DEPTH,
  MAX_CONCURRENT_AFFECTED_OPERATIONS,
  MAX_REPEATED_UNKNOWN_STATE,
  MAX_COMPENSATION_FAILURES,
  MAX_RECOVERY_DEPTH,
  FailureClassification,
} from '../types/recoveryControl';
import {
  createCascadeRecord,
  createCascadeContainmentDecision,
  validateAndSanitizePayload,
  RecoveryContractViolationError,
  deepFreeze,
} from './recoveryControl';
import { GovernanceActor } from '../types/governanceControlPlane';

export class RecoveryCascadeService {
  private readonly activeCascades: Map<string, CascadeRecord> = new Map();
  private readonly activeDecisions: Map<string, CascadeContainmentDecision> = new Map();

  /**
   * Deterministically classifies whether an operational failure pattern represents
   * a cascade, and establishes autonomous containment boundaries.
   * Zero LLM tokens; pure empirical evidence evaluation.
   */
  public detectCascade(evidence: CascadeEvidence): Readonly<CascadeRecord> {
    if (!evidence) {
      throw new RecoveryContractViolationError('CascadeEvidence is mandatory');
    }
    if (!evidence.rootOperationId || evidence.rootOperationId.trim() === '') {
      throw new RecoveryContractViolationError('rootOperationId is mandatory');
    }

    // Security check: reject prototype pollution and credential leakage
    if (evidence.metadata) {
      validateAndSanitizePayload(evidence.metadata);
    }

    // Bounds check: affected operations cannot exceed safety limit
    const affectedOperations = evidence.affectedOperationIds ? [...evidence.affectedOperationIds] : [evidence.rootOperationId];
    if (affectedOperations.length > MAX_CONCURRENT_AFFECTED_OPERATIONS) {
      throw new RecoveryContractViolationError(
        `Affected operations count ${affectedOperations.length} exceeds safety limit of ${MAX_CONCURRENT_AFFECTED_OPERATIONS}`
      );
    }

    const timestamp = Date.now();
    const nonce = Math.random().toString(36).substring(2, 7);
    const cascadeId = `casc_${evidence.rootOperationId}_${timestamp}_${nonce}`;
    const causationId = evidence.causationId || evidence.rootOperationId;
    const correlationId = evidence.correlationId || evidence.rootOperationId;
    const failureClass: FailureClassification = evidence.rootFailureClassification || 'SYSTEM_INTERRUPTION';

    // ------------------------------------------------------------------------
    // INVARIANT 1: A single, isolated failure does NOT establish a cascade
    // ------------------------------------------------------------------------
    const isIsolatedFailure =
      (evidence.failureCount === undefined || evidence.failureCount <= 1) &&
      (evidence.sameClassFailures === undefined || evidence.sameClassFailures <= 1) &&
      (evidence.recoveryChainDepth === undefined || evidence.recoveryChainDepth <= 1) &&
      (evidence.dependencyFailures === undefined || evidence.dependencyFailures === 0) &&
      (evidence.connectorFailures === undefined || evidence.connectorFailures === 0) &&
      (evidence.providerFailures === undefined || evidence.providerFailures === 0) &&
      (evidence.unknownStateCount === undefined || evidence.unknownStateCount <= 1) &&
      (evidence.compensationFailureCount === undefined || evidence.compensationFailureCount === 0) &&
      (!evidence.affectedMissionIds || evidence.affectedMissionIds.length < 2) &&
      (!evidence.governanceDenials || evidence.governanceDenials < 2) &&
      !evidence.staleApproval &&
      !evidence.stalePolicy &&
      !evidence.unknownGovernance &&
      !evidence.resourceSaturation &&
      !evidence.triggerCycleDetected &&
      (!evidence.reactionDepth || evidence.reactionDepth < 3);

    if (isIsolatedFailure) {
      return createCascadeRecord({
        cascadeId,
        rootOperationId: evidence.rootOperationId,
        failureClass,
        cascadeClass: 'NO_CASCADE',
        severity: 'LOW',
        depth: 1,
        affectedOperationIds: affectedOperations,
        affectedMissionIds: evidence.affectedMissionIds ? [...evidence.affectedMissionIds] : undefined,
        affectedConnectorIds: evidence.affectedConnectorIds ? [...evidence.affectedConnectorIds] : undefined,
        affectedProviderIds: evidence.affectedProviderIds ? [...evidence.affectedProviderIds] : undefined,
        causationId,
        correlationId,
        detectedAt: timestamp,
        expiresAt: timestamp + 300000,
        lifecycleState: 'CLASSIFIED',
        containmentAction: 'ALLOW',
        authorityRequirement: [],
        metadata: evidence.metadata ? { ...evidence.metadata } : undefined,
      });
    }

    // ------------------------------------------------------------------------
    // INVARIANT 2: Deterministic Evidence-Driven Cascade Classification
    // ------------------------------------------------------------------------
    let cascadeClass: CascadeClassification = 'UNKNOWN_CASCADE';
    let severity: 'LOW' | 'MEDIUM' | 'HIGH' | 'CRITICAL' = 'MEDIUM';
    let containmentAction: CascadeContainmentControl = 'ESCALATE';
    let authorityRequirement: string[] = ['SYSTEM_RECOVERY'];

    // Tier 1: System-wide failure (Resource saturation + repeated external failures)
    if (
      evidence.resourceSaturation &&
      ((evidence.connectorFailures && evidence.connectorFailures >= MAX_FAILURES_PER_CONNECTOR) ||
        (evidence.providerFailures && evidence.providerFailures >= MAX_FAILURES_PER_PROVIDER))
    ) {
      cascadeClass = 'SYSTEM_WIDE_FAILURE';
      severity = 'CRITICAL';
      containmentAction = 'ABORT';
      authorityRequirement = ['SYSTEM_ADMIN_INTERVENTION', 'HUMAN_APPROVAL'];
    }
    // Tier 2: Reaction cascade (Trigger cycles or deep trigger recursion from Stage 19)
    else if (evidence.triggerCycleDetected === true || (evidence.reactionDepth !== undefined && evidence.reactionDepth >= 5)) {
      cascadeClass = 'REACTION_CASCADE';
      severity = 'HIGH';
      containmentAction = 'PAUSE';
      authorityRequirement = ['TRIGGER_GOVERNANCE', 'HUMAN_APPROVAL'];
    }
    // Tier 3: Recovery chain depth exhaustion (Stage 23 recursive recovery guard)
    else if (evidence.recoveryChainDepth !== undefined && evidence.recoveryChainDepth >= MAX_RECOVERY_DEPTH) {
      cascadeClass = 'RECOVERY_CHAIN';
      severity = 'HIGH';
      containmentAction = 'ESCALATE';
      authorityRequirement = ['RECOVERY_GOVERNANCE', 'HUMAN_APPROVAL'];
    }
    // Tier 4: Retry amplification (Excessive consecutive failures on single operation)
    else if (evidence.failureCount !== undefined && evidence.failureCount >= MAX_FAILURES_PER_OPERATION) {
      cascadeClass = 'RETRY_AMPLIFICATION';
      severity = 'MEDIUM';
      containmentAction = 'THROTTLE';
      authorityRequirement = ['RATE_LIMITER_CONTROL'];
    }
    // Tier 5: Dependency propagation (Prerequisite failures blocking graph)
    else if (evidence.dependencyFailures !== undefined && evidence.dependencyFailures >= MAX_FAILURES_PER_DEPENDENCY) {
      cascadeClass = 'DEPENDENCY_FAILURE';
      severity = 'HIGH';
      containmentAction = 'DEFER';
      authorityRequirement = ['DEPENDENCY_ARBITRATION'];
    }
    // Tier 6: Connector failure propagation (Repeated connector transport faults)
    else if (evidence.connectorFailures !== undefined && evidence.connectorFailures >= MAX_FAILURES_PER_CONNECTOR) {
      cascadeClass = 'CONNECTOR_FAILURE';
      severity = 'HIGH';
      containmentAction = 'ISOLATE';
      authorityRequirement = ['CONNECTOR_LIFECYCLE_CONTROL', 'HUMAN_APPROVAL'];
    }
    // Tier 7: Provider failure propagation (Repeated model/gateway errors)
    else if (evidence.providerFailures !== undefined && evidence.providerFailures >= MAX_FAILURES_PER_PROVIDER) {
      cascadeClass = 'PROVIDER_FAILURE';
      severity = 'HIGH';
      containmentAction = 'DEFER';
      authorityRequirement = ['PROVIDER_ROUTER_CONTROL'];
    }
    // Tier 8: Permission failure loop (Repeated Stage 16 revocation / permission denial)
    else if (
      (evidence.sameClassFailures && evidence.sameClassFailures >= 2 && evidence.rootFailureClassification === 'PERMISSION') ||
      evidence.rootFailureClassification === 'PERMISSION'
    ) {
      cascadeClass = 'PERMISSION_FAILURE';
      severity = 'HIGH';
      containmentAction = 'REQUIRE_APPROVAL';
      authorityRequirement = ['CONNECTOR_CREDENTIAL_REAUTHORIZATION', 'HUMAN_APPROVAL'];
    }
    // Tier 9: Policy block (Repeated Stage 20/21 policy DENY)
    else if (
      (evidence.sameClassFailures && evidence.sameClassFailures >= 2 && evidence.rootFailureClassification === 'POLICY') ||
      evidence.rootFailureClassification === 'POLICY'
    ) {
      cascadeClass = 'POLICY_BLOCK';
      severity = 'HIGH';
      containmentAction = 'ABORT';
      authorityRequirement = ['POLICY_ADMINISTRATION'];
    }
    // Tier 10: Repeated unknown external state (Reconciliation required; never blind retry)
    else if (evidence.unknownStateCount !== undefined && evidence.unknownStateCount >= MAX_REPEATED_UNKNOWN_STATE) {
      cascadeClass = 'RECONCILIATION_FAILURE';
      severity = 'HIGH';
      containmentAction = 'REQUIRE_APPROVAL';
      authorityRequirement = ['RECONCILIATION_GATEWAY', 'HUMAN_APPROVAL'];
    }
    // Tier 11: Compensation failure (Compensation error; prevent infinite reverse loops)
    else if (evidence.compensationFailureCount !== undefined && evidence.compensationFailureCount >= MAX_COMPENSATION_FAILURES) {
      cascadeClass = 'COMPENSATION_FAILURE';
      severity = 'HIGH';
      containmentAction = 'ESCALATE';
      authorityRequirement = ['COMPENSATION_ADMINISTRATION', 'HUMAN_APPROVAL'];
    }
    // Tier 12: Resource exhaustion (Memory / disk / quota saturation)
    else if (evidence.resourceSaturation === true) {
      cascadeClass = 'RESOURCE_EXHAUSTION';
      severity = 'HIGH';
      containmentAction = 'THROTTLE';
      authorityRequirement = ['RESOURCE_GOVERNOR'];
    }
    // Tier 13: Governance denials
    else if (evidence.governanceDenials !== undefined && evidence.governanceDenials >= 2) {
      cascadeClass = 'AUTHORIZATION_FAILURE';
      severity = 'HIGH';
      containmentAction = 'REQUIRE_APPROVAL';
      authorityRequirement = ['GOVERNANCE_CONTROL_PLANE', 'HUMAN_APPROVAL'];
    }
    // Tier 14: Mission cascade
    else if (evidence.affectedMissionIds && evidence.affectedMissionIds.length >= 2) {
      cascadeClass = 'MISSION_CASCADE';
      severity = 'HIGH';
      containmentAction = 'PAUSE';
      authorityRequirement = ['MISSION_CONTROL', 'HUMAN_APPROVAL'];
    }

    // ------------------------------------------------------------------------
    // INVARIANT 3: FAIL-CLOSED PRINCIPLE (Section 8)
    // When autonomous authority or operational state is uncertain -> Fail closed!
    // ------------------------------------------------------------------------
    if (evidence.unknownGovernance === true || evidence.staleApproval === true || evidence.stalePolicy === true) {
      containmentAction = 'REQUIRE_APPROVAL';
      severity = 'HIGH';
      authorityRequirement = ['GOVERNANCE_CONTROL_PLANE', 'HUMAN_APPROVAL'];
    }

    const depth = Math.min(evidence.recoveryChainDepth ?? 1, MAX_CASCADE_DEPTH);

    const record = createCascadeRecord({
      cascadeId,
      rootOperationId: evidence.rootOperationId,
      failureClass,
      cascadeClass,
      severity,
      depth,
      affectedOperationIds: affectedOperations,
      affectedMissionIds: evidence.affectedMissionIds ? [...evidence.affectedMissionIds] : undefined,
      affectedConnectorIds: evidence.affectedConnectorIds ? [...evidence.affectedConnectorIds] : undefined,
      affectedProviderIds: evidence.affectedProviderIds ? [...evidence.affectedProviderIds] : undefined,
      causationId,
      correlationId,
      detectedAt: timestamp,
      expiresAt: timestamp + 300000, // 5 minutes TTL
      lifecycleState: 'CLASSIFIED',
      containmentAction,
      authorityRequirement,
      metadata: evidence.metadata ? { ...evidence.metadata } : undefined,
    });

    this.activeCascades.set(cascadeId, record);
    return record;
  }

  /**
   * Formulates a deterministic CascadeContainmentDecision.
   * Note: This produces a control recommendation; it does NOT execute actions directly.
   */
  public formulateContainmentDecision(cascade: CascadeRecord): Readonly<CascadeContainmentDecision> {
    if (!cascade) {
      throw new RecoveryContractViolationError('CascadeRecord is mandatory');
    }

    const timestamp = Date.now();
    const containmentId = `cont_${cascade.cascadeId}_${timestamp}`;
    const requiresHumanApproval =
      cascade.severity === 'HIGH' ||
      cascade.severity === 'CRITICAL' ||
      cascade.containmentAction === 'ISOLATE' ||
      cascade.containmentAction === 'ABORT';

    const decision = createCascadeContainmentDecision({
      containmentId,
      cascadeId: cascade.cascadeId,
      recommendedControl: cascade.containmentAction,
      severity: cascade.severity,
      affectedScope: {
        operationIds: [...cascade.affectedOperationIds],
        connectorIds: cascade.affectedConnectorIds ? [...cascade.affectedConnectorIds] : undefined,
        providerIds: cascade.affectedProviderIds ? [...cascade.affectedProviderIds] : undefined,
        missionIds: cascade.affectedMissionIds ? [...cascade.affectedMissionIds] : undefined,
      },
      reasonCodes: [`CASCADE_${cascade.cascadeClass}`, `CONTROL_${cascade.containmentAction}`],
      evidenceIds: cascade.evidenceReferences ? [...cascade.evidenceReferences] : [`ev_${cascade.cascadeId}`],
      requiredAuthority: [...cascade.authorityRequirement],
      approvalRequirement: {
        required: requiresHumanApproval,
        humanOperatorRequired: requiresHumanApproval,
      },
      expiresAt: cascade.expiresAt,
      causationId: cascade.causationId,
      correlationId: cascade.correlationId,
      lifecycleState: 'CONTAINMENT_PROPOSED',
      timestamp,
      metadata: cascade.metadata ? { ...cascade.metadata } : undefined,
    });

    this.activeDecisions.set(containmentId, decision);
    return decision;
  }

  /**
   * Applies an authenticated human approval to a proposed containment decision.
   * Bound to Stage 21 Governance requirements (actorType === 'USER').
   * Rejects SYSTEM and AUTONOMOUS_AGENT.
   */
  public applyHumanApproval(
    decision: CascadeContainmentDecision,
    approval: {
      actor: GovernanceActor;
      governanceDecisionId: string;
      timestamp?: number;
    }
  ): Readonly<CascadeContainmentDecision> {
    if (!decision) {
      throw new RecoveryContractViolationError('CascadeContainmentDecision is mandatory');
    }
    if (!approval || !approval.actor) {
      throw new RecoveryContractViolationError('Approval actor is mandatory');
    }
    if (approval.actor.actorType !== 'USER') {
      throw new RecoveryContractViolationError(
        `Invalid approval actor type '${approval.actor.actorType}'. Only authenticated human operators ('USER') can authorize cascade containment.`
      );
    }
    if (!approval.actor.actorId || approval.actor.actorId.trim() === '') {
      throw new RecoveryContractViolationError('actor.actorId cannot be empty');
    }
    if (!approval.governanceDecisionId || approval.governanceDecisionId.trim() === '') {
      throw new RecoveryContractViolationError('governanceDecisionId cannot be empty');
    }

    if (decision.lifecycleState !== 'CONTAINMENT_PROPOSED' && decision.lifecycleState !== 'GOVERNED') {
      throw new RecoveryContractViolationError(
        `Cannot apply approval to containment decision in '${decision.lifecycleState}' state (must be CONTAINMENT_PROPOSED or GOVERNED)`
      );
    }

    const updatedDecision: CascadeContainmentDecision = {
      ...decision,
      approvalRequirement: {
        required: true,
        humanOperatorRequired: true,
        approvedBy: approval.actor.actorId,
        approvedAt: approval.timestamp ?? Date.now(),
      },
      governanceDecisionId: approval.governanceDecisionId,
      lifecycleState: 'CONTAINED',
    };

    const frozen = deepFreeze(updatedDecision);
    this.activeDecisions.set(decision.containmentId, frozen);
    return frozen;
  }

  /**
   * Transitions a cascade record through its deterministic lifecycle.
   * Enforces illegal transition rejection.
   */
  public transitionLifecycle(
    record: CascadeRecord,
    nextState: CascadeLifecycleState
  ): Readonly<CascadeRecord> {
    if (!record) {
      throw new RecoveryContractViolationError('CascadeRecord is mandatory');
    }

    const validTransitions: Record<CascadeLifecycleState, readonly CascadeLifecycleState[]> = {
      DETECTED: ['CLASSIFIED', 'ABORTED', 'EXPIRED'],
      CLASSIFIED: ['ASSESSED', 'CONTAINMENT_PROPOSED', 'ABORTED', 'EXPIRED'],
      ASSESSED: ['CONTAINMENT_PROPOSED', 'GOVERNED', 'ABORTED', 'EXPIRED'],
      CONTAINMENT_PROPOSED: ['GOVERNED', 'CONTAINED', 'REJECTED', 'ABORTED', 'EXPIRED'],
      GOVERNED: ['CONTAINED', 'REJECTED', 'ABORTED', 'EXPIRED'],
      CONTAINED: ['MONITORED', 'RECOVERED', 'ESCALATED', 'UNRESOLVED'],
      MONITORED: ['RECOVERED', 'ESCALATED', 'CONTAINED', 'UNRESOLVED'],
      RECOVERED: [], // Terminal
      REJECTED: [],  // Terminal
      EXPIRED: [],   // Terminal
      ESCALATED: ['CONTAINED', 'UNRESOLVED'],
      UNRESOLVED: ['ESCALATED', 'ABORTED'],
      ABORTED: [],   // Terminal
    };

    const allowed = validTransitions[record.lifecycleState] || [];
    if (!allowed.includes(nextState)) {
      throw new RecoveryContractViolationError(
        `Illegal cascade lifecycle transition from '${record.lifecycleState}' to '${nextState}'`
      );
    }

    const updated: CascadeRecord = {
      ...record,
      lifecycleState: nextState,
    };

    const frozen = deepFreeze(updated);
    this.activeCascades.set(record.cascadeId, frozen);
    return frozen;
  }

  public getActiveCascade(cascadeId: string): CascadeRecord | undefined {
    return this.activeCascades.get(cascadeId);
  }

  public getActiveDecision(containmentId: string): CascadeContainmentDecision | undefined {
    return this.activeDecisions.get(containmentId);
  }

  public clear(): void {
    this.activeCascades.clear();
    this.activeDecisions.clear();
  }
}

export const recoveryCascadeService = new RecoveryCascadeService();
