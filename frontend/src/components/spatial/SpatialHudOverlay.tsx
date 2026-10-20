import React from 'react';
import {
  ArrowUpRight,
  Radio,
  Compass,
  Sparkles,
  Layers,
  Film,
  Cpu,
  Eye,
  Volume2,
  VolumeX,
  Keyboard,
} from 'lucide-react';
import { SpatialCameraState, SpatialHudOverlayProps, CAMERA_WAYPOINTS, SPATIAL_STAGES } from '../../types/spatial';
import { SpatialInspectorPanel } from './SpatialInspectorPanel';
import { SpatialCommandBar } from './SpatialCommandBar';

export const SpatialHudOverlay: React.FC<SpatialHudOverlayProps> = ({
  cameraState,
  activeStage,
  onSelectStage,
  spatialProgress,
  onProgressChange,
  onSelectCameraState,
  onOpenStudio,
  onOpenStudioWithShot,
  selectedModule,
  onSelectModule,
  selectedShot,
  corridorSummary,
  productionTelemetry,
  inspectorData,
  onCloseInspector,
  onInspectCore,
  focusTarget,
  isCinematicMode = false,
  onToggleCinematicMode,
  isAudioEnabled = false,
  onToggleAudio,
  isReducedMotion = false,
  onToggleReducedMotion,
  onOpenShortcuts,
  sequences,
  activeSequenceId,
  onSelectSequence,
  intentStage,
  activeIntent,
  activeJobPackage,
  onSubmitCommand,
  onInspectJobPackage,
  onDispatchExecution,
  isDispatching,
}) => {
  const currentWaypoint = (CAMERA_WAYPOINTS && CAMERA_WAYPOINTS[cameraState]) || {
    position: [0, 2.2, 5.8],
    target: [0, 2.0, 0],
    fov: 38,
    label: 'CORE COMMAND HUB',
    code: 'SEC-03',
    description: 'Focal workstation view of central quantum monolith',
    progress: 1.0,
  };
  const [posX, posY, posZ] = currentWaypoint.position;
  const isAwakening = activeStage === 'AWAKENING';

  if (isCinematicMode) {
    return (
      <div
        className="spatial-hud-root spatial-hud-cinematic"
        data-testid="spatial-hud-cinematic"
        style={{
          position: 'absolute',
          inset: 0,
          pointerEvents: 'none',
          zIndex: 20,
        }}
      >
        {onToggleCinematicMode && (
          <button
            type="button"
            data-testid="hud-exit-cinematic-btn"
            onClick={onToggleCinematicMode}
            style={{
              position: 'absolute',
              top: '16px',
              right: '16px',
              display: 'flex',
              alignItems: 'center',
              gap: '0.4rem',
              backgroundColor: 'rgba(7, 10, 16, 0.88)',
              border: '1px solid rgba(245, 158, 11, 0.55)',
              color: '#fbbf24',
              padding: '6px 12px',
              borderRadius: '4px',
              fontSize: '0.6875rem',
              fontFamily: "'JetBrains Mono', monospace",
              fontWeight: 600,
              cursor: 'pointer',
              pointerEvents: 'auto',
              backdropFilter: 'blur(8px)',
              boxShadow: '0 4px 20px rgba(0, 0, 0, 0.75)',
              letterSpacing: '0.06em',
            }}
            title="Exit Cinematic Mode [H]"
          >
            <Eye size={13} color="#f59e0b" />
            <span>RESTORE HUD [H]</span>
          </button>
        )}
      </div>
    );
  }

  return (
    <div
      className="spatial-hud-root"
      style={{
        position: 'absolute',
        inset: 0,
        pointerEvents: 'none',
        zIndex: 20,
        display: 'flex',
        flexDirection: 'column',
        justifyContent: 'space-between',
        padding: '1.25rem 1.5rem',
        fontFamily: "'JetBrains Mono', monospace",
        color: '#94a3b8',
      }}
    >
      {/* Precision Corner Reticles */}
      <div
        style={{
          position: 'absolute',
          top: '16px',
          left: '16px',
          width: '18px',
          height: '18px',
          borderTop: '1px solid rgba(245, 158, 11, 0.45)',
          borderLeft: '1px solid rgba(245, 158, 11, 0.45)',
        }}
      />
      <div
        style={{
          position: 'absolute',
          top: '16px',
          right: '16px',
          width: '18px',
          height: '18px',
          borderTop: '1px solid rgba(245, 158, 11, 0.45)',
          borderRight: '1px solid rgba(245, 158, 11, 0.45)',
        }}
      />
      <div
        style={{
          position: 'absolute',
          bottom: '16px',
          left: '16px',
          width: '18px',
          height: '18px',
          borderBottom: '1px solid rgba(245, 158, 11, 0.45)',
          borderLeft: '1px solid rgba(245, 158, 11, 0.45)',
        }}
      />
      <div
        style={{
          position: 'absolute',
          bottom: '16px',
          right: '16px',
          width: '18px',
          height: '18px',
          borderBottom: '1px solid rgba(245, 158, 11, 0.45)',
          borderRight: '1px solid rgba(245, 158, 11, 0.45)',
        }}
      />

      {/* TOP HUD BAR */}
      <div
        className="spatial-top-header"
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          gap: '1rem',
          flexWrap: 'wrap',
          backgroundColor: 'rgba(7, 10, 16, 0.88)',
          border: '1px solid rgba(255, 255, 255, 0.08)',
          borderRadius: '8px',
          padding: '0.625rem 1rem',
          backdropFilter: 'blur(16px)',
          boxShadow: '0 8px 32px rgba(0, 0, 0, 0.75)',
          opacity: isAwakening ? 0 : 1,
          pointerEvents: isAwakening ? 'none' : 'auto',
          transition: 'opacity 0.3s ease',
        }}
      >
        {/* System Identity & Telemetry */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: '0.35rem' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.625rem' }}>
            <span
              style={{
                fontSize: '0.875rem',
                fontWeight: 700,
                letterSpacing: '0.12em',
                color: '#f8fafc',
                textShadow: '0 0 12px rgba(255, 255, 255, 0.15)',
              }}
            >
              ARYAOS // SPATIAL OS
            </span>
            <span
              style={{
                fontSize: '0.625rem',
                padding: '2px 6px',
                borderRadius: '3px',
                backgroundColor: 'rgba(245, 158, 11, 0.14)',
                color: '#fbbf24',
                border: '1px solid rgba(245, 158, 11, 0.4)',
                fontWeight: 600,
                letterSpacing: '0.08em',
              }}
            >
              CORE V1
            </span>
            <div style={{ display: 'flex', alignItems: 'center', gap: '0.35rem', fontSize: '0.6875rem' }}>
              <span
                style={{
                  width: '6px',
                  height: '6px',
                  borderRadius: '50%',
                  backgroundColor: '#f59e0b',
                  boxShadow: '0 0 8px rgba(245, 158, 11, 0.9)',
                  display: 'inline-block',
                }}
              />
              <span style={{ color: '#cbd5e1', fontWeight: 500 }}>STATUS: ONLINE</span>
            </div>
            <span style={{ color: '#334155' }}>|</span>
            <span style={{ fontSize: '0.6875rem', color: '#64748b' }}>FREQ: 4.8 THz</span>
            <span style={{ color: '#334155' }}>|</span>
            <span style={{ fontSize: '0.6875rem', color: '#64748b' }}>SECTOR: 01-ALPHA</span>
          </div>

          {/* Phase 4 & 9 Live Production Intelligence Telemetry Strip */}
          <div
            data-testid="hud-production-telemetry"
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: '0.5rem',
              fontSize: '0.625rem',
              color: '#94a3b8',
              flexWrap: 'wrap',
              backgroundColor: 'rgba(15, 23, 42, 0.65)',
              padding: '3px 8px',
              borderRadius: '4px',
              border: '1px solid rgba(255, 255, 255, 0.05)',
            }}
          >
            <span>
              PROJECT: <strong style={{ color: '#e2e8f0', letterSpacing: '0.02em' }}>{productionTelemetry?.activeProjectTitle || 'DEFAULT PROJECT'}</strong>
            </span>
            <span style={{ color: '#334155' }}>|</span>
            <span>
              ROUTE: <span style={{ color: '#fbbf24', fontWeight: 600 }}>{productionTelemetry?.activeProvider ? `${productionTelemetry.activeProvider} / ${productionTelemetry.activeModel}` : '--'}</span>
            </span>
            <span style={{ color: '#334155' }}>|</span>
            <span>
              EXECUTION: <span style={{ color: productionTelemetry?.executionStatus === 'RUNNING' || productionTelemetry?.executionStatus === 'PROCESSING' ? '#10b981' : productionTelemetry?.executionStatus === 'FAILED' ? '#ef4444' : '#38bdf8', fontWeight: 600 }}>{productionTelemetry?.executionStatus || 'NO ACTIVE RUN'}</span>
            </span>
            {productionTelemetry?.productionProgress && productionTelemetry.productionProgress !== '--' && (
              <>
                <span style={{ color: '#334155' }}>|</span>
                <span>
                  PROGRESS: <span style={{ color: '#38bdf8', fontWeight: 600 }}>{productionTelemetry.productionProgress}</span>
                </span>
              </>
            )}
            {productionTelemetry?.lastEvent && (
              <>
                <span style={{ color: '#334155' }}>|</span>
                <span>
                  EVENT: <span style={{ color: '#cbd5e1' }}>{productionTelemetry.lastEvent}</span>
                </span>
              </>
            )}
          </div>
        </div>

        {/* Navigation & Controls */}
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: '0.625rem',
            pointerEvents: 'auto',
            flexWrap: 'wrap',
          }}
        >
          {/* Inspect Core Button */}
          {onInspectCore && (
            <button
              type="button"
              data-testid="hud-inspect-core-btn"
              onClick={onInspectCore}
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: '0.35rem',
                backgroundColor: 'rgba(245, 158, 11, 0.1)',
                border: '1px solid rgba(245, 158, 11, 0.45)',
                color: '#fbbf24',
                padding: '4px 8px',
                borderRadius: '4px',
                fontSize: '0.6875rem',
                fontFamily: 'inherit',
                cursor: 'pointer',
                letterSpacing: '0.05em',
                transition: 'all 0.15s ease',
              }}
              title="Inspect Central ARYAOS Core"
            >
              <Cpu size={12} color="#f59e0b" />
              <span>CORE INSPECTOR</span>
            </button>
          )}

          {/* Multi-Sequence Selector */}
          {sequences && sequences.length > 1 && onSelectSequence && (
            <div
              data-testid="hud-sequence-selector"
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: '2px',
                backgroundColor: 'rgba(7, 10, 16, 0.85)',
                padding: '3px',
                borderRadius: '4px',
                border: '1px solid rgba(56, 189, 248, 0.25)',
                backdropFilter: 'blur(8px)',
              }}
            >
              <span style={{ fontSize: '0.625rem', color: '#38bdf8', padding: '0 4px', fontWeight: 700 }}>
                SEQ:
              </span>
              {sequences.map((seq) => {
                const isSelectedSeq = seq.id === activeSequenceId;
                return (
                  <button
                    key={seq.id}
                    type="button"
                    data-testid={`hud-seq-btn-${seq.id}`}
                    onClick={() => onSelectSequence(seq.id)}
                    style={{
                      backgroundColor: isSelectedSeq ? 'rgba(56, 189, 248, 0.18)' : 'transparent',
                      border: isSelectedSeq ? '1px solid #38bdf8' : '1px solid transparent',
                      color: isSelectedSeq ? '#38bdf8' : '#64748b',
                      padding: '3px 6px',
                      borderRadius: '3px',
                      fontSize: '0.625rem',
                      fontFamily: 'inherit',
                      cursor: 'pointer',
                      letterSpacing: '0.04em',
                    }}
                  >
                    0{seq.order} // {seq.title.replace(/^Sequence \d+ \/\/\s*/i, '')}
                  </button>
                );
              })}
            </div>
          )}

          {/* Waypoint Selectors: ENTRY, APPROACH, HUB, SYSTEMS, CORRIDOR, COMMAND */}
          <div
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: '2px',
              backgroundColor: 'rgba(7, 10, 16, 0.85)',
              padding: '3px',
              borderRadius: '4px',
              border: '1px solid rgba(255, 255, 255, 0.08)',
              backdropFilter: 'blur(8px)',
              flexWrap: 'wrap',
            }}
          >
            {(['ENTRY', 'APPROACH', 'HUB', 'SYSTEMS', 'CORRIDOR', 'COMMAND'] as SpatialCameraState[]).map(
              (stateKey, idx) => {
                const isCurrent = cameraState === stateKey;
                return (
                  <button
                    key={stateKey}
                    type="button"
                    onClick={() => onSelectCameraState(stateKey)}
                    style={{
                      backgroundColor: isCurrent ? 'rgba(245, 158, 11, 0.16)' : 'transparent',
                      border: isCurrent ? '1px solid rgba(245, 158, 11, 0.5)' : '1px solid transparent',
                      color: isCurrent ? '#fbbf24' : '#64748b',
                      padding: '4px 8px',
                      borderRadius: '3px',
                      fontSize: '0.6875rem',
                      fontFamily: 'inherit',
                      cursor: 'pointer',
                      letterSpacing: '0.05em',
                      transition: 'all 0.15s ease',
                    }}
                    title={`Switch to ${stateKey} viewpoint`}
                  >
                    0{idx + 1} // {stateKey}
                  </button>
                );
              }
            )}
          </div>

          {/* Audio Feedback Toggle */}
          {onToggleAudio && (
            <button
              type="button"
              data-testid="hud-toggle-audio-btn"
              onClick={onToggleAudio}
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: '0.3rem',
                backgroundColor: isAudioEnabled ? 'rgba(245, 158, 11, 0.14)' : 'rgba(7, 10, 16, 0.85)',
                border: isAudioEnabled ? '1px solid rgba(245, 158, 11, 0.5)' : '1px solid rgba(255, 255, 255, 0.08)',
                color: isAudioEnabled ? '#fbbf24' : '#64748b',
                padding: '4px 8px',
                borderRadius: '4px',
                fontSize: '0.6875rem',
                fontFamily: 'inherit',
                cursor: 'pointer',
                letterSpacing: '0.04em',
                transition: 'all 0.15s ease',
              }}
              title="Toggle Cybernetic Audio Feedback"
            >
              {isAudioEnabled ? <Volume2 size={12} color="#fbbf24" /> : <VolumeX size={12} color="#64748b" />}
              <span>{isAudioEnabled ? 'AUDIO ON' : 'AUDIO OFF'}</span>
            </button>
          )}

          {/* Cinematic Mode Toggle */}
          {onToggleCinematicMode && (
            <button
              type="button"
              data-testid="hud-toggle-cinematic-btn"
              onClick={onToggleCinematicMode}
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: '0.3rem',
                backgroundColor: 'rgba(7, 10, 16, 0.85)',
                border: '1px solid rgba(255, 255, 255, 0.08)',
                color: '#94a3b8',
                padding: '4px 8px',
                borderRadius: '4px',
                fontSize: '0.6875rem',
                fontFamily: 'inherit',
                cursor: 'pointer',
                letterSpacing: '0.04em',
                transition: 'all 0.15s ease',
              }}
              title="Toggle Cinematic Mode (Hide HUD) [H]"
            >
              <Eye size={12} color="#94a3b8" />
              <span>CINEMATIC [H]</span>
            </button>
          )}

          {/* Shortcuts Guide Button */}
          {onOpenShortcuts && (
            <button
              type="button"
              data-testid="hud-shortcuts-btn"
              onClick={onOpenShortcuts}
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: '0.25rem',
                backgroundColor: 'rgba(7, 10, 16, 0.85)',
                border: '1px solid rgba(255, 255, 255, 0.08)',
                color: '#94a3b8',
                padding: '4px 8px',
                borderRadius: '4px',
                fontSize: '0.6875rem',
                fontFamily: 'inherit',
                cursor: 'pointer',
                letterSpacing: '0.04em',
                transition: 'all 0.15s ease',
              }}
              title="View Keyboard Operator Matrix [?]"
            >
              <Keyboard size={12} color="#94a3b8" />
              <span>[?]</span>
            </button>
          )}

          {/* Action: Open Creator Studio */}
          {onOpenStudio && (
            <button
              type="button"
              onClick={onOpenStudio}
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: '0.375rem',
                backgroundColor: 'rgba(245, 158, 11, 0.12)',
                border: '1px solid rgba(245, 158, 11, 0.45)',
                color: '#fbbf24',
                padding: '5px 12px',
                borderRadius: '4px',
                fontSize: '0.75rem',
                fontFamily: 'inherit',
                fontWeight: 600,
                cursor: 'pointer',
                letterSpacing: '0.06em',
                boxShadow: '0 2px 10px rgba(0, 0, 0, 0.5)',
                transition: 'all 0.15s ease',
              }}
              onMouseEnter={(e) => {
                e.currentTarget.style.backgroundColor = 'rgba(245, 158, 11, 0.22)';
                e.currentTarget.style.borderColor = 'rgba(245, 158, 11, 0.8)';
              }}
              onMouseLeave={(e) => {
                e.currentTarget.style.backgroundColor = 'rgba(245, 158, 11, 0.12)';
                e.currentTarget.style.borderColor = 'rgba(245, 158, 11, 0.45)';
              }}
            >
              <Sparkles size={13} color="#fbbf24" />
              <span>ENTER CREATOR STUDIO</span>
              <ArrowUpRight size={13} />
            </button>
          )}
        </div>
      </div>

      {/* 9-STAGE PROGRESSIVE SPATIAL DISCOVERY NAVIGATOR (Reference Architecture) */}
      <div
        data-testid="spatial-stage-navigator"
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          gap: '4px',
          marginTop: '0.65rem',
          flexWrap: 'wrap',
          pointerEvents: 'auto',
        }}
      >
        {SPATIAL_STAGES.map((stg) => {
          const isCurrent = activeStage === stg.id || cameraState === stg.cameraState;
          return (
            <button
              key={stg.id}
              type="button"
              data-testid={`stage-nav-${stg.id}`}
              data-stage-btn={`spatial-stage-btn-${stg.id}`}
              onClick={() => {
                onSelectCameraState(stg.cameraState);
                onSelectStage?.(stg.id);
                onProgressChange?.(stg.progress);
              }}
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: '0.28rem',
                backgroundColor: isCurrent ? 'rgba(245, 158, 11, 0.2)' : 'rgba(7, 10, 16, 0.75)',
                border: isCurrent ? '1px solid #f59e0b' : '1px solid rgba(255, 255, 255, 0.08)',
                color: isCurrent ? '#fbbf24' : '#64748b',
                padding: '3px 8px',
                borderRadius: '4px',
                fontSize: '0.625rem',
                fontFamily: 'inherit',
                fontWeight: isCurrent ? 700 : 500,
                cursor: 'pointer',
                letterSpacing: '0.05em',
                transition: 'all 0.15s ease',
                backdropFilter: 'blur(8px)',
              }}
              title={`Stage 0${stg.stage}: ${stg.label} — ${stg.description}`}
            >
              <span style={{ color: isCurrent ? '#fbbf24' : '#94a3b8', fontWeight: 700 }}>
                0{stg.stage}
              </span>
              <span>{stg.label}</span>
            </button>
          );
        })}
      </div>

      {/* ARYAOS COMMAND BAR (Phase 7 Functional Control Layer) */}
      {onSubmitCommand && (
        <div
          style={{
            marginTop: '0.65rem',
            width: '100%',
            display: 'flex',
            justifyContent: 'center',
            opacity: isAwakening ? 0 : 1,
            pointerEvents: isAwakening ? 'none' : 'auto',
            transition: 'opacity 0.3s ease',
          }}
        >
          <SpatialCommandBar
            intentStage={intentStage || 'IDLE'}
            activeIntent={activeIntent}
            activeJobPackage={activeJobPackage}
            onSubmitCommand={onSubmitCommand}
            onInspectJobPackage={onInspectJobPackage}
            onDispatchExecution={onDispatchExecution}
            isDispatching={isDispatching}
          />
        </div>
      )}

      {/* FLOATING SUB-PANEL: Active Module & Shot Telemetry */}
      <div
        style={{
          display: 'flex',
          flexDirection: 'column',
          gap: '0.75rem',
          maxWidth: '380px',
          marginTop: '1rem',
          pointerEvents: isAwakening ? 'none' : 'auto',
          opacity: isAwakening ? 0 : 1,
          transition: 'opacity 0.3s ease',
        }}
      >
        {/* Selected System Module Card */}
        {selectedModule && (
          <div
            data-testid="hud-selected-module"
            style={{
              backgroundColor: 'rgba(7, 10, 16, 0.88)',
              border: '1px solid rgba(245, 158, 11, 0.45)',
              borderRadius: '6px',
              padding: '0.625rem 0.875rem',
              backdropFilter: 'blur(8px)',
              boxShadow: '0 4px 20px rgba(0, 0, 0, 0.6)',
              display: 'flex',
              flexDirection: 'column',
              gap: '0.35rem',
            }}
          >
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '0.35rem' }}>
                <Layers size={13} color="#f59e0b" />
                <span
                  style={{
                    color: '#fbbf24',
                    fontWeight: 700,
                    fontSize: '0.75rem',
                    letterSpacing: '0.08em',
                  }}
                >
                  SUBSYSTEM // {selectedModule.name}
                </span>
              </div>
              <span style={{ fontSize: '0.625rem', color: '#64748b' }}>[{selectedModule.code}]</span>
            </div>
            <div style={{ fontSize: '0.6875rem', color: '#cbd5e1' }}>{selectedModule.title}</div>
            <div
              style={{
                fontSize: '0.625rem',
                color: '#94a3b8',
                display: 'flex',
                gap: '0.5rem',
                alignItems: 'center',
              }}
            >
              <span style={{ color: '#10b981' }}>STATUS: {selectedModule.telemetry.status}</span>
              <span>|</span>
              <span>LOAD: {selectedModule.telemetry.loadPercent}%</span>
              <span>|</span>
              <span>LATENCY: {selectedModule.telemetry.latencyMs}ms</span>
            </div>
            <div style={{ fontSize: '0.625rem', color: '#64748b', fontStyle: 'italic' }}>
              {selectedModule.telemetry.detail}
            </div>
          </div>
        )}

        {/* Selected Shot Card */}
        {selectedShot && (
          <div
            data-testid="hud-selected-shot"
            style={{
              backgroundColor: 'rgba(7, 10, 16, 0.88)',
              border: '1px solid rgba(56, 189, 248, 0.45)',
              borderRadius: '6px',
              padding: '0.625rem 0.875rem',
              backdropFilter: 'blur(8px)',
              boxShadow: '0 4px 20px rgba(0, 0, 0, 0.6)',
              display: 'flex',
              flexDirection: 'column',
              gap: '0.35rem',
            }}
          >
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '0.35rem' }}>
                <Film size={13} color="#38bdf8" />
                <span
                  style={{
                    color: '#38bdf8',
                    fontWeight: 700,
                    fontSize: '0.75rem',
                    letterSpacing: '0.08em',
                  }}
                >
                  CORRIDOR SHOT // {String(selectedShot.order).padStart(2, '0')}
                </span>
              </div>
              <span
                style={{
                  fontSize: '0.625rem',
                  color: selectedShot.status === 'COMPLETE' ? '#10b981' : '#f59e0b',
                }}
              >
                [{selectedShot.status}]
              </span>
            </div>
            <div style={{ fontSize: '0.6875rem', color: '#cbd5e1' }}>{selectedShot.title}</div>
            <div
              style={{
                fontSize: '0.625rem',
                color: '#94a3b8',
                display: 'flex',
                gap: '0.5rem',
                alignItems: 'center',
              }}
            >
              <span>TYPE: {selectedShot.generationType.toUpperCase()}</span>
              <span>|</span>
              <span>DURATION: {selectedShot.duration || 5}s</span>
              <span>|</span>
              <span
                style={{
                  color:
                    selectedShot.continuityStatus === 'PASS'
                      ? '#38bdf8'
                      : selectedShot.continuityStatus === 'WARNING'
                      ? '#f59e0b'
                      : '#ef4444',
                }}
              >
                CONTINUITY: {selectedShot.continuityStatus || 'PASS'}
              </span>
            </div>

            {/* Direct Studio Integration */}
            {onOpenStudioWithShot && (
              <button
                type="button"
                data-testid="hud-shot-open-studio-btn"
                onClick={() => onOpenStudioWithShot(selectedShot)}
                style={{
                  alignSelf: 'flex-start',
                  marginTop: '0.35rem',
                  display: 'flex',
                  alignItems: 'center',
                  gap: '0.3rem',
                  backgroundColor: 'rgba(56, 189, 248, 0.12)',
                  border: '1px solid rgba(56, 189, 248, 0.45)',
                  color: '#38bdf8',
                  borderRadius: '4px',
                  padding: '3px 8px',
                  fontSize: '0.625rem',
                  fontWeight: 700,
                  cursor: 'pointer',
                  fontFamily: 'inherit',
                  letterSpacing: '0.04em',
                }}
                title={`Open Shot ${selectedShot.order} in Creator Studio`}
              >
                <Sparkles size={11} />
                <span>LOAD IN STUDIO</span>
              </button>
            )}
          </div>
        )}
      </div>

      {/* SELECTION INSPECTOR PANEL (Docked Right) */}
      {inspectorData && onCloseInspector && (
        <div
          style={{
            position: 'absolute',
            top: '75px',
            right: '20px',
            pointerEvents: 'auto',
            zIndex: 35,
          }}
        >
          <SpatialInspectorPanel
            data={inspectorData}
            onClose={onCloseInspector}
          />
        </div>
      )}

      {/* CENTER CROSSHAIR RETICLE (Restrained / Minimal) */}
      <div
        style={{
          position: 'absolute',
          top: '50%',
          left: '50%',
          transform: 'translate(-50%, -50%)',
          width: '32px',
          height: '32px',
          pointerEvents: 'none',
          opacity: 0.14,
        }}
      >
        <div
          style={{
            position: 'absolute',
            top: 0,
            bottom: 0,
            left: '50%',
            width: '1px',
            background: '#f59e0b',
          }}
        />
        <div
          style={{
            position: 'absolute',
            left: 0,
            right: 0,
            top: '50%',
            height: '1px',
            background: '#f59e0b',
          }}
        />
      </div>

      {/* BOTTOM HUD BAR */}
      <div
        data-testid="hud-bottom-bar"
        className="spatial-bottom-bar"
        style={{
          display: 'flex',
          alignItems: 'flex-end',
          justifyContent: 'space-between',
          fontSize: '0.6875rem',
          color: '#64748b',
          flexWrap: 'wrap',
          gap: '0.75rem',
          opacity: isAwakening ? 0 : 1,
          pointerEvents: isAwakening ? 'none' : 'auto',
          transition: 'opacity 0.3s ease',
        }}
      >
        {/* Active Waypoint Coordinates & Corridor Summary */}
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem', flexWrap: 'wrap' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.35rem' }}>
            <Compass size={12} color="#f59e0b" />
            <span style={{ color: '#cbd5e1' }}>
              STATION: {currentWaypoint.label} [{currentWaypoint.code}]
            </span>
          </div>
          <span>|</span>
          <span>
            COORD: X:{posX.toFixed(2)} Y:{posY.toFixed(2)} Z:{posZ.toFixed(2)}
          </span>
          <span>|</span>
          <span>FOV: {currentWaypoint.fov}°</span>
          {spatialProgress !== undefined && (
            <>
              <span>|</span>
              <span style={{ color: '#fbbf24' }}>
                PROGRESS: {(spatialProgress * 100).toFixed(0)}%
              </span>
            </>
          )}
          {corridorSummary && (
            <>
              <span>|</span>
              <span style={{ color: '#38bdf8' }}>
                CORRIDOR: {corridorSummary.totalShots} SHOTS [{corridorSummary.continuityStatus}]
              </span>
            </>
          )}
          {onToggleReducedMotion && (
            <>
              <span>|</span>
              <button
                type="button"
                data-testid="hud-toggle-motion-btn"
                onClick={onToggleReducedMotion}
                style={{
                  background: 'transparent',
                  border: '1px solid rgba(255, 255, 255, 0.1)',
                  borderRadius: '3px',
                  color: isReducedMotion ? '#f59e0b' : '#64748b',
                  fontSize: '0.625rem',
                  padding: '2px 6px',
                  cursor: 'pointer',
                  fontFamily: 'inherit',
                  letterSpacing: '0.04em',
                }}
                title="Toggle Damped Smooth Camera vs Snapped Motion"
              >
                MOTION: {isReducedMotion ? 'SNAPPED' : 'DAMPED'}
              </button>
            </>
          )}
          <span>|</span>
          <span style={{ color: '#10b981', fontSize: '0.625rem' }}>RENDER: 60 FPS // PBR</span>
        </div>

        {/* Operational Guidance */}
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', opacity: 0.8 }}>
          <Radio size={12} color="#f59e0b" />
          <span>[1-6] STATIONS • [C] STUDIO • [H] CINEMATIC • [I] CORE • [M] MODULES • [?] SHORTCUTS</span>
        </div>
      </div>
    </div>
  );
};
