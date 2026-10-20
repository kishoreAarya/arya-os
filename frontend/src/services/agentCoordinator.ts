/**
 * AryaOS V1 — Stage 10: Multi-Agent Coordinator
 *
 * Deterministically orchestrates specialized worker agents:
 * - Scores agent compatibility using measurable criteria (capabilities, workload, trust, history)
 * - Assigns AgentTasks to optimal workers
 * - Enforces resource leases through ResourceGovernor
 * - Enforces shared memory locks through MemoryLockManager
 * - Dispatches provider tasks strictly through Stage 07 ExecutionGateway
 * - Verifies outputs through Objective QualityGate
 * - Aggregates results and returns normalized observations to Stage 08 Orchestration
 */

import { ActionNode, Goal, Observation, ProducedArtifact } from '../types/goalOrchestration';
import {
  AgentProfile,
  AgentTask,
  AgentTaskStatus,
  AggregatedAgentResult,
  AgentOperationalTelemetry,
  TaskMemoryAccessDeclaration,
} from '../types/agentCoordination';
import { ActionProposal } from '../types/spatialCommand';
import { agentRegistry } from './agentRegistry';
import { resourceGovernor } from './resourceGovernor';
import { memoryLockManager } from './memoryLockManager';
import { agentConflictManager } from './agentConflictManager';
import { qualityGate } from './qualityGate';
import { agentResultAggregator } from './agentResultAggregator';
import { providerRouter } from './providerRouter';
import { executionGateway } from './executionGateway';
import { executionPersistence } from './executionPersistence';
import { executionJournal } from './executionJournal';

class AgentCoordinator {
  private activeTasks: Map<string, AgentTask> = new Map(); // taskId -> AgentTask
  private completedTasks: Map<string, AgentTask> = new Map();
  private failedTasks: Map<string, AgentTask> = new Map();
  private taskResults: Map<string, AggregatedAgentResult> = new Map();

  constructor() {
    this.resetState();
  }

  public resetState(): void {
    this.activeTasks.clear();
    this.completedTasks.clear();
    this.failedTasks.clear();
    this.taskResults.clear();
    agentRegistry.resetRegistry();
    resourceGovernor.resetState();
    memoryLockManager.resetState();
    agentConflictManager.resetState();
  }

  public getTask(taskId: string): AgentTask | undefined {
    return (
      this.activeTasks.get(taskId) ||
      this.completedTasks.get(taskId) ||
      this.failedTasks.get(taskId)
    );
  }

  public getActiveTasks(): AgentTask[] {
    return Array.from(this.activeTasks.values());
  }

  public getAllTasks(): AgentTask[] {
    return [
      ...Array.from(this.activeTasks.values()),
      ...Array.from(this.completedTasks.values()),
      ...Array.from(this.failedTasks.values()),
    ];
  }

  /**
   * Deterministically scores and selects the optimal agent for a given action.
   */
  public selectBestAgent(action: ActionNode): AgentProfile | undefined {
    const candidates = agentRegistry.getAgentsForCapability(action.requiredCapability);
    if (candidates.length === 0) return undefined;

    // Filter by available concurrency slot
    const available = candidates.filter((c) => c.currentWorkload < c.concurrencyLimit);
    if (available.length === 0) return undefined;

    // Deterministic scoring
    const scored = available.map((agent) => {
      let score = 0;
      // 1. Primary capability match bonus (+10)
      if (agent.capabilities.includes(action.requiredCapability)) {
        score += 10;
      }

      // 2. Trust Level Bonus (+5 for AUTONOMOUS, +3 for VERIFIED)
      if (agent.trustLevel === 'AUTONOMOUS') score += 5;
      else if (agent.trustLevel === 'VERIFIED') score += 3;

      // 3. Workload balancing: reward lower utilization (+4 for empty, +2 for partial)
      const workloadRatio = agent.currentWorkload / agent.concurrencyLimit;
      score += Math.round((1 - workloadRatio) * 4);

      // 4. Historical success bonus
      const totalHistory = agent.historicalSuccessCount + agent.historicalFailureCount;
      if (totalHistory > 0) {
        const rate = agent.historicalSuccessCount / totalHistory;
        score += Math.round(rate * 3);
      }

      return { agent, score };
    });

    scored.sort((a, b) => b.score - a.score);
    return scored[0]?.agent;
  }

  /**
   * Translates an ActionNode into a managed AgentTask and assigns an agent.
   */
  public assignAgentForAction(
    action: ActionNode,
    goal: Goal
  ): { assigned: boolean; agent?: AgentProfile; task?: AgentTask; failureReason?: string } {
    const agent = this.selectBestAgent(action);
    if (!agent) {
      return {
        assigned: false,
        failureReason: `No available worker agent matches capability '${action.requiredCapability}' with concurrency capacity.`,
      };
    }

    // Determine memory access declarations
    const memoryAccessDeclarations: TaskMemoryAccessDeclaration[] = [];
    if (goal.contextRequirements.targetMemoryId) {
      const isMutation =
        action.approvalRequirement.riskLevel === 'CONSEQUENTIAL' ||
        action.approvalRequirement.riskLevel === 'EXTERNAL_SIDE_EFFECT';
      memoryAccessDeclarations.push({
        memoryId: goal.contextRequirements.targetMemoryId,
        accessType: isMutation ? 'WRITE' : 'READ',
      });
    }

    const taskId = `TASK-${action.actionId}`;
    const task: AgentTask = {
      taskId,
      goalId: goal.goalId,
      planId: action.planId,
      planVersion: goal.currentPlanVersion,
      parentActionId: action.actionId,
      assignedAgentId: agent.agentId,
      capability: action.requiredCapability,
      contextReferences: goal.contextRequirements.contextMemories,
      inputContract: action.inputs,
      expectedOutputContract: {},
      priority: goal.priority,
      riskLevel: action.approvalRequirement.riskLevel,
      estimatedCost: { minUsd: null, maxUsd: 0.05, currency: 'USD' },
      estimatedLatency: 1500,
      status: 'ASSIGNED',
      qualityRequirement:
        action.approvalRequirement.riskLevel === 'CONSEQUENTIAL'
          ? 'QUALITY_HIGH'
          : 'QUALITY_STANDARD',
      memoryAccessDeclarations,
      createdAt: new Date().toISOString(),
      updatedAt: new Date().toISOString(),
    };

    // Update state
    this.activeTasks.set(taskId, task);
    agentRegistry.updateAgentWorkload(agent.agentId, 1);

    // Save to persistence & journal
    executionJournal.appendEvent({
      goalId: goal.goalId,
      planId: action.planId,
      planVersion: goal.currentPlanVersion,
      actionId: action.actionId,
      eventType: 'ACTION_SCHEDULED',
      payload: {
        taskId,
        assignedAgent: agent.agentId,
        agentRole: agent.role,
        capability: action.requiredCapability,
      },
    });

    return { assigned: true, agent, task };
  }

  /**
   * Executes an assigned AgentTask end-to-end through the governance, locking,
   * gateway, quality, and aggregation layers.
   */
  public async executeTask(
    task: AgentTask,
    goal: Goal,
    signal?: AbortSignal
  ): Promise<{
    success: boolean;
    aggregatedResult?: AggregatedAgentResult;
    observation?: Observation;
    failureReason?: string;
  }> {
    const agent = agentRegistry.getAgent(task.assignedAgentId || '');
    if (!agent) {
      return { success: false, failureReason: `Assigned agent '${task.assignedAgentId}' not found.` };
    }

    task.status = 'RUNNING';
    task.updatedAt = new Date().toISOString();

    // 1. Acquire Resource Lease
    const leaseResult = resourceGovernor.acquireLease(goal.goalId, task, agent);
    if (!leaseResult.allowed || !leaseResult.lease) {
      task.status = 'BLOCKED';
      this.failedTasks.set(task.taskId, task);
      this.activeTasks.delete(task.taskId);
      agentRegistry.updateAgentWorkload(agent.agentId, -1);

      executionJournal.appendEvent({
        goalId: goal.goalId,
        actionId: task.parentActionId,
        eventType: 'ACTION_FAILED',
        payload: { reason: leaseResult.failureReason },
      });

      return {
        success: false,
        failureReason: leaseResult.failureReason || 'Resource governance rejected lease.',
      };
    }
    const lease = leaseResult.lease;

    // 2. Acquire Shared Memory Locks
    const lockResult = memoryLockManager.acquireLocks(
      task.taskId,
      agent.agentId,
      task.memoryAccessDeclarations
    );

    if (!lockResult.acquired) {
      resourceGovernor.releaseLease(lease.leaseId);
      agentRegistry.updateAgentWorkload(agent.agentId, -1);
      task.status = 'BLOCKED';
      this.failedTasks.set(task.taskId, task);
      this.activeTasks.delete(task.taskId);

      // Register conflict
      agentConflictManager.recordConflict({
        goalId: goal.goalId,
        category: 'MEMORY_WRITE_CONFLICT',
        conflictingTaskIds: [task.taskId, ...lockResult.conflictingLocks.map((l) => l.ownerTaskId)],
        conflictingAgentIds: [agent.agentId, ...lockResult.conflictingLocks.map((l) => l.ownerAgentId)],
        resourceOrMemoryId: lockResult.conflictingLocks[0]?.memoryId,
        description: lockResult.failureReason || 'Concurrent memory write lock conflict detected.',
        provenanceRecords: lockResult.conflictingLocks.map((l) => ({ ...l })),
      });

      return {
        success: false,
        failureReason: lockResult.failureReason || 'Memory lock conflict.',
      };
    }

    try {
      // 3. Create Execution Proposal and Plan via Provider Router (Stage 06)
      const proposal: ActionProposal = {
        id: task.parentActionId,
        actionClass: task.capability === 'RESEARCH' ? 'RESEARCH' : 'CREATE_WORKFLOW',
        title: `Task ${task.taskId} by ${agent.name}`,
        description: `Autonomous execution by ${agent.name} (${agent.role})`,
        sourceMemoryId: goal.contextRequirements.targetMemoryId,
        sourceMemoryTitle: goal.provenance.sourceMemoryTitle,
        contextSummary: {
          relatedCount: goal.contextRequirements.contextMemories.length,
          entitiesCount: goal.contextRequirements.entityNames.length,
          decisionsCount: 1,
        },
        payload: task.inputContract,
        executionType: 'BACKEND_ADAPTER',
        status: 'PROPOSED',
        createdAt: new Date().toISOString(),
      };

      const executionPlan = providerRouter.createExecutionPlan(proposal);
      executionPlan.capability = task.capability;

      // 4. Dispatch exclusively via Stage 07 Execution Gateway
      const executionResult = await executionGateway.execute(executionPlan, undefined, { signal });

      // 5. Objective Quality Gate Verification (Stage 10)
      const qualityCheck = qualityGate.evaluate(
        task,
        executionResult.sanitizedOutput || executionResult.output,
        executionResult.structuredOutput,
        executionResult.latencyMs
      );

      // 6. Aggregate Result (Stage 10)
      const aggregatedResult = agentResultAggregator.aggregateSingle(
        task,
        agent,
        executionResult,
        qualityCheck.humanReviewRequired ? 'HUMAN_REVIEW_REQUIRED' : 'SINGLE_RESULT'
      );

      const isOverallSuccess =
        (executionResult.status === 'SUCCEEDED' ||
          executionResult.status === 'FALLBACK_SUCCEEDED') &&
        qualityCheck.passed;

      task.status = isOverallSuccess ? 'SUCCEEDED' : 'FAILED';
      task.updatedAt = new Date().toISOString();

      if (isOverallSuccess) {
        this.completedTasks.set(task.taskId, task);
        agentRegistry.recordAgentTelemetry(agent.agentId, true);
      } else {
        this.failedTasks.set(task.taskId, task);
        agentRegistry.recordAgentTelemetry(agent.agentId, false);
      }
      this.activeTasks.delete(task.taskId);
      this.taskResults.set(task.taskId, aggregatedResult);

      // 7. Synthesize Stage 08 Normalized Observation
      const producedArtifacts: ProducedArtifact[] = [];
      if (isOverallSuccess && aggregatedResult.output) {
        producedArtifacts.push({
          id: `ART-${task.taskId}`,
          type: 'AGENT_SYNTHESIS',
          name: `${agent.name} Output`,
          content: aggregatedResult.output,
        });
      }

      const observation: Observation = {
        observationId: `OBS-${Date.now()}-${Math.floor(Math.random() * 1000)}`,
        goalId: goal.goalId,
        planId: task.planId,
        actionId: task.parentActionId,
        executionId: aggregatedResult.executionId,
        status: isOverallSuccess ? 'SUCCESS' : 'FAILURE',
        resultSummary: isOverallSuccess
          ? `Task completed by ${agent.name} via ${aggregatedResult.providerId} in ${aggregatedResult.latencyMs}ms.`
          : qualityCheck.issues.join('; ') || executionResult.error || 'Execution failed',
        producedArtifacts,
        providerId: aggregatedResult.providerId,
        modelId: executionResult.modelId,
        latencyMs: aggregatedResult.latencyMs,
        failureReason: isOverallSuccess ? undefined : qualityCheck.issues.join('; ') || executionResult.error,
        confidence: isOverallSuccess ? 0.95 : 0.1,
        downstreamImplications: isOverallSuccess
          ? [`Unblocks downstream dependencies for ${task.parentActionId}`]
          : [`Blocks downstream dependents of ${task.parentActionId}`],
        memoryReferences: goal.contextRequirements.contextMemories,
        timestamp: new Date().toISOString(),
      };

      // 8. Release Leases and Locks
      const actualCost =
        typeof aggregatedResult.actualCostUsd === 'number'
          ? aggregatedResult.actualCostUsd
          : null;
      resourceGovernor.releaseLease(lease.leaseId, actualCost);
      memoryLockManager.releaseLocksForTask(task.taskId);
      agentRegistry.updateAgentWorkload(agent.agentId, -1);

      return {
        success: isOverallSuccess,
        aggregatedResult,
        observation,
        failureReason: isOverallSuccess ? undefined : observation.failureReason,
      };
    } catch (err: unknown) {
      resourceGovernor.releaseLease(lease.leaseId);
      memoryLockManager.releaseLocksForTask(task.taskId);
      agentRegistry.updateAgentWorkload(agent.agentId, -1);
      task.status = 'FAILED';
      this.failedTasks.set(task.taskId, task);
      this.activeTasks.delete(task.taskId);

      const errMessage = err instanceof Error ? err.message : String(err);
      return { success: false, failureReason: errMessage };
    }
  }

  /**
   * Compiles live operational telemetry across multi-agent activities.
   */
  public getTelemetry(goalId?: string): AgentOperationalTelemetry {
    const allAgents = agentRegistry.getAllAgents();
    const activeAgents = allAgents.filter((a) => a.currentWorkload > 0).length;

    const allTasks = this.getAllTasks();
    const filteredTasks = goalId ? allTasks.filter((t) => t.goalId === goalId) : allTasks;

    const queuedTasks = filteredTasks.filter((t) => t.status === 'ASSIGNED' || t.status === 'WAITING').length;
    const runningTasks = filteredTasks.filter((t) => t.status === 'RUNNING').length;
    const completedTasks = filteredTasks.filter((t) => t.status === 'SUCCEEDED').length;
    const failedTasks = filteredTasks.filter((t) => t.status === 'FAILED').length;

    const completedResults = Array.from(this.taskResults.values()).filter(
      (r) => !goalId || r.goalId === goalId
    );
    const totalLatency = completedResults.reduce((acc, r) => acc + r.latencyMs, 0);
    const averageLatencyMs =
      completedResults.length > 0 ? Math.round(totalLatency / completedResults.length) : 0;

    const costTracking = goalId
      ? resourceGovernor.getGoalCostTracking(goalId)
      : { costSoFar: 0, costStatus: 'KNOWN' as const };

    const activeLeases = resourceGovernor.getActiveLeases();
    const activeLocks = memoryLockManager.getActiveLocks();
    const conflicts = goalId
      ? agentConflictManager.getConflictsForGoal(goalId)
      : agentConflictManager.getAllConflicts();

    const maxConcurrency = 3;
    const concurrencyUtilization = Math.min(1, runningTasks / maxConcurrency);

    return {
      activeAgents,
      queuedTasks,
      runningTasks,
      completedTasks,
      failedTasks,
      averageLatencyMs,
      cumulativeCostUsd: costTracking.costSoFar,
      costStatus: costTracking.costStatus,
      concurrencyUtilization: Number(concurrencyUtilization.toFixed(2)),
      conflictCount: conflicts.length,
      replanCount: 0,
      approvalCount: 0,
      activeLeasesCount: activeLeases.length,
      activeLocksCount: activeLocks.length,
    };
  }
}

export const agentCoordinator = new AgentCoordinator();
