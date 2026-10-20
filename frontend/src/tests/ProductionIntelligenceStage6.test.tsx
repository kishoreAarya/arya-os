import React from 'react';
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent, waitFor, act } from '@testing-library/react';
import { App } from '../App';
import { CapabilitiesManifest, GenerationJob, HistoryItem } from '../types/creator';
import {
  historyItemToProductionRun,
  generationJobToProductionRun,
  computeOperationalMetrics,
  filterAndSortRuns,
  ProductionRun,
} from '../types/productionRun';
import { RunDetailInspector } from '../components/history/RunDetailInspector';

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

const mockHistoryData: HistoryItem[] = [
  {
    job_id: 'run-image-001',
    workflow_run_id: 'wf-image-001',
    generation_type: 'image',
    prompt: 'Cinematic cybernetic control station in obsidian mist',
    model: 'FLUX 1.1 Pro',
    provider: 'together',
    aspect_ratio: '16:9',
    duration_seconds: 4.2,
    status: 'completed',
    asset_url: 'https://cdn.example.com/obsidian_mist.png',
    total_cost_usd: 0.045,
    created_at: '2026-09-27T08:00:00Z',
    completed_at: '2026-09-27T08:00:04Z',
  },
  {
    job_id: 'run-video-002',
    workflow_run_id: 'wf-video-002',
    generation_type: 'video',
    prompt: 'Aerial flight over neon metropolis grid',
    model: 'Kling 1.6 Standard',
    provider: 'kling',
    aspect_ratio: '16:9',
    duration_seconds: 5.0,
    status: 'completed',
    asset_url: 'https://cdn.example.com/neon_metropolis.mp4',
    total_cost_usd: 0.12,
    created_at: '2026-09-27T08:10:00Z',
    completed_at: '2026-09-27T08:10:15Z',
  },
  {
    job_id: 'run-failed-003',
    workflow_run_id: 'wf-failed-003',
    generation_type: 'image',
    prompt: 'Corrupted neural matrix render',
    model: 'FLUX 1.1 Pro',
    provider: 'together',
    aspect_ratio: '1:1',
    status: 'failed',
    failure_reason: 'Provider rate limit exceeded (HTTP 429)',
    total_cost_usd: 0.0,
    created_at: '2026-09-27T08:20:00Z',
  },
  {
    job_id: 'run-i2v-004',
    workflow_run_id: 'wf-i2v-004',
    generation_type: 'image_to_video',
    prompt: 'Glitch animation with particle simulation',
    model: 'Kling 1.6 Motion',
    provider: 'fal',
    aspect_ratio: '9:16',
    duration_seconds: 5.0,
    status: 'completed',
    asset_url: 'https://cdn.example.com/particle_sim.mp4',
    total_cost_usd: 0.08,
    created_at: '2026-09-27T08:30:00Z',
    completed_at: '2026-09-27T08:30:10Z',
  },
];

describe('AryaOS Stage 6: Persistent Production Intelligence & Run Management', () => {
  let submittedPayloads: any[] = [];
  let simulatedPollResponse: any = null;

  beforeEach(() => {
    vi.resetAllMocks();
    localStorage.clear();
    sessionStorage.clear();
    submittedPayloads = [];

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
          json: () => Promise.resolve(mockHistoryData),
        });
      }

      if (urlStr.includes('/creator/generate')) {
        const body = JSON.parse((init?.body as string) || '{}');
        submittedPayloads.push(body);
        return Promise.resolve({
          ok: true,
          json: () =>
            Promise.resolve({
              job_id: 'job-stage6-active',
              workflow_run_id: 'wf-stage6-active',
              status: 'in_progress',
              current_stage: 'image_generation',
              generation_type: body.generation_type || 'image',
              prompt: body.prompt || '',
              model: body.model || 'black-forest-labs/FLUX.1.1-pro',
              provider: body.provider || 'together',
              aspect_ratio: body.aspect_ratio || '16:9',
              total_cost_usd: 0.0,
              output: {},
            }),
        });
      }

      if (urlStr.includes('/creator/jobs/')) {
        return Promise.resolve({
          ok: true,
          json: () =>
            Promise.resolve(
              simulatedPollResponse || {
                job_id: 'job-stage6-active',
                workflow_run_id: 'wf-stage6-active',
                status: 'in_progress',
                current_stage: 'image_generation',
                generation_type: 'image',
                prompt: 'Active test run',
                model: 'FLUX 1.1 Pro',
                provider: 'together',
                aspect_ratio: '16:9',
                total_cost_usd: 0.05,
                output: {},
              }
            ),
        });
      }

      return Promise.resolve({
        ok: true,
        json: () => Promise.resolve({}),
      });
    });
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  // 1. Run Registry: History item conversion
  it('1. correctly maps history item into ProductionRun registry model', () => {
    const item = mockHistoryData[0];
    const run = historyItemToProductionRun(item);

    expect(run.id).toBe('wf-image-001');
    expect(run.jobId).toBe('run-image-001');
    expect(run.mode).toBe('image');
    expect(run.status).toBe('completed');
    expect(run.prompt).toBe('Cinematic cybernetic control station in obsidian mist');
    expect(run.model).toBe('FLUX 1.1 Pro');
    expect(run.provider).toBe('together');
    expect(run.parameters.aspectRatio).toBe('16:9');
    expect(run.outputAsset).toBe('https://cdn.example.com/obsidian_mist.png');
    expect(run.cost).toBe(0.045);
  });

  // 2. Run Registry: Missing optional fields handling
  it('2. handles missing optional fields safely without fabricating fake telemetry', () => {
    const minimalItem: HistoryItem = {
      job_id: 'job-min-1',
      workflow_run_id: 'wf-min-1',
      generation_type: 'image',
      prompt: 'Minimal prompt test',
      status: 'pending',
      total_cost_usd: 0.0,
      created_at: '2026-09-27T09:00:00Z',
    };

    const run = historyItemToProductionRun(minimalItem);
    expect(run.model).toBeUndefined();
    expect(run.provider).toBeUndefined();
    expect(run.cost).toBeUndefined();
    expect(run.error).toBeUndefined();
    expect(run.outputAsset).toBeUndefined();
  });

  // 3. Run Registry: Generation job conversion
  it('3. converts live GenerationJob with output payload to ProductionRun', () => {
    const job: GenerationJob = {
      job_id: 'live-job-1',
      workflow_run_id: 'live-wf-1',
      status: 'completed',
      current_stage: 'completed',
      generation_type: 'video',
      prompt: 'Live job test',
      model: 'Kling 1.6 Standard',
      provider: 'kling',
      aspect_ratio: '16:9',
      duration_seconds: 5.0,
      total_cost_usd: 0.14,
      started_at: '2026-09-27T08:00:00Z',
      completed_at: '2026-09-27T08:00:10Z',
      output: {
        asset_url: 'https://cdn.example.com/live_output.mp4',
        provider_used: 'kling-replicate',
        source_image_path: 'https://cdn.example.com/keyframe.png',
      },
    };

    const run = generationJobToProductionRun(job);
    expect(run.actualProvider).toBe('kling-replicate');
    expect(run.outputAsset).toBe('https://cdn.example.com/live_output.mp4');
    expect(run.startFrame).toBe('https://cdn.example.com/keyframe.png');
    expect(run.durationSeconds).toBe(10);
  });

  // 4. Metrics: Operational metrics calculations
  it('4. computes accurate operational metrics across run registry', () => {
    const runs = mockHistoryData.map(historyItemToProductionRun);
    const metrics = computeOperationalMetrics(runs);

    expect(metrics.totalRuns).toBe(4);
    expect(metrics.successfulRuns).toBe(3);
    expect(metrics.failedRuns).toBe(1);
    expect(metrics.successRate).toBe(75); // 3 of 4 = 75%
    expect(metrics.totalCostUsd).toBeCloseTo(0.245, 3);
    expect(metrics.providerUsage['together']).toBe(2);
    expect(metrics.providerUsage['kling']).toBe(1);
    expect(metrics.providerUsage['fal']).toBe(1);
  });

  // 5. Metrics: Empty dataset handling
  it('5. handles empty dataset gracefully without division by zero or NaN', () => {
    const metrics = computeOperationalMetrics([]);
    expect(metrics.totalRuns).toBe(0);
    expect(metrics.successfulRuns).toBe(0);
    expect(metrics.failedRuns).toBe(0);
    expect(metrics.successRate).toBe(0);
    expect(metrics.avgDurationSeconds).toBeNull();
    expect(metrics.totalCostUsd).toBe(0);
  });

  // 6. Search filtering: Search by prompt
  it('6. filters runs by prompt text in search', () => {
    const runs = mockHistoryData.map(historyItemToProductionRun);
    const results = filterAndSortRuns(runs, 'neon metropolis', 'all', 'newest');
    expect(results).toHaveLength(1);
    expect(results[0].jobId).toBe('run-video-002');
  });

  // 7. Search filtering: Search by model or provider
  it('7. filters runs by provider or model name in search', () => {
    const runs = mockHistoryData.map(historyItemToProductionRun);
    const results = filterAndSortRuns(runs, 'kling', 'all', 'newest');
    expect(results).toHaveLength(2); // video and image_to_video
  });

  // 8. Mode Filtering: Image only, Video only, Failed only
  it('8. filters runs by generation mode and completion status', () => {
    const runs = mockHistoryData.map(historyItemToProductionRun);

    const imageRuns = filterAndSortRuns(runs, '', 'image', 'newest');
    expect(imageRuns).toHaveLength(2);

    const videoRuns = filterAndSortRuns(runs, '', 'video', 'newest');
    expect(videoRuns).toHaveLength(1);

    const failedRuns = filterAndSortRuns(runs, '', 'failed', 'newest');
    expect(failedRuns).toHaveLength(1);
    expect(failedRuns[0].error).toContain('Provider rate limit exceeded');
  });

  // 9. Sorting: Newest vs Oldest first
  it('9. sorts runs chronologically by newest and oldest first', () => {
    const runs = mockHistoryData.map(historyItemToProductionRun);

    const newest = filterAndSortRuns(runs, '', 'all', 'newest');
    expect(newest[0].jobId).toBe('run-i2v-004'); // 08:30:00Z

    const oldest = filterAndSortRuns(runs, '', 'all', 'oldest');
    expect(oldest[0].jobId).toBe('run-image-001'); // 08:00:00Z
  });

  // 10. UI: History panel renders search bar and operational metrics
  it('10. renders operational metrics bar and search controls in UI', async () => {
    render(<App />);

    await waitFor(() => {
      expect(screen.getByText('Generation History')).toBeInTheDocument();
    });

    // Check Metrics Bar
    expect(screen.getByTestId('production-metrics-bar')).toBeInTheDocument();
    expect(screen.getByText('TOTAL RUNS')).toBeInTheDocument();
    expect(screen.getByText('SUCCESS RATE')).toBeInTheDocument();
    expect(screen.getByText('75.0%')).toBeInTheDocument();

    // Check Search Input & Filter Chips
    expect(screen.getByTestId('history-search-input')).toBeInTheDocument();
    expect(screen.getByTestId('history-filter-chips')).toBeInTheDocument();
  });

  // 11. UI: Search input filters rendered cards in DOM
  it('11. typing into search input interactively filters history items in DOM', async () => {
    render(<App />);

    await waitFor(() => {
      expect(screen.getByText('Cinematic cybernetic control station in obsidian mist')).toBeInTheDocument();
    });

    const searchInput = screen.getByTestId('history-search-input');
    fireEvent.change(searchInput, { target: { value: 'neon metropolis' } });

    // Matching card should remain visible
    expect(screen.getByText('Aerial flight over neon metropolis grid')).toBeInTheDocument();
    // Non-matching card should disappear
    expect(screen.queryByText('Cinematic cybernetic control station in obsidian mist')).not.toBeInTheDocument();
  });

  // 12. UI: Filter chips narrow displayed cards
  it('12. clicking filter chip updates visible items', async () => {
    render(<App />);

    await waitFor(() => {
      expect(screen.getByTestId('history-filter-video')).toBeInTheDocument();
    });

    // Click 'Video' filter chip
    fireEvent.click(screen.getByTestId('history-filter-video'));

    expect(screen.getByText('Aerial flight over neon metropolis grid')).toBeInTheDocument();
    expect(screen.queryByText('Cinematic cybernetic control station in obsidian mist')).not.toBeInTheDocument();
  });

  // 13. UI: Inspect button opens RunDetailInspector
  it('13. clicking inspect button opens RunDetailInspector modal', async () => {
    render(<App />);

    await waitFor(() => {
      expect(screen.getByTestId('inspect-run-run-image-001')).toBeInTheDocument();
    });

    fireEvent.click(screen.getByTestId('inspect-run-run-image-001'));

    // Inspector dialog must open
    expect(await screen.findByTestId('run-detail-inspector')).toBeInTheDocument();
    expect(screen.getByText('RUN INTELLIGENCE & TELEMETRY')).toBeInTheDocument();
    expect(screen.getByTestId('lifecycle-timeline')).toBeInTheDocument();
    expect(screen.getByTestId('run-detail-prompt')).toHaveTextContent('Cinematic cybernetic control station in obsidian mist');
  });

  // 14. UI: Run detail displays truthful provider, model, and cost telemetry
  it('14. run detail modal shows truthful provider, model, and cost telemetry', async () => {
    render(<App />);

    await waitFor(() => {
      expect(screen.getByTestId('inspect-run-run-image-001')).toBeInTheDocument();
    });

    fireEvent.click(screen.getByTestId('inspect-run-run-image-001'));

    const telemetryBox = await screen.findByTestId('run-telemetry-box');
    expect(telemetryBox).toHaveTextContent('together');
    expect(telemetryBox).toHaveTextContent('FLUX 1.1 Pro');
    expect(telemetryBox).toHaveTextContent('$0.0450');
  });

  // 15. UI: Failed run detail shows failure reason and error badge
  it('15. failed run detail modal surfaces error diagnostics clearly', async () => {
    render(<App />);

    await waitFor(() => {
      expect(screen.getByTestId('inspect-run-run-failed-003')).toBeInTheDocument();
    });

    fireEvent.click(screen.getByTestId('inspect-run-run-failed-003'));

    expect(await screen.findByTestId('run-failure-notice')).toBeInTheDocument();
    expect(screen.getByText(/Provider rate limit exceeded/i)).toBeInTheDocument();
  });

  // 16. Reproduce: Restores historical parameters to console without auto-execution
  it('16. Reproduce parameters restores prompt, mode, and settings into console WITHOUT executing', async () => {
    render(<App />);

    await waitFor(() => {
      expect(screen.getByTestId('inspect-run-run-video-002')).toBeInTheDocument();
    });

    // Initial check: zero submissions
    expect(submittedPayloads).toHaveLength(0);

    // Open inspector for video run
    fireEvent.click(screen.getByTestId('inspect-run-run-video-002'));

    // Click Reproduce button
    const reproduceBtn = await screen.findByTestId('run-reproduce-btn');
    fireEvent.click(reproduceBtn);

    // Console prompt input must now contain the historical prompt
    const promptInput = screen.getByLabelText(/Prompt/i);
    expect(promptInput).toHaveValue('Aerial flight over neon metropolis grid');

    // CRITICAL REQUIREMENT: Must NOT have auto-executed generation!
    expect(submittedPayloads).toHaveLength(0);
  });

  // 17. Active vs History: Selecting history does not stop active job polling
  it('17. selecting historical run does not stop or corrupt active running job', async () => {
    render(<App />);

    await waitFor(() => {
      expect(screen.getByLabelText(/Prompt/i)).toBeInTheDocument();
    });

    // Start an active generation
    const promptInput = screen.getByLabelText(/Prompt/i);
    fireEvent.change(promptInput, { target: { value: 'New active generation' } });

    const generateBtn = screen.getByTestId('generate-button');
    fireEvent.click(generateBtn);

    // Wait for active generation state in CommandCore
    await waitFor(() => {
      expect(screen.getByTestId('core-state-label')).toHaveTextContent(/SYNTHESIZING|PROCESSING/i);
    });

    // Click on history item card while active job is running
    const historyCard = screen.getByTestId('history-item-run-image-001');
    fireEvent.click(historyCard);

    // Active generation state must NOT be wiped or replaced by historical completed item
    expect(screen.getByTestId('core-state-label')).toHaveTextContent(/SYNTHESIZING|PROCESSING/i);
  });

  // 18. Retry vs Reproduce: Retry re-executes immutable payload, whereas reproduce only populates form
  it('18. distinguishes retry from reproduce behavior', async () => {
    let submissionCount = 0;
    (globalThis.fetch as any).mockImplementation((url: string, init?: RequestInit) => {
      const urlStr = url.toString();
      if (urlStr.includes('/health')) return Promise.resolve({ ok: true, json: () => Promise.resolve({ status: 'healthy', checks: { postgres: 'ok' } }) });
      if (urlStr.includes('/creator/capabilities')) return Promise.resolve({ ok: true, json: () => Promise.resolve(mockManifest) });
      if (urlStr.includes('/creator/history')) return Promise.resolve({ ok: true, json: () => Promise.resolve(mockHistoryData) });
      if (urlStr.includes('/creator/generate')) {
        submissionCount++;
        const body = JSON.parse((init?.body as string) || '{}');
        submittedPayloads.push(body);
        if (submissionCount === 1) {
          return Promise.resolve({
            ok: true,
            json: () => Promise.resolve({
              job_id: 'job-stage6-retry',
              workflow_run_id: 'wf-retry',
              status: 'failed',
              failure_reason: 'GPU out of memory',
              generation_type: 'image',
              prompt: body.prompt,
              total_cost_usd: 0,
              output: {},
            }),
          });
        }
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve({
            job_id: 'job-stage6-retry-ok',
            workflow_run_id: 'wf-retry-ok',
            status: 'completed',
            generation_type: 'image',
            prompt: body.prompt,
            total_cost_usd: 0,
            output: {},
          }),
        });
      }
      return Promise.resolve({ ok: true, json: () => Promise.resolve({}) });
    });

    render(<App />);

    await waitFor(() => {
      expect(screen.getByLabelText(/Prompt/i)).toBeInTheDocument();
    });

    // Enter prompt and execute
    const promptInput = screen.getByLabelText(/Prompt/i);
    fireEvent.change(promptInput, { target: { value: 'Prompt to fail and retry' } });

    fireEvent.click(screen.getByTestId('generate-button'));

    // Wait for failure
    await waitFor(() => {
      expect(screen.getByText(/GPU out of memory/i)).toBeInTheDocument();
    });

    // Modifying form prompt after failure
    fireEvent.change(promptInput, { target: { value: 'Edited prompt in form' } });

    // Click Retry
    const retryBtn = screen.getByTestId('job-retry-button');
    fireEvent.click(retryBtn);

    // Retry must use original immutable snapshot, NOT the edited prompt
    expect(submittedPayloads[submittedPayloads.length - 1].prompt).toBe('Prompt to fail and retry');
  });

  // 19. Security: No sensitive tokens, API keys, or credentials rendered
  it('19. does not render API keys, auth tokens, or provider secrets in run details', async () => {
    localStorage.setItem('arya_api_key', 'secret_production_key_xyz123');

    render(<App />);

    await waitFor(() => {
      expect(screen.getByTestId('inspect-run-run-image-001')).toBeInTheDocument();
    });

    fireEvent.click(screen.getByTestId('inspect-run-run-image-001'));

    await waitFor(() => {
      expect(screen.getByTestId('run-detail-inspector')).toBeInTheDocument();
    });

    // Verify secret API key is nowhere in inspector text
    const modalContent = screen.getByTestId('run-detail-inspector').textContent || '';
    expect(modalContent).not.toContain('secret_production_key_xyz123');
    expect(modalContent).not.toContain('Bearer');
  });

  // 20. Accessibility: Inspector closes on Escape key press
  it('20. closes run detail inspector when user presses Escape key', async () => {
    render(<App />);

    await waitFor(() => {
      expect(screen.getByTestId('inspect-run-run-image-001')).toBeInTheDocument();
    });

    fireEvent.click(screen.getByTestId('inspect-run-run-image-001'));
    expect(await screen.findByTestId('run-detail-inspector')).toBeInTheDocument();

    // Press Escape
    fireEvent.keyDown(window, { key: 'Escape', code: 'Escape' });

    await waitFor(() => {
      expect(screen.queryByTestId('run-detail-inspector')).not.toBeInTheDocument();
    });
  });
});
