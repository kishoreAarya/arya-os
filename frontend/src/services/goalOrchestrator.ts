/**
 * AryaOS V1 — Stage 08: End-to-End Autonomous Goal Orchestration Engine
 *
 * Coordinates closed-loop task execution:
 * GOAL -> PLAN -> ACTION GRAPH -> SCHEDULER -> CONTEXT -> ROUTER -> GATEWAY
 * -> RESULT -> OBSERVATION -> MEMORY -> REPLAN -> COMPLETION
 *
 * Strictly executes provider intelligence exclusively through the Stage 07 ExecutionGateway.
 */

import {
  Goal,
  Plan,
  ActionNode,
  ActionStatus,
  Observation,
  ProducedArtifact,
  GoalExecutionOptions,
} from '../types/goalOrchestration';
import { ExecutionPlan } from '../types/intelligenceProvider';
import { ActionProposal, CommandContext, MemoryEvent } from '../types/spatialCommand';
import { goalInterpreter } from './goalInterpreter';
import { planGenerator } from './planGenerator';
import { executionGateway } from './executionGateway';
import { providerRouter } from './providerRouter';
import { resultNormalizer } from './resultNormalizer';
import { actionProposalService } from './actionProposalService';
import { memoryArchiveService } from './memoryArchiveService';
import { memoryContextService } from './memoryContextService';
import { executionPersistence } from './executionPersistence';
import { executionJournal } from './executionJournal';
import { recoveryManager } from './recoveryManager';
import { executionScheduler } from './executionScheduler';
import { GoalRecoveryResult } from '../types/executionPersistence';

export class GoalOrchestrator {
  private goals: Map<string, Goal> = new Map();
  private observations: Map<string, Observation[]> = new Map(); // goalId -> observations
  private executionOptions: Map<string, GoalExecutionOptions> = new Map(); // goalId -> options
  private activeGoalId: string | null = null;
  private abortControllers: Map<string, AbortController> = new Map(); // goalId -> controller
  private isProcessing: boolean = false;

  constructor() {
    this.resetState();
  }

  /**
   * Clears orchestrator state (useful for tests and fresh sessions).
   */
  public resetState(): void {
    this.goals.clear();
    this.observations.clear();
    this.executionOptions.clear();
    this.activeGoalId = null;
    this.abortControllers.clear();
    this.isProcessing = false;
    executionPersistence.clearEnvelope();
    executionJournal.resetState();
    executionScheduler.resetState();
  }

  public getGoal(goalId: string): Goal | undefined {
    return this.goals.get(goalId);
  }

  public getAllGoals(): Goal[] {
    return Array.from(this.goals.values());
  }

  public getActiveGoal(): Goal | null {
    return this.activeGoalId ? this.goals.get(this.activeGoalId) || null : null;
  }

  public getObservationsForGoal(goalId: string): Observation[] {
    return this.observations.get(goalId) || [];
  }

  /**
   * Primary entry point: Creates, plans, and begins autonomous execution of a goal.
   */
  public async createAndExecuteGoal(
    userIntent: string,
    targetMemoryId?: string,
    options: GoalExecutionOptions = {}
  ): Promise<Goal> {
    // 1. Goal Interpretation
    const goal = goalInterpreter.interpret(userIntent, targetMemoryId);
    this.goals.set(goal.goalId, goal);
    this.executionOptions.set(goal.goalId, options);
    this.activeGoalId = goal.goalId;

    executionPersistence.saveGoal(goal);
    executionPersistence.updateTelemetry((prev) => ({
      ...prev,
      totalGoalsStarted: prev.totalGoalsStarted + 1,
    }));
    executionJournal.appendEvent({
      goalId: goal.goalId,
      eventType: 'GOAL_CREATED',
      newState: goal.status,
      payload: { objective: goal.objective, intent: userIntent },
    });
    this.recordMemoryEvent(goal, 'GOAL_CREATED', 'RECORDED', `Goal created: "${goal.objective}"`);

    // 2. Initial Plan Generation (Plan v1)
    const plan = planGenerator.generatePlan(goal);
    goal.plans.push(plan);
    goal.currentPlanId = plan.planId;
    goal.currentPlanVersion = 1;
    goal.status = 'READY';
    goal.updatedAt = new Date().toISOString();

    executionPersistence.saveGoal(goal);
    executionJournal.appendEvent({
      goalId: goal.goalId,
      planId: plan.planId,
      planVersion: plan.version,
      eventType: 'PLAN_CREATED',
      newState: 'READY',
      payload: { actionCount: plan.actions.length, layers: plan.executionOrder.length },
    });
    this.recordMemoryEvent(
      goal,
      'PLAN_CREATED',
      'PLANNED',
      `Plan v1 generated with ${plan.actions.length} action nodes across ${plan.executionOrder.length} topological layers.`
    );

    options.onGoalProgress?.(goal, plan);

    // 3. Begin Autonomous Execution Loop
    await this.runExecutionLoop(goal.goalId, options);

    return this.goals.get(goal.goalId)!;
  }

  /**
   * The core execution scheduler loop.
   */
  public async runExecutionLoop(
    goalId: string,
    options?: GoalExecutionOptions
  ): Promise<void> {
    const goal = this.goals.get(goalId);
    if (!goal) return;

    const mergedOptions: GoalExecutionOptions = {
      ...(this.executionOptions.get(goalId) || {}),
      ...(options || {}),
    };
    this.executionOptions.set(goalId, mergedOptions);

    const controller = new AbortController();
    this.abortControllers.set(goalId, controller);
    const maxReplans = mergedOptions.maxReplans ?? 2;
    let replanCount = 0;

    goal.status = 'EXECUTING';
    goal.updatedAt = new Date().toISOString();
    executionPersistence.saveGoal(goal);
    executionJournal.appendEvent({
      goalId: goal.goalId,
      eventType: 'GOAL_RESUMED',
      newState: 'EXECUTING',
    });

    while (goal.status === 'EXECUTING') {
      const activePlan = goal.plans.find((p) => p.planId === goal.currentPlanId);
      if (!activePlan) break;

      // 1. Check for cancellation
      if (mergedOptions.signal?.aborted || controller.signal.aborted) {
        goal.status = 'CANCELLED';
        goal.updatedAt = new Date().toISOString();
        executionPersistence.saveGoal(goal);
        executionJournal.appendEvent({
          goalId: goal.goalId,
          eventType: 'GOAL_CANCELLED',
          newState: 'CANCELLED',
        });
        this.recordMemoryEvent(goal, 'GOAL_CANCELLED', 'RECORDED', 'Goal execution cancelled by operator.');
        break;
      }

      // 2. Identify ready actions whose dependencies are fully SUCCEEDED
      const executableActions = this.resolveExecutableActions(activePlan, mergedOptions.autoApprove);

      // Check if all actions in plan are finished
      const allSucceeded = activePlan.actions.every((a) => a.status === 'SUCCEEDED');
      if (allSucceeded) {
        goal.status = 'COMPLETED';
        goal.updatedAt = new Date().toISOString();
        goal.finalSummary = `Goal completed successfully across ${activePlan.actions.length} actions in Plan v${activePlan.version}.`;
        executionPersistence.saveGoal(goal);
        executionPersistence.updateTelemetry((prev) => ({
          ...prev,
          totalGoalsCompleted: prev.totalGoalsCompleted + 1,
        }));
        executionJournal.appendEvent({
          goalId: goal.goalId,
          planId: activePlan.planId,
          planVersion: activePlan.version,
          eventType: 'GOAL_COMPLETED',
          newState: 'COMPLETED',
          payload: { finalSummary: goal.finalSummary },
        });
        this.recordMemoryEvent(goal, 'GOAL_COMPLETED', 'EXECUTED', goal.finalSummary);
        mergedOptions.onGoalProgress?.(goal, activePlan);
        break;
      }

      // 3. Check for actions awaiting approval
      const awaitingApproval = activePlan.actions.filter((a) => a.status === 'AWAITING_APPROVAL');
      if (awaitingApproval.length > 0 && !mergedOptions.autoApprove) {
        goal.status = 'AWAITING_APPROVAL';
        goal.updatedAt = new Date().toISOString();
        const pendingAct = awaitingApproval[0];

        executionPersistence.saveApproval({
          approvalId: `APPR-${pendingAct.actionId}`,
          goalId: goal.goalId,
          planId: activePlan.planId,
          actionId: pendingAct.actionId,
          actionTitle: pendingAct.title,
          riskLevel: pendingAct.approvalRequirement.riskLevel,
          requestedAt: new Date().toISOString(),
          status: 'PENDING',
          expiresAt: new Date(Date.now() + 86400000).toISOString(),
        });
        executionPersistence.saveGoal(goal);
        executionJournal.appendEvent({
          goalId: goal.goalId,
          planId: activePlan.planId,
          planVersion: activePlan.version,
          actionId: pendingAct.actionId,
          eventType: 'APPROVAL_REQUIRED',
          previousState: 'READY',
          newState: 'AWAITING_APPROVAL',
          payload: { actionTitle: pendingAct.title, riskLevel: pendingAct.approvalRequirement.riskLevel },
        });

        this.recordMemoryEvent(
          goal,
          'ACTION_AWAITING_APPROVAL',
          'PLANNED',
          `Action [${pendingAct.title}] requires human operator confirmation.`
        );
        mergedOptions.onGoalProgress?.(goal, activePlan);
        break; // Pause execution until operator approval
      }

      // If no actions can execute and not completed, check if blocked or failed
      if (executableActions.length === 0) {
        const hasFailed = activePlan.actions.some((a) => a.status === 'FAILED');
        if (hasFailed) {
          // Trigger replanning if within maxReplans
          const failedAction = activePlan.actions.find((a) => a.status === 'FAILED')!;
          if (replanCount < maxReplans) {
            replanCount++;
            goal.status = 'REPLANNING';
            executionJournal.appendEvent({
              goalId: goal.goalId,
              planId: activePlan.planId,
              planVersion: activePlan.version,
              actionId: failedAction.actionId,
              eventType: 'GOAL_REPLANNED',
              previousState: 'EXECUTING',
              newState: 'REPLANNING',
              payload: { failedAction: failedAction.title, replanCount },
            });
            this.recordMemoryEvent(
              goal,
              'PLAN_REVISED',
              'PLANNED',
              `Replanning triggered for failed action [${failedAction.title}]. Generating Plan v${activePlan.version + 1}.`
            );

            activePlan.status = 'SUPERSEDED';
            activePlan.supersededAt = new Date().toISOString();

            const newPlan = planGenerator.generateReplan(
              goal,
              activePlan,
              failedAction.actionId,
              `Recovering from failure in ${failedAction.title}`
            );

            goal.plans.push(newPlan);
            goal.currentPlanId = newPlan.planId;
            goal.currentPlanVersion = newPlan.version;
            goal.status = 'EXECUTING';

            executionPersistence.saveGoal(goal);
            executionPersistence.updateTelemetry((prev) => ({
              ...prev,
              totalReplans: prev.totalReplans + 1,
            }));

            mergedOptions.onGoalProgress?.(goal, newPlan);
            continue; // Continue loop with newly generated plan version
          } else {
            goal.status = 'FAILED';
            goal.failureReason = `Goal failed: action [${failedAction.title}] failed and replan limit (${maxReplans}) reached.`;
            executionPersistence.saveGoal(goal);
            executionPersistence.updateTelemetry((prev) => ({
              ...prev,
              totalGoalsFailed: prev.totalGoalsFailed + 1,
            }));
            executionJournal.appendEvent({
              goalId: goal.goalId,
              planId: activePlan.planId,
              planVersion: activePlan.version,
              actionId: failedAction.actionId,
              eventType: 'GOAL_FAILED',
              newState: 'FAILED',
              payload: { failureReason: goal.failureReason },
            });
            this.recordMemoryEvent(goal, 'GOAL_FAILED', 'RECORDED', goal.failureReason);
            mergedOptions.onGoalProgress?.(goal, activePlan);
            break;
          }
        }

        // Otherwise blocked
        goal.status = 'BLOCKED';
        executionPersistence.saveGoal(goal);
        this.recordMemoryEvent(goal, 'GOAL_BLOCKED', 'RECORDED', 'No executable actions remaining in dependency graph.');
        mergedOptions.onGoalProgress?.(goal, activePlan);
        break;
      }

      // 4. Concurrently execute ready actions (bounded by maxConcurrentActions)
      const concurrencyLimit = mergedOptions.maxConcurrentActions || 2;
      const batch = executableActions.slice(0, concurrencyLimit);

      // Execute batch concurrently
      await Promise.all(
        batch.map((action) =>
          this.executeActionNode(goal, activePlan, action, controller.signal)
        )
      );

      mergedOptions.onGoalProgress?.(goal, activePlan);
    }
  }

  /**
   * Resolves which action nodes can be executed right now.
   * A node is executable when all its dependencies have status SUCCEEDED.
   */
  private resolveExecutableActions(plan: Plan, autoApprove?: boolean): ActionNode[] {
    const readyNodes: ActionNode[] = [];

    for (const action of plan.actions) {
      if (action.status === 'SUCCEEDED' || action.status === 'EXECUTING' || action.status === 'FAILED') {
        continue;
      }

      // Check all dependencies
      const deps = action.dependencies;
      const allDepsMet = deps.every((depId) => {
        const depNode = plan.actions.find((a) => a.actionId === depId);
        return depNode && depNode.status === 'SUCCEEDED';
      });

      if (allDepsMet) {
        if (action.approvalRequirement.required && !action.approvalRequirement.approvedAt) {
          if (autoApprove) {
            action.approvalRequirement.approvedAt = new Date().toISOString();
            action.approvalRequirement.approvedBy = 'auto-approval-policy';
            action.status = 'READY';
            readyNodes.push(action);
          } else {
            action.status = 'AWAITING_APPROVAL';
          }
        } else {
          action.status = 'READY';
          readyNodes.push(action);
        }
      } else {
        action.status = 'WAITING_DEPENDENCY';
      }
    }

    return readyNodes;
  }

  /**
   * Executes a single ActionNode strictly through the Stage 07 Execution Gateway.
   */
  public async executeActionNode(
    goal: Goal,
    plan: Plan,
    action: ActionNode,
    signal?: AbortSignal
  ): Promise<Observation> {
    const startTime = Date.now();
    action.status = 'EXECUTING';
    executionJournal.appendEvent({
      goalId: goal.goalId,
      planId: plan.planId,
      planVersion: plan.version,
      actionId: action.actionId,
      eventType: 'ACTION_STARTED',
      newState: 'EXECUTING',
      payload: { capability: action.requiredCapability },
    });
    this.recordMemoryEvent(
      goal,
      'ACTION_EXECUTING',
      'EXECUTING',
      `Dispatching action [${action.title}] via ExecutionGateway (${action.requiredCapability}).`
    );

    // 1. Build ActionProposal representation
    const proposal: ActionProposal = {
      id: action.actionId,
      actionClass: action.type === 'RESEARCH' ? 'RESEARCH' : 'CREATE_WORKFLOW',
      title: action.title,
      description: action.description,
      sourceMemoryId: goal.contextRequirements.targetMemoryId,
      sourceMemoryTitle: goal.provenance.sourceMemoryTitle,
      contextSummary: {
        relatedCount: goal.contextRequirements.contextMemories.length,
        entitiesCount: goal.contextRequirements.entityNames.length,
        decisionsCount: 1,
      },
      payload: action.inputs,
      executionType: 'BACKEND_ADAPTER',
      status: 'PROPOSED',
      createdAt: new Date().toISOString(),
    };

    // 2. Route via ProviderRouter (Stage 06)
    const executionPlan = providerRouter.createExecutionPlan(proposal);
    executionPlan.capability = action.requiredCapability;
    action.providerId = executionPlan.providerId;
    action.modelId = executionPlan.modelId;

    // 3. Dispatch via Stage 07 ExecutionGateway Singleton
    const executionResult = await executionGateway.execute(
      executionPlan,
      undefined,
      { signal }
    );

    action.executionId = executionResult.executionId;
    const latency = Date.now() - startTime;

    if (executionResult.fallbackUsed) {
      executionPersistence.updateTelemetry((prev) => ({
        ...prev,
        totalFallbacksTriggered: prev.totalFallbacksTriggered + 1,
      }));
      executionJournal.appendEvent({
        goalId: goal.goalId,
        planId: plan.planId,
        planVersion: plan.version,
        actionId: action.actionId,
        eventType: 'PROVIDER_FALLBACK',
        payload: {
          originalProvider: executionPlan.providerId,
          fallbackProvider: executionResult.providerId,
        },
      });
    }

    // 4. Observation & Result Validation
    const isSuccess =
      executionResult.status === 'SUCCEEDED' ||
      executionResult.status === 'FALLBACK_SUCCEEDED';

    const observationId = `OBS-${Date.now()}-${Math.floor(Math.random() * 1000)}`;
    const producedArtifacts: ProducedArtifact[] = [];

    if (isSuccess && executionResult.output) {
      producedArtifacts.push({
        id: `ART-${action.actionId}`,
        type: 'TEXT_SYNTHESIS',
        name: `${action.title} Artifact`,
        content: executionResult.output,
      });
    }

    const observation: Observation = {
      observationId,
      goalId: goal.goalId,
      planId: plan.planId,
      actionId: action.actionId,
      executionId: executionResult.executionId,
      status: isSuccess ? 'SUCCESS' : 'FAILURE',
      resultSummary: isSuccess
        ? `Action executed via ${executionResult.providerId} (${executionResult.modelId}) in ${latency}ms.`
        : executionResult.sanitizedError || executionResult.error || 'Execution failed',
      producedArtifacts,
      providerId: executionResult.providerId,
      modelId: executionResult.modelId,
      latencyMs: latency,
      failureReason: isSuccess ? undefined : executionResult.error,
      confidence: isSuccess ? 0.96 : 0.2,
      downstreamImplications: isSuccess
        ? [`Unblocks dependent actions in layer for ${action.title}`]
        : [`Blocks downstream dependents of ${action.title}`],
      memoryReferences: goal.contextRequirements.contextMemories,
      timestamp: new Date().toISOString(),
    };

    // Store observation
    const goalObs = this.observations.get(goal.goalId) || [];
    goalObs.push(observation);
    this.observations.set(goal.goalId, goalObs);

    executionPersistence.saveObservation(goal.goalId, observation);

    // Update ActionNode Status
    if (isSuccess) {
      action.status = 'SUCCEEDED';
      action.outputs = {
        summary: observation.resultSummary,
        artifacts: producedArtifacts,
      };
      executionPersistence.saveGoal(goal);
      executionPersistence.updateTelemetry((prev) => ({
        ...prev,
        totalActionsExecuted: prev.totalActionsExecuted + 1,
      }));
      executionJournal.appendEvent({
        goalId: goal.goalId,
        planId: plan.planId,
        planVersion: plan.version,
        actionId: action.actionId,
        eventType: 'ACTION_SUCCEEDED',
        newState: 'SUCCEEDED',
        payload: {
          providerId: executionResult.providerId,
          latencyMs: latency,
        },
      });
      this.recordMemoryEvent(
        goal,
        'ACTION_SUCCEEDED',
        'EXECUTED',
        `Action [${action.title}] completed successfully via ${executionResult.providerId}.`
      );
    } else if (executionResult.status === 'CANCELLED') {
      action.status = 'CANCELLED';
      executionPersistence.saveGoal(goal);
      executionJournal.appendEvent({
        goalId: goal.goalId,
        planId: plan.planId,
        planVersion: plan.version,
        actionId: action.actionId,
        eventType: 'ACTION_CANCELLED',
        newState: 'CANCELLED',
      });
      this.recordMemoryEvent(
        goal,
        'ACTION_FAILED',
        'RECORDED',
        `Action [${action.title}] was cancelled by operator.`
      );
    } else {
      action.status = 'FAILED';
      executionPersistence.saveGoal(goal);
      executionJournal.appendEvent({
        goalId: goal.goalId,
        planId: plan.planId,
        planVersion: plan.version,
        actionId: action.actionId,
        eventType: 'ACTION_FAILED',
        newState: 'FAILED',
        payload: {
          error: observation.failureReason,
        },
      });
      this.recordMemoryEvent(
        goal,
        'ACTION_FAILED',
        'RECORDED',
        `Action [${action.title}] failed on ${executionResult.providerId}: ${observation.failureReason}`
      );
    }

    return observation;
  }

  /**
   * Operator Approval for a consequential or external side-effect action.
   */
  public async approveAction(
    goalId: string,
    actionId: string,
    operatorId: string = 'operator-primary'
  ): Promise<boolean> {
    const goal = this.goals.get(goalId);
    if (!goal) return false;

    const plan = goal.plans.find((p) => p.planId === goal.currentPlanId);
    if (!plan) return false;

    const action = plan.actions.find((a) => a.actionId === actionId);
    if (!action) return false;

    action.approvalRequirement.approvedBy = operatorId;
    action.approvalRequirement.approvedAt = new Date().toISOString();
    action.status = 'READY';

    executionPersistence.saveApproval({
      approvalId: `APPR-${actionId}`,
      goalId,
      planId: plan.planId,
      actionId,
      actionTitle: action.title,
      riskLevel: action.approvalRequirement.riskLevel,
      requestedAt: action.approvalRequirement.approvedAt,
      status: 'APPROVED',
      decidedAt: new Date().toISOString(),
      decidedBy: operatorId,
      expiresAt: new Date(Date.now() + 86400000).toISOString(),
    });
    executionPersistence.saveGoal(goal);
    executionJournal.appendEvent({
      goalId,
      planId: plan.planId,
      planVersion: plan.version,
      actionId,
      eventType: 'APPROVAL_GRANTED',
      previousState: 'AWAITING_APPROVAL',
      newState: 'READY',
      payload: { operatorId },
    });

    this.recordMemoryEvent(
      goal,
      'ACTION_APPROVED',
      'RECORDED',
      `Operator approved consequential action [${action.title}]. Resuming goal execution.`
    );

    if (goal.status === 'AWAITING_APPROVAL') {
      goal.status = 'EXECUTING';
      await this.runExecutionLoop(goalId);
    }

    return true;
  }

  /**
   * Operator Rejection for a consequential action.
   */
  public rejectAction(
    goalId: string,
    actionId: string,
    reason: string
  ): boolean {
    const goal = this.goals.get(goalId);
    if (!goal) return false;

    const plan = goal.plans.find((p) => p.planId === goal.currentPlanId);
    if (!plan) return false;

    const action = plan.actions.find((a) => a.actionId === actionId);
    if (!action) return false;

    action.approvalRequirement.rejectionReason = reason;
    action.status = 'BLOCKED';
    goal.status = 'BLOCKED';

    executionPersistence.saveApproval({
      approvalId: `APPR-${actionId}`,
      goalId,
      planId: plan.planId,
      actionId,
      actionTitle: action.title,
      riskLevel: action.approvalRequirement.riskLevel,
      requestedAt: new Date().toISOString(),
      status: 'REJECTED',
      decidedAt: new Date().toISOString(),
      rejectionReason: reason,
      expiresAt: new Date(Date.now() + 86400000).toISOString(),
    });
    executionPersistence.saveGoal(goal);
    executionJournal.appendEvent({
      goalId,
      planId: plan.planId,
      planVersion: plan.version,
      actionId,
      eventType: 'APPROVAL_REJECTED',
      previousState: 'AWAITING_APPROVAL',
      newState: 'BLOCKED',
      payload: { reason },
    });

    this.recordMemoryEvent(
      goal,
      'ACTION_REJECTED',
      'RECORDED',
      `Operator rejected consequential action [${action.title}]: ${reason}`
    );

    return true;
  }

  /**
   * Operator Pause Control.
   */
  public pauseGoal(goalId: string): boolean {
    const goal = this.goals.get(goalId);
    if (!goal || goal.status !== 'EXECUTING') return false;

    goal.status = 'BLOCKED';
    goal.updatedAt = new Date().toISOString();
    executionPersistence.saveGoal(goal);
    executionJournal.appendEvent({
      goalId,
      eventType: 'GOAL_PAUSED',
      previousState: 'EXECUTING',
      newState: 'BLOCKED',
    });
    this.recordMemoryEvent(goal, 'GOAL_PAUSED', 'RECORDED', 'Goal paused by operator.');
    return true;
  }

  /**
   * Operator Resume Control.
   */
  public async resumeGoal(goalId: string): Promise<boolean> {
    const goal = this.goals.get(goalId);
    if (!goal || (goal.status !== 'BLOCKED' && goal.status !== 'AWAITING_APPROVAL')) return false;

    goal.status = 'EXECUTING';
    goal.updatedAt = new Date().toISOString();
    executionPersistence.saveGoal(goal);
    executionJournal.appendEvent({
      goalId,
      eventType: 'GOAL_RESUMED',
      previousState: 'BLOCKED',
      newState: 'EXECUTING',
    });
    this.recordMemoryEvent(goal, 'GOAL_RESUMED', 'RECORDED', 'Goal resumed by operator.');
    await this.runExecutionLoop(goalId);
    return true;
  }

  /**
   * Operator Cancellation Control.
   */
  public cancelGoal(goalId: string): boolean {
    const goal = this.goals.get(goalId);
    if (!goal) return false;

    const controller = this.abortControllers.get(goalId);
    if (controller) {
      controller.abort();
    }

    goal.status = 'CANCELLED';
    goal.updatedAt = new Date().toISOString();

    const plan = goal.plans.find((p) => p.planId === goal.currentPlanId);
    if (plan) {
      plan.status = 'CANCELLED';
      for (const act of plan.actions) {
        if (act.status === 'READY' || act.status === 'WAITING_DEPENDENCY' || act.status === 'AWAITING_APPROVAL') {
          act.status = 'CANCELLED';
        }
      }
    }

    executionPersistence.saveGoal(goal);
    executionJournal.appendEvent({
      goalId,
      eventType: 'GOAL_CANCELLED',
      newState: 'CANCELLED',
    });
    this.recordMemoryEvent(goal, 'GOAL_CANCELLED', 'RECORDED', 'Goal cancelled by operator.');
    return true;
  }

  /**
   * Recovers persisted goals from durable storage on restart.
   */
  public recoverPersistedGoals(): GoalRecoveryResult[] {
    const envelope = executionPersistence.loadEnvelope();
    if (envelope && envelope.goals) {
      for (const [gid, g] of Object.entries(envelope.goals)) {
        this.goals.set(gid, g);
      }
      if (envelope.activeGoalId) {
        this.activeGoalId = envelope.activeGoalId;
      }
      if (envelope.observations) {
        for (const [gid, obsList] of Object.entries(envelope.observations)) {
          this.observations.set(gid, obsList);
        }
      }
    }
    const results = recoveryManager.recoverAllGoals();
    for (const res of results) {
      const g = this.goals.get(res.goalId);
      if (g) {
        g.status = res.recoveredStatus as any;
      }
    }
    return results;
  }

  /**
   * Semantic Memory Event Appender with complete provenance.
   */
  private recordMemoryEvent(
    goal: Goal,
    type: string,
    status: 'PLANNED' | 'EXECUTING' | 'EXECUTED' | 'RECORDED',
    summary: string
  ): void {
    const cleanSummary = resultNormalizer.sanitizeText(summary);
    const eventStatus: 'PLANNED' | 'EXECUTED' | 'RECORDED' =
      status === 'EXECUTING' ? 'PLANNED' : status;
    const event: MemoryEvent = {
      id: `EVT-ORCHESTRATOR-${Date.now()}-${Math.floor(Math.random() * 1000)}`,
      type: `INTELLIGENCE_ORCHESTRATOR_${type}`,
      sourceMemoryId: goal.contextRequirements.targetMemoryId,
      sourceMemoryTitle: goal.provenance.sourceMemoryTitle,
      action: 'CREATE_WORKFLOW',
      timestamp: new Date().toISOString(),
      status: eventStatus,
      resultSummary: cleanSummary,
      relatedEntities: [
        'ORCHESTRATOR',
        goal.goalId,
        ...goal.contextRequirements.entityNames,
      ],
      metadata: {
        goalId: goal.goalId,
        goalStatus: goal.status,
        planVersion: goal.currentPlanVersion,
        userIntent: goal.userIntent,
        provenance: goal.provenance,
      },
    };

    actionProposalService.recordMemoryEvent(event);
  }
}

export const goalOrchestrator = new GoalOrchestrator();
