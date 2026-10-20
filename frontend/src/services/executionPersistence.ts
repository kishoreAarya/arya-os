/**
 * AryaOS V1 — Stage 09: Execution Persistence Service
 *
 * Provider-neutral, zero-secret-leakage persistence layer for Autonomous Goals,
 * Action Graphs (DAGs), Observations, Approvals, and Operational Telemetry.
 */

import { Goal, Observation } from '../types/goalOrchestration';
import {
  PersistedOrchestrationEnvelope,
  PersistedApprovalRecord,
  OperationalTelemetry,
} from '../types/executionPersistence';
import {
  ExperienceRecord,
  EvaluationRecord,
  LearningSignal,
  PolicyRecommendation,
  PlanEvaluation,
} from '../types/agentEvaluation';
import { Mission, MissionCheckpoint } from '../types/missionControl';
import {
  KnowledgeNode,
  KnowledgeEdge,
  KnowledgeFact,
  KnowledgeContradiction,
  KnowledgePattern,
  KnowledgeStrategy,
  MissionKnowledgeSnapshot,
  KnowledgeSnapshot,
} from '../types/strategicKnowledge';
import {
  Decision,
  DecisionContext,
  DecisionRecommendation,
  PostDecisionRecord,
  DecisionEvaluation,
} from '../types/decisionIntelligence';
import {
  ActionAuditRecord,
  ActionResult,
  ActionRequest,
} from '../types/actionBus';
import {
  Connector,
  ConnectorLifecycleEvent,
  AgentCapabilityGrant,
  MissionCapabilityGrant,
} from '../types/connectorFabric';
import {
  Trigger,
  ReactionProposal,
  ReactionExecutionResult,
} from '../types/eventTrigger';
import {
  Policy,
  PolicyProposal,
  PolicyActivationRecord,
  PolicyRollbackRecord,
  PolicyShadowRecord,
  PolicyDriftRecord,
  PolicyConflictRecord,
} from '../types/policyIntelligence';
import {
  GovernanceDecision,
  PolicySnapshot,
} from '../types/governanceControlPlane';
import { OperationalAuditEvent } from '../types/operationalAudit';
import {
  RecoveryControlDecision,
  RecoveryControlRequest,
  RecoveryControlLease,
} from '../types/recoveryControl';

export const STORAGE_KEY_ORCHESTRATION = 'arya_persisted_orchestration_envelope';
export const CURRENT_ORCHESTRATION_SCHEMA_VERSION = 1;

const DEFAULT_TELEMETRY: OperationalTelemetry = {
  totalGoalsStarted: 0,
  totalGoalsCompleted: 0,
  totalGoalsFailed: 0,
  totalGoalsRecovered: 0,
  totalActionsExecuted: 0,
  totalFallbacksTriggered: 0,
  totalReplans: 0,
  averageLatencyMs: 'UNKNOWN',
  totalCostUsd: 'UNKNOWN',
};

// In-memory fallback if localStorage is inaccessible or throws QuotaExceededError
let memoryFallbackStore: string | null = null;

export class ExecutionPersistence {
  /**
   * Recursively sanitizes any data structure before serialization.
   * Enforces Zero Secret Leakage: strips api keys, bearer tokens, passwords, and sensitive headers.
   */
  public sanitizeForPersistence<T>(data: T): T {
    if (data === null || data === undefined) return data;
    if (typeof data !== 'object') {
      if (typeof data === 'string') {
        return this.sanitizeString(data) as unknown as T;
      }
      return data;
    }

    if (Array.isArray(data)) {
      return data.map((item) => this.sanitizeForPersistence(item)) as unknown as T;
    }

    const cleanObj: Record<string, unknown> = {};
    const sensitiveKeyPatterns = [
      'apikey',
      'api_key',
      'token',
      'secret',
      'password',
      'bearer',
      'credential',
      'privatekey',
    ];

    for (const [key, value] of Object.entries(data as Record<string, unknown>)) {
      const lowerKey = key.toLowerCase();
      const isSensitiveKey =
        !lowerKey.includes('state') &&
        !lowerKey.includes('ref') &&
        (lowerKey === 'authorization' ||
          lowerKey === 'auth' ||
          lowerKey.startsWith('auth_') ||
          sensitiveKeyPatterns.some((pattern) => lowerKey.includes(pattern)));

      if (isSensitiveKey) {
        // Redact sensitive keys
        cleanObj[key] = '[REDACTED_SECRET]';
      } else if (typeof value === 'object' && value !== null) {
        cleanObj[key] = this.sanitizeForPersistence(value);
      } else if (typeof value === 'string') {
        cleanObj[key] = this.sanitizeString(value);
      } else {
        cleanObj[key] = value;
      }
    }

    return cleanObj as T;
  }

  /**
   * Sanitizes strings to scrub raw tokens, Bearer headers, or secret patterns.
   */
  public sanitizeString(text: string): string {
    return text
      .replace(/Bearer\s+[A-Za-z0-9\-_\.=]+/gi, 'Bearer [REDACTED_TOKEN]')
      .replace(/sk-[A-Za-z0-9\-_]{20,}/gi, 'sk-[REDACTED_KEY]')
      .replace(/key-[A-Za-z0-9\-_]{20,}/gi, 'key-[REDACTED_KEY]')
      .replace(/ghp_[A-Za-z0-9]{20,}/gi, 'ghp_[REDACTED_TOKEN]');
  }

  /**
   * Serializes a PersistedOrchestrationEnvelope into a sanitized JSON string.
   */
  public serializeEnvelope(envelope: PersistedOrchestrationEnvelope): string {
    const sanitized = this.sanitizeForPersistence(envelope);
    return JSON.stringify(sanitized);
  }

  /**
   * Validates schema and structural integrity of a persisted envelope.
   */
  public validateEnvelope(payload: unknown): payload is PersistedOrchestrationEnvelope {
    if (!payload || typeof payload !== 'object') return false;
    const env = payload as Record<string, unknown>;

    if (env.schemaVersion !== CURRENT_ORCHESTRATION_SCHEMA_VERSION) return false;
    if (typeof env.savedAt !== 'string') return false;
    if (!env.goals || typeof env.goals !== 'object') return false;
    if (!env.observations || typeof env.observations !== 'object') return false;
    if (!env.approvals || typeof env.approvals !== 'object') return false;
    if (!env.telemetry || typeof env.telemetry !== 'object') return false;

    return true;
  }

  /**
   * Deserializes a persisted JSON string into a validated envelope, or null if corrupted.
   */
  public deserializeEnvelope(payload: string): PersistedOrchestrationEnvelope | null {
    if (!payload || typeof payload !== 'string') return null;

    try {
      const parsed = JSON.parse(payload);
      if (!this.validateEnvelope(parsed)) {
        return null;
      }
      return parsed;
    } catch {
      return null;
    }
  }

  /**
   * Saves the entire orchestration envelope to persistent storage.
   */
  public saveEnvelope(envelope: PersistedOrchestrationEnvelope): boolean {
    try {
      const serialized = this.serializeEnvelope(envelope);
      if (typeof localStorage !== 'undefined') {
        localStorage.setItem(STORAGE_KEY_ORCHESTRATION, serialized);
      }
      memoryFallbackStore = serialized;
      return true;
    } catch (err) {
      console.warn('Failed to save orchestration envelope to localStorage, falling back to memory store:', err);
      try {
        memoryFallbackStore = this.serializeEnvelope(envelope);
        return true;
      } catch {
        return false;
      }
    }
  }

  /**
   * Loads the orchestration envelope from persistent storage.
   */
  public loadEnvelope(): PersistedOrchestrationEnvelope | null {
    try {
      let raw: string | null = null;
      if (typeof localStorage !== 'undefined') {
        raw = localStorage.getItem(STORAGE_KEY_ORCHESTRATION);
      }
      if (!raw) {
        raw = memoryFallbackStore;
      }
      if (!raw) return null;
      return this.deserializeEnvelope(raw);
    } catch (err) {
      console.warn('Failed to load orchestration envelope from storage:', err);
      return null;
    }
  }

  /**
   * Clears the orchestration storage (useful for reset, testing, and logout).
   */
  public clearEnvelope(): void {
    try {
      if (typeof localStorage !== 'undefined') {
        localStorage.removeItem(STORAGE_KEY_ORCHESTRATION);
      }
      memoryFallbackStore = null;
    } catch (err) {
      console.warn('Failed to clear orchestration envelope:', err);
    }
  }

  /**
   * Checks if persisted orchestration state currently exists.
   */
  public hasPersistedState(): boolean {
    try {
      if (typeof localStorage !== 'undefined') {
        const raw = localStorage.getItem(STORAGE_KEY_ORCHESTRATION);
        if (raw) return true;
      }
      return memoryFallbackStore !== null;
    } catch {
      return false;
    }
  }

  /**
   * Identifies whether the current storage backend is durable (e.g. localStorage)
   * or non-durable in-memory fallback.
   * Never claims durable persistence during memory fallback.
   */
  public isDurableStorageActive(): boolean {
    try {
      if (typeof localStorage === 'undefined') return false;
      const testKey = '__aryaos_durability_test__';
      localStorage.setItem(testKey, '1');
      localStorage.removeItem(testKey);
      return true;
    } catch {
      return false;
    }
  }

  /**
   * Creates a fresh default envelope.
   */
  public createDefaultEnvelope(): PersistedOrchestrationEnvelope {
    return {
      schemaVersion: CURRENT_ORCHESTRATION_SCHEMA_VERSION,
      savedAt: new Date().toISOString(),
      goals: {},
      activeGoalId: null,
      observations: {},
      approvals: {},
      telemetry: { ...DEFAULT_TELEMETRY },
      experiences: {},
      evaluations: {},
      learningSignals: {},
      policyRecommendations: {},
      planEvaluations: {},
      missions: {},
      activeMissionId: null,
      missionCheckpoints: {},
      recoveryControlDecisions: {},
      recoveryControlRequests: {},
      recoveryControlLeases: {},
    };
  }

  /**
   * Helper: Saves a single Goal into the persisted envelope.
   */
  public saveGoal(goal: Goal): boolean {
    const envelope = this.loadEnvelope() || this.createDefaultEnvelope();
    envelope.goals[goal.goalId] = goal;
    envelope.activeGoalId = goal.goalId;
    envelope.savedAt = new Date().toISOString();
    return this.saveEnvelope(envelope);
  }

  /**
   * Helper: Saves an observation list for a goal.
   */
  public saveObservation(goalId: string, observation: Observation): boolean {
    const envelope = this.loadEnvelope() || this.createDefaultEnvelope();
    const existing = envelope.observations[goalId] || [];
    existing.push(observation);
    envelope.observations[goalId] = existing;
    envelope.savedAt = new Date().toISOString();
    return this.saveEnvelope(envelope);
  }

  /**
   * Helper: Saves an approval record.
   */
  public saveApproval(approval: PersistedApprovalRecord): boolean {
    const envelope = this.loadEnvelope() || this.createDefaultEnvelope();
    envelope.approvals[approval.approvalId] = approval;
    envelope.savedAt = new Date().toISOString();
    return this.saveEnvelope(envelope);
  }

  /**
   * Helper: Updates telemetry counters atomically.
   */
  public updateTelemetry(updater: (prev: OperationalTelemetry) => OperationalTelemetry): void {
    const envelope = this.loadEnvelope() || this.createDefaultEnvelope();
    envelope.telemetry = updater(envelope.telemetry || { ...DEFAULT_TELEMETRY });
    envelope.savedAt = new Date().toISOString();
    this.saveEnvelope(envelope);
  }

  /**
   * Helper: Saves an experience record into the persisted envelope.
   */
  public saveExperience(experience: ExperienceRecord): boolean {
    const envelope = this.loadEnvelope() || this.createDefaultEnvelope();
    if (!envelope.experiences) envelope.experiences = {};
    envelope.experiences[experience.experienceId] = experience;
    envelope.savedAt = new Date().toISOString();
    return this.saveEnvelope(envelope);
  }

  /**
   * Helper: Retrieves experiences with optional filters.
   */
  public getExperiences(filter?: {
    agentId?: string;
    providerId?: string;
    taskType?: string;
    goalId?: string;
  }): ExperienceRecord[] {
    const envelope = this.loadEnvelope();
    if (!envelope || !envelope.experiences) return [];
    let list = Object.values(envelope.experiences);
    if (filter?.agentId) list = list.filter((e) => e.agentId === filter.agentId);
    if (filter?.providerId) list = list.filter((e) => e.providerId === filter.providerId);
    if (filter?.taskType) list = list.filter((e) => e.taskType === filter.taskType);
    if (filter?.goalId) list = list.filter((e) => e.goalId === filter.goalId);
    return list;
  }

  /**
   * Helper: Saves an evaluation record into the persisted envelope.
   */
  public saveEvaluation(evaluation: EvaluationRecord): boolean {
    const envelope = this.loadEnvelope() || this.createDefaultEnvelope();
    if (!envelope.evaluations) envelope.evaluations = {};
    envelope.evaluations[evaluation.evaluationId] = evaluation;
    envelope.savedAt = new Date().toISOString();
    return this.saveEnvelope(envelope);
  }

  /**
   * Helper: Retrieves evaluations with optional filters.
   */
  public getEvaluations(filter?: {
    agentId?: string;
    providerId?: string;
    goalId?: string;
  }): EvaluationRecord[] {
    const envelope = this.loadEnvelope();
    if (!envelope || !envelope.evaluations) return [];
    let list = Object.values(envelope.evaluations);
    if (filter?.agentId) list = list.filter((e) => e.agentId === filter.agentId);
    if (filter?.providerId) list = list.filter((e) => e.providerId === filter.providerId);
    if (filter?.goalId) list = list.filter((e) => e.goalId === filter.goalId);
    return list;
  }

  /**
   * Helper: Saves a learning signal into the persisted envelope.
   */
  public saveLearningSignal(signal: LearningSignal): boolean {
    const envelope = this.loadEnvelope() || this.createDefaultEnvelope();
    if (!envelope.learningSignals) envelope.learningSignals = {};
    envelope.learningSignals[signal.signalId] = signal;
    envelope.savedAt = new Date().toISOString();
    return this.saveEnvelope(envelope);
  }

  /**
   * Helper: Retrieves learning signals with optional filters.
   */
  public getLearningSignals(filter?: {
    dimension?: string;
    status?: string;
  }): LearningSignal[] {
    const envelope = this.loadEnvelope();
    if (!envelope || !envelope.learningSignals) return [];
    let list = Object.values(envelope.learningSignals);
    if (filter?.dimension) list = list.filter((s) => s.dimension === filter.dimension);
    if (filter?.status) list = list.filter((s) => s.status === filter.status);
    return list;
  }

  /**
   * Helper: Saves a policy recommendation into the persisted envelope.
   */
  public savePolicyRecommendation(rec: PolicyRecommendation): boolean {
    const envelope = this.loadEnvelope() || this.createDefaultEnvelope();
    if (!envelope.policyRecommendations) envelope.policyRecommendations = {};
    envelope.policyRecommendations[rec.recommendationId] = rec;
    envelope.savedAt = new Date().toISOString();
    return this.saveEnvelope(envelope);
  }

  /**
   * Helper: Retrieves policy recommendations with optional status filter.
   */
  public getPolicyRecommendations(status?: string): PolicyRecommendation[] {
    const envelope = this.loadEnvelope();
    if (!envelope || !envelope.policyRecommendations) return [];
    let list = Object.values(envelope.policyRecommendations);
    if (status) list = list.filter((r) => r.status === status);
    return list;
  }

  /**
   * Helper: Saves a plan evaluation into the persisted envelope.
   */
  public savePlanEvaluation(planEval: PlanEvaluation): boolean {
    const envelope = this.loadEnvelope() || this.createDefaultEnvelope();
    if (!envelope.planEvaluations) envelope.planEvaluations = {};
    envelope.planEvaluations[planEval.planEvaluationId] = planEval;
    envelope.savedAt = new Date().toISOString();
    return this.saveEnvelope(envelope);
  }

  /**
   * Helper: Retrieves plan evaluations with optional goalId filter.
   */
  public getPlanEvaluations(goalId?: string): PlanEvaluation[] {
    const envelope = this.loadEnvelope();
    if (!envelope || !envelope.planEvaluations) return [];
    let list = Object.values(envelope.planEvaluations);
    if (goalId) list = list.filter((pe) => pe.goalId === goalId);
    return list;
  }

  /**
   * Helper: Saves a Mission into the persisted envelope.
   */
  public saveMission(mission: Mission): boolean {
    const envelope = this.loadEnvelope() || this.createDefaultEnvelope();
    if (!envelope.missions) envelope.missions = {};
    envelope.missions[mission.missionId] = mission;
    envelope.activeMissionId = mission.missionId;
    envelope.savedAt = new Date().toISOString();
    return this.saveEnvelope(envelope);
  }

  /**
   * Helper: Retrieves a single Mission by ID.
   */
  public getMission(missionId: string): Mission | null {
    const envelope = this.loadEnvelope();
    if (!envelope || !envelope.missions) return null;
    return envelope.missions[missionId] || null;
  }

  /**
   * Helper: Retrieves all persisted Missions.
   */
  public getMissions(): Mission[] {
    const envelope = this.loadEnvelope();
    if (!envelope || !envelope.missions) return [];
    return Object.values(envelope.missions);
  }

  /**
   * Helper: Saves a Mission Checkpoint into the persisted envelope.
   */
  public saveMissionCheckpoint(checkpoint: MissionCheckpoint): boolean {
    const envelope = this.loadEnvelope() || this.createDefaultEnvelope();
    if (!envelope.missionCheckpoints) envelope.missionCheckpoints = {};
    envelope.missionCheckpoints[checkpoint.checkpointId] = checkpoint;
    envelope.savedAt = new Date().toISOString();
    return this.saveEnvelope(envelope);
  }

  /**
   * Helper: Retrieves Mission Checkpoints, optionally filtered by missionId.
   */
  public getMissionCheckpoints(missionId?: string): MissionCheckpoint[] {
    const envelope = this.loadEnvelope();
    if (!envelope || !envelope.missionCheckpoints) return [];
    let list = Object.values(envelope.missionCheckpoints);
    if (missionId) list = list.filter((c) => c.missionId === missionId);
    return list;
  }

  // ==========================================
  // STAGE 13: STRATEGIC KNOWLEDGE METHODS
  // ==========================================

  public saveKnowledgeNode(node: KnowledgeNode): boolean {
    const envelope = this.loadEnvelope() || this.createDefaultEnvelope();
    if (!envelope.knowledgeNodes) envelope.knowledgeNodes = {};
    envelope.knowledgeNodes[node.id] = node;
    envelope.savedAt = new Date().toISOString();
    return this.saveEnvelope(envelope);
  }

  public getKnowledgeNode(id: string): KnowledgeNode | null {
    const envelope = this.loadEnvelope();
    if (!envelope || !envelope.knowledgeNodes) return null;
    return envelope.knowledgeNodes[id] || null;
  }

  public getKnowledgeNodes(type?: string): KnowledgeNode[] {
    const envelope = this.loadEnvelope();
    if (!envelope || !envelope.knowledgeNodes) return [];
    let list = Object.values(envelope.knowledgeNodes);
    if (type) list = list.filter((n) => n.type === type);
    return list;
  }

  public saveKnowledgeEdge(edge: KnowledgeEdge): boolean {
    const envelope = this.loadEnvelope() || this.createDefaultEnvelope();
    if (!envelope.knowledgeEdges) envelope.knowledgeEdges = [];
    // Deduplicate by source + target + relation
    const existingIdx = envelope.knowledgeEdges.findIndex(
      (e) => e.source === edge.source && e.target === edge.target && e.relation === edge.relation
    );
    if (existingIdx >= 0) {
      envelope.knowledgeEdges[existingIdx] = edge;
    } else {
      envelope.knowledgeEdges.push(edge);
    }
    envelope.savedAt = new Date().toISOString();
    return this.saveEnvelope(envelope);
  }

  public getKnowledgeEdges(nodeId?: string): KnowledgeEdge[] {
    const envelope = this.loadEnvelope();
    if (!envelope || !envelope.knowledgeEdges) return [];
    if (!nodeId) return envelope.knowledgeEdges;
    return envelope.knowledgeEdges.filter((e) => e.source === nodeId || e.target === nodeId);
  }

  public saveKnowledgeFact(fact: KnowledgeFact): boolean {
    const envelope = this.loadEnvelope() || this.createDefaultEnvelope();
    if (!envelope.knowledgeFacts) envelope.knowledgeFacts = {};
    envelope.knowledgeFacts[fact.id] = fact;
    envelope.savedAt = new Date().toISOString();
    return this.saveEnvelope(envelope);
  }

  public getKnowledgeFact(id: string): KnowledgeFact | null {
    const envelope = this.loadEnvelope();
    if (!envelope || !envelope.knowledgeFacts) return null;
    return envelope.knowledgeFacts[id] || null;
  }

  public getKnowledgeFacts(status?: string): KnowledgeFact[] {
    const envelope = this.loadEnvelope();
    if (!envelope || !envelope.knowledgeFacts) return [];
    let list = Object.values(envelope.knowledgeFacts);
    if (status) list = list.filter((f) => f.status === status);
    return list;
  }

  public saveKnowledgeContradiction(contradiction: KnowledgeContradiction): boolean {
    const envelope = this.loadEnvelope() || this.createDefaultEnvelope();
    if (!envelope.knowledgeContradictions) envelope.knowledgeContradictions = {};
    envelope.knowledgeContradictions[contradiction.contradictionId] = contradiction;
    envelope.savedAt = new Date().toISOString();
    return this.saveEnvelope(envelope);
  }

  public getKnowledgeContradictions(status?: string): KnowledgeContradiction[] {
    const envelope = this.loadEnvelope();
    if (!envelope || !envelope.knowledgeContradictions) return [];
    let list = Object.values(envelope.knowledgeContradictions);
    if (status) list = list.filter((c) => c.resolutionStatus === status);
    return list;
  }

  public saveKnowledgePattern(pattern: KnowledgePattern): boolean {
    const envelope = this.loadEnvelope() || this.createDefaultEnvelope();
    if (!envelope.knowledgePatterns) envelope.knowledgePatterns = {};
    envelope.knowledgePatterns[pattern.id] = pattern;
    envelope.savedAt = new Date().toISOString();
    return this.saveEnvelope(envelope);
  }

  public getKnowledgePatterns(type?: string): KnowledgePattern[] {
    const envelope = this.loadEnvelope();
    if (!envelope || !envelope.knowledgePatterns) return [];
    let list = Object.values(envelope.knowledgePatterns);
    if (type) list = list.filter((p) => p.type === type);
    return list;
  }

  public saveKnowledgeStrategy(strategy: KnowledgeStrategy): boolean {
    const envelope = this.loadEnvelope() || this.createDefaultEnvelope();
    if (!envelope.knowledgeStrategies) envelope.knowledgeStrategies = {};
    envelope.knowledgeStrategies[strategy.strategyId] = strategy;
    envelope.savedAt = new Date().toISOString();
    return this.saveEnvelope(envelope);
  }

  public getKnowledgeStrategies(status?: string): KnowledgeStrategy[] {
    const envelope = this.loadEnvelope();
    if (!envelope || !envelope.knowledgeStrategies) return [];
    let list = Object.values(envelope.knowledgeStrategies);
    if (status) list = list.filter((s) => s.status === status);
    return list;
  }

  public saveMissionKnowledgeSnapshot(snapshot: MissionKnowledgeSnapshot): boolean {
    const envelope = this.loadEnvelope() || this.createDefaultEnvelope();
    if (!envelope.missionKnowledgeSnapshots) envelope.missionKnowledgeSnapshots = {};
    if (!envelope.missionKnowledgeSnapshots[snapshot.missionId]) {
      envelope.missionKnowledgeSnapshots[snapshot.missionId] = [];
    }
    envelope.missionKnowledgeSnapshots[snapshot.missionId].push(snapshot);
    envelope.savedAt = new Date().toISOString();
    return this.saveEnvelope(envelope);
  }

  public getMissionKnowledgeSnapshots(missionId?: string): MissionKnowledgeSnapshot[] {
    const envelope = this.loadEnvelope();
    if (!envelope || !envelope.missionKnowledgeSnapshots) return [];
    if (missionId) return envelope.missionKnowledgeSnapshots[missionId] || [];
    return Object.values(envelope.missionKnowledgeSnapshots).flat();
  }

  public saveKnowledgeSnapshot(snapshot: KnowledgeSnapshot): boolean {
    const envelope = this.loadEnvelope() || this.createDefaultEnvelope();
    if (!envelope.knowledgeSnapshots) envelope.knowledgeSnapshots = [];
    envelope.knowledgeSnapshots.push(snapshot);
    envelope.savedAt = new Date().toISOString();
    return this.saveEnvelope(envelope);
  }

  public getKnowledgeSnapshots(): KnowledgeSnapshot[] {
    const envelope = this.loadEnvelope();
    if (!envelope || !envelope.knowledgeSnapshots) return [];
    return envelope.knowledgeSnapshots;
  }

  // --- Stage 14: Decision Intelligence Persistence Methods ---

  public saveDecision(decision: Decision): boolean {
    const envelope = this.loadEnvelope() || this.createDefaultEnvelope();
    if (!envelope.decisions) envelope.decisions = {};
    envelope.decisions[decision.id] = decision;
    envelope.savedAt = new Date().toISOString();
    return this.saveEnvelope(envelope);
  }

  public getDecision(decisionId: string): Decision | null {
    const envelope = this.loadEnvelope();
    if (!envelope || !envelope.decisions) return null;
    return envelope.decisions[decisionId] || null;
  }

  public getAllDecisions(status?: string): Decision[] {
    const envelope = this.loadEnvelope();
    if (!envelope || !envelope.decisions) return [];
    let list = Object.values(envelope.decisions);
    if (status) list = list.filter((d) => d.status === status);
    return list;
  }

  public saveDecisionContext(context: DecisionContext): boolean {
    const envelope = this.loadEnvelope() || this.createDefaultEnvelope();
    if (!envelope.decisionContexts) envelope.decisionContexts = {};
    envelope.decisionContexts[context.contextId] = context;
    envelope.savedAt = new Date().toISOString();
    return this.saveEnvelope(envelope);
  }

  public getDecisionContext(contextId: string): DecisionContext | null {
    const envelope = this.loadEnvelope();
    if (!envelope || !envelope.decisionContexts) return null;
    return envelope.decisionContexts[contextId] || null;
  }

  public getAllDecisionContexts(): DecisionContext[] {
    const envelope = this.loadEnvelope();
    if (!envelope || !envelope.decisionContexts) return [];
    return Object.values(envelope.decisionContexts);
  }

  public saveDecisionRecommendation(recommendation: DecisionRecommendation): boolean {
    const envelope = this.loadEnvelope() || this.createDefaultEnvelope();
    if (!envelope.decisionRecommendations) envelope.decisionRecommendations = {};
    envelope.decisionRecommendations[recommendation.recommendationId] = recommendation;
    envelope.savedAt = new Date().toISOString();
    return this.saveEnvelope(envelope);
  }

  public getDecisionRecommendation(recommendationId: string): DecisionRecommendation | null {
    const envelope = this.loadEnvelope();
    if (!envelope || !envelope.decisionRecommendations) return null;
    return envelope.decisionRecommendations[recommendationId] || null;
  }

  public getAllDecisionRecommendations(status?: string): DecisionRecommendation[] {
    const envelope = this.loadEnvelope();
    if (!envelope || !envelope.decisionRecommendations) return [];
    let list = Object.values(envelope.decisionRecommendations);
    if (status) list = list.filter((r) => r.status === status);
    return list;
  }

  public savePostDecisionRecord(record: PostDecisionRecord): boolean {
    const envelope = this.loadEnvelope() || this.createDefaultEnvelope();
    if (!envelope.postDecisionRecords) envelope.postDecisionRecords = {};
    envelope.postDecisionRecords[record.decisionId] = record;
    envelope.savedAt = new Date().toISOString();
    return this.saveEnvelope(envelope);
  }

  public getPostDecisionRecord(decisionId: string): PostDecisionRecord | null {
    const envelope = this.loadEnvelope();
    if (!envelope || !envelope.postDecisionRecords) return null;
    return envelope.postDecisionRecords[decisionId] || null;
  }

  public getAllPostDecisionRecords(): PostDecisionRecord[] {
    const envelope = this.loadEnvelope();
    if (!envelope || !envelope.postDecisionRecords) return [];
    return Object.values(envelope.postDecisionRecords);
  }

  public saveDecisionEvaluation(evaluation: DecisionEvaluation): boolean {
    const envelope = this.loadEnvelope() || this.createDefaultEnvelope();
    if (!envelope.decisionEvaluations) envelope.decisionEvaluations = {};
    envelope.decisionEvaluations[evaluation.decisionId] = evaluation;
    envelope.savedAt = new Date().toISOString();
    return this.saveEnvelope(envelope);
  }

  public getDecisionEvaluation(decisionId: string): DecisionEvaluation | null {
    const envelope = this.loadEnvelope();
    if (!envelope || !envelope.decisionEvaluations) return null;
    return envelope.decisionEvaluations[decisionId] || null;
  }

  public getAllDecisionEvaluations(): DecisionEvaluation[] {
    const envelope = this.loadEnvelope();
    if (!envelope || !envelope.decisionEvaluations) return [];
    return Object.values(envelope.decisionEvaluations);
  }

  // --- Stage 15: Action Bus Persistence Methods ---

  public saveActionAuditRecord(record: ActionAuditRecord): boolean {
    const envelope = this.loadEnvelope() || this.createDefaultEnvelope();
    if (!envelope.actionAuditRecords) envelope.actionAuditRecords = {};
    envelope.actionAuditRecords[record.actionId] = this.sanitizeForPersistence(record);
    envelope.savedAt = new Date().toISOString();
    return this.saveEnvelope(envelope);
  }

  public getActionAuditRecord(actionId: string): ActionAuditRecord | null {
    const envelope = this.loadEnvelope();
    if (!envelope || !envelope.actionAuditRecords) return null;
    return envelope.actionAuditRecords[actionId] || null;
  }

  public getAllActionAuditRecords(): ActionAuditRecord[] {
    const envelope = this.loadEnvelope();
    if (!envelope || !envelope.actionAuditRecords) return [];
    return Object.values(envelope.actionAuditRecords);
  }

  public saveActionResult(result: ActionResult): boolean {
    const envelope = this.loadEnvelope() || this.createDefaultEnvelope();
    if (!envelope.actionResults) envelope.actionResults = {};
    envelope.actionResults[result.actionId] = this.sanitizeForPersistence(result);
    envelope.savedAt = new Date().toISOString();
    return this.saveEnvelope(envelope);
  }

  public getActionResult(actionId: string): ActionResult | null {
    const envelope = this.loadEnvelope();
    if (!envelope || !envelope.actionResults) return null;
    return envelope.actionResults[actionId] || null;
  }

  public getAllActionResults(): ActionResult[] {
    const envelope = this.loadEnvelope();
    if (!envelope || !envelope.actionResults) return [];
    return Object.values(envelope.actionResults);
  }

  public saveActionRequest(request: ActionRequest): boolean {
    const envelope = this.loadEnvelope() || this.createDefaultEnvelope();
    if (!envelope.persistedActionRequests) envelope.persistedActionRequests = {};
    envelope.persistedActionRequests[request.actionId] = this.sanitizeForPersistence(request);
    envelope.savedAt = new Date().toISOString();
    return this.saveEnvelope(envelope);
  }

  public getActionRequest(actionId: string): ActionRequest | null {
    const envelope = this.loadEnvelope();
    if (!envelope || !envelope.persistedActionRequests) return null;
    return envelope.persistedActionRequests[actionId] || null;
  }

  public getAllActionRequests(): ActionRequest[] {
    const envelope = this.loadEnvelope();
    if (!envelope || !envelope.persistedActionRequests) return [];
    return Object.values(envelope.persistedActionRequests);
  }

  // --- Stage 16: Connector Fabric Persistence ---

  public saveConnector(connector: Connector): boolean {
    const envelope = this.loadEnvelope() || this.createDefaultEnvelope();
    if (!envelope.connectors) envelope.connectors = {};
    envelope.connectors[connector.id] = this.sanitizeForPersistence(connector);
    envelope.savedAt = new Date().toISOString();
    return this.saveEnvelope(envelope);
  }

  public getConnector(connectorId: string): Connector | null {
    const envelope = this.loadEnvelope();
    if (!envelope || !envelope.connectors) return null;
    return envelope.connectors[connectorId] || null;
  }

  public getAllConnectors(): Connector[] {
    const envelope = this.loadEnvelope();
    if (!envelope || !envelope.connectors) return [];
    return Object.values(envelope.connectors);
  }

  public deleteConnector(connectorId: string): boolean {
    const envelope = this.loadEnvelope();
    if (!envelope || !envelope.connectors) return false;
    if (envelope.connectors[connectorId]) {
      delete envelope.connectors[connectorId];
      envelope.savedAt = new Date().toISOString();
      return this.saveEnvelope(envelope);
    }
    return false;
  }

  public saveConnectorAuditEvent(event: ConnectorLifecycleEvent): boolean {
    const envelope = this.loadEnvelope() || this.createDefaultEnvelope();
    if (!envelope.connectorAuditEvents) envelope.connectorAuditEvents = [];
    envelope.connectorAuditEvents.push(this.sanitizeForPersistence(event));
    envelope.savedAt = new Date().toISOString();
    return this.saveEnvelope(envelope);
  }

  public getConnectorAuditEvents(connectorId?: string): ConnectorLifecycleEvent[] {
    const envelope = this.loadEnvelope();
    if (!envelope || !envelope.connectorAuditEvents) return [];
    if (!connectorId) return envelope.connectorAuditEvents;
    return envelope.connectorAuditEvents.filter((e) => e.connectorId === connectorId);
  }

  public saveAgentCapabilityGrant(grant: AgentCapabilityGrant): boolean {
    const envelope = this.loadEnvelope() || this.createDefaultEnvelope();
    if (!envelope.agentCapabilityGrants) envelope.agentCapabilityGrants = {};
    envelope.agentCapabilityGrants[grant.grantId] = this.sanitizeForPersistence(grant);
    envelope.savedAt = new Date().toISOString();
    return this.saveEnvelope(envelope);
  }

  public getAgentCapabilityGrant(grantId: string): AgentCapabilityGrant | null {
    const envelope = this.loadEnvelope();
    if (!envelope || !envelope.agentCapabilityGrants) return null;
    return envelope.agentCapabilityGrants[grantId] || null;
  }

  public getAllAgentCapabilityGrants(agentId?: string): AgentCapabilityGrant[] {
    const envelope = this.loadEnvelope();
    if (!envelope || !envelope.agentCapabilityGrants) return [];
    const all = Object.values(envelope.agentCapabilityGrants);
    if (!agentId) return all;
    return all.filter((g) => g.agentId === agentId);
  }

  public saveMissionCapabilityGrant(grant: MissionCapabilityGrant): boolean {
    const envelope = this.loadEnvelope() || this.createDefaultEnvelope();
    if (!envelope.missionCapabilityGrants) envelope.missionCapabilityGrants = {};
    envelope.missionCapabilityGrants[grant.grantId] = this.sanitizeForPersistence(grant);
    envelope.savedAt = new Date().toISOString();
    return this.saveEnvelope(envelope);
  }

  public getMissionCapabilityGrant(grantId: string): MissionCapabilityGrant | null {
    const envelope = this.loadEnvelope();
    if (!envelope || !envelope.missionCapabilityGrants) return null;
    return envelope.missionCapabilityGrants[grantId] || null;
  }

  public getAllMissionCapabilityGrants(missionId?: string): MissionCapabilityGrant[] {
    const envelope = this.loadEnvelope();
    if (!envelope || !envelope.missionCapabilityGrants) return [];
    const all = Object.values(envelope.missionCapabilityGrants);
    if (!missionId) return all;
    return all.filter((g) => g.missionId === missionId);
  }

  // ============================================================
  // Stage 19: Event Triggers & Reaction Persistence
  // ============================================================

  public saveTrigger(trigger: Trigger): boolean {
    const envelope = this.loadEnvelope() || this.createDefaultEnvelope();
    if (!envelope.triggers) envelope.triggers = {};
    envelope.triggers[trigger.triggerId] = this.sanitizeForPersistence(trigger);
    envelope.savedAt = new Date().toISOString();
    return this.saveEnvelope(envelope);
  }

  public getTrigger(triggerId: string): Trigger | null {
    const envelope = this.loadEnvelope();
    if (!envelope || !envelope.triggers) return null;
    return envelope.triggers[triggerId] || null;
  }

  public getAllTriggers(): Trigger[] {
    const envelope = this.loadEnvelope();
    if (!envelope || !envelope.triggers) return [];
    return Object.values(envelope.triggers);
  }

  public saveReactionProposal(proposal: ReactionProposal): boolean {
    const envelope = this.loadEnvelope() || this.createDefaultEnvelope();
    if (!envelope.reactionProposals) envelope.reactionProposals = {};
    envelope.reactionProposals[proposal.proposalId] = this.sanitizeForPersistence(proposal);
    envelope.savedAt = new Date().toISOString();
    return this.saveEnvelope(envelope);
  }

  public getReactionProposal(proposalId: string): ReactionProposal | null {
    const envelope = this.loadEnvelope();
    if (!envelope || !envelope.reactionProposals) return null;
    return envelope.reactionProposals[proposalId] || null;
  }

  public getAllReactionProposals(): ReactionProposal[] {
    const envelope = this.loadEnvelope();
    if (!envelope || !envelope.reactionProposals) return [];
    return Object.values(envelope.reactionProposals);
  }

  public saveReactionResult(result: ReactionExecutionResult): boolean {
    const envelope = this.loadEnvelope() || this.createDefaultEnvelope();
    if (!envelope.reactionResults) envelope.reactionResults = {};
    envelope.reactionResults[result.proposalId] = this.sanitizeForPersistence(result);
    envelope.savedAt = new Date().toISOString();
    return this.saveEnvelope(envelope);
  }

  public getReactionResult(proposalId: string): ReactionExecutionResult | null {
    const envelope = this.loadEnvelope();
    if (!envelope || !envelope.reactionResults) return null;
    return envelope.reactionResults[proposalId] || null;
  }

  public getAllReactionResults(): ReactionExecutionResult[] {
    const envelope = this.loadEnvelope();
    if (!envelope || !envelope.reactionResults) return [];
    return Object.values(envelope.reactionResults);
  }

  // ==========================================
  // Stage 20 Policy Intelligence Persistence
  // ==========================================

  public savePolicy(policy: Policy): boolean {
    const envelope = this.loadEnvelope() || this.createDefaultEnvelope();
    if (!envelope.policies) envelope.policies = {};
    envelope.policies[policy.id] = this.sanitizeForPersistence(policy);
    envelope.savedAt = new Date().toISOString();
    return this.saveEnvelope(envelope);
  }

  public getPolicy(policyId: string): Policy | null {
    const envelope = this.loadEnvelope();
    if (!envelope || !envelope.policies) return null;
    return envelope.policies[policyId] || null;
  }

  public getAllPolicies(): Policy[] {
    const envelope = this.loadEnvelope();
    if (!envelope || !envelope.policies) return [];
    return Object.values(envelope.policies);
  }

  public savePolicyProposal(proposal: PolicyProposal): boolean {
    const envelope = this.loadEnvelope() || this.createDefaultEnvelope();
    if (!envelope.policyProposals) envelope.policyProposals = {};
    envelope.policyProposals[proposal.proposalId] = this.sanitizeForPersistence(proposal);
    envelope.savedAt = new Date().toISOString();
    return this.saveEnvelope(envelope);
  }

  public getPolicyProposal(proposalId: string): PolicyProposal | null {
    const envelope = this.loadEnvelope();
    if (!envelope || !envelope.policyProposals) return null;
    return envelope.policyProposals[proposalId] || null;
  }

  public getAllPolicyProposals(): PolicyProposal[] {
    const envelope = this.loadEnvelope();
    if (!envelope || !envelope.policyProposals) return [];
    return Object.values(envelope.policyProposals);
  }

  public savePolicyActivation(activation: PolicyActivationRecord): boolean {
    const envelope = this.loadEnvelope() || this.createDefaultEnvelope();
    if (!envelope.policyActivations) envelope.policyActivations = {};
    envelope.policyActivations[activation.activationId] = this.sanitizeForPersistence(activation);
    envelope.savedAt = new Date().toISOString();
    return this.saveEnvelope(envelope);
  }

  public getAllPolicyActivations(): PolicyActivationRecord[] {
    const envelope = this.loadEnvelope();
    if (!envelope || !envelope.policyActivations) return [];
    return Object.values(envelope.policyActivations);
  }

  public savePolicyRollback(rollback: PolicyRollbackRecord): boolean {
    const envelope = this.loadEnvelope() || this.createDefaultEnvelope();
    if (!envelope.policyRollbacks) envelope.policyRollbacks = {};
    envelope.policyRollbacks[rollback.rollbackId] = this.sanitizeForPersistence(rollback);
    envelope.savedAt = new Date().toISOString();
    return this.saveEnvelope(envelope);
  }

  public getAllPolicyRollbacks(): PolicyRollbackRecord[] {
    const envelope = this.loadEnvelope();
    if (!envelope || !envelope.policyRollbacks) return [];
    return Object.values(envelope.policyRollbacks);
  }

  public savePolicyShadow(shadow: PolicyShadowRecord): boolean {
    const envelope = this.loadEnvelope() || this.createDefaultEnvelope();
    if (!envelope.policyShadows) envelope.policyShadows = {};
    envelope.policyShadows[shadow.shadowRecordId] = this.sanitizeForPersistence(shadow);
    envelope.savedAt = new Date().toISOString();
    return this.saveEnvelope(envelope);
  }

  public getAllPolicyShadows(): PolicyShadowRecord[] {
    const envelope = this.loadEnvelope();
    if (!envelope || !envelope.policyShadows) return [];
    return Object.values(envelope.policyShadows);
  }

  public savePolicyDrift(drift: PolicyDriftRecord): boolean {
    const envelope = this.loadEnvelope() || this.createDefaultEnvelope();
    if (!envelope.policyDrifts) envelope.policyDrifts = {};
    envelope.policyDrifts[drift.driftId] = this.sanitizeForPersistence(drift);
    envelope.savedAt = new Date().toISOString();
    return this.saveEnvelope(envelope);
  }

  public getAllPolicyDrifts(): PolicyDriftRecord[] {
    const envelope = this.loadEnvelope();
    if (!envelope || !envelope.policyDrifts) return [];
    return Object.values(envelope.policyDrifts);
  }

  public savePolicyConflict(conflict: PolicyConflictRecord): boolean {
    const envelope = this.loadEnvelope() || this.createDefaultEnvelope();
    if (!envelope.policyConflicts) envelope.policyConflicts = {};
    envelope.policyConflicts[conflict.conflictId] = this.sanitizeForPersistence(conflict);
    envelope.savedAt = new Date().toISOString();
    return this.saveEnvelope(envelope);
  }

  public getAllPolicyConflicts(): PolicyConflictRecord[] {
    const envelope = this.loadEnvelope();
    if (!envelope || !envelope.policyConflicts) return [];
    return Object.values(envelope.policyConflicts);
  }

  // Stage 21: Governed Policy Control Plane Persistence Methods
  public saveGovernanceDecision(decision: GovernanceDecision): boolean {
    const envelope = this.loadEnvelope() || this.createDefaultEnvelope();
    if (!envelope.governanceDecisions) envelope.governanceDecisions = {};
    envelope.governanceDecisions[decision.decisionId] = this.sanitizeForPersistence(decision);
    envelope.savedAt = new Date().toISOString();
    return this.saveEnvelope(envelope);
  }

  public getGovernanceDecision(decisionId: string): GovernanceDecision | null {
    const envelope = this.loadEnvelope();
    if (!envelope || !envelope.governanceDecisions) return null;
    return envelope.governanceDecisions[decisionId] || null;
  }

  public getAllGovernanceDecisions(): GovernanceDecision[] {
    const envelope = this.loadEnvelope();
    if (!envelope || !envelope.governanceDecisions) return [];
    return Object.values(envelope.governanceDecisions);
  }

  public savePolicySnapshot(snapshot: PolicySnapshot): boolean {
    const envelope = this.loadEnvelope() || this.createDefaultEnvelope();
    if (!envelope.policySnapshots) envelope.policySnapshots = {};
    envelope.policySnapshots[snapshot.snapshotId] = this.sanitizeForPersistence(snapshot);
    envelope.savedAt = new Date().toISOString();
    return this.saveEnvelope(envelope);
  }

  public getPolicySnapshot(snapshotId: string): PolicySnapshot | null {
    const envelope = this.loadEnvelope();
    if (!envelope || !envelope.policySnapshots) return null;
    return envelope.policySnapshots[snapshotId] || null;
  }

  public getAllPolicySnapshots(): PolicySnapshot[] {
    const envelope = this.loadEnvelope();
    if (!envelope || !envelope.policySnapshots) return [];
    return Object.values(envelope.policySnapshots);
  }

  // Stage 22: System Observability & Causal Audit Methods
  public saveOperationalAuditEvent(event: OperationalAuditEvent): boolean {
    const envelope = this.loadEnvelope() || this.createDefaultEnvelope();
    if (!envelope.auditEvents) envelope.auditEvents = {};
    envelope.auditEvents[event.eventId] = this.sanitizeForPersistence(event);
    envelope.savedAt = new Date().toISOString();
    return this.saveEnvelope(envelope);
  }

  public getOperationalAuditEvent(eventId: string): OperationalAuditEvent | null {
    const envelope = this.loadEnvelope();
    if (!envelope || !envelope.auditEvents) return null;
    return envelope.auditEvents[eventId] || null;
  }

  public getAllOperationalAuditEvents(): OperationalAuditEvent[] {
    const envelope = this.loadEnvelope();
    if (!envelope || !envelope.auditEvents) return [];
    return Object.values(envelope.auditEvents);
  }

  // ============================================================
  // Stage 23: Resilient Autonomous Operations & Recovery Persistence
  // ============================================================

  public saveRecoveryControlDecision(decision: RecoveryControlDecision): boolean {
    const envelope = this.loadEnvelope() || this.createDefaultEnvelope();
    if (!envelope.recoveryControlDecisions) envelope.recoveryControlDecisions = {};
    envelope.recoveryControlDecisions[decision.decisionId] = this.sanitizeForPersistence(decision);
    envelope.savedAt = new Date().toISOString();
    return this.saveEnvelope(envelope);
  }

  public getRecoveryControlDecision(decisionId: string): RecoveryControlDecision | null {
    const envelope = this.loadEnvelope();
    if (!envelope || !envelope.recoveryControlDecisions) return null;
    return envelope.recoveryControlDecisions[decisionId] || null;
  }

  public getAllRecoveryControlDecisions(): RecoveryControlDecision[] {
    const envelope = this.loadEnvelope();
    if (!envelope || !envelope.recoveryControlDecisions) return [];
    return Object.values(envelope.recoveryControlDecisions);
  }

  public saveRecoveryControlRequest(request: RecoveryControlRequest): boolean {
    const envelope = this.loadEnvelope() || this.createDefaultEnvelope();
    if (!envelope.recoveryControlRequests) envelope.recoveryControlRequests = {};
    envelope.recoveryControlRequests[request.requestId] = this.sanitizeForPersistence(request);
    envelope.savedAt = new Date().toISOString();
    return this.saveEnvelope(envelope);
  }

  public getRecoveryControlRequest(requestId: string): RecoveryControlRequest | null {
    const envelope = this.loadEnvelope();
    if (!envelope || !envelope.recoveryControlRequests) return null;
    return envelope.recoveryControlRequests[requestId] || null;
  }

  public getAllRecoveryControlRequests(): RecoveryControlRequest[] {
    const envelope = this.loadEnvelope();
    if (!envelope || !envelope.recoveryControlRequests) return [];
    return Object.values(envelope.recoveryControlRequests);
  }

  public saveRecoveryControlLease(lease: RecoveryControlLease): boolean {
    const envelope = this.loadEnvelope() || this.createDefaultEnvelope();
    if (!envelope.recoveryControlLeases) envelope.recoveryControlLeases = {};
    envelope.recoveryControlLeases[lease.decisionId] = this.sanitizeForPersistence(lease);
    envelope.savedAt = new Date().toISOString();
    return this.saveEnvelope(envelope);
  }

  public getRecoveryControlLease(decisionId: string): RecoveryControlLease | null {
    const envelope = this.loadEnvelope();
    if (!envelope || !envelope.recoveryControlLeases) return null;
    return envelope.recoveryControlLeases[decisionId] || null;
  }

  public deleteRecoveryControlLease(decisionId: string): boolean {
    const envelope = this.loadEnvelope();
    if (!envelope || !envelope.recoveryControlLeases) return false;
    if (envelope.recoveryControlLeases[decisionId]) {
      delete envelope.recoveryControlLeases[decisionId];
      envelope.savedAt = new Date().toISOString();
      return this.saveEnvelope(envelope);
    }
    return false;
  }

  public getAllRecoveryControlLeases(): RecoveryControlLease[] {
    const envelope = this.loadEnvelope();
    if (!envelope || !envelope.recoveryControlLeases) return [];
    return Object.values(envelope.recoveryControlLeases);
  }
}

export const executionPersistence = new ExecutionPersistence();

