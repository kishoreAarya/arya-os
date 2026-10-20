/**
 * AryaOS V1 — Stage 22: Operation Trace Reconstruction Service
 *
 * Reconstructs the complete origin-to-outcome causal audit trace for any operationId.
 * Guarantees explicit representation of missing evidence (never fabricates missing steps)
 * and generates deterministic human-readable explanations without LLM inference.
 */

import {
  OperationTrace,
  CausalTraceStep,
  CausalNodeType,
  OperationalAuditEvent,
} from '../types/operationalAudit';
import { auditEventRegistry } from './auditEventRegistry';
import { causalTraceService } from './causalTraceService';

export class OperationTraceService {
  /**
   * Reconstructs the deterministic operation trace for an operationId.
   */
  public getOperationTrace(operationId: string): OperationTrace {
    const events = auditEventRegistry.getEventsByOperationId(operationId);

    if (events.length === 0) {
      return {
        operationId,
        correlationId: 'UNKNOWN_CORRELATION',
        rootOrigin: {
          originType: 'UNKNOWN',
          originId: 'UNKNOWN',
          actor: { actorId: 'unknown', actorType: 'SYSTEM' },
          timestamp: 0,
        },
        terminalStatus: 'UNKNOWN',
        epistemicStatus: 'UNKNOWN',
        isCompleted: false,
        totalDurationMs: 0,
        steps: [
          {
            stepIndex: 1,
            stageName: 'Unknown',
            nodeType: 'MISSING_EVIDENCE',
            referenceId: operationId,
            timestamp: 0,
            status: 'UNKNOWN',
            epistemicStatus: 'UNKNOWN',
            description: `No audit events found for operationId '${operationId}'.`,
            isMissingEvidence: true,
          },
        ],
        causalGraph: causalTraceService.buildCausalGraph(operationId),
        deterministicExplanation: `Operation '${operationId}' has no recorded operational audit events.`,
        evidenceLedger: [],
      };
    }

    // Sort events chronologically
    const sorted = [...events].sort((a, b) => a.timestamp - b.timestamp);
    const firstEvt = sorted[0];
    const lastEvt = sorted[sorted.length - 1];

    const totalDurationMs = Math.max(0, lastEvt.timestamp - firstEvt.timestamp);
    const terminalStatus = lastEvt.lifecycleState;
    const epistemicStatus = lastEvt.epistemicStatus;
    const isCompleted =
      terminalStatus === 'SUCCEEDED' ||
      terminalStatus === 'FAILED' ||
      terminalStatus === 'REJECTED' ||
      terminalStatus === 'DENIED' ||
      terminalStatus === 'RECONCILED';

    // 1. Reconstruct chronological steps
    const steps: CausalTraceStep[] = [];
    let stepIndex = 1;

    for (const evt of sorted) {
      steps.push({
        stepIndex: stepIndex++,
        stageName: evt.sourceSystem,
        nodeType: this.mapEventTypeToNodeType(evt),
        referenceId: evt.eventId,
        timestamp: evt.timestamp,
        status: evt.lifecycleState,
        epistemicStatus: evt.epistemicStatus,
        description: `${evt.eventType}: ${evt.reason || evt.lifecycleState}`,
        evidenceId: evt.evidenceReferences[0],
        isMissingEvidence: false,
      });
    }

    // 2. Detect missing structural links
    // Check if an Action was dispatched or executed, but Policy or Governance was missing
    const hasAction = sorted.some((e) => e.eventType === 'ACTION_DISPATCHED' || e.eventType === 'ACTION_EXECUTED');
    const hasGovernance = sorted.some((e) => e.eventType === 'GOVERNANCE_DECIDED');
    if (hasAction && !hasGovernance) {
      steps.splice(steps.length - 1, 0, {
        stepIndex: stepIndex++,
        stageName: 'Stage 21 Governance',
        nodeType: 'MISSING_EVIDENCE',
        referenceId: 'MISSING_GOVERNANCE_CHECK',
        timestamp: firstEvt.timestamp,
        status: 'UNKNOWN',
        epistemicStatus: 'UNKNOWN',
        description: 'Missing evidence: Action was dispatched without recorded governance evaluation.',
        isMissingEvidence: true,
      });
    }

    // 3. Collect evidence ledger
    const evidenceSet = new Set<string>();
    for (const evt of sorted) {
      for (const evId of evt.evidenceReferences) {
        evidenceSet.add(evId);
      }
    }

    // 4. Generate deterministic narrative explanation
    const deterministicExplanation = this.generateDeterministicExplanation(sorted, lastEvt);

    return {
      operationId,
      correlationId: firstEvt.correlationId,
      causationId: firstEvt.causationId,
      parentOperationId: firstEvt.parentOperationId,
      rootOrigin: {
        originType: firstEvt.eventType,
        originId: firstEvt.eventId,
        actor: firstEvt.actor,
        timestamp: firstEvt.timestamp,
      },
      terminalStatus,
      epistemicStatus,
      isCompleted,
      totalDurationMs,
      steps,
      causalGraph: causalTraceService.buildCausalGraph(operationId),
      failureBoundary: lastEvt.failureBoundary,
      deterministicExplanation,
      evidenceLedger: Array.from(evidenceSet),
    };
  }

  private generateDeterministicExplanation(
    events: OperationalAuditEvent[],
    lastEvent: OperationalAuditEvent
  ): string {
    const origin = events[0];
    const trigger = events.find((e) => e.eventType === 'TRIGGER_EVALUATED');
    const reaction = events.find((e) => e.eventType === 'REACTION_PROPOSED');
    const policy = events.find((e) => e.eventType === 'POLICY_EVALUATED');
    const gov = events.find((e) => e.eventType === 'GOVERNANCE_DECIDED');
    const action = events.find((e) => e.eventType === 'ACTION_DISPATCHED');
    const result = events.find(
      (e) =>
        e.eventType === 'ACTION_EXECUTED' ||
        e.eventType === 'OPERATION_SUCCEEDED' ||
        e.eventType === 'OPERATION_FAILED'
    );
    const reconciled = events.find((e) => e.eventType === 'STATE_RECONCILED');

    const narrative: string[] = [];

    narrative.push(`Operation '${origin.operationId}' originated from ${origin.actor.actorType} (${origin.actor.actorId}) via ${origin.eventType}.`);

    if (trigger) {
      narrative.push(`Trigger '${trigger.triggerId || 'anonymous'}' matched event conditions.`);
    }

    if (reaction) {
      narrative.push(`Reaction proposal '${reaction.proposalId || 'unidentified'}' was formulated with risk '${reaction.riskLevel || 'LOW'}'.`);
    }

    if (policy) {
      narrative.push(`Policy '${policy.policyId || 'baseline'}' v${policy.policyVersion || 1} was evaluated.`);
    }

    if (gov) {
      narrative.push(`Governance control plane rendered decision '${gov.governanceDecision || 'UNKNOWN'}'.`);
    }

    if (action) {
      narrative.push(`Action '${action.actionId || 'act-unidentified'}' was dispatched to Action Bus.`);
    } else if (gov?.governanceDecision === 'DENY' || gov?.governanceDecision === 'REQUIRE_APPROVAL') {
      narrative.push(`No Action Bus dispatch occurred due to governance restriction (${gov.governanceDecision}).`);
    }

    if (result) {
      narrative.push(`Execution completed with status '${result.lifecycleState}' (Epistemic: ${result.epistemicStatus}).`);
    }

    if (reconciled) {
      narrative.push(`Post-execution system state successfully reconciled.`);
    } else if (lastEvent.failureBoundary) {
      narrative.push(
        `Operation halted at boundary '${lastEvent.failureBoundary.boundary}' in ${lastEvent.failureBoundary.stoppingStage}: ${lastEvent.failureBoundary.reason}`
      );
    }

    return narrative.join(' ');
  }

  private mapEventTypeToNodeType(evt: OperationalAuditEvent): CausalNodeType {
    switch (evt.eventType) {
      case 'REQUEST_RECEIVED':
      case 'REQUEST_VALIDATED':
        return evt.actor.actorType === 'USER' ? 'USER_REQUEST' : 'EXTERNAL_EVENT';
      case 'GOAL_ORCHESTRATED':
        return evt.missionId ? 'MISSION' : 'GOAL';
      case 'TRIGGER_EVALUATED':
        return 'TRIGGER';
      case 'REACTION_PROPOSED':
        return 'REACTION';
      case 'POLICY_EVALUATED':
        return 'POLICY';
      case 'GOVERNANCE_DECIDED':
        return 'GOVERNANCE_DECISION';
      case 'AUTHORITY_CHECKED':
        return 'AUTHORIZATION';
      case 'ACTION_DISPATCHED':
      case 'ACTION_EXECUTED':
        return 'ACTION';
      case 'OBSERVATION_RECORDED':
        return 'OBSERVATION';
      case 'STATE_RECONCILED':
      case 'OPERATION_SUCCEEDED':
      case 'OPERATION_FAILED':
      case 'OPERATION_DENIED':
      case 'OPERATION_PAUSED':
      case 'OPERATION_DEFERRED':
      case 'OPERATION_UNKNOWN':
        return 'RESULT';
      default:
        return 'OBSERVATION';
    }
  }
}

export const operationTraceService = new OperationTraceService();
