import React from 'react';
import {
  X,
  Layers,
  Clock,
  Cpu,
  ArrowRight,
  ShieldAlert,
  CheckCircle2,
  AlertTriangle,
  AlertCircle,
  Copy,
  Film,
  Image as ImageIcon,
  Code2,
} from 'lucide-react';
import { Shot } from '../../types/productionTimeline';

interface ShotDetailInspectorProps {
  shot: Shot;
  onClose: () => void;
  onReproduce: (shot: Shot) => void;
  onSelect?: (shot: Shot) => void;
}

export const ShotDetailInspector: React.FC<ShotDetailInspectorProps> = ({
  shot,
  onClose,
  onReproduce,
  onSelect,
}) => {
  const isBlocked = shot.readiness === 'BLOCKED' || shot.status === 'BLOCKED';
  const isWarning = shot.readiness === 'WARNING';
  const isReady = shot.readiness === 'READY' || shot.status === 'READY';
  const isComplete = shot.status === 'COMPLETE';

  const badgeColor = isComplete
    ? '#34d399'
    : isReady
    ? '#38bdf8'
    : isWarning || isBlocked
    ? '#fbbf24'
    : 'var(--text-muted)';

  const getStatusIcon = (status: string) => {
    switch (status) {
      case 'PASS':
      case 'READY':
      case 'COMPLETE':
      case 'PROVIDED':
        return <CheckCircle2 size={13} style={{ color: '#34d399' }} />;
      case 'WARNING':
        return <AlertTriangle size={13} style={{ color: '#fbbf24' }} />;
      case 'BLOCKED':
      case 'MISSING':
      case 'FAILED':
        return <AlertCircle size={13} style={{ color: '#fbbf24' }} />;
      default:
        return <Clock size={13} style={{ color: 'var(--text-muted)' }} />;
    }
  };

  // Stage 10 Section 18: Exact Generation Payload Preview
  const payloadPreview = {
    prompt: shot.prompt,
    generation_type: shot.generationType,
    model: shot.selectedModel,
    provider: shot.selectedProvider || undefined,
    aspect_ratio: shot.aspectRatio,
    resolution: shot.resolution || undefined,
    duration: shot.duration || undefined,
    start_frame: shot.startFrame || undefined,
    end_frame: shot.endFrame || undefined,
    reference_image: shot.referenceAssets?.[0] || undefined,
  };

  return (
    <div
      data-testid="shot-detail-inspector"
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
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div
        style={{
          width: '100%',
          maxWidth: '720px',
          maxHeight: '90vh',
          overflowY: 'auto',
          backgroundColor: 'rgba(11, 16, 26, 0.98)',
          border: '1px solid rgba(59, 130, 246, 0.25)',
          borderRadius: 'var(--radius-md, 8px)',
          padding: '1.25rem',
          boxShadow: '0 20px 40px rgba(0, 0, 0, 0.8), inset 0 1px 0 rgba(255, 255, 255, 0.08)',
          display: 'flex',
          flexDirection: 'column',
          gap: '1rem',
          color: 'var(--text-secondary)',
          fontSize: '0.75rem',
          fontFamily: 'var(--font-sans, system-ui, sans-serif)',
        }}
      >
        {/* Header */}
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', borderBottom: '1px solid rgba(255, 255, 255, 0.08)', paddingBottom: '0.75rem' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
            <span
              style={{
                fontFamily: 'var(--font-mono, monospace)',
                fontWeight: 700,
                fontSize: '0.75rem',
                color: '#38bdf8',
                backgroundColor: 'rgba(56, 189, 248, 0.1)',
                padding: '2px 6px',
                borderRadius: '4px',
              }}
            >
              SHOT {String(shot.order).padStart(2, '0')}
            </span>
            <strong style={{ color: 'var(--text-primary)', fontSize: '0.875rem' }}>
              {shot.title}
            </strong>
          </div>

          <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
            <span
              data-testid="shot-inspector-readiness-badge"
              style={{
                display: 'inline-flex',
                alignItems: 'center',
                gap: '4px',
                padding: '2px 8px',
                borderRadius: '4px',
                fontSize: '0.6875rem',
                fontWeight: 700,
                backgroundColor: `${badgeColor}1a`,
                border: `1px solid ${badgeColor}55`,
                color: badgeColor,
                letterSpacing: '0.04em',
              }}
            >
              {`STATE // ${shot.status}`}
            </span>
            <button
              data-testid="shot-inspector-close-btn"
              onClick={onClose}
              style={{
                background: 'none',
                border: 'none',
                color: 'var(--text-muted)',
                cursor: 'pointer',
                padding: '4px',
                display: 'flex',
                alignItems: 'center',
              }}
            >
              <X size={16} />
            </button>
          </div>
        </div>

        {/* Validation Reasons / Machine-readable codes if blocked */}
        {isBlocked && (
          <div
            data-testid="shot-validation-reasons"
            style={{
              padding: '0.625rem 0.875rem',
              backgroundColor: 'rgba(245, 158, 11, 0.08)',
              borderLeft: '3px solid #fbbf24',
              borderRadius: '0 4px 4px 0',
              color: '#fde68a',
            }}
          >
            <div style={{ fontWeight: 600, marginBottom: '4px' }}>EXECUTION BLOCKED</div>
            <ul style={{ margin: 0, paddingLeft: '1.25rem', lineHeight: 1.5 }}>
              {shot.validationResults.reasons.map((r, i) => (
                <li key={i}>{r}</li>
              ))}
            </ul>
          </div>
        )}

        {/* Prompt Section */}
        <div>
          <span style={{ display: 'block', fontSize: '0.625rem', textTransform: 'uppercase', color: 'var(--text-muted)', letterSpacing: '0.05em', marginBottom: '4px' }}>
            Prompt
          </span>
          <div
            data-testid="shot-prompt-display"
            style={{
              padding: '0.625rem',
              backgroundColor: 'rgba(0, 0, 0, 0.35)',
              borderRadius: '4px',
              border: '1px solid rgba(255, 255, 255, 0.04)',
              color: 'var(--text-primary)',
              lineHeight: 1.4,
            }}
          >
            {shot.prompt}
          </div>
        </div>

        {/* Configuration Matrix */}
        <div
          data-testid="shot-config-facts"
          style={{
            display: 'grid',
            gridTemplateColumns: 'repeat(auto-fit, minmax(130px, 1fr))',
            gap: '0.5rem',
            backgroundColor: 'rgba(0, 0, 0, 0.25)',
            padding: '0.75rem',
            borderRadius: '4px',
            border: '1px solid rgba(255, 255, 255, 0.04)',
          }}
        >
          <div>
            <span style={{ display: 'block', color: 'var(--text-muted)', fontSize: '0.625rem' }}>MODE</span>
            <strong style={{ color: 'var(--text-primary)' }}>{shot.generationType.toUpperCase()}</strong>
          </div>
          <div>
            <span style={{ display: 'block', color: 'var(--text-muted)', fontSize: '0.625rem' }}>MODEL</span>
            <strong style={{ color: 'var(--text-primary)' }}>{shot.selectedModel}</strong>
          </div>
          <div>
            <span style={{ display: 'block', color: 'var(--text-muted)', fontSize: '0.625rem' }}>ASPECT RATIO</span>
            <strong style={{ color: 'var(--text-primary)' }}>{shot.aspectRatio}</strong>
          </div>
          {shot.duration && (
            <div>
              <span style={{ display: 'block', color: 'var(--text-muted)', fontSize: '0.625rem' }}>DURATION</span>
              <strong style={{ color: 'var(--text-primary)' }}>{shot.duration}s</strong>
            </div>
          )}
          <div>
            <span style={{ display: 'block', color: 'var(--text-muted)', fontSize: '0.625rem' }}>PROVIDER</span>
            <strong style={{ color: 'var(--text-primary)' }}>{shot.selectedProvider}</strong>
          </div>
          <div>
            <span style={{ display: 'block', color: 'var(--text-muted)', fontSize: '0.625rem' }}>SOURCE PROVENANCE</span>
            <span style={{ fontFamily: 'var(--font-mono, monospace)', fontSize: '0.625rem', color: 'var(--text-muted)' }}>
              {shot.provenance}
            </span>
          </div>
        </div>

        {/* Dependencies Section */}
        <div data-testid="shot-dependencies-list">
          <span style={{ display: 'block', fontSize: '0.625rem', textTransform: 'uppercase', color: 'var(--text-muted)', letterSpacing: '0.05em', marginBottom: '4px' }}>
            Dependencies & Predecessors
          </span>
          {shot.dependencyShotIds.length === 0 ? (
            <div style={{ color: 'var(--text-muted)', fontStyle: 'italic', fontSize: '0.6875rem' }}>
              None (Root Shot)
            </div>
          ) : (
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: '6px' }}>
              {shot.dependencyShotIds.map((depId) => (
                <span
                  key={depId}
                  style={{
                    display: 'inline-flex',
                    alignItems: 'center',
                    gap: '4px',
                    padding: '2px 8px',
                    backgroundColor: 'rgba(59, 130, 246, 0.1)',
                    border: '1px solid rgba(59, 130, 246, 0.3)',
                    borderRadius: '4px',
                    fontFamily: 'var(--font-mono, monospace)',
                    fontSize: '0.6875rem',
                    color: '#93c5fd',
                  }}
                >
                  DEP: {depId}
                </span>
              ))}
            </div>
          )}
        </div>

        {/* Continuity Breakdown Matrix */}
        <div data-testid="shot-continuity-matrix">
          <span style={{ display: 'block', fontSize: '0.625rem', textTransform: 'uppercase', color: 'var(--text-muted)', letterSpacing: '0.05em', marginBottom: '6px' }}>
            Story & Production Continuity Verification
          </span>

          <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
            {/* 1. Character Continuity */}
            <div
              data-testid="continuity-character"
              style={{
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'space-between',
                padding: '6px 8px',
                backgroundColor: 'rgba(0, 0, 0, 0.25)',
                borderRadius: '4px',
                border: '1px solid rgba(255, 255, 255, 0.04)',
              }}
            >
              <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                {getStatusIcon(shot.continuityReport.character.status)}
                <span style={{ fontWeight: 600, color: 'var(--text-primary)' }}>CHARACTER:</span>
                <span>{shot.continuityReport.character.detail}</span>
              </div>
              <span style={{ fontFamily: 'var(--font-mono, monospace)', fontSize: '0.5625rem', color: 'var(--text-muted)' }}>
                SOURCE // {shot.continuityReport.character.source}
              </span>
            </div>

            {/* 2. Environment Continuity */}
            <div
              data-testid="continuity-environment"
              style={{
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'space-between',
                padding: '6px 8px',
                backgroundColor: 'rgba(0, 0, 0, 0.25)',
                borderRadius: '4px',
                border: '1px solid rgba(255, 255, 255, 0.04)',
              }}
            >
              <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                {getStatusIcon(shot.continuityReport.environment.status)}
                <span style={{ fontWeight: 600, color: 'var(--text-primary)' }}>ENVIRONMENT:</span>
                <span>{shot.continuityReport.environment.detail}</span>
              </div>
              <span style={{ fontFamily: 'var(--font-mono, monospace)', fontSize: '0.5625rem', color: 'var(--text-muted)' }}>
                SOURCE // {shot.continuityReport.environment.source}
              </span>
            </div>

            {/* 3. Visual Continuity */}
            <div
              data-testid="continuity-visual"
              style={{
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'space-between',
                padding: '6px 8px',
                backgroundColor: 'rgba(0, 0, 0, 0.25)',
                borderRadius: '4px',
                border: '1px solid rgba(255, 255, 255, 0.04)',
              }}
            >
              <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                {getStatusIcon(shot.continuityReport.visual.status)}
                <span style={{ fontWeight: 600, color: 'var(--text-primary)' }}>VISUAL:</span>
                <span>{shot.continuityReport.visual.detail}</span>
              </div>
              <span style={{ fontFamily: 'var(--font-mono, monospace)', fontSize: '0.5625rem', color: 'var(--text-muted)' }}>
                SOURCE // {shot.continuityReport.visual.source}
              </span>
            </div>

            {/* 4. Temporal Continuity */}
            <div
              data-testid="continuity-temporal"
              style={{
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'space-between',
                padding: '6px 8px',
                backgroundColor: 'rgba(0, 0, 0, 0.25)',
                borderRadius: '4px',
                border: '1px solid rgba(255, 255, 255, 0.04)',
              }}
            >
              <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                {getStatusIcon(shot.continuityReport.temporal.status)}
                <span style={{ fontWeight: 600, color: 'var(--text-primary)' }}>TEMPORAL:</span>
                <span>{shot.continuityReport.temporal.detail}</span>
              </div>
              <span style={{ fontFamily: 'var(--font-mono, monospace)', fontSize: '0.5625rem', color: 'var(--text-muted)' }}>
                SOURCE // {shot.continuityReport.temporal.source}
              </span>
            </div>

            {/* 5. Start Frame Continuity */}
            <div
              data-testid="continuity-start-frame"
              style={{
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'space-between',
                padding: '6px 8px',
                backgroundColor: 'rgba(0, 0, 0, 0.25)',
                borderRadius: '4px',
                border: '1px solid rgba(255, 255, 255, 0.04)',
              }}
            >
              <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                {getStatusIcon(shot.continuityReport.startFrame.status)}
                <span style={{ fontWeight: 600, color: 'var(--text-primary)' }}>START FRAME:</span>
                <span>{shot.continuityReport.startFrame.detail}</span>
              </div>
              <span style={{ fontFamily: 'var(--font-mono, monospace)', fontSize: '0.5625rem', color: 'var(--text-muted)' }}>
                SOURCE // {shot.continuityReport.startFrame.source}
              </span>
            </div>
          </div>
        </div>

        {/* Section 18: Read-Only Execution Payload Preview */}
        <div data-testid="shot-payload-preview-section">
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '4px' }}>
            <span style={{ fontSize: '0.625rem', textTransform: 'uppercase', color: 'var(--text-muted)', letterSpacing: '0.05em' }}>
              Execution Payload Preview (POST /creator/generate)
            </span>
            <span
              style={{
                fontFamily: 'var(--font-mono, monospace)',
                fontSize: '0.5625rem',
                color: '#38bdf8',
                backgroundColor: 'rgba(56, 189, 248, 0.1)',
                padding: '1px 5px',
                borderRadius: '3px',
              }}
            >
              READ-ONLY PREVIEW // NON-AUTONOMOUS
            </span>
          </div>

          <pre
            data-testid="shot-payload-preview-json"
            style={{
              margin: 0,
              padding: '0.625rem',
              backgroundColor: 'rgba(0, 0, 0, 0.4)',
              borderRadius: '4px',
              border: '1px solid rgba(255, 255, 255, 0.05)',
              fontFamily: 'var(--font-mono, monospace)',
              fontSize: '0.625rem',
              color: '#93c5fd',
              overflowX: 'auto',
              whiteSpace: 'pre-wrap',
              lineHeight: 1.4,
            }}
          >
            {JSON.stringify(payloadPreview, null, 2)}
          </pre>
        </div>

        {/* Actions Footer */}
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'flex-end', gap: '8px', borderTop: '1px solid rgba(255, 255, 255, 0.08)', paddingTop: '0.75rem', marginTop: '0.5rem' }}>
          <button
            data-testid="shot-reproduce-btn"
            onClick={() => {
              onReproduce(shot);
              onClose();
            }}
            style={{
              display: 'inline-flex',
              alignItems: 'center',
              gap: '6px',
              padding: '6px 14px',
              backgroundColor: 'rgba(56, 189, 248, 0.15)',
              border: '1px solid rgba(56, 189, 248, 0.4)',
              borderRadius: '4px',
              color: '#38bdf8',
              fontWeight: 600,
              fontSize: '0.6875rem',
              cursor: 'pointer',
              letterSpacing: '0.04em',
            }}
          >
            <Copy size={13} />
            <span>REPRODUCE PARAMETERS TO CONSOLE</span>
          </button>
        </div>
      </div>
    </div>
  );
};
