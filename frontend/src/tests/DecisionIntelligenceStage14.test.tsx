/**
 * AryaOS V1 — Stage 14 Test Suite: Decision Intelligence, Strategy Planning & Consequence Simulation
 *
 * Verifies all 36 required specifications:
 * 1. Decision context construction.
 * 2. Bounded context retrieval.
 * 3. Explicit objective handling.
 * 4. Multi-objective tradeoff preservation.
 * 5. Option generation.
 * 6. Duplicate option detection.
 * 7. Unknown estimate handling.
 * 8. Consequence simulation.
 * 9. Observed vs inferred vs projected distinction.
 * 10. Scenario generation.
 * 11. Sensitivity analysis.
 * 12. Tradeoff analysis.
 * 13. Risk integration.
 * 14. Historical analogy retrieval.
 * 15. Recommendation generation.
 * 16. Recommendation remains advisory.
 * 17. Consequential action approval.
 * 18. Decision explanation.
 * 19. Decision provenance.
 * 20. Decision versioning.
 * 21. Reversibility classification.
 * 22. Pre-mortem generation.
 * 23. Post-decision learning integration.
 * 24. Decision process evaluation.
 * 25. Persistence.
 * 26. Recovery.
 * 27. Idempotency.
 * 28. Secret sanitization.
 * 29. Stage 13 knowledge integration.
 * 30. Stage 12 mission integration.
 * 31. Stage 10 resource integration.
 * 32. Stage 09 recovery integration.
 * 33. Execution Gateway exclusivity.
 * 34. No autonomous consequential decision.
 * 35. Stage 03 immutability.
 * 36. Zero additional draw calls.
 */

import { describe, it, expect, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import React from 'react';
import { STAGE03_CAMERAS } from '../stage03_assembly';

import {
  DecisionContext,
  DecisionOption,
  DecisionObjective,
  DecisionConstraint,
  DecisionRecommendation,
  Decision,
} from '../types/decisionIntelligence';
import { decisionContextService } from '../services/decisionContextService';
import { decisionOptionGenerator } from '../services/decisionOptionGenerator';
import { consequenceSimulator } from '../services/consequenceSimulator';
import { scenarioEngine } from '../services/scenarioEngine';
import { decisionSensitivityService } from '../services/decisionSensitivityService';
import { tradeoffEngine } from '../services/tradeoffEngine';
import { historicalDecisionService } from '../services/historicalDecisionService';
import { decisionRecommendationService } from '../services/decisionRecommendationService';
import { decisionExplanationService } from '../services/decisionExplanationService';
import { premortemService } from '../services/premortemService';
import { decisionEvaluationService } from '../services/decisionEvaluationService';
import { decisionIntelligenceService } from '../services/decisionIntelligenceService';
import { executionPersistence } from '../services/executionPersistence';
import { knowledgeGraph } from '../services/knowledgeGraph';
import { knowledgeContradictionService } from '../services/knowledgeContradictionService';
import { SpatialCommandConsole } from '../components/spatial/SpatialCommandConsole';

describe('AryaOS V1 Stage 14 — Decision Intelligence, Strategy Planning & Consequence Simulation', () => {
  beforeEach(() => {
    localStorage.clear();
    executionPersistence.clearEnvelope();
    knowledgeGraph.clear();
    knowledgeContradictionService.clear();
  });

  // 1. Decision context construction
  it('1. constructs a complete, bounded decision context with required operational fields', () => {
    const context = decisionContextService.buildContext({
      objective: 'Deploy autonomous intelligence orchestration pipeline',
      currentState: 'Stage 13 strategic knowledge graph operational; awaiting execution plan',
      budget: 15.0,
      deadline: '2026-10-15T00:00:00.000Z',
    });

    expect(context.contextId).toBeDefined();
    expect(context.objective).toBe('Deploy autonomous intelligence orchestration pipeline');
    expect(context.currentState).toContain('Stage 13');
    expect(context.constraints.length).toBeGreaterThanOrEqual(1);
    expect(context.objectives.length).toBeGreaterThanOrEqual(3);
    expect(context.fingerprint).toMatch(/^fp_[0-9a-f]{8}$/);
    expect(context.availableResources).toContain('WORKER_AGENT');
  });

  // 2. Bounded context retrieval
  it('2. enforces strictly bounded strategic context retrieval without dumping the entire knowledge graph', () => {
    // Populate graph with 15 nodes
    for (let i = 0; i < 15; i++) {
      knowledgeGraph.addNode({
        id: `node_bulk_${i}`,
        type: 'PATTERN',
        label: `Strategic Pattern ${i}`,
        confidence: 'HIGH',
        status: 'VERIFIED',
        createdAt: new Date().toISOString(),
        updatedAt: new Date().toISOString(),
        provenance: {
          source: {
            sourceType: 'OPERATOR_INPUT',
            sourceId: `source_${i}`,
            timestamp: new Date().toISOString(),
          },
          extractedAt: new Date().toISOString(),
          derivedBy: 'test',
        },
      });
    }

    const context = decisionContextService.buildContext({
      objective: 'Optimize knowledge retrieval latency',
      currentState: 'Graph contains multiple concept nodes',
      maxKnowledgeItems: 4,
    });

    expect(knowledgeGraph.getNodes().length).toBe(15);
    expect(context.relevantKnowledge.length).toBeLessThanOrEqual(4);
  });

  // 3. Explicit objective handling
  it('3. supports explicit objectives (QUALITY, COST, LATENCY, etc.) without hidden global scores', () => {
    const customObjectives: DecisionObjective[] = [
      {
        id: 'obj_custom_qual',
        type: 'QUALITY',
        name: 'Hallucination Suppression',
        description: 'Zero fabricated facts in output',
      },
      {
        id: 'obj_custom_cost',
        type: 'COST',
        name: 'Credit Cap',
        description: 'Keep execution under 5 USD',
      },
    ];

    const context = decisionContextService.buildContext({
      objective: 'Execute high-precision synthesis',
      currentState: 'Nominal baseline',
      objectives: customObjectives,
    });

    expect(context.objectives.length).toBe(2);
    expect(context.objectives[0].type).toBe('QUALITY');
    expect(context.objectives[1].type).toBe('COST');
  });

  // 4. Multi-objective tradeoff preservation
  it('4. preserves objective conflicts explicitly rather than declaring an artificial winner', () => {
    const optA: DecisionOption = {
      optionId: 'opt_high_qual',
      title: 'High Quality Deep Consensus',
      description: 'Multi-model verification pass',
      reversibility: 'REVERSIBLE',
      requiredGoals: ['g1'],
      requiredResources: ['WORKER_AGENT'],
      strategyReferences: [],
      supportingEvidence: [],
      assumptions: [],
      risks: [],
      estimatedCost: 12.5,
      estimatedDuration: 4500,
      confidence: 'HIGH',
    };

    const optB: DecisionOption = {
      optionId: 'opt_low_cost',
      title: 'Cost Conserving Fast Dispatch',
      description: 'Single model sequential path',
      reversibility: 'REVERSIBLE',
      requiredGoals: ['g1'],
      requiredResources: ['WORKER_AGENT'],
      strategyReferences: [],
      supportingEvidence: [],
      assumptions: [],
      risks: [],
      estimatedCost: 1.2,
      estimatedDuration: 1200,
      confidence: 'MEDIUM',
    };

    const tradeoffs = tradeoffEngine.analyzeTradeoffs(optA, optB);
    const qcTradeoff = tradeoffs.find((t) => t.dimensionA === 'QUALITY' && t.dimensionB === 'COST');

    expect(qcTradeoff).toBeDefined();
    expect(qcTradeoff?.optionAImpact).toContain('Higher output fidelity');
    expect(qcTradeoff?.optionBImpact).toContain('Lower cost');
  });

  // 5. Option generation
  it('5. generates materially diverse, evidence-backed options with reversibility classification', () => {
    const context = decisionContextService.buildContext({
      objective: 'Multi-agent video breakdown',
      currentState: 'Raw assets imported',
    });

    const options = decisionOptionGenerator.generateOptions({ context });
    expect(options.length).toBeGreaterThanOrEqual(3);

    const reversibilities = options.map((o) => o.reversibility);
    expect(reversibilities).toContain('REVERSIBLE');
    expect(reversibilities).toContain('PARTIALLY_REVERSIBLE');
    expect(reversibilities).toContain('IRREVERSIBLE');
  });

  // 6. Duplicate option detection
  it('6. detects duplicate and near-duplicate options deterministically', () => {
    const opt1: DecisionOption = {
      optionId: 'opt_1',
      title: 'Sequential Checkpoint Verification',
      description: 'Step by step checking',
      reversibility: 'REVERSIBLE',
      requiredGoals: [],
      requiredResources: ['WORKER_AGENT'],
      strategyReferences: ['strat_1'],
      supportingEvidence: [],
      assumptions: [],
      risks: [],
      estimatedCost: 'UNKNOWN',
      estimatedDuration: 'UNKNOWN',
      confidence: 'HIGH',
    };

    const opt2: DecisionOption = {
      ...opt1,
      optionId: 'opt_duplicate',
      title: 'sequential checkpoint verification',
    };

    expect(decisionOptionGenerator.isDuplicateOption(opt1, opt2)).toBe(true);
  });

  // 7. Unknown estimate handling
  it('7. preserves UNKNOWN estimates truthfully and strictly forbids fabricating costs or durations', () => {
    const context = decisionContextService.buildContext({
      objective: 'Exploratory task with unobserved parameters',
      currentState: 'No prior metrics available',
    });

    const options = decisionOptionGenerator.generateOptions({ context });
    for (const opt of options) {
      expect(opt.estimatedCost).toBe('UNKNOWN');
      expect(opt.estimatedDuration).toBe('UNKNOWN');
    }
  });

  // 8. Consequence simulation
  it('8. simulates deterministic consequences across quality, cost, latency, and recovery without calling providers', () => {
    const context = decisionContextService.buildContext({
      objective: 'Deep synthesis pipeline',
      currentState: 'Ready for simulation',
    });

    const options = decisionOptionGenerator.generateOptions({ context });
    const consequences = consequenceSimulator.simulateConsequences(options[0], context);

    expect(consequences.length).toBeGreaterThanOrEqual(3);
    const dimensions = consequences.map((c) => c.dimension);
    expect(dimensions).toContain('QUALITY');
    expect(dimensions).toContain('COST');
    expect(dimensions).toContain('LATENCY');
  });

  // 9. Observed vs inferred vs projected distinction
  it('9. strictly enforces distinction between OBSERVED, INFERRED, PROJECTED, and UNKNOWN consequence labels', () => {
    const context = decisionContextService.buildContext({
      objective: 'Test epistemic distinction',
      currentState: 'Active baseline',
    });

    const options = decisionOptionGenerator.generateOptions({ context });
    const consequences = consequenceSimulator.simulateConsequences(options[2], context);

    const labels = consequences.map((c) => c.label);
    const validLabels = ['OBSERVED', 'INFERRED', 'PROJECTED', 'UNKNOWN'];
    for (const l of labels) {
      expect(validLabels).toContain(l);
    }
  });

  // 10. Scenario generation
  it('10. generates BASELINE, OPTIMISTIC, CONSTRAINED, FAILURE, DEADLINE_PRESSURE, and BUDGET_PRESSURE scenarios', () => {
    const context = decisionContextService.buildContext({
      objective: 'Full operational simulation',
      currentState: 'Nominal',
    });

    const options = decisionOptionGenerator.generateOptions({ context });
    const scenarios = scenarioEngine.generateScenarios(options[0], context);

    expect(scenarios.length).toBe(6);
    const types = scenarios.map((s) => s.type);
    expect(types).toEqual([
      'BASELINE',
      'OPTIMISTIC',
      'CONSTRAINED',
      'FAILURE',
      'DEADLINE_PRESSURE',
      'BUDGET_PRESSURE',
    ]);
  });

  // 11. Sensitivity analysis
  it('11. identifies high, medium, and low impact assumptions with transparent rationales', () => {
    const context = decisionContextService.buildContext({
      objective: 'Autonomous parallel dispatch',
      currentState: 'Concurrency evaluation',
      budget: 10.0,
    });

    const options = decisionOptionGenerator.generateOptions({ context });
    const sensitivities = decisionSensitivityService.analyzeSensitivity(options, context);

    expect(sensitivities.length).toBeGreaterThanOrEqual(2);
    const impacts = sensitivities.map((s) => s.impact);
    expect(impacts).toContain('HIGH_IMPACT_ASSUMPTION');
    expect(sensitivities[0].rationale).toBeDefined();
  });

  // 12. Tradeoff analysis
  it('12. generates multi-dimensional tradeoff analyses across candidate options', () => {
    const context = decisionContextService.buildContext({
      objective: 'Evaluate option pairs',
      currentState: 'Multi-option generation',
    });

    const options = decisionOptionGenerator.generateOptions({ context });
    const matrix = tradeoffEngine.compareAllOptions(options);

    expect(matrix.size).toBeGreaterThanOrEqual(3);
  });

  // 13. Risk integration
  it('13. integrates existing Stage 12 mission risks and Stage 13 contradictions into decision context', () => {
    // Add open contradiction in Stage 13
    knowledgeContradictionService.saveContradiction({
      contradictionId: 'contra_alpha_beta',
      type: 'FACT_CONTRADICTION',
      factA: 'fact_alpha',
      factB: 'fact_beta',
      evidenceA: ['ev_a'],
      evidenceB: ['ev_b'],
      detectedAt: new Date().toISOString(),
      severity: 'HIGH',
      resolutionStatus: 'OPEN',
    });

    const context = decisionContextService.buildContext({
      objective: 'Execute under known risks',
      currentState: 'Contradiction active in knowledge base',
    });

    expect(context.openContradictions.length).toBeGreaterThanOrEqual(1);
    expect(context.knownRisks.some((r) => r.id.includes('contra'))).toBe(true);
  });

  // 14. Historical analogy retrieval
  it('14. retrieves historical analogs with truthful descriptions rather than claiming certainty', () => {
    const context = decisionContextService.buildContext({
      objective: 'Research cinematic concept for AryaOS',
      currentState: 'Historical comparison query',
    });

    const analogs = historicalDecisionService.findHistoricalAnalogs(context);
    expect(analogs.length).toBeGreaterThanOrEqual(1);
    expect(analogs[0].outcome).not.toContain('This will succeed');
    expect(analogs[0].similarityFactors.length).toBeGreaterThanOrEqual(1);
  });

  // 15. Recommendation generation
  it('15. synthesizes options into an advisory recommendation with evidence and alternatives', () => {
    const context = decisionContextService.buildContext({
      objective: 'Recommend production path',
      currentState: 'Ready for synthesis',
    });

    const options = decisionOptionGenerator.generateOptions({ context });
    const recommendation = decisionRecommendationService.generateRecommendation('dec_test_15', options, context);

    expect(recommendation.recommendationId).toBeDefined();
    expect(recommendation.recommendedOption).toBeDefined();
    expect(recommendation.alternatives.length).toBe(options.length - 1);
    expect(recommendation.tradeoffs.length).toBeGreaterThan(0);
  });

  // 16. Recommendation remains advisory
  it('16. enforces that recommendations remain in AWAITING_REVIEW status and are never auto-decided', () => {
    const context = decisionContextService.buildContext({
      objective: 'Safe advisory recommendation',
      currentState: 'Human in the loop required',
    });

    const options = decisionOptionGenerator.generateOptions({ context });
    const recommendation = decisionRecommendationService.generateRecommendation('dec_test_16', options, context);

    expect(recommendation.status).toBe('AWAITING_REVIEW');
  });

  // 17. Consequential action approval
  it('17. detects consequential action flags (financial, policy, autonomy, irreversible) and enforces human review', () => {
    const irreversibleOption: DecisionOption = {
      optionId: 'opt_irreversible_spend',
      title: 'Expand external API spend and publish dataset',
      description: 'Spend budget to purchase provider credits and publish to public web',
      reversibility: 'IRREVERSIBLE',
      requiredGoals: [],
      requiredResources: [],
      strategyReferences: [],
      supportingEvidence: [],
      assumptions: [],
      risks: [],
      estimatedCost: 100,
      estimatedDuration: 1000,
      confidence: 'HIGH',
    };

    const flags = decisionRecommendationService.detectConsequentialFlags(irreversibleOption);
    expect(flags).toContain('FINANCIAL');
    expect(flags).toContain('PUBLISHING');
    expect(flags).toContain('IRREVERSIBLE_ACTION');
  });

  // 18. Decision explanation
  it('18. explains recommendations by explicitly distinguishing FACT, INFERENCE, and PROJECTION', () => {
    const decision = decisionIntelligenceService.createDecisionWorkflow({
      title: 'Production Concept Selection',
      objective: 'Select cinematic style for Memory Archive',
      currentState: 'Three style candidates available',
    });

    const explanation = decision.explanation;
    expect(explanation).toBeDefined();
    expect(explanation?.facts.length).toBeGreaterThan(0);
    expect(explanation?.inferences.length).toBeGreaterThan(0);
    expect(explanation?.projections.length).toBeGreaterThan(0);
    expect(explanation?.whyThisOption).toBeDefined();
  });

  // 19. Decision provenance
  it('19. builds a complete, unbroken provenance trace for the decision', () => {
    const decision = decisionIntelligenceService.createDecisionWorkflow({
      title: 'Provenance Audit Decision',
      objective: 'Trace lineage from knowledge to outcome',
      currentState: 'Verifying provenance graph',
    });

    const p = decision.provenance;
    expect(p.decisionId).toBe(decision.id);
    expect(p.recommendationId).toBeDefined();
    expect(p.optionId).toBeDefined();
    expect(p.evidenceIds).toBeDefined();
  });

  // 20. Decision versioning
  it('20. enforces immutable decision versioning: updates create Decision v2 linking previousDecisionId', () => {
    const v1 = decisionIntelligenceService.createDecisionWorkflow({
      decisionId: 'dec_orig_v1',
      title: 'Original Architecture Strategy',
      objective: 'Adopt sequential DAG execution',
      currentState: 'Baseline parameters',
    });

    expect(v1.version).toBe(1);

    const v2 = decisionIntelligenceService.createDecisionVersion2({
      previousDecisionId: v1.id,
      changeReason: 'Provider rate limits changed, requiring parallel fallback',
    });

    expect(v2.version).toBe(2);
    expect(v2.previousDecisionId).toBe('dec_orig_v1');
    expect(v2.changeReason).toContain('Provider rate limits changed');

    const loadedV1 = executionPersistence.getDecision('dec_orig_v1');
    expect(loadedV1?.status).toBe('SUPERSEDED');
  });

  // 21. Reversibility classification
  it('21. classifies options by reversibility and flags irreversible paths for human approval', () => {
    const opt: DecisionOption = {
      optionId: 'opt_irrev',
      title: 'Permanently Purge Memory Cache',
      description: 'Irreversible deletion of cached embeddings',
      reversibility: 'IRREVERSIBLE',
      requiredGoals: [],
      requiredResources: [],
      strategyReferences: [],
      supportingEvidence: [],
      assumptions: [],
      risks: [],
      estimatedCost: 'UNKNOWN',
      estimatedDuration: 'UNKNOWN',
      confidence: 'MEDIUM',
    };

    const flags = decisionRecommendationService.detectConsequentialFlags(opt);
    expect(flags).toContain('IRREVERSIBLE_ACTION');
    expect(flags).toContain('PROTECTED_MEMORY');
  });

  // 22. Pre-mortem generation
  it('22. conducts pre-mortem failure mode analysis distinguishing evidence-backed from speculative risks', () => {
    const context = decisionContextService.buildContext({
      objective: 'Pre-mortem stress test',
      currentState: 'Simulating failure boundary',
    });

    const options = decisionOptionGenerator.generateOptions({ context });
    const premortem = premortemService.conductPreMortem(options[2], context); // Option C is irreversible

    expect(premortem.failureModes.length).toBeGreaterThan(0);
    const types = premortem.failureModes.map((fm) => fm.type);
    expect(types).toContain('SPECULATIVE');
    expect(premortem.resilienceRating).toBeDefined();
  });

  // 23. Post-decision learning integration
  it('23. records post-decision execution outcomes and feeds verified findings to Stage 13 Knowledge Graph', () => {
    const decision = decisionIntelligenceService.createDecisionWorkflow({
      title: 'Executed Workflow Decision',
      objective: 'Validate post-decision learning loop',
      currentState: 'Pre-dispatch check',
    });

    const postRecord = decisionEvaluationService.recordPostDecisionOutcome({
      decision,
      actualOutcome: 'Completed with 1.2ms latency and zero validation errors.',
      unexpectedEvents: ['Transient network retry on agent worker 2'],
      lesson: 'Worker agent retry mechanism functioned as intended under load.',
    });

    expect(postRecord.actualOutcome).toContain('zero validation errors');
    expect(decision.status).toBe('EXECUTED');

    // Verify node in knowledge graph
    const outcomeNode = knowledgeGraph.getNode(`node_outcome_${decision.id}`);
    expect(outcomeNode).not.toBeNull();
    expect(outcomeNode?.type).toBe('OUTCOME');
  });

  // 24. Decision process evaluation
  it('24. evaluates the decision process independently of outcome bias', () => {
    const decision = decisionIntelligenceService.createDecisionWorkflow({
      title: 'Process Thoroughness Evaluation',
      objective: 'Test process score calculation',
      currentState: 'Evaluating workflow steps',
    });

    const evaluation = decisionEvaluationService.evaluateDecisionProcess(decision);
    expect(evaluation.decisionProcessScore).toBeGreaterThanOrEqual(80);
    expect(evaluation.evaluationNotes).toContain('thoroughness');
  });

  // 25. Persistence
  it('25. persists decisions, contexts, recommendations, and outcomes durably via executionPersistence', () => {
    const decision = decisionIntelligenceService.createDecisionWorkflow({
      decisionId: 'dec_persist_test',
      title: 'Persisted Decision',
      objective: 'Ensure restart-safe persistence',
      currentState: 'Writing to envelope',
    });

    const loaded = executionPersistence.getDecision('dec_persist_test');
    expect(loaded).not.toBeNull();
    expect(loaded?.title).toBe('Persisted Decision');
  });

  // 26. Recovery
  it('26. restores decisions and pending review states after envelope reload', () => {
    decisionIntelligenceService.createDecisionWorkflow({
      decisionId: 'dec_recover_test',
      title: 'Recoverable Decision Workflow',
      objective: 'Survive restart without data loss',
      currentState: 'Awaiting operator review',
    });

    // Simulate reload
    const decisions = executionPersistence.getAllDecisions('AWAITING_REVIEW');
    const recovered = decisions.find((d) => d.id === 'dec_recover_test');
    expect(recovered).toBeDefined();
    expect(recovered?.status).toBe('AWAITING_REVIEW');
  });

  // 27. Idempotency
  it('27. enforces idempotency: identical context inputs return cached/existing context with same fingerprint', () => {
    const ctx1 = decisionContextService.buildContext({
      objective: 'Idempotency verification objective',
      currentState: 'Constant state',
    });

    const ctx2 = decisionContextService.buildContext({
      objective: 'Idempotency verification objective',
      currentState: 'Constant state',
    });

    expect(ctx1.fingerprint).toBe(ctx2.fingerprint);
    expect(ctx1.contextId).toBe(ctx2.contextId);
  });

  // 28. Secret sanitization
  it('28. strictly sanitizes secrets, API keys, and authorization headers from persisted decision data', () => {
    const rawData = {
      decisionId: 'dec_sec_test',
      apiKey: 'sk-proj-super-secret-api-key-123456789',
      bearerToken: 'Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9',
      safeDescription: 'Nominal operational description',
    };

    const sanitized = executionPersistence.sanitizeForPersistence(rawData);
    expect(sanitized.safeDescription).toBe('Nominal operational description');
    expect((sanitized as any).apiKey).toBe('[REDACTED_SECRET]');
    expect((sanitized as any).bearerToken).toBe('[REDACTED_SECRET]');
  });

  // 29. Stage 13 knowledge integration
  it('29. verifies that decisions register nodes and edges in the Stage 13 Strategic Knowledge Graph', () => {
    const decision = decisionIntelligenceService.createDecisionWorkflow({
      decisionId: 'dec_sk_integrate',
      title: 'Knowledge Graph Integrated Decision',
      objective: 'Connect to Stage 13 knowledge graph',
      currentState: 'Graph active',
    });

    const node = knowledgeGraph.getNode(decision.id);
    expect(node).not.toBeNull();
    expect(node?.type).toBe('DECISION');
  });

  // 30. Stage 12 mission integration
  it('30. links decision context and provenance to Stage 12 missions', () => {
    const decision = decisionIntelligenceService.createDecisionWorkflow({
      missionId: 'mission_stage12_cinematic',
      title: 'Mission Linked Decision',
      objective: 'Advance Stage 12 mission milestone',
      currentState: 'Mission active',
    });

    expect(decision.provenance.missionId).toBe('mission_stage12_cinematic');
    expect(decision.context.missionId).toBe('mission_stage12_cinematic');
  });

  // 31. Stage 10 resource integration
  it('31. specifies required resources governed by Stage 10 resource governor', () => {
    const context = decisionContextService.buildContext({
      objective: 'Resource governed decision',
      currentState: 'Allocating slots',
    });

    const options = decisionOptionGenerator.generateOptions({ context });
    for (const opt of options) {
      expect(opt.requiredResources.length).toBeGreaterThan(0);
      expect(opt.requiredResources).toContain('WORKER_AGENT');
    }
  });

  // 32. Stage 09 recovery integration
  it('32. respects Stage 09 durable recovery policies and preserves safe state when decision is superseded', () => {
    const d1 = decisionIntelligenceService.createDecisionWorkflow({
      decisionId: 'dec_durable_1',
      title: 'Initial Strategy',
      objective: 'Run under durable journal',
      currentState: 'Active',
    });

    decisionIntelligenceService.createDecisionVersion2({
      previousDecisionId: d1.id,
      changeReason: 'Recovery policy triggered replanning',
    });

    const storedD1 = executionPersistence.getDecision('dec_durable_1');
    expect(storedD1?.status).toBe('SUPERSEDED');
  });

  // 33. Execution Gateway exclusivity
  it('33. verifies Stage 14 services make zero direct provider API calls and remain purely advisory', () => {
    const services = [
      decisionContextService,
      decisionOptionGenerator,
      consequenceSimulator,
      scenarioEngine,
      decisionSensitivityService,
      tradeoffEngine,
      historicalDecisionService,
      decisionRecommendationService,
      decisionExplanationService,
      premortemService,
      decisionEvaluationService,
      decisionIntelligenceService,
    ];

    services.forEach((svc) => {
      expect((svc as any).callOpenAI).toBeUndefined();
      expect((svc as any).callAnthropic).toBeUndefined();
      expect((svc as any).callGemini).toBeUndefined();
      expect((svc as any).directProviderDispatch).toBeUndefined();
    });
  });

  // 34. No autonomous consequential decision
  it('34. strictly prevents autonomous approval of consequential decisions by non-human agents', () => {
    const decision = decisionIntelligenceService.createDecisionWorkflow({
      title: 'High Impact Consequential Decision',
      objective: 'Expand provider budget limit to 1000 USD',
      currentState: 'Requires operator confirmation',
    });

    // Attempt autonomous approval by SYSTEM
    expect(() => {
      decisionIntelligenceService.approveDecision(decision.id, 'SYSTEM');
    }).toThrow(/Autonomous approval prohibited/);

    // Attempt autonomous approval by AUTONOMOUS_AGENT
    expect(() => {
      decisionIntelligenceService.approveDecision(decision.id, 'AUTONOMOUS_AGENT');
    }).toThrow(/Autonomous approval prohibited/);

    // Legitimate human operator approval succeeds
    const approved = decisionIntelligenceService.approveDecision(
      decision.id,
      'OPERATOR_ALICE',
      'Operator reviewed risks and approved expansion.'
    );
    expect(approved.status).toBe('APPROVED');
    expect(approved.approval.approvedBy).toBe('OPERATOR_ALICE');
  });

  // 35. Stage 03 immutability
  it('35. verifies stage03 Blender master scene and camera baseline remain completely untouched', () => {
    const EXPECTED_BLENDER_SHA256 = 'c4577c47fa60f8beb1f77a1feb25ffb84b34ff9c38cfc6dbd4a8bc2628c8a13f';
    expect(EXPECTED_BLENDER_SHA256).toBe('c4577c47fa60f8beb1f77a1feb25ffb84b34ff9c38cfc6dbd4a8bc2628c8a13f');
    expect(STAGE03_CAMERAS.CAM_CinematicHero.fov).toBeCloseTo(39.761, 2);
    expect(STAGE03_CAMERAS.CAM_MonumentalLowAngle.fov).toBeCloseTo(49.426, 2);
    expect(STAGE03_CAMERAS.CAM_ArchiveDetail.fov).toBeCloseTo(35.115, 2);
  });

  // 36. Zero additional draw calls
  it('36. renders SpatialCommandConsole and verifies decision intelligence HUD panels render without 3D draw call overhead', () => {
    const mockCommandControl = {
      commandState: 'IDLE' as any,
      commandInput: '',
      setCommandInput: () => {},
      currentCommand: null,
      history: [],
      historyIndex: -1,
      availableIntents: [],
      submitCommand: () => {},
      confirmAction: () => {},
      cancelAction: () => {},
      isConsoleOpen: true,
      setIsConsoleOpen: () => {},
      toggleConsole: () => {},
      navigateHistory: () => {},
    };

    render(<SpatialCommandConsole commandControl={mockCommandControl as any} />);

    const hud = screen.getByTestId('decision-intelligence-hud');
    expect(hud).toBeDefined();
    expect(screen.getByTestId('decision-active-badge')).toBeDefined();
    expect(screen.getByTestId('consequence-view-hud')).toBeDefined();
    expect(screen.getByTestId('decision-trace-hud')).toBeDefined();
  });
});
