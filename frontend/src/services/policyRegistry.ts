/**
 * AryaOS V1 — Stage 20: Policy Registry
 *
 * Authoritative registry and lifecycle state machine for Governed Policies.
 * Enforces immutable versioning, legal lifecycle transitions, duplicate checks,
 * secret sanitization, and persistence integration.
 */

import {
  Policy,
  PolicyId,
  PolicyStatus,
  PolicyVersion,
} from '../types/policyIntelligence';
import { executionPersistence } from './executionPersistence';

export class PolicyRegistry {
  private activePolicies: Map<PolicyId, Policy> = new Map();
  private policyHistory: Map<PolicyId, Policy[]> = new Map(); // policyId -> array of prior immutable versions
  private registryVersion: number = 1;

  constructor() {
    this.reset();
  }

  public reset(): void {
    this.activePolicies.clear();
    this.policyHistory.clear();
    this.registryVersion = 1;
  }

  public getRegistryVersion(): number {
    return this.registryVersion;
  }

  /**
   * Registers a new policy or rejects duplicate registration.
   */
  public registerPolicy(policyInput: Policy): Policy {
    this.validatePolicyStructure(policyInput);

    if (this.activePolicies.has(policyInput.id)) {
      throw new Error(
        `Duplicate Policy Error: Policy '${policyInput.id}' is already registered. To update, use updatePolicy().`
      );
    }

    const sanitized = this.sanitizePolicy(policyInput);

    // Initial default version must be 1 if not set
    if (!sanitized.version) {
      sanitized.version = 1;
    }

    this.activePolicies.set(sanitized.id, sanitized);
    this.registryVersion++;
    executionPersistence.savePolicy(sanitized);

    return sanitized;
  }

  /**
   * Updates an existing policy, creating an immutable historical record and incrementing version.
   */
  public updatePolicy(
    policyId: PolicyId,
    updates: Partial<Policy>,
    updatedBy: string,
    changeDescription: string
  ): Policy {
    const existing = this.activePolicies.get(policyId);
    if (!existing) {
      throw new Error(`Policy '${policyId}' not found in registry.`);
    }

    // Preserve historical version immutability
    const historicalCopy: Policy = JSON.parse(JSON.stringify(existing));
    const history = this.policyHistory.get(policyId) || [];
    history.push(historicalCopy);
    this.policyHistory.set(policyId, history);

    const newVersion = existing.version + 1;
    const now = Date.now();

    const updated: Policy = {
      ...existing,
      ...updates,
      id: existing.id, // ID remains immutable
      version: newVersion,
      provenance: {
        ...existing.provenance,
        updatedAt: now,
        changeLog: [
          ...existing.provenance.changeLog,
          {
            version: newVersion,
            timestamp: now,
            changedBy: updatedBy,
            description: changeDescription,
          },
        ],
      },
    };

    const sanitized = this.sanitizePolicy(updated);
    this.activePolicies.set(policyId, sanitized);
    this.registryVersion++;
    executionPersistence.savePolicy(sanitized);

    return sanitized;
  }

  /**
   * Transitions a policy's status according to the strict lifecycle state machine.
   * Direct DRAFT -> ACTIVE is strictly forbidden.
   */
  public transitionStatus(
    policyId: PolicyId,
    targetStatus: PolicyStatus,
    operatorId: string,
    reason: string
  ): Policy {
    const policy = this.activePolicies.get(policyId);
    if (!policy) {
      throw new Error(`Policy '${policyId}' not found in registry.`);
    }

    const currentStatus = policy.status;

    // Check for illegal direct jump
    if (currentStatus === 'DRAFT' && targetStatus === 'ACTIVE') {
      throw new Error(
        `Illegal State Transition: Cannot transition policy '${policyId}' directly from DRAFT to ACTIVE. It must proceed through CANDIDATE, UNDER_REVIEW, and APPROVED.`
      );
    }

    const legalTransitions: Record<PolicyStatus, PolicyStatus[]> = {
      DRAFT: ['CANDIDATE', 'REVOKED'],
      CANDIDATE: ['UNDER_REVIEW', 'DRAFT', 'REVOKED'],
      UNDER_REVIEW: ['APPROVED', 'DRAFT', 'REVOKED'],
      APPROVED: ['ACTIVE', 'REVOKED'],
      ACTIVE: ['PAUSED', 'DEPRECATED', 'REVOKED'],
      PAUSED: ['ACTIVE', 'REVOKED'],
      DEPRECATED: ['REVOKED'],
      REVOKED: [], // Terminal
    };

    if (!legalTransitions[currentStatus].includes(targetStatus)) {
      throw new Error(
        `Illegal State Transition: Cannot transition policy '${policyId}' from '${currentStatus}' to '${targetStatus}'.`
      );
    }

    return this.updatePolicy(
      policyId,
      { status: targetStatus },
      operatorId,
      `Lifecycle transition: ${currentStatus} -> ${targetStatus}. Reason: ${reason}`
    );
  }

  public getPolicy(policyId: PolicyId): Policy | undefined {
    return this.activePolicies.get(policyId);
  }

  public getAllPolicies(): Policy[] {
    return Array.from(this.activePolicies.values());
  }

  public getActivePolicies(): Policy[] {
    return Array.from(this.activePolicies.values()).filter(
      (p) => p.status === 'ACTIVE'
    );
  }

  public getPolicyHistory(policyId: PolicyId): Policy[] {
    return this.policyHistory.get(policyId) || [];
  }

  public getHistoricalVersion(policyId: PolicyId, version: PolicyVersion): Policy | undefined {
    if (this.activePolicies.get(policyId)?.version === version) {
      return this.activePolicies.get(policyId);
    }
    const history = this.policyHistory.get(policyId) || [];
    return history.find((p) => p.version === version);
  }

  /**
   * Secret Sanitization: Recursively removes or redacts secret tokens.
   */
  private sanitizePolicy(policy: Policy): Policy {
    const raw = JSON.parse(JSON.stringify(policy));
    this.scrubSecrets(raw);
    return raw as Policy;
  }

  private scrubSecrets(obj: unknown): void {
    if (!obj || typeof obj !== 'object') return;

    const sensitiveKeyPatterns = [
      /apikey/i,
      /token/i,
      /secret/i,
      /password/i,
      /auth.*header/i,
      /private.*key/i,
      /credential/i,
    ];

    if (Array.isArray(obj)) {
      obj.forEach((item) => this.scrubSecrets(item));
      return;
    }

    const record = obj as Record<string, unknown>;
    for (const key of Object.keys(record)) {
      if (sensitiveKeyPatterns.some((pattern) => pattern.test(key))) {
        record[key] = '[REDACTED]';
      } else if (typeof record[key] === 'object') {
        this.scrubSecrets(record[key]);
      }
    }
  }

  private validatePolicyStructure(p: Policy): void {
    if (!p.id || typeof p.id !== 'string') {
      throw new Error('Policy Validation Error: Missing or invalid id.');
    }
    if (!p.name || typeof p.name !== 'string') {
      throw new Error('Policy Validation Error: Missing or invalid name.');
    }
    if (!p.scope || !p.scope.scopeType) {
      throw new Error('Policy Validation Error: Missing or invalid scope.');
    }
    if (!p.priority) {
      throw new Error('Policy Validation Error: Missing or invalid priority.');
    }
    if (!p.effect || !p.effect.type) {
      throw new Error('Policy Validation Error: Missing or invalid effect.');
    }
    if (!p.provenance) {
      throw new Error('Policy Validation Error: Missing provenance.');
    }
  }
}

export const policyRegistry = new PolicyRegistry();
