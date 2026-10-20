/**
 * AryaOS V1 — Stage 19: Trigger Risk Classification Service
 *
 * Computes deterministic, objective risk levels for reaction proposals based on
 * reaction semantics, target capabilities, and operation parameters.
 *
 * CRITICAL INVARIANT:
 * A trigger cannot declare a low risk level to bypass governance.
 * Risk is intrinsically derived from the reaction semantics and capability registry.
 */

import {
  TriggerReaction,
  TriggerRiskLevel,
  TriggerActionIntent,
} from '../types/eventTrigger';
import { capabilityRegistry } from './capabilityRegistry';

export class TriggerRiskService {
  /**
   * Classifies the intrinsic risk of a proposed reaction.
   */
  public classifyRisk(reaction: TriggerReaction): TriggerRiskLevel {
    // 1. Semantic reaction type baseline
    switch (reaction.reactionType) {
      case 'CREATE_OBSERVATION':
      case 'REQUEST_RESEARCH':
      case 'REQUEST_ANALYSIS':
      case 'REQUEST_HUMAN_APPROVAL':
        return 'LOW';

      case 'CREATE_GOAL':
      case 'UPDATE_MISSION':
        return 'MEDIUM';

      case 'REPLAN_MISSION':
      case 'PAUSE_MISSION':
        return 'HIGH';

      case 'EXTERNAL_ACTION':
        return this.classifyActionIntentRisk(reaction.actionIntent);

      default:
        return 'HIGH';
    }
  }

  /**
   * Computes risk level for external capability actions.
   */
  public classifyActionIntentRisk(actionIntent?: TriggerActionIntent): TriggerRiskLevel {
    if (!actionIntent) {
      return 'MEDIUM';
    }

    if (actionIntent.requiredRisk === 'CRITICAL') {
      return 'CRITICAL';
    }
    if (actionIntent.requiredRisk === 'HIGH') {
      return 'HIGH';
    }

    const { capabilityId, operation, parameters } = actionIntent;

    // Critical operations: spending, permission changes, credential alterations, deletions
    const opLower = (operation || '').toLowerCase();
    const isDestructive =
      opLower.includes('delete') ||
      opLower.includes('destroy') ||
      opLower.includes('revoke') ||
      opLower.includes('purge') ||
      opLower.includes('drop');

    const isFinancialOrPrivilege =
      opLower.includes('spend') ||
      opLower.includes('pay') ||
      opLower.includes('transfer') ||
      opLower.includes('grant') ||
      opLower.includes('promote');

    if (isDestructive || isFinancialOrPrivilege) {
      return 'CRITICAL';
    }

    // Check capability registry declared risk
    const cap = capabilityRegistry.getCapability(capabilityId);
    if (cap) {
      if (cap.riskLevel === 'CRITICAL') return 'CRITICAL';
      if (cap.riskLevel === 'HIGH') return 'HIGH';
    }

    // Write operations are at minimum HIGH risk
    const isWrite =
      opLower.includes('write') ||
      opLower.includes('create') ||
      opLower.includes('update') ||
      opLower.includes('post') ||
      opLower.includes('put') ||
      opLower.includes('patch');

    if (isWrite) {
      return 'HIGH';
    }

    return cap ? cap.riskLevel : 'MEDIUM';
  }

  /**
   * Resolves effective risk, ensuring declared risk never downgrades intrinsic risk.
   */
  public resolveEffectiveRisk(
    declaredRisk: TriggerRiskLevel,
    reaction: TriggerReaction
  ): TriggerRiskLevel {
    const intrinsic = this.classifyRisk(reaction);
    const riskRanks: Record<TriggerRiskLevel, number> = {
      LOW: 1,
      MEDIUM: 2,
      HIGH: 3,
      CRITICAL: 4,
    };

    // The effective risk is the maximum of declared and intrinsic risk
    return riskRanks[intrinsic] >= riskRanks[declaredRisk] ? intrinsic : declaredRisk;
  }

  public calculateReactionRisk(reaction: TriggerReaction): TriggerRiskLevel {
    return this.classifyRisk(reaction);
  }

  public elevateRisk(
    declaredRisk: TriggerRiskLevel,
    reaction: TriggerReaction
  ): TriggerRiskLevel {
    return this.resolveEffectiveRisk(declaredRisk, reaction);
  }

  public requiresHumanApproval(
    effectiveRisk: TriggerRiskLevel,
    reaction?: TriggerReaction
  ): boolean {
    return effectiveRisk === 'HIGH' || effectiveRisk === 'CRITICAL' || reaction?.reactionType === 'PAUSE_MISSION';
  }
}

export const triggerRiskService = new TriggerRiskService();
