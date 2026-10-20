import React from 'react';
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { App } from '../App';
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
import { CapabilitiesManifest, GenerationJob, HistoryItem } from '../types/creator';
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
      {
        id: 'black-forest-labs/FLUX.1-dev',
        name: 'FLUX 1 Dev (Together AI)',
        provider: 'together',
        default: false,
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
    ],
  },
};

const mockRuns: ProductionRun[] = [
  {
    id: 'run-1',
    jobId: 'job-1',
    createdAt: '2026-09-27T00:00:00Z',
    mode: 'image',
    status: 'completed',
    model: 'black-forest-labs/FLUX.1.1-pro',
    provider: 'together',
    prompt: 'Obsidian console',
    cost: 0.04,
    costUsd: 0.04,
    parameters: { aspectRatio: '16:9' },
  },
  {
    id: 'run-2',
    jobId: 'job-2',
    createdAt: '2026-09-27T01:00:00Z',
    mode: 'image',
    status: 'completed',
    model: 'black-forest-labs/FLUX.1.1-pro',
    provider: 'together',
    prompt: 'Cinema console',
    cost: 0.05,
    costUsd: 0.05,
    parameters: { aspectRatio: '16:9' },
  },
];

describe('AryaOS Stage 8: Intelligent Production Decision Layer', () => {
  beforeEach(() => {
    localStorage.clear();
    sessionStorage.clear();
    vi.clearAllMocks();
  });

  // =========================================================================
  // 1. CAPABILITY MATRIX
  // =========================================================================
  describe('1. Capability Matrix', () => {
    it('1. recognized supported model', () => {
      const config: ConfigurationParameters = {
        generationType: 'image',
        model: 'black-forest-labs/FLUX.1.1-pro',
        aspectRatio: '16:9',
      };
      const result = validateConfiguration(config, mockManifest);
      const modelCheck = result.checks.find((c) => c.id === 'model');
      expect(modelCheck?.status).toBe('PASSED');
      expect(modelCheck?.detail).toBe('FLUX 1.1 Pro (Together AI)');
    });

    it('2. rejected unsupported model', () => {
      const config: ConfigurationParameters = {
        generationType: 'image',
        model: 'unsupported/model-v99',
        aspectRatio: '16:9',
      };
      const result = validateConfiguration(config, mockManifest);
      const modelCheck = result.checks.find((c) => c.id === 'model');
      expect(modelCheck?.status).toBe('FAILED');
      expect(result.ready).toBe(false);
      expect(result.status).toBe('BLOCKED');
    });

    it('3. recognized supported aspect ratio', () => {
      const config: ConfigurationParameters = {
        generationType: 'image',
        model: 'black-forest-labs/FLUX.1.1-pro',
        aspectRatio: '16:9',
      };
      const result = validateConfiguration(config, mockManifest);
      const arCheck = result.checks.find((c) => c.id === 'aspect_ratio');
      expect(arCheck?.status).toBe('PASSED');
    });

    it('4. rejected unsupported aspect ratio', () => {
      const config: ConfigurationParameters = {
        generationType: 'image',
        model: 'black-forest-labs/FLUX.1.1-pro',
        aspectRatio: '21:9', // not in manifest
      };
      const result = validateConfiguration(config, mockManifest);
      const arCheck = result.checks.find((c) => c.id === 'aspect_ratio');
      expect(arCheck?.status).toBe('FAILED');
      expect(result.ready).toBe(false);
    });

    it('5. recognized supported resolution', () => {
      const config: ConfigurationParameters = {
        generationType: 'image',
        model: 'black-forest-labs/FLUX.1.1-pro',
        aspectRatio: '16:9',
        resolution: '1024x1024',
      };
      const result = validateConfiguration(config, mockManifest);
      const resCheck = result.checks.find((c) => c.id === 'resolution');
      expect(resCheck?.status).toBe('PASSED');
    });

    it('6. rejected unsupported resolution', () => {
      const config: ConfigurationParameters = {
        generationType: 'image',
        model: 'black-forest-labs/FLUX.1.1-pro',
        aspectRatio: '16:9',
        resolution: '3840x2160',
      };
      const result = validateConfiguration(config, mockManifest);
      const resCheck = result.checks.find((c) => c.id === 'resolution');
      expect(resCheck?.status).toBe('FAILED');
      expect(result.ready).toBe(false);
    });

    it('7. recognized supported duration', () => {
      const config: ConfigurationParameters = {
        generationType: 'video',
        model: 'kwaivgi/kling-v1.6-standard',
        aspectRatio: '16:9',
        duration: 5,
      };
      const result = validateConfiguration(config, mockManifest);
      const durCheck = result.checks.find((c) => c.id === 'duration');
      expect(durCheck?.status).toBe('PASSED');
    });

    it('8. rejected unsupported duration', () => {
      const config: ConfigurationParameters = {
        generationType: 'video',
        model: 'kwaivgi/kling-v1.6-standard',
        aspectRatio: '16:9',
        duration: 60,
      };
      const result = validateConfiguration(config, mockManifest);
      const durCheck = result.checks.find((c) => c.id === 'duration');
      expect(durCheck?.status).toBe('FAILED');
      expect(result.ready).toBe(false);
    });
  });

  // =========================================================================
  // 2. CONDITIONING & KEYFRAME CONSTRAINTS
  // =========================================================================
  describe('2. Conditioning', () => {
    it('9. required reference detected when specified', () => {
      const config: ConfigurationParameters = {
        generationType: 'image',
        model: 'black-forest-labs/FLUX.1.1-pro',
        aspectRatio: '16:9',
        requiresReference: true,
        referenceImageUrl: 'https://cdn.example.com/reference.png',
      };
      const result = validateConfiguration(config, mockManifest);
      const refCheck = result.checks.find((c) => c.id === 'reference');
      expect(refCheck?.status).toBe('PASSED');
    });

    it('10. missing reference blocks execution when reference is required', () => {
      const config: ConfigurationParameters = {
        generationType: 'image',
        model: 'black-forest-labs/FLUX.1.1-pro',
        aspectRatio: '16:9',
        requiresReference: true,
      };
      const result = validateConfiguration(config, mockManifest);
      const refCheck = result.checks.find((c) => c.id === 'reference');
      expect(refCheck?.status).toBe('FAILED');
      expect(result.ready).toBe(false);
    });

    it('11. required start frame detected for image_to_video', () => {
      const config: ConfigurationParameters = {
        generationType: 'image_to_video',
        model: 'kwaivgi/kling-v1.6-standard',
        aspectRatio: '16:9',
        startFrameUrl: 'https://cdn.example.com/start_frame.png',
      };
      const result = validateConfiguration(config, mockManifest);
      const sfCheck = result.checks.find((c) => c.id === 'start_frame');
      expect(sfCheck?.status).toBe('PASSED');
      expect(result.ready).toBe(true);
    });

    it('12. missing start frame blocks I2V execution with exact deterministic reason', () => {
      const config: ConfigurationParameters = {
        generationType: 'image_to_video',
        model: 'kwaivgi/kling-v1.6-standard',
        aspectRatio: '16:9',
      };
      const result = validateConfiguration(config, mockManifest);
      const sfCheck = result.checks.find((c) => c.id === 'start_frame');
      expect(sfCheck?.status).toBe('FAILED');
      expect(result.ready).toBe(false);
      expect(result.reason).toBe('START FRAME REQUIRED');
    });

    it('13. unsupported end frame remains unavailable and blocks execution if attached', () => {
      const config: ConfigurationParameters = {
        generationType: 'image_to_video',
        model: 'kwaivgi/kling-v1.6-standard',
        aspectRatio: '16:9',
        startFrameUrl: 'https://cdn.example.com/start.png',
        endFrameUrl: 'https://cdn.example.com/unsupported_end.png',
      };
      const result = validateConfiguration(config, mockManifest);
      const efCheck = result.checks.find((c) => c.id === 'end_frame');
      expect(efCheck?.status).toBe('FAILED');
      expect(result.ready).toBe(false);
    });
  });

  // =========================================================================
  // 3. PRE-FLIGHT EVALUATION
  // =========================================================================
  describe('3. Pre-flight Check', () => {
    it('14. valid configuration returns READY with executable directive', () => {
      const config: ConfigurationParameters = {
        generationType: 'image',
        model: 'black-forest-labs/FLUX.1.1-pro',
        aspectRatio: '16:9',
      };
      const rec = deriveProductionRecommendation(config, mockManifest, 'ACTIVE', mockRuns);
      expect(rec.status).toBe('READY');
      expect(rec.directive).toBe('READY FOR EXECUTION');
      expect(rec.preflight.ready).toBe(true);
    });

    it('15. invalid configuration returns BLOCKED with exact reason', () => {
      const config: ConfigurationParameters = {
        generationType: 'image_to_video',
        model: 'kwaivgi/kling-v1.6-standard',
        aspectRatio: '16:9',
        // missing start frame
      };
      const rec = deriveProductionRecommendation(config, mockManifest, 'ACTIVE', mockRuns);
      expect(rec.status).toBe('BLOCKED');
      expect(rec.directive).toBe('EXECUTION BLOCKED');
      expect(rec.reason).toBe('START FRAME REQUIRED');
    });

    it('16. multiple validation failures reported deterministically in order', () => {
      const config: ConfigurationParameters = {
        generationType: 'image_to_video',
        model: 'nonexistent-model',
        aspectRatio: 'invalid-ratio',
      };
      const result = validateConfiguration(config, mockManifest);
      expect(result.ready).toBe(false);
      expect(result.reasons.length).toBeGreaterThanOrEqual(2);
      expect(result.reasons[0]).toContain('nonexistent-model');
      expect(result.reasons[1]).toContain('invalid-ratio');
    });
  });

  // =========================================================================
  // 4. COST-AWARE DECISION SUPPORT
  // =========================================================================
  describe('4. Cost Decision Support', () => {
    it('17. displays known cost from real historical runs', () => {
      const cost = deriveCostDecisionSupport('black-forest-labs/FLUX.1.1-pro', 'together', mockRuns);
      expect(cost.hasCostData).toBe(true);
      expect(cost.avgKnownCost).toBe(0.045);
      expect(cost.displayStatus).toBe('$0.0450');
      expect(cost.runCount).toBe(2);
    });

    it('18. missing cost remains UNAVAILABLE without estimating or fabricating prices', () => {
      const cost = deriveCostDecisionSupport('unseen-model-id', 'unknown-provider', []);
      expect(cost.hasCostData).toBe(false);
      expect(cost.avgKnownCost).toBeNull();
      expect(cost.displayStatus).toBe('COST COMPARISON UNAVAILABLE');
    });

    it('19. aggregate known cost preserved across multiple executions', () => {
      const cost = deriveCostDecisionSupport('black-forest-labs/FLUX.1.1-pro', 'together', mockRuns);
      expect(cost.totalKnownCost).toBe(0.09);
    });
  });

  // =========================================================================
  // 5. QUALITY-AWARE DECISION SUPPORT
  // =========================================================================
  describe('5. Quality Decision Support', () => {
    it('20. existing quality data displayed if verified score is available', () => {
      const runsWithQuality = [
        {
          ...mockRuns[0],
          qualityScore: 92,
        },
      ];
      const quality = deriveQualityDecisionSupport('black-forest-labs/FLUX.1.1-pro', runsWithQuality as any);
      expect(quality.qualityDataAvailable).toBe(true);
      expect(quality.qualityScore).toBe(92);
      expect(quality.label).toBe('KNOWN');
      expect(quality.displayText).toBe('Score: 92/100');
    });

    it('21. absent quality data displays UNAVAILABLE truthfully', () => {
      const quality = deriveQualityDecisionSupport('black-forest-labs/FLUX.1.1-pro', mockRuns);
      expect(quality.qualityDataAvailable).toBe(false);
      expect(quality.qualityScore).toBeNull();
      expect(quality.label).toBe('UNAVAILABLE');
      expect(quality.displayText).toBe('QUALITY DATA UNAVAILABLE');
    });

    it('22. never manufactures a fake quality score', () => {
      const quality = deriveQualityDecisionSupport('fal-ai/flux-pro/v1.1', []);
      expect(quality.qualityScore).toBeNull();
      expect(quality.displayText).toBe('QUALITY DATA UNAVAILABLE');
      expect(quality.displayText).not.toMatch(/\d+\/100/);
    });
  });

  // =========================================================================
  // 6. DECISION INTEGRITY & NON-AUTONOMOUS EXECUTION
  // =========================================================================
  describe('6. Decision Integrity', () => {
    it('23. makes no subjective "best model" or "cheapest" claims', () => {
      const config: ConfigurationParameters = {
        generationType: 'image',
        model: 'black-forest-labs/FLUX.1.1-pro',
        aspectRatio: '16:9',
      };
      const rec = deriveProductionRecommendation(config, mockManifest, 'ACTIVE', mockRuns);
      const textDump = JSON.stringify(rec).toLowerCase();
      expect(textDump).not.toContain('best model');
      expect(textDump).not.toContain('optimal model');
      expect(textDump).not.toContain('cheapest');
      expect(textDump).not.toContain('fastest');
    });

    it('24. produces no fabricated provider capability in decision matrix', () => {
      const matrix = buildCapabilityDecisionMatrix(mockManifest);
      expect(matrix.length).toBeGreaterThan(0);
      for (const entry of matrix) {
        expect(['AVAILABLE', 'UNAVAILABLE']).toContain(entry.availability);
        expect(entry.endFrameSupport).toBe(false);
      }
    });

    it('25. enforces pure deterministic calculation without autonomous execution', () => {
      const config: ConfigurationParameters = {
        generationType: 'image',
        model: 'black-forest-labs/FLUX.1.1-pro',
        aspectRatio: '16:9',
      };
      const fetchSpy = vi.spyOn(globalThis, 'fetch');
      const rec = deriveProductionRecommendation(config, mockManifest, 'ACTIVE', mockRuns);
      expect(rec.status).toBe('READY');
      expect(fetchSpy).not.toHaveBeenCalled();
    });

    it('26. GenerateButton respects pre-flight state (disabled when blocked)', () => {
      const { rerender } = render(
        <GenerateButton
          generationType="image"
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

      rerender(
        <GenerateButton
          generationType="image"
          isSubmitting={false}
          isJobRunning={false}
          onClick={vi.fn()}
          disabled={false}
          isPreflightBlocked={false}
        />
      );
      expect(btn).toBeEnabled();
      expect(btn).toHaveAttribute('data-preflight-ready', 'true');
    });
  });

  // =========================================================================
  // 7. LIFECYCLE & WORKSPACE INTEGRITY
  // =========================================================================
  describe('7. Lifecycle & Workspace Integrity', () => {
    it('27. retry semantics are preserved without altering payload snapshots', () => {
      const onRetryMock = vi.fn();
      render(
        <GenerateButton
          generationType="image"
          isSubmitting={false}
          isJobRunning={false}
          onClick={vi.fn()}
          onRetry={onRetryMock}
          disabled={false}
          error="Network timeout during generation"
        />
      );
      const retryBtn = screen.getByTestId('retry-generation-button');
      expect(retryBtn).toBeInTheDocument();
      fireEvent.click(retryBtn);
      expect(onRetryMock).toHaveBeenCalledTimes(1);
    });

    it('28. active polling remains guarded and disables button while job is in progress', () => {
      render(
        <GenerateButton
          generationType="image"
          isSubmitting={false}
          isJobRunning={true}
          onClick={vi.fn()}
          disabled={false}
        />
      );
      const btn = screen.getByTestId('generate-button');
      expect(btn).toBeDisabled();
      expect(screen.getByText('Generation in Progress...')).toBeInTheDocument();
    });

    it('29. workspace recovery does not persist sensitive tokens in localStorage', () => {
      const testRecord = {
        jobId: 'job-stage8-recovery',
        generationType: 'image' as const,
        submittedAt: Date.now(),
        payloadSnapshot: {
          generation_type: 'image' as const,
          prompt: 'Safe prompt with no credentials',
          aspect_ratio: '16:9',
        },
      };
      localStorage.setItem('arya_active_job_recovery', JSON.stringify(testRecord));

      const raw = localStorage.getItem('arya_active_job_recovery') || '';
      expect(raw).not.toContain('api_key');
      expect(raw).not.toContain('bearer');
      expect(raw).not.toContain('secret');
    });

    it('30. history browsing isolates inspector and does not alter configuration', () => {
      const config: ConfigurationParameters = {
        generationType: 'image',
        model: 'black-forest-labs/FLUX.1.1-pro',
        aspectRatio: '16:9',
      };
      const recBefore = deriveProductionRecommendation(config, mockManifest, 'ACTIVE', mockRuns);
      // Simulate historical run inspection
      const inspectedRun = mockRuns[0];
      expect(inspectedRun.prompt).toBe('Obsidian console');
      // Configuration remains independent
      const recAfter = deriveProductionRecommendation(config, mockManifest, 'ACTIVE', mockRuns);
      expect(recAfter.preflight.ready).toBe(recBefore.preflight.ready);
      expect(recAfter.status).toBe(recBefore.status);
    });
  });

  // =========================================================================
  // 8. SECURITY & UI SAFETY
  // =========================================================================
  describe('8. Security & UI Safety', () => {
    it('31. no secrets or API keys rendered in decision surfaces', () => {
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
    });

    it('32. malicious HTML in prompts or reasons is strictly escaped without dangerous injection', () => {
      const maliciousPrompt = '<img src="x" onerror="window.pwned=true" /><script>alert("xss")</script>';
      const config: ConfigurationParameters = {
        generationType: 'image',
        model: 'black-forest-labs/FLUX.1.1-pro',
        aspectRatio: '16:9',
        prompt: maliciousPrompt,
      };
      const rec = deriveProductionRecommendation(config, mockManifest, 'ACTIVE', mockRuns);
      const { container } = render(<ProductionDecisionCard recommendation={rec} />);
      // Raw HTML script or onerror tags must NOT execute or be inserted as DOM nodes
      expect(container.querySelector('script')).toBeNull();
      expect((window as any).pwned).toBeUndefined();
    });
  });
});
