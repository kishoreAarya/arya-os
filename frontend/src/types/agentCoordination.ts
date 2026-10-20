/**
 * AryaOS V1 — Stage 10: Multi-Agent Coordination, Resource Governance & Intelligence Economy
 *
 * Domain contracts for:
 * - Provider-neutral Agent Profiles and Roles
 * - Agent Tasks, Contracts, and Statuses
 * - Resource Governance, Budgets, and Leases
 * - Shared Memory Locking and Conflict Detection
 * - Result Aggregation and Objective Quality Gates
 * - Agent Telemetry and Operational Provenance
 */

import { ProviderCapabilityType } from './intelligenceProvider';
import { ActionRiskLevel } from './goalOrchestration';

export type AgentRole =
  | 'RESEARCHER'
  | 'ANALYST'
  | 'PLANNER'
  | 'WRITER'
  | 'CODER'
  | 'VISION_ANALYST'
  | 'VIDEO_DIRECTOR'
  | 'QUALITY_REVIEWER'
  | 'METADATA_AGENT'
  | 'PUBLISHING_AGENT';

export type AgentCostClass = 'ECONOMY' | 'STANDARD' | 'PREMIUM';

export type AgentLatencyClass = 'FAST' | 'BALANCED' | 'DEEP';

export type AgentTrustLevel = 'PROVISIONAL' | 'VERIFIED' | 'AUTONOMOUS';

export type AgentAutonomyLevel = 'LOW' | 'MEDIUM' | 'HIGH';

export type AgentStatus =
  | 'IDLE'
  | 'ASSIGNED'
  | 'RUNNING'
  | 'WAITING'
  | 'BLOCKED'
  | 'PAUSED'
  | 'UNAVAILABLE';

export interface AgentProfile {
  agentId: string;
  name: string;
  role: AgentRole;
  capabilities: ProviderCapabilityType[];
  allowedCapabilities: ProviderCapabilityType[];
  contextRequirements: string[];
  costClass: AgentCostClass;
  latencyClass: AgentLatencyClass;
  concurrencyLimit: number;
  currentWorkload: number;
  trustLevel: AgentTrustLevel;
  autonomyLevel: AgentAutonomyLevel;
  status: AgentStatus;
  memoryScopes: string[];
  historicalSuccessCount: number;
  historicalFailureCount: number;
  metadata?: Record<string, unknown>;
}

export type AgentTaskStatus =
  | 'IDLE'
  | 'ASSIGNED'
  | 'RUNNING'
  | 'WAITING'
  | 'BLOCKED'
  | 'SUCCEEDED'
  | 'FAILED'
  | 'CANCELLED'
  | 'RETRYING';

export type QualityRequirementLevel =
  | 'QUALITY_LOW'
  | 'QUALITY_STANDARD'
  | 'QUALITY_HIGH'
  | 'HUMAN_REVIEW';

export type MemoryAccessType = 'READ' | 'WRITE' | 'READ_WRITE';

export interface TaskMemoryAccessDeclaration {
  memoryId: string;
  accessType: MemoryAccessType;
  vitrineId?: string;
}

export interface AgentTask {
  taskId: string;
  goalId: string;
  planId: string;
  planVersion: number;
  parentActionId: string;
  assignedAgentId?: string;
  capability: ProviderCapabilityType;
  contextReferences: string[];
  inputContract: Record<string, unknown>;
  expectedOutputContract: Record<string, unknown>;
  priority: 'LOW' | 'MEDIUM' | 'HIGH' | 'CRITICAL';
  riskLevel: ActionRiskLevel;
  estimatedCost: {
    minUsd: number | null;
    maxUsd: number | null;
    currency: 'USD';
  };
  estimatedLatency: number;
  deadline?: string;
  status: AgentTaskStatus;
  qualityRequirement: QualityRequirementLevel;
  memoryAccessDeclarations: TaskMemoryAccessDeclaration[];
  createdAt: string;
  updatedAt: string;
}

export type MemoryLockState = 'AVAILABLE' | 'READ_LOCKED' | 'WRITE_LOCKED' | 'CONFLICT';

export interface MemoryLock {
  lockId: string;
  memoryId: string;
  ownerTaskId: string;
  ownerAgentId: string;
  accessType: MemoryAccessType;
  acquiredAt: string;
  expiresAt: string;
}

export interface ResourceBudget {
  maxCostUsd?: number;
  maxLatencyMs?: number;
  maxConcurrentActions: number;
  maxConcurrentAgents: number;
  maxRetries: number;
  maxTokenEstimate?: number;
}

export interface ResourceLease {
  leaseId: string;
  goalId: string;
  taskId: string;
  agentId: string;
  providerId?: string;
  grantedAt: string;
  expiresAt: string;
  estimatedCost: number | null;
  estimatedTokens: number;
}

export type GovernanceCheckResult =
  | { allowed: true }
  | {
      allowed: false;
      reason:
        | 'RESOURCE_BUDGET_EXCEEDED'
        | 'RESOURCE_LIMIT_REACHED'
        | 'ROUTE_RECONSIDERATION_REQUIRED'
        | 'CONCURRENCY_LIMIT_REACHED'
        | 'MEMORY_LOCK_CONFLICT'
        | 'INSUFFICIENT_AUTONOMY';
      details: string;
    };

export type ConflictCategory =
  | 'MEMORY_WRITE_CONFLICT'
  | 'CONTRADICTORY_OUTPUT'
  | 'DUPLICATE_TASK_ASSIGNMENT'
  | 'DUPLICATE_EXECUTION'
  | 'INCOMPATIBLE_RESOURCE_OWNERSHIP'
  | 'CIRCULAR_DEPENDENCY';

export type ConflictResolutionStrategy = 'REVIEW' | 'REPLAN' | 'RESOLVE';

export interface ConflictRecord {
  conflictId: string;
  goalId: string;
  category: ConflictCategory;
  conflictingTaskIds: string[];
  conflictingAgentIds: string[];
  resourceOrMemoryId?: string;
  description: string;
  detectedAt: string;
  resolvedAt?: string;
  resolutionStrategy?: ConflictResolutionStrategy;
  resolutionDetails?: string;
  provenanceRecords: Record<string, unknown>[];
}

export type ResultAggregationStrategy =
  | 'SINGLE_RESULT'
  | 'MERGE'
  | 'CONSENSUS_REQUIRED'
  | 'HUMAN_REVIEW_REQUIRED';

export interface AggregatedAgentResult {
  aggregationId: string;
  goalId: string;
  taskId: string;
  agentId: string;
  providerId: string;
  executionId: string;
  output: string;
  structuredOutput?: Record<string, unknown>;
  provenance: Record<string, unknown>;
  confidence: number | 'UNKNOWN';
  actualCostUsd: number | 'UNKNOWN';
  latencyMs: number;
  status: 'SUCCEEDED' | 'FAILED' | 'CONFLICT' | 'AWAITING_REVIEW';
  strategyApplied: ResultAggregationStrategy;
  timestamp: string;
}

export type AgentFailureClassification =
  | 'TRANSIENT_FAILURE'
  | 'PROVIDER_FAILURE'
  | 'RESOURCE_FAILURE'
  | 'CONTEXT_FAILURE'
  | 'VALIDATION_FAILURE'
  | 'CONFLICT'
  | 'TIMEOUT'
  | 'CANCELLED'
  | 'PERMANENT_FAILURE';

export interface AgentOperationalTelemetry {
  activeAgents: number;
  queuedTasks: number;
  runningTasks: number;
  completedTasks: number;
  failedTasks: number;
  averageLatencyMs: number;
  cumulativeCostUsd: number;
  costStatus: 'KNOWN' | 'UNKNOWN' | 'PARTIALLY_KNOWN';
  concurrencyUtilization: number;
  conflictCount: number;
  replanCount: number;
  approvalCount: number;
  activeLeasesCount: number;
  activeLocksCount: number;
}
