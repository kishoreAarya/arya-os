import { GenerationType, CapabilitiesManifest } from './creator';
import { FactSource } from './productionDecision';

/**
 * Stage 10: Timeline fact source attribution.
 * Strictly adheres to Stage 9 5-source provenance model (Section 17).
 */
export type TimelineFactSource = FactSource;

/**
 * Deterministic shot lifecycle state.
 * Non-autonomous: READY does NOT trigger execution.
 */
export type ShotLifecycleStatus =
  | 'DRAFT'
  | 'CONFIGURING'
  | 'BLOCKED'
  | 'READY'
  | 'QUEUED'
  | 'GENERATING'
  | 'COMPLETE'
  | 'FAILED'
  | 'RECOVERY_REQUIRED';

/**
 * Project persistence and recovery UX states (Stage 11).
 */
export type ProjectRecoveryState =
  | 'NEW'
  | 'RECOVERABLE'
  | 'RESTORED'
  | 'RECOVERY_REQUIRED'
  | 'SAVED'
  | 'UNSAVED';

/**
 * Versioned local storage envelope for persisted projects (Stage 11).
 */
export interface PersistedProjectEnvelope {
  schemaVersion: number;
  savedAt: string;
  project: Project;
}

/**
 * Sequence-level production status.
 */
export type SequenceStatus =
  | 'READY'
  | 'BLOCKED'
  | 'PARTIALLY_READY'
  | 'IN_PROGRESS'
  | 'COMPLETE';

/**
 * Status of continuity checks.
 * UNAVAILABLE is used whenever required data is not supplied.
 */
export type ContinuityStatus =
  | 'PASS'
  | 'WARNING'
  | 'BLOCKED'
  | 'UNAVAILABLE';

/**
 * Start frame continuity state between adjacent/dependent shots.
 */
export type StartFrameContinuityStatus =
  | 'REQUIRED'
  | 'PROVIDED'
  | 'MISSING'
  | 'UNAVAILABLE'
  | 'NOT_APPLICABLE';

/**
 * Declared character continuity metadata.
 */
export interface CharacterContinuityRequirement {
  characterId?: string;
  name?: string;
  declaredAppearance?: string;
  wardrobe?: string;
  hair?: string;
  visualIdentityReferences?: string[];
  source: TimelineFactSource;
}

/**
 * Declared environment continuity metadata.
 */
export interface EnvironmentContinuityRequirement {
  location?: string;
  environmentType?: string;
  timeOfDay?: string;
  weather?: string;
  lighting?: string;
  sceneDescription?: string;
  source: TimelineFactSource;
}

/**
 * Declared visual continuity metadata.
 */
export interface VisualContinuityRequirement {
  aspectRatio?: string;
  resolution?: string;
  visualStyle?: string;
  cameraRequirements?: string;
  lightingRequirements?: string;
  colorRequirements?: string;
  source: TimelineFactSource;
}

/**
 * Declared temporal continuity metadata.
 */
export interface TemporalContinuityRequirement {
  order: number;
  predecessorId?: string;
  successorId?: string;
  durationSeconds?: number;
  requiresStartFrameFromPredecessor: boolean;
  source: TimelineFactSource;
}

/**
 * Result of a single continuity check dimension.
 */
export interface ContinuityCheckResult {
  status: ContinuityStatus;
  detail: string;
  source: TimelineFactSource;
  missingFields?: string[];
  conflicts?: string[];
  matchedFields?: string[];
}

/**
 * Comprehensive continuity evaluation for a shot.
 */
export interface ShotContinuityReport {
  character: ContinuityCheckResult;
  environment: ContinuityCheckResult;
  visual: ContinuityCheckResult;
  temporal: ContinuityCheckResult;
  startFrame: {
    status: StartFrameContinuityStatus;
    sourceShotId?: string;
    assetUrl?: string;
    detail: string;
    source: TimelineFactSource;
  };
}

/**
 * Deterministic shot validation results.
 */
export interface ShotValidationResult {
  isValid: boolean;
  readiness: 'READY' | 'BLOCKED' | 'WARNING';
  reasons: string[];
  reasonCodes: string[];
  preflightReady: boolean;
  dependenciesSatisfied: boolean;
  startFrameSatisfied: boolean;
}

/**
 * Normalized Shot Data Model (ProductionShot).
 */
export interface Shot {
  id: string;
  shotId?: string; // Prompt Section 6 alias
  sequenceId: string;
  order: number;
  title: string;
  description?: string;
  prompt: string;
  negativePrompt?: string;
  generationType: GenerationType;
  selectedModel: string;
  selectedProvider: string;
  aspectRatio: string;
  resolution?: string;
  duration?: number;
  startFrame?: string;
  endFrame?: string;
  referenceAssets?: string[];
  characterIds?: string[];
  locationId?: string;
  timeOfDay?: string;
  continuityRequirements?: {
    character?: CharacterContinuityRequirement;
    environment?: EnvironmentContinuityRequirement;
    visual?: VisualContinuityRequirement;
    temporal?: TemporalContinuityRequirement;
  };
  characterRequirements?: CharacterContinuityRequirement;
  environmentRequirements?: EnvironmentContinuityRequirement;
  visualRequirements?: VisualContinuityRequirement;
  temporalRequirements?: TemporalContinuityRequirement;
  dependencyShotIds: string[];
  predecessorShotId?: string;
  successorShotId?: string;
  status: ShotLifecycleStatus;
  readiness: 'READY' | 'BLOCKED' | 'WARNING';
  preflightStatus?: 'READY' | 'BLOCKED' | 'WARNING';
  continuityStatus?: ContinuityStatus;
  validationResults: ShotValidationResult;
  continuityReport: ShotContinuityReport;
  outputAssetUrl?: string;
  outputJobId?: string;
  provenance: TimelineFactSource;
  createdAt?: string;
  updatedAt?: string;
  failureDetails?: {
    category: string;
    stage: string;
    reason: string;
    retryEligible: boolean;
  };
  dependencyState?: string;
  metadata_json?: Record<string, any>;
  firstFrame?: string;
  lastFrame?: string;
}

export type ProductionShot = Shot;

/**
 * Normalized Sequence Data Model (ProductionSequence).
 */
export interface Sequence {
  id: string;
  sequenceId?: string; // Prompt Section 7 alias
  projectId: string;
  order: number;
  title: string;
  description?: string;
  shots: Shot[];
  activeShotId?: string;
  status: SequenceStatus;
  sequenceStatus?: SequenceStatus;
  statusReasons: string[];
  totalShots: number;
  readyShots: number;
  blockedShots: number;
  warningShots?: number;
  inFlightShots: number;
  completeShots: number;
  completedShots?: number;
  totalDurationSeconds: number;
  totalDuration?: number;
  continuityWarnings?: string[];
  sequencePreflightStatus?: 'READY' | 'BLOCKED' | 'WARNING';
  createdAt: string;
  updatedAt: string;
}

export type ProductionSequence = Sequence;

/**
 * Normalized Project Data Model.
 */
export interface Project {
  id: string;
  title: string;
  description?: string;
  sequences: Sequence[];
  activeSequenceId: string;
  activeShotId?: string;
  createdAt: string;
  updatedAt: string;
  metadata?: Record<string, any>;
}

/**
 * Sequence Telemetry Summary for OperationalStrip integration.
 */
export interface SequenceOperationalSummary {
  sequenceNumber: string;
  sequenceTitle: string;
  totalShots: number;
  readyShots: number;
  blockedShots: number;
  inFlightShots: number;
  completeShots: number;
}

/**
 * Read-Only Sequence Execution Plan (Section 18).
 */
export interface SequenceExecutionPlanItem {
  order: number;
  shotId: string;
  title: string;
  endpoint: string;
  payload: {
    prompt: string;
    generation_type: GenerationType;
    model: string;
    provider?: string;
    aspect_ratio: string;
    resolution?: string;
    duration?: number;
    start_frame?: string;
    end_frame?: string;
    reference_image?: string;
  };
  dependencies: string[];
  status: ShotLifecycleStatus;
  readiness: 'READY' | 'BLOCKED' | 'WARNING';
}

export interface SequenceExecutionPlan {
  sequenceId: string;
  sequenceTitle: string;
  totalShots: number;
  totalDuration: number;
  planStatus: SequenceStatus;
  shots: SequenceExecutionPlanItem[];
}
