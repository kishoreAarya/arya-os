import { describe, it, expect, vi } from 'vitest';
import React from 'react';
import { render, screen, fireEvent } from '@testing-library/react';
import { SpatialInspectorPanel } from '../components/spatial/SpatialInspectorPanel';
import { SpatialWorld } from '../components/spatial/SpatialWorld';
import { Project } from '../types/productionTimeline';
import { SpatialInspectorData } from '../types/spatial';

// Mock WebGL canvas & R3F for headless JSDOM environment
vi.mock('@react-three/fiber', () => ({
  Canvas: ({ children }: any) => <div data-testid="mock-r3f-canvas">{children}</div>,
  useFrame: vi.fn(),
  useThree: () => ({
    camera: {
      position: { set: vi.fn(), copy: vi.fn(), lerp: vi.fn() },
      lookAt: vi.fn(),
    },
  }),
}));

vi.mock('@react-three/drei', () => ({
  useGLTF: () => ({ scene: { clone: () => ({}) } }),
  MeshReflectorMaterial: () => null,
}));

describe('AryaOS V1 — Spatial Frontend Phase 13: Temporal Continuity & Production Graph', () => {
  const mockInspectorDataWithDependency: SpatialInspectorData = {
    category: 'SHOT',
    id: 'shot-02',
    title: 'SHOT INSPECTION // 02',
    subtitle: 'A neon drone swooping down towards the obsidian monolith',
    status: 'READY',
    statusVariant: 'active',
    metrics: [
      { label: 'Type', value: 'VIDEO' },
      { label: 'Duration', value: '5s' },
      { label: 'Aspect Ratio', value: '16:9' },
      { label: 'Continuity', value: 'PASS' },
    ],
    details: [
      'Predecessor Link: Shot shot-01',
      'Dependency State: READY',
      'First Frame Anchor: Attached (PROVIDED)',
    ],
    temporalDependency: {
      predecessorId: 'shot-01',
      predecessorTitle: 'Shot 01 // Monolith Origin',
      anchorType: 'LAST FRAME',
      anchorStatus: 'VERIFIED',
      continuityStatus: 'PASS',
      conditioningTarget: 'FIRST FRAME',
      sourceArtifactPath: '/storage/artifacts/shot_01_last.png',
      validationLevel: 'STRUCTURAL_TECHNICAL_CONTINUITY',
    },
  };

  it('1. renders TEMPORAL DEPENDENCY section in SpatialInspectorPanel with all required fields', () => {
    const handleClose = vi.fn();
    render(<SpatialInspectorPanel data={mockInspectorDataWithDependency} onClose={handleClose} />);

    const tempDepSection = screen.getByTestId('spatial-inspector-temporal-dependency');
    expect(tempDepSection).toBeInTheDocument();

    // Verify Predecessor
    const predecessor = screen.getByTestId('spatial-inspector-predecessor');
    expect(predecessor).toHaveTextContent('Shot 01 // Monolith Origin');

    // Verify Anchor Status
    const anchorStatus = screen.getByTestId('spatial-inspector-anchor-status');
    expect(anchorStatus).toHaveTextContent('✓ VERIFIED');

    // Verify Continuity Badge
    const continuityBadge = screen.getByTestId('spatial-inspector-continuity-badge');
    expect(continuityBadge).toHaveTextContent('PASS');

    // Verify Conditioning Target
    expect(tempDepSection).toHaveTextContent('CONDITIONING');
    expect(tempDepSection).toHaveTextContent('FIRST FRAME');

    // Verify Source Artifact
    const sourceArtifact = screen.getByTestId('spatial-inspector-source-artifact');
    expect(sourceArtifact).toHaveTextContent('shot_01_last.png');

    // Verify Level
    expect(tempDepSection).toHaveTextContent('STRUCTURAL_TECHNICAL_CONTINUITY');
  });

  it('2. renders warning and blocked continuity states accurately in inspector', () => {
    const blockedData: SpatialInspectorData = {
      ...mockInspectorDataWithDependency,
      temporalDependency: {
        ...mockInspectorDataWithDependency.temporalDependency!,
        continuityStatus: 'BLOCKED',
        anchorStatus: 'MISSING',
      },
    };

    const { rerender } = render(<SpatialInspectorPanel data={blockedData} onClose={vi.fn()} />);

    let continuityBadge = screen.getByTestId('spatial-inspector-continuity-badge');
    expect(continuityBadge).toHaveTextContent('BLOCKED');
    let anchorStatus = screen.getByTestId('spatial-inspector-anchor-status');
    expect(anchorStatus).toHaveTextContent('MISSING');

    const warningData: SpatialInspectorData = {
      ...mockInspectorDataWithDependency,
      temporalDependency: {
        ...mockInspectorDataWithDependency.temporalDependency!,
        continuityStatus: 'WARNING',
        anchorStatus: 'PENDING',
      },
    };

    rerender(<SpatialInspectorPanel data={warningData} onClose={vi.fn()} />);

    continuityBadge = screen.getByTestId('spatial-inspector-continuity-badge');
    expect(continuityBadge).toHaveTextContent('WARNING');
    anchorStatus = screen.getByTestId('spatial-inspector-anchor-status');
    expect(anchorStatus).toHaveTextContent('PENDING');
  });

  it('3. renders dependency badges, predecessor links, and last-frame badges in corridor', () => {
    const mockProject: Project = {
      id: 'proj-phase13',
      title: 'Temporal Continuity Production',
      activeSequenceId: 'seq-01',
      activeShotId: 'shot-01',
      sequences: [
        {
          id: 'seq-01',
          projectId: 'proj-phase13',
          title: 'Sequence 01',
          order: 1,
          totalShots: 2,
          readyShots: 1,
          blockedShots: 0,
          inFlightShots: 0,
          completeShots: 1,
          status: 'READY',
          shots: [
            {
              id: 'shot-01',
              sequenceId: 'seq-01',
              order: 1,
              title: 'Shot 01',
              prompt: 'Establishing landscape',
              generationType: 'image',
              status: 'COMPLETE',
              duration: 5,
              aspectRatio: '16:9',
              selectedModel: 'flux-schnell',
              selectedProvider: 'fal',
              dependencyShotIds: [],
              readiness: 'READY',
              validationResults: {
                isValid: true,
                readiness: 'READY',
                reasons: [],
                reasonCodes: [],
                preflightReady: true,
                dependenciesSatisfied: true,
                startFrameSatisfied: true,
              },
              continuityReport: {
                character: { status: 'PASS', detail: 'OK', source: 'USER_CONFIGURATION' },
                environment: { status: 'PASS', detail: 'OK', source: 'USER_CONFIGURATION' },
                visual: { status: 'PASS', detail: 'OK', source: 'USER_CONFIGURATION' },
                temporal: { status: 'PASS', detail: 'OK', source: 'USER_CONFIGURATION' },
                startFrame: { status: 'NOT_APPLICABLE', detail: 'Root shot', source: 'USER_CONFIGURATION' },
              },
              provenance: 'USER_CONFIGURATION',
              outputAssetUrl: '/api/v1/artifacts/shot_01.png',
              dependencyState: 'INDEPENDENT',
              lastFrame: '/api/v1/artifacts/shot_01_last.png',
            },
            {
              id: 'shot-02',
              sequenceId: 'seq-01',
              order: 2,
              title: 'Shot 02',
              prompt: 'Drone flying into landscape',
              generationType: 'video',
              status: 'READY',
              duration: 5,
              aspectRatio: '16:9',
              selectedModel: 'kling-video',
              selectedProvider: 'kling',
              predecessorShotId: 'shot-01',
              dependencyShotIds: ['shot-01'],
              readiness: 'READY',
              validationResults: {
                isValid: true,
                readiness: 'READY',
                reasons: [],
                reasonCodes: [],
                preflightReady: true,
                dependenciesSatisfied: true,
                startFrameSatisfied: true,
              },
              continuityReport: {
                character: { status: 'PASS', detail: 'OK', source: 'USER_CONFIGURATION' },
                environment: { status: 'PASS', detail: 'OK', source: 'USER_CONFIGURATION' },
                visual: { status: 'PASS', detail: 'OK', source: 'USER_CONFIGURATION' },
                temporal: { status: 'PASS', detail: 'OK', source: 'USER_CONFIGURATION' },
                startFrame: { status: 'PROVIDED', detail: 'Conditioned on Shot 01', source: 'USER_CONFIGURATION' },
              },
              provenance: 'USER_CONFIGURATION',
              dependencyState: 'READY',
              firstFrame: '/api/v1/artifacts/shot_01_last.png',
            },
          ],
          statusReasons: [],
          totalDurationSeconds: 10,
          createdAt: new Date().toISOString(),
          updatedAt: new Date().toISOString(),
        },
      ],
      createdAt: new Date().toISOString(),
      updatedAt: new Date().toISOString(),

    };

    render(<SpatialWorld project={mockProject} />);

    // Check Shot 01 badges
    const shot1DepBadge = screen.getByTestId('spatial-shot-dependency-badge-shot-01');
    expect(shot1DepBadge).toHaveTextContent('INDEPENDENT');
    const shot1LastFrameBadge = screen.getByTestId('spatial-shot-last-frame-badge-shot-01');
    expect(shot1LastFrameBadge).toHaveTextContent('[LAST FRAME ✓]');

    // Check Shot 02 badges and link
    const shot2DepBadge = screen.getByTestId('spatial-shot-dependency-badge-shot-02');
    expect(shot2DepBadge).toHaveTextContent('READY');
    const shot2PredecessorLink = screen.getByTestId('spatial-shot-predecessor-link-shot-02');
    expect(shot2PredecessorLink).toHaveTextContent('[FIRST FRAME ← SHOT 1]');
  });

  it('4. clicking a dependent shot in SpatialWorld opens inspector with populated temporal dependency', () => {
    const mockProject: Project = {
      id: 'proj-phase13-select',
      title: 'Temporal Continuity Select',
      activeSequenceId: 'seq-01',
      activeShotId: 'shot-01',
      sequences: [
        {
          id: 'seq-01',
          projectId: 'proj-phase13',
          title: 'Sequence 01',
          order: 1,
          totalShots: 2,
          readyShots: 1,
          blockedShots: 0,
          inFlightShots: 0,
          completeShots: 1,
          status: 'READY',
          shots: [
            {
              id: 'shot-01',
              sequenceId: 'seq-01',
              order: 1,
              title: 'Shot 01 Genesis',
              prompt: 'Genesis origin frame',
              generationType: 'image',
              status: 'COMPLETE',
              duration: 5,
              aspectRatio: '16:9',
              selectedModel: 'flux-schnell',
              selectedProvider: 'fal',
              dependencyShotIds: [],
              readiness: 'READY',
              validationResults: {
                isValid: true,
                readiness: 'READY',
                reasons: [],
                reasonCodes: [],
                preflightReady: true,
                dependenciesSatisfied: true,
                startFrameSatisfied: true,
              },
              continuityReport: {
                character: { status: 'PASS', detail: 'OK', source: 'USER_CONFIGURATION' },
                environment: { status: 'PASS', detail: 'OK', source: 'USER_CONFIGURATION' },
                visual: { status: 'PASS', detail: 'OK', source: 'USER_CONFIGURATION' },
                temporal: { status: 'PASS', detail: 'OK', source: 'USER_CONFIGURATION' },
                startFrame: { status: 'NOT_APPLICABLE', detail: 'Root', source: 'USER_CONFIGURATION' },
              },
              provenance: 'USER_CONFIGURATION',
              outputAssetUrl: '/api/v1/artifacts/shot_01.png',
              dependencyState: 'INDEPENDENT',
              lastFrame: '/api/v1/artifacts/shot_01_last.png',
            },
            {
              id: 'shot-02',
              sequenceId: 'seq-01',
              order: 2,
              title: 'Shot 02 Continuation',
              prompt: 'Continuing the trajectory',
              generationType: 'video',
              status: 'READY',
              duration: 5,
              aspectRatio: '16:9',
              selectedModel: 'kling-video',
              selectedProvider: 'kling',
              predecessorShotId: 'shot-01',
              dependencyShotIds: ['shot-01'],
              readiness: 'READY',
              validationResults: {
                isValid: true,
                readiness: 'READY',
                reasons: [],
                reasonCodes: [],
                preflightReady: true,
                dependenciesSatisfied: true,
                startFrameSatisfied: true,
              },
              continuityReport: {
                character: { status: 'PASS', detail: 'OK', source: 'USER_CONFIGURATION' },
                environment: { status: 'PASS', detail: 'OK', source: 'USER_CONFIGURATION' },
                visual: { status: 'PASS', detail: 'OK', source: 'USER_CONFIGURATION' },
                temporal: { status: 'PASS', detail: 'OK', source: 'USER_CONFIGURATION' },
                startFrame: { status: 'PROVIDED', detail: 'Provided by shot 01', source: 'USER_CONFIGURATION' },
              },
              provenance: 'USER_CONFIGURATION',
              dependencyState: 'READY',
              firstFrame: '/api/v1/artifacts/shot_01_last.png',
            },
          ],
          statusReasons: [],
          totalDurationSeconds: 10,
          createdAt: new Date().toISOString(),
          updatedAt: new Date().toISOString(),
        },
      ],
      createdAt: new Date().toISOString(),
      updatedAt: new Date().toISOString(),

    };

    render(<SpatialWorld project={mockProject} />);

    // Click on Shot 02 card
    const shot2Button = screen.getByTestId('spatial-shot-shot-02');
    fireEvent.click(shot2Button);

    // Inspector should now open and display TEMPORAL DEPENDENCY section
    const tempDepSection = screen.getByTestId('spatial-inspector-temporal-dependency');
    expect(tempDepSection).toBeInTheDocument();

    const predecessor = screen.getByTestId('spatial-inspector-predecessor');
    expect(predecessor).toHaveTextContent('Shot 01');

    const anchorStatus = screen.getByTestId('spatial-inspector-anchor-status');
    expect(anchorStatus).toHaveTextContent('✓ VERIFIED');
  });
});
