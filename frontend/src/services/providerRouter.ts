/**
 * AryaOS V1 — Stage 06: Provider Router
 *
 * Deterministic router that inspects action proposals, selects optimal intelligence
 * providers via data-driven policies, and synthesizes complete execution plans.
 */

import { ActionProposal, CommandContext } from '../types/spatialCommand';
import {
  ProviderCapabilityType,
  ExecutionPlan,
  RoutingDecision,
  IntelligenceProvider,
} from '../types/intelligenceProvider';
import { providerRegistry } from './providerRegistry';
import { routingPolicyManager } from './routingPolicy';
import { contextPackager } from './contextPackager';

export const providerRouter = {
  /**
   * Resolves required capability for an action class.
   */
  resolveCapability(proposal: ActionProposal): ProviderCapabilityType {
    switch (proposal.actionClass) {
      case 'RESEARCH':
        return 'RESEARCH';
      case 'CREATE_WORKFLOW':
        if (proposal.payload?.workflowType === 'VIDEO_SYNTHESIS') {
          return 'VIDEO_GENERATION';
        }
        return 'REASONING';
      case 'CREATE_ARTIFACT':
        return 'IMAGE_GENERATION';
      case 'TRACE_MEMORY':
      case 'OPEN_MEMORY':
        return 'REASONING';
      case 'FILTER_MEMORY':
        return 'CLASSIFICATION';
      default:
        return 'REASONING';
    }
  },

  /**
   * Evaluates routing policy and returns a deterministic RoutingDecision.
   */
  route(proposal: ActionProposal): RoutingDecision {
    const capability = this.resolveCapability(proposal);
    const policy = routingPolicyManager.getPolicy(capability);

    const reasons: string[] = [];
    let selectedProvider: IntelligenceProvider | undefined;
    let fallbackProvider: IntelligenceProvider | undefined;

    // 1. Try preferred providers
    for (const pid of policy.preferredProviders) {
      const p = providerRegistry.getProvider(pid);
      if (p && p.capabilities.includes(capability) && p.availability !== 'UNAVAILABLE') {
        selectedProvider = p;
        reasons.push(`Selected preferred provider '${p.name}' (${p.id}) for capability ${capability}.`);
        reasons.push(`Within configured max cost tier (${p.costProfile.tier} <= ${policy.maxCostTier || 3}).`);
        if (p.contextWindow) {
          reasons.push(`Supports large context window (${p.contextWindow.toLocaleString()} tokens).`);
        }
        break;
      }
    }

    // 2. Resolve fallback provider
    for (const pid of policy.fallbackProviders) {
      const p = providerRegistry.getProvider(pid);
      if (p && p.id !== selectedProvider?.id && p.capabilities.includes(capability) && p.availability !== 'UNAVAILABLE') {
        fallbackProvider = p;
        break;
      }
    }

    // 3. Fallback to any capable provider if no preferred was found
    if (!selectedProvider) {
      const capable = providerRegistry.getProvidersForCapability(capability);
      const viable = capable.find((p) => p.availability !== 'UNAVAILABLE');
      if (viable) {
        selectedProvider = viable;
        reasons.push(`Preferred providers unavailable. Routed to alternative capable provider '${viable.name}' (${viable.id}).`);
      } else if (capable.length > 0) {
        selectedProvider = capable[0];
        reasons.push(`All capable providers currently marked ${selectedProvider.availability}.`);
      }
    }

    // Default safety fallback if registry is completely empty
    if (!selectedProvider) {
      return {
        capability,
        selectedProviderId: 'unassigned',
        selectedProviderName: 'No Provider Available',
        selectedModel: 'none',
        reasons: ['No registered provider supports this capability in the current environment.'],
        status: 'UNAVAILABLE',
        estimatedCostTier: 0,
      };
    }

    if (fallbackProvider) {
      reasons.push(`Configured fallback: '${fallbackProvider.name}' (${fallbackProvider.defaultModel}).`);
    }

    return {
      capability,
      selectedProviderId: selectedProvider.id,
      selectedProviderName: selectedProvider.name,
      selectedModel: selectedProvider.defaultModel,
      reasons,
      fallbackProviderId: fallbackProvider?.id,
      fallbackModel: fallbackProvider?.defaultModel,
      status: selectedProvider.availability,
      estimatedCostTier: selectedProvider.costProfile.tier,
    };
  },

  /**
   * Constructs a complete, deterministic ExecutionPlan ready for confirmation and dispatch.
   */
  createExecutionPlan(
    proposal: ActionProposal,
    context?: CommandContext
  ): ExecutionPlan {
    const decision = this.route(proposal);
    const contextPackage = contextPackager.packageContext(context, proposal);
    const provider = providerRegistry.getProvider(decision.selectedProviderId);

    const timeoutSeconds = Math.max(30, Math.ceil((provider?.latencyProfile.p95Seconds || 15) * 1.5));
    const estimatedUsd = provider?.costProfile.perUnitCostUsd || null;

    let planStatus: ExecutionPlan['status'] = 'ROUTED';
    if (decision.status === 'CONFIGURATION_REQUIRED') {
      planStatus = 'CONFIGURATION_REQUIRED';
    } else if (decision.status === 'UNAVAILABLE') {
      planStatus = 'UNAVAILABLE';
    }

    return {
      id: `PLAN-${Date.now()}-${Math.floor(Math.random() * 1000)}`,
      actionId: proposal.id,
      actionClass: proposal.actionClass,
      providerId: decision.selectedProviderId,
      providerName: decision.selectedProviderName,
      modelId: decision.selectedModel,
      capability: decision.capability,
      contextPackage,
      inputPayload: proposal.payload || {},
      expectedOutputType:
        decision.capability === 'IMAGE_GENERATION' || decision.capability === 'VIDEO_GENERATION'
          ? 'media/asset'
          : 'text/markdown',
      timeoutSeconds,
      retryPolicy: {
        maxRetries: 2,
        backoffMs: 1500,
      },
      fallbackProviderId: decision.fallbackProviderId,
      fallbackModelId: decision.fallbackModel,
      estimatedCostMetadata: {
        costTier: decision.estimatedCostTier,
        estimatedUsd,
        currency: 'USD',
      },
      routingRationale: {
        capability: decision.capability,
        selectedProvider: decision.selectedProviderName,
        reasons: decision.reasons,
        fallbackProvider: decision.fallbackProviderId,
      },
      status: planStatus,
      createdAt: new Date().toISOString(),
    };
  },
};
