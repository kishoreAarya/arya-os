export type GenerationType = 'image' | 'video' | 'image_to_video';

export interface ModelCapability {
  id: string;
  name: string;
  provider: string;
  default?: boolean;
  cost_tier: number;
  configured: boolean;
  start_frame: boolean;
  end_frame: boolean;
}

export interface AspectRatioOption {
  id: string;
  label: string;
  dimensions: string;
}

export interface ResolutionOption {
  id: string;
  label: string;
}

export interface DurationOption {
  value: number;
  label: string;
}

export interface GenerationTypeOption {
  id: GenerationType;
  label: string;
  description: string;
}

export interface CapabilitiesManifest {
  generation_types: GenerationTypeOption[];
  aspect_ratios: AspectRatioOption[];
  resolutions: ResolutionOption[];
  durations: DurationOption[];
  models: {
    image: ModelCapability[];
    video: ModelCapability[];
    image_to_video: ModelCapability[];
  };
}

export interface CreatorGeneratePayload {
  generation_type: GenerationType;
  prompt: string;
  model?: string;
  provider?: string;
  aspect_ratio: string;
  resolution?: string;
  duration_seconds?: number;
  start_frame_url?: string;
  end_frame_url?: string;
  reference_image_url?: string;
}

export type JobStatus = 'pending' | 'in_progress' | 'completed' | 'failed';

export interface GenerationJob {
  job_id: string;
  workflow_run_id: string;
  status: JobStatus;
  current_stage?: string;
  generation_type: GenerationType;
  prompt: string;
  model?: string;
  provider?: string;
  aspect_ratio?: string;
  duration_seconds?: number;
  total_cost_usd: number;
  started_at?: string;
  completed_at?: string;
  failure_reason?: string;
  output: {
    asset_url?: string;
    storage_path?: string;
    candidate_urls?: string[];
    source_image_path?: string;
    keyframe_image_url?: string;
    provider_used?: string;
    duration_seconds?: number;
    aspect_ratio?: string;
    generation_type?: string;
  };
}

export interface HistoryItem {
  job_id: string;
  workflow_run_id: string;
  generation_type: GenerationType;
  prompt: string;
  model?: string;
  provider?: string;
  aspect_ratio?: string;
  duration_seconds?: number;
  status: JobStatus;
  asset_url?: string;
  total_cost_usd: number;
  created_at: string;
  completed_at?: string;
  failure_reason?: string;
}

export interface HealthStatus {
  status: 'healthy' | 'degraded' | 'error' | 'connecting';
  checks?: Record<string, string>;
}
