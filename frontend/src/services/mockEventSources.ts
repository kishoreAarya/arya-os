/**
 * AryaOS V1 — Stage 18: Offline Deterministic Test Doubles
 *
 * Provides mock webhook sources for GitHub and Google Drive to simulate
 * ingress, signatures, timestamp drifts, and malformed payloads without
 * requiring real external network connections.
 */

import { ExternalEventEnvelope } from '../types/externalEvent';

export class MockGitHubWebhookSource {
  public createIssueOpenedEnvelope(params: {
    connectorId?: string;
    deliveryId?: string;
    repository?: string;
    issueNumber?: number;
    title?: string;
    signature?: string;
    timestamp?: string;
    rawBodyOverride?: string;
  }): ExternalEventEnvelope {
    const deliveryId = params.deliveryId || `gh_del_${Date.now()}_${Math.random().toString(36).slice(2, 6)}`;
    const repository = params.repository || 'aryaos/core';
    const issueNumber = params.issueNumber !== undefined ? params.issueNumber : 101;
    const title = params.title || 'Inbound Issue Test';

    const payload = {
      action: 'opened',
      repository,
      issueNumber,
      title,
      schemaVersion: '1.0.0',
      occurredAt: params.timestamp || new Date().toISOString(),
    };

    const rawBody = params.rawBodyOverride !== undefined ? params.rawBodyOverride : JSON.stringify(payload);
    const signature = params.signature !== undefined ? params.signature : 'sha256=mock_valid_signature_hash_123';

    return {
      rawBody,
      headers: {
        'x-github-delivery': deliveryId,
        'x-github-event': 'issue.created',
        'x-hub-signature-256': signature,
        'x-github-delivery-timestamp': params.timestamp || new Date().toISOString(),
        'content-type': 'application/json',
      },
      ingressTimestamp: new Date().toISOString(),
      connectorId: params.connectorId || 'connector_github',
    };
  }

  public createIssueClosedEnvelope(params: {
    connectorId?: string;
    deliveryId?: string;
    repository?: string;
    issueNumber?: number;
    signature?: string;
  }): ExternalEventEnvelope {
    const deliveryId = params.deliveryId || `gh_del_close_${Date.now()}`;
    const payload = {
      action: 'closed',
      repository: params.repository || 'aryaos/core',
      issueNumber: params.issueNumber || 101,
      schemaVersion: '1.0.0',
      occurredAt: new Date().toISOString(),
    };

    return {
      rawBody: JSON.stringify(payload),
      headers: {
        'x-github-delivery': deliveryId,
        'x-github-event': 'issue.closed',
        'x-hub-signature-256': params.signature || 'sha256=mock_valid_signature_hash_123',
        'content-type': 'application/json',
      },
      ingressTimestamp: new Date().toISOString(),
      connectorId: params.connectorId || 'connector_github',
    };
  }
}

export class MockGoogleDriveEventSource {
  public createFileCreatedEnvelope(params: {
    connectorId?: string;
    channelId?: string;
    fileId?: string;
    fileName?: string;
    path?: string;
    signature?: string;
    timestamp?: string;
  }): ExternalEventEnvelope {
    const channelId = params.channelId || `gdrive_chan_${Date.now()}`;
    const payload = {
      fileId: params.fileId || 'file_drive_test_101',
      fileName: params.fileName || 'architecture_manifest.json',
      path: params.path || '/drive/root/architecture_manifest.json',
      schemaVersion: '1.0.0',
      occurredAt: params.timestamp || new Date().toISOString(),
    };

    return {
      rawBody: JSON.stringify(payload),
      headers: {
        'x-goog-channel-id': channelId,
        'x-goog-event': 'file.created',
        'x-goog-channel-token': params.signature || 'mock_valid_channel_token_xyz',
        'x-goog-message-timestamp': params.timestamp || new Date().toISOString(),
        'content-type': 'application/json',
      },
      ingressTimestamp: new Date().toISOString(),
      connectorId: params.connectorId || 'connector_google_drive',
    };
  }

  public createFileDeletedEnvelope(params: {
    connectorId?: string;
    fileId?: string;
    signature?: string;
  }): ExternalEventEnvelope {
    const payload = {
      fileId: params.fileId || 'file_drive_deleted_01',
      path: '/drive/root/stale.json',
      schemaVersion: '1.0.0',
      occurredAt: new Date().toISOString(),
    };

    return {
      rawBody: JSON.stringify(payload),
      headers: {
        'x-goog-channel-id': `gdrive_chan_del_${Date.now()}`,
        'x-goog-event': 'file.deleted',
        'x-goog-channel-token': params.signature || 'mock_valid_channel_token_xyz',
        'content-type': 'application/json',
      },
      ingressTimestamp: new Date().toISOString(),
      connectorId: params.connectorId || 'connector_google_drive',
    };
  }
}

export const mockGitHubWebhookSource = new MockGitHubWebhookSource();
export const mockGoogleDriveEventSource = new MockGoogleDriveEventSource();
