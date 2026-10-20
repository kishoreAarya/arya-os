/**
 * AryaOS V1 — Stage 11: Evidence Graph Service
 *
 * Bidirectional relationship graph connecting:
 * GOAL -> ACTION -> AGENT -> PROVIDER -> EXECUTION -> OUTPUT -> EVALUATION -> DECISION -> HUMAN_APPROVAL
 *
 * Supports provenance tracing, auditability, and structured evidence verification.
 */

import { EvidenceItem, ConfidenceBand } from '../types/agentEvaluation';

export interface EvidenceEdge {
  sourceId: string;
  targetId: string;
  relationship: string;
  timestamp: string;
}

export class EvidenceGraph {
  private nodes: Map<string, EvidenceItem> = new Map();
  private edges: EvidenceEdge[] = [];

  /**
   * Adds or updates an evidence item node.
   */
  public addEvidence(item: EvidenceItem): void {
    this.nodes.set(item.entityId, item);
  }

  /**
   * Creates a bidirectional or directed edge between two entities.
   */
  public linkEntities(
    sourceId: string,
    targetId: string,
    relationship: string,
    timestamp: string = new Date().toISOString()
  ): void {
    // Avoid duplicate edges
    const exists = this.edges.some(
      (e) => e.sourceId === sourceId && e.targetId === targetId && e.relationship === relationship
    );
    if (!exists) {
      this.edges.push({ sourceId, targetId, relationship, timestamp });
    }
  }

  /**
   * Retrieves an evidence node by entityId.
   */
  public getEvidence(entityId: string): EvidenceItem | undefined {
    return this.nodes.get(entityId);
  }

  /**
   * Traverses related entities up to a specified depth.
   */
  public getRelatedEntities(
    entityId: string,
    maxDepth: number = 3
  ): Array<{ item: EvidenceItem; relationship: string; depth: number }> {
    const results: Array<{ item: EvidenceItem; relationship: string; depth: number }> = [];
    const visited = new Set<string>([entityId]);
    const queue: Array<{ id: string; depth: number; incomingRel: string }> = [
      { id: entityId, depth: 0, incomingRel: 'SELF' },
    ];

    while (queue.length > 0) {
      const current = queue.shift()!;
      if (current.depth >= maxDepth) continue;

      // Find all connected edges (both directions)
      const connectedEdges = this.edges.filter(
        (e) => e.sourceId === current.id || e.targetId === current.id
      );

      for (const edge of connectedEdges) {
        const neighborId = edge.sourceId === current.id ? edge.targetId : edge.sourceId;
        if (!visited.has(neighborId)) {
          visited.add(neighborId);
          const neighborNode = this.nodes.get(neighborId);
          if (neighborNode) {
            results.push({
              item: neighborNode,
              relationship: edge.relationship,
              depth: current.depth + 1,
            });
          }
          queue.push({
            id: neighborId,
            depth: current.depth + 1,
            incomingRel: edge.relationship,
          });
        }
      }
    }

    return results;
  }

  /**
   * Traces an evaluation or decision back to its root execution provenance:
   * Goal, Action, Agent, Provider, Execution, and Human Approval.
   */
  public traceEvaluationToProvenance(evaluationId: string): {
    evaluationId: string;
    goalId?: string;
    actionId?: string;
    agentId?: string;
    providerId?: string;
    executionId?: string;
    humanApprovalId?: string;
    evidence: EvidenceItem[];
  } {
    const related = this.getRelatedEntities(evaluationId, 5);
    const evidenceList: EvidenceItem[] = [];

    const evalNode = this.nodes.get(evaluationId);
    if (evalNode) evidenceList.push(evalNode);

    let goalId: string | undefined;
    let actionId: string | undefined;
    let agentId: string | undefined;
    let providerId: string | undefined;
    let executionId: string | undefined;
    let humanApprovalId: string | undefined;

    for (const rel of related) {
      evidenceList.push(rel.item);
      switch (rel.item.entityType) {
        case 'GOAL':
          if (!goalId) goalId = rel.item.entityId;
          break;
        case 'ACTION':
          if (!actionId) actionId = rel.item.entityId;
          break;
        case 'AGENT':
          if (!agentId) agentId = rel.item.entityId;
          break;
        case 'PROVIDER':
          if (!providerId) providerId = rel.item.entityId;
          break;
        case 'EXECUTION':
          if (!executionId) executionId = rel.item.entityId;
          break;
        case 'HUMAN_APPROVAL':
          if (!humanApprovalId) humanApprovalId = rel.item.entityId;
          break;
      }
    }

    return {
      evaluationId,
      goalId,
      actionId,
      agentId,
      providerId,
      executionId,
      humanApprovalId,
      evidence: evidenceList,
    };
  }

  /**
   * Creates and registers a standard EvidenceItem helper.
   */
  public createEvidenceItem(
    entityType: EvidenceItem['entityType'],
    entityId: string,
    summary: string,
    source: string,
    confidence: ConfidenceBand = 'MEDIUM',
    metadata: Record<string, unknown> = {}
  ): EvidenceItem {
    const item: EvidenceItem = {
      evidenceId: `ev-${entityType.toLowerCase()}-${Date.now()}-${Math.random().toString(36).substr(2, 6)}`,
      entityType,
      entityId,
      summary,
      timestamp: new Date().toISOString(),
      source,
      confidence,
      metadata,
    };
    this.addEvidence(item);
    return item;
  }

  /**
   * Returns all registered nodes.
   */
  public getAllNodes(): EvidenceItem[] {
    return Array.from(this.nodes.values());
  }

  /**
   * Returns all edges.
   */
  public getAllEdges(): EvidenceEdge[] {
    return [...this.edges];
  }

  /**
   * Clears in-memory graph.
   */
  public clear(): void {
    this.nodes.clear();
    this.edges = [];
  }
}

export const evidenceGraph = new EvidenceGraph();
