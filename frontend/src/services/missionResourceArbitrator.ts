/**
 * AryaOS V1 — Stage 12: Cross-Mission Resource Arbitrator
 *
 * Detects and resolves resource contention across multiple concurrent missions.
 * Reuses Stage 10 ResourceGovernor boundaries and limits; never bypasses governance.
 */

import {
  Mission,
  ResourceAllocationDecision,
} from '../types/missionControl';
import { resourceGovernor } from './resourceGovernor';
import { missionPriorityEngine } from './missionPriority';

export interface ContentionRecord {
  type:
    | 'RESOURCE_CONTENTION'
    | 'BUDGET_CONTENTION'
    | 'AGENT_CONTENTION'
    | 'PROVIDER_CONTENTION'
    | 'DEADLINE_CONTENTION';
  missionIds: string[];
  resourceName: string;
  details: string;
}

export class MissionResourceArbitrator {
  /**
   * Scans a set of concurrent active missions to detect resource, budget, or agent contention.
   */
  public detectContention(missions: Mission[]): {
    hasContention: boolean;
    contentions: ContentionRecord[];
  } {
    const active = missions.filter(
      (m) => m.status === 'RUNNING' || m.status === 'READY' || m.status === 'PLANNED'
    );
    const contentions: ContentionRecord[] = [];

    // 1. Budget Contention Check
    let totalMaxCost = 0;
    const missionBudgets: Record<string, number> = {};
    for (const m of active) {
      for (const c of m.constraints) {
        if (c.type === 'COST_BUDGET' && typeof c.value === 'number') {
          totalMaxCost += c.value;
          missionBudgets[m.missionId] = c.value;
        }
      }
    }

    // Default global budget ceiling (e.g. $10.00)
    const GLOBAL_BUDGET_LIMIT = 10.0;
    if (totalMaxCost > GLOBAL_BUDGET_LIMIT && active.length > 1) {
      contentions.push({
        type: 'BUDGET_CONTENTION',
        missionIds: Object.keys(missionBudgets),
        resourceName: 'GLOBAL_USD_BUDGET',
        details: `Aggregate concurrent missions budget ($${totalMaxCost.toFixed(2)}) exceeds global budget ceiling ($${GLOBAL_BUDGET_LIMIT.toFixed(2)}).`,
      });
    }

    // 2. Concurrency Contention Check
    let totalConcurrencyRequired = 0;
    for (const m of active) {
      const plan = m.plans[m.plans.length - 1];
      const maxParallel = plan?.goalOrder.reduce((max, layer) => Math.max(max, layer.length), 0) || 1;
      totalConcurrencyRequired += maxParallel;
    }

    const GLOBAL_CONCURRENCY_LIMIT = 5;
    if (totalConcurrencyRequired > GLOBAL_CONCURRENCY_LIMIT && active.length > 1) {
      contentions.push({
        type: 'RESOURCE_CONTENTION',
        missionIds: active.map((m) => m.missionId),
        resourceName: 'CONCURRENT_EXECUTION_SLOTS',
        details: `Total parallel goals requested (${totalConcurrencyRequired}) exceeds system concurrency capacity (${GLOBAL_CONCURRENCY_LIMIT}).`,
      });
    }

    // 3. Deadline Contention Check (conflicting imminent deadlines)
    const imminentMissions = active.filter((m) => {
      if (!m.deadline) return false;
      const remMs = new Date(m.deadline).getTime() - Date.now();
      return remMs > 0 && remMs < 3600000; // < 1 hour
    });

    if (imminentMissions.length > 1) {
      contentions.push({
        type: 'DEADLINE_CONTENTION',
        missionIds: imminentMissions.map((m) => m.missionId),
        resourceName: 'SCHEDULING_WINDOW',
        details: `${imminentMissions.length} missions have conflicting urgent deadlines within 1 hour.`,
      });
    }

    return {
      hasContention: contentions.length > 0,
      contentions,
    };
  }

  /**
   * Arbitrates a resource allocation request from a mission.
   */
  public arbitrateResourceRequest(
    missionId: string,
    requestedResource: string,
    amount: number,
    allMissions: Mission[]
  ): ResourceAllocationDecision {
    const targetMission = allMissions.find((m) => m.missionId === missionId);
    if (!targetMission) {
      return {
        missionId,
        requestedResource,
        availableResource: 0,
        decision: 'REJECTED',
        reason: `Mission '${missionId}' not found.`,
        affectedMissions: [],
        provenance: {},
      };
    }

    const priorityInfo = missionPriorityEngine.evaluatePriority(targetMission, allMissions);
    const { hasContention, contentions } = this.detectContention(allMissions);

    if (!hasContention) {
      return {
        missionId,
        requestedResource,
        availableResource: amount,
        decision: 'GRANTED',
        reason: 'Resource granted: No cross-mission contention detected.',
        affectedMissions: [],
        provenance: { priority: priorityInfo.calculatedPriority },
      };
    }

    // Resolve contention based on explicit priority
    const competingMissions = allMissions.filter(
      (m) => m.missionId !== missionId && (m.status === 'RUNNING' || m.status === 'READY')
    );

    const hasHigherPriorityCompeting = competingMissions.some((m) => {
      const p = missionPriorityEngine.evaluatePriority(m, allMissions);
      const rank = (pr: string) => (pr === 'CRITICAL' ? 4 : pr === 'HIGH' ? 3 : pr === 'NORMAL' ? 2 : 1);
      return rank(p.calculatedPriority) > rank(priorityInfo.calculatedPriority);
    });

    if (hasHigherPriorityCompeting) {
      return {
        missionId,
        requestedResource,
        availableResource: Math.max(1, Math.floor(amount * 0.5)),
        decision: 'THROTTLED',
        reason: `Resource throttled to 50% capacity due to higher priority concurrent mission contention.`,
        affectedMissions: competingMissions.map((m) => m.missionId),
        provenance: {
          assignedPriority: priorityInfo.calculatedPriority,
          contentionsDetected: contentions.length,
        },
      };
    }

    return {
      missionId,
      requestedResource,
      availableResource: amount,
      decision: 'GRANTED',
      reason: `Resource granted: Mission '${missionId}' holds superior priority in contention resolution.`,
      affectedMissions: competingMissions.map((m) => m.missionId),
      provenance: { priority: priorityInfo.calculatedPriority },
    };
  }
}

export const missionResourceArbitrator = new MissionResourceArbitrator();
