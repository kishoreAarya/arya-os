/**
 * AryaOS V1 — Stage 14: Central Decision Intelligence Service
 *
 * Primary coordinator and façade for Decision Intelligence:
 * CONTEXT → DIVERSE OPTIONS → SCENARIO SIMULATION → PRE-MORTEM →
 * SENSITIVITY → TRADEOFF ANALYSIS → ADVISORY RECOMMENDATION →
 * HUMAN REVIEW → GOVERNED EXECUTION → POST-DECISION LEARNING.
 *
 * Immutable Versioning:
 * Decisions are immutable once approved. Changes create Decision v2 linking previousDecisionId.
 *
 * Single Execution Boundary:
 * All actions execute strictly through the existing Stage 07 Execution Gateway.
 */

import {
  Decision,
  DecisionStatus,
  DecisionPriority,
  DecisionContext,
  DecisionOption,
  DecisionRecommendation,
  DecisionApproval,
  DecisionProvenance,
  DecisionEvidence,
  DecisionConstraint,
  DecisionObjective,
  RiskAssessment,
} from '../types/decisionIntelligence';
import { decisionContextService } from './decisionContextService';
import { decisionOptionGenerator } from './decisionOptionGenerator';
import { scenarioEngine } from './scenarioEngine';
import { decisionSensitivityService } from './decisionSensitivityService';
import { premortemService } from './premortemService';
import { decisionRecommendationService } from './decisionRecommendationService';
import { decisionExplanationService } from './decisionExplanationService';
import { decisionEvaluationService } from './decisionEvaluationService';
import { executionPersistence } from './executionPersistence';
import { knowledgeGraph } from './knowledgeGraph';

export interface CreateDecisionWorkflowInput {
  decisionId?: string;
  title: string;
  description?: string;
  missionId?: string;
  goalId?: string;
  objective: string;
  currentState: string;
  priority?: DecisionPriority;
  constraints?: DecisionConstraint[];
  objectives?: DecisionObjective[];
  budget?: number | 'UNKNOWN';
  deadline?: string;
  customOptions?: Array<Partial<DecisionOption>>;
}

export class DecisionIntelligenceService {
  /**
   * Runs the full formal decision workflow and returns a Decision awaiting review.
   */
  public createDecisionWorkflow(input: CreateDecisionWorkflowInput): Decision {
    const decisionId = input.decisionId || `dec_${Date.now()}_${Math.random().toString(36).slice(2, 7)}`;
    const priority = input.priority || 'HIGH';

    // 1. Decision Context Construction
    const context = decisionContextService.buildContext({
      missionId: input.missionId,
      goalId: input.goalId,
      objective: input.objective,
      currentState: input.currentState,
      constraints: input.constraints,
      objectives: input.objectives,
      budget: input.budget,
      deadline: input.deadline,
    });

    // 2. Materially Diverse Option Generation
    const rawOptions = decisionOptionGenerator.generateOptions({
      context,
      customOptions: input.customOptions,
    });

    // 3. Scenario Engine Simulation for Each Option
    const optionsWithScenarios: DecisionOption[] = rawOptions.map((opt) => {
      const scenarios = scenarioEngine.generateScenarios(opt, context);
      return {
        ...opt,
        scenarios,
      };
    });

    // 4. Sensitivity Analysis
    const sensitivity = decisionSensitivityService.analyzeSensitivity(
      optionsWithScenarios,
      context
    );

    // 5. Pre-Mortem Analysis on Primary Option
    const primaryOption = optionsWithScenarios[0];
    const premortem = premortemService.conductPreMortem(primaryOption, context);

    // 6. Advisory Recommendation Generation (Strictly AWAITING_REVIEW)
    const recommendation = decisionRecommendationService.generateRecommendation(
      decisionId,
      optionsWithScenarios,
      context
    );

    // 7. Decision Explanation (FACT vs INFERENCE vs PROJECTION)
    const explanation = decisionExplanationService.explainRecommendation(
      recommendation,
      optionsWithScenarios,
      context
    );

    // 8. Decision Provenance Graph Lineage
    const provenance: DecisionProvenance = {
      decisionId,
      recommendationId: recommendation.recommendationId,
      optionId: recommendation.recommendedOptionId,
      scenarioIds: (primaryOption.scenarios || []).map((s) => s.id),
      evidenceIds: recommendation.supportingEvidence.map((e) => e.id),
      knowledgeNodeIds: context.relevantKnowledge.map((k) => k.id),
      experienceIds: context.relevantExperiences.map((e) => e.id),
      missionId: input.missionId,
      goalId: input.goalId,
      timestamp: new Date().toISOString(),
    };

    // Initial Approval State (Requires operator review)
    const consequentialFlags = decisionRecommendationService.detectConsequentialFlags(primaryOption);
    const approval: DecisionApproval = {
      approvalId: `appr_${decisionId}`,
      status: 'AWAITING_REVIEW',
      requiresHumanApproval: consequentialFlags.length > 0 || primaryOption.reversibility === 'IRREVERSIBLE',
      consequentialFlags,
    };

    const decision: Decision = {
      id: decisionId,
      version: 1,
      title: input.title,
      description: input.description || `Decision workflow for objective: ${input.objective}`,
      status: 'AWAITING_REVIEW' as DecisionStatus,
      priority,
      context,
      options: optionsWithScenarios,
      recommendation,
      approval,
      provenance,
      sensitivity,
      explanation,
      premortem,
      createdAt: new Date().toISOString(),
      updatedAt: new Date().toISOString(),
    };

    // Persist Decision and register in Knowledge Graph
    executionPersistence.saveDecision(decision);
    this.registerDecisionInKnowledgeGraph(decision);

    return decision;
  }

  /**
   * Registers a decision node and lineage edges in Stage 13 Strategic Knowledge Graph.
   */
  private registerDecisionInKnowledgeGraph(decision: Decision): void {
    try {
      knowledgeGraph.addNode({
        id: decision.id,
        type: 'DECISION',
        label: `Decision: ${decision.title}`,
        confidence: 'HIGH',
        status: 'VERIFIED',
        createdAt: decision.createdAt,
        updatedAt: decision.updatedAt,
        provenance: {
          source: {
            sourceType: 'STAGE11_DECISION',
            sourceId: 'decisionIntelligenceService',
            timestamp: decision.createdAt,
          },
          extractedAt: decision.createdAt,
          derivedBy: 'decisionIntelligenceService',
          confidenceScore: 1.0,
        },
        metadata: {
          status: decision.status,
          priority: decision.priority,
          objective: decision.context.objective,
          recommendedOptionId: decision.recommendation?.recommendedOptionId,
        },
      });

      if (decision.provenance.missionId) {
        knowledgeGraph.addEdge({
          id: `edge_m_dec_${decision.id}`,
          source: decision.provenance.missionId,
          target: decision.id,
          relation: 'RELATES_TO',
          confidence: 'HIGH',
          weight: 1.0,
          createdAt: decision.createdAt,
          provenance: {
            source: {
              sourceType: 'STAGE11_DECISION',
              sourceId: 'decisionIntelligenceService',
              timestamp: decision.createdAt,
            },
            extractedAt: decision.createdAt,
            derivedBy: 'decisionIntelligenceService',
          },
        });
      }
    } catch {
      // Graceful fallback if node already exists
    }
  }

  /**
   * Applies Human Operator Approval to a Decision.
   * Strictly prohibits autonomous approval.
   */
  public approveDecision(
    decisionId: string,
    operatorId: string,
    comments?: string
  ): Decision {
    const decision = executionPersistence.getDecision(decisionId);
    if (!decision) {
      throw new Error(`Decision not found: ${decisionId}`);
    }

    if (!operatorId || operatorId === 'SYSTEM' || operatorId === 'AUTONOMOUS_AGENT') {
      throw new Error(
        'Autonomous approval prohibited: Consequential decisions strictly require human operator authorization.'
      );
    }

    if (!decision.recommendation) {
      throw new Error(`Decision ${decisionId} has no recommendation to approve.`);
    }

    const approval = decisionRecommendationService.approveByOperator(
      decision.recommendation,
      operatorId,
      comments
    );

    decision.approval = approval;
    decision.status = 'APPROVED';
    decision.updatedAt = new Date().toISOString();

    executionPersistence.saveDecision(decision);

    // Evaluate decision process thoroughness
    decisionEvaluationService.evaluateDecisionProcess(decision);

    return decision;
  }

  /**
   * Rejects a decision with documented operator reason.
   */
  public rejectDecision(
    decisionId: string,
    operatorId: string,
    rejectionReason: string
  ): Decision {
    const decision = executionPersistence.getDecision(decisionId);
    if (!decision) {
      throw new Error(`Decision not found: ${decisionId}`);
    }

    decision.approval = {
      approvalId: `appr_rej_${decisionId}`,
      status: 'REJECTED',
      approvedBy: operatorId,
      reviewedAt: new Date().toISOString(),
      comments: rejectionReason,
      requiresHumanApproval: true,
      consequentialFlags: decision.approval.consequentialFlags,
    };
    decision.status = 'REJECTED';
    decision.updatedAt = new Date().toISOString();

    executionPersistence.saveDecision(decision);
    return decision;
  }

  /**
   * Creates an immutable Decision v2 when operational circumstances change.
   * Does NOT mutate Decision v1.
   */
  public createDecisionVersion2(params: {
    previousDecisionId: string;
    changeReason: string;
    newEvidence?: DecisionEvidence[];
    changedConstraints?: DecisionConstraint[];
    changedRisks?: RiskAssessment[];
  }): Decision {
    const prev = executionPersistence.getDecision(params.previousDecisionId);
    if (!prev) {
      throw new Error(`Previous decision not found: ${params.previousDecisionId}`);
    }

    // Mark previous decision as SUPERSEDED
    prev.status = 'SUPERSEDED';
    prev.updatedAt = new Date().toISOString();
    executionPersistence.saveDecision(prev);

    // Build new decision v2
    const v2Id = `${prev.id}_v${prev.version + 1}`;
    const v2Constraints = params.changedConstraints || prev.context.constraints;

    const v2 = this.createDecisionWorkflow({
      decisionId: v2Id,
      title: `${prev.title} (v${prev.version + 1})`,
      description: `Version ${prev.version + 1} superseding ${prev.id}. Reason: ${params.changeReason}`,
      missionId: prev.provenance.missionId,
      goalId: prev.provenance.goalId,
      objective: prev.context.objective,
      currentState: prev.context.currentState,
      priority: prev.priority,
      constraints: v2Constraints,
      objectives: prev.context.objectives,
      budget: prev.context.budget,
      deadline: prev.context.deadline,
    });

    v2.version = prev.version + 1;
    v2.previousDecisionId = prev.id;
    v2.changeReason = params.changeReason;
    v2.newEvidence = params.newEvidence || [];
    v2.changedConstraints = params.changedConstraints;
    v2.changedRisks = params.changedRisks;

    executionPersistence.saveDecision(v2);
    return v2;
  }
}

export const decisionIntelligenceService = new DecisionIntelligenceService();
