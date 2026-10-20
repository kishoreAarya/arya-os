/**
 * AryaOS V1 — Stage 08: Goal Orchestration React Hook
 *
 * Connects the Goal Orchestration Engine to spatial UI components,
 * providing reactive updates for goal lifecycle, active plan, DAG action status,
 * observations, and operator controls.
 */

import { useState, useCallback, useEffect } from 'react';
import {
  Goal,
  Plan,
  ActionNode,
  Observation,
  GoalExecutionOptions,
} from '../types/goalOrchestration';
import { goalOrchestrator } from '../services/goalOrchestrator';
import { agentCoordinator } from '../services/agentCoordinator';
import { AgentOperationalTelemetry, AgentTask } from '../types/agentCoordination';

export interface UseGoalOrchestrationReturn {
  activeGoal: Goal | null;
  activePlan: Plan | null;
  actions: ActionNode[];
  observations: Observation[];
  isExecuting: boolean;
  needsApproval: boolean;
  isRecovered: boolean;
  recoverySummary: string | null;
  currentAction: ActionNode | null;
  agentTelemetry: AgentOperationalTelemetry;
  agentTasks: AgentTask[];

  startGoal: (
    userIntent: string,
    targetMemoryId?: string,
    options?: GoalExecutionOptions
  ) => Promise<Goal>;
  approveAction: (actionId: string) => Promise<boolean>;
  rejectAction: (actionId: string, reason: string) => boolean;
  pauseGoal: () => boolean;
  resumeGoal: () => Promise<boolean>;
  cancelGoal: () => boolean;
  recoverGoals: () => void;
  refreshState: () => void;
}

export function useGoalOrchestration(): UseGoalOrchestrationReturn {
  const [activeGoal, setActiveGoal] = useState<Goal | null>(() => goalOrchestrator.getActiveGoal());
  const [activePlan, setActivePlan] = useState<Plan | null>(() => {
    const g = goalOrchestrator.getActiveGoal();
    return g?.plans.find((p) => p.planId === g.currentPlanId) || null;
  });
  const [observations, setObservations] = useState<Observation[]>(() => {
    const g = goalOrchestrator.getActiveGoal();
    return g ? goalOrchestrator.getObservationsForGoal(g.goalId) : [];
  });
  const [isRecovered, setIsRecovered] = useState<boolean>(false);
  const [recoverySummary, setRecoverySummary] = useState<string | null>(null);
  const [agentTelemetry, setAgentTelemetry] = useState<AgentOperationalTelemetry>(() =>
    agentCoordinator.getTelemetry()
  );
  const [agentTasks, setAgentTasks] = useState<AgentTask[]>(() =>
    agentCoordinator.getAllTasks()
  );

  useEffect(() => {
    // Automatic crash recovery check on mount
    const results = goalOrchestrator.recoverPersistedGoals();
    if (results.length > 0) {
      setIsRecovered(true);
      setRecoverySummary(results.map((r) => r.summary).join(' | '));
      const g = goalOrchestrator.getActiveGoal();
      setActiveGoal(g ? { ...g } : null);
      if (g) {
        const p = g.plans.find((plan) => plan.planId === g.currentPlanId);
        setActivePlan(p ? { ...p } : null);
        setObservations([...goalOrchestrator.getObservationsForGoal(g.goalId)]);
      }
    }
  }, []);

  const refreshState = useCallback(() => {
    const g = goalOrchestrator.getActiveGoal();
    setActiveGoal(g ? { ...g } : null);
    if (g) {
      const p = g.plans.find((plan) => plan.planId === g.currentPlanId);
      setActivePlan(p ? { ...p } : null);
      setObservations([...goalOrchestrator.getObservationsForGoal(g.goalId)]);
    } else {
      setActivePlan(null);
      setObservations([]);
    }
    setAgentTelemetry(agentCoordinator.getTelemetry(g?.goalId));
    setAgentTasks(agentCoordinator.getAllTasks());
  }, []);

  const startGoal = useCallback(
    async (
      userIntent: string,
      targetMemoryId?: string,
      options: GoalExecutionOptions = {}
    ): Promise<Goal> => {
      const g = await goalOrchestrator.createAndExecuteGoal(userIntent, targetMemoryId, {
        ...options,
        onGoalProgress: () => {
          refreshState();
        },
      });
      refreshState();
      return g;
    },
    [refreshState]
  );

  const approveAction = useCallback(
    async (actionId: string): Promise<boolean> => {
      if (!activeGoal) return false;
      const res = await goalOrchestrator.approveAction(activeGoal.goalId, actionId);
      refreshState();
      return res;
    },
    [activeGoal, refreshState]
  );

  const rejectAction = useCallback(
    (actionId: string, reason: string): boolean => {
      if (!activeGoal) return false;
      const res = goalOrchestrator.rejectAction(activeGoal.goalId, actionId, reason);
      refreshState();
      return res;
    },
    [activeGoal, refreshState]
  );

  const pauseGoal = useCallback((): boolean => {
    if (!activeGoal) return false;
    const res = goalOrchestrator.pauseGoal(activeGoal.goalId);
    refreshState();
    return res;
  }, [activeGoal, refreshState]);

  const resumeGoal = useCallback(async (): Promise<boolean> => {
    if (!activeGoal) return false;
    const res = await goalOrchestrator.resumeGoal(activeGoal.goalId);
    refreshState();
    return res;
  }, [activeGoal, refreshState]);

  const cancelGoal = useCallback((): boolean => {
    if (!activeGoal) return false;
    const res = goalOrchestrator.cancelGoal(activeGoal.goalId);
    refreshState();
    return res;
  }, [activeGoal, refreshState]);

  const recoverGoals = useCallback(() => {
    const results = goalOrchestrator.recoverPersistedGoals();
    if (results.length > 0) {
      setIsRecovered(true);
      setRecoverySummary(results.map((r) => r.summary).join(' | '));
      refreshState();
    }
  }, [refreshState]);

  const actions = activePlan?.actions || [];
  const isExecuting = activeGoal?.status === 'EXECUTING';
  const needsApproval = activeGoal?.status === 'AWAITING_APPROVAL';
  const currentAction = actions.find((a) => a.status === 'EXECUTING' || a.status === 'AWAITING_APPROVAL') || null;

  return {
    activeGoal,
    activePlan,
    actions,
    observations,
    isExecuting,
    needsApproval,
    isRecovered,
    recoverySummary,
    currentAction,
    agentTelemetry,
    agentTasks,
    startGoal,
    approveAction,
    rejectAction,
    pauseGoal,
    resumeGoal,
    cancelGoal,
    recoverGoals,
    refreshState,
  };
}
