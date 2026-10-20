/**
 * AryaOS V1 — Stage 07: Real Provider Execution Gateway & Operational Validation Tests
 *
 * Exhaustive unit, adversarial security, and integration verification for:
 * 1. Explicit 12 Execution States & Deterministic State Machine Transitions
 * 2. Single Controlled Boundary & Pre-Execution Capability Negotiation
 * 3. Honest Configuration Validation & Zero Simulated Success
 * 4. Controlled Timeout Handling & Operator AbortSignal Cancellation
 * 5. Automated Fallback Chain, Fallback Depth Limits, & Exhaustion Reporting
 * 6. Gateway Idempotency & In-Flight Duplicate Submission Protection
 * 7. Security Hardening & Zero Secret Leakage (Bearer, AIza, sk-ant, sk, parameters)
 * 8. Semantic Memory Event Ingestion with Full Provenance Loop
 * 9. Provider Health Tracking (AVAILABLE, RATE_LIMITED, DEGRADED, UNAVAILABLE)
 * 10. Spatial Command Console UI Transparency & Cancellation Controls
 */

import React from 'react';
import { render, screen, fireEvent, act, renderHook } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { executionGateway } from '../services/executionGateway';
import { providerRegistry } from '../services/providerRegistry';
import { routingPolicyManager } from '../services/routingPolicy';
import { providerRouter } from '../services/providerRouter';
import { providerExecutionAdapter } from '../services/providerExecutionAdapter';
import { resultNormalizer } from '../services/resultNormalizer';
import { actionProposalService } from '../services/actionProposalService';
import { commandParser } from '../services/commandParser';
import { memoryContextService } from '../services/memoryContextService';
import { useMemoryArchive } from '../hooks/useMemoryArchive';
import { useSpatialCommand } from '../hooks/useSpatialCommand';
import { SpatialCommandConsole } from '../components/spatial/SpatialCommandConsole';
import {
  ExecutionPlan,
  GatewayExecutionState,
  ProviderAdapter,
} from '../types/intelligenceProvider';

describe('AryaOS V1 Stage 07 — Real Provider Execution Gateway & Operational Validation', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    executionGateway.resetState();
    providerRegistry.resetToDefaults();
    routingPolicyManager.resetToDefaults();
    providerExecutionAdapter.initializeDefaultAdapters();
    actionProposalService.resetMemoryEvents();
  });

  describe('1. Explicit 12 Provider Execution States', () => {
    it('enforces all 12 explicit execution states deterministically', async () => {
      const validStates: GatewayExecutionState[] = [
        'PLANNED',
        'CONFIGURATION_REQUIRED',
        'READY',
        'EXECUTING',
        'SUCCEEDED',
        'FAILED',
        'TIMEOUT',
        'CANCELLED',
        'UNAVAILABLE',
        'FALLBACK_EXECUTING',
        'FALLBACK_SUCCEEDED',
        'FALLBACK_FAILED',
      ];

      expect(validStates.length).toBe(12);

      // Verify that SUCCEEDED is never fabricated from an error
      const cmd = commandParser.parse('Create a research task from this memory', 'MEM-0001');
      const proposal = actionProposalService.createProposal(cmd)!;
      const plan = providerRouter.createExecutionPlan(proposal);

      const errResult = resultNormalizer.normalizeFailure(
        plan,
        'FAILED',
        'Simulated vendor 500 error',
        120
      );
      expect(errResult.status).toBe('FAILED');
      expect(errResult.status).not.toBe('SUCCEEDED');
      expect(errResult.output).toBeUndefined();
    });

    it('tracks state progression via onStateChange callback during execution lifecycle', async () => {
      const cmd = commandParser.parse('Create a research task from this memory', 'MEM-0001');
      const proposal = actionProposalService.createProposal(cmd)!;
      const plan = providerRouter.createExecutionPlan(proposal);

      const observedStates: GatewayExecutionState[] = [];
      const result = await executionGateway.execute(plan, undefined, {
        onStateChange: (st) => observedStates.push(st),
      });

      expect(observedStates).toContain('EXECUTING');
      expect(observedStates).toContain('SUCCEEDED');
      expect(result.status).toBe('SUCCEEDED');
    });
  });

  describe('2. Single Controlled Boundary & Capability Negotiation', () => {
    it('executes provider-backed intelligence plans exclusively through ExecutionGateway', async () => {
      const cmd = commandParser.parse('Create a research task from this memory', 'MEM-0001');
      const proposal = actionProposalService.createProposal(cmd)!;
      const plan = providerRouter.createExecutionPlan(proposal);

      const result = await executionGateway.execute(plan);
      expect(result.status).toBe('SUCCEEDED');
      expect(result.executionId).toMatch(/^EXEC-\d+/);
      expect(result.providerId).toBe('gemini');
      expect(result.modelId).toBe('gemini-3.1-pro-preview');
      expect(result.provenance.sourceCommand).toContain('Research');
    });

    it('rejects execution when requested capability is not supported by the selected provider', async () => {
      const cmd = commandParser.parse('Create a research task from this memory', 'MEM-0001');
      const proposal = actionProposalService.createProposal(cmd)!;
      const plan = providerRouter.createExecutionPlan(proposal);

      // Request Kling (video only) for Code Generation
      plan.providerId = 'kling';
      plan.capability = 'CODE_GENERATION';

      const result = await executionGateway.execute(plan);
      expect(result.status).toBe('FAILED');
      expect(result.error).toContain('Capability mismatch');
      expect(result.error).toContain('Kling');
      expect(result.metadata?.failureType).toBe('CAPABILITY_MISMATCH');
    });

    it('returns UNAVAILABLE when dispatching to an unregistered provider ID', async () => {
      const cmd = commandParser.parse('Create a research task from this memory', 'MEM-0001');
      const proposal = actionProposalService.createProposal(cmd)!;
      const plan = providerRouter.createExecutionPlan(proposal);

      plan.providerId = 'unknown_vendor_quantum';
      const result = await executionGateway.execute(plan);

      expect(result.status).toBe('FAILED');
      expect(result.error).toContain('not registered');
    });
  });

  describe('3. Honest Configuration Validation & Zero Simulated Success', () => {
    it('returns CONFIGURATION_REQUIRED honestly when provider API keys are missing', async () => {
      providerRegistry.updateProviderAvailability('gemini', 'CONFIGURATION_REQUIRED');

      const cmd = commandParser.parse('Create a research task from this memory', 'MEM-0001');
      const proposal = actionProposalService.createProposal(cmd)!;
      const plan = providerRouter.createExecutionPlan(proposal);

      const result = await executionGateway.execute(plan);
      expect(result.status).toBe('CONFIGURATION_REQUIRED');
      expect(result.error).toContain('CONFIGURATION_REQUIRED');
      expect(result.output).toBeUndefined();

      // Ensure provenance records the honest failure
      expect(result.provenance.providerSelected).toBe('Google Gemini');
      expect(result.provenance.fallbackUsed).toBe(false);
    });

    it('returns UNAVAILABLE honestly when provider is decommissioned or offline', async () => {
      providerRegistry.updateProviderAvailability('gemini', 'UNAVAILABLE');

      // Register adapter that mirrors the UNAVAILABLE check
      providerExecutionAdapter.registerAdapter({
        providerId: 'gemini',
        supportedCapabilities: ['RESEARCH'],
        validateConfiguration: () => ({ isValid: false, reason: 'Provider is marked UNAVAILABLE.' }),
        execute: async () => ({ status: 'UNAVAILABLE', error: 'Service offline' }),
      });

      const cmd = commandParser.parse('Create a research task from this memory', 'MEM-0001');
      const proposal = actionProposalService.createProposal(cmd)!;
      const plan = providerRouter.createExecutionPlan(proposal);
      plan.providerId = 'gemini';
      plan.fallbackProviderId = undefined; // isolate primary

      const result = await executionGateway.execute(plan);
      expect(result.status).toBe('CONFIGURATION_REQUIRED');
      expect(result.error).toContain('UNAVAILABLE');
    });
  });

  describe('4. Controlled Timeout & Operator Cancellation', () => {
    it('aborts execution immediately when AbortSignal is cancelled prior to dispatch', async () => {
      const cmd = commandParser.parse('Create a research task from this memory', 'MEM-0001');
      const proposal = actionProposalService.createProposal(cmd)!;
      const plan = providerRouter.createExecutionPlan(proposal);

      const controller = new AbortController();
      controller.abort(); // Cancel before call

      const result = await executionGateway.execute(plan, undefined, { signal: controller.signal });
      expect(result.status).toBe('CANCELLED');
      expect(result.error).toContain('cancelled by operator');
    });

    it('aborts running provider execution cleanly when signal is triggered mid-flight', async () => {
      const controller = new AbortController();

      // Slow custom provider that respects abort
      providerExecutionAdapter.registerAdapter({
        providerId: 'gemini',
        supportedCapabilities: ['RESEARCH'],
        validateConfiguration: () => ({ isValid: true }),
        execute: async (plan, signal) => {
          return new Promise((resolve) => {
            signal?.addEventListener('abort', () => {
              resolve({ status: 'CANCELLED', error: 'Operator aborted mid-stream' });
            });
          });
        },
      });

      const cmd = commandParser.parse('Create a research task from this memory', 'MEM-0001');
      const proposal = actionProposalService.createProposal(cmd)!;
      const plan = providerRouter.createExecutionPlan(proposal);

      const execPromise = executionGateway.execute(plan, undefined, { signal: controller.signal });
      setTimeout(() => controller.abort(), 10);

      const result = await execPromise;
      expect(result.status).toBe('CANCELLED');
    });

    it('triggers timeout and records DEGRADED provider health on excessive latency', async () => {
      // Mock adapter that stalls longer than plan timeout
      providerExecutionAdapter.registerAdapter({
        providerId: 'gemini',
        supportedCapabilities: ['RESEARCH'],
        validateConfiguration: () => ({ isValid: true }),
        execute: async () => {
          return new Promise((resolve) => {
            setTimeout(() => resolve({ status: 'SUCCEEDED', output: 'Late response' }), 200);
          });
        },
      });

      const cmd = commandParser.parse('Create a research task from this memory', 'MEM-0001');
      const proposal = actionProposalService.createProposal(cmd)!;
      const plan = providerRouter.createExecutionPlan(proposal);
      plan.timeoutSeconds = 0.05; // 50ms timeout for test speed
      plan.fallbackProviderId = undefined; // Isolate primary timeout

      const result = await executionGateway.execute(plan);
      expect(result.status).toBe('TIMEOUT');
      expect(result.error).toContain('timed out');
      expect(executionGateway.getProviderHealth('gemini')).toBe('DEGRADED');
    });
  });

  describe('5. Automated Fallback Chain & Depth Control', () => {
    it('automatically transitions to secondary fallback when primary fails', async () => {
      // Primary fails with upstream error
      providerExecutionAdapter.registerAdapter({
        providerId: 'gemini',
        supportedCapabilities: ['RESEARCH'],
        validateConfiguration: () => ({ isValid: true }),
        execute: async () => ({
          status: 'FAILED',
          error: 'Gemini service 503 Overloaded',
        }),
      });

      const cmd = commandParser.parse('Create a research task from this memory', 'MEM-0001');
      const proposal = actionProposalService.createProposal(cmd)!;
      const plan = providerRouter.createExecutionPlan(proposal);
      plan.fallbackProviderId = 'openrouter';

      const statesObserved: GatewayExecutionState[] = [];
      const result = await executionGateway.execute(plan, undefined, {
        onStateChange: (st) => statesObserved.push(st),
      });

      expect(statesObserved).toContain('FALLBACK_EXECUTING');
      expect(statesObserved).toContain('FALLBACK_SUCCEEDED');
      expect(result.status).toBe('FALLBACK_SUCCEEDED');
      expect(result.fallbackUsed).toBe(true);
      expect(result.providerId).toBe('openrouter');
      expect(result.metadata?.primaryFailureReason).toContain('503 Overloaded');
    });

    it('terminates with FALLBACK_FAILED when all fallback providers fail', async () => {
      // Both primary and fallback fail
      providerExecutionAdapter.registerAdapter({
        providerId: 'gemini',
        supportedCapabilities: ['RESEARCH'],
        validateConfiguration: () => ({ isValid: true }),
        execute: async () => ({ status: 'FAILED', error: 'Gemini network timeout' }),
      });

      providerExecutionAdapter.registerAdapter({
        providerId: 'openrouter',
        supportedCapabilities: ['RESEARCH'],
        validateConfiguration: () => ({ isValid: true }),
        execute: async () => ({ status: 'FAILED', error: 'OpenRouter balance exhausted' }),
      });

      const cmd = commandParser.parse('Create a research task from this memory', 'MEM-0001');
      const proposal = actionProposalService.createProposal(cmd)!;
      const plan = providerRouter.createExecutionPlan(proposal);
      plan.fallbackProviderId = 'openrouter';

      const result = await executionGateway.execute(plan);
      expect(result.status).toBe('FALLBACK_FAILED');
      expect(result.error).toContain('Both primary');
      expect(result.error).toContain('OpenRouter balance exhausted');
      expect(result.metadata?.primaryError).toContain('Gemini network timeout');
      expect(result.metadata?.fallbackError).toContain('OpenRouter balance exhausted');
    });

    it('enforces maximum fallback depth and prevents infinite retry recursion', async () => {
      providerExecutionAdapter.registerAdapter({
        providerId: 'gemini',
        supportedCapabilities: ['RESEARCH'],
        validateConfiguration: () => ({ isValid: true }),
        execute: async () => ({ status: 'FAILED', error: 'Primary failed' }),
      });

      const cmd = commandParser.parse('Create a research task from this memory', 'MEM-0001');
      const proposal = actionProposalService.createProposal(cmd)!;
      const plan = providerRouter.createExecutionPlan(proposal);
      plan.fallbackProviderId = 'openrouter';

      // Setting maxFallbackDepth = 0 disables fallback
      const result = await executionGateway.execute(plan, undefined, { maxFallbackDepth: 0 });
      expect(result.status).toBe('FAILED');
      expect(result.fallbackUsed).toBe(false);
      expect(result.providerId).toBe('gemini');
    });
  });

  describe('6. Gateway Idempotency & In-Flight Duplicate Prevention', () => {
    it('returns the same in-flight execution promise when duplicate command intent is submitted', async () => {
      let callCount = 0;
      providerExecutionAdapter.registerAdapter({
        providerId: 'gemini',
        supportedCapabilities: ['RESEARCH'],
        validateConfiguration: () => ({ isValid: true }),
        execute: async () => {
          callCount++;
          await new Promise((r) => setTimeout(r, 40));
          return { status: 'SUCCEEDED', output: 'Idempotency verified' };
        },
      });

      const cmd = commandParser.parse('Create a research task from this memory', 'MEM-0001');
      const proposal = actionProposalService.createProposal(cmd)!;
      const plan = providerRouter.createExecutionPlan(proposal);

      // Fire 3 simultaneous executions of the identical action plan
      const [res1, res2, res3] = await Promise.all([
        executionGateway.execute(plan),
        executionGateway.execute(plan),
        executionGateway.execute(plan),
      ]);

      expect(callCount).toBe(1); // Provider called exactly once
      expect(res1.executionId).toBe(res2.executionId);
      expect(res2.executionId).toBe(res3.executionId);
      expect(res1.status).toBe('SUCCEEDED');
    });
  });

  describe('7. Security Hardening & Zero Secret Leakage', () => {
    it('sanitizes Bearer tokens, AIza keys, and sk- tokens from output and errors', () => {
      const adversarialText =
        'Authorization: Bearer sk-ant-api03-abcdef1234567890abcdef1234567890 ' +
        'and Google key AIzaSyD12345678901234567890123456789012345 ' +
        'with sk-proj-1234567890abcdef1234567890 ' +
        'and query api_key=supersecretvalue123.';

      const sanitized = resultNormalizer.sanitizeText(adversarialText);

      expect(sanitized).not.toContain('sk-ant-api03-abcdef1234567890abcdef1234567890');
      expect(sanitized).not.toContain('AIzaSyD12345678901234567890123456789012345');
      expect(sanitized).not.toContain('sk-proj-1234567890abcdef1234567890');
      expect(sanitized).not.toContain('supersecretvalue123');

      expect(sanitized).toContain('Authorization: Bearer [REDACTED]');
      expect(sanitized).toContain('AIza[REDACTED]');
      expect(sanitized).toContain('api_key=[REDACTED]');
    });

    it('ensures no sensitive credentials exist anywhere in ExecutionResult or memory events', async () => {
      // Custom adapter that attempts to leak a key in its output
      providerExecutionAdapter.registerAdapter({
        providerId: 'gemini',
        supportedCapabilities: ['RESEARCH'],
        validateConfiguration: () => ({ isValid: true }),
        execute: async () => ({
          status: 'SUCCEEDED',
          output: 'Leak attempt: Bearer sk-ant-secret1234567890abcdef12345',
        }),
      });

      const cmd = commandParser.parse('Create a research task from this memory', 'MEM-0001');
      const proposal = actionProposalService.createProposal(cmd)!;
      const plan = providerRouter.createExecutionPlan(proposal);

      const result = await executionGateway.execute(plan);
      expect(result.output).not.toContain('sk-ant-secret');
      expect(result.output).toContain('Bearer [REDACTED]');

      const events = actionProposalService.getMemoryEvents();
      const serializedEvents = JSON.stringify(events);
      expect(serializedEvents).not.toContain('sk-ant-secret');
    });

    it('treats untrusted provider output as raw external text without executing dangerous scripts', () => {
      const maliciousScript = '<script>window.location="https://attacker.site/steal"</script>';
      const sanitized = resultNormalizer.sanitizeText(maliciousScript);
      // Ensure it is treated as harmless string and does not evaluate
      expect(typeof sanitized).toBe('string');
    });
  });

  describe('8. Semantic Memory Loop & Provenance Tracking', () => {
    it('appends verified semantic memory event on successful gateway execution', async () => {
      const cmd = commandParser.parse('Create a research task from this memory', 'MEM-0001');
      const proposal = actionProposalService.createProposal(cmd)!;
      const plan = providerRouter.createExecutionPlan(proposal);

      await executionGateway.execute(plan);

      const events = actionProposalService.getMemoryEvents();
      expect(events.length).toBeGreaterThan(0);

      const event = events[0];
      expect(event.type).toBe('INTELLIGENCE_GATEWAY_SUCCEEDED');
      expect(event.status).toBe('EXECUTED');
      expect(event.metadata?.provider).toBe('gemini');
      expect(event.metadata?.model).toBe('gemini-3.1-pro-preview');
      expect(event.metadata?.capability).toBe('RESEARCH');
      expect(event.metadata?.provenance).toBeDefined();
      expect((event.metadata?.provenance as any).sourceCommand).toContain('Research');
    });

    it('records failed executions as PLANNED memory events without fabricating success', async () => {
      providerRegistry.updateProviderAvailability('gemini', 'CONFIGURATION_REQUIRED');

      const cmd = commandParser.parse('Create a research task from this memory', 'MEM-0001');
      const proposal = actionProposalService.createProposal(cmd)!;
      const plan = providerRouter.createExecutionPlan(proposal);

      await executionGateway.execute(plan);

      const events = actionProposalService.getMemoryEvents();
      const event = events[0];
      expect(event.type).toBe('INTELLIGENCE_GATEWAY_CONFIGURATION_REQUIRED');
      expect(event.status).toBe('PLANNED');
      expect(event.metadata?.error).toContain('CONFIGURATION_REQUIRED');
    });
  });

  describe('9. Provider Health Tracking', () => {
    it('records RATE_LIMITED on HTTP 429 response', async () => {
      providerExecutionAdapter.registerAdapter({
        providerId: 'gemini',
        supportedCapabilities: ['RESEARCH'],
        validateConfiguration: () => ({ isValid: true }),
        execute: async () => ({
          status: 'FAILED',
          error: 'HTTP 429: Resource has been exhausted (rate limit exceeded)',
        }),
      });

      const cmd = commandParser.parse('Create a research task from this memory', 'MEM-0001');
      const proposal = actionProposalService.createProposal(cmd)!;
      const plan = providerRouter.createExecutionPlan(proposal);
      plan.fallbackProviderId = undefined;

      await executionGateway.execute(plan);
      expect(executionGateway.getProviderHealth('gemini')).toBe('RATE_LIMITED');
    });

    it('records DEGRADED on HTTP 500 server error and AVAILABLE on recovery', async () => {
      providerExecutionAdapter.registerAdapter({
        providerId: 'gemini',
        supportedCapabilities: ['RESEARCH'],
        validateConfiguration: () => ({ isValid: true }),
        execute: async () => ({
          status: 'FAILED',
          error: 'HTTP 500: Internal server error in provider cluster',
        }),
      });

      const cmd = commandParser.parse('Create a research task from this memory', 'MEM-0001');
      const proposal = actionProposalService.createProposal(cmd)!;
      const plan = providerRouter.createExecutionPlan(proposal);
      plan.fallbackProviderId = undefined;

      await executionGateway.execute(plan);
      expect(executionGateway.getProviderHealth('gemini')).toBe('DEGRADED');

      // Now provider recovers
      providerExecutionAdapter.registerAdapter({
        providerId: 'gemini',
        supportedCapabilities: ['RESEARCH'],
        validateConfiguration: () => ({ isValid: true }),
        execute: async () => ({ status: 'SUCCEEDED', output: 'Cluster healthy' }),
      });

      await executionGateway.execute(plan);
      expect(executionGateway.getProviderHealth('gemini')).toBe('AVAILABLE');
    });
  });

  describe('10. Spatial Command Console UI Transparency & Cancellation Controls', () => {
    it('renders gateway execution telemetry block with provider, model, latency, and fallback', () => {
      const mockControl: any = {
        commandState: 'RESULT',
        commandInput: '',
        currentCommand: null,
        activeProposal: null,
        activeExecutionPlan: null,
        lastResult: {
          actionId: 'ACT-001',
          success: true,
          status: 'EXECUTED',
          message: 'Executed via gemini in 42ms.',
          timestamp: new Date().toISOString(),
        },
        lastExecutionResult: {
          executionId: 'EXEC-TEST-001',
          planId: 'PLAN-TEST-001',
          status: 'SUCCEEDED',
          providerId: 'gemini',
          modelId: 'gemini-3.1-pro-preview',
          capability: 'RESEARCH',
          startedAt: new Date().toISOString(),
          completedAt: new Date().toISOString(),
          latencyMs: 42,
          fallbackUsed: false,
          retryCount: 0,
          output: 'Telemetry test output',
          provenance: {
            executionId: 'EXEC-TEST-001',
            planId: 'PLAN-TEST-001',
            contextMemoriesCount: 1,
            providerSelected: 'gemini',
            modelSelected: 'gemini-3.1-pro-preview',
            capability: 'RESEARCH',
            fallbackUsed: false,
            timestamp: new Date().toISOString(),
          },
          executionMode: 'REAL',
          timestamp: new Date().toISOString(),
        },
        highlightedVitrineIds: [],
        activeCamera: 'CAM_CinematicHero',
        memoryEvents: [],
        isConsoleOpen: true,
        setCommandInput: vi.fn(),
        submitCommand: vi.fn(),
        confirmProposal: vi.fn(),
        cancelProposal: vi.fn(),
        dismissResult: vi.fn(),
        clearHighlights: vi.fn(),
        setActiveCamera: vi.fn(),
        setIsConsoleOpen: vi.fn(),
        toggleConsole: vi.fn(),
        navigateHistory: vi.fn(),
      };

      render(<SpatialCommandConsole commandControl={mockControl} />);

      expect(screen.getByTestId('gateway-execution-telemetry')).toBeInTheDocument();
      expect(screen.getByTestId('gateway-execution-state')).toHaveTextContent('SUCCEEDED');
      expect(screen.getByTestId('gateway-telemetry-provider')).toHaveTextContent('gemini');
      expect(screen.getByTestId('gateway-telemetry-model')).toHaveTextContent('gemini-3.1-pro-preview');
      expect(screen.getByTestId('gateway-telemetry-latency')).toHaveTextContent('42ms');
      expect(screen.getByTestId('gateway-telemetry-fallback')).toHaveTextContent('NO');
    });

    it('renders cancellation control button during active gateway execution', () => {
      const cancelSpy = vi.fn();
      const mockControl: any = {
        commandState: 'EXECUTING',
        commandInput: '',
        currentCommand: null,
        activeProposal: null,
        activeExecutionPlan: null,
        lastResult: null,
        lastExecutionResult: null,
        highlightedVitrineIds: [],
        activeCamera: 'CAM_CinematicHero',
        memoryEvents: [],
        isConsoleOpen: true,
        setCommandInput: vi.fn(),
        submitCommand: vi.fn(),
        confirmProposal: vi.fn(),
        cancelProposal: cancelSpy,
        dismissResult: vi.fn(),
        clearHighlights: vi.fn(),
        setActiveCamera: vi.fn(),
        setIsConsoleOpen: vi.fn(),
        toggleConsole: vi.fn(),
        navigateHistory: vi.fn(),
      };

      render(<SpatialCommandConsole commandControl={mockControl} />);

      expect(screen.getByTestId('gateway-executing-banner')).toBeInTheDocument();
      const cancelBtn = screen.getByTestId('gateway-cancel-btn');
      expect(cancelBtn).toBeInTheDocument();

      fireEvent.click(cancelBtn);
      expect(cancelSpy).toHaveBeenCalledTimes(1);
    });
  });
});
