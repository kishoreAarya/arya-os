/**
 * AryaOS V1 — Stage 15: Universal Action Bus Service
 *
 * The single governed execution boundary for external system capabilities.
 * Enforces validation, authorization, sandboxing, idempotency, resource governance,
 * timeout handling, audit trailing, persistence, and knowledge graph integration.
 *
 * CRITICAL INVARIANT:
 * - AI reasoning / LLM generation: Stage 07 executionGateway.execute()
 * - External action execution: Stage 15 actionBus.execute()
 * Neither boundary may bypass the other.
 */

import {
  ActionRequest,
  ActionResult,
  ActionAuditRecord,
  ActionPolicy,
  ActionRetryCategory,
  ActionExecutionStatus,
} from '../types/actionBus';
import { capabilityRegistry } from './capabilityRegistry';
import { adapterRegistry } from './capabilityAdapter';
import { actionAuthorizationService } from './actionAuthorizationService';
import { actionResultNormalizer, createRequestFingerprint } from './actionResultNormalizer';
import { actionReconciliationService } from './actionReconciliationService';
import { executionPersistence } from './executionPersistence';
import { executionJournal } from './executionJournal';
import { knowledgeGraph } from './knowledgeGraph';
import { connectorRegistry } from './connectorRegistry';
import { connectorHealthService } from './connectorHealthService';
import { connectorPermissionService } from './connectorPermissionService';

export interface ActionBusExecuteOptions {
  policy?: ActionPolicy;
  operatorApproval?: { approvedBy: string; signature?: string };
}

export class ActionBusService {
  private activeExecutions: Map<string, { abortController: AbortController; startTime: number }> = new Map();

  /**
   * Primary entry point for executing external capabilities.
   */
  public async execute(
    request: ActionRequest,
    options?: ActionBusExecuteOptions
  ): Promise<ActionResult> {
    const startTime = Date.now();
    const fingerprint = createRequestFingerprint(request);

    // Persist incoming request
    executionPersistence.saveActionRequest(request);

    // 1. Idempotency Check: Return cached result if already executed with same key
    if (request.idempotencyKey) {
      const existingResults = executionPersistence.getAllActionResults();
      const cached = existingResults.find(
        (r) => r.provenance?.requestFingerprint === fingerprint && r.success
      );
      if (cached) {
        return cached;
      }
    }

    // 2. Resolve Capability
    const capability = capabilityRegistry.getCapability(request.capabilityId);
    if (!capability) {
      const result = actionResultNormalizer.normalizeFailure(
        request,
        new Error(`Capability '${request.capabilityId}' is not registered in CapabilityRegistry`),
        'NOT_FOUND',
        Date.now() - startTime
      );
      this.recordAudit(request, fingerprint, 'DENIED', 'LOW', result);
      return result;
    }

    // 3. Check Capability Availability
    if (capability.availability === 'OFFLINE') {
      const result = actionResultNormalizer.normalizeFailure(
        request,
        new Error(`Capability '${request.capabilityId}' is currently OFFLINE`),
        'PERMANENT',
        Date.now() - startTime,
        'UNAVAILABLE'
      );
      this.recordAudit(request, fingerprint, 'DENIED', capability.riskLevel, result);
      return result;
    }

    // 4. Schema Validation
    const validation = capabilityRegistry.validateParameters(request.capabilityId, request.parameters);
    if (!validation.valid) {
      const result = actionResultNormalizer.normalizeFailure(
        request,
        new Error(`Schema validation failed: ${validation.errors.join('; ')}`),
        'VALIDATION',
        Date.now() - startTime
      );
      this.recordAudit(request, fingerprint, 'DENIED', capability.riskLevel, result);
      return result;
    }

    // 5. Authorization & Sandbox Check
    const auth = actionAuthorizationService.authorize(
      request,
      options?.policy,
      options?.operatorApproval
    );

    if (!auth.authorized) {
      const category: ActionRetryCategory = auth.status === 'REQUIRES_APPROVAL' ? 'AUTHORIZATION' : 'PERMISSION';
      const result = actionResultNormalizer.normalizeFailure(
        request,
        new Error(`Action authorization failed: ${auth.reason}`),
        category,
        Date.now() - startTime,
        auth.status === 'REQUIRES_APPROVAL' ? 'REQUIRES_APPROVAL' : 'DENIED'
      );
      this.recordAudit(request, fingerprint, auth.status, auth.riskLevel, result);
      return result;
    }

    // 5b. Connector Fabric & Identity/Permission Verification (Stage 16)
    const associatedConnector = connectorRegistry
      .listConnectors()
      .find((conn) => conn.capabilities.some((c) => c.capabilityId === request.capabilityId));

    if (associatedConnector) {
      // Health & Credential Readiness Gatekeeper
      const readiness = connectorHealthService.evaluateActionReadiness(associatedConnector.id);
      if (!readiness.ready) {
        const category: ActionRetryCategory =
          readiness.status === 'REQUIRES_CONFIGURATION' ? 'AUTHORIZATION' : 'PERMISSION';
        const statusOverride: ActionExecutionStatus =
          readiness.status === 'REQUIRES_CONFIGURATION'
            ? 'REQUIRES_APPROVAL'
            : readiness.status === 'UNAVAILABLE'
            ? 'UNAVAILABLE'
            : 'DENIED';

        const result = actionResultNormalizer.normalizeFailure(
          request,
          new Error(`Connector Fabric Gatekeeper: ${readiness.reason}`),
          category,
          Date.now() - startTime,
          statusOverride
        );
        this.recordAudit(request, fingerprint, 'DENIED', capability.riskLevel, result);
        return result;
      }

      // Scoped Permission & Agent/Mission Grant Check
      const resourceTarget =
        (request.parameters.path as string) ||
        (request.parameters.repository as string) ||
        (request.parameters.url as string) ||
        (request.parameters.channel as string) ||
        undefined;

      const hasMissionGrants = request.context.missionId
        ? executionPersistence.getAllMissionCapabilityGrants(request.context.missionId).length > 0
        : false;

      const permCheck = connectorPermissionService.evaluateAuthorization({
        connectorId: associatedConnector.id,
        capabilityId: request.capabilityId,
        operation: request.operation,
        resourceTarget,
        agentId: request.context.agentId,
        missionId: hasMissionGrants ? request.context.missionId : undefined,
        effectiveRisk: auth.riskLevel,
        operatorApproval: options?.operatorApproval,
      });

      if (!permCheck.authorized) {
        const isApprovalRequired =
          permCheck.reason?.includes('signoff') || permCheck.reason?.includes('approval');
        const category: ActionRetryCategory = isApprovalRequired ? 'AUTHORIZATION' : 'PERMISSION';
        const statusOverride: ActionExecutionStatus = isApprovalRequired ? 'REQUIRES_APPROVAL' : 'DENIED';

        const result = actionResultNormalizer.normalizeFailure(
          request,
          new Error(`Connector Permission Denied: ${permCheck.reason}`),
          category,
          Date.now() - startTime,
          statusOverride
        );
        this.recordAudit(request, fingerprint, statusOverride, capability.riskLevel, result);
        return result;
      }
    }

    // 6. Resolve Adapter
    const adapter = adapterRegistry.getAdapter(request.capabilityId);
    if (!adapter) {
      const result = actionResultNormalizer.normalizeFailure(
        request,
        new Error(`No adapter found for capability '${request.capabilityId}'`),
        'NOT_FOUND',
        Date.now() - startTime
      );
      this.recordAudit(request, fingerprint, auth.status, auth.riskLevel, result);
      return result;
    }

    // 7. Execute Adapter with Timeout & Retries
    const timeoutMs = request.timeoutMs || capability.timeoutMs || 5000;
    const maxRetries = capability.retryPolicy.maxRetries || 0;
    let attempt = 0;
    let lastError: unknown = null;

    const abortController = new AbortController();
    this.activeExecutions.set(request.actionId, { abortController, startTime });

    while (attempt <= maxRetries) {
      try {
        const rawOutput = await Promise.race([
          adapter.execute(request),
          new Promise((_, reject) =>
            setTimeout(() => reject(new Error(`Action execution timed out after ${timeoutMs}ms`)), timeoutMs)
          ),
        ]);

        const durationMs = Date.now() - startTime;
        this.activeExecutions.delete(request.actionId);

        const result = actionResultNormalizer.normalizeSuccess(request, rawOutput, durationMs);
        executionPersistence.saveActionResult(result);
        this.recordAudit(request, fingerprint, auth.status, auth.riskLevel, result);

        // Memory & Knowledge Graph Integration
        this.emitActionKnowledge(request, result);

        // Journal Event Emission
        if (request.context.goalId) {
          executionJournal.appendEvent({
            goalId: request.context.goalId,
            actionId: request.actionId,
            eventType: 'ACTION_SUCCEEDED',
            newState: 'SUCCEEDED',
            payload: { capabilityId: request.capabilityId, operation: request.operation },
          });
        }

        return result;
      } catch (err) {
        lastError = err;
        const errMsg = err instanceof Error ? err.message : String(err);
        const isTimeout = errMsg.includes('timed out');
        const retryCategory: ActionRetryCategory = isTimeout
          ? 'TIMEOUT'
          : errMsg.includes('rate limit')
          ? 'RATE_LIMIT'
          : 'TRANSIENT';

        // Check if retry is safe for this capability and category
        const isRetrySafe =
          capability.retryPolicy.retryableCategories.includes(retryCategory) &&
          auth.riskLevel !== 'CRITICAL' &&
          request.capabilityId !== 'filesystem.write'; // Never blindly retry filesystem writes

        if (attempt < maxRetries && isRetrySafe) {
          attempt++;
          await new Promise((r) => setTimeout(r, capability.retryPolicy.backoffMs * attempt));
          continue;
        }

        break;
      }
    }

    this.activeExecutions.delete(request.actionId);
    const durationMs = Date.now() - startTime;

    // 8. Uncertain State Reconciliation
    const reconciliation = await actionReconciliationService.reconcile(request);
    if (reconciliation.reconciled && reconciliation.reconciledResult) {
      this.recordAudit(request, fingerprint, auth.status, auth.riskLevel, reconciliation.reconciledResult);
      return reconciliation.reconciledResult;
    }

    const errObj = lastError as any;
    const errorMsg = lastError instanceof Error ? lastError.message : String(lastError);
    const isRateLimit =
      errObj?.code === 'RATE_LIMITED' ||
      errObj?.statusCode === 429 ||
      /rate limit/i.test(errorMsg);
    const isAuth =
      errObj?.statusCode === 401 ||
      errObj?.statusCode === 403 ||
      errObj?.code === 'UNAUTHORIZED' ||
      errObj?.code === 'FORBIDDEN' ||
      /unauthorized|forbidden|authentication|expired/i.test(errorMsg);
    const isTimeout =
      errorMsg.includes('timed out') ||
      errObj?.code === 'TIMEOUT' ||
      errObj?.statusCode === 408;

    const category: ActionRetryCategory = isTimeout
      ? 'TIMEOUT'
      : isRateLimit
      ? 'RATE_LIMIT'
      : isAuth
      ? 'AUTHORIZATION'
      : 'TRANSIENT';
    const statusOverride: ActionExecutionStatus = isTimeout
      ? 'TIMEOUT'
      : isAuth
      ? 'REQUIRES_APPROVAL'
      : 'FAILED';

    const failureResult = actionResultNormalizer.normalizeFailure(
      request,
      lastError,
      category,
      durationMs,
      statusOverride
    );

    executionPersistence.saveActionResult(failureResult);
    this.recordAudit(request, fingerprint, auth.status, auth.riskLevel, failureResult);

    if (request.context.goalId) {
      executionJournal.appendEvent({
        goalId: request.context.goalId,
        actionId: request.actionId,
        eventType: 'ACTION_FAILED',
        newState: failureResult.status,
        payload: { capabilityId: request.capabilityId, error: failureResult.error?.message },
      });
    }

    return failureResult;
  }

  /**
   * Cancels a currently executing action.
   */
  public cancel(actionId: string): boolean {
    const active = this.activeExecutions.get(actionId);
    if (active) {
      active.abortController.abort();
      this.activeExecutions.delete(actionId);
      return true;
    }
    return false;
  }

  /**
   * Helper: Records sanitized audit trail in persistence.
   */
  private recordAudit(
    request: ActionRequest,
    fingerprint: string,
    authState: string,
    riskLevel: ActionAuditRecord['riskLevel'],
    result: ActionResult
  ): void {
    const auditRecord: ActionAuditRecord = {
      actionId: request.actionId,
      capabilityId: request.capabilityId,
      requestFingerprint: fingerprint,
      authorizationState: authState,
      riskLevel,
      executionState: result.status,
      startTime: request.context.timestamp,
      endTime: new Date().toISOString(),
      resultStatus: result.status,
      errorCategory: result.error?.category,
      provenance: result.provenance,
    };
    executionPersistence.saveActionAuditRecord(auditRecord);
  }

  /**
   * Helper: Ingests action result into Stage 13 Strategic Knowledge Graph.
   */
  private emitActionKnowledge(request: ActionRequest, result: ActionResult): void {
    try {
      const actionNodeId = `node_action_${request.actionId}`;
      knowledgeGraph.addNode({
        id: actionNodeId,
        type: 'ACTION',
        label: `Action: ${request.capabilityId} (${request.operation})`,
        confidence: 'HIGH',
        status: 'VERIFIED',
        createdAt: new Date().toISOString(),
        updatedAt: new Date().toISOString(),
        provenance: {
          source: {
            sourceType: 'STAGE09_JOURNAL',
            sourceId: request.actionId,
            timestamp: new Date().toISOString(),
          },
          extractedAt: new Date().toISOString(),
          derivedBy: 'actionBusService',
          missionId: request.context.missionId,
          goalId: request.context.goalId,
          actionId: request.actionId,
        },
        metadata: {
          capabilityId: request.capabilityId,
          operation: request.operation,
          success: result.success,
        },
      });

      if (request.context.missionId) {
        if (!knowledgeGraph.getNode(request.context.missionId)) {
          knowledgeGraph.addNode({
            id: request.context.missionId,
            type: 'MISSION',
            label: `Mission: ${request.context.missionId}`,
            confidence: 'HIGH',
            status: 'VERIFIED',
            createdAt: new Date().toISOString(),
            updatedAt: new Date().toISOString(),
            provenance: {
              source: {
                sourceType: 'STAGE09_JOURNAL',
                sourceId: request.context.missionId,
                timestamp: new Date().toISOString(),
              },
              extractedAt: new Date().toISOString(),
              derivedBy: 'actionBusService',
            },
          });
        }

        knowledgeGraph.addEdge({
          id: `edge_m_act_${request.actionId}`,
          source: request.context.missionId,
          target: actionNodeId,
          relation: 'EXECUTED_ACTION',
          confidence: 'HIGH',
          weight: 1.0,
          createdAt: new Date().toISOString(),
          provenance: {
            source: {
              sourceType: 'STAGE09_JOURNAL',
              sourceId: request.actionId,
              timestamp: new Date().toISOString(),
            },
            extractedAt: new Date().toISOString(),
            derivedBy: 'actionBusService',
          },
        });
      }
    } catch {
      // Graceful fallback if node already exists
    }
  }
}

export const actionBusService = new ActionBusService();
