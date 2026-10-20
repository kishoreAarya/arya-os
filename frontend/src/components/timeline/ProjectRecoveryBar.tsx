import React from 'react';
import {
  Save,
  RotateCcw,
  Trash2,
  AlertTriangle,
  CheckCircle2,
  Database,
  Eye,
  X,
  FileCheck,
} from 'lucide-react';
import { ProjectRecoveryState, PersistedProjectEnvelope } from '../../types/productionTimeline';

interface ProjectRecoveryBarProps {
  recoveryState: ProjectRecoveryState;
  envelope: PersistedProjectEnvelope | null;
  onRestore?: () => void;
  onDiscard?: () => void;
  onRestoreProject?: () => void;
  onDiscardProject?: () => void;
  onReviewShots?: () => void;
  onReviewInterruptedShots?: () => void;
  onDismiss?: () => void;
}

export const ProjectRecoveryBar: React.FC<ProjectRecoveryBarProps> = ({
  recoveryState,
  envelope,
  onRestore,
  onDiscard,
  onRestoreProject,
  onDiscardProject,
  onReviewShots,
  onReviewInterruptedShots,
  onDismiss,
}) => {
  const handleRestore = onRestore || onRestoreProject || (() => {});
  const handleDiscard = onDiscard || onDiscardProject || (() => {});
  const handleReview = onReviewShots || onReviewInterruptedShots;
  // If no envelope and state is NEW or undefined, render subtle indicator
  if (recoveryState === 'NEW') {
    return (
      <div
        data-testid="project-recovery-bar"
        data-recovery-state="NEW"
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          padding: '0.4rem 0.75rem',
          backgroundColor: 'rgba(15, 23, 42, 0.4)',
          border: '1px solid rgba(255, 255, 255, 0.05)',
          borderRadius: '4px',
          fontSize: '0.6875rem',
          fontFamily: 'var(--font-mono, monospace)',
          color: 'var(--text-muted)',
          marginBottom: '0.625rem',
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
          <Database size={12} style={{ color: 'var(--text-muted)' }} />
          <strong style={{ letterSpacing: '0.05em' }}>PROJECT STATE // NEW</strong>
          <span>— No persisted production project found.</span>
        </div>
      </div>
    );
  }

  // Saved Project Found / Recoverable State
  if (recoveryState === 'RECOVERABLE' && envelope) {
    const totalSequences = envelope.project.sequences?.length || 0;
    const totalShots = envelope.project.sequences?.reduce(
      (sum, s) => sum + (s.shots?.length || 0),
      0
    ) || 0;
    const formattedDate = new Date(envelope.savedAt).toLocaleTimeString();

    return (
      <div
        data-testid="project-recovery-bar"
        data-recovery-state="RECOVERABLE"
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          flexWrap: 'wrap',
          gap: '0.625rem',
          padding: '0.5rem 0.875rem',
          backgroundColor: 'rgba(56, 189, 248, 0.08)',
          border: '1px solid rgba(56, 189, 248, 0.3)',
          borderRadius: '4px',
          fontSize: '0.6875rem',
          fontFamily: 'var(--font-mono, monospace)',
          color: 'var(--text-primary)',
          marginBottom: '0.625rem',
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: '8px', flexWrap: 'wrap' }}>
          <RotateCcw size={13} style={{ color: '#38bdf8' }} />
          <strong style={{ color: '#38bdf8', letterSpacing: '0.05em' }}>
            PROJECT STATE // RECOVERABLE
          </strong>
          <span style={{ color: 'var(--text-muted)' }}>|</span>
          <span>PROJECT: <strong style={{ color: '#f1f5f9' }}>{envelope.project.title}</strong></span>
          <span style={{ color: 'var(--text-muted)' }}>|</span>
          <span>SEQUENCES: {String(totalSequences).padStart(2, '0')}</span>
          <span style={{ color: 'var(--text-muted)' }}>|</span>
          <span>SHOTS: {String(totalShots).padStart(2, '0')}</span>
          <span style={{ color: 'var(--text-muted)' }}>|</span>
          <span style={{ color: 'var(--text-muted)' }}>LAST SAVED: {formattedDate}</span>
        </div>

        <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
          <button
            data-testid="restore-project-btn"
            onClick={handleRestore}
            style={{
              display: 'inline-flex',
              alignItems: 'center',
              gap: '4px',
              padding: '3px 9px',
              backgroundColor: 'rgba(56, 189, 248, 0.2)',
              border: '1px solid rgba(56, 189, 248, 0.5)',
              borderRadius: '3px',
              color: '#38bdf8',
              fontWeight: 700,
              fontSize: '0.625rem',
              cursor: 'pointer',
              letterSpacing: '0.04em',
            }}
          >
            <RotateCcw size={11} />
            <span>RESTORE PROJECT</span>
          </button>

          <button
            data-testid="discard-project-btn"
            onClick={handleDiscard}
            style={{
              display: 'inline-flex',
              alignItems: 'center',
              gap: '4px',
              padding: '3px 8px',
              backgroundColor: 'rgba(239, 68, 68, 0.1)',
              border: '1px solid rgba(239, 68, 68, 0.3)',
              borderRadius: '3px',
              color: '#f87171',
              fontSize: '0.625rem',
              cursor: 'pointer',
            }}
          >
            <Trash2 size={11} />
            <span>DISCARD</span>
          </button>
        </div>
      </div>
    );
  }

  // Restored state banner
  if (recoveryState === 'RESTORED') {
    return (
      <div
        data-testid="project-recovery-bar"
        data-recovery-state="RESTORED"
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          padding: '0.45rem 0.875rem',
          backgroundColor: 'rgba(52, 211, 153, 0.08)',
          border: '1px solid rgba(52, 211, 153, 0.3)',
          borderRadius: '4px',
          fontSize: '0.6875rem',
          fontFamily: 'var(--font-mono, monospace)',
          color: '#34d399',
          marginBottom: '0.625rem',
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
          <CheckCircle2 size={13} style={{ color: '#34d399' }} />
          <strong style={{ letterSpacing: '0.05em' }}>PROJECT STATE // RESTORED</strong>
          <span style={{ color: 'var(--text-secondary)' }}>
            — Production intent recovered. No generation dispatched.
          </span>
        </div>

        {onDismiss && (
          <button
            data-testid="dismiss-recovery-btn"
            onClick={onDismiss}
            style={{
              background: 'none',
              border: 'none',
              color: 'var(--text-muted)',
              cursor: 'pointer',
              padding: '2px',
            }}
          >
            <X size={13} />
          </button>
        )}
      </div>
    );
  }

  // Interrupted Execution / Recovery Required state
  if (recoveryState === 'RECOVERY_REQUIRED') {
    return (
      <div
        data-testid="project-recovery-bar"
        data-recovery-state="RECOVERY_REQUIRED"
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          flexWrap: 'wrap',
          gap: '0.5rem',
          padding: '0.5rem 0.875rem',
          backgroundColor: 'rgba(245, 158, 11, 0.08)',
          border: '1px solid rgba(245, 158, 11, 0.35)',
          borderRadius: '4px',
          fontSize: '0.6875rem',
          fontFamily: 'var(--font-mono, monospace)',
          color: '#fbbf24',
          marginBottom: '0.625rem',
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
          <AlertTriangle size={13} style={{ color: '#fbbf24' }} />
          <strong style={{ letterSpacing: '0.05em' }}>PROJECT STATE // RECOVERY REQUIRED</strong>
          <span style={{ color: '#fde68a' }}>
            — One or more shots were previously in-flight. Execution state cannot be verified locally.
          </span>
        </div>

        {handleReview && (
          <button
            data-testid="review-interrupted-shots-btn"
            onClick={handleReview}
            style={{
              display: 'inline-flex',
              alignItems: 'center',
              gap: '4px',
              padding: '3px 9px',
              backgroundColor: 'rgba(245, 158, 11, 0.2)',
              border: '1px solid rgba(245, 158, 11, 0.5)',
              borderRadius: '3px',
              color: '#fbbf24',
              fontWeight: 700,
              fontSize: '0.625rem',
              cursor: 'pointer',
            }}
          >
            <Eye size={11} />
            <span>REVIEW SHOTS</span>
          </button>
        )}
      </div>
    );
  }

  // Saved / Persisted confirmation indicator
  if (recoveryState === 'SAVED') {
    return (
      <div
        data-testid="project-recovery-bar"
        data-recovery-state="SAVED"
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          padding: '0.35rem 0.75rem',
          backgroundColor: 'rgba(56, 189, 248, 0.05)',
          border: '1px solid rgba(56, 189, 248, 0.15)',
          borderRadius: '4px',
          fontSize: '0.625rem',
          fontFamily: 'var(--font-mono, monospace)',
          color: 'var(--text-muted)',
          marginBottom: '0.625rem',
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
          <FileCheck size={12} style={{ color: '#38bdf8' }} />
          <span style={{ color: '#38bdf8', fontWeight: 600 }}>PROJECT STATE // SAVED</span>
          <span>— Production intent persisted locally.</span>
        </div>
      </div>
    );
  }

  return null;
};
