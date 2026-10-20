/**
 * AryaOS V1 — Stage 22: Causal Trace Service
 *
 * Constructs and bounds the operational causal graph linking events, triggers,
 * policies, governance decisions, actions, results, and observations.
 *
 * Enforces cycle protection, maximum depth, maximum node count, and explicit
 * representation of missing evidence without deleting historical facts.
 */

import {
  CausalGraph,
  CausalNode,
  CausalEdge,
  CausalNodeType,
  CausalEdgeType,
  MAX_CAUSAL_DEPTH,
  MAX_CAUSAL_NODES,
  OperationalAuditEvent,
} from '../types/operationalAudit';
import { auditEventRegistry } from './auditEventRegistry';

export class CausalTraceService {
  /**
   * Reconstructs the bounded causal graph for a specific operation.
   */
  public buildCausalGraph(operationId: string): CausalGraph {
    const events = auditEventRegistry.getEventsByOperationId(operationId);

    const nodesMap: Map<string, CausalNode> = new Map();
    const edges: CausalEdge[] = [];
    const visitedInPath: Set<string> = new Set();
    let hasCycles = false;
    let isTruncated = false;
    let maxDepthReached = 0;

    if (events.length === 0) {
      return {
        operationId,
        rootNodeId: 'node-empty',
        nodes: [],
        edges: [],
        maxDepthReached: 0,
        isTruncated: false,
        hasCycles: false,
      };
    }

    // Sort events chronologically
    const sorted = [...events].sort((a, b) => a.timestamp - b.timestamp);
    const rootEvent = sorted[0];
    const rootNodeId = this.getNodeIdForEvent(rootEvent);

    // 1. Build nodes from chronological events
    for (const evt of sorted) {
      if (nodesMap.size >= MAX_CAUSAL_NODES) {
        isTruncated = true;
        break;
      }

      const nodeId = this.getNodeIdForEvent(evt);
      if (!nodesMap.has(nodeId)) {
        nodesMap.set(nodeId, {
          nodeId,
          nodeType: this.mapEventTypeToNodeType(evt),
          label: `${evt.eventType} (${evt.lifecycleState})`,
          timestamp: evt.timestamp,
          stageSource: evt.sourceSystem,
          status: evt.lifecycleState,
          epistemicStatus: evt.epistemicStatus,
          metadata: {
            actor: evt.actor,
            reason: evt.reason,
            failureBoundary: evt.failureBoundary,
          },
        });
      }
    }

    // 2. Link edges based on explicit causal identifiers and sequential progression
    for (let i = 0; i < sorted.length; i++) {
      if (nodesMap.size >= MAX_CAUSAL_NODES || edges.length >= MAX_CAUSAL_NODES * 2) {
        isTruncated = true;
        break;
      }

      const currentEvt = sorted[i];
      const currentNodeId = this.getNodeIdForEvent(currentEvt);

      // Causal link via causationId if pointing to another event in this operation
      if (currentEvt.causationId) {
        const parentEvt = sorted.find(
          (e) => e.eventId === currentEvt.causationId || e.operationId === currentEvt.causationId
        );
        if (parentEvt) {
          const parentNodeId = this.getNodeIdForEvent(parentEvt);
          this.addEdgeSafe(edges, parentNodeId, currentNodeId, 'CAUSED_BY', currentEvt.timestamp, visitedInPath, () => {
            hasCycles = true;
          });
          continue;
        }
      }

      // Parent operation link
      if (currentEvt.parentOperationId) {
        const parentOpEvt = sorted.find((e) => e.operationId === currentEvt.parentOperationId);
        if (parentOpEvt) {
          const parentNodeId = this.getNodeIdForEvent(parentOpEvt);
          this.addEdgeSafe(edges, parentNodeId, currentNodeId, 'PARENT_OF', currentEvt.timestamp, visitedInPath, () => {
            hasCycles = true;
          });
          continue;
        }
      }

      // Sequential progression link if not first event
      if (i > 0) {
        const prevEvt = sorted[i - 1];
        const prevNodeId = this.getNodeIdForEvent(prevEvt);
        const edgeType = this.resolveEdgeType(prevEvt, currentEvt);
        this.addEdgeSafe(edges, prevNodeId, currentNodeId, edgeType, currentEvt.timestamp, visitedInPath, () => {
          hasCycles = true;
        });
      }
    }

    // 3. Compute traversal depth
    maxDepthReached = this.calculateMaxDepth(rootNodeId, edges, 0, new Set());
    if (maxDepthReached >= MAX_CAUSAL_DEPTH) {
      isTruncated = true;
    }

    return {
      operationId,
      rootNodeId,
      nodes: Array.from(nodesMap.values()),
      edges,
      maxDepthReached: Math.min(maxDepthReached, MAX_CAUSAL_DEPTH),
      isTruncated,
      hasCycles,
    };
  }

  /**
   * Adds an edge safely, rejecting self-cycles and detecting graph cycles.
   */
  public addEdgeSafe(
    edges: CausalEdge[],
    fromNodeId: string,
    toNodeId: string,
    edgeType: CausalEdgeType,
    timestamp: number,
    visitedInPath: Set<string>,
    onCycle: () => void
  ): boolean {
    // 1. Reject impossible self-cycles
    if (fromNodeId === toNodeId) {
      onCycle();
      return false;
    }

    // 2. Detect cycle in current traversal path
    if (visitedInPath.has(toNodeId)) {
      onCycle();
      return false;
    }

    // 3. Duplicate edge prevention
    const exists = edges.some(
      (e) => e.fromNodeId === fromNodeId && e.toNodeId === toNodeId && e.edgeType === edgeType
    );
    if (exists) {
      return false;
    }

    edges.push({
      fromNodeId,
      toNodeId,
      edgeType,
      timestamp,
    });

    visitedInPath.add(fromNodeId);
    return true;
  }

  /**
   * Calculates maximum traversal depth with cycle safety.
   */
  private calculateMaxDepth(
    currentNodeId: string,
    edges: CausalEdge[],
    currentDepth: number,
    visited: Set<string>
  ): number {
    if (currentDepth >= MAX_CAUSAL_DEPTH || visited.has(currentNodeId)) {
      return currentDepth;
    }

    visited.add(currentNodeId);
    const outgoing = edges.filter((e) => e.fromNodeId === currentNodeId);
    if (outgoing.length === 0) {
      visited.delete(currentNodeId);
      return currentDepth;
    }

    let maxChildDepth = currentDepth;
    for (const edge of outgoing) {
      const depth = this.calculateMaxDepth(edge.toNodeId, edges, currentDepth + 1, visited);
      if (depth > maxChildDepth) {
        maxChildDepth = depth;
      }
    }

    visited.delete(currentNodeId);
    return maxChildDepth;
  }

  private getNodeIdForEvent(evt: OperationalAuditEvent): string {
    return `node-${evt.eventType.toLowerCase().replace(/_/g, '-')}-${evt.eventId}`;
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

  private resolveEdgeType(prev: OperationalAuditEvent, curr: OperationalAuditEvent): CausalEdgeType {
    if (curr.eventType === 'TRIGGER_EVALUATED') return 'TRIGGERED';
    if (curr.eventType === 'REACTION_PROPOSED') return 'PROPOSED';
    if (curr.eventType === 'POLICY_EVALUATED' || curr.eventType === 'GOVERNANCE_DECIDED') return 'GOVERNED_BY';
    if (curr.eventType === 'AUTHORITY_CHECKED') return 'AUTHORIZED_BY';
    if (curr.eventType === 'ACTION_DISPATCHED') return 'DISPATCHED_TO';
    if (curr.eventType === 'ACTION_EXECUTED' || curr.eventType.startsWith('OPERATION_')) return 'RESULTED_IN';
    if (curr.eventType === 'STATE_RECONCILED') return 'RECONCILED_TO';
    if (curr.eventType === 'OBSERVATION_RECORDED') return 'OBSERVED_AS';
    return 'CAUSED_BY';
  }
}

export const causalTraceService = new CausalTraceService();
