/**
 * AryaOS V1 — Stage 15: Capability Registry
 *
 * Central registry for all external system capabilities.
 * Enforces provider-neutral schemas, risk levels, required permissions,
 * and sandbox configurations.
 */

import {
  ActionCapability,
  ActionCapabilityType,
  ActionPermission,
  ActionRiskLevel,
} from '../types/actionBus';

export class CapabilityRegistry {
  private capabilities: Map<string, ActionCapability> = new Map();

  constructor() {
    this.registerDefaultCapabilities();
  }

  /**
   * Registers or updates an external capability in the registry.
   */
  public registerCapability(capability: ActionCapability): void {
    if (!capability.capabilityId || !capability.type) {
      throw new Error('Invalid capability: capabilityId and type are required');
    }
    this.capabilities.set(capability.capabilityId, capability);
  }

  /**
   * Retrieves a capability by its unique ID.
   */
  public getCapability(capabilityId: string): ActionCapability | null {
    return this.capabilities.get(capabilityId) || null;
  }

  /**
   * Lists registered capabilities with optional filtering.
   */
  public listCapabilities(filter?: {
    type?: ActionCapabilityType;
    availability?: 'ONLINE' | 'DEGRADED' | 'OFFLINE';
    riskLevel?: ActionRiskLevel;
  }): ActionCapability[] {
    let list = Array.from(this.capabilities.values());
    if (filter?.type) list = list.filter((c) => c.type === filter.type);
    if (filter?.availability) list = list.filter((c) => c.availability === filter.availability);
    if (filter?.riskLevel) list = list.filter((c) => c.riskLevel === filter.riskLevel);
    return list;
  }

  /**
   * Updates capability availability.
   */
  public setAvailability(capabilityId: string, availability: 'ONLINE' | 'DEGRADED' | 'OFFLINE'): void {
    const cap = this.capabilities.get(capabilityId);
    if (!cap) {
      throw new Error(`Capability not found: ${capabilityId}`);
    }
    cap.availability = availability;
  }

  /**
   * Validates parameters against the capability inputSchema.
   */
  public validateParameters(
    capabilityId: string,
    parameters: Record<string, unknown>
  ): { valid: boolean; errors: string[] } {
    const cap = this.capabilities.get(capabilityId);
    if (!cap) {
      return { valid: false, errors: [`Capability '${capabilityId}' is not registered`] };
    }

    const errors: string[] = [];
    const schema = cap.inputSchema;

    // Check required fields
    if (schema.required) {
      for (const reqField of schema.required) {
        if (parameters[reqField] === undefined || parameters[reqField] === null || parameters[reqField] === '') {
          errors.push(`Missing required parameter: '${reqField}'`);
        }
      }
    }

    // Check property types
    if (schema.properties) {
      for (const [propName, propDef] of Object.entries(schema.properties)) {
        const val = parameters[propName];
        if (val !== undefined && val !== null) {
          if (propDef.type === 'string' && typeof val !== 'string') {
            errors.push(`Parameter '${propName}' must be a string, got ${typeof val}`);
          } else if (propDef.type === 'number' && typeof val !== 'number') {
            errors.push(`Parameter '${propName}' must be a number, got ${typeof val}`);
          } else if (propDef.type === 'boolean' && typeof val !== 'boolean') {
            errors.push(`Parameter '${propName}' must be a boolean, got ${typeof val}`);
          } else if (propDef.type === 'array' && !Array.isArray(val)) {
            errors.push(`Parameter '${propName}' must be an array`);
          } else if (propDef.type === 'object' && (typeof val !== 'object' || Array.isArray(val))) {
            errors.push(`Parameter '${propName}' must be an object`);
          }

          if (propDef.enum && typeof val === 'string' && !propDef.enum.includes(val)) {
            errors.push(`Parameter '${propName}' must be one of: ${propDef.enum.join(', ')}`);
          }
        }
      }
    }

    return { valid: errors.length === 0, errors };
  }

  /**
   * Clears all custom capabilities and resets defaults.
   */
  public reset(): void {
    this.capabilities.clear();
    this.registerDefaultCapabilities();
  }

  /**
   * Pre-registers standard neutral capabilities.
   */
  private registerDefaultCapabilities(): void {
    // 1. Filesystem Read
    this.registerCapability({
      capabilityId: 'filesystem.read',
      name: 'Filesystem Reader',
      type: 'FILE',
      description: 'Reads local filesystem content within sandboxed paths',
      version: '1.0.0',
      riskLevel: 'LOW',
      requiredPermissions: ['FILES_READ'],
      supportedOperations: ['read_file', 'list_directory'],
      inputSchema: {
        type: 'object',
        required: ['path'],
        properties: {
          path: { type: 'string', description: 'Relative sandboxed path' },
          encoding: { type: 'string', enum: ['utf-8', 'binary'] },
        },
      },
      timeoutMs: 3000,
      retryPolicy: { maxRetries: 2, retryableCategories: ['TIMEOUT', 'TRANSIENT'], backoffMs: 200 },
      idempotencyPolicy: { isIdempotent: true, requiresIdempotencyKey: false },
      availability: 'ONLINE',
      sandboxConfig: {
        allowedPaths: ['/workspace', '/data', '/tmp/sandbox'],
        maxPayloadBytes: 10485760, // 10MB
      },
    });

    // 2. Filesystem Write
    this.registerCapability({
      capabilityId: 'filesystem.write',
      name: 'Filesystem Writer',
      type: 'FILE',
      description: 'Writes local filesystem content within sandboxed paths',
      version: '1.0.0',
      riskLevel: 'HIGH',
      requiredPermissions: ['FILES_WRITE'],
      supportedOperations: ['write_file', 'delete_file'],
      inputSchema: {
        type: 'object',
        required: ['path'],
        properties: {
          path: { type: 'string', description: 'Relative sandboxed target path' },
          content: { type: 'string', description: 'File payload' },
          overwrite: { type: 'boolean', description: 'Allow overwrite' },
        },
      },
      timeoutMs: 5000,
      retryPolicy: { maxRetries: 1, retryableCategories: ['TIMEOUT'], backoffMs: 500 },
      idempotencyPolicy: { isIdempotent: true, requiresIdempotencyKey: true },
      availability: 'ONLINE',
      sandboxConfig: {
        allowedPaths: ['/workspace', '/data/output', '/tmp/sandbox'],
        maxPayloadBytes: 10485760,
      },
    });

    // 3. Web Search
    this.registerCapability({
      capabilityId: 'web.search',
      name: 'External Web Search',
      type: 'SEARCH',
      description: 'Queries search indexing engines for public web content',
      version: '1.0.0',
      riskLevel: 'MEDIUM',
      requiredPermissions: ['WEB_SEARCH'],
      supportedOperations: ['query'],
      inputSchema: {
        type: 'object',
        required: ['query'],
        properties: {
          query: { type: 'string', description: 'Search keywords' },
          maxResults: { type: 'number', description: 'Number of results' },
        },
      },
      timeoutMs: 8000,
      retryPolicy: { maxRetries: 3, retryableCategories: ['RATE_LIMIT', 'TIMEOUT', 'TRANSIENT'], backoffMs: 1000 },
      idempotencyPolicy: { isIdempotent: true, requiresIdempotencyKey: false },
      availability: 'ONLINE',
    });

    // 4. External HTTP
    this.registerCapability({
      capabilityId: 'external.http',
      name: 'HTTP Endpoint Request',
      type: 'HTTP',
      description: 'Performs external REST HTTP calls to declared allowlisted domains',
      version: '1.0.0',
      riskLevel: 'MEDIUM',
      requiredPermissions: ['EXTERNAL_HTTP'],
      supportedOperations: ['get', 'post'],
      inputSchema: {
        type: 'object',
        required: ['url', 'method'],
        properties: {
          url: { type: 'string', description: 'Destination HTTP URL' },
          method: { type: 'string', enum: ['GET', 'POST', 'PUT', 'DELETE'] },
          headers: { type: 'object' },
          body: { type: 'string' },
        },
      },
      timeoutMs: 10000,
      retryPolicy: { maxRetries: 2, retryableCategories: ['TIMEOUT', 'RATE_LIMIT'], backoffMs: 500 },
      idempotencyPolicy: { isIdempotent: false, requiresIdempotencyKey: true },
      availability: 'ONLINE',
      sandboxConfig: {
        allowedDomains: ['api.github.com', 'api.weather.gov', 'api.aryaos.local'],
        maxPayloadBytes: 5242880,
      },
    });

    // 5. GitHub Read Issue
    this.registerCapability({
      capabilityId: 'github.read_issue',
      name: 'GitHub Issue Reader',
      type: 'GITHUB',
      description: 'Reads issue details from authorized repositories',
      version: '1.0.0',
      riskLevel: 'LOW',
      requiredPermissions: ['GITHUB_READ'],
      supportedOperations: ['get_issue', 'list_issues'],
      inputSchema: {
        type: 'object',
        required: ['repository'],
        properties: {
          repository: { type: 'string', description: 'Owner/repo format' },
          issueNumber: { type: 'number' },
        },
      },
      timeoutMs: 5000,
      retryPolicy: { maxRetries: 2, retryableCategories: ['TIMEOUT', 'RATE_LIMIT'], backoffMs: 500 },
      idempotencyPolicy: { isIdempotent: true, requiresIdempotencyKey: false },
      availability: 'ONLINE',
      sandboxConfig: {
        allowedRepositories: ['aryaos/core', 'aryaos/frontend', 'aryaos/sandbox'],
      },
    });

    // 5b. GitHub Issue Read (Alias/Connector identifier)
    this.registerCapability({
      capabilityId: 'github.issue_read',
      name: 'GitHub Issue Reader',
      type: 'GITHUB',
      description: 'Reads issue details from authorized repositories',
      version: '1.0.0',
      riskLevel: 'LOW',
      requiredPermissions: ['GITHUB_READ'],
      supportedOperations: ['get_issue', 'list_issues'],
      inputSchema: {
        type: 'object',
        required: ['repository'],
        properties: {
          repository: { type: 'string', description: 'Owner/repo format' },
          issueNumber: { type: 'number' },
        },
      },
      timeoutMs: 5000,
      retryPolicy: { maxRetries: 2, retryableCategories: ['TIMEOUT', 'RATE_LIMIT', 'TRANSIENT'], backoffMs: 500 },
      idempotencyPolicy: { isIdempotent: true, requiresIdempotencyKey: false },
      availability: 'ONLINE',
      sandboxConfig: {
        allowedRepositories: ['aryaos/core', 'aryaos/frontend', 'aryaos/sandbox'],
      },
    });

    // 6. GitHub Create Issue
    this.registerCapability({
      capabilityId: 'github.create_issue',
      name: 'GitHub Issue Creator',
      type: 'GITHUB',
      description: 'Creates a new issue in authorized repositories',
      version: '1.0.0',
      riskLevel: 'HIGH',
      requiredPermissions: ['GITHUB_WRITE'],
      supportedOperations: ['create_issue'],
      inputSchema: {
        type: 'object',
        required: ['repository', 'title', 'body'],
        properties: {
          repository: { type: 'string', description: 'Owner/repo format' },
          title: { type: 'string' },
          body: { type: 'string' },
          labels: { type: 'array' },
        },
      },
      timeoutMs: 8000,
      retryPolicy: { maxRetries: 1, retryableCategories: ['TIMEOUT'], backoffMs: 1000 },
      idempotencyPolicy: { isIdempotent: false, requiresIdempotencyKey: true },
      availability: 'ONLINE',
      sandboxConfig: {
        allowedRepositories: ['aryaos/core', 'aryaos/frontend', 'aryaos/sandbox'],
      },
    });

    // 6b. GitHub Issue Write (Alias/Connector identifier)
    this.registerCapability({
      capabilityId: 'github.issue_write',
      name: 'GitHub Issue Writer',
      type: 'GITHUB',
      description: 'Creates a new issue in authorized repositories',
      version: '1.0.0',
      riskLevel: 'HIGH',
      requiredPermissions: ['GITHUB_WRITE'],
      supportedOperations: ['create_issue'],
      inputSchema: {
        type: 'object',
        required: ['repository', 'title', 'body'],
        properties: {
          repository: { type: 'string', description: 'Owner/repo format' },
          title: { type: 'string' },
          body: { type: 'string' },
          labels: { type: 'array' },
        },
      },
      timeoutMs: 8000,
      retryPolicy: { maxRetries: 1, retryableCategories: ['TIMEOUT'], backoffMs: 1000 },
      idempotencyPolicy: { isIdempotent: false, requiresIdempotencyKey: true },
      availability: 'ONLINE',
      sandboxConfig: {
        allowedRepositories: ['aryaos/core', 'aryaos/frontend', 'aryaos/sandbox'],
      },
    });

    // 7. Notification Send
    this.registerCapability({
      capabilityId: 'notification.send',
      name: 'Notification Dispatcher',
      type: 'NOTIFICATION',
      description: 'Dispatches operational notifications to declared channels',
      version: '1.0.0',
      riskLevel: 'HIGH',
      requiredPermissions: ['NOTIFICATION_SEND'],
      supportedOperations: ['send_message'],
      inputSchema: {
        type: 'object',
        required: ['channel', 'message'],
        properties: {
          channel: { type: 'string', description: 'Destination channel' },
          message: { type: 'string', description: 'Notification message body' },
          urgency: { type: 'string', enum: ['LOW', 'NORMAL', 'URGENT'] },
        },
      },
      timeoutMs: 4000,
      retryPolicy: { maxRetries: 2, retryableCategories: ['TIMEOUT', 'TRANSIENT'], backoffMs: 300 },
      idempotencyPolicy: { isIdempotent: false, requiresIdempotencyKey: true },
      availability: 'ONLINE',
      sandboxConfig: {
        allowedChannels: ['ops-alerts', 'deployment-log', 'operator-console'],
      },
    });

    // 8. Google Drive List Files
    this.registerCapability({
      capabilityId: 'google_drive.list_files',
      name: 'Google Drive File Lister',
      type: 'CONNECTOR',
      description: 'Lists files in authorized Google Drive directories',
      version: '1.0.0',
      riskLevel: 'LOW',
      requiredPermissions: ['FILES_READ'],
      supportedOperations: ['list_files'],
      inputSchema: {
        type: 'object',
        properties: {
          pageSize: { type: 'number' },
          query: { type: 'string' },
        },
      },
      timeoutMs: 5000,
      retryPolicy: { maxRetries: 2, retryableCategories: ['TIMEOUT', 'RATE_LIMIT'], backoffMs: 500 },
      idempotencyPolicy: { isIdempotent: true, requiresIdempotencyKey: false },
      availability: 'ONLINE',
      sandboxConfig: {
        allowedPaths: ['/drive/root', '/drive/workspace'],
      },
    });

    // 9. Google Drive Read File
    this.registerCapability({
      capabilityId: 'google_drive.read_file',
      name: 'Google Drive File Reader',
      type: 'CONNECTOR',
      description: 'Reads file metadata and content from Google Drive',
      version: '1.0.0',
      riskLevel: 'LOW',
      requiredPermissions: ['FILES_READ'],
      supportedOperations: ['read_file'],
      inputSchema: {
        type: 'object',
        required: ['fileId'],
        properties: {
          fileId: { type: 'string', description: 'Google Drive file ID' },
        },
      },
      timeoutMs: 6000,
      retryPolicy: { maxRetries: 2, retryableCategories: ['TIMEOUT', 'RATE_LIMIT'], backoffMs: 500 },
      idempotencyPolicy: { isIdempotent: true, requiresIdempotencyKey: false },
      availability: 'ONLINE',
      sandboxConfig: {
        allowedPaths: ['/drive/root', '/drive/workspace'],
      },
    });
  }
}

export const capabilityRegistry = new CapabilityRegistry();
