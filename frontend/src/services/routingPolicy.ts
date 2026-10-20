/**
 * AryaOS V1 — Stage 06: Routing Policy Engine
 *
 * Configurable data-driven routing policies mapping intelligence capabilities
 * to preferred providers, fallback chains, cost budgets, and quality tiers.
 */

import {
  ProviderCapabilityType,
  RoutingPolicy,
} from '../types/intelligenceProvider';

export const DEFAULT_ROUTING_POLICIES: Record<ProviderCapabilityType, RoutingPolicy> = {
  RESEARCH: {
    capability: 'RESEARCH',
    preferredProviders: ['gemini', 'openrouter'],
    fallbackProviders: ['anthropic', 'openai'],
    maxCostTier: 3,
    latencyPreference: 'BALANCED',
    qualityRequirement: 'HIGH',
  },
  REASONING: {
    capability: 'REASONING',
    preferredProviders: ['gemini', 'openrouter'],
    fallbackProviders: ['anthropic', 'openai'],
    maxCostTier: 3,
    latencyPreference: 'BALANCED',
    qualityRequirement: 'MAXIMUM',
  },
  CODE_GENERATION: {
    capability: 'CODE_GENERATION',
    preferredProviders: ['openrouter', 'anthropic'],
    fallbackProviders: ['gemini'],
    maxCostTier: 3,
    latencyPreference: 'BALANCED',
    qualityRequirement: 'HIGH',
  },
  IMAGE_GENERATION: {
    capability: 'IMAGE_GENERATION',
    preferredProviders: ['fal'],
    fallbackProviders: ['together', 'replicate'],
    maxCostTier: 3,
    latencyPreference: 'BALANCED',
    qualityRequirement: 'HIGH',
  },
  VIDEO_GENERATION: {
    capability: 'VIDEO_GENERATION',
    preferredProviders: ['fal', 'kling'],
    fallbackProviders: ['replicate'],
    maxCostTier: 3,
    latencyPreference: 'THOROUGH',
    qualityRequirement: 'HIGH',
  },
  SUMMARIZATION: {
    capability: 'SUMMARIZATION',
    preferredProviders: ['gemini', 'openrouter'],
    fallbackProviders: ['anthropic'],
    maxCostTier: 2,
    latencyPreference: 'LOW',
    qualityRequirement: 'STANDARD',
  },
  STRUCTURED_EXTRACTION: {
    capability: 'STRUCTURED_EXTRACTION',
    preferredProviders: ['gemini', 'anthropic'],
    fallbackProviders: ['openai'],
    maxCostTier: 3,
    latencyPreference: 'LOW',
    qualityRequirement: 'HIGH',
  },
  VISION: {
    capability: 'VISION',
    preferredProviders: ['gemini', 'fal'],
    fallbackProviders: ['anthropic', 'openai'],
    maxCostTier: 3,
    latencyPreference: 'BALANCED',
    qualityRequirement: 'HIGH',
  },
  EMBEDDING: {
    capability: 'EMBEDDING',
    preferredProviders: ['gemini', 'openai'],
    fallbackProviders: [],
    maxCostTier: 1,
    latencyPreference: 'LOW',
    qualityRequirement: 'STANDARD',
  },
  CLASSIFICATION: {
    capability: 'CLASSIFICATION',
    preferredProviders: ['gemini', 'openrouter'],
    fallbackProviders: ['anthropic'],
    maxCostTier: 2,
    latencyPreference: 'LOW',
    qualityRequirement: 'STANDARD',
  },
};

class RoutingPolicyManager {
  private policies: Map<ProviderCapabilityType, RoutingPolicy> = new Map();

  constructor() {
    this.resetToDefaults();
  }

  public resetToDefaults(): void {
    this.policies.clear();
    (Object.keys(DEFAULT_ROUTING_POLICIES) as ProviderCapabilityType[]).forEach((cap) => {
      this.policies.set(cap, { ...DEFAULT_ROUTING_POLICIES[cap] });
    });
  }

  public getPolicy(capability: ProviderCapabilityType): RoutingPolicy {
    const existing = this.policies.get(capability);
    if (existing) {
      return { ...existing };
    }
    return {
      capability,
      preferredProviders: ['gemini'],
      fallbackProviders: ['openrouter'],
      maxCostTier: 3,
      latencyPreference: 'BALANCED',
      qualityRequirement: 'STANDARD',
    };
  }

  public setPolicy(policy: RoutingPolicy): void {
    this.policies.set(policy.capability, { ...policy });
  }
}

export const routingPolicyManager = new RoutingPolicyManager();
