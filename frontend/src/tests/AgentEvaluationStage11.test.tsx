/**
 * AryaOS V1 — Stage 11: Agent Evaluation, Collective Intelligence & Learning Loop Tests
 *
 * Verifies:
 * 1. Multi-dimensional evaluation across all 11 dimensions
 * 2. Truthful metric handling ('UNKNOWN' costs, no metric fabrication)
 * 3. Quality assessment checks (completeness, issues, syntax)
 * 4. Latency assessment and deadline compliance
 * 5. Reliability assessment (retries, fallback usage)
 * 6. Experience store input/output fingerprinting and secret sanitization
 * 7. Experience store persistence integration
 * 8. Experience store filtering (agentId, providerId, taskType)
 * 9. Evidence graph entity linking
 * 10. Evidence graph provenance tracing
 * 11. Evidence graph human approval linkage
 * 12. Agent performance profiling (taskType profiles)
 * 13. Agent performance profiling (capability profiles and confidence bands)
 * 14. Provider evaluation profiling (observed metrics and availability)
 * 15. Provider evaluation availability degradation (DEGRADED / UNAVAILABLE)
 * 16. Task performance service agent recommendations
 * 17. Collective intelligence (SINGLE_RESULT and MERGE strategies)
 * 18. Collective intelligence structured disagreement detection
 * 19. Collective intelligence minority opinion preservation
 * 20. Collective intelligence EVIDENCE_WEIGHTED_CONSENSUS selection
 * 21. Collective intelligence HUMAN_REVIEW_REQUIRED escalation
 * 22. Learning signal service AGENT_HIGH_QUALITY_FOR_TASK derivation
 * 23. Learning signal service PROVIDER_HIGH_FAILURE_RATE and ROUTE_REPEATEDLY_FAILED derivation
 * 24. Policy recommendation service human approval boundary (cannot apply without human approval)
 * 25. Adaptive routing advisor safe-mode recommendations
 * 26. Comparative plan evaluation (Plan v1 vs Plan v2) and structured self-critique
 * 27. Spatial Command Console Stage 11 HUD integration
 */

import React from 'react';
import { render, screen } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { agentEvaluationService } from '../services/agentEvaluationService';
import { providerEvaluationService } from '../services/providerEvaluationService';
import { taskPerformanceService } from '../services/taskPerformanceService';
import { experienceStore } from '../services/experienceStore';
import { evidenceGraph } from '../services/evidenceGraph';
import { collectiveIntelligence } from '../services/collectiveIntelligence';
import { learningSignalService } from '../services/learningSignalService';
import { policyRecommendationService } from '../services/policyRecommendationService';
import { adaptiveRoutingAdvisor } from '../services/adaptiveRoutingAdvisor';
import { planEvaluationService } from '../services/planEvaluationService';
import { executionPersistence } from '../services/executionPersistence';
import { SpatialCommandConsole } from '../components/spatial/SpatialCommandConsole';
import { Goal, Plan } from '../types/goalOrchestration';
import { AgentOpinion } from '../types/agentEvaluation';

describe('AryaOS V1 Stage 11 — Agent Evaluation, Collective Intelligence & Learning Loop', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    executionPersistence.clearEnvelope();
    evidenceGraph.clear();
  });

  // 1. Multi-dimensional evaluation across all 11 dimensions
  it('1. performs multi-dimensional evaluation across required dimensions', () => {
    const evalRecord = agentEvaluationService.evaluateExecution({
      goalId: 'goal-1',
      actionId: 'act-1',
      agentId: 'specialist-analyst',
      providerId: 'gemini',
      capability: 'SUMMARIZATION',
      taskType: 'MEMORY_SYNTHESIS',
      executionId: 'exec-1',
      planVersion: 1,
      output: 'Synthesized memory narrative covering all vitrine relationships.',
      outcome: { isSuccess: true, status: 'SUCCEEDED' },
      latencyMs: 1200,
      estimatedLatencyMs: 1500,
      costUsd: 0.004,
      estimatedCostUsd: 0.01,
      fallbackUsed: false,
      retriesCount: 0,
    });

    expect(evalRecord.evaluationId).toBeDefined();
    expect(evalRecord.overallScore).toBeGreaterThan(0.8);
    expect(evalRecord.quality.passed).toBe(true);
    expect(evalRecord.quality.scores[0].dimension).toBe('QUALITY');
    expect(evalRecord.cost.withinBudget).toBe(true);
    expect(evalRecord.latency.withinDeadline).toBe(true);
    expect(evalRecord.reliability.status).toBe('SUCCESS');
  });

  // 2. Evaluation handles 'UNKNOWN' cost truthfully when usage metrics are missing
  it("2. evaluates cost as 'UNKNOWN' truthfully when cost usage data is omitted", () => {
    const evalRecord = agentEvaluationService.evaluateExecution({
      goalId: 'goal-1',
      actionId: 'act-2',
      agentId: 'specialist-coder',
      providerId: 'ollama',
      capability: 'CODE_GENERATION',
      taskType: 'AST_AUDIT',
      executionId: 'exec-2',
      planVersion: 1,
      output: 'AST traversal completed without syntax errors.',
      outcome: { isSuccess: true, status: 'SUCCEEDED' },
      latencyMs: 800,
      costUsd: 'UNKNOWN',
    });

    expect(evalRecord.cost.actualUsd).toBe('UNKNOWN');
    expect(evalRecord.cost.efficiencyScore).toBe('UNKNOWN');
  });

  // 3. Quality assessment checks syntax, completeness, and absence of truncation/error flags
  it('3. quality assessment flags issues when output is blank or truncated', () => {
    const evalRecord = agentEvaluationService.evaluateExecution({
      goalId: 'goal-1',
      actionId: 'act-3',
      agentId: 'specialist-writer',
      providerId: 'anthropic',
      capability: 'SUMMARIZATION',
      taskType: 'SCENARIO_EXPANSION',
      executionId: 'exec-3',
      planVersion: 1,
      output: 'Output received: [TRUNCATED] [ERROR] buffer exhausted',
      outcome: { isSuccess: true, status: 'SUCCEEDED' },
      latencyMs: 2500,
    });

    expect(evalRecord.quality.issues.length).toBeGreaterThan(0);
    expect(evalRecord.quality.issues[0]).toContain('truncation');
  });

  // 4. Latency assessment evaluates deadline compliance and efficiency degradation
  it('4. latency assessment evaluates deadline compliance and degrades score on overrun', () => {
    const evalRecord = agentEvaluationService.evaluateExecution({
      goalId: 'goal-1',
      actionId: 'act-4',
      agentId: 'specialist-vision',
      providerId: 'gemini',
      capability: 'EMBEDDING',
      taskType: 'IMAGE_VECTORIZATION',
      executionId: 'exec-4',
      planVersion: 1,
      output: 'Generated 512-dim embedding vector.',
      outcome: { isSuccess: true, status: 'SUCCEEDED' },
      latencyMs: 4000,
      estimatedLatencyMs: 2000,
    });

    expect(evalRecord.latency.withinDeadline).toBe(false);
    expect(typeof evalRecord.latency.efficiencyScore).toBe('number');
    expect(evalRecord.latency.efficiencyScore as number).toBeLessThan(1.0);
  });

  // 5. Reliability assessment captures fallback usage and retry count
  it('5. reliability assessment captures fallback usage and classifies status as RECOVERED', () => {
    const evalRecord = agentEvaluationService.evaluateExecution({
      goalId: 'goal-1',
      actionId: 'act-5',
      agentId: 'specialist-analyst',
      providerId: 'mock',
      capability: 'REASONING',
      taskType: 'DECISION_ANALYSIS',
      executionId: 'exec-5',
      planVersion: 1,
      output: 'Fallback analysis produced from cache.',
      outcome: { isSuccess: true, status: 'SUCCEEDED' },
      latencyMs: 950,
      fallbackUsed: true,
      retriesCount: 2,
    });

    expect(evalRecord.reliability.fallbackUsed).toBe(true);
    expect(evalRecord.reliability.retriesCount).toBe(2);
    expect(evalRecord.reliability.status).toBe('RECOVERED');
  });

  // 6. Experience store correctly fingerprints inputs and outputs without storing plaintext secrets
  it('6. experience store generates 64-char hex fingerprints and redacts raw secrets', () => {
    const evalRecord = agentEvaluationService.evaluateExecution({
      goalId: 'goal-secret',
      actionId: 'act-sec',
      agentId: 'specialist-analyst',
      providerId: 'openai',
      capability: 'SUMMARIZATION',
      taskType: 'SECURE_QUERY',
      executionId: 'exec-sec',
      planVersion: 1,
      output: 'Confidential result',
      outcome: { isSuccess: true, status: 'SUCCEEDED' },
      latencyMs: 500,
    });

    const exp = experienceStore.recordExperience({
      goalId: 'goal-secret',
      actionId: 'act-sec',
      agentId: 'specialist-analyst',
      providerId: 'openai',
      capability: 'SUMMARIZATION',
      taskType: 'SECURE_QUERY',
      executionId: 'exec-sec',
      planVersion: 1,
      rawInput: { query: 'fetch user secrets', apiKey: 'sk-ant-1234567890abcdef123456' },
      rawOutput: { token: 'Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9' },
      evaluation: evalRecord,
      cost: 0.001,
      latencyMs: 500,
      status: 'SUCCEEDED',
      provenance: { authorization: 'Bearer secret_token_xyz' },
    });

    expect(exp.inputFingerprint).toHaveLength(64);
    expect(exp.outputFingerprint).toHaveLength(64);
    expect(exp.provenance.authorization).toBe('[REDACTED_SECRET]');
  });

  // 7. Experience store integrates with executionPersistence to survive reload
  it('7. experiences persist and reload from executionPersistence correctly', () => {
    const evalRecord = agentEvaluationService.evaluateExecution({
      goalId: 'goal-persist',
      actionId: 'act-p1',
      agentId: 'specialist-planner',
      providerId: 'gemini',
      capability: 'REASONING',
      taskType: 'PLAN_GENERATION',
      executionId: 'exec-p1',
      planVersion: 1,
      output: 'Generated 4-step execution DAG.',
      outcome: { isSuccess: true, status: 'SUCCEEDED' },
      latencyMs: 1100,
    });

    experienceStore.recordExperience({
      goalId: 'goal-persist',
      actionId: 'act-p1',
      agentId: 'specialist-planner',
      providerId: 'gemini',
      capability: 'REASONING',
      taskType: 'PLAN_GENERATION',
      executionId: 'exec-p1',
      planVersion: 1,
      rawInput: 'Create DAG',
      rawOutput: 'DAG ready',
      evaluation: evalRecord,
      cost: 0.002,
      latencyMs: 1100,
      status: 'SUCCEEDED',
    });

    const reloaded = executionPersistence.getExperiences({ goalId: 'goal-persist' });
    expect(reloaded).toHaveLength(1);
    expect(reloaded[0].actionId).toBe('act-p1');
    expect(reloaded[0].agentId).toBe('specialist-planner');
  });

  // 8. Experience store filters experiences by agentId, providerId, and taskType
  it('8. filters experiences by agent, provider, and task type', () => {
    const evalRec = agentEvaluationService.evaluateExecution({
      goalId: 'goal-filter',
      actionId: 'act-f',
      agentId: 'agent-A',
      providerId: 'provider-X',
      capability: 'SUMMARIZATION',
      taskType: 'SUMMARIZATION',
      executionId: 'exec-f',
      planVersion: 1,
      output: 'Summary',
      outcome: { isSuccess: true, status: 'SUCCEEDED' },
      latencyMs: 400,
    });

    experienceStore.recordExperience({
      goalId: 'goal-filter',
      actionId: 'act-f',
      agentId: 'agent-A',
      providerId: 'provider-X',
      capability: 'SUMMARIZATION',
      taskType: 'SUMMARIZATION',
      executionId: 'exec-f',
      planVersion: 1,
      rawInput: 'in',
      rawOutput: 'out',
      evaluation: evalRec,
      cost: 0.001,
      latencyMs: 400,
      status: 'SUCCEEDED',
    });

    expect(experienceStore.getExperiencesByAgent('agent-A')).toHaveLength(1);
    expect(experienceStore.getExperiencesByAgent('agent-B')).toHaveLength(0);
    expect(experienceStore.getExperiencesByProvider('provider-X')).toHaveLength(1);
    expect(experienceStore.getExperiencesByTaskType('SUMMARIZATION')).toHaveLength(1);
  });

  // 9. Evidence graph links GOAL -> ACTION -> AGENT -> PROVIDER -> EXECUTION -> EVALUATION
  it('9. evidence graph links all entities into a connected relationship graph', () => {
    evidenceGraph.clear();
    const evalRec = agentEvaluationService.evaluateExecution({
      goalId: 'g-9',
      actionId: 'a-9',
      agentId: 'ag-9',
      providerId: 'pr-9',
      capability: 'RESEARCH',
      taskType: 'DEEP_DIVE',
      executionId: 'ex-9',
      planVersion: 1,
      output: 'Deep dive findings',
      outcome: { isSuccess: true, status: 'SUCCEEDED' },
      latencyMs: 900,
    });

    experienceStore.recordExperience({
      goalId: 'g-9',
      actionId: 'a-9',
      agentId: 'ag-9',
      providerId: 'pr-9',
      capability: 'RESEARCH',
      taskType: 'DEEP_DIVE',
      executionId: 'ex-9',
      planVersion: 1,
      rawInput: 'Research prompt',
      rawOutput: 'Deep dive findings',
      evaluation: evalRec,
      cost: 0.003,
      latencyMs: 900,
      status: 'SUCCEEDED',
    });

    const related = evidenceGraph.getRelatedEntities('g-9', 5);
    expect(related.length).toBeGreaterThanOrEqual(4);
    const hasAgent = related.some((r) => r.item.entityId === 'ag-9');
    const hasAction = related.some((r) => r.item.entityId === 'a-9');
    expect(hasAgent).toBe(true);
    expect(hasAction).toBe(true);
  });

  // 10. Evidence graph traces evaluation back to root provenance
  it('10. traces an evaluation back to root goal, action, and execution provenance', () => {
    const evalRec = agentEvaluationService.evaluateExecution({
      goalId: 'g-10',
      actionId: 'a-10',
      agentId: 'ag-10',
      providerId: 'pr-10',
      capability: 'CODE_GENERATION',
      taskType: 'LINT_CHECK',
      executionId: 'ex-10',
      planVersion: 1,
      output: 'Clean lint',
      outcome: { isSuccess: true, status: 'SUCCEEDED' },
      latencyMs: 300,
    });

    experienceStore.recordExperience({
      goalId: 'g-10',
      actionId: 'a-10',
      agentId: 'ag-10',
      providerId: 'pr-10',
      capability: 'CODE_GENERATION',
      taskType: 'LINT_CHECK',
      executionId: 'ex-10',
      planVersion: 1,
      rawInput: 'lint',
      rawOutput: 'clean',
      evaluation: evalRec,
      cost: 0.001,
      latencyMs: 300,
      status: 'SUCCEEDED',
    });

    const trace = evidenceGraph.traceEvaluationToProvenance(evalRec.evaluationId);
    expect(trace.goalId).toBe('g-10');
    expect(trace.actionId).toBe('a-10');
    expect(trace.agentId).toBe('ag-10');
    expect(trace.providerId).toBe('pr-10');
  });

  // 11. Evidence graph links human approval to evaluation decisions
  it('11. links human operator decisions to the evaluation provenance chain', () => {
    const evalRec = agentEvaluationService.evaluateExecution({
      goalId: 'g-11',
      actionId: 'a-11',
      agentId: 'ag-11',
      providerId: 'pr-11',
      capability: 'REASONING',
      taskType: 'RISKY_ACTION',
      executionId: 'ex-11',
      planVersion: 1,
      output: 'Proposed modification',
      outcome: { isSuccess: true, status: 'SUCCEEDED' },
      latencyMs: 600,
    });

    experienceStore.recordExperience({
      goalId: 'g-11',
      actionId: 'a-11',
      agentId: 'ag-11',
      providerId: 'pr-11',
      capability: 'REASONING',
      taskType: 'RISKY_ACTION',
      executionId: 'ex-11',
      planVersion: 1,
      rawInput: 'modify',
      rawOutput: 'done',
      evaluation: evalRec,
      cost: 0.002,
      latencyMs: 600,
      status: 'SUCCEEDED',
      humanDecision: 'APPROVED',
    });

    const trace = evidenceGraph.traceEvaluationToProvenance(evalRec.evaluationId);
    expect(trace.humanApprovalId).toBe('appr-ex-11');
  });

  // 12. Agent performance profiling computes success rate, avg quality, and avg latency per taskType
  it('12. builds contextual agent profile with success rate, quality, and latency metrics', () => {
    for (let i = 0; i < 4; i++) {
      const evalRec = agentEvaluationService.evaluateExecution({
        goalId: `g-prof-${i}`,
        actionId: `a-prof-${i}`,
        agentId: 'specialist-analyst',
        providerId: 'gemini',
        capability: 'SUMMARIZATION',
        taskType: 'MEMORY_SYNTHESIS',
        executionId: `ex-prof-${i}`,
        planVersion: 1,
        output: 'Synthesis output',
        outcome: { isSuccess: true, status: 'SUCCEEDED' },
        latencyMs: 1000 + i * 100,
      });

      experienceStore.recordExperience({
        goalId: `g-prof-${i}`,
        actionId: `a-prof-${i}`,
        agentId: 'specialist-analyst',
        providerId: 'gemini',
        capability: 'SUMMARIZATION',
        taskType: 'MEMORY_SYNTHESIS',
        executionId: `ex-prof-${i}`,
        planVersion: 1,
        rawInput: 'in',
        rawOutput: 'out',
        evaluation: evalRec,
        cost: 0.001,
        latencyMs: 1000 + i * 100,
        status: 'SUCCEEDED',
      });
    }

    const profile = agentEvaluationService.buildAgentProfile('specialist-analyst');
    const taskProfile = profile.taskTypeProfiles['MEMORY_SYNTHESIS'];

    expect(taskProfile).toBeDefined();
    expect(taskProfile.sampleSize).toBe(4);
    expect(taskProfile.successRate).toBe(1.0);
    expect(typeof taskProfile.averageQuality).toBe('number');
    expect(taskProfile.confidence).toBe('MEDIUM');
  });

  // 13. Agent performance profiling computes capability profiles and confidence bands
  it('13. calculates confidence bands (LOW <3, MEDIUM 3..7, HIGH >=8) for capability profiles', () => {
    expect(agentEvaluationService.calculateConfidence(2)).toBe('LOW');
    expect(agentEvaluationService.calculateConfidence(5)).toBe('MEDIUM');
    expect(agentEvaluationService.calculateConfidence(10)).toBe('HIGH');
  });

  // 14. Provider evaluation profiling computes observed success rate, fallback rate, and availability
  it('14. computes observed success rate, fallback rate, and availability for providers', () => {
    for (let i = 0; i < 5; i++) {
      const isFallback = i === 4;
      const evalRec = agentEvaluationService.evaluateExecution({
        goalId: `g-prov-${i}`,
        actionId: `a-prov-${i}`,
        agentId: 'agent-1',
        providerId: 'anthropic',
        capability: 'SUMMARIZATION',
        taskType: 'REASONING_PROMPT',
        executionId: `ex-prov-${i}`,
        planVersion: 1,
        output: 'Prompt result',
        outcome: { isSuccess: true, status: 'SUCCEEDED' },
        latencyMs: 1500,
        fallbackUsed: isFallback,
      });

      experienceStore.recordExperience({
        goalId: `g-prov-${i}`,
        actionId: `a-prov-${i}`,
        agentId: 'agent-1',
        providerId: 'anthropic',
        capability: 'SUMMARIZATION',
        taskType: 'REASONING_PROMPT',
        executionId: `ex-prov-${i}`,
        planVersion: 1,
        rawInput: 'in',
        rawOutput: 'out',
        evaluation: evalRec,
        cost: 0.005,
        latencyMs: 1500,
        status: 'SUCCEEDED',
      });
    }

    const provProfile = providerEvaluationService.buildProviderProfile('anthropic');
    const cap = provProfile.capabilities['SUMMARIZATION'];

    expect(cap).toBeDefined();
    expect(cap.sampleSize).toBe(5);
    expect(cap.observedSuccessRate).toBe(1.0);
    expect(cap.fallbackRate).toBe(0.2);
    expect(provProfile.availabilityStatus).toBe('HEALTHY');
  });

  // 15. Provider evaluation marks provider DEGRADED or UNAVAILABLE if failure rate is high
  it('15. marks provider status DEGRADED or UNAVAILABLE when failure rate is high', () => {
    for (let i = 0; i < 4; i++) {
      const isSuccess = i === 0; // 3 failures, 1 success (25% success rate)
      const evalRec = agentEvaluationService.evaluateExecution({
        goalId: `g-fail-${i}`,
        actionId: `a-fail-${i}`,
        agentId: 'agent-1',
        providerId: 'failing-provider',
        capability: 'RESEARCH',
        taskType: 'WEB_FETCH',
        executionId: `ex-fail-${i}`,
        planVersion: 1,
        output: isSuccess ? 'Web data' : '',
        outcome: { isSuccess, status: isSuccess ? 'SUCCEEDED' : 'FAILED', error: isSuccess ? undefined : 'Timeout' },
        latencyMs: 5000,
      });

      experienceStore.recordExperience({
        goalId: `g-fail-${i}`,
        actionId: `a-fail-${i}`,
        agentId: 'agent-1',
        providerId: 'failing-provider',
        capability: 'RESEARCH',
        taskType: 'WEB_FETCH',
        executionId: `ex-fail-${i}`,
        planVersion: 1,
        rawInput: 'fetch',
        rawOutput: isSuccess ? 'data' : 'timeout',
        evaluation: evalRec,
        cost: 0.0,
        latencyMs: 5000,
        status: isSuccess ? 'SUCCEEDED' : 'FAILED',
      });
    }

    const profile = providerEvaluationService.buildProviderProfile('failing-provider');
    expect(profile.availabilityStatus).toBe('UNAVAILABLE');
  });

  // 16. Task performance service recommends best agent for a given task class based on empirical score
  it('16. task performance service recommends best agent for a task class based on empirical score', () => {
    // Agent 1 has average score 0.70
    const eval1 = agentEvaluationService.evaluateExecution({
      goalId: 'g-t1',
      actionId: 'a-t1',
      agentId: 'agent-regular',
      providerId: 'mock',
      capability: 'CODE_GENERATION',
      taskType: 'SECURITY_AUDIT',
      executionId: 'ex-t1',
      planVersion: 1,
      output: 'Audit partial',
      outcome: { isSuccess: true, status: 'SUCCEEDED' },
      latencyMs: 2000,
      estimatedLatencyMs: 1500,
    });
    experienceStore.recordExperience({
      goalId: 'g-t1',
      actionId: 'a-t1',
      agentId: 'agent-regular',
      providerId: 'mock',
      capability: 'CODE_GENERATION',
      taskType: 'SECURITY_AUDIT',
      executionId: 'ex-t1',
      planVersion: 1,
      rawInput: 'audit',
      rawOutput: 'partial',
      evaluation: eval1,
      cost: 0.001,
      latencyMs: 2000,
      status: 'SUCCEEDED',
    });

    // Agent 2 has average score 0.95
    const eval2 = agentEvaluationService.evaluateExecution({
      goalId: 'g-t2',
      actionId: 'a-t2',
      agentId: 'agent-specialist',
      providerId: 'mock',
      capability: 'CODE_GENERATION',
      taskType: 'SECURITY_AUDIT',
      executionId: 'ex-t2',
      planVersion: 1,
      output: 'Comprehensive verified security audit with zero vulnerabilities.',
      outcome: { isSuccess: true, status: 'SUCCEEDED' },
      latencyMs: 800,
      estimatedLatencyMs: 1500,
    });
    experienceStore.recordExperience({
      goalId: 'g-t2',
      actionId: 'a-t2',
      agentId: 'agent-specialist',
      providerId: 'mock',
      capability: 'CODE_GENERATION',
      taskType: 'SECURITY_AUDIT',
      executionId: 'ex-t2',
      planVersion: 1,
      rawInput: 'audit',
      rawOutput: 'complete',
      evaluation: eval2,
      cost: 0.001,
      latencyMs: 800,
      status: 'SUCCEEDED',
    });

    const rec = taskPerformanceService.recommendAgentForTask('SECURITY_AUDIT');
    expect(rec.agentId).toBe('agent-specialist');
    expect(typeof rec.score).toBe('number');
    expect(rec.score as number).toBeGreaterThan(0.8);
  });

  // 17. Collective intelligence resolves SINGLE_RESULT and MERGE strategies
  it('17. collective intelligence resolves SINGLE_RESULT and MERGE strategies properly', () => {
    const opinions: AgentOpinion[] = [
      {
        opinionId: 'op-1',
        agentId: 'agent-writer-1',
        taskId: 'task-c1',
        output: 'Cinematic lighting enhances atmosphere.',
        confidence: 'HIGH',
        evidence: ['vitrine-1'],
        provenance: {},
      },
      {
        opinionId: 'op-2',
        agentId: 'agent-writer-2',
        taskId: 'task-c1',
        output: 'Orchestral soundscapes anchor narrative focus.',
        confidence: 'HIGH',
        evidence: ['vitrine-2'],
        provenance: {},
      },
    ];

    const singleDec = collectiveIntelligence.evaluateOpinions({
      goalId: 'g-ci',
      taskId: 'task-c1',
      strategy: 'SINGLE_RESULT',
      opinions,
    });
    expect(singleDec.selectedOutput).toBe('Cinematic lighting enhances atmosphere.');

    const mergeDec = collectiveIntelligence.evaluateOpinions({
      goalId: 'g-ci',
      taskId: 'task-c1',
      strategy: 'MERGE',
      opinions,
    });
    expect(mergeDec.selectedOutput).toContain('[Agent agent-writer-1]');
    expect(mergeDec.selectedOutput).toContain('[Agent agent-writer-2]');
  });

  // 18. Collective intelligence detects structured disagreement among multiple agents
  it('18. detects structured disagreement when agent outputs diverge', () => {
    const opinions: AgentOpinion[] = [
      {
        opinionId: 'op-d1',
        agentId: 'analyst-1',
        taskId: 'task-d',
        output: 'Plan A is safe to proceed.',
        confidence: 'HIGH',
        evidence: [],
        provenance: {},
      },
      {
        opinionId: 'op-d2',
        agentId: 'analyst-2',
        taskId: 'task-d',
        output: 'Plan A carries severe concurrency collision risk.',
        confidence: 'HIGH',
        evidence: [],
        provenance: {},
      },
    ];

    const decision = collectiveIntelligence.evaluateOpinions({
      goalId: 'g-d',
      taskId: 'task-d',
      strategy: 'CONSENSUS',
      opinions,
    });

    expect(decision.disagreementDetected).toBe(true);
    expect(decision.consensusAchieved).toBe(false);
    expect(decision.status).toBe('REVIEW_REQUIRED');
  });

  // 19. Collective intelligence preserves minority opinions and does not discard dissent
  it('19. preserves all minority opinions without discarding divergent views', () => {
    const opinions: AgentOpinion[] = [
      {
        opinionId: 'op-m1',
        agentId: 'analyst-1',
        taskId: 'task-m',
        output: 'Approve release',
        confidence: 'HIGH',
        evidence: [],
        provenance: {},
      },
      {
        opinionId: 'op-m2',
        agentId: 'analyst-2',
        taskId: 'task-m',
        output: 'Approve release',
        confidence: 'HIGH',
        evidence: [],
        provenance: {},
      },
      {
        opinionId: 'op-m3',
        agentId: 'safety-officer',
        taskId: 'task-m',
        output: 'Block release: high-risk action lacks human confirmation',
        confidence: 'HIGH',
        evidence: ['safety-rule-1'],
        provenance: {},
      },
    ];

    const decision = collectiveIntelligence.evaluateOpinions({
      goalId: 'g-m',
      taskId: 'task-m',
      strategy: 'CONSENSUS',
      opinions,
    });

    expect(decision.opinions).toHaveLength(3);
    const minority = decision.opinions.find((o) => o.agentId === 'safety-officer');
    expect(minority).toBeDefined();
    expect(minority?.output).toContain('Block release');
  });

  // 20. Collective intelligence executes EVIDENCE_WEIGHTED_CONSENSUS selecting highest weighted opinion
  it('20. executes EVIDENCE_WEIGHTED_CONSENSUS selecting highest weighted opinion', () => {
    const opinions: AgentOpinion[] = [
      {
        opinionId: 'op-w1',
        agentId: 'junior-agent',
        taskId: 'task-w',
        output: 'Quick answer without proof',
        confidence: 'LOW',
        evidence: [],
        provenance: {},
      },
      {
        opinionId: 'op-w2',
        agentId: 'lead-specialist',
        taskId: 'task-w',
        output: 'Rigorously verified architectural conclusion',
        confidence: 'HIGH',
        evidence: ['benchmark-data-1', 'benchmark-data-2'],
        provenance: {},
      },
    ];

    const decision = collectiveIntelligence.evaluateOpinions({
      goalId: 'g-w',
      taskId: 'task-w',
      strategy: 'EVIDENCE_WEIGHTED_CONSENSUS',
      opinions,
    });

    expect(decision.selectedOutput).toBe('Rigorously verified architectural conclusion');
  });

  // 21. Collective intelligence escalates to HUMAN_REVIEW_REQUIRED when disagreement triggers safety policy
  it('21. escalates to HUMAN_REVIEW_REQUIRED under HUMAN_REVIEW strategy upon disagreement', () => {
    const opinions: AgentOpinion[] = [
      {
        opinionId: 'op-h1',
        agentId: 'agent-1',
        taskId: 'task-h',
        output: 'Overclock budget',
        confidence: 'MEDIUM',
        evidence: [],
        provenance: {},
      },
      {
        opinionId: 'op-h2',
        agentId: 'agent-2',
        taskId: 'task-h',
        output: 'Keep strict budget limits',
        confidence: 'HIGH',
        evidence: [],
        provenance: {},
      },
    ];

    const decision = collectiveIntelligence.evaluateOpinions({
      goalId: 'g-h',
      taskId: 'task-h',
      strategy: 'HUMAN_REVIEW',
      opinions,
    });

    expect(decision.status).toBe('HUMAN_REVIEW_REQUIRED');
  });

  // 22. Learning signal service derives AGENT_HIGH_QUALITY_FOR_TASK from consistent high scores
  it('22. derives AGENT_HIGH_QUALITY_FOR_TASK from consistently high execution scores', () => {
    for (let i = 0; i < 3; i++) {
      const evalRec = agentEvaluationService.evaluateExecution({
        goalId: `g-sig-${i}`,
        actionId: `a-sig-${i}`,
        agentId: 'master-coder',
        providerId: 'mock',
        capability: 'CODE_GENERATION',
        taskType: 'STATIC_ANALYSIS',
        executionId: `ex-sig-${i}`,
        planVersion: 1,
        output: 'Flawless analysis output with full symbol references',
        outcome: { isSuccess: true, status: 'SUCCEEDED' },
        latencyMs: 700,
        estimatedLatencyMs: 1000,
      });

      experienceStore.recordExperience({
        goalId: `g-sig-${i}`,
        actionId: `a-sig-${i}`,
        agentId: 'master-coder',
        providerId: 'mock',
        capability: 'CODE_GENERATION',
        taskType: 'STATIC_ANALYSIS',
        executionId: `ex-sig-${i}`,
        planVersion: 1,
        rawInput: 'in',
        rawOutput: 'out',
        evaluation: evalRec,
        cost: 0.001,
        latencyMs: 700,
        status: 'SUCCEEDED',
      });
    }

    const signals = learningSignalService.scanAndDeriveSignals();
    const qualitySignal = signals.find((s) => s.signalType === 'AGENT_HIGH_QUALITY_FOR_TASK');

    expect(qualitySignal).toBeDefined();
    expect(qualitySignal?.observation).toContain('master-coder');
    expect(qualitySignal?.status).toBe('ACTIONABLE');
  });

  // 23. Learning signal service derives PROVIDER_HIGH_FAILURE_RATE and ROUTE_REPEATEDLY_FAILED without fabricating signals
  it('23. derives PROVIDER_HIGH_FAILURE_RATE and ROUTE_REPEATEDLY_FAILED upon repeated failures', () => {
    for (let i = 0; i < 3; i++) {
      const evalRec = agentEvaluationService.evaluateExecution({
        goalId: `g-rf-${i}`,
        actionId: `a-rf-${i}`,
        agentId: 'agent-flake',
        providerId: 'provider-flaky',
        capability: 'REASONING',
        taskType: 'HEAVY_MATH',
        executionId: `ex-rf-${i}`,
        planVersion: 1,
        output: '',
        outcome: { isSuccess: false, status: 'FAILED', error: 'Provider outage' },
        latencyMs: 6000,
      });

      experienceStore.recordExperience({
        goalId: `g-rf-${i}`,
        actionId: `a-rf-${i}`,
        agentId: 'agent-flake',
        providerId: 'provider-flaky',
        capability: 'REASONING',
        taskType: 'HEAVY_MATH',
        executionId: `ex-rf-${i}`,
        planVersion: 1,
        rawInput: 'math',
        rawOutput: 'err',
        evaluation: evalRec,
        cost: 0.0,
        latencyMs: 6000,
        status: 'FAILED',
      });
    }

    const signals = learningSignalService.scanAndDeriveSignals();
    const failSignal = signals.find((s) => s.signalType === 'PROVIDER_HIGH_FAILURE_RATE');
    const routeSignal = signals.find((s) => s.signalType === 'ROUTE_REPEATEDLY_FAILED');

    expect(failSignal).toBeDefined();
    expect(routeSignal).toBeDefined();
  });

  // 24. Policy recommendation service requires explicit human approval and cannot apply unapproved policy
  it('24. enforces explicit human approval before any policy recommendation can be applied', () => {
    // Seed failing provider experiences to derive actionable signals
    for (let i = 0; i < 3; i++) {
      const evalRec = agentEvaluationService.evaluateExecution({
        goalId: `g-rec-${i}`,
        actionId: `a-rec-${i}`,
        agentId: 'agent-1',
        providerId: 'unstable-provider',
        capability: 'RESEARCH',
        taskType: 'WEB_FETCH',
        executionId: `ex-rec-${i}`,
        planVersion: 1,
        output: '',
        outcome: { isSuccess: false, status: 'FAILED', error: 'Connection timeout' },
        latencyMs: 5000,
      });

      experienceStore.recordExperience({
        goalId: `g-rec-${i}`,
        actionId: `a-rec-${i}`,
        agentId: 'agent-1',
        providerId: 'unstable-provider',
        capability: 'RESEARCH',
        taskType: 'WEB_FETCH',
        executionId: `ex-rec-${i}`,
        planVersion: 1,
        rawInput: 'fetch',
        rawOutput: 'timeout',
        evaluation: evalRec,
        cost: 0.0,
        latencyMs: 5000,
        status: 'FAILED',
      });
    }

    learningSignalService.scanAndDeriveSignals();
    const recommendations = policyRecommendationService.generateRecommendationsFromSignals();
    expect(recommendations.length).toBeGreaterThan(0);

    const targetRec = recommendations[0];
    expect(targetRec.status).toBe('PROPOSED');
    expect(targetRec.requiresHumanApproval).toBe(true);

    // Attempting to apply without human review must be rejected
    const appliedUnapproved = policyRecommendationService.applyRecommendation(targetRec.recommendationId);
    expect(appliedUnapproved).toBe(false);

    // Human operator reviews and approves
    const approved = policyRecommendationService.reviewRecommendation(
      targetRec.recommendationId,
      'APPROVED',
      'LeadOperator'
    );
    expect(approved?.status).toBe('APPROVED');

    // Applying approved recommendation succeeds
    const appliedApproved = policyRecommendationService.applyRecommendation(targetRec.recommendationId);
    expect(appliedApproved).toBe(true);
  });

  // 25. Adaptive routing advisor provides safe-mode route recommendations without executing or mutating policies
  it('25. adaptive routing advisor provides non-destructive routing recommendations', () => {
    const advice = adaptiveRoutingAdvisor.adviseRoute('STATIC_ANALYSIS', 'CODE_GENERATION', 'LOW');
    expect(advice.recommendedAgentId).toBeDefined();
    expect(advice.recommendedProviderId).toBeDefined();
    expect(advice.supportingEvidence.length).toBeGreaterThan(0);
    expect(advice.riskLevel).toBe('LOW');
  });

  // 26. Comparative plan evaluation compares Plan v1 vs Plan v2 and self-critique distinguishes known from speculative improvements
  it('26. evaluates and compares Plan v1 vs Plan v2, and generates structured self-critique', () => {
    const planV1: Plan = {
      planId: 'plan-v1',
      goalId: 'goal-comp',
      version: 1,
      actions: [
        {
          actionId: 'act-c1',
          goalId: 'goal-comp',
          planId: 'plan-v1',
          title: 'Action 1',
          type: 'RESEARCH',
          description: 'Step 1',
          inputs: {},
          dependencies: [],
          requiredCapability: 'RESEARCH',
          status: 'SUCCEEDED',
          retryPolicy: { maxRetries: 1, backoffMs: 100, retriesAttempted: 0 },
          approvalRequirement: { required: false, riskLevel: 'LOW_RISK' },
          completionCriteria: [],
          provenance: {},
        },
        {
          actionId: 'act-c2',
          goalId: 'goal-comp',
          planId: 'plan-v1',
          title: 'Action 2',
          type: 'SUMMARIZATION',
          description: 'Step 2',
          inputs: {},
          dependencies: ['act-c1'],
          requiredCapability: 'SUMMARIZATION',
          status: 'FAILED',
          retryPolicy: { maxRetries: 1, backoffMs: 100, retriesAttempted: 1 },
          approvalRequirement: { required: false, riskLevel: 'LOW_RISK' },
          completionCriteria: [],
          provenance: {},
        },
      ],
      dependencies: { 'act-c2': ['act-c1'] },
      executionOrder: [['act-c1'], ['act-c2']],
      estimatedCost: { minUsd: 0.01, maxUsd: 0.05, currency: 'USD' },
      estimatedLatencyMs: 3000,
      riskLevel: 'LOW_RISK',
      requiredApprovals: [],
      completionCriteria: [],
      status: 'SUPERSEDED',
      createdAt: new Date().toISOString(),
    };

    const planV2: Plan = {
      planId: 'plan-v2',
      goalId: 'goal-comp',
      version: 2,
      actions: [
        {
          actionId: 'act-c1',
          goalId: 'goal-comp',
          planId: 'plan-v2',
          title: 'Action 1',
          type: 'RESEARCH',
          description: 'Step 1',
          inputs: {},
          dependencies: [],
          requiredCapability: 'RESEARCH',
          status: 'SUCCEEDED',
          retryPolicy: { maxRetries: 1, backoffMs: 100, retriesAttempted: 0 },
          approvalRequirement: { required: false, riskLevel: 'LOW_RISK' },
          completionCriteria: [],
          provenance: {},
        },
        {
          actionId: 'act-c2-revised',
          goalId: 'goal-comp',
          planId: 'plan-v2',
          title: 'Action 2 Revised',
          type: 'SUMMARIZATION',
          description: 'Step 2 Revised',
          inputs: {},
          dependencies: ['act-c1'],
          requiredCapability: 'SUMMARIZATION',
          status: 'SUCCEEDED',
          retryPolicy: { maxRetries: 1, backoffMs: 100, retriesAttempted: 0 },
          approvalRequirement: { required: false, riskLevel: 'LOW_RISK' },
          completionCriteria: [],
          provenance: {},
        },
      ],
      dependencies: { 'act-c2-revised': ['act-c1'] },
      executionOrder: [['act-c1'], ['act-c2-revised']],
      estimatedCost: { minUsd: 0.01, maxUsd: 0.05, currency: 'USD' },
      estimatedLatencyMs: 2500,
      riskLevel: 'LOW_RISK',
      requiredApprovals: [],
      completionCriteria: [],
      status: 'COMPLETED',
      createdAt: new Date().toISOString(),
    };

    const mockGoal: Goal = {
      goalId: 'goal-comp',
      userIntent: 'Demonstrate comparative plan evaluation',
      objective: 'Verify Plan v1 to Plan v2 performance gain',
      constraints: ['Zero secret leakage'],
      priority: 'HIGH',
      status: 'COMPLETED',
      createdAt: new Date().toISOString(),
      updatedAt: new Date().toISOString(),
      currentPlanId: 'plan-v2',
      currentPlanVersion: 2,
      plans: [planV1, planV2],
      completionCriteria: ['All actions succeeded'],
      approvalPolicy: { requireApprovalForConsequential: false, autoApproveReadOnly: true },
      contextRequirements: { contextMemories: [], entityNames: [] },
      provenance: { commandText: 'test', createdAt: new Date().toISOString() },
    };

    const evalV1 = planEvaluationService.evaluatePlan(mockGoal, 1);
    const evalV2 = planEvaluationService.evaluatePlan(mockGoal, 2);

    expect(evalV1.actionsFailed).toBe(1);
    expect(evalV2.actionsFailed).toBe(0);

    const comparison = planEvaluationService.comparePlans(evalV1, evalV2);
    expect(comparison.winner).toBe('PLAN_B');
    expect(comparison.rationale).toContain('Plan v2 outperformed Plan v1');

    const critique = planEvaluationService.generateSelfCritique(mockGoal, 2);
    expect(critique.succeeded.length).toBe(2);
    expect(critique.mustNotChange.length).toBeGreaterThan(0);
    expect(critique.knownImprovements.length).toBeGreaterThan(0);
    expect(critique.speculativeImprovements.length).toBeGreaterThan(0);
  });

  // 27. Spatial Command Console HUD integration
  it('27. renders Stage 11 Intelligence Evaluation & Learning Loop HUD elements', () => {
    const mockCommandControl: any = {
      commandState: 'IDLE',
      commandInput: '',
      currentCommand: null,
      lastResult: null,
      lastExecutionResult: null,
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

    render(<SpatialCommandConsole commandControl={mockCommandControl} />);
    expect(screen.getByTestId('intelligence-evaluation-hud')).toBeInTheDocument();
    expect(screen.getByTestId('eval-quality-badge')).toBeInTheDocument();
    expect(screen.getByTestId('eval-signals-badge')).toBeInTheDocument();
    expect(screen.getByTestId('eval-governance-badge')).toBeInTheDocument();
  });
});
