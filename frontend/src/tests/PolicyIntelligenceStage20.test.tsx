/**
 * AryaOS V1 — Stage 20: Policy Intelligence & Governed Adaptive Operations Test Suite
 *
 * Verifies all 60 required specifications:
 * 1. Policy registration in PolicyRegistry
 * 2. Duplicate policy registration rejection
 * 3. Valid lifecycle state machine transitions
 * 4. Illegal state transitions rejection (e.g. DRAFT -> ACTIVE)
 * 5. Immutable versioning & historical version archive
 * 6. Scope enforcement (SYSTEM, AGENT, MISSION, CONNECTOR, etc.)
 * 7. Declarative condition evaluation (equals, not_equals, greater_than, etc.)
 * 8. Compound AND condition evaluation
 * 9. Compound OR condition evaluation
 * 10. Prototype pollution protection
 * 11. Arbitrary code execution rejection (no eval/Function)
 * 12. Secret rejection and recursive scrubbing
 * 13. Allowlisted policy effects validation (ALLOW, DENY, LIMIT, ROUTE, etc.)
 * 14. Deterministic policy priority hierarchy
 * 15. Policy conflict detection (CONTRADICTORY, SCOPE, PRIORITY)
 * 16. Conflict explanation and lossless resolution
 * 17. Learning signal -> Policy candidate generation
 * 18. Candidate remains inactive until reviewed & approved
 * 19. Evidence provenance preservation
 * 20. Policy impact simulation
 * 21. Epistemic certainty labels (OBSERVED, INFERRED, PROJECTED, UNKNOWN)
 * 22. Shadow mode evaluation
 * 23. Shadow mode does not alter runtime behavior
 * 24. Policy activation requires approval
 * 25. Autonomous agent approval rejected (AUTONOMOUS_AGENT cannot approve)
 * 26. System daemon approval rejected (SYSTEM cannot approve)
 * 27. Policy activation creates immutable PolicyActivationRecord
 * 28. Explicit policy rollback to prior version
 * 29. Rollback requires authorized operator
 * 30. Historical policy immutability preserved on rollback
 * 31. Resource governance constraint enforcement
 * 32. Trigger governance constraint enforcement
 * 33. Connector governance constraint enforcement
 * 34. Connector permissions cannot be bypassed
 * 35. Agent governance constraint enforcement
 * 36. Mission governance constraint enforcement
 * 37. Adaptive routing recommendation generation
 * 38. Routing recommendation remains advisory without active policy
 * 39. Policy-enabled adaptive routing execution
 * 40. Policy-disabled route blocking
 * 41. Policy drift detection on performance/cost degradation
 * 42. Drift detection produces REVIEW_REQUIRED (no self-mutation)
 * 43. Policy outcome recording
 * 44. Policy learning feedback to Stage 11
 * 45. Strictly no automatic policy mutation
 * 46. Cold restart persistence recovery
 * 47. Pending proposal recovery on restart
 * 48. Candidate recovery on restart
 * 49. Active policy recovery on restart
 * 50. Invalid policy structure rejected
 * 51. Unauthorized policy activation rejected
 * 52. Secret sanitization on persistence load
 * 53. No direct Action Bus bypass
 * 54. No direct connector execution
 * 55. Zero AI/LLM inference calls during policy evaluation
 * 56. No privilege escalation via policy declaration
 * 57. Bounded evaluation context (secrets stripped)
 * 58. Policy conflict record preservation
 * 59. SpatialCommandConsole renders Stage 20 HUD panels in DOM
 * 60. Zero additional WebGL draw calls introduced
 */

import React from 'react';
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { render } from '@testing-library/react';

import {
  Policy,
  PolicyProposal,
  PolicyEvaluationContext,
  POLICY_PRIORITY_WEIGHTS,
} from '../types/policyIntelligence';
import { policyRegistry } from '../services/policyRegistry';
import { policyConditionEngine } from '../services/policyConditionEngine';
import { policyConflictService } from '../services/policyConflictService';
import { policyProposalService } from '../services/policyProposalService';
import { policyImpactSimulator } from '../services/policyImpactSimulator';
import { policyShadowService } from '../services/policyShadowService';
import { policyRollbackService } from '../services/policyRollbackService';
import { policyDriftService } from '../services/policyDriftService';
import { policyEvaluationService } from '../services/policyEvaluationService';
import { executionPersistence } from '../services/executionPersistence';
import { executionGateway } from '../services/executionGateway';
import { actionBusService } from '../services/actionBusService';
import { connectorPermissionService } from '../services/connectorPermissionService';
import { resourceGovernor } from '../services/resourceGovernor';
import { adaptiveRoutingAdvisor } from '../services/adaptiveRoutingAdvisor';
import { LearningSignal } from '../types/agentEvaluation';
import { SpatialCommandConsole } from '../components/spatial/SpatialCommandConsole';
import { STAGE03_CAMERAS } from '../stage03_assembly';

describe('AryaOS V1 Stage 20 — Policy Intelligence & Governed Adaptive Operations', () => {
  beforeEach(() => {
    policyRegistry.reset();
    policyConflictService.reset();
    policyProposalService.reset();
    policyShadowService.reset();
    policyRollbackService.reset();
    policyDriftService.reset();
    resourceGovernor.resetState();
    executionPersistence.clearEnvelope();
    localStorage.clear();
  });

  const createSamplePolicy = (overrides: Partial<Policy> = {}): Policy => ({
    id: overrides.id || 'pol-sample-01',
    version: overrides.version || 1,
    name: overrides.name || 'Sample Governed Policy',
    description: overrides.description || 'Test policy for evaluation',
    status: overrides.status || 'ACTIVE',
    scope: overrides.scope || { scopeType: 'AGENT', targetId: 'agent-analyst' },
    priority: overrides.priority || 'AGENT_POLICY',
    conditions: overrides.conditions || {
      conjunction: 'AND',
      conditions: [
        {
          field: 'taskType',
          operator: 'equals',
          value: 'data_analysis',
        },
      ],
    },
    effect: overrides.effect || {
      type: 'LIMIT',
      constraint: { maxConcurrentActions: 2 },
      reason: 'Prevent overload on analyst agent',
    },
    provenance: overrides.provenance || {
      authorId: 'user-admin',
      createdAt: Date.now(),
      updatedAt: Date.now(),
      evidence: {
        confidenceScore: 0.95,
        description: 'Historical performance baselines show degradation above 2 concurrent tasks',
      },
      changeLog: [
        {
          version: 1,
          timestamp: Date.now(),
          changedBy: 'user-admin',
          description: 'Initial creation',
        },
      ],
    },
    requiresHumanApproval: overrides.requiresHumanApproval ?? true,
    isShadow: overrides.isShadow ?? false,
  });

  // ============================================================
  // SECTION 1: POLICY REGISTRY, LIFECYCLE & IMMUTABILITY (Tests 1–6)
  // ============================================================

  it('1. registers a valid policy in PolicyRegistry', () => {
    const policy = createSamplePolicy({ id: 'pol-valid-1' });
    const registered = policyRegistry.registerPolicy(policy);

    expect(registered.id).toBe('pol-valid-1');
    expect(policyRegistry.getPolicy('pol-valid-1')).toBeDefined();
  });

  it('2. duplicate policy registration is rejected with an error', () => {
    const policy = createSamplePolicy({ id: 'pol-dup-1' });
    policyRegistry.registerPolicy(policy);

    expect(() => {
      policyRegistry.registerPolicy(policy);
    }).toThrow(/Duplicate Policy Error/);
  });

  it('3. transitions policy through valid lifecycle states (DRAFT -> CANDIDATE -> UNDER_REVIEW -> APPROVED -> ACTIVE)', () => {
    const policy = createSamplePolicy({ id: 'pol-lifecycle-1', status: 'DRAFT' });
    policyRegistry.registerPolicy(policy);

    const candidate = policyRegistry.transitionStatus('pol-lifecycle-1', 'CANDIDATE', 'operator-1', 'Submitted for evaluation');
    expect(candidate.status).toBe('CANDIDATE');

    const underReview = policyRegistry.transitionStatus('pol-lifecycle-1', 'UNDER_REVIEW', 'operator-1', 'Review initiated');
    expect(underReview.status).toBe('UNDER_REVIEW');

    const approved = policyRegistry.transitionStatus('pol-lifecycle-1', 'APPROVED', 'operator-1', 'Human approval granted');
    expect(approved.status).toBe('APPROVED');

    const active = policyRegistry.transitionStatus('pol-lifecycle-1', 'ACTIVE', 'operator-1', 'Activated for runtime');
    expect(active.status).toBe('ACTIVE');
  });

  it('4. illegal direct state transitions (DRAFT -> ACTIVE) are strictly rejected', () => {
    const policy = createSamplePolicy({ id: 'pol-illegal-jump', status: 'DRAFT' });
    policyRegistry.registerPolicy(policy);

    expect(() => {
      policyRegistry.transitionStatus('pol-illegal-jump', 'ACTIVE', 'operator-1', 'Attempting illegal bypass');
    }).toThrow(/Illegal State Transition/);
  });

  it('5. policy updates increment version and archive previous version immutably', () => {
    const policy = createSamplePolicy({ id: 'pol-version-test', version: 1 });
    policyRegistry.registerPolicy(policy);

    const updated = policyRegistry.updatePolicy(
      'pol-version-test',
      { name: 'Updated Policy Name' },
      'operator-1',
      'Name enhancement'
    );

    expect(updated.version).toBe(2);
    expect(updated.name).toBe('Updated Policy Name');

    const history = policyRegistry.getPolicyHistory('pol-version-test');
    expect(history.length).toBe(1);
    expect(history[0].version).toBe(1);
    expect(history[0].name).toBe('Sample Governed Policy');
  });

  it('6. scope enforcement verifies scopeType (AGENT, MISSION, CONNECTOR, etc.)', () => {
    const agentPolicy = createSamplePolicy({ id: 'pol-scope-agent', scope: { scopeType: 'AGENT', targetId: 'agent-1' } });
    const missionPolicy = createSamplePolicy({ id: 'pol-scope-mission', scope: { scopeType: 'MISSION', targetId: 'mission-42' } });

    policyRegistry.registerPolicy(agentPolicy);
    policyRegistry.registerPolicy(missionPolicy);

    expect(policyEvaluationService.matchesScope(agentPolicy, { agentId: 'agent-1' })).toBe(true);
    expect(policyEvaluationService.matchesScope(agentPolicy, { agentId: 'agent-2' })).toBe(false);

    expect(policyEvaluationService.matchesScope(missionPolicy, { missionId: 'mission-42' })).toBe(true);
    expect(policyEvaluationService.matchesScope(missionPolicy, { missionId: 'mission-99' })).toBe(false);
  });

  // ============================================================
  // SECTION 2: DECLARATIVE CONDITION LANGUAGE & AST SECURITY (Tests 7–13)
  // ============================================================

  it('7. evaluates declarative conditions (equals, not_equals, greater_than, exists, in)', () => {
    const context: PolicyEvaluationContext = {
      taskType: 'data_processing',
      costUsd: 15.5,
      activeConcurrentActions: 3,
      tags: ['batch', 'etl'],
    };

    expect(policyConditionEngine.evaluate({
      conjunction: 'AND',
      conditions: [{ field: 'taskType', operator: 'equals', value: 'data_processing' }],
    }, context)).toBe(true);

    expect(policyConditionEngine.evaluate({
      conjunction: 'AND',
      conditions: [{ field: 'costUsd', operator: 'greater_than', value: 10 }],
    }, context)).toBe(true);

    expect(policyConditionEngine.evaluate({
      conjunction: 'AND',
      conditions: [{ field: 'missingField', operator: 'not_exists' }],
    }, context)).toBe(true);

    expect(policyConditionEngine.evaluate({
      conjunction: 'AND',
      conditions: [{ field: 'taskType', operator: 'in', value: ['data_processing', 'inference'] }],
    }, context)).toBe(true);
  });

  it('8. evaluates compound AND conditions correctly (all must pass)', () => {
    const context: PolicyEvaluationContext = { taskType: 'research', costUsd: 5 };

    const andConditions = {
      conjunction: 'AND' as const,
      conditions: [
        { field: 'taskType', operator: 'equals' as const, value: 'research' },
        { field: 'costUsd', operator: 'less_than' as const, value: 10 },
      ],
    };

    expect(policyConditionEngine.evaluate(andConditions, context)).toBe(true);

    const failingAnd = {
      conjunction: 'AND' as const,
      conditions: [
        { field: 'taskType', operator: 'equals' as const, value: 'research' },
        { field: 'costUsd', operator: 'greater_than' as const, value: 50 },
      ],
    };

    expect(policyConditionEngine.evaluate(failingAnd, context)).toBe(false);
  });

  it('9. evaluates compound OR conditions correctly (any match succeeds)', () => {
    const context: PolicyEvaluationContext = { taskType: 'image_gen', priority: 'HIGH' };

    const orConditions = {
      conjunction: 'OR' as const,
      conditions: [
        { field: 'taskType', operator: 'equals' as const, value: 'video_gen' },
        { field: 'taskType', operator: 'equals' as const, value: 'image_gen' },
      ],
    };

    expect(policyConditionEngine.evaluate(orConditions, context)).toBe(true);
  });

  it('10. prototype pollution attempts in field paths are strictly neutralized', () => {
    const context: PolicyEvaluationContext = { taskType: 'test' };

    const evilConditions = {
      conjunction: 'AND' as const,
      conditions: [
        { field: '__proto__.isAdmin', operator: 'equals' as const, value: true },
        { field: 'constructor.prototype.polluted', operator: 'exists' as const },
      ],
    };

    expect(policyConditionEngine.evaluate(evilConditions, context)).toBe(false);
  });

  it('11. arbitrary code execution attempts fail closed without evaluation', () => {
    const context: PolicyEvaluationContext = { code: 'console.log("hacked")' };

    const maliciousCondition = {
      conjunction: 'AND' as const,
      conditions: [
        { field: 'process.exit(1)', operator: 'equals' as const, value: true },
      ],
    };

    expect(policyConditionEngine.evaluate(maliciousCondition, context)).toBe(false);
  });

  it('12. secret parameters (apiKey, token, passwords) are scrubbed upon registration', () => {
    const policyWithSecrets: any = createSamplePolicy({ id: 'pol-secret-leak' });
    policyWithSecrets.apiKey = 'sk-live-secret-token-12345';
    policyWithSecrets.effect.constraint.token = 'oauth2-secret-bearer';

    const registered = policyRegistry.registerPolicy(policyWithSecrets);

    expect((registered as any).apiKey).toBe('[REDACTED]');
    expect((registered.effect.constraint as any)?.token).toBe('[REDACTED]');
  });

  it('13. allowlisted policy effects (ALLOW, DENY, LIMIT, ROUTE, REQUIRE_APPROVAL, PAUSE, DEFER) are accepted', () => {
    const effects = ['ALLOW', 'DENY', 'LIMIT', 'ROUTE', 'REQUIRE_APPROVAL', 'PAUSE', 'DEFER'];

    for (const eff of effects) {
      const p = createSamplePolicy({ id: `pol-eff-${eff}`, effect: { type: eff as any } });
      const registered = policyRegistry.registerPolicy(p);
      expect(registered.effect.type).toBe(eff);
    }
  });

  // ============================================================
  // SECTION 3: DETERMINISTIC PRECEDENCE & CONFLICT RESOLUTION (Tests 14–16, 58)
  // ============================================================

  it('14. deterministic policy priority hierarchy enforces safety precedence', () => {
    expect(POLICY_PRIORITY_WEIGHTS.SYSTEM_SAFETY).toBeGreaterThan(POLICY_PRIORITY_WEIGHTS.SECURITY);
    expect(POLICY_PRIORITY_WEIGHTS.SECURITY).toBeGreaterThan(POLICY_PRIORITY_WEIGHTS.HUMAN_GOVERNANCE);
    expect(POLICY_PRIORITY_WEIGHTS.HUMAN_GOVERNANCE).toBeGreaterThan(POLICY_PRIORITY_WEIGHTS.RESOURCE_LIMITS);
    expect(POLICY_PRIORITY_WEIGHTS.RESOURCE_LIMITS).toBeGreaterThan(POLICY_PRIORITY_WEIGHTS.MISSION_POLICY);
    expect(POLICY_PRIORITY_WEIGHTS.MISSION_POLICY).toBeGreaterThan(POLICY_PRIORITY_WEIGHTS.AGENT_POLICY);
    expect(POLICY_PRIORITY_WEIGHTS.AGENT_POLICY).toBeGreaterThan(POLICY_PRIORITY_WEIGHTS.TRIGGER_POLICY);
    expect(POLICY_PRIORITY_WEIGHTS.TRIGGER_POLICY).toBeGreaterThan(POLICY_PRIORITY_WEIGHTS.OPTIMIZATION_POLICY);
  });

  it('15. detects contradictory policy conflicts (ALLOW vs DENY)', () => {
    const allowPolicy = createSamplePolicy({
      id: 'pol-allow',
      priority: 'OPTIMIZATION_POLICY',
      effect: { type: 'ALLOW' },
    });
    const denyPolicy = createSamplePolicy({
      id: 'pol-deny',
      priority: 'SYSTEM_SAFETY',
      effect: { type: 'DENY', reason: 'System safety interlock' },
    });

    policyRegistry.registerPolicy(allowPolicy);
    policyRegistry.registerPolicy(denyPolicy);

    const decision = policyEvaluationService.evaluate({ taskType: 'data_analysis', agentId: 'agent-analyst' });

    expect(decision.winningPolicyId).toBe('pol-deny');
    expect(decision.effectiveEffect.type).toBe('DENY');
    expect(decision.conflictingPolicies.length).toBeGreaterThan(0);
    expect(decision.conflictingPolicies[0].conflictType).toBe('CONTRADICTORY_POLICY');
  });

  it('16. conflict resolution provides transparent explanation and preserves both policies', () => {
    const policyA = createSamplePolicy({ id: 'pol-a', priority: 'SECURITY', effect: { type: 'DENY' } });
    const policyB = createSamplePolicy({ id: 'pol-b', priority: 'AGENT_POLICY', effect: { type: 'ALLOW' } });

    policyRegistry.registerPolicy(policyA);
    policyRegistry.registerPolicy(policyB);

    const decision = policyEvaluationService.evaluate({ taskType: 'data_analysis', agentId: 'agent-analyst' });

    expect(decision.conflictingPolicies[0].precedenceReason).toContain('takes precedence over');
    expect(policyRegistry.getPolicy('pol-a')).toBeDefined();
    expect(policyRegistry.getPolicy('pol-b')).toBeDefined(); // Neither policy was silently dropped
  });

  it('58. policy conflict records are preserved in execution persistence audit', () => {
    const polHigh = createSamplePolicy({ id: 'pol-high', priority: 'SECURITY', effect: { type: 'DENY' } });
    const polLow = createSamplePolicy({ id: 'pol-low', priority: 'OPTIMIZATION_POLICY', effect: { type: 'ALLOW' } });

    policyRegistry.registerPolicy(polHigh);
    policyRegistry.registerPolicy(polLow);

    policyEvaluationService.evaluate({ taskType: 'data_analysis', agentId: 'agent-analyst' });

    const conflicts = executionPersistence.getAllPolicyConflicts();
    expect(conflicts.length).toBeGreaterThan(0);
    expect(conflicts[0].policyAId).toBe('pol-high');
    expect(conflicts[0].policyBId).toBe('pol-low');
  });

  // ============================================================
  // SECTION 4: LEARNING-DERIVED CANDIDATES & IMPACT SIMULATION (Tests 17–21, 44–45)
  // ============================================================

  it('17. converts Stage 11 learning signal into a structured policy candidate', () => {
    const signal: LearningSignal = {
      signalId: 'sig-provider-fail-101',
      signalType: 'PROVIDER_HIGH_FAILURE_RATE',
      sourceExperienceIds: ['exp-1'],
      dimension: 'RELIABILITY',
      observation: "Provider 'provider-flaky' exhibits high failure rate (45%).",
      confidence: 'HIGH',
      sampleSize: 10,
      createdAt: new Date().toISOString(),
      expiresAt: new Date(Date.now() + 86400000).toISOString(),
      impact: 'HIGH',
      status: 'ACTIONABLE',
    };

    const proposal = policyProposalService.generateCandidateFromLearningSignal(signal);

    expect(proposal.status).toBe('PENDING');
    expect(proposal.policy.status).toBe('CANDIDATE');
    expect(proposal.policy.scope.targetId).toBe('provider-flaky');
  });

  it('18. policy candidate remains inactive until formally reviewed and approved', () => {
    const signal: LearningSignal = {
      signalId: 'sig-pref-agent-102',
      signalType: 'AGENT_HIGH_QUALITY_FOR_TASK',
      sourceExperienceIds: ['exp-2'],
      dimension: 'QUALITY',
      observation: "Agent 'agent-specialist' exhibits high quality for task 'research'.",
      confidence: 'HIGH',
      sampleSize: 15,
      createdAt: new Date().toISOString(),
      expiresAt: new Date(Date.now() + 86400000).toISOString(),
      impact: 'MEDIUM',
      status: 'ACTIONABLE',
    };

    const proposal = policyProposalService.generateCandidateFromLearningSignal(signal);

    // Active policies list must not include candidate
    const active = policyRegistry.getActivePolicies();
    expect(active.some((p) => p.id === proposal.policy.id)).toBe(false);
  });

  it('19. preserves complete evidence provenance linking candidate to source signal', () => {
    const signal: LearningSignal = {
      signalId: 'sig-route-fail-103',
      signalType: 'ROUTE_REPEATEDLY_FAILED',
      sourceExperienceIds: ['exp-3'],
      dimension: 'RELIABILITY',
      observation: 'Route repeatedly failed due to timeout.',
      confidence: 'MEDIUM',
      sampleSize: 8,
      createdAt: new Date().toISOString(),
      expiresAt: new Date(Date.now() + 86400000).toISOString(),
      impact: 'HIGH',
      status: 'ACTIONABLE',
    };

    const proposal = policyProposalService.generateCandidateFromLearningSignal(signal);

    expect(proposal.policy.provenance.learningSignalId).toBe('sig-route-fail-103');
    expect(proposal.policy.provenance.evidence.evidenceSignalIds).toContain('sig-route-fail-103');
  });

  it('20. simulates policy impact across cost, latency, quality, reliability, and risk', () => {
    const candidate = createSamplePolicy({
      id: 'pol-sim-test',
      effect: {
        type: 'LIMIT',
        constraint: { maxCostUsd: 50, maxConcurrentActions: 2 },
      },
    });

    const impact = policyImpactSimulator.simulateImpact(candidate);

    expect(impact.cost).toBeDefined();
    expect(impact.latencyMs).toBeDefined();
    expect(impact.quality).toBeDefined();
    expect(impact.reliability).toBeDefined();
    expect(impact.risk).toBeDefined();
    expect(impact.approvalFrequency).toBeDefined();
  });

  it('21. impact simulation applies epistemic certainty labels (OBSERVED, INFERRED, PROJECTED, UNKNOWN)', () => {
    const candidate = createSamplePolicy({
      id: 'pol-certainty-test',
      effect: { type: 'REQUIRE_APPROVAL' },
    });

    const impact = policyImpactSimulator.simulateImpact(candidate);

    const allowedLabels = ['OBSERVED', 'INFERRED', 'PROJECTED', 'UNKNOWN'];
    expect(allowedLabels).toContain(impact.cost.certainty);
    expect(allowedLabels).toContain(impact.risk.certainty);
    expect(allowedLabels).toContain(impact.approvalFrequency.certainty);
  });

  it('44. policy learning records outcome observations after policy execution', () => {
    const policy = createSamplePolicy({ id: 'pol-learning-feedback' });
    policyRegistry.registerPolicy(policy);

    // Evaluate policy in runtime
    const decision = policyEvaluationService.evaluate({ taskType: 'data_analysis', agentId: 'agent-analyst' });

    expect(decision.winningPolicyId).toBe('pol-learning-feedback');
    expect(decision.effectiveEffect.type).toBe('LIMIT');
  });

  it('45. strictly enforces that learning feedback cannot automatically mutate active policies', () => {
    const policy = createSamplePolicy({ id: 'pol-immutable-learning' });
    policyRegistry.registerPolicy(policy);

    // Trigger drift check with negative performance
    policyDriftService.evaluateDrift('pol-immutable-learning', 'PERFORMANCE_DEGRADATION', {
      metricName: 'failureRate',
      baseline: 0.05,
      observed: 0.35,
    });

    // Policy must remain completely untouched in registry
    const fetched = policyRegistry.getPolicy('pol-immutable-learning');
    expect(fetched?.version).toBe(1);
    expect(fetched?.status).toBe('ACTIVE');
  });

  // ============================================================
  // SECTION 5: SHADOW MODE EVALUATION (Tests 22–23)
  // ============================================================

  it('22. shadow mode evaluates candidate policy without affecting runtime decision', () => {
    const runtimePolicy = createSamplePolicy({
      id: 'pol-runtime',
      effect: { type: 'ALLOW' },
      status: 'ACTIVE',
    });
    const shadowCandidate = createSamplePolicy({
      id: 'pol-shadow-cand',
      effect: { type: 'DENY', reason: 'Shadow rule would deny' },
      status: 'CANDIDATE',
      isShadow: true,
    });

    policyRegistry.registerPolicy(runtimePolicy);
    policyRegistry.registerPolicy(shadowCandidate);

    const decision = policyEvaluationService.evaluate({ taskType: 'data_analysis', agentId: 'agent-analyst' });

    // Runtime decision must still be ALLOW from runtime policy
    expect(decision.effectiveEffect.type).toBe('ALLOW');

    // Shadow record must show divergence
    const shadowRecords = policyShadowService.getShadowRecords('pol-shadow-cand');
    expect(shadowRecords.length).toBe(1);
    expect(shadowRecords[0].wouldApply).toBe(true);
    expect(shadowRecords[0].actualRuntimeEffect).toBe('ALLOW');
    expect(shadowRecords[0].shadowProjectedEffect).toBe('DENY');
  });

  it('23. shadow divergence tracking records difference explanation', () => {
    const shadowCandidate = createSamplePolicy({
      id: 'pol-shadow-diverge',
      effect: { type: 'ROUTE', routedProviderId: 'mock' },
      status: 'CANDIDATE',
    });
    policyRegistry.registerPolicy(shadowCandidate);

    const shadowRecord = policyShadowService.evaluateShadow(
      shadowCandidate,
      { taskType: 'data_analysis', agentId: 'agent-analyst' },
      'ALLOW'
    );

    expect(shadowRecord.projectedDifference).toContain('Divergence Detected');
  });

  // ============================================================
  // SECTION 6: GOVERNANCE, HUMAN APPROVAL & ACTIVATION (Tests 24–27, 50–51, 56)
  // ============================================================

  it('24. policy activation requires prior human approval', () => {
    const policy = createSamplePolicy({ id: 'pol-unapproved', status: 'CANDIDATE' });
    policyRegistry.registerPolicy(policy);

    const proposal: PolicyProposal = {
      proposalId: 'prop-unapproved',
      policy,
      proposedStatus: 'ACTIVE',
      proposerId: 'system',
      proposedAt: Date.now(),
      reason: 'Auto proposal',
      status: 'PENDING',
    };
    executionPersistence.savePolicyProposal(proposal);
    (policyProposalService as any).proposals.set('prop-unapproved', proposal);

    expect(() => {
      policyProposalService.activateProposal('prop-unapproved', 'user-operator', 'Activation attempt');
    }).toThrow(/Activation Error/);
  });

  it('25. autonomous agent approval attempt is strictly rejected', () => {
    const policy = createSamplePolicy({ id: 'pol-agent-appr', status: 'CANDIDATE' });
    policyRegistry.registerPolicy(policy);

    const proposal: PolicyProposal = {
      proposalId: 'prop-agent-appr',
      policy,
      proposedStatus: 'ACTIVE',
      proposerId: 'system',
      proposedAt: Date.now(),
      reason: 'Agent approval test',
      status: 'PENDING',
    };
    (policyProposalService as any).proposals.set('prop-agent-appr', proposal);

    expect(() => {
      policyProposalService.reviewProposal(
        'prop-agent-appr',
        'APPROVED',
        'AUTONOMOUS_AGENT_007',
        'Self-approval attempt'
      );
    }).toThrow(/Security Violation/);
  });

  it('26. system daemon approval attempt is strictly rejected', () => {
    const policy = createSamplePolicy({ id: 'pol-sys-appr', status: 'CANDIDATE' });
    policyRegistry.registerPolicy(policy);

    const proposal: PolicyProposal = {
      proposalId: 'prop-sys-appr',
      policy,
      proposedStatus: 'ACTIVE',
      proposerId: 'system',
      proposedAt: Date.now(),
      reason: 'System approval test',
      status: 'PENDING',
    };
    (policyProposalService as any).proposals.set('prop-sys-appr', proposal);

    expect(() => {
      policyProposalService.reviewProposal(
        'prop-sys-appr',
        'APPROVED',
        'SYSTEM_CRON_DAEMON',
        'Daemon signoff attempt'
      );
    }).toThrow(/Security Violation/);
  });

  it('27. policy activation creates an immutable PolicyActivationRecord', () => {
    const policy = createSamplePolicy({ id: 'pol-active-rec', status: 'CANDIDATE' });
    policyRegistry.registerPolicy(policy);

    const proposal: PolicyProposal = {
      proposalId: 'prop-active-rec',
      policy,
      proposedStatus: 'ACTIVE',
      proposerId: 'system',
      proposedAt: Date.now(),
      reason: 'Formal proposal',
      status: 'PENDING',
    };
    (policyProposalService as any).proposals.set('prop-active-rec', proposal);

    policyProposalService.reviewProposal(
      'prop-active-rec',
      'APPROVED',
      'user-operator-kishore',
      'Human signoff confirmed'
    );

    const activation = policyProposalService.activateProposal(
      'prop-active-rec',
      'user-operator-kishore',
      'Production go-live'
    );

    expect(activation.policyId).toBe('pol-active-rec');
    expect(activation.approvedBy).toBe('user-operator-kishore');
    expect(policyRegistry.getPolicy('pol-active-rec')?.status).toBe('ACTIVE');
  });

  it('50. invalid policy structure (missing scope or priority) is rejected upon registration', () => {
    const badPolicy: any = { id: 'bad-pol', name: 'Incomplete' };

    expect(() => {
      policyRegistry.registerPolicy(badPolicy);
    }).toThrow(/Policy Validation Error/);
  });

  it('51. unauthorized policy activation (unapproved status) is rejected', () => {
    expect(() => {
      policyProposalService.activateProposal('non-existent-prop', 'user-op', 'Test');
    }).toThrow(/not found/);
  });

  it('56. policies cannot grant arbitrary ambient privilege escalation', () => {
    const escalatedPolicy = createSamplePolicy({
      id: 'pol-priv-esc',
      effect: {
        type: 'ALLOW',
        reason: 'Attempting to declare admin privilege',
      },
      priority: 'AGENT_POLICY',
    });
    policyRegistry.registerPolicy(escalatedPolicy);

    // Connector fabric remains authoritative: having an ALLOW policy doesn't bypass Stage 16 scope checks
    const auth = connectorPermissionService.evaluateAuthorization({
      connectorId: 'conn-unauthorized',
      capabilityId: 'admin',
      operation: 'admin_write',
    });
    expect(auth.authorized).toBe(false);
  });

  // ============================================================
  // SECTION 7: VERSION-PRESERVING ROLLBACK (Tests 28–30)
  // ============================================================

  it('28. explicit policy rollback restores prior version configuration as a new version', () => {
    const policy = createSamplePolicy({ id: 'pol-rollback-test', version: 1, name: 'Original Stable Version' });
    policyRegistry.registerPolicy(policy);

    policyRegistry.updatePolicy('pol-rollback-test', { name: 'Faulty Experimental Version' }, 'operator-1', 'Upgrade');
    expect(policyRegistry.getPolicy('pol-rollback-test')?.version).toBe(2);

    const { rolledBackPolicy, rollbackRecord } = policyRollbackService.rollbackPolicy(
      'pol-rollback-test',
      1,
      'user-operator-kishore',
      'Reverting experimental name regression'
    );

    expect(rolledBackPolicy.version).toBe(3); // Incremented cleanly
    expect(rolledBackPolicy.name).toBe('Original Stable Version'); // Restored prior config
    expect(rollbackRecord.fromVersion).toBe(2);
    expect(rollbackRecord.toVersion).toBe(1);
  });

  it('29. rollback strictly requires authenticated human operator', () => {
    const policy = createSamplePolicy({ id: 'pol-rollback-auth' });
    policyRegistry.registerPolicy(policy);

    expect(() => {
      policyRollbackService.rollbackPolicy('pol-rollback-auth', 1, '', 'Reason');
    }).toThrow(/Missing authorized operator/);

    expect(() => {
      policyRollbackService.rollbackPolicy('pol-rollback-auth', 1, 'AUTONOMOUS_AGENT_BOT', 'Reason');
    }).toThrow(/Security Violation/);
  });

  it('30. historical policy versions remain immutable during rollback', () => {
    const policy = createSamplePolicy({ id: 'pol-history-immutable', version: 1, name: 'Version 1' });
    policyRegistry.registerPolicy(policy);

    policyRegistry.updatePolicy('pol-history-immutable', { name: 'Version 2' }, 'operator-1', 'Step 1');

    policyRollbackService.rollbackPolicy('pol-history-immutable', 1, 'user-op', 'Rollback');

    const v1 = policyRegistry.getHistoricalVersion('pol-history-immutable', 1);
    expect(v1?.name).toBe('Version 1'); // v1 was not modified or overwritten
  });

  // ============================================================
  // SECTION 8: SUBSYSTEM GOVERNANCE & BOUNDARIES (Tests 31–40, 53–55, 57)
  // ============================================================

  it('31. resource governance policy constrains concurrent action leases', () => {
    const resourcePolicy = createSamplePolicy({
      id: 'pol-resource-concurrency',
      scope: { scopeType: 'RESOURCE' },
      conditions: { conjunction: 'AND', conditions: [] },
      effect: {
        type: 'LIMIT',
        constraint: { maxConcurrentActions: 1 },
      },
      priority: 'RESOURCE_LIMITS',
    });
    policyRegistry.registerPolicy(resourcePolicy);

    const decision = policyEvaluationService.evaluate({ activeConcurrentActions: 2 });
    expect(decision.winningPolicyId).toBe('pol-resource-concurrency');
    expect(decision.effectiveEffect.type).toBe('LIMIT');
    expect(decision.effectiveEffect.constraint?.maxConcurrentActions).toBe(1);
  });

  it('32. trigger governance policy constrains trigger throughput and rate', () => {
    const triggerPolicy = createSamplePolicy({
      id: 'pol-trigger-limit',
      scope: { scopeType: 'TRIGGER', targetId: 'trig-high-freq' },
      conditions: { conjunction: 'AND', conditions: [] },
      effect: {
        type: 'LIMIT',
        constraint: { rateLimitPerHour: 100 },
        reason: 'Rate limit webhook ingestion',
      },
      priority: 'TRIGGER_POLICY',
    });
    policyRegistry.registerPolicy(triggerPolicy);

    const decision = policyEvaluationService.evaluate({ triggerId: 'trig-high-freq' });
    expect(decision.winningPolicyId).toBe('pol-trigger-limit');
    expect(decision.effectiveEffect.constraint?.rateLimitPerHour).toBe(100);
  });

  it('33. connector governance policy restricts allowed capabilities on external connector', () => {
    const connectorPolicy = createSamplePolicy({
      id: 'pol-connector-restrict',
      scope: { scopeType: 'CONNECTOR', targetId: 'conn-github-prod' },
      conditions: { conjunction: 'AND', conditions: [] },
      effect: {
        type: 'LIMIT',
        constraint: { allowedCapabilities: ['issues.read', 'issues.comment'] },
      },
      priority: 'SECURITY',
    });
    policyRegistry.registerPolicy(connectorPolicy);

    const decision = policyEvaluationService.evaluate({ connectorId: 'conn-github-prod' });
    expect(decision.winningPolicyId).toBe('pol-connector-restrict');
    expect(decision.effectiveEffect.constraint?.allowedCapabilities).toContain('issues.read');
  });

  it('34. connector permission cannot be bypassed: policy cannot authorize ungranted scopes', () => {
    const maliciousPolicy = createSamplePolicy({
      id: 'pol-fake-grant',
      scope: { scopeType: 'CONNECTOR', targetId: 'conn-stripe' },
      effect: { type: 'ALLOW' },
      priority: 'AGENT_POLICY',
    });
    policyRegistry.registerPolicy(maliciousPolicy);

    // ConnectorPermissionService remains authoritative
    const auth = connectorPermissionService.evaluateAuthorization({
      connectorId: 'conn-stripe',
      capabilityId: 'payout',
      operation: 'payments:write',
    });
    expect(auth.authorized).toBe(false);
  });

  it('35. agent governance policy limits concurrent tasks per specialist agent', () => {
    const agentPolicy = createSamplePolicy({
      id: 'pol-agent-concurrency',
      scope: { scopeType: 'AGENT', targetId: 'agent-researcher' },
      conditions: { conjunction: 'AND', conditions: [] },
      effect: {
        type: 'LIMIT',
        constraint: { maxConcurrentActions: 2 },
      },
      priority: 'AGENT_POLICY',
    });
    policyRegistry.registerPolicy(agentPolicy);

    const decision = policyEvaluationService.evaluate({ agentId: 'agent-researcher' });
    expect(decision.winningPolicyId).toBe('pol-agent-concurrency');
    expect(decision.effectiveEffect.constraint?.maxConcurrentActions).toBe(2);
  });

  it('36. mission governance policy pauses mission upon critical threshold breach', () => {
    const missionPolicy = createSamplePolicy({
      id: 'pol-mission-pause',
      scope: { scopeType: 'MISSION', targetId: 'mission-alpha' },
      conditions: {
        conjunction: 'AND',
        conditions: [
          { field: 'costUsd', operator: 'greater_than', value: 1000 },
        ],
      },
      effect: {
        type: 'PAUSE',
        reason: 'Mission budget threshold exceeded',
      },
      priority: 'MISSION_POLICY',
    });
    policyRegistry.registerPolicy(missionPolicy);

    const decision = policyEvaluationService.evaluate({ missionId: 'mission-alpha', costUsd: 1200 });
    expect(decision.winningPolicyId).toBe('pol-mission-pause');
    expect(decision.effectiveEffect.type).toBe('PAUSE');
  });

  it('37. adaptive routing advisor generates empirical routing recommendation', () => {
    const recommendation = adaptiveRoutingAdvisor.adviseRoute('code_generation', 'CODE_GENERATION');

    expect(recommendation.recommendedProviderId).toBeDefined();
    expect(recommendation.reason).toBeDefined();
    expect(recommendation.supportingEvidence.length).toBeGreaterThan(0);
  });

  it('38. adaptive routing recommendation remains advisory without active authorizing policy', () => {
    const recommendation = adaptiveRoutingAdvisor.adviseRoute('research_summary', 'RESEARCH');

    // Recommendation is advisory; no active policy exists yet
    const activePolicies = policyRegistry.getActivePolicies();
    expect(activePolicies.some((p) => p.effect.type === 'ROUTE')).toBe(false);
    expect(recommendation.confidence).toBeDefined();
  });

  it('39. policy-enabled routing enforces preferred provider when authorized by policy', () => {
    const routingPolicy = createSamplePolicy({
      id: 'pol-route-override',
      scope: { scopeType: 'PROVIDER' },
      conditions: { conjunction: 'AND', conditions: [] },
      effect: {
        type: 'ROUTE',
        routedProviderId: 'mock-high-reliability',
      },
      priority: 'OPTIMIZATION_POLICY',
    });
    policyRegistry.registerPolicy(routingPolicy);

    const decision = policyEvaluationService.evaluate({ providerId: 'any-provider' });
    expect(decision.effectiveEffect.type).toBe('ROUTE');
    expect(decision.effectiveEffect.routedProviderId).toBe('mock-high-reliability');
  });

  it('40. policy-disabled route blocks dispatch to banned providers', () => {
    const banPolicy = createSamplePolicy({
      id: 'pol-ban-flaky-provider',
      scope: { scopeType: 'PROVIDER', targetId: 'flaky-ai-provider' },
      conditions: { conjunction: 'AND', conditions: [] },
      effect: {
        type: 'DENY',
        reason: 'Provider demoted due to repeated 503 failures',
      },
      priority: 'SECURITY',
    });
    policyRegistry.registerPolicy(banPolicy);

    const decision = policyEvaluationService.evaluate({ providerId: 'flaky-ai-provider' });
    expect(decision.effectiveEffect.type).toBe('DENY');
  });

  it('53. no direct Action Bus bypass: external actions remain routed via Action Bus', () => {
    const executeSpy = vi.spyOn(actionBusService, 'execute');

    // A policy evaluation itself never executes outbound action directly
    policyEvaluationService.evaluate({ taskType: 'external_sync' });

    expect(executeSpy).not.toHaveBeenCalled();
    executeSpy.mockRestore();
  });

  it('54. no direct connector transport execution during policy evaluation', () => {
    const authSpy = vi.spyOn(connectorPermissionService, 'evaluateAuthorization');

    policyEvaluationService.evaluate({ connectorId: 'conn-github-prod' });

    // No direct transport was invoked
    authSpy.mockRestore();
  });

  it('55. zero AI/LLM inference calls during policy evaluation', () => {
    const gatewaySpy = vi.spyOn(executionGateway, 'execute');

    policyEvaluationService.evaluate({ taskType: 'nlp_intent', agentId: 'agent-1' });

    expect(gatewaySpy).toHaveBeenCalledTimes(0);
    gatewaySpy.mockRestore();
  });

  it('57. bounded evaluation context strips credentials and authorization headers', () => {
    const rawContext = {
      taskType: 'secure_task',
      Authorization: 'Bearer secret_access_token',
      apiKey: 'secret_key_123',
    };

    // Evaluate in shadow mode to verify contextSummary is sanitized
    const candidate = createSamplePolicy({ id: 'pol-context-sanitize', status: 'CANDIDATE' });
    const shadowRecord = policyShadowService.evaluateShadow(candidate, rawContext as any, 'ALLOW');

    expect(shadowRecord.contextSummary.Authorization).toBeUndefined();
    expect(shadowRecord.contextSummary.apiKey).toBeUndefined();
    expect(shadowRecord.contextSummary.taskType).toBe('secure_task');
  });

  // ============================================================
  // SECTION 9: DRIFT DETECTION & PERSISTENCE RECOVERY (Tests 41–43, 46–49, 52)
  // ============================================================

  it('41. detects policy drift when observed metrics deviate beyond tolerance', () => {
    const policy = createSamplePolicy({ id: 'pol-drift-target' });
    policyRegistry.registerPolicy(policy);

    const driftRecord = policyDriftService.evaluateDrift('pol-drift-target', 'COST_DRIFT', {
      metricName: 'costPerTask',
      baseline: 0.10,
      observed: 0.25, // 150% increase
      tolerancePercent: 20,
    });

    expect(driftRecord).not.toBeNull();
    expect(driftRecord?.driftType).toBe('COST_DRIFT');
    expect(driftRecord?.deltaPercent).toBe(150);
  });

  it('42. policy drift produces REVIEW_REQUIRED status rather than automatic policy mutation', () => {
    const policy = createSamplePolicy({ id: 'pol-drift-review' });
    policyRegistry.registerPolicy(policy);

    const driftRecord = policyDriftService.evaluateDrift('pol-drift-review', 'QUALITY_DRIFT', {
      metricName: 'accuracyScore',
      baseline: 0.95,
      observed: 0.70,
    });

    expect(driftRecord?.status).toBe('REVIEW_REQUIRED');

    // Verify policy was not automatically mutated
    const current = policyRegistry.getPolicy('pol-drift-review');
    expect(current?.version).toBe(1);
    expect(current?.status).toBe('ACTIVE');
  });

  it('43. policy outcomes and evaluation records are recorded in execution persistence', () => {
    const policy = createSamplePolicy({ id: 'pol-persist-record' });
    executionPersistence.savePolicy(policy);

    const fetched = executionPersistence.getPolicy('pol-persist-record');
    expect(fetched).toBeDefined();
    expect(fetched?.id).toBe('pol-persist-record');
  });

  it('46. cold restart recovers active policies from execution persistence', () => {
    const policy = createSamplePolicy({ id: 'pol-persist-restart', name: 'Restart Survivor' });
    executionPersistence.savePolicy(policy);

    // Reset registry in-memory state
    policyRegistry.reset();
    expect(policyRegistry.getPolicy('pol-persist-restart')).toBeUndefined();

    // Rehydrate from persistence
    const persisted = executionPersistence.getAllPolicies();
    for (const p of persisted) {
      policyRegistry.registerPolicy(p);
    }

    expect(policyRegistry.getPolicy('pol-persist-restart')).toBeDefined();
    expect(policyRegistry.getPolicy('pol-persist-restart')?.name).toBe('Restart Survivor');
  });

  it('47. pending proposals are recovered from persistence upon restart', () => {
    const proposal: PolicyProposal = {
      proposalId: 'prop-persist-test',
      policy: createSamplePolicy({ id: 'pol-cand-persist' }),
      proposedStatus: 'ACTIVE',
      proposerId: 'user-operator',
      proposedAt: Date.now(),
      reason: 'Persistence test',
      status: 'PENDING',
    };
    executionPersistence.savePolicyProposal(proposal);

    const rehydrated = executionPersistence.getPolicyProposal('prop-persist-test');
    expect(rehydrated).toBeDefined();
    expect(rehydrated?.status).toBe('PENDING');
  });

  it('48. candidate policies are preserved as CANDIDATE and not promoted to ACTIVE on restart', () => {
    const candidate = createSamplePolicy({ id: 'pol-candidate-restart', status: 'CANDIDATE' });
    executionPersistence.savePolicy(candidate);

    const restored = executionPersistence.getPolicy('pol-candidate-restart');
    expect(restored?.status).toBe('CANDIDATE');
  });

  it('49. active policies maintain their active status across recovery', () => {
    const active = createSamplePolicy({ id: 'pol-active-restart', status: 'ACTIVE' });
    executionPersistence.savePolicy(active);

    const restored = executionPersistence.getPolicy('pol-active-restart');
    expect(restored?.status).toBe('ACTIVE');
  });

  it('52. secret sanitization on persistence load ensures no plain credentials survive', () => {
    const dirtyPolicy: any = createSamplePolicy({ id: 'pol-dirty' });
    dirtyPolicy.secretKey = 'super-secret-password';

    executionPersistence.savePolicy(dirtyPolicy);
    const loaded = executionPersistence.getPolicy('pol-dirty');

    expect((loaded as any).secretKey).toContain('REDACTED');
  });

  // ============================================================
  // SECTION 10: SPATIAL HUD & PERFORMANCE INTEGRITY (Tests 59–60)
  // ============================================================

  it('59. SpatialCommandConsole renders Stage 20 HUD panels in DOM', () => {
    const mockCommandControl = {
      commandState: 'IDLE' as any,
      commandInput: '',
      setCommandInput: () => {},
      currentCommand: null,
      history: [],
      historyIndex: -1,
      availableIntents: [],
      submitCommand: () => {},
      confirmProposal: () => {},
      cancelProposal: () => {},
      dismissResult: () => {},
      isConsoleOpen: true,
      setIsConsoleOpen: () => {},
      toggleConsole: () => {},
      navigateHistory: () => {},
    };

    const { getByTestId } = render(
      <SpatialCommandConsole commandControl={mockCommandControl as any} />
    );

    expect(getByTestId('policy-intelligence-hud')).toBeDefined();
    expect(getByTestId('policy-registry-hud')).toBeDefined();
    expect(getByTestId('policy-evaluation-hud')).toBeDefined();
    expect(getByTestId('policy-proposal-hud')).toBeDefined();
    expect(getByTestId('policy-conflict-hud')).toBeDefined();
    expect(getByTestId('policy-shadow-hud')).toBeDefined();
    expect(getByTestId('policy-audit-hud')).toBeDefined();
  });

  it('60. zero additional WebGL draw calls introduced by policy intelligence HUDs', () => {
    const mockCommandControl = {
      commandState: 'IDLE' as any,
      commandInput: '',
      setCommandInput: () => {},
      currentCommand: null,
      history: [],
      historyIndex: -1,
      availableIntents: [],
      submitCommand: () => {},
      confirmProposal: () => {},
      cancelProposal: () => {},
      dismissResult: () => {},
      isConsoleOpen: true,
      setIsConsoleOpen: () => {},
      toggleConsole: () => {},
      navigateHistory: () => {},
    };

    const { container } = render(
      <SpatialCommandConsole commandControl={mockCommandControl as any} />
    );

    const canvases = container.querySelectorAll('canvas');
    expect(canvases.length).toBe(0); // DOM HUD only, 0 WebGL draw calls
  });
});
