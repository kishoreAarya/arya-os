import React from 'react';
import { Sparkles, Key, CheckCircle2, RefreshCw } from 'lucide-react';
import { HealthStatus } from '../types/creator';
import { AppView } from '../types/dashboard';
import { AppNav } from './navigation/AppNav';

interface HeaderProps {
  health: HealthStatus;
  onOpenAuth: () => void;
  hasApiKey: boolean;
  onRefreshHistory: () => void;
  isRefreshingHistory?: boolean;
  activeView?: AppView;
  onViewChange?: (view: AppView) => void;
}

export const Header: React.FC<HeaderProps> = ({
  health,
  onOpenAuth,
  hasApiKey,
  onRefreshHistory,
  isRefreshingHistory,
  activeView,
  onViewChange,
}) => {
  const isHealthy = health.status === 'healthy';
  const isDegraded = health.status === 'degraded';

  const healthColor = isHealthy
    ? 'var(--success)'
    : isDegraded
    ? 'var(--warning)'
    : 'var(--danger)';

  const healthGlow = isHealthy
    ? 'var(--success-glow)'
    : isDegraded
    ? 'var(--warning-glow)'
    : 'var(--danger-glow)';

  return (
    <header
      style={{
        borderBottom: '1px solid var(--border-color)',
        backgroundColor: 'rgba(10, 14, 22, 0.88)',
        backdropFilter: 'blur(16px)',
        WebkitBackdropFilter: 'blur(16px)',
        padding: '0.5rem 1rem',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        gap: '0.5rem',
        position: 'sticky',
        top: 0,
        zIndex: 40,
        boxShadow: '0 4px 20px rgba(0, 0, 0, 0.5), inset 0 1px 0 rgba(255, 255, 255, 0.05)',
      }}
    >
      {/* Brand Identity & Command Indicator */}
      <div style={{ display: 'flex', alignItems: 'center', gap: '0.875rem' }}>
        <div
          style={{
            width: '36px',
            height: '36px',
            borderRadius: 'var(--radius-sm)',
            background: 'linear-gradient(135deg, #3b82f6 0%, #1d4ed8 100%)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            boxShadow: '0 2px 10px rgba(59, 130, 246, 0.4), inset 0 1px 0 rgba(255, 255, 255, 0.25)',
            border: '1px solid rgba(255, 255, 255, 0.15)',
          }}
        >
          <Sparkles size={19} color="#ffffff" />
        </div>
        <div>
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
            <h1
              style={{
                fontSize: '1.125rem',
                fontWeight: 700,
                letterSpacing: '-0.025em',
                color: 'var(--text-primary)',
              }}
            >
              AryaOS
            </h1>
            <span
              style={{
                fontSize: '0.6875rem',
                fontWeight: 700,
                backgroundColor: 'rgba(59, 130, 246, 0.12)',
                color: '#93c5fd',
                border: '1px solid rgba(59, 130, 246, 0.35)',
                borderRadius: '4px',
                padding: '1px 6px',
                letterSpacing: '0.04em',
                boxShadow: '0 0 8px rgba(59, 130, 246, 0.15)',
              }}
            >
              V1 CREATOR
            </span>
          </div>
          <p style={{ fontSize: '0.75rem', color: 'var(--text-muted)', letterSpacing: '-0.01em' }}>
            Cinematic AI Media Generation Studio
          </p>
        </div>
      </div>

      {/* Navigation Command Bar */}
      {activeView && onViewChange && (
        <div style={{ display: 'flex', justifyContent: 'center' }}>
          <AppNav activeView={activeView} onViewChange={onViewChange} />
        </div>
      )}

      {/* Telemetry & Global Controls */}
      <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
        {/* Backend health status badge */}
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: '0.5rem',
            fontSize: '0.75rem',
            padding: '5px 10px',
            borderRadius: 'var(--radius-sm)',
            backgroundColor: 'rgba(7, 10, 16, 0.85)',
            border: '1px solid var(--border-color)',
            boxShadow: 'inset 0 1px 2px rgba(0, 0, 0, 0.4)',
          }}
          title="FastAPI Backend Health Status"
        >
          <div
            style={{
              width: '7px',
              height: '7px',
              borderRadius: '50%',
              backgroundColor: healthColor,
              boxShadow: `0 0 8px ${healthGlow}`,
            }}
          />
          <span style={{ color: 'var(--text-secondary)', textTransform: 'capitalize', fontWeight: 500 }}>
            Backend: <strong style={{ color: isHealthy ? 'var(--text-primary)' : healthColor }}>{health.status}</strong>
          </span>
        </div>

        {/* Refresh History / Sync DB Button */}
        <button
          onClick={onRefreshHistory}
          className="btn-secondary"
          title="Refresh History from Database"
        >
          <RefreshCw size={13} className={isRefreshingHistory ? 'animate-spin' : ''} />
          <span>Sync DB</span>
        </button>

        {/* API Key configuration button */}
        <button
          onClick={onOpenAuth}
          className="btn-secondary"
          style={{
            borderColor: hasApiKey ? 'rgba(16, 185, 129, 0.4)' : 'var(--border-color)',
          }}
        >
          <Key size={13} color={hasApiKey ? 'var(--success)' : 'var(--text-muted)'} />
          <span>{hasApiKey ? 'API Key Set' : 'Configure API Key'}</span>
          {hasApiKey ? (
            <CheckCircle2 size={12} color="var(--success)" />
          ) : (
            <span
              style={{
                width: '6px',
                height: '6px',
                borderRadius: '50%',
                backgroundColor: 'var(--warning)',
                boxShadow: '0 0 6px var(--warning-glow)',
              }}
            />
          )}
        </button>
      </div>
    </header>
  );
};
