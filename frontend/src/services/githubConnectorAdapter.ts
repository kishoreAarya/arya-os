/**
 * AryaOS V1 — Stage 17: GitHub Real Connector Adapter
 *
 * Implements Stage 15 CapabilityAdapter interface for GitHub.
 * Connects through ConnectorTransport using ephemeral credentials resolved
 * via CredentialResolver.
 *
 * Invariant: Never retains raw credentials. Normalizes rate limits and errors.
 */

import { CapabilityAdapter } from './capabilityAdapter';
import { ActionRequest } from '../types/actionBus';
import { connectorTransportRegistry } from './connectorTransportRegistry';
import { credentialResolver } from './credentialResolver';
import { connectorRegistry } from './connectorRegistry';

export class GitHubConnectorAdapter implements CapabilityAdapter {
  private readonly defaultConnectorId = 'connector_github';
  private readonly allowedHost = 'api.github.com';

  public canExecute(request: ActionRequest): boolean {
    return (
      request.capabilityId === 'github.issue_read' ||
      request.capabilityId === 'github.issue_write' ||
      request.capabilityId === 'github.read_issue' ||
      request.capabilityId === 'github.create_issue'
    );
  }

  public validate(request: ActionRequest): { valid: boolean; errors: string[] } {
    const errors: string[] = [];
    const repo = request.parameters.repository as string;
    if (!repo) {
      errors.push('Parameter "repository" is required');
    } else if (!repo.includes('/')) {
      errors.push('Repository parameter must follow "owner/repo" structure');
    }

    if (request.operation === 'get_issue' && !request.parameters.issueNumber) {
      errors.push('Parameter "issueNumber" is required for get_issue');
    }

    if (request.operation === 'create_issue' && !request.parameters.title) {
      errors.push('Parameter "title" is required for create_issue');
    }

    return { valid: errors.length === 0, errors };
  }

  public async execute(request: ActionRequest): Promise<unknown> {
    const repo = request.parameters.repository as string;
    const connector = connectorRegistry.getConnector(this.defaultConnectorId);

    // 1. Resolve Ephemeral Credential
    let ephemeralCred: { headers: Record<string, string> } = { headers: {} };
    if (connector?.credentialRef) {
      try {
        ephemeralCred = await credentialResolver.resolve(connector.credentialRef);
      } catch (err: any) {
        throw credentialResolver.sanitizeError(err);
      }
    }

    // 2. Prepare Transport Request
    const transport = connectorTransportRegistry.getTransport('GITHUB');
    let endpoint = `https://${this.allowedHost}/repos/${repo}/issues`;
    let method: 'GET' | 'POST' = 'GET';
    let body: unknown = undefined;

    if (request.operation === 'get_issue') {
      endpoint = `${endpoint}/${request.parameters.issueNumber}`;
      method = 'GET';
    } else if (request.operation === 'create_issue') {
      method = 'POST';
      body = {
        title: request.parameters.title,
        body: request.parameters.body || '',
      };
    }

    try {
      const response = await transport.execute({
        endpoint,
        method,
        headers: {
          ...ephemeralCred.headers,
          'Accept': 'application/vnd.github.v3+json',
        },
        body,
        context: {
          connectorId: this.defaultConnectorId,
          connectorType: 'GITHUB',
          actionId: request.actionId,
          idempotencyKey: request.idempotencyKey,
        },
      });

      return response.data;
    } catch (err: any) {
      // Ensure error message is sanitized of any authorization tokens
      const sanitized = credentialResolver.sanitizeError(err);
      // Map rate limit properties if present
      if (err.statusCode === 429 || err.code === 'RATE_LIMITED') {
        (sanitized as any).statusCode = 429;
        (sanitized as any).retryAfterMs = err.retryAfterMs || 60000;
        (sanitized as any).isRetryable = true;
      }
      throw sanitized;
    } finally {
      // Zero out ephemeral memory reference
      ephemeralCred = { headers: {} };
    }
  }

  public cancel(_actionId: string): boolean {
    return true;
  }

  public async healthCheck(): Promise<'ONLINE' | 'DEGRADED' | 'OFFLINE'> {
    const transport = connectorTransportRegistry.getTransport('GITHUB');
    const health = await transport.checkHealth({
      connectorId: this.defaultConnectorId,
      connectorType: 'GITHUB',
    });
    return health.status;
  }
}

export const githubConnectorAdapter = new GitHubConnectorAdapter();
