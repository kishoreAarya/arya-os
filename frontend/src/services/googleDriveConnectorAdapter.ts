/**
 * AryaOS V1 — Stage 17: Google Drive Real Connector Adapter
 *
 * Implements Stage 15 CapabilityAdapter interface for Google Drive.
 * Scoped strictly to read-only operations (list_files, read_file).
 *
 * Invariant: Never retains raw credentials. Normalizes errors and rate limits.
 */

import { CapabilityAdapter } from './capabilityAdapter';
import { ActionRequest } from '../types/actionBus';
import { connectorTransportRegistry } from './connectorTransportRegistry';
import { credentialResolver } from './credentialResolver';
import { connectorRegistry } from './connectorRegistry';

export class GoogleDriveConnectorAdapter implements CapabilityAdapter {
  private readonly defaultConnectorId = 'connector_google_drive';
  private readonly allowedHost = 'www.googleapis.com';

  public canExecute(request: ActionRequest): boolean {
    return (
      request.capabilityId === 'google_drive.list_files' ||
      request.capabilityId === 'google_drive.read_file'
    );
  }

  public validate(request: ActionRequest): { valid: boolean; errors: string[] } {
    const errors: string[] = [];
    if (request.operation === 'read_file' && !request.parameters.fileId) {
      errors.push('Parameter "fileId" is required for read_file');
    }
    return { valid: errors.length === 0, errors };
  }

  public async execute(request: ActionRequest): Promise<unknown> {
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
    const transport = connectorTransportRegistry.getTransport('GOOGLE_DRIVE');
    let endpoint = `https://${this.allowedHost}/drive/v3/files`;
    let method: 'GET' | 'POST' = 'GET';

    if (request.operation === 'read_file') {
      endpoint = `${endpoint}/${request.parameters.fileId}`;
    }

    try {
      const response = await transport.execute({
        endpoint,
        method,
        headers: {
          ...ephemeralCred.headers,
          'Accept': 'application/json',
        },
        context: {
          connectorId: this.defaultConnectorId,
          connectorType: 'GOOGLE_DRIVE',
          actionId: request.actionId,
          idempotencyKey: request.idempotencyKey,
        },
      });

      return response.data;
    } catch (err: any) {
      const sanitized = credentialResolver.sanitizeError(err);
      if (err.statusCode === 429 || err.code === 'RATE_LIMITED') {
        (sanitized as any).statusCode = 429;
        (sanitized as any).retryAfterMs = err.retryAfterMs || 60000;
        (sanitized as any).isRetryable = true;
      }
      throw sanitized;
    } finally {
      ephemeralCred = { headers: {} };
    }
  }

  public cancel(_actionId: string): boolean {
    return true;
  }

  public async healthCheck(): Promise<'ONLINE' | 'DEGRADED' | 'OFFLINE'> {
    const transport = connectorTransportRegistry.getTransport('GOOGLE_DRIVE');
    const health = await transport.checkHealth({
      connectorId: this.defaultConnectorId,
      connectorType: 'GOOGLE_DRIVE',
    });
    return health.status;
  }
}

export const googleDriveConnectorAdapter = new GoogleDriveConnectorAdapter();
