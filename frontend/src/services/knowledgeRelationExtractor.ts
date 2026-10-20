/**
 * AryaOS V1 — Stage 13: Knowledge Relation Extractor
 *
 * Deterministic relation extraction across multi-domain runtime records:
 * Missions, Goals, Actions, Agents, Providers, Artifacts, Memories, Experiences,
 * Evaluations, and Decisions.
 *
 * Every extracted relation preserves full provenance and confidence metrics.
 */

import {
  KnowledgeEdge,
  KnowledgeProvenance,
  KnowledgeConfidence,
} from '../types/strategicKnowledge';

export class KnowledgeRelationExtractor {
  /**
   * Deterministically constructs an edge with full provenance and canonical ID.
   */
  public createRelation(params: {
    source: string;
    target: string;
    relation: string;
    provenance: KnowledgeProvenance;
    confidence?: KnowledgeConfidence;
    weight?: number;
    metadata?: Record<string, unknown>;
  }): KnowledgeEdge {
    const {
      source,
      target,
      relation,
      provenance,
      confidence = 'HIGH',
      weight = 1.0,
      metadata = {},
    } = params;

    const id = `edge:${source}--${relation}-->${target}`;

    return {
      id,
      source,
      target,
      relation,
      provenance,
      confidence,
      createdAt: new Date().toISOString(),
      weight,
      metadata,
    };
  }

  /**
   * Extracts relations between a Mission and its child Goals.
   */
  public extractMissionGoalRelations(
    missionId: string,
    goalIds: string[],
    provenance: KnowledgeProvenance
  ): KnowledgeEdge[] {
    return goalIds.map((goalId) =>
      this.createRelation({
        source: missionId,
        target: goalId,
        relation: 'MISSION_CONTAINS_GOAL',
        provenance,
        confidence: 'HIGH',
      })
    );
  }

  /**
   * Extracts dependency edges between Goals: (prerequisite -> dependent)
   */
  public extractGoalDependencyRelations(
    goalId: string,
    prerequisiteGoalIds: string[],
    provenance: KnowledgeProvenance
  ): KnowledgeEdge[] {
    return prerequisiteGoalIds.map((prereqId) =>
      this.createRelation({
        source: prereqId,
        target: goalId,
        relation: 'GOAL_DEPENDS_ON_GOAL',
        provenance,
        confidence: 'HIGH',
      })
    );
  }

  /**
   * Extracts relation between Goal and the executing Agent.
   */
  public extractGoalAgentRelation(
    goalId: string,
    agentId: string,
    provenance: KnowledgeProvenance
  ): KnowledgeEdge {
    return this.createRelation({
      source: goalId,
      target: agentId,
      relation: 'GOAL_USED_AGENT',
      provenance,
      confidence: 'HIGH',
    });
  }

  /**
   * Extracts relation between Agent and underlying Provider.
   */
  public extractAgentProviderRelation(
    agentId: string,
    providerId: string,
    provenance: KnowledgeProvenance
  ): KnowledgeEdge {
    return this.createRelation({
      source: agentId,
      target: providerId,
      relation: 'AGENT_USED_PROVIDER',
      provenance,
      confidence: 'HIGH',
    });
  }

  /**
   * Extracts relation between Action/Execution and generated Artifact.
   */
  public extractExecutionArtifactRelation(
    executionId: string,
    artifactId: string,
    provenance: KnowledgeProvenance
  ): KnowledgeEdge {
    return this.createRelation({
      source: executionId,
      target: artifactId,
      relation: 'EXECUTION_PRODUCED_ARTIFACT',
      provenance,
      confidence: 'HIGH',
    });
  }

  /**
   * Extracts relation between Execution and generated Experience.
   */
  public extractExecutionExperienceRelation(
    executionId: string,
    experienceId: string,
    provenance: KnowledgeProvenance
  ): KnowledgeEdge {
    return this.createRelation({
      source: executionId,
      target: experienceId,
      relation: 'EXECUTION_GENERATED_EXPERIENCE',
      provenance,
      confidence: 'HIGH',
    });
  }

  /**
   * Extracts relation linking Experience to a Fact it supports.
   */
  public extractExperienceFactRelation(
    experienceId: string,
    factId: string,
    provenance: KnowledgeProvenance
  ): KnowledgeEdge {
    return this.createRelation({
      source: experienceId,
      target: factId,
      relation: 'EXPERIENCE_SUPPORTS_FACT',
      provenance,
      confidence: 'HIGH',
    });
  }

  /**
   * Extracts relation linking Fact to a Strategy it supports.
   */
  public extractFactStrategyRelation(
    factId: string,
    strategyId: string,
    provenance: KnowledgeProvenance
  ): KnowledgeEdge {
    return this.createRelation({
      source: factId,
      target: strategyId,
      relation: 'FACT_SUPPORTS_STRATEGY',
      provenance,
      confidence: 'HIGH',
    });
  }

  /**
   * Extracts contradiction edge between two conflicting facts.
   */
  public extractFactContradictionRelation(
    factAId: string,
    factBId: string,
    provenance: KnowledgeProvenance
  ): KnowledgeEdge {
    return this.createRelation({
      source: factAId,
      target: factBId,
      relation: 'FACT_CONTRADICTS_FACT',
      provenance,
      confidence: 'HIGH',
      metadata: { bidirectional: true },
    });
  }

  /**
   * Extracts relation linking Decision to affected Mission.
   */
  public extractDecisionMissionRelation(
    decisionId: string,
    missionId: string,
    provenance: KnowledgeProvenance
  ): KnowledgeEdge {
    return this.createRelation({
      source: decisionId,
      target: missionId,
      relation: 'DECISION_AFFECTED_MISSION',
      provenance,
      confidence: 'HIGH',
    });
  }

  /**
   * Extracts relation linking Risk to affected Goal.
   */
  public extractRiskGoalRelation(
    riskId: string,
    goalId: string,
    provenance: KnowledgeProvenance
  ): KnowledgeEdge {
    return this.createRelation({
      source: riskId,
      target: goalId,
      relation: 'RISK_AFFECTED_GOAL',
      provenance,
      confidence: 'HIGH',
    });
  }

  /**
   * Extracts relation linking Learning Signal to supported Fact.
   */
  public extractLearningSignalFactRelation(
    signalId: string,
    factId: string,
    provenance: KnowledgeProvenance
  ): KnowledgeEdge {
    return this.createRelation({
      source: signalId,
      target: factId,
      relation: 'LEARNING_SIGNAL_SUPPORTS_FACT',
      provenance,
      confidence: 'HIGH',
    });
  }

  /**
   * Extracts relation linking Spatial Memory to Mission.
   */
  public extractMemoryMissionRelation(
    memoryId: string,
    missionId: string,
    provenance: KnowledgeProvenance
  ): KnowledgeEdge {
    return this.createRelation({
      source: memoryId,
      target: missionId,
      relation: 'MEMORY_REFERENCES_MISSION',
      provenance,
      confidence: 'HIGH',
    });
  }

  /**
   * Creative domain hierarchy: PROJECT -> CHARACTER -> ASSET -> WORKFLOW
   */
  public extractCreativeLineageRelations(params: {
    projectId: string;
    characterId?: string;
    assetId?: string;
    workflowId?: string;
    provenance: KnowledgeProvenance;
  }): KnowledgeEdge[] {
    const edges: KnowledgeEdge[] = [];
    const { projectId, characterId, assetId, workflowId, provenance } = params;

    if (characterId) {
      edges.push(
        this.createRelation({
          source: projectId,
          target: characterId,
          relation: 'PROJECT_CONTAINS_CHARACTER',
          provenance,
          confidence: 'HIGH',
        })
      );
    }

    if (characterId && assetId) {
      edges.push(
        this.createRelation({
          source: characterId,
          target: assetId,
          relation: 'CHARACTER_USES_ASSET',
          provenance,
          confidence: 'HIGH',
        })
      );
    }

    if (workflowId && assetId) {
      edges.push(
        this.createRelation({
          source: workflowId,
          target: assetId,
          relation: 'WORKFLOW_PRODUCES_ASSET',
          provenance,
          confidence: 'HIGH',
        })
      );
    }

    return edges;
  }
}

export const knowledgeRelationExtractor = new KnowledgeRelationExtractor();
