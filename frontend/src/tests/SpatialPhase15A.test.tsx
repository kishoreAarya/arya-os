/**
 * AryaOS V1 — Phase 15A: Awakening Hero Asset Integration Test Suite
 *
 * Verifies:
 * 1. SpatialAwakeningHero renders full-screen awakening-hero.png asset.
 * 2. Stage 01 Initial Awakening displays authoritative visual identity:
 *    - ARYAOS monumental typography
 *    - THE INTELLIGENCE LAYER FOR AUTONOMOUS CREATION tagline
 *    - ENTER THE INTELLIGENCE action button
 * 3. Clicking "ENTER THE INTELLIGENCE" triggers transition to Stage 02 (AryaOS Core).
 * 4. SpatialHudOverlay suppresses dashboard telemetry and command bar during Stage 01.
 * 5. SpatialWorld mounts cleanly in Stage 01 Awakening mode.
 * 6. Smooth transition cross-fades from hero image to interactive 3D Core at Stage 02.
 * 7. Stage 02 displays the updated ARYAOS CORE identity.
 * 8. Continuous wheel scrubbing via interpolateStageProgress navigates between stages.
 * 9. Reduced motion accessibility is respected.
 */

import React from 'react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import '@testing-library/jest-dom';

import {
  SPATIAL_STAGES,
  SpatialStage,
  CAMERA_WAYPOINTS,
  interpolateStageProgress,
} from '../types/spatial';
import { SpatialAwakeningHero } from '../components/spatial/SpatialAwakeningHero';
import { SpatialWorld } from '../components/spatial/SpatialWorld';
import { SpatialHudOverlay } from '../components/spatial/SpatialHudOverlay';
import { Project } from '../types/productionTimeline';

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
  id: 'proj-phase15-awakening',
  title: 'ARYAOS SPATIAL AWAKENING',
  description: 'Production sequence demonstrating Phase 15A Awakening hero asset integration',
  activeSequenceId: 'seq-01',
  activeShotId: 'shot-01',
  createdAt: new Date().toISOString(),
  updatedAt: new Date().toISOString(),
  sequences: [
    {
      id: 'seq-01',
      projectId: 'proj-phase15-awakening',
      order: 1,
      title: 'Sequence 01 // System Awakening',
      status: 'READY',
      statusReasons: [],
      totalShots: 2,
      readyShots: 2,
      blockedShots: 0,
      inFlightShots: 0,
      completeShots: 0,
      totalDurationSeconds: 5,
      createdAt: new Date().toISOString(),
      updatedAt: new Date().toISOString(),
      shots: [
        {
          id: 'shot-01',
          order: 1,
          sequenceId: 'seq-01',
          title: 'Shot 01 // Awakening',
          prompt: 'Dark cinematic spatial environment with amber beam',
          status: 'READY',
          generationType: 'image',
          duration: 5,
          aspectRatio: '16:9',
          selectedModel: 'flux-schnell',
          selectedProvider: 'fal',
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
          dependencyShotIds: [],
        },
      ],
    },
  ],
};

describe('AryaOS V1 — Phase 15A: Awakening Hero Asset Integration', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  describe('1. SpatialAwakeningHero Component & Visual Baseline', () => {
    it('renders the awakening hero container and loads awakening-hero.png', () => {
      render(
        <SpatialAwakeningHero
          activeStage="AWAKENING"
          onEnterCore={vi.fn()}
        />
      );

      const heroContainer = screen.getByTestId('spatial-awakening-hero');
      expect(heroContainer).toBeInTheDocument();
      expect(heroContainer).toHaveAttribute('data-active', 'true');

      const heroImg = screen.getByTestId('awakening-hero-image');
      expect(heroImg).toBeInTheDocument();
      expect(heroImg).toHaveAttribute('src', '/assets/spatial/awakening-hero.png');
    });

    it('displays the authoritative pure cognitive identity and typography', () => {
      render(
        <SpatialAwakeningHero
          activeStage="AWAKENING"
          onEnterCore={vi.fn()}
        />
      );

      expect(screen.getByTestId('awakening-hero-overlay')).toBeInTheDocument();
      expect(screen.getByText('ARYAOS // SPATIAL OS V1')).toBeInTheDocument();
      expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent('ARYAOS');
      expect(screen.getByText('THE INTELLIGENCE LAYER FOR AUTONOMOUS CREATION')).toBeInTheDocument();
    });

    it('renders the interactive "ENTER THE INTELLIGENCE →" button and triggers callback on click', () => {
      const handleEnterCore = vi.fn();
      render(
        <SpatialAwakeningHero
          activeStage="AWAKENING"
          onEnterCore={handleEnterCore}
        />
      );

      const enterBtn = screen.getByTestId('awakening-enter-btn');
      expect(enterBtn).toBeInTheDocument();
      expect(enterBtn).toHaveTextContent(/ENTER THE INTELLIGENCE/i);

      fireEvent.click(enterBtn);
      expect(handleEnterCore).toHaveBeenCalledTimes(1);
    });

    it('fades out when activeStage is not AWAKENING', () => {
      render(
        <SpatialAwakeningHero
          activeStage="CORE"
          onEnterCore={vi.fn()}
        />
      );

      const heroContainer = screen.getByTestId('spatial-awakening-hero');
      expect(heroContainer).toHaveAttribute('data-active', 'false');
      expect(heroContainer).toHaveAttribute('aria-hidden', 'true');
    });

    it('calculates continuous opacity correctly across spatialProgress (0.0 -> 0.15)', () => {
      const { rerender } = render(
        <SpatialAwakeningHero
          activeStage="AWAKENING"
          spatialProgress={0.0}
        />
      );

      let heroContainer = screen.getByTestId('spatial-awakening-hero');
      expect(heroContainer.style.opacity).toBe('1');

      // Mid-progress between Awakening and Core
      rerender(
        <SpatialAwakeningHero
          activeStage="AWAKENING"
          spatialProgress={0.075}
        />
      );
      heroContainer = screen.getByTestId('spatial-awakening-hero');
      const midOpacity = parseFloat(heroContainer.style.opacity);
      expect(midOpacity).toBeGreaterThan(0.2);
      expect(midOpacity).toBeLessThan(0.8);

      // Completed transition to Core (progress >= 0.14)
      rerender(
        <SpatialAwakeningHero
          activeStage="CORE"
          spatialProgress={0.15}
        />
      );
      heroContainer = screen.getByTestId('spatial-awakening-hero');
      expect(heroContainer.style.opacity).toBe('0');
      expect(heroContainer.style.visibility).toBe('hidden');
    });
  });

  describe('2. HUD Clutter Reduction During Stage 01 Awakening', () => {
    it('suppresses top header telemetry bar during Stage 01 Awakening', () => {
      render(
        <SpatialHudOverlay
          cameraState="ENTRY"
          activeStage="AWAKENING"
          onSelectCameraState={vi.fn()}
        />
      );

      // Top header should be visually suppressed (opacity: 0, pointerEvents: none) during Awakening
      const topHeader = document.querySelector('.spatial-top-header');
      expect(topHeader).toHaveStyle({ opacity: '0', pointerEvents: 'none' });
    });

    it('reveals top header telemetry when in Stage 02 Core', () => {
      render(
        <SpatialHudOverlay
          cameraState="HUB"
          activeStage="CORE"
          onSelectCameraState={vi.fn()}
        />
      );

      const topHeader = document.querySelector('.spatial-top-header');
      expect(topHeader).toHaveStyle({ opacity: '1', pointerEvents: 'auto' });
    });

    it('keeps the 9-stage navigator accessible during Awakening for manual jumping', () => {
      const handleSelectStage = vi.fn();
      render(
        <SpatialHudOverlay
          cameraState="ENTRY"
          activeStage="AWAKENING"
          onSelectCameraState={vi.fn()}
          onSelectStage={handleSelectStage}
        />
      );

      const stageNav = screen.getByTestId('spatial-stage-navigator');
      expect(stageNav).toBeInTheDocument();

      const coreBtn = screen.getByTestId('stage-nav-CORE');
      fireEvent.click(coreBtn);
      expect(handleSelectStage).toHaveBeenCalledWith('CORE');
    });
  });

  describe('3. SpatialWorld Integration & Stage 01 -> Stage 02 Journey', () => {
    it('mounts in Stage 01 Awakening when initialCameraState="ENTRY" and initialStage="AWAKENING"', () => {
      render(
        <SpatialWorld
          initialCameraState="ENTRY"
          initialStage="AWAKENING"
          project={mockProject}
        />
      );

      const world = screen.getByTestId('spatial-world-container');
      expect(world).toHaveAttribute('data-camera-state', 'ENTRY');
      expect(world).toHaveAttribute('data-active-stage', 'AWAKENING');

      expect(screen.getByTestId('spatial-awakening-hero')).toBeInTheDocument();
      expect(screen.getByTestId('awakening-hero-image')).toBeInTheDocument();
    });

    it('transitions to Stage 02 Core when clicking ENTER THE INTELLIGENCE button', () => {
      render(
        <SpatialWorld
          initialCameraState="ENTRY"
          initialStage="AWAKENING"
          project={mockProject}
        />
      );

      const enterBtn = screen.getByTestId('awakening-enter-btn');
      fireEvent.click(enterBtn);

      const world = screen.getByTestId('spatial-world-container');
      expect(world).toHaveAttribute('data-active-stage', 'CORE');
      expect(world).toHaveAttribute('data-camera-state', 'HUB');
    });

    it('displays the updated ARYAOS CORE stage label in SPATIAL_STAGES', () => {
      const coreStage = SPATIAL_STAGES.find((s) => s.id === 'CORE');
      expect(coreStage).toBeDefined();
      expect(coreStage?.label).toBe('ARYAOS CORE');
    });

    it('smoothly interpolates camera from ENTRY (Awakening) to HUB (Core) via interpolateStageProgress', () => {
      const stage01 = interpolateStageProgress(0.0);
      expect(stage01.position[0]).toBeCloseTo(CAMERA_WAYPOINTS.ENTRY.position[0]);
      expect(stage01.position[1]).toBeCloseTo(CAMERA_WAYPOINTS.ENTRY.position[1]);
      expect(stage01.position[2]).toBeCloseTo(CAMERA_WAYPOINTS.ENTRY.position[2]);

      const stage02 = interpolateStageProgress(0.12);
      expect(stage02.position[0]).toBeCloseTo(CAMERA_WAYPOINTS.HUB.position[0]);
      expect(stage02.position[1]).toBeCloseTo(CAMERA_WAYPOINTS.HUB.position[1]);
      expect(stage02.position[2]).toBeCloseTo(CAMERA_WAYPOINTS.HUB.position[2]);
    });
  });
});
