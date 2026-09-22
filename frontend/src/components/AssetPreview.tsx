import React from 'react';
import {
  Download,
  ExternalLink,
  Sparkles,
  Maximize2,
  Film,
  Image as ImageIcon,
  DollarSign,
  Clock,
  Layers,
  CheckCircle2,
} from 'lucide-react';
import { GenerationJob, GenerationType } from '../types/creator';
import { getDownloadProxyUrl } from '../api/creatorApi';

interface AssetPreviewProps {
  currentJob?: GenerationJob | null;
  previewUrl?: string;
  generationType: GenerationType;
  prompt?: string;
}

export const AssetPreview: React.FC<AssetPreviewProps> = ({
  currentJob,
  previewUrl,
  generationType,
  prompt,
}) => {
  const assetUrl = previewUrl || currentJob?.output?.asset_url || currentJob?.output?.storage_path;
  const isVideo =
    generationType === 'video' ||
    generationType === 'image_to_video' ||
    (assetUrl && (assetUrl.includes('.mp4') || assetUrl.includes('video')));

  const downloadFilename = `arya_${generationType}_${Date.now()}.${isVideo ? 'mp4' : 'png'}`;

  return (
    <div className="creator-card" style={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
      <div className="creator-card-header">
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
          {isVideo ? <Film size={18} color="var(--accent-primary)" /> : <ImageIcon size={18} color="var(--accent-primary)" />}
          <span className="card-title">Preview & Generated Asset</span>
        </div>

        {assetUrl && (
          <div style={{ display: 'flex', gap: '0.5rem' }}>
            <a
              href={getDownloadProxyUrl(assetUrl, downloadFilename)}
              download={downloadFilename}
              className="btn-secondary"
              style={{ textDecoration: 'none' }}
              title="Download Asset"
            >
              <Download size={14} />
              <span>Download</span>
            </a>
            {assetUrl.startsWith('http') && (
              <a
                href={assetUrl}
                target="_blank"
                rel="noreferrer"
                className="btn-secondary"
                style={{ textDecoration: 'none' }}
                title="Open in new tab"
              >
                <ExternalLink size={14} />
              </a>
            )}
          </div>
        )}
      </div>

      {/* Main Viewport */}
      <div style={{
        flex: 1,
        minHeight: '380px',
        maxHeight: '620px',
        backgroundColor: '#05070c',
        borderRadius: 'var(--radius-md)',
        border: '1px solid var(--border-color)',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        overflow: 'hidden',
        position: 'relative',
      }}>
        {assetUrl ? (
          isVideo ? (
            <video
              src={assetUrl}
              controls
              autoPlay
              loop
              style={{
                width: '100%',
                height: '100%',
                maxHeight: '600px',
                objectFit: 'contain',
              }}
              data-testid="video-player"
            />
          ) : (
            <img
              src={assetUrl}
              alt="Generated asset preview"
              style={{
                width: '100%',
                height: '100%',
                maxHeight: '600px',
                objectFit: 'contain',
              }}
              data-testid="image-preview"
            />
          )
        ) : (
          <div style={{
            textAlign: 'center',
            padding: '2rem',
            color: 'var(--text-muted)',
            display: 'flex',
            flexDirection: 'column',
            alignItems: 'center',
            gap: '0.75rem',
          }}>
            <div style={{
              width: '56px',
              height: '56px',
              borderRadius: '50%',
              backgroundColor: 'var(--bg-secondary)',
              border: '1px dashed var(--border-color)',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
            }}>
              <Sparkles size={24} color="var(--text-muted)" />
            </div>
            <div>
              <p style={{ fontSize: '0.9375rem', fontWeight: 600, color: 'var(--text-secondary)' }}>
                Creative Viewport Ready
              </p>
              <p style={{ fontSize: '0.8125rem', maxWidth: '300px', margin: '0.25rem auto 0' }}>
                Select generation parameters, write your prompt, and click Generate to see live results.
              </p>
            </div>
          </div>
        )}
      </div>

      {/* Generation Information Badges */}
      {assetUrl && currentJob && (
        <div style={{
          marginTop: '1rem',
          padding: '0.875rem',
          backgroundColor: 'var(--bg-primary)',
          borderRadius: 'var(--radius-md)',
          border: '1px solid var(--border-color)',
          fontSize: '0.8125rem',
        }}>
          <div style={{
            display: 'flex',
            flexWrap: 'wrap',
            gap: '0.5rem',
            marginBottom: '0.5rem',
          }}>
            <span className="badge badge-completed">
              <CheckCircle2 size={11} /> Ready
            </span>

            <span style={{
              display: 'inline-flex',
              alignItems: 'center',
              gap: '4px',
              background: 'var(--bg-card)',
              padding: '2px 8px',
              borderRadius: '4px',
              color: 'var(--text-secondary)',
            }}>
              <Layers size={12} />
              <span>{currentJob.output.provider_used || currentJob.provider || currentJob.model || 'Arya OS'}</span>
            </span>

            {currentJob.aspect_ratio && (
              <span style={{
                display: 'inline-flex',
                alignItems: 'center',
                gap: '4px',
                background: 'var(--bg-card)',
                padding: '2px 8px',
                borderRadius: '4px',
                color: 'var(--text-secondary)',
              }}>
                <Maximize2 size={12} />
                <span>{currentJob.aspect_ratio}</span>
              </span>
            )}

            {isVideo && (currentJob.duration_seconds || currentJob.output.duration_seconds) && (
              <span style={{
                display: 'inline-flex',
                alignItems: 'center',
                gap: '4px',
                background: 'var(--bg-card)',
                padding: '2px 8px',
                borderRadius: '4px',
                color: 'var(--text-secondary)',
              }}>
                <Clock size={12} />
                <span>{currentJob.output.duration_seconds || currentJob.duration_seconds}s</span>
              </span>
            )}

            {currentJob.total_cost_usd > 0 && (
              <span style={{
                display: 'inline-flex',
                alignItems: 'center',
                gap: '2px',
                background: 'rgba(16, 185, 129, 0.1)',
                border: '1px solid rgba(16, 185, 129, 0.25)',
                padding: '2px 8px',
                borderRadius: '4px',
                color: 'var(--success)',
                fontWeight: 600,
              }}>
                <span>${currentJob.total_cost_usd.toFixed(4)}</span>
              </span>
            )}
          </div>

          <div style={{ color: 'var(--text-muted)', fontSize: '0.75rem', fontStyle: 'italic', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
            "{currentJob.prompt}"
          </div>
        </div>
      )}
    </div>
  );
};
