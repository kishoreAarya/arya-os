import React from 'react';
import { Sparkles, Loader2, AlertTriangle, RotateCcw } from 'lucide-react';
import { GenerationType } from '../types/creator';

interface GenerateButtonProps {
  generationType: GenerationType;
  isSubmitting: boolean;
  isJobRunning: boolean;
  onClick: () => void;
  onRetry?: () => void;
  disabled: boolean;
  error?: string | null;
  isPreflightBlocked?: boolean;
}

export const GenerateButton: React.FC<GenerateButtonProps> = ({
  generationType,
  isSubmitting,
  isJobRunning,
  onClick,
  onRetry,
  disabled,
  error,
  isPreflightBlocked = false,
}) => {
  const getButtonText = () => {
    if (isSubmitting) return 'Submitting Job...';
    if (isJobRunning) return 'Generation in Progress...';
    switch (generationType) {
      case 'image':
        return 'Generate Image';
      case 'video':
        return 'Generate Video';
      case 'image_to_video':
        return 'Animate Image → Video';
    }
  };

  return (
    <div style={{ marginTop: '1rem' }}>
      <button
        type="button"
        className="btn-primary"
        onClick={onClick}
        disabled={disabled || isSubmitting || isJobRunning || isPreflightBlocked}
        id="generateButton"
        data-testid="generate-button"
        data-preflight-ready={!isPreflightBlocked ? 'true' : 'false'}
      >
        {isSubmitting || isJobRunning ? (
          <Loader2 size={18} className="animate-spin" />
        ) : (
          <Sparkles size={18} />
        )}
        <span>{getButtonText()}</span>
      </button>

      {error && (
        <div style={{
          marginTop: '0.75rem',
          padding: '0.75rem',
          backgroundColor: 'rgba(239, 68, 68, 0.1)',
          border: '1px solid rgba(239, 68, 68, 0.3)',
          borderRadius: 'var(--radius-md)',
          color: '#f87171',
          fontSize: '0.8125rem',
          display: 'flex',
          flexDirection: 'column',
          gap: '0.5rem',
        }} role="alert">
          <div style={{ display: 'flex', alignItems: 'flex-start', gap: '0.5rem' }}>
            <AlertTriangle size={16} style={{ flexShrink: 0, marginTop: '2px' }} />
            <div>
              <strong style={{ display: 'block', marginBottom: '2px' }}>Generation Error</strong>
              <span>{error}</span>
            </div>
          </div>
          {onRetry && (
            <button
              type="button"
              onClick={onRetry}
              className="btn-secondary"
              style={{
                alignSelf: 'flex-start',
                borderColor: 'rgba(239, 68, 68, 0.4)',
                color: '#ffffff',
                backgroundColor: 'rgba(239, 68, 68, 0.2)',
                padding: '4px 10px',
                fontSize: '0.75rem',
                display: 'inline-flex',
                alignItems: 'center',
                gap: '4px',
              }}
              data-testid="retry-generation-button"
            >
              <RotateCcw size={12} />
              <span>Retry Generation</span>
            </button>
          )}
        </div>
      )}
    </div>
  );
};
