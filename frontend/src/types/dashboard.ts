export type AppView = 'spatial' | 'creator' | 'pipelines' | 'research' | 'publishing' | 'learning';

export type WorkflowStatusType =
  | 'pending'
  | 'running'
  | 'awaiting_approval'
  | 'completed'
  | 'failed';

export interface WorkflowRunArtifacts {
  video_path?: string | null;
  thumbnail_path?: string | null;
  audio_path?: string | null;
  script_content?: string | null;
  storyboard?: Record<string, unknown> | null;
  images?: string[];
  metadata?: Record<string, unknown> | null;
}

export interface CreateWorkflowRunPayload {
  project_id: string;
  topic?: string;
  mode?: 'assisted' | 'autonomous' | 'manual';
  execute?: boolean;
}

export interface WorkflowRunCreateResponse {
  workflow_run_id: string;
  status: WorkflowStatusType;
  current_stage: string | null;
}

export interface WorkflowRunItem {
  id: string;
  project_id: string;
  topic: string | null;
  mode: string;
  status: WorkflowStatusType;
  current_stage: string | null;
  total_cost_usd: number | string;
  started_at: string | null;
  completed_at: string | null;
  failure_reason: string | null;
  created_at: string;
  updated_at: string;
  artifacts?: WorkflowRunArtifacts | null;
}

export interface LearningFeedbackItem {
  id: string;
  category: string;
  insight: string;
  confidence: number | null;
  based_on_video_count: number;
  is_active: boolean;
  created_at: string;
  updated_at: string;
}

export interface ApprovalDecisionPayload {
  action: 'approve' | 'reject' | 'retry' | 'manual_edit' | 'continue';
  reviewer_notes?: string;
}

export interface ApprovalCheckpointItem {
  id: string;
  workflow_run_id: string;
  stage: string;
  reference_table: string;
  reference_id: string;
  action: string | null;
  reviewer_notes: string | null;
  decided_at: string | null;
  created_at: string;
  updated_at: string;
  review_content?: Record<string, unknown> | null;
}

export interface QualityScore {
  dimension: string;
  score: number;
  scored_by: string;
}

export interface GenerationAttempt {
  attempt_number: number;
  succeeded: boolean;
  failure_reason: string | null;
  provider_id: string | null;
  cost_usd: number;
}

export interface ApprovalTrace {
  stage: string;
  action: string | null;
  decided_at: string | null;
}

export interface LineageTraceItem {
  artifact_type: string;
  reference_table: string;
  reference_id: string;
  version: number;
  created_at: string;
  quality_scores: QualityScore[];
  generation_attempts: GenerationAttempt[];
  approval: ApprovalTrace[];
}

export interface LineageResponse {
  workflow_run_id: string;
  topic: string | null;
  status: string;
  current_stage: string | null;
  total_cost_usd: number;
  trace: LineageTraceItem[];
}

export interface ResearchSignalItem {
  topic: string;
  search_volume_or_signal: string;
  relevance: number;
  freshness: string;
  competition?: string | null;
  source: string;
  timestamp: string;
  confidence: number;
  opportunity_score?: number | null;
  metadata?: Record<string, unknown>;
}

export interface ResearchResponse {
  source: string;
  query: Record<string, unknown>;
  total_results: number;
  retrieved_at: string;
  results: ResearchSignalItem[];
}

export interface PublishingChannel {
  id: string | null;
  name: string | null;
  identifier: string | null;
}

export interface PublishingStatusResponse {
  platform: string;
  base_url?: string;
  configured: boolean;
  reachable: boolean;
  status: 'connected' | 'disconnected' | string;
  error: string | null;
  connected_channels: number;
  channels: PublishingChannel[];
}

export interface PublishRequest {
  asset_storage_path: string;
  title?: string;
  caption?: string;
  platform?: string;
  social_platform?: string;
  integration_id?: string | null;
  publish_type?: 'now' | 'schedule' | 'draft';
  dry_run: boolean;
  workflow_run_id?: string | null;
  video_id?: string | null;
}

export interface PublishResponse {
  success: boolean;
  platform: string;
  published_content_id?: string | null;
  publish_status: string;
  scheduled_at?: string | null;
  url?: string | null;
  is_dry_run: boolean;
  error?: string | null;
}
