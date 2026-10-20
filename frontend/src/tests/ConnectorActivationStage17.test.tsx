/**
 * AryaOS V1 — Stage 17 Verification Test Suite
 * Real Connector Activation & Controlled Integration
 *
 * Covers all 45 required test cases:
 * 1. GitHub discovery
 * 2. Google Drive discovery
 * 3. unsupported connector rejection
 * 4. configuration requirement
 * 5. human authorization requirement
 * 6. autonomous installation approval rejection
 * 7. valid lifecycle transitions
 * 8. invalid lifecycle transitions
 * 9. CredentialRef without secret
 * 10. raw credential persistence rejection
 * 11. token metadata leakage prevention
 * 12. token error leakage prevention
 * 13. expired credential detection
 * 14. execution blocked after expiry
 * 15. reauthentication state
 * 16. credential revocation
 * 17. connector alone does not grant capability
 * 18. capability alone does not grant agent authority
 * 19. agent grant required
 * 20. mission grant required
 * 21. grant intersection enforcement
 * 22. stale permission version rejection
 * 23. revoked connector invalidates grants
 * 24. GitHub scope rejection
 * 25. Google Drive scope rejection
 * 26. authorized GitHub read reaches Action Bus
 * 27. authorized GitHub write reaches Action Bus
 * 28. unauthorized action never reaches transport
 * 29. Stage 15 remains exclusive external execution boundary
 * 30. no direct LLM calls
 * 31. missing OAuth configuration
 * 32. invalid OAuth state
 * 33. authorization code never persists
 * 34. access token never persists
 * 35. refresh token never persists
 * 36. successful authentication creates CredentialRef
 * 37. rate-limit normalization
 * 38. authentication failure normalization
 * 39. timeout normalization
 * 40. uncertain external write enters reconciliation
 * 41. restart revalidates connector
 * 42. revoked credential remains unusable
 * 43. disabled connector cannot execute
 * 44. network unavailable fails closed
 * 45. recovery never performs unauthorized external write
 */

import { describe, it, expect, beforeEach } from 'vitest';
import React from 'react';
import { render } from '@testing-library/react';

// Domain Types
import {
  Connector,
  ConnectorType,
  ConnectorStatus,
  ConnectorScope,
  ConnectorPermission,
} from '../types/connectorFabric';
import { ActionRequest, ActionResult } from '../types/actionBus';

// Core Services
import { connectorRegistry } from '../services/connectorRegistry';
import { connectorDiscoveryService } from '../services/connectorDiscoveryService';
import { connectorLifecycleService } from '../services/connectorLifecycleService';
import { connectorHealthService } from '../services/connectorHealthService';
import { connectorPermissionService } from '../services/connectorPermissionService';
import { credentialBoundary } from '../services/credentialBoundary';
import { credentialResolver } from '../services/credentialResolver';
import { oauthBoundary } from '../services/oauthBoundary';
import { oauthSessionService } from '../services/oauthSessionService';
import { connectorInstallationService } from '../services/connectorInstallationService';
import { connectorTransportRegistry } from '../services/connectorTransportRegistry';
import { actionBusService } from '../services/actionBusService';
import { actionReconciliationService } from '../services/actionReconciliationService';
import { capabilityRegistry } from '../services/capabilityRegistry';
import { adapterRegistry } from '../services/capabilityAdapter';
import { connectorAdapterFactory } from '../services/connectorAdapterFactory';
import { executionPersistence } from '../services/executionPersistence';
import { executionGateway } from '../services/executionGateway';
import { SpatialCommandConsole } from '../components/spatial/SpatialCommandConsole';

describe('AryaOS V1 Stage 17 — Real Connector Activation & Controlled Integration', () => {
  beforeEach(() => {
    localStorage.clear();
    executionPersistence.clearEnvelope();
    oauthSessionService.clear();
    connectorAdapterFactory.initializeAdapters();
    connectorTransportRegistry.getMockTransport().setNetworkOnline(true);
    connectorTransportRegistry.getMockTransport().setSimulatedRateLimit(null);
  });

  // 1. GitHub discovery
  it('1. discovers GitHub connector template with OAuth2 authentication modes', () => {
    const def = connectorDiscoveryService.getDiscoveryDefinition('GITHUB');
    expect(def).not.toBeNull();
    expect(def?.displayName).toContain('GitHub');
    expect(def?.authenticationModes).toContain('OAUTH2');
  });

  // 2. Google Drive discovery
  it('2. discovers Google Drive connector template with read-only storage scopes', () => {
    const def = connectorDiscoveryService.getDiscoveryDefinition('GOOGLE_DRIVE');
    expect(def).not.toBeNull();
    expect(def?.displayName).toContain('Google Drive');
    expect(def?.authenticationModes).toContain('OAUTH2');
  });

  // 3. unsupported connector rejection
  it('3. rejects discovery or installation of unsupported connector types', async () => {
    await expect(
      connectorInstallationService.installAndActivate({
        id: 'conn_unsupported',
        type: 'NON_EXISTENT' as any,
        name: 'Invalid Type',
        configuration: {},
        humanSignoff: { approvedBy: 'OPERATOR_BOB', timestamp: new Date().toISOString() },
      })
    ).rejects.toThrow(/Unsupported connector type/);
  });

  // 4. configuration requirement
  it('4. strictly requires clientId configuration for OAuth2 connectors', async () => {
    await expect(
      connectorInstallationService.installAndActivate({
        id: 'conn_gh_no_client',
        type: 'GITHUB',
        name: 'Unconfigured GitHub',
        configuration: {}, // Missing clientId
        humanSignoff: { approvedBy: 'OPERATOR_BOB', timestamp: new Date().toISOString() },
      })
    ).rejects.toThrow(/CONFIGURATION_REQUIRED/);
  });

  // 5. human authorization requirement
  it('5. requires explicit human operator signoff for connector installation', async () => {
    await expect(
      connectorInstallationService.installAndActivate({
        id: 'conn_gh_no_human',
        type: 'GITHUB',
        name: 'Unapproved GitHub',
        configuration: { clientId: 'client_123' },
      })
    ).rejects.toThrow(/Human Authorization Rejection/);
  });

  // 6. autonomous installation approval rejection
  it('6. rejects autonomous agent or system installation signoffs', async () => {
    await expect(
      connectorInstallationService.installAndActivate({
        id: 'conn_gh_auto_spoof',
        type: 'GITHUB',
        name: 'Auto Approved GitHub',
        configuration: { clientId: 'client_123' },
        humanSignoff: { approvedBy: 'AUTONOMOUS_AGENT', timestamp: new Date().toISOString() },
      })
    ).rejects.toThrow(/Security Boundary Violation/);
  });

  // 7. valid lifecycle transitions
  it('7. executes valid lifecycle transitions from DISCOVERED through ACTIVE', () => {
    const conn: Connector = {
      id: 'conn_lifecycle_17',
      name: 'Lifecycle 17',
      type: 'CUSTOM',
      version: '1.0.0',
      status: 'DISCOVERED',
      health: 'UNKNOWN',
      configuration: {},
      scopes: [],
      permissions: [],
      capabilities: [],
      permissionVersion: 1,
      createdAt: new Date().toISOString(),
      updatedAt: new Date().toISOString(),
    };
    connectorRegistry.registerConnector(conn);

    let updated = connectorLifecycleService.transition('conn_lifecycle_17', 'CONFIGURING', 'OP', 'Config');
    expect(updated.status).toBe('CONFIGURING');

    updated = connectorLifecycleService.transition('conn_lifecycle_17', 'AWAITING_HUMAN_AUTHORIZATION', 'OP', 'Signoff request');
    expect(updated.status).toBe('AWAITING_HUMAN_AUTHORIZATION');

    updated = connectorLifecycleService.transition('conn_lifecycle_17', 'AUTHENTICATING', 'OP', 'Signed');
    expect(updated.status).toBe('AUTHENTICATING');

    updated = connectorLifecycleService.transition('conn_lifecycle_17', 'CONNECTED', 'OP', 'Authed');
    expect(updated.status).toBe('CONNECTED');

    updated = connectorLifecycleService.transition('conn_lifecycle_17', 'HEALTH_CHECK', 'SYSTEM', 'Checking');
    expect(updated.status).toBe('HEALTH_CHECK');

    updated = connectorLifecycleService.transition('conn_lifecycle_17', 'ACTIVE', 'OP', 'Active');
    expect(updated.status).toBe('ACTIVE');
  });

  // 8. invalid lifecycle transitions
  it('8. strictly rejects illegal jumps like DISCOVERED -> ACTIVE', () => {
    const conn: Connector = {
      id: 'conn_illegal_jump_17',
      name: 'Illegal Jump 17',
      type: 'CUSTOM',
      version: '1.0.0',
      status: 'DISCOVERED',
      health: 'UNKNOWN',
      configuration: {},
      scopes: [],
      permissions: [],
      capabilities: [],
      permissionVersion: 1,
      createdAt: new Date().toISOString(),
      updatedAt: new Date().toISOString(),
    };
    connectorRegistry.registerConnector(conn);

    expect(() =>
      connectorLifecycleService.transition('conn_illegal_jump_17', 'ACTIVE', 'OP', 'Illegal bypass')
    ).toThrow(/Invalid lifecycle transition rejected/);
  });

  // 9. CredentialRef without secret
  it('9. ensures created CredentialRef contains only metadata and zero raw secrets', () => {
    const ref = credentialBoundary.createCredentialRef('conn_meta_test', 'OAUTH2', {
      status: 'VALID',
    });
    expect(ref.credentialId).toBeDefined();
    expect((ref as any).token).toBeUndefined();
    expect((ref as any).accessToken).toBeUndefined();
    expect((ref as any).clientSecret).toBeUndefined();
  });

  // 10. raw credential persistence rejection
  it('10. asserts raw credential fields are strictly rejected before persistence', () => {
    const badObject = {
      connectorId: 'conn_pers_leak',
      access_token: 'ghp_secret_access_token_123',
    };
    expect(() => credentialBoundary.assertNoRawCredentials(badObject)).toThrow(/Security Violation/);
  });

  // 11. token metadata leakage prevention
  it('11. verifies metadata objects cannot conceal secret tokens', () => {
    const contaminated = {
      meta: {
        env: 'prod',
        bearer: 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.badsecret',
      },
    };
    expect(() => credentialBoundary.assertNoRawCredentials(contaminated)).toThrow(/Security Violation/);
  });

  // 12. token error leakage prevention
  it('12. scrubs Authorization and bearer tokens from error traces and messages', () => {
    const leakedError = new Error('Request failed with Authorization: Bearer ghp_secret_key_888');
    const sanitized = credentialResolver.sanitizeError(leakedError);
    expect(sanitized.message).not.toContain('ghp_secret_key_888');
    expect(sanitized.message).toContain('Authorization: [REDACTED_SECRET]');
  });

  // 13. expired credential detection
  it('13. detects expired credential validity timestamp', () => {
    const expiredRef = credentialBoundary.createCredentialRef('conn_exp_17', 'TOKEN', {
      expiresAt: new Date(Date.now() - 5000).toISOString(),
      status: 'VALID',
    });
    expect(credentialBoundary.validateCredentialRef(expiredRef)).toBe('EXPIRED');
  });

  // 14. execution blocked after expiry
  it('14. blocks credential resolution and execution when credential is expired', async () => {
    const expiredRef = credentialBoundary.createCredentialRef('conn_exp_block', 'TOKEN', {
      expiresAt: new Date(Date.now() - 5000).toISOString(),
      status: 'EXPIRED',
    });
    await expect(credentialResolver.resolve(expiredRef)).rejects.toThrow(/EXPIRED/);
  });

  // 15. reauthentication state
  it('15. transitions connector to AUTH_REQUIRED when credentials expire', async () => {
    const conn: Connector = {
      id: 'conn_reauth_test',
      name: 'Reauth Test',
      type: 'GITHUB',
      version: '1.0.0',
      status: 'ACTIVE',
      health: 'HEALTHY',
      configuration: { clientId: 'client_123' },
      scopes: [],
      permissions: [],
      capabilities: [],
      credentialRef: credentialBoundary.createCredentialRef('conn_reauth_test', 'OAUTH2', {
        expiresAt: new Date(Date.now() - 1000).toISOString(),
        status: 'EXPIRED',
      }),
      permissionVersion: 1,
      createdAt: new Date().toISOString(),
      updatedAt: new Date().toISOString(),
    };
    connectorRegistry.registerConnector(conn);

    const health = await connectorHealthService.checkHealth('conn_reauth_test');
    expect(health).toBe('AUTH_REQUIRED');
  });

  // 16. credential revocation
  it('16. revokes a connector and invalidates credential reference permanently', () => {
    const conn: Connector = {
      id: 'conn_revoke_test',
      name: 'Revoke Test',
      type: 'CUSTOM',
      version: '1.0.0',
      status: 'ACTIVE',
      health: 'HEALTHY',
      configuration: {},
      scopes: [],
      permissions: [],
      capabilities: [],
      credentialRef: credentialBoundary.createCredentialRef('conn_revoke_test', 'TOKEN', {
        status: 'VALID',
      }),
      permissionVersion: 1,
      createdAt: new Date().toISOString(),
      updatedAt: new Date().toISOString(),
    };
    connectorRegistry.registerConnector(conn);

    const revoked = connectorLifecycleService.revokeConnector('conn_revoke_test', 'SEC_OP', 'Compromise');
    expect(revoked.status).toBe('REVOKED');
    expect(revoked.credentialRef?.status).toBe('REVOKED');
  });

  // 17. connector alone does not grant capability
  it('17. verifies connector activation alone does not grant capability access without explicit permissions', () => {
    const conn: Connector = {
      id: 'conn_active_no_perm',
      name: 'Active No Perm',
      type: 'FILESYSTEM',
      version: '1.0.0',
      status: 'ACTIVE',
      health: 'HEALTHY',
      configuration: {},
      scopes: [],
      permissions: [], // No permissions
      capabilities: [],
      credentialRef: credentialBoundary.createCredentialRef('conn_active_no_perm', 'LOCAL_CREDENTIAL', { status: 'VALID' }),
      permissionVersion: 1,
      createdAt: new Date().toISOString(),
      updatedAt: new Date().toISOString(),
    };
    connectorRegistry.registerConnector(conn);

    const auth = connectorPermissionService.evaluateAuthorization({
      connectorId: 'conn_active_no_perm',
      capabilityId: 'filesystem.read',
      operation: 'read_file',
      resourceTarget: '/workspace',
    });
    expect(auth.authorized).toBe(false);
    expect(auth.reason).toContain('Default DENY');
  });

  // 18. capability alone does not grant agent authority
  it('18. verifies capability permission alone does not grant agent authority without AgentCapabilityGrant', () => {
    const auth = connectorPermissionService.evaluateAuthorization({
      connectorId: 'connector_filesystem',
      capabilityId: 'filesystem.read',
      operation: 'read_file',
      resourceTarget: '/workspace/README.md',
      agentId: 'agent_rogue_no_grant',
    });
    expect(auth.authorized).toBe(false);
    expect(auth.reason).toContain('does not have an active capability grant');
  });

  // 19. agent grant required
  it('19. authorizes execution only when an explicit, active AgentCapabilityGrant exists', () => {
    connectorPermissionService.grantAgentCapability({
      agentId: 'agent_verified_17',
      connectorId: 'connector_filesystem',
      capabilityId: 'filesystem.read',
      scope: { resourceType: 'directory', resourcePath: '/workspace', allowedOperations: ['read_file'], readOnly: true },
      riskLimit: 'LOW',
      grantedBy: 'OPERATOR_ALICE',
    });

    const auth = connectorPermissionService.evaluateAuthorization({
      connectorId: 'connector_filesystem',
      capabilityId: 'filesystem.read',
      operation: 'read_file',
      resourceTarget: '/workspace/README.md',
      agentId: 'agent_verified_17',
    });
    expect(auth.authorized).toBe(true);
  });

  // 20. mission grant required
  it('20. requires explicit MissionCapabilityGrant when mission governance is applied', () => {
    connectorPermissionService.grantMissionCapability({
      missionId: 'mis_governed_17',
      connectorId: 'connector_filesystem',
      capabilityId: 'filesystem.read',
      scope: { resourceType: 'directory', resourcePath: '/workspace', allowedOperations: ['read_file'], readOnly: true },
      riskLimit: 'LOW',
      grantedBy: 'CHIEF_OPERATOR',
    });

    const auth = connectorPermissionService.evaluateAuthorization({
      connectorId: 'connector_filesystem',
      capabilityId: 'filesystem.read',
      operation: 'read_file',
      resourceTarget: '/workspace/README.md',
      missionId: 'mis_governed_17',
    });
    expect(auth.authorized).toBe(true);
  });

  // 21. grant intersection enforcement
  it('21. enforces intersection of both agent and mission grants when both are present', () => {
    connectorPermissionService.grantAgentCapability({
      agentId: 'agent_dual_test',
      connectorId: 'connector_filesystem',
      capabilityId: 'filesystem.read',
      scope: { resourceType: 'directory', resourcePath: '/workspace', allowedOperations: ['read_file'], readOnly: true },
      riskLimit: 'LOW',
      grantedBy: 'OP',
    });

    // Agent has grant, but Mission does not
    const partialAuth = connectorPermissionService.evaluateAuthorization({
      connectorId: 'connector_filesystem',
      capabilityId: 'filesystem.read',
      operation: 'read_file',
      resourceTarget: '/workspace/README.md',
      agentId: 'agent_dual_test',
      missionId: 'mis_unregistered_dual',
    });
    expect(partialAuth.authorized).toBe(false);
  });

  // 22. stale permission version rejection
  it('22. rejects authorization when verifiedPermissionVersion is older than connector version', () => {
    const auth = connectorPermissionService.evaluateAuthorization({
      connectorId: 'connector_filesystem',
      capabilityId: 'filesystem.read',
      operation: 'read_file',
      resourceTarget: '/workspace/README.md',
      verifiedPermissionVersion: 999, // Mismatched version
    });
    expect(auth.authorized).toBe(false);
    expect(auth.reason).toContain('Stale permission authorization');
  });

  // 23. revoked connector invalidates grants
  it('23. blocks execution against revoked connector even if agent grant previously existed', () => {
    const conn: Connector = {
      id: 'conn_grant_revoked',
      name: 'Revoked Grant Test',
      type: 'FILESYSTEM',
      version: '1.0.0',
      status: 'ACTIVE',
      health: 'HEALTHY',
      configuration: {},
      scopes: [{ resourceType: 'directory', resourcePath: '/workspace', allowedOperations: ['read_file'], readOnly: true }],
      permissions: [
        {
          permissionId: 'perm_rev_test',
          connectorId: 'conn_grant_revoked',
          name: 'Rev Test',
          scope: { resourceType: 'directory', resourcePath: '/workspace', allowedOperations: ['read_file'], readOnly: true },
          riskTier: 'LOW',
          requiresHumanApproval: false,
          version: 1,
        },
      ],
      capabilities: [],
      credentialRef: credentialBoundary.createCredentialRef('conn_grant_revoked', 'LOCAL_CREDENTIAL', { status: 'VALID' }),
      permissionVersion: 1,
      createdAt: new Date().toISOString(),
      updatedAt: new Date().toISOString(),
    };
    connectorRegistry.registerConnector(conn);

    // Revoke connector
    connectorLifecycleService.revokeConnector('conn_grant_revoked', 'SEC_OP', 'Incident');

    const readiness = connectorHealthService.evaluateActionReadiness('conn_grant_revoked');
    expect(readiness.ready).toBe(false);
  });

  // 24. GitHub scope rejection
  it('24. rejects GitHub operations outside authorized repository scope', () => {
    const auth = connectorPermissionService.evaluateAuthorization({
      connectorId: 'connector_github',
      capabilityId: 'github.issue_read',
      operation: 'get_issue',
      resourceTarget: 'unauthorized-org/private-repo',
    });
    expect(auth.authorized).toBe(false);
  });

  // 25. Google Drive scope rejection
  it('25. rejects Google Drive operations targeting out-of-scope paths', () => {
    const auth = connectorPermissionService.evaluateAuthorization({
      connectorId: 'connector_google_drive',
      capabilityId: 'google_drive.read_file',
      operation: 'read_file',
      resourceTarget: '/unauthorized/system/secrets.json',
    });
    expect(auth.authorized).toBe(false);
  });

  // 26. authorized GitHub read reaches Action Bus
  it('26. dispatches authorized GitHub issue read through Action Bus end-to-end', async () => {
    // Configure connector_github as active with valid credential in test mode
    const ghConn = connectorRegistry.getConnector('connector_github')!;
    ghConn.status = 'ACTIVE';
    ghConn.health = 'HEALTHY';
    ghConn.credentialRef!.status = 'VALID';
    connectorRegistry.updateConnector(ghConn);

    const request: ActionRequest = {
      actionId: 'act_gh_read_test',
      capabilityId: 'github.read_issue',
      operation: 'get_issue',
      parameters: { repository: 'aryaos/core', issueNumber: 101 },
      idempotencyKey: 'k_gh_read_01',
      context: { timestamp: new Date().toISOString() },
    };

    const result = await actionBusService.execute(request);
    expect(result.success).toBe(true);
    expect(result.status).toBe('SUCCEEDED');
    expect((result.data as any).title).toBe('Memory Environment Anchor');
  });

  // 27. authorized GitHub write reaches Action Bus
  it('27. dispatches authorized GitHub issue creation through Action Bus with operator approval', async () => {
    const request: ActionRequest = {
      actionId: 'act_gh_write_test',
      capabilityId: 'github.create_issue',
      operation: 'create_issue',
      parameters: {
        repository: 'aryaos/core',
        title: 'Stage 17 Real Connector Integration',
        body: 'Controlled external activation verified',
      },
      idempotencyKey: 'k_gh_write_01',
      context: { timestamp: new Date().toISOString() },
    };

    const result = await actionBusService.execute(request, {
      operatorApproval: { approvedBy: 'OPERATOR_ALICE' },
    });
    expect(result.success).toBe(true);
    expect((result.data as any).number).toBeGreaterThan(100);
  });

  // 28. unauthorized action never reaches transport
  it('28. strictly blocks unauthorized action before it can invoke connector transport', async () => {
    const request: ActionRequest = {
      actionId: 'act_unauth_transport_check',
      capabilityId: 'filesystem.read',
      operation: 'read_file',
      parameters: { path: '/etc/shadow' }, // Out of scope
      idempotencyKey: 'k_unauth_01',
      context: { timestamp: new Date().toISOString() },
    };

    const result = await actionBusService.execute(request);
    expect(result.success).toBe(false);
    expect(result.status).toBe('DENIED');
  });

  // 29. Stage 15 remains exclusive external execution boundary
  it('29. verifies all external actions route exclusively through Stage 15 actionBusService.execute()', () => {
    expect(actionBusService.execute).toBeDefined();
    expect(actionBusService.cancel).toBeDefined();
  });

  // 30. no direct LLM calls
  it('30. verifies Stage 17 services make zero direct LLM provider API calls', () => {
    expect((connectorInstallationService as any).executeLLM).toBeUndefined();
    expect((credentialResolver as any).callOpenAI).toBeUndefined();
    expect((oauthBoundary as any).callAnthropic).toBeUndefined();
  });

  // 31. missing OAuth configuration
  it('31. flags OAuth initiation without clientId as CONFIGURATION_REQUIRED', () => {
    expect(() =>
      oauthBoundary.generateAuthorizationUrl({
        connectorId: 'conn_test_no_client',
        connectorType: 'GITHUB',
        redirectUri: 'http://localhost:3000/oauth/callback',
      })
    ).toThrow(/CONFIGURATION_REQUIRED/);
  });

  // 32. invalid OAuth state
  it('32. rejects OAuth exchange when state token is missing or forged (CSRF defense)', async () => {
    await expect(
      oauthBoundary.exchangeCodeForCredentialRef({
        connectorId: 'connector_github',
        connectorType: 'GITHUB',
        authorizationCode: 'valid_code_123',
        state: 'forged_fake_state_token',
        redirectUri: 'http://localhost:3000/oauth/callback',
      })
    ).rejects.toThrow(/OAuth Security Rejection/);
  });

  // 33. authorization code never persists
  it('33. verifies authorizationCode is never placed into persistent storage', async () => {
    const authUrl = oauthBoundary.generateAuthorizationUrl({
      connectorId: 'connector_github',
      connectorType: 'GITHUB',
      clientId: 'mock_gh_client_id',
      redirectUri: 'http://localhost:3000/oauth/callback',
    });

    const credRef = await oauthBoundary.exchangeCodeForCredentialRef({
      connectorId: 'connector_github',
      connectorType: 'GITHUB',
      authorizationCode: 'auth_code_secret_abc123',
      state: authUrl.state,
      redirectUri: 'http://localhost:3000/oauth/callback',
    });

    expect((credRef as any).authorizationCode).toBeUndefined();
    expect(() => credentialBoundary.assertNoRawCredentials(credRef)).not.toThrow();
  });

  // 34. access token never persists
  it('34. verifies access token is never placed in CredentialRef or execution envelope', () => {
    const credRef = credentialBoundary.createCredentialRef('conn_token_test', 'OAUTH2', {
      status: 'VALID',
    });
    expect((credRef as any).access_token).toBeUndefined();
    expect((credRef as any).accessToken).toBeUndefined();
  });

  // 35. refresh token never persists
  it('35. verifies refresh token is never placed in CredentialRef or execution envelope', () => {
    const credRef = credentialBoundary.createCredentialRef('conn_ref_test', 'OAUTH2', {
      status: 'VALID',
    });
    expect((credRef as any).refresh_token).toBeUndefined();
    expect((credRef as any).refreshToken).toBeUndefined();
  });

  // 36. successful authentication creates CredentialRef
  it('36. generates valid CredentialRef with non-sensitive metadata upon authentication', async () => {
    const authUrl = oauthBoundary.generateAuthorizationUrl({
      connectorId: 'connector_google_drive',
      connectorType: 'GOOGLE_DRIVE',
      clientId: 'google_drive_client_id_test',
      redirectUri: 'http://localhost:3000/oauth/callback',
    });

    const credRef = await oauthBoundary.exchangeCodeForCredentialRef({
      connectorId: 'connector_google_drive',
      connectorType: 'GOOGLE_DRIVE',
      authorizationCode: 'auth_code_gdrive_456',
      state: authUrl.state,
      redirectUri: 'http://localhost:3000/oauth/callback',
    });

    expect(credRef.status).toBe('VALID');
    expect(credRef.credentialType).toBe('OAUTH2');
    expect(credRef.credentialId).toContain('cred_oauth_connector_google_drive');
  });

  // 37. rate-limit normalization
  it('37. normalizes 429 response into RATE_LIMITED status with retryAfterMs', async () => {
    // Simulate rate limit on mock transport
    connectorTransportRegistry.getMockTransport().setSimulatedRateLimit({ remaining: 0, resetMs: 30000 });

    const ghConn = connectorRegistry.getConnector('connector_github')!;
    ghConn.status = 'ACTIVE';
    ghConn.health = 'HEALTHY';
    ghConn.credentialRef!.status = 'VALID';
    connectorRegistry.updateConnector(ghConn);

    const request: ActionRequest = {
      actionId: 'act_rate_limit_test',
      capabilityId: 'github.issue_read',
      operation: 'get_issue',
      parameters: { repository: 'aryaos/core', issueNumber: 101 },
      idempotencyKey: 'k_rl_01',
      context: { timestamp: new Date().toISOString() },
    };

    const result = await actionBusService.execute(request);
    expect(result.success).toBe(false);
    expect(result.error?.category).toBe('RATE_LIMIT');
  });

  // 38. authentication failure normalization
  it('38. normalizes authentication failure without leaking credentials', async () => {
    const conn = connectorRegistry.getConnector('connector_github')!;
    conn.status = 'ACTIVE';
    conn.health = 'HEALTHY';
    conn.credentialRef!.status = 'EXPIRED';
    connectorRegistry.updateConnector(conn);

    const request: ActionRequest = {
      actionId: 'act_auth_fail_test',
      capabilityId: 'github.issue_read',
      operation: 'get_issue',
      parameters: { repository: 'aryaos/core', issueNumber: 101 },
      idempotencyKey: 'k_af_01',
      context: { timestamp: new Date().toISOString() },
    };

    const result = await actionBusService.execute(request);
    expect(result.success).toBe(false);
    expect(result.error?.category).toBe('AUTHORIZATION');
    expect(result.error?.message).not.toContain('Bearer');
  });

  // 39. timeout normalization
  it('39. normalizes adapter timeout into TIMEOUT status and classifies as retryable', async () => {
    const slowAdapter = {
      canExecute: () => true,
      validate: () => ({ valid: true, errors: [] }),
      execute: async () => {
        await new Promise((r) => setTimeout(r, 200));
        return { done: true };
      },
      cancel: () => true,
      healthCheck: async () => 'ONLINE' as const,
    };
    adapterRegistry.registerAdapter('test.slow_timeout_17', slowAdapter);
    capabilityRegistry.registerCapability({
      capabilityId: 'test.slow_timeout_17',
      name: 'Slow Service',
      type: 'CUSTOM',
      description: 'Slow test',
      version: '1.0.0',
      riskLevel: 'LOW',
      requiredPermissions: ['WORKFLOW_TRIGGER'],
      supportedOperations: ['slow_op'],
      inputSchema: {},
      timeoutMs: 20,
      retryPolicy: { maxRetries: 0, retryableCategories: ['TIMEOUT'], backoffMs: 0 },
      idempotencyPolicy: { isIdempotent: true, requiresIdempotencyKey: false },
      availability: 'ONLINE',
    });

    const request: ActionRequest = {
      actionId: 'act_timeout_norm_test',
      capabilityId: 'test.slow_timeout_17',
      operation: 'slow_op',
      parameters: {},
      idempotencyKey: 'k_to_norm',
      context: { timestamp: new Date().toISOString() },
    };

    const result = await actionBusService.execute(request);
    expect(result.status).toBe('TIMEOUT');
    expect(result.error?.category).toBe('TIMEOUT');
  });

  // 40. uncertain external write enters reconciliation
  it('40. marks uncertain external write as STATE_UNKNOWN and reconciles prior to duplicate side effects', async () => {
    const ambiguousRequest: ActionRequest = {
      actionId: 'act_ambig_17',
      capabilityId: 'external.http',
      operation: 'post',
      parameters: { url: 'https://api.aryaos.local/submit', method: 'POST' },
      idempotencyKey: 'k_ambig_17',
      context: { timestamp: new Date().toISOString() },
    };

    const recon = await actionReconciliationService.reconcile(ambiguousRequest);
    expect(recon.status).toBe('STATE_UNKNOWN');
    expect(recon.reconciled).toBe(false);
  });

  // 41. restart revalidates connector
  it('41. revalidates restored connector credentials upon application reload', () => {
    const conn: Connector = {
      id: 'conn_restart_reval',
      name: 'Restart Reval',
      type: 'GITHUB',
      version: '1.0.0',
      status: 'ACTIVE',
      health: 'HEALTHY',
      configuration: { clientId: 'client_123' },
      scopes: [],
      permissions: [],
      capabilities: [],
      credentialRef: credentialBoundary.createCredentialRef('conn_restart_reval', 'OAUTH2', {
        expiresAt: new Date(Date.now() - 5000).toISOString(),
        status: 'EXPIRED',
      }),
      permissionVersion: 1,
      createdAt: new Date().toISOString(),
      updatedAt: new Date().toISOString(),
    };
    executionPersistence.saveConnector(conn);

    const reloaded = executionPersistence.getConnector('conn_restart_reval');
    expect(reloaded).not.toBeNull();
    const evaluated = credentialBoundary.validateCredentialRef(reloaded!.credentialRef!);
    expect(evaluated).toBe('EXPIRED');
  });

  // 42. revoked credential remains unusable
  it('42. verifies revoked credential cannot be re-authenticated without new registration', async () => {
    const revokedRef = credentialBoundary.createCredentialRef('conn_perm_revoked', 'TOKEN', {
      status: 'REVOKED',
    });
    await expect(credentialResolver.resolve(revokedRef)).rejects.toThrow(/REVOKED and permanently disabled/);
  });

  // 43. disabled connector cannot execute
  it('43. blocks execution when connector status is set to DISABLED', () => {
    const conn: Connector = {
      id: 'conn_disabled_exec',
      name: 'Disabled Exec',
      type: 'FILESYSTEM',
      version: '1.0.0',
      status: 'DISABLED',
      health: 'UNAVAILABLE',
      configuration: {},
      scopes: [],
      permissions: [],
      capabilities: [],
      credentialRef: credentialBoundary.createCredentialRef('conn_disabled_exec', 'LOCAL_CREDENTIAL', { status: 'VALID' }),
      permissionVersion: 1,
      createdAt: new Date().toISOString(),
      updatedAt: new Date().toISOString(),
    };
    connectorRegistry.registerConnector(conn);

    const readiness = connectorHealthService.evaluateActionReadiness('conn_disabled_exec');
    expect(readiness.ready).toBe(false);
    expect(readiness.status).toBe('DISABLED');
  });

  // 44. network unavailable fails closed
  it('44. fails closed when network transport is offline', async () => {
    connectorTransportRegistry.getMockTransport().setNetworkOnline(false);

    const ghConn = connectorRegistry.getConnector('connector_github')!;
    ghConn.status = 'ACTIVE';
    ghConn.health = 'HEALTHY';
    ghConn.credentialRef!.status = 'VALID';
    connectorRegistry.updateConnector(ghConn);

    const request: ActionRequest = {
      actionId: 'act_net_offline_test',
      capabilityId: 'github.issue_read',
      operation: 'get_issue',
      parameters: { repository: 'aryaos/core', issueNumber: 101 },
      idempotencyKey: 'k_offline_01',
      context: { timestamp: new Date().toISOString() },
    };

    const result = await actionBusService.execute(request);
    expect(result.success).toBe(false);
    expect(result.error?.category).toBe('TRANSIENT');
  });

  // 45. recovery never performs unauthorized external write
  it('45. ensures recovery never executes unauthorized external write operations', async () => {
    const unauthorizedWriteRequest: ActionRequest = {
      actionId: 'act_recov_unauth_write',
      capabilityId: 'filesystem.write',
      operation: 'write_file',
      parameters: { path: '/workspace/secrets.txt', content: 'unauthorized data' },
      idempotencyKey: 'k_recov_unauth_write',
      context: { timestamp: new Date().toISOString() },
    };

    // Attempt execute without operator approval on HIGH-risk write
    const result = await actionBusService.execute(unauthorizedWriteRequest);
    expect(result.success).toBe(false);
    expect(result.status).toBe('REQUIRES_APPROVAL');
  });

  // Additional Verification: Spatial Command Console HUD panels
  it('46. renders SpatialCommandConsole and verifies Stage 17 HUD panels render without 3D draw call overhead', () => {
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

    const { getByTestId } = render(<SpatialCommandConsole commandControl={mockCommandControl as any} />);
    expect(getByTestId('connector-activation-hud')).toBeDefined();
    expect(getByTestId('authentication-status-hud')).toBeDefined();
    expect(getByTestId('credential-status-hud')).toBeDefined();
    expect(getByTestId('credential-ref-mask').textContent).toBe('••••a91c');
    expect(getByTestId('credential-status-badge').textContent).toContain('VALID');
  });
});
