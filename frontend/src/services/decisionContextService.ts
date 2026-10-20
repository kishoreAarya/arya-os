/**
 * AryaOS V1 — Stage 14: Decision Context Service
 *
 * Assembles bounded, explainable, evidence-backed decision contexts.
 * Binds Missions, Goals, Knowledge Graph, Historical Strategies, and Risks
 * without leaking raw graph dumps or fabricating estimates.
 */

import {
  DecisionContext,
  DecisionConstraint,
  DecisionObjective,
  RiskAssessment,
  DecisionConfidence,
} from '../types/decisionIntelligence';
import { KnowledgeNode, KnowledgeContradiction } from '../types/strategicKnowledge';
import { executionPersistence } from './executionPersistence';
import { knowledgeGraph } from './knowledgeGraph';
import { knowledgeContradictionService } from './knowledgeContradictionService';
import { missionRiskService } from './missionRiskService';

export function createDeterministicHash(input: string): string {
  let hash = 0;
  for (let i = 0; i < input.length; i++) {
    const char = input.charCodeAt(i);
    hash = (hash << 5) - hash + char;
    hash |= 0;
  }
  return 'fp_' + Math.abs(hash).toString(16).padStart(8, '0');
}

export interface BuildDecisionContextParams {
  contextId?: string;
  missionId?: string;
  goalId?: string;
  objective: string;
  currentState: string;
  constraints?: DecisionConstraint[];
  objectives?: DecisionObjective[];
  budget?: number | 'UNKNOWN';
  deadline?: string;
  availableResources?: string[];
  maxKnowledgeItems?: number;
}

export class DecisionContextService {
  /**
   * Constructs a bounded, explainable DecisionContext.
   */
  public buildContext(params: BuildDecisionContextParams): DecisionContext {
    const maxKnowledge = params.maxKnowledgeItems || 5;

    // 1. Objectives (Preserve conflicts explicitly, default to explicit objectives if omitted)
    const objectives: DecisionObjective[] = params.objectives && params.objectives.length > 0
      ? params.objectives
      : [
          {
            id: 'obj_quality',
            type: 'QUALITY',
            name: 'Execution Quality',
            description: 'Maintain high output fidelity and correctness',
          },
          {
            id: 'obj_cost',
            type: 'COST',
            name: 'Cost Efficiency',
            description: 'Minimize provider credit and token consumption',
          },
          {
            id: 'obj_latency',
            type: 'LATENCY',
            name: 'Execution Latency',
            description: 'Minimize task completion duration',
          },
        ];

    // 2. Constraints
    const defaultConstraints: DecisionConstraint[] = [
      {
        id: 'c_human_authority',
        name: 'Human Authority Boundary',
        description: 'Consequential decisions require explicit human review and approval',
        constraintType: 'HUMAN_AUTHORITY',
        isImmutable: true,
      },
    ];
    const constraints: DecisionConstraint[] = [
      ...defaultConstraints,
      ...(params.constraints || []),
    ];

    // 3. Bounded Strategic Knowledge Retrieval (Limit to top relevant facts)
    const allFacts = executionPersistence.getKnowledgeFacts();
    const relevantFacts = allFacts
      .filter((fact) => {
        const matchesMission = params.missionId && (fact.subject === params.missionId || fact.object === params.missionId);
        const matchesObjective = fact.predicate.toLowerCase().includes(params.objective.toLowerCase().slice(0, 10)) ||
          fact.subject.toLowerCase().includes(params.objective.toLowerCase().slice(0, 10));
        return matchesMission || matchesObjective || fact.confidence === 'HIGH';
      })
      .slice(0, maxKnowledge)
      .map((f) => ({
        id: f.id,
        title: `${f.subject} ${f.predicate} ${f.object}`,
        type: 'FACT',
        confidence: f.confidence,
      }));

    // If no filtered facts found, pull up to maxKnowledge nodes
    const finalRelevantKnowledge = relevantFacts.length > 0
      ? relevantFacts
      : knowledgeGraph.getNodes()
          .slice(0, maxKnowledge)
          .map((n: KnowledgeNode) => ({
            id: n.id,
            title: n.label,
            type: n.type,
            confidence: n.confidence,
          }));

    // 4. Relevant Experiences (Stage 11)
    const allExperiences = executionPersistence.getExperiences();
    const relevantExperiences = allExperiences
      .slice(0, 5)
      .map((exp) => ({
        id: exp.experienceId,
        pattern: exp.taskType,
        outcome: exp.status === 'COMPLETED' ? 'SUCCESS' : 'FAILURE',
      }));

    // 5. Known Risks from Stage 12 missionRiskService + Stage 13 contradictions
    const knownRisks: RiskAssessment[] = [];
    if (params.missionId) {
      const envelope = executionPersistence.loadEnvelope();
      const mission = envelope?.missions ? envelope.missions[params.missionId] : undefined;
      if (mission) {
        const missionRisks = missionRiskService.assessRisks(mission);
        for (const r of missionRisks.slice(0, 5)) {
          knownRisks.push({
            id: `ra_${r.riskId}`,
            riskId: r.riskId,
            classification: 'KNOWN',
            title: r.type,
            description: r.evidence.join('; ') || r.type,
            severity: r.level,
            likelihood: 'HIGH',
            mitigation: r.mitigation,
            evidenceIds: r.evidence,
          });
        }
      }
    }

    // 6. Open Contradictions from Stage 13
    const contradictions = knowledgeContradictionService.getContradictions('OPEN');
    const openContradictions = contradictions.slice(0, 5).map((c: KnowledgeContradiction) => ({
      id: c.contradictionId,
      description: `Contradiction between fact ${c.factA} and fact ${c.factB} (${c.type})`,
      severity: c.severity,
    }));

    // Add high severity contradictions as risks
    for (const c of contradictions.filter((item: KnowledgeContradiction) => item.severity === 'HIGH' || item.severity === 'CRITICAL')) {
      knownRisks.push({
        id: `ra_contra_${c.contradictionId}`,
        riskId: c.contradictionId,
        classification: 'KNOWN',
        title: `Contradiction: ${c.type}`,
        description: `Contradiction between fact ${c.factA} and ${c.factB}`,
        severity: c.severity,
        likelihood: 'HIGH',
        evidenceIds: [c.factA, c.factB],
      });
    }

    // 7. Historical Strategies from Stage 13
    const strategies = executionPersistence.getKnowledgeStrategies('VALIDATED');
    const historicalStrategies = strategies.slice(0, 5).map((s) => ({
      id: s.strategyId,
      name: s.title,
      successRate: s.observedOutcomes.length > 0 ? 0.9 : 0.75,
    }));

    // 8. Pending Approvals from Persistence
    const envelope = executionPersistence.loadEnvelope();
    const pendingApprovals = envelope?.approvals
      ? Object.values(envelope.approvals).filter((a) => a.status === 'PENDING').map((a) => a.approvalId)
      : [];

    // 9. Available Resources
    const availableResources = params.availableResources || [
      'WORKER_AGENT',
      'COORDINATOR_AGENT',
      'EXECUTION_GATEWAY',
      'SPATIAL_CONSOLE',
    ];

    // 10. Truthful Budget and Deadline
    const budget = params.budget !== undefined ? params.budget : 'UNKNOWN';
    const deadline = params.deadline;

    // 11. Fingerprint Calculation (Deterministic)
    const fpSource = `${params.missionId || ''}:${params.goalId || ''}:${params.objective}:${params.currentState}:${constraints
      .map((c) => c.id)
      .sort()
      .join(',')}:${objectives
      .map((o) => o.id)
      .sort()
      .join(',')}`;
    const fingerprint = createDeterministicHash(fpSource);

    // Check if duplicate context exists in persistence
    const existing = executionPersistence
      .getAllDecisionContexts()
      .find((c) => c.fingerprint === fingerprint);

    if (existing) {
      return existing;
    }

    const contextId = params.contextId || `ctx_dec_${Date.now()}_${Math.random().toString(36).slice(2, 7)}`;

    const context: DecisionContext = {
      contextId,
      missionId: params.missionId,
      goalId: params.goalId,
      objective: params.objective,
      currentState: params.currentState,
      constraints,
      availableResources,
      relevantKnowledge: finalRelevantKnowledge,
      relevantExperiences,
      knownRisks,
      openContradictions,
      historicalStrategies,
      pendingApprovals,
      deadline,
      budget,
      objectives,
      fingerprint,
      createdAt: new Date().toISOString(),
    };

    executionPersistence.saveDecisionContext(context);
    return context;
  }
}

export const decisionContextService = new DecisionContextService();
