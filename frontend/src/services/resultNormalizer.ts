/**
 * AryaOS V1 — Stage 06/07: Result Normalizer
 *
 * Normalizes disparate provider responses and errors into the unified ExecutionResult format.
 * Sanitizes errors to prevent secret leakage and guarantees honest telemetry reporting.
 */

import {
  ExecutionResult,
  GatewayExecutionState,
  ExecutionPlan,
  ExecutionProvenance,
} from '../types/intelligenceProvider';

export interface NormalizerOptions {
  executionId?: string;
  startedAt?: string;
  completedAt?: string;
  fallbackUsed?: boolean;
  retryCount?: number;
  executionMode?: 'REAL' | 'SIMULATED' | 'TEST';
}

export const resultNormalizer = {
  /**
   * Sanitizes strings to eliminate any potential secrets, bearer tokens, or sensitive patterns.
   */
  sanitizeText(raw: string | undefined): string {
    if (!raw) return '';
    return raw
      .replace(/Authorization:\s*(Bearer|Basic)\s+[^\s,;]+/gi, 'Authorization: $1 [REDACTED]')
      .replace(/Bearer\s+[A-Za-z0-9_\-\.]{8,}/gi, 'Bearer [REDACTED]')
      .replace(/AIza[0-9A-Za-z_\-]{35}/g, 'AIza[REDACTED]')
      .replace(/sk-ant-[A-Za-z0-9_\-]{20,}/g, 'sk-ant-[REDACTED]')
      .replace(/sk-[A-Za-z0-9_\-]{20,}/g, 'sk-[REDACTED]')
      .replace(/(api[_-]?key|token|secret|password|auth)=([^\s&'"]+)/gi, '$1=[REDACTED]')
      .replace(/([A-Za-z0-9_-]{28,})/g, (match) => {
        // Preserve standard uuid or sha256 hashes
        if (/^[0-9a-f]{8}-[0-9a-f]{4}/i.test(match) || /^[0-9a-f]{64}$/i.test(match)) {
          return match;
        }
        return match.length > 32 ? '[REDACTED_TOKEN]' : match;
      });
  },

  /**
   * Builds execution provenance record for complete audit trail.
   */
  buildProvenance(
    plan: ExecutionPlan,
    executionId: string,
    fallbackUsed: boolean,
    timestamp: string
  ): ExecutionProvenance {
    return {
      executionId,
      planId: plan.id,
      actionId: plan.actionId,
      sourceCommand: plan.contextPackage.userInput,
      sourceMemoryId: plan.contextPackage.memoryContext[0]?.id,
      sourceMemoryTitle: plan.contextPackage.memoryContext[0]?.title,
      contextMemoriesCount: plan.contextPackage.memoryContext.length,
      providerSelected: plan.providerName,
      modelSelected: plan.modelId,
      capability: plan.capability,
      fallbackUsed,
      fallbackProvider: plan.fallbackProviderId,
      timestamp,
    };
  },

  /**
   * Normalizes a successful execution into standard ExecutionResult.
   */
  normalizeSuccess(
    plan: ExecutionPlan,
    output: string,
    latencyMs: number,
    usage?: { inputTokens?: number; outputTokens?: number; costUsd?: number | null },
    structuredOutput?: Record<string, unknown>,
    metadata?: Record<string, unknown>,
    options?: NormalizerOptions
  ): ExecutionResult {
    const timestamp = options?.completedAt || new Date().toISOString();
    const executionId = options?.executionId || `EXEC-${Date.now()}-${Math.floor(Math.random() * 1000)}`;
    const fallbackUsed = Boolean(options?.fallbackUsed || metadata?.fallbackUsed);
    const retryCount = options?.retryCount ?? Number(metadata?.retryCount || 0);
    const sanitized = this.sanitizeText(output);

    const status: GatewayExecutionState = fallbackUsed ? 'FALLBACK_SUCCEEDED' : 'SUCCEEDED';

    return {
      executionId,
      planId: plan.id,
      status,
      providerId: plan.providerId,
      modelId: plan.modelId,
      capability: plan.capability,
      startedAt: options?.startedAt || new Date(Date.now() - latencyMs).toISOString(),
      completedAt: timestamp,
      latencyMs: Math.max(0, latencyMs),
      fallbackUsed,
      retryCount,
      output: sanitized,
      sanitizedOutput: sanitized,
      structuredOutput,
      routingRationale: plan.routingRationale,
      contextSummary: {
        memoriesCount: plan.contextPackage.memoryContext.length,
        tokenEstimate: plan.contextPackage.tokenEstimate,
        activeMemoryId: plan.contextPackage.memoryContext[0]?.id,
      },
      provenance: this.buildProvenance(plan, executionId, fallbackUsed, timestamp),
      executionMode: options?.executionMode || 'REAL',
      usage: {
        inputTokens: usage?.inputTokens,
        outputTokens: usage?.outputTokens,
        estimatedCost: usage?.costUsd !== undefined ? usage.costUsd : plan.estimatedCostMetadata.estimatedUsd,
        unitLabel: plan.capability.includes('GENERATION') ? 'units' : 'tokens',
      },
      metadata,
      timestamp,
    };
  },

  /**
   * Normalizes a provider error, timeout, or configuration requirement honestly.
   */
  normalizeFailure(
    plan: ExecutionPlan,
    status: GatewayExecutionState,
    error: string,
    latencyMs: number,
    metadata?: Record<string, unknown>,
    options?: NormalizerOptions
  ): ExecutionResult {
    const timestamp = options?.completedAt || new Date().toISOString();
    const executionId = options?.executionId || `EXEC-${Date.now()}-${Math.floor(Math.random() * 1000)}`;
    const fallbackUsed = Boolean(options?.fallbackUsed || metadata?.fallbackUsed);
    const retryCount = options?.retryCount ?? Number(metadata?.retryCount || 0);
    const sanitizedErr = this.sanitizeText(error);

    return {
      executionId,
      planId: plan.id,
      status,
      providerId: plan.providerId,
      modelId: plan.modelId,
      capability: plan.capability,
      startedAt: options?.startedAt || new Date(Date.now() - latencyMs).toISOString(),
      completedAt: timestamp,
      latencyMs: Math.max(0, latencyMs),
      fallbackUsed,
      retryCount,
      error: sanitizedErr,
      sanitizedError: sanitizedErr,
      routingRationale: plan.routingRationale,
      contextSummary: {
        memoriesCount: plan.contextPackage.memoryContext.length,
        tokenEstimate: plan.contextPackage.tokenEstimate,
        activeMemoryId: plan.contextPackage.memoryContext[0]?.id,
      },
      provenance: this.buildProvenance(plan, executionId, fallbackUsed, timestamp),
      executionMode: options?.executionMode || 'REAL',
      usage: {
        estimatedCost: null,
      },
      metadata,
      timestamp,
    };
  },
};
