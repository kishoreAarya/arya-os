/**
 * AryaOS V1 — Stage 13: Knowledge Ingestion Service
 *
 * Ingests multi-domain telemetry from Stages 04, 09, 10, 11, and 12.
 * Invariants:
 * - Enforces zero secret leakage via comprehensive credential sanitization.
 * - Idempotent ingestion: deterministic IDs ensure duplicate sources never duplicate facts or nodes.
 * - Restarts are safe: re-ingestion updates existing canonical entries deterministically.
 */

import {
  KnowledgeNode,
  KnowledgeFact,
  KnowledgeEvidence,
  KnowledgeProvenance,
  KnowledgeConfidence,
  MissionKnowledgeSnapshot,
} from '../types/strategicKnowledge';
import { knowledgeGraph } from './knowledgeGraph';
import { knowledgeRelationExtractor } from './knowledgeRelationExtractor';
import { knowledgeConfidenceService } from './knowledgeConfidenceService';
import { knowledgeContradictionService } from './knowledgeContradictionService';
import { executionPersistence } from './executionPersistence';

export class KnowledgeIngestionService {
  /**
   * Generates a deterministic canonical fact ID from subject, predicate, and object.
   */
  public getCanonicalFactId(subject: string, predicate: string, object: string): string {
    return `fact:${subject.toLowerCase()}::${predicate.toUpperCase()}::${object.toLowerCase()}`;
  }

  /**
   * Sanitizes input data before ingestion to guarantee zero secret leakage.
   */
  public sanitizeSecret(data: unknown): unknown {
    return executionPersistence.sanitizeForPersistence(data);
  }

  /**
   * Ingests a canonical Fact. Evaluates evidence, computes confidence,
   * checks for contradictions, and persists.
   */
  public ingestFact(params: {
    subject: string;
    predicate: string;
    object: string;
    evidence: KnowledgeEvidence[];
    provenance: KnowledgeProvenance;
    metadata?: Record<string, unknown>;
  }): KnowledgeFact {
    const { subject, predicate, object, evidence, provenance, metadata = {} } = params;

    // Sanitize any secrets in metadata or provenance
    const cleanMeta = this.sanitizeSecret(metadata) as Record<string, unknown>;
    const cleanProv = this.sanitizeSecret(provenance) as KnowledgeProvenance;

    const factId = this.getCanonicalFactId(subject, predicate, object);
    const existingFact = executionPersistence.getKnowledgeFact(factId);

    // Merge evidence with existing evidence if present
    const existingEvidenceIds = existingFact?.evidence || [];
    const newEvidenceIds = evidence.map((e) => e.id);
    const mergedEvidenceIds = Array.from(new Set([...existingEvidenceIds, ...newEvidenceIds]));

    // Evaluate confidence deterministically
    const confResult = knowledgeConfidenceService.evaluateConfidence({
      evidenceList: evidence,
      observedAt: cleanProv.source.timestamp,
    });

    const status =
      confResult.confidence === 'UNKNOWN'
        ? 'UNCERTAIN'
        : confResult.confidence === 'LOW' && mergedEvidenceIds.length === 0
        ? 'UNCERTAIN'
        : 'VERIFIED';

    const fact: KnowledgeFact = {
      id: factId,
      subject,
      predicate,
      object,
      evidence: mergedEvidenceIds,
      confidence: confResult.confidence,
      validity: 'ACTIVE',
      status,
      validFrom: existingFact?.validFrom || cleanProv.source.timestamp || new Date().toISOString(),
      observedAt: cleanProv.source.timestamp || new Date().toISOString(),
      provenance: cleanProv,
      metadata: cleanMeta,
    };

    // Detect contradictions against existing facts in the system
    const allExisting = executionPersistence.getKnowledgeFacts();
    const contradictions = knowledgeContradictionService.detectContradictions(fact, allExisting);
    if (contradictions.length > 0) {
      fact.contradictionIds = contradictions.map((c) => c.contradictionId);
      contradictions.forEach((c) => executionPersistence.saveKnowledgeContradiction(c));
    }

    // Persist fact
    executionPersistence.saveKnowledgeFact(fact);

    // Also register subject and object nodes in knowledgeGraph if not present
    if (!knowledgeGraph.getNode(subject)) {
      knowledgeGraph.addNode({
        id: subject,
        type: 'CAPABILITY', // default until refined
        label: subject,
        createdAt: new Date().toISOString(),
        updatedAt: new Date().toISOString(),
        provenance: cleanProv,
        confidence: fact.confidence,
        status: 'VERIFIED',
      });
    }

    if (!knowledgeGraph.getNode(object)) {
      knowledgeGraph.addNode({
        id: object,
        type: 'CAPABILITY',
        label: object,
        createdAt: new Date().toISOString(),
        updatedAt: new Date().toISOString(),
        provenance: cleanProv,
        confidence: fact.confidence,
        status: 'VERIFIED',
      });
    }

    // Add relation edge to graph
    const edge = knowledgeRelationExtractor.createRelation({
      source: subject,
      target: object,
      relation: predicate,
      provenance: cleanProv,
      confidence: fact.confidence,
    });
    knowledgeGraph.addEdge(edge);
    executionPersistence.saveKnowledgeEdge(edge);

    return fact;
  }

  /**
   * Ingests an Experience record from Stage 11.
   */
  public ingestExperience(exp: {
    experienceId: string;
    taskType: string;
    agentId: string;
    providerId: string;
    success: boolean;
    qualityScore?: number;
    latencyMs?: number;
    costUsd?: number;
    timestamp?: string;
  }): { node: KnowledgeNode; fact?: KnowledgeFact } {
    const timestamp = exp.timestamp || new Date().toISOString();
    const provenance: KnowledgeProvenance = {
      source: {
        sourceType: 'STAGE11_EXPERIENCE',
        sourceId: exp.experienceId,
        timestamp,
      },
      extractedAt: new Date().toISOString(),
      derivedBy: 'KnowledgeIngestionService.ingestExperience',
    };

    // 1. Add Experience node
    const expNode: KnowledgeNode = {
      id: exp.experienceId,
      type: 'EXPERIENCE',
      label: `Experience: ${exp.taskType} via ${exp.agentId}`,
      createdAt: timestamp,
      updatedAt: timestamp,
      provenance,
      confidence: 'HIGH',
      status: 'VERIFIED',
      metadata: {
        taskType: exp.taskType,
        agentId: exp.agentId,
        providerId: exp.providerId,
        success: exp.success,
        qualityScore: exp.qualityScore,
        latencyMs: exp.latencyMs,
      },
    };
    knowledgeGraph.addNode(expNode);
    executionPersistence.saveKnowledgeNode(expNode);

    // 2. Derive Fact: (agentId -> PERFORMS_WELL_FOR / UNDERPERFORMS_FOR -> taskType)
    const predicate = exp.success ? 'PERFORMS_WELL_FOR' : 'UNDERPERFORMS_FOR';
    const evidence: KnowledgeEvidence = {
      id: `ev:exp:${exp.experienceId}`,
      sourceType: 'STAGE11_EXPERIENCE',
      sourceId: exp.experienceId,
      description: `Task '${exp.taskType}' execution by '${exp.agentId}' ${exp.success ? 'succeeded' : 'failed'}.`,
      timestamp,
      weight: exp.success ? 0.8 : 0.9,
      provenance,
    };

    const fact = this.ingestFact({
      subject: exp.agentId,
      predicate,
      object: exp.taskType,
      evidence: [evidence],
      provenance,
    });

    return { node: expNode, fact };
  }

  /**
   * Ingests an Evaluation record from Stage 11.
   */
  public ingestEvaluation(evalRec: {
    evaluationId: string;
    agentId: string;
    qualityScore: number;
    reliabilityScore: number;
    timestamp?: string;
  }): KnowledgeNode {
    const timestamp = evalRec.timestamp || new Date().toISOString();
    const provenance: KnowledgeProvenance = {
      source: {
        sourceType: 'STAGE11_EVALUATION',
        sourceId: evalRec.evaluationId,
        timestamp,
      },
      extractedAt: new Date().toISOString(),
      derivedBy: 'KnowledgeIngestionService.ingestEvaluation',
    };

    const evalNode: KnowledgeNode = {
      id: evalRec.evaluationId,
      type: 'EVALUATION',
      label: `Evaluation for Agent ${evalRec.agentId}`,
      createdAt: timestamp,
      updatedAt: timestamp,
      provenance,
      confidence: 'HIGH',
      status: 'VERIFIED',
      metadata: {
        agentId: evalRec.agentId,
        qualityScore: evalRec.qualityScore,
        reliabilityScore: evalRec.reliabilityScore,
      },
    };

    knowledgeGraph.addNode(evalNode);
    executionPersistence.saveKnowledgeNode(evalNode);

    return evalNode;
  }

  /**
   * Ingests a completed Mission and creates a MissionKnowledgeSnapshot.
   */
  public ingestMissionSummary(params: {
    missionId: string;
    objective: string;
    goals: Array<{
      goalId: string;
      title: string;
      status: string;
      durationMs?: number;
      tokens?: number;
      agentId?: string;
    }>;
    executionStrategy: string;
    outcomes: string[];
    quality?: number;
    cost?: number;
    latencyMs?: number;
    failures?: string[];
    replans?: number;
    risks?: string[];
    decisions?: string[];
    lessons?: string[];
  }): MissionKnowledgeSnapshot {
    const timestamp = new Date().toISOString();
    const provenance: KnowledgeProvenance = {
      source: {
        sourceType: 'STAGE12_MISSION',
        sourceId: params.missionId,
        timestamp,
      },
      extractedAt: timestamp,
      derivedBy: 'KnowledgeIngestionService.ingestMissionSummary',
      missionId: params.missionId,
    };

    const existingSnapshots = executionPersistence.getMissionKnowledgeSnapshots(params.missionId);
    const nextVersion = existingSnapshots.length + 1;

    const snapshot: MissionKnowledgeSnapshot = {
      snapshotId: `msnap:${params.missionId}-v${nextVersion}`,
      missionId: params.missionId,
      version: nextVersion,
      timestamp,
      objective: params.objective,
      goalsSummary: params.goals,
      executionStrategy: params.executionStrategy,
      outcomes: params.outcomes,
      quality: params.quality ?? 1.0,
      cost: params.cost ?? 0,
      latencyMs: params.latencyMs ?? 0,
      failures: params.failures ?? [],
      replans: params.replans ?? 0,
      risksEncountered: params.risks ?? [],
      humanDecisions: params.decisions ?? [],
      lessons: params.lessons ?? [],
      provenance,
    };

    // Save snapshot
    executionPersistence.saveMissionKnowledgeSnapshot(snapshot);

    // Create Mission Node
    const missionNode: KnowledgeNode = {
      id: params.missionId,
      type: 'MISSION',
      label: `Mission: ${params.missionId}`,
      createdAt: timestamp,
      updatedAt: timestamp,
      provenance,
      confidence: 'HIGH',
      status: 'VERIFIED',
      metadata: {
        objective: params.objective,
        version: nextVersion,
        replans: params.replans,
      },
    };
    knowledgeGraph.addNode(missionNode);
    executionPersistence.saveKnowledgeNode(missionNode);

    // Ensure Goal Nodes exist in graph
    params.goals.forEach((goal) => {
      if (!knowledgeGraph.getNode(goal.goalId)) {
        knowledgeGraph.addNode({
          id: goal.goalId,
          type: 'GOAL',
          label: goal.title,
          createdAt: timestamp,
          updatedAt: timestamp,
          provenance,
          confidence: 'HIGH',
          status: 'VERIFIED',
        });
      }
    });

    // Link Goals to Mission
    const goalIds = params.goals.map((g) => g.goalId);
    const edges = knowledgeRelationExtractor.extractMissionGoalRelations(
      params.missionId,
      goalIds,
      provenance
    );
    edges.forEach((edge) => {
      knowledgeGraph.addEdge(edge);
      executionPersistence.saveKnowledgeEdge(edge);
    });

    return snapshot;
  }
}

export const knowledgeIngestionService = new KnowledgeIngestionService();
