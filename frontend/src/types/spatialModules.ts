/**
 * AryaOS V1 — Spatial System Modules & Shot Corridor Type Definitions
 * Phase 3: System Modules (Memory, Planning, Routing, Execution) and Multi-Shot Corridor
 */

export type SpatialModuleId = 'memory' | 'planning' | 'routing' | 'execution' | 'analytics' | 'job_package';

export type SpatialModuleStatus = 'IDLE' | 'ACTIVE' | 'PROCESSING' | 'READY' | 'SYNCHRONIZED';

export interface SpatialModuleTelemetry {
  status: SpatialModuleStatus;
  loadPercent: number;
  throughput: string;
  latencyMs: number;
  activeItemsCount: number;
  detail: string;
}

export interface SpatialModuleData {
  id: SpatialModuleId;
  name: string;
  code: string;
  sector: string;
  title: string;
  description: string;
  position: [number, number, number];
  telemetry: SpatialModuleTelemetry;
}

import { GenerationType } from './creator';

export interface SpatialShotCardData {
  id: string;
  order: number;
  title: string;
  prompt: string;
  status: 'DRAFT' | 'CONFIGURING' | 'BLOCKED' | 'READY' | 'QUEUED' | 'GENERATING' | 'COMPLETE' | 'FAILED' | 'RECOVERY_REQUIRED';
  generationType: GenerationType | 'image' | 'video' | 'image-to-video' | 'image_to_video';
  duration?: number;
  aspectRatio?: string;
  model?: string;
  continuityStatus?: 'PASS' | 'WARNING' | 'BLOCKED' | 'UNAVAILABLE';
  predecessorId?: string;
  outputAssetUrl?: string;
  failureReason?: string;
  startFrame?: string;
  endFrame?: string;
  referenceAssets?: string[];
  dependencyShotIds?: string[];
  startFrameStatus?: 'REQUIRED' | 'PROVIDED' | 'MISSING' | 'UNAVAILABLE' | 'NOT_APPLICABLE' | string;
  characterContinuity?: 'PASS' | 'WARNING' | 'BLOCKED' | 'UNAVAILABLE' | string;
  environmentContinuity?: 'PASS' | 'WARNING' | 'BLOCKED' | 'UNAVAILABLE' | string;
  visualContinuity?: 'PASS' | 'WARNING' | 'BLOCKED' | 'UNAVAILABLE' | string;
  outputJobId?: string;
  dependencyState?: 'INDEPENDENT' | 'WAITING_FOR_PREDECESSOR' | 'READY' | 'EXECUTING' | 'CONTINUITY_PASS' | 'CONTINUITY_WARNING' | 'CONTINUITY_BLOCKED' | string;
  firstFrame?: string;
  lastFrame?: string;
  frameAnchors?: {
    first_frame?: { path: string; url?: string; width: number; height: number; hash: string };
    last_frame?: { path: string; url?: string; width: number; height: number; hash: string };
  };
}

export interface SpatialCorridorSummary {
  totalShots: number;
  activeCount: number;
  completeCount: number;
  continuityStatus: 'PASS' | 'WARNING' | 'BLOCKED' | 'UNAVAILABLE';
}

export const DEFAULT_SPATIAL_MODULES: SpatialModuleData[] = [
  {
    id: 'memory',
    name: 'MEMORY',
    code: 'MOD-01',
    sector: 'ORBIT-ALPHA',
    title: 'EPISODIC ARCHIVE & RETRIEVAL',
    description: 'Episodic memory store, character lineage cache, and shot continuity indexes',
    position: [-4.2, 1.4, -3.0],
    telemetry: {
      status: 'SYNCHRONIZED',
      loadPercent: 34,
      throughput: '1.2 GB/s',
      latencyMs: 4,
      activeItemsCount: 128,
      detail: 'Lineage graphs & continuity cache verified',
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
      status: 'READY',
      loadPercent: 58,
      throughput: '8.4 ops/s',
      latencyMs: 12,
      activeItemsCount: 16,
      detail: 'Dependency tree evaluated: 0 blockers',
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
      status: 'ACTIVE',
      loadPercent: 72,
      throughput: '42 req/min',
      latencyMs: 18,
      activeItemsCount: 4,
      detail: 'Optimal provider routes established',
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
      loadPercent: 44,
      throughput: '99.4% pass',
      latencyMs: 8,
      activeItemsCount: 48,
      detail: 'Continuity & duration integrity tracking online',
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
      status: 'READY',
      loadPercent: 62,
      throughput: '100% schema',
      latencyMs: 2,
      activeItemsCount: 2,
      detail: 'Validated orchestration payload prepared for dispatch',
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
      status: 'PROCESSING',
      loadPercent: 88,
      throughput: '60 fps',
      latencyMs: 25,
      activeItemsCount: 1,
      detail: 'Corridor pipeline conduit synchronized',
    },
  },
];
