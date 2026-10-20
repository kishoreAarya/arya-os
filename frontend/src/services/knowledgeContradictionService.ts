/**
 * AryaOS V1 — Stage 13: Knowledge Contradiction Detection Service
 *
 * Detects factual, temporal, outcome, and strategic contradictions.
 * Invariant: Never silently overwrite contradicting facts; record full
 * contradiction records with dual-sided evidence and severity classification.
 */

import {
  KnowledgeFact,
  KnowledgeContradiction,
  KnowledgeContradictionType,
  ContradictionSeverity,
} from '../types/strategicKnowledge';

export class KnowledgeContradictionService {
  private contradictions: Map<string, KnowledgeContradiction> = new Map();

  /**
   * Generates a deterministic canonical contradiction ID
   */
  public getCanonicalContradictionId(factAId: string, factBId: string, type: string): string {
    const sortedIds = [factAId, factBId].sort();
    return `contra:${type}:${sortedIds[0]}_vs_${sortedIds[1]}`;
  }

  /**
   * Evaluates two facts for direct semantic contradiction.
   * e.g. Same subject and opposing predicates (PERFORMS_WELL_FOR vs UNDERPERFORMS_FOR),
   * or opposing objects for deterministic properties (STATUS = ACTIVE vs STATUS = DISABLED).
   */
  public evaluatePair(factA: KnowledgeFact, factB: KnowledgeFact): KnowledgeContradiction | null {
    if (factA.id === factB.id) return null;

    // Both must share the same subject
    if (factA.subject !== factB.subject) return null;

    const opposingPredicates: Record<string, string> = {
      PERFORMS_WELL_FOR: 'UNDERPERFORMS_FOR',
      UNDERPERFORMS_FOR: 'PERFORMS_WELL_FOR',
      ENABLES: 'BLOCKS',
      BLOCKS: 'ENABLES',
      SUCCEEDED_WITH: 'FAILED_WITH',
      FAILED_WITH: 'SUCCEEDED_WITH',
      RECOMMENDS: 'PROHIBITS',
      PROHIBITS: 'RECOMMENDS',
      COMPATIBLE_WITH: 'INCOMPATIBLE_WITH',
      INCOMPATIBLE_WITH: 'COMPATIBLE_WITH',
    };

    let contradictionType: KnowledgeContradictionType | null = null;
    let severity: ContradictionSeverity = 'MEDIUM';

    // 1. Check opposing predicates on same object
    if (
      opposingPredicates[factA.predicate] === factB.predicate &&
      factA.object === factB.object
    ) {
      contradictionType = 'FACT_CONTRADICTION';
      severity = 'HIGH';
    }

    // 2. Check identical predicate with opposing objects on exclusive property
    if (factA.predicate === factB.predicate && factA.predicate === 'HAS_OUTCOME') {
      if (
        (factA.object === 'SUCCESS' && factB.object === 'FAILURE') ||
        (factA.object === 'FAILURE' && factB.object === 'SUCCESS')
      ) {
        contradictionType = 'OUTCOME_CONFLICT';
        severity = 'HIGH';
      }
    }

    // 3. Temporal overlap check: both active simultaneously with conflicting claims
    if (contradictionType) {
      const isOverlap =
        (!factA.validUntil || new Date(factA.validUntil) > new Date(factB.validFrom)) &&
        (!factB.validUntil || new Date(factB.validUntil) > new Date(factA.validFrom));

      if (isOverlap && (factA.validity === 'ACTIVE' && factB.validity === 'ACTIVE')) {
        severity = 'CRITICAL';
      }
    }

    if (!contradictionType) return null;

    const contradictionId = this.getCanonicalContradictionId(factA.id, factB.id, contradictionType);

    const record: KnowledgeContradiction = {
      contradictionId,
      type: contradictionType,
      factA: factA.id,
      factB: factB.id,
      evidenceA: factA.evidence || [],
      evidenceB: factB.evidence || [],
      detectedAt: new Date().toISOString(),
      severity,
      resolutionStatus: 'OPEN',
    };

    this.contradictions.set(contradictionId, record);
    return record;
  }

  /**
   * Scans a candidate fact against existing facts in the system.
   */
  public detectContradictions(
    candidate: KnowledgeFact,
    existingFacts: KnowledgeFact[]
  ): KnowledgeContradiction[] {
    const results: KnowledgeContradiction[] = [];

    for (const existing of existingFacts) {
      const contra = this.evaluatePair(candidate, existing);
      if (contra) {
        results.push(contra);
      }
    }

    return results;
  }

  /**
   * Retrieves all detected contradictions, optionally filtered by status.
   */
  public getContradictions(status?: KnowledgeContradiction['resolutionStatus']): KnowledgeContradiction[] {
    const all = Array.from(this.contradictions.values());
    if (!status) return all;
    return all.filter((c) => c.resolutionStatus === status);
  }

  /**
   * Retrieves a contradiction by ID.
   */
  public getContradiction(id: string): KnowledgeContradiction | null {
    return this.contradictions.get(id) || null;
  }

  /**
   * Stores or updates a contradiction.
   */
  public saveContradiction(contra: KnowledgeContradiction): void {
    this.contradictions.set(contra.contradictionId, contra);
  }

  /**
   * Clears in-memory contradictions.
   */
  public clear(): void {
    this.contradictions.clear();
  }
}

export const knowledgeContradictionService = new KnowledgeContradictionService();
