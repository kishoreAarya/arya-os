/**
 * AryaOS V1 — Stage 22: Operational Lifecycle Service
 *
 * Enforces canonical operational lifecycle state transitions and prevents
 * illegal state jumps, synthetic success claims, and un-evidenced state promotions.
 */

import {
  OperationalLifecycleState,
  TERMINAL_LIFECYCLE_STATES,
} from '../types/operationalAudit';

export class OperationalLifecycleService {
  /**
   * Allowed state transitions map:
   * Maps current state -> set of permissible next states.
   */
  private allowedTransitions: Map<OperationalLifecycleState, Set<OperationalLifecycleState>> = new Map([
    ['RECEIVED', new Set(['VALIDATED', 'REJECTED', 'FAILED', 'UNKNOWN'])],
    ['VALIDATED', new Set(['PLANNED', 'TRIGGERED', 'PROPOSED', 'GOVERNED', 'REJECTED', 'FAILED', 'UNKNOWN'])],
    ['PLANNED', new Set(['TRIGGERED', 'PROPOSED', 'GOVERNED', 'CANCELLED', 'PAUSED', 'FAILED', 'UNKNOWN'])],
    ['TRIGGERED', new Set(['PROPOSED', 'REJECTED', 'DEFERRED', 'FAILED', 'UNKNOWN'])],
    ['PROPOSED', new Set(['GOVERNED', 'REJECTED', 'DEFERRED', 'FAILED', 'UNKNOWN'])],
    ['GOVERNED', new Set(['AUTHORIZED', 'DENIED', 'DEFERRED', 'PAUSED', 'FAILED', 'UNKNOWN'])],
    ['AUTHORIZED', new Set(['DISPATCHED', 'CANCELLED', 'PAUSED', 'FAILED', 'UNKNOWN'])],
    ['DISPATCHED', new Set(['EXECUTING', 'FAILED', 'UNKNOWN'])],
    ['EXECUTING', new Set(['SUCCEEDED', 'FAILED', 'UNKNOWN', 'DEFERRED', 'PAUSED', 'CANCELLED'])],
    // Terminal states can only transition to RECONCILED
    ['SUCCEEDED', new Set(['RECONCILED', 'FAILED'])],
    ['FAILED', new Set(['RECONCILED'])],
    ['REJECTED', new Set(['RECONCILED'])],
    ['DENIED', new Set(['RECONCILED'])],
    ['DEFERRED', new Set(['GOVERNED', 'CANCELLED', 'RECONCILED'])],
    ['PAUSED', new Set(['GOVERNED', 'AUTHORIZED', 'CANCELLED', 'RECONCILED'])],
    ['CANCELLED', new Set(['RECONCILED'])],
    ['UNKNOWN', new Set(['RECONCILED', 'SUCCEEDED', 'FAILED'])], // UNKNOWN can be updated only via authenticated reconciliation
    ['RECONCILED', new Set()], // Pure terminal
  ]);

  /**
   * Validates if a transition from currentState to targetState is permissible.
   */
  public isValidTransition(
    currentState: OperationalLifecycleState,
    targetState: OperationalLifecycleState
  ): { valid: boolean; reason?: string } {
    if (currentState === targetState) {
      return { valid: true };
    }

    const nextPermitted = this.allowedTransitions.get(currentState);
    if (!nextPermitted || !nextPermitted.has(targetState)) {
      return {
        valid: false,
        reason: `Illegal lifecycle transition: Cannot transition from '${currentState}' to '${targetState}'.`,
      };
    }

    return { valid: true };
  }

  /**
   * Checks if a lifecycle state is terminal.
   */
  public isTerminal(state: OperationalLifecycleState): boolean {
    return TERMINAL_LIFECYCLE_STATES.has(state);
  }

  /**
   * Resolves the authoritative state when reconciling operational intent with observed reality.
   * Core Invariant: ActionBus dispatch !== external success.
   */
  public resolveOperationalTruth(params: {
    dispatchedState: OperationalLifecycleState;
    externalEvidenceReceived: boolean;
    externalSuccessObserved?: boolean;
    reconciliationMatched?: boolean;
  }): OperationalLifecycleState {
    // If not dispatched, return current dispatched state
    if (params.dispatchedState !== 'DISPATCHED' && params.dispatchedState !== 'EXECUTING') {
      return params.dispatchedState;
    }

    // Dispatched, but no external evidence received -> UNKNOWN
    if (!params.externalEvidenceReceived) {
      return 'UNKNOWN';
    }

    // External evidence exists and indicates failure
    if (params.externalSuccessObserved === false) {
      return 'FAILED';
    }

    // External evidence exists and indicates success
    if (params.externalSuccessObserved === true) {
      if (params.reconciliationMatched === false) {
        return 'FAILED'; // Reconciliation mismatch overrides nominal success
      }
      return 'SUCCEEDED';
    }

    return 'UNKNOWN';
  }
}

export const operationalLifecycleService = new OperationalLifecycleService();
