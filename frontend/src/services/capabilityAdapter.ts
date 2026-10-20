/**
 * AryaOS V1 — Stage 15: Capability Adapter & Reference Mock Adapters
 *
 * Defines the CapabilityAdapter interface isolating core Action Bus from
 * external service implementation details.
 * Provides deterministic reference mock adapters for testing without live credentials.
 */

import { ActionRequest } from '../types/actionBus';

export interface CapabilityAdapter {
  canExecute(request: ActionRequest): boolean;
  validate(request: ActionRequest): { valid: boolean; errors: string[] };
  execute(request: ActionRequest): Promise<unknown>;
  cancel(actionId: string): boolean;
  healthCheck(): Promise<'ONLINE' | 'DEGRADED' | 'OFFLINE'>;
}

export class MockFileAdapter implements CapabilityAdapter {
  private fileSystem: Map<string, string> = new Map([
    ['/workspace/README.md', '# AryaOS Project Repository\nVerified stage baseline.'],
    ['/workspace/config.json', '{"status": "ONLINE", "version": "1.0.0"}'],
    ['/data/sample.txt', 'Empirical dataset records.'],
  ]);

  public canExecute(request: ActionRequest): boolean {
    return request.capabilityId.startsWith('filesystem.');
  }

  public validate(request: ActionRequest): { valid: boolean; errors: string[] } {
    const errors: string[] = [];
    const path = request.parameters.path as string;
    if (!path) errors.push('Parameter "path" is required');
    if (path && (path.includes('../') || path.includes('..\\'))) {
      errors.push('Path traversal attempt detected');
    }
    return { valid: errors.length === 0, errors };
  }

  public async execute(request: ActionRequest): Promise<unknown> {
    const path = request.parameters.path as string;
    if (request.operation === 'read_file') {
      const content = this.fileSystem.get(path);
      if (content === undefined) {
        throw new Error(`File not found: ${path}`);
      }
      return { path, content, sizeBytes: content.length, readAt: new Date().toISOString() };
    } else if (request.operation === 'write_file') {
      const content = (request.parameters.content as string) || '';
      this.fileSystem.set(path, content);
      return { path, bytesWritten: content.length, writtenAt: new Date().toISOString() };
    } else if (request.operation === 'delete_file') {
      const deleted = this.fileSystem.delete(path);
      return { path, deleted };
    }
    throw new Error(`Unsupported filesystem operation: ${request.operation}`);
  }

  public cancel(_actionId: string): boolean {
    return true;
  }

  public async healthCheck(): Promise<'ONLINE' | 'DEGRADED' | 'OFFLINE'> {
    return 'ONLINE';
  }
}

export class MockWebAdapter implements CapabilityAdapter {
  public canExecute(request: ActionRequest): boolean {
    return request.capabilityId === 'web.search';
  }

  public validate(request: ActionRequest): { valid: boolean; errors: string[] } {
    const errors: string[] = [];
    if (!request.parameters.query) errors.push('Parameter "query" is required');
    return { valid: errors.length === 0, errors };
  }

  public async execute(request: ActionRequest): Promise<unknown> {
    const query = request.parameters.query as string;
    return {
      query,
      results: [
        {
          title: `Verified Result for "${query}"`,
          url: `https://aryaos.internal/search?q=${encodeURIComponent(query)}`,
          snippet: `Empirical observation matching query keywords "${query}".`,
        },
      ],
      totalResults: 1,
      searchedAt: new Date().toISOString(),
    };
  }

  public cancel(_actionId: string): boolean {
    return true;
  }

  public async healthCheck(): Promise<'ONLINE' | 'DEGRADED' | 'OFFLINE'> {
    return 'ONLINE';
  }
}

export class MockGitHubAdapter implements CapabilityAdapter {
  private issues: Map<string, Array<{ number: number; title: string; body: string; labels: string[] }>> = new Map([
    [
      'aryaos/core',
      [
        { number: 101, title: 'Memory Environment Anchor', body: 'GLB verification tracking', labels: ['spatial'] },
      ],
    ],
  ]);

  public canExecute(request: ActionRequest): boolean {
    return request.capabilityId.startsWith('github.');
  }

  public validate(request: ActionRequest): { valid: boolean; errors: string[] } {
    const errors: string[] = [];
    const repo = request.parameters.repository as string;
    if (!repo) errors.push('Parameter "repository" is required');
    if (repo && !repo.includes('/')) errors.push('Repository must be formatted as "owner/repo"');
    return { valid: errors.length === 0, errors };
  }

  public async execute(request: ActionRequest): Promise<unknown> {
    const repo = request.parameters.repository as string;
    if (request.operation === 'get_issue') {
      const issueNum = Number(request.parameters.issueNumber);
      const list = this.issues.get(repo) || [];
      const found = list.find((i) => i.number === issueNum);
      if (!found) throw new Error(`Issue #${issueNum} not found in ${repo}`);
      return { repository: repo, ...found };
    } else if (request.operation === 'create_issue') {
      const title = request.parameters.title as string;
      const body = (request.parameters.body as string) || '';
      const labels = (request.parameters.labels as string[]) || [];
      const list = this.issues.get(repo) || [];
      const newIssueNumber = 100 + list.length + 1;
      const newIssue = { number: newIssueNumber, title, body, labels };
      list.push(newIssue);
      this.issues.set(repo, list);
      return {
        repository: repo,
        issueNumber: newIssueNumber,
        number: newIssueNumber,
        url: `https://github.com/${repo}/issues/${newIssueNumber}`,
        createdAt: new Date().toISOString(),
      };
    }
    throw new Error(`Unsupported GitHub operation: ${request.operation}`);
  }

  public cancel(_actionId: string): boolean {
    return true;
  }

  public async healthCheck(): Promise<'ONLINE' | 'DEGRADED' | 'OFFLINE'> {
    return 'ONLINE';
  }

  public getIssueDirect(repo: string, title: string): { number: number; title: string } | null {
    const list = this.issues.get(repo) || [];
    return list.find((i) => i.title === title) || null;
  }
}

export class MockNotificationAdapter implements CapabilityAdapter {
  private sentMessages: Array<{ channel: string; message: string; timestamp: string }> = [];

  public canExecute(request: ActionRequest): boolean {
    return request.capabilityId === 'notification.send';
  }

  public validate(request: ActionRequest): { valid: boolean; errors: string[] } {
    const errors: string[] = [];
    if (!request.parameters.channel) errors.push('Parameter "channel" is required');
    if (!request.parameters.message) errors.push('Parameter "message" is required');
    return { valid: errors.length === 0, errors };
  }

  public async execute(request: ActionRequest): Promise<unknown> {
    const channel = request.parameters.channel as string;
    const message = request.parameters.message as string;
    const entry = { channel, message, timestamp: new Date().toISOString() };
    this.sentMessages.push(entry);
    return { status: 'DISPATCHED', channel, timestamp: entry.timestamp };
  }

  public cancel(_actionId: string): boolean {
    return true;
  }

  public async healthCheck(): Promise<'ONLINE' | 'DEGRADED' | 'OFFLINE'> {
    return 'ONLINE';
  }

  public getSentMessages(): Array<{ channel: string; message: string; timestamp: string }> {
    return [...this.sentMessages];
  }
}

export class AdapterRegistry {
  private adapters: Map<string, CapabilityAdapter> = new Map();

  constructor() {
    this.registerDefaults();
  }

  public registerAdapter(capabilityId: string, adapter: CapabilityAdapter): void {
    this.adapters.set(capabilityId, adapter);
  }

  public getAdapter(capabilityId: string): CapabilityAdapter | null {
    if (this.adapters.has(capabilityId)) {
      return this.adapters.get(capabilityId)!;
    }
    // Match prefix-based adapters (e.g. filesystem.*, github.*)
    for (const [key, adapter] of this.adapters.entries()) {
      if (key.endsWith('*') && capabilityId.startsWith(key.slice(0, -1))) {
        return adapter;
      }
    }
    return null;
  }

  private registerDefaults(): void {
    const fileAdapter = new MockFileAdapter();
    this.registerAdapter('filesystem.read', fileAdapter);
    this.registerAdapter('filesystem.write', fileAdapter);

    const webAdapter = new MockWebAdapter();
    this.registerAdapter('web.search', webAdapter);

    const githubAdapter = new MockGitHubAdapter();
    this.registerAdapter('github.read_issue', githubAdapter);
    this.registerAdapter('github.create_issue', githubAdapter);
    this.registerAdapter('github.issue_read', githubAdapter);
    this.registerAdapter('github.issue_write', githubAdapter);

    const notifAdapter = new MockNotificationAdapter();
    this.registerAdapter('notification.send', notifAdapter);
  }
}

export const adapterRegistry = new AdapterRegistry();
