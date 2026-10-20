/**
 * AryaOS V1 — Stage 16: Connector Lifecycle Service
 *
 * Enforces valid state machine transitions for external connectors.
 * Records immutable lifecycle audit events into execution persistence.
 * Prevents invalid state jumps and governs revocation and disconnection.
 */

import {
  Connector,
  ConnectorId,
  ConnectorStatus,
  ConnectorLifecycleEvent,
} from '../types/connectorFabric';
import { connectorRegistry } from './connectorRegistry';
import { executionPersistence } from './executionPersistence';

export class ConnectorLifecycleService {
  /**
   * Allowed state transitions map.
   */
  private readonly validTransitions: Record<ConnectorStatus, ConnectorStatus[]> = {
    DISCOVERED: ['CONFIGURING', 'DISABLED'],
    CONFIGURING: ['AWAITING_HUMAN_AUTHORIZATION', 'AUTHENTICATING', 'DISABLED', 'ERROR', 'CONFIGURATION_REQUIRED'],
    AWAITING_HUMAN_AUTHORIZATION: ['AUTHENTICATING', 'CONFIGURING', 'DISABLED', 'REVOKED'],
    AUTHENTICATING: ['CONNECTED', 'CONFIGURING', 'ERROR', 'AUTH_FAILED', 'AUTH_REQUIRED'],
    CONNECTED: ['HEALTH_CHECK', 'ACTIVE', 'DEGRADED', 'DISCONNECTING', 'REVOKED'],
    HEALTH_CHECK: ['ACTIVE', 'DEGRADED', 'UNAVAILABLE', 'REVOKED'],
    ACTIVE: ['DEGRADED', 'DISCONNECTING', 'REVOKED', 'DISABLED', 'SUSPENDED', 'EXPIRED'],
    DEGRADED: ['ACTIVE', 'DISCONNECTING', 'REVOKED', 'DISABLED', 'UNAVAILABLE'],
    SUSPENDED: ['ACTIVE', 'CONFIGURING', 'REVOKED'],
    DISCONNECTING: ['DISCONNECTED', 'REVOKED'],
    DISCONNECTED: ['CONFIGURING', 'AUTHENTICATING', 'REVOKED'],
    REVOKED: ['CONFIGURING', 'DISCOVERED'], // Must reconfigure from scratch
    ERROR: ['CONFIGURING', 'AUTHENTICATING', 'DISABLED', 'REVOKED'],
    DISABLED: ['CONFIGURING', 'AUTHENTICATING', 'ACTIVE'],
    AUTH_REQUIRED: ['AUTHENTICATING', 'CONFIGURING', 'REVOKED'],
    CONFIGURATION_REQUIRED: ['CONFIGURING', 'REVOKED'],
    AUTH_FAILED: ['AUTHENTICATING', 'CONFIGURING', 'REVOKED'],
    EXPIRED: ['AUTHENTICATING', 'CONFIGURING', 'REVOKED'],
    UNAVAILABLE: ['HEALTH_CHECK', 'ACTIVE', 'CONFIGURING', 'DEGRADED'],
  };

  /**
   * Transitions a connector to a new state if the transition is valid.
   */
  public transition(
    connectorId: ConnectorId,
    newState: ConnectorStatus,
    actor: string,
    reason: string
  ): Connector {
    const connector = connectorRegistry.getConnector(connectorId);
    if (!connector) {
      throw new Error(`Cannot transition non-existent connector '${connectorId}'`);
    }

    const previousState = connector.status;
    if (previousState === newState) {
      return connector; // Idempotent no-op
    }

    const allowed = this.validTransitions[previousState] || [];
    if (!allowed.includes(newState)) {
      throw new Error(
        `Invalid lifecycle transition rejected: Cannot move connector '${connectorId}' from '${previousState}' to '${newState}'. Allowed: [${allowed.join(', ')}]`
      );
    }

    connector.status = newState;
    connector.updatedAt = new Date().toISOString();

    // If active, ensure health reflects connectivity
    if (newState === 'ACTIVE') {
      connector.health = 'HEALTHY';
    } else if (newState === 'REVOKED') {
      connector.health = 'AUTH_REQUIRED';
      if (connector.credentialRef) {
        connector.credentialRef.status = 'REVOKED';
      }
      connector.permissionVersion++;
    } else if (newState === 'DISCONNECTED') {
      connector.health = 'UNAVAILABLE';
    }

    connectorRegistry.updateConnector(connector);

    // Record Lifecycle Audit Event
    const event: ConnectorLifecycleEvent = {
      eventId: `cle_${connectorId}_${Date.now()}_${Math.random().toString(36).slice(2, 6)}`,
      connectorId,
      timestamp: new Date().toISOString(),
      actor,
      previousState,
      newState,
      reason,
      permissionVersion: connector.permissionVersion,
      provenance: {
        connectorId,
        permissionVersion: connector.permissionVersion,
        timestamp: new Date().toISOString(),
        actor,
      },
    };

    executionPersistence.saveConnectorAuditEvent(event);
    return connector;
  }

  /**
   * Revokes a connector, invalidating its credential reference and permissions.
   */
  public revokeConnector(connectorId: ConnectorId, actor: string, reason: string): Connector {
    return this.transition(connectorId, 'REVOKED', actor, reason);
  }

  /**
   * Disconnects an active connector cleanly.
   */
  public disconnectConnector(connectorId: ConnectorId, actor: string, reason: string): Connector {
    const conn = connectorRegistry.getConnector(connectorId);
    if (!conn) {
      throw new Error(`Cannot disconnect non-existent connector '${connectorId}'`);
    }

    if (conn.status === 'ACTIVE' || conn.status === 'DEGRADED') {
      this.transition(connectorId, 'DISCONNECTING', actor, reason);
    }
    return this.transition(connectorId, 'DISCONNECTED', actor, reason);
  }
}

export const connectorLifecycleService = new ConnectorLifecycleService();
