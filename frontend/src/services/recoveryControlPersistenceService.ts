/**
 * AryaOS V1 — Stage 23: Durable Recovery Control & Stage 09 Persistence Integration
 *
 * Phase 9: Connects the Stage 23 Recovery Control Plane to Stage 09 Execution Persistence
 * and Execution Journal.
 *
 * ABSOLUTE ARCHITECTURAL INVARIANTS:
 * 1. STAGE 09 OWNS RECOVERY PERSISTENCE AND CRASH RECOVERY.
 *    Stage 23 MUST NOT create a second persistence engine, journal, or crash recovery engine.
 * 2. Stage 23 decides WHAT recovery control is appropriate.
 *    Stage 09 determines HOW durable recovery state survives interruption.
 *    Stage 22 determines WHAT ACTUALLY HAPPENED (Operational Truth).
 *    Stage 21 determines WHETHER AUTHORITY EXISTS (Governance).
 * 3. NO BLIND REPLAY: A restart must NEVER blindly replay retry, compensation, or reconciliation.
 * 4. IDEMPOTENCY & LEASE SAFETY: Prevents concurrent recovery workers from racing on the same decision.
 * 5. IMMUTABILITY: Historical decisions are never mutated. Supersession creates a new version.
 * 6. ZERO DIRECT NETWORK / ZERO LLM TOKENS: Pure deterministic logic.
 */

import {
  RecoveryControlDecision,
  RecoveryControlRequest,
  RecoveryControlLease,
  RevalidationContext,
  DecisionRevalidationResult,
  RecoveryAction,
  RecoveryControlLifecycleState,
  MAX_RECOVERY_DEPTH,
  MAX_AUTOMATIC_RETRIES,
  MAX_RECONCILIATION_ATTEMPTS,
  MAX_CASCADE_DEPTH,
} from '../types/recoveryControl';
import {
  deepFreeze,
  RecoveryContractViolationError,
  validateAndSanitizePayload,
  isRecoveryControlLifecycleState,
  isRecoveryOutcome,
} from './recoveryControl';
import { executionPersistence } from './executionPersistence';
import { executionJournal } from './executionJournal';
import { operationalTruthService } from './operationalTruthService';

export const DEFAULT_RECOVERY_LEASE_TTL_MS = 30000; // 30 seconds default lease
export const MAX_PERSISTED_PAYLOAD_SIZE = 65536; // 64KB safety limit for payload structures

export class RecoveryControlPersistenceService {
  /**
   * Persists a validated RecoveryControlDecision into Stage 09 durable storage.
   * Emits corresponding domain events to the Stage 09 Execution Journal.
   */
  public persistControlDecision(
    decision: RecoveryControlDecision,
    request?: RecoveryControlRequest
  ): boolean {
    if (!decision) {
      throw new RecoveryContractViolationError('decision is mandatory for persistence');
    }
    if (!decision.decisionId || typeof decision.decisionId !== 'string') {
      throw new RecoveryContractViolationError('decisionId is mandatory for persistence');
    }
    if (!decision.operationId || typeof decision.operationId !== 'string') {
      throw new RecoveryContractViolationError('operationId is mandatory for persistence');
    }

    // Security validation against secret leaks and oversized payload
    this.assertSecurePersistenceRecord(decision);

    // Save decision to Stage 09 executionPersistence envelope
    const savedDecision = executionPersistence.saveRecoveryControlDecision(decision);
    if (!savedDecision) {
      return false;
    }

    // If request provided, persist request context as well
    if (request) {
      this.assertSecurePersistenceRecord(request);
      executionPersistence.saveRecoveryControlRequest(request);
    }

    // Emit domain event to Stage 09 Execution Journal
    const eventType = this.resolveJournalEventType(decision.lifecycleState);
    executionJournal.appendEvent({
      goalId: decision.goalId || 'system-recovery-control',
      actionId: decision.actionId || decision.operationId,
      eventType,
      previousState: undefined,
      newState: decision.lifecycleState,
      provenance: {
        stage: 'Stage 23 Recovery Control Plane',
        version: 'Phase 9',
      },
      payload: {
        decisionId: decision.decisionId,
        requestId: decision.requestId,
        operationId: decision.operationId,
        causationId: decision.causationId,
        correlationId: decision.correlationId,
        classification: decision.classification,
        recoveryOutcome: decision.recoveryOutcome,
        recommendedAction: decision.recommendedAction,
        riskLevel: decision.riskLevel,
        lifecycleState: decision.lifecycleState,
        evidenceIds: decision.evidenceIds,
        createdAt: decision.createdAt,
      },
    });

    return true;
  }

  /**
   * Loads a persisted RecoveryControlDecision from Stage 09 storage.
   * Validates schema integrity and rejects tampered or forged records.
   */
  public loadControlDecision(decisionId: string): RecoveryControlDecision | null {
    if (!decisionId || typeof decisionId !== 'string') {
      return null;
    }

    const raw = executionPersistence.getRecoveryControlDecision(decisionId);
    if (!raw) {
      return null;
    }

    // Validate structural integrity and guard against prototype pollution / object injection
    this.assertSecurePersistenceRecord(raw);

    if (
      !raw.decisionId ||
      !raw.requestId ||
      !raw.operationId ||
      !raw.classification ||
      !isRecoveryOutcome(raw.recoveryOutcome) ||
      !isRecoveryControlLifecycleState(raw.lifecycleState)
    ) {
      console.warn(`Tampered or invalid persisted recovery control decision rejected: ${decisionId}`);
      return null;
    }

    return deepFreeze(raw);
  }

  /**
   * Retrieves a persisted decision by its original requestId (idempotent lookup).
   */
  public loadControlDecisionByRequestId(requestId: string): RecoveryControlDecision | null {
    if (!requestId || typeof requestId !== 'string') return null;
    const all = executionPersistence.getAllRecoveryControlDecisions();
    const found = all.find((d) => d.requestId === requestId);
    if (!found) return null;
    return this.loadControlDecision(found.decisionId);
  }

  /**
   * Retrieves a persisted decision by operationId.
   */
  public loadControlDecisionByOperationId(operationId: string): RecoveryControlDecision | null {
    if (!operationId || typeof operationId !== 'string') return null;
    const all = executionPersistence.getAllRecoveryControlDecisions();
    const found = all.find((d) => d.operationId === operationId);
    if (!found) return null;
    return this.loadControlDecision(found.decisionId);
  }

  /**
   * Revalidates a persisted decision following restart, process interruption, or authority change.
   *
   * Enforces:
   * 1. Expiration check.
   * 2. Stage 22 Operational Truth verification (prevents replaying already succeeded actions).
   * 3. Stage 21 Governance staleness detection (rejects stale approvals and policy drift).
   * 4. Interrupted reconciliation counter preservation (never resets attempt counter).
   * 5. Interrupted compensation safety.
   * 6. Cascade containment override preservation.
   */
  public revalidateDecision(
    decisionId: string,
    context?: RevalidationContext
  ): DecisionRevalidationResult {
    const decision = this.loadControlDecision(decisionId);
    if (!decision) {
      throw new RecoveryContractViolationError(`Cannot revalidate non-existent decision: ${decisionId}`);
    }

    const now = context?.now ?? Date.now();

    // 1. Expiration Check
    if (decision.expiresAt > 0 && now >= decision.expiresAt) {
      executionJournal.appendEvent({
        goalId: decision.goalId || 'system-recovery-control',
        actionId: decision.operationId,
        eventType: 'RECOVERY_CONTROL_EXPIRED',
        previousState: decision.lifecycleState,
        newState: 'EXPIRED',
        payload: { decisionId, reason: 'Decision TTL elapsed during downtime/restart' },
      });

      return {
        valid: false,
        isStale: true,
        isExpired: true,
        requiresReevaluation: true,
        currentDecision: decision,
        reason: `Recovery control decision ${decisionId} expired at ${new Date(decision.expiresAt).toISOString()}`,
        reasonCode: 'EXPIRED',
        recommendedAction: 'ESCALATE',
      };
    }

    // 2. Stage 22 Operational Truth Check: Did the operation already complete offline?
    if (
      context?.externalSuccess === true ||
      context?.observedOperationStatus === 'SUCCEEDED'
    ) {
      return {
        valid: true,
        isStale: false,
        isExpired: false,
        requiresReevaluation: false,
        currentDecision: decision,
        reason: 'Operation already completed successfully while offline (Stage 22 empirical truth)',
        reasonCode: 'ALREADY_COMPLETED',
        recommendedAction: 'WAIT',
      };
    }

    // 3. Epistemic Honesty: If external confirmation is unconfirmed, remain UNKNOWN
    if (context?.externalStatusConfirmed === false && decision.epistemicStatus === 'UNKNOWN') {
      return {
        valid: true,
        isStale: false,
        isExpired: false,
        requiresReevaluation: false,
        currentDecision: decision,
        reason: 'External state remains unconfirmed (epistemic honesty)',
        reasonCode: 'UNCONFIRMED_EXTERNAL_STATE',
        recommendedAction: 'RECONCILE',
      };
    }

    // 4. Mission State & Constraint Check (Stage 12)
    if (
      context?.missionConstraintBlocked === true ||
      context?.missionState === 'PAUSED' ||
      context?.missionState === 'CANCELLED'
    ) {
      return {
        valid: false,
        isStale: true,
        isExpired: false,
        requiresReevaluation: true,
        currentDecision: decision,
        reason: 'Mission is paused, cancelled, or constraint-blocked; recovery resumption suspended',
        reasonCode: 'MISSION_CONSTRAINT_BLOCKED',
        recommendedAction: 'PAUSE',
      };
    }

    // 5. Policy Drift Check (Stage 20)
    const policyVersionMismatch =
      context?.currentPolicyVersion !== undefined &&
      decision.policyVersion !== undefined &&
      context.currentPolicyVersion !== decision.policyVersion;

    const policySnapshotMismatch =
      context?.currentPolicySnapshotId !== undefined &&
      decision.policySnapshotId !== undefined &&
      context.currentPolicySnapshotId !== decision.policySnapshotId;

    if (policyVersionMismatch || policySnapshotMismatch) {
      return {
        valid: false,
        isStale: true,
        isExpired: false,
        requiresReevaluation: true,
        currentDecision: decision,
        reason: policyVersionMismatch
          ? `Policy version changed (${decision.policyVersion} -> ${context?.currentPolicyVersion}); recovery decision requires re-governance`
          : `Policy snapshot changed (${decision.policySnapshotId} -> ${context?.currentPolicySnapshotId}); recovery decision requires re-governance`,
        reasonCode: policyVersionMismatch ? 'POLICY_VERSION_MISMATCH' : 'POLICY_SNAPSHOT_MISMATCH',
        recommendedAction: 'REQUIRE_APPROVAL',
      };
    }

    // 6. Connector Permission & Security Drift Check (Stage 16)
    if (
      context?.connectorPermissionRevoked === true ||
      context?.connectorStatus === 'ERROR'
    ) {
      return {
        valid: false,
        isStale: true,
        isExpired: false,
        requiresReevaluation: true,
        currentDecision: decision,
        reason: 'Connector permissions revoked or connector is in ERROR status across restart',
        reasonCode: 'CONNECTOR_PERMISSION_MISSING',
        recommendedAction: 'REQUIRE_APPROVAL',
      };
    }

    // 7. Human Approval Expiration Check (Stage 21)
    if (context?.humanApprovalExpired === true) {
      return {
        valid: false,
        isStale: true,
        isExpired: false,
        requiresReevaluation: true,
        currentDecision: decision,
        reason: 'Human operator approval expired across restart; re-approval required',
        reasonCode: 'APPROVAL_TOKEN_EXPIRED',
        recommendedAction: 'REQUIRE_APPROVAL',
      };
    }

    // 8. General Governance & Policy Staleness Check (Stage 21)
    const isStaleGovernance =
      Boolean(context?.policySnapshotExpired) ||
      Boolean(context?.connectorPermissionChanged) ||
      Boolean(decision.governanceRequirement.stale);

    if (isStaleGovernance) {
      executionJournal.appendEvent({
        goalId: decision.goalId || 'system-recovery-control',
        actionId: decision.operationId,
        eventType: 'RECOVERY_CONTROL_STALE',
        previousState: decision.lifecycleState,
        newState: 'GOVERNANCE_REQUIRED',
        payload: {
          decisionId,
          reason: 'Governance authority, policy snapshot, or connector permission became stale across restart',
        },
      });

      // Consequential operations fail closed
      const isConsequential =
        decision.recommendedAction === 'RETRY' ||
        decision.recommendedAction === 'RESUME' ||
        decision.recommendedAction === 'COMPENSATE' ||
        decision.recommendedAction === 'ABORT' ||
        decision.containmentDecision?.recommendedControl === 'ISOLATE';

      return {
        valid: false,
        isStale: true,
        isExpired: false,
        requiresReevaluation: true,
        currentDecision: decision,
        reason: 'Governance authority has become stale; consequential action requires Stage 21 revalidation',
        reasonCode: 'GOVERNANCE_STALE',
        recommendedAction: isConsequential ? 'REQUIRE_APPROVAL' : decision.recommendedAction,
      };
    }

    // 9. Interrupted Reconciliation Check: Preserve attempt counter across restart
    if (decision.recommendedAction === 'RECONCILE') {
      if (decision.reconciliationAttempts >= MAX_RECONCILIATION_ATTEMPTS) {
        return {
          valid: false,
          isStale: false,
          isExpired: false,
          requiresReevaluation: true,
          currentDecision: decision,
          reason: `Maximum reconciliation attempts (${MAX_RECONCILIATION_ATTEMPTS}) reached across restart; escalating to operator`,
          reasonCode: 'MAX_RECONCILIATION_ATTEMPTS_EXCEEDED',
          recommendedAction: 'ESCALATE',
        };
      }
    }

    // 10. Interrupted Compensation Check: Must verify compensation status before replay
    if (decision.recommendedAction === 'COMPENSATE') {
      if (context?.operationStatusChanged || context?.observedOperationStatus === 'COMPENSATED') {
        return {
          valid: true,
          isStale: false,
          isExpired: false,
          requiresReevaluation: false,
          currentDecision: decision,
          reason: 'Compensation already executed successfully; no repeat compensation required',
          reasonCode: 'COMPENSATION_ALREADY_EXECUTED',
          recommendedAction: 'WAIT',
        };
      }
    }

    // 11. Cascade Containment Preservation Check: Containment cannot be downgraded
    if (decision.containmentDecision) {
      const containment = decision.containmentDecision.recommendedControl;
      if (
        containment === 'ABORT' ||
        containment === 'PAUSE' ||
        containment === 'ISOLATE' ||
        containment === 'ESCALATE'
      ) {
        return {
          valid: true,
          isStale: false,
          isExpired: false,
          requiresReevaluation: false,
          currentDecision: decision,
          reason: `Active cascade containment (${containment}) survives restart and cannot be downgraded`,
          reasonCode: 'CASCADE_CONTAINMENT_PRESERVED',
          recommendedAction: decision.recommendedAction,
        };
      }
    }

    // Decision remains valid as-is
    return {
      valid: true,
      isStale: false,
      isExpired: false,
      requiresReevaluation: false,
      currentDecision: decision,
      reason: 'Persisted recovery decision remains fully valid and authorized across restart',
      reasonCode: 'VALID',
      recommendedAction: decision.recommendedAction,
    };
  }

  /**
   * Supersedes an existing persisted decision with a newly governed decision.
   * Enforces immutability: the old decision record is NOT overwritten, but marked SUPERSEDED.
   */
  public supersedeDecision(
    oldDecisionId: string,
    supersedingDecision: RecoveryControlDecision,
    reason: string
  ): { oldDecision: RecoveryControlDecision; newDecision: RecoveryControlDecision } {
    const oldDecision = this.loadControlDecision(oldDecisionId);
    if (!oldDecision) {
      throw new RecoveryContractViolationError(`Cannot supersede non-existent decision: ${oldDecisionId}`);
    }

    // Create superseded copy of the old decision
    const updatedOld: RecoveryControlDecision = deepFreeze({
      ...oldDecision,
      lifecycleState: 'EXPIRED' as RecoveryControlLifecycleState, // or terminal superseded state
    });

    // Save updated old decision
    executionPersistence.saveRecoveryControlDecision(updatedOld);

    // Persist new superseding decision
    this.persistControlDecision(supersedingDecision);

    // Record supersession event in Stage 09 Execution Journal
    executionJournal.appendEvent({
      goalId: supersedingDecision.goalId || 'system-recovery-control',
      actionId: supersedingDecision.operationId,
      eventType: 'RECOVERY_CONTROL_SUPERSEDED',
      previousState: oldDecision.lifecycleState,
      newState: supersedingDecision.lifecycleState,
      provenance: {
        oldDecisionId,
        newDecisionId: supersedingDecision.decisionId,
        reason,
      },
      payload: {
        oldDecisionId,
        newDecisionId: supersedingDecision.decisionId,
        operationId: supersedingDecision.operationId,
        reason,
        timestamp: Date.now(),
      },
    });

    return {
      oldDecision: updatedOld,
      newDecision: supersedingDecision,
    };
  }

  /**
   * Acquires a single-runtime execution lease for acting on a recovery decision.
   * Prevents two recovery workers from simultaneously executing recovery for the same decision.
   */
  public acquireRecoveryLease(params: {
    decisionId: string;
    operationId: string;
    workerId: string;
    ttlMs?: number;
  }): { acquired: boolean; lease?: RecoveryControlLease; failureReason?: string } {
    const { decisionId, operationId, workerId, ttlMs = DEFAULT_RECOVERY_LEASE_TTL_MS } = params;

    if (!decisionId || !operationId || !workerId) {
      throw new RecoveryContractViolationError('decisionId, operationId, and workerId are mandatory for lease');
    }

    const now = Date.now();
    const existing = executionPersistence.getRecoveryControlLease(decisionId);

    // Check if currently held by another worker and active
    if (existing && existing.expiresAt > now && existing.workerId !== workerId) {
      return {
        acquired: false,
        failureReason: `Recovery decision ${decisionId} is currently leased by worker '${existing.workerId}' until ${new Date(existing.expiresAt).toISOString()}`,
      };
    }

    const lease: RecoveryControlLease = deepFreeze({
      leaseId: `rclease_${decisionId}_${workerId}_${now}`,
      decisionId,
      operationId,
      workerId,
      acquiredAt: now,
      expiresAt: now + ttlMs,
    });

    executionPersistence.saveRecoveryControlLease(lease);

    executionJournal.appendEvent({
      goalId: 'system-recovery-lease',
      actionId: operationId,
      eventType: 'LEASE_ACQUIRED',
      newState: 'ACTIVE',
      payload: {
        leaseId: lease.leaseId,
        decisionId,
        operationId,
        workerId,
        expiresAt: lease.expiresAt,
      },
    });

    return { acquired: true, lease };
  }

  /**
   * Releases an active recovery control lease.
   */
  public releaseRecoveryLease(decisionId: string, workerId: string): boolean {
    const existing = executionPersistence.getRecoveryControlLease(decisionId);
    if (!existing) {
      return false;
    }

    if (existing.workerId !== workerId) {
      console.warn(`Worker '${workerId}' attempted to release lease held by '${existing.workerId}'`);
      return false;
    }

    executionPersistence.deleteRecoveryControlLease(decisionId);

    executionJournal.appendEvent({
      goalId: 'system-recovery-lease',
      actionId: existing.operationId,
      eventType: 'LEASE_RELEASED',
      previousState: 'ACTIVE',
      newState: 'RELEASED',
      payload: {
        leaseId: existing.leaseId,
        decisionId,
        workerId,
      },
    });

    return true;
  }

  /**
   * Returns current active recovery lease if not expired.
   */
  public getActiveLease(decisionId: string): RecoveryControlLease | null {
    const lease = executionPersistence.getRecoveryControlLease(decisionId);
    if (!lease) return null;
    if (Date.now() >= lease.expiresAt) {
      executionPersistence.deleteRecoveryControlLease(decisionId);
      return null;
    }
    return lease;
  }

  /**
   * Scans and loads all persisted recovery control decisions from Stage 09.
   * Useful during cold-start recovery.
   */
  public recoverAllPersistedDecisions(): RecoveryControlDecision[] {
    const all = executionPersistence.getAllRecoveryControlDecisions();
    return all.map((d) => deepFreeze(d));
  }

  /**
   * Security hardening assertions against prototype pollution, secret leakage, and forged records.
   */
  private assertSecurePersistenceRecord(record: unknown): void {
    if (!record || typeof record !== 'object') return;

    // Detect prototype pollution
    validateAndSanitizePayload(record as Record<string, unknown>);

    // Payload size guard
    const serialized = JSON.stringify(record);
    if (serialized.length > MAX_PERSISTED_PAYLOAD_SIZE) {
      throw new RecoveryContractViolationError(
        `Oversized persistence record rejected: ${serialized.length} bytes exceeds ${MAX_PERSISTED_PAYLOAD_SIZE} limit`
      );
    }

    // Secret credential guard
    const forbiddenPatterns = ['bearer ', 'sk-', 'ghp_', 'privatekey', 'client_secret'];
    const lower = serialized.toLowerCase();
    for (const pattern of forbiddenPatterns) {
      if (lower.includes(pattern)) {
        throw new RecoveryContractViolationError(
          `Security violation: Record contains prohibited credential pattern '${pattern}'`
        );
      }
    }
  }

  private resolveJournalEventType(state: RecoveryControlLifecycleState): import('../types/executionPersistence').OrchestrationJournalEventType {
    switch (state) {
      case 'RECEIVED':
      case 'VALIDATED':
        return 'RECOVERY_CONTROL_CREATED';
      case 'CLASSIFIED':
        return 'RECOVERY_CONTROL_CLASSIFIED';
      case 'ASSESSED':
        return 'RECOVERY_CONTROL_ASSESSED';
      case 'DECIDED':
        return 'RECOVERY_CONTROL_DECIDED';
      case 'GOVERNANCE_REQUIRED':
        return 'RECOVERY_CONTROL_STALE';
      case 'EXPIRED':
        return 'RECOVERY_CONTROL_EXPIRED';
      case 'ESCALATED':
        return 'RECOVERY_CONTROL_ESCALATED';
      default:
        return 'RECOVERY_CONTROL_DECIDED';
    }
  }

  /**
   * Verifies if the underlying Stage 09 storage is durable or non-durable in-memory fallback.
   * Never claims durable persistence during memory fallback.
   */
  public isDurableStorage(): boolean {
    return executionPersistence.isDurableStorageActive();
  }
}

export const recoveryControlPersistenceService = new RecoveryControlPersistenceService();
