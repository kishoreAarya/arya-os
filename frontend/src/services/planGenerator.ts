/**
 * AryaOS V1 — Stage 08: Plan Generator & Action Graph Constructor
 *
 * Generates dependency-aware Action Graphs (DAGs) from high-level goals.
 * Computes topological concurrency layers, enforces capability requirements,
 * estimates cost/latency envelopes, and supports plan versioning.
 */

import {
  Goal,
  Plan,
  ActionNode,
  ActionStatus,
  ActionRiskLevel,
} from '../types/goalOrchestration';
import { providerRegistry } from './providerRegistry';

export class PlanGenerator {
  /**
   * Generates initial Plan v1 for a goal.
   */
  public generatePlan(goal: Goal): Plan {
    const planId = `PLAN-${goal.goalId}-V1`;
    const actions = this.decomposeGoalIntoActionGraph(goal, planId, 1);
    const dependencies = this.extractDependencyMap(actions);
    const executionOrder = this.computeTopologicalLayers(actions, dependencies);
    const { estimatedCost, estimatedLatencyMs } = this.estimatePlanMetrics(actions);

    const requiredApprovals = actions
      .filter((a) => a.approvalRequirement.required)
      .map((a) => a.actionId);

    const highestRisk: ActionRiskLevel = actions.some(
      (a) => a.approvalRequirement.riskLevel === 'EXTERNAL_SIDE_EFFECT'
    )
      ? 'EXTERNAL_SIDE_EFFECT'
      : actions.some((a) => a.approvalRequirement.riskLevel === 'CONSEQUENTIAL')
      ? 'CONSEQUENTIAL'
      : actions.some((a) => a.approvalRequirement.riskLevel === 'LOW_RISK')
      ? 'LOW_RISK'
      : 'READ_ONLY';

    const plan: Plan = {
      planId,
      goalId: goal.goalId,
      version: 1,
      actions,
      dependencies,
      executionOrder,
      estimatedCost,
      estimatedLatencyMs,
      riskLevel: highestRisk,
      requiredApprovals,
      completionCriteria: goal.completionCriteria,
      status: 'ACTIVE',
      createdAt: new Date().toISOString(),
    };

    return plan;
  }

  /**
   * Generates a new plan version (e.g. Plan v2) during replanning,
   * preserving already-succeeded nodes and replanning around failed/dependent nodes.
   */
  public generateReplan(
    goal: Goal,
    currentPlan: Plan,
    failedActionId: string,
    replanReason: string
  ): Plan {
    const newVersion = currentPlan.version + 1;
    const planId = `PLAN-${goal.goalId}-V${newVersion}`;

    // 1. Preserve succeeded nodes exactly as they were
    const preservedActions: ActionNode[] = [];
    for (const action of currentPlan.actions) {
      if (action.status === 'SUCCEEDED') {
        preservedActions.push({
          ...action,
          planId, // update plan reference
        });
      }
    }

    // 2. Identify nodes that need replanning: the failed node + downstream dependents
    const failedNode = currentPlan.actions.find((a) => a.actionId === failedActionId);
    const downstreamIds = this.getDownstreamActionIds(currentPlan, failedActionId);

    // Create a modified replacement for the failed node (e.g., using alternative model or adjusted prompt)
    const replacementActionId = `ACT-${goal.goalId}-R${newVersion}-1`;
    const replacementNode: ActionNode = {
      actionId: replacementActionId,
      goalId: goal.goalId,
      planId,
      title: `${failedNode?.title || 'Recovered Action'} (Replanned)`,
      type: failedNode?.type || 'RESEARCH',
      description: `Replanned execution: ${replanReason}`,
      inputs: {
        ...(failedNode?.inputs || {}),
        replanAttempt: newVersion,
        originalFailure: replanReason,
      },
      dependencies: failedNode?.dependencies || [],
      requiredCapability: failedNode?.requiredCapability || 'RESEARCH',
      status: 'READY',
      retryPolicy: { maxRetries: 1, backoffMs: 1000, retriesAttempted: 0 },
      approvalRequirement: failedNode?.approvalRequirement || {
        required: false,
        riskLevel: 'READ_ONLY',
      },
      completionCriteria: failedNode?.completionCriteria || ['Recovered execution successfully completed.'],
      provenance: {
        originalActionId: failedActionId,
        replanReason,
        version: newVersion,
      },
    };

    // Adapt downstream dependent nodes to depend on replacementActionId instead of failedActionId
    const adaptedDownstream: ActionNode[] = [];
    for (const action of currentPlan.actions) {
      if (downstreamIds.includes(action.actionId) && action.actionId !== failedActionId) {
        const updatedDeps = action.dependencies.map((dep) =>
          dep === failedActionId ? replacementActionId : dep
        );
        adaptedDownstream.push({
          ...action,
          planId,
          dependencies: updatedDeps,
          status: 'WAITING_DEPENDENCY',
        });
      }
    }

    const allNewActions = [...preservedActions, replacementNode, ...adaptedDownstream];
    const dependencies = this.extractDependencyMap(allNewActions);
    const executionOrder = this.computeTopologicalLayers(allNewActions, dependencies);
    const { estimatedCost, estimatedLatencyMs } = this.estimatePlanMetrics(allNewActions);

    const plan: Plan = {
      planId,
      goalId: goal.goalId,
      version: newVersion,
      actions: allNewActions,
      dependencies,
      executionOrder,
      estimatedCost,
      estimatedLatencyMs,
      riskLevel: currentPlan.riskLevel,
      requiredApprovals: allNewActions
        .filter((a) => a.approvalRequirement.required)
        .map((a) => a.actionId),
      completionCriteria: goal.completionCriteria,
      status: 'ACTIVE',
      createdAt: new Date().toISOString(),
      replanReason,
    };

    return plan;
  }

  /**
   * Decomposes user goal into a dependency-aware Action Graph.
   */
  private decomposeGoalIntoActionGraph(
    goal: Goal,
    planId: string,
    version: number
  ): ActionNode[] {
    const actions: ActionNode[] = [];
    const lower = goal.userIntent.toLowerCase();

    // Pattern 1: Research & Production Brief
    if (lower.includes('production brief') || lower.includes('brief') || lower.includes('concept')) {
      const act1Id = `ACT-${goal.goalId}-V${version}-1`;
      const act2Id = `ACT-${goal.goalId}-V${version}-2`;
      const act3Id = `ACT-${goal.goalId}-V${version}-3`;

      // Node 1: Architectural Research (Independent / Ready)
      actions.push({
        actionId: act1Id,
        goalId: goal.goalId,
        planId,
        title: 'Architectural Research & Context Extraction',
        type: 'RESEARCH',
        description: `Analyze spatial memory archive and extract precedents for ${goal.objective}`,
        inputs: {
          userInput: goal.userIntent,
          contextMemories: goal.contextRequirements.contextMemories,
          targetMemoryId: goal.contextRequirements.targetMemoryId,
        },
        dependencies: [],
        requiredCapability: 'RESEARCH',
        status: 'READY',
        retryPolicy: { maxRetries: 2, backoffMs: 1000, retriesAttempted: 0 },
        approvalRequirement: { required: false, riskLevel: 'READ_ONLY' },
        completionCriteria: [
          'Memory context researched and structured summary produced',
          'Zero sensitive tokens leaked',
        ],
        provenance: { goalId: goal.goalId, nodeIndex: 1 },
      });

      // Node 2: Concept Synthesis (Depends on Node 1)
      actions.push({
        actionId: act2Id,
        goalId: goal.goalId,
        planId,
        title: 'Concept Synthesis & Decision Framing',
        type: 'REASONING',
        description: 'Synthesize research findings into cinematic creative concept framework',
        inputs: {
          parentAction: act1Id,
          constraints: goal.constraints,
        },
        dependencies: [act1Id],
        requiredCapability: 'REASONING',
        status: 'WAITING_DEPENDENCY',
        retryPolicy: { maxRetries: 2, backoffMs: 1000, retriesAttempted: 0 },
        approvalRequirement: { required: false, riskLevel: 'LOW_RISK' },
        completionCriteria: [
          'Concept narrative formulated with continuity to Stage 03 architecture',
        ],
        provenance: { goalId: goal.goalId, nodeIndex: 2 },
      });

      // Node 3: Production Brief Generation (Depends on Node 2, Requires Approval)
      actions.push({
        actionId: act3Id,
        goalId: goal.goalId,
        planId,
        title: 'Production Brief & Milestone Compilation',
        type: 'STRUCTURED_EXTRACTION',
        description: 'Generate formal production execution brief and job package specifications',
        inputs: {
          parentAction: act2Id,
          objective: goal.objective,
        },
        dependencies: [act2Id],
        requiredCapability: 'STRUCTURED_EXTRACTION',
        status: 'WAITING_DEPENDENCY',
        retryPolicy: { maxRetries: 1, backoffMs: 1000, retriesAttempted: 0 },
        approvalRequirement: {
          required: goal.approvalPolicy.requireApprovalForConsequential,
          riskLevel: 'CONSEQUENTIAL',
        },
        completionCriteria: [
          'Production brief compiled with milestones and job package envelope',
        ],
        provenance: { goalId: goal.goalId, nodeIndex: 3 },
      });

      return actions;
    }

    // Pattern 2: Multi-branch Concurrent Research & Synthesis
    const actBranchA = `ACT-${goal.goalId}-V${version}-1A`;
    const actBranchB = `ACT-${goal.goalId}-V${version}-1B`;
    const actMerge = `ACT-${goal.goalId}-V${version}-2`;

    // Branch A: Character/System Research
    actions.push({
      actionId: actBranchA,
      goalId: goal.goalId,
      planId,
      title: 'Domain Research (Branch A: System Capabilities)',
      type: 'RESEARCH',
      description: 'Analyze core systems and capabilities',
      inputs: { target: 'SYSTEM_CAPABILITIES' },
      dependencies: [],
      requiredCapability: 'RESEARCH',
      status: 'READY',
      retryPolicy: { maxRetries: 2, backoffMs: 1000, retriesAttempted: 0 },
      approvalRequirement: { required: false, riskLevel: 'READ_ONLY' },
      completionCriteria: ['Capabilities verified'],
      provenance: { branch: 'A' },
    });

    // Branch B: Environmental Context Research
    actions.push({
      actionId: actBranchB,
      goalId: goal.goalId,
      planId,
      title: 'Domain Research (Branch B: Spatial Memory Context)',
      type: 'RESEARCH',
      description: 'Analyze spatial vitrine relationships',
      inputs: { target: 'SPATIAL_RELATIONSHIPS' },
      dependencies: [],
      requiredCapability: 'RESEARCH',
      status: 'READY',
      retryPolicy: { maxRetries: 2, backoffMs: 1000, retriesAttempted: 0 },
      approvalRequirement: { required: false, riskLevel: 'READ_ONLY' },
      completionCriteria: ['Memory relationships mapped'],
      provenance: { branch: 'B' },
    });

    // Merge Node: Synthesis (Depends on BOTH 1A and 1B)
    actions.push({
      actionId: actMerge,
      goalId: goal.goalId,
      planId,
      title: 'Synthesized Architectural Brief',
      type: 'REASONING',
      description: 'Unify concurrent research branches into cohesive synthesis',
      inputs: { parents: [actBranchA, actBranchB] },
      dependencies: [actBranchA, actBranchB],
      requiredCapability: 'REASONING',
      status: 'WAITING_DEPENDENCY',
      retryPolicy: { maxRetries: 1, backoffMs: 1000, retriesAttempted: 0 },
      approvalRequirement: { required: false, riskLevel: 'LOW_RISK' },
      completionCriteria: ['Dual-branch synthesis achieved'],
      provenance: { branch: 'MERGE' },
    });

    return actions;
  }

  /**
   * Builds map of actionId -> prerequisites.
   */
  private extractDependencyMap(actions: ActionNode[]): Record<string, string[]> {
    const map: Record<string, string[]> = {};
    for (const act of actions) {
      map[act.actionId] = act.dependencies;
    }
    return map;
  }

  /**
   * Computes topological layers (Kahn's algorithm) for concurrency.
   */
  public computeTopologicalLayers(
    actions: ActionNode[],
    dependencies: Record<string, string[]>
  ): string[][] {
    const layers: string[][] = [];
    const remaining = new Set(actions.map((a) => a.actionId));
    const satisfied = new Set<string>();

    while (remaining.size > 0) {
      const currentLayer: string[] = [];

      for (const actionId of remaining) {
        const deps = dependencies[actionId] || [];
        const allDepsSatisfied = deps.every((d) => satisfied.has(d));
        if (allDepsSatisfied) {
          currentLayer.push(actionId);
        }
      }

      if (currentLayer.length === 0) {
        // Cycle detected or unresolvable dependencies - break out safely
        layers.push(Array.from(remaining));
        break;
      }

      for (const id of currentLayer) {
        remaining.delete(id);
        satisfied.add(id);
      }

      layers.push(currentLayer);
    }

    return layers;
  }

  /**
   * Finds all transitive downstream dependents of an action ID.
   */
  private getDownstreamActionIds(plan: Plan, targetActionId: string): string[] {
    const dependents = new Set<string>();
    const queue = [targetActionId];

    while (queue.length > 0) {
      const current = queue.shift()!;
      for (const action of plan.actions) {
        if (action.dependencies.includes(current) && !dependents.has(action.actionId)) {
          dependents.add(action.actionId);
          queue.push(action.actionId);
        }
      }
    }

    return Array.from(dependents);
  }

  /**
   * Estimates cost and latency envelopes across the action graph.
   */
  private estimatePlanMetrics(
    actions: ActionNode[]
  ): {
    estimatedCost: { minUsd: number | null; maxUsd: number | null; currency: 'USD' };
    estimatedLatencyMs: number;
  } {
    let minCost = 0;
    let maxCost = 0;
    let totalLatency = 0;

    for (const action of actions) {
      const providers = providerRegistry.getProvidersForCapability(action.requiredCapability);
      const cheapest = providers[0];
      const priciest = providers[providers.length - 1];

      if (cheapest?.costProfile.perUnitCostUsd) {
        minCost += cheapest.costProfile.perUnitCostUsd;
      } else {
        minCost += 0.0002;
      }

      if (priciest?.costProfile.perUnitCostUsd) {
        maxCost += priciest.costProfile.perUnitCostUsd;
      } else {
        maxCost += 0.0015;
      }

      totalLatency += (cheapest?.latencyProfile.averageSeconds || 3) * 1000;
    }

    return {
      estimatedCost: {
        minUsd: Number(minCost.toFixed(4)),
        maxUsd: Number(maxCost.toFixed(4)),
        currency: 'USD',
      },
      estimatedLatencyMs: totalLatency,
    };
  }
}

export const planGenerator = new PlanGenerator();
