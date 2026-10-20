/**
 * AryaOS V1 — Spatial Functional Control Layer & Intent Types
 * Phase 7: Intent Lifecycle, Intent Object, and Formal Job Package Boundary Contract
 */

import { GenerationType, CreatorGeneratePayload } from './creator';
import {
  ContinuityStatus,
  StartFrameContinuityStatus,
  ShotLifecycleStatus,
} from './productionTimeline';

export type AryaIntentStage =
  | 'IDLE'
  | 'INTENTION'
  | 'ANALYZING'
  | 'PLANNING'
  | 'ROUTING'
  | 'READY'
  | 'DISPATCHING'
  | 'EXECUTING'
  | 'BLOCKED'
  | 'FAILED';

export interface AryaParsedDirectives {
  cleanPrompt: string;
  generationType: GenerationType;
  durationSeconds?: number;
  aspectRatio: string;
  resolution?: string;
  preferredStyle?: string;
  constraints: string[];
  referenceRequirements?: {
    requiresStartFrame: boolean;
    requiresEndFrame: boolean;
    requiresReferenceImage: boolean;
  };
  inferredPredecessor?: boolean;
}

export interface AryaIntent {
  id: string;
  rawInput: string;
  timestamp: string;
  stage: AryaIntentStage;
  projectId: string;
  sequenceId: string;
  directives: AryaParsedDirectives;
  activeBlocker?: {
    stage: 'PLANNING' | 'ROUTING' | 'MEMORY' | 'EXECUTION';
    reason: string;
    detail: string;
  };
}

/**
 * AryaJobPackage — The formal immutable boundary contract between:
 * ARYAOS DECISION MAKING / ORCHESTRATION (What, When, Which Route, Which References)
 * and
 * EXECUTION LAYER (How the media is generated).
 */
export interface AryaJobPackage {
  jobPackageId: string;
  intentId?: string;
  createdAt: string;
  projectId: string;
  sequenceId: string;
  shotId: string;
  shotOrder: number;

  // 1. Planning Layer Contract
  plan: {
    title: string;
    prompt: string;
    generationType: GenerationType;
    durationSeconds?: number;
    mode?: string;
    sourceShot?: string;
    fps?: number;
    predecessorShotId?: string;
    successorShotId?: string;
    dependencies: string[];
    isFirstShotInSequence: boolean;
  };

  // 2. References & Keyframe Anchors (Part I)
  references: {
    firstFrame?: string;
    lastFrame?: string;
    startFrameUrl?: string;
    endFrameUrl?: string;
    referenceImageUrl?: string;
    referenceAssets: string[];
    referenceVideos?: string[];
    sourceShot?: string;
    visualIdentityReferences?: string[];
  };

  // 3. Routing Arbitration Contract (Part E)
  modelRoute: {
    provider: string;
    model: string;
    modelName: string;
    mode: GenerationType;
    preflightReady: boolean;
    preflightReasons: string[];
    availability: 'AVAILABLE' | 'UNAVAILABLE';
    estimatedCostUsd?: number;
    qualityTier?: string;
  };

  // 4. Shot Configuration
  shotConfiguration: {
    aspectRatio: string;
    resolution?: string;
    duration?: number;
    fps?: number;
  };

  // 5. Continuity Requirements Evaluated (Part D)
  continuityRequirements: {
    character: ContinuityStatus;
    environment: ContinuityStatus;
    visual: ContinuityStatus;
    temporal: ContinuityStatus;
    startFrame: StartFrameContinuityStatus;
  };

  // 6. Output Destination
  outputRequirements: {
    destination: 'ARYAOS_CORRIDOR_STREAM';
    targetFormat: string;
  };

  // 7. Architectural Boundary Guard
  decisionBoundary: 'ARYAOS_ORCHESTRATION_VALIDATED';

  // 8. Low-Level Execution Payload to be handed to the execution engine
  executionPayload: CreatorGeneratePayload;
}
