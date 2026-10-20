/**
 * AryaOS V1 — Stage 16: Connector Fabric, Identity & Permission Management
 *
 * Domain contracts for external system connectivity, credentials references,
 * scoped permissions, connector lifecycle, health monitoring, and governance.
 *
 * CRITICAL SEPARATION OF CONCEPTS:
 * - CONNECTOR: authenticated external system connection.
 * - CAPABILITY: operation exposed by a connector.
 * - PERMISSION: authorization to perform an operation.
 * - CREDENTIAL: secret required to authenticate (represented internally via CredentialRef only).
 * - ACTION: concrete invocation dispatched via Stage 15 Universal Action Bus.
 * - PROVIDER: AI execution backend handled by Stage 07 Execution Gateway.
 */

import { ActionRiskLevel } from './actionBus';

export interface ActionSchemaDefinition {
  type?: string;
  required?: string[];
  properties?: Record<string, { type: string; description?: string; enum?: string[] }>;
}

export type ConnectorId = string;

export type ConnectorType =
  | 'GITHUB'
  | 'GOOGLE_DRIVE'
  | 'SLACK'
  | 'GMAIL'
  | 'CALENDAR'
  | 'POSTIZ'
  | 'FILESYSTEM'
  | 'WEB'
  | 'CUSTOM';

export type ConnectorStatus =
  | 'DISCOVERED'
  | 'CONFIGURING'
  | 'AWAITING_HUMAN_AUTHORIZATION'
  | 'AUTHENTICATING'
  | 'CONNECTED'
  | 'HEALTH_CHECK'
  | 'ACTIVE'
  | 'DEGRADED'
  | 'SUSPENDED'
  | 'DISCONNECTING'
  | 'DISCONNECTED'
  | 'REVOKED'
  | 'ERROR'
  | 'DISABLED'
  | 'AUTH_REQUIRED'
  | 'CONFIGURATION_REQUIRED'
  | 'AUTH_FAILED'
  | 'EXPIRED'
  | 'UNAVAILABLE';

export type ConnectorHealth =
  | 'HEALTHY'
  | 'DEGRADED'
  | 'UNAVAILABLE'
  | 'AUTH_REQUIRED'
  | 'PERMISSION_REQUIRED'
  | 'UNKNOWN';

export type CredentialType =
  | 'OAUTH2'
  | 'API_KEY'
  | 'TOKEN'
  | 'SERVICE_ACCOUNT'
  | 'LOCAL_CREDENTIAL'
  | 'NONE';

export type CredentialStatus =
  | 'VALID'
  | 'EXPIRED'
  | 'REVOKED'
  | 'CONFIGURATION_REQUIRED'
  | 'UNKNOWN';

/**
 * Abstract reference to an authentication credential.
 * ABSOLUTE RULE: Never stores or exposes raw tokens, keys, or passwords.
 */
export interface ConnectorCredentialRef {
  credentialId: string;
  connectorId: ConnectorId;
  credentialType: CredentialType;
  createdAt: string;
  expiresAt?: string;
  status: CredentialStatus;
  metadata?: Record<string, unknown>;
}

export interface ConnectorScope {
  resourceType: string; // e.g. 'repository', 'directory', 'channel', 'domain'
  resourcePath: string; // e.g. 'owner/repo', '/workspace', '#general', 'api.github.com'
  allowedOperations: string[];
  readOnly: boolean;
}

export interface ConnectorPermission {
  permissionId: string;
  connectorId: ConnectorId;
  name: string;
  scope: ConnectorScope;
  riskTier: ActionRiskLevel;
  requiresHumanApproval: boolean;
  version: number;
}

export interface ConnectorCapability {
  capabilityId: string;
  connectorId: ConnectorId;
  name: string;
  version: string;
  riskLevel: ActionRiskLevel;
  requiredPermissions: string[];
  supportedOperations: string[];
  inputSchema: ActionSchemaDefinition;
  outputSchema?: ActionSchemaDefinition;
}

export interface ConnectorConfiguration {
  baseUrl?: string;
  clientId?: string;
  scopeList?: string[];
  customHeaders?: Record<string, string>;
  settings?: Record<string, unknown>;
}

export interface Connector {
  id: ConnectorId;
  name: string;
  type: ConnectorType;
  version: string;
  status: ConnectorStatus;
  health: ConnectorHealth;
  configuration: ConnectorConfiguration;
  scopes: ConnectorScope[];
  credentialRef?: ConnectorCredentialRef;
  permissions: ConnectorPermission[];
  capabilities: ConnectorCapability[];
  permissionVersion: number;
  createdAt: string;
  updatedAt: string;
}

export interface ConnectorProvenance {
  connectorId: ConnectorId;
  permissionVersion: number;
  timestamp: string;
  actor: string;
}

export interface ConnectorLifecycleEvent {
  eventId: string;
  connectorId: ConnectorId;
  timestamp: string;
  actor: string;
  previousState: ConnectorStatus;
  newState: ConnectorStatus;
  reason: string;
  permissionVersion: number;
  provenance: ConnectorProvenance;
}

export interface ConnectorError {
  code: string;
  message: string;
  category: 'AUTH' | 'PERMISSION' | 'HEALTH' | 'LIFECYCLE' | 'NETWORK' | 'VALIDATION';
  details?: Record<string, unknown>;
}

/**
 * Explicit grant of a capability to a specific AI Agent.
 * Enforces DEFAULT DENY.
 */
export interface AgentCapabilityGrant {
  grantId: string;
  agentId: string;
  connectorId: ConnectorId;
  capabilityId: string;
  scope: ConnectorScope;
  riskLimit: ActionRiskLevel;
  expiresAt?: string;
  grantStatus: 'ACTIVE' | 'REVOKED' | 'EXPIRED';
  grantedAt: string;
  grantedBy: string;
}

/**
 * Explicit grant of a capability to a long-horizon Mission.
 * Enforces DEFAULT DENY and mission lifecycle expiration.
 */
export interface MissionCapabilityGrant {
  grantId: string;
  missionId: string;
  connectorId: ConnectorId;
  capabilityId: string;
  scope: ConnectorScope;
  riskLimit: ActionRiskLevel;
  expiresAt?: string;
  grantStatus: 'ACTIVE' | 'REVOKED' | 'EXPIRED';
  grantedAt: string;
  grantedBy: string;
}

export interface ConnectorDiscoveryDefinition {
  connectorType: ConnectorType;
  displayName: string;
  description: string;
  version: string;
  supportedCapabilities: string[];
  authenticationModes: CredentialType[];
  requiredPermissions: string[];
  configurationRequirements: Record<string, string>;
}
