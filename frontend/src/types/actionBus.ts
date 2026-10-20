/**
 * AryaOS V1 — Stage 15: Universal Action Bus Domain Contracts
 *
 * Single governed execution boundary for external system capabilities
 * (filesystem, web search, HTTP, GitHub, notifications, connectors).
 *
 * CRITICAL ARCHITECTURAL DISTINCTION:
 * - AI Provider / LLM Reasoning: Stage 07 executionGateway.execute()
 * - External Actions & Capabilities: Stage 15 actionBus.execute()
 * Neither boundary may bypass the other.
 */

export type ActionCapabilityType =
  | 'READ'
  | 'WRITE'
  | 'SEARCH'
  | 'HTTP'
  | 'FILE'
  | 'GITHUB'
  | 'CONNECTOR'
  | 'NOTIFICATION'
  | 'WORKFLOW'
  | 'MEDIA'
  | 'DATABASE'
  | 'CUSTOM';

export type ActionRiskLevel = 'LOW' | 'MEDIUM' | 'HIGH' | 'CRITICAL';

export type ActionExecutionStatus =
  | 'PLANNED'
  | 'AUTHORIZED'
  | 'DENIED'
  | 'READY'
  | 'EXECUTING'
  | 'SUCCEEDED'
  | 'FAILED'
  | 'TIMEOUT'
  | 'CANCELLED'
  | 'UNAVAILABLE'
  | 'REQUIRES_APPROVAL'
  | 'STATE_UNKNOWN';

export type ActionPermission =
  | 'FILES_READ'
  | 'FILES_WRITE'
  | 'WEB_SEARCH'
  | 'GITHUB_READ'
  | 'GITHUB_WRITE'
  | 'EXTERNAL_HTTP'
  | 'NOTIFICATION_SEND'
  | 'WORKFLOW_TRIGGER'
  | 'PUBLISH_CONTENT'
  | 'DATABASE_READ'
  | 'DATABASE_WRITE'
  | 'CONNECTOR_EXECUTE';

export type ActionRetryCategory =
  | 'TRANSIENT'
  | 'RATE_LIMIT'
  | 'TIMEOUT'
  | 'AUTHORIZATION'
  | 'VALIDATION'
  | 'PERMISSION'
  | 'NOT_FOUND'
  | 'CONFLICT'
  | 'PERMANENT';

export interface ActionSandboxConfig {
  allowedPaths?: string[];
  allowedDomains?: string[];
  allowedRepositories?: string[];
  allowedChannels?: string[];
  maxPayloadBytes?: number;
}

export interface ActionCapability {
  capabilityId: string;
  name: string;
  type: ActionCapabilityType;
  description: string;
  version: string;
  riskLevel: ActionRiskLevel;
  requiredPermissions: ActionPermission[];
  supportedOperations: string[];
  inputSchema: {
    type?: string;
    required?: string[];
    properties?: Record<string, { type: string; description?: string; enum?: string[] }>;
  };
  outputSchema?: Record<string, unknown>;
  timeoutMs: number;
  retryPolicy: {
    maxRetries: number;
    retryableCategories: ActionRetryCategory[];
    backoffMs: number;
  };
  idempotencyPolicy: {
    isIdempotent: boolean;
    requiresIdempotencyKey: boolean;
  };
  availability: 'ONLINE' | 'DEGRADED' | 'OFFLINE';
  sandboxConfig?: ActionSandboxConfig;
}

export interface ActionAuthorization {
  authorized: boolean;
  status: 'AUTHORIZED' | 'DENIED' | 'REQUIRES_APPROVAL';
  riskLevel: ActionRiskLevel;
  requiresHumanApproval: boolean;
  approvedBy?: string;
  reviewedAt?: string;
  reason?: string;
  grantedPermissions: ActionPermission[];
}

export interface ActionExecutionContext {
  missionId?: string;
  goalId?: string;
  actionNodeId?: string;
  decisionId?: string;
  agentId?: string;
  operatorId?: string;
  timestamp: string;
}

export interface ActionRequest {
  actionId: string;
  capabilityId: string;
  operation: string;
  parameters: Record<string, unknown>;
  idempotencyKey: string;
  context: ActionExecutionContext;
  timeoutMs?: number;
  metadata?: Record<string, unknown>;
}

export interface ActionError {
  code: string;
  message: string;
  category: ActionRetryCategory;
  retryable: boolean;
  details?: Record<string, unknown>;
}

export interface ActionProvenance {
  actionId: string;
  capabilityId: string;
  requestFingerprint: string;
  missionId?: string;
  goalId?: string;
  decisionId?: string;
  agentId?: string;
  timestamp: string;
}

export interface ActionResult {
  actionId: string;
  capabilityId: string;
  success: boolean;
  status: ActionExecutionStatus;
  data: unknown;
  metadata: Record<string, unknown>;
  error?: ActionError;
  provenance: ActionProvenance;
  durationMs: number;
}

export interface ActionAuditRecord {
  actionId: string;
  capabilityId: string;
  requestFingerprint: string;
  authorizationState: string;
  riskLevel: ActionRiskLevel;
  executionState: ActionExecutionStatus;
  startTime: string;
  endTime?: string;
  resultStatus: ActionExecutionStatus;
  errorCategory?: ActionRetryCategory;
  provenance: ActionProvenance;
}

export interface ActionPolicy {
  policyId: string;
  name: string;
  allowedCapabilities?: string[];
  deniedCapabilities?: string[];
  allowedPermissions?: ActionPermission[];
  allowedPaths?: string[];
  allowedDomains?: string[];
  allowedRepositories?: string[];
  maxPayloadBytes?: number;
  requireHumanApprovalForCritical: boolean;
  requireApprovalForHighRisk: boolean;
}
