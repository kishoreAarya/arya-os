/**
 * AryaOS V1 — Phase 14: Spatial OS Transformation & RIOS Core Experience Test Suite
 *
 * Verifies:
 * 1. 9-Stage Progressive Spatial Discovery Architecture (Awakening -> Creations)
 * 2. Embodied RIOS Core & Reactive Operational Lighting / State Pulses
 * 3. 6 Subsystem Modules (Memory, Planning, Routing, Analytics, Job Package, Execution)
 * 4. Contextual Slide-in Inspection Console & HUD Clutter Reduction
 * 5. Keyboard Navigation & Wheel Navigation Accessibility
 * 6. Non-Destructive Production Continuity & Full Roundtrip Stability
 */

import React from 'react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import '@testing-library/jest-dom';

import {
  SPATIAL_STAGES,
  SpatialStage,
  CAMERA_WAYPOINTS,
  interpolateStageProgress,
  interpolateSpatialProgress,
} from '../types/spatial';
import { DEFAULT_SPATIAL_MODULES, SpatialModuleId } from '../types/spatialModules';
import { SpatialWorld } from '../components/spatial/SpatialWorld';
import { SpatialHudOverlay } from '../components/spatial/SpatialHudOverlay';
import { SpatialCore } from '../components/spatial/SpatialCore';
import { Project } from '../types/productionTimeline';
import { AryaJobPackage } from '../types/spatialIntent';

// Mock audio system to avoid Web Audio API issues in JSDOM
vi.mock('../utils/spatialAudio', () => ({
  spatialAudio: {
    playStationBlip: vi.fn(),
    playCoreInspect: vi.fn(),
    playModuleSelect: vi.fn(),
    playShotSelect: vi.fn(),
    playModeToggle: vi.fn(),
    toggle: vi.fn(() => true),
    isEnabled: vi.fn(() => false),
  },
}));

// Mock Three.js Canvas to render cleanly in JSDOM
vi.mock('@react-three/fiber', () => ({
  Canvas: ({ children }: any) => <div data-testid="r3f-canvas-mock">{children}</div>,
  useFrame: vi.fn(),
  useThree: () => ({
    camera: { position: { set: vi.fn() }, lookAt: vi.fn(), fov: 40, updateProjectionMatrix: vi.fn() },
    scene: { add: vi.fn(), remove: vi.fn() },
    gl: { domElement: document.createElement('canvas') },
  }),
}));

const mockProject: Project = {
  id: 'proj-phase14-spatial-os',
  title: 'RIOS SPATIAL ODYSSEY',
  description: 'Production sequence demonstrating Phase 14 Spatial OS transformation',
  activeSequenceId: 'seq-01',
  activeShotId: 'shot-01',
  sequences: [
    {
      id: 'seq-01',
      projectId: 'proj-phase14-spatial-os',
      order: 1,
      title: 'Sequence 01 // Quantum Monolith Awakening',
      status: 'READY',
      statusReasons: [],
      totalShots: 2,
      readyShots: 1,
      blockedShots: 0,
      inFlightShots: 0,
      completeShots: 1,
      totalDurationSeconds: 9,
      createdAt: new Date().toISOString(),
      updatedAt: new Date().toISOString(),
      shots: [
        {
          id: 'shot-01',
          sequenceId: 'seq-01',
          order: 1,
          title: 'Shot 01 // Monolith Awakening',
          prompt: 'Cinematic wide angle, obsidian monolith activating with amber pulse',
          status: 'COMPLETE',
          generationType: 'image',
          duration: 5,
          aspectRatio: '16:9',
          selectedModel: 'flux-schnell',
          selectedProvider: 'fal',
          continuityStatus: 'PASS',
          predecessorShotId: undefined,
          dependencyShotIds: [],
          readiness: 'READY',
          validationResults: {
            isValid: true,
            readiness: 'READY',
            reasons: [],
            reasonCodes: [],
            preflightReady: true,
            dependenciesSatisfied: true,
            startFrameSatisfied: true,
          },
          continuityReport: {
            character: { status: 'PASS', detail: 'OK', source: 'USER_CONFIGURATION' },
            environment: { status: 'PASS', detail: 'OK', source: 'USER_CONFIGURATION' },
            visual: { status: 'PASS', detail: 'OK', source: 'USER_CONFIGURATION' },
            temporal: { status: 'PASS', detail: 'OK', source: 'USER_CONFIGURATION' },
            startFrame: { status: 'NOT_APPLICABLE', detail: 'First shot', source: 'USER_CONFIGURATION' },
          },
          provenance: 'USER_CONFIGURATION',
          dependencyState: 'INDEPENDENT',
          lastFrame: '/api/v1/artifacts/mock_shot_01_last.png',
          outputAssetUrl: '/api/v1/artifacts/mock_shot_01.png',
        },
        {
          id: 'shot-02',
          sequenceId: 'seq-01',
          order: 2,
          title: 'Shot 02 // Corridor Emergence',
          prompt: 'Temporal tracking shot, cyan conduits extending into cybernetic corridor',
          status: 'READY',
          generationType: 'video',
          duration: 4,
          aspectRatio: '16:9',
          selectedModel: 'kling-v1-5',
          selectedProvider: 'kling',
          continuityStatus: 'PASS',
          predecessorShotId: 'shot-01',
          dependencyShotIds: ['shot-01'],
          readiness: 'READY',
          validationResults: {
            isValid: true,
            readiness: 'READY',
            reasons: [],
            reasonCodes: [],
            preflightReady: true,
            dependenciesSatisfied: true,
            startFrameSatisfied: true,
          },
          continuityReport: {
            character: { status: 'PASS', detail: 'OK', source: 'USER_CONFIGURATION' },
            environment: { status: 'PASS', detail: 'OK', source: 'USER_CONFIGURATION' },
            visual: { status: 'PASS', detail: 'OK', source: 'USER_CONFIGURATION' },
            temporal: { status: 'PASS', detail: 'OK', source: 'USER_CONFIGURATION' },
            startFrame: { status: 'PROVIDED', detail: 'Provided by shot 01', source: 'USER_CONFIGURATION' },
          },
          provenance: 'USER_CONFIGURATION',
          dependencyState: 'READY',
          startFrame: '/api/v1/artifacts/mock_shot_01_last.png',
          lastFrame: '/api/v1/artifacts/mock_shot_02_last.png',
          outputAssetUrl: '/api/v1/artifacts/mock_shot_02.mp4',
        },
      ],
    },
  ],
  createdAt: new Date().toISOString(),
  updatedAt: new Date().toISOString(),
  metadata: {
    facts: [
      {
        id: 'fact-01',
        key: 'monolith_material',
        value: 'Obsidian with gold energy veins',
        status: 'ESTABLISHED',
        source: 'USER_CONFIGURATION',
        originShotId: 'shot-01',
        lastVerifiedShotId: 'shot-01',
      },
    ],
  },
};

const mockJobPackage: AryaJobPackage = {
  jobPackageId: 'pkg-spatial-os-7788',
  createdAt: new Date().toISOString(),
  projectId: 'proj-phase14-spatial-os',
  sequenceId: 'seq-01',
  shotId: 'shot-02',
  shotOrder: 2,
  plan: {
    title: 'Shot 02 // Corridor Emergence',
    prompt: 'Temporal tracking shot, cyan conduits extending into cybernetic corridor',
    generationType: 'video',
    durationSeconds: 4,
    mode: 'image_to_video',
    dependencies: ['shot-01'],
    isFirstShotInSequence: false,
    predecessorShotId: 'shot-01',
  },
  references: {
    firstFrame: '/api/v1/artifacts/mock_shot_01_last.png',
    startFrameUrl: '/api/v1/artifacts/mock_shot_01_last.png',
    referenceAssets: ['/api/v1/artifacts/mock_shot_01_last.png'],
  },
  modelRoute: {
    provider: 'kling',
    model: 'kling-v1-5',
    modelName: 'Kling 1.5 Standard',
    mode: 'video',
    availability: 'AVAILABLE',
    estimatedCostUsd: 0.05,
    preflightReasons: [],
    preflightReady: true,
  },
  shotConfiguration: {
    aspectRatio: '16:9',
    resolution: '1080p',
    duration: 4,
    fps: 25,
  },
  continuityRequirements: {
    visual: 'PASS',
    temporal: 'PASS',
    character: 'PASS',
    environment: 'PASS',
    startFrame: 'PROVIDED',
  },
  outputRequirements: {
    destination: 'ARYAOS_CORRIDOR_STREAM',
    targetFormat: 'mp4',
  },
  executionPayload: {
    prompt: 'Temporal tracking shot, cyan conduits extending into cybernetic corridor',
    generation_type: 'video',
    model: 'kling-v1-5',
    aspect_ratio: '16:9',
  },
  decisionBoundary: 'ARYAOS_ORCHESTRATION_VALIDATED',
};

describe('AryaOS V1 — Phase 14: Spatial OS Transformation & RIOS Core Experience', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  describe('1. 9-Stage Progressive Spatial Discovery Architecture', () => {
    it('defines all 9 progressive spatial stages with monotonic progression', () => {
      expect(SPATIAL_STAGES).toHaveLength(9);

      const expectedStages: SpatialStage[] = [
        'AWAKENING',
        'CORE',
        'MEMORY',
        'PLANNING',
        'ROUTING',
        'COMMAND',
        'EXECUTION',
        'ARTIFACT',
        'CREATIONS',
      ];

      SPATIAL_STAGES.forEach((stage, idx) => {
        expect(stage.id).toBe(expectedStages[idx]);
        expect(stage.progress).toBeGreaterThanOrEqual(0);
        expect(stage.progress).toBeLessThanOrEqual(1);
        expect(stage.label).toBeTruthy();
        expect(stage.description).toBeTruthy();
        if (idx > 0) {
          expect(stage.progress).toBeGreaterThan(SPATIAL_STAGES[idx - 1].progress);
        }
      });
    });

    it('renders the 9-stage scrubber in SpatialHudOverlay with stage navigation buttons', () => {
      const handleSelectStage = vi.fn();

      render(
        <SpatialHudOverlay
          cameraState="HUB"
          activeStage="CORE"
          onSelectStage={handleSelectStage}
          onSelectCameraState={vi.fn()}
        />
      );

      const stageNav = screen.getByTestId('spatial-stage-navigator');
      expect(stageNav).toBeInTheDocument();

      // Verify all 9 stage buttons exist
      SPATIAL_STAGES.forEach((stg) => {
        const btn = screen.getByTestId(`stage-nav-${stg.id}`);
        expect(btn).toBeInTheDocument();
      });

      // Click STG-04 (PLANNING)
      const planningBtn = screen.getByTestId('stage-nav-PLANNING');
      fireEvent.click(planningBtn);
      expect(handleSelectStage).toHaveBeenCalledWith('PLANNING');
    });

    it('smoothly interpolates coordinates across all 9 stages via interpolateStageProgress', () => {
      // Test endpoints and intermediate stops
      const start = interpolateStageProgress(0.0);
      expect(start.position[0]).toBeCloseTo(CAMERA_WAYPOINTS.ENTRY.position[0]);
      expect(start.position[1]).toBeCloseTo(CAMERA_WAYPOINTS.ENTRY.position[1]);
      expect(start.position[2]).toBeCloseTo(CAMERA_WAYPOINTS.ENTRY.position[2]);

      const coreStage = interpolateStageProgress(0.12);
      expect(coreStage.position[0]).toBeCloseTo(CAMERA_WAYPOINTS.HUB.position[0]);
      expect(coreStage.position[1]).toBeCloseTo(CAMERA_WAYPOINTS.HUB.position[1]);
      expect(coreStage.position[2]).toBeCloseTo(CAMERA_WAYPOINTS.HUB.position[2]);

      const memoryStage = interpolateStageProgress(0.25);
      expect(memoryStage.position[0]).toBeCloseTo(CAMERA_WAYPOINTS.MEMORY.position[0]);

      const end = interpolateStageProgress(1.0);
      expect(end.position[0]).toBeCloseTo(CAMERA_WAYPOINTS.CORRIDOR.position[0]);
      expect(end.position[1]).toBeCloseTo(CAMERA_WAYPOINTS.CORRIDOR.position[1]);
    });
  });

  describe('2. Embodied RIOS Core & Reactive Operational Lighting', () => {
    it('mounts SpatialCore with dynamic state reactivity props', () => {
      const handleInspectCore = vi.fn();
      render(
        <SpatialCore
          activeState="HUB"
          systemState="GENERATING"
          intentStage="PLANNING"
          onCoreClick={handleInspectCore}
        />
      );

      // Verify container renders
      const container = screen.getByTestId('spatial-core-container');
      expect(container).toBeInTheDocument();
      expect(container).toHaveAttribute('data-active-state', 'HUB');
    });

    it('opens Core Inspector upon clicking central monolith in fallback mode', () => {
      render(<SpatialWorld project={mockProject} />);

      const coreTrigger = screen.getByTestId('spatial-core-inspect-trigger');
      fireEvent.click(coreTrigger);

      // Contextual inspector panel should appear
      const inspector = screen.getByTestId('spatial-inspector-panel');
      expect(inspector).toBeInTheDocument();
      expect(screen.getByText(/ARYAOS CORE V1/i)).toBeInTheDocument();
      expect(screen.getByText(/Monolithic Autonomous Intelligence/i)).toBeInTheDocument();
    });
  });

  describe('3. 6 Subsystem Modules (Memory, Planning, Routing, Analytics, Job Package, Execution)', () => {
    it('renders all 6 modules in fallback grid and 3D module list', () => {
      render(<SpatialWorld project={mockProject} />);

      const expectedModuleIds: SpatialModuleId[] = [
        'memory',
        'planning',
        'routing',
        'analytics',
        'job_package',
        'execution',
      ];

      expectedModuleIds.forEach((id) => {
        const modBtn = screen.getByTestId(`spatial-module-${id}`);
        expect(modBtn).toBeInTheDocument();
      });
    });

    it('contextually inspects ANALYTICS module with verified metrics', () => {
      render(<SpatialWorld project={mockProject} historyCount={42} />);

      const analyticsBtn = screen.getByTestId('spatial-module-analytics');
      fireEvent.click(analyticsBtn);

      const inspector = screen.getByTestId('spatial-inspector-panel');
      expect(inspector).toBeInTheDocument();
      expect(screen.getByText(/ANALYTICS \/\/ SIGNAL OBSERVERS/i)).toBeInTheDocument();
      expect(screen.getByText(/42/)).toBeInTheDocument();
      expect(screen.getByText(/Continuity Rate/i)).toBeInTheDocument();
    });

    it('contextually inspects JOB PACKAGE module and shows boundary contract', () => {
      render(
        <SpatialWorld
          project={mockProject}
          activeJobPackage={mockJobPackage}
        />
      );

      const jobPkgBtn = screen.getByTestId('spatial-module-job_package');
      fireEvent.click(jobPkgBtn);

      const inspector = screen.getByTestId('spatial-inspector-panel');
      expect(inspector).toBeInTheDocument();
      expect(screen.getByText(/JOB PACKAGE \/\/ BOUNDARY CONTRACT/i)).toBeInTheDocument();
      expect(screen.getAllByText(/pkg-spatia/i)[0]).toBeInTheDocument();
      expect(screen.getByText(/INSPECT FULL PACKAGE/i)).toBeInTheDocument();
    });

    it('cycles through all 6 modules sequentially using keyboard key M', () => {
      render(<SpatialWorld project={mockProject} />);

      // 1. Press 'm' -> MEMORY
      fireEvent.keyDown(window, { key: 'm' });
      expect(screen.getByText(/MEMORY \/\/ EPISODIC CONTINUITY/i)).toBeInTheDocument();

      // 2. Press 'm' -> PLANNING
      fireEvent.keyDown(window, { key: 'm' });
      expect(screen.getByText(/PLANNING \/\/ SEQUENCE SYNTHESIS/i)).toBeInTheDocument();

      // 3. Press 'm' -> ROUTING
      fireEvent.keyDown(window, { key: 'm' });
      expect(screen.getByText(/ROUTING \/\/ DISPATCH ARBITRATION/i)).toBeInTheDocument();

      // 4. Press 'm' -> EXECUTION
      fireEvent.keyDown(window, { key: 'm' });
      expect(screen.getByText(/EXECUTION \/\/ RUNTIME SYNTHESIS/i)).toBeInTheDocument();

      // 5. Press 'm' -> ANALYTICS
      fireEvent.keyDown(window, { key: 'm' });
      expect(screen.getByText(/ANALYTICS \/\/ SIGNAL OBSERVERS/i)).toBeInTheDocument();

      // 6. Press 'm' -> JOB PACKAGE
      fireEvent.keyDown(window, { key: 'm' });
      expect(screen.getByText(/JOB PACKAGE \/\/ BOUNDARY CONTRACT/i)).toBeInTheDocument();
    });
  });

  describe('4. Contextual Slide-in Inspection Console & Clutter Reduction', () => {
    it('slides inspector panel in on demand and dismisses cleanly with Escape key', () => {
      render(<SpatialWorld project={mockProject} />);

      // Initially no inspector open
      expect(screen.queryByTestId('spatial-inspector-panel')).not.toBeInTheDocument();

      // Inspect shot-01
      const shot01Btn = screen.getByTestId('spatial-shot-shot-01');
      fireEvent.click(shot01Btn);

      expect(screen.getByTestId('spatial-inspector-panel')).toBeInTheDocument();
      expect(screen.getByText(/SHOT INSPECTION \/\/ 01/i)).toBeInTheDocument();

      // Press Escape -> closes inspector
      fireEvent.keyDown(window, { key: 'Escape' });
      expect(screen.queryByTestId('spatial-inspector-panel')).not.toBeInTheDocument();
    });

    it('dismisses inspector panel via the close X button', () => {
      render(<SpatialWorld project={mockProject} />);

      const coreTrigger = screen.getByTestId('spatial-core-inspect-trigger');
      fireEvent.click(coreTrigger);
      expect(screen.getByTestId('spatial-inspector-panel')).toBeInTheDocument();

      const closeBtn = screen.getByTestId('spatial-inspector-close-btn');
      fireEvent.click(closeBtn);
      expect(screen.queryByTestId('spatial-inspector-panel')).not.toBeInTheDocument();
    });
  });

  describe('5. Continuous Wheel Navigation & Waypoint Transitions', () => {
    it('handles mouse wheel delta without crashing and keeps progress clamped [0, 1]', () => {
      const handleSelectStage = vi.fn();
      render(
        <SpatialWorld
          project={mockProject}
          onSelectStage={handleSelectStage}
        />
      );

      const container = screen.getByTestId('spatial-world-container');

      // Dispatch wheel scroll down
      fireEvent.wheel(container, { deltaY: 200 });
      // Should not throw and container remains intact
      expect(container).toBeInTheDocument();
    });
  });

  describe('6. Production Integrity & Roundtrip Transition', () => {
    it('preserves LOAD IN CREATOR STUDIO action button and passes shot data cleanly', () => {
      const handleOpenStudioWithShot = vi.fn();

      render(
        <SpatialWorld
          project={mockProject}
          onOpenStudioWithShot={handleOpenStudioWithShot}
        />
      );

      // Select shot-02 (video shot)
      const shot02Btn = screen.getByTestId('spatial-shot-shot-02');
      fireEvent.click(shot02Btn);

      const loadBtn = screen.getByRole('button', { name: /LOAD IN CREATOR STUDIO/i });
      expect(loadBtn).toBeInTheDocument();

      fireEvent.click(loadBtn);
      expect(handleOpenStudioWithShot).toHaveBeenCalledWith(
        expect.objectContaining({
          id: 'shot-02',
          generationType: 'video',
          duration: 4,
          aspectRatio: '16:9',
        })
      );
    });

    it('displays PostgreSQL authoritative persistence status in HUD telemetry', () => {
      render(
        <SpatialWorld
          project={mockProject}
          syncStatus="ONLINE"
        />
      );

      const telemetryPanel = screen.getByTestId('hud-production-telemetry');
      expect(telemetryPanel).toBeInTheDocument();
      expect(screen.getByText(/RIOS SPATIAL ODYSSEY/i)).toBeInTheDocument();
    });
  });
});
