/**
 * AryaOS V1 — Stage 21: Governance Context Service
 *
 * Constructs a bounded, sanitized GovernanceContext from incoming GovernanceRequests.
 * Strictly prevents credential leakage, prototype pollution, oversized context injection,
 * and unbounded memory graph traversal.
 */

import {
  GovernanceRequest,
  GovernanceContext,
} from '../types/governanceControlPlane';
import { PolicyScopeType } from '../types/policyIntelligence';
import { ActionRiskLevel, ActionRequest } from '../types/actionBus';
import { capabilityRegistry } from './capabilityRegistry';

export class GovernanceContextService {
  private readonly SENSITIVE_KEY_PATTERNS = [
    /auth/i,
    /token/i,
    /key/i,
    /secret/i,
    /password/i,
    /credential/i,
    /bearer/i,
    /private/i,
  ];

  private readonly DANGEROUS_PROTO_KEYS = new Set(['__proto__', 'constructor', 'prototype']);
  private readonly MAX_DEPTH = 3;
  private readonly MAX_KEYS = 50;

  /**
   * Builds a clean, bounded GovernanceContext for policy evaluation.
   */
  public buildContext(
    request: GovernanceRequest,
    runtimeOverrides?: Partial<GovernanceContext>
  ): GovernanceContext {
    if (!request || !request.requestId || !request.actor) {
      throw new Error('Invalid GovernanceRequest: missing requestId or actor');
    }

    const sanitizedParameters = this.sanitizeObject(request.parameters || {});
    const scopeType = this.deriveScopeType(request);
    const targetId = this.deriveTargetId(request, scopeType);

    const correlationId =
      request.correlationId ||
      `corr_${request.requestId}_${Date.now()}_${Math.random().toString(36).substring(2, 6)}`;

    const context: GovernanceContext = {
      requestId: request.requestId,
      correlationId,
      actor: {
        actorId: request.actor.actorId,
        actorType: request.actor.actorType,
        role: request.actor.role || 'STANDARD_OPERATOR',
        ipAddress: request.actor.ipAddress,
      },
      scopeType,
      targetId,
      capability: request.capabilityId,
      actionType: request.actionType,
      missionId: request.missionId,
      goalId: request.goalId,
      triggerId: request.triggerId,
      connectorId: request.connectorId,
      providerId: request.providerId,
      riskLevel: request.riskLevel || 'LOW',
      sanitizedParameters,
      currentMissionState: runtimeOverrides?.currentMissionState,
      currentConnectorState: runtimeOverrides?.currentConnectorState,
      currentPermissionScopes: runtimeOverrides?.currentPermissionScopes || [],
      activeConcurrentActions: runtimeOverrides?.activeConcurrentActions || 0,
      activeConcurrentAgents: runtimeOverrides?.activeConcurrentAgents || 0,
      costUsd: runtimeOverrides?.costUsd || 0,
      tokenCount: runtimeOverrides?.tokenCount || 0,
      requestFrequency: runtimeOverrides?.requestFrequency || 0,
      timestamp: request.timestamp || Date.now(),
      ...this.filterAllowedOverrides(runtimeOverrides || {}),
    };

    return Object.freeze(context);
  }

  /**
   * Derives primary policy scope type from request attributes.
   */
  private deriveScopeType(request: GovernanceRequest): PolicyScopeType {
    if (request.connectorId) return 'CONNECTOR';
    if (request.triggerId) return 'TRIGGER';
    if (request.missionId) return 'MISSION';
    if (request.actor?.actorType === 'AUTONOMOUS_AGENT' || request.actor?.actorId?.startsWith('agent-')) return 'AGENT';
    if (request.providerId) return 'PROVIDER';
    if (request.actionType === 'RESOURCE_ALLOCATION' || request.actionType === 'RESOURCE_LEASE') return 'RESOURCE';
    return 'SYSTEM';
  }

  /**
   * Derives specific target ID for the policy scope.
   */
  private deriveTargetId(request: GovernanceRequest, scopeType: PolicyScopeType): string | undefined {
    switch (scopeType) {
      case 'CONNECTOR':
        return request.connectorId;
      case 'TRIGGER':
        return request.triggerId;
      case 'MISSION':
        return request.missionId;
      case 'AGENT':
        return request.actor.actorId;
      case 'PROVIDER':
        return request.providerId;
      default:
        return undefined;
    }
  }

  /**
   * Recursively sanitizes an object, stripping secrets and blocking prototype pollution.
   */
  public sanitizeObject(
    obj: Record<string, unknown>,
    depth = 0
  ): Record<string, unknown> {
    if (depth > this.MAX_DEPTH || !obj || typeof obj !== 'object' || Array.isArray(obj)) {
      return {};
    }

    const clean: Record<string, unknown> = {};
    let keyCount = 0;

    for (const [key, value] of Object.entries(obj)) {
      if (keyCount >= this.MAX_KEYS) break;

      // Defense against prototype pollution
      if (this.DANGEROUS_PROTO_KEYS.has(key)) {
        continue;
      }

      // Defense against secret leakage
      if (this.SENSITIVE_KEY_PATTERNS.some((pattern) => pattern.test(key))) {
        continue;
      }

      if (value === null || value === undefined) {
        clean[key] = value;
      } else if (typeof value === 'string' || typeof value === 'number' || typeof value === 'boolean') {
        clean[key] = value;
      } else if (Array.isArray(value)) {
        clean[key] = value.slice(0, 20).filter((item) =>
          typeof item === 'string' || typeof item === 'number' || typeof item === 'boolean'
        );
      } else if (typeof value === 'object') {
        if (depth + 1 <= this.MAX_DEPTH) {
          clean[key] = this.sanitizeObject(value as Record<string, unknown>, depth + 1);
        }
      }

      keyCount++;
    }

    return clean;
  }

  /**
   * Filter overrides to prevent arbitrary injection.
   */
  private filterAllowedOverrides(overrides: Record<string, unknown>): Record<string, unknown> {
    const allowed = new Set([
      'taskType',
      'actionType',
      'requestFrequency',
      'resourceType',
      'changeType',
      'sourceSystem',
      'failureRate',
      'averageLatencyMs',
    ]);

    const result: Record<string, unknown> = {};
    for (const [k, v] of Object.entries(overrides)) {
      if (allowed.has(k) && !this.DANGEROUS_PROTO_KEYS.has(k)) {
        result[k] = v;
      }
    }
    return result;
  }

  /**
   * Maps an ActionRequest to a GovernanceRequest.
   */
  public mapActionRequestToGovernanceRequest(
    actionRequest: ActionRequest & { triggerId?: string }
  ): GovernanceRequest {
    const cap = capabilityRegistry.getCapability(actionRequest.capabilityId);
    return {
      requestId: actionRequest.actionId || `gov_req_${Date.now()}_${Math.random().toString(36).substring(2, 6)}`,
      correlationId: actionRequest.idempotencyKey,
      actor: {
        actorId: actionRequest.context?.agentId || actionRequest.context?.operatorId || 'OPERATOR',
        actorType: actionRequest.context?.agentId ? 'AUTONOMOUS_AGENT' : 'USER',
        role: actionRequest.context?.agentId ? 'AGENT' : 'OPERATOR',
      },
      targetSystem: actionRequest.capabilityId,
      capabilityId: actionRequest.capabilityId,
      actionType: actionRequest.operation,
      missionId: actionRequest.context?.missionId,
      triggerId: actionRequest.triggerId,
      connectorId: (actionRequest.parameters?.connectorId as string) || undefined,
      riskLevel: cap?.riskLevel || 'LOW',
      parameters: actionRequest.parameters,
      timestamp: Date.now(),
    };
  }
}

export const governanceContextService = new GovernanceContextService();
