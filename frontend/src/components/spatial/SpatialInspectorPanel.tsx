import React, { useEffect } from 'react';
import {
  X,
  Info,
  Activity,
  CheckCircle2,
  AlertTriangle,
  AlertCircle,
  Cpu,
  Layers,
  Film,
  Box,
  Image as ImageIcon,
  CornerDownRight,
  ShieldCheck,
} from 'lucide-react';
import { SpatialInspectorData } from '../../types/spatial';

interface SpatialInspectorPanelProps {
  data: SpatialInspectorData;
  onClose: () => void;
}

/**
 * SpatialInspectorPanel — Non-destructive contextual inspection panel
 * Presents live production intelligence for Core, Subsystem Modules, Corridor Shots, and Job Packages.
 * Strictly observational: Zero mutations, zero autonomous execution triggers.
 */
export const SpatialInspectorPanel: React.FC<SpatialInspectorPanelProps> = ({ data, onClose }) => {
  // Listen for Escape key to close the inspector
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        onClose();
      }
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [onClose]);

  const categoryIcon = () => {
    switch (data.category) {
      case 'CORE':
        return <Cpu size={14} color="#f59e0b" />;
      case 'SUBSYSTEM':
        return <Layers size={14} color="#fbbf24" />;
      case 'SHOT':
        return <Film size={14} color="#38bdf8" />;
      case 'JOB_PACKAGE':
        return <Box size={14} color="#10b981" />;
      default:
        return <Info size={14} color="#f59e0b" />;
    }
  };

  const categoryLabel = () => {
    switch (data.category) {
      case 'CORE':
        return 'SYSTEM CORE';
      case 'SUBSYSTEM':
        return 'SUBSYSTEM MODULE';
      case 'SHOT':
        return 'PRODUCTION SHOT';
      case 'JOB_PACKAGE':
        return 'JOB PACKAGE // BOUNDARY';
      default:
        return 'INSPECTOR';
    }
  };

  const getStatusBadge = () => {
    const variant = data.statusVariant || 'neutral';
    let bg = 'rgba(100, 116, 139, 0.15)';
    let border = 'rgba(100, 116, 139, 0.4)';
    let text = '#94a3b8';
    let IconComponent = Activity;

    if (variant === 'success') {
      bg = 'rgba(16, 185, 129, 0.15)';
      border = 'rgba(16, 185, 129, 0.4)';
      text = '#10b981';
      IconComponent = CheckCircle2;
    } else if (variant === 'warning') {
      bg = 'rgba(245, 158, 11, 0.15)';
      border = 'rgba(245, 158, 11, 0.4)';
      text = '#fbbf24';
      IconComponent = AlertTriangle;
    } else if (variant === 'error') {
      bg = 'rgba(239, 68, 68, 0.15)';
      border = 'rgba(239, 68, 68, 0.4)';
      text = '#ef4444';
      IconComponent = AlertCircle;
    } else if (variant === 'active') {
      bg = 'rgba(56, 189, 248, 0.15)';
      border = 'rgba(56, 189, 248, 0.4)';
      text = '#38bdf8';
      IconComponent = Activity;
    }

    return (
      <span
        style={{
          display: 'inline-flex',
          alignItems: 'center',
          gap: '0.3rem',
          padding: '2px 8px',
          borderRadius: '4px',
          backgroundColor: bg,
          border: `1px solid ${border}`,
          color: text,
          fontSize: '0.6875rem',
          fontWeight: 700,
          letterSpacing: '0.06em',
          textTransform: 'uppercase',
        }}
      >
        <IconComponent size={11} />
        {data.status}
      </span>
    );
  };

  return (
    <aside
      data-testid="spatial-inspector-panel"
      aria-label="Spatial Selection Inspector"
      style={{
        position: 'relative',
        width: '360px',
        maxWidth: 'calc(100vw - 2rem)',
        backgroundColor: 'rgba(7, 10, 16, 0.94)',
        border: '1px solid rgba(245, 158, 11, 0.35)',
        borderRadius: '8px',
        padding: '1rem',
        backdropFilter: 'blur(16px)',
        boxShadow: '0 8px 32px rgba(0, 0, 0, 0.75)',
        display: 'flex',
        flexDirection: 'column',
        gap: '0.85rem',
        color: '#cbd5e1',
        fontFamily: "'JetBrains Mono', monospace",
        zIndex: 50,
        pointerEvents: 'auto',
      }}
    >
      {/* Header: Category Badge & Close Button */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.45rem' }}>
          {categoryIcon()}
          <span
            style={{
              fontSize: '0.6875rem',
              fontWeight: 700,
              letterSpacing: '0.1em',
              color: '#f59e0b',
            }}
          >
            [{categoryLabel()}]
          </span>
        </div>
        <button
          type="button"
          data-testid="spatial-inspector-close-btn"
          onClick={onClose}
          aria-label="Close inspector panel"
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: '0.25rem',
            background: 'transparent',
            border: '1px solid rgba(255, 255, 255, 0.1)',
            borderRadius: '4px',
            color: '#94a3b8',
            fontSize: '0.625rem',
            padding: '2px 6px',
            cursor: 'pointer',
            transition: 'all 0.15s ease',
          }}
          onMouseEnter={(e) => {
            e.currentTarget.style.color = '#f8fafc';
            e.currentTarget.style.borderColor = 'rgba(245, 158, 11, 0.5)';
          }}
          onMouseLeave={(e) => {
            e.currentTarget.style.color = '#94a3b8';
            e.currentTarget.style.borderColor = 'rgba(255, 255, 255, 0.1)';
          }}
        >
          <span
            data-testid="spatial-inspector-close"
            style={{ display: 'inline-flex', alignItems: 'center', gap: '0.25rem' }}
          >
            <span>ESC // CLOSE</span>
            <X size={12} />
          </span>
        </button>
      </div>

      {/* Title & Status */}
      <div style={{ display: 'flex', flexDirection: 'column', gap: '0.35rem' }}>
        <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: '0.5rem' }}>
          <h2
            style={{
              fontSize: '0.875rem',
              fontWeight: 700,
              color: '#f8fafc',
              letterSpacing: '0.04em',
              margin: 0,
              lineHeight: 1.3,
            }}
          >
            {data.title}
          </h2>
          {getStatusBadge()}
        </div>
        {data.subtitle && (
          <div style={{ fontSize: '0.6875rem', color: '#94a3b8', lineHeight: 1.4 }}>
            {data.subtitle}
          </div>
        )}
      </div>

      {/* Structured Metrics Grid */}
      {data.metrics && data.metrics.length > 0 && (
        <div
          style={{
            display: 'grid',
            gridTemplateColumns: 'repeat(2, 1fr)',
            gap: '0.5rem',
            backgroundColor: 'rgba(15, 23, 42, 0.6)',
            padding: '0.625rem',
            borderRadius: '6px',
            border: '1px solid rgba(255, 255, 255, 0.05)',
          }}
        >
          {data.metrics.map((m, idx) => (
            <div key={idx} style={{ display: 'flex', flexDirection: 'column', gap: '0.15rem' }}>
              <span style={{ fontSize: '0.5625rem', color: '#64748b', letterSpacing: '0.06em' }}>
                {m.label.toUpperCase()}
              </span>
              <span style={{ fontSize: '0.75rem', fontWeight: 600, color: '#e2e8f0' }}>
                {m.value}
              </span>
            </div>
          ))}
        </div>
      )}

      {/* Details List */}
      {data.details && data.details.length > 0 && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '0.3rem' }}>
          <span style={{ fontSize: '0.5625rem', color: '#64748b', letterSpacing: '0.08em' }}>
            OPERATIONAL LOGS & TELEMETRY
          </span>
          <div
            style={{
              display: 'flex',
              flexDirection: 'column',
              gap: '0.35rem',
              backgroundColor: 'rgba(2, 6, 23, 0.5)',
              padding: '0.5rem 0.625rem',
              borderRadius: '4px',
              borderLeft: '2px solid #f59e0b',
            }}
          >
            {data.details.map((detail, idx) => (
              <div key={idx} style={{ fontSize: '0.625rem', color: '#94a3b8', lineHeight: 1.4 }}>
                • {detail}
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Thumbnail Asset Preview (If shot render asset exists) */}
      {data.thumbnailUrl && (
        <div
          data-testid="spatial-inspector-asset-preview"
          style={{
            position: 'relative',
            width: '100%',
            height: '160px',
            backgroundColor: '#020408',
            borderRadius: '6px',
            overflow: 'hidden',
            border: '1px solid rgba(56, 189, 248, 0.4)',
            boxShadow: '0 4px 20px rgba(0, 0, 0, 0.75)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
          }}
        >
          {data.thumbnailUrl.endsWith('.mp4') || data.thumbnailUrl.endsWith('.webm') ? (
            <video
              data-testid="spatial-inspector-video-player"
              src={data.thumbnailUrl}
              controls
              playsInline
              loop
              style={{
                width: '100%',
                height: '100%',
                objectFit: 'contain',
              }}
            />
          ) : (
            <img
              src={data.thumbnailUrl}
              alt={data.title}
              style={{
                width: '100%',
                height: '100%',
                objectFit: 'cover',
              }}
              onError={(e) => {
                (e.currentTarget as HTMLElement).style.display = 'none';
              }}
            />
          )}
          <div
            style={{
              position: 'absolute',
              top: '6px',
              left: '6px',
              backgroundColor: 'rgba(2, 6, 23, 0.85)',
              padding: '2px 6px',
              borderRadius: '3px',
              fontSize: '0.5625rem',
              color: '#38bdf8',
              border: '1px solid rgba(56, 189, 248, 0.3)',
              fontWeight: 600,
              letterSpacing: '0.04em',
            }}
          >
            {data.thumbnailUrl.endsWith('.mp4') || data.thumbnailUrl.endsWith('.webm') ? 'VIDEO ARTIFACT // MP4' : 'ARTIFACT PREVIEW'}
          </div>
          <div
            style={{
              position: 'absolute',
              bottom: '6px',
              right: '6px',
              backgroundColor: 'rgba(2, 4, 8, 0.85)',
              padding: '2px 6px',
              borderRadius: '3px',
              fontSize: '0.5625rem',
              color: '#10b981',
              border: '1px solid rgba(16, 185, 129, 0.3)',
              fontWeight: 600,
            }}
          >
            RENDER CACHE ACTIVE
          </div>
        </div>
      )}

      {/* Remediation Guidance */}
      {data.remediation && (
        <div
          data-testid="spatial-inspector-remediation"
          style={{
            backgroundColor: 'rgba(239, 68, 68, 0.1)',
            border: '1px solid rgba(239, 68, 68, 0.35)',
            borderRadius: '4px',
            padding: '0.5rem 0.625rem',
            fontSize: '0.625rem',
            color: '#fca5a5',
            display: 'flex',
            flexDirection: 'column',
            gap: '0.2rem',
          }}
        >
          <span style={{ fontWeight: 700, color: '#ef4444', letterSpacing: '0.04em' }}>
            CONTINUITY REMEDIATION:
          </span>
          <span>{data.remediation}</span>
        </div>
      )}

      {/* Keyframe Anchors & Continuity References (Part I) */}
      {(data.firstFrameUrl || data.lastFrameUrl || data.referenceImageUrl) && (
        <div
          data-testid="spatial-inspector-keyframes"
          style={{
            display: 'flex',
            flexDirection: 'column',
            gap: '0.4rem',
            backgroundColor: 'rgba(15, 23, 42, 0.55)',
            border: '1px solid rgba(56, 189, 248, 0.25)',
            borderRadius: '6px',
            padding: '0.625rem',
          }}
        >
          <span style={{ fontSize: '0.5625rem', color: '#38bdf8', fontWeight: 700, letterSpacing: '0.08em' }}>
            KEYFRAME ANCHORS & REFERENCES (PART I)
          </span>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(80px, 1fr))', gap: '0.4rem' }}>
            {data.firstFrameUrl && (
              <div style={{ display: 'flex', flexDirection: 'column', gap: '0.2rem' }}>
                <span style={{ fontSize: '0.5625rem', color: '#64748b' }}>FIRST FRAME</span>
                <div style={{ width: '100%', height: '52px', backgroundColor: '#020408', borderRadius: '4px', overflow: 'hidden', border: '1px solid rgba(56, 189, 248, 0.4)' }}>
                  <img src={data.firstFrameUrl} alt="First Frame" style={{ width: '100%', height: '100%', objectFit: 'cover' }} onError={(e) => { (e.currentTarget as HTMLElement).style.display = 'none'; }} />
                </div>
              </div>
            )}
            {data.lastFrameUrl && (
              <div style={{ display: 'flex', flexDirection: 'column', gap: '0.2rem' }}>
                <span style={{ fontSize: '0.5625rem', color: '#64748b' }}>LAST FRAME</span>
                <div style={{ width: '100%', height: '52px', backgroundColor: '#020408', borderRadius: '4px', overflow: 'hidden', border: '1px solid rgba(16, 185, 129, 0.4)' }}>
                  <img src={data.lastFrameUrl} alt="Last Frame" style={{ width: '100%', height: '100%', objectFit: 'cover' }} onError={(e) => { (e.currentTarget as HTMLElement).style.display = 'none'; }} />
                </div>
              </div>
            )}
            {data.referenceImageUrl && (
              <div style={{ display: 'flex', flexDirection: 'column', gap: '0.2rem' }}>
                <span style={{ fontSize: '0.5625rem', color: '#64748b' }}>REFERENCE IMAGE</span>
                <div style={{ width: '100%', height: '52px', backgroundColor: '#020408', borderRadius: '4px', overflow: 'hidden', border: '1px solid rgba(245, 158, 11, 0.4)' }}>
                  <img src={data.referenceImageUrl} alt="Reference Image" style={{ width: '100%', height: '100%', objectFit: 'cover' }} onError={(e) => { (e.currentTarget as HTMLElement).style.display = 'none'; }} />
                </div>
              </div>
            )}
          </div>
        </div>
      )}

      {/* Temporal Continuity & Production Graph Dependency Section */}
      {data.temporalDependency && (
        <div
          data-testid="spatial-inspector-temporal-dependency"
          style={{
            display: 'flex',
            flexDirection: 'column',
            gap: '0.45rem',
            backgroundColor: 'rgba(15, 23, 42, 0.65)',
            border: '1px solid rgba(56, 189, 248, 0.35)',
            borderRadius: '6px',
            padding: '0.625rem',
          }}
        >
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '0.35rem' }}>
              <CornerDownRight size={13} color="#38bdf8" />
              <span style={{ fontSize: '0.625rem', color: '#38bdf8', fontWeight: 700, letterSpacing: '0.08em' }}>
                TEMPORAL DEPENDENCY
              </span>
            </div>
            <span
              data-testid="spatial-inspector-continuity-badge"
              style={{
                fontSize: '0.5625rem',
                fontWeight: 700,
                padding: '2px 6px',
                borderRadius: '3px',
                backgroundColor:
                  data.temporalDependency.continuityStatus === 'PASS'
                    ? 'rgba(16, 185, 129, 0.2)'
                    : data.temporalDependency.continuityStatus === 'WARNING'
                    ? 'rgba(245, 158, 11, 0.2)'
                    : 'rgba(239, 68, 68, 0.2)',
                color:
                  data.temporalDependency.continuityStatus === 'PASS'
                    ? '#10b981'
                    : data.temporalDependency.continuityStatus === 'WARNING'
                    ? '#fbbf24'
                    : '#ef4444',
                border:
                  data.temporalDependency.continuityStatus === 'PASS'
                    ? '1px solid rgba(16, 185, 129, 0.4)'
                    : data.temporalDependency.continuityStatus === 'WARNING'
                    ? '1px solid rgba(245, 158, 11, 0.4)'
                    : '1px solid rgba(239, 68, 68, 0.4)',
              }}
            >
              {data.temporalDependency.continuityStatus || 'PASS'}
            </span>
          </div>

          <div
            style={{
              display: 'grid',
              gridTemplateColumns: 'repeat(2, 1fr)',
              gap: '0.4rem',
              backgroundColor: 'rgba(2, 6, 23, 0.4)',
              padding: '0.45rem',
              borderRadius: '4px',
            }}
          >
            <div style={{ display: 'flex', flexDirection: 'column', gap: '0.1rem' }}>
              <span style={{ fontSize: '0.5625rem', color: '#64748b' }}>PREDECESSOR</span>
              <span style={{ fontSize: '0.6875rem', fontWeight: 600, color: '#e2e8f0' }} data-testid="spatial-inspector-predecessor">
                {data.temporalDependency.predecessorTitle || data.temporalDependency.predecessorId || 'None (Root Shot)'}
              </span>
            </div>

            <div style={{ display: 'flex', flexDirection: 'column', gap: '0.1rem' }}>
              <span style={{ fontSize: '0.5625rem', color: '#64748b' }}>ANCHOR</span>
              <span style={{ fontSize: '0.6875rem', fontWeight: 600, color: '#38bdf8' }}>
                {data.temporalDependency.anchorType || 'LAST FRAME'}
              </span>
            </div>

            <div style={{ display: 'flex', flexDirection: 'column', gap: '0.1rem' }}>
              <span style={{ fontSize: '0.5625rem', color: '#64748b' }}>ANCHOR STATUS</span>
              <span
                data-testid="spatial-inspector-anchor-status"
                style={{
                  display: 'inline-flex',
                  alignItems: 'center',
                  gap: '0.2rem',
                  fontSize: '0.625rem',
                  fontWeight: 700,
                  color: data.temporalDependency.anchorStatus === 'VERIFIED' ? '#10b981' : '#f59e0b',
                }}
              >
                {data.temporalDependency.anchorStatus === 'VERIFIED' ? '✓ VERIFIED' : data.temporalDependency.anchorStatus || 'PENDING'}
              </span>
            </div>

            <div style={{ display: 'flex', flexDirection: 'column', gap: '0.1rem' }}>
              <span style={{ fontSize: '0.5625rem', color: '#64748b' }}>CONDITIONING</span>
              <span style={{ fontSize: '0.6875rem', fontWeight: 600, color: '#fbbf24' }}>
                {data.temporalDependency.conditioningTarget || 'FIRST FRAME'}
              </span>
            </div>
          </div>

          {data.temporalDependency.sourceArtifactPath && (
            <div style={{ fontSize: '0.5625rem', color: '#94a3b8', display: 'flex', flexDirection: 'column', gap: '0.15rem' }}>
              <span style={{ color: '#64748b' }}>SOURCE ARTIFACT:</span>
              <span
                data-testid="spatial-inspector-source-artifact"
                style={{
                  color: '#38bdf8',
                  wordBreak: 'break-all',
                  fontFamily: 'monospace',
                }}
              >
                {data.temporalDependency.sourceArtifactPath.split('/').pop()}
              </span>
            </div>
          )}

          {data.temporalDependency.validationLevel && (
            <div style={{ fontSize: '0.5625rem', color: '#64748b' }}>
              LEVEL: <span style={{ color: '#a78bfa' }}>{data.temporalDependency.validationLevel}</span>
            </div>
          )}
        </div>
      )}

      {/* Formal Job Package Specification (Part F) */}
      {data.jobPackage && (
        <div
          data-testid="spatial-inspector-job-package"
          style={{
            display: 'flex',
            flexDirection: 'column',
            gap: '0.4rem',
            backgroundColor: 'rgba(6, 78, 59, 0.18)',
            border: '1px solid rgba(16, 185, 129, 0.4)',
            borderRadius: '6px',
            padding: '0.625rem',
          }}
        >
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '0.35rem' }}>
              <ShieldCheck size={13} color="#10b981" />
              <span style={{ fontSize: '0.625rem', color: '#34d399', fontWeight: 700, letterSpacing: '0.06em' }}>
                JOB PACKAGE BOUNDARY
              </span>
            </div>
            <span style={{ fontSize: '0.5625rem', color: '#6ee7b7' }}>[{data.jobPackage.jobPackageId.slice(0, 12)}]</span>
          </div>

          <div style={{ display: 'flex', flexDirection: 'column', gap: '0.2rem', fontSize: '0.625rem', color: '#cbd5e1' }}>
            <div>• <strong style={{ color: '#94a3b8' }}>Model Route:</strong> {data.jobPackage.modelRoute.provider.toUpperCase()} // {data.jobPackage.modelRoute.modelName}</div>
            <div>• <strong style={{ color: '#94a3b8' }}>Mode & Format:</strong> {data.jobPackage.plan.generationType.toUpperCase()} ({data.jobPackage.shotConfiguration.aspectRatio}) • {data.jobPackage.plan.durationSeconds || 5}s</div>
            <div>• <strong style={{ color: '#94a3b8' }}>Preflight Route:</strong> <span style={{ color: data.jobPackage.modelRoute.preflightReady ? '#10b981' : '#ef4444' }}>{data.jobPackage.modelRoute.preflightReady ? 'PASSED (READY)' : 'BLOCKED'}</span></div>
            <div>• <strong style={{ color: '#94a3b8' }}>Continuity Verified:</strong> Visual [{data.jobPackage.continuityRequirements.visual}], Temporal [{data.jobPackage.continuityRequirements.temporal}], StartFrame [{data.jobPackage.continuityRequirements.startFrame}]</div>
            <div>• <strong style={{ color: '#94a3b8' }}>Boundary Gate:</strong> {data.jobPackage.decisionBoundary}</div>
          </div>
        </div>
      )}

      {/* Action Buttons (e.g. Load in Creator Studio) */}
      {data.actionLabel && data.onAction && (
        <div style={{ display: 'flex', gap: '0.5rem', marginTop: '0.25rem' }}>
          <button
            type="button"
            data-testid="spatial-inspector-action-btn"
            onClick={data.onAction}
            style={{
              flex: 1,
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              gap: '0.35rem',
              backgroundColor: 'rgba(245, 158, 11, 0.14)',
              border: '1px solid rgba(245, 158, 11, 0.55)',
              color: '#fbbf24',
              borderRadius: '4px',
              padding: '0.5rem 0.75rem',
              fontSize: '0.6875rem',
              fontWeight: 700,
              fontFamily: 'inherit',
              letterSpacing: '0.06em',
              cursor: 'pointer',
              transition: 'all 0.15s ease',
            }}
            onMouseEnter={(e) => {
              e.currentTarget.style.backgroundColor = 'rgba(245, 158, 11, 0.25)';
              e.currentTarget.style.borderColor = 'rgba(245, 158, 11, 0.85)';
            }}
            onMouseLeave={(e) => {
              e.currentTarget.style.backgroundColor = 'rgba(245, 158, 11, 0.14)';
              e.currentTarget.style.borderColor = 'rgba(245, 158, 11, 0.55)';
            }}
          >
            <span>{data.actionLabel}</span>
          </button>

          {data.secondaryActionLabel && data.onSecondaryAction && (
            <button
              type="button"
              data-testid="spatial-inspector-secondary-btn"
              onClick={data.onSecondaryAction}
              style={{
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                gap: '0.35rem',
                backgroundColor: 'rgba(56, 189, 248, 0.1)',
                border: '1px solid rgba(56, 189, 248, 0.4)',
                color: '#38bdf8',
                borderRadius: '4px',
                padding: '0.5rem 0.65rem',
                fontSize: '0.6875rem',
                fontWeight: 600,
                fontFamily: 'inherit',
                cursor: 'pointer',
              }}
            >
              <span>{data.secondaryActionLabel}</span>
            </button>
          )}
        </div>
      )}

      {/* Provenance / Continuity Note */}
      {data.provenance && (
        <div
          style={{
            fontSize: '0.5625rem',
            color: '#64748b',
            borderTop: '1px solid rgba(255, 255, 255, 0.06)',
            paddingTop: '0.5rem',
            display: 'flex',
            alignItems: 'center',
            gap: '0.35rem',
          }}
        >
          <span style={{ color: '#f59e0b' }}>PROVENANCE:</span>
          <span>{data.provenance}</span>
        </div>
      )}
    </aside>
  );
};
