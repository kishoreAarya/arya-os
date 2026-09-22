import React from 'react';
import { Layers, Clock, Maximize2, ShieldCheck, AlertCircle } from 'lucide-react';
import {
  AspectRatioOption,
  DurationOption,
  GenerationType,
  ModelCapability,
  ResolutionOption,
} from '../types/creator';

interface ConfigPanelProps {
  generationType: GenerationType;
  models: ModelCapability[];
  selectedModel: string;
  onModelChange: (modelId: string) => void;
  aspectRatios: AspectRatioOption[];
  selectedAspectRatio: string;
  onAspectRatioChange: (ar: string) => void;
  resolutions: ResolutionOption[];
  selectedResolution: string;
  onResolutionChange: (res: string) => void;
  durations: DurationOption[];
  selectedDuration: number;
  onDurationChange: (dur: number) => void;
}

export const ConfigPanel: React.FC<ConfigPanelProps> = ({
  generationType,
  models,
  selectedModel,
  onModelChange,
  aspectRatios,
  selectedAspectRatio,
  onAspectRatioChange,
  resolutions,
  selectedResolution,
  onResolutionChange,
  durations,
  selectedDuration,
  onDurationChange,
}) => {
  const currentModelObj = models.find((m) => m.id === selectedModel);
  const isVideo = generationType === 'video' || generationType === 'image_to_video';

  const getAspectPreviewStyle = (id: string) => {
    switch (id) {
      case '16:9':
        return { width: '28px', height: '16px' };
      case '9:16':
        return { width: '16px', height: '28px' };
      case '1:1':
        return { width: '22px', height: '22px' };
      case '4:5':
        return { width: '18px', height: '24px' };
      default:
        return { width: '22px', height: '22px' };
    }
  };

  return (
    <div style={{ marginBottom: '1.25rem' }}>
      {/* Model Selection */}
      <div style={{ marginBottom: '1rem' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '0.5rem' }}>
          <label className="form-label" htmlFor="modelSelect" style={{ marginBottom: 0 }}>
            Model
          </label>
          {currentModelObj && (
            <span style={{
              fontSize: '0.6875rem',
              display: 'flex',
              alignItems: 'center',
              gap: '4px',
              color: currentModelObj.configured ? 'var(--success)' : 'var(--warning)',
            }}>
              {currentModelObj.configured ? (
                <>
                  <ShieldCheck size={12} />
                  <span>Provider Configured</span>
                </>
              ) : (
                <>
                  <AlertCircle size={12} />
                  <span>Key Pending in .env</span>
                </>
              )}
            </span>
          )}
        </div>

        <select
          id="modelSelect"
          className="form-select"
          value={selectedModel}
          onChange={(e) => onModelChange(e.target.value)}
        >
          {models.map((model) => (
            <option key={model.id} value={model.id}>
              {model.name} [{model.provider.toUpperCase()}] {model.configured ? '' : '(Key unconfigured)'}
            </option>
          ))}
        </select>
      </div>

      {/* Aspect Ratio */}
      <div style={{ marginBottom: '1rem' }}>
        <label className="form-label">Aspect Ratio</label>
        <div className="aspect-grid" role="radiogroup" aria-label="Aspect Ratio">
          {aspectRatios.map((ar) => (
            <button
              key={ar.id}
              type="button"
              role="radio"
              aria-checked={selectedAspectRatio === ar.id}
              className={`aspect-option ${selectedAspectRatio === ar.id ? 'selected' : ''}`}
              onClick={() => onAspectRatioChange(ar.id)}
            >
              <div
                className="aspect-preview-rect"
                style={getAspectPreviewStyle(ar.id)}
              />
              <span style={{ fontSize: '0.75rem', fontWeight: 600 }}>{ar.id}</span>
            </button>
          ))}
        </div>
      </div>

      {/* Resolution */}
      <div style={{ marginBottom: '1rem' }}>
        <label className="form-label" htmlFor="resolutionSelect">
          Resolution
        </label>
        <select
          id="resolutionSelect"
          className="form-select"
          value={selectedResolution}
          onChange={(e) => onResolutionChange(e.target.value)}
        >
          {resolutions.map((res) => (
            <option key={res.id} value={res.id}>
              {res.label}
            </option>
          ))}
        </select>
      </div>

      {/* Video Duration (Video only) */}
      {isVideo && (
        <div style={{ marginBottom: '1rem' }}>
          <label className="form-label">
            Video Duration <span style={{ textTransform: 'none', color: 'var(--text-muted)' }}>(video only)</span>
          </label>
          <div style={{ display: 'flex', gap: '0.5rem' }}>
            {durations.map((dur) => (
              <button
                key={dur.value}
                type="button"
                onClick={() => onDurationChange(dur.value)}
                style={{
                  flex: 1,
                  padding: '0.5rem 0.75rem',
                  borderRadius: 'var(--radius-md)',
                  background: selectedDuration === dur.value ? 'rgba(99, 102, 241, 0.15)' : 'var(--bg-primary)',
                  border: `1px solid ${selectedDuration === dur.value ? 'var(--accent-primary)' : 'var(--border-color)'}`,
                  color: selectedDuration === dur.value ? 'var(--accent-primary)' : 'var(--text-secondary)',
                  fontSize: '0.8125rem',
                  fontWeight: 600,
                  cursor: 'pointer',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  gap: '0.375rem',
                  transition: 'all 0.15s ease',
                }}
              >
                <Clock size={14} />
                <span>{dur.label}</span>
              </button>
            ))}
          </div>
        </div>
      )}
    </div>
  );
};
