/**
 * AryaOS V1 — Stage 20: Policy Drift Detection Service
 *
 * Continuously monitors post-activation policy efficacy against expected baselines.
 * Invariant: Produces REVIEW_REQUIRED signals upon detecting performance, cost,
 * or resource drift. Strictly prohibits automatic self-mutation or silent policy patching.
 */

import {
  PolicyId,
  PolicyDriftRecord,
  PolicyDriftType,
} from '../types/policyIntelligence';
import { policyRegistry } from './policyRegistry';
import { executionPersistence } from './executionPersistence';

export interface MetricComparison {
  metricName: string;
  baseline: number;
  observed: number;
  tolerancePercent?: number; // default: 20%
}

export class PolicyDriftService {
  private driftRecords: Map<string, PolicyDriftRecord> = new Map();

  public reset(): void {
    this.driftRecords.clear();
  }

  /**
   * Compares observed metrics against baseline for an active policy.
   * If variance exceeds tolerance, records drift and flags REVIEW_REQUIRED.
   */
  public evaluateDrift(
    policyId: PolicyId,
    driftType: PolicyDriftType,
    comparison: MetricComparison
  ): PolicyDriftRecord | null {
    const policy = policyRegistry.getPolicy(policyId);
    if (!policy) {
      throw new Error(`Policy '${policyId}' not found.`);
    }

    const { metricName, baseline, observed } = comparison;
    const tolerance = comparison.tolerancePercent ?? 20;

    let deltaPercent = 0;
    if (baseline !== 0) {
      deltaPercent = ((observed - baseline) / Math.abs(baseline)) * 100;
    } else if (observed !== 0) {
      deltaPercent = 100;
    }

    // Check if drift exceeds tolerance
    const isDrifting = Math.abs(deltaPercent) > tolerance;

    if (!isDrifting) {
      return null;
    }

    const driftId = `drift-${policyId}-${metricName}-${Date.now()}`;
    const driftRecord: PolicyDriftRecord = {
      driftId,
      policyId,
      version: policy.version,
      driftType,
      observedMetric: metricName,
      baselineValue: baseline,
      currentValue: observed,
      deltaPercent: Number(deltaPercent.toFixed(2)),
      detectedAt: Date.now(),
      status: 'REVIEW_REQUIRED',
    };

    this.driftRecords.set(driftId, driftRecord);
    executionPersistence.savePolicyDrift(driftRecord);

    return driftRecord;
  }

  public getDriftRecords(policyId?: PolicyId): PolicyDriftRecord[] {
    const records = Array.from(this.driftRecords.values());
    if (policyId) {
      return records.filter((r) => r.policyId === policyId);
    }
    return records;
  }
}

export const policyDriftService = new PolicyDriftService();
