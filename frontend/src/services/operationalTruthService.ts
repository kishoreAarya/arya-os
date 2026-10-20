/**
 * AryaOS V1 — Stage 22: Operational Truth Service
 *
 * Strict discriminator separating Operational Intent from Operational Truth.
 * Enforces: REQUESTED != PLANNED != AUTHORIZED != DISPATCHED != EXECUTED != OBSERVED != RECONCILED.
 * Prevents synthetic success claims when external confirmation is absent (UNKNOWN state invariant).
 */

import {
  OperationalLifecycleState,
  EpistemicStatus,
  FailureBoundaryDetail,
} from '../types/operationalAudit';

export interface TruthReconciliationResult {
  isAuthoritativeTruth: boolean;
  lifecycleState: OperationalLifecycleState;
  epistemicStatus: EpistemicStatus;
  reconciled: boolean;
  discrepancyDetected: boolean;
  failureBoundary?: FailureBoundaryDetail;
  reconciliationSummary: string;
}

export class OperationalTruthService {
  /**
   * Asserts whether a given lifecycle state represents Intent or Verified Truth.
   */
  public isIntentOnly(state: OperationalLifecycleState): boolean {
    return (
      state === 'RECEIVED' ||
      state === 'VALIDATED' ||
      state === 'PLANNED' ||
      state === 'TRIGGERED' ||
      state === 'PROPOSED' ||
      state === 'GOVERNED' ||
      state === 'AUTHORIZED' ||
      state === 'DISPATCHED'
    );
  }

  /**
   * Asserts whether a given lifecycle state represents an observed execution or terminal state.
   */
  public isObservedState(state: OperationalLifecycleState): boolean {
    return (
      state === 'EXECUTING' ||
      state === 'SUCCEEDED' ||
      state === 'FAILED' ||
      state === 'REJECTED' ||
      state === 'DENIED' ||
      state === 'DEFERRED' ||
      state === 'PAUSED' ||
      state === 'CANCELLED' ||
      state === 'RECONCILED'
    );
  }

  /**
   * Reconciles operational dispatch with external observation evidence.
   *
   * CRITICAL INVARIANT:
   * Action Bus dispatch succeeded != External Action succeeded.
   * If external confirmation is unavailable -> status = UNKNOWN, epistemicStatus = UNKNOWN.
   */
  public reconcileOperationalTruth(params: {
    dispatchedState: OperationalLifecycleState;
    hasActionBusDispatched: boolean;
    hasExternalConfirmation: boolean;
    externalSuccess?: boolean;
    expectedStateDelta?: Record<string, unknown>;
    observedStateDelta?: Record<string, unknown>;
    reconciliationMatched?: boolean;
  }): TruthReconciliationResult {
    // Case 1: Not dispatched yet (still in intent phase)
    if (!params.hasActionBusDispatched) {
      return {
        isAuthoritativeTruth: false,
        lifecycleState: params.dispatchedState,
        epistemicStatus: 'PROJECTED',
        reconciled: false,
        discrepancyDetected: false,
        reconciliationSummary: `Operation remains in intent phase (${params.dispatchedState}). No dispatch occurred.`,
      };
    }

    // Case 2: Dispatched, but NO external confirmation received
    if (!params.hasExternalConfirmation) {
      return {
        isAuthoritativeTruth: false,
        lifecycleState: 'UNKNOWN',
        epistemicStatus: 'UNKNOWN',
        reconciled: false,
        discrepancyDetected: false,
        failureBoundary: {
          boundary: 'EXTERNAL_RESULT_UNKNOWN',
          stoppingStage: 'Stage 15 / Stage 17 External Transport',
          reason: 'Action Bus dispatch completed, but no external verification or observation was received.',
          remedialAction: 'Poll connector health or query external resource status for state confirmation.',
        },
        reconciliationSummary:
          'Action Bus dispatch succeeded, but external outcome remains UNKNOWN pending external confirmation.',
      };
    }

    // Case 3: External confirmation received, but external execution failed
    if (params.externalSuccess === false) {
      return {
        isAuthoritativeTruth: true,
        lifecycleState: 'FAILED',
        epistemicStatus: 'OBSERVED',
        reconciled: true,
        discrepancyDetected: false,
        failureBoundary: {
          boundary: 'PROVIDER_FAILURE',
          stoppingStage: 'External System / Adapter',
          reason: 'External system reported execution failure or error response.',
        },
        reconciliationSummary: 'External execution failed as observed by authenticated callback/observation.',
      };
    }

    // Case 4: External confirmation received as success, check reconciliation match
    if (params.reconciliationMatched === false) {
      return {
        isAuthoritativeTruth: true,
        lifecycleState: 'FAILED',
        epistemicStatus: 'CONFIRMED',
        reconciled: false,
        discrepancyDetected: true,
        failureBoundary: {
          boundary: 'RECONCILIATION_FAILURE',
          stoppingStage: 'Stage 22 Operational Truth Reconciler',
          reason: 'Observed post-execution state does not match expected state delta.',
        },
        reconciliationSummary:
          'Discrepancy detected: External system reported success, but state delta reconciliation failed.',
      };
    }

    // Case 5: Fully observed and reconciled truth
    return {
      isAuthoritativeTruth: true,
      lifecycleState: 'RECONCILED',
      epistemicStatus: 'CONFIRMED',
      reconciled: true,
      discrepancyDetected: false,
      reconciliationSummary:
        'Operation successfully executed, observed externally, and reconciled with expected system state.',
    };
  }
}

export const operationalTruthService = new OperationalTruthService();
