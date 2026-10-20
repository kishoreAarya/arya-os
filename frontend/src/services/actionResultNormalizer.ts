/**
 * AryaOS V1 — Stage 15: Action Result Normalizer
 *
 * Normalizes disparate external capability responses into standard ActionResult contracts.
 * Enforces Zero Secret Leakage by sanitizing output data and errors.
 */

import {
  ActionRequest,
  ActionResult,
  ActionError,
  ActionExecutionStatus,
  ActionRetryCategory,
  ActionProvenance,
} from '../types/actionBus';
import { executionPersistence } from './executionPersistence';

export function createRequestFingerprint(request: ActionRequest): string {
  const source = `${request.capabilityId}:${request.operation}:${request.idempotencyKey}:${JSON.stringify(
    request.parameters
  )}`;
  let hash = 0;
  for (let i = 0; i < source.length; i++) {
    const char = source.charCodeAt(i);
    hash = (hash << 5) - hash + char;
    hash |= 0;
  }
  return 'fp_act_' + Math.abs(hash).toString(16).padStart(8, '0');
}

export class ActionResultNormalizer {
  /**
   * Normalizes a successful adapter output into a standard ActionResult.
   */
  public normalizeSuccess(
    request: ActionRequest,
    rawData: unknown,
    durationMs: number
  ): ActionResult {
    const fingerprint = createRequestFingerprint(request);
    const sanitizedData = executionPersistence.sanitizeForPersistence(rawData);

    const provenance: ActionProvenance = {
      actionId: request.actionId,
      capabilityId: request.capabilityId,
      requestFingerprint: fingerprint,
      missionId: request.context.missionId,
      goalId: request.context.goalId,
      decisionId: request.context.decisionId,
      agentId: request.context.agentId,
      timestamp: new Date().toISOString(),
    };

    return {
      actionId: request.actionId,
      capabilityId: request.capabilityId,
      success: true,
      status: 'SUCCEEDED',
      data: sanitizedData,
      metadata: {
        operation: request.operation,
        durationMs,
        normalizedAt: new Date().toISOString(),
      },
      provenance,
      durationMs,
    };
  }

  /**
   * Normalizes a failed execution into a standard ActionResult with structured ActionError.
   */
  public normalizeFailure(
    request: ActionRequest,
    error: unknown,
    category: ActionRetryCategory,
    durationMs: number,
    statusOverride?: ActionExecutionStatus
  ): ActionResult {
    const fingerprint = createRequestFingerprint(request);
    const rawMessage = error instanceof Error ? error.message : String(error || 'Action execution failed');
    const sanitizedMessage = typeof rawMessage === 'string'
      ? executionPersistence.sanitizeForPersistence(rawMessage)
      : 'Action execution failed';

    const actionError: ActionError = {
      code: `ERR_${category}`,
      message: sanitizedMessage,
      category,
      retryable: category === 'TRANSIENT' || category === 'TIMEOUT' || category === 'RATE_LIMIT',
      details: error instanceof Error && error.stack ? { stackSnippet: error.stack.slice(0, 200) } : undefined,
    };

    const provenance: ActionProvenance = {
      actionId: request.actionId,
      capabilityId: request.capabilityId,
      requestFingerprint: fingerprint,
      missionId: request.context.missionId,
      goalId: request.context.goalId,
      decisionId: request.context.decisionId,
      agentId: request.context.agentId,
      timestamp: new Date().toISOString(),
    };

    const status: ActionExecutionStatus = statusOverride || (category === 'TIMEOUT' ? 'TIMEOUT' : 'FAILED');

    return {
      actionId: request.actionId,
      capabilityId: request.capabilityId,
      success: false,
      status,
      data: null,
      metadata: {
        operation: request.operation,
        durationMs,
        normalizedAt: new Date().toISOString(),
      },
      error: actionError,
      provenance,
      durationMs,
    };
  }
}

export const actionResultNormalizer = new ActionResultNormalizer();
