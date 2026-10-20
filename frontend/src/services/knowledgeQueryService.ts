/**
 * AryaOS V1 — Stage 13: Knowledge Query Service
 *
 * Query execution engine over canonical knowledge facts, edges, nodes,
 * strategies, and contradictions.
 * Invariant: Never returns unsupported conclusions as facts. Truthful confidence.
 */

import {
  KnowledgeQuery,
  KnowledgeQueryResult,
  KnowledgeFact,
  KnowledgeConfidence,
  KnowledgeProvenance,
} from '../types/strategicKnowledge';
import { knowledgeGraph } from './knowledgeGraph';
import { executionPersistence } from './executionPersistence';
import { knowledgeConfidenceService } from './knowledgeConfidenceService';

export class KnowledgeQueryService {
  /**
   * Executes a structured query against the knowledge base.
   */
  public query(query: KnowledgeQuery): KnowledgeQueryResult {
    const allFacts = executionPersistence.getKnowledgeFacts();
    const allContradictions = executionPersistence.getKnowledgeContradictions();

    let matchedFacts = allFacts;

    if (query.subject) {
      matchedFacts = matchedFacts.filter(
        (f) => f.subject.toLowerCase() === query.subject!.toLowerCase()
      );
    }

    if (query.predicate) {
      matchedFacts = matchedFacts.filter(
        (f) => f.predicate.toLowerCase() === query.predicate!.toLowerCase()
      );
    }

    if (query.object) {
      matchedFacts = matchedFacts.filter(
        (f) => f.object.toLowerCase() === query.object!.toLowerCase()
      );
    }

    if (!query.includeObsolete) {
      matchedFacts = matchedFacts.filter(
        (f) => f.validity !== 'OBSOLETE' && f.validity !== 'SUPERSEDED'
      );
    }

    if (query.minConfidence) {
      const confRank: Record<KnowledgeConfidence, number> = {
        UNKNOWN: 0,
        LOW: 1,
        MEDIUM: 2,
        HIGH: 3,
      };
      const minRank = confRank[query.minConfidence] || 0;
      matchedFacts = matchedFacts.filter((f) => confRank[f.confidence] >= minRank);
    }

    if (query.limit && query.limit > 0) {
      matchedFacts = matchedFacts.slice(0, query.limit);
    }

    // Collect related nodes and edges from knowledgeGraph
    const nodeIds = new Set<string>();
    matchedFacts.forEach((f) => {
      nodeIds.add(f.subject);
      nodeIds.add(f.object);
    });

    const nodes = Array.from(nodeIds)
      .map((id) => knowledgeGraph.getNode(id))
      .filter((n): n is NonNullable<typeof n> => !!n);

    const edges = Array.from(nodeIds).flatMap((id) => knowledgeGraph.getEdges(id));

    // Deduplicate edges
    const uniqueEdgesMap = new Map<string, (typeof edges)[0]>();
    edges.forEach((e) => uniqueEdgesMap.set(e.id, e));
    const uniqueEdges = Array.from(uniqueEdgesMap.values());

    // Collect related contradictions
    const factIdSet = new Set(matchedFacts.map((f) => f.id));
    const contradictions = allContradictions.filter(
      (c) => factIdSet.has(c.factA) || factIdSet.has(c.factB)
    );

    // Compute composite query confidence
    let confidence: KnowledgeConfidence = 'UNKNOWN';
    if (matchedFacts.length > 0) {
      const confCounts: Record<KnowledgeConfidence, number> = {
        UNKNOWN: 0,
        LOW: 0,
        MEDIUM: 0,
        HIGH: 0,
      };
      matchedFacts.forEach((f) => confCounts[f.confidence]++);
      if (confCounts.HIGH > 0 && confCounts.HIGH >= matchedFacts.length / 2) {
        confidence = 'HIGH';
      } else if (confCounts.MEDIUM > 0) {
        confidence = 'MEDIUM';
      } else if (confCounts.LOW > 0) {
        confidence = 'LOW';
      }
    }

    const provenanceList: KnowledgeProvenance[] = matchedFacts.map((f) => f.provenance);

    return {
      facts: matchedFacts,
      evidence: [],
      nodes,
      edges: uniqueEdges,
      contradictions,
      confidence,
      provenanceList,
      timestamp: new Date().toISOString(),
      totalMatches: matchedFacts.length,
    };
  }

  /**
   * Helper query: "Which agents historically performed well for this capability/task?"
   */
  public queryAgentsForCapability(capability: string): KnowledgeQueryResult {
    return this.query({
      predicate: 'PERFORMS_WELL_FOR',
      object: capability,
      minConfidence: 'LOW',
    });
  }

  /**
   * Helper query: "What caused previous mission failures?"
   */
  public queryMissionFailureCauses(): KnowledgeQueryResult {
    return this.query({
      predicate: 'CAUSED_FAILURE',
      includeObsolete: true,
    });
  }

  /**
   * Helper query: "Which provider failures affected this task type?"
   */
  public queryProviderFailures(providerId?: string): KnowledgeQueryResult {
    return this.query({
      subject: providerId,
      predicate: 'FAILED_WITH',
      includeObsolete: true,
    });
  }
}

export const knowledgeQueryService = new KnowledgeQueryService();
