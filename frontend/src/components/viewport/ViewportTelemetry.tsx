import React from 'react';
import {
  CheckCircle2,
  Clock,
  Layers,
  Maximize2,
  Cpu,
  Monitor,
} from 'lucide-react';
import { GenerationJob } from '../../types/creator';

export interface ViewportTelemetryProps {
  currentJob: GenerationJob;
  isVideo: boolean;
}

export const ViewportTelemetry: React.FC<ViewportTelemetryProps> = ({
  currentJob,
  isVideo,
}) => {
  const provider = currentJob.output?.provider_used || currentJob.provider;
  const model = currentJob.model;
  const aspectRatio = currentJob.aspect_ratio || currentJob.output?.aspect_ratio;
  const duration = currentJob.output?.duration_seconds || currentJob.duration_seconds;
  const cost = currentJob.total_cost_usd;

  return (
    <div
      style={{
        marginTop: '1rem',
        padding: '0.875rem',
        backgroundColor: 'rgba(7, 10, 16, 0.88)',
        borderRadius: 'var(--radius-md)',
        border: '1px solid var(--border-color)',
        fontSize: '0.8125rem',
      }}
    >
      <div
        style={{
          display: 'flex',
          flexWrap: 'wrap',
          gap: '0.5rem',
          marginBottom: '0.5rem',
        }}
      >
        {/* Status Badge */}
        {currentJob.status === 'completed' && (
          <span className="badge badge-completed">
            <CheckCircle2 size={11} /> Ready
          </span>
        )}

        {/* Provider */}
        {provider && (
          <span
            style={{
              display: 'inline-flex',
              alignItems: 'center',
              gap: '4px',
              background: 'var(--bg-card)',
              border: '1px solid var(--border-color)',
              padding: '2px 8px',
              borderRadius: '4px',
              color: 'var(--text-secondary)',
            }}
          >
            <Layers size={12} />
            <span>{provider}</span>
          </span>
        )}

        {/* Model */}
        {model && (
          <span
            style={{
              display: 'inline-flex',
              alignItems: 'center',
              gap: '4px',
              background: 'var(--bg-card)',
              border: '1px solid var(--border-color)',
              padding: '2px 8px',
              borderRadius: '4px',
              color: 'var(--text-secondary)',
            }}
          >
            <Cpu size={12} />
            <span>{model.split('/')[1] || model}</span>
          </span>
        )}

        {/* Aspect Ratio */}
        {aspectRatio && (
          <span
            style={{
              display: 'inline-flex',
              alignItems: 'center',
              gap: '4px',
              background: 'var(--bg-card)',
              border: '1px solid var(--border-color)',
              padding: '2px 8px',
              borderRadius: '4px',
              color: 'var(--text-secondary)',
            }}
          >
            <Maximize2 size={12} />
            <span>{aspectRatio}</span>
          </span>
        )}

        {/* Duration for Video */}
        {isVideo && duration !== undefined && duration > 0 && (
          <span
            style={{
              display: 'inline-flex',
              alignItems: 'center',
              gap: '4px',
              background: 'var(--bg-card)',
              border: '1px solid var(--border-color)',
              padding: '2px 8px',
              borderRadius: '4px',
              color: 'var(--text-secondary)',
            }}
          >
            <Clock size={12} />
            <span>{duration}s</span>
          </span>
        )}

        {/* Total Cost USD */}
        {cost !== undefined && cost > 0 && (
          <span
            style={{
              display: 'inline-flex',
              alignItems: 'center',
              gap: '2px',
              background: 'rgba(16, 185, 129, 0.1)',
              border: '1px solid rgba(16, 185, 129, 0.25)',
              padding: '2px 8px',
              borderRadius: '4px',
              color: 'var(--success)',
              fontWeight: 600,
            }}
          >
            <span>${cost.toFixed(4)}</span>
          </span>
        )}
      </div>

      {/* Prompt preview */}
      {currentJob.prompt && (
        <div
          style={{
            color: 'var(--text-muted)',
            fontSize: '0.75rem',
            fontStyle: 'italic',
            overflow: 'hidden',
            textOverflow: 'ellipsis',
            whiteSpace: 'nowrap',
          }}
        >
          "{currentJob.prompt}"
        </div>
      )}
    </div>
  );
};
