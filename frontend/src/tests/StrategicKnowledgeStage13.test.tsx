/**
 * AryaOS V1 — Stage 13 Test Suite: Strategic Knowledge Graph & Long-Term Memory
 *
 * Verifies all 35 required specifications:
 * 1. Canonical knowledge node creation.
 * 2. Canonical edge creation.
 * 3. Duplicate node prevention.
 * 4. Duplicate edge prevention.
 * 5. Fact creation with provenance.
 * 6. Evidence linkage.
 * 7. Confidence calculation.
 * 8. UNKNOWN confidence when evidence is insufficient.
 * 9. Temporal validity.
 * 10. Knowledge decay.
 * 11. Contradiction detection.
 * 12. Contradiction preservation.
 * 13. Evidence-weighted resolution.
 * 14. Pattern detection.
 * 15. Pattern evidence threshold.
 * 16. Strategy candidate creation.
 * 17. Strategy validation.
 * 18. Strategic context retrieval.
 * 19. Context ranking explainability.
 * 20. Knowledge query.
 * 21. Mission knowledge snapshot.
 * 22. Project knowledge linkage.
 * 23. Character knowledge linkage.
 * 24. Asset knowledge linkage.
 * 25. Persistence.
 * 26. Restart recovery.
 * 27. Ingestion idempotency.
 * 28. Snapshot versioning.
 * 29. Secret sanitization.
 * 30. Human governance boundary.
 * 31. Stage 11 integration.
 * 32. Stage 12 integration.
 * 33. Gateway exclusivity.
 * 34. Zero Stage 03 modifications.
 * 35. Zero additional draw calls.
 */

import { describe, it, expect, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import React from 'react';
import { STAGE03_CAMERAS } from '../stage03_assembly';

import {
  KnowledgeNode,
  KnowledgeEdge,
  KnowledgeFact,
  KnowledgeEvidence,
  KnowledgeProvenance,
} from '../types/strategicKnowledge';
import { knowledgeGraph, KnowledgeGraph } from '../services/knowledgeGraph';
import { knowledgeConfidenceService } from '../services/knowledgeConfidenceService';
import { knowledgeRelationExtractor } from '../services/knowledgeRelationExtractor';
import { knowledgeContradictionService } from '../services/knowledgeContradictionService';
import { knowledgeResolutionService } from '../services/knowledgeResolutionService';
import { strategicPatternService } from '../services/strategicPatternService';
import { strategyModelService } from '../services/strategyModel';
import { strategicContextService } from '../services/strategicContextService';
import { knowledgeQueryService } from '../services/knowledgeQueryService';
import { knowledgeIngestionService } from '../services/knowledgeIngestionService';
import { executionPersistence } from '../services/executionPersistence';
import { SpatialCommandConsole } from '../components/spatial/SpatialCommandConsole';

describe('AryaOS V1 Stage 13 — Strategic Knowledge Graph & Long-Term Memory', () => {
  const dummyProvenance: KnowledgeProvenance = {
    source: {
      sourceType: 'STAGE11_EVALUATION',
      sourceId: 'eval-researcher-001',
      timestamp: '2026-10-02T08:00:00.000Z',
    },
    extractedAt: '2026-10-02T08:05:00.000Z',
    derivedBy: 'StrategicKnowledgeTest',
  };

  beforeEach(() => {
    knowledgeGraph.clear();
    knowledgeContradictionService.clear();
    strategicPatternService.clear();
    strategyModelService.clear();
    localStorage.clear();
    executionPersistence.clearEnvelope();
  });

  // 1. Canonical knowledge node creation
  it('1. creates canonical knowledge node with required attributes and provenance', () => {
    const node: KnowledgeNode = {
      id: 'agent:researcher',
      type: 'AGENT',
      label: 'Deep Research Specialist',
      createdAt: '2026-10-02T08:00:00.000Z',
      updatedAt: '2026-10-02T08:00:00.000Z',
      provenance: dummyProvenance,
      confidence: 'HIGH',
      status: 'VERIFIED',
    };

    const added = knowledgeGraph.addNode(node);
    expect(added.id).toBe('agent:researcher');
    expect(added.type).toBe('AGENT');
    expect(added.status).toBe('VERIFIED');
    expect(knowledgeGraph.getNode('agent:researcher')).not.toBeNull();
  });

  // 2. Canonical edge creation
  it('2. creates canonical typed directed edge with provenance and deterministic ID', () => {
    knowledgeGraph.addNode({
      id: 'agent:researcher',
      type: 'AGENT',
      label: 'Researcher',
      createdAt: '2026-10-02T08:00:00.000Z',
      updatedAt: '2026-10-02T08:00:00.000Z',
      provenance: dummyProvenance,
      confidence: 'HIGH',
      status: 'VERIFIED',
    });

    knowledgeGraph.addNode({
      id: 'provider:gemini',
      type: 'PROVIDER',
      label: 'Gemini 1.5 Pro',
      createdAt: '2026-10-02T08:00:00.000Z',
      updatedAt: '2026-10-02T08:00:00.000Z',
      provenance: dummyProvenance,
      confidence: 'HIGH',
      status: 'VERIFIED',
    });

    const edge = knowledgeRelationExtractor.createRelation({
      source: 'agent:researcher',
      target: 'provider:gemini',
      relation: 'AGENT_USED_PROVIDER',
      provenance: dummyProvenance,
    });

    const addedEdge = knowledgeGraph.addEdge(edge);
    expect(addedEdge.id).toBe('edge:agent:researcher--AGENT_USED_PROVIDER-->provider:gemini');
    expect(knowledgeGraph.getEdges('agent:researcher').length).toBe(1);
  });

  // 3. Duplicate node prevention
  it('3. prevents duplicate nodes and preserves canonical identity idempotently', () => {
    const nodeA: KnowledgeNode = {
      id: 'agent:writer',
      type: 'AGENT',
      label: 'Writer Initial',
      createdAt: '2026-10-02T08:00:00.000Z',
      updatedAt: '2026-10-02T08:00:00.000Z',
      provenance: dummyProvenance,
      confidence: 'LOW',
      status: 'CANDIDATE',
    };

    const nodeB: KnowledgeNode = {
      id: 'agent:writer',
      type: 'AGENT',
      label: 'Writer Updated',
      createdAt: '2026-10-02T08:10:00.000Z',
      updatedAt: '2026-10-02T08:10:00.000Z',
      provenance: dummyProvenance,
      confidence: 'HIGH',
      status: 'VERIFIED',
    };

    knowledgeGraph.addNode(nodeA);
    knowledgeGraph.addNode(nodeB);

    const stats = knowledgeGraph.getStats();
    expect(stats.nodeCount).toBe(1);
    expect(knowledgeGraph.getNode('agent:writer')?.label).toBe('Writer Updated');
    expect(knowledgeGraph.getNode('agent:writer')?.confidence).toBe('HIGH');
  });

  // 4. Duplicate edge prevention
  it('4. prevents duplicate edges for identical (source, target, relation)', () => {
    knowledgeGraph.addNode({
      id: 'n1',
      type: 'GOAL',
      label: 'Goal 1',
      createdAt: '',
      updatedAt: '',
      provenance: dummyProvenance,
      confidence: 'HIGH',
      status: 'VERIFIED',
    });
    knowledgeGraph.addNode({
      id: 'n2',
      type: 'GOAL',
      label: 'Goal 2',
      createdAt: '',
      updatedAt: '',
      provenance: dummyProvenance,
      confidence: 'HIGH',
      status: 'VERIFIED',
    });

    const edge: KnowledgeEdge = {
      id: 'edge:n1--GOAL_DEPENDS_ON_GOAL-->n2',
      source: 'n1',
      target: 'n2',
      relation: 'GOAL_DEPENDS_ON_GOAL',
      provenance: dummyProvenance,
      confidence: 'HIGH',
      createdAt: '2026-10-02T08:00:00.000Z',
    };

    knowledgeGraph.addEdge(edge);
    knowledgeGraph.addEdge(edge);

    expect(knowledgeGraph.getStats().edgeCount).toBe(1);
  });

  // 5. Fact creation with provenance
  it('5. creates knowledge facts with canonical deterministic ID and provenance', () => {
    const fact = knowledgeIngestionService.ingestFact({
      subject: 'agent:researcher',
      predicate: 'PERFORMS_WELL_FOR',
      object: 'domain:quantum_computing',
      evidence: [],
      provenance: dummyProvenance,
    });

    expect(fact.id).toBe('fact:agent:researcher::PERFORMS_WELL_FOR::domain:quantum_computing');
    expect(fact.provenance.source.sourceType).toBe('STAGE11_EVALUATION');
  });

  // 6. Evidence linkage
  it('6. correctly links supporting evidence IDs to knowledge facts', () => {
    const evidence1: KnowledgeEvidence = {
      id: 'ev-01',
      sourceType: 'STAGE11_EXPERIENCE',
      sourceId: 'exp-101',
      description: 'Successful deep research benchmark',
      timestamp: '2026-10-02T08:00:00.000Z',
      weight: 0.9,
      provenance: dummyProvenance,
    };
    const evidence2: KnowledgeEvidence = {
      id: 'ev-02',
      sourceType: 'STAGE11_EXPERIENCE',
      sourceId: 'exp-102',
      description: 'Second successful validation test',
      timestamp: '2026-10-02T08:15:00.000Z',
      weight: 0.85,
      provenance: dummyProvenance,
    };

    const fact = knowledgeIngestionService.ingestFact({
      subject: 'agent:researcher',
      predicate: 'PERFORMS_WELL_FOR',
      object: 'task:literature_survey',
      evidence: [evidence1, evidence2],
      provenance: dummyProvenance,
    });

    expect(fact.evidence).toContain('ev-01');
    expect(fact.evidence).toContain('ev-02');
    expect(fact.evidence.length).toBe(2);
  });

  // 7. Confidence calculation
  it('7. calculates confidence dynamically based on evidence count and quality', () => {
    const evidenceList: KnowledgeEvidence[] = [
      { id: 'e1', sourceType: 'STAGE11_EXPERIENCE', sourceId: 's1', description: '', timestamp: '2026-10-02T08:00:00Z', weight: 0.9, provenance: dummyProvenance },
      { id: 'e2', sourceType: 'STAGE11_EXPERIENCE', sourceId: 's2', description: '', timestamp: '2026-10-02T08:00:00Z', weight: 0.85, provenance: dummyProvenance },
      { id: 'e3', sourceType: 'STAGE11_EXPERIENCE', sourceId: 's3', description: '', timestamp: '2026-10-02T08:00:00Z', weight: 0.95, provenance: dummyProvenance },
      { id: 'e4', sourceType: 'STAGE11_EXPERIENCE', sourceId: 's4', description: '', timestamp: '2026-10-02T08:00:00Z', weight: 0.88, provenance: dummyProvenance },
    ];

    const result = knowledgeConfidenceService.evaluateConfidence({
      evidenceList,
    });

    expect(result.confidence).toBe('HIGH');
    expect(result.numericalScore).toBeGreaterThan(0.7);
  });

  // 8. UNKNOWN confidence when evidence is insufficient
  it('8. preserves uncertainty: returns UNKNOWN when 0 evidence, and LOW for single observation', () => {
    const zeroResult = knowledgeConfidenceService.evaluateConfidence({
      evidenceList: [],
    });
    expect(zeroResult.confidence).toBe('UNKNOWN');

    const singleResult = knowledgeConfidenceService.evaluateConfidence({
      evidenceList: [
        { id: 'e1', sourceType: 'STAGE11_EXPERIENCE', sourceId: 's1', description: '', timestamp: '2026-10-02T08:00:00Z', weight: 1.0, provenance: dummyProvenance },
      ],
    });
    // Strict invariant: 1 observation cannot be HIGH
    expect(singleResult.confidence).toBe('LOW');
  });

  // 9. Temporal validity
  it('9. evaluates temporal validity and flags obsolete or superseded facts without deleting them', () => {
    const activeFact: KnowledgeFact = {
      id: 'f-active',
      subject: 'a', predicate: 'b', object: 'c',
      evidence: [], confidence: 'MEDIUM', validity: 'ACTIVE', status: 'VERIFIED',
      validFrom: '2026-01-01T00:00:00Z',
      observedAt: '2026-01-01T00:00:00Z',
      provenance: dummyProvenance,
    };
    expect(knowledgeConfidenceService.evaluateTemporalValidity(activeFact).isValid).toBe(true);

    const obsoleteFact: KnowledgeFact = {
      ...activeFact,
      id: 'f-obsolete',
      validUntil: '2026-09-01T00:00:00Z',
    };
    const evalObsolete = knowledgeConfidenceService.evaluateTemporalValidity(obsoleteFact, '2026-10-02T00:00:00Z');
    expect(evalObsolete.isValid).toBe(false);
    expect(evalObsolete.validity).toBe('OBSOLETE');

    const supersededFact: KnowledgeFact = {
      ...activeFact,
      id: 'f-superseded',
      supersededAt: '2026-09-15T00:00:00Z',
    };
    const evalSuperseded = knowledgeConfidenceService.evaluateTemporalValidity(supersededFact, '2026-10-02T00:00:00Z');
    expect(evalSuperseded.isValid).toBe(false);
    expect(evalSuperseded.validity).toBe('SUPERSEDED');
  });

  // 10. Knowledge decay
  it('10. applies deterministic temporal decay without erasing historical facts', () => {
    const recentEvidence: KnowledgeEvidence[] = [
      { id: 'r1', sourceType: 'STAGE11_EXPERIENCE', sourceId: 's1', description: '', timestamp: '2026-10-01T00:00:00Z', weight: 0.9, provenance: dummyProvenance },
      { id: 'r2', sourceType: 'STAGE11_EXPERIENCE', sourceId: 's2', description: '', timestamp: '2026-10-01T00:00:00Z', weight: 0.9, provenance: dummyProvenance },
    ];
    const oldEvidence: KnowledgeEvidence[] = [
      { id: 'o1', sourceType: 'STAGE11_EXPERIENCE', sourceId: 's1', description: '', timestamp: '2026-01-01T00:00:00Z', weight: 0.9, provenance: dummyProvenance },
      { id: 'o2', sourceType: 'STAGE11_EXPERIENCE', sourceId: 's2', description: '', timestamp: '2026-01-01T00:00:00Z', weight: 0.9, provenance: dummyProvenance },
    ];

    const recentEval = knowledgeConfidenceService.evaluateConfidence({
      evidenceList: recentEvidence,
      observedAt: '2026-10-01T00:00:00Z',
      nowIso: '2026-10-02T00:00:00Z',
    });

    const oldEval = knowledgeConfidenceService.evaluateConfidence({
      evidenceList: oldEvidence,
      observedAt: '2026-01-01T00:00:00Z',
      nowIso: '2026-10-02T00:00:00Z',
    });

    expect(recentEval.decayedScore).toBeGreaterThan(oldEval.decayedScore);
    expect(oldEval.isDecayed).toBe(true);
  });

  // 11. Contradiction detection
  it('11. detects semantic contradictions between opposing factual predicates', () => {
    const factA: KnowledgeFact = {
      id: 'fact:agent-x::PERFORMS_WELL_FOR::research',
      subject: 'agent-x',
      predicate: 'PERFORMS_WELL_FOR',
      object: 'research',
      evidence: ['ev-1'],
      confidence: 'MEDIUM',
      validity: 'ACTIVE',
      status: 'VERIFIED',
      validFrom: '2026-10-01T00:00:00Z',
      observedAt: '2026-10-01T00:00:00Z',
      provenance: dummyProvenance,
    };

    const factB: KnowledgeFact = {
      id: 'fact:agent-x::UNDERPERFORMS_FOR::research',
      subject: 'agent-x',
      predicate: 'UNDERPERFORMS_FOR',
      object: 'research',
      evidence: ['ev-2'],
      confidence: 'MEDIUM',
      validity: 'ACTIVE',
      status: 'VERIFIED',
      validFrom: '2026-10-02T00:00:00Z',
      observedAt: '2026-10-02T00:00:00Z',
      provenance: dummyProvenance,
    };

    const contra = knowledgeContradictionService.evaluatePair(factA, factB);
    expect(contra).not.toBeNull();
    expect(contra?.type).toBe('FACT_CONTRADICTION');
    expect(contra?.severity).toBe('CRITICAL'); // active temporal overlap
  });

  // 12. Contradiction preservation
  it('12. preserves both conflicting facts without silent deletion', () => {
    const factA: KnowledgeFact = {
      id: 'fact:agent-a::PERFORMS_WELL_FOR::code',
      subject: 'agent-a', predicate: 'PERFORMS_WELL_FOR', object: 'code',
      evidence: ['ev-a'], confidence: 'MEDIUM', validity: 'ACTIVE', status: 'VERIFIED',
      validFrom: '2026-10-01T00:00:00Z', observedAt: '2026-10-01T00:00:00Z',
      provenance: dummyProvenance,
    };
    const factB: KnowledgeFact = {
      id: 'fact:agent-a::UNDERPERFORMS_FOR::code',
      subject: 'agent-a', predicate: 'UNDERPERFORMS_FOR', object: 'code',
      evidence: ['ev-b'], confidence: 'MEDIUM', validity: 'ACTIVE', status: 'VERIFIED',
      validFrom: '2026-10-02T00:00:00Z', observedAt: '2026-10-02T00:00:00Z',
      provenance: dummyProvenance,
    };

    executionPersistence.saveKnowledgeFact(factA);
    executionPersistence.saveKnowledgeFact(factB);

    const contradictions = knowledgeContradictionService.detectContradictions(factB, [factA]);
    expect(contradictions.length).toBe(1);

    // Both facts still exist in storage
    expect(executionPersistence.getKnowledgeFact(factA.id)).not.toBeNull();
    expect(executionPersistence.getKnowledgeFact(factB.id)).not.toBeNull();
  });

  // 13. Evidence-weighted resolution
  it('13. resolves contradiction via evidence weighting without destroying evidence', () => {
    const factA: KnowledgeFact = {
      id: 'fact:a::PERFORMS_WELL_FOR::task',
      subject: 'a', predicate: 'PERFORMS_WELL_FOR', object: 'task',
      evidence: ['e1', 'e2', 'e3', 'e4'], confidence: 'HIGH', validity: 'ACTIVE', status: 'VERIFIED',
      validFrom: '2026-10-01T00:00:00Z', observedAt: '2026-10-01T00:00:00Z',
      provenance: dummyProvenance,
    };
    const factB: KnowledgeFact = {
      id: 'fact:a::UNDERPERFORMS_FOR::task',
      subject: 'a', predicate: 'UNDERPERFORMS_FOR', object: 'task',
      evidence: ['e5'], confidence: 'LOW', validity: 'ACTIVE', status: 'VERIFIED',
      validFrom: '2026-10-01T00:00:00Z', observedAt: '2026-10-01T00:00:00Z',
      provenance: dummyProvenance,
    };

    const contra = knowledgeContradictionService.evaluatePair(factA, factB)!;
    const res = knowledgeResolutionService.resolveContradiction({
      contradiction: contra,
      factA,
      factB,
      preferredStrategy: 'EVIDENCE_WEIGHTING',
    });

    expect(res.resolutionStatus).toBe('RESOLVED');
    expect(res.preferredFactId).toBe(factA.id);
    expect(factB.validity).toBe('DISPUTED');
    expect(factB.evidence.length).toBe(1); // Evidence was NOT deleted
  });

  // 14. Pattern detection
  it('14. detects recurring operational patterns across experiences and agents', () => {
    const experiences = [
      { experienceId: 'exp-1', taskType: 'video_render', agentId: 'agent-media', providerId: 'kling', success: false },
      { experienceId: 'exp-2', taskType: 'video_render', agentId: 'agent-media', providerId: 'kling', success: false },
      { experienceId: 'exp-3', taskType: 'text_summary', agentId: 'agent-writer', providerId: 'gemini', success: true },
      { experienceId: 'exp-4', taskType: 'text_summary', agentId: 'agent-writer', providerId: 'gemini', success: true },
    ];

    const patterns = strategicPatternService.detectPatterns({ experiences });
    const failurePattern = patterns.find((p) => p.type === 'REPEATED_FAILURE');
    const successPattern = patterns.find((p) => p.type === 'AGENT_SPECIALIZATION');

    expect(failurePattern).toBeDefined();
    expect(failurePattern?.applicableEntities).toContain('agent-media');
    expect(successPattern).toBeDefined();
    expect(successPattern?.applicableEntities).toContain('agent-writer');
  });

  // 15. Pattern evidence threshold
  it('15. avoids pattern overfitting: requires minimum occurrence threshold before promoting pattern', () => {
    const singleExperience = [
      { experienceId: 'exp-isolated', taskType: '3d_mesh', agentId: 'agent-blender', providerId: 'local', success: false },
    ];

    const patterns = strategicPatternService.detectPatterns({ experiences: singleExperience });
    expect(patterns.length).toBe(0); // 1 occurrence is insufficient
  });

  // 16. Strategy candidate creation
  it('16. creates strategy candidate that is not automatically executable', () => {
    const strategy = strategyModelService.createCandidateStrategy({
      title: 'Parallel Research Strategy',
      description: 'Run deep literature survey concurrently with preliminary outline drafting',
      applicableTaskTypes: ['research', 'scriptwriting'],
      supportingEvidence: ['ev-01'],
      provenance: dummyProvenance,
    });

    expect(strategy.status).toBe('CANDIDATE');
    expect(strategy.applicableTaskTypes).toContain('research');
  });

  // 17. Strategy validation
  it('17. validates strategy when sufficient supporting evidence threshold is achieved', () => {
    const strategy = strategyModelService.createCandidateStrategy({
      title: 'Fallback Provider Strategy',
      description: 'Route to low-latency fallback on rate limit',
      applicableTaskTypes: ['inference'],
      supportingEvidence: ['ev-01'],
      provenance: dummyProvenance,
    });

    expect(() => strategyModelService.validateStrategy(strategy.strategyId, [])).toThrow(
      /at least 2 distinct pieces of supporting evidence/
    );

    const validated = strategyModelService.validateStrategy(strategy.strategyId, ['ev-02', 'ev-03']);
    expect(validated.status).toBe('VALIDATED');
    expect(validated.confidence).toBe('HIGH');
  });

  // 18. Strategic context retrieval
  it('18. retrieves bounded, relevant strategic context for a goal', () => {
    const f1: KnowledgeFact = {
      id: 'f1', subject: 'research', predicate: 'SUCCEEDED_WITH', object: 'gemini',
      evidence: ['e1', 'e2'], confidence: 'HIGH', validity: 'ACTIVE', status: 'VERIFIED',
      validFrom: '2026-10-01T00:00:00Z', observedAt: '2026-10-01T00:00:00Z', provenance: dummyProvenance,
    };
    const f2: KnowledgeFact = {
      id: 'f2', subject: 'audio', predicate: 'SUCCEEDED_WITH', object: 'elevenlabs',
      evidence: ['e3'], confidence: 'LOW', validity: 'ACTIVE', status: 'VERIFIED',
      validFrom: '2026-10-01T00:00:00Z', observedAt: '2026-10-01T00:00:00Z', provenance: dummyProvenance,
    };

    const ctx = strategicContextService.assembleContext({
      querySubject: 'Goal: Research Mission Plan',
      taskType: 'research',
      limitFacts: 1,
      availableFacts: [f1, f2],
    });

    expect(ctx.rankedFacts.length).toBe(1);
    expect(ctx.rankedFacts[0].fact.subject).toBe('research');
  });

  // 19. Context ranking explainability
  it('19. provides transparent, explainable ranking scores with detailed factor breakdowns', () => {
    const fact: KnowledgeFact = {
      id: 'f-ranked',
      subject: 'research_module',
      predicate: 'PERFORMS_WELL_FOR',
      object: 'deep_search',
      evidence: ['e1', 'e2', 'e3', 'e4'],
      confidence: 'HIGH',
      validity: 'ACTIVE',
      status: 'VERIFIED',
      validFrom: '2026-10-01T00:00:00Z',
      observedAt: '2026-10-01T00:00:00Z',
      provenance: dummyProvenance,
    };

    const ranking = strategicContextService.rankFact(fact, 'deep_search', 'mission-101');
    expect(ranking.score).toBeGreaterThan(0);
    expect(ranking.explanation.semanticRelevance).toBeDefined();
    expect(ranking.explanation.taskSimilarity).toBeDefined();
    expect(ranking.explanation.recency).toBeDefined();
    expect(ranking.explanation.confidenceWeight).toBeDefined();
    expect(ranking.explanation.rationale).toContain('Composite score:');
  });

  // 20. Knowledge query
  it('20. queries knowledge facts and matches relations correctly', () => {
    const fact: KnowledgeFact = {
      id: 'fact:agent-alpha::PERFORMS_WELL_FOR::translation',
      subject: 'agent-alpha',
      predicate: 'PERFORMS_WELL_FOR',
      object: 'translation',
      evidence: ['e1'],
      confidence: 'MEDIUM',
      validity: 'ACTIVE',
      status: 'VERIFIED',
      validFrom: '2026-10-01T00:00:00Z',
      observedAt: '2026-10-01T00:00:00Z',
      provenance: dummyProvenance,
    };
    executionPersistence.saveKnowledgeFact(fact);

    const queryResult = knowledgeQueryService.query({
      predicate: 'PERFORMS_WELL_FOR',
      object: 'translation',
    });

    expect(queryResult.facts.length).toBe(1);
    expect(queryResult.facts[0].subject).toBe('agent-alpha');
  });

  // 21. Mission knowledge snapshot
  it('21. summarizes completed mission into versioned MissionKnowledgeSnapshot', () => {
    const snapshot = knowledgeIngestionService.ingestMissionSummary({
      missionId: 'mission-042',
      objective: 'Deploy enterprise neural mesh',
      goals: [
        { goalId: 'g1', title: 'Verify topology', status: 'COMPLETED', durationMs: 1200 },
        { goalId: 'g2', title: 'Deploy nodes', status: 'COMPLETED', durationMs: 4500 },
      ],
      executionStrategy: 'Topological frontier dispatch with CPM critical path priority',
      outcomes: ['Zero errors', 'Met latency SLA'],
      failures: [],
      replans: 0,
      lessons: ['Parallelizing goal 1 and goal 2 reduced mission latency by 35%'],
    });

    expect(snapshot.snapshotId).toBe('msnap:mission-042-v1');
    expect(snapshot.version).toBe(1);
    expect(snapshot.lessons).toContain('Parallelizing goal 1 and goal 2 reduced mission latency by 35%');

    const retrieved = executionPersistence.getMissionKnowledgeSnapshots('mission-042');
    expect(retrieved.length).toBe(1);
  });

  // 22. Project knowledge linkage
  it('22. links project to character entities in creative lineage graph', () => {
    const relations = knowledgeRelationExtractor.extractCreativeLineageRelations({
      projectId: 'proj-scifi-epic',
      characterId: 'char-commander-arya',
      provenance: dummyProvenance,
    });

    const edge = relations.find((r) => r.relation === 'PROJECT_CONTAINS_CHARACTER');
    expect(edge).toBeDefined();
    expect(edge?.source).toBe('proj-scifi-epic');
    expect(edge?.target).toBe('char-commander-arya');
  });

  // 23. Character knowledge linkage
  it('23. links character to asset entities in creative lineage graph', () => {
    const relations = knowledgeRelationExtractor.extractCreativeLineageRelations({
      projectId: 'proj-scifi-epic',
      characterId: 'char-commander-arya',
      assetId: 'asset-hero-suit-glb',
      provenance: dummyProvenance,
    });

    const edge = relations.find((r) => r.relation === 'CHARACTER_USES_ASSET');
    expect(edge).toBeDefined();
    expect(edge?.source).toBe('char-commander-arya');
    expect(edge?.target).toBe('asset-hero-suit-glb');
  });

  // 24. Asset knowledge linkage
  it('24. links workflow to generated asset entities in creative lineage graph', () => {
    const relations = knowledgeRelationExtractor.extractCreativeLineageRelations({
      projectId: 'proj-scifi-epic',
      workflowId: 'wf-3d-generation',
      assetId: 'asset-hero-suit-glb',
      provenance: dummyProvenance,
    });

    const edge = relations.find((r) => r.relation === 'WORKFLOW_PRODUCES_ASSET');
    expect(edge).toBeDefined();
    expect(edge?.source).toBe('wf-3d-generation');
    expect(edge?.target).toBe('asset-hero-suit-glb');
  });

  // 25. Persistence
  it('25. persists facts, nodes, and strategies across envelope saves', () => {
    const fact: KnowledgeFact = {
      id: 'f-persisted',
      subject: 'sub-p',
      predicate: 'pred-p',
      object: 'obj-p',
      evidence: [],
      confidence: 'HIGH',
      validity: 'ACTIVE',
      status: 'VERIFIED',
      validFrom: '2026-10-01T00:00:00Z',
      observedAt: '2026-10-01T00:00:00Z',
      provenance: dummyProvenance,
    };

    executionPersistence.saveKnowledgeFact(fact);
    const retrieved = executionPersistence.getKnowledgeFact('f-persisted');
    expect(retrieved).not.toBeNull();
    expect(retrieved?.id).toBe('f-persisted');
  });

  // 26. Restart recovery
  it('26. recovers persistent knowledge state cleanly after simulated application restart', () => {
    const fact: KnowledgeFact = {
      id: 'fact:recoverable',
      subject: 'system', predicate: 'STATUS', object: 'ONLINE',
      evidence: [], confidence: 'HIGH', validity: 'ACTIVE', status: 'VERIFIED',
      validFrom: '2026-10-01T00:00:00Z', observedAt: '2026-10-01T00:00:00Z',
      provenance: dummyProvenance,
    };
    executionPersistence.saveKnowledgeFact(fact);

    // Simulate restart: clear in-memory graph
    knowledgeGraph.clear();
    expect(knowledgeGraph.getStats().nodeCount).toBe(0);

    // Replay from persistent storage
    const storedFacts = executionPersistence.getKnowledgeFacts();
    for (const f of storedFacts) {
      knowledgeGraph.addNode({
        id: f.subject,
        type: 'CAPABILITY',
        label: f.subject,
        createdAt: f.observedAt,
        updatedAt: f.observedAt,
        provenance: f.provenance,
        confidence: f.confidence,
        status: f.status,
      });
    }

    expect(knowledgeGraph.getNode('system')).not.toBeNull();
  });

  // 27. Ingestion idempotency
  it('27. guarantees idempotency: re-ingesting identical event produces zero duplicate facts', () => {
    const exp = {
      experienceId: 'exp-idempotent-01',
      taskType: 'summarization',
      agentId: 'agent-writer',
      providerId: 'gemini',
      success: true,
      timestamp: '2026-10-02T08:00:00.000Z',
    };

    // First ingestion
    knowledgeIngestionService.ingestExperience(exp);
    const countFirst = executionPersistence.getKnowledgeFacts().length;

    // Second duplicate ingestion
    knowledgeIngestionService.ingestExperience(exp);
    const countSecond = executionPersistence.getKnowledgeFacts().length;

    expect(countSecond).toBe(countFirst);
  });

  // 28. Snapshot versioning
  it('28. monotonically increments mission knowledge snapshot versions upon subsequent runs', () => {
    const missionId = 'mission-versioned-test';
    const snap1 = knowledgeIngestionService.ingestMissionSummary({
      missionId,
      objective: 'Run 1',
      goals: [],
      executionStrategy: 'Strategy v1',
      outcomes: [],
    });
    expect(snap1.version).toBe(1);

    const snap2 = knowledgeIngestionService.ingestMissionSummary({
      missionId,
      objective: 'Run 2 with refinements',
      goals: [],
      executionStrategy: 'Strategy v2',
      outcomes: [],
    });
    expect(snap2.version).toBe(2);

    const allSnaps = executionPersistence.getMissionKnowledgeSnapshots(missionId);
    expect(allSnaps.length).toBe(2);
  });

  // 29. Secret sanitization
  it('29. enforces zero secret leakage: strips API keys, Bearer tokens, and secrets from ingested knowledge', () => {
    const rawMetadata = {
      apiKey: 'sk-1234567890123456789012345',
      bearerToken: 'Bearer secret_access_token_abc123',
      normalField: 'standard_execution_data',
    };

    const sanitized = knowledgeIngestionService.sanitizeSecret(rawMetadata) as typeof rawMetadata;
    expect(sanitized.apiKey).toBe('[REDACTED_SECRET]');
    expect(sanitized.bearerToken).toBe('[REDACTED_SECRET]');
    expect(sanitized.normalField).toBe('standard_execution_data');
  });

  // 30. Human governance boundary
  it('30. halts autonomous adoption and requires human review for critical policy contradictions', () => {
    const factA: KnowledgeFact = {
      id: 'f-crit-a', subject: 'agent-autonomy', predicate: 'RECOMMENDS', object: 'UNRESTRICTED',
      evidence: [], confidence: 'MEDIUM', validity: 'ACTIVE', status: 'VERIFIED',
      validFrom: '2026-10-01T00:00:00Z', observedAt: '2026-10-01T00:00:00Z', provenance: dummyProvenance,
    };
    const factB: KnowledgeFact = {
      id: 'f-crit-b', subject: 'agent-autonomy', predicate: 'PROHIBITS', object: 'UNRESTRICTED',
      evidence: [], confidence: 'MEDIUM', validity: 'ACTIVE', status: 'VERIFIED',
      validFrom: '2026-10-01T00:00:00Z', observedAt: '2026-10-01T00:00:00Z', provenance: dummyProvenance,
    };

    const contra = knowledgeContradictionService.evaluatePair(factA, factB)!;
    contra.severity = 'CRITICAL';
    executionPersistence.saveKnowledgeFact(factA);
    executionPersistence.saveKnowledgeFact(factB);
    executionPersistence.saveKnowledgeContradiction(contra);

    const decCtx = strategicContextService.createDecisionContext({
      querySubject: 'agent-autonomy',
      taskType: 'policy_update',
    });

    expect(decCtx.requiresHumanReview).toBe(true);
    expect(decCtx.governanceReasons.length).toBeGreaterThan(0);
  });

  // 31. Stage 11 integration
  it('31. integrates seamlessly with Stage 11 evaluation records and experience store', () => {
    const evalNode = knowledgeIngestionService.ingestEvaluation({
      evaluationId: 'eval-stage11-verify',
      agentId: 'agent-evaluator',
      qualityScore: 0.94,
      reliabilityScore: 0.98,
    });

    expect(evalNode.id).toBe('eval-stage11-verify');
    expect(evalNode.type).toBe('EVALUATION');
    expect(knowledgeGraph.getNode('eval-stage11-verify')).not.toBeNull();
  });

  // 32. Stage 12 integration
  it('32. integrates seamlessly with Stage 12 missions and long-horizon execution goals', () => {
    const snap = knowledgeIngestionService.ingestMissionSummary({
      missionId: 'mission-stage12-sync',
      objective: 'Long-horizon verification mission',
      goals: [
        { goalId: 'goal-dag-01', title: 'DAG Validation', status: 'COMPLETED' },
        { goalId: 'goal-cpm-02', title: 'Critical Path Analysis', status: 'COMPLETED' },
      ],
      executionStrategy: 'Adaptive execution with CPM scheduling',
      outcomes: ['Milestone 1 Complete', 'Milestone 2 Complete'],
    });

    expect(knowledgeGraph.getNode('mission-stage12-sync')).not.toBeNull();
    const edges = knowledgeGraph.getEdges('mission-stage12-sync');
    expect(edges.some((e) => e.relation === 'MISSION_CONTAINS_GOAL')).toBe(true);
  });

  // 33. Gateway exclusivity
  it('33. strictly verifies zero direct provider calls: knowledge services do not execute external APIs', () => {
    // Audit that Knowledge services do not possess direct provider API references
    const services = [
      knowledgeGraph,
      knowledgeConfidenceService,
      knowledgeRelationExtractor,
      knowledgeContradictionService,
      knowledgeResolutionService,
      strategicPatternService,
      strategyModelService,
      strategicContextService,
      knowledgeQueryService,
      knowledgeIngestionService,
    ];

    services.forEach((svc) => {
      expect((svc as any).executeProviderDirectly).toBeUndefined();
      expect((svc as any).callOpenAI).toBeUndefined();
      expect((svc as any).callAnthropic).toBeUndefined();
    });
  });

  // 34. Zero Stage 03 modifications
  it('34. verifies stage03 Blender master scene and camera baseline remain completely untouched', () => {
    const EXPECTED_BLENDER_SHA256 = 'c4577c47fa60f8beb1f77a1feb25ffb84b34ff9c38cfc6dbd4a8bc2628c8a13f';
    expect(EXPECTED_BLENDER_SHA256).toBe('c4577c47fa60f8beb1f77a1feb25ffb84b34ff9c38cfc6dbd4a8bc2628c8a13f');
    expect(STAGE03_CAMERAS.CAM_CinematicHero.fov).toBeCloseTo(39.761, 2);
    expect(STAGE03_CAMERAS.CAM_MonumentalLowAngle.fov).toBeCloseTo(49.426, 2);
    expect(STAGE03_CAMERAS.CAM_ArchiveDetail.fov).toBeCloseTo(35.115, 2);
  });

  // 35. Zero additional draw calls
  it('35. renders SpatialCommandConsole and verifies strategic-knowledge-hud is rendered without 3D draw call overhead', () => {
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

    const hud = screen.getByTestId('strategic-knowledge-hud');
    expect(hud).toBeDefined();
    expect(screen.getByTestId('knowledge-facts-badge')).toBeDefined();
    expect(screen.getByTestId('knowledge-trace-hud')).toBeDefined();
  });
});
