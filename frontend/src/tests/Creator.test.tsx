import React from 'react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { App } from '../App';
import { CapabilitiesManifest, HistoryItem } from '../types/creator';

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
    { id: '4:5', label: '4:5 (Social Feed)', dimensions: '864x1080' },
  ],
  resolutions: [
    { id: '1024x1024', label: '1024 × 1024 (Standard)' },
    { id: '1344x768', label: '1344 × 768 (Landscape HD)' },
  ],
  durations: [
    { value: 5, label: '5 seconds' },
    { value: 10, label: '10 seconds' },
  ],
  models: {
    image: [
      {
        id: 'black-forest-labs/FLUX.1.1-pro',
        name: 'FLUX 1.1 Pro (Together AI)',
        provider: 'together',
        default: true,
        cost_tier: 2,
        configured: true,
        start_frame: false,
        end_frame: false,
      },
      {
        id: 'fal-ai/flux-pro/v1.1',
        name: 'FLUX 1.1 Pro (fal.ai)',
        provider: 'fal',
        default: false,
        cost_tier: 2,
        configured: true,
        start_frame: false,
        end_frame: false,
      },
    ],
    video: [
      {
        id: 'kwaivgi/kling-v1.6-standard',
        name: 'Kling 1.6 Standard (Hybrid)',
        provider: 'kling',
        default: true,
        cost_tier: 2,
        configured: true,
        start_frame: true,
        end_frame: false, // strictly false in V1
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

const mockHistory: HistoryItem[] = [
  {
    job_id: 'hist-001',
    workflow_run_id: 'hist-001',
    generation_type: 'image',
    prompt: 'A majestic mountain landscape at sunrise',
    model: 'FLUX 1.1 Pro',
    provider: 'together',
    aspect_ratio: '16:9',
    status: 'completed',
    asset_url: 'https://cdn.example.com/mountain.png',
    total_cost_usd: 0.04,
    created_at: new Date().toISOString(),
  },
];

describe('AryaOS Creator Mode Frontend', () => {
  beforeEach(() => {
    vi.resetAllMocks();

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
          json: () => Promise.resolve(mockHistory),
        });
      }

      if (urlStr.includes('/creator/generate')) {
        const body = JSON.parse(init?.body as string || '{}');
        return Promise.resolve({
          ok: true,
          json: () =>
            Promise.resolve({
              job_id: 'job-test-999',
              workflow_run_id: 'job-test-999',
              status: 'in_progress',
              current_stage: body.generation_type === 'image' ? 'image_generation' : 'video_generation',
              generation_type: body.generation_type,
              prompt: body.prompt,
              model: body.model,
              aspect_ratio: body.aspect_ratio,
              total_cost_usd: 0.04,
              output: {},
            }),
        });
      }

      if (urlStr.includes('/creator/jobs/job-test-999')) {
        return Promise.resolve({
          ok: true,
          json: () =>
            Promise.resolve({
              job_id: 'job-test-999',
              workflow_run_id: 'job-test-999',
              status: 'completed',
              current_stage: 'completed',
              generation_type: 'image',
              prompt: 'A test prompt',
              model: 'black-forest-labs/FLUX.1.1-pro',
              aspect_ratio: '16:9',
              total_cost_usd: 0.04,
              output: {
                asset_url: 'https://cdn.example.com/test_result.png',
                storage_path: 'https://cdn.example.com/test_result.png',
                provider_used: 'together',
                duration_seconds: 4.2,
                aspect_ratio: '16:9',
              },
            }),
        });
      }

      return Promise.reject(new Error(`Unhandled fetch: ${urlStr}`));
    });
  });

  // 1. Creator page renders
  it('1. renders the Creator page with AryaOS header and controls', async () => {
    render(<App />);
    expect(screen.getByText('AryaOS')).toBeInTheDocument();
    expect(screen.getByText('V1 CREATOR')).toBeInTheDocument();
    await waitFor(() => {
      expect(screen.getByRole('tab', { name: /^Image$/i })).toBeInTheDocument();
      expect(screen.getByLabelText(/Prompt/i)).toBeInTheDocument();
      expect(screen.getByRole('button', { name: /Generate Image/i })).toBeInTheDocument();
    });
  });

  // 2. Generation type selection works
  it('2. generation type selection switches tabs correctly', async () => {
    render(<App />);
    await waitFor(() => expect(screen.getByRole('tab', { name: /^Video$/i })).toBeInTheDocument());

    const videoTab = screen.getByRole('tab', { name: /^Video$/i });
    fireEvent.click(videoTab);
    expect(videoTab).toHaveClass('active');
    expect(screen.getByRole('button', { name: /Generate Video/i })).toBeInTheDocument();

    const i2vTab = screen.getByRole('tab', { name: /Image → Video/i });
    fireEvent.click(i2vTab);
    expect(i2vTab).toHaveClass('active');
    expect(screen.getByRole('button', { name: /Animate Image → Video/i })).toBeInTheDocument();
  });

  // 3. Prompt validation works
  it('3. validates that prompt cannot be empty', async () => {
    render(<App />);
    await waitFor(() => expect(screen.getByRole('button', { name: /Generate Image/i })).toBeInTheDocument());

    const generateBtn = screen.getByRole('button', { name: /Generate Image/i });
    fireEvent.click(generateBtn);

    expect(await screen.findByText(/Please enter a prompt/i)).toBeInTheDocument();
  });

  // 4. Model selection works
  it('4. model selection updates the selected model', async () => {
    render(<App />);
    await waitFor(() => expect(screen.getByLabelText(/Model/i)).toBeInTheDocument());

    const modelSelect = screen.getByLabelText(/Model/i) as HTMLSelectElement;
    expect(modelSelect.value).toBe('black-forest-labs/FLUX.1.1-pro');

    fireEvent.change(modelSelect, { target: { value: 'fal-ai/flux-pro/v1.1' } });
    expect(modelSelect.value).toBe('fal-ai/flux-pro/v1.1');
  });

  // 5. Aspect ratio works
  it('5. aspect ratio selection updates aspect ratio state', async () => {
    render(<App />);
    await waitFor(() => expect(screen.getByRole('radio', { name: /16:9/i })).toBeInTheDocument());

    const portraitBtn = screen.getByRole('radio', { name: /9:16/i });
    fireEvent.click(portraitBtn);
    expect(portraitBtn).toHaveClass('selected');
  });

  // 6. Video-only fields appear only for video
  it('6. video duration fields appear only when Video or Image->Video is selected', async () => {
    render(<App />);
    await waitFor(() => expect(screen.getByRole('tab', { name: /^Video$/i })).toBeInTheDocument());

    // In Image mode: Video duration should NOT be visible
    expect(screen.queryByText(/Video Duration/i)).not.toBeInTheDocument();

    // Switch to Video mode: Video duration should be visible
    fireEvent.click(screen.getByRole('tab', { name: /^Video$/i }));
    expect(screen.getByText(/Video Duration/i)).toBeInTheDocument();
    expect(screen.getByText('5 seconds')).toBeInTheDocument();
    expect(screen.getByText('10 seconds')).toBeInTheDocument();
  });

  // 7. Start/end frame controls respect capabilities
  it('7. start and end frame controls strictly respect model capabilities', async () => {
    render(<App />);
    await waitFor(() => expect(screen.getByRole('tab', { name: /^Video$/i })).toBeInTheDocument());

    // Switch to Video mode (Kling model: start_frame=true, end_frame=false)
    fireEvent.click(screen.getByRole('tab', { name: /^Video$/i }));

    // Start frame should be supported
    expect(screen.getByText(/Start Frame \(First Frame\)/i)).toBeInTheDocument();
    expect(screen.getByText(/Base keyframe image from which motion begins/i)).toBeInTheDocument();

    // End frame should be clearly disabled with an explicit unsupported explanation
    expect(screen.getByText(/End Frame \(Last Frame\)/i)).toBeInTheDocument();
    expect(screen.getByTestId('end-frame-unsupported')).toBeInTheDocument();
    expect(screen.getByTestId('end-frame-unsupported')).toHaveTextContent(
      /End\/last frame is disabled.*does not support end-frame anchoring/i
    );
  });

  // 8. Generation request uses the real AryaOS API
  it('8. submits generation request to /creator/generate with correct payload', async () => {
    render(<App />);
    await waitFor(() => expect(screen.getByLabelText(/Prompt/i)).toBeInTheDocument());

    const promptInput = screen.getByLabelText(/Prompt/i);
    fireEvent.change(promptInput, { target: { value: 'A cinematic cybernetic garden' } });

    const generateBtn = screen.getByRole('button', { name: /Generate Image/i });
    fireEvent.click(generateBtn);

    await waitFor(() => {
      expect(globalThis.fetch).toHaveBeenCalledWith(
        '/creator/generate',
        expect.objectContaining({
          method: 'POST',
          body: expect.stringContaining('A cinematic cybernetic garden'),
        })
      );
    });
  });

  // 9. Job status is displayed
  it('9. displays job status card while job is processing and polling', async () => {
    render(<App />);
    await waitFor(() => expect(screen.getByLabelText(/Prompt/i)).toBeInTheDocument());

    fireEvent.change(screen.getByLabelText(/Prompt/i), { target: { value: 'A test scene' } });
    fireEvent.click(screen.getByRole('button', { name: /Generate Image/i }));

    expect(await screen.findByText('Job Status')).toBeInTheDocument();
    expect(screen.getByTestId('job-status-badge')).toBeInTheDocument();
  });

  // 10. Successful result is displayed
  it('10. displays generated result preview and telemetry upon completion', async () => {
    render(<App />);
    await waitFor(() => expect(screen.getByLabelText(/Prompt/i)).toBeInTheDocument());

    fireEvent.change(screen.getByLabelText(/Prompt/i), { target: { value: 'A completed scene' } });
    fireEvent.click(screen.getByRole('button', { name: /Generate Image/i }));

    // Wait for polling to fetch the completed job
    await waitFor(
      () => {
        const image = screen.getByTestId('image-preview');
        expect(image).toHaveAttribute('src', 'https://cdn.example.com/test_result.png');
      },
      { timeout: 4000 }
    );

    expect(screen.getByText('Download')).toBeInTheDocument();
  });

  // 11. Failed generation displays an error
  it('11. displays human-readable error when generation fails', async () => {
    (globalThis.fetch as any).mockImplementation((url: string, init?: RequestInit) => {
      const urlStr = url.toString();
      if (urlStr.includes('/health')) {
        return Promise.resolve({ ok: true, json: () => Promise.resolve({ status: 'healthy', checks: {} }) });
      }
      if (urlStr.includes('/creator/capabilities')) {
        return Promise.resolve({ ok: true, json: () => Promise.resolve(mockManifest) });
      }
      if (urlStr.includes('/creator/history')) {
        return Promise.resolve({ ok: true, json: () => Promise.resolve(mockHistory) });
      }
      if (urlStr.includes('/creator/generate')) {
        return Promise.resolve({
          ok: false,
          status: 500,
          text: () => Promise.resolve('All upstream providers failed (Replicate credit exhausted)'),
        });
      }
      return Promise.resolve({ ok: true, json: () => Promise.resolve({}) });
    });

    render(<App />);
    await waitFor(() => expect(screen.getByLabelText(/Prompt/i)).toBeInTheDocument());

    fireEvent.change(screen.getByLabelText(/Prompt/i), { target: { value: 'Trigger failure' } });
    fireEvent.click(screen.getByRole('button', { name: /Generate Image/i }));

    expect(
      await screen.findByText(/All upstream providers failed \(Replicate credit exhausted\)/i)
    ).toBeInTheDocument();
  });

  // 12. History loads from backend
  it('12. loads persistent history items from database and allows selection into preview', async () => {
    render(<App />);

    expect(await screen.findByText('Generation History')).toBeInTheDocument();
    expect(screen.getByText('A majestic mountain landscape at sunrise')).toBeInTheDocument();

    const historyCard = screen.getByTestId('history-item-hist-001');
    fireEvent.click(historyCard);

    // Clicking history item should populate the preview viewport
    await waitFor(() => {
      const img = screen.getByTestId('image-preview');
      expect(img).toHaveAttribute('src', 'https://cdn.example.com/mountain.png');
    });
  });
});
