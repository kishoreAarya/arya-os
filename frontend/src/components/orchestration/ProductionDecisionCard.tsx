import React, { useState } from 'react';
import {
  Cpu,
  CheckCircle2,
  AlertCircle,
  AlertTriangle,
  DollarSign,
  Award,
  ChevronDown,
  ChevronUp,
  ShieldCheck,
  Send,
  FileText,
} from 'lucide-react';
import { ProductionRecommendation } from '../../types/productionDecision';

interface ProductionDecisionCardProps {
  recommendation: ProductionRecommendation;
}

export const ProductionDecisionCard: React.FC<ProductionDecisionCardProps> = ({ recommendation }) => {
  const [showEvidence, setShowEvidence] = useState<boolean>(true);
  const { status, directive, reason, reasons, reasonCode, explanation, categorization, preflightSummary, executionPreview } =
    recommendation;

  const isReady = status === 'READY';
  const isBlocked = status === 'BLOCKED';
  const isWarning = status === 'WARNING';

  // Badge styling: Amber for blocked/warning configuration guidance (strictly non-red), Cyan for ready
  const badgeStyle: React.CSSProperties = isBlocked || isWarning
    ? {
        backgroundColor: 'rgba(245, 158, 11, 0.12)',
        border: '1px solid rgba(245, 158, 11, 0.35)',
        color: '#fbbf24',
      }
    : {
        backgroundColor: 'rgba(56, 189, 248, 0.12)',
        border: '1px solid rgba(56, 189, 248, 0.35)',
        color: '#38bdf8',
      };

  const badgeLabel = isBlocked
    ? 'CONFIGURATION BLOCKED'
    : isWarning
    ? 'CONFIGURATION WARNING'
    : 'CONFIGURATION READY';

  return (
    <div
      className="production-decision-card"
      data-testid="decision-explanation-card"
      style={{
        marginTop: '1rem',
        marginBottom: '1rem',
        padding: '0.875rem 1rem',
        backgroundColor: 'rgba(15, 23, 42, 0.75)',
        background: 'linear-gradient(180deg, rgba(17, 24, 39, 0.85) 0%, rgba(11, 16, 26, 0.95) 100%)',
        border: `1px solid ${isBlocked ? 'rgba(245, 158, 11, 0.28)' : 'rgba(59, 130, 246, 0.22)'}`,
        borderRadius: 'var(--radius-md)',
        fontSize: '0.75rem',
        color: 'var(--text-secondary)',
        display: 'flex',
        flexDirection: 'column',
        gap: '0.75rem',
        position: 'relative',
        zIndex: 1,
        boxSizing: 'border-box',
      }}
    >
      {/* 1. Header & Status Badge */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: '0.5rem', flexWrap: 'wrap' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
          <Cpu size={13} style={{ color: 'var(--primary-glow)' }} />
          <span
            style={{
              fontWeight: 700,
              letterSpacing: '0.06em',
              color: 'var(--text-primary)',
              textTransform: 'uppercase',
              fontSize: '0.6875rem',
            }}
          >
            05 // PRODUCTION DECISION INTELLIGENCE
          </span>
        </div>

        <span
          data-testid="preflight-status-badge"
          style={{
            display: 'inline-flex',
            alignItems: 'center',
            gap: '4px',
            padding: '2px 8px',
            borderRadius: '4px',
            fontSize: '0.6875rem',
            fontWeight: 700,
            letterSpacing: '0.04em',
            ...badgeStyle,
          }}
        >
          {isReady ? (
            <CheckCircle2 size={12} />
          ) : isWarning ? (
            <AlertTriangle size={12} />
          ) : (
            <AlertCircle size={12} />
          )}
          <span>{badgeLabel}</span>
        </span>
      </div>

      {/* 2. Actionable Reason & Reason Code if Blocked */}
      {isBlocked && (
        <div
          data-testid="preflight-reasons-list"
          style={{
            padding: '0.5rem 0.75rem',
            backgroundColor: 'rgba(245, 158, 11, 0.08)',
            borderLeft: '2px solid #fbbf24',
            borderRadius: '0 4px 4px 0',
            color: '#fde68a',
            fontSize: '0.71875rem',
            lineHeight: 1.4,
          }}
        >
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '4px' }}>
            <span style={{ fontWeight: 600, letterSpacing: '0.02em' }}>
              REASON: {reason || 'CONFIGURATION BLOCKED'}
            </span>
            {reasonCode && (
              <span
                data-testid="decision-reason-code"
                style={{
                  fontSize: '0.625rem',
                  fontFamily: 'var(--font-mono, monospace)',
                  backgroundColor: 'rgba(0, 0, 0, 0.3)',
                  padding: '1px 5px',
                  borderRadius: '3px',
                  color: '#fbbf24',
                  letterSpacing: '0.04em',
                }}
              >
                CODE // {reasonCode}
              </span>
            )}
          </div>
          {reasons && reasons.length > 1 && (
            <ul style={{ margin: '4px 0 0 1rem', padding: 0 }}>
              {reasons.slice(1).map((r, idx) => (
                <li key={idx}>{r}</li>
              ))}
            </ul>
          )}
        </div>
      )}

      {/* 3. Stage 9 Pre-Flight Deterministic Summary */}
      {preflightSummary && preflightSummary.length > 0 && (
        <div
          data-testid="preflight-summary-table"
          style={{
            backgroundColor: 'rgba(0, 0, 0, 0.3)',
            borderRadius: 'var(--radius-sm)',
            padding: '0.5rem 0.625rem',
            border: '1px solid rgba(255, 255, 255, 0.04)',
            fontFamily: 'var(--font-mono, monospace)',
            fontSize: '0.65625rem',
          }}
        >
          <div
            style={{
              fontSize: '0.625rem',
              fontWeight: 700,
              letterSpacing: '0.06em',
              color: 'var(--text-muted)',
              marginBottom: '0.375rem',
              textTransform: 'uppercase',
            }}
          >
            PRE-FLIGHT CONFIGURATION SUMMARY
          </div>
          <div
            style={{
              display: 'grid',
              gridTemplateColumns: 'repeat(auto-fill, minmax(110px, 1fr))',
              gap: '0.375rem 0.5rem',
            }}
          >
            {preflightSummary.map((item) => {
              const isItemFailed = item.status === 'BLOCKED' || item.status === 'NOT_SUPPORTED' || item.status === 'MISSING';
              const isItemReady = item.status === 'READY' || item.status === 'SUPPORTED' || item.status === 'VALID';
              const valColor = isItemFailed ? '#fbbf24' : isItemReady ? '#38bdf8' : 'var(--text-secondary)';
              const displayVal = item.key === 'status' ? `STATUS // ${item.value}` : item.value;
              return (
                <div key={item.key} style={{ display: 'flex', flexDirection: 'column' }}>
                  <span style={{ color: 'var(--text-muted)', fontSize: '0.5625rem', textTransform: 'uppercase' }}>
                    {item.label}
                  </span>
                  <span style={{ color: valColor, fontWeight: 600 }}>{displayVal}</span>
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* 4. Model Facts & Conditioning (Preserved Stage 8 IDs) */}
      <div
        data-testid="decision-model-facts"
        style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(auto-fit, minmax(120px, 1fr))',
          gap: '0.5rem',
          backgroundColor: 'rgba(0, 0, 0, 0.25)',
          padding: '0.625rem',
          borderRadius: 'var(--radius-sm)',
          border: '1px solid rgba(255, 255, 255, 0.04)',
        }}
      >
        <div>
          <span style={{ display: 'block', color: 'var(--text-muted)', fontSize: '0.625rem', textTransform: 'uppercase' }}>
            Model
          </span>
          <strong style={{ color: 'var(--text-primary)', fontSize: '0.75rem' }}>
            {explanation.modelName}
          </strong>
        </div>

        <div>
          <span style={{ display: 'block', color: 'var(--text-muted)', fontSize: '0.625rem', textTransform: 'uppercase' }}>
            Supported
          </span>
          <span style={{ color: 'var(--text-secondary)' }}>
            {explanation.supportedAspectRatios.join(' · ') || '16:9'}
          </span>
        </div>

        {explanation.supportedDurations.length > 0 && (
          <div>
            <span style={{ display: 'block', color: 'var(--text-muted)', fontSize: '0.625rem', textTransform: 'uppercase' }}>
              Duration
            </span>
            <span style={{ color: 'var(--text-secondary)' }}>
              {explanation.supportedDurations.map((d) => `${d}s`).join(' / ')}
            </span>
          </div>
        )}

        <div>
          <span style={{ display: 'block', color: 'var(--text-muted)', fontSize: '0.625rem', textTransform: 'uppercase' }}>
            Start Frame
          </span>
          <span
            data-testid="decision-start-frame-support"
            style={{
              fontWeight: 600,
              color: explanation.startFrameSupport === 'SUPPORTED' ? '#38bdf8' : 'var(--text-muted)',
            }}
          >
            {explanation.startFrameSupport}
          </span>
        </div>

        <div>
          <span style={{ display: 'block', color: 'var(--text-muted)', fontSize: '0.625rem', textTransform: 'uppercase' }}>
            End Frame
          </span>
          <span
            data-testid="decision-end-frame-support"
            style={{
              fontWeight: 600,
              color: 'var(--text-muted)',
            }}
          >
            {explanation.endFrameSupport}
          </span>
        </div>
      </div>

      {/* 5. Telemetry Strip: Cost & Quality Support (Preserved Stage 8 IDs) */}
      <div
        style={{
          display: 'flex',
          flexWrap: 'wrap',
          alignItems: 'center',
          justifyContent: 'space-between',
          gap: '0.75rem',
          paddingTop: '0.375rem',
          borderTop: '1px solid rgba(255, 255, 255, 0.05)',
        }}
      >
        <div data-testid="decision-cost-display" style={{ display: 'flex', alignItems: 'center', gap: '5px' }}>
          <DollarSign size={12} style={{ color: explanation.cost.hasCostData ? '#34d399' : 'var(--text-muted)' }} />
          <span>
            {explanation.cost.hasCostData ? (
              <>
                <span style={{ color: 'var(--text-muted)' }}>AVG KNOWN COST: </span>
                <strong style={{ color: '#34d399' }}>{explanation.cost.displayStatus}</strong>
                <span style={{ color: 'var(--text-muted)', fontSize: '0.65rem' }}> ({explanation.cost.runCount} runs)</span>
              </>
            ) : (
              <span style={{ color: 'var(--text-muted)' }}>COST COMPARISON: UNAVAILABLE</span>
            )}
          </span>
        </div>

        <div data-testid="decision-quality-display" style={{ display: 'flex', alignItems: 'center', gap: '5px' }}>
          <Award size={12} style={{ color: explanation.quality.qualityDataAvailable ? '#38bdf8' : 'var(--text-muted)' }} />
          <span style={{ color: 'var(--text-muted)' }}>
            {explanation.quality.displayText}
          </span>
        </div>
      </div>

      {/* 6. Stage 9 Expandable Evidence & Provenance Section */}
      <div style={{ borderTop: '1px dashed rgba(255, 255, 255, 0.08)', paddingTop: '0.375rem' }}>
        <button
          type="button"
          data-testid="decision-evidence-toggle"
          onClick={() => setShowEvidence((prev) => !prev)}
          style={{
            background: 'none',
            border: 'none',
            color: 'var(--text-muted)',
            cursor: 'pointer',
            padding: '2px 0',
            display: 'flex',
            alignItems: 'center',
            gap: '4px',
            fontSize: '0.625rem',
            letterSpacing: '0.06em',
            textTransform: 'uppercase',
            width: '100%',
            justifyContent: 'space-between',
          }}
        >
          <span style={{ display: 'flex', alignItems: 'center', gap: '4px' }}>
            <FileText size={11} style={{ color: 'var(--accent-primary)' }} />
            <span>DECISION EVIDENCE & SOURCE PROVENANCE</span>
          </span>
          {showEvidence ? <ChevronUp size={12} /> : <ChevronDown size={12} />}
        </button>

        {showEvidence && (
          <div
            style={{
              display: 'flex',
              flexDirection: 'column',
              gap: '0.625rem',
              marginTop: '0.5rem',
              padding: '0.5rem',
              backgroundColor: 'rgba(0, 0, 0, 0.35)',
              borderRadius: 'var(--radius-sm)',
              border: '1px solid rgba(255, 255, 255, 0.04)',
            }}
          >
            {/* A. WHY Section */}
            <div data-testid="decision-why-list">
              <div
                style={{
                  fontSize: '0.625rem',
                  fontWeight: 700,
                  letterSpacing: '0.05em',
                  color: 'var(--text-muted)',
                  textTransform: 'uppercase',
                  marginBottom: '0.25rem',
                }}
              >
                WHY // VERIFICATION BASIS
              </div>
              <div style={{ display: 'flex', flexDirection: 'column', gap: '3px' }}>
                {recommendation.preflight.checks.map((chk) => {
                  const isPassed = chk.status === 'PASSED';
                  const isFailed = chk.status === 'FAILED';
                  return (
                    <div
                      key={chk.id}
                      style={{
                        display: 'flex',
                        alignItems: 'center',
                        justifyContent: 'space-between',
                        gap: '0.5rem',
                        fontSize: '0.65625rem',
                      }}
                    >
                      <span style={{ display: 'flex', alignItems: 'center', gap: '5px' }}>
                        <span style={{ color: isPassed ? '#34d399' : isFailed ? '#fbbf24' : 'var(--text-muted)' }}>
                          {isPassed ? '✓' : isFailed ? '✕' : '•'}
                        </span>
                        <span style={{ color: isFailed ? '#fde68a' : 'var(--text-secondary)' }}>
                          {chk.detail || chk.label}
                        </span>
                      </span>
                      {chk.source && (
                        <span
                          style={{
                            fontSize: '0.5625rem',
                            fontFamily: 'var(--font-mono, monospace)',
                            color: 'var(--text-muted)',
                            letterSpacing: '0.02em',
                          }}
                        >
                          SOURCE // {chk.source}
                        </span>
                      )}
                    </div>
                  );
                })}
              </div>
            </div>

            {/* B. MODEL FACTS PANEL */}
            <div
              data-testid="decision-model-facts-panel"
              style={{
                borderTop: '1px solid rgba(255, 255, 255, 0.04)',
                paddingTop: '0.375rem',
              }}
            >
              <div
                style={{
                  fontSize: '0.625rem',
                  fontWeight: 700,
                  letterSpacing: '0.05em',
                  color: 'var(--text-muted)',
                  textTransform: 'uppercase',
                  marginBottom: '0.25rem',
                }}
              >
                MODEL FACTS
              </div>
              <div
                style={{
                  display: 'grid',
                  gridTemplateColumns: 'repeat(auto-fit, minmax(130px, 1fr))',
                  gap: '0.375rem',
                  fontFamily: 'var(--font-mono, monospace)',
                  fontSize: '0.65625rem',
                }}
              >
                {categorization.facts
                  .filter((f) => ['model', 'provider', 'mode', 'aspect', 'resolution'].includes(f.id))
                  .map((f) => (
                    <div key={f.id} style={{ display: 'flex', flexDirection: 'column' }}>
                      <span style={{ color: 'var(--text-muted)', fontSize: '0.5625rem' }}>{f.label}</span>
                      <strong style={{ color: 'var(--text-primary)', fontSize: '0.6875rem' }}>{f.value}</strong>
                      <span style={{ color: 'rgba(255, 255, 255, 0.25)', fontSize: '0.5rem' }}>
                        SOURCE // {f.source}
                      </span>
                    </div>
                  ))}
              </div>
            </div>

            {/* C. OPERATIONAL FACTS PANEL */}
            <div
              data-testid="decision-operational-facts-panel"
              style={{
                borderTop: '1px solid rgba(255, 255, 255, 0.04)',
                paddingTop: '0.375rem',
              }}
            >
              <div
                style={{
                  fontSize: '0.625rem',
                  fontWeight: 700,
                  letterSpacing: '0.05em',
                  color: 'var(--text-muted)',
                  textTransform: 'uppercase',
                  marginBottom: '0.25rem',
                }}
              >
                OPERATIONAL FACTS
              </div>
              <div
                style={{
                  display: 'grid',
                  gridTemplateColumns: 'repeat(auto-fit, minmax(130px, 1fr))',
                  gap: '0.375rem',
                  fontFamily: 'var(--font-mono, monospace)',
                  fontSize: '0.65625rem',
                }}
              >
                {categorization.facts
                  .filter((f) => ['runs_count', 'recent_cost', 'avg_cost', 'quality_data'].includes(f.id))
                  .map((f) => (
                    <div key={f.id} style={{ display: 'flex', flexDirection: 'column' }}>
                      <span style={{ color: 'var(--text-muted)', fontSize: '0.5625rem' }}>{f.label}</span>
                      <strong style={{ color: 'var(--text-primary)', fontSize: '0.6875rem' }}>{f.value}</strong>
                      <span style={{ color: 'rgba(255, 255, 255, 0.25)', fontSize: '0.5rem' }}>
                        SOURCE // {f.source}
                      </span>
                    </div>
                  ))}
              </div>
            </div>

            {/* D. EXECUTION PAYLOAD PREVIEW */}
            {executionPreview && (
              <div
                data-testid="execution-preview-panel"
                style={{
                  borderTop: '1px solid rgba(255, 255, 255, 0.04)',
                  paddingTop: '0.375rem',
                  fontFamily: 'var(--font-mono, monospace)',
                  fontSize: '0.625rem',
                }}
              >
                <div
                  style={{
                    fontWeight: 700,
                    letterSpacing: '0.05em',
                    color: 'var(--text-muted)',
                    textTransform: 'uppercase',
                    marginBottom: '0.25rem',
                  }}
                >
                  EXECUTION PAYLOAD PREVIEW
                </div>
                <div
                  style={{
                    backgroundColor: 'rgba(0, 0, 0, 0.3)',
                    padding: '0.375rem 0.5rem',
                    borderRadius: '2px',
                    color: 'var(--text-secondary)',
                    lineHeight: 1.5,
                  }}
                >
                  <div>MODE: {executionPreview.mode.toUpperCase()}</div>
                  <div>MODEL: {executionPreview.model}</div>
                  <div>PROVIDER: {executionPreview.provider}</div>
                  <div>ASPECT: {executionPreview.aspectRatio}</div>
                  <div>RESOLUTION: {executionPreview.resolution}</div>
                  <div>PROMPT: {executionPreview.promptStatus} ({executionPreview.promptPreview})</div>
                  <div>REFERENCE: {executionPreview.referenceStatus}</div>
                  {executionPreview.durationSeconds && <div>DURATION: {executionPreview.durationSeconds}s</div>}
                </div>
                <div style={{ marginTop: '0.375rem', color: 'var(--text-muted)', fontSize: '0.59375rem' }}>
                  <div style={{ fontWeight: 600, color: 'var(--text-primary)', marginBottom: '2px' }}>ON EXECUTE</div>
                  {executionPreview.dispatchSteps.map((step, idx) => (
                    <div key={idx}>{step}</div>
                  ))}
                </div>
              </div>
            )}

            {/* E. EXECUTION POLICY */}
            <div
              data-testid="decision-execution-policy"
              style={{
                borderTop: '1px solid rgba(255, 255, 255, 0.04)',
                paddingTop: '0.375rem',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'space-between',
                flexWrap: 'wrap',
                gap: '0.25rem 0.5rem',
                fontSize: '0.59375rem',
                color: 'var(--text-muted)',
                fontFamily: 'var(--font-mono, monospace)',
              }}
            >
              <div style={{ display: 'flex', alignItems: 'center', gap: '3px' }}>
                <ShieldCheck size={11} style={{ color: 'var(--accent-primary)' }} />
                <span>NO AUTOMATIC MODEL SWITCH</span>
              </div>
              <div>NO AUTOMATIC PARAMETER CHANGE</div>
              <div style={{ color: 'var(--accent-primary)', fontWeight: 600 }}>USER CONFIRMATION REQUIRED</div>
            </div>
          </div>
        )}
      </div>

      {/* 7. Pre-flight Directive */}
      <div
        data-testid="preflight-directive"
        style={{
          fontSize: '0.6875rem',
          fontWeight: 600,
          letterSpacing: '0.04em',
          textTransform: 'uppercase',
          textAlign: 'center',
          padding: '4px',
          backgroundColor: isBlocked || isWarning ? 'rgba(245, 158, 11, 0.06)' : 'rgba(56, 189, 248, 0.06)',
          borderRadius: '3px',
          color: isBlocked || isWarning ? '#fbbf24' : '#38bdf8',
        }}
      >
        PRE-FLIGHT // {directive}
      </div>
    </div>
  );
};
