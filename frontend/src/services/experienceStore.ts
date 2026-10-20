/**
 * AryaOS V1 — Stage 11: Sanitized Experience Store
 *
 * Persists and indexes sanitized execution experiences.
 * Enforces zero-secret leakage, input/output fingerprinting, and audit links
 * to the Stage 09 Execution Persistence service and Evidence Graph.
 */

import { ExperienceRecord, EvaluationRecord } from '../types/agentEvaluation';
import { ProviderCapabilityType } from '../types/intelligenceProvider';
import { executionPersistence } from './executionPersistence';
import { evidenceGraph } from './evidenceGraph';

export interface RecordExperienceInput {
  goalId: string;
  actionId: string;
  agentId: string;
  providerId: string;
  capability: ProviderCapabilityType;
  taskType: string;
  executionId: string;
  planVersion: number;
  rawInput: unknown;
  rawOutput: unknown;
  evaluation: EvaluationRecord;
  cost: number | 'UNKNOWN';
  latencyMs: number;
  status: string;
  humanDecision?: 'APPROVED' | 'REJECTED';
  downstreamOutcome?: string;
  provenance?: Record<string, unknown>;
}

export class ExperienceStore {
  /**
   * Deterministic 64-character hash for input/output fingerprinting
   */
  public computeFingerprint(input: unknown): string {
    const str = typeof input === 'string' ? input : JSON.stringify(input || '');
    let h1 = 0xdeadbeef,
      h2 = 0x41c64e6d,
      h3 = 0x12345678,
      h4 = 0x98765432;
    for (let i = 0; i < str.length; i++) {
      const ch = str.charCodeAt(i);
      h1 = Math.imul(h1 ^ ch, 2654435761);
      h2 = Math.imul(h2 ^ ch, 1597334677);
      h3 = Math.imul(h3 ^ ch, 3812015801);
      h4 = Math.imul(h4 ^ ch, 2718281829);
    }
    h1 = Math.imul(h1 ^ (h1 >>> 16), 2246822507) ^ Math.imul(h2 ^ (h2 >>> 13), 3266489909);
    h2 = Math.imul(h2 ^ (h2 >>> 16), 2246822507) ^ Math.imul(h3 ^ (h3 >>> 13), 3266489909);
    h3 = Math.imul(h3 ^ (h3 >>> 16), 2246822507) ^ Math.imul(h4 ^ (h4 >>> 13), 3266489909);
    h4 = Math.imul(h4 ^ (h4 >>> 16), 2246822507) ^ Math.imul(h1 ^ (h1 >>> 13), 3266489909);
    const p1 = (h1 >>> 0).toString(16).padStart(8, '0');
    const p2 = (h2 >>> 0).toString(16).padStart(8, '0');
    const p3 = (h3 >>> 0).toString(16).padStart(8, '0');
    const p4 = (h4 >>> 0).toString(16).padStart(8, '0');
    return `${p1}${p2}${p3}${p4}${p4}${p3}${p2}${p1}`;
  }

  /**
   * Records a sanitized execution experience and links evidence into the EvidenceGraph.
   */
  public recordExperience(input: RecordExperienceInput): ExperienceRecord {
    const sanitizedInput = executionPersistence.sanitizeForPersistence(input.rawInput);
    const sanitizedOutput = executionPersistence.sanitizeForPersistence(input.rawOutput);
    const sanitizedProvenance = executionPersistence.sanitizeForPersistence(input.provenance || {});

    const inputFingerprint = this.computeFingerprint(sanitizedInput);
    const outputFingerprint = this.computeFingerprint(sanitizedOutput);

    const experienceId = `exp-${Date.now()}-${Math.random().toString(36).substr(2, 6)}`;
    const timestamp = new Date().toISOString();

    const experience: ExperienceRecord = {
      experienceId,
      goalId: input.goalId,
      actionId: input.actionId,
      agentId: input.agentId,
      providerId: input.providerId,
      capability: input.capability,
      taskType: input.taskType,
      executionId: input.executionId,
      planVersion: input.planVersion,
      inputFingerprint,
      outputFingerprint,
      evaluation: input.evaluation,
      cost: input.cost,
      latencyMs: input.latencyMs,
      status: input.status,
      humanDecision: input.humanDecision,
      downstreamOutcome: input.downstreamOutcome,
      timestamp,
      provenance: sanitizedProvenance,
    };

    // Save to execution persistence
    executionPersistence.saveExperience(experience);
    executionPersistence.saveEvaluation(input.evaluation);

    // Link into EvidenceGraph
    evidenceGraph.createEvidenceItem(
      'GOAL',
      input.goalId,
      `Goal context for action ${input.actionId}`,
      'Orchestrator'
    );
    evidenceGraph.createEvidenceItem(
      'ACTION',
      input.actionId,
      `Action ${input.actionId} (task: ${input.taskType})`,
      'ActionDAG'
    );
    evidenceGraph.createEvidenceItem(
      'AGENT',
      input.agentId,
      `Assigned Agent ${input.agentId}`,
      'AgentRegistry'
    );
    evidenceGraph.createEvidenceItem(
      'PROVIDER',
      input.providerId,
      `Intelligence Provider ${input.providerId}`,
      'ExecutionGateway'
    );
    evidenceGraph.createEvidenceItem(
      'EXECUTION',
      input.executionId,
      `Execution status: ${input.status} (${input.latencyMs}ms)`,
      'ExecutionGateway'
    );
    evidenceGraph.createEvidenceItem(
      'EVALUATION',
      input.evaluation.evaluationId,
      `Evaluation score: ${input.evaluation.overallScore}`,
      'AgentEvaluationService'
    );

    evidenceGraph.linkEntities(input.goalId, input.actionId, 'INCLUDES_ACTION');
    evidenceGraph.linkEntities(input.actionId, input.agentId, 'ASSIGNED_TO_AGENT');
    evidenceGraph.linkEntities(input.agentId, input.providerId, 'DISPATCHED_TO_PROVIDER');
    evidenceGraph.linkEntities(input.actionId, input.executionId, 'GENERATED_EXECUTION');
    evidenceGraph.linkEntities(input.executionId, input.evaluation.evaluationId, 'EVALUATED_BY');

    if (input.humanDecision) {
      const approvalNodeId = `appr-${input.executionId}`;
      evidenceGraph.createEvidenceItem(
        'HUMAN_APPROVAL',
        approvalNodeId,
        `Human operator decision: ${input.humanDecision}`,
        'HumanOperator'
      );
      evidenceGraph.linkEntities(input.evaluation.evaluationId, approvalNodeId, 'GOVERNED_BY');
    }

    return experience;
  }

  /**
   * Retrieves all experiences, optionally filtered.
   */
  public getExperiences(filter?: {
    agentId?: string;
    providerId?: string;
    taskType?: string;
    goalId?: string;
  }): ExperienceRecord[] {
    return executionPersistence.getExperiences(filter);
  }

  /**
   * Retrieves a single experience by ID.
   */
  public getExperience(experienceId: string): ExperienceRecord | null {
    const list = executionPersistence.getExperiences();
    return list.find((e) => e.experienceId === experienceId) || null;
  }

  /**
   * Retrieves experiences by task type.
   */
  public getExperiencesByTaskType(taskType: string): ExperienceRecord[] {
    return this.getExperiences({ taskType });
  }

  /**
   * Retrieves experiences by agent ID.
   */
  public getExperiencesByAgent(agentId: string): ExperienceRecord[] {
    return this.getExperiences({ agentId });
  }

  /**
   * Retrieves experiences by provider ID.
   */
  public getExperiencesByProvider(providerId: string): ExperienceRecord[] {
    return this.getExperiences({ providerId });
  }

  /**
   * Clears all stored experiences.
   */
  public clearExperiences(): void {
    const envelope = executionPersistence.loadEnvelope();
    if (envelope) {
      envelope.experiences = {};
      envelope.evaluations = {};
      executionPersistence.saveEnvelope(envelope);
    }
  }
}

export const experienceStore = new ExperienceStore();
