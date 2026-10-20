import React, { useEffect } from 'react';
import {
  X,
  Copy,
  RotateCcw,
  CheckCircle2,
  AlertCircle,
  Clock,
  Film,
  Image as ImageIcon,
  DollarSign,
  Cpu,
  Layers,
  Eye,
  ExternalLink,
} from 'lucide-react';
import { ProductionRun } from '../../types/productionRun';

interface RunDetailInspectorProps {
  run: ProductionRun | null;
  isOpen: boolean;
  onClose: () => void;
  onReproduce: (run: ProductionRun) => void;
  onInspectInViewport?: (run: ProductionRun) => void;
}

export const RunDetailInspector: React.FC<RunDetailInspectorProps> = ({
  run,
  isOpen,
  onClose,
  onReproduce,
  onInspectInViewport,
}) => {
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape' && isOpen) {
        onClose();
      }
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [isOpen, onClose]);

  if (!isOpen || !run) return null;

  const isVideo =
    run.mode === 'video' ||
    run.mode === 'image_to_video' ||
    Boolean(run.outputAsset && (run.outputAsset.includes('.mp4') || run.outputAsset.includes('video')));

  const getStatusBadge = () => {
    switch (run.status) {
      case 'completed':
        return (
          <span className="badge badge-completed" style={{ display: 'inline-flex', alignItems: 'center', gap: '4px' }}>
            <CheckCircle2 size={12} />
            <span>COMPLETED</span>
          </span>
        );
      case 'failed':
        return (
          <span className="badge badge-failed" style={{ display: 'inline-flex', alignItems: 'center', gap: '4px' }}>
            <AlertCircle size={12} />
            <span>FAILED</span>
          </span>
        );
      case 'in_progress':
        return <span className="badge badge-in_progress">PROCESSING</span>;
      default:
        return <span className="badge badge-pending">PENDING</span>;
    }
  };

  const formattedDate = run.createdAt
    ? new Date(run.createdAt).toLocaleString(undefined, {
        dateStyle: 'medium',
        timeStyle: 'medium',
      })
    : 'Unknown';

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-labelledby="run-detail-title"
      data-testid="run-detail-inspector"
      style={{
        position: 'fixed',
        inset: 0,
        backgroundColor: 'rgba(3, 7, 18, 0.85)',
        backdropFilter: 'blur(8px)',
        zIndex: 1000,
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        padding: '1rem',
      }}
      onClick={onClose}
    >
      <div
        className="creator-card"
        style={{
          width: '100%',
          maxWidth: '840px',
          maxHeight: '90vh',
          overflowY: 'auto',
          backgroundColor: '#0c1017',
          border: '1px solid rgba(255, 255, 255, 0.12)',
          borderRadius: 'var(--radius-lg, 8px)',
          boxShadow: '0 25px 50px -12px rgba(0, 0, 0, 0.7)',
          padding: '1.5rem',
        }}
        onClick={(e) => e.stopPropagation()}
      >
        {/* Top Header */}
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            borderBottom: '1px solid rgba(255, 255, 255, 0.08)',
            paddingBottom: '1rem',
            marginBottom: '1.25rem',
          }}
        >
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
            <div
              style={{
                width: '32px',
                height: '32px',
                borderRadius: '6px',
                backgroundColor: 'rgba(59, 130, 246, 0.12)',
                border: '1px solid rgba(59, 130, 246, 0.3)',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
              }}
            >
              {isVideo ? <Film size={16} color="var(--accent-primary)" /> : <ImageIcon size={16} color="var(--accent-primary)" />}
            </div>
            <div>
              <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                <h3
                  id="run-detail-title"
                  style={{
                    fontSize: '1rem',
                    fontWeight: 600,
                    margin: 0,
                    color: 'var(--text-primary)',
                    letterSpacing: '0.02em',
                  }}
                >
                  RUN INTELLIGENCE & TELEMETRY
                </h3>
                {getStatusBadge()}
              </div>
              <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)', fontFamily: 'monospace', marginTop: '2px' }}>
                ID: {run.id}
              </div>
            </div>
          </div>

          <button
            type="button"
            onClick={onClose}
            aria-label="Close inspector"
            className="btn-secondary"
            style={{
              padding: '6px',
              borderRadius: '6px',
              color: 'var(--text-muted)',
            }}
          >
            <X size={18} />
          </button>
        </div>

        {/* Section 1: Lifecycle Timeline */}
        <div style={{ marginBottom: '1.5rem' }}>
          <div
            style={{
              fontSize: '0.6875rem',
              fontWeight: 700,
              textTransform: 'uppercase',
              letterSpacing: '0.08em',
              color: 'var(--text-muted)',
              marginBottom: '0.75rem',
            }}
          >
            01 // EXECUTION LIFECYCLE TIMELINE
          </div>
          <div
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: '0.5rem',
              backgroundColor: 'rgba(7, 10, 16, 0.8)',
              border: '1px solid rgba(255, 255, 255, 0.06)',
              borderRadius: '6px',
              padding: '0.75rem 1rem',
              overflowX: 'auto',
            }}
            data-testid="lifecycle-timeline"
          >
            {/* Step 1: Created */}
            <div style={{ display: 'flex', alignItems: 'center', gap: '0.375rem' }}>
              <span style={{ width: '8px', height: '8px', borderRadius: '50%', backgroundColor: 'var(--accent-primary)' }} />
              <span style={{ fontSize: '0.75rem', fontWeight: 600, color: 'var(--text-primary)' }}>CREATED</span>
            </div>
            <span style={{ color: 'var(--text-muted)', fontSize: '0.75rem' }}>→</span>

            {/* Step 2: Submitted */}
            <div style={{ display: 'flex', alignItems: 'center', gap: '0.375rem' }}>
              <span style={{ width: '8px', height: '8px', borderRadius: '50%', backgroundColor: 'var(--accent-primary)' }} />
              <span style={{ fontSize: '0.75rem', fontWeight: 600, color: 'var(--text-primary)' }}>SUBMITTED</span>
            </div>
            <span style={{ color: 'var(--text-muted)', fontSize: '0.75rem' }}>→</span>

            {/* Step 3: Synthesizing */}
            <div style={{ display: 'flex', alignItems: 'center', gap: '0.375rem' }}>
              <span style={{ width: '8px', height: '8px', borderRadius: '50%', backgroundColor: 'var(--accent-primary)' }} />
              <span style={{ fontSize: '0.75rem', fontWeight: 600, color: 'var(--text-primary)' }}>SYNTHESIZING</span>
            </div>
            <span style={{ color: 'var(--text-muted)', fontSize: '0.75rem' }}>→</span>

            {/* Step 4: Processing */}
            <div style={{ display: 'flex', alignItems: 'center', gap: '0.375rem' }}>
              <span
                style={{
                  width: '8px',
                  height: '8px',
                  borderRadius: '50%',
                  backgroundColor: run.status === 'failed' ? 'var(--danger)' : 'var(--accent-primary)',
                }}
              />
              <span style={{ fontSize: '0.75rem', fontWeight: 600, color: 'var(--text-primary)' }}>PROCESSING</span>
            </div>
            <span style={{ color: 'var(--text-muted)', fontSize: '0.75rem' }}>→</span>

            {/* Step 5: Complete or Error */}
            {run.status === 'failed' ? (
              <div style={{ display: 'flex', alignItems: 'center', gap: '0.375rem' }}>
                <span style={{ width: '8px', height: '8px', borderRadius: '50%', backgroundColor: 'var(--danger)' }} />
                <span style={{ fontSize: '0.75rem', fontWeight: 700, color: 'var(--danger)' }}>ERROR</span>
              </div>
            ) : (
              <div style={{ display: 'flex', alignItems: 'center', gap: '0.375rem' }}>
                <span
                  style={{
                    width: '8px',
                    height: '8px',
                    borderRadius: '50%',
                    backgroundColor: run.status === 'completed' ? 'var(--success)' : 'var(--text-muted)',
                  }}
                />
                <span
                  style={{
                    fontSize: '0.75rem',
                    fontWeight: 700,
                    color: run.status === 'completed' ? 'var(--success)' : 'var(--text-muted)',
                  }}
                >
                  COMPLETE
                </span>
              </div>
            )}
          </div>
        </div>

        {/* Section 2: Core Grid (Telemetry, Conditioning, Parameters) */}
        <div
          style={{
            display: 'grid',
            gridTemplateColumns: 'repeat(auto-fit, minmax(240px, 1fr))',
            gap: '1rem',
            marginBottom: '1.5rem',
          }}
        >
          {/* Identity & Metadata Card */}
          <div
            style={{
              backgroundColor: 'rgba(7, 10, 16, 0.65)',
              border: '1px solid rgba(255, 255, 255, 0.06)',
              borderRadius: '6px',
              padding: '0.875rem',
            }}
          >
            <div
              style={{
                fontSize: '0.6875rem',
                fontWeight: 700,
                color: 'var(--text-muted)',
                textTransform: 'uppercase',
                letterSpacing: '0.05em',
                marginBottom: '0.5rem',
              }}
            >
              RUN IDENTITY
            </div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: '0.375rem', fontSize: '0.8125rem' }}>
              <div>
                <span style={{ color: 'var(--text-muted)' }}>Mode: </span>
                <span style={{ fontWeight: 600, textTransform: 'capitalize' }}>
                  {run.mode.replace(/_/g, ' ')}
                </span>
              </div>
              <div>
                <span style={{ color: 'var(--text-muted)' }}>Created: </span>
                <span>{formattedDate}</span>
              </div>
              <div>
                <span style={{ color: 'var(--text-muted)' }}>Job ID: </span>
                <span style={{ fontFamily: 'monospace', fontSize: '0.75rem' }}>{run.jobId}</span>
              </div>
              {run.workflowRunId && run.workflowRunId !== run.jobId && (
                <div>
                  <span style={{ color: 'var(--text-muted)' }}>Workflow Run: </span>
                  <span style={{ fontFamily: 'monospace', fontSize: '0.75rem' }}>{run.workflowRunId}</span>
                </div>
              )}
            </div>
          </div>

          {/* Execution Telemetry Card */}
          <div
            style={{
              backgroundColor: 'rgba(7, 10, 16, 0.65)',
              border: '1px solid rgba(255, 255, 255, 0.06)',
              borderRadius: '6px',
              padding: '0.875rem',
            }}
            data-testid="run-telemetry-box"
          >
            <div
              style={{
                fontSize: '0.6875rem',
                fontWeight: 700,
                color: 'var(--text-muted)',
                textTransform: 'uppercase',
                letterSpacing: '0.05em',
                marginBottom: '0.5rem',
              }}
            >
              EXECUTION TELEMETRY
            </div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: '0.375rem', fontSize: '0.8125rem' }}>
              <div>
                <span style={{ color: 'var(--text-muted)' }}>Provider: </span>
                <span style={{ fontWeight: 600, color: 'var(--accent-primary)' }} data-testid="telemetry-actual-provider">
                  {run.actualProvider || run.provider || 'UNAVAILABLE'}
                </span>
              </div>
              <div>
                <span style={{ color: 'var(--text-muted)' }}>Requested Provider: </span>
                <span style={{ fontWeight: 600 }} data-testid="telemetry-requested-provider">
                  {run.requestedProvider || 'UNAVAILABLE'}
                </span>
              </div>
              <div>
                <span style={{ color: 'var(--text-muted)' }}>Model: </span>
                <span style={{ fontWeight: 600 }} data-testid="telemetry-actual-model">
                  {run.actualModel || run.model || 'UNAVAILABLE'}
                </span>
              </div>
              <div>
                <span style={{ color: 'var(--text-muted)' }}>Requested Model: </span>
                <span style={{ fontWeight: 600 }} data-testid="telemetry-requested-model">
                  {run.requestedModel || 'UNAVAILABLE'}
                </span>
              </div>
              <div>
                <span style={{ color: 'var(--text-muted)' }}>Duration: </span>
                <span>{run.durationSeconds ? `${run.durationSeconds}s` : 'UNAVAILABLE'}</span>
              </div>
              <div>
                <span style={{ color: 'var(--text-muted)' }}>Cost: </span>
                {typeof run.cost === 'number' && run.cost > 0 ? (
                  <span style={{ color: 'var(--success)', fontWeight: 600 }}>${run.cost.toFixed(4)}</span>
                ) : (
                  <span style={{ color: 'var(--text-muted)' }}>UNAVAILABLE</span>
                )}
              </div>
            </div>
          </div>

          {/* Parameters & Directives Card */}
          <div
            style={{
              backgroundColor: 'rgba(7, 10, 16, 0.65)',
              border: '1px solid rgba(255, 255, 255, 0.06)',
              borderRadius: '6px',
              padding: '0.875rem',
            }}
          >
            <div
              style={{
                fontSize: '0.6875rem',
                fontWeight: 700,
                color: 'var(--text-muted)',
                textTransform: 'uppercase',
                letterSpacing: '0.05em',
                marginBottom: '0.5rem',
              }}
            >
              GENERATION PARAMETERS
            </div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: '0.375rem', fontSize: '0.8125rem' }}>
              <div>
                <span style={{ color: 'var(--text-muted)' }}>Aspect Ratio: </span>
                <span>{run.parameters.aspectRatio || '16:9'}</span>
              </div>
              {run.parameters.resolution && (
                <div>
                  <span style={{ color: 'var(--text-muted)' }}>Resolution: </span>
                  <span>{run.parameters.resolution}</span>
                </div>
              )}
              {run.parameters.durationSeconds && (
                <div>
                  <span style={{ color: 'var(--text-muted)' }}>Duration Seconds: </span>
                  <span>{run.parameters.durationSeconds}s</span>
                </div>
              )}
              <div>
                <span style={{ color: 'var(--text-muted)' }}>Conditioning: </span>
                <span>
                  {run.parameters.startFrameUrl || run.startFrame
                    ? 'Start Frame Supplied'
                    : run.parameters.referenceImageUrl || run.referenceAsset
                    ? 'Reference Image Supplied'
                    : 'Text-to-Media Direct'}
                </span>
              </div>
            </div>
          </div>
        </div>

        {/* Section 3: Prompt Text Display */}
        <div style={{ marginBottom: '1.5rem' }}>
          <div
            style={{
              fontSize: '0.6875rem',
              fontWeight: 700,
              textTransform: 'uppercase',
              letterSpacing: '0.08em',
              color: 'var(--text-muted)',
              marginBottom: '0.5rem',
            }}
          >
            PROMPT & DIRECTIVES
          </div>
          <div
            style={{
              backgroundColor: 'rgba(7, 10, 16, 0.85)',
              border: '1px solid rgba(255, 255, 255, 0.08)',
              borderRadius: '6px',
              padding: '0.875rem',
              fontSize: '0.875rem',
              lineHeight: 1.5,
              color: 'var(--text-primary)',
              wordBreak: 'break-word',
            }}
            data-testid="run-detail-prompt"
          >
            {run.prompt}
          </div>
        </div>

        {/* Section 4: Output Asset & Provenance */}
        {run.outputAsset && (
          <div style={{ marginBottom: '1.5rem' }}>
            <div
              style={{
                fontSize: '0.6875rem',
                fontWeight: 700,
                textTransform: 'uppercase',
                letterSpacing: '0.08em',
                color: 'var(--text-muted)',
                marginBottom: '0.5rem',
              }}
            >
              OUTPUT ASSET & PROVENANCE
            </div>
            <div
              style={{
                backgroundColor: 'rgba(7, 10, 16, 0.85)',
                border: '1px solid rgba(255, 255, 255, 0.08)',
                borderRadius: '6px',
                padding: '0.875rem',
                display: 'flex',
                gap: '1rem',
                alignItems: 'center',
              }}
            >
              <div
                style={{
                  width: '96px',
                  height: '96px',
                  borderRadius: '4px',
                  backgroundColor: '#000',
                  overflow: 'hidden',
                  flexShrink: 0,
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                }}
              >
                {isVideo ? (
                  <video
                    src={run.outputAsset}
                    style={{ width: '100%', height: '100%', objectFit: 'cover' }}
                  />
                ) : (
                  <img
                    src={run.outputAsset}
                    alt="Run output preview"
                    style={{ width: '100%', height: '100%', objectFit: 'cover' }}
                  />
                )}
              </div>
              <div style={{ flex: 1, minWidth: 0, fontSize: '0.8125rem' }}>
                <div style={{ fontWeight: 600, marginBottom: '0.25rem' }}>
                  {isVideo ? 'Produced Video Stream' : 'Synthesized Keyframe Image'}
                </div>
                <div
                  style={{
                    color: 'var(--text-muted)',
                    fontFamily: 'monospace',
                    fontSize: '0.75rem',
                    overflow: 'hidden',
                    textOverflow: 'ellipsis',
                    whiteSpace: 'nowrap',
                    marginBottom: '0.5rem',
                  }}
                >
                  {run.outputAsset}
                </div>
                {onInspectInViewport && (
                  <button
                    type="button"
                    onClick={() => {
                      onInspectInViewport(run);
                      onClose();
                    }}
                    className="btn-secondary"
                    style={{
                      fontSize: '0.75rem',
                      padding: '4px 8px',
                      display: 'inline-flex',
                      alignItems: 'center',
                      gap: '4px',
                    }}
                  >
                    <Eye size={12} />
                    <span>View in Creative Viewport</span>
                  </button>
                )}
              </div>
            </div>
          </div>
        )}

        {/* Section 5: Failure Notice if failed */}
        {run.status === 'failed' && (
          <div
            style={{
              padding: '0.875rem',
              backgroundColor: 'rgba(239, 68, 68, 0.08)',
              border: '1px solid rgba(239, 68, 68, 0.25)',
              borderRadius: '6px',
              color: '#fca5a5',
              fontSize: '0.8125rem',
              marginBottom: '1.5rem',
            }}
            data-testid="run-failure-notice"
          >
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '6px' }}>
              <strong
                style={{ display: 'block', textTransform: 'uppercase', letterSpacing: '0.04em' }}
                data-testid="failure-intelligence-box"
              >
                EXECUTION FAILURE INTELLIGENCE
              </strong>
              <span
                className="badge badge-failed"
                style={{ fontSize: '0.6875rem', fontWeight: 700 }}
                data-testid="failure-category"
              >
                {run.failureCategory || 'UNKNOWN'}
              </span>
            </div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: '4px', fontSize: '0.75rem', marginBottom: '6px' }}>
              <div>
                <span style={{ color: 'var(--text-muted)' }}>Failure Stage: </span>
                <span data-testid="failure-stage" style={{ fontWeight: 600 }}>{run.failureStage || 'UNKNOWN'}</span>
              </div>
              <div>
                <span style={{ color: 'var(--text-muted)' }}>Timestamp: </span>
                <span>{run.completedAt || run.createdAt || 'UNAVAILABLE'}</span>
              </div>
              <div>
                <span style={{ color: 'var(--text-muted)' }}>Retry Availability: </span>
                <span style={{ color: 'var(--success)', fontWeight: 600 }}>Available (Immutable payload preserved)</span>
              </div>
            </div>
            <div data-testid="failure-reason">
              <span style={{ color: 'var(--text-muted)' }}>Reason: </span>
              <span>{run.failureReason || run.error || 'The backend provider failed or connection timed out.'}</span>
            </div>
          </div>
        )}

        {/* Cancellation status if active or pending */}
        {(run.status === 'in_progress' || run.status === 'pending') && (
          <div
            style={{
              padding: '0.625rem 0.875rem',
              backgroundColor: 'rgba(255, 255, 255, 0.03)',
              border: '1px dashed rgba(255, 255, 255, 0.15)',
              borderRadius: '6px',
              fontSize: '0.75rem',
              color: 'var(--text-muted)',
              marginBottom: '1.5rem',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'space-between',
            }}
            data-testid="inspector-cancellation-status"
          >
            <span>OPERATIONAL CANCELLATION:</span>
            <span style={{ fontWeight: 600, color: 'var(--text-muted)' }}>
              CANCELLATION UNAVAILABLE (Backend V1 does not expose a job cancellation endpoint)
            </span>
          </div>
        )}

        {/* Actions Footer */}
        <div
          style={{
            display: 'flex',
            justifyContent: 'flex-end',
            alignItems: 'center',
            gap: '0.75rem',
            borderTop: '1px solid rgba(255, 255, 255, 0.08)',
            paddingTop: '1.25rem',
          }}
        >
          <button
            type="button"
            onClick={onClose}
            className="btn-secondary"
            style={{ padding: '8px 16px', fontSize: '0.8125rem' }}
          >
            Close
          </button>

          {/* Reproduce Button: Loads parameters into editable console without executing */}
          <button
            type="button"
            onClick={() => {
              onReproduce(run);
              onClose();
            }}
            className="btn-primary"
            style={{
              padding: '8px 16px',
              fontSize: '0.8125rem',
              display: 'inline-flex',
              alignItems: 'center',
              gap: '6px',
            }}
            data-testid="run-reproduce-btn"
          >
            <Copy size={14} />
            <span>Reproduce Parameters</span>
          </button>
        </div>
      </div>
    </div>
  );
};
