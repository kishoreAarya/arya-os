import React from 'react';
import { Wand2, X } from 'lucide-react';
import { GenerationType } from '../types/creator';

interface PromptSectionProps {
  prompt: string;
  onChange: (value: string) => void;
  generationType: GenerationType;
  error?: string | null;
}

const SAMPLE_PROMPTS: Record<GenerationType, string[]> = {
  image: [
    'Cinematic wide shot of a futuristic cyberpunk observatory overlooking neon skyscrapers, 35mm lens, atmospheric haze',
    'Medium close-up portrait of a Renaissance astronomer analyzing brass astrolabes in candlelight, oil painting aesthetic',
    'Hyper-detailed macro photograph of morning dewdrops on bioluminescent rainforest moss, soft natural morning sunlight',
  ],
  video: [
    'Slow cinematic dolly forward revealing an ancient obsidian monolith glowing softly at dusk, atmospheric fog drifting',
    'Dramatic drone pull-back across roaring stormy ocean cliffs into cloudy sunset sky, 24fps motion blur',
  ],
  image_to_video: [
    'Subtle natural camera push-in with gentle wind moving hair and background trees, realistic motion',
    'Slow pan right across scenery with gentle depth-of-field transition, steady cinematic handheld motion',
  ],
};

export const PromptSection: React.FC<PromptSectionProps> = ({
  prompt,
  onChange,
  generationType,
  error,
}) => {
  const maxLength = 2000;
  const samples = SAMPLE_PROMPTS[generationType] || SAMPLE_PROMPTS.image;

  return (
    <div style={{ marginBottom: '1.25rem' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '0.5rem' }}>
        <label className="form-label" htmlFor="promptInput" style={{ marginBottom: 0 }}>
          Prompt <span style={{ color: 'var(--danger)' }}>*</span>
        </label>
        <span style={{ fontSize: '0.75rem', color: prompt.length > maxLength ? 'var(--danger)' : 'var(--text-muted)' }}>
          {prompt.length} / {maxLength}
        </span>
      </div>

      <div style={{ position: 'relative' }}>
        <textarea
          id="promptInput"
          className="form-textarea"
          rows={4}
          value={prompt}
          onChange={(e) => onChange(e.target.value)}
          placeholder={
            generationType === 'image'
              ? 'Describe the image scene, lighting, camera angle, and visual aesthetics...'
              : generationType === 'image_to_video'
              ? 'Describe how the reference image should animate, camera motion, dynamics...'
              : 'Describe the video scene, camera movements, and cinematic action...'
          }
          style={{
            borderColor: error ? 'var(--danger)' : undefined,
            resize: 'vertical',
            minHeight: '90px',
          }}
        />

        {prompt && (
          <button
            type="button"
            onClick={() => onChange('')}
            style={{
              position: 'absolute',
              top: '0.5rem',
              right: '0.5rem',
              background: 'rgba(0, 0, 0, 0.4)',
              border: 'none',
              borderRadius: '4px',
              color: 'var(--text-muted)',
              cursor: 'pointer',
              padding: '2px',
            }}
            title="Clear prompt"
          >
            <X size={14} />
          </button>
        )}
      </div>

      {error && (
        <p style={{ color: 'var(--danger)', fontSize: '0.75rem', marginTop: '0.375rem' }} role="alert">
          {error}
        </p>
      )}

      {/* Suggestion Chips */}
      <div style={{ marginTop: '0.5rem', display: 'flex', flexWrap: 'wrap', gap: '0.375rem', alignItems: 'center' }}>
        <span style={{ fontSize: '0.6875rem', color: 'var(--text-muted)', display: 'flex', alignItems: 'center', gap: '2px' }}>
          <Wand2 size={11} /> Try:
        </span>
        {samples.map((sample, idx) => (
          <button
            key={idx}
            type="button"
            onClick={() => onChange(sample)}
            style={{
              background: 'var(--bg-primary)',
              border: '1px solid var(--border-color)',
              borderRadius: '9999px',
              color: 'var(--text-secondary)',
              fontSize: '0.6875rem',
              padding: '2px 8px',
              cursor: 'pointer',
              whiteSpace: 'nowrap',
              maxWidth: '220px',
              overflow: 'hidden',
              textOverflow: 'ellipsis',
              transition: 'all 0.15s ease',
            }}
            title={sample}
          >
            {sample}
          </button>
        ))}
      </div>
    </div>
  );
};
