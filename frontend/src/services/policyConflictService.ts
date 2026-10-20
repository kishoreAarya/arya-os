/**
 * AryaOS V1 — Stage 20: Policy Conflict Service
 *
 * Detects, classifies, and deterministically resolves conflicts between matching policies.
 * Invariant: Preserves full conflict provenance without silently dropping either policy.
 * Resolution is governed by the deterministic priority hierarchy:
 * SYSTEM_SAFETY (100) > SECURITY (90) > HUMAN_GOVERNANCE (80) >
 * RESOURCE_LIMITS (70) > MISSION_POLICY (60) > AGENT_POLICY (50) >
 * TRIGGER_POLICY (40) > OPTIMIZATION_POLICY (30).
 */

import {
  Policy,
  PolicyConflictRecord,
  PolicyConflictType,
  POLICY_PRIORITY_WEIGHTS,
  PolicyEvaluationResult,
  EffectivePolicyDecision,
} from '../types/policyIntelligence';
import { executionPersistence } from './executionPersistence';

export class PolicyConflictService {
  private recordedConflicts: Map<string, PolicyConflictRecord> = new Map();

  public reset(): void {
    this.recordedConflicts.clear();
  }

  /**
   * Resolves a set of matching policy evaluations into a single effective decision.
   */
  public resolveConflicts(
    matchedPolicies: PolicyEvaluationResult[],
    allPoliciesMap: Map<string, Policy>
  ): EffectivePolicyDecision {
    if (matchedPolicies.length === 0) {
      return {
        effectiveEffect: { type: 'ALLOW', reason: 'Default allow: No active policies matched.' },
        winningPolicyId: 'SYSTEM_DEFAULT',
        winningPolicyVersion: 1,
        winningPriority: 'OPTIMIZATION_POLICY',
        appliedPolicies: [],
        conflictingPolicies: [],
        reason: 'No policies triggered for this evaluation context.',
      };
    }

    if (matchedPolicies.length === 1) {
      const sole = matchedPolicies[0];
      return {
        effectiveEffect: sole.effect,
        winningPolicyId: sole.policyId,
        winningPolicyVersion: sole.version,
        winningPriority: sole.priority,
        appliedPolicies: [sole],
        conflictingPolicies: [],
        reason: `Sole matching policy '${sole.policyId}' applied.`,
      };
    }

    // Sort by priority weight descending. If weights equal, more restrictive effect wins.
    const sorted = [...matchedPolicies].sort((a, b) => {
      if (b.priorityWeight !== a.priorityWeight) {
        return b.priorityWeight - a.priorityWeight;
      }
      return this.getEffectRestrictiveness(b.effect.type) - this.getEffectRestrictiveness(a.effect.type);
    });

    const winner = sorted[0];
    const conflicts: PolicyConflictRecord[] = [];

    // Compare winner against all other matched policies to detect and record conflicts
    for (let i = 1; i < sorted.length; i++) {
      const competitor = sorted[i];
      const conflictType = this.classifyConflict(winner, competitor, allPoliciesMap);

      if (conflictType) {
        const conflictId = `conflict-${winner.policyId}-${competitor.policyId}-${Date.now()}-${Math.random().toString(36).substring(2, 6)}`;
        const precedenceReason = `Policy '${winner.policyId}' (Priority: ${winner.priority}, Weight: ${winner.priorityWeight}) takes precedence over Policy '${competitor.policyId}' (Priority: ${competitor.priority}, Weight: ${competitor.priorityWeight}) due to hierarchical precedence rules.`;

        const conflictRecord: PolicyConflictRecord = {
          conflictId,
          policyAId: winner.policyId,
          policyAVersion: winner.version,
          policyBId: competitor.policyId,
          policyBVersion: competitor.version,
          conflictType,
          precedenceReason,
          effectivePolicyId: winner.policyId,
          detectedAt: Date.now(),
        };

        conflicts.push(conflictRecord);
        this.recordedConflicts.set(conflictId, conflictRecord);
        executionPersistence.savePolicyConflict(conflictRecord);
      }
    }

    return {
      effectiveEffect: winner.effect,
      winningPolicyId: winner.policyId,
      winningPolicyVersion: winner.version,
      winningPriority: winner.priority,
      appliedPolicies: sorted,
      conflictingPolicies: conflicts,
      reason: `Hierarchical precedence selected Policy '${winner.policyId}' (Weight: ${winner.priorityWeight}). ${conflicts.length} conflicting policies resolved and preserved in audit log.`,
    };
  }

  /**
   * Classifies the nature of the policy conflict.
   */
  private classifyConflict(
    a: PolicyEvaluationResult,
    b: PolicyEvaluationResult,
    allPoliciesMap: Map<string, Policy>
  ): PolicyConflictType | null {
    const isContradictory =
      (a.effect.type === 'ALLOW' && (b.effect.type === 'DENY' || b.effect.type === 'PAUSE')) ||
      (b.effect.type === 'ALLOW' && (a.effect.type === 'DENY' || a.effect.type === 'PAUSE')) ||
      (a.effect.type === 'DENY' && b.effect.type !== 'DENY');

    if (isContradictory) {
      return 'CONTRADICTORY_POLICY';
    }

    if (a.priorityWeight !== b.priorityWeight) {
      return 'PRIORITY_CONFLICT';
    }

    const policyA = allPoliciesMap.get(a.policyId);
    const policyB = allPoliciesMap.get(b.policyId);

    if (policyA && policyB && policyA.scope.scopeType !== policyB.scope.scopeType) {
      return 'SCOPE_CONFLICT';
    }

    if (a.effect.constraint || b.effect.constraint) {
      return 'RESOURCE_CONFLICT';
    }

    return 'PRIORITY_CONFLICT';
  }

  private getEffectRestrictiveness(effect: string): number {
    switch (effect) {
      case 'DENY':
        return 10;
      case 'PAUSE':
        return 8;
      case 'REQUIRE_APPROVAL':
        return 6;
      case 'REQUIRE_REVIEW':
        return 5;
      case 'LIMIT':
        return 4;
      case 'DEFER':
        return 3;
      case 'ROUTE':
        return 2;
      case 'ALLOW':
        return 1;
      default:
        return 0;
    }
  }

  public getAllConflicts(): PolicyConflictRecord[] {
    return Array.from(this.recordedConflicts.values());
  }
}

export const policyConflictService = new PolicyConflictService();
