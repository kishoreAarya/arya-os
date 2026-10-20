import React from 'react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import {
  buildCapabilityDecisionMatrix,
  validateConfiguration,
  deriveCostDecisionSupport,
  deriveQualityDecisionSupport,
  deriveProductionRecommendation,
  ConfigurationParameters,
} from '../types/productionDecision';
import { ProductionDecisionCard } from '../components/orchestration/ProductionDecisionCard';
import { GenerateButton } from '../components/GenerateButton';
import { OperationalStrip } from '../components/orchestration/OperationalStrip';
import { CapabilitiesManifest } from '../types/creator';
import { ProductionRun } from '../types/productionRun';

const mockManifest: CapabilitiesManifest = {
  generation_types: [
    { id: 'image', label: 'Image', description: 'High-fidelity image' },
    { id: 'video', label: 'Video', description: 'Text or keyframe video' },
    { id: 'image_to_video', label: 'Image → Video', description: 'Motion video' },
  ],
  aspect_ratios: [
    { id: '16:9', label: '16:9 (Landscape)', dimensions: '1344x768' },
    { id: '9:16', label: '9:16 (Portrait)', dimensions: '768x1344' },
    { id: '1:1', label: '1:1 (Square)', dimensions: '1024x1024' },
    { id: '4:5', label: '4:5 (Social)', dimensions: '864x1080' },
  ],
  resolutions: [
    { id: '1024x1024', label: '1024 × 1024 (Standard)' },
    { id: '1344x768', label: '1344 × 768 (Landscape HD)' },
  ],
  durations: [
    { value: 5, label: '5 seconds' },
    { value: 10, label: '10 seconds' },
  ],
  models: {
    image: [
      {
        id: 'black-forest-labs/FLUX.1.1-pro',
        name: 'FLUX 1.1 Pro (Together AI)',
        provider: 'together',
        default: true,
        cost_tier: 2,
        configured: true,
        start_frame: false,
        end_frame: false,
      },
    ],
    video: [
      {
        id: 'kwaivgi/kling-v1.6-standard',
        name: 'Kling 1.6 Standard',
        provider: 'kling',
        default: true,
        cost_tier: 2,
        configured: true,
        start_frame: true,
        end_frame: false,
      },
    ],
    image_to_video: [
      {
        id: 'kwaivgi/kling-v1.6-standard',
        name: 'Kling 1.6 Standard',
        provider: 'kling',
        default: true,
        cost_tier: 2,
        configured: true,
        start_frame: true,
        end_frame: false,
      },
      {
        id: 'unconfigured/model-disabled',
        name: 'Disabled Model',
        provider: 'offline',
        default: false,
        cost_tier: 1,
        configured: false,
        start_frame: true,
        end_frame: false,
      },
    ],
  },
};

const mockRuns: ProductionRun[] = [
  {
    id: 'run-stage9-1',
    jobId: 'job-stage9-1',
    createdAt: '2026-09-27T00:00:00Z',
    mode: 'image',
    status: 'completed',
    model: 'black-forest-labs/FLUX.1.1-pro',
    provider: 'together',
    prompt: 'Obsidian console telemetry',
    cost: 0.04,
    costUsd: 0.04,
    parameters: { aspectRatio: '16:9' },
  },
  {
    id: 'run-stage9-2',
    jobId: 'job-stage9-2',
    createdAt: '2026-09-27T01:00:00Z',
    mode: 'image',
    status: 'completed',
    model: 'black-forest-labs/FLUX.1.1-pro',
    provider: 'together',
    prompt: 'Quantum workstation',
    cost: 0.0385,
    costUsd: 0.0385,
    parameters: { aspectRatio: '16:9' },
  },
];

describe('AryaOS Stage 9: Production Intelligence UX Hardening & Decision Transparency', () => {
  beforeEach(() => {
    localStorage.clear();
    sessionStorage.clear();
    vi.clearAllMocks();
  });

  // =========================================================================
  // 1. DECISION LOGIC & REASON CODES
  // =========================================================================
  describe('1. Decision Logic & Reason Codes', () => {
    it('1. READY decision exposes correct reason code (CONFIGURATION_READY)', () => {
      const config: ConfigurationParameters = {
        generationType: 'image',
        model: 'black-forest-labs/FLUX.1.1-pro',
        aspectRatio: '16:9',
        prompt: 'Valid prompt for testing ready state',
      };
      const result = validateConfiguration(config, mockManifest);
      expect(result.ready).toBe(true);
      expect(result.status).toBe('READY');
      expect(result.reasonCode).toBe('CONFIGURATION_READY');
      expect(result.reasonCodes).toContain('CONFIGURATION_READY');
    });

    it('2. BLOCKED decision exposes correct reason code for missing prompt when empty', () => {
      const config: ConfigurationParameters = {
        generationType: 'image',
        model: 'black-forest-labs/FLUX.1.1-pro',
        aspectRatio: '16:9',
        prompt: '',
      };
      const result = validateConfiguration(config, mockManifest);
      expect(result.ready).toBe(false);
      expect(result.status).toBe('BLOCKED');
      expect(result.reasonCode).toBe('PROMPT_REQUIRED');
      expect(result.reasonCodes).toContain('PROMPT_REQUIRED');
    });

    it('3. WARNING remains distinct from BLOCKED and allows execution', () => {
      const config: ConfigurationParameters = {
        generationType: 'image',
        model: 'black-forest-labs/FLUX.1.1-pro',
        aspectRatio: '16:9',
        prompt: 'Valid prompt',
      };
      // When system state is DEGRADED, recommendation status is WARNING
      const rec = deriveProductionRecommendation(config, mockManifest, 'DEGRADED', mockRuns);
      expect(rec.status).toBe('WARNING');
      expect(rec.preflight.ready).toBe(true); // Pre-flight allows execution
      expect(rec.categorization.warnings.length).toBeGreaterThan(0);
      expect(rec.directive).toContain('READY FOR EXECUTION (SYSTEM DEGRADED)');
    });

    it('4. Multiple blocking reasons are deterministic and maintain priority', () => {
      const config: ConfigurationParameters = {
        generationType: 'image_to_video',
        model: 'unknown-model-xyz',
        aspectRatio: 'unsupported-aspect',
        prompt: 'a'.repeat(2005), // Too long
      };
      const result = validateConfiguration(config, mockManifest);
      expect(result.ready).toBe(false);
      expect(result.reasons.length).toBeGreaterThanOrEqual(2);
      expect(result.reasonCodes).toContain('MODEL_UNAVAILABLE');
      expect(result.reasonCodes).toContain('PROMPT_TOO_LONG');
      expect(result.reasonCodes).toContain('ASPECT_RATIO_UNSUPPORTED');
      expect(result.reasonCode).toBe(result.reasonCodes[0]);
    });

    it('5. Missing capability manifest blocks execution with CAPABILITY_MANIFEST_UNAVAILABLE', () => {
      const config: ConfigurationParameters = {
        generationType: 'image',
        model: 'black-forest-labs/FLUX.1.1-pro',
        aspectRatio: '16:9',
      };
      const result = validateConfiguration(config, null);
      expect(result.ready).toBe(false);
      expect(result.status).toBe('BLOCKED');
      expect(result.reasonCode).toBe('CAPABILITY_MANIFEST_UNAVAILABLE');
      expect(result.checks[0].source).toBe('SYSTEM_STATE');
    });

    it('6. Unsupported model blocks execution with MODEL_UNSUPPORTED or MODEL_UNAVAILABLE', () => {
      const config: ConfigurationParameters = {
        generationType: 'image',
        model: 'kwaivgi/kling-v1.6-standard', // Video model attempted in image mode
        aspectRatio: '16:9',
      };
      const result = validateConfiguration(config, mockManifest);
      expect(result.ready).toBe(false);
      expect(result.status).toBe('BLOCKED');
      expect(result.reasonCode).toBe('MODEL_UNSUPPORTED');
    });

    it('7. Missing start frame blocks I2V with START_FRAME_REQUIRED', () => {
      const config: ConfigurationParameters = {
        generationType: 'image_to_video',
        model: 'kwaivgi/kling-v1.6-standard',
        aspectRatio: '16:9',
        // startFrameUrl omitted
      };
      const result = validateConfiguration(config, mockManifest);
      expect(result.ready).toBe(false);
      expect(result.status).toBe('BLOCKED');
      expect(result.reasonCode).toBe('START_FRAME_REQUIRED');
      expect(result.reason).toBe('START FRAME REQUIRED');
    });

    it('8. Unsupported end frame blocks execution with END_FRAME_UNSUPPORTED', () => {
      const config: ConfigurationParameters = {
        generationType: 'image_to_video',
        model: 'kwaivgi/kling-v1.6-standard',
        aspectRatio: '16:9',
        startFrameUrl: 'https://cdn.example.com/start.png',
        endFrameUrl: 'https://cdn.example.com/unsupported-end.png',
      };
      const result = validateConfiguration(config, mockManifest);
      expect(result.ready).toBe(false);
      expect(result.status).toBe('BLOCKED');
      expect(result.reasonCode).toBe('END_FRAME_UNSUPPORTED');
    });
  });

  // =========================================================================
  // 2. EVIDENCE & SOURCE ATTRIBUTION
  // =========================================================================
  describe('2. Evidence & Source Attribution', () => {
    it('9. Capability facts identify their source as CAPABILITY_MANIFEST', () => {
      const config: ConfigurationParameters = {
        generationType: 'image',
        model: 'black-forest-labs/FLUX.1.1-pro',
        aspectRatio: '16:9',
      };
      const rec = deriveProductionRecommendation(config, mockManifest, 'ACTIVE', mockRuns);
      const modelFact = rec.categorization.facts.find((f) => f.id === 'model');
      expect(modelFact).toBeDefined();
      expect(modelFact?.source).toBe('CAPABILITY_MANIFEST');
      expect(modelFact?.value).toBe('FLUX 1.1 Pro (Together AI)');

      const providerFact = rec.categorization.facts.find((f) => f.id === 'provider');
      expect(providerFact?.source).toBe('CAPABILITY_MANIFEST');
      expect(providerFact?.value).toBe('together');
    });

    it('10. Historical cost identifies historical-run source as HISTORICAL_RUN', () => {
      const cost = deriveCostDecisionSupport('black-forest-labs/FLUX.1.1-pro', 'together', mockRuns);
      expect(cost.hasCostData).toBe(true);
      expect(cost.source).toBe('HISTORICAL_RUN');
      expect(cost.runCount).toBe(2);
      expect(cost.avgKnownCost).toBeCloseTo(0.03925, 4);
    });

    it('11. Quality unavailable is explicitly represented with source UNAVAILABLE', () => {
      const quality = deriveQualityDecisionSupport('black-forest-labs/FLUX.1.1-pro', mockRuns);
      expect(quality.qualityDataAvailable).toBe(false);
      expect(quality.qualityScore).toBeNull();
      expect(quality.source).toBe('UNAVAILABLE');
      expect(quality.displayText).toBe('QUALITY DATA UNAVAILABLE');
      expect(quality.reasonCode).toBe('QUALITY_DATA_UNAVAILABLE');
    });

    it('12. No fabricated benchmark values appear in quality support', () => {
      const quality = deriveQualityDecisionSupport('any-model-id', []);
      expect(quality.qualityScore).toBeNull();
      expect(quality.displayText).toBe('QUALITY DATA UNAVAILABLE');
      expect(quality.displayText).not.toMatch(/\d+\/100/);
    });

    it('13. No fabricated pricing appears when runs are absent', () => {
      const cost = deriveCostDecisionSupport('unseen-model', 'unknown-provider', []);
      expect(cost.hasCostData).toBe(false);
      expect(cost.avgKnownCost).toBeNull();
      expect(cost.displayStatus).toBe('COST COMPARISON UNAVAILABLE');
      expect(cost.source).toBe('UNAVAILABLE');
      expect(cost.reasonCode).toBe('COST_DATA_UNAVAILABLE');
    });
  });

  // =========================================================================
  // 3. CONFIGURATION INVALIDATION
  // =========================================================================
  describe('3. Configuration Invalidation', () => {
    it('14. Prompt changes recompute decision from VALID to TOO LONG', () => {
      const validConfig: ConfigurationParameters = {
        generationType: 'image',
        model: 'black-forest-labs/FLUX.1.1-pro',
        aspectRatio: '16:9',
        prompt: 'Normal prompt within bounds',
      };
      const recValid = deriveProductionRecommendation(validConfig, mockManifest, 'ACTIVE', mockRuns);
      expect(recValid.preflight.ready).toBe(true);

      const invalidConfig: ConfigurationParameters = {
        ...validConfig,
        prompt: 'x'.repeat(2005),
      };
      const recInvalid = deriveProductionRecommendation(invalidConfig, mockManifest, 'ACTIVE', mockRuns);
      expect(recInvalid.preflight.ready).toBe(false);
      expect(recInvalid.status).toBe('BLOCKED');
      expect(recInvalid.reasonCode).toBe('PROMPT_TOO_LONG');
    });

    it('15. Model changes recompute decision immediately', () => {
      const validConfig: ConfigurationParameters = {
        generationType: 'image',
        model: 'black-forest-labs/FLUX.1.1-pro',
        aspectRatio: '16:9',
      };
      const rec1 = deriveProductionRecommendation(validConfig, mockManifest, 'ACTIVE', mockRuns);
      expect(rec1.preflight.ready).toBe(true);

      const invalidConfig: ConfigurationParameters = {
        ...validConfig,
        model: 'nonexistent/model',
      };
      const rec2 = deriveProductionRecommendation(invalidConfig, mockManifest, 'ACTIVE', mockRuns);
      expect(rec2.preflight.ready).toBe(false);
      expect(rec2.status).toBe('BLOCKED');
    });

    it('16. Resolution changes recompute decision', () => {
      const validConfig: ConfigurationParameters = {
        generationType: 'image',
        model: 'black-forest-labs/FLUX.1.1-pro',
        aspectRatio: '16:9',
        resolution: '1024x1024',
      };
      const rec1 = deriveProductionRecommendation(validConfig, mockManifest, 'ACTIVE', mockRuns);
      expect(rec1.preflight.ready).toBe(true);

      const invalidConfig: ConfigurationParameters = {
        ...validConfig,
        resolution: '8192x4320', // unsupported
      };
      const rec2 = deriveProductionRecommendation(invalidConfig, mockManifest, 'ACTIVE', mockRuns);
      expect(rec2.preflight.ready).toBe(false);
      expect(rec2.reasonCode).toBe('RESOLUTION_UNSUPPORTED');
    });

    it('17. Aspect ratio changes recompute decision', () => {
      const validConfig: ConfigurationParameters = {
        generationType: 'image',
        model: 'black-forest-labs/FLUX.1.1-pro',
        aspectRatio: '16:9',
      };
      expect(deriveProductionRecommendation(validConfig, mockManifest, 'ACTIVE', mockRuns).preflight.ready).toBe(true);

      const invalidConfig: ConfigurationParameters = {
        ...validConfig,
        aspectRatio: '32:9', // unsupported
      };
      const rec = deriveProductionRecommendation(invalidConfig, mockManifest, 'ACTIVE', mockRuns);
      expect(rec.preflight.ready).toBe(false);
      expect(rec.reasonCode).toBe('ASPECT_RATIO_UNSUPPORTED');
    });

    it('18. Duration changes recompute decision', () => {
      const validConfig: ConfigurationParameters = {
        generationType: 'video',
        model: 'kwaivgi/kling-v1.6-standard',
        aspectRatio: '16:9',
        duration: 5,
      };
      expect(deriveProductionRecommendation(validConfig, mockManifest, 'ACTIVE', mockRuns).preflight.ready).toBe(true);

      const invalidConfig: ConfigurationParameters = {
        ...validConfig,
        duration: 999, // unsupported
      };
      const rec = deriveProductionRecommendation(invalidConfig, mockManifest, 'ACTIVE', mockRuns);
      expect(rec.preflight.ready).toBe(false);
      expect(rec.reasonCode).toBe('DURATION_UNSUPPORTED');
    });

    it('19. Start frame changes recompute decision', () => {
      const blockedConfig: ConfigurationParameters = {
        generationType: 'image_to_video',
        model: 'kwaivgi/kling-v1.6-standard',
        aspectRatio: '16:9',
      };
      const rec1 = deriveProductionRecommendation(blockedConfig, mockManifest, 'ACTIVE', mockRuns);
      expect(rec1.status).toBe('BLOCKED');
      expect(rec1.reasonCode).toBe('START_FRAME_REQUIRED');

      const readyConfig: ConfigurationParameters = {
        ...blockedConfig,
        startFrameUrl: 'https://cdn.example.com/start-frame.png',
      };
      const rec2 = deriveProductionRecommendation(readyConfig, mockManifest, 'ACTIVE', mockRuns);
      expect(rec2.preflight.ready).toBe(true);
      expect(rec2.status).toBe('READY');
      expect(rec2.reasonCode).toBe('CONFIGURATION_READY');
    });

    it('20. Capability refresh recomputes decision and detects removed model as MODEL_UNAVAILABLE', () => {
      const config: ConfigurationParameters = {
        generationType: 'image',
        model: 'black-forest-labs/FLUX.1.1-pro',
        aspectRatio: '16:9',
      };
      // Manifest before: has FLUX.1.1-pro
      const recBefore = deriveProductionRecommendation(config, mockManifest, 'ACTIVE', mockRuns);
      expect(recBefore.status).toBe('READY');

      // Refreshed manifest where FLUX.1.1-pro is no longer present
      const refreshedManifest: CapabilitiesManifest = {
        ...mockManifest,
        models: {
          ...mockManifest.models,
          image: [],
        },
      };
      const recAfter = deriveProductionRecommendation(config, refreshedManifest, 'ACTIVE', mockRuns);
      expect(recAfter.status).toBe('BLOCKED');
      expect(recAfter.reasonCode).toBe('MODEL_UNAVAILABLE');
      expect(recAfter.reasons[0]).toContain('MODEL NO LONGER AVAILABLE');
    });
  });

  // =========================================================================
  // 4. EXECUTION SAFETY & NON-AUTONOMOUS POLICY
  // =========================================================================
  describe('4. Execution Safety & Non-Autonomous Policy', () => {
    it('21. BLOCKED state disables execution button and shows preflight blocked attribute', () => {
      render(
        <GenerateButton
          generationType="image_to_video"
          isSubmitting={false}
          isJobRunning={false}
          onClick={vi.fn()}
          disabled={false}
          isPreflightBlocked={true}
        />
      );
      const btn = screen.getByTestId('generate-button');
      expect(btn).toBeDisabled();
      expect(btn).toHaveAttribute('data-preflight-ready', 'false');
    });

    it('22. READY state allows user to click execute button', () => {
      const onClickMock = vi.fn();
      render(
        <GenerateButton
          generationType="image"
          isSubmitting={false}
          isJobRunning={false}
          onClick={onClickMock}
          disabled={false}
          isPreflightBlocked={false}
        />
      );
      const btn = screen.getByTestId('generate-button');
      expect(btn).toBeEnabled();
      expect(btn).toHaveAttribute('data-preflight-ready', 'true');
      fireEvent.click(btn);
      expect(onClickMock).toHaveBeenCalledTimes(1);
    });

    it('23. No automatic execution occurs during decision generation', () => {
      const fetchSpy = vi.spyOn(globalThis, 'fetch');
      const config: ConfigurationParameters = {
        generationType: 'image',
        model: 'black-forest-labs/FLUX.1.1-pro',
        aspectRatio: '16:9',
      };
      deriveProductionRecommendation(config, mockManifest, 'ACTIVE', mockRuns);
      expect(fetchSpy).not.toHaveBeenCalled();
    });

    it('24. No automatic model switching occurs on unconfigured model', () => {
      const config: ConfigurationParameters = {
        generationType: 'image_to_video',
        model: 'unconfigured/model-disabled',
        aspectRatio: '16:9',
      };
      const rec = deriveProductionRecommendation(config, mockManifest, 'ACTIVE', mockRuns);
      // Keeps requested model, reports MODEL_UNAVAILABLE, does NOT switch to kling
      expect(rec.explanation.modelId).toBe('unconfigured/model-disabled');
      expect(rec.status).toBe('BLOCKED');
      expect(rec.reasonCode).toBe('MODEL_UNAVAILABLE');
    });

    it('25. Execution payload preview matches configuration parameters exactly without mutation', () => {
      const config: ConfigurationParameters = {
        generationType: 'image',
        model: 'black-forest-labs/FLUX.1.1-pro',
        aspectRatio: '16:9',
        resolution: '1344x768',
        prompt: 'Exact user specified prompt that should never be altered',
      };
      const rec = deriveProductionRecommendation(config, mockManifest, 'ACTIVE', mockRuns);
      expect(rec.executionPreview.mode).toBe('image');
      expect(rec.executionPreview.model).toBe('black-forest-labs/FLUX.1.1-pro');
      expect(rec.executionPreview.aspectRatio).toBe('16:9');
      expect(rec.executionPreview.resolution).toBe('1344x768');
      expect(rec.executionPreview.promptPreview).toBe('Exact user specified prompt that should never be altered');
      expect(rec.executionPreview.dispatchSteps.length).toBeGreaterThan(0);
    });
  });

  // =========================================================================
  // 5. SECURITY & EVIDENCE TRANSPARENCY UI
  // =========================================================================
  describe('5. Security & Evidence Transparency UI', () => {
    it('26. No credentials, secret keys, or bearer tokens rendered in UI', () => {
      const config: ConfigurationParameters = {
        generationType: 'image',
        model: 'black-forest-labs/FLUX.1.1-pro',
        aspectRatio: '16:9',
      };
      const rec = deriveProductionRecommendation(config, mockManifest, 'ACTIVE', mockRuns);
      const { container } = render(<ProductionDecisionCard recommendation={rec} />);
      const text = container.textContent || '';
      expect(text).not.toContain('AIzaSy');
      expect(text).not.toContain('sk-');
      expect(text).not.toContain('bearer');
      expect(text).not.toContain('secret');
      expect(text).not.toContain('password');
    });

    it('27. No auth tokens stored in decision recommendation state', () => {
      const config: ConfigurationParameters = {
        generationType: 'image',
        model: 'black-forest-labs/FLUX.1.1-pro',
        aspectRatio: '16:9',
      };
      const rec = deriveProductionRecommendation(config, mockManifest, 'ACTIVE', mockRuns);
      const dumped = JSON.stringify(rec);
      expect(dumped).not.toContain('token');
      expect(dumped).not.toContain('authorization');
      expect(dumped).not.toContain('api_key');
    });

    it('28. Renders Evidence Panel, Summary Table, Execution Preview, and Policy with safe escaping', () => {
      const config: ConfigurationParameters = {
        generationType: 'image',
        model: 'black-forest-labs/FLUX.1.1-pro',
        aspectRatio: '16:9',
        prompt: '<script>alert("xss")</script>',
      };
      const rec = deriveProductionRecommendation(config, mockManifest, 'ACTIVE', mockRuns);
      render(<ProductionDecisionCard recommendation={rec} />);

      // Verify Pre-flight summary table
      expect(screen.getByTestId('preflight-summary-table')).toBeInTheDocument();

      // Verify Evidence section toggle and panels
      expect(screen.getByTestId('decision-evidence-toggle')).toBeInTheDocument();
      expect(screen.getByTestId('decision-why-list')).toBeInTheDocument();
      expect(screen.getByTestId('decision-model-facts-panel')).toBeInTheDocument();
      expect(screen.getByTestId('decision-operational-facts-panel')).toBeInTheDocument();
      expect(screen.getByTestId('execution-preview-panel')).toBeInTheDocument();
      expect(screen.getByTestId('decision-execution-policy')).toBeInTheDocument();

      // Verify Execution Policy text
      expect(screen.getByText('NO AUTOMATIC MODEL SWITCH')).toBeInTheDocument();
      expect(screen.getByText('NO AUTOMATIC PARAMETER CHANGE')).toBeInTheDocument();
      expect(screen.getByText('USER CONFIRMATION REQUIRED')).toBeInTheDocument();

      // Safe script tag escaping
      expect(document.querySelector('script')).toBeNull();
      expect(screen.getByTestId('execution-preview-panel')).toHaveTextContent('alert("xss")');
    });
  });
});
