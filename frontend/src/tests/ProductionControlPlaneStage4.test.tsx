import React from 'react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { App } from '../App';
import { CapabilitiesManifest, GenerationJob, HistoryItem } from '../types/creator';
import { WorkflowOrbit } from '../components/workflow/WorkflowOrbit';
import { ReferenceUpload } from '../components/ReferenceUpload';
import { StartEndFrameControls } from '../components/StartEndFrameControls';

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
    { id: '1280x720', label: '1280 × 720 (HD)' },
  ],
  durations: [
    { value: 5, label: '5 seconds' },
    { value: 10, label: '10 seconds' },
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
        name: 'Kling 1.6 Standard (Motion)',
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

const mockInitialHistory: HistoryItem[] = [
  {
    job_id: 'hist-prior-1',
    workflow_run_id: 'run-prior-1',
    generation_type: 'image',
    prompt: 'A prior obsidian command console render',
    model: 'FLUX 1.1 Pro',
    provider: 'together',
    aspect_ratio: '16:9',
    status: 'completed',
    asset_url: 'https://cdn.example.com/obsidian_render.png',
    total_cost_usd: 0.04,
    created_at: new Date().toISOString(),
  },
];

describe('AryaOS Stage 4: Production Control Plane & Generation Workflow Integration', () => {
  let submittedPayloads: any[] = [];
  let pollCount = 0;
  let simulatedJobStatus: GenerationJob = {
    job_id: 'job-stage4-001',
    workflow_run_id: 'wf-stage4-001',
    status: 'in_progress',
    current_stage: 'image_generation',
    generation_type: 'image',
    prompt: 'Deep obsidian cinematic visual',
    model: 'black-forest-labs/FLUX.1.1-pro',
    provider: 'together',
    aspect_ratio: '16:9',
    total_cost_usd: 0.045,
    output: {},
  };

  beforeEach(() => {
    vi.resetAllMocks();
    submittedPayloads = [];
    pollCount = 0;
    simulatedJobStatus = {
      job_id: 'job-stage4-001',
      workflow_run_id: 'wf-stage4-001',
      status: 'in_progress',
      current_stage: 'image_generation',
      generation_type: 'image',
      prompt: 'Deep obsidian cinematic visual',
      model: 'black-forest-labs/FLUX.1.1-pro',
      provider: 'together',
      aspect_ratio: '16:9',
      total_cost_usd: 0.045,
      output: {},
    };

    globalThis.fetch = vi.fn().mockImplementation((url: string, init?: RequestInit) => {
      const urlStr = url.toString();

      if (urlStr.includes('/health')) {
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve({ status: 'healthy', checks: { postgres: 'ok', redis: 'ok' } }),
        });
      }

      if (urlStr.includes('/creator/capabilities')) {
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve(mockManifest),
        });
      }

      if (urlStr.includes('/creator/history')) {
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve(mockInitialHistory),
        });
      }

      if (urlStr.includes('/creator/upload')) {
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve({ url: 'https://cdn.example.com/uploaded_ref.png' }),
        });
      }

      if (urlStr.includes('/creator/generate')) {
        const body = JSON.parse(init?.body as string || '{}');
        submittedPayloads.push(body);
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve(simulatedJobStatus),
        });
      }

      if (urlStr.includes('/creator/jobs/')) {
        pollCount++;
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve(simulatedJobStatus),
        });
      }

      return Promise.reject(new Error(`Unhandled fetch: ${urlStr}`));
    });
  });

  // 1 & 2. State Progression: STANDBY -> READY
  it('verifies initial STANDBY state and clean transition to READY upon prompt input', async () => {
    render(<App />);

    await waitFor(() => {
      expect(screen.getByText('STANDBY')).toBeInTheDocument();
      expect(screen.getByLabelText(/Prompt/i)).toBeInTheDocument();
    });

    const promptInput = screen.getByLabelText(/Prompt/i);
    fireEvent.change(promptInput, { target: { value: 'Atmospheric command center exterior' } });

    await waitFor(() => {
      expect(screen.getByText('READY')).toBeInTheDocument();
    });
  });

  // 3. Validation rejection on empty prompt
  it('blocks execution and renders visible validation error when prompt is empty', async () => {
    render(<App />);

    await waitFor(() => {
      expect(screen.getByTestId('generate-button')).toBeInTheDocument();
    });

    const generateBtn = screen.getByTestId('generate-button');
    fireEvent.click(generateBtn);

    await waitFor(() => {
      expect(screen.getByText('Please enter a prompt describing your desired generation.')).toBeInTheDocument();
    });

    expect(submittedPayloads.length).toBe(0);
  });

  // 4. Image-to-video mode validation: requires start frame
  it('blocks image-to-video execution if start frame is missing and renders directive', async () => {
    render(<App />);

    await waitFor(() => {
      expect(screen.getByRole('tab', { name: /Image → Video/i })).toBeInTheDocument();
      expect(screen.getByTestId('generate-button')).toBeInTheDocument();
    });

    fireEvent.click(screen.getByRole('tab', { name: /Image → Video/i }));

    const promptInput = screen.getByLabelText(/Prompt/i);
    fireEvent.change(promptInput, { target: { value: 'Slow cinematic dolly forward' } });

    // Without start frame, state should be CONFIGURING
    await waitFor(() => {
      expect(screen.getByText('CONFIGURING')).toBeInTheDocument();
    });

    const generateBtn = screen.getByTestId('generate-button');
    fireEvent.click(generateBtn);

    await waitFor(() => {
      expect(screen.getByText('Image → Video generation requires a start frame image.')).toBeInTheDocument();
    });

    expect(submittedPayloads.length).toBe(0);
  });

  // 5 & 6. Job submission payload accuracy and SYNTHESIZING state
  it('submits valid job with accurate payload and enters SYNTHESIZING lifecycle', async () => {
    render(<App />);

    await waitFor(() => {
      expect(screen.getByLabelText(/Prompt/i)).toBeInTheDocument();
      expect(screen.getByTestId('generate-button')).toBeInTheDocument();
    });

    const promptInput = screen.getByLabelText(/Prompt/i);
    fireEvent.change(promptInput, { target: { value: 'Hyperdetailed command deck' } });

    const generateBtn = screen.getByTestId('generate-button');
    fireEvent.click(generateBtn);

    await waitFor(() => {
      expect(submittedPayloads.length).toBe(1);
    });

    expect(submittedPayloads[0]).toMatchObject({
      generation_type: 'image',
      prompt: 'Hyperdetailed command deck',
      model: 'black-forest-labs/FLUX.1.1-pro',
      provider: 'together',
      aspect_ratio: '16:9',
      resolution: '1024x1024',
    });
  });

  // 7 & 8. Polling progression into PROCESSING and telemetry reflection
  it('reflects PROCESSING state and telemetry when active stage is executing', async () => {
    render(<App />);

    await waitFor(() => {
      expect(screen.getByLabelText(/Prompt/i)).toBeInTheDocument();
      expect(screen.getByTestId('generate-button')).toBeInTheDocument();
    });

    fireEvent.change(screen.getByLabelText(/Prompt/i), { target: { value: 'Anodized steel console' } });
    fireEvent.click(screen.getByTestId('generate-button'));

    await waitFor(() => {
      expect(screen.getByText('PROCESSING')).toBeInTheDocument();
      expect(screen.getByText('Job Status')).toBeInTheDocument();
      expect(screen.getByText('Executing Image Generation Agent')).toBeInTheDocument();
    });
  });

  // 9 & 10. Completed state and asset rendering in Viewport
  it('transitions to COMPLETE and renders generated image asset in Creative Viewport', async () => {
    simulatedJobStatus = {
      job_id: 'job-stage4-done',
      workflow_run_id: 'wf-stage4-done',
      status: 'completed',
      current_stage: 'completed',
      generation_type: 'image',
      prompt: 'Cinematic deep space console',
      model: 'black-forest-labs/FLUX.1.1-pro',
      provider: 'together',
      aspect_ratio: '16:9',
      total_cost_usd: 0.045,
      output: {
        asset_url: 'https://cdn.example.com/result_asset.png',
        storage_path: 'https://cdn.example.com/result_asset.png',
      },
    };

    render(<App />);

    await waitFor(() => {
      expect(screen.getByLabelText(/Prompt/i)).toBeInTheDocument();
      expect(screen.getByTestId('generate-button')).toBeInTheDocument();
    });

    fireEvent.change(screen.getByLabelText(/Prompt/i), { target: { value: 'Cinematic deep space console' } });
    fireEvent.click(screen.getByTestId('generate-button'));

    await waitFor(() => {
      expect(screen.getByText('COMPLETE')).toBeInTheDocument();
      expect(screen.getByTestId('image-preview')).toHaveAttribute('src', 'https://cdn.example.com/result_asset.png');
    });
  });

  // 10-B. Video asset rendering
  it('renders video element with controls when video generation completes', async () => {
    simulatedJobStatus = {
      job_id: 'job-stage4-vid',
      workflow_run_id: 'wf-stage4-vid',
      status: 'completed',
      current_stage: 'completed',
      generation_type: 'video',
      prompt: 'Cinematic camera pan across workstation',
      model: 'kwaivgi/kling-v1.6-standard',
      provider: 'kling',
      aspect_ratio: '16:9',
      total_cost_usd: 0.12,
      output: {
        asset_url: 'https://cdn.example.com/cinematic_pan.mp4',
        storage_path: 'https://cdn.example.com/cinematic_pan.mp4',
      },
    };

    render(<App />);

    await waitFor(() => {
      expect(screen.getByRole('tab', { name: /^Video$/i })).toBeInTheDocument();
      expect(screen.getByTestId('generate-button')).toBeInTheDocument();
    });

    fireEvent.click(screen.getByRole('tab', { name: /^Video$/i }));
    fireEvent.change(screen.getByLabelText(/Prompt/i), { target: { value: 'Cinematic camera pan across workstation' } });
    fireEvent.click(screen.getByTestId('generate-button'));

    await waitFor(() => {
      expect(screen.getByTestId('video-player')).toHaveAttribute('src', 'https://cdn.example.com/cinematic_pan.mp4');
    });
  });

  // 11. Viewport controls (zoom, fullscreen, download)
  it('provides operational viewport controls (zoom, fullscreen, download)', async () => {
    simulatedJobStatus = {
      job_id: 'job-stage4-ctl',
      workflow_run_id: 'wf-stage4-ctl',
      status: 'completed',
      current_stage: 'completed',
      generation_type: 'image',
      prompt: 'Precision control console',
      model: 'black-forest-labs/FLUX.1.1-pro',
      provider: 'together',
      aspect_ratio: '16:9',
      total_cost_usd: 0.045,
      output: {
        asset_url: 'https://cdn.example.com/ctl_asset.png',
        storage_path: 'https://cdn.example.com/ctl_asset.png',
      },
    };

    render(<App />);

    await waitFor(() => {
      expect(screen.getByLabelText(/Prompt/i)).toBeInTheDocument();
      expect(screen.getByTestId('generate-button')).toBeInTheDocument();
    });

    fireEvent.change(screen.getByLabelText(/Prompt/i), { target: { value: 'Precision control console' } });
    fireEvent.click(screen.getByTestId('generate-button'));

    await waitFor(() => {
      expect(screen.getByTestId('btn-toggle-zoom')).toBeInTheDocument();
      expect(screen.getByTestId('btn-toggle-fullscreen')).toBeInTheDocument();
      expect(screen.getByTestId('btn-download-asset')).toBeInTheDocument();
    });

    // Test zoom toggle
    const zoomBtn = screen.getByTestId('btn-toggle-zoom');
    expect(screen.getByText('100%')).toBeInTheDocument();
    fireEvent.click(zoomBtn);
    expect(screen.getByText('Fit')).toBeInTheDocument();
    fireEvent.click(zoomBtn);
    expect(screen.getByText('100%')).toBeInTheDocument();
  });

  // 12 & 13. Failure handling, localized error, and retry preserving parameters
  it('handles backend execution failure gracefully with retry preserving parameters', async () => {
    let callIndex = 0;
    globalThis.fetch = vi.fn().mockImplementation((url: string, init?: RequestInit) => {
      const urlStr = url.toString();
      if (urlStr.includes('/health')) return Promise.resolve({ ok: true, json: () => Promise.resolve({ status: 'healthy', checks: {} }) });
      if (urlStr.includes('/creator/capabilities')) return Promise.resolve({ ok: true, json: () => Promise.resolve(mockManifest) });
      if (urlStr.includes('/creator/history')) return Promise.resolve({ ok: true, json: () => Promise.resolve([]) });

      if (urlStr.includes('/creator/generate')) {
        callIndex++;
        const body = JSON.parse(init?.body as string || '{}');
        submittedPayloads.push(body);

        if (callIndex === 1) {
          // First attempt fails
          return Promise.resolve({
            ok: true,
            json: () => Promise.resolve({
              job_id: 'job-stage4-fail',
              workflow_run_id: 'wf-fail',
              status: 'failed',
              failure_reason: 'GPU allocation timeout on node cluster',
              generation_type: body.generation_type,
              prompt: body.prompt,
              model: body.model,
            }),
          });
        }

        // Retry succeeds
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve({
            job_id: 'job-stage4-retry-success',
            workflow_run_id: 'wf-success',
            status: 'completed',
            current_stage: 'completed',
            generation_type: body.generation_type,
            prompt: body.prompt,
            model: body.model,
            output: { asset_url: 'https://cdn.example.com/retry_recovered.png' },
          }),
        });
      }

      if (urlStr.includes('/creator/jobs/')) {
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve(callIndex === 1 ? {
            job_id: 'job-stage4-fail',
            workflow_run_id: 'wf-fail',
            status: 'failed',
            failure_reason: 'GPU allocation timeout on node cluster',
            generation_type: 'image',
            prompt: 'Resilient node execution prompt',
            model: 'black-forest-labs/FLUX.1.1-pro',
            output: {},
          } : {
            job_id: 'job-stage4-retry-success',
            workflow_run_id: 'wf-success',
            status: 'completed',
            current_stage: 'completed',
            generation_type: 'image',
            prompt: 'Resilient node execution prompt',
            model: 'black-forest-labs/FLUX.1.1-pro',
            output: { asset_url: 'https://cdn.example.com/retry_recovered.png' },
          }),
        });
      }

      return Promise.reject(new Error(`Unhandled fetch: ${urlStr}`));
    });

    render(<App />);

    await waitFor(() => {
      expect(screen.getByLabelText(/Prompt/i)).toBeInTheDocument();
      expect(screen.getByTestId('generate-button')).toBeInTheDocument();
    });

    const promptInput = screen.getByLabelText(/Prompt/i);
    fireEvent.change(promptInput, { target: { value: 'Resilient node execution prompt' } });
    fireEvent.click(screen.getByTestId('generate-button'));

    // Verify failure UI
    await waitFor(() => {
      expect(screen.getByText('ERROR')).toBeInTheDocument();
      expect(screen.getByText('GPU allocation timeout on node cluster')).toBeInTheDocument();
      expect(screen.getByTestId('job-retry-button')).toBeInTheDocument();
    });

    // Click retry
    fireEvent.click(screen.getByTestId('job-retry-button'));

    // Verify retry submitted again with exact same prompt without losing user configuration
    await waitFor(() => {
      expect(submittedPayloads.length).toBe(2);
      expect(submittedPayloads[1].prompt).toBe('Resilient node execution prompt');
      expect(screen.getByText('COMPLETE')).toBeInTheDocument();
    });
  });

  // 14. Error isolation: upstream pipeline nodes remain functional during execution error
  it('isolates error to execution node while upstream nodes remain complete in WorkflowOrbit', () => {
    const { container } = render(
      <WorkflowOrbit
        generationType="image"
        hasPrompt={true}
        hasReference={false}
        hasModel={true}
        modelName="FLUX 1.1 Pro"
        isGenerating={false}
        isProcessing={false}
        isCompleted={false}
        isError={true}
      />
    );

    const generateNode = container.querySelector('[data-node-id="generate"]');
    expect(generateNode).toHaveClass('workflow-node-error');

    const promptNode = container.querySelector('[data-node-id="prompt"]');
    expect(promptNode).toHaveClass('workflow-node-completed');
    expect(promptNode).not.toHaveClass('workflow-node-error');

    const modelNode = container.querySelector('[data-node-id="model"]');
    expect(modelNode).toHaveClass('workflow-node-completed');
    expect(modelNode).not.toHaveClass('workflow-node-error');
  });

  // 15, 16 & 17. Reference image upload, replacement, and removal
  describe('Reference Asset Lifecycle', () => {
    it('supports reference upload, in-place replacement, and removal', async () => {
      let currentRefUrl: string | undefined = undefined;
      const handleImageChange = vi.fn((url) => {
        currentRefUrl = url;
      });

      const { rerender } = render(
        <ReferenceUpload
          label="Reference Image (Optional)"
          sublabel="Provide a reference image"
          imageUrl={currentRefUrl}
          onImageChange={handleImageChange}
        />
      );

      // Upload simulated file
      const file = new File(['mock content'], 'test_ref.png', { type: 'image/png' });
      const fileInput = screen.getByTestId('reference-file-input');
      fireEvent.change(fileInput, { target: { files: [file] } });

      await waitFor(() => {
        expect(handleImageChange).toHaveBeenCalledWith('https://cdn.example.com/uploaded_ref.png');
      });

      // Rerender with preview url
      rerender(
        <ReferenceUpload
          label="Reference Image (Optional)"
          sublabel="Provide a reference image"
          imageUrl="https://cdn.example.com/uploaded_ref.png"
          onImageChange={handleImageChange}
        />
      );

      expect(screen.getByTestId('reference-preview-img')).toBeInTheDocument();
      expect(screen.getByTestId('replace-reference-btn')).toBeInTheDocument();
      expect(screen.getByTestId('remove-reference-btn')).toBeInTheDocument();

      // Remove reference
      fireEvent.click(screen.getByTestId('remove-reference-btn'));
      expect(handleImageChange).toHaveBeenLastCalledWith(undefined);
    });
  });

  // 18. First/Last frame backend capability display
  it('correctly indicates start frame support and reports end frame limitation based on model manifest', () => {
    render(
      <StartEndFrameControls
        generationType="video"
        selectedModelObj={mockManifest.models.video[0]}
        startFrameUrl=""
        onStartFrameChange={vi.fn()}
        endFrameUrl=""
        onEndFrameChange={vi.fn()}
      />
    );

    expect(screen.getByText('Start Frame (First Frame)')).toBeInTheDocument();
    expect(screen.getByTestId('end-frame-unsupported')).toBeInTheDocument();
    expect(screen.getByTestId('end-frame-unsupported')).toHaveTextContent(
      /does not support end-frame anchoring in the backend/i
    );
  });

  // 19. Generation mode switching updates configurations and keyframe visibility
  it('switches generation modes cleanly and exposes respective synthesis options', async () => {
    render(<App />);

    await waitFor(() => {
      expect(screen.getByRole('tab', { name: /^Image$/i })).toBeInTheDocument();
      expect(screen.getByTestId('generate-button')).toBeInTheDocument();
    });

    // Image mode shows Reference Input
    expect(screen.getByText('03 // REFERENCE INPUT')).toBeInTheDocument();

    // Switch to Video mode
    fireEvent.click(screen.getByRole('tab', { name: /^Video$/i }));

    await waitFor(() => {
      expect(screen.getByText('04 // KEYFRAME DIRECTIVES')).toBeInTheDocument();
    });

    // Switch to Image -> Video mode
    fireEvent.click(screen.getByRole('tab', { name: /Image → Video/i }));

    await waitFor(() => {
      expect(screen.getByText('04 // KEYFRAME DIRECTIVES')).toBeInTheDocument();
    });
  });

  // 20. History panel selection loads previous asset into viewport
  it('loads historical asset into Creative Viewport when selected from HistoryPanel', async () => {
    render(<App />);

    await waitFor(() => {
      expect(screen.getByText('A prior obsidian command console render')).toBeInTheDocument();
    });

    // Click on history item card
    fireEvent.click(screen.getByText('A prior obsidian command console render'));

    await waitFor(() => {
      expect(screen.getByTestId('image-preview')).toHaveAttribute(
        'src',
        'https://cdn.example.com/obsidian_render.png'
      );
    });
  });
});
