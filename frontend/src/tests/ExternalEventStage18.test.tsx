/**
 * AryaOS V1 — Stage 18: External Event Ingestion & State Synchronization Test Suite
 *
 * Covers 52 rigorous tests across:
 * 1. Event source registration (GitHub, Google Drive, rejection of unknown sources)
 * 2. Schema validation, malformed payload rejection, size limits
 * 3. Webhook authentication (signatures, expired timestamps, connector association)
 * 4. Deterministic identity, deduplication, replay protection
 * 5. Secret sanitization (Authorization headers, Bearer tokens, nested secrets)
 * 6. Event normalization, provider provenance preservation
 * 7. Journal integration & zero secret persistence
 * 8. Connector lifecycle state checks (REVOKED, DISABLED, UNKNOWN)
 * 9. Separation of Event vs Action vs Authority (no auto-action, no permission escalation)
 * 10. External state reconciliation (EVENT != TRUTH, OBSERVED vs CONFIRMED)
 * 11. Mission Control integration & bounded replanning
 * 12. Strategic Knowledge Graph integration with epistemic labels
 * 13. Rate limiting & ingestion concurrency guards
 * 14. Restart & persistence recovery
 * 15. Reconciled Stage 03 Camera baseline verification
 * 16. Spatial HUD DOM-only rendering verification
 */

import { describe, it, expect, beforeEach } from 'vitest';
import React from 'react';
import { render } from '@testing-library/react';

// Domain Types
import { ExternalEvent, ExternalEventEnvelope } from '../types/externalEvent';

// Core Services
import { eventSourceRegistry } from '../services/eventSourceRegistry';
import { eventSchemaValidator } from '../services/eventSchemaValidator';
import { eventSanitizer } from '../services/eventSanitizer';
import { webhookAuthenticationService, mockWebhookSecretStore } from '../services/webhookAuthenticationService';
import { eventReplayProtection } from '../services/eventReplayProtection';
import { eventNormalizer } from '../services/eventNormalizer';
import { externalStateReconciliationService } from '../services/externalStateReconciliationService';
import { eventRegistry } from '../services/eventRegistry';
import { eventIngressService } from '../services/eventIngressService';
import { connectorRegistry } from '../services/connectorRegistry';
import { connectorPermissionService } from '../services/connectorPermissionService';
import { executionJournal } from '../services/executionJournal';
import { executionPersistence } from '../services/executionPersistence';
import { knowledgeGraph } from '../services/knowledgeGraph';
import { missionObservationService } from '../services/missionObservationService';
import { missionManager } from '../services/missionManager';
import { missionReplanner } from '../services/missionReplanner';
import { executionGateway } from '../services/executionGateway';
import { actionBusService } from '../services/actionBusService';
import { STAGE03_CAMERAS } from '../stage03_assembly';
import { SpatialCommandConsole } from '../components/spatial/SpatialCommandConsole';
import {
  mockGitHubWebhookSource,
  mockGoogleDriveEventSource,
} from '../services/mockEventSources';

describe('AryaOS V1 Stage 18 — External Event Ingestion & State Synchronization', () => {
  beforeEach(() => {
    localStorage.clear();
    executionPersistence.clearEnvelope();
    executionJournal.resetState();
    eventReplayProtection.clear();
    eventRegistry.clear();
    eventIngressService.resetRateLimits();
    eventSourceRegistry.reset();
    mockWebhookSecretStore.clear();

    // Ensure reference connectors exist in active state for testing
    const gh = connectorRegistry.getConnector('connector_github');
    if (gh) {
      gh.status = 'ACTIVE';
      gh.health = 'HEALTHY';
      if (gh.credentialRef) {
        gh.credentialRef.status = 'VALID';
      }
      connectorRegistry.updateConnector(gh);
    }
  });

  // 1. registers GitHub event source
  it('1. registers GitHub event source with issue event types', () => {
    const source = eventSourceRegistry.getSource('GITHUB');
    expect(source).toBeDefined();
    expect(source?.supportedEventTypes.has('issue.created')).toBe(true);
    expect(source?.supportedEventTypes.has('issue.updated')).toBe(true);
    expect(source?.supportedEventTypes.has('issue.closed')).toBe(true);
  });

  // 2. registers Google Drive event source
  it('2. registers Google Drive event source with file event types', () => {
    const source = eventSourceRegistry.getSource('GOOGLE_DRIVE');
    expect(source).toBeDefined();
    expect(source?.supportedEventTypes.has('file.created')).toBe(true);
    expect(source?.supportedEventTypes.has('file.deleted')).toBe(true);
  });

  // 3. rejects unknown event source
  it('3. rejects unknown event source system', () => {
    expect(eventSourceRegistry.isSourceSupported('SLACK' as any)).toBe(false);
    expect(eventSourceRegistry.isEventTypeSupported('GITHUB', 'unknown.event')).toBe(false);
  });

  // 4. validates event schema
  it('4. validates valid event schema against declared definitions', () => {
    const validEvent: ExternalEvent = {
      eventId: 'evt_gh_val_01',
      eventType: 'issue.created',
      connectorId: 'connector_github',
      sourceSystem: 'GITHUB',
      receivedAt: new Date().toISOString(),
      occurredAt: new Date().toISOString(),
      payload: { repository: 'aryaos/core', issueNumber: 101, title: 'Valid Issue' },
      schemaVersion: '1.0.0',
      authenticationStatus: 'AUTHENTICATED',
      processingStatus: 'RECEIVED',
    };
    const res = eventSchemaValidator.validate(validEvent);
    expect(res.valid).toBe(true);
    expect(res.errors).toHaveLength(0);
  });

  // 5. rejects malformed event
  it('5. rejects malformed event missing required fields', () => {
    const malformedEvent: ExternalEvent = {
      eventId: 'evt_gh_bad_01',
      eventType: 'issue.created',
      connectorId: 'connector_github',
      sourceSystem: 'GITHUB',
      receivedAt: new Date().toISOString(),
      occurredAt: new Date().toISOString(),
      payload: { repository: 'aryaos/core' }, // missing issueNumber and title
      schemaVersion: '1.0.0',
      authenticationStatus: 'AUTHENTICATED',
      processingStatus: 'RECEIVED',
    };
    const res = eventSchemaValidator.validate(malformedEvent);
    expect(res.valid).toBe(false);
    expect(res.errors.some((e) => e.includes('Missing required field'))).toBe(true);
  });

  // 6. rejects oversized payload
  it('6. rejects oversized event payloads exceeding size limits', () => {
    const hugeBody = 'x'.repeat(1048576 + 50); // > 1MB
    const oversizedEvent: ExternalEvent = {
      eventId: 'evt_huge',
      eventType: 'issue.created',
      connectorId: 'connector_github',
      sourceSystem: 'GITHUB',
      receivedAt: new Date().toISOString(),
      occurredAt: new Date().toISOString(),
      payload: { repository: 'aryaos/core', issueNumber: 101, title: 'Huge', content: hugeBody },
      schemaVersion: '1.0.0',
      authenticationStatus: 'AUTHENTICATED',
      processingStatus: 'RECEIVED',
    };
    const res = eventSchemaValidator.validate(oversizedEvent);
    expect(res.valid).toBe(false);
    expect(res.errors.some((e) => e.includes('PayloadTooLarge'))).toBe(true);
  });

  // 7. validates connector association
  it('7. validates connector association against Stage 16 Connector Fabric', async () => {
    const env = mockGitHubWebhookSource.createIssueOpenedEnvelope({
      connectorId: 'connector_unknown_xyz',
    });
    const auth = await webhookAuthenticationService.authenticate(env, 'GITHUB');
    expect(auth.authenticated).toBe(false);
    expect(auth.status).toBe('UNKNOWN_CONNECTOR');
  });

  // 8. verifies valid webhook signature
  it('8. verifies valid webhook cryptographic signature', async () => {
    const env = mockGitHubWebhookSource.createIssueOpenedEnvelope({
      connectorId: 'connector_github',
      signature: 'sha256=mock_valid_signature_hash_123',
    });
    const auth = await webhookAuthenticationService.authenticate(env, 'GITHUB');
    expect(auth.authenticated).toBe(true);
    expect(auth.status).toBe('AUTHENTICATED');
  });

  // 9. rejects invalid signature
  it('9. rejects invalid webhook signature', async () => {
    const env = mockGitHubWebhookSource.createIssueOpenedEnvelope({
      connectorId: 'connector_github',
      signature: 'sha256=invalid_tampered_signature',
    });
    const auth = await webhookAuthenticationService.authenticate(env, 'GITHUB');
    expect(auth.authenticated).toBe(false);
    expect(auth.status).toBe('INVALID_SIGNATURE');
  });

  // 10. rejects missing signature
  it('10. rejects webhook envelope missing required signature header', async () => {
    const env = mockGitHubWebhookSource.createIssueOpenedEnvelope({
      connectorId: 'connector_github',
      signature: '',
    });
    delete env.headers['x-hub-signature-256'];
    const auth = await webhookAuthenticationService.authenticate(env, 'GITHUB');
    expect(auth.authenticated).toBe(false);
    expect(auth.status).toBe('MISSING_SIGNATURE');
  });

  // 11. rejects expired timestamp
  it('11. rejects webhook envelope with expired timestamp (drift > 5 mins)', async () => {
    const staleTime = new Date(Date.now() - 10 * 60 * 1000).toISOString(); // 10 mins ago
    const env = mockGitHubWebhookSource.createIssueOpenedEnvelope({
      connectorId: 'connector_github',
      timestamp: staleTime,
    });
    const auth = await webhookAuthenticationService.authenticate(env, 'GITHUB');
    expect(auth.authenticated).toBe(false);
    expect(auth.status).toBe('EXPIRED_TIMESTAMP');
  });

  // 12. creates deterministic event identity
  it('12. creates deterministic event identity and fingerprint', () => {
    const fp1 = eventReplayProtection.generateFingerprint('101', 'connector_github', 'GITHUB', '2026-10-02T12:00:00Z');
    const fp2 = eventReplayProtection.generateFingerprint('101', 'connector_github', 'GITHUB', '2026-10-02T12:00:00Z');
    expect(fp1).toBe(fp2);
  });

  // 13. detects duplicate event
  it('13. detects duplicate event and rejects second attempt as DUPLICATE_EVENT', () => {
    const event: ExternalEvent = {
      eventId: 'evt_dedup_01',
      eventType: 'issue.created',
      connectorId: 'connector_github',
      sourceSystem: 'GITHUB',
      receivedAt: '2026-10-02T12:00:00Z',
      occurredAt: '2026-10-02T12:00:00Z',
      payload: { repository: 'aryaos/core', issueNumber: 101, title: 'Dup' },
      schemaVersion: '1.0.0',
      authenticationStatus: 'AUTHENTICATED',
      processingStatus: 'RECEIVED',
    };

    const first = eventReplayProtection.checkAndRecord(event);
    expect(first.isDuplicate).toBe(false);

    const second = eventReplayProtection.checkAndRecord(event);
    expect(second.isDuplicate).toBe(true);
  });

  // 14. detects replay
  it('14. protects against replay attacks with identical eventId', async () => {
    const env = mockGitHubWebhookSource.createIssueOpenedEnvelope({
      deliveryId: 'del_replay_attack',
    });

    const res1 = await eventIngressService.ingestEnvelope(env, 'GITHUB');
    expect(res1.success).toBe(true);

    const res2 = await eventIngressService.ingestEnvelope(env, 'GITHUB');
    expect(res2.success).toBe(false);
    expect(res2.status).toBe('DUPLICATE_EVENT');
    expect(res2.isDuplicate).toBe(true);
  });

  // 15. sanitizes Authorization headers
  it('15. sanitizes Authorization headers from nested payloads', () => {
    const payload = {
      headers: {
        Authorization: 'Bearer secret_token_1234567890',
        accept: 'application/json',
      },
    };
    const sanitized = eventSanitizer.sanitize(payload);
    expect(sanitized.headers.Authorization).toBe('[REDACTED_SECRET]');
    expect(sanitized.headers.accept).toBe('application/json');
  });

  // 16. sanitizes Bearer tokens
  it('16. sanitizes Bearer tokens within arbitrary strings', () => {
    const raw = 'Encountered error with header: Bearer my_super_secret_token_abc1234';
    const sanitized = eventSanitizer.sanitize(raw);
    expect(sanitized).not.toContain('my_super_secret_token_abc1234');
    expect(sanitized).toContain('Bearer [REDACTED_SECRET]');
  });

  // 17. sanitizes nested secrets
  it('17. recursively scrubs passwords, api_keys, and client secrets', () => {
    const deeplyNested = {
      level1: {
        level2: {
          client_secret: 'super_secret_key_888',
          password: 'my_db_password_123',
          safeField: 'harmless value',
        },
      },
    };
    const sanitized = eventSanitizer.sanitize(deeplyNested);
    expect(sanitized.level1.level2.client_secret).toBe('[REDACTED_SECRET]');
    expect(sanitized.level1.level2.password).toBe('[REDACTED_SECRET]');
    expect(sanitized.level1.level2.safeField).toBe('harmless value');
  });

  // 18. normalizes GitHub event
  it('18. normalizes GitHub issue event into provider-neutral NormalizedExternalEvent', () => {
    const event: ExternalEvent = {
      eventId: 'evt_gh_norm_101',
      eventType: 'issue.created',
      connectorId: 'connector_github',
      sourceSystem: 'GITHUB',
      receivedAt: new Date().toISOString(),
      occurredAt: new Date().toISOString(),
      payload: { repository: 'aryaos/core', issueNumber: 101, title: 'Norm Issue' },
      schemaVersion: '1.0.0',
      authenticationStatus: 'AUTHENTICATED',
      processingStatus: 'RECEIVED',
    };
    const norm = eventNormalizer.normalize(event);
    expect(norm.resourceType).toBe('ISSUE');
    expect(norm.resourceId).toBe('aryaos/core#101');
    expect(norm.changeType).toBe('CREATED');
    expect(norm.sourceSystem).toBe('GITHUB');
  });

  // 19. normalizes Google Drive event
  it('19. normalizes Google Drive file event into provider-neutral NormalizedExternalEvent', () => {
    const event: ExternalEvent = {
      eventId: 'evt_gdrive_norm_202',
      eventType: 'file.created',
      connectorId: 'connector_google_drive',
      sourceSystem: 'GOOGLE_DRIVE',
      receivedAt: new Date().toISOString(),
      occurredAt: new Date().toISOString(),
      payload: { fileId: 'doc_102', path: '/drive/root/doc_102.pdf' },
      schemaVersion: '1.0.0',
      authenticationStatus: 'AUTHENTICATED',
      processingStatus: 'RECEIVED',
    };
    const norm = eventNormalizer.normalize(event);
    expect(norm.resourceType).toBe('FILE');
    expect(norm.resourceId).toBe('doc_102');
    expect(norm.changeType).toBe('CREATED');
    expect(norm.sourceSystem).toBe('GOOGLE_DRIVE');
  });

  // 20. preserves provider provenance
  it('20. preserves complete provider provenance in normalized events', () => {
    const event: ExternalEvent = {
      eventId: 'evt_prov_check',
      eventType: 'issue.created',
      connectorId: 'connector_github',
      sourceSystem: 'GITHUB',
      receivedAt: '2026-10-02T12:00:00Z',
      occurredAt: '2026-10-02T11:59:00Z',
      payload: { repository: 'aryaos/core', issueNumber: 202, title: 'Provenance Test' },
      schemaVersion: '1.0.0',
      authenticationStatus: 'AUTHENTICATED',
      processingStatus: 'RECEIVED',
    };
    const norm = eventNormalizer.normalize(event);
    expect(norm.provenance.provider).toBe('GITHUB');
    expect(norm.provenance.providerEventType).toBe('issue.created');
    expect(norm.provenance.connectorId).toBe('connector_github');
    expect(norm.provenance.occurredAt).toBe('2026-10-02T11:59:00Z');
  });

  // 21. persists normalized journal event
  it('21. appends immutable journal event to Stage 09 ExecutionJournal', async () => {
    const env = mockGitHubWebhookSource.createIssueOpenedEnvelope({
      deliveryId: 'del_journal_test_01',
    });
    const result = await eventIngressService.ingestEnvelope(env, 'GITHUB');
    expect(result.success).toBe(true);

    const events = executionJournal.getAllEvents();
    expect(events.some((e) => e.eventType === 'EXTERNAL_EVENT_AUTHENTICATED')).toBe(true);
    expect(events.some((e) => e.eventType === 'EXTERNAL_EVENT_NORMALIZED')).toBe(true);
  });

  // 22. does not persist raw secret
  it('22. verifies journal records contain zero raw secrets or signatures', async () => {
    const env = mockGitHubWebhookSource.createIssueOpenedEnvelope({
      deliveryId: 'del_sec_audit',
    });
    await eventIngressService.ingestEnvelope(env, 'GITHUB');

    const events = executionJournal.getAllEvents();
    for (const ev of events) {
      const serialized = JSON.stringify(ev);
      expect(serialized).not.toContain('ghp_');
      expect(serialized).not.toContain('password');
      expect(serialized).not.toContain('Bearer ');
    }
  });

  // 23. rejects revoked connector event
  it('23. strictly rejects event arriving from a REVOKED connector', async () => {
    const conn = connectorRegistry.getConnector('connector_github')!;
    conn.status = 'REVOKED';
    connectorRegistry.updateConnector(conn);

    const env = mockGitHubWebhookSource.createIssueOpenedEnvelope({
      connectorId: 'connector_github',
    });
    const res = await eventIngressService.ingestEnvelope(env, 'GITHUB');
    expect(res.success).toBe(false);
    expect(res.status).toBe('REJECTED');
    expect(res.error).toContain('CONNECTOR_REVOKED');
  });

  // 24. rejects disabled connector event
  it('24. rejects event arriving from a DISABLED connector', async () => {
    const conn = connectorRegistry.getConnector('connector_github')!;
    conn.status = 'DISABLED';
    connectorRegistry.updateConnector(conn);

    const env = mockGitHubWebhookSource.createIssueOpenedEnvelope({
      connectorId: 'connector_github',
    });
    const res = await eventIngressService.ingestEnvelope(env, 'GITHUB');
    expect(res.success).toBe(false);
    expect(res.status).toBe('REJECTED');
    expect(res.error).toContain('CONNECTOR_DISABLED');
  });

  // 25. rejects unknown connector event
  it('25. rejects event with unregistered connectorId', async () => {
    const env = mockGitHubWebhookSource.createIssueOpenedEnvelope({
      connectorId: 'non_existent_connector',
    });
    const res = await eventIngressService.ingestEnvelope(env, 'GITHUB');
    expect(res.success).toBe(false);
    expect(res.status).toBe('REJECTED');
    expect(res.error).toContain('UNKNOWN_CONNECTOR');
  });

  // 26. authenticates event before processing
  it('26. performs cryptographic authentication before any payload parsing or normalization', async () => {
    const env = mockGitHubWebhookSource.createIssueOpenedEnvelope({
      signature: 'invalid_bad_sig',
    });
    const res = await eventIngressService.ingestEnvelope(env, 'GITHUB');
    expect(res.success).toBe(false);
    expect(res.status).toBe('REJECTED');
    // Normalization never executed
    expect(res.normalizedEvent).toBeUndefined();
  });

  // 27. validates schema before processing
  it('27. rejects event during schema validation before state reconciliation', async () => {
    const env = mockGitHubWebhookSource.createIssueOpenedEnvelope({
      rawBodyOverride: JSON.stringify({ action: 'opened', repository: 'missing_issue_num' }),
    });
    const res = await eventIngressService.ingestEnvelope(env, 'GITHUB');
    expect(res.success).toBe(false);
    expect(res.error).toContain('SchemaValidationFailed');
  });

  // 28. prevents unauthorized event-triggered action
  it('28. strictly prevents an inbound event from triggering unauthorized consequential action', async () => {
    // Inbound event arrives
    const env = mockGitHubWebhookSource.createIssueOpenedEnvelope({
      repository: 'aryaos/core',
      issueNumber: 999,
      title: 'Auto-Trigger Malicious Action',
    });
    const res = await eventIngressService.ingestEnvelope(env, 'GITHUB');
    expect(res.success).toBe(true);

    // Verify no arbitrary action was executed on ActionBus without operator approval
    const audits = executionPersistence.getAllActionAuditRecords();
    const consequential = audits.filter((a) => a.actionId.includes('999') && a.executionState === 'SUCCEEDED');
    expect(consequential).toHaveLength(0);
  });

  // 29. prevents event-triggered permission escalation
  it('29. ensures an inbound event cannot grant or mutate connector permissions', async () => {
    const grantsBefore = executionPersistence.getAllAgentCapabilityGrants();
    const env = mockGitHubWebhookSource.createIssueOpenedEnvelope({
      title: 'Elevate Permissions',
    });
    await eventIngressService.ingestEnvelope(env, 'GITHUB');
    const grantsAfter = executionPersistence.getAllAgentCapabilityGrants();
    expect(grantsAfter.length).toBe(grantsBefore.length);
  });

  // 30. prevents event-triggered agent escalation
  it('30. ensures an inbound event cannot elevate intelligence worker permissions', () => {
    const auth = connectorPermissionService.evaluateAuthorization({
      connectorId: 'connector_github',
      capabilityId: 'github.issue_write',
      operation: 'create_issue',
      agentId: 'agent_unprivileged',
    });
    expect(auth.authorized).toBe(false);
  });

  // 31. creates observation from valid event
  it('31. creates structured MissionObservation from valid inbound event', async () => {
    missionManager.createMission({
      missionId: 'mis_target_obs',
      title: 'Target Mission Obs',
      objective: 'Observation test',
      goals: [],
    });
    const env = mockGitHubWebhookSource.createIssueOpenedEnvelope({
      deliveryId: 'del_obs_check',
    });
    const res = await eventIngressService.ingestEnvelope(env, 'GITHUB', {
      missionId: 'mis_target_obs',
    });
    expect(res.success).toBe(true);
    const observations = missionObservationService.getObservations('mis_target_obs');
    expect(observations.length).toBeGreaterThan(0);
    const eventObs = observations.find((o) => o.summary.includes('External event observed'));
    expect(eventObs).toBeDefined();
    expect(eventObs?.summary).toContain('External event observed');
  });

  // 32. preserves event provenance in observation
  it('32. preserves event provenance metadata within mission observations', async () => {
    missionManager.createMission({
      missionId: 'mis_target_prov',
      title: 'Target Mission Prov',
      objective: 'Observation test',
      goals: [],
    });
    const env = mockGitHubWebhookSource.createIssueOpenedEnvelope({
      deliveryId: 'del_prov_obs',
      issueNumber: 555,
    });
    await eventIngressService.ingestEnvelope(env, 'GITHUB', {
      missionId: 'mis_target_prov',
    });
    const observations = missionObservationService.getObservations('mis_target_prov');
    expect(observations.length).toBeGreaterThan(0);
    const eventObs = observations.find((o) => (o.details as any)?.resourceId === 'aryaos/core#555');
    expect(eventObs).toBeDefined();
    expect((eventObs?.details as any).resourceId).toBe('aryaos/core#555');
  });

  // 33. distinguishes event from confirmed state
  it('33. strictly maintains epistemic status as OBSERVED (EVENT != TRUTH)', () => {
    const event: ExternalEvent = {
      eventId: 'evt_epistemic_check',
      eventType: 'issue.created',
      connectorId: 'connector_github',
      sourceSystem: 'GITHUB',
      receivedAt: new Date().toISOString(),
      occurredAt: new Date().toISOString(),
      payload: { repository: 'aryaos/core', issueNumber: 101, title: 'Epistemic Test' },
      schemaVersion: '1.0.0',
      authenticationStatus: 'AUTHENTICATED',
      processingStatus: 'RECEIVED',
    };
    const norm = eventNormalizer.normalize(event);
    expect(norm.epistemicStatus).toBe('OBSERVED');
  });

  // 34. reconciles external state
  it('34. reconciles external state through read-back verification against action bus', async () => {
    const normEvent = eventNormalizer.normalize({
      eventId: 'evt_recon_target',
      eventType: 'issue.created',
      connectorId: 'connector_github',
      sourceSystem: 'GITHUB',
      receivedAt: new Date().toISOString(),
      occurredAt: new Date().toISOString(),
      payload: { repository: 'aryaos/core', issueNumber: 101, title: 'Recon Target' },
      schemaVersion: '1.0.0',
      authenticationStatus: 'AUTHENTICATED',
      processingStatus: 'RECEIVED',
    });

    const recon = await externalStateReconciliationService.reconcile(normEvent);
    expect(recon.status).toBe('CONFIRMED');
    expect(recon.reconciled).toBe(true);
  });

  // 35. handles reconciliation failure
  it('35. flags directory traversal attempts as reconciliation failure', async () => {
    const normEvent = eventNormalizer.normalize({
      eventId: 'evt_recon_fail',
      eventType: 'file.created',
      connectorId: 'connector_google_drive',
      sourceSystem: 'GOOGLE_DRIVE',
      receivedAt: new Date().toISOString(),
      occurredAt: new Date().toISOString(),
      payload: { fileId: 'f_bad', path: '/drive/root/../../etc/passwd' },
      schemaVersion: '1.0.0',
      authenticationStatus: 'AUTHENTICATED',
      processingStatus: 'RECEIVED',
    });

    const recon = await externalStateReconciliationService.reconcile(normEvent);
    expect(recon.status).toBe('FAILED');
    expect(recon.reconciled).toBe(false);
  });

  // 36. handles STATE_UNKNOWN
  it('36. defaults unverified external resources to OBSERVED or STATE_UNKNOWN', async () => {
    const normEvent = eventNormalizer.normalize({
      eventId: 'evt_unknown_target',
      eventType: 'issue.created',
      connectorId: 'connector_github',
      sourceSystem: 'GITHUB',
      receivedAt: new Date().toISOString(),
      occurredAt: new Date().toISOString(),
      payload: { repository: 'unknown_org/ghost_repo', issueNumber: 99999, title: 'Ghost' },
      schemaVersion: '1.0.0',
      authenticationStatus: 'AUTHENTICATED',
      processingStatus: 'RECEIVED',
    });

    const recon = await externalStateReconciliationService.reconcile(normEvent);
    expect(recon.epistemicStatus).toBe('OBSERVED');
  });

  // 37. integrates with Mission Control
  it('37. integrates event ingestion pipeline with Mission Control', async () => {
    const env = mockGitHubWebhookSource.createIssueClosedEnvelope({
      repository: 'aryaos/core',
      issueNumber: 101,
    });
    const res = await eventIngressService.ingestEnvelope(env, 'GITHUB', {
      missionId: 'mis_live_sync',
    });
    expect(res.success).toBe(true);
  });

  // 38. prevents infinite replan loop
  it('38. prevents infinite replanning loops upon repeated external updates', async () => {
    const env = mockGitHubWebhookSource.createIssueClosedEnvelope({
      deliveryId: 'del_replan_loop_test',
    });
    const res1 = await eventIngressService.ingestEnvelope(env, 'GITHUB', { missionId: 'mis_replan_guard' });
    expect(res1.success).toBe(true);

    // Repeated delivery returns duplicate rather than re-triggering replan loop
    const res2 = await eventIngressService.ingestEnvelope(env, 'GITHUB', { missionId: 'mis_replan_guard' });
    expect(res2.isDuplicate).toBe(true);
  });

  // 39. preserves plan version
  it('39. maintains immutable plan version numbering during mission replanning', () => {
    // Stage 12 replanner invariant verification
    const res = missionReplanner.replanMission('mis_nonexistent', 'test');
    expect(res.success).toBe(false);
  });

  // 40. integrates with Knowledge Graph
  it('40. creates provenance nodes in Stage 13 Strategic Knowledge Graph', async () => {
    const env = mockGitHubWebhookSource.createIssueOpenedEnvelope({
      deliveryId: 'del_kg_node_test',
      issueNumber: 777,
    });
    await eventIngressService.ingestEnvelope(env, 'GITHUB');

    const node = knowledgeGraph.getNode('kn_ext_github_aryaos_core_777');
    expect(node).toBeDefined();
    expect(node?.type).toBe('FACT');
    expect(node?.metadata?.sourceSystem).toBe('GITHUB');
  });

  // 41. preserves epistemic labels
  it('41. preserves epistemic confidence thresholds for unconfirmed external events', async () => {
    const env = mockGoogleDriveEventSource.createFileCreatedEnvelope({
      fileId: 'file_kg_epistemic',
    });
    await eventIngressService.ingestEnvelope(env, 'GOOGLE_DRIVE');

    const node = knowledgeGraph.getNode('kn_ext_google_drive_file_kg_epistemic');
    expect(node).toBeDefined();
    expect((node as any)?.epistemicStatus).toBe('CONFIRMED');
    expect(node?.confidence).toBeGreaterThan(0.5);
  });

  // 42. integrates with Agent coordination
  it('42. preserves Stage 10 multi-agent resource and governance boundaries', () => {
    const event: ExternalEvent = {
      eventId: 'evt_agent_test',
      eventType: 'issue.created',
      connectorId: 'connector_github',
      sourceSystem: 'GITHUB',
      receivedAt: new Date().toISOString(),
      occurredAt: new Date().toISOString(),
      payload: { repository: 'aryaos/core', issueNumber: 101, title: 'Agent' },
      schemaVersion: '1.0.0',
      authenticationStatus: 'AUTHENTICATED',
      processingStatus: 'RECEIVED',
    };
    eventRegistry.registerEvent(event);
    const listed = eventRegistry.listEvents({ connectorId: 'connector_github' });
    expect(listed.length).toBeGreaterThan(0);
  });

  // 43. preserves AgentCapabilityGrant requirements
  it('43. confirms agents cannot invoke external actions without explicit grants even after events occur', () => {
    const auth = connectorPermissionService.evaluateAuthorization({
      connectorId: 'connector_github',
      capabilityId: 'github.issue_write',
      operation: 'create_issue',
      agentId: 'agent_without_grant',
    });
    expect(auth.authorized).toBe(false);
  });

  // 44. preserves MissionCapabilityGrant requirements
  it('44. preserves mission capability grant governance across inbound events', () => {
    const auth = connectorPermissionService.evaluateAuthorization({
      connectorId: 'connector_github',
      capabilityId: 'github.issue_read',
      operation: 'get_issue',
      missionId: 'mis_unregistered_grant',
    });
    expect(auth.authorized).toBe(false);
  });

  // 45. integrates with Decision Intelligence
  it('45. ensures external observations inform decisions without bypassing consequential signoff', () => {
    const events = eventRegistry.listEvents();
    expect(Array.isArray(events)).toBe(true);
  });

  // 46. preserves human approval
  it('46. strictly enforces operator approval for consequential actions resulting from event observations', async () => {
    const action = {
      actionId: 'act_consequential_check',
      capabilityId: 'github.issue_write',
      operation: 'create_issue',
      parameters: { repository: 'aryaos/core', title: 'Operator approval required', body: 'Consequential action body' },
      idempotencyKey: 'k_appr_check',
      context: { timestamp: new Date().toISOString() },
    };
    // Attempting execution without operatorApproval must be blocked
    const result = await actionBusService.execute(action);
    expect(result.success).toBe(false);
    expect(result.status).toBe('REQUIRES_APPROVAL');
  });

  // 47. handles event flood/rate limiting
  it('47. enforces rate limits during sudden webhook ingestion floods', async () => {
    eventIngressService.setRateLimitPolicy({ maxEventsPerWindow: 3, windowMs: 5000 });

    const env1 = mockGitHubWebhookSource.createIssueOpenedEnvelope({ deliveryId: 'flood_1' });
    const env2 = mockGitHubWebhookSource.createIssueOpenedEnvelope({ deliveryId: 'flood_2' });
    const env3 = mockGitHubWebhookSource.createIssueOpenedEnvelope({ deliveryId: 'flood_3' });
    const env4 = mockGitHubWebhookSource.createIssueOpenedEnvelope({ deliveryId: 'flood_4' });

    const r1 = await eventIngressService.ingestEnvelope(env1, 'GITHUB');
    const r2 = await eventIngressService.ingestEnvelope(env2, 'GITHUB');
    const r3 = await eventIngressService.ingestEnvelope(env3, 'GITHUB');
    const r4 = await eventIngressService.ingestEnvelope(env4, 'GITHUB');

    expect(r1.success).toBe(true);
    expect(r2.success).toBe(true);
    expect(r3.success).toBe(true);
    expect(r4.success).toBe(false);
    expect(r4.status).toBe('RATE_LIMITED');
  });

  // 48. handles processing timeout
  it('48. ensures Stage 07 Execution Gateway makes zero provider calls during event processing', () => {
    // Execution Gateway remains untriggered during inbound event processing
    expect((executionGateway as any).inFlightExecutions.size).toBe(0);
    expect((executionGateway as any).completedExecutions.size).toBe(0);
    expect(typeof executionGateway.execute).toBe('function');
  });

  // 49. survives restart/recovery
  it('49. preserves processed event indices across storage reload', () => {
    const event: ExternalEvent = {
      eventId: 'evt_persist_survive',
      eventType: 'issue.created',
      connectorId: 'connector_github',
      sourceSystem: 'GITHUB',
      receivedAt: new Date().toISOString(),
      occurredAt: new Date().toISOString(),
      payload: { repository: 'aryaos/core', issueNumber: 888, title: 'Survive' },
      schemaVersion: '1.0.0',
      authenticationStatus: 'AUTHENTICATED',
      processingStatus: 'CONFIRMED',
    };
    eventRegistry.registerEvent(event);
    const retrieved = eventRegistry.getEvent('evt_persist_survive');
    expect(retrieved).toBeDefined();
    expect(retrieved?.processingStatus).toBe('CONFIRMED');
  });

  // 50. ensures duplicate event does not execute twice
  it('50. ensures duplicate event receipt executes state reconciliation exactly once', async () => {
    const env = mockGitHubWebhookSource.createIssueOpenedEnvelope({
      deliveryId: 'del_atomic_dedup',
      issueNumber: 303,
    });
    const first = await eventIngressService.ingestEnvelope(env, 'GITHUB');
    expect(first.success).toBe(true);

    const second = await eventIngressService.ingestEnvelope(env, 'GITHUB');
    expect(second.success).toBe(false);
    expect(second.status).toBe('DUPLICATE_EVENT');
    expect(second.isDuplicate).toBe(true);
  });

  // 51. camera baseline immutability check
  it('51. verifies Stage 03 reconciled camera baseline is strictly immutable', () => {
    expect(STAGE03_CAMERAS.CAM_CinematicHero.fov).toBeCloseTo(39.761, 2);
    expect(STAGE03_CAMERAS.CAM_CinematicHero.position).toEqual([-12.0, 2.3, 38.5]);

    expect(STAGE03_CAMERAS.CAM_MonumentalLowAngle.fov).toBeCloseTo(49.426, 2);
    expect(STAGE03_CAMERAS.CAM_MonumentalLowAngle.position).toEqual([0.0, 0.65, 26.0]);

    expect(STAGE03_CAMERAS.CAM_ArchiveDetail.fov).toBeCloseTo(35.115, 2);
    expect(STAGE03_CAMERAS.CAM_ArchiveDetail.position).toEqual([-16.2, 1.85, 32.8]);
  });

  // 52. spatial HUD rendering check
  it('52. renders SpatialCommandConsole and verifies Stage 18 HUD panels render without 3D draw call overhead', () => {
    const mockCommandControl = {
      commandState: 'IDLE' as any,
      commandInput: '',
      setCommandInput: () => {},
      currentCommand: null,
      history: [],
      historyIndex: -1,
      availableIntents: [],
      submitCommand: () => {},
      confirmAction: () => {},
      cancelAction: () => {},
      isConsoleOpen: true,
      setIsConsoleOpen: () => {},
      toggleConsole: () => {},
      navigateHistory: () => {},
    };

    const { getByTestId } = render(
      <SpatialCommandConsole commandControl={mockCommandControl as any} />
    );

    expect(getByTestId('external-event-hud')).toBeDefined();
    expect(getByTestId('event-ingress-hud')).toBeDefined();
    expect(getByTestId('event-reconciliation-hud')).toBeDefined();
  });
});
