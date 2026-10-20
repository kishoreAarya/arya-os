/**
 * AryaOS V1 — Spatial Interface Type Definitions
 * Phase 1 & 2: Spatial World Shell, Environment, Camera Rig, Monolith, GLB Pipeline & HUD
 */

import {
  SpatialModuleData,
  SpatialModuleId,
  SpatialShotCardData,
  SpatialCorridorSummary,
} from './spatialModules';
import { Project, Shot } from './productionTimeline';
import { GenerationJob, CapabilitiesManifest } from './creator';
import { ProductionRecommendation } from './productionDecision';
import { SystemOperationalState } from './productionRun';
import { AryaIntent, AryaIntentStage, AryaJobPackage } from './spatialIntent';

export type SpatialCameraState =
  | 'ENTRY'
  | 'APPROACH'
  | 'HUB'
  | 'SYSTEMS'
  | 'CORRIDOR'
  | 'COMMAND'
  | 'MEMORY'
  | 'PLANNING'
  | 'ROUTING'
  | 'EXECUTION'
  | 'ARTIFACT';

export type SpatialStage =
  | 'AWAKENING'
  | 'CORE'
  | 'MEMORY'
  | 'PLANNING'
  | 'ROUTING'
  | 'COMMAND'
  | 'EXECUTION'
  | 'ARTIFACT'
  | 'CREATIONS';

export interface SpatialStageConfig {
  stage: number;
  id: SpatialStage;
  label: string;
  subtitle: string;
  cameraState: SpatialCameraState;
  progress: number;
  description: string;
}

export const SPATIAL_STAGES: SpatialStageConfig[] = [
  {
    stage: 1,
    id: 'AWAKENING',
    label: 'SYSTEM AWAKENS',
    subtitle: 'ATMOSPHERIC PERIMETER',
    cameraState: 'ENTRY',
    progress: 0.0,
    description: 'Dark cinematic intro — Monolith silhouette and floating obsidian islands',
  },
  {
    stage: 2,
    id: 'CORE',
    label: 'ARYAOS CORE',
    subtitle: 'INTELLIGENCE CENTER',
    cameraState: 'HUB',
    progress: 0.15,
    description: 'Central cybernetic intelligence engine — Reasoning, state, and decision core',
  },
  {
    stage: 3,
    id: 'MEMORY',
    label: 'CONTEXTUAL MEMORY',
    subtitle: 'EPISODIC ARCHIVE',
    cameraState: 'MEMORY',
    progress: 0.3,
    description: 'Holographic memory stack — Character, channel, and performance history',
  },
  {
    stage: 4,
    id: 'PLANNING',
    label: 'WORKFLOW PLANNING',
    subtitle: 'TIMELINE COMPILATION',
    cameraState: 'PLANNING',
    progress: 0.45,
    description: 'Multi-shot sequence synthesis and dependency graph compilation',
  },
  {
    stage: 5,
    id: 'ROUTING',
    label: 'PROVIDER ROUTER',
    subtitle: 'MODEL CONSTELLATION',
    cameraState: 'ROUTING',
    progress: 0.6,
    description: 'Arbitration constellation across FLUX, Kling, Runway, and ComfyUI models',
  },
  {
    stage: 6,
    id: 'COMMAND',
    label: 'INTENTION → EXECUTION',
    subtitle: 'JOB PACKAGE COMPILATION',
    cameraState: 'COMMAND',
    progress: 0.72,
    description: 'User prompt decomposition and sealed AryaJobPackage boundary',
  },
  {
    stage: 7,
    id: 'EXECUTION',
    label: 'LIVE PRODUCTION',
    subtitle: 'EXECUTION GATEWAY',
    cameraState: 'EXECUTION',
    progress: 0.85,
    description: 'Direct handoff to OpenMontage generation engine and live telemetry',
  },
  {
    stage: 8,
    id: 'ARTIFACT',
    label: 'ARTIFACT EXPLORATION',
    subtitle: 'MULTI-SHOT CORRIDOR',
    cameraState: 'CORRIDOR',
    progress: 0.95,
    description: 'Spatial media wall with verified first-frame and last-frame anchors',
  },
  {
    stage: 9,
    id: 'CREATIONS',
    label: 'CREATIONS UNIVERSE',
    subtitle: 'PRODUCTION HISTORY',
    cameraState: 'CORRIDOR',
    progress: 1.0,
    description: 'Comprehensive historical gallery across projects and sequences',
  },
];

export interface SpatialCameraWaypoint {
  position: [number, number, number];
  target: [number, number, number];
  fov: number;
  label: string;
  code: string;
  description: string;
  progress: number;
}

export interface SpatialFocusTarget {
  position: [number, number, number];
  target: [number, number, number];
  fov?: number;
  label?: string;
}

export interface TemporalDependencyInfo {
  predecessorId?: string;
  predecessorTitle?: string;
  anchorType?: string;
  anchorStatus?: 'VERIFIED' | 'PENDING' | 'MISSING' | 'NOT_APPLICABLE' | string;
  continuityStatus?: 'PASS' | 'WARNING' | 'BLOCKED' | 'UNAVAILABLE' | string;
  conditioningTarget?: 'FIRST_FRAME' | 'REFERENCE' | 'NONE' | string;
  sourceArtifactPath?: string;
  sourceArtifactUrl?: string;
  validationLevel?: string;
  details?: string[];
  dimensionsMatch?: boolean;
  aspectRatioMatch?: boolean;
  width?: number;
  height?: number;
  sha256?: string;
}

export interface SpatialInspectorData {
  category: 'CORE' | 'SUBSYSTEM' | 'SHOT' | 'JOB_PACKAGE';
  id: string;
  title: string;
  subtitle?: string;
  status: string;
  statusVariant?: 'neutral' | 'success' | 'warning' | 'error' | 'active';
  metrics: { label: string; value: string | number }[];
  details: string[];
  provenance?: string;
  actionLabel?: string;
  onAction?: () => void;
  secondaryActionLabel?: string;
  onSecondaryAction?: () => void;
  thumbnailUrl?: string;
  firstFrameUrl?: string;
  lastFrameUrl?: string;
  referenceImageUrl?: string;
  remediation?: string;
  jobPackage?: AryaJobPackage;
  temporalDependency?: TemporalDependencyInfo;
}

export interface SpatialProductionTelemetry {
  systemStatus: string;
  activeProjectTitle: string;
  activeShotTitle: string;
  workflowState: string;
  activeProvider: string;
  activeModel: string;
  executionStatus: string;
  productionProgress: string;
  lastEvent: string;
  runIdentifier: string;
  errorState?: string | null;
  warningState?: string | null;
}

export const CAMERA_WAYPOINTS: Record<SpatialCameraState, SpatialCameraWaypoint> = {
  ENTRY: {
    position: [0, 5.2, 18.0],
    target: [0, 1.8, 0],
    fov: 46,
    label: 'SYSTEM PERIMETER',
    code: 'SEC-01',
    description: 'Far volumetric perimeter — AryaOS monolith silhouette',
    progress: 0.0,
  },
  APPROACH: {
    position: [0, 3.2, 10.5],
    target: [0, 2.0, 0],
    fov: 40,
    label: 'ORBITAL APPROACH',
    code: 'SEC-02',
    description: 'Mid-range transition through atmospheric depth',
    progress: 0.5,
  },
  HUB: {
    position: [0, 2.2, 5.8],
    target: [0, 2.0, 0],
    fov: 38,
    label: 'CORE COMMAND HUB',
    code: 'SEC-03',
    description: 'Focal workstation view of central quantum monolith',
    progress: 1.0,
  },
  SYSTEMS: {
    position: [-3.8, 4.2, 8.4],
    target: [0, 1.6, 0],
    fov: 44,
    label: 'SYSTEM MODULES',
    code: 'SEC-04',
    description: 'Orbital vantage of Memory, Planning, Routing, and Execution modules',
    progress: 0.7,
  },
  CORRIDOR: {
    position: [3.2, 2.2, 7.8],
    target: [0, 1.2, 3.8],
    fov: 42,
    label: 'MULTI-SHOT CORRIDOR',
    code: 'SEC-05',
    description: 'Linear cinematic corridor of production shots and continuity links',
    progress: 0.85,
  },
  COMMAND: {
    position: [0, 1.8, 4.4],
    target: [0, 1.8, 0],
    fov: 36,
    label: 'EXECUTIVE COMMAND',
    code: 'SEC-06',
    description: 'Direct console alignment with central intelligence monolith',
    progress: 1.0,
  },
  MEMORY: {
    position: [-3.4, 2.0, -1.2],
    target: [-4.2, 1.4, -3.0],
    fov: 38,
    label: 'MEMORY ARCHIVE',
    code: 'SEC-07',
    description: 'Holographic data storage cube and lineage cache',
    progress: 0.3,
  },
  PLANNING: {
    position: [-2.6, 1.8, 3.4],
    target: [-3.6, 0.9, 1.8],
    fov: 38,
    label: 'PLANNING DAIS',
    code: 'SEC-08',
    description: 'Tiered rotating analyzer rings and sequence compiler',
    progress: 0.45,
  },
  ROUTING: {
    position: [2.6, 1.8, 3.4],
    target: [3.6, 0.9, 1.8],
    fov: 38,
    label: 'PROVIDER CONSTELLATION',
    code: 'SEC-09',
    description: 'Celestial router cage and model arbitration matrix',
    progress: 0.6,
  },
  EXECUTION: {
    position: [3.4, 2.0, -1.2],
    target: [4.2, 1.4, -3.0],
    fov: 38,
    label: 'EXECUTION GATEWAY',
    code: 'SEC-10',
    description: 'Heavy industrial power platform and OpenMontage feed',
    progress: 0.85,
  },
  ARTIFACT: {
    position: [3.2, 2.2, 7.8],
    target: [0, 1.2, 3.8],
    fov: 42,
    label: 'SPATIAL PRODUCTION CORRIDOR',
    code: 'SEC-11',
    description: 'Floating cinematic artifact screens with frame anchor links',
    progress: 0.95,
  },
};

/**
 * Interpolates camera coordinates and target smoothly along spatial progress [0.0 -> 1.0]
 * Smooth transition through ENTRY -> APPROACH -> HUB (Phase 2 Specification)
 */
export function interpolateSpatialProgress(progress: number): {
  position: [number, number, number];
  target: [number, number, number];
  fov: number;
} {
  const clamped = Math.max(0, Math.min(1, progress));

  let from: SpatialCameraWaypoint;
  let to: SpatialCameraWaypoint;
  let factor: number;

  if (clamped <= 0.5) {
    from = CAMERA_WAYPOINTS.ENTRY;
    to = CAMERA_WAYPOINTS.APPROACH;
    factor = clamped / 0.5;
  } else {
    from = CAMERA_WAYPOINTS.APPROACH;
    to = CAMERA_WAYPOINTS.HUB;
    factor = (clamped - 0.5) / 0.5;
  }

  // Smooth cosine easing
  const eased = 0.5 - 0.5 * Math.cos(factor * Math.PI);

  const position: [number, number, number] = [
    from.position[0] + (to.position[0] - from.position[0]) * eased,
    from.position[1] + (to.position[1] - from.position[1]) * eased,
    from.position[2] + (to.position[2] - from.position[2]) * eased,
  ];

  const target: [number, number, number] = [
    from.target[0] + (to.target[0] - from.target[0]) * eased,
    from.target[1] + (to.target[1] - from.target[1]) * eased,
    from.target[2] + (to.target[2] - from.target[2]) * eased,
  ];

  const fov = from.fov + (to.fov - from.fov) * eased;

  return { position, target, fov };
}

/**
 * Interpolates camera coordinates and target smoothly along the 9-stage spatial narrative
 */
export function interpolateStageProgress(progress: number): {
  position: [number, number, number];
  target: [number, number, number];
  fov: number;
} {
  const clamped = Math.max(0, Math.min(1, progress));

  const stops: { t: number; wp: SpatialCameraWaypoint }[] = [
    { t: 0.0, wp: CAMERA_WAYPOINTS.ENTRY },
    { t: 0.12, wp: CAMERA_WAYPOINTS.HUB },
    { t: 0.25, wp: CAMERA_WAYPOINTS.MEMORY },
    { t: 0.38, wp: CAMERA_WAYPOINTS.PLANNING },
    { t: 0.50, wp: CAMERA_WAYPOINTS.ROUTING },
    { t: 0.62, wp: CAMERA_WAYPOINTS.COMMAND },
    { t: 0.75, wp: CAMERA_WAYPOINTS.EXECUTION },
    { t: 0.88, wp: CAMERA_WAYPOINTS.ARTIFACT },
    { t: 1.0, wp: CAMERA_WAYPOINTS.CORRIDOR },
  ];

  let from = stops[0];
  let to = stops[stops.length - 1];

  for (let i = 0; i < stops.length - 1; i++) {
    if (clamped >= stops[i].t && clamped <= stops[i + 1].t) {
      from = stops[i];
      to = stops[i + 1];
      break;
    }
  }

  const span = to.t - from.t;
  const factor = span > 0 ? (clamped - from.t) / span : 0;
  const eased = 0.5 - 0.5 * Math.cos(factor * Math.PI);

  const position: [number, number, number] = [
    from.wp.position[0] + (to.wp.position[0] - from.wp.position[0]) * eased,
    from.wp.position[1] + (to.wp.position[1] - from.wp.position[1]) * eased,
    from.wp.position[2] + (to.wp.position[2] - from.wp.position[2]) * eased,
  ];

  const target: [number, number, number] = [
    from.wp.target[0] + (to.wp.target[0] - from.wp.target[0]) * eased,
    from.wp.target[1] + (to.wp.target[1] - from.wp.target[1]) * eased,
    from.wp.target[2] + (to.wp.target[2] - from.wp.target[2]) * eased,
  ];

  const fov = from.wp.fov + (to.wp.fov - from.wp.fov) * eased;

  return { position, target, fov };
}

export interface SpatialTelemetry {
  cameraState: SpatialCameraState;
  coordinates: { x: number; y: number; z: number };
  systemStatus: 'STANDBY' | 'CALIBRATING' | 'ONLINE' | 'ACTIVE';
  activeSector: string;
  coreOutputKw: number;
  spatialProgress?: number;
}

export interface SpatialWorldProps {
  initialCameraState?: SpatialCameraState;
  initialStage?: SpatialStage;
  spatialProgress?: number;
  onOpenStudio?: () => void;
  onOpenStudioWithShot?: (shot: Shot | SpatialShotCardData) => void;
  className?: string;
  style?: React.CSSProperties;
  customGlbPath?: string;
  project?: Project;
  activeShotId?: string;
  onSelectShot?: (shot: Shot) => void;
  selectedModuleId?: SpatialModuleId;
  onSelectModule?: (moduleId: SpatialModuleId) => void;
  modules?: SpatialModuleData[];
  currentJob?: GenerationJob | null;
  productionRecommendation?: ProductionRecommendation | null;
  systemOperationalState?: SystemOperationalState;
  historyCount?: number;
  errorState?: string | null;
  focusTarget?: SpatialFocusTarget | null;
  onFocusTargetChange?: (target: SpatialFocusTarget | null) => void;
  inspectorData?: SpatialInspectorData | null;
  onCloseInspector?: () => void;
  isCinematicMode?: boolean;
  onCinematicModeChange?: (active: boolean) => void;
  isAudioEnabled?: boolean;
  onAudioToggle?: (enabled: boolean) => void;
  selectedSequenceId?: string;
  onSelectSequence?: (sequenceId: string) => void;
  onToggleReducedMotion?: () => void;
  overrideReducedMotion?: boolean;
  capabilitiesManifest?: CapabilitiesManifest | null;
  onProjectChange?: (project: Project) => void;
  onDispatchExecution?: (pkg: AryaJobPackage) => Promise<void>;
  activeJobPackage?: AryaJobPackage | null;
  syncStatus?: 'ONLINE' | 'OFFLINE' | 'SYNCING' | 'ERROR';
  activeStage?: SpatialStage;
  onSelectStage?: (stage: SpatialStage) => void;
}

export interface SpatialHudOverlayProps {
  cameraState: SpatialCameraState;
  onSelectCameraState: (state: SpatialCameraState) => void;
  activeStage?: SpatialStage;
  onSelectStage?: (stage: SpatialStage) => void;
  onOpenStudio?: () => void;
  onOpenStudioWithShot?: (shot: Shot | SpatialShotCardData) => void;
  telemetry?: Partial<SpatialTelemetry>;
  spatialProgress?: number;
  onProgressChange?: (progress: number) => void;
  selectedModule?: SpatialModuleData | null;
  onSelectModule?: (id: SpatialModuleId) => void;
  selectedShot?: SpatialShotCardData | null;
  corridorSummary?: SpatialCorridorSummary;
  productionTelemetry?: SpatialProductionTelemetry;
  inspectorData?: SpatialInspectorData | null;
  onCloseInspector?: () => void;
  onInspectCore?: () => void;
  focusTarget?: SpatialFocusTarget | null;
  isCinematicMode?: boolean;
  onToggleCinematicMode?: () => void;
  isAudioEnabled?: boolean;
  onToggleAudio?: () => void;
  isReducedMotion?: boolean;
  onToggleReducedMotion?: () => void;
  onOpenShortcuts?: () => void;
  sequences?: { id: string; title: string; order: number }[];
  activeSequenceId?: string;
  onSelectSequence?: (id: string) => void;
  // Phase 7: Command bar & Job Package Integration
  intentStage?: AryaIntentStage;
  activeIntent?: AryaIntent | null;
  activeJobPackage?: AryaJobPackage | null;
  onSubmitCommand?: (text: string) => void;
  onInspectJobPackage?: () => void;
  onDispatchExecution?: () => void;
  isDispatching?: boolean;
}

export interface SpatialModelViewerProps {
  modelPath: string;
  position?: [number, number, number];
  scale?: number | [number, number, number];
  rotation?: [number, number, number];
  isReducedMotion?: boolean;
  pointer?: { x: number; y: number };
  onCoreClick?: () => void;
  onError?: (error: Error) => void;
  systemState?: string;
  intentStage?: AryaIntentStage;
}

export interface SpatialCoreProps {
  modelPath?: string;
  isReducedMotion?: boolean;
  pointer?: { x: number; y: number };
  activeState?: SpatialCameraState;
  onCoreClick?: () => void;
  systemState?: string;
  intentStage?: AryaIntentStage;
}

export interface SpatialMonolithProps {
  isReducedMotion?: boolean;
  pointer?: { x: number; y: number };
  activeState?: SpatialCameraState;
  onCoreClick?: () => void;
  glbModelPath?: string;
  systemState?: string;
  intentStage?: AryaIntentStage;
}

export interface SpatialEnvironmentProps {
  isReducedMotion?: boolean;
  enableReflections?: boolean;
}

export interface SpatialCameraRigProps {
  cameraState: SpatialCameraState;
  spatialProgress?: number;
  pointer: { x: number; y: number };
  isReducedMotion: boolean;
  focusTarget?: SpatialFocusTarget | null;
}
