/**
 * AryaOS V1 — Stage 17: Connector Transport Registry & Mock Transport Implementation
 *
 * Manages active transport instances mapped by connector type or ID.
 * Provides deterministic mock transport capabilities for offline testing.
 *
 * SECURITY INVARIANT:
 * Transports strictly execute pre-authorized requests.
 * Transports never perform authorization logic.
 */

import {
  ConnectorTransport,
  ConnectorRequest,
  ConnectorResponse,
  ConnectorTransportContext,
  ConnectorTransportHealth,
} from '../types/connectorTransport';
import { ConnectorType } from '../types/connectorFabric';

/**
 * Deterministic Mock Transport for Offline Testing.
 * Simulates GitHub, Google Drive, and standard HTTP interactions.
 */
export class MockConnectorTransport implements ConnectorTransport {
  private networkOnline = true;
  private simulatedRateLimit: { remaining: number; resetMs: number } | null = null;
  private latencyMs = 2;

  // In-memory test state for GitHub issues
  private githubIssues: Map<string, Array<{ number: number; title: string; body: string; state: string }>> = new Map([
    [
      'aryaos/core',
      [
        { number: 101, title: 'Memory Environment Anchor', body: 'GLB verification tracking', state: 'open' },
        { number: 102, title: 'Action Bus Routing', body: 'Capability routing audit', state: 'open' },
      ],
    ],
  ]);

  // In-memory test state for Google Drive files
  private driveFiles: Map<string, Array<{ id: string; name: string; mimeType: string; content?: string }>> = new Map([
    [
      'root',
      [
        { id: 'file_doc_01', name: 'MissionPlan.md', mimeType: 'text/markdown', content: '# Mission Alpha Execution Plan' },
        { id: 'file_spec_02', name: 'ArchitectureSpec.pdf', mimeType: 'application/pdf', content: 'PDF Binary Content' },
      ],
    ],
  ]);

  public setNetworkOnline(online: boolean): void {
    this.networkOnline = online;
  }

  public setSimulatedRateLimit(limit: { remaining: number; resetMs: number } | null): void {
    this.simulatedRateLimit = limit;
  }

  public async execute<T = unknown>(request: ConnectorRequest): Promise<ConnectorResponse<T>> {
    if (!this.networkOnline) {
      const err: any = new Error('Network transport error: Host is unreachable (NETWORK_UNAVAILABLE).');
      err.code = 'NETWORK_UNAVAILABLE';
      err.isRetryable = true;
      throw err;
    }

    if (this.simulatedRateLimit && this.simulatedRateLimit.remaining <= 0) {
      const err: any = new Error(`API rate limit exceeded for ${request.endpoint}. Retry after ${this.simulatedRateLimit.resetMs}ms`);
      err.code = 'RATE_LIMITED';
      err.statusCode = 429;
      err.retryAfterMs = this.simulatedRateLimit.resetMs;
      err.isRetryable = true;
      throw err;
    }

    // 1. GitHub Simulation
    if (request.context.connectorType === 'GITHUB') {
      return this.handleGitHubRequest<T>(request);
    }

    // 2. Google Drive Simulation
    if (request.context.connectorType === 'GOOGLE_DRIVE') {
      return this.handleGoogleDriveRequest<T>(request);
    }

    // Default mock response
    return {
      statusCode: 200,
      headers: { 'content-type': 'application/json' },
      data: { status: 'OK', echo: request.body } as unknown as T,
      durationMs: this.latencyMs,
    };
  }

  private handleGitHubRequest<T>(request: ConnectorRequest): ConnectorResponse<T> {
    const endpoint = request.endpoint;

    // GET /repos/:owner/:repo/issues/:number
    const issueMatch = endpoint.match(/\/repos\/([^/]+)\/([^/]+)\/issues\/(\d+)/);
    if (issueMatch && request.method === 'GET') {
      const repo = `${issueMatch[1]}/${issueMatch[2]}`;
      const issueNum = parseInt(issueMatch[3], 10);
      const issues = this.githubIssues.get(repo) || [];
      const issue = issues.find((i) => i.number === issueNum);
      if (!issue) {
        const err: any = new Error(`GitHub Issue #${issueNum} not found in ${repo}`);
        err.code = 'NOT_FOUND';
        err.statusCode = 404;
        err.isRetryable = false;
        throw err;
      }
      return {
        statusCode: 200,
        headers: { 'content-type': 'application/json' },
        data: issue as unknown as T,
        durationMs: this.latencyMs,
      };
    }

    // POST /repos/:owner/:repo/issues
    const createMatch = endpoint.match(/\/repos\/([^/]+)\/([^/]+)\/issues$/);
    if (createMatch && request.method === 'POST') {
      const repo = `${createMatch[1]}/${createMatch[2]}`;
      const body = (request.body as any) || {};
      const issues = this.githubIssues.get(repo) || [];
      const newNumber = 200 + issues.length + 1;
      const created = {
        number: newNumber,
        issueNumber: newNumber,
        title: body.title || 'Untitled Issue',
        body: body.body || '',
        state: 'open',
      };
      issues.push(created);
      this.githubIssues.set(repo, issues);

      return {
        statusCode: 201,
        headers: { 'content-type': 'application/json' },
        data: created as unknown as T,
        durationMs: this.latencyMs,
      };
    }

    throw new Error(`Mock GitHub transport unhandled endpoint: ${request.method} ${endpoint}`);
  }

  private handleGoogleDriveRequest<T>(request: ConnectorRequest): ConnectorResponse<T> {
    const endpoint = request.endpoint;

    // GET /drive/v3/files
    if (endpoint.includes('/drive/v3/files') && request.method === 'GET' && !endpoint.includes('/drive/v3/files/')) {
      const files = this.driveFiles.get('root') || [];
      return {
        statusCode: 200,
        headers: { 'content-type': 'application/json' },
        data: { files, total: files.length } as unknown as T,
        durationMs: this.latencyMs,
      };
    }

    // GET /drive/v3/files/:id
    const fileMatch = endpoint.match(/\/drive\/v3\/files\/([^/?]+)/);
    if (fileMatch && request.method === 'GET') {
      const fileId = fileMatch[1];
      const files = this.driveFiles.get('root') || [];
      const found = files.find((f) => f.id === fileId);
      if (!found) {
        const err: any = new Error(`Google Drive File '${fileId}' not found.`);
        err.code = 'NOT_FOUND';
        err.statusCode = 404;
        err.isRetryable = false;
        throw err;
      }
      return {
        statusCode: 200,
        headers: { 'content-type': 'application/json' },
        data: found as unknown as T,
        durationMs: this.latencyMs,
      };
    }

    throw new Error(`Mock Google Drive transport unhandled endpoint: ${request.method} ${endpoint}`);
  }

  public async checkHealth(context: ConnectorTransportContext): Promise<ConnectorTransportHealth> {
    if (!this.networkOnline) {
      return {
        status: 'OFFLINE',
        lastChecked: new Date().toISOString(),
        details: { reason: 'Network host unreachable' },
      };
    }
    return {
      status: 'ONLINE',
      latencyMs: this.latencyMs,
      lastChecked: new Date().toISOString(),
    };
  }
}

export class ConnectorTransportRegistry {
  private transports: Map<ConnectorType, ConnectorTransport> = new Map();
  private mockTransport: MockConnectorTransport;

  constructor() {
    this.mockTransport = new MockConnectorTransport();
    // Default all connector types to mock transport for safe offline execution
    this.transports.set('GITHUB', this.mockTransport);
    this.transports.set('GOOGLE_DRIVE', this.mockTransport);
    this.transports.set('FILESYSTEM', this.mockTransport);
    this.transports.set('WEB', this.mockTransport);
    this.transports.set('CUSTOM', this.mockTransport);
  }

  public registerTransport(type: ConnectorType, transport: ConnectorTransport): void {
    this.transports.set(type, transport);
  }

  public getTransport(type: ConnectorType): ConnectorTransport {
    const transport = this.transports.get(type);
    if (!transport) {
      return this.mockTransport;
    }
    return transport;
  }

  public getMockTransport(): MockConnectorTransport {
    return this.mockTransport;
  }
}

export const connectorTransportRegistry = new ConnectorTransportRegistry();
