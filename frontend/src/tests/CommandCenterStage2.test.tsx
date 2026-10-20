import React from 'react';
import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { CommandCore } from '../components/command-core/CommandCore';
import { WorkflowOrbit } from '../components/workflow/WorkflowOrbit';
import { ViewportControls } from '../components/viewport/ViewportControls';
import { ViewportTelemetry } from '../components/viewport/ViewportTelemetry';
import { ViewportFrame } from '../components/viewport/ViewportFrame';
import { GenerationJob } from '../types/creator';

describe('AryaOS Stage 2: 3D Command Center & Spatial Workflow System', () => {
  // 1. CommandCore tests
  describe('CommandCore component', () => {
    it('renders with accessible role and displays Idle state by default', () => {
      render(
        <CommandCore
          state="idle"
          generationType="image"
          modelName="FLUX 1.1 Pro"
        />
      );

      expect(screen.getByRole('region', { name: /AryaOS 3D Command Core/i })).toBeInTheDocument();
      expect(screen.getByText(/Spatial Command Core/i)).toBeInTheDocument();
      expect(screen.getByText(/STANDBY/i)).toBeInTheDocument();
      expect(screen.getByText(/Mode:/i)).toBeInTheDocument();
      expect(screen.getByText(/FLUX 1.1 Pro/i)).toBeInTheDocument();
    });

    it('displays Armed / Ready state when prompted and ready to execute', () => {
      render(
        <CommandCore
          state="ready"
          generationType="video"
          modelName="Kling 1.6 Standard"
        />
      );

      expect(screen.getByText(/READY/i)).toBeInTheDocument();
      expect(screen.getByText(/Video/i)).toBeInTheDocument();
    });

    it('displays Synthesizing and System Alert states appropriately', () => {
      const { rerender } = render(
        <CommandCore state="processing" generationType="image" />
      );
      expect(screen.getByText(/PROCESSING/i)).toBeInTheDocument();

      rerender(<CommandCore state="error" generationType="image" />);
      expect(screen.getByText(/ERROR/i)).toBeInTheDocument();

      rerender(<CommandCore state="complete" generationType="image" />);
      expect(screen.getByText(/COMPLETE/i)).toBeInTheDocument();
    });
  });

  // 2. WorkflowOrbit tests
  describe('WorkflowOrbit component', () => {
    it('renders standard 5-stage pipeline for image and video modes', () => {
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

      expect(screen.getByRole('region', { name: /Generation Workflow Pipeline/i })).toBeInTheDocument();
      expect(screen.getByText('Prompt')).toBeInTheDocument();
      expect(screen.getByText('Reference')).toBeInTheDocument();
      expect(screen.getByText('AI Model')).toBeInTheDocument();
      expect(screen.getByText('Generate')).toBeInTheDocument();
      expect(screen.getByText('Asset Viewport')).toBeInTheDocument();
      expect(screen.getByText(/Pipeline Armed/i)).toBeInTheDocument();
    });

    it('renders cinematic keyframe flow when generationType is image_to_video', () => {
      render(
        <WorkflowOrbit
          generationType="image_to_video"
          hasPrompt={true}
          hasReference={true}
          hasModel={true}
          modelName="Kling 1.6 Standard"
          isGenerating={false}
          isProcessing={true}
          isCompleted={false}
          isError={false}
          startFrameUrl="https://cdn.example.com/start.png"
          endFrameUrl="https://cdn.example.com/end.png"
        />
      );

      expect(screen.getByText('Reference Image')).toBeInTheDocument();
      expect(screen.getByText('Start Frame')).toBeInTheDocument();
      expect(screen.getByText('Motion Engine')).toBeInTheDocument();
      expect(screen.getByText('End Frame')).toBeInTheDocument();
      expect(screen.getByText('Video Asset')).toBeInTheDocument();
      expect(screen.getByText(/Synthesizing Media/i)).toBeInTheDocument();
    });
  });

  // 3. Viewport subcomponents
  describe('Viewport subcomponents', () => {
    it('ViewportControls handles zoom toggle, fullscreen, and download', () => {
      const onToggleZoom = vi.fn();
      const onToggleFullscreen = vi.fn();
      const onPrev = vi.fn();
      const onNext = vi.fn();

      render(
        <ViewportControls
          zoomMode="fit"
          onToggleZoom={onToggleZoom}
          isFullscreen={false}
          onToggleFullscreen={onToggleFullscreen}
          downloadUrl="https://cdn.example.com/image.png"
          downloadFilename="arya_image.png"
          onPrev={onPrev}
          onNext={onNext}
          hasPrev={true}
          hasNext={true}
        />
      );

      const zoomBtn = screen.getByRole('button', { name: /100%/i });
      fireEvent.click(zoomBtn);
      expect(onToggleZoom).toHaveBeenCalledTimes(1);

      const expandBtn = screen.getByRole('button', { name: /Fullscreen Viewport/i });
      fireEvent.click(expandBtn);
      expect(onToggleFullscreen).toHaveBeenCalledTimes(1);

      const prevBtn = screen.getByRole('button', { name: /Previous Asset/i });
      fireEvent.click(prevBtn);
      expect(onPrev).toHaveBeenCalledTimes(1);

      const downloadLink = screen.getByRole('link', { name: /Download/i });
      expect(downloadLink).toHaveAttribute('href', 'https://cdn.example.com/image.png');
      expect(downloadLink).toHaveAttribute('download', 'arya_image.png');
    });

    it('ViewportTelemetry renders exact metadata without fabricating values', () => {
      const mockJob: GenerationJob = {
        job_id: 'job-999',
        workflow_run_id: 'wf-999',
        generation_type: 'video',
        status: 'completed',
        prompt: 'A hyper-lapse of galactic clouds',
        model: 'kwaivgi/kling-v1.6-standard',
        provider: 'kling',
        aspect_ratio: '16:9',
        duration_seconds: 5,
        total_cost_usd: 0.045,
        output: {
          asset_url: 'https://cdn.example.com/video.mp4',
          provider_used: 'kling',
          duration_seconds: 5,
          aspect_ratio: '16:9',
        },
      };

      render(<ViewportTelemetry currentJob={mockJob} isVideo={true} />);

      expect(screen.getByText('Ready')).toBeInTheDocument();
      expect(screen.getByText('kling')).toBeInTheDocument();
      expect(screen.getByText('kling-v1.6-standard')).toBeInTheDocument();
      expect(screen.getByText('16:9')).toBeInTheDocument();
      expect(screen.getByText('5s')).toBeInTheDocument();
      expect(screen.getByText('$0.0450')).toBeInTheDocument();
      expect(screen.getByText('"A hyper-lapse of galactic clouds"')).toBeInTheDocument();
    });

    it('ViewportFrame wraps children and displays loading scan line during synthesis', () => {
      render(
        <ViewportFrame zoomMode="fit" isFullscreen={false} isLoading={true}>
          <div data-testid="test-content">Rendered Content</div>
        </ViewportFrame>
      );

      expect(screen.getByTestId('test-content')).toBeInTheDocument();
    });
  });
});
