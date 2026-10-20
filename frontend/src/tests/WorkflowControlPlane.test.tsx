import React from 'react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { App } from '../App';
import {
  ApprovalCheckpointItem,
  LearningFeedbackItem,
  LineageResponse,
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
    artifacts: {
      video_path: '/storage/videos/quantum_computing_v1.mp4',
      thumbnail_path: '/storage/thumbnails/quantum_computing_thumb.png',
      audio_path: '/storage/audio/quantum_computing_voice.mp3',
      script_content: 'Hook: Imagine computing millions of possibilities in a split second.\nBody: Superposition enables qubits to process simultaneously.',
      storyboard: { shots: [{ shot: 1, prompt: 'Neon circuit glowing' }] },
      images: ['/storage/images/shot_1.png', '/storage/images/shot_2.png'],
      metadata: { target_duration: 30 },
    },
  },
  {
    id: 'run-uuid-002',
    project_id: 'proj-uuid-111',
    topic: 'Top 5 AI Code Editors',
    mode: 'assisted',
    status: 'pending',
    current_stage: 'created',
    total_cost_usd: 0.0,
    started_at: null,
    completed_at: null,
    failure_reason: null,
    created_at: '2026-09-25T11:00:00Z',
    updated_at: '2026-09-25T11:00:00Z',
    artifacts: null,
  },
];

const mockApprovalCheckpoint: ApprovalCheckpointItem = {
  id: 'cp-uuid-999',
  workflow_run_id: 'run-uuid-001',
  stage: 'script',
  reference_table: 'scripts',
  reference_id: 'script-ref-1',
  action: null,
  reviewer_notes: null,
  decided_at: null,
  created_at: '2026-09-25T10:01:00Z',
  updated_at: '2026-09-25T10:01:00Z',
  review_content: {
    type: 'script',
    content: 'Hook: Imagine computing millions of possibilities in a split second.\nBody: Superposition enables qubits to process simultaneously.',
    word_count: 18,
    validation_notes: 'High hook score (88)',
  },
};

const mockLearningFeedback: LearningFeedbackItem[] = [
  {
    id: 'learn-001',
    category: 'script',
    insight: 'Questions in first 3 seconds boost retention by 28%',
    confidence: 0.88,
    based_on_video_count: 14,
    is_active: true,
    created_at: '2026-09-25T08:00:00Z',
    updated_at: '2026-09-25T08:00:00Z',
  },
  {
    id: 'learn-002',
    category: 'thumbnail',
    insight: 'High contrast neon text on dark background increases CTR by 15%',
    confidence: 0.76,
    based_on_video_count: 9,
    is_active: true,
    created_at: '2026-09-25T08:30:00Z',
    updated_at: '2026-09-25T08:30:00Z',
  },
];

describe('AryaOS Slice 9 Frontend Workflow Control Plane', () => {
  let createdRunPayload: any = null;
  let executedRunId: string | null = null;
  let decidedCheckpointPayload: any = null;
  let simulate409Conflict = false;

  beforeEach(() => {
    vi.resetAllMocks();
    createdRunPayload = null;
    executedRunId = null;
    decidedCheckpointPayload = null;
    simulate409Conflict = false;

    // Clipboard mock
    Object.assign(navigator, {
      clipboard: {
        writeText: vi.fn().mockResolvedValue(undefined),
      },
    });

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

      // Execute run endpoint POST /workflow-runs/{id}/execute
      if (urlStr.includes('/execute') && init?.method === 'POST') {
        const parts = urlStr.split('/workflow-runs/')[1].split('/execute');
        executedRunId = parts[0];
        return Promise.resolve({
          ok: true,
          json: () =>
            Promise.resolve({
              workflow_run_id: executedRunId,
              status: 'running',
              current_stage: 'created',
            }),
        });
      }

      // Create workflow run POST /workflow-runs/
      if (urlStr.includes('/workflow-runs') && init?.method === 'POST') {
        createdRunPayload = JSON.parse((init?.body as string) || '{}');
        return Promise.resolve({
          ok: true,
          json: () =>
            Promise.resolve({
              workflow_run_id: 'run-uuid-003',
              status: urlStr.includes('execute=true') ? 'running' : 'pending',
              current_stage: 'created',
            }),
        });
      }

      // Checkpoint decide endpoint POST /approvals/{id}/decide
      if (urlStr.includes('/approvals/') && urlStr.includes('/decide') && init?.method === 'POST') {
        if (simulate409Conflict) {
          return Promise.resolve({
            ok: false,
            status: 409,
            json: () => Promise.resolve({ detail: 'Checkpoint has already been decided: approve' }),
            text: () => Promise.resolve('Conflict: Checkpoint has already been decided'),
          });
        }
        decidedCheckpointPayload = JSON.parse((init?.body as string) || '{}');
        return Promise.resolve({
          ok: true,
          json: () =>
            Promise.resolve({
              ...mockApprovalCheckpoint,
              action: decidedCheckpointPayload.action,
              reviewer_notes: decidedCheckpointPayload.reviewer_notes,
              decided_at: '2026-09-25T12:00:00Z',
            }),
        });
      }

      // Pending approvals GET /approvals/pending/{run_id}
      if (urlStr.includes('/approvals/pending/')) {
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve([mockApprovalCheckpoint]),
        });
      }

      // Learning feedback GET /learning/feedback
      if (urlStr.includes('/learning/feedback')) {
        if (urlStr.includes('category=script')) {
          return Promise.resolve({
            ok: true,
            json: () => Promise.resolve([mockLearningFeedback[0]]),
          });
        }
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve(mockLearningFeedback),
        });
      }

      // Workflow run detail GET /workflow-runs/{id}
      if (urlStr.includes('/workflow-runs/run-uuid-001')) {
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve(mockWorkflowRuns[0]),
        });
      }

      if (urlStr.includes('/workflow-runs/run-uuid-002')) {
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve(mockWorkflowRuns[1]),
        });
      }

      if (urlStr.includes('/workflow-runs/run-uuid-003')) {
        return Promise.resolve({
          ok: true,
          json: () =>
            Promise.resolve({
              id: 'run-uuid-003',
              project_id: createdRunPayload?.project_id || 'proj-uuid-111',
              topic: createdRunPayload?.topic || 'Autonomous AI Discovery',
              mode: createdRunPayload?.mode || 'assisted',
              status: 'running',
              current_stage: 'created',
              total_cost_usd: 0.0,
              started_at: '2026-09-25T12:00:00Z',
              completed_at: null,
              failure_reason: null,
              created_at: '2026-09-25T12:00:00Z',
              updated_at: '2026-09-25T12:00:00Z',
              artifacts: null,
            }),
        });
      }

      if (urlStr.includes('/lineage/')) {
        return Promise.resolve({
          ok: true,
          json: () =>
            Promise.resolve({
              workflow_run_id: 'run-uuid-001',
              topic: 'Future of Quantum Computing',
              status: 'completed',
              current_stage: 'learning_updated',
              total_cost_usd: 0.125,
              trace: [],
            }),
        });
      }

      // Workflow runs list GET /workflow-runs
      if (urlStr.includes('/workflow-runs')) {
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve(mockWorkflowRuns),
        });
      }

      return Promise.resolve({
        ok: true,
        json: () => Promise.resolve({}),
      });
    });
  });

  // 1. Workflow Launcher Tests
  it('1. launches a new workflow run from modal and initiates execution', async () => {
    render(<App />);

    // Navigate to Pipelines & Runs
    fireEvent.click(screen.getByRole('button', { name: /Pipelines & Runs/i }));

    await waitFor(() => {
      expect(screen.getByRole('button', { name: /Launch Pipeline/i })).toBeInTheDocument();
    });

    // Click Launch Pipeline to open launcher modal
    fireEvent.click(screen.getByRole('button', { name: /Launch Pipeline/i }));

    expect(screen.getByRole('heading', { name: /Launch Workflow Pipeline/i })).toBeInTheDocument();

    // Fill in topic
    const topicInput = screen.getByLabelText(/Topic \/ Concept Title/i);
    fireEvent.change(topicInput, { target: { value: 'Autonomous AI Agent Breakthrough' } });

    // Select mode
    const modeSelect = screen.getByLabelText(/Execution Mode/i);
    fireEvent.change(modeSelect, { target: { value: 'autonomous' } });

    // Submit form
    const launchSubmitBtn = screen.getByRole('button', { name: /Launch & Execute/i });
    fireEvent.click(launchSubmitBtn);

    await waitFor(() => {
      expect(createdRunPayload).not.toBeNull();
      expect(createdRunPayload.topic).toBe('Autonomous AI Agent Breakthrough');
      expect(createdRunPayload.mode).toBe('autonomous');
    });
  });

  // 2. Unexecuted Pending Run Action
  it('2. provides Execute Run action for pending workflows', async () => {
    render(<App />);

    fireEvent.click(screen.getByRole('button', { name: /Pipelines & Runs/i }));

    await waitFor(() => {
      expect(screen.getByText('Top 5 AI Code Editors')).toBeInTheDocument();
    });

    // Inspect the pending run (run-uuid-002)
    const inspectButtons = screen.getAllByRole('button', { name: /Inspect/i });
    fireEvent.click(inspectButtons[1]);

    await waitFor(() => {
      expect(screen.getByText(/Workflow Ready to Execute/i)).toBeInTheDocument();
      expect(screen.getByRole('button', { name: /Execute Run/i })).toBeInTheDocument();
    });

    // Click execute
    fireEvent.click(screen.getByRole('button', { name: /Execute Run/i }));

    await waitFor(() => {
      expect(executedRunId).toBe('run-uuid-002');
    });
  });

  // 3. Artifacts Inspection & Script Copying
  it('3. renders produced workflow artifacts and allows copying script content', async () => {
    render(<App />);

    fireEvent.click(screen.getByRole('button', { name: /Pipelines & Runs/i }));

    await waitFor(() => {
      expect(screen.getByText('Future of Quantum Computing')).toBeInTheDocument();
    });

    // Inspect run with artifacts (run-uuid-001)
    const inspectButtons = screen.getAllByRole('button', { name: /Inspect/i });
    fireEvent.click(inspectButtons[0]);

    await waitFor(() => {
      expect(screen.getByRole('heading', { name: /Produced Workflow Artifacts/i })).toBeInTheDocument();
      expect(screen.getByText(/Generated Production Script/i)).toBeInTheDocument();
      expect(screen.getByText(/Master Video Asset/i)).toBeInTheDocument();
      expect(screen.getByText(/High-CTR Thumbnail/i)).toBeInTheDocument();
      expect(screen.getByText(/Master Audio Track/i)).toBeInTheDocument();
    });

    // Verify Copy Script button
    const copyBtn = screen.getByRole('button', { name: /Copy Script/i });
    expect(copyBtn).toBeInTheDocument();

    fireEvent.click(copyBtn);

    expect(navigator.clipboard.writeText).toHaveBeenCalledWith(
      expect.stringContaining('Imagine computing millions of possibilities')
    );

    await waitFor(() => {
      expect(screen.getByText(/Copied!/i)).toBeInTheDocument();
    });
  });

  // 4. Human Approval Checkpoint Console & Decision Submission
  it('4. displays approval checkpoints and submits human review decisions', async () => {
    render(<App />);

    fireEvent.click(screen.getByRole('button', { name: /Pipelines & Runs/i }));

    await waitFor(() => {
      expect(screen.getByText('Future of Quantum Computing')).toBeInTheDocument();
    });

    const inspectButtons = screen.getAllByRole('button', { name: /Inspect/i });
    fireEvent.click(inspectButtons[0]);

    await waitFor(() => {
      expect(screen.getByRole('heading', { name: /Human Approval Checkpoint/i })).toBeInTheDocument();
      expect(screen.getByText(/Reviewable Asset Content:/i)).toBeInTheDocument();
      expect(screen.getByRole('button', { name: /Approve/i })).toBeInTheDocument();
      expect(screen.getByRole('button', { name: /Reject/i })).toBeInTheDocument();
    });

    // Add reviewer notes
    const notesInput = screen.getByPlaceholderText(/Add guidance or revision requests.../i);
    fireEvent.change(notesInput, { target: { value: 'Hook looks strong, proceed to generation' } });

    // Click Approve
    const approveBtn = screen.getByRole('button', { name: /Approve/i });
    fireEvent.click(approveBtn);

    await waitFor(() => {
      expect(decidedCheckpointPayload).not.toBeNull();
      expect(decidedCheckpointPayload.action).toBe('approve');
      expect(decidedCheckpointPayload.reviewer_notes).toBe('Hook looks strong, proceed to generation');
    });
  });

  // 5. Handling 409 Conflict Gracefully
  it('5. gracefully handles 409 conflict when approval checkpoint is already decided', async () => {
    simulate409Conflict = true;

    render(<App />);

    fireEvent.click(screen.getByRole('button', { name: /Pipelines & Runs/i }));

    await waitFor(() => {
      expect(screen.getByText('Future of Quantum Computing')).toBeInTheDocument();
    });

    const inspectButtons = screen.getAllByRole('button', { name: /Inspect/i });
    fireEvent.click(inspectButtons[0]);

    await waitFor(() => {
      expect(screen.getByRole('button', { name: /Approve/i })).toBeInTheDocument();
    });

    const approveBtn = screen.getByRole('button', { name: /Approve/i });
    fireEvent.click(approveBtn);

    await waitFor(() => {
      expect(screen.getByText(/Checkpoint has already been decided/i)).toBeInTheDocument();
    });
  });

  // 6. Dedicated Learning Loop View & Instance-Wide Disclaimer
  it('6. navigates to Learning Loop view, displays instance-wide disclaimer, and filters feedback', async () => {
    render(<App />);

    // Click Learning Loop navigation tab
    const learningTab = screen.getByRole('button', { name: /Learning Loop/i });
    expect(learningTab).toBeInTheDocument();
    fireEvent.click(learningTab);

    // Verify view header and disclaimer notice
    expect(screen.getByRole('heading', { name: /Learning Loop & Performance Intelligence/i })).toBeInTheDocument();
    expect(screen.getByRole('note')).toHaveTextContent(/Learning feedback is currently instance-wide in V1/i);

    // Verify feedback cards rendered
    await waitFor(() => {
      expect(screen.getByText(/Questions in first 3 seconds boost retention by 28%/i)).toBeInTheDocument();
      expect(screen.getByText(/High contrast neon text on dark background increases CTR by 15%/i)).toBeInTheDocument();
      expect(screen.getByText('88%')).toBeInTheDocument();
      expect(screen.getByText('14 videos')).toBeInTheDocument();
    });

    // Test category filter pill
    const scriptFilterBtn = screen.getByRole('button', { name: /Script & Hook/i });
    fireEvent.click(scriptFilterBtn);

    await waitFor(() => {
      expect(screen.getByText(/Questions in first 3 seconds boost retention by 28%/i)).toBeInTheDocument();
    });
  });
});
