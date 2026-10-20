/**
 * AryaOS V1 — Stage 20: Policy Evaluation Service
 *
 * Runtime policy governance coordinator. Evaluates active policies against
 * runtime contexts (Agent, Mission, Trigger, Connector, Provider, Resource),
 * handles conflicts via deterministic hierarchy, and evaluates shadow policies.
 *
 * Invariants:
 * - A policy CANNOT grant a permission that Stage 16 denies.
 * - A policy CANNOT bypass Stage 15 Universal Action Bus.
 * - A policy CANNOT bypass Stage 07 Execution Gateway.
 * - Shadow evaluation never influences the runtime decision.
 */

import {
  Policy,
  PolicyEvaluationContext,
  PolicyEvaluationResult,
  EffectivePolicyDecision,
  POLICY_PRIORITY_WEIGHTS,
} from '../types/policyIntelligence';
import { policyRegistry } from './policyRegistry';
import { policyConditionEngine } from './policyConditionEngine';
import { policyConflictService } from './policyConflictService';
import { policyShadowService } from './policyShadowService';
import { executionPersistence } from './executionPersistence';
import { executionJournal } from './executionJournal';

export class PolicyEvaluationService {
  /**
   * Evaluates all active policies against an operational context and determines the effective decision.
   */
  public evaluate(context: PolicyEvaluationContext): EffectivePolicyDecision {
    const activePolicies = policyRegistry.getActivePolicies();
    const allPoliciesMap = new Map<string, Policy>(
      policyRegistry.getAllPolicies().map((p) => [p.id, p])
    );

    const matchedResults: PolicyEvaluationResult[] = [];

    for (const policy of activePolicies) {
      if (this.matchesScope(policy, context)) {
        const isMatched = policyConditionEngine.evaluate(policy.conditions, context);
        if (isMatched) {
          const priorityWeight = POLICY_PRIORITY_WEIGHTS[policy.priority] || 0;
          matchedResults.push({
            policyId: policy.id,
            version: policy.version,
            matched: true,
            effect: policy.effect,
            priority: policy.priority,
            priorityWeight,
            reason: policy.effect.reason || `Enforced by policy '${policy.id}' v${policy.version}`,
          });
        }
      }
    }

    // Resolve conflicts and identify winner
    const decision = policyConflictService.resolveConflicts(matchedResults, allPoliciesMap);

    // Run shadow evaluation for candidate/shadow policies (does not alter decision)
    const allPolicies = policyRegistry.getAllPolicies();
    for (const p of allPolicies) {
      if (p.isShadow || p.status === 'CANDIDATE') {
        if (this.matchesScope(p, context)) {
          policyShadowService.evaluateShadow(p, context, decision.effectiveEffect.type);
        }
      }
    }

    // Persist evaluation telemetry to execution journal
    executionJournal.appendEvent({
      goalId: context.goalId || 'policy-governance',
      eventType: 'POLICY_EVALUATED',
      payload: {
        winningPolicyId: decision.winningPolicyId,
        effectiveEffect: decision.effectiveEffect.type,
        contextSummary: {
          agentId: context.agentId,
          missionId: context.missionId,
          providerId: context.providerId,
          connectorId: context.connectorId,
          taskType: context.taskType,
        },
      },
    });

    return decision;
  }

  /**
   * Verifies if a policy's declared scope matches the evaluation context.
   */
  public matchesScope(policy: Policy, context: PolicyEvaluationContext): boolean {
    const scope = policy.scope;
    if (!scope) return false;

    switch (scope.scopeType) {
      case 'SYSTEM':
        return true;

      case 'AGENT':
        if (!context.agentId) return false;
        return !scope.targetId || scope.targetId === context.agentId;

      case 'MISSION':
        if (!context.missionId) return false;
        return !scope.targetId || scope.targetId === context.missionId;

      case 'TRIGGER':
        if (!context.triggerId) return false;
        return !scope.targetId || scope.targetId === context.triggerId;

      case 'CONNECTOR':
        if (!context.connectorId) return false;
        return !scope.targetId || scope.targetId === context.connectorId;

      case 'PROVIDER':
        if (!context.providerId) return false;
        return !scope.targetId || scope.targetId === context.providerId;

      case 'RESOURCE':
        return (
          context.activeConcurrentActions !== undefined ||
          context.activeConcurrentAgents !== undefined ||
          context.costUsd !== undefined ||
          context.tokenCount !== undefined
        );

      case 'WORKFLOW':
        return !!context.taskType || !!context.capability;

      case 'REACTION':
        return !!context.triggerId;

      default:
        return false;
    }
  }
}

export const policyEvaluationService = new PolicyEvaluationService();
