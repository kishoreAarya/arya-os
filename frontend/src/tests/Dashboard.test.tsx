import React from 'react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { App } from '../App';
import {
  LineageResponse,
  PublishingStatusResponse,
  ResearchResponse,
  WorkflowRunItem,
} from '../types/dashboard';

const mockWorkflowRuns: WorkflowRunItem[] = [
  {
    id: 'run-uuid-001',
    project_id: 'proj-uuid-111',
    topic: 'Future of Quantum Computing',
    mode: 'autonomous',
    status: 'completed',
    current_stage: 'learning_updated',
    total_cost_usd: 0.125,
    started_at: '2026-09-25T10:00:00Z',
    completed_at: '2026-09-25T10:03:00Z',
    failure_reason: null,
    created_at: '2026-09-25T10:00:00Z',
    updated_at: '2026-09-25T10:03:00Z',
  },
  {
    id: 'run-uuid-002',
    project_id: 'proj-uuid-111',
    topic: 'Top 5 AI Code Editors',
    mode: 'assisted',
    status: 'failed',
    current_stage: 'video_generated',
    total_cost_usd: 0.045,
    started_at: '2026-09-25T11:00:00Z',
    completed_at: '2026-09-25T11:01:30Z',
    failure_reason: 'Kling API upstream timeout (504 Gateway)',
    created_at: '2026-09-25T11:00:00Z',
    updated_at: '2026-09-25T11:01:30Z',
  },
];

const mockLineage: LineageResponse = {
  workflow_run_id: 'run-uuid-001',
  topic: 'Future of Quantum Computing',
  status: 'completed',
  current_stage: 'learning_updated',
  total_cost_usd: 0.125,
  trace: [
    {
      artifact_type: 'script',
      reference_table: 'scripts',
      reference_id: 'script-ref-1',
      version: 1,
      created_at: '2026-09-25T10:01:00Z',
      quality_scores: [
        { dimension: 'hook', score: 88, scored_by: 'StoryValidator' },
        { dimension: 'pacing', score: 92, scored_by: 'StoryValidator' },
      ],
      generation_attempts: [
        {
          attempt_number: 1,
          succeeded: true,
          failure_reason: null,
          provider_id: 'openrouter/claude-3.5',
          cost_usd: 0.015,
        },
      ],
      approval: [],
    },
    {
      artifact_type: 'video',
      reference_table: 'videos',
      reference_id: 'video-ref-1',
      version: 1,
      created_at: '2026-09-25T10:02:30Z',
      quality_scores: [
        { dimension: 'video_quality', score: 85, scored_by: 'VideoValidator' },
      ],
      generation_attempts: [
        {
          attempt_number: 1,
          succeeded: true,
          failure_reason: null,
          provider_id: 'kling/v1.6',
          cost_usd: 0.095,
        },
      ],
      approval: [],
    },
  ],
};

const mockTrends: ResearchResponse = {
  source: 'multi_source',
  query: { topic: 'AI video tools', limit: 10, time_range: 'month' },
  total_results: 2,
  retrieved_at: '2026-09-25T10:15:00Z',
  results: [
    {
      topic: 'OpenAI Sora API Release',
      search_volume_or_signal: 'Breakout query +450% interest',
      relevance: 0.94,
      freshness: '2h ago',
      competition: 'Low',
      source: 'Google Trends',
      timestamp: '2026-09-25T08:15:00Z',
      confidence: 0.92,
      opportunity_score: 89,
    },
    {
      topic: 'Kling 1.6 vs Runway Gen-3 Shootout',
      search_volume_or_signal: '128 comments on r/artificial',
      relevance: 0.88,
      freshness: '4h ago',
      competition: 'Medium',
      source: 'Reddit',
      timestamp: '2026-09-25T06:15:00Z',
      confidence: 0.86,
      opportunity_score: 82,
    },
  ],
};

const mockPublishingStatus: PublishingStatusResponse = {
  platform: 'postiz',
  base_url: 'https://postiz.internal.local',
  configured: true,
  reachable: true,
  status: 'connected',
  error: null,
  connected_channels: 2,
  channels: [
    { id: 'ch-yt-01', name: 'Tech Insights YouTube', identifier: 'youtube' },
    { id: 'ch-tt-02', name: 'Arya Reels TikTok', identifier: 'tiktok' },
  ],
};

describe('AryaOS Slice 7 Multi-View Navigation & Dashboard', () => {
  let lastPublishBody: any = null;

  beforeEach(() => {
    vi.resetAllMocks();
    lastPublishBody = null;

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
          json: () =>
            Promise.resolve({
              generation_types: [{ id: 'image', label: 'Image', description: 'Image generation' }],
              aspect_ratios: [{ id: '16:9', label: '16:9', dimensions: '1344x768' }],
              resolutions: [{ id: '1024x1024', label: '1024x1024' }],
              durations: [{ value: 5, label: '5s' }],
              models: { image: [{ id: 'flux', name: 'Flux', provider: 'fal', default: true, cost_tier: 1, configured: true, start_frame: false, end_frame: false }] },
            }),
        });
      }

      if (urlStr.includes('/creator/history')) {
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve([]),
        });
      }

      if (urlStr.includes('/workflow-runs/run-uuid-001')) {
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve(mockWorkflowRuns[0]),
        });
      }

      if (urlStr.includes('/lineage/run-uuid-001')) {
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve(mockLineage),
        });
      }

      if (urlStr.includes('/workflow-runs')) {
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve(mockWorkflowRuns),
        });
      }

      if (urlStr.includes('/research/trends') || urlStr.includes('/research/reddit')) {
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve(mockTrends),
        });
      }

      if (urlStr.includes('/publishing/status')) {
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve(mockPublishingStatus),
        });
      }

      if (urlStr.includes('/publishing/publish')) {
        lastPublishBody = JSON.parse((init?.body as string) || '{}');
        return Promise.resolve({
          ok: true,
          json: () =>
            Promise.resolve({
              success: true,
              platform: 'postiz',
              published_content_id: 'sim-post-123',
              publish_status: 'draft',
              is_dry_run: lastPublishBody.dry_run,
            }),
        });
      }

      return Promise.resolve({
        ok: true,
        json: () => Promise.resolve({}),
      });
    });
  });

  // 1. Navigation Tests
  it('1. defaults to Creator Studio view and renders navigation tabs', async () => {
    render(<App />);

    expect(screen.getByRole('button', { name: /Creator Studio/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Pipelines & Runs/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Research & Trends/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Publishing/i })).toBeInTheDocument();

    // Verify Creator Studio prompt input is in document initially
    expect(screen.getByLabelText(/Prompt/i)).toBeInTheDocument();
  });

  it('2. switches view to Pipelines & Runs when tab clicked', async () => {
    render(<App />);

    const pipelinesTab = screen.getByRole('button', { name: /Pipelines & Runs/i });
    fireEvent.click(pipelinesTab);

    expect(screen.getByRole('heading', { name: /Pipelines & Workflow Runs/i })).toBeInTheDocument();
    expect(screen.getByText(/Execution Log/i)).toBeInTheDocument();
  });

  it('3. switches view to Research & Trends when tab clicked', async () => {
    render(<App />);

    const researchTab = screen.getByRole('button', { name: /Research & Trends/i });
    fireEvent.click(researchTab);

    expect(screen.getByRole('heading', { name: /Research & Trend Intelligence/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Discover Trends/i })).toBeInTheDocument();
  });

  it('4. switches view to Publishing when tab clicked', async () => {
    render(<App />);

    const pubTab = screen.getByRole('button', { name: /Publishing/i });
    fireEvent.click(pubTab);

    expect(screen.getByRole('heading', { name: /Publishing & Distribution Center/i })).toBeInTheDocument();
    expect(screen.getByText(/Connected Publishing Channels/i)).toBeInTheDocument();
  });

  // 2. Pipelines & Runs Tests
  it('5. fetches and renders workflow runs list with status badges and costs', async () => {
    render(<App />);

    fireEvent.click(screen.getByRole('button', { name: /Pipelines & Runs/i }));

    await waitFor(() => {
      expect(screen.getByText('Future of Quantum Computing')).toBeInTheDocument();
      expect(screen.getByText('Top 5 AI Code Editors')).toBeInTheDocument();
    });

    expect(screen.getByText(/Completed/i)).toBeInTheDocument();
    expect(screen.getByText(/Failed/i)).toBeInTheDocument();
    expect(screen.getByText('$0.1250')).toBeInTheDocument();
  });

  it('6. selecting a run loads its details and lineage quality breakdown', async () => {
    render(<App />);

    fireEvent.click(screen.getByRole('button', { name: /Pipelines & Runs/i }));

    await waitFor(() => {
      expect(screen.getByText('Future of Quantum Computing')).toBeInTheDocument();
    });

    const inspectButtons = screen.getAllByRole('button', { name: /Inspect/i });
    fireEvent.click(inspectButtons[0]);

    await waitFor(() => {
      expect(screen.getByRole('heading', { name: /Pipeline Stage Stepper/i })).toBeInTheDocument();
      expect(screen.getByRole('heading', { name: /Artifact Lineage & Quality Scores/i })).toBeInTheDocument();
    });

    expect(screen.getByText(/hook: 88/i)).toBeInTheDocument();
    expect(screen.getByText(/pacing: 92/i)).toBeInTheDocument();
    expect(screen.getByText(/openrouter\/claude-3.5/i)).toBeInTheDocument();
  });

  // 3. Research & Trends Tests
  it('7. queries trend intelligence and displays signal cards', async () => {
    render(<App />);

    fireEvent.click(screen.getByRole('button', { name: /Research & Trends/i }));

    const searchButton = screen.getByRole('button', { name: /Discover Trends/i });
    fireEvent.click(searchButton);

    await waitFor(() => {
      expect(screen.getByText('OpenAI Sora API Release')).toBeInTheDocument();
      expect(screen.getByText('Kling 1.6 vs Runway Gen-3 Shootout')).toBeInTheDocument();
    });

    expect(screen.getByText('Google Trends')).toBeInTheDocument();
    expect(screen.getByText('Reddit')).toBeInTheDocument();
    expect(screen.getAllByText(/Opportunity:/i).length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText('89/100')).toBeInTheDocument();
  });

  // 4. Publishing & Dry-Run Tests
  it('8. renders publishing connectivity status and connected social channels', async () => {
    render(<App />);

    const pubTab = screen.getByRole('button', { name: /Publishing/i });
    fireEvent.click(pubTab);

    await waitFor(() => {
      expect(screen.getByRole('heading', { name: /Publishing & Distribution Center/i })).toBeInTheDocument();
    });

    await waitFor(() => {
      expect(screen.getAllByText('Tech Insights YouTube').length).toBeGreaterThanOrEqual(1);
      expect(screen.getAllByText('Arya Reels TikTok').length).toBeGreaterThanOrEqual(1);
    });

    expect(screen.getByText(/2 Connected/i)).toBeInTheDocument();
    expect(screen.getAllByText(/Reachable/i).length).toBeGreaterThanOrEqual(1);
  });

  it('9. dry-run publish simulation console strictly enforces dry_run: true safeguard', async () => {
    render(<App />);

    const pubTab = screen.getByRole('button', { name: /Publishing/i });
    fireEvent.click(pubTab);

    await waitFor(() => {
      expect(screen.getByRole('heading', { name: /Publishing & Distribution Center/i })).toBeInTheDocument();
    });

    const simulateBtn = screen.getByRole('button', { name: /Simulate Release \(Dry Run\)/i });
    fireEvent.click(simulateBtn);

    await waitFor(() => {
      expect(screen.getByText(/Dry-Run Contract Passed/i)).toBeInTheDocument();
      expect(screen.getByText(/Is Dry Run:/i)).toBeInTheDocument();
    });

    expect(lastPublishBody).not.toBeNull();
    expect(lastPublishBody.dry_run).toBe(true);
  });
});
