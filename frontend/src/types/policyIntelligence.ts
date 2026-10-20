/**
 * AryaOS V1 — Stage 20: Policy Intelligence & Governed Adaptive Operations
 *
 * Core Domain Models and Contract Definitions for Governed Policy Intelligence.
 *
 * Governing Invariants:
 * - LEARNING ≠ AUTHORITY
 * - EXPERIENCE ≠ PERMISSION
 * - RECOMMENDATION ≠ POLICY
 * - POLICY ≠ APPROVAL
 * - APPROVAL ≠ EXECUTION
 */

export type PolicyId = string;
export type PolicyVersion = number;

export type PolicyStatus =
  | 'DRAFT'
  | 'CANDIDATE'
  | 'UNDER_REVIEW'
  | 'APPROVED'
  | 'ACTIVE'
  | 'PAUSED'
  | 'DEPRECATED'
  | 'REVOKED';

export type PolicyScopeType =
  | 'SYSTEM'
  | 'AGENT'
  | 'MISSION'
  | 'TRIGGER'
  | 'REACTION'
  | 'RESOURCE'
  | 'CONNECTOR'
  | 'PROVIDER'
  | 'WORKFLOW';

export interface PolicyScope {
  scopeType: PolicyScopeType;
  targetId?: string; // Specific agentId, missionId, connectorId, or undefined for scope-wide
  qualifiers?: Record<string, string>;
}

export type PolicyOperator =
  | 'equals'
  | 'not_equals'
  | 'contains'
  | 'exists'
  | 'not_exists'
  | 'greater_than'
  | 'less_than'
  | 'in'
  | 'not_in';

export interface PolicyCondition {
  field: string;
  operator: PolicyOperator;
  value?: unknown;
}

export interface PolicyConditionGroup {
  conjunction: 'AND' | 'OR';
  conditions: (PolicyCondition | PolicyConditionGroup)[];
}

export type PolicyEffectType =
  | 'ALLOW'
  | 'DENY'
  | 'LIMIT'
  | 'REQUIRE_APPROVAL'
  | 'REQUIRE_REVIEW'
  | 'PAUSE'
  | 'DEFER'
  | 'ROUTE';

export interface PolicyConstraint {
  maxConcurrentActions?: number;
  maxConcurrentAgents?: number;
  maxRetries?: number;
  maxCostUsd?: number;
  maxTokens?: number;
  cooldownMs?: number;
  rateLimitPerHour?: number;
  allowedCapabilities?: string[];
  disallowedProviders?: string[];
  preferredProviderId?: string;
  preferredAgentId?: string;
}

export interface PolicyEffect {
  type: PolicyEffectType;
  constraint?: PolicyConstraint;
  reason?: string;
  targetSystem?: string;
  routedProviderId?: string;
  routedAgentId?: string;
}

export type PolicyPriorityLevel =
  | 'SYSTEM_SAFETY'     // 100
  | 'SECURITY'          // 90
  | 'HUMAN_GOVERNANCE'  // 80
  | 'RESOURCE_LIMITS'   // 70
  | 'MISSION_POLICY'    // 60
  | 'AGENT_POLICY'      // 50
  | 'TRIGGER_POLICY'    // 40
  | 'OPTIMIZATION_POLICY'; // 30

export const POLICY_PRIORITY_WEIGHTS: Record<PolicyPriorityLevel, number> = {
  SYSTEM_SAFETY: 100,
  SECURITY: 90,
  HUMAN_GOVERNANCE: 80,
  RESOURCE_LIMITS: 70,
  MISSION_POLICY: 60,
  AGENT_POLICY: 50,
  TRIGGER_POLICY: 40,
  OPTIMIZATION_POLICY: 30,
};

export interface PolicyEvidence {
  evidenceSignalIds?: string[];
  experienceIds?: string[];
  knowledgeFactIds?: string[];
  missionIds?: string[];
  confidenceScore: number;
  sampleSize?: number;
  description: string;
}

export type EpistemicCertainty = 'OBSERVED' | 'INFERRED' | 'PROJECTED' | 'UNKNOWN';

export interface PolicyImpactDimension {
  value: number | string;
  certainty: EpistemicCertainty;
  deltaPercent?: number;
  notes?: string;
}

export interface PolicyImpact {
  cost: PolicyImpactDimension;
  latencyMs: PolicyImpactDimension;
  quality: PolicyImpactDimension;
  resourceUsage: PolicyImpactDimension;
  reliability: PolicyImpactDimension;
  risk: PolicyImpactDimension;
  approvalFrequency: PolicyImpactDimension;
}

export interface PolicyProvenance {
  authorId: string;
  createdAt: number;
  updatedAt: number;
  parentPolicyId?: string;
  learningSignalId?: string;
  evidence: PolicyEvidence;
  changeLog: Array<{
    version: number;
    timestamp: number;
    changedBy: string;
    description: string;
  }>;
}

export interface Policy {
  id: PolicyId;
  version: PolicyVersion;
  name: string;
  description: string;
  status: PolicyStatus;
  scope: PolicyScope;
  priority: PolicyPriorityLevel;
  conditions: PolicyConditionGroup;
  effect: PolicyEffect;
  provenance: PolicyProvenance;
  requiresHumanApproval: boolean;
  isShadow?: boolean;
}

export interface PolicyProposal {
  proposalId: string;
  policy: Policy;
  proposedStatus: PolicyStatus;
  proposerId: string;
  proposedAt: number;
  reason: string;
  status: 'PENDING' | 'APPROVED' | 'REJECTED' | 'EXPIRED';
  reviewedBy?: string;
  reviewedAt?: number;
  rejectionReason?: string;
  impactSimulation?: PolicyImpact;
}

export interface PolicyActivationRecord {
  activationId: string;
  policyId: PolicyId;
  version: PolicyVersion;
  approvedBy: string;
  approvedAt: number;
  activationAt: number;
  previousPolicyVersion?: PolicyVersion;
  reason: string;
}

export interface PolicyRollbackRecord {
  rollbackId: string;
  policyId: PolicyId;
  fromVersion: PolicyVersion;
  toVersion: PolicyVersion;
  authorizedBy: string;
  authorizedAt: number;
  rollbackAt: number;
  reason: string;
}

export interface PolicyEvaluationContext {
  agentId?: string;
  missionId?: string;
  goalId?: string;
  triggerId?: string;
  connectorId?: string;
  providerId?: string;
  capability?: string;
  taskType?: string;
  costUsd?: number;
  tokenCount?: number;
  activeConcurrentActions?: number;
  activeConcurrentAgents?: number;
  riskLevel?: string;
  [key: string]: unknown;
}

export interface PolicyEvaluationResult {
  policyId: PolicyId;
  version: PolicyVersion;
  matched: boolean;
  effect: PolicyEffect;
  priority: PolicyPriorityLevel;
  priorityWeight: number;
  reason: string;
}

export interface EffectivePolicyDecision {
  effectiveEffect: PolicyEffect;
  winningPolicyId: PolicyId;
  winningPolicyVersion: PolicyVersion;
  winningPriority: PolicyPriorityLevel;
  appliedPolicies: PolicyEvaluationResult[];
  conflictingPolicies: PolicyConflictRecord[];
  reason: string;
}

export type PolicyConflictType =
  | 'CONTRADICTORY_POLICY'
  | 'SCOPE_CONFLICT'
  | 'PRIORITY_CONFLICT'
  | 'RESOURCE_CONFLICT'
  | 'AUTHORIZATION_CONFLICT';

export interface PolicyConflictRecord {
  conflictId: string;
  policyAId: PolicyId;
  policyAVersion: PolicyVersion;
  policyBId: PolicyId;
  policyBVersion: PolicyVersion;
  conflictType: PolicyConflictType;
  precedenceReason: string;
  effectivePolicyId: PolicyId;
  detectedAt: number;
}

export interface PolicyShadowRecord {
  shadowRecordId: string;
  policyId: PolicyId;
  version: PolicyVersion;
  evaluatedAt: number;
  wouldApply: boolean;
  actualRuntimeEffect: PolicyEffectType;
  shadowProjectedEffect: PolicyEffectType;
  projectedDifference: string;
  contextSummary: Record<string, unknown>;
}

export type PolicyDriftType =
  | 'PERFORMANCE_DEGRADATION'
  | 'RESOURCE_DRIFT'
  | 'COST_DRIFT'
  | 'QUALITY_DRIFT'
  | 'RISK_DRIFT';

export interface PolicyDriftRecord {
  driftId: string;
  policyId: PolicyId;
  version: PolicyVersion;
  driftType: PolicyDriftType;
  observedMetric: string;
  baselineValue: number;
  currentValue: number;
  deltaPercent: number;
  detectedAt: number;
  status: 'REVIEW_REQUIRED' | 'ACKNOWLEDGED' | 'RESOLVED';
}
