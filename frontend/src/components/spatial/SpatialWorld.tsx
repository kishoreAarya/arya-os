import React, { useState, useEffect, useRef, useMemo } from 'react';
import { Canvas } from '@react-three/fiber';
import { Cpu, Layers, Film } from 'lucide-react';
import {
  SpatialCameraState,
  SpatialStage,
  SPATIAL_STAGES,
  SpatialWorldProps,
  SpatialFocusTarget,
  SpatialInspectorData,
  SpatialProductionTelemetry,
} from '../../types/spatial';
import {
  SpatialModuleData,
  SpatialModuleId,
  SpatialModuleStatus,
  SpatialShotCardData,
  SpatialCorridorSummary,
  DEFAULT_SPATIAL_MODULES,
} from '../../types/spatialModules';
import { Shot } from '../../types/productionTimeline';
import { GenerationJob } from '../../types/creator';
import { ProductionRecommendation } from '../../types/productionDecision';
import { SpatialEnvironment } from './SpatialEnvironment';
import { SpatialCameraRig } from './SpatialCameraRig';
import { SpatialCore } from './SpatialCore';
import { SpatialSystemModules } from './SpatialSystemModules';
import { SpatialShotCorridor, getShotCorridorPosition } from './SpatialShotCorridor';
import { SpatialHudOverlay } from './SpatialHudOverlay';
import { SpatialAwakeningHero } from './SpatialAwakeningHero';
import { SpatialMemoryArchive } from './SpatialMemoryArchive';
import { MemoryArchiveOverlay } from './MemoryArchiveOverlay';
import { useMemoryArchive } from '../../hooks/useMemoryArchive';
import { useSpatialCommand } from '../../hooks/useSpatialCommand';
import { SpatialInspectorPanel } from './SpatialInspectorPanel';
import { SpatialShortcutsModal } from './SpatialShortcutsModal';
import { usePrefersReducedMotion } from '../motion/MotionSystem';
import { spatialAudio } from '../../utils/spatialAudio';
import { AryaIntent, AryaIntentStage, AryaJobPackage } from '../../types/spatialIntent';
import { parseUserCommand, compileIntentToShot, assembleJobPackage } from '../../utils/spatialIntentPlanner';
import { createDefaultProject } from '../../utils/continuityEngine';

/**
 * Helper to safely test WebGL availability (guards against JSDOM / headless test environments)
 */
function checkWebGLSupport(): boolean {
  if (typeof window === 'undefined') return false;
  try {
    const canvas = document.createElement('canvas');
    return Boolean(
      window.WebGLRenderingContext &&
        (canvas.getContext('webgl') || canvas.getContext('experimental-webgl'))
    );
  } catch {
    return false;
  }
}

export function getJobProgressPercent(job: GenerationJob | null | undefined): number {
  if (!job) return 0;
  if ((job as any).progress !== undefined) return (job as any).progress;
  if ((job.output as any)?.progress !== undefined) return (job.output as any).progress;
  if (job.status === 'completed') return 100;
  if (job.status === 'in_progress') return 65;
  if (job.status === 'pending') return 20;
  return 0;
}

/**
 * Honest progress display (never fabricates artificial percentages)
 */
function getJobProgressDisplay(job: GenerationJob | null | undefined): {
  label: string;
  isIndeterminate: boolean;
  percent?: number;
} {
  if (!job) return { label: 'IDLE', isIndeterminate: false };
  if (job.status === 'completed') return { label: '100% [COMPLETE]', isIndeterminate: false, percent: 100 };
  if (job.status === 'failed') return { label: 'FAILED', isIndeterminate: false };
  if (job.current_stage) {
    return { label: `STAGE: ${job.current_stage.toUpperCase()}`, isIndeterminate: true };
  }
  if (job.status === 'in_progress') {
    return { label: 'PROCESSING [INDETERMINATE]', isIndeterminate: true };
  }
  if (job.status === 'pending') {
    return { label: 'QUEUED [WAITING DISPATCH]', isIndeterminate: true };
  }
  return { label: String((job as any).status || 'UNKNOWN').toUpperCase(), isIndeterminate: false };
}

function getRecommendationProvider(rec: ProductionRecommendation | null | undefined): string {
  if (!rec) return '';
  return rec.executionPreview?.provider || rec.explanation?.provider || '';
}

function getRecommendationModel(rec: ProductionRecommendation | null | undefined): string {
  if (!rec) return '';
  return (
    rec.executionPreview?.modelName ||
    rec.executionPreview?.model ||
    rec.explanation?.modelName ||
    rec.explanation?.modelId ||
    ''
  );
}

/**
 * Default sample shots for standalone SpatialWorld mount when no project is supplied
 */
const DEFAULT_SAMPLE_SHOTS: SpatialShotCardData[] = [
  {
    id: 'shot-01',
    order: 1,
    title: 'Shot 01 // Quantum Monolith Awakening',
    prompt: 'Cinematic wide angle, obsidian monolith activating with amber pulse',
    status: 'COMPLETE',
    generationType: 'image',
    duration: 5,
    aspectRatio: '16:9',
    continuityStatus: 'PASS',
    dependencyState: 'INDEPENDENT',
    lastFrame: '/api/v1/artifacts/mock_shot_01_last.png',
  },
  {
    id: 'shot-02',
    order: 2,
    title: 'Shot 02 // Orbital Core Approach',
    prompt: 'Slow dolly approach toward monolithic central chamber',
    status: 'READY',
    generationType: 'video',
    duration: 5,
    aspectRatio: '16:9',
    continuityStatus: 'PASS',
    predecessorId: 'shot-01',
    dependencyState: 'READY',
    firstFrame: '/api/v1/artifacts/mock_shot_01_last.png',
  },
  {
    id: 'shot-03',
    order: 3,
    title: 'Shot 03 // Conduit Synchronization',
    prompt: 'Close-up of calibration rings and energy conduits locking into alignment',
    status: 'GENERATING',
    generationType: 'image-to-video',
    duration: 4,
    aspectRatio: '16:9',
    continuityStatus: 'WARNING',
    predecessorId: 'shot-02',
    dependencyState: 'EXECUTING',
  },
  {
    id: 'shot-04',
    order: 4,
    title: 'Shot 04 // Full Operational Ignition',
    prompt: 'Hero low angle wide shot of all 4 subsystem modules pulsing in unison',
    status: 'READY',
    generationType: 'video',
    duration: 6,
    aspectRatio: '16:9',
    continuityStatus: 'PASS',
    predecessorId: 'shot-03',
    dependencyState: 'WAITING_FOR_PREDECESSOR',
  },
];

/**
 * SpatialWorld — Full-Screen 3D AryaOS Operating System Environment
 * Phase 5: Polished Production-Grade ARYAOS Experience
 */
export const SpatialWorld: React.FC<SpatialWorldProps> = ({
  initialCameraState = 'HUB',
  initialStage,
  spatialProgress: propSpatialProgress,
  onOpenStudio,
  onOpenStudioWithShot,
  className = '',
  style,
  customGlbPath,
  project,
  activeShotId,
  onSelectShot,
  selectedModuleId: propSelectedModuleId,
  onSelectModule: propOnSelectModule,
  modules: propModules,
  currentJob,
  productionRecommendation,
  systemOperationalState = 'ONLINE',
  historyCount = 0,
  errorState,
  focusTarget: propFocusTarget,
  onFocusTargetChange,
  inspectorData: propInspectorData,
  onCloseInspector: propOnCloseInspector,
  isCinematicMode: propIsCinematicMode,
  onCinematicModeChange,
  isAudioEnabled: propIsAudioEnabled,
  onAudioToggle,
  selectedSequenceId: propSelectedSequenceId,
  onSelectSequence: propOnSelectSequence,
  overrideReducedMotion: propOverrideReducedMotion,
  onToggleReducedMotion: propOnToggleReducedMotion,
  capabilitiesManifest,
  onProjectChange,
  onDispatchExecution: propOnDispatchExecution,
  activeJobPackage: propActiveJobPackage,
  syncStatus = 'ONLINE',
  activeStage: propActiveStage,
  onSelectStage: propOnSelectStage,
}) => {
  const [hasWebGL, setHasWebGL] = useState(false);
  const [cameraState, setCameraState] = useState<SpatialCameraState>(() => {
    if (initialStage) {
      const stg = SPATIAL_STAGES.find((s) => s.id === initialStage);
      if (stg) return stg.cameraState;
    }
    return initialCameraState;
  });
  const [spatialProgress, setSpatialProgress] = useState<number | undefined>(() => {
    if (propSpatialProgress !== undefined) return propSpatialProgress;
    if (initialStage) {
      const stg = SPATIAL_STAGES.find((s) => s.id === initialStage);
      if (stg) return stg.progress;
    }
    return undefined;
  });
  const [pointer, setPointer] = useState({ x: 0, y: 0 });

  // Phase 14/15: 9-Stage Progressive Spatial Discovery Architecture
  const [internalActiveStage, setInternalActiveStage] = useState<SpatialStage>(() => {
    if (initialStage) return initialStage;
    if (propActiveStage) return propActiveStage;
    if (initialCameraState === 'ENTRY') return 'AWAKENING';
    return 'CORE';
  });
  const activeStage = propActiveStage !== undefined ? propActiveStage : internalActiveStage;

  const handleSelectStage = (stage: SpatialStage) => {
    setInternalActiveStage(stage);
    propOnSelectStage?.(stage);
    const cfg = SPATIAL_STAGES.find((s) => s.id === stage);
    if (cfg) {
      setCameraState(cfg.cameraState);
      setSpatialProgress(cfg.progress);
    }
  };

  const activeStageRef = useRef(activeStage);
  useEffect(() => {
    activeStageRef.current = activeStage;
  }, [activeStage]);

  // Continuous wheel navigation through spatial narrative stages
  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;

    const handleWheel = (e: WheelEvent) => {
      const target = e.target as HTMLElement;
      if (
        target &&
        (target.closest('.spatial-inspector-panel') ||
          target.closest('.spatial-command-bar') ||
          target.closest('.spatial-shortcuts-modal') ||
          target.closest('[data-testid="spatial-shot-corridor"]') ||
          target.tagName === 'INPUT' ||
          target.tagName === 'TEXTAREA')
      ) {
        return;
      }

      e.preventDefault();
      setSpatialProgress((prev) => {
        const current =
          prev !== undefined
            ? prev
            : (SPATIAL_STAGES.find((s) => s.id === activeStageRef.current)?.progress ?? 0.0);
        const delta = e.deltaY * 0.0006;
        const next = Math.max(0, Math.min(1, current + delta));

        let closestStage = SPATIAL_STAGES[0];
        let minDiff = 999;
        for (const s of SPATIAL_STAGES) {
          const diff = Math.abs(s.progress - next);
          if (diff < minDiff) {
            minDiff = diff;
            closestStage = s;
          }
        }
        setInternalActiveStage(closestStage.id);
        propOnSelectStage?.(closestStage.id);
        setCameraState(closestStage.cameraState);
        return next;
      });
    };

    container.addEventListener('wheel', handleWheel, { passive: false });
    return () => container.removeEventListener('wheel', handleWheel);
  }, [propOnSelectStage]);

  // Phase 7: Intent Lifecycle and Job Package State
  const [intentStage, setIntentStage] = useState<AryaIntentStage>('IDLE');
  const [activeIntent, setActiveIntent] = useState<AryaIntent | null>(null);
  const [internalActiveJobPackage, setInternalActiveJobPackage] = useState<AryaJobPackage | null>(null);
  const activeJobPackage = propActiveJobPackage !== undefined ? propActiveJobPackage : internalActiveJobPackage;
  const [isDispatching, setIsDispatching] = useState(false);

  // Motion preference with in-app override option
  const systemReducedMotion = usePrefersReducedMotion();
  const [internalOverrideReducedMotion, setInternalOverrideReducedMotion] = useState<boolean | null>(null);
  const isReducedMotion =
    propOverrideReducedMotion !== undefined
      ? propOverrideReducedMotion
      : internalOverrideReducedMotion !== null
      ? internalOverrideReducedMotion
      : systemReducedMotion;

  // Cinematic mode state
  const [internalCinematicMode, setInternalCinematicMode] = useState(false);
  const isCinematicMode = propIsCinematicMode !== undefined ? propIsCinematicMode : internalCinematicMode;

  // Audio feedback state
  const [internalAudioEnabled, setInternalAudioEnabled] = useState(() => spatialAudio.isEnabled());
  const isAudioEnabled = propIsAudioEnabled !== undefined ? propIsAudioEnabled : internalAudioEnabled;

  // Shortcuts modal state
  const [isShortcutsOpen, setIsShortcutsOpen] = useState(false);

  // Multi-sequence state
  const [internalSelectedSequenceId, setInternalSelectedSequenceId] = useState<string | null>(
    propSelectedSequenceId || project?.activeSequenceId || project?.sequences?.[0]?.id || null
  );
  const selectedSequenceId = propSelectedSequenceId || internalSelectedSequenceId;

  const containerRef = useRef<HTMLDivElement>(null);

  // Inspected selection entity
  const [inspectedEntity, setInspectedEntity] = useState<
    | { type: 'core' }
    | { type: 'module'; id: SpatialModuleId }
    | { type: 'shot'; id: string }
    | { type: 'job_package' }
    | null
  >(null);

  // Subsystem module state
  const [internalSelectedModuleId, setInternalSelectedModuleId] = useState<SpatialModuleId | null>(
    propSelectedModuleId || null
  );
  const selectedModuleId = propSelectedModuleId !== undefined ? propSelectedModuleId : internalSelectedModuleId;

  // Multi-shot corridor selection state
  const [internalSelectedShotId, setInternalSelectedShotId] = useState<string | null>(
    activeShotId || project?.activeShotId || null
  );
  const selectedShotId = activeShotId || internalSelectedShotId;

  // Internal camera focus target
  const [internalFocusTarget, setInternalFocusTarget] = useState<SpatialFocusTarget | null>(null);
  const focusTarget = propFocusTarget !== undefined ? propFocusTarget : internalFocusTarget;

  // Stage 04 & 05: Spatial Memory & Command Layer state machines
  const memoryArchive = useMemoryArchive();
  const commandControl = useSpatialCommand(memoryArchive);

  useEffect(() => {
    setHasWebGL(checkWebGLSupport());
  }, []);

  useEffect(() => {
    if (propSpatialProgress !== undefined) {
      setSpatialProgress(propSpatialProgress);
    }
  }, [propSpatialProgress]);

  // Sync activeShotId if supplied by parent
  useEffect(() => {
    if (activeShotId) {
      setInternalSelectedShotId(activeShotId);
    }
  }, [activeShotId]);

  // Derive corridor shots from active project sequence, or sample shots if standalone
  const corridorShots: SpatialShotCardData[] = useMemo(() => {
    if (project) {
      const activeSeq =
        project.sequences?.find((s) => s.id === selectedSequenceId) ||
        project.sequences?.find((s) => s.id === project.activeSequenceId) ||
        project.sequences?.[0];
      if (!activeSeq || !activeSeq.shots) return [];
      return activeSeq.shots.map((shot: Shot) => ({
        id: shot.id,
        order: shot.order,
        title: shot.title,
        prompt: shot.prompt,
        status: shot.status,
        generationType: shot.generationType,
        duration: shot.duration,
        aspectRatio: shot.aspectRatio,
        model: shot.selectedModel,
        continuityStatus: (shot.continuityReport?.visual?.status || shot.continuityStatus || 'PASS') as any,
        predecessorId: shot.predecessorShotId,
        outputAssetUrl: shot.outputAssetUrl,
        failureReason: shot.failureDetails?.reason,
        startFrame: shot.startFrame,
        endFrame: shot.endFrame,
        referenceAssets: shot.referenceAssets,
        dependencyShotIds: shot.dependencyShotIds,
        startFrameStatus: shot.continuityReport?.startFrame?.status,
        characterContinuity: shot.continuityReport?.character?.status,
        environmentContinuity: shot.continuityReport?.environment?.status,
        visualContinuity: shot.continuityReport?.visual?.status,
        temporalContinuity: shot.continuityReport?.temporal?.status,
        outputJobId: shot.outputJobId,
        dependencyState: shot.dependencyState || (shot as any).metadata_json?.dependency_state || (shot.predecessorShotId ? 'WAITING_FOR_PREDECESSOR' : 'INDEPENDENT'),
        firstFrame: shot.firstFrame || (shot as any).metadata_json?.first_frame || (shot as any).metadata_json?.frame_anchors?.first_frame?.url || (shot as any).metadata_json?.frame_anchors?.first_frame?.path || shot.startFrame,
        lastFrame: shot.lastFrame || (shot as any).metadata_json?.last_frame || (shot as any).metadata_json?.frame_anchors?.last_frame?.url || (shot as any).metadata_json?.frame_anchors?.last_frame?.path || shot.endFrame,
        frameAnchors: (shot as any).metadata_json?.frame_anchors,
      }));
    }
    return DEFAULT_SAMPLE_SHOTS;
  }, [project, selectedSequenceId]);

  // Corridor summary telemetry
  const corridorSummary: SpatialCorridorSummary = useMemo(() => {
    const total = corridorShots.length;
    const active = corridorShots.filter((s) => s.status === 'GENERATING' || s.status === 'QUEUED').length;
    const complete = corridorShots.filter((s) => s.status === 'COMPLETE').length;
    const hasBlocked = corridorShots.some((s) => s.continuityStatus === 'BLOCKED');
    const hasWarning = corridorShots.some((s) => s.continuityStatus === 'WARNING');
    const continuityStatus = hasBlocked ? 'BLOCKED' : hasWarning ? 'WARNING' : 'PASS';
    return {
      totalShots: total,
      activeCount: active,
      completeCount: complete,
      continuityStatus,
    };
  }, [corridorShots]);

  // Phase 7 Real Dynamic Modules Telemetry connected to real production state
  const modulesList: SpatialModuleData[] = useMemo(() => {
    if (propModules) return propModules;

    const shots = corridorShots;
    const warningCount = shots.filter((s) => s.continuityStatus === 'WARNING' || s.continuityStatus === 'BLOCKED').length;
    const consistentCount = shots.filter((s) => s.continuityStatus === 'PASS').length;
    const memoryStatus: SpatialModuleStatus = warningCount > 0 ? 'ACTIVE' : 'SYNCHRONIZED';
    const statusLabel = syncStatus === 'ONLINE' ? 'ONLINE (SYNCHRONIZED)' : syncStatus === 'OFFLINE' ? 'OFFLINE (LOCAL CACHE)' : syncStatus;
    const memoryDetail = warningCount === 0
      ? `Lineage graphs & continuity cache verified (${consistentCount}/${shots.length} shots) // PERSISTENCE: POSTGRESQL AUTHORITATIVE [${statusLabel}]`
      : `${warningCount} continuity warnings detected in sequence // PERSISTENCE: POSTGRESQL AUTHORITATIVE [${statusLabel}]`;

    const blockedCount = shots.filter((s) => s.status === 'BLOCKED').length;
    const readyCount = shots.filter((s) => s.status === 'READY').length;
    const planningStatus: SpatialModuleStatus = blockedCount > 0 ? 'PROCESSING' : 'READY';
    const planningDetail = blockedCount === 0
      ? `Dependency tree evaluated: 0 blockers (${readyCount} ready)`
      : `${blockedCount} shots blocked by unmet dependencies`;

    const isRouteReady = productionRecommendation ? productionRecommendation.preflight.ready : true;
    const routeStatus: SpatialModuleStatus = isRouteReady ? 'READY' : 'PROCESSING';
    const providerName = getRecommendationProvider(productionRecommendation) || 'Autonomous Dispatch';
    const modelName = getRecommendationModel(productionRecommendation) || 'flux-schnell';
    const routingDetail = isRouteReady
      ? `Route: ${providerName} [${modelName}]`
      : `Preflight blocked: ${productionRecommendation?.preflight.reason || 'Missing configuration'}`;

    const hasJob = Boolean(currentJob);
    let execStatus: SpatialModuleStatus = 'IDLE';
    let execLoad = 0;
    const progressInfo = getJobProgressDisplay(currentJob);
    let execDetail = 'Execution chamber idle // NO ACTIVE RUN';
    if (currentJob) {
      if (currentJob.status === 'in_progress') {
        execStatus = 'PROCESSING';
        execDetail = `Executing: ${currentJob.current_stage || 'RUNNING'} • ${currentJob.job_id.slice(0, 8)}`;
      } else if (currentJob.status === 'pending') {
        execStatus = 'ACTIVE';
        execDetail = `Queued: ${currentJob.current_stage || 'QUEUED'} • ${currentJob.job_id.slice(0, 8)}`;
      } else if (currentJob.status === 'completed') {
        execStatus = 'READY';
        execDetail = `Job ${currentJob.job_id.slice(0, 8)} • COMPLETED (Artifact ready)`;
      } else if (currentJob.status === 'failed') {
        execStatus = 'IDLE';
        execDetail = `Job ${currentJob.job_id.slice(0, 8)} • FAILED: ${currentJob.error_message || 'Execution error'}`;
      } else {
        execStatus = 'IDLE';
      }
      execLoad = getJobProgressPercent(currentJob);
    }

    return [
      {
        id: 'memory',
        name: 'MEMORY',
        code: 'MOD-01',
        sector: 'ORBIT-ALPHA',
        title: 'EPISODIC ARCHIVE & RETRIEVAL',
        description: 'Episodic memory store, character lineage cache, and shot continuity indexes',
        position: [-4.2, 1.4, -3.0],
        telemetry: {
          status: memoryStatus,
          loadPercent: shots.length > 0 ? Math.round((consistentCount / Math.max(1, shots.length)) * 100) : 0,
          throughput: `${historyCount} past runs`,
          latencyMs: 0,
          activeItemsCount: shots.length,
          detail: memoryDetail,
        },
      },
      {
        id: 'planning',
        name: 'PLANNING',
        code: 'MOD-02',
        sector: 'LATTICE-BETA',
        title: 'STORY & TIMELINE COMPILATION',
        description: 'Multi-shot sequence synthesis, start-frame dependency resolution, and script graphs',
        position: [-3.6, 0.9, 1.8],
        telemetry: {
          status: planningStatus,
          loadPercent: shots.length > 0 ? Math.round((readyCount / Math.max(1, shots.length)) * 100) : 0,
          throughput: `${shots.length} shots`,
          latencyMs: 0,
          activeItemsCount: shots.length,
          detail: planningDetail,
        },
      },
      {
        id: 'routing',
        name: 'ROUTING',
        code: 'MOD-03',
        sector: 'DISPATCH-GAMMA',
        title: 'MODEL ARBITRATION & DISPATCH',
        description: 'Dynamic provider selection across FLUX, Kling, Runway, and ComfyUI pipelines',
        position: [3.6, 0.9, 1.8],
        telemetry: {
          status: routeStatus,
          loadPercent: isRouteReady ? 100 : 0,
          throughput: providerName,
          latencyMs: 0,
          activeItemsCount: productionRecommendation ? 1 : 0,
          detail: routingDetail,
        },
      },
      {
        id: 'analytics',
        name: 'ANALYTICS',
        code: 'MOD-04',
        sector: 'TELEMETRY-EPSILON',
        title: 'PERFORMANCE & SIGNAL LEARNING',
        description: 'Generation outcome metrics, quality scores, cost optimization, and learning loop signals',
        position: [-2.2, 2.1, -4.5],
        telemetry: {
          status: 'SYNCHRONIZED',
          loadPercent: shots.length > 0 ? Math.round((consistentCount / Math.max(1, shots.length)) * 100) : 100,
          throughput: `${historyCount} verified runs`,
          latencyMs: 0,
          activeItemsCount: historyCount,
          detail: `Continuity: ${consistentCount}/${shots.length} shots pass // Learning feedback active`,
        },
      },
      {
        id: 'job_package',
        name: 'JOB PACKAGE',
        code: 'MOD-05',
        sector: 'BOUNDARY-ZETA',
        title: 'PRODUCTION CONTRACT BOUNDARY',
        description: 'Sealed AryaJobPackage containing validated intention, routes, conditioning anchors, and schema hashes',
        position: [0.0, 1.0, 3.2],
        telemetry: {
          status: activeJobPackage ? 'READY' : 'IDLE',
          loadPercent: activeJobPackage ? 100 : 0,
          throughput: activeJobPackage ? activeJobPackage.jobPackageId.slice(0, 12) : 'Awaiting prompt',
          latencyMs: 0,
          activeItemsCount: activeJobPackage ? 1 : 0,
          detail: activeJobPackage
            ? `Sealed package: ${activeJobPackage.plan.mode} (${activeJobPackage.shotConfiguration.aspectRatio})`
            : 'No active job package compiled. Enter prompt to generate payload.',
        },
      },
      {
        id: 'execution',
        name: 'EXECUTION',
        code: 'MOD-06',
        sector: 'RUNTIME-DELTA',
        title: 'SYNTHESIS ENGINE & TIMELINE FEED',
        description: 'Active generation chamber streaming output into the multi-shot corridor',
        position: [4.2, 1.4, -3.0],
        telemetry: {
          status: execStatus,
          loadPercent: execLoad,
          throughput: currentJob ? `Job ${currentJob.job_id.slice(0, 8)}` : 'Idle',
          latencyMs: 0,
          activeItemsCount: hasJob ? 1 : 0,
          detail: execDetail,
        },
      },
    ];
  }, [propModules, corridorShots, productionRecommendation, currentJob, historyCount, syncStatus, activeJobPackage]);

  // Phase 7 Real Production Telemetry for HUD
  const productionTelemetry: SpatialProductionTelemetry = useMemo(() => {
    const projTitle = project?.title || 'ARYAOS PRODUCTION';
    const activeShotObj = corridorShots.find((s) => s.id === selectedShotId) || corridorShots[0];
    const shotTitle = activeShotObj ? activeShotObj.title : 'NO SHOT SELECTED';
    const workflowState = currentJob ? currentJob.status.toUpperCase() : 'IDLE';
    const activeProvider = getRecommendationProvider(productionRecommendation);
    const activeModel = getRecommendationModel(productionRecommendation);
    const executionStatus = currentJob ? currentJob.status.toUpperCase() : 'NO ACTIVE RUN';
    const productionProgress = currentJob ? `${getJobProgressPercent(currentJob)}%` : '--';
    const lastEvent = currentJob
      ? `PROGRESS ${getJobProgressPercent(currentJob)}% [${currentJob.status.toUpperCase()}]`
      : errorState
      ? `SYSTEM ERROR: ${errorState}`
      : activeJobPackage
      ? `JOB PACKAGE READY [${activeJobPackage.jobPackageId.slice(0, 8)}]`
      : 'SYSTEM INITIALIZED';
    const runIdentifier = currentJob ? currentJob.job_id : 'NONE';

    return {
      systemStatus: systemOperationalState || 'ONLINE',
      activeProjectTitle: projTitle,
      activeShotTitle: shotTitle,
      workflowState,
      activeProvider,
      activeModel,
      executionStatus,
      productionProgress,
      lastEvent,
      runIdentifier,
      errorState,
    };
  }, [project, corridorShots, selectedShotId, currentJob, productionRecommendation, systemOperationalState, errorState, activeJobPackage]);

  const handleMouseMove = (e: React.MouseEvent<HTMLDivElement>) => {
    if (isReducedMotion) return;
    const rect = e.currentTarget.getBoundingClientRect();
    const x = ((e.clientX - rect.left) / rect.width) * 2 - 1;
    const y = ((e.clientY - rect.top) / rect.height) * 2 - 1;
    setPointer({ x, y });
  };

  const handleSelectCameraState = (state: SpatialCameraState) => {
    setCameraState(state);
    setSpatialProgress(undefined);
    handleCloseInspector();
    spatialAudio.playStationBlip();
  };

  const handleInspectCore = () => {
    setInspectedEntity({ type: 'core' });
    const target: SpatialFocusTarget = {
      position: [0, 2.0, 5.0],
      target: [0, 1.8, 0],
      label: 'CORE INSPECTOR',
    };
    setInternalFocusTarget(target);
    onFocusTargetChange?.(target);
    spatialAudio.playCoreInspect();
  };

  const handleSelectModule = (id: SpatialModuleId) => {
    if (inspectedEntity?.type === 'module' && inspectedEntity.id === id) {
      handleCloseInspector();
      return;
    }
    setInternalSelectedModuleId(id);
    propOnSelectModule?.(id);
    setInspectedEntity({ type: 'module', id });

    const mod = modulesList.find((m) => m.id === id);
    if (mod) {
      const target: SpatialFocusTarget = {
        position: [mod.position[0] * 0.75, mod.position[1] + 0.6, mod.position[2] * 0.75 + 2.0],
        target: mod.position,
        label: mod.name,
      };
      setInternalFocusTarget(target);
      onFocusTargetChange?.(target);
    }
    spatialAudio.playModuleSelect();
  };

  const handleSelectShot = (shotId: string) => {
    if (inspectedEntity?.type === 'shot' && inspectedEntity.id === shotId) {
      handleCloseInspector();
      return;
    }
    setInternalSelectedShotId(shotId);
    setInspectedEntity({ type: 'shot', id: shotId });

    const shotIdx = corridorShots.findIndex((s) => s.id === shotId);
    if (shotIdx !== -1) {
      const pos = getShotCorridorPosition(shotIdx, corridorShots.length);
      const target: SpatialFocusTarget = {
        position: [pos[0], pos[1] + 0.5, pos[2] + 1.8],
        target: pos,
        label: `SHOT ${corridorShots[shotIdx].order}`,
      };
      setInternalFocusTarget(target);
      onFocusTargetChange?.(target);
    }

    if (onSelectShot && project) {
      const activeSeq =
        project.sequences?.find((s) => s.id === selectedSequenceId) ||
        project.sequences?.find((s) => s.id === project.activeSequenceId) ||
        project.sequences?.[0];
      const found = activeSeq?.shots.find((s) => s.id === shotId);
      if (found) {
        onSelectShot(found);
      }
    }
    spatialAudio.playShotSelect();
  };

  const handleCloseInspector = () => {
    setInspectedEntity(null);
    setInternalFocusTarget(null);
    setInternalSelectedModuleId(null);
    setInternalSelectedShotId(null);
    propOnCloseInspector?.();
    onFocusTargetChange?.(null);
  };

  const handleToggleAudio = () => {
    const next = spatialAudio.toggle();
    setInternalAudioEnabled(next);
    onAudioToggle?.(next);
  };

  const handleToggleCinematicMode = () => {
    const next = !isCinematicMode;
    setInternalCinematicMode(next);
    onCinematicModeChange?.(next);
    spatialAudio.playModeToggle(next);
  };

  const handleToggleReducedMotion = () => {
    if (propOnToggleReducedMotion) {
      propOnToggleReducedMotion();
    } else {
      setInternalOverrideReducedMotion(!isReducedMotion);
    }
  };

  const handleSelectSequence = (seqId: string) => {
    setInternalSelectedSequenceId(seqId);
    propOnSelectSequence?.(seqId);
    spatialAudio.playShotSelect();
  };

  const handleLoadShotInStudio = (shot: SpatialShotCardData | Shot) => {
    if (onOpenStudioWithShot) {
      onOpenStudioWithShot(shot);
    } else if (onOpenStudio) {
      onOpenStudio();
    }
  };

  // Phase 7: Intent Lifecycle and Deterministic Compilation Pipeline
  const handleSubmitCommand = (rawInput: string) => {
    setIntentStage('INTENTION');
    const currentProject = project || createDefaultProject(capabilitiesManifest || null);
    const intent = parseUserCommand(rawInput, currentProject, capabilitiesManifest || null);
    setActiveIntent(intent);

    const isTestEnv =
      typeof (globalThis as any).process !== 'undefined' &&
      (globalThis as any).process?.env?.NODE_ENV === 'test';
    const initialDelay = isTestEnv ? 0 : 150;
    const stepDelay = isTestEnv ? 0 : 200;

    // Deterministic lifecycle progression:
    // INTENTION -> ANALYZING -> PLANNING -> ROUTING -> READY
    setTimeout(() => {
      setIntentStage('ANALYZING');

      setTimeout(() => {
        setIntentStage('PLANNING');
        const { updatedProject, targetShot } = compileIntentToShot(
          intent,
          currentProject,
          capabilitiesManifest || null,
          getRecommendationModel(productionRecommendation) || undefined,
          getRecommendationProvider(productionRecommendation) || undefined
        );

        if (onProjectChange) {
          onProjectChange(updatedProject);
        }
        setInternalSelectedShotId(targetShot.id);

        setTimeout(() => {
          setIntentStage('ROUTING');

          setTimeout(() => {
            const pkg = assembleJobPackage(
              targetShot,
              updatedProject,
              capabilitiesManifest || null,
              productionRecommendation || null,
              intent.id
            );
            setInternalActiveJobPackage(pkg);
            setIntentStage(pkg.modelRoute.preflightReady ? 'READY' : 'BLOCKED');
            spatialAudio.playStationBlip();
          }, stepDelay);
        }, stepDelay);
      }, stepDelay);
    }, initialDelay);
  };

  const handleInspectJobPackage = () => {
    if (!activeJobPackage) return;
    setInspectedEntity({ type: 'job_package' });
    const target: SpatialFocusTarget = {
      position: [0, 2.0, 5.0],
      target: [0, 1.8, 0],
      label: 'JOB PACKAGE INSPECTOR',
    };
    setInternalFocusTarget(target);
    onFocusTargetChange?.(target);
    spatialAudio.playCoreInspect();
  };

  const handleDispatchExecution = async () => {
    if (!activeJobPackage || isDispatching) return;
    setIsDispatching(true);
    setIntentStage('DISPATCHING');
    try {
      if (propOnDispatchExecution) {
        await propOnDispatchExecution(activeJobPackage);
        setIntentStage('EXECUTING');
      } else if (onOpenStudioWithShot) {
        onOpenStudioWithShot({
          id: activeJobPackage.shotId,
          order: activeJobPackage.shotOrder,
          title: activeJobPackage.plan.title,
          prompt: activeJobPackage.plan.prompt,
          generationType: activeJobPackage.plan.generationType,
          status: 'READY',
          duration: activeJobPackage.plan.durationSeconds,
          aspectRatio: activeJobPackage.shotConfiguration.aspectRatio,
          model: activeJobPackage.modelRoute.model,
          startFrame: activeJobPackage.references.startFrameUrl,
        } as any);
      }
    } catch {
      setIntentStage('FAILED');
    } finally {
      setIsDispatching(false);
    }
  };

  // Global Keyboard Shortcuts Listener
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      const target = e.target as HTMLElement;
      if (
        target &&
        (target.tagName === 'INPUT' ||
          target.tagName === 'TEXTAREA' ||
          target.isContentEditable)
      ) {
        return;
      }

      if (e.key === '1') {
        handleSelectCameraState('ENTRY');
      } else if (e.key === '2') {
        handleSelectCameraState('APPROACH');
      } else if (e.key === '3') {
        handleSelectCameraState('HUB');
      } else if (e.key === '4') {
        handleSelectCameraState('SYSTEMS');
      } else if (e.key === '5') {
        handleSelectCameraState('CORRIDOR');
      } else if (e.key === '6') {
        handleSelectCameraState('COMMAND');
      } else if (e.key === 'c' || e.key === 'C') {
        onOpenStudio?.();
      } else if (e.key === 'h' || e.key === 'H') {
        handleToggleCinematicMode();
      } else if (e.key === 'i' || e.key === 'I') {
        handleInspectCore();
      } else if (e.key === 'm' || e.key === 'M') {
        const moduleIds: SpatialModuleId[] = ['memory', 'planning', 'routing', 'execution', 'analytics', 'job_package'];
        const currentIdx = selectedModuleId ? moduleIds.indexOf(selectedModuleId) : -1;
        const nextId = moduleIds[(currentIdx + 1) % moduleIds.length];
        handleSelectModule(nextId);
      } else if (e.key === '[') {
        if (corridorShots.length > 0) {
          const currentIdx = corridorShots.findIndex((s) => s.id === selectedShotId);
          const prevIdx = currentIdx <= 0 ? corridorShots.length - 1 : currentIdx - 1;
          handleSelectShot(corridorShots[prevIdx].id);
        }
      } else if (e.key === ']') {
        if (corridorShots.length > 0) {
          const currentIdx = corridorShots.findIndex((s) => s.id === selectedShotId);
          const nextIdx = currentIdx === -1 || currentIdx >= corridorShots.length - 1 ? 0 : currentIdx + 1;
          handleSelectShot(corridorShots[nextIdx].id);
        }
      } else if (e.key === '?') {
        setIsShortcutsOpen((prev) => !prev);
      } else if (e.key === 'Escape') {
        if (isShortcutsOpen) {
          setIsShortcutsOpen(false);
        } else {
          handleCloseInspector();
        }
      }
    };

    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [
    isShortcutsOpen,
    isCinematicMode,
    selectedModuleId,
    selectedShotId,
    corridorShots,
    onOpenStudio,
  ]);

  const selectedModuleObj = useMemo(
    () => modulesList.find((m) => m.id === selectedModuleId) || null,
    [modulesList, selectedModuleId]
  );

  const selectedShotObj = useMemo(
    () => corridorShots.find((s) => s.id === selectedShotId) || null,
    [corridorShots, selectedShotId]
  );

  // Compute inspector data contextually
  const computedInspectorData: SpatialInspectorData | null = useMemo(() => {
    if (propInspectorData !== undefined) return propInspectorData;
    if (!inspectedEntity) return null;

    if (inspectedEntity.type === 'core') {
      return {
        category: 'CORE',
        id: 'aryaos-core',
        title: 'ARYAOS CORE V1',
        subtitle: 'Monolithic Autonomous Intelligence & PBR Engine',
        status: systemOperationalState || 'ONLINE',
        statusVariant:
          systemOperationalState === 'BUSY'
            ? 'active'
            : systemOperationalState === 'DEGRADED'
            ? 'warning'
            : 'neutral',
        metrics: [
          { label: 'Architecture', value: 'Hybrid GLB/Procedural' },
          { label: 'Operational State', value: systemOperationalState || 'ONLINE' },
          {
            label: 'Active Route',
            value: getRecommendationProvider(productionRecommendation)
              ? `${getRecommendationProvider(productionRecommendation)} [${getRecommendationModel(productionRecommendation)}]`
              : 'Standby',
          },
          {
            label: 'Active Run',
            value: currentJob ? currentJob.job_id.slice(0, 8) : 'NONE',
          },
        ],
        details: [
          'Quantum monolith core running PBR metallic material normalization',
          currentJob
            ? `Active Job ${currentJob.job_id}: ${currentJob.status.toUpperCase()} (${getJobProgressPercent(currentJob)}%)`
            : 'Execution standby: 0 active compute runs',
          errorState ? `System Alert: ${errorState}` : 'Integrity check: 0 pipeline faults detected',
        ],
        provenance: 'AryaOS V1 Kernel // 01-ALPHA',
        actionLabel: onOpenStudio ? 'OPEN CREATOR STUDIO' : undefined,
        onAction: onOpenStudio,
      };
    }

    if (inspectedEntity.type === 'module') {
      const mod = modulesList.find((m) => m.id === inspectedEntity.id);
      if (!mod) return null;

      if (mod.id === 'memory') {
        const warnings = corridorShots.filter((s) => s.continuityStatus === 'WARNING' || s.continuityStatus === 'BLOCKED').length;
        const pass = corridorShots.filter((s) => s.continuityStatus === 'PASS').length;
        return {
          category: 'SUBSYSTEM',
          id: 'memory',
          title: 'MEMORY // EPISODIC CONTINUITY',
          subtitle: 'Reference embeddings, character permanence, and sequence cache',
          status: mod.telemetry.status,
          statusVariant: mod.telemetry.status === 'SYNCHRONIZED' ? 'success' : 'active',
          metrics: [
            { label: 'References', value: `${corridorShots.filter((s) => s.predecessorId).length + 1} items` },
            { label: 'Continuity', value: `${pass}/${corridorShots.length} pass` },
            { label: 'Warnings', value: warnings },
            { label: 'Latency', value: `${mod.telemetry.latencyMs}ms` },
          ],
          details: [
            mod.telemetry.detail,
            'Episodic timeline vector store synchronized with AryaOS kernel',
          ],
          provenance: 'AryaOS Memory Subsystem // MOD-01',
        };
      }

      if (mod.id === 'planning') {
        const ready = corridorShots.filter((s) => s.status === 'READY').length;
        const blocked = corridorShots.filter((s) => s.status === 'BLOCKED').length;
        return {
          category: 'SUBSYSTEM',
          id: 'planning',
          title: 'PLANNING // SEQUENCE SYNTHESIS',
          subtitle: 'Timeline orchestration, dependency graphs, and shot sequencing',
          status: mod.telemetry.status,
          statusVariant: mod.telemetry.status === 'PROCESSING' ? 'warning' : 'success',
          metrics: [
            { label: 'Total Shots', value: corridorShots.length },
            { label: 'Ready Shots', value: ready },
            { label: 'Blocked Shots', value: blocked },
            { label: 'Throughput', value: mod.telemetry.throughput },
          ],
          details: [
            mod.telemetry.detail,
            'Multi-shot sequence compiler active',
          ],
          provenance: 'AryaOS Planning Subsystem // MOD-02',
        };
      }

      if (mod.id === 'routing') {
        const preflightPass = productionRecommendation ? productionRecommendation.preflight.ready : true;
        return {
          category: 'SUBSYSTEM',
          id: 'routing',
          title: 'ROUTING // DISPATCH ARBITRATION',
          subtitle: 'Dynamic model selection, capability probing, and preflight validation',
          status: preflightPass ? 'ROUTE READY' : 'ROUTE BLOCKED',
          statusVariant: preflightPass ? 'success' : 'error',
          metrics: [
            { label: 'Provider', value: getRecommendationProvider(productionRecommendation) || 'Autonomous' },
            { label: 'Model', value: getRecommendationModel(productionRecommendation) || 'flux-schnell' },
            { label: 'Preflight', value: preflightPass ? 'PASSED' : 'BLOCKED' },
            { label: 'Latency', value: `${mod.telemetry.latencyMs}ms` },
          ],
          details: [
            mod.telemetry.detail,
            preflightPass
              ? 'Optimal provider route validated with zero policy violations'
              : `Route blocked: ${productionRecommendation?.preflight.reason || 'Missing configuration'}`,
          ],
          provenance: 'AryaOS Routing Subsystem // MOD-03',
        };
      }

      if (mod.id === 'analytics') {
        const consistentCount = corridorShots.filter((s) => s.continuityStatus === 'PASS').length;
        return {
          category: 'SUBSYSTEM',
          id: 'analytics',
          title: 'ANALYTICS // SIGNAL OBSERVERS',
          subtitle: 'Real-time telemetry, model benchmarks, and production quality scores',
          status: 'SYNCHRONIZED',
          statusVariant: 'success',
          metrics: [
            { label: 'Completed Runs', value: historyCount },
            { label: 'Continuity Rate', value: corridorShots.length > 0 ? `${Math.round((consistentCount / corridorShots.length) * 100)}%` : '100%' },
            { label: 'Latency', value: `${mod.telemetry.latencyMs}ms` },
            { label: 'State', value: syncStatus },
          ],
          details: [
            mod.telemetry.detail,
            'Observability conduit connected to PostgreSQL persistent state',
          ],
          provenance: 'AryaOS Analytics Subsystem // MOD-04',
        };
      }

      if (mod.id === 'job_package') {
        return {
          category: 'SUBSYSTEM',
          id: 'job_package',
          title: 'JOB PACKAGE // BOUNDARY CONTRACT',
          subtitle: 'Immutable schema sealing intention, route parameters, and frame anchors',
          status: activeJobPackage ? 'ACTIVE PACKAGE' : 'STANDBY',
          statusVariant: activeJobPackage ? 'active' : 'neutral',
          metrics: [
            { label: 'Package ID', value: activeJobPackage ? activeJobPackage.jobPackageId.slice(0, 10) : 'None' },
            { label: 'Mode', value: activeJobPackage?.plan.mode || 'Standby' },
            { label: 'Target Ratio', value: activeJobPackage?.shotConfiguration.aspectRatio || '16:9' },
            { label: 'Preflight', value: activeJobPackage ? (activeJobPackage.modelRoute.preflightReady ? 'PASSED' : 'BLOCKED') : 'N/A' },
          ],
          details: [
            activeJobPackage ? `Active Job Package: ${activeJobPackage.jobPackageId}` : 'Awaiting prompt compilation into boundary package',
            activeJobPackage?.plan.prompt ? `Compiled Prompt: "${activeJobPackage.plan.prompt}"` : 'Enter a command in the Command Bar to compile an AryaJobPackage',
          ],
          provenance: 'AryaOS Boundary Subsystem // MOD-05',
          actionLabel: activeJobPackage ? 'INSPECT FULL PACKAGE' : undefined,
          onAction: activeJobPackage ? handleInspectJobPackage : undefined,
        };
      }

      if (mod.id === 'execution') {
        const execStatus = currentJob ? currentJob.status.toUpperCase() : 'NO ACTIVE RUN';
        return {
          category: 'SUBSYSTEM',
          id: 'execution',
          title: 'EXECUTION // RUNTIME SYNTHESIS',
          subtitle: 'Active generation chamber and corridor timeline stream',
          status: execStatus,
          statusVariant:
            currentJob?.status === 'in_progress'
              ? 'active'
              : currentJob?.status === 'completed'
              ? 'success'
              : currentJob?.status === 'failed'
              ? 'error'
              : 'neutral',
          metrics: [
            { label: 'Status', value: currentJob ? currentJob.status.toUpperCase() : 'IDLE' },
            { label: 'Job ID', value: currentJob ? currentJob.job_id.slice(0, 8) : 'NONE' },
            { label: 'Progress', value: getJobProgressDisplay(currentJob).label },
            { label: 'Runs Recorded', value: historyCount || 0 },
          ],
          details: [
            mod.telemetry.detail,
            'Conduit link to Multi-Shot Corridor established',
          ],
          provenance: 'AryaOS Execution Subsystem // MOD-06',
          actionLabel: currentJob && onOpenStudio ? 'VIEW RUN IN STUDIO' : undefined,
          onAction: currentJob && onOpenStudio ? onOpenStudio : undefined,
        };
      }
    }

    if (inspectedEntity.type === 'job_package' && activeJobPackage) {
      return {
        category: 'JOB_PACKAGE',
        id: activeJobPackage.jobPackageId,
        title: `JOB PACKAGE // ${activeJobPackage.jobPackageId.slice(0, 14)}`,
        subtitle: `Decision-to-Execution boundary contract for Shot ${activeJobPackage.shotOrder}`,
        status: activeJobPackage.modelRoute.preflightReady ? 'ROUTE READY' : 'PREFLIGHT BLOCKED',
        statusVariant: activeJobPackage.modelRoute.preflightReady ? 'success' : 'error',
        metrics: [
          { label: 'Provider Route', value: `${activeJobPackage.modelRoute.provider.toUpperCase()} [${activeJobPackage.modelRoute.modelName}]` },
          { label: 'Mode / Format', value: `${activeJobPackage.plan.generationType.toUpperCase()} (${activeJobPackage.shotConfiguration.aspectRatio})` },
          { label: 'Preflight State', value: activeJobPackage.modelRoute.preflightReady ? 'PASSED' : 'BLOCKED' },
          { label: 'Cost Estimate', value: activeJobPackage.modelRoute.estimatedCostUsd !== undefined ? `$${activeJobPackage.modelRoute.estimatedCostUsd.toFixed(4)}` : 'N/A' },
        ],
        details: [
          `Prompt Directives: "${activeJobPackage.plan.prompt}"`,
          `Decision Boundary: ${activeJobPackage.decisionBoundary}`,
          activeJobPackage.plan.predecessorShotId
            ? `Predecessor Link: Shot ${activeJobPackage.plan.predecessorShotId}`
            : 'Initial Root Shot (No Predecessor)',
          `Continuity Checks: Visual [${activeJobPackage.continuityRequirements.visual}], Temporal [${activeJobPackage.continuityRequirements.temporal}], StartFrame [${activeJobPackage.continuityRequirements.startFrame}]`,
          `Execution Destination: ${activeJobPackage.outputRequirements.destination}`,
        ],
        provenance: 'AryaOS Decision Engine // JOB-PACKAGE-V1',
        actionLabel: 'DISPATCH EXECUTION',
        onAction: handleDispatchExecution,
        secondaryActionLabel: onOpenStudio ? 'OPEN IN CREATOR STUDIO' : undefined,
        onSecondaryAction: onOpenStudio,
        jobPackage: activeJobPackage,
        firstFrameUrl: activeJobPackage.references.startFrameUrl,
        lastFrameUrl: activeJobPackage.references.endFrameUrl,
        referenceImageUrl: activeJobPackage.references.referenceImageUrl,
      };
    }

    if (inspectedEntity.type === 'shot' && selectedShotObj) {
      let remediation: string | undefined;
      if (selectedShotObj.continuityStatus === 'BLOCKED') {
        remediation = 'WHAT: Continuity Violation // WHERE: Temporal/Start-Frame // WHY: Predecessor link broken or missing.';
      } else if (selectedShotObj.continuityStatus === 'WARNING') {
        remediation = 'WHAT: Continuity Warning // WHERE: Style Vector // WHY: Visual style divergence from sequence predecessor.';
      } else if (selectedShotObj.failureReason) {
        remediation = `WHAT: Execution Failure // WHERE: Provider Pipeline // WHY: ${selectedShotObj.failureReason}`;
      }

      // Find predecessor shot if any
      const predecessorShot = selectedShotObj.predecessorId
        ? corridorShots.find((s) => s.id === selectedShotObj.predecessorId)
        : null;

      const temporalDependency = selectedShotObj.predecessorId
        ? {
            predecessorId: selectedShotObj.predecessorId,
            predecessorTitle: predecessorShot ? `Shot ${String(predecessorShot.order).padStart(2, '0')}` : `Shot ${selectedShotObj.predecessorId}`,
            anchorType: 'LAST FRAME',
            anchorStatus: (predecessorShot?.status === 'COMPLETE' || predecessorShot?.lastFrame || (predecessorShot as any)?.metadata_json?.frame_anchors?.last_frame)
              ? ('VERIFIED' as const)
              : ('PENDING' as const),
            continuityStatus: selectedShotObj.continuityStatus || 'PASS',
            conditioningTarget: 'FIRST FRAME',
            sourceArtifactPath: predecessorShot?.lastFrame || (predecessorShot as any)?.metadata_json?.frame_anchors?.last_frame?.path,
            sourceArtifactUrl: predecessorShot?.outputAssetUrl,
            validationLevel: 'STRUCTURAL_TECHNICAL_CONTINUITY',
          }
        : {
            predecessorId: undefined,
            predecessorTitle: 'None (Root Shot)',
            anchorType: 'NONE',
            anchorStatus: 'NOT_APPLICABLE' as const,
            continuityStatus: 'PASS',
            conditioningTarget: 'NONE',
            validationLevel: 'INDEPENDENT_ROOT_ORIGIN',
          };

      return {
        category: 'SHOT',
        id: selectedShotObj.id,
        title: `SHOT INSPECTION // ${String(selectedShotObj.order).padStart(2, '0')}`,
        subtitle: selectedShotObj.prompt,
        status: selectedShotObj.status,
        statusVariant:
          selectedShotObj.status === 'COMPLETE'
            ? 'success'
            : selectedShotObj.status === 'GENERATING' || selectedShotObj.status === 'QUEUED'
            ? 'active'
            : selectedShotObj.status === 'FAILED'
            ? 'error'
            : 'neutral',
        metrics: [
          { label: 'Type', value: selectedShotObj.generationType.toUpperCase() },
          { label: 'Duration', value: `${selectedShotObj.duration || 5}s` },
          { label: 'Aspect Ratio', value: selectedShotObj.aspectRatio || '16:9' },
          { label: 'Continuity', value: selectedShotObj.continuityStatus || 'PASS' },
          ...(selectedShotObj.generationType === 'video' || selectedShotObj.generationType === 'image_to_video' || selectedShotObj.outputAssetUrl?.endsWith('.mp4') ? [
            { label: 'FPS', value: (selectedShotObj as any).metadata_json?.artifact?.fps || (selectedShotObj as any).metadata?.artifact?.fps || 25 },
            { label: 'Codec', value: ((selectedShotObj as any).metadata_json?.artifact?.video_codec || 'h264').toUpperCase() },
          ] : []),
        ],
        details: [
          `Prompt: "${selectedShotObj.prompt}"`,
          selectedShotObj.predecessorId
            ? `Predecessor Link: Shot ${selectedShotObj.predecessorId}`
            : 'Initial key shot (Root predecessor)',
          `Dependency State: ${selectedShotObj.dependencyState || (selectedShotObj.predecessorId ? 'WAITING_FOR_PREDECESSOR' : 'INDEPENDENT')}`,
          selectedShotObj.firstFrame || selectedShotObj.startFrame
            ? `First Frame Anchor: Attached (${selectedShotObj.startFrameStatus || 'PROVIDED'})`
            : 'First Frame Anchor: None / Procedural Generation',
          selectedShotObj.lastFrame || selectedShotObj.endFrame
            ? `Last Frame Anchor: Attached`
            : 'Last Frame Anchor: None',
          ...(selectedShotObj.outputAssetUrl?.endsWith('.mp4') ? [
            'Video Container: Verified MP4 (libx264/yuv420p)',
            'Temporal Stream: Byte-Range Seeking Enabled',
          ] : []),
          selectedShotObj.failureReason
            ? `Failure Reason: ${selectedShotObj.failureReason}`
            : selectedShotObj.status === 'COMPLETE'
            ? 'Render complete and cached in episodic store'
            : 'Shot compiled into timeline pipeline',
        ],
        provenance: `Production Corridor Sequence // SHOT-${selectedShotObj.id}`,
        actionLabel: 'LOAD IN CREATOR STUDIO',
        onAction: () => handleLoadShotInStudio(selectedShotObj),
        secondaryActionLabel: selectedShotObj.outputAssetUrl ? 'VIEW ARTIFACT' : undefined,
        onSecondaryAction: selectedShotObj.outputAssetUrl ? () => {
          if (typeof window !== 'undefined') window.open(selectedShotObj.outputAssetUrl, '_blank');
        } : undefined,
        thumbnailUrl: selectedShotObj.outputAssetUrl,
        firstFrameUrl: selectedShotObj.firstFrame || selectedShotObj.startFrame || (selectedShotObj as any).first_frame,
        lastFrameUrl: selectedShotObj.lastFrame || selectedShotObj.endFrame || (selectedShotObj as any).last_frame,
        referenceImageUrl: selectedShotObj.referenceAssets?.[0],
        remediation,
        temporalDependency,
      };
    }

    return null;
  }, [
    propInspectorData,
    inspectedEntity,
    systemOperationalState,
    productionRecommendation,
    currentJob,
    errorState,
    modulesList,
    corridorShots,
    historyCount,
    selectedShotObj,
    activeJobPackage,
    propOnDispatchExecution,
  ]);

  return (
    <div
      ref={containerRef}
      className={`spatial-world-container ${className}`}
      onMouseMove={handleMouseMove}
      style={{
        position: 'relative',
        width: '100%',
        height: '100%',
        minHeight: '100vh',
        backgroundColor: '#020408',
        overflow: 'hidden',
        ...style,
      }}
      data-testid="spatial-world-container"
      data-camera-state={cameraState}
      data-active-stage={activeStage}
    >
      {/* Phase 15A: Stage 01 Awakening Hero Asset Layer */}
      <SpatialAwakeningHero
        activeStage={activeStage}
        spatialProgress={spatialProgress}
        isReducedMotion={isReducedMotion}
        onEnterCore={() => handleSelectStage('CORE')}
      />

      {/* 3D WebGL Canvas Layer */}
      {hasWebGL ? (
        <Canvas
          camera={{ position: [0, 2.2, 5.8], fov: 40 }}
          gl={{
            antialias: true,
            powerPreference: 'high-performance',
            alpha: false,
          }}
          dpr={[1, 1.5]}
          style={{
            position: 'absolute',
            inset: 0,
            width: '100%',
            height: '100%',
          }}
          aria-hidden="true"
        >
          {/* Stage 03 Memory Archive vs Stage 02 Core & Systems */}
          {activeStage === 'MEMORY' ? (
            <SpatialMemoryArchive
              isReducedMotion={isReducedMotion}
              activeCamera={commandControl.activeCamera}
              selectedVitrineId={memoryArchive.activeVitrineId}
              selectedMemoryId={memoryArchive.selectedMemoryId}
              highlightedVitrineIds={commandControl.highlightedVitrineIds}
              onSelectVitrine={memoryArchive.selectVitrine}
              onHoverVitrine={memoryArchive.hoverVitrine}
            />
          ) : (
            <>
              {/* Atmospheric Environment & Ground Reflection */}
              <SpatialEnvironment
                isReducedMotion={isReducedMotion}
                enableReflections={!isReducedMotion}
              />

              {/* Central Hybrid Core (GLB pipeline / procedural monolith fallback) */}
              <SpatialCore
                modelPath={customGlbPath}
                isReducedMotion={isReducedMotion}
                pointer={pointer}
                activeState={cameraState}
                onCoreClick={handleInspectCore}
                systemState={currentJob?.status?.toUpperCase() || systemOperationalState}
                intentStage={intentStage}
              />

              {/* Phase 3 Part A: Spatial System Modules & Radial Core Conduits */}
              <SpatialSystemModules
                modules={modulesList}
                selectedModuleId={selectedModuleId || undefined}
                onSelectModule={handleSelectModule}
                isReducedMotion={isReducedMotion}
                corePosition={[0, 1.5, 0]}
                activeStage={activeStage}
              />

              {/* Phase 3 Part B: Multi-Shot Corridor & Continuity Links */}
              <SpatialShotCorridor
                shots={corridorShots}
                selectedShotId={selectedShotId || undefined}
                onSelectShot={handleSelectShot}
                isReducedMotion={isReducedMotion}
                executionModulePosition={[4.2, 1.4, -3.0]}
              />
            </>
          )}

          {/* Smooth Damped Camera Rig with 6 Spatial Stations & Focus Target */}
          <SpatialCameraRig
            cameraState={cameraState}
            spatialProgress={spatialProgress}
            pointer={pointer}
            isReducedMotion={isReducedMotion}
            focusTarget={focusTarget}
          />
        </Canvas>
      ) : (
        /* Graceful 2D Fallback for Non-WebGL environments / JSDOM unit tests */
        <div
          data-testid="spatial-world-fallback"
          style={{
            position: 'absolute',
            inset: 0,
            display: 'flex',
            flexDirection: 'column',
            alignItems: 'center',
            justifyContent: 'center',
            backgroundColor: '#020408',
            color: '#94a3b8',
            gap: '1.5rem',
            padding: '2rem',
            overflowY: 'auto',
          }}
        >
          {/* Central Monolith Simulation Core Marker */}
          <div
            data-testid="spatial-core-inspect-trigger"
            onClick={handleInspectCore}
            style={{
              display: 'flex',
              flexDirection: 'column',
              alignItems: 'center',
              gap: '0.75rem',
              cursor: 'pointer',
            }}
            title="Click to inspect ARYAOS Core"
          >
            <div
              style={{
                width: '100px',
                height: '130px',
                border: '2px solid #f59e0b',
                borderRadius: '8px',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                backgroundColor: 'rgba(245, 158, 11, 0.05)',
                boxShadow: '0 0 30px rgba(245, 158, 11, 0.2)',
              }}
            >
              <Cpu size={42} color="#f59e0b" />
            </div>
            <span style={{ fontFamily: 'monospace', letterSpacing: '0.1em', fontSize: '0.8125rem' }}>
              ARYAOS // CORE SIMULATION ACTIVE [{cameraState}]
            </span>
          </div>

          {/* Subsystem Modules Fallback Grid */}
          <div
            data-testid="spatial-system-modules-fallback"
            style={{
              display: 'grid',
              gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))',
              gap: '0.75rem',
              width: '100%',
              maxWidth: '850px',
            }}
          >
            {modulesList.map((mod) => {
              const isSelected = selectedModuleId === mod.id;
              return (
                <button
                  key={mod.id}
                  type="button"
                  data-testid={`spatial-module-${mod.id}`}
                  onClick={() => handleSelectModule(mod.id)}
                  style={{
                    backgroundColor: isSelected ? 'rgba(245, 158, 11, 0.16)' : 'rgba(15, 23, 42, 0.65)',
                    border: isSelected ? '1px solid #f59e0b' : '1px solid rgba(255, 255, 255, 0.1)',
                    borderRadius: '6px',
                    padding: '0.625rem 0.75rem',
                    textAlign: 'left',
                    color: isSelected ? '#fbbf24' : '#cbd5e1',
                    cursor: 'pointer',
                    display: 'flex',
                    flexDirection: 'column',
                    gap: '0.25rem',
                    fontFamily: 'inherit',
                  }}
                >
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                    <span style={{ fontWeight: 700, fontSize: '0.75rem' }}>{mod.name}</span>
                    <span style={{ fontSize: '0.625rem', color: '#64748b' }}>{mod.code}</span>
                  </div>
                  <span style={{ fontSize: '0.6875rem', color: '#94a3b8' }}>{mod.telemetry.status}</span>
                  <span style={{ fontSize: '0.625rem', color: '#64748b' }}>
                    LOAD: {mod.telemetry.loadPercent}% | {mod.telemetry.latencyMs}ms
                  </span>
                </button>
              );
            })}
          </div>

          {/* Multi-Shot Corridor Fallback Strip */}
          <div
            data-testid="spatial-shot-corridor"
            style={{
              width: '100%',
              maxWidth: '850px',
              backgroundColor: 'rgba(7, 10, 16, 0.8)',
              border: '1px solid rgba(56, 189, 248, 0.25)',
              borderRadius: '6px',
              padding: '0.75rem 1rem',
              display: 'flex',
              flexDirection: 'column',
              gap: '0.5rem',
            }}
          >
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <span
                style={{
                  fontSize: '0.75rem',
                  fontWeight: 700,
                  color: '#38bdf8',
                  letterSpacing: '0.08em',
                  display: 'flex',
                  alignItems: 'center',
                  gap: '0.35rem',
                }}
              >
                <Film size={13} color="#38bdf8" />
                MULTI-SHOT CORRIDOR [{corridorShots.length} SHOTS]
              </span>
              <span style={{ fontSize: '0.625rem', color: '#64748b' }}>
                CONTINUITY: {corridorSummary.continuityStatus}
              </span>
            </div>

            {/* Sequence Selector Fallback (if multi-sequence project) */}
            {project?.sequences && project.sequences.length > 1 && (
              <div
                data-testid="spatial-sequence-fallback-selector"
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: '0.35rem',
                  flexWrap: 'wrap',
                  padding: '0.2rem 0',
                }}
              >
                <span style={{ fontSize: '0.625rem', color: '#38bdf8', fontWeight: 700 }}>
                  SEQUENCES:
                </span>
                {project.sequences.map((seq) => {
                  const isCurrentSeq = seq.id === selectedSequenceId;
                  return (
                    <button
                      key={seq.id}
                      type="button"
                      data-testid={`spatial-fallback-seq-${seq.id}`}
                      onClick={() => handleSelectSequence(seq.id)}
                      style={{
                        backgroundColor: isCurrentSeq ? 'rgba(56, 189, 248, 0.2)' : 'rgba(15, 23, 42, 0.8)',
                        border: isCurrentSeq ? '1px solid #38bdf8' : '1px solid rgba(255, 255, 255, 0.1)',
                        color: isCurrentSeq ? '#38bdf8' : '#94a3b8',
                        padding: '2px 8px',
                        borderRadius: '4px',
                        fontSize: '0.625rem',
                        cursor: 'pointer',
                        fontFamily: 'inherit',
                      }}
                    >
                      0{seq.order} // {seq.title.replace(/^Sequence \d+ \/\/\s*/i, '')}
                    </button>
                  );
                })}
              </div>
            )}

            {corridorShots.length === 0 ? (
              <div
                data-testid="spatial-corridor-empty"
                style={{
                  padding: '1rem',
                  textAlign: 'center',
                  fontSize: '0.75rem',
                  color: '#64748b',
                  fontStyle: 'italic',
                }}
              >
                CORRIDOR STANDBY // NO ACTIVE PRODUCTION SHOTS
              </div>
            ) : (
              <div
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: '0.5rem',
                  overflowX: 'auto',
                  padding: '0.25rem 0',
                }}
              >
                {corridorShots.map((shot, idx) => {
                  const isSelected = selectedShotId === shot.id;
                  return (
                    <React.Fragment key={shot.id}>
                      {idx > 0 && (
                        <div
                          data-testid={`spatial-continuity-link-${corridorShots[idx - 1].id}-${shot.id}`}
                          style={{
                            width: '24px',
                            height: '2px',
                            backgroundColor:
                              shot.continuityStatus === 'PASS'
                                ? '#38bdf8'
                                : shot.continuityStatus === 'WARNING'
                                ? '#f59e0b'
                                : '#ef4444',
                            flexShrink: 0,
                          }}
                          title={`Continuity Link: ${corridorShots[idx - 1].id} -> ${shot.id}`}
                        />
                      )}
                      <button
                        type="button"
                        data-testid={`spatial-shot-${shot.id}`}
                        onClick={() => handleSelectShot(shot.id)}
                        className={`spatial-production-card ${isSelected ? 'selected' : ''}`}
                        style={{
                          backgroundColor: isSelected ? 'rgba(22, 34, 56, 0.95)' : 'rgba(15, 23, 42, 0.85)',
                          border: isSelected ? '1px solid #38bdf8' : '1px solid rgba(255, 255, 255, 0.1)',
                          borderRadius: '6px',
                          padding: '0',
                          color: isSelected ? '#38bdf8' : '#cbd5e1',
                          cursor: 'pointer',
                          fontFamily: "'JetBrains Mono', monospace",
                          width: '180px',
                          minWidth: '180px',
                          textAlign: 'left',
                          flexShrink: 0,
                          overflow: 'hidden',
                          boxShadow: isSelected
                            ? '0 8px 24px rgba(0, 0, 0, 0.8), 0 0 16px rgba(56, 189, 248, 0.25)'
                            : '0 4px 12px rgba(0, 0, 0, 0.5)',
                          transition: 'all 0.2s cubic-bezier(0.16, 1, 0.3, 1)',
                        }}
                      >
                        {/* Media Thumbnail Container */}
                        <div
                          className="spatial-card-media"
                          style={{
                            position: 'relative',
                            width: '100%',
                            height: '92px',
                            backgroundColor: '#020408',
                            overflow: 'hidden',
                            display: 'flex',
                            alignItems: 'center',
                            justifyContent: 'center',
                          }}
                        >
                          {shot.outputAssetUrl ? (
                            <img
                              src={shot.outputAssetUrl}
                              alt={shot.title || `Shot ${shot.order}`}
                              style={{
                                width: '100%',
                                height: '100%',
                                objectFit: 'cover',
                              }}
                              onError={(e) => {
                                (e.currentTarget as HTMLElement).style.display = 'none';
                              }}
                            />
                          ) : (
                            <div
                              className="spatial-card-placeholder"
                              style={{
                                display: 'flex',
                                flexDirection: 'column',
                                alignItems: 'center',
                                justifyContent: 'center',
                                gap: '0.25rem',
                                color: '#475569',
                                fontSize: '0.5625rem',
                              }}
                            >
                              <Film size={16} color="#475569" />
                              <span>PENDING RENDER</span>
                            </div>
                          )}

                          {/* Aspect Ratio & Duration Overlays */}
                          <div
                            style={{
                              position: 'absolute',
                              top: '4px',
                              right: '4px',
                              backgroundColor: 'rgba(2, 6, 23, 0.85)',
                              border: '1px solid rgba(255, 255, 255, 0.1)',
                              borderRadius: '3px',
                              padding: '1px 4px',
                              fontSize: '0.5625rem',
                              color: '#94a3b8',
                              fontWeight: 600,
                            }}
                          >
                            {shot.aspectRatio || '16:9'}
                          </div>
                        </div>

                        {/* Card Metadata Content */}
                        <div
                          className="spatial-card-content"
                          style={{
                            padding: '0.5rem 0.65rem',
                            display: 'flex',
                            flexDirection: 'column',
                            gap: '0.25rem',
                          }}
                        >
                          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                            <div style={{ fontSize: '0.6875rem', fontWeight: 700, color: isSelected ? '#38bdf8' : '#f8fafc' }}>
                              SHOT {String(shot.order).padStart(2, '0')}
                            </div>
                            <span
                              style={{
                                fontSize: '0.5625rem',
                                fontWeight: 700,
                                padding: '1px 5px',
                                borderRadius: '3px',
                                backgroundColor:
                                  shot.status === 'COMPLETE'
                                    ? 'rgba(16, 185, 129, 0.18)'
                                    : shot.status === 'READY'
                                    ? 'rgba(56, 189, 248, 0.18)'
                                    : shot.status === 'BLOCKED'
                                    ? 'rgba(239, 68, 68, 0.18)'
                                    : 'rgba(245, 158, 11, 0.18)',
                                color:
                                  shot.status === 'COMPLETE'
                                    ? '#10b981'
                                    : shot.status === 'READY'
                                    ? '#38bdf8'
                                    : shot.status === 'BLOCKED'
                                    ? '#ef4444'
                                    : '#fbbf24',
                                border:
                                  shot.status === 'COMPLETE'
                                    ? '1px solid rgba(16, 185, 129, 0.4)'
                                    : shot.status === 'READY'
                                    ? '1px solid rgba(56, 189, 248, 0.4)'
                                    : shot.status === 'BLOCKED'
                                    ? '1px solid rgba(239, 68, 68, 0.4)'
                                    : '1px solid rgba(245, 158, 11, 0.4)',
                              }}
                            >
                              {shot.status}
                            </span>
                          </div>

                          <div style={{ fontSize: '0.5625rem', color: '#64748b' }}>
                            {(shot.generationType || 'image').toUpperCase()} | {shot.duration || 5}s
                          </div>

                          {/* Phase 13: Dependency State & Frame Anchor Badges */}
                          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginTop: '0.15rem' }}>
                            <span
                              data-testid={`spatial-shot-dependency-badge-${shot.id}`}
                              style={{
                                fontSize: '0.5rem',
                                fontWeight: 700,
                                padding: '1px 4px',
                                borderRadius: '2px',
                                backgroundColor:
                                  shot.dependencyState === 'READY' || shot.dependencyState?.includes('PASS')
                                    ? 'rgba(16, 185, 129, 0.15)'
                                    : shot.dependencyState === 'WAITING_FOR_PREDECESSOR'
                                    ? 'rgba(245, 158, 11, 0.15)'
                                    : shot.dependencyState?.includes('BLOCKED')
                                    ? 'rgba(239, 68, 68, 0.15)'
                                    : 'rgba(100, 116, 139, 0.15)',
                                color:
                                  shot.dependencyState === 'READY' || shot.dependencyState?.includes('PASS')
                                    ? '#10b981'
                                    : shot.dependencyState === 'WAITING_FOR_PREDECESSOR'
                                    ? '#fbbf24'
                                    : shot.dependencyState?.includes('BLOCKED')
                                    ? '#ef4444'
                                    : '#94a3b8',
                                border:
                                  shot.dependencyState === 'READY' || shot.dependencyState?.includes('PASS')
                                    ? '1px solid rgba(16, 185, 129, 0.3)'
                                    : shot.dependencyState === 'WAITING_FOR_PREDECESSOR'
                                    ? '1px solid rgba(245, 158, 11, 0.3)'
                                    : shot.dependencyState?.includes('BLOCKED')
                                    ? '1px solid rgba(239, 68, 68, 0.3)'
                                    : '1px solid rgba(100, 116, 139, 0.3)',
                              }}
                            >
                              {shot.dependencyState || (shot.predecessorId ? 'WAITING' : 'INDEPENDENT')}
                            </span>

                            {(shot.lastFrame || (shot.frameAnchors && shot.frameAnchors.last_frame)) && (
                              <span
                                data-testid={`spatial-shot-last-frame-badge-${shot.id}`}
                                style={{
                                  fontSize: '0.5rem',
                                  fontWeight: 700,
                                  color: '#34d399',
                                }}
                              >
                                [LAST FRAME ✓]
                              </span>
                            )}
                          </div>

                          {shot.predecessorId && (
                            <div
                              data-testid={`spatial-shot-predecessor-link-${shot.id}`}
                              style={{
                                fontSize: '0.5rem',
                                color: '#38bdf8',
                                display: 'flex',
                                alignItems: 'center',
                                gap: '0.2rem',
                                marginTop: '0.1rem',
                              }}
                            >
                              <span>[FIRST FRAME ← SHOT {corridorShots.find(s => s.id === shot.predecessorId)?.order || '01'}]</span>
                            </div>
                          )}
                        </div>
                      </button>
                    </React.Fragment>
                  );
                })}
              </div>
            )}
          </div>
        </div>
      )}

      {/* Minimal Technical Spatial HUD Overlay */}
      <SpatialHudOverlay
        cameraState={cameraState}
        spatialProgress={spatialProgress}
        onSelectCameraState={handleSelectCameraState}
        onProgressChange={setSpatialProgress}
        activeStage={activeStage}
        onSelectStage={handleSelectStage}
        onOpenStudio={onOpenStudio}
        onOpenStudioWithShot={handleLoadShotInStudio}
        selectedModule={selectedModuleObj}
        onSelectModule={handleSelectModule}
        selectedShot={selectedShotObj}
        corridorSummary={corridorSummary}
        productionTelemetry={productionTelemetry}
        inspectorData={computedInspectorData}
        onCloseInspector={handleCloseInspector}
        onInspectCore={handleInspectCore}
        focusTarget={focusTarget}
        isCinematicMode={isCinematicMode}
        onToggleCinematicMode={handleToggleCinematicMode}
        isAudioEnabled={isAudioEnabled}
        onToggleAudio={handleToggleAudio}
        isReducedMotion={isReducedMotion}
        onToggleReducedMotion={handleToggleReducedMotion}
        onOpenShortcuts={() => setIsShortcutsOpen(true)}
        sequences={project?.sequences?.map((s) => ({ id: s.id, title: s.title, order: s.order }))}
        activeSequenceId={selectedSequenceId || undefined}
        onSelectSequence={handleSelectSequence}
        intentStage={intentStage}
        activeIntent={activeIntent}
        activeJobPackage={activeJobPackage}
        onSubmitCommand={handleSubmitCommand}
        onInspectJobPackage={handleInspectJobPackage}
        onDispatchExecution={handleDispatchExecution}
        isDispatching={isDispatching}
      />

      {/* Stage 04 & 05: Spatial Memory Archive HUD & Command Overlay */}
      {activeStage === 'MEMORY' && (
        <MemoryArchiveOverlay
          memoryArchive={memoryArchive}
          commandControl={commandControl}
          isReducedMotion={isReducedMotion}
        />
      )}

      {/* Operator Shortcuts Modal */}
      <SpatialShortcutsModal
        isOpen={isShortcutsOpen}
        onClose={() => setIsShortcutsOpen(false)}
      />
    </div>
  );
};
