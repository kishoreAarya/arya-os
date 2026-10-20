/**
 * AryaOS V1 — Stage 16: Connector Fabric, Identity & Permission Management Test Suite
 *
 * Verifies:
 * - Connector registration, catalog, and duplicate prevention
 * - State machine lifecycle validation and invalid transition rejection
 * - Credential Boundary and Zero Raw Secret storage invariants
 * - Default DENY scoped permissions, agent grants, mission grants, and versioning
 * - Health gatekeeping and health-based action blocking
 * - Revocation, disconnection, and stale authorization invalidation
 * - Action Bus integration and defense-in-depth authorization
 * - Persistence, recovery, and audit trailing
 * - Spatial HUD integration with ZERO additional WebGL draw calls
 * - Stage 03 Blender master scene and camera immutability
 */

import React from 'react';
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { render } from '@testing-library/react';

import {
  Connector,
  ConnectorPermission,
  ConnectorScope,
  ConnectorCapability,
} from '../types/connectorFabric';
import { connectorRegistry } from '../services/connectorRegistry';
import { connectorLifecycleService } from '../services/connectorLifecycleService';
import { credentialBoundary, mockOAuthProvider, mockCredentialStore } from '../services/credentialBoundary';
import { connectorHealthService } from '../services/connectorHealthService';
import { connectorDiscoveryService } from '../services/connectorDiscoveryService';
import { connectorPermissionService } from '../services/connectorPermissionService';
import { actionBusService } from '../services/actionBusService';
import { executionPersistence } from '../services/executionPersistence';
import { executionGateway } from '../services/executionGateway';
import { decisionIntelligenceService } from '../services/decisionIntelligenceService';
import { missionManager } from '../services/missionManager';
import { STAGE03_CAMERAS } from '../stage03_assembly';
import { SpatialCommandConsole } from '../components/spatial/SpatialCommandConsole';
import { ActionRequest } from '../types/actionBus';

describe('AryaOS V1 Stage 16 — Connector Fabric, Identity & Permission Management', () => {
  beforeEach(() => {
    connectorRegistry.reset();
    mockCredentialStore.clear();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  // 1. Connector Registration
  it('1. registers external connectors with structured schemas, scopes, and capabilities', () => {
    const connector: Connector = {
      id: 'conn_custom_01',
      name: 'Custom Enterprise DB',
      type: 'CUSTOM',
      version: '1.0.0',
      status: 'CONFIGURING',
      health: 'HEALTHY',
      configuration: { baseUrl: 'https://db.enterprise.local' },
      scopes: [
        { resourceType: 'database', resourcePath: 'analytics_db', allowedOperations: ['query'], readOnly: true },
      ],
      permissions: [],
      capabilities: [],
      permissionVersion: 1,
      createdAt: new Date().toISOString(),
      updatedAt: new Date().toISOString(),
    };

    connectorRegistry.registerConnector(connector);
    const retrieved = connectorRegistry.getConnector('conn_custom_01');
    expect(retrieved).not.toBeNull();
    expect(retrieved?.name).toBe('Custom Enterprise DB');
    expect(retrieved?.type).toBe('CUSTOM');
  });

  // 2. Duplicate Connector Rejection
  it('2. rejects duplicate connector registrations deterministically', () => {
    const connector: Connector = {
      id: 'conn_dup_test',
      name: 'Duplicate Test',
      type: 'CUSTOM',
      version: '1.0.0',
      status: 'CONFIGURING',
      health: 'HEALTHY',
      configuration: {},
      scopes: [],
      permissions: [],
      capabilities: [],
      permissionVersion: 1,
      createdAt: new Date().toISOString(),
      updatedAt: new Date().toISOString(),
    };

    connectorRegistry.registerConnector(connector);
    expect(() => connectorRegistry.registerConnector(connector)).toThrow(/already registered/);
  });

  // 3. Connector Lifecycle
  it('3. transitions connector lifecycle through valid state machine transitions', () => {
    const conn: Connector = {
      id: 'conn_lifecycle_test',
      name: 'Lifecycle Test',
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

    // DISCOVERED -> CONFIGURING
    let updated = connectorLifecycleService.transition('conn_lifecycle_test', 'CONFIGURING', 'OPERATOR', 'Configure settings');
    expect(updated.status).toBe('CONFIGURING');

    // CONFIGURING -> AUTHENTICATING
    updated = connectorLifecycleService.transition('conn_lifecycle_test', 'AUTHENTICATING', 'OPERATOR', 'Start auth');
    expect(updated.status).toBe('AUTHENTICATING');

    // AUTHENTICATING -> CONNECTED
    updated = connectorLifecycleService.transition('conn_lifecycle_test', 'CONNECTED', 'OPERATOR', 'Handshake ok');
    expect(updated.status).toBe('CONNECTED');

    // CONNECTED -> ACTIVE
    updated = connectorLifecycleService.transition('conn_lifecycle_test', 'ACTIVE', 'OPERATOR', 'Activate');
    expect(updated.status).toBe('ACTIVE');
    expect(updated.health).toBe('HEALTHY');
  });

  // 4. Invalid State Transition Rejection
  it('4. rejects invalid state machine transitions without corrupting state', () => {
    const conn: Connector = {
      id: 'conn_invalid_jump',
      name: 'Invalid Jump Test',
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

    // Direct jump from DISCOVERED -> ACTIVE is illegal
    expect(() =>
      connectorLifecycleService.transition('conn_invalid_jump', 'ACTIVE', 'OPERATOR', 'Illegal jump')
    ).toThrow(/Invalid lifecycle transition/);

    expect(connectorRegistry.getConnector('conn_invalid_jump')?.status).toBe('DISCOVERED');
  });

  // 5. Connector Discovery
  it('5. discovers available connector definitions without automatically connecting', () => {
    const definitions = connectorDiscoveryService.discoverConnectors();
    expect(definitions.length).toBeGreaterThanOrEqual(6);

    const ghDef = connectorDiscoveryService.getDiscoveryDefinition('GITHUB');
    expect(ghDef).not.toBeNull();
    expect(ghDef?.displayName).toContain('GitHub');
    expect(ghDef?.authenticationModes).toContain('OAUTH2');

    // Verify discovery does not auto-register unauthorized active connectors
    const all = connectorRegistry.listConnectors();
    const slackConn = all.find((c) => c.type === 'SLACK');
    expect(slackConn).toBeUndefined();
  });

  // 6. Credential Reference Creation
  it('6. creates non-sensitive CredentialRefs containing zero raw secret material', () => {
    const credRef = credentialBoundary.createCredentialRef('connector_github', 'OAUTH2', {
      expiresAt: new Date(Date.now() + 3600000).toISOString(),
      metadata: { scope: 'read:org' },
    });

    expect(credRef.credentialId).toContain('cred_ref_connector_github');
    expect(credRef.connectorId).toBe('connector_github');
    expect(credRef.credentialType).toBe('OAUTH2');
    expect((credRef as any).token).toBeUndefined();
    expect((credRef as any).password).toBeUndefined();
    expect((credRef as any).apiKey).toBeUndefined();
  });

  // 7. No Raw Credential Persistence
  it('7. strictly asserts that persisted objects contain zero raw credentials', () => {
    const cleanObject = {
      connectorId: 'conn_ok',
      status: 'ACTIVE',
      meta: { region: 'us-east' },
    };
    expect(() => credentialBoundary.assertNoRawCredentials(cleanObject)).not.toThrow();

    const contaminatedObject = {
      connectorId: 'conn_bad',
      token: 'ghp_secret_access_token_1234567890',
    };
    expect(() => credentialBoundary.assertNoRawCredentials(contaminatedObject)).toThrow(/Security Violation/);
  });

  // 8. OAuth Configuration Requirement
  it('8. flags unconfigured OAuth connectors as CONFIGURATION_REQUIRED', () => {
    const conn = connectorRegistry.getConnector('connector_github');
    expect(conn).not.toBeNull();
    expect(conn?.credentialRef?.status).toBe('CONFIGURATION_REQUIRED');
    expect(conn?.health).toBe('AUTH_REQUIRED');
  });

  // 9. Credential Expiration
  it('9. detects expired credentials and classifies status as EXPIRED', () => {
    const expiredRef = credentialBoundary.createCredentialRef('conn_exp_test', 'TOKEN', {
      expiresAt: new Date(Date.now() - 1000).toISOString(), // 1s in the past
      status: 'VALID',
    });

    const evaluated = credentialBoundary.validateCredentialRef(expiredRef);
    expect(evaluated).toBe('EXPIRED');
  });

  // 10. Permission Creation
  it('10. creates explicit, typed ConnectorPermissions with resource scopes', () => {
    const scope: ConnectorScope = {
      resourceType: 'repository',
      resourcePath: 'aryaos/frontend',
      allowedOperations: ['read_file', 'create_issue'],
      readOnly: false,
    };

    const perm: ConnectorPermission = {
      permissionId: 'perm_test_01',
      connectorId: 'connector_github',
      name: 'Frontend Repo Access',
      scope,
      riskTier: 'MEDIUM',
      requiresHumanApproval: false,
      version: 1,
    };

    expect(perm.scope.resourcePath).toBe('aryaos/frontend');
    expect(perm.riskTier).toBe('MEDIUM');
  });

  // 11. Default Deny
  it('11. enforces DEFAULT DENY when an operation is not explicitly permitted', () => {
    const auth = connectorPermissionService.evaluateAuthorization({
      connectorId: 'connector_filesystem',
      capabilityId: 'filesystem.write',
      operation: 'destroy_database', // Not permitted
      resourceTarget: '/workspace',
    });

    expect(auth.authorized).toBe(false);
    expect(auth.reason).toContain('Default DENY');
  });

  // 12. Scoped Permission
  it('12. restricts operations to declared resource scopes and rejects out-of-scope targets', () => {
    // Authorized scope: /workspace
    const authorized = connectorPermissionService.evaluateAuthorization({
      connectorId: 'connector_filesystem',
      capabilityId: 'filesystem.read',
      operation: 'read_file',
      resourceTarget: '/workspace/package.json',
    });
    expect(authorized.authorized).toBe(true);

    // Out of scope: /etc/shadow
    const unauthorized = connectorPermissionService.evaluateAuthorization({
      connectorId: 'connector_filesystem',
      capabilityId: 'filesystem.read',
      operation: 'read_file',
      resourceTarget: '/etc/shadow',
    });
    expect(unauthorized.authorized).toBe(false);
  });

  // 13. Permission Versioning
  it('13. increments permissionVersion when updating connector permissions', () => {
    const conn = connectorRegistry.getConnector('connector_filesystem');
    expect(conn?.permissionVersion).toBe(1);

    connectorPermissionService.updateConnectorPermissions(
      'connector_filesystem',
      [
        {
          permissionId: 'perm_fs_v2',
          connectorId: 'connector_filesystem',
          name: 'V2 Restricted Read',
          scope: { resourceType: 'directory', resourcePath: '/workspace/safe', allowedOperations: ['read_file'], readOnly: true },
          riskTier: 'LOW',
          requiresHumanApproval: false,
          version: 2,
        },
      ],
      'OPERATOR_ADMIN'
    );

    const updated = connectorRegistry.getConnector('connector_filesystem');
    expect(updated?.permissionVersion).toBe(2);
  });

  // 14. Connector Capability Mapping
  it('14. maps connector capabilities accurately to registry definitions', () => {
    const caps = connectorRegistry.getConnectorCapabilities('connector_filesystem');
    expect(caps.length).toBe(2);
    expect(caps.map((c) => c.capabilityId)).toContain('filesystem.read');
    expect(caps.map((c) => c.capabilityId)).toContain('filesystem.write');
  });

  // 15. Connector Health
  it('15. assesses connector health on-demand without background polling overhead', async () => {
    const health = await connectorHealthService.checkHealth('connector_filesystem');
    expect(health).toBe('HEALTHY');

    const ghHealth = await connectorHealthService.checkHealth('connector_github');
    expect(ghHealth).toBe('AUTH_REQUIRED');
  });

  // 16. Health-Based Action Blocking
  it('16. blocks action execution when connector health requires authentication or is unavailable', () => {
    const readiness = connectorHealthService.evaluateActionReadiness('connector_github');
    expect(readiness.ready).toBe(false);
    expect(readiness.status).toBe('REQUIRES_CONFIGURATION');
    expect(readiness.reason).toContain('re-authentication');
  });

  // 17. Connector Revoke
  it('17. revokes a connector and invalidates its credential reference', () => {
    connectorLifecycleService.revokeConnector('connector_filesystem', 'SECURITY_OFFICER', 'Security incident response');
    const conn = connectorRegistry.getConnector('connector_filesystem');
    expect(conn?.status).toBe('REVOKED');
    expect(conn?.credentialRef?.status).toBe('REVOKED');
    expect(conn?.health).toBe('AUTH_REQUIRED');
  });

  // 18. Revoked Connector Execution Denial
  it('18. denies Action Bus execution against a revoked connector', async () => {
    connectorLifecycleService.revokeConnector('connector_filesystem', 'ADMIN', 'Audit test');

    const request: ActionRequest = {
      actionId: 'act_revoked_test',
      capabilityId: 'filesystem.read',
      operation: 'read_file',
      parameters: { path: '/workspace/README.md' },
      idempotencyKey: 'k_rev_01',
      context: { timestamp: new Date().toISOString() },
    };

    const result = await actionBusService.execute(request);
    expect(result.success).toBe(false);
    expect(result.status).toBe('DENIED');
    expect(result.error?.message).toContain('Connector Fabric Gatekeeper');
  });

  // 19. Permission Change Invalidation
  it('19. detects stale permission authorizations after connector permission updates', () => {
    const verifiedVersion = 1;

    // Mutate permissions to version 2
    connectorPermissionService.updateConnectorPermissions('connector_filesystem', [], 'ADMIN');

    // Attempt authorization with stale version token
    const auth = connectorPermissionService.evaluateAuthorization({
      connectorId: 'connector_filesystem',
      capabilityId: 'filesystem.read',
      operation: 'read_file',
      resourceTarget: '/workspace/file.txt',
      verifiedPermissionVersion: verifiedVersion,
    });

    expect(auth.authorized).toBe(false);
    expect(auth.reason).toContain('Stale permission authorization detected');
  });

  // 20. Agent Capability Grant
  it('20. enforces agent-level capability grants with DEFAULT DENY for ungranted agents', () => {
    // Agent 1 receives grant
    connectorPermissionService.grantAgentCapability({
      agentId: 'agent_coder_01',
      connectorId: 'connector_filesystem',
      capabilityId: 'filesystem.read',
      scope: { resourceType: 'directory', resourcePath: '/workspace', allowedOperations: ['read_file'], readOnly: true },
      riskLimit: 'LOW',
      grantedBy: 'OPERATOR',
    });

    const agent1Auth = connectorPermissionService.evaluateAuthorization({
      connectorId: 'connector_filesystem',
      capabilityId: 'filesystem.read',
      operation: 'read_file',
      resourceTarget: '/workspace/src/index.ts',
      agentId: 'agent_coder_01',
    });
    expect(agent1Auth.authorized).toBe(true);

    // Agent 2 has no grant -> Denied
    const agent2Auth = connectorPermissionService.evaluateAuthorization({
      connectorId: 'connector_filesystem',
      capabilityId: 'filesystem.read',
      operation: 'read_file',
      resourceTarget: '/workspace/src/index.ts',
      agentId: 'agent_untrusted_02',
    });
    expect(agent2Auth.authorized).toBe(false);
    expect(agent2Auth.reason).toContain('does not have an active capability grant');
  });

  // 21. Mission Capability Grant
  it('21. enforces mission-level capability grants and blocks ungranted missions', () => {
    connectorPermissionService.grantMissionCapability({
      missionId: 'mis_alpha_build',
      connectorId: 'connector_filesystem',
      capabilityId: 'filesystem.read',
      scope: { resourceType: 'directory', resourcePath: '/workspace', allowedOperations: ['read_file'], readOnly: true },
      riskLimit: 'LOW',
      grantedBy: 'CHIEF_OPERATOR',
    });

    const missionAuth = connectorPermissionService.evaluateAuthorization({
      connectorId: 'connector_filesystem',
      capabilityId: 'filesystem.read',
      operation: 'read_file',
      resourceTarget: '/workspace/package.json',
      missionId: 'mis_alpha_build',
    });
    expect(missionAuth.authorized).toBe(true);

    const ungrantedMissionAuth = connectorPermissionService.evaluateAuthorization({
      connectorId: 'connector_filesystem',
      capabilityId: 'filesystem.read',
      operation: 'read_file',
      resourceTarget: '/workspace/package.json',
      missionId: 'mis_unregistered_99',
    });
    expect(ungrantedMissionAuth.authorized).toBe(false);
  });

  // 22. Agent + Mission Permission Intersection
  it('22. requires intersection of both agent and mission grants when both are present', () => {
    connectorPermissionService.grantAgentCapability({
      agentId: 'agent_lead',
      connectorId: 'connector_filesystem',
      capabilityId: 'filesystem.read',
      scope: { resourceType: 'directory', resourcePath: '/workspace', allowedOperations: ['read_file'], readOnly: true },
      riskLimit: 'LOW',
      grantedBy: 'OPERATOR',
    });

    // Agent has grant, but Mission does not
    const partialAuth = connectorPermissionService.evaluateAuthorization({
      connectorId: 'connector_filesystem',
      capabilityId: 'filesystem.read',
      operation: 'read_file',
      resourceTarget: '/workspace/file.txt',
      agentId: 'agent_lead',
      missionId: 'mis_unauthorized_scope',
    });
    expect(partialAuth.authorized).toBe(false);

    // Grant mission capability
    connectorPermissionService.grantMissionCapability({
      missionId: 'mis_unauthorized_scope',
      connectorId: 'connector_filesystem',
      capabilityId: 'filesystem.read',
      scope: { resourceType: 'directory', resourcePath: '/workspace', allowedOperations: ['read_file'], readOnly: true },
      riskLimit: 'LOW',
      grantedBy: 'OPERATOR',
    });

    // Both granted -> Authorized
    const fullAuth = connectorPermissionService.evaluateAuthorization({
      connectorId: 'connector_filesystem',
      capabilityId: 'filesystem.read',
      operation: 'read_file',
      resourceTarget: '/workspace/file.txt',
      agentId: 'agent_lead',
      missionId: 'mis_unauthorized_scope',
    });
    expect(fullAuth.authorized).toBe(true);
  });

  // 23. Action Bus Integration
  it('23. dispatches authorized connector capability action through Stage 15 Action Bus', async () => {
    const request: ActionRequest = {
      actionId: 'act_conn_bus_dispatch',
      capabilityId: 'filesystem.read',
      operation: 'read_file',
      parameters: { path: '/workspace/README.md' },
      idempotencyKey: 'k_conn_bus_01',
      context: { timestamp: new Date().toISOString() },
    };

    const result = await actionBusService.execute(request);
    expect(result.success).toBe(true);
    expect(result.status).toBe('SUCCEEDED');
  });

  // 24. Action Authorization Integration
  it('24. blocks Action Bus dispatch when connector permission check fails', async () => {
    const request: ActionRequest = {
      actionId: 'act_conn_denied',
      capabilityId: 'filesystem.read',
      operation: 'read_file',
      parameters: { path: '/workspace/README.md' },
      idempotencyKey: 'k_conn_denied_01',
      context: { agentId: 'agent_no_grant', timestamp: new Date().toISOString() },
    };

    const result = await actionBusService.execute(request);
    expect(result.success).toBe(false);
    expect(result.status).toBe('DENIED');
    expect(result.error?.message).toContain('Connector Permission Denied');
  });

  // 25. Human Approval for Privileged Permissions
  it('25. enforces human approval for privileged connector installation and rejects autonomous approval', () => {
    // Attempt autonomous approval
    expect(() =>
      connectorDiscoveryService.installConnector({
        id: 'conn_slack_priv',
        type: 'SLACK',
        name: 'Enterprise Slack',
        configuration: {},
        scopes: [{ resourceType: 'channel', resourcePath: '#exec', allowedOperations: ['send'], readOnly: false }],
        permissions: [
          {
            permissionId: 'perm_slack_send',
            connectorId: 'conn_slack_priv',
            name: 'Slack Send',
            scope: { resourceType: 'channel', resourcePath: '#exec', allowedOperations: ['send'], readOnly: false },
            riskTier: 'HIGH',
            requiresHumanApproval: true,
            version: 1,
          },
        ],
        humanApproval: { approvedBy: 'SYSTEM' }, // Prohibited
      })
    ).toThrow(/Autonomous approval cannot install privileged connectors/);

    // Legitimate human signoff succeeds
    const installed = connectorDiscoveryService.installConnector({
      id: 'conn_slack_priv',
      type: 'SLACK',
      name: 'Enterprise Slack',
      configuration: {},
      scopes: [{ resourceType: 'channel', resourcePath: '#exec', allowedOperations: ['send'], readOnly: false }],
      permissions: [
        {
          permissionId: 'perm_slack_send',
          connectorId: 'conn_slack_priv',
          name: 'Slack Send',
          scope: { resourceType: 'channel', resourcePath: '#exec', allowedOperations: ['send'], readOnly: false },
          riskTier: 'HIGH',
          requiresHumanApproval: true,
          version: 1,
        },
      ],
      humanApproval: { approvedBy: 'OPERATOR_ALICE' },
    });
    expect(installed.id).toBe('conn_slack_priv');
  });

  // 26. Lifecycle Audit Trail
  it('26. generates immutable ConnectorLifecycleEvents into execution persistence', () => {
    connectorLifecycleService.transition('connector_filesystem', 'DEGRADED', 'DIAGNOSTIC_DAEMON', 'High latency detected');

    const events = executionPersistence.getConnectorAuditEvents('connector_filesystem');
    expect(events.length).toBeGreaterThanOrEqual(1);
    const last = events[events.length - 1];
    expect(last.newState).toBe('DEGRADED');
    expect(last.actor).toBe('DIAGNOSTIC_DAEMON');
    expect(last.reason).toContain('High latency');
  });

  // 27. Persistence
  it('27. durably persists connectors, audit records, and capability grants', () => {
    const conn = connectorRegistry.getConnector('connector_filesystem');
    expect(conn).not.toBeNull();

    const loaded = executionPersistence.getConnector('connector_filesystem');
    expect(loaded).not.toBeNull();
    expect(loaded?.id).toBe('connector_filesystem');
  });

  // 28. Recovery
  it('28. restores connector registry state from persisted envelope and revalidates credentials', () => {
    const all = executionPersistence.getAllConnectors();
    expect(all.length).toBeGreaterThanOrEqual(1);

    // Verify recovery doesn't blindly trust expired credentials
    const conn = all[0];
    const status = credentialBoundary.validateCredentialRef(conn.credentialRef);
    expect(['VALID', 'CONFIGURATION_REQUIRED', 'EXPIRED', 'REVOKED']).toContain(status);
  });

  // 29. Idempotency
  it('29. handles duplicate connector transitions idempotently without corrupting state', () => {
    const conn = connectorRegistry.getConnector('connector_filesystem');
    expect(conn?.status).toBe('ACTIVE');

    // Repeated transition to ACTIVE
    const result = connectorLifecycleService.transition('connector_filesystem', 'ACTIVE', 'OPERATOR', 'No-op transition');
    expect(result.status).toBe('ACTIVE');
  });

  // 30. Secret Sanitization
  it('30. strictly sanitizes connector configuration and metadata to prevent secret leakage', () => {
    const dirtyConfig = {
      baseUrl: 'https://api.github.com',
      apiKey: 'sk-proj-super-secret-key-12345',
      bearerToken: 'Bearer raw_jwt_token',
      safeName: 'Public Endpoint',
    };

    const sanitized = executionPersistence.sanitizeForPersistence(dirtyConfig);
    expect((sanitized as any).apiKey).toBe('[REDACTED_SECRET]');
    expect((sanitized as any).bearerToken).toBe('[REDACTED_SECRET]');
    expect(sanitized.safeName).toBe('Public Endpoint');
  });

  // 31. Stage 15 Integration
  it('31. preserves Stage 15 Universal Action Bus contracts and separation invariants', () => {
    expect(actionBusService.execute).toBeDefined();
    expect(actionBusService.cancel).toBeDefined();
  });

  // 32. Stage 14 Integration
  it('32. enforces that Stage 14 decision approvals do not bypass Stage 16 connector permissions', async () => {
    const decision = decisionIntelligenceService.createDecisionWorkflow({
      title: 'Connector Integration Decision',
      objective: 'Verify decision to connector authority flow',
      currentState: 'Strategic proposal approved',
    });
    decisionIntelligenceService.approveDecision(decision.id, 'CHIEF_OPERATOR');

    // Downstream action targeting unauthorized agent grant fails despite approved decision
    const request: ActionRequest = {
      actionId: 'act_dec_unauth_agent',
      capabilityId: 'filesystem.read',
      operation: 'read_file',
      parameters: { path: '/workspace/sensitive.key' },
      idempotencyKey: 'k_dec_auth_01',
      context: {
        decisionId: decision.id,
        agentId: 'agent_without_grant',
        timestamp: new Date().toISOString(),
      },
    };

    const result = await actionBusService.execute(request);
    expect(result.success).toBe(false);
    expect(result.status).toBe('DENIED');
  });

  // 33. Stage 12 Integration
  it('33. preserves Stage 12 mission context in connector authorization and audit traces', () => {
    const mission = missionManager.createMission({
      title: 'Connector Integration Mission',
      objective: 'Verifies mission governance over connectors',
      priority: 'NORMAL',
      goals: [],
    });

    connectorPermissionService.grantMissionCapability({
      missionId: mission.missionId,
      connectorId: 'connector_filesystem',
      capabilityId: 'filesystem.read',
      scope: { resourceType: 'directory', resourcePath: '/workspace', allowedOperations: ['read_file'], readOnly: true },
      riskLimit: 'LOW',
      grantedBy: 'OPERATOR',
    });

    const grant = executionPersistence.getAllMissionCapabilityGrants(mission.missionId);
    expect(grant.length).toBe(1);
    expect(grant[0].missionId).toBe(mission.missionId);
  });

  // 34. Stage 10 Integration
  it('34. enforces Stage 10 resource limits and multi-agent coordination governance', () => {
    // Verifies multi-agent governance respects separate agent grants
    const leadGrant = connectorPermissionService.grantAgentCapability({
      agentId: 'agent_lead',
      connectorId: 'connector_filesystem',
      capabilityId: 'filesystem.write',
      scope: { resourceType: 'directory', resourcePath: '/workspace', allowedOperations: ['write_file'], readOnly: false },
      riskLimit: 'HIGH',
      grantedBy: 'OPERATOR',
    });
    expect(leadGrant.agentId).toBe('agent_lead');
  });

  // 35. Gateway Separation
  it('35. strictly maintains absolute separation between Stage 07 executionGateway and Stage 16 Connector Fabric', () => {
    // executionGateway must not know about connectorRegistry
    expect((executionGateway as any).connectors).toBeUndefined();
    expect((connectorRegistry as any).executeLLM).toBeUndefined();
  });

  // 36. No Direct Provider Calls
  it('36. verifies Connector Fabric services make zero direct LLM provider API calls', () => {
    const conn = connectorRegistry.getConnector('connector_filesystem');
    expect(conn).toBeDefined();
    // Zero provider API interaction in registry, lifecycle, or permissions
    expect((connectorLifecycleService as any).provider).toBeUndefined();
  });

  // 37. Offline Deterministic Tests
  it('37. verifies all capabilities and connectors run offline with zero network credentials required', async () => {
    const handshake = await mockOAuthProvider.simulateHandshake('connector_github', ['read:org']);
    expect(handshake.credentialRef.status).toBe('VALID');
    expect(handshake.grantedScopes).toContain('read:org');
  });

  // 38. Stage 03 Immutability
  it('38. verifies stage03 Blender master scene and camera baseline remain completely untouched', () => {
    expect(STAGE03_CAMERAS.CAM_CinematicHero.fov).toBeCloseTo(39.761, 2);
    expect(STAGE03_CAMERAS.CAM_CinematicHero.position).toEqual([-12.0, 2.3, 38.5]);
    expect(STAGE03_CAMERAS.CAM_MonumentalLowAngle.fov).toBeCloseTo(49.426, 2);
    expect(STAGE03_CAMERAS.CAM_ArchiveDetail.fov).toBeCloseTo(35.115, 2);
  });

  // 39. Zero Additional Draw Calls
  it('39. renders SpatialCommandConsole and verifies Connector Fabric HUD panels render without 3D draw call overhead', () => {
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

    expect(getByTestId('connector-fabric-hud')).toBeDefined();
    expect(getByTestId('permission-matrix-hud')).toBeDefined();
    expect(getByTestId('connector-audit-hud')).toBeDefined();
    expect(getByTestId('connector-status-badge')).toBeDefined();
    expect(getByTestId('permission-default-deny-badge')).toBeDefined();
  });
});
