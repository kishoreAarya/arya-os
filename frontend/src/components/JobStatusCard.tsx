import React from 'react';
import {
  CheckCircle2,
  AlertCircle,
  Loader2,
  RefreshCw,
  RotateCcw,
} from 'lucide-react';
import { GenerationJob } from '../types/creator';

interface JobStatusCardProps {
  job: GenerationJob;
  onRefresh?: () => void;
  onRetry?: () => void;
}

export const JobStatusCard: React.FC<JobStatusCardProps> = ({ job, onRefresh, onRetry }) => {
  const getStatusBadge = () => {
    switch (job.status) {
      case 'pending':
        return <span className="badge badge-pending">Queued</span>;
      case 'in_progress':
        return (
          <span className="badge badge-in_progress">
            <Loader2 size={12} className="animate-spin" />
            Running
          </span>
        );
      case 'completed':
        return (
          <span className="badge badge-completed">
            <CheckCircle2 size={12} />
            Completed
          </span>
        );
      case 'failed':
        return (
          <span className="badge badge-failed">
            <AlertCircle size={12} />
            Failed
          </span>
        );
    }
  };

  const getStageDisplay = () => {
    switch (job.current_stage) {
      case 'created':
        return 'Job initialized & queued';
      case 'image_generation':
        return 'Executing Image Generation Agent';
      case 'video_generation':
        return 'Executing Video Generation Agent';
      case 'completed':
        return 'Asset successfully produced & stored';
      default:
        return job.current_stage || 'Processing';
    }
  };

  return (
    <div
      className="creator-card"
      style={{
        marginBottom: '1.25rem',
        borderColor: job.status === 'failed' ? 'rgba(239, 68, 68, 0.4)' : undefined,
      }}
    >
      <div className="creator-card-header">
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
          <span className="card-title">Job Status</span>
          <div data-testid="job-status-badge">{getStatusBadge()}</div>
        </div>

        {onRefresh && (
          <button
            type="button"
            onClick={onRefresh}
            className="btn-secondary"
            style={{ padding: '4px 8px', fontSize: '0.75rem' }}
            title="Poll fresh status"
          >
            <RefreshCw size={12} />
            <span>Poll</span>
          </button>
        )}
      </div>

      {/* Cinematic Progress Bar */}
      <div
        style={{
          height: '4px',
          backgroundColor: 'rgba(7, 10, 16, 0.9)',
          borderRadius: '2px',
          overflow: 'hidden',
          marginBottom: '1rem',
          border: '1px solid rgba(255, 255, 255, 0.05)',
        }}
      >
        <div
          style={{
            height: '100%',
            width:
              job.status === 'completed'
                ? '100%'
                : job.status === 'in_progress'
                ? '65%'
                : job.status === 'failed'
                ? '100%'
                : '20%',
            backgroundColor:
              job.status === 'completed'
                ? 'var(--success)'
                : job.status === 'failed'
                ? 'var(--danger)'
                : 'var(--accent-primary)',
            boxShadow:
              job.status === 'in_progress'
                ? '0 0 10px rgba(59, 130, 246, 0.6)'
                : job.status === 'completed'
                ? '0 0 10px rgba(16, 185, 129, 0.5)'
                : undefined,
            transition: 'all 0.5s ease',
          }}
        />
      </div>

      {/* Telemetry Information Grid */}
      <div
        style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(auto-fit, minmax(130px, 1fr))',
          gap: '0.75rem',
          fontSize: '0.8125rem',
          marginBottom: '0.75rem',
        }}
      >
        <div
          style={{
            background: 'rgba(7, 10, 16, 0.75)',
            border: '1px solid var(--border-color)',
            padding: '0.5rem 0.75rem',
            borderRadius: 'var(--radius-sm)',
          }}
        >
          <div style={{ color: 'var(--text-muted)', fontSize: '0.6875rem', textTransform: 'uppercase', letterSpacing: '0.04em' }}>
            Workflow ID
          </div>
          <div style={{ fontFamily: 'monospace', fontWeight: 600, overflow: 'hidden', textOverflow: 'ellipsis' }}>
            {job.workflow_run_id ? job.workflow_run_id.slice(0, 8) : '—'}
          </div>
        </div>

        <div
          style={{
            background: 'rgba(7, 10, 16, 0.75)',
            border: '1px solid var(--border-color)',
            padding: '0.5rem 0.75rem',
            borderRadius: 'var(--radius-sm)',
          }}
        >
          <div style={{ color: 'var(--text-muted)', fontSize: '0.6875rem', textTransform: 'uppercase', letterSpacing: '0.04em' }}>
            Type
          </div>
          <div style={{ fontWeight: 600, textTransform: 'capitalize' }}>
            {job.generation_type.replace(/_/g, ' ')}
          </div>
        </div>

        <div
          style={{
            background: 'rgba(7, 10, 16, 0.75)',
            border: '1px solid var(--border-color)',
            padding: '0.5rem 0.75rem',
            borderRadius: 'var(--radius-sm)',
          }}
        >
          <div style={{ color: 'var(--text-muted)', fontSize: '0.6875rem', textTransform: 'uppercase', letterSpacing: '0.04em' }}>
            Active Stage
          </div>
          <div style={{ fontWeight: 600, color: 'var(--text-primary)' }}>
            {getStageDisplay()}
          </div>
        </div>

        <div
          style={{
            background: 'rgba(7, 10, 16, 0.75)',
            border: '1px solid var(--border-color)',
            padding: '0.5rem 0.75rem',
            borderRadius: 'var(--radius-sm)',
          }}
        >
          <div style={{ color: 'var(--text-muted)', fontSize: '0.6875rem', textTransform: 'uppercase', letterSpacing: '0.04em' }}>
            Provider
          </div>
          <div style={{ fontWeight: 600, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }} data-testid="job-actual-provider">
            {job.actual_provider || job.output?.provider_used || job.provider || 'UNAVAILABLE'}
          </div>
          <div style={{ color: 'var(--text-muted)', fontSize: '0.625rem' }} data-testid="job-requested-provider">
            Req: {job.requested_provider || job.provider || 'UNAVAILABLE'}
          </div>
        </div>

        <div
          style={{
            background: 'rgba(7, 10, 16, 0.75)',
            border: '1px solid var(--border-color)',
            padding: '0.5rem 0.75rem',
            borderRadius: 'var(--radius-sm)',
          }}
        >
          <div style={{ color: 'var(--text-muted)', fontSize: '0.6875rem', textTransform: 'uppercase', letterSpacing: '0.04em' }}>
            Model
          </div>
          <div style={{ fontWeight: 600, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }} data-testid="job-actual-model">
            {job.actual_model || job.output?.model_used || job.model || 'UNAVAILABLE'}
          </div>
          <div style={{ color: 'var(--text-muted)', fontSize: '0.625rem' }} data-testid="job-requested-model">
            Req: {job.requested_model || job.model || 'UNAVAILABLE'}
          </div>
        </div>

        <div
          style={{
            background: 'rgba(7, 10, 16, 0.75)',
            border: '1px solid var(--border-color)',
            padding: '0.5rem 0.75rem',
            borderRadius: 'var(--radius-sm)',
          }}
        >
          <div style={{ color: 'var(--text-muted)', fontSize: '0.6875rem', textTransform: 'uppercase', letterSpacing: '0.04em' }}>
            Cost
          </div>
          <div
            style={{
              fontWeight: 600,
              color: job.total_cost_usd > 0 ? 'var(--success)' : 'var(--text-muted)',
            }}
            data-testid="job-cost-display"
          >
            {job.total_cost_usd > 0 ? `$${job.total_cost_usd.toFixed(4)}` : 'UNAVAILABLE'}
          </div>
        </div>
      </div>

      {/* Cancellation Notice for in-flight jobs */}
      {(job.status === 'in_progress' || job.status === 'pending') && (
        <div
          style={{
            marginBottom: '0.75rem',
            padding: '0.375rem 0.625rem',
            backgroundColor: 'rgba(255, 255, 255, 0.02)',
            border: '1px dashed rgba(255, 255, 255, 0.1)',
            borderRadius: 'var(--radius-sm)',
            fontSize: '0.6875rem',
            color: 'var(--text-muted)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
          }}
          data-testid="job-cancellation-notice"
        >
          <span>EXECUTION CONTROL:</span>
          <span>CANCELLATION UNAVAILABLE (V1 Contract)</span>
        </div>
      )}

      {/* Failure Reason & Retry if Failed */}
      {job.status === 'failed' && (
        <div
          style={{
            padding: '0.75rem',
            backgroundColor: 'rgba(239, 68, 68, 0.08)',
            border: '1px solid rgba(239, 68, 68, 0.25)',
            borderRadius: 'var(--radius-md)',
            color: '#fca5a5',
            fontSize: '0.8125rem',
            display: 'flex',
            justifyContent: 'space-between',
            alignItems: 'center',
            gap: '0.75rem',
          }}
          data-testid="job-failure-error"
        >
          <div>
            <strong style={{ display: 'block', marginBottom: '2px' }}>Execution Failed</strong>
            <span>{job.failure_reason || 'Backend execution failed or was interrupted.'}</span>
          </div>
          {onRetry && (
            <button
              type="button"
              onClick={onRetry}
              className="btn-secondary"
              style={{
                backgroundColor: 'rgba(239, 68, 68, 0.2)',
                borderColor: 'rgba(239, 68, 68, 0.4)',
                color: '#ffffff',
                padding: '4px 10px',
                fontSize: '0.75rem',
                whiteSpace: 'nowrap',
                gap: '4px',
              }}
              data-testid="job-retry-button"
            >
              <RotateCcw size={12} />
              <span>Retry</span>
            </button>
          )}
        </div>
      )}
    </div>
  );
};
