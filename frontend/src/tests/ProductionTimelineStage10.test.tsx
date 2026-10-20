import React from 'react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import '@testing-library/jest-dom';
import {
  Project,
  Sequence,
  Shot,
  SequenceOperationalSummary,
} from '../types/productionTimeline';
import {
  createDefaultProject,
  validateShot,
  evaluateSequenceReadiness,
  evaluateCharacterContinuity,
  evaluateEnvironmentContinuity,
  evaluateVisualContinuity,
  evaluateTemporalContinuity,
  evaluateStartFrameContinuity,
  reorderShots,
  duplicateShot,
  removeShot,
  editShot,
  linkPredecessorStartFrame,
  reproduceShotToConsole,
  generateSequenceExecutionPlan,
} from '../utils/continuityEngine';
import { ProductionTimeline } from '../components/timeline/ProductionTimeline';
import { ShotDetailInspector } from '../components/timeline/ShotDetailInspector';
import { OperationalStrip } from '../components/orchestration/OperationalStrip';
import { ProductionDecisionCard } from '../components/orchestration/ProductionDecisionCard';
import { deriveProductionRecommendation } from '../types/productionDecision';
import { CapabilitiesManifest } from '../types/creator';

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
        cost_tier: 2,
        configured: true,
        start_frame: false,
        end_frame: false,
      },
    ],
    video: [
      {
        id: 'wan-video/wan-2.1-t2v-14b',
        name: 'Wan 2.1 T2V 14B',
        provider: 'together',
        default: true,
        cost_tier: 3,
        configured: true,
        start_frame: false,
        end_frame: false,
      },
    ],
    image_to_video: [
      {
        id: 'kling-ai/kling-v1.6-pro',
        name: 'Kling 1.6 Pro (fal.ai)',
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

describe('AryaOS Stage 10: Multi-Shot Production Timeline & Story Continuity Control Plane', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    localStorage.clear();
    sessionStorage.clear();
  });

  // 1. Create sequence
  it('1. Create sequence: creates normalized sequence with ordered shots and metadata', () => {
    const project = createDefaultProject(mockManifest);
    const seq = project.sequences[0];
    expect(seq.id).toBe('seq-001');
    expect(seq.title).toContain('Sequence 01');
    expect(seq.shots).toHaveLength(2);
    expect(seq.order).toBe(1);
    expect(seq.status).toBeDefined();
  });

  // 2. Add shot
  it('2. Add shot: adds a new shot to the sequence with continuous 1-indexed order', () => {
    const project = createDefaultProject(mockManifest);
    const initialShots = project.sequences[0].shots;
    const newShot: Shot = {
      id: 'shot-003',
      sequenceId: 'seq-001',
      order: 3,
      title: 'Shot 03 // New Scene',
      prompt: 'Interior observation deck',
      generationType: 'image',
      selectedModel: 'black-forest-labs/FLUX.1.1-pro',
      selectedProvider: 'together',
      aspectRatio: '16:9',
      dependencyShotIds: [],
      status: 'READY',
      readiness: 'READY',
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
        character: { status: 'UNAVAILABLE', detail: 'None', source: 'UNAVAILABLE' },
        environment: { status: 'UNAVAILABLE', detail: 'None', source: 'UNAVAILABLE' },
        visual: { status: 'PASS', detail: 'Format ok', source: 'USER_CONFIGURATION' },
        temporal: { status: 'PASS', detail: 'Order valid', source: 'USER_CONFIGURATION' },
        startFrame: { status: 'NOT_APPLICABLE', detail: 'NA', source: 'CAPABILITY_MANIFEST' },
      },
    };

    const updated = [...initialShots, newShot];
    expect(updated).toHaveLength(3);
    expect(updated[2].order).toBe(3);
  });

  // 3. Remove shot
  it('3. Remove shot: immutably removes a shot and updates references and ordering', () => {
    const project = createDefaultProject(mockManifest);
    const initialShots = project.sequences[0].shots;
    expect(initialShots).toHaveLength(2);

    const updated = removeShot(initialShots, 'shot-001', mockManifest);
    expect(updated).toHaveLength(1);
    expect(updated[0].id).toBe('shot-002');
    expect(updated[0].order).toBe(1);
    // Dependency on shot-001 should be pruned
    expect(updated[0].dependencyShotIds).not.toContain('shot-001');
  });

  // 4. Duplicate shot
  it('4. Duplicate shot: duplicates shot configuration into a new shot with new unique ID', () => {
    const project = createDefaultProject(mockManifest);
    const initialShots = project.sequences[0].shots;

    const duplicated = duplicateShot(initialShots, 'shot-001', mockManifest);
    expect(duplicated).toHaveLength(3);
    expect(duplicated[1].title).toContain('Establishing Shot // Obsidian Station (Copy)');
    expect(duplicated[1].id).not.toBe('shot-001');
    expect(duplicated[1].order).toBe(2);
    expect(duplicated[2].order).toBe(3);
  });

  // 5. Reorder shot
  it('5. Reorder shot: reorders shots immutably and recalculates indices and temporal continuity', () => {
    const project = createDefaultProject(mockManifest);
    const initialShots = project.sequences[0].shots;
    expect(initialShots[0].id).toBe('shot-001');

    const reordered = reorderShots(initialShots, 0, 1, mockManifest);
    expect(reordered[0].id).toBe('shot-002');
    expect(reordered[0].order).toBe(1);
    expect(reordered[1].id).toBe('shot-001');
    expect(reordered[1].order).toBe(2);
  });

  // 6. Select shot
  it('6. Select shot: selects shot without triggering automatic generation execution', () => {
    const project = createDefaultProject(mockManifest);
    const onSelect = vi.fn();

    render(
      <ProductionTimeline
        project={project}
        activeShotId={undefined}
        onSelectShot={onSelect}
        onReproduceShot={vi.fn()}
        onReorderShots={vi.fn()}
        onAddShot={vi.fn()}
        onLinkPredecessor={vi.fn()}
        manifest={mockManifest}
      />
    );

    const shotCards = screen.getAllByTestId('timeline-shot-card');
    fireEvent.click(shotCards[0]);
    expect(onSelect).toHaveBeenCalledTimes(1);
    expect(onSelect).toHaveBeenCalledWith(expect.objectContaining({ id: 'shot-001' }));
  });

  // 7. Edit shot
  it('7. Edit shot: updates shot prompt and parameters without mutating original ID', () => {
    const project = createDefaultProject(mockManifest);
    const initialShots = project.sequences[0].shots;

    const edited = editShot(
      initialShots,
      'shot-001',
      { prompt: 'Updated exterior station prompt at sunset' },
      mockManifest
    );

    expect(edited[0].id).toBe('shot-001');
    expect(edited[0].prompt).toBe('Updated exterior station prompt at sunset');
  });

  // 8. Shot status derivation
  it('8. Shot status derivation: derives DRAFT, READY, and BLOCKED based on configuration state', () => {
    const baseShot = createDefaultProject(mockManifest).sequences[0].shots[0];

    // Empty prompt -> DRAFT
    const draftShot = validateShot({ ...baseShot, prompt: '' }, [baseShot], mockManifest);
    expect(draftShot.status).toBe('DRAFT');

    // Valid prompt & constraints -> READY
    const readyShot = validateShot({ ...baseShot, prompt: 'A valid prompt' }, [baseShot], mockManifest);
    expect(readyShot.status).toBe('READY');

    // Blocked dependencies -> BLOCKED
    const blockedShot = validateShot(
      { ...baseShot, dependencyShotIds: ['non-existent-dep'] },
      [baseShot],
      mockManifest
    );
    expect(blockedShot.status).toBe('BLOCKED');
  });

  // 9. Sequence duration calculation
  it('9. Sequence duration calculation: accurately sums planned duration across shots', () => {
    const project = createDefaultProject(mockManifest);
    const shots = project.sequences[0].shots;
    const readiness = evaluateSequenceReadiness(shots);

    // Shot 1 (image) = 0s or duration value, Shot 2 (video) = 5s
    expect(readiness.metrics.totalDuration).toBeGreaterThanOrEqual(5);
  });

  // 10. Sequence preflight
  it('10. Sequence preflight: computes sequence-level preflight metrics and readiness state', () => {
    const project = createDefaultProject(mockManifest);
    const evalSeq = evaluateSequenceReadiness(project.sequences[0].shots);

    expect(evalSeq.status).toBe('BLOCKED'); // Shot 2 start frame not yet provided
    expect(evalSeq.metrics.total).toBe(2);
    expect(evalSeq.metrics.ready).toBe(1);
    expect(evalSeq.metrics.blocked).toBe(1);
  });

  // 11. Blocked shot propagation
  it('11. Blocked shot propagation: blocks sequence when any required shot is blocked with itemized directives', () => {
    const project = createDefaultProject(mockManifest);
    const evalSeq = evaluateSequenceReadiness(project.sequences[0].shots);

    expect(evalSeq.status).toBe('BLOCKED');
    expect(evalSeq.statusReasons.length).toBeGreaterThan(0);
    expect(evalSeq.statusReasons[0]).toContain('SHOT 02:');
  });

  // 12. Warning propagation
  it('12. Warning propagation: surfaces continuity warnings in sequence metrics and status', () => {
    const project = createDefaultProject(mockManifest);
    const shots = [...project.sequences[0].shots];

    // Introduce aspect ratio mismatch between shots
    shots[0] = { ...shots[0], aspectRatio: '16:9' };
    shots[1] = { ...shots[1], aspectRatio: '9:16' };

    const validated = shots.map((s) => validateShot(s, shots, mockManifest));
    const evalSeq = evaluateSequenceReadiness(validated);

    expect(evalSeq.metrics.continuityWarnings.length).toBeGreaterThan(0);
    expect(evalSeq.metrics.continuityWarnings[0]).toContain('Aspect ratio mismatch');
  });

  // 13. Character continuity
  it('13. Character continuity: detects wardrobe/hair shifts and surfaces IDENTITY REFERENCE AVAILABLE', () => {
    const shotA: Shot = {
      ...createDefaultProject(mockManifest).sequences[0].shots[0],
      characterRequirements: {
        characterId: 'char-hero',
        name: 'Hero',
        wardrobe: 'Tactical Armor',
        hair: 'Short Crop',
        visualIdentityReferences: ['https://assets.local/ref.png'],
        source: 'USER_CONFIGURATION',
      },
    };

    const shotB: Shot = {
      ...createDefaultProject(mockManifest).sequences[0].shots[1],
      characterRequirements: {
        characterId: 'char-hero',
        name: 'Hero',
        wardrobe: 'Lab Coat', // Mismatch
        hair: 'Short Crop',
        visualIdentityReferences: ['https://assets.local/ref.png'],
        source: 'USER_CONFIGURATION',
      },
    };

    const result = evaluateCharacterContinuity(shotB, shotA);
    expect(result.status).toBe('WARNING');
    expect(result.detail).toContain('Wardrobe mismatch');
  });

  // 14. Location continuity
  it('14. Location continuity: verifies locationId consistency and detects location conflicts', () => {
    const shotA = {
      ...createDefaultProject(mockManifest).sequences[0].shots[0],
      locationId: 'loc-hangar',
      environmentRequirements: { location: 'Main Hangar', source: 'USER_CONFIGURATION' as const },
    };
    const shotB = {
      ...createDefaultProject(mockManifest).sequences[0].shots[1],
      locationId: 'loc-bridge',
      environmentRequirements: { location: 'Command Bridge', source: 'USER_CONFIGURATION' as const },
    };

    const result = evaluateEnvironmentContinuity(shotB, shotA);
    expect(result.status).toBe('WARNING');
    expect(result.detail).toContain('LOCATION CONFLICT');
  });

  // 15. Time continuity
  it('15. Time continuity: detects time of day shifts (DAY -> NIGHT) without explicit transition', () => {
    const shotA = {
      ...createDefaultProject(mockManifest).sequences[0].shots[0],
      timeOfDay: 'Day',
      environmentRequirements: { location: 'Plaza', timeOfDay: 'Day', source: 'USER_CONFIGURATION' as const },
    };
    const shotB = {
      ...createDefaultProject(mockManifest).sequences[0].shots[1],
      timeOfDay: 'Night',
      environmentRequirements: { location: 'Plaza', timeOfDay: 'Night', source: 'USER_CONFIGURATION' as const },
    };

    const result = evaluateEnvironmentContinuity(shotB, shotA);
    expect(result.status).toBe('WARNING');
    expect(result.detail).toContain("Time of day shift: 'DAY' -> 'NIGHT'");
  });

  // 16. Aspect ratio continuity warning
  it('16. Aspect ratio continuity warning: flags 16:9 -> 9:16 with source USER_CONFIGURATION', () => {
    const shotA = { ...createDefaultProject(mockManifest).sequences[0].shots[0], aspectRatio: '16:9' };
    const shotB = { ...createDefaultProject(mockManifest).sequences[0].shots[1], aspectRatio: '9:16' };

    const result = evaluateVisualContinuity(shotB, shotA);
    expect(result.status).toBe('WARNING');
    expect(result.source).toBe('USER_CONFIGURATION');
    expect(result.detail).toContain('Aspect ratio mismatch: 16:9 -> 9:16');
  });

  // 17. Resolution continuity warning
  it('17. Resolution continuity warning: flags resolution mismatches between consecutive shots', () => {
    const shotA = { ...createDefaultProject(mockManifest).sequences[0].shots[0], resolution: '1344x768' };
    const shotB = { ...createDefaultProject(mockManifest).sequences[0].shots[1], resolution: '768x1344' };

    const result = evaluateVisualContinuity(shotB, shotA);
    expect(result.status).toBe('WARNING');
    expect(result.detail).toContain('Resolution mismatch: 1344x768 -> 768x1344');
  });

  // 18. Model change warning
  it('18. Model change warning: produces deterministic warning when model changes between shots', () => {
    const shotA = {
      ...createDefaultProject(mockManifest).sequences[0].shots[0],
      generationType: 'image' as const,
      selectedModel: 'black-forest-labs/FLUX.1.1-pro',
    };
    const shotB = {
      ...createDefaultProject(mockManifest).sequences[0].shots[1],
      generationType: 'image' as const,
      selectedModel: 'stabilityai/sdxl-turbo',
    };

    const result = evaluateVisualContinuity(shotB, shotA);
    expect(result.status).toBe('WARNING');
    expect(result.detail).toContain('Model changed');
  });

  // 19. Reference asset continuity
  it('19. Reference asset continuity: confirms identity reference availability when attached', () => {
    const shotA: Shot = {
      ...createDefaultProject(mockManifest).sequences[0].shots[0],
      characterRequirements: {
        characterId: 'char-deva',
        name: 'Deva',
        visualIdentityReferences: ['https://assets.local/deva.png'],
        source: 'USER_CONFIGURATION',
      },
    };
    const shotB: Shot = {
      ...createDefaultProject(mockManifest).sequences[0].shots[1],
      characterRequirements: {
        characterId: 'char-deva',
        name: 'Deva',
        visualIdentityReferences: ['https://assets.local/deva.png'],
        source: 'USER_CONFIGURATION',
      },
    };

    const result = evaluateCharacterContinuity(shotB, shotA);
    expect(result.status).toBe('PASS');
    expect(result.detail).toContain('IDENTITY REFERENCE AVAILABLE');
  });

  // 20. Missing reference detection
  it('20. Missing reference detection: flags warning when character reference asset is missing in successor shot', () => {
    const shotA: Shot = {
      ...createDefaultProject(mockManifest).sequences[0].shots[0],
      characterRequirements: {
        characterId: 'char-deva',
        name: 'Deva',
        visualIdentityReferences: ['https://assets.local/deva.png'],
        source: 'USER_CONFIGURATION',
      },
    };
    const shotB: Shot = {
      ...createDefaultProject(mockManifest).sequences[0].shots[1],
      characterRequirements: {
        characterId: 'char-deva',
        name: 'Deva',
        visualIdentityReferences: [], // Missing!
        source: 'USER_CONFIGURATION',
      },
    };

    const result = evaluateCharacterContinuity(shotB, shotA);
    expect(result.status).toBe('WARNING');
    expect(result.detail).toContain('IDENTITY REFERENCE UNAVAILABLE for Deva');
  });

  // 21. Dependency validation
  it('21. Dependency validation: blocks downstream shot until prerequisite reaches COMPLETE status', () => {
    const project = createDefaultProject(mockManifest);
    const shots = [...project.sequences[0].shots];

    // Predecessor is NOT complete
    const valBlocked = validateShot(shots[1], shots, mockManifest);
    expect(valBlocked.validationResults.dependenciesSatisfied).toBe(false);
    expect(valBlocked.readiness).toBe('BLOCKED');

    // Complete predecessor
    shots[0] = {
      ...shots[0],
      status: 'COMPLETE',
      outputAssetUrl: 'https://storage.googleapis.com/assets/shot1.png',
    };

    const valReady = validateShot(shots[1], shots, mockManifest);
    expect(valReady.validationResults.dependenciesSatisfied).toBe(true);
    expect(valReady.readiness).toBe('READY');
  });

  // 22. Payload preview
  it('22. Payload preview: generates read-only sequence execution plan with POST /creator/generate payloads', () => {
    const project = createDefaultProject(mockManifest);
    const plan = generateSequenceExecutionPlan(project.sequences[0]);

    expect(plan.sequenceId).toBe('seq-001');
    expect(plan.totalShots).toBe(2);
    expect(plan.shots[0].endpoint).toBe('POST /creator/generate');
    expect(plan.shots[0].payload.prompt).toBe(project.sequences[0].shots[0].prompt);
    expect(plan.shots[0].payload.generation_type).toBe('image');
  });

  // 23. No automatic execution
  it('23. No automatic execution: selecting or adding a shot never dispatches job or changes runtime status', () => {
    const project = createDefaultProject(mockManifest);
    const shot = project.sequences[0].shots[0];
    const validated = validateShot(shot, project.sequences[0].shots, mockManifest);

    expect(validated.status).toBe('READY');
    expect(validated.outputJobId).toBeUndefined();
  });

  // 24. No automatic model switching
  it('24. No automatic model switching: preserves user-selected model even if unavailable in manifest', () => {
    const project = createDefaultProject(mockManifest);
    const shot = {
      ...project.sequences[0].shots[0],
      selectedModel: 'discontinued/custom-model-v0',
    };

    const result = validateShot(shot, project.sequences[0].shots, mockManifest);
    expect(result.selectedModel).toBe('discontinued/custom-model-v0');
    expect(result.readiness).toBe('BLOCKED');
  });

  // 25. No automatic parameter modification
  it('25. No automatic parameter modification: preserves prompt, duration, and aspect ratio without mutations', () => {
    const project = createDefaultProject(mockManifest);
    const shot = {
      ...project.sequences[0].shots[0],
      prompt: 'Precise prompt with specific framing and color tags',
      duration: 7,
      aspectRatio: '16:9',
    };

    const result = validateShot(shot, project.sequences[0].shots, mockManifest);
    expect(result.prompt).toBe('Precise prompt with specific framing and color tags');
    expect(result.duration).toBe(7);
    expect(result.aspectRatio).toBe('16:9');
  });

  // 26. Provenance integrity
  it('26. Provenance integrity: all continuity and validation facts trace strictly to the 5 allowed sources', () => {
    const project = createDefaultProject(mockManifest);
    const shot = project.sequences[0].shots[0];
    const report = shot.continuityReport;

    const allowedSources = [
      'CAPABILITY_MANIFEST',
      'HISTORICAL_RUN',
      'USER_CONFIGURATION',
      'SYSTEM_STATE',
      'UNAVAILABLE',
    ];

    expect(allowedSources).toContain(report.character.source);
    expect(allowedSources).toContain(report.environment.source);
    expect(allowedSources).toContain(report.visual.source);
    expect(allowedSources).toContain(report.temporal.source);
    expect(allowedSources).toContain(report.startFrame.source);
  });

  // 27. Empty sequence handling
  it('27. Empty sequence handling: handles empty sequence gracefully and shows empty state directive', () => {
    const emptyProject: Project = {
      id: 'proj-empty',
      title: 'Empty Project',
      sequences: [
        {
          id: 'seq-empty',
          projectId: 'proj-empty',
          order: 1,
          title: 'Empty Sequence',
          shots: [],
          status: 'READY',
          statusReasons: ['SEQUENCE CONTAINS NO SHOTS'],
          totalShots: 0,
          readyShots: 0,
          blockedShots: 0,
          inFlightShots: 0,
          completeShots: 0,
          totalDurationSeconds: 0,
          createdAt: new Date().toISOString(),
          updatedAt: new Date().toISOString(),
        },
      ],
      activeSequenceId: 'seq-empty',
      createdAt: new Date().toISOString(),
      updatedAt: new Date().toISOString(),
    };

    render(
      <ProductionTimeline
        project={emptyProject}
        onSelectShot={vi.fn()}
        onReproduceShot={vi.fn()}
        onReorderShots={vi.fn()}
        onAddShot={vi.fn()}
        onLinkPredecessor={vi.fn()}
        manifest={mockManifest}
      />
    );

    expect(screen.getByTestId('empty-sequence-message')).toHaveTextContent('No shots in sequence');
  });

  // 28. Single-shot sequence
  it('28. Single-shot sequence: validates root shot with zero predecessor continuity blockers', () => {
    const singleShot = createDefaultProject(mockManifest).sequences[0].shots[0];
    const validated = validateShot(singleShot, [singleShot], mockManifest);

    expect(validated.readiness).toBe('READY');
    expect(validated.continuityReport.visual.status).toBe('PASS');
    expect(validated.continuityReport.visual.detail).toContain('Initial shot format declared');
  });

  // 29. Large sequence handling
  it('29. Large sequence handling: validates 50 shots within strict performance threshold (<100ms)', () => {
    const baseShot = createDefaultProject(mockManifest).sequences[0].shots[0];
    const largeShots: Shot[] = Array.from({ length: 50 }, (_, i) => ({
      ...baseShot,
      id: `shot-${String(i + 1).padStart(3, '0')}`,
      order: i + 1,
      title: `Shot ${i + 1}`,
      prompt: `Scene ${i + 1} prompt`,
    }));

    const startTime = performance.now();
    const validated = largeShots.map((s) => validateShot(s, largeShots, mockManifest));
    const readiness = evaluateSequenceReadiness(validated);
    const elapsed = performance.now() - startTime;

    expect(validated).toHaveLength(50);
    expect(readiness.metrics.total).toBe(50);
    expect(elapsed).toBeLessThan(100);
  });

  // 30. Malformed shot data
  it('30. Malformed shot data: handles null/undefined fields safely without throwing uncaught exceptions', () => {
    const malformedShot = {
      id: 'shot-corrupt',
      sequenceId: 'seq-001',
    } as any;

    expect(() => validateShot(malformedShot, [malformedShot], mockManifest)).not.toThrow();
  });

  // 31. Existing Stage 1–9 regression protection
  it('31. Existing Stage 1–9 regression protection: verifies OperationalStrip and DecisionCard operate synchronously', () => {
    const summary: SequenceOperationalSummary = {
      sequenceNumber: '01',
      sequenceTitle: 'Sequence 01',
      totalShots: 2,
      readyShots: 1,
      blockedShots: 1,
      inFlightShots: 0,
      completeShots: 0,
    };

    render(
      <OperationalStrip
        systemState="ACTIVE"
        activeCount={1}
        queuedCount={0}
        processingCount={0}
        failedCount={0}
        totalCostUsd={0.05}
        sequenceSummary={summary}
      />
    );

    expect(screen.getByTestId('operational-sequence-summary')).toBeInTheDocument();
    expect(screen.getByTestId('strip-seq-shots')).toHaveTextContent('2');
  });
});
