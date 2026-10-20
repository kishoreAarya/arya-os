/**
 * AryaOS V1 — Stage 22: Audit Evidence Service
 *
 * Models and verifies evidence provenance and epistemic certainty levels.
 * Enforces strict anti-upgrade rules:
 * - INFERRED != CONFIRMED
 * - PROJECTED != OBSERVED
 * - UNKNOWN cannot transition to SUCCEEDED without fresh authoritative evidence.
 */

import { EpistemicStatus } from '../types/operationalAudit';

export interface EvidenceRecord {
  evidenceId: string;
  sourceType: 'EXTERNAL_WEBHOOK' | 'CONNECTOR_OBSERVATION' | 'ACTION_RESULT' | 'USER_ASSERTION' | 'INFERRED_LOGIC';
  sourceId: string;
  timestamp: number;
  epistemicLevel: EpistemicStatus;
  isCryptographicallyVerified: boolean;
  fingerprint: string;
  metadata?: Record<string, unknown>;
}

export class AuditEvidenceService {
  private evidenceStore: Map<string, EvidenceRecord> = new Map();

  /**
   * Resets evidence store (for testing).
   */
  public reset(): void {
    this.evidenceStore.clear();
  }

  /**
   * Registers an evidence item into the store.
   */
  public recordEvidence(evidence: EvidenceRecord): void {
    this.evidenceStore.set(evidence.evidenceId, Object.freeze({ ...evidence }));
  }

  /**
   * Retrieves an evidence record by ID.
   */
  public getEvidence(evidenceId: string): EvidenceRecord | undefined {
    return this.evidenceStore.get(evidenceId);
  }

  /**
   * Validates if an epistemic promotion from currentLevel to newLevel is justified by evidence.
   */
  public validateEpistemicTransition(params: {
    currentLevel: EpistemicStatus;
    targetLevel: EpistemicStatus;
    supportingEvidenceIds: string[];
  }): { valid: boolean; reason?: string } {
    if (params.currentLevel === params.targetLevel) {
      return { valid: true };
    }

    // Rank of epistemic strength: UNKNOWN (0) < PROJECTED (1) < INFERRED (2) < OBSERVED (3) < CONFIRMED (4)
    const rank: Record<EpistemicStatus, number> = {
      UNKNOWN: 0,
      PROJECTED: 1,
      INFERRED: 2,
      OBSERVED: 3,
      CONFIRMED: 4,
    };

    const currentRank = rank[params.currentLevel];
    const targetRank = rank[params.targetLevel];

    // Downward revisions or lateral transitions are always allowed (e.g. realizing a state is UNKNOWN)
    if (targetRank <= currentRank) {
      return { valid: true };
    }

    // Upward promotion requires non-empty verified evidence
    if (!params.supportingEvidenceIds || params.supportingEvidenceIds.length === 0) {
      return {
        valid: false,
        reason: `Anti-Upgrade Violation: Cannot promote epistemic status from '${params.currentLevel}' to '${params.targetLevel}' without supporting evidence.`,
      };
    }

    // Verifying supporting evidence exists in evidence store
    const verifiedEvidence = params.supportingEvidenceIds
      .map((id) => this.evidenceStore.get(id))
      .filter(Boolean) as EvidenceRecord[];

    if (verifiedEvidence.length === 0) {
      return {
        valid: false,
        reason: `Anti-Upgrade Violation: None of the supplied evidence IDs exist in the verified evidence store.`,
      };
    }

    // To promote to OBSERVED or CONFIRMED, evidence must be cryptographically verified or from authoritative observation
    if (params.targetLevel === 'CONFIRMED' || params.targetLevel === 'OBSERVED') {
      const hasAuthoritative = verifiedEvidence.some(
        (e) =>
          e.epistemicLevel === 'OBSERVED' ||
          e.epistemicLevel === 'CONFIRMED' ||
          e.isCryptographicallyVerified
      );
      if (!hasAuthoritative) {
        return {
          valid: false,
          reason: `Anti-Upgrade Violation: Promotion to '${params.targetLevel}' requires at least one cryptographically verified or authoritative observation evidence record.`,
        };
      }
    }

    return { valid: true };
  }
}

export const auditEvidenceService = new AuditEvidenceService();
