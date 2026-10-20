import React from 'react';
import { Activity, RefreshCw, AlertCircle, CheckCircle2, Clock, ShieldAlert } from 'lucide-react';
import { SystemOperationalState } from '../../types/productionRun';
import { SequenceOperationalSummary } from '../../types/productionTimeline';

interface OperationalStripProps {
  systemState: SystemOperationalState;
  activeCount: number;
  queuedCount: number;
  processingCount: number;
  failedCount: number;
  totalCostUsd: number;
  isRefreshing?: boolean;
  onRefresh?: () => void;
  hasActiveJob?: boolean;
  preflightStatus?: 'READY' | 'BLOCKED' | 'WARNING';
  sequenceSummary?: SequenceOperationalSummary;
  projectStatus?: 'NEW' | 'SAVED' | 'UNSAVED' | 'RECOVERED';
}

export const OperationalStrip: React.FC<OperationalStripProps> = ({
  systemState,
  activeCount,
  queuedCount,
  processingCount,
  failedCount,
  totalCostUsd,
  isRefreshing = false,
  onRefresh,
  hasActiveJob = false,
  preflightStatus = 'READY',
  sequenceSummary,
  projectStatus,
}) => {
  const getStateColor = () => {
    switch (systemState) {
      case 'ACTIVE':
        return 'var(--accent-primary)';
      case 'DEGRADED':
        return '#f59e0b';
      case 'ERROR':
        return 'var(--danger)';
      case 'IDLE':
      default:
        return 'var(--text-muted)';
    }
  };

  return (
    <div
      style={{
        position: 'relative',
        zIndex: 10,
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        flexWrap: 'wrap',
        gap: '0.75rem',
        padding: '0.625rem 1rem',
        background: 'linear-gradient(180deg, rgba(17, 24, 39, 0.95) 0%, rgba(11, 16, 26, 0.98) 100%)',
        border: '1px solid rgba(59, 130, 246, 0.3)',
        borderRadius: 'var(--radius-md, 6px)',
        boxShadow: '0 4px 16px rgba(0, 0, 0, 0.5), inset 0 1px 0 rgba(255, 255, 255, 0.08)',
        marginBottom: '0.875rem',
        fontSize: '0.75rem',
        fontFamily: 'monospace',
      }}
      data-testid="operational-strip"
    >
      {/* 1. System Operational State */}
      <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
        <span
          style={{
            width: '7px',
            height: '7px',
            borderRadius: '50%',
            backgroundColor: getStateColor(),
            boxShadow: systemState === 'ACTIVE' ? '0 0 8px rgba(59, 130, 246, 0.8)' : undefined,
          }}
        />
        <span style={{ color: 'var(--text-muted)', letterSpacing: '0.06em' }}>SYSTEM //</span>
        <span
          data-testid="operational-system-state"
          style={{
            fontWeight: 700,
            color: getStateColor(),
            letterSpacing: '0.08em',
          }}
        >
          SYS: {systemState}
        </span>
      </div>

      {/* 2. Run Counts Strip */}
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: '0.875rem',
          color: 'var(--text-primary)',
        }}
        data-testid="operational-run-counts"
      >
        <div>
          <span style={{ color: 'var(--text-muted)' }}>RUNS: </span>
          <span style={{ fontWeight: 700 }} data-testid="count-active-runs">
            {String(activeCount).padStart(2, '0')}
          </span>
        </div>
        <div>
          <span style={{ color: 'var(--text-muted)' }}>QUEUED: </span>
          <span style={{ fontWeight: 700 }} data-testid="count-queued-runs">
            {String(queuedCount).padStart(2, '0')}
          </span>
        </div>
        <div>
          <span style={{ color: 'var(--text-muted)' }}>IN-FLIGHT: </span>
          <span style={{ fontWeight: 700, color: processingCount > 0 ? 'var(--accent-primary)' : undefined }} data-testid="count-processing-runs">
            {String(processingCount).padStart(2, '0')}
          </span>
        </div>
        <div>
          <span style={{ color: 'var(--text-muted)' }}>FAILURES: </span>
          <span style={{ fontWeight: 700, color: failedCount > 0 ? 'var(--danger)' : undefined }} data-testid="count-failed-runs">
            {String(failedCount).padStart(2, '0')}
          </span>
        </div>
      </div>

      {/* Pre-Flight State */}
      <div style={{ display: 'flex', alignItems: 'center', gap: '4px' }}>
        <span
          data-testid="operational-preflight-status"
          style={{
            fontWeight: 700,
            color: preflightStatus === 'READY' ? 'var(--accent-primary)' : '#fbbf24',
            letterSpacing: '0.04em',
          }}
        >
          PRE-FLIGHT: {preflightStatus}
        </span>
      </div>

      {/* Stage 10: Sequence-level Telemetry */}
      {sequenceSummary && (
        <div
          data-testid="operational-sequence-summary"
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: '0.625rem',
            borderLeft: '1px solid rgba(255, 255, 255, 0.1)',
            paddingLeft: '0.625rem',
            color: 'var(--text-secondary)',
          }}
        >
          <div>
            <span style={{ color: 'var(--text-muted)' }}>SEQ: </span>
            <strong style={{ color: '#38bdf8' }} data-testid="strip-seq-num">{sequenceSummary.sequenceNumber}</strong>
          </div>
          <div>
            <span style={{ color: 'var(--text-muted)' }}>SHOTS: </span>
            <strong data-testid="strip-seq-shots">{sequenceSummary.totalShots}</strong>
          </div>
          <div>
            <span style={{ color: 'var(--text-muted)' }}>READY: </span>
            <strong style={{ color: '#38bdf8' }} data-testid="strip-seq-ready">{sequenceSummary.readyShots}</strong>
          </div>
          <div>
            <span style={{ color: 'var(--text-muted)' }}>BLOCKED: </span>
            <strong style={{ color: sequenceSummary.blockedShots > 0 ? '#fbbf24' : undefined }} data-testid="strip-seq-blocked">
              {sequenceSummary.blockedShots}
            </strong>
          </div>
          <div>
            <span style={{ color: 'var(--text-muted)' }}>IN-FLIGHT: </span>
            <strong style={{ color: sequenceSummary.inFlightShots > 0 ? '#c084fc' : undefined }} data-testid="strip-seq-inflight">
              {sequenceSummary.inFlightShots}
            </strong>
          </div>
          <div>
            <span style={{ color: 'var(--text-muted)' }}>COMPLETE: </span>
            <strong style={{ color: '#34d399' }} data-testid="strip-seq-complete">{sequenceSummary.completeShots}</strong>
          </div>
        </div>
      )}

      {/* 3. Cost & Actions */}
      <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
        {/* Stage 11: Project Persistence Status Indicator */}
        {projectStatus && (
          <div
            data-testid="operational-project-status"
            style={{
              display: 'inline-flex',
              alignItems: 'center',
              gap: '4px',
              fontSize: '0.6875rem',
              padding: '2px 6px',
              borderRadius: '3px',
              backgroundColor:
                projectStatus === 'SAVED' || projectStatus === 'RECOVERED'
                  ? 'rgba(56, 189, 248, 0.12)'
                  : 'rgba(255, 255, 255, 0.05)',
              color:
                projectStatus === 'SAVED' || projectStatus === 'RECOVERED'
                  ? '#38bdf8'
                  : 'var(--text-muted)',
              border: '1px solid rgba(255, 255, 255, 0.1)',
            }}
          >
            <span>PROJECT // {projectStatus}</span>
          </div>
        )}

        {/* Cost Indicator */}
        <div style={{ color: 'var(--text-muted)' }}>
          <span>COST </span>
          <span style={{ color: totalCostUsd > 0 ? 'var(--success)' : 'var(--text-muted)', fontWeight: 600 }}>
            {totalCostUsd > 0 ? `$${totalCostUsd.toFixed(4)}` : 'UNAVAILABLE'}
          </span>
        </div>

        {/* Cancellation status: Truthfully notes backend does not support cancellation */}
        {hasActiveJob && (
          <span
            style={{
              fontSize: '0.6875rem',
              color: 'var(--text-muted)',
              border: '1px dashed rgba(255, 255, 255, 0.15)',
              padding: '2px 6px',
              borderRadius: '2px',
            }}
            title="Backend V1 does not expose a job cancellation endpoint"
            data-testid="cancellation-badge"
          >
            CANCEL: UNAVAILABLE
          </span>
        )}

        {/* Operational Reconcile / Refresh Button */}
        {onRefresh && (
          <button
            type="button"
            onClick={onRefresh}
            disabled={isRefreshing}
            className="btn-secondary"
            style={{
              padding: '3px 8px',
              fontSize: '0.6875rem',
              gap: '4px',
              height: 'auto',
            }}
            title="Reconcile system status, history, and active job without restarting generation"
            data-testid="operational-refresh-btn"
          >
            <RefreshCw size={11} className={isRefreshing ? 'animate-spin' : undefined} />
            <span>RECONCILE</span>
          </button>
        )}
      </div>
    </div>
  );
};
