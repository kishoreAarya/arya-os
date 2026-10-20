/**
 * AryaOS V1 — Stage 13: Knowledge Confidence & Decay Service
 *
 * Deterministic evaluation of knowledge confidence and temporal decay.
 * Preserves uncertainty: never converts a single observation into HIGH confidence.
 * Separates historical truth from current operational relevance.
 */

import {
  KnowledgeConfidence,
  KnowledgeEvidence,
  KnowledgeFact,
  KnowledgeContradiction,
} from '../types/strategicKnowledge';

export interface ConfidenceEvaluationResult {
  confidence: KnowledgeConfidence;
  numericalScore: number; // 0 to 1
  evidenceCount: number;
  averageEvidenceQuality: number;
  recencyFactor: number;
  consistencyFactor: number;
  decayedScore: number;
  isDecayed: boolean;
  explanation: string;
}

export class KnowledgeConfidenceService {
  private readonly DEFAULT_HALF_LIFE_DAYS = 60; // 60 days half-life for confidence decay

  /**
   * Evaluates the confidence of a fact or claim given its supporting evidence,
   * contradictory signals, and age.
   */
  public evaluateConfidence(params: {
    evidenceList: KnowledgeEvidence[];
    contradictions?: KnowledgeContradiction[];
    observedAt?: string;
    nowIso?: string;
    halfLifeDays?: number;
  }): ConfidenceEvaluationResult {
    const {
      evidenceList,
      contradictions = [],
      observedAt,
      nowIso = new Date().toISOString(),
      halfLifeDays = this.DEFAULT_HALF_LIFE_DAYS,
    } = params;

    const count = evidenceList.length;

    // RULE: 0 evidence -> UNKNOWN
    if (count === 0) {
      return {
        confidence: 'UNKNOWN',
        numericalScore: 0,
        evidenceCount: 0,
        averageEvidenceQuality: 0,
        recencyFactor: 1.0,
        consistencyFactor: 1.0,
        decayedScore: 0,
        isDecayed: false,
        explanation: 'No supporting evidence available; confidence is UNKNOWN.',
      };
    }

    // 1. Evidence Quality Calculation
    const totalWeight = evidenceList.reduce((acc, ev) => acc + (ev.weight ?? 0.5), 0);
    const avgQuality = Math.min(1.0, Math.max(0.1, totalWeight / count));

    // 2. Consistency Factor (Contradictions penalty)
    const openContradictions = contradictions.filter(
      (c) => c.resolutionStatus === 'OPEN' || c.resolutionStatus === 'UNDER_REVIEW'
    );
    let consistencyFactor = 1.0;
    if (openContradictions.length > 0) {
      const hasCritical = openContradictions.some((c) => c.severity === 'CRITICAL' || c.severity === 'HIGH');
      consistencyFactor = hasCritical ? 0.4 : 0.7;
    }

    // 3. Recency Factor
    const mostRecentDate = observedAt
      ? new Date(observedAt)
      : new Date(
          Math.max(...evidenceList.map((e) => (e.timestamp ? new Date(e.timestamp).getTime() : 0)))
        );
    const now = new Date(nowIso);
    const ageDays = Math.max(0, (now.getTime() - mostRecentDate.getTime()) / (1000 * 60 * 60 * 24));
    
    // Half-life exponential decay: R = 2^(-age / halfLife)
    const recencyFactor = Math.pow(2, -ageDays / halfLifeDays);

    // 4. Base Confidence Calculation
    // Base score combines evidence count logarithmically + quality + consistency
    // Count multiplier: count 1 -> 0.35, count 2 -> 0.55, count 3 -> 0.70, count >= 4 -> 0.85+
    const countWeight = Math.min(1.0, 0.25 * Math.log2(count + 1));
    const rawScore = countWeight * 0.45 + avgQuality * 0.35 + consistencyFactor * 0.20;

    // Apply temporal decay to yield current relevance / decayed score
    const decayedScore = rawScore * (0.6 + 0.4 * recencyFactor);
    const isDecayed = recencyFactor < 0.5;

    // STRICT INVARIANTS:
    // 1. Single observation CANNOT be HIGH. Maximum for count == 1 is LOW.
    let confidence: KnowledgeConfidence;

    if (count === 1) {
      confidence = 'LOW';
    } else if (rawScore < 0.30 || consistencyFactor < 0.5) {
      confidence = 'LOW';
    } else if (rawScore >= 0.75 && count >= 4 && consistencyFactor >= 0.9 && avgQuality >= 0.75) {
      confidence = 'HIGH';
    } else {
      confidence = 'MEDIUM';
    }

    const explanation = `Evidence count: ${count}, Avg Quality: ${avgQuality.toFixed(2)}, Consistency: ${consistencyFactor.toFixed(2)}, Recency: ${recencyFactor.toFixed(2)}. Evaluated confidence: ${confidence}.`;

    return {
      confidence,
      numericalScore: Number(rawScore.toFixed(3)),
      evidenceCount: count,
      averageEvidenceQuality: Number(avgQuality.toFixed(3)),
      recencyFactor: Number(recencyFactor.toFixed(3)),
      consistencyFactor: Number(consistencyFactor.toFixed(3)),
      decayedScore: Number(decayedScore.toFixed(3)),
      isDecayed,
      explanation,
    };
  }

  /**
   * Evaluates whether a fact is historically valid but operationally superseded or obsolete.
   */
  public evaluateTemporalValidity(fact: KnowledgeFact, nowIso = new Date().toISOString()): {
    isValid: boolean;
    validity: KnowledgeFact['validity'];
    reason: string;
  } {
    const now = new Date(nowIso);

    if (fact.supersededAt && new Date(fact.supersededAt) <= now) {
      return {
        isValid: false,
        validity: 'SUPERSEDED',
        reason: `Fact superseded at ${fact.supersededAt}.`,
      };
    }

    if (fact.validUntil && new Date(fact.validUntil) <= now) {
      return {
        isValid: false,
        validity: 'OBSOLETE',
        reason: `Fact validity period expired at ${fact.validUntil}.`,
      };
    }

    if (fact.validity === 'DISPUTED') {
      return {
        isValid: false,
        validity: 'DISPUTED',
        reason: 'Fact is under open dispute or contradictory evidence.',
      };
    }

    return {
      isValid: true,
      validity: 'ACTIVE',
      reason: 'Fact is currently active and within its valid time horizon.',
    };
  }
}

export const knowledgeConfidenceService = new KnowledgeConfidenceService();
