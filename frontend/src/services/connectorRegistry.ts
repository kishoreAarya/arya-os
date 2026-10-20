/**
 * AryaOS V1 — Stage 16: Connector Registry
 *
 * Deterministic registration and lifecycle catalog for external connectors.
 * Rejects duplicate connector registrations.
 * Maps connectors to their exposed capabilities, permissions, health, and scopes.
 */

import {
  Connector,
  ConnectorId,
  ConnectorType,
  ConnectorStatus,
  ConnectorHealth,
  ConnectorCapability,
  ConnectorPermission,
} from '../types/connectorFabric';
import { executionPersistence } from './executionPersistence';

export class ConnectorRegistry {
  private connectors = new Map<ConnectorId, Connector>();

  constructor() {
    this.registerDefaultConnectors();
  }

  /**
   * Registers a new external connector into the fabric.
   * Deterministic: rejects duplicate IDs.
   */
  public registerConnector(connector: Connector): void {
    if (this.connectors.has(connector.id)) {
      throw new Error(`Duplicate connector registration rejected: Connector '${connector.id}' is already registered.`);
    }

    this.connectors.set(connector.id, { ...connector });
    executionPersistence.saveConnector(connector);
  }

  /**
   * Retrieves a connector by ID.
   */
  public getConnector(connectorId: ConnectorId): Connector | null {
    return this.connectors.get(connectorId) || null;
  }

  /**
   * Lists connectors with optional filtering.
   */
  public listConnectors(filter?: {
    type?: ConnectorType;
    status?: ConnectorStatus;
    health?: ConnectorHealth;
  }): Connector[] {
    let list = Array.from(this.connectors.values());
    if (filter?.type) list = list.filter((c) => c.type === filter.type);
    if (filter?.status) list = list.filter((c) => c.status === filter.status);
    if (filter?.health) list = list.filter((c) => c.health === filter.health);
    return list;
  }

  /**
   * Disables an active connector.
   */
  public disableConnector(connectorId: ConnectorId, reason = 'Operator disabled connector'): boolean {
    const conn = this.connectors.get(connectorId);
    if (!conn) return false;

    conn.status = 'DISABLED';
    conn.updatedAt = new Date().toISOString();
    this.connectors.set(connectorId, conn);
    executionPersistence.saveConnector(conn);
    return true;
  }

  /**
   * Enables a disabled connector.
   */
  public enableConnector(connectorId: ConnectorId): boolean {
    const conn = this.connectors.get(connectorId);
    if (!conn) return false;

    conn.status = conn.credentialRef?.status === 'VALID' ? 'ACTIVE' : 'CONFIGURING';
    conn.updatedAt = new Date().toISOString();
    this.connectors.set(connectorId, conn);
    executionPersistence.saveConnector(conn);
    return true;
  }

  /**
   * Removes a connector from the registry.
   */
  public removeConnector(connectorId: ConnectorId): boolean {
    if (!this.connectors.has(connectorId)) return false;
    this.connectors.delete(connectorId);
    executionPersistence.deleteConnector(connectorId);
    return true;
  }

  /**
   * Returns all capabilities exposed by a specific connector.
   */
  public getConnectorCapabilities(connectorId: ConnectorId): ConnectorCapability[] {
    const conn = this.connectors.get(connectorId);
    return conn ? [...conn.capabilities] : [];
  }

  /**
   * Returns the current health state of a connector.
   */
  public getConnectorHealth(connectorId: ConnectorId): ConnectorHealth {
    const conn = this.connectors.get(connectorId);
    return conn ? conn.health : 'UNKNOWN';
  }

  /**
   * Updates an existing connector in memory and persistence.
   */
  public updateConnector(connector: Connector): void {
    if (!this.connectors.has(connector.id)) {
      throw new Error(`Cannot update non-existent connector '${connector.id}'`);
    }
    this.connectors.set(connector.id, { ...connector });
    executionPersistence.saveConnector(connector);
  }

  /**
   * Clears registry and restores default connector baseline.
   */
  public reset(): void {
    this.connectors.clear();
    this.registerDefaultConnectors();
  }

  /**
   * Registers default reference connector blueprints in sandboxed offline state.
   */
  private registerDefaultConnectors(): void {
    // 1. Filesystem Connector
    const fsPerms: ConnectorPermission[] = [
      {
        permissionId: 'perm_fs_read',
        connectorId: 'connector_filesystem',
        name: 'Filesystem Sandboxed Read',
        scope: {
          resourceType: 'directory',
          resourcePath: '/workspace',
          allowedOperations: ['read_file', 'list_directory'],
          readOnly: true,
        },
        riskTier: 'LOW',
        requiresHumanApproval: false,
        version: 1,
      },
      {
        permissionId: 'perm_fs_read_sandbox',
        connectorId: 'connector_filesystem',
        name: 'Filesystem Sandbox Read',
        scope: {
          resourceType: 'directory',
          resourcePath: '/tmp/sandbox',
          allowedOperations: ['read_file', 'list_directory'],
          readOnly: true,
        },
        riskTier: 'LOW',
        requiresHumanApproval: false,
        version: 1,
      },
      {
        permissionId: 'perm_fs_read_data',
        connectorId: 'connector_filesystem',
        name: 'Filesystem Data Read',
        scope: {
          resourceType: 'directory',
          resourcePath: '/data',
          allowedOperations: ['read_file', 'list_directory'],
          readOnly: true,
        },
        riskTier: 'LOW',
        requiresHumanApproval: false,
        version: 1,
      },
      {
        permissionId: 'perm_fs_write',
        connectorId: 'connector_filesystem',
        name: 'Filesystem Sandboxed Write',
        scope: {
          resourceType: 'directory',
          resourcePath: '/workspace',
          allowedOperations: ['write_file', 'delete_file'],
          readOnly: false,
        },
        riskTier: 'HIGH',
        requiresHumanApproval: true,
        version: 1,
      },
      {
        permissionId: 'perm_fs_write_sandbox',
        connectorId: 'connector_filesystem',
        name: 'Filesystem Sandbox Write',
        scope: {
          resourceType: 'directory',
          resourcePath: '/tmp/sandbox',
          allowedOperations: ['write_file', 'delete_file'],
          readOnly: false,
        },
        riskTier: 'HIGH',
        requiresHumanApproval: true,
        version: 1,
      },
    ];

    const fsCaps: ConnectorCapability[] = [
      {
        capabilityId: 'filesystem.read',
        connectorId: 'connector_filesystem',
        name: 'Filesystem Reader',
        version: '1.0.0',
        riskLevel: 'LOW',
        requiredPermissions: ['perm_fs_read'],
        supportedOperations: ['read_file', 'list_directory'],
        inputSchema: { type: 'object', required: ['path'] },
      },
      {
        capabilityId: 'filesystem.write',
        connectorId: 'connector_filesystem',
        name: 'Filesystem Writer',
        version: '1.0.0',
        riskLevel: 'HIGH',
        requiredPermissions: ['perm_fs_write'],
        supportedOperations: ['write_file', 'delete_file'],
        inputSchema: { type: 'object', required: ['path'] },
      },
    ];

    this.registerConnector({
      id: 'connector_filesystem',
      name: 'Local Filesystem Connector',
      type: 'FILESYSTEM',
      version: '1.0.0',
      status: 'ACTIVE',
      health: 'HEALTHY',
      configuration: { baseUrl: 'file:///', settings: { root: '/workspace' } },
      scopes: [
        { resourceType: 'directory', resourcePath: '/workspace', allowedOperations: ['read_file', 'write_file', 'delete_file', 'list_directory'], readOnly: false },
        { resourceType: 'directory', resourcePath: '/data', allowedOperations: ['read_file', 'list_directory'], readOnly: true },
        { resourceType: 'directory', resourcePath: '/tmp/sandbox', allowedOperations: ['read_file', 'write_file', 'delete_file', 'list_directory'], readOnly: false },
      ],
      credentialRef: {
        credentialId: 'cred_ref_fs_local',
        connectorId: 'connector_filesystem',
        credentialType: 'LOCAL_CREDENTIAL',
        createdAt: new Date().toISOString(),
        status: 'VALID',
      },
      permissions: fsPerms,
      capabilities: fsCaps,
      permissionVersion: 1,
      createdAt: new Date().toISOString(),
      updatedAt: new Date().toISOString(),
    });

    // 2. Web Search Connector
    this.registerConnector({
      id: 'connector_web',
      name: 'Web Query Connector',
      type: 'WEB',
      version: '1.0.0',
      status: 'ACTIVE',
      health: 'HEALTHY',
      configuration: { baseUrl: 'https://duckduckgo.com' },
      scopes: [
        { resourceType: 'domain', resourcePath: '*.google.com', allowedOperations: ['query'], readOnly: true },
        { resourceType: 'domain', resourcePath: '*.duckduckgo.com', allowedOperations: ['query'], readOnly: true },
      ],
      credentialRef: {
        credentialId: 'cred_ref_web_public',
        connectorId: 'connector_web',
        credentialType: 'NONE',
        createdAt: new Date().toISOString(),
        status: 'VALID',
      },
      permissions: [
        {
          permissionId: 'perm_web_search',
          connectorId: 'connector_web',
          name: 'Web Query Permission',
          scope: { resourceType: 'domain', resourcePath: '*', allowedOperations: ['query'], readOnly: true },
          riskTier: 'LOW',
          requiresHumanApproval: false,
          version: 1,
        },
      ],
      capabilities: [
        {
          capabilityId: 'web.search',
          connectorId: 'connector_web',
          name: 'Web Search Engine',
          version: '1.0.0',
          riskLevel: 'LOW',
          requiredPermissions: ['perm_web_search'],
          supportedOperations: ['query'],
          inputSchema: { type: 'object', required: ['query'] },
        },
      ],
      permissionVersion: 1,
      createdAt: new Date().toISOString(),
      updatedAt: new Date().toISOString(),
    });

    // 3. GitHub Connector
    this.registerConnector({
      id: 'connector_github',
      name: 'GitHub VCS Connector',
      type: 'GITHUB',
      version: '1.0.0',
      status: 'CONFIGURING',
      health: 'AUTH_REQUIRED',
      configuration: { baseUrl: 'https://api.github.com', clientId: 'aryaos-github-app' },
      scopes: [
        { resourceType: 'repository', resourcePath: 'aryaos/core', allowedOperations: ['get_issue', 'create_issue'], readOnly: false },
        { resourceType: 'repository', resourcePath: 'aryaos/workspace', allowedOperations: ['get_issue'], readOnly: true },
        { resourceType: 'repository', resourcePath: 'aryaos/*', allowedOperations: ['get_issue', 'create_issue', 'comment_issue'], readOnly: false },
      ],
      credentialRef: {
        credentialId: 'cred_ref_gh_default',
        connectorId: 'connector_github',
        credentialType: 'OAUTH2',
        createdAt: new Date().toISOString(),
        status: 'CONFIGURATION_REQUIRED',
        metadata: { sandboxMode: true },
      },
      permissions: [
        {
          permissionId: 'perm_gh_read',
          connectorId: 'connector_github',
          name: 'GitHub Issue Reader',
          scope: { resourceType: 'repository', resourcePath: 'aryaos/*', allowedOperations: ['get_issue', 'list_issues'], readOnly: true },
          riskTier: 'LOW',
          requiresHumanApproval: false,
          version: 1,
        },
        {
          permissionId: 'perm_gh_write',
          connectorId: 'connector_github',
          name: 'GitHub Issue Writer',
          scope: { resourceType: 'repository', resourcePath: 'aryaos/*', allowedOperations: ['create_issue', 'comment_issue'], readOnly: false },
          riskTier: 'MEDIUM',
          requiresHumanApproval: true,
          version: 1,
        },
      ],
      capabilities: [
        {
          capabilityId: 'github.issue_read',
          connectorId: 'connector_github',
          name: 'GitHub Issue Reader',
          version: '1.0.0',
          riskLevel: 'LOW',
          requiredPermissions: ['perm_gh_read'],
          supportedOperations: ['get_issue', 'list_issues'],
          inputSchema: { type: 'object', required: ['repository', 'issueNumber'] },
        },
        {
          capabilityId: 'github.issue_write',
          connectorId: 'connector_github',
          name: 'GitHub Issue Writer',
          version: '1.0.0',
          riskLevel: 'MEDIUM',
          requiredPermissions: ['perm_gh_write'],
          supportedOperations: ['create_issue'],
          inputSchema: { type: 'object', required: ['repository', 'title'] },
        },
      ],
      permissionVersion: 1,
      createdAt: new Date().toISOString(),
      updatedAt: new Date().toISOString(),
    });

    // 4. HTTP Connector
    this.registerConnector({
      id: 'connector_http',
      name: 'External HTTP Connector',
      type: 'CUSTOM',
      version: '1.0.0',
      status: 'ACTIVE',
      health: 'HEALTHY',
      configuration: {},
      scopes: [
        { resourceType: 'domain', resourcePath: '*', allowedOperations: ['get', 'post', 'put', 'delete'], readOnly: false },
      ],
      credentialRef: {
        credentialId: 'cred_ref_http_none',
        connectorId: 'connector_http',
        credentialType: 'NONE',
        createdAt: new Date().toISOString(),
        status: 'VALID',
      },
      permissions: [
        {
          permissionId: 'perm_http_egress',
          connectorId: 'connector_http',
          name: 'HTTP Egress',
          scope: { resourceType: 'domain', resourcePath: '*', allowedOperations: ['get', 'post', 'put', 'delete'], readOnly: false },
          riskTier: 'MEDIUM',
          requiresHumanApproval: false,
          version: 1,
        },
      ],
      capabilities: [
        {
          capabilityId: 'external.http',
          connectorId: 'connector_http',
          name: 'HTTP Client',
          version: '1.0.0',
          riskLevel: 'MEDIUM',
          requiredPermissions: ['perm_http_egress'],
          supportedOperations: ['get', 'post', 'put', 'delete'],
          inputSchema: { type: 'object', required: ['url'] },
        },
      ],
      permissionVersion: 1,
      createdAt: new Date().toISOString(),
      updatedAt: new Date().toISOString(),
    });

    // 5. Notification Connector
    this.registerConnector({
      id: 'connector_notification',
      name: 'Internal Notification Dispatcher',
      type: 'CUSTOM',
      version: '1.0.0',
      status: 'ACTIVE',
      health: 'HEALTHY',
      configuration: {},
      scopes: [
        { resourceType: 'channel', resourcePath: '*', allowedOperations: ['send_message', 'alert'], readOnly: false },
      ],
      credentialRef: {
        credentialId: 'cred_ref_notif_local',
        connectorId: 'connector_notification',
        credentialType: 'NONE',
        createdAt: new Date().toISOString(),
        status: 'VALID',
      },
      permissions: [
        {
          permissionId: 'perm_notif_send',
          connectorId: 'connector_notification',
          name: 'Notification Dispatch',
          scope: { resourceType: 'channel', resourcePath: '*', allowedOperations: ['send_message', 'alert'], readOnly: false },
          riskTier: 'LOW',
          requiresHumanApproval: false,
          version: 1,
        },
      ],
      capabilities: [
        {
          capabilityId: 'notification.send',
          connectorId: 'connector_notification',
          name: 'Notification Dispatcher',
          version: '1.0.0',
          riskLevel: 'LOW',
          requiredPermissions: ['perm_notif_send'],
          supportedOperations: ['send_message', 'alert'],
          inputSchema: { type: 'object', required: ['channel', 'message'] },
        },
      ],
      permissionVersion: 1,
      createdAt: new Date().toISOString(),
      updatedAt: new Date().toISOString(),
    });

    // 6. Google Drive Connector
    this.registerConnector({
      id: 'connector_google_drive',
      name: 'Google Drive Storage Connector',
      type: 'GOOGLE_DRIVE',
      version: '1.0.0',
      status: 'CONFIGURING',
      health: 'AUTH_REQUIRED',
      configuration: { baseUrl: 'https://www.googleapis.com/drive/v3', clientId: 'aryaos-gdrive-client' },
      scopes: [
        { resourceType: 'directory', resourcePath: '/drive/root', allowedOperations: ['list_files', 'read_file'], readOnly: true },
        { resourceType: 'directory', resourcePath: '/drive/workspace', allowedOperations: ['list_files', 'read_file'], readOnly: true },
      ],
      credentialRef: {
        credentialId: 'cred_ref_gdrive_default',
        connectorId: 'connector_google_drive',
        credentialType: 'OAUTH2',
        createdAt: new Date().toISOString(),
        status: 'CONFIGURATION_REQUIRED',
        metadata: { sandboxMode: true },
      },
      permissions: [
        {
          permissionId: 'perm_gdrive_read',
          connectorId: 'connector_google_drive',
          name: 'Google Drive Reader',
          scope: { resourceType: 'directory', resourcePath: '/drive/root', allowedOperations: ['list_files', 'read_file'], readOnly: true },
          riskTier: 'LOW',
          requiresHumanApproval: false,
          version: 1,
        },
      ],
      capabilities: [
        {
          capabilityId: 'google_drive.list_files',
          connectorId: 'connector_google_drive',
          name: 'Google Drive File Lister',
          version: '1.0.0',
          riskLevel: 'LOW',
          requiredPermissions: ['perm_gdrive_read'],
          supportedOperations: ['list_files'],
          inputSchema: { type: 'object' },
        },
        {
          capabilityId: 'google_drive.read_file',
          connectorId: 'connector_google_drive',
          name: 'Google Drive File Reader',
          version: '1.0.0',
          riskLevel: 'LOW',
          requiredPermissions: ['perm_gdrive_read'],
          supportedOperations: ['read_file'],
          inputSchema: { type: 'object', required: ['fileId'] },
        },
      ],
      permissionVersion: 1,
      createdAt: new Date().toISOString(),
      updatedAt: new Date().toISOString(),
    });
  }
}

export const connectorRegistry = new ConnectorRegistry();
