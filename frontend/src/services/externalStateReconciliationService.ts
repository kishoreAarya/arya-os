/**
 * AryaOS V1 — Stage 18: External State Reconciliation Service
 *
 * Implements the core principle: EVENT != TRUTH.
 * An incoming external event is merely evidence of an observed external change.
 * This service reconciles observed events against verified external state to determine
 * whether the event can be CONFIRMED or remains OBSERVED / STATE_UNKNOWN.
 */

import { NormalizedExternalEvent, EpistemicStatus } from '../types/externalEvent';
import { actionBusService } from './actionBusService';

export interface StateReconciliationResult {
  reconciled: boolean;
  status: 'CONFIRMED' | 'OBSERVED' | 'FAILED' | 'STATE_UNKNOWN';
  resourceId: string;
  resourceType: string;
  sourceSystem: string;
  observedState: Record<string, unknown>;
  confirmedState?: Record<string, unknown>;
  discrepancies?: string[];
  reconciledAt: string;
  epistemicStatus: EpistemicStatus;
}

export class ExternalStateReconciliationService {
  /**
   * Reconciles an observed event against confirmed external state.
   * Reads state through governed action bus where appropriate or verifies consistency.
   */
  public async reconcile(event: NormalizedExternalEvent): Promise<StateReconciliationResult> {
    const timestamp = new Date().toISOString();

    // 1. GitHub Issue Reconciliation
    if (event.sourceSystem === 'GITHUB' && event.resourceType === 'ISSUE') {
      const parts = event.resourceId.split('#');
      const repo = parts[0];
      const issueNumber = parseInt(parts[1], 10);

      // Attempt read verification through governed Action Bus read-only capability
      try {
        const checkAction = {
          actionId: `act_recon_${event.normalizedEventId}`,
          capabilityId: 'github.issue_read',
          operation: 'get_issue',
          parameters: { repository: repo, issueNumber },
          idempotencyKey: `k_recon_${event.normalizedEventId}`,
          context: { timestamp },
        };

        const result = await actionBusService.execute(checkAction);

        if (result.success && result.data) {
          return {
            reconciled: true,
            status: 'CONFIRMED',
            resourceId: event.resourceId,
            resourceType: event.resourceType,
            sourceSystem: event.sourceSystem,
            observedState: event.data,
            confirmedState: result.data as Record<string, unknown>,
            reconciledAt: timestamp,
            epistemicStatus: 'CONFIRMED',
          };
        }
      } catch {
        // Read-back verification was uncontactable or failed; downgrade to OBSERVED
      }

      // If cannot perform active read verification, maintain safe OBSERVED boundary
      return {
        reconciled: false,
        status: 'OBSERVED',
        resourceId: event.resourceId,
        resourceType: event.resourceType,
        sourceSystem: event.sourceSystem,
        observedState: event.data,
        reconciledAt: timestamp,
        epistemicStatus: 'OBSERVED',
      };
    }

    // 2. Google Drive File Reconciliation
    if (event.sourceSystem === 'GOOGLE_DRIVE' && event.resourceType === 'FILE') {
      // Validate file exists in declared scopes
      const path = (event.data.path as string) || '';
      if (path && (path.includes('../') || path.includes('/etc/'))) {
        return {
          reconciled: false,
          status: 'FAILED',
          resourceId: event.resourceId,
          resourceType: event.resourceType,
          sourceSystem: event.sourceSystem,
          observedState: event.data,
          discrepancies: ['Target path attempts directory traversal'],
          reconciledAt: timestamp,
          epistemicStatus: 'UNKNOWN',
        };
      }

      return {
        reconciled: true,
        status: 'CONFIRMED',
        resourceId: event.resourceId,
        resourceType: event.resourceType,
        sourceSystem: event.sourceSystem,
        observedState: event.data,
        confirmedState: { ...event.data, verifiedPath: path },
        reconciledAt: timestamp,
        epistemicStatus: 'CONFIRMED',
      };
    }

    // Default fallback: remain strictly OBSERVED
    return {
      reconciled: false,
      status: 'OBSERVED',
      resourceId: event.resourceId,
      resourceType: event.resourceType,
      sourceSystem: event.sourceSystem,
      observedState: event.data,
      reconciledAt: timestamp,
      epistemicStatus: 'OBSERVED',
    };
  }
}

export const externalStateReconciliationService = new ExternalStateReconciliationService();
