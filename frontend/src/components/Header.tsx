import React from 'react';
import { Sparkles, Key, CheckCircle2, AlertTriangle, RefreshCw } from 'lucide-react';
import { HealthStatus } from '../types/creator';

interface HeaderProps {
  health: HealthStatus;
  onOpenAuth: () => void;
  hasApiKey: boolean;
  onRefreshHistory: () => void;
  isRefreshingHistory?: boolean;
}

export const Header: React.FC<HeaderProps> = ({
  health,
  onOpenAuth,
  hasApiKey,
  onRefreshHistory,
  isRefreshingHistory,
}) => {
  return (
    <header style={{
      borderBottom: '1px solid var(--border-color)',
      backgroundColor: 'var(--bg-secondary)',
      padding: '0.875rem 1.5rem',
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'space-between',
    }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: '0.875rem' }}>
        <div style={{
          width: '36px',
          height: '36px',
          borderRadius: '8px',
          background: 'linear-gradient(135deg, #6366f1 0%, #8b5cf6 100%)',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          boxShadow: '0 2px 8px rgba(99, 102, 241, 0.4)'
        }}>
          <Sparkles size={20} color="#ffffff" />
        </div>
        <div>
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
            <h1 style={{ fontSize: '1.125rem', fontWeight: 700, letterSpacing: '-0.02em' }}>AryaOS</h1>
            <span style={{
              fontSize: '0.6875rem',
              fontWeight: 600,
              backgroundColor: 'rgba(99, 102, 241, 0.15)',
              color: '#a5b4fc',
              border: '1px solid rgba(99, 102, 241, 0.3)',
              borderRadius: '4px',
              padding: '1px 6px',
            }}>V1 CREATOR</span>
          </div>
          <p style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>
            Cinematic AI Media Generation Studio
          </p>
        </div>
      </div>

      <div style={{ display: 'flex', alignItems: 'center', gap: '1rem' }}>
        {/* Backend health status badge */}
        <div style={{
          display: 'flex',
          alignItems: 'center',
          gap: '0.375rem',
          fontSize: '0.75rem',
          padding: '4px 8px',
          borderRadius: '6px',
          backgroundColor: 'var(--bg-primary)',
          border: '1px solid var(--border-color)',
        }} title="FastAPI Backend Health Status">
          <div style={{
            width: '8px',
            height: '8px',
            borderRadius: '50%',
            backgroundColor: health.status === 'healthy' ? 'var(--success)' : health.status === 'degraded' ? 'var(--warning)' : 'var(--danger)',
            boxShadow: health.status === 'healthy' ? '0 0 6px var(--success)' : 'none',
          }} />
          <span style={{ color: 'var(--text-secondary)', textTransform: 'capitalize' }}>
            Backend: {health.status}
          </span>
        </div>

        {/* Refresh History Button */}
        <button
          onClick={onRefreshHistory}
          className="btn-secondary"
          title="Refresh History from Database"
        >
          <RefreshCw size={14} className={isRefreshingHistory ? 'animate-spin' : ''} />
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
          <Key size={14} color={hasApiKey ? 'var(--success)' : 'var(--text-muted)'} />
          <span>{hasApiKey ? 'API Key Set' : 'Configure API Key'}</span>
          {hasApiKey ? (
            <CheckCircle2 size={12} color="var(--success)" />
          ) : (
            <span style={{
              width: '6px',
              height: '6px',
              borderRadius: '50%',
              backgroundColor: 'var(--warning)',
            }} />
          )}
        </button>
      </div>
    </header>
  );
};
