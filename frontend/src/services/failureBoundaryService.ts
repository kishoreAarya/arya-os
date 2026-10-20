/**
 * AryaOS V1 — Stage 22: Failure Boundary Reconstruction Service
 *
 * Pinpoints the exact architectural boundary where an operation was halted,
 * blocked, or failed, preventing all failures from collapsing into a generic 'FAILED' state.
 */

import {
  FailureBoundaryDetail,
  FailureBoundaryType,
  OperationalAuditEvent,
} from '../types/operationalAudit';

export class FailureBoundaryService {
  /**
   * Resolves the exact failure boundary from an operational audit trail.
   */
  public diagnoseFailureBoundary(events: OperationalAuditEvent[]): FailureBoundaryDetail | undefined {
    if (events.length === 0) {
      return undefined;
    }

    const lastEvt = events[events.length - 1];

    // If the last event already has an explicit failure boundary, return it
    if (lastEvt.failureBoundary) {
      return lastEvt.failureBoundary;
    }

    // 1. Check for Governance Denial
    const govEvent = events.find((e) => e.eventType === 'GOVERNANCE_DECIDED');
    if (govEvent?.governanceDecision === 'DENY') {
      return {
        boundary: 'POLICY_DENIED',
        stoppingStage: 'Stage 21 Governance Control Plane',
        reason: govEvent.reason || 'Operation blocked by active policy governance rules.',
        remedialAction: 'Review governing active policies or request policy exemption.',
        evidenceId: govEvent.eventId,
      };
    }

    // 2. Check for Human Approval Requirement / Pending
    if (govEvent?.governanceDecision === 'REQUIRE_APPROVAL' && lastEvt.lifecycleState !== 'SUCCEEDED') {
      return {
        boundary: 'HUMAN_APPROVAL_PENDING',
        stoppingStage: 'Stage 21 Human Operator Gate',
        reason: 'Operation requires explicit human operator approval before dispatch.',
        remedialAction: 'Submit operator approval token with valid signature.',
        evidenceId: govEvent.eventId,
      };
    }

    // 3. Check for Authority Check Failure
    const authEvent = events.find((e) => e.eventType === 'AUTHORITY_CHECKED');
    if (authEvent && authEvent.lifecycleState === 'DENIED') {
      return {
        boundary: 'AUTHORIZATION_DENIED',
        stoppingStage: 'Stage 21 Authority Intersection',
        reason: authEvent.reason || 'Failed multi-tier authority intersection check.',
        remedialAction: 'Verify agent capability grants and connector permissions.',
        evidenceId: authEvent.eventId,
      };
    }

    // 4. Check for Action Bus Dispatch without External Confirmation (UNKNOWN)
    const actionDispatched = events.find((e) => e.eventType === 'ACTION_DISPATCHED');
    const externalConfirmed = events.find(
      (e) => e.eventType === 'OBSERVATION_RECORDED' || e.eventType === 'STATE_RECONCILED'
    );
    if (actionDispatched && !externalConfirmed && lastEvt.lifecycleState === 'UNKNOWN') {
      return {
        boundary: 'EXTERNAL_RESULT_UNKNOWN',
        stoppingStage: 'Stage 15 / Stage 17 Action Bus Transport',
        reason: 'Action was dispatched to external system, but no authoritative confirmation was observed.',
        remedialAction: 'Execute external state reconciliation query or wait for webhook receipt.',
        evidenceId: actionDispatched.eventId,
      };
    }

    // 5. Check for State Reconciliation Failure
    const reconciledEvent = events.find((e) => e.eventType === 'STATE_RECONCILED');
    if (reconciledEvent && reconciledEvent.lifecycleState === 'FAILED') {
      return {
        boundary: 'RECONCILIATION_FAILURE',
        stoppingStage: 'Stage 22 Operational Truth Reconciler',
        reason: reconciledEvent.reason || 'External system claimed success, but state reconciliation failed.',
        remedialAction: 'Inspect external resource delta and resolve data drift.',
        evidenceId: reconciledEvent.eventId,
      };
    }

    // 6. Generic failure fallback if status is FAILED
    if (lastEvt.lifecycleState === 'FAILED') {
      return {
        boundary: 'UNKNOWN_BOUNDARY',
        stoppingStage: lastEvt.sourceSystem || 'Unknown',
        reason: lastEvt.reason || 'Operation failed at an unspecified execution boundary.',
        evidenceId: lastEvt.eventId,
      };
    }

    return undefined;
  }

  /**
   * Helper to construct a standard FailureBoundaryDetail.
   */
  public createDetail(
    boundary: FailureBoundaryType,
    stoppingStage: string,
    reason: string,
    remedialAction?: string
  ): FailureBoundaryDetail {
    return {
      boundary,
      stoppingStage,
      reason,
      remedialAction,
    };
  }
}

export const failureBoundaryService = new FailureBoundaryService();
