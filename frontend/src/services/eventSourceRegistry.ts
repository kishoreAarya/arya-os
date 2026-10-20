/**
 * AryaOS V1 — Stage 18: Event Source Registry
 *
 * Maps external connectors and source systems to their supported event types,
 * schemas, and validation contracts.
 * Enforces minimal safe subsets for GitHub and Google Drive.
 */

import { ExternalEventSource } from '../types/externalEvent';

export interface EventTypeDefinition {
  eventType: string;
  displayName: string;
  description: string;
  schemaVersion: string;
  requiredFields: string[];
  fieldTypes: Record<string, 'string' | 'number' | 'boolean' | 'object' | 'array'>;
  maxPayloadBytes?: number;
}

export interface EventSourceDefinition {
  sourceSystem: ExternalEventSource;
  connectorType: string;
  displayName: string;
  signatureHeaderName: string;
  timestampHeaderName?: string;
  supportedEventTypes: Map<string, EventTypeDefinition>;
}

export class EventSourceRegistry {
  private sources = new Map<ExternalEventSource, EventSourceDefinition>();

  constructor() {
    this.registerDefaults();
  }

  public registerSource(def: EventSourceDefinition): void {
    this.sources.set(def.sourceSystem, def);
  }

  public getSource(sourceSystem: ExternalEventSource): EventSourceDefinition | undefined {
    return this.sources.get(sourceSystem);
  }

  public isSourceSupported(sourceSystem: string): boolean {
    return this.sources.has(sourceSystem as ExternalEventSource);
  }

  public isEventTypeSupported(sourceSystem: ExternalEventSource, eventType: string): boolean {
    const source = this.sources.get(sourceSystem);
    if (!source) return false;
    return source.supportedEventTypes.has(eventType);
  }

  public getEventTypeDefinition(
    sourceSystem: ExternalEventSource,
    eventType: string
  ): EventTypeDefinition | undefined {
    const source = this.sources.get(sourceSystem);
    if (!source) return undefined;
    return source.supportedEventTypes.get(eventType);
  }

  public listSupportedEventTypes(sourceSystem: ExternalEventSource): string[] {
    const source = this.sources.get(sourceSystem);
    if (!source) return [];
    return Array.from(source.supportedEventTypes.keys());
  }

  public reset(): void {
    this.sources.clear();
    this.registerDefaults();
  }

  private registerDefaults(): void {
    // 1. GitHub Event Source
    const ghTypes = new Map<string, EventTypeDefinition>();

    ghTypes.set('issue.created', {
      eventType: 'issue.created',
      displayName: 'GitHub Issue Created',
      description: 'Triggered when a new issue is opened in an authorized repository',
      schemaVersion: '1.0.0',
      requiredFields: ['repository', 'issueNumber', 'title'],
      fieldTypes: {
        repository: 'string',
        issueNumber: 'number',
        title: 'string',
        body: 'string',
        action: 'string',
      },
    });

    ghTypes.set('issue.updated', {
      eventType: 'issue.updated',
      displayName: 'GitHub Issue Updated',
      description: 'Triggered when an issue is edited, commented, or updated',
      schemaVersion: '1.0.0',
      requiredFields: ['repository', 'issueNumber'],
      fieldTypes: {
        repository: 'string',
        issueNumber: 'number',
        title: 'string',
        body: 'string',
        action: 'string',
      },
    });

    ghTypes.set('issue.closed', {
      eventType: 'issue.closed',
      displayName: 'GitHub Issue Closed',
      description: 'Triggered when an issue is closed in an authorized repository',
      schemaVersion: '1.0.0',
      requiredFields: ['repository', 'issueNumber'],
      fieldTypes: {
        repository: 'string',
        issueNumber: 'number',
        action: 'string',
      },
    });

    this.registerSource({
      sourceSystem: 'GITHUB',
      connectorType: 'GITHUB',
      displayName: 'GitHub Webhooks',
      signatureHeaderName: 'x-hub-signature-256',
      timestampHeaderName: 'x-github-delivery-timestamp',
      supportedEventTypes: ghTypes,
    });

    // 2. Google Drive Event Source
    const gdriveTypes = new Map<string, EventTypeDefinition>();

    gdriveTypes.set('file.created', {
      eventType: 'file.created',
      displayName: 'Google Drive File Created',
      description: 'Triggered when a file is created in monitored Drive directories',
      schemaVersion: '1.0.0',
      requiredFields: ['fileId', 'fileName', 'path'],
      fieldTypes: {
        fileId: 'string',
        fileName: 'string',
        path: 'string',
        mimeType: 'string',
        size: 'number',
      },
    });

    gdriveTypes.set('file.updated', {
      eventType: 'file.updated',
      displayName: 'Google Drive File Updated',
      description: 'Triggered when file content or metadata is updated',
      schemaVersion: '1.0.0',
      requiredFields: ['fileId'],
      fieldTypes: {
        fileId: 'string',
        fileName: 'string',
        path: 'string',
        modifiedTime: 'string',
      },
    });

    gdriveTypes.set('file.deleted', {
      eventType: 'file.deleted',
      displayName: 'Google Drive File Deleted',
      description: 'Triggered when a file is removed from Drive',
      schemaVersion: '1.0.0',
      requiredFields: ['fileId'],
      fieldTypes: {
        fileId: 'string',
        path: 'string',
      },
    });

    this.registerSource({
      sourceSystem: 'GOOGLE_DRIVE',
      connectorType: 'GOOGLE_DRIVE',
      displayName: 'Google Drive Push Notifications',
      signatureHeaderName: 'x-goog-channel-token',
      timestampHeaderName: 'x-goog-message-timestamp',
      supportedEventTypes: gdriveTypes,
    });
  }
}

export const eventSourceRegistry = new EventSourceRegistry();
