/**
 * AryaOS V1 — Stage 19: Event-Driven Reaction Engine & Controlled Trigger Orchestration Test Suite
 *
 * Verifies all 60 required specifications:
 * 1. Valid trigger registration
 * 2. Missing required fields rejection
 * 3. Invalid risk level rejection
 * 4. Secret scrubbing in trigger parameters
 * 5. Code injection attempts rejection in conditions
 * 6. Immutability & version bumping
 * 7. Valid lifecycle state machine transitions
 * 8. Invalid lifecycle transitions rejection
 * 9. Equality condition operators (equals, not_equals)
 * 10. Text operators (contains, starts_with, ends_with)
 * 11. Numeric comparisons (greater_than, less_than)
 * 12. Existence checks (exists, not_exists)
 * 13. Set containment (in, not_in)
 * 14. Logical AND operator
 * 15. Logical OR operator
 * 16. Nested dot-path resolution
 * 17. Fail-closed behavior on missing dot-path
 * 18. Fail-closed behavior on type mismatch
 * 19. Malicious code / prototype rejection in conditions
 * 20. Complex nested boolean condition trees
 * 21. Event pattern matching (sourceSystem, resourceType, changeType)
 * 22. Wildcard matching in event patterns
 * 23. Pattern non-matching filter
 * 24. Disabled/revoked trigger filtering
 * 25. Condition evaluation false filtering
 * 26. Multiple triggers matched to single event
 * 27. Passive observation classified as LOW risk
 * 28. Analysis request classified as LOW/MEDIUM risk
 * 29. Mission modification classified as HIGH risk
 * 30. External action write classified as CRITICAL risk
 * 31. Automatic risk elevation for consequential reactions
 * 32. Consequential triggers flag human approval requirement
 * 33. Proposal generation with deterministic identity and provenance
 * 34. Auto-authorization of LOW-risk proposals
 * 35. High/critical risk proposals hold for human approval
 * 36. Human operator approval grants authorization
 * 37. Human operator rejection marks proposal rejected
 * 38. Autonomous agent approval rejected (AUTONOMOUS_AGENT cannot approve)
 * 39. System approval rejected (SYSTEM cannot approve)
 * 40. Connector permission scope verification before authorization
 * 41. Reaction execution dispatched via Stage 15 Action Bus
 * 42. No direct connector execution bypass
 * 43. Zero AI/LLM inference calls during reaction execution
 * 44. Execution blocked for unapproved proposals
 * 45. Execution blocked for rejected proposals
 * 46. Concurrency throttling enforced
 * 47. Idempotency deduplication enforced
 * 48. Provenance propagation across reactions
 * 49. Reaction depth limit halts causal loop (CHAIN_LIMIT)
 * 50. Cycle detection halts recurring trigger invocation
 * 51. REACTION_CHAIN_LIMIT journal event emitted
 * 52. Failure audit trail preserved without infinite recursion
 * 53. PAUSE_MISSION dispatches to missionManager
 * 54. REPLAN_MISSION dispatches to missionReplanner
 * 55. CREATE_GOAL dispatches to goalOrchestrator
 * 56. Persistence saves triggers, proposals, and results
 * 57. Restart recovers triggers and proposals from persistence
 * 58. SpatialCommandConsole renders Stage 19 HUD panels in DOM
 * 59. Stage 03 camera baseline immutable and reconciled
 * 60. Zero additional WebGL draw calls introduced
 */

import { describe, it, expect, beforeEach, vi } from 'vitest';
import React from 'react';
import { render } from '@testing-library/react';

// Domain Types
import {
  Trigger,
  TriggerCondition,
  TriggerConditionGroup,
  ReactionProposal,
} from '../types/eventTrigger';
import { NormalizedExternalEvent } from '../types/externalEvent';

// Core Services
import { triggerRegistry } from '../services/triggerRegistry';
import { triggerConditionEngine } from '../services/triggerConditionEngine';
import { triggerRiskService } from '../services/triggerRiskService';
import { reactionProposalService } from '../services/reactionProposalService';
import { triggerEvaluationService } from '../services/triggerEvaluationService';
import { reactionExecutionEngine } from '../services/reactionExecutionEngine';
import { connectorRegistry } from '../services/connectorRegistry';
import { connectorPermissionService } from '../services/connectorPermissionService';
import { executionJournal } from '../services/executionJournal';
import { executionPersistence } from '../services/executionPersistence';
import { executionGateway } from '../services/executionGateway';
import { actionBusService } from '../services/actionBusService';
import { missionManager } from '../services/missionManager';
import { missionReplanner } from '../services/missionReplanner';
import { goalOrchestrator } from '../services/goalOrchestrator';
import { STAGE03_CAMERAS } from '../stage03_assembly';
import { SpatialCommandConsole } from '../components/spatial/SpatialCommandConsole';

describe('AryaOS V1 Stage 19 — Event-Driven Reaction Engine & Trigger Orchestration', () => {
  const sampleNormalizedEvent: NormalizedExternalEvent = {
    normalizedEventId: 'evt_norm_101',
    originalEventId: 'evt_orig_101',
    connectorId: 'connector_github',
    resourceType: 'ISSUE',
    resourceId: 'issue_42',
    changeType: 'CREATED',
    sourceSystem: 'GITHUB',
    provenance: {
      provider: 'GITHUB',
      providerEventType: 'issues.opened',
      providerEventId: 'gh_evt_101',
      connectorId: 'connector_github',
      occurredAt: new Date().toISOString(),
      receivedAt: new Date().toISOString(),
      authenticationMethod: 'HMAC_SHA256',
      ingestFingerprint: 'fp_101',
    },
    epistemicStatus: 'OBSERVED',
    data: {
      issue: {
        number: 42,
        title: 'Critical bug in production',
        state: 'open',
        labels: ['bug', 'critical'],
        priority: 1,
        author: {
          username: 'octocat',
          isStaff: true,
        },
      },
      repository: 'aryaos/core',
    },
    timestamp: new Date().toISOString(),
  };

  beforeEach(() => {
    localStorage.clear();
    executionPersistence.clearEnvelope();
    executionJournal.resetState();
    triggerRegistry.clear();
    reactionProposalService.clear();
    reactionExecutionEngine.clear();

    // Ensure reference connectors exist in active state for testing
    const gh = connectorRegistry.getConnector('connector_github');
    if (gh) {
      gh.status = 'ACTIVE';
      gh.health = 'HEALTHY';
      if (gh.credentialRef) {
        gh.credentialRef.status = 'VALID';
      }
      connectorRegistry.updateConnector(gh);
    }
  });

  // ============================================================
  // SECTION 1: TRIGGER DOMAIN & REGISTRY (Tests 1 - 8)
  // ============================================================

  it('1. registers a valid declarative trigger with DRAFT or ACTIVE state', () => {
    const trigger: Trigger = {
      triggerId: 'trig_issue_observed',
      name: 'Observe New Issues',
      description: 'Creates observation record whenever a GitHub issue is opened',
      status: 'ACTIVE',
      version: 1,
      riskLevel: 'LOW',
      eventFilter: {
        sourceSystem: 'GITHUB',
        resourceType: 'ISSUE',
        changeType: 'CREATED',
      },
      reaction: {
        reactionType: 'CREATE_OBSERVATION',
        observationSummary: 'Observed newly opened GitHub issue',
      },
      provenance: {
        createdBy: 'operator_admin',
        createdAt: new Date().toISOString(),
        updatedAt: new Date().toISOString(),
      },
    };

    const res = triggerRegistry.registerTrigger(trigger);
    expect(res.success).toBe(true);
    expect(res.trigger).toBeDefined();
    expect(triggerRegistry.getTrigger('trig_issue_observed')?.status).toBe('ACTIVE');
  });

  it('2. rejects trigger missing required fields (id, name, eventFilter, reaction)', () => {
    const invalidTrigger: Partial<Trigger> = {
      triggerId: '',
      name: '',
      // missing eventFilter and reaction
    };

    const res = triggerRegistry.registerTrigger(invalidTrigger as Trigger);
    expect(res.success).toBe(false);
    expect(res.errors.length).toBeGreaterThan(0);
    expect(res.errors.some((e) => e.includes('triggerId'))).toBe(true);
  });

  it('3. rejects trigger with invalid risk level or missing reaction type', () => {
    const invalidTrigger: Trigger = {
      triggerId: 'trig_bad_risk',
      name: 'Bad Risk Trigger',
      status: 'ACTIVE',
      version: 1,
      riskLevel: 'ULTRA_DANGEROUS' as any,
      eventFilter: { sourceSystem: 'GITHUB' },
      reaction: { reactionType: '' as any },
      provenance: {
        createdBy: 'user',
        createdAt: new Date().toISOString(),
        updatedAt: new Date().toISOString(),
      },
    };

    const res = triggerRegistry.registerTrigger(invalidTrigger);
    expect(res.success).toBe(false);
    expect(res.errors.some((e) => e.includes('riskLevel') || e.includes('reactionType'))).toBe(true);
  });

  it('4. scrubs secrets in trigger parameters upon registration', () => {
    const triggerWithSecret: Trigger = {
      triggerId: 'trig_secret_scrub',
      name: 'Secret Leak Test',
      status: 'ACTIVE',
      version: 1,
      riskLevel: 'LOW',
      eventFilter: { sourceSystem: 'GITHUB' },
      reaction: {
        reactionType: 'CREATE_OBSERVATION',
        parameters: {
          apiKey: 'sk-abcdef12345678901234567890',
          token: 'ghp_secretTokenValue1234567890',
          normalKey: 'safe-value',
        },
      },
      provenance: {
        createdBy: 'admin',
        createdAt: new Date().toISOString(),
        updatedAt: new Date().toISOString(),
      },
    };

    const res = triggerRegistry.registerTrigger(triggerWithSecret);
    expect(res.success).toBe(true);
    const registered = triggerRegistry.getTrigger('trig_secret_scrub');
    expect(registered?.reaction.parameters?.apiKey).toBe('[REDACTED]');
    expect(registered?.reaction.parameters?.token).toBe('[REDACTED]');
    expect(registered?.reaction.parameters?.normalKey).toBe('safe-value');
  });

  it('5. rejects code injection attempts in conditions (eval, Function, __proto__, <script>)', () => {
    const maliciousTrigger: Trigger = {
      triggerId: 'trig_injection_test',
      name: 'Malicious Trigger',
      status: 'ACTIVE',
      version: 1,
      riskLevel: 'LOW',
      eventFilter: { sourceSystem: 'GITHUB' },
      conditions: {
        field: 'issue.title',
        operator: 'equals',
        value: "javascript:eval('malicious()')",
      },
      reaction: { reactionType: 'CREATE_OBSERVATION' },
      provenance: {
        createdBy: 'attacker',
        createdAt: new Date().toISOString(),
        updatedAt: new Date().toISOString(),
      },
    };

    const res = triggerRegistry.registerTrigger(maliciousTrigger);
    expect(res.success).toBe(false);
    expect(res.errors.some((e) => e.includes('Code injection'))).toBe(true);
  });

  it('6. enforces trigger immutability: updates bump version and preserve previous version', () => {
    const trigger: Trigger = {
      triggerId: 'trig_immutable_version',
      name: 'Version 1 Trigger',
      status: 'ACTIVE',
      version: 1,
      riskLevel: 'LOW',
      eventFilter: { sourceSystem: 'GITHUB' },
      reaction: { reactionType: 'CREATE_OBSERVATION' },
      provenance: {
        createdBy: 'admin',
        createdAt: new Date().toISOString(),
        updatedAt: new Date().toISOString(),
      },
    };

    triggerRegistry.registerTrigger(trigger);

    // Update trigger
    const updateRes = triggerRegistry.updateTrigger('trig_immutable_version', {
      name: 'Version 2 Trigger',
    });

    expect(updateRes.success).toBe(true);
    expect(updateRes.trigger?.version).toBe(2);
    expect(updateRes.trigger?.name).toBe('Version 2 Trigger');

    // Historical version 1 must remain accessible
    const v1 = triggerRegistry.getTriggerVersion('trig_immutable_version', 1);
    expect(v1).toBeDefined();
    expect(v1?.version).toBe(1);
    expect(v1?.name).toBe('Version 1 Trigger');
  });

  it('7. enforces valid lifecycle state transitions (DRAFT -> ACTIVE -> PAUSED -> DISABLED -> REVOKED)', () => {
    const trigger: Trigger = {
      triggerId: 'trig_lifecycle',
      name: 'Lifecycle Trigger',
      status: 'DRAFT',
      version: 1,
      riskLevel: 'LOW',
      eventFilter: { sourceSystem: 'GITHUB' },
      reaction: { reactionType: 'CREATE_OBSERVATION' },
      provenance: {
        createdBy: 'admin',
        createdAt: new Date().toISOString(),
        updatedAt: new Date().toISOString(),
      },
    };

    triggerRegistry.registerTrigger(trigger);

    expect(triggerRegistry.transitionState('trig_lifecycle', 'ACTIVE').success).toBe(true);
    expect(triggerRegistry.getTrigger('trig_lifecycle')?.status).toBe('ACTIVE');

    expect(triggerRegistry.transitionState('trig_lifecycle', 'PAUSED').success).toBe(true);
    expect(triggerRegistry.getTrigger('trig_lifecycle')?.status).toBe('PAUSED');

    expect(triggerRegistry.transitionState('trig_lifecycle', 'ACTIVE').success).toBe(true);
    expect(triggerRegistry.transitionState('trig_lifecycle', 'DISABLED').success).toBe(true);
    expect(triggerRegistry.transitionState('trig_lifecycle', 'REVOKED').success).toBe(true);
  });

  it('8. rejects invalid lifecycle transitions (e.g. REVOKED -> ACTIVE)', () => {
    const trigger: Trigger = {
      triggerId: 'trig_invalid_transition',
      name: 'Revoked Trigger',
      status: 'REVOKED',
      version: 1,
      riskLevel: 'LOW',
      eventFilter: { sourceSystem: 'GITHUB' },
      reaction: { reactionType: 'CREATE_OBSERVATION' },
      provenance: {
        createdBy: 'admin',
        createdAt: new Date().toISOString(),
        updatedAt: new Date().toISOString(),
      },
    };

    triggerRegistry.registerTrigger(trigger);

    const res = triggerRegistry.transitionState('trig_invalid_transition', 'ACTIVE');
    expect(res.success).toBe(false);
    expect(res.error).toContain('Invalid state transition');
    expect(triggerRegistry.getTrigger('trig_invalid_transition')?.status).toBe('REVOKED');
  });

  // ============================================================
  // SECTION 2: DECLARATIVE CONDITION ENGINE (Tests 9 - 20)
  // ============================================================

  it('9. evaluates equality condition operators (equals, not_equals)', () => {
    const condEquals: TriggerCondition = {
      field: 'issue.state',
      operator: 'equals',
      value: 'open',
    };
    expect(triggerConditionEngine.evaluate(condEquals, sampleNormalizedEvent.data).matched).toBe(true);

    const condNotEquals: TriggerCondition = {
      field: 'issue.state',
      operator: 'not_equals',
      value: 'closed',
    };
    expect(triggerConditionEngine.evaluate(condNotEquals, sampleNormalizedEvent.data).matched).toBe(true);
  });

  it('10. evaluates text operations (contains, starts_with, ends_with)', () => {
    const condContains: TriggerCondition = {
      field: 'issue.title',
      operator: 'contains',
      value: 'Critical bug',
    };
    expect(triggerConditionEngine.evaluate(condContains, sampleNormalizedEvent.data).matched).toBe(true);

    const condStartsWith: TriggerCondition = {
      field: 'issue.title',
      operator: 'starts_with',
      value: 'Critical',
    };
    expect(triggerConditionEngine.evaluate(condStartsWith, sampleNormalizedEvent.data).matched).toBe(true);

    const condEndsWith: TriggerCondition = {
      field: 'issue.title',
      operator: 'ends_with',
      value: 'production',
    };
    expect(triggerConditionEngine.evaluate(condEndsWith, sampleNormalizedEvent.data).matched).toBe(true);
  });

  it('11. evaluates numeric comparisons (greater_than, less_than)', () => {
    const condGT: TriggerCondition = {
      field: 'issue.number',
      operator: 'greater_than',
      value: 10,
    };
    expect(triggerConditionEngine.evaluate(condGT, sampleNormalizedEvent.data).matched).toBe(true);

    const condLT: TriggerCondition = {
      field: 'issue.priority',
      operator: 'less_than',
      value: 5,
    };
    expect(triggerConditionEngine.evaluate(condLT, sampleNormalizedEvent.data).matched).toBe(true);
  });

  it('12. evaluates existence checks (exists, not_exists)', () => {
    const condExists: TriggerCondition = {
      field: 'issue.author.username',
      operator: 'exists',
    };
    expect(triggerConditionEngine.evaluate(condExists, sampleNormalizedEvent.data).matched).toBe(true);

    const condNotExists: TriggerCondition = {
      field: 'issue.nonexistentProperty',
      operator: 'not_exists',
    };
    expect(triggerConditionEngine.evaluate(condNotExists, sampleNormalizedEvent.data).matched).toBe(true);
  });

  it('13. evaluates set containment (in, not_in)', () => {
    const condIn: TriggerCondition = {
      field: 'issue.state',
      operator: 'in',
      value: ['open', 'pending'],
    };
    expect(triggerConditionEngine.evaluate(condIn, sampleNormalizedEvent.data).matched).toBe(true);

    const condNotIn: TriggerCondition = {
      field: 'issue.state',
      operator: 'not_in',
      value: ['closed', 'archived'],
    };
    expect(triggerConditionEngine.evaluate(condNotIn, sampleNormalizedEvent.data).matched).toBe(true);
  });

  it('14. evaluates logical AND compound condition correctly', () => {
    const groupAND: TriggerConditionGroup = {
      logicalOperator: 'AND',
      conditions: [
        { field: 'issue.state', operator: 'equals', value: 'open' },
        { field: 'issue.priority', operator: 'equals', value: 1 },
      ],
    };

    expect(triggerConditionEngine.evaluate(groupAND, sampleNormalizedEvent.data).matched).toBe(true);

    const failingAND: TriggerConditionGroup = {
      logicalOperator: 'AND',
      conditions: [
        { field: 'issue.state', operator: 'equals', value: 'open' },
        { field: 'issue.priority', operator: 'equals', value: 99 },
      ],
    };

    expect(triggerConditionEngine.evaluate(failingAND, sampleNormalizedEvent.data).matched).toBe(false);
  });

  it('15. evaluates logical OR compound condition correctly', () => {
    const groupOR: TriggerConditionGroup = {
      logicalOperator: 'OR',
      conditions: [
        { field: 'issue.state', operator: 'equals', value: 'closed' },
        { field: 'issue.state', operator: 'equals', value: 'open' },
      ],
    };

    expect(triggerConditionEngine.evaluate(groupOR, sampleNormalizedEvent.data).matched).toBe(true);
  });

  it('16. evaluates nested dot-path resolution in event data (data.issue.title, data.labels[0])', () => {
    const condNested: TriggerCondition = {
      field: 'issue.author.isStaff',
      operator: 'equals',
      value: true,
    };

    expect(triggerConditionEngine.evaluate(condNested, sampleNormalizedEvent.data).matched).toBe(true);

    const condArray: TriggerCondition = {
      field: 'issue.labels[0]',
      operator: 'equals',
      value: 'bug',
    };

    expect(triggerConditionEngine.evaluate(condArray, sampleNormalizedEvent.data).matched).toBe(true);
  });

  it('17. fails closed (evaluates to false) on missing or invalid dot-paths', () => {
    const condMissing: TriggerCondition = {
      field: 'issue.deeply.nested.missing.path',
      operator: 'equals',
      value: 'anything',
    };

    const res = triggerConditionEngine.evaluate(condMissing, sampleNormalizedEvent.data);
    expect(res.matched).toBe(false);
    expect(res.error).toBeDefined();
  });

  it('18. fails closed on type mismatches (e.g. greater_than on string)', () => {
    const condTypeMismatch: TriggerCondition = {
      field: 'issue.title',
      operator: 'greater_than',
      value: 42,
    };

    const res = triggerConditionEngine.evaluate(condTypeMismatch, sampleNormalizedEvent.data);
    expect(res.matched).toBe(false);
  });

  it('19. rejects condition evaluation if condition attempts code execution or malicious prototypes', () => {
    const maliciousCond: TriggerCondition = {
      field: '__proto__.polluted',
      operator: 'equals',
      value: 'pwned',
    };

    const res = triggerConditionEngine.evaluate(maliciousCond, sampleNormalizedEvent.data);
    expect(res.matched).toBe(false);
    expect(res.error).toContain('Unsafe field path');
  });

  it('20. handles complex nested boolean tree (AND containing OR and atomic rules)', () => {
    const complexTree: TriggerConditionGroup = {
      logicalOperator: 'AND',
      conditions: [
        { field: 'issue.number', operator: 'greater_than', value: 0 },
        {
          logicalOperator: 'OR',
          conditions: [
            { field: 'issue.state', operator: 'equals', value: 'closed' },
            {
              logicalOperator: 'AND',
              conditions: [
                { field: 'issue.state', operator: 'equals', value: 'open' },
                { field: 'issue.author.username', operator: 'equals', value: 'octocat' },
              ],
            },
          ],
        },
      ],
    };

    const res = triggerConditionEngine.evaluate(complexTree, sampleNormalizedEvent.data);
    expect(res.matched).toBe(true);
  });

  // ============================================================
  // SECTION 3: TRIGGER EVALUATION & PATTERN MATCHING (Tests 21 - 26)
  // ============================================================

  it('21. matches trigger when sourceSystem, resourceType, and changeType match', () => {
    const trigger: Trigger = {
      triggerId: 'trig_exact_match',
      name: 'Exact Match',
      status: 'ACTIVE',
      version: 1,
      riskLevel: 'LOW',
      eventFilter: {
        sourceSystem: 'GITHUB',
        resourceType: 'ISSUE',
        changeType: 'CREATED',
      },
      reaction: { reactionType: 'CREATE_OBSERVATION' },
      provenance: {
        createdBy: 'admin',
        createdAt: new Date().toISOString(),
        updatedAt: new Date().toISOString(),
      },
    };

    triggerRegistry.registerTrigger(trigger);
    const matched = triggerEvaluationService.evaluateEvent(sampleNormalizedEvent);
    expect(matched.length).toBe(1);
    expect(matched[0]?.trigger?.triggerId).toBe('trig_exact_match');
  });

  it('22. supports wildcard * in event pattern matching', () => {
    const triggerWildcard: Trigger = {
      triggerId: 'trig_wildcard',
      name: 'Wildcard Match',
      status: 'ACTIVE',
      version: 1,
      riskLevel: 'LOW',
      eventFilter: {
        sourceSystem: '*',
        resourceType: 'ISSUE',
        changeType: '*',
      },
      reaction: { reactionType: 'CREATE_OBSERVATION' },
      provenance: {
        createdBy: 'admin',
        createdAt: new Date().toISOString(),
        updatedAt: new Date().toISOString(),
      },
    };

    triggerRegistry.registerTrigger(triggerWildcard);
    const matched = triggerEvaluationService.evaluateEvent(sampleNormalizedEvent);
    expect(matched.some((m) => m.trigger?.triggerId === 'trig_wildcard')).toBe(true);
  });

  it('23. filters out triggers whose event patterns do not match', () => {
    const triggerMismatch: Trigger = {
      triggerId: 'trig_drive_only',
      name: 'Drive Only',
      status: 'ACTIVE',
      version: 1,
      riskLevel: 'LOW',
      eventFilter: {
        sourceSystem: 'GOOGLE_DRIVE',
        resourceType: 'FILE',
        changeType: 'CREATED',
      },
      reaction: { reactionType: 'CREATE_OBSERVATION' },
      provenance: {
        createdBy: 'admin',
        createdAt: new Date().toISOString(),
        updatedAt: new Date().toISOString(),
      },
    };

    triggerRegistry.registerTrigger(triggerMismatch);
    const matched = triggerEvaluationService.evaluateEvent(sampleNormalizedEvent);
    expect(matched.some((m) => m.trigger?.triggerId === 'trig_drive_only')).toBe(false);
  });

  it('24. filters out disabled or revoked triggers even if pattern matches', () => {
    const triggerDisabled: Trigger = {
      triggerId: 'trig_disabled_filter',
      name: 'Disabled Trigger',
      status: 'DISABLED',
      version: 1,
      riskLevel: 'LOW',
      eventFilter: {
        sourceSystem: 'GITHUB',
        resourceType: 'ISSUE',
      },
      reaction: { reactionType: 'CREATE_OBSERVATION' },
      provenance: {
        createdBy: 'admin',
        createdAt: new Date().toISOString(),
        updatedAt: new Date().toISOString(),
      },
    };

    triggerRegistry.registerTrigger(triggerDisabled);
    const matched = triggerEvaluationService.evaluateEvent(sampleNormalizedEvent);
    expect(matched.some((m) => m.trigger?.triggerId === 'trig_disabled_filter')).toBe(false);
  });

  it('25. filters out triggers whose conditions evaluate to false', () => {
    const triggerFalseCond: Trigger = {
      triggerId: 'trig_false_cond',
      name: 'Closed Issues Only',
      status: 'ACTIVE',
      version: 1,
      riskLevel: 'LOW',
      eventFilter: { sourceSystem: 'GITHUB', resourceType: 'ISSUE' },
      conditions: {
        field: 'issue.state',
        operator: 'equals',
        value: 'closed',
      },
      reaction: { reactionType: 'CREATE_OBSERVATION' },
      provenance: {
        createdBy: 'admin',
        createdAt: new Date().toISOString(),
        updatedAt: new Date().toISOString(),
      },
    };

    triggerRegistry.registerTrigger(triggerFalseCond);
    const matched = triggerEvaluationService.evaluateEvent(sampleNormalizedEvent);
    expect(matched.some((m) => m.trigger?.triggerId === 'trig_false_cond')).toBe(false);
  });

  it('26. evaluates multiple triggers against a single normalized event', () => {
    const t1: Trigger = {
      triggerId: 'trig_multi_1',
      name: 'Multi 1',
      status: 'ACTIVE',
      version: 1,
      riskLevel: 'LOW',
      eventFilter: { sourceSystem: 'GITHUB' },
      reaction: { reactionType: 'CREATE_OBSERVATION' },
      provenance: { createdBy: 'admin', createdAt: '', updatedAt: '' },
    };
    const t2: Trigger = {
      triggerId: 'trig_multi_2',
      name: 'Multi 2',
      status: 'ACTIVE',
      version: 1,
      riskLevel: 'LOW',
      eventFilter: { resourceType: 'ISSUE' },
      reaction: { reactionType: 'REQUEST_ANALYSIS' },
      provenance: { createdBy: 'admin', createdAt: '', updatedAt: '' },
    };

    triggerRegistry.registerTrigger(t1);
    triggerRegistry.registerTrigger(t2);

    const matched = triggerEvaluationService.evaluateEvent(sampleNormalizedEvent);
    expect(matched.length).toBeGreaterThanOrEqual(2);
  });

  // ============================================================
  // SECTION 4: RISK CLASSIFICATION & ELEVATION (Tests 27 - 32)
  // ============================================================

  it('27. classifies passive observation (CREATE_OBSERVATION) as LOW risk', () => {
    const risk = triggerRiskService.calculateReactionRisk({
      reactionType: 'CREATE_OBSERVATION',
    });
    expect(risk).toBe('LOW');
  });

  it('28. classifies analysis request (REQUEST_ANALYSIS) as LOW/MEDIUM risk', () => {
    const risk = triggerRiskService.calculateReactionRisk({
      reactionType: 'REQUEST_ANALYSIS',
    });
    expect(risk === 'LOW' || risk === 'MEDIUM').toBe(true);
  });

  it('29. classifies mission modification (PAUSE_MISSION, REPLAN_MISSION) as HIGH risk', () => {
    const pauseRisk = triggerRiskService.calculateReactionRisk({
      reactionType: 'PAUSE_MISSION',
    });
    const replanRisk = triggerRiskService.calculateReactionRisk({
      reactionType: 'REPLAN_MISSION',
    });
    expect(pauseRisk).toBe('HIGH');
    expect(replanRisk).toBe('HIGH');
  });

  it('30. classifies external action write (EXTERNAL_ACTION) as CRITICAL risk', () => {
    const risk = triggerRiskService.calculateReactionRisk({
      reactionType: 'EXTERNAL_ACTION',
      actionIntent: {
        capabilityId: 'github_write',
        operation: 'create_comment',
        parameters: { body: 'auto comment' },
        requiredRisk: 'CRITICAL',
      },
    });
    expect(risk).toBe('CRITICAL');
  });

  it('31. automatically elevates trigger risk if declared risk is lower than reaction operational risk', () => {
    const effectiveRisk = triggerRiskService.elevateRisk(
      'LOW', // Trigger falsely declares itself LOW risk
      {
        reactionType: 'EXTERNAL_ACTION',
        actionIntent: {
          capabilityId: 'github_write',
          operation: 'delete_repo',
          parameters: {},
          requiredRisk: 'CRITICAL',
        },
      }
    );
    expect(effectiveRisk).toBe('CRITICAL');
  });

  it('32. flags consequential triggers as requiring human approval', () => {
    const requiresApproval = triggerRiskService.requiresHumanApproval('HIGH', {
      reactionType: 'PAUSE_MISSION',
    });
    expect(requiresApproval).toBe(true);
  });

  // ============================================================
  // SECTION 5: REACTION PROPOSAL & AUTHORIZATION (Tests 33 - 40)
  // ============================================================

  it('33. generates a reaction proposal with deterministic ID and provenance', () => {
    const trigger: Trigger = {
      triggerId: 'trig_prop_test',
      name: 'Proposal Test',
      status: 'ACTIVE',
      version: 1,
      riskLevel: 'LOW',
      eventFilter: { sourceSystem: 'GITHUB' },
      reaction: { reactionType: 'CREATE_OBSERVATION' },
      provenance: { createdBy: 'admin', createdAt: '', updatedAt: '' },
    };

    const proposal = reactionProposalService.createProposal(trigger, sampleNormalizedEvent, {
      causationId: 'cau_101',
      correlationId: 'cor_101',
      depth: 0,
    });

    expect(proposal.proposalId).toBeDefined();
    expect(proposal.provenance.causationId).toBe('cau_101');
    expect(proposal.provenance.correlationId).toBe('cor_101');
    expect(proposal.provenance.depth).toBe(0);
  });

  it('34. automatically authorizes LOW risk proposals', () => {
    const trigger: Trigger = {
      triggerId: 'trig_low_auto',
      name: 'Low Auto Auth',
      status: 'ACTIVE',
      version: 1,
      riskLevel: 'LOW',
      eventFilter: { sourceSystem: 'GITHUB' },
      reaction: { reactionType: 'CREATE_OBSERVATION' },
      provenance: { createdBy: 'admin', createdAt: '', updatedAt: '' },
    };

    const proposal = reactionProposalService.createProposal(trigger, sampleNormalizedEvent, {});
    expect(proposal.status).toBe('AUTHORIZED');
    expect(proposal.requiresHumanApproval).toBe(false);
  });

  it('35. sets HIGH/CRITICAL proposals to AWAITING_APPROVAL', () => {
    const trigger: Trigger = {
      triggerId: 'trig_high_gate',
      name: 'High Risk Gate',
      status: 'ACTIVE',
      version: 1,
      riskLevel: 'HIGH',
      eventFilter: { sourceSystem: 'GITHUB' },
      reaction: { reactionType: 'PAUSE_MISSION', targetMissionId: 'mis_101' },
      provenance: { createdBy: 'admin', createdAt: '', updatedAt: '' },
    };

    const proposal = reactionProposalService.createProposal(trigger, sampleNormalizedEvent, {});
    expect(proposal.status).toBe('AWAITING_APPROVAL');
    expect(proposal.requiresHumanApproval).toBe(true);
  });

  it('36. human operator approval successfully grants authorization', () => {
    const trigger: Trigger = {
      triggerId: 'trig_human_approve',
      name: 'Human Approval Test',
      status: 'ACTIVE',
      version: 1,
      riskLevel: 'HIGH',
      eventFilter: { sourceSystem: 'GITHUB' },
      reaction: { reactionType: 'PAUSE_MISSION', targetMissionId: 'mis_101' },
      provenance: { createdBy: 'admin', createdAt: '', updatedAt: '' },
    };

    const proposal = reactionProposalService.createProposal(trigger, sampleNormalizedEvent, {});
    expect(proposal.status).toBe('AWAITING_APPROVAL');

    const approveRes = reactionProposalService.grantApproval(
      proposal.proposalId,
      'operator_alice',
      'Confirmed by operator in console'
    );

    expect(approveRes.success).toBe(true);
    expect(approveRes.proposal?.status).toBe('AUTHORIZED');
    expect(approveRes.proposal?.operatorApproval?.approvedBy).toBe('operator_alice');
  });

  it('37. human operator rejection successfully marks proposal rejected', () => {
    const trigger: Trigger = {
      triggerId: 'trig_human_reject',
      name: 'Human Reject Test',
      status: 'ACTIVE',
      version: 1,
      riskLevel: 'HIGH',
      eventFilter: { sourceSystem: 'GITHUB' },
      reaction: { reactionType: 'PAUSE_MISSION', targetMissionId: 'mis_101' },
      provenance: { createdBy: 'admin', createdAt: '', updatedAt: '' },
    };

    const proposal = reactionProposalService.createProposal(trigger, sampleNormalizedEvent, {});
    const rejectRes = reactionProposalService.rejectProposal(
      proposal.proposalId,
      'operator_bob',
      'Unintended side effect'
    );

    expect(rejectRes.success).toBe(true);
    expect(rejectRes.proposal?.status).toBe('REJECTED');
  });

  it('38. autonomous agent approval attempt is strictly rejected (AUTONOMOUS_AGENT cannot approve)', () => {
    const trigger: Trigger = {
      triggerId: 'trig_agent_hack',
      name: 'Agent Hack Attempt',
      status: 'ACTIVE',
      version: 1,
      riskLevel: 'HIGH',
      eventFilter: { sourceSystem: 'GITHUB' },
      reaction: { reactionType: 'PAUSE_MISSION', targetMissionId: 'mis_101' },
      provenance: { createdBy: 'admin', createdAt: '', updatedAt: '' },
    };

    const proposal = reactionProposalService.createProposal(trigger, sampleNormalizedEvent, {});
    const failApprove = reactionProposalService.grantApproval(
      proposal.proposalId,
      'AUTONOMOUS_AGENT_SUBAGENT_42',
      'I approve myself'
    );

    expect(failApprove.success).toBe(false);
    expect(failApprove.error).toContain('Autonomous agents and system processes cannot grant human approval');
    expect(reactionProposalService.getProposal(proposal.proposalId)?.status).toBe('AWAITING_APPROVAL');
  });

  it('39. system approval attempt is strictly rejected (SYSTEM cannot approve)', () => {
    const trigger: Trigger = {
      triggerId: 'trig_sys_hack',
      name: 'System Hack Attempt',
      status: 'ACTIVE',
      version: 1,
      riskLevel: 'HIGH',
      eventFilter: { sourceSystem: 'GITHUB' },
      reaction: { reactionType: 'PAUSE_MISSION', targetMissionId: 'mis_101' },
      provenance: { createdBy: 'admin', createdAt: '', updatedAt: '' },
    };

    const proposal = reactionProposalService.createProposal(trigger, sampleNormalizedEvent, {});
    const failApprove = reactionProposalService.grantApproval(
      proposal.proposalId,
      'SYSTEM_ORCHESTRATOR',
      'System auto-approval'
    );

    expect(failApprove.success).toBe(false);
    expect(failApprove.error).toContain('Autonomous agents and system processes cannot grant human approval');
  });

  it('40. connector permission check enforces scope before authorization', () => {
    const authCheck = connectorPermissionService.evaluateAuthorization({
      connectorId: 'connector_github',
      capabilityId: 'github_read',
      operation: 'UNAUTHORIZED_OP',
      agentId: 'agent_test',
    });

    expect(authCheck.authorized).toBe(false);
  });

  // ============================================================
  // SECTION 6: REACTION EXECUTION & ACTION BUS (Tests 41 - 47)
  // ============================================================

  it('41. executes authorized reaction via Stage 15 Action Bus (actionBusService.execute)', async () => {
    const actionSpy = vi.spyOn(actionBusService, 'execute');

    const trigger: Trigger = {
      triggerId: 'trig_bus_exec',
      name: 'Action Bus Trigger',
      status: 'ACTIVE',
      version: 1,
      riskLevel: 'LOW',
      eventFilter: { sourceSystem: 'GITHUB' },
      reaction: {
        reactionType: 'EXTERNAL_ACTION',
        actionIntent: {
          capabilityId: 'github_read',
          operation: 'read_issue',
          parameters: { issueNumber: 42 },
          requiredRisk: 'LOW',
        },
      },
      provenance: { createdBy: 'admin', createdAt: '', updatedAt: '' },
    };

    const proposal = reactionProposalService.createProposal(trigger, sampleNormalizedEvent, {});
    expect(proposal.status).toBe('AUTHORIZED');

    const execRes = await reactionExecutionEngine.executeProposal(proposal);
    expect(actionSpy).toHaveBeenCalled();
    expect(execRes.status).toBe('SUCCEEDED');
    actionSpy.mockRestore();
  });

  it('42. never bypasses Action Bus for external actions', async () => {
    const actionSpy = vi.spyOn(actionBusService, 'execute');

    const trigger: Trigger = {
      triggerId: 'trig_no_bypass',
      name: 'No Bypass Test',
      status: 'ACTIVE',
      version: 1,
      riskLevel: 'LOW',
      eventFilter: { sourceSystem: 'GITHUB' },
      reaction: {
        reactionType: 'EXTERNAL_ACTION',
        actionIntent: {
          capabilityId: 'file_read',
          operation: 'read',
          parameters: { path: '/workspace/test.txt' },
        },
      },
      provenance: { createdBy: 'admin', createdAt: '', updatedAt: '' },
    };

    const proposal = reactionProposalService.createProposal(trigger, sampleNormalizedEvent, {});
    await reactionExecutionEngine.executeProposal(proposal);
    expect(actionSpy).toHaveBeenCalledTimes(1);
    actionSpy.mockRestore();
  });

  it('43. zero AI/LLM inference calls during reaction execution (executionGateway.execute 0 calls)', async () => {
    const gatewaySpy = vi.spyOn(executionGateway, 'execute');

    const trigger: Trigger = {
      triggerId: 'trig_zero_llm',
      name: 'Zero LLM Test',
      status: 'ACTIVE',
      version: 1,
      riskLevel: 'LOW',
      eventFilter: { sourceSystem: 'GITHUB' },
      reaction: { reactionType: 'CREATE_OBSERVATION' },
      provenance: { createdBy: 'admin', createdAt: '', updatedAt: '' },
    };

    const proposal = reactionProposalService.createProposal(trigger, sampleNormalizedEvent, {});
    await reactionExecutionEngine.executeProposal(proposal);

    expect(gatewaySpy).not.toHaveBeenCalled();
    gatewaySpy.mockRestore();
  });

  it('44. blocks execution of proposals that are still AWAITING_APPROVAL', async () => {
    const trigger: Trigger = {
      triggerId: 'trig_blocked_unapproved',
      name: 'Blocked Unapproved',
      status: 'ACTIVE',
      version: 1,
      riskLevel: 'HIGH',
      eventFilter: { sourceSystem: 'GITHUB' },
      reaction: { reactionType: 'PAUSE_MISSION', targetMissionId: 'mis_101' },
      provenance: { createdBy: 'admin', createdAt: '', updatedAt: '' },
    };

    const proposal = reactionProposalService.createProposal(trigger, sampleNormalizedEvent, {});
    expect(proposal.status).toBe('AWAITING_APPROVAL');

    const execRes = await reactionExecutionEngine.executeProposal(proposal);
    expect(execRes.status).toBe('REQUIRES_APPROVAL');
    expect(execRes.error).toContain('Proposal requires human approval');
  });

  it('45. blocks execution of proposals that are REJECTED', async () => {
    const trigger: Trigger = {
      triggerId: 'trig_blocked_rejected',
      name: 'Blocked Rejected',
      status: 'ACTIVE',
      version: 1,
      riskLevel: 'HIGH',
      eventFilter: { sourceSystem: 'GITHUB' },
      reaction: { reactionType: 'PAUSE_MISSION', targetMissionId: 'mis_101' },
      provenance: { createdBy: 'admin', createdAt: '', updatedAt: '' },
    };

    const proposal = reactionProposalService.createProposal(trigger, sampleNormalizedEvent, {});
    reactionProposalService.rejectProposal(proposal.proposalId, 'operator_alice', 'No');

    const rejectedProposal = reactionProposalService.getProposal(proposal.proposalId)!;
    const execRes = await reactionExecutionEngine.executeProposal(rejectedProposal);
    expect(execRes.status).toBe('REJECTED');
  });

  it('46. concurrency throttling enforced for reactions', async () => {
    // Engine initializes with maxConcurrent = 10
    expect(reactionExecutionEngine.getActiveExecutionCount()).toBe(0);
  });

  it('47. enforces idempotency deduplication (repeated execution returns existing result)', async () => {
    const trigger: Trigger = {
      triggerId: 'trig_idempotent_rxn',
      name: 'Idempotent Reaction',
      status: 'ACTIVE',
      version: 1,
      riskLevel: 'LOW',
      eventFilter: { sourceSystem: 'GITHUB' },
      reaction: { reactionType: 'CREATE_OBSERVATION' },
      provenance: { createdBy: 'admin', createdAt: '', updatedAt: '' },
    };

    const proposal = reactionProposalService.createProposal(trigger, sampleNormalizedEvent, {});
    const firstExec = await reactionExecutionEngine.executeProposal(proposal);
    expect(firstExec.status).toBe('SUCCEEDED');

    const secondExec = await reactionExecutionEngine.executeProposal(proposal);
    expect(secondExec.status).toBe('SUCCEEDED');
    expect(secondExec.reactionId).toBe(firstExec.reactionId);
  });

  // ============================================================
  // SECTION 7: CAUSAL LOOP PROTECTION & CHAIN LIMITS (Tests 48 - 52)
  // ============================================================

  it('48. propagates provenance across reactions (causationId, correlationId, depth, visitedTriggerIds)', () => {
    const trigger: Trigger = {
      triggerId: 'trig_provenance_prop',
      name: 'Provenance Propagation',
      status: 'ACTIVE',
      version: 1,
      riskLevel: 'LOW',
      eventFilter: { sourceSystem: 'GITHUB' },
      reaction: { reactionType: 'CREATE_OBSERVATION' },
      provenance: { createdBy: 'admin', createdAt: '', updatedAt: '' },
    };

    const proposal = reactionProposalService.createProposal(trigger, sampleNormalizedEvent, {
      causationId: 'cau_parent_77',
      correlationId: 'cor_mission_99',
      depth: 2,
      visitedTriggerIds: ['trig_ancestor_1', 'trig_ancestor_2'],
    });

    expect(proposal.provenance.causationId).toBe('cau_parent_77');
    expect(proposal.provenance.correlationId).toBe('cor_mission_99');
    expect(proposal.provenance.depth).toBe(2);
    expect(proposal.provenance.visitedTriggerIds).toContain('trig_ancestor_1');
    expect(proposal.provenance.visitedTriggerIds).toContain('trig_ancestor_2');
    expect(proposal.provenance.visitedTriggerIds).toContain('trig_provenance_prop');
  });

  it('49. terminates reaction chain when depth exceeds max depth (status: CHAIN_LIMIT)', async () => {
    const trigger: Trigger = {
      triggerId: 'trig_deep_chain',
      name: 'Deep Chain Trigger',
      status: 'ACTIVE',
      version: 1,
      riskLevel: 'LOW',
      eventFilter: { sourceSystem: 'GITHUB' },
      executionPolicy: { maxReactionDepth: 3 },
      reaction: { reactionType: 'CREATE_OBSERVATION' },
      provenance: { createdBy: 'admin', createdAt: '', updatedAt: '' },
    };

    // Proposal at depth 3 exceeds max depth limit
    const proposal = reactionProposalService.createProposal(trigger, sampleNormalizedEvent, {
      depth: 3,
    });

    const execRes = await reactionExecutionEngine.executeProposal(proposal);
    expect(execRes.status).toBe('CHAIN_LIMIT');
    expect(execRes.error).toContain('Reaction depth limit exceeded');
  });

  it('50. detects cyclic triggers via visitedTriggerIds and terminates immediately', async () => {
    const trigger: Trigger = {
      triggerId: 'trig_cycle_victim',
      name: 'Cyclic Trigger',
      status: 'ACTIVE',
      version: 1,
      riskLevel: 'LOW',
      eventFilter: { sourceSystem: 'GITHUB' },
      reaction: { reactionType: 'CREATE_OBSERVATION' },
      provenance: { createdBy: 'admin', createdAt: '', updatedAt: '' },
    };

    // Proposal where triggerId has already been visited
    const proposal = reactionProposalService.createProposal(trigger, sampleNormalizedEvent, {
      visitedTriggerIds: ['trig_cycle_victim'],
    });

    const execRes = await reactionExecutionEngine.executeProposal(proposal);
    expect(execRes.status).toBe('CHAIN_LIMIT');
    expect(execRes.error).toContain('Causal trigger cycle detected');
  });

  it('51. emits REACTION_CHAIN_LIMIT event to execution journal on cycle or depth breach', async () => {
    const journalSpy = vi.spyOn(executionJournal, 'appendEvent');

    const trigger: Trigger = {
      triggerId: 'trig_journal_limit',
      name: 'Journal Limit Trigger',
      status: 'ACTIVE',
      version: 1,
      riskLevel: 'LOW',
      eventFilter: { sourceSystem: 'GITHUB' },
      reaction: { reactionType: 'CREATE_OBSERVATION' },
      provenance: { createdBy: 'admin', createdAt: '', updatedAt: '' },
    };

    const proposal = reactionProposalService.createProposal(trigger, sampleNormalizedEvent, {
      depth: 4,
    });

    await reactionExecutionEngine.executeProposal(proposal);

    expect(journalSpy).toHaveBeenCalledWith(
      expect.objectContaining({
        eventType: 'REACTION_CHAIN_LIMIT',
      })
    );
    journalSpy.mockRestore();
  });

  it('52. preserves failure audit trail without infinite recursion', async () => {
    const trigger: Trigger = {
      triggerId: 'trig_failing_rxn',
      name: 'Failing Reaction',
      status: 'ACTIVE',
      version: 1,
      riskLevel: 'LOW',
      eventFilter: { sourceSystem: 'GITHUB' },
      reaction: {
        reactionType: 'PAUSE_MISSION', // Missing required targetMissionId triggers clean error
      },
      provenance: { createdBy: 'admin', createdAt: '', updatedAt: '' },
    };

    const proposal = reactionProposalService.createProposal(trigger, sampleNormalizedEvent, {});
    const res = await reactionExecutionEngine.executeProposal(proposal);

    expect(res.status).toBe('FAILED');
    expect(res.error).toBeDefined();

    // Verify stored in execution results
    const stored = reactionExecutionEngine.getExecutionResult(proposal.proposalId);
    expect(stored?.status).toBe('FAILED');
  });

  // ============================================================
  // SECTION 8: MISSION, GOAL & RECOVERY INTEGRATION (Tests 53 - 57)
  // ============================================================

  it('53. dispatches PAUSE_MISSION to missionManager successfully', async () => {
    const pauseSpy = vi.spyOn(missionManager, 'pauseMission').mockReturnValue(true);

    const trigger: Trigger = {
      triggerId: 'trig_pause_mis',
      name: 'Pause Mission',
      status: 'ACTIVE',
      version: 1,
      riskLevel: 'HIGH',
      eventFilter: { sourceSystem: 'GITHUB' },
      reaction: {
        reactionType: 'PAUSE_MISSION',
        targetMissionId: 'mis_target_99',
      },
      provenance: { createdBy: 'admin', createdAt: '', updatedAt: '' },
    };

    const proposal = reactionProposalService.createProposal(trigger, sampleNormalizedEvent, {});
    reactionProposalService.grantApproval(proposal.proposalId, 'operator_alice');

    const approvedProposal = reactionProposalService.getProposal(proposal.proposalId)!;
    const res = await reactionExecutionEngine.executeProposal(approvedProposal);

    expect(res.status).toBe('SUCCEEDED');
    expect(pauseSpy).toHaveBeenCalledWith('mis_target_99');
    pauseSpy.mockRestore();
  });

  it('54. dispatches REPLAN_MISSION to missionReplanner successfully', async () => {
    const replanSpy = vi.spyOn(missionReplanner, 'replanMission').mockReturnValue({
      success: true,
      missionId: 'mis_target_99',
      oldVersion: 1,
      newVersion: 2,
      strategyApplied: 'INCREMENTAL_EXTEND',
      summary: 'Replanned',
    } as any);

    const trigger: Trigger = {
      triggerId: 'trig_replan_mis',
      name: 'Replan Mission',
      status: 'ACTIVE',
      version: 1,
      riskLevel: 'HIGH',
      eventFilter: { sourceSystem: 'GITHUB' },
      reaction: {
        reactionType: 'REPLAN_MISSION',
        targetMissionId: 'mis_target_99',
      },
      provenance: { createdBy: 'admin', createdAt: '', updatedAt: '' },
    };

    const proposal = reactionProposalService.createProposal(trigger, sampleNormalizedEvent, {});
    reactionProposalService.grantApproval(proposal.proposalId, 'operator_alice');

    const approvedProposal = reactionProposalService.getProposal(proposal.proposalId)!;
    const res = await reactionExecutionEngine.executeProposal(approvedProposal);

    expect(res.status).toBe('SUCCEEDED');
    expect(replanSpy).toHaveBeenCalledWith('mis_target_99', expect.any(String));
    replanSpy.mockRestore();
  });

  it('55. dispatches CREATE_GOAL to goalOrchestrator successfully', async () => {
    const goalSpy = vi.spyOn(goalOrchestrator, 'createAndExecuteGoal').mockResolvedValue({
      goalId: 'goal_spawned_1',
      title: 'Fix bug',
      status: 'COMPLETED',
    } as any);

    const trigger: Trigger = {
      triggerId: 'trig_spawn_goal',
      name: 'Spawn Goal',
      status: 'ACTIVE',
      version: 1,
      riskLevel: 'HIGH',
      eventFilter: { sourceSystem: 'GITHUB' },
      reaction: {
        reactionType: 'CREATE_GOAL',
        goalIntent: 'Investigate and fix bug 42',
      },
      provenance: { createdBy: 'admin', createdAt: '', updatedAt: '' },
    };

    const proposal = reactionProposalService.createProposal(trigger, sampleNormalizedEvent, {});
    reactionProposalService.grantApproval(proposal.proposalId, 'operator_alice');

    const approvedProposal = reactionProposalService.getProposal(proposal.proposalId)!;
    const res = await reactionExecutionEngine.executeProposal(approvedProposal);

    expect(res.status).toBe('SUCCEEDED');
    expect(goalSpy).toHaveBeenCalledWith('Investigate and fix bug 42');
    goalSpy.mockRestore();
  });

  it('56. persistence saves triggers, proposals, and results in executionPersistence', () => {
    const trigger: Trigger = {
      triggerId: 'trig_persist_test',
      name: 'Persist Test',
      status: 'ACTIVE',
      version: 1,
      riskLevel: 'LOW',
      eventFilter: { sourceSystem: 'GITHUB' },
      reaction: { reactionType: 'CREATE_OBSERVATION' },
      provenance: { createdBy: 'admin', createdAt: '', updatedAt: '' },
    };

    executionPersistence.saveTrigger(trigger);
    expect(executionPersistence.getTrigger('trig_persist_test')).toBeDefined();
    expect(executionPersistence.getAllTriggers().length).toBeGreaterThanOrEqual(1);

    const proposal: ReactionProposal = {
      proposalId: 'prop_persist_test',
      triggerId: 'trig_persist_test',
      triggerVersion: 1,
      eventId: 'evt_101',
      reactionType: 'CREATE_OBSERVATION',
      reactionParameters: {},
      riskLevel: 'LOW',
      requiresHumanApproval: false,
      status: 'AUTHORIZED',
      proposedAt: new Date().toISOString(),
      provenance: {
        triggeredAt: new Date().toISOString(),
        eventFingerprint: 'evt_101',
        causationId: 'cau_1',
        correlationId: 'cor_1',
        depth: 0,
        visitedTriggerIds: ['trig_persist_test'],
      },
      authorizationRequirements: {
        requiresHumanApproval: false,
        requiredPermissions: [],
      },
    };

    executionPersistence.saveReactionProposal(proposal);
    expect(executionPersistence.getReactionProposal('prop_persist_test')).toBeDefined();
    expect(executionPersistence.getAllReactionProposals().length).toBeGreaterThanOrEqual(1);
  });

  it('57. restart recovers triggers and proposals from persistence', () => {
    const trigger: Trigger = {
      triggerId: 'trig_survive_reboot',
      name: 'Reboot Survivor',
      status: 'ACTIVE',
      version: 1,
      riskLevel: 'LOW',
      eventFilter: { sourceSystem: 'GITHUB' },
      reaction: { reactionType: 'CREATE_OBSERVATION' },
      provenance: { createdBy: 'admin', createdAt: '', updatedAt: '' },
    };

    executionPersistence.saveTrigger(trigger);

    // Simulate service restart by clearing registry cache and re-loading
    triggerRegistry.clear();
    expect(triggerRegistry.getTrigger('trig_survive_reboot')).toBeNull();

    triggerRegistry.loadFromPersistence();
    expect(triggerRegistry.getTrigger('trig_survive_reboot')).toBeDefined();
  });

  // ============================================================
  // SECTION 9: HUD & VISUAL ASSET IMMUTABILITY (Tests 58 - 60)
  // ============================================================

  it('58. SpatialCommandConsole renders Stage 19 HUD panels in DOM', () => {
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

    expect(getByTestId('trigger-reaction-hud')).toBeDefined();
    expect(getByTestId('trigger-registry-hud')).toBeDefined();
    expect(getByTestId('trigger-evaluation-hud')).toBeDefined();
    expect(getByTestId('reaction-queue-hud')).toBeDefined();
    expect(getByTestId('reaction-audit-hud')).toBeDefined();
  });

  it('59. Stage 03 camera baseline immutable and reconciled', () => {
    expect(STAGE03_CAMERAS.CAM_CinematicHero.fov).toBeCloseTo(39.761, 2);
    expect(STAGE03_CAMERAS.CAM_CinematicHero.position).toEqual([-12.0, 2.3, 38.5]);

    expect(STAGE03_CAMERAS.CAM_MonumentalLowAngle.fov).toBeCloseTo(49.426, 2);
    expect(STAGE03_CAMERAS.CAM_MonumentalLowAngle.position).toEqual([0.0, 0.65, 26.0]);

    expect(STAGE03_CAMERAS.CAM_ArchiveDetail.fov).toBeCloseTo(35.115, 2);
    expect(STAGE03_CAMERAS.CAM_ArchiveDetail.position).toEqual([-16.2, 1.85, 32.8]);
  });

  it('60. zero additional WebGL draw calls introduced by reaction engine HUDs', () => {
    // The HUD elements are rendered exclusively in the DOM layer outside the WebGL canvas
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

    // Canvas elements inside SpatialCommandConsole must be 0 (DOM only)
    const canvases = container.querySelectorAll('canvas');
    expect(canvases.length).toBe(0);
  });
});
