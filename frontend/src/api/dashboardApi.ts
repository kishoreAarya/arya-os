import { getStoredApiKey } from './creatorApi';
import {
  ApprovalCheckpointItem,
  ApprovalDecisionPayload,
  CreateWorkflowRunPayload,
  LearningFeedbackItem,
  LineageResponse,
  PublishingStatusResponse,
  PublishRequest,
  PublishResponse,
  ResearchResponse,
  WorkflowRunCreateResponse,
  WorkflowRunItem,
} from '../types/dashboard';

const getAuthHeaders = (): HeadersInit => {
  const key = getStoredApiKey();
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
  };
  if (key) {
    headers['Authorization'] = `Bearer ${key}`;
  }
  return headers;
};

export async function fetchWorkflowRuns(params?: {
  projectId?: string;
  limit?: number;
  offset?: number;
}): Promise<WorkflowRunItem[]> {
  const query = new URLSearchParams();
  if (params?.limit !== undefined) query.set('limit', String(params.limit));
  if (params?.offset !== undefined) query.set('offset', String(params.offset));
  if (params?.projectId) query.set('project_id', params.projectId);

  const queryString = query.toString();
  const url = `/workflow-runs${queryString ? `?${queryString}` : ''}`;

  const res = await fetch(url, { headers: getAuthHeaders() });

  if (res.status === 401) {
    throw new Error('Authentication required: Invalid or missing ARYA_API_KEY');
  }
  if (!res.ok) {
    const errText = await res.text();
    throw new Error(`Failed to load workflow runs: ${res.status} ${errText}`);
  }

  return res.json();
}

export async function fetchWorkflowRunDetail(id: string): Promise<WorkflowRunItem> {
  const res = await fetch(`/workflow-runs/${encodeURIComponent(id)}`, {
    headers: getAuthHeaders(),
  });

  if (res.status === 401) {
    throw new Error('Authentication required: Invalid or missing ARYA_API_KEY');
  }
  if (res.status === 404) {
    throw new Error(`Workflow run ${id} not found`);
  }
  if (!res.ok) {
    const errText = await res.text();
    throw new Error(`Failed to load run details: ${res.status} ${errText}`);
  }

  return res.json();
}

export async function fetchLineage(workflowRunId: string): Promise<LineageResponse> {
  const res = await fetch(`/lineage/${encodeURIComponent(workflowRunId)}`, {
    headers: getAuthHeaders(),
  });

  if (res.status === 401) {
    throw new Error('Authentication required: Invalid or missing ARYA_API_KEY');
  }
  if (res.status === 404) {
    throw new Error(`Lineage trace not found for run ${workflowRunId}`);
  }
  if (!res.ok) {
    const errText = await res.text();
    throw new Error(`Failed to load lineage trace: ${res.status} ${errText}`);
  }

  return res.json();
}

export async function fetchTrends(params: {
  topic: string;
  subreddit?: string;
  timeRange?: string;
  limit?: number;
}): Promise<ResearchResponse> {
  const query = new URLSearchParams();
  query.set('topic', params.topic.trim());
  if (params.limit !== undefined) query.set('limit', String(params.limit));
  if (params.timeRange) query.set('time_range', params.timeRange);
  if (params.subreddit?.trim()) query.set('subreddit', params.subreddit.trim());

  const res = await fetch(`/research/trends?${query.toString()}`, {
    headers: getAuthHeaders(),
  });

  if (res.status === 401) {
    throw new Error('Authentication required: Invalid or missing ARYA_API_KEY');
  }
  if (res.status === 422) {
    throw new Error('Invalid query: Topic is required for trend discovery');
  }
  if (!res.ok) {
    const errText = await res.text();
    throw new Error(`Failed to fetch trends: ${res.status} ${errText}`);
  }

  return res.json();
}

export async function fetchRedditResearch(params: {
  topic?: string;
  subreddit?: string;
  timeRange?: string;
  limit?: number;
}): Promise<ResearchResponse> {
  const query = new URLSearchParams();
  if (params.topic?.trim()) query.set('topic', params.topic.trim());
  if (params.subreddit?.trim()) query.set('subreddit', params.subreddit.trim());
  if (params.timeRange) query.set('time_range', params.timeRange);
  if (params.limit !== undefined) query.set('limit', String(params.limit));

  const res = await fetch(`/research/reddit?${query.toString()}`, {
    headers: getAuthHeaders(),
  });

  if (res.status === 401) {
    throw new Error('Authentication required: Invalid or missing ARYA_API_KEY');
  }
  if (res.status === 422) {
    throw new Error('At least one of topic or subreddit must be provided');
  }
  if (!res.ok) {
    const errText = await res.text();
    throw new Error(`Failed to fetch Reddit research: ${res.status} ${errText}`);
  }

  return res.json();
}

export async function fetchPublishingStatus(): Promise<PublishingStatusResponse> {
  const res = await fetch('/publishing/status', {
    headers: getAuthHeaders(),
  });

  if (res.status === 401) {
    throw new Error('Authentication required: Invalid or missing ARYA_API_KEY');
  }
  if (!res.ok) {
    const errText = await res.text();
    throw new Error(`Failed to load publishing status: ${res.status} ${errText}`);
  }

  return res.json();
}

export async function executePublishTest(payload: PublishRequest): Promise<PublishResponse> {
  // Enforce dry_run=true safeguard
  const safePayload: PublishRequest = {
    ...payload,
    dry_run: true,
  };

  const res = await fetch('/publishing/publish', {
    method: 'POST',
    headers: getAuthHeaders(),
    body: JSON.stringify(safePayload),
  });

  if (res.status === 401) {
    throw new Error('Authentication required: Invalid or missing ARYA_API_KEY');
  }
  if (res.status === 403) {
    throw new Error('Access denied: Path outside storage root or disallowed file type');
  }
  if (!res.ok) {
    const errText = await res.text();
    throw new Error(`Publish dry-run failed: ${res.status} ${errText}`);
  }

  return res.json();
}

export async function executeWorkflowRun(runId: string): Promise<{
  workflow_run_id: string;
  status: string;
  current_stage: string | null;
}> {
  const res = await fetch(`/workflow-runs/${encodeURIComponent(runId)}/execute`, {
    method: 'POST',
    headers: getAuthHeaders(),
  });

  if (res.status === 401) {
    throw new Error('Authentication required: Invalid or missing ARYA_API_KEY');
  }
  if (!res.ok) {
    const errText = await res.text();
    throw new Error(`Failed to execute workflow run: ${res.status} ${errText}`);
  }

  return res.json();
}

export async function fetchLearningFeedback(params?: {
  category?: string;
  minConfidence?: number;
  limit?: number;
}): Promise<LearningFeedbackItem[]> {
  const query = new URLSearchParams();
  if (params?.category) query.set('category', params.category);
  if (params?.minConfidence !== undefined) query.set('min_confidence', String(params.minConfidence));
  if (params?.limit !== undefined) query.set('limit', String(params.limit));

  const qs = query.toString();
  const res = await fetch(`/learning/feedback${qs ? `?${qs}` : ''}`, {
    headers: getAuthHeaders(),
  });

  if (res.status === 401) {
    throw new Error('Authentication required: Invalid or missing ARYA_API_KEY');
  }
  if (!res.ok) {
    const errText = await res.text();
    throw new Error(`Failed to fetch learning feedback: ${res.status} ${errText}`);
  }

  return res.json();
}

export async function createWorkflowRun(
  payload: CreateWorkflowRunPayload
): Promise<WorkflowRunCreateResponse> {
  const executeQuery = payload.execute ? '?execute=true' : '';
  const res = await fetch(`/workflow-runs/${executeQuery}`, {
    method: 'POST',
    headers: getAuthHeaders(),
    body: JSON.stringify({
      project_id: payload.project_id,
      topic: payload.topic || null,
      mode: payload.mode || 'assisted',
    }),
  });

  if (res.status === 401) {
    throw new Error('Authentication required: Invalid or missing ARYA_API_KEY');
  }
  if (!res.ok) {
    const errText = await res.text();
    throw new Error(`Failed to create workflow run: ${res.status} ${errText}`);
  }

  return res.json();
}

export async function fetchPendingApprovals(
  workflowRunId: string
): Promise<ApprovalCheckpointItem[]> {
  const res = await fetch(`/approvals/pending/${encodeURIComponent(workflowRunId)}`, {
    headers: getAuthHeaders(),
  });

  if (res.status === 401) {
    throw new Error('Authentication required: Invalid or missing ARYA_API_KEY');
  }
  if (!res.ok) {
    const errText = await res.text();
    throw new Error(`Failed to fetch pending approvals: ${res.status} ${errText}`);
  }

  const data = await res.json();
  return Array.isArray(data) ? data : [];
}

export async function decideApproval(
  checkpointId: string,
  payload: ApprovalDecisionPayload
): Promise<ApprovalCheckpointItem> {
  const res = await fetch(`/approvals/${encodeURIComponent(checkpointId)}/decide`, {
    method: 'POST',
    headers: getAuthHeaders(),
    body: JSON.stringify({
      action: payload.action,
      reviewer_notes: payload.reviewer_notes || null,
    }),
  });

  if (res.status === 401) {
    throw new Error('Authentication required: Invalid or missing ARYA_API_KEY');
  }
  if (res.status === 409) {
    let errDetail = 'Checkpoint has already been decided';
    try {
      const errJson = await res.json();
      if (errJson.detail) errDetail = errJson.detail;
    } catch {
      // fallback
    }
    throw new Error(`Conflict: ${errDetail}`);
  }
  if (!res.ok) {
    const errText = await res.text();
    throw new Error(`Failed to decide approval: ${res.status} ${errText}`);
  }

  return res.json();
}

