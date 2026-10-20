/**
 * AryaOS V1 — Stage 06: Provider Registry
 *
 * Central registry mapping real intelligence providers, their capabilities,
 * cost/latency profiles, and availability states without hard-coding secrets.
 */

import {
  IntelligenceProvider,
  ProviderCapabilityType,
  ProviderAvailabilityStatus,
} from '../types/intelligenceProvider';

export const DEFAULT_PROVIDERS: IntelligenceProvider[] = [
  {
    id: 'gemini',
    name: 'Google Gemini',
    category: 'LLM',
    capabilities: [
      'REASONING',
      'RESEARCH',
      'SUMMARIZATION',
      'VISION',
      'EMBEDDING',
      'STRUCTURED_EXTRACTION',
    ],
    availability: 'AVAILABLE',
    costProfile: {
      tier: 1,
      inputTokenCostPerMillion: 0.15,
      outputTokenCostPerMillion: 0.6,
      description: 'Ultra-low cost high-throughput multicontext reasoning.',
    },
    latencyProfile: {
      averageSeconds: 6.0,
      p95Seconds: 12.0,
    },
    contextWindow: 1_000_000,
    supportedModels: [
      'gemini-3.1-pro-preview',
      'gemini-3.1-flash-lite',
      'gemini-3-flash-preview',
      'gemini-3.5-flash',
    ],
    defaultModel: 'gemini-3.1-pro-preview',
    secretReference: 'GEMINI_API_KEY',
    isFallback: false,
    notes: 'Primary reasoning and research engine with 1M token context.',
  },
  {
    id: 'openrouter',
    name: 'OpenRouter',
    category: 'LLM',
    capabilities: [
      'REASONING',
      'RESEARCH',
      'CODE_GENERATION',
      'SUMMARIZATION',
    ],
    availability: 'AVAILABLE',
    costProfile: {
      tier: 2,
      inputTokenCostPerMillion: 0.27,
      outputTokenCostPerMillion: 1.1,
      description: 'Multi-model aggregator with competitive open-source pricing.',
    },
    latencyProfile: {
      averageSeconds: 8.0,
      p95Seconds: 15.0,
    },
    contextWindow: 128_000,
    supportedModels: [
      'deepseek/deepseek-chat',
      'moonshotai/kimi-k2',
      'meta-llama/llama-3.3-70b-instruct',
    ],
    defaultModel: 'deepseek/deepseek-chat',
    secretReference: 'OPENROUTER_API_KEY',
    isFallback: false,
    notes: 'Secondary code generation and deep reasoning fallback router.',
  },
  {
    id: 'anthropic',
    name: 'Anthropic Claude',
    category: 'LLM',
    capabilities: [
      'REASONING',
      'RESEARCH',
      'CODE_GENERATION',
      'VISION',
      'STRUCTURED_EXTRACTION',
    ],
    availability: 'AVAILABLE',
    costProfile: {
      tier: 3,
      inputTokenCostPerMillion: 3.0,
      outputTokenCostPerMillion: 15.0,
      description: 'Premium reasoning and nuanced architectural prose.',
    },
    latencyProfile: {
      averageSeconds: 7.0,
      p95Seconds: 14.0,
    },
    contextWindow: 200_000,
    supportedModels: [
      'claude-sonnet-4-6',
      'claude-3-5-haiku-20241022',
    ],
    defaultModel: 'claude-sonnet-4-6',
    secretReference: 'ANTHROPIC_API_KEY',
    isFallback: true,
    notes: 'High-precision architectural fallback for critical arbitration.',
  },
  {
    id: 'openai',
    name: 'OpenAI GPT',
    category: 'LLM',
    capabilities: [
      'REASONING',
      'RESEARCH',
      'VISION',
      'EMBEDDING',
      'STRUCTURED_EXTRACTION',
    ],
    availability: 'AVAILABLE',
    costProfile: {
      tier: 3,
      inputTokenCostPerMillion: 2.5,
      outputTokenCostPerMillion: 10.0,
      description: 'Frontier multi-modal intelligence.',
    },
    latencyProfile: {
      averageSeconds: 6.0,
      p95Seconds: 12.0,
    },
    contextWindow: 128_000,
    supportedModels: [
      'gpt-4o',
      'gpt-4o-mini',
    ],
    defaultModel: 'gpt-4o',
    secretReference: 'OPENAI_API_KEY',
    isFallback: true,
    notes: 'Multimodal vision and structured extraction engine.',
  },
  {
    id: 'fal',
    name: 'fal.ai Media Engine',
    category: 'IMAGE_GEN',
    capabilities: [
      'IMAGE_GENERATION',
      'VIDEO_GENERATION',
      'VISION',
    ],
    availability: 'AVAILABLE',
    costProfile: {
      tier: 2,
      perUnitCostUsd: 0.05,
      description: 'Low-latency distributed inference for FLUX Pro and Kling Video.',
    },
    latencyProfile: {
      averageSeconds: 35.0,
      p95Seconds: 65.0,
    },
    supportedModels: [
      'fal-ai/flux-pro/v1.1',
      'flux-dev',
      'fal-ai/kling-video/v1.6/standard/image-to-video',
      'fal-ai/wan-i2v',
      'ltx-video',
    ],
    defaultModel: 'fal-ai/flux-pro/v1.1',
    secretReference: 'FAL_KEY',
    isFallback: false,
    notes: 'Primary visual generation pipeline routed through OpenMontage boundary.',
  },
  {
    id: 'together',
    name: 'Together AI',
    category: 'IMAGE_GEN',
    capabilities: [
      'IMAGE_GENERATION',
      'VIDEO_GENERATION',
      'REASONING',
    ],
    availability: 'READY_FOR_CONFIGURATION',
    costProfile: {
      tier: 2,
      perUnitCostUsd: 0.04,
      description: 'Serverless FLUX inference and Wan video models.',
    },
    latencyProfile: {
      averageSeconds: 30.0,
      p95Seconds: 55.0,
    },
    supportedModels: [
      'black-forest-labs/FLUX.1.1-pro',
      'black-forest-labs/FLUX.1-dev',
      'togethercomputer/wan-2.1-t2v',
    ],
    defaultModel: 'black-forest-labs/FLUX.1.1-pro',
    secretReference: 'TOGETHER_API_KEY',
    isFallback: true,
    notes: 'Secondary image provider fallback.',
  },
  {
    id: 'kling',
    name: 'Kling AI Video',
    category: 'VIDEO_GEN',
    capabilities: [
      'VIDEO_GENERATION',
    ],
    availability: 'AVAILABLE',
    costProfile: {
      tier: 2,
      perUnitCostUsd: 0.12,
      description: 'High-fidelity cinematic shot motion synthesis.',
    },
    latencyProfile: {
      averageSeconds: 60.0,
      p95Seconds: 180.0,
    },
    supportedModels: [
      'kwaivgi/kling-v1.6-standard',
    ],
    defaultModel: 'kwaivgi/kling-v1.6-standard',
    secretReference: 'FAL_KEY',
    isFallback: false,
    notes: 'Real Kling video provider via OpenMontage adapter.',
  },
  {
    id: 'replicate',
    name: 'Replicate',
    category: 'IMAGE_GEN',
    capabilities: [
      'IMAGE_GENERATION',
      'VIDEO_GENERATION',
    ],
    availability: 'READY_FOR_CONFIGURATION',
    costProfile: {
      tier: 3,
      perUnitCostUsd: 0.08,
      description: 'Cloud API for open weights community models.',
    },
    latencyProfile: {
      averageSeconds: 40.0,
      p95Seconds: 90.0,
    },
    supportedModels: [
      'black-forest-labs/flux-schnell',
      'lightricks/ltx-video',
    ],
    defaultModel: 'black-forest-labs/flux-schnell',
    secretReference: 'REPLICATE_API_KEY',
    isFallback: true,
    notes: 'Tertiary fallback provider for visual synthesis.',
  },
];

class ProviderRegistry {
  private providers: Map<string, IntelligenceProvider> = new Map();

  constructor() {
    this.resetToDefaults();
  }

  /**
   * Resets registry to default AryaOS provider definitions.
   */
  public resetToDefaults(): void {
    this.providers.clear();
    DEFAULT_PROVIDERS.forEach((p) => {
      this.providers.set(p.id, { ...p });
    });
  }

  /**
   * Registers a new provider or updates an existing one cleanly.
   */
  public registerProvider(provider: IntelligenceProvider): void {
    this.providers.set(provider.id, { ...provider });
  }

  /**
   * Retrieves provider by ID.
   */
  public getProvider(id: string): IntelligenceProvider | undefined {
    return this.providers.get(id);
  }

  /**
   * Returns all registered providers.
   */
  public getAllProviders(): IntelligenceProvider[] {
    return Array.from(this.providers.values());
  }

  /**
   * Returns all providers capable of performing the specified capability,
   * sorted by cost tier (cheapest first).
   */
  public getProvidersForCapability(capability: ProviderCapabilityType): IntelligenceProvider[] {
    return Array.from(this.providers.values())
      .filter((p) => p.capabilities.includes(capability))
      .sort((a, b) => a.costProfile.tier - b.costProfile.tier);
  }

  /**
   * Updates provider availability status.
   */
  public updateProviderAvailability(id: string, status: ProviderAvailabilityStatus): boolean {
    const existing = this.providers.get(id);
    if (!existing) return false;
    existing.availability = status;
    return true;
  }
}

export const providerRegistry = new ProviderRegistry();
