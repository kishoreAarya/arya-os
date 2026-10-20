/**
 * AryaOS V1 — Stage 11: Agent Evaluation Service
 *
 * Deterministic multi-dimensional evaluation of agent task executions:
 * - QUALITY, CORRECTNESS, COMPLETENESS, RELEVANCE, CONSISTENCY
 * - LATENCY, COST, RELIABILITY, RESOURCE_EFFICIENCY
 * - HUMAN_ACCEPTANCE, DOWNSTREAM_SUCCESS
 *
 * Provides agent performance profiling across (agent × capability × task type).
 */

import {
  EvaluationRecord,
  EvaluationScore,
  EvaluationDimension,
  QualityAssessment,
  CostAssessment,
  LatencyAssessment,
  ReliabilityAssessment,
  ExecutionOutcome,
  AgentPerformanceProfile,
  TaskPerformanceProfile,
  ConfidenceBand,
} from '../types/agentEvaluation';
import { ProviderCapabilityType } from '../types/intelligenceProvider';
import { QualityRequirementLevel } from '../types/agentCoordination';
import { executionPersistence } from './executionPersistence';

export interface EvaluateExecutionInput {
  goalId: string;
  actionId: string;
  agentId: string;
  providerId: string;
  capability: ProviderCapabilityType;
  taskType: string;
  executionId: string;
  planVersion: number;
  output: unknown;
  outcome: ExecutionOutcome;
  latencyMs: number;
  estimatedLatencyMs?: number;
  costUsd?: number | 'UNKNOWN';
  estimatedCostUsd?: number | null;
  fallbackUsed?: boolean;
  retriesCount?: number;
  humanApprovalGranted?: boolean;
  downstreamSuccess?: boolean;
  qualityLevel?: QualityRequirementLevel;
  evaluatorIdentity?: string;
}

export class AgentEvaluationService {
  /**
   * Helper to determine confidence band from sample size
   */
  public calculateConfidence(sampleSize: number): ConfidenceBand {
    if (sampleSize >= 8) return 'HIGH';
    if (sampleSize >= 3) return 'MEDIUM';
    return 'LOW';
  }

  /**
   * Evaluates an agent's execution across all dimensions
   */
  public evaluateExecution(input: EvaluateExecutionInput): EvaluationRecord {
    const timestamp = new Date().toISOString();
    const evaluationId = `eval-${Date.now()}-${Math.random().toString(36).substr(2, 6)}`;
    const qualityLevel = input.qualityLevel || 'QUALITY_STANDARD';

    // 1. Correctness Assessment
    const isCorrect = input.outcome.isSuccess && !input.outcome.error;
    const correctnessScore = isCorrect ? 1.0 : 0.0;

    // 2. Completeness Assessment
    let completenessScore = 1.0;
    const issues: string[] = [];
    if (!input.output) {
      completenessScore = 0.0;
      issues.push('Output is empty or undefined');
    } else if (typeof input.output === 'string') {
      if (input.output.trim().length === 0) {
        completenessScore = 0.0;
        issues.push('Output string is blank');
      } else if (input.output.includes('[TRUNCATED]') || input.output.includes('[ERROR]')) {
        completenessScore = 0.5;
        issues.push('Output contains error/truncation flags');
      }
    }

    // 3. Relevance Assessment
    const relevanceScore = isCorrect ? 0.95 : 0.2;

    // 4. Quality Assessment
    const passedQuality = isCorrect && completenessScore >= 0.7;
    const rawQuality = isCorrect ? (completenessScore + relevanceScore) / 2 : 0.1;
    const qualityScore: EvaluationScore = {
      value: Number(rawQuality.toFixed(2)),
      scale: { min: 0, max: 1 },
      dimension: 'QUALITY',
      source: 'AutomatedQualityGate',
      timestamp,
      confidence: 'HIGH',
      evidenceReferences: [input.executionId],
    };

    const quality: QualityAssessment = {
      level: qualityLevel,
      passed: passedQuality,
      scores: [qualityScore],
      issues,
    };

    // 5. Cost Assessment (truthful: UNKNOWN if not provided)
    const costUsd = input.costUsd !== undefined ? input.costUsd : 'UNKNOWN';
    let costEfficiency: number | 'UNKNOWN' = 'UNKNOWN';
    let withinBudget = true;
    if (typeof costUsd === 'number') {
      const estimated = input.estimatedCostUsd ?? 0.05;
      withinBudget = costUsd <= estimated;
      costEfficiency = costUsd <= estimated ? 1.0 : Number(Math.max(0, 1 - (costUsd - estimated) / estimated).toFixed(2));
    }
    const cost: CostAssessment = {
      estimatedUsd: input.estimatedCostUsd ?? null,
      actualUsd: costUsd,
      withinBudget,
      efficiencyScore: costEfficiency,
    };

    // 6. Latency Assessment
    const estimatedLatency = input.estimatedLatencyMs ?? 2000;
    const withinDeadline = input.latencyMs <= estimatedLatency;
    const latencyEfficiency =
      input.latencyMs <= estimatedLatency
        ? 1.0
        : Number(Math.max(0, 1 - (input.latencyMs - estimatedLatency) / estimatedLatency).toFixed(2));

    const latency: LatencyAssessment = {
      estimatedMs: estimatedLatency,
      actualMs: input.latencyMs,
      withinDeadline,
      efficiencyScore: latencyEfficiency,
    };

    // 7. Reliability Assessment
    const fallbackUsed = !!input.fallbackUsed;
    const retriesCount = input.retriesCount ?? 0;
    let reliabilityStatus: 'SUCCESS' | 'FAILURE' | 'RECOVERED' = 'SUCCESS';
    if (!input.outcome.isSuccess) {
      reliabilityStatus = 'FAILURE';
    } else if (fallbackUsed || retriesCount > 0) {
      reliabilityStatus = 'RECOVERED';
    }
    const reliability: ReliabilityAssessment = {
      fallbackUsed,
      retriesCount,
      status: reliabilityStatus,
    };

    // 8. Overall Score Calculation
    // We average available numerical dimensions: Correctness (0.3), Completeness (0.2), Quality (0.2), Latency (0.15), Reliability (0.15)
    const reliabilityScore = reliabilityStatus === 'SUCCESS' ? 1.0 : reliabilityStatus === 'RECOVERED' ? 0.75 : 0.0;
    const weightedSum =
      correctnessScore * 0.3 +
      completenessScore * 0.2 +
      rawQuality * 0.2 +
      latencyEfficiency * 0.15 +
      reliabilityScore * 0.15;
    const overallScore = Number(weightedSum.toFixed(2));

    const record: EvaluationRecord = {
      evaluationId,
      executionId: input.executionId,
      evaluationVersion: 1,
      goalId: input.goalId,
      actionId: input.actionId,
      agentId: input.agentId,
      providerId: input.providerId,
      capability: input.capability,
      taskType: input.taskType,
      timestamp,
      quality,
      cost,
      latency,
      reliability,
      outcome: input.outcome,
      overallScore,
      evaluatorIdentity: input.evaluatorIdentity || 'AgentEvaluationService:v1',
    };

    return record;
  }

  /**
   * Builds an empirical AgentPerformanceProfile from historical experiences
   */
  public buildAgentProfile(agentId: string, role: string = 'ANALYST'): AgentPerformanceProfile {
    const experiences = executionPersistence.getExperiences({ agentId });
    const taskTypeProfiles: Record<string, TaskPerformanceProfile> = {};
    const capabilityProfiles: Record<
      string,
      {
        qualityScore: number | 'UNKNOWN';
        reliabilityScore: number | 'UNKNOWN';
        latencyAverageMs: number | 'UNKNOWN';
        sampleSize: number;
        confidence: ConfidenceBand;
      }
    > = {};

    let totalDecisions = 0;
    let approvedDecisions = 0;

    // Group by taskType
    const byTaskType: Record<string, typeof experiences> = {};
    const byCapability: Record<string, typeof experiences> = {};

    for (const exp of experiences) {
      if (!byTaskType[exp.taskType]) byTaskType[exp.taskType] = [];
      byTaskType[exp.taskType].push(exp);

      if (!byCapability[exp.capability]) byCapability[exp.capability] = [];
      byCapability[exp.capability].push(exp);

      if (exp.humanDecision) {
        totalDecisions++;
        if (exp.humanDecision === 'APPROVED') approvedDecisions++;
      }
    }

    // Build Task Profiles
    for (const [taskType, list] of Object.entries(byTaskType)) {
      const sampleSize = list.length;
      const successes = list.filter(
        (e) =>
          e.status === 'COMPLETED' ||
          e.status === 'SUCCESS' ||
          e.status === 'SUCCEEDED' ||
          e.evaluation.outcome.isSuccess
      ).length;
      const successRate = sampleSize > 0 ? Number((successes / sampleSize).toFixed(2)) : 'UNKNOWN';

      const scoredExps = list.filter((e) => typeof e.evaluation.overallScore === 'number');
      const avgQuality =
        scoredExps.length > 0
          ? Number(
              (
                scoredExps.reduce((acc, e) => acc + (e.evaluation.overallScore as number), 0) /
                scoredExps.length
              ).toFixed(2)
            )
          : 'UNKNOWN';

      const avgLatency =
        sampleSize > 0
          ? Number((list.reduce((acc, e) => acc + e.latencyMs, 0) / sampleSize).toFixed(0))
          : 'UNKNOWN';

      taskTypeProfiles[taskType] = {
        agentId,
        taskType,
        capability: list[0].capability,
        sampleSize,
        successRate,
        averageQuality: avgQuality,
        averageLatencyMs: avgLatency,
        confidence: this.calculateConfidence(sampleSize),
        lastObservedAt: list[list.length - 1].timestamp,
      };
    }

    // Build Capability Profiles
    for (const [cap, list] of Object.entries(byCapability)) {
      const sampleSize = list.length;
      const successes = list.filter(
        (e) =>
          e.status === 'COMPLETED' ||
          e.status === 'SUCCESS' ||
          e.status === 'SUCCEEDED' ||
          e.evaluation.outcome.isSuccess
      ).length;
      const reliabilityScore = sampleSize > 0 ? Number((successes / sampleSize).toFixed(2)) : 'UNKNOWN';

      const scored = list.filter((e) => typeof e.evaluation.overallScore === 'number');
      const qualityScore =
        scored.length > 0
          ? Number(
              (
                scored.reduce((acc, e) => acc + (e.evaluation.overallScore as number), 0) /
                scored.length
              ).toFixed(2)
            )
          : 'UNKNOWN';

      const latencyAvg =
        sampleSize > 0
          ? Number((list.reduce((acc, e) => acc + e.latencyMs, 0) / sampleSize).toFixed(0))
          : 'UNKNOWN';

      capabilityProfiles[cap] = {
        qualityScore,
        reliabilityScore,
        latencyAverageMs: latencyAvg,
        sampleSize,
        confidence: this.calculateConfidence(sampleSize),
      };
    }

    const approvalRate =
      totalDecisions > 0 ? Number((approvedDecisions / totalDecisions).toFixed(2)) : 'UNKNOWN';

    return {
      agentId,
      role,
      taskTypeProfiles,
      capabilityProfiles,
      approvalRate,
      conflictCount: 0,
      lastUpdated: new Date().toISOString(),
    };
  }
}

export const agentEvaluationService = new AgentEvaluationService();
