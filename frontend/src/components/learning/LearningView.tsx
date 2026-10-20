import React, { useEffect, useState } from 'react';
import {
  Brain,
  RefreshCw,
  AlertCircle,
  Sparkles,
  Info,
  CheckCircle,
  TrendingUp,
} from 'lucide-react';
import { fetchLearningFeedback } from '../../api/dashboardApi';
import { LearningFeedbackItem } from '../../types/dashboard';

const CATEGORIES = [
  { id: 'all', label: 'All Categories' },
  { id: 'topic', label: 'Topic & Trends' },
  { id: 'script', label: 'Script & Hook' },
  { id: 'thumbnail', label: 'Thumbnail' },
  { id: 'prompt', label: 'Visual Prompt' },
  { id: 'title', label: 'Video Title' },
];

const CONFIDENCE_LEVELS = [
  { value: 0, label: 'All Confidence (0%+)' },
  { value: 0.5, label: 'Moderate (50%+)' },
  { value: 0.7, label: 'High (70%+)' },
  { value: 0.85, label: 'Very High (85%+)' },
];

export const LearningView: React.FC = () => {
  const [feedbackItems, setFeedbackItems] = useState<LearningFeedbackItem[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Filters
  const [selectedCategory, setSelectedCategory] = useState('all');
  const [minConfidence, setMinConfidence] = useState(0);

  useEffect(() => {
    loadFeedback();
  }, [selectedCategory, minConfidence]);

  const loadFeedback = async () => {
    setIsLoading(true);
    setError(null);
    try {
      const data = await fetchLearningFeedback({
        category: selectedCategory === 'all' ? undefined : selectedCategory,
        minConfidence: minConfidence > 0 ? minConfidence : undefined,
      });
      setFeedbackItems(data);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Failed to fetch learning feedback';
      setError(msg);
    } finally {
      setIsLoading(false);
    }
  };

  const getCategoryColor = (cat: string) => {
    switch (cat.toLowerCase()) {
      case 'topic':
        return '#3b82f6';
      case 'script':
        return '#10b981';
      case 'thumbnail':
        return '#a855f7';
      case 'prompt':
        return '#f59e0b';
      case 'title':
        return '#06b6d4';
      default:
        return 'var(--accent-primary)';
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
          marginBottom: '1.25rem',
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
            <Brain size={22} color="var(--accent-primary)" />
            Learning Loop & Performance Intelligence
          </h2>
          <p style={{ fontSize: '0.8125rem', color: 'var(--text-muted)', marginTop: '0.25rem' }}>
            Empirical heuristics and feedback distilled from published video performance analytics.
          </p>
        </div>

        <button
          type="button"
          onClick={loadFeedback}
          disabled={isLoading}
          className="btn-secondary"
          style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}
        >
          <RefreshCw size={14} className={isLoading ? 'animate-spin' : ''} />
          <span>Refresh Feedback</span>
        </button>
      </div>

      {/* Instance-Wide Scope Disclaimer Banner */}
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: '0.75rem',
          padding: '0.875rem 1.25rem',
          borderRadius: '8px',
          backgroundColor: 'rgba(99, 102, 241, 0.08)',
          border: '1px solid rgba(99, 102, 241, 0.25)',
          marginBottom: '1.5rem',
          color: 'var(--text-primary)',
          fontSize: '0.8125rem',
        }}
        role="note"
      >
        <Info size={18} color="var(--accent-primary)" style={{ flexShrink: 0 }} />
        <div>
          <strong>Instance-Wide Scope Notice:</strong> Learning feedback is currently instance-wide in V1.
          Insights generated from any project or published run improve generation and validation parameters across all workflows.
        </div>
      </div>

      {/* Filter Bar */}
      <div
        className="creator-card"
        style={{
          padding: '1rem 1.25rem',
          marginBottom: '1.5rem',
          display: 'flex',
          flexWrap: 'wrap',
          alignItems: 'center',
          justifyContent: 'space-between',
          gap: '1rem',
        }}
      >
        {/* Category Pills */}
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: '0.5rem', alignItems: 'center' }}>
          <span style={{ fontSize: '0.75rem', color: 'var(--text-muted)', fontWeight: 600, marginRight: '0.25rem' }}>
            Category:
          </span>
          {CATEGORIES.map((cat) => {
            const isSelected = selectedCategory === cat.id;
            return (
              <button
                key={cat.id}
                type="button"
                onClick={() => setSelectedCategory(cat.id)}
                style={{
                  padding: '4px 10px',
                  borderRadius: '16px',
                  border: isSelected ? '1px solid var(--accent-primary)' : '1px solid var(--border-color)',
                  backgroundColor: isSelected ? 'rgba(99, 102, 241, 0.15)' : 'var(--bg-secondary)',
                  color: isSelected ? 'var(--accent-primary)' : 'var(--text-secondary)',
                  fontSize: '0.75rem',
                  fontWeight: isSelected ? 600 : 500,
                  cursor: 'pointer',
                  transition: 'all 0.15s ease',
                }}
              >
                {cat.label}
              </button>
            );
          })}
        </div>

        {/* Confidence Threshold */}
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
          <span style={{ fontSize: '0.75rem', color: 'var(--text-muted)', fontWeight: 600 }}>
            Min Confidence:
          </span>
          <select
            value={minConfidence}
            onChange={(e) => setMinConfidence(Number(e.target.value))}
            className="input-select"
            style={{
              padding: '4px 8px',
              fontSize: '0.75rem',
              backgroundColor: 'var(--bg-secondary)',
              color: 'var(--text-primary)',
              borderRadius: '6px',
              border: '1px solid var(--border-color)',
            }}
          >
            {CONFIDENCE_LEVELS.map((cl) => (
              <option key={cl.value} value={cl.value}>
                {cl.label}
              </option>
            ))}
          </select>
        </div>
      </div>

      {/* Main Feedback Content */}
      {isLoading && feedbackItems.length === 0 ? (
        <div style={{ padding: '3.5rem', textAlign: 'center', color: 'var(--text-muted)' }}>
          <RefreshCw size={24} className="animate-spin" style={{ margin: '0 auto 0.75rem' }} />
          <p style={{ fontSize: '0.875rem' }}>Querying learning repository feedback...</p>
        </div>
      ) : error ? (
        <div
          style={{
            padding: '2.5rem',
            textAlign: 'center',
            color: 'var(--danger)',
            backgroundColor: 'rgba(239, 68, 68, 0.05)',
            borderRadius: '8px',
            border: '1px solid rgba(239, 68, 68, 0.2)',
          }}
        >
          <AlertCircle size={28} style={{ margin: '0 auto 0.5rem' }} />
          <p style={{ fontSize: '0.875rem', fontWeight: 500 }}>{error}</p>
          <button
            type="button"
            onClick={loadFeedback}
            className="btn-secondary"
            style={{ marginTop: '1rem' }}
          >
            Retry
          </button>
        </div>
      ) : feedbackItems.length === 0 ? (
        <div
          className="creator-card"
          style={{
            padding: '3.5rem',
            textAlign: 'center',
            color: 'var(--text-muted)',
          }}
        >
          <Sparkles size={36} style={{ margin: '0 auto 0.75rem', opacity: 0.4 }} />
          <h3 style={{ fontSize: '1rem', fontWeight: 600, color: 'var(--text-secondary)' }}>
            No Learning Feedback Recorded
          </h3>
          <p style={{ fontSize: '0.8125rem', marginTop: '0.25rem', maxWidth: '480px', margin: '0.25rem auto 0' }}>
            As workflows complete and post-publish analytics accumulate, the Learning Loop automatically extracts reusable patterns and scores their predictive confidence.
          </p>
        </div>
      ) : (
        <div
          style={{
            display: 'grid',
            gridTemplateColumns: 'repeat(auto-fill, minmax(360px, 1fr))',
            gap: '1rem',
          }}
        >
          {feedbackItems.map((item) => {
            const confPct = Math.round((item.confidence ?? 0) * 100);
            const badgeColor = getCategoryColor(item.category);

            return (
              <div
                key={item.id}
                className="creator-card"
                style={{
                  padding: '1.25rem',
                  display: 'flex',
                  flexDirection: 'column',
                  justifyContent: 'space-between',
                  gap: '1rem',
                  position: 'relative',
                  borderLeft: `4px solid ${badgeColor}`,
                }}
              >
                <div>
                  {/* Card Top: Category and Status */}
                  <div
                    style={{
                      display: 'flex',
                      justifyContent: 'space-between',
                      alignItems: 'center',
                      marginBottom: '0.75rem',
                    }}
                  >
                    <span
                      style={{
                        fontSize: '0.6875rem',
                        fontWeight: 700,
                        textTransform: 'uppercase',
                        letterSpacing: '0.05em',
                        color: badgeColor,
                        padding: '2px 8px',
                        borderRadius: '4px',
                        backgroundColor: `${badgeColor}15`,
                      }}
                    >
                      {item.category}
                    </span>

                    {item.is_active ? (
                      <span
                        style={{
                          display: 'flex',
                          alignItems: 'center',
                          gap: '0.25rem',
                          fontSize: '0.6875rem',
                          color: 'var(--success)',
                          fontWeight: 600,
                        }}
                      >
                        <CheckCircle size={12} />
                        Active Rule
                      </span>
                    ) : (
                      <span
                        style={{
                          fontSize: '0.6875rem',
                          color: 'var(--text-muted)',
                        }}
                      >
                        Inactive
                      </span>
                    )}
                  </div>

                  {/* Insight Text */}
                  <p
                    style={{
                      fontSize: '0.875rem',
                      lineHeight: 1.5,
                      color: 'var(--text-primary)',
                      fontWeight: 500,
                    }}
                  >
                    {item.insight}
                  </p>
                </div>

                {/* Card Bottom: Confidence & Evidence Sample Size */}
                <div
                  style={{
                    paddingTop: '0.75rem',
                    borderTop: '1px solid var(--border-color)',
                    display: 'flex',
                    justifyContent: 'space-between',
                    alignItems: 'flex-end',
                  }}
                >
                  <div>
                    <span
                      style={{
                        fontSize: '0.6875rem',
                        color: 'var(--text-muted)',
                        display: 'block',
                      }}
                    >
                      Confidence Score
                    </span>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', marginTop: '2px' }}>
                      <span
                        style={{
                          fontSize: '0.9375rem',
                          fontWeight: 700,
                          color:
                            confPct >= 80
                              ? 'var(--success)'
                              : confPct >= 60
                              ? 'var(--warning)'
                              : 'var(--text-secondary)',
                        }}
                      >
                        {confPct}%
                      </span>
                      {/* Mini progress bar */}
                      <div
                        style={{
                          width: '60px',
                          height: '5px',
                          borderRadius: '3px',
                          backgroundColor: 'var(--bg-secondary)',
                          overflow: 'hidden',
                        }}
                      >
                        <div
                          style={{
                            width: `${confPct}%`,
                            height: '100%',
                            backgroundColor:
                              confPct >= 80
                                ? 'var(--success)'
                                : confPct >= 60
                                ? 'var(--warning)'
                                : 'var(--accent-primary)',
                          }}
                        />
                      </div>
                    </div>
                  </div>

                  <div style={{ textAlign: 'right' }}>
                    <span
                      style={{
                        fontSize: '0.6875rem',
                        color: 'var(--text-muted)',
                        display: 'block',
                      }}
                    >
                      Evidence Base
                    </span>
                    <span
                      style={{
                        fontSize: '0.75rem',
                        color: 'var(--text-secondary)',
                        fontWeight: 500,
                        display: 'flex',
                        alignItems: 'center',
                        gap: '0.25rem',
                        justifyContent: 'flex-end',
                      }}
                    >
                      <TrendingUp size={12} />
                      {item.based_on_video_count} {item.based_on_video_count === 1 ? 'video' : 'videos'}
                    </span>
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
};
