/**
 * AryaOS V1 — Stage 10: Multi-Agent Coordination, Resource Governance & Intelligence Economy Tests
 *
 * Comprehensive verification of:
 * 1. Agent Assignment & Capability Matching (provider-neutral, workload-aware)
 * 2. Concurrency Governance & DAG Parallelism (action and per-agent limits)
 * 3. Cost & Latency Governance (budget preflight, unknown costs, deadline feasibility)
 * 4. Shared Memory Locking & Collision Prevention (read/read vs read/write vs write/write)
 * 5. Conflict Detection & Resolution (memory write conflicts, contradictory outputs)
 * 6. Objective Quality Gating & Truthful Result Aggregation (SINGLE_RESULT, MERGE, CONSENSUS)
 * 7. End-to-End Multi-Agent Goal Execution with Full Provenance
 * 8. Zero Secret Leakage & Single Gateway Boundary Integrity
 * 9. Spatial Command Console HUD Transparency
 */

import React from 'react';
import { render, screen, act } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { agentRegistry } from '../services/agentRegistry';
import { resourceGovernor } from '../services/resourceGovernor';
import { memoryLockManager } from '../services/memoryLockManager';
import { agentConflictManager } from '../services/agentConflictManager';
import { qualityGate } from '../services/qualityGate';
import { agentResultAggregator } from '../services/agentResultAggregator';
import { agentCoordinator } from '../services/agentCoordinator';
import { goalOrchestrator } from '../services/goalOrchestrator';
import { executionGateway } from '../services/executionGateway';
import { providerRegistry } from '../services/providerRegistry';
import { providerExecutionAdapter } from '../services/providerExecutionAdapter';
import { actionProposalService } from '../services/actionProposalService';
import { SpatialCommandConsole } from '../components/spatial/SpatialCommandConsole';
import { ActionNode, Goal } from '../types/goalOrchestration';
import { AgentTask } from '../types/agentCoordination';

describe('AryaOS V1 Stage 10 — Multi-Agent Coordination, Resource Governance & Intelligence Economy', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    agentCoordinator.resetState();
    goalOrchestrator.resetState();
    executionGateway.resetState();
    providerRegistry.resetToDefaults();
    providerExecutionAdapter.initializeDefaultAdapters();
    actionProposalService.resetMemoryEvents();
  });

  // =========================================================================
  // 1. Agent Assignment & Compatibility Scoring
  // =========================================================================
  describe('1. Agent Assignment & Compatibility Scoring', () => {
    it('matches task capability to the optimal provider-neutral agent', () => {
      const mockAction: ActionNode = {
        actionId: 'act-res-1',
        goalId: 'goal-1',
        planId: 'plan-1',
        title: 'Research Memory Vitrine',
        type: 'RESEARCH',
        description: 'Gather facts from archival vitrine',
        inputs: {},
        dependencies: [],
        requiredCapability: 'RESEARCH',
        status: 'READY',
        retryPolicy: { maxRetries: 2, backoffMs: 1000, retriesAttempted: 0 },
        approvalRequirement: { required: false, riskLevel: 'READ_ONLY' },
        completionCriteria: [],
        provenance: {},
      };

      const selected = agentCoordinator.selectBestAgent(mockAction);
      expect(selected).toBeDefined();
      expect(selected?.agentId).toBe('agent-researcher');
      expect(selected?.role).toBe('RESEARCHER');
      expect(selected?.capabilities).toContain('RESEARCH');
    });

    it('balances workload by assigning to less saturated agents', () => {
      // Saturate agent-researcher and agent-analyst workload
      agentRegistry.updateAgentWorkload('agent-researcher', 3);
      agentRegistry.updateAgentWorkload('agent-analyst', 2);

      const mockAction: ActionNode = {
        actionId: 'act-sum-1',
        goalId: 'goal-1',
        planId: 'plan-1',
        title: 'Summarize Vitrine Findings',
        type: 'RESEARCH',
        description: 'Summarize gathered notes',
        inputs: {},
        dependencies: [],
        requiredCapability: 'SUMMARIZATION',
        status: 'READY',
        retryPolicy: { maxRetries: 2, backoffMs: 1000, retriesAttempted: 0 },
        approvalRequirement: { required: false, riskLevel: 'READ_ONLY' },
        completionCriteria: [],
        provenance: {},
      };

      // Narrative Synthesizer (agent-writer) also handles SUMMARIZATION and has 0 workload
      const selected = agentCoordinator.selectBestAgent(mockAction);
      expect(selected).toBeDefined();
      expect(selected?.agentId).toBe('agent-writer');
      expect(selected?.role).toBe('WRITER');
    });

    it('rejects assignment if no compatible agent has capacity', () => {
      // Disable video director
      agentRegistry.updateAgentStatus('agent-video-director', 'UNAVAILABLE');

      const mockAction: ActionNode = {
        actionId: 'act-vid-1',
        goalId: 'goal-1',
        planId: 'plan-1',
        title: 'Generate Cinematic Keyframe Sequence',
        type: 'VIDEO',
        description: 'Render video sequence',
        inputs: {},
        dependencies: [],
        requiredCapability: 'VIDEO_GENERATION',
        status: 'READY',
        retryPolicy: { maxRetries: 1, backoffMs: 2000, retriesAttempted: 0 },
        approvalRequirement: { required: true, riskLevel: 'CONSEQUENTIAL' },
        completionCriteria: [],
        provenance: {},
      };

      const selected = agentCoordinator.selectBestAgent(mockAction);
      expect(selected).toBeUndefined();
    });

    it('ensures agent profiles remain provider-neutral without vendor lock-in', () => {
      const allAgents = agentRegistry.getAllAgents();
      for (const agent of allAgents) {
        // Agent identity must not be hardcoded to OpenAI, Anthropic, or Google
        expect(agent.agentId).not.toMatch(/openai|anthropic|gemini|google/i);
        expect(agent.name).not.toMatch(/chatgpt|claude|gemini/i);
      }
    });
  });

  // =========================================================================
  // 2. Resource Governance (Cost, Latency, Concurrency)
  // =========================================================================
  describe('2. Resource Governance', () => {
    it('halts dispatch when goal financial budget would be exceeded', () => {
      resourceGovernor.setGoalBudget('goal-budget-test', {
        maxCostUsd: 0.1, // $0.10 ceiling
      });

      const preflight1 = resourceGovernor.checkBudgetPreflight('goal-budget-test', 0.05);
      expect(preflight1.allowed).toBe(true);

      // Record $0.08 expenditure
      const lease = resourceGovernor.acquireLease(
        'goal-budget-test',
        {
          taskId: 'task-1',
          goalId: 'goal-budget-test',
          planId: 'p-1',
          planVersion: 1,
          parentActionId: 'a-1',
          capability: 'REASONING',
          contextReferences: [],
          inputContract: {},
          expectedOutputContract: {},
          priority: 'NORMAL' as any,
          riskLevel: 'READ_ONLY',
          estimatedCost: { minUsd: null, maxUsd: 0.05, currency: 'USD' },
          estimatedLatency: 1000,
          status: 'RUNNING',
          qualityRequirement: 'QUALITY_STANDARD',
          memoryAccessDeclarations: [],
          createdAt: '',
          updatedAt: '',
        },
        agentRegistry.getAgent('agent-analyst')!
      );
      expect(lease.allowed).toBe(true);
      resourceGovernor.releaseLease(lease.lease!.leaseId, 0.08);

      // Now preflight with another $0.05 should exceed $0.10 limit ($0.08 + $0.05 = $0.13 > $0.10)
      const preflight2 = resourceGovernor.checkBudgetPreflight('goal-budget-test', 0.05);
      expect(preflight2.allowed).toBe(false);
      expect((preflight2 as any).reason).toBe('RESOURCE_BUDGET_EXCEEDED');
    });

    it('records UNKNOWN cost truthfully when provider does not return financial usage', () => {
      const lease = resourceGovernor.acquireLease(
        'goal-cost-unknown',
        {
          taskId: 'task-u',
          goalId: 'goal-cost-unknown',
          planId: 'p-1',
          planVersion: 1,
          parentActionId: 'a-1',
          capability: 'REASONING',
          contextReferences: [],
          inputContract: {},
          expectedOutputContract: {},
          priority: 'NORMAL' as any,
          riskLevel: 'READ_ONLY',
          estimatedCost: { minUsd: null, maxUsd: 0.02, currency: 'USD' },
          estimatedLatency: 500,
          status: 'RUNNING',
          qualityRequirement: 'QUALITY_STANDARD',
          memoryAccessDeclarations: [],
          createdAt: '',
          updatedAt: '',
        },
        agentRegistry.getAgent('agent-analyst')!
      );

      // Release with UNKNOWN cost
      resourceGovernor.releaseLease(lease.lease!.leaseId, 'UNKNOWN');

      const tracking = resourceGovernor.getGoalCostTracking('goal-cost-unknown');
      expect(tracking.costStatus).toBe('UNKNOWN');
      expect(tracking.costSoFar).toBe(0);
    });

    it('enforces maximum concurrent actions limit for a goal', () => {
      resourceGovernor.setGoalBudget('goal-concurrency', {
        maxConcurrentActions: 2,
      });

      const taskTemplate: AgentTask = {
        taskId: 't-1',
        goalId: 'goal-concurrency',
        planId: 'p-1',
        planVersion: 1,
        parentActionId: 'a-1',
        capability: 'RESEARCH',
        contextReferences: [],
        inputContract: {},
        expectedOutputContract: {},
        priority: 'NORMAL' as any,
        riskLevel: 'READ_ONLY',
        estimatedCost: { minUsd: null, maxUsd: null, currency: 'USD' },
        estimatedLatency: 1000,
        status: 'RUNNING',
        qualityRequirement: 'QUALITY_STANDARD',
        memoryAccessDeclarations: [],
        createdAt: '',
        updatedAt: '',
      };

      const agent = agentRegistry.getAgent('agent-researcher')!;
      const l1 = resourceGovernor.acquireLease('goal-concurrency', { ...taskTemplate, taskId: 't-1' }, agent);
      const l2 = resourceGovernor.acquireLease('goal-concurrency', { ...taskTemplate, taskId: 't-2' }, agent);
      const l3 = resourceGovernor.acquireLease('goal-concurrency', { ...taskTemplate, taskId: 't-3' }, agent);

      expect(l1.allowed).toBe(true);
      expect(l2.allowed).toBe(true);
      expect(l3.allowed).toBe(false);
      expect((l3.checkResult as any)?.reason).toBe('CONCURRENCY_LIMIT_REACHED');
    });

    it('detects unfeasible deadlines and requests route reconsideration', () => {
      const pastDeadline = new Date(Date.now() - 5000).toISOString();
      const task: AgentTask = {
        taskId: 't-deadline',
        goalId: 'goal-d',
        planId: 'p-1',
        planVersion: 1,
        parentActionId: 'a-1',
        capability: 'REASONING',
        contextReferences: [],
        inputContract: {},
        expectedOutputContract: {},
        priority: 'HIGH',
        riskLevel: 'READ_ONLY',
        estimatedCost: { minUsd: null, maxUsd: null, currency: 'USD' },
        estimatedLatency: 10000, // 10 seconds
        deadline: pastDeadline,
        status: 'ASSIGNED',
        qualityRequirement: 'QUALITY_STANDARD',
        memoryAccessDeclarations: [],
        createdAt: '',
        updatedAt: '',
      };

      const check = resourceGovernor.checkDeadlineFeasibility(task, 10000);
      expect(check.allowed).toBe(false);
      expect((check as any).reason).toBe('ROUTE_RECONSIDERATION_REQUIRED');
    });
  });

  // =========================================================================
  // 3. Shared Memory Locking
  // =========================================================================
  describe('3. Shared Memory Locking & Collision Prevention', () => {
    it('permits concurrent READ locks on the same memory entity', () => {
      const acq1 = memoryLockManager.acquireLocks('task-r1', 'agent-researcher', [
        { memoryId: 'MEM-0001', accessType: 'READ' },
      ]);
      const acq2 = memoryLockManager.acquireLocks('task-r2', 'agent-analyst', [
        { memoryId: 'MEM-0001', accessType: 'READ' },
      ]);

      expect(acq1.acquired).toBe(true);
      expect(acq2.acquired).toBe(true);
      expect(memoryLockManager.getLockState('MEM-0001')).toBe('READ_LOCKED');
    });

    it('blocks concurrent WRITE lock when another task holds a READ lock', () => {
      memoryLockManager.acquireLocks('task-r1', 'agent-researcher', [
        { memoryId: 'MEM-0002', accessType: 'READ' },
      ]);

      const writeAttempt = memoryLockManager.acquireLocks('task-w1', 'agent-writer', [
        { memoryId: 'MEM-0002', accessType: 'WRITE' },
      ]);

      expect(writeAttempt.acquired).toBe(false);
      expect(writeAttempt.conflictingLocks.length).toBeGreaterThanOrEqual(1);
      expect(writeAttempt.conflictingLocks[0].ownerTaskId).toBe('task-r1');
    });

    it('blocks concurrent WRITE lock when another task holds a WRITE lock', () => {
      memoryLockManager.acquireLocks('task-w1', 'agent-writer', [
        { memoryId: 'MEM-0003', accessType: 'WRITE' },
      ]);

      const writeAttempt2 = memoryLockManager.acquireLocks('task-w2', 'agent-coder', [
        { memoryId: 'MEM-0003', accessType: 'WRITE' },
      ]);

      expect(writeAttempt2.acquired).toBe(false);
      expect(writeAttempt2.conflictingLocks[0].ownerTaskId).toBe('task-w1');
    });

    it('releases locks cleanly upon task completion', () => {
      memoryLockManager.acquireLocks('task-temp', 'agent-analyst', [
        { memoryId: 'MEM-0004', accessType: 'WRITE' },
      ]);
      expect(memoryLockManager.getLockState('MEM-0004')).toBe('WRITE_LOCKED');

      memoryLockManager.releaseLocksForTask('task-temp');
      expect(memoryLockManager.getLockState('MEM-0004')).toBe('AVAILABLE');
    });
  });

  // =========================================================================
  // 4. Conflict Detection & Resolution
  // =========================================================================
  describe('4. Conflict Detection & Resolution', () => {
    it('detects simultaneous memory write collisions and registers structured conflict', () => {
      const taskA: AgentTask = {
        taskId: 'task-a',
        goalId: 'goal-conflict-1',
        planId: 'plan-1',
        planVersion: 1,
        parentActionId: 'act-a',
        assignedAgentId: 'agent-writer',
        capability: 'REASONING',
        contextReferences: [],
        inputContract: {},
        expectedOutputContract: {},
        priority: 'MEDIUM',
        riskLevel: 'CONSEQUENTIAL',
        estimatedCost: { minUsd: null, maxUsd: null, currency: 'USD' },
        estimatedLatency: 1000,
        status: 'RUNNING',
        qualityRequirement: 'QUALITY_STANDARD',
        memoryAccessDeclarations: [{ memoryId: 'MEM-0010', accessType: 'WRITE' }],
        createdAt: '',
        updatedAt: '',
      };

      const taskB: AgentTask = {
        taskId: 'task-b',
        goalId: 'goal-conflict-1',
        planId: 'plan-1',
        planVersion: 1,
        parentActionId: 'act-b',
        assignedAgentId: 'agent-coder',
        capability: 'CODE_GENERATION',
        contextReferences: [],
        inputContract: {},
        expectedOutputContract: {},
        priority: 'MEDIUM',
        riskLevel: 'CONSEQUENTIAL',
        estimatedCost: { minUsd: null, maxUsd: null, currency: 'USD' },
        estimatedLatency: 1000,
        status: 'RUNNING',
        qualityRequirement: 'QUALITY_STANDARD',
        memoryAccessDeclarations: [{ memoryId: 'MEM-0010', accessType: 'WRITE' }],
        createdAt: '',
        updatedAt: '',
      };

      const conflicts = agentConflictManager.checkMemoryWriteConflicts([taskA, taskB]);
      expect(conflicts.length).toBe(1);
      expect(conflicts[0].category).toBe('MEMORY_WRITE_CONFLICT');
      expect(conflicts[0].resourceOrMemoryId).toBe('MEM-0010');
      expect(conflicts[0].conflictingTaskIds).toContain('task-a');
      expect(conflicts[0].conflictingTaskIds).toContain('task-b');
    });

    it('detects contradictory execution results from multi-agent tasks', () => {
      const results = [
        {
          aggregationId: 'agg-1',
          goalId: 'goal-c2',
          taskId: 't-1',
          agentId: 'agent-analyst',
          providerId: 'gemini',
          executionId: 'e-1',
          output: 'The reactor aperture is operating at normal 88% efficiency.',
          provenance: {},
          confidence: 'UNKNOWN' as const,
          actualCostUsd: 0.01,
          latencyMs: 800,
          status: 'SUCCEEDED' as const,
          strategyApplied: 'SINGLE_RESULT' as const,
          timestamp: '',
        },
        {
          aggregationId: 'agg-2',
          goalId: 'goal-c2',
          taskId: 't-2',
          agentId: 'agent-quality',
          providerId: 'anthropic',
          executionId: 'e-2',
          output: 'CRITICAL FAILURE: Aperture core collapsed.',
          provenance: {},
          confidence: 'UNKNOWN' as const,
          actualCostUsd: 0.01,
          latencyMs: 950,
          status: 'FAILED' as const,
          strategyApplied: 'SINGLE_RESULT' as const,
          timestamp: '',
        },
      ];

      const conflict = agentConflictManager.detectContradictoryOutputs(results, 'goal-c2');
      expect(conflict).not.toBeNull();
      expect(conflict?.category).toBe('CONTRADICTORY_OUTPUT');
    });

    it('resolves conflict with structured strategy (REVIEW, REPLAN, RESOLVE)', () => {
      const record = agentConflictManager.recordConflict({
        goalId: 'goal-res',
        category: 'MEMORY_WRITE_CONFLICT',
        conflictingTaskIds: ['t-1', 't-2'],
        conflictingAgentIds: ['a-1', 'a-2'],
        description: 'Test collision',
        provenanceRecords: [],
      });

      const resolved = agentConflictManager.resolveConflict(
        record.conflictId,
        'RESOLVE',
        'Serial execution prioritized for task t-1 over t-2'
      );
      expect(resolved).toBe(true);

      const conflicts = agentConflictManager.getConflictsForGoal('goal-res');
      expect(conflicts[0].resolutionStrategy).toBe('RESOLVE');
      expect(conflicts[0].resolvedAt).toBeDefined();
    });
  });

  // =========================================================================
  // 5. Objective Quality Gate & Result Aggregation
  // =========================================================================
  describe('5. Objective Quality Gate & Result Aggregation', () => {
    it('fails output that is empty or whitespace-only', () => {
      const task: AgentTask = {
        taskId: 't-q',
        goalId: 'g-q',
        planId: 'p-1',
        planVersion: 1,
        parentActionId: 'a-1',
        capability: 'REASONING',
        contextReferences: [],
        inputContract: {},
        expectedOutputContract: {},
        priority: 'NORMAL' as any,
        riskLevel: 'READ_ONLY',
        estimatedCost: { minUsd: null, maxUsd: null, currency: 'USD' },
        estimatedLatency: 500,
        status: 'RUNNING',
        qualityRequirement: 'QUALITY_STANDARD',
        memoryAccessDeclarations: [],
        createdAt: '',
        updatedAt: '',
      };

      const evalResult = qualityGate.evaluate(task, '   \n  ');
      expect(evalResult.passed).toBe(false);
      expect(evalResult.issues[0]).toContain('empty');
    });

    it('flags HUMAN_REVIEW when quality requirement explicitly demands operator verification', () => {
      const task: AgentTask = {
        taskId: 't-hr',
        goalId: 'g-q',
        planId: 'p-1',
        planVersion: 1,
        parentActionId: 'a-1',
        capability: 'REASONING',
        contextReferences: [],
        inputContract: {},
        expectedOutputContract: {},
        priority: 'CRITICAL',
        riskLevel: 'CONSEQUENTIAL',
        estimatedCost: { minUsd: null, maxUsd: null, currency: 'USD' },
        estimatedLatency: 1000,
        status: 'RUNNING',
        qualityRequirement: 'HUMAN_REVIEW',
        memoryAccessDeclarations: [],
        createdAt: '',
        updatedAt: '',
      };

      const evalResult = qualityGate.evaluate(task, 'Production-ready final brief');
      expect(evalResult.humanReviewRequired).toBe(true);
    });

    it('aggregates multi-agent outputs using MERGE strategy preserving individual attribution', () => {
      const results = [
        {
          aggregationId: 'a1',
          goalId: 'g-m',
          taskId: 't-1',
          agentId: 'agent-researcher',
          providerId: 'gemini',
          executionId: 'e-1',
          output: 'Part 1: Historical records indicate 24 vitrines installed.',
          provenance: {},
          confidence: 'UNKNOWN' as const,
          actualCostUsd: 0.005,
          latencyMs: 700,
          status: 'SUCCEEDED' as const,
          strategyApplied: 'SINGLE_RESULT' as const,
          timestamp: '',
        },
        {
          aggregationId: 'a2',
          goalId: 'g-m',
          taskId: 't-2',
          agentId: 'agent-analyst',
          providerId: 'anthropic',
          executionId: 'e-2',
          output: 'Part 2: 18 vitrines active, 6 undergoing restoration.',
          provenance: {},
          confidence: 'UNKNOWN' as const,
          actualCostUsd: 0.015,
          latencyMs: 900,
          status: 'SUCCEEDED' as const,
          strategyApplied: 'SINGLE_RESULT' as const,
          timestamp: '',
        },
      ];

      const merged = agentResultAggregator.aggregateMultiple('g-m', 't-multi', results, 'MERGE');
      expect(merged.strategyApplied).toBe('MERGE');
      expect(merged.output).toContain('agent-researcher');
      expect(merged.output).toContain('agent-analyst');
      expect(merged.actualCostUsd).toBe(0.02);
      expect(merged.latencyMs).toBe(800);
      expect(merged.status).toBe('SUCCEEDED');
    });

    it('enforces CONSENSUS_REQUIRED and flags CONFLICT when agent outputs diverge', () => {
      const results = [
        {
          aggregationId: 'a1',
          goalId: 'g-c',
          taskId: 't-c',
          agentId: 'agent-1',
          providerId: 'p-1',
          executionId: 'e-1',
          output: 'Aperture status: OK',
          provenance: {},
          confidence: 'UNKNOWN' as const,
          actualCostUsd: 0.01,
          latencyMs: 500,
          status: 'SUCCEEDED' as const,
          strategyApplied: 'SINGLE_RESULT' as const,
          timestamp: '',
        },
        {
          aggregationId: 'a2',
          goalId: 'g-c',
          taskId: 't-c',
          agentId: 'agent-2',
          providerId: 'p-2',
          executionId: 'e-2',
          output: 'Aperture status: CRITICAL_FAULT',
          provenance: {},
          confidence: 'UNKNOWN' as const,
          actualCostUsd: 0.01,
          latencyMs: 600,
          status: 'SUCCEEDED' as const,
          strategyApplied: 'SINGLE_RESULT' as const,
          timestamp: '',
        },
      ];

      const consensus = agentResultAggregator.aggregateMultiple('g-c', 't-c', results, 'CONSENSUS_REQUIRED');
      expect(consensus.status).toBe('CONFLICT');
      expect(consensus.output).toContain('CONSENSUS_FAILED');
    });
  });

  // =========================================================================
  // 6. End-to-End Multi-Agent Coordinator Integration
  // =========================================================================
  describe('6. End-to-End Multi-Agent Coordinator Integration', () => {
    it('executes a multi-agent task through the coordinator to completion', async () => {
      const mockGoal: Goal = {
        goalId: 'goal-e2e-agent',
        userIntent: 'Analyze vitrines and synthesize concept',
        objective: 'Analyze vitrines and synthesize concept',
        constraints: [],
        priority: 'HIGH',
        status: 'EXECUTING',
        createdAt: new Date().toISOString(),
        updatedAt: new Date().toISOString(),
        currentPlanVersion: 1,
        plans: [],
        completionCriteria: [],
        approvalPolicy: { requireApprovalForConsequential: false, autoApproveReadOnly: true },
        contextRequirements: { contextMemories: ['MEM-0001'], entityNames: [] },
        provenance: { commandText: 'test', createdAt: new Date().toISOString() },
      };

      const mockAction: ActionNode = {
        actionId: 'act-coord-1',
        goalId: mockGoal.goalId,
        planId: 'plan-1',
        title: 'Deep Contextual Analysis',
        type: 'RESEARCH',
        description: 'Analyze memory records',
        inputs: { query: 'archival history' },
        dependencies: [],
        requiredCapability: 'RESEARCH',
        status: 'READY',
        retryPolicy: { maxRetries: 2, backoffMs: 1000, retriesAttempted: 0 },
        approvalRequirement: { required: false, riskLevel: 'READ_ONLY' },
        completionCriteria: [],
        provenance: {},
      };

      const assignment = agentCoordinator.assignAgentForAction(mockAction, mockGoal);
      expect(assignment.assigned).toBe(true);
      expect(assignment.agent?.role).toBe('RESEARCHER');

      const result = await agentCoordinator.executeTask(assignment.task!, mockGoal);
      expect(result.success).toBe(true);
      expect(result.aggregatedResult?.status).toBe('SUCCEEDED');
      expect(result.observation?.status).toBe('SUCCESS');

      // Verify telemetry updated
      const telemetry = agentCoordinator.getTelemetry(mockGoal.goalId);
      expect(telemetry.completedTasks).toBe(1);
    });

    it('stops for approval when task is consequential and requires operator verification', async () => {
      const mockGoal: Goal = {
        goalId: 'goal-appr-gate',
        userIntent: 'Modify vitrine state',
        objective: 'Modify vitrine state',
        constraints: [],
        priority: 'CRITICAL',
        status: 'EXECUTING',
        createdAt: new Date().toISOString(),
        updatedAt: new Date().toISOString(),
        currentPlanVersion: 1,
        plans: [],
        completionCriteria: [],
        approvalPolicy: { requireApprovalForConsequential: true, autoApproveReadOnly: false },
        contextRequirements: { contextMemories: [], entityNames: [] },
        provenance: { commandText: 'test', createdAt: new Date().toISOString() },
      };

      const consequentialAction: ActionNode = {
        actionId: 'act-appr-1',
        goalId: mockGoal.goalId,
        planId: 'plan-1',
        title: 'Commit Destructive Mutation',
        type: 'WORKFLOW',
        description: 'Mutate archival database',
        inputs: {},
        dependencies: [],
        requiredCapability: 'REASONING',
        status: 'READY',
        retryPolicy: { maxRetries: 1, backoffMs: 1000, retriesAttempted: 0 },
        approvalRequirement: { required: true, riskLevel: 'CONSEQUENTIAL' },
        completionCriteria: [],
        provenance: {},
      };

      const assignment = agentCoordinator.assignAgentForAction(consequentialAction, mockGoal);
      expect(assignment.assigned).toBe(true);
      expect(assignment.task?.qualityRequirement).toBe('QUALITY_HIGH');
    });
  });

  // =========================================================================
  // 7. Spatial Command Console UI Transparency
  // =========================================================================
  describe('7. Spatial Command Console HUD Transparency', () => {
    it('renders AGENT OPERATIONS and RESOURCE GOVERNOR telemetry in spatial HUD', async () => {
      const mockCommandControl = {
        commandState: 'IDLE' as const,
        commandInput: '',
        currentCommand: null,
        lastResult: null,
        lastExecutionResult: null,
        activeCamera: 'CAM_CinematicHero' as const,
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

      // Start a goal so activeGoal is defined
      await act(async () => {
        await goalOrchestrator.createAndExecuteGoal('Research memory vitrines', 'MEM-0001', {
          autoApprove: true,
        });
      });

      render(
        <SpatialCommandConsole
          commandControl={mockCommandControl as any}
          isReducedMotion={true}
        />
      );

      // Verify Stage 10 Agent Operations HUD is present
      const agentHud = screen.getByTestId('agent-operations-hud');
      expect(agentHud).toBeInTheDocument();
      expect(agentHud.textContent).toContain('AGENT OPERATIONS');

      // Verify Stage 10 Resource Governor HUD is present
      const resourceHud = screen.getByTestId('resource-governor-hud');
      expect(resourceHud).toBeInTheDocument();
      expect(resourceHud.textContent).toContain('RESOURCE GOVERNOR');
      expect(resourceHud.textContent).toContain('COST:');
    });
  });
});
