import { describe, it, expect, vi, beforeEach } from 'vitest';
import React from 'react';
import { render, screen, fireEvent, act } from '@testing-library/react';
import { SpatialWorld } from '../components/spatial/SpatialWorld';
import { SpatialInspectorPanel } from '../components/spatial/SpatialInspectorPanel';
import { SpatialShortcutsModal } from '../components/spatial/SpatialShortcutsModal';
import { SpatialHudOverlay } from '../components/spatial/SpatialHudOverlay';
import { App } from '../App';
import { Project, Shot } from '../types/productionTimeline';
import { spatialAudio } from '../utils/spatialAudio';
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

describe('AryaOS V1 — Spatial Frontend Phase 5: Polished Production-Grade Experience', () => {
  const mockMultiSeqProject: Project = {
    id: 'proj-phase5',
    title: 'Cyberpunk Odyssey V1',
    description: 'Cinematic multi-shot narrative sequence with multiple sequences',
    activeSequenceId: 'seq-01',
    activeShotId: 'shot-01',
    sequences: [
      {
        id: 'seq-01',
        title: 'Sequence 01 // Neon District',
        order: 1,
        totalShots: 2,
        readyShots: 2,
        blockedShots: 0,
        inFlightShots: 0,
        completeShots: 1,
        status: 'READY',
        shots: [
          {
            id: 'shot-01',
            sequenceId: 'seq-01',
            order: 1,
            title: 'Shot 01 // Obsidian Monolith Awakening',
            prompt: 'Wide cinematic shot of glowing obsidian monolith',
            generationType: 'image',
            status: 'COMPLETE',
            duration: 5,
            aspectRatio: '16:9',
            selectedModel: 'flux-schnell',
            outputAssetUrl: 'https://images.unsplash.com/photo-test-monolith.jpg',
            continuityStatus: 'PASS',
          },
          {
            id: 'shot-02',
            sequenceId: 'seq-01',
            order: 2,
            title: 'Shot 02 // Conduit Pulse',
            prompt: 'Dolly zoom into pulsating conduit rings',
            generationType: 'video',
            status: 'READY',
            duration: 5,
            aspectRatio: '16:9',
            selectedModel: 'kling-video',
            predecessorShotId: 'shot-01',
            continuityStatus: 'PASS',
          },
        ],
      },
      {
        id: 'seq-02',
        title: 'Sequence 02 // Orbital Station Hub',
        order: 2,
        totalShots: 2,
        readyShots: 1,
        blockedShots: 1,
        inFlightShots: 0,
        completeShots: 0,
        status: 'BLOCKED',
        shots: [
          {
            id: 'shot-03',
            sequenceId: 'seq-02',
            order: 1,
            title: 'Shot 03 // Docking Bay Atmospheric Entry',
            prompt: 'Spacecraft docking in atmospheric cloud chamber',
            generationType: 'video',
            status: 'READY',
            duration: 6,
            aspectRatio: '16:9',
            selectedModel: 'runway-gen3',
            continuityStatus: 'PASS',
          },
          {
            id: 'shot-04',
            sequenceId: 'seq-02',
            order: 2,
            title: 'Shot 04 // Reactor Chamber Lockdown',
            prompt: 'Deep reactor chamber emergency lockdown with crimson sparks',
            generationType: 'video',
            status: 'BLOCKED',
            duration: 4,
            aspectRatio: '16:9',
            selectedModel: 'kling-video',
            predecessorShotId: 'shot-03',
            continuityStatus: 'BLOCKED',
            failureDetails: {
              reason: 'Predecessor continuity mismatch: keyframe style diverged',
            },
          },
        ],
      },
    ],
  } as unknown as Project;

  beforeEach(() => {
    vi.clearAllMocks();
    localStorage.clear();
  });

  describe('1. Operator Keyboard Shortcuts & Command Matrix', () => {
    it('1. switches camera stations using number keys 1 through 6', () => {
      render(<SpatialWorld project={mockMultiSeqProject} initialCameraState="HUB" />);
      const container = screen.getByTestId('spatial-world-container');
      expect(container).toHaveAttribute('data-camera-state', 'HUB');

      // Key 1: ENTRY
      fireEvent.keyDown(window, { key: '1' });
      expect(container).toHaveAttribute('data-camera-state', 'ENTRY');

      // Key 2: APPROACH
      fireEvent.keyDown(window, { key: '2' });
      expect(container).toHaveAttribute('data-camera-state', 'APPROACH');

      // Key 4: SYSTEMS
      fireEvent.keyDown(window, { key: '4' });
      expect(container).toHaveAttribute('data-camera-state', 'SYSTEMS');

      // Key 5: CORRIDOR
      fireEvent.keyDown(window, { key: '5' });
      expect(container).toHaveAttribute('data-camera-state', 'CORRIDOR');

      // Key 6: COMMAND
      fireEvent.keyDown(window, { key: '6' });
      expect(container).toHaveAttribute('data-camera-state', 'COMMAND');

      // Key 3: Return to HUB
      fireEvent.keyDown(window, { key: '3' });
      expect(container).toHaveAttribute('data-camera-state', 'HUB');
    });

    it('2. opens Creator Studio with key C', () => {
      const onOpenStudio = vi.fn();
      render(<SpatialWorld project={mockMultiSeqProject} onOpenStudio={onOpenStudio} />);

      fireEvent.keyDown(window, { key: 'c' });
      expect(onOpenStudio).toHaveBeenCalledTimes(1);

      fireEvent.keyDown(window, { key: 'C' });
      expect(onOpenStudio).toHaveBeenCalledTimes(2);
    });

    it('3. toggles Cinematic Mode with key H', () => {
      render(<SpatialWorld project={mockMultiSeqProject} />);

      // Initially HUD is visible
      expect(screen.getByTestId('hud-production-telemetry')).toBeInTheDocument();

      // Press 'h' -> Enter Cinematic Mode
      fireEvent.keyDown(window, { key: 'h' });
      expect(screen.getByTestId('spatial-hud-cinematic')).toBeInTheDocument();
      expect(screen.getByTestId('hud-exit-cinematic-btn')).toBeInTheDocument();

      // Press 'h' again -> Exit Cinematic Mode
      fireEvent.keyDown(window, { key: 'h' });
      expect(screen.getByTestId('hud-production-telemetry')).toBeInTheDocument();
    });

    it('4. opens Core Inspector with key I', () => {
      render(<SpatialWorld project={mockMultiSeqProject} />);

      // Initially inspector is not visible
      expect(screen.queryByTestId('spatial-inspector-panel')).not.toBeInTheDocument();

      // Press 'i' -> Opens Core Inspector
      fireEvent.keyDown(window, { key: 'i' });
      expect(screen.getByTestId('spatial-inspector-panel')).toBeInTheDocument();
      expect(screen.getByText(/ARYAOS CORE V1/i)).toBeInTheDocument();
    });

    it('5. cycles subsystem modules with key M', () => {
      render(<SpatialWorld project={mockMultiSeqProject} />);

      // Press 'm' -> Selects MEMORY
      fireEvent.keyDown(window, { key: 'm' });
      expect(screen.getByTestId('spatial-inspector-panel')).toBeInTheDocument();
      expect(screen.getByText(/MEMORY \/\/ EPISODIC CONTINUITY/i)).toBeInTheDocument();

      // Press 'm' again -> Selects PLANNING
      fireEvent.keyDown(window, { key: 'm' });
      expect(screen.getByText(/PLANNING \/\/ SEQUENCE SYNTHESIS/i)).toBeInTheDocument();

      // Press 'm' again -> Selects ROUTING
      fireEvent.keyDown(window, { key: 'm' });
      expect(screen.getByText(/ROUTING \/\/ DISPATCH ARBITRATION/i)).toBeInTheDocument();

      // Press 'm' again -> Selects EXECUTION
      fireEvent.keyDown(window, { key: 'm' });
      expect(screen.getByText(/EXECUTION \/\/ RUNTIME SYNTHESIS/i)).toBeInTheDocument();
    });

    it('6. traverses corridor shots with keys [ and ]', () => {
      render(<SpatialWorld project={mockMultiSeqProject} />);

      // Press ']' -> selects next shot (shot-01 or shot-02)
      fireEvent.keyDown(window, { key: ']' });
      expect(screen.getByTestId('spatial-inspector-panel')).toBeInTheDocument();

      // Press '[' -> traverses back
      fireEvent.keyDown(window, { key: '[' });
      expect(screen.getByTestId('spatial-inspector-panel')).toBeInTheDocument();
    });

    it('7. toggles operator shortcuts guide modal with key ? and dismisses with Escape', () => {
      render(<SpatialWorld project={mockMultiSeqProject} />);

      expect(screen.queryByTestId('spatial-shortcuts-modal')).not.toBeInTheDocument();

      // Press '?'
      fireEvent.keyDown(window, { key: '?' });
      expect(screen.getByTestId('spatial-shortcuts-modal')).toBeInTheDocument();
      expect(screen.getByText(/OPERATOR COMMAND MATRIX \/\/ SHORTCUTS/i)).toBeInTheDocument();

      // Press 'Escape'
      fireEvent.keyDown(window, { key: 'Escape' });
      expect(screen.queryByTestId('spatial-shortcuts-modal')).not.toBeInTheDocument();
    });

    it('8. suppresses global shortcuts when typing inside form input fields', () => {
      render(
        <div>
          <input data-testid="test-input" type="text" />
          <SpatialWorld project={mockMultiSeqProject} initialCameraState="HUB" />
        </div>
      );

      const input = screen.getByTestId('test-input');
      const container = screen.getByTestId('spatial-world-container');

      // Focus input and fire keydown on the input element
      fireEvent.keyDown(input, { key: '1' });
      // Should NOT switch camera state
      expect(container).toHaveAttribute('data-camera-state', 'HUB');
    });
  });

  describe('2. Cinematic Presentation Mode', () => {
    it('9. allows entering and exiting cinematic mode via HUD button', () => {
      render(<SpatialWorld project={mockMultiSeqProject} />);

      const cinematicBtn = screen.getByTestId('hud-toggle-cinematic-btn');
      fireEvent.click(cinematicBtn);

      // Now in cinematic mode
      expect(screen.getByTestId('spatial-hud-cinematic')).toBeInTheDocument();

      // Exit cinematic mode
      const exitBtn = screen.getByTestId('hud-exit-cinematic-btn');
      fireEvent.click(exitBtn);

      // Returned to standard HUD
      expect(screen.getByTestId('hud-production-telemetry')).toBeInTheDocument();
    });
  });

  describe('3. Procedural Cybernetic Audio Feedback', () => {
    it('10. toggles spatial sound state and updates HUD indicator', () => {
      render(<SpatialWorld project={mockMultiSeqProject} />);

      const audioBtn = screen.getByTestId('hud-toggle-audio-btn');
      expect(audioBtn).toHaveTextContent(/AUDIO OFF/i);

      fireEvent.click(audioBtn);
      expect(audioBtn).toHaveTextContent(/AUDIO ON/i);
      expect(spatialAudio.isEnabled()).toBe(true);

      fireEvent.click(audioBtn);
      expect(audioBtn).toHaveTextContent(/AUDIO OFF/i);
      expect(spatialAudio.isEnabled()).toBe(false);
    });
  });

  describe('4. Multi-Sequence Switching & Corridor Synchronization', () => {
    it('11. renders sequence selector pills and switches active sequence corridor', () => {
      render(<SpatialWorld project={mockMultiSeqProject} />);

      // Sequence selector in HUD
      expect(screen.getByTestId('hud-sequence-selector')).toBeInTheDocument();
      expect(screen.getByTestId('hud-seq-btn-seq-01')).toBeInTheDocument();
      expect(screen.getByTestId('hud-seq-btn-seq-02')).toBeInTheDocument();

      // Initially Sequence 01 shots are present
      expect(screen.getByTestId('spatial-shot-shot-01')).toBeInTheDocument();
      expect(screen.getByTestId('spatial-shot-shot-02')).toBeInTheDocument();

      // Click Sequence 02 button
      fireEvent.click(screen.getByTestId('hud-seq-btn-seq-02'));

      // Sequence 02 shots are now displayed in corridor
      expect(screen.getByTestId('spatial-shot-shot-03')).toBeInTheDocument();
      expect(screen.getByTestId('spatial-shot-shot-04')).toBeInTheDocument();
    });
  });

  describe('5. Direct Production Integration (Studio Bridge & Inspector Assets)', () => {
    it('12. shot inspector provides LOAD IN CREATOR STUDIO action button and asset preview', () => {
      const onOpenStudioWithShot = vi.fn();
      render(
        <SpatialWorld
          project={mockMultiSeqProject}
          onOpenStudioWithShot={onOpenStudioWithShot}
        />
      );

      // Select shot-01 which has an outputAssetUrl
      fireEvent.click(screen.getByTestId('spatial-shot-shot-01'));

      const inspector = screen.getByTestId('spatial-inspector-panel');
      expect(inspector).toBeInTheDocument();

      // Verify asset preview thumbnail is rendered
      expect(screen.getByTestId('spatial-inspector-asset-preview')).toBeInTheDocument();

      // Verify action button exists
      const actionBtn = screen.getByTestId('spatial-inspector-action-btn');
      expect(actionBtn).toHaveTextContent(/LOAD IN CREATOR STUDIO/i);

      fireEvent.click(actionBtn);
      expect(onOpenStudioWithShot).toHaveBeenCalledTimes(1);
      expect(onOpenStudioWithShot).toHaveBeenCalledWith(
        expect.objectContaining({ id: 'shot-01', prompt: expect.stringContaining('obsidian monolith') })
      );
    });

    it('13. blocked shot displays remediation diagnostic in inspector', () => {
      render(<SpatialWorld project={mockMultiSeqProject} />);

      // Switch to Sequence 2
      fireEvent.click(screen.getByTestId('hud-seq-btn-seq-02'));

      // Click blocked shot-04
      fireEvent.click(screen.getByTestId('spatial-shot-shot-04'));

      // Verify remediation message is displayed
      expect(screen.getByTestId('spatial-inspector-remediation')).toBeInTheDocument();
      expect(screen.getByText(/CONTINUITY REMEDIATION:/i)).toBeInTheDocument();
    });

    it('14. seamless roundtrip: loading shot from Spatial into Creator Studio populates parameters', async () => {
      render(<App initialView="spatial" />);

      // Verify spatial world is active
      expect(screen.getByTestId('spatial-world-container')).toBeInTheDocument();

      // Open a shot in the corridor
      const shotBtn = screen.getAllByTestId(/^spatial-shot-shot-/)[0];
      fireEvent.click(shotBtn);

      // Click LOAD IN STUDIO in the inspector or HUD
      const loadBtn = screen.getByTestId('spatial-inspector-action-btn');
      await act(async () => {
        fireEvent.click(loadBtn);
      });

      // App should transition to Creator Studio with active prompt
      expect(screen.getByRole('region', { name: /Creator Controls/i })).toBeInTheDocument();
      const promptInput = screen.getByLabelText(/Prompt/i);
      expect((promptInput as HTMLTextAreaElement).value.length).toBeGreaterThan(0);
    });
  });

  describe('6. Motion Modes & Non-Destructive Observability', () => {
    it('15. allows toggling motion between DAMPED and SNAPPED in the HUD', () => {
      render(<SpatialWorld project={mockMultiSeqProject} />);

      const motionBtn = screen.getByTestId('hud-toggle-motion-btn');
      expect(motionBtn).toBeInTheDocument();

      fireEvent.click(motionBtn);
      // Switches motion preference without throwing
      expect(screen.getByTestId('spatial-world-container')).toBeInTheDocument();
    });

    it('16. maintains non-destructive safety: inspector never exposes uncontrolled mutations', () => {
      const sampleInspectorData: SpatialInspectorData = {
        category: 'SHOT',
        id: 'shot-safety-check',
        title: 'SAFETY AUDIT',
        status: 'READY',
        metrics: [{ label: 'SECURITY', value: 'VERIFIED' }],
        details: ['Audit passed'],
      };

      render(
        <SpatialInspectorPanel
          data={sampleInspectorData}
          onClose={vi.fn()}
        />
      );

      // Verifies no mutate/delete/generate button exists
      expect(screen.queryByRole('button', { name: /generate/i })).not.toBeInTheDocument();
      expect(screen.queryByRole('button', { name: /delete/i })).not.toBeInTheDocument();
      expect(screen.queryByRole('button', { name: /execute/i })).not.toBeInTheDocument();
    });

    it('17. standalone SpatialShortcutsModal renders properly and closes on button click', () => {
      const onClose = vi.fn();
      render(<SpatialShortcutsModal isOpen={true} onClose={onClose} />);

      expect(screen.getByTestId('spatial-shortcuts-modal')).toBeInTheDocument();
      expect(screen.getByText(/OPERATOR COMMAND MATRIX/i)).toBeInTheDocument();

      fireEvent.click(screen.getByTestId('shortcuts-modal-close'));
      expect(onClose).toHaveBeenCalledTimes(1);
    });
  });
});
