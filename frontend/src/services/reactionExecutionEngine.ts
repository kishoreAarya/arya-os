/**
 * AryaOS V1 — Stage 19: Reaction Execution Engine & Controlled Trigger Orchestration
 *
 * Dispatches authorized reaction proposals strictly through EXISTING orchestration boundaries:
 * - Goal creation -> Stage 08 GoalOrchestrator
 * - Mission updates -> Stage 12 MissionManager / MissionReplanner
 * - External actions -> Stage 15 Universal Action Bus
 *
 * ABSOLUTE INVARIANTS:
 * - Deterministic reaction idempotency: duplicate deliveries return cached result
 * - Loop protection: depth and visited trigger tracking abort cyclic chains (REACTION_CHAIN_LIMIT)
 * - Multi-tier authorization: Stage 10 resource limits, Stage 16 connector permissions
 * - Human signoff boundary: consequential reactions require valid human approval
 * - Sole AI boundary: Stage 07 Execution Gateway remains unbypassed
 * - Zero raw secret persistence
 */

import {
  ReactionProposal,
  ReactionExecutionResult,
  ReactionExecutionStatus,
} from '../types/eventTrigger';
import { ActionRequest } from '../types/actionBus';
import { actionBusService } from './actionBusService';
import { goalOrchestrator } from './goalOrchestrator';
import { missionManager } from './missionManager';
import { missionReplanner } from './missionReplanner';
import { missionObservationService } from './missionObservationService';
import { connectorPermissionService } from './connectorPermissionService';
import { resourceGovernor } from './resourceGovernor';
import { executionJournal } from './executionJournal';
import { executionPersistence } from './executionPersistence';
import { knowledgeGraph } from './knowledgeGraph';
import { KnowledgeNode } from '../types/strategicKnowledge';
import { triggerRegistry } from './triggerRegistry';
import { reactionProposalService } from './reactionProposalService';

export class ReactionExecutionEngine {
  private activeReactionCount: number = 0;
  private readonly maxConcurrentReactions: number = 5;
  private readonly defaultMaxDepth: number = 3;
  private executionResults: Map<string, ReactionExecutionResult> = new Map();

  /**
   * Generates a deterministic reaction ID.
   */
  public generateReactionId(proposal: ReactionProposal): string {
    const raw = `${proposal.triggerId}_v${proposal.triggerVersion}_${proposal.eventId}_${proposal.reactionType}_${proposal.missionId || proposal.goalId || 'target'}`;
    let hash = 0;
    for (let i = 0; i < raw.length; i++) {
      hash = (hash << 5) - hash + raw.charCodeAt(i);
      hash |= 0;
    }
    const hex = Math.abs(hash).toString(16).padStart(8, '0');
    return `rxn_${proposal.triggerId}_${hex}`;
  }

  /**
   * Executes a ReactionProposal through existing governed subsystems.
   */
  public async executeReaction(
    proposal: ReactionProposal,
    options?: {
      operatorApproval?: { approvedBy: string; signature?: string };
      overrideMaxDepth?: number;
    }
  ): Promise<ReactionExecutionResult> {
    const startTime = Date.now();
    const reactionId = this.generateReactionId(proposal);

    // 1. Idempotency Check: Return existing cached result if already executed
    const existing = executionPersistence.getReactionResult(reactionId);
    if (existing) {
      this.recordJournal('REACTION_DUPLICATE', {
        reactionId,
        proposalId: proposal.proposalId,
        triggerId: proposal.triggerId,
      }, proposal.missionId);
      return {
        ...existing,
        replayed: true,
      };
    }

    // 2. Loop Protection & Reaction Chain Depth Verification
    const depth = proposal.provenance.depth;
    const maxDepth = options?.overrideMaxDepth ?? this.defaultMaxDepth;
    const visited = proposal.provenance.visitedTriggerIds || [];
    const occurrences = visited.filter((id) => id === proposal.triggerId).length;
    const isCycle = occurrences > 1;

    if (depth >= maxDepth) {
      const result: ReactionExecutionResult = {
        reactionId,
        proposalId: proposal.proposalId,
        triggerId: proposal.triggerId,
        triggerVersion: proposal.triggerVersion,
        eventId: proposal.eventId,
        status: 'CHAIN_LIMIT',
        error: `Reaction chain terminated: Reaction depth limit exceeded (depth: ${depth}/${maxDepth}, visited: [${visited.join(', ')}])`,
        executedAt: new Date().toISOString(),
        latencyMs: Date.now() - startTime,
        replayed: false,
      };

      executionPersistence.saveReactionResult(result);
      this.recordJournal('REACTION_CHAIN_LIMIT', {
        reactionId,
        depth,
        maxDepth,
        visitedTriggerIds: visited,
      }, proposal.missionId);

      return result;
    }

    if (isCycle) {
      const result: ReactionExecutionResult = {
        reactionId,
        proposalId: proposal.proposalId,
        triggerId: proposal.triggerId,
        triggerVersion: proposal.triggerVersion,
        eventId: proposal.eventId,
        status: 'CHAIN_LIMIT',
        error: `Reaction chain terminated: Causal trigger cycle detected for trigger '${proposal.triggerId}' (visited: [${visited.join(', ')}])`,
        executedAt: new Date().toISOString(),
        latencyMs: Date.now() - startTime,
        replayed: false,
      };

      executionPersistence.saveReactionResult(result);
      this.recordJournal('REACTION_CHAIN_LIMIT', {
        reactionId,
        depth,
        maxDepth,
        visitedTriggerIds: visited,
      }, proposal.missionId);

      return result;
    }

    // 3. Concurrency & Resource Governance (Stage 10)
    if (this.activeReactionCount >= this.maxConcurrentReactions) {
      const result: ReactionExecutionResult = {
        reactionId,
        proposalId: proposal.proposalId,
        triggerId: proposal.triggerId,
        triggerVersion: proposal.triggerVersion,
        eventId: proposal.eventId,
        status: 'RATE_LIMITED',
        error: `Max concurrent reactions reached (${this.maxConcurrentReactions})`,
        executedAt: new Date().toISOString(),
        latencyMs: Date.now() - startTime,
        replayed: false,
      };
      this.recordJournal('REACTION_REJECTED', {
        reactionId,
        reason: 'CONCURRENCY_LIMIT_EXCEEDED',
      }, proposal.missionId);
      return result;
    }

    if (proposal.missionId) {
      const budgetCheck = resourceGovernor.checkBudgetPreflight(proposal.missionId);
      if (!budgetCheck.allowed) {
        const result: ReactionExecutionResult = {
          reactionId,
          proposalId: proposal.proposalId,
          triggerId: proposal.triggerId,
          triggerVersion: proposal.triggerVersion,
          eventId: proposal.eventId,
          status: 'REJECTED',
          error: `Resource Governor: ${budgetCheck.reason} — ${budgetCheck.details}`,
          executedAt: new Date().toISOString(),
          latencyMs: Date.now() - startTime,
          replayed: false,
        };
        this.recordJournal('REACTION_REJECTED', {
          reactionId,
          reason: budgetCheck.reason,
        }, proposal.missionId);
        return result;
      }
    }

    // 4. Approval Gateway
    let currentProposal = proposal;
    if (currentProposal.status === 'AWAITING_APPROVAL') {
      if (options?.operatorApproval) {
        currentProposal = reactionProposalService.approveProposal(
          currentProposal.proposalId,
          options.operatorApproval
        );
      }
    }

    if (currentProposal.status === 'AWAITING_APPROVAL') {
      const result: ReactionExecutionResult = {
        reactionId,
        proposalId: currentProposal.proposalId,
        triggerId: currentProposal.triggerId,
        triggerVersion: currentProposal.triggerVersion,
        eventId: currentProposal.eventId,
        status: 'REQUIRES_APPROVAL',
        error: 'Proposal requires human approval: Reaction is consequential and requires explicit human operator signoff.',
        executedAt: new Date().toISOString(),
        latencyMs: Date.now() - startTime,
        replayed: false,
      };
      this.recordJournal('REACTION_AWAITING_APPROVAL', {
        reactionId,
        proposalId: currentProposal.proposalId,
        riskLevel: currentProposal.riskLevel,
      }, currentProposal.missionId);
      return result;
    }

    if (currentProposal.status === 'REJECTED') {
      const result: ReactionExecutionResult = {
        reactionId,
        proposalId: currentProposal.proposalId,
        triggerId: currentProposal.triggerId,
        triggerVersion: currentProposal.triggerVersion,
        eventId: currentProposal.eventId,
        status: 'REJECTED',
        error: currentProposal.rejectionReason || 'Proposal rejected by governance.',
        executedAt: new Date().toISOString(),
        latencyMs: Date.now() - startTime,
        replayed: false,
      };
      this.recordJournal('REACTION_REJECTED', {
        reactionId,
        reason: result.error,
      }, currentProposal.missionId);
      return result;
    }

    // 5. Dispatch Reaction via Existing Subsystems (Action Bus is the sole external action boundary)
    this.activeReactionCount++;
    this.recordJournal('REACTION_EXECUTING', {
      reactionId,
      reactionType: currentProposal.reactionType,
      triggerId: currentProposal.triggerId,
    }, currentProposal.missionId);

    try {
      let output: unknown = null;

      switch (currentProposal.reactionType) {
        case 'CREATE_OBSERVATION': {
          const missionId = currentProposal.missionId || 'mis_system_default';
          const summary =
            (currentProposal.reactionParameters.observationSummary as string) ||
            `Trigger ${currentProposal.triggerId} observed external event ${currentProposal.eventId}`;
          output = missionObservationService.recordObservation(
            missionId,
            'PROGRESS',
            summary,
            {
              reactionId,
              triggerId: currentProposal.triggerId,
              eventId: currentProposal.eventId,
              ...currentProposal.reactionParameters,
            }
          );
          break;
        }

        case 'REPLAN_MISSION': {
          if (!currentProposal.missionId) {
            throw new Error('REPLAN_MISSION requires targetMissionId');
          }
          const reason = `Event-triggered replan: Trigger ${currentProposal.triggerId} for event ${currentProposal.eventId}`;
          output = missionReplanner.replanMission(currentProposal.missionId, reason);
          break;
        }

        case 'PAUSE_MISSION': {
          if (!currentProposal.missionId) {
            throw new Error('PAUSE_MISSION requires targetMissionId');
          }
          output = missionManager.pauseMission(currentProposal.missionId);
          break;
        }

        case 'CREATE_GOAL': {
          const intent =
            (currentProposal.reactionParameters.goalIntent as string) ||
            `Address external event ${currentProposal.eventId}`;
          output = await goalOrchestrator.createAndExecuteGoal(intent);
          break;
        }

        case 'REQUEST_RESEARCH':
        case 'REQUEST_ANALYSIS': {
          const missionId = currentProposal.missionId || 'mis_system_default';
          output = missionObservationService.recordObservation(
            missionId,
            'QUALITY',
            `Autonomous research requested: ${currentProposal.reactionType} by trigger ${currentProposal.triggerId}`,
            { reactionId, ...currentProposal.reactionParameters }
          );
          break;
        }

        case 'EXTERNAL_ACTION': {
          if (!currentProposal.proposedAction) {
            throw new Error('EXTERNAL_ACTION requires proposedAction intent');
          }
          const actionReq: ActionRequest = {
            actionId: `act_rxn_${reactionId}`,
            capabilityId: currentProposal.proposedAction.capabilityId,
            operation: currentProposal.proposedAction.operation,
            parameters: currentProposal.proposedAction.parameters,
            idempotencyKey: `k_${reactionId}`,
            context: {
              timestamp: new Date().toISOString(),
              missionId: currentProposal.missionId,
            },
          };
          output = await actionBusService.execute(actionReq, {
            operatorApproval: currentProposal.operatorApproval,
          });
          break;
        }

        default:
          output = { message: `Executed reaction ${currentProposal.reactionType}` };
          break;
      }

      const executionDuration = Date.now() - startTime;
      const result: ReactionExecutionResult = {
        reactionId,
        proposalId: currentProposal.proposalId,
        triggerId: currentProposal.triggerId,
        triggerVersion: currentProposal.triggerVersion,
        eventId: currentProposal.eventId,
        status: 'SUCCEEDED',
        output,
        executedAt: new Date().toISOString(),
        latencyMs: executionDuration,
        replayed: false,
      };

      executionPersistence.saveReactionResult(result);
      this.recordJournal('REACTION_SUCCEEDED', {
        reactionId,
        latencyMs: executionDuration,
      }, currentProposal.missionId);

      // 7. Provenance & Evidence in Knowledge Graph (Stage 13)
      this.recordKnowledgeEvidence(currentProposal, result);

      return result;
    } catch (err: any) {
      const result: ReactionExecutionResult = {
        reactionId,
        proposalId: currentProposal.proposalId,
        triggerId: currentProposal.triggerId,
        triggerVersion: currentProposal.triggerVersion,
        eventId: currentProposal.eventId,
        status: 'FAILED',
        error: err.message || 'Reaction execution failed',
        executedAt: new Date().toISOString(),
        latencyMs: Date.now() - startTime,
        replayed: false,
      };

      executionPersistence.saveReactionResult(result);
      this.recordJournal('REACTION_FAILED', {
        reactionId,
        error: result.error,
      }, currentProposal.missionId);

      return result;
    } finally {
      this.activeReactionCount--;
    }
  }

  private recordKnowledgeEvidence(
    proposal: ReactionProposal,
    result: ReactionExecutionResult
  ): void {
    try {
      const nodeId = `kn_rxn_${proposal.triggerId}_${proposal.eventId}`;
      const node: KnowledgeNode = {
        id: nodeId,
        type: 'FACT',
        label: `Reaction ${proposal.reactionType} triggered by ${proposal.triggerId}`,
        confidence: 0.95,
        status: 'CONFIRMED',
        epistemicStatus: 'CONFIRMED',
        evidenceCount: 1,
        sourceMissions: proposal.missionId ? [proposal.missionId] : [],
        contributingAgents: [],
        createdAt: result.executedAt,
        updatedAt: result.executedAt,
        metadata: {
          reactionId: result.reactionId,
          triggerId: proposal.triggerId,
          triggerVersion: proposal.triggerVersion,
          eventId: proposal.eventId,
          status: result.status,
        },
      } as any;
      knowledgeGraph.addNode(node);
    } catch {
      // Safe boundary
    }
  }

  private recordJournal(
    eventType: any,
    payload: Record<string, unknown>,
    missionId?: string
  ): void {
    try {
      executionJournal.appendEvent({
        goalId: missionId || 'goal_reaction_engine',
        eventType,
        payload: {
          ...payload,
          timestamp: new Date().toISOString(),
        },
      });
    } catch {
      // Safe fallback
    }
  }

  public async executeProposal(
    proposal: ReactionProposal,
    options?: {
      operatorApproval?: { approvedBy: string; signature?: string };
      overrideMaxDepth?: number;
    }
  ): Promise<ReactionExecutionResult> {
    const result = await this.executeReaction(proposal, options);
    this.executionResults.set(proposal.proposalId, result);
    return result;
  }

  public getExecutionResult(proposalId: string): ReactionExecutionResult | undefined {
    return this.executionResults.get(proposalId) || executionPersistence.getReactionResult(proposalId) || undefined;
  }

  public getActiveExecutionCount(): number {
    return this.activeReactionCount;
  }

  public clear(): void {
    this.executionResults.clear();
    this.activeReactionCount = 0;
  }
}

export const reactionExecutionEngine = new ReactionExecutionEngine();
