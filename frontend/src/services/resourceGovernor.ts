/**
 * AryaOS V1 — Stage 10: Resource Governor & Intelligence Economy Engine
 *
 * Enforces strict financial, token, concurrency, and temporal limits across all autonomous work:
 * - Preflight financial budget verification
 * - Truthful cost accounting without fabricated pricing (missing cost is recorded as UNKNOWN)
 * - Single-runtime lease tracking for concurrent actions and agents
 * - Deadline feasibility checks triggering ROUTE_RECONSIDERATION_REQUIRED
 */

import {
  ResourceBudget,
  ResourceLease,
  GovernanceCheckResult,
  AgentTask,
  AgentProfile,
} from '../types/agentCoordination';

export const DEFAULT_RESOURCE_BUDGET: ResourceBudget = {
  maxConcurrentActions: 3,
  maxConcurrentAgents: 4,
  maxRetries: 2,
};

class ResourceGovernor {
  private activeLeases: Map<string, ResourceLease> = new Map(); // leaseId -> lease
  private goalBudgets: Map<string, ResourceBudget> = new Map(); // goalId -> budget
  private goalCosts: Map<string, { cost: number; isPartial: boolean }> = new Map(); // goalId -> tracking
  private goalTokenUsage: Map<string, number> = new Map(); // goalId -> total tokens

  constructor() {
    this.resetState();
  }

  public resetState(): void {
    this.activeLeases.clear();
    this.goalBudgets.clear();
    this.goalCosts.clear();
    this.goalTokenUsage.clear();
  }

  public setGoalBudget(goalId: string, budget: Partial<ResourceBudget>): void {
    const existing = this.goalBudgets.get(goalId) || { ...DEFAULT_RESOURCE_BUDGET };
    this.goalBudgets.set(goalId, { ...existing, ...budget });
  }

  public getGoalBudget(goalId: string): ResourceBudget {
    return this.goalBudgets.get(goalId) || { ...DEFAULT_RESOURCE_BUDGET };
  }

  public getGoalCostTracking(goalId: string): {
    costSoFar: number;
    costStatus: 'KNOWN' | 'UNKNOWN' | 'PARTIALLY_KNOWN';
    remainingBudget: number | null;
  } {
    const tracking = this.goalCosts.get(goalId) || { cost: 0, isPartial: false };
    const budget = this.getGoalBudget(goalId);

    let status: 'KNOWN' | 'UNKNOWN' | 'PARTIALLY_KNOWN' = 'KNOWN';
    if (tracking.isPartial && tracking.cost > 0) {
      status = 'PARTIALLY_KNOWN';
    } else if (tracking.isPartial && tracking.cost === 0) {
      status = 'UNKNOWN';
    }

    const remainingBudget =
      budget.maxCostUsd !== undefined ? Math.max(0, budget.maxCostUsd - tracking.cost) : null;

    return {
      costSoFar: Number(tracking.cost.toFixed(4)),
      costStatus: status,
      remainingBudget: remainingBudget !== null ? Number(remainingBudget.toFixed(4)) : null,
    };
  }

  /**
   * Preflight budget evaluation prior to dispatch.
   */
  public checkBudgetPreflight(goalId: string, estimatedCostUsd?: number | null): GovernanceCheckResult {
    const budget = this.getGoalBudget(goalId);
    if (budget.maxCostUsd === undefined) {
      return { allowed: true };
    }

    const current = this.goalCosts.get(goalId)?.cost || 0;
    const est = estimatedCostUsd ?? 0;

    if (current + est > budget.maxCostUsd) {
      return {
        allowed: false,
        reason: 'RESOURCE_BUDGET_EXCEEDED',
        details: `Goal cost limit of $${budget.maxCostUsd} would be exceeded (current: $${current.toFixed(4)}, estimated addition: $${est.toFixed(4)}).`,
      };
    }

    return { allowed: true };
  }

  /**
   * Deadline feasibility evaluation.
   */
  public checkDeadlineFeasibility(task: AgentTask, estimatedLatencyMs: number): GovernanceCheckResult {
    if (!task.deadline) {
      return { allowed: true };
    }

    const deadlineTime = new Date(task.deadline).getTime();
    const predictedCompletion = Date.now() + estimatedLatencyMs;

    if (predictedCompletion > deadlineTime) {
      return {
        allowed: false,
        reason: 'ROUTE_RECONSIDERATION_REQUIRED',
        details: `Task '${task.taskId}' estimated completion in ${estimatedLatencyMs}ms would violate deadline ${task.deadline}.`,
      };
    }

    return { allowed: true };
  }

  /**
   * Requests a single-runtime execution lease.
   */
  public acquireLease(
    goalId: string,
    task: AgentTask,
    agent: AgentProfile,
    providerId?: string
  ): { allowed: boolean; lease?: ResourceLease; failureReason?: string; checkResult?: GovernanceCheckResult } {
    const budget = this.getGoalBudget(goalId);

    // 1. Check preflight cost
    const budgetCheck = this.checkBudgetPreflight(goalId, task.estimatedCost.maxUsd);
    if (!budgetCheck.allowed) {
      return { allowed: false, failureReason: budgetCheck.details, checkResult: budgetCheck };
    }

    // 2. Check deadline feasibility
    const deadlineCheck = this.checkDeadlineFeasibility(task, task.estimatedLatency);
    if (!deadlineCheck.allowed) {
      return { allowed: false, failureReason: deadlineCheck.details, checkResult: deadlineCheck };
    }

    // 3. Check global concurrent actions
    const currentGoalActions = Array.from(this.activeLeases.values()).filter((l) => l.goalId === goalId);
    if (currentGoalActions.length >= budget.maxConcurrentActions) {
      return {
        allowed: false,
        failureReason: `Max concurrent actions limit (${budget.maxConcurrentActions}) reached for goal.`,
        checkResult: {
          allowed: false,
          reason: 'CONCURRENCY_LIMIT_REACHED',
          details: `Max concurrent actions limit (${budget.maxConcurrentActions}) reached.`,
        },
      };
    }

    // 4. Check distinct active agents for goal
    const activeAgentIds = new Set(currentGoalActions.map((l) => l.agentId));
    if (!activeAgentIds.has(agent.agentId) && activeAgentIds.size >= budget.maxConcurrentAgents) {
      return {
        allowed: false,
        failureReason: `Max concurrent agents limit (${budget.maxConcurrentAgents}) reached for goal.`,
        checkResult: {
          allowed: false,
          reason: 'CONCURRENCY_LIMIT_REACHED',
          details: `Max concurrent agents limit (${budget.maxConcurrentAgents}) reached.`,
        },
      };
    }

    // 5. Check per-agent concurrency limit
    const agentLeases = Array.from(this.activeLeases.values()).filter((l) => l.agentId === agent.agentId);
    if (agentLeases.length >= agent.concurrencyLimit) {
      return {
        allowed: false,
        failureReason: `Agent '${agent.name}' concurrency limit (${agent.concurrencyLimit}) saturated.`,
        checkResult: {
          allowed: false,
          reason: 'CONCURRENCY_LIMIT_REACHED',
          details: `Agent concurrency limit (${agent.concurrencyLimit}) saturated.`,
        },
      };
    }

    // Grant lease
    const now = Date.now();
    const lease: ResourceLease = {
      leaseId: `LEASE-${now}-${Math.floor(Math.random() * 10000)}`,
      goalId,
      taskId: task.taskId,
      agentId: agent.agentId,
      providerId,
      grantedAt: new Date(now).toISOString(),
      expiresAt: new Date(now + Math.max(30000, task.estimatedLatency * 2)).toISOString(),
      estimatedCost: task.estimatedCost.maxUsd,
      estimatedTokens: 1500,
    };

    this.activeLeases.set(lease.leaseId, lease);

    return { allowed: true, lease };
  }

  /**
   * Releases an active lease and commits actual financial & token expenditure.
   */
  public releaseLease(
    leaseId: string,
    actualCostUsd?: number | 'UNKNOWN' | null,
    actualTokens?: number
  ): void {
    const lease = this.activeLeases.get(leaseId);
    if (!lease) return;

    this.activeLeases.delete(leaseId);

    // Update goal cost tracking truthful accounting
    const current = this.goalCosts.get(lease.goalId) || { cost: 0, isPartial: false };

    if (typeof actualCostUsd === 'number') {
      current.cost += actualCostUsd;
    } else {
      current.isPartial = true;
    }
    this.goalCosts.set(lease.goalId, current);

    // Update token usage
    if (actualTokens) {
      const prevTokens = this.goalTokenUsage.get(lease.goalId) || 0;
      this.goalTokenUsage.set(lease.goalId, prevTokens + actualTokens);
    }
  }

  public getActiveLeases(): ResourceLease[] {
    return Array.from(this.activeLeases.values());
  }
}

export const resourceGovernor = new ResourceGovernor();
