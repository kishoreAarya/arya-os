/**
 * AryaOS V1 — Stage 11: Plan Evaluation Service
 *
 * Comparative plan evaluation (e.g. Plan v1 vs Plan v2) and structured self-critique.
 * Explicitly distinguishes empirically grounded known improvements from speculative hypotheses,
 * preserving immutable safety constraints ('mustNotChange').
 */

import { PlanEvaluation, SelfCritique } from '../types/agentEvaluation';
import { Goal, Plan } from '../types/goalOrchestration';
import { executionPersistence } from './executionPersistence';

export interface PlanComparisonResult {
  winner: 'PLAN_A' | 'PLAN_B' | 'TIE';
  efficiencyDiff: number | 'UNKNOWN';
  latencyDiffMs: number;
  successRateDiff: number;
  rationale: string;
  comparisonSummary: string;
}

export class PlanEvaluationService {
  /**
   * Evaluates a plan's execution outcome from the Goal and stored experiences.
   */
  public evaluatePlan(goal: Goal, planVersion?: number): PlanEvaluation {
    const version = planVersion ?? goal.currentPlanVersion;
    const plan = goal.plans.find((p) => p.version === version) || goal.plans[0];

    const planId = plan ? plan.planId : goal.currentPlanId || 'unknown-plan';
    const actionCount = plan ? plan.actions.length : 0;

    let actionsSucceeded = 0;
    let actionsFailed = 0;
    let actualLatencyMs = 0;
    let recoveryEventsCount = 0;

    // Check action nodes in the plan
    if (plan) {
      for (const act of plan.actions) {
        if (act.status === 'SUCCEEDED') actionsSucceeded++;
        else if (act.status === 'FAILED') actionsFailed++;

        if (act.retryPolicy.retriesAttempted > 0) {
          recoveryEventsCount += act.retryPolicy.retriesAttempted;
        }
      }
    }

    // Check stored experiences for additional execution telemetry
    const experiences = executionPersistence.getExperiences({ goalId: goal.goalId });
    const planExperiences = experiences.filter((e) => e.planVersion === version);

    for (const exp of planExperiences) {
      actualLatencyMs += exp.latencyMs;
      if (exp.evaluation.reliability.fallbackUsed) {
        recoveryEventsCount++;
      }
    }

    const plannedLatencyMs = plan ? plan.estimatedLatencyMs : 5000;
    const plannedCostUsd = plan?.estimatedCost.maxUsd ?? null;
    const replanTriggered = goal.plans.length > 1 && version < goal.currentPlanVersion;

    // Calculate efficiency score (0..1.0)
    let overallEfficiencyScore: number | 'UNKNOWN' = 'UNKNOWN';
    if (actionCount > 0) {
      const successRate = actionsSucceeded / actionCount;
      const latencyEfficiency =
        actualLatencyMs <= plannedLatencyMs
          ? 1.0
          : Math.max(0, 1 - (actualLatencyMs - plannedLatencyMs) / plannedLatencyMs);
      const recoveryPenalty = Math.max(0, 1 - recoveryEventsCount * 0.15);

      const rawEfficiency = successRate * 0.5 + latencyEfficiency * 0.3 + recoveryPenalty * 0.2;
      overallEfficiencyScore = Number(rawEfficiency.toFixed(2));
    }

    const qualitySummary =
      actionsFailed === 0
        ? `Plan v${version} completed successfully with ${actionsSucceeded}/${actionCount} actions verified.`
        : `Plan v${version} experienced ${actionsFailed} failures across ${actionCount} total actions.`;

    const planEval: PlanEvaluation = {
      planEvaluationId: `peval-${goal.goalId}-v${version}-${Date.now()}`,
      goalId: goal.goalId,
      planId,
      planVersion: version,
      plannedCostUsd,
      actualCostUsd: 'UNKNOWN',
      plannedLatencyMs,
      actualLatencyMs,
      actionCount,
      actionsSucceeded,
      actionsFailed,
      recoveryEventsCount,
      replanTriggered,
      qualitySummary,
      overallEfficiencyScore,
      completedAt: new Date().toISOString(),
    };

    executionPersistence.savePlanEvaluation(planEval);
    return planEval;
  }

  /**
   * Compares two PlanEvaluations (e.g. Plan v1 vs Plan v2)
   */
  public comparePlans(planA: PlanEvaluation, planB: PlanEvaluation): PlanComparisonResult {
    const successRateA = planA.actionCount > 0 ? planA.actionsSucceeded / planA.actionCount : 0;
    const successRateB = planB.actionCount > 0 ? planB.actionsSucceeded / planB.actionCount : 0;

    const effA = typeof planA.overallEfficiencyScore === 'number' ? planA.overallEfficiencyScore : 0;
    const effB = typeof planB.overallEfficiencyScore === 'number' ? planB.overallEfficiencyScore : 0;

    const latencyDiff = planB.actualLatencyMs - planA.actualLatencyMs;
    const successRateDiff = Number((successRateB - successRateA).toFixed(2));
    const efficiencyDiff =
      typeof planA.overallEfficiencyScore === 'number' &&
      typeof planB.overallEfficiencyScore === 'number'
        ? Number((effB - effA).toFixed(2))
        : 'UNKNOWN';

    let winner: 'PLAN_A' | 'PLAN_B' | 'TIE' = 'TIE';
    let rationale = '';

    if (successRateB > successRateA || (successRateB === successRateA && effB > effA)) {
      winner = 'PLAN_B';
      rationale = `Plan v${planB.planVersion} outperformed Plan v${planA.planVersion} with higher success rate (${(successRateB * 100).toFixed(0)}% vs ${(successRateA * 100).toFixed(0)}%) and superior efficiency score.`;
    } else if (successRateA > successRateB || (successRateA === successRateB && effA > effB)) {
      winner = 'PLAN_A';
      rationale = `Plan v${planA.planVersion} outperformed Plan v${planB.planVersion} with higher success rate (${(successRateA * 100).toFixed(0)}% vs ${(successRateB * 100).toFixed(0)}%).`;
    } else {
      winner = 'TIE';
      rationale = `Plan v${planA.planVersion} and Plan v${planB.planVersion} demonstrated equivalent execution efficiency.`;
    }

    const comparisonSummary = `Plan v${planA.planVersion} (Success: ${(successRateA * 100).toFixed(0)}%, Latency: ${planA.actualLatencyMs}ms) vs Plan v${planB.planVersion} (Success: ${(successRateB * 100).toFixed(0)}%, Latency: ${planB.actualLatencyMs}ms). Result: ${winner}.`;

    return {
      winner,
      efficiencyDiff,
      latencyDiffMs: latencyDiff,
      successRateDiff,
      rationale,
      comparisonSummary,
    };
  }

  /**
   * Generates a structured self-critique distinguishing known from speculative improvements.
   */
  public generateSelfCritique(goal: Goal, planVersion?: number): SelfCritique {
    const version = planVersion ?? goal.currentPlanVersion;
    const plan = goal.plans.find((p) => p.version === version) || goal.plans[0];

    const succeeded: string[] = [];
    const failed: string[] = [];
    const uncertain: string[] = [];

    if (plan) {
      for (const act of plan.actions) {
        if (act.status === 'SUCCEEDED') succeeded.push(`Action ${act.actionId}: ${act.title}`);
        else if (act.status === 'FAILED') failed.push(`Action ${act.actionId}: ${act.title}`);
        else uncertain.push(`Action ${act.actionId}: ${act.title} (Status: ${act.status})`);
      }
    }

    const knownImprovements: string[] = [];
    const speculativeImprovements: string[] = [];
    const mustNotChange: string[] = [
      'Stage 03 Blender scene and 14 GLB 3D assets remain strictly immutable.',
      'All intelligence task executions must be mediated through the Stage 07 Execution Gateway.',
      'Human approval checkpoints for high-risk actions cannot be bypassed.',
    ];

    if (failed.length > 0) {
      knownImprovements.push(
        `Address verified failure in ${failed.length} action(s) by configuring alternate fallback providers.`
      );
    }

    if (goal.plans.length > 1) {
      knownImprovements.push(
        `Plan was replanned from v1 to v${goal.currentPlanVersion}; preserve topological ordering of proven stable actions.`
      );
    }

    speculativeImprovements.push(
      'Evaluate concurrent action batching in sub-DAG layers to reduce overall pipeline latency.',
      'Investigate lightweight specialized agents for routine validation steps to conserve resource budget.'
    );

    const evidenceSummary = [
      `Goal objective: ${goal.objective}`,
      `Total plan actions: ${plan ? plan.actions.length : 0}`,
      `Succeeded actions: ${succeeded.length}`,
      `Failed actions: ${failed.length}`,
    ];

    return {
      taskId: goal.goalId,
      succeeded,
      failed,
      uncertain,
      evidenceSummary,
      knownImprovements,
      speculativeImprovements,
      mustNotChange,
      timestamp: new Date().toISOString(),
    };
  }
}

export const planEvaluationService = new PlanEvaluationService();
