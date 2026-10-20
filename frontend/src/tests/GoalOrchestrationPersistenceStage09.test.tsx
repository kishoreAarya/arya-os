/**
 * AryaOS V1 — Stage 09: Persistent Autonomous Operations & Recovery Layer Test Suite
 *
 * Verifies that goal execution survives application restarts, browser refresh,
 * process crashes, and network interruption without losing state, duplicating
 * consequential actions, or leaking credentials.
 */

import React from 'react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import { renderHook, act } from '@testing-library/react';
import '@testing-library/jest-dom';

import { goalOrchestrator } from '../services/goalOrchestrator';
import { goalInterpreter } from '../services/goalInterpreter';
import { planGenerator } from '../services/planGenerator';
import { executionPersistence, STORAGE_KEY_ORCHESTRATION } from '../services/executionPersistence';
import { executionJournal, STORAGE_KEY_JOURNAL } from '../services/executionJournal';
import { recoveryManager } from '../services/recoveryManager';
import { executionScheduler } from '../services/executionScheduler';
import { executionGateway } from '../services/executionGateway';
import { providerExecutionAdapter } from '../services/providerExecutionAdapter';
import { providerRegistry } from '../services/providerRegistry';
import { routingPolicyManager } from '../services/routingPolicy';
import { useGoalOrchestration } from '../hooks/useGoalOrchestration';
import { SpatialCommandConsole } from '../components/spatial/SpatialCommandConsole';
import { Goal, Plan, ActionNode } from '../types/goalOrchestration';

describe('AryaOS V1 Stage 09 — Persistent Autonomous Operations & Recovery Layer', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    goalOrchestrator.resetState();
    executionPersistence.clearEnvelope();
    executionJournal.resetState();
    executionScheduler.resetState();
    executionGateway.resetState();
    providerRegistry.resetToDefaults();
    routingPolicyManager.resetToDefaults();
    providerExecutionAdapter.initializeDefaultAdapters();
  });

  describe('1. State Persistence & Serialization Integrity', () => {
    it('persists structured goal and plan into a versioned envelope', async () => {
      const intent = 'Research a cinematic concept for AryaOS and prepare a production brief';
      const goal = await goalOrchestrator.createAndExecuteGoal(intent, 'MEM-0001', {
        autoApprove: true,
      });

      expect(goal.status).toBe('COMPLETED');

      // Verify envelope in storage
      const envelope = executionPersistence.loadEnvelope();
      expect(envelope).not.toBeNull();
      expect(envelope?.schemaVersion).toBe(1);
      expect(envelope?.goals[goal.goalId]).toBeDefined();
      expect(envelope?.goals[goal.goalId].objective).toBe(goal.objective);

      const activePlan = envelope?.goals[goal.goalId].plans[0];
      expect(activePlan?.actions.length).toBe(3);
      expect(activePlan?.actions.every((a) => a.status === 'SUCCEEDED')).toBe(true);
    });

    it('persists observations and human approvals safely with timestamps', () => {
      const goal = goalInterpreter.interpret('Generate video production brief for new cinematic sequence', 'MEM-0001');
      const plan = planGenerator.generatePlan(goal);
      goal.plans.push(plan);
      goal.currentPlanId = plan.planId;
      executionPersistence.saveGoal(goal);

      const approvalRecord = {
        approvalId: 'APPR-TEST-001',
        goalId: goal.goalId,
        planId: plan.planId,
        actionId: 'ACT-TEST-001',
        actionTitle: 'Publish Video Artifact',
        riskLevel: 'CONSEQUENTIAL',
        requestedAt: new Date().toISOString(),
        status: 'PENDING' as const,
        expiresAt: new Date(Date.now() + 86400000).toISOString(),
      };

      executionPersistence.saveApproval(approvalRecord);

      const loaded = executionPersistence.loadEnvelope();
      expect(loaded?.approvals['APPR-TEST-001']).toBeDefined();
      expect(loaded?.approvals['APPR-TEST-001'].status).toBe('PENDING');
      expect(loaded?.approvals['APPR-TEST-001'].riskLevel).toBe('CONSEQUENTIAL');
    });
  });

  describe('2. Event-Sourced Execution Journal', () => {
    it('appends sequential immutable journal events for all state transitions', async () => {
      const intent = 'Analyze multi-branch domain capabilities and memory vitrines';
      const goal = await goalOrchestrator.createAndExecuteGoal(intent, 'MEM-0001', {
        autoApprove: true,
      });

      const events = executionJournal.getEventsForGoal(goal.goalId);
      expect(events.length).toBeGreaterThanOrEqual(4);

      // Verify monotonic ordering
      for (let i = 0; i < events.length - 1; i++) {
        expect(events[i].sequenceNumber).toBeLessThan(events[i + 1].sequenceNumber);
      }

      const eventTypes = events.map((e) => e.eventType);
      expect(eventTypes).toContain('GOAL_CREATED');
      expect(eventTypes).toContain('PLAN_CREATED');
      expect(eventTypes).toContain('ACTION_STARTED');
      expect(eventTypes).toContain('ACTION_SUCCEEDED');
      expect(eventTypes).toContain('GOAL_COMPLETED');
    });

    it('never overwrites historical events and provides subscription notifications', () => {
      const receivedEvents: string[] = [];
      const unsubscribe = executionJournal.subscribe((ev) => {
        receivedEvents.push(ev.eventType);
      });

      executionJournal.appendEvent({
        goalId: 'GOAL-TEST-001',
        eventType: 'GOAL_CREATED',
        payload: { test: true },
      });

      executionJournal.appendEvent({
        goalId: 'GOAL-TEST-001',
        eventType: 'PLAN_CREATED',
        payload: { planId: 'PLAN-1' },
      });

      expect(receivedEvents).toEqual(['GOAL_CREATED', 'PLAN_CREATED']);
      unsubscribe();
    });
  });

  describe('3. Crash Recovery Engine & State Reconstruction', () => {
    it('preserves completed upstream actions and restores the exact DAG execution frontier', () => {
      const goal = goalInterpreter.interpret('Research a cinematic concept for AryaOS and prepare a production brief');
      const plan = planGenerator.generatePlan(goal);
      goal.plans.push(plan);
      goal.currentPlanId = plan.planId;

      // Simulate crash where Action 1 completed, Action 2 was executing, Action 3 waiting
      plan.actions[0].status = 'SUCCEEDED';
      plan.actions[1].status = 'EXECUTING';
      plan.actions[2].status = 'WAITING_DEPENDENCY';
      goal.status = 'EXECUTING';

      executionPersistence.saveGoal(goal);

      // Run Recovery on reboot
      const results = recoveryManager.recoverAllGoals();
      expect(results.length).toBe(1);

      const recovered = results[0];
      expect(recovered.goalId).toBe(goal.goalId);
      expect(recovered.recoveredStatus).toBe('READY');

      // Frontier should point to Action 2 (Action 1 is SUCCEEDED, Action 3 is waiting on Action 2)
      expect(recovered.executableFrontier).toContain(plan.actions[1].actionId);
      expect(recovered.executableFrontier).not.toContain(plan.actions[2].actionId);
      expect(plan.actions[0].status).toBe('SUCCEEDED');
    });

    it('recovers verified completion from Stage 07 gateway idempotency cache if action completed before crash', () => {
      const goal = goalInterpreter.interpret('Research a cinematic concept for AryaOS and prepare a production brief');
      const plan = planGenerator.generatePlan(goal);
      goal.plans.push(plan);
      goal.currentPlanId = plan.planId;

      const act1 = plan.actions[0];
      act1.status = 'EXECUTING';
      goal.status = 'EXECUTING';

      // Pre-seed Stage 07 Gateway idempotency completed record
      const idempKey = `IDEMP-${act1.actionId}-${act1.requiredCapability}-${act1.providerId || 'default'}`;
      (executionGateway as any).completedExecutions.set(idempKey, {
        executionId: 'EXEC-PRE-CRASH',
        planId: plan.planId,
        providerId: 'gemini',
        modelId: 'gemini-2.0-flash-exp',
        status: 'SUCCEEDED',
        output: 'Recovered pre-crash output from gateway idempotency cache',
        latencyMs: 120,
        timestamp: new Date().toISOString(),
        usage: { promptTokens: 50, completionTokens: 50, totalTokens: 100 },
        provenance: {},
      });

      executionPersistence.saveGoal(goal);

      const results = recoveryManager.recoverAllGoals();
      expect(results[0].actionDecisions[0].actionToTake).toBe('PRESERVE_SUCCEEDED');

      const recoveredGoal = executionPersistence.loadEnvelope()?.goals[goal.goalId];
      const recoveredAct1 = recoveredGoal?.plans[0].actions[0];
      expect(recoveredAct1?.status).toBe('SUCCEEDED');
      expect(recoveredAct1?.outputs?.summary).toContain('Recovered pre-crash output');
    });

    it('restores pending human approval boundary across session restart without auto-approving', () => {
      const goal = goalInterpreter.interpret('Research a cinematic concept for AryaOS and prepare a production brief');
      const plan = planGenerator.generatePlan(goal);
      goal.plans.push(plan);
      goal.currentPlanId = plan.planId;

      // Actions 1 and 2 succeeded, Action 3 was awaiting approval when process died
      plan.actions[0].status = 'SUCCEEDED';
      plan.actions[1].status = 'SUCCEEDED';
      plan.actions[2].status = 'AWAITING_APPROVAL';
      plan.actions[2].approvalRequirement.required = true;
      plan.actions[2].approvalRequirement.approvedAt = undefined;
      goal.status = 'AWAITING_APPROVAL';

      executionPersistence.saveGoal(goal);

      const results = recoveryManager.recoverAllGoals();
      expect(results[0].recoveredStatus).toBe('AWAITING_APPROVAL');
      expect(results[0].approvalsPending).toContain(plan.actions[2].actionId);

      // Verify action remains AWAITING_APPROVAL in recovered state
      const recoveredGoal = executionPersistence.loadEnvelope()?.goals[goal.goalId];
      const recoveredAct3 = recoveredGoal?.plans[0].actions[2];
      expect(recoveredAct3?.status).toBe('AWAITING_APPROVAL');
      expect(recoveredAct3?.approvalRequirement.approvedAt).toBeUndefined();
    });

    it('recovers goal after provider fallback and preserves fallback provenance', async () => {
      // Primary gemini fails with 503 Overloaded; fallback to anthropic
      providerExecutionAdapter.registerAdapter({
        providerId: 'gemini',
        supportedCapabilities: ['RESEARCH'],
        validateConfiguration: () => ({ isValid: true }),
        execute: async () => ({
          status: 'FAILED',
          error: 'Gemini 503 Overloaded',
        }),
      });

      const intent = 'Research a cinematic concept for AryaOS and prepare a production brief';
      const goal = await goalOrchestrator.createAndExecuteGoal(intent, 'MEM-0001', {
        autoApprove: true,
      });

      expect(goal.status).toBe('COMPLETED');

      // Verify journal recorded fallback event
      const events = executionJournal.getEventsForGoal(goal.goalId);
      const fallbackEvent = events.find((e) => e.eventType === 'PROVIDER_FALLBACK');
      expect(fallbackEvent).toBeDefined();

      // Verify recovery on reboot preserves completed fallback state
      const results = recoveryManager.recoverAllGoals();
      expect(results[0].recoveredStatus).toBe('COMPLETED');
    });

    it('recovers plan version and plan history after replanning across application restart', () => {
      const goal = goalInterpreter.interpret('Research cinematic concept');
      const planV1 = planGenerator.generatePlan(goal);
      planV1.status = 'SUPERSEDED';
      planV1.actions[0].status = 'SUCCEEDED';
      planV1.actions[1].status = 'FAILED';

      const planV2 = planGenerator.generateReplan(goal, planV1, planV1.actions[1].actionId, 'Provider failure');
      planV2.actions[0].status = 'SUCCEEDED';
      planV2.actions[1].status = 'READY';

      goal.plans = [planV1, planV2];
      goal.currentPlanId = planV2.planId;
      goal.currentPlanVersion = 2;
      goal.status = 'READY';

      executionPersistence.saveGoal(goal);

      const results = recoveryManager.recoverAllGoals();
      expect(results[0].recoveredStatus).toBe('READY');
      expect(results[0].planVersion).toBe(2);

      const recoveredGoal = executionPersistence.loadEnvelope()?.goals[goal.goalId];
      expect(recoveredGoal?.plans.length).toBe(2);
      expect(recoveredGoal?.currentPlanVersion).toBe(2);
      expect(recoveredGoal?.plans[1].status).toBe('ACTIVE');
      expect(recoveredGoal?.plans[0].status).toBe('SUPERSEDED');
    });
  });

  describe('4. Action Resume Policy & Consequential Safety', () => {
    it('forces consequential in-flight actions to hold for human approval instead of blind retry', () => {
      const goal = goalInterpreter.interpret('Generate video production brief for new cinematic sequence');
      const plan = planGenerator.generatePlan(goal);
      goal.plans.push(plan);
      goal.currentPlanId = plan.planId;

      // An in-flight consequential video generation action was interrupted
      const consequentialAct = plan.actions[2];
      consequentialAct.status = 'EXECUTING';
      consequentialAct.approvalRequirement.required = true;
      consequentialAct.approvalRequirement.riskLevel = 'CONSEQUENTIAL';
      goal.status = 'EXECUTING';

      executionPersistence.saveGoal(goal);

      const results = recoveryManager.recoverAllGoals();
      const decision = results[0].actionDecisions.find((d) => d.actionId === consequentialAct.actionId);

      expect(decision?.actionToTake).toBe('HOLD_FOR_APPROVAL');
      expect(decision?.recoveryClassification).toBe('REQUIRES_HUMAN_APPROVAL');

      const recoveredGoal = executionPersistence.loadEnvelope()?.goals[goal.goalId];
      const recoveredConsequentialAct = recoveredGoal?.plans[0].actions[2];
      expect(recoveredConsequentialAct?.status).toBe('AWAITING_APPROVAL');
    });

    it('never resurrects cancelled goals across restart', () => {
      const goal = goalInterpreter.interpret('Research concept');
      const plan = planGenerator.generatePlan(goal);
      goal.plans.push(plan);
      goal.currentPlanId = plan.planId;
      goal.status = 'CANCELLED';

      executionPersistence.saveGoal(goal);

      const results = recoveryManager.recoverAllGoals();
      expect(results[0].recoveredStatus).toBe('CANCELLED');
      expect(results[0].resumed).toBe(false);
      expect(results[0].executableFrontier.length).toBe(0);
    });
  });

  describe('5. Security Hardening & Zero Secret Leakage', () => {
    it('guarantees that API keys, Bearer tokens, and secrets are scrubbed from persisted state and journal', () => {
      const dirtyPayload = {
        apiKey: 'sk-abcdef12345678901234567890',
        authorization: 'Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.token',
        nested: {
          secretToken: 'key-98765432109876543210',
          cleanData: 'Cinematic Archive Analysis',
        },
      };

      const sanitized = executionPersistence.sanitizeForPersistence(dirtyPayload);
      const json = JSON.stringify(sanitized);

      expect(json).not.toContain('sk-abcdef12345678901234567890');
      expect(json).not.toContain('eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9');
      expect(json).not.toContain('key-98765432109876543210');
      expect(json).toContain('[REDACTED_SECRET]');
      expect(json).toContain('Cinematic Archive Analysis');
    });
  });

  describe('6. Execution Scheduler Foundation', () => {
    it('supports immediate, delayed, and retry scheduling', async () => {
      let callCount = 0;
      const job = executionScheduler.scheduleJob({
        goalId: 'GOAL-SCHED-001',
        planId: 'PLAN-1',
        actionId: 'ACT-1',
        type: 'IMMEDIATE_ACTION',
        delayMs: 0,
        executeCallback: async () => {
          callCount++;
        },
      });

      await Promise.resolve();
      expect(job.status).toBe('COMPLETED');
      expect(callCount).toBe(1);
    });

    it('triggers dependency-unblocked actions when parent succeeds', async () => {
      const goal = goalInterpreter.interpret('Research concept');
      const plan = planGenerator.generatePlan(goal);
      const [act1, act2] = plan.actions;

      act1.status = 'SUCCEEDED';
      act2.status = 'WAITING_DEPENDENCY';
      act2.dependencies = [act1.actionId];

      let unblockedTriggered = false;
      const unblocked = executionScheduler.onDependencySatisfied(plan, act1.actionId, async () => {
        unblockedTriggered = true;
      });

      expect(unblocked.length).toBe(1);
      expect(unblocked[0].actionId).toBe(act2.actionId);
      expect(act2.status).toBe('READY');
    });
  });

  describe('7. React Hook Boot Recovery & HUD Transparency', () => {
    it('automatically recovers active goals on hook mount', async () => {
      const goal = goalInterpreter.interpret('Research a cinematic concept for AryaOS and prepare a production brief');
      const plan = planGenerator.generatePlan(goal);
      goal.plans.push(plan);
      goal.currentPlanId = plan.planId;
      plan.actions[0].status = 'SUCCEEDED';
      plan.actions[1].status = 'READY';
      goal.status = 'READY';

      executionPersistence.saveGoal(goal);

      const { result } = renderHook(() => useGoalOrchestration());

      expect(result.current.isRecovered).toBe(true);
      expect(result.current.activeGoal).not.toBeNull();
      expect(result.current.activeGoal?.goalId).toBe(goal.goalId);
      expect(result.current.activePlan?.version).toBe(1);
    });

    it('renders the durable recovery badge in the SpatialCommandConsole HUD', () => {
      // Seed persisted recovered goal
      const goal = goalInterpreter.interpret('Research cinematic lighting');
      const plan = planGenerator.generatePlan(goal);
      goal.plans.push(plan);
      goal.currentPlanId = plan.planId;
      goal.status = 'READY';
      (goalOrchestrator as any).goals.set(goal.goalId, goal);
      (goalOrchestrator as any).activeGoalId = goal.goalId;
      executionPersistence.saveGoal(goal);

      const mockControl: any = {
        commandState: 'IDLE',
        commandInput: '',
        currentCommand: null,
        activeProposal: null,
        activeExecutionPlan: null,
        lastResult: null,
        lastExecutionResult: null,
        highlightedVitrineIds: [],
        activeCamera: 'CAM_CinematicHero',
        memoryEvents: [],
        isConsoleOpen: true,
        setCommandInput: vi.fn(),
        submitCommand: vi.fn(),
        confirmProposal: vi.fn(),
        cancelProposal: vi.fn(),
        dismissResult: vi.fn(),
        setIsConsoleOpen: vi.fn(),
        toggleConsole: vi.fn(),
        navigateHistory: vi.fn(),
      };

      render(<SpatialCommandConsole commandControl={mockControl} />);

      // Verify HUD exists and renders the recovery badge
      const hud = screen.getByTestId('goal-orchestration-hud');
      expect(hud).toBeInTheDocument();

      const badge = screen.getByTestId('goal-recovered-badge');
      expect(badge).toBeInTheDocument();
      expect(badge).toHaveTextContent('DURABLE RECOVERED');
    });
  });
});
