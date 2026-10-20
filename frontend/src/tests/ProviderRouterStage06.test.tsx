/**
 * AryaOS V1 — Stage 06: Intelligence Provider Router & Execution Boundary Tests
 *
 * Comprehensive unit and integration verification for:
 * 1. Provider Registry (registration, capability lookup, availability, duplicate handling)
 * 2. Provider Router & Routing Policy (capability matching, preferred/fallback resolution, deterministic rationale)
 * 3. Context Packager (relevant selection, exclusion of irrelevant memories, entity/timeline extraction, token sizing)
 * 4. Execution Adapter & Lifecycle (success, failure, timeout, cancellation, automated fallback)
 * 5. Security & Secret Hygiene (sanitization, no secrets in plans/logs/memory events)
 * 6. Semantic Memory Ledger Ingestion (event creation on success/failure, metadata provenance)
 */

import React from 'react';
import { render, screen, fireEvent, act, renderHook } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { providerRegistry } from '../services/providerRegistry';
import { routingPolicyManager } from '../services/routingPolicy';
import { contextPackager } from '../services/contextPackager';
import { providerRouter } from '../services/providerRouter';
import { providerExecutionAdapter } from '../services/providerExecutionAdapter';
import { executionGateway } from '../services/executionGateway';
import { resultNormalizer } from '../services/resultNormalizer';
import { actionProposalService } from '../services/actionProposalService';
import { commandParser } from '../services/commandParser';
import { memoryContextService } from '../services/memoryContextService';
import { useMemoryArchive } from '../hooks/useMemoryArchive';
import { useSpatialCommand } from '../hooks/useSpatialCommand';
import { SpatialActionPreview } from '../components/spatial/SpatialActionPreview';
import {
  IntelligenceProvider,
  ExecutionPlan,
} from '../types/intelligenceProvider';

describe('AryaOS V1 Stage 06 — Intelligence Provider Router & Real Execution Boundary', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    providerRegistry.resetToDefaults();
    routingPolicyManager.resetToDefaults();
    providerExecutionAdapter.initializeDefaultAdapters();
    actionProposalService.resetMemoryEvents();
    executionGateway.resetState();
  });

  describe('1. Provider Registry', () => {
    it('registers and retrieves default intelligence providers accurately', () => {
      const providers = providerRegistry.getAllProviders();
      expect(providers.length).toBeGreaterThanOrEqual(8);

      const gemini = providerRegistry.getProvider('gemini');
      expect(gemini).toBeDefined();
      expect(gemini?.name).toBe('Google Gemini');
      expect(gemini?.capabilities).toContain('RESEARCH');
      expect(gemini?.capabilities).toContain('REASONING');
      expect(gemini?.costProfile.tier).toBe(1);

      const fal = providerRegistry.getProvider('fal');
      expect(fal).toBeDefined();
      expect(fal?.capabilities).toContain('IMAGE_GENERATION');
      expect(fal?.capabilities).toContain('VIDEO_GENERATION');
    });

    it('filters providers for capability ordered cheapest-first', () => {
      const researchProviders = providerRegistry.getProvidersForCapability('RESEARCH');
      expect(researchProviders.length).toBeGreaterThanOrEqual(3);

      // Verify cheapest first (tier 1 < tier 2 < tier 3)
      for (let i = 0; i < researchProviders.length - 1; i++) {
        expect(researchProviders[i].costProfile.tier).toBeLessThanOrEqual(
          researchProviders[i + 1].costProfile.tier
        );
      }
    });

    it('updates provider availability status correctly', () => {
      const updated = providerRegistry.updateProviderAvailability('gemini', 'UNAVAILABLE');
      expect(updated).toBe(true);

      const gemini = providerRegistry.getProvider('gemini');
      expect(gemini?.availability).toBe('UNAVAILABLE');

      // Non-existent provider
      const nonExistent = providerRegistry.updateProviderAvailability('fake_provider_xyz', 'AVAILABLE');
      expect(nonExistent).toBe(false);
    });

    it('handles duplicate provider registration cleanly by updating definitions', () => {
      const customProvider: IntelligenceProvider = {
        id: 'gemini',
        name: 'Google Gemini Updated',
        category: 'LLM',
        capabilities: ['RESEARCH'],
        availability: 'AVAILABLE',
        costProfile: { tier: 1, description: 'Updated profile' },
        latencyProfile: { averageSeconds: 3.0 },
        supportedModels: ['gemini-custom'],
        defaultModel: 'gemini-custom',
      };

      providerRegistry.registerProvider(customProvider);
      const retrieved = providerRegistry.getProvider('gemini');
      expect(retrieved?.name).toBe('Google Gemini Updated');
      expect(retrieved?.defaultModel).toBe('gemini-custom');
    });
  });

  describe('2. Provider Router & Routing Policy', () => {
    it('deterministically routes research proposals to preferred providers with rationale', () => {
      const cmd = commandParser.parse('Create a research task from this memory', 'MEM-0001');
      const proposal = actionProposalService.createProposal(cmd)!;

      const decision = providerRouter.route(proposal);
      expect(decision.capability).toBe('RESEARCH');
      expect(decision.selectedProviderId).toBe('gemini');
      expect(decision.selectedModel).toBe('gemini-3.1-pro-preview');
      expect(decision.reasons.length).toBeGreaterThanOrEqual(2);
      expect(decision.reasons.some((r) => r.includes('preferred provider'))).toBe(true);
      expect(decision.fallbackProviderId).toBeDefined();
    });

    it('routes video generation proposals to specialized media providers', () => {
      const cmd = commandParser.parse('Generate a production plan from this decision', 'MEM-0002');
      const proposal = actionProposalService.createProposal(cmd)!;

      // When payload is video synthesis
      proposal.payload = { workflowType: 'VIDEO_SYNTHESIS' };
      const decision = providerRouter.route(proposal);
      expect(decision.capability).toBe('VIDEO_GENERATION');
      expect(['fal', 'kling']).toContain(decision.selectedProviderId);
    });

    it('falls back to secondary provider when preferred provider is marked UNAVAILABLE', () => {
      providerRegistry.updateProviderAvailability('gemini', 'UNAVAILABLE');

      const cmd = commandParser.parse('Create a research task from this memory', 'MEM-0001');
      const proposal = actionProposalService.createProposal(cmd)!;

      const decision = providerRouter.route(proposal);
      // Gemini unavailable -> should route to next preferred (openrouter) or fallback (anthropic)
      expect(decision.selectedProviderId).not.toBe('gemini');
      expect(['openrouter', 'anthropic']).toContain(decision.selectedProviderId);
      expect(decision.reasons.some((r) => r.includes('openrouter') || r.includes('anthropic'))).toBe(true);
    });

    it('produces complete execution plans without embedding secrets', () => {
      const cmd = commandParser.parse('Create a research task from this memory', 'MEM-0001');
      const proposal = actionProposalService.createProposal(cmd)!;
      const context = memoryContextService.buildContext('MEM-0001');

      const plan = providerRouter.createExecutionPlan(proposal, context);
      expect(plan.id).toContain('PLAN-');
      expect(plan.actionId).toBe(proposal.id);
      expect(plan.providerId).toBe('gemini');
      expect(plan.contextPackage.memoryContext.length).toBeGreaterThan(0);
      expect(plan.timeoutSeconds).toBeGreaterThanOrEqual(15);
      expect(plan.status).toBe('ROUTED');

      // Verify NO secrets in the plan
      const planString = JSON.stringify(plan);
      expect(planString).not.toContain('AIza');
      expect(planString).not.toContain('Bearer');
      expect(planString).not.toContain('secret');
      expect(planString).not.toContain('password');
    });
  });

  describe('3. Context Packaging Layer', () => {
    it('packages active memory and direct relationships while excluding unrelated memories', () => {
      const cmd = commandParser.parse('Create a research task from this memory', 'MEM-0001');
      const proposal = actionProposalService.createProposal(cmd)!;
      const context = memoryContextService.buildContext('MEM-0001');

      const pkg = contextPackager.packageContext(context, proposal, { maxMemories: 5 });
      expect(pkg.memoryContext.length).toBeLessThanOrEqual(5);

      // Active memory must be first with highest relevance
      expect(pkg.memoryContext[0].id).toBe('MEM-0001');
      expect(pkg.memoryContext[0].relevanceScore).toBe(1.0);

      // Must include direct relationship
      const relIds = context.directRelationships.map((r) => r.memory.id);
      const packagedIds = pkg.memoryContext.map((m) => m.id);
      const hasDirectRel = relIds.some((id) => packagedIds.includes(id));
      expect(hasDirectRel).toBe(true);

      // Must not package all 24 memories
      expect(packagedIds.length).toBeLessThan(24);
    });

    it('extracts unique entity context and timeline context correctly', () => {
      const cmd = commandParser.parse('Create a research task from this memory', 'MEM-0001');
      const proposal = actionProposalService.createProposal(cmd)!;
      const context = memoryContextService.buildContext('MEM-0001');

      const pkg = contextPackager.packageContext(context, proposal);
      expect(pkg.entityContext.length).toBeGreaterThan(0);

      // Verify entity deduplication
      const names = pkg.entityContext.map((e) => e.name);
      const uniqueNames = Array.from(new Set(names));
      expect(names.length).toBe(uniqueNames.length);

      // Verify timeline context predecessor/successor
      expect(pkg.timelineContext?.predecessor).toBeDefined();
    });

    it('compresses text summaries exceeding the character threshold', () => {
      const longText = 'This is an extremely long memory record summary designed to test text compression. '.repeat(10);
      const compressed = contextPackager.compressText(longText, 60);
      expect(compressed.length).toBeLessThanOrEqual(60);
      expect(compressed.endsWith('...')).toBe(true);
    });
  });

  describe('4. Execution Adapter & Lifecycle', () => {
    it('executes plans successfully and normalizes output, latency, and usage telemetry', async () => {
      const cmd = commandParser.parse('Create a research task from this memory', 'MEM-0001');
      const proposal = actionProposalService.createProposal(cmd)!;
      const plan = providerRouter.createExecutionPlan(proposal);

      const result = await providerExecutionAdapter.executePlan(plan);
      expect(['SUCCESS', 'SUCCEEDED']).toContain(result.status);
      expect(result.providerId).toBe('gemini');
      expect(result.output).toBeDefined();
      expect(result.output).toContain('Architectural Research Synthesis');
      expect(result.latencyMs).toBeGreaterThanOrEqual(0);
      expect(result.usage?.estimatedCost).toBeDefined();
    });

    it('honestly reports CONFIGURATION_REQUIRED when provider credentials are missing', async () => {
      // Mark provider as requiring configuration
      providerRegistry.updateProviderAvailability('gemini', 'CONFIGURATION_REQUIRED');

      const cmd = commandParser.parse('Create a research task from this memory', 'MEM-0001');
      const proposal = actionProposalService.createProposal(cmd)!;
      const plan = providerRouter.createExecutionPlan(proposal);

      const result = await providerExecutionAdapter.executePlan(plan);
      expect(result.status).toBe('CONFIGURATION_REQUIRED');
      expect(result.error).toContain('CONFIGURATION_REQUIRED');
      expect(result.output).toBeUndefined();
    });

    it('handles operator cancellation cleanly prior to or during execution', async () => {
      const cmd = commandParser.parse('Create a research task from this memory', 'MEM-0001');
      const proposal = actionProposalService.createProposal(cmd)!;
      const plan = providerRouter.createExecutionPlan(proposal);

      const controller = new AbortController();
      controller.abort(); // Cancel before start

      const result = await providerExecutionAdapter.executePlan(plan, controller.signal);
      expect(result.status).toBe('CANCELLED');
      expect(result.error).toContain('cancelled');
    });

    it('handles provider timeout and triggers automated fallback to secondary provider', async () => {
      // Register custom failing/timeout adapter for primary provider
      providerExecutionAdapter.registerAdapter({
        providerId: 'gemini',
        validateConfiguration: () => ({ isValid: true }),
        execute: async () => {
          throw new Error('Upstream provider connection refused (504 Gateway Timeout)');
        },
      });

      const cmd = commandParser.parse('Create a research task from this memory', 'MEM-0001');
      const proposal = actionProposalService.createProposal(cmd)!;
      const plan = providerRouter.createExecutionPlan(proposal);
      plan.fallbackProviderId = 'openrouter';

      const result = await providerExecutionAdapter.executePlan(plan);
      // Secondary fallback should have executed
      expect(['SUCCESS', 'FALLBACK_SUCCEEDED']).toContain(result.status);
      expect(result.metadata?.fallbackUsed).toBe(true);
      expect(result.metadata?.originalProvider).toBe('gemini');
      expect(result.providerId).toBe('openrouter');
    });
  });

  describe('5. Security & Sanitization', () => {
    it('sanitizes bearer tokens, API keys, and sensitive parameters from outputs and error messages', () => {
      const rawError = 'Failed to connect: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.xyz and api_key=sk-1234567890abcdef1234567890';
      const sanitized = resultNormalizer.sanitizeText(rawError);

      expect(sanitized).not.toContain('eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.xyz');
      expect(sanitized).not.toContain('sk-1234567890abcdef1234567890');
      expect(sanitized).toContain('Bearer [REDACTED]');
      expect(sanitized).toContain('api_key=[REDACTED]');
    });

    it('ensures no sensitive credentials exist in memory events or telemetry', async () => {
      const cmd = commandParser.parse('Create a research task from this memory', 'MEM-0001');
      const proposal = actionProposalService.createProposal(cmd)!;
      const plan = providerRouter.createExecutionPlan(proposal);

      await providerExecutionAdapter.executePlan(plan);

      const events = actionProposalService.getMemoryEvents();
      expect(events.length).toBeGreaterThan(0);

      const eventString = JSON.stringify(events[0]);
      expect(eventString).not.toContain('Bearer');
      expect(eventString).not.toContain('api_key');
      expect(eventString).not.toContain('secret');
      expect(eventString).not.toContain('password');
    });
  });

  describe('6. Semantic Memory Ledger Ingestion', () => {
    it('appends verified memory events on successful execution with provider metadata', async () => {
      const cmd = commandParser.parse('Create a research task from this memory', 'MEM-0001');
      const proposal = actionProposalService.createProposal(cmd)!;
      const plan = providerRouter.createExecutionPlan(proposal);

      const result = await providerExecutionAdapter.executePlan(plan);
      expect(['SUCCESS', 'SUCCEEDED']).toContain(result.status);

      const events = actionProposalService.getMemoryEvents();
      expect(events.length).toBeGreaterThan(0);

      const latestEvent = events[0];
      expect(['INTELLIGENCE_ROUTER_SUCCESS', 'INTELLIGENCE_GATEWAY_SUCCEEDED']).toContain(latestEvent.type);
      expect(latestEvent.action).toBe('RESEARCH');
      expect(latestEvent.metadata?.provider).toBe('gemini');
      expect(latestEvent.metadata?.capability).toBe('RESEARCH');
      expect(latestEvent.metadata?.latencyMs).toBeGreaterThanOrEqual(0);
    });

    it('records failed executions as planned/recorded events without fabricating success', async () => {
      providerExecutionAdapter.registerAdapter({
        providerId: 'gemini',
        validateConfiguration: () => ({ isValid: false, reason: 'CONFIGURATION_REQUIRED' }),
        execute: async (p) => resultNormalizer.normalizeFailure(p, 'CONFIGURATION_REQUIRED', 'Missing key', 10),
      });

      const cmd = commandParser.parse('Create a research task from this memory', 'MEM-0001');
      const proposal = actionProposalService.createProposal(cmd)!;
      const plan = providerRouter.createExecutionPlan(proposal);
      plan.fallbackProviderId = undefined; // Disable fallback for this test

      const result = await providerExecutionAdapter.executePlan(plan);
      expect(result.status).toBe('CONFIGURATION_REQUIRED');

      const events = actionProposalService.getMemoryEvents();
      const latestEvent = events[0];
      expect([
        'INTELLIGENCE_ROUTER_CONFIGURATION_REQUIRED',
        'INTELLIGENCE_GATEWAY_CONFIGURATION_REQUIRED',
      ]).toContain(latestEvent.type);
      expect(latestEvent.status).toBe('PLANNED');
    });
  });

  describe('7. Spatial UI Transparency Integration', () => {
    it('renders intelligence routing block in SpatialActionPreview with provider, model, and context', () => {
      const cmd = commandParser.parse('Create a research task from this memory', 'MEM-0001');
      const proposal = actionProposalService.createProposal(cmd)!;
      const plan = providerRouter.createExecutionPlan(proposal);

      render(
        <SpatialActionPreview
          proposal={proposal}
          executionPlan={plan}
          onConfirm={vi.fn()}
          onCancel={vi.fn()}
        />
      );

      expect(screen.getByTestId('spatial-routing-block')).toBeInTheDocument();
      expect(screen.getByTestId('routing-provider-name')).toHaveTextContent('Google Gemini');
      expect(screen.getByTestId('routing-model-id')).toHaveTextContent('gemini-3.1-pro-preview');
      expect(screen.getByTestId('routing-plan-status')).toHaveTextContent('ROUTED');
    });

    it('coordinates full hook lifecycle from command submission to real provider dispatch', async () => {
      const { result: memHook } = renderHook(() => useMemoryArchive());
      const { result: cmdHook } = renderHook(() => useSpatialCommand(memHook.current));

      // Submit consequential command
      act(() => {
        cmdHook.current.submitCommand('Create a research task from this memory');
      });

      expect(cmdHook.current.commandState).toBe('PROPOSING_ACTION');
      expect(cmdHook.current.activeProposal).not.toBeNull();
      expect(cmdHook.current.activeExecutionPlan).not.toBeNull();
      expect(cmdHook.current.activeExecutionPlan?.providerId).toBe('gemini');

      // Operator confirms proposal
      await act(async () => {
        cmdHook.current.confirmProposal();
        // Wait for execution timeout (150ms)
        await new Promise((r) => setTimeout(r, 200));
      });

      expect(cmdHook.current.commandState).toBe('RESULT');
      expect(cmdHook.current.lastResult?.status).toBe('EXECUTED');
      expect(cmdHook.current.lastExecutionResult).toBeDefined();
      expect(['SUCCESS', 'SUCCEEDED']).toContain(cmdHook.current.lastExecutionResult?.status);
    });
  });
});
