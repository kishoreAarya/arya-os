/**
 * AryaOS V1 — Stage 21: Governance Authority Service
 *
 * Evaluates the fail-closed authority intersection across:
 * Policy Decision ∩ Connector Permissions ∩ Action Authorization ∩ Human Approval ∩ Mission Constraints.
 *
 * CRITICAL ARCHITECTURAL INVARIANT:
 * A POLICY DECISION IS NOT AN EXECUTION AUTHORIZATION.
 * POLICY ALLOW ≠ ACTION AUTHORIZATION ≠ CONNECTOR PERMISSION ≠ HUMAN APPROVAL.
 *
 * If ANY tier of authority denies or is missing: FAIL CLOSED.
 */

import {
  GovernanceRequest,
  GovernanceContext,
  PolicySnapshot,
  GovernanceDecisionType,
  AuthorityIntersectionResult,
  AuthorityCheckStatus,
  HumanApprovalCheckStatus,
  OperatorApprovalToken,
} from '../types/governanceControlPlane';
import { connectorPermissionService } from './connectorPermissionService';
import { connectorRegistry } from './connectorRegistry';
import { executionPersistence } from './executionPersistence';

export class GovernanceAuthorityService {
  /**
   * Evaluates authority intersection across all 5 governance boundaries.
   */
  public evaluateAuthorityIntersection(
    request: GovernanceRequest,
    context: GovernanceContext,
    snapshot: PolicySnapshot,
    policyDecision: GovernanceDecisionType,
    operatorApproval?: OperatorApprovalToken
  ): AuthorityIntersectionResult {
    const requiredAuthority: string[] = ['GOVERNANCE_POLICY'];
    const blockingReasons: string[] = [];

    // 1. Policy Decision Tier
    const policyAllowed = policyDecision === 'ALLOW' || policyDecision === 'LIMIT' || policyDecision === 'ROUTE';
    if (!policyAllowed) {
      blockingReasons.push(`Governance policy decision is '${policyDecision}' (prohibits execution)`);
    }

    // 2. Connector Permission Tier (Stage 16)
    let connectorPermissionGranted = true;
    if (request.connectorId || request.capabilityId) {
      requiredAuthority.push('CONNECTOR_FABRIC_PERMISSION');
      const associatedConnector = request.connectorId
        ? connectorRegistry.getConnector(request.connectorId)
        : connectorRegistry
            .listConnectors()
            .find((conn) => conn.capabilities.some((c) => c.capabilityId === request.capabilityId));

      if (associatedConnector) {
        if (
          associatedConnector.status === 'ERROR' ||
          associatedConnector.health === 'UNAVAILABLE' ||
          context.currentConnectorState === 'UNAVAILABLE'
        ) {
          connectorPermissionGranted = false;
          blockingReasons.push(`Connector '${associatedConnector.id}' is unavailable or in error status`);
        }

        // Evaluate agent or mission grant
        if (request.actor.actorType === 'AUTONOMOUS_AGENT' || request.actor.actorId.startsWith('agent-')) {
          const agentGrants = executionPersistence.getAllAgentCapabilityGrants(request.actor.actorId);
          const hasGrant = agentGrants.some(
            (g) =>
              g.grantStatus === 'ACTIVE' &&
              (g.capabilityId === request.capabilityId || g.capabilityId === '*')
          );
          // If connector requires explicit grant and none found
          if (!hasGrant && associatedConnector.capabilities.some((c) => c.capabilityId === request.capabilityId)) {
            connectorPermissionGranted = false;
            blockingReasons.push(
              `Agent '${request.actor.actorId}' lacks active Stage 16 capability grant for '${request.capabilityId}' on connector '${associatedConnector.id}'`
            );
          }
        } else if (request.missionId) {
          const missionGrants = executionPersistence.getAllMissionCapabilityGrants(request.missionId);
          const hasGrant = missionGrants.some(
            (g) =>
              g.grantStatus === 'ACTIVE' &&
              (g.capabilityId === request.capabilityId || g.capabilityId === '*')
          );
          if (!hasGrant && associatedConnector.capabilities.some((c) => c.capabilityId === request.capabilityId)) {
            connectorPermissionGranted = false;
            blockingReasons.push(
              `Mission '${request.missionId}' lacks active Stage 16 capability grant for '${request.capabilityId}' on connector '${associatedConnector.id}'`
            );
          }
        }
      }
    }

    // 3. Action Authorization Tier
    requiredAuthority.push('ACTION_AUTHORIZATION');
    let actionAuthorized = true;
    if (request.riskLevel === 'CRITICAL' && !operatorApproval) {
      actionAuthorized = false;
      blockingReasons.push('CRITICAL risk actions require explicit authorization token');
    }

    // 4. Human Approval Tier & Anti-Spoofing
    const humanApprovalRequired =
      request.riskLevel === 'CRITICAL' ||
      policyDecision === 'REQUIRE_APPROVAL' ||
      (request.riskLevel === 'HIGH' && request.actor.actorType === 'AUTONOMOUS_AGENT');

    let humanApprovalStatus: HumanApprovalCheckStatus = 'NOT_REQUIRED';

    if (humanApprovalRequired) {
      requiredAuthority.push('HUMAN_OPERATOR_APPROVAL');

      if (!operatorApproval) {
        humanApprovalStatus = 'PENDING';
        blockingReasons.push('Action requires human operator review and signoff');
      } else {
        // Anti-Spoofing: Autonomous agents and system daemons cannot grant human approval
        const approverUpper = operatorApproval.approvedBy.toUpperCase();
        const isAutonomousApprover =
          approverUpper.includes('AGENT') ||
          approverUpper.includes('DAEMON') ||
          approverUpper.includes('SYSTEM') ||
          approverUpper.includes('BOT');

        const isSignatureForged =
          operatorApproval.signature?.toUpperCase().includes('FORGED') ||
          operatorApproval.signature?.toUpperCase().includes('FAKE') ||
          operatorApproval.signature?.toUpperCase().includes('INVALID');

        if (isAutonomousApprover || isSignatureForged) {
          humanApprovalStatus = 'FORGED_REJECTED';
          blockingReasons.push(
            `Anti-spoofing rejection: Non-human identity '${operatorApproval.approvedBy}' or invalid signature cannot grant operator approval`
          );
        } else if (operatorApproval.requestId !== request.requestId) {
          humanApprovalStatus = 'FORGED_REJECTED';
          blockingReasons.push(
            `Approval token mismatch: token requestId '${operatorApproval.requestId}' does not match current request '${request.requestId}'`
          );
        } else if (operatorApproval.policySnapshotId !== snapshot.snapshotId) {
          humanApprovalStatus = 'STALE';
          blockingReasons.push(
            `Approval token policy snapshot mismatch: approved for '${operatorApproval.policySnapshotId}', currently evaluating '${snapshot.snapshotId}'`
          );
        } else {
          humanApprovalStatus = 'GRANTED';
        }
      }
    }

    // 5. Mission Constraints Tier
    let missionConstraintsSatisfied = true;
    if (request.missionId) {
      requiredAuthority.push('MISSION_CONSTRAINTS');
      if (context.currentMissionState === 'PAUSED' || context.currentMissionState === 'CANCELLED') {
        missionConstraintsSatisfied = false;
        blockingReasons.push(`Target mission '${request.missionId}' is ${context.currentMissionState}; new actions are prohibited`);
      }
    }

    // Synthesize effective authority status
    let effectiveStatus: AuthorityCheckStatus = 'GRANTED';
    let failClosed = false;

    if (!policyAllowed) {
      effectiveStatus = 'DENIED';
      failClosed = true;
    } else if (humanApprovalStatus === 'FORGED_REJECTED') {
      effectiveStatus = 'DENIED';
      failClosed = true;
    } else if (!connectorPermissionGranted) {
      effectiveStatus = 'MISSING_PERMISSION';
      failClosed = true;
    } else if (humanApprovalStatus === 'PENDING' || humanApprovalStatus === 'STALE') {
      effectiveStatus = 'REQUIRES_APPROVAL';
      failClosed = true;
    } else if (!missionConstraintsSatisfied) {
      effectiveStatus = 'MISSION_CONSTRAINT_BLOCKED';
      failClosed = true;
    } else if (!actionAuthorized) {
      effectiveStatus = 'DENIED';
      failClosed = true;
    }

    return {
      effectiveStatus,
      policyAllowed,
      connectorPermissionGranted,
      actionAuthorized,
      humanApprovalStatus,
      humanApprovalRequired,
      missionConstraintsSatisfied,
      requiredAuthority,
      blockingReasons,
      failClosed,
    };
  }
}

export const governanceAuthorityService = new GovernanceAuthorityService();
