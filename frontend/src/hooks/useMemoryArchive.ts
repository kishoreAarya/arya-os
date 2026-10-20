/**
 * AryaOS V1 — Stage 04: Spatial Memory Archive Hook
 *
 * Implements the spatial interaction state machine:
 * IDLE -> HOVERED -> SELECTED -> INSPECTING -> RELATED_MEMORY -> RETURN
 *
 * Handles selection, filtering, search, relationship traversal, and chronological timeline.
 */

import { useState, useMemo, useCallback, useEffect } from 'react';
import {
  MemoryRecord,
  MemoryType,
  MemoryInteractionState,
  MemoryFilterType,
  MemoryRelationship,
  VitrineMemoryMapping,
  TimelineContext,
} from '../types/memory';
import {
  memoryArchiveService,
  VITRINE_MAPPING_REGISTRY,
} from '../services/memoryArchiveService';

export interface UseMemoryArchiveReturn {
  // State
  interactionState: MemoryInteractionState;
  selectedMemoryId: string | null;
  hoveredMemoryId: string | null;
  hoveredVitrineId: string | null;
  activeVitrineId: string | null;
  activeMemory: MemoryRecord | null;
  activeMapping: VitrineMemoryMapping | null;
  searchQuery: string;
  activeFilter: MemoryFilterType;
  isDetailOpen: boolean;
  navigationHistory: string[];
  canNavigateBack: boolean;
  previousMemory: MemoryRecord | null;

  // Filtered & Resolved data
  allMemories: MemoryRecord[];
  filteredMemories: MemoryRecord[];
  relatedMemories: Array<{ memory: MemoryRecord; relationship: MemoryRelationship }>;
  timelineContext: TimelineContext | null;

  // Actions
  selectMemory: (memoryId: string | null) => void;
  selectVitrine: (vitrineId: string | null) => void;
  hoverMemory: (memoryId: string | null) => void;
  hoverVitrine: (vitrineId: string | null) => void;
  navigateToRelated: (targetMemoryId: string) => void;
  navigateBack: () => void;
  closeInspection: () => void;
  setSearchQuery: (query: string) => void;
  setActiveFilter: (filter: MemoryFilterType) => void;
  resetFilters: () => void;
}

export function useMemoryArchive(initialMemoryId?: string | null): UseMemoryArchiveReturn {
  const [interactionState, setInteractionState] = useState<MemoryInteractionState>('IDLE');
  const [selectedMemoryId, setSelectedMemoryId] = useState<string | null>(initialMemoryId || null);
  const [hoveredMemoryId, setHoveredMemoryId] = useState<string | null>(null);
  const [hoveredVitrineId, setHoveredVitrineId] = useState<string | null>(null);
  const [searchQuery, setSearchQuery] = useState<string>('');
  const [activeFilter, setActiveFilter] = useState<MemoryFilterType>('ALL');
  const [navigationHistory, setNavigationHistory] = useState<string[]>(
    initialMemoryId ? [initialMemoryId] : []
  );
  const [isDetailOpen, setIsDetailOpen] = useState<boolean>(Boolean(initialMemoryId));

  // Base dataset
  const allMemories = useMemo(() => memoryArchiveService.getAllMemories(), []);

  // Filtered dataset
  const filteredMemories = useMemo(() => {
    return memoryArchiveService.searchMemories(searchQuery, activeFilter);
  }, [searchQuery, activeFilter]);

  // Active Memory record
  const activeMemory = useMemo(() => {
    if (!selectedMemoryId) return null;
    return memoryArchiveService.getMemoryById(selectedMemoryId) || null;
  }, [selectedMemoryId]);

  // Active Vitrine ID & Mapping
  const activeVitrineId = useMemo(() => {
    if (!selectedMemoryId) return null;
    return memoryArchiveService.getVitrineIdByMemoryId(selectedMemoryId) || null;
  }, [selectedMemoryId]);

  const activeMapping = useMemo(() => {
    if (!activeVitrineId) return null;
    return (
      VITRINE_MAPPING_REGISTRY.find((m) => m.vitrineId === activeVitrineId) || null
    );
  }, [activeVitrineId]);

  // Related memories graph
  const relatedMemories = useMemo(() => {
    if (!selectedMemoryId) return [];
    return memoryArchiveService.getRelatedMemories(selectedMemoryId);
  }, [selectedMemoryId]);

  // Timeline Context
  const timelineContext = useMemo(() => {
    if (!selectedMemoryId) return null;
    return memoryArchiveService.getTimelineContext(selectedMemoryId);
  }, [selectedMemoryId]);

  // Navigation History Stack Helpers
  const canNavigateBack = navigationHistory.length > 1;
  const previousMemoryId = canNavigateBack ? navigationHistory[navigationHistory.length - 2] : null;
  const previousMemory = useMemo(() => {
    if (!previousMemoryId) return null;
    return memoryArchiveService.getMemoryById(previousMemoryId) || null;
  }, [previousMemoryId]);

  // Action: Select Memory
  const selectMemory = useCallback((memoryId: string | null) => {
    if (!memoryId) {
      setSelectedMemoryId(null);
      setIsDetailOpen(false);
      setInteractionState('IDLE');
      setNavigationHistory([]);
      return;
    }

    setSelectedMemoryId(memoryId);
    setIsDetailOpen(true);
    setInteractionState('INSPECTING');
    setNavigationHistory((prev) => {
      if (prev.length > 0 && prev[prev.length - 1] === memoryId) {
        return prev;
      }
      return [...prev, memoryId];
    });
  }, []);

  // Action: Select Vitrine (translates spatial click to semantic selection)
  const selectVitrine = useCallback((vitrineId: string | null) => {
    if (!vitrineId) {
      selectMemory(null);
      return;
    }
    const mem = memoryArchiveService.getMemoryByVitrineId(vitrineId);
    if (mem) {
      selectMemory(mem.id);
    } else {
      console.warn(`[Stage 04] No memory mapped for vitrine ${vitrineId}`);
    }
  }, [selectMemory]);

  // Action: Hover Memory
  const hoverMemory = useCallback((memoryId: string | null) => {
    setHoveredMemoryId(memoryId);
    if (memoryId) {
      const vId = memoryArchiveService.getVitrineIdByMemoryId(memoryId) || null;
      setHoveredVitrineId(vId);
      setInteractionState((curr) => (curr === 'IDLE' ? 'HOVERED' : curr));
    } else {
      setHoveredVitrineId(null);
      setInteractionState((curr) => (curr === 'HOVERED' ? 'IDLE' : curr));
    }
  }, []);

  // Action: Hover Vitrine
  const hoverVitrine = useCallback((vitrineId: string | null) => {
    setHoveredVitrineId(vitrineId);
    if (vitrineId) {
      const mem = memoryArchiveService.getMemoryByVitrineId(vitrineId);
      setHoveredMemoryId(mem ? mem.id : null);
      setInteractionState((curr) => (curr === 'IDLE' ? 'HOVERED' : curr));
    } else {
      setHoveredMemoryId(null);
      setInteractionState((curr) => (curr === 'HOVERED' ? 'IDLE' : curr));
    }
  }, []);

  // Action: Navigate to Related Memory
  const navigateToRelated = useCallback((targetMemoryId: string) => {
    setInteractionState('RELATED_MEMORY');
    setSelectedMemoryId(targetMemoryId);
    setIsDetailOpen(true);
    setNavigationHistory((prev) => [...prev, targetMemoryId]);
    setTimeout(() => {
      setInteractionState('INSPECTING');
    }, 120);
  }, []);

  // Action: Navigate Back in Stack
  const navigateBack = useCallback(() => {
    if (navigationHistory.length <= 1) {
      setSelectedMemoryId(null);
      setIsDetailOpen(false);
      setNavigationHistory([]);
      setInteractionState('RETURN');
      setTimeout(() => setInteractionState('IDLE'), 120);
      return;
    }

    const nextHistory = navigationHistory.slice(0, -1);
    const prevId = nextHistory[nextHistory.length - 1];
    setInteractionState('RETURN');
    setNavigationHistory(nextHistory);
    setSelectedMemoryId(prevId);
    setTimeout(() => {
      setInteractionState('INSPECTING');
    }, 120);
  }, [navigationHistory]);

  // Action: Close Inspection
  const closeInspection = useCallback(() => {
    setSelectedMemoryId(null);
    setIsDetailOpen(false);
    setNavigationHistory([]);
    setInteractionState('IDLE');
  }, []);

  // Action: Reset Filters
  const resetFilters = useCallback(() => {
    setSearchQuery('');
    setActiveFilter('ALL');
  }, []);

  // Global Keyboard Navigation
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      // Don't intercept if user is typing in an input or textarea
      if (
        e.target instanceof HTMLInputElement ||
        e.target instanceof HTMLTextAreaElement ||
        (e.target as HTMLElement)?.isContentEditable
      ) {
        if (e.key === 'Escape') {
          (e.target as HTMLElement).blur();
        }
        return;
      }

      if (e.key === 'Escape') {
        if (isDetailOpen) {
          e.preventDefault();
          closeInspection();
        }
      } else if (e.key === 'Backspace' || e.key === 'ArrowLeft') {
        if (isDetailOpen && canNavigateBack) {
          e.preventDefault();
          navigateBack();
        }
      }
    };

    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [isDetailOpen, canNavigateBack, closeInspection, navigateBack]);

  return {
    interactionState,
    selectedMemoryId,
    hoveredMemoryId,
    hoveredVitrineId,
    activeVitrineId,
    activeMemory,
    activeMapping,
    searchQuery,
    activeFilter,
    isDetailOpen,
    navigationHistory,
    canNavigateBack,
    previousMemory,

    allMemories,
    filteredMemories,
    relatedMemories,
    timelineContext,

    selectMemory,
    selectVitrine,
    hoverMemory,
    hoverVitrine,
    navigateToRelated,
    navigateBack,
    closeInspection,
    setSearchQuery,
    setActiveFilter,
    resetFilters,
  };
}
