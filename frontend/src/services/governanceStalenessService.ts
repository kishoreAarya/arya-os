/**
 * AryaOS V1 — Stage 21: Governance Staleness Service
 *
 * Detects policy version divergence, snapshot staleness, and stale operator approvals.
 * Prevents in-flight policy changes or altered requests from executing under stale decisions.
 */

import {
  PolicySnapshot,
  GovernanceStalenessCheck,
  StalenessStatus,
  OperatorApprovalToken,
  GovernanceRequest,
} from '../types/governanceControlPlane';
import { policyRegistry } from './policyRegistry';
import { executionPersistence } from './executionPersistence';

export class GovernanceStalenessService {
  /**
   * Verifies whether an evaluated decision or snapshot remains fresh at execution time.
   */
  public checkStaleness(
    snapshot: PolicySnapshot,
    request: GovernanceRequest,
    approvalToken?: OperatorApprovalToken
  ): GovernanceStalenessCheck {
    const currentRegistryVersion = policyRegistry.getRegistryVersion();
    const MAX_DECISION_TTL_MS = 300000; // 5 minutes

    // 0. TTL Check
    if (request.timestamp && Date.now() - request.timestamp > MAX_DECISION_TTL_MS) {
      return {
        isStale: true,
        status: 'EXPIRED',
        reason: `Governance request has exceeded TTL (${Date.now() - request.timestamp}ms > ${MAX_DECISION_TTL_MS}ms). Re-evaluation required.`,
        evaluatedSnapshotId: snapshot.snapshotId,
        currentRegistryVersion,
        snapshotRegistryVersion: snapshot.registryVersion,
      };
    }
    if (approvalToken && approvalToken.approvedAt && Date.now() - approvalToken.approvedAt > MAX_DECISION_TTL_MS) {
      return {
        isStale: true,
        status: 'EXPIRED',
        reason: `Operator approval token has expired (${Date.now() - approvalToken.approvedAt}ms > ${MAX_DECISION_TTL_MS}ms). Re-approval required.`,
        evaluatedSnapshotId: snapshot.snapshotId,
        currentRegistryVersion,
        snapshotRegistryVersion: snapshot.registryVersion,
      };
    }

    // 1. Registry Version Check
    if (snapshot.registryVersion !== currentRegistryVersion) {
      return {
        isStale: true,
        status: 'VERSION_MISMATCH',
        reason: `Active policy registry has advanced from version ${snapshot.registryVersion} to ${currentRegistryVersion}. Re-evaluation required.`,
        evaluatedSnapshotId: snapshot.snapshotId,
        currentRegistryVersion,
        snapshotRegistryVersion: snapshot.registryVersion,
      };
    }

    // 2. Individual Active Policy Version & Status Check
    for (const entry of snapshot.policies) {
      const livePolicy = policyRegistry.getPolicy(entry.policyId);
      if (!livePolicy) {
        return {
          isStale: true,
          status: 'VERSION_MISMATCH',
          reason: `Policy '${entry.policyId}' was revoked or removed from active catalog.`,
          evaluatedSnapshotId: snapshot.snapshotId,
          currentRegistryVersion,
          snapshotRegistryVersion: snapshot.registryVersion,
        };
      }
      if (livePolicy.version !== entry.version) {
        return {
          isStale: true,
          status: 'VERSION_MISMATCH',
          reason: `Policy '${entry.policyId}' updated from version ${entry.version} to ${livePolicy.version}.`,
          evaluatedSnapshotId: snapshot.snapshotId,
          currentRegistryVersion,
          snapshotRegistryVersion: snapshot.registryVersion,
        };
      }
      if (livePolicy.status !== 'ACTIVE') {
        return {
          isStale: true,
          status: 'VERSION_MISMATCH',
          reason: `Policy '${entry.policyId}' status transitioned to '${livePolicy.status}' (no longer ACTIVE).`,
          evaluatedSnapshotId: snapshot.snapshotId,
          currentRegistryVersion,
          snapshotRegistryVersion: snapshot.registryVersion,
        };
      }
    }

    // 3. Approval Staleness Check
    if (approvalToken) {
      if (approvalToken.policySnapshotId !== snapshot.snapshotId) {
        return {
          isStale: true,
          status: 'STALE_APPROVAL',
          reason: `Approval token policySnapshotId mismatch: operator approval was granted against snapshot '${approvalToken.policySnapshotId}', but current evaluation uses '${snapshot.snapshotId}'.`,
          evaluatedSnapshotId: snapshot.snapshotId,
          currentRegistryVersion,
          snapshotRegistryVersion: snapshot.registryVersion,
        };
      }

      if (approvalToken.requestId !== request.requestId) {
        return {
          isStale: true,
          status: 'STALE_APPROVAL',
          reason: `Operator approval token requestId '${approvalToken.requestId}' does not match target request '${request.requestId}'.`,
          evaluatedSnapshotId: snapshot.snapshotId,
          currentRegistryVersion,
          snapshotRegistryVersion: snapshot.registryVersion,
          alteredRequestParameters: true,
        };
      }
    }

    return {
      isStale: false,
      status: 'FRESH',
      evaluatedSnapshotId: snapshot.snapshotId,
      currentRegistryVersion,
      snapshotRegistryVersion: snapshot.registryVersion,
    };
  }
}

export const governanceStalenessService = new GovernanceStalenessService();
