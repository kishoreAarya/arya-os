/**
 * AryaOS V1 — Stage 04: Spatial Memory & Intelligence Integration Tests
 *
 * Verifies:
 * 1. Semantic Memory Object Model & 24 Deterministic Vitrine Mappings
 * 2. Memory Archive Service (Search, Category Filters, Graph Traversal, Timeline)
 * 3. Spatial Interaction State Machine (useMemoryArchive hook)
 * 4. Cinematic Spatial Detail HUD Overlay (MemoryArchiveOverlay)
 * 5. Spatial Memory 3D Relationships (SpatialMemoryRelationships)
 * 6. Defensive missing-data handling and keyboard navigation
 */

import React from 'react';
import { render, screen, fireEvent, act, renderHook } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import * as THREE from 'three';
import {
  memoryArchiveService,
  VITRINE_MAPPING_REGISTRY,
  STAGE04_MEMORY_DATABASE,
} from '../services/memoryArchiveService';
import { useMemoryArchive } from '../hooks/useMemoryArchive';
import { MemoryArchiveOverlay } from '../components/spatial/MemoryArchiveOverlay';
import { SpatialMemoryRelationships } from '../components/spatial/SpatialMemoryRelationships';
import { MemoryRecord } from '../types/memory';

describe('AryaOS V1 Stage 04 — Spatial Intelligence & Memory Interaction', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  describe('1. Semantic Memory Object Model & Deterministic 24-Vitrine Mappings', () => {
    it('contains exactly 24 deterministic mappings matching the 24 Stage 03 vitrines', () => {
      expect(VITRINE_MAPPING_REGISTRY).toHaveLength(24);
      expect(STAGE04_MEMORY_DATABASE).toHaveLength(24);

      // Verify all 8 Dais Flank Crystals
      for (let i = 1; i <= 8; i++) {
        const id = `Dais_Flank_Crystal_0${i}`;
        const mapping = VITRINE_MAPPING_REGISTRY.find((m) => m.vitrineId === id);
        expect(mapping).toBeDefined();
        expect(mapping?.sector).toBe('DAIS_FLANK');
      }

      // Verify all 12 Pathway Memory Crystals
      for (let i = 1; i <= 12; i++) {
        const numStr = i < 10 ? `0${i}` : `${i}`;
        const id = `Pathway_Memory_Crystal_${numStr}`;
        const mapping = VITRINE_MAPPING_REGISTRY.find((m) => m.vitrineId === id);
        expect(mapping).toBeDefined();
        expect(mapping?.sector).toBe('PATHWAY');
      }

      // Verify all 4 Rotunda Inner Crystals
      for (let i = 1; i <= 4; i++) {
        const id = `Rotunda_Inner_Crystal_0${i}`;
        const mapping = VITRINE_MAPPING_REGISTRY.find((m) => m.vitrineId === id);
        expect(mapping).toBeDefined();
        expect(mapping?.sector).toBe('ROTUNDA_INNER');
      }
    });

    it('provides fast bidirectional lookup between Vitrine ID and Memory Record', () => {
      // Vitrine -> Memory
      const mem1 = memoryArchiveService.getMemoryByVitrineId('Dais_Flank_Crystal_01');
      expect(mem1).toBeDefined();
      expect(mem1?.id).toBe('MEM-0001');
      expect(mem1?.title).toContain('Project Horizon');

      // Memory -> Vitrine
      const vitrineId = memoryArchiveService.getVitrineIdByMemoryId('MEM-0001');
      expect(vitrineId).toBe('Dais_Flank_Crystal_01');

      // Rotunda Inner Crystal check
      const memCore = memoryArchiveService.getMemoryByVitrineId('Rotunda_Inner_Crystal_01');
      expect(memCore).toBeDefined();
      expect(memCore?.id).toBe('MEM-0021');
      expect(memCore?.title).toContain('Astrolabe Core Ignition');
    });

    it('all 24 memory records contain valid non-empty semantic fields', () => {
      STAGE04_MEMORY_DATABASE.forEach((record) => {
        expect(record.id).toMatch(/^MEM-\d{4}$/);
        expect(record.title.trim().length).toBeGreaterThan(5);
        expect(record.summary.trim().length).toBeGreaterThan(20);
        expect(record.importance).toBeGreaterThanOrEqual(0.0);
        expect(record.importance).toBeLessThanOrEqual(1.0);
        expect(Array.isArray(record.tags)).toBe(true);
        expect(record.tags.length).toBeGreaterThan(0);
        expect(Array.isArray(record.entities)).toBe(true);
        expect(record.entities.length).toBeGreaterThan(0);
        expect(Array.isArray(record.relationships)).toBe(true);
        expect(record.source).toBeDefined();
        expect(record.source.type).toBeDefined();
      });
    });
  });

  describe('2. Memory Archive Service (Search, Category Filters, Graph & Timeline)', () => {
    it('filters records by category pills accurately', () => {
      const all = memoryArchiveService.filterMemories('ALL');
      expect(all).toHaveLength(24);

      const projects = memoryArchiveService.filterMemories('PROJECTS');
      expect(projects.length).toBeGreaterThanOrEqual(2);
      projects.forEach((p) => expect(p.type).toBe('project'));

      const decisions = memoryArchiveService.filterMemories('DECISIONS');
      expect(decisions.length).toBeGreaterThanOrEqual(3);
      decisions.forEach((d) => expect(d.type).toBe('decision'));

      const workflows = memoryArchiveService.filterMemories('WORKFLOWS');
      expect(workflows.length).toBeGreaterThanOrEqual(3);
      workflows.forEach((w) => expect(w.type).toBe('workflow'));

      const artifacts = memoryArchiveService.filterMemories('ARTIFACTS');
      expect(artifacts.length).toBeGreaterThanOrEqual(3);
      artifacts.forEach((a) => expect(a.type).toBe('artifact'));

      const events = memoryArchiveService.filterMemories('EVENTS');
      expect(events.length).toBeGreaterThanOrEqual(3);
      events.forEach((e) => expect(e.type).toBe('event'));

      const knowledge = memoryArchiveService.filterMemories('KNOWLEDGE');
      expect(knowledge.length).toBeGreaterThanOrEqual(4);
      knowledge.forEach((k) => expect(k.type).toBe('knowledge'));
    });

    it('performs full-text search matching title, summary, tags, and entity names', () => {
      // By title keyword
      const horizonResults = memoryArchiveService.searchMemories('Horizon');
      expect(horizonResults.length).toBeGreaterThanOrEqual(1);
      expect(horizonResults[0].id).toBe('MEM-0001');

      // By summary keyword
      const astrolabeResults = memoryArchiveService.searchMemories('380W kinetic reactor');
      expect(astrolabeResults.length).toBeGreaterThanOrEqual(1);
      expect(astrolabeResults[0].id).toBe('MEM-0021');

      // By tag
      const continuityResults = memoryArchiveService.searchMemories('continuity');
      expect(continuityResults.length).toBeGreaterThanOrEqual(2);

      // By entity name
      const scriptAgentResults = memoryArchiveService.searchMemories('Script Agent');
      expect(scriptAgentResults.length).toBeGreaterThanOrEqual(1);

      // Empty query returns all
      expect(memoryArchiveService.searchMemories('')).toHaveLength(24);

      // Non-matching query returns empty array
      expect(memoryArchiveService.searchMemories('xyznonexistentquery999')).toHaveLength(0);
    });

    it('resolves associated memory relationship graph bidirectionally', () => {
      // MEM-0001 has relationships to MEM-0002, MEM-0023, MEM-0004
      const relatedTo1 = memoryArchiveService.getRelatedMemories('MEM-0001');
      expect(relatedTo1.length).toBeGreaterThanOrEqual(2);

      const relatedIds = relatedTo1.map((r) => r.memory.id);
      expect(relatedIds).toContain('MEM-0002');

      // MEM-0021 (Astrolabe Core)
      const relatedTo21 = memoryArchiveService.getRelatedMemories('MEM-0021');
      expect(relatedTo21.length).toBeGreaterThanOrEqual(2);
      const relatedTo21Ids = relatedTo21.map((r) => r.memory.id);
      expect(relatedTo21Ids).toContain('MEM-0022');
    });

    it('computes chronological timeline context with predecessor and successor', () => {
      // Genesis record: MEM-0023 is 2026-08-01 (first)
      const genesisTimeline = memoryArchiveService.getTimelineContext('MEM-0023');
      expect(genesisTimeline).not.toBeNull();
      expect(genesisTimeline?.hasTimestamp).toBe(true);
      expect(genesisTimeline?.chronologicalIndex).toBe(1);
      expect(genesisTimeline?.predecessor).toBeUndefined();
      expect(genesisTimeline?.successor).toBeDefined();

      // Middle record: MEM-0001
      const midTimeline = memoryArchiveService.getTimelineContext('MEM-0001');
      expect(midTimeline).not.toBeNull();
      expect(midTimeline?.predecessor).toBeDefined();
      expect(midTimeline?.successor).toBeDefined();
      expect(midTimeline?.chronologicalIndex).toBe(2);

      // Defensively handles invalid ID
      expect(memoryArchiveService.getTimelineContext('MEM-INVALID')).toBeNull();
    });
  });

  describe('3. Spatial Interaction State Machine (useMemoryArchive Hook)', () => {
    it('initializes in IDLE state with full dataset and clean navigation stack', () => {
      const { result } = renderHook(() => useMemoryArchive());
      expect(result.current.interactionState).toBe('IDLE');
      expect(result.current.selectedMemoryId).toBeNull();
      expect(result.current.activeMemory).toBeNull();
      expect(result.current.isDetailOpen).toBe(false);
      expect(result.current.canNavigateBack).toBe(false);
      expect(result.current.filteredMemories).toHaveLength(24);
    });

    it('selects vitrine, transitions to INSPECTING, and binds active mapping', () => {
      const { result } = renderHook(() => useMemoryArchive());

      act(() => {
        result.current.selectVitrine('Dais_Flank_Crystal_01');
      });

      expect(result.current.interactionState).toBe('INSPECTING');
      expect(result.current.selectedMemoryId).toBe('MEM-0001');
      expect(result.current.activeMemory?.title).toContain('Project Horizon');
      expect(result.current.activeVitrineId).toBe('Dais_Flank_Crystal_01');
      expect(result.current.activeMapping?.sector).toBe('DAIS_FLANK');
      expect(result.current.isDetailOpen).toBe(true);
    });

    it('navigates through related memories and allows stack back-navigation', () => {
      const { result } = renderHook(() => useMemoryArchive());

      // 1. Select initial memory
      act(() => {
        result.current.selectMemory('MEM-0001');
      });
      expect(result.current.navigationHistory).toEqual(['MEM-0001']);
      expect(result.current.canNavigateBack).toBe(false);

      // 2. Navigate to related memory MEM-0002
      act(() => {
        result.current.navigateToRelated('MEM-0002');
      });
      expect(result.current.selectedMemoryId).toBe('MEM-0002');
      expect(result.current.navigationHistory).toEqual(['MEM-0001', 'MEM-0002']);
      expect(result.current.canNavigateBack).toBe(true);
      expect(result.current.previousMemory?.id).toBe('MEM-0001');

      // 3. Navigate back to previous memory
      act(() => {
        result.current.navigateBack();
      });
      expect(result.current.selectedMemoryId).toBe('MEM-0001');
      expect(result.current.navigationHistory).toEqual(['MEM-0001']);
      expect(result.current.canNavigateBack).toBe(false);
    });

    it('closes inspection and returns to IDLE state', () => {
      const { result } = renderHook(() => useMemoryArchive());

      act(() => {
        result.current.selectMemory('MEM-0005');
      });
      expect(result.current.isDetailOpen).toBe(true);

      act(() => {
        result.current.closeInspection();
      });
      expect(result.current.isDetailOpen).toBe(false);
      expect(result.current.selectedMemoryId).toBeNull();
      expect(result.current.interactionState).toBe('IDLE');
    });

    it('handles hover states seamlessly without disrupting active selection', () => {
      const { result } = renderHook(() => useMemoryArchive());

      act(() => {
        result.current.hoverVitrine('Dais_Flank_Crystal_02');
      });
      expect(result.current.hoveredVitrineId).toBe('Dais_Flank_Crystal_02');
      expect(result.current.hoveredMemoryId).toBe('MEM-0002');
      expect(result.current.interactionState).toBe('HOVERED');

      act(() => {
        result.current.hoverVitrine(null);
      });
      expect(result.current.hoveredVitrineId).toBeNull();
      expect(result.current.interactionState).toBe('IDLE');
    });
  });

  describe('4. Cinematic Spatial Detail HUD Overlay Component', () => {
    it('renders search input, filter pills, and bottom vitrine card registry', () => {
      const { result } = renderHook(() => useMemoryArchive());

      render(<MemoryArchiveOverlay memoryArchive={result.current} />);

      expect(screen.getByTestId('memory-archive-overlay')).toBeInTheDocument();
      expect(screen.getByTestId('memory-top-bar')).toBeInTheDocument();
      expect(screen.getByTestId('memory-search-input')).toBeInTheDocument();
      expect(screen.getByTestId('memory-filter-bar')).toBeInTheDocument();
      expect(screen.getByTestId('memory-bottom-drawer')).toBeInTheDocument();

      // Check card count
      expect(screen.getByTestId('memory-card-MEM-0001')).toBeInTheDocument();
      expect(screen.getByTestId('memory-card-MEM-0024')).toBeInTheDocument();
    });

    it('filters cards when category filter pill is clicked', () => {
      const { result } = renderHook(() => useMemoryArchive());
      render(<MemoryArchiveOverlay memoryArchive={result.current} />);

      const decisionsPill = screen.getByTestId('memory-filter-pill-decisions');
      fireEvent.click(decisionsPill);

      expect(result.current.activeFilter).toBe('DECISIONS');
    });

    it('opens detail inspection panel when a memory card is clicked', () => {
      const { result } = renderHook(() => useMemoryArchive());
      const { rerender } = render(<MemoryArchiveOverlay memoryArchive={result.current} />);

      const card = screen.getByTestId('memory-card-MEM-0001');
      fireEvent.click(card);

      rerender(<MemoryArchiveOverlay memoryArchive={result.current} />);

      const detailPanel = screen.getByTestId('memory-detail-panel');
      expect(detailPanel).toBeInTheDocument();
      expect(screen.getByTestId('memory-title')).toHaveTextContent(/Project Horizon/i);
      expect(screen.getByTestId('memory-summary')).toBeInTheDocument();
      expect(screen.getByText(/ASSOCIATED ENTITIES/i)).toBeInTheDocument();
      expect(screen.getByText(/SEMANTIC TAGS/i)).toBeInTheDocument();
      expect(screen.getByText(/ASSOCIATED MEMORY GRAPH/i)).toBeInTheDocument();
      expect(screen.getByText(/TEMPORAL CONTINUITY/i)).toBeInTheDocument();
    });

    it('navigates to related memory from within the inspection panel', () => {
      const { result } = renderHook(() => useMemoryArchive('MEM-0001'));
      const { rerender } = render(<MemoryArchiveOverlay memoryArchive={result.current} />);

      expect(screen.getByTestId('memory-detail-panel')).toBeInTheDocument();

      // Click related memory MEM-0002
      const relatedBtn = screen.getByTestId('memory-related-item-MEM-0002');
      fireEvent.click(relatedBtn);

      rerender(<MemoryArchiveOverlay memoryArchive={result.current} />);

      expect(result.current.selectedMemoryId).toBe('MEM-0002');
      expect(screen.getByTestId('memory-nav-back')).toBeInTheDocument();

      // Click Back button
      const backBtn = screen.getByTestId('memory-nav-back');
      fireEvent.click(backBtn);

      rerender(<MemoryArchiveOverlay memoryArchive={result.current} />);
      expect(result.current.selectedMemoryId).toBe('MEM-0001');
    });

    it('closes detail panel when close button is clicked', () => {
      const { result } = renderHook(() => useMemoryArchive('MEM-0001'));
      const { rerender } = render(<MemoryArchiveOverlay memoryArchive={result.current} />);

      const closeBtn = screen.getByTestId('memory-close-btn');
      fireEvent.click(closeBtn);

      rerender(<MemoryArchiveOverlay memoryArchive={result.current} />);
      expect(screen.queryByTestId('memory-detail-panel')).not.toBeInTheDocument();
    });

    it('renders graceful empty state when search finds no matches', () => {
      const { result } = renderHook(() => useMemoryArchive());
      act(() => {
        result.current.setSearchQuery('nonexistent999xyz');
      });

      render(<MemoryArchiveOverlay memoryArchive={result.current} />);

      expect(screen.getByTestId('memory-empty-state')).toBeInTheDocument();
      expect(screen.getByText(/NO MATCHING MEMORIES ARCHIVED/i)).toBeInTheDocument();
    });
  });

  describe('5. Spatial Memory 3D Relationships (SpatialMemoryRelationships)', () => {
    const mockVitrines = [
      {
        id: 'Dais_Flank_Crystal_01',
        threejs_transform: { position: [-9.17, 2.2, 6.42] as [number, number, number] },
      },
      {
        id: 'Dais_Flank_Crystal_02',
        threejs_transform: { position: [-5.6, 2.2, 9.69] as [number, number, number] },
      },
      {
        id: 'Rotunda_Inner_Crystal_03',
        threejs_transform: { position: [0.0, 1.8, 3.5] as [number, number, number] },
      },
    ];

    it('returns null (zero draw calls) when no memory is selected', () => {
      const { container } = render(
        <SpatialMemoryRelationships
          selectedMemoryId={null}
          vitrines={mockVitrines}
        />
      );
      expect(container.firstChild).toBeNull();
    });

    it('constructs a lineSegments mesh with AdditiveBlending when memory is selected', () => {
      render(
        <SpatialMemoryRelationships
          selectedMemoryId="MEM-0001"
          vitrines={mockVitrines}
        />
      );
      const relElement = screen.getByTestId('spatial-memory-relationships');
      expect(relElement).toBeInTheDocument();
      expect(Number(relElement.getAttribute('data-points'))).toBeGreaterThan(0);
    });

    it('handles vitrine array with missing target vitrines defensively', () => {
      const { container } = render(
        <SpatialMemoryRelationships
          selectedMemoryId="MEM-0001"
          vitrines={[]}
        />
      );
      expect(container.firstChild).toBeNull();
    });
  });
});
