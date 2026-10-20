/**
 * AryaOS V1 — Stage 17: Controlled Connector Installation Service
 *
 * Implements the verified, human-governed connector activation lifecycle:
 * DISCOVERED -> CONFIGURING -> AWAITING_HUMAN_AUTHORIZATION -> AUTHENTICATING -> CONNECTED -> HEALTH_CHECK -> ACTIVE
 *
 * CRITICAL ARCHITECTURAL BOUNDARY:
 * Connecting a connector does NOT grant capability permissions,
 * agent authority, or mission authority.
 * Autonomous installation approvals are strictly rejected.
 */

import {
  Connector,
  ConnectorId,
  ConnectorType,
  ConnectorConfiguration,
  ConnectorScope,
  ConnectorPermission,
  ConnectorCredentialRef,
} from '../types/connectorFabric';
import { connectorRegistry } from './connectorRegistry';
import { connectorDiscoveryService } from './connectorDiscoveryService';
import { connectorLifecycleService } from './connectorLifecycleService';
import { connectorHealthService } from './connectorHealthService';
import { credentialBoundary } from './credentialBoundary';
import { oauthBoundary } from './oauthBoundary';

export interface HumanApprovalSignoff {
  approvedBy: string;
  signature?: string;
  timestamp: string;
  notes?: string;
}

export interface ConnectorInstallRequest {
  id: ConnectorId;
  type: ConnectorType;
  name: string;
  configuration: ConnectorConfiguration;
  scopes?: ConnectorScope[];
  permissions?: ConnectorPermission[];
  humanSignoff?: HumanApprovalSignoff;
  oauthParams?: {
    authorizationCode: string;
    state: string;
    redirectUri: string;
  };
}

export class ConnectorInstallationService {
  /**
   * Installs and activates a connector through the governed Stage 17 lifecycle.
   */
  public async installAndActivate(request: ConnectorInstallRequest): Promise<Connector> {
    // 1. Discovery Validation
    const discoveryDef = connectorDiscoveryService.getDiscoveryDefinition(request.type);
    if (!discoveryDef) {
      throw new Error(`Connector Installation Error: Unsupported connector type '${request.type}'.`);
    }

    // 2. Configuration Validation
    if (discoveryDef.authenticationModes.includes('OAUTH2')) {
      if (!request.configuration.clientId) {
        throw new Error(`CONFIGURATION_REQUIRED: OAuth connector '${request.id}' requires 'clientId' configuration.`);
      }
    }

    // 3. Human Authorization Requirement
    // Connecting external infrastructure MUST have human operator signoff
    if (!request.humanSignoff || !request.humanSignoff.approvedBy) {
      throw new Error(`Human Authorization Rejection: Activating connector '${request.id}' requires explicit human operator signoff.`);
    }

    const approver = request.humanSignoff.approvedBy;
    if (approver === 'AUTONOMOUS_AGENT' || approver === 'SYSTEM') {
      throw new Error(`Security Boundary Violation: Autonomous agent '${approver}' cannot authorize connector installation.`);
    }

    // 4. Initial Registration in DISCOVERED / CONFIGURING
    const initialConnector: Connector = {
      id: request.id,
      name: request.name,
      type: request.type,
      version: discoveryDef.version,
      status: 'DISCOVERED',
      health: 'UNKNOWN',
      configuration: request.configuration,
      scopes: request.scopes || [],
      permissions: request.permissions || [],
      capabilities: [],
      permissionVersion: 1,
      createdAt: new Date().toISOString(),
      updatedAt: new Date().toISOString(),
    };

    connectorRegistry.registerConnector(initialConnector);

    // 5. Lifecycle Transition: DISCOVERED -> CONFIGURING
    connectorLifecycleService.transition(request.id, 'CONFIGURING', approver, 'Operator configured parameters');

    // 6. Lifecycle Transition: CONFIGURING -> AWAITING_HUMAN_AUTHORIZATION
    connectorLifecycleService.transition(request.id, 'AWAITING_HUMAN_AUTHORIZATION', approver, 'Operator authorization requested');

    // 7. Lifecycle Transition: AWAITING_HUMAN_AUTHORIZATION -> AUTHENTICATING
    connectorLifecycleService.transition(request.id, 'AUTHENTICATING', approver, 'Operator signed authorization');

    // 8. Ephemeral Credential Resolution / OAuth Exchange
    let credentialRef: ConnectorCredentialRef;
    if (request.oauthParams) {
      credentialRef = await oauthBoundary.exchangeCodeForCredentialRef({
        connectorId: request.id,
        connectorType: request.type,
        authorizationCode: request.oauthParams.authorizationCode,
        state: request.oauthParams.state,
        redirectUri: request.oauthParams.redirectUri,
      });
    } else {
      credentialRef = credentialBoundary.createCredentialRef(
        request.id,
        discoveryDef.authenticationModes[0] || 'NONE',
        { status: 'VALID' }
      );
    }

    // Update connector with credentialRef
    const registered = connectorRegistry.getConnector(request.id)!;
    registered.credentialRef = credentialRef;
    connectorRegistry.updateConnector(registered);

    // 9. Lifecycle Transition: AUTHENTICATING -> CONNECTED
    connectorLifecycleService.transition(request.id, 'CONNECTED', approver, 'Authentication established');

    // 10. Lifecycle Transition: CONNECTED -> HEALTH_CHECK
    connectorLifecycleService.transition(request.id, 'HEALTH_CHECK', 'SYSTEM', 'Validating connectivity');

    // 11. Health Assessment
    const health = await connectorHealthService.checkHealth(request.id);
    if (health === 'UNAVAILABLE' || health === 'AUTH_REQUIRED') {
      connectorLifecycleService.transition(request.id, 'DEGRADED', 'SYSTEM', `Initial health check degraded: ${health}`);
      registered.health = health;
      connectorRegistry.updateConnector(registered);
      return registered;
    }

    // 12. Lifecycle Transition: HEALTH_CHECK -> ACTIVE
    const activated = connectorLifecycleService.transition(request.id, 'ACTIVE', approver, 'Health check passed and verified');
    activated.health = 'HEALTHY';
    connectorRegistry.updateConnector(activated);

    return activated;
  }
}

export const connectorInstallationService = new ConnectorInstallationService();
