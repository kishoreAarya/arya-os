import React from 'react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import '@testing-library/jest-dom';
import {
  Project,
  Sequence,
  Shot,
  PersistedProjectEnvelope,
} from '../types/productionTimeline';
import {
  STORAGE_KEY_PROJECT,
  CURRENT_SCHEMA_VERSION,
  sanitizeForPersistence,
  serializeProject,
  validatePersistedProject,
  deserializeProject,
  saveProject,
  loadProject,
  clearProject,
  hasPersistedProject,
  getPersistedProjectEnvelope,
  recomputeDerivedState,
  checkForInterruptedShots,
  reconcileProjectWithHistory,
} from '../utils/projectPersistence';
import { ProjectRecoveryBar } from '../components/timeline/ProjectRecoveryBar';
import { ProductionTimeline } from '../components/timeline/ProductionTimeline';
import { OperationalStrip } from '../components/orchestration/OperationalStrip';
import { CapabilitiesManifest, HistoryItem, GenerationJob } from '../types/creator';

const mockManifest: CapabilitiesManifest = {
  generation_types: [
    { id: 'image', label: 'Image', description: 'Keyframe image generation' },
    { id: 'video', label: 'Video', description: 'Text or keyframe-driven video clip' },
    { id: 'image_to_video', label: 'Image → Video', description: 'Animate image using motion models' },
  ],
  aspect_ratios: [
    { id: '16:9', label: '16:9 (Landscape)', dimensions: '1344x768' },
    { id: '9:16', label: '9:16 (Portrait)', dimensions: '768x1344' },
    { id: '1:1', label: '1:1 (Square)', dimensions: '1024x1024' },
  ],
  resolutions: [
    { id: '1024x1024', label: '1024 × 1024' },
    { id: '1344x768', label: '1344 × 768' },
    { id: '768x1344', label: '768 × 1344' },
  ],
  durations: [
    { value: 5.0, label: '5 seconds' },
    { value: 10.0, label: '10 seconds' },
  ],
  models: {
    image: [
      {
        id: 'black-forest-labs/FLUX.1.1-pro',
        name: 'FLUX 1.1 Pro (Together AI)',
        provider: 'together',
        default: true,
        cost_tier: 1,
        configured: true,
        start_frame: false,
        end_frame: false,
      },
    ],
    video: [
      {
        id: 'kling-v1-standard',
        name: 'Kling 1.0 Standard (Fal.ai)',
        provider: 'fal',
        default: true,
        cost_tier: 2,
        configured: true,
        start_frame: false,
        end_frame: false,
      },
    ],
    image_to_video: [
      {
        id: 'kling-v1-pro-i2v',
        name: 'Kling 1.5 Pro (Fal.ai)',
        provider: 'fal',
        default: true,
        cost_tier: 2,
        configured: true,
        start_frame: true,
        end_frame: false,
      },
    ],
  },
};

const createMockProject = (): Project => ({
  id: 'proj-stage11-test',
  title: 'Cinematic Teaser // Sequence Alpha',
  description: 'Production multi-shot continuity test',
  sequences: [
    {
      id: 'seq-alpha',
      projectId: 'proj-stage11-test',
      title: 'Opening Act',
      order: 1,
      shots: [
        {
          id: 'shot-01',
          sequenceId: 'seq-alpha',
          order: 1,
          title: 'Shot 01 // Wide Establish',
          prompt: 'Wide establishment cinematic shot of mountain valley at dawn',
          generationType: 'image',
          selectedModel: 'black-forest-labs/FLUX.1.1-pro',
          selectedProvider: 'together',
          aspectRatio: '16:9',
          resolution: '1344x768',
          status: 'READY',
          readiness: 'READY',
          provenance: 'USER_CONFIGURATION',
          dependencyShotIds: [],
          referenceAssets: ['https://storage.aryaos.internal/refs/dawn.jpg'],
          validationResults: {
            isValid: true,
            readiness: 'READY',
            reasons: ['READY FOR EXECUTION'],
            reasonCodes: ['READY'],
            preflightReady: true,
            dependenciesSatisfied: true,
            startFrameSatisfied: true,
          },
          continuityReport: {
            character: { status: 'UNAVAILABLE', detail: 'CHARACTER: UNAVAILABLE', source: 'UNAVAILABLE' },
            environment: { status: 'UNAVAILABLE', detail: 'ENV: UNAVAILABLE', source: 'UNAVAILABLE' },
            visual: { status: 'PASS', detail: 'Visual format 16:9', source: 'USER_CONFIGURATION' },
            temporal: { status: 'PASS', detail: 'Temporal ordering valid', source: 'USER_CONFIGURATION' },
            startFrame: { status: 'NOT_APPLICABLE', detail: 'NOT APPLICABLE', source: 'CAPABILITY_MANIFEST' },
          },
        },
        {
          id: 'shot-02',
          sequenceId: 'seq-alpha',
          order: 2,
          title: 'Shot 02 // Drone Push',
          prompt: 'Drone push into mountain valley showing misty river below',
          generationType: 'image_to_video',
          selectedModel: 'kling-v1-pro-i2v',
          selectedProvider: 'fal',
          aspectRatio: '16:9',
          duration: 5.0,
          status: 'READY',
          readiness: 'READY',
          startFrame: 'https://storage.aryaos.internal/renders/shot01.png',
          predecessorShotId: 'shot-01',
          dependencyShotIds: ['shot-01'],
          referenceAssets: [],
          provenance: 'USER_CONFIGURATION',
          validationResults: {
            isValid: true,
            readiness: 'READY',
            reasons: ['READY FOR EXECUTION'],
            reasonCodes: ['READY'],
            preflightReady: true,
            dependenciesSatisfied: true,
            startFrameSatisfied: true,
          },
          continuityReport: {
            character: { status: 'UNAVAILABLE', detail: 'CHARACTER: UNAVAILABLE', source: 'UNAVAILABLE' },
            environment: { status: 'UNAVAILABLE', detail: 'ENV: UNAVAILABLE', source: 'UNAVAILABLE' },
            visual: { status: 'PASS', detail: 'Visual format 16:9', source: 'USER_CONFIGURATION' },
            temporal: { status: 'PASS', detail: 'Temporal ordering valid', source: 'USER_CONFIGURATION' },
            startFrame: { status: 'PROVIDED', detail: 'START FRAME PROVIDED', source: 'USER_CONFIGURATION', assetUrl: 'https://storage.aryaos.internal/renders/shot01.png' },
          },
        },
      ],
      status: 'READY',
      sequenceStatus: 'READY',
      statusReasons: ['ALL SHOTS READY'],
      totalShots: 2,
      readyShots: 2,
      blockedShots: 0,
      inFlightShots: 0,
      completeShots: 0,
      totalDurationSeconds: 5,
      createdAt: '2026-09-27T10:00:00.000Z',
      updatedAt: '2026-09-27T10:00:00.000Z',
    },
  ],
  activeSequenceId: 'seq-alpha',
  activeShotId: 'shot-01',
  createdAt: '2026-09-27T10:00:00.000Z',
  updatedAt: '2026-09-27T10:00:00.000Z',
  metadata: {
    createdAt: '2026-09-27T10:00:00.000Z',
    updatedAt: '2026-09-27T10:00:00.000Z',
    version: '1.0.0',
  },
});

describe('AryaOS Stage 11: Production Project Persistence, Recovery & State Integrity', () => {
  beforeEach(() => {
    localStorage.clear();
    vi.restoreAllMocks();
  });

  // =========================================================================
  // 1. Persistence Engine & Serialization Core
  // =========================================================================
  describe('1. Persistence Engine & Serialization Core', () => {
    it('1. saveProject writes sanitized envelope to storage with schemaVersion and savedAt', () => {
      const proj = createMockProject();
      const result = saveProject(proj);
      expect(result).toBe(true);

      const raw = localStorage.getItem(STORAGE_KEY_PROJECT);
      expect(raw).toBeTruthy();
      const parsed = JSON.parse(raw!);
      expect(parsed.schemaVersion).toBe(CURRENT_SCHEMA_VERSION);
      expect(parsed.savedAt).toBeDefined();
      expect(parsed.project.id).toBe(proj.id);
      expect(parsed.project.sequences.length).toBe(1);
      expect(parsed.project.sequences[0].shots.length).toBe(2);
    });

    it('2. loadProject returns identical project structure when valid envelope exists', () => {
      const proj = createMockProject();
      saveProject(proj);

      const loaded = loadProject();
      expect(loaded).not.toBeNull();
      expect(loaded!.id).toBe(proj.id);
      expect(loaded!.title).toBe(proj.title);
      expect(loaded!.sequences.length).toBe(1);
      expect(loaded!.sequences[0].shots[0].id).toBe('shot-01');
      expect(loaded!.sequences[0].shots[1].id).toBe('shot-02');
    });

    it('3. clearProject safely purges stored project envelope', () => {
      const proj = createMockProject();
      saveProject(proj);
      expect(hasPersistedProject()).toBe(true);

      clearProject();
      expect(hasPersistedProject()).toBe(false);
      expect(localStorage.getItem(STORAGE_KEY_PROJECT)).toBeNull();
      expect(loadProject()).toBeNull();
    });

    it('4. hasPersistedProject returns false when storage is empty or corrupt', () => {
      expect(hasPersistedProject()).toBe(false);

      localStorage.setItem(STORAGE_KEY_PROJECT, 'corrupted-non-json');
      expect(hasPersistedProject()).toBe(false);

      localStorage.setItem(STORAGE_KEY_PROJECT, JSON.stringify({ schemaVersion: 99 }));
      expect(hasPersistedProject()).toBe(false);
    });

    it('5. serializeProject produces valid JSON envelope string', () => {
      const proj = createMockProject();
      const serialized = serializeProject(proj);
      expect(typeof serialized).toBe('string');

      const parsed = JSON.parse(serialized);
      expect(parsed.schemaVersion).toBe(CURRENT_SCHEMA_VERSION);
      expect(parsed.project.id).toBe(proj.id);
    });

    it('6. deserializeProject reconstructs the project safely', () => {
      const proj = createMockProject();
      const serialized = serializeProject(proj);
      const deserialized = deserializeProject(serialized);

      expect(deserialized).not.toBeNull();
      expect(deserialized!.id).toBe(proj.id);
      expect(deserialized!.sequences[0].shots[0].prompt).toBe(proj.sequences[0].shots[0].prompt);
    });
  });

  // =========================================================================
  // 2. State Integrity & Recovery Preservation
  // =========================================================================
  describe('2. State Integrity & Recovery Preservation', () => {
    it('7. Restoration preserves sequence ordering across serialization cycles', () => {
      const proj = createMockProject();
      const secondSeq: Sequence = {
        ...proj.sequences[0],
        id: 'seq-beta',
        title: 'Climax Act',
        order: 2,
        shots: [],
      };
      proj.sequences.push(secondSeq);

      saveProject(proj);
      const loaded = loadProject();

      expect(loaded!.sequences.length).toBe(2);
      expect(loaded!.sequences[0].id).toBe('seq-alpha');
      expect(loaded!.sequences[0].order).toBe(1);
      expect(loaded!.sequences[1].id).toBe('seq-beta');
      expect(loaded!.sequences[1].order).toBe(2);
    });

    it('8. Restoration preserves shot ordering within sequences', () => {
      const proj = createMockProject();
      saveProject(proj);
      const loaded = loadProject();

      const shots = loaded!.sequences[0].shots;
      expect(shots[0].id).toBe('shot-01');
      expect(shots[0].order).toBe(1);
      expect(shots[1].id).toBe('shot-02');
      expect(shots[1].order).toBe(2);
    });

    it('9. Restoration preserves exact model, provider, aspect ratio, duration, and resolution', () => {
      const proj = createMockProject();
      saveProject(proj);
      const loaded = loadProject();

      const shot1 = loaded!.sequences[0].shots[0];
      expect(shot1.selectedModel).toBe('black-forest-labs/FLUX.1.1-pro');
      expect(shot1.selectedProvider).toBe('together');
      expect(shot1.aspectRatio).toBe('16:9');
      expect(shot1.resolution).toBe('1344x768');

      const shot2 = loaded!.sequences[0].shots[1];
      expect(shot2.selectedModel).toBe('kling-v1-pro-i2v');
      expect(shot2.selectedProvider).toBe('fal');
      expect(shot2.aspectRatio).toBe('16:9');
      expect(shot2.duration).toBe(5.0);
    });

    it('10. Restoration preserves predecessor start frame links and dependencies', () => {
      const proj = createMockProject();
      saveProject(proj);
      const loaded = loadProject();

      const shot2 = loaded!.sequences[0].shots[1];
      expect(shot2.startFrame).toBe('https://storage.aryaos.internal/renders/shot01.png');
      expect(shot2.predecessorShotId).toBe('shot-01');
      expect(shot2.dependencyShotIds).toContain('shot-01');
      expect(shot2.provenance).toBe('USER_CONFIGURATION');
    });

    it('11. Restoration preserves reference assets', () => {
      const proj = createMockProject();
      saveProject(proj);
      const loaded = loadProject();

      const shot1 = loaded!.sequences[0].shots[0];
      expect(shot1.referenceAssets).toEqual(['https://storage.aryaos.internal/refs/dawn.jpg']);
    });

    it('12. getPersistedProjectEnvelope returns metadata envelope without mutating state', () => {
      const proj = createMockProject();
      saveProject(proj);

      const envelope = getPersistedProjectEnvelope();
      expect(envelope).not.toBeNull();
      expect(envelope!.schemaVersion).toBe(CURRENT_SCHEMA_VERSION);
      expect(envelope!.project.id).toBe(proj.id);
      expect(envelope!.savedAt).toBeDefined();
    });
  });

  // =========================================================================
  // 3. Safety, Robustness & Non-Autonomous Policy
  // =========================================================================
  describe('3. Safety, Robustness & Non-Autonomous Policy', () => {
    it('13. Deserializing corrupt JSON returns null safely without throwing', () => {
      expect(deserializeProject('{"incomplete":')).toBeNull();
      expect(deserializeProject('')).toBeNull();
      expect(deserializeProject('{}')).toBeNull();
    });

    it('14. Deserializing unsupported schemaVersion returns null safely', () => {
      const invalidVersionEnvelope = JSON.stringify({
        schemaVersion: 2,
        savedAt: new Date().toISOString(),
        project: createMockProject(),
      });
      expect(deserializeProject(invalidVersionEnvelope)).toBeNull();
    });

    it('15. Deserializing project missing required fields returns null safely', () => {
      const invalidProject = JSON.stringify({
        schemaVersion: 1,
        savedAt: new Date().toISOString(),
        project: {
          id: 'test',
          // missing sequences array
        },
      });
      expect(deserializeProject(invalidProject)).toBeNull();
    });

    it('16. Deserializing malformed shot objects does not crash', () => {
      const malformedProject = JSON.stringify({
        schemaVersion: 1,
        savedAt: new Date().toISOString(),
        project: {
          id: 'test',
          title: 'Test',
          sequences: [
            {
              id: 'seq-1',
              title: 'Seq 1',
              shots: [{ id: 'shot-1' }], // missing required shot properties like order, prompt
            },
          ],
        },
      });
      expect(deserializeProject(malformedProject)).toBeNull();
    });

    it('17. sanitizeForPersistence strips sensitive keys (tokens, apiKeys, auth) from project metadata', () => {
      const proj = createMockProject();
      proj.metadata = {
        ...proj.metadata,
        apiKey: 'SECRET-KEY-12345',
        authToken: 'BEARER-XYZ',
        temporarySecret: 'PASSWORD-ABC',
        safeMetadata: 'ALLOWED',
      };

      const sanitized = sanitizeForPersistence(proj);
      expect(sanitized.metadata).toBeDefined();
      expect(sanitized.metadata?.apiKey).toBeUndefined();
      expect(sanitized.metadata?.authToken).toBeUndefined();
      expect(sanitized.metadata?.temporarySecret).toBeUndefined();
      expect(sanitized.metadata?.safeMetadata).toBe('ALLOWED');
    });

    it('18. sanitizeForPersistence returns deep clone and does not mutate source object', () => {
      const proj = createMockProject();
      const sanitized = sanitizeForPersistence(proj);
      sanitized.title = 'Mutated Clone Title';

      expect(proj.title).toBe('Cinematic Teaser // Sequence Alpha');
    });

    it('19. Non-autonomous verification: Restoration NEVER triggers POST /creator/generate', () => {
      const fetchSpy = vi.fn();
      globalThis.fetch = fetchSpy;

      const proj = createMockProject();
      saveProject(proj);
      const loaded = loadProject();
      expect(loaded).not.toBeNull();

      const recomputed = recomputeDerivedState(loaded!, mockManifest);
      expect(recomputed).toBeDefined();

      // Ensure fetch was never called
      expect(fetchSpy).not.toHaveBeenCalled();
    });

    it('20. Restoration never auto-switches model even if manifest default differs', () => {
      const proj = createMockProject();
      // shot-01 has FLUX 1.1 Pro
      proj.sequences[0].shots[0].selectedModel = 'custom-legacy-model';
      saveProject(proj);

      const loaded = loadProject();
      expect(loaded!.sequences[0].shots[0].selectedModel).toBe('custom-legacy-model');
    });
  });

  // =========================================================================
  // 4. Derived State Recalculation (Derived State Rule)
  // =========================================================================
  describe('4. Derived State Recalculation', () => {
    it('21. recomputeDerivedState evaluates continuity reports dynamically', () => {
      const proj = createMockProject();
      // Remove precomputed continuity report
      delete (proj.sequences[0].shots[0] as any).continuityReport;

      const recomputed = recomputeDerivedState(proj, mockManifest);
      const shot01 = recomputed.sequences[0].shots[0];
      expect(shot01.continuityReport).toBeDefined();
      expect(shot01.continuityReport!.visual.status).toBe('PASS');
      expect(shot01.continuityReport!.temporal.status).toBe('PASS');
    });

    it('22. recomputeDerivedState dynamically re-evaluates sequence readiness and metrics', () => {
      const proj = createMockProject();
      proj.sequences[0].shots[1].dependencyShotIds = [];
      proj.sequences[0].shots[1].predecessorShotId = undefined;
      // Corrupt metrics on the sequence
      proj.sequences[0].readyShots = 0;
      proj.sequences[0].totalShots = 0;
      proj.sequences[0].status = 'BLOCKED';

      const recomputed = recomputeDerivedState(proj, mockManifest);
      const seq = recomputed.sequences[0];
      expect(seq.totalShots).toBe(2);
      expect(seq.readyShots).toBe(2);
      expect(seq.status).toBe('READY');
      expect(seq.sequencePreflightStatus).toBe('READY');
    });

    it('23. recomputeDerivedState identifies missing start frame for image_to_video as BLOCKED', () => {
      const proj = createMockProject();
      // Break shot 02 start frame
      proj.sequences[0].shots[1].startFrame = undefined;
      proj.sequences[0].shots[1].predecessorShotId = undefined;

      const recomputed = recomputeDerivedState(proj, mockManifest);
      const shot02 = recomputed.sequences[0].shots[1];
      expect(shot02.validationResults.readiness).toBe('BLOCKED');
      expect(shot02.validationResults.reasonCodes).toContain('START_FRAME_REQUIRED');
      expect(recomputed.sequences[0].status).toBe('BLOCKED');
    });
  });

  // =========================================================================
  // 5. Interrupted Jobs & Recovery Required Handling
  // =========================================================================
  describe('5. Interrupted Jobs & Recovery Required Handling', () => {
    it('24. Deserializing a project with in-flight shots converts them to RECOVERY_REQUIRED', () => {
      const proj = createMockProject();
      proj.sequences[0].shots[0].status = 'GENERATING';
      proj.sequences[0].shots[1].status = 'QUEUED';

      const serialized = serializeProject(proj);
      const loaded = deserializeProject(serialized);

      expect(loaded).not.toBeNull();
      const shot01 = loaded!.sequences[0].shots[0];
      const shot02 = loaded!.sequences[0].shots[1];

      expect(shot01.status).toBe('RECOVERY_REQUIRED');
      expect(shot01.readiness).toBe('BLOCKED');
      expect(shot01.validationResults.reasons[0]).toContain('PREVIOUS GENERATION INTERRUPTED');

      expect(shot02.status).toBe('RECOVERY_REQUIRED');
      expect(shot02.readiness).toBe('BLOCKED');
    });

    it('25. checkForInterruptedShots detects shots in RECOVERY_REQUIRED state', () => {
      const proj = createMockProject();
      proj.sequences[0].shots[0].status = 'RECOVERY_REQUIRED';

      const check = checkForInterruptedShots(proj);
      expect(check.hasInterrupted).toBe(true);
      expect(check.interruptedShotIds).toContain('shot-01');
    });

    it('26. checkForInterruptedShots reports false when no shots require recovery', () => {
      const proj = createMockProject();
      const check = checkForInterruptedShots(proj);
      expect(check.hasInterrupted).toBe(false);
      expect(check.interruptedShotIds.length).toBe(0);
    });

    it('27. Sequence with RECOVERY_REQUIRED shot is evaluated as BLOCKED', () => {
      const proj = createMockProject();
      proj.sequences[0].shots[0].status = 'RECOVERY_REQUIRED';

      const recomputed = recomputeDerivedState(proj, mockManifest);
      expect(recomputed.sequences[0].status).toBe('BLOCKED');
      expect(recomputed.sequences[0].blockedShots).toBeGreaterThanOrEqual(1);
    });
  });

  // =========================================================================
  // 6. Reconciliation with Backend Execution History
  // =========================================================================
  describe('6. Reconciliation with Backend Execution History', () => {
    it('28. reconcileProjectWithHistory links completed historical run to shot output without generating', () => {
      const proj = createMockProject();
      proj.sequences[0].shots[0].outputJobId = 'job-history-100';
      proj.sequences[0].shots[0].status = 'RECOVERY_REQUIRED';

      const history: HistoryItem[] = [
        {
          job_id: 'job-history-100',
          workflow_run_id: 'run-100',
          generation_type: 'image',
          prompt: 'mountain valley',
          status: 'completed',
          asset_url: 'https://storage.aryaos.internal/renders/job-100.png',
          total_cost_usd: 0.04,
          created_at: '2026-09-27T11:00:00Z',
        },
      ];

      const reconciled = reconcileProjectWithHistory(proj, history);
      const shot01 = reconciled.sequences[0].shots[0];
      expect(shot01.status).toBe('COMPLETE');
      expect(shot01.outputAssetUrl).toBe('https://storage.aryaos.internal/renders/job-100.png');
      expect(shot01.provenance).toBe('HISTORICAL_RUN');
    });

    it('29. reconcileProjectWithHistory marks shot as FAILED if historical run failed', () => {
      const proj = createMockProject();
      proj.sequences[0].shots[0].outputJobId = 'job-history-fail';

      const history: HistoryItem[] = [
        {
          job_id: 'job-history-fail',
          workflow_run_id: 'run-fail',
          generation_type: 'image',
          prompt: 'mountain valley',
          status: 'failed',
          failure_reason: 'Provider GPU quota exhausted',
          total_cost_usd: 0.0,
          created_at: '2026-09-27T11:00:00Z',
        },
      ];

      const reconciled = reconcileProjectWithHistory(proj, history);
      const shot01 = reconciled.sequences[0].shots[0];
      expect(shot01.status).toBe('FAILED');
      expect(shot01.failureDetails?.reason).toBe('Provider GPU quota exhausted');
      expect(shot01.provenance).toBe('HISTORICAL_RUN');
    });

    it('30. reconcileProjectWithHistory leaves shots without outputJobId untouched', () => {
      const proj = createMockProject();
      const reconciled = reconcileProjectWithHistory(proj, []);
      expect(reconciled).toEqual(proj);
    });
  });

  // =========================================================================
  // 7. UX & Visual Recovery Surface
  // =========================================================================
  describe('7. UX & Visual Recovery Surface', () => {
    it('31. ProjectRecoveryBar renders PROJECT STATE // NEW when no saved project', () => {
      render(
        <ProjectRecoveryBar
          recoveryState="NEW"
          envelope={null}
          onRestoreProject={vi.fn()}
          onDiscardProject={vi.fn()}
        />
      );

      expect(screen.getByTestId('project-recovery-bar')).toBeInTheDocument();
      expect(screen.getByText('PROJECT STATE // NEW')).toBeInTheDocument();
      expect(screen.getByText(/No persisted production project found/i)).toBeInTheDocument();
    });

    it('32. ProjectRecoveryBar renders PROJECT STATE // RECOVERABLE with metadata and action buttons', () => {
      const envelope: PersistedProjectEnvelope = {
        schemaVersion: 1,
        savedAt: '2026-09-27T12:00:00Z',
        project: createMockProject(),
      };

      const onRestore = vi.fn();
      const onDiscard = vi.fn();

      render(
        <ProjectRecoveryBar
          recoveryState="RECOVERABLE"
          envelope={envelope}
          onRestoreProject={onRestore}
          onDiscardProject={onDiscard}
        />
      );

      expect(screen.getByText('PROJECT STATE // RECOVERABLE')).toBeInTheDocument();
      expect(screen.getByText('Cinematic Teaser // Sequence Alpha')).toBeInTheDocument();
      expect(screen.getByText(/SEQUENCES: 01/i)).toBeInTheDocument();
      expect(screen.getByText(/SHOTS: 02/i)).toBeInTheDocument();

      const restoreBtn = screen.getByTestId('restore-project-btn');
      const discardBtn = screen.getByTestId('discard-project-btn');

      expect(restoreBtn).toBeInTheDocument();
      expect(discardBtn).toBeInTheDocument();

      fireEvent.click(restoreBtn);
      expect(onRestore).toHaveBeenCalledTimes(1);

      fireEvent.click(discardBtn);
      expect(onDiscard).toHaveBeenCalledTimes(1);
    });

    it('33. ProjectRecoveryBar renders PROJECT STATE // RECOVERY REQUIRED with review action', () => {
      const onReview = vi.fn();
      render(
        <ProjectRecoveryBar
          recoveryState="RECOVERY_REQUIRED"
          envelope={null}
          onRestoreProject={vi.fn()}
          onDiscardProject={vi.fn()}
          onReviewInterruptedShots={onReview}
        />
      );

      expect(screen.getByText('PROJECT STATE // RECOVERY REQUIRED')).toBeInTheDocument();
      expect(screen.getByText(/One or more shots were previously in-flight/i)).toBeInTheDocument();

      const reviewBtn = screen.getByTestId('review-interrupted-shots-btn');
      expect(reviewBtn).toBeInTheDocument();

      fireEvent.click(reviewBtn);
      expect(onReview).toHaveBeenCalledTimes(1);
    });

    it('34. ProjectRecoveryBar renders PROJECT STATE // RESTORED with non-autonomous notice', () => {
      render(
        <ProjectRecoveryBar
          recoveryState="RESTORED"
          envelope={null}
          onRestoreProject={vi.fn()}
          onDiscardProject={vi.fn()}
        />
      );

      expect(screen.getByText('PROJECT STATE // RESTORED')).toBeInTheDocument();
      expect(screen.getByText(/Production intent recovered. No generation dispatched./i)).toBeInTheDocument();
    });

    it('35. ProjectRecoveryBar renders PROJECT STATE // SAVED badge', () => {
      render(
        <ProjectRecoveryBar
          recoveryState="SAVED"
          envelope={null}
          onRestoreProject={vi.fn()}
          onDiscardProject={vi.fn()}
        />
      );

      expect(screen.getByText('PROJECT STATE // SAVED')).toBeInTheDocument();
    });

    it('36. OperationalStrip displays operational project status badge correctly', () => {
      const { rerender } = render(
        <OperationalStrip
          systemState="IDLE"
          activeCount={0}
          queuedCount={0}
          processingCount={0}
          failedCount={0}
          totalCostUsd={0}
          isRefreshing={false}
          onRefresh={vi.fn()}
          projectStatus="NEW"
        />
      );

      const statusBadge = screen.getByTestId('operational-project-status');
      expect(statusBadge).toHaveTextContent('PROJECT // NEW');

      rerender(
        <OperationalStrip
          systemState="IDLE"
          activeCount={0}
          queuedCount={0}
          processingCount={0}
          failedCount={0}
          totalCostUsd={0}
          isRefreshing={false}
          onRefresh={vi.fn()}
          projectStatus="SAVED"
        />
      );
      expect(statusBadge).toHaveTextContent('PROJECT // SAVED');

      rerender(
        <OperationalStrip
          systemState="IDLE"
          activeCount={0}
          queuedCount={0}
          processingCount={0}
          failedCount={0}
          totalCostUsd={0}
          isRefreshing={false}
          onRefresh={vi.fn()}
          projectStatus="RECOVERED"
        />
      );
      expect(statusBadge).toHaveTextContent('PROJECT // RECOVERED');
    });

    it('37. ProductionTimeline renders ProjectRecoveryBar when recoveryState is provided', () => {
      const proj = createMockProject();
      render(
        <ProductionTimeline
          project={proj}
          activeShotId={proj.activeShotId}
          onSelectShot={vi.fn()}
          onReproduceShot={vi.fn()}
          onReorderShots={vi.fn()}
          onAddShot={vi.fn()}
          onLinkPredecessor={vi.fn()}
          manifest={mockManifest}
          recoveryState="RECOVERABLE"
          envelope={{
            schemaVersion: 1,
            savedAt: '2026-09-27T12:00:00Z',
            project: proj,
          }}
          onRestoreProject={vi.fn()}
          onDiscardProject={vi.fn()}
        />
      );

      expect(screen.getByTestId('project-recovery-bar')).toBeInTheDocument();
      expect(screen.getByText('PROJECT STATE // RECOVERABLE')).toBeInTheDocument();
    });
  });
});
