/**
 * AryaOS V1 — Stage 16: Connector Permission Service
 *
 * Implements Scoped Permission Management, Agent/Mission Capability Grants,
 * Permission Versioning, and Zero-Trust Default-DENY Authorization.
 *
 * SECURITY INVARIANT:
 * No capability may infer permission from:
 * - agent trust / agent rank
 * - provider trust
 * - mission priority
 * - historical success
 * - learning signal
 * - knowledge confidence
 * Permission must be explicit, scoped, auditable, and revocable.
 */

import { ActionRiskLevel } from '../types/actionBus';
import {
  ConnectorId,
  ConnectorPermission,
  ConnectorScope,
  AgentCapabilityGrant,
  MissionCapabilityGrant,
} from '../types/connectorFabric';
import { connectorRegistry } from './connectorRegistry';
import { executionPersistence } from './executionPersistence';

export class ConnectorPermissionService {
  /**
   * Evaluates if a target resource path matches a declared permission scope.
   * Supports prefix, exact, and wildcard patterns (* and **).
   */
  public matchScope(target: string | undefined, scope: ConnectorScope): boolean {
    if (!target) return true; // Operation is non-resource-specific
    const pattern = scope.resourcePath;

    if (pattern === '*' || pattern === '**') return true;
    if (pattern === target) return true;

    // Wildcard prefix matching, e.g. "aryaos/*" matches "aryaos/core"
    if (pattern.endsWith('/*')) {
      const prefix = pattern.slice(0, -2);
      return target.startsWith(prefix);
    }

    // Path prefix matching, e.g. "/workspace" matches "/workspace/docs/file.txt"
    if (target.startsWith(pattern)) return true;

    return false;
  }

  /**
   * Grants a capability explicitly to an AI Agent.
   * Enforces DEFAULT DENY for all non-granted capabilities.
   */
  public grantAgentCapability(
    grantInput: Omit<AgentCapabilityGrant, 'grantId' | 'grantedAt' | 'grantStatus'>
  ): AgentCapabilityGrant {
    const grant: AgentCapabilityGrant = {
      ...grantInput,
      grantId: `acg_${grantInput.agentId}_${grantInput.capabilityId}_${Date.now()}`,
      grantStatus: 'ACTIVE',
      grantedAt: new Date().toISOString(),
    };

    executionPersistence.saveAgentCapabilityGrant(grant);
    return grant;
  }

  /**
   * Grants a capability explicitly to a long-horizon Mission.
   */
  public grantMissionCapability(
    grantInput: Omit<MissionCapabilityGrant, 'grantId' | 'grantedAt' | 'grantStatus'>
  ): MissionCapabilityGrant {
    const grant: MissionCapabilityGrant = {
      ...grantInput,
      grantId: `mcg_${grantInput.missionId}_${grantInput.capabilityId}_${Date.now()}`,
      grantStatus: 'ACTIVE',
      grantedAt: new Date().toISOString(),
    };

    executionPersistence.saveMissionCapabilityGrant(grant);
    return grant;
  }

  /**
   * Updates connector permissions and increments permissionVersion to invalidate stale decisions.
   */
  public updateConnectorPermissions(
    connectorId: ConnectorId,
    newPermissions: ConnectorPermission[],
    actor = 'OPERATOR'
  ): void {
    const conn = connectorRegistry.getConnector(connectorId);
    if (!conn) {
      throw new Error(`Cannot update permissions for non-existent connector '${connectorId}'`);
    }

    conn.permissions = [...newPermissions];
    conn.permissionVersion++; // Invalidate stale cached authorizations
    conn.updatedAt = new Date().toISOString();
    connectorRegistry.updateConnector(conn);

    executionPersistence.saveConnectorAuditEvent({
      eventId: `cpe_${connectorId}_${Date.now()}`,
      connectorId,
      timestamp: new Date().toISOString(),
      actor,
      previousState: conn.status,
      newState: conn.status,
      reason: `Permissions updated to version ${conn.permissionVersion}`,
      permissionVersion: conn.permissionVersion,
      provenance: {
        connectorId,
        permissionVersion: conn.permissionVersion,
        timestamp: new Date().toISOString(),
        actor,
      },
    });
  }

  /**
   * Core multi-tier authorization chain:
   * AGENT -> MISSION -> CONNECTOR -> CAPABILITY -> RESOURCE SCOPE -> ACTION -> HUMAN APPROVAL
   */
  public evaluateAuthorization(params: {
    connectorId: ConnectorId;
    capabilityId: string;
    operation: string;
    resourceTarget?: string;
    agentId?: string;
    missionId?: string;
    verifiedPermissionVersion?: number;
    strictMissionScoping?: boolean;
    effectiveRisk?: ActionRiskLevel;
    operatorApproval?: { approvedBy: string; signature?: string };
  }): {
    authorized: boolean;
    reason?: string;
    permissionVersion?: number;
    requiredRisk?: ActionRiskLevel;
  } {
    const conn = connectorRegistry.getConnector(params.connectorId);
    if (!conn) {
      return { authorized: false, reason: `Connector '${params.connectorId}' is not registered.` };
    }

    // 1. Permission Version Check (detect stale authorizations)
    if (
      params.verifiedPermissionVersion !== undefined &&
      params.verifiedPermissionVersion !== conn.permissionVersion
    ) {
      return {
        authorized: false,
        reason: `Stale permission authorization detected: Expected v${params.verifiedPermissionVersion}, but connector is currently on v${conn.permissionVersion}. Reauthorization required.`,
        permissionVersion: conn.permissionVersion,
      };
    }

    // 2. Connector Permission Verification
    const matchingPerm = conn.permissions.find((p) => {
      const opMatch = p.scope.allowedOperations.includes(params.operation) || p.scope.allowedOperations.includes('*');
      const scopeMatch = this.matchScope(params.resourceTarget, p.scope);
      return opMatch && scopeMatch;
    });

    if (!matchingPerm) {
      return {
        authorized: false,
        reason: `Connector '${params.connectorId}' lacks permission for operation '${params.operation}' on target '${params.resourceTarget || 'default'}'. (Default DENY)`,
        permissionVersion: conn.permissionVersion,
      };
    }

    // 3. Agent Capability Grant Check (Default DENY for agents)
    if (params.agentId) {
      const grants = executionPersistence.getAllAgentCapabilityGrants(params.agentId);
      const activeGrant = grants.find(
        (g) =>
          g.grantStatus === 'ACTIVE' &&
          g.connectorId === params.connectorId &&
          (g.capabilityId === params.capabilityId || g.capabilityId === '*') &&
          this.matchScope(params.resourceTarget, g.scope)
      );

      if (!activeGrant) {
        return {
          authorized: false,
          reason: `Agent '${params.agentId}' does not have an active capability grant for '${params.capabilityId}' on '${params.resourceTarget || '*'}' (Default DENY).`,
          permissionVersion: conn.permissionVersion,
        };
      }

      // Check grant expiration
      if (activeGrant.expiresAt && new Date(activeGrant.expiresAt).getTime() <= Date.now()) {
        return {
          authorized: false,
          reason: `Agent '${params.agentId}' capability grant has expired.`,
          permissionVersion: conn.permissionVersion,
        };
      }
    }

    // 4. Mission Capability Grant Check (Default DENY for missions)
    if (params.missionId) {
      const grants = executionPersistence.getAllMissionCapabilityGrants(params.missionId);
      const activeGrant = grants.find(
        (g) =>
          g.grantStatus === 'ACTIVE' &&
          g.connectorId === params.connectorId &&
          (g.capabilityId === params.capabilityId || g.capabilityId === '*') &&
          this.matchScope(params.resourceTarget, g.scope)
      );

      if (!activeGrant) {
        return {
          authorized: false,
          reason: `Mission '${params.missionId}' does not have an active capability grant for '${params.capabilityId}' (Default DENY).`,
          permissionVersion: conn.permissionVersion,
        };
      }

      // Check grant expiration
      if (activeGrant.expiresAt && new Date(activeGrant.expiresAt).getTime() <= Date.now()) {
        return {
          authorized: false,
          reason: `Mission '${params.missionId}' capability grant has expired.`,
          permissionVersion: conn.permissionVersion,
        };
      }
    }

    // 5. Human Signoff Boundary for High / Critical Risk
    const effectiveRisk: ActionRiskLevel = params.effectiveRisk || matchingPerm.riskTier;
    const requiresHuman =
      matchingPerm.requiresHumanApproval ||
      effectiveRisk === 'CRITICAL' ||
      (effectiveRisk === 'HIGH' && !matchingPerm.scope.readOnly);

    if (requiresHuman) {
      if (!params.operatorApproval || !params.operatorApproval.approvedBy) {
        return {
          authorized: false,
          reason: `Operation requires explicit human operator signoff (Risk: ${effectiveRisk}).`,
          permissionVersion: conn.permissionVersion,
          requiredRisk: effectiveRisk,
        };
      }

      if (
        params.operatorApproval.approvedBy === 'SYSTEM' ||
        params.operatorApproval.approvedBy === 'AUTONOMOUS_AGENT'
      ) {
        return {
          authorized: false,
          reason: `Autonomous approval is strictly prohibited for privileged operations.`,
          permissionVersion: conn.permissionVersion,
          requiredRisk: effectiveRisk,
        };
      }
    }

    return {
      authorized: true,
      permissionVersion: conn.permissionVersion,
      requiredRisk: effectiveRisk,
    };
  }
}

export const connectorPermissionService = new ConnectorPermissionService();
