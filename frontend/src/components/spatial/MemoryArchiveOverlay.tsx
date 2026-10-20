/**
 * AryaOS V1 — Stage 04: Spatial Memory Archive HUD Overlay
 *
 * Cinematic obsidian HUD interface for Stage 03 Memory Archive:
 * - Search & Category Filter bar
 * - Real-time Vitrine Hover Telemetry
 * - Semantic Memory Inspector (Metadata, Entities, Tags, Importance)
 * - Relationship Graph Links & Jump Navigation
 * - Chronological Timeline Bar (Predecessor, Current, Successor)
 * - Navigation History Stack (Back / Forward)
 * - Defensive empty states & Accessibility
 */

import React, { useRef, useEffect } from 'react';
import {
  Search,
  X,
  ArrowLeft,
  ArrowRight,
  Database,
  Tag,
  Users,
  Compass,
  Layers,
  Sparkles,
  Clock,
  ExternalLink,
  ShieldCheck,
  ChevronRight,
  Activity,
} from 'lucide-react';
import {
  MemoryFilterType,
  MemoryRecord,
  MemoryType,
} from '../../types/memory';
import { UseMemoryArchiveReturn } from '../../hooks/useMemoryArchive';
import { UseSpatialCommandReturn, useSpatialCommand } from '../../hooks/useSpatialCommand';
import { SpatialCommandConsole } from './SpatialCommandConsole';
import { SpatialActionPreview } from './SpatialActionPreview';

export interface MemoryArchiveOverlayProps {
  memoryArchive: UseMemoryArchiveReturn;
  commandControl?: UseSpatialCommandReturn;
  isReducedMotion?: boolean;
}

const FILTER_PILLS: Array<{ id: MemoryFilterType; label: string; countSuffix?: string }> = [
  { id: 'ALL', label: 'ALL ARCHIVES' },
  { id: 'PROJECTS', label: 'PROJECTS' },
  { id: 'DECISIONS', label: 'DECISIONS' },
  { id: 'CONVERSATIONS', label: 'DIALOGUES' },
  { id: 'WORKFLOWS', label: 'WORKFLOWS' },
  { id: 'ARTIFACTS', label: 'ARTIFACTS' },
  { id: 'EVENTS', label: 'EVENTS' },
  { id: 'KNOWLEDGE', label: 'KNOWLEDGE' },
];

function getTypeColor(type: MemoryType): { badge: string; border: string; bg: string; text: string } {
  switch (type) {
    case 'project':
      return { badge: '#38bdf8', border: 'rgba(56, 189, 248, 0.3)', bg: 'rgba(56, 189, 248, 0.1)', text: '#7dd3fc' };
    case 'decision':
      return { badge: '#f59e0b', border: 'rgba(245, 158, 11, 0.3)', bg: 'rgba(245, 158, 11, 0.1)', text: '#fcd34d' };
    case 'conversation':
      return { badge: '#a855f7', border: 'rgba(168, 85, 247, 0.3)', bg: 'rgba(168, 85, 247, 0.1)', text: '#d8b4fe' };
    case 'workflow':
      return { badge: '#10b981', border: 'rgba(16, 185, 129, 0.3)', bg: 'rgba(16, 185, 129, 0.1)', text: '#6ee7b7' };
    case 'artifact':
      return { badge: '#ec4899', border: 'rgba(236, 72, 153, 0.3)', bg: 'rgba(236, 72, 153, 0.1)', text: '#f472b6' };
    case 'event':
      return { badge: '#f97316', border: 'rgba(249, 115, 22, 0.3)', bg: 'rgba(249, 115, 22, 0.1)', text: '#fdba74' };
    case 'knowledge':
    default:
      return { badge: '#22d3ee', border: 'rgba(34, 211, 238, 0.3)', bg: 'rgba(34, 211, 238, 0.1)', text: '#67e8f9' };
  }
}

export const MemoryArchiveOverlay: React.FC<MemoryArchiveOverlayProps> = ({
  memoryArchive,
  commandControl: propCommandControl,
  isReducedMotion = false,
}) => {
  const internalCommandControl = useSpatialCommand(memoryArchive);
  const commandControl = propCommandControl || internalCommandControl;
  const {
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
    canNavigateBack,
    previousMemory,
    filteredMemories,
    relatedMemories,
    timelineContext,
    selectMemory,
    hoverMemory,
    navigateToRelated,
    navigateBack,
    closeInspection,
    setSearchQuery,
    setActiveFilter,
    resetFilters,
  } = memoryArchive;

  const searchInputRef = useRef<HTMLInputElement>(null);

  // Keyboard shortcut '/' to focus search
  useEffect(() => {
    const handleSlash = (e: KeyboardEvent) => {
      if (e.key === '/' && document.activeElement !== searchInputRef.current) {
        e.preventDefault();
        searchInputRef.current?.focus();
      }
    };
    window.addEventListener('keydown', handleSlash);
    return () => window.removeEventListener('keydown', handleSlash);
  }, []);

  return (
    <div
      data-testid="memory-archive-overlay"
      className="memory-archive-overlay-root"
      style={{
        position: 'absolute',
        inset: 0,
        pointerEvents: 'none', // Allow 3D canvas interaction underneath except on UI elements
        zIndex: 40,
        display: 'flex',
        flexDirection: 'column',
        fontFamily: "'JetBrains Mono', 'Fira Code', monospace",
        color: '#cbd5e1',
        overflow: 'hidden',
      }}
    >
      {/* ========================================================
          TOP HEADER: SEARCH & FILTER TELEMETRY BAR
          ======================================================== */}
      <div
        data-testid="memory-top-bar"
        style={{
          pointerEvents: 'auto',
          margin: '1.25rem 1.5rem 0',
          padding: '0.75rem 1rem',
          backgroundColor: 'rgba(7, 10, 18, 0.88)',
          backdropFilter: 'blur(16px)',
          border: '1px solid rgba(56, 189, 248, 0.2)',
          borderRadius: '8px',
          boxShadow: '0 8px 32px rgba(0, 0, 0, 0.7)',
          display: 'flex',
          flexDirection: 'column',
          gap: '0.625rem',
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: '1rem' }}>
          {/* Spatial Archive Header & Status */}
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
            <div
              style={{
                width: '32px',
                height: '32px',
                borderRadius: '6px',
                backgroundColor: 'rgba(56, 189, 248, 0.12)',
                border: '1px solid #38bdf8',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
              }}
            >
              <Database size={16} color="#38bdf8" />
            </div>
            <div>
              <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                <span style={{ fontSize: '0.8125rem', fontWeight: 700, color: '#f8fafc', letterSpacing: '0.08em' }}>
                  STAGE 04 // SPATIAL MEMORY ARCHIVE
                </span>
                <span
                  data-testid="memory-state-indicator"
                  style={{
                    fontSize: '0.625rem',
                    padding: '1px 6px',
                    borderRadius: '3px',
                    backgroundColor: 'rgba(34, 211, 238, 0.15)',
                    color: '#22d3ee',
                    border: '1px solid rgba(34, 211, 238, 0.3)',
                    letterSpacing: '0.06em',
                  }}
                >
                  STATE: {interactionState}
                </span>
              </div>
              <div style={{ fontSize: '0.6875rem', color: '#64748b' }}>
                24 DETERMINISTIC VITRINE RECORDS // GRAPH INDEX ACTIVE
              </div>
            </div>
          </div>

          {/* Search Box */}
          <div
            style={{
              position: 'relative',
              width: '340px',
              display: 'flex',
              alignItems: 'center',
            }}
          >
            <Search
              size={14}
              color="#64748b"
              style={{ position: 'absolute', left: '10px', pointerEvents: 'none' }}
            />
            <input
              ref={searchInputRef}
              data-testid="memory-search-input"
              type="text"
              placeholder="Search title, summary, tags, entities... [/]"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              style={{
                width: '100%',
                backgroundColor: 'rgba(15, 23, 42, 0.85)',
                border: '1px solid rgba(56, 189, 248, 0.25)',
                borderRadius: '6px',
                padding: '6px 28px 6px 30px',
                fontSize: '0.75rem',
                color: '#f8fafc',
                outline: 'none',
                fontFamily: 'inherit',
                transition: 'border-color 0.15s ease',
              }}
              onFocus={(e) => {
                e.currentTarget.style.borderColor = '#38bdf8';
              }}
              onBlur={(e) => {
                e.currentTarget.style.borderColor = 'rgba(56, 189, 248, 0.25)';
              }}
            />
            {searchQuery && (
              <button
                type="button"
                data-testid="memory-search-clear-btn"
                onClick={() => setSearchQuery('')}
                style={{
                  position: 'absolute',
                  right: '8px',
                  background: 'transparent',
                  border: 'none',
                  color: '#64748b',
                  cursor: 'pointer',
                  padding: '2px',
                  display: 'flex',
                  alignItems: 'center',
                }}
                title="Clear search"
              >
                <X size={13} />
              </button>
            )}
          </div>
        </div>

        {/* Filter Pills */}
        <div
          data-testid="memory-filter-bar"
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: '0.375rem',
            flexWrap: 'wrap',
          }}
        >
          {FILTER_PILLS.map((pill) => {
            const isActive = activeFilter === pill.id;
            return (
              <button
                key={pill.id}
                type="button"
                data-testid={`memory-filter-pill-${pill.id.toLowerCase()}`}
                onClick={() => setActiveFilter(pill.id)}
                style={{
                  backgroundColor: isActive ? 'rgba(56, 189, 248, 0.2)' : 'rgba(15, 23, 42, 0.6)',
                  border: isActive ? '1px solid #38bdf8' : '1px solid rgba(255, 255, 255, 0.08)',
                  color: isActive ? '#38bdf8' : '#94a3b8',
                  padding: '3px 9px',
                  borderRadius: '4px',
                  fontSize: '0.625rem',
                  fontWeight: isActive ? 700 : 500,
                  cursor: 'pointer',
                  letterSpacing: '0.06em',
                  fontFamily: 'inherit',
                  transition: 'all 0.15s ease',
                }}
              >
                {pill.label}
              </button>
            );
          })}
          {searchQuery && (
            <span
              style={{
                marginLeft: 'auto',
                fontSize: '0.625rem',
                color: '#38bdf8',
              }}
            >
              MATCHES: {filteredMemories.length} / 24
            </span>
          )}
        </div>
      </div>

      {/* ========================================================
          STAGE 05: SPATIAL COMMAND CONSOLE & TERMINAL
          ======================================================== */}
      <SpatialCommandConsole
        commandControl={commandControl}
        isReducedMotion={isReducedMotion}
      />

      {/* ========================================================
          STAGE 05: ACTION PREVIEW CONFIRMATION MODAL
          ======================================================== */}
      {commandControl.activeProposal && (
        <SpatialActionPreview
          proposal={commandControl.activeProposal}
          executionPlan={commandControl.activeExecutionPlan}
          onConfirm={commandControl.confirmProposal}
          onCancel={commandControl.cancelProposal}
          isReducedMotion={isReducedMotion}
        />
      )}

      {/* ========================================================
          HOVER TELEMETRY BADGE (SHOWN WHEN HOVERING A VITRINE)
          ======================================================== */}
      {hoveredMemoryId && !isDetailOpen && (
        <div
          data-testid="memory-hover-badge"
          style={{
            pointerEvents: 'none',
            position: 'absolute',
            bottom: '120px',
            left: '50%',
            transform: 'translateX(-50%)',
            backgroundColor: 'rgba(7, 10, 18, 0.92)',
            backdropFilter: 'blur(12px)',
            border: '1px solid #38bdf8',
            borderRadius: '6px',
            padding: '0.5rem 1rem',
            display: 'flex',
            alignItems: 'center',
            gap: '0.75rem',
            boxShadow: '0 4px 20px rgba(0, 0, 0, 0.8), 0 0 16px rgba(56, 189, 248, 0.25)',
          }}
        >
          <Compass size={16} color="#38bdf8" />
          <div style={{ display: 'flex', flexDirection: 'column' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
              <span style={{ fontSize: '0.6875rem', fontWeight: 700, color: '#38bdf8' }}>
                [{hoveredVitrineId || 'VITRINE'}]
              </span>
              <span style={{ fontSize: '0.625rem', color: '#64748b' }}>
                ID: {hoveredMemoryId}
              </span>
            </div>
            <span style={{ fontSize: '0.75rem', color: '#f8fafc', fontWeight: 600 }}>
              {filteredMemories.find((m) => m.id === hoveredMemoryId)?.title || 'Memory Record'}
            </span>
          </div>
          <span style={{ fontSize: '0.625rem', color: '#94a3b8', fontStyle: 'italic', marginLeft: '0.5rem' }}>
            CLICK TO INSPECT
          </span>
        </div>
      )}

      {/* ========================================================
          MAIN BODY: CINEMATIC DETAIL INSPECTOR PANEL (LEFT DRAWER)
          ======================================================== */}
      {isDetailOpen && activeMemory && (
        <div
          role="dialog"
          aria-label={`Memory Detail: ${activeMemory.title}`}
          data-testid="memory-detail-panel"
          style={{
            pointerEvents: 'auto',
            position: 'absolute',
            top: '5.2rem',
            bottom: '1.25rem',
            left: '1.5rem',
            width: '440px',
            maxWidth: 'calc(100vw - 3rem)',
            backgroundColor: 'rgba(7, 10, 18, 0.94)',
            backdropFilter: 'blur(24px)',
            border: '1px solid rgba(56, 189, 248, 0.3)',
            borderRadius: '8px',
            boxShadow: '0 12px 48px rgba(0, 0, 0, 0.85), 0 0 24px rgba(56, 189, 248, 0.15)',
            display: 'flex',
            flexDirection: 'column',
            overflow: 'hidden',
          }}
        >
          {/* Detail Panel Header */}
          <div
            style={{
              padding: '0.875rem 1rem',
              borderBottom: '1px solid rgba(255, 255, 255, 0.08)',
              backgroundColor: 'rgba(15, 23, 42, 0.65)',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'space-between',
            }}
          >
            <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
              <span
                style={{
                  fontSize: '0.625rem',
                  fontWeight: 700,
                  color: '#38bdf8',
                  padding: '2px 6px',
                  borderRadius: '3px',
                  backgroundColor: 'rgba(56, 189, 248, 0.15)',
                  border: '1px solid rgba(56, 189, 248, 0.3)',
                }}
              >
                {activeMemory.id}
              </span>
              {activeMapping && (
                <span
                  style={{
                    fontSize: '0.625rem',
                    color: '#94a3b8',
                    letterSpacing: '0.04em',
                  }}
                >
                  SECTOR: {activeMapping.sector} // ARCH: {activeMapping.archetype.toUpperCase()}
                </span>
              )}
            </div>

            <div style={{ display: 'flex', alignItems: 'center', gap: '0.375rem' }}>
              {/* Back button if in navigation stack */}
              {canNavigateBack && (
                <button
                  type="button"
                  data-testid="memory-nav-back"
                  onClick={navigateBack}
                  style={{
                    backgroundColor: 'rgba(34, 211, 238, 0.15)',
                    border: '1px solid rgba(34, 211, 238, 0.3)',
                    color: '#22d3ee',
                    borderRadius: '4px',
                    padding: '3px 7px',
                    fontSize: '0.625rem',
                    cursor: 'pointer',
                    display: 'flex',
                    alignItems: 'center',
                    gap: '0.25rem',
                    fontFamily: 'inherit',
                  }}
                  title="Return to previous memory in stack (Backspace / Left Arrow)"
                >
                  <ArrowLeft size={11} />
                  BACK
                </button>
              )}

              {/* Close Button */}
              <button
                type="button"
                data-testid="memory-close-btn"
                onClick={closeInspection}
                style={{
                  backgroundColor: 'transparent',
                  border: '1px solid rgba(255, 255, 255, 0.1)',
                  color: '#94a3b8',
                  borderRadius: '4px',
                  padding: '3px 6px',
                  cursor: 'pointer',
                  display: 'flex',
                  alignItems: 'center',
                  fontFamily: 'inherit',
                }}
                title="Close Memory Detail (ESC)"
              >
                <X size={14} />
              </button>
            </div>
          </div>

          {/* Scrollable Content Body */}
          <div
            style={{
              flex: 1,
              overflowY: 'auto',
              padding: '1rem',
              display: 'flex',
              flexDirection: 'column',
              gap: '1rem',
            }}
          >
            {/* Title & Importance */}
            <div>
              <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', marginBottom: '0.375rem' }}>
                <span
                  style={{
                    fontSize: '0.5625rem',
                    fontWeight: 700,
                    textTransform: 'uppercase',
                    padding: '1px 5px',
                    borderRadius: '2px',
                    backgroundColor: getTypeColor(activeMemory.type).bg,
                    color: getTypeColor(activeMemory.type).text,
                    border: `1px solid ${getTypeColor(activeMemory.type).border}`,
                  }}
                >
                  {activeMemory.type}
                </span>
                <span style={{ fontSize: '0.625rem', color: '#64748b' }}>
                  VITRINE: {activeMemory.spatialObjectId || 'UNATTACHED'}
                </span>
              </div>

              <h2
                data-testid="memory-title"
                style={{
                  fontSize: '0.9375rem',
                  fontWeight: 700,
                  color: '#f8fafc',
                  margin: 0,
                  lineHeight: 1.35,
                }}
              >
                {activeMemory.title}
              </h2>

              {/* Importance Gauge */}
              <div style={{ marginTop: '0.5rem', display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                <span style={{ fontSize: '0.625rem', color: '#64748b' }}>IMPORTANCE:</span>
                <div
                  style={{
                    flex: 1,
                    height: '4px',
                    backgroundColor: 'rgba(255, 255, 255, 0.08)',
                    borderRadius: '2px',
                    overflow: 'hidden',
                  }}
                >
                  <div
                    style={{
                      height: '100%',
                      width: `${Math.round(activeMemory.importance * 100)}%`,
                      backgroundColor:
                        activeMemory.importance >= 0.95
                          ? '#f59e0b'
                          : activeMemory.importance >= 0.8
                          ? '#38bdf8'
                          : '#64748b',
                    }}
                  />
                </div>
                <span style={{ fontSize: '0.625rem', color: '#94a3b8', fontWeight: 700 }}>
                  {Math.round(activeMemory.importance * 100)}%
                </span>
              </div>
            </div>

            {/* Summary */}
            <div
              style={{
                backgroundColor: 'rgba(15, 23, 42, 0.5)',
                border: '1px solid rgba(255, 255, 255, 0.06)',
                borderRadius: '6px',
                padding: '0.75rem',
              }}
            >
              <span
                style={{
                  fontSize: '0.625rem',
                  fontWeight: 700,
                  color: '#64748b',
                  letterSpacing: '0.06em',
                  display: 'block',
                  marginBottom: '0.375rem',
                }}
              >
                ARCHITECTURAL SUMMARY
              </span>
              <p
                data-testid="memory-summary"
                style={{
                  fontSize: '0.75rem',
                  color: '#cbd5e1',
                  margin: 0,
                  lineHeight: 1.5,
                }}
              >
                {activeMemory.summary}
              </p>
            </div>

            {/* Source & Timestamps */}
            <div
              style={{
                display: 'grid',
                gridTemplateColumns: '1fr 1fr',
                gap: '0.5rem',
                fontSize: '0.625rem',
              }}
            >
              <div
                style={{
                  backgroundColor: 'rgba(15, 23, 42, 0.4)',
                  border: '1px solid rgba(255, 255, 255, 0.05)',
                  borderRadius: '4px',
                  padding: '0.5rem',
                }}
              >
                <div style={{ color: '#64748b', display: 'flex', alignItems: 'center', gap: '0.25rem' }}>
                  <ShieldCheck size={11} color="#64748b" />
                  <span>ORIGIN SOURCE</span>
                </div>
                <div style={{ color: '#94a3b8', marginTop: '2px', fontWeight: 600 }}>
                  {activeMemory.source.type.toUpperCase()} // {activeMemory.source.identifier || 'INTERNAL'}
                </div>
              </div>

              <div
                style={{
                  backgroundColor: 'rgba(15, 23, 42, 0.4)',
                  border: '1px solid rgba(255, 255, 255, 0.05)',
                  borderRadius: '4px',
                  padding: '0.5rem',
                }}
              >
                <div style={{ color: '#64748b', display: 'flex', alignItems: 'center', gap: '0.25rem' }}>
                  <Clock size={11} color="#64748b" />
                  <span>TEMPORAL ANCHOR</span>
                </div>
                <div style={{ color: '#94a3b8', marginTop: '2px', fontWeight: 600 }}>
                  {activeMemory.createdAt
                    ? new Date(activeMemory.createdAt).toISOString().replace('T', ' ').slice(0, 16) + ' UTC'
                    : 'EPOCH ZERO / HISTORICAL'}
                </div>
              </div>
            </div>

            {/* Entities Involved */}
            {activeMemory.entities && activeMemory.entities.length > 0 && (
              <div>
                <span
                  style={{
                    fontSize: '0.625rem',
                    fontWeight: 700,
                    color: '#64748b',
                    letterSpacing: '0.06em',
                    display: 'flex',
                    alignItems: 'center',
                    gap: '0.35rem',
                    marginBottom: '0.375rem',
                  }}
                >
                  <Users size={12} color="#64748b" />
                  ASSOCIATED ENTITIES ({activeMemory.entities.length})
                </span>
                <div style={{ display: 'flex', flexDirection: 'column', gap: '0.25rem' }}>
                  {activeMemory.entities.map((ent) => (
                    <div
                      key={ent.id}
                      style={{
                        backgroundColor: 'rgba(15, 23, 42, 0.4)',
                        border: '1px solid rgba(255, 255, 255, 0.05)',
                        borderRadius: '4px',
                        padding: '4px 8px',
                        display: 'flex',
                        alignItems: 'center',
                        justifyContent: 'space-between',
                        fontSize: '0.6875rem',
                      }}
                    >
                      <div style={{ display: 'flex', alignItems: 'center', gap: '0.375rem' }}>
                        <span
                          style={{
                            fontSize: '0.5625rem',
                            padding: '1px 4px',
                            borderRadius: '2px',
                            backgroundColor: 'rgba(56, 189, 248, 0.1)',
                            color: '#38bdf8',
                            border: '1px solid rgba(56, 189, 248, 0.2)',
                          }}
                        >
                          {ent.type.toUpperCase()}
                        </span>
                        <span style={{ color: '#e2e8f0', fontWeight: 600 }}>{ent.name}</span>
                      </div>
                      {ent.role && (
                        <span style={{ fontSize: '0.625rem', color: '#64748b' }}>{ent.role}</span>
                      )}
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* Tags */}
            {activeMemory.tags && activeMemory.tags.length > 0 && (
              <div>
                <span
                  style={{
                    fontSize: '0.625rem',
                    fontWeight: 700,
                    color: '#64748b',
                    letterSpacing: '0.06em',
                    display: 'flex',
                    alignItems: 'center',
                    gap: '0.35rem',
                    marginBottom: '0.375rem',
                  }}
                >
                  <Tag size={12} color="#64748b" />
                  SEMANTIC TAGS
                </span>
                <div style={{ display: 'flex', flexWrap: 'wrap', gap: '0.35rem' }}>
                  {activeMemory.tags.map((tag) => (
                    <span
                      key={tag}
                      style={{
                        fontSize: '0.625rem',
                        backgroundColor: 'rgba(30, 41, 59, 0.7)',
                        border: '1px solid rgba(255, 255, 255, 0.08)',
                        borderRadius: '3px',
                        padding: '2px 6px',
                        color: '#94a3b8',
                      }}
                    >
                      #{tag}
                    </span>
                  ))}
                </div>
              </div>
            )}

            {/* Related Memories Graph */}
            <div>
              <span
                style={{
                  fontSize: '0.625rem',
                  fontWeight: 700,
                  color: '#64748b',
                  letterSpacing: '0.06em',
                  display: 'flex',
                  alignItems: 'center',
                  gap: '0.35rem',
                  marginBottom: '0.375rem',
                }}
              >
                <Compass size={12} color="#64748b" />
                ASSOCIATED MEMORY GRAPH ({relatedMemories.length})
              </span>

              {relatedMemories.length === 0 ? (
                <div
                  style={{
                    fontSize: '0.6875rem',
                    color: '#64748b',
                    fontStyle: 'italic',
                    padding: '0.5rem',
                    backgroundColor: 'rgba(15, 23, 42, 0.3)',
                    borderRadius: '4px',
                  }}
                >
                  NO DIRECT MEMORY EDGES REGISTERED
                </div>
              ) : (
                <div style={{ display: 'flex', flexDirection: 'column', gap: '0.375rem' }}>
                  {relatedMemories.map(({ memory: relMem, relationship }) => (
                    <button
                      key={relMem.id}
                      type="button"
                      data-testid={`memory-related-item-${relMem.id}`}
                      onClick={() => navigateToRelated(relMem.id)}
                      style={{
                        backgroundColor: 'rgba(15, 23, 42, 0.55)',
                        border: '1px solid rgba(56, 189, 248, 0.2)',
                        borderRadius: '4px',
                        padding: '6px 8px',
                        textAlign: 'left',
                        cursor: 'pointer',
                        display: 'flex',
                        flexDirection: 'column',
                        gap: '2px',
                        fontFamily: 'inherit',
                        transition: 'all 0.15s ease',
                      }}
                      onMouseEnter={(e) => {
                        e.currentTarget.style.borderColor = '#38bdf8';
                        e.currentTarget.style.backgroundColor = 'rgba(56, 189, 248, 0.1)';
                      }}
                      onMouseLeave={(e) => {
                        e.currentTarget.style.borderColor = 'rgba(56, 189, 248, 0.2)';
                        e.currentTarget.style.backgroundColor = 'rgba(15, 23, 42, 0.55)';
                      }}
                    >
                      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                        <span style={{ fontSize: '0.5625rem', color: '#38bdf8', fontWeight: 700 }}>
                          [{relationship.relationshipType.toUpperCase()}] {relationship.label}
                        </span>
                        <ChevronRight size={11} color="#38bdf8" />
                      </div>
                      <span style={{ fontSize: '0.6875rem', color: '#e2e8f0', fontWeight: 600 }}>
                        {relMem.title}
                      </span>
                    </button>
                  ))}
                </div>
              )}
            </div>

            {/* Timeline Bar (Predecessor, Sequence Index, Successor) */}
            <div
              style={{
                backgroundColor: 'rgba(15, 23, 42, 0.65)',
                border: '1px solid rgba(56, 189, 248, 0.25)',
                borderRadius: '6px',
                padding: '0.625rem',
              }}
            >
              <div
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'space-between',
                  marginBottom: '0.5rem',
                }}
              >
                <span style={{ fontSize: '0.625rem', fontWeight: 700, color: '#38bdf8' }}>
                  TEMPORAL CONTINUITY
                </span>
                <span style={{ fontSize: '0.5625rem', color: '#64748b' }}>
                  {timelineContext?.hasTimestamp
                    ? `ORDER: ${timelineContext.chronologicalIndex} / ${timelineContext.totalInSequence}`
                    : 'TIMELINE DATA UNAVAILABLE'}
                </span>
              </div>

              <div style={{ display: 'flex', gap: '0.5rem' }}>
                {/* Predecessor */}
                <button
                  type="button"
                  data-testid="memory-timeline-prev"
                  disabled={!timelineContext?.predecessor}
                  onClick={() => {
                    if (timelineContext?.predecessor) {
                      navigateToRelated(timelineContext.predecessor.id);
                    }
                  }}
                  style={{
                    flex: 1,
                    backgroundColor: timelineContext?.predecessor
                      ? 'rgba(30, 41, 59, 0.6)'
                      : 'rgba(15, 23, 42, 0.2)',
                    border: timelineContext?.predecessor
                      ? '1px solid rgba(255, 255, 255, 0.1)'
                      : '1px solid rgba(255, 255, 255, 0.03)',
                    color: timelineContext?.predecessor ? '#cbd5e1' : '#475569',
                    borderRadius: '4px',
                    padding: '4px 6px',
                    fontSize: '0.5625rem',
                    cursor: timelineContext?.predecessor ? 'pointer' : 'not-allowed',
                    textAlign: 'left',
                    fontFamily: 'inherit',
                  }}
                >
                  <div style={{ display: 'flex', alignItems: 'center', gap: '2px', color: '#94a3b8' }}>
                    <ArrowLeft size={10} />
                    <span>PREDECESSOR</span>
                  </div>
                  <div
                    style={{
                      marginTop: '2px',
                      overflow: 'hidden',
                      textOverflow: 'ellipsis',
                      whiteSpace: 'nowrap',
                    }}
                  >
                    {timelineContext?.predecessor?.title || 'None (Genesis)'}
                  </div>
                </button>

                {/* Successor */}
                <button
                  type="button"
                  data-testid="memory-timeline-next"
                  disabled={!timelineContext?.successor}
                  onClick={() => {
                    if (timelineContext?.successor) {
                      navigateToRelated(timelineContext.successor.id);
                    }
                  }}
                  style={{
                    flex: 1,
                    backgroundColor: timelineContext?.successor
                      ? 'rgba(30, 41, 59, 0.6)'
                      : 'rgba(15, 23, 42, 0.2)',
                    border: timelineContext?.successor
                      ? '1px solid rgba(255, 255, 255, 0.1)'
                      : '1px solid rgba(255, 255, 255, 0.03)',
                    color: timelineContext?.successor ? '#cbd5e1' : '#475569',
                    borderRadius: '4px',
                    padding: '4px 6px',
                    fontSize: '0.5625rem',
                    cursor: timelineContext?.successor ? 'pointer' : 'not-allowed',
                    textAlign: 'right',
                    fontFamily: 'inherit',
                  }}
                >
                  <div
                    style={{
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'flex-end',
                      gap: '2px',
                      color: '#94a3b8',
                    }}
                  >
                    <span>SUCCESSOR</span>
                    <ArrowRight size={10} />
                  </div>
                  <div
                    style={{
                      marginTop: '2px',
                      overflow: 'hidden',
                      textOverflow: 'ellipsis',
                      whiteSpace: 'nowrap',
                    }}
                  >
                    {timelineContext?.successor?.title || 'None (Terminus)'}
                  </div>
                </button>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* ========================================================
          BOTTOM STRIP: ACCESSIBLE VITRINE MEMORY GRID DRAWER
          (Permits exploration without requiring 3D canvas raycasting)
          ======================================================== */}
      <div
        data-testid="memory-bottom-drawer"
        style={{
          pointerEvents: 'auto',
          marginTop: 'auto',
          margin: '0 1.5rem 1.25rem',
          padding: '0.625rem 0.875rem',
          backgroundColor: 'rgba(7, 10, 18, 0.9)',
          backdropFilter: 'blur(16px)',
          border: '1px solid rgba(56, 189, 248, 0.2)',
          borderRadius: '8px',
          boxShadow: '0 8px 32px rgba(0, 0, 0, 0.8)',
          display: 'flex',
          flexDirection: 'column',
          gap: '0.5rem',
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
          <span style={{ fontSize: '0.6875rem', fontWeight: 700, color: '#38bdf8', letterSpacing: '0.06em' }}>
            SPATIAL VITRINE REGISTRY // [{filteredMemories.length} RECORDS DISPLAYED]
          </span>
          <span style={{ fontSize: '0.5625rem', color: '#64748b' }}>
            CLICK TO FOCUS // HOVER TO HIGHLIGHT IN 3D
          </span>
        </div>

        {/* Horizontal scroll strip */}
        <div
          data-testid="memory-cards-container"
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: '0.5rem',
            overflowX: 'auto',
            paddingBottom: '0.25rem',
          }}
        >
          {filteredMemories.length === 0 ? (
            <div
              data-testid="memory-empty-state"
              style={{
                padding: '0.75rem',
                fontSize: '0.6875rem',
                color: '#64748b',
                fontStyle: 'italic',
                width: '100%',
                textAlign: 'center',
              }}
            >
              NO MATCHING MEMORIES ARCHIVED IN CURRENT SECTOR FILTER
              <button
                type="button"
                onClick={resetFilters}
                style={{
                  marginLeft: '0.5rem',
                  backgroundColor: 'transparent',
                  border: 'none',
                  color: '#38bdf8',
                  textDecoration: 'underline',
                  cursor: 'pointer',
                  fontFamily: 'inherit',
                  fontSize: 'inherit',
                }}
              >
                Reset Search
              </button>
            </div>
          ) : (
            filteredMemories.map((mem) => {
              const isSelected = selectedMemoryId === mem.id;
              const isHovered = hoveredMemoryId === mem.id;
              const isHighlighted = commandControl.highlightedVitrineIds && mem.spatialObjectId
                ? commandControl.highlightedVitrineIds.includes(mem.spatialObjectId)
                : false;
              const hasHighlights = commandControl.highlightedVitrineIds.length > 0;
              const opacity = hasHighlights && !isHighlighted && !isSelected ? 0.4 : 1.0;
              const typeCfg = getTypeColor(mem.type);

              return (
                <button
                  key={mem.id}
                  type="button"
                  data-testid={`memory-card-${mem.id}`}
                  onClick={() => selectMemory(isSelected ? null : mem.id)}
                  onMouseEnter={() => hoverMemory(mem.id)}
                  onMouseLeave={() => hoverMemory(null)}
                  style={{
                    opacity,
                    backgroundColor: isSelected
                      ? 'rgba(56, 189, 248, 0.15)'
                      : isHighlighted
                      ? 'rgba(245, 158, 11, 0.15)'
                      : isHovered
                      ? 'rgba(30, 41, 59, 0.8)'
                      : 'rgba(15, 23, 42, 0.65)',
                    border: isSelected
                      ? '1px solid #38bdf8'
                      : isHighlighted
                      ? '1px solid #f59e0b'
                      : isHovered
                      ? '1px solid rgba(56, 189, 248, 0.4)'
                      : '1px solid rgba(255, 255, 255, 0.08)',
                    borderRadius: '6px',
                    padding: '6px 8px',
                    width: '160px',
                    minWidth: '160px',
                    textAlign: 'left',
                    cursor: 'pointer',
                    display: 'flex',
                    flexDirection: 'column',
                    gap: '3px',
                    fontFamily: 'inherit',
                    transition: 'all 0.15s ease',
                    boxShadow: isSelected
                      ? '0 0 12px rgba(56, 189, 248, 0.25)'
                      : isHighlighted
                      ? '0 0 12px rgba(245, 158, 11, 0.3)'
                      : 'none',
                  }}
                >
                  <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                    <span
                      style={{
                        fontSize: '0.5rem',
                        fontWeight: 700,
                        color: typeCfg.text,
                        backgroundColor: typeCfg.bg,
                        padding: '1px 3px',
                        borderRadius: '2px',
                        textTransform: 'uppercase',
                      }}
                    >
                      {mem.type}
                    </span>
                    <span style={{ fontSize: '0.5rem', color: '#64748b' }}>
                      {mem.id}
                    </span>
                  </div>

                  <span
                    style={{
                      fontSize: '0.625rem',
                      fontWeight: 600,
                      color: isSelected ? '#38bdf8' : '#f1f5f9',
                      overflow: 'hidden',
                      textOverflow: 'ellipsis',
                      whiteSpace: 'nowrap',
                    }}
                  >
                    {mem.title}
                  </span>

                  <span
                    style={{
                      fontSize: '0.5rem',
                      color: '#64748b',
                      overflow: 'hidden',
                      textOverflow: 'ellipsis',
                      whiteSpace: 'nowrap',
                    }}
                  >
                    {mem.spatialObjectId || 'Vitrine'}
                  </span>
                </button>
              );
            })
          )}
        </div>
      </div>
    </div>
  );
};
