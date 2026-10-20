/**
 * AryaOS V1 — Stage 19: Reaction Proposal Service
 *
 * Constructs immutable ReactionProposal records from matched triggers,
 * evaluates multi-tier authorization requirements, and enforces human signoff boundaries.
 *
 * CRITICAL INVARIANTS:
 * - A proposal is NOT an action.
 * - Consequential actions (HIGH / CRITICAL) produce status 'AWAITING_APPROVAL'.
 * - AUTONOMOUS_AGENT and SYSTEM approvals are strictly rejected.
 */

import {
  Trigger,
  ReactionProposal,
  TriggerEvaluationContext,
  TriggerRiskLevel,
} from '../types/eventTrigger';
import { NormalizedExternalEvent } from '../types/externalEvent';
import { triggerRiskService } from './triggerRiskService';
import { executionPersistence } from './executionPersistence';

export class ReactionProposalService {
  private proposals: Map<string, ReactionProposal> = new Map();

  constructor() {
    this.loadFromStorage();
  }

  /**
   * Constructs an immutable ReactionProposal from a matched trigger.
   */
  public createProposal(
    trigger: Trigger,
    event: NormalizedExternalEvent,
    context: Partial<TriggerEvaluationContext>
  ): ReactionProposal {
    const timestamp = new Date().toISOString();
    const isExplicitlyLowPause =
      trigger.riskLevel === 'LOW' &&
      trigger.reaction.reactionType === 'PAUSE_MISSION' &&
      !trigger.reaction.targetMissionId;

    const effectiveRisk = isExplicitlyLowPause
      ? 'LOW'
      : triggerRiskService.resolveEffectiveRisk(
          trigger.riskLevel,
          trigger.reaction
        );

    const requiresHuman =
      !isExplicitlyLowPause &&
      (effectiveRisk === 'HIGH' ||
        effectiveRisk === 'CRITICAL' ||
        trigger.authorizationPolicy?.requiresHumanApproval === true);

    const causationId = context.causationId || `cau_${event.originalEventId || event.normalizedEventId}`;
    const correlationId = context.correlationId || `cor_${trigger.triggerId}_${event.originalEventId || event.normalizedEventId}`;
    const depth = context.depth || 0;
    const visitedTriggerIds = context.visitedTriggerIds
      ? [...context.visitedTriggerIds, trigger.triggerId]
      : [trigger.triggerId];

    // Deterministic proposal identity
    const proposalId = `prop_${trigger.triggerId}_v${trigger.version}_${event.originalEventId}`;

    const proposal: ReactionProposal = {
      proposalId,
      triggerId: trigger.triggerId,
      triggerVersion: trigger.version,
      trigger,
      eventId: event.originalEventId,
      missionId: context.missionId || trigger.reaction.targetMissionId,
      goalId: trigger.reaction.targetGoalId,
      reactionType: trigger.reaction.reactionType,
      riskLevel: effectiveRisk,
      requiresHumanApproval: requiresHuman,
      proposedAction: trigger.reaction.actionIntent ? { ...trigger.reaction.actionIntent } : undefined,
      reactionParameters: {
        ...trigger.reaction.parameters,
        goalIntent: trigger.reaction.goalIntent,
        observationSummary: trigger.reaction.observationSummary,
      },
      authorizationRequirements: {
        requiresHumanApproval: requiresHuman,
        requiredPermissions: trigger.authorizationPolicy?.requiredPermissions || [],
        requiredRole: trigger.authorizationPolicy?.requiredRole,
      },
      provenance: {
        triggeredAt: timestamp,
        eventFingerprint: event.normalizedEventId,
        causationId,
        correlationId,
        depth,
        visitedTriggerIds,
      },
      status: requiresHuman ? 'AWAITING_APPROVAL' : 'AUTHORIZED',
      createdAt: timestamp,
    };

    // Immutability preservation: freeze proposal object
    const frozen = Object.freeze({ ...proposal });
    this.proposals.set(proposalId, frozen as ReactionProposal);
    executionPersistence.saveReactionProposal(frozen as ReactionProposal);

    return frozen as ReactionProposal;
  }

  /**
   * Approves an awaiting proposal with human operator signoff.
   * Rejects autonomous / system signoff attempts.
   */
  public approveProposal(
    proposalId: string,
    operatorSignoff: { approvedBy: string; signature?: string }
  ): ReactionProposal {
    const proposal = this.proposals.get(proposalId);
    if (!proposal) {
      throw new Error(`Proposal '${proposalId}' not found.`);
    }

    if (proposal.status !== 'AWAITING_APPROVAL') {
      throw new Error(`Cannot approve proposal '${proposalId}' in state '${proposal.status}'.`);
    }

    // Strict human review invariant
    const approver = (operatorSignoff.approvedBy || '').toUpperCase();
    if (approver === 'AUTONOMOUS_AGENT' || approver === 'SYSTEM') {
      const rejected: ReactionProposal = Object.freeze({
        ...proposal,
        status: 'REJECTED',
        rejectionReason: `Autonomous approval attempted by '${operatorSignoff.approvedBy}' is strictly prohibited for consequential reactions.`,
      });
      this.proposals.set(proposalId, rejected);
      executionPersistence.saveReactionProposal(rejected);
      return rejected;
    }

    const authorized: ReactionProposal = Object.freeze({
      ...proposal,
      status: 'AUTHORIZED',
      operatorApproval: {
        approvedBy: operatorSignoff.approvedBy,
        approvedAt: new Date().toISOString(),
        signature: operatorSignoff.signature || `sig_${Date.now()}`,
      },
    });

    this.proposals.set(proposalId, authorized);
    executionPersistence.saveReactionProposal(authorized);
    return authorized;
  }

  public grantApproval(
    proposalId: string,
    approvedBy: string,
    reason?: string
  ): { success: boolean; proposal?: ReactionProposal; error?: string } {
    try {
      const approverUpper = (approvedBy || '').toUpperCase();
      if (
        approverUpper.startsWith('AUTONOMOUS_AGENT') ||
        approverUpper.startsWith('SYSTEM') ||
        approverUpper === 'AUTONOMOUS_AGENT' ||
        approverUpper === 'SYSTEM'
      ) {
        return {
          success: false,
          error: `Autonomous agents and system processes cannot grant human approval (attempted by: ${approvedBy})`,
        };
      }
      const approved = this.approveProposal(proposalId, { approvedBy, signature: reason });
      return { success: approved.status === 'AUTHORIZED', proposal: approved };
    } catch (err: any) {
      return { success: false, error: err.message };
    }
  }

  public rejectProposal(
    proposalId: string,
    rejectedBy: string,
    rejectionReason?: string
  ): { success: boolean; proposal?: ReactionProposal; error?: string } {
    const proposal = this.proposals.get(proposalId);
    if (!proposal) {
      return { success: false, error: `Proposal '${proposalId}' not found.` };
    }
    const rejected: ReactionProposal = Object.freeze({
      ...proposal,
      status: 'REJECTED',
      rejectionReason: rejectionReason || `Rejected by ${rejectedBy}`,
    });
    this.proposals.set(proposalId, rejected);
    executionPersistence.saveReactionProposal(rejected);
    return { success: true, proposal: rejected };
  }

  public loadFromPersistence(): void {
    this.loadFromStorage();
  }

  public getProposal(proposalId: string): ReactionProposal | null {
    return this.proposals.get(proposalId) || null;
  }

  public listProposals(filter?: { status?: string; triggerId?: string }): ReactionProposal[] {
    let list = Array.from(this.proposals.values());
    if (filter?.status) list = list.filter((p) => p.status === filter.status);
    if (filter?.triggerId) list = list.filter((p) => p.triggerId === filter.triggerId);
    return list;
  }

  public clear(): void {
    this.proposals.clear();
  }

  private loadFromStorage(): void {
    try {
      const persisted = executionPersistence.getAllReactionProposals();
      persisted.forEach((p) => {
        this.proposals.set(p.proposalId, Object.freeze(p));
      });
    } catch {
      // Safe fallback
    }
  }
}

export const reactionProposalService = new ReactionProposalService();
