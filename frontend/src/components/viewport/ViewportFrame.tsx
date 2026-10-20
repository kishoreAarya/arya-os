import React from 'react';
import { usePrefersReducedMotion } from '../motion/MotionSystem';

export interface ViewportFrameProps {
  children: React.ReactNode;
  zoomMode: 'fit' | 'actual';
  isFullscreen: boolean;
  isLoading?: boolean;
  hasMedia?: boolean;
}

export const ViewportFrame: React.FC<ViewportFrameProps> = ({
  children,
  zoomMode,
  isFullscreen,
  isLoading = false,
  hasMedia = false,
}) => {
  const isReducedMotion = usePrefersReducedMotion();

  return (
    <div
      style={{
        flex: 1,
        minHeight: isFullscreen ? '100vh' : 'clamp(340px, 38vh, 560px)',
        maxHeight: isFullscreen ? '100vh' : '580px',
        backgroundColor: '#04060a',
        borderRadius: isFullscreen ? '0' : 'var(--radius-md)',
        border: isFullscreen ? 'none' : '1px solid var(--border-color)',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        overflow: zoomMode === 'actual' ? 'auto' : 'hidden',
        position: isFullscreen ? 'fixed' : 'relative',
        inset: isFullscreen ? 0 : undefined,
        zIndex: isFullscreen ? 999 : 1,
        boxShadow: isFullscreen
          ? 'none'
          : 'inset 0 2px 24px rgba(0, 0, 0, 0.85), 0 10px 32px rgba(0, 0, 0, 0.5)',
        transition: isReducedMotion ? 'none' : 'border-color 0.25s ease, box-shadow 0.25s ease',
      }}
    >
      {/* Precision Technical Corner Reticles (Cinema Monitor Framing) */}
      <div
        aria-hidden="true"
        style={{
          position: 'absolute',
          top: '10px',
          left: '10px',
          width: '16px',
          height: '16px',
          borderTop: '1.5px solid rgba(59, 130, 246, 0.45)',
          borderLeft: '1.5px solid rgba(59, 130, 246, 0.45)',
          pointerEvents: 'none',
          zIndex: 3,
        }}
      />
      <div
        aria-hidden="true"
        style={{
          position: 'absolute',
          top: '10px',
          right: '10px',
          width: '16px',
          height: '16px',
          borderTop: '1.5px solid rgba(59, 130, 246, 0.45)',
          borderRight: '1.5px solid rgba(59, 130, 246, 0.45)',
          pointerEvents: 'none',
          zIndex: 3,
        }}
      />
      <div
        aria-hidden="true"
        style={{
          position: 'absolute',
          bottom: '10px',
          left: '10px',
          width: '16px',
          height: '16px',
          borderBottom: '1.5px solid rgba(59, 130, 246, 0.45)',
          borderLeft: '1.5px solid rgba(59, 130, 246, 0.45)',
          pointerEvents: 'none',
          zIndex: 3,
        }}
      />
      <div
        aria-hidden="true"
        style={{
          position: 'absolute',
          bottom: '10px',
          right: '10px',
          width: '16px',
          height: '16px',
          borderBottom: '1.5px solid rgba(59, 130, 246, 0.45)',
          borderRight: '1.5px solid rgba(59, 130, 246, 0.45)',
          pointerEvents: 'none',
          zIndex: 3,
        }}
      />

      {/* Subtle Technical Monitor Tag */}
      <div
        aria-hidden="true"
        style={{
          position: 'absolute',
          top: '12px',
          left: '32px',
          fontSize: '0.625rem',
          fontWeight: 600,
          letterSpacing: '0.12em',
          color: 'var(--text-muted)',
          opacity: 0.35,
          textTransform: 'uppercase',
          pointerEvents: 'none',
          zIndex: 3,
          fontFamily: 'monospace',
          userSelect: 'none',
        }}
      >
        MONITOR // REC.709
      </div>

      {/* Center Reticle Crosshairs (Rendered ONLY in empty state to never cover media) */}
      {!hasMedia && (
        <div
          aria-hidden="true"
          style={{
            position: 'absolute',
            top: '50%',
            left: '50%',
            transform: 'translate(-50%, -50%)',
            width: '28px',
            height: '28px',
            pointerEvents: 'none',
            opacity: 0.18,
            zIndex: 2,
          }}
        >
          <div
            style={{
              position: 'absolute',
              top: 0,
              bottom: 0,
              left: '50%',
              width: '1px',
              background: 'var(--accent-primary)',
            }}
          />
          <div
            style={{
              position: 'absolute',
              left: 0,
              right: 0,
              top: '50%',
              height: '1px',
              background: 'var(--accent-primary)',
            }}
          />
        </div>
      )}

      {/* Synthesis Scan Line — Active ONLY during generation / synthesis */}
      {isLoading && (
        <div
          aria-hidden="true"
          style={{
            position: 'absolute',
            inset: 0,
            background:
              'linear-gradient(180deg, transparent 0%, rgba(59, 130, 246, 0.12) 50%, transparent 100%)',
            pointerEvents: 'none',
            zIndex: 4,
            animation: isReducedMotion ? 'none' : 'scanSweep 2.2s ease-in-out infinite',
          }}
        />
      )}

      {/* Inner Cinema Perimeter Vignette */}
      <div
        aria-hidden="true"
        style={{
          position: 'absolute',
          inset: 0,
          boxShadow: 'inset 0 0 50px rgba(0, 0, 0, 0.7)',
          pointerEvents: 'none',
          zIndex: 2,
        }}
      />

      {children}
    </div>
  );
};

