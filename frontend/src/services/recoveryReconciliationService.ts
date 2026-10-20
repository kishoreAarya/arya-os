/**
 * AryaOS V1 — Stage 23: Reconciliation Service & Safe Probe Control
 *
 * Phase 5: Coordinates safe, bounded, read-only reconciliation probes to determine
 * whether an UNKNOWN external operation has actually succeeded, failed, or remains unknown.
 *
 * ABSOLUTE BOUNDARIES:
 * - ZERO direct network calls (no fetch, no Axios, no provider SDK, no raw sockets).
 * - ZERO mutation replay (reconciliation is READ-ONLY inquiry, NEVER repeating the original side effect).
 * - All external execution delegates strictly to Stage 15 Action Bus or Stage 07 Execution Gateway.
 * - Epistemic honesty: probe failure != original operation failure. Uncertainty is strictly preserved.
 * - Bounded attempts (max 3) preventing infinite loops.
 */

import {
  RecoveryPlan,
  ReconciliationRequest,
  ReconciliationResultRecord,
  PlanReconciliationInput,
  ReconciliationOutcome,
  ReconciliationEpistemicStatus,
  ReconciliationProbeIntent,
  MAX_RECONCILIATION_ATTEMPTS,
} from '../types/recoveryControl';
import {
  createReconciliationRequest,
  createReconciliationResultRecord,
  validateAndSanitizePayload,
  RecoveryContractViolationError,
} from './recoveryControl';
import { actionBusService } from './actionBusService';
import { executionGateway } from './executionGateway';

export interface ReconciliationExecutionBoundary {
  executeActionBusProbe?: (request: {
    capabilityId: string;
    operation: string;
    parameters: Record<string, unknown>;
    idempotencyKey: string;
  }) => Promise<{ success: boolean; data?: unknown; error?: unknown; notFound?: boolean }>;
  executeGatewayProbe?: (idempotencyKey: string) => Promise<{ completed: boolean; result?: unknown; error?: unknown }>;
}

export class RecoveryReconciliationService {
  /**
   * Formulates a bounded, read-only ReconciliationRequest for an uncertain operation.
   * Does NOT execute the probe.
   */
  public planReconciliation(input: PlanReconciliationInput): Readonly<ReconciliationRequest> {
    if (!input || !input.plan) {
      throw new RecoveryContractViolationError('RecoveryPlan is mandatory for planning reconciliation');
    }
    const plan = input.plan;
    if (!plan.originalOperationId || plan.originalOperationId.trim() === '') {
      throw new RecoveryContractViolationError('plan.originalOperationId is mandatory');
    }
    if (!plan.causationId || plan.causationId.trim() === '') {
      throw new RecoveryContractViolationError('plan.causationId is mandatory');
    }
    if (!plan.correlationId || plan.correlationId.trim() === '') {
      throw new RecoveryContractViolationError('plan.correlationId is mandatory');
    }

    // Security check: reject prototype pollution in metadata
    if (input.metadata) {
      validateAndSanitizePayload(input.metadata);
    }
    if (input.probeParameters) {
      validateAndSanitizePayload(input.probeParameters);
    }

    // Target capability determination
    const targetCapability = input.targetCapability || this.inferReadOnlyCapability(plan);
    if (!targetCapability || targetCapability.trim() === '') {
      throw new RecoveryContractViolationError('targetCapability could not be resolved');
    }

    // Hard Boundary: No arbitrary URLs
    if (/^https?:\/\//i.test(targetCapability)) {
      throw new RecoveryContractViolationError('Arbitrary URLs are strictly forbidden as reconciliation target');
    }

    // Probe Intent
    const probeIntent: ReconciliationProbeIntent =
      input.probeIntent || 'READ_ONLY_STATUS_CHECK';

    const timestamp = Date.now();
    const nonce = Math.random().toString(36).substring(2, 7);
    const reconciliationId = `recon_${plan.originalOperationId}_${timestamp}_${nonce}`;

    const maxAttempts = input.maxAttempts ?? MAX_RECONCILIATION_ATTEMPTS;
    const attemptNumber = input.attemptNumber ?? 1;

    return createReconciliationRequest({
      reconciliationId,
      originalOperationId: plan.originalOperationId,
      recoveryPlanId: plan.recoveryPlanId,
      targetCapability,
      probeIntent,
      isReadOnly: true,
      causationId: plan.originalOperationId, // Causal link to original operation
      correlationId: plan.correlationId,
      timeoutMs: input.timeoutMs ?? (plan.reconciliationRequirement?.timeoutMs ?? 10000),
      attemptNumber,
      maxAttempts,
      evidenceReferences: plan.evidenceReferences ? [...plan.evidenceReferences] : [],
      governanceRequired: input.governanceRequired ?? (plan.requiredAuthority.length > 0),
      lifecycleState: 'PLANNED',
      probeParameters: input.probeParameters,
      metadata: input.metadata ? { ...input.metadata } : undefined,
    });
  }

  /**
   * Coordinates execution of a safe read-only reconciliation probe across existing boundaries.
   * Delegates to Stage 15 Action Bus or Stage 07 Execution Gateway.
   * Strictly NO direct network calls.
   */
  public async coordinateProbe(
    request: ReconciliationRequest,
    boundary?: ReconciliationExecutionBoundary
  ): Promise<Readonly<ReconciliationResultRecord>> {
    if (!request) {
      throw new RecoveryContractViolationError('ReconciliationRequest is mandatory');
    }

    // Hard Boundary: Reject arbitrary URLs
    if (/^https?:\/\//i.test(request.targetCapability)) {
      throw new RecoveryContractViolationError('Arbitrary URLs are strictly forbidden as reconciliation target');
    }

    // Attempt Limit Bound
    if (request.attemptNumber > request.maxAttempts) {
      return createReconciliationResultRecord({
        reconciliationId: request.reconciliationId,
        originalOperationId: request.originalOperationId,
        recoveryPlanId: request.recoveryPlanId,
        outcome: 'EXPIRED',
        epistemicStatus: 'UNKNOWN',
        note: `Reconciliation attempt limit exceeded (${request.attemptNumber}/${request.maxAttempts}). Epistemic uncertainty preserved.`,
        causationId: request.originalOperationId,
        correlationId: request.correlationId,
        attemptNumber: request.attemptNumber,
      });
    }

    // Ensure strictly read-only
    if (request.isReadOnly !== true) {
      throw new RecoveryContractViolationError('Reconciliation probe must be strictly read-only');
    }

    // Check if target capability is known to be unavailable
    if (request.targetCapability === 'RECONCILIATION_UNAVAILABLE' || request.targetCapability.startsWith('mutation.')) {
      return createReconciliationResultRecord({
        reconciliationId: request.reconciliationId,
        originalOperationId: request.originalOperationId,
        recoveryPlanId: request.recoveryPlanId,
        outcome: 'RECONCILIATION_UNAVAILABLE',
        epistemicStatus: 'UNKNOWN',
        note: `Safe read-only reconciliation is not available for '${request.targetCapability}'. Mutation replay forbidden.`,
        causationId: request.originalOperationId,
        correlationId: request.correlationId,
        attemptNumber: request.attemptNumber,
      });
    }

    // Dispatch across authorized boundary
    try {
      if (boundary?.executeActionBusProbe) {
        const probeRes = await boundary.executeActionBusProbe({
          capabilityId: request.targetCapability,
          operation: 'reconcile_status_probe',
          parameters: (request.probeParameters as Record<string, unknown>) || {},
          idempotencyKey: `k_recon_${request.reconciliationId}`,
        });

        return this.mapProbeResponse(request, probeRes);
      }

      if (boundary?.executeGatewayProbe) {
        const gatewayRes = await boundary.executeGatewayProbe(`k_recon_${request.originalOperationId}`);
        if (gatewayRes.completed && gatewayRes.result) {
          return createReconciliationResultRecord({
            reconciliationId: request.reconciliationId,
            originalOperationId: request.originalOperationId,
            recoveryPlanId: request.recoveryPlanId,
            outcome: 'VERIFIED_SUCCESS',
            epistemicStatus: 'CONFIRMED',
            observedExternalState: { result: gatewayRes.result },
            authoritativeEvidenceReferences: [`gateway_exec_${request.originalOperationId}`],
            note: 'Provider execution gateway verified completed operation in execution store.',
            causationId: request.originalOperationId,
            correlationId: request.correlationId,
            attemptNumber: request.attemptNumber,
          });
        }
        return createReconciliationResultRecord({
          reconciliationId: request.reconciliationId,
          originalOperationId: request.originalOperationId,
          recoveryPlanId: request.recoveryPlanId,
          outcome: 'STILL_UNKNOWN',
          epistemicStatus: 'UNKNOWN',
          note: 'Provider execution gateway has no record of completed execution. State remains uncertain.',
          causationId: request.originalOperationId,
          correlationId: request.correlationId,
          attemptNumber: request.attemptNumber,
        });
      }

      // Default Stage 15 Action Bus invocation
      if (request.targetCapability.startsWith('action.') || request.targetCapability.includes('.')) {
        const busResult = await actionBusService.execute({
          actionId: `act_${request.reconciliationId}`,
          capabilityId: request.targetCapability,
          operation: 'get_status',
          parameters: (request.probeParameters as Record<string, unknown>) || {},
          idempotencyKey: `k_recon_${request.reconciliationId}`,
          context: {
            timestamp: new Date().toISOString(),
          },
          metadata: {
            isReconciliationProbe: true,
            originalOperationId: request.originalOperationId,
          },
        });

        if (busResult.success) {
          return createReconciliationResultRecord({
            reconciliationId: request.reconciliationId,
            originalOperationId: request.originalOperationId,
            recoveryPlanId: request.recoveryPlanId,
            outcome: 'VERIFIED_SUCCESS',
            epistemicStatus: 'CONFIRMED',
            observedExternalState: busResult.data as Record<string, unknown>,
            authoritativeEvidenceReferences: [busResult.actionId],
            probeOperationReference: busResult.actionId,
            note: 'Action Bus read-only probe verified successful external state.',
            causationId: request.originalOperationId,
            correlationId: request.correlationId,
            attemptNumber: request.attemptNumber,
          });
        }

        if (busResult.status === 'DENIED') {
          return createReconciliationResultRecord({
            reconciliationId: request.reconciliationId,
            originalOperationId: request.originalOperationId,
            recoveryPlanId: request.recoveryPlanId,
            outcome: 'REJECTED',
            epistemicStatus: 'UNKNOWN',
            note: `Reconciliation probe rejected by Action Bus authorization boundary: ${busResult.error?.message || 'Access denied'}`,
            causationId: request.originalOperationId,
            correlationId: request.correlationId,
            attemptNumber: request.attemptNumber,
          });
        }

        // If action bus returned failure because capability not found or probe failed
        return createReconciliationResultRecord({
          reconciliationId: request.reconciliationId,
          originalOperationId: request.originalOperationId,
          recoveryPlanId: request.recoveryPlanId,
          outcome: 'STILL_UNKNOWN',
          epistemicStatus: 'UNKNOWN',
          note: `Action Bus inquiry indeterminate (${busResult.status}). Uncertainty preserved.`,
          causationId: request.originalOperationId,
          correlationId: request.correlationId,
          attemptNumber: request.attemptNumber,
        });
      }

      // Default Stage 07 Execution Gateway invocation
      const existing = executionGateway.getCompletedExecution(request.originalOperationId);
      if (existing && existing.status === 'SUCCEEDED') {
        return createReconciliationResultRecord({
          reconciliationId: request.reconciliationId,
          originalOperationId: request.originalOperationId,
          recoveryPlanId: request.recoveryPlanId,
          outcome: 'VERIFIED_SUCCESS',
          epistemicStatus: 'CONFIRMED',
          observedExternalState: { output: existing.output },
          authoritativeEvidenceReferences: [existing.executionId],
          note: 'Execution gateway confirmed execution succeeded.',
          causationId: request.originalOperationId,
          correlationId: request.correlationId,
          attemptNumber: request.attemptNumber,
        });
      }

      // Default safe fallback: state remains unknown
      return createReconciliationResultRecord({
        reconciliationId: request.reconciliationId,
        originalOperationId: request.originalOperationId,
        recoveryPlanId: request.recoveryPlanId,
        outcome: 'STILL_UNKNOWN',
        epistemicStatus: 'UNKNOWN',
        note: 'No authoritative evidence returned from execution boundaries. State remains unknown.',
        causationId: request.originalOperationId,
        correlationId: request.correlationId,
        attemptNumber: request.attemptNumber,
      });
    } catch (probeError: unknown) {
      // CRITICAL INVARIANT: Probe failure != Original operation failure!
      const errorMsg = probeError instanceof Error ? probeError.message : String(probeError);
      return createReconciliationResultRecord({
        reconciliationId: request.reconciliationId,
        originalOperationId: request.originalOperationId,
        recoveryPlanId: request.recoveryPlanId,
        outcome: 'FAILED',
        epistemicStatus: 'UNKNOWN',
        note: `Reconciliation probe execution encountered an internal error: ${errorMsg}. Original operation status remains UNKNOWN.`,
        causationId: request.originalOperationId,
        correlationId: request.correlationId,
        attemptNumber: request.attemptNumber,
      });
    }
  }

  /**
   * Helper to infer a safe read-only inquiry capability from the original operation context.
   */
  private inferReadOnlyCapability(plan: RecoveryPlan): string {
    const original = plan.originalOperationId;
    if (original.includes('github')) return 'github.issue_read';
    if (original.includes('file')) return 'filesystem.stat';
    if (original.includes('deploy')) return 'deployment.status';
    if (original.includes('provider')) return 'provider.status_check';
    return 'system.resource_status';
  }

  /**
   * Maps boundary probe responses to deterministic reconciliation records.
   */
  private mapProbeResponse(
    request: ReconciliationRequest,
    probeRes: { success: boolean; data?: unknown; error?: unknown; notFound?: boolean }
  ): Readonly<ReconciliationResultRecord> {
    if (probeRes.success && probeRes.data) {
      return createReconciliationResultRecord({
        reconciliationId: request.reconciliationId,
        originalOperationId: request.originalOperationId,
        recoveryPlanId: request.recoveryPlanId,
        outcome: 'VERIFIED_SUCCESS',
        epistemicStatus: 'CONFIRMED',
        observedExternalState: probeRes.data as Record<string, unknown>,
        authoritativeEvidenceReferences: [`probe_ev_${request.reconciliationId}`],
        note: 'Read-only inquiry confirmed external side-effect is present and verified.',
        causationId: request.originalOperationId,
        correlationId: request.correlationId,
        attemptNumber: request.attemptNumber,
      });
    }

    if (probeRes.notFound === true) {
      return createReconciliationResultRecord({
        reconciliationId: request.reconciliationId,
        originalOperationId: request.originalOperationId,
        recoveryPlanId: request.recoveryPlanId,
        outcome: 'VERIFIED_FAILURE',
        epistemicStatus: 'OBSERVED',
        note: 'Read-only inquiry confirmed external resource does not exist. Original operation confirmed unperformed.',
        causationId: request.originalOperationId,
        correlationId: request.correlationId,
        attemptNumber: request.attemptNumber,
      });
    }

    if (probeRes.error) {
      // Probe failed; does NOT mean original operation failed!
      return createReconciliationResultRecord({
        reconciliationId: request.reconciliationId,
        originalOperationId: request.originalOperationId,
        recoveryPlanId: request.recoveryPlanId,
        outcome: 'FAILED',
        epistemicStatus: 'UNKNOWN',
        note: `Probe execution failed (${String(probeRes.error)}). Original operation state remains UNKNOWN.`,
        causationId: request.originalOperationId,
        correlationId: request.correlationId,
        attemptNumber: request.attemptNumber,
      });
    }

    return createReconciliationResultRecord({
      reconciliationId: request.reconciliationId,
      originalOperationId: request.originalOperationId,
      recoveryPlanId: request.recoveryPlanId,
      outcome: 'STILL_UNKNOWN',
      epistemicStatus: 'UNKNOWN',
      note: 'Probe completed without definitive external confirmation. Epistemic state remains UNKNOWN.',
      causationId: request.originalOperationId,
      correlationId: request.correlationId,
      attemptNumber: request.attemptNumber,
    });
  }
}

export const recoveryReconciliationService = new RecoveryReconciliationService();
