/**
 * AryaOS V1 — Stage 07: Real Provider Execution Gateway
 *
 * The single controlled boundary through which AryaOS dispatches all provider-backed
 * intelligence tasks. Enforces:
 * - Single boundary abstraction (zero direct UI-to-provider calls)
 * - Deterministic execution states
 * - Idempotency and duplicate submission prevention
 * - Pre-execution capability negotiation
 * - Secret hygiene and output sanitization
 * - Controlled timeout, cancellation, and automated fallback
 * - Memory provenance loop closure
 */

import {
  ExecutionPlan,
  ExecutionResult,
  GatewayExecutionState,
  ProviderHealthStatus,
  ProviderAdapter,
  ProviderCapabilityType,
} from '../types/intelligenceProvider';
import { CommandContext, MemoryEvent } from '../types/spatialCommand';
import { resultNormalizer } from './resultNormalizer';
import { providerExecutionAdapter } from './providerExecutionAdapter';
import { actionProposalService } from './actionProposalService';
import { providerRegistry } from './providerRegistry';

export interface GatewayExecutionOptions {
  signal?: AbortSignal;
  maxFallbackDepth?: number;
  executionMode?: 'REAL' | 'SIMULATED' | 'TEST';
  onStateChange?: (state: GatewayExecutionState) => void;
}

class ExecutionGateway {
  private inFlightExecutions: Map<string, Promise<ExecutionResult>> = new Map();
  private completedExecutions: Map<string, ExecutionResult> = new Map();
  private providerHealthMap: Map<string, ProviderHealthStatus> = new Map();

  constructor() {
    this.resetState();
  }

  /**
   * Resets gateway in-flight records and caches (useful for tests).
   */
  public resetState(): void {
    this.inFlightExecutions.clear();
    this.completedExecutions.clear();
    this.providerHealthMap.clear();
  }

  /**
   * Returns a completed execution result by idempotency key if available.
   */
  public getCompletedExecution(idempotencyKey: string): ExecutionResult | undefined {
    return this.completedExecutions.get(idempotencyKey);
  }

  /**
   * Checks if an execution is currently in-flight for an idempotency key.
   */
  public hasInFlightExecution(idempotencyKey: string): boolean {
    return this.inFlightExecutions.has(idempotencyKey);
  }

  /**
   * Generates a deterministic idempotency key for an action and plan.
   */
  public generateIdempotencyKey(plan: ExecutionPlan): string {
    return `IDEMP-${plan.actionId || plan.id}-${plan.capability}-${plan.providerId}`;
  }

  /**
   * Returns current health of a provider.
   */
  public getProviderHealth(providerId: string): ProviderHealthStatus {
    const recorded = this.providerHealthMap.get(providerId);
    if (recorded) return recorded;

    const p = providerRegistry.getProvider(providerId);
    if (!p) return 'UNKNOWN';
    if (p.availability === 'UNAVAILABLE') return 'UNAVAILABLE';
    if (p.availability === 'CONFIGURATION_REQUIRED') return 'UNKNOWN';
    return 'AVAILABLE';
  }

  /**
   * Updates health status for a provider based on execution feedback.
   */
  public setProviderHealth(providerId: string, health: ProviderHealthStatus): void {
    this.providerHealthMap.set(providerId, health);
  }

  /**
   * Validates capability negotiation prior to execution.
   */
  public validateCapability(
    providerId: string,
    capability: ProviderCapabilityType
  ): { valid: boolean; reason?: string } {
    const provider = providerRegistry.getProvider(providerId);
    if (!provider) {
      return { valid: false, reason: `Provider '${providerId}' is not registered in the system.` };
    }
    if (!provider.capabilities.includes(capability)) {
      return {
        valid: false,
        reason: `Capability mismatch: Provider '${provider.name}' does not support requested capability '${capability}'. Supported: [${provider.capabilities.join(', ')}].`,
      };
    }
    return { valid: true };
  }

  /**
   * Single controlled entrypoint for executing any provider-backed intelligence task.
   */
  public async execute(
    plan: ExecutionPlan,
    context?: CommandContext,
    options: GatewayExecutionOptions = {}
  ): Promise<ExecutionResult> {
    const startTime = Date.now();
    const startedAt = new Date().toISOString();
    const executionId = `EXEC-${Date.now()}-${Math.floor(Math.random() * 1000)}`;
    const idempotencyKey = this.generateIdempotencyKey(plan);
    const maxFallbackDepth = options.maxFallbackDepth ?? 2;
    const executionMode = options.executionMode || 'REAL';

    // 1. Early Cancellation Check
    if (options.signal?.aborted) {
      const res = resultNormalizer.normalizeFailure(
        plan,
        'CANCELLED',
        'Execution cancelled by operator prior to dispatch.',
        0,
        undefined,
        { executionId, startedAt, executionMode }
      );
      this.recordEventFromExecution(plan, res);
      return res;
    }

    // 2. Idempotency Check: Return in-flight execution if same action intent is currently executing
    const existingInFlight = this.inFlightExecutions.get(idempotencyKey);
    if (existingInFlight) {
      return existingInFlight;
    }

    // Wrap execution in tracked Promise for idempotency
    const executionPromise = (async (): Promise<ExecutionResult> => {
      try {
        options.onStateChange?.('EXECUTING');

        // 3. Pre-execution Capability Negotiation
        const capNegotiation = this.validateCapability(plan.providerId, plan.capability);
        if (!capNegotiation.valid) {
          const res = resultNormalizer.normalizeFailure(
            plan,
            'FAILED',
            capNegotiation.reason || 'Capability negotiation failed.',
            Date.now() - startTime,
            { failureType: 'CAPABILITY_MISMATCH' },
            { executionId, startedAt, executionMode }
          );
          this.recordEventFromExecution(plan, res);
          return res;
        }

        // 4. Provider Adapter Lookup
        const adapter = providerExecutionAdapter.getAdapter(plan.providerId);
        if (!adapter) {
          const res = resultNormalizer.normalizeFailure(
            plan,
            'UNAVAILABLE',
            `No execution adapter registered for provider '${plan.providerId}'.`,
            Date.now() - startTime,
            { failureType: 'ADAPTER_NOT_FOUND' },
            { executionId, startedAt, executionMode }
          );
          this.recordEventFromExecution(plan, res);
          return res;
        }

        // 5. Configuration Validation
        const config = adapter.validateConfiguration();
        if (!config.isValid) {
          const res = resultNormalizer.normalizeFailure(
            plan,
            'CONFIGURATION_REQUIRED',
            config.reason || `CONFIGURATION_REQUIRED: Credentials missing for provider '${plan.providerId}'.`,
            Date.now() - startTime,
            { failureType: 'CONFIGURATION_REQUIRED' },
            { executionId, startedAt, executionMode }
          );
          this.recordEventFromExecution(plan, res);
          return res;
        }

        // 6. Execute Primary Provider with Timeout & Cancellation
        let primaryResult: ExecutionResult;
        const timeoutMs = (plan.timeoutSeconds || 30) * 1000;
        let timeoutId: ReturnType<typeof setTimeout> | undefined;

        try {
          const timeoutPromise = new Promise<ExecutionResult>((resolve) => {
            timeoutId = setTimeout(() => {
              this.setProviderHealth(plan.providerId, 'DEGRADED');
              resolve(
                resultNormalizer.normalizeFailure(
                  plan,
                  'TIMEOUT',
                  `Provider '${plan.providerId}' timed out after ${plan.timeoutSeconds}s.`,
                  timeoutMs,
                  { failureType: 'TIMEOUT' },
                  { executionId, startedAt, executionMode }
                )
              );
            }, timeoutMs);
          });

          const abortPromise = new Promise<ExecutionResult>((resolve) => {
            if (options.signal) {
              options.signal.addEventListener('abort', () => {
                resolve(
                  resultNormalizer.normalizeFailure(
                    plan,
                    'CANCELLED',
                    'Execution cancelled by operator during processing.',
                    Date.now() - startTime,
                    { failureType: 'OPERATOR_CANCELLED' },
                    { executionId, startedAt, executionMode }
                  )
                );
              });
            }
          });

          const adapterPromise = (async () => {
            const raw = await adapter.execute(plan, options.signal, { executionMode });
            const latency = Date.now() - startTime;
            if ('planId' in raw && raw.status) {
              return raw as ExecutionResult;
            }
            if (raw.status === 'SUCCEEDED') {
              this.setProviderHealth(plan.providerId, 'AVAILABLE');
              return resultNormalizer.normalizeSuccess(
                plan,
                raw.output || '',
                latency,
                raw.usage,
                raw.structuredOutput,
                raw.metadata,
                { executionId, startedAt, executionMode }
              );
            }
            if (raw.status === 'CONFIGURATION_REQUIRED') {
              return resultNormalizer.normalizeFailure(
                plan,
                'CONFIGURATION_REQUIRED',
                raw.error || 'Configuration required.',
                latency,
                raw.metadata,
                { executionId, startedAt, executionMode }
              );
            }
            if (raw.status === 'TIMEOUT') {
              this.setProviderHealth(plan.providerId, 'DEGRADED');
              return resultNormalizer.normalizeFailure(
                plan,
                'TIMEOUT',
                raw.error || 'Timeout occurred.',
                latency,
                raw.metadata,
                { executionId, startedAt, executionMode }
              );
            }
            if (raw.status === 'UNAVAILABLE') {
              this.setProviderHealth(plan.providerId, 'UNAVAILABLE');
              return resultNormalizer.normalizeFailure(
                plan,
                'UNAVAILABLE',
                raw.error || 'Provider unavailable.',
                latency,
                raw.metadata,
                { executionId, startedAt, executionMode }
              );
            }
            if (raw.status === 'CANCELLED') {
              return resultNormalizer.normalizeFailure(
                plan,
                'CANCELLED',
                raw.error || 'Execution cancelled.',
                latency,
                raw.metadata,
                { executionId, startedAt, executionMode }
              );
            }
            // FAILED
            if (raw.error?.includes('429') || raw.error?.includes('rate limit')) {
              this.setProviderHealth(plan.providerId, 'RATE_LIMITED');
            } else {
              this.setProviderHealth(plan.providerId, 'DEGRADED');
            }
            return resultNormalizer.normalizeFailure(
              plan,
              'FAILED',
              raw.error || 'Provider execution failed.',
              latency,
              raw.metadata,
              { executionId, startedAt, executionMode }
            );
          })().catch((err: unknown) => {
            const errStr = err instanceof Error ? err.message : String(err);
            if (errStr.includes('429') || errStr.includes('rate limit')) {
              this.setProviderHealth(plan.providerId, 'RATE_LIMITED');
            } else {
              this.setProviderHealth(plan.providerId, 'DEGRADED');
            }
            return resultNormalizer.normalizeFailure(
              plan,
              'FAILED',
              `Unhandled provider error: ${errStr}`,
              Date.now() - startTime,
              { failureType: 'UNHANDLED_EXCEPTION' },
              { executionId, startedAt, executionMode }
            );
          });

          primaryResult = await Promise.race([adapterPromise, timeoutPromise, abortPromise]);
        } finally {
          if (timeoutId) clearTimeout(timeoutId);
        }

        // 7. Check if Primary Execution Succeeded or was explicitly Cancelled
        if (
          primaryResult.status === 'SUCCEEDED' ||
          primaryResult.status === 'CANCELLED' ||
          primaryResult.status === 'CONFIGURATION_REQUIRED'
        ) {
          options.onStateChange?.(primaryResult.status);
          this.recordEventFromExecution(plan, primaryResult);
          return primaryResult;
        }

        // 8. Automated Fallback Chain
        const canFallback =
          (primaryResult.status === 'FAILED' ||
            primaryResult.status === 'TIMEOUT' ||
            primaryResult.status === 'UNAVAILABLE') &&
          plan.fallbackProviderId &&
          plan.fallbackProviderId !== plan.providerId &&
          maxFallbackDepth > 0;

        if (!canFallback) {
          options.onStateChange?.(primaryResult.status);
          this.recordEventFromExecution(plan, primaryResult);
          return primaryResult;
        }

        // Transition to FALLBACK_EXECUTING
        options.onStateChange?.('FALLBACK_EXECUTING');

        const fallbackAdapter = providerExecutionAdapter.getAdapter(plan.fallbackProviderId!);
        if (!fallbackAdapter) {
          const fallbackFailedResult = resultNormalizer.normalizeFailure(
            plan,
            'FALLBACK_FAILED',
            `Primary provider '${plan.providerId}' failed (${primaryResult.error}), and fallback provider '${plan.fallbackProviderId}' has no registered adapter.`,
            Date.now() - startTime,
            { primaryError: primaryResult.error },
            { executionId, startedAt, fallbackUsed: true, executionMode }
          );
          options.onStateChange?.('FALLBACK_FAILED');
          this.recordEventFromExecution(plan, fallbackFailedResult);
          return fallbackFailedResult;
        }

        const fallbackPlan: ExecutionPlan = {
          ...plan,
          id: `${plan.id}-FALLBACK`,
          providerId: plan.fallbackProviderId!,
          modelId: plan.fallbackModelId || 'default',
        };

        const fallbackStartTime = Date.now();
        try {
          const rawFallback = await fallbackAdapter.execute(fallbackPlan, options.signal, { executionMode });
          const totalLatency = Date.now() - startTime;

          if (rawFallback.status === 'SUCCEEDED') {
            const fallbackSuccess = resultNormalizer.normalizeSuccess(
              fallbackPlan,
              rawFallback.output || '',
              totalLatency,
              rawFallback.usage,
              rawFallback.structuredOutput,
              {
                ...rawFallback.metadata,
                fallbackUsed: true,
                originalProvider: plan.providerId,
                primaryFailureReason: primaryResult.error,
              },
              { executionId, startedAt, fallbackUsed: true, retryCount: 1, executionMode }
            );
            options.onStateChange?.('FALLBACK_SUCCEEDED');
            this.recordEventFromExecution(fallbackPlan, fallbackSuccess);
            return fallbackSuccess;
          }

          // Fallback also failed
          const fallbackFailedResult = resultNormalizer.normalizeFailure(
            fallbackPlan,
            'FALLBACK_FAILED',
            `Both primary '${plan.providerId}' (${primaryResult.error}) and fallback '${fallbackPlan.providerId}' failed: ${rawFallback.error || 'Unknown error'}`,
            totalLatency,
            {
              primaryError: primaryResult.error,
              fallbackError: rawFallback.error,
            },
            { executionId, startedAt, fallbackUsed: true, retryCount: 1, executionMode }
          );
          options.onStateChange?.('FALLBACK_FAILED');
          this.recordEventFromExecution(fallbackPlan, fallbackFailedResult);
          return fallbackFailedResult;
        } catch (fbErr: unknown) {
          const fbErrStr = fbErr instanceof Error ? fbErr.message : String(fbErr);
          const fallbackFailedResult = resultNormalizer.normalizeFailure(
            fallbackPlan,
            'FALLBACK_FAILED',
            `Both primary '${plan.providerId}' (${primaryResult.error}) and fallback '${fallbackPlan.providerId}' failed: ${fbErrStr}`,
            Date.now() - startTime,
            { primaryError: primaryResult.error, fallbackError: fbErrStr },
            { executionId, startedAt, fallbackUsed: true, retryCount: 1, executionMode }
          );
          options.onStateChange?.('FALLBACK_FAILED');
          this.recordEventFromExecution(fallbackPlan, fallbackFailedResult);
          return fallbackFailedResult;
        }
      } finally {
        this.inFlightExecutions.delete(idempotencyKey);
      }
    })();

    this.inFlightExecutions.set(idempotencyKey, executionPromise);
    const finalResult = await executionPromise;
    this.completedExecutions.set(idempotencyKey, finalResult);
    return finalResult;
  }

  /**
   * Appends execution result to the semantic memory event ledger with complete provenance.
   */
  private recordEventFromExecution(plan: ExecutionPlan, result: ExecutionResult): void {
    const memoryEvent: MemoryEvent = {
      id: `EVT-GATEWAY-${Date.now()}-${Math.floor(Math.random() * 1000)}`,
      type: `INTELLIGENCE_GATEWAY_${result.status}`,
      sourceMemoryId: result.provenance.sourceMemoryId,
      sourceMemoryTitle: result.provenance.sourceMemoryTitle,
      action: plan.actionClass,
      timestamp: result.completedAt || result.timestamp,
      status:
        result.status === 'SUCCEEDED' || result.status === 'FALLBACK_SUCCEEDED'
          ? 'EXECUTED'
          : result.status === 'CANCELLED'
          ? 'RECORDED'
          : 'PLANNED',
      resultSummary:
        result.status === 'SUCCEEDED' || result.status === 'FALLBACK_SUCCEEDED'
          ? `Executed via ${result.providerId} (${result.modelId}) in ${result.latencyMs}ms. Fallback used: ${result.fallbackUsed ? 'YES' : 'NO'}.`
          : `Execution ${result.status} on ${result.providerId}: ${result.sanitizedError || result.error || 'N/A'}`,
      relatedEntities: [
        result.providerId.toUpperCase(),
        plan.capability,
        ...plan.contextPackage.entityContext.map((e) => e.name),
      ],
      metadata: {
        executionId: result.executionId,
        planId: plan.id,
        provider: result.providerId,
        model: result.modelId,
        capability: plan.capability,
        latencyMs: result.latencyMs,
        fallbackUsed: result.fallbackUsed,
        retryCount: result.retryCount,
        usage: result.usage,
        error: result.sanitizedError || result.error,
        executionMode: result.executionMode,
        provenance: result.provenance,
      },
    };

    actionProposalService.recordMemoryEvent(memoryEvent);
  }
}

export const executionGateway = new ExecutionGateway();
