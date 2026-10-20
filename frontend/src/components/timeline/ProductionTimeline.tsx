import React, { useState } from 'react';
import {
  Film,
  Plus,
  ArrowLeft,
  ArrowRight,
  Info,
  Copy,
  Layers,
  CheckCircle2,
  AlertTriangle,
  AlertCircle,
  Clock,
  Sparkles,
  Link as LinkIcon,
  Trash2,
  Files,
  FileCode,
  X,
} from 'lucide-react';
import { Project, Sequence, Shot, ProjectRecoveryState, PersistedProjectEnvelope } from '../../types/productionTimeline';
import { ShotDetailInspector } from './ShotDetailInspector';
import { ProjectRecoveryBar } from './ProjectRecoveryBar';
import { CapabilitiesManifest } from '../../types/creator';
import { generateSequenceExecutionPlan } from '../../utils/continuityEngine';

interface ProductionTimelineProps {
  project: Project;
  activeShotId?: string;
  onSelectShot: (shot: Shot) => void;
  onReproduceShot: (shot: Shot) => void;
  onReorderShots: (sourceIndex: number, targetIndex: number) => void;
  onAddShot: () => void;
  onDuplicateShot?: (shot: Shot) => void;
  onRemoveShot?: (shotId: string) => void;
  onLinkPredecessor: (targetShotId: string, sourceShotId: string) => void;
  manifest: CapabilitiesManifest | null;
  recoveryState?: ProjectRecoveryState;
  envelope?: PersistedProjectEnvelope | null;
  onRestoreProject?: () => void;
  onDiscardProject?: () => void;
  onReviewInterruptedShots?: () => void;
  onDismissRecovery?: () => void;
}

export const ProductionTimeline: React.FC<ProductionTimelineProps> = ({
  project,
  activeShotId,
  onSelectShot,
  onReproduceShot,
  onReorderShots,
  onAddShot,
  onDuplicateShot,
  onRemoveShot,
  onLinkPredecessor,
  manifest,
  recoveryState,
  envelope,
  onRestoreProject,
  onDiscardProject,
  onReviewInterruptedShots,
  onDismissRecovery,
}) => {
  const [inspectingShot, setInspectingShot] = useState<Shot | null>(null);
  const [showExecutionPlan, setShowExecutionPlan] = useState<boolean>(false);

  const activeSequence: Sequence | undefined =
    project.sequences.find((s) => s.id === project.activeSequenceId) ||
    project.sequences[0];

  const shots = activeSequence?.shots || [];

  const getStatusBadgeStyle = (status: string) => {
    switch (status) {
      case 'READY':
      case 'COMPLETE':
        return {
          backgroundColor: 'rgba(56, 189, 248, 0.12)',
          border: '1px solid rgba(56, 189, 248, 0.4)',
          color: '#38bdf8',
        };
      case 'WARNING':
      case 'PARTIALLY_READY':
        return {
          backgroundColor: 'rgba(245, 158, 11, 0.12)',
          border: '1px solid rgba(245, 158, 11, 0.4)',
          color: '#fbbf24',
        };
      case 'BLOCKED':
      case 'FAILED':
        return {
          backgroundColor: 'rgba(245, 158, 11, 0.12)',
          border: '1px solid rgba(245, 158, 11, 0.4)',
          color: '#fbbf24',
        };
      case 'IN_PROGRESS':
      case 'GENERATING':
        return {
          backgroundColor: 'rgba(168, 85, 247, 0.15)',
          border: '1px solid rgba(168, 85, 247, 0.4)',
          color: '#c084fc',
        };
      default:
        return {
          backgroundColor: 'rgba(255, 255, 255, 0.05)',
          border: '1px solid rgba(255, 255, 255, 0.1)',
          color: 'var(--text-muted)',
        };
    }
  };

  const executionPlan = activeSequence ? generateSequenceExecutionPlan(activeSequence) : null;

  return (
    <section
      aria-label="Multi-Shot Production Timeline"
      className="production-timeline-section"
      data-testid="production-timeline"
      style={{
        maxWidth: '1600px',
        margin: '1.25rem auto 1rem',
        padding: '0 1.5rem',
        width: '100%',
        boxSizing: 'border-box',
      }}
    >
      <div
        style={{
          background: 'linear-gradient(180deg, rgba(17, 24, 39, 0.95) 0%, rgba(10, 14, 22, 0.98) 100%)',
          border: '1px solid rgba(59, 130, 246, 0.22)',
          borderRadius: 'var(--radius-md, 8px)',
          padding: '1rem',
          boxShadow: '0 8px 32px rgba(0, 0, 0, 0.5), inset 0 1px 0 rgba(255, 255, 255, 0.05)',
          display: 'flex',
          flexDirection: 'column',
          gap: '0.875rem',
        }}
      >
        {/* Stage 11: Project Recovery & Persistence Surface */}
        {recoveryState && (
          <ProjectRecoveryBar
            recoveryState={recoveryState}
            envelope={envelope || null}
            onRestore={onRestoreProject || (() => {})}
            onDiscard={onDiscardProject || (() => {})}
            onReviewShots={onReviewInterruptedShots}
            onDismiss={onDismissRecovery}
          />
        )}

        {/* 1. Timeline Header: Sequence Selector, Readiness Badge & Telemetry */}
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            flexWrap: 'wrap',
            gap: '0.75rem',
            borderBottom: '1px solid rgba(255, 255, 255, 0.06)',
            paddingBottom: '0.75rem',
          }}
        >
          {/* Title & Sequence Label */}
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px', flexWrap: 'wrap' }}>
            <Film size={15} style={{ color: 'var(--primary-glow, #38bdf8)' }} />
            <span
              style={{
                fontFamily: 'var(--font-mono, monospace)',
                fontWeight: 700,
                fontSize: '0.71875rem',
                letterSpacing: '0.06em',
                color: 'var(--text-primary)',
              }}
            >
              06 // MULTI-SHOT TIMELINE & STORY CONTINUITY
            </span>

            {activeSequence && (
              <span
                style={{
                  fontSize: '0.6875rem',
                  color: 'var(--text-muted)',
                  borderLeft: '1px solid rgba(255, 255, 255, 0.15)',
                  paddingLeft: '8px',
                }}
              >
                {activeSequence.title}
              </span>
            )}
          </div>

          {/* Sequence Status & Telemetry Metrics */}
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem', flexWrap: 'wrap' }}>
            {activeSequence && (
              <span
                data-testid="sequence-status-badge"
                style={{
                  display: 'inline-flex',
                  alignItems: 'center',
                  gap: '5px',
                  padding: '3px 10px',
                  borderRadius: '4px',
                  fontSize: '0.6875rem',
                  fontWeight: 700,
                  letterSpacing: '0.04em',
                  fontFamily: 'var(--font-mono, monospace)',
                  ...getStatusBadgeStyle(activeSequence.status),
                }}
              >
                SEQUENCE // {activeSequence.status}
              </span>
            )}

            {/* Sequence Metrics Strip */}
            {activeSequence && (
              <div
                data-testid="sequence-metrics-strip"
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: '0.75rem',
                  fontSize: '0.6875rem',
                  fontFamily: 'var(--font-mono, monospace)',
                  color: 'var(--text-secondary)',
                  backgroundColor: 'rgba(0, 0, 0, 0.3)',
                  padding: '3px 8px',
                  borderRadius: '4px',
                  border: '1px solid rgba(255, 255, 255, 0.04)',
                }}
              >
                <div>
                  <span style={{ color: 'var(--text-muted)' }}>SHOTS: </span>
                  <strong data-testid="seq-metric-total">{activeSequence.totalShots}</strong>
                </div>
                <div>
                  <span style={{ color: 'var(--text-muted)' }}>READY: </span>
                  <strong style={{ color: '#38bdf8' }} data-testid="seq-metric-ready">
                    {activeSequence.readyShots}
                  </strong>
                </div>
                <div>
                  <span style={{ color: 'var(--text-muted)' }}>BLOCKED: </span>
                  <strong style={{ color: activeSequence.blockedShots > 0 ? '#fbbf24' : undefined }} data-testid="seq-metric-blocked">
                    {activeSequence.blockedShots}
                  </strong>
                </div>
                <div>
                  <span style={{ color: 'var(--text-muted)' }}>IN-FLIGHT: </span>
                  <strong style={{ color: activeSequence.inFlightShots > 0 ? '#c084fc' : undefined }} data-testid="seq-metric-inflight">
                    {activeSequence.inFlightShots}
                  </strong>
                </div>
                <div>
                  <span style={{ color: 'var(--text-muted)' }}>COMPLETE: </span>
                  <strong style={{ color: '#34d399' }} data-testid="seq-metric-complete">
                    {activeSequence.completeShots}
                  </strong>
                </div>
              </div>
            )}

            {/* Sequence Execution Plan Button (Section 18) */}
            <button
              data-testid="sequence-execution-plan-btn"
              onClick={() => setShowExecutionPlan(true)}
              style={{
                display: 'inline-flex',
                alignItems: 'center',
                gap: '4px',
                padding: '4px 10px',
                backgroundColor: 'rgba(255, 255, 255, 0.06)',
                border: '1px solid rgba(255, 255, 255, 0.15)',
                borderRadius: '4px',
                color: 'var(--text-secondary)',
                fontSize: '0.6875rem',
                fontWeight: 600,
                cursor: 'pointer',
                letterSpacing: '0.04em',
              }}
              title="View Read-Only Sequence Execution Plan"
            >
              <FileCode size={12} />
              <span>EXECUTION PLAN</span>
            </button>

            {/* Add Shot Button */}
            <button
              data-testid="add-shot-btn"
              onClick={onAddShot}
              style={{
                display: 'inline-flex',
                alignItems: 'center',
                gap: '4px',
                padding: '4px 10px',
                backgroundColor: 'rgba(56, 189, 248, 0.12)',
                border: '1px solid rgba(56, 189, 248, 0.35)',
                borderRadius: '4px',
                color: '#38bdf8',
                fontSize: '0.6875rem',
                fontWeight: 600,
                cursor: 'pointer',
                letterSpacing: '0.04em',
              }}
            >
              <Plus size={12} />
              <span>NEW SHOT</span>
            </button>
          </div>
        </div>

        {/* 2. Sequence Blocked Explanations (Strict Non-Hallucinatory Reasons) */}
        {activeSequence && activeSequence.status === 'BLOCKED' && activeSequence.statusReasons.length > 0 && (
          <div
            data-testid="sequence-blocked-reasons"
            style={{
              padding: '0.5rem 0.75rem',
              backgroundColor: 'rgba(245, 158, 11, 0.08)',
              borderLeft: '3px solid #fbbf24',
              borderRadius: '0 4px 4px 0',
              color: '#fde68a',
              fontSize: '0.6875rem',
              lineHeight: 1.4,
            }}
          >
            <div style={{ fontWeight: 700, marginBottom: '2px', letterSpacing: '0.04em' }}>
              SEQUENCE BLOCKED // CONTINUITY & DEPENDENCY DIRECTIVES:
            </div>
            <ul style={{ margin: 0, paddingLeft: '1.25rem' }}>
              {activeSequence.statusReasons.map((r, i) => (
                <li key={i}>{r}</li>
              ))}
            </ul>
          </div>
        )}

        {/* 3. Empty Sequence State */}
        {shots.length === 0 && (
          <div
            data-testid="empty-sequence-message"
            style={{
              padding: '2rem 1rem',
              textAlign: 'center',
              color: 'var(--text-muted)',
              fontSize: '0.75rem',
              fontStyle: 'italic',
            }}
          >
            No shots in sequence. Click "NEW SHOT" to begin multi-shot planning.
          </div>
        )}

        {/* 4. Horizontal Shot Track */}
        {shots.length > 0 && (
          <div
            data-testid="timeline-shot-track"
            style={{
              display: 'grid',
              gridTemplateColumns: 'repeat(auto-fill, minmax(280px, 1fr))',
              gap: '0.875rem',
              alignItems: 'stretch',
            }}
          >
            {shots.map((shot, index) => {
              const isSelected = shot.id === activeShotId;
              const isBlocked = shot.status === 'BLOCKED' || shot.readiness === 'BLOCKED';
              const isReady = shot.status === 'READY' || shot.readiness === 'READY';
              const isComplete = shot.status === 'COMPLETE';
              const isGenerating = shot.status === 'GENERATING';

              const cardBorder = isSelected
                ? 'rgba(56, 189, 248, 0.85)'
                : isBlocked
                ? 'rgba(245, 158, 11, 0.35)'
                : 'rgba(255, 255, 255, 0.08)';

              const cardBg = isSelected
                ? 'linear-gradient(180deg, rgba(20, 30, 48, 0.95) 0%, rgba(13, 20, 32, 0.98) 100%)'
                : 'rgba(0, 0, 0, 0.3)';

              return (
                <div
                  key={shot.id}
                  data-testid="timeline-shot-card"
                  data-testid-shot={shot.id}
                  id={`timeline-shot-card-${shot.id}`}
                  onClick={() => onSelectShot(shot)}
                  style={{
                    backgroundColor: 'rgba(15, 23, 42, 0.65)',
                    background: cardBg,
                    border: `1px solid ${cardBorder}`,
                    borderRadius: '6px',
                    padding: '0.75rem',
                    display: 'flex',
                    flexDirection: 'column',
                    justifyContent: 'space-between',
                    gap: '0.625rem',
                    cursor: 'pointer',
                    transition: 'border-color 0.15s ease, transform 0.15s ease',
                    position: 'relative',
                    boxShadow: isSelected ? '0 0 16px rgba(56, 189, 248, 0.25)' : undefined,
                  }}
                >
                  {/* Card Header: Order, Mode & Readiness */}
                  <div
                    data-testid={`timeline-shot-card-${shot.id}`}
                    style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: '6px' }}
                  >
                    <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                      <span
                        data-testid="shot-order-label"
                        style={{
                          fontFamily: 'var(--font-mono, monospace)',
                          fontWeight: 700,
                          fontSize: '0.6875rem',
                          color: isSelected ? '#38bdf8' : 'var(--text-muted)',
                        }}
                      >
                        SHOT {String(shot.order).padStart(2, '0')}
                      </span>
                      <span
                        style={{
                          fontSize: '0.5625rem',
                          fontFamily: 'var(--font-mono, monospace)',
                          backgroundColor: 'rgba(255, 255, 255, 0.06)',
                          padding: '1px 5px',
                          borderRadius: '3px',
                          color: 'var(--text-muted)',
                          textTransform: 'uppercase',
                        }}
                      >
                        {shot.generationType.replace('_', ' ')}
                      </span>
                    </div>

                    <span
                      data-testid="shot-readiness-badge"
                      style={{
                        fontSize: '0.625rem',
                        fontWeight: 700,
                        fontFamily: 'var(--font-mono, monospace)',
                        padding: '1px 6px',
                        borderRadius: '3px',
                        ...getStatusBadgeStyle(shot.status),
                      }}
                    >
                      {`STATE // ${shot.status}`}
                    </span>
                  </div>

                  {/* Title & Prompt Preview */}
                  <div>
                    <strong
                      style={{
                        display: 'block',
                        fontSize: '0.75rem',
                        color: 'var(--text-primary)',
                        marginBottom: '3px',
                        whiteSpace: 'nowrap',
                        overflow: 'hidden',
                        textOverflow: 'ellipsis',
                      }}
                    >
                      {shot.title}
                    </strong>
                    <div
                      style={{
                        fontSize: '0.6875rem',
                        color: 'var(--text-muted)',
                        display: '-webkit-box',
                        WebkitLineClamp: 2,
                        WebkitBoxOrient: 'vertical',
                        overflow: 'hidden',
                        lineHeight: 1.3,
                      }}
                    >
                      {shot.prompt}
                    </div>
                  </div>

                  {/* Parameters & Continuity Indicators */}
                  <div
                    style={{
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'space-between',
                      flexWrap: 'wrap',
                      gap: '4px',
                      fontSize: '0.625rem',
                      color: 'var(--text-muted)',
                      borderTop: '1px solid rgba(255, 255, 255, 0.04)',
                      paddingTop: '0.375rem',
                    }}
                  >
                    <span>{shot.aspectRatio}</span>
                    {shot.duration && <span>{shot.duration}s</span>}
                    {shot.dependencyShotIds.length > 0 && (
                      <span
                        data-testid="shot-dependency-badge"
                        style={{
                          color: '#93c5fd',
                          backgroundColor: 'rgba(59, 130, 246, 0.1)',
                          padding: '1px 4px',
                          borderRadius: '2px',
                        }}
                      >
                        DEP: {shot.dependencyShotIds[0]}
                      </span>
                    )}
                    {shot.continuityReport?.character?.status === 'WARNING' && (
                      <span style={{ color: '#fbbf24' }} title="Character continuity warning">
                        CHAR: WARN
                      </span>
                    )}
                  </div>

                  {/* Card Actions: Reorder, Duplicate, Remove, Reproduce, Inspect */}
                  <div
                    style={{
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'space-between',
                      gap: '4px',
                      borderTop: '1px solid rgba(255, 255, 255, 0.04)',
                      paddingTop: '0.375rem',
                    }}
                    onClick={(e) => e.stopPropagation()}
                  >
                    {/* Reorder Arrows */}
                    <div style={{ display: 'flex', alignItems: 'center', gap: '3px' }}>
                      <button
                        data-testid={`shot-move-left-${shot.id}`}
                        disabled={index === 0}
                        onClick={() => onReorderShots(index, index - 1)}
                        style={{
                          background: 'none',
                          border: 'none',
                          color: index === 0 ? 'rgba(255, 255, 255, 0.1)' : 'var(--text-muted)',
                          cursor: index === 0 ? 'not-allowed' : 'pointer',
                          padding: '2px',
                        }}
                        title="Move Shot Left"
                      >
                        <ArrowLeft size={13} />
                      </button>
                      <button
                        data-testid={`shot-move-right-${shot.id}`}
                        disabled={index === shots.length - 1}
                        onClick={() => onReorderShots(index, index + 1)}
                        style={{
                          background: 'none',
                          border: 'none',
                          color: index === shots.length - 1 ? 'rgba(255, 255, 255, 0.1)' : 'var(--text-muted)',
                          cursor: index === shots.length - 1 ? 'not-allowed' : 'pointer',
                          padding: '2px',
                        }}
                        title="Move Shot Right"
                      >
                        <ArrowRight size={13} />
                      </button>
                    </div>

                    {/* Operational Actions */}
                    <div style={{ display: 'flex', alignItems: 'center', gap: '4px' }}>
                      {/* Duplicate Shot */}
                      {onDuplicateShot && (
                        <button
                          data-testid={`shot-duplicate-btn-${shot.id}`}
                          onClick={() => onDuplicateShot(shot)}
                          style={{
                            background: 'none',
                            border: 'none',
                            color: 'var(--text-muted)',
                            cursor: 'pointer',
                            padding: '2px',
                            display: 'flex',
                            alignItems: 'center',
                          }}
                          title="Duplicate Shot"
                        >
                          <Files size={11} />
                        </button>
                      )}

                      {/* Remove Shot */}
                      {onRemoveShot && (
                        <button
                          data-testid={`shot-remove-btn-${shot.id}`}
                          onClick={() => onRemoveShot(shot.id)}
                          style={{
                            background: 'none',
                            border: 'none',
                            color: 'rgba(239, 68, 68, 0.7)',
                            cursor: 'pointer',
                            padding: '2px',
                            display: 'flex',
                            alignItems: 'center',
                          }}
                          title="Remove Shot"
                        >
                          <Trash2 size={11} />
                        </button>
                      )}

                      {/* Quick Reproduce */}
                      <button
                        data-testid={`shot-quick-reproduce-${shot.id}`}
                        onClick={() => onReproduceShot(shot)}
                        style={{
                          background: 'none',
                          border: 'none',
                          color: 'var(--text-muted)',
                          cursor: 'pointer',
                          padding: '2px 4px',
                          display: 'flex',
                          alignItems: 'center',
                          gap: '3px',
                          fontSize: '0.625rem',
                        }}
                        title="Reproduce Parameters to Console"
                      >
                        <Copy size={11} />
                        <span>REPRODUCE</span>
                      </button>

                      {/* Inspect Detail */}
                      <button
                        data-testid={`shot-inspect-btn-${shot.id}`}
                        onClick={() => setInspectingShot(shot)}
                        style={{
                          background: 'none',
                          border: '1px solid rgba(255, 255, 255, 0.1)',
                          borderRadius: '3px',
                          color: 'var(--text-secondary)',
                          cursor: 'pointer',
                          padding: '2px 6px',
                          display: 'flex',
                          alignItems: 'center',
                          gap: '3px',
                          fontSize: '0.625rem',
                        }}
                        title="Inspect Continuity & Preflight Details"
                      >
                        <Info size={11} />
                        <span>INSPECT</span>
                      </button>
                    </div>
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </div>

      {/* Shot Detail Inspector Modal */}
      {inspectingShot && (
        <ShotDetailInspector
          shot={inspectingShot}
          onClose={() => setInspectingShot(null)}
          onReproduce={onReproduceShot}
          onSelect={onSelectShot}
        />
      )}

      {/* Sequence Execution Plan Modal (Section 18) */}
      {showExecutionPlan && executionPlan && (
        <div
          data-testid="sequence-execution-plan-modal"
          style={{
            position: 'fixed',
            inset: 0,
            backgroundColor: 'rgba(0, 0, 0, 0.75)',
            backdropFilter: 'blur(8px)',
            WebkitBackdropFilter: 'blur(8px)',
            zIndex: 50,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            padding: '1.5rem',
          }}
          onClick={(e) => {
            if (e.target === e.currentTarget) setShowExecutionPlan(false);
          }}
        >
          <div
            style={{
              width: '100%',
              maxWidth: '780px',
              maxHeight: '90vh',
              overflowY: 'auto',
              backgroundColor: 'rgba(11, 16, 26, 0.98)',
              border: '1px solid rgba(59, 130, 246, 0.3)',
              borderRadius: 'var(--radius-md, 8px)',
              padding: '1.25rem',
              boxShadow: '0 20px 40px rgba(0, 0, 0, 0.8)',
              display: 'flex',
              flexDirection: 'column',
              gap: '1rem',
            }}
          >
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', borderBottom: '1px solid rgba(255, 255, 255, 0.08)', paddingBottom: '0.75rem' }}>
              <div>
                <strong style={{ color: 'var(--text-primary)', fontSize: '0.875rem' }}>
                  SEQUENCE EXECUTION PLAN // READ-ONLY PREVIEW
                </strong>
                <div style={{ fontSize: '0.6875rem', color: 'var(--text-muted)' }}>
                  {executionPlan.sequenceTitle} · {executionPlan.totalShots} shots · {executionPlan.totalDuration}s planned
                </div>
              </div>
              <button
                data-testid="close-execution-plan-btn"
                onClick={() => setShowExecutionPlan(false)}
                style={{
                  background: 'none',
                  border: 'none',
                  color: 'var(--text-muted)',
                  cursor: 'pointer',
                  padding: '4px',
                }}
              >
                <X size={16} />
              </button>
            </div>

            <div style={{ display: 'flex', flexDirection: 'column', gap: '0.75rem' }}>
              {executionPlan.shots.map((item) => (
                <div
                  key={item.shotId}
                  data-testid={`execution-plan-item-${item.shotId}`}
                  style={{
                    backgroundColor: 'rgba(0, 0, 0, 0.35)',
                    border: '1px solid rgba(255, 255, 255, 0.05)',
                    borderRadius: '4px',
                    padding: '0.75rem',
                  }}
                >
                  <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '4px' }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                      <span style={{ fontFamily: 'var(--font-mono, monospace)', fontWeight: 700, color: '#38bdf8', fontSize: '0.6875rem' }}>
                        SHOT {String(item.order).padStart(2, '0')}
                      </span>
                      <span style={{ fontSize: '0.75rem', color: 'var(--text-primary)', fontWeight: 600 }}>
                        {item.title}
                      </span>
                    </div>
                    <span style={{ fontFamily: 'var(--font-mono, monospace)', fontSize: '0.625rem', color: '#93c5fd' }}>
                      {item.endpoint}
                    </span>
                  </div>
                  <pre
                    style={{
                      margin: 0,
                      padding: '0.5rem',
                      backgroundColor: 'rgba(0, 0, 0, 0.4)',
                      borderRadius: '3px',
                      fontFamily: 'var(--font-mono, monospace)',
                      fontSize: '0.625rem',
                      color: 'var(--text-secondary)',
                      overflowX: 'auto',
                      whiteSpace: 'pre-wrap',
                    }}
                  >
                    {JSON.stringify(item.payload, null, 2)}
                  </pre>
                </div>
              ))}
            </div>
          </div>
        </div>
      )}
    </section>
  );
};
