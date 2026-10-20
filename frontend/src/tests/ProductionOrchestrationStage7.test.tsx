import React from 'react';
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { App } from '../App';
import {
  deriveSystemState,
  classifyFailure,
  computeOperationalMetrics,
  historyItemToProductionRun,
  ProductionRun,
} from '../types/productionRun';
import { OperationalStrip } from '../components/orchestration/OperationalStrip';
import { JobStatusCard } from '../components/JobStatusCard';
import { RunDetailInspector } from '../components/history/RunDetailInspector';
import { GenerationJob, HistoryItem, CapabilitiesManifest } from '../types/creator';

// Mock manifest
const mockManifest = {
  models: {
    image: [
      { id: 'imagen-3.0-generate-002', name: 'Imagen 3.0', default: true, provider: 'Google Vertex AI', cost_tier: 1, configured: true, start_frame: false, end_frame: false },
      { id: 'flux-1-schnell', name: 'FLUX.1 Schnell', default: false, provider: 'Black Forest Labs', cost_tier: 1, configured: true, start_frame: false, end_frame: false },
    ],
    video: [
      { id: 'veo-2.0-generate-001', name: 'Veo 2.0', default: true, provider: 'Google DeepMind', cost_tier: 2, configured: true, start_frame: true, end_frame: false },
    ],
    image_to_video: [
      { id: 'veo-2.0-i2v-001', name: 'Veo 2.0 I2V', default: true, provider: 'Google DeepMind', cost_tier: 2, configured: true, start_frame: true, end_frame: false },
    ],
  },
  aspect_ratios: [
    { id: '16:9', label: '16:9' },
    { id: '1:1', label: '1:1' },
    { id: '9:16', label: '9:16' },
  ],
  resolutions: [
    { id: '1024x1024', label: '1024x1024' },
    { id: '1920x1080', label: '1920x1080' },
  ],
  durations: [
    { value: 5, label: '5s' },
    { value: 10, label: '10s' },
  ],
} as unknown as CapabilitiesManifest;

describe('AryaOS Stage 7: Production Orchestration, Queue Awareness & Operational Control', () => {
  const originalFetch = window.fetch;

  beforeEach(() => {
    localStorage.clear();
    sessionStorage.clear();
    vi.clearAllMocks();
    vi.useRealTimers();
  });

  afterEach(() => {
    window.fetch = originalFetch;
    vi.restoreAllMocks();
  });

  // =========================================================================
  // 1. SYSTEM OPERATIONAL STATE DERIVATION & TELEMETRY
  // =========================================================================
  describe('1. Truthful System Operational State Derivation', () => {
    it('evaluates to IDLE when system is healthy and no job is active', () => {
      const state = deriveSystemState('healthy', false, undefined, null, 0);
      expect(state).toBe('IDLE');
    });

    it('evaluates to ACTIVE when generation is submitting or job is pending/in_progress', () => {
      expect(deriveSystemState('healthy', true, undefined, null, 0)).toBe('ACTIVE');
      expect(deriveSystemState('healthy', false, 'pending', null, 0)).toBe('ACTIVE');
      expect(deriveSystemState('healthy', false, 'in_progress', null, 0)).toBe('ACTIVE');
    });

    it('evaluates to DEGRADED when backend health is degraded or poll errors occur', () => {
      expect(deriveSystemState('degraded', false, undefined, null, 0)).toBe('DEGRADED');
      expect(deriveSystemState('healthy', false, undefined, null, 2)).toBe('DEGRADED');
    });

    it('evaluates to ERROR when backend health is error, job failed, or submission error exists', () => {
      expect(deriveSystemState('error', false, undefined, null, 0)).toBe('ERROR');
      expect(deriveSystemState('healthy', false, 'failed', null, 0)).toBe('ERROR');
      expect(deriveSystemState('healthy', false, undefined, 'Network submission failed', 0)).toBe('ERROR');
    });
  });

  // =========================================================================
  // 2. FAILURE CLASSIFICATION INTELLIGENCE
  // =========================================================================
  describe('2. Failure Intelligence & Classification', () => {
    it('classifies submission, timeout, validation, network, and provider failures correctly', () => {
      expect(classifyFailure('Failed to submit generation request')).toBe('SUBMISSION_FAILURE');
      expect(classifyFailure('Request timed out after 30000ms')).toBe('TIMEOUT');
      expect(classifyFailure('Invalid aspect ratio 21:9 specified')).toBe('VALIDATION_FAILURE');
      expect(classifyFailure('Failed to fetch from backend server')).toBe('NETWORK_FAILURE');
      expect(classifyFailure('Upstream provider quota exceeded')).toBe('PROVIDER_FAILURE');
      expect(classifyFailure('CUDA out of memory')).toBe('PROVIDER_FAILURE');
      expect(classifyFailure('Something completely unspecified happened')).toBe('UNKNOWN');
      expect(classifyFailure(undefined)).toBe('UNKNOWN');
    });
  });

  // =========================================================================
  // 3. OPERATIONAL METRICS & TRUTHFUL COST CALCULATIONS
  // =========================================================================
  describe('3. Operational Metrics & Cost Aggregation', () => {
    it('aggregates total runs, success rate, queued runs, and cost by provider/model without fabrication', () => {
      const runs: ProductionRun[] = [
        {
          id: 'run-1',
          jobId: 'run-1',
          mode: 'image',
          prompt: 'A prompt 1',
          status: 'completed',
          costUsd: 0.04,
          requestedProvider: 'Google Vertex AI',
          actualProvider: 'Google Vertex AI',
          requestedModel: 'imagen-3.0-generate-002',
          actualModel: 'imagen-3.0-generate-002',
          parameters: {},
          createdAt: '2026-09-27T00:00:00Z',
        },
        {
          id: 'run-2',
          jobId: 'run-2',
          mode: 'video',
          prompt: 'A prompt 2',
          status: 'completed',
          costUsd: 0.20,
          requestedProvider: 'Google DeepMind',
          actualProvider: 'Google DeepMind',
          requestedModel: 'veo-2.0-generate-001',
          actualModel: 'veo-2.0-generate-001',
          parameters: {},
          createdAt: '2026-09-27T00:00:00Z',
        },
        {
          id: 'run-3',
          jobId: 'run-3',
          mode: 'image',
          prompt: 'A prompt 3',
          status: 'failed',
          costUsd: undefined, // no cost incurred
          requestedProvider: 'Black Forest Labs',
          actualProvider: undefined,
          failureReason: 'Rate limit exceeded',
          failureCategory: 'PROVIDER_FAILURE',
          parameters: {},
          createdAt: '2026-09-27T00:00:00Z',
        },
        {
          id: 'run-4',
          jobId: 'run-4',
          mode: 'image',
          prompt: 'A prompt 4',
          status: 'pending',
          parameters: {},
          createdAt: '2026-09-27T00:00:00Z',
        },
      ];

      const metrics = computeOperationalMetrics(runs);
      expect(metrics.totalRuns).toBe(4);
      expect(metrics.successfulRuns).toBe(2);
      expect(metrics.failedRuns).toBe(1);
      expect(metrics.queuedRuns).toBe(1);
      expect(metrics.successRate).toBe(67);
      expect(metrics.totalCostUsd).toBeCloseTo(0.24, 4);

      // Cost grouping
      expect(metrics.costByProvider['Google Vertex AI']).toBeCloseTo(0.04, 4);
      expect(metrics.costByProvider['Google DeepMind']).toBeCloseTo(0.20, 4);
      expect(metrics.costByModel['imagen-3.0-generate-002']).toBeCloseTo(0.04, 4);
    });

    it('maps history item to ProductionRun with requested vs actual provider and model', () => {
      const item: HistoryItem = {
        job_id: 'job-123',
        workflow_run_id: 'wf-123',
        status: 'completed',
        generation_type: 'image',
        prompt: 'Futuristic city',
        requested_provider: 'Google Vertex AI',
        actual_provider: 'Google Cloud Platform',
        requested_model: 'imagen-3.0',
        actual_model: 'imagen-3.0-generate-002',
        total_cost_usd: 0.04,
        created_at: '2026-09-27T04:00:00Z',
      };

      const run = historyItemToProductionRun(item);
      expect(run.id).toBe('wf-123');
      expect(run.jobId).toBe('job-123');
      expect(run.requestedProvider).toBe('Google Vertex AI');
      expect(run.actualProvider).toBe('Google Cloud Platform');
      expect(run.requestedModel).toBe('imagen-3.0');
      expect(run.actualModel).toBe('imagen-3.0-generate-002');
      expect(run.costUsd).toBe(0.04);
    });
  });

  // =========================================================================
  // 4. OPERATIONAL STRIP COMPONENT
  // =========================================================================
  describe('4. OperationalStrip Component', () => {
    it('renders system state, active counts, cost, and truthful cancellation unavailable notice', () => {
      const handleRefresh = vi.fn();
      render(
        <OperationalStrip
          systemState="ACTIVE"
          activeCount={2}
          queuedCount={1}
          processingCount={1}
          failedCount={0}
          totalCostUsd={0.125}
          isRefreshing={false}
          onRefresh={handleRefresh}
          hasActiveJob={true}
        />
      );

      expect(screen.getByTestId('operational-strip')).toBeInTheDocument();
      expect(screen.getByTestId('operational-system-state')).toHaveTextContent('SYS: ACTIVE');
      expect(screen.getByTestId('count-active-runs')).toHaveTextContent('02');
      expect(screen.getByTestId('count-queued-runs')).toHaveTextContent('01');
      expect(screen.getByTestId('count-processing-runs')).toHaveTextContent('01');
      expect(screen.getByTestId('count-failed-runs')).toHaveTextContent('00');
      expect(screen.getByText('$0.1250')).toBeInTheDocument();
      expect(screen.getByTestId('cancellation-badge')).toHaveTextContent('CANCEL: UNAVAILABLE');

      // Click reconcile button
      const reconcileBtn = screen.getByTestId('operational-refresh-btn');
      fireEvent.click(reconcileBtn);
      expect(handleRefresh).toHaveBeenCalledTimes(1);
    });

    it('displays UNAVAILABLE when total cost is 0 and hides cancellation badge when no active job', () => {
      render(
        <OperationalStrip
          systemState="IDLE"
          activeCount={0}
          queuedCount={0}
          processingCount={0}
          failedCount={0}
          totalCostUsd={0}
          isRefreshing={false}
          hasActiveJob={false}
        />
      );

      expect(screen.getByTestId('operational-system-state')).toHaveTextContent('SYS: IDLE');
      expect(screen.getByText('UNAVAILABLE')).toBeInTheDocument();
      expect(screen.queryByTestId('cancellation-badge')).not.toBeInTheDocument();
    });
  });

  // =========================================================================
  // 5. JOB STATUS CARD TELEMETRY & CANCELLATION NOTICE
  // =========================================================================
  describe('5. JobStatusCard Telemetry & Cancellation Status', () => {
    it('surfaces requested and actual provider & model and displays cancellation notice for active job', () => {
      const job = {
        job_id: 'job-active-99',
        workflow_run_id: 'wf-active-99',
        status: 'in_progress',
        generation_type: 'video',
        prompt: 'Cosmic nebula flowing',
        requested_provider: 'Google DeepMind',
        actual_provider: 'Google Vertex AI',
        requested_model: 'veo-2.0',
        actual_model: 'veo-2.0-generate-001',
        total_cost_usd: 0.15,
        current_stage: 'video_generation',
      } as unknown as GenerationJob;

      render(<JobStatusCard job={job} />);

      expect(screen.getByTestId('job-requested-provider')).toHaveTextContent('Google DeepMind');
      expect(screen.getByTestId('job-actual-provider')).toHaveTextContent('Google Vertex AI');
      expect(screen.getByTestId('job-requested-model')).toHaveTextContent('veo-2.0');
      expect(screen.getByTestId('job-actual-model')).toHaveTextContent('veo-2.0-generate-001');
      expect(screen.getByTestId('job-cost-display')).toHaveTextContent('$0.1500');
      expect(screen.getByTestId('job-cancellation-notice')).toHaveTextContent(/CANCELLATION UNAVAILABLE/i);
    });

    it('truthfully displays UNAVAILABLE for missing provider/model/cost values without crashing', () => {
      const job = {
        job_id: 'job-minimal',
        status: 'pending',
        generation_type: 'image',
        prompt: 'Simple prompt',
      } as unknown as GenerationJob;

      render(<JobStatusCard job={job} />);

      expect(screen.getByTestId('job-requested-provider')).toHaveTextContent('UNAVAILABLE');
      expect(screen.getByTestId('job-actual-provider')).toHaveTextContent('UNAVAILABLE');
      expect(screen.getByTestId('job-cost-display')).toHaveTextContent('UNAVAILABLE');
    });
  });

  // =========================================================================
  // 6. RUN DETAIL INSPECTOR & FAILURE INTELLIGENCE
  // =========================================================================
  describe('6. RunDetailInspector Failure Intelligence & Telemetry', () => {
    it('renders failure intelligence box with category, stage, reason, and retry note', () => {
      const failedRun: ProductionRun = {
        id: 'run-failed-77',
        jobId: 'run-failed-77',
        mode: 'image',
        prompt: 'Futuristic hypercar',
        status: 'failed',
        failureReason: 'Upstream provider quota exceeded',
        failureCategory: 'PROVIDER_FAILURE',
        failureStage: 'image_generation',
        requestedProvider: 'Google Vertex AI',
        actualProvider: 'Google Vertex AI',
        requestedModel: 'imagen-3.0',
        actualModel: 'imagen-3.0-generate-002',
        parameters: {
          aspectRatio: '16:9',
          resolution: '1024x1024',
        },
        createdAt: '2026-09-27T00:00:00Z',
      };

      const handleReproduce = vi.fn();
      const handleClose = vi.fn();

      const { unmount } = render(
        <RunDetailInspector
          run={failedRun}
          isOpen={true}
          onClose={handleClose}
          onReproduce={handleReproduce}
        />
      );

      // Verify Failure Intelligence
      expect(screen.getByTestId('failure-intelligence-box')).toBeInTheDocument();
      expect(screen.getByTestId('failure-category')).toHaveTextContent('PROVIDER_FAILURE');
      expect(screen.getByTestId('failure-stage')).toHaveTextContent('image_generation');
      expect(screen.getByTestId('failure-reason')).toHaveTextContent('Upstream provider quota exceeded');

      // Verify Provider & Model Telemetry
      expect(screen.getByTestId('telemetry-requested-provider')).toHaveTextContent('Google Vertex AI');
      expect(screen.getByTestId('telemetry-actual-provider')).toHaveTextContent('Google Vertex AI');
      expect(screen.getByTestId('telemetry-requested-model')).toHaveTextContent('imagen-3.0');
      expect(screen.getByTestId('telemetry-actual-model')).toHaveTextContent('imagen-3.0-generate-002');

      // Verify Reproduce Parameters button
      const reproduceBtn = screen.getByRole('button', { name: /reproduce parameters/i });
      fireEvent.click(reproduceBtn);
      expect(handleReproduce).toHaveBeenCalledWith(failedRun);

      unmount();

      // Verify in-flight run renders truthful cancellation unavailable notice
      const inProgressRun: ProductionRun = {
        ...failedRun,
        status: 'in_progress',
      };
      render(
        <RunDetailInspector
          run={inProgressRun}
          isOpen={true}
          onClose={handleClose}
          onReproduce={handleReproduce}
        />
      );
      expect(screen.getByTestId('inspector-cancellation-status')).toHaveTextContent(/CANCELLATION UNAVAILABLE/i);
    });
  });

  // =========================================================================
  // 7. FULL WORKSTATION INTEGRATION & ACTIVE GENERATION PROTECTION
  // =========================================================================
  describe('7. Workstation Integration & Operational Protection', () => {
    it('preserves active in-flight generation when user clicks on history items', async () => {
      let pollCount = 0;
      window.fetch = vi.fn().mockImplementation((url: string | URL | Request) => {
        const urlStr = typeof url === 'string' ? url : url.toString();

        if (urlStr.endsWith('/creator/capabilities')) {
          return Promise.resolve({
            ok: true,
            status: 200,
            json: async () => mockManifest,
          });
        }

        if (urlStr.endsWith('/creator/history')) {
          return Promise.resolve({
            ok: true,
            status: 200,
            json: async () => [
              {
                job_id: 'job-hist-1',
                status: 'completed',
                generation_type: 'image',
                prompt: 'Historical completed asset',
                asset_url: 'https://cdn.example.com/hist1.png',
                total_cost_usd: 0.04,
                created_at: '2026-09-27T00:00:00Z',
              },
            ],
          });
        }

        if (urlStr.endsWith('/creator/generate')) {
          return Promise.resolve({
            ok: true,
            status: 200,
            json: async () => ({
              job_id: 'job-active-in-flight',
              status: 'in_progress',
              generation_type: 'image',
              prompt: 'Active in-flight prompt',
              current_stage: 'image_generation',
              total_cost_usd: 0.04,
            }),
          });
        }

        if (urlStr.includes('/creator/jobs/job-active-in-flight')) {
          pollCount++;
          return Promise.resolve({
            ok: true,
            status: 200,
            json: async () => ({
              job_id: 'job-active-in-flight',
              status: 'in_progress',
              generation_type: 'image',
              prompt: 'Active in-flight prompt',
              current_stage: 'image_generation',
              total_cost_usd: 0.04,
            }),
          });
        }

        if (urlStr.endsWith('/live') || urlStr.endsWith('/ready')) {
          return Promise.resolve({
            ok: true,
            status: 200,
            json: async () => ({ status: 'healthy', database: 'connected', redis: 'connected' }),
          });
        }

        return Promise.reject(new Error(`Unhandled route: ${urlStr}`));
      });

      render(<App />);

      // Wait for manifest & history to load
      await waitFor(() => {
        expect(screen.getByText('Historical completed asset')).toBeInTheDocument();
      });

      // Initially SYS: IDLE
      expect(screen.getByTestId('operational-system-state')).toHaveTextContent('SYS: IDLE');

      // Submit a new generation
      const promptInput = document.getElementById('promptInput') as HTMLTextAreaElement;
      fireEvent.change(promptInput, { target: { value: 'Active in-flight prompt' } });

      const generateBtn = screen.getByRole('button', { name: /generate image/i });
      fireEvent.click(generateBtn);

      // Verify that system state transitions to ACTIVE
      await waitFor(() => {
        expect(screen.getByTestId('operational-system-state')).toHaveTextContent('SYS: ACTIVE');
        expect(screen.getByTestId('count-active-runs')).toHaveTextContent('01');
      });

      // Verify that active job is displayed
      expect(screen.getByText('Active in-flight prompt')).toBeInTheDocument();

      // Now click on the historical item in the history list
      const histItemBtn = screen.getByText('Historical completed asset');
      fireEvent.click(histItemBtn);

      // ACTIVE GENERATION PROTECTION GUARANTEE:
      // The active job MUST NOT be replaced by the historical item in the creative viewport/status card!
      expect(screen.getByText('Active in-flight prompt')).toBeInTheDocument();
      expect(screen.getByTestId('operational-system-state')).toHaveTextContent('SYS: ACTIVE');
      expect(screen.getByTestId('cancellation-badge')).toHaveTextContent('CANCEL: UNAVAILABLE');
    });

    it('operational reconcile action fetches latest health, manifest, history, and active job', async () => {
      let historyFetchCount = 0;
      window.fetch = vi.fn().mockImplementation((url: string | URL | Request) => {
        const urlStr = typeof url === 'string' ? url : url.toString();

        if (urlStr.endsWith('/creator/capabilities')) {
          return Promise.resolve({
            ok: true,
            status: 200,
            json: async () => mockManifest,
          });
        }

        if (urlStr.endsWith('/creator/history')) {
          historyFetchCount++;
          return Promise.resolve({
            ok: true,
            status: 200,
            json: async () => [],
          });
        }

        if (urlStr.endsWith('/live') || urlStr.endsWith('/ready')) {
          return Promise.resolve({
            ok: true,
            status: 200,
            json: async () => ({ status: 'healthy', database: 'connected', redis: 'connected' }),
          });
        }

        return Promise.reject(new Error(`Unhandled route: ${urlStr}`));
      });

      render(<App />);

      await waitFor(() => {
        expect(screen.getByTestId('operational-strip')).toBeInTheDocument();
      });

      const initialCount = historyFetchCount;
      const reconcileBtn = screen.getByTestId('operational-refresh-btn');
      fireEvent.click(reconcileBtn);

      await waitFor(() => {
        expect(historyFetchCount).toBeGreaterThan(initialCount);
      });
    });
  });
});
