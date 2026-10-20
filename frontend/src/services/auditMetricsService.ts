/**
 * AryaOS V1 — Stage 22: Audit Metrics Service
 *
 * Computes deterministic observability metrics derived strictly from verified
 * operational audit events in the AuditEventRegistry. Zero synthetic metrics.
 */

import { OperationalMetrics } from '../types/operationalAudit';
import { auditEventRegistry } from './auditEventRegistry';

export class AuditMetricsService {
  /**
   * Computes complete operational metrics from the audit registry.
   */
  public computeMetrics(): OperationalMetrics {
    const allEvents = auditEventRegistry.getAllEvents();

    // Group events by operationId
    const opMap = new Map<string, typeof allEvents[0][]>();
    for (const evt of allEvents) {
      const existing = opMap.get(evt.operationId);
      if (existing) {
        existing.push(evt);
      } else {
        opMap.set(evt.operationId, [evt]);
      }
    }

    let activeCount = 0;
    let succeededCount = 0;
    let failedCount = 0;
    let deniedCount = 0;
    let deferredCount = 0;
    let pausedCount = 0;
    let unknownCount = 0;

    let totalDurationMs = 0;
    let completedOpsWithDuration = 0;

    let totalGovLatencyMs = 0;
    let govCount = 0;

    let totalActionLatencyMs = 0;
    let actionCount = 0;

    let totalReconcileLatencyMs = 0;
    let reconcileCount = 0;

    let retryCount = 0;
    let staleDecisionCount = 0;

    const epistemicBreakdown = {
      observedCount: 0,
      confirmedCount: 0,
      inferredCount: 0,
      projectedCount: 0,
      unknownCount: 0,
    };

    for (const [_, opEvents] of opMap.entries()) {
      const sorted = [...opEvents].sort((a, b) => a.timestamp - b.timestamp);
      const first = sorted[0];
      const last = sorted[sorted.length - 1];

      // Terminal vs Active
      const terminal = last.lifecycleState;
      switch (terminal) {
        case 'SUCCEEDED':
        case 'RECONCILED':
          succeededCount++;
          break;
        case 'FAILED':
        case 'REJECTED':
          failedCount++;
          break;
        case 'DENIED':
          deniedCount++;
          break;
        case 'DEFERRED':
          deferredCount++;
          break;
        case 'PAUSED':
          pausedCount++;
          break;
        case 'UNKNOWN':
          unknownCount++;
          break;
        default:
          activeCount++;
          break;
      }

      // Duration
      if (
        terminal === 'SUCCEEDED' ||
        terminal === 'RECONCILED' ||
        terminal === 'FAILED' ||
        terminal === 'DENIED'
      ) {
        totalDurationMs += Math.max(0, last.timestamp - first.timestamp);
        completedOpsWithDuration++;
      }

      // Latencies & Special counts
      for (let i = 0; i < sorted.length; i++) {
        const e = sorted[i];

        // Epistemic breakdown
        switch (e.epistemicStatus) {
          case 'OBSERVED':
            epistemicBreakdown.observedCount++;
            break;
          case 'CONFIRMED':
            epistemicBreakdown.confirmedCount++;
            break;
          case 'INFERRED':
            epistemicBreakdown.inferredCount++;
            break;
          case 'PROJECTED':
            epistemicBreakdown.projectedCount++;
            break;
          case 'UNKNOWN':
          default:
            epistemicBreakdown.unknownCount++;
            break;
        }

        // Stale detection
        if (e.reason?.includes('STALE') || e.failureBoundary?.boundary.includes('STALE')) {
          staleDecisionCount++;
        }

        // Retries
        if (e.eventType === 'ACTION_DISPATCHED' && i > 0 && sorted[i - 1].eventType === 'ACTION_DISPATCHED') {
          retryCount++;
        }

        // Governance latency
        if (e.eventType === 'GOVERNANCE_DECIDED' && i > 0) {
          totalGovLatencyMs += Math.max(0, e.timestamp - sorted[i - 1].timestamp);
          govCount++;
        }

        // Action Bus latency
        if (e.eventType === 'ACTION_EXECUTED' && i > 0) {
          totalActionLatencyMs += Math.max(0, e.timestamp - sorted[i - 1].timestamp);
          actionCount++;
        }

        // Reconciliation latency
        if (e.eventType === 'STATE_RECONCILED' && i > 0) {
          totalReconcileLatencyMs += Math.max(0, e.timestamp - sorted[i - 1].timestamp);
          reconcileCount++;
        }
      }
    }

    return {
      totalOperations: opMap.size,
      activeOperations: activeCount,
      succeededOperations: succeededCount,
      failedOperations: failedCount,
      deniedOperations: deniedCount,
      deferredOperations: deferredCount,
      pausedOperations: pausedCount,
      unknownResultOperations: unknownCount,
      averageOperationDurationMs:
        completedOpsWithDuration > 0 ? Math.round(totalDurationMs / completedOpsWithDuration) : 0,
      averageGovernanceLatencyMs: govCount > 0 ? Math.round(totalGovLatencyMs / govCount) : 0,
      averageActionBusLatencyMs: actionCount > 0 ? Math.round(totalActionLatencyMs / actionCount) : 0,
      averageReconciliationLatencyMs:
        reconcileCount > 0 ? Math.round(totalReconcileLatencyMs / reconcileCount) : 0,
      totalRetriesRecorded: retryCount,
      staleDecisionsDetected: staleDecisionCount,
      epistemicBreakdown,
      computedAt: Date.now(),
    };
  }
}

export const auditMetricsService = new AuditMetricsService();
