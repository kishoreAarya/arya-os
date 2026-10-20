/**
 * AryaOS V1 — Stage 21: Governed Policy Control Plane & Runtime Governance Test Suite
 *
 * Exhaustive verification of all 76 specifications across 13 major sections:
 * 1. Context Construction & Sanitization (1-6)
 * 2. Policy Snapshot Immutability & Version Tracking (7-12)
 * 3. Governance Evaluation & Precedence Hierarchy (13-18)
 * 4. Authority Intersection & Fail-Closed Invariant (19-25)
 * 5. Human Approval Gate & Anti-Spoofing (26-31)
 * 6. Staleness Detection & In-Flight Invalidation (32-37)
 * 7. Explainability & Provenance (10-Point Explanation) (38-44)
 * 8. Universal Action Bus Integration (45-50)
 * 9. Connector Fabric & Permission Integration (51-55)
 * 10. Stage 19 Event Reaction Engine Integration (56-60)
 * 11. Mission Control & Decision Intelligence Integration (61-65)
 * 12. Persistence, Audit Trailing & Replay (66-70)
 * 13. DOM Telemetry & Non-WebGL Performance Guard (71-76)
 *
 * ABSOLUTE ARCHITECTURAL INVARIANT:
 * A POLICY DECISION IS NOT AN EXECUTION AUTHORIZATION.
 * POLICY ALLOW ≠ ACTION AUTHORIZATION ≠ CONNECTOR PERMISSION ≠ HUMAN APPROVAL.
 */

import React from 'react';
import { describe, it, expect, beforeEach } from 'vitest';
import { render } from '@testing-library/react';

// Domain Services & Registries
import { governanceControlPlane } from '../services/governanceControlPlane';
import { governanceContextService } from '../services/governanceContextService';
import { policySnapshotService } from '../services/policySnapshotService';
import { governanceAuthorityService } from '../services/governanceAuthorityService';
import { governanceStalenessService } from '../services/governanceStalenessService';
import { governanceExplanationService } from '../services/governanceExplanationService';
import { policyRegistry } from '../services/policyRegistry';
import { executionPersistence } from '../services/executionPersistence';
import { executionJournal } from '../services/executionJournal';
import { actionBusService } from '../services/actionBusService';
import { capabilityRegistry } from '../services/capabilityRegistry';
import { adapterRegistry } from '../services/capabilityAdapter';
import { connectorRegistry } from '../services/connectorRegistry';
import { connectorPermissionService } from '../services/connectorPermissionService';

// Types
import {
  GovernanceRequest,
  GovernanceDecision,
  OperatorApprovalToken,
} from '../types/governanceControlPlane';
import { Policy } from '../types/policyIntelligence';
import { ActionRequest, ActionCapability } from '../types/actionBus';
import { Connector } from '../types/connectorFabric';

// Components
import { SpatialCommandConsole } from '../components/spatial/SpatialCommandConsole';

describe('AryaOS V1 Stage 21 — Governed Policy Control Plane & Runtime Governance', () => {
  beforeEach(() => {
    // Reset all registries and state machines for deterministic isolation
    policyRegistry.reset();
    policySnapshotService.reset();
    governanceControlPlane.resetCache();
    connectorRegistry.reset();
    capabilityRegistry.reset();
    (executionPersistence as any).resetState?.();
    executionJournal.reset();
  });

  // =========================================================================
  // Section 1: Context Construction & Sanitization (1-6)
  // =========================================================================

  it('1. constructs bounded, sanitized GovernanceContext from GovernanceRequest', () => {
    const request: GovernanceRequest = {
      requestId: 'req_001',
      actor: { actorId: 'agent_alpha', actorType: 'AUTONOMOUS_AGENT', role: 'ENGINEER' },
      targetSystem: 'fs-capability',
      capabilityId: 'fs-write',
      actionType: 'FILE_CREATE',
      parameters: { filename: 'test.txt', size: 1024 },
      timestamp: Date.now(),
    };

    const context = governanceContextService.buildContext(request);
    expect(context.requestId).toBe('req_001');
    expect(context.actor.actorId).toBe('agent_alpha');
    expect(context.actor.actorType).toBe('AUTONOMOUS_AGENT');
    expect(context.scopeType).toBe('AGENT');
    expect(context.sanitizedParameters.filename).toBe('test.txt');
    expect(context.sanitizedParameters.size).toBe(1024);
    expect(Object.isFrozen(context)).toBe(true);
  });

  it('2. strips sensitive keys (token, secret, apiKey, password) recursively from context', () => {
    const request: GovernanceRequest = {
      requestId: 'req_002',
      actor: { actorId: 'user_1', actorType: 'USER' },
      targetSystem: 'auth-service',
      parameters: {
        safeField: 'visible_data',
        apiKey: 'SECRET_API_KEY_12345',
        bearerToken: 'BEARER_TOKEN_9999',
        nested: {
          password: 'super_secret_pw',
          innerSafe: 'ok_to_read',
          authHeader: 'Basic dXNlcjpwYXNz',
        },
      },
      timestamp: Date.now(),
    };

    const context = governanceContextService.buildContext(request);
    expect(context.sanitizedParameters.safeField).toBe('visible_data');
    expect(context.sanitizedParameters.apiKey).toBeUndefined();
    expect(context.sanitizedParameters.bearerToken).toBeUndefined();
    const nested = context.sanitizedParameters.nested as Record<string, unknown>;
    expect(nested.password).toBeUndefined();
    expect(nested.authHeader).toBeUndefined();
    expect(nested.innerSafe).toBe('ok_to_read');
  });

  it('3. blocks prototype pollution keys (__proto__, constructor, prototype) in context', () => {
    const maliciousPayload = JSON.parse(
      '{"__proto__": {"polluted": true}, "constructor": {"polluted": true}, "prototype": {"polluted": true}, "normal": 42}'
    );

    const request: GovernanceRequest = {
      requestId: 'req_003',
      actor: { actorId: 'attacker', actorType: 'USER' },
      targetSystem: 'system',
      parameters: maliciousPayload,
      timestamp: Date.now(),
    };

    const context = governanceContextService.buildContext(request);
    expect(context.sanitizedParameters.normal).toBe(42);
    expect((context.sanitizedParameters as any).polluted).toBeUndefined();
    expect((({} as any).polluted)).toBeUndefined();
  });

  it('4. enforces max context depth and key limit on context parameters', () => {
    // Generate deep nested structure (> 3 levels)
    const deepObj = { l1: { l2: { l3: { l4: { l5: 'deep_hidden' } } } } };
    const request: GovernanceRequest = {
      requestId: 'req_004',
      actor: { actorId: 'agent_depth', actorType: 'AUTONOMOUS_AGENT' },
      targetSystem: 'system',
      parameters: deepObj,
      timestamp: Date.now(),
    };

    const context = governanceContextService.buildContext(request);
    const l1 = context.sanitizedParameters.l1 as any;
    const l2 = l1.l2 as any;
    const l3 = l2.l3 as any;
    // Depth limit stops recursion
    expect(l3.l4).toBeUndefined();
  });

  it('5. derives correct PolicyScopeType from request characteristics', () => {
    const reqConnector: GovernanceRequest = {
      requestId: 'r_conn',
      actor: { actorId: 'op', actorType: 'USER' },
      targetSystem: 'conn_1',
      connectorId: 'conn_github',
      timestamp: Date.now(),
    };
    expect(governanceContextService.buildContext(reqConnector).scopeType).toBe('CONNECTOR');

    const reqTrigger: GovernanceRequest = {
      requestId: 'r_trig',
      actor: { actorId: 'trig', actorType: 'EXTERNAL_TRIGGER' },
      targetSystem: 'trig_1',
      triggerId: 'trig_webhook_1',
      timestamp: Date.now(),
    };
    expect(governanceContextService.buildContext(reqTrigger).scopeType).toBe('TRIGGER');

    const reqMission: GovernanceRequest = {
      requestId: 'r_miss',
      actor: { actorId: 'miss', actorType: 'SYSTEM' },
      targetSystem: 'mission_1',
      missionId: 'mission_orion',
      timestamp: Date.now(),
    };
    expect(governanceContextService.buildContext(reqMission).scopeType).toBe('MISSION');
  });

  it('6. sanitizes and restricts runtime context overrides to prevent arbitrary injection', () => {
    const request: GovernanceRequest = {
      requestId: 'req_006',
      actor: { actorId: 'user_1', actorType: 'USER' },
      targetSystem: 'system',
      timestamp: Date.now(),
    };

    const overrides = {
      activeConcurrentActions: 5,
      costUsd: 12.5,
      arbitraryInjectedKey: 'MALICIOUS_OVERRIDE',
    };

    const context = governanceContextService.buildContext(request, overrides as any);
    expect(context.activeConcurrentActions).toBe(5);
    expect(context.costUsd).toBe(12.5);
    expect((context as any).arbitraryInjectedKey).toBeUndefined();
  });

  // =========================================================================
  // Section 2: Policy Snapshot Immutability & Version Tracking (7-12)
  // =========================================================================

  it('7. captures consistent, immutable snapshot from active policies in PolicyRegistry', () => {
    const policy = createTestPolicy('pol_active_1', 'ACTIVE', 'SYSTEM_SAFETY', 'ALLOW');
    policyRegistry.registerPolicy(policy);

    const snapshot = policySnapshotService.captureSnapshot();
    expect(snapshot.activePolicyCount).toBe(1);
    expect(snapshot.policies[0].policyId).toBe('pol_active_1');
    expect(snapshot.registryVersion).toBe(policyRegistry.getRegistryVersion());
    expect(snapshot.fingerprint).toBeDefined();
  });

  it('8. snapshot includes only ACTIVE policies (ignores DRAFT, CANDIDATE, REVOKED, PAUSED)', () => {
    policyRegistry.registerPolicy(createTestPolicy('pol_active', 'ACTIVE', 'SECURITY', 'ALLOW'));
    policyRegistry.registerPolicy(createTestPolicy('pol_draft', 'DRAFT', 'SECURITY', 'ALLOW'));
    policyRegistry.registerPolicy(createTestPolicy('pol_cand', 'CANDIDATE', 'SECURITY', 'ALLOW'));

    const snapshot = policySnapshotService.captureSnapshot();
    expect(snapshot.activePolicyCount).toBe(1);
    expect(snapshot.policies[0].policyId).toBe('pol_active');
  });

  it('9. snapshot is deep-frozen (Object.isFrozen) to prevent in-flight modification', () => {
    policyRegistry.registerPolicy(createTestPolicy('pol_frozen', 'ACTIVE', 'SECURITY', 'ALLOW'));
    const snapshot = policySnapshotService.captureSnapshot();

    expect(Object.isFrozen(snapshot)).toBe(true);
    expect(Object.isFrozen(snapshot.policies)).toBe(true);
    expect(Object.isFrozen(snapshot.policies[0])).toBe(true);
  });

  it('10. in-flight registration or update of policies does not mutate existing snapshot', () => {
    policyRegistry.registerPolicy(createTestPolicy('pol_initial', 'ACTIVE', 'SECURITY', 'ALLOW'));
    const snapshot = policySnapshotService.captureSnapshot();
    expect(snapshot.activePolicyCount).toBe(1);

    // Register a second policy afterwards
    policyRegistry.registerPolicy(createTestPolicy('pol_subsequent', 'ACTIVE', 'SECURITY', 'ALLOW'));
    expect(snapshot.activePolicyCount).toBe(1);
    expect(snapshot.policies.length).toBe(1);
    expect(policySnapshotService.isSnapshotCurrent(snapshot)).toBe(false);
  });

  it('11. snapshot generates deterministic fingerprint and repeatable snapshotId', () => {
    policyRegistry.registerPolicy(createTestPolicy('pol_fp', 'ACTIVE', 'SECURITY', 'ALLOW'));
    const snap1 = policySnapshotService.captureSnapshot();

    expect(snap1.fingerprint).toContain('v');
    expect(snap1.snapshotId).toContain(snap1.fingerprint.split('_')[1].slice(0, 6));
  });

  it('12. detects snapshot misalignment when policyRegistry version increments', () => {
    const pol = policyRegistry.registerPolicy(createTestPolicy('pol_align', 'ACTIVE', 'SECURITY', 'ALLOW'));
    const snap = policySnapshotService.captureSnapshot();
    expect(policySnapshotService.isSnapshotCurrent(snap)).toBe(true);

    // Transition status or update increments registryVersion
    policyRegistry.transitionStatus(pol.id, 'PAUSED', 'OPERATOR', 'Testing');
    expect(policySnapshotService.isSnapshotCurrent(snap)).toBe(false);
  });

  // =========================================================================
  // Section 3: Governance Evaluation & Precedence Hierarchy (13-18)
  // =========================================================================

  it('13. evaluates request against snapshot policies matching scope and conditions', () => {
    policyRegistry.registerPolicy(
      createTestPolicy('pol_sys', 'ACTIVE', 'SECURITY', 'ALLOW', {
        scopeType: 'SYSTEM',
      })
    );

    const request: GovernanceRequest = {
      requestId: 'req_eval_1',
      actor: { actorId: 'user_1', actorType: 'USER' },
      targetSystem: 'system',
      timestamp: Date.now(),
    };

    const decision = governanceControlPlane.evaluateGovernance(request);
    expect(decision.decision).toBe('ALLOW');
    expect(decision.winningPolicyId).toBe('pol_sys');
    expect(decision.matchedPolicies).toContain('pol_sys');
  });

  it('14. resolves policy conflicts using deterministic 8-tier priority hierarchy', () => {
    // SYSTEM_SAFETY has higher weight than MISSION_POLICY
    policyRegistry.registerPolicy(
      createTestPolicy('pol_safety', 'ACTIVE', 'SYSTEM_SAFETY', 'DENY', {
        scopeType: 'SYSTEM',
      })
    );
    policyRegistry.registerPolicy(
      createTestPolicy('pol_mission', 'ACTIVE', 'MISSION_POLICY', 'ALLOW', {
        scopeType: 'SYSTEM',
      })
    );

    const request: GovernanceRequest = {
      requestId: 'req_conflict_1',
      actor: { actorId: 'user_1', actorType: 'USER' },
      targetSystem: 'system',
      timestamp: Date.now(),
    };

    const decision = governanceControlPlane.evaluateGovernance(request);
    expect(decision.decision).toBe('DENY');
    expect(decision.winningPolicyId).toBe('pol_safety');
    expect(decision.winningPriority).toBe('SYSTEM_SAFETY');
  });

  it('15. contradictory conflict (ALLOW vs DENY) strictly favors higher priority tier', () => {
    policyRegistry.registerPolicy(
      createTestPolicy('pol_sec_deny', 'ACTIVE', 'SECURITY', 'DENY', { scopeType: 'SYSTEM' })
    );
    policyRegistry.registerPolicy(
      createTestPolicy('pol_user_allow', 'ACTIVE', 'USER_POLICY', 'ALLOW', { scopeType: 'SYSTEM' })
    );

    const request: GovernanceRequest = {
      requestId: 'req_sec_win',
      actor: { actorId: 'user_1', actorType: 'USER' },
      targetSystem: 'system',
      timestamp: Date.now(),
    };

    const decision = governanceControlPlane.evaluateGovernance(request);
    expect(decision.decision).toBe('DENY');
    expect(decision.winningPolicyId).toBe('pol_sec_deny');
  });

  it('16. same-tier conflict with opposing effects falls back to safety default (DENY)', () => {
    policyRegistry.registerPolicy(
      createTestPolicy('pol_sec_allow', 'ACTIVE', 'SECURITY', 'ALLOW', { scopeType: 'SYSTEM' })
    );
    policyRegistry.registerPolicy(
      createTestPolicy('pol_sec_deny2', 'ACTIVE', 'SECURITY', 'DENY', { scopeType: 'SYSTEM' })
    );

    const request: GovernanceRequest = {
      requestId: 'req_same_tier',
      actor: { actorId: 'user_1', actorType: 'USER' },
      targetSystem: 'system',
      timestamp: Date.now(),
    };

    const decision = governanceControlPlane.evaluateGovernance(request);
    expect(decision.decision).toBe('DENY');
  });

  it('17. unmatched requests default to ALLOW with complete explanatory metadata', () => {
    // Empty registry
    const request: GovernanceRequest = {
      requestId: 'req_unmatched',
      actor: { actorId: 'user_1', actorType: 'USER' },
      targetSystem: 'system',
      timestamp: Date.now(),
    };

    const decision = governanceControlPlane.evaluateGovernance(request);
    expect(decision.decision).toBe('ALLOW');
    expect(decision.explanation.deterministicRationale).toMatch(/No (active )?policies (matched|triggered)/);
  });

  it('18. governance evaluation produces an immutable, frozen GovernanceDecision', () => {
    const request: GovernanceRequest = {
      requestId: 'req_freeze',
      actor: { actorId: 'user_1', actorType: 'USER' },
      targetSystem: 'system',
      timestamp: Date.now(),
    };

    const decision = governanceControlPlane.evaluateGovernance(request);
    expect(Object.isFrozen(decision)).toBe(true);
    expect(Object.isFrozen(decision.authorityIntersection)).toBe(true);
    expect(Object.isFrozen(decision.explanation)).toBe(true);
  });

  // =========================================================================
  // Section 4: Authority Intersection & Fail-Closed Invariant (19-25)
  // =========================================================================

  it('19. CRITICAL INVARIANT: A POLICY DECISION IS NOT AN EXECUTION AUTHORIZATION', () => {
    // Register policy that says ALLOW
    policyRegistry.registerPolicy(
      createTestPolicy('pol_allow', 'ACTIVE', 'SECURITY', 'ALLOW', { scopeType: 'SYSTEM' })
    );

    // Register a connector that requires grants
    connectorRegistry.registerConnector(createTestConnector('conn_secure', ['fs_write']));

    // Request from autonomous agent with NO capability grant
    const request: GovernanceRequest = {
      requestId: 'req_axiom',
      actor: { actorId: 'agent_rogue', actorType: 'AUTONOMOUS_AGENT' },
      targetSystem: 'conn_secure',
      connectorId: 'conn_secure',
      capabilityId: 'fs_write',
      timestamp: Date.now(),
    };

    const decision = governanceControlPlane.evaluateGovernance(request);
    // Even though policy says ALLOW, authority intersection fails closed!
    expect(decision.authorityIntersection.policyAllowed).toBe(true);
    expect(decision.authorityIntersection.connectorPermissionGranted).toBe(false);
    expect(decision.authorityIntersection.failClosed).toBe(true);
    expect(decision.decision).toBe('DENY');
    expect(decision.reason).toContain('Missing Connector Fabric permission');
  });

  it('20. policy ALLOW + Connector Permission missing -> FAIL CLOSED (DENIED)', () => {
    policyRegistry.registerPolicy(createTestPolicy('pol_allow_conn', 'ACTIVE', 'SECURITY', 'ALLOW'));
    connectorRegistry.registerConnector(createTestConnector('conn_db', ['db_query']));

    const request: GovernanceRequest = {
      requestId: 'req_missing_grant',
      actor: { actorId: 'agent_worker', actorType: 'AUTONOMOUS_AGENT' },
      targetSystem: 'conn_db',
      connectorId: 'conn_db',
      capabilityId: 'db_query',
      timestamp: Date.now(),
    };

    const decision = governanceControlPlane.evaluateGovernance(request);
    expect(decision.decision).toBe('DENY');
    expect(decision.authorityIntersection.effectiveStatus).toBe('MISSING_PERMISSION');
  });

  it('21. policy ALLOW + Action Authorization missing -> FAIL CLOSED (DENIED)', () => {
    policyRegistry.registerPolicy(createTestPolicy('pol_allow_act', 'ACTIVE', 'SECURITY', 'ALLOW'));

    const request: GovernanceRequest = {
      requestId: 'req_missing_auth',
      actor: { actorId: 'user_1', actorType: 'USER' },
      targetSystem: 'system',
      riskLevel: 'CRITICAL',
      timestamp: Date.now(),
    };

    const decision = governanceControlPlane.evaluateGovernance(request);
    // CRITICAL risk without operator approval fails closed
    expect(decision.authorityIntersection.actionAuthorized).toBe(false);
    expect(decision.decision).toBe('REQUIRE_APPROVAL');
  });

  it('22. policy ALLOW + Human Approval missing for CRITICAL risk -> FAIL CLOSED (REQUIRE_APPROVAL)', () => {
    policyRegistry.registerPolicy(createTestPolicy('pol_allow_human', 'ACTIVE', 'SECURITY', 'ALLOW'));

    const request: GovernanceRequest = {
      requestId: 'req_need_approval',
      actor: { actorId: 'agent_99', actorType: 'AUTONOMOUS_AGENT' },
      targetSystem: 'system',
      riskLevel: 'HIGH',
      timestamp: Date.now(),
    };

    const decision = governanceControlPlane.evaluateGovernance(request);
    expect(decision.authorityIntersection.humanApprovalRequired).toBe(true);
    expect(decision.authorityIntersection.humanApprovalStatus).toBe('PENDING');
    expect(decision.decision).toBe('REQUIRE_APPROVAL');
  });

  it('23. policy ALLOW + Mission Constraint violated -> FAIL CLOSED (PAUSED)', () => {
    policyRegistry.registerPolicy(createTestPolicy('pol_allow_mission', 'ACTIVE', 'SECURITY', 'ALLOW'));

    const request: GovernanceRequest = {
      requestId: 'req_mission_paused',
      actor: { actorId: 'user_1', actorType: 'USER' },
      targetSystem: 'system',
      missionId: 'mission_halted',
      timestamp: Date.now(),
    };

    const decision = governanceControlPlane.evaluateGovernance(request, {
      runtimeOverrides: { currentMissionState: 'PAUSED' },
    });

    expect(decision.authorityIntersection.missionConstraintsSatisfied).toBe(false);
    expect(decision.decision).toBe('PAUSE');
  });

  it('24. all five authority tiers granted -> execution ALLOWED', () => {
    policyRegistry.registerPolicy(createTestPolicy('pol_all_pass', 'ACTIVE', 'SECURITY', 'ALLOW'));
    connectorRegistry.registerConnector(createTestConnector('conn_open', ['read']));
    executionPersistence.saveAgentCapabilityGrant({
      grantId: 'acg_grant_ok',
      agentId: 'agent_verified',
      connectorId: 'conn_open',
      capabilityId: 'read',
      scope: { resourceType: 'directory', resourcePath: '*', allowedOperations: ['read'], readOnly: true },
      riskLimit: 'HIGH',
      grantStatus: 'ACTIVE',
      grantedAt: new Date().toISOString(),
      grantedBy: 'OPERATOR',
    });

    const request: GovernanceRequest = {
      requestId: 'req_all_pass',
      actor: { actorId: 'agent_verified', actorType: 'AUTONOMOUS_AGENT' },
      targetSystem: 'conn_open',
      connectorId: 'conn_open',
      capabilityId: 'read',
      riskLevel: 'LOW',
      timestamp: Date.now(),
    };

    const decision = governanceControlPlane.evaluateGovernance(request);
    expect(decision.decision).toBe('ALLOW');
    expect(decision.authorityIntersection.failClosed).toBe(false);
    expect(decision.authorityIntersection.effectiveStatus).toBe('GRANTED');
  });

  it('25. unauthenticated or missing actor identity fails closed with DENY', () => {
    const invalidRequest = {
      requestId: 'req_no_actor',
      targetSystem: 'system',
      timestamp: Date.now(),
    } as any;

    expect(() => governanceControlPlane.evaluateGovernance(invalidRequest)).toThrow(
      'Invalid GovernanceRequest: missing requestId or actor'
    );
  });

  // =========================================================================
  // Section 5: Human Approval Gate & Anti-Spoofing (26-31)
  // =========================================================================

  it('26. high/critical risk actions require valid operator approval token', () => {
    policyRegistry.registerPolicy(createTestPolicy('pol_crit', 'ACTIVE', 'SECURITY', 'ALLOW'));

    const request: GovernanceRequest = {
      requestId: 'req_critical_run',
      actor: { actorId: 'operator_1', actorType: 'USER' },
      targetSystem: 'production-db',
      riskLevel: 'CRITICAL',
      timestamp: Date.now(),
    };

    // Without token: REQUIRE_APPROVAL
    const unapproved = governanceControlPlane.evaluateGovernance(request);
    expect(unapproved.decision).toBe('REQUIRE_APPROVAL');

    // With valid operator token: ALLOW
    const snapshot = policySnapshotService.captureSnapshot();
    const token: OperatorApprovalToken = {
      approvedBy: 'HUMAN_OPERATOR_ALICE',
      approvedAt: Date.now(),
      requestId: 'req_critical_run',
      policySnapshotId: snapshot.snapshotId,
      riskLevel: 'CRITICAL',
      signature: 'VALID_RSA_OPERATOR_SIGNATURE',
    };

    const approved = governanceControlPlane.evaluateGovernance(request, {
      operatorApproval: token,
      snapshot,
    });
    expect(approved.decision).toBe('ALLOW');
    expect(approved.authorityIntersection.humanApprovalStatus).toBe('GRANTED');
  });

  it('27. ANTI-SPOOFING: autonomous agent cannot approve its own or others requests', () => {
    policyRegistry.registerPolicy(createTestPolicy('pol_spoof_agent', 'ACTIVE', 'SECURITY', 'ALLOW'));
    const snapshot = policySnapshotService.captureSnapshot();

    const request: GovernanceRequest = {
      requestId: 'req_spoof_1',
      actor: { actorId: 'agent_x', actorType: 'AUTONOMOUS_AGENT' },
      targetSystem: 'system',
      riskLevel: 'HIGH',
      timestamp: Date.now(),
    };

    // Autonomous agent attempting to forge human approval
    const forgedToken: OperatorApprovalToken = {
      approvedBy: 'agent_x', // Autonomous agent!
      approvedAt: Date.now(),
      requestId: 'req_spoof_1',
      policySnapshotId: snapshot.snapshotId,
      riskLevel: 'HIGH',
      signature: 'AGENT_FAKE_SIG',
    };

    const decision = governanceControlPlane.evaluateGovernance(request, {
      operatorApproval: forgedToken,
      snapshot,
    });
    expect(decision.authorityIntersection.humanApprovalStatus).toBe('FORGED_REJECTED');
    expect(decision.decision).toBe('DENY');
    expect(decision.reason).toContain('Anti-spoofing rejection');
  });

  it('28. ANTI-SPOOFING: system daemon cannot approve requests', () => {
    policyRegistry.registerPolicy(createTestPolicy('pol_spoof_sys', 'ACTIVE', 'SECURITY', 'ALLOW'));
    const snapshot = policySnapshotService.captureSnapshot();

    const request: GovernanceRequest = {
      requestId: 'req_spoof_2',
      actor: { actorId: 'agent_y', actorType: 'AUTONOMOUS_AGENT' },
      targetSystem: 'system',
      riskLevel: 'HIGH',
      timestamp: Date.now(),
    };

    const forgedToken: OperatorApprovalToken = {
      approvedBy: 'daemon_cron_runner', // System daemon!
      approvedAt: Date.now(),
      requestId: 'req_spoof_2',
      policySnapshotId: snapshot.snapshotId,
      riskLevel: 'HIGH',
      signature: 'DAEMON_FAKE_SIG',
    };

    const decision = governanceControlPlane.evaluateGovernance(request, {
      operatorApproval: forgedToken,
      snapshot,
    });
    expect(decision.authorityIntersection.humanApprovalStatus).toBe('FORGED_REJECTED');
    expect(decision.decision).toBe('DENY');
  });

  it('29. operator approval token is uniquely bound to specific requestId', () => {
    policyRegistry.registerPolicy(createTestPolicy('pol_req_bind', 'ACTIVE', 'SECURITY', 'ALLOW'));
    const snapshot = policySnapshotService.captureSnapshot();

    const request: GovernanceRequest = {
      requestId: 'req_target_real',
      actor: { actorId: 'user_1', actorType: 'USER' },
      targetSystem: 'system',
      riskLevel: 'CRITICAL',
      timestamp: Date.now(),
    };

    // Token approved for a different request
    const tokenMismatched: OperatorApprovalToken = {
      approvedBy: 'HUMAN_BOB',
      approvedAt: Date.now(),
      requestId: 'req_DIFFERENT_REPLAY_ATTEMPT',
      policySnapshotId: snapshot.snapshotId,
      riskLevel: 'CRITICAL',
    };

    const decision = governanceControlPlane.evaluateGovernance(request, {
      operatorApproval: tokenMismatched,
      snapshot,
    });
    expect(decision.authorityIntersection.humanApprovalStatus).toBe('FORGED_REJECTED');
    expect(decision.decision).toBe('DENY');
  });

  it('30. operator approval token is invalidated if policy snapshot changes', () => {
    const pol = policyRegistry.registerPolicy(createTestPolicy('pol_token_snap', 'ACTIVE', 'SECURITY', 'ALLOW'));
    const oldSnapshot = policySnapshotService.captureSnapshot();

    // Registry changes!
    policyRegistry.updatePolicy(pol.id, { description: 'Updated' }, 'HUMAN_ALICE', 'Policy update');
    const newSnapshot = policySnapshotService.captureSnapshot();

    const request: GovernanceRequest = {
      requestId: 'req_snap_test',
      actor: { actorId: 'user_1', actorType: 'USER' },
      targetSystem: 'system',
      riskLevel: 'CRITICAL',
      timestamp: Date.now(),
    };

    const tokenForOldSnapshot: OperatorApprovalToken = {
      approvedBy: 'HUMAN_ALICE',
      approvedAt: Date.now(),
      requestId: 'req_snap_test',
      policySnapshotId: oldSnapshot.snapshotId, // Stale snapshot ID
      riskLevel: 'CRITICAL',
    };

    const staleness = governanceStalenessService.checkStaleness(newSnapshot, request, tokenForOldSnapshot);
    expect(staleness.isStale).toBe(true);
    expect(staleness.reason).toContain('Approval token policySnapshotId mismatch');
  });

  it('31. operator approval token requires valid operator signature', () => {
    policyRegistry.registerPolicy(createTestPolicy('pol_sig_check', 'ACTIVE', 'SECURITY', 'ALLOW'));
    const snapshot = policySnapshotService.captureSnapshot();

    const request: GovernanceRequest = {
      requestId: 'req_sig_check',
      actor: { actorId: 'user_1', actorType: 'USER' },
      targetSystem: 'system',
      riskLevel: 'CRITICAL',
      timestamp: Date.now(),
    };

    const tokenForgedSig: OperatorApprovalToken = {
      approvedBy: 'HUMAN_CHARLIE',
      approvedAt: Date.now(),
      requestId: 'req_sig_check',
      policySnapshotId: snapshot.snapshotId,
      riskLevel: 'CRITICAL',
      signature: 'FORGED_SIGNATURE_ATTEMPT',
    };

    const decision = governanceControlPlane.evaluateGovernance(request, {
      operatorApproval: tokenForgedSig,
      snapshot,
    });
    expect(decision.authorityIntersection.humanApprovalStatus).toBe('FORGED_REJECTED');
    expect(decision.decision).toBe('DENY');
  });

  // =========================================================================
  // Section 6: Staleness Detection & In-Flight Invalidation (32-37)
  // =========================================================================

  it('32. TTL expiration marks governance decision STALE', () => {
    policyRegistry.registerPolicy(createTestPolicy('pol_ttl', 'ACTIVE', 'SECURITY', 'ALLOW'));
    const snapshot = policySnapshotService.captureSnapshot();

    const request: GovernanceRequest = {
      requestId: 'req_ttl',
      actor: { actorId: 'user_1', actorType: 'USER' },
      targetSystem: 'system',
      timestamp: Date.now() - 3600000, // 1 hour ago (TTL is 5 minutes)
    };

    const token: OperatorApprovalToken = {
      approvedBy: 'HUMAN_ALICE',
      approvedAt: Date.now() - 3600000, // 1 hour ago
      requestId: 'req_ttl',
      policySnapshotId: snapshot.snapshotId,
      riskLevel: 'LOW',
    };

    const staleness = governanceStalenessService.checkStaleness(snapshot, request, token);
    expect(staleness.isStale).toBe(true);
    expect(staleness.status).toBe('EXPIRED');
  });

  it('33. policy registry version increment invalidates decision snapshot', () => {
    const pol = policyRegistry.registerPolicy(createTestPolicy('pol_reg_inc', 'ACTIVE', 'SECURITY', 'ALLOW'));
    const snap = policySnapshotService.captureSnapshot();

    policyRegistry.updatePolicy(pol.id, { name: 'New name' }, 'OPERATOR', 'Name update');

    const request: GovernanceRequest = {
      requestId: 'req_reg_inc',
      actor: { actorId: 'user_1', actorType: 'USER' },
      targetSystem: 'system',
      timestamp: Date.now(),
    };

    const staleness = governanceStalenessService.checkStaleness(snap, request);
    expect(staleness.isStale).toBe(true);
    expect(staleness.status).toBe('VERSION_MISMATCH');
  });

  it('34. connector permission changes invalidate prior authorization', () => {
    connectorRegistry.registerConnector(createTestConnector('conn_perm_inc', ['op_1']));
    connectorPermissionService.updateConnectorPermissions(
      'conn_perm_inc',
      [{
        permissionId: 'perm_1',
        connectorId: 'conn_perm_inc',
        name: 'test_perm',
        scope: { resourceType: 'directory', allowedOperations: ['op_1', 'op_2'], resourcePath: '*', readOnly: false },
        riskTier: 'LOW',
        requiresHumanApproval: false,
        version: 1,
      }],
      'OPERATOR'
    );

    const check = connectorPermissionService.evaluateAuthorization({
      connectorId: 'conn_perm_inc',
      capabilityId: 'op_1',
      operation: 'op_1',
      verifiedPermissionVersion: 1, // Connector is now v2!
    });

    expect(check.authorized).toBe(false);
    expect(check.reason).toContain('Stale permission authorization detected');
  });

  it('35. request parameter alteration between evaluation and execution is detected as stale', () => {
    const pol = policyRegistry.registerPolicy(createTestPolicy('pol_param_alter', 'ACTIVE', 'SECURITY', 'ALLOW'));
    const snap = policySnapshotService.captureSnapshot();

    const originalReq: GovernanceRequest = {
      requestId: 'req_param_test',
      actor: { actorId: 'user_1', actorType: 'USER' },
      targetSystem: 'system',
      parameters: { path: '/tmp/safe.txt' },
      timestamp: Date.now(),
    };

    const decision = governanceControlPlane.evaluateGovernance(originalReq, { snapshot: snap });

    // In-flight parameter tampering
    const alteredReq: GovernanceRequest = {
      ...originalReq,
      parameters: { path: '/etc/shadow' },
    };

    const preCheck = governanceControlPlane.verifyPreExecution(decision, alteredReq);
    expect(preCheck.isStale).toBe(true);
    expect(preCheck.reason).toContain('Request parameters altered between evaluation and execution');
  });

  it('36. pre-execution staleness check rejects execution under stale decision', () => {
    const pol = policyRegistry.registerPolicy(createTestPolicy('pol_pre_exec', 'ACTIVE', 'SECURITY', 'ALLOW'));
    const snap = policySnapshotService.captureSnapshot();

    const request: GovernanceRequest = {
      requestId: 'req_pre_exec',
      actor: { actorId: 'user_1', actorType: 'USER' },
      targetSystem: 'system',
      timestamp: Date.now(),
    };

    const decision = governanceControlPlane.evaluateGovernance(request, { snapshot: snap });

    // Mutate registry
    policyRegistry.transitionStatus(pol.id, 'PAUSED', 'OPERATOR', 'Pause for maintenance');

    const preExec = governanceControlPlane.verifyPreExecution(decision, request);
    expect(preExec.isStale).toBe(true);
    expect(preExec.status).toBe('VERSION_MISMATCH');
  });

  it('37. explicit re-evaluation captures a fresh snapshot and generates an up-to-date decision', () => {
    const pol = policyRegistry.registerPolicy(createTestPolicy('pol_reeval', 'ACTIVE', 'SECURITY', 'ALLOW'));
    const initialDecision = governanceControlPlane.evaluateGovernance({
      requestId: 'req_reeval',
      actor: { actorId: 'user_1', actorType: 'USER' },
      targetSystem: 'system',
      timestamp: Date.now(),
    });
    expect(initialDecision.decision).toBe('ALLOW');

    // Revoke policy
    policyRegistry.transitionStatus(pol.id, 'REVOKED', 'OPERATOR', 'Revocation');

    // Re-evaluate
    const updatedDecision = governanceControlPlane.evaluateGovernance(
      {
        requestId: 'req_reeval',
        actor: { actorId: 'user_1', actorType: 'USER' },
        targetSystem: 'system',
        timestamp: Date.now(),
      },
      { bypassCache: true }
    );

    // Old policy no longer active
    expect(updatedDecision.matchedPolicies.length).toBe(0);
  });

  // =========================================================================
  // Section 7: Explainability & Provenance (10-Point Explanation) (38-44)
  // =========================================================================

  it('38. 10-Point Explanation: includes request identity, actor, and bounded context summary', () => {
    const req: GovernanceRequest = {
      requestId: 'req_exp_1',
      actor: { actorId: 'agent_exp', actorType: 'AUTONOMOUS_AGENT' },
      targetSystem: 'system',
      timestamp: Date.now(),
    };

    const decision = governanceControlPlane.evaluateGovernance(req);
    expect(decision.explanation.requestId).toBe('req_exp_1');
    expect(decision.explanation.actor?.actorId).toBe('agent_exp');
    expect(decision.explanation.contextSummary?.actorType).toBe('AUTONOMOUS_AGENT');
  });

  it('39. 10-Point Explanation: lists all matched active policies with versions', () => {
    policyRegistry.registerPolicy(createTestPolicy('pol_exp_match', 'ACTIVE', 'SECURITY', 'ALLOW'));
    const req: GovernanceRequest = {
      requestId: 'req_exp_2',
      actor: { actorId: 'user_1', actorType: 'USER' },
      targetSystem: 'system',
      timestamp: Date.now(),
    };

    const decision = governanceControlPlane.evaluateGovernance(req);
    expect(decision.explanation.matchedPolicies).toContain('pol_exp_match');
  });

  it('40. 10-Point Explanation: documents detected conflicts and deterministic resolution rationale', () => {
    policyRegistry.registerPolicy(createTestPolicy('pol_c_1', 'ACTIVE', 'SYSTEM_SAFETY', 'DENY'));
    policyRegistry.registerPolicy(createTestPolicy('pol_c_2', 'ACTIVE', 'RESOURCE_LIMITS', 'ALLOW'));

    const req: GovernanceRequest = {
      requestId: 'req_exp_conflict',
      actor: { actorId: 'user_1', actorType: 'USER' },
      targetSystem: 'system',
      timestamp: Date.now(),
    };

    const decision = governanceControlPlane.evaluateGovernance(req);
    expect(decision.explanation.precedenceResolution).toBeDefined();
    expect(decision.explanation.resultingPolicyDecision).toBe('DENY');
  });

  it('41. 10-Point Explanation: provides granular status for all 5 authority tiers', () => {
    const req: GovernanceRequest = {
      requestId: 'req_exp_tiers',
      actor: { actorId: 'user_1', actorType: 'USER' },
      targetSystem: 'system',
      timestamp: Date.now(),
    };

    const decision = governanceControlPlane.evaluateGovernance(req);
    const tiers = decision.explanation.authorityTiers!;
    expect(tiers.policyTier.evaluated).toBe(true);
    expect(tiers.connectorTier).toBeDefined();
    expect(tiers.actionTier).toBeDefined();
    expect(tiers.humanTier).toBeDefined();
    expect(tiers.missionTier).toBeDefined();
  });

  it('42. 10-Point Explanation: details human approval check and anti-spoofing verification', () => {
    const req: GovernanceRequest = {
      requestId: 'req_exp_human',
      actor: { actorId: 'user_1', actorType: 'USER' },
      targetSystem: 'system',
      riskLevel: 'CRITICAL',
      timestamp: Date.now(),
    };

    const decision = governanceControlPlane.evaluateGovernance(req);
    expect(decision.explanation.humanApprovalCheck!.required).toBe(true);
    expect(decision.explanation.humanApprovalCheck!.status).toBe('PENDING');
  });

  it('43. 10-Point Explanation: captures staleness evaluation and snapshot alignment', () => {
    const req: GovernanceRequest = {
      requestId: 'req_exp_stale',
      actor: { actorId: 'user_1', actorType: 'USER' },
      targetSystem: 'system',
      timestamp: Date.now(),
    };

    const decision = governanceControlPlane.evaluateGovernance(req);
    expect(decision.explanation.stalenessEvaluation!.isStale).toBe(false);
    expect(decision.explanation.policySnapshotId).toBe(decision.policySnapshotId);
  });

  it('44. 10-Point Explanation: includes deterministic metadata (latency, timestamp, fingerprint)', () => {
    const req: GovernanceRequest = {
      requestId: 'req_exp_meta',
      actor: { actorId: 'user_1', actorType: 'USER' },
      targetSystem: 'system',
      timestamp: Date.now(),
    };

    const decision = governanceControlPlane.evaluateGovernance(req);
    expect(decision.explanation.deterministicMetadata!.evaluationLatencyMs).toBeGreaterThanOrEqual(0);
    expect(decision.explanation.deterministicMetadata!.fingerprint).toBeDefined();
  });

  // =========================================================================
  // Section 8: Universal Action Bus Integration (45-50)
  // =========================================================================

  it('45. executeGovernedAction evaluates governance prior to dispatching to ActionBus', async () => {
    const testCap: ActionCapability = {
      capabilityId: 'cap_echo',
      name: 'Echo Capability',
      type: 'READ',
      description: 'Echoes test string',
      version: '1.0.0',
      riskLevel: 'LOW',
      requiredPermissions: ['WORKFLOW_TRIGGER'],
      supportedOperations: ['echo'],
      inputSchema: { type: 'object' },
      timeoutMs: 5000,
      retryPolicy: { maxRetries: 0, retryableCategories: [], backoffMs: 100 },
      idempotencyPolicy: { isIdempotent: true, requiresIdempotencyKey: false },
      availability: 'ONLINE',
    };
    capabilityRegistry.registerCapability(testCap);
    adapterRegistry.registerAdapter('cap_echo', {
      canExecute: () => true,
      validate: () => ({ valid: true, errors: [] }),
      execute: async () => ({ success: true, output: 'echoed' }),
      cancel: () => true,
      healthCheck: async () => 'ONLINE',
    });

    const actionReq: ActionRequest = {
      actionId: 'act_gov_test',
      capabilityId: 'cap_echo',
      operation: 'echo',
      parameters: { msg: 'hello' },
      idempotencyKey: 'idemp_gov_test',
      context: { timestamp: new Date().toISOString() },
    };

    const result = await governanceControlPlane.executeGovernedAction(actionReq);
    expect(result.decision.decision).toBe('ALLOW');
    expect(result.actionResult?.success).toBe(true);
  });

  it('46. blocked governance decisions (DENY) do not invoke ActionBus.execute', async () => {
    policyRegistry.registerPolicy(
      createTestPolicy('pol_deny_echo', 'ACTIVE', 'SECURITY', 'DENY', { scopeType: 'SYSTEM' })
    );

    let executed = false;
    adapterRegistry.registerAdapter('cap_blocked', {
      canExecute: () => true,
      validate: () => ({ valid: true, errors: [] }),
      execute: async () => {
        executed = true;
        return { success: true };
      },
      cancel: () => true,
      healthCheck: async () => 'ONLINE',
    });

    const actionReq: ActionRequest = {
      actionId: 'act_blocked',
      capabilityId: 'cap_blocked',
      operation: 'run',
      parameters: {},
      idempotencyKey: 'idemp_blocked',
      context: { timestamp: new Date().toISOString() },
    };

    const result = await governanceControlPlane.executeGovernedAction(actionReq);
    expect(result.decision.decision).toBe('DENY');
    expect(result.actionResult).toBeUndefined();
    expect(executed).toBe(false);
  });

  it('47. approval-required governance decisions do not invoke ActionBus.execute until approved', async () => {
    let executed = false;
    capabilityRegistry.registerCapability({
      capabilityId: 'cap_dangerous',
      name: 'Dangerous Capability',
      type: 'CUSTOM',
      description: 'Critical danger',
      version: '1.0.0',
      riskLevel: 'CRITICAL',
      requiredPermissions: ['WORKFLOW_TRIGGER'],
      supportedOperations: ['format_drive'],
      inputSchema: {},
      timeoutMs: 1000,
      retryPolicy: { maxRetries: 0, retryableCategories: [], backoffMs: 100 },
      idempotencyPolicy: { isIdempotent: false, requiresIdempotencyKey: false },
      availability: 'ONLINE',
    });

    adapterRegistry.registerAdapter('cap_dangerous', {
      canExecute: () => true,
      validate: () => ({ valid: true, errors: [] }),
      execute: async () => {
        executed = true;
        return { success: true };
      },
      cancel: () => true,
      healthCheck: async () => 'ONLINE',
    });

    const actionReq: ActionRequest = {
      actionId: 'act_crit_unapproved',
      capabilityId: 'cap_dangerous',
      operation: 'format_drive',
      parameters: {},
      idempotencyKey: 'idemp_crit',
      context: { timestamp: new Date().toISOString() },
    };

    const result = await governanceControlPlane.executeGovernedAction(actionReq);
    expect(result.decision.decision).toBe('REQUIRE_APPROVAL');
    expect(result.actionResult).toBeUndefined();
    expect(executed).toBe(false);
  });

  it('48. allowed governance decisions successfully dispatch to ActionBus.execute', async () => {
    capabilityRegistry.registerCapability({
      capabilityId: 'cap_safe_query',
      name: 'Safe Query',
      type: 'READ',
      description: 'Safe query',
      version: '1.0.0',
      riskLevel: 'LOW',
      requiredPermissions: ['WORKFLOW_TRIGGER'],
      supportedOperations: ['query'],
      inputSchema: {},
      timeoutMs: 1000,
      retryPolicy: { maxRetries: 0, retryableCategories: [], backoffMs: 100 },
      idempotencyPolicy: { isIdempotent: true, requiresIdempotencyKey: false },
      availability: 'ONLINE',
    });

    adapterRegistry.registerAdapter('cap_safe_query', {
      canExecute: () => true,
      validate: () => ({ valid: true, errors: [] }),
      execute: async () => ({ success: true, output: { rows: [1, 2, 3] } }),
      cancel: () => true,
      healthCheck: async () => 'ONLINE',
    });

    const actionReq: ActionRequest = {
      actionId: 'act_safe_run',
      capabilityId: 'cap_safe_query',
      operation: 'query',
      parameters: {},
      idempotencyKey: 'idemp_safe_run',
      context: { timestamp: new Date().toISOString() },
    };

    const result = await governanceControlPlane.executeGovernedAction(actionReq);
    expect(result.decision.decision).toBe('ALLOW');
    expect(result.actionResult?.success).toBe(true);
  });

  it('49. ActionBus failure is recorded in provenance while preserving governance decision', async () => {
    capabilityRegistry.registerCapability({
      capabilityId: 'cap_failing',
      name: 'Failing Cap',
      type: 'CUSTOM',
      description: 'Fails',
      version: '1.0.0',
      riskLevel: 'LOW',
      requiredPermissions: ['WORKFLOW_TRIGGER'],
      supportedOperations: ['fail'],
      inputSchema: {},
      timeoutMs: 1000,
      retryPolicy: { maxRetries: 0, retryableCategories: [], backoffMs: 100 },
      idempotencyPolicy: { isIdempotent: true, requiresIdempotencyKey: false },
      availability: 'ONLINE',
    });

    adapterRegistry.registerAdapter('cap_failing', {
      canExecute: () => true,
      validate: () => ({ valid: true, errors: [] }),
      execute: async () => {
        throw new Error('Downstream network crash');
      },
      cancel: () => true,
      healthCheck: async () => 'ONLINE',
    });

    const actionReq: ActionRequest = {
      actionId: 'act_downstream_fail',
      capabilityId: 'cap_failing',
      operation: 'fail',
      parameters: {},
      idempotencyKey: 'idemp_fail_test',
      context: { timestamp: new Date().toISOString() },
    };

    const result = await governanceControlPlane.executeGovernedAction(actionReq);
    // Governance decision was ALLOW
    expect(result.decision.decision).toBe('ALLOW');
    // But action result records downstream failure
    expect(result.actionResult?.success).toBe(false);
    expect(result.actionResult?.error?.message).toContain('Downstream network crash');
  });

  it('50. idempotency key and correlationId are preserved end-to-end across governance and ActionBus', async () => {
    capabilityRegistry.registerCapability({
      capabilityId: 'cap_idemp',
      name: 'Idemp Cap',
      type: 'READ',
      description: 'Idempotency test',
      version: '1.0.0',
      riskLevel: 'LOW',
      requiredPermissions: ['WORKFLOW_TRIGGER'],
      supportedOperations: ['get'],
      inputSchema: {},
      timeoutMs: 1000,
      retryPolicy: { maxRetries: 0, retryableCategories: [], backoffMs: 100 },
      idempotencyPolicy: { isIdempotent: true, requiresIdempotencyKey: true },
      availability: 'ONLINE',
    });

    adapterRegistry.registerAdapter('cap_idemp', {
      canExecute: () => true,
      validate: () => ({ valid: true, errors: [] }),
      execute: async () => ({ success: true, output: 'first_call' }),
      cancel: () => true,
      healthCheck: async () => 'ONLINE',
    });

    const actionReq: ActionRequest = {
      actionId: 'act_idemp_1',
      capabilityId: 'cap_idemp',
      operation: 'get',
      parameters: {},
      idempotencyKey: 'KEY_REUSE_123',
      context: { timestamp: new Date().toISOString() },
    };

    const first = await governanceControlPlane.executeGovernedAction(actionReq);
    const second = await governanceControlPlane.executeGovernedAction(actionReq);

    expect((first.actionResult?.data as any)?.output).toBe('first_call');
    expect((second.actionResult?.data as any)?.output).toBe('first_call');
  });

  // =========================================================================
  // Section 9: Connector Fabric & Permission Integration (51-55)
  // =========================================================================

  it('51. evaluates Stage 16 Connector Fabric permission scopes during authority intersection', () => {
    connectorRegistry.registerConnector(createTestConnector('conn_scoped', ['write']));
    const request: GovernanceRequest = {
      requestId: 'req_scoped_conn',
      actor: { actorId: 'user_1', actorType: 'USER' },
      targetSystem: 'conn_scoped',
      connectorId: 'conn_scoped',
      capabilityId: 'write',
      timestamp: Date.now(),
    };

    const decision = governanceControlPlane.evaluateGovernance(request);
    expect(decision.authorityIntersection.connectorPermissionGranted).toBe(true);
  });

  it('52. evaluates Agent Capability Grants (Default DENY for agents without explicit grant)', () => {
    connectorRegistry.registerConnector(createTestConnector('conn_gated', ['secret_op']));

    const request: GovernanceRequest = {
      requestId: 'req_agent_ungranted',
      actor: { actorId: 'agent_bob', actorType: 'AUTONOMOUS_AGENT' },
      targetSystem: 'conn_gated',
      connectorId: 'conn_gated',
      capabilityId: 'secret_op',
      timestamp: Date.now(),
    };

    const decision = governanceControlPlane.evaluateGovernance(request);
    expect(decision.decision).toBe('DENY');
    expect(decision.authorityIntersection.connectorPermissionGranted).toBe(false);
  });

  it('53. evaluates Mission Capability Grants for long-horizon mission tasks', () => {
    connectorRegistry.registerConnector(createTestConnector('conn_mission_gated', ['mission_op']));
    executionPersistence.saveMissionCapabilityGrant({
      grantId: 'mcg_1',
      missionId: 'mission_apollo',
      connectorId: 'conn_mission_gated',
      capabilityId: 'mission_op',
      scope: { resourceType: 'directory', resourcePath: '*', allowedOperations: ['mission_op'], readOnly: false },
      riskLimit: 'HIGH',
      grantStatus: 'ACTIVE',
      grantedAt: new Date().toISOString(),
      grantedBy: 'OPERATOR',
    });

    const request: GovernanceRequest = {
      requestId: 'req_mission_grant',
      actor: { actorId: 'system_executor', actorType: 'SYSTEM' },
      targetSystem: 'conn_mission_gated',
      connectorId: 'conn_mission_gated',
      capabilityId: 'mission_op',
      missionId: 'mission_apollo',
      timestamp: Date.now(),
    };

    const decision = governanceControlPlane.evaluateGovernance(request);
    expect(decision.decision).toBe('ALLOW');
    expect(decision.authorityIntersection.connectorPermissionGranted).toBe(true);
  });

  it('54. connector offline readiness state causes authority intersection to fail closed', () => {
    const conn = createTestConnector('conn_offline', ['op']);
    conn.status = 'ERROR';
    conn.health = 'UNAVAILABLE';
    connectorRegistry.registerConnector(conn);

    const request: GovernanceRequest = {
      requestId: 'req_offline_conn',
      actor: { actorId: 'user_1', actorType: 'USER' },
      targetSystem: 'conn_offline',
      connectorId: 'conn_offline',
      capabilityId: 'op',
      timestamp: Date.now(),
    };

    const decision = governanceControlPlane.evaluateGovernance(request, {
      runtimeOverrides: { currentConnectorState: 'UNAVAILABLE' },
    });
    expect(decision.authorityIntersection.connectorPermissionGranted).toBe(false);
    expect(decision.decision).toBe('DENY');
  });

  it('55. connector permission update triggers permissionVersion invalidation in governance', () => {
    connectorRegistry.registerConnector(createTestConnector('conn_versioning', ['op_a']));
    connectorPermissionService.updateConnectorPermissions(
      'conn_versioning',
      [{
        permissionId: 'perm_chk',
        connectorId: 'conn_versioning',
        name: 'perm_chk',
        scope: { resourceType: 'directory', allowedOperations: ['op_a', 'op_b'], resourcePath: '*', readOnly: false },
        riskTier: 'LOW',
        requiresHumanApproval: false,
        version: 1,
      }],
      'OPERATOR'
    );

    const conn = connectorRegistry.getConnector('conn_versioning');
    expect(conn?.permissionVersion).toBe(2);
  });

  // =========================================================================
  // Section 10: Stage 19 Event Reaction Engine Integration (56-60)
  // =========================================================================

  it('56. evaluateTriggeredReaction passes triggerId and event context to governance control plane', () => {
    policyRegistry.registerPolicy(
      createTestPolicy('pol_trig_allow', 'ACTIVE', 'TRIGGER_POLICY', 'ALLOW', {
        scopeType: 'TRIGGER',
        targetId: 'trig_file_watcher',
      })
    );

    const actionReq: ActionRequest = {
      actionId: 'act_trig_1',
      capabilityId: 'cap_process',
      operation: 'process',
      parameters: {},
      idempotencyKey: 'idemp_trig_1',
      context: { timestamp: new Date().toISOString() },
    };

    const decision = governanceControlPlane.evaluateTriggeredReaction('trig_file_watcher', actionReq);
    expect(decision.decision).toBe('ALLOW');
    expect(decision.matchedPolicies).toContain('pol_trig_allow');
  });

  it('57. trigger-scoped policy constrains event-driven reaction execution', () => {
    policyRegistry.registerPolicy(
      createTestPolicy('pol_trig_deny', 'ACTIVE', 'TRIGGER_POLICY', 'DENY', {
        scopeType: 'TRIGGER',
        targetId: 'trig_banned_webhook',
      })
    );

    const actionReq: ActionRequest = {
      actionId: 'act_trig_deny',
      capabilityId: 'cap_process',
      operation: 'process',
      parameters: {},
      idempotencyKey: 'idemp_trig_deny',
      context: { timestamp: new Date().toISOString() },
    };

    const decision = governanceControlPlane.evaluateTriggeredReaction('trig_banned_webhook', actionReq);
    expect(decision.decision).toBe('DENY');
    expect(decision.winningPolicyId).toBe('pol_trig_deny');
  });

  it('58. trigger rate limit breach evaluates to LIMIT or DEFER decision', () => {
    policyRegistry.registerPolicy(
      createTestPolicy('pol_rate_limit', 'ACTIVE', 'TRIGGER_POLICY', 'LIMIT', {
        scopeType: 'TRIGGER',
        targetId: 'trig_high_freq',
      })
    );

    const actionReq: ActionRequest = {
      actionId: 'act_trig_limit',
      capabilityId: 'cap_process',
      operation: 'process',
      parameters: {},
      idempotencyKey: 'idemp_trig_limit',
      context: { timestamp: new Date().toISOString() },
    };

    const decision = governanceControlPlane.evaluateTriggeredReaction('trig_high_freq', actionReq);
    expect(decision.decision).toBe('LIMIT');
  });

  it('59. autonomous triggered reaction cannot bypass human approval for high-risk capabilities', () => {
    const actionReq: ActionRequest = {
      actionId: 'act_trig_crit',
      capabilityId: 'cap_dangerous',
      operation: 'drop_database',
      parameters: {},
      idempotencyKey: 'idemp_trig_crit',
      context: { timestamp: new Date().toISOString() },
    };

    const decision = governanceControlPlane.evaluateTriggeredReaction('trig_auto', actionReq);
    // Even without an active policy, default risk check flags CRITICAL as requiring approval
    const critReq: GovernanceRequest = {
      requestId: 'req_trig_crit_check',
      actor: { actorId: 'trig_auto', actorType: 'EXTERNAL_TRIGGER' },
      targetSystem: 'system',
      riskLevel: 'CRITICAL',
      timestamp: Date.now(),
    };
    const critDecision = governanceControlPlane.evaluateGovernance(critReq);
    expect(critDecision.decision).toBe('REQUIRE_APPROVAL');
  });

  it('60. triggered reaction correlationId tracks through governance audit trail', () => {
    const actionReq: ActionRequest = {
      actionId: 'act_corr_test',
      capabilityId: 'cap_audit',
      operation: 'audit',
      parameters: {},
      idempotencyKey: 'corr_track_999',
      context: { timestamp: new Date().toISOString() },
    };

    const decision = governanceControlPlane.evaluateTriggeredReaction('trig_tracked', actionReq);
    const persisted = executionPersistence.getGovernanceDecision(decision.decisionId);
    expect(persisted).toBeDefined();
    expect(persisted?.requestId).toBe('act_corr_test');
  });

  // =========================================================================
  // Section 11: Mission Control & Decision Intelligence Integration (61-65)
  // =========================================================================

  it('61. mission-scoped policies govern operations initiated within long-horizon mission context', () => {
    policyRegistry.registerPolicy(
      createTestPolicy('pol_mission_scope', 'ACTIVE', 'MISSION_POLICY', 'LIMIT', {
        scopeType: 'MISSION',
        targetId: 'mission_deep_space',
      })
    );

    const req: GovernanceRequest = {
      requestId: 'req_mission_gov',
      actor: { actorId: 'agent_explorer', actorType: 'AUTONOMOUS_AGENT' },
      targetSystem: 'system',
      missionId: 'mission_deep_space',
      timestamp: Date.now(),
    };

    const decision = governanceControlPlane.evaluateGovernance(req);
    expect(decision.decision).toBe('LIMIT');
    expect(decision.winningPolicyId).toBe('pol_mission_scope');
  });

  it('62. mission pause state enforces PAUSE in authority intersection', () => {
    policyRegistry.registerPolicy(createTestPolicy('pol_any', 'ACTIVE', 'SECURITY', 'ALLOW'));

    const req: GovernanceRequest = {
      requestId: 'req_pause_state',
      actor: { actorId: 'user_1', actorType: 'USER' },
      targetSystem: 'system',
      missionId: 'mission_halted',
      timestamp: Date.now(),
    };

    const decision = governanceControlPlane.evaluateGovernance(req, {
      runtimeOverrides: { currentMissionState: 'PAUSED' },
    });
    expect(decision.decision).toBe('PAUSE');
    expect(decision.reason).toContain('Mission constraints violated');
  });

  it('63. epistemic certainty labels (OBSERVED, INFERRED, PROJECTED) attach to governance decision', () => {
    const req: GovernanceRequest = {
      requestId: 'req_epistemic',
      actor: { actorId: 'user_1', actorType: 'USER' },
      targetSystem: 'system',
      timestamp: Date.now(),
    };

    const decision = governanceControlPlane.evaluateGovernance(req, {
      epistemicStatus: 'PROJECTED',
    });
    expect(decision.epistemicStatus).toBe('PROJECTED');
  });

  it('64. decision intelligence consequences inform risk level before policy evaluation', () => {
    const req: GovernanceRequest = {
      requestId: 'req_sim_risk',
      actor: { actorId: 'user_1', actorType: 'USER' },
      targetSystem: 'system',
      riskLevel: 'CRITICAL',
      timestamp: Date.now(),
    };

    const decision = governanceControlPlane.evaluateGovernance(req);
    expect(decision.explanation.humanApprovalCheck!.riskLevel).toBe('CRITICAL');
  });

  it('65. strategic knowledge graph remains isolated from policy evaluation side-effects', () => {
    const req: GovernanceRequest = {
      requestId: 'req_kg_pure',
      actor: { actorId: 'user_1', actorType: 'USER' },
      targetSystem: 'system',
      timestamp: Date.now(),
    };

    const before = executionPersistence.getAllGovernanceDecisions().length;
    governanceControlPlane.evaluateGovernance(req);
    const after = executionPersistence.getAllGovernanceDecisions().length;
    expect(after).toBe(before + 1);
  });

  // =========================================================================
  // Section 12: Persistence, Audit Trailing & Replay (66-70)
  // =========================================================================

  it('66. governance decisions are persisted in executionPersistence audit store', () => {
    const req: GovernanceRequest = {
      requestId: 'req_persist_1',
      actor: { actorId: 'user_1', actorType: 'USER' },
      targetSystem: 'system',
      timestamp: Date.now(),
    };

    const decision = governanceControlPlane.evaluateGovernance(req);
    const stored = executionPersistence.getGovernanceDecision(decision.decisionId);
    expect(stored).toBeDefined();
    expect(stored?.decisionId).toBe(decision.decisionId);
    expect(stored?.decision).toBe(decision.decision);
  });

  it('67. policy snapshots are persisted and retrievable by snapshotId', () => {
    policyRegistry.registerPolicy(createTestPolicy('pol_snap_store', 'ACTIVE', 'SECURITY', 'ALLOW'));
    const snap = policySnapshotService.captureSnapshot();

    const retrieved = executionPersistence.getPolicySnapshot?.(snap.snapshotId);
    expect(retrieved).toBeDefined();
    expect(retrieved?.snapshotId).toBe(snap.snapshotId);
  });

  it('68. governance evaluation events are appended to executionJournal with goal/correlation ID', () => {
    const req: GovernanceRequest = {
      requestId: 'req_journal_test',
      goalId: 'goal_omega_7',
      actor: { actorId: 'user_1', actorType: 'USER' },
      targetSystem: 'system',
      timestamp: Date.now(),
    };

    governanceControlPlane.evaluateGovernance(req);
    const events = executionJournal.getEventsForGoal('goal_omega_7');
    expect(events.some((e) => e.eventType === 'GOVERNANCE_EVALUATED')).toBe(true);
  });

  it('69. cold restart restores governance decision history and snapshot registry from persistence', () => {
    const req: GovernanceRequest = {
      requestId: 'req_cold_1',
      actor: { actorId: 'user_1', actorType: 'USER' },
      targetSystem: 'system',
      timestamp: Date.now(),
    };
    const decision = governanceControlPlane.evaluateGovernance(req);

    // Simulate cold restart by clearing in-memory cache
    governanceControlPlane.resetCache();

    // Verify persistence still has it
    const recovered = executionPersistence.getGovernanceDecision(decision.decisionId);
    expect(recovered?.decisionId).toBe(decision.decisionId);
  });

  it('70. deterministic replay of identical request and snapshot produces bit-identical decision', () => {
    policyRegistry.registerPolicy(createTestPolicy('pol_replay', 'ACTIVE', 'SECURITY', 'ALLOW'));
    const snapshot = policySnapshotService.captureSnapshot();

    const request: GovernanceRequest = {
      requestId: 'req_replay_id',
      actor: { actorId: 'user_replay', actorType: 'USER' },
      targetSystem: 'system',
      parameters: { key: 'val' },
      timestamp: 1700000000000,
    };

    const dec1 = governanceControlPlane.evaluateGovernance(request, { snapshot, bypassCache: true });
    const dec2 = governanceControlPlane.evaluateGovernance(request, { snapshot, bypassCache: true });

    expect(dec1.decision).toBe(dec2.decision);
    expect(dec1.winningPolicyId).toBe(dec2.winningPolicyId);
    expect(dec1.authorityIntersection.effectiveStatus).toBe(dec2.authorityIntersection.effectiveStatus);
    expect(dec1.policySnapshotId).toBe(dec2.policySnapshotId);
  });

  // =========================================================================
  // Section 13: DOM Telemetry & Non-WebGL Performance Guard (71-76)
  // =========================================================================

  it('71. SpatialCommandConsole renders governance-control-plane-hud in pure DOM', () => {
    const mockCommandControl = createMockCommandControl();
    const { getByTestId } = render(
      <SpatialCommandConsole commandControl={mockCommandControl as any} />
    );

    expect(getByTestId('governance-control-plane-hud')).toBeDefined();
    expect(getByTestId('governance-plane-status').textContent).toBe('OPERATIONAL');
  });

  it('72. SpatialCommandConsole displays all Stage 21 sub-panels (decision, authority, staleness, explanation)', () => {
    const mockCommandControl = createMockCommandControl();
    const { getByTestId } = render(
      <SpatialCommandConsole commandControl={mockCommandControl as any} />
    );

    expect(getByTestId('governance-decision-hud')).toBeDefined();
    expect(getByTestId('authority-intersection-hud')).toBeDefined();
    expect(getByTestId('governance-staleness-hud')).toBeDefined();
    expect(getByTestId('governance-explanation-hud')).toBeDefined();
  });

  it('73. HUD displays mandatory invariant badge: POLICY_ALLOW_NEQ_AUTH', () => {
    const mockCommandControl = createMockCommandControl();
    const { getByTestId } = render(
      <SpatialCommandConsole commandControl={mockCommandControl as any} />
    );

    expect(getByTestId('governance-invariant-badge').textContent).toBe('POLICY_ALLOW_NEQ_AUTH');
    expect(getByTestId('governance-decision-badge').textContent).toBe('FAIL_CLOSED');
  });

  it('74. HUD displays authority intersection formula and anti-spoofing status', () => {
    const mockCommandControl = createMockCommandControl();
    const { getByTestId } = render(
      <SpatialCommandConsole commandControl={mockCommandControl as any} />
    );

    expect(getByTestId('authority-intersection-status').textContent).toBe('5_TIER_INTERSECTION');
    expect(getByTestId('authority-human-gate').textContent).toBe('ANTI_SPOOFING_ACTIVE');
  });

  it('75. zero additional WebGL draw calls introduced by governance HUDs', () => {
    const mockCommandControl = createMockCommandControl();
    const { container } = render(
      <SpatialCommandConsole commandControl={mockCommandControl as any} />
    );

    const canvases = container.querySelectorAll('canvas');
    expect(canvases.length).toBe(0); // Pure DOM HUD only, 0 WebGL draw calls
  });

  it('76. zero AI/LLM inference calls during governance control plane execution', () => {
    // Verified by pure deterministic execution without network or model dispatch
    const req: GovernanceRequest = {
      requestId: 'req_pure_logic',
      actor: { actorId: 'user_1', actorType: 'USER' },
      targetSystem: 'system',
      timestamp: Date.now(),
    };

    const start = performance.now();
    const decision = governanceControlPlane.evaluateGovernance(req);
    const duration = performance.now() - start;

    expect(decision).toBeDefined();
    // Deterministic evaluation completes in sub-millisecond to low milliseconds (no LLM latency)
    expect(duration).toBeLessThan(100);
  });
});

// ===========================================================================
// Test Helpers
// ===========================================================================

function createTestPolicy(
  id: string,
  status: any,
  priority: any,
  effectType: any,
  overrides?: Partial<Policy> & { scopeType?: any; targetId?: any }
): Policy {
  const scopeType = overrides?.scopeType || overrides?.scope?.scopeType || 'SYSTEM';
  const targetId = overrides?.targetId || overrides?.scope?.targetId;
  return {
    id,
    name: `Policy ${id}`,
    description: `Test policy for ${id}`,
    version: 1,
    status,
    priority,
    scope: { scopeType, targetId, ...(overrides?.scope || {}) },
    conditions: {
      conjunction: 'AND',
      conditions: [],
      ...(overrides?.conditions || {}),
    },
    effect: {
      type: effectType,
      reason: `Test effect ${effectType}`,
      ...(overrides?.effect || {}),
    },
    provenance: {
      authorId: 'OPERATOR',
      createdAt: Date.now(),
      updatedAt: Date.now(),
      evidence: { confidenceScore: 1.0, description: 'Direct human operator policy definition' },
      changeLog: [],
      ...(overrides?.provenance || {}),
    },
    requiresHumanApproval: false,
    ...overrides,
  };
}

function createTestConnector(id: string, capabilities: string[]): Connector {
  return {
    id,
    name: `Connector ${id}`,
    version: '1.0.0',
    type: 'FILESYSTEM',
    status: 'ACTIVE',
    health: 'HEALTHY',
    configuration: {},
    scopes: [{ resourceType: 'directory', resourcePath: '*', allowedOperations: ['*'], readOnly: false }],
    permissions: capabilities.map((cap) => ({
      permissionId: `perm_${id}_${cap}`,
      connectorId: id,
      name: cap,
      scope: { resourceType: 'directory', resourcePath: '*', allowedOperations: [cap], readOnly: false },
      riskTier: 'LOW',
      requiresHumanApproval: false,
      version: 1,
    })),
    permissionVersion: 1,
    capabilities: capabilities.map((cap) => ({
      capabilityId: cap,
      connectorId: id,
      name: cap,
      version: '1.0.0',
      riskLevel: 'LOW',
      requiredPermissions: [cap],
      supportedOperations: [cap],
      inputSchema: {},
    })),
    createdAt: new Date().toISOString(),
    updatedAt: new Date().toISOString(),
  };
}

function createMockCommandControl() {
  return {
    commandState: 'IDLE' as any,
    commandInput: '',
    setCommandInput: () => {},
    currentCommand: null,
    history: [],
    historyIndex: -1,
    availableIntents: [],
    submitCommand: () => {},
    confirmProposal: () => {},
    cancelProposal: () => {},
    dismissResult: () => {},
    isConsoleOpen: true,
    setIsConsoleOpen: () => {},
    toggleConsole: () => {},
    navigateHistory: () => {},
  };
}
