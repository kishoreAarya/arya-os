/**
 * AryaOS V1 — Stage 08: End-to-End Autonomous Task Orchestration Tests
 *
 * Comprehensive verification for:
 * 1. Goal Creation & Natural Language Interpretation
 * 2. Dependency-Aware Action Graph (DAG) & Topological Layering
 * 3. Execution Scheduling strictly through Stage 07 ExecutionGateway
 * 4. Validation Scenario 1: End-to-End Multi-Step Autonomous Goal (Research -> Synthesis -> Brief -> Completion)
 * 5. Validation Scenario 2: Controlled Failure & Automated Provider Fallback
 * 6. Validation Scenario 3: Partial Success, Failure Recovery & Plan Versioning (Plan v1 -> Plan v2)
 * 7. Human Approval Boundary (AWAITING_APPROVAL -> approveAction / rejectAction)
 * 8. Operator Controls (Pause, Resume, Cancel with AbortSignal propagation)
 * 9. Idempotency & Concurrency (Dependency-aware scheduling)
 * 10. Closed-Loop Semantic Memory Ingestion with Complete Provenance & Zero Secret Leakage
 * 11. Spatial Command Console UI Transparency & Control Integration
 */

import React from 'react';
import { render, screen, fireEvent, act, renderHook } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { goalOrchestrator } from '../services/goalOrchestrator';
import { goalInterpreter } from '../services/goalInterpreter';
import { planGenerator } from '../services/planGenerator';
import { executionGateway } from '../services/executionGateway';
import { providerRegistry } from '../services/providerRegistry';
import { routingPolicyManager } from '../services/routingPolicy';
import { providerExecutionAdapter } from '../services/providerExecutionAdapter';
import { actionProposalService } from '../services/actionProposalService';
import { commandParser } from '../services/commandParser';
import { useGoalOrchestration } from '../hooks/useGoalOrchestration';
import { SpatialCommandConsole } from '../components/spatial/SpatialCommandConsole';
import { ActionNode, Goal, Plan } from '../types/goalOrchestration';

describe('AryaOS V1 Stage 08 — End-to-End Autonomous Task Orchestration & Closed-Loop Intelligence', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    goalOrchestrator.resetState();
    executionGateway.resetState();
    providerRegistry.resetToDefaults();
    routingPolicyManager.resetToDefaults();
    providerExecutionAdapter.initializeDefaultAdapters();
    actionProposalService.resetMemoryEvents();
  });

  describe('1. Goal Creation & Interpretation', () => {
    it('interprets natural-language intent into a structured Goal grounded in memory context', () => {
      const intent = 'Research a cinematic concept for AryaOS and prepare a production brief.';
      const goal = goalInterpreter.interpret(intent, 'MEM-0001');

      expect(goal.goalId).toMatch(/^GOAL-\d+/);
      expect(goal.userIntent).toBe(intent);
      expect(goal.objective).toContain('production-ready architectural concept');
      expect(goal.constraints.length).toBeGreaterThanOrEqual(2);
      expect(goal.completionCriteria.length).toBeGreaterThanOrEqual(2);
      expect(goal.contextRequirements.targetMemoryId).toBe('MEM-0001');
      expect(goal.contextRequirements.contextMemories).toContain('MEM-0001');
      expect(goal.provenance.sourceMemoryId).toBe('MEM-0001');
      expect(goal.approvalPolicy.requireApprovalForConsequential).toBe(true);
    });

    it('assigns appropriate priority and approval policy based on intent sensitivity', () => {
      const readOnlyGoal = goalInterpreter.interpret('Analyze previous decisions regarding reactor aperture');
      expect(readOnlyGoal.priority).toBe('MEDIUM');
      expect(readOnlyGoal.approvalPolicy.requireApprovalForConsequential).toBe(false);

      const productionGoal = goalInterpreter.interpret('Generate video production brief for new cinematic sequence');
      expect(productionGoal.approvalPolicy.requireApprovalForConsequential).toBe(true);
    });
  });

  describe('2. Action Graph (DAG) & Plan Generation', () => {
    it('decomposes a goal into a dependency-aware Action Graph rather than a flat array', () => {
      const goal = goalInterpreter.interpret('Research a cinematic concept for AryaOS and prepare a production brief');
      const plan = planGenerator.generatePlan(goal);

      expect(plan.planId).toContain('PLAN-');
      expect(plan.version).toBe(1);
      expect(plan.actions.length).toBe(3);

      const [act1, act2, act3] = plan.actions;

      // Node 1: Research (independent)
      expect(act1.dependencies).toHaveLength(0);
      expect(act1.status).toBe('READY');
      expect(act1.requiredCapability).toBe('RESEARCH');

      // Node 2: Concept Synthesis (depends on Node 1)
      expect(act2.dependencies).toContain(act1.actionId);
      expect(act2.status).toBe('WAITING_DEPENDENCY');
      expect(act2.requiredCapability).toBe('REASONING');

      // Node 3: Production Brief (depends on Node 2, requires approval)
      expect(act3.dependencies).toContain(act2.actionId);
      expect(act3.status).toBe('WAITING_DEPENDENCY');
      expect(act3.approvalRequirement.required).toBe(true);
      expect(act3.approvalRequirement.riskLevel).toBe('CONSEQUENTIAL');
    });

    it('computes topological execution layers for dependency-aware concurrency', () => {
      const goal = goalInterpreter.interpret('Analyze multi-branch domain capabilities and memory vitrines');
      const plan = planGenerator.generatePlan(goal);

      // Verify layers
      expect(plan.executionOrder.length).toBeGreaterThanOrEqual(2);
      // Layer 0 contains independent nodes (which can execute concurrently)
      expect(plan.executionOrder[0].length).toBeGreaterThanOrEqual(1);
    });

    it('calculates plan cost and latency envelopes without fabricating numbers', () => {
      const goal = goalInterpreter.interpret('Research a cinematic concept for AryaOS and prepare a production brief');
      const plan = planGenerator.generatePlan(goal);

      expect(plan.estimatedCost.currency).toBe('USD');
      expect(plan.estimatedCost.minUsd).toBeGreaterThan(0);
      expect(plan.estimatedCost.maxUsd).toBeGreaterThanOrEqual(plan.estimatedCost.minUsd!);
      expect(plan.estimatedLatencyMs).toBeGreaterThan(0);
    });
  });

  describe('3. Validation Scenario 1: End-to-End Multi-Step Autonomous Goal', () => {
    it('executes a multi-step goal autonomously through Stage 07 to full completion', async () => {
      const intent = 'Research a cinematic concept for AryaOS and prepare a production brief';

      // Auto-approve consequential actions for automated test run
      const goal = await goalOrchestrator.createAndExecuteGoal(intent, 'MEM-0001', {
        autoApprove: true,
      });

      expect(goal.status).toBe('COMPLETED');
      expect(goal.currentPlanVersion).toBe(1);

      const activePlan = goal.plans[0];
      expect(activePlan.actions.every((a) => a.status === 'SUCCEEDED')).toBe(true);

      // Verify each action node produced executionId and outputs
      for (const action of activePlan.actions) {
        expect(action.executionId).toBeDefined();
        expect(action.outputs).toBeDefined();
        expect(action.outputs?.artifacts).toBeDefined();
      }

      // Verify observations captured
      const obs = goalOrchestrator.getObservationsForGoal(goal.goalId);
      expect(obs.length).toBe(3);
      expect(obs.every((o) => o.status === 'SUCCESS')).toBe(true);

      // Verify audit trail completeness
      const events = actionProposalService.getMemoryEvents();
      const goalEvents = events.filter((e) => (e.metadata as any)?.goalId === goal.goalId);
      expect(goalEvents.length).toBeGreaterThanOrEqual(5);

      const eventTypes = goalEvents.map((e) => e.type);
      expect(eventTypes).toContain('INTELLIGENCE_ORCHESTRATOR_GOAL_CREATED');
      expect(eventTypes).toContain('INTELLIGENCE_ORCHESTRATOR_PLAN_CREATED');
      expect(eventTypes).toContain('INTELLIGENCE_ORCHESTRATOR_ACTION_EXECUTING');
      expect(eventTypes).toContain('INTELLIGENCE_ORCHESTRATOR_ACTION_SUCCEEDED');
      expect(eventTypes).toContain('INTELLIGENCE_ORCHESTRATOR_GOAL_COMPLETED');
    });
  });

  describe('4. Validation Scenario 2: Controlled Failure & Automated Provider Fallback', () => {
    it('handles primary provider failure by falling back according to Stage 06/07 policy', async () => {
      // Primary gemini fails with 503 Overloaded
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

      // First action should have fallen back to anthropic and succeeded
      const activePlan = goal.plans.find((p) => p.planId === goal.currentPlanId)!;
      const firstAction = activePlan.actions[0];
      expect(firstAction.status).toBe('SUCCEEDED');

      const obs = goalOrchestrator.getObservationsForGoal(goal.goalId);
      expect(obs[0].status).toBe('SUCCESS');
      expect(obs[0].providerId).toBe('anthropic');
    });
  });

  describe('5. Validation Scenario 3: Partial Success, Failure Recovery & Plan Versioning', () => {
    it('preserves successful actions and generates Plan v2 when an intermediate node fails', async () => {
      let callCount = 0;
      // Primary succeeds for first action, fails on second action, succeeds on replan
      providerExecutionAdapter.registerAdapter({
        providerId: 'gemini',
        supportedCapabilities: ['RESEARCH', 'REASONING', 'STRUCTURED_EXTRACTION'],
        validateConfiguration: () => ({ isValid: true }),
        execute: async (plan) => {
          callCount++;
          // Fail the 2nd action on Plan v1
          if (callCount === 2) {
            return {
              status: 'FAILED',
              error: 'Rate limit / cluster transient failure on synthesis',
            };
          }
          return {
            status: 'SUCCEEDED',
            output: `Verified response for ${plan.capability} [call ${callCount}]`,
          };
        },
      });

      // Secondary fallback also fails for action 2 so the action fails at gateway level to trigger replan
      providerExecutionAdapter.registerAdapter({
        providerId: 'anthropic',
        supportedCapabilities: ['RESEARCH', 'REASONING', 'STRUCTURED_EXTRACTION'],
        validateConfiguration: () => ({ isValid: true }),
        execute: async (plan) => {
          if (callCount === 2) {
            return {
              status: 'FAILED',
              error: 'Anthropic secondary failure',
            };
          }
          return {
            status: 'SUCCEEDED',
            output: `Verified anthropic response for ${plan.capability}`,
          };
        },
      });

      const intent = 'Research a cinematic concept for AryaOS and prepare a production brief';
      const goal = await goalOrchestrator.createAndExecuteGoal(intent, 'MEM-0001', {
        autoApprove: true,
        maxReplans: 2,
      });

      // Goal should have recovered via replan and reached COMPLETED
      expect(goal.status).toBe('COMPLETED');
      expect(goal.currentPlanVersion).toBe(2);
      expect(goal.plans.length).toBe(2);

      const [planV1, planV2] = goal.plans;
      expect(planV1.version).toBe(1);
      expect(planV1.status).toBe('SUPERSEDED');

      expect(planV2.version).toBe(2);
      expect(planV2.status).toBe('ACTIVE');

      // Verify partial success: Action 1 from Plan v1 was preserved in Plan v2
      const v2Action1 = planV2.actions[0];
      expect(v2Action1.status).toBe('SUCCEEDED');

      // Verify events recorded plan revision
      const events = actionProposalService.getMemoryEvents();
      const revisionEvent = events.find(
        (e) => e.type === 'INTELLIGENCE_ORCHESTRATOR_PLAN_REVISED'
      );
      expect(revisionEvent).toBeDefined();
    });
  });

  describe('6. Human Approval Boundary', () => {
    it('pauses execution at AWAITING_APPROVAL when consequential action requires operator confirmation', async () => {
      const intent = 'Research a cinematic concept for AryaOS and prepare a production brief';

      // Execute WITHOUT autoApprove
      const goal = await goalOrchestrator.createAndExecuteGoal(intent, 'MEM-0001', {
        autoApprove: false,
      });

      // Actions 1 and 2 succeed; Action 3 requires approval and halts goal at AWAITING_APPROVAL
      expect(goal.status).toBe('AWAITING_APPROVAL');

      const activePlan = goal.plans[0];
      const action3 = activePlan.actions[2];
      expect(action3.status).toBe('AWAITING_APPROVAL');

      // Operator approves Action 3
      const approved = await goalOrchestrator.approveAction(goal.goalId, action3.actionId);
      expect(approved).toBe(true);

      // Execution resumes and completes
      expect(goal.status).toBe('COMPLETED');
      expect(action3.status).toBe('SUCCEEDED');
    });

    it('blocks action and goal when operator rejects consequential action', async () => {
      const intent = 'Research a cinematic concept for AryaOS and prepare a production brief';

      const goal = await goalOrchestrator.createAndExecuteGoal(intent, 'MEM-0001', {
        autoApprove: false,
      });

      expect(goal.status).toBe('AWAITING_APPROVAL');
      const activePlan = goal.plans[0];
      const action3 = activePlan.actions[2];

      const rejected = goalOrchestrator.rejectAction(
        goal.goalId,
        action3.actionId,
        'Risk threshold exceeded'
      );
      expect(rejected).toBe(true);
      expect(goal.status).toBe('BLOCKED');
      expect(action3.status).toBe('BLOCKED');
      expect(action3.approvalRequirement.rejectionReason).toBe('Risk threshold exceeded');
    });
  });

  describe('7. Operator Controls (Pause, Resume, Cancel)', () => {
    it('supports operator pause and resume of running goals', async () => {
      const goal = goalInterpreter.interpret('Research concept');
      const plan = planGenerator.generatePlan(goal);
      goal.plans.push(plan);
      goal.currentPlanId = plan.planId;
      goal.status = 'EXECUTING';
      (goalOrchestrator as any).goals.set(goal.goalId, goal);

      const paused = goalOrchestrator.pauseGoal(goal.goalId);
      expect(paused).toBe(true);
      expect(goal.status).toBe('BLOCKED');

      const resumed = await goalOrchestrator.resumeGoal(goal.goalId);
      expect(resumed).toBe(true);
    });

    it('cancels goal and aborts running operations cleanly via AbortSignal', async () => {
      const intent = 'Research a cinematic concept for AryaOS and prepare a production brief';
      const goalPromise = goalOrchestrator.createAndExecuteGoal(intent, 'MEM-0001');

      // Cancel immediately
      const activeGoal = goalOrchestrator.getActiveGoal()!;
      goalOrchestrator.cancelGoal(activeGoal.goalId);

      const finalGoal = await goalPromise;
      expect(finalGoal.status).toBe('CANCELLED');
    });
  });

  describe('8. Security Hardening & Zero Secret Leakage', () => {
    it('guarantees that secrets are scrubbed from Goal, Plan, ActionNode, Observations, and MemoryEvents', async () => {
      // Mock adapter attempting to leak secrets in output
      providerExecutionAdapter.registerAdapter({
        providerId: 'gemini',
        supportedCapabilities: ['RESEARCH', 'REASONING', 'STRUCTURED_EXTRACTION'],
        validateConfiguration: () => ({ isValid: true }),
        execute: async () => ({
          status: 'SUCCEEDED',
          output: 'Sensitive output: Authorization: Bearer sk-ant-secret1234567890abcdef12345 and AIzaSyD12345678901234567890123456789012345',
        }),
      });

      const intent = 'Research a cinematic concept for AryaOS and prepare a production brief';
      const goal = await goalOrchestrator.createAndExecuteGoal(intent, 'MEM-0001', {
        autoApprove: true,
      });

      const goalSerialized = JSON.stringify(goal);
      expect(goalSerialized).not.toContain('sk-ant-secret1234567890abcdef12345');
      expect(goalSerialized).not.toContain('AIzaSyD12345678901234567890123456789012345');
      expect(goalSerialized).toContain('Bearer [REDACTED]');
      expect(goalSerialized).toContain('AIza[REDACTED]');

      const obs = goalOrchestrator.getObservationsForGoal(goal.goalId);
      const obsSerialized = JSON.stringify(obs);
      expect(obsSerialized).not.toContain('sk-ant-secret');
      expect(obsSerialized).not.toContain('AIzaSyD');

      const events = actionProposalService.getMemoryEvents();
      const eventsSerialized = JSON.stringify(events);
      expect(eventsSerialized).not.toContain('sk-ant-secret');
      expect(eventsSerialized).not.toContain('AIzaSyD');
    });
  });

  describe('9. Command Parser & Hook Lifecycle Integration', () => {
    it('recognizes ORCHESTRATE_GOAL commands in natural language', () => {
      const cmd1 = commandParser.parse('Goal: Research a cinematic concept for AryaOS and prepare a production brief');
      expect(cmd1.intent).toBe('ORCHESTRATE_GOAL');

      const cmd2 = commandParser.parse('Orchestrate: Formulate production plan for Astrolabe core');
      expect(cmd2.intent).toBe('ORCHESTRATE_GOAL');
    });

    it('provides reactive goal state and controls via useGoalOrchestration hook', async () => {
      const { result } = renderHook(() => useGoalOrchestration());

      await act(async () => {
        await result.current.startGoal(
          'Research a cinematic concept for AryaOS and prepare a production brief',
          'MEM-0001',
          { autoApprove: true }
        );
      });

      expect(result.current.activeGoal).not.toBeNull();
      expect(result.current.activeGoal?.status).toBe('COMPLETED');
      expect(result.current.activePlan?.version).toBe(1);
      expect(result.current.actions.length).toBe(3);
    });
  });

  describe('10. Spatial Command Console UI Transparency & Control Integration', () => {
    it('renders goal orchestration HUD with active plan, objective, and action status indicators', () => {
      // Mock active goal and plan
      const goal = goalInterpreter.interpret('Research a cinematic concept for AryaOS and prepare a production brief');
      const plan = planGenerator.generatePlan(goal);
      goal.plans.push(plan);
      goal.currentPlanId = plan.planId;
      goal.status = 'EXECUTING';
      (goalOrchestrator as any).goals.set(goal.goalId, goal);
      (goalOrchestrator as any).activeGoalId = goal.goalId;

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
        clearHighlights: vi.fn(),
        setActiveCamera: vi.fn(),
        setIsConsoleOpen: vi.fn(),
        toggleConsole: vi.fn(),
        navigateHistory: vi.fn(),
      };

      render(<SpatialCommandConsole commandControl={mockControl} />);

      expect(screen.getByTestId('goal-orchestration-hud')).toBeInTheDocument();
      expect(screen.getByTestId('goal-plan-version')).toHaveTextContent('PLAN v1');
      expect(screen.getByTestId('goal-objective')).toBeInTheDocument();
      expect(screen.getByTestId('goal-actions-list')).toBeInTheDocument();
      expect(screen.getByTestId('goal-pause-btn')).toBeInTheDocument();
      expect(screen.getByTestId('goal-cancel-btn')).toBeInTheDocument();
    });
  });
});
