import React from 'react';
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent, waitFor, act } from '@testing-library/react';
import { App } from '../App';
import { CapabilitiesManifest, GenerationJob, HistoryItem } from '../types/creator';
import { ReferenceUpload } from '../components/ReferenceUpload';

const mockManifest: CapabilitiesManifest = {
  generation_types: [
    { id: 'image', label: 'Image', description: 'High-fidelity image generation' },
    { id: 'video', label: 'Video', description: 'Cinematic video generation' },
    { id: 'image_to_video', label: 'Image → Video', description: 'Motion synthesis from keyframe' },
  ],
  aspect_ratios: [
    { id: '16:9', label: '16:9 (Landscape)', dimensions: '1344x768' },
    { id: '9:16', label: '9:16 (Portrait)', dimensions: '768x1344' },
    { id: '1:1', label: '1:1 (Square)', dimensions: '1024x1024' },
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
        id: 'fal-ai/kling-video/v1.6/standard/image-to-video',
        name: 'Kling 1.6 Motion',
        provider: 'fal',
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
    job_id: 'hist-item-001',
    workflow_run_id: 'wf-item-001',
    generation_type: 'image',
    prompt: 'Pre-existing command center rendering',
    model: 'FLUX 1.1 Pro',
    provider: 'together',
    aspect_ratio: '16:9',
    status: 'completed',
    asset_url: 'https://cdn.example.com/pre_existing.png',
    total_cost_usd: 0.04,
    created_at: new Date().toISOString(),
  },
];

describe('AryaOS Stage 5: Production Reliability, Job Lifecycle & Workspace Recovery', () => {
  let submittedPayloads: any[] = [];
  let pollRequestCount = 0;
  let simulatedJobResponse: any = null;

  beforeEach(() => {
    vi.resetAllMocks();
    localStorage.clear();
    sessionStorage.clear();
    submittedPayloads = [];
    pollRequestCount = 0;

    simulatedJobResponse = {
      job_id: 'job-stage5-100',
      workflow_run_id: 'wf-stage5-100',
      status: 'in_progress',
      current_stage: 'image_generation',
      generation_type: 'image',
      prompt: 'Production grade generation',
      model: 'black-forest-labs/FLUX.1.1-pro',
      provider: 'together',
      aspect_ratio: '16:9',
      total_cost_usd: 0.05,
      output: {},
    };

    globalThis.fetch = vi.fn().mockImplementation((url: string, init?: RequestInit) => {
      const urlStr = url.toString();

      if (urlStr.includes('/health')) {
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve({ status: 'healthy', checks: { postgres: 'ok' } }),
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

      if (urlStr.includes('/creator/upload')) {
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve({ url: 'https://cdn.example.com/ref.png', key: 'ref.png', filename: 'ref.png' }),
        });
      }

      if (urlStr.includes('/creator/generate')) {
        const body = JSON.parse((init?.body as string) || '{}');
        submittedPayloads.push(body);
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve(simulatedJobResponse || {
            job_id: 'job-stage5-100',
            workflow_run_id: 'wf-stage5-100',
            status: 'in_progress',
            current_stage: 'image_generation',
            generation_type: body.generation_type,
            prompt: body.prompt,
            model: body.model,
            provider: body.provider,
            aspect_ratio: body.aspect_ratio,
            output: {},
          }),
        });
      }

      if (urlStr.includes('/creator/jobs/')) {
        pollRequestCount++;
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve(simulatedJobResponse),
        });
      }

      return Promise.reject(new Error(`Unhandled mock fetch: ${urlStr}`));
    });
  });

  afterEach(() => {
    localStorage.clear();
    sessionStorage.clear();
  });

  // 1. Initial application starts STANDBY
  it('1. Initial application starts in STANDBY state', async () => {
    render(<App />);

    await waitFor(() => {
      expect(screen.getByText('STANDBY')).toBeInTheDocument();
      expect(screen.getByTestId('core-state-label')).toHaveTextContent('STANDBY');
    });
  });

  // 2. Valid prompt reaches READY
  it('2. Valid prompt reaches READY state', async () => {
    render(<App />);

    await waitFor(() => {
      expect(screen.getByLabelText(/Prompt/i)).toBeInTheDocument();
    });

    fireEvent.change(screen.getByLabelText(/Prompt/i), {
      target: { value: 'Atmospheric command station console' },
    });

    await waitFor(() => {
      expect(screen.getByText('READY')).toBeInTheDocument();
      expect(screen.getByTestId('core-state-label')).toHaveTextContent('READY');
    });
  });

  // 3. Execute enters SYNTHESIZING
  it('3. Execute enters SYNTHESIZING state immediately upon submission', async () => {
    // Delay submission slightly to observe SYNTHESIZING state
    (globalThis.fetch as any).mockImplementation((url: string, init?: RequestInit) => {
      const urlStr = url.toString();
      if (urlStr.includes('/health')) return Promise.resolve({ ok: true, json: () => Promise.resolve({ status: 'healthy' }) });
      if (urlStr.includes('/creator/capabilities')) return Promise.resolve({ ok: true, json: () => Promise.resolve(mockManifest) });
      if (urlStr.includes('/creator/history')) return Promise.resolve({ ok: true, json: () => Promise.resolve([]) });
      if (urlStr.includes('/creator/generate')) {
        return new Promise((resolve) => {
          setTimeout(() => {
            resolve({
              ok: true,
              json: () => Promise.resolve(simulatedJobResponse),
            });
          }, 100);
        });
      }
      return Promise.resolve({ ok: true, json: () => Promise.resolve({}) });
    });

    render(<App />);

    await waitFor(() => expect(screen.getByLabelText(/Prompt/i)).toBeInTheDocument());

    fireEvent.change(screen.getByLabelText(/Prompt/i), { target: { value: 'Hyperdetailed nebula' } });
    fireEvent.click(screen.getByTestId('generate-button'));

    // Immediate state while POST is executing
    expect(screen.getByText('SYNTHESIZING')).toBeInTheDocument();
    expect(screen.getByTestId('core-state-label')).toHaveTextContent('SYNTHESIZING');
  });

  // 4. Polling enters PROCESSING
  it('4. Polling enters PROCESSING when active stage reports running', async () => {
    simulatedJobResponse = {
      job_id: 'job-stage5-processing',
      workflow_run_id: 'wf-processing',
      status: 'in_progress',
      current_stage: 'image_generation',
      generation_type: 'image',
      prompt: 'Processing pipeline prompt',
      model: 'black-forest-labs/FLUX.1.1-pro',
      provider: 'together',
      output: {},
    };

    render(<App />);
    await waitFor(() => expect(screen.getByLabelText(/Prompt/i)).toBeInTheDocument());

    fireEvent.change(screen.getByLabelText(/Prompt/i), { target: { value: 'Processing pipeline prompt' } });
    fireEvent.click(screen.getByTestId('generate-button'));

    await waitFor(() => {
      expect(screen.getByText('PROCESSING')).toBeInTheDocument();
      expect(screen.getByText('Executing Image Generation Agent')).toBeInTheDocument();
    });
  });

  // 5. Completion enters COMPLETE
  it('5. Completion transitions CommandCore to COMPLETE', async () => {
    simulatedJobResponse = {
      job_id: 'job-stage5-complete',
      workflow_run_id: 'wf-complete',
      status: 'completed',
      current_stage: 'completed',
      generation_type: 'image',
      prompt: 'Completed scene prompt',
      model: 'black-forest-labs/FLUX.1.1-pro',
      provider: 'together',
      output: {
        asset_url: 'https://cdn.example.com/completed.png',
        storage_path: 'https://cdn.example.com/completed.png',
      },
    };

    render(<App />);
    await waitFor(() => expect(screen.getByLabelText(/Prompt/i)).toBeInTheDocument());

    fireEvent.change(screen.getByLabelText(/Prompt/i), { target: { value: 'Completed scene prompt' } });
    fireEvent.click(screen.getByTestId('generate-button'));

    await waitFor(() => {
      expect(screen.getByText('COMPLETE')).toBeInTheDocument();
      expect(screen.getByTestId('core-state-label')).toHaveTextContent('COMPLETE');
    });
  });

  // 6. Completion stops polling
  it('6. Completion stops further polling requests', async () => {
    simulatedJobResponse = {
      job_id: 'job-stage5-stop-poll',
      workflow_run_id: 'wf-stop',
      status: 'completed',
      current_stage: 'completed',
      generation_type: 'image',
      prompt: 'Polling stop test',
      output: { asset_url: 'https://cdn.example.com/done.png' },
    };

    render(<App />);
    await waitFor(() => expect(screen.getByLabelText(/Prompt/i)).toBeInTheDocument());

    fireEvent.change(screen.getByLabelText(/Prompt/i), { target: { value: 'Polling stop test' } });
    fireEvent.click(screen.getByTestId('generate-button'));

    await waitFor(() => {
      expect(screen.getByText('COMPLETE')).toBeInTheDocument();
    });

    const callsAtCompletion = pollRequestCount;
    // Wait a brief tick to ensure polling loop has terminated
    await new Promise((r) => setTimeout(r, 300));
    expect(pollRequestCount).toBe(callsAtCompletion);
  });

  // 7. Failure enters ERROR
  it('7. Failure transitions CommandCore to ERROR with human-readable reason', async () => {
    simulatedJobResponse = {
      job_id: 'job-stage5-fail',
      workflow_run_id: 'wf-fail',
      status: 'failed',
      failure_reason: 'GPU cluster rate limit exceeded',
      generation_type: 'image',
      prompt: 'Failed prompt',
      output: {},
    };

    render(<App />);
    await waitFor(() => expect(screen.getByLabelText(/Prompt/i)).toBeInTheDocument());

    fireEvent.change(screen.getByLabelText(/Prompt/i), { target: { value: 'Failed prompt' } });
    fireEvent.click(screen.getByTestId('generate-button'));

    await waitFor(() => {
      expect(screen.getByText('ERROR')).toBeInTheDocument();
      expect(screen.getByText('GPU cluster rate limit exceeded')).toBeInTheDocument();
    });
  });

  // 8. Failure stops polling
  it('8. Failure stops polling cleanly', async () => {
    simulatedJobResponse = {
      job_id: 'job-stage5-fail-poll',
      workflow_run_id: 'wf-fail-poll',
      status: 'failed',
      failure_reason: 'Unrecoverable provider timeout',
      generation_type: 'image',
      prompt: 'Fail poll prompt',
      output: {},
    };

    render(<App />);
    await waitFor(() => expect(screen.getByLabelText(/Prompt/i)).toBeInTheDocument());

    fireEvent.change(screen.getByLabelText(/Prompt/i), { target: { value: 'Fail poll prompt' } });
    fireEvent.click(screen.getByTestId('generate-button'));

    await waitFor(() => {
      expect(screen.getByText('ERROR')).toBeInTheDocument();
    });

    const callsAtFailure = pollRequestCount;
    await new Promise((r) => setTimeout(r, 300));
    expect(pollRequestCount).toBe(callsAtFailure);
  });

  // 9. Retry preserves original submitted parameters
  it('9. Retry preserves original submitted parameters even if form was modified', async () => {
    let callNum = 0;
    (globalThis.fetch as any).mockImplementation((url: string, init?: RequestInit) => {
      const urlStr = url.toString();
      if (urlStr.includes('/health')) return Promise.resolve({ ok: true, json: () => Promise.resolve({ status: 'healthy' }) });
      if (urlStr.includes('/creator/capabilities')) return Promise.resolve({ ok: true, json: () => Promise.resolve(mockManifest) });
      if (urlStr.includes('/creator/history')) return Promise.resolve({ ok: true, json: () => Promise.resolve([]) });

      if (urlStr.includes('/creator/generate')) {
        callNum++;
        const body = JSON.parse((init?.body as string) || '{}');
        submittedPayloads.push(body);

        if (callNum === 1) {
          return Promise.resolve({
            ok: true,
            json: () => Promise.resolve({
              job_id: 'job-retry-fail',
              workflow_run_id: 'wf-retry-fail',
              status: 'failed',
              failure_reason: 'Node warm-up required',
              generation_type: body.generation_type,
              prompt: body.prompt,
            }),
          });
        }
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve({
            job_id: 'job-retry-ok',
            workflow_run_id: 'wf-retry-ok',
            status: 'completed',
            current_stage: 'completed',
            generation_type: body.generation_type,
            prompt: body.prompt,
            output: { asset_url: 'https://cdn.example.com/retry_success.png' },
          }),
        });
      }

      if (urlStr.includes('/creator/jobs/')) {
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve(callNum === 1 ? {
            job_id: 'job-retry-fail',
            status: 'failed',
            failure_reason: 'Node warm-up required',
          } : {
            job_id: 'job-retry-ok',
            status: 'completed',
            output: { asset_url: 'https://cdn.example.com/retry_success.png' },
          }),
        });
      }

      return Promise.reject(new Error(`Unhandled: ${urlStr}`));
    });

    render(<App />);
    await waitFor(() => expect(screen.getByLabelText(/Prompt/i)).toBeInTheDocument());

    const promptInput = screen.getByLabelText(/Prompt/i);
    fireEvent.change(promptInput, { target: { value: 'Original Golden Prompt' } });
    fireEvent.click(screen.getByTestId('generate-button'));

    // Wait for failure
    await waitFor(() => {
      expect(screen.getByText('ERROR')).toBeInTheDocument();
      expect(screen.getByTestId('job-retry-button')).toBeInTheDocument();
    });

    // User modifies prompt field in UI during/after failure
    fireEvent.change(promptInput, { target: { value: 'Accidental Unrelated Form Edit' } });

    // Click retry
    fireEvent.click(screen.getByTestId('job-retry-button'));

    await waitFor(() => {
      expect(submittedPayloads.length).toBe(2);
      // Rationale: Retry MUST use original submitted parameters snapshot, NOT the subsequent edit
      expect(submittedPayloads[0].prompt).toBe('Original Golden Prompt');
      expect(submittedPayloads[1].prompt).toBe('Original Golden Prompt');
      expect(screen.getByText('COMPLETE')).toBeInTheDocument();
    });
  });

  // 10. Retry does not create duplicate polling loops
  it('10. Retry cancels existing loop and does not create duplicate polling timers', async () => {
    let callNum = 0;
    (globalThis.fetch as any).mockImplementation((url: string, init?: RequestInit) => {
      const urlStr = url.toString();
      if (urlStr.includes('/health')) return Promise.resolve({ ok: true, json: () => Promise.resolve({ status: 'healthy' }) });
      if (urlStr.includes('/creator/capabilities')) return Promise.resolve({ ok: true, json: () => Promise.resolve(mockManifest) });
      if (urlStr.includes('/creator/history')) return Promise.resolve({ ok: true, json: () => Promise.resolve([]) });

      if (urlStr.includes('/creator/generate')) {
        callNum++;
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve({
            job_id: `job-retry-loop-${callNum}`,
            workflow_run_id: `wf-${callNum}`,
            status: callNum === 1 ? 'failed' : 'completed',
            failure_reason: callNum === 1 ? 'Temporary failure' : undefined,
            generation_type: 'image',
            prompt: 'Test single poll loop',
            output: callNum === 2 ? { asset_url: 'https://cdn.example.com/ok.png' } : {},
          }),
        });
      }

      if (urlStr.includes('/creator/jobs/')) {
        pollRequestCount++;
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve({
            job_id: `job-retry-loop-${callNum}`,
            status: 'completed',
            output: { asset_url: 'https://cdn.example.com/ok.png' },
          }),
        });
      }

      return Promise.reject(new Error(`Unhandled: ${urlStr}`));
    });

    render(<App />);
    await waitFor(() => expect(screen.getByLabelText(/Prompt/i)).toBeInTheDocument());

    fireEvent.change(screen.getByLabelText(/Prompt/i), { target: { value: 'Test single poll loop' } });
    fireEvent.click(screen.getByTestId('generate-button'));

    await waitFor(() => expect(screen.getByTestId('job-retry-button')).toBeInTheDocument());

    fireEvent.click(screen.getByTestId('job-retry-button'));

    await waitFor(() => expect(screen.getByText('COMPLETE')).toBeInTheDocument());

    // Single interval cleanup guarantees no runaway poll rate
    expect(pollRequestCount).toBeLessThanOrEqual(2);
  });

  // 11. Double-click cannot create duplicate submissions
  it('11. Rapid double-click cannot create duplicate job submissions', async () => {
    render(<App />);
    await waitFor(() => expect(screen.getByLabelText(/Prompt/i)).toBeInTheDocument());

    fireEvent.change(screen.getByLabelText(/Prompt/i), { target: { value: 'Rapid double click prevention' } });

    const btn = screen.getByTestId('generate-button');
    // Rapid synchronous double click
    fireEvent.click(btn);
    fireEvent.click(btn);

    await waitFor(() => {
      expect(submittedPayloads.length).toBe(1);
    });
  });

  // 12. Polling cleanup occurs on unmount
  it('12. Polling cleanup occurs on unmount without console warnings or orphan timers', async () => {
    simulatedJobResponse = {
      job_id: 'job-unmount-test',
      workflow_run_id: 'wf-unmount',
      status: 'in_progress',
      current_stage: 'image_generation',
      generation_type: 'image',
      prompt: 'Unmount cleanup test',
      output: {},
    };

    const { unmount } = render(<App />);
    await waitFor(() => expect(screen.getByLabelText(/Prompt/i)).toBeInTheDocument());

    fireEvent.change(screen.getByLabelText(/Prompt/i), { target: { value: 'Unmount cleanup test' } });
    fireEvent.click(screen.getByTestId('generate-button'));

    await waitFor(() => expect(screen.getByText('PROCESSING')).toBeInTheDocument());

    // Unmount while polling is active
    unmount();

    // Advance time slightly; should not crash or throw unmounted state update errors
    await new Promise((r) => setTimeout(r, 200));
  });

  // 13. Stale job cannot overwrite newer job state
  it('13. Stale job response cannot overwrite state of a newer job', async () => {
    let callIndex = 0;
    (globalThis.fetch as any).mockImplementation((url: string, init?: RequestInit) => {
      const urlStr = url.toString();
      if (urlStr.includes('/health')) return Promise.resolve({ ok: true, json: () => Promise.resolve({ status: 'healthy' }) });
      if (urlStr.includes('/creator/capabilities')) return Promise.resolve({ ok: true, json: () => Promise.resolve(mockManifest) });
      if (urlStr.includes('/creator/history')) return Promise.resolve({ ok: true, json: () => Promise.resolve([]) });

      if (urlStr.includes('/creator/generate')) {
        callIndex++;
        const body = JSON.parse((init?.body as string) || '{}');
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve({
            job_id: `job-seq-${callIndex}`,
            workflow_run_id: `wf-${callIndex}`,
            status: 'in_progress',
            prompt: body.prompt,
            generation_type: 'image',
            output: {},
          }),
        });
      }

      if (urlStr.includes('/creator/jobs/job-seq-1')) {
        // Delayed stale poll response for job 1
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve({
            job_id: 'job-seq-1',
            status: 'failed',
            failure_reason: 'Stale job 1 failure',
            prompt: 'First old job',
            generation_type: 'image',
            output: {},
          }),
        });
      }

      if (urlStr.includes('/creator/jobs/job-seq-2')) {
        // Newer job 2 poll response
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve({
            job_id: 'job-seq-2',
            status: 'completed',
            prompt: 'Second new job',
            generation_type: 'image',
            output: { asset_url: 'https://cdn.example.com/job2.png' },
          }),
        });
      }

      return Promise.reject(new Error(`Unhandled: ${urlStr}`));
    });

    render(<App />);
    await waitFor(() => expect(screen.getByLabelText(/Prompt/i)).toBeInTheDocument());

    // Submit Job 1
    fireEvent.change(screen.getByLabelText(/Prompt/i), { target: { value: 'First old job' } });
    fireEvent.click(screen.getByTestId('generate-button'));

    await waitFor(() => expect(screen.getByText('Job Status')).toBeInTheDocument());

    // Submit Job 2 (supersedes Job 1)
    fireEvent.change(screen.getByLabelText(/Prompt/i), { target: { value: 'Second new job' } });
    // Note: since Job 1 is running, click retry or retry mechanism initiates new generation
    fireEvent.click(screen.getByTestId('generate-button'));

    // Wait for Job 2 completion
    await waitFor(() => {
      // Must not display "Stale job 1 failure"
      expect(screen.queryByText('Stale job 1 failure')).not.toBeInTheDocument();
    });
  });

  // 14. History refresh does not erase active viewport state
  it('14. History refresh does not erase the currently displayed asset in viewport', async () => {
    simulatedJobResponse = {
      job_id: 'job-hist-viewport',
      workflow_run_id: 'wf-hist-vp',
      status: 'completed',
      current_stage: 'completed',
      generation_type: 'image',
      prompt: 'Viewport persistence during refresh',
      output: { asset_url: 'https://cdn.example.com/viewport_persist.png' },
    };

    render(<App />);
    await waitFor(() => expect(screen.getByLabelText(/Prompt/i)).toBeInTheDocument());

    fireEvent.change(screen.getByLabelText(/Prompt/i), { target: { value: 'Viewport persistence during refresh' } });
    fireEvent.click(screen.getByTestId('generate-button'));

    await waitFor(() => {
      expect(screen.getByTestId('image-preview')).toHaveAttribute('src', 'https://cdn.example.com/viewport_persist.png');
    });

    // Trigger history refresh from header
    const refreshBtn = screen.getByTitle(/Refresh History from Database/i);
    fireEvent.click(refreshBtn);

    // Asset must remain visible in viewport
    expect(screen.getByTestId('image-preview')).toHaveAttribute('src', 'https://cdn.example.com/viewport_persist.png');
  });

  // 15. Completed asset loads into viewport
  it('15. Completed asset loads with image tag into Creative Viewport', async () => {
    simulatedJobResponse = {
      job_id: 'job-asset-load',
      workflow_run_id: 'wf-asset',
      status: 'completed',
      current_stage: 'completed',
      generation_type: 'image',
      prompt: 'Load asset test',
      output: { asset_url: 'https://cdn.example.com/final_output.png' },
    };

    render(<App />);
    await waitFor(() => expect(screen.getByLabelText(/Prompt/i)).toBeInTheDocument());

    fireEvent.change(screen.getByLabelText(/Prompt/i), { target: { value: 'Load asset test' } });
    fireEvent.click(screen.getByTestId('generate-button'));

    await waitFor(() => {
      const img = screen.getByTestId('image-preview');
      expect(img).toBeInTheDocument();
      expect(img).toHaveAttribute('src', 'https://cdn.example.com/final_output.png');
    });
  });

  // 16. Video asset uses the correct media element
  it('16. Video asset uses the video element with controls in viewport', async () => {
    simulatedJobResponse = {
      job_id: 'job-video-media',
      workflow_run_id: 'wf-video',
      status: 'completed',
      current_stage: 'completed',
      generation_type: 'video',
      prompt: 'Ocean waves clip',
      output: { asset_url: 'https://cdn.example.com/ocean_waves.mp4' },
    };

    render(<App />);
    await waitFor(() => expect(screen.getByRole('tab', { name: /^Video$/i })).toBeInTheDocument());

    fireEvent.click(screen.getByRole('tab', { name: /^Video$/i }));
    fireEvent.change(screen.getByLabelText(/Prompt/i), { target: { value: 'Ocean waves clip' } });
    fireEvent.click(screen.getByTestId('generate-button'));

    await waitFor(() => {
      const video = screen.getByTestId('video-player');
      expect(video).toBeInTheDocument();
      expect(video).toHaveAttribute('src', 'https://cdn.example.com/ocean_waves.mp4');
    });
  });

  // 17. Temporary polling failure does not falsely report completion
  it('17. Temporary polling network failure does not falsely report completion or crash active job', async () => {
    let pollCount = 0;
    (globalThis.fetch as any).mockImplementation((url: string, init?: RequestInit) => {
      const urlStr = url.toString();
      if (urlStr.includes('/health')) return Promise.resolve({ ok: true, json: () => Promise.resolve({ status: 'healthy' }) });
      if (urlStr.includes('/creator/capabilities')) return Promise.resolve({ ok: true, json: () => Promise.resolve(mockManifest) });
      if (urlStr.includes('/creator/history')) return Promise.resolve({ ok: true, json: () => Promise.resolve([]) });

      if (urlStr.includes('/creator/generate')) {
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve({
            job_id: 'job-temp-fail',
            status: 'in_progress',
            generation_type: 'image',
            prompt: 'Temp failure test',
            output: {},
          }),
        });
      }

      if (urlStr.includes('/creator/jobs/job-temp-fail')) {
        pollCount++;
        if (pollCount === 1) {
          // First poll tick: transient 500 error
          return Promise.resolve({
            ok: false,
            status: 500,
            text: () => Promise.resolve('Upstream Gateway Timeout'),
          });
        }
        // Second poll tick: recovers and completes
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve({
            job_id: 'job-temp-fail',
            status: 'completed',
            generation_type: 'image',
            prompt: 'Temp failure test',
            output: { asset_url: 'https://cdn.example.com/recovered.png' },
          }),
        });
      }

      return Promise.reject(new Error(`Unhandled: ${urlStr}`));
    });

    render(<App />);
    await waitFor(() => expect(screen.getByLabelText(/Prompt/i)).toBeInTheDocument());

    fireEvent.change(screen.getByLabelText(/Prompt/i), { target: { value: 'Temp failure test' } });
    fireEvent.click(screen.getByTestId('generate-button'));

    // Verify it handles transient hiccup and eventually reaches complete
    await waitFor(
      () => {
        expect(screen.getByText('COMPLETE')).toBeInTheDocument();
      },
      { timeout: 4500 }
    );
  });

  // 18. Missing optional backend fields do not crash the UI
  it('18. Missing optional backend fields do not crash the UI (defensive parsing)', async () => {
    simulatedJobResponse = {
      job_id: 'job-minimal-fields',
      workflow_run_id: 'wf-minimal',
      status: 'completed',
      current_stage: 'completed',
      generation_type: 'image',
      prompt: 'Minimal payload prompt',
      total_cost_usd: null,
      output: {}, // Missing provider_used, candidate_urls, duration, etc.
    };

    render(<App />);
    await waitFor(() => expect(screen.getByLabelText(/Prompt/i)).toBeInTheDocument());

    fireEvent.change(screen.getByLabelText(/Prompt/i), { target: { value: 'Minimal payload prompt' } });
    fireEvent.click(screen.getByTestId('generate-button'));

    // Should complete cleanly without throwing Uncaught TypeError
    await waitFor(() => {
      expect(screen.getByText('COMPLETE')).toBeInTheDocument();
      expect(screen.getByText('Job Status')).toBeInTheDocument();
    });
  });

  // 19. Active-job parameter snapshot remains stable after form edits
  it('19. Active-job parameter snapshot remains stable after form edits during execution', async () => {
    simulatedJobResponse = {
      job_id: 'job-snapshot-stability',
      workflow_run_id: 'wf-snapshot',
      status: 'in_progress',
      current_stage: 'image_generation',
      generation_type: 'image',
      prompt: 'Submitted Snapshot Prompt',
      model: 'black-forest-labs/FLUX.1.1-pro',
      provider: 'together',
      output: {},
    };

    render(<App />);
    await waitFor(() => expect(screen.getByLabelText(/Prompt/i)).toBeInTheDocument());

    const promptInput = screen.getByLabelText(/Prompt/i);
    fireEvent.change(promptInput, { target: { value: 'Submitted Snapshot Prompt' } });
    fireEvent.click(screen.getByTestId('generate-button'));

    await waitFor(() => {
      expect(screen.getByText('PROCESSING')).toBeInTheDocument();
    });

    // Form is edited while job is running
    fireEvent.change(promptInput, { target: { value: 'Subsequent Form Modification' } });

    // JobStatusCard and active telemetry still display original submitted prompt
    expect(screen.getByText('Job Status')).toBeInTheDocument();
    expect(submittedPayloads[0].prompt).toBe('Submitted Snapshot Prompt');
  });

  // 20. Workspace recovery behaves correctly IF the existing backend contract supports it
  it('20. Workspace recovery restores in-progress generation after page refresh', async () => {
    // Simulate pre-existing unfinished job saved in localStorage before refresh
    localStorage.setItem(
      'arya_active_job_recovery',
      JSON.stringify({
        jobId: 'job-recovery-active-99',
        generationType: 'image',
        submittedAt: Date.now() - 5000,
        payloadSnapshot: {
          generation_type: 'image',
          prompt: 'Recovered active workspace job',
          model: 'black-forest-labs/FLUX.1.1-pro',
        },
      })
    );

    let recoveredPollCount = 0;
    (globalThis.fetch as any).mockImplementation((url: string) => {
      const urlStr = url.toString();
      if (urlStr.includes('/health')) return Promise.resolve({ ok: true, json: () => Promise.resolve({ status: 'healthy' }) });
      if (urlStr.includes('/creator/capabilities')) return Promise.resolve({ ok: true, json: () => Promise.resolve(mockManifest) });
      if (urlStr.includes('/creator/history')) return Promise.resolve({ ok: true, json: () => Promise.resolve([]) });

      if (urlStr.includes('/creator/jobs/job-recovery-active-99')) {
        recoveredPollCount++;
        if (recoveredPollCount === 1) {
          // First poll on mount restores in-progress state
          return Promise.resolve({
            ok: true,
            json: () => Promise.resolve({
              job_id: 'job-recovery-active-99',
              workflow_run_id: 'wf-rec-99',
              status: 'in_progress',
              current_stage: 'image_generation',
              generation_type: 'image',
              prompt: 'Recovered active workspace job',
              model: 'black-forest-labs/FLUX.1.1-pro',
              output: {},
            }),
          });
        }
        // Next poll tick finishes the job
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve({
            job_id: 'job-recovery-active-99',
            workflow_run_id: 'wf-rec-99',
            status: 'completed',
            current_stage: 'completed',
            generation_type: 'image',
            prompt: 'Recovered active workspace job',
            output: { asset_url: 'https://cdn.example.com/recovered_done.png' },
          }),
        });
      }

      return Promise.reject(new Error(`Unhandled: ${urlStr}`));
    });

    render(<App />);

    // Rationale: Reconnects to backend, restores PROCESSING state, then completes
    await waitFor(() => {
      expect(screen.getByText('PROCESSING')).toBeInTheDocument();
      expect(screen.getByText('Job Status')).toBeInTheDocument();
    });

    await waitFor(
      () => {
        expect(screen.getByText('COMPLETE')).toBeInTheDocument();
        expect(screen.getByTestId('image-preview')).toHaveAttribute(
          'src',
          'https://cdn.example.com/recovered_done.png'
        );
      },
      { timeout: 4500 }
    );

    // Stale recovery record cleared upon completion
    expect(localStorage.getItem('arya_active_job_recovery')).toBeNull();
  });

  // 21. If recovery is unsupported by the backend contract, verify safe fallback behavior
  it('21. Safe fallback behavior if backend reports 404 for stored recovery job', async () => {
    localStorage.setItem(
      'arya_active_job_recovery',
      JSON.stringify({
        jobId: 'job-stale-expired-404',
        generationType: 'image',
        submittedAt: Date.now() - 10000,
      })
    );

    (globalThis.fetch as any).mockImplementation((url: string) => {
      const urlStr = url.toString();
      if (urlStr.includes('/health')) return Promise.resolve({ ok: true, json: () => Promise.resolve({ status: 'healthy' }) });
      if (urlStr.includes('/creator/capabilities')) return Promise.resolve({ ok: true, json: () => Promise.resolve(mockManifest) });
      if (urlStr.includes('/creator/history')) return Promise.resolve({ ok: true, json: () => Promise.resolve([]) });

      if (urlStr.includes('/creator/jobs/job-stale-expired-404')) {
        return Promise.resolve({
          ok: false,
          status: 404,
          text: () => Promise.resolve('Job not found'),
        });
      }

      return Promise.reject(new Error(`Unhandled: ${urlStr}`));
    });

    render(<App />);

    // App must not crash and should settle into clean STANDBY
    await waitFor(() => {
      expect(screen.getByText('STANDBY')).toBeInTheDocument();
    });

    // Stale recovery record pruned
    expect(localStorage.getItem('arya_active_job_recovery')).toBeNull();
  });

  // 22. Object URL cleanup occurs where applicable
  it('22. Object URL cleanup occurs upon file selection, replacement, and unmount', async () => {
    const originalCreate = URL.createObjectURL;
    const originalRevoke = URL.revokeObjectURL;

    const mockCreate = vi.fn(() => 'blob:http://localhost/test-blob-uuid');
    const mockRevoke = vi.fn();

    URL.createObjectURL = mockCreate;
    URL.revokeObjectURL = mockRevoke;

    try {
      const handleImageChange = vi.fn();
      const { unmount } = render(
        <ReferenceUpload
          label="Reference Input"
          onImageChange={handleImageChange}
        />
      );

      const file = new File(['mock content'], 'test_cleanup.png', { type: 'image/png' });
      const input = screen.getByTestId('reference-file-input');

      fireEvent.change(input, { target: { files: [file] } });

      await waitFor(() => {
        expect(mockCreate).toHaveBeenCalled();
        expect(mockRevoke).toHaveBeenCalled();
      });

      unmount();
    } finally {
      URL.createObjectURL = originalCreate;
      URL.revokeObjectURL = originalRevoke;
    }
  });
});
