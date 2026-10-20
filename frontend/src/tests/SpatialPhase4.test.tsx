import { describe, it, expect, vi, beforeEach } from 'vitest';
import React from 'react';
import { render, screen, fireEvent, act } from '@testing-library/react';
import { SpatialWorld } from '../components/spatial/SpatialWorld';
import { SpatialInspectorPanel } from '../components/spatial/SpatialInspectorPanel';
import { SpatialCameraRig } from '../components/spatial/SpatialCameraRig';
import { SpatialHudOverlay } from '../components/spatial/SpatialHudOverlay';
import { App } from '../App';
import { Project, Shot } from '../types/productionTimeline';
import { GenerationJob } from '../types/creator';
import { ProductionRecommendation } from '../types/productionDecision';
import { CAMERA_WAYPOINTS, SpatialCameraState, SpatialInspectorData } from '../types/spatial';

// Mock WebGL canvas & R3F for headless JSDOM environment
vi.mock('@react-three/fiber', () => ({
  Canvas: ({ children }: any) => <div data-testid="mock-r3f-canvas">{children}</div>,
  useFrame: vi.fn(),
  useThree: () => ({
    camera: {
      position: { set: vi.fn(), copy: vi.fn(), lerp: vi.fn() },
      lookAt: vi.fn(),
    },
  }),
}));

vi.mock('@react-three/drei', () => ({
  useGLTF: () => ({ scene: { clone: () => ({}) } }),
  MeshReflectorMaterial: () => null,
}));

describe('AryaOS V1 — Spatial Frontend Phase 4: Production Intelligence & Interaction Polish', () => {
  const mockProject: Project = {
    id: 'proj-phase4',
    title: 'Cyberpunk Odyssey V1',
    description: 'Cinematic multi-shot narrative sequence',
    activeSequenceId: 'seq-01',
    activeShotId: 'shot-02',
    sequences: [
      {
        id: 'seq-01',
        title: 'Sequence 01 // Neon District',
        order: 1,
        totalShots: 3,
        readyShots: 1,
        blockedShots: 1,
        inFlightShots: 0,
        completeShots: 1,
        status: 'READY',
        shots: [
          {
            id: 'shot-01',
            order: 1,
            title: 'Shot 01 // Neon Core Awakening',
            prompt: 'Wide cinematic establishing shot of neon core',
            generationType: 'image',
            status: 'COMPLETE',
            duration: 5,
            aspectRatio: '16:9',
            continuityStatus: 'PASS',
            continuityReport: {
              visual: { status: 'PASS', detail: 'Clean character match', source: 'CAPABILITY_MANIFEST' },
            } as any,
          },
          {
            id: 'shot-02',
            order: 2,
            title: 'Shot 02 // Alleyway Tracking',
            prompt: 'Camera dolly through rain-slicked alleyway with reference asset',
            generationType: 'video',
            status: 'READY',
            duration: 5,
            aspectRatio: '16:9',
            predecessorShotId: 'shot-01',
            continuityStatus: 'PASS',
            continuityReport: {
              visual: { status: 'PASS', detail: 'Continuous lighting', source: 'CAPABILITY_MANIFEST' },
            } as any,
          },
          {
            id: 'shot-03',
            order: 3,
            title: 'Shot 03 // Barricade Encounter',
            prompt: 'Encounter with hostile drone grid',
            generationType: 'image_to_video',
            status: 'BLOCKED',
            duration: 4,
            aspectRatio: '16:9',
            predecessorShotId: 'shot-02',
            continuityStatus: 'WARNING',
            continuityReport: {
              visual: { status: 'WARNING', detail: 'Character silhouette deviation', source: 'CAPABILITY_MANIFEST' },
            } as any,
          },
        ],
      },
    ],
  } as unknown as Project;

  const mockJob: GenerationJob = {
    job_id: 'job-p4-987654321',
    workflow_run_id: 'wf-run-1234',
    status: 'in_progress',
    generation_type: 'video',
    prompt: 'Camera dolly through rain-slicked alleyway',
    model: 'kling-v1',
    provider: 'Kling AI',
    total_cost_usd: 0.12,
    output: {},
  };

  const mockRecommendation: ProductionRecommendation = {
    status: 'READY',
    directive: 'Proceed with optimized route',
    reasons: ['Provider online and fully configured'],
    reasonCodes: ['CONFIGURATION_READY'],
    preflight: {
      ready: true,
      status: 'READY',
      reasons: [],
      reasonCodes: [],
      checks: [],
    },
    explanation: {
      modelName: 'kling-v1',
      modelId: 'kling-v1',
      provider: 'Kling AI',
      availability: 'AVAILABLE',
      supportedAspectRatios: ['16:9'],
      supportedResolutions: ['1080p'],
      supportedDurations: [5],
      startFrameSupport: 'SUPPORTED',
      endFrameSupport: 'SUPPORTED',
      referenceSupport: 'SUPPORTED',
      cost: {
        avgKnownCost: 0.12,
        recentCost: 0.12,
        totalKnownCost: 0.12,
        runCount: 1,
        hasCostData: true,
        displayStatus: 'KNOWN',
        source: 'HISTORICAL_RUN',
      },
      quality: {
        qualityScore: 9.4,
        qualityDataAvailable: true,
        label: 'KNOWN',
        displayText: 'High quality benchmark',
        source: 'CAPABILITY_MANIFEST',
      },
    },
    categorization: {
      hardBlocks: [],
      warnings: [],
      facts: [],
      userDecision: {
        status: 'READY',
        directive: 'Route verified',
        requiresConfirmation: false,
      },
    },
    preflightSummary: [],
    executionPreview: {
      mode: 'video',
      model: 'kling-v1',
      modelName: 'Kling Video V1',
      provider: 'Kling AI',
      aspectRatio: '16:9',
      resolution: '1080p',
      promptStatus: 'READY',
      promptPreview: 'Camera dolly through rain-slicked alleyway',
      referenceStatus: 'NONE',
      startFrameStatus: 'NONE',
      endFrameStatus: 'NONE',
      durationSeconds: 5,
      dispatchSteps: ['Validate credentials', 'Dispatch to Kling'],
    },
  } as unknown as ProductionRecommendation;

  describe('1. Core System Telemetry in Spatial HUD', () => {
    it('1. surfaces live production state: project title, route, execution status, and event', () => {
      render(
        <SpatialWorld
          project={mockProject}
          currentJob={mockJob}
          productionRecommendation={mockRecommendation}
          systemOperationalState="ACTIVE"
          historyCount={5}
        />
      );

      const telemetry = screen.getByTestId('hud-production-telemetry');
      expect(telemetry).toBeInTheDocument();
      expect(screen.getByText(/Cyberpunk Odyssey V1/i)).toBeInTheDocument();
      expect(screen.getByText(/Kling AI \/ Kling Video V1/i)).toBeInTheDocument();
      expect(screen.getAllByText(/IN_PROGRESS/i).length).toBeGreaterThanOrEqual(1);
      expect(screen.getAllByText(/65%/i).length).toBeGreaterThanOrEqual(1);
    });

    it('2. renders neutral fallback telemetry cleanly when no active job is present', () => {
      render(
        <SpatialWorld
          project={mockProject}
          currentJob={null}
          productionRecommendation={null}
          systemOperationalState="IDLE"
        />
      );

      const telemetry = screen.getByTestId('hud-production-telemetry');
      expect(telemetry).toBeInTheDocument();
      expect(screen.getByText(/NO ACTIVE RUN/i)).toBeInTheDocument();
      expect(screen.getByText(/SYSTEM INITIALIZED/i)).toBeInTheDocument();
    });
  });

  describe('2. Subsystem Modules Production Intelligence', () => {
    it('3. Memory module responds dynamically to continuity alerts and reference links', () => {
      render(
        <SpatialWorld
          project={mockProject}
          currentJob={mockJob}
        />
      );

      // In 2D fallback, memory module is rendered with live status
      const memBtn = screen.getByTestId('spatial-module-memory');
      expect(memBtn).toBeInTheDocument();
      // shot-03 has a warning, so memory status transitions to ACTIVE
      expect(memBtn).toHaveTextContent(/ACTIVE/i);
    });

    it('4. Planning module connects to timeline status and blocker counts', () => {
      render(
        <SpatialWorld
          project={mockProject}
        />
      );

      const planningBtn = screen.getByTestId('spatial-module-planning');
      expect(planningBtn).toBeInTheDocument();
      // shot-03 is BLOCKED, so planning module shows PROCESSING
      expect(planningBtn).toHaveTextContent(/PROCESSING/i);
    });

    it('5. Routing module reflects provider routing and preflight status', () => {
      render(
        <SpatialWorld
          project={mockProject}
          productionRecommendation={mockRecommendation}
        />
      );

      const routingBtn = screen.getByTestId('spatial-module-routing');
      expect(routingBtn).toBeInTheDocument();
      expect(routingBtn).toHaveTextContent(/READY/i);
    });

    it('6. Execution module connects to active workflow run state and load percent', () => {
      render(
        <SpatialWorld
          project={mockProject}
          currentJob={mockJob}
        />
      );

      const execBtn = screen.getByTestId('spatial-module-execution');
      expect(execBtn).toBeInTheDocument();
      expect(execBtn).toHaveTextContent(/PROCESSING/i);
      expect(execBtn).toHaveTextContent(/LOAD: 65%/i);
    });
  });

  describe('3. Multi-Shot Corridor Intelligence', () => {
    it('7. Shot cards expose live lifecycle status, duration, and continuity links', () => {
      render(
        <SpatialWorld
          project={mockProject}
        />
      );

      expect(screen.getByTestId('spatial-shot-shot-01')).toHaveTextContent(/COMPLETE/i);
      expect(screen.getByTestId('spatial-shot-shot-02')).toHaveTextContent(/READY/i);
      expect(screen.getByTestId('spatial-shot-shot-03')).toHaveTextContent(/BLOCKED/i);
      expect(screen.getByTestId('spatial-continuity-link-shot-01-shot-02')).toBeInTheDocument();
      expect(screen.getByTestId('spatial-continuity-link-shot-02-shot-03')).toBeInTheDocument();
    });
  });

  describe('4. Contextual Spatial Selection Inspector', () => {
    it('8. opens Core inspector when Core is clicked or triggered via HUD button', () => {
      render(
        <SpatialWorld
          project={mockProject}
          currentJob={mockJob}
          productionRecommendation={mockRecommendation}
          systemOperationalState="ACTIVE"
        />
      );

      const inspectCoreBtn = screen.getByTestId('hud-inspect-core-btn');
      fireEvent.click(inspectCoreBtn);

      const inspector = screen.getByTestId('spatial-inspector-panel');
      expect(inspector).toBeInTheDocument();
      expect(screen.getByText(/\[SYSTEM CORE\]/i)).toBeInTheDocument();
      expect(screen.getByText(/ARYAOS CORE V1/i)).toBeInTheDocument();
      expect(screen.getByText(/Hybrid GLB\/Procedural/i)).toBeInTheDocument();
      expect(screen.getByText(/Quantum monolith core/i)).toBeInTheDocument();
    });

    it('9. opens Subsystem Module inspector when a module is selected', () => {
      render(
        <SpatialWorld
          project={mockProject}
          productionRecommendation={mockRecommendation}
        />
      );

      const routingBtn = screen.getByTestId('spatial-module-routing');
      fireEvent.click(routingBtn);

      const inspector = screen.getByTestId('spatial-inspector-panel');
      expect(inspector).toBeInTheDocument();
      expect(screen.getByText(/\[SUBSYSTEM MODULE\]/i)).toBeInTheDocument();
      expect(screen.getByText(/ROUTING \/\/ DISPATCH ARBITRATION/i)).toBeInTheDocument();
      expect(screen.getByText(/ROUTE READY/i)).toBeInTheDocument();
      expect(screen.getByText(/AryaOS Routing Subsystem \/\/ MOD-03/i)).toBeInTheDocument();
    });

    it('10. opens Shot inspector when a corridor shot is selected', () => {
      render(
        <SpatialWorld
          project={mockProject}
        />
      );

      const shot3Btn = screen.getByTestId('spatial-shot-shot-03');
      fireEvent.click(shot3Btn);

      const inspector = screen.getByTestId('spatial-inspector-panel');
      expect(inspector).toBeInTheDocument();
      expect(screen.getByText(/\[PRODUCTION SHOT\]/i)).toBeInTheDocument();
      expect(screen.getByText(/SHOT INSPECTION \/\/ 03/i)).toBeInTheDocument();
      expect(screen.getAllByText(/Encounter with hostile drone grid/i).length).toBeGreaterThanOrEqual(1);
      expect(screen.getByText(/Predecessor Link: Shot shot-02/i)).toBeInTheDocument();
    });

    it('11. closes inspector cleanly when clicking close button [ESC // CLOSE]', () => {
      render(
        <SpatialWorld
          project={mockProject}
        />
      );

      // Open inspector
      fireEvent.click(screen.getByTestId('spatial-shot-shot-01'));
      expect(screen.getByTestId('spatial-inspector-panel')).toBeInTheDocument();

      // Click close button
      const closeBtn = screen.getByTestId('spatial-inspector-close');
      fireEvent.click(closeBtn);

      expect(screen.queryByTestId('spatial-inspector-panel')).not.toBeInTheDocument();
    });

    it('12. closes inspector when Escape key is pressed', () => {
      render(
        <SpatialWorld
          project={mockProject}
        />
      );

      // Open inspector
      fireEvent.click(screen.getByTestId('hud-inspect-core-btn'));
      expect(screen.getByTestId('spatial-inspector-panel')).toBeInTheDocument();

      // Press Escape key
      fireEvent.keyDown(window, { key: 'Escape', code: 'Escape' });

      expect(screen.queryByTestId('spatial-inspector-panel')).not.toBeInTheDocument();
    });
  });

  describe('5. Camera Focus & Station Preservation', () => {
    it('13. computes camera focus target on selection and clears on close', () => {
      const handleFocusTargetChange = vi.fn();
      render(
        <SpatialWorld
          project={mockProject}
          onFocusTargetChange={handleFocusTargetChange}
        />
      );

      // Select module
      fireEvent.click(screen.getByTestId('spatial-module-memory'));
      expect(handleFocusTargetChange).toHaveBeenCalledWith(
        expect.objectContaining({
          label: 'MEMORY',
        })
      );

      // Close inspector
      fireEvent.click(screen.getByTestId('spatial-inspector-close'));
      expect(handleFocusTargetChange).toHaveBeenCalledWith(null);
    });

    it('14. preserves all 6 spatial stations and switches viewpoints accurately', () => {
      render(<SpatialWorld initialCameraState="ENTRY" />);

      const container = screen.getByTestId('spatial-world-container');
      expect(container).toHaveAttribute('data-camera-state', 'ENTRY');

      // Click on APPROACH button
      const approachBtn = screen.getByRole('button', { name: /02 \/\/ APPROACH/i });
      fireEvent.click(approachBtn);
      expect(container).toHaveAttribute('data-camera-state', 'APPROACH');

      // Click on CORRIDOR button
      const corridorBtn = screen.getByRole('button', { name: /05 \/\/ CORRIDOR/i });
      fireEvent.click(corridorBtn);
      expect(container).toHaveAttribute('data-camera-state', 'CORRIDOR');
    });

    it('15. SpatialCameraRig accepts focusTarget and honors reduced motion without crashing', () => {
      const { rerender } = render(
        <SpatialCameraRig
          cameraState="HUB"
          pointer={{ x: 0, y: 0 }}
          isReducedMotion={false}
          focusTarget={{
            position: [0, 2.0, 5.0],
            target: [0, 1.8, 0],
            label: 'CORE',
          }}
        />
      );

      expect(CAMERA_WAYPOINTS.HUB).toBeDefined();

      // Rerender with reduced motion
      rerender(
        <SpatialCameraRig
          cameraState="HUB"
          pointer={{ x: 0, y: 0 }}
          isReducedMotion={true}
          focusTarget={null}
        />
      );

      expect(CAMERA_WAYPOINTS.COMMAND).toBeDefined();
    });
  });

  describe('6. Safety & Non-Destructive Observability', () => {
    it('16. spatial interactions and inspector contain zero generation or mutating buttons', () => {
      const sampleInspectorData: SpatialInspectorData = {
        category: 'CORE',
        id: 'core-test',
        title: 'TEST CORE',
        status: 'ONLINE',
        statusVariant: 'success',
        metrics: [{ label: 'STATUS', value: 'ACTIVE' }],
        details: ['Log 1', 'Log 2'],
      };

      render(
        <SpatialInspectorPanel
          data={sampleInspectorData}
          onClose={vi.fn()}
        />
      );

      // Verify no submit, generate, or execute button exists in inspector
      expect(screen.queryByRole('button', { name: /generate/i })).not.toBeInTheDocument();
      expect(screen.queryByRole('button', { name: /execute/i })).not.toBeInTheDocument();
      expect(screen.queryByRole('button', { name: /submit/i })).not.toBeInTheDocument();
      expect(screen.queryByRole('button', { name: /delete/i })).not.toBeInTheDocument();
    });

    it('17. allows seamless roundtrip transition into Creator Studio and back', async () => {
      render(<App initialView="spatial" />);

      // Verify spatial world is active
      expect(screen.getByTestId('spatial-world-container')).toBeInTheDocument();

      // Click Enter Creator Studio
      const enterStudioBtn = screen.getByRole('button', { name: /ENTER CREATOR STUDIO/i });
      await act(async () => {
        fireEvent.click(enterStudioBtn);
      });

      // Creator Studio should now be active
      expect(screen.getByRole('region', { name: /Creator Controls/i })).toBeInTheDocument();

      // Switch back to Spatial Core
      const spatialNavBtn = screen.getByRole('button', { name: /Spatial Core/i });
      await act(async () => {
        fireEvent.click(spatialNavBtn);
      });

      expect(screen.getByTestId('spatial-world-container')).toBeInTheDocument();
    });
  });
});
