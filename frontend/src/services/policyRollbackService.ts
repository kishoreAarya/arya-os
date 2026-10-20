/**
 * AryaOS V1 — Stage 20: Policy Rollback Service
 *
 * Implements auditable, explicit rollback for active policies.
 * Invariant: Preserves historical version immutability by rolling back
 * to a new version increment with prior configuration, rather than destructive in-place mutation.
 */

import {
  PolicyId,
  PolicyVersion,
  PolicyRollbackRecord,
  Policy,
} from '../types/policyIntelligence';
import { policyRegistry } from './policyRegistry';
import { executionPersistence } from './executionPersistence';

export class PolicyRollbackService {
  private rollbackRecords: Map<string, PolicyRollbackRecord> = new Map();

  public reset(): void {
    this.rollbackRecords.clear();
  }

  /**
   * Rolls back an active policy to an explicit prior version.
   */
  public rollbackPolicy(
    policyId: PolicyId,
    targetPriorVersion: PolicyVersion,
    authorizedBy: string,
    reason: string
  ): { rolledBackPolicy: Policy; rollbackRecord: PolicyRollbackRecord } {
    if (!authorizedBy || typeof authorizedBy !== 'string') {
      throw new Error('Rollback Error: Missing authorized operator ID.');
    }

    // Security check: Autonomous agents cannot authorize rollback
    if (authorizedBy.startsWith('AUTONOMOUS_AGENT') || authorizedBy.startsWith('SYSTEM')) {
      throw new Error(
        `Security Violation: Operator '${authorizedBy}' is not authorized to execute policy rollback.`
      );
    }

    const currentPolicy = policyRegistry.getPolicy(policyId);
    if (!currentPolicy) {
      throw new Error(`Rollback Error: Policy '${policyId}' not found.`);
    }

    if (currentPolicy.version === targetPriorVersion) {
      throw new Error(
        `Rollback Error: Target version ${targetPriorVersion} is already the current active version.`
      );
    }

    const historicalTarget = policyRegistry.getHistoricalVersion(policyId, targetPriorVersion);
    if (!historicalTarget) {
      throw new Error(
        `Rollback Error: Historical version ${targetPriorVersion} for policy '${policyId}' does not exist in history.`
      );
    }

    const fromVersion = currentPolicy.version;

    // Apply configuration of historical target as an update (increments version cleanly)
    const rolledBackPolicy = policyRegistry.updatePolicy(
      policyId,
      {
        name: historicalTarget.name,
        description: historicalTarget.description,
        scope: historicalTarget.scope,
        priority: historicalTarget.priority,
        conditions: historicalTarget.conditions,
        effect: historicalTarget.effect,
        status: 'ACTIVE', // Ensure rolled-back policy is active
      },
      authorizedBy,
      `Explicit rollback from version ${fromVersion} to configuration of version ${targetPriorVersion}. Reason: ${reason}`
    );

    const rollbackId = `rollback-${policyId}-v${fromVersion}-to-v${targetPriorVersion}-${Date.now()}`;
    const rollbackRecord: PolicyRollbackRecord = {
      rollbackId,
      policyId,
      fromVersion,
      toVersion: targetPriorVersion,
      authorizedBy,
      authorizedAt: Date.now(),
      rollbackAt: Date.now(),
      reason,
    };

    this.rollbackRecords.set(rollbackId, rollbackRecord);
    executionPersistence.savePolicyRollback(rollbackRecord);

    return { rolledBackPolicy, rollbackRecord };
  }

  public getRollbackRecords(policyId?: PolicyId): PolicyRollbackRecord[] {
    const records = Array.from(this.rollbackRecords.values());
    if (policyId) {
      return records.filter((r) => r.policyId === policyId);
    }
    return records;
  }
}

export const policyRollbackService = new PolicyRollbackService();
