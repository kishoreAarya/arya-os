/**
 * AryaOS V1 — Stage 11: Agent Evaluation, Collective Intelligence & Learning Loop Types
 *
 * Domain contracts for:
 * - Multidimensional Evaluation Dimensions & Records
 * - Sanitized Execution Experiences
 * - Agent, Provider & Task-Specific Performance Profiles
 * - Collective Decisions, Opinions & Evidence Graphs
 * - Empirical Learning Signals with Confidence Bands & Recency Weighting
 * - Auditable Policy Recommendations with Human Governance Boundaries
 * - Comparative Plan Evaluations & Self-Critique
 */

import { ProviderCapabilityType } from './intelligenceProvider';
import { QualityRequirementLevel } from './agentCoordination';

export type EvaluationDimension =
  | 'QUALITY'
  | 'CORRECTNESS'
  | 'COMPLETENESS'
  | 'RELEVANCE'
  | 'CONSISTENCY'
  | 'LATENCY'
  | 'COST'
  | 'RELIABILITY'
  | 'RESOURCE_EFFICIENCY'
  | 'HUMAN_ACCEPTANCE'
  | 'DOWNSTREAM_SUCCESS';

export type EvaluationStatus = 'PENDING' | 'EVALUATED' | 'FAILED' | 'SKIPPED';

export type ConfidenceBand = 'LOW' | 'MEDIUM' | 'HIGH';

export interface EvaluationScore {
  value: number | 'UNKNOWN';
  scale: { min: number; max: number };
  dimension: EvaluationDimension;
  source: string;
  timestamp: string;
  confidence: ConfidenceBand;
  evidenceReferences: string[];
}

export interface QualityAssessment {
  level: QualityRequirementLevel;
  passed: boolean;
  scores: EvaluationScore[];
  issues: string[];
}

export interface CostAssessment {
  estimatedUsd: number | null;
  actualUsd: number | 'UNKNOWN';
  withinBudget: boolean;
  efficiencyScore: number | 'UNKNOWN';
}

export interface LatencyAssessment {
  estimatedMs: number;
  actualMs: number;
  withinDeadline: boolean;
  efficiencyScore: number | 'UNKNOWN';
}

export interface ReliabilityAssessment {
  fallbackUsed: boolean;
  retriesCount: number;
  status: 'SUCCESS' | 'FAILURE' | 'RECOVERED';
}

export interface ExecutionOutcome {
  isSuccess: boolean;
  status: string;
  error?: string;
  humanApprovalGranted?: boolean;
}

export interface EvaluationRecord {
  evaluationId: string;
  executionId: string;
  evaluationVersion: number;
  goalId: string;
  actionId: string;
  agentId: string;
  providerId: string;
  capability: ProviderCapabilityType;
  taskType: string;
  timestamp: string;
  quality: QualityAssessment;
  cost: CostAssessment;
  latency: LatencyAssessment;
  reliability: ReliabilityAssessment;
  outcome: ExecutionOutcome;
  overallScore: number | 'UNKNOWN';
  evaluatorIdentity: string;
}

export interface ExperienceRecord {
  experienceId: string;
  goalId: string;
  actionId: string;
  agentId: string;
  providerId: string;
  capability: ProviderCapabilityType;
  taskType: string;
  executionId: string;
  planVersion: number;
  inputFingerprint: string;
  outputFingerprint: string;
  evaluation: EvaluationRecord;
  cost: number | 'UNKNOWN';
  latencyMs: number;
  status: string;
  humanDecision?: 'APPROVED' | 'REJECTED';
  downstreamOutcome?: string;
  timestamp: string;
  provenance: Record<string, unknown>;
}

export interface TaskPerformanceProfile {
  agentId: string;
  taskType: string;
  capability: ProviderCapabilityType;
  sampleSize: number;
  successRate: number | 'UNKNOWN';
  averageQuality: number | 'UNKNOWN';
  averageLatencyMs: number | 'UNKNOWN';
  confidence: ConfidenceBand;
  lastObservedAt: string;
}

export interface AgentPerformanceProfile {
  agentId: string;
  role: string;
  taskTypeProfiles: Record<string, TaskPerformanceProfile>;
  capabilityProfiles: Record<
    string,
    {
      qualityScore: number | 'UNKNOWN';
      reliabilityScore: number | 'UNKNOWN';
      latencyAverageMs: number | 'UNKNOWN';
      sampleSize: number;
      confidence: ConfidenceBand;
    }
  >;
  approvalRate: number | 'UNKNOWN';
  conflictCount: number;
  lastUpdated: string;
}

export interface ProviderPerformanceProfile {
  providerId: string;
  capabilities: Record<
    string,
    {
      observedSuccessRate: number | 'UNKNOWN';
      averageLatencyMs: number | 'UNKNOWN';
      observedReliability: number | 'UNKNOWN';
      fallbackRate: number | 'UNKNOWN';
      costEfficiency: number | 'UNKNOWN';
      sampleSize: number;
      confidence: ConfidenceBand;
    }
  >;
  availabilityStatus: string;
  lastUpdated: string;
}

export interface AgentOpinion {
  opinionId: string;
  agentId: string;
  taskId: string;
  output: string;
  structuredOutput?: Record<string, unknown>;
  confidence: ConfidenceBand | 'UNKNOWN';
  evidence: string[];
  evaluation?: EvaluationRecord;
  provenance: Record<string, unknown>;
}

export interface EvidenceItem {
  evidenceId: string;
  entityType:
    | 'GOAL'
    | 'ACTION'
    | 'AGENT'
    | 'PROVIDER'
    | 'EXECUTION'
    | 'OUTPUT'
    | 'EVALUATION'
    | 'DECISION'
    | 'HUMAN_APPROVAL';
  entityId: string;
  summary: string;
  timestamp: string;
  source: string;
  confidence: ConfidenceBand;
  metadata: Record<string, unknown>;
}

export type CollectiveStrategy =
  | 'SINGLE_RESULT'
  | 'MERGE'
  | 'CONSENSUS'
  | 'EVIDENCE_WEIGHTED_CONSENSUS'
  | 'EXPERT_REVIEW'
  | 'HUMAN_REVIEW';

export interface CollectiveDecision {
  decisionId: string;
  goalId: string;
  taskId: string;
  strategy: CollectiveStrategy;
  participatingAgents: string[];
  opinions: AgentOpinion[];
  selectedOutput: string;
  structuredOutput?: Record<string, unknown>;
  consensusAchieved: boolean;
  disagreementDetected: boolean;
  supportingEvidenceIds: string[];
  decidedAt: string;
  status: 'RESOLVED' | 'REVIEW_REQUIRED' | 'HUMAN_REVIEW_REQUIRED';
}

export type LearningSignalStatus =
  | 'OBSERVED'
  | 'VALIDATED'
  | 'ACTIONABLE'
  | 'EXPIRED'
  | 'SUPERSEDED';

export interface LearningSignal {
  signalId: string;
  signalType: string;
  sourceExperienceIds: string[];
  dimension: EvaluationDimension;
  observation: string;
  confidence: ConfidenceBand;
  sampleSize: number;
  createdAt: string;
  expiresAt: string;
  impact: 'LOW' | 'MEDIUM' | 'HIGH';
  status: LearningSignalStatus;
}

export type RecommendationStatus =
  | 'PROPOSED'
  | 'UNDER_REVIEW'
  | 'APPROVED'
  | 'REJECTED'
  | 'EXPIRED'
  | 'IMPLEMENTED';

export interface PolicyRecommendation {
  recommendationId: string;
  reason: string;
  evidenceSignalIds: string[];
  affectedPolicy: string;
  proposedAdjustment: Record<string, unknown>;
  expectedImpact: string;
  risk: 'LOW' | 'MEDIUM' | 'HIGH';
  confidence: ConfidenceBand;
  status: RecommendationStatus;
  requiresHumanApproval: boolean;
  proposedAt: string;
  reviewedAt?: string;
  reviewedBy?: string;
  rejectionReason?: string;
}

export interface RoutingRecommendation {
  recommendedAgentId?: string;
  recommendedProviderId?: string;
  reason: string;
  supportingEvidence: string[];
  confidence: ConfidenceBand;
  expectedCostTier?: number;
  expectedLatencyMs?: number;
  riskLevel: 'LOW' | 'MEDIUM' | 'HIGH';
}

export interface PlanEvaluation {
  planEvaluationId: string;
  goalId: string;
  planId: string;
  planVersion: number;
  plannedCostUsd: number | null;
  actualCostUsd: number | 'UNKNOWN';
  plannedLatencyMs: number;
  actualLatencyMs: number;
  actionCount: number;
  actionsSucceeded: number;
  actionsFailed: number;
  recoveryEventsCount: number;
  replanTriggered: boolean;
  qualitySummary: string;
  overallEfficiencyScore: number | 'UNKNOWN';
  completedAt: string;
}

export interface SelfCritique {
  taskId: string;
  succeeded: string[];
  failed: string[];
  uncertain: string[];
  evidenceSummary: string[];
  knownImprovements: string[];
  speculativeImprovements: string[];
  mustNotChange: string[];
  timestamp: string;
}
