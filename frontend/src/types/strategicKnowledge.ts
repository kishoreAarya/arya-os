/**
 * AryaOS V1 — Stage 13: Strategic Knowledge Graph & Long-Term Memory Domain Contracts
 *
 * Semantic knowledge layer above spatial memories, durable journal events,
 * multi-agent coordination, agent evaluation, and long-horizon mission control.
 */

export type KnowledgeNodeType =
  | 'MISSION'
  | 'GOAL'
  | 'ACTION'
  | 'AGENT'
  | 'PROVIDER'
  | 'CAPABILITY'
  | 'PROJECT'
  | 'CHARACTER'
  | 'ASSET'
  | 'WORKFLOW'
  | 'ARTIFACT'
  | 'DECISION'
  | 'OUTCOME'
  | 'PATTERN'
  | 'STRATEGY'
  | 'CONSTRAINT'
  | 'RISK'
  | 'MEMORY'
  | 'EXPERIENCE'
  | 'EVALUATION'
  | 'LEARNING_SIGNAL';

export type KnowledgeConfidence = 'UNKNOWN' | 'LOW' | 'MEDIUM' | 'HIGH';

export type KnowledgeValidity = 'ACTIVE' | 'SUPERSEDED' | 'OBSOLETE' | 'DISPUTED';

export type KnowledgeStatus =
  | 'VERIFIED'
  | 'CANDIDATE'
  | 'UNCERTAIN'
  | 'DEPRECATED'
  | 'REJECTED';

export type KnowledgeContradictionType =
  | 'FACT_CONTRADICTION'
  | 'TEMPORAL_CONTRADICTION'
  | 'SOURCE_CONFLICT'
  | 'OUTCOME_CONFLICT'
  | 'STRATEGY_CONFLICT';

export type ContradictionSeverity = 'LOW' | 'MEDIUM' | 'HIGH' | 'CRITICAL';

export type ContradictionResolutionStatus =
  | 'OPEN'
  | 'UNDER_REVIEW'
  | 'RESOLVED'
  | 'SUPERSEDED';

export type ResolutionStrategy =
  | 'TEMPORAL_RESOLUTION'
  | 'EVIDENCE_WEIGHTING'
  | 'SOURCE_PRIORITY'
  | 'CONTEXT_PARTITION'
  | 'HUMAN_REVIEW';

export type StrategicPatternType =
  | 'REPEATED_FAILURE'
  | 'REPEATED_SUCCESS'
  | 'RESOURCE_BOTTLENECK'
  | 'QUALITY_BOTTLENECK'
  | 'DEADLINE_PATTERN'
  | 'AGENT_SPECIALIZATION'
  | 'PROVIDER_SPECIALIZATION'
  | 'MISSION_FAILURE_PATTERN'
  | 'MISSION_SUCCESS_PATTERN'
  | 'RECURRING_CONFLICT'
  | 'RECURRING_REPLAN';

export type StrategyStatus = 'CANDIDATE' | 'VALIDATED' | 'DEPRECATED' | 'REJECTED';

export type KnowledgeSourceType =
  | 'STAGE04_MEMORY'
  | 'STAGE09_JOURNAL'
  | 'STAGE10_COORDINATION'
  | 'STAGE11_EXPERIENCE'
  | 'STAGE11_EVALUATION'
  | 'STAGE11_LEARNING_SIGNAL'
  | 'STAGE11_DECISION'
  | 'STAGE12_MISSION'
  | 'STAGE12_OBSERVATION'
  | 'STAGE12_RISK'
  | 'STAGE12_CHECKPOINT'
  | 'OPERATOR_INPUT';

export interface KnowledgeSource {
  sourceType: KnowledgeSourceType;
  sourceId: string;
  sourceName?: string;
  timestamp: string;
  metadata?: Record<string, unknown>;
}

export interface KnowledgeProvenance {
  source: KnowledgeSource;
  extractedAt: string;
  derivedBy: string; // Service or function that extracted this
  executionId?: string;
  missionId?: string;
  goalId?: string;
  actionId?: string;
  evaluationId?: string;
  memoryId?: string;
  confidenceScore?: number;
}

export interface KnowledgeEvidence {
  id: string;
  sourceType: KnowledgeSourceType;
  sourceId: string;
  description: string;
  timestamp: string;
  weight: number; // 0 to 1
  provenance: KnowledgeProvenance;
  metadata?: Record<string, unknown>;
}

export interface KnowledgeNode {
  id: string; // Canonical identifier
  type: KnowledgeNodeType;
  label: string;
  createdAt: string;
  updatedAt: string;
  provenance: KnowledgeProvenance;
  confidence: KnowledgeConfidence;
  status: KnowledgeStatus;
  validity?: KnowledgeValidity;
  metadata?: Record<string, unknown>;
}

export interface KnowledgeEdge {
  id: string;
  source: string; // Subject / origin node ID
  target: string; // Object / destination node ID
  relation: string; // Canonical relation predicate
  provenance: KnowledgeProvenance;
  confidence: KnowledgeConfidence;
  createdAt: string;
  weight?: number;
  metadata?: Record<string, unknown>;
}

export interface KnowledgeFact {
  id: string; // Canonical identifier: hash(subject + predicate + object)
  subject: string; // Subject node ID or canonical symbol
  predicate: string; // Canonical relation / predicate
  object: string; // Target node ID or value
  evidence: string[]; // List of KnowledgeEvidence IDs supporting this fact
  confidence: KnowledgeConfidence;
  validity: KnowledgeValidity;
  status: KnowledgeStatus; // If evidence is insufficient: status = 'UNCERTAIN'
  validFrom: string;
  validUntil?: string;
  observedAt: string;
  supersededAt?: string;
  provenance: KnowledgeProvenance;
  contradictionIds?: string[];
  metadata?: Record<string, unknown>;
}

export interface KnowledgeClaim {
  claimId: string;
  claimant: string; // Agent, Provider, or Operator ID
  statement: string;
  subject: string;
  predicate: string;
  object: string;
  submittedAt: string;
  supportingEvidenceIds: string[];
  status: 'PENDING_VERIFICATION' | 'ACCEPTED' | 'DISPUTED' | 'REJECTED';
}

export interface KnowledgeContradiction {
  contradictionId: string;
  type: KnowledgeContradictionType;
  factA: string; // Fact ID A
  factB: string; // Fact ID B
  evidenceA: string[]; // Supporting evidence IDs for A
  evidenceB: string[]; // Supporting evidence IDs for B
  detectedAt: string;
  severity: ContradictionSeverity;
  resolutionStatus: ContradictionResolutionStatus;
  resolutionStrategy?: ResolutionStrategy;
  resolvedAt?: string;
  resolutionNote?: string;
  resolvedBy?: string; // Operator ID or automated resolution rule
}

export interface KnowledgePattern {
  id: string;
  type: StrategicPatternType;
  label: string;
  description: string;
  applicableEntities: string[]; // Agent IDs, Provider IDs, Mission types
  supportingEvidence: string[]; // Evidence IDs
  occurrenceCount: number;
  confidence: KnowledgeConfidence;
  detectedAt: string;
  lastObservedAt: string;
  suggestedAction?: string;
  metadata?: Record<string, unknown>;
}

export interface KnowledgeStrategy {
  strategyId: string;
  title: string;
  description: string;
  applicableTaskTypes: string[];
  supportingEvidence: string[];
  observedOutcomes: string[];
  confidence: KnowledgeConfidence;
  knownRisks: string[];
  constraints: string[];
  status: StrategyStatus;
  createdAt: string;
  updatedAt: string;
  validatedAt?: string;
  deprecatedAt?: string;
  provenance: KnowledgeProvenance;
}

export interface ContextRankingExplanation {
  semanticRelevance: number; // 0 to 1
  taskSimilarity: number;    // 0 to 1
  recency: number;           // 0 to 1
  confidenceWeight: number;  // 0 to 1
  outcomeRelevance: number;  // 0 to 1
  missionSimilarity: number; // 0 to 1
  finalScore: number;        // Composite score [0, 100]
  rationale: string;
}

export interface RankedKnowledgeFact {
  fact: KnowledgeFact;
  score: number;
  explanation: ContextRankingExplanation;
}

export interface KnowledgeContext {
  querySubject: string;
  memories: unknown[];
  experiences: unknown[];
  historicalMissions: unknown[];
  strategies: KnowledgeStrategy[];
  risks: unknown[];
  contradictions: KnowledgeContradiction[];
  learningSignals: unknown[];
  agentProviderEvidence: unknown[];
  rankedFacts: RankedKnowledgeFact[];
  generatedAt: string;
  summary: string;
}

export interface KnowledgeDecisionContext {
  contextId: string;
  targetGoalId?: string;
  targetMissionId?: string;
  strategicContext: KnowledgeContext;
  governanceThresholdExceeded: boolean;
  requiresHumanReview: boolean;
  governanceReasons: string[];
  createdAt: string;
}

export interface MissionKnowledgeSnapshot {
  snapshotId: string;
  missionId: string;
  version: number;
  timestamp: string;
  objective: string;
  goalsSummary: Array<{
    goalId: string;
    title: string;
    status: string;
    durationMs?: number;
    tokens?: number;
    agentId?: string;
  }>;
  executionStrategy: string;
  outcomes: string[];
  quality: number;
  cost: number;
  latencyMs: number;
  failures: string[];
  replans: number;
  risksEncountered: string[];
  humanDecisions: string[];
  lessons: string[];
  provenance: KnowledgeProvenance;
}

export interface KnowledgeSnapshot {
  version: number;
  timestamp: string;
  nodeCount: number;
  edgeCount: number;
  factCount: number;
  contradictionCount: number;
  strategyCount: number;
  stateHash: string;
}

export interface KnowledgeQuery {
  subject?: string;
  predicate?: string;
  object?: string;
  nodeType?: KnowledgeNodeType;
  agentId?: string;
  providerId?: string;
  missionId?: string;
  taskType?: string;
  minConfidence?: KnowledgeConfidence;
  includeObsolete?: boolean;
  limit?: number;
}

export interface KnowledgeQueryResult {
  facts: KnowledgeFact[];
  evidence: KnowledgeEvidence[];
  nodes: KnowledgeNode[];
  edges: KnowledgeEdge[];
  contradictions: KnowledgeContradiction[];
  confidence: KnowledgeConfidence;
  provenanceList: KnowledgeProvenance[];
  timestamp: string;
  totalMatches: number;
}
