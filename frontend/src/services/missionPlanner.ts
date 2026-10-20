/**
 * AryaOS V1 — Stage 12: Mission Planner & Critical Path Engine
 *
 * Decomposes multi-goal missions into topologically sequenced execution layers,
 * computes deterministic critical paths, and evaluates cost/duration envelopes
 * using empirical evidence without silently mutating runtime policy.
 */

import {
  Mission,
  MissionExecutionPlan,
  MissionRisk,
} from '../types/missionControl';
import { missionDependencyGraph } from './missionDependencyGraph';
import { executionPersistence } from './executionPersistence';

export class MissionPlanner {
  /**
   * Generates a deterministic MissionExecutionPlan from a Mission specification.
   */
  public generatePlan(
    mission: Mission,
    planVersion?: number,
    changeReason?: string,
    previousPlan?: MissionExecutionPlan
  ): MissionExecutionPlan {
    const version = planVersion ?? (previousPlan ? previousPlan.planVersion + 1 : 1);
    const analysis = missionDependencyGraph.analyzeDependencies(
      mission.goals,
      mission.dependencies
    );

    if (!analysis.isValid) {
      throw new Error(
        `[MissionPlanner] Cannot plan mission '${mission.missionId}': Dependency graph contains validation errors: ${analysis.issues.map((i) => i.message).join('; ')}`
      );
    }

    // 1. Calculate Critical Path
    const criticalPath = this.computeCriticalPath(mission, analysis.topologicalOrder);

    // 2. Estimate Duration & Cost from Goals and Historical Evidence
    let totalEstimatedDurationMs: number | 'UNKNOWN' = 0;
    let minCostUsd: number | null = null;
    let maxCostUsd: number | null = null;
    let hasUnknownDuration = false;

    // Check historical experiences to inform duration/cost
    const experiences = executionPersistence.getExperiences();

    for (const gRef of mission.goals) {
      if (gRef.timeoutMs) {
        if (typeof totalEstimatedDurationMs === 'number') {
          totalEstimatedDurationMs += gRef.timeoutMs;
        }
      } else {
        // Look for historical duration for similar tasks
        const relevantExp = experiences.filter((e) => e.goalId === gRef.goalId);
        if (relevantExp.length > 0) {
          const avgLat =
            relevantExp.reduce((acc, e) => acc + e.latencyMs, 0) / relevantExp.length;
          if (typeof totalEstimatedDurationMs === 'number') {
            totalEstimatedDurationMs += avgLat;
          }
        } else {
          hasUnknownDuration = true;
        }
      }
    }

    if (hasUnknownDuration && totalEstimatedDurationMs === 0) {
      totalEstimatedDurationMs = 'UNKNOWN';
    }

    // Extract constraints
    for (const c of mission.constraints) {
      if (c.type === 'COST_BUDGET' && typeof c.value === 'number') {
        maxCostUsd = c.value;
        minCostUsd = c.value * 0.4;
      }
    }

    // 3. Build Initial Risk Assessment
    const riskAssessment: MissionRisk[] = [];
    if (analysis.issues.some((i) => i.type === 'DEPENDENCY_FAILURE')) {
      riskAssessment.push({
        riskId: `risk-dep-fail-${Date.now()}`,
        type: 'DEPENDENCY',
        level: 'CRITICAL',
        source: 'MissionDependencyGraph',
        evidence: analysis.issues.map((i) => i.message),
        confidence: 'HIGH',
        createdAt: new Date().toISOString(),
        mitigation: 'Replan or isolate optional failed dependencies.',
      });
    }

    if (mission.deadline) {
      const deadlineDate = new Date(mission.deadline).getTime();
      const nowDate = Date.now();
      if (deadlineDate < nowDate) {
        riskAssessment.push({
          riskId: `risk-deadline-${Date.now()}`,
          type: 'DEADLINE',
          level: 'CRITICAL',
          source: 'MissionPlanner',
          evidence: [`Deadline '${mission.deadline}' has already expired.`],
          confidence: 'HIGH',
          createdAt: new Date().toISOString(),
          mitigation: 'Request operator approval for deadline relaxation.',
        });
      }
    }

    // 4. Preserved vs Affected Goals during replanning
    const preservedGoals: string[] = [];
    const affectedGoals: string[] = [];

    if (previousPlan) {
      for (const g of mission.goals) {
        if (g.status === 'COMPLETED' || (g.status as string) === 'SUCCEEDED') {
          preservedGoals.push(g.goalId);
        } else {
          affectedGoals.push(g.goalId);
        }
      }
    } else {
      affectedGoals.push(...mission.goals.map((g) => g.goalId));
    }

    const assumptions: string[] = [
      'Stage 07 Execution Gateway remains the single provider execution boundary.',
      'Completed goals are immutable and will not be re-executed during replanning.',
      'Resource allocations are bounded by Stage 10 Resource Governor limits.',
    ];

    const evidence: string[] = [
      `Topological layering produced ${analysis.parallelGroups.length} parallel group(s).`,
      `Critical path contains ${criticalPath.length} goal(s).`,
    ];

    return {
      missionId: mission.missionId,
      planVersion: version,
      goalOrder: analysis.parallelGroups,
      criticalPath,
      estimatedCost: {
        minUsd: minCostUsd,
        maxUsd: maxCostUsd,
        currency: 'USD',
      },
      estimatedDurationMs: totalEstimatedDurationMs,
      riskAssessment,
      assumptions,
      evidence,
      confidence: 'HIGH',
      createdAt: new Date().toISOString(),
      previousPlanVersion: previousPlan ? previousPlan.planVersion : undefined,
      changeReason,
      preservedGoals,
      affectedGoals,
    };
  }

  /**
   * Deterministically calculates the longest dependency chain (critical path).
   */
  public computeCriticalPath(
    mission: Mission,
    topologicalOrder: string[]
  ): string[] {
    if (topologicalOrder.length === 0) return [];

    const adj: Record<string, string[]> = {};
    for (const g of mission.goals) {
      adj[g.goalId] = [];
    }
    for (const dep of mission.dependencies) {
      if (adj[dep.fromGoalId]) {
        adj[dep.fromGoalId].push(dep.toGoalId);
      }
    }

    // Find path with maximum hops
    const distances: Record<string, number> = {};
    const predecessors: Record<string, string | null> = {};

    for (const node of topologicalOrder) {
      distances[node] = 1;
      predecessors[node] = null;
    }

    let maxDist = 0;
    let endNode = topologicalOrder[0];

    for (const u of topologicalOrder) {
      const distU = distances[u] || 1;
      for (const v of adj[u] || []) {
        if ((distances[v] || 0) < distU + 1) {
          distances[v] = distU + 1;
          predecessors[v] = u;
          if (distances[v] > maxDist) {
            maxDist = distances[v];
            endNode = v;
          }
        }
      }
    }

    // Reconstruct path
    const path: string[] = [];
    let curr: string | null = endNode;
    while (curr) {
      path.unshift(curr);
      curr = predecessors[curr];
    }

    return path;
  }
}

export const missionPlanner = new MissionPlanner();
