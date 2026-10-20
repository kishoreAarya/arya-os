/**
 * AryaOS V1 — Stage 16: Connector Discovery & Installation Service
 *
 * Provides a discovery catalog of external connector definitions.
 * Governs the installation lifecycle:
 * DISCOVER -> REVIEW -> CONFIGURE -> AUTHORIZE -> CONNECT -> HEALTH CHECK -> ACTIVE
 * Enforces human approval requirement for write, communication, publishing, or destructive permissions.
 */

import {
  Connector,
  ConnectorType,
  ConnectorDiscoveryDefinition,
  ConnectorPermission,
  ConnectorScope,
  ConnectorConfiguration,
} from '../types/connectorFabric';
import { connectorRegistry } from './connectorRegistry';
import { credentialBoundary } from './credentialBoundary';
import { executionPersistence } from './executionPersistence';

export class ConnectorDiscoveryService {
  private definitions: Map<ConnectorType, ConnectorDiscoveryDefinition> = new Map();

  constructor() {
    this.registerStandardDefinitions();
  }

  /**
   * Lists all available connector templates discovered in the system catalog.
   */
  public discoverConnectors(): ConnectorDiscoveryDefinition[] {
    return Array.from(this.definitions.values());
  }

  /**
   * Retrieves a discovery definition by connector type.
   */
  public getDiscoveryDefinition(type: ConnectorType): ConnectorDiscoveryDefinition | null {
    return this.definitions.get(type) || null;
  }

  /**
   * Installs and configures a new connector into the fabric.
   * Requires human approval if permissions involve writes, communication, or destructive operations.
   */
  public installConnector(params: {
    id: string;
    type: ConnectorType;
    name: string;
    configuration: ConnectorConfiguration;
    permissions: ConnectorPermission[];
    scopes: ConnectorScope[];
    humanApproval?: { approvedBy: string; signature?: string };
  }): Connector {
    const def = this.definitions.get(params.type);
    if (!def) {
      throw new Error(`Cannot install connector: Unsupported connector type '${params.type}'`);
    }

    // Check if any requested permissions require human approval
    const requiresHuman = params.permissions.some(
      (p) =>
        p.requiresHumanApproval ||
        p.riskTier === 'HIGH' ||
        p.riskTier === 'CRITICAL' ||
        !p.scope.readOnly ||
        p.scope.allowedOperations.some((op) =>
          ['write', 'delete', 'post', 'send', 'publish', 'purge', 'spend'].some((verb) => op.includes(verb))
        )
    );

    if (requiresHuman) {
      if (!params.humanApproval || !params.humanApproval.approvedBy) {
        throw new Error(
          `Human Governance Rejection: Installing connector '${params.id}' with privileged permissions requires explicit human operator signoff.`
        );
      }
      if (
        params.humanApproval.approvedBy === 'SYSTEM' ||
        params.humanApproval.approvedBy === 'AUTONOMOUS_AGENT'
      ) {
        throw new Error(
          `Security Boundary: Autonomous approval cannot install privileged connectors.`
        );
      }
    }

    const credentialRef = credentialBoundary.createCredentialRef(
      params.id,
      def.authenticationModes[0] || 'NONE',
      { status: def.authenticationModes[0] === 'NONE' ? 'VALID' : 'CONFIGURATION_REQUIRED' }
    );

    const connector: Connector = {
      id: params.id,
      name: params.name,
      type: params.type,
      version: def.version,
      status: credentialRef.status === 'VALID' ? 'ACTIVE' : 'CONFIGURING',
      health: credentialRef.status === 'VALID' ? 'HEALTHY' : 'AUTH_REQUIRED',
      configuration: params.configuration,
      scopes: params.scopes,
      credentialRef,
      permissions: params.permissions,
      capabilities: [], // Populated on registration or capability bind
      permissionVersion: 1,
      createdAt: new Date().toISOString(),
      updatedAt: new Date().toISOString(),
    };

    connectorRegistry.registerConnector(connector);
    return connector;
  }

  private registerStandardDefinitions(): void {
    this.definitions.set('GITHUB', {
      connectorType: 'GITHUB',
      displayName: 'GitHub VCS & Issues',
      description: 'Repositories, issues, PRs, and commit metadata',
      version: '1.0.0',
      supportedCapabilities: ['github.read_issue', 'github.create_issue', 'github.comment_issue'],
      authenticationModes: ['OAUTH2', 'TOKEN'],
      requiredPermissions: ['perm_gh_read', 'perm_gh_write'],
      configurationRequirements: { baseUrl: 'https://api.github.com', clientId: 'OAuth App ID' },
    });

    this.definitions.set('GOOGLE_DRIVE', {
      connectorType: 'GOOGLE_DRIVE',
      displayName: 'Google Drive Storage',
      description: 'Document and media asset synchronization',
      version: '1.0.0',
      supportedCapabilities: ['google_drive.list_files', 'google_drive.read_file', 'gdrive.read', 'gdrive.write'],
      authenticationModes: ['OAUTH2', 'SERVICE_ACCOUNT'],
      requiredPermissions: ['perm_gdrive_read', 'perm_gdrive_write'],
      configurationRequirements: { clientId: 'Google Cloud Client ID' },
    });

    this.definitions.set('SLACK', {
      connectorType: 'SLACK',
      displayName: 'Slack Communications',
      description: 'Channel messaging and thread notifications',
      version: '1.0.0',
      supportedCapabilities: ['slack.read', 'slack.send'],
      authenticationModes: ['OAUTH2', 'TOKEN'],
      requiredPermissions: ['perm_slack_read', 'perm_slack_send'],
      configurationRequirements: { webhookUrl: 'Slack Webhook or Bot Token' },
    });

    this.definitions.set('GMAIL', {
      connectorType: 'GMAIL',
      displayName: 'Gmail Dispatcher',
      description: 'Operational dispatch notifications via email',
      version: '1.0.0',
      supportedCapabilities: ['gmail.send'],
      authenticationModes: ['OAUTH2', 'SERVICE_ACCOUNT'],
      requiredPermissions: ['perm_gmail_send'],
      configurationRequirements: { clientId: 'Google OAuth Client ID' },
    });

    this.definitions.set('CALENDAR', {
      connectorType: 'CALENDAR',
      displayName: 'Google Calendar Scheduler',
      description: 'Mission milestone and schedule synchronization',
      version: '1.0.0',
      supportedCapabilities: ['calendar.read', 'calendar.create_event'],
      authenticationModes: ['OAUTH2'],
      requiredPermissions: ['perm_cal_read', 'perm_cal_write'],
      configurationRequirements: { clientId: 'Google OAuth Client ID' },
    });

    this.definitions.set('POSTIZ', {
      connectorType: 'POSTIZ',
      displayName: 'Postiz Social Publishing',
      description: 'Multi-platform social content scheduler and publisher',
      version: '1.0.0',
      supportedCapabilities: ['postiz.schedule_post', 'postiz.publish'],
      authenticationModes: ['API_KEY'],
      requiredPermissions: ['perm_postiz_schedule', 'perm_postiz_publish'],
      configurationRequirements: { baseUrl: 'Postiz API URL', apiKey: 'API Key Reference' },
    });

    this.definitions.set('FILESYSTEM', {
      connectorType: 'FILESYSTEM',
      displayName: 'Sandboxed Local Filesystem',
      description: 'Local workspace reading and writing within strict sandboxes',
      version: '1.0.0',
      supportedCapabilities: ['filesystem.read', 'filesystem.write'],
      authenticationModes: ['LOCAL_CREDENTIAL', 'NONE'],
      requiredPermissions: ['perm_fs_read', 'perm_fs_write'],
      configurationRequirements: { root: 'Sandbox Directory Path' },
    });

    this.definitions.set('WEB', {
      connectorType: 'WEB',
      displayName: 'Public Web Search & Fetch',
      description: 'Public web search and HTTP document retrieval',
      version: '1.0.0',
      supportedCapabilities: ['web.search', 'external.http'],
      authenticationModes: ['NONE'],
      requiredPermissions: ['perm_web_search'],
      configurationRequirements: {},
    });
  }
}

export const connectorDiscoveryService = new ConnectorDiscoveryService();
