/**
 * AryaOS V1 — Stage 21: Governed Policy Control Plane & Runtime Governance
 *
 * Domain contracts, types, and invariant specifications for the
 * central deterministic Governance Control Plane.
 *
 * Core Axiom:
 * A POLICY DECISION IS NOT AN EXECUTION AUTHORIZATION.
 * POLICY ALLOW ≠ ACTION AUTHORIZATION ≠ CONNECTOR PERMISSION ≠ HUMAN APPROVAL.
 *
 * Effective Authority = Policy ∩ Connector Permissions ∩ Action Authorization ∩ Human Approval ∩ Mission Constraints.
 */

import {
  Policy,
  PolicyEffect,
  PolicyEffectType,
  PolicyPriorityLevel,
  PolicyScope,
  PolicyScopeType,
  PolicyConditionGroup,
} from './policyIntelligence';
import { ActionRiskLevel } from './actionBus';

export type GovernanceDecisionType =
  | 'ALLOW'
  | 'DENY'
  | 'LIMIT'
  | 'REQUIRE_APPROVAL'
  | 'REQUIRE_REVIEW'
  | 'PAUSE'
  | 'DEFER'
  | 'ROUTE';

export type GovernanceActorType =
  | 'USER'
  | 'AUTONOMOUS_AGENT'
  | 'SYSTEM'
  | 'EXTERNAL_TRIGGER';

export interface GovernanceActor {
  actorId: string;
  actorType: GovernanceActorType;
  role?: string;
  ipAddress?: string;
}

export interface GovernanceRequest {
  requestId: string;
  correlationId?: string;
  actor: GovernanceActor;
  targetSystem: string;
  capabilityId?: string;
  actionType?: string;
  missionId?: string;
  goalId?: string;
  triggerId?: string;
  connectorId?: string;
  providerId?: string;
  parameters?: Record<string, unknown>;
  riskLevel?: ActionRiskLevel;
  timestamp: number;
}

export interface PolicySnapshotEntry {
  policyId: string;
  version: number;
  name: string;
  priority: PolicyPriorityLevel;
  priorityWeight: number;
  scope: PolicyScope;
  effect: PolicyEffect;
  conditions: PolicyConditionGroup;
}

export interface PolicySnapshot {
  snapshotId: string;
  registryVersion: number;
  createdAt: number;
  activePolicyCount: number;
  policies: readonly PolicySnapshotEntry[] | PolicySnapshotEntry[];
  fingerprint: string;
}

export interface GovernanceContext {
  requestId: string;
  correlationId: string;
  actor: GovernanceActor;
  scopeType: PolicyScopeType;
  targetId?: string;
  capability?: string;
  actionType?: string;
  missionId?: string;
  goalId?: string;
  triggerId?: string;
  connectorId?: string;
  providerId?: string;
  riskLevel: ActionRiskLevel;
  sanitizedParameters: Record<string, unknown>;
  currentMissionState?: string;
  currentConnectorState?: string;
  currentPermissionScopes?: string[];
  activeConcurrentActions?: number;
  activeConcurrentAgents?: number;
  costUsd?: number;
  tokenCount?: number;
  requestFrequency?: number;
  timestamp: number;
  [key: string]: unknown;
}

export type AuthorityCheckStatus =
  | 'GRANTED'
  | 'DENIED'
  | 'REQUIRES_APPROVAL'
  | 'MISSING_PERMISSION'
  | 'MISSION_CONSTRAINT_BLOCKED';

export type HumanApprovalCheckStatus =
  | 'NOT_REQUIRED'
  | 'PENDING'
  | 'GRANTED'
  | 'REJECTED'
  | 'STALE'
  | 'FORGED_REJECTED';

export interface OperatorApprovalToken {
  approvedBy: string;
  approvedAt: number;
  requestId: string;
  policySnapshotId: string;
  policyVersion?: number;
  riskLevel: ActionRiskLevel;
  signature?: string;
}

export interface AuthorityIntersectionResult {
  effectiveStatus: AuthorityCheckStatus;
  policyAllowed: boolean;
  connectorPermissionGranted: boolean;
  actionAuthorized: boolean;
  humanApprovalStatus: HumanApprovalCheckStatus;
  humanApprovalRequired: boolean;
  missionConstraintsSatisfied: boolean;
  requiredAuthority: string[];
  blockingReasons: string[];
  failClosed: boolean;
}

export type EpistemicStatus = 'OBSERVED' | 'INFERRED' | 'PROJECTED' | 'UNKNOWN';

export interface GovernanceExplanation {
  whatWasRequested: string;
  snapshotUsed: string;
  policiesMatched: string[];
  matchedPolicies?: string[];
  policiesConflicted: Array<{ policyA: string; policyB: string; reason: string }>;
  precedenceResolution: string;
  resultingPolicyDecision: GovernanceDecisionType;
  authorityRequired: string[];
  humanApprovalRequired: boolean;
  approvalPresent: boolean;
  executingOrBlockingBoundary: string;
  epistemicStatus: EpistemicStatus;
  requestId?: string;
  actor?: GovernanceActor;
  contextSummary?: Record<string, unknown>;
  deterministicRationale?: string;
  policySnapshotId?: string;
  authorityTiers?: {
    policyTier: { evaluated: boolean; allowed: boolean; decision: string };
    connectorTier: { required: boolean; granted: boolean };
    actionTier: { authorized: boolean };
    humanTier: { required: boolean; status: string };
    missionTier: { satisfied: boolean };
  };
  humanApprovalCheck?: {
    required: boolean;
    status: string;
    riskLevel?: string;
  };
  stalenessEvaluation?: {
    isStale: boolean;
    status: string;
    reason?: string;
  };
  deterministicMetadata?: {
    evaluationLatencyMs: number;
    fingerprint: string;
  };
}

export type StalenessStatus =
  | 'FRESH'
  | 'STALE_POLICY'
  | 'STALE_APPROVAL'
  | 'VERSION_MISMATCH'
  | 'EXPIRED'
  | 'REQUIRES_REEVALUATION';

export interface GovernanceStalenessCheck {
  isStale: boolean;
  status: StalenessStatus;
  reason?: string;
  evaluatedSnapshotId: string;
  currentRegistryVersion: number;
  snapshotRegistryVersion: number;
  alteredRequestParameters?: boolean;
}

export interface GovernanceDecision {
  decisionId: string;
  requestId: string;
  correlationId: string;
  policySnapshotId: string;
  policyRegistryVersion: number;
  evaluatedPolicyVersions: Record<string, number>;
  decision: GovernanceDecisionType;
  reason: string;
  matchedPolicies: string[];
  conflictingPolicies: Array<{
    conflictId: string;
    policyAId: string;
    policyBId: string;
    conflictType: string;
    precedenceReason: string;
  }>;
  winningPolicyId: string;
  winningPriority: PolicyPriorityLevel;
  authorityIntersection: AuthorityIntersectionResult;
  staleness: GovernanceStalenessCheck;
  explanation: GovernanceExplanation;
  epistemicStatus?: EpistemicStatus;
  deterministicMetadata: {
    evaluationLatencyMs: number;
    evaluatedAt: number;
    cacheHit: boolean;
    fingerprint: string;
  };
}
