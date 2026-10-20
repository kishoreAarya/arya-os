/**
 * AryaOS V1 — Stage 13: Knowledge Graph Service
 *
 * Deterministic graph representation of cross-domain strategic knowledge.
 * Supports canonical nodes, typed directed edges, deduplication, neighbor discovery,
 * pathfinding, and bounded subgraph extraction.
 */

import {
  KnowledgeNode,
  KnowledgeEdge,
  KnowledgeNodeType,
} from '../types/strategicKnowledge';

export class KnowledgeGraph {
  private nodes: Map<string, KnowledgeNode> = new Map();
  private edges: Map<string, KnowledgeEdge> = new Map();
  // Adjacency indices: nodeId -> Set of edge IDs
  private outEdges: Map<string, Set<string>> = new Map();
  private inEdges: Map<string, Set<string>> = new Map();

  /**
   * Generates a deterministic canonical edge ID
   */
  public getCanonicalEdgeId(source: string, target: string, relation: string): string {
    return `edge:${source}--${relation}-->${target}`;
  }

  /**
   * Adds or updates a canonical node.
   * Idempotent: repeated ingestion updates timestamp and preserves canonical identity.
   */
  public addNode(node: KnowledgeNode): KnowledgeNode {
    if (!node.id || !node.type) {
      throw new Error('KnowledgeNode must have a valid id and type');
    }

    const existing = this.nodes.get(node.id);
    if (existing) {
      // Merge / update
      const updated: KnowledgeNode = {
        ...existing,
        ...node,
        createdAt: existing.createdAt,
        updatedAt: node.updatedAt || new Date().toISOString(),
        metadata: {
          ...existing.metadata,
          ...node.metadata,
        },
      };
      this.nodes.set(node.id, updated);
      return updated;
    }

    const newNode: KnowledgeNode = {
      ...node,
      createdAt: node.createdAt || new Date().toISOString(),
      updatedAt: node.updatedAt || new Date().toISOString(),
    };
    this.nodes.set(newNode.id, newNode);
    if (!this.outEdges.has(newNode.id)) this.outEdges.set(newNode.id, new Set());
    if (!this.inEdges.has(newNode.id)) this.inEdges.set(newNode.id, new Set());
    return newNode;
  }

  /**
   * Retrieves a node by ID.
   */
  public getNode(id: string): KnowledgeNode | null {
    return this.nodes.get(id) || null;
  }

  /**
   * Retrieves all nodes, optionally filtered by node type.
   */
  public getNodes(type?: KnowledgeNodeType): KnowledgeNode[] {
    const all = Array.from(this.nodes.values());
    if (!type) return all;
    return all.filter((n) => n.type === type);
  }

  /**
   * Removes a node and all connected incoming/outgoing edges.
   */
  public removeNode(id: string): boolean {
    if (!this.nodes.has(id)) return false;

    // Remove outgoing edges
    const outSet = this.outEdges.get(id);
    if (outSet) {
      for (const edgeId of outSet) {
        const edge = this.edges.get(edgeId);
        if (edge) {
          const inSet = this.inEdges.get(edge.target);
          if (inSet) inSet.delete(edgeId);
          this.edges.delete(edgeId);
        }
      }
      this.outEdges.delete(id);
    }

    // Remove incoming edges
    const inSet = this.inEdges.get(id);
    if (inSet) {
      for (const edgeId of inSet) {
        const edge = this.edges.get(edgeId);
        if (edge) {
          const outSet2 = this.outEdges.get(edge.source);
          if (outSet2) outSet2.delete(edgeId);
          this.edges.delete(edgeId);
        }
      }
      this.inEdges.delete(id);
    }

    this.nodes.delete(id);
    return true;
  }

  /**
   * Adds a directed typed edge between two existing nodes.
   * Idempotent: duplicate edges with identical source, target, and relation are merged.
   */
  public addEdge(edge: KnowledgeEdge): KnowledgeEdge {
    if (!this.nodes.has(edge.source)) {
      throw new Error(`Cannot add edge: source node '${edge.source}' does not exist in graph`);
    }
    if (!this.nodes.has(edge.target)) {
      throw new Error(`Cannot add edge: target node '${edge.target}' does not exist in graph`);
    }

    const canonicalId = edge.id || this.getCanonicalEdgeId(edge.source, edge.target, edge.relation);
    const existing = this.edges.get(canonicalId);
    if (existing) {
      // Idempotent update
      const updated: KnowledgeEdge = {
        ...existing,
        ...edge,
        id: canonicalId,
      };
      this.edges.set(canonicalId, updated);
      return updated;
    }

    const newEdge: KnowledgeEdge = {
      ...edge,
      id: canonicalId,
      createdAt: edge.createdAt || new Date().toISOString(),
    };
    this.edges.set(canonicalId, newEdge);

    if (!this.outEdges.has(edge.source)) this.outEdges.set(edge.source, new Set());
    if (!this.inEdges.has(edge.target)) this.inEdges.set(edge.target, new Set());

    this.outEdges.get(edge.source)!.add(canonicalId);
    this.inEdges.get(edge.target)!.add(canonicalId);

    return newEdge;
  }

  /**
   * Retrieves all edges, optionally filtered by node ID (source or target).
   */
  public getEdges(nodeId?: string): KnowledgeEdge[] {
    if (!nodeId) {
      return Array.from(this.edges.values());
    }

    const edgeIds = new Set<string>();
    const outSet = this.outEdges.get(nodeId);
    if (outSet) outSet.forEach((id) => edgeIds.add(id));
    const inSet = this.inEdges.get(nodeId);
    if (inSet) inSet.forEach((id) => edgeIds.add(id));

    return Array.from(edgeIds)
      .map((id) => this.edges.get(id))
      .filter((e): e is KnowledgeEdge => !!e);
  }

  /**
   * Retrieves immediate neighbor nodes in the specified direction.
   */
  public getNeighbors(nodeId: string, direction: 'IN' | 'OUT' | 'BOTH' = 'BOTH'): KnowledgeNode[] {
    const neighborIds = new Set<string>();

    if (direction === 'OUT' || direction === 'BOTH') {
      const outSet = this.outEdges.get(nodeId);
      if (outSet) {
        for (const edgeId of outSet) {
          const edge = this.edges.get(edgeId);
          if (edge) neighborIds.add(edge.target);
        }
      }
    }

    if (direction === 'IN' || direction === 'BOTH') {
      const inSet = this.inEdges.get(nodeId);
      if (inSet) {
        for (const edgeId of inSet) {
          const edge = this.edges.get(edgeId);
          if (edge) neighborIds.add(edge.source);
        }
      }
    }

    return Array.from(neighborIds)
      .map((id) => this.nodes.get(id))
      .filter((n): n is KnowledgeNode => !!n);
  }

  /**
   * Finds connected nodes with a specific relation predicate.
   */
  public findRelated(nodeId: string, relationType?: string): KnowledgeNode[] {
    const outSet = this.outEdges.get(nodeId);
    if (!outSet) return [];

    const relatedNodes: KnowledgeNode[] = [];
    for (const edgeId of outSet) {
      const edge = this.edges.get(edgeId);
      if (edge && (!relationType || edge.relation === relationType)) {
        const targetNode = this.nodes.get(edge.target);
        if (targetNode) relatedNodes.push(targetNode);
      }
    }
    return relatedNodes;
  }

  /**
   * Deterministic BFS shortest path between startId and targetId.
   */
  public findPath(startId: string, targetId: string, maxDepth = 10): string[] | null {
    if (startId === targetId) return [startId];
    if (!this.nodes.has(startId) || !this.nodes.has(targetId)) return null;

    const queue: Array<{ current: string; path: string[] }> = [
      { current: startId, path: [startId] },
    ];
    const visited = new Set<string>([startId]);

    while (queue.length > 0) {
      const { current, path } = queue.shift()!;
      if (path.length > maxDepth) continue;

      const outSet = this.outEdges.get(current);
      if (!outSet) continue;

      for (const edgeId of outSet) {
        const edge = this.edges.get(edgeId);
        if (!edge) continue;
        const next = edge.target;

        if (next === targetId) {
          return [...path, next];
        }

        if (!visited.has(next)) {
          visited.add(next);
          queue.push({ current: next, path: [...path, next] });
        }
      }
    }

    return null;
  }

  /**
   * Extracts a bounded subgraph centered at rootId up to max depth.
   */
  public querySubgraph(rootId: string, depth = 2): { nodes: KnowledgeNode[]; edges: KnowledgeEdge[] } {
    if (!this.nodes.has(rootId)) {
      return { nodes: [], edges: [] };
    }

    const visitedNodes = new Set<string>([rootId]);
    const visitedEdges = new Set<string>();
    let currentFrontier = [rootId];

    for (let d = 0; d < depth; d++) {
      const nextFrontier: string[] = [];

      for (const curr of currentFrontier) {
        // Collect out edges
        const outSet = this.outEdges.get(curr);
        if (outSet) {
          for (const edgeId of outSet) {
            const edge = this.edges.get(edgeId);
            if (edge) {
              visitedEdges.add(edgeId);
              if (!visitedNodes.has(edge.target)) {
                visitedNodes.add(edge.target);
                nextFrontier.push(edge.target);
              }
            }
          }
        }

        // Collect in edges
        const inSet = this.inEdges.get(curr);
        if (inSet) {
          for (const edgeId of inSet) {
            const edge = this.edges.get(edgeId);
            if (edge) {
              visitedEdges.add(edgeId);
              if (!visitedNodes.has(edge.source)) {
                visitedNodes.add(edge.source);
                nextFrontier.push(edge.source);
              }
            }
          }
        }
      }

      currentFrontier = nextFrontier;
      if (currentFrontier.length === 0) break;
    }

    const nodes = Array.from(visitedNodes)
      .map((id) => this.nodes.get(id))
      .filter((n): n is KnowledgeNode => !!n);

    const edges = Array.from(visitedEdges)
      .map((id) => this.edges.get(id))
      .filter((e): e is KnowledgeEdge => !!e);

    return { nodes, edges };
  }

  /**
   * Clears the graph.
   */
  public clear(): void {
    this.nodes.clear();
    this.edges.clear();
    this.outEdges.clear();
    this.inEdges.clear();
  }

  /**
   * Returns graph statistics.
   */
  public getStats(): { nodeCount: number; edgeCount: number; nodeTypes: Record<string, number> } {
    const nodeTypes: Record<string, number> = {};
    for (const node of this.nodes.values()) {
      nodeTypes[node.type] = (nodeTypes[node.type] || 0) + 1;
    }
    return {
      nodeCount: this.nodes.size,
      edgeCount: this.edges.size,
      nodeTypes,
    };
  }
}

export const knowledgeGraph = new KnowledgeGraph();
