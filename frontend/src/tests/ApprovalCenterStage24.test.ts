/**
 * AryaOS V1 — Stage 24: Mission Operations Control Plane
 * Phase 4: Approval Center Projection Unit & Adversarial Test Suite
 *
 * Requirements:
 * 1. Pending approval projection
 * 2. Approved approval projection
 * 3. Rejected approval projection
 * 4. Expired approval projection
 * 5. Invalid approval projection
 * 6. Unknown approval projection
 * 7. Request ID preservation
 * 8. Policy snapshot binding
 * 9. Policy version binding
 * 10. Risk level preservation
 * 11. Actor identity preservation
 * 12. Expiration preservation
 * 13. Governance explanation preservation
 * 14. Mission context preservation
 * 15. Operation context preservation
 * 16. Recovery approval projection
 * 17. Reaction approval projection
 * 18. Policy approval projection
 * 19. Decision approval projection
 * 20. Deterministic ordering
 * 21. Filtering
 * 22. Read-only behavior
 * 23. No Action Bus execution
 * 24. No governance mutation
 * 25. No policy activation
 * 26. No recovery dispatch
 * 27. No approval mutation
 * 28. UNKNOWN preservation
 * 29. Secret scrubbing
 * 30. Prototype pollution resistance
 * 31. Malformed input handling
 * 32. Stale approval projection
 * 33. Concurrent reads
 * 34. Duplicate approval record handling
 * 35. Full integration with ControlPlaneSnapshot
 *
 * Mandatory Adversarial Cases:
 * Case A — Forged Approval (client attempts approvalState = APPROVED while backend is PENDING)
 * Case B — Stale Policy (approval references version 7 while authoritative registry uses 8)
 * Case C — Expired Approval (TTL expired, never converted to REJECTED)
 * Case D — Unknown Approval (backend cannot determine state, never coerced to PENDING)
 * Case E — Wrong Actor (autonomous agent/system actor, state INVALID, actor preserved)
 * Case F — Recovery Approval (human operator requirement projected, zero recovery dispatch)
 * Case G — Policy Approval (candidate policy projected, zero policy activation)
 * Case H — Reaction Approval (reaction proposal projected, zero reaction execution)
 * Case I — Decision Approval (consequential decision projected, zero decision execution)
 * Case J — Duplicate Event (replayed approval canonically deduplicated)
 * Case K — Different Approvals (same requestId, distinct canonical IDs and timestamps preserved)
 */

import { describe, it, expect, beforeEach, vi } from 'vitest';
import { controlPlaneSnapshotService, ApprovalFilterOptions } from '../services/controlPlaneSnapshotService';
import { executionPersistence } from '../services/executionPersistence';
import { policyRegistry } from '../services/policyRegistry';
import { reactionProposalService } from '../services/reactionProposalService';
import { actionBusService } from '../services/actionBusService';
import { governanceControlPlane } from '../services/governanceControlPlane';
import { recoveryControlPlane } from '../services/recoveryControlPlane';
import { PersistedApprovalRecord, PersistedOrchestrationEnvelope } from '../types/executionPersistence';
import { GovernanceDecision } from '../types/governanceControlPlane';
import { RecoveryControlDecision } from '../types/recoveryControl';
import { Policy } from '../types/policyIntelligence';
import { Trigger, ReactionProposal } from '../types/eventTrigger';
import { NormalizedExternalEvent } from '../types/externalEvent';

describe('AryaOS V1 — Stage 24: Phase 4 Approval Center Projection', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    executionPersistence.clearEnvelope();
    policyRegistry.reset();
    reactionProposalService.clear();
  });

  // 1. Pending approval projection
  it('1. pending approval projection accurately captures awaiting state', () => {
    const record: PersistedApprovalRecord = {
      approvalId: 'appr-req-101',
      goalId: 'goal-101',
      planId: 'plan-101',
      actionId: 'act-101',
      actionTitle: 'Deploy production hotfix',
      riskLevel: 'HIGH',
      requestedAt: '2026-10-04T08:00:00.000Z',
      status: 'PENDING',
      expiresAt: '2026-10-05T08:00:00.000Z',
    };
    executionPersistence.saveApproval(record);

    const projected = controlPlaneSnapshotService.projectApprovals(null);
    const item = projected.find((p) => p.approvalId === 'appr-req-101');

    expect(item).toBeDefined();
    expect(item?.approvalState).toBe('PENDING');
    expect(item?.actionTitle).toBe('Deploy production hotfix');
    expect(item?.riskLevel).toBe('HIGH');
  });

  // 2. Approved approval projection
  it('2. approved approval projection captures operator signoff', () => {
    const record: PersistedApprovalRecord = {
      approvalId: 'appr-req-102',
      goalId: 'goal-102',
      planId: 'plan-102',
      actionId: 'act-102',
      actionTitle: 'Authorize high-value transfer',
      riskLevel: 'CRITICAL',
      requestedAt: '2026-10-04T08:00:00.000Z',
      status: 'APPROVED',
      decidedAt: '2026-10-04T08:15:00.000Z',
      decidedBy: 'human_operator_alice',
      expiresAt: '2026-10-05T08:00:00.000Z',
    };
    executionPersistence.saveApproval(record);

    const projected = controlPlaneSnapshotService.projectApprovals(null);
    const item = projected.find((p) => p.approvalId === 'appr-req-102');

    expect(item).toBeDefined();
    expect(item?.approvalState).toBe('APPROVED');
    expect(item?.actorId).toBe('human_operator_alice');
    expect(item?.approvedAt).toBe('2026-10-04T08:15:00.000Z');
  });

  // 3. Rejected approval projection
  it('3. rejected approval projection captures rejection reason', () => {
    const record: PersistedApprovalRecord = {
      approvalId: 'appr-req-103',
      goalId: 'goal-103',
      planId: 'plan-103',
      actionId: 'act-103',
      actionTitle: 'Drop customer table',
      riskLevel: 'CRITICAL',
      requestedAt: '2026-10-04T08:00:00.000Z',
      status: 'REJECTED',
      decidedAt: '2026-10-04T08:10:00.000Z',
      decidedBy: 'human_operator_bob',
      rejectionReason: 'Exceeds allowable operational risk',
      expiresAt: '2026-10-05T08:00:00.000Z',
    };
    executionPersistence.saveApproval(record);

    const projected = controlPlaneSnapshotService.projectApprovals(null);
    const item = projected.find((p) => p.approvalId === 'appr-req-103');

    expect(item).toBeDefined();
    expect(item?.approvalState).toBe('REJECTED');
    expect(item?.reason).toBe('Exceeds allowable operational risk');
    expect(item?.rejectedAt).toBe('2026-10-04T08:10:00.000Z');
  });

  // 4. Expired approval projection
  it('4. expired approval projection preserves EXPIRED without converting to REJECTED', () => {
    const record: PersistedApprovalRecord = {
      approvalId: 'appr-req-104',
      goalId: 'goal-104',
      planId: 'plan-104',
      actionId: 'act-104',
      actionTitle: 'Ephemeral token issuance',
      riskLevel: 'MEDIUM',
      requestedAt: '2026-10-01T08:00:00.000Z',
      status: 'EXPIRED',
      expiresAt: '2026-10-01T09:00:00.000Z',
    };
    executionPersistence.saveApproval(record);

    const projected = controlPlaneSnapshotService.projectApprovals(null);
    const item = projected.find((p) => p.approvalId === 'appr-req-104');

    expect(item).toBeDefined();
    expect(item?.approvalState).toBe('EXPIRED');
    expect(item?.approvalState).not.toBe('REJECTED');
  });

  // 5. Invalid approval projection
  it('5. invalid approval projection flags forged signature as INVALID without converting to REJECTED', () => {
    const record: any = {
      approvalId: 'appr-req-105',
      goalId: 'goal-105',
      planId: 'plan-105',
      actionId: 'act-105',
      actionTitle: 'Unauthorized capability elevation',
      riskLevel: 'HIGH',
      requestedAt: '2026-10-04T08:00:00.000Z',
      status: 'APPROVED',
      decidedBy: 'human_operator_carol',
      signature: 'FORGED_SIGNATURE_ATTEMPT_XYZ',
      expiresAt: '2026-10-05T08:00:00.000Z',
    };
    executionPersistence.saveApproval(record);

    const projected = controlPlaneSnapshotService.projectApprovals(null);
    const item = projected.find((p) => p.approvalId === 'appr-req-105');

    expect(item).toBeDefined();
    expect(item?.approvalState).toBe('INVALID');
    expect(item?.approvalState).not.toBe('REJECTED');
  });

  // 6. Unknown approval projection
  it('6. unknown approval projection preserves UNKNOWN without coercing to PENDING', () => {
    const record: any = {
      approvalId: 'appr-req-106',
      goalId: 'goal-106',
      planId: 'plan-106',
      actionId: 'act-106',
      actionTitle: 'Ambiguous unclassified operation',
      riskLevel: 'LOW',
      requestedAt: '2026-10-04T08:00:00.000Z',
      status: 'AMBIGUOUS_STATE',
      expiresAt: '2026-10-05T08:00:00.000Z',
    };
    executionPersistence.saveApproval(record);

    const projected = controlPlaneSnapshotService.projectApprovals(null);
    const item = projected.find((p) => p.approvalId === 'appr-req-106');

    expect(item).toBeDefined();
    expect(item?.approvalState).toBe('UNKNOWN');
    expect(item?.approvalState).not.toBe('PENDING');
  });

  // 7. Request ID preservation
  it('7. request ID preservation faithfully reflects authoritative request/plan ID', () => {
    const record: PersistedApprovalRecord = {
      approvalId: 'appr-req-107',
      goalId: 'goal-107',
      planId: 'plan-uuid-exact-777',
      actionId: 'act-107',
      actionTitle: 'Execute safe read',
      riskLevel: 'READ_ONLY',
      requestedAt: '2026-10-04T08:00:00.000Z',
      status: 'PENDING',
      expiresAt: '2026-10-05T08:00:00.000Z',
    };
    executionPersistence.saveApproval(record);

    const projected = controlPlaneSnapshotService.projectApprovals(null);
    const item = projected.find((p) => p.approvalId === 'appr-req-107');

    expect(item?.requestId).toBe('plan-uuid-exact-777');
  });

  // 8. Policy snapshot binding
  it('8. policy snapshot binding preserves exact snapshot identifier from governance', () => {
    const govDecision: GovernanceDecision = {
      decisionId: 'gov-dec-108',
      requestId: 'req-108',
      correlationId: 'corr-108',
      policySnapshotId: 'snap-governance-bound-888',
      policyRegistryVersion: 1,
      evaluatedPolicyVersions: {},
      decision: 'REQUIRE_APPROVAL',
      reason: 'Consequential modification requires operator review',
      matchedPolicies: ['pol-sec-1'],
      conflictingPolicies: [],
      winningPolicyId: 'pol-sec-1',
      winningPriority: 'SECURITY',
      authorityIntersection: {
        effectiveStatus: 'REQUIRES_APPROVAL',
        policyAllowed: true,
        connectorPermissionGranted: true,
        actionAuthorized: false,
        humanApprovalStatus: 'PENDING',
        humanApprovalRequired: true,
        missionConstraintsSatisfied: true,
        requiredAuthority: ['production.write'],
        blockingReasons: ['Human approval required'],
        failClosed: false,
      },
      staleness: {
        isStale: false,
        status: 'FRESH',
        evaluatedSnapshotId: 'snap-governance-bound-888',
        currentRegistryVersion: 1,
        snapshotRegistryVersion: 1,
      },
      explanation: {
        whatWasRequested: 'Database migration step 3',
        snapshotUsed: 'snap-governance-bound-888',
        policiesMatched: ['pol-sec-1'],
        policiesConflicted: [],
        precedenceResolution: 'Standard priority',
        resultingPolicyDecision: 'REQUIRE_APPROVAL',
        authorityRequired: ['production.write'],
        humanApprovalRequired: true,
        approvalPresent: false,
        executingOrBlockingBoundary: 'governanceControlPlane',
        epistemicStatus: 'OBSERVED',
        humanApprovalCheck: {
          required: true,
          status: 'PENDING',
          riskLevel: 'HIGH',
        },
      },
      deterministicMetadata: {
        evaluationLatencyMs: 1,
        evaluatedAt: 1727970000000,
        cacheHit: false,
        fingerprint: 'fp-108',
      },
    };
    executionPersistence.saveGovernanceDecision(govDecision);

    const projected = controlPlaneSnapshotService.projectApprovals(null);
    const item = projected.find((p) => p.approvalId === 'gov-dec-108');

    expect(item).toBeDefined();
    expect(item?.policySnapshotId).toBe('snap-governance-bound-888');
    expect(item?.approvalState).toBe('PENDING');
  });

  // 9. Policy version binding
  it('9. policy version binding preserves exact policy registry version', () => {
    const govDecision: any = {
      decisionId: 'gov-dec-109',
      requestId: 'req-109',
      correlationId: 'corr-109',
      policySnapshotId: 'snap-109',
      policyRegistryVersion: 1,
      decision: 'REQUIRE_APPROVAL',
      reason: 'Approval required',
      authorityIntersection: {
        humanApprovalRequired: true,
        humanApprovalStatus: 'PENDING',
      },
      deterministicMetadata: {
        evaluatedAt: 1727970000000,
      },
    };
    executionPersistence.saveGovernanceDecision(govDecision);

    const projected = controlPlaneSnapshotService.projectApprovals(null);
    const item = projected.find((p) => p.approvalId === 'gov-dec-109');

    expect(item?.policyVersion).toBe(1);
  });

  // 10. Risk level preservation
  it('10. risk level preservation preserves CRITICAL/HIGH/MEDIUM/LOW/READ_ONLY faithfully', () => {
    const record: PersistedApprovalRecord = {
      approvalId: 'appr-req-110',
      goalId: 'goal-110',
      planId: 'plan-110',
      actionId: 'act-110',
      actionTitle: 'Nuclear option reset',
      riskLevel: 'CRITICAL',
      requestedAt: '2026-10-04T08:00:00.000Z',
      status: 'PENDING',
      expiresAt: '2026-10-05T08:00:00.000Z',
    };
    executionPersistence.saveApproval(record);

    const projected = controlPlaneSnapshotService.projectApprovals(null);
    const item = projected.find((p) => p.approvalId === 'appr-req-110');

    expect(item?.riskLevel).toBe('CRITICAL');
  });

  // 11. Actor identity preservation
  it('11. actor identity preservation captures human identity accurately', () => {
    const record: PersistedApprovalRecord = {
      approvalId: 'appr-req-111',
      goalId: 'goal-111',
      planId: 'plan-111',
      actionId: 'act-111',
      actionTitle: 'Manual signoff on risk assessment',
      riskLevel: 'LOW',
      requestedAt: '2026-10-04T08:00:00.000Z',
      status: 'APPROVED',
      decidedBy: 'operator_danielle@aryaos.org',
      decidedAt: '2026-10-04T08:05:00.000Z',
      expiresAt: '2026-10-05T08:00:00.000Z',
    };
    executionPersistence.saveApproval(record);

    const projected = controlPlaneSnapshotService.projectApprovals(null);
    const item = projected.find((p) => p.approvalId === 'appr-req-111');

    expect(item?.actorId).toBe('operator_danielle@aryaos.org');
  });

  // 12. Expiration preservation
  it('12. expiration preservation maintains authoritative expiration timestamp', () => {
    const expiry = '2026-10-10T12:00:00.000Z';
    const record: PersistedApprovalRecord = {
      approvalId: 'appr-req-112',
      goalId: 'goal-112',
      planId: 'plan-112',
      actionId: 'act-112',
      actionTitle: 'Grant temporary API credential',
      riskLevel: 'HIGH',
      requestedAt: '2026-10-04T08:00:00.000Z',
      status: 'PENDING',
      expiresAt: expiry,
    };
    executionPersistence.saveApproval(record);

    const projected = controlPlaneSnapshotService.projectApprovals(null);
    const item = projected.find((p) => p.approvalId === 'appr-req-112');

    expect(item?.expiresAt).toBe(expiry);
  });

  // 13. Governance explanation preservation
  it('13. governance explanation preservation retains authoritative explanation without fabricating facts', () => {
    const govDecision: any = {
      decisionId: 'gov-dec-113',
      requestId: 'req-113',
      correlationId: 'corr-113',
      policySnapshotId: 'snap-113',
      policyRegistryVersion: 1,
      decision: 'REQUIRE_APPROVAL',
      reason: 'Requires dual human authorization under Policy Sec-9',
      authorityIntersection: {
        humanApprovalRequired: true,
        humanApprovalStatus: 'PENDING',
      },
      explanation: {
        whatWasRequested: 'Access secret storage vault',
        deterministicRationale: 'High sensitivity vault access policy matched',
      },
      deterministicMetadata: {
        evaluatedAt: 1727970000000,
      },
    };
    executionPersistence.saveGovernanceDecision(govDecision);

    const projected = controlPlaneSnapshotService.projectApprovals(null);
    const item = projected.find((p) => p.approvalId === 'gov-dec-113');

    expect(item?.actionTitle).toBe('Access secret storage vault');
    expect(item?.reason).toBe('Requires dual human authorization under Policy Sec-9');
  });

  // 14. Mission context preservation
  it('14. mission context preservation enables filtering approvals by missionId', () => {
    const rec1: PersistedApprovalRecord = {
      approvalId: 'appr-mis-1',
      goalId: 'mis-alpha-001',
      planId: 'plan-1',
      actionId: 'act-1',
      actionTitle: 'Action Alpha',
      riskLevel: 'HIGH',
      requestedAt: '2026-10-04T08:00:00.000Z',
      status: 'PENDING',
      expiresAt: '2026-10-05T08:00:00.000Z',
    };
    const rec2: PersistedApprovalRecord = {
      approvalId: 'appr-mis-2',
      goalId: 'mis-beta-002',
      planId: 'plan-2',
      actionId: 'act-2',
      actionTitle: 'Action Beta',
      riskLevel: 'LOW',
      requestedAt: '2026-10-04T08:00:00.000Z',
      status: 'PENDING',
      expiresAt: '2026-10-05T08:00:00.000Z',
    };
    executionPersistence.saveApproval(rec1);
    executionPersistence.saveApproval(rec2);

    const filtered = controlPlaneSnapshotService.projectApprovals(null, { missionId: 'mis-alpha-001' });

    expect(filtered.length).toBe(1);
    expect(filtered[0].approvalId).toBe('appr-mis-1');
  });

  // 15. Operation context preservation
  it('15. operation context preservation enables filtering approvals by operationId', () => {
    const rec1: PersistedApprovalRecord = {
      approvalId: 'appr-op-1',
      goalId: 'goal-1',
      planId: 'plan-1',
      actionId: 'op-target-115',
      actionTitle: 'Operation Target Action',
      riskLevel: 'HIGH',
      requestedAt: '2026-10-04T08:00:00.000Z',
      status: 'PENDING',
      expiresAt: '2026-10-05T08:00:00.000Z',
    };
    const rec2: PersistedApprovalRecord = {
      approvalId: 'appr-op-2',
      goalId: 'goal-1',
      planId: 'plan-1',
      actionId: 'op-other-115',
      actionTitle: 'Operation Other Action',
      riskLevel: 'LOW',
      requestedAt: '2026-10-04T08:00:00.000Z',
      status: 'PENDING',
      expiresAt: '2026-10-05T08:00:00.000Z',
    };
    executionPersistence.saveApproval(rec1);
    executionPersistence.saveApproval(rec2);

    const filtered = controlPlaneSnapshotService.projectApprovals(null, { operationId: 'op-target-115' });

    expect(filtered.length).toBe(1);
    expect(filtered[0].approvalId).toBe('appr-op-1');
  });

  // 16. Recovery approval projection
  it('16. recovery approval projection captures Stage 23 human requirement without recovery dispatch', () => {
    const recoverySpy = vi.spyOn(recoveryControlPlane, 'evaluateRecoveryControl');
    const recDecision: RecoveryControlDecision = {
      decisionId: 'rec-dec-116',
      requestId: 'req-rec-116',
      operationId: 'op-rec-116',
      classification: 'UNKNOWN_EXTERNAL_STATE',
      recoveryOutcome: 'REQUIRE_APPROVAL',
      recommendedAction: 'ROLLBACK',
      governanceRequirement: {
        required: true,
        humanOperatorRequired: true,
        reason: 'Rollback of distributed transaction requires human confirmation',
      },
      requiredAuthority: ['recovery.rollback'],
      riskLevel: 'HIGH',
      epistemicStatus: 'OBSERVED',
      reasonCodes: ['HIGH_RISK_RECOVERY'],
      evidenceIds: ['ev-1'],
      causationId: 'cau-1',
      correlationId: 'corr-1',
      expiresAt: Date.now() + 600000,
      lifecycleState: 'GOVERNANCE_REQUIRED',
      recoveryDepth: 1,
      retryCount: 0,
      reconciliationAttempts: 0,
      createdAt: 1727970000000,
    };
    executionPersistence.saveRecoveryControlDecision(recDecision);

    const projected = controlPlaneSnapshotService.projectApprovals(null);
    const item = projected.find((p) => p.approvalId === 'rec-dec-116');

    expect(item).toBeDefined();
    expect(item?.approvalState).toBe('PENDING');
    expect(item?.actionTitle).toBe('Recovery: ROLLBACK');
    expect(recoverySpy).toHaveBeenCalledTimes(0);
  });

  // 17. Reaction approval projection
  it('17. reaction approval projection captures Stage 19 human approval without reaction execution', () => {
    const trigger: Trigger = {
      triggerId: 'trig-117',
      name: 'High Risk Reaction',
      version: 1,
      eventFilter: { eventType: 'SECURITY_ALERT' },
      reaction: {
        reactionType: 'REQUEST_HUMAN_APPROVAL',
        actionIntent: { capabilityId: 'cap-shutdown', operation: 'shutdown', parameters: { targetService: 'auth-gateway' } },
      },
      riskLevel: 'HIGH',
      authorizationPolicy: {
        requiresHumanApproval: true,
        requiredPermissions: ['security.admin'],
      },
      status: 'ACTIVE',
      createdAt: '2026-10-04T08:00:00.000Z',
      updatedAt: '2026-10-04T08:00:00.000Z',
    };
    const event: any = {
      normalizedEventId: 'norm-ev-117',
      originalEventId: 'orig-ev-117',
      connectorId: 'conn-sec',
      sourceSystem: 'WEBHOOK',
      resourceType: 'SECURITY_ALERT',
      resourceId: 'res-117',
      changeType: 'DETECTED',
      data: { threat: 'critical' },
      timestamp: '2026-10-04T08:00:00.000Z',
      ingestedAt: '2026-10-04T08:00:00.000Z',
      signatureValid: true,
      deduplicationKey: 'dedup-117',
      processingStatus: 'NORMALIZED',
    };

    const prop = reactionProposalService.createProposal(trigger, event, {});
    expect(prop.status).toBe('AWAITING_APPROVAL');

    const projected = controlPlaneSnapshotService.projectApprovals(null);
    const item = projected.find((p) => p.approvalId === prop.proposalId);

    expect(item).toBeDefined();
    expect(item?.approvalState).toBe('PENDING');
    expect(item?.actionTitle).toBe('REQUEST_HUMAN_APPROVAL');
  });

  // 18. Policy approval projection
  it('18. policy approval projection captures Stage 20 policy review candidates without activation', () => {
    const candidatePolicy: Policy = {
      id: 'pol-candidate-118',
      name: 'Restrict Egress Bandwidth',
      description: 'Limits outbound network data for unknown destinations',
      status: 'CANDIDATE',
      scope: { scopeType: 'SYSTEM' },
      priority: 'SECURITY',
      effect: { type: 'ALLOW' },
      conditions: { conjunction: 'AND', conditions: [] },
      version: 1,
      requiresHumanApproval: true,
      provenance: {
        authorId: 'policy_architect_eve',
        createdAt: 1727970000000,
        updatedAt: 1727970000000,
        evidence: { confidenceScore: 1, description: 'Test' },
        changeLog: [],
      },
    };
    policyRegistry.registerPolicy(candidatePolicy);

    const projected = controlPlaneSnapshotService.projectApprovals(null);
    const item = projected.find((p) => p.approvalId === 'policy_appr_pol-candidate-118');

    expect(item).toBeDefined();
    expect(item?.approvalState).toBe('PENDING');
    expect(item?.actionTitle).toBe('Restrict Egress Bandwidth');
    expect(policyRegistry.getPolicy('pol-candidate-118')?.status).toBe('CANDIDATE');
  });

  // 19. Decision approval projection
  it('19. decision approval projection captures consequential decision review without decision execution', () => {
    const envelope = executionPersistence.loadEnvelope() || (executionPersistence as any).createDefaultEnvelope();
    envelope.decisions = {
      'dec-119': {
        id: 'dec-119',
        title: 'Migrate Primary Datastore',
        description: 'Cutover traffic to secondary replicated cluster',
        status: 'AWAITING_REVIEW',
        priority: 'CRITICAL',
        createdAt: '2026-10-04T08:00:00.000Z',
        approval: {
          approvalId: 'dec-appr-119',
          status: 'AWAITING_REVIEW',
          requiresHumanApproval: true,
        },
        provenance: {
          missionId: 'mis-infra-1',
          goalId: 'goal-infra-1',
        },
      },
    };
    executionPersistence.saveEnvelope(envelope);

    const projected = controlPlaneSnapshotService.projectApprovals(null);
    const item = projected.find((p) => p.approvalId === 'dec-appr-119');

    expect(item).toBeDefined();
    expect(item?.approvalState).toBe('PENDING');
    expect(item?.actionTitle).toBe('Migrate Primary Datastore');
    expect(item?.riskLevel).toBe('CRITICAL');
  });

  // 20. Deterministic ordering
  it('20. deterministic ordering sorts strictly by timestamp ascending, then sequence, then approvalId', () => {
    const recA: PersistedApprovalRecord = {
      approvalId: 'appr-time-200',
      goalId: 'goal-1',
      planId: 'plan-1',
      actionId: 'act-1',
      actionTitle: 'Action 200',
      riskLevel: 'LOW',
      requestedAt: '2026-10-04T12:00:00.000Z',
      status: 'PENDING',
      expiresAt: '2026-10-05T08:00:00.000Z',
    };
    const recB: PersistedApprovalRecord = {
      approvalId: 'appr-time-100',
      goalId: 'goal-1',
      planId: 'plan-1',
      actionId: 'act-1',
      actionTitle: 'Action 100',
      riskLevel: 'LOW',
      requestedAt: '2026-10-04T08:00:00.000Z',
      status: 'PENDING',
      expiresAt: '2026-10-05T08:00:00.000Z',
    };
    const recC: PersistedApprovalRecord = {
      approvalId: 'appr-time-100-alpha',
      goalId: 'goal-1',
      planId: 'plan-1',
      actionId: 'act-1',
      actionTitle: 'Action 100 Alpha',
      riskLevel: 'LOW',
      requestedAt: '2026-10-04T08:00:00.000Z',
      status: 'PENDING',
      expiresAt: '2026-10-05T08:00:00.000Z',
    };
    executionPersistence.saveApproval(recA);
    executionPersistence.saveApproval(recB);
    executionPersistence.saveApproval(recC);

    const projected = controlPlaneSnapshotService.projectApprovals(null);
    const ids = projected.map((p) => p.approvalId);

    // recB and recC share timestamp 08:00:00. Lexical tie-break: appr-time-100 comes before appr-time-100-alpha.
    // recA has 12:00:00 so it comes last.
    expect(ids.indexOf('appr-time-100')).toBeLessThan(ids.indexOf('appr-time-100-alpha'));
    expect(ids.indexOf('appr-time-100-alpha')).toBeLessThan(ids.indexOf('appr-time-200'));
  });

  // 21. Filtering
  it('21. filtering correctly applies riskLevel, approvalState, actorId, requestId, and maxApprovals', () => {
    const records: PersistedApprovalRecord[] = [
      {
        approvalId: 'appr-filter-1',
        goalId: 'goal-1',
        planId: 'plan-target',
        actionId: 'act-1',
        actionTitle: 'Action 1',
        riskLevel: 'CRITICAL',
        requestedAt: '2026-10-04T08:00:00.000Z',
        status: 'PENDING',
        expiresAt: '2026-10-05T08:00:00.000Z',
      },
      {
        approvalId: 'appr-filter-2',
        goalId: 'goal-1',
        planId: 'plan-target',
        actionId: 'act-2',
        actionTitle: 'Action 2',
        riskLevel: 'HIGH',
        requestedAt: '2026-10-04T08:01:00.000Z',
        status: 'APPROVED',
        decidedBy: 'human_operator_charlie',
        expiresAt: '2026-10-05T08:00:00.000Z',
      },
      {
        approvalId: 'appr-filter-3',
        goalId: 'goal-1',
        planId: 'plan-other',
        actionId: 'act-3',
        actionTitle: 'Action 3',
        riskLevel: 'CRITICAL',
        requestedAt: '2026-10-04T08:02:00.000Z',
        status: 'PENDING',
        expiresAt: '2026-10-05T08:00:00.000Z',
      },
    ];
    records.forEach((r) => executionPersistence.saveApproval(r));

    // Filter by riskLevel
    const criticalOnly = controlPlaneSnapshotService.projectApprovals(null, { riskLevel: 'CRITICAL' });
    expect(criticalOnly.every((a) => a.riskLevel === 'CRITICAL')).toBe(true);

    // Filter by approvalState
    const approvedOnly = controlPlaneSnapshotService.projectApprovals(null, { approvalState: 'APPROVED' });
    expect(approvedOnly.length).toBe(1);
    expect(approvedOnly[0].approvalId).toBe('appr-filter-2');

    // Filter by requestId
    const planTargetOnly = controlPlaneSnapshotService.projectApprovals(null, { requestId: 'plan-target' });
    expect(planTargetOnly.length).toBe(2);

    // Filter by maxApprovals
    const limited = controlPlaneSnapshotService.projectApprovals(null, { maxApprovals: 1 });
    expect(limited.length).toBe(1);
  });

  // 22. Read-only behavior
  it('22. read-only behavior: returns deeply frozen objects that cannot be mutated', () => {
    const record: PersistedApprovalRecord = {
      approvalId: 'appr-imm-122',
      goalId: 'goal-1',
      planId: 'plan-1',
      actionId: 'act-1',
      actionTitle: 'Immutable record',
      riskLevel: 'LOW',
      requestedAt: '2026-10-04T08:00:00.000Z',
      status: 'PENDING',
      expiresAt: '2026-10-05T08:00:00.000Z',
    };
    executionPersistence.saveApproval(record);

    const projected = controlPlaneSnapshotService.projectApprovals(null);
    expect(Object.isFrozen(projected)).toBe(true);
    expect(Object.isFrozen(projected[0])).toBe(true);

    expect(() => {
      (projected as any)[0].approvalState = 'APPROVED';
    }).toThrow();
  });

  // 23. No Action Bus execution
  it('23. no Action Bus execution: projection NEVER calls actionBusService.execute', () => {
    const spy = vi.spyOn(actionBusService, 'execute');
    controlPlaneSnapshotService.projectApprovals(null);
    expect(spy).toHaveBeenCalledTimes(0);
  });

  // 24. No governance mutation
  it('24. no governance mutation: projection NEVER calls governance evaluation or modification', () => {
    const spy = vi.spyOn(governanceControlPlane, 'evaluateGovernance');
    controlPlaneSnapshotService.projectApprovals(null);
    expect(spy).toHaveBeenCalledTimes(0);
  });

  // 25. No policy activation
  it('25. no policy activation: projection NEVER mutates policy status in policyRegistry', () => {
    const policySpy = vi.spyOn(policyRegistry, 'transitionStatus');
    controlPlaneSnapshotService.projectApprovals(null);
    expect(policySpy).toHaveBeenCalledTimes(0);
  });

  // 26. No recovery dispatch
  it('26. no recovery dispatch: projection NEVER dispatches or executes recovery plans', () => {
    const recSpy = vi.spyOn(recoveryControlPlane, 'evaluateRecoveryControl');
    controlPlaneSnapshotService.projectApprovals(null);
    expect(recSpy).toHaveBeenCalledTimes(0);
  });

  // 27. No approval mutation
  it('27. no approval mutation: projection leaves backend persistence completely unchanged', () => {
    const record: PersistedApprovalRecord = {
      approvalId: 'appr-untouchable-127',
      goalId: 'goal-1',
      planId: 'plan-1',
      actionId: 'act-1',
      actionTitle: 'Untouchable Record',
      riskLevel: 'HIGH',
      requestedAt: '2026-10-04T08:00:00.000Z',
      status: 'PENDING',
      expiresAt: '2026-10-05T08:00:00.000Z',
    };
    executionPersistence.saveApproval(record);

    controlPlaneSnapshotService.projectApprovals(null);

    const envelope = executionPersistence.loadEnvelope();
    expect(envelope?.approvals?.['appr-untouchable-127']?.status).toBe('PENDING');
  });

  // 28. UNKNOWN preservation
  it('28. UNKNOWN preservation: missing or ambiguous state is never coerced to synthetic defaults', () => {
    const rawRecord: any = {
      approvalId: 'appr-unknown-128',
      goalId: 'goal-1',
      planId: 'plan-1',
      actionId: 'act-1',
      actionTitle: 'Unknown state action',
      riskLevel: 'LOW',
      requestedAt: '2026-10-04T08:00:00.000Z',
      status: undefined,
      expiresAt: '2026-10-05T08:00:00.000Z',
    };
    executionPersistence.saveApproval(rawRecord);

    const projected = controlPlaneSnapshotService.projectApprovals(null);
    const item = projected.find((p) => p.approvalId === 'appr-unknown-128');

    expect(item?.approvalState).toBe('UNKNOWN');
    expect(item?.approvalState).not.toBe('PENDING');
    expect(item?.approvalState).not.toBe('APPROVED');
    expect(item?.approvalState).not.toBe('REJECTED');
  });

  // 29. Secret scrubbing
  it('29. secret scrubbing redacts bearer tokens, api keys, and passwords from actionTitle and reason', () => {
    const record: PersistedApprovalRecord = {
      approvalId: 'appr-scrub-129',
      goalId: 'goal-1',
      planId: 'plan-1',
      actionId: 'act-1',
      actionTitle: 'Deploy with Bearer supersecrettoken123 and api_key=topsecretkey456',
      riskLevel: 'CRITICAL',
      requestedAt: '2026-10-04T08:00:00.000Z',
      status: 'REJECTED',
      rejectionReason: 'Failed verification: password=supersecretpass and sk-proj0123456789abcdef leaked',
      expiresAt: '2026-10-05T08:00:00.000Z',
    };
    executionPersistence.saveApproval(record);

    const projected = controlPlaneSnapshotService.projectApprovals(null);
    const item = projected.find((p) => p.approvalId === 'appr-scrub-129');

    expect(item).toBeDefined();
    expect(item?.actionTitle).not.toContain('supersecrettoken123');
    expect(item?.actionTitle).not.toContain('topsecretkey456');
    expect(item?.actionTitle).toContain('[REDACTED');

    expect(item?.reason).not.toContain('supersecretpass');
    expect(item?.reason).not.toContain('sk-proj0123456789abcdef');
    expect(item?.reason).toContain('[REDACTED');
  });

  // 30. Prototype pollution resistance
  it('30. prototype pollution resistance ignores __proto__ and constructor injection in filter options', () => {
    const maliciousFilter: any = JSON.parse(
      '{"__proto__":{"polluted":"yes"},"constructor":{"prototype":{"polluted":"yes"}},"riskLevel":"HIGH"}'
    );

    const projected = controlPlaneSnapshotService.projectApprovals(null, maliciousFilter);

    expect((Object.prototype as any).polluted).toBeUndefined();
    expect(Array.isArray(projected)).toBe(true);
  });

  // 31. Malformed input handling
  it('31. malformed input handling gracefully absorbs null, undefined, and corrupted inputs', () => {
    expect(() => controlPlaneSnapshotService.projectApprovals(null)).not.toThrow();
    expect(() => controlPlaneSnapshotService.projectApprovals({} as any)).not.toThrow();
    expect(() => controlPlaneSnapshotService.projectApprovals({ approvals: null } as any)).not.toThrow();
    expect(() => controlPlaneSnapshotService.projectApprovals(null, 'not an object' as any)).not.toThrow();
  });

  // 32. Stale approval projection
  it('32. stale approval projection flags policy version mismatch as INVALID', () => {
    const govDecision: any = {
      decisionId: 'gov-stale-132',
      requestId: 'req-stale-132',
      correlationId: 'corr-132',
      policySnapshotId: 'snap-stale-132',
      policyRegistryVersion: 1,
      decision: 'REQUIRE_APPROVAL',
      reason: 'Requires approval',
      staleness: {
        isStale: true,
        status: 'STALE_APPROVAL',
        evaluatedSnapshotId: 'snap-stale-132',
        currentRegistryVersion: 2,
        snapshotRegistryVersion: 1,
      },
      authorityIntersection: {
        humanApprovalRequired: true,
        humanApprovalStatus: 'STALE',
      },
      deterministicMetadata: {
        evaluatedAt: 1727970000000,
      },
    };
    executionPersistence.saveGovernanceDecision(govDecision);

    const projected = controlPlaneSnapshotService.projectApprovals(null);
    const item = projected.find((p) => p.approvalId === 'gov-stale-132');

    expect(item).toBeDefined();
    expect(item?.approvalState).toBe('INVALID');
    expect(item?.approvalState).not.toBe('REJECTED');
  });

  // 33. Concurrent reads
  it('33. concurrent reads return identical frozen snapshots without race conditions', async () => {
    const record: PersistedApprovalRecord = {
      approvalId: 'appr-conc-133',
      goalId: 'goal-1',
      planId: 'plan-1',
      actionId: 'act-1',
      actionTitle: 'Concurrent action',
      riskLevel: 'LOW',
      requestedAt: '2026-10-04T08:00:00.000Z',
      status: 'PENDING',
      expiresAt: '2026-10-05T08:00:00.000Z',
    };
    executionPersistence.saveApproval(record);

    const promises = Array.from({ length: 10 }, () =>
      Promise.resolve(controlPlaneSnapshotService.projectApprovals(null))
    );
    const results = await Promise.all(promises);

    for (let i = 1; i < results.length; i++) {
      expect(results[i]).toEqual(results[0]);
    }
  });

  // 34. Duplicate approval record handling
  it('34. duplicate approval record handling canonically deduplicates replayed events', () => {
    const envelope = executionPersistence.loadEnvelope() || (executionPersistence as any).createDefaultEnvelope();
    envelope.approvals = {
      'appr-dup-1': {
        approvalId: 'appr-dup-1',
        goalId: 'goal-1',
        planId: 'plan-1',
        actionId: 'act-1',
        actionTitle: 'Canonical event',
        riskLevel: 'HIGH',
        requestedAt: '2026-10-04T08:00:00.000Z',
        status: 'PENDING',
        expiresAt: '2026-10-05T08:00:00.000Z',
      },
    };
    executionPersistence.saveEnvelope(envelope);

    const projected = controlPlaneSnapshotService.projectApprovals(null);
    const duplicates = projected.filter((p) => p.approvalId === 'appr-dup-1');

    expect(duplicates.length).toBe(1);
  });

  // 35. Full integration with ControlPlaneSnapshot
  it('35. full integration with ControlPlaneSnapshot includes approvals projection', () => {
    const record: PersistedApprovalRecord = {
      approvalId: 'appr-snapshot-135',
      goalId: 'goal-135',
      planId: 'plan-135',
      actionId: 'act-135',
      actionTitle: 'Control plane top-level integration',
      riskLevel: 'MEDIUM',
      requestedAt: '2026-10-04T08:00:00.000Z',
      status: 'PENDING',
      expiresAt: '2026-10-05T08:00:00.000Z',
    };
    executionPersistence.saveApproval(record);

    const snapshot = controlPlaneSnapshotService.getSnapshot();
    const item = snapshot.approvals.find((a) => a.approvalId === 'appr-snapshot-135');

    expect(item).toBeDefined();
    expect(item?.approvalState).toBe('PENDING');
    expect(item?.actionTitle).toBe('Control plane top-level integration');
  });

  // ============================================================================
  // MANDATORY ADVERSARIAL CASES A THROUGH K
  // ============================================================================

  // CASE A — FORGED APPROVAL
  it('Case A: client-supplied approvalState = APPROVED cannot alter backend PENDING state', () => {
    const record: PersistedApprovalRecord = {
      approvalId: 'appr-adv-a',
      goalId: 'goal-a',
      planId: 'plan-a',
      actionId: 'act-a',
      actionTitle: 'Sensitive production operation',
      riskLevel: 'CRITICAL',
      requestedAt: '2026-10-04T08:00:00.000Z',
      status: 'PENDING',
      expiresAt: '2026-10-05T08:00:00.000Z',
    };
    executionPersistence.saveApproval(record);

    // Client passes approvalState = 'APPROVED' as a filter or mock override attempt
    const projected = controlPlaneSnapshotService.projectApprovals(null, { approvalState: 'APPROVED' });

    // The backend record is PENDING, so filtering for APPROVED returns 0 records.
    expect(projected.find((p) => p.approvalId === 'appr-adv-a')).toBeUndefined();

    // Direct read without filter proves backend remains truthfully PENDING
    const full = controlPlaneSnapshotService.projectApprovals(null);
    const item = full.find((p) => p.approvalId === 'appr-adv-a');
    expect(item?.approvalState).toBe('PENDING');
  });

  // CASE B — STALE POLICY
  it('Case B: approval referencing policy version 7 when current registry is 8 is classified as INVALID', () => {
    // Current registry is at version 1. Let's register a few policies to advance version to 8.
    for (let v = 1; v <= 7; v++) {
      policyRegistry.registerPolicy({
        id: `pol-version-adv-${v}`,
        name: `Version Policy ${v}`,
        description: `Version test policy ${v}`,
        status: 'ACTIVE',
        scope: { scopeType: 'SYSTEM' },
        priority: 'SECURITY',
        effect: { type: 'ALLOW' },
        conditions: { conjunction: 'AND', conditions: [] },
        version: 1,
        requiresHumanApproval: false,
        provenance: {
          authorId: 'admin',
          createdAt: 1727970000000,
          updatedAt: 1727970000000,
          evidence: { confidenceScore: 1, description: 'Test' },
          changeLog: [],
        },
      });
    }

    const currentRegVersion = policyRegistry.getRegistryVersion();
    expect(currentRegVersion).toBeGreaterThan(7);

    // Governance decision created under older policy version 7
    const staleDecision: any = {
      decisionId: 'gov-adv-b',
      requestId: 'req-adv-b',
      correlationId: 'corr-adv-b',
      policySnapshotId: 'snap-adv-b',
      policyRegistryVersion: 7, // Stale relative to current
      decision: 'REQUIRE_APPROVAL',
      reason: 'Requires approval under older policy version',
      authorityIntersection: {
        humanApprovalRequired: true,
        humanApprovalStatus: 'PENDING',
      },
      deterministicMetadata: {
        evaluatedAt: 1727970000000,
      },
    };
    executionPersistence.saveGovernanceDecision(staleDecision);

    const projected = controlPlaneSnapshotService.projectApprovals(null);
    const item = projected.find((p) => p.approvalId === 'gov-adv-b');

    expect(item).toBeDefined();
    expect(item?.approvalState).toBe('INVALID');
    expect(item?.approvalState).not.toBe('APPROVED');
  });

  // CASE C — EXPIRED APPROVAL
  it('Case C: approval TTL has expired -> EXPIRED, never converted to REJECTED', () => {
    const record: PersistedApprovalRecord = {
      approvalId: 'appr-adv-c',
      goalId: 'goal-c',
      planId: 'plan-c',
      actionId: 'act-c',
      actionTitle: 'Time-bounded permission grant',
      riskLevel: 'HIGH',
      requestedAt: '2026-10-01T08:00:00.000Z',
      status: 'EXPIRED',
      expiresAt: '2026-10-01T09:00:00.000Z',
    };
    executionPersistence.saveApproval(record);

    const projected = controlPlaneSnapshotService.projectApprovals(null);
    const item = projected.find((p) => p.approvalId === 'appr-adv-c');

    expect(item?.approvalState).toBe('EXPIRED');
    expect(item?.approvalState).not.toBe('REJECTED');
  });

  // CASE D — UNKNOWN APPROVAL
  it('Case D: backend cannot determine state -> UNKNOWN, never coerced to PENDING', () => {
    const rawRecord: any = {
      approvalId: 'appr-adv-d',
      goalId: 'goal-d',
      planId: 'plan-d',
      actionId: 'act-d',
      actionTitle: 'Unverifiable state action',
      riskLevel: 'LOW',
      requestedAt: '2026-10-04T08:00:00.000Z',
      status: 'UNKNOWN_STATUS_FROM_CORRUPT_JOURNAL',
      expiresAt: '2026-10-05T08:00:00.000Z',
    };
    executionPersistence.saveApproval(rawRecord);

    const projected = controlPlaneSnapshotService.projectApprovals(null);
    const item = projected.find((p) => p.approvalId === 'appr-adv-d');

    expect(item?.approvalState).toBe('UNKNOWN');
    expect(item?.approvalState).not.toBe('PENDING');
  });

  // CASE E — WRONG ACTOR
  it('Case E: approval granted by non-human actor (AUTONOMOUS_AGENT) is classified as INVALID, preserving actor identity', () => {
    const record: PersistedApprovalRecord = {
      approvalId: 'appr-adv-e',
      goalId: 'goal-e',
      planId: 'plan-e',
      actionId: 'act-e',
      actionTitle: 'Autonomous agent self-approval attempt',
      riskLevel: 'CRITICAL',
      requestedAt: '2026-10-04T08:00:00.000Z',
      status: 'APPROVED',
      decidedBy: 'AUTONOMOUS_AGENT_ROBOT_42',
      decidedAt: '2026-10-04T08:01:00.000Z',
      expiresAt: '2026-10-05T08:00:00.000Z',
    };
    executionPersistence.saveApproval(record);

    const projected = controlPlaneSnapshotService.projectApprovals(null);
    const item = projected.find((p) => p.approvalId === 'appr-adv-e');

    expect(item).toBeDefined();
    expect(item?.actorId).toBe('AUTONOMOUS_AGENT_ROBOT_42');
    expect(item?.approvalState).toBe('INVALID');
    expect(item?.approvalState).not.toBe('APPROVED');
  });

  // CASE F — RECOVERY APPROVAL
  it('Case F: recovery requires human approval -> projected as PENDING without recovery dispatch', () => {
    const recoverySpy = vi.spyOn(recoveryControlPlane, 'evaluateRecoveryControl');
    const recDecision: RecoveryControlDecision = {
      decisionId: 'rec-adv-f',
      requestId: 'req-rec-f',
      operationId: 'op-rec-f',
      classification: 'TRANSIENT',
      recoveryOutcome: 'REQUIRE_APPROVAL',
      recommendedAction: 'RETRY',
      governanceRequirement: {
        required: true,
        humanOperatorRequired: true,
        reason: 'Retry limit reached; manual approval required',
      },
      requiredAuthority: ['recovery.retry'],
      riskLevel: 'MEDIUM',
      epistemicStatus: 'OBSERVED',
      reasonCodes: ['RETRY_LIMIT'],
      evidenceIds: [],
      causationId: 'cau-f',
      correlationId: 'corr-f',
      expiresAt: Date.now() + 600000,
      lifecycleState: 'GOVERNANCE_REQUIRED',
      recoveryDepth: 1,
      retryCount: 2,
      reconciliationAttempts: 0,
      createdAt: 1727970000000,
    };
    executionPersistence.saveRecoveryControlDecision(recDecision);

    const projected = controlPlaneSnapshotService.projectApprovals(null);
    const item = projected.find((p) => p.approvalId === 'rec-adv-f');

    expect(item).toBeDefined();
    expect(item?.approvalState).toBe('PENDING');
    expect(recoverySpy).toHaveBeenCalledTimes(0);
  });

  // CASE G — POLICY APPROVAL
  it('Case G: policy candidate requires approval -> projected as PENDING without policy activation', () => {
    const pol: Policy = {
      id: 'pol-adv-g',
      name: 'Restricted DB Query',
      description: 'Candidate policy requiring operator signoff',
      status: 'UNDER_REVIEW',
      scope: { scopeType: 'SYSTEM' },
      priority: 'SECURITY',
      effect: { type: 'LIMIT' },
      conditions: { conjunction: 'AND', conditions: [] },
      version: 1,
      requiresHumanApproval: true,
      provenance: {
        authorId: 'policy_author_frank',
        createdAt: 1727970000000,
        updatedAt: 1727970000000,
        evidence: { confidenceScore: 1, description: 'Test' },
        changeLog: [],
      },
    };
    policyRegistry.registerPolicy(pol);

    const projected = controlPlaneSnapshotService.projectApprovals(null);
    const item = projected.find((p) => p.approvalId === 'policy_appr_pol-adv-g');

    expect(item).toBeDefined();
    expect(item?.approvalState).toBe('PENDING');
    expect(policyRegistry.getPolicy('pol-adv-g')?.status).toBe('UNDER_REVIEW');
  });

  // CASE H — REACTION APPROVAL
  it('Case H: reaction requires approval -> projected as PENDING without reaction execution', () => {
    const trigger: Trigger = {
      triggerId: 'trig-adv-h',
      name: 'Consequential Reaction Trigger',
      version: 1,
      eventFilter: { eventType: 'DATABASE_CORRUPTION' },
      reaction: {
        reactionType: 'REQUEST_HUMAN_APPROVAL',
      },
      riskLevel: 'CRITICAL',
      authorizationPolicy: {
        requiresHumanApproval: true,
        requiredPermissions: ['db.admin'],
      },
      status: 'ACTIVE',
      createdAt: '2026-10-04T08:00:00.000Z',
      updatedAt: '2026-10-04T08:00:00.000Z',
    };
    const event: any = {
      normalizedEventId: 'norm-ev-h',
      originalEventId: 'orig-ev-h',
      connectorId: 'conn-db',
      sourceSystem: 'WEBHOOK',
      resourceType: 'DATABASE',
      resourceId: 'res-ledger',
      changeType: 'CORRUPTED',
      data: { table: 'ledger' },
      timestamp: '2026-10-04T08:00:00.000Z',
      ingestedAt: '2026-10-04T08:00:00.000Z',
      signatureValid: true,
      deduplicationKey: 'dedup-h',
      processingStatus: 'NORMALIZED',
    };

    const prop = reactionProposalService.createProposal(trigger, event, {});

    const projected = controlPlaneSnapshotService.projectApprovals(null);
    const item = projected.find((p) => p.approvalId === prop.proposalId);

    expect(item).toBeDefined();
    expect(item?.approvalState).toBe('PENDING');
    expect(item?.actionTitle).toBe('REQUEST_HUMAN_APPROVAL');
  });

  // CASE I — DECISION APPROVAL
  it('Case I: consequential decision requires approval -> projected as PENDING without decision execution', () => {
    const envelope = executionPersistence.loadEnvelope() || (executionPersistence as any).createDefaultEnvelope();
    envelope.decisions = {
      'dec-adv-i': {
        id: 'dec-adv-i',
        title: 'Major Cluster Migration',
        description: 'Rebalance storage nodes across regions',
        status: 'AWAITING_REVIEW',
        priority: 'CRITICAL',
        createdAt: '2026-10-04T08:00:00.000Z',
        approval: {
          approvalId: 'dec-appr-adv-i',
          status: 'AWAITING_REVIEW',
          requiresHumanApproval: true,
        },
        provenance: {
          missionId: 'mis-storage',
          goalId: 'goal-storage',
        },
      },
    };
    executionPersistence.saveEnvelope(envelope);

    const projected = controlPlaneSnapshotService.projectApprovals(null);
    const item = projected.find((p) => p.approvalId === 'dec-appr-adv-i');

    expect(item).toBeDefined();
    expect(item?.approvalState).toBe('PENDING');
    expect(item?.actionTitle).toBe('Major Cluster Migration');
  });

  // CASE J — DUPLICATE EVENT
  it('Case J: replayed approval event is canonically deduplicated', () => {
    const record: PersistedApprovalRecord = {
      approvalId: 'appr-adv-j-replay',
      goalId: 'goal-j',
      planId: 'plan-j',
      actionId: 'act-j',
      actionTitle: 'Single idempotent approval',
      riskLevel: 'HIGH',
      requestedAt: '2026-10-04T08:00:00.000Z',
      status: 'PENDING',
      expiresAt: '2026-10-05T08:00:00.000Z',
    };

    // Save once
    executionPersistence.saveApproval(record);
    // Replay / save same approvalId again
    executionPersistence.saveApproval(record);

    const projected = controlPlaneSnapshotService.projectApprovals(null);
    const count = projected.filter((p) => p.approvalId === 'appr-adv-j-replay').length;

    expect(count).toBe(1);
  });

  // CASE K — DIFFERENT APPROVALS
  it('Case K: two approvals with same request but different canonical IDs and timestamps are preserved distinctly', () => {
    const rec1: PersistedApprovalRecord = {
      approvalId: 'appr-adv-k-first',
      goalId: 'goal-k',
      planId: 'req-shared-k',
      actionId: 'act-k-1',
      actionTitle: 'First Attempt at Request',
      riskLevel: 'HIGH',
      requestedAt: '2026-10-04T08:00:00.000Z',
      status: 'REJECTED',
      expiresAt: '2026-10-05T08:00:00.000Z',
    };
    const rec2: PersistedApprovalRecord = {
      approvalId: 'appr-adv-k-second',
      goalId: 'goal-k',
      planId: 'req-shared-k',
      actionId: 'act-k-2',
      actionTitle: 'Second Revised Attempt at Request',
      riskLevel: 'HIGH',
      requestedAt: '2026-10-04T09:00:00.000Z',
      status: 'PENDING',
      expiresAt: '2026-10-05T08:00:00.000Z',
    };

    executionPersistence.saveApproval(rec1);
    executionPersistence.saveApproval(rec2);

    const projected = controlPlaneSnapshotService.projectApprovals(null);
    const first = projected.find((p) => p.approvalId === 'appr-adv-k-first');
    const second = projected.find((p) => p.approvalId === 'appr-adv-k-second');

    expect(first).toBeDefined();
    expect(second).toBeDefined();
    expect(first?.approvalState).toBe('REJECTED');
    expect(second?.approvalState).toBe('PENDING');
    expect(first?.requestId).toBe('req-shared-k');
    expect(second?.requestId).toBe('req-shared-k');
  });
});
