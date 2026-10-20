import React from 'react';
import {
  Download,
  ExternalLink,
  Maximize2,
  Minimize2,
  ZoomIn,
  ZoomOut,
  ChevronLeft,
  ChevronRight,
} from 'lucide-react';

export interface ViewportControlsProps {
  zoomMode: 'fit' | 'actual';
  onToggleZoom: () => void;
  isFullscreen: boolean;
  onToggleFullscreen: () => void;
  downloadUrl?: string;
  downloadFilename?: string;
  externalUrl?: string;
  onPrev?: () => void;
  onNext?: () => void;
  hasPrev?: boolean;
  hasNext?: boolean;
}

export const ViewportControls: React.FC<ViewportControlsProps> = ({
  zoomMode,
  onToggleZoom,
  isFullscreen,
  onToggleFullscreen,
  downloadUrl,
  downloadFilename,
  externalUrl,
  onPrev,
  onNext,
  hasPrev = false,
  hasNext = false,
}) => {
  return (
    <div
      style={{
        display: 'flex',
        alignItems: 'center',
        gap: '0.375rem',
        flexWrap: 'wrap',
      }}
    >
      {/* History Navigation Controls */}
      {(hasPrev || hasNext) && (
        <div style={{ display: 'flex', gap: '2px', marginRight: '0.25rem' }}>
          <button
            type="button"
            onClick={onPrev}
            disabled={!hasPrev}
            className="btn-secondary"
            style={{ padding: '4px 6px' }}
            title="Previous Asset in History"
            aria-label="Previous Asset"
          >
            <ChevronLeft size={13} />
          </button>

          <button
            type="button"
            onClick={onNext}
            disabled={!hasNext}
            className="btn-secondary"
            style={{ padding: '4px 6px' }}
            title="Next Asset in History"
            aria-label="Next Asset"
          >
            <ChevronRight size={13} />
          </button>
        </div>
      )}

      {/* Sizing / Zoom Toggle */}
      <button
        type="button"
        onClick={onToggleZoom}
        className="btn-secondary"
        style={{ padding: '4px 8px', fontSize: '0.75rem' }}
        title={zoomMode === 'fit' ? 'Zoom to 100% scale' : 'Fit to viewport'}
        data-testid="btn-toggle-zoom"
      >
        {zoomMode === 'fit' ? (
          <>
            <ZoomIn size={12} />
            <span>100%</span>
          </>
        ) : (
          <>
            <ZoomOut size={12} />
            <span>Fit</span>
          </>
        )}
      </button>

      {/* Fullscreen Toggle */}
      <button
        type="button"
        onClick={onToggleFullscreen}
        className="btn-secondary"
        style={{ padding: '4px 8px', fontSize: '0.75rem' }}
        title={isFullscreen ? 'Exit Fullscreen' : 'Enter Fullscreen Viewport'}
        aria-label={isFullscreen ? 'Exit Fullscreen' : 'Fullscreen Viewport'}
        data-testid="btn-toggle-fullscreen"
      >
        {isFullscreen ? <Minimize2 size={12} /> : <Maximize2 size={12} />}
        <span>{isFullscreen ? 'Exit' : 'Expand'}</span>
      </button>

      {/* Download Action Link (Preserves required test contract) */}
      {downloadUrl && (
        <a
          href={downloadUrl}
          download={downloadFilename}
          className="btn-secondary"
          style={{ textDecoration: 'none' }}
          title="Download Asset"
          data-testid="btn-download-asset"
        >
          <Download size={14} />
          <span>Download</span>
        </a>
      )}

      {/* External Link */}
      {externalUrl && (
        <a
          href={externalUrl}
          target="_blank"
          rel="noreferrer"
          className="btn-secondary"
          style={{ textDecoration: 'none', padding: '4px 8px' }}
          title="Open in new tab"
        >
          <ExternalLink size={14} />
        </a>
      )}
    </div>
  );
};
