import React, { useState, useMemo } from 'react';
import {
  History,
  Image as ImageIcon,
  Film,
  CheckCircle2,
  AlertCircle,
  ChevronRight,
  Search,
  Filter,
  ArrowUpDown,
  Eye,
  RotateCcw,
  Sparkles,
} from 'lucide-react';
import { HistoryItem } from '../types/creator';
import {
  ProductionRun,
  HistoryFilterType,
  HistorySortOrder,
  historyItemToProductionRun,
  computeOperationalMetrics,
  filterAndSortRuns,
} from '../types/productionRun';
import { ProductionMetricsBar } from './history/ProductionMetricsBar';
import { RunDetailInspector } from './history/RunDetailInspector';

interface HistoryPanelProps {
  history: HistoryItem[];
  isLoading: boolean;
  onSelectItem: (item: HistoryItem) => void;
  selectedJobId?: string;
  onReproduce?: (run: ProductionRun) => void;
}

export const HistoryPanel: React.FC<HistoryPanelProps> = ({
  history,
  isLoading,
  onSelectItem,
  selectedJobId,
  onReproduce,
}) => {
  const [searchTerm, setSearchTerm] = useState('');
  const [filterType, setFilterType] = useState<HistoryFilterType>('all');
  const [sortOrder, setSortOrder] = useState<HistorySortOrder>('newest');
  const [inspectedRun, setInspectedRun] = useState<ProductionRun | null>(null);

  // Map history items to unified ProductionRun registry
  const productionRuns = useMemo(
    () => history.map(historyItemToProductionRun),
    [history]
  );

  // Compute operational metrics
  const metrics = useMemo(
    () => computeOperationalMetrics(productionRuns),
    [productionRuns]
  );

  // Filter and sort runs
  const visibleRuns = useMemo(
    () => filterAndSortRuns(productionRuns, searchTerm, filterType, sortOrder),
    [productionRuns, searchTerm, filterType, sortOrder]
  );

  const filterButtons: { id: HistoryFilterType; label: string }[] = [
    { id: 'all', label: 'All' },
    { id: 'image', label: 'Image' },
    { id: 'video', label: 'Video' },
    { id: 'image_to_video', label: 'Image → Video' },
    { id: 'completed', label: 'Completed' },
    { id: 'failed', label: 'Failed' },
    { id: 'processing', label: 'Processing' },
  ];

  return (
    <div className="creator-card" style={{ marginTop: '1.5rem' }}>
      {/* Panel Header */}
      <div className="creator-card-header">
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
          <History size={18} color="var(--accent-primary)" />
          <span className="card-title">Generation History</span>
        </div>
        <span style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>
          {history.length} persistent {history.length === 1 ? 'generation' : 'generations'}
        </span>
      </div>

      {/* Production Operational Metrics Bar */}
      {!isLoading && history.length > 0 && (
        <ProductionMetricsBar metrics={metrics} />
      )}

      {/* History Browser Controls: Search, Filter Chips, Sort Order */}
      {!isLoading && history.length > 0 && (
        <div
          style={{
            display: 'flex',
            flexWrap: 'wrap',
            alignItems: 'center',
            justifyContent: 'space-between',
            gap: '0.75rem',
            marginBottom: '1rem',
            padding: '0.75rem',
            backgroundColor: 'rgba(7, 10, 16, 0.65)',
            border: '1px solid rgba(255, 255, 255, 0.06)',
            borderRadius: 'var(--radius-sm, 4px)',
          }}
          data-testid="history-controls-bar"
        >
          {/* Search Input */}
          <div style={{ position: 'relative', flex: '1 1 240px', maxWidth: '380px' }}>
            <Search
              size={14}
              color="var(--text-muted)"
              style={{ position: 'absolute', left: '10px', top: '50%', transform: 'translateY(-50%)' }}
            />
            <input
              type="text"
              value={searchTerm}
              onChange={(e) => setSearchTerm(e.target.value)}
              placeholder="Search prompt, run ID, model, provider..."
              style={{
                width: '100%',
                padding: '6px 12px 6px 30px',
                fontSize: '0.8125rem',
                backgroundColor: 'rgba(3, 7, 18, 0.8)',
                border: '1px solid rgba(255, 255, 255, 0.1)',
                borderRadius: '4px',
                color: 'var(--text-primary)',
                outline: 'none',
              }}
              data-testid="history-search-input"
            />
          </div>

          {/* Filter Chips */}
          <div
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: '0.375rem',
              flexWrap: 'wrap',
            }}
            data-testid="history-filter-chips"
          >
            {filterButtons.map((btn) => {
              const isActive = filterType === btn.id;
              return (
                <button
                  key={btn.id}
                  type="button"
                  onClick={() => setFilterType(btn.id)}
                  style={{
                    padding: '4px 8px',
                    fontSize: '0.75rem',
                    borderRadius: '4px',
                    backgroundColor: isActive ? 'rgba(59, 130, 246, 0.2)' : 'transparent',
                    border: `1px solid ${isActive ? 'var(--accent-primary)' : 'rgba(255, 255, 255, 0.08)'}`,
                    color: isActive ? '#ffffff' : 'var(--text-muted)',
                    cursor: 'pointer',
                    transition: 'all 0.15s ease',
                  }}
                  data-testid={`history-filter-${btn.id}`}
                >
                  {btn.label}
                </button>
              );
            })}
          </div>

          {/* Sort Selector Button */}
          <button
            type="button"
            onClick={() => setSortOrder((prev) => (prev === 'newest' ? 'oldest' : 'newest'))}
            className="btn-secondary"
            style={{
              padding: '4px 8px',
              fontSize: '0.75rem',
              display: 'inline-flex',
              alignItems: 'center',
              gap: '4px',
            }}
            title="Toggle sort order"
            data-testid="history-sort-toggle"
          >
            <ArrowUpDown size={12} />
            <span>{sortOrder === 'newest' ? 'Newest First' : 'Oldest First'}</span>
          </button>
        </div>
      )}

      {/* Main Content Area */}
      {isLoading ? (
        <div style={{ padding: '2rem', textAlign: 'center', color: 'var(--text-muted)' }}>
          Loading persistent history from database...
        </div>
      ) : history.length === 0 ? (
        <div
          style={{
            padding: '2rem',
            textAlign: 'center',
            color: 'var(--text-muted)',
            fontSize: '0.875rem',
            border: '1px dashed var(--border-color)',
            borderRadius: 'var(--radius-md)',
          }}
        >
          No previous generations yet. Submit your first generation to begin building your factory catalog.
        </div>
      ) : visibleRuns.length === 0 ? (
        <div
          style={{
            padding: '2rem',
            textAlign: 'center',
            color: 'var(--text-muted)',
            fontSize: '0.875rem',
            border: '1px dashed var(--border-color)',
            borderRadius: 'var(--radius-md)',
          }}
          data-testid="history-no-matches"
        >
          No historical runs match the search or filter criteria.
        </div>
      ) : (
        <div
          style={{
            display: 'grid',
            gridTemplateColumns: 'repeat(auto-fill, minmax(290px, 1fr))',
            gap: '0.75rem',
            maxHeight: '360px',
            overflowY: 'auto',
            paddingRight: '4px',
          }}
          data-testid="history-list"
        >
          {visibleRuns.map((run, index) => {
            const isSelected = selectedJobId === run.jobId;
            const isVideo =
              run.mode === 'video' ||
              run.mode === 'image_to_video' ||
              Boolean(run.outputAsset && (run.outputAsset.includes('.mp4') || run.outputAsset.includes('video')));

            // Match back to original HistoryItem for onSelectItem compatibility
            const originalItem = history.find((h) => h.job_id === run.jobId) || {
              job_id: run.jobId,
              workflow_run_id: run.workflowRunId || run.id,
              generation_type: run.mode,
              prompt: run.prompt,
              model: run.model,
              provider: run.provider,
              aspect_ratio: run.parameters.aspectRatio,
              duration_seconds: run.parameters.durationSeconds,
              status: run.status,
              asset_url: run.outputAsset,
              total_cost_usd: run.cost || 0.0,
              created_at: run.createdAt,
              completed_at: run.completedAt,
              failure_reason: run.error,
            };

            return (
              <div
                key={run.jobId || run.id || `run-${index}`}
                onClick={() => onSelectItem(originalItem)}
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
                  position: 'relative',
                }}
                className="history-card"
                data-testid={`history-item-${run.jobId}`}
              >
                {/* Media thumbnail / icon */}
                <div
                  style={{
                    width: '56px',
                    height: '56px',
                    borderRadius: 'var(--radius-sm)',
                    backgroundColor: 'var(--bg-card)',
                    overflow: 'hidden',
                    flexShrink: 0,
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                  }}
                >
                  {run.outputAsset && !isVideo ? (
                    <img
                      src={run.outputAsset}
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
                  <div
                    style={{
                      display: 'flex',
                      alignItems: 'center',
                      gap: '0.375rem',
                      marginBottom: '0.25rem',
                    }}
                  >
                    <span
                      style={{
                        fontSize: '0.6875rem',
                        fontWeight: 600,
                        textTransform: 'uppercase',
                        color: 'var(--text-secondary)',
                      }}
                    >
                      {run.mode.replace(/_/g, ' ')}
                    </span>
                    <span style={{ fontSize: '0.625rem', color: 'var(--text-muted)' }}>•</span>
                    <span style={{ fontSize: '0.6875rem', color: 'var(--text-muted)' }}>
                      {run.parameters.aspectRatio || '16:9'}
                    </span>
                    {run.status === 'completed' && (
                      <CheckCircle2 size={11} color="var(--success)" style={{ marginLeft: 'auto' }} />
                    )}
                    {run.status === 'failed' && (
                      <AlertCircle size={11} color="var(--danger)" style={{ marginLeft: 'auto' }} />
                    )}
                  </div>

                  <p
                    style={{
                      fontSize: '0.8125rem',
                      fontWeight: 500,
                      color: 'var(--text-primary)',
                      overflow: 'hidden',
                      textOverflow: 'ellipsis',
                      whiteSpace: 'nowrap',
                      marginBottom: '0.25rem',
                    }}
                  >
                    {run.prompt}
                  </p>

                  <div
                    style={{
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'space-between',
                      fontSize: '0.6875rem',
                      color: 'var(--text-muted)',
                    }}
                  >
                    <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', maxWidth: '120px' }}>
                      {run.model || 'Standard'}
                    </span>
                    {run.cost && run.cost > 0 ? (
                      <span style={{ color: 'var(--success)' }}>
                        ${run.cost.toFixed(3)}
                      </span>
                    ) : null}
                  </div>
                </div>

                {/* Action buttons: Inspect details */}
                <div style={{ display: 'flex', alignItems: 'center', gap: '4px' }}>
                  <button
                    type="button"
                    onClick={(e) => {
                      e.stopPropagation();
                      setInspectedRun(run);
                    }}
                    title="Inspect Run Intelligence"
                    aria-label={`Inspect run ${run.jobId}`}
                    className="btn-secondary"
                    style={{
                      padding: '4px',
                      borderRadius: '4px',
                      color: 'var(--text-muted)',
                    }}
                    data-testid={`inspect-run-${run.jobId}`}
                  >
                    <Eye size={13} />
                  </button>
                  <ChevronRight size={14} color="var(--text-muted)" />
                </div>
              </div>
            );
          })}
        </div>
      )}

      {/* Run Detail Modal Inspector */}
      <RunDetailInspector
        isOpen={Boolean(inspectedRun)}
        run={inspectedRun}
        onClose={() => setInspectedRun(null)}
        onReproduce={(run) => {
          if (onReproduce) {
            onReproduce(run);
          }
        }}
        onInspectInViewport={(run) => {
          const orig = history.find((h) => h.job_id === run.jobId);
          if (orig) {
            onSelectItem(orig);
          }
        }}
      />
    </div>
  );
};
