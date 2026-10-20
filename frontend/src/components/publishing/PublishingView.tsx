import React, { useEffect, useState } from 'react';
import {
  Share2,
  RefreshCw,
  CheckCircle2,
  XCircle,
  AlertTriangle,
  Send,
  Shield,
  Layers,
  HelpCircle,
  Globe,
  Radio,
  FileCheck,
} from 'lucide-react';
import { executePublishTest, fetchPublishingStatus } from '../../api/dashboardApi';
import { PublishingStatusResponse, PublishResponse } from '../../types/dashboard';

export const PublishingView: React.FC = () => {
  const [status, setStatus] = useState<PublishingStatusResponse | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Dry-run simulation form state
  const [assetPath, setAssetPath] = useState('videos/production_render.mp4');
  const [title, setTitle] = useState('AryaOS Cinematic Reel');
  const [caption, setCaption] = useState('Autonomous generation by AryaOS #AI #Shorts');
  const [socialPlatform, setSocialPlatform] = useState('youtube');
  const [selectedChannelId, setSelectedChannelId] = useState<string>('');

  const [isSimulating, setIsSimulating] = useState(false);
  const [simulationResult, setSimulationResult] = useState<PublishResponse | null>(null);
  const [simulationError, setSimulationError] = useState<string | null>(null);

  useEffect(() => {
    loadStatus();
  }, []);

  const loadStatus = async () => {
    setIsLoading(true);
    setError(null);
    try {
      const data = await fetchPublishingStatus();
      setStatus(data);
      if (data.channels.length > 0 && !selectedChannelId) {
        setSelectedChannelId(data.channels[0].id || '');
      }
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Failed to load publishing status';
      setError(msg);
    } finally {
      setIsLoading(false);
    }
  };

  const handleDryRunPublish = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!assetPath.trim()) {
      setSimulationError('Please provide an asset storage path.');
      return;
    }

    setIsSimulating(true);
    setSimulationError(null);
    setSimulationResult(null);

    try {
      // executePublishTest explicitly enforces dry_run: true
      const result = await executePublishTest({
        asset_storage_path: assetPath.trim(),
        title: title.trim(),
        caption: caption.trim(),
        platform: 'postiz',
        social_platform: socialPlatform,
        integration_id: selectedChannelId || undefined,
        publish_type: 'draft',
        dry_run: true,
      });

      setSimulationResult(result);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Publish dry-run simulation failed';
      setSimulationError(msg);
    } finally {
      setIsSimulating(false);
    }
  };

  return (
    <div style={{ maxWidth: '1600px', margin: '0 auto', padding: '1.5rem', width: '100%' }}>
      {/* Header */}
      <div
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          marginBottom: '1.5rem',
        }}
      >
        <div>
          <h2
            style={{
              fontSize: '1.25rem',
              fontWeight: 700,
              color: 'var(--text-primary)',
              display: 'flex',
              alignItems: 'center',
              gap: '0.5rem',
            }}
          >
            <Share2 size={22} color="var(--accent-primary)" />
            Publishing & Distribution Center
          </h2>
          <p style={{ fontSize: '0.8125rem', color: 'var(--text-muted)', marginTop: '0.25rem' }}>
            Inspect Postiz social channel connectivity and safely simulate release dispatches.
          </p>
        </div>

        <button
          type="button"
          onClick={loadStatus}
          disabled={isLoading}
          className="btn-secondary"
          style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}
        >
          <RefreshCw size={14} className={isLoading ? 'animate-spin' : ''} />
          <span>Probe Gateway</span>
        </button>
      </div>

      <div
        style={{
          display: 'grid',
          gridTemplateColumns: '1fr 480px',
          gap: '1.5rem',
          alignItems: 'start',
        }}
      >
        {/* Left Column: Connectivity & Channels */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: '1.5rem' }}>
          {/* Status Probe Card */}
          <div className="creator-card">
            <h3
              style={{
                fontSize: '0.9375rem',
                fontWeight: 600,
                color: 'var(--text-primary)',
                marginBottom: '1rem',
                display: 'flex',
                alignItems: 'center',
                gap: '0.5rem',
              }}
            >
              <Radio size={16} color="var(--accent-primary)" />
              Gateway Connectivity Probe
            </h3>

            {isLoading ? (
              <div style={{ padding: '2rem', textAlign: 'center', color: 'var(--text-muted)' }}>
                <RefreshCw size={20} className="animate-spin" style={{ margin: '0 auto 0.5rem' }} />
                <p style={{ fontSize: '0.8125rem' }}>Checking Postiz API credentials and reachability...</p>
              </div>
            ) : error ? (
              <div
                style={{
                  padding: '1.25rem',
                  borderRadius: '6px',
                  backgroundColor: 'rgba(239, 68, 68, 0.05)',
                  border: '1px solid rgba(239, 68, 68, 0.3)',
                  color: 'var(--danger)',
                  fontSize: '0.8125rem',
                }}
              >
                <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', fontWeight: 600 }}>
                  <XCircle size={16} />
                  Gateway Unreachable
                </div>
                <p style={{ marginTop: '0.25rem' }}>{error}</p>
              </div>
            ) : status ? (
              <div style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
                <div
                  style={{
                    display: 'grid',
                    gridTemplateColumns: 'repeat(3, 1fr)',
                    gap: '0.75rem',
                  }}
                >
                  <div
                    style={{
                      padding: '0.75rem',
                      borderRadius: '6px',
                      backgroundColor: 'var(--bg-primary)',
                      border: '1px solid var(--border-color)',
                    }}
                  >
                    <span style={{ fontSize: '0.6875rem', color: 'var(--text-muted)' }}>Platform</span>
                    <span
                      style={{
                        display: 'block',
                        fontWeight: 600,
                        fontSize: '0.875rem',
                        color: 'var(--text-primary)',
                        textTransform: 'capitalize',
                        marginTop: '2px',
                      }}
                    >
                      {status.platform}
                    </span>
                  </div>

                  <div
                    style={{
                      padding: '0.75rem',
                      borderRadius: '6px',
                      backgroundColor: 'var(--bg-primary)',
                      border: '1px solid var(--border-color)',
                    }}
                  >
                    <span style={{ fontSize: '0.6875rem', color: 'var(--text-muted)' }}>Reachable</span>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '0.375rem', marginTop: '2px' }}>
                      {status.reachable ? (
                        <CheckCircle2 size={14} color="var(--success)" />
                      ) : (
                        <XCircle size={14} color="var(--danger)" />
                      )}
                      <span
                        style={{
                          fontWeight: 600,
                          fontSize: '0.875rem',
                          color: status.reachable ? 'var(--success)' : 'var(--danger)',
                        }}
                      >
                        {status.reachable ? 'Reachable' : 'Offline'}
                      </span>
                    </div>
                  </div>

                  <div
                    style={{
                      padding: '0.75rem',
                      borderRadius: '6px',
                      backgroundColor: 'var(--bg-primary)',
                      border: '1px solid var(--border-color)',
                    }}
                  >
                    <span style={{ fontSize: '0.6875rem', color: 'var(--text-muted)' }}>Channels</span>
                    <span
                      style={{
                        display: 'block',
                        fontWeight: 600,
                        fontSize: '0.875rem',
                        color: 'var(--text-primary)',
                        marginTop: '2px',
                      }}
                    >
                      {status.connected_channels} Connected
                    </span>
                  </div>
                </div>

                {status.error && (
                  <div
                    style={{
                      padding: '0.75rem',
                      borderRadius: '6px',
                      backgroundColor: 'rgba(245, 158, 11, 0.08)',
                      border: '1px solid rgba(245, 158, 11, 0.3)',
                      color: 'var(--warning)',
                      fontSize: '0.75rem',
                      display: 'flex',
                      alignItems: 'center',
                      gap: '0.5rem',
                    }}
                  >
                    <AlertTriangle size={14} />
                    <span>{status.error}</span>
                  </div>
                )}
              </div>
            ) : null}
          </div>

          {/* Connected Channels List */}
          <div className="creator-card">
            <h3
              style={{
                fontSize: '0.9375rem',
                fontWeight: 600,
                color: 'var(--text-primary)',
                marginBottom: '1rem',
                display: 'flex',
                alignItems: 'center',
                gap: '0.5rem',
              }}
            >
              <Globe size={16} color="var(--accent-primary)" />
              Connected Publishing Channels
            </h3>

            {!status || status.channels.length === 0 ? (
              <div style={{ padding: '2rem', textAlign: 'center', color: 'var(--text-muted)' }}>
                <Share2 size={24} style={{ margin: '0 auto 0.5rem', opacity: 0.4 }} />
                <p style={{ fontSize: '0.8125rem' }}>No channels currently linked in Postiz.</p>
                <p style={{ fontSize: '0.75rem', color: 'var(--text-muted)', marginTop: '0.25rem' }}>
                  Connect YouTube, TikTok, or Instagram accounts via the Postiz console.
                </p>
              </div>
            ) : (
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '0.75rem' }}>
                {status.channels.map((ch, idx) => (
                  <div
                    key={ch.id || idx}
                    style={{
                      padding: '0.875rem',
                      borderRadius: '6px',
                      backgroundColor: 'var(--bg-primary)',
                      border: '1px solid var(--border-color)',
                      display: 'flex',
                      alignItems: 'center',
                      gap: '0.75rem',
                    }}
                  >
                    <div
                      style={{
                        width: '32px',
                        height: '32px',
                        borderRadius: '6px',
                        backgroundColor: 'var(--bg-card)',
                        display: 'flex',
                        alignItems: 'center',
                        justifyContent: 'center',
                        color: 'var(--accent-primary)',
                      }}
                    >
                      <Share2 size={16} />
                    </div>
                    <div>
                      <span
                        style={{
                          fontWeight: 600,
                          fontSize: '0.8125rem',
                          color: 'var(--text-primary)',
                          display: 'block',
                        }}
                      >
                        {ch.name || 'Unnamed Channel'}
                      </span>
                      <span
                        style={{
                          fontSize: '0.6875rem',
                          color: 'var(--text-muted)',
                          textTransform: 'uppercase',
                        }}
                      >
                        {ch.identifier || 'Social'}
                      </span>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>

        {/* Right Column: Safe Dry-Run Test Console */}
        <div className="creator-card">
          <div
            style={{
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'space-between',
              marginBottom: '0.75rem',
              paddingBottom: '0.75rem',
              borderBottom: '1px solid var(--border-color)',
            }}
          >
            <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
              <Shield size={16} color="var(--success)" />
              <h3 style={{ fontSize: '0.9375rem', fontWeight: 600, color: 'var(--text-primary)' }}>
                Dry-Run Simulation Console
              </h3>
            </div>
            <span
              style={{
                fontSize: '0.625rem',
                fontWeight: 700,
                padding: '2px 6px',
                borderRadius: '4px',
                backgroundColor: 'rgba(16, 185, 129, 0.15)',
                color: 'var(--success)',
                border: '1px solid rgba(16, 185, 129, 0.3)',
              }}
            >
              DRY RUN ONLY
            </span>
          </div>

          <p style={{ fontSize: '0.75rem', color: 'var(--text-muted)', marginBottom: '1rem', lineHeight: 1.4 }}>
            Test dispatch payloads against the PublishingAgent without releasing content to real social feeds.
          </p>

          <form onSubmit={handleDryRunPublish} style={{ display: 'flex', flexDirection: 'column', gap: '0.875rem' }}>
            <div>
              <label
                style={{
                  fontSize: '0.75rem',
                  fontWeight: 600,
                  color: 'var(--text-secondary)',
                  display: 'block',
                  marginBottom: '0.25rem',
                }}
              >
                Asset Storage Path *
              </label>
              <input
                type="text"
                value={assetPath}
                onChange={(e) => setAssetPath(e.target.value)}
                placeholder="videos/asset.mp4"
                style={{
                  width: '100%',
                  padding: '8px 10px',
                  borderRadius: '6px',
                  backgroundColor: 'var(--bg-primary)',
                  border: '1px solid var(--border-color)',
                  color: 'var(--text-primary)',
                  fontSize: '0.8125rem',
                  outline: 'none',
                }}
              />
            </div>

            <div>
              <label
                style={{
                  fontSize: '0.75rem',
                  fontWeight: 600,
                  color: 'var(--text-secondary)',
                  display: 'block',
                  marginBottom: '0.25rem',
                }}
              >
                Post Title
              </label>
              <input
                type="text"
                value={title}
                onChange={(e) => setTitle(e.target.value)}
                placeholder="Title of release"
                style={{
                  width: '100%',
                  padding: '8px 10px',
                  borderRadius: '6px',
                  backgroundColor: 'var(--bg-primary)',
                  border: '1px solid var(--border-color)',
                  color: 'var(--text-primary)',
                  fontSize: '0.8125rem',
                  outline: 'none',
                }}
              />
            </div>

            <div>
              <label
                style={{
                  fontSize: '0.75rem',
                  fontWeight: 600,
                  color: 'var(--text-secondary)',
                  display: 'block',
                  marginBottom: '0.25rem',
                }}
              >
                Caption & Description
              </label>
              <textarea
                value={caption}
                onChange={(e) => setCaption(e.target.value)}
                rows={2}
                placeholder="Post caption text"
                style={{
                  width: '100%',
                  padding: '8px 10px',
                  borderRadius: '6px',
                  backgroundColor: 'var(--bg-primary)',
                  border: '1px solid var(--border-color)',
                  color: 'var(--text-primary)',
                  fontSize: '0.8125rem',
                  outline: 'none',
                  resize: 'none',
                }}
              />
            </div>

            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '0.75rem' }}>
              <div>
                <label
                  style={{
                    fontSize: '0.75rem',
                    fontWeight: 600,
                    color: 'var(--text-secondary)',
                    display: 'block',
                    marginBottom: '0.25rem',
                  }}
                >
                  Platform
                </label>
                <select
                  value={socialPlatform}
                  onChange={(e) => setSocialPlatform(e.target.value)}
                  style={{
                    width: '100%',
                    padding: '8px 10px',
                    borderRadius: '6px',
                    backgroundColor: 'var(--bg-primary)',
                    border: '1px solid var(--border-color)',
                    color: 'var(--text-primary)',
                    fontSize: '0.8125rem',
                    outline: 'none',
                  }}
                >
                  <option value="youtube">YouTube Shorts</option>
                  <option value="tiktok">TikTok</option>
                  <option value="instagram">Instagram Reels</option>
                  <option value="x">X / Twitter</option>
                </select>
              </div>

              <div>
                <label
                  style={{
                    fontSize: '0.75rem',
                    fontWeight: 600,
                    color: 'var(--text-secondary)',
                    display: 'block',
                    marginBottom: '0.25rem',
                  }}
                >
                  Target Channel
                </label>
                <select
                  value={selectedChannelId}
                  onChange={(e) => setSelectedChannelId(e.target.value)}
                  style={{
                    width: '100%',
                    padding: '8px 10px',
                    borderRadius: '6px',
                    backgroundColor: 'var(--bg-primary)',
                    border: '1px solid var(--border-color)',
                    color: 'var(--text-primary)',
                    fontSize: '0.8125rem',
                    outline: 'none',
                  }}
                >
                  <option value="">Default / First Channel</option>
                  {status?.channels.map((ch, idx) => (
                    <option key={ch.id || idx} value={ch.id || ''}>
                      {ch.name || ch.identifier || `Channel ${idx + 1}`}
                    </option>
                  ))}
                </select>
              </div>
            </div>

            <button
              type="submit"
              disabled={isSimulating}
              className="btn-primary"
              style={{
                marginTop: '0.5rem',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                gap: '0.5rem',
                backgroundColor: 'var(--accent-hover)',
              }}
            >
              <Send size={14} className={isSimulating ? 'animate-spin' : ''} />
              <span>{isSimulating ? 'Validating Simulation...' : 'Simulate Release (Dry Run)'}</span>
            </button>
          </form>

          {/* Simulation Output */}
          {simulationError ? (
            <div
              style={{
                marginTop: '1rem',
                padding: '0.875rem',
                borderRadius: '6px',
                backgroundColor: 'rgba(239, 68, 68, 0.08)',
                border: '1px solid rgba(239, 68, 68, 0.3)',
                color: 'var(--danger)',
                fontSize: '0.75rem',
              }}
            >
              <div style={{ display: 'flex', alignItems: 'center', gap: '0.375rem', fontWeight: 600 }}>
                <XCircle size={14} />
                Simulation Failed
              </div>
              <p style={{ marginTop: '0.25rem' }}>{simulationError}</p>
            </div>
          ) : simulationResult ? (
            <div
              style={{
                marginTop: '1rem',
                padding: '0.875rem',
                borderRadius: '6px',
                backgroundColor: 'rgba(16, 185, 129, 0.08)',
                border: '1px solid rgba(16, 185, 129, 0.3)',
                fontSize: '0.75rem',
              }}
            >
              <div
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: '0.375rem',
                  color: 'var(--success)',
                  fontWeight: 600,
                  marginBottom: '0.5rem',
                }}
              >
                <FileCheck size={16} />
                Dry-Run Contract Passed
              </div>
              <div style={{ display: 'flex', flexDirection: 'column', gap: '0.25rem', color: 'var(--text-secondary)' }}>
                <span>
                  Status: <strong style={{ color: 'var(--text-primary)' }}>{simulationResult.publish_status}</strong>
                </span>
                <span>
                  Is Dry Run: <strong style={{ color: 'var(--success)' }}>Yes (Safe)</strong>
                </span>
                {simulationResult.published_content_id && (
                  <span>
                    Simulated Content ID: <code>{simulationResult.published_content_id}</code>
                  </span>
                )}
                {simulationResult.url && (
                  <span>
                    Destination URL: <code>{simulationResult.url}</code>
                  </span>
                )}
              </div>
            </div>
          ) : null}
        </div>
      </div>
    </div>
  );
};
