import React from 'react';
import { PlayCircle, StopCircle, AlertCircle, CheckCircle2, Info } from 'lucide-react';
import { GenerationType, ModelCapability } from '../types/creator';
import { ReferenceUpload } from './ReferenceUpload';

interface StartEndFrameControlsProps {
  generationType: GenerationType;
  selectedModelObj?: ModelCapability;
  startFrameUrl?: string;
  onStartFrameChange: (url?: string) => void;
  endFrameUrl?: string;
  onEndFrameChange: (url?: string) => void;
}

export const StartEndFrameControls: React.FC<StartEndFrameControlsProps> = ({
  generationType,
  selectedModelObj,
  startFrameUrl,
  onStartFrameChange,
  endFrameUrl,
  onEndFrameChange,
}) => {
  if (generationType === 'image') {
    return null; // Not applicable for static image generation
  }

  const supportsStartFrame = Boolean(selectedModelObj?.start_frame);
  const supportsEndFrame = Boolean(selectedModelObj?.end_frame);

  return (
    <div style={{ marginBottom: '1.25rem', display: 'flex', flexDirection: 'column', gap: '1rem' }}>
      {/* Start / First Frame Control */}
      <div>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '0.375rem' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.375rem' }}>
            <PlayCircle size={15} color="var(--accent-primary)" />
            <span style={{ fontSize: '0.8125rem', fontWeight: 600, color: 'var(--text-secondary)', textTransform: 'uppercase', letterSpacing: '0.05em' }}>
              Start Frame (First Frame)
            </span>
          </div>
          {supportsStartFrame ? (
            <span style={{ fontSize: '0.6875rem', color: 'var(--success)', display: 'flex', alignItems: 'center', gap: '3px' }}>
              <CheckCircle2 size={11} /> Supported
            </span>
          ) : (
            <span style={{ fontSize: '0.6875rem', color: 'var(--text-muted)' }}>
              Unsupported
            </span>
          )}
        </div>

        {supportsStartFrame ? (
          <ReferenceUpload
            label=""
            sublabel="Base keyframe image from which motion begins"
            imageUrl={startFrameUrl}
            onImageChange={onStartFrameChange}
          />
        ) : (
          <div className="capability-disabled-box" data-testid="start-frame-unsupported">
            <Info size={16} />
            <span>
              The selected model (<strong>{selectedModelObj?.name || 'Current Model'}</strong>) does not support start-frame motion input.
            </span>
          </div>
        )}
      </div>

      {/* End / Last Frame Control */}
      <div>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '0.375rem' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.375rem' }}>
            <StopCircle size={15} color="var(--text-muted)" />
            <span style={{ fontSize: '0.8125rem', fontWeight: 600, color: 'var(--text-secondary)', textTransform: 'uppercase', letterSpacing: '0.05em' }}>
              End Frame (Last Frame)
            </span>
          </div>
          {supportsEndFrame ? (
            <span style={{ fontSize: '0.6875rem', color: 'var(--success)', display: 'flex', alignItems: 'center', gap: '3px' }}>
              <CheckCircle2 size={11} /> Supported
            </span>
          ) : (
            <span style={{ fontSize: '0.6875rem', color: 'var(--text-muted)' }} data-testid="end-frame-badge">
              Unsupported
            </span>
          )}
        </div>

        {supportsEndFrame ? (
          <ReferenceUpload
            label=""
            sublabel="Target ending frame to anchor the video transition"
            imageUrl={endFrameUrl}
            onImageChange={onEndFrameChange}
          />
        ) : (
          <div className="capability-disabled-box" data-testid="end-frame-unsupported">
            <AlertCircle size={16} />
            <span>
              End/last frame is <strong>disabled</strong>: The selected model/provider ({selectedModelObj?.name || 'Current Model'}) does not support end-frame anchoring in the backend.
            </span>
          </div>
        )}
      </div>
    </div>
  );
};
