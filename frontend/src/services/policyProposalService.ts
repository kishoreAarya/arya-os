/**
 * AryaOS V1 — Stage 20: Policy Proposal & Governance Service
 *
 * Governs policy candidate generation from Stage 11 Learning Signals,
 * impact simulation, human operator review, and activation.
 *
 * Invariants:
 * - LEARNING SIGNAL ≠ POLICY
 * - RECOMMENDATION ≠ APPROVAL
 * - AUTONOMOUS AGENT / SYSTEM APPROVALS ARE STRICTLY PROHIBITED.
 */

import {
  Policy,
  PolicyProposal,
  PolicyActivationRecord,
} from '../types/policyIntelligence';
import { LearningSignal } from '../types/agentEvaluation';
import { policyRegistry } from './policyRegistry';
import { policyImpactSimulator } from './policyImpactSimulator';
import { executionPersistence } from './executionPersistence';

export class PolicyProposalService {
  private proposals: Map<string, PolicyProposal> = new Map();
  private activationRecords: Map<string, PolicyActivationRecord> = new Map();

  public reset(): void {
    this.proposals.clear();
    this.activationRecords.clear();
  }

  /**
   * Generates a policy candidate from an active Stage 11 Learning Signal.
   */
  public generateCandidateFromLearningSignal(
    signal: LearningSignal,
    proposerId: string = 'policy-intelligence-system'
  ): PolicyProposal {
    const policyId = `policy-candidate-${signal.signalType.toLowerCase().replace(/_/g, '-')}-${Date.now()}`;
    const now = Date.now();

    let effectType = 'LIMIT';
    let targetScope = 'PROVIDER';
    let targetId = 'unknown';

    if (signal.signalType === 'PROVIDER_HIGH_FAILURE_RATE') {
      const match = signal.observation.match(/Provider '([^']+)'/);
      targetId = match ? match[1] : 'unstable-provider';
      effectType = 'ROUTE';
      targetScope = 'PROVIDER';
    } else if (signal.signalType === 'AGENT_HIGH_QUALITY_FOR_TASK') {
      const match = signal.observation.match(/Agent '([^']+)'/);
      targetId = match ? match[1] : 'specialist-agent';
      effectType = 'ROUTE';
      targetScope = 'AGENT';
    } else if (signal.signalType === 'ROUTE_REPEATEDLY_FAILED') {
      effectType = 'DENY';
      targetScope = 'WORKFLOW';
    }

    const candidatePolicy: Policy = {
      id: policyId,
      version: 1,
      name: `Governed Policy Candidate: ${signal.signalType}`,
      description: `Derived from learning signal ${signal.signalId}: ${signal.observation}`,
      status: 'CANDIDATE',
      scope: {
        scopeType: targetScope as any,
        targetId,
      },
      priority: 'OPTIMIZATION_POLICY',
      conditions: {
        conjunction: 'AND',
        conditions: [
          {
            field: 'taskType',
            operator: 'exists',
          },
        ],
      },
      effect: {
        type: effectType as any,
        reason: `Generated from empirical evidence in signal ${signal.signalId}`,
        routedProviderId: effectType === 'ROUTE' && targetScope === 'PROVIDER' ? 'mock' : undefined,
        routedAgentId: effectType === 'ROUTE' && targetScope === 'AGENT' ? targetId : undefined,
      },
      provenance: {
        authorId: proposerId,
        createdAt: now,
        updatedAt: now,
        learningSignalId: signal.signalId,
        evidence: {
          evidenceSignalIds: [signal.signalId],
          confidenceScore: signal.confidence === 'HIGH' ? 0.9 : signal.confidence === 'MEDIUM' ? 0.7 : 0.5,
          description: signal.observation,
        },
        changeLog: [
          {
            version: 1,
            timestamp: now,
            changedBy: proposerId,
            description: `Generated candidate from learning signal ${signal.signalId}`,
          },
        ],
      },
      requiresHumanApproval: true,
    };

    const impact = policyImpactSimulator.simulateImpact(candidatePolicy);

    const proposalId = `prop-${policyId}`;
    const proposal: PolicyProposal = {
      proposalId,
      policy: candidatePolicy,
      proposedStatus: 'ACTIVE',
      proposerId,
      proposedAt: now,
      reason: `Empirical learning signal detected: ${signal.observation}`,
      status: 'PENDING',
      impactSimulation: impact,
    };

    // Register candidate in policy registry (remains CANDIDATE, NOT ACTIVE)
    policyRegistry.registerPolicy(candidatePolicy);

    this.proposals.set(proposalId, proposal);
    executionPersistence.savePolicyProposal(proposal);

    return proposal;
  }

  /**
   * Reviews a policy proposal. Enforces that only verified human operators can approve.
   */
  public reviewProposal(
    proposalId: string,
    decision: 'APPROVED' | 'REJECTED',
    reviewerId: string,
    reason: string
  ): PolicyProposal {
    const proposal = this.proposals.get(proposalId);
    if (!proposal) {
      throw new Error(`Policy Proposal '${proposalId}' not found.`);
    }

    if (decision === 'APPROVED') {
      // Security Boundary: Reject autonomous agents and system daemons
      if (reviewerId.startsWith('AUTONOMOUS_AGENT') || reviewerId.startsWith('SYSTEM')) {
        throw new Error(
          `Security Violation: Approver '${reviewerId}' is not authorized. ` +
          `Only verified human operators can approve policy proposals.`
        );
      }

      proposal.status = 'APPROVED';
      proposal.reviewedBy = reviewerId;
      proposal.reviewedAt = Date.now();

      // Transition policy status to APPROVED in registry
      policyRegistry.transitionStatus(
        proposal.policy.id,
        'UNDER_REVIEW',
        reviewerId,
        'Review began'
      );
      policyRegistry.transitionStatus(
        proposal.policy.id,
        'APPROVED',
        reviewerId,
        `Approved by human operator: ${reason}`
      );
    } else {
      proposal.status = 'REJECTED';
      proposal.reviewedBy = reviewerId;
      proposal.reviewedAt = Date.now();
      proposal.rejectionReason = reason;

      policyRegistry.transitionStatus(
        proposal.policy.id,
        'REVOKED',
        reviewerId,
        `Rejected by reviewer: ${reason}`
      );
    }

    executionPersistence.savePolicyProposal(proposal);
    return proposal;
  }

  /**
   * Activates an APPROVED policy proposal, creating an immutable PolicyActivationRecord.
   */
  public activateProposal(
    proposalId: string,
    activatorId: string,
    reason: string
  ): PolicyActivationRecord {
    const proposal = this.proposals.get(proposalId);
    if (!proposal) {
      throw new Error(`Policy Proposal '${proposalId}' not found.`);
    }

    if (proposal.status !== 'APPROVED') {
      throw new Error(
        `Activation Error: Cannot activate proposal '${proposalId}' because status is '${proposal.status}', not 'APPROVED'.`
      );
    }

    const policy = policyRegistry.getPolicy(proposal.policy.id);
    if (!policy) {
      throw new Error(`Policy '${proposal.policy.id}' not found in registry.`);
    }

    const previousVersion = policy.version > 1 ? policy.version - 1 : undefined;

    // Transition to ACTIVE in registry
    policyRegistry.transitionStatus(
      policy.id,
      'ACTIVE',
      activatorId,
      reason
    );

    const activationId = `act-${policy.id}-v${policy.version}-${Date.now()}`;
    const activationRecord: PolicyActivationRecord = {
      activationId,
      policyId: policy.id,
      version: policy.version,
      approvedBy: proposal.reviewedBy || activatorId,
      approvedAt: proposal.reviewedAt || Date.now(),
      activationAt: Date.now(),
      previousPolicyVersion: previousVersion,
      reason,
    };

    this.activationRecords.set(activationId, activationRecord);
    executionPersistence.savePolicyActivation(activationRecord);

    return activationRecord;
  }

  public getProposal(proposalId: string): PolicyProposal | undefined {
    return this.proposals.get(proposalId);
  }

  public getAllProposals(): PolicyProposal[] {
    return Array.from(this.proposals.values());
  }

  public getAllActivations(): PolicyActivationRecord[] {
    return Array.from(this.activationRecords.values());
  }
}

export const policyProposalService = new PolicyProposalService();
