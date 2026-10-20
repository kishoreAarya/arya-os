/**
 * AryaOS V1 — Stage 06/07: Intelligence Provider & Execution Boundary Types
 *
 * Provider-neutral domain models decoupling AryaOS cognition and spatial memory
 * from concrete model vendors, runtime APIs, and execution environments.
 */

import { ActionClass } from './spatialCommand';

export type ProviderCapabilityType =
  | 'REASONING'
  | 'RESEARCH'
  | 'CODE_GENERATION'
  | 'VISION'
  | 'IMAGE_GENERATION'
  | 'VIDEO_GENERATION'
  | 'EMBEDDING'
  | 'CLASSIFICATION'
  | 'SUMMARIZATION'
  | 'STRUCTURED_EXTRACTION';

export type ProviderAvailabilityStatus =
  | 'AVAILABLE'
  | 'UNAVAILABLE'
  | 'CONFIGURATION_REQUIRED'
  | 'READY_FOR_CONFIGURATION'
  | 'DEGRADED';

export type ProviderHealthStatus =
  | 'AVAILABLE'
  | 'CONFIGURED'
  | 'UNAVAILABLE'
  | 'RATE_LIMITED'
  | 'DEGRADED'
  | 'UNKNOWN';

export interface ProviderCostProfile {
  tier: number; // 1 (lowest) to 5 (highest)
  inputTokenCostPerMillion?: number;
  outputTokenCostPerMillion?: number;
  perUnitCostUsd?: number;
  description: string;
}

export interface ProviderLatencyProfile {
  averageSeconds: number;
  p95Seconds?: number;
}

export interface IntelligenceProvider {
  id: string; // e.g., 'gemini', 'openrouter', 'fal', 'anthropic', 'openai', 'kling', 'together', 'elevenlabs', 'replicate'
  name: string;
  category: 'LLM' | 'IMAGE_GEN' | 'VIDEO_GEN' | 'VOICE_GEN' | 'COMPUTE';
  capabilities: ProviderCapabilityType[];
  availability: ProviderAvailabilityStatus;
  costProfile: ProviderCostProfile;
  latencyProfile: ProviderLatencyProfile;
  contextWindow?: number;
  supportedModels: string[];
  defaultModel: string;
  secretReference?: string; // e.g., "GEMINI_API_KEY" — NEVER the secret value
  isFallback?: boolean;
  notes?: string;
}

export interface ContextPackageItem {
  id: string;
  title: string;
  summary: string;
  type: string;
  relevanceScore: number;
}

export interface ContextPackage {
  systemContext: string;
  taskContext: string;
  memoryContext: ContextPackageItem[];
  entityContext: Array<{ name: string; type: string }>;
  timelineContext?: { predecessor?: string; successor?: string };
  userInput: string;
  tokenEstimate: number;
}

export interface RoutingPolicy {
  capability: ProviderCapabilityType;
  preferredProviders: string[];
  fallbackProviders: string[];
  maxCostTier?: number;
  latencyPreference?: 'LOW' | 'BALANCED' | 'THOROUGH';
  qualityRequirement?: 'STANDARD' | 'HIGH' | 'MAXIMUM';
}

export interface RoutingDecision {
  capability: ProviderCapabilityType;
  selectedProviderId: string;
  selectedProviderName: string;
  selectedModel: string;
  reasons: string[];
  fallbackProviderId?: string;
  fallbackModel?: string;
  status: ProviderAvailabilityStatus;
  estimatedCostTier: number;
}

export type ExecutionPlanStatus =
  | 'DRAFT'
  | 'READY'
  | 'ROUTED'
  | 'EXECUTING'
  | 'COMPLETED'
  | 'FAILED'
  | 'CANCELLED'
  | 'CONFIGURATION_REQUIRED'
  | 'UNAVAILABLE';

export interface ExecutionPlan {
  id: string;
  actionId: string;
  actionClass: ActionClass;
  providerId: string;
  providerName: string;
  modelId: string;
  capability: ProviderCapabilityType;
  contextPackage: ContextPackage;
  inputPayload: Record<string, unknown>;
  expectedOutputType: string;
  timeoutSeconds: number;
  retryPolicy: {
    maxRetries: number;
    backoffMs: number;
  };
  fallbackProviderId?: string;
  fallbackModelId?: string;
  estimatedCostMetadata: {
    costTier: number;
    estimatedUsd: number | null;
    currency: 'USD';
  };
  routingRationale: {
    capability: ProviderCapabilityType;
    selectedProvider: string;
    reasons: string[];
    fallbackProvider?: string;
  };
  status: ExecutionPlanStatus;
  createdAt: string;
}

/**
 * Stage 07: Explicit Provider Execution States
 * Deterministic and auditable state machine.
 */
export type GatewayExecutionState =
  | 'PLANNED'
  | 'CONFIGURATION_REQUIRED'
  | 'READY'
  | 'EXECUTING'
  | 'SUCCEEDED'
  | 'FAILED'
  | 'TIMEOUT'
  | 'CANCELLED'
  | 'UNAVAILABLE'
  | 'FALLBACK_EXECUTING'
  | 'FALLBACK_SUCCEEDED'
  | 'FALLBACK_FAILED';

// Backwards-compatible alias for existing callers
export type ExecutionResultStatus = GatewayExecutionState | 'SUCCESS' | 'PARTIAL';

export interface ExecutionProvenance {
  executionId: string;
  planId: string;
  actionId?: string;
  sourceCommand?: string;
  sourceMemoryId?: string;
  sourceMemoryTitle?: string;
  contextMemoriesCount: number;
  providerSelected: string;
  modelSelected: string;
  capability: ProviderCapabilityType;
  fallbackUsed: boolean;
  fallbackProvider?: string;
  timestamp: string;
}

export interface ExecutionResult {
  executionId: string;
  planId: string;
  status: GatewayExecutionState;
  providerId: string;
  modelId: string;
  capability: ProviderCapabilityType;
  startedAt: string;
  completedAt: string;
  latencyMs: number;
  fallbackUsed: boolean;
  retryCount: number;
  output?: string;
  sanitizedOutput?: string;
  error?: string;
  sanitizedError?: string;
  structuredOutput?: Record<string, unknown>;
  routingRationale?: {
    capability: ProviderCapabilityType;
    selectedProvider: string;
    reasons: string[];
    fallbackProvider?: string;
  };
  contextSummary?: {
    memoriesCount: number;
    tokenEstimate: number;
    activeMemoryId?: string;
  };
  provenance: ExecutionProvenance;
  executionMode: 'REAL' | 'SIMULATED' | 'TEST';
  usage?: {
    inputTokens?: number;
    outputTokens?: number;
    estimatedCost: number | null;
    unitLabel?: string;
  };
  metadata?: Record<string, unknown>;
  timestamp: string;
}

export interface ProviderAdapterExecutionResult {
  status: 'SUCCEEDED' | 'FAILED' | 'TIMEOUT' | 'UNAVAILABLE' | 'CONFIGURATION_REQUIRED' | 'CANCELLED';
  output?: string;
  error?: string;
  structuredOutput?: Record<string, unknown>;
  usage?: {
    inputTokens?: number;
    outputTokens?: number;
    costUsd?: number | null;
  };
  metadata?: Record<string, unknown>;
}

export interface ProviderAdapter {
  providerId: string;
  supportedCapabilities?: ProviderCapabilityType[];
  validateConfiguration(): { isValid: boolean; reason?: string };
  checkHealth?(): Promise<ProviderHealthStatus>;
  execute(
    plan: ExecutionPlan,
    signal?: AbortSignal,
    options?: { executionMode?: 'REAL' | 'SIMULATED' | 'TEST' }
  ): Promise<ProviderAdapterExecutionResult | ExecutionResult>;
}
