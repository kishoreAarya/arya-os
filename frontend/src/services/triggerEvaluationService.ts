/**
 * AryaOS V1 — Stage 19: Trigger Evaluation Service
 *
 * Coordinates matching of incoming normalized external events against active triggers,
 * enforces bounded context size, and produces reaction proposals.
 *
 * CRITICAL INVARIANT:
 * - Only ACTIVE triggers evaluate. PAUSED / DISABLED / DRAFT triggers are ignored.
 * - Context excludes all raw credentials and tokens.
 */

import {
  Trigger,
  TriggerEvaluationContext,
  ReactionProposal,
} from '../types/eventTrigger';
import { NormalizedExternalEvent } from '../types/externalEvent';
import { triggerRegistry } from './triggerRegistry';
import { triggerConditionEngine } from './triggerConditionEngine';
import { reactionProposalService } from './reactionProposalService';
import { executionJournal } from './executionJournal';

export class TriggerEvaluationService {
  /**
   * Evaluates all active triggers against an incoming normalized event.
   */
  public evaluateEvent(
    event: NormalizedExternalEvent,
    causalContext?: {
      missionId?: string;
      projectId?: string;
      causationId?: string;
      correlationId?: string;
      depth?: number;
      visitedTriggerIds?: string[];
    }
  ): ReactionProposal[] {
    const activeTriggers = triggerRegistry.listActiveTriggers();
    const proposals: ReactionProposal[] = [];

    // Bounded TriggerEvaluationContext
    const context: TriggerEvaluationContext = {
      event: {
        eventId: event.originalEventId,
        sourceSystem: event.sourceSystem,
        eventType: event.provenance.providerEventType || 'unknown',
        connectorId: event.connectorId,
        resourceType: event.resourceType,
        resourceId: event.resourceId,
        changeType: event.changeType,
        timestamp: event.timestamp,
        epistemicStatus: event.epistemicStatus,
        data: { ...event.data },
      },
      missionId: causalContext?.missionId,
      projectId: causalContext?.projectId,
      causationId: causalContext?.causationId,
      correlationId: causalContext?.correlationId,
      depth: causalContext?.depth || 0,
      visitedTriggerIds: causalContext?.visitedTriggerIds || [],
    };

    for (const trigger of activeTriggers) {
      // 1. Filter match
      const filterMatches = triggerConditionEngine.matchFilter(trigger.eventFilter, context);
      if (!filterMatches) {
        continue;
      }

      // 2. Condition match
      const conditionsMatch = triggerConditionEngine.evaluateConditions(trigger.conditions, context);
      if (!conditionsMatch) {
        this.recordJournal('TRIGGER_SKIPPED', {
          triggerId: trigger.triggerId,
          version: trigger.version,
          eventId: event.originalEventId,
          reason: 'CONDITIONS_NOT_MET',
        }, context.missionId);
        continue;
      }

      // 3. Matched: create proposal
      const proposal = reactionProposalService.createProposal(trigger, event, context);
      proposals.push(proposal);

      this.recordJournal('TRIGGER_MATCHED', {
        triggerId: trigger.triggerId,
        version: trigger.version,
        eventId: event.originalEventId,
        proposalId: proposal.proposalId,
        riskLevel: proposal.riskLevel,
        status: proposal.status,
      }, context.missionId);
    }

    return proposals;
  }

  private recordJournal(
    eventType: any,
    payload: Record<string, unknown>,
    missionId?: string
  ): void {
    try {
      executionJournal.appendEvent({
        goalId: missionId || 'goal_trigger_orchestration',
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
}

export const triggerEvaluationService = new TriggerEvaluationService();
