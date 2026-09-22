import React from 'react';
import {
  Clock,
  CheckCircle2,
  AlertCircle,
  Loader2,
  DollarSign,
  Layers,
  Cpu,
  RefreshCw,
} from 'lucide-react';
import { GenerationJob } from '../types/creator';

interface JobStatusCardProps {
  job: GenerationJob;
  onRefresh?: () => void;
}

export const JobStatusCard: React.FC<JobStatusCardProps> = ({ job, onRefresh }) => {
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
    <div className="creator-card" style={{ marginBottom: '1.25rem', borderColor: job.status === 'failed' ? 'rgba(239, 68, 68, 0.4)' : undefined }}>
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

      {/* Progress Bar */}
      <div style={{
        height: '4px',
        backgroundColor: 'var(--bg-primary)',
        borderRadius: '2px',
        overflow: 'hidden',
        marginBottom: '1rem',
      }}>
        <div style={{
          height: '100%',
          width: job.status === 'completed' ? '100%' : job.status === 'in_progress' ? '65%' : job.status === 'failed' ? '100%' : '20%',
          backgroundColor: job.status === 'completed' ? 'var(--success)' : job.status === 'failed' ? 'var(--danger)' : 'var(--accent-primary)',
          transition: 'all 0.5s ease',
        }} />
      </div>

      {/* Info Grid */}
      <div style={{
        display: 'grid',
        gridTemplateColumns: 'repeat(auto-fit, minmax(130px, 1fr))',
        gap: '0.75rem',
        fontSize: '0.8125rem',
        marginBottom: '0.75rem',
      }}>
        <div style={{ background: 'var(--bg-primary)', padding: '0.5rem 0.75rem', borderRadius: 'var(--radius-sm)' }}>
          <div style={{ color: 'var(--text-muted)', fontSize: '0.6875rem', textTransform: 'uppercase' }}>Workflow ID</div>
          <div style={{ fontFamily: 'monospace', fontWeight: 600, overflow: 'hidden', textOverflow: 'ellipsis' }}>
            {job.workflow_run_id ? job.workflow_run_id.slice(0, 8) : '—'}
          </div>
        </div>

        <div style={{ background: 'var(--bg-primary)', padding: '0.5rem 0.75rem', borderRadius: 'var(--radius-sm)' }}>
          <div style={{ color: 'var(--text-muted)', fontSize: '0.6875rem', textTransform: 'uppercase' }}>Type</div>
          <div style={{ fontWeight: 600, textTransform: 'capitalize' }}>
            {job.generation_type.replace(/_/g, ' ')}
          </div>
        </div>

        <div style={{ background: 'var(--bg-primary)', padding: '0.5rem 0.75rem', borderRadius: 'var(--radius-sm)' }}>
          <div style={{ color: 'var(--text-muted)', fontSize: '0.6875rem', textTransform: 'uppercase' }}>Active Stage</div>
          <div style={{ fontWeight: 600, color: 'var(--text-primary)' }}>
            {getStageDisplay()}
          </div>
        </div>

        <div style={{ background: 'var(--bg-primary)', padding: '0.5rem 0.75rem', borderRadius: 'var(--radius-sm)' }}>
          <div style={{ color: 'var(--text-muted)', fontSize: '0.6875rem', textTransform: 'uppercase' }}>Provider / Model</div>
          <div style={{ fontWeight: 600, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
            {job.output.provider_used || job.provider || job.model || 'Auto'}
          </div>
        </div>

        {job.total_cost_usd > 0 && (
          <div style={{ background: 'var(--bg-primary)', padding: '0.5rem 0.75rem', borderRadius: 'var(--radius-sm)' }}>
            <div style={{ color: 'var(--text-muted)', fontSize: '0.6875rem', textTransform: 'uppercase' }}>Cost</div>
            <div style={{ fontWeight: 600, color: 'var(--success)' }}>
              ${job.total_cost_usd.toFixed(4)}
            </div>
          </div>
        )}
      </div>

      {/* Failure Reason if Failed */}
      {job.status === 'failed' && job.failure_reason && (
        <div style={{
          padding: '0.75rem',
          backgroundColor: 'rgba(239, 68, 68, 0.08)',
          border: '1px solid rgba(239, 68, 68, 0.25)',
          borderRadius: 'var(--radius-md)',
          color: '#fca5a5',
          fontSize: '0.8125rem',
        }} data-testid="job-failure-error">
          <strong style={{ display: 'block', marginBottom: '2px' }}>Execution Failed</strong>
          <span>{job.failure_reason}</span>
        </div>
      )}
    </div>
  );
};
