/**
 * AryaOS V1 — Stage 10: Multi-Agent Result Aggregator
 *
 * Normalizes and aggregates execution outputs across worker agents:
 * - Preserves complete worker, provider, and execution provenance
 * - Never manufactures confidence scores or billing metrics (unknowns remain UNKNOWN)
 * - Supports SINGLE_RESULT, MERGE, CONSENSUS_REQUIRED, and HUMAN_REVIEW_REQUIRED
 */

import {
  AgentTask,
  AgentProfile,
  AggregatedAgentResult,
  ResultAggregationStrategy,
} from '../types/agentCoordination';
import { ExecutionResult } from '../types/intelligenceProvider';

export const agentResultAggregator = {
  /**
   * Normalizes a single execution result into an AggregatedAgentResult.
   */
  aggregateSingle(
    task: AgentTask,
    agent: AgentProfile,
    executionResult: ExecutionResult,
    strategy: ResultAggregationStrategy = 'SINGLE_RESULT'
  ): AggregatedAgentResult {
    const isSuccess =
      executionResult.status === 'SUCCEEDED' ||
      executionResult.status === 'FALLBACK_SUCCEEDED';

    const costUsd =
      executionResult.usage?.estimatedCost !== undefined &&
      executionResult.usage?.estimatedCost !== null
        ? executionResult.usage.estimatedCost
        : 'UNKNOWN';

    return {
      aggregationId: `AGG-${Date.now()}-${Math.floor(Math.random() * 10000)}`,
      goalId: task.goalId,
      taskId: task.taskId,
      agentId: agent.agentId,
      providerId: executionResult.providerId,
      executionId: executionResult.executionId,
      output: executionResult.sanitizedOutput || executionResult.output || '',
      structuredOutput: executionResult.structuredOutput,
      provenance: {
        ...executionResult.provenance,
        agentName: agent.name,
        agentRole: agent.role,
        qualityRequirement: task.qualityRequirement,
      },
      confidence: 'UNKNOWN', // Truthful: provider does not supply objective probability
      actualCostUsd: costUsd,
      latencyMs: executionResult.latencyMs,
      status: isSuccess ? 'SUCCEEDED' : 'FAILED',
      strategyApplied: strategy,
      timestamp: new Date().toISOString(),
    };
  },

  /**
   * Aggregates multiple agent results according to a declared strategy.
   */
  aggregateMultiple(
    goalId: string,
    taskId: string,
    results: AggregatedAgentResult[],
    strategy: ResultAggregationStrategy
  ): AggregatedAgentResult {
    if (results.length === 0) {
      throw new Error('Cannot aggregate an empty result set.');
    }

    if (results.length === 1 || strategy === 'SINGLE_RESULT') {
      return results[0];
    }

    const totalLatency = results.reduce((acc, r) => acc + r.latencyMs, 0);
    const avgLatency = Math.round(totalLatency / results.length);

    // Sum costs if all known, else UNKNOWN
    let totalCost: number | 'UNKNOWN' = 0;
    for (const r of results) {
      if (typeof r.actualCostUsd === 'number') {
        (totalCost as number) += r.actualCostUsd;
      } else {
        totalCost = 'UNKNOWN';
        break;
      }
    }

    const primary = results[0];

    switch (strategy) {
      case 'MERGE': {
        const mergedOutputs = results
          .map((r) => `[${r.agentId} via ${r.providerId}]:\n${r.output}`)
          .join('\n\n---\n\n');

        const mergedStructured: Record<string, unknown> = {};
        results.forEach((r) => {
          if (r.structuredOutput) {
            Object.assign(mergedStructured, r.structuredOutput);
          }
        });

        const allSucceeded = results.every((r) => r.status === 'SUCCEEDED');

        return {
          aggregationId: `AGG-MERGE-${Date.now()}`,
          goalId,
          taskId,
          agentId: results.map((r) => r.agentId).join('+'),
          providerId: results.map((r) => r.providerId).join('+'),
          executionId: results.map((r) => r.executionId).join('+'),
          output: mergedOutputs,
          structuredOutput: Object.keys(mergedStructured).length > 0 ? mergedStructured : undefined,
          provenance: {
            strategy: 'MERGE',
            contributors: results.map((r) => ({
              agentId: r.agentId,
              providerId: r.providerId,
              executionId: r.executionId,
            })),
          },
          confidence: 'UNKNOWN',
          actualCostUsd: totalCost,
          latencyMs: avgLatency,
          status: allSucceeded ? 'SUCCEEDED' : 'FAILED',
          strategyApplied: 'MERGE',
          timestamp: new Date().toISOString(),
        };
      }

      case 'CONSENSUS_REQUIRED': {
        const matchingOutputs = results.every(
          (r) => r.output.trim() === primary.output.trim() && r.status === 'SUCCEEDED'
        );

        return {
          aggregationId: `AGG-CONSENSUS-${Date.now()}`,
          goalId,
          taskId,
          agentId: results.map((r) => r.agentId).join('+'),
          providerId: results.map((r) => r.providerId).join('+'),
          executionId: results.map((r) => r.executionId).join('+'),
          output: matchingOutputs ? primary.output : 'CONSENSUS_FAILED: Divergent agent outputs detected.',
          structuredOutput: matchingOutputs ? primary.structuredOutput : undefined,
          provenance: {
            strategy: 'CONSENSUS_REQUIRED',
            consensusAchieved: matchingOutputs,
            contributors: results.map((r) => ({
              agentId: r.agentId,
              providerId: r.providerId,
            })),
          },
          confidence: 'UNKNOWN',
          actualCostUsd: totalCost,
          latencyMs: avgLatency,
          status: matchingOutputs ? 'SUCCEEDED' : 'CONFLICT',
          strategyApplied: 'CONSENSUS_REQUIRED',
          timestamp: new Date().toISOString(),
        };
      }

      case 'HUMAN_REVIEW_REQUIRED': {
        return {
          aggregationId: `AGG-REVIEW-${Date.now()}`,
          goalId,
          taskId,
          agentId: primary.agentId,
          providerId: primary.providerId,
          executionId: primary.executionId,
          output: primary.output,
          structuredOutput: primary.structuredOutput,
          provenance: {
            strategy: 'HUMAN_REVIEW_REQUIRED',
            requiresReview: true,
          },
          confidence: 'UNKNOWN',
          actualCostUsd: totalCost,
          latencyMs: avgLatency,
          status: 'AWAITING_REVIEW',
          strategyApplied: 'HUMAN_REVIEW_REQUIRED',
          timestamp: new Date().toISOString(),
        };
      }

      default:
        return primary;
    }
  },
};
