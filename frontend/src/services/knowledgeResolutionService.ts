/**
 * AryaOS V1 — Stage 13: Knowledge Resolution Service
 *
 * Resolves contradictions through deterministic evidence weighting, temporal
 * precedence, source priority, context partitioning, or human governance.
 * Invariant: Never deletes evidence. Preserves both sides with clear audit logs.
 */

import {
  KnowledgeContradiction,
  KnowledgeFact,
  ResolutionStrategy,
  KnowledgeEvidence,
} from '../types/strategicKnowledge';

export interface ResolutionResult {
  contradictionId: string;
  resolutionStatus: KnowledgeContradiction['resolutionStatus'];
  strategyUsed: ResolutionStrategy;
  preferredFactId?: string;
  deprecateFactId?: string;
  note: string;
  requiresHumanReview: boolean;
}

export class KnowledgeResolutionService {
  /**
   * Source reliability hierarchy for source-priority resolution
   */
  private readonly SOURCE_HIERARCHY: Record<string, number> = {
    OPERATOR_INPUT: 100,
    STAGE11_EVALUATION: 85,
    STAGE12_MISSION: 80,
    STAGE11_EXPERIENCE: 70,
    STAGE11_LEARNING_SIGNAL: 65,
    STAGE09_JOURNAL: 60,
    STAGE04_MEMORY: 50,
  };

  /**
   * Resolves a contradiction using the requested or most appropriate deterministic strategy.
   */
  public resolveContradiction(params: {
    contradiction: KnowledgeContradiction;
    factA: KnowledgeFact;
    factB: KnowledgeFact;
    evidenceListA?: KnowledgeEvidence[];
    evidenceListB?: KnowledgeEvidence[];
    preferredStrategy?: ResolutionStrategy;
    operatorNote?: string;
    operatorId?: string;
  }): ResolutionResult {
    const {
      contradiction,
      factA,
      factB,
      evidenceListA = [],
      evidenceListB = [],
      preferredStrategy,
      operatorNote,
      operatorId,
    } = params;

    // Consequential/Critical contradictions require explicit Human Review unless a preferred strategy was specified
    if (contradiction.severity === 'CRITICAL' && !operatorId && !preferredStrategy) {
      return {
        contradictionId: contradiction.contradictionId,
        resolutionStatus: 'UNDER_REVIEW',
        strategyUsed: 'HUMAN_REVIEW',
        note: 'Contradiction severity is CRITICAL. System requires operator signoff before resolution.',
        requiresHumanReview: true,
      };
    }

    // 1. HUMAN REVIEW STRATEGY
    if (preferredStrategy === 'HUMAN_REVIEW' || operatorId) {
      contradiction.resolutionStatus = 'RESOLVED';
      contradiction.resolutionStrategy = 'HUMAN_REVIEW';
      contradiction.resolvedAt = new Date().toISOString();
      contradiction.resolvedBy = operatorId || 'OPERATOR_DESK';
      contradiction.resolutionNote = operatorNote || 'Manually adjudicated and signed off by operator.';

      return {
        contradictionId: contradiction.contradictionId,
        resolutionStatus: 'RESOLVED',
        strategyUsed: 'HUMAN_REVIEW',
        note: contradiction.resolutionNote,
        requiresHumanReview: false,
      };
    }

    // 2. TEMPORAL RESOLUTION
    // If one fact is observed significantly later and the earlier has an expiry or natural obsolescence
    const timeA = new Date(factA.observedAt).getTime();
    const timeB = new Date(factB.observedAt).getTime();
    const timeDiffDays = Math.abs(timeA - timeB) / (1000 * 60 * 60 * 24);

    if (preferredStrategy === 'TEMPORAL_RESOLUTION' || (!preferredStrategy && timeDiffDays > 30)) {
      const newerFact = timeA > timeB ? factA : factB;
      const olderFact = timeA > timeB ? factB : factA;

      // Mark older fact as superseded without deleting
      olderFact.validity = 'SUPERSEDED';
      olderFact.supersededAt = newerFact.observedAt;

      contradiction.resolutionStatus = 'RESOLVED';
      contradiction.resolutionStrategy = 'TEMPORAL_RESOLUTION';
      contradiction.resolvedAt = new Date().toISOString();
      contradiction.resolvedBy = 'AUTOMATED_TEMPORAL_RULE';
      contradiction.resolutionNote = `Fact ${olderFact.id} superseded by newer evidence in Fact ${newerFact.id} (${timeDiffDays.toFixed(1)} days newer).`;

      return {
        contradictionId: contradiction.contradictionId,
        resolutionStatus: 'RESOLVED',
        strategyUsed: 'TEMPORAL_RESOLUTION',
        preferredFactId: newerFact.id,
        deprecateFactId: olderFact.id,
        note: contradiction.resolutionNote,
        requiresHumanReview: false,
      };
    }

    // 3. EVIDENCE WEIGHTING
    // Compare total weight & volume of evidence
    const weightA = evidenceListA.reduce((sum, e) => sum + (e.weight || 0.5), 0) + (factA.evidence?.length || 0);
    const weightB = evidenceListB.reduce((sum, e) => sum + (e.weight || 0.5), 0) + (factB.evidence?.length || 0);

    if (preferredStrategy === 'EVIDENCE_WEIGHTING' || (!preferredStrategy && Math.abs(weightA - weightB) >= 2.0)) {
      const dominantFact = weightA > weightB ? factA : factB;
      const weakerFact = weightA > weightB ? factB : factA;

      weakerFact.validity = 'DISPUTED';
      weakerFact.status = 'UNCERTAIN';

      contradiction.resolutionStatus = 'RESOLVED';
      contradiction.resolutionStrategy = 'EVIDENCE_WEIGHTING';
      contradiction.resolvedAt = new Date().toISOString();
      contradiction.resolvedBy = 'AUTOMATED_EVIDENCE_WEIGHTING';
      contradiction.resolutionNote = `Dominant evidence weight (${Math.max(weightA, weightB).toFixed(1)} vs ${Math.min(weightA, weightB).toFixed(1)}) favors Fact ${dominantFact.id}. Weaker fact marked DISPUTED without deletion.`;

      return {
        contradictionId: contradiction.contradictionId,
        resolutionStatus: 'RESOLVED',
        strategyUsed: 'EVIDENCE_WEIGHTING',
        preferredFactId: dominantFact.id,
        deprecateFactId: weakerFact.id,
        note: contradiction.resolutionNote,
        requiresHumanReview: false,
      };
    }

    // 4. SOURCE PRIORITY
    const priorityA = this.SOURCE_HIERARCHY[factA.provenance.source.sourceType] || 0;
    const priorityB = this.SOURCE_HIERARCHY[factB.provenance.source.sourceType] || 0;

    if (preferredStrategy === 'SOURCE_PRIORITY' || (!preferredStrategy && priorityA !== priorityB)) {
      const dominantFact = priorityA > priorityB ? factA : factB;
      const lowerFact = priorityA > priorityB ? factB : factA;

      lowerFact.validity = 'DISPUTED';

      contradiction.resolutionStatus = 'RESOLVED';
      contradiction.resolutionStrategy = 'SOURCE_PRIORITY';
      contradiction.resolvedAt = new Date().toISOString();
      contradiction.resolvedBy = 'AUTOMATED_SOURCE_PRIORITY';
      contradiction.resolutionNote = `Higher-tier provenance source (${dominantFact.provenance.source.sourceType} vs ${lowerFact.provenance.source.sourceType}) preferred for Fact ${dominantFact.id}.`;

      return {
        contradictionId: contradiction.contradictionId,
        resolutionStatus: 'RESOLVED',
        strategyUsed: 'SOURCE_PRIORITY',
        preferredFactId: dominantFact.id,
        deprecateFactId: lowerFact.id,
        note: contradiction.resolutionNote,
        requiresHumanReview: false,
      };
    }

    // Default fallback: hold for human review
    contradiction.resolutionStatus = 'UNDER_REVIEW';
    contradiction.resolutionStrategy = 'HUMAN_REVIEW';

    return {
      contradictionId: contradiction.contradictionId,
      resolutionStatus: 'UNDER_REVIEW',
      strategyUsed: 'HUMAN_REVIEW',
      note: 'Evidence is evenly matched across temporal, weight, and source metrics; escalating for operator adjudication.',
      requiresHumanReview: true,
    };
  }
}

export const knowledgeResolutionService = new KnowledgeResolutionService();
