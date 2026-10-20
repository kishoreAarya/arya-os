import React, { useState, useEffect, useRef } from 'react';
import { Terminal, Sparkles, CheckCircle2, AlertTriangle, Play, Eye, ArrowRight, CornerDownLeft, Loader2 } from 'lucide-react';
import { AryaIntent, AryaIntentStage, AryaJobPackage } from '../../types/spatialIntent';

interface SpatialCommandBarProps {
  intentStage: AryaIntentStage;
  activeIntent?: AryaIntent | null;
  activeJobPackage?: AryaJobPackage | null;
  onSubmitCommand: (commandText: string) => void;
  onInspectJobPackage?: () => void;
  onDispatchExecution?: () => void;
  isDispatching?: boolean;
}

export const SpatialCommandBar: React.FC<SpatialCommandBarProps> = ({
  intentStage,
  activeIntent,
  activeJobPackage,
  onSubmitCommand,
  onInspectJobPackage,
  onDispatchExecution,
  isDispatching = false,
}) => {
  const [inputText, setInputText] = useState('');
  const [isFocused, setIsFocused] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  // Global keyboard shortcut '/' to focus command bar
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      // Avoid stealing focus if user is already typing in an input or textarea
      const target = e.target as HTMLElement;
      if (
        e.key === '/' &&
        target.tagName !== 'INPUT' &&
        target.tagName !== 'TEXTAREA' &&
        !target.isContentEditable
      ) {
        e.preventDefault();
        inputRef.current?.focus();
      }
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, []);

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!inputText.trim() || isDispatching) return;
    onSubmitCommand(inputText.trim());
  };

  // Preview directives detected in real-time as user types
  const lower = inputText.toLowerCase();
  const detectedDuration = lower.match(/(\d+)\s*(?:-?\s*sec|\s*s)\b/)?.[1];
  const detectedRatio = lower.includes('9:16') || lower.includes('vertical')
    ? '9:16'
    : lower.includes('1:1') || lower.includes('square')
    ? '1:1'
    : lower.includes('21:9') || lower.includes('ultrawide')
    ? '21:9'
    : '16:9';
  const detectedMode = lower.includes('image-to-video') || lower.includes('i2v')
    ? 'I2V'
    : /\b(image|still|photo|picture|render)\b/.test(lower) && !/\b(video|clip|shot)\b/.test(lower)
    ? 'IMAGE'
    : 'VIDEO';

  const stages: AryaIntentStage[] = ['INTENTION', 'ANALYZING', 'PLANNING', 'ROUTING', 'READY'];
  const currentStageIndex = stages.indexOf(intentStage);

  return (
    <div
      data-testid="spatial-command-bar-container"
      style={{
        position: 'relative',
        display: 'flex',
        flexDirection: 'column',
        gap: '0.4rem',
        width: '100%',
        maxWidth: '680px',
        margin: '0 auto',
        pointerEvents: 'auto',
        fontFamily: "'JetBrains Mono', monospace",
      }}
    >
      {/* 1. Main Command Input Envelope */}
      <form
        onSubmit={handleSubmit}
        data-testid="spatial-command-form"
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: '0.6rem',
          backgroundColor: isFocused ? 'rgba(15, 23, 42, 0.95)' : 'rgba(10, 16, 26, 0.88)',
          border: isFocused
            ? '1px solid rgba(56, 189, 248, 0.75)'
            : '1px solid rgba(255, 255, 255, 0.12)',
          borderRadius: '8px',
          padding: '0.55rem 0.85rem',
          backdropFilter: 'blur(16px)',
          boxShadow: isFocused
            ? '0 0 24px rgba(56, 189, 248, 0.25), 0 8px 32px rgba(0, 0, 0, 0.85)'
            : '0 4px 20px rgba(0, 0, 0, 0.65)',
          transition: 'all 0.2s cubic-bezier(0.16, 1, 0.3, 1)',
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.35rem', color: '#f59e0b' }}>
          <Terminal size={14} />
          <span style={{ fontSize: '0.6875rem', fontWeight: 700, letterSpacing: '0.08em' }}>
            INTENT //
          </span>
        </div>

        <input
          ref={inputRef}
          type="text"
          data-testid="spatial-command-input"
          value={inputText}
          onChange={(e) => setInputText(e.target.value)}
          onFocus={() => setIsFocused(true)}
          onBlur={() => setIsFocused(false)}
          placeholder="Enter command — What do you want AryaOS to create? (e.g. 'Cinematic keyframe of quantum monolith, 16:9') [ / ]"
          style={{
            flex: 1,
            background: 'transparent',
            border: 'none',
            outline: 'none',
            color: '#f8fafc',
            fontSize: '0.8125rem',
            fontFamily: 'inherit',
            letterSpacing: '0.02em',
          }}
        />

        {/* Live Detected Parameter Chips */}
        {inputText.length > 5 && (
          <div data-testid="spatial-command-chips" style={{ display: 'flex', alignItems: 'center', gap: '0.3rem' }}>
            <span
              style={{
                fontSize: '0.5625rem',
                padding: '2px 5px',
                borderRadius: '3px',
                backgroundColor: 'rgba(56, 189, 248, 0.15)',
                border: '1px solid rgba(56, 189, 248, 0.4)',
                color: '#38bdf8',
                fontWeight: 600,
              }}
            >
              {detectedMode}
            </span>
            <span
              style={{
                fontSize: '0.5625rem',
                padding: '2px 5px',
                borderRadius: '3px',
                backgroundColor: 'rgba(245, 158, 11, 0.15)',
                border: '1px solid rgba(245, 158, 11, 0.4)',
                color: '#fbbf24',
                fontWeight: 600,
              }}
            >
              {detectedRatio}
            </span>
            {detectedDuration && (
              <span
                style={{
                  fontSize: '0.5625rem',
                  padding: '2px 5px',
                  borderRadius: '3px',
                  backgroundColor: 'rgba(16, 185, 129, 0.15)',
                  border: '1px solid rgba(16, 185, 129, 0.4)',
                  color: '#10b981',
                  fontWeight: 600,
                }}
              >
                {detectedDuration}s
              </span>
            )}
          </div>
        )}

        <button
          type="submit"
          data-testid="spatial-command-submit"
          disabled={!inputText.trim() || isDispatching}
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: '0.3rem',
            backgroundColor: inputText.trim() ? 'rgba(245, 158, 11, 0.2)' : 'rgba(255, 255, 255, 0.05)',
            border: inputText.trim() ? '1px solid rgba(245, 158, 11, 0.6)' : '1px solid rgba(255, 255, 255, 0.1)',
            color: inputText.trim() ? '#fbbf24' : '#64748b',
            borderRadius: '4px',
            padding: '3px 8px',
            fontSize: '0.6875rem',
            fontWeight: 700,
            cursor: inputText.trim() ? 'pointer' : 'default',
            fontFamily: 'inherit',
            letterSpacing: '0.04em',
            transition: 'all 0.15s ease',
          }}
          title="Submit Command [Enter]"
        >
          <span>PLAN</span>
          <CornerDownLeft size={11} />
        </button>
      </form>

      {/* 2. Lifecycle Status & Actions Bar (Active during or after command submission) */}
      {intentStage !== 'IDLE' && (
        <div
          data-testid="spatial-command-lifecycle"
          style={{
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            gap: '0.75rem',
            backgroundColor: 'rgba(7, 10, 16, 0.88)',
            border: '1px solid rgba(245, 158, 11, 0.25)',
            borderRadius: '4px',
            padding: '0.35rem 0.65rem',
            backdropFilter: 'blur(8px)',
            fontSize: '0.625rem',
          }}
        >
          {/* Step Indicator */}
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
            <span style={{ color: '#64748b', fontWeight: 600 }}>LIFECYCLE:</span>
            {stages.map((stageName, idx) => {
              const isPast = currentStageIndex > idx;
              const isCurrent = currentStageIndex === idx;
              const isFuture = currentStageIndex < idx;

              let color = '#475569';
              if (isCurrent) color = '#fbbf24';
              else if (isPast) color = '#10b981';

              return (
                <React.Fragment key={stageName}>
                  <div
                    style={{
                      display: 'flex',
                      alignItems: 'center',
                      gap: '0.2rem',
                      color,
                      fontWeight: isCurrent ? 700 : 500,
                      letterSpacing: '0.06em',
                    }}
                  >
                    {isPast && <CheckCircle2 size={10} color="#10b981" />}
                    {isCurrent && (
                      <span
                        style={{
                          width: '6px',
                          height: '6px',
                          borderRadius: '50%',
                          backgroundColor: '#f59e0b',
                          boxShadow: '0 0 6px #f59e0b',
                        }}
                      />
                    )}
                    <span>{stageName}</span>
                  </div>
                  {idx < stages.length - 1 && <span style={{ color: '#334155' }}>→</span>}
                </React.Fragment>
              );
            })}
          </div>

          {/* Contextual Actions when READY or BLOCKED */}
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.4rem' }}>
            {(intentStage === 'READY' || intentStage === 'BLOCKED') && activeJobPackage && (
              <>
                {onInspectJobPackage && (
                  <button
                    type="button"
                    data-testid="spatial-command-inspect-pkg-btn"
                    onClick={onInspectJobPackage}
                    style={{
                      display: 'flex',
                      alignItems: 'center',
                      gap: '0.25rem',
                      backgroundColor: 'rgba(56, 189, 248, 0.12)',
                      border: '1px solid rgba(56, 189, 248, 0.45)',
                      color: '#38bdf8',
                      borderRadius: '3px',
                      padding: '2px 6px',
                      fontSize: '0.625rem',
                      fontWeight: 600,
                      cursor: 'pointer',
                      fontFamily: 'inherit',
                    }}
                  >
                    <Eye size={11} />
                    <span>JOB PACKAGE</span>
                  </button>
                )}

                {onDispatchExecution && (
                  <button
                    type="button"
                    data-testid="spatial-command-dispatch-btn"
                    onClick={onDispatchExecution}
                    disabled={isDispatching || !activeJobPackage.modelRoute.preflightReady}
                    style={{
                      display: 'flex',
                      alignItems: 'center',
                      gap: '0.25rem',
                      backgroundColor: activeJobPackage.modelRoute.preflightReady
                        ? 'rgba(16, 185, 129, 0.2)'
                        : 'rgba(239, 68, 68, 0.2)',
                      border: activeJobPackage.modelRoute.preflightReady
                        ? '1px solid rgba(16, 185, 129, 0.6)'
                        : '1px solid rgba(239, 68, 68, 0.6)',
                      color: activeJobPackage.modelRoute.preflightReady ? '#34d399' : '#f87171',
                      borderRadius: '3px',
                      padding: '2px 8px',
                      fontSize: '0.625rem',
                      fontWeight: 700,
                      cursor: activeJobPackage.modelRoute.preflightReady ? 'pointer' : 'not-allowed',
                      fontFamily: 'inherit',
                      letterSpacing: '0.04em',
                    }}
                    title={
                      activeJobPackage.modelRoute.preflightReady
                        ? 'Dispatch Job Package to Execution Chamber'
                        : `Preflight Blocked: ${activeJobPackage.modelRoute.preflightReasons.join(', ')}`
                    }
                  >
                    {isDispatching ? (
                      <>
                        <Loader2 size={11} className="spin" />
                        <span>DISPATCHING...</span>
                      </>
                    ) : (
                      <>
                        <Play size={11} />
                        <span>DISPATCH EXECUTION</span>
                      </>
                    )}
                  </button>
                )}
              </>
            )}

            {intentStage === 'BLOCKED' && (
              <div
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: '0.3rem',
                  color: '#ef4444',
                  fontWeight: 600,
                }}
              >
                <AlertTriangle size={11} />
                <span>{activeIntent?.activeBlocker?.reason || 'PLANNING BLOCKED'}</span>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
};
