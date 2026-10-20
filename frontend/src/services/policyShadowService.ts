/**
 * AryaOS V1 — Stage 20: Policy Shadow Service
 *
 * Implements non-intrusive shadow evaluation for candidate policies.
 * Evaluates what candidate policies WOULD have decided without altering
 * runtime behavior or side-effect execution.
 */

import {
  Policy,
  PolicyEvaluationContext,
  PolicyShadowRecord,
  PolicyEffectType,
} from '../types/policyIntelligence';
import { policyConditionEngine } from './policyConditionEngine';
import { executionPersistence } from './executionPersistence';

export class PolicyShadowService {
  private shadowRecords: Map<string, PolicyShadowRecord> = new Map();

  public reset(): void {
    this.shadowRecords.clear();
  }

  /**
   * Evaluates a candidate policy in shadow mode against a runtime context and actual runtime outcome.
   */
  public evaluateShadow(
    candidatePolicy: Policy,
    context: PolicyEvaluationContext,
    actualRuntimeEffect: PolicyEffectType
  ): PolicyShadowRecord {
    const wouldApply = policyConditionEngine.evaluate(candidatePolicy.conditions, context);
    const shadowProjectedEffect = wouldApply ? candidatePolicy.effect.type : actualRuntimeEffect;

    let projectedDifference = 'No difference: Candidate policy would have agreed with runtime decision.';
    if (wouldApply && candidatePolicy.effect.type !== actualRuntimeEffect) {
      projectedDifference = `Divergence Detected: Runtime chose '${actualRuntimeEffect}', whereas Shadow Policy '${candidatePolicy.id}' would have enforced '${candidatePolicy.effect.type}' (${candidatePolicy.effect.reason || 'No reason specified'}).`;
    } else if (!wouldApply) {
      projectedDifference = `Conditions not met: Shadow Policy '${candidatePolicy.id}' would not have triggered.`;
    }

    // Sanitize context summary (strip any keys or secrets)
    const sensitiveKeyPatterns = [/auth/i, /token/i, /key/i, /secret/i, /password/i, /credential/i];
    const contextSummary: Record<string, unknown> = {};
    for (const [k, v] of Object.entries(context)) {
      if (sensitiveKeyPatterns.some((p) => p.test(k))) {
        continue; // Exclude sensitive keys
      }
      if (typeof v === 'string' || typeof v === 'number' || typeof v === 'boolean') {
        contextSummary[k] = v;
      }
    }

    const shadowRecordId = `shadow-${candidatePolicy.id}-${Date.now()}-${Math.random().toString(36).substring(2, 6)}`;
    const record: PolicyShadowRecord = {
      shadowRecordId,
      policyId: candidatePolicy.id,
      version: candidatePolicy.version,
      evaluatedAt: Date.now(),
      wouldApply,
      actualRuntimeEffect,
      shadowProjectedEffect,
      projectedDifference,
      contextSummary,
    };

    this.shadowRecords.set(shadowRecordId, record);
    executionPersistence.savePolicyShadow(record);

    return record;
  }

  public getShadowRecords(policyId?: string): PolicyShadowRecord[] {
    const records = Array.from(this.shadowRecords.values());
    if (policyId) {
      return records.filter((r) => r.policyId === policyId);
    }
    return records;
  }
}

export const policyShadowService = new PolicyShadowService();
