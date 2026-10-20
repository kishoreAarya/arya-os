/**
 * AryaOS V1 — Stage 09: Execution Scheduler Foundation
 *
 * Deterministic, single-runtime task scheduler supporting immediate DAG execution,
 * delayed dispatch, exponential retry backoff, dependency-triggered unblocking,
 * and operator approval continuations.
 */

import { Goal, Plan, ActionNode } from '../types/goalOrchestration';
import { SchedulerJob, SchedulerJobType } from '../types/executionPersistence';
import { executionJournal } from './executionJournal';

export class ExecutionScheduler {
  private activeJobs: Map<string, SchedulerJob> = new Map();
  private timers: Map<string, ReturnType<typeof setTimeout>> = new Map();

  /**
   * Resets scheduler queue and cancels all pending timers (useful for test isolation).
   */
  public resetState(): void {
    for (const timer of this.timers.values()) {
      clearTimeout(timer);
    }
    this.timers.clear();
    this.activeJobs.clear();
  }

  /**
   * Schedules an action for immediate or delayed dispatch.
   */
  public scheduleJob(params: {
    goalId: string;
    planId: string;
    actionId: string;
    type: SchedulerJobType;
    delayMs?: number;
    attempt?: number;
    executeCallback: () => Promise<void>;
  }): SchedulerJob {
    const delay = params.delayMs || 0;
    const jobId = `JOB-${Date.now()}-${params.actionId}-${params.type}`;
    const scheduledFor = new Date(Date.now() + delay).toISOString();

    const job: SchedulerJob = {
      jobId,
      goalId: params.goalId,
      planId: params.planId,
      actionId: params.actionId,
      type: params.type,
      scheduledFor,
      status: 'PENDING',
      attempt: params.attempt || 1,
      backoffMs: delay,
      createdAt: new Date().toISOString(),
    };

    this.activeJobs.set(jobId, job);

    if (delay === 0) {
      // Immediate execution
      job.status = 'RUNNING';
      params
        .executeCallback()
        .then(() => {
          job.status = 'COMPLETED';
        })
        .catch(() => {
          job.status = 'CANCELLED';
        });
    } else {
      // Delayed timer
      const timer = setTimeout(async () => {
        job.status = 'RUNNING';
        try {
          await params.executeCallback();
          job.status = 'COMPLETED';
        } catch {
          job.status = 'CANCELLED';
        } finally {
          this.timers.delete(jobId);
        }
      }, delay);

      this.timers.set(jobId, timer);
    }

    return job;
  }

  /**
   * Schedules a retry with backoff according to action retry policy.
   */
  public scheduleRetry(
    action: ActionNode,
    attempt: number,
    baseBackoffMs: number,
    executeCallback: () => Promise<void>
  ): SchedulerJob {
    // Exponential backoff with jitter
    const delayMs = Math.min(baseBackoffMs * Math.pow(2, attempt - 1), 30000);

    executionJournal.appendEvent({
      goalId: action.goalId,
      planId: action.planId,
      actionId: action.actionId,
      eventType: 'ACTION_READY',
      previousState: 'FAILED',
      newState: 'READY',
      payload: {
        scheduledRetryAttempt: attempt,
        delayMs,
      },
    });

    return this.scheduleJob({
      goalId: action.goalId,
      planId: action.planId,
      actionId: action.actionId,
      type: 'RETRY_BACKOFF',
      delayMs,
      attempt,
      executeCallback,
    });
  }

  /**
   * Evaluates downstream actions when an action succeeds, triggering ready dependents.
   */
  public onDependencySatisfied(
    plan: Plan,
    succeededActionId: string,
    executeCallback: (action: ActionNode) => Promise<void>
  ): ActionNode[] {
    const unblocked: ActionNode[] = [];

    for (const action of plan.actions) {
      if (action.status !== 'WAITING_DEPENDENCY') continue;

      const deps = action.dependencies;
      if (!deps.includes(succeededActionId)) continue;

      // Check if ALL dependencies are now satisfied
      const allMet = deps.every((depId) => {
        const dep = plan.actions.find((a) => a.actionId === depId);
        return dep && dep.status === 'SUCCEEDED';
      });

      if (allMet) {
        if (action.approvalRequirement.required && !action.approvalRequirement.approvedAt) {
          action.status = 'AWAITING_APPROVAL';
        } else {
          action.status = 'READY';
          unblocked.push(action);
          this.scheduleJob({
            goalId: action.goalId,
            planId: action.planId,
            actionId: action.actionId,
            type: 'DEPENDENCY_TRIGGERED',
            delayMs: 0,
            executeCallback: () => executeCallback(action),
          });
        }
      }
    }

    return unblocked;
  }

  /**
   * Cancels a pending scheduled job.
   */
  public cancelJob(jobId: string): boolean {
    const timer = this.timers.get(jobId);
    if (timer) {
      clearTimeout(timer);
      this.timers.delete(jobId);
    }

    const job = this.activeJobs.get(jobId);
    if (job && job.status === 'PENDING') {
      job.status = 'CANCELLED';
      return true;
    }
    return false;
  }

  /**
   * Returns all active scheduled jobs.
   */
  public getPendingJobs(): SchedulerJob[] {
    return Array.from(this.activeJobs.values()).filter((j) => j.status === 'PENDING');
  }
}

export const executionScheduler = new ExecutionScheduler();
