import React, { useRef, useState } from 'react';
import { Upload, X, Image as ImageIcon, Link, Loader2 } from 'lucide-react';
import { uploadAsset } from '../api/creatorApi';

interface ReferenceUploadProps {
  label: string;
  sublabel?: string;
  imageUrl?: string;
  onImageChange: (url?: string) => void;
  disabled?: boolean;
}

export const ReferenceUpload: React.FC<ReferenceUploadProps> = ({
  label,
  sublabel,
  imageUrl,
  onImageChange,
  disabled = false,
}) => {
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [isUploading, setIsUploading] = useState(false);
  const [isUrlMode, setIsUrlMode] = useState(false);
  const [urlInput, setUrlInput] = useState('');
  const [uploadError, setUploadError] = useState<string | null>(null);

  const handleFileSelected = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;

    setIsUploading(true);
    setUploadError(null);
    try {
      const res = await uploadAsset(file);
      onImageChange(res.url);
    } catch (err: any) {
      setUploadError(err.message || 'File upload failed');
    } finally {
      setIsUploading(false);
      if (fileInputRef.current) fileInputRef.current.value = '';
    }
  };

  const handleUrlSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (urlInput.trim()) {
      onImageChange(urlInput.trim());
      setIsUrlMode(false);
      setUrlInput('');
    }
  };

  return (
    <div style={{ marginBottom: '1.25rem', opacity: disabled ? 0.6 : 1 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '0.5rem' }}>
        <label className="form-label" style={{ marginBottom: 0 }}>{label}</label>
        {!disabled && !imageUrl && (
          <button
            type="button"
            onClick={() => setIsUrlMode(!isUrlMode)}
            style={{
              background: 'transparent',
              border: 'none',
              color: 'var(--accent-primary)',
              fontSize: '0.75rem',
              cursor: 'pointer',
              display: 'flex',
              alignItems: 'center',
              gap: '3px',
            }}
          >
            <Link size={11} />
            {isUrlMode ? 'Upload File' : 'Paste URL'}
          </button>
        )}
      </div>

      {sublabel && (
        <p style={{ fontSize: '0.75rem', color: 'var(--text-muted)', marginBottom: '0.5rem' }}>
          {sublabel}
        </p>
      )}

      {imageUrl ? (
        <div style={{
          position: 'relative',
          borderRadius: 'var(--radius-md)',
          overflow: 'hidden',
          border: '1px solid var(--border-color)',
          maxHeight: '140px',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          background: 'var(--bg-primary)',
        }}>
          <img
            src={imageUrl}
            alt="Reference preview"
            style={{ width: '100%', height: '140px', objectFit: 'cover' }}
          />
          <button
            type="button"
            onClick={() => onImageChange(undefined)}
            style={{
              position: 'absolute',
              top: '0.5rem',
              right: '0.5rem',
              backgroundColor: 'rgba(0, 0, 0, 0.7)',
              color: '#ffffff',
              border: 'none',
              borderRadius: '50%',
              width: '24px',
              height: '24px',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              cursor: 'pointer',
            }}
            title="Remove image"
          >
            <X size={14} />
          </button>
        </div>
      ) : isUrlMode ? (
        <form onSubmit={handleUrlSubmit} style={{ display: 'flex', gap: '0.5rem' }}>
          <input
            type="url"
            className="form-input"
            placeholder="https://example.com/image.png"
            value={urlInput}
            onChange={(e) => setUrlInput(e.target.value)}
            disabled={disabled}
            autoFocus
          />
          <button type="submit" className="btn-secondary" disabled={disabled || !urlInput.trim()}>
            Add
          </button>
        </form>
      ) : (
        <div>
          <input
            ref={fileInputRef}
            type="file"
            accept="image/*"
            onChange={handleFileSelected}
            style={{ display: 'none' }}
            disabled={disabled || isUploading}
          />
          <div
            onClick={() => !disabled && !isUploading && fileInputRef.current?.click()}
            style={{
              border: '2px dashed var(--border-color)',
              borderRadius: 'var(--radius-md)',
              padding: '1rem',
              textAlign: 'center',
              cursor: disabled || isUploading ? 'not-allowed' : 'pointer',
              backgroundColor: 'var(--bg-primary)',
              transition: 'all 0.15s ease',
            }}
          >
            {isUploading ? (
              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '0.5rem', color: 'var(--accent-primary)' }}>
                <Loader2 size={20} className="animate-spin" />
                <span style={{ fontSize: '0.8125rem' }}>Uploading reference...</span>
              </div>
            ) : (
              <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: '0.375rem' }}>
                <Upload size={20} color="var(--text-muted)" />
                <span style={{ fontSize: '0.8125rem', color: 'var(--text-secondary)' }}>
                  Click to upload or drag & drop
                </span>
                <span style={{ fontSize: '0.6875rem', color: 'var(--text-muted)' }}>
                  PNG, JPG, WebP up to 15MB
                </span>
              </div>
            )}
          </div>
        </div>
      )}

      {uploadError && (
        <p style={{ color: 'var(--danger)', fontSize: '0.75rem', marginTop: '0.375rem' }}>
          {uploadError}
        </p>
      )}
    </div>
  );
};
