import React from 'react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { CommandCore } from '../components/command-core/CommandCore';
import { CommandCoreState } from '../components/command-core/commandCoreTypes';
import { WorkflowOrbit } from '../components/workflow/WorkflowOrbit';
import { ViewportFrame } from '../components/viewport/ViewportFrame';
import { AssetPreview } from '../components/AssetPreview';
import { App } from '../App';
import { CapabilitiesManifest, GenerationJob, HistoryItem } from '../types/creator';

const mockManifest: CapabilitiesManifest = {
  generation_types: [
    { id: 'image', label: 'Image', description: 'Image generation' },
    { id: 'video', label: 'Video', description: 'Video generation' },
    { id: 'image_to_video', label: 'Image → Video', description: 'Image to video' },
  ],
  aspect_ratios: [
    { id: '16:9', label: '16:9 (Landscape)', dimensions: '1344x768' },
    { id: '9:16', label: '9:16 (Portrait)', dimensions: '768x1344' },
    { id: '1:1', label: '1:1 (Square)', dimensions: '1024x1024' },
  ],
  resolutions: [
    { id: '1024x1024', label: '1024 × 1024 (Standard)' },
  ],
  durations: [
    { value: 5, label: '5 seconds' },
  ],
  models: {
    image: [
      {
        id: 'black-forest-labs/FLUX.1.1-pro',
        name: 'FLUX 1.1 Pro',
        provider: 'together',
        default: true,
        cost_tier: 2,
        configured: true,
        start_frame: false,
        end_frame: false,
      },
    ],
    video: [
      {
        id: 'kwaivgi/kling-v1.6-standard',
        name: 'Kling 1.6 Standard',
        provider: 'kling',
        default: true,
        cost_tier: 2,
        configured: true,
        start_frame: true,
        end_frame: false,
      },
    ],
    image_to_video: [
      {
        id: 'kwaivgi/kling-v1.6-standard',
        name: 'Kling 1.6 Standard',
        provider: 'kling',
        default: true,
        cost_tier: 2,
        configured: true,
        start_frame: true,
        end_frame: false,
      },
    ],
  },
};

describe('AryaOS Stage 3: Cinematic Intelligence & Interactive Command-Center Refinement', () => {
  // 1. CommandCore State Rendering & Semantic Status Language
  describe('Stage 3-A & 3-B: CommandCore Semantic State Language', () => {
    const semanticCases: Array<{ state: CommandCoreState; expectedLabel: string; isError: boolean }> = [
      { state: 'idle', expectedLabel: 'STANDBY', isError: false },
      { state: 'configuring', expectedLabel: 'CONFIGURING', isError: false },
      { state: 'ready', expectedLabel: 'READY', isError: false },
      { state: 'generating', expectedLabel: 'SYNTHESIZING', isError: false },
      { state: 'processing', expectedLabel: 'PROCESSING', isError: false },
      { state: 'complete', expectedLabel: 'COMPLETE', isError: false },
      { state: 'error', expectedLabel: 'ERROR', isError: true },
    ];

    semanticCases.forEach(({ state, expectedLabel, isError }) => {
      it(`renders semantic label "${expectedLabel}" for state "${state}" with proper semantic styling`, () => {
        const { container } = render(
          <CommandCore
            state={state}
            generationType="image"
            modelName="FLUX 1.1 Pro"
          />
        );

        // 1. Accessible region and header
        expect(screen.getByRole('region', { name: /AryaOS 3D Command Core/i })).toBeInTheDocument();
        expect(screen.getByText('Spatial Command Core')).toBeInTheDocument();

        // 2. Exact semantic status text
        const stateBadge = screen.getByTestId('core-state-label');
        expect(stateBadge).toHaveTextContent(expectedLabel);

        // 3. Error state strictly reserved for error
        const card = container.querySelector('.command-core-card');
        expect(card).toHaveClass(`core-card-${state}`);

        if (isError) {
          expect(card).toHaveClass('core-card-error');
          expect(container.querySelector('.core-state-error')).toBeInTheDocument();
        } else {
          expect(card).not.toHaveClass('core-card-error');
          expect(container.querySelector('.core-state-error')).not.toBeInTheDocument();
        }
      });
    });

    it('never displays "SYSTEM ALERT" in any normal operational state', () => {
      const normalStates: CommandCoreState[] = ['idle', 'configuring', 'ready', 'generating', 'processing', 'complete'];
      normalStates.forEach((state) => {
        const { unmount } = render(<CommandCore state={state} generationType="image" />);
        expect(screen.queryByText(/SYSTEM ALERT/i)).not.toBeInTheDocument();
        unmount();
      });
    });
  });

  // 2. Workflow Pipeline & Choreography
  describe('Stage 3-C & 3-D: Workflow Pipeline & State Choreography', () => {
    it('communicates INPUT -> PROCESSING -> OUTPUT in standard pipeline', () => {
      render(
        <WorkflowOrbit
          generationType="image"
          hasPrompt={true}
          hasReference={false}
          hasModel={true}
          modelName="FLUX 1.1 Pro"
          isGenerating={false}
          isProcessing={false}
          isCompleted={false}
          isError={false}
        />
      );

      // Verify node flow
      expect(screen.getByText('Prompt')).toBeInTheDocument();
      expect(screen.getByText('Reference')).toBeInTheDocument();
      expect(screen.getByText('AI Model')).toBeInTheDocument();
      expect(screen.getByText('Generate')).toBeInTheDocument();
      expect(screen.getByText('Asset Viewport')).toBeInTheDocument();

      // State label when prompt is entered
      expect(screen.getByText('Pipeline Armed')).toBeInTheDocument();
    });

    it('choreographs active generating state with illuminated node and pulse', () => {
      const { container } = render(
        <WorkflowOrbit
          generationType="image"
          hasPrompt={true}
          hasReference={false}
          hasModel={true}
          modelName="FLUX 1.1 Pro"
          isGenerating={true}
          isProcessing={false}
          isCompleted={false}
          isError={false}
        />
      );

      expect(screen.getByText('Dispatching Task')).toBeInTheDocument();
      const generateNode = container.querySelector('[data-node-id="generate"]');
      expect(generateNode).toHaveClass('workflow-node-active');

      // Downstream node remains pending/subdued
      const viewportNode = container.querySelector('[data-node-id="preview"]');
      expect(viewportNode).toHaveClass('workflow-node-pending');
    });

    it('synchronizes completion state resolving to output node', () => {
      const { container } = render(
        <WorkflowOrbit
          generationType="image"
          hasPrompt={true}
          hasReference={false}
          hasModel={true}
          modelName="FLUX 1.1 Pro"
          isGenerating={false}
          isProcessing={false}
          isCompleted={true}
          isError={false}
        />
      );

      expect(screen.getByText('Asset Produced')).toBeInTheDocument();
      const viewportNode = container.querySelector('[data-node-id="preview"]');
      expect(viewportNode).toHaveClass('workflow-node-completed');
    });

    it('isolates error state to failed stage without turning upstream nodes red', () => {
      const { container } = render(
        <WorkflowOrbit
          generationType="image"
          hasPrompt={true}
          hasReference={true}
          hasModel={true}
          modelName="FLUX 1.1 Pro"
          isGenerating={false}
          isProcessing={false}
          isCompleted={false}
          isError={true}
        />
      );

      // Stage header indicates error
      expect(screen.getByText('Execution Error')).toBeInTheDocument();

      // Failed stage is marked error
      const generateNode = container.querySelector('[data-node-id="generate"]');
      expect(generateNode).toHaveClass('workflow-node-error');

      // Upstream nodes remain completed and NOT error
      const promptNode = container.querySelector('[data-node-id="prompt"]');
      expect(promptNode).toHaveClass('workflow-node-completed');
      expect(promptNode).not.toHaveClass('workflow-node-error');

      const modelNode = container.querySelector('[data-node-id="model"]');
      expect(modelNode).toHaveClass('workflow-node-completed');
      expect(modelNode).not.toHaveClass('workflow-node-error');

      // Downstream node remains quiet/pending
      const viewportNode = container.querySelector('[data-node-id="preview"]');
      expect(viewportNode).toHaveClass('workflow-node-pending');
      expect(viewportNode).not.toHaveClass('workflow-node-error');
    });
  });

  // 3. Creative Viewport & Empty State
  describe('Stage 3-E & 3-F: Creative Viewport & Empty State', () => {
    it('renders sophisticated empty state hierarchy when no asset is loaded', () => {
      render(
        <AssetPreview
          generationType="image"
          currentJob={null}
        />
      );

      expect(screen.getByText('CREATIVE VIEWPORT')).toBeInTheDocument();
      expect(screen.getByText('READY FOR SYNTHESIS')).toBeInTheDocument();
      expect(
        screen.getByText(/Select your generation parameters and submit a prompt to begin/i)
      ).toBeInTheDocument();
    });

    it('renders high-end cinema framing with technical monitor tag and corner reticles', () => {
      render(
        <ViewportFrame zoomMode="fit" isFullscreen={false} hasMedia={false}>
          <div data-testid="viewport-content">Test</div>
        </ViewportFrame>
      );

      expect(screen.getByText('MONITOR // REC.709')).toBeInTheDocument();
      expect(screen.getByTestId('viewport-content')).toBeInTheDocument();
    });

    it('hides center crosshairs when media exists to ensure MEDIA > UI', () => {
      const { rerender } = render(
        <AssetPreview
          generationType="image"
          previewUrl="https://cdn.example.com/asset.png"
        />
      );

      expect(screen.getByTestId('image-preview')).toHaveAttribute('src', 'https://cdn.example.com/asset.png');
      expect(screen.queryByText('CREATIVE VIEWPORT')).not.toBeInTheDocument();
    });
  });

  // 4. End-to-End Creator Studio State Integration
  describe('Stage 3 Integration: Real Application State Synchronization', () => {
    beforeEach(() => {
      vi.resetAllMocks();
      globalThis.fetch = vi.fn().mockImplementation((url: string) => {
        const urlStr = url.toString();
        if (urlStr.includes('/health')) {
          return Promise.resolve({ ok: true, json: () => Promise.resolve({ status: 'healthy', checks: {} }) });
        }
        if (urlStr.includes('/creator/capabilities')) {
          return Promise.resolve({ ok: true, json: () => Promise.resolve(mockManifest) });
        }
        if (urlStr.includes('/creator/history')) {
          return Promise.resolve({ ok: true, json: () => Promise.resolve([]) });
        }
        return Promise.reject(new Error(`Unhandled fetch: ${urlStr}`));
      });
    });

    it('initializes in STANDBY state without any false red alerts', async () => {
      render(<App />);

      await waitFor(() => {
        expect(screen.getByText('STANDBY')).toBeInTheDocument();
      });

      // Confirm no error alert badge or red HUD appears
      expect(screen.queryByText(/SYSTEM ALERT/i)).not.toBeInTheDocument();
      expect(screen.queryByText(/ERROR/i)).not.toBeInTheDocument();
    });

    it('transitions from STANDBY to READY when prompt is provided', async () => {
      render(<App />);

      await waitFor(() => {
        expect(screen.getByLabelText(/Prompt/i)).toBeInTheDocument();
      });

      expect(screen.getByText('STANDBY')).toBeInTheDocument();

      const promptInput = screen.getByLabelText(/Prompt/i);
      fireEvent.change(promptInput, { target: { value: 'A dark cinematic command center' } });

      await waitFor(() => {
        expect(screen.getByText('READY')).toBeInTheDocument();
      });
    });
  });
});
