import React from 'react';
import { Image, Video, Film } from 'lucide-react';
import { GenerationType } from '../types/creator';

interface GenerationTypeSelectorProps {
  selectedType: GenerationType;
  onChange: (type: GenerationType) => void;
}

export const GenerationTypeSelector: React.FC<GenerationTypeSelectorProps> = ({
  selectedType,
  onChange,
}) => {
  return (
    <div style={{ marginBottom: '1.25rem' }}>
      <label className="form-label">Generation Type</label>
      <div className="tab-group" role="tablist">
        <button
          type="button"
          role="tab"
          aria-selected={selectedType === 'image'}
          className={`tab-btn ${selectedType === 'image' ? 'active' : ''}`}
          onClick={() => onChange('image')}
          id="tab-image"
        >
          <Image size={16} />
          <span>Image</span>
        </button>

        <button
          type="button"
          role="tab"
          aria-selected={selectedType === 'video'}
          className={`tab-btn ${selectedType === 'video' ? 'active' : ''}`}
          onClick={() => onChange('video')}
          id="tab-video"
        >
          <Video size={16} />
          <span>Video</span>
        </button>

        <button
          type="button"
          role="tab"
          aria-selected={selectedType === 'image_to_video'}
          className={`tab-btn ${selectedType === 'image_to_video' ? 'active' : ''}`}
          onClick={() => onChange('image_to_video')}
          id="tab-image-to-video"
        >
          <Film size={16} />
          <span>Image → Video</span>
        </button>
      </div>
    </div>
  );
};
