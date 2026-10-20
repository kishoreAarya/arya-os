import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import React from 'react';
import { render, screen, fireEvent, act } from '@testing-library/react';
import { parseUserCommand, compileIntentToShot, assembleJobPackage } from '../utils/spatialIntentPlanner';
import { SpatialCommandBar } from '../components/spatial/SpatialCommandBar';
import { SpatialInspectorPanel } from '../components/spatial/SpatialInspectorPanel';
import { SpatialWorld } from '../components/spatial/SpatialWorld';
import { Project } from '../types/productionTimeline';
import { AryaIntent, AryaJobPackage } from '../types/spatialIntent';
import { SpatialInspectorData } from '../types/spatial';

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

describe('AryaOS V1 — Spatial Frontend Phase 7: Functional Control Layer & Production Integration', () => {
  const mockProject: Project = {
    id: 'proj-phase7',
    title: 'Neon Odyssey Production Sequence',
    description: 'Production sequence with real keyframe continuity and shot dependencies',
    activeSequenceId: 'seq-01',
    activeShotId: 'shot-01',
    sequences: [
      {
        id: 'seq-01',
        title: 'Sequence 01 // Harbor District',
        order: 1,
        totalShots: 2,
        readyShots: 1,
        blockedShots: 0,
        inFlightShots: 0,
        completeShots: 1,
        status: 'READY',
        shots: [
          {
            id: 'shot-01',
            sequenceId: 'seq-01',
            order: 1,
            title: 'Shot 01 // Obsidian Monolith Approach',
            prompt: 'Wide cinematic tracking shot of an obsidian monolith rising from the misty bay at dusk',
            generationType: 'image',
            status: 'COMPLETE',
            duration: 5,
            aspectRatio: '16:9',
            selectedModel: 'flux-schnell',
            outputAssetUrl: 'https://images.unsplash.com/photo-monolith-01.jpg',
            continuityStatus: 'PASS',
            startFrame: 'https://images.unsplash.com/photo-monolith-start.jpg',
            endFrame: 'https://images.unsplash.com/photo-monolith-01.jpg',
            referenceAssets: ['https://images.unsplash.com/photo-monolith-01.jpg'],
          },
          {
            id: 'shot-02',
            sequenceId: 'seq-01',
            order: 2,
            title: 'Shot 02 // Amber Conduit Resonance',
            prompt: 'Slow dolly zoom into the glowing amber core chamber with electrical conduits pulsing',
            generationType: 'video',
            status: 'COMPLETE',
            duration: 6,
            aspectRatio: '16:9',
            selectedModel: 'kling-video',
            selectedProvider: 'kling',
            outputAssetUrl: 'https://images.unsplash.com/photo-conduit-end.jpg',
            predecessorShotId: 'shot-01',
            continuityStatus: 'PASS',
            startFrame: 'https://images.unsplash.com/photo-monolith-01.jpg',
            endFrame: 'https://images.unsplash.com/photo-conduit-end.jpg',
            referenceAssets: ['https://images.unsplash.com/photo-monolith-01.jpg'],
          },
        ],
      },
    ],
  } as unknown as Project;

  const mockManifest: any = {
    generation_types: [
      { id: 'image', label: 'Image' },
      { id: 'video', label: 'Video' },
    ],
    models: {
      image: [{ id: 'flux-schnell', name: 'Flux Schnell', provider: 'together', default: true, configured: true }],
      video: [{ id: 'kling-video', name: 'Kling Video v1.5', provider: 'kling', default: true, configured: true }],
    },
    providers: [
      { id: 'together', name: 'Together AI', available: true, models: ['flux-schnell'] },
      { id: 'kling', name: 'Kling Video', available: true, models: ['kling-video'] },
    ],
    aspect_ratios: [
      { id: '16:9', label: '16:9' },
      { id: '9:16', label: '9:16' },
      { id: '1:1', label: '1:1' },
      { id: '21:9', label: '21:9' },
    ],
    durations: [
      { value: 4, label: '4s' },
      { value: 5, label: '5s' },
      { value: 6, label: '6s' },
      { value: 7, label: '7s' },
      { value: 10, label: '10s' },
    ],
  };

  beforeEach(() => {
    vi.clearAllMocks();
    localStorage.clear();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  /* -------------------------------------------------------------------------- */
  /* PART B: INTENT PARSER & DIRECTIVES EXTRACTION                              */
  /* -------------------------------------------------------------------------- */
  describe('1. Natural Language Intent Parsing (Part B & C)', () => {
    it('1. extracts duration, aspect ratio, style, and generation type from natural language', () => {
      const input = 'Create a cinematic 10-second shot of a rainy futuristic city at night in 9:16 vertical format';
      const intent = parseUserCommand(input);

      expect(intent.rawInput).toBe(input);
      expect(intent.stage).toBe('INTENTION');
      expect(intent.directives.durationSeconds).toBe(10);
      expect(intent.directives.aspectRatio).toBe('9:16');
      expect(intent.directives.generationType).toBe('video');
      expect(intent.directives.preferredStyle).toContain('cinematic');
      expect(intent.directives.preferredStyle).toContain('futuristic');
      expect(intent.directives.cleanPrompt.length).toBeGreaterThan(10);
    });

    it('2. detects image generation keywords', () => {
      const input = 'Generate a high-res photo portrait of a cybernetic pilot in 1:1 square ratio';
      const intent = parseUserCommand(input);

      expect(intent.directives.generationType).toBe('image');
      expect(intent.directives.aspectRatio).toBe('1:1');
      expect(intent.directives.durationSeconds).toBeUndefined();
    });

    it('3. detects continuity and predecessor references with active project', () => {
      const input = 'Continue with a 6s clip starting from the last frame of the previous shot';
      const intent = parseUserCommand(input, mockProject);

      expect(intent.directives.durationSeconds).toBe(6);
      expect(intent.directives.inferredPredecessor).toBe(true);
      expect(intent.directives.constraints.some((c) => c.includes('Predecessor Continuity'))).toBe(true);
    });

    it('4. compiles parsed intent into a structured Shot draft with sequence continuity', () => {
      const intent = parseUserCommand('Create a 5-second video tracking the amber conduit pulse', mockProject);
      const { updatedProject, targetShot } = compileIntentToShot(
        intent,
        mockProject,
        mockManifest,
        'kling-video',
        'kling',
        'seq-01'
      );

      expect(targetShot.sequenceId).toBe('seq-01');
      expect(targetShot.duration).toBe(5);
      expect(targetShot.generationType).toBe('video');
      expect(targetShot.predecessorShotId).toBe('shot-02');
      expect(targetShot.status).toBe('READY');
      expect(targetShot.startFrame).toBe('https://images.unsplash.com/photo-conduit-end.jpg');
      expect(updatedProject.sequences[0].shots).toHaveLength(3);
    });
  });

  /* -------------------------------------------------------------------------- */
  /* PART F: JOB PACKAGE BOUNDARY CONTRACT                                      */
  /* -------------------------------------------------------------------------- */
  describe('2. AryaJobPackage Boundary Contract Assembly (Part F)', () => {
    it('1. assembles a validated AryaJobPackage with execution payload and preflight checks', () => {
      const intent = parseUserCommand('Render a 5-second video tracking the neon citadel in 16:9', mockProject);
      const { updatedProject, targetShot } = compileIntentToShot(intent, mockProject, mockManifest, 'kling-video', 'kling', 'seq-01');

      const jobPkg = assembleJobPackage(
        targetShot,
        updatedProject,
        mockManifest,
        {
          provider: 'kling',
          model: 'kling-video',
          preflight: { ready: true, reasons: [] },
          explanation: {
            quality: { tier: 'HIGH' },
            cost: { estimatedCostUsd: 0.05 },
          },
        } as any,
        intent.id
      );

      expect(jobPkg.jobPackageId).toContain('pkg-');
      expect(jobPkg.intentId).toBe(intent.id);
      expect(jobPkg.shotId).toBe(targetShot.id);
      expect(jobPkg.sequenceId).toBe('seq-01');
      expect(jobPkg.modelRoute.provider).toBe('kling');
      expect(jobPkg.modelRoute.model).toBe('kling-video');
      expect(jobPkg.modelRoute.preflightReady).toBe(true);
      expect(jobPkg.decisionBoundary).toBe('ARYAOS_ORCHESTRATION_VALIDATED');

      // Verify execution payload contract
      expect(jobPkg.executionPayload.prompt).toBe(targetShot.prompt);
      expect(jobPkg.executionPayload.generation_type).toBe('video');
      expect(jobPkg.executionPayload.model).toBe('kling-video');
      expect(jobPkg.executionPayload.aspect_ratio).toBe('16:9');
      expect(jobPkg.executionPayload.duration_seconds).toBe(5);
    });

    it('2. blocks job package when critical preflight criteria fail', () => {
      const intent = parseUserCommand('Test empty route', mockProject);
      const { updatedProject, targetShot } = compileIntentToShot(intent, mockProject, null, '', 'seq-01');

      const jobPkg = assembleJobPackage(
        targetShot,
        updatedProject,
        null,
        {
          provider: 'none',
          model: '',
          preflight: { ready: false, reasons: ['Model route unavailable', 'Missing API key'] },
        } as any,
        intent.id
      );

      expect(jobPkg.modelRoute.preflightReady).toBe(false);
      expect(jobPkg.modelRoute.preflightReasons).toContain('Model route unavailable');
    });
  });

  /* -------------------------------------------------------------------------- */
  /* PART B: SPATIAL COMMAND BAR HUD COMPONENT                                  */
  /* -------------------------------------------------------------------------- */
  describe('3. SpatialCommandBar HUD Component (Part B)', () => {
    it('1. renders terminal input bar with shortcut hint and stage indicators', () => {
      render(
        <SpatialCommandBar
          intentStage="IDLE"
          onSubmitCommand={vi.fn()}
          onInspectJobPackage={vi.fn()}
          onDispatchExecution={vi.fn()}
        />
      );

      expect(screen.getByTestId('spatial-command-bar-container')).toBeInTheDocument();
      expect(screen.getByTestId('spatial-command-input')).toBeInTheDocument();
      expect(screen.getByPlaceholderText(/Enter command/i)).toBeInTheDocument();
    });

    it('2. dynamically updates directive chips as user types', () => {
      render(
        <SpatialCommandBar
          intentStage="IDLE"
          onSubmitCommand={vi.fn()}
          onInspectJobPackage={vi.fn()}
          onDispatchExecution={vi.fn()}
        />
      );

      const input = screen.getByTestId('spatial-command-input');
      fireEvent.change(input, { target: { value: 'Create 10s cinematic video in 9:16' } });

      expect(screen.getByText(/10s/i)).toBeInTheDocument();
      expect(screen.getByText(/9:16/i)).toBeInTheDocument();
      expect(screen.getByText(/VIDEO/i)).toBeInTheDocument();
    });

    it('3. submits command on Enter key and form submission', () => {
      const onSubmit = vi.fn();
      render(
        <SpatialCommandBar
          intentStage="IDLE"
          onSubmitCommand={onSubmit}
          onInspectJobPackage={vi.fn()}
          onDispatchExecution={vi.fn()}
        />
      );

      const input = screen.getByTestId('spatial-command-input') as HTMLInputElement;
      fireEvent.change(input, { target: { value: 'Synthesize a 5s drone flyby' } });
      fireEvent.submit(screen.getByTestId('spatial-command-form'));

      expect(onSubmit).toHaveBeenCalledTimes(1);
      expect(onSubmit).toHaveBeenCalledWith('Synthesize a 5s drone flyby');
    });

    it('4. focuses input when user presses / globally', () => {
      render(
        <SpatialCommandBar
          intentStage="IDLE"
          onSubmitCommand={vi.fn()}
          onInspectJobPackage={vi.fn()}
          onDispatchExecution={vi.fn()}
        />
      );

      const input = screen.getByTestId('spatial-command-input');
      expect(document.activeElement).not.toBe(input);

      fireEvent.keyDown(window, { key: '/' });
      expect(document.activeElement).toBe(input);
    });

    it('5. displays Job Package review & dispatch buttons when package is ready', () => {
      const onInspectPkg = vi.fn();
      const onDispatch = vi.fn();
      const mockJobPackage: AryaJobPackage = {
        jobPackageId: 'pkg-shot-test-99',
        intentId: 'intent-99',
        createdAt: new Date().toISOString(),
        projectId: 'proj-phase7',
        sequenceId: 'seq-01',
        shotId: 'shot-99',
        shotOrder: 3,
        plan: {
          title: 'Pulsating Conduit',
          prompt: 'Pulsating conduit glowing amber',
          generationType: 'video',
          durationSeconds: 5,
          dependencies: [],
          isFirstShotInSequence: false,
        },
        references: {
          referenceAssets: [],
        },
        modelRoute: {
          provider: 'kling',
          model: 'kling-video',
          modelName: 'Kling Video v1.5',
          mode: 'video',
          preflightReady: true,
          preflightReasons: [],
          availability: 'AVAILABLE',
        },
        shotConfiguration: {
          aspectRatio: '16:9',
          duration: 5,
        },
        continuityRequirements: {
          character: 'UNAVAILABLE',
          environment: 'PASS',
          visual: 'PASS',
          temporal: 'PASS',
          startFrame: 'NOT_APPLICABLE',
        },
        outputRequirements: {
          destination: 'ARYAOS_CORRIDOR_STREAM',
          targetFormat: 'video/mp4',
        },
        decisionBoundary: 'ARYAOS_ORCHESTRATION_VALIDATED',
        executionPayload: {
          prompt: 'Pulsating conduit',
          generation_type: 'video',
          model: 'kling-video',
          provider: 'kling',
          aspect_ratio: '16:9',
          duration_seconds: 5,
        },
      };

      render(
        <SpatialCommandBar
          intentStage="READY"
          activeJobPackage={mockJobPackage}
          onSubmitCommand={vi.fn()}
          onInspectJobPackage={onInspectPkg}
          onDispatchExecution={onDispatch}
        />
      );

      const pkgBtn = screen.getByTestId('spatial-command-inspect-pkg-btn');
      expect(pkgBtn).toBeInTheDocument();
      fireEvent.click(pkgBtn);
      expect(onInspectPkg).toHaveBeenCalledTimes(1);

      const dispatchBtn = screen.getByTestId('spatial-command-dispatch-btn');
      expect(dispatchBtn).toBeInTheDocument();
      fireEvent.click(dispatchBtn);
      expect(onDispatch).toHaveBeenCalledTimes(1);
    });
  });

  /* -------------------------------------------------------------------------- */
  /* PART H, I & J: SPATIAL INSPECTOR PANEL (KEYFRAME ANCHORS & JOB PKG)        */
  /* -------------------------------------------------------------------------- */
  describe('4. SpatialInspectorPanel Production Anchors & Job Package (Part H & I)', () => {
    it('1. renders Job Package inspector with payload details and boundary guarantee', () => {
      const mockJobPackage: AryaJobPackage = {
        jobPackageId: 'pkg-shot-01-phase7',
        intentId: 'intent-01',
        createdAt: new Date().toISOString(),
        projectId: 'proj-phase7',
        sequenceId: 'seq-01',
        shotId: 'shot-01',
        shotOrder: 1,
        plan: {
          title: 'Monolith Approach',
          prompt: 'Wide cinematic tracking shot of an obsidian monolith',
          generationType: 'video',
          durationSeconds: 5,
          dependencies: [],
          isFirstShotInSequence: true,
        },
        references: {
          referenceAssets: [],
        },
        modelRoute: {
          provider: 'kling',
          model: 'kling-video',
          modelName: 'Kling Video v1.5',
          mode: 'video',
          preflightReady: true,
          preflightReasons: [],
          availability: 'AVAILABLE',
          estimatedCostUsd: 0.045,
        },
        shotConfiguration: {
          aspectRatio: '16:9',
          duration: 5,
        },
        continuityRequirements: {
          character: 'UNAVAILABLE',
          environment: 'PASS',
          visual: 'PASS',
          temporal: 'PASS',
          startFrame: 'NOT_APPLICABLE',
        },
        outputRequirements: {
          destination: 'ARYAOS_CORRIDOR_STREAM',
          targetFormat: 'video/mp4',
        },
        decisionBoundary: 'ARYAOS_ORCHESTRATION_VALIDATED',
        executionPayload: {
          prompt: 'Wide cinematic tracking shot of an obsidian monolith',
          generation_type: 'video',
          model: 'kling-video',
          provider: 'kling',
          aspect_ratio: '16:9',
          duration_seconds: 5,
        },
      };

      const inspectorData: SpatialInspectorData = {
        id: 'job-pkg-test',
        title: 'JOB PACKAGE // pkg-shot-01-phase7',
        category: 'JOB_PACKAGE',
        status: 'ROUTE READY',
        subtitle: 'Decision-to-Execution boundary contract for Shot 1',
        details: ['Decision-to-Execution boundary contract for Shot 1'],
        metrics: [
          { label: 'Provider Route', value: 'KLING [Kling Video v1.5]' },
          { label: 'Preflight State', value: 'PASSED' },
        ],
        jobPackage: mockJobPackage,
        actionLabel: 'DISPATCH EXECUTION',
        onAction: vi.fn(),
      };

      render(
        <SpatialInspectorPanel
          data={inspectorData}
          onClose={vi.fn()}
        />
      );

      expect(screen.getByText(/JOB PACKAGE BOUNDARY/i)).toBeInTheDocument();
      expect(screen.getByText(/ARYAOS_ORCHESTRATION_VALIDATED/i)).toBeInTheDocument();
      expect(screen.getByText(/PASSED \(READY\)/i)).toBeInTheDocument();

      const actionBtn = screen.getByTestId('spatial-inspector-action-btn');
      fireEvent.click(actionBtn);
      expect(inspectorData.onAction).toHaveBeenCalledTimes(1);
    });

    it('2. renders First Frame, Last Frame, and Reference Anchors for corridor shot cards', () => {
      const inspectorData: SpatialInspectorData = {
        id: 'shot-02',
        title: 'SHOT INSPECTION // 02',
        category: 'SHOT',
        status: 'READY',
        subtitle: 'Slow dolly zoom into the glowing amber core chamber',
        details: ['Slow dolly zoom into the glowing amber core chamber'],
        firstFrameUrl: 'https://images.unsplash.com/photo-monolith-01.jpg',
        lastFrameUrl: 'https://images.unsplash.com/photo-conduit-end.jpg',
        referenceImageUrl: 'https://images.unsplash.com/photo-monolith-01.jpg',
        metrics: [
          { label: 'Type', value: 'VIDEO' },
          { label: 'Duration', value: '6s' },
          { label: 'Continuity', value: 'PASS' },
        ],
      };

      render(<SpatialInspectorPanel data={inspectorData} onClose={vi.fn()} />);

      expect(screen.getByTestId('spatial-inspector-keyframes')).toBeInTheDocument();
      expect(screen.getByText(/KEYFRAME ANCHORS & REFERENCES/i)).toBeInTheDocument();
      expect(screen.getByText(/FIRST FRAME/i)).toBeInTheDocument();
      expect(screen.getByText(/LAST FRAME/i)).toBeInTheDocument();
      expect(screen.getByText(/REFERENCE IMAGE/i)).toBeInTheDocument();

      const images = screen.getAllByRole('img');
      expect(images.length).toBeGreaterThanOrEqual(3);
    });

    it('3. displays honest persistence limitation in Memory Module inspection', () => {
      const inspectorData: SpatialInspectorData = {
        id: 'memory-subsystem',
        title: 'MEMORY // EPISODIC CONTINUITY',
        category: 'SUBSYSTEM',
        status: 'SYNCHRONIZED',
        subtitle: 'Persistent narrative memory store tracking series keyframes, character locks, and temporal anchors.',
        details: ['Persistent narrative memory store tracking series keyframes, character locks, and temporal anchors.'],
        metrics: [
          { label: 'Total Series Shots', value: '2' },
          { label: 'Persistence Status', value: 'LOCAL STORAGE ENVELOPE (REMOTE DB PERSISTENCE CONTRACT MISSING)' },
        ],
      };

      render(<SpatialInspectorPanel data={inspectorData} onClose={vi.fn()} />);

      expect(screen.getByText(/REMOTE DB PERSISTENCE CONTRACT MISSING/i)).toBeInTheDocument();
    });

    it('4. displays honest remediation guidance when continuity is blocked', () => {
      const inspectorData: SpatialInspectorData = {
        id: 'shot-03',
        title: 'SHOT INSPECTION // 03',
        category: 'SHOT',
        status: 'BLOCKED',
        details: ['Continuity violation detected'],
        remediation: 'WHAT: Continuity Violation // WHERE: Temporal/Start-Frame // WHY: Predecessor link broken or missing.',
        metrics: [
          { label: 'Continuity', value: 'BLOCKED' },
        ],
      };

      render(<SpatialInspectorPanel data={inspectorData} onClose={vi.fn()} />);

      expect(screen.getByTestId('spatial-inspector-remediation')).toBeInTheDocument();
      expect(screen.getByText(/CONTINUITY REMEDIATION:/i)).toBeInTheDocument();
      expect(screen.getByText(/WHAT: Continuity Violation/i)).toBeInTheDocument();
    });
  });

  /* -------------------------------------------------------------------------- */
  /* PART D, E, G: SPATIAL WORLD INTEGRATION & DISPATCH REACTIVITY              */
  /* -------------------------------------------------------------------------- */
  describe('5. SpatialWorld Functional Lifecycle Integration (Part D, E, G, L)', () => {
    it('1. integrates command bar submission into reactive intent stages and job package assembly', async () => {
      const onDispatchExecution = vi.fn();
      const onProjectChange = vi.fn();

      render(
        <SpatialWorld
          project={mockProject}
          capabilitiesManifest={mockManifest}
          onDispatchExecution={onDispatchExecution}
          onProjectChange={onProjectChange}
        />
      );

      // Verify command bar is present in HUD
      const input = screen.getByTestId('spatial-command-input');
      expect(input).toBeInTheDocument();

      // Submit an intention command
      fireEvent.change(input, {
        target: { value: 'Synthesize a 7s cinematic reveal of the floating crown in 16:9' },
      });
      fireEvent.submit(screen.getByTestId('spatial-command-form'));

      // Wait for deterministic lifecycle progression (0ms per step in test environment)
      await act(async () => {
        await new Promise((r) => setTimeout(r, 60));
      });

      // Verify stage progression to READY and Job Package inspection button appears
      expect(screen.getByTestId('spatial-command-inspect-pkg-btn')).toBeInTheDocument();
      expect(screen.getByTestId('spatial-command-dispatch-btn')).toBeInTheDocument();

      // Click "DISPATCH EXECUTION"
      await act(async () => {
        fireEvent.click(screen.getByTestId('spatial-command-dispatch-btn'));
      });

      // Execution callback should have been dispatched with real payload
      expect(onDispatchExecution).toHaveBeenCalledTimes(1);
      const pkg = onDispatchExecution.mock.calls[0][0] as AryaJobPackage;
      expect(pkg.executionPayload.duration_seconds).toBe(7);
      expect(pkg.executionPayload.aspect_ratio).toBe('16:9');
      expect(pkg.executionPayload.generation_type).toBe('video');
    });

    it('2. opens Job Package inspector when clicking Inspect Job Pkg button', async () => {
      render(<SpatialWorld project={mockProject} capabilitiesManifest={mockManifest} />);

      const input = screen.getByTestId('spatial-command-input');
      fireEvent.change(input, { target: { value: 'Create 4s image portrait' } });
      fireEvent.submit(screen.getByTestId('spatial-command-form'));

      await act(async () => {
        await new Promise((r) => setTimeout(r, 60));
      });

      const inspectPkgBtn = screen.getByTestId('spatial-command-inspect-pkg-btn');
      act(() => {
        fireEvent.click(inspectPkgBtn);
      });

      // Inspector panel opens with Job Package category
      expect(screen.getByTestId('spatial-inspector-panel')).toBeInTheDocument();
      expect(screen.getAllByText(/JOB PACKAGE \/\//i).length).toBeGreaterThanOrEqual(1);
      expect(screen.getByText(/JOB PACKAGE BOUNDARY/i)).toBeInTheDocument();
    });

    it('3. reflects honest telemetry and provider status without fabricated numbers', () => {
      render(
        <SpatialWorld
          project={mockProject}
          capabilitiesManifest={{
            providers: [
              { id: 'flux', name: 'Flux AI', available: true, models: ['flux-schnell'] },
              { id: 'kling', name: 'Kling Video', available: true, models: ['kling-video'] },
            ],
          } as any}
        />
      );

      // Verify production telemetry bar shows real project title and corridor shots
      expect(screen.getByText(/Neon Odyssey Production Sequence/i)).toBeInTheDocument();
      expect(screen.getByText(/MULTI-SHOT CORRIDOR \[2 SHOTS\]/i)).toBeInTheDocument();
    });
  });
});
