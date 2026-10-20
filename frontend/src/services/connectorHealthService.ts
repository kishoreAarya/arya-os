/**
 * AryaOS V1 — Stage 16: Connector Health Service
 *
 * Evaluates operational readiness and health for registered connectors.
 * Enforces bounded, on-demand health verification (zero high-frequency background polling).
 * Provides health-based execution gatekeeper for Stage 15 Action Bus.
 */

import {
  ConnectorId,
  ConnectorHealth,
} from '../types/connectorFabric';
import { connectorRegistry } from './connectorRegistry';
import { credentialBoundary } from './credentialBoundary';
import { executionPersistence } from './executionPersistence';

export class ConnectorHealthService {
  private lastChecked = new Map<ConnectorId, number>();
  private readonly checkThrottleMs = 1000; // Minimum interval between checks

  /**
   * Performs an on-demand, bounded health check for a connector.
   */
  public async checkHealth(connectorId: ConnectorId): Promise<ConnectorHealth> {
    const conn = connectorRegistry.getConnector(connectorId);
    if (!conn) {
      return 'UNAVAILABLE';
    }

    // Check status invariants
    if (conn.status === 'REVOKED') {
      conn.health = 'AUTH_REQUIRED';
      connectorRegistry.updateConnector(conn);
      return 'AUTH_REQUIRED';
    }

    if (conn.status === 'DISABLED' || conn.status === 'DISCONNECTED') {
      conn.health = 'UNAVAILABLE';
      connectorRegistry.updateConnector(conn);
      return 'UNAVAILABLE';
    }

    // Check credential status
    const credStatus = credentialBoundary.validateCredentialRef(conn.credentialRef);
    if (credStatus === 'EXPIRED' || credStatus === 'CONFIGURATION_REQUIRED' || credStatus === 'REVOKED') {
      conn.health = 'AUTH_REQUIRED';
      connectorRegistry.updateConnector(conn);
      return 'AUTH_REQUIRED';
    }

    // Throttled refresh
    const now = Date.now();
    const prev = this.lastChecked.get(connectorId) || 0;
    if (now - prev > this.checkThrottleMs) {
      this.lastChecked.set(connectorId, now);
      conn.health = conn.status === 'ACTIVE' ? 'HEALTHY' : 'DEGRADED';
      connectorRegistry.updateConnector(conn);
    }

    return conn.health;
  }

  /**
   * Health-based action blocking gatekeeper.
   * Prevents executing actions through unavailable, revoked, or unauthenticated connectors.
   */
  public evaluateActionReadiness(connectorId: ConnectorId): {
    ready: boolean;
    status: 'READY' | 'REQUIRES_CONFIGURATION' | 'DENIED' | 'UNAVAILABLE' | 'DISABLED';
    reason?: string;
  } {
    const conn = connectorRegistry.getConnector(connectorId);
    if (!conn) {
      return { ready: false, status: 'UNAVAILABLE', reason: `Connector '${connectorId}' is not registered.` };
    }

    if (conn.status === 'DISABLED') {
      return { ready: false, status: 'DISABLED', reason: `Connector '${connectorId}' is currently disabled.` };
    }

    if (conn.status === 'REVOKED') {
      return { ready: false, status: 'DENIED', reason: `Connector '${connectorId}' has been revoked.` };
    }

    if (conn.status === 'DISCONNECTED' || conn.health === 'UNAVAILABLE') {
      return { ready: false, status: 'UNAVAILABLE', reason: `Connector '${connectorId}' is disconnected or unavailable.` };
    }

    const credStatus = credentialBoundary.validateCredentialRef(conn.credentialRef);
    if (credStatus === 'CONFIGURATION_REQUIRED' || credStatus === 'EXPIRED' || conn.health === 'AUTH_REQUIRED') {
      return {
        ready: false,
        status: 'REQUIRES_CONFIGURATION',
        reason: `Connector '${connectorId}' requires credential configuration or re-authentication (Credential status: ${credStatus}).`,
      };
    }

    return { ready: true, status: 'READY' };
  }

  /**
   * Explicitly sets health status for testing or manual intervention.
   */
  public setHealth(connectorId: ConnectorId, health: ConnectorHealth): void {
    const conn = connectorRegistry.getConnector(connectorId);
    if (conn) {
      conn.health = health;
      connectorRegistry.updateConnector(conn);
    }
  }
}

export const connectorHealthService = new ConnectorHealthService();
