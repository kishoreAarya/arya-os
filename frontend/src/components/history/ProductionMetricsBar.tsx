import React from 'react';
import { Activity, CheckCircle2, AlertCircle, Clock, DollarSign, Layers } from 'lucide-react';
import { OperationalMetrics } from '../../types/productionRun';

interface ProductionMetricsBarProps {
  metrics: OperationalMetrics;
}

export const ProductionMetricsBar: React.FC<ProductionMetricsBarProps> = ({ metrics }) => {
  return (
    <div
      style={{
        display: 'grid',
        gridTemplateColumns: 'repeat(auto-fit, minmax(140px, 1fr))',
        gap: '0.5rem',
        marginBottom: '1rem',
      }}
      data-testid="production-metrics-bar"
    >
      {/* 1. Total Runs */}
      <div
        style={{
          backgroundColor: 'rgba(7, 10, 16, 0.75)',
          border: '1px solid rgba(255, 255, 255, 0.06)',
          borderRadius: '4px',
          padding: '0.5rem 0.75rem',
          display: 'flex',
          flexDirection: 'column',
          gap: '2px',
        }}
      >
        <span style={{ fontSize: '0.625rem', color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.05em' }}>
          TOTAL RUNS
        </span>
        <span style={{ fontSize: '1rem', fontWeight: 700, color: 'var(--text-primary)', fontFamily: 'monospace' }}>
          {metrics.totalRuns}
        </span>
      </div>

      {/* 2. Success Rate */}
      <div
        style={{
          backgroundColor: 'rgba(7, 10, 16, 0.75)',
          border: '1px solid rgba(255, 255, 255, 0.06)',
          borderRadius: '4px',
          padding: '0.5rem 0.75rem',
          display: 'flex',
          flexDirection: 'column',
          gap: '2px',
        }}
      >
        <span style={{ fontSize: '0.625rem', color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.05em' }}>
          SUCCESS RATE
        </span>
        <span
          data-testid="metrics-success-rate"
          style={{
            fontSize: '1rem',
            fontWeight: 700,
            color: metrics.totalRuns > 0 && metrics.successRate >= 80 ? 'var(--success)' : 'var(--text-primary)',
            fontFamily: 'monospace',
          }}
        >
          {metrics.totalRuns > 0 ? `${metrics.successRate}.0%` : '—'}
        </span>
      </div>

      {/* 3. Successful vs Failed */}
      <div
        style={{
          backgroundColor: 'rgba(7, 10, 16, 0.75)',
          border: '1px solid rgba(255, 255, 255, 0.06)',
          borderRadius: '4px',
          padding: '0.5rem 0.75rem',
          display: 'flex',
          flexDirection: 'column',
          gap: '2px',
        }}
      >
        <span style={{ fontSize: '0.625rem', color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.05em' }}>
          COMPLETED / FAILED
        </span>
        <div style={{ display: 'flex', alignItems: 'center', gap: '6px', fontSize: '0.9375rem', fontWeight: 600, fontFamily: 'monospace' }}>
          <span style={{ color: 'var(--success)' }}>{metrics.successfulRuns}</span>
          <span style={{ color: 'var(--text-muted)' }}>/</span>
          <span style={{ color: metrics.failedRuns > 0 ? 'var(--danger)' : 'var(--text-muted)' }}>{metrics.failedRuns}</span>
        </div>
      </div>

      {/* 4. Average Latency */}
      <div
        style={{
          backgroundColor: 'rgba(7, 10, 16, 0.75)',
          border: '1px solid rgba(255, 255, 255, 0.06)',
          borderRadius: '4px',
          padding: '0.5rem 0.75rem',
          display: 'flex',
          flexDirection: 'column',
          gap: '2px',
        }}
      >
        <span style={{ fontSize: '0.625rem', color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.05em' }}>
          AVG DURATION
        </span>
        <span style={{ fontSize: '1rem', fontWeight: 700, color: 'var(--text-primary)', fontFamily: 'monospace' }}>
          {metrics.avgDurationSeconds !== null ? `${metrics.avgDurationSeconds}s` : 'UNAVAILABLE'}
        </span>
      </div>

      {/* 5. Total Cost */}
      <div
        style={{
          backgroundColor: 'rgba(7, 10, 16, 0.75)',
          border: '1px solid rgba(255, 255, 255, 0.06)',
          borderRadius: '4px',
          padding: '0.5rem 0.75rem',
          display: 'flex',
          flexDirection: 'column',
          gap: '2px',
        }}
      >
        <span style={{ fontSize: '0.625rem', color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.05em' }}>
          OPERATIONAL COST
        </span>
        <span
          style={{
            fontSize: '1rem',
            fontWeight: 700,
            color: metrics.totalCostUsd > 0 ? 'var(--success)' : 'var(--text-muted)',
            fontFamily: 'monospace',
          }}
        >
          {metrics.totalCostUsd > 0 ? `$${metrics.totalCostUsd.toFixed(4)}` : 'UNAVAILABLE'}
        </span>
      </div>
    </div>
  );
};
