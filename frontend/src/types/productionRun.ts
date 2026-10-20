import { GenerationJob, GenerationType, HistoryItem, JobStatus } from './creator';

export type SystemOperationalState = 'IDLE' | 'ACTIVE' | 'DEGRADED' | 'ERROR';

export type FailureCategory =
  | 'SUBMISSION_FAILURE'
  | 'PROVIDER_FAILURE'
  | 'TIMEOUT'
  | 'VALIDATION_FAILURE'
  | 'NETWORK_FAILURE'
  | 'UNKNOWN';

export function classifyFailure(error: string | undefined): FailureCategory {
  if (!error) return 'UNKNOWN';
  const lower = error.toLowerCase();
  if (
    lower.includes('validation') ||
    lower.includes('invalid') ||
    lower.includes('422') ||
    lower.includes('cannot be blank')
  ) {
    return 'VALIDATION_FAILURE';
  }
  if (lower.includes('timeout') || lower.includes('timed out') || lower.includes('deadline')) {
    return 'TIMEOUT';
  }
  if (
    lower.includes('network') ||
    lower.includes('fetch') ||
    lower.includes('gateway') ||
    lower.includes('502') ||
    lower.includes('503') ||
    lower.includes('504') ||
    lower.includes('connection')
  ) {
    return 'NETWORK_FAILURE';
  }
  if (
    lower.includes('submission') ||
    lower.includes('submit') ||
    lower.includes('401') ||
    lower.includes('403') ||
    lower.includes('429') ||
    lower.includes('capacity')
  ) {
    return 'SUBMISSION_FAILURE';
  }
  if (
    lower.includes('provider') ||
    lower.includes('replicate') ||
    lower.includes('fal') ||
    lower.includes('kling') ||
    lower.includes('together') ||
    lower.includes('gpu') ||
    lower.includes('cuda') ||
    lower.includes('out of memory')
  ) {
    return 'PROVIDER_FAILURE';
  }
  return 'UNKNOWN';
}

export function deriveSystemState(
  healthStatus: string,
  isSubmitting: boolean,
  currentJobStatus?: string,
  error?: string | null,
  pollErrorCount: number = 0
): SystemOperationalState {
  if (healthStatus === 'error' || (error && !isSubmitting) || currentJobStatus === 'failed') {
    return 'ERROR';
  }
  if (healthStatus === 'degraded' || pollErrorCount > 0) {
    return 'DEGRADED';
  }
  if (isSubmitting || currentJobStatus === 'pending' || currentJobStatus === 'in_progress') {
    return 'ACTIVE';
  }
  return 'IDLE';
}

export interface ProductionRunParameters {
  aspectRatio?: string;
  resolution?: string;
  durationSeconds?: number;
  referenceImageUrl?: string;
  startFrameUrl?: string;
  endFrameUrl?: string;
}

export interface ProductionRun {
  id: string;
  jobId: string;
  workflowRunId?: string;
  createdAt: string;
  startedAt?: string;
  completedAt?: string;
  mode: GenerationType;
  status: JobStatus;
  model?: string;
  provider?: string;
  requestedModel?: string;
  requestedProvider?: string;
  actualModel?: string;
  actualProvider?: string;
  parameters: ProductionRunParameters;
  prompt: string;
  referenceAsset?: string;
  startFrame?: string;
  endFrame?: string;
  outputAsset?: string;
  error?: string;
  failureReason?: string;
  failureCategory?: FailureCategory;
  failureStage?: string;
  durationMs?: number;
  durationSeconds?: number;
  cost?: number;
  costUsd?: number;
  currentStage?: string;
}

export interface OperationalMetrics {
  totalRuns: number;
  successfulRuns: number;
  failedRuns: number;
  processingRuns: number;
  queuedRuns: number;
  successRate: number; // 0 to 100 percentage
  avgDurationSeconds: number | null;
  totalCostUsd: number;
  providerUsage: Record<string, number>;
  modelUsage: Record<string, number>;
  costByProvider: Record<string, number>;
  costByModel: Record<string, number>;
}

export type HistoryFilterType =
  | 'all'
  | 'image'
  | 'video'
  | 'image_to_video'
  | 'completed'
  | 'failed'
  | 'processing';

export type HistorySortOrder = 'newest' | 'oldest';

export function historyItemToProductionRun(item: HistoryItem): ProductionRun {
  let durationSeconds: number | undefined = item.duration_seconds;
  let durationMs: number | undefined = undefined;

  if (item.completed_at && item.created_at) {
    const start = new Date(item.created_at).getTime();
    const end = new Date(item.completed_at).getTime();
    if (!isNaN(start) && !isNaN(end) && end >= start) {
      durationMs = end - start;
      if (!durationSeconds || durationSeconds === 5.0) {
        durationSeconds = Math.round((durationMs / 100) / 10);
      }
    }
  }

  const failureCategory = item.failure_reason ? classifyFailure(item.failure_reason) : undefined;
  const failureStage = item.status === 'failed' ? 'execution' : undefined;

  return {
    id: item.workflow_run_id || item.job_id,
    jobId: item.job_id,
    workflowRunId: item.workflow_run_id,
    createdAt: item.created_at || new Date().toISOString(),
    completedAt: item.completed_at,
    mode: item.generation_type,
    status: item.status,
    model: item.actual_model || item.model,
    provider: item.actual_provider || item.provider,
    requestedModel: item.requested_model || item.model,
    requestedProvider: item.requested_provider || item.provider,
    actualModel: item.actual_model || item.model,
    actualProvider: item.actual_provider || item.provider,
    parameters: {
      aspectRatio: item.aspect_ratio || '16:9',
      durationSeconds: item.duration_seconds,
    },
    prompt: item.prompt,
    outputAsset: item.asset_url,
    error: item.failure_reason,
    failureReason: item.failure_reason,
    failureCategory,
    failureStage,
    durationMs,
    durationSeconds,
    cost: typeof item.total_cost_usd === 'number' && item.total_cost_usd > 0 ? item.total_cost_usd : undefined,
    costUsd: typeof item.total_cost_usd === 'number' && item.total_cost_usd > 0 ? item.total_cost_usd : undefined,
  };
}

export function generationJobToProductionRun(job: GenerationJob): ProductionRun {
  let durationSeconds: number | undefined = job.duration_seconds;
  let durationMs: number | undefined = undefined;

  if (job.completed_at && job.started_at) {
    const start = new Date(job.started_at).getTime();
    const end = new Date(job.completed_at).getTime();
    if (!isNaN(start) && !isNaN(end) && end >= start) {
      durationMs = end - start;
      durationSeconds = Math.round((durationMs / 100) / 10);
    }
  }

  const failureCategory = job.failure_reason ? classifyFailure(job.failure_reason) : undefined;

  return {
    id: job.workflow_run_id || job.job_id,
    jobId: job.job_id,
    workflowRunId: job.workflow_run_id,
    createdAt: job.started_at || new Date().toISOString(),
    startedAt: job.started_at,
    completedAt: job.completed_at,
    mode: job.generation_type,
    status: job.status,
    model: job.actual_model || job.output?.model_used || job.model,
    provider: job.actual_provider || job.output?.provider_used || job.provider,
    requestedModel: job.requested_model || job.model,
    requestedProvider: job.requested_provider || job.provider,
    actualModel: job.actual_model || job.output?.model_used || job.model,
    actualProvider: job.actual_provider || job.output?.provider_used || job.provider,
    currentStage: job.current_stage,
    failureStage: job.current_stage || (job.status === 'failed' ? 'execution' : undefined),
    failureCategory,
    parameters: {
      aspectRatio: job.aspect_ratio || job.output?.aspect_ratio || '16:9',
      durationSeconds: job.duration_seconds || job.output?.duration_seconds,
      startFrameUrl: job.output?.source_image_path || job.output?.keyframe_image_url,
    },
    prompt: job.prompt,
    outputAsset: job.output?.asset_url || job.output?.storage_path,
    referenceAsset: job.output?.source_image_path || job.output?.keyframe_image_url,
    startFrame: job.output?.source_image_path || job.output?.keyframe_image_url,
    error: job.failure_reason,
    failureReason: job.failure_reason,
    durationMs,
    durationSeconds,
    cost: typeof job.total_cost_usd === 'number' && job.total_cost_usd > 0 ? job.total_cost_usd : undefined,
    costUsd: typeof job.total_cost_usd === 'number' && job.total_cost_usd > 0 ? job.total_cost_usd : undefined,
  };
}

export function computeOperationalMetrics(runs: ProductionRun[]): OperationalMetrics {
  const totalRuns = runs.length;
  if (totalRuns === 0) {
    return {
      totalRuns: 0,
      successfulRuns: 0,
      failedRuns: 0,
      processingRuns: 0,
      queuedRuns: 0,
      successRate: 0,
      avgDurationSeconds: null,
      totalCostUsd: 0,
      providerUsage: {},
      modelUsage: {},
      costByProvider: {},
      costByModel: {},
    };
  }

  let successfulRuns = 0;
  let failedRuns = 0;
  let processingRuns = 0;
  let queuedRuns = 0;
  let totalDuration = 0;
  let durationCount = 0;
  let totalCostUsd = 0;
  const providerUsage: Record<string, number> = {};
  const modelUsage: Record<string, number> = {};
  const costByProvider: Record<string, number> = {};
  const costByModel: Record<string, number> = {};

  for (const run of runs) {
    if (run.status === 'completed') {
      successfulRuns++;
    } else if (run.status === 'failed') {
      failedRuns++;
    } else if (run.status === 'in_progress') {
      processingRuns++;
    } else if (run.status === 'pending') {
      queuedRuns++;
    }

    if (run.durationSeconds && run.durationSeconds > 0) {
      totalDuration += run.durationSeconds;
      durationCount++;
    }

    const runCost = typeof run.costUsd === 'number' ? run.costUsd : run.cost;
    if (typeof runCost === 'number' && runCost > 0) {
      totalCostUsd += runCost;
      const prov = run.actualProvider || run.provider;
      if (prov) {
        costByProvider[prov] = Math.round(((costByProvider[prov] || 0) + runCost) * 10000) / 10000;
      }
      const mod = run.actualModel || run.model;
      if (mod) {
        costByModel[mod] = Math.round(((costByModel[mod] || 0) + runCost) * 10000) / 10000;
      }
    }

    const provider = run.actualProvider || run.provider;
    if (provider) {
      providerUsage[provider] = (providerUsage[provider] || 0) + 1;
    }

    const model = run.actualModel || run.model;
    if (model) {
      modelUsage[model] = (modelUsage[model] || 0) + 1;
    }
  }

  const finishedRuns = successfulRuns + failedRuns;
  const successRate = finishedRuns > 0 ? Math.round((successfulRuns / finishedRuns) * 100) : 0;
  const avgDurationSeconds = durationCount > 0 ? Math.round((totalDuration / durationCount) * 10) / 10 : null;

  return {
    totalRuns,
    successfulRuns,
    failedRuns,
    processingRuns,
    queuedRuns,
    successRate,
    avgDurationSeconds,
    totalCostUsd: Math.round(totalCostUsd * 10000) / 10000,
    providerUsage,
    modelUsage,
    costByProvider,
    costByModel,
  };
}

export function filterAndSortRuns(
  runs: ProductionRun[],
  searchTerm: string,
  filterType: HistoryFilterType,
  sortOrder: HistorySortOrder
): ProductionRun[] {
  let filtered = runs;

  // 1. Text Search across prompt, run ID, job ID, model, provider
  const term = searchTerm.trim().toLowerCase();
  if (term) {
    filtered = filtered.filter((run) => {
      const matchPrompt = run.prompt.toLowerCase().includes(term);
      const matchId = run.id.toLowerCase().includes(term);
      const matchJobId = run.jobId.toLowerCase().includes(term);
      const matchWorkflowId = run.workflowRunId?.toLowerCase().includes(term);
      const matchModel = run.model?.toLowerCase().includes(term);
      const matchProvider = run.provider?.toLowerCase().includes(term);
      return Boolean(matchPrompt || matchId || matchJobId || matchWorkflowId || matchModel || matchProvider);
    });
  }

  // 2. Filter by Mode or Status
  if (filterType !== 'all') {
    if (filterType === 'image') {
      filtered = filtered.filter((r) => r.mode === 'image');
    } else if (filterType === 'video') {
      filtered = filtered.filter((r) => r.mode === 'video');
    } else if (filterType === 'image_to_video') {
      filtered = filtered.filter((r) => r.mode === 'image_to_video');
    } else if (filterType === 'completed') {
      filtered = filtered.filter((r) => r.status === 'completed');
    } else if (filterType === 'failed') {
      filtered = filtered.filter((r) => r.status === 'failed');
    } else if (filterType === 'processing') {
      filtered = filtered.filter((r) => r.status === 'in_progress' || r.status === 'pending');
    }
  }

  // 3. Sorting
  return [...filtered].sort((a, b) => {
    const timeA = new Date(a.createdAt).getTime() || 0;
    const timeB = new Date(b.createdAt).getTime() || 0;
    return sortOrder === 'newest' ? timeB - timeA : timeA - timeB;
  });
}
