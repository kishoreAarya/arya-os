import React from 'react';
import { History, Image as ImageIcon, Film, Clock, AlertCircle, CheckCircle2, ChevronRight, DollarSign } from 'lucide-react';
import { HistoryItem } from '../types/creator';

interface HistoryPanelProps {
  history: HistoryItem[];
  isLoading: boolean;
  onSelectItem: (item: HistoryItem) => void;
  selectedJobId?: string;
}

export const HistoryPanel: React.FC<HistoryPanelProps> = ({
  history,
  isLoading,
  onSelectItem,
  selectedJobId,
}) => {
  return (
    <div className="creator-card" style={{ marginTop: '1.5rem' }}>
      <div className="creator-card-header">
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
          <History size={18} color="var(--accent-primary)" />
          <span className="card-title">Generation History</span>
        </div>
        <span style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>
          {history.length} persistent {history.length === 1 ? 'generation' : 'generations'}
        </span>
      </div>

      {isLoading ? (
        <div style={{ padding: '2rem', textAlign: 'center', color: 'var(--text-muted)' }}>
          Loading persistent history from database...
        </div>
      ) : history.length === 0 ? (
        <div style={{
          padding: '2rem',
          textAlign: 'center',
          color: 'var(--text-muted)',
          fontSize: '0.875rem',
          border: '1px dashed var(--border-color)',
          borderRadius: 'var(--radius-md)',
        }}>
          No previous generations yet. Submit your first generation to begin building your factory catalog.
        </div>
      ) : (
        <div style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(auto-fill, minmax(280px, 1fr))',
          gap: '0.75rem',
          maxHeight: '360px',
          overflowY: 'auto',
          paddingRight: '4px',
        }} data-testid="history-list">
          {history.map((item) => {
            const isSelected = selectedJobId === item.job_id;
            const isVideo = item.generation_type === 'video' || item.generation_type === 'image_to_video';

            return (
              <div
                key={item.job_id}
                onClick={() => onSelectItem(item)}
                style={{
                  display: 'flex',
                  gap: '0.75rem',
                  padding: '0.75rem',
                  backgroundColor: isSelected ? 'rgba(99, 102, 241, 0.12)' : 'var(--bg-primary)',
                  border: `1px solid ${isSelected ? 'var(--accent-primary)' : 'var(--border-color)'}`,
                  borderRadius: 'var(--radius-md)',
                  cursor: 'pointer',
                  transition: 'all 0.15s ease',
                  alignItems: 'center',
                }}
                className="history-card"
                data-testid={`history-item-${item.job_id}`}
              >
                {/* Media thumbnail / icon */}
                <div style={{
                  width: '56px',
                  height: '56px',
                  borderRadius: 'var(--radius-sm)',
                  backgroundColor: 'var(--bg-card)',
                  overflow: 'hidden',
                  flexShrink: 0,
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                }}>
                  {item.asset_url && !isVideo ? (
                    <img
                      src={item.asset_url}
                      alt="Thumbnail"
                      style={{ width: '100%', height: '100%', objectFit: 'cover' }}
                      onError={(e) => {
                        (e.target as HTMLElement).style.display = 'none';
                      }}
                    />
                  ) : isVideo ? (
                    <Film size={22} color="var(--accent-primary)" />
                  ) : (
                    <ImageIcon size={22} color="var(--text-muted)" />
                  )}
                </div>

                {/* Info */}
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{
                    display: 'flex',
                    alignItems: 'center',
                    gap: '0.375rem',
                    marginBottom: '0.25rem',
                  }}>
                    <span style={{
                      fontSize: '0.6875rem',
                      fontWeight: 600,
                      textTransform: 'uppercase',
                      color: 'var(--text-secondary)',
                    }}>
                      {item.generation_type.replace(/_/g, ' ')}
                    </span>
                    <span style={{ fontSize: '0.625rem', color: 'var(--text-muted)' }}>•</span>
                    <span style={{ fontSize: '0.6875rem', color: 'var(--text-muted)' }}>
                      {item.aspect_ratio || '16:9'}
                    </span>
                    {item.status === 'completed' && (
                      <CheckCircle2 size={11} color="var(--success)" style={{ marginLeft: 'auto' }} />
                    )}
                    {item.status === 'failed' && (
                      <AlertCircle size={11} color="var(--danger)" style={{ marginLeft: 'auto' }} />
                    )}
                  </div>

                  <p style={{
                    fontSize: '0.8125rem',
                    fontWeight: 500,
                    color: 'var(--text-primary)',
                    overflow: 'hidden',
                    textOverflow: 'ellipsis',
                    whiteSpace: 'nowrap',
                    marginBottom: '0.25rem',
                  }}>
                    {item.prompt}
                  </p>

                  <div style={{
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'space-between',
                    fontSize: '0.6875rem',
                    color: 'var(--text-muted)',
                  }}>
                    <span>{item.model || 'Standard'}</span>
                    {item.total_cost_usd > 0 && (
                      <span style={{ color: 'var(--success)' }}>
                        ${item.total_cost_usd.toFixed(3)}
                      </span>
                    )}
                  </div>
                </div>

                <ChevronRight size={14} color="var(--text-muted)" />
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
};
