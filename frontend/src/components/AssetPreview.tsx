import React, { useState } from 'react';
import { Film, Image as ImageIcon, Sparkles } from 'lucide-react';
import { GenerationJob, GenerationType, HistoryItem } from '../types/creator';
import { getDownloadProxyUrl } from '../api/creatorApi';
import { ViewportFrame } from './viewport/ViewportFrame';
import { ViewportControls } from './viewport/ViewportControls';
import { ViewportTelemetry } from './viewport/ViewportTelemetry';

interface AssetPreviewProps {
  currentJob?: GenerationJob | null;
  previewUrl?: string;
  generationType: GenerationType;
  prompt?: string;
  history?: HistoryItem[];
  onSelectHistoryItem?: (item: HistoryItem) => void;
}

export const AssetPreview: React.FC<AssetPreviewProps> = ({
  currentJob,
  previewUrl,
  generationType,
  history = [],
  onSelectHistoryItem,
}) => {
  const [zoomMode, setZoomMode] = useState<'fit' | 'actual'>('fit');
  const [isFullscreen, setIsFullscreen] = useState(false);

  const assetUrl = previewUrl || currentJob?.output?.asset_url || currentJob?.output?.storage_path;
  const isVideo =
    generationType === 'video' ||
    generationType === 'image_to_video' ||
    Boolean(assetUrl && (assetUrl.includes('.mp4') || assetUrl.includes('video')));

  const downloadFilename = `arya_${generationType}_${Date.now()}.${isVideo ? 'mp4' : 'png'}`;
  const downloadProxyUrl = assetUrl ? getDownloadProxyUrl(assetUrl, downloadFilename) : undefined;

  // History Prev / Next navigation
  const currentHistoryIndex = history.findIndex(
    (item) => item.job_id === currentJob?.job_id
  );
  const hasPrev = currentHistoryIndex > 0;
  const hasNext = currentHistoryIndex >= 0 && currentHistoryIndex < history.length - 1;

  const handlePrev = () => {
    if (hasPrev && onSelectHistoryItem) {
      onSelectHistoryItem(history[currentHistoryIndex - 1]);
    }
  };

  const handleNext = () => {
    if (hasNext && onSelectHistoryItem) {
      onSelectHistoryItem(history[currentHistoryIndex + 1]);
    }
  };

  const handleToggleFullscreen = () => {
    setIsFullscreen((prev) => !prev);
  };

  const handleToggleZoom = () => {
    setZoomMode((prev) => (prev === 'fit' ? 'actual' : 'fit'));
  };

  return (
    <div
      className="creator-card"
      style={{
        display: 'flex',
        flexDirection: 'column',
        height: '100%',
      }}
    >
      {/* Viewport Header */}
      <div className="creator-card-header">
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
          {isVideo ? (
            <Film size={18} color="var(--accent-primary)" />
          ) : (
            <ImageIcon size={18} color="var(--accent-primary)" />
          )}
          <span className="card-title">Preview & Generated Asset</span>
        </div>

        {/* Viewport Controls Bar */}
        <ViewportControls
          zoomMode={zoomMode}
          onToggleZoom={handleToggleZoom}
          isFullscreen={isFullscreen}
          onToggleFullscreen={handleToggleFullscreen}
          downloadUrl={downloadProxyUrl}
          downloadFilename={downloadFilename}
          externalUrl={assetUrl?.startsWith('http') ? assetUrl : undefined}
          onPrev={handlePrev}
          onNext={handleNext}
          hasPrev={hasPrev}
          hasNext={hasNext}
        />
      </div>

      {/* Cinematic Viewport Frame */}
      <ViewportFrame
        zoomMode={zoomMode}
        isFullscreen={isFullscreen}
        isLoading={currentJob?.status === 'in_progress'}
        hasMedia={Boolean(assetUrl)}
      >
        {assetUrl ? (
          isVideo ? (
            <video
              src={assetUrl}
              controls
              autoPlay
              loop
              style={{
                width: zoomMode === 'actual' ? 'auto' : '100%',
                height: zoomMode === 'actual' ? 'auto' : '100%',
                maxHeight: zoomMode === 'actual' ? 'none' : '600px',
                objectFit: zoomMode === 'actual' ? 'none' : 'contain',
              }}
              data-testid="video-player"
            />
          ) : (
            <img
              src={assetUrl}
              alt="Generated asset preview"
              style={{
                width: zoomMode === 'actual' ? 'auto' : '100%',
                height: zoomMode === 'actual' ? 'auto' : '100%',
                maxHeight: zoomMode === 'actual' ? 'none' : '600px',
                objectFit: zoomMode === 'actual' ? 'none' : 'contain',
              }}
              data-testid="image-preview"
            />
          )
        ) : (
          <div
            className="viewport-empty-state"
            style={{
              textAlign: 'center',
              padding: '2.5rem 1.5rem',
              color: 'var(--text-muted)',
              display: 'flex',
              flexDirection: 'column',
              alignItems: 'center',
              gap: '1rem',
              position: 'relative',
              zIndex: 3,
            }}
          >
            {/* Ambient Orbital Geometry & Center Spark */}
            <div
              style={{
                position: 'relative',
                width: '84px',
                height: '84px',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
              }}
            >
              {/* Outer faint orbital ring */}
              <div
                style={{
                  position: 'absolute',
                  inset: 0,
                  borderRadius: '50%',
                  border: '1px dashed rgba(59, 130, 246, 0.25)',
                }}
              />
              {/* Secondary ring */}
              <div
                style={{
                  position: 'absolute',
                  inset: '10px',
                  borderRadius: '50%',
                  border: '1px solid rgba(59, 130, 246, 0.18)',
                }}
              />
              {/* Center nucleus */}
              <div
                style={{
                  width: '46px',
                  height: '46px',
                  borderRadius: '50%',
                  backgroundColor: 'rgba(10, 16, 28, 0.95)',
                  border: '1px solid rgba(59, 130, 246, 0.4)',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  boxShadow: '0 0 20px rgba(59, 130, 246, 0.22)',
                }}
              >
                <Sparkles size={20} color="var(--accent-primary)" style={{ opacity: 0.95 }} />
              </div>
            </div>

            {/* Conceptual Hierarchy */}
            <div>
              <span
                style={{
                  fontSize: '0.6875rem',
                  fontWeight: 700,
                  letterSpacing: '0.12em',
                  textTransform: 'uppercase',
                  color: 'var(--accent-primary)',
                  display: 'block',
                  marginBottom: '0.375rem',
                }}
              >
                CREATIVE VIEWPORT
              </span>
              <p
                style={{
                  fontSize: '0.9375rem',
                  fontWeight: 600,
                  color: 'var(--text-primary)',
                  letterSpacing: '0.02em',
                  marginBottom: '0.375rem',
                }}
              >
                READY FOR SYNTHESIS
              </p>
              <p
                style={{
                  fontSize: '0.8125rem',
                  color: 'var(--text-muted)',
                  maxWidth: '320px',
                  margin: '0 auto',
                  lineHeight: 1.45,
                }}
              >
                Select your generation parameters and submit a prompt to begin.
              </p>
            </div>
          </div>
        )}
      </ViewportFrame>

      {/* Generation Information & Telemetry Layer */}
      {assetUrl && currentJob && (
        <ViewportTelemetry currentJob={currentJob} isVideo={isVideo} />
      )}
    </div>
  );
};
