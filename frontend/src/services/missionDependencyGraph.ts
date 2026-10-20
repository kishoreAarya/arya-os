/**
 * AryaOS V1 — Stage 12: Mission Dependency Graph
 *
 * Deterministic Directed Acyclic Graph (DAG) validation and dependency analysis
 * for multi-goal missions. Detects cycles, missing references, and blocked frontiers.
 */

import {
  MissionGoalReference,
  MissionDependency,
} from '../types/missionControl';

export type DependencyValidationErrorType =
  | 'CIRCULAR_DEPENDENCY'
  | 'MISSING_GOAL'
  | 'DUPLICATE_DEPENDENCY'
  | 'INVALID_REFERENCE'
  | 'DEPENDENCY_FAILURE'
  | 'BLOCKED_DEPENDENCY';

export interface DependencyValidationIssue {
  type: DependencyValidationErrorType;
  fromGoalId: string;
  toGoalId: string;
  message: string;
}

export interface DependencyGraphAnalysis {
  isValid: boolean;
  issues: DependencyValidationIssue[];
  topologicalOrder: string[];
  parallelGroups: string[][];
  executableFrontier: string[];
  blockedGoals: string[];
  failedGoals: string[];
}

export class MissionDependencyGraph {
  /**
   * Validates the dependency graph and returns full structural analysis.
   */
  public analyzeDependencies(
    goals: MissionGoalReference[],
    dependencies: MissionDependency[]
  ): DependencyGraphAnalysis {
    const issues: DependencyValidationIssue[] = [];
    const goalMap = new Map<string, MissionGoalReference>();
    for (const g of goals) {
      goalMap.set(g.goalId, g);
    }

    // 1. Check for Invalid References, Missing Goals, and Duplicates
    const seenEdges = new Set<string>();
    for (const dep of dependencies) {
      if (dep.fromGoalId === dep.toGoalId) {
        issues.push({
          type: 'INVALID_REFERENCE',
          fromGoalId: dep.fromGoalId,
          toGoalId: dep.toGoalId,
          message: `Goal '${dep.fromGoalId}' cannot depend on itself.`,
        });
      }

      if (!goalMap.has(dep.fromGoalId)) {
        issues.push({
          type: 'MISSING_GOAL',
          fromGoalId: dep.fromGoalId,
          toGoalId: dep.toGoalId,
          message: `Dependency origin goal '${dep.fromGoalId}' does not exist in mission.`,
        });
      }

      if (!goalMap.has(dep.toGoalId)) {
        issues.push({
          type: 'MISSING_GOAL',
          fromGoalId: dep.fromGoalId,
          toGoalId: dep.toGoalId,
          message: `Dependency target goal '${dep.toGoalId}' does not exist in mission.`,
        });
      }

      const edgeKey = `${dep.fromGoalId}->${dep.toGoalId}`;
      if (seenEdges.has(edgeKey)) {
        issues.push({
          type: 'DUPLICATE_DEPENDENCY',
          fromGoalId: dep.fromGoalId,
          toGoalId: dep.toGoalId,
          message: `Duplicate dependency detected between '${dep.fromGoalId}' and '${dep.toGoalId}'.`,
        });
      }
      seenEdges.add(edgeKey);
    }

    // 2. Build Adjacency List for Topological Sort & Cycle Detection
    // Dependency: fromGoalId must complete BEFORE toGoalId can run.
    // Edge: fromGoalId -> toGoalId
    const inDegree: Record<string, number> = {};
    const adj: Record<string, string[]> = {};
    const parents: Record<string, string[]> = {};

    for (const g of goals) {
      inDegree[g.goalId] = 0;
      adj[g.goalId] = [];
      parents[g.goalId] = [];
    }

    for (const dep of dependencies) {
      if (goalMap.has(dep.fromGoalId) && goalMap.has(dep.toGoalId) && dep.fromGoalId !== dep.toGoalId) {
        adj[dep.fromGoalId].push(dep.toGoalId);
        parents[dep.toGoalId].push(dep.fromGoalId);
        inDegree[dep.toGoalId] = (inDegree[dep.toGoalId] || 0) + 1;
      }
    }

    // Kahn's Algorithm for Topological Sort & Layering
    const queue: string[] = [];
    for (const [id, deg] of Object.entries(inDegree)) {
      if (deg === 0) queue.push(id);
    }

    const topologicalOrder: string[] = [];
    const parallelGroups: string[][] = [];

    let currentLayer = [...queue];
    while (currentLayer.length > 0) {
      parallelGroups.push(currentLayer);
      const nextLayer: string[] = [];

      for (const node of currentLayer) {
        topologicalOrder.push(node);
        for (const neighbor of adj[node] || []) {
          inDegree[neighbor]--;
          if (inDegree[neighbor] === 0) {
            nextLayer.push(neighbor);
          }
        }
      }
      currentLayer = nextLayer;
    }

    // Check for circular dependency
    if (topologicalOrder.length < goals.length) {
      // Find nodes stuck in inDegree > 0
      const cycleNodes = goals
        .filter((g) => !topologicalOrder.includes(g.goalId))
        .map((g) => g.goalId);

      issues.push({
        type: 'CIRCULAR_DEPENDENCY',
        fromGoalId: cycleNodes[0] || 'CYCLE',
        toGoalId: cycleNodes[cycleNodes.length - 1] || 'CYCLE',
        message: `Circular dependency detected involving goals: ${cycleNodes.join(', ')}`,
      });
    }

    // 3. Determine Executable Frontier & Blocked / Failed States
    const executableFrontier: string[] = [];
    const blockedGoals: string[] = [];
    const failedGoals: string[] = [];

    for (const g of goals) {
      if (g.status === 'COMPLETED' || (g.status as string) === 'SUCCEEDED') {
        continue;
      }
      if (g.status === 'FAILED') {
        failedGoals.push(g.goalId);
        continue;
      }

      // Check all upstream parent goals
      const upstreamParents = parents[g.goalId] || [];
      let isBlocked = false;
      let hasFailedParent = false;

      for (const pId of upstreamParents) {
        const parent = goalMap.get(pId);
        if (!parent || (parent.status !== 'COMPLETED' && (parent.status as string) !== 'SUCCEEDED')) {
          isBlocked = true;
        }
        if (parent && parent.status === 'FAILED' && parent.mandatory) {
          hasFailedParent = true;
        }
      }

      if (hasFailedParent) {
        issues.push({
          type: 'DEPENDENCY_FAILURE',
          fromGoalId: g.goalId,
          toGoalId: g.goalId,
          message: `Goal '${g.goalId}' cannot execute because mandatory upstream dependency failed.`,
        });
        blockedGoals.push(g.goalId);
      } else if (isBlocked) {
        blockedGoals.push(g.goalId);
      } else {
        executableFrontier.push(g.goalId);
      }
    }

    return {
      isValid: issues.filter((i) => i.type === 'CIRCULAR_DEPENDENCY' || i.type === 'MISSING_GOAL' || i.type === 'INVALID_REFERENCE').length === 0,
      issues,
      topologicalOrder,
      parallelGroups,
      executableFrontier,
      blockedGoals,
      failedGoals,
    };
  }
}

export const missionDependencyGraph = new MissionDependencyGraph();
