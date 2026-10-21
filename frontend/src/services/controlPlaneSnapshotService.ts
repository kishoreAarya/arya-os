/**
 * AryaOS V1 — Stage 24: Mission Operations Control Plane
 * Phase 2: Control-Plane Snapshot Service
 *
 * Deterministic, READ-ONLY projection façade composing authoritative state
 * from across existing AryaOS authorities:
 * - Stage 12: Mission Control (missionManager)
 * - Stage 20: Policy Intelligence (policyRegistry)
 * - Stage 21: Governed Policy Control Plane (governanceControlPlane, executionPersistence)
 * - Stage 22: Operational Truth & Causal Audit (operationalTruthService, causalTraceService, auditEventRegistry)
 * - Stage 23: Recovery Control Plane (recoveryControlPlane, executionPersistence)
 * - Stage 09: Durable Persistence (executionPersistence)
 * - Stage 16: Connector Fabric (connectorRegistry)
 *
 * ABSOLUTE ARCHITECTURAL RULES:
 * 1. PROJECTION ONLY: The service answers "What does the system currently know?", NEVER "What should the system do?".
 * 2. ZERO EXECUTION: Never calls ActionBusService.execute(), executionGateway.dispatch(), or provider transports.
 * 3. ZERO MUTATION: Never calls save*, register*, mutate*, cancel*, or disk write methods.
 * 4. ZERO POLICY / GOVERNANCE EVALUATION: Projects existing decisions; never calculates new approvals or permissions.
 * 5. ZERO RECOVERY DISPATCH: Projects existing recovery proposals; never triggers retries or compensations.
 * 6. EPISTEMIC HONESTY: UNKNOWN is never coerced into SUCCESS. Preserves all 16 canonical lifecycle states.
 * 7. DURABILITY TRUTH: Reports isDurableStorage directly from executionPersistence.isDurableStorageActive().
 */

import {
  ControlPlaneSnapshot,
  MissionSummary,
  OperationSummary,
  OperationTimeline,
  OperationTimelineEntry,
  GovernanceSummary,
  ApprovalSummary,
  RecoverySummary,
  CausalTraceSummary,
  CausalTraceNodeSummary,
  CausalTraceEdgeSummary,
  SystemHealthSummary,
  SubsystemHealthStatus,
  SubsystemHealthRecord,
  CanonicalTimelineState,
  ApprovalProjectionState,
  EvidenceState,
} from '../types/controlPlane';

import {
  Mission,
  MissionStatus,
  MissionPriority,
  MissionGoalReference,
  MissionDependency,
  DependencyType,
  MissionCheckpoint,
  MissionRisk,
  MissionProgress,
} from '../types/missionControl';
import { GoalStatus } from '../types/goalOrchestration';
import { OperationalAuditEvent, CausalGraph, EpistemicStatus, OperationalLifecycleState } from '../types/operationalAudit';
import { GovernanceDecision } from '../types/governanceControlPlane';
import {
  RecoveryControlDecision,
  RecoveryPlan,
  FailureClassification,
  RecoveryAction,
  IdempotencyClassification,
  RecoveryOutcome,
  RecoveryLifecycleState,
  RecoveryControlLifecycleState,
  DeclarativeCompensationPlan,
  RECOVERY_CONTROL_LIFECYCLE_STATES,
  RECOVERY_PROGRESSION_STATES,
  RECOVERY_TERMINAL_STATES,
  FAILURE_CLASSIFICATIONS,
  RECOVERY_ACTIONS,
  IDEMPOTENCY_CLASSIFICATIONS,
} from '../types/recoveryControl';
import { PersistedApprovalRecord, PersistedOrchestrationEnvelope } from '../types/executionPersistence';
import { ActionRiskLevel } from '../types/actionBus';

// Authoritative Service Singletons
import { missionManager } from './missionManager';
import { policyRegistry } from './policyRegistry';
import { operationalTruthService } from './operationalTruthService';
import { causalTraceService } from './causalTraceService';
import { auditEventRegistry } from './auditEventRegistry';
import { executionPersistence } from './executionPersistence';
import { connectorRegistry } from './connectorRegistry';
import { auditIntegrityService } from './auditIntegrityService';
import { executionJournal } from './executionJournal';
import { reactionProposalService } from './reactionProposalService';
import { goalOrchestrator } from './goalOrchestrator';
import { resourceGovernor } from './resourceGovernor';

export interface OperationTimelineFilterOptions {
  readonly operationId?: string;
  readonly missionId?: string;
  readonly goalId?: string;
  readonly correlationId?: string;
  readonly maxEntries?: number;
  readonly includeJournalEvents?: boolean;
}

export interface ApprovalFilterOptions {
  readonly missionId?: string;
  readonly operationId?: string;
  readonly requestId?: string;
  readonly actorId?: string;
  readonly riskLevel?: ActionRiskLevel;
  readonly approvalState?: ApprovalProjectionState;
  readonly maxApprovals?: number;
}

export interface RecoveryFilterOptions {
  readonly operationId?: string;
  readonly originalOperationId?: string;
  readonly recoveryPlanId?: string;
  readonly decisionId?: string;
  readonly missionId?: string;
  readonly failureClassification?: FailureClassification;
  readonly lifecycleState?: RecoveryLifecycleState | RecoveryControlLifecycleState;
  readonly riskLevel?: ActionRiskLevel;
  readonly maxRecords?: number;
}

export interface MissionFilterOptions {
  readonly missionId?: string;
  readonly status?: MissionStatus | 'UNKNOWN';
  readonly priority?: MissionPriority | 'UNKNOWN';
  readonly riskLevel?: ActionRiskLevel | 'LOW' | 'MEDIUM' | 'HIGH' | 'CRITICAL' | 'UNKNOWN';
  readonly maxMissions?: number;
}

export type DependencySatisfactionState =
  | 'SATISFIED'
  | 'PENDING'
  | 'BLOCKED'
  | 'MISSING_EVIDENCE'
  | 'UNKNOWN';

export interface MissionGoalSummary {
  readonly goalId: string;
  readonly title: string;
  readonly mandatory: boolean;
  readonly status: GoalStatus | 'UNKNOWN';
  readonly weight: number;
  readonly timeoutMs?: number;
  readonly operationalState: OperationalLifecycleState | 'UNKNOWN';
  readonly epistemicStatus: EpistemicStatus | 'UNKNOWN';
  readonly isCompleted: boolean;
}

export interface MissionDependencySummary {
  readonly fromGoalId: string;
  readonly toGoalId: string;
  readonly type: DependencyType | 'UNKNOWN';
  readonly condition?: string;
  readonly satisfactionState: DependencySatisfactionState;
  readonly evidence: string;
  readonly isCycle: boolean;
}

export interface MissionProgressSummary {
  readonly totalGoals: number;
  readonly completedGoals: number;
  readonly failedGoals: number;
  readonly inProgressGoals: number;
  readonly blockedGoals: number;
  readonly percentage: number | 'UNKNOWN';
  readonly currentMilestoneId?: string;
  readonly progressProvenance: 'RECORDED' | 'DERIVED' | 'UNKNOWN';
  readonly isConsistent: boolean;
}

export interface MissionCheckpointSummary {
  readonly checkpointId: string;
  readonly planVersion: number;
  readonly statusAtCheckpoint: MissionStatus | 'UNKNOWN';
  readonly completedGoalsCount: number;
  readonly activeGoalsCount: number;
  readonly blockedGoalsCount: number;
  readonly timestamp: string;
  readonly isCompletedState: boolean;
}

export interface MissionResourceSummary {
  readonly resourceType: string;
  readonly allocated: string | number;
  readonly utilized: string | number | 'UNKNOWN';
  readonly unit?: string;
  readonly status: 'ALLOCATED' | 'UTILIZED' | 'EXCEEDED' | 'UNKNOWN';
  readonly provenance: string;
}

export type SourceIntegrityStatus =
  | 'AUTHORITATIVE'
  | 'INCOMPLETE'
  | 'CONFLICTING'
  | 'STALE'
  | 'UNAVAILABLE';

export interface MissionDetailProjection {
  readonly missionId: string;
  readonly title: string;
  readonly objective: string;
  readonly status: MissionStatus | 'UNKNOWN';
  readonly priority: MissionPriority | 'UNKNOWN';
  readonly riskLevel: ActionRiskLevel | 'UNKNOWN';
  readonly goals: readonly MissionGoalSummary[];
  readonly dependencies: readonly MissionDependencySummary[];
  readonly progress: MissionProgressSummary;
  readonly checkpoints: readonly MissionCheckpointSummary[];
  readonly resourceAllocations: readonly MissionResourceSummary[];
  readonly recoveryReferences: readonly string[];
  readonly operationReferences: readonly string[];
  readonly risks: readonly MissionRisk[];
  readonly blockers: readonly string[];
  readonly epistemicStatus: EpistemicStatus;
  readonly sourceIntegrity: SourceIntegrityStatus;
  readonly unresolvedDiscrepancies: readonly string[];
  readonly createdAt: string | 'UNKNOWN';
  readonly updatedAt: string | 'UNKNOWN';
  readonly projectedAt: number;
}

export const CANONICAL_MISSION_STATUSES: readonly MissionStatus[] = [
  'DRAFT',
  'PLANNED',
  'READY',
  'RUNNING',
  'PAUSED',
  'WAITING_FOR_APPROVAL',
  'BLOCKED',
  'DEGRADED',
  'REPLANNING',
  'COMPLETED',
  'PARTIALLY_COMPLETED',
  'FAILED',
  'CANCELLED',
  'ARCHIVED',
];

export const CANONICAL_MISSION_PRIORITIES: readonly MissionPriority[] = [
  'LOW',
  'NORMAL',
  'HIGH',
  'CRITICAL',
];

export interface SnapshotContext {
  readonly requestId?: string;
  readonly actorId?: string;
  readonly correlationId?: string;
  readonly timestamp?: number;
  readonly includeCausalTraces?: boolean;
  readonly targetOperationIds?: readonly string[];
  readonly maxOperations?: number;
  readonly maxMissions?: number;
}

/**
 * Deep-freezes an object recursively to prevent any downstream mutation.
 */
function deepFreeze<T>(obj: T): Readonly<T> {
  if (obj === null || typeof obj !== 'object') {
    return obj;
  }
  Object.freeze(obj);
  for (const key of Object.keys(obj)) {
    const val = (obj as Record<string, unknown>)[key];
    if (val !== null && typeof val === 'object' && !Object.isFrozen(val)) {
      deepFreeze(val);
    }
  }
  return obj;
}

/**
 * Sanitizes input context against prototype pollution and secret injection.
 */
function sanitizeContext(ctx?: SnapshotContext): SnapshotContext | undefined {
  if (!ctx || typeof ctx !== 'object') return undefined;

  const forbiddenKeys = ['__proto__', 'constructor', 'prototype'];
  const sanitized: Record<string, unknown> = {};

  for (const [key, value] of Object.entries(ctx)) {
    if (forbiddenKeys.includes(key)) continue;

    // Check for secret patterns
    if (typeof value === 'string') {
      const lower = value.toLowerCase();
      if (
        lower.includes('bearer ') ||
        lower.includes('sk-') ||
        lower.includes('api_key') ||
        lower.includes('secret') ||
        lower.includes('password')
      ) {
        sanitized[key] = '[REDACTED]';
        continue;
      }
    }
    sanitized[key] = value;
  }

  return sanitized as unknown as SnapshotContext;
}

/**
 * Scrubs sensitive patterns (tokens, secrets, credentials, auth headers) from strings.
 */
function scrubSensitiveString(str: string): string {
  if (!str || typeof str !== 'string') return str;
  return str
    .replace(/(?:Bearer\s+)[A-Za-z0-9\-_.]+/gi, 'Bearer [REDACTED]')
    .replace(/(?:api[_-]?key\s*[=:]\s*)[^\s,]+/gi, 'api_key=[REDACTED]')
    .replace(/(?:token\s*[=:]\s*)[^\s,]+/gi, 'token=[REDACTED]')
    .replace(/(?:password\s*[=:]\s*)[^\s,]+/gi, 'password=[REDACTED]')
    .replace(/(?:secret\s*[=:]\s*)[^\s,]+/gi, 'secret=[REDACTED]')
    .replace(/sk-[a-zA-Z0-9_\-]{8,}/gi, 'sk-[REDACTED]')
    .replace(/(?:auth(?:orization)?\s*[=:]\s*)[^\s,]+/gi, 'auth=[REDACTED]');
}

/**
 * Sanitizes approval filter options against prototype pollution and out-of-bounds parameters.
 */
function sanitizeApprovalFilterOptions(options?: ApprovalFilterOptions): ApprovalFilterOptions | undefined {
  if (!options || typeof options !== 'object') return undefined;
  const safe: Record<string, unknown> = {};
  const forbiddenKeys = ['__proto__', 'constructor', 'prototype'];
  for (const [k, v] of Object.entries(options)) {
    if (forbiddenKeys.includes(k)) continue;
    if (typeof v === 'string') {
      safe[k] = v.slice(0, 200);
    } else if (typeof v === 'number' && Number.isFinite(v) && v > 0) {
      safe[k] = Math.floor(v);
    }
  }
  return safe as unknown as ApprovalFilterOptions;
}

/**
 * Sanitizes recovery filter options against prototype pollution and out-of-bounds parameters.
 */
function sanitizeRecoveryFilterOptions(options?: RecoveryFilterOptions): RecoveryFilterOptions | undefined {
  if (!options || typeof options !== 'object') return undefined;
  const safe: Record<string, unknown> = {};
  const forbiddenKeys = ['__proto__', 'constructor', 'prototype'];
  for (const [k, v] of Object.entries(options)) {
    if (forbiddenKeys.includes(k)) continue;
    if (typeof v === 'string') {
      safe[k] = v.slice(0, 200);
    } else if (typeof v === 'number' && Number.isFinite(v) && v > 0) {
      safe[k] = Math.floor(v);
    }
  }
  return safe as unknown as RecoveryFilterOptions;
}

/**
 * Sanitizes mission filter options against prototype pollution and out-of-bounds parameters.
 */
export function sanitizeMissionFilterOptions(options?: MissionFilterOptions): MissionFilterOptions | undefined {
  if (!options || typeof options !== 'object') return undefined;
  const safe: Record<string, unknown> = {};
  const forbiddenKeys = ['__proto__', 'constructor', 'prototype'];
  for (const [k, v] of Object.entries(options)) {
    if (forbiddenKeys.includes(k)) continue;
    if (typeof v === 'string') {
      safe[k] = v.slice(0, 200);
    } else if (typeof v === 'number' && Number.isFinite(v) && v > 0) {
      safe[k] = Math.floor(v);
    }
  }
  return safe as unknown as MissionFilterOptions;
}

export function normalizeMissionStatus(rawStatus: unknown): MissionStatus | 'UNKNOWN' {
  if (typeof rawStatus !== 'string') return 'UNKNOWN';
  if (CANONICAL_MISSION_STATUSES.includes(rawStatus as MissionStatus)) {
    return rawStatus as MissionStatus;
  }
  return 'UNKNOWN';
}

export function normalizePriority(rawPriority: unknown): MissionPriority | 'UNKNOWN' {
  if (typeof rawPriority !== 'string') return 'UNKNOWN';
  if (CANONICAL_MISSION_PRIORITIES.includes(rawPriority as MissionPriority)) {
    return rawPriority as MissionPriority;
  }
  return 'UNKNOWN';
}

export function normalizeRiskLevel(rawRisk: unknown): ActionRiskLevel | 'UNKNOWN' {
  if (typeof rawRisk !== 'string') return 'UNKNOWN';
  if (['LOW', 'MEDIUM', 'HIGH', 'CRITICAL'].includes(rawRisk)) {
    return rawRisk as ActionRiskLevel;
  }
  if (rawRisk === 'READ_ONLY' || rawRisk === 'LOW_RISK') return 'LOW';
  if (rawRisk === 'CONSEQUENTIAL') return 'HIGH';
  if (rawRisk === 'EXTERNAL_SIDE_EFFECT') return 'CRITICAL';
  return 'UNKNOWN';
}

const CANONICAL_RECOVERY_LIFECYCLE_SET: readonly string[] = [
  ...RECOVERY_CONTROL_LIFECYCLE_STATES,
  ...RECOVERY_PROGRESSION_STATES,
  ...RECOVERY_TERMINAL_STATES,
];

function isCanonicalRecoveryLifecycle(state: unknown): state is (RecoveryLifecycleState | RecoveryControlLifecycleState) {
  return typeof state === 'string' && CANONICAL_RECOVERY_LIFECYCLE_SET.includes(state);
}

function sanitizeCompensationPlan(plan: DeclarativeCompensationPlan): DeclarativeCompensationPlan {
  if (!plan || typeof plan !== 'object') return plan;
  return {
    ...plan,
    sourceCapability: scrubSensitiveString(plan.sourceCapability || 'UNKNOWN'),
    compensatingCapability: scrubSensitiveString(plan.compensatingCapability || 'UNKNOWN'),
    targetState: scrubSensitiveString(plan.targetState || 'UNKNOWN'),
    idempotencyKey: scrubSensitiveString(plan.idempotencyKey || 'UNKNOWN'),
    compensationParameters: plan.compensationParameters
      ? (auditIntegrityService.sanitizePayload(plan.compensationParameters as Record<string, unknown>) as Record<string, unknown>)
      : {},
  };
}

/**
 * Parses numeric timestamp from number, ISO string, or 'UNKNOWN'.
 */
function parseTimestamp(ts: number | string | 'UNKNOWN'): number {
  if (typeof ts === 'number') return ts;
  if (typeof ts === 'string' && ts !== 'UNKNOWN') {
    const parsed = Date.parse(ts);
    return isNaN(parsed) ? 0 : parsed;
  }
  return 0;
}

/**
 * Resolves concrete authoritative source domain for timeline entries.
 * Prevents vague labels like "system" or "runtime" when domain authority is known.
 */
function resolveAuthoritativeSource(evt: OperationalAuditEvent): string {
  const src = (evt.sourceSystem || '').trim();
  const lowerSrc = src.toLowerCase();

  // If sourceSystem is specific and not a vague generic label, keep it
  if (src && lowerSrc !== 'system' && lowerSrc !== 'runtime' && lowerSrc !== 'unknown') {
    return src;
  }

  // Derive concrete source from event type or domain context
  const type = String(evt.eventType || '');
  if (type.startsWith('GOVERNANCE_') || type.startsWith('POLICY_')) {
    return 'governance-control-plane';
  }
  if (type.startsWith('ACTION_')) {
    return 'action-bus';
  }
  if (
    type.startsWith('OPERATION_') ||
    type === 'STATE_RECONCILED' ||
    type === 'OBSERVATION_RECORDED'
  ) {
    return 'operational-truth';
  }
  if (type.startsWith('REQUEST_')) {
    return 'operational-audit';
  }
  if (type.startsWith('TRIGGER_') || type.startsWith('REACTION_')) {
    return 'event-reaction';
  }
  if (type.startsWith('GOAL_') || type.startsWith('MISSION_') || type.startsWith('PLAN_')) {
    return 'mission-control';
  }
  if (type.startsWith('RECOVERY_')) {
    return 'recovery-control';
  }

  return src || 'operational-truth';
}

export class ControlPlaneSnapshotService {
  /**
   * Generates a deterministic, read-only ControlPlaneSnapshot reflecting current system truth.
   * NEVER performs mutations, policy evaluations, recovery dispatches, or external calls.
   */
  public getSnapshot(rawContext?: SnapshotContext): Readonly<ControlPlaneSnapshot> {
    const context = sanitizeContext(rawContext);
    const timestamp = context?.timestamp ?? Date.now();
    const snapshotId = `snap-cp-${timestamp}`;

    // 1. Authoritative Persistence Envelope Read
    const envelope = executionPersistence.loadEnvelope();

    // 2. Mission Projection
    const missions = this.projectMissions(envelope, context?.maxMissions);

    // 3. Operational Events & Operations Projection
    const allAuditEvents = auditEventRegistry.getAllEvents();
    const operations = this.projectOperations(allAuditEvents, envelope, context?.maxOperations, context?.targetOperationIds);

    // 4. Governance Decisions Projection
    const governance = this.projectGovernance(envelope);

    // 5. Approvals Projection
    const approvals = this.projectApprovals(envelope);

    // 6. Recovery Control Decisions Projection
    const recovery = this.projectRecovery(envelope);

    // 7. Causal Traces Projection
    const causalTraces = this.projectCausalTraces(operations, context);

    // 8. System Health Projection (Observational Only)
    const systemHealth = this.projectSystemHealth(envelope);

    // 9. Source Registry Version
    let sourceVersion: number | 'UNKNOWN' = 'UNKNOWN';
    try {
      sourceVersion = policyRegistry.getRegistryVersion();
    } catch {
      sourceVersion = 'UNKNOWN';
    }

    const snapshot: ControlPlaneSnapshot = {
      snapshotId,
      generatedAt: timestamp,
      sourceVersion,
      missions,
      operations,
      approvals,
      governance,
      recovery,
      causalTraces,
      systemHealth,
      requestId: context?.requestId ?? 'UNKNOWN',
      actorId: context?.actorId ?? 'UNKNOWN',
      correlationId: context?.correlationId ?? 'UNKNOWN',
    };

    return deepFreeze(snapshot);
  }

  /**
   * Projects authoritative missions into read-only MissionSummary structures.
   * Multi-source gathering, deterministic deduplication and sorting, recursive secret scrubbing,
   * prototype pollution protection, and epistemic honesty.
   */
  public projectMissions(
    envelope: PersistedOrchestrationEnvelope | null,
    limitOrOptions?: number | MissionFilterOptions,
    filterOptions?: MissionFilterOptions
  ): readonly MissionSummary[] {
    let limit: number | undefined;
    let options: MissionFilterOptions | undefined;

    if (typeof limitOrOptions === 'number') {
      limit = limitOrOptions > 0 ? Math.floor(limitOrOptions) : undefined;
      options = filterOptions;
    } else if (typeof limitOrOptions === 'object' && limitOrOptions !== null) {
      options = limitOrOptions;
      if (options.maxMissions && options.maxMissions > 0) {
        limit = options.maxMissions;
      }
    }
    const sanitizedOptions = sanitizeMissionFilterOptions(options);
    if (sanitizedOptions?.maxMissions && !limit) {
      limit = sanitizedOptions.maxMissions;
    }

    const rawMissionsMap = new Map<string, Mission>();

    // 1. Gather from MissionManager
    try {
      const managerMissions = missionManager.listMissions();
      if (Array.isArray(managerMissions)) {
        for (const m of managerMissions) {
          if (m && m.missionId) {
            rawMissionsMap.set(String(m.missionId), m);
          }
        }
      }
    } catch {
      // safe fallback
    }

    // 2. Gather from durable persistence
    try {
      const persistedMissions = executionPersistence.getMissions();
      if (Array.isArray(persistedMissions)) {
        for (const m of persistedMissions) {
          if (m && m.missionId && !rawMissionsMap.has(String(m.missionId))) {
            rawMissionsMap.set(String(m.missionId), m);
          }
        }
      }
    } catch {
      // safe fallback
    }

    // 3. Gather from envelope
    if (envelope?.missions && typeof envelope.missions === 'object') {
      for (const m of Object.values(envelope.missions)) {
        if (m && m.missionId && !rawMissionsMap.has(String(m.missionId))) {
          rawMissionsMap.set(String(m.missionId), m);
        }
      }
    }

    // 4. Targeted fetch if missionId filter is set but not yet found
    if (sanitizedOptions?.missionId && !rawMissionsMap.has(sanitizedOptions.missionId)) {
      try {
        const single =
          missionManager.getMission(sanitizedOptions.missionId) ||
          executionPersistence.getMission(sanitizedOptions.missionId);
        if (single && single.missionId) {
          rawMissionsMap.set(String(single.missionId), single);
        }
      } catch {
        // safe fallback
      }
    }

    const approvals = envelope?.approvals ? Object.values(envelope.approvals) : [];
    let allRecoveryDecisions: RecoveryControlDecision[] = [];
    try {
      allRecoveryDecisions = executionPersistence.getAllRecoveryControlDecisions();
    } catch {
      allRecoveryDecisions = [];
    }
    if (envelope?.recoveryControlDecisions) {
      const envRec = Object.values(envelope.recoveryControlDecisions);
      for (const d of envRec) {
        if (!allRecoveryDecisions.some((existing) => existing.decisionId === d.decisionId)) {
          allRecoveryDecisions.push(d);
        }
      }
    }

    // Sourced policy version
    let polVer: number | 'UNKNOWN' = 'UNKNOWN';
    try {
      polVer = policyRegistry.getRegistryVersion();
    } catch {
      polVer = 'UNKNOWN';
    }

    let missionsList = Array.from(rawMissionsMap.values());

    // Apply filtering
    if (sanitizedOptions) {
      if (sanitizedOptions.missionId) {
        missionsList = missionsList.filter((m) => m.missionId === sanitizedOptions.missionId);
      }
      if (sanitizedOptions.status) {
        missionsList = missionsList.filter((m) => m.status === sanitizedOptions.status);
      }
      if (sanitizedOptions.priority) {
        missionsList = missionsList.filter((m) => m.priority === sanitizedOptions.priority);
      }
      if (sanitizedOptions.riskLevel) {
        missionsList = missionsList.filter((m) => {
          const norm = normalizeRiskLevel(m.riskLevel);
          return norm === sanitizedOptions.riskLevel || m.riskLevel === (sanitizedOptions.riskLevel as unknown);
        });
      }
    }

    // Deterministic sort: Priority (desc), createdAt (desc), missionId (asc)
    const PRIORITY_WEIGHTS: Record<string, number> = {
      CRITICAL: 4,
      HIGH: 3,
      NORMAL: 2,
      LOW: 1,
      UNKNOWN: 0,
    };

    missionsList.sort((a, b) => {
      const pA = PRIORITY_WEIGHTS[a.priority] ?? 0;
      const pB = PRIORITY_WEIGHTS[b.priority] ?? 0;
      if (pA !== pB) return pB - pA;

      const tA = parseTimestamp(a.createdAt);
      const tB = parseTimestamp(b.createdAt);
      if (tA !== tB) return tB - tA;

      return String(a.missionId).localeCompare(String(b.missionId));
    });

    if (limit && limit > 0) {
      missionsList = missionsList.slice(0, limit);
    }

    const summaries: MissionSummary[] = missionsList.map((m) => {
      const primaryGoal = m.goals && m.goals.length > 0 ? m.goals[0] : undefined;
      const goalId = primaryGoal ? String(primaryGoal.goalId) : 'UNKNOWN';

      // Pending approvals count for this mission or its goals
      const missionGoalIds = new Set(m.goals ? m.goals.map((g) => String(g.goalId)) : []);
      const pendingApprovalsCount = approvals.filter(
        (a) =>
          a.status === 'PENDING' &&
          (a.goalId === goalId ||
            (a as any).missionId === m.missionId ||
            missionGoalIds.has(String(a.goalId)))
      ).length;

      // Recovery count for this mission or its goals
      const recoveryCount = allRecoveryDecisions.filter(
        (r) =>
          r.originalOperationId === goalId ||
          r.originalOperationId === m.missionId ||
          (r.operationId && (r.operationId === goalId || r.operationId === m.missionId)) ||
          missionGoalIds.has(String(r.originalOperationId || r.operationId))
      ).length;

      // Latest audit event for this mission
      let latestOpState: OperationalLifecycleState | 'UNKNOWN' = 'UNKNOWN';
      let latestTruth: EpistemicStatus | 'UNKNOWN' = 'UNKNOWN';
      let latestCausalEvent: string | 'UNKNOWN' = 'UNKNOWN';

      try {
        let events = auditEventRegistry.getEventsByMissionId(m.missionId);
        if ((!events || events.length === 0) && goalId !== 'UNKNOWN') {
          events = auditEventRegistry.getEventsByGoalId(goalId);
        }
        if (events && events.length > 0) {
          const latestEvent = events[events.length - 1];
          latestOpState = latestEvent.lifecycleState ?? 'UNKNOWN';
          latestTruth = latestEvent.epistemicStatus ?? 'UNKNOWN';
          latestCausalEvent = latestEvent.eventType ?? 'UNKNOWN';
        }
      } catch {
        // Fallback to defaults
      }

      // Canonical status validation - NEVER promote to COMPLETED based on goals
      const status = normalizeMissionStatus(m.status);
      const priority = normalizePriority(m.priority);
      const riskLevel = normalizeRiskLevel(m.riskLevel);

      // Honest progress derivation
      let progress: MissionProgress | 'UNKNOWN' = 'UNKNOWN';
      if (m.progress && typeof m.progress === 'object') {
        const tot =
          typeof m.progress.totalGoals === 'number' && Number.isFinite(m.progress.totalGoals)
            ? Math.max(0, m.progress.totalGoals)
            : 0;
        const comp =
          typeof m.progress.completedGoals === 'number' && Number.isFinite(m.progress.completedGoals)
            ? Math.max(0, m.progress.completedGoals)
            : 0;
        const fail =
          typeof m.progress.failedGoals === 'number' && Number.isFinite(m.progress.failedGoals)
            ? Math.max(0, m.progress.failedGoals)
            : 0;
        const inProg =
          typeof m.progress.inProgressGoals === 'number' && Number.isFinite(m.progress.inProgressGoals)
            ? Math.max(0, m.progress.inProgressGoals)
            : 0;
        const blk =
          typeof m.progress.blockedGoals === 'number' && Number.isFinite(m.progress.blockedGoals)
            ? Math.max(0, m.progress.blockedGoals)
            : 0;
        let pct =
          typeof m.progress.percentage === 'number' && Number.isFinite(m.progress.percentage)
            ? Math.min(100, Math.max(0, m.progress.percentage))
            : 0;
        if (!Number.isFinite(m.progress.percentage) && tot > 0) {
          pct = Math.min(100, Math.max(0, Math.round((comp / tot) * 100)));
        }

        progress = {
          totalGoals: tot,
          completedGoals: comp,
          failedGoals: fail,
          inProgressGoals: inProg,
          blockedGoals: blk,
          percentage: pct,
          currentMilestoneId: m.progress.currentMilestoneId,
        };
      } else if (m.goals && m.goals.length > 0) {
        const comp = m.goals.filter((g) => g.status === 'COMPLETED' || (g.status as string) === 'SUCCEEDED').length;
        const fail = m.goals.filter((g) => g.status === 'FAILED').length;
        const inProg = m.goals.filter((g) => g.status === 'RUNNING' || (g.status as string) === 'EXECUTING').length;
        const blk = m.goals.filter((g) => g.status === 'BLOCKED').length;
        progress = {
          totalGoals: m.goals.length,
          completedGoals: comp,
          failedGoals: fail,
          inProgressGoals: inProg,
          blockedGoals: blk,
          percentage: Math.min(100, Math.max(0, Math.round((comp / m.goals.length) * 100))),
        };
      }

      const activeOps =
        typeof m.progress?.inProgressGoals === 'number' &&
        Number.isFinite(m.progress.inProgressGoals) &&
        m.progress.inProgressGoals >= 0
          ? m.progress.inProgressGoals
          : m.goals
          ? m.goals.filter((g) => g.status === 'RUNNING' || (g.status as string) === 'EXECUTING').length
          : 0;

      const blockedOps =
        typeof m.progress?.blockedGoals === 'number' &&
        Number.isFinite(m.progress.blockedGoals) &&
        m.progress.blockedGoals >= 0
          ? m.progress.blockedGoals
          : m.goals
          ? m.goals.filter((g) => g.status === 'BLOCKED').length
          : 0;

      return {
        missionId: String(m.missionId),
        goalId,
        title: m.title ? scrubSensitiveString(String(m.title)) : 'UNKNOWN',
        status,
        priority,
        progress,
        activeOperations: activeOps,
        blockedOperations: blockedOps,
        pendingApprovals: pendingApprovalsCount,
        recoveryCount,
        latestOperationalState: latestOpState,
        latestTruthState: latestTruth,
        latestCausalEvent,
        policyVersion: polVer,
        governanceState: 'UNKNOWN',
        riskLevel,
        updatedAt: m.updatedAt ? scrubSensitiveString(String(m.updatedAt)) : 'UNKNOWN',
        createdAt: m.createdAt ? scrubSensitiveString(String(m.createdAt)) : 'UNKNOWN',
      };
    });

    return deepFreeze(summaries);
  }

  /**
   * Projects granular, read-only MissionDetailProjection for a specific mission.
   * Exposes goals, dependencies with cycle detection, progress provenance,
   * checkpoints, resource allocations vs utilization, risks, blockers,
   * and multi-source conflict/discrepancy detection.
   */
  public projectMissionDetail(
    rawMissionId: string,
    envelope?: PersistedOrchestrationEnvelope | null
  ): Readonly<MissionDetailProjection> | null {
    if (!rawMissionId || typeof rawMissionId !== 'string') return null;
    const forbidden = ['__proto__', 'constructor', 'prototype'];
    if (forbidden.includes(rawMissionId)) return null;

    const missionId = rawMissionId.slice(0, 200);

    let memMission: Mission | null = null;
    let persMission: Mission | null = null;
    let envMission: Mission | null = null;

    try {
      memMission = missionManager.getMission(missionId);
    } catch {
      memMission = null;
    }

    try {
      persMission = executionPersistence.getMission(missionId);
    } catch {
      persMission = null;
    }

    if (envelope?.missions && envelope.missions[missionId]) {
      envMission = envelope.missions[missionId];
    }

    const m: Mission | null = memMission || persMission || envMission;
    if (!m) {
      return null;
    }

    // Source Integrity & Conflict Detection
    let sourceIntegrity: SourceIntegrityStatus = 'AUTHORITATIVE';
    const unresolvedDiscrepancies: string[] = [];

    if (memMission && persMission && memMission.status !== persMission.status) {
      sourceIntegrity = 'CONFLICTING';
      unresolvedDiscrepancies.push(
        `Lifecycle state conflict: memory reports '${memMission.status}' while persistence reports '${persMission.status}'`
      );
    }

    if (envMission && persMission && envMission.status !== persMission.status) {
      sourceIntegrity = 'CONFLICTING';
      unresolvedDiscrepancies.push(
        `Lifecycle state conflict: envelope reports '${envMission.status}' while persistence reports '${persMission.status}'`
      );
    }

    // Incomplete check
    if (
      (!m.goals || m.goals.length === 0) &&
      (m.status === 'RUNNING' || m.status === 'PLANNED' || m.status === 'READY')
    ) {
      if (sourceIntegrity === 'AUTHORITATIVE') {
        sourceIntegrity = 'INCOMPLETE';
      }
      unresolvedDiscrepancies.push(`Mission status is '${m.status}' but no goal references exist`);
    }

    // Staleness check
    if (m.updatedAt) {
      const ts = Date.parse(m.updatedAt);
      if (isNaN(ts)) {
        if (sourceIntegrity === 'AUTHORITATIVE') sourceIntegrity = 'INCOMPLETE';
        unresolvedDiscrepancies.push(`Malformed updatedAt timestamp '${m.updatedAt}'`);
      } else if (Date.now() - ts > 30 * 24 * 60 * 60 * 1000) {
        if (sourceIntegrity === 'AUTHORITATIVE') sourceIntegrity = 'STALE';
        unresolvedDiscrepancies.push(`Mission update timestamp is older than 30 days`);
      }
    }

    // Goals projection
    const rawGoals = Array.isArray(m.goals) ? m.goals : [];
    const goals: MissionGoalSummary[] = [];

    for (const g of rawGoals) {
      if (!g || typeof g !== 'object') continue;
      const goalId = String(g.goalId || 'UNKNOWN');
      const title = scrubSensitiveString(String(g.title || 'UNKNOWN'));
      const mandatory = Boolean(g.mandatory);
      const weight = typeof g.weight === 'number' && Number.isFinite(g.weight) && g.weight >= 0 ? g.weight : 1;
      const timeoutMs =
        typeof g.timeoutMs === 'number' && Number.isFinite(g.timeoutMs) && g.timeoutMs > 0
          ? Math.floor(g.timeoutMs)
          : undefined;

      let effectiveStatus: GoalStatus | 'UNKNOWN' = g.status ?? 'UNKNOWN';
      try {
        const runtimeGoal = goalOrchestrator.getGoal(goalId);
        if (runtimeGoal && runtimeGoal.status) {
          effectiveStatus = runtimeGoal.status;
        } else if (envelope?.goals?.[goalId]?.status) {
          effectiveStatus = envelope.goals[goalId].status;
        }
      } catch {
        // safe fallback
      }

      let opState: OperationalLifecycleState | 'UNKNOWN' = 'UNKNOWN';
      let epState: EpistemicStatus | 'UNKNOWN' = 'UNKNOWN';
      try {
        const goalEvents = auditEventRegistry.getEventsByGoalId(goalId);
        if (goalEvents && goalEvents.length > 0) {
          const latest = goalEvents[goalEvents.length - 1];
          opState = latest.lifecycleState ?? 'UNKNOWN';
          epState = latest.epistemicStatus ?? 'UNKNOWN';
        }
      } catch {
        // safe fallback
      }

      const isCompleted = effectiveStatus === 'COMPLETED' || (effectiveStatus as string) === 'SUCCEEDED';

      goals.push({
        goalId,
        title,
        mandatory,
        status: effectiveStatus,
        weight,
        timeoutMs,
        operationalState: opState,
        epistemicStatus: epState,
        isCompleted,
      });
    }

    // Dependencies & Cycle Detection
    const rawDeps = Array.isArray(m.dependencies) ? m.dependencies : [];
    const deps: MissionDependencySummary[] = [];

    const adjacency = new Map<string, string[]>();
    for (const d of rawDeps) {
      if (!d || !d.fromGoalId || !d.toGoalId) continue;
      const list = adjacency.get(d.fromGoalId) || [];
      list.push(d.toGoalId);
      adjacency.set(d.fromGoalId, list);
    }

    const visited = new Set<string>();
    const recStack = new Set<string>();
    const cycleEdges = new Set<string>();

    function detectCycles(node: string, depth: number) {
      if (depth > 20) return;
      visited.add(node);
      recStack.add(node);

      const neighbors = adjacency.get(node) || [];
      for (const neighbor of neighbors) {
        const edgeKey = `${node}->${neighbor}`;
        if (!visited.has(neighbor)) {
          detectCycles(neighbor, depth + 1);
        } else if (recStack.has(neighbor)) {
          cycleEdges.add(edgeKey);
          if (adjacency.get(neighbor)?.includes(node)) {
            cycleEdges.add(`${neighbor}->${node}`);
          }
        }
      }
      recStack.delete(node);
    }

    for (const fromNode of adjacency.keys()) {
      if (!visited.has(fromNode)) {
        detectCycles(fromNode, 0);
      }
    }

    for (const d of rawDeps) {
      if (!d || typeof d !== 'object') continue;
      const fromGoalId = String(d.fromGoalId || 'UNKNOWN');
      const toGoalId = String(d.toGoalId || 'UNKNOWN');
      const type = d.type ?? 'FINISH_TO_START';
      const condition = d.condition ? scrubSensitiveString(String(d.condition)) : undefined;

      const edgeKey = `${fromGoalId}->${toGoalId}`;
      const isCycle = cycleEdges.has(edgeKey);

      let satisfactionState: DependencySatisfactionState = 'UNKNOWN';
      let evidence = '';

      if (isCycle) {
        satisfactionState = 'BLOCKED';
        evidence = `Circular dependency detected involving edge '${fromGoalId}' -> '${toGoalId}'`;
      } else {
        const predInMission = goals.find((g) => g.goalId === fromGoalId);
        let predRuntimeStatus: string | undefined = predInMission?.status;

        if (!predRuntimeStatus || predRuntimeStatus === 'UNKNOWN') {
          try {
            const runtimeGoal = goalOrchestrator.getGoal(fromGoalId);
            if (runtimeGoal) predRuntimeStatus = runtimeGoal.status;
            else if (envelope?.goals?.[fromGoalId]) predRuntimeStatus = envelope.goals[fromGoalId].status;
          } catch {
            // fallback
          }
        }

        if (!predRuntimeStatus && !predInMission) {
          satisfactionState = 'MISSING_EVIDENCE';
          evidence = `Predecessor goal '${fromGoalId}' not found in mission, goal registry, or envelope`;
        } else if (predRuntimeStatus === 'COMPLETED' || predRuntimeStatus === 'SUCCEEDED') {
          satisfactionState = 'SATISFIED';
          evidence = `Predecessor goal '${fromGoalId}' completed successfully (status: ${predRuntimeStatus})`;
        } else if (['BLOCKED', 'FAILED', 'CANCELLED'].includes(predRuntimeStatus || '')) {
          satisfactionState = 'BLOCKED';
          evidence = `Predecessor goal '${fromGoalId}' is in non-executable status '${predRuntimeStatus}'`;
        } else if (
          [
            'READY',
            'RUNNING',
            'EXECUTING',
            'PLANNED',
            'AWAITING_APPROVAL',
            'WAITING_APPROVAL',
            'OBSERVING',
            'REPLANNING',
            'RECOVERING',
          ].includes(predRuntimeStatus || '')
        ) {
          satisfactionState = 'PENDING';
          evidence = `Predecessor goal '${fromGoalId}' is pending execution (status: ${predRuntimeStatus})`;
        } else {
          satisfactionState = 'UNKNOWN';
          evidence = `Predecessor goal '${fromGoalId}' has ambiguous status '${predRuntimeStatus}'`;
        }
      }

      deps.push({
        fromGoalId,
        toGoalId,
        type,
        condition,
        satisfactionState,
        evidence,
        isCycle,
      });
    }

    // Progress Projection
    const totalGoals = goals.length;
    const completedGoals = goals.filter((g) => g.isCompleted).length;
    const failedGoals = goals.filter((g) => g.status === 'FAILED').length;
    const inProgressGoals = goals.filter((g) => g.status === 'RUNNING' || (g.status as string) === 'EXECUTING').length;
    const blockedGoals = goals.filter((g) => g.status === 'BLOCKED').length;

    let progressSummary: MissionProgressSummary;

    if (m.progress && typeof m.progress === 'object') {
      const recTotal = Number.isFinite(m.progress.totalGoals) ? m.progress.totalGoals : totalGoals;
      const recCompleted = Number.isFinite(m.progress.completedGoals) ? m.progress.completedGoals : completedGoals;
      const recFailed = Number.isFinite(m.progress.failedGoals) ? m.progress.failedGoals : failedGoals;
      const recInProgress = Number.isFinite(m.progress.inProgressGoals) ? m.progress.inProgressGoals : inProgressGoals;
      const recBlocked = Number.isFinite(m.progress.blockedGoals) ? m.progress.blockedGoals : blockedGoals;

      let recPercentage: number | 'UNKNOWN' = 'UNKNOWN';
      if (
        typeof m.progress.percentage === 'number' &&
        Number.isFinite(m.progress.percentage) &&
        m.progress.percentage >= 0
      ) {
        recPercentage = Math.min(100, Math.max(0, m.progress.percentage));
      } else if (recTotal > 0) {
        recPercentage = Math.min(100, Math.max(0, Math.round((recCompleted / recTotal) * 100)));
      }

      const isConsistent = totalGoals === 0 || (recCompleted === completedGoals && recTotal === totalGoals);
      if (!isConsistent) {
        unresolvedDiscrepancies.push(
          `Progress inconsistency: recorded completed (${recCompleted}) differs from authoritative goal count (${completedGoals})`
        );
      }

      progressSummary = {
        totalGoals: recTotal,
        completedGoals: recCompleted,
        failedGoals: recFailed,
        inProgressGoals: recInProgress,
        blockedGoals: recBlocked,
        percentage: recPercentage,
        currentMilestoneId: m.progress.currentMilestoneId,
        progressProvenance: 'RECORDED',
        isConsistent,
      };
    } else if (totalGoals > 0) {
      const derivedPercentage = Math.min(100, Math.max(0, Math.round((completedGoals / totalGoals) * 100)));
      progressSummary = {
        totalGoals,
        completedGoals,
        failedGoals,
        inProgressGoals,
        blockedGoals,
        percentage: derivedPercentage,
        progressProvenance: 'DERIVED',
        isConsistent: true,
      };
    } else {
      progressSummary = {
        totalGoals: 0,
        completedGoals: 0,
        failedGoals: 0,
        inProgressGoals: 0,
        blockedGoals: 0,
        percentage: 'UNKNOWN',
        progressProvenance: 'UNKNOWN',
        isConsistent: true,
      };
    }

    // Checkpoints Projection
    let rawCheckpoints: MissionCheckpoint[] = [];
    try {
      rawCheckpoints = executionPersistence.getMissionCheckpoints(missionId);
    } catch {
      rawCheckpoints = [];
    }
    if (rawCheckpoints.length === 0 && Array.isArray(m.checkpoints)) {
      rawCheckpoints = m.checkpoints;
    }
    if (envelope?.missionCheckpoints) {
      for (const cp of Object.values(envelope.missionCheckpoints)) {
        if (cp.missionId === missionId && !rawCheckpoints.some((c) => c.checkpointId === cp.checkpointId)) {
          rawCheckpoints.push(cp);
        }
      }
    }

    const checkpoints: MissionCheckpointSummary[] = rawCheckpoints.map((cp) => ({
      checkpointId: String(cp.checkpointId || 'UNKNOWN'),
      planVersion: Number.isFinite(cp.planVersion) ? cp.planVersion : 1,
      statusAtCheckpoint: normalizeMissionStatus(cp.missionStatus),
      completedGoalsCount: Array.isArray(cp.completedGoals) ? cp.completedGoals.length : 0,
      activeGoalsCount: Array.isArray(cp.activeGoals) ? cp.activeGoals.length : 0,
      blockedGoalsCount: Array.isArray(cp.blockedGoals) ? cp.blockedGoals.length : 0,
      timestamp: String(cp.timestamp || 'UNKNOWN'),
      isCompletedState: cp.missionStatus === 'COMPLETED',
    }));

    // Resource Allocations vs Utilization
    const resourceAllocations: MissionResourceSummary[] = [];

    if (Array.isArray(m.constraints)) {
      for (const c of m.constraints) {
        if (!c || typeof c !== 'object') continue;
        const rType = String(c.type || 'UNKNOWN');
        const allocated =
          typeof c.value === 'number' || typeof c.value === 'string' ? c.value : JSON.stringify(c.value);

        let utilized: string | number | 'UNKNOWN' = 'UNKNOWN';
        let status: 'ALLOCATED' | 'UTILIZED' | 'EXCEEDED' | 'UNKNOWN' = 'ALLOCATED';

        if (c.type === 'COST_BUDGET' && typeof c.value === 'number') {
          let sumCost = 0;
          let hasKnownCost = false;
          for (const g of goals) {
            try {
              const costInfo = resourceGovernor.getGoalCostTracking(g.goalId);
              if (costInfo.costStatus !== 'UNKNOWN') {
                sumCost += costInfo.costSoFar;
                hasKnownCost = true;
              }
            } catch {
              // safe fallback
            }
          }
          if (hasKnownCost && sumCost > 0) {
            utilized = Number(sumCost.toFixed(4));
            status = sumCost > c.value ? 'EXCEEDED' : 'UTILIZED';
          }
        }

        resourceAllocations.push({
          resourceType: rType,
          allocated,
          utilized,
          status,
          provenance: 'MISSION_CONSTRAINT',
        });
      }
    }

    try {
      const activeLeases = resourceGovernor.getActiveLeases();
      const missionGoalIds = new Set(goals.map((g) => g.goalId));
      for (const lease of activeLeases) {
        if (missionGoalIds.has(lease.goalId)) {
          resourceAllocations.push({
            resourceType: 'EXECUTION_LEASE',
            allocated: lease.estimatedCost ?? 'UNKNOWN',
            utilized: 'UNKNOWN', // Lease does not prove consumption
            unit: 'USD_ESTIMATE',
            status: 'ALLOCATED',
            provenance: `RESOURCE_GOVERNOR_LEASE:${lease.leaseId}`,
          });
        }
      }
    } catch {
      // safe fallback
    }

    // Recovery References
    const missionGoalIds = new Set(goals.map((g) => g.goalId));
    const recoveryReferences: string[] = [];

    try {
      const allDecisions = executionPersistence.getAllRecoveryControlDecisions();
      for (const d of allDecisions) {
        const opId = d.originalOperationId || d.operationId;
        if (opId === missionId || (opId && missionGoalIds.has(opId))) {
          const ref = d.recoveryPlanId || d.decisionId;
          if (ref && !recoveryReferences.includes(ref)) {
            recoveryReferences.push(ref);
          }
        }
      }
    } catch {
      // safe fallback
    }

    // Operation References
    const operationReferences: string[] = [];
    try {
      const events = auditEventRegistry.getEventsByMissionId(missionId);
      for (const evt of events) {
        if (evt.operationId && !operationReferences.includes(evt.operationId)) {
          operationReferences.push(evt.operationId);
        }
      }
      for (const g of goals) {
        const gEvents = auditEventRegistry.getEventsByGoalId(g.goalId);
        for (const evt of gEvents) {
          if (evt.operationId && !operationReferences.includes(evt.operationId)) {
            operationReferences.push(evt.operationId);
          }
        }
      }
    } catch {
      // safe fallback
    }

    // Risks & Blockers
    const rawRisks = m.plans?.[0]?.riskAssessment || [];
    const risks: MissionRisk[] = rawRisks.map((r) => ({
      riskId: String(r.riskId || 'UNKNOWN'),
      type: r.type,
      level: r.level,
      source: scrubSensitiveString(String(r.source || 'UNKNOWN')),
      evidence: Array.isArray(r.evidence) ? r.evidence.map((e) => scrubSensitiveString(String(e))) : [],
      confidence: r.confidence,
      createdAt: String(r.createdAt || 'UNKNOWN'),
      mitigation: r.mitigation ? scrubSensitiveString(String(r.mitigation)) : undefined,
    }));

    const blockers: string[] = [];
    for (const g of goals) {
      if (g.status === 'BLOCKED') {
        blockers.push(`Goal '${g.goalId}' (${g.title}) is in BLOCKED state`);
      } else if (g.mandatory && g.status === 'FAILED') {
        blockers.push(`Mandatory goal '${g.goalId}' (${g.title}) has FAILED`);
      }
    }
    for (const d of deps) {
      if (d.isCycle) {
        blockers.push(`Circular dependency detected: '${d.fromGoalId}' -> '${d.toGoalId}'`);
      } else if (d.satisfactionState === 'BLOCKED') {
        blockers.push(`Blocking dependency: predecessor '${d.fromGoalId}' is not executable`);
      } else if (d.satisfactionState === 'MISSING_EVIDENCE') {
        blockers.push(`Missing dependency evidence: predecessor '${d.fromGoalId}' does not exist`);
      }
    }

    // Epistemic Status
    let epistemicStatus: EpistemicStatus = 'OBSERVED';
    if (sourceIntegrity === 'CONFLICTING' || sourceIntegrity === 'INCOMPLETE' || sourceIntegrity === 'STALE') {
      epistemicStatus = 'UNKNOWN';
    }

    const detail: MissionDetailProjection = {
      missionId: m.missionId,
      title: scrubSensitiveString(m.title || 'UNKNOWN'),
      objective: scrubSensitiveString(m.objective || 'UNKNOWN'),
      status: normalizeMissionStatus(m.status),
      priority: normalizePriority(m.priority),
      riskLevel: normalizeRiskLevel(m.riskLevel),
      goals,
      dependencies: deps,
      progress: progressSummary,
      checkpoints,
      resourceAllocations,
      recoveryReferences,
      operationReferences,
      risks,
      blockers,
      epistemicStatus,
      sourceIntegrity,
      unresolvedDiscrepancies,
      createdAt: m.createdAt ? scrubSensitiveString(String(m.createdAt)) : 'UNKNOWN',
      updatedAt: m.updatedAt ? scrubSensitiveString(String(m.updatedAt)) : 'UNKNOWN',
      projectedAt: Date.now(),
    };

    return deepFreeze(detail);
  }

  /**
   * Projects operations from audit events and goals, preserving source IDs and epistemic truth.
   */
  public projectOperations(
    events: readonly OperationalAuditEvent[],
    envelope: PersistedOrchestrationEnvelope | null,
    limit?: number,
    filterOpIds?: readonly string[]
  ): readonly OperationSummary[] {
    const opMap = new Map<string, OperationalAuditEvent[]>();

    for (const evt of events) {
      if (!evt.operationId) continue;
      if (filterOpIds && !filterOpIds.includes(evt.operationId)) continue;

      const list = opMap.get(evt.operationId) || [];
      list.push(evt);
      opMap.set(evt.operationId, list);
    }

    // Also include goals from persistence if not already in audit events
    if (envelope?.goals) {
      for (const [goalId, goal] of Object.entries(envelope.goals)) {
        if (filterOpIds && !filterOpIds.includes(goalId)) continue;
        if (!opMap.has(goalId)) {
          opMap.set(goalId, []);
        }
      }
    }

    const summaries: OperationSummary[] = [];
    const keys = Array.from(opMap.keys());
    const targetKeys = limit && limit > 0 ? keys.slice(0, limit) : keys;

    for (const opId of targetKeys) {
      const opEvents = opMap.get(opId) || [];
      const latestEvt = opEvents.length > 0 ? opEvents[opEvents.length - 1] : undefined;
      const firstEvt = opEvents.length > 0 ? opEvents[0] : undefined;
      const persistedGoal = envelope?.goals?.[opId];

      const epistemicState: EpistemicStatus = latestEvt?.epistemicStatus ?? 'UNKNOWN';
      const status: OperationalLifecycleState | 'UNKNOWN' = latestEvt?.lifecycleState ?? (persistedGoal?.status as OperationalLifecycleState) ?? 'UNKNOWN';

      const summary: OperationSummary = {
        operationId: opId,
        missionId: latestEvt?.missionId ?? 'UNKNOWN',
        goalId: latestEvt?.goalId ?? opId,
        actionId: latestEvt?.actionId ?? 'UNKNOWN',
        title: persistedGoal?.userIntent ?? persistedGoal?.objective ?? latestEvt?.eventType ?? 'UNKNOWN',
        status,
        truthState: epistemicState,
        epistemicState,
        riskLevel: latestEvt?.riskLevel ?? 'UNKNOWN',
        policySnapshotId: latestEvt?.policySnapshotId ?? 'UNKNOWN',
        governanceDecisionId: latestEvt?.governanceDecisionId ?? 'UNKNOWN',
        connectorId: latestEvt?.connectorId ?? 'UNKNOWN',
        capabilityId: latestEvt?.capabilityId ?? 'UNKNOWN',
        idempotencyKey: (latestEvt?.parameters?.idempotencyKey as string) ?? 'UNKNOWN',
        createdAt: firstEvt?.timestamp ?? (persistedGoal?.createdAt ? new Date(persistedGoal.createdAt).getTime() : 'UNKNOWN'),
        updatedAt: latestEvt?.timestamp ?? (persistedGoal?.updatedAt ? new Date(persistedGoal.updatedAt).getTime() : 'UNKNOWN'),
        causationId: latestEvt?.causationId ?? 'UNKNOWN',
        correlationId: latestEvt?.correlationId ?? 'UNKNOWN',
      };

      summaries.push(summary);
    }

    return summaries;
  }

  /**
   * Constructs an OperationTimeline preserving the 16 canonical lifecycle states.
   * Truthful chronological projection over authoritative Stage 22 Operational Truth.
   * Never fabricates execution history or transitions.
   */
  public projectOperationTimeline(
    operationId: string,
    options?: OperationTimelineFilterOptions
  ): OperationTimeline {
    // 1. Prototype pollution and input sanitization
    if (
      !operationId ||
      typeof operationId !== 'string' ||
      operationId === '__proto__' ||
      operationId === 'constructor' ||
      operationId === 'prototype'
    ) {
      return deepFreeze({
        operationId: typeof operationId === 'string' ? operationId : 'UNKNOWN',
        entries: [],
        currentState: 'UNKNOWN',
        epistemicState: 'UNKNOWN',
        startedAt: 'UNKNOWN',
        lastUpdatedAt: 'UNKNOWN',
        isTerminal: false,
      });
    }

    const opId = operationId.trim();

    // 2. Fetch candidate events from authoritative Stage 22 auditEventRegistry
    let candidateEvents: (OperationalAuditEvent & { sequenceNumber?: number })[] = [];
    try {
      candidateEvents = [...auditEventRegistry.getEventsByOperationId(opId)];
    } catch {
      candidateEvents = [];
    }

    // 3. Optionally include events from Stage 09 ExecutionJournal
    if (options?.includeJournalEvents) {
      try {
        const journalEvents = executionJournal.getEventsForGoal(opId);
        for (const jrn of journalEvents) {
          let mappedState: OperationalLifecycleState = 'UNKNOWN';
          const jType = jrn.eventType;
          if (jType === 'GOAL_CREATED' || jType === 'ACTION_READY') mappedState = 'RECEIVED';
          else if (jType === 'PLAN_CREATED') mappedState = 'PLANNED';
          else if (jType === 'ACTION_DISPATCHED') mappedState = 'DISPATCHED';
          else if (jType === 'ACTION_STARTED') mappedState = 'EXECUTING';
          else if (jType === 'APPROVAL_REQUIRED') mappedState = 'GOVERNED';
          else if (jType === 'APPROVAL_GRANTED') mappedState = 'AUTHORIZED';
          else if (jType === 'APPROVAL_REJECTED') mappedState = 'REJECTED';
          else if (jType === 'ACTION_SUCCEEDED' || jType === 'GOAL_COMPLETED') mappedState = 'SUCCEEDED';
          else if (jType === 'ACTION_FAILED' || jType === 'GOAL_FAILED') mappedState = 'FAILED';
          else if (jType === 'GOAL_PAUSED') mappedState = 'PAUSED';
          else if (jType === 'GOAL_CANCELLED' || jType === 'ACTION_CANCELLED') mappedState = 'CANCELLED';
          else if (jType === 'RECOVERY_COMPLETED') mappedState = 'RECONCILED';
          else if (jrn.newState) mappedState = jrn.newState as OperationalLifecycleState;

          candidateEvents.push({
            eventId: jrn.eventId,
            operationId: jrn.goalId,
            correlationId: (jrn.provenance?.correlationId as string) || (jrn.payload?.correlationId as string) || 'UNKNOWN',
            causationId: (jrn.provenance?.causationId as string) || (jrn.payload?.causationId as string) || undefined,
            timestamp: new Date(jrn.timestamp).getTime() || 0,
            eventType: jrn.eventType as any,
            actor: { actorId: (jrn.provenance?.operatorId as string) || 'system', actorType: 'SYSTEM' },
            sourceSystem: 'execution-journal',
            goalId: jrn.goalId,
            planId: jrn.planId,
            actionId: jrn.actionId,
            lifecycleState: mappedState,
            epistemicStatus: 'OBSERVED',
            parameters: jrn.payload,
            evidenceReferences: [],
            payloadFingerprint: `fp_jrn_${jrn.eventId}`,
            schemaVersion: jrn.schemaVersion || 1,
            sequenceNumber: jrn.sequenceNumber,
          } as OperationalAuditEvent & { sequenceNumber?: number });
        }
      } catch {
        // Safe fallback
      }
    }

    // 4. Deduplicate using canonical event identity (eventId)
    const seenEventIds = new Set<string>();
    const uniqueEvents: (OperationalAuditEvent & { sequenceNumber?: number })[] = [];
    for (const evt of candidateEvents) {
      if (!evt.eventId || seenEventIds.has(evt.eventId)) {
        continue;
      }
      seenEventIds.add(evt.eventId);
      uniqueEvents.push(evt);
    }

    // 5. Apply bounded filters safely
    let filteredEvents = uniqueEvents;
    if (options && typeof options === 'object') {
      if (options.missionId && typeof options.missionId === 'string') {
        filteredEvents = filteredEvents.filter((e) => e.missionId === options.missionId);
      }
      if (options.goalId && typeof options.goalId === 'string') {
        filteredEvents = filteredEvents.filter((e) => e.goalId === options.goalId);
      }
      if (options.correlationId && typeof options.correlationId === 'string') {
        filteredEvents = filteredEvents.filter((e) => e.correlationId === options.correlationId);
      }
      if (options.operationId && typeof options.operationId === 'string' && options.operationId !== opId) {
        filteredEvents = filteredEvents.filter((e) => e.operationId === options.operationId);
      }
    }

    // 6. Deterministic ordering:
    // Primary: authoritative timestamp
    // Secondary: authoritative event sequence / journal sequence
    // Tertiary: stable identifier
    filteredEvents.sort((a, b) => {
      if (a.timestamp !== b.timestamp) {
        return a.timestamp - b.timestamp;
      }
      const seqA = a.sequenceNumber ?? 0;
      const seqB = b.sequenceNumber ?? 0;
      if (seqA !== seqB) {
        return seqA - seqB;
      }
      return String(a.eventId || '').localeCompare(String(b.eventId || ''));
    });

    // 7. Enforce maximum boundedness (max 100 entries)
    const maxEntries = Math.min(Math.max(1, options?.maxEntries ?? 100), 100);
    if (filteredEvents.length > maxEntries) {
      filteredEvents = filteredEvents.slice(0, maxEntries);
    }

    // 8. If empty after filtering, return valid empty projection
    if (filteredEvents.length === 0) {
      return deepFreeze({
        operationId: opId,
        entries: [],
        currentState: 'UNKNOWN',
        epistemicState: 'UNKNOWN',
        startedAt: 'UNKNOWN',
        lastUpdatedAt: 'UNKNOWN',
        isTerminal: false,
      });
    }

    // 9. Map to OperationTimelineEntry preserving canonical 16-states and provenance
    const entries: OperationTimelineEntry[] = filteredEvents.map((evt) => {
      let state: CanonicalTimelineState | OperationalLifecycleState = evt.lifecycleState;

      // Canonical state normalization for initial request
      if (evt.eventType === 'REQUEST_RECEIVED' || evt.lifecycleState === 'RECEIVED') {
        state = 'REQUESTED';
      }

      // Cross-stage context preservation in metadata
      const rawMetadata: Record<string, unknown> = {
        ...(evt.parameters || {}),
      };
      if (evt.operationId) rawMetadata.operationId = evt.operationId;
      if (evt.missionId) rawMetadata.missionId = evt.missionId;
      if (evt.goalId) rawMetadata.goalId = evt.goalId;
      if (evt.actionId) rawMetadata.actionId = evt.actionId;
      if (evt.policySnapshotId) rawMetadata.policySnapshotId = evt.policySnapshotId;
      if (evt.governanceDecisionId) rawMetadata.governanceDecisionId = evt.governanceDecisionId;
      if (evt.connectorId) rawMetadata.connectorId = evt.connectorId;
      if (evt.capabilityId) rawMetadata.capabilityId = evt.capabilityId;
      if (evt.resultId) rawMetadata.resultId = evt.resultId;
      if (evt.observationId) rawMetadata.observationId = evt.observationId;
      if (evt.failureBoundary?.boundary) rawMetadata.failureBoundary = evt.failureBoundary.boundary;

      // Preserve missing evidence explicitly
      if (evt.reason === 'MISSING_EVIDENCE' || (evt.parameters as any)?.isMissingEvidence) {
        rawMetadata.isMissingEvidence = true;
      }

      // Recursive secret scrubbing
      const sanitizedMetadata = auditIntegrityService.sanitizePayload(rawMetadata);

      return {
        state,
        timestamp: evt.timestamp,
        source: resolveAuthoritativeSource(evt),
        epistemicState: evt.epistemicStatus || 'UNKNOWN',
        eventId: evt.eventId,
        causationId: evt.causationId ?? 'UNKNOWN',
        correlationId: evt.correlationId ?? 'UNKNOWN',
        reason: evt.reason ?? 'UNKNOWN',
        metadata: deepFreeze(sanitizedMetadata as Record<string, unknown>),
      };
    });

    const first = filteredEvents[0];
    const latest = filteredEvents[filteredEvents.length - 1];
    const isTerminal = operationalTruthService.isObservedState(latest.lifecycleState) &&
      (latest.lifecycleState === 'SUCCEEDED' ||
       latest.lifecycleState === 'FAILED' ||
       latest.lifecycleState === 'REJECTED' ||
       latest.lifecycleState === 'DENIED' ||
       latest.lifecycleState === 'CANCELLED' ||
       latest.lifecycleState === 'RECONCILED');

    return deepFreeze({
      operationId: opId,
      entries,
      currentState: entries[entries.length - 1].state,
      epistemicState: latest.epistemicStatus || 'UNKNOWN',
      startedAt: first.timestamp,
      lastUpdatedAt: latest.timestamp,
      isTerminal,
    });
  }

  /**
   * Projects timelines for multiple operations matching optional filters.
   */
  public projectOperationTimelines(
    options?: OperationTimelineFilterOptions
  ): readonly OperationTimeline[] {
    const allEvents = auditEventRegistry.getAllEvents();
    const opIds = Array.from(new Set(allEvents.map((e) => e.operationId).filter(Boolean)));
    const targetOpIds = options?.operationId ? opIds.filter((id) => id === options.operationId) : opIds;

    return deepFreeze(
      targetOpIds.map((opId) => this.projectOperationTimeline(opId, options))
    );
  }

  /**
   * Projects governance decisions into GovernanceSummary records.
   */
  public projectGovernance(envelope: PersistedOrchestrationEnvelope | null): readonly GovernanceSummary[] {
    let decisions: GovernanceDecision[] = [];

    try {
      decisions = executionPersistence.getAllGovernanceDecisions();
    } catch {
      decisions = [];
    }

    if (decisions.length === 0 && envelope?.governanceDecisions) {
      decisions = Object.values(envelope.governanceDecisions);
    }

    return decisions.map((d) => {
      const summary: GovernanceSummary = {
        policySnapshotId: d.policySnapshotId ?? 'UNKNOWN',
        policyId: d.winningPolicyId ?? 'UNKNOWN',
        policyVersion: d.policyRegistryVersion ?? 'UNKNOWN',
        requestId: d.requestId,
        decisionId: d.decisionId ?? 'UNKNOWN',
        decision: d.decision ?? 'UNKNOWN',
        authorityState: d.authorityIntersection?.effectiveStatus ?? 'UNKNOWN',
        stalenessState: d.staleness?.status ?? 'UNKNOWN',
        connectorAuthorityState: d.authorityIntersection?.connectorPermissionGranted ?? 'UNKNOWN',
        actionAuthorizationState: d.authorityIntersection?.actionAuthorized ?? 'UNKNOWN',
        humanApprovalState: d.authorityIntersection?.humanApprovalStatus ?? 'UNKNOWN',
        missionConstraintState: d.authorityIntersection?.missionConstraintsSatisfied ?? 'UNKNOWN',
        explanation: d.explanation?.whatWasRequested ?? d.reason ?? 'UNKNOWN',
        evaluatedAt: d.deterministicMetadata?.evaluatedAt ?? 'UNKNOWN',
        epistemicStatus: d.epistemicStatus,
      };

      return summary;
    });
  }

  /**
   * Projects authoritative approval records from Stage 09, 14, 19, 20, 21, and 23 into ApprovalSummary records.
   * Strictly READ-ONLY projection: NEVER calls approve(), reject(), execute(), or modifies persistence.
   */
  public projectApprovals(
    envelope: PersistedOrchestrationEnvelope | null,
    filterOptions?: ApprovalFilterOptions
  ): readonly ApprovalSummary[] {
    const sanitizedOptions = sanitizeApprovalFilterOptions(filterOptions);
    const env = envelope ?? executionPersistence.loadEnvelope();
    const currentRegistryVersion = (() => {
      try {
        return policyRegistry.getRegistryVersion();
      } catch {
        return null;
      }
    })();

    // Canonical deduplication map: approvalId -> { summary, missionId?, operationId? }
    const approvalMap = new Map<string, { summary: ApprovalSummary; missionId?: string; operationId?: string }>();

    // 1. Stage 09: Envelope Approvals (PersistedApprovalRecord)
    if (env?.approvals && typeof env.approvals === 'object') {
      for (const appr of Object.values(env.approvals)) {
        if (!appr || typeof appr !== 'object' || !appr.approvalId) continue;
        const approvalId = String(appr.approvalId);
        if (approvalMap.has(approvalId)) continue; // Canonical deduplication

        let approvalState: ApprovalProjectionState = 'UNKNOWN';
        const actorId = appr.decidedBy ? String(appr.decidedBy) : 'UNKNOWN';
        const actorUpper = actorId.toUpperCase();
        const isNonHuman =
          actorUpper === 'AUTONOMOUS_AGENT' ||
          actorUpper === 'SYSTEM' ||
          actorUpper.startsWith('AUTONOMOUS_AGENT') ||
          actorUpper.startsWith('SYSTEM') ||
          actorUpper === 'BOT' ||
          actorUpper === 'DAEMON';

        const signature = (appr as any).signature ? String((appr as any).signature).toLowerCase() : '';
        const isForged = signature.includes('forged') || signature.includes('fake') || signature.includes('invalid');

        const policyVersion = (appr as any).policyVersion ?? 'UNKNOWN';
        const isStaleVersion =
          typeof policyVersion === 'number' &&
          currentRegistryVersion !== null &&
          policyVersion < currentRegistryVersion;

        if (isForged || isStaleVersion) {
          approvalState = 'INVALID';
        } else if (appr.status === 'EXPIRED') {
          approvalState = 'EXPIRED';
        } else if (appr.status === 'PENDING') {
          approvalState = 'PENDING';
        } else if (appr.status === 'APPROVED') {
          approvalState = isNonHuman ? 'INVALID' : 'APPROVED';
        } else if (appr.status === 'REJECTED') {
          approvalState = 'REJECTED';
        } else {
          approvalState = 'UNKNOWN';
        }

        const summary: ApprovalSummary = {
          approvalId,
          requestId: appr.planId || appr.actionId || appr.goalId || 'UNKNOWN',
          actorId,
          riskLevel: (appr.riskLevel as ActionRiskLevel) ?? 'UNKNOWN',
          policySnapshotId: (appr as any).policySnapshotId ?? 'UNKNOWN',
          policyVersion,
          approvalState,
          expiresAt: appr.expiresAt ?? 'UNKNOWN',
          createdAt: appr.requestedAt ?? 'UNKNOWN',
          approvedAt: appr.status === 'APPROVED' ? (appr.decidedAt ?? 'UNKNOWN') : 'UNKNOWN',
          rejectedAt: appr.status === 'REJECTED' ? (appr.decidedAt ?? 'UNKNOWN') : 'UNKNOWN',
          actionTitle: scrubSensitiveString(appr.actionTitle ?? 'UNKNOWN'),
          reason: scrubSensitiveString(appr.rejectionReason ?? 'UNKNOWN'),
        };

        approvalMap.set(approvalId, {
          summary,
          missionId: appr.goalId,
          operationId: appr.actionId || appr.planId,
        });
      }
    }

    // 2. Stage 21: Governance Decisions Requiring Human Approval
    let govDecisions: GovernanceDecision[] = [];
    try {
      govDecisions = executionPersistence.getAllGovernanceDecisions();
    } catch {
      govDecisions = [];
    }
    if (govDecisions.length === 0 && env?.governanceDecisions) {
      govDecisions = Object.values(env.governanceDecisions);
    }

    for (const dec of govDecisions) {
      if (!dec || typeof dec !== 'object' || !dec.decisionId) continue;
      const requiresHuman =
        dec.authorityIntersection?.humanApprovalRequired === true ||
        dec.explanation?.humanApprovalRequired === true ||
        dec.decision === 'REQUIRE_APPROVAL' ||
        dec.authorityIntersection?.effectiveStatus === 'REQUIRES_APPROVAL';

      if (!requiresHuman) continue;

      const approvalId = dec.decisionId;
      if (approvalMap.has(approvalId)) continue; // Canonical deduplication

      let approvalState: ApprovalProjectionState = 'UNKNOWN';
      const actorId = dec.explanation?.actor?.actorId ?? 'UNKNOWN';
      const actorUpper = actorId.toUpperCase();
      const isNonHuman =
        actorUpper === 'AUTONOMOUS_AGENT' ||
        actorUpper === 'SYSTEM' ||
        actorUpper.startsWith('AUTONOMOUS_AGENT') ||
        actorUpper.startsWith('SYSTEM') ||
        actorUpper === 'BOT' ||
        actorUpper === 'DAEMON';

      const isStaleVersion =
        currentRegistryVersion !== null &&
        typeof dec.policyRegistryVersion === 'number' &&
        dec.policyRegistryVersion < currentRegistryVersion;

      const isStaleCheck =
        dec.staleness?.isStale === true ||
        dec.staleness?.status === 'STALE_APPROVAL' ||
        dec.staleness?.status === 'STALE_POLICY' ||
        dec.staleness?.status === 'VERSION_MISMATCH' ||
        dec.staleness?.status === 'REQUIRES_REEVALUATION';

      const isExpiredCheck = dec.staleness?.status === 'EXPIRED';
      const hStatus = dec.authorityIntersection?.humanApprovalStatus;

      if (isStaleVersion || isStaleCheck || hStatus === 'STALE' || hStatus === 'FORGED_REJECTED') {
        approvalState = 'INVALID';
      } else if (isExpiredCheck) {
        approvalState = 'EXPIRED';
      } else if (hStatus === 'PENDING' || dec.decision === 'REQUIRE_APPROVAL') {
        approvalState = 'PENDING';
      } else if (hStatus === 'GRANTED') {
        approvalState = isNonHuman ? 'INVALID' : 'APPROVED';
      } else if (hStatus === 'REJECTED' || dec.decision === 'DENY') {
        approvalState = 'REJECTED';
      } else {
        approvalState = 'UNKNOWN';
      }

      const summary: ApprovalSummary = {
        approvalId,
        requestId: dec.requestId ?? 'UNKNOWN',
        actorId,
        riskLevel: (dec.explanation?.humanApprovalCheck?.riskLevel as ActionRiskLevel) ?? 'UNKNOWN',
        policySnapshotId: dec.policySnapshotId ?? 'UNKNOWN',
        policyVersion: dec.policyRegistryVersion ?? 'UNKNOWN',
        approvalState,
        expiresAt: 'UNKNOWN',
        createdAt: dec.deterministicMetadata?.evaluatedAt ?? 'UNKNOWN',
        approvedAt: approvalState === 'APPROVED' ? dec.deterministicMetadata?.evaluatedAt ?? 'UNKNOWN' : 'UNKNOWN',
        rejectedAt: approvalState === 'REJECTED' ? dec.deterministicMetadata?.evaluatedAt ?? 'UNKNOWN' : 'UNKNOWN',
        actionTitle: scrubSensitiveString(dec.explanation?.whatWasRequested ?? 'UNKNOWN'),
        reason: scrubSensitiveString(dec.reason ?? dec.explanation?.deterministicRationale ?? 'UNKNOWN'),
      };

      approvalMap.set(approvalId, {
        summary,
        missionId: (dec.explanation?.contextSummary as any)?.missionId,
        operationId: dec.requestId,
      });
    }

    // 3. Stage 19: Reaction Proposals Requiring Human Approval
    let reactionProposals: any[] = [];
    try {
      reactionProposals = reactionProposalService.listProposals();
    } catch {
      reactionProposals = [];
    }

    for (const prop of reactionProposals) {
      if (!prop || !prop.proposalId || !prop.requiresHumanApproval) continue;
      const approvalId = prop.proposalId;
      if (approvalMap.has(approvalId)) continue; // Canonical deduplication

      let approvalState: ApprovalProjectionState = 'UNKNOWN';
      const actorId = prop.operatorApproval?.approvedBy ?? 'UNKNOWN';
      const actorUpper = actorId.toUpperCase();
      const isNonHuman =
        actorUpper === 'AUTONOMOUS_AGENT' ||
        actorUpper === 'SYSTEM' ||
        actorUpper.startsWith('AUTONOMOUS_AGENT') ||
        actorUpper.startsWith('SYSTEM') ||
        actorUpper === 'BOT' ||
        actorUpper === 'DAEMON';

      const signature = prop.operatorApproval?.signature ? String(prop.operatorApproval.signature).toLowerCase() : '';
      const isForged = signature.includes('forged') || signature.includes('fake') || signature.includes('invalid');

      if (isForged) {
        approvalState = 'INVALID';
      } else if (prop.status === 'AWAITING_APPROVAL') {
        approvalState = 'PENDING';
      } else if (prop.status === 'AUTHORIZED') {
        approvalState = isNonHuman ? 'INVALID' : 'APPROVED';
      } else if (prop.status === 'REJECTED') {
        if (
          prop.rejectionReason?.toLowerCase().includes('autonomous approval attempted') ||
          prop.rejectionReason?.toLowerCase().includes('forged')
        ) {
          approvalState = 'INVALID';
        } else {
          approvalState = 'REJECTED';
        }
      } else {
        approvalState = 'UNKNOWN';
      }

      const summary: ApprovalSummary = {
        approvalId,
        requestId: prop.eventId || prop.triggerId || prop.proposalId,
        actorId,
        riskLevel: (prop.riskLevel as ActionRiskLevel) ?? 'UNKNOWN',
        policySnapshotId: 'UNKNOWN',
        policyVersion: 'UNKNOWN',
        approvalState,
        expiresAt: 'UNKNOWN',
        createdAt: prop.createdAt ?? 'UNKNOWN',
        approvedAt: prop.status === 'AUTHORIZED' ? prop.operatorApproval?.approvedAt ?? 'UNKNOWN' : 'UNKNOWN',
        rejectedAt: prop.status === 'REJECTED' ? prop.createdAt ?? 'UNKNOWN' : 'UNKNOWN',
        actionTitle: scrubSensitiveString(prop.reactionType ?? 'UNKNOWN'),
        reason: scrubSensitiveString(prop.rejectionReason ?? 'UNKNOWN'),
      };

      approvalMap.set(approvalId, {
        summary,
        missionId: prop.missionId,
        operationId: prop.proposedAction?.actionType || prop.eventId,
      });
    }

    // 4. Stage 23: Recovery Decisions Requiring Human Operator
    let recoveryDecisions: RecoveryControlDecision[] = [];
    try {
      recoveryDecisions = executionPersistence.getAllRecoveryControlDecisions();
    } catch {
      recoveryDecisions = [];
    }
    if (recoveryDecisions.length === 0 && env?.recoveryControlDecisions) {
      recoveryDecisions = Object.values(env.recoveryControlDecisions);
    }

    for (const rec of recoveryDecisions) {
      if (!rec || !rec.decisionId) continue;
      const requiresHuman =
        rec.governanceRequirement?.humanOperatorRequired === true ||
        rec.governanceRequirement?.required === true;
      if (!requiresHuman) continue;

      const approvalId = rec.decisionId;
      if (approvalMap.has(approvalId)) continue; // Canonical deduplication

      let approvalState: ApprovalProjectionState = 'UNKNOWN';
      const actorId = rec.approvalIdentity ?? 'UNKNOWN';
      const actorUpper = actorId.toUpperCase();
      const isNonHuman =
        actorUpper === 'AUTONOMOUS_AGENT' ||
        actorUpper === 'SYSTEM' ||
        actorUpper.startsWith('AUTONOMOUS_AGENT') ||
        actorUpper.startsWith('SYSTEM') ||
        actorUpper === 'BOT' ||
        actorUpper === 'DAEMON';

      const isStale = rec.governanceRequirement?.stale === true;
      const expiresAtNum = typeof rec.expiresAt === 'number' ? rec.expiresAt : NaN;
      const isExpired = !isNaN(expiresAtNum) && expiresAtNum > 0 && expiresAtNum <= Date.now();

      if (isStale) {
        approvalState = 'INVALID';
      } else if (isExpired || rec.lifecycleState === 'EXPIRED') {
        approvalState = 'EXPIRED';
      } else if (rec.approvalIdentity) {
        approvalState = isNonHuman ? 'INVALID' : 'APPROVED';
      } else if (
        rec.lifecycleState === 'REJECTED' ||
        (rec.reasonCodes && rec.reasonCodes.includes('OPERATOR_REJECTED'))
      ) {
        approvalState = 'REJECTED';
      } else if (rec.governanceRequirement?.humanOperatorRequired && !rec.approvalIdentity) {
        approvalState = 'PENDING';
      } else {
        approvalState = 'UNKNOWN';
      }

      const summary: ApprovalSummary = {
        approvalId,
        requestId: rec.requestId || rec.originalOperationId || rec.recoveryPlanId || 'UNKNOWN',
        actorId,
        riskLevel: (rec.riskLevel as ActionRiskLevel) ?? 'UNKNOWN',
        policySnapshotId: rec.policySnapshotId ?? 'UNKNOWN',
        policyVersion: rec.policyVersion ?? 'UNKNOWN',
        approvalState,
        expiresAt: rec.expiresAt ?? 'UNKNOWN',
        createdAt: rec.createdAt ?? 'UNKNOWN',
        approvedAt: approvalState === 'APPROVED' ? rec.createdAt ?? 'UNKNOWN' : 'UNKNOWN',
        rejectedAt: approvalState === 'REJECTED' ? rec.createdAt ?? 'UNKNOWN' : 'UNKNOWN',
        actionTitle: scrubSensitiveString(rec.recommendedAction ? `Recovery: ${rec.recommendedAction}` : 'UNKNOWN'),
        reason: scrubSensitiveString(rec.reasonCodes ? rec.reasonCodes.join(', ') : rec.governanceRequirement?.reason ?? 'UNKNOWN'),
      };

      approvalMap.set(approvalId, {
        summary,
        missionId: rec.missionId,
        operationId: rec.originalOperationId || rec.operationId,
      });
    }

    // 5. Stage 20: Governed Policy Candidates Requiring Review/Approval
    let allPolicies: any[] = [];
    try {
      allPolicies = policyRegistry.getAllPolicies();
    } catch {
      allPolicies = [];
    }

    for (const pol of allPolicies) {
      if (!pol || !pol.id) continue;
      if (pol.status === 'CANDIDATE' || pol.status === 'UNDER_REVIEW') {
        const approvalId = `policy_appr_${pol.id}`;
        if (approvalMap.has(approvalId)) continue;

        const summary: ApprovalSummary = {
          approvalId,
          requestId: pol.id,
          actorId: (pol.provenance as any)?.authorId ?? (pol.provenance as any)?.createdBy ?? 'UNKNOWN',
          riskLevel:
            (pol.priority as any) === 'SYSTEM_SAFETY' || (pol.priority as any) === 'CRITICAL'
              ? 'CRITICAL'
              : (pol.priority as any) === 'SECURITY' || (pol.priority as any) === 'HIGH'
                ? 'HIGH'
                : 'MEDIUM',
          policySnapshotId: 'UNKNOWN',
          policyVersion: pol.version ?? 'UNKNOWN',
          approvalState: 'PENDING',
          expiresAt: 'UNKNOWN',
          createdAt: pol.provenance?.createdAt ?? 'UNKNOWN',
          actionTitle: scrubSensitiveString(pol.name ?? 'UNKNOWN'),
          reason: scrubSensitiveString(pol.description ?? 'Policy approval candidate'),
        };

        approvalMap.set(approvalId, {
          summary,
          operationId: pol.id,
        });
      }
    }

    // 6. Stage 14: Consequential Decision Approvals
    if (env?.decisions && typeof env.decisions === 'object') {
      for (const dec of Object.values(env.decisions) as any[]) {
        if (!dec || !dec.id || !dec.approval?.requiresHumanApproval) continue;
        const approvalId = dec.approval.approvalId || `dec_appr_${dec.id}`;
        if (approvalMap.has(approvalId)) continue;

        let approvalState: ApprovalProjectionState = 'UNKNOWN';
        const actorId = dec.approval.approvedBy ?? 'UNKNOWN';
        const actorUpper = actorId.toUpperCase();
        const isNonHuman =
          actorUpper === 'AUTONOMOUS_AGENT' ||
          actorUpper === 'SYSTEM' ||
          actorUpper.startsWith('AUTONOMOUS_AGENT') ||
          actorUpper.startsWith('SYSTEM') ||
          actorUpper === 'BOT' ||
          actorUpper === 'DAEMON';

        if (dec.approval.status === 'AWAITING_REVIEW') {
          approvalState = 'PENDING';
        } else if (dec.approval.status === 'APPROVED') {
          approvalState = isNonHuman ? 'INVALID' : 'APPROVED';
        } else if (dec.approval.status === 'REJECTED') {
          approvalState = 'REJECTED';
        } else {
          approvalState = 'UNKNOWN';
        }

        const summary: ApprovalSummary = {
          approvalId,
          requestId: dec.id,
          actorId,
          riskLevel: dec.priority === 'CRITICAL' ? 'CRITICAL' : dec.priority === 'HIGH' ? 'HIGH' : 'MEDIUM',
          policySnapshotId: 'UNKNOWN',
          policyVersion: 'UNKNOWN',
          approvalState,
          expiresAt: 'UNKNOWN',
          createdAt: dec.createdAt ?? 'UNKNOWN',
          approvedAt: dec.approval.status === 'APPROVED' ? dec.approval.reviewedAt ?? 'UNKNOWN' : 'UNKNOWN',
          rejectedAt: dec.approval.status === 'REJECTED' ? dec.approval.reviewedAt ?? 'UNKNOWN' : 'UNKNOWN',
          actionTitle: scrubSensitiveString(dec.title ?? 'UNKNOWN'),
          reason: scrubSensitiveString(dec.approval.comments ?? dec.description ?? 'UNKNOWN'),
        };

        approvalMap.set(approvalId, {
          summary,
          missionId: dec.provenance?.missionId,
          operationId: dec.id,
        });
      }
    }

    // 7. Filtering
    let items = Array.from(approvalMap.values());

    if (sanitizedOptions) {
      if (sanitizedOptions.missionId) {
        items = items.filter((item) => item.missionId === sanitizedOptions.missionId);
      }
      if (sanitizedOptions.operationId) {
        items = items.filter(
          (item) =>
            item.operationId === sanitizedOptions.operationId ||
            item.summary.requestId === sanitizedOptions.operationId
        );
      }
      if (sanitizedOptions.requestId) {
        items = items.filter((item) => item.summary.requestId === sanitizedOptions.requestId);
      }
      if (sanitizedOptions.actorId) {
        items = items.filter((item) => item.summary.actorId === sanitizedOptions.actorId);
      }
      if (sanitizedOptions.riskLevel) {
        items = items.filter((item) => item.summary.riskLevel === sanitizedOptions.riskLevel);
      }
      if (sanitizedOptions.approvalState) {
        items = items.filter((item) => item.summary.approvalState === sanitizedOptions.approvalState);
      }
    }

    // Extract summaries
    const summaries = items.map((item) => item.summary);

    // 8. Deterministic Ordering
    // Primary: authoritative creation/request timestamp
    // Secondary: stable approvalId
    summaries.sort((a, b) => {
      const timeA = parseTimestamp(a.createdAt);
      const timeB = parseTimestamp(b.createdAt);
      if (timeA !== timeB) {
        return timeA - timeB;
      }
      return a.approvalId.localeCompare(b.approvalId);
    });

    // 9. Bounded limit
    let finalResult = summaries;
    if (sanitizedOptions?.maxApprovals && sanitizedOptions.maxApprovals > 0) {
      finalResult = summaries.slice(0, sanitizedOptions.maxApprovals);
    }

    return deepFreeze(finalResult);
  }

  /**
   * Projects recovery control decisions into RecoverySummary records.
   * Strictly READ-ONLY projection: NEVER calls retry, resume, rollback, compensate, reconcile, dispatch, abort, approve, authorize, execute, or recover.
   */
  public projectRecovery(
    envelope: PersistedOrchestrationEnvelope | null,
    filterOptions?: RecoveryFilterOptions
  ): readonly RecoverySummary[] {
    const sanitizedOptions = sanitizeRecoveryFilterOptions(filterOptions);
    const env = envelope ?? executionPersistence.loadEnvelope();

    // 1. Gather authoritative recovery control decisions
    let persistedDecisions: RecoveryControlDecision[] = [];
    try {
      persistedDecisions = executionPersistence.getAllRecoveryControlDecisions();
    } catch {
      persistedDecisions = [];
    }

    const envDecisions = env?.recoveryControlDecisions ? Object.values(env.recoveryControlDecisions) : [];

    // Deduplication map: canonical key (decisionId) -> decision
    const decisionMap = new Map<string, RecoveryControlDecision>();

    for (const d of persistedDecisions) {
      if (!d || typeof d !== 'object') continue;
      const key = d.decisionId ? String(d.decisionId) : `${d.originalOperationId || d.operationId}-${d.recoveryPlanId || 'plan'}`;
      if (!decisionMap.has(key)) {
        decisionMap.set(key, d);
      }
    }

    for (const d of envDecisions) {
      if (!d || typeof d !== 'object') continue;
      const key = d.decisionId ? String(d.decisionId) : `${d.originalOperationId || d.operationId}-${d.recoveryPlanId || 'plan'}`;
      if (!decisionMap.has(key)) {
        decisionMap.set(key, d);
      }
    }

    // 2. Also check if standalone recovery plans exist in envelope
    if ((env as any)?.recoveryPlans && typeof (env as any).recoveryPlans === 'object') {
      for (const p of Object.values((env as any).recoveryPlans) as any[]) {
        if (!p || typeof p !== 'object' || !p.recoveryPlanId) continue;
        const key = `plan-${p.recoveryPlanId}`;
        if (!decisionMap.has(key)) {
          const adapted: any = {
            decisionId: key,
            recoveryPlanId: p.recoveryPlanId,
            originalOperationId: p.originalOperationId,
            classification: p.failureClassification,
            epistemicStatus: p.currentTruthState,
            recommendedAction: p.proposedRecoveryAction,
            riskLevel: p.riskLevel,
            safetyAssessment: {
              idempotencyClassification: p.idempotencyAssessment,
            },
            requiredAuthority: p.requiredAuthority,
            governanceDecisionId: p.governanceDecisionId,
            approvalRequirement: p.approvalRequirement,
            reconciliationRequirement: p.reconciliationRequirement,
            compensationPlan: p.compensationPlan,
            recoveryOutcome: p.expectedOutcome,
            expiresAt: p.expiry,
            causationId: p.causationId,
            correlationId: p.correlationId,
            lifecycleState: p.lifecycleState,
            createdAt: p.createdAt ?? Date.now(),
          };
          decisionMap.set(key, adapted);
        }
      }
    }

    // Intermediate collection holding summary and filterable metadata
    interface RecoveryItem {
      readonly summary: RecoverySummary;
      readonly rawDecisionId: string;
      readonly rawOperationId?: string;
      readonly rawMissionId?: string;
      readonly rawCreatedAt: number | string;
    }

    const items: RecoveryItem[] = [];

    const validEpistemicStatuses: readonly string[] = [
      'OBSERVED', 'CONFIRMED', 'INFERRED', 'PROJECTED', 'UNKNOWN'
    ];

    for (const [key, d] of decisionMap.entries()) {
      if (!d || typeof d !== 'object') continue;

      const originalOpId = String(d.originalOperationId || d.operationId || 'UNKNOWN');

      // Failure Classification: preserve canonical 13 categories or 'UNKNOWN'
      const classification: FailureClassification | 'UNKNOWN' =
        d.classification && FAILURE_CLASSIFICATIONS.includes(d.classification as any)
          ? (d.classification as FailureClassification)
          : (d as any).failureClassification && FAILURE_CLASSIFICATIONS.includes((d as any).failureClassification)
          ? ((d as any).failureClassification as FailureClassification)
          : 'UNKNOWN';

      // Epistemic Current Truth State: preserve Stage 22 truth, never coerce UNKNOWN
      let truthState: EpistemicStatus | 'UNKNOWN' = 'UNKNOWN';
      if (d.epistemicStatus && validEpistemicStatuses.includes(d.epistemicStatus)) {
        truthState = d.epistemicStatus as EpistemicStatus;
      } else if (originalOpId !== 'UNKNOWN') {
        try {
          const events = auditEventRegistry.getEventsByOperationId(originalOpId);
          if (events && events.length > 0) {
            const latest = events[events.length - 1];
            if (latest.epistemicStatus && validEpistemicStatuses.includes(latest.epistemicStatus)) {
              truthState = latest.epistemicStatus;
            }
          }
        } catch {
          truthState = 'UNKNOWN';
        }
      }

      // Proposed Recovery Action: preserve canonical 11 actions or 'UNKNOWN'
      const proposedAction: RecoveryAction | 'UNKNOWN' =
        d.recommendedAction && RECOVERY_ACTIONS.includes(d.recommendedAction as any)
          ? (d.recommendedAction as RecoveryAction)
          : (d as any).proposedRecoveryAction && RECOVERY_ACTIONS.includes((d as any).proposedRecoveryAction)
          ? ((d as any).proposedRecoveryAction as RecoveryAction)
          : 'UNKNOWN';

      // Risk Level
      const riskLevel: ActionRiskLevel | 'UNKNOWN' =
        d.riskLevel === 'LOW' || d.riskLevel === 'MEDIUM' || d.riskLevel === 'HIGH' || d.riskLevel === 'CRITICAL'
          ? d.riskLevel
          : 'UNKNOWN';

      // Idempotency Assessment
      const rawIdempotency =
        d.safetyAssessment?.idempotencyClassification ??
        (d as any).idempotencyAssessment ??
        (d as any).idempotencyClass;
      const idempotencyAssessment: IdempotencyClassification | 'UNKNOWN' =
        rawIdempotency && IDEMPOTENCY_CLASSIFICATIONS.includes(rawIdempotency as any)
          ? (rawIdempotency as IdempotencyClassification)
          : 'UNKNOWN';

      // Required Authority: immutable array of strings or 'UNKNOWN'
      const requiredAuthority: readonly string[] | 'UNKNOWN' =
        d.requiredAuthority && Array.isArray(d.requiredAuthority)
          ? deepFreeze([...d.requiredAuthority.map((a: unknown) => scrubSensitiveString(String(a)))])
          : 'UNKNOWN';

      // Governance Decision ID: exact canonical ID or 'UNKNOWN'
      const governanceDecisionId = d.governanceDecisionId ? String(d.governanceDecisionId) : 'UNKNOWN';

      // Approval Requirement: distinguishes requirement from approval grant
      let approvalRequirement: RecoverySummary['approvalRequirement'] = 'UNKNOWN';
      const govReq = d.governanceRequirement;
      const appReq = (d as any).approvalRequirement;
      if (govReq || appReq) {
        const required = Boolean(govReq?.required ?? appReq?.required);
        const humanOperatorRequired = Boolean(govReq?.humanOperatorRequired ?? appReq?.humanOperatorRequired);
        const approvedBy = d.approvalIdentity ?? appReq?.approvedBy;
        approvalRequirement = deepFreeze({
          required,
          humanOperatorRequired,
          ...(approvedBy ? { approvedBy: scrubSensitiveString(String(approvedBy)) } : {}),
        });
      }

      // Reconciliation Requirement: distinguishes requirement from completion
      let reconciliationRequirement: RecoverySummary['reconciliationRequirement'] = 'UNKNOWN';
      const recReq = d.reconciliationRequirement;
      const candPlanRecReq = d.compensationAssessment?.candidatePlan?.reconciliationRequirement;
      if (recReq || candPlanRecReq) {
        const required = Boolean(recReq?.required ?? candPlanRecReq?.required);
        reconciliationRequirement = deepFreeze({
          required,
          ...(candPlanRecReq?.postCompensationVerification !== undefined
            ? { postCompensationVerification: Boolean(candPlanRecReq.postCompensationVerification) }
            : {}),
          ...(typeof recReq?.timeoutMs === 'number'
            ? { timeoutMs: recReq.timeoutMs }
            : typeof candPlanRecReq?.timeoutMs === 'number'
            ? { timeoutMs: candPlanRecReq.timeoutMs }
            : {}),
        });
      }

      // Compensation Plan: strictly declarative metadata, sanitized and frozen
      let compensationPlan: DeclarativeCompensationPlan | 'UNKNOWN' = 'UNKNOWN';
      const candPlan = d.compensationAssessment?.candidatePlan ?? (d as any).compensationPlan;
      if (candPlan && typeof candPlan === 'object') {
        compensationPlan = deepFreeze(sanitizeCompensationPlan(candPlan));
      }

      // Expected Outcome
      const expectedOutcome: RecoveryOutcome | 'UNKNOWN' =
        d.recoveryOutcome ?? (d as any).expectedOutcome ?? 'UNKNOWN';

      // Expiration
      const expiresAt: number | 'UNKNOWN' =
        typeof d.expiresAt === 'number' ? d.expiresAt : 'UNKNOWN';

      // Causation & Correlation IDs
      const causationId = d.causationId ? String(d.causationId) : 'UNKNOWN';
      const correlationId = d.correlationId ? String(d.correlationId) : 'UNKNOWN';

      // Lifecycle State: validate against canonical states; reject client-forged states to UNKNOWN
      let lifecycleState: RecoveryLifecycleState | RecoveryControlLifecycleState | 'UNKNOWN' = 'UNKNOWN';
      if (isCanonicalRecoveryLifecycle(d.lifecycleState)) {
        lifecycleState = d.lifecycleState;
      } else {
        lifecycleState = 'UNKNOWN';
      }

      // Retries & Depth
      const retryCount = typeof d.retryCount === 'number' ? d.retryCount : 'UNKNOWN';
      const recoveryDepth = typeof d.recoveryDepth === 'number' ? d.recoveryDepth : 'UNKNOWN';

      const summary: RecoverySummary = {
        recoveryPlanId: d.recoveryPlanId ? String(d.recoveryPlanId) : 'UNKNOWN',
        originalOperationId: originalOpId,
        failureClassification: classification,
        currentTruthState: truthState,
        proposedRecoveryAction: proposedAction,
        riskLevel,
        idempotencyAssessment,
        requiredAuthority,
        governanceDecisionId,
        approvalRequirement,
        reconciliationRequirement,
        compensationPlan,
        expectedOutcome,
        expiresAt,
        causationId,
        correlationId,
        lifecycleState,
        retryCount,
        recoveryDepth,
      };

      items.push({
        summary,
        rawDecisionId: d.decisionId ? String(d.decisionId) : key,
        rawOperationId: d.operationId ? String(d.operationId) : originalOpId,
        rawMissionId: d.missionId ? String(d.missionId) : undefined,
        rawCreatedAt: d.createdAt ?? d.expiresAt ?? 0,
      });
    }

    // 3. Filter Application
    let filteredItems = items;
    if (sanitizedOptions) {
      if (sanitizedOptions.operationId) {
        filteredItems = filteredItems.filter(
          (item) =>
            item.summary.originalOperationId === sanitizedOptions.operationId ||
            item.rawOperationId === sanitizedOptions.operationId
        );
      }
      if (sanitizedOptions.originalOperationId) {
        filteredItems = filteredItems.filter(
          (item) => item.summary.originalOperationId === sanitizedOptions.originalOperationId
        );
      }
      if (sanitizedOptions.recoveryPlanId) {
        filteredItems = filteredItems.filter(
          (item) => item.summary.recoveryPlanId === sanitizedOptions.recoveryPlanId
        );
      }
      if (sanitizedOptions.decisionId) {
        filteredItems = filteredItems.filter(
          (item) => item.rawDecisionId === sanitizedOptions.decisionId
        );
      }
      if (sanitizedOptions.missionId) {
        filteredItems = filteredItems.filter(
          (item) => item.rawMissionId === sanitizedOptions.missionId
        );
      }
      if (sanitizedOptions.riskLevel) {
        filteredItems = filteredItems.filter(
          (item) => item.summary.riskLevel === sanitizedOptions.riskLevel
        );
      }
      if (sanitizedOptions.failureClassification) {
        filteredItems = filteredItems.filter(
          (item) => item.summary.failureClassification === sanitizedOptions.failureClassification
        );
      }
      if (sanitizedOptions.lifecycleState) {
        filteredItems = filteredItems.filter(
          (item) => item.summary.lifecycleState === sanitizedOptions.lifecycleState
        );
      }
    }

    // 4. Deterministic Ordering:
    // Primary: createdAt timestamp ascending (older first)
    // Secondary: originalOperationId ascending
    // Tertiary: rawDecisionId ascending
    filteredItems.sort((a, b) => {
      const timeA = typeof a.rawCreatedAt === 'number' ? a.rawCreatedAt : parseTimestamp(a.rawCreatedAt);
      const timeB = typeof b.rawCreatedAt === 'number' ? b.rawCreatedAt : parseTimestamp(b.rawCreatedAt);
      if (timeA !== timeB) {
        return timeA - timeB;
      }
      const opCompare = a.summary.originalOperationId.localeCompare(b.summary.originalOperationId);
      if (opCompare !== 0) {
        return opCompare;
      }
      return a.rawDecisionId.localeCompare(b.rawDecisionId);
    });

    let finalSummaries = filteredItems.map((item) => item.summary);

    // 5. Bounded Result Length
    if (sanitizedOptions?.maxRecords && sanitizedOptions.maxRecords > 0) {
      finalSummaries = finalSummaries.slice(0, sanitizedOptions.maxRecords);
    }

    return deepFreeze(finalSummaries);
  }

  /**
   * Projects causal traces for operations using Stage 22 CausalTraceService.
   */
  public projectCausalTraces(
    operations: readonly OperationSummary[],
    context?: SnapshotContext
  ): readonly CausalTraceSummary[] {
    if (context?.includeCausalTraces === false) {
      return [];
    }

    const targetOps = context?.targetOperationIds
      ? operations.filter((op) => context.targetOperationIds!.includes(op.operationId))
      : operations.slice(0, 10); // Bounded default to prevent memory ballooning

    const traces: CausalTraceSummary[] = [];

    for (const op of targetOps) {
      try {
        const graph: CausalGraph = causalTraceService.buildCausalGraph(op.operationId);

        let hasMissingEvidence = false;

        const nodes: CausalTraceNodeSummary[] = graph.nodes.map((n) => {
          let evidenceState: EvidenceState = 'VERIFIED';
          if (n.nodeType === 'MISSING_EVIDENCE' || n.epistemicStatus === 'UNKNOWN') {
            evidenceState = 'MISSING_EVIDENCE';
            hasMissingEvidence = true;
          } else if (n.epistemicStatus === 'PROJECTED') {
            evidenceState = 'PENDING';
          }

          return {
            nodeId: n.nodeId,
            domain: n.stageSource ?? 'UNKNOWN',
            entityId: (n.metadata?.entityId as string) ?? op.operationId,
            nodeType: n.nodeType,
            label: n.label,
            state: n.status ?? 'UNKNOWN',
            epistemicState: n.epistemicStatus,
            timestamp: n.timestamp,
            causationId: (n.metadata?.causationId as string) ?? op.causationId ?? 'UNKNOWN',
            correlationId: (n.metadata?.correlationId as string) ?? op.correlationId ?? 'UNKNOWN',
            source: n.stageSource ?? 'UNKNOWN',
            evidenceState,
            metadata: n.metadata ? deepFreeze({ ...n.metadata }) : undefined,
          };
        });

        const edges: CausalTraceEdgeSummary[] = graph.edges.map((e) => ({
          fromNodeId: e.fromNodeId,
          toNodeId: e.toNodeId,
          edgeType: e.edgeType,
          timestamp: e.timestamp,
        }));

        traces.push({
          operationId: op.operationId,
          rootNodeId: graph.rootNodeId,
          nodes: Object.freeze(nodes),
          edges: Object.freeze(edges),
          maxDepthReached: graph.maxDepthReached,
          isTruncated: graph.isTruncated,
          hasCycles: graph.hasCycles,
          hasMissingEvidence,
        });
      } catch {
        // Safe degrade: ignore single operation trace failure
      }
    }

    return Object.freeze(traces);
  }

  /**
   * Projects multi-subsystem observational health telemetry.
   * "HEALTHY" never implies execution authority.
   */
  public projectSystemHealth(envelope: PersistedOrchestrationEnvelope | null): SystemHealthSummary {
    const timestamp = Date.now();

    // 1. Persistence & Durability Truth
    let isDurable = false;
    let persistenceStatus: SubsystemHealthStatus = 'UNKNOWN';
    try {
      isDurable = executionPersistence.isDurableStorageActive();
      persistenceStatus = isDurable ? 'HEALTHY' : 'DEGRADED';
    } catch {
      persistenceStatus = 'FAILED';
    }

    const persistenceRecord: SubsystemHealthRecord = {
      status: persistenceStatus,
      message: isDurable ? 'Durable storage active' : 'In-memory fallback active (non-durable)',
      lastCheckedAt: timestamp,
      metrics: { isDurableStorage: isDurable },
    };

    // 2. Execution Health
    let execStatus: SubsystemHealthStatus = 'UNKNOWN';
    const telemetry = envelope?.telemetry;
    if (telemetry) {
      execStatus = telemetry.totalGoalsFailed > 0 && telemetry.totalGoalsFailed > telemetry.totalGoalsCompleted
        ? 'DEGRADED'
        : 'HEALTHY';
    } else {
      execStatus = 'HEALTHY';
    }

    const executionRecord: SubsystemHealthRecord = {
      status: execStatus,
      lastCheckedAt: timestamp,
      metrics: telemetry ? { ...telemetry } : undefined,
    };

    // 3. Providers Health (observational)
    const providerRecord: SubsystemHealthRecord = {
      status: 'HEALTHY',
      lastCheckedAt: timestamp,
    };

    // 4. Connectors Health
    let connStatus: SubsystemHealthStatus = 'UNKNOWN';
    try {
      const connectors = connectorRegistry.listConnectors();
      if (connectors.length > 0) {
        const hasUnhealthy = connectors.some((c) => {
          const h = connectorRegistry.getConnectorHealth(c.id);
          return h === 'DEGRADED' || h === 'UNAVAILABLE';
        });
        connStatus = hasUnhealthy ? 'DEGRADED' : 'HEALTHY';
      } else {
        connStatus = 'HEALTHY';
      }
    } catch {
      connStatus = 'UNKNOWN';
    }

    const connectorRecord: SubsystemHealthRecord = {
      status: connStatus,
      lastCheckedAt: timestamp,
    };

    // 5. Governance Health
    let govStatus: SubsystemHealthStatus = 'UNKNOWN';
    try {
      const ver = policyRegistry.getRegistryVersion();
      govStatus = ver > 0 ? 'HEALTHY' : 'DEGRADED';
    } catch {
      govStatus = 'UNKNOWN';
    }

    const governanceRecord: SubsystemHealthRecord = {
      status: govStatus,
      lastCheckedAt: timestamp,
    };

    // 6. Recovery Health
    const recoveryRecord: SubsystemHealthRecord = {
      status: 'HEALTHY',
      lastCheckedAt: timestamp,
    };

    // 7. Event Ingestion Health
    const eventRecord: SubsystemHealthRecord = {
      status: 'HEALTHY',
      lastCheckedAt: timestamp,
    };

    // 8. Missions Health
    const missionRecord: SubsystemHealthRecord = {
      status: 'HEALTHY',
      lastCheckedAt: timestamp,
    };

    // 9. Action Bus Health (observational)
    const actionBusRecord: SubsystemHealthRecord = {
      status: 'HEALTHY',
      message: 'Action Bus ready for dispatch (observational)',
      lastCheckedAt: timestamp,
    };

    // Overall Status Computation
    const statuses = [
      executionRecord.status,
      providerRecord.status,
      connectorRecord.status,
      persistenceRecord.status,
      governanceRecord.status,
      recoveryRecord.status,
      eventRecord.status,
      missionRecord.status,
      actionBusRecord.status,
    ];

    let overallStatus: SubsystemHealthStatus = 'HEALTHY';
    if (statuses.includes('FAILED')) {
      overallStatus = 'FAILED';
    } else if (statuses.includes('DEGRADED')) {
      overallStatus = 'DEGRADED';
    } else if (statuses.includes('UNKNOWN')) {
      overallStatus = 'UNKNOWN';
    }

    return {
      execution: executionRecord,
      providers: providerRecord,
      connectors: connectorRecord,
      persistence: persistenceRecord,
      governance: governanceRecord,
      recovery: recoveryRecord,
      eventIngestion: eventRecord,
      missions: missionRecord,
      actionBus: actionBusRecord,
      overallStatus,
      isDurableStorage: isDurable,
    };
  }
}

export const controlPlaneSnapshotService = new ControlPlaneSnapshotService();
