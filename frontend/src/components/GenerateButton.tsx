import React from 'react';
import { Sparkles, Loader2, AlertTriangle } from 'lucide-react';
import { GenerationType } from '../types/creator';

interface GenerateButtonProps {
  generationType: GenerationType;
  isSubmitting: boolean;
  isJobRunning: boolean;
  onClick: () => void;
  disabled: boolean;
  error?: string | null;
}

export const GenerateButton: React.FC<GenerateButtonProps> = ({
  generationType,
  isSubmitting,
  isJobRunning,
  onClick,
  disabled,
  error,
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
        disabled={disabled || isSubmitting || isJobRunning}
        id="generateButton"
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
          alignItems: 'flex-start',
          gap: '0.5rem',
        }} role="alert">
          <AlertTriangle size={16} style={{ flexShrink: 0, marginTop: '2px' }} />
          <div>
            <strong style={{ display: 'block', marginBottom: '2px' }}>Generation Error</strong>
            <span>{error}</span>
          </div>
        </div>
      )}
    </div>
  );
};
