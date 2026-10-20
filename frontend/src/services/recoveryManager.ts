/**
 * AryaOS V1 — Stage 09: Recovery Manager
 *
 * Deterministic crash recovery engine that reconstructs goal states, restores DAG frontiers,
 * applies action resume safety policies, prevents duplicate consequential executions via
 * Stage 07 idempotency checks, and preserves human approval boundaries across restarts.
 */

import { Goal, Plan, ActionNode } from '../types/goalOrchestration';
import {
  ActionRecoveryClassification,
  RecoveryActionDecision,
  GoalRecoveryResult,
  PersistedApprovalRecord,
} from '../types/executionPersistence';
import { executionPersistence } from './executionPersistence';
import { executionJournal } from './executionJournal';
import { executionGateway } from './executionGateway';

export class RecoveryManager {
  /**
   * Classifies an action's recovery safety according to its semantics, capability, and risk level.
   */
  public classifyActionRecovery(action: ActionNode, goal?: Goal): ActionRecoveryClassification {
    // 1. Terminal / Completed States
    if (action.status === 'SUCCEEDED' || action.status === 'CANCELLED') {
      return 'DO_NOT_RETRY';
    }

    // 2. Consequential / External Side Effects require human approval
    if (
      action.approvalRequirement.required ||
      action.approvalRequirement.riskLevel === 'CONSEQUENTIAL' ||
      action.approvalRequirement.riskLevel === 'EXTERNAL_SIDE_EFFECT' ||
      action.type === 'VIDEO_GENERATION'
    ) {
      if (!action.approvalRequirement.approvedAt) {
        return 'REQUIRES_HUMAN_APPROVAL';
      }
      // If was in-flight when stopped, require revalidation to prevent duplicate execution
      if (action.status === 'EXECUTING') {
        return 'REQUIRES_REVALIDATION';
      }
      return 'IDEMPOTENT_RETRY';
    }

    // 3. Failed actions check retry policy
    if (action.status === 'FAILED') {
      if (action.retryPolicy.retriesAttempted < action.retryPolicy.maxRetries) {
        return 'SAFE_TO_RETRY';
      }
      return 'DO_NOT_RETRY';
    }

    // 4. Read-only / research / analysis in-flight or ready
    if (
      action.requiredCapability === 'RESEARCH' ||
      action.approvalRequirement.riskLevel === 'READ_ONLY' ||
      action.approvalRequirement.riskLevel === 'LOW_RISK'
    ) {
      return 'SAFE_TO_RETRY';
    }

    // 5. Default fallback
    return 'IDEMPOTENT_RETRY';
  }

  /**
   * Computes the exact executable DAG frontier after crash or restart.
   * An action is on the frontier if all its dependencies are SUCCEEDED and it is not completed or blocked.
   */
  public getExecutableFrontier(plan: Plan): string[] {
    const frontier: string[] = [];

    for (const action of plan.actions) {
      if (
        action.status === 'SUCCEEDED' ||
        action.status === 'FAILED' ||
        action.status === 'CANCELLED' ||
        action.status === 'BLOCKED'
      ) {
        continue;
      }

      const allDepsMet = action.dependencies.every((depId) => {
        const depNode = plan.actions.find((a) => a.actionId === depId);
        return depNode && depNode.status === 'SUCCEEDED';
      });

      if (allDepsMet) {
        frontier.push(action.actionId);
      }
    }

    return frontier;
  }

  /**
   * Recovers a single Goal deterministically from persisted state and journal.
   */
  public recoverGoal(goal: Goal): GoalRecoveryResult {
    const previousStatus = goal.status;
    const plan = goal.plans.find((p) => p.planId === goal.currentPlanId);

    if (!plan) {
      return {
        goalId: goal.goalId,
        previousStatus,
        recoveredStatus: goal.status,
        planVersion: goal.currentPlanVersion,
        executableFrontier: [],
        actionDecisions: [],
        approvalsPending: [],
        resumed: false,
        summary: `Goal ${goal.goalId} has no active plan to recover.`,
      };
    }

    // If goal was already COMPLETED or CANCELLED, preserve terminal state (no resurrection)
    if (goal.status === 'COMPLETED' || goal.status === 'CANCELLED') {
      return {
        goalId: goal.goalId,
        previousStatus,
        recoveredStatus: goal.status,
        planVersion: plan.version,
        executableFrontier: [],
        actionDecisions: [],
        approvalsPending: [],
        resumed: false,
        summary: `Goal ${goal.goalId} is in terminal status ${goal.status}. Preserved without modification.`,
      };
    }

    executionJournal.appendEvent({
      goalId: goal.goalId,
      planId: plan.planId,
      planVersion: plan.version,
      eventType: 'RECOVERY_INITIATED',
      previousState: previousStatus,
      payload: { reason: 'System restart / crash recovery triggered' },
    });

    const actionDecisions: RecoveryActionDecision[] = [];
    const approvalsPending: string[] = [];

    // Check each action in the active plan
    for (const action of plan.actions) {
      const classification = this.classifyActionRecovery(action, goal);

      // 1. Succeeded actions are preserved unconditionally
      if (action.status === 'SUCCEEDED') {
        actionDecisions.push({
          actionId: action.actionId,
          previousStatus: action.status,
          recoveryClassification: 'DO_NOT_RETRY',
          actionToTake: 'PRESERVE_SUCCEEDED',
          reason: 'Action completed successfully prior to interruption.',
        });
        continue;
      }

      // 2. Interrupted in-flight actions (status === 'EXECUTING')
      if (action.status === 'EXECUTING') {
        const idempKey = `IDEMP-${action.actionId}-${action.requiredCapability}-${action.providerId || 'default'}`;
        const cachedExecution = executionGateway.getCompletedExecution(idempKey);

        if (cachedExecution && (cachedExecution.status === 'SUCCEEDED' || cachedExecution.status === 'FALLBACK_SUCCEEDED')) {
          // Execution had actually completed in the gateway before process died
          action.status = 'SUCCEEDED';
          action.outputs = {
            summary: cachedExecution.output,
          };
          actionDecisions.push({
            actionId: action.actionId,
            previousStatus: 'EXECUTING',
            recoveryClassification: 'DO_NOT_RETRY',
            actionToTake: 'PRESERVE_SUCCEEDED',
            reason: 'Recovered verified completion from Stage 07 gateway idempotency cache.',
            idempotencyKey: idempKey,
          });
          continue;
        }

        // Check if consequential: hold for approval / revalidation
        if (
          action.approvalRequirement.required ||
          action.approvalRequirement.riskLevel === 'CONSEQUENTIAL' ||
          action.approvalRequirement.riskLevel === 'EXTERNAL_SIDE_EFFECT'
        ) {
          action.status = 'AWAITING_APPROVAL';
          action.approvalRequirement.approvedAt = undefined; // Require human approval again
          approvalsPending.push(action.actionId);

          actionDecisions.push({
            actionId: action.actionId,
            previousStatus: 'EXECUTING',
            recoveryClassification: 'REQUIRES_HUMAN_APPROVAL',
            actionToTake: 'HOLD_FOR_APPROVAL',
            reason: 'Interrupted consequential action paused at human approval boundary to prevent unintended side effects.',
            idempotencyKey: idempKey,
          });
        } else {
          // Safe read-only action transitions back to READY
          action.status = 'READY';
          actionDecisions.push({
            actionId: action.actionId,
            previousStatus: 'EXECUTING',
            recoveryClassification: 'SAFE_TO_RETRY',
            actionToTake: 'RESUME_IMMEDIATELY',
            reason: 'Safe read-only query transitioned to READY for automated resumption.',
            idempotencyKey: idempKey,
          });
        }
        continue;
      }

      // 3. Actions awaiting approval
      if (action.status === 'AWAITING_APPROVAL') {
        approvalsPending.push(action.actionId);
        actionDecisions.push({
          actionId: action.actionId,
          previousStatus: action.status,
          recoveryClassification: 'REQUIRES_HUMAN_APPROVAL',
          actionToTake: 'HOLD_FOR_APPROVAL',
          reason: 'Preserved pending human approval boundary across session restart.',
        });
        continue;
      }

      // 4. Waiting dependency
      if (action.status === 'WAITING_DEPENDENCY') {
        actionDecisions.push({
          actionId: action.actionId,
          previousStatus: action.status,
          recoveryClassification: classification,
          actionToTake: 'SKIP',
          reason: 'Dependencies not yet satisfied.',
        });
      }
    }

    // Calculate post-recovery execution frontier
    const executableFrontier = this.getExecutableFrontier(plan);

    // Update goal status
    let recoveredStatus: string = goal.status;
    if (approvalsPending.length > 0) {
      recoveredStatus = 'AWAITING_APPROVAL';
    } else if (goal.status === 'PAUSED') {
      recoveredStatus = 'PAUSED';
    } else if (plan.actions.every((a) => a.status === 'SUCCEEDED')) {
      recoveredStatus = 'COMPLETED';
    } else if (executableFrontier.length > 0) {
      recoveredStatus = 'READY';
    }

    goal.status = recoveredStatus as any;
    goal.updatedAt = new Date().toISOString();

    // Persist recovered goal
    executionPersistence.saveGoal(goal);

    executionJournal.appendEvent({
      goalId: goal.goalId,
      planId: plan.planId,
      planVersion: plan.version,
      eventType: 'RECOVERY_COMPLETED',
      previousState: previousStatus,
      newState: recoveredStatus,
      payload: {
        frontierCount: executableFrontier.length,
        pendingApprovalsCount: approvalsPending.length,
      },
    });

    return {
      goalId: goal.goalId,
      previousStatus,
      recoveredStatus,
      planVersion: plan.version,
      executableFrontier,
      actionDecisions,
      approvalsPending,
      resumed: recoveredStatus === 'READY' || recoveredStatus === 'EXECUTING',
      summary: `Goal ${goal.goalId} recovered from ${previousStatus} to ${recoveredStatus} with ${executableFrontier.length} executable frontier actions.`,
    };
  }

  /**
   * Recovers all persisted goals across the entire application on boot.
   */
  public recoverAllGoals(): GoalRecoveryResult[] {
    const envelope = executionPersistence.loadEnvelope();
    if (!envelope || !envelope.goals) {
      return [];
    }

    const results: GoalRecoveryResult[] = [];
    for (const goal of Object.values(envelope.goals)) {
      const res = this.recoverGoal(goal);
      results.push(res);
    }

    executionPersistence.updateTelemetry((prev) => ({
      ...prev,
      totalGoalsRecovered: prev.totalGoalsRecovered + results.filter((r) => r.resumed).length,
      lastRecoveryAt: new Date().toISOString(),
    }));

    return results;
  }
}

export const recoveryManager = new RecoveryManager();
